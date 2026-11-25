"""
Cache dei prezzi storici giornalieri (non rettificati).

La cache è in SQLite (tabella price_history_cache).
yfinance viene interrogato solo per aggiornare i dati mancanti.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import NamedTuple

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import PriceHistoryCache

log = logging.getLogger("paperfolio.price_history")

# Scarica al massimo questo numero di anni di storico al primo download
MAX_YEARS_HISTORY = 20
# Pausa tra richieste yfinance per rispettare i rate limit
FETCH_DELAY_S = 0.5
# Giorni già in cache che si riscaricano a ogni aggiornamento
REFRESH_DAYS = 5


class DayRow(NamedTuple):
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None
    dividend: float
    split_ratio: float


# ── Fetch da yfinance ─────────────────────────────────────────────────────────

def fetch_history(db: Session, symbol: str, start: date | None = None) -> int:
    """
    Scarica lo storico da yfinance e lo salva nella cache.
    Se start=None usa l'ultimo dato in cache (aggiornamento incrementale)
    oppure scarica gli ultimi MAX_YEARS_HISTORY anni.
    Restituisce il numero di righe aggiunte.
    """
    if start is None:
        last = db.scalar(
            select(func.max(PriceHistoryCache.date))
            .where(PriceHistoryCache.symbol == symbol)
        )
        if last is not None:
            # Si riscaricano gli ultimi giorni: la barra di oggi letta a mercato aperto va corretta
            start = last - timedelta(days=REFRESH_DAYS)
        else:
            start = date.today() - timedelta(days=MAX_YEARS_HISTORY * 365)
    db.commit()  # nessun blocco sul database durante il download

    if start > date.today():
        return 0

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            start=start.isoformat(),
            end=(date.today() + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
    except Exception as exc:
        log.warning("fetch_history(%s): %s", symbol, exc)
        return 0

    if hist.empty:
        return 0

    # Normalizza i nomi delle colonne (yfinance a volte usa maiuscole/minuscole diverse)
    hist.columns = [str(c).strip() for c in hist.columns]
    close_col = next((c for c in hist.columns if c.lower() == "close"), None)
    if close_col is None:
        log.warning("fetch_history(%s): colonna Close non trovata", symbol)
        return 0

    split_col = next((c for c in hist.columns if "split" in c.lower()), None)
    div_col = next((c for c in hist.columns if "dividend" in c.lower()), None)
    open_col = next((c for c in hist.columns if c.lower() == "open"), None)
    high_col = next((c for c in hist.columns if c.lower() == "high"), None)
    low_col = next((c for c in hist.columns if c.lower() == "low"), None)
    vol_col = next((c for c in hist.columns if c.lower() == "volume"), None)

    def _num(row, col):
        if not col:
            return None
        v = float(row[col])
        return None if v != v else v  # NaN → None

    parsed: dict[date, dict] = {}
    for idx, row in hist.iterrows():
        close_val = _num(row, close_col)
        if close_val is None or close_val <= 0:
            continue
        split_val = _num(row, split_col) or 1.0
        vol = _num(row, vol_col)
        parsed[idx.date()] = dict(
            open=_num(row, open_col), high=_num(row, high_col), low=_num(row, low_col),
            close=close_val, volume=int(vol) if vol is not None else None,
            dividend=_num(row, div_col) or 0.0, split_ratio=split_val,
        )
    if not parsed:
        return 0

    existing = {
        r.date: r for r in db.scalars(
            select(PriceHistoryCache).where(
                PriceHistoryCache.symbol == symbol,
                PriceHistoryCache.date >= min(parsed), PriceHistoryCache.date <= max(parsed),
            )
        )
    }
    now = utcnow()
    added = 0
    for d, values in parsed.items():
        row = existing.get(d)
        if row is None:
            db.add(PriceHistoryCache(symbol=symbol, date=d, fetched_at=now, **values))
            added += 1
        else:
            for k, v in values.items():
                setattr(row, k, v)
            row.fetched_at = now
    db.commit()
    return added


def fetch_many(db: Session, symbols: list[str], start: date | None = None) -> dict[str, int]:
    """Aggiorna la cache per più simboli. Rispetta i rate limit con una pausa tra le richieste."""
    result = {}
    for sym in symbols:
        result[sym] = fetch_history(db, sym, start)
        time.sleep(FETCH_DELAY_S)
    return result


# ── Lettura dalla cache ───────────────────────────────────────────────────────

def get_rows(db: Session, symbol: str, start: date, end: date) -> list[DayRow]:
    """Legge dalla cache i dati tra start ed end (inclusi). Ordine crescente per data."""
    rows = db.scalars(
        select(PriceHistoryCache)
        .where(
            PriceHistoryCache.symbol == symbol,
            PriceHistoryCache.date >= start,
            PriceHistoryCache.date <= end,
        )
        .order_by(PriceHistoryCache.date)
    ).all()
    return [DayRow(r.date, r.open, r.high, r.low, r.close, r.volume, r.dividend, r.split_ratio)
            for r in rows]


def get_adjusted_closes(db: Session, symbol: str, start: date, end: date) -> list[tuple[date, float]]:
    """
    Chiusure comparabili nel tempo. Yahoo fornisce lo storico già rettificato per gli split
    (anche con auto_adjust=False: resta escluso solo l'effetto dei dividendi), quindi
    le chiusure in cache si usano così come sono.
    """
    return [(r.date, r.close) for r in get_rows(db, symbol, start, end)]


def has_enough_history(db: Session, symbol: str, min_days: int = 252) -> bool:
    """True se la cache ha almeno min_days righe per il simbolo."""
    count = db.scalar(
        select(func.count(PriceHistoryCache.id))
        .where(PriceHistoryCache.symbol == symbol)
    ) or 0
    return count >= min_days


def coverage_pct(db: Session, symbols: list[str], min_days: int = 252) -> float:
    """Percentuale di simboli con storia sufficiente (usata dall'interruttore di sicurezza)."""
    if not symbols:
        return 1.0
    ok = sum(1 for s in symbols if has_enough_history(db, s, min_days))
    return ok / len(symbols)
