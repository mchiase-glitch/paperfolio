from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data_provider import DataProviderError, get_provider
from ..models import Instrument

FISCAL_BY_TYPE = {"stock": "azioni", "etf": "etf_armonizzati"}


def unsupported_reason(itype: str, market: str | None) -> str | None:
    if market is None:
        return "borsa non supportata"
    if itype == "etf" and market == "USA":
        # Gli ETF USA non sono UCITS e non sono acquistabili dai risparmiatori italiani
        return "ETF non armonizzato (USA)"
    if itype == "bond":
        return "le obbligazioni si inseriscono a mano"
    if itype not in FISCAL_BY_TYPE:
        return "disponibile nelle prossime fasi"
    return None


def get_or_create(db: Session, symbol: str, isin: str | None = None) -> Instrument:
    """Strumento già noto oppure creato dai dati anagrafici della fonte. Solleva DataProviderError."""
    existing = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if existing:
        return existing
    info = get_provider().info(symbol)
    reason = unsupported_reason(info.type, info.market)
    if reason:
        raise DataProviderError(f"Strumento non negoziabile: {reason}")
    isin = (isin or info.isin or "").upper() or None
    # Senza paese dalla fonte (tipico degli ETF) si usa il prefisso dell'ISIN: IE, LU, ...
    country = info.country or (isin[:2] if isin else None)
    inst = Instrument(symbol=info.symbol, isin=isin, name=info.name, type=info.type,
                      market=info.market, exchange=info.exchange, currency=info.currency, country=country,
                      fiscal_category=FISCAL_BY_TYPE[info.type], data_source="yfinance")
    db.add(inst)
    db.commit()
    return inst
