from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")


def eur(value: Decimal) -> Decimal:
    """Arrotonda al centesimo (metà per eccesso), come per gli addebiti reali."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
