"""
Endpoint dei backtest.

POST   /api/auto/{id}/backtest     – avvia un backtest con strategia e parametri del portafoglio
GET    /api/auto/{id}/backtests    – backtest fatti per quel portafoglio
GET    /api/backtest/{id}          – stato, avanzamento e risultati
GET    /api/backtest/{id}/trades   – operazioni simulate (a pagine)
DELETE /api/backtest/{id}          – elimina un backtest
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, BacktestRun, BacktestTrade, LedgerEntry, StrategyConfig
from ..services import backtest as backtest_svc
from ..services.money import eur

router = APIRouter(prefix="/api", tags=["backtest"])


class BacktestBody(BaseModel):
    start: date = backtest_svc.DEFAULT_START
    end: date | None = None
    split: date | None = None  # inizio del periodo di verifica
    initial_capital: Decimal | None = Field(default=None, gt=0)
    risk_free: Decimal = Field(default=Decimal("0.02"), ge=0, le=Decimal("0.2"))


def _run_dict(run: BacktestRun, with_results: bool = False) -> dict:
    params = json.loads(run.params_json)
    cls = backtest_svc.STRATEGY_CLASSES.get(run.strategy_type)
    out = {
        "universe_lists": cls(None, params).universe_lists() if cls else [],
        "id": run.id,
        "config_id": run.strategy_config_id,
        "strategy_type": run.strategy_type,
        "strategy_version": run.strategy_version,
        "params": json.loads(run.params_json),
        "start": run.start_date.isoformat(),
        "end": run.end_date.isoformat(),
        "split": run.split_date.isoformat() if run.split_date else None,
        "initial_capital": run.initial_capital,
        "status": run.status,
        "progress": run.progress,
        "message": run.message,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    results = json.loads(run.results_json) if run.results_json else None
    if with_results:
        out["results"] = results
    elif results:
        full = results["periods"]["full"]
        out["summary"] = {"cagr": full["strategy"]["cagr"], "max_drawdown": full["strategy"]["max_drawdown"],
                          "benchmark_cagr": (full.get("benchmark") or {}).get("cagr")}
    return out


def _initial_capital(db: Session, config_id: int) -> Decimal:
    account = db.scalar(select(Account).where(Account.strategy_config_id == config_id))
    if account is None:
        return Decimal("100000")
    first = db.scalar(select(LedgerEntry).where(LedgerEntry.account_id == account.id, LedgerEntry.kind == "deposit")
                      .order_by(LedgerEntry.ts, LedgerEntry.id))
    return first.cash_delta_eur if first else Decimal("100000")


@router.post("/auto/{config_id}/backtest", status_code=201)
def start_backtest(config_id: int, body: BacktestBody, db: Session = Depends(get_db)):
    cfg = db.get(StrategyConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "Portafoglio automatico non trovato")
    if cfg.strategy_type not in backtest_svc.STRATEGY_CLASSES:
        raise HTTPException(400, f"Backtest non disponibile per {cfg.strategy_type}")
    end = body.end or date.today()
    if body.start >= end:
        raise HTTPException(400, "La data di inizio deve precedere quella di fine")
    if body.split is not None and not (body.start < body.split < end):
        raise HTTPException(400, "L'inizio del periodo di verifica deve cadere dentro il periodo del backtest")
    params = json.loads(cfg.params_json) if cfg.params_json else {}
    params["risk_free"] = float(body.risk_free)
    capital = eur(body.initial_capital or _initial_capital(db, config_id))
    run = backtest_svc.create_run(db, cfg.strategy_type, params, body.start, end, capital, body.split, cfg.id)
    return _run_dict(run)


@router.get("/auto/{config_id}/backtests")
def list_backtests(config_id: int, db: Session = Depends(get_db)):
    runs = db.scalars(select(BacktestRun).where(BacktestRun.strategy_config_id == config_id)
                      .order_by(BacktestRun.id.desc()).limit(20)).all()
    return [_run_dict(r) for r in runs]


def _get(db: Session, run_id: int) -> BacktestRun:
    run = db.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(404, "Backtest non trovato")
    return run


@router.get("/backtest/{run_id}")
def get_backtest(run_id: int, db: Session = Depends(get_db)):
    run = _get(db, run_id)
    out = _run_dict(run, with_results=True)
    if run.strategy_config_id:
        cfg = db.get(StrategyConfig, run.strategy_config_id)
        out["config_name"] = cfg.name if cfg else None
    out["queue_position"] = (db.scalar(select(func.count(BacktestRun.id)).where(
        BacktestRun.status == "queued", BacktestRun.id < run.id)) or 0) if run.status == "queued" else None
    return out


@router.get("/backtest/{run_id}/trades")
def get_trades(run_id: int, offset: int = 0, limit: int = 50, side: str | None = None,
               db: Session = Depends(get_db)):
    _get(db, run_id)
    q = select(BacktestTrade).where(BacktestTrade.run_id == run_id)
    if side:
        q = q.where(BacktestTrade.side == side)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(BacktestTrade.day, BacktestTrade.id).offset(offset).limit(min(limit, 200))).all()
    return {"total": total, "items": [{
        "day": t.day.isoformat(), "symbol": t.symbol, "side": t.side, "quantity": t.quantity, "price": t.price,
        "currency": t.currency, "gross_eur": t.gross_eur, "costs_eur": t.costs_eur, "tax_eur": t.tax_eur,
        "cash_delta_eur": t.cash_delta_eur, "realized_eur": t.realized_eur, "reason": t.reason,
    } for t in rows]}


@router.delete("/backtest/{run_id}", status_code=204)
def delete_backtest(run_id: int, db: Session = Depends(get_db)):
    run = _get(db, run_id)
    if run.status in ("queued", "running"):
        raise HTTPException(400, "Il backtest è ancora in corso")
    db.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run_id))
    db.delete(run)
    db.commit()
