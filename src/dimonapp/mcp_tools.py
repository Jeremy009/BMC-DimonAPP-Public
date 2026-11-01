"""The work behind the tools of /mcp: read the views, then sum and check (FDS section 15.5).

Reading goes through the views of migration 0003 only (R20.10). The rest are plain functions
over the rows read, so they can be tested without an MCP client. The worker id of a row is
only used to group activities by worker; no output model has a field for it (R20.2).
"""

import calendar
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from dimonapp.clock import BELGIAN_TIME_ZONE
from dimonapp.mcp_models import (
    LONG_ACTIVITY_HOURS,
    LONG_DAY_HOURS,
    MAX_DAYS_PER_WEEK,
    ActivityTypeCatalogue,
    ActivityTypeEntry,
    ActivityTypeTotal,
    Anomalies,
    Anomaly,
    BusyWeek,
    CancelledActivity,
    DailyActivities,
    Day,
    DayActivity,
    LimitAtThreshold,
    LimitKind,
    LongActivity,
    LongDay,
    MonthReview,
    PendingDimona,
    PeriodSummary,
    RejectedDimona,
    ShortFlexiJob,
    WorkerTypeTotal,
    YearWithoutLimits,
)
from dimonapp.mcp_views import (
    activities_view,
    activity_types_view,
    configured_years_view,
    limit_thresholds_view,
    yearly_limits_view,
)
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    CompensationModel,
    DimonaStatus,
    Period,
    WorkerType,
)

# The longest period a tool accepts, both days included (R20.19).
MAX_PERIOD_DAYS = 366
# English weekday names, whatever the locale of the server.
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


class ActivityRow(BaseModel):
    """One row of the activities view."""

    id: int
    worker_id: int
    worker_type: WorkerType
    activity_date: date
    activity_type: str
    duration_hours: Decimal
    start_time: Optional[time]
    dimona_status: DimonaStatus
    is_cancelled: bool
    created_at: datetime


class ActivityTypeRow(BaseModel):
    """One row of the activity types view."""

    code: str
    label: str
    compensation_model: CompensationModel
    description_required: bool
    supplement: Optional[str]


class LimitRow(BaseModel):
    """One row of the yearly limits view: the hours values only."""

    year: int
    worker_type: WorkerType
    period: Period
    hours_limit: Optional[Decimal]
    min_hours_per_activity: Optional[Decimal]
    has_euro_limit: bool


class ThresholdRow(BaseModel):
    """One row of the limit thresholds view."""

    year: int
    period: Period
    worker_type: WorkerType
    kind: LimitKind
    hours_limit: Optional[Decimal]
    n_workers: int


class LimitData(BaseModel):
    """What find_anomalies needs to know of the limits of the years of a period."""

    limits: list[LimitRow]
    configured_years: set[int]
    thresholds: list[ThresholdRow]


def check_period(start: date, end: date) -> None:
    """Refuse a period that ends before it starts or is longer than allowed (R20.19)."""
    if end < start:
        raise ToolError(f'The end date {end} is before the start date {start}.')
    n_days = (end - start).days + 1
    if n_days > MAX_PERIOD_DAYS:
        raise ToolError(
            f'The period has {n_days} days; it may have at most {MAX_PERIOD_DAYS} days. '
            'Ask for a shorter period.'
        )


def find_month_period(year: int, month: int) -> tuple[date, date]:
    """Give the first and last day of a month."""
    n_days = calendar.monthrange(year=year, month=month)[1]
    return date(year=year, month=month, day=1), date(year=year, month=month, day=n_days)


def list_dates(start: date, end: date) -> Iterator[date]:
    """Give every date from start to end, both included."""
    n_days = (end - start).days + 1
    for offset in range(n_days):
        yield start + timedelta(days=offset)


def find_week_start(day: date) -> date:
    """Give the Monday of the week of a date."""
    return day - timedelta(days=day.weekday())


def is_counted_row(activity: ActivityRow) -> bool:
    """Tell whether an activity counts: not cancelled and not Dimona-rejected (R17.2)."""
    return not activity.is_cancelled and activity.dimona_status != DimonaStatus.REJECTED


def is_in_period(activity: ActivityRow, start: date, end: date) -> bool:
    """Tell whether an activity falls in a period, both days included."""
    return start <= activity.activity_date <= end


def convert_hours(hours: Decimal) -> float:
    """Give hours as a plain number for the output (R20.19)."""
    return float(hours)


def read_activities(connection: sa.Connection, start: date, end: date) -> list[ActivityRow]:
    """Read every activity of a period from the activities view, by date then id."""
    query = (
        sa.select(activities_view)
        .where(activities_view.c.activity_date.between(start, end))
        .order_by(activities_view.c.activity_date, activities_view.c.id)
    )
    rows = connection.execute(query).mappings()
    return [ActivityRow.model_validate(dict(row)) for row in rows]


def read_activity_types(connection: sa.Connection) -> list[ActivityTypeRow]:
    """Read the activity types and supplements from their view."""
    rows = connection.execute(sa.select(activity_types_view)).mappings()
    return [ActivityTypeRow.model_validate(dict(row)) for row in rows]


def read_labels(connection: sa.Connection) -> dict[str, str]:
    """Give the French label of every activity type and supplement, by code."""
    activity_types = read_activity_types(connection=connection)
    return {activity_type.code: activity_type.label for activity_type in activity_types}


def read_limit_data(connection: sa.Connection, years: list[int]) -> LimitData:
    """Read the limits, the configured years and the threshold counts of some years."""
    limits_query = sa.select(yearly_limits_view).where(yearly_limits_view.c.year.in_(years))
    limit_rows = connection.execute(limits_query).mappings()
    limits = [LimitRow.model_validate(dict(row)) for row in limit_rows]
    years_query = sa.select(configured_years_view.c.year)
    configured_years = set(connection.scalars(years_query))
    thresholds_query = (
        sa.select(limit_thresholds_view)
        .where(limit_thresholds_view.c.year.in_(years))
        .order_by(limit_thresholds_view.c.year, limit_thresholds_view.c.worker_type)
    )
    threshold_rows = connection.execute(thresholds_query).mappings()
    thresholds = [ThresholdRow.model_validate(dict(row)) for row in threshold_rows]
    return LimitData(limits=limits, configured_years=configured_years, thresholds=thresholds)


def build_catalogue(activity_types: list[ActivityTypeRow]) -> ActivityTypeCatalogue:
    """List the activity types a worker declares, in the order of FDS 5.2, without any rate."""
    by_code = {activity_type.code: activity_type for activity_type in activity_types}
    entries = []
    for code in ACTIVITY_TYPE_CODES:
        activity_type = by_code[code]
        supplement = activity_type.supplement
        supplement_label = by_code[supplement].label if supplement is not None else None
        entry = ActivityTypeEntry(
            code=code,
            label=activity_type.label,
            compensation_model=activity_type.compensation_model,
            supplement=supplement,
            supplement_label=supplement_label,
        )
        entries.append(entry)
    return ActivityTypeCatalogue(activity_types=entries)


def summarise_activities(
    activities: list[ActivityRow],
    labels: dict[str, str],
    start: date,
    end: date,
) -> PeriodSummary:
    """Sum the counted activities of a period per activity type and per worker type (R20.14)."""
    period_activities = [
        activity for activity in activities if is_in_period(activity=activity, start=start, end=end)
    ]
    counted_activities = [
        activity for activity in period_activities if is_counted_row(activity=activity)
    ]
    not_cancelled = [activity for activity in period_activities if not activity.is_cancelled]

    # Per activity type, in the order of FDS 5.2, then per worker type
    activity_type_totals = []
    for code in ACTIVITY_TYPE_CODES:
        type_activities = [
            activity for activity in counted_activities if activity.activity_type == code
        ]
        if not type_activities:
            continue
        type_hours = sum(activity.duration_hours for activity in type_activities)
        total = ActivityTypeTotal(
            activity_type=code,
            label=labels[code],
            hours=convert_hours(hours=type_hours),
            n_activities=len(type_activities),
        )
        activity_type_totals.append(total)
    worker_type_totals = []
    for worker_type in WorkerType:
        type_activities = [
            activity for activity in counted_activities if activity.worker_type == worker_type
        ]
        if not type_activities:
            continue
        type_hours = sum(activity.duration_hours for activity in type_activities)
        total = WorkerTypeTotal(
            worker_type=worker_type,
            hours=convert_hours(hours=type_hours),
            n_activities=len(type_activities),
        )
        worker_type_totals.append(total)

    hours = sum((activity.duration_hours for activity in counted_activities), start=Decimal('0'))
    worker_ids = {activity.worker_id for activity in counted_activities}
    rejected = [
        activity for activity in not_cancelled if activity.dimona_status == DimonaStatus.REJECTED
    ]
    pending = [
        activity for activity in not_cancelled if activity.dimona_status == DimonaStatus.PENDING
    ]
    return PeriodSummary(
        start=start,
        end=end,
        hours=convert_hours(hours=hours),
        n_activities=len(counted_activities),
        n_workers=len(worker_ids),
        activity_types=activity_type_totals,
        worker_types=worker_type_totals,
        n_cancelled=len(period_activities) - len(not_cancelled),
        n_rejected=len(rejected),
        n_pending=len(pending),
    )


def build_day_activity(activity: ActivityRow, labels: dict[str, str]) -> DayActivity:
    """Describe one counted activity of a day; the start time only for a flexi-job."""
    is_flexi_job = activity.worker_type == WorkerType.FLEXI_JOB
    return DayActivity(
        activity_id=activity.id,
        activity_type=activity.activity_type,
        label=labels[activity.activity_type],
        hours=convert_hours(hours=activity.duration_hours),
        start_time=activity.start_time if is_flexi_job else None,
        worker_type=activity.worker_type,
        dimona_status=activity.dimona_status,
    )


def list_days(
    activities: list[ActivityRow],
    labels: dict[str, str],
    start: date,
    end: date,
) -> DailyActivities:
    """Give every day of a period with its counted activities, empty days included (R20.15)."""
    counted_activities = [activity for activity in activities if is_counted_row(activity=activity)]
    days = []
    for day in list_dates(start=start, end=end):
        day_activities = [
            build_day_activity(activity=activity, labels=labels)
            for activity in counted_activities
            if activity.activity_date == day
        ]
        weekday = WEEKDAYS[day.weekday()]
        days.append(Day(day=day, weekday=weekday, activities=day_activities))
    return DailyActivities(start=start, end=end, days=days)


def find_status_anomalies(activities: list[ActivityRow], today: date) -> list[Anomaly]:
    """Find the pending and rejected Dimona declarations and the cancellations."""
    anomalies: list[Anomaly] = []
    for activity in activities:
        activity_id = activity.id
        activity_date = activity.activity_date
        if activity.is_cancelled:
            anomaly = CancelledActivity(activity_id=activity_id, activity_date=activity_date)
            anomalies.append(anomaly)
        elif activity.dimona_status == DimonaStatus.REJECTED:
            anomaly = RejectedDimona(activity_id=activity_id, activity_date=activity_date)
            anomalies.append(anomaly)
        elif activity.dimona_status == DimonaStatus.PENDING:
            declared_on = activity.created_at.astimezone(tz=BELGIAN_TIME_ZONE).date()
            days_pending = (today - declared_on).days
            anomaly = PendingDimona(
                activity_id=activity_id,
                activity_date=activity_date,
                days_pending=days_pending,
            )
            anomalies.append(anomaly)
    kind_order = ('pending_dimona', 'rejected_dimona', 'cancelled_activity')
    return sorted(anomalies, key=lambda anomaly: kind_order.index(anomaly.kind))


def find_long_activities(activities: list[ActivityRow], labels: dict[str, str]) -> list[Anomaly]:
    """Find the counted activities of more than 5 hours, whatever their type."""
    anomalies: list[Anomaly] = []
    for activity in activities:
        if activity.duration_hours <= LONG_ACTIVITY_HOURS:
            continue
        anomaly = LongActivity(
            activity_id=activity.id,
            activity_date=activity.activity_date,
            activity_type=activity.activity_type,
            label=labels[activity.activity_type],
            hours=convert_hours(hours=activity.duration_hours),
        )
        anomalies.append(anomaly)
    return anomalies


def group_by_worker_and_key(
    activities: list[ActivityRow],
    keys: dict[int, date],
) -> dict[tuple[int, date], list[ActivityRow]]:
    """Group activities by worker and by a date of each activity (its day or its week)."""
    groups: dict[tuple[int, date], list[ActivityRow]] = {}
    for activity in activities:
        group_key = (activity.worker_id, keys[activity.id])
        groups.setdefault(group_key, []).append(activity)
    return groups


def find_long_days(activities: list[ActivityRow]) -> list[Anomaly]:
    """Find the days on which one worker's counted activities add up to more than 8 hours.

    The anomaly gives the date and the activities, never the worker.
    """
    days = {activity.id: activity.activity_date for activity in activities}
    groups = group_by_worker_and_key(activities=activities, keys=days)
    anomalies: list[Anomaly] = []
    for group_key in groups:
        day_activities = groups[group_key]
        hours = sum(activity.duration_hours for activity in day_activities)
        if hours <= LONG_DAY_HOURS:
            continue
        anomaly = LongDay(
            activity_date=group_key[1],
            activity_ids=[activity.id for activity in day_activities],
            hours=convert_hours(hours=hours),
        )
        anomalies.append(anomaly)
    return sorted(anomalies, key=lambda anomaly: anomaly.activity_date)


def find_busy_weeks(activities: list[ActivityRow]) -> list[Anomaly]:
    """Find the weeks, Monday to Sunday, in which one worker worked on more than 2 days.

    The activities given cover whole weeks, also the days outside the asked period.
    """
    week_starts = {
        activity.id: find_week_start(day=activity.activity_date) for activity in activities
    }
    groups = group_by_worker_and_key(activities=activities, keys=week_starts)
    anomalies: list[Anomaly] = []
    for group_key in groups:
        week_activities = groups[group_key]
        dates = sorted({activity.activity_date for activity in week_activities})
        if len(dates) <= MAX_DAYS_PER_WEEK:
            continue
        week_start = group_key[1]
        anomaly = BusyWeek(
            week_start=week_start,
            week_end=week_start + timedelta(days=6),
            n_days=len(dates),
            dates=dates,
            activity_ids=[activity.id for activity in week_activities],
        )
        anomalies.append(anomaly)
    return sorted(anomalies, key=lambda anomaly: anomaly.week_start)


def find_short_flexi_jobs(activities: list[ActivityRow], limits: list[LimitRow]) -> list[Anomaly]:
    """Find the counted flexi-job activities below the minimum hours per activity of their year.

    A year without a minimum is not checked, as the submission gate does not check it (R7.17).
    """
    min_hours_per_year = {
        limit.year: limit.min_hours_per_activity
        for limit in limits
        if limit.worker_type == WorkerType.FLEXI_JOB
        and limit.period == Period.YEAR
        and limit.min_hours_per_activity is not None
    }
    anomalies: list[Anomaly] = []
    for activity in activities:
        if activity.worker_type != WorkerType.FLEXI_JOB:
            continue
        min_hours = min_hours_per_year.get(activity.activity_date.year)
        if min_hours is None or activity.duration_hours >= min_hours:
            continue
        anomaly = ShortFlexiJob(
            activity_id=activity.id,
            activity_date=activity.activity_date,
            hours=convert_hours(hours=activity.duration_hours),
            min_hours=convert_hours(hours=min_hours),
        )
        anomalies.append(anomaly)
    return anomalies


def find_limit_anomalies(activities: list[ActivityRow], limit_data: LimitData) -> list[Anomaly]:
    """Find the years without a complete set of limits and the limits at the threshold."""
    anomalies: list[Anomaly] = []
    activity_years = sorted({activity.activity_date.year for activity in activities})
    for year in activity_years:
        if year in limit_data.configured_years:
            continue
        year_activities = [
            activity for activity in activities if activity.activity_date.year == year
        ]
        anomaly = YearWithoutLimits(year=year, n_activities=len(year_activities))
        anomalies.append(anomaly)
    for threshold in limit_data.thresholds:
        if not threshold.n_workers:
            continue
        hours_limit = threshold.hours_limit
        anomaly = LimitAtThreshold(
            year=threshold.year,
            period=threshold.period,
            worker_type=threshold.worker_type,
            limit_kind=threshold.kind,
            hours_limit=convert_hours(hours=hours_limit) if hours_limit is not None else None,
            n_workers=threshold.n_workers,
        )
        anomalies.append(anomaly)
    return anomalies


def find_period_anomalies(
    activities: list[ActivityRow],
    labels: dict[str, str],
    limit_data: LimitData,
    start: date,
    end: date,
    today: date,
) -> Anomalies:
    """Find everything in a period that needs a look (R20.16).

    The activities cover the whole weeks around the period, for the check of the busy weeks;
    every other check keeps to the period.
    """
    period_activities = [
        activity for activity in activities if is_in_period(activity=activity, start=start, end=end)
    ]
    counted_activities = [activity for activity in activities if is_counted_row(activity=activity)]
    counted_in_period = [
        activity for activity in period_activities if is_counted_row(activity=activity)
    ]
    anomalies = [
        *find_status_anomalies(activities=period_activities, today=today),
        *find_long_activities(activities=counted_in_period, labels=labels),
        *find_long_days(activities=counted_in_period),
        *find_busy_weeks(activities=counted_activities),
        *find_short_flexi_jobs(activities=counted_in_period, limits=limit_data.limits),
        *find_limit_anomalies(activities=counted_in_period, limit_data=limit_data),
    ]
    return Anomalies(start=start, end=end, n_anomalies=len(anomalies), anomalies=anomalies)


def list_period_years(start: date, end: date) -> list[int]:
    """Give the years a period touches."""
    return list(range(start.year, end.year + 1))


def summarise_period(connection: sa.Connection, start: date, end: date) -> PeriodSummary:
    """Read and sum the counted activities of a period."""
    check_period(start=start, end=end)
    activities = read_activities(connection=connection, start=start, end=end)
    labels = read_labels(connection=connection)
    return summarise_activities(activities=activities, labels=labels, start=start, end=end)


def list_daily_activities(connection: sa.Connection, start: date, end: date) -> DailyActivities:
    """Read the counted activities of a period, day by day."""
    check_period(start=start, end=end)
    activities = read_activities(connection=connection, start=start, end=end)
    labels = read_labels(connection=connection)
    return list_days(activities=activities, labels=labels, start=start, end=end)


def find_anomalies(connection: sa.Connection, start: date, end: date, today: date) -> Anomalies:
    """Read the activities and limits around a period and find its anomalies."""
    check_period(start=start, end=end)
    weeks_start = find_week_start(day=start)
    weeks_end = find_week_start(day=end) + timedelta(days=6)
    activities = read_activities(connection=connection, start=weeks_start, end=weeks_end)
    labels = read_labels(connection=connection)
    years = list_period_years(start=start, end=end)
    limit_data = read_limit_data(connection=connection, years=years)
    return find_period_anomalies(
        activities=activities,
        labels=labels,
        limit_data=limit_data,
        start=start,
        end=end,
        today=today,
    )


def review_month(connection: sa.Connection, year: int, month: int, today: date) -> MonthReview:
    """Give what tells whether a month looks correct (R20.17)."""
    start, end = find_month_period(year=year, month=month)
    summary = summarise_period(connection=connection, start=start, end=end)
    daily_activities = list_daily_activities(connection=connection, start=start, end=end)
    empty_days = [day for day in daily_activities.days if not day.activities]
    anomalies = find_anomalies(connection=connection, start=start, end=end, today=today)
    return MonthReview(
        year=year,
        month=month,
        summary=summary,
        days_without_activities=empty_days,
        anomalies=anomalies,
    )


def read_catalogue(connection: sa.Connection) -> ActivityTypeCatalogue:
    """Read the catalogue of the activity types (R20.18)."""
    activity_types = read_activity_types(connection=connection)
    return build_catalogue(activity_types=activity_types)
