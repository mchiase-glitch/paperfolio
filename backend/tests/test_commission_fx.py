from decimal import Decimal as D

from app.services.commission import commission, tobin_tax
from app.services.fx import applied_rate, to_eur


def test_commissione_ita_applica_il_minimo():
    # 3 + 0,07% × 1.000 = 3,70 → minimo 5,00
    assert commission(D("1000"), D("3"), D("0.0007"), D("5")) == D("5.00")


def test_commissione_ita_sopra_il_minimo():
    # 3 + 0,07% × 10.000 = 10,00
    assert commission(D("10000"), D("3"), D("0.0007"), D("5")) == D("10.00")


def test_commissione_eur_e_usa():
    assert commission(D("5000"), D("12"), D("0.0007"), D("5")) == D("15.50")
    assert commission(D("2500"), D("6"), D("0.0007"), D("5")) == D("7.75")


def test_commissione_arrotondata_al_centesimo():
    assert commission(D("1234.56"), D("6"), D("0.0007"), D("5")) == D("6.86")  # 6,864192


def test_tobin_solo_acquisti_azioni_italiane():
    rate = D("0.001")
    assert tobin_tax("stock", "IT", "buy", D("5000"), rate) == D("5.00")
    assert tobin_tax("stock", "IT", "sell", D("5000"), rate) == D("0.00")
    assert tobin_tax("etf", "IT", "buy", D("5000"), rate) == D("0.00")
    assert tobin_tax("bond", "IT", "buy", D("5000"), rate) == D("0.00")
    assert tobin_tax("stock", "NL", "buy", D("5000"), rate) == D("0.00")  # es. Stellantis, quotata a Milano


def test_cambio_sempre_a_sfavore():
    market, spread = D("1.08"), D("0.001")
    assert applied_rate(market, spread, "buy") == D("1.07892")
    assert applied_rate(market, spread, "sell") == D("1.08108")
    buy = to_eur(D("1000"), "USD", market, spread, "buy")
    sell = to_eur(D("1000"), "USD", market, spread, "sell")
    mid = D("1000") / market
    assert buy.amount_eur > mid > sell.amount_eur  # pago di più comprando, incasso di meno vendendo


def test_cambio_eur_neutro():
    c = to_eur(D("1000"), "EUR", D("1"), D("0.001"), "buy")
    assert c.amount_eur == D("1000") and c.applied_rate == D("1")
