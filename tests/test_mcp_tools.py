"""The work behind the tools of /mcp, on rows built in memory (R20.14 to R20.19)."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

import pytest
from fastmcp.exceptions import ToolError

from dimonapp.clock import BELGIAN_TIME_ZONE
from dimonapp.mcp_models import Anomaly
from dimonapp.mcp_tools import (
    ActivityRow,
    ActivityTypeRow,
    LimitData,
    LimitRow,
    ThresholdRow,
    build_catalogue,
    check_period,
    find_month_period,
    find_period_anomalies,
    list_days,
    summarise_activities,
)
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    CompensationModel,
    DimonaStatus,
    Period,
    WorkerType,
)

LABELS = {
    'permanence': 'Permanence',
    'courses': 'Cours BMC',
    'route_setting_easy': 'Ouverture facile',
}
# Monday 5 October 2026 to Sunday 11 October 2026.
MONDAY = date(2026, 10, 5)
SUNDAY = date(2026, 10, 11)
TODAY = date(2026, 10, 31)
NO_LIMITS = LimitData(limits=[], configured_years={2026}, thresholds=[])


def build_row(
    activity_id: int = 1,
    worker_id: int = 1,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    activity_date: date = MONDAY,
    activity_type: str = 'courses',
    hours: str = '2',
    start_time: Optional[time] = None,
    dimona_status: DimonaStatus = DimonaStatus.OK,
    is_cancelled: bool = False,
    created_at: datetime = datetime(2026, 10, 1, 9, 0, tzinfo=BELGIAN_TIME_ZONE),
) -> ActivityRow:
    """Build one row of the activities view."""
    return ActivityRow(
        id=activity_id,
        worker_id=worker_id,
        worker_type=worker_type,
        activity_date=activity_date,
        activity_type=activity_type,
        duration_hours=Decimal(hours),
        start_time=start_time,
        dimona_status=dimona_status,
        is_cancelled=is_cancelled,
        created_at=created_at,
    )


def find_week_anomalies(
    activities: list[ActivityRow],
    start: date = MONDAY,
    end: date = SUNDAY,
    limit_data: LimitData = NO_LIMITS,
) -> list[Anomaly]:
    """Find the anomalies of a period, by default the week of Monday 5 October 2026."""
    anomalies = find_period_anomalies(
        activities=activities,
        labels=LABELS,
        limit_data=limit_data,
        start=start,
        end=end,
        today=TODAY,
    )
    return anomalies.anomalies


def test_r20_19_period_ending_before_its_start_is_refused() -> None:
    """The end date comes on or after the start date."""
    with pytest.raises(ToolError):
        check_period(start=date(2026, 10, 2), end=date(2026, 10, 1))


def test_r20_19_period_of_at_most_366_days_is_accepted() -> None:
    """A leap year, both days included, is the longest period."""
    check_period(start=date(2028, 1, 1), end=date(2028, 12, 31))


def test_r20_19_period_longer_than_366_days_is_refused() -> None:
    """One day more is refused with a clear message."""
    with pytest.raises(ToolError):
        check_period(start=date(2028, 1, 1), end=date(2029, 1, 1))


def test_r20_17_month_period_runs_from_its_first_to_its_last_day() -> None:
    """February of a leap year has 29 days."""
    assert find_month_period(year=2028, month=2) == (date(2028, 2, 1), date(2028, 2, 29))


def test_r20_14_summary_sums_counted_activities_per_type() -> None:
    """Hours and counts per activity type and worker type, only for counted activities."""
    activities = [
        build_row(activity_id=1, worker_id=1, hours='2'),
        build_row(activity_id=2, worker_id=2, hours='1.5', activity_type='permanence'),
        build_row(
            activity_id=3,
            worker_id=3,
            worker_type=WorkerType.VRIJWILLIGER,
            hours='3',
            dimona_status=DimonaStatus.NOT_APPLICABLE,
        ),
        build_row(activity_id=4, worker_id=1, hours='2', dimona_status=DimonaStatus.PENDING),
        build_row(activity_id=5, worker_id=4, hours='9', dimona_status=DimonaStatus.REJECTED),
        build_row(activity_id=6, worker_id=4, hours='9', is_cancelled=True),
    ]

    summary = summarise_activities(activities=activities, labels=LABELS, start=MONDAY, end=SUNDAY)

    assert summary.hours == 8.5
    assert summary.n_activities == 4
    assert summary.n_workers == 3
    assert [(total.activity_type, total.hours) for total in summary.activity_types] == [
        ('permanence', 1.5),
        ('courses', 7.0),
    ]
    assert summary.activity_types[1].label == 'Cours BMC'
    assert [(total.worker_type, total.n_activities) for total in summary.worker_types] == [
        (WorkerType.VRIJWILLIGER, 1),
        (WorkerType.ARTICLE_17, 3),
    ]
    assert (summary.n_cancelled, summary.n_rejected, summary.n_pending) == (1, 1, 1)


def test_r20_14_summary_keeps_to_the_period() -> None:
    """An activity the day after the period is left out."""
    activities = [
        build_row(activity_id=1, activity_date=SUNDAY),
        build_row(activity_id=2, activity_date=date(2026, 10, 12)),
    ]

    summary = summarise_activities(activities=activities, labels=LABELS, start=MONDAY, end=SUNDAY)

    assert summary.n_activities == 1


def test_r20_15_every_day_is_listed_with_its_weekday() -> None:
    """Days without an activity are listed too, with an empty list."""
    activities = [build_row(activity_id=1, activity_date=date(2026, 10, 7))]

    daily_activities = list_days(activities=activities, labels=LABELS, start=MONDAY, end=SUNDAY)

    days = daily_activities.days
    assert [day.day for day in days][0] == MONDAY
    assert len(days) == 7
    assert [day.weekday for day in days][:3] == ['Monday', 'Tuesday', 'Wednesday']
    assert [len(day.activities) for day in days] == [0, 0, 1, 0, 0, 0, 0]


def test_r20_15_day_lists_counted_activities_only() -> None:
    """A cancelled or rejected activity is not on the list of its day; a pending one is."""
    activities = [
        build_row(activity_id=1, dimona_status=DimonaStatus.PENDING),
        build_row(activity_id=2, dimona_status=DimonaStatus.REJECTED),
        build_row(activity_id=3, is_cancelled=True),
    ]

    daily_activities = list_days(activities=activities, labels=LABELS, start=MONDAY, end=MONDAY)

    day_activities = daily_activities.days[0].activities
    assert [activity.activity_id for activity in day_activities] == [1]
    assert day_activities[0].dimona_status == DimonaStatus.PENDING


def test_r20_15_start_time_is_given_for_a_flexi_job_only() -> None:
    """The start time of a flexi-job activity is listed, with its worker type and hours."""
    activities = [
        build_row(
            activity_id=1,
            worker_type=WorkerType.FLEXI_JOB,
            hours='3.25',
            start_time=time(18, 30),
        ),
        build_row(activity_id=2),
    ]

    daily_activities = list_days(activities=activities, labels=LABELS, start=MONDAY, end=MONDAY)

    flexi_job, article_17 = daily_activities.days[0].activities
    assert flexi_job.start_time == time(18, 30)
    assert flexi_job.hours == 3.25
    assert flexi_job.worker_type == WorkerType.FLEXI_JOB
    assert article_17.start_time is None


def test_r20_16_status_anomalies_give_ids_dates_and_days_pending() -> None:
    """Pending with its age in days, then rejected, then cancelled."""
    activities = [
        build_row(activity_id=1, is_cancelled=True),
        build_row(activity_id=2, dimona_status=DimonaStatus.REJECTED),
        build_row(
            activity_id=3,
            dimona_status=DimonaStatus.PENDING,
            created_at=datetime(2026, 10, 28, 23, 30, tzinfo=BELGIAN_TIME_ZONE),
        ),
    ]

    anomalies = find_week_anomalies(activities=activities)

    assert [(anomaly.kind, anomaly.activity_id) for anomaly in anomalies] == [
        ('pending_dimona', 3),
        ('rejected_dimona', 2),
        ('cancelled_activity', 1),
    ]
    assert anomalies[0].days_pending == 3
    assert anomalies[0].activity_date == MONDAY
    assert 'RSZ' in anomalies[0].explanation


def test_r20_16_activity_of_more_than_5_hours_is_long() -> None:
    """More than 5 hours, whatever the activity type; exactly 5 hours is not."""
    activities = [
        build_row(activity_id=1, worker_id=1, hours='5.5', activity_type='permanence'),
        build_row(activity_id=2, worker_id=2, hours='5', activity_type='route_setting_easy'),
        build_row(activity_id=3, worker_id=3, hours='6', is_cancelled=True),
    ]

    anomalies = find_week_anomalies(activities=activities)

    long_activities = [anomaly for anomaly in anomalies if anomaly.kind == 'long_activity']
    assert [anomaly.activity_id for anomaly in long_activities] == [1]
    assert long_activities[0].hours == 5.5
    assert long_activities[0].label == 'Permanence'


def test_r20_16_day_of_more_than_8_hours_for_one_worker_is_long() -> None:
    """Two activities of one worker add up; the same hours spread over two workers do not."""
    activities = [
        build_row(activity_id=1, worker_id=1, hours='4.5'),
        build_row(activity_id=2, worker_id=1, hours='4', activity_type='permanence'),
        build_row(activity_id=3, worker_id=2, hours='4.5'),
        build_row(activity_id=4, worker_id=3, hours='4.5'),
    ]

    anomalies = find_week_anomalies(activities=activities)

    long_days = [anomaly for anomaly in anomalies if anomaly.kind == 'long_day']
    assert len(long_days) == 1
    assert long_days[0].activity_ids == [1, 2]
    assert long_days[0].hours == 8.5
    assert long_days[0].activity_date == MONDAY
    assert 'worker_id' not in long_days[0].model_dump()


def test_r20_16_more_than_2_days_in_a_week_for_one_worker() -> None:
    """The whole week counts, also its days outside the period; 2 days are not an anomaly."""
    activities = [
        build_row(activity_id=1, worker_id=1, activity_date=MONDAY),
        build_row(activity_id=2, worker_id=1, activity_date=date(2026, 10, 7)),
        build_row(activity_id=3, worker_id=1, activity_date=date(2026, 10, 7)),
        build_row(activity_id=4, worker_id=1, activity_date=SUNDAY),
        build_row(activity_id=5, worker_id=2, activity_date=MONDAY),
        build_row(activity_id=6, worker_id=2, activity_date=SUNDAY),
    ]

    anomalies = find_week_anomalies(
        activities=activities,
        start=date(2026, 10, 7),
        end=date(2026, 10, 8),
    )

    busy_weeks = [anomaly for anomaly in anomalies if anomaly.kind == 'many_days_in_week']
    assert len(busy_weeks) == 1
    assert (busy_weeks[0].week_start, busy_weeks[0].week_end) == (MONDAY, SUNDAY)
    assert busy_weeks[0].n_days == 3
    assert busy_weeks[0].dates == [MONDAY, date(2026, 10, 7), SUNDAY]
    assert busy_weeks[0].activity_ids == [1, 2, 3, 4]


def test_r20_16_flexi_job_under_the_minimum_of_its_year() -> None:
    """A flexi-job below the minimum hours is flagged; a year without minimum is not checked."""
    limits = [
        LimitRow(
            year=2026,
            worker_type=WorkerType.FLEXI_JOB,
            period=Period.YEAR,
            hours_limit=None,
            min_hours_per_activity=Decimal('3'),
            has_euro_limit=True,
        ),
    ]
    limit_data = LimitData(limits=limits, configured_years={2026}, thresholds=[])
    flexi_job = WorkerType.FLEXI_JOB
    activities = [
        build_row(activity_id=1, worker_type=flexi_job, hours='2.5'),
        build_row(activity_id=2, worker_type=flexi_job, hours='3'),
        build_row(activity_id=3, hours='1'),
    ]

    anomalies = find_week_anomalies(activities=activities, limit_data=limit_data)

    short_flexi_jobs = [
        anomaly for anomaly in anomalies if anomaly.kind == 'flexi_job_under_minimum'
    ]
    assert [anomaly.activity_id for anomaly in short_flexi_jobs] == [1]
    assert (short_flexi_jobs[0].hours, short_flexi_jobs[0].min_hours) == (2.5, 3.0)


def test_r20_16_year_without_complete_limits() -> None:
    """A year of the period with counted activities but no complete limits needs a look."""
    limit_data = LimitData(limits=[], configured_years=set(), thresholds=[])
    activities = [build_row(activity_id=1), build_row(activity_id=2, is_cancelled=True)]

    anomalies = find_week_anomalies(activities=activities, limit_data=limit_data)

    years = [anomaly for anomaly in anomalies if anomaly.kind == 'year_without_limits']
    assert [(anomaly.year, anomaly.n_activities) for anomaly in years] == [(2026, 1)]


def test_r20_16_limits_at_the_threshold_give_counts_only() -> None:
    """A limit with workers at 90 % is listed with its count; a limit without any is not."""
    thresholds = [
        ThresholdRow(
            year=2026,
            period=Period.Q4,
            worker_type=WorkerType.ARTICLE_17,
            kind='hours',
            hours_limit=Decimal('150'),
            n_workers=2,
        ),
        ThresholdRow(
            year=2026,
            period=Period.YEAR,
            worker_type=WorkerType.VRIJWILLIGER,
            kind='euro',
            hours_limit=None,
            n_workers=1,
        ),
        ThresholdRow(
            year=2026,
            period=Period.YEAR,
            worker_type=WorkerType.FLEXI_JOB,
            kind='euro',
            hours_limit=None,
            n_workers=0,
        ),
    ]
    limit_data = LimitData(limits=[], configured_years={2026}, thresholds=thresholds)

    anomalies = find_week_anomalies(activities=[], limit_data=limit_data)

    assert [(anomaly.kind, anomaly.n_workers) for anomaly in anomalies] == [
        ('limit_at_threshold', 2),
        ('limit_at_threshold', 1),
    ]
    assert anomalies[0].hours_limit == 150.0
    assert anomalies[1].hours_limit is None


def test_r20_16_nothing_unusual_gives_no_anomaly() -> None:
    """A short, accepted activity in a configured year needs no look."""
    anomalies = find_week_anomalies(activities=[build_row(activity_id=1)])

    assert anomalies == []


def test_r20_18_catalogue_lists_the_nine_activity_types_with_their_supplement() -> None:
    """In the order of FDS 5.2, with the supplement label, and without the supplements."""
    hourly = CompensationModel.HOURLY
    activity_types = [
        ActivityTypeRow(
            code=code,
            label=f'Label {code}',
            compensation_model=hourly,
            description_required=False,
            supplement='group_travel' if code == 'group_with_instructor' else None,
        )
        for code in ACTIVITY_TYPE_CODES
    ]
    supplement = ActivityTypeRow(
        code='group_travel',
        label='Déplacement groupe',
        compensation_model=CompensationModel.FIXED,
        description_required=False,
        supplement=None,
    )

    catalogue = build_catalogue(activity_types=[supplement, *activity_types])

    entries = catalogue.activity_types
    assert [entry.code for entry in entries] == list(ACTIVITY_TYPE_CODES)
    group_with_instructor = entries[3]
    assert group_with_instructor.supplement == 'group_travel'
    assert group_with_instructor.supplement_label == 'Déplacement groupe'
