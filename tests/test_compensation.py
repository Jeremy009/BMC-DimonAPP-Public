"""Compensation rules (R6.4, R6.5, R6.7)."""

from datetime import date
from decimal import Decimal

from dimonapp.compensation import compute_compensation, find_rate
from dimonapp.models import CompensationModel
from factories import build_rate


def test_r6_4_hourly_compensation_is_rate_times_hours() -> None:
    """An hourly activity pays the rate for every hour entered."""
    amount = compute_compensation(
        compensation_model=CompensationModel.HOURLY,
        rate=Decimal('15.00'),
        duration_hours=Decimal('2.5'),
    )

    assert amount == Decimal('37.50')


def test_r6_4_hourly_compensation_is_rounded_half_up_to_the_cent() -> None:
    """15,33 x 2,5 = 38,325 becomes 38,33."""
    amount = compute_compensation(
        compensation_model=CompensationModel.HOURLY,
        rate=Decimal('15.33'),
        duration_hours=Decimal('2.5'),
    )

    assert amount == Decimal('38.33')


def test_r6_5_fixed_price_compensation_ignores_hours() -> None:
    """A fixed-price activity pays the rate once, whatever the hours."""
    amounts = [
        compute_compensation(
            compensation_model=CompensationModel.FIXED,
            rate=Decimal('60.00'),
            duration_hours=duration_hours,
        )
        for duration_hours in (Decimal('1'), Decimal('8'))
    ]

    assert amounts == [Decimal('60.00'), Decimal('60.00')]


def test_r6_7_rate_valid_on_the_activity_date_is_chosen() -> None:
    """Among several versions, the newest one on or before the activity date applies."""
    old_rate = build_rate(valid_from=date(2026, 1, 1), amount=Decimal('15'))
    new_rate = build_rate(valid_from=date(2026, 7, 1), amount=Decimal('18'))
    rates = [new_rate, old_rate]

    assert find_rate(rates=rates, activity_date=date(2026, 6, 30)) is old_rate
    assert find_rate(rates=rates, activity_date=date(2026, 7, 1)) is new_rate
    assert find_rate(rates=rates, activity_date=date(2027, 2, 1)) is new_rate


def test_r6_7_no_rate_before_the_first_version() -> None:
    """An activity before the first rate version has no rate."""
    rates = [build_rate(valid_from=date(2026, 1, 1))]

    assert find_rate(rates=rates, activity_date=date(2025, 12, 31)) is None
