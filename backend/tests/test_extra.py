from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.models import DailyValuation, LedgerEntry
from app.services import orders, portfolio, positions

from .conftest import OPEN_MIL, SATURDAY, add_stock, utc

LATER = utc(2025, 3, 12, 11, 0)  # stessa seduta, un'ora dopo


# --- Ordini limite e stop -------------------------------------------------------------

@pytest.mark.parametrize("otype,side,trigger,price,met", [
    ("limit", "buy", "10", "9.99", True), ("limit", "buy", "10", "10.01", False),
    ("limit", "sell", "10", "10", True), ("limit", "sell", "10", "9.99", False),
    ("stop", "sell", "10", "9.5", True), ("stop", "sell", "10", "10.5", False),
    ("stop", "buy", "10", "10.5", True), ("stop", "buy", "10", "9.5", False),
])
def test_condizioni_limite_e_stop(otype, side, trigger, price, met):
    assert orders.condition_met(otype, side, D(trigger), D(price)) is met


def test_acquisto_limite_attende_e_si_esegue_al_ribasso(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    o = orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL, order_type="limit", trigger_price=D("13.50"))
    assert o.status == "pending"
    # prenotazione al prezzo limite: (1.350 + 5 commissione + 1,35 Tobin) × 1,05
    assert o.reserved_eur == D("1424.17")  # 1.356,35 × 1,05
    assert orders.process_pending(db, now=utc(2025, 3, 12, 10, 30)) == []  # prezzo ancora sopra il limite
    provider.set("ENI.MI", "13.40", LATER)
    orders.process_pending(db, now=LATER)
    assert o.status == "executed"
    e = db.query(LedgerEntry).filter_by(order_id=o.id).one()
    assert e.price == D("13.40")  # eseguito al prezzo di mercato, migliore del limite


def test_limite_gia_raggiunto_si_esegue_subito(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    o = orders.place_order(db, account, inst, "buy", D("10"), now=OPEN_MIL, order_type="limit", trigger_price=D("15"))
    assert o.status == "executed"


def test_stop_loss_scatta_quando_il_prezzo_scende(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    stop = orders.place_order(db, account, inst, "sell", D("100"), now=OPEN_MIL, order_type="stop", trigger_price=D("13"))
    assert stop.status == "pending"
    provider.set("ENI.MI", "12.80", LATER)
    orders.process_pending(db, now=LATER)
    assert stop.status == "executed"
    assert positions.position(db, account.id, inst.id).quantity == 0


def test_stop_in_acquisto_prenota_al_prezzo_piu_alto(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    pv = orders.preview(db, account, inst, "buy", D("100"), now=OPEN_MIL, order_type="stop", trigger_price=D("15"))
    assert not pv.condition_met and not pv.executes_now
    assert pv.reserved_eur == D("1581.83")  # (1.500 + 5 + 1,50) × 1,05 = 1.581,825


def test_ordine_scaduto_libera_la_liquidita(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    o = orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL, order_type="limit",
                           trigger_price=D("12"), expires_on=date(2025, 3, 14))
    assert positions.reserved_cash(db, account.id) > 0
    orders.process_pending(db, now=SATURDAY)  # sabato 15/03: validità finita venerdì
    assert o.status == "expired"
    assert positions.reserved_cash(db, account.id) == 0


def test_limite_obbligatorio(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    with pytest.raises(orders.OrderError, match="limite"):
        orders.preview(db, account, inst, "buy", D("1"), now=OPEN_MIL, order_type="limit")


# --- Più portafogli -------------------------------------------------------------------

def test_portafogli_separati_e_selezione(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)
    second = portfolio.open_account(db, D("5000"), now=OPEN_MIL, name="Prudente")
    assert portfolio.active_account(db).id == second.id  # il nuovo diventa quello selezionato
    assert positions.cash_balance(db, second.id) == D("5000")
    assert positions.open_positions(db, second.id) == {}
    portfolio.select_account(db, account)
    assert portfolio.active_account(db).id == account.id
    portfolio.close_account(db, second, now=OPEN_MIL)
    assert [a.id for a in portfolio.open_accounts(db)] == [account.id]


def test_reset_mantiene_il_nome(db, account):
    account.name = "Dinamico"
    db.commit()
    new = portfolio.reset(db, D("20000"), now=OPEN_MIL)
    assert new.name == "Dinamico" and new.id != account.id and portfolio.active_account(db).id == new.id


# --- Storico del valore ---------------------------------------------------------------

def test_storico_valore_con_liquidita_dal_ledger(db, account, provider):
    inst = add_stock(db)
    provider.set("ENI.MI", "14", OPEN_MIL)
    orders.place_order(db, account, inst, "buy", D("100"), now=OPEN_MIL)  # costo 1.406,40
    db.add(DailyValuation(account_id=account.id, day=date(2025, 3, 12), positions_value_eur=D("1400")))
    db.add(DailyValuation(account_id=account.id, day=date(2025, 3, 13), positions_value_eur=D("1450")))
    db.commit()
    provider.set("ENI.MI", "15", utc(2025, 3, 14, 10, 0))
    points = portfolio.value_history(db, account, now=utc(2025, 3, 14, 10, 0))
    assert points[0] == (date(2025, 1, 2), D("10000.00"))  # apertura del conto
    assert points[1] == (date(2025, 3, 12), D("10000") - D("1406.40") + D("1400"))
    assert points[2] == (date(2025, 3, 13), D("10043.60"))
    assert points[-1] == (date(2025, 3, 14), D("10093.60"))  # valore attuale: 8.593,60 + 1.500


# --- API: portafogli, watchlist, storico ------------------------------------------------

def test_api_portafogli_watchlist_storico(provider):
    from app.main import app
    with TestClient(app) as client:
        start = client.get("/api/accounts").json()
        r = client.post("/api/accounts", json={"name": "Secondo", "capital": "3000"})
        assert r.status_code == 200
        new_id = r.json()["id"]
        acc = client.get("/api/accounts").json()
        assert acc["current_id"] == new_id and len(acc["accounts"]) == len(start["accounts"]) + 1
        assert client.get("/api/portfolio").json()["cash"] == "3000.00"
        assert client.put(f"/api/accounts/{new_id}", json={"name": "Rinominato"}).json()["name"] == "Rinominato"

        h = client.get("/api/portfolio/history?benchmark=FTSEMIB.MI").json()
        assert h["points"][-1]["value"] == "3000.00" and len(h["benchmarks"]) == 4
        assert client.get("/api/portfolio/history?benchmark=XXX").status_code == 400

        r = client.post(f"/api/accounts/{new_id}/close", json={"confirm": True})
        assert r.status_code == 200 and r.json()["current_id"] != new_id
        others = r.json()["accounts"]
        if len(others) == 1:
            assert client.post(f"/api/accounts/{others[0]['id']}/close", json={"confirm": True}).status_code == 400

        from app.database import SessionLocal
        from app.models import Instrument
        with SessionLocal() as db:
            inst = Instrument(symbol="WATCH.MI", name="Watch SpA", type="stock", market="ITA", exchange="XMIL",
                              currency="EUR", country="IT", fiscal_category="azioni", data_source="manual")
            db.add(inst)
            db.commit()
            inst_id = inst.id
        client.put(f"/api/instruments/{inst_id}/manual-price", json={"price": "7"})
        assert client.post(f"/api/watchlist/{inst_id}").json() == {"watched": True}
        items = client.get("/api/watchlist").json()["items"]
        assert [i["price"] for i in items if i["instrument_id"] == inst_id] == ["7"]
        assert client.get(f"/api/instruments/{inst_id}").json()["watched"] is True
        client.delete(f"/api/watchlist/{inst_id}")
        assert client.get(f"/api/instruments/{inst_id}").json()["watched"] is False
