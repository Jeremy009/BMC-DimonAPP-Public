"""Checksum of an IBAN (R11.8)."""

import pytest

from dimonapp.iban import compute_iban_check_digits, is_valid_iban, normalise_iban


@pytest.mark.parametrize(
    'iban',
    ['BE71096123456769', 'be71 0961 2345 6769', 'BE68 5390 0754 7034', 'NL91ABNA0417164300'],
)
def test_r11_8_valid_ibans_are_accepted(iban: str) -> None:
    """Spaces and lower case are ignored, and another country than Belgium is fine."""
    assert is_valid_iban(iban=iban)


@pytest.mark.parametrize(
    'iban',
    [
        'BE71096123456768',
        'BE71096123546769',
        'BE7109612345676',
        '71096123456769BE',
        'BE71-0961-2345-6769',
        'BEXX096123456769',
        'BE71',
        '',
    ],
)
def test_r11_8_invalid_ibans_are_refused(iban: str) -> None:
    """A wrong digit, two swapped digits, a missing digit or a wrong form is refused."""
    assert not is_valid_iban(iban=iban)


def test_r11_8_iban_is_stored_without_spaces_in_capitals() -> None:
    """One stored form, whatever the admin typed."""
    assert normalise_iban(iban=' be71 0961 2345 6769 ') == 'BE71096123456769'


def test_r11_8_check_digits_make_a_valid_iban() -> None:
    """The computed check digits are those of a known IBAN."""
    check_digits = compute_iban_check_digits(country_code='BE', account_number='096123456769')

    assert check_digits == '71'
