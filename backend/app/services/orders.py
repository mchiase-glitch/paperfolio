from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import utcnow
from ..models import Account, CommissionRule, Instrument, LedgerEntry, LossUsage, Order, TaxRule
from . import bonds, market_hours, positions, prices, settings
from .commission import commission, tobin_tax
from .fx import to_eur
from .money import ZERO, eur
from .tax import compute_sale_tax, loss_lots

ROME = ZoneInfo(config.DISPLAY_TZ)


class OrderError(Exception):
    pass


@dataclass
class OrderPreview:
    instrument_id: int
    side: str
    quantity: Decimal
    price: Decimal
    price_currency: str
    price_time: datetime
    is_manual: bool
    fx_market: Decimal
    fx_spread: Decimal
    fx_applied: Decimal
    gross_ccy: Decimal
    gross_eur: Decimal
    accrued_interest_eur: Decimal  # rateo lordo (obbligazioni)
    commission_eur: Decimal
    tobin_tax_eur: Decimal
    tax_eur: Decimal  # imposta stimata (vendite)
    net_eur: Decimal  # addebito (acquisto) o accredito (vendita)
    realized_fiscal_eur: Decimal | None
    realized_gross_eur: Decimal | None
    market_open: bool
    executes_now: bool
    next_open: datetime | None
    reserved_eur: Decimal  # liquidità prenotata se l'ordine resta in attesa
    accrued_interest: Decimal = ZERO  # rateo lordo in valuta dello strumento
    interest_tax_eur: Decimal = ZERO  # imposta sul rateo (vendita) o credito d'imposta (acquisto, negativo)
    settlement_date: date | None = None
    tax_detail: object | None = field(default=None, repr=False)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("tax_detail")
        return d


def _commission_rule(db: Session, inst: Instrument) -> CommissionRule:
    rule = db.scalar(select(CommissionRule).where(CommissionRule.instrument_type == inst.type,
                                                  CommissionRule.market == inst.market))
    if rule is None:
        raise OrderError(f"Nessuna commissione configurata per {inst.type}/{inst.market}")
    return rule


def preview(db: Session, account: Account, inst: Instrument, side: str, quantity: Decimal,
            now: datetime | None = None) -> OrderPreview:
    if side not in ("buy", "sell"):
        raise OrderError("Lato dell'ordine non valido")
    if quantity <= 0:
        raise OrderError("La quantità deve essere maggiore di zero")
    if inst.type in ("stock", "etf") and quantity != quantity.to_integral_value():
        raise OrderError("Per azioni ed ETF la quantità deve essere un numero intero")
    now = now or utcnow()
    if inst.type == "bond":
        lot = inst.lot_size or Decimal("1000")
        if quantity % lot != 0:
            raise OrderError(f"Il nominale deve essere un multiplo del taglio minimo ({lot.normalize():f})")
        if bonds.settlement_date(inst, now.astimezone(ROME).date()) >= inst.maturity:
            raise OrderError("Obbligazione scaduta o in scadenza: non è più negoziabile")
    p = prices.get_price(db, inst, max_age=15, now=now)
    if p.currency != inst.currency:
        raise OrderError(f"Valuta del prezzo ({p.currency}) diversa da quella dello strumento ({inst.currency})")
    fx_market, _ = prices.get_fx(db, inst.currency)
    return compute(db, account, inst, side, quantity, p, fx_market, now)


def compute(db: Session, account: Account, inst: Instrument, side: str, quantity: Decimal,
            p: prices.PriceInfo, fx_market: Decimal, now: datetime, charge_commission: bool = True,
            settlement: date | None = None) -> OrderPreview:
    """Importi, imposte e stato del mercato per un'operazione a un prezzo dato."""
    spread = settings.get_decimal(db, "fx_spread")
    gross_ccy = quantity * p.price * inst.multiplier  # obbligazioni: moltiplicatore 0,01 (prezzo in %)
    conv = to_eur(gross_ccy, inst.currency, fx_market, spread, side)
    gross_eur = eur(conv.amount_eur)
    comm = ZERO
    if charge_commission:
        rule = _commission_rule(db, inst)
        comm = commission(gross_eur, rule.fixed_eur, rule.pct, rule.minimum_eur)
    tobin = tobin_tax(inst.type, inst.country, side, gross_eur, settings.get_decimal(db, "tobin_rate"))

    # Rateo: chi compra lo paga al venditore; in entrambi i casi la banca applica l'imposta
    # dello strumento (credito per chi compra), così si tassa solo l'interesse maturato nel possesso
    accrued_ccy = accrued_eur = interest_tax = ZERO
    if inst.type == "bond":
        settlement = settlement or bonds.settlement_date(inst, now.astimezone(ROME).date())
        accrued_ccy = eur(quantity * bonds.accrued_per100(inst, settlement) / 100)
        if accrued_ccy:
            accrued_eur = eur(to_eur(accrued_ccy, inst.currency, fx_market, spread, side).amount_eur)
            interest_tax = eur(accrued_eur * _interest_rate(db, inst))

    tax_eur, realized_fiscal, realized_gross, tax_detail = ZERO, None, None, None
    if side == "buy":
        net = gross_eur + accrued_eur - interest_tax + comm + tobin
        interest_tax = -interest_tax
    else:
        pos = positions.position(db, account.id, inst.id)
        if pos.quantity > 0:
            sold = min(quantity, pos.quantity)
            fraction = sold / pos.quantity
            # In caso di quantità oltre il posseduto il calcolo fiscale riguarda solo la parte posseduta
            proceeds = gross_eur * sold / quantity
            realized_gross = eur(proceeds - pos.cost_gross_eur * fraction)
            realized_fiscal = eur(proceeds - comm - pos.cost_fiscal_eur * fraction)
            tax_rule = db.get(TaxRule, inst.fiscal_category)
            if tax_rule is None:
                raise OrderError(f"Categoria fiscale sconosciuta: {inst.fiscal_category}")
            tax_detail = compute_sale_tax(realized_fiscal, tax_rule, loss_lots(db, account.id),
                                          now.astimezone(ROME).date())
            tax_eur = tax_detail.tax
        net = gross_eur + accrued_eur - interest_tax - comm - tax_eur

    session_open = market_hours.session_open(inst.exchange, now)
    market_open = session_open is not None
    fresh = market_open and (p.is_manual or p.price_time >= session_open)
    reserved = ZERO
    if side == "buy" and not fresh:
        reserved = eur(net * (1 + settings.get_decimal(db, "reservation_margin")))
    return OrderPreview(
        instrument_id=inst.id, side=side, quantity=quantity, price=p.price, price_currency=p.currency,
        price_time=p.price_time, is_manual=p.is_manual, fx_market=conv.market_rate, fx_spread=conv.spread,
        fx_applied=conv.applied_rate, gross_ccy=gross_ccy, gross_eur=gross_eur, accrued_interest_eur=accrued_eur,
        commission_eur=comm, tobin_tax_eur=tobin, tax_eur=tax_eur, net_eur=net,
        realized_fiscal_eur=realized_fiscal, realized_gross_eur=realized_gross,
        market_open=market_open, executes_now=fresh,
        next_open=None if market_open else market_hours.next_open(inst.exchange, now),
        reserved_eur=reserved, accrued_interest=accrued_ccy, interest_tax_eur=interest_tax,
        settlement_date=settlement, tax_detail=tax_detail,
    )


def _interest_rate(db: Session, inst: Instrument) -> Decimal:
    """Aliquota effettiva sugli interessi: 12,5% per la white list (26% × 48,08%), 26% per le altre."""
    rule = db.get(TaxRule, inst.fiscal_category)
    return rule.rate * rule.base_factor


def _check(db: Session, account: Account, inst: Instrument, pv: OrderPreview, amount_needed: Decimal,
           exclude_order_id: int | None = None) -> None:
    if pv.side == "buy":
        available = positions.cash_balance(db, account.id) - positions.reserved_cash(db, account.id, exclude_order_id)
        if available < amount_needed:
            raise OrderError(f"Liquidità insufficiente: servono {amount_needed} €, disponibili {eur(available)} €")
    else:
        held = positions.position(db, account.id, inst.id).quantity
        free = held - positions.pending_sell_quantity(db, account.id, inst.id, exclude_order_id)
        if pv.quantity > free:
            if not settings.get_bool(db, "allow_short_selling"):
                raise OrderError(f"Vendita allo scoperto non consentita: quantità disponibile {free}")
            raise OrderError("Le posizioni short saranno gestite insieme ai derivati")


def place_order(db: Session, account: Account, inst: Instrument, side: str, quantity: Decimal,
                now: datetime | None = None) -> Order:
    now = now or utcnow()
    pv = preview(db, account, inst, side, quantity, now)
    _check(db, account, inst, pv, pv.net_eur if pv.executes_now else pv.reserved_eur)
    order = Order(account_id=account.id, instrument_id=inst.id, side=side, quantity=quantity,
                  status="pending", reserved_eur=pv.reserved_eur, created_at=now)
    db.add(order)
    db.flush()
    if pv.executes_now:
        _execute(db, account, inst, order, pv, now)
    db.commit()
    return order


def _execute(db: Session, account: Account, inst: Instrument, order: Order, pv: OrderPreview, now: datetime) -> None:
    record_trade(db, account, inst, pv, now, order_id=order.id, position_side=order.position_side)
    order.status = "executed"
    order.executed_at = now


def record_trade(db: Session, account: Account, inst: Instrument, pv: OrderPreview, now: datetime,
                 order_id: int | None = None, position_side: str = "long", kind: str | None = None,
                 **extra) -> LedgerEntry:
    if inst.type == "bond":
        extra.update(accrued_interest=pv.accrued_interest, accrued_interest_eur=pv.accrued_interest_eur,
                     interest_tax_eur=pv.interest_tax_eur, settlement_date=pv.settlement_date)
    entry = LedgerEntry(
        account_id=account.id, ts=now, kind=kind or pv.side, instrument_id=inst.id, order_id=order_id,
        position_side=position_side, quantity=pv.quantity, price=pv.price, price_currency=pv.price_currency,
        fx_market=pv.fx_market, fx_spread=pv.fx_spread, fx_applied=pv.fx_applied, gross_eur=pv.gross_eur,
        commission_eur=pv.commission_eur, tobin_tax_eur=pv.tobin_tax_eur, tax_eur=pv.tax_eur,
        cash_delta_eur=-pv.net_eur if pv.side == "buy" else pv.net_eur,
        fiscal_category=inst.fiscal_category, **extra,
    )
    if pv.side == "sell":
        entry.realized_gross_eur = pv.realized_gross_eur
        entry.realized_fiscal_eur = pv.realized_fiscal_eur
        if pv.tax_detail is not None:
            entry.taxable_eur = pv.tax_detail.taxable
            if pv.tax_detail.loss_added > 0:
                entry.loss_added_eur = pv.tax_detail.loss_added
                entry.loss_expiry = pv.tax_detail.loss_expiry
    db.add(entry)
    db.flush()
    if pv.side == "sell" and pv.tax_detail is not None:
        for loss_entry_id, amount in pv.tax_detail.usages:
            db.add(LossUsage(account_id=account.id, loss_entry_id=loss_entry_id, used_by_entry_id=entry.id,
                             amount_eur=amount, ts=now))
    return entry


def cancel_order(db: Session, order: Order, now: datetime | None = None) -> Order:
    if order.status != "pending":
        raise OrderError("Si possono annullare solo gli ordini in attesa")
    order.status = "cancelled"
    order.cancelled_at = now or utcnow()
    db.commit()
    return order


def process_pending(db: Session, now: datetime | None = None) -> list[Order]:
    """Esegue gli ordini in attesa al primo prezzo successivo all'apertura."""
    now = now or utcnow()
    done = []
    for order in list(db.scalars(select(Order).where(Order.status == "pending").order_by(Order.created_at))):
        inst = db.get(Instrument, order.instrument_id)
        account = db.get(Account, order.account_id)
        if account.closed_at is not None or not market_hours.is_open(inst.exchange, now):
            continue
        try:
            pv = preview(db, account, inst, order.side, order.quantity, now)
        except OrderError as exc:  # es. obbligazione arrivata a scadenza
            order.status, order.note = "rejected", str(exc)
            db.commit()
            done.append(order)
            continue
        except Exception:
            continue  # prezzo non disponibile: si riprova al prossimo giro
        if not pv.executes_now:
            continue
        try:
            _check(db, account, inst, pv, pv.net_eur, exclude_order_id=order.id)
        except OrderError as exc:
            order.status = "rejected"
            order.note = str(exc)
            db.commit()
            done.append(order)
            continue
        _execute(db, account, inst, order, pv, now)
        db.commit()
        done.append(order)
    return done
