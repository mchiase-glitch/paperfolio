from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import utcnow
from ..models import Account, AppSetting, DailyValuation, Instrument, LedgerEntry, Order, TaxRule
from . import bonds, corporate_events, positions, prices, settings
from .commission import commission
from .money import ZERO, eur
from .orders import _commission_rule
from .tax import stamp_duty

ROME = ZoneInfo(config.DISPLAY_TZ)


def rome_date(when: datetime) -> date:
    return when.astimezone(ROME).date()


CURRENT_KEY = "current_account_id"


def open_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.closed_at.is_(None)).order_by(Account.id)))


def active_account(db: Session) -> Account:
    """Portafoglio selezionato nell'app (uno solo alla volta, valido per tutti i dispositivi)."""
    row = db.get(AppSetting, CURRENT_KEY)
    if row:
        account = db.get(Account, int(row.value))
        if account is not None and account.closed_at is None:
            return account
    account = db.scalar(select(Account).where(Account.closed_at.is_(None)).order_by(Account.id.desc()))
    if account is None:
        return open_account(db, config.INITIAL_CAPITAL)
    select_account(db, account)
    return account


def select_account(db: Session, account: Account) -> None:
    settings.set_value(db, CURRENT_KEY, str(account.id))
    db.commit()


def open_account(db: Session, capital: Decimal, now: datetime | None = None, name: str = "Portafoglio", set_current: bool = True) -> Account:
    now = now or utcnow()
    account = Account(name=name, initial_capital=capital, created_at=now)
    db.add(account)
    db.flush()
    db.add(LedgerEntry(account_id=account.id, ts=now, kind="deposit", cash_delta_eur=eur(capital),
                       description="Capitale iniziale"))
    if set_current:
        settings.set_value(db, CURRENT_KEY, str(account.id))
    db.commit()
    return account


def _position_rows(db: Session, account: Account, now: datetime,
                   max_age: int = prices.CACHE_SECONDS) -> list[dict]:
    rows = []
    today_entries = {}
    for e in positions.ledger(db, account.id):
        if e.kind in ("buy", "sell", "redemption"):
            today_entries.setdefault(e.instrument_id, []).append(e)
    for (instrument_id, side), pos in positions.open_positions(db, account.id).items():
        inst = db.get(Instrument, instrument_id)
        row = {"instrument": inst, "position": pos, "side": side, "error": None}
        try:
            p = prices.get_price(db, inst, max_age=max_age)
            fx, _ = prices.get_fx(db, inst.currency, max_age=max_age)
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
        # Obbligazioni: rateo che si incasserebbe vendendo oggi (regolamento T+2)
        accrued_eur = ZERO
        if inst.type == "bond":
            settle = bonds.settlement_date(inst, rome_date(now))
            accrued_eur = pos.quantity * bonds.accrued_per100(inst, settle) / 100 / fx
        row.update(price=p, fx=fx, mv_ccy=mv_ccy, mv_eur=mv_eur, day_eur=day_ccy / fx, accrued_eur=accrued_eur)
        rows.append(row)
    return rows


def positions_value(db: Session, account: Account, now: datetime | None = None,
                    max_age: int = prices.CACHE_SECONDS) -> Decimal:
    """Controvalore delle posizioni. `max_age` alto = usa gli ultimi prezzi salvati senza chiederli alla fonte
    (serve all'elenco dei portafogli: con centinaia di posizioni le richieste una per una richiedono minuti)."""
    return sum((r["mv_eur"] for r in _position_rows(db, account, now or utcnow(), max_age)
                if r["error"] is None), ZERO)


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


def value_history(db: Session, account: Account, now: datetime | None = None) -> list[tuple[date, Decimal]]:
    """Valore totale a fine giornata: controvalore salvato ogni sera + liquidità ricostruita dal ledger.

    Ci sono solo i giorni in cui il server era acceso; l'ultimo punto è il valore attuale.
    """
    now = now or utcnow()
    today = rome_date(now)
    values = _daily_values(db, account)
    entries = [(rome_date(e.ts), e.cash_delta_eur) for e in positions.ledger(db, account.id)]
    out = []
    cash, i = ZERO, 0
    days = set(values) | {rome_date(account.created_at)}  # il primo giorno vale il capitale iniziale
    for day in sorted(d for d in days if d < today):
        while i < len(entries) and entries[i][0] <= day:
            cash += entries[i][1]
            i += 1
        out.append((day, eur(values.get(day, ZERO) + cash)))
    out.append((today, summary(db, account, now)["total_value"]))
    return out


def last_valuation(db: Session, account: Account) -> tuple[date, Decimal]:
    """Ultimo valore totale salvato (controvalore della sera + liquidità di quel giorno), senza chiedere prezzi.
    Senza valorizzazioni: il capitale iniziale al giorno di apertura."""
    row = db.scalar(select(DailyValuation).where(DailyValuation.account_id == account.id)
                    .order_by(DailyValuation.day.desc()).limit(1))
    if row is None:
        return rome_date(account.created_at), eur(account.initial_capital)
    cash = sum((e.cash_delta_eur for e in positions.ledger(db, account.id) if rome_date(e.ts) <= row.day), ZERO)
    return row.day, eur(row.positions_value_eur + cash)


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


def close_account(db: Session, account: Account, now: datetime | None = None,
                  note: str = "Annullato per chiusura del portafoglio") -> None:
    """Chiude un portafoglio: bollo maturato addebitato, ordini in attesa annullati. Lo storico resta."""
    now = now or utcnow()
    snapshot(db, account, now)
    charge_stamp(db, account, rome_date(now).year, rome_date(now), now)
    for o in db.scalars(select(Order).where(Order.account_id == account.id, Order.status == "pending")):
        o.status, o.cancelled_at, o.note = "cancelled", now, note
    account.closed_at = now
    db.commit()


def reset(db: Session, capital: Decimal, now: datetime | None = None) -> Account:
    """Chiude il portafoglio selezionato e ne apre uno nuovo con lo stesso nome."""
    now = now or utcnow()
    old = active_account(db)
    close_account(db, old, now, "Annullato per reset del portafoglio")
    return open_account(db, capital, now, old.name)


def summary(db: Session, account: Account, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rows = _position_rows(db, account, now)
    cash = positions.cash_balance(db, account.id)
    reserved = positions.reserved_cash(db, account.id)

    realized_gross = realized_fiscal = sale_taxes = tobin = stamp = income_net = ZERO
    for e in positions.ledger(db, account.id):
        if e.kind in ("sell", "redemption"):
            realized_gross += e.realized_gross_eur or ZERO
            realized_fiscal += e.realized_fiscal_eur or ZERO
            sale_taxes += e.tax_eur
        elif e.kind in ("dividend", "coupon"):
            realized_gross += e.gross_eur
            income_net += e.cash_delta_eur
        elif e.kind == "buy":
            tobin += e.tobin_tax_eur
        elif e.kind == "stamp_duty":
            stamp += e.tax_eur
        if e.accrued_interest_eur:
            # Rateo pagato in acquisto (costo) e incassato in vendita, al lordo e al netto dell'imposta
            sign = -1 if e.kind == "buy" else 1
            realized_gross += sign * e.accrued_interest_eur
            income_net += sign * e.accrued_interest_eur - (e.interest_tax_eur or ZERO)

    out_positions = []
    mv_total = unreal_gross = unreal_net = day_total = accrued_total = ZERO
    for r in rows:
        inst, pos = r["instrument"], r["position"]
        item = {
            "instrument_id": inst.id, "symbol": inst.symbol, "isin": inst.isin, "name": inst.name,
            "type": inst.type, "market": inst.market, "currency": inst.currency, "side": r["side"],
            "quantity": pos.quantity, "avg_price": pos.avg_price, "avg_cost_eur": pos.avg_cost_eur,
            "cost_eur": eur(pos.cost_fiscal_eur), "error": r["error"], "maturity": inst.maturity,
            "coupon_rate": inst.coupon_rate,
        }
        if r["error"] is None:
            p = r["price"]
            rule = db.get(TaxRule, inst.fiscal_category)
            accrued = r["accrued_eur"]
            gross = r["mv_eur"] - pos.cost_gross_eur
            sell_comm = commission(r["mv_eur"], *_comm_args(db, inst))
            fiscal = r["mv_eur"] - sell_comm - pos.cost_fiscal_eur
            est_tax = eur(fiscal * rule.base_factor * rule.rate) if rule and fiscal > 0 else ZERO
            net = fiscal - est_tax
            if accrued:
                # Il rateo maturato fa parte del risultato non ancora incassato
                gross += accrued
                net += accrued * (1 - rule.rate * rule.base_factor)
                accrued_total += accrued
                item["accrued_eur"] = eur(accrued)
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
    realized_net = realized_fiscal - sale_taxes - tobin - stamp + income_net
    total_value = cash + mv_total + accrued_total
    return {
        "account_id": account.id, "as_of": now, "initial_capital": account.initial_capital,
        "total_value": eur(total_value), "positions_value": eur(mv_total), "accrued_interest": eur(accrued_total),
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
        "upcoming_dividends": corporate_events.upcoming_dividends(db, account, now),
    }


def _comm_args(db: Session, inst: Instrument) -> tuple[Decimal, Decimal, Decimal]:
    rule = _commission_rule(db, inst)
    return rule.fixed_eur, rule.pct, rule.minimum_eur
