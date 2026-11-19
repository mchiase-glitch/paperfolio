from decimal import Decimal as D

from fastapi.testclient import TestClient

from app.database import SessionLocal, utcnow
from app.main import app
from app.models import Instrument


def test_flusso_completo_api(provider):
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        start = client.get("/api/portfolio").json()
        assert start["cash"] == "10000.00" and start["positions"] == []

        with SessionLocal() as db:
            inst = Instrument(symbol="TEST.MI", name="Test SpA", type="stock", market="ITA", exchange="XMIL",
                              currency="EUR", country="IT", fiscal_category="azioni", data_source="manual")
            db.add(inst)
            db.commit()
            inst_id = inst.id
        r = client.put(f"/api/instruments/{inst_id}/manual-price", json={"price": "20"})
        assert r.status_code == 200

        pv = client.post("/api/orders/preview", json={"instrument_id": inst_id, "side": "buy", "quantity": "10"})
        assert pv.status_code == 200
        body = pv.json()
        assert body["gross_eur"] == "200.00" and body["commission_eur"] == "5.00" and body["tobin_tax_eur"] == "0.20"
        assert body["is_manual"] is True

        r = client.post("/api/orders", json={"instrument_id": inst_id, "side": "buy", "quantity": "10"})
        assert r.status_code == 200
        order = r.json()
        assert order["status"] in ("executed", "pending")  # dipende dall'orario reale della borsa

        r = client.post("/api/orders", json={"instrument_id": inst_id, "side": "sell", "quantity": "999"})
        assert r.status_code == 400

        assert client.get("/api/orders").json()["orders"][0]["id"] == order["id"]
        assert "data_ora_roma" in client.get("/api/movements.csv").text
        assert client.get("/api/fiscal").json()["year"] == utcnow().year

        s = client.get("/api/settings").json()
        ita = next(c for c in s["commissions"] if c["instrument_type"] == "stock" and c["market"] == "ITA")
        r = client.put("/api/settings", json={"fx_spread": "0.002",
                                              "commissions": [{**ita, "minimum_eur": "4"}]})
        assert r.json()["fx_spread"] == "0.002"
        assert next(c for c in r.json()["commissions"] if c["id"] == ita["id"])["minimum_eur"] == "4"

        r = client.post("/api/settings/reset", json={"capital": "25000", "confirm": True})
        assert D(client.get("/api/portfolio").json()["cash"]) == D("25000")
