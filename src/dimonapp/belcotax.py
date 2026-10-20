"""The Belcotax-on-web XML file with the fiches 281.27 of one income year (R14.2, R14.4).

Built after the Belcotax-on-web brochure of FOD Financiën (income year 2025, record 281.27)
and checked against the official schema. Amounts are in eurocents and hours in hundredths of
an hour, as the brochure asks. National register numbers are never logged (R3.5).
"""

import logging
from datetime import date
from decimal import Decimal

from lxml import etree

from dimonapp.activities import QUARTERS
from dimonapp.configuration import OrganisationForm, read_company_number_digits
from dimonapp.fiche_lines import FicheLine
from dimonapp.models import Period
from dimonapp.xml_schemas import add_child, write_checked_xml

logger = logging.getLogger(__name__)

# The income year of the Belcotax schema stored with the code; the only place it is named.
# Update it, with the schema file, when FOD Financiën publishes the next one (R14.4).
BELCOTAX_SCHEMA_YEAR = 2025
BELCOTAX_SCHEMA_FILE = f'belcotax-{BELCOTAX_SCHEMA_YEAR}.xsd'

FILE_TYPE = 'BELCOTAX'
FICHE_TYPE = '28127'
# French: the language of the receipts FOD Financiën sends and of BMC as debtor.
LANGUAGE_FRENCH = '2'
COUNTRY_BELGIUM = '150'
ORDINARY_SENDING = '0'
ORDINARY_FICHE = '0'
INDIVIDUAL_FICHE = '0'
# Zone 2.099: A is the sports sector, B the socio-cultural sector.
# NOTE: to be confirmed by BMC; a climbing gym is taken to be the sports sector.
SECTOR = 'A'
QUARTER_HOURS_ZONES = {
    Period.Q1: 'f27_2167_overuren',
    Period.Q2: 'f27_2168_overuren',
    Period.Q3: 'f27_2169_overuren',
    Period.Q4: 'f27_2170_overuren',
}
# The longest text the zones accept, from the brochure.
MAX_SENDER_NAME_LENGTH = 41
MAX_DEBTOR_NAME_LENGTH = 28
MAX_SENDER_ADDRESS_LENGTH = 32
MAX_SENDER_CITY_LENGTH = 27
MAX_PHONE_LENGTH = 12
MAX_CONTACT_PERSON_LENGTH = 34
MAX_LAST_NAME_LENGTH = 41
MAX_FIRST_NAME_LENGTH = 15
MAX_ADDRESS_LENGTH = 150
MAX_CITY_LENGTH = 27


def convert_to_hundredths(value: Decimal) -> int:
    """Give an amount in eurocents or a number of hours in hundredths of an hour."""
    return int(value * 100)


def add_fiche(
    parent: etree._Element,
    line: FicheLine,
    year: int,
    company_number: str,
    sequence_number: int,
) -> int:
    """Add the fiche of one worker; give its control total (zone 2.059).

    Everything was earned in the income year itself, so zone 2.063 equals the total 2.060 and
    the control total, the sum of the zones 2.060 to 2.088, is twice the amount.
    """
    cents = convert_to_hundredths(value=line.amount)
    control_total = 2 * cents
    fiche = add_child(parent=parent, tag='Fiche28127')
    add_child(parent=fiche, tag='f2002_inkomstenjaar', text=str(year))
    add_child(parent=fiche, tag='f2005_registratienummer', text=company_number)
    add_child(parent=fiche, tag='f2008_typefiche', text=FICHE_TYPE)
    add_child(parent=fiche, tag='f2009_volgnummer', text=str(sequence_number))
    add_child(parent=fiche, tag='f2011_nationaalnr', text=line.national_register_number)
    add_child(parent=fiche, tag='f2013_naam', text=line.last_name[:MAX_LAST_NAME_LENGTH])
    add_child(parent=fiche, tag='f2015_adres', text=line.street[:MAX_ADDRESS_LENGTH])
    add_child(parent=fiche, tag='f2016_postcodebelgisch', text=line.postal_code)
    add_child(parent=fiche, tag='f2017_gemeente', text=line.city[:MAX_CITY_LENGTH])
    add_child(parent=fiche, tag='f2018_landwoonplaats', text=COUNTRY_BELGIUM)
    add_child(parent=fiche, tag='f2028_typetraitement', text=ORDINARY_FICHE)
    add_child(parent=fiche, tag='f2029_enkelopgave325', text=INDIVIDUAL_FICHE)
    add_child(parent=fiche, tag='f2114_voornamen', text=line.first_name[:MAX_FIRST_NAME_LENGTH])
    add_child(parent=fiche, tag='f27_2059_totaalcontrole', text=str(control_total))
    add_child(parent=fiche, tag='f27_2060_beloning', text=str(cents))
    add_child(parent=fiche, tag='f27_2063_amountthisyear', text=str(cents))
    add_child(parent=fiche, tag='f27_2099_sector', text=SECTOR)
    for quarter in QUARTERS:
        hundredths = convert_to_hundredths(value=line.quarter_hours[quarter])
        add_child(parent=fiche, tag=QUARTER_HOURS_ZONES[quarter], text=str(hundredths))
    return control_total


def build_belcotax_file(
    lines: list[FicheLine],
    organisation: OrganisationForm,
    year: int,
    created_on: date,
) -> bytes:
    """Build the Belcotax XML of one income year: one sending, one declaration (R14.2).

    BMC is both the sender and the debtor of the income. The fiches are numbered from 1 in the
    order of the lines. The file is checked against the schema before it is given.
    """
    company_number = read_company_number_digits(company_number=organisation.company_number)
    income_year = str(year)
    n_fiches = len(lines)

    # The sending: BMC as sender
    root = etree.Element('Verzendingen')
    sending = add_child(parent=root, tag='Verzending')
    add_child(parent=sending, tag='v0002_inkomstenjaar', text=income_year)
    add_child(parent=sending, tag='v0010_bestandtype', text=FILE_TYPE)
    add_child(parent=sending, tag='v0011_aanmaakdatum', text=f'{created_on:%d-%m-%Y}')
    add_child(parent=sending, tag='v0014_naam', text=organisation.name[:MAX_SENDER_NAME_LENGTH])
    sender_address = organisation.address[:MAX_SENDER_ADDRESS_LENGTH]
    sender_city = organisation.city[:MAX_SENDER_CITY_LENGTH]
    add_child(parent=sending, tag='v0015_adres', text=sender_address)
    add_child(parent=sending, tag='v0016_postcode', text=organisation.postal_code)
    add_child(parent=sending, tag='v0017_gemeente', text=sender_city)
    phone = organisation.phone[:MAX_PHONE_LENGTH]
    add_child(parent=sending, tag='v0018_telefoonnummer', text=phone)
    contact_person = organisation.contact_person[:MAX_CONTACT_PERSON_LENGTH]
    add_child(parent=sending, tag='v0021_contactpersoon', text=contact_person)
    add_child(parent=sending, tag='v0022_taalcode', text=LANGUAGE_FRENCH)
    add_child(parent=sending, tag='v0023_emailadres', text=organisation.contact_details)
    add_child(parent=sending, tag='v0024_nationaalnr', text=company_number)
    add_child(parent=sending, tag='v0025_typeenvoi', text=ORDINARY_SENDING)

    # The declaration: BMC as debtor of the income
    declarations = add_child(parent=sending, tag='Aangiften')
    declaration = add_child(parent=declarations, tag='Aangifte')
    add_child(parent=declaration, tag='a1002_inkomstenjaar', text=income_year)
    add_child(parent=declaration, tag='a1005_registratienummer', text=company_number)
    debtor_name = organisation.name[:MAX_DEBTOR_NAME_LENGTH]
    add_child(parent=declaration, tag='a1011_naamnl1', text=debtor_name)
    add_child(parent=declaration, tag='a1013_adresnl', text=sender_address)
    add_child(parent=declaration, tag='a1014_postcodebelgisch', text=organisation.postal_code)
    add_child(parent=declaration, tag='a1015_gemeente', text=sender_city)
    add_child(parent=declaration, tag='a1016_landwoonplaats', text=COUNTRY_BELGIUM)
    add_child(parent=declaration, tag='a1020_taalcode', text=LANGUAGE_FRENCH)

    # One fiche per worker
    groups = add_child(parent=declaration, tag='Opgaven')
    group = add_child(parent=groups, tag='Opgave32527')
    control_total = 0
    for sequence_number, line in enumerate(lines, start=1):
        control_total += add_fiche(
            parent=group,
            line=line,
            year=year,
            company_number=company_number,
            sequence_number=sequence_number,
        )

    # The closing records, with the totals FOD Financiën checks the file with
    sequence_total = str(sum(range(1, n_fiches + 1)))
    add_child(parent=declaration, tag='r8002_inkomstenjaar', text=income_year)
    add_child(parent=declaration, tag='r8005_registratienummer', text=company_number)
    add_child(parent=declaration, tag='r8010_aantalrecords', text=str(n_fiches + 2))
    add_child(parent=declaration, tag='r8011_controletotaal', text=sequence_total)
    add_child(parent=declaration, tag='r8012_controletotaal', text=str(control_total))
    add_child(parent=declaration, tag='r8013_totaalvoorheffingen', text='0')
    add_child(parent=sending, tag='r9002_inkomstenjaar', text=income_year)
    add_child(parent=sending, tag='r9010_aantallogbestanden', text='3')
    add_child(parent=sending, tag='r9011_totaalaantalrecords', text=str(n_fiches + 4))
    add_child(parent=sending, tag='r9012_controletotaal', text=sequence_total)
    add_child(parent=sending, tag='r9013_controletotaal', text=str(control_total))
    add_child(parent=sending, tag='r9014_controletotaal', text='0')

    belcotax_file = write_checked_xml(root=root, schema_file_name=BELCOTAX_SCHEMA_FILE)
    logger.info(f'Belcotax file of {year} built: {n_fiches} fiches.')
    return belcotax_file
