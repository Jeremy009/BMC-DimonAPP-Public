"""French formatting of amounts, hours, dates and months (R18.1)."""

import datetime
import unicodedata
from decimal import Decimal

# A no-break space keeps an amount such as 1 234,50 € on one line in tables.
NO_BREAK_SPACE = ' '

MONTH_NAMES = (
    'janvier',
    'février',
    'mars',
    'avril',
    'mai',
    'juin',
    'juillet',
    'août',
    'septembre',
    'octobre',
    'novembre',
    'décembre',
)

# Monday first, as Python's date.weekday() counts.
WEEKDAY_NAMES = (
    'lundi',
    'mardi',
    'mercredi',
    'jeudi',
    'vendredi',
    'samedi',
    'dimanche',
)

# Letters that Unicode does not split into a plain letter and an accent.
PLAIN_LETTERS = str.maketrans(
    {
        'Ł': 'L',
        'ł': 'l',
        'Ø': 'O',
        'ø': 'o',
        'Đ': 'D',
        'đ': 'd',
        'ß': 'ss',
        'Æ': 'AE',
        'æ': 'ae',
        'Œ': 'OE',
        'œ': 'oe',
    }
)


def format_amount(amount: Decimal) -> str:
    """Format an amount in euro the French way, for example 1 234,50 €."""
    english = f'{amount:,.2f}'
    french = english.replace(',', NO_BREAK_SPACE).replace('.', ',')
    return f'{french}{NO_BREAK_SPACE}€'


def format_decimal(value: Decimal) -> str:
    """Format a number the French way without trailing zeros, for example 2,5 or 3."""
    english = f'{value.normalize():f}'
    return english.replace('.', ',')


def format_hours(hours: Decimal) -> str:
    """Format a duration in hours the French way, for example 2,5 h or 3 h."""
    french = format_decimal(value=hours)
    return f'{french}{NO_BREAK_SPACE}h'


def format_date(day: datetime.date) -> str:
    """Format a date as DD/MM/YYYY."""
    return day.strftime('%d/%m/%Y')


def format_month(year: int, month: int) -> str:
    """Format a month with its French name, for example octobre 2026."""
    month_name = MONTH_NAMES[month - 1]
    return f'{month_name} {year}'


def format_month_title(year: int, month: int) -> str:
    """Format a month as a heading, with a capital, for example Octobre 2026."""
    return format_month(year=year, month=month).capitalize()


def format_iban(iban: str) -> str:
    """Format an IBAN in groups of four, for example BE71 0961 2345 6769."""
    groups = [iban[start : start + 4] for start in range(0, len(iban), 4)]
    return ' '.join(groups)


def remove_accents(text: str) -> str:
    """Give a text in plain ASCII letters, for example Michael for Michaël.

    Used where only basic characters are accepted: the payment file and file names. A
    letter without a plain form in Unicode is taken from PLAIN_LETTERS; any other character
    without one is left out.
    """
    decomposed = unicodedata.normalize('NFKD', text.translate(PLAIN_LETTERS))
    return decomposed.encode('ascii', 'ignore').decode('ascii')
