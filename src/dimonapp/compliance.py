"""Compliance engine: compares counted activities with the configured limits (FDS section 10).

The engine only warns; it never refuses anything (R16.3). Every limit comes in as an argument,
read from the yearly_limits table; no limit value lives in the code (R15.2).
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from dimonapp.activities import find_period, is_counted
from dimonapp.models import Activity, Period, Worker, WorkerType, YearlyLimit

logger = logging.getLogger(__name__)

# A worker is flagged from 90% of a limit on (R10.3).
FLAG_THRESHOLD = Decimal('0.9')

# Which limits a year needs before it counts as configured (FDS 7.7): the worker type, the
# period and the field that must be filled in. Only the structure lives here, never a value.
# Freelancers have no limits (R5.6).
REQUIRED_LIMITS = (
    (WorkerType.VRIJWILLIGER, Period.YEAR, 'euro_limit'),
    (WorkerType.ARTICLE_17, Period.Q1, 'hours_limit'),
    (WorkerType.ARTICLE_17, Period.Q2, 'hours_limit'),
    (WorkerType.ARTICLE_17, Period.Q3, 'hours_limit'),
    (WorkerType.ARTICLE_17, Period.Q4, 'hours_limit'),
    (WorkerType.ARTICLE_17, Period.YEAR, 'hours_limit'),
    (WorkerType.ARTICLE_17, Period.YEAR, 'euro_limit'),
    (WorkerType.FLEXI_JOB, Period.YEAR, 'euro_limit'),
    (WorkerType.FLEXI_JOB, Period.YEAR, 'min_hours_per_activity'),
)


class LimitFlag(BaseModel):
    """A worker who reached the threshold of one limit in one period."""

    worker_id: int
    worker_type: WorkerType
    year: int
    period: Period
    quantity: Literal['hours', 'euro']
    total: Decimal
    limit: Decimal


def find_filled_limits(limit: YearlyLimit) -> set[tuple[WorkerType, str, str]]:
    """Give the required limits that one row fills in, as (worker type, period, field)."""
    filled_limits = set()
    for worker_type, period, field in REQUIRED_LIMITS:
        if limit.worker_type != worker_type or limit.period != period:
            continue
        if getattr(limit, field) is not None:
            filled_limits.add((worker_type, period, field))
    return filled_limits


def find_configured_years(limits: list[YearlyLimit]) -> set[int]:
    """Give the years in which every required limit is filled in.

    If any required limit is missing, the whole year counts as not configured (R16.4).
    """
    filled_limits_per_year: dict[int, set[tuple[WorkerType, str, str]]] = {}
    for limit in limits:
        filled_limits = filled_limits_per_year.setdefault(limit.year, set())
        filled_limits.update(find_filled_limits(limit=limit))
    required_limits = set(REQUIRED_LIMITS)
    configured_years = set()
    for year in filled_limits_per_year:
        if required_limits <= filled_limits_per_year[year]:
            configured_years.add(year)
    return configured_years


def find_years_without_limits(activities: list[Activity], limits: list[YearlyLimit]) -> list[int]:
    """Give the years that hold a counted activity but no complete set of limits (R16.4)."""
    configured_years = find_configured_years(limits=limits)
    counted_activities = [activity for activity in activities if is_counted(activity=activity)]
    activity_years = {activity.activity_date.year for activity in counted_activities}
    return sorted(activity_years - configured_years)


def is_in_period(activity_date: date, year: int, period: str) -> bool:
    """Tell whether a date falls in a period of a year (R15.3)."""
    if activity_date.year != year:
        return False
    return period == Period.YEAR or period == find_period(activity_date=activity_date)


def check_limit(worker: Worker, activities: list[Activity], limit: YearlyLimit) -> list[LimitFlag]:
    """Compare one worker's counted activities with one limit row."""
    year = limit.year
    period = limit.period
    period_activities = [
        activity
        for activity in activities
        if is_in_period(activity_date=activity.activity_date, year=year, period=period)
    ]
    if not period_activities:
        return []

    # Sum the period (R16.1)
    zero = Decimal('0')
    total_hours = sum((activity.duration_hours for activity in period_activities), start=zero)
    total_euro = sum((activity.compensation_amount for activity in period_activities), start=zero)

    # Flag each filled-in limit that reached the threshold (R16.2)
    candidates = (('hours', total_hours, limit.hours_limit), ('euro', total_euro, limit.euro_limit))
    flags = []
    for quantity, total, limit_value in candidates:
        if limit_value is None or total < limit_value * FLAG_THRESHOLD:
            continue
        flag = LimitFlag(
            worker_id=worker.id,
            worker_type=worker.worker_type,
            year=year,
            period=Period(period),
            quantity=quantity,
            total=total,
            limit=limit_value,
        )
        flags.append(flag)
    return flags


def find_limit_flags(
    workers: list[Worker],
    activities: list[Activity],
    limits: list[YearlyLimit],
) -> list[LimitFlag]:
    """Find every worker at or above the threshold of a limit for their current status.

    Only activities declared under the worker's current type count, so a status change starts
    from zero (R5.5). Future activities count like past ones (R16.1). Freelancers are never
    flagged (R16.5), and a year without a complete set of limits raises no flag (R16.4).
    """
    configured_years = find_configured_years(limits=limits)
    counted_activities = [activity for activity in activities if is_counted(activity=activity)]
    flags = []
    for worker in workers:
        if worker.worker_type == WorkerType.FREELANCER:
            continue
        worker_id = worker.id
        worker_type = worker.worker_type
        own_activities = [
            activity
            for activity in counted_activities
            if activity.worker_id == worker_id and activity.worker_type == worker_type
        ]
        for limit in limits:
            if limit.worker_type != worker_type or limit.year not in configured_years:
                continue
            limit_flags = check_limit(worker=worker, activities=own_activities, limit=limit)
            flags.extend(limit_flags)
    n_flags = len(flags)
    logger.info(f'Compliance check done: {n_flags} limit flag(s).')
    return flags
