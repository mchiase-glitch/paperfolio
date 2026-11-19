from dataclasses import dataclass
from decimal import Decimal

ONE = Decimal("1")


@dataclass(frozen=True)
class FxConversion:
    market_rate: Decimal  # unità di valuta per 1 EUR (es. 1.08 USD)
    spread: Decimal
    applied_rate: Decimal
    amount_ccy: Decimal
    amount_eur: Decimal  # non arrotondato


def applied_rate(market_rate: Decimal, spread: Decimal, side: str) -> Decimal:
    """Cambio applicato, sempre a sfavore del cliente.

    Acquisto: servono valuta estera, si ricevono meno unità per euro → cambio più basso.
    Vendita: si cedono valuta estera, servono più unità per ottenere un euro → cambio più alto.
    """
    if side == "buy":
        return market_rate * (ONE - spread)
    if side == "sell":
        return market_rate * (ONE + spread)
    raise ValueError(f"side non valido: {side}")


def to_eur(amount_ccy: Decimal, currency: str, market_rate: Decimal, spread: Decimal, side: str) -> FxConversion:
    if currency == "EUR":
        return FxConversion(ONE, Decimal("0"), ONE, amount_ccy, amount_ccy)
    rate = applied_rate(market_rate, spread, side)
    return FxConversion(market_rate, spread, rate, amount_ccy, amount_ccy / rate)
