from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..data_provider import DataProviderError, get_provider
from ..database import utcnow
from ..models import FxRate, Instrument, Price

CACHE_SECONDS = 60


@dataclass
class PriceInfo:
    price: Decimal
    prev_close: Decimal | None
    currency: str
    price_time: datetime
    source: str
    is_manual: bool
    stale: bool = False  # fonte non raggiungibile: si usa l'ultimo prezzo noto


def get_price(db: Session, instrument: Instrument, max_age: int = CACHE_SECONDS,
              now: datetime | None = None) -> PriceInfo:
    now = now or utcnow()
    cached = db.get(Price, instrument.id)
    if instrument.data_source == "manual":
        if not cached:
            raise DataProviderError("Prezzo manuale non ancora inserito")
        return _from_row(cached)
    if cached and timedelta(0) <= (now - cached.fetched_at) < timedelta(seconds=max_age):
        return _from_row(cached)
    try:
        q = get_provider().quote(instrument.symbol)
    except Exception as exc:
        if cached:
            info = _from_row(cached)
            info.stale = True
            return info
        raise DataProviderError(str(exc)) from exc
    if cached is None:
        cached = Price(instrument_id=instrument.id)
        db.add(cached)
    cached.price, cached.prev_close, cached.currency = q.price, q.prev_close, q.currency
    cached.price_time, cached.fetched_at = q.price_time, now
    cached.source, cached.is_manual = get_provider().name, 0
    db.commit()
    return _from_row(cached)


def set_manual_price(db: Session, instrument: Instrument, price: Decimal, when: datetime) -> None:
    row = db.get(Price, instrument.id)
    if row is None:
        row = Price(instrument_id=instrument.id)
        db.add(row)
    row.prev_close = row.price if row.price is not None else None
    row.price, row.currency, row.price_time = price, instrument.currency, when
    row.fetched_at, row.source, row.is_manual = utcnow(), "manual", 1
    db.commit()


def get_fx(db: Session, currency: str, max_age: int = CACHE_SECONDS) -> tuple[Decimal, datetime]:
    """Cambio di mercato: unità di `currency` per 1 EUR."""
    if currency == "EUR":
        return Decimal("1"), utcnow()
    cached = db.get(FxRate, currency)
    if cached and (utcnow() - cached.fetched_at) < timedelta(seconds=max_age):
        return cached.rate, cached.rate_time
    try:
        q = get_provider().fx_rate(currency)
    except Exception as exc:
        if cached:
            return cached.rate, cached.rate_time
        raise DataProviderError(f"Cambio EUR/{currency} non disponibile") from exc
    if cached is None:
        cached = FxRate(currency=currency)
        db.add(cached)
    cached.rate, cached.rate_time, cached.fetched_at = q.price, q.price_time, utcnow()
    db.commit()
    return cached.rate, cached.rate_time


def _from_row(row: Price) -> PriceInfo:
    return PriceInfo(row.price, row.prev_close, row.currency, row.price_time, row.source, bool(row.is_manual))
