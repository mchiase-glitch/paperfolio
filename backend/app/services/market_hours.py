from datetime import datetime, timezone
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=None)
def _calendar(mic: str):
    return xcals.get_calendar(mic)


def _ts(when: datetime) -> pd.Timestamp:
    return pd.Timestamp(when.astimezone(timezone.utc)).floor("min")


def is_open(mic: str, when: datetime) -> bool:
    return bool(_calendar(mic).is_open_on_minute(_ts(when)))


def session_open(mic: str, when: datetime) -> datetime | None:
    """Apertura della seduta in corso, oppure None se la borsa è chiusa."""
    cal = _calendar(mic)
    ts = _ts(when)
    if not cal.is_open_on_minute(ts):
        return None
    session = cal.minute_to_session(ts, direction="none")
    return cal.session_open(session).to_pydatetime()


def next_open(mic: str, when: datetime) -> datetime:
    return _calendar(mic).next_open(_ts(when)).to_pydatetime()
