from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class DataProviderError(Exception):
    pass


@dataclass
class Quote:
    price: Decimal
    currency: str
    price_time: datetime  # UTC
    prev_close: Decimal | None = None


@dataclass
class SearchResult:
    symbol: str
    name: str
    type: str  # stock / etf
    exchange: str | None  # MIC, None se borsa non supportata
    market: str | None
    exchange_label: str


@dataclass
class InstrumentInfo:
    symbol: str
    name: str
    type: str
    exchange: str
    market: str
    currency: str
    country: str | None
    isin: str | None


class DataProvider(Protocol):
    name: str

    def quote(self, symbol: str) -> Quote: ...

    def fx_rate(self, currency: str) -> Quote:
        """Unità di `currency` per 1 EUR."""
        ...

    def search(self, query: str) -> list[SearchResult]: ...

    def info(self, symbol: str) -> InstrumentInfo: ...

    def history(self, symbol: str, period: str) -> list[tuple[date, Decimal]]: ...
