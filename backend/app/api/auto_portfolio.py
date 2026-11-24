"""
Endpoint REST per i portafogli automatici.

GET  /api/auto                    – lista di tutti i portafogli automatici
POST /api/auto                    – crea una nuova strategia + portafoglio
GET  /api/auto/{id}               – dettaglio portafoglio automatico
PATCH /api/auto/{id}              – modifica parametri
DELETE /api/auto/{id}             – elimina (solo se senza ordini eseguiti)
GET  /api/auto/{id}/runs          – ultimi run (decisioni incluse)
POST /api/auto/{id}/run_now       – "Prova ora" (dry-run)
POST /api/auto/{id}/run_live      – esegui ora (live)
PATCH /api/auto/{id}/pause        – metti in pausa / riprendi
GET  /api/universes               – lista degli universi disponibili
GET  /api/universes/{name}/items  – titoli di un universo
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db, utcnow
from ..models import Account, Order, StrategyConfig, StrategyDecision, StrategyRun
from ..services import auto_portfolio, portfolio as portfolio_svc, universes
from ..services import positions as positions_svc
from ..services.money import eur

router = APIRouter(prefix="/api", tags=["automatici"])

STRATEGY_DEFAULTS: dict[str, dict] = {
    "P1": {"rebalance_band": 0.25},
    "P2": {"sma_months": 10},
}


class CreateAutoBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    strategy_type: str = Field(..., pattern=r"^P[1-9]$")
    universe_list: str = Field(..., min_length=1)
    initial_capital: Decimal = Field(..., gt=0)
    params: dict = Field(default_factory=dict)


# ── Universi ──────────────────────────────────────────────────────────────────

@router.get("/universes")
def list_universes(db: Session = Depends(get_db)):
    return [
        {"name": lst.name, "label": lst.label, "source": lst.source,
         "updated_at": lst.updated_at.isoformat() if lst.updated_at else None}
        for lst in universes.get_all_lists(db)
    ]


@router.get("/universes/{name}/items")
def get_universe_items(name: str, db: Session = Depends(get_db)):
    items = universes.get_items(db, name)
    if not items and universes.get_list(db, name) is None:
        raise HTTPException(404, f"Universo '{name}' non trovato")
    return [{"symbol": i.symbol, "name": i.name, "isin": i.isin} for i in items]


# ── Portafogli automatici ─────────────────────────────────────────────────────

def _config_dict(db: Session, cfg: StrategyConfig, account: Account | None) -> dict:
    params = json.loads(cfg.params_json) if cfg.params_json else {}
    universe_list = params.get("universe_list") or ""
    symbols = universes.get_symbols(db, [universe_list])
    pending = 0
    if account:
        pending = len(db.scalars(select(Order.id).where(Order.account_id == account.id,
                                                       Order.status == "pending")).all())
    return {
        "data_ready_pct": round(auto_portfolio.ready_pct(db, symbols) * 100),
        "preparation": auto_portfolio.preparation_status(universe_list),
        "positions_count": len(positions_svc.open_positions(db, account.id)) if account else 0,
        "pending_orders": pending,
        "id": cfg.id,
        "name": cfg.name,
        "strategy_type": cfg.strategy_type,
        "params": params,
        "is_paused": bool(cfg.is_paused),
        "is_drawdown_braking": bool(cfg.is_drawdown_braking),
        "created_at": cfg.created_at.isoformat(),
        "account_id": account.id if account else None,
        "account_name": account.name if account else None,
        "cash_balance": str(positions_svc.cash_balance(db, account.id)) if account else None,
    }


@router.get("/auto")
def list_auto_portfolios(db: Session = Depends(get_db)):
    configs = db.scalars(select(StrategyConfig).order_by(StrategyConfig.id)).all()
    result = []
    for cfg in configs:
        account = db.scalar(select(Account).where(Account.strategy_config_id == cfg.id))
        result.append(_config_dict(db, cfg, account))
    return result


@router.post("/auto", status_code=201)
def create_auto_portfolio(body: CreateAutoBody, db: Session = Depends(get_db)):
    """Crea una nuova strategia automatica con il portafoglio collegato."""
    import json as _json, traceback
    if body.strategy_type not in auto_portfolio.STRATEGY_CLASSES:
        raise HTTPException(400, f"Tipo strategia '{body.strategy_type}' non supportato")

    if universes.get_list(db, body.universe_list) is None:
        raise HTTPException(400, f"Universo '{body.universe_list}' non trovato")

    try:
        # Merge defaults + params utente; aggiungi sempre universe_list
        defaults = STRATEGY_DEFAULTS.get(body.strategy_type, {})
        merged_params = {**defaults, **body.params, "universe_list": body.universe_list}

        cfg = StrategyConfig(
            name=body.name,
            strategy_type=body.strategy_type,
            params_json=_json.dumps(merged_params),
            is_paused=0,
            is_drawdown_braking=0,
            created_at=utcnow(),
        )
        db.add(cfg)
        db.flush()

        account = portfolio_svc.open_account(
            db,
            capital=eur(body.initial_capital),
            now=utcnow(),
            name=body.name,
            set_current=False,
        )
        account.strategy_config_id = cfg.id
        db.commit()
        db.refresh(cfg)
        db.refresh(account)
        auto_portfolio.start_preparation(body.universe_list)
        return _config_dict(db, cfg, account)
    except Exception as exc:
        db.rollback()
        tb = traceback.format_exc()
        raise HTTPException(500, f"{exc}\n\n{tb}")


@router.get("/auto/{config_id}")
def get_auto_portfolio(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    account = db.scalar(select(Account).where(Account.strategy_config_id == config_id))
    return _config_dict(db, cfg, account)


@router.get("/auto/{config_id}/runs")
def get_auto_runs(config_id: int, limit: int = 20, db: Session = Depends(get_db)):
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    runs = db.scalars(
        select(StrategyRun)
        .where(StrategyRun.strategy_config_id == config_id)
        .order_by(StrategyRun.ran_at.desc())
        .limit(limit)
    ).all()
    result = []
    for run in runs:
        decisions = db.scalars(
            select(StrategyDecision).where(StrategyDecision.run_id == run.id)
            .order_by(StrategyDecision.id)
        ).all()
        result.append({
            "id": run.id,
            "run_key": run.run_key,
            "ran_at": run.ran_at.isoformat(),
            "is_dry_run": bool(run.is_dry_run),
            "status": run.status,
            "note": run.note,
            "decisions": [
                {
                    "symbol": d.symbol,
                    "action": d.action,
                    "reason_it": d.reason_it,
                    "order_id": d.order_id,
                    "signal_data": json.loads(d.signal_data_json) if d.signal_data_json else {},
                }
                for d in decisions
            ],
        })
    return result


@router.post("/auto/{config_id}/run_now")
def run_now_dry(config_id: int, db: Session = Depends(get_db)):
    """Prova ora (dry-run): genera le decisioni senza piazzare ordini."""
    import traceback
    from datetime import date
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    today = date.today()
    try:
        result = auto_portfolio.run_strategy(db, cfg, is_dry_run=True, today=today)
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{exc}\n\n{tb}")
    return result


@router.post("/auto/{config_id}/run_live")
def run_now_live(config_id: int, db: Session = Depends(get_db)):
    """Esegui ora (live): genera le decisioni e piazza gli ordini reali."""
    import traceback
    from datetime import date
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    today = date.today()
    try:
        result = auto_portfolio.run_strategy(db, cfg, is_dry_run=False, today=today)
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{exc}\n\n{tb}")
    return result


@router.patch("/auto/{config_id}/pause")
def toggle_pause(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    cfg.is_paused = 0 if cfg.is_paused else 1
    db.commit()
    return {"id": cfg.id, "is_paused": bool(cfg.is_paused)}
