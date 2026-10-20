"""Configuration by the admin: the yearly legal limits and BMC's own details (FDS 7.7).

Plain functions on a database session. Only the structure of the limits table lives here;
every value is entered by the admin and stored in yearly_limits (R15.2).
"""

import logging
import math
from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.compliance import find_configured_years
from dimonapp.iban import is_valid_iban, normalise_iban
from dimonapp.labels import PERIOD_LABELS
from dimonapp.models import Activity, OrganisationConfig, Period, WorkerType, YearlyLimit
from dimonapp.results import ActionResult
from dimonapp.worker_types import WORKER_TYPE_LABELS

logger = logging.getLogger(__name__)

# The rows of the limits table, in the order shown. Freelancers have no limits (R5.6).
LIMIT_ROWS = (
    (WorkerType.VRIJWILLIGER, Period.YEAR),
    (WorkerType.ARTICLE_17, Period.Q1),
    (WorkerType.ARTICLE_17, Period.Q2),
    (WorkerType.ARTICLE_17, Period.Q3),
    (WorkerType.ARTICLE_17, Period.Q4),
    (WorkerType.ARTICLE_17, Period.YEAR),
    (WorkerType.FLEXI_JOB, Period.YEAR),
)

WORKER_TYPE_COLUMN = 'Type de travailleur'
PERIOD_COLUMN = 'Période'
HOURS_COLUMN = "Limite d'heures"
EURO_COLUMN = 'Limite en euros'
MIN_HOURS_COLUMN = 'Heures min. par activité'
VALUE_COLUMNS = {
    HOURS_COLUMN: 'hours_limit',
    EURO_COLUMN: 'euro_limit',
    MIN_HOURS_COLUMN: 'min_hours_per_activity',
}

# The largest values the columns of yearly_limits can hold.
MAX_HOURS = Decimal('9999.99')
MAX_EURO = Decimal('99999999.99')

NEGATIVE_LIMIT_MESSAGE = 'Limites non enregistrées : une limite ne peut pas être négative.'
TOO_HIGH_LIMIT_MESSAGE = (
    'Limites non enregistrées : une limite dépasse la valeur maximale '
    '(9 999,99 heures ou 99 999 999,99 €).'
)
ORGANISATION_NOT_SAVED_PREFIX = 'Coordonnées non enregistrées : '
ORGANISATION_INCOMPLETE_MESSAGE = f'{ORGANISATION_NOT_SAVED_PREFIX}remplissez tous les champs.'
INVALID_COMPANY_NUMBER_MESSAGE = (
    f"{ORGANISATION_NOT_SAVED_PREFIX}le numéro d'entreprise doit compter dix chiffres."
)
INVALID_POSTAL_CODE_MESSAGE = (
    f'{ORGANISATION_NOT_SAVED_PREFIX}le code postal doit être un code postal belge '
    '(quatre chiffres).'
)
INVALID_ORGANISATION_IBAN_MESSAGE = (
    f"{ORGANISATION_NOT_SAVED_PREFIX}l'IBAN n'est pas valide (clé de contrôle)."
)
N_COMPANY_NUMBER_DIGITS = 10
ORGANISATION_SAVED_MESSAGE = 'Coordonnées de BMC enregistrées.'


class LimitLine(BaseModel):
    """The limits of one worker type for one period; an empty value means no limit."""

    worker_type: WorkerType
    period: Period
    hours_limit: Optional[Decimal] = None
    euro_limit: Optional[Decimal] = None
    min_hours_per_activity: Optional[Decimal] = None


class OrganisationForm(BaseModel):
    """BMC's company number and debtor details (R15.4).

    address is the street and number; contact_details is the contact e-mail address. The IBAN
    is the account the payment file pays from (R13.2).
    """

    company_number: str = ''
    name: str = ''
    address: str = ''
    postal_code: str = ''
    city: str = ''
    contact_person: str = ''
    phone: str = ''
    contact_details: str = ''
    iban: str = ''


def read_company_number_digits(company_number: str) -> str:
    """Give the digits of a company number, as Belcotax wants it: 0123.456.789 is 0123456789."""
    return ''.join(character for character in company_number if character.isdigit())


def is_belgian_postal_code(postal_code: str) -> bool:
    """Tell whether a text is a Belgian postal code: four digits, from 1000 on."""
    is_four_digits = len(postal_code) == 4 and postal_code.isascii() and postal_code.isdigit()
    return is_four_digits and postal_code >= '1000'


def find_configuration_years(session: Session, today: date) -> list[int]:
    """Give the years the admin can configure: this year, the next, and every year in use."""
    limit_years = session.scalars(sa.select(YearlyLimit.year).distinct())
    activity_years = session.scalars(
        sa.select(sa.extract('year', Activity.activity_date)).distinct()
    )
    years = {today.year, today.year + 1}
    years.update(limit_years)
    years.update(int(year) for year in activity_years)
    return sorted(years)


def is_year_configured(session: Session, year: int) -> bool:
    """Tell whether every required limit of a year is filled in (R16.4)."""
    limits = list(session.scalars(sa.select(YearlyLimit).where(YearlyLimit.year == year)))
    return year in find_configured_years(limits=limits)


def load_limit_lines(session: Session, year: int) -> list[LimitLine]:
    """Give the limits of one year as the fixed rows of the table; unknown rows are empty."""
    limits = list(session.scalars(sa.select(YearlyLimit).where(YearlyLimit.year == year)))
    stored_limits = {(limit.worker_type, limit.period): limit for limit in limits}
    lines = []
    for worker_type, period in LIMIT_ROWS:
        line = LimitLine(worker_type=worker_type, period=period)
        limit = stored_limits.get((worker_type, period))
        if limit is not None:
            line.hours_limit = limit.hours_limit
            line.euro_limit = limit.euro_limit
            line.min_hours_per_activity = limit.min_hours_per_activity
        lines.append(line)
    return lines


def build_limit_table(lines: list[LimitLine]) -> list[dict[str, object]]:
    """Build the editable table of the limits of one year, with French headers."""
    rows = []
    for line in lines:
        row: dict[str, object] = {
            WORKER_TYPE_COLUMN: WORKER_TYPE_LABELS[line.worker_type],
            PERIOD_COLUMN: PERIOD_LABELS[line.period],
        }
        for column in VALUE_COLUMNS:
            value = getattr(line, VALUE_COLUMNS[column])
            row[column] = float(value) if value is not None else None
        rows.append(row)
    return rows


def read_table_value(value: object) -> Optional[Decimal]:
    """Read one cell of the edited table: a number, or nothing when the cell is empty."""
    if value is None:
        return None
    number = float(value)
    if math.isnan(number):
        return None
    return Decimal(str(number))


def read_limit_table(rows: list[dict[str, object]]) -> list[LimitLine]:
    """Read the edited table back; the rows keep the fixed order of LIMIT_ROWS."""
    lines = []
    for row_index, (worker_type, period) in enumerate(LIMIT_ROWS):
        row = rows[row_index]
        line = LimitLine(worker_type=worker_type, period=period)
        for column in VALUE_COLUMNS:
            value = read_table_value(value=row.get(column))
            setattr(line, VALUE_COLUMNS[column], value)
        lines.append(line)
    return lines


def find_limit_line_error(line: LimitLine) -> Optional[str]:
    """Give the French message of a value the database cannot hold, or None."""
    checks = (
        (line.hours_limit, MAX_HOURS),
        (line.euro_limit, MAX_EURO),
        (line.min_hours_per_activity, MAX_HOURS),
    )
    for value, max_value in checks:
        if value is None:
            continue
        if value < 0:
            return NEGATIVE_LIMIT_MESSAGE
        if value > max_value:
            return TOO_HIGH_LIMIT_MESSAGE
    return None


def save_limit_lines(session: Session, year: int, lines: list[LimitLine]) -> ActionResult:
    """Store the limits of one year, replacing what was there (R15.1).

    The result warns when the year is still not completely configured, because the compliance
    engine then raises no flag for it (R16.4).
    """
    for line in lines:
        error = find_limit_line_error(line=line)
        if error is not None:
            return ActionResult(level='error', message=error)

    limits = list(session.scalars(sa.select(YearlyLimit).where(YearlyLimit.year == year)))
    stored_limits = {(limit.worker_type, limit.period): limit for limit in limits}
    for line in lines:
        limit = stored_limits.get((line.worker_type, line.period))
        if limit is None:
            limit = YearlyLimit(year=year, worker_type=line.worker_type, period=line.period)
            session.add(limit)
        limit.hours_limit = line.hours_limit
        limit.euro_limit = line.euro_limit
        limit.min_hours_per_activity = line.min_hours_per_activity
    session.flush()
    logger.info(f'Limits of {year} saved.')

    if not is_year_configured(session=session, year=year):
        message = (
            f"Limites {year} enregistrées, mais l'année reste non configurée : il manque des "
            'limites obligatoires.'
        )
        return ActionResult(level='warning', message=message)
    return ActionResult(level='success', message=f'Limites {year} enregistrées.')


def load_organisation(session: Session) -> OrganisationForm:
    """Give BMC's details as stored; every detail is empty until they are entered."""
    organisation = session.scalars(sa.select(OrganisationConfig)).first()
    if organisation is None:
        return OrganisationForm()
    return OrganisationForm(
        company_number=organisation.company_number,
        name=organisation.name,
        address=organisation.address,
        postal_code=organisation.postal_code,
        city=organisation.city,
        contact_person=organisation.contact_person,
        phone=organisation.phone,
        contact_details=organisation.contact_details,
        iban=organisation.iban,
    )


def clean_organisation_form(form: OrganisationForm) -> OrganisationForm:
    """Give the form as it is stored: trimmed, the IBAN without spaces in capitals."""
    return OrganisationForm(
        company_number=form.company_number.strip(),
        name=form.name.strip(),
        address=form.address.strip(),
        postal_code=form.postal_code.strip(),
        city=form.city.strip(),
        contact_person=form.contact_person.strip(),
        phone=form.phone.strip(),
        contact_details=form.contact_details.strip(),
        iban=normalise_iban(iban=form.iban),
    )


def find_organisation_form_error(form: OrganisationForm) -> Optional[str]:
    """Give the French message of the first problem in a cleaned form, or None.

    Every detail is needed: the Belcotax file and the payment file cannot be built without.
    """
    values = form.model_dump()
    if not all(values[field] for field in values):
        return ORGANISATION_INCOMPLETE_MESSAGE
    company_number_digits = read_company_number_digits(company_number=form.company_number)
    if len(company_number_digits) != N_COMPANY_NUMBER_DIGITS:
        return INVALID_COMPANY_NUMBER_MESSAGE
    if not is_belgian_postal_code(postal_code=form.postal_code):
        return INVALID_POSTAL_CODE_MESSAGE
    if not is_valid_iban(iban=form.iban):
        return INVALID_ORGANISATION_IBAN_MESSAGE
    return None


def is_organisation_complete(organisation: OrganisationForm) -> bool:
    """Tell whether BMC's stored details are enough for the exports (R13.2, R14.2)."""
    cleaned_form = clean_organisation_form(form=organisation)
    return find_organisation_form_error(form=cleaned_form) is None


def save_organisation(session: Session, form: OrganisationForm) -> ActionResult:
    """Store BMC's details in the single row of organisation_config (R15.4)."""
    cleaned_form = clean_organisation_form(form=form)
    error = find_organisation_form_error(form=cleaned_form)
    if error is not None:
        return ActionResult(level='error', message=error)

    organisation = session.scalars(sa.select(OrganisationConfig)).first()
    if organisation is None:
        organisation = OrganisationConfig()
        session.add(organisation)
    values = cleaned_form.model_dump()
    for field in values:
        setattr(organisation, field, values[field])
    session.flush()
    logger.info('Organisation details saved.')
    return ActionResult(level='success', message=ORGANISATION_SAVED_MESSAGE)
