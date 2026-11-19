import re
from datetime import date, timezone
from decimal import Decimal

import yfinance as yf

from .base import DataProviderError, InstrumentInfo, Quote, SearchResult
from .mapping import COUNTRIES, MINOR_CURRENCIES, YAHOO_EXCHANGES, YAHOO_TYPES

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _dec(value, places: str = "0.0001") -> Decimal:
    # Passando da str si evitano gli artefatti binari dei float di pandas
    return Decimal(repr(float(value))).quantize(Decimal(places))


def _normalize_currency(currency: str) -> tuple[str, int]:
    return MINOR_CURRENCIES.get(currency, (currency, 1))


class YFinanceProvider:
    name = "yfinance"

    def _last_bar(self, symbol: str):
        t = yf.Ticker(symbol)
        intraday = t.history(period="5d", interval="1m", auto_adjust=False)
        daily = t.history(period="1mo", interval="1d", auto_adjust=False)
        if daily.empty and intraday.empty:
            raise DataProviderError(f"Nessun prezzo disponibile per {symbol}")
        if not intraday.empty:
            last_ts, last_close = intraday.index[-1], intraday["Close"].iloc[-1]
        else:
            last_ts, last_close = daily.index[-1], daily["Close"].iloc[-1]
        prev_close = None
        if not daily.empty:
            earlier = daily[daily.index.date < last_ts.date()]
            if not earlier.empty:
                prev_close = earlier["Close"].iloc[-1]
        return t, last_ts, last_close, prev_close

    def quote(self, symbol: str) -> Quote:
        t, last_ts, last_close, prev_close = self._last_bar(symbol)
        try:
            raw_ccy = t.fast_info["currency"]
        except Exception as exc:
            raise DataProviderError(f"Valuta sconosciuta per {symbol}") from exc
        currency, divisor = _normalize_currency(raw_ccy)
        return Quote(
            price=_dec(last_close) / divisor,
            currency=currency,
            price_time=last_ts.to_pydatetime().astimezone(timezone.utc),
            prev_close=None if prev_close is None else _dec(prev_close) / divisor,
        )

    def fx_rate(self, currency: str) -> Quote:
        _, last_ts, last_close, prev_close = self._last_bar(f"EUR{currency}=X")
        return Quote(
            price=_dec(last_close, "0.00001"),
            currency=currency,
            price_time=last_ts.to_pydatetime().astimezone(timezone.utc),
            prev_close=None if prev_close is None else _dec(prev_close, "0.00001"),
        )

    def search(self, query: str) -> list[SearchResult]:
        try:
            quotes = yf.Search(query, max_results=15, news_count=0, lists_count=0).quotes
        except Exception as exc:
            raise DataProviderError("Ricerca non disponibile") from exc
        results = []
        for q in quotes:
            itype = YAHOO_TYPES.get(q.get("quoteType", ""))
            if not itype:
                continue
            mapped = YAHOO_EXCHANGES.get(q.get("exchange", ""))
            results.append(SearchResult(
                symbol=q["symbol"],
                name=q.get("longname") or q.get("shortname") or q["symbol"],
                type=itype,
                exchange=mapped[0] if mapped else None,
                market=mapped[1] if mapped else None,
                exchange_label=mapped[2] if mapped else q.get("exchDisp", q.get("exchange", "")),
            ))
        return results

    def info(self, symbol: str) -> InstrumentInfo:
        try:
            data = yf.Ticker(symbol).info
        except Exception as exc:
            raise DataProviderError(f"Dati anagrafici non disponibili per {symbol}") from exc
        mapped = YAHOO_EXCHANGES.get(data.get("exchange", ""))
        itype = YAHOO_TYPES.get(data.get("quoteType", ""))
        if not mapped or not itype or not data.get("currency"):
            raise DataProviderError(f"Strumento non supportato: {symbol}")
        currency, _ = _normalize_currency(data["currency"])
        return InstrumentInfo(
            symbol=symbol,
            name=data.get("longName") or data.get("shortName") or symbol,
            type=itype,
            exchange=mapped[0],
            market=mapped[1],
            currency=currency,
            country=COUNTRIES.get(data.get("country", "")),
            isin=None,
        )

    def history(self, symbol: str, period: str) -> list[tuple[date, Decimal]]:
        h = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        if h.empty:
            return []
        currency = yf.Ticker(symbol).fast_info["currency"]
        _, divisor = _normalize_currency(currency)
        return [(ts.date(), _dec(close) / divisor) for ts, close in h["Close"].items()]
