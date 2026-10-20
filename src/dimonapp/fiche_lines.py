"""What one fiche 281.27 reports about one worker (R14.3)."""

from decimal import Decimal

from pydantic import BaseModel

from dimonapp.models import Period


class FicheLine(BaseModel):
    """The totals of one article 17 worker for one income year, with the identification."""

    first_name: str
    last_name: str
    national_register_number: str
    street: str
    postal_code: str
    city: str
    amount: Decimal
    quarter_hours: dict[Period, Decimal]


def sum_fiche_hours(line: FicheLine) -> Decimal:
    """Give the hours of the whole year of a fiche."""
    return sum(line.quarter_hours.values(), start=Decimal('0'))
