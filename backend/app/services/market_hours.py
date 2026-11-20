from datetime import date, datetime, timedelta, timezone
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


def add_sessions(mic: str, d: date, n: int) -> date:
    """Data che cade `n` giorni di borsa dopo `d` (regolamento T+2)."""
    try:
        sessions = _calendar(mic).sessions_in_range(pd.Timestamp(d + timedelta(days=1)),
                                                    pd.Timestamp(d + timedelta(days=20)))
    except Exception:
        sessions = []
    if len(sessions) < n:  # oltre l'orizzonte del calendario: solo giorni feriali
        while n > 0:
            d += timedelta(days=1)
            n -= d.weekday() < 5
        return d
    return sessions[n - 1].date()
