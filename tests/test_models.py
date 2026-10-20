"""Schema, seed and constraints against the migrated PostgreSQL (R1.9, R1.10, R3.5, R4.1, R6)."""

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.orm import Session

from dimonapp.compensation import find_rate
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    RATE_CODES,
    SUPPLEMENT_CODES,
    Activity,
    ActivityType,
    Authorisation,
    Base,
    CompensationModel,
    CompensationRate,
    DocumentType,
    Worker,
    WorkerType,
)
from factories import (
    FAKE_IBAN,
    VALID_NATIONAL_REGISTER_NUMBER,
    build_activity,
    build_authorisation,
    build_limit,
    build_rate,
    build_worker,
)

EXPECTED_ACTIVITY_TYPES = {
    'permanence': ('Permanence', CompensationModel.FIXED, False),
    'courses': ('Cours BMC', CompensationModel.HOURLY, False),
    'group_without_instructor': ('Cours groupe sans mono', CompensationModel.HOURLY, False),
    'group_with_instructor': ('Cours groupe avec mono', CompensationModel.HOURLY, False),
    'route_setting_easy': ('Ouverture 4A - 5C', CompensationModel.FIXED, True),
    'route_setting_medium': ('Ouverture 6A - 6C', CompensationModel.FIXED, True),
    'route_setting_hard': ('Ouverture 7A et plus', CompensationModel.FIXED, True),
    'route_cleaning_easy': ('Démontage facile', CompensationModel.FIXED, False),
    'route_cleaning_hard': ('Démontage difficile (cordes 9 à 14)', CompensationModel.FIXED, False),
}
EXPECTED_SUPPLEMENTS = {
    'group_travel': ('Déplacement groupe', CompensationModel.FIXED, False),
    'rope_supplement': ('Supplément corde 9 à 14', CompensationModel.FIXED, False),
}


def save_worker(session: Session, username: str = 'worker') -> Worker:
    """Store a fake worker and give it back with its identifier."""
    worker = build_worker(username=username)
    session.add(worker)
    session.flush()
    return worker


def test_r1_10_migrated_schema_matches_the_models(migrated_engine: sa.Engine) -> None:
    """The committed migration creates exactly what the ORM models describe."""
    with migrated_engine.connect() as connection:
        migration_context = MigrationContext.configure(connection=connection)
        differences = compare_metadata(context=migration_context, metadata=Base.metadata)

    assert differences == []


def test_r4_1_workers_and_admins_are_separate_tables(migrated_engine: sa.Engine) -> None:
    """The ten tables of FDS section 11 exist, with workers and admins apart."""
    with migrated_engine.connect() as connection:
        table_names = set(sa.inspect(connection).get_table_names())

    expected_table_names = {
        'workers',
        'admins',
        'activity_types',
        'compensation_rates',
        'activities',
        'yearly_limits',
        'authorisations',
        'organisation_config',
        'sign_in_failures',
        'last_actions',
    }
    assert expected_table_names <= table_names
    assert set(Base.metadata.tables) == expected_table_names


def test_r6_1_nine_activity_types_and_two_supplements_are_seeded(session: Session) -> None:
    """The seeded rows carry the FDS labels, models and description flags (R6.3, R6.8, R6.9)."""
    activity_types = session.scalars(sa.select(ActivityType)).all()

    seeded = {
        activity_type.code: (
            activity_type.label,
            activity_type.compensation_model,
            activity_type.description_required,
        )
        for activity_type in activity_types
    }
    assert seeded == {**EXPECTED_ACTIVITY_TYPES, **EXPECTED_SUPPLEMENTS}
    assert set(ACTIVITY_TYPE_CODES) == set(EXPECTED_ACTIVITY_TYPES)
    assert set(SUPPLEMENT_CODES) == set(EXPECTED_SUPPLEMENTS)
    assert sorted(RATE_CODES) == sorted([*ACTIVITY_TYPE_CODES, *SUPPLEMENT_CODES])


def test_r6_9_each_supplement_is_offered_on_its_activity_types(session: Session) -> None:
    """Group travel on the two group courses, the rope supplement on the three route settings."""
    statement = sa.select(ActivityType).where(ActivityType.supplement.is_not(None))
    supplements = {
        activity_type.code: activity_type.supplement for activity_type in session.scalars(statement)
    }

    assert supplements == {
        'group_without_instructor': 'group_travel',
        'group_with_instructor': 'group_travel',
        'route_setting_easy': 'rope_supplement',
        'route_setting_medium': 'rope_supplement',
        'route_setting_hard': 'rope_supplement',
    }


def test_r6_3_only_the_three_course_types_are_hourly(session: Session) -> None:
    """Three hourly activity types; the six others and the supplements are fixed price (R6.2)."""
    statement = sa.select(ActivityType.code).where(
        ActivityType.compensation_model == CompensationModel.HOURLY
    )
    hourly_codes = set(session.scalars(statement).all())

    assert hourly_codes == {'courses', 'group_without_instructor', 'group_with_instructor'}


def test_r1_9_records_round_trip_with_exact_decimals_and_arrays(session: Session) -> None:
    """Amounts come back as exact decimals and covered activities as a list."""
    worker = save_worker(session=session)
    worker_id = worker.id
    rate = build_rate(worker_id=worker_id, valid_from=date(2026, 1, 1), amount=Decimal('15.33'))
    authorisation = build_authorisation(
        worker_id=worker_id, activity_types=('courses', 'permanence')
    )
    session.add_all([rate, authorisation])
    session.flush()
    session.expire_all()

    stored_rate = session.scalars(sa.select(CompensationRate)).one()
    stored_authorisation = session.scalars(sa.select(Authorisation)).one()
    stored_worker = session.get(Worker, worker_id)

    assert stored_rate.amount == Decimal('15.33')
    assert stored_authorisation.activity_types == ['courses', 'permanence']
    assert stored_authorisation.uploaded_at is not None
    assert stored_worker.is_active is True


def test_r6_6_one_rate_per_activity_type_and_start_date(session: Session) -> None:
    """Two versions of the same rate cannot start on the same day."""
    worker = save_worker(session=session)
    worker_id = worker.id
    first = build_rate(worker_id=worker_id, valid_from=date(2026, 1, 1))
    duplicate = build_rate(worker_id=worker_id, valid_from=date(2026, 1, 1))
    session.add_all([first, duplicate])

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_duplicate_national_register_number_is_refused(session: Session) -> None:
    """A national register number belongs to one worker."""
    save_worker(session=session, username='first')
    session.add(build_worker(username='second'))

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_duplicate_username_is_refused(session: Session) -> None:
    """A username belongs to one worker."""
    save_worker(session=session)
    session.add(build_worker(national_register_number='01032030341'))

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


@pytest.mark.parametrize('field', ['email', 'street', 'postal_code', 'city'])
def test_r11_2_worker_without_email_or_address_is_refused(session: Session, field: str) -> None:
    """The e-mail and the postal address are required in the database too (FDS 11.1)."""
    worker = build_worker()
    setattr(worker, field, None)
    session.add(worker)

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_duplicate_email_is_refused(session: Session) -> None:
    """An e-mail address belongs to one worker (FDS 11.1)."""
    first_number = '90011510185'
    second_number = '95060220229'
    session.add(build_worker(username='a', national_register_number=first_number, email='x@y.be'))
    session.add(build_worker(username='b', national_register_number=second_number, email='x@y.be'))
    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_duplicate_limit_for_the_same_year_type_and_period_is_refused(session: Session) -> None:
    """One limit row per year, worker type and period."""
    session.add_all([build_limit(), build_limit()])

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_authorisation_without_covered_activity_is_refused(session: Session) -> None:
    """A document covers one or more activity types (R12.4)."""
    worker = save_worker(session=session)
    session.add(build_authorisation(worker_id=worker.id, activity_types=()))

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_r17_3_activity_keeps_its_amount_when_a_newer_rate_is_added(session: Session) -> None:
    """The rate, model and amount are copies; a later rate version changes nothing (R6.7)."""
    worker = save_worker(session=session)
    worker_id = worker.id
    old_rate = build_rate(worker_id=worker_id, valid_from=date(2026, 1, 1), amount=Decimal('15'))
    activity = build_activity(worker_id=worker_id, activity_date=date(2026, 5, 10))
    session.add_all([old_rate, activity])
    session.flush()

    new_rate = build_rate(worker_id=worker_id, valid_from=date(2026, 5, 1), amount=Decimal('20'))
    session.add(new_rate)
    session.flush()
    session.expire_all()

    stored_activity = session.scalars(sa.select(Activity)).one()
    rates = list(session.scalars(sa.select(CompensationRate)).all())
    rate_for_a_new_activity = find_rate(rates=rates, activity_date=date(2026, 5, 10))
    assert rate_for_a_new_activity.amount == Decimal('20.00')
    assert stored_activity.worker_type == worker.worker_type
    assert stored_activity.compensation_model == CompensationModel.HOURLY
    assert stored_activity.rate_applied == Decimal('15.00')
    assert stored_activity.compensation_amount == Decimal('30.00')


def test_r3_5_national_number_and_iban_exist_only_in_workers() -> None:
    """No other table has a column for a national register number or a person's IBAN.

    The one IBAN outside workers is BMC's own account in organisation_config (R15.4): the
    account of the association, not personal data.
    """
    columns_with_personal_data = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            column_name = column.name
            if 'national' in column_name or 'iban' in column_name:
                columns_with_personal_data.add(f'{table.name}.{column_name}')

    assert columns_with_personal_data == {
        'workers.national_register_number',
        'workers.iban',
        'organisation_config.iban',
    }


def test_r3_5_worker_representation_hides_personal_data() -> None:
    """A worker that ends up in a log message shows neither national number nor IBAN."""
    worker = build_worker(worker_id=1)

    text = f'{worker!r} {worker}'

    assert VALID_NATIONAL_REGISTER_NUMBER not in text
    assert FAKE_IBAN not in text


@pytest.mark.parametrize(
    ('document_type', 'worker_type'),
    [
        (DocumentType.CONTRACT, None),
        (DocumentType.QUALIFICATION, WorkerType.ARTICLE_17),
    ],
)
def test_r12_10_only_a_contract_has_a_worker_type(
    session: Session,
    document_type: DocumentType,
    worker_type: Optional[WorkerType],
) -> None:
    """The database refuses a contract without worker type and a qualification with one."""
    worker = save_worker(session=session)
    authorisation = build_authorisation(worker_id=worker.id)
    authorisation.document_type = document_type
    authorisation.worker_type = worker_type
    session.add(authorisation)

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()
