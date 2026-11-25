"""
Interfaccia comune a tutte le strategie automatiche.

Ogni strategia implementa i 6 passi:
1. Universo: titoli ammessi
2. Segnale: quali tenere/comprare e quali vendere
3. Filtri di rischio: drawdown, concentrazione, dati incompleti
4. Dimensionamento: quanto comprare di ciascuno
5. Ordini: passati al motore esistente
6. Registro: motivazione in italiano di ogni decisione

La strategia NON scrive nel ledger e non legge il database: vede il portafoglio e lo storico
attraverso un `StrategyContext`. Dal vivo il contesto legge il ledger e la cache dei prezzi;
nel backtest legge lo stato simulato e lo storico fino al giorno simulato. Così le regole
sono le stesse nei due casi.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

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
    """
    symbol: str
    action: str
    target_weight: Decimal | None
    reason_it: str
    signal_data: dict = field(default_factory=dict)

    def signal_data_json(self) -> str:
        return json.dumps(self.signal_data, default=str)


@dataclass
class UniversePrice:
    """Prezzo (in EUR) di un titolo dell'universo per il calcolo dei pesi e del dimensionamento."""
    symbol: str
    instrument_id: int | None  # None se non ancora nel DB
    price: Decimal
    currency: str
    available: bool  # False se il prezzo non è disponibile


class StrategyContext(ABC):
    """Quello che una strategia può vedere: portafoglio attuale e storico fino a `today`."""

    today: date

    @abstractmethod
    def quantity(self, symbol: str) -> Decimal:
        """Azioni possedute del titolo."""

    @abstractmethod
    def cash(self) -> Decimal:
        """Liquidità in EUR."""

    @abstractmethod
    def history(self, symbol: str, start: date, end: date) -> list:
        """Righe giornaliere (DayRow) tra start ed end, mai oltre `today`."""

    @abstractmethod
    def history_count(self, symbol: str) -> int:
        """Numero di giorni di storico disponibili fino a `today`."""


class BaseStrategy(ABC):
    """Classe base per tutte le strategie. Ogni strategia implementa i metodi astratti."""

    def __init__(self, config, params: dict):
        self.config = config  # StrategyConfig (dal vivo) oppure None (backtest)
        self.params = params

    # ── Metodi da implementare ────────────────────────────────────────────────

    @property
    @abstractmethod
    def frequency(self) -> str:
        """'daily' | 'monthly' | 'annual'"""

    @abstractmethod
    def should_run_today(self, today: date, next_day: date | None = None) -> bool:
        """True se la strategia deve girare oggi (es. ultimo giorno di borsa del mese per P2).

        `next_day` è il giorno di borsa successivo quando è noto (backtest); dal vivo si stima.
        """

    @abstractmethod
    def generate_decisions(
        self,
        ctx: StrategyContext,
        universe_prices: list[UniversePrice],
        drawdown_braking: bool,
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


def holdings_value(ctx: StrategyContext, prices: list[UniversePrice]) -> Decimal:
    """Valore in EUR dei titoli posseduti, ai prezzi dell'universo."""
    total = ZERO
    for up in prices:
        if up.available and up.price > ZERO:
            q = ctx.quantity(up.symbol)
            if q > ZERO:
                total += q * up.price
    return total
