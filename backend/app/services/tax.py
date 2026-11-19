import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LedgerEntry, LossUsage, TaxRule
from .money import ZERO, eur


@dataclass
class LossLot:
    entry_id: int
    origin: date
    expiry: date
    remaining: Decimal
    fiscal_category: str | None = None


@dataclass
class SaleTax:
    taxable: Decimal  # base imponibile dopo compensazione
    tax: Decimal
    loss_added: Decimal  # minus che entra nello zainetto (già ridotta al 48,08% se white list)
    loss_expiry: date | None
    usages: list[tuple[int, Decimal]] = field(default_factory=list)  # (riga zainetto, importo usato)


def loss_expiry(realized_on: date) -> date:
    """Una minus vale fino al 31/12 del quarto anno successivo."""
    return date(realized_on.year + 4, 12, 31)


def compute_sale_tax(realized: Decimal, rule: TaxRule, lots: list[LossLot], on: date) -> SaleTax:
    """Imposta su una vendita nel regime amministrato.

    `realized` = corrispettivo netto commissioni − costo fiscale (con commissioni di acquisto).
    `lots` = minus disponibili nello zainetto; si usano prima le più vecchie, se non scadute.
    """
    if realized > 0:
        base = realized * rule.base_factor
        usages: list[tuple[int, Decimal]] = []
        if rule.gains_kind == "diversi":
            for lot in sorted(lots, key=lambda lot: (lot.origin, lot.entry_id)):
                if base <= 0:
                    break
                if lot.expiry < on or lot.remaining <= 0:
                    continue
                used = min(lot.remaining, base)
                usages.append((lot.entry_id, eur(used)))
                base -= used
        taxable = eur(base)
        return SaleTax(taxable, eur(taxable * rule.rate), ZERO, None, usages)
    if realized < 0 and rule.losses_kind == "diversi":
        return SaleTax(ZERO, ZERO, eur(-realized * rule.base_factor), loss_expiry(on))
    return SaleTax(ZERO, ZERO, ZERO, None)


def loss_lots(db: Session, account_id: int) -> list[LossLot]:
    """Zainetto: minus registrate meno gli utilizzi, ricalcolato dal ledger."""
    used: dict[int, Decimal] = {}
    for u in db.scalars(select(LossUsage).where(LossUsage.account_id == account_id)):
        used[u.loss_entry_id] = used.get(u.loss_entry_id, ZERO) + u.amount_eur
    lots = []
    q = select(LedgerEntry).where(LedgerEntry.account_id == account_id, LedgerEntry.loss_added_eur.is_not(None))
    for e in db.scalars(q):
        if e.loss_added_eur and e.loss_added_eur > 0:
            lots.append(LossLot(e.id, e.ts.date(), e.loss_expiry, e.loss_added_eur - used.get(e.id, ZERO),
                                e.fiscal_category))
    return sorted(lots, key=lambda lot: (lot.origin, lot.entry_id))


# --- Imposta di bollo -------------------------------------------------------------

def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def stamp_duty(daily_values: dict[date, Decimal], start: date, end: date, rate: Decimal) -> Decimal:
    """Bollo pro rata: per ogni giorno da `start` a `end` (inclusi) si applica rate/giorni_anno
    al controvalore di mercato di quel giorno. I giorni senza valutazione riprendono l'ultima nota."""
    total = ZERO
    last = ZERO
    for d in sorted(k for k in daily_values if k < start):
        last = daily_values[d]
    day = start
    while day <= end:
        if day in daily_values:
            last = daily_values[day]
        total += last * rate / days_in_year(day.year)
        day += timedelta(days=1)
    return eur(total)
