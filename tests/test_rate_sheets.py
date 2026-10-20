"""The compensation sheet and its rate versions (R6.6, R6.7, FDS 7.4)."""

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp import rate_sheets
from dimonapp.compensation import find_rate
from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import RATE_CODES, Activity, ActivityType, CompensationModel
from dimonapp.rate_sheets import (
    build_sheet_rows,
    build_version_rows,
    find_worker_rates,
    format_rate,
    save_rate_version,
)
from factories import build_activity, build_rate, build_worker

TODAY = date(2026, 10, 10)


@pytest.fixture
def worker_id(session: Session) -> int:
    """Store a worker and give the id."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    return worker.id


def read_activity_types(session: Session) -> tuple[dict[str, str], dict[str, CompensationModel]]:
    """Read the labels and the compensation models of the seeded activity types and supplements."""
    activity_types = list(session.scalars(sa.select(ActivityType)))
    labels = {activity_type.code: activity_type.label for activity_type in activity_types}
    models = {
        activity_type.code: activity_type.compensation_model for activity_type in activity_types
    }
    return labels, models


def test_r6_6_sheet_shows_one_rate_per_activity_type_with_its_model(
    session: Session,
    worker_id: int,
) -> None:
    """Eleven rows in the FDS order; the model tells what the rate pays for (R6.2)."""
    for activity_type in RATE_CODES:
        rate = build_rate(
            valid_from=date(2026, 9, 1),
            amount=Decimal('20'),
            worker_id=worker_id,
            activity_type=activity_type,
        )
        session.add(rate)
    session.flush()
    labels, models = read_activity_types(session=session)

    rows = build_sheet_rows(
        rates=find_worker_rates(session=session, worker_id=worker_id),
        activity_labels=labels,
        compensation_models=models,
        today=TODAY,
    )

    assert [row["Type d'activité"] for row in rows] == [labels[code] for code in RATE_CODES]
    assert rows[0] == {
        "Type d'activité": 'Permanence',
        'Modèle': 'Prix fixe',
        'Tarif actuel': f'20,00{NO_BREAK_SPACE}€ / activité',
        'Valable depuis': '01/09/2026',
    }
    assert rows[1]['Modèle'] == 'Horaire'
    assert rows[1]['Tarif actuel'] == f'20,00{NO_BREAK_SPACE}€ / heure'


def test_r6_7_sheet_shows_the_rate_valid_today(session: Session, worker_id: int) -> None:
    """A version starting later is not the current rate yet, but is listed as a version."""
    session.add(build_rate(valid_from=date(2026, 9, 1), amount=Decimal('20'), worker_id=worker_id))
    session.add(build_rate(valid_from=date(2026, 11, 1), amount=Decimal('22'), worker_id=worker_id))
    session.flush()
    labels, models = read_activity_types(session=session)
    rates = find_worker_rates(session=session, worker_id=worker_id)

    sheet_rows = build_sheet_rows(
        rates=rates,
        activity_labels=labels,
        compensation_models=models,
        today=TODAY,
    )
    version_rows = build_version_rows(
        rates=rates,
        activity_labels=labels,
        compensation_models=models,
    )

    assert sheet_rows[1]['Tarif actuel'] == f'20,00{NO_BREAK_SPACE}€ / heure'
    assert sheet_rows[1]['Valable depuis'] == '01/09/2026'
    assert sheet_rows[0]['Tarif actuel'] == 'Aucun tarif'
    assert [row['Valable à partir du'] for row in version_rows] == ['01/11/2026', '01/09/2026']


def test_r6_7_new_version_applies_from_its_date_on(session: Session, worker_id: int) -> None:
    """The old rate stays for earlier dates; the new one is used from its start date."""
    session.add(build_rate(valid_from=date(2026, 9, 1), amount=Decimal('20'), worker_id=worker_id))
    session.flush()

    result = save_rate_version(
        session=session,
        worker_id=worker_id,
        activity_type='courses',
        amount=Decimal('22.5'),
        valid_from=date(2026, 11, 1),
    )

    rates = find_worker_rates(session=session, worker_id=worker_id)
    before = find_rate(rates=rates, activity_date=date(2026, 10, 31))
    after = find_rate(rates=rates, activity_date=date(2026, 11, 1))
    assert result.level == 'success'
    assert result.message == 'Tarif enregistré, valable à partir du 01/11/2026.'
    assert before.amount == Decimal('20.00')
    assert after.amount == Decimal('22.50')


def test_r6_7_declared_activity_keeps_its_amount(session: Session, worker_id: int) -> None:
    """A version covering the date of a declared activity does not recalculate it."""
    activity = build_activity(worker_id=worker_id, compensation_amount=Decimal('30'))
    session.add(activity)
    session.flush()
    activity_id = activity.id

    save_rate_version(
        session=session,
        worker_id=worker_id,
        activity_type='courses',
        amount=Decimal('99'),
        valid_from=date(2026, 1, 1),
    )

    session.expire_all()
    kept_activity = session.get(Activity, activity_id)
    assert kept_activity.compensation_amount == Decimal('30.00')
    assert kept_activity.rate_applied == Decimal('15.00')


def test_r6_7_version_on_the_same_date_is_corrected(session: Session, worker_id: int) -> None:
    """Saving twice for one date leaves one version, with the last amount."""
    for amount in (Decimal('220'), Decimal('22')):
        save_rate_version(
            session=session,
            worker_id=worker_id,
            activity_type='courses',
            amount=amount,
            valid_from=date(2026, 11, 1),
        )

    rates = find_worker_rates(session=session, worker_id=worker_id)
    assert [rate.amount for rate in rates] == [Decimal('22.00')]


@pytest.mark.parametrize(
    ('amount', 'valid_from', 'message'),
    [
        (None, date(2026, 11, 1), rate_sheets.MISSING_AMOUNT_MESSAGE),
        (Decimal('-1'), date(2026, 11, 1), rate_sheets.NEGATIVE_AMOUNT_MESSAGE),
        (Decimal('20'), None, rate_sheets.MISSING_VALID_FROM_MESSAGE),
    ],
)
def test_r6_7_incomplete_version_is_refused(
    session: Session,
    worker_id: int,
    amount: Optional[Decimal],
    valid_from: Optional[date],
    message: str,
) -> None:
    """A version needs an amount that is not negative and a start date."""
    result = save_rate_version(
        session=session,
        worker_id=worker_id,
        activity_type='courses',
        amount=amount,
        valid_from=valid_from,
    )

    assert result.level == 'error'
    assert result.message == message
    assert find_worker_rates(session=session, worker_id=worker_id) == []


def test_r6_2_rate_names_what_it_pays_for() -> None:
    """Per hour for hourly activities, per activity for fixed-price ones."""
    hourly = format_rate(amount=Decimal('20'), compensation_model=CompensationModel.HOURLY)
    fixed = format_rate(amount=Decimal('45'), compensation_model=CompensationModel.FIXED)

    assert hourly == f'20,00{NO_BREAK_SPACE}€ / heure'
    assert fixed == f'45,00{NO_BREAK_SPACE}€ / activité'


def test_r6_12_standard_rates_are_those_of_the_bmc_timesheet() -> None:
    """One standard rate per activity type and supplement, as in FDS 7.4."""
    assert rate_sheets.DEFAULT_RATES == {
        'permanence': Decimal('60'),
        'courses': Decimal('18'),
        'group_without_instructor': Decimal('20'),
        'group_with_instructor': Decimal('40'),
        'group_travel': Decimal('25'),
        'route_setting_easy': Decimal('50'),
        'route_setting_medium': Decimal('60'),
        'route_setting_hard': Decimal('70'),
        'rope_supplement': Decimal('10'),
        'route_cleaning_easy': Decimal('15'),
        'route_cleaning_hard': Decimal('25'),
    }
    assert list(rate_sheets.DEFAULT_RATES) == list(RATE_CODES)
