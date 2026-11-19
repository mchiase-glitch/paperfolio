from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.models import LedgerEntry, LossUsage
from app.services import orders, portfolio, positions
from app.services.orders import OrderError

from .conftest import OPEN_MIL, OPEN_NYSE, SATURDAY, add_stock, utc


def test_acquisto_a_borsa_aperta_eseguito_subito(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    o = orders.place_order(db, account, inst, "buy", D("500"), now=OPEN_MIL)
    assert o.status == "executed"
    # 7.000 + commissione 3+4,90=7,90 + Tobin 7,00
    assert positions.cash_balance(db, account.id) == D("10000") - D("7000") - D("7.90") - D("7.00")
    pos = positions.position(db, account.id, inst.id)
    assert pos.quantity == D("500") and pos.avg_price == D("14")


def test_prezzo_medio_di_carico_ponderato(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    provider.set("ENI.MI", "13", utc(2025, 3, 12, 10, 1))
    orders.place_order(db, account, inst, "buy", D("200"), now=utc(2025, 3, 12, 10, 2))
    pos = positions.position(db, account.id, inst.id)
    assert pos.avg_price == D("12")  # (1000 + 2600) / 300
    provider.set("ENI.MI", "15", utc(2025, 3, 12, 10, 3))
    orders.place_order(db, account, inst, "sell", D("150"), now=utc(2025, 3, 12, 10, 4))
    pos = positions.position(db, account.id, inst.id)
    assert pos.quantity == D("150") and pos.avg_price == D("12")  # la vendita non cambia il prezzo medio


def test_borsa_chiusa_ordine_in_attesa_con_prenotazione(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    o = orders.place_order(db, account, inst, "buy", D("100"), now=SATURDAY)
    assert o.status == "pending"
    assert o.reserved_eur == D("1055.25")  # (1000 + 5) × 1,05
    assert positions.cash_balance(db, account.id) == D("10000")
    assert positions.reserved_cash(db, account.id) == D("1055.25")


def test_ordine_in_attesa_eseguito_al_primo_prezzo_dopo_apertura(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    o = orders.place_order(db, account, inst, "buy", D("100"), now=SATURDAY)
    monday_open = utc(2025, 3, 17, 8, 0)
    # Borsa aperta ma il prezzo è ancora quello di venerdì: l'ordine aspetta
    assert orders.process_pending(db, now=utc(2025, 3, 17, 8, 5)) == []
    provider.set("ENI.MI", "10.5", utc(2025, 3, 17, 8, 1))
    done = orders.process_pending(db, now=utc(2025, 3, 17, 8, 20))
    assert [x.id for x in done] == [o.id] and o.status == "executed"
    assert monday_open < o.executed_at
    # La prenotazione è rilasciata: resta solo l'addebito effettivo
    assert positions.reserved_cash(db, account.id) == 0
    assert positions.cash_balance(db, account.id) == D("10000") - D("1050") - D("5")


def test_ordine_in_attesa_annullabile(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    o = orders.place_order(db, account, inst, "buy", D("100"), now=SATURDAY)
    orders.cancel_order(db, o, now=SATURDAY)
    assert o.status == "cancelled" and positions.reserved_cash(db, account.id) == 0
    with pytest.raises(OrderError):
        orders.cancel_order(db, o)


def test_liquidita_insufficiente(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "100", OPEN_MIL)
    with pytest.raises(OrderError, match="Liquidità insufficiente"):
        orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)


def test_prenotazione_conta_nella_liquidita_disponibile(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    orders.place_order(db, account, inst, "buy", D("900"), now=SATURDAY)  # prenota 9.455,25
    with pytest.raises(OrderError, match="Liquidità insufficiente"):
        orders.place_order(db, account, inst, "buy", D("100"), now=SATURDAY)


def test_ordine_in_attesa_rifiutato_se_il_prezzo_sale_troppo(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    o = orders.place_order(db, account, inst, "buy", D("900"), now=SATURDAY)
    provider.set("ENI.MI", "12", utc(2025, 3, 17, 8, 1))
    orders.process_pending(db, now=utc(2025, 3, 17, 8, 20))
    assert o.status == "rejected" and "Liquidità" in o.note


def test_vendita_allo_scoperto_vietata(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("10"), now=OPEN_MIL)
    with pytest.raises(OrderError, match="scoperto"):
        orders.place_order(db, account, inst, "sell", D("11"), now=OPEN_MIL)


def test_vendite_in_attesa_riducono_la_quantita_vendibile(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("10"), now=OPEN_MIL)
    orders.place_order(db, account, inst, "sell", D("8"), now=SATURDAY)
    with pytest.raises(OrderError, match="scoperto"):
        orders.place_order(db, account, inst, "sell", D("3"), now=SATURDAY)


def test_plusvalenza_tassata_e_compensata_con_zainetto(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("200"), now=OPEN_MIL)  # costo 2.000 + 5
    provider.set("ENI.MI", "9", utc(2025, 3, 12, 11, 0))
    orders.place_order(db, account, inst, "sell", D("100"), now=utc(2025, 3, 12, 11, 1))
    loss = db.query(LedgerEntry).filter_by(kind="sell").one()
    # 900 − 5 commissione − 1.002,50 costo = −107,50
    assert loss.realized_fiscal_eur == D("-107.50") and loss.loss_added_eur == D("107.50")

    provider.set("ENI.MI", "13", utc(2025, 3, 12, 12, 0))
    orders.place_order(db, account, inst, "sell", D("100"), now=utc(2025, 3, 12, 12, 1))
    gain = db.query(LedgerEntry).filter_by(kind="sell").order_by(LedgerEntry.id.desc()).first()
    # 1.300 − 5 − 1.002,50 = 292,50; meno zainetto 107,50 = 185,00 × 26% = 48,10
    assert gain.realized_fiscal_eur == D("292.50")
    assert gain.taxable_eur == D("185.00") and gain.tax_eur == D("48.10")
    assert db.query(LossUsage).one().amount_eur == D("107.50")


def test_acquisto_usd_con_spread(db, account, provider):
    inst = add_stock(db, symbol="AAPL", country="US", market="USA", exchange="XNYS", currency="USD")
    provider.set("AAPL", "200", OPEN_NYSE, currency="USD")
    pv = orders.preview(db, account, inst, "buy", D("10"), now=OPEN_NYSE)
    assert pv.fx_market == D("1.08") and pv.fx_applied == D("1.07892")
    assert pv.gross_eur == D("1853.71")  # 2.000 / 1,07892
    assert pv.commission_eur == D("7.30") and pv.tobin_tax_eur == 0
    assert pv.net_eur == D("1861.01")


def test_ledger_append_only(db, account):
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE ledger_entries SET cash_delta_eur='999999'"))
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM ledger_entries"))
    db.rollback()


def test_bollo_addebitato_al_31_dicembre(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    portfolio.snapshot(db, account, now=OPEN_MIL)  # 1.000 € dal 12/03/2025
    portfolio.charge_past_years(db, now=utc(2026, 1, 1, 9, 0))
    stamp = db.query(LedgerEntry).filter_by(kind="stamp_duty").one()
    # 1.000 × 0,2% × 295/365 = 1,6164
    assert stamp.tax_eur == D("1.62") and stamp.tax_year == 2025
    portfolio.charge_past_years(db, now=utc(2026, 1, 2, 9, 0))
    assert db.query(LedgerEntry).filter_by(kind="stamp_duty").count() == 1


def test_reset_portafoglio(db, account, provider):
    inst = add_stock(db, country="NL")
    provider.set("ENI.MI", "10", utc(2025, 3, 14, 16, 29))
    orders.place_order(db, account, inst, "buy", D("100"), now=SATURDAY)
    new = portfolio.reset(db, D("50000"), now=SATURDAY)
    assert new.id != account.id and account.closed_at is not None
    assert positions.cash_balance(db, new.id) == D("50000")
    assert positions.reserved_cash(db, account.id) == 0
