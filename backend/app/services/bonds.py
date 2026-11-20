"""Calcoli sulle obbligazioni a tasso fisso: calendario cedole, rateo, rendimento a scadenza.

Convenzioni:
- prezzo in % del nominale, corso secco (senza rateo); importi "per 100" di nominale
- cedole regolari ricavate a ritroso dalla scadenza; la prima cedola è ridotta se l'emissione
  cade dentro il periodo (cedola corta). Le prime cedole lunghe non sono gestite.
- giorni: ACT/ACT ICMA (BTP e la maggior parte delle obbligazioni in euro) oppure 30/360
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..models import Instrument
from . import market_hours

HUNDRED = Decimal("100")
ZERO = Decimal("0")
SETTLEMENT_DAYS = 2
DAY_COUNTS = ("ACT/ACT", "30/360")
FREQUENCIES = (1, 2, 4, 12)


def add_months(d: date, months: int, anchor_day: int | None = None) -> date:
    """Sposta di `months` mesi mantenendo il giorno di riferimento (limitato alla fine del mese)."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    day = anchor_day or d.day
    return date(y, m, min(day, monthrange(y, m)[1]))


def _step(inst: Instrument) -> int:
    return 12 // inst.coupon_frequency


def regular_date(inst: Instrument, k: int) -> date:
    """k-esima data cedolare regolare prima della scadenza (k = 0 è la scadenza)."""
    return add_months(inst.maturity, -k * _step(inst), inst.maturity.day)


def previous_coupon(inst: Instrument, d: date) -> tuple[date, date]:
    """Periodo cedolare regolare che contiene `d`: (inizio incluso, fine esclusa)."""
    k = 0
    while regular_date(inst, k) > d:
        k += 1
    return regular_date(inst, k), regular_date(inst, k - 1) if k > 0 else add_months(inst.maturity, _step(inst))


def days_30_360(start: date, end: date) -> int:
    """30E/360: ogni mese conta 30 giorni."""
    d1, d2 = min(start.day, 30), min(end.day, 30)
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


def _period_coupon(inst: Instrument) -> Decimal:
    return inst.coupon_rate * HUNDRED / inst.coupon_frequency


def _fraction(inst: Instrument, start: date, end: date, period_start: date, period_end: date) -> Decimal:
    """Quota del periodo cedolare maturata tra `start` ed `end`."""
    if inst.day_count == "30/360":
        return Decimal(days_30_360(start, end)) * inst.coupon_frequency / 360
    return Decimal((end - start).days) / Decimal((period_end - period_start).days)


def accrued_per100(inst: Instrument, settlement: date) -> Decimal:
    """Rateo lordo maturato alla data di regolamento, per 100 di nominale."""
    if not inst.coupon_rate or settlement >= inst.maturity:
        return ZERO
    if inst.issue_date and settlement <= inst.issue_date:
        return ZERO
    prev, nxt = previous_coupon(inst, settlement)
    start = max(prev, inst.issue_date) if inst.issue_date else prev
    return _period_coupon(inst) * _fraction(inst, start, settlement, prev, nxt)


def coupon_schedule(inst: Instrument, after: date) -> list[tuple[date, Decimal]]:
    """Cedole con data successiva ad `after`, fino alla scadenza: (data, importo per 100)."""
    out = []
    k = 0
    while True:
        d = regular_date(inst, k)
        if d <= after or (inst.issue_date and d <= inst.issue_date):
            break
        out.append(d)
        k += 1
    out.reverse()
    result = []
    for d in out:
        amount = _period_coupon(inst) if inst.coupon_rate else ZERO
        prev = add_months(d, -_step(inst), inst.maturity.day)
        if inst.coupon_rate and inst.issue_date and inst.issue_date > prev:
            amount = _period_coupon(inst) * _fraction(inst, inst.issue_date, d, prev, d)  # cedola corta
        if amount > 0:
            result.append((d, amount))
    return result


def settlement_date(inst: Instrument, trade_day: date) -> date:
    return market_hours.add_sessions(inst.exchange, trade_day, SETTLEMENT_DAYS)


@dataclass
class Yield:
    gross: Decimal | None
    net: Decimal | None


def _solve(flows: list[tuple[Decimal, Decimal]], price: Decimal) -> Decimal | None:
    """Tasso annuo composto che uguaglia il valore attuale dei flussi al prezzo (bisezione)."""
    def pv(y: Decimal) -> Decimal:
        return sum((cf / (1 + y) ** t for t, cf in flows), ZERO)

    lo, hi = Decimal("-0.5"), Decimal("1")
    if not (pv(hi) <= price <= pv(lo)):
        return None
    for _ in range(45):  # precisione ben oltre il millesimo di punto
        mid = (lo + hi) / 2
        if pv(mid) > price:
            lo = mid
        else:
            hi = mid
    return ((lo + hi) / 2).quantize(Decimal("0.000001"))


def yield_to_maturity(inst: Instrument, clean: Decimal, settlement: date, tax_rate: Decimal) -> Yield:
    """Rendimento effettivo annuo a scadenza, lordo e netto.

    Netto: cedole e rateo al netto dell'imposta, imposta sulla differenza tra rimborso e prezzo se positiva.
    Commissioni escluse.
    """
    if settlement >= inst.maturity:
        return Yield(None, None)
    accrued = accrued_per100(inst, settlement)
    schedule = coupon_schedule(inst, settlement)

    def flows(t_rate: Decimal) -> list[tuple[Decimal, Decimal]]:
        out = [(Decimal((d - settlement).days) / 365, amount * (1 - t_rate)) for d, amount in schedule]
        gain_tax = max(HUNDRED - clean, ZERO) * t_rate
        out.append((Decimal((inst.maturity - settlement).days) / 365, HUNDRED - gain_tax))
        return out

    gross = _solve(flows(ZERO), clean + accrued)
    net = _solve(flows(tax_rate), clean + accrued * (1 - tax_rate))
    return Yield(gross, net)
