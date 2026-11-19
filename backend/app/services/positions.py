from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LedgerEntry, Order
from .money import ZERO


@dataclass
class Position:
    instrument_id: int
    side: str = "long"
    quantity: Decimal = ZERO
    cost_ccy: Decimal = ZERO  # solo prezzo, valuta strumento (per il prezzo medio di carico)
    cost_gross_eur: Decimal = ZERO  # solo prezzo, EUR al cambio applicato
    cost_fiscal_eur: Decimal = ZERO  # prezzo + commissioni di acquisto: costo fiscale
    entries: list[int] = field(default_factory=list)

    @property
    def avg_price(self) -> Decimal:
        return self.cost_ccy / self.quantity if self.quantity else ZERO

    @property
    def avg_cost_eur(self) -> Decimal:
        return self.cost_fiscal_eur / self.quantity if self.quantity else ZERO


def apply_entry(positions: dict[tuple[int, str], Position], e: LedgerEntry) -> None:
    """Aggiorna le posizioni con una riga del ledger (prezzo medio ponderato)."""
    if e.instrument_id is None or e.kind not in ("buy", "sell"):
        return
    key = (e.instrument_id, e.position_side)
    pos = positions.setdefault(key, Position(instrument_id=e.instrument_id, side=e.position_side))
    if e.kind == "buy":
        pos.quantity += e.quantity
        pos.cost_ccy += e.quantity * e.price
        pos.cost_gross_eur += e.gross_eur
        pos.cost_fiscal_eur += e.gross_eur + e.commission_eur
    else:
        fraction = e.quantity / pos.quantity
        pos.cost_ccy -= pos.cost_ccy * fraction
        pos.cost_gross_eur -= pos.cost_gross_eur * fraction
        pos.cost_fiscal_eur -= pos.cost_fiscal_eur * fraction
        pos.quantity -= e.quantity
    pos.entries.append(e.id)


def positions_from_entries(entries) -> dict[tuple[int, str], Position]:
    positions: dict[tuple[int, str], Position] = {}
    for e in entries:
        apply_entry(positions, e)
    return positions


def ledger(db: Session, account_id: int):
    return db.scalars(select(LedgerEntry).where(LedgerEntry.account_id == account_id)
                      .order_by(LedgerEntry.ts, LedgerEntry.id))


def open_positions(db: Session, account_id: int) -> dict[tuple[int, str], Position]:
    return {k: p for k, p in positions_from_entries(ledger(db, account_id)).items() if p.quantity != 0}


def position(db: Session, account_id: int, instrument_id: int, side: str = "long") -> Position:
    entries = db.scalars(select(LedgerEntry).where(
        LedgerEntry.account_id == account_id, LedgerEntry.instrument_id == instrument_id)
        .order_by(LedgerEntry.ts, LedgerEntry.id))
    return positions_from_entries(entries).get((instrument_id, side), Position(instrument_id, side))


def cash_balance(db: Session, account_id: int) -> Decimal:
    # Somma in Python: SUM() di SQLite convertirebbe i Decimal testuali in float
    total = ZERO
    for v in db.scalars(select(LedgerEntry.cash_delta_eur).where(LedgerEntry.account_id == account_id)):
        total += v
    return total


def reserved_cash(db: Session, account_id: int, exclude_order_id: int | None = None) -> Decimal:
    total = ZERO
    q = select(Order).where(Order.account_id == account_id, Order.status == "pending")
    for o in db.scalars(q):
        if o.id != exclude_order_id:
            total += o.reserved_eur
    return total


def pending_sell_quantity(db: Session, account_id: int, instrument_id: int, exclude_order_id: int | None = None) -> Decimal:
    total = ZERO
    q = select(Order).where(Order.account_id == account_id, Order.instrument_id == instrument_id,
                            Order.status == "pending", Order.side == "sell")
    for o in db.scalars(q):
        if o.id != exclude_order_id:
            total += o.quantity
    return total
