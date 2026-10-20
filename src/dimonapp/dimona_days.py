"""The Dimona period of one article 17 worker on one day (R8.9, R8.10, R9.6, R9.7).

The RSZ keeps at most one article 17 period per worker and day and refuses a second Dimona IN
for that day ("Période Dimona en double"). The first activity of the day opens the period;
every later activity, and every cancellation while others remain, changes its planned hours.
Those hours always follow from the stored activities, which themselves never change (R17.1).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.models import Activity, DimonaStatus, WorkerType


def find_day_activities(session: Session, worker_id: int, activity_date: date) -> list[Activity]:
    """Give the worker's non-cancelled article 17 activities of one day, oldest first."""
    query = (
        sa.select(Activity)
        .where(
            Activity.worker_id == worker_id,
            Activity.activity_date == activity_date,
            Activity.worker_type == WorkerType.ARTICLE_17,
            Activity.is_cancelled.is_(False),
        )
        .order_by(Activity.id)
    )
    return list(session.scalars(query))


def has_pending_declaration(activities: list[Activity]) -> bool:
    """Tell whether one of the activities waits for a Dimona verdict (R8.10, R9.7).

    While one does, nobody knows the hours the RSZ holds for that day, so nothing is sent.
    """
    return any(activity.dimona_status == DimonaStatus.PENDING for activity in activities)


def find_accepted_activities(activities: list[Activity]) -> list[Activity]:
    """Keep the activities whose Dimona declaration the RSZ accepted."""
    return [activity for activity in activities if activity.dimona_status == DimonaStatus.OK]


def find_period_declaration_id(activities: list[Activity]) -> Optional[str]:
    """Give the declaration ID of the latest accepted activity, or None without any.

    Every accepted activity of the day belongs to the same period, so any of them leads to it.
    """
    accepted_activities = find_accepted_activities(activities=activities)
    if not accepted_activities:
        return None
    return accepted_activities[-1].dimona_declaration_id


def sum_planned_hours(activities: list[Activity]) -> int:
    """Give the whole hours of the accepted activities, as the RSZ takes them (R7.5)."""
    accepted_activities = find_accepted_activities(activities=activities)
    hours = sum((activity.duration_hours for activity in accepted_activities), start=Decimal('0'))
    return int(hours)
