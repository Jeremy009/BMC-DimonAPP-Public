"""The clock gives the Belgian date (R7.4)."""

import datetime
from typing import Optional

import pytest

from dimonapp import clock


class LateEveningInUtc(datetime.datetime):
    """A clock stuck at 23:30 UTC on 10 October 2026, which is 01:30 the next day in Belgium."""

    @classmethod
    def now(cls, tz: Optional[datetime.tzinfo] = None) -> datetime.datetime:
        """Give the fixed moment in the asked time zone."""
        moment = datetime.datetime(2026, 10, 10, 23, 30, tzinfo=datetime.UTC)
        return moment.astimezone(tz)


def test_r7_4_today_follows_the_belgian_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Late in the evening in UTC it is already tomorrow in Belgium."""
    monkeypatch.setattr(clock.datetime, 'datetime', LateEveningInUtc)

    assert clock.read_today() == datetime.date(2026, 10, 11)


def test_r13_2_now_follows_the_belgian_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The moment a payment file is made is told in Belgian time."""
    monkeypatch.setattr(clock.datetime, 'datetime', LateEveningInUtc)

    now = clock.read_now()

    assert now.strftime('%Y-%m-%d %H:%M') == '2026-10-11 01:30'
