from datetime import date
from decimal import Decimal as D

from app.api.instruments import unsupported_reason
from app.data_provider import CorporateActions
from app.models import CorporateEvent, LedgerEntry, WithholdingRate
from app.services import corporate_events as ce
from app.services import orders, portfolio, positions

from .conftest import OPEN_MIL, OPEN_NYSE, add_stock, utc


def event(db, inst, kind="dividend", ex=date(2025, 3, 17), pay=date(2025, 3, 19), amount=None, ratio=None):
    ev = CorporateEvent(instrument_id=inst.id, kind=kind, ex_date=ex, pay_date=pay if kind == "dividend" else None,
                        amount=None if amount is None else D(amount), ratio=None if ratio is None else D(ratio),
                        source="manual", pay_date_estimated=0)
    db.add(ev)
    db.commit()
    return ev


def dividends(db):
    return db.query(LedgerEntry).filter_by(kind="dividend").all()


def test_dividendo_italiano_accreditato_alla_data_di_pagamento(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    event(db, inst, amount="0.25")
    ce.process(db, now=utc(2025, 3, 18, 10, 0))  # stacco passato, pagamento no
    assert dividends(db) == []
    ce.process(db, now=utc(2025, 3, 19, 6, 0))
    (d,) = dividends(db)
    assert (d.gross_eur, d.withholding_eur, d.tax_eur, d.cash_delta_eur) == (D("25.00"), D("0.00"), D("6.50"), D("18.50"))
    assert d.ts.date() == date(2025, 3, 18)  # mezzanotte del 19 a Roma = 23:00 UTC del 18


def test_dividendo_usa_ritenuta_15_poi_26_sul_netto_con_cambio(db, account, provider):
    inst = add_stock(db, symbol="AAPL", country="US", market="USA", exchange="XNYS", currency="USD")
    provider.set("AAPL", "50", OPEN_NYSE, currency="USD")
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_NYSE)
    event(db, inst, ex=date(2025, 3, 20), pay=date(2025, 3, 25), amount="0.27")
    ce.process(db, now=utc(2025, 3, 25, 12, 0))
    (d,) = dividends(db)
    assert d.fx_applied == D("1.08108")  # conversione USD→EUR a sfavore
    # 27 USD / 1,08108 = 24,98 €; ritenuta USA 15% = 3,75; 26% su 21,23 = 5,52; netto 15,71
    assert (d.gross_eur, d.withholding_eur, d.tax_eur, d.cash_delta_eur) == (D("24.98"), D("3.75"), D("5.52"), D("15.71"))


def test_distribuzione_etf_senza_ritenuta_estera(db, account, provider):
    db.add(WithholdingRate(country="IE", rate=D("0.25")))
    inst = add_stock(db, symbol="VHYL.MI", country="IE", type="etf", fiscal_category="etf_armonizzati")
    provider.set("VHYL.MI", "60", OPEN_MIL)
    o = orders.place_order(db, account, inst, "buy", D("50"), now=OPEN_MIL)
    assert db.query(LedgerEntry).filter_by(order_id=o.id).one().tobin_tax_eur == 0  # niente Tobin sugli ETF
    event(db, inst, amount="0.40")
    ce.process(db, now=utc(2025, 3, 20, 8, 0))
    (d,) = dividends(db)
    assert (d.gross_eur, d.withholding_eur, d.tax_eur, d.cash_delta_eur) == (D("20.00"), D("0.00"), D("5.20"), D("14.80"))


def test_acquisto_il_giorno_dello_stacco_non_da_diritto(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 17, 8, 1))
    orders.place_order(db, account, inst, "buy", D("100"), now=utc(2025, 3, 17, 9, 0))
    event(db, inst, amount="0.25")
    ce.process(db, now=utc(2025, 3, 20, 8, 0))
    assert dividends(db) == []


def test_vendita_il_giorno_dello_stacco_mantiene_il_diritto(db, account, provider):
    inst = add_stock(db, country="LU")  # paese senza ritenuta predefinita: qui conta solo la data
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    provider.set("ENI.MI", "10", utc(2025, 3, 17, 8, 1))
    orders.place_order(db, account, inst, "sell", D("100"), now=utc(2025, 3, 17, 9, 0))
    event(db, inst, amount="0.25")
    up = ce.upcoming_dividends(db, account, now=utc(2025, 3, 18, 8, 0))
    assert [(u["quantity"], u["net_eur"]) for u in up] == [(D("100"), D("18.50"))]
    ce.process(db, now=utc(2025, 3, 20, 8, 0))
    assert dividends(db)[0].quantity == D("100")


def test_accredito_una_sola_volta(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    event(db, inst, amount="0.25")
    ce.process(db, now=utc(2025, 3, 20, 8, 0))
    ce.process(db, now=utc(2025, 3, 21, 8, 0))
    assert len(dividends(db)) == 1


def test_dividendo_nel_risultato_realizzato(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    event(db, inst, amount="0.25")
    ce.process(db, now=utc(2025, 3, 20, 8, 0))
    s = portfolio.summary(db, account, now=utc(2025, 3, 20, 8, 0))
    assert s["pnl"]["realized_gross"] == D("25.00")
    assert s["pnl"]["realized_net"] == D("18.50") - D("1.40")  # meno la Tobin tax dell'acquisto


def test_frazionamento_adegua_quantita_e_prezzo_medio(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "100", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("10"), now=OPEN_MIL)
    before = positions.position(db, account.id, inst.id)
    event(db, inst, kind="split", ratio="4")
    ce.process(db, now=utc(2025, 3, 16, 8, 0))
    assert positions.position(db, account.id, inst.id).quantity == D("10")  # non ancora efficace
    ce.process(db, now=utc(2025, 3, 17, 6, 0))
    after = positions.position(db, account.id, inst.id)
    assert after.quantity == D("40") and after.avg_price == D("25")
    assert after.cost_fiscal_eur == before.cost_fiscal_eur


def test_raggruppamento_liquida_la_frazione(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("15"), now=OPEN_MIL)  # costo 150 + 5
    event(db, inst, kind="split", ratio="0.1")  # 1×10: 15 → 1,5
    provider.set("ENI.MI", "105", utc(2025, 3, 17, 8, 1))
    ce.process(db, now=utc(2025, 3, 17, 12, 0))
    assert positions.position(db, account.id, inst.id).quantity == D("1")
    sale = db.query(LedgerEntry).filter_by(kind="sell").one()
    assert sale.quantity == D("0.5") and sale.gross_eur == D("52.50") and sale.commission_eur == 0
    assert sale.realized_fiscal_eur == D("0.83")  # 52,50 − 155/3


def test_dividendi_rettificati_dalla_fonte_tornano_reali():
    divs = [(date(2020, 5, 8), D("0.205")), (date(2020, 11, 6), D("0.205"))]
    splits = [(date(2020, 8, 31), D("4"))]
    assert ce.unadjust_dividends(divs, splits) == [(date(2020, 5, 8), D("0.820")), (date(2020, 11, 6), D("0.205"))]


def test_sincronizzazione_e_data_di_pagamento(db, account, provider):
    us = add_stock(db, symbol="AAPL", country="US", market="USA", exchange="XNYS", currency="USD")
    it = add_stock(db)
    provider.actions["AAPL"] = CorporateActions(
        dividends=[(date(2024, 11, 8), D("0.25")), (date(2025, 2, 10), D("0.25"))],
        splits=[], announced=[(date(2025, 2, 10), date(2025, 2, 13))])
    provider.actions["ENI.MI"] = CorporateActions(dividends=[(date(2025, 3, 14), D("0.25"))], splits=[], announced=[])
    ce.sync_instrument(db, us, since=date(2025, 1, 2))
    ce.sync_instrument(db, it, since=date(2025, 1, 2))
    evs = {(e.instrument_id, e.ex_date): e for e in db.query(CorporateEvent).all()}
    assert (us.id, date(2024, 11, 8)) not in evs  # anteriore al primo acquisto
    assert evs[(us.id, date(2025, 2, 10))].pay_date == date(2025, 2, 13)
    eni = evs[(it.id, date(2025, 3, 14))]
    assert eni.pay_date == date(2025, 3, 18) and eni.pay_date_estimated == 1  # venerdì + 2 giorni lavorativi
    ce.sync_instrument(db, it, since=date(2025, 1, 2))
    assert db.query(CorporateEvent).count() == 2


def test_etf_usa_non_negoziabili():
    assert unsupported_reason("etf", "USA") is not None
    assert unsupported_reason("etf", "ITA") is None
    assert unsupported_reason("stock", "USA") is None
