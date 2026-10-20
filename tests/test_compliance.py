"""Compliance engine (R5.5, R5.6, R15.2, R15.3, R16.1 to R16.5)."""

from datetime import date
from decimal import Decimal

import pytest

from dimonapp.compliance import LimitFlag, find_limit_flags, find_years_without_limits
from dimonapp.models import Activity, DimonaStatus, Period, WorkerType, YearlyLimit
from factories import build_activity, build_complete_limits, build_limit, build_worker


def build_hours_limits(hours_limit: Decimal, period: Period = Period.YEAR) -> list[YearlyLimit]:
    """Build a configured 2026 with one article 17 hours limit of interest."""
    limits = build_complete_limits(year=2026)
    for limit in limits:
        if limit.worker_type == WorkerType.ARTICLE_17 and limit.period == period:
            limit.hours_limit = hours_limit
    return limits


def find_flags_of_one_worker(
    activities: list[Activity],
    limits: list[YearlyLimit],
    worker_type: WorkerType = WorkerType.ARTICLE_17,
) -> list[LimitFlag]:
    """Run the engine for worker 1."""
    worker = build_worker(worker_id=1, worker_type=worker_type)
    return find_limit_flags(workers=[worker], activities=activities, limits=limits)


@pytest.mark.parametrize(
    ('duration_hours', 'is_flagged'),
    [(Decimal('89'), False), (Decimal('90'), True), (Decimal('120'), True)],
)
def test_r16_2_flag_from_90_percent_of_the_limit(duration_hours: Decimal, is_flagged: bool) -> None:
    """Below 90% nothing is flagged; at 90% and above 100% the worker is flagged."""
    activities = [build_activity(duration_hours=duration_hours)]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert bool(flags) is is_flagged


def test_r16_2_flag_describes_the_worker_period_and_totals() -> None:
    """A flag names the worker, the status, the period, the total and the limit."""
    activities = [build_activity(duration_hours=Decimal('95'))]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    expected = LimitFlag(
        worker_id=1,
        worker_type=WorkerType.ARTICLE_17,
        year=2026,
        period=Period.YEAR,
        quantity='hours',
        total=Decimal('95'),
        limit=Decimal('100'),
    )
    assert flags == [expected]


def test_r16_2_hours_and_euro_are_flagged_separately() -> None:
    """One limit row can raise an hours flag and a euro flag."""
    activities = [build_activity(duration_hours=Decimal('95'), compensation_amount=Decimal('950'))]
    limits = build_complete_limits(year=2026)
    limits[1].hours_limit = Decimal('100')
    limits[1].euro_limit = Decimal('1000')

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    quantities = [flag.quantity for flag in flags]
    assert quantities == ['hours', 'euro']


def test_r16_1_totals_are_summed_per_quarter() -> None:
    """A quarter limit only sees the activities of its three months."""
    activities = [
        build_activity(activity_date=date(2026, 3, 31), duration_hours=Decimal('50')),
        build_activity(activity_date=date(2026, 4, 1), duration_hours=Decimal('50')),
        build_activity(activity_date=date(2026, 6, 30), duration_hours=Decimal('45')),
    ]
    limits = build_hours_limits(hours_limit=Decimal('100'), period=Period.Q2)

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert [(flag.period, flag.total) for flag in flags] == [(Period.Q2, Decimal('95'))]


def test_r16_1_year_total_sums_all_quarters() -> None:
    """The YEAR period adds up the whole calendar year."""
    activities = [
        build_activity(activity_date=date(2026, 1, 5), duration_hours=Decimal('50')),
        build_activity(activity_date=date(2026, 12, 20), duration_hours=Decimal('45')),
    ]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert [flag.total for flag in flags] == [Decimal('95')]


def test_r16_1_planned_future_activity_counts() -> None:
    """The engine has no notion of today: an activity far in the future is summed too."""
    activities = [build_activity(activity_date=date(2031, 12, 31), duration_hours=Decimal('95'))]
    limits = build_complete_limits(year=2031)
    limits[1].hours_limit = Decimal('100')

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert len(flags) == 1


def test_r17_2_cancelled_and_rejected_activities_are_not_summed() -> None:
    """Only counted activities reach the totals."""
    activities = [
        build_activity(duration_hours=Decimal('60')),
        build_activity(duration_hours=Decimal('60'), is_cancelled=True),
        build_activity(duration_hours=Decimal('60'), dimona_status=DimonaStatus.REJECTED),
    ]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert flags == []


def test_r5_5_activities_under_a_former_status_are_left_out() -> None:
    """After a status change the worker starts from zero for the new status."""
    activities = [
        build_activity(worker_type=WorkerType.VRIJWILLIGER, duration_hours=Decimal('95')),
        build_activity(worker_type=WorkerType.ARTICLE_17, duration_hours=Decimal('10')),
    ]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert flags == []


def test_r16_1_activities_of_another_worker_are_left_out() -> None:
    """Totals are per worker."""
    activities = [build_activity(worker_id=2, duration_hours=Decimal('95'))]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert flags == []


def test_r15_3_each_year_is_checked_against_its_own_limits() -> None:
    """There is no active year: 2026 and 2027 activities meet the 2026 and 2027 limits."""
    activities = [
        build_activity(activity_date=date(2026, 5, 1), duration_hours=Decimal('95')),
        build_activity(activity_date=date(2027, 5, 1), duration_hours=Decimal('95')),
    ]
    limits_2026 = build_complete_limits(year=2026)
    limits_2026[1].hours_limit = Decimal('100')
    limits_2027 = build_complete_limits(year=2027)
    limits_2027[1].hours_limit = Decimal('200')

    flags = find_flags_of_one_worker(activities=activities, limits=[*limits_2026, *limits_2027])

    assert [flag.year for flag in flags] == [2026]


def test_r15_2_limits_come_only_from_the_given_rows() -> None:
    """An empty limit means no limit: volunteers have no hours cap, however many hours."""
    volunteer = WorkerType.VRIJWILLIGER
    activities = [build_activity(worker_type=volunteer, duration_hours=Decimal('9999'))]
    limits = build_complete_limits(year=2026)

    flags = find_flags_of_one_worker(activities=activities, limits=limits, worker_type=volunteer)

    assert flags == []


@pytest.mark.parametrize('with_limit_row', [False, True])
def test_r16_5_freelancers_are_never_flagged(with_limit_row: bool) -> None:
    """A freelancer raises no flag, even when someone entered a limit row for freelancers."""
    activities = [build_activity(worker_type=WorkerType.FREELANCER, duration_hours=Decimal('500'))]
    limits = build_complete_limits(year=2026)
    if with_limit_row:
        freelancer_limit = build_limit(worker_type=WorkerType.FREELANCER, hours_limit=Decimal('1'))
        limits.append(freelancer_limit)

    flags = find_flags_of_one_worker(
        activities=activities,
        limits=limits,
        worker_type=WorkerType.FREELANCER,
    )

    assert flags == []


def test_r16_3_exceeding_a_limit_returns_flags_and_blocks_nothing() -> None:
    """Far above the limit the engine still just reports."""
    activities = [build_activity(duration_hours=Decimal('500'))]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)

    assert len(flags) == 1


def test_r16_4_year_without_limits_is_reported_and_not_flagged() -> None:
    """A 2027 activity gets the missing limits warning, not the 2026 values."""
    activities = [build_activity(activity_date=date(2027, 5, 1), duration_hours=Decimal('500'))]
    limits = build_hours_limits(hours_limit=Decimal('100'))

    flags = find_flags_of_one_worker(activities=activities, limits=limits)
    missing_years = find_years_without_limits(activities=activities, limits=limits)

    assert flags == []
    assert missing_years == [2027]


def test_r16_4_year_with_limits_for_only_some_worker_types_is_not_configured() -> None:
    """If a worker type has no limits at all, the whole year is missing and raises no flag."""
    activities = [build_activity(duration_hours=Decimal('500'))]
    limits = [build_limit(worker_type=WorkerType.ARTICLE_17, hours_limit=Decimal('100'))]

    flags = find_flags_of_one_worker(activities=activities, limits=limits)
    missing_years = find_years_without_limits(activities=activities, limits=limits)

    assert flags == []
    assert missing_years == [2026]


@pytest.mark.parametrize(
    ('row_index', 'field'),
    [
        (0, 'euro_limit'),
        (1, 'hours_limit'),
        (1, 'euro_limit'),
        (2, 'euro_limit'),
        (2, 'min_hours_per_activity'),
        (3, 'hours_limit'),
        (6, 'hours_limit'),
    ],
)
def test_r16_4_one_empty_required_limit_makes_the_whole_year_not_configured(
    row_index: int,
    field: str,
) -> None:
    """Everything must be filled in: a single empty required value breaks the year."""
    activities = [build_activity(duration_hours=Decimal('500'))]
    limits = build_hours_limits(hours_limit=Decimal('100'), period=Period.Q2)
    setattr(limits[row_index], field, None)

    flags = find_flags_of_one_worker(activities=activities, limits=limits)
    missing_years = find_years_without_limits(activities=activities, limits=limits)

    assert flags == []
    assert missing_years == [2026]


def test_r16_4_one_missing_quarter_row_makes_the_whole_year_not_configured() -> None:
    """A year without the row of one article 17 quarter is not configured."""
    activities = [build_activity()]
    limits = build_complete_limits(year=2026)[:-1]

    assert find_years_without_limits(activities=activities, limits=limits) == [2026]


def test_r16_4_configured_year_is_not_reported() -> None:
    """A year with every required limit filled in raises no warning."""
    activities = [build_activity()]
    limits = build_complete_limits(year=2026)

    assert find_years_without_limits(activities=activities, limits=limits) == []


def test_r16_4_year_without_counted_activity_is_not_reported() -> None:
    """Cancelled activities alone do not ask for limits."""
    activities = [build_activity(activity_date=date(2027, 5, 1), is_cancelled=True)]

    assert find_years_without_limits(activities=activities, limits=[]) == []
