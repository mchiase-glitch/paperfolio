"""
Interfaccia comune a tutte le strategie automatiche.

Ogni strategia implementa i 6 passi:
1. Universo: titoli ammessi
2. Segnale: quali tenere/comprare e quali vendere
3. Filtri di rischio: drawdown, concentrazione, dati incompleti
4. Dimensionamento: quanto comprare di ciascuno
5. Ordini: passati al motore esistente
6. Registro: motivazione in italiano di ogni decisione

La strategia NON scrive nel ledger direttamente: genera Decision e
il modulo auto_portfolio si occupa di placing e registrazione.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ...models import Account, StrategyConfig

log = logging.getLogger("paperfolio.strategies")

ZERO = Decimal("0")


@dataclass
class Decision:
    """
    Singola decisione di una strategia per un titolo.

    action: 'buy' | 'sell' | 'hold' | 'skip'
    target_weight: peso obiettivo (0–1) del totale del portafoglio; None per hold/skip
    reason_it: motivazione in italiano per il registro
    signal_data: dati numerici di supporto (es. prezzo, media, RSI)
    instrument_id: id dell'Instrument nel DB; riempito da auto_portfolio prima dell'esecuzione
    """
    symbol: str
    action: str
    target_weight: Decimal | None
    reason_it: str
    signal_data: dict = field(default_factory=dict)
    instrument_id: int | None = None

    def signal_data_json(self) -> str:
        return json.dumps(self.signal_data, default=str)


@dataclass
class UniversePrice:
    """Prezzo di un titolo dell'universo per il calcolo degli indicatori e del sizing."""
    symbol: str
    instrument_id: int | None  # None se non ancora nel DB
    price: Decimal
    currency: str
    available: bool  # False se il prezzo non è disponibile


class BaseStrategy(ABC):
    """Classe base per tutte le strategie. Ogni strategia implementa i metodi astratti."""

    def __init__(self, config: StrategyConfig, params: dict):
        self.config = config
        self.params = params

    # ── Metodi da implementare ────────────────────────────────────────────────

    @property
    @abstractmethod
    def frequency(self) -> str:
        """'daily' | 'monthly' | 'annual'"""

    @abstractmethod
    def should_run_today(self, db: Session, today: date) -> bool:
        """True se la strategia deve girare oggi (es. ultimo giorno di borsa del mese per P2)."""

    @abstractmethod
    def generate_decisions(
        self,
        db: Session,
        account: Account,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
        now: datetime,
    ) -> list[Decision]:
        """
        Genera le decisioni (buy/sell/hold/skip) per ogni titolo dell'universo.
        Non piazza ordini: si limita a restituire le decisioni.
        """

    # ── Helpers condivisi ─────────────────────────────────────────────────────

    def run_key(self, today: date) -> str:
        if self.frequency == "daily":
            return f"{self.config.id}_{self.config.strategy_type}_{today.isoformat()}"
        elif self.frequency == "monthly":
            return f"{self.config.id}_{self.config.strategy_type}_{today.year}-{today.month:02d}"
        else:  # annual
            return f"{self.config.id}_{self.config.strategy_type}_{today.year}"

    def _param(self, key: str, default):
        v = self.params.get(key, default)
        if isinstance(default, Decimal):
            return Decimal(str(v))
        return v

    def _param_decimal(self, key: str, default: str) -> Decimal:
        return Decimal(str(self.params.get(key, default)))

    # ── Dimensionamento ───────────────────────────────────────────────────────

    def size_equal(self, n: int) -> Decimal:
        """Peso uguale per ogni posizione."""
        if n == 0:
            return ZERO
        return Decimal("1") / Decimal(str(n))

    def size_inv_volatility(self, symbols: list[str], db: Session, today: date) -> dict[str, Decimal]:
        """
        Peso inverso alla volatilità a 60 giorni.
        Restituisce un dict {symbol: weight} normalizzato a 1.
        Fallback: uguale se la volatilità non è disponibile.
        """
        from datetime import timedelta
        from ...services import price_history, indicators
        end = today
        start = end - timedelta(days=120)
        vols: dict[str, float] = {}
        for sym in symbols:
            rows = price_history.get_rows(db, sym, start, end)
            if len(rows) >= 61:
                closes = [r.close for r in rows[-61:]]
                v = indicators.volatility_annual(closes)
                if v and v > 0:
                    vols[sym] = v
        if not vols or len(vols) < len(symbols) / 2:
            # Fallback a equal weight
            w = self.size_equal(len(symbols))
            return {s: w for s in symbols}
        inv = {s: 1.0 / vols.get(s, 1.0) for s in symbols}
        total = sum(inv.values())
        return {s: Decimal(str(round(v / total, 6))) for s, v in inv.items()}
