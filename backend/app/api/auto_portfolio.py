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
    "P3": {"etf_share": 0.5, "n_stocks": 10, "abs_threshold": 0.0, "refuge": "bond", "rebalance_band": 0.2,
           "etf_ita": "IMIB.MI", "etf_eur": "MSE.MI", "etf_usa": "IUSA.MI", "etf_refuge": "XGLE.MI"},
    "P4": {"n_hold": 10, "keep_rank": 20, "trend_days": 200},
    "P5": {"max_positions": 5, "rsi_entry": 10, "max_days": 10, "sma_long": 200, "sma_exit": 5},
    "P6": {"n_hold": 15, "rebalance_month": 4, "exclude": ["banks", "insurance", "utilities"], "rebalance_band": 0.2},
    "P7": {"rebalance_month": 1, "max_weight": 0.10},
}
# Parametri comuni a tutte le strategie (valgono anche se non salvati: sono i predefiniti delle strategie)
COMMON_DEFAULTS: dict = {"min_order": 2500, "drawdown_brake": True}
# Strategie che lavorano sulle tre liste insieme: la lista non si sceglie
MULTI_LIST = {"P3", "P4", "P5", "P6", "P7"}

# Regole di validazione dei parametri modificabili
FRACTIONS = {"rebalance_band", "etf_share", "max_weight"}   # quote tra 0 e 1
CHOICES = {"refuge": {"bond", "cash"}}
LIST_CHOICES = {"exclude": {"banks", "insurance", "utilities"}}
PERCENT_RANGE = {"abs_threshold": (-1.0, 1.0)}


NOT_EDITABLE = {"etf_ita", "etf_eur", "etf_usa", "etf_refuge"}  # cambiarli richiederebbe nuovi dati e strumenti


def editable_defaults(strategy_type: str) -> dict:
    base = {k: v for k, v in STRATEGY_DEFAULTS.get(strategy_type, {}).items() if k not in NOT_EDITABLE}
    return {**base, **COMMON_DEFAULTS}


def _coerce_param(key: str, value, default):
    """Converte e controlla un parametro modificato dall'utente, con lo stesso tipo del predefinito."""
    bad = HTTPException(400, f"Valore non valido per {key}: {value!r}")
    try:
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise bad
            return value
        if isinstance(default, int):
            v = int(value)
            if v != float(value) or v < (1 if key != "min_order" else 0):
                raise bad
            if key == "rebalance_month" and not 1 <= v <= 12:
                raise bad
            return v
        if isinstance(default, float):
            v = float(value)
            lo, hi = PERCENT_RANGE.get(key, (0.0, 1.0 if key in FRACTIONS else float("inf")))
            if not lo <= v <= hi or (key == "max_weight" and v == 0):
                raise bad
            return v
        if isinstance(default, list):
            if not isinstance(value, list) or not set(value) <= LIST_CHOICES.get(key, set(value)):
                raise bad
            return list(value)
        v = str(value).strip()
        if not v or (key in CHOICES and v not in CHOICES[key]):
            raise bad
        return v
    except (TypeError, ValueError):
        raise bad from None


def _p7_sleeves(params: dict, universe_list: str | None) -> list[dict]:
    """Quote di P7: strategie scelte (default P2 e P4) in parti uguali, ognuna con i suoi parametri predefiniti."""
    sleeves = params.get("sleeves") or [{"type": t} for t in ("P2", "P4")]
    out = []
    for s in sleeves:
        t = s.get("type")
        if t not in STRATEGY_DEFAULTS or t == "P7":
            raise HTTPException(400, f"Strategia non valida nel portafoglio combinato: {t}")
        p = {**STRATEGY_DEFAULTS[t], **(s.get("params") or {})}
        if t not in MULTI_LIST:
            p.setdefault("universe_list", universe_list or "ftse_mib")
        out.append({"type": t, "share": float(s.get("share") or 1), "params": p})
    total = sum(s["share"] for s in out)
    for s in out:
        s["share"] = round(s["share"] / total, 6)
    return out


class CreateAutoBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    strategy_type: str = Field(..., pattern=r"^P[1-9]$")
    universe_list: str | None = None
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
    strategy = auto_portfolio.make_strategy(cfg)
    ss = auto_portfolio.strategy_symbols(db, strategy) if strategy else None
    pending = 0
    if account:
        pending = len(db.scalars(select(Order.id).where(Order.account_id == account.id,
                                                       Order.status == "pending")).all())
    nxt = auto_portfolio.next_check(db, cfg, strategy) if strategy else None
    return {
        "data_ready_pct": round(min(auto_portfolio.ready_pct(db, ss.tradeable, ss.reference),
                                    auto_portfolio.fundamentals_ready(db, strategy, ss)) * 100) if ss else 0,
        "preparation": auto_portfolio.preparation_status(auto_portfolio.preparation_key(ss, strategy)) if ss else None,
        "backtest_unavailable": strategy.backtest_unavailable if strategy else None,
        "universe_lists": strategy.universe_lists() if strategy else [],
        "session": auto_portfolio.strategy_region(strategy) if strategy else None,
        "positions_count": len(positions_svc.open_positions(db, account.id)) if account else 0,
        "pending_orders": pending,
        "id": cfg.id,
        "name": cfg.name,
        "strategy_type": cfg.strategy_type,
        "params": params,
        "defaults": editable_defaults(cfg.strategy_type),
        "next_check": nxt.isoformat() if nxt else None,
        "performance": auto_portfolio.live_performance(db, account, strategy) if account and strategy else None,
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

    multi = body.strategy_type in MULTI_LIST
    if not multi and (not body.universe_list or universes.get_list(db, body.universe_list) is None):
        raise HTTPException(400, f"Universo '{body.universe_list}' non trovato")

    try:
        # Parametri predefiniti + quelli scelti; le strategie su una sola lista ricordano quale
        defaults = STRATEGY_DEFAULTS.get(body.strategy_type, {})
        merged_params = {**defaults, **body.params}
        if not multi:
            merged_params["universe_list"] = body.universe_list
        if body.strategy_type == "P7":
            merged_params["sleeves"] = _p7_sleeves(body.params, body.universe_list)

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
        strategy = auto_portfolio.make_strategy(cfg)
        auto_portfolio.start_preparation(auto_portfolio.strategy_symbols(db, strategy), strategy.needs_fundamentals)
        return _config_dict(db, cfg, account)
    except HTTPException:
        db.rollback()
        raise
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


class ParamsBody(BaseModel):
    params: dict = Field(default_factory=dict)
    reset: bool = False                       # "ripristina default"
    sleeve_shares: list[float] | None = None  # P7: quote delle strategie, nello stesso ordine


@router.patch("/auto/{config_id}/params")
def update_params(config_id: int, body: ParamsBody, db: Session = Depends(get_db)):
    """Modifica i parametri (valgono dal prossimo controllo). Elenco dei titoli e strategie di P7 non si cambiano."""
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    current = json.loads(cfg.params_json) if cfg.params_json else {}
    defaults = editable_defaults(cfg.strategy_type)
    if body.reset:
        new = {**current, **defaults}
        if "sleeves" in new:
            for s in new["sleeves"]:
                s["share"] = round(1 / len(new["sleeves"]), 6)
    else:
        unknown = set(body.params) - set(defaults)
        if unknown:
            raise HTTPException(400, f"Parametri non modificabili: {', '.join(sorted(unknown))}")
        new = {**current, **{k: _coerce_param(k, v, defaults[k]) for k, v in body.params.items()}}
        if body.sleeve_shares is not None:
            sleeves = new.get("sleeves") or []
            if len(body.sleeve_shares) != len(sleeves) or any(x <= 0 for x in body.sleeve_shares):
                raise HTTPException(400, "Quote non valide: servono valori positivi, una per strategia")
            tot = sum(body.sleeve_shares)
            for s, x in zip(sleeves, body.sleeve_shares):
                s["share"] = round(x / tot, 6)
    if "keep_rank" in new and "n_hold" in new and new["keep_rank"] < new["n_hold"]:
        raise HTTPException(400, "Il posto fino a cui si tengono i titoli non può essere prima del numero di titoli")
    cfg.params_json = json.dumps(new)
    db.commit()
    account = db.scalar(select(Account).where(Account.strategy_config_id == config_id))
    return _config_dict(db, cfg, account)


@router.patch("/auto/{config_id}/pause")
def toggle_pause(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    cfg.is_paused = 0 if cfg.is_paused else 1
    db.commit()
    return {"id": cfg.id, "is_paused": bool(cfg.is_paused)}
