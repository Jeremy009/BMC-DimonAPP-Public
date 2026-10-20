"""French formatting of amounts, hours, dates and months (R18.1)."""

import datetime
from decimal import Decimal

import pytest

from dimonapp.french import (
    MONTH_NAMES,
    format_amount,
    format_date,
    format_decimal,
    format_hours,
    format_iban,
    format_month,
    format_month_title,
    remove_accents,
)


@pytest.mark.parametrize(
    ('amount', 'expected'),
    [
        (Decimal('1234.5'), '1 234,50 €'),
        (Decimal('40'), '40,00 €'),
        (Decimal('0.999'), '1,00 €'),
        (Decimal('1234567.89'), '1 234 567,89 €'),
    ],
)
def test_r18_1_amount_uses_french_format(amount: Decimal, expected: str) -> None:
    """Amounts use a space for thousands, a comma for decimals and the euro sign last."""
    assert format_amount(amount=amount) == expected


@pytest.mark.parametrize(
    ('hours', 'expected'),
    [
        (Decimal('2.5'), '2,5 h'),
        (Decimal('3.0'), '3 h'),
        (Decimal('10'), '10 h'),
        (Decimal('0.25'), '0,25 h'),
    ],
)
def test_r18_1_hours_use_french_format(hours: Decimal, expected: str) -> None:
    """Hours use a decimal comma and drop needless zeros."""
    assert format_hours(hours=hours) == expected


def test_r18_1_date_is_day_month_year() -> None:
    """Dates read DD/MM/YYYY."""
    day = datetime.date(2026, 10, 4)

    assert format_date(day=day) == '04/10/2026'


def test_r18_1_month_uses_french_name() -> None:
    """A month reads as its French name followed by the year."""
    assert format_month(year=2026, month=10) == 'octobre 2026'
    assert format_month(year=2027, month=1) == 'janvier 2027'
    assert format_month(year=2026, month=12) == 'décembre 2026'


def test_r18_1_all_month_names_are_french() -> None:
    """The twelve month names are the French ones, in calendar order."""
    expected = (
        'janvier février mars avril mai juin juillet août septembre octobre novembre décembre'
    )

    assert ' '.join(MONTH_NAMES) == expected


def test_r18_1_decimal_uses_a_comma_and_drops_trailing_zeros() -> None:
    """A table shows 2,5 and 4, not 2.50 and 4.00."""
    assert format_decimal(value=Decimal('2.50')) == '2,5'
    assert format_decimal(value=Decimal('4.00')) == '4'


def test_r18_1_month_title_starts_with_a_capital() -> None:
    """The heading of a monthly tab reads Octobre 2026, also for an accented month."""
    assert format_month_title(year=2026, month=10) == 'Octobre 2026'
    assert format_month_title(year=2026, month=2) == 'Février 2026'
    assert format_month_title(year=2026, month=8) == 'Août 2026'


def test_r18_1_iban_is_shown_in_groups_of_four() -> None:
    """An IBAN reads as on a bank card."""
    assert format_iban(iban='BE71096123456769') == 'BE71 0961 2345 6769'


def test_r13_2_accents_are_removed_where_only_plain_letters_are_accepted() -> None:
    """Letters keep their plain form; a character without one is left out."""
    assert remove_accents(text='Michaël Çağlar') == 'Michael Caglar'
    assert remove_accents(text='Łukasz Søren Weiß') == 'Lukasz Soren Weiss'
    assert remove_accents(text='février €') == 'fevrier '
