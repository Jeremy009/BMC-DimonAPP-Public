"""The cancellation flow (FDS section 9).

Cancelling only ever sets the cancellation marker (R9.5), and for a Dimona activity only once
the Dimona service has confirmed (R9.4). An article 17 activity shares the Dimona period of
its day with the worker's other activities of that day: while others remain, the period keeps
their hours instead of being cancelled (R9.6).
"""

import logging
from typing import Literal

from sqlalchemy.orm import Session

from dimonapp import worker_messages
from dimonapp.dimona import CancellationOutcome, DimonaClient
from dimonapp.dimona_days import (
    find_accepted_activities,
    find_day_activities,
    has_pending_declaration,
    sum_planned_hours,
)
from dimonapp.models import Activity, WorkerType
from dimonapp.results import ActionResult
from dimonapp.worker_types import requires_dimona

logger = logging.getLogger(__name__)

# How the answer to lowering the hours of a day reads as a cancellation (R9.6).
UPDATE_CANCELLATION_STATUSES = {
    'accepted': 'confirmed',
    'rejected': 'refused',
    'no_answer': 'no_answer',
}


class CancellationResult(ActionResult):
    """How a cancellation ended and what to tell the worker."""

    outcome: Literal['cancelled', 'no_declaration_id', 'pending_day', 'refused', 'no_answer']


def lower_day_hours(
    dimona_client: DimonaClient,
    activity: Activity,
    remaining_activities: list[Activity],
) -> CancellationOutcome:
    """Lower the hours of the day's period to those of the remaining activities (R9.6)."""
    planned_hours = sum_planned_hours(activities=remaining_activities)
    logger.info(f'Article 17 period of activity {activity.id} lowered to {planned_hours} hours.')
    outcome = dimona_client.update_hours(
        declaration_id=activity.dimona_declaration_id,
        planned_hours=planned_hours,
    )
    status = UPDATE_CANCELLATION_STATUSES[outcome.status]
    return CancellationOutcome(status=status, message=outcome.message)


def cancel_activity(
    session: Session,
    dimona_client: DimonaClient,
    worker_id: int,
    activity_id: int,
) -> CancellationResult:
    """Cancel one of the worker's own activities, past or future (R7.9)."""
    activity = session.get(Activity, activity_id)
    if activity is None or activity.worker_id != worker_id or activity.is_cancelled:
        raise ValueError('Not an active activity of this worker.')

    # Volunteer or freelancer activity: cancelled at once (R9.1)
    if not requires_dimona(worker_type=activity.worker_type):
        activity.is_cancelled = True
        session.flush()
        logger.info(f'Activity {activity_id} cancelled without Dimona.')
        message = worker_messages.CANCELLED_MESSAGE
        return CancellationResult(outcome='cancelled', level='success', message=message)

    # Rejected or pending declaration: nothing to cancel at the Dimona service (R9.2)
    declaration_id = activity.dimona_declaration_id
    if declaration_id is None:
        logger.info(f'Activity {activity_id} not cancelled: no Dimona declaration ID.')
        message = worker_messages.NO_DECLARATION_ID_MESSAGE
        return CancellationResult(outcome='no_declaration_id', level='warning', message=message)

    # Article 17: the period of the day may hold other activities (R9.6, R9.7)
    remaining_activities = []
    if activity.worker_type == WorkerType.ARTICLE_17:
        day_activities = find_day_activities(
            session=session,
            worker_id=worker_id,
            activity_date=activity.activity_date,
        )
        if has_pending_declaration(activities=day_activities):
            logger.info(f'Activity {activity_id} not cancelled: Dimona pending that day.')
            message = worker_messages.CANCELLATION_PENDING_DAY_MESSAGE
            return CancellationResult(outcome='pending_day', level='warning', message=message)
        other_activities = [other for other in day_activities if other.id != activity_id]
        remaining_activities = find_accepted_activities(activities=other_activities)

    # Ask the Dimona service and follow its real answer (R9.4)
    if remaining_activities:
        outcome = lower_day_hours(
            dimona_client=dimona_client,
            activity=activity,
            remaining_activities=remaining_activities,
        )
        success_message = worker_messages.CANCELLED_WITH_DIMONA_UPDATE_MESSAGE
    else:
        outcome = dimona_client.cancel(declaration_id=declaration_id)
        success_message = worker_messages.CANCELLED_WITH_DIMONA_MESSAGE
    if outcome.status == 'refused':
        logger.info(f'Activity {activity_id} not cancelled: refused by Dimona.')
        message = worker_messages.build_cancellation_refused_message(reason=outcome.message)
        return CancellationResult(outcome='refused', level='warning', message=message)
    if outcome.status == 'no_answer':
        logger.info(f'Activity {activity_id} not cancelled: no answer from Dimona.')
        message = worker_messages.CANCELLATION_NO_ANSWER_MESSAGE
        return CancellationResult(outcome='no_answer', level='warning', message=message)

    activity.is_cancelled = True
    session.flush()
    logger.info(f'Activity {activity_id} cancelled after confirmation by Dimona.')
    return CancellationResult(outcome='cancelled', level='success', message=success_message)
