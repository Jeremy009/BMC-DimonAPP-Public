"""The clock: what "today" is for BMC, wherever the server runs."""

import datetime
from zoneinfo import ZoneInfo

# Cloud Run runs in UTC; "today or later" (R7.4) is judged on the Belgian calendar.
BELGIAN_TIME_ZONE = ZoneInfo('Europe/Brussels')


def read_today() -> datetime.date:
    """Give today's date in Belgium."""
    return read_now().date()


def read_now() -> datetime.datetime:
    """Give the current date and time in Belgium."""
    return datetime.datetime.now(tz=BELGIAN_TIME_ZONE)
