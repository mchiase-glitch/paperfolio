"""
Dati di bilancio per P6 (valore + qualità), scaricati da Yahoo Finance e tenuti in cache.

Yahoo dà solo gli ultimi bilanci, non quelli com'erano negli anni passati: per questo
P6 funziona solo dal vivo e non ha backtest.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import Fundamentals

log = logging.getLogger("paperfolio.fundamentals")

MAX_AGE_DAYS = 45  # oltre si riscaricano prima dell'esecuzione annuale


def _first(df, *names) -> float | None:
    """Valore più recente della prima riga disponibile tra quelle indicate."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in names:
        if name in df.index:
            s = df.loc[name].dropna()
            if len(s):
                return float(s.iloc[0])
    return None


def download(symbol: str) -> dict:
    """Interroga la fonte. Solleva un'eccezione se non risponde."""
    t = yf.Ticker(symbol)
    info = t.info or {}
    inc, bs = t.income_stmt, t.balance_sheet
    return {
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "financial_currency": info.get("financialCurrency"),
        "enterprise_value": info.get("enterpriseValue"),
        "ebit": _first(inc, "EBIT", "Operating Income"),
        "gross_profit": _first(inc, "Gross Profit"),
        "total_assets": _first(bs, "Total Assets"),
        "current_assets": _first(bs, "Current Assets"),
        "current_liabilities": _first(bs, "Current Liabilities"),
        "net_ppe": _first(bs, "Net PPE"),
    }


def refresh(db: Session, symbol: str) -> dict | None:
    try:
        data = download(symbol)
    except Exception as exc:  # noqa: BLE001 - un titolo senza dati resta escluso
        log.warning("Bilancio di %s non disponibile: %s", symbol, exc)
        return None
    row = db.get(Fundamentals, symbol)
    if row is None:
        db.add(Fundamentals(symbol=symbol, fetched_at=utcnow(), data_json=json.dumps(data)))
    else:
        row.data_json, row.fetched_at = json.dumps(data), utcnow()
    db.commit()
    return data


def get(db: Session, symbol: str) -> dict | None:
    row = db.get(Fundamentals, symbol)
    return json.loads(row.data_json) if row else None


def stale(db: Session, symbols: list[str], max_age_days: int = MAX_AGE_DAYS) -> list[str]:
    """Titoli senza dati di bilancio o con dati più vecchi di max_age_days."""
    limit = utcnow() - timedelta(days=max_age_days)
    fresh = set(db.scalars(select(Fundamentals.symbol).where(Fundamentals.symbol.in_(symbols),
                                                             Fundamentals.fetched_at >= limit)))
    return [s for s in symbols if s not in fresh]


def sectors(db: Session, symbols: list[str]) -> dict[str, str]:
    """Settore (classificazione Yahoo) dei titoli che lo hanno in cache. Il settore cambia di rado:
    va bene anche un dato non recente."""
    out = {}
    for row in db.scalars(select(Fundamentals).where(Fundamentals.symbol.in_(symbols))):
        sector = json.loads(row.data_json).get("sector")
        if sector:
            out[row.symbol] = sector
    return out


def coverage(db: Session, symbols: list[str]) -> float:
    if not symbols:
        return 1.0
    have = set(db.scalars(select(Fundamentals.symbol).where(Fundamentals.symbol.in_(symbols))))
    return len(have) / len(symbols)
