"""
P2 – Trend following mensile (Faber 10 mesi).

Regola: l'ultimo giorno di borsa del mese, per ogni titolo dell'universo:
  - Se chiusura mensile > SMA(10 mesi): tieni/compra (peso uguale)
  - Se chiusura mensile < SMA(10 mesi): vendi e vai in cash

In caso di drawdown brake: non fare nuovi acquisti.

I prezzi della cache sono già rettificati per gli split dalla fonte (Yahoo):
non vanno rettificati una seconda volta.

Parametri (params_json della StrategyConfig):
  universe_list: nome della lista universo (es. "eurostoxx50")
  sma_months: lunghezza SMA mensile (default 10)
  min_history_days: storia minima richiesta per un titolo (default 300)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from ..indicators import last_monthly_close, monthly_sma
from .base import BaseStrategy, Decision, StrategyContext, UniversePrice

log = logging.getLogger("paperfolio.p2")

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_SMA_MONTHS = 10
DEFAULT_MIN_HISTORY = 300  # ~14 mesi di dati per avere almeno 10 chiusure mensili


class P2Trend(BaseStrategy):
    """P2: trend following mensile Faber a 10 mesi."""

    @property
    def frequency(self) -> str:
        return "monthly"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        """Gira l'ultimo giorno di borsa del mese."""
        if next_day is not None:
            return next_day.month != today.month
        return _is_last_trading_day_of_month(today)

    def generate_decisions(
        self,
        ctx: StrategyContext,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
    ) -> list[Decision]:
        sma_months = int(self._param("sma_months", DEFAULT_SMA_MONTHS))
        min_history = int(self._param("min_history_days", DEFAULT_MIN_HISTORY))
        end = ctx.today
        start = end - timedelta(days=(sma_months + 3) * 31)

        available = [up for up in universe_prices if up.available and up.price > ZERO]
        if not available:
            return []

        bullish: list[tuple[UniversePrice, float, float]] = []
        others: list[Decision] = []
        order: list[str] = []

        for up in available:
            order.append(up.symbol)
            if ctx.history_count(up.symbol) < min_history:
                others.append(Decision(
                    up.symbol, "skip", None,
                    f"Storia insufficiente per calcolare SMA({sma_months} mesi): skip",
                    {"min_history": min_history},
                ))
                continue

            rows = ctx.history(up.symbol, start, end)
            dates = [r.date for r in rows]
            closes = [r.close for r in rows]
            sma_val = monthly_sma(dates, closes, sma_months) if rows else None
            last_close = last_monthly_close(dates, closes) if rows else None

            if sma_val is None or last_close is None:
                others.append(Decision(
                    up.symbol, "skip", None,
                    f"Dati insufficienti per SMA({sma_months} mesi): skip",
                    {"last_close": last_close, "sma": sma_val},
                ))
            elif last_close > sma_val:
                bullish.append((up, last_close, sma_val))
            else:
                held = ctx.quantity(up.symbol) > ZERO
                others.append(Decision(
                    up.symbol, "sell" if held else "hold", ZERO if held else None,
                    f"Chiusura mensile {last_close:.2f} < SMA({sma_months}) {sma_val:.2f}: "
                    + ("segnale ribassista, vendi e vai in liquidità" if held
                       else "segnale ribassista, resta fuori"),
                    {"last_close": last_close, "sma": sma_val, "sma_months": sma_months},
                ))

        n_bullish = len(bullish)
        target_weight = ONE / Decimal(str(n_bullish)) if n_bullish else ZERO
        by_symbol = {d.symbol: d for d in others}
        for up, last_close, sma_val in bullish:
            data = {"last_close": last_close, "sma": sma_val, "n_bullish": n_bullish}
            if drawdown_braking:
                by_symbol[up.symbol] = Decision(
                    up.symbol, "hold", None,
                    f"Chiusura mensile {last_close:.2f} > SMA({sma_months}) {sma_val:.2f}: "
                    f"segnale rialzista, ma freno drawdown attivo: nessun acquisto",
                    data,
                )
            else:
                w, note = self.sized(ctx, up, target_weight, available)
                by_symbol[up.symbol] = Decision(
                    up.symbol, "buy", w,
                    self.with_note(f"Chiusura mensile {last_close:.2f} > SMA({sma_months}) {sma_val:.2f}: "
                                   f"segnale rialzista, peso obiettivo {float(w)*100:.1f}%", note),
                    data,
                )
        return [by_symbol[s] for s in order]


def _is_last_trading_day_of_month(today: date) -> bool:
    """Oggi è l'ultimo giorno di borsa del mese se il prossimo giorno lavorativo cade nel mese successivo."""
    candidate = today + timedelta(days=1)
    while candidate.weekday() >= 5:  # salta sabato (5) e domenica (6)
        candidate += timedelta(days=1)
    return candidate.month != today.month
