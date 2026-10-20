"""The Belcotax-on-web XML with the fiches 281.27 (R14.2, R14.4)."""

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from dimonapp import belcotax
from dimonapp.belcotax import build_belcotax_file
from dimonapp.xml_schemas import SCHEMA_FOLDER, load_schema, write_checked_xml
from factories import VALID_NATIONAL_REGISTER_NUMBER, build_fiche_line, build_organisation_form

CREATED_ON = date(2026, 1, 15)


def build_document(n_fiches: int = 1) -> etree._Element:
    """Build the Belcotax file of 2025 with a number of equal fiches and parse it again."""
    lines = [build_fiche_line() for _ in range(n_fiches)]
    content = build_belcotax_file(
        lines=lines,
        organisation=build_organisation_form(),
        year=2025,
        created_on=CREATED_ON,
    )
    return etree.fromstring(content)


def read_zones(parent: etree._Element) -> dict[str, str]:
    """Give the zones directly under an element with their text."""
    return {child.tag: child.text for child in parent if child.text and child.text.strip()}


def test_r14_4_schema_version_is_a_single_constant_with_its_file() -> None:
    """The target is belcotax-2025.xsd, stored with the code."""
    assert belcotax.BELCOTAX_SCHEMA_YEAR == 2025
    assert belcotax.BELCOTAX_SCHEMA_FILE == 'belcotax-2025.xsd'
    assert (SCHEMA_FOLDER / belcotax.BELCOTAX_SCHEMA_FILE).is_file()


def test_r14_4_belcotax_file_follows_the_schema() -> None:
    """The generated file is valid against the official schema."""
    document = build_document()

    schema = load_schema(file_name=belcotax.BELCOTAX_SCHEMA_FILE)
    assert document.tag == 'Verzendingen'
    assert schema.validate(document)


def test_r14_4_file_that_breaks_the_schema_never_leaves_the_application() -> None:
    """A document the schema refuses raises an error instead of being given."""
    root = etree.Element('Verzendingen')
    etree.SubElement(root, 'Inconnu')

    with pytest.raises(ValueError):
        write_checked_xml(root=root, schema_file_name=belcotax.BELCOTAX_SCHEMA_FILE)


def test_r14_2_belcotax_file_names_bmc_as_sender_and_debtor() -> None:
    """BMC's details of the configuration, the company number as ten digits."""
    document = build_document()

    sending = read_zones(parent=document.find('Verzending'))
    declaration = read_zones(parent=document.find('.//Aangifte'))
    assert sending['v0002_inkomstenjaar'] == '2025'
    assert sending['v0010_bestandtype'] == 'BELCOTAX'
    assert sending['v0011_aanmaakdatum'] == '15-01-2026'
    assert sending['v0014_naam'] == 'Brussels Monkeys Climbing ASBL'
    assert sending['v0015_adres'] == 'Rue Exemple 1'
    assert sending['v0016_postcode'] == '1000'
    assert sending['v0017_gemeente'] == 'Bruxelles'
    assert sending['v0018_telefoonnummer'] == '021234567'
    assert sending['v0021_contactpersoon'] == 'Ada Admin'
    assert sending['v0022_taalcode'] == '2'
    assert sending['v0023_emailadres'] == 'info@example.com'
    assert sending['v0024_nationaalnr'] == '0123456789'
    assert sending['v0025_typeenvoi'] == '0'
    assert declaration['a1005_registratienummer'] == '0123456789'
    # The name of the debtor holds at most 28 characters
    assert declaration['a1011_naamnl1'] == 'Brussels Monkeys Climbing AS'
    assert declaration['a1014_postcodebelgisch'] == '1000'
    assert declaration['a1020_taalcode'] == '2'


def test_r14_2_fiche_holds_the_worker_and_the_totals_in_cents_and_hundredths() -> None:
    """Amounts in eurocents, hours per quarter in hundredths, the control total over both."""
    document = build_document()

    fiche = read_zones(parent=document.find('.//Opgave32527/Fiche28127'))
    assert fiche == {
        'f2002_inkomstenjaar': '2025',
        'f2005_registratienummer': '0123456789',
        'f2008_typefiche': '28127',
        'f2009_volgnummer': '1',
        'f2011_nationaalnr': VALID_NATIONAL_REGISTER_NUMBER,
        'f2013_naam': 'Peeters',
        'f2015_adres': 'Rue Imaginaire 12',
        'f2016_postcodebelgisch': '1050',
        'f2017_gemeente': 'Ixelles',
        'f2018_landwoonplaats': '150',
        'f2028_typetraitement': '0',
        'f2029_enkelopgave325': '0',
        'f2114_voornamen': 'Lotte',
        'f27_2059_totaalcontrole': '246900',
        'f27_2060_beloning': '123450',
        'f27_2063_amountthisyear': '123450',
        'f27_2099_sector': 'A',
        'f27_2167_overuren': '1050',
        'f27_2168_overuren': '0',
        'f27_2169_overuren': '300',
        'f27_2170_overuren': '0',
    }


def test_r14_2_closing_records_count_and_total_the_fiches() -> None:
    """Three fiches: numbered 1 to 3, with the record counts and control totals of the brochure."""
    document = build_document(n_fiches=3)

    numbers = [element.text for element in document.iterfind('.//f2009_volgnummer')]
    declaration = read_zones(parent=document.find('.//Aangifte'))
    sending = read_zones(parent=document.find('Verzending'))
    assert numbers == ['1', '2', '3']
    assert declaration['r8010_aantalrecords'] == '5'
    assert declaration['r8011_controletotaal'] == '6'
    assert declaration['r8012_controletotaal'] == '740700'
    assert sending['r9010_aantallogbestanden'] == '3'
    assert sending['r9011_totaalaantalrecords'] == '7'
    assert sending['r9012_controletotaal'] == '6'
    assert sending['r9013_controletotaal'] == '740700'


def test_r3_5_belcotax_file_logs_no_national_register_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log only tells the year and the number of fiches."""
    caplog.set_level('INFO')

    build_document()

    assert 'Belcotax file of 2025 built: 1 fiches.' in caplog.text
    assert VALID_NATIONAL_REGISTER_NUMBER not in caplog.text
    assert 'Peeters' not in caplog.text


def test_r14_2_amounts_convert_exactly() -> None:
    """Decimals keep the cents exact."""
    assert belcotax.convert_to_hundredths(value=Decimal('46.63')) == 4663
    assert belcotax.convert_to_hundredths(value=Decimal('1.75')) == 175
