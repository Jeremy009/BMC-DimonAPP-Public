"""Month arithmetic of the monthly navigation (R7.8, R7.11)."""

from datetime import date

from dimonapp.months import add_months, find_month_start, find_quarter_start, shift_month


def test_r7_8_month_start_is_the_first_day() -> None:
    """Any day gives the first day of its month."""
    assert find_month_start(day=date(2026, 10, 17)) == date(2026, 10, 1)


def test_r7_8_next_and_previous_month() -> None:
    """The arrows move one month forward or back."""
    assert shift_month(month_start=date(2026, 10, 1), n_months=1) == date(2026, 11, 1)
    assert shift_month(month_start=date(2026, 10, 1), n_months=-1) == date(2026, 9, 1)


def test_r7_8_navigation_crosses_the_year() -> None:
    """December is followed by January of the next year, and the other way round."""
    assert shift_month(month_start=date(2026, 12, 1), n_months=1) == date(2027, 1, 1)
    assert shift_month(month_start=date(2027, 1, 1), n_months=-1) == date(2026, 12, 1)


def test_r7_14_three_months_ahead_keeps_the_day_of_the_month() -> None:
    """10 October plus three months is 10 January of the next year."""
    assert add_months(day=date(2026, 10, 10), n_months=3) == date(2027, 1, 10)


def test_r7_14_three_months_ahead_stops_at_the_end_of_a_shorter_month() -> None:
    """30 November plus three months is the last day of February."""
    assert add_months(day=date(2026, 11, 30), n_months=3) == date(2027, 2, 28)


def test_r7_16_quarter_start_is_the_first_day_of_the_quarter() -> None:
    """Every day of a quarter gives 1 January, April, July or October."""
    assert find_quarter_start(day=date(2026, 1, 1)) == date(2026, 1, 1)
    assert find_quarter_start(day=date(2026, 6, 30)) == date(2026, 4, 1)
    assert find_quarter_start(day=date(2026, 8, 15)) == date(2026, 7, 1)
    assert find_quarter_start(day=date(2026, 12, 31)) == date(2026, 10, 1)
