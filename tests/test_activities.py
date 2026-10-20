"""Counted activities, periods and a worker's month (R7.2, R7.12, R17.2)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from dimonapp.activities import (
    find_all_month_activities,
    find_month_activities,
    find_period,
    is_counted,
    sum_counted_activities,
)
from dimonapp.models import DimonaStatus, Period
from factories import build_activity, build_worker


@pytest.mark.parametrize(
    'dimona_status',
    [DimonaStatus.OK, DimonaStatus.PENDING, DimonaStatus.NOT_APPLICABLE],
)
def test_r17_2_activity_counts_unless_rejected(dimona_status: DimonaStatus) -> None:
    """Accepted, pending and Dimona-free activities all count."""
    activity = build_activity(dimona_status=dimona_status)

    assert is_counted(activity=activity)


def test_r17_2_rejected_activity_does_not_count() -> None:
    """A Dimona-rejected activity is left out of every total."""
    activity = build_activity(dimona_status=DimonaStatus.REJECTED)

    assert not is_counted(activity=activity)


def test_r17_2_cancelled_activity_does_not_count() -> None:
    """A cancelled activity is left out of every total."""
    activity = build_activity(is_cancelled=True)

    assert not is_counted(activity=activity)


@pytest.mark.parametrize(
    ('month', 'expected'),
    [
        (1, Period.Q1),
        (3, Period.Q1),
        (4, Period.Q2),
        (6, Period.Q2),
        (7, Period.Q3),
        (9, Period.Q3),
        (10, Period.Q4),
        (12, Period.Q4),
    ],
)
def test_period_is_the_quarter_of_the_month(month: int, expected: Period) -> None:
    """Each month falls in its calendar quarter."""
    assert find_period(activity_date=date(2026, month, 15)) is expected


def test_r7_12_totals_only_include_counted_activities() -> None:
    """Cancelled and Dimona-rejected activities are left out of the monthly totals."""
    activities = [
        build_activity(duration_hours=Decimal('2'), compensation_amount=Decimal('30')),
        build_activity(
            duration_hours=Decimal('2.5'),
            compensation_amount=Decimal('45'),
            dimona_status=DimonaStatus.PENDING,
        ),
        build_activity(duration_hours=Decimal('4'), is_cancelled=True),
        build_activity(duration_hours=Decimal('8'), dimona_status=DimonaStatus.REJECTED),
    ]

    totals = sum_counted_activities(activities=activities)

    assert totals.hours == Decimal('4.5')
    assert totals.amount == Decimal('75')


def test_r7_12_totals_of_an_empty_month_are_zero() -> None:
    """A month without activities totals zero hours and zero euro."""
    totals = sum_counted_activities(activities=[])

    assert totals.hours == Decimal('0')
    assert totals.amount == Decimal('0')


def test_r7_10_month_activities_are_those_of_the_month_oldest_first(session: Session) -> None:
    """The first and last day of the month belong to it; the days around it do not."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    days = [date(2026, 10, 31), date(2026, 9, 30), date(2026, 10, 1), date(2026, 11, 1)]
    for day in days:
        session.add(build_activity(worker_id=worker.id, activity_date=day))
    session.flush()

    activities = find_month_activities(
        session=session,
        worker_id=worker.id,
        month_start=date(2026, 10, 1),
    )

    assert [activity.activity_date for activity in activities] == [
        date(2026, 10, 1),
        date(2026, 10, 31),
    ]


def test_r7_2_month_activities_are_only_the_worker_s_own(session: Session) -> None:
    """Another worker's activities of the same month are never returned."""
    worker = build_worker()
    colleague = build_worker(username='colleague', national_register_number='90010112372')
    session.add_all([worker, colleague])
    session.flush()
    session.add(build_activity(worker_id=worker.id, activity_date=date(2026, 10, 5)))
    session.add(build_activity(worker_id=colleague.id, activity_date=date(2026, 10, 6)))
    session.flush()

    activities = find_month_activities(
        session=session,
        worker_id=worker.id,
        month_start=date(2026, 10, 1),
    )

    assert [activity.worker_id for activity in activities] == [worker.id]


def test_r19_1_all_month_activities_hold_every_worker_by_day_then_name(
    session: Session,
) -> None:
    """Every worker, cancelled and rejected included; other months left out."""
    zoe = build_worker(username='z', national_register_number='1', first_name='Zoé')
    alex = build_worker(username='a', national_register_number='2', first_name='Alex')
    session.add_all([zoe, alex])
    session.flush()
    activities = [
        build_activity(worker_id=zoe.id, activity_date=date(2026, 10, 7)),
        build_activity(worker_id=alex.id, activity_date=date(2026, 10, 7), is_cancelled=True),
        build_activity(
            worker_id=zoe.id,
            activity_date=date(2026, 10, 2),
            dimona_status=DimonaStatus.REJECTED,
        ),
        build_activity(worker_id=zoe.id, activity_date=date(2026, 9, 30)),
        build_activity(worker_id=zoe.id, activity_date=date(2026, 11, 1)),
    ]
    session.add_all(activities)
    session.flush()

    pairs = find_all_month_activities(session=session, month_start=date(2026, 10, 1))

    summary = [(activity.activity_date.day, worker.first_name) for activity, worker in pairs]
    assert summary == [(2, 'Zoé'), (7, 'Alex'), (7, 'Zoé')]
