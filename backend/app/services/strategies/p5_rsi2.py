"""
P5 – Ritorno alla media con RSI a 2 giorni (Connors).

Ogni giorno di borsa, sui titoli delle tre liste:
- compra quando la chiusura è sopra la media a 200 giorni (tendenza di fondo positiva)
  e l'RSI a 2 giorni è sotto 10 (forte calo degli ultimi giorni, che di solito rientra);
- vende quando la chiusura supera la media a 5 giorni (rimbalzo avvenuto), oppure scende sotto
  la media a 200 giorni, oppure dopo 10 giorni di borsa (stop temporale);
- al massimo 5 posizioni insieme, ciascuna da 1/5 del capitale; se i candidati sono di più,
  si scelgono quelli con l'RSI più basso.

Parametri: max_positions (5), rsi_entry (10), max_days (10), sma_long (200), sma_exit (5),
exit_below_sma_long (sì: vende se la chiusura scende sotto la media lunga), drawdown_brake (sì).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..indicators import prefix_sums, rsi_series
from .base import BaseStrategy, Decision, StrategyContext, UniversePrice
from .common import ALL_LISTS

ZERO = Decimal("0")
ONE = Decimal("1")


class P5Rsi2(BaseStrategy):

    default_max_weight = Decimal("0.20")  # 5 posizioni da 1/5: il limite comune del 10% le dimezzerebbe

    def __init__(self, config, params: dict):
        super().__init__(config, params)
        self._cache: dict[str, tuple[int, list, list]] = {}  # simbolo → (id serie, RSI, somme cumulate)

    @property
    def frequency(self) -> str:
        return "daily"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        return today.weekday() < 5

    def universe_lists(self) -> list[str]:
        return list(self.params.get("universe_lists") or ALL_LISTS)

    def _indicators(self, symbol: str, closes: list[float]) -> tuple[list, list]:
        """RSI e somme cumulate calcolati una volta per serie (nel backtest la serie è sempre la stessa)."""
        c = self._cache.get(symbol)
        if c is None or c[0] != id(closes) or len(c[1]) != len(closes):
            c = (id(closes), rsi_series(closes, 2), prefix_sums(closes))
            self._cache[symbol] = c
        return c[1], c[2]

    def generate_decisions(self, ctx: StrategyContext, universe_prices: list[UniversePrice],
                           drawdown_braking: bool) -> list[Decision]:
        max_pos = int(self._param("max_positions", 5))
        rsi_entry = float(self._param("rsi_entry", 10))
        max_days = int(self._param("max_days", 10))
        n_long = int(self._param("sma_long", 200))
        n_exit = int(self._param("sma_exit", 5))
        exit_long = bool(self._param("exit_below_sma_long", True))  # uscita se perde la media lunga
        weight = ONE / Decimal(max_pos)

        decisions: list[Decision] = []
        candidates: list[tuple[float, str, str, dict]] = []
        held = exiting = 0
        for up in universe_prices:
            owned = ctx.quantity(up.symbol) > ZERO
            if not up.available or up.price <= ZERO or up.instrument_type != "stock":
                held += owned  # occupa comunque un posto
                continue
            dates, closes, i = ctx.closes(up.symbol)
            if i + 1 < n_long or (ctx.today - dates[i]).days > 7:
                if owned:
                    held += 1
                    decisions.append(Decision(up.symbol, "hold", None, "Dati recenti mancanti: si tiene"))
                continue
            rsi, ps = self._indicators(up.symbol, closes)
            close = closes[i]
            sma_long = (ps[i + 1] - ps[i + 1 - n_long]) / n_long
            sma_exit = (ps[i + 1] - ps[i + 1 - n_exit]) / n_exit
            r = rsi[i]
            data = {"close": close, "sma_long": sma_long, "sma_exit": sma_exit, "rsi2": r}
            if owned:
                held += 1
                days = ctx.held_days(up.symbol)
                data["days"] = days
                if close > sma_exit:
                    reason = f"Chiusura {close:.2f} sopra la media a {n_exit} giorni ({sma_exit:.2f}): rimbalzo avvenuto"
                elif exit_long and close < sma_long:
                    reason = f"Chiusura {close:.2f} sotto la media a {n_long} giorni ({sma_long:.2f}): tendenza persa"
                elif days >= max_days:
                    reason = f"Tenuto {days} giorni di borsa senza rimbalzo: stop temporale"
                else:
                    decisions.append(Decision(up.symbol, "hold", None,
                                              f"In attesa del rimbalzo: chiusura {close:.2f}, media a {n_exit} giorni "
                                              f"{sma_exit:.2f}, giorno {days} di {max_days}", data))
                    continue
                exiting += 1
                decisions.append(Decision(up.symbol, "sell", ZERO, f"{reason}: vendita", data))
            elif r is not None and close > sma_long and r < rsi_entry:
                candidates.append((r, up.symbol,
                                   f"Chiusura {close:.2f} sopra la media a {n_long} giorni ({sma_long:.2f}) e "
                                   f"RSI(2) {r:.1f} sotto {rsi_entry:.0f}", data))

        slots = max_pos - (held - exiting)
        by_symbol = {up.symbol: up for up in universe_prices}
        for k, (r, sym, head, data) in enumerate(sorted(candidates)):
            if drawdown_braking:
                decisions.append(Decision(sym, "hold", None, f"{head}, ma freno drawdown attivo: nessun acquisto", data))
            elif k < slots:
                w, note = self.sized(ctx, by_symbol[sym], weight, universe_prices)
                decisions.append(Decision(sym, "buy", w, self.with_note(
                    f"{head}: acquisto con peso {w * 100:.0f}%", note), data))
            else:
                decisions.append(Decision(sym, "hold", None,
                                          f"{head}, ma le {max_pos} posizioni sono già occupate", data))
        return decisions
