from datetime import date
from decimal import Decimal as D

import pytest

from app.models import Instrument, LedgerEntry
from app.services import bonds, orders, portfolio, positions, prices
from app.services import corporate_events as ce

from .conftest import OPEN_MIL, utc

# 0,26 × 0,4808: aliquota effettiva dei titoli di Stato white list
WL = D("0.125008")


def add_bond(db, maturity=date(2030, 3, 1), rate="0.035", freq=2, price="98.50", issue=None,
             category="titoli_stato_whitelist", day_count="ACT/ACT", lot="1000", schedule_from=date(2025, 3, 12)):
    inst = Instrument(symbol=f"IT{maturity:%Y%m%d}{rate}"[:12], isin="IT0005000000", name="BTP test", type="bond",
                      market="ITA", exchange="XMIL", currency="EUR", country="IT", fiscal_category=category,
                      data_source="manual", multiplier=D("0.01"), coupon_rate=D(rate), coupon_frequency=freq,
                      maturity=maturity, issue_date=issue, lot_size=D(lot), day_count=day_count)
    db.add(inst)
    db.commit()
    prices.set_manual_price(db, inst, D(price), OPEN_MIL)
    ce.create_bond_schedule(db, inst, schedule_from)
    return inst


def close(a, b):
    return abs(a - b) < D("1e-20")


def entries(db, kind):
    return db.query(LedgerEntry).filter_by(kind=kind).all()


# --- Calcoli puri ------------------------------------------------------------------

def test_regolamento_t_piu_2_giorni_di_borsa(db):
    inst = add_bond(db)
    assert bonds.settlement_date(inst, date(2025, 3, 12)) == date(2025, 3, 14)  # mercoledì → venerdì
    assert bonds.settlement_date(inst, date(2025, 3, 13)) == date(2025, 3, 17)  # giovedì → lunedì
    assert bonds.settlement_date(inst, date(2025, 4, 17)) == date(2025, 4, 23)  # Venerdì Santo e Pasquetta chiusi


def test_rateo_act_act(db):
    inst = add_bond(db)
    # periodo 01/03/2025–01/09/2025 (184 giorni), maturati 13 giorni: 1,75 × 13/184
    assert close(bonds.accrued_per100(inst, date(2025, 3, 14)), D("1.75") * 13 / 184)
    assert bonds.accrued_per100(inst, date(2025, 3, 1)) == 0  # nel giorno della cedola il rateo riparte da zero


def test_rateo_30_360(db):
    inst = add_bond(db, maturity=date(2028, 6, 15), rate="0.04", freq=1, day_count="30/360")
    # dal 15/06/2024 al 14/03/2025 = 269 giorni "commerciali"
    assert close(bonds.accrued_per100(inst, date(2025, 3, 14)), D("4") * 269 / 360)


def test_prima_cedola_corta(db):
    inst = add_bond(db, issue=date(2025, 1, 15), schedule_from=date(2025, 1, 15))
    first_date, first_amount = bonds.coupon_schedule(inst, date(2025, 1, 15))[0]
    assert first_date == date(2025, 3, 1)
    assert close(first_amount, D("1.75") * 45 / 181)  # dal 15/01 al 01/03 su un periodo di 181 giorni
    assert close(bonds.accrued_per100(inst, date(2025, 2, 14)), D("1.75") * 30 / 181)
    assert bonds.accrued_per100(inst, date(2025, 1, 10)) == 0  # prima dell'emissione


def test_calendario_cedole_fine_mese(db):
    inst = add_bond(db, maturity=date(2027, 8, 31), freq=2)
    dates = [d for d, _ in bonds.coupon_schedule(inst, date(2025, 3, 12))]
    assert dates[:3] == [date(2025, 8, 31), date(2026, 2, 28), date(2026, 8, 31)]


def test_rendimento_a_scadenza_alla_pari(db):
    inst = add_bond(db, maturity=date(2030, 3, 14), rate="0.03", freq=1)
    y = bonds.yield_to_maturity(inst, D("100"), date(2025, 3, 14), WL)
    assert abs(y.gross - D("0.03")) < D("0.0002")
    assert abs(y.net - D("0.02625")) < D("0.0002")  # cedole nette al 12,5%


def test_rendimento_sotto_la_pari_include_il_guadagno_a_scadenza(db):
    inst = add_bond(db, maturity=date(2030, 3, 14), rate="0.03", freq=1)
    y = bonds.yield_to_maturity(inst, D("95"), date(2025, 3, 14), WL)
    assert y.gross > D("0.04") and y.net < y.gross


# --- Ordini ----------------------------------------------------------------------------

def test_acquisto_con_rateo_e_credito_d_imposta(db, account):
    inst = add_bond(db)
    pv = orders.preview(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    assert pv.settlement_date == date(2025, 3, 14)
    assert pv.gross_eur == D("4925.00")  # 5.000 × 98,50%
    assert pv.accrued_interest_eur == D("6.18")  # 5.000 × 1,75% × 13/184
    assert pv.interest_tax_eur == D("-0.77")  # 12,5% del rateo, a credito di chi compra
    assert pv.commission_eur == D("6.45")  # 3 + 0,07% × 4.925
    assert pv.tobin_tax_eur == 0
    assert pv.net_eur == D("4936.86")
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    pos = positions.position(db, account.id, inst.id)
    assert pos.quantity == D("5000") and pos.avg_price == D("98.50")
    assert positions.cash_balance(db, account.id) == D("10000") - D("4936.86")


def test_nominale_multiplo_del_taglio(db, account):
    inst = add_bond(db)
    with pytest.raises(orders.OrderError, match="multiplo"):
        orders.preview(db, account, inst, "buy", D("1500"), now=OPEN_MIL)


def test_vendita_plus_white_list_al_12_5_e_imposta_sul_rateo(db, account):
    inst = add_bond(db)
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    prices.set_manual_price(db, inst, D("100"), OPEN_MIL)
    o = orders.place_order(db, account, inst, "sell", D("5000"), now=OPEN_MIL)
    e = db.query(LedgerEntry).filter_by(order_id=o.id).one()
    # plus fiscale 5.000 − 6,50 − (4.925 + 6,45) = 62,05; base 48,08% = 29,83; imposta 26% = 7,76
    assert (e.realized_fiscal_eur, e.taxable_eur, e.tax_eur) == (D("62.05"), D("29.83"), D("7.76"))
    assert (e.accrued_interest_eur, e.interest_tax_eur) == (D("6.18"), D("0.77"))
    assert e.cash_delta_eur == D("4991.15")  # 5.000 + 6,18 − 0,77 − 6,50 − 7,76


def test_minus_white_list_nello_zainetto_al_48_08(db, account):
    inst = add_bond(db)
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    prices.set_manual_price(db, inst, D("95"), OPEN_MIL)
    o = orders.place_order(db, account, inst, "sell", D("5000"), now=OPEN_MIL)
    e = db.query(LedgerEntry).filter_by(order_id=o.id).one()
    # minus 4.750 − 6,33 − 4.931,45 = −187,78 → nello zainetto 90,28 (48,08%)
    assert e.realized_fiscal_eur == D("-187.78")
    assert e.loss_added_eur == D("90.28") and e.tax_eur == 0


def test_obbligazione_societaria_interessi_al_26(db, account):
    inst = add_bond(db, category="obbligazioni_societarie")
    pv = orders.preview(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    assert pv.interest_tax_eur == D("-1.61")  # 26% di 6,18


# --- Cedole e rimborso ----------------------------------------------------------------

def test_cedola_accreditata_al_netto(db, account):
    inst = add_bond(db)
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    ce.process(db, now=utc(2025, 8, 31, 10, 0))
    assert entries(db, "coupon") == []
    ce.process(db, now=utc(2025, 9, 1, 6, 0))
    (c,) = entries(db, "coupon")
    # 5.000 × 1,75% = 87,50; imposta 12,5% = 10,94; netto 76,56
    assert (c.gross_eur, c.tax_eur, c.cash_delta_eur) == (D("87.50"), D("10.94"), D("76.56"))
    ce.process(db, now=utc(2025, 9, 2, 6, 0))
    assert len(entries(db, "coupon")) == 1  # mai due volte


def test_cedola_spetta_in_base_al_regolamento(db, account):
    inst = add_bond(db)
    # acquisto giovedì 28/08: regolamento lunedì 01/09, giorno della cedola → niente cedola e niente rateo
    pv = orders.preview(db, account, inst, "buy", D("5000"), now=utc(2025, 8, 28, 10, 0))
    assert pv.settlement_date == date(2025, 9, 1) and pv.accrued_interest_eur == 0
    orders.place_order(db, account, inst, "buy", D("5000"), now=utc(2025, 8, 28, 10, 0))
    ce.process(db, now=utc(2025, 9, 1, 6, 0))
    assert entries(db, "coupon") == []


def test_venditore_incassa_la_cedola_se_regola_dopo(db, account):
    inst = add_bond(db)
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    # vendita giovedì 28/08, regolata il 01/09: la cedola resta al venditore
    orders.place_order(db, account, inst, "sell", D("5000"), now=utc(2025, 8, 28, 10, 0))
    ce.process(db, now=utc(2025, 9, 1, 6, 0))
    (c,) = entries(db, "coupon")
    assert c.quantity == D("5000")


def test_rimborso_a_scadenza_con_ultima_cedola(db, account):
    inst = add_bond(db, maturity=date(2025, 4, 1), rate="0.02", freq=1, price="99.80")
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    ce.process(db, now=utc(2025, 4, 1, 6, 0))
    (c,) = entries(db, "coupon")
    assert c.gross_eur == D("100.00")
    (r,) = entries(db, "redemption")
    # 5.000 al 100% senza commissioni; costo 4.990 + 6,49 → plus 3,51, base 1,69, imposta 0,44
    assert (r.gross_eur, r.commission_eur, r.realized_fiscal_eur, r.tax_eur) == (D("5000.00"), 0, D("3.51"), D("0.44"))
    assert positions.position(db, account.id, inst.id).quantity == 0
    with pytest.raises(orders.OrderError, match="scadenza"):
        orders.preview(db, account, inst, "buy", D("1000"), now=utc(2025, 3, 28, 10, 0))


def test_rateo_nel_valore_del_portafoglio(db, account):
    inst = add_bond(db)
    orders.place_order(db, account, inst, "buy", D("5000"), now=OPEN_MIL)
    s = portfolio.summary(db, account, now=OPEN_MIL)
    (p,) = s["positions"]
    assert p["accrued_eur"] == D("6.18")
    assert s["total_value"] == D("10000") - D("4936.86") + D("4925.00") + D("6.18")
