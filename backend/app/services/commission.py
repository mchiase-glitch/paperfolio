from decimal import Decimal

from .money import eur


def commission(gross_eur: Decimal, fixed: Decimal, pct: Decimal, minimum: Decimal) -> Decimal:
    """Commissione = max(fisso + percentuale × controvalore in EUR, minimo)."""
    return eur(max(fixed + pct * gross_eur, minimum))


def tobin_tax(instrument_type: str, country: str | None, side: str, gross_eur: Decimal, rate: Decimal) -> Decimal:
    """Tobin tax solo sugli acquisti di azioni italiane (non ETF né obbligazioni)."""
    if side == "buy" and instrument_type == "stock" and country == "IT":
        return eur(gross_eur * rate)
    return Decimal("0.00")
