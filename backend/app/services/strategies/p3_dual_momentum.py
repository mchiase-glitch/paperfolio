"""
P3 – Dual momentum regionale (adattamento di GEM ad azioni + ETF).

Ogni mese, l'ultimo giorno di borsa:
1. confronta il rendimento a 12 mesi, in euro, degli indici FTSE MIB, Euro Stoxx 50 e S&P 500;
2. se la regione migliore supera la soglia del momentum assoluto (default 0%) il portafoglio va lì:
   - quota ETF (default 50%) sull'ETF UCITS della regione;
   - quota azioni (default 50%) sui 10 titoli della regione con il miglior momentum 12-1, pesi uguali;
3. altrimenti tutto sul rifugio: ETF di titoli di Stato in euro (default) oppure liquidità.

Una posizione già vicina al peso obiettivo (entro la tolleranza) non si tocca, per non pagare
commissioni su ritocchi minimi.

Parametri: etf_share (0.5), n_stocks (10), abs_threshold (0.0), refuge ("bond" | "cash"),
rebalance_band (0.2), etf_ita, etf_eur, etf_usa, etf_refuge (ticker degli ETF).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .base import BaseStrategy, Decision, StrategyContext, UniversePrice, holdings_value
from .common import ALL_LISTS, REGIONS, fx_symbol, momentum_12_1, pct, return_eur
from .p2_trend import _is_last_trading_day_of_month

ZERO = Decimal("0")
ONE = Decimal("1")

DEFAULT_ETFS = {
    "etf_ita": "IMIB.MI",     # iShares FTSE MIB UCITS ETF (Dist)
    "etf_eur": "MSE.MI",      # Amundi EURO STOXX 50 II UCITS ETF (Acc)
    "etf_usa": "IUSA.MI",     # iShares Core S&P 500 UCITS ETF (Dist), quotato in euro
    "etf_refuge": "XGLE.MI",  # Xtrackers II Eurozone Government Bond UCITS ETF (Acc)
}
ETF_PARAM = {"ITA": "etf_ita", "EUR": "etf_eur", "USA": "etf_usa"}


class P3DualMomentum(BaseStrategy):

    @property
    def frequency(self) -> str:
        return "monthly"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        if next_day is not None:
            return next_day.month != today.month
        return _is_last_trading_day_of_month(today)

    def universe_lists(self) -> list[str]:
        return list(ALL_LISTS)

    def etf(self, key: str) -> str:
        return self.params.get(key) or DEFAULT_ETFS[key]

    def extra_tradeable(self) -> list[str]:
        return [self.etf(k) for k in DEFAULT_ETFS]

    def reference_symbols(self) -> list[str]:
        return [r.index for r in REGIONS.values()] + [fx_symbol("USD")]

    def generate_decisions(self, ctx: StrategyContext, universe_prices: list[UniversePrice],
                           drawdown_braking: bool) -> list[Decision]:
        etf_share = self._param_decimal("etf_share", "0.5")
        n_stocks = int(self._param("n_stocks", 10))
        threshold = float(self._param("abs_threshold", 0.0))
        refuge = self.params.get("refuge", "bond")
        band = self._param_decimal("rebalance_band", "0.2")

        returns = {code: return_eur(ctx, r.index, r.currency) for code, r in REGIONS.items()}
        if any(v is None for v in returns.values()):
            missing = ", ".join(REGIONS[c].label for c, v in returns.items() if v is None)
            return [Decision("—", "skip", None, f"Rendimento a 12 mesi non disponibile per: {missing}. Nessuna operazione.")]
        summary = ", ".join(f"{REGIONS[c].label} {pct(v)}" for c, v in returns.items())
        best = max(returns, key=returns.get)
        prices = {up.symbol: up for up in universe_prices if up.available and up.price > ZERO}

        targets: dict[str, Decimal] = {}
        why: dict[str, str] = {}
        if returns[best] > threshold:
            region = REGIONS[best]
            head = f"Rendimenti a 12 mesi in euro: {summary}. Vince {region.label}"
            etf_sym = self.etf(ETF_PARAM[best])
            if etf_share > 0 and etf_sym in prices:
                targets[etf_sym] = etf_share
                why[etf_sym] = f"{head}: quota ETF {pct(etf_share)}"
            stock_share = ONE - etf_share
            if stock_share > 0:
                moms = [(momentum_12_1(ctx, up.symbol, up.listing_currency), up.symbol)
                        for up in prices.values() if region.stocks in up.groups and up.instrument_type == "stock"]
                top = sorted(((m, s) for m, s in moms if m is not None), reverse=True)[:n_stocks]
                for rank, (m, s) in enumerate(top, start=1):
                    targets[s] = stock_share / len(top)
                    why[s] = (f"{head}: tra i {len(top)} titoli della regione con il miglior momentum 12-1 "
                              f"({rank}°, {pct(m)})")
        else:
            head = (f"Rendimenti a 12 mesi in euro: {summary}. Nessuna regione supera la soglia del "
                    f"{pct(threshold)}")
            if refuge == "bond":
                sym = self.etf("etf_refuge")
                if sym in prices:
                    targets[sym] = ONE
                    why[sym] = f"{head}: tutto sull'ETF di titoli di Stato"

        total = ctx.cash() + holdings_value(ctx, universe_prices)
        if total <= ZERO:
            return []
        decisions = []
        held = [s for s in prices if ctx.quantity(s) > ZERO]
        for sym in list(targets) + [s for s in held if s not in targets]:
            up = prices[sym]
            w = targets.get(sym, ZERO)
            cur = ctx.quantity(sym) * up.price / total
            data = {"current_weight": str(cur), "target_weight": str(w), "returns": returns}
            if w == ZERO:
                decisions.append(Decision(sym, "sell", ZERO, f"{head}: il titolo non fa più parte del portafoglio, "
                                                             "vendita", data))
            elif abs(cur - w) <= band * w:
                decisions.append(Decision(sym, "hold", None, f"{why[sym]}; peso attuale {pct(cur)} già vicino "
                                                             f"all'obiettivo {pct(w)}", data))
            elif cur < w:
                if drawdown_braking:
                    decisions.append(Decision(sym, "hold", None, f"{why[sym]}; freno drawdown attivo: nessun acquisto",
                                              data))
                else:
                    decisions.append(Decision(sym, "buy", w, f"{why[sym]}; peso {pct(cur)} → {pct(w)}: acquisto",
                                              data))
            else:
                decisions.append(Decision(sym, "sell", w, f"{why[sym]}; peso {pct(cur)} → {pct(w)}: vendita parziale",
                                          data))
        if not targets:
            decisions.append(Decision("—", "hold", None, f"{head}: tutto in liquidità"))
        return decisions
