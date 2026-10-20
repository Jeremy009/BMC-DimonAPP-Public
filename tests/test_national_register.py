"""National register number checksum (R11.3)."""

import pytest

from dimonapp.national_register import (
    format_national_register_number,
    is_valid_national_register_number,
    normalise_national_register_number,
)


@pytest.mark.parametrize('number', ['85073003328', '01032030341', '85.07.30-033.28'])
def test_r11_3_valid_numbers_are_accepted(number: str) -> None:
    """Births before and from 2000 pass, with or without separators."""
    assert is_valid_national_register_number(number=number)


@pytest.mark.parametrize(
    'number',
    ['85073003329', '85073013328', '8507300332', '850730033280', '8507300332A', ''],
)
def test_r11_3_invalid_numbers_are_refused(number: str) -> None:
    """A wrong digit, a wrong length or a letter is refused."""
    assert not is_valid_national_register_number(number=number)


def test_r11_3_number_is_stored_without_separators() -> None:
    """Dots, dashes and spaces are dropped before the number is stored."""
    assert normalise_national_register_number(number='85.07.30-033 28') == '85073003328'


def test_r14_2_number_is_formatted_for_a_document() -> None:
    """The fiche shows the number as on an identity card."""
    assert format_national_register_number(number='85073003328') == '85.07.30-033.28'
