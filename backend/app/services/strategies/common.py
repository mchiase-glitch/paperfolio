"""
Pezzi comuni alle strategie P3, P4 e P5: regioni con il loro indice, cambi, momentum, medie.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .base import StrategyContext

ZERO = Decimal("0")
ALL_LISTS = ["ftse_mib", "eurostoxx50", "sp100"]


@dataclass(frozen=True)
class Region:
    code: str          # mercato di quotazione: ITA / EUR / USA
    label: str
    index: str         # indice Yahoo usato per i segnali
    currency: str
    stocks: str        # lista di universo dei titoli della regione


REGIONS = {
    "ITA": Region("ITA", "FTSE MIB", "FTSEMIB.MI", "EUR", "ftse_mib"),
    "EUR": Region("EUR", "Euro Stoxx 50", "^STOXX50E", "EUR", "eurostoxx50"),
    "USA": Region("USA", "S&P 500", "^GSPC", "USD", "sp100"),
}

# Momentum 12-1: rendimento degli ultimi 12 mesi escluso l'ultimo, in giorni di borsa
MOM_LONG = 252
MOM_SKIP = 21


def fx_symbol(currency: str) -> str:
    """Cambio Yahoo: unità di valuta per 1 EUR (es. EURUSD=X ≈ 1,08)."""
    return f"EUR{currency}=X"


def fx_at(ctx: StrategyContext, currency: str, d: date) -> float | None:
    if currency == "EUR":
        return 1.0
    dates, closes, i = ctx.closes(fx_symbol(currency))
    j = min(bisect_right(dates, d) - 1, i)
    return closes[j] if j >= 0 else None


def close_on_or_before(ctx: StrategyContext, symbol: str, d: date) -> tuple[date, float] | None:
    dates, closes, i = ctx.closes(symbol)
    j = min(bisect_right(dates, d) - 1, i)
    return (dates[j], closes[j]) if j >= 0 else None


def return_eur(ctx: StrategyContext, symbol: str, currency: str, days: int = 365) -> float | None:
    """Rendimento in euro dell'ultimo anno (o di `days` giorni di calendario)."""
    target = ctx.today - timedelta(days=days)
    now = close_on_or_before(ctx, symbol, ctx.today)
    past = close_on_or_before(ctx, symbol, target)
    if now is None or past is None or (ctx.today - now[0]).days > 14 or (target - past[0]).days > 14:
        return None
    fx_now, fx_past = fx_at(ctx, currency, now[0]), fx_at(ctx, currency, past[0])
    if not fx_now or not fx_past or past[1] <= 0:
        return None
    return (now[1] / fx_now) / (past[1] / fx_past) - 1


def momentum_12_1(ctx: StrategyContext, symbol: str, currency: str) -> float | None:
    """Rendimento in euro da 12 mesi fa a 1 mese fa (si salta l'ultimo mese, che tende a invertirsi)."""
    dates, closes, i = ctx.closes(symbol)
    if i < MOM_LONG or (ctx.today - dates[i]).days > 14:
        return None
    a, b = i - MOM_LONG, i - MOM_SKIP
    fx_a, fx_b = fx_at(ctx, currency, dates[a]), fx_at(ctx, currency, dates[b])
    if not fx_a or not fx_b or closes[a] <= 0:
        return None
    return (closes[b] / fx_b) / (closes[a] / fx_a) - 1


def above_sma(ctx: StrategyContext, symbol: str, days: int = 200) -> tuple[bool, float, float] | None:
    """(chiusura sopra la media?, chiusura, media) per l'ultimo giorno disponibile."""
    _, closes, i = ctx.closes(symbol)
    if i + 1 < days:
        return None
    avg = sum(closes[i - days + 1:i + 1]) / days
    return closes[i] > avg, closes[i], avg


def pct(v: float | Decimal) -> str:
    return f"{float(v) * 100:.1f}%"
