"""Rules about activities: whether one counts, its period, and a worker's month."""

from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.models import Activity, DimonaStatus, Period, Worker
from dimonapp.months import shift_month

QUARTERS = (Period.Q1, Period.Q2, Period.Q3, Period.Q4)


class ActivityTotals(BaseModel):
    """The totals of a set of activities."""

    hours: Decimal
    amount: Decimal


def is_counted(activity: Activity) -> bool:
    """Tell whether an activity counts in totals: not cancelled and not Dimona-rejected (R17.2)."""
    return not activity.is_cancelled and activity.dimona_status != DimonaStatus.REJECTED


def find_period(activity_date: date) -> Period:
    """Give the quarter a date falls in."""
    quarter_index = (activity_date.month - 1) // 3
    return QUARTERS[quarter_index]


def find_month_activities(session: Session, worker_id: int, month_start: date) -> list[Activity]:
    """Give one worker's activities of one month, oldest first (R7.2, R7.9, R7.10)."""
    next_month_start = shift_month(month_start=month_start, n_months=1)
    query = (
        sa.select(Activity)
        .where(
            Activity.worker_id == worker_id,
            Activity.activity_date >= month_start,
            Activity.activity_date < next_month_start,
        )
        .order_by(Activity.activity_date, Activity.id)
    )
    return list(session.scalars(query))


def find_all_month_activities(session: Session, month_start: date) -> list[tuple[Activity, Worker]]:
    """Give every worker's activities of one month with their worker, by day then name (R19.1)."""
    next_month_start = shift_month(month_start=month_start, n_months=1)
    query = (
        sa.select(Activity, Worker)
        .join(Worker, Worker.id == Activity.worker_id)
        .where(
            Activity.activity_date >= month_start,
            Activity.activity_date < next_month_start,
        )
        .order_by(Activity.activity_date, Worker.last_name, Worker.first_name, Activity.id)
    )
    return [(activity, worker) for activity, worker in session.execute(query)]


def sum_counted_activities(activities: list[Activity]) -> ActivityTotals:
    """Sum the hours and compensation of the counted activities only (R7.12)."""
    counted_activities = [activity for activity in activities if is_counted(activity=activity)]
    zero = Decimal('0')
    hours = sum((activity.duration_hours for activity in counted_activities), start=zero)
    amount = sum((activity.compensation_amount for activity in counted_activities), start=zero)
    return ActivityTotals(hours=hours, amount=amount)
