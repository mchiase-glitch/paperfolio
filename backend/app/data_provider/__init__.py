from .base import DataProvider, DataProviderError, InstrumentInfo, Quote, SearchResult

_provider: DataProvider | None = None


def get_provider() -> DataProvider:
    """Fonte di mercato automatica. Gli strumenti con data_source='manual' non la interrogano."""
    global _provider
    if _provider is None:
        from .yfinance_adapter import YFinanceProvider

        _provider = YFinanceProvider()
    return _provider


def set_provider(provider: DataProvider) -> None:
    global _provider
    _provider = provider


__all__ = ["DataProvider", "DataProviderError", "InstrumentInfo", "Quote", "SearchResult",
           "get_provider", "set_provider"]
