"""Month arithmetic: the monthly navigation and the latest date to declare (R7.8, R7.14, R7.16)."""

from datetime import date


def find_month_start(day: date) -> date:
    """Give the first day of the month a date falls in."""
    return day.replace(day=1)


def add_months(day: date, n_months: int) -> date:
    """Give the same day n months later; the last day of that month when it is shorter."""
    month_start = shift_month(month_start=find_month_start(day=day), n_months=n_months)
    next_month_start = shift_month(month_start=month_start, n_months=1)
    n_days_in_month = (next_month_start - month_start).days
    return month_start.replace(day=min(day.day, n_days_in_month))


def shift_month(month_start: date, n_months: int) -> date:
    """Give the first day of the month n months later, or earlier when n is negative."""
    month_index = month_start.year * 12 + (month_start.month - 1) + n_months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year=year, month=month, day=1)


def find_quarter_start(day: date) -> date:
    """Give the first day of the quarter a date falls in."""
    first_month = day.month - (day.month - 1) % 3
    return date(year=day.year, month=first_month, day=1)
