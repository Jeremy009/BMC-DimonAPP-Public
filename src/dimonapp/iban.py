"""Checksum of an IBAN (R11.8), so a typing error never reaches the payment file.

Nothing here logs the IBAN (R3.5).
"""

MIN_LENGTH = 15
MAX_LENGTH = 34


def normalise_iban(iban: str) -> str:
    """Give an IBAN as stored: without spaces, in capitals."""
    return ''.join(iban.split()).upper()


def convert_to_digits(text: str) -> str:
    """Replace every letter by its number (A is 10, Z is 35), as the IBAN checksum asks."""
    return ''.join(str(int(character, 36)) for character in text)


def compute_iban_check_digits(country_code: str, account_number: str) -> str:
    """Compute the two check digits that follow the country code of an IBAN."""
    digits = convert_to_digits(text=f'{account_number}{country_code}00')
    check_digits = 98 - int(digits) % 97
    return f'{check_digits:02d}'


def is_valid_iban(iban: str) -> bool:
    """Tell whether an IBAN has a plausible form and a correct checksum (mod 97).

    Spaces and lower case are ignored, so 'be71 0961 2345 6769' is read as 'BE71096123456769'.
    Any country is accepted; the length is only checked against the IBAN standard.
    """
    compact = normalise_iban(iban=iban)
    if not MIN_LENGTH <= len(compact) <= MAX_LENGTH:
        return False
    if not compact.isascii() or not compact.isalnum():
        return False
    if not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rearranged = f'{compact[4:]}{compact[:4]}'
    return int(convert_to_digits(text=rearranged)) % 97 == 1
