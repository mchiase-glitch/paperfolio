"""
P2 – Trend following mensile (Faber 10 mesi).

Regola: il penultimo giorno di borsa del mese (per poter piazzare
gli ordini prima della chiusura), per ogni titolo dell'universo:
  - Se chiusura mensile > SMA(10 mesi): tieni/compra (peso uguale)
  - Se chiusura mensile < SMA(10 mesi): vendi e vai in cash

In caso di drawdown brake: non fare nuovi acquisti.

Parametri (params_json della StrategyConfig):
  universe_list: nome della lista universo (es. "eurostoxx50")
  sma_months: lunghezza SMA mensile (default 10)
  min_history_days: storia minima richiesta per un titolo (default 300)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Account, StrategyConfig
from .base import BaseStrategy, Decision, UniversePrice
from ..price_history import get_rows, has_enough_history
from ..indicators import monthly_sma, last_monthly_close, split_adjust

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

    def should_run_today(self, db: Session, today: date) -> bool:
        """
        Gira l'ultimo giorno di borsa del mese.
        Verifica che non ci siano altri giorni di borsa dello stesso mese dopo oggi.
        Usa un'euristica: se domani è in un mese diverso, o se domani+1 è nel mese successivo
        e domani cade di weekend, allora oggi è l'ultimo giorno di borsa del mese.
        """
        return _is_last_trading_day_of_month(today)

    def generate_decisions(
        self,
        db: Session,
        account: Account,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
        now: datetime,
    ) -> list[Decision]:
        sma_months = int(self._param("sma_months", DEFAULT_SMA_MONTHS))
        min_history = int(self._param("min_history_days", DEFAULT_MIN_HISTORY))
        end = now.date()
        # Scarica abbastanza storico per calcolare SMA(10 mesi) + margine
        start = end - timedelta(days=(sma_months + 3) * 31)

        available = [up for up in universe_prices if up.available and up.price > ZERO]
        if not available:
            return []

        # Quali titoli hanno il segnale rialzista?
        bullish: list[UniversePrice] = []
        decisions: list[Decision] = []

        for up in available:
            if not has_enough_history(db, up.symbol, min_history):
                decisions.append(Decision(
                    symbol=up.symbol,
                    action="skip",
                    target_weight=None,
                    reason_it=f"Storia insufficiente per calcolare SMA({sma_months} mesi): skip",
                    signal_data={"min_history": min_history},
                ))
                continue

            rows = get_rows(db, up.symbol, start, end)
            if not rows:
                decisions.append(Decision(
                    symbol=up.symbol,
                    action="skip",
                    target_weight=None,
                    reason_it="Nessun dato in cache: skip",
                    signal_data={},
                ))
                continue

            dates = [r.date for r in rows]
            closes_raw = [r.close for r in rows]
            splits = [r.split_ratio for r in rows]
            closes = split_adjust(closes_raw, splits)

            sma_val = monthly_sma(dates, closes, sma_months)
            last_close = last_monthly_close(dates, closes)

            if sma_val is None or last_close is None:
                decisions.append(Decision(
                    symbol=up.symbol,
                    action="skip",
                    target_weight=None,
                    reason_it=f"Dati insufficienti per SMA({sma_months} mesi): skip",
                    signal_data={"last_close": str(last_close), "sma": str(sma_val)},
                ))
                continue

            if last_close > sma_val:
                bullish.append(up)
                # La decisione definitiva (buy/hold) viene aggiunta dopo
                decisions.append(("bullish", up, last_close, sma_val))  # type: ignore[arg-type]
            else:
                decisions.append(Decision(
                    symbol=up.symbol,
                    action="sell",
                    target_weight=ZERO,
                    reason_it=(
                        f"Chiusura mensile {last_close:.2f} < SMA({sma_months}) {sma_val:.2f}: "
                        f"segnale ribassista, vendi e vai in cash"
                    ),
                    signal_data={"last_close": last_close, "sma": sma_val, "sma_months": sma_months},
                ))

        # Costruisce le decisioni finali per i titoli rialzisti
        n_bullish = len(bullish)
        target_weight = ONE / Decimal(str(n_bullish)) if n_bullish > 0 else ZERO

        final: list[Decision] = []
        for d in decisions:
            if isinstance(d, tuple) and d[0] == "bullish":
                _, up, last_close, sma_val = d
                if drawdown_braking:
                    final.append(Decision(
                        symbol=up.symbol,
                        action="hold",
                        target_weight=None,
                        reason_it=(
                            f"Chiusura mensile {last_close:.2f} > SMA({sma_months}) {sma_val:.2f}: "
                            f"segnale rialzista, ma brake attivo: nessun acquisto"
                        ),
                        signal_data={"last_close": last_close, "sma": sma_val},
                    ))
                else:
                    final.append(Decision(
                        symbol=up.symbol,
                        action="buy",
                        target_weight=target_weight,
                        reason_it=(
                            f"Chiusura mensile {last_close:.2f} > SMA({sma_months}) {sma_val:.2f}: "
                            f"segnale rialzista, acquisto con peso {float(target_weight)*100:.1f}%"
                        ),
                        signal_data={"last_close": last_close, "sma": sma_val, "n_bullish": n_bullish},
                    ))
            else:
                final.append(d)  # type: ignore[arg-type]
        return final


# ── Helper ────────────────────────────────────────────────────────────────────

def _is_last_trading_day_of_month(today: date) -> bool:
    """
    Euristica: oggi è l'ultimo giorno di borsa del mese se il prossimo
    giorno lavorativo (lun-ven) cade già nel mese successivo.
    Non usa exchange_calendars per semplicità; l'orchestratore può
    sovrascrivere con una verifica più precisa.
    """
    candidate = today + timedelta(days=1)
    while candidate.weekday() >= 5:  # salta sabato (5) e domenica (6)
        candidate += timedelta(days=1)
    return candidate.month != today.month
