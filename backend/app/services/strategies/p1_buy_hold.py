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
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Account, Instrument, StrategyConfig
from .base import BaseStrategy, Decision, UniversePrice
from .. import positions as positions_svc

log = logging.getLogger("paperfolio.p1")

ZERO = Decimal("0")
ONE = Decimal("1")
DEFAULT_BAND = Decimal("0.25")


class P1BuyHold(BaseStrategy):
    """P1: buy & hold con ribilanciamento a banda fissa."""

    @property
    def frequency(self) -> str:
        return "daily"

    def should_run_today(self, db: Session, today: date) -> bool:
        return True  # P1 gira ogni giorno di borsa aperta

    def generate_decisions(
        self,
        db: Session,
        account: Account,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
        now: datetime,
    ) -> list[Decision]:
        band = self._param_decimal("rebalance_band", str(DEFAULT_BAND))
        available = [up for up in universe_prices if up.available and up.price > ZERO]
        if not available:
            return []

        n = len(available)
        target_weight = ONE / Decimal(str(n))

        # Calcola valore totale del portafoglio (cash + posizioni)
        cash = positions_svc.cash_balance(db, account.id)
        holdings_value = _holdings_value(db, account.id, universe_prices)
        total = cash + holdings_value
        if total <= ZERO:
            # Portafoglio vuoto: compra tutto in parti uguali
            if drawdown_braking:
                return []
            return [
                Decision(
                    symbol=up.symbol,
                    action="buy",
                    target_weight=target_weight,
                    reason_it=f"Avvio portafoglio P1: acquisto uguale per tutti i {n} titoli",
                    signal_data={"price": str(up.price), "target_weight": str(target_weight)},
                )
                for up in available
            ]

        decisions: list[Decision] = []
        for up in available:
            current_weight = _current_weight(db, account.id, up, total)
            deviation = abs(current_weight - target_weight)
            if deviation > band * target_weight:
                if current_weight < target_weight:
                    if drawdown_braking:
                        decisions.append(Decision(
                            symbol=up.symbol,
                            action="hold",
                            target_weight=None,
                            reason_it=(
                                f"Peso corrente {_pct(current_weight)} < obiettivo {_pct(target_weight)} "
                                f"(scostamento {_pct(deviation)}), ma brake attivo: nessun acquisto"
                            ),
                            signal_data={"current_weight": str(current_weight), "target_weight": str(target_weight)},
                        ))
                    else:
                        decisions.append(Decision(
                            symbol=up.symbol,
                            action="buy",
                            target_weight=target_weight,
                            reason_it=(
                                f"Peso corrente {_pct(current_weight)} < obiettivo {_pct(target_weight)} "
                                f"(scostamento {_pct(deviation)} > banda {_pct(band * target_weight)}): acquisto"
                            ),
                            signal_data={"current_weight": str(current_weight), "target_weight": str(target_weight)},
                        ))
                else:
                    decisions.append(Decision(
                        symbol=up.symbol,
                        action="sell",
                        target_weight=target_weight,
                        reason_it=(
                            f"Peso corrente {_pct(current_weight)} > obiettivo {_pct(target_weight)} "
                            f"(scostamento {_pct(deviation)} > banda {_pct(band * target_weight)}): vendita"
                        ),
                        signal_data={"current_weight": str(current_weight), "target_weight": str(target_weight)},
                    ))
            else:
                decisions.append(Decision(
                    symbol=up.symbol,
                    action="hold",
                    target_weight=None,
                    reason_it=(
                        f"Peso corrente {_pct(current_weight)} nel range ±{_pct(band * target_weight)} "
                        f"dell'obiettivo {_pct(target_weight)}: nessuna azione"
                    ),
                    signal_data={"current_weight": str(current_weight), "target_weight": str(target_weight)},
                ))
        return decisions


# ── Helpers ───────────────────────────────────────────────────────────────────

def _holdings_value(db: Session, account_id: int, prices: list[UniversePrice]) -> Decimal:
    total = ZERO
    for up in prices:
        if up.instrument_id and up.available and up.price > ZERO:
            pos = positions_svc.position(db, account_id, up.instrument_id)
            if pos.quantity > ZERO:
                total += pos.quantity * up.price
    return total


def _current_weight(db: Session, account_id: int, up: UniversePrice, total: Decimal) -> Decimal:
    if total <= ZERO or not up.instrument_id:
        return ZERO
    pos = positions_svc.position(db, account_id, up.instrument_id)
    if pos.quantity <= ZERO:
        return ZERO
    return (pos.quantity * up.price) / total


def _pct(v: Decimal) -> str:
    return f"{float(v) * 100:.1f}%"
