from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import utcnow
from ..models import Account, DailyValuation, Instrument, LedgerEntry, Order, TaxRule
from . import positions, prices, settings
from .commission import commission
from .money import ZERO, eur
from .orders import _commission_rule
from .tax import stamp_duty

ROME = ZoneInfo(config.DISPLAY_TZ)


def rome_date(when: datetime) -> date:
    return when.astimezone(ROME).date()


def active_account(db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.closed_at.is_(None)).order_by(Account.id.desc()))
    if account is None:
        account = open_account(db, config.INITIAL_CAPITAL)
    return account


def open_account(db: Session, capital: Decimal, now: datetime | None = None) -> Account:
    now = now or utcnow()
    account = Account(name="Portafoglio", initial_capital=capital, created_at=now)
    db.add(account)
    db.flush()
    db.add(LedgerEntry(account_id=account.id, ts=now, kind="deposit", cash_delta_eur=eur(capital),
                       description="Capitale iniziale"))
    db.commit()
    return account


def _position_rows(db: Session, account: Account, now: datetime) -> list[dict]:
    rows = []
    today_entries = {}
    for e in positions.ledger(db, account.id):
        if e.kind in ("buy", "sell"):
            today_entries.setdefault(e.instrument_id, []).append(e)
    for (instrument_id, side), pos in positions.open_positions(db, account.id).items():
        inst = db.get(Instrument, instrument_id)
        row = {"instrument": inst, "position": pos, "side": side, "error": None}
        try:
            p = prices.get_price(db, inst)
            fx, _ = prices.get_fx(db, inst.currency)
        except Exception as exc:
            row["error"] = str(exc)
            rows.append(row)
            continue
        mv_ccy = pos.quantity * p.price * inst.multiplier
        mv_eur = mv_ccy / fx
        # Variazione del giorno: si confronta con la chiusura precedente, tenendo conto delle operazioni di oggi
        trade_day = rome_date(p.price_time)
        day_ccy = ZERO
        if p.prev_close is not None:
            qty_start = pos.quantity
            flows = ZERO
            for e in today_entries.get(instrument_id, []):
                if rome_date(e.ts) >= trade_day:
                    sign = 1 if e.kind == "buy" else -1
                    qty_start -= sign * e.quantity
                    flows += sign * e.quantity * e.price
            day_ccy = (pos.quantity * p.price - qty_start * p.prev_close - flows) * inst.multiplier
        row.update(price=p, fx=fx, mv_ccy=mv_ccy, mv_eur=mv_eur, day_eur=day_ccy / fx)
        rows.append(row)
    return rows


def positions_value(db: Session, account: Account, now: datetime | None = None) -> Decimal:
    return sum((r["mv_eur"] for r in _position_rows(db, account, now or utcnow()) if r["error"] is None), ZERO)


def snapshot(db: Session, account: Account, now: datetime | None = None) -> None:
    now = now or utcnow()
    value = eur(positions_value(db, account, now))
    day = rome_date(now)
    row = db.get(DailyValuation, (account.id, day))
    if row is None:
        db.add(DailyValuation(account_id=account.id, day=day, positions_value_eur=value))
    else:
        row.positions_value_eur = value
    db.commit()


def _daily_values(db: Session, account: Account) -> dict[date, Decimal]:
    q = select(DailyValuation).where(DailyValuation.account_id == account.id)
    return {r.day: r.positions_value_eur for r in db.scalars(q)}


def _stamp_start(db: Session, account: Account, year: int) -> date:
    return max(date(year, 1, 1), rome_date(account.created_at))


def stamp_estimate(db: Session, account: Account, now: datetime | None = None) -> Decimal:
    """Bollo maturato nell'anno in corso fino a oggi (oggi valorizzato ai prezzi attuali)."""
    now = now or utcnow()
    today = rome_date(now)
    values = _daily_values(db, account)
    values[today] = eur(positions_value(db, account, now))
    return stamp_duty(values, _stamp_start(db, account, today.year), today, settings.get_decimal(db, "stamp_duty_rate"))


def stamp_charged(db: Session, account: Account, year: int) -> bool:
    return db.scalar(select(LedgerEntry.id).where(LedgerEntry.account_id == account.id,
                                                  LedgerEntry.kind == "stamp_duty",
                                                  LedgerEntry.tax_year == year)) is not None


def charge_stamp(db: Session, account: Account, year: int, end: date, when: datetime) -> Decimal:
    if stamp_charged(db, account, year):
        return ZERO
    amount = stamp_duty(_daily_values(db, account), _stamp_start(db, account, year), end,
                        settings.get_decimal(db, "stamp_duty_rate"))
    if amount > 0:
        db.add(LedgerEntry(account_id=account.id, ts=when, kind="stamp_duty", cash_delta_eur=-amount,
                           tax_eur=amount, tax_year=year,
                           description=f"Imposta di bollo {year} (dal {_stamp_start(db, account, year):%d/%m} al {end:%d/%m})"))
        db.commit()
    return amount


def charge_past_years(db: Session, now: datetime | None = None) -> None:
    """Addebita al 31/12 il bollo degli anni chiusi non ancora addebitato."""
    now = now or utcnow()
    for account in db.scalars(select(Account).where(Account.closed_at.is_(None))):
        for year in range(rome_date(account.created_at).year, rome_date(now).year):
            end = date(year, 12, 31)
            when = datetime.combine(end, time(23, 59), ROME)
            charge_stamp(db, account, year, end, when)


def reset(db: Session, capital: Decimal, now: datetime | None = None) -> Account:
    """Chiude il portafoglio (addebitando il bollo maturato) e ne apre uno nuovo. Lo storico resta."""
    now = now or utcnow()
    old = active_account(db)
    snapshot(db, old, now)
    charge_stamp(db, old, rome_date(now).year, rome_date(now), now)
    for o in db.scalars(select(Order).where(Order.account_id == old.id, Order.status == "pending")):
        o.status, o.cancelled_at, o.note = "cancelled", now, "Annullato per reset del portafoglio"
    old.closed_at = now
    db.commit()
    return open_account(db, capital, now)


def summary(db: Session, account: Account, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = _position_rows(db, account, now)
    cash = positions.cash_balance(db, account.id)
    reserved = positions.reserved_cash(db, account.id)

    realized_gross = realized_fiscal = sale_taxes = tobin = stamp = ZERO
    for e in positions.ledger(db, account.id):
        if e.kind == "sell":
            realized_gross += e.realized_gross_eur or ZERO
            realized_fiscal += e.realized_fiscal_eur or ZERO
            sale_taxes += e.tax_eur
        elif e.kind == "buy":
            tobin += e.tobin_tax_eur
        elif e.kind == "stamp_duty":
            stamp += e.tax_eur

    out_positions = []
    mv_total = unreal_gross = unreal_net = day_total = ZERO
    for r in rows:
        inst, pos = r["instrument"], r["position"]
        item = {
            "instrument_id": inst.id, "symbol": inst.symbol, "isin": inst.isin, "name": inst.name,
            "type": inst.type, "market": inst.market, "currency": inst.currency, "side": r["side"],
            "quantity": pos.quantity, "avg_price": pos.avg_price, "avg_cost_eur": pos.avg_cost_eur,
            "cost_eur": eur(pos.cost_fiscal_eur), "error": r["error"],
        }
        if r["error"] is None:
            p = r["price"]
            gross = r["mv_eur"] - pos.cost_gross_eur
            rule = db.get(TaxRule, inst.fiscal_category)
            sell_comm = commission(r["mv_eur"], *_comm_args(db, inst))
            fiscal = r["mv_eur"] - sell_comm - pos.cost_fiscal_eur
            est_tax = eur(fiscal * rule.base_factor * rule.rate) if rule and fiscal > 0 else ZERO
            net = fiscal - est_tax
            item.update(
                price=p.price, prev_close=p.prev_close, price_time=p.price_time, is_manual=p.is_manual,
                stale=p.stale, fx_market=r["fx"], market_value_ccy=r["mv_ccy"], market_value_eur=eur(r["mv_eur"]),
                pnl_gross_eur=eur(gross), pnl_net_eur=eur(net),
                pnl_pct=(gross / pos.cost_gross_eur * 100) if pos.cost_gross_eur else ZERO,
                day_change_eur=eur(r["day_eur"]),
                day_change_pct=((p.price / p.prev_close - 1) * 100) if p.prev_close else None,
            )
            mv_total += r["mv_eur"]
            unreal_gross += gross
            unreal_net += net
            day_total += r["day_eur"]
        out_positions.append(item)

    stamp_est = stamp_estimate(db, account, now)
    realized_net = realized_fiscal - sale_taxes - tobin - stamp
    total_value = cash + mv_total
    return {
        "account_id": account.id, "as_of": now, "initial_capital": account.initial_capital,
        "total_value": eur(total_value), "positions_value": eur(mv_total),
        "cash": eur(cash), "reserved": eur(reserved), "available": eur(cash - reserved),
        "pnl": {
            "day": eur(day_total),
            "day_pct": (day_total / (mv_total - day_total) * 100) if mv_total - day_total else ZERO,
            "realized_gross": eur(realized_gross), "realized_net": eur(realized_net),
            "unrealized_gross": eur(unreal_gross), "unrealized_net": eur(unreal_net),
            "total_gross": eur(realized_gross + unreal_gross),
            "total_net": eur(realized_net + unreal_net - stamp_est),
        },
        "stamp_duty_estimate": stamp_est,
        "positions": out_positions,
    }


def _comm_args(db: Session, inst: Instrument) -> tuple[Decimal, Decimal, Decimal]:
    rule = _commission_rule(db, inst)
    return rule.fixed_eur, rule.pct, rule.minimum_eur
