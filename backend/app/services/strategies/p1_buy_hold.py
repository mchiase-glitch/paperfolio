"""
P1 – Buy & Hold con ribilanciamento automatico.

Logica:
- Compra tutti i titoli dell'universo in parti uguali all'avvio.
- Ogni giorno controlla i pesi correnti.
- Se un peso si discosta di più di REBALANCE_BAND dal peso obiettivo, ribilancia.
- In modalità drawdown brake non fa nuovi acquisti; vende solo se necessario.

Parametri (params_json della StrategyConfig):
  universe_list: nome della lista universo (es. "ftse_mib")
  rebalance_band: soglia di scostamento per il ribilanciamento (default 0.25 = 25%)
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from .base import BaseStrategy, Decision, StrategyContext, UniversePrice, holdings_value

log = logging.getLogger("paperfolio.p1")

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_BAND = Decimal("0.25")


class P1BuyHold(BaseStrategy):
    """P1: buy & hold con ribilanciamento a banda fissa."""

    @property
    def frequency(self) -> str:
        return "daily"

    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        return today.weekday() < 5  # P1 gira ogni giorno di borsa

    def generate_decisions(
        self,
        ctx: StrategyContext,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
    ) -> list[Decision]:
        band = self._param_decimal("rebalance_band", str(DEFAULT_BAND))
        available = [up for up in universe_prices if up.available and up.price > ZERO]
        if not available:
            return []

        n = len(available)
        equal = ONE / Decimal(str(n))
        total = ctx.cash() + holdings_value(ctx, universe_prices)
        if total <= ZERO:
            return []

        decisions: list[Decision] = []
        for up in available:
            target_weight, note = self.sized(ctx, up, equal, available)
            current_weight = ctx.quantity(up.symbol) * up.price / total
            deviation = abs(current_weight - target_weight)
            data = {"current_weight": str(current_weight), "target_weight": str(target_weight)}
            if deviation <= band * target_weight:
                decisions.append(Decision(
                    up.symbol, "hold", None,
                    f"Peso corrente {_pct(current_weight)} nel range ±{_pct(band * target_weight)} "
                    f"dell'obiettivo {_pct(target_weight)}: nessuna azione",
                    data,
                ))
            elif current_weight < target_weight:
                if drawdown_braking:
                    decisions.append(Decision(
                        up.symbol, "hold", None,
                        f"Peso corrente {_pct(current_weight)} < obiettivo {_pct(target_weight)} "
                        f"(scostamento {_pct(deviation)}), ma freno drawdown attivo: nessun acquisto",
                        data,
                    ))
                else:
                    decisions.append(Decision(
                        up.symbol, "buy", target_weight,
                        self.with_note(f"Peso corrente {_pct(current_weight)} < obiettivo {_pct(target_weight)} "
                                       f"(scostamento {_pct(deviation)} > banda {_pct(band * target_weight)}): "
                                       "acquisto", note),
                        data,
                    ))
            else:
                decisions.append(Decision(
                    up.symbol, "sell", target_weight,
                    f"Peso corrente {_pct(current_weight)} > obiettivo {_pct(target_weight)} "
                    f"(scostamento {_pct(deviation)} > banda {_pct(band * target_weight)}): vendita",
                    data,
                ))
        return decisions


def _pct(v: Decimal) -> str:
    return f"{float(v) * 100:.1f}%"
