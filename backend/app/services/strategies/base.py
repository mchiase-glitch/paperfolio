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
from bisect import bisect_right
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
    market: str | None = None        # ITA / EUR / USA: borsa di quotazione
    groups: tuple[str, ...] = ()     # liste di universo che contengono il titolo
    instrument_type: str = "stock"
    listing_currency: str = "EUR"    # valuta in cui è quotato (i prezzi storici sono in questa valuta)


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

    @abstractmethod
    def closes(self, symbol: str) -> tuple[list[date], list[float], int]:
        """(date, chiusure, i): si possono leggere solo le posizioni 0..i (i = ultimo giorno ≤ today, -1 se nessuno).

        Le liste possono essere più lunghe (nel backtest contengono il futuro): restituirle intere evita
        di copiarle ogni giorno, e le strategie possono tenere in memoria indicatori calcolati una volta.
        """

    @abstractmethod
    def entry_date(self, symbol: str) -> date | None:
        """Giorno in cui è stata aperta la posizione attuale sul titolo (None se non posseduto)."""

    def fundamentals(self, symbol: str) -> dict | None:
        """Ultimi dati di bilancio (solo dal vivo: nel backtest non esistono quelli storici)."""
        return None

    def held_days(self, symbol: str) -> int:
        """Giorni di borsa trascorsi dall'apertura della posizione (il giorno dell'acquisto non conta)."""
        entry = self.entry_date(symbol)
        if entry is None:
            return 0
        dates, _, i = self.closes(symbol)
        return max(0, i - bisect_right(dates, entry) + 1)


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

    # ── Caratteristiche ───────────────────────────────────────────────────────

    needs_fundamentals = False  # usa i dati di bilancio (da scaricare prima)
    backtest_unavailable: str | None = None  # motivo per cui il backtest non ha senso

    @property
    def uses_drawdown_brake(self) -> bool:
        """Parametro `drawdown_brake` (predefinito sì): se falso la strategia compra anche col freno acceso."""
        return bool(self.params.get("drawdown_brake", True))

    def load_state(self, state_json: str | None) -> None:
        """Stato tra un'esecuzione e l'altra (solo le strategie che ne hanno bisogno, es. P7)."""

    def dump_state(self) -> str | None:
        return None

    # ── Universo ──────────────────────────────────────────────────────────────

    def universe_lists(self) -> list[str]:
        """Liste di universo i cui titoli la strategia può comprare."""
        name = self.params.get("universe_list")
        return [name] if name else []

    def extra_tradeable(self) -> list[str]:
        """Altri strumenti negoziabili fuori dalle liste (es. gli ETF di P3)."""
        return []

    def reference_symbols(self) -> list[str]:
        """Serie solo da leggere (indici, cambi): servono ai segnali, non si comprano."""
        return []

    # ── Helpers condivisi ─────────────────────────────────────────────────────

    def run_key(self, today: date) -> str:
        return f"{self.config.id}_{self.config.strategy_type}_{period_key(self.frequency, today)}"

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


def period_key(frequency: str, today: date) -> str:
    """Periodo a cui appartiene un giorno: lo stesso periodo non si esegue due volte."""
    if frequency == "daily":
        return today.isoformat()
    if frequency == "monthly":
        return f"{today.year}-{today.month:02d}"
    return str(today.year)


def holdings_value(ctx: StrategyContext, prices: list[UniversePrice]) -> Decimal:
    """Valore in EUR dei titoli posseduti, ai prezzi dell'universo."""
    total = ZERO
    for up in prices:
        if up.available and up.price > ZERO:
            q = ctx.quantity(up.symbol)
            if q > ZERO:
                total += q * up.price
    return total
