"""
P6 – Valore + qualità (Magic Formula di Greenblatt, adattata).

Una volta l'anno, nel mese scelto (default aprile, quando i bilanci annuali sono usciti),
sui titoli delle tre liste esclusi banche, assicurazioni e utility:
1. classifica per rendimento degli utili = EBIT / valore d'impresa (quanto "rende" l'azienda
   rispetto a quanto costa comprarla tutta, debiti compresi);
2. classifica per redditività del capitale = EBIT / (capitale circolante netto + immobilizzazioni);
   se mancano i dati: utile lordo / totale attivo;
3. somma le due posizioni in classifica e compra i primi 15 con pesi uguali.

Un titolo senza dati di bilancio sufficienti è escluso e segnalato nel registro.
Backtest non disponibile: la fonte non ha i bilanci com'erano alle date passate.

Parametri: n_hold (15), rebalance_month (4), exclude (["banks", "insurance", "utilities"]),
rebalance_band (0.2).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .base import BaseStrategy, Decision, StrategyContext, UniversePrice, holdings_value
from .common import ALL_LISTS, fx_at, pct

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_EXCLUDE = ["banks", "insurance", "utilities"]
EXCLUDE_LABELS = {"banks": "banca", "insurance": "assicurazione", "utilities": "utility"}


def excluded_kind(f: dict, exclude: list[str]) -> str | None:
    industry = (f.get("industry") or "").lower()
    sector = (f.get("sector") or "").lower()
    if "banks" in exclude and industry.startswith("banks"):
        return "banks"
    if "insurance" in exclude and industry.startswith("insurance"):
        return "insurance"
    if "utilities" in exclude and (sector == "utilities" or industry.startswith("utilities")):
        return "utilities"
    return None


def ratios(f: dict, ebit_to_quote: float | None) -> tuple[float | None, float | None, str]:
    """(rendimento degli utili, redditività, come è calcolata la redditività)."""
    ebit = f.get("ebit")
    ev = f.get("enterprise_value")
    if ebit is None or ebit_to_quote is None:
        return None, None, ""
    ey = ebit * ebit_to_quote / ev if ev and ev > 0 else None
    ca, cl, ppe = f.get("current_assets"), f.get("current_liabilities"), f.get("net_ppe")
    if None not in (ca, cl, ppe) and (ca - cl) + ppe > 0:
        return ey, ebit / ((ca - cl) + ppe), "EBIT / capitale investito"
    gp, ta = f.get("gross_profit"), f.get("total_assets")
    if gp is not None and ta:
        return ey, gp / ta, "utile lordo / attivo"
    return ey, None, ""


class P6ValueQuality(BaseStrategy):

    needs_fundamentals = True
    backtest_unavailable = ("La fonte dei dati dà solo gli ultimi bilanci, non quelli com'erano negli anni passati: "
                            "un backtest userebbe informazioni che allora non si conoscevano e il risultato sarebbe falsato.")

    @property
    def frequency(self) -> str:
        return "annual"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        return today.weekday() < 5 and today.month == int(self._param("rebalance_month", 4))

    def universe_lists(self) -> list[str]:
        return list(self.params.get("universe_lists") or ALL_LISTS)

    def reference_symbols(self) -> list[str]:
        return ["EURUSD=X"]

    def generate_decisions(self, ctx: StrategyContext, universe_prices: list[UniversePrice],
                           drawdown_braking: bool) -> list[Decision]:
        n_hold = int(self._param("n_hold", 15))
        exclude = list(self.params.get("exclude") or DEFAULT_EXCLUDE)
        band = self._param_decimal("rebalance_band", "0.2")

        notes: list[Decision] = []
        scored: dict[str, tuple[float, float, str]] = {}
        prices = {up.symbol: up for up in universe_prices if up.available and up.price > ZERO
                  and up.instrument_type == "stock"}
        for sym, up in prices.items():
            f = ctx.fundamentals(sym)
            if not f:
                notes.append(Decision(sym, "skip", None, "Dati di bilancio non disponibili: escluso"))
                continue
            kind = excluded_kind(f, exclude)
            if kind:
                notes.append(Decision(sym, "skip", None, f"Escluso dalla strategia: {EXCLUDE_LABELS[kind]}"))
                continue
            ey, q, how = ratios(f, _conversion(ctx, f, up.listing_currency))
            if ey is None or q is None:
                notes.append(Decision(sym, "skip", None,
                                      "Dati di bilancio insufficienti (manca utile operativo, valore d'impresa o "
                                      "attivo): escluso"))
                continue
            scored[sym] = (ey, q, how)

        by_ey = sorted(scored, key=lambda s: -scored[s][0])
        by_q = sorted(scored, key=lambda s: -scored[s][1])
        r_ey = {s: i + 1 for i, s in enumerate(by_ey)}
        r_q = {s: i + 1 for i, s in enumerate(by_q)}
        ranked = sorted(scored, key=lambda s: (r_ey[s] + r_q[s], r_ey[s]))
        top = ranked[:n_hold]
        weight = ONE / Decimal(n_hold)

        def why(s: str) -> str:
            ey, q, how = scored[s]
            return (f"Rendimento degli utili {pct(ey)} ({r_ey[s]}° su {len(scored)}), redditività {pct(q)} "
                    f"[{how}] ({r_q[s]}°): punteggio {r_ey[s] + r_q[s]}, {ranked.index(s) + 1}° in classifica")

        total = ctx.cash() + holdings_value(ctx, universe_prices)
        decisions: list[Decision] = []
        if total <= ZERO:
            return notes
        for sym in top:
            cur = ctx.quantity(sym) * prices[sym].price / total
            data = {"ey": scored[sym][0], "quality": scored[sym][1], "rank": ranked.index(sym) + 1}
            if abs(cur - weight) <= band * weight:
                decisions.append(Decision(sym, "hold", None, f"{why(sym)}; peso {pct(cur)} già vicino all'obiettivo",
                                          data))
            elif cur < weight:
                if drawdown_braking:
                    decisions.append(Decision(sym, "hold", None, f"{why(sym)}; freno drawdown attivo: nessun acquisto",
                                              data))
                else:
                    decisions.append(Decision(sym, "buy", weight, f"{why(sym)}: tra i primi {n_hold}, acquisto con "
                                                                  f"peso {pct(weight)}", data))
            else:
                decisions.append(Decision(sym, "sell", weight, f"{why(sym)}; peso {pct(cur)} sopra l'obiettivo: "
                                                               "vendita parziale", data))
        for sym, up in prices.items():
            if sym not in top and ctx.quantity(sym) > ZERO:
                reason = (f"{why(sym)}: non più tra i primi {n_hold}" if sym in scored
                          else "Non più classificabile (dati di bilancio mancanti o settore escluso)")
                decisions.append(Decision(sym, "sell", ZERO, f"{reason}, vendita"))
        return decisions + notes


def _conversion(ctx: StrategyContext, f: dict, listing_currency: str) -> float | None:
    """Fattore per portare l'EBIT (valuta di bilancio) nella valuta del valore d'impresa (valuta di quotazione)."""
    fin = f.get("financial_currency") or listing_currency
    quote = f.get("currency") or listing_currency
    if fin == quote:
        return 1.0
    if {fin, quote} <= {"EUR", "USD"}:
        usd_per_eur = fx_at(ctx, "USD", ctx.today)
        if not usd_per_eur:
            return None
        return usd_per_eur if fin == "EUR" else 1 / usd_per_eur
    return None
