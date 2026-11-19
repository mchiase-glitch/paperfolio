from datetime import date
from decimal import Decimal as D

from app.models import TaxRule
from app.services.tax import LossLot, compute_sale_tax, loss_expiry, stamp_duty

AZIONI = TaxRule(fiscal_category="azioni", label="", rate=D("0.26"), base_factor=D("1"),
                 gains_kind="diversi", losses_kind="diversi")
WHITELIST = TaxRule(fiscal_category="titoli_stato_whitelist", label="", rate=D("0.26"), base_factor=D("0.4808"),
                    gains_kind="diversi", losses_kind="diversi")
ETF = TaxRule(fiscal_category="etf_armonizzati", label="", rate=D("0.26"), base_factor=D("1"),
              gains_kind="capitale", losses_kind="diversi")
DERIVATI = TaxRule(fiscal_category="derivati", label="", rate=D("0.26"), base_factor=D("1"),
                   gains_kind="diversi", losses_kind="diversi")
ON = date(2025, 6, 10)


def test_plus_azioni_tassata_al_26():
    t = compute_sale_tax(D("1000"), AZIONI, [], ON)
    assert (t.taxable, t.tax, t.loss_added) == (D("1000.00"), D("260.00"), D("0"))


def test_minus_azioni_entra_nello_zainetto_con_scadenza():
    t = compute_sale_tax(D("-400"), AZIONI, [], ON)
    assert t.tax == 0 and t.loss_added == D("400.00")
    assert t.loss_expiry == date(2029, 12, 31)


def test_scadenza_31_dicembre_quarto_anno_successivo():
    assert loss_expiry(date(2025, 1, 1)) == date(2029, 12, 31)
    assert loss_expiry(date(2025, 12, 31)) == date(2029, 12, 31)


def test_zainetto_compensa_prima_le_minus_piu_vecchie():
    lots = [LossLot(2, date(2024, 5, 1), date(2028, 12, 31), D("300")),
            LossLot(1, date(2023, 5, 1), date(2027, 12, 31), D("200"))]
    t = compute_sale_tax(D("350"), AZIONI, lots, ON)
    assert t.usages == [(1, D("200.00")), (2, D("150.00"))]
    assert t.taxable == D("0.00") and t.tax == D("0.00")


def test_zainetto_ignora_minus_scadute():
    lots = [LossLot(1, date(2020, 5, 1), date(2024, 12, 31), D("500"))]
    t = compute_sale_tax(D("100"), AZIONI, lots, date(2025, 1, 1))
    assert t.usages == [] and t.tax == D("26.00")


def test_zainetto_ultimo_giorno_valido():
    lots = [LossLot(1, date(2020, 5, 1), date(2024, 12, 31), D("500"))]
    t = compute_sale_tax(D("100"), AZIONI, lots, date(2024, 12, 31))
    assert t.usages == [(1, D("100.00"))] and t.tax == 0


def test_compensazione_parziale():
    lots = [LossLot(1, date(2024, 1, 1), date(2028, 12, 31), D("100"))]
    t = compute_sale_tax(D("1000"), AZIONI, lots, ON)
    assert t.taxable == D("900.00") and t.tax == D("234.00")


def test_titoli_stato_whitelist_aliquota_effettiva_12_5():
    t = compute_sale_tax(D("1000"), WHITELIST, [], ON)
    assert t.taxable == D("480.80") and t.tax == D("125.01")  # 1000 × 48,08% × 26% = 125,008


def test_titoli_stato_whitelist_minus_al_48_08():
    assert compute_sale_tax(D("-1000"), WHITELIST, [], ON).loss_added == D("480.80")


def test_etf_plus_reddito_di_capitale_non_compensabile():
    lots = [LossLot(1, date(2024, 1, 1), date(2028, 12, 31), D("500"))]
    t = compute_sale_tax(D("1000"), ETF, lots, ON)
    assert t.usages == [] and t.tax == D("260.00")


def test_etf_minus_entra_nello_zainetto():
    assert compute_sale_tax(D("-300"), ETF, [], ON).loss_added == D("300.00")


def test_derivati_redditi_diversi():
    lots = [LossLot(1, date(2024, 1, 1), date(2028, 12, 31), D("500"))]
    assert compute_sale_tax(D("200"), DERIVATI, lots, ON).tax == 0


def test_bollo_anno_intero():
    values = {date(2025, 1, 1): D("10000")}
    assert stamp_duty(values, date(2025, 1, 1), date(2025, 12, 31), D("0.002")) == D("20.00")


def test_bollo_pro_rata():
    # 10.000 € detenuti per 73 giorni su 365: 20 × 73/365 = 4,00
    values = {date(2025, 1, 1): D("0"), date(2025, 10, 20): D("10000")}
    assert stamp_duty(values, date(2025, 1, 1), date(2025, 12, 31), D("0.002")) == D("4.00")


def test_bollo_giorni_mancanti_riprendono_ultimo_valore():
    values = {date(2025, 3, 1): D("10000"), date(2025, 3, 11): D("0")}  # 10 giorni a 10.000
    assert stamp_duty(values, date(2025, 1, 1), date(2025, 12, 31), D("0.002")) == D("0.55")  # 0,5479


def test_bollo_anno_bisestile():
    values = {date(2024, 1, 1): D("10000")}
    assert stamp_duty(values, date(2024, 1, 1), date(2024, 12, 31), D("0.002")) == D("20.00")
