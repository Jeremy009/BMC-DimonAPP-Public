"""Compensation of an activity: the rate valid on its date and the amount (R6.4 to R6.7)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from dimonapp.models import CompensationModel, CompensationRate

CENT = Decimal('0.01')


def find_rate(rates: list[CompensationRate], activity_date: date) -> Optional[CompensationRate]:
    """Pick the newest rate version valid on the activity date, or None when there is none.

    The rates are those of one worker for one activity type (R6.7).
    """
    valid_rates = [rate for rate in rates if rate.valid_from <= activity_date]
    if not valid_rates:
        return None
    return max(valid_rates, key=lambda rate: rate.valid_from)


def compute_compensation(
    compensation_model: CompensationModel,
    rate: Decimal,
    duration_hours: Decimal,
) -> Decimal:
    """Compute the amount due for one activity, to the cent.

    Hourly is the rate times the hours (R6.4); fixed price is the rate itself, whatever the
    hours (R6.5).
    """
    if compensation_model == CompensationModel.FIXED:
        return rate.quantize(CENT, rounding=ROUND_HALF_UP)
    amount = rate * duration_hours
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)
