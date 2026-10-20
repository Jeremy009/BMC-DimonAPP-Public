"""Configuration: yearly limits and BMC's details (R15.1, R15.3, R15.4)."""

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp import configuration
from dimonapp.compliance import REQUIRED_LIMITS
from dimonapp.configuration import (
    LIMIT_ROWS,
    LimitLine,
    OrganisationForm,
    build_limit_table,
    find_configuration_years,
    is_organisation_complete,
    is_year_configured,
    load_limit_lines,
    load_organisation,
    read_company_number_digits,
    read_limit_table,
    save_limit_lines,
    save_organisation,
)
from dimonapp.models import OrganisationConfig, Period, WorkerType, YearlyLimit
from dimonapp.submission import find_min_hours
from factories import build_activity, build_limit, build_organisation_form, build_worker

TODAY = date(2026, 10, 10)
INDICATIVE_VALUES = {
    (WorkerType.VRIJWILLIGER, Period.YEAR): {'euro_limit': Decimal('1900')},
    (WorkerType.ARTICLE_17, Period.Q1): {'hours_limit': Decimal('150')},
    (WorkerType.ARTICLE_17, Period.Q2): {'hours_limit': Decimal('150')},
    (WorkerType.ARTICLE_17, Period.Q3): {'hours_limit': Decimal('285')},
    (WorkerType.ARTICLE_17, Period.Q4): {'hours_limit': Decimal('150')},
    (WorkerType.ARTICLE_17, Period.YEAR): {
        'hours_limit': Decimal('450'),
        'euro_limit': Decimal('7700'),
    },
    (WorkerType.FLEXI_JOB, Period.YEAR): {
        'euro_limit': Decimal('18000'),
        'min_hours_per_activity': Decimal('3'),
    },
}


def build_complete_lines() -> list[LimitLine]:
    """Build the seven rows of the table with every required limit filled in."""
    return [
        LimitLine(worker_type=worker_type, period=period, **INDICATIVE_VALUES[worker_type, period])
        for worker_type, period in LIMIT_ROWS
    ]


def test_r15_1_table_has_a_row_per_worker_type_and_period() -> None:
    """Every required limit has its row; freelancers have none (R5.6)."""
    row_keys = set(LIMIT_ROWS)
    required_keys = {(worker_type, period) for worker_type, period, _ in REQUIRED_LIMITS}

    assert required_keys == row_keys
    assert WorkerType.FREELANCER not in {worker_type for worker_type, _ in LIMIT_ROWS}


def test_r15_1_admin_sets_the_limits_of_a_year(session: Session) -> None:
    """The saved limits are stored per year, worker type and period, and configure the year."""
    result = save_limit_lines(session=session, year=2027, lines=build_complete_lines())

    limits = list(session.scalars(sa.select(YearlyLimit).where(YearlyLimit.year == 2027)))
    third_quarter = [limit for limit in limits if limit.period == Period.Q3][0]
    assert result.level == 'success'
    assert result.message == 'Limites 2027 enregistrées.'
    assert len(limits) == len(LIMIT_ROWS)
    assert third_quarter.worker_type == WorkerType.ARTICLE_17
    assert third_quarter.hours_limit == Decimal('285.00')
    assert is_year_configured(session=session, year=2027)
    assert not is_year_configured(session=session, year=2026)
    assert find_min_hours(session=session, year=2027) == Decimal('3.00')


def test_r15_1_saving_again_replaces_the_values(session: Session) -> None:
    """A second save changes the stored rows instead of adding new ones."""
    save_limit_lines(session=session, year=2027, lines=build_complete_lines())
    lines = load_limit_lines(session=session, year=2027)
    lines[0].euro_limit = Decimal('2000')
    lines[1].euro_limit = Decimal('500')

    save_limit_lines(session=session, year=2027, lines=lines)

    reloaded = load_limit_lines(session=session, year=2027)
    n_limits = session.scalar(sa.select(sa.func.count()).select_from(YearlyLimit))
    assert n_limits == len(LIMIT_ROWS)
    assert reloaded[0].euro_limit == Decimal('2000.00')
    assert reloaded[1].euro_limit == Decimal('500.00')
    assert reloaded[1].hours_limit == Decimal('150.00')


def test_r16_4_incomplete_year_is_saved_with_a_warning(session: Session) -> None:
    """A missing required limit is allowed, but the admin is told the year is not configured."""
    lines = build_complete_lines()
    lines[3].hours_limit = None

    result = save_limit_lines(session=session, year=2027, lines=lines)

    assert result.level == 'warning'
    assert result.message == (
        "Limites 2027 enregistrées, mais l'année reste non configurée : il manque des "
        'limites obligatoires.'
    )
    assert not is_year_configured(session=session, year=2027)
    assert load_limit_lines(session=session, year=2027)[0].euro_limit == Decimal('1900.00')


def test_r15_1_negative_limit_is_refused(session: Session) -> None:
    """Nothing is stored when a value is below zero."""
    lines = build_complete_lines()
    lines[0].euro_limit = Decimal('-1')

    result = save_limit_lines(session=session, year=2027, lines=lines)

    assert result.level == 'error'
    assert result.message == configuration.NEGATIVE_LIMIT_MESSAGE
    assert session.scalar(sa.select(sa.func.count()).select_from(YearlyLimit)) == 0


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('hours_limit', Decimal('10000')),
        ('euro_limit', Decimal('100000000')),
        ('min_hours_per_activity', Decimal('10000')),
    ],
)
def test_r15_1_limit_too_high_for_the_database_is_refused(
    session: Session,
    field: str,
    value: Decimal,
) -> None:
    """A value the column cannot hold gives a message, not a database error."""
    lines = build_complete_lines()
    setattr(lines[5], field, value)

    result = save_limit_lines(session=session, year=2027, lines=lines)

    assert result.level == 'error'
    assert result.message == configuration.TOO_HIGH_LIMIT_MESSAGE
    assert session.scalar(sa.select(sa.func.count()).select_from(YearlyLimit)) == 0


def test_r15_1_unconfigured_year_opens_as_an_empty_table(session: Session) -> None:
    """Seven rows without values: nothing is guessed or copied from another year (R16.4)."""
    session.add(build_limit(year=2026, euro_limit=Decimal('7700')))
    session.flush()

    lines = load_limit_lines(session=session, year=2027)

    assert [(line.worker_type, line.period) for line in lines] == list(LIMIT_ROWS)
    for line in lines:
        assert line.hours_limit is None
        assert line.euro_limit is None
        assert line.min_hours_per_activity is None


def test_r15_1_table_shows_french_headers_and_periods() -> None:
    """The editable table uses the French names of FDS 3.4 (R18.1)."""
    table = build_limit_table(lines=build_complete_lines())

    assert list(table[0]) == [
        'Type de travailleur',
        'Période',
        "Limite d'heures",
        'Limite en euros',
        'Heures min. par activité',
    ]
    assert [row['Période'] for row in table] == ['ANNÉE', 'T1', 'T2', 'T3', 'T4', 'ANNÉE', 'ANNÉE']
    assert table[0]['Type de travailleur'] == 'Volontaire'
    assert table[0]["Limite d'heures"] is None
    assert table[0]['Limite en euros'] == 1900.0
    assert table[6]['Heures min. par activité'] == 3.0


def test_r15_1_edited_table_is_read_back_with_empty_cells() -> None:
    """An emptied cell, as None or not-a-number, means no limit."""
    table = build_limit_table(lines=build_complete_lines())
    table[0]['Limite en euros'] = 1950.5
    table[1]["Limite d'heures"] = float('nan')
    table[5]['Limite en euros'] = None

    lines = read_limit_table(rows=table)

    assert lines[0].euro_limit == Decimal('1950.5')
    assert lines[1].hours_limit is None
    assert lines[5].euro_limit is None
    assert lines[5].hours_limit == Decimal('450.0')
    assert lines[6].worker_type == WorkerType.FLEXI_JOB


def test_r15_3_years_offered_are_those_in_use_this_year_and_the_next(session: Session) -> None:
    """Any year can be edited; there is no active year to pick."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    session.add(build_activity(worker_id=worker.id, activity_date=date(2024, 3, 1)))
    session.add(build_limit(year=2025))
    session.flush()

    years = find_configuration_years(session=session, today=TODAY)

    assert years == [2024, 2025, 2026, 2027]
    assert not hasattr(configuration, 'active_year')


def test_r15_4_admin_maintains_the_organisation_details(session: Session) -> None:
    """The details are stored in the single row, cleaned, and replaced by a later save."""
    empty = load_organisation(session=session)
    form = build_organisation_form()
    form.company_number = ' 0123.456.789 '
    form.iban = 'be97 0000 0000 0099'

    result = save_organisation(session=session, form=form)
    form.contact_details = 'contact@example.com'
    save_organisation(session=session, form=form)

    stored = load_organisation(session=session)
    n_rows = session.scalar(sa.select(sa.func.count()).select_from(OrganisationConfig))
    assert empty.company_number == ''
    assert empty.iban == ''
    assert not is_organisation_complete(organisation=empty)
    assert result.level == 'success'
    assert n_rows == 1
    assert stored.company_number == '0123.456.789'
    assert stored.contact_details == 'contact@example.com'
    assert stored.postal_code == '1000'
    assert stored.iban == 'BE97000000000099'
    assert is_organisation_complete(organisation=stored)


@pytest.mark.parametrize('field', list(OrganisationForm.model_fields))
def test_r15_4_every_organisation_detail_is_needed(session: Session, field: str) -> None:
    """The 281.27, Belcotax and the payment file need them all: an empty one is refused."""
    form = build_organisation_form()
    setattr(form, field, '  ')

    result = save_organisation(session=session, form=form)

    assert result.level == 'error'
    assert result.message == configuration.ORGANISATION_INCOMPLETE_MESSAGE
    assert session.scalar(sa.select(sa.func.count()).select_from(OrganisationConfig)) == 0


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('company_number', '123.456.789', configuration.INVALID_COMPANY_NUMBER_MESSAGE),
        ('postal_code', '100', configuration.INVALID_POSTAL_CODE_MESSAGE),
        ('postal_code', '0999', configuration.INVALID_POSTAL_CODE_MESSAGE),
        ('postal_code', 'B-1000', configuration.INVALID_POSTAL_CODE_MESSAGE),
        ('iban', 'BE97000000000098', configuration.INVALID_ORGANISATION_IBAN_MESSAGE),
    ],
)
def test_r15_4_organisation_details_the_exports_cannot_use_are_refused(
    session: Session,
    field: str,
    value: str,
    message: str,
) -> None:
    """Ten digits in the company number, a Belgian postal code, an IBAN with a right checksum."""
    form = build_organisation_form()
    setattr(form, field, value)

    result = save_organisation(session=session, form=form)

    assert result.level == 'error'
    assert result.message == message


def test_r15_4_company_number_is_read_as_ten_digits() -> None:
    """Belcotax wants the digits only."""
    assert read_company_number_digits(company_number='0123.456.789') == '0123456789'
