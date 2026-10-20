"""Checksum of the Belgian national register number (R11.3).

Nothing here logs the number (R3.5).
"""

SEPARATORS = str.maketrans('', '', '.- ')
N_DIGITS = 11


def compute_check_digits(first_nine_digits: str, born_from_2000: bool) -> int:
    """Compute the two check digits: 97 minus the first nine digits modulo 97.

    For births from 2000 on, a 2 is put in front of the nine digits first.
    """
    prefix = '2' if born_from_2000 else ''
    number = int(f'{prefix}{first_nine_digits}')
    return 97 - number % 97


def normalise_national_register_number(number: str) -> str:
    """Give a national register number as stored: the digits without dots, dashes or spaces."""
    return number.translate(SEPARATORS)


def is_valid_national_register_number(number: str) -> bool:
    """Tell whether a national register number has eleven digits and a correct checksum.

    Dots, dashes and spaces are ignored, so '85.07.30-033.28' is read as '85073003328'.
    """
    digits = normalise_national_register_number(number=number)
    if len(digits) != N_DIGITS or not digits.isascii() or not digits.isdigit():
        return False
    first_nine_digits = digits[:9]
    check_digits = int(digits[9:])
    before_2000 = compute_check_digits(first_nine_digits=first_nine_digits, born_from_2000=False)
    from_2000 = compute_check_digits(first_nine_digits=first_nine_digits, born_from_2000=True)
    return check_digits in (before_2000, from_2000)


def format_national_register_number(number: str) -> str:
    """Format a stored national register number for a document, for example 85.07.30-033.28."""
    return f'{number[:2]}.{number[2:4]}.{number[4:6]}-{number[6:9]}.{number[9:]}'
