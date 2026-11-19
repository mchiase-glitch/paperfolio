import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..data_provider import get_provider
from ..database import utcnow
from ..models import Account, CorporateEvent, Instrument, LedgerEntry, TaxRule, WithholdingRate
from . import positions, prices, settings
from .fx import to_eur
from .money import ZERO, eur
from .orders import compute, record_trade

ROME = ZoneInfo(config.DISPLAY_TZ)
log = logging.getLogger("paperfolio.events")


def day_start(d: date) -> datetime:
    """Inizio della giornata (ora di Roma): ciò che è avvenuto prima dà diritto all'evento."""
    return datetime.combine(d, time(0), ROME)


def add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def estimate_pay_date(inst: Instrument, ex_date: date) -> date:
    """Stima quando la fonte non dà la data di pagamento; resta modificabile dall'app."""
    if inst.market == "USA":
        return ex_date + timedelta(days=21)
    if inst.type == "etf":
        return ex_date + timedelta(days=14)
    return add_business_days(ex_date, 2)  # Borsa Italiana e principali borse UE


def unadjust_dividends(dividends: list[tuple[date, Decimal]], splits: list[tuple[date, Decimal]]):
    """La fonte riporta i dividendi passati già divisi per gli split successivi: si ricostruisce l'importo reale."""
    out = []
    for ex, amount in dividends:
        factor = Decimal("1")
        for split_date, ratio in splits:
            if split_date > ex:
                factor *= ratio
        out.append((ex, amount * factor))
    return out


def it_num(value: Decimal) -> str:
    """Numero in forma italiana per le descrizioni (virgola decimale)."""
    return f"{value.normalize():f}".replace(".", ",")


def split_label(ratio: Decimal) -> str:
    if ratio >= 1:
        return f"Frazionamento {it_num(ratio)}×1"
    return f"Raggruppamento 1×{it_num((1 / ratio).quantize(Decimal('0.01')))}"


# --- Sincronizzazione dalla fonte -------------------------------------------------

def sync_instrument(db: Session, inst: Instrument, since: date) -> int:
    acts = get_provider().corporate_actions(inst.symbol)
    events = {(e.kind, e.ex_date): e for e in db.scalars(select(CorporateEvent)
                                                           .where(CorporateEvent.instrument_id == inst.id))}
    announced = {ex: pay for ex, pay in acts.announced}
    created = 0

    for ex, amount in unadjust_dividends(acts.dividends, acts.splits):
        if ex < since:
            continue
        ev = events.get(("dividend", ex))
        if ev is None:
            pay = announced.get(ex)
            ev = CorporateEvent(instrument_id=inst.id, kind="dividend", ex_date=ex, amount=amount, source="yfinance",
                                pay_date=pay or estimate_pay_date(inst, ex), pay_date_estimated=0 if pay else 1)
            db.add(ev)
            events[("dividend", ex)] = ev
            created += 1
        elif ev.amount is None:
            ev.amount = amount  # annunciato in precedenza senza importo

    for ex, pay in announced.items():
        if ex < since:
            continue
        ev = events.get(("dividend", ex))
        if ev is None:
            db.add(CorporateEvent(instrument_id=inst.id, kind="dividend", ex_date=ex, pay_date=pay,
                                  pay_date_estimated=0, source="yfinance"))
            created += 1
        elif ev.pay_date_estimated and ev.source == "yfinance" and not _processed_anywhere(db, ev):
            ev.pay_date, ev.pay_date_estimated = pay, 0

    for ex, ratio in acts.splits:
        if ex >= since and ("split", ex) not in events:
            db.add(CorporateEvent(instrument_id=inst.id, kind="split", ex_date=ex, ratio=ratio, source="yfinance"))
            created += 1
    db.commit()
    return created


def sync_all(db: Session) -> None:
    """Interroga la fonte per ogni strumento movimentato nei conti aperti, dalla data del primo acquisto."""
    first_trade: dict[int, date] = {}
    q = (select(LedgerEntry).join(Account, Account.id == LedgerEntry.account_id)
         .where(Account.closed_at.is_(None), LedgerEntry.kind == "buy"))
    for e in db.scalars(q):
        d = e.ts.astimezone(ROME).date()
        first_trade[e.instrument_id] = min(d, first_trade.get(e.instrument_id, d))
    for instrument_id, since in first_trade.items():
        inst = db.get(Instrument, instrument_id)
        if inst.data_source != "yfinance":
            continue
        try:
            sync_instrument(db, inst, since)
        except Exception as exc:
            db.rollback()
            log.warning("Eventi societari non aggiornati per %s: %s", inst.symbol, exc)


# --- Effetti sul conto ------------------------------------------------------------

def _processed(db: Session, account_id: int, ev: CorporateEvent) -> bool:
    kind = "split" if ev.kind == "split" else "dividend"
    return db.scalar(select(LedgerEntry.id).where(LedgerEntry.account_id == account_id,
                                                  LedgerEntry.corporate_event_id == ev.id,
                                                  LedgerEntry.kind == kind)) is not None


def _processed_anywhere(db: Session, ev: CorporateEvent) -> bool:
    if ev.id is None:
        return False
    return db.scalar(select(LedgerEntry.id).where(LedgerEntry.corporate_event_id == ev.id)) is not None


@dataclass
class DividendAmounts:
    quantity: Decimal
    gross_ccy: Decimal
    fx_market: Decimal
    fx_spread: Decimal
    fx_applied: Decimal
    gross_eur: Decimal
    withholding_rate: Decimal
    withholding_eur: Decimal
    tax_eur: Decimal  # imposta italiana sul netto della ritenuta estera
    net_eur: Decimal


def dividend_amounts(db: Session, inst: Instrument, quantity: Decimal, amount: Decimal,
                     fx_market: Decimal) -> DividendAmounts:
    """Prima la ritenuta del paese emittente (solo azioni estere), poi l'aliquota italiana sul netto."""
    gross_ccy = quantity * amount * inst.multiplier
    conv = to_eur(gross_ccy, inst.currency, fx_market, settings.get_decimal(db, "fx_spread"), "sell")
    gross_eur = eur(conv.amount_eur)
    rate = ZERO
    if inst.type == "stock" and inst.country and inst.country != "IT":
        row = db.get(WithholdingRate, inst.country)
        rate = row.rate if row else ZERO
    withholding = eur(gross_eur * rate)
    rule = db.get(TaxRule, inst.fiscal_category)
    tax = eur((gross_eur - withholding) * rule.rate * rule.base_factor)
    return DividendAmounts(quantity, gross_ccy, conv.market_rate, conv.spread, conv.applied_rate, gross_eur,
                           rate, withholding, tax, gross_eur - withholding - tax)


def credit_dividend(db: Session, account: Account, inst: Instrument, ev: CorporateEvent) -> LedgerEntry | None:
    qty = positions.position(db, account.id, inst.id, before=day_start(ev.ex_date)).quantity
    if qty <= 0:
        return None
    fx_market, _ = prices.get_fx(db, inst.currency)
    a = dividend_amounts(db, inst, qty, ev.amount, fx_market)
    entry = LedgerEntry(
        account_id=account.id, ts=day_start(ev.pay_date), kind="dividend", instrument_id=inst.id,
        quantity=qty, price=ev.amount, price_currency=inst.currency, fx_market=a.fx_market, fx_spread=a.fx_spread,
        fx_applied=a.fx_applied, gross_eur=a.gross_eur, withholding_eur=a.withholding_eur, tax_eur=a.tax_eur,
        cash_delta_eur=a.net_eur, fiscal_category=inst.fiscal_category, corporate_event_id=ev.id,
        description=(f"{'Distribuzione' if inst.type == 'etf' else 'Dividendo'} {it_num(ev.amount)} "
                     f"{inst.currency} × {it_num(qty)} (stacco {ev.ex_date:%d/%m/%Y})"),
    )
    db.add(entry)
    return entry


def apply_split(db: Session, account: Account, inst: Instrument, ev: CorporateEvent) -> LedgerEntry | None:
    start = day_start(ev.ex_date)
    qty = positions.position(db, account.id, inst.id, before=start).quantity
    if qty <= 0:
        return None
    new_qty = qty * ev.ratio
    whole = Decimal(math.floor(new_qty))
    fraction = new_qty - whole
    price_info = fx_market = None
    if fraction > 0:
        # Prezzo letto prima di scrivere: se manca, si riprova al giro successivo
        price_info = prices.get_price(db, inst)
        fx_market, _ = prices.get_fx(db, inst.currency)
    entry = LedgerEntry(account_id=account.id, ts=start, kind="split", instrument_id=inst.id, quantity=qty,
                        ratio=ev.ratio, corporate_event_id=ev.id,
                        description=f"{split_label(ev.ratio)}: {it_num(qty)} → {it_num(new_qty)}")
    db.add(entry)
    db.flush()
    if fraction > 0:
        pv = compute(db, account, inst, "sell", fraction, price_info, fx_market, start, charge_commission=False)
        record_trade(db, account, inst, pv, start, corporate_event_id=ev.id,
                     description=f"Liquidazione della frazione di {it_num(fraction)} da {split_label(ev.ratio).lower()}")
    return entry


def process(db: Session, now: datetime | None = None) -> int:
    """Applica gli split dalla data di efficacia e accredita i dividendi alla data di pagamento."""
    today = (now or utcnow()).astimezone(ROME).date()
    done = 0
    accounts = list(db.scalars(select(Account).where(Account.closed_at.is_(None))))
    for ev in db.scalars(select(CorporateEvent).order_by(CorporateEvent.ex_date, CorporateEvent.id)):
        due = (ev.kind == "split" and ev.ex_date <= today) or \
              (ev.kind == "dividend" and ev.amount is not None and ev.pay_date is not None and ev.pay_date <= today)
        if not due:
            continue
        inst = db.get(Instrument, ev.instrument_id)
        for account in accounts:
            if _processed(db, account.id, ev):
                continue
            try:
                entry = apply_split(db, account, inst, ev) if ev.kind == "split" else credit_dividend(db, account, inst, ev)
                db.commit()
                done += entry is not None
            except Exception as exc:
                db.rollback()
                log.warning("Evento %s non elaborato: %s", ev.id, exc)
    return done


def upcoming_dividends(db: Session, account: Account, now: datetime | None = None) -> list[dict]:
    """Dividendi già maturati (stacco passato) in attesa della data di pagamento."""
    today = (now or utcnow()).astimezone(ROME).date()
    out = []
    q = select(CorporateEvent).where(CorporateEvent.kind == "dividend", CorporateEvent.amount.is_not(None),
                                     CorporateEvent.ex_date <= today, CorporateEvent.pay_date > today)
    for ev in db.scalars(q.order_by(CorporateEvent.pay_date)):
        if _processed(db, account.id, ev):
            continue
        inst = db.get(Instrument, ev.instrument_id)
        qty = positions.position(db, account.id, inst.id, before=day_start(ev.ex_date)).quantity
        if qty <= 0:
            continue
        try:
            fx_market, _ = prices.get_fx(db, inst.currency)
        except Exception:
            continue
        a = dividend_amounts(db, inst, qty, ev.amount, fx_market)
        out.append({"event_id": ev.id, "instrument_id": inst.id, "name": inst.name, "symbol": inst.symbol,
                    "ex_date": ev.ex_date, "pay_date": ev.pay_date, "pay_date_estimated": bool(ev.pay_date_estimated),
                    "quantity": qty, "amount": ev.amount, "currency": inst.currency,
                    "gross_eur": a.gross_eur, "net_eur": a.net_eur})
    return out
