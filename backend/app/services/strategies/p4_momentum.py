"""
P4 – Momentum 12-1 con filtro di tendenza.

Ogni mese, l'ultimo giorno di borsa, sui titoli delle tre liste (FTSE MIB, Euro Stoxx 50, S&P 100):
1. classifica i titoli per rendimento in euro degli ultimi 12 mesi escluso l'ultimo;
2. tiene i primi 10; un titolo già in portafoglio resta finché è tra i primi 20 (isteresi:
   meno operazioni e meno commissioni);
3. compra un titolo solo se l'indice della sua borsa è sopra la media a 200 giorni;
   altrimenti quel posto resta in liquidità fino al mese successivo.

Parametri: n_hold (10), keep_rank (20), trend_days (200).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .base import BaseStrategy, Decision, StrategyContext, UniversePrice
from .common import ALL_LISTS, REGIONS, above_sma, fx_symbol, momentum_12_1, pct
from .p2_trend import _is_last_trading_day_of_month

ZERO = Decimal("0")
ONE = Decimal("1")


class P4Momentum(BaseStrategy):

    @property
    def frequency(self) -> str:
        return "monthly"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        if next_day is not None:
            return next_day.month != today.month
        return _is_last_trading_day_of_month(today)

    def universe_lists(self) -> list[str]:
        return list(self.params.get("universe_lists") or ALL_LISTS)

    def reference_symbols(self) -> list[str]:
        return [r.index for r in REGIONS.values()] + [fx_symbol("USD")]

    def generate_decisions(self, ctx: StrategyContext, universe_prices: list[UniversePrice],
                           drawdown_braking: bool) -> list[Decision]:
        n_hold = int(self._param("n_hold", 10))
        keep_rank = int(self._param("keep_rank", 20))
        trend_days = int(self._param("trend_days", 200))
        weight = ONE / Decimal(n_hold)

        prices = [up for up in universe_prices if up.available and up.price > ZERO and up.instrument_type == "stock"]
        moms = {up.symbol: momentum_12_1(ctx, up.symbol, up.listing_currency) for up in prices}
        ranked = sorted((s for s in moms if moms[s] is not None), key=lambda s: -moms[s])
        rank = {s: i + 1 for i, s in enumerate(ranked)}
        market = {up.symbol: up.market for up in prices}
        trend = {code: above_sma(ctx, r.index, trend_days) for code, r in REGIONS.items()}

        decisions: list[Decision] = []
        kept = 0
        for up in prices:
            if ctx.quantity(up.symbol) <= ZERO:
                continue
            r = rank.get(up.symbol)
            data = {"momentum": moms.get(up.symbol), "rank": r}
            if r is not None and r <= keep_rank:
                kept += 1
                decisions.append(Decision(up.symbol, "hold", None,
                                          f"Momentum 12-1 {pct(moms[up.symbol])}, {r}° su {len(ranked)}: ancora tra "
                                          f"i primi {keep_rank}, si tiene", data))
            else:
                where = f"{r}° su {len(ranked)}" if r else "momentum non calcolabile"
                decisions.append(Decision(up.symbol, "sell", ZERO,
                                          f"Uscito dai primi {keep_rank} ({where}): vendita", data))

        slots = n_hold - kept
        for sym in ranked[:n_hold]:
            if slots <= 0:
                break
            if ctx.quantity(sym) > ZERO:
                continue
            slots -= 1
            head = f"Momentum 12-1 {pct(moms[sym])}, {rank[sym]}° su {len(ranked)}"
            data = {"momentum": moms[sym], "rank": rank[sym]}
            region = REGIONS.get(market.get(sym) or "")
            t = trend.get(region.code) if region else None
            if drawdown_braking:
                decisions.append(Decision(sym, "hold", None, f"{head}, ma freno drawdown attivo: nessun acquisto",
                                          data))
            elif t is None:
                decisions.append(Decision(sym, "hold", None, f"{head}, ma manca l'indice della sua borsa: il posto "
                                                             "resta in liquidità", data))
            elif not t[0]:
                decisions.append(Decision(sym, "hold", None,
                                          f"{head}, ma {region.label} ({t[1]:.0f}) è sotto la media a {trend_days} "
                                          f"giorni ({t[2]:.0f}): il posto resta in liquidità", data))
            else:
                decisions.append(Decision(sym, "buy", weight,
                                          f"{head}; {region.label} sopra la media a {trend_days} giorni: acquisto "
                                          f"con peso {pct(weight)}", data))
        return decisions
