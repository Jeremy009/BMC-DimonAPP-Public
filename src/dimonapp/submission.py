"""The activity submission gate and the Dimona flow (FDS section 8).

Plain functions on a database session and a Dimona client, so the gate is tested without
Streamlit. The checks run in the FDS order and stop at the first failure (R8.1). Legal limits
are never checked here: they only raise warnings on the admin dashboard (R16.3).
"""

import logging
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Literal, Optional

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp import worker_messages
from dimonapp.activities import is_counted
from dimonapp.authorisations import has_valid_contract, has_valid_document
from dimonapp.compensation import compute_compensation, find_rate
from dimonapp.dimona import DeclarationOutcome, DimonaClient, DimonaDeclaration
from dimonapp.dimona_days import (
    find_day_activities,
    find_period_declaration_id,
    has_pending_declaration,
    sum_planned_hours,
)
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    Activity,
    ActivityType,
    Authorisation,
    CompensationRate,
    DimonaStatus,
    DocumentType,
    Period,
    Worker,
    WorkerType,
    YearlyLimit,
)
from dimonapp.months import add_months, find_quarter_start, shift_month
from dimonapp.results import ActionResult
from dimonapp.worker_types import requires_dimona

logger = logging.getLogger(__name__)

# An activity is declared at most this many months ahead (R7.14).
MAX_MONTHS_AHEAD = 3
# The RSZ takes a flexi-job declaration from this many months before its quarter starts (R7.16).
FLEXI_MONTHS_BEFORE_QUARTER = 1
MONTHS_PER_QUARTER = 3
# A flexi-job starts on the hour or the half hour (R7.15).
START_TIME_STEP_MINUTES = 30

# The supplements a worker gets at most once per day (R6.11).
ONCE_PER_DAY_SUPPLEMENTS = ('group_travel',)

# How each answer of the Dimona service is stored (R8.6 to R8.8).
DIMONA_STATUSES = {
    'accepted': DimonaStatus.OK,
    'rejected': DimonaStatus.REJECTED,
    'no_answer': DimonaStatus.PENDING,
}


class ActivityForm(BaseModel):
    """What the worker enters in the create form (R7.3)."""

    # Empty when the date picker holds no date: a picked date that falls outside the limits
    # later, for example at midnight, is emptied rather than replaced.
    activity_date: Optional[date]
    activity_type: str
    duration_hours: Optional[Decimal]
    description: str = ''
    # Only asked of flexi-jobbers (R7.15).
    start_time: Optional[time] = None
    # The tick box of the supplement, only offered by an activity type that has one (R6.9).
    with_supplement: bool = False


class SubmissionResult(ActionResult):
    """How a submission ended and what to tell the worker.

    Without activity_id nothing was registered (R8.2).
    """

    outcome: Literal[
        'invalid_input',
        'no_contract',
        'no_qualification',
        'pending_day',
        'confirmed',
        'accepted',
        'rejected',
        'pending',
    ]
    activity_id: Optional[int] = None


def find_min_hours(session: Session, year: int) -> Optional[Decimal]:
    """Give the minimum hours per flexi-job activity configured for a year, or None (R7.7).

    The value comes only from the yearly_limits table (R15.2). A year without it is not
    guessed: the check is then skipped and the activity is not blocked (FDS section 10).
    """
    query = sa.select(YearlyLimit.min_hours_per_activity).where(
        YearlyLimit.year == year,
        YearlyLimit.worker_type == WorkerType.FLEXI_JOB,
        YearlyLimit.period == Period.YEAR,
    )
    return session.scalars(query).first()


def find_latest_flexi_date(today: date) -> date:
    """Give the last day of the latest quarter the RSZ takes flexi-job declarations for (R7.16).

    A quarter opens one month before it starts: on 1 December the first quarter of the next
    year opens. Until then the current quarter is the latest one.
    """
    quarter_start = find_quarter_start(day=today)
    next_quarter_start = shift_month(month_start=quarter_start, n_months=MONTHS_PER_QUARTER)
    opening_day = shift_month(month_start=next_quarter_start, n_months=-FLEXI_MONTHS_BEFORE_QUARTER)
    if today >= opening_day:
        quarter_start = next_quarter_start
    following_quarter_start = shift_month(month_start=quarter_start, n_months=MONTHS_PER_QUARTER)
    return following_quarter_start - timedelta(days=1)


def find_latest_date(today: date, worker_type: WorkerType) -> date:
    """Give the latest date this worker type can declare an activity for today (R7.14, R7.16)."""
    latest_date = add_months(day=today, n_months=MAX_MONTHS_AHEAD)
    if worker_type != WorkerType.FLEXI_JOB:
        return latest_date
    return min(latest_date, find_latest_flexi_date(today=today))


def is_valid_start_time(start_time: Optional[time]) -> bool:
    """Tell whether a flexi-job start time is entered, on the hour or the half hour (R7.15)."""
    if start_time is None:
        return False
    is_on_step = start_time.minute % START_TIME_STEP_MINUTES == 0
    return is_on_step and start_time.second == 0 and start_time.microsecond == 0


def find_input_error(
    form: ActivityForm,
    activity_type: ActivityType,
    worker_type: WorkerType,
    min_hours: Optional[Decimal],
    today: date,
) -> Optional[str]:
    """Give the French message of the first invalid input, or None when all is valid.

    Date entered, not in the past (R7.4) and at most 3 months ahead (R7.14), for flexi-jobbers
    within the quarters the RSZ takes (R7.16) and with a start time (R7.15), duration entered in
    whole hours (R7.5), minimum duration for flexi-jobbers (R7.7), description for route setting
    (R7.6).
    """
    if form.activity_date is None:
        return worker_messages.MISSING_DATE_MESSAGE
    if form.activity_date < today:
        return worker_messages.PAST_DATE_MESSAGE
    if form.activity_date > add_months(day=today, n_months=MAX_MONTHS_AHEAD):
        return worker_messages.TOO_FAR_AHEAD_MESSAGE
    is_flexi_job = worker_type == WorkerType.FLEXI_JOB
    latest_date = find_latest_date(today=today, worker_type=worker_type)
    if form.activity_date > latest_date:
        return worker_messages.build_flexi_too_far_message(latest_date=latest_date)
    if is_flexi_job and not is_valid_start_time(start_time=form.start_time):
        return worker_messages.MISSING_START_TIME_MESSAGE
    duration_hours = form.duration_hours
    if duration_hours is None or duration_hours <= 0:
        return worker_messages.MISSING_DURATION_MESSAGE
    if duration_hours % 1 != 0:
        return worker_messages.WHOLE_HOURS_MESSAGE
    if is_flexi_job and min_hours is not None and duration_hours < min_hours:
        return worker_messages.build_min_hours_message(min_hours=min_hours)
    if activity_type.description_required and not form.description.strip():
        return worker_messages.MISSING_DESCRIPTION_MESSAGE
    return None


def has_supplement_that_day(
    session: Session,
    worker_id: int,
    activity_date: date,
    supplement: str,
) -> bool:
    """Tell whether a counted activity of the worker already carries the supplement that day."""
    query = (
        sa.select(Activity)
        .join(ActivityType, Activity.activity_type == ActivityType.code)
        .where(
            Activity.worker_id == worker_id,
            Activity.activity_date == activity_date,
            Activity.supplement_amount > 0,
            ActivityType.supplement == supplement,
        )
    )
    activities = session.scalars(query)
    return any(is_counted(activity=activity) for activity in activities)


def find_supplement_error(
    session: Session,
    worker_id: int,
    activity_date: date,
    supplement: Optional[str],
) -> Optional[str]:
    """Give the French message of a supplement that is not allowed, or None (R6.11).

    The group travel supplement is paid at most once per day.
    """
    if supplement not in ONCE_PER_DAY_SUPPLEMENTS:
        return None
    is_declared = has_supplement_that_day(
        session=session,
        worker_id=worker_id,
        activity_date=activity_date,
        supplement=supplement,
    )
    return worker_messages.SUPPLEMENT_ALREADY_DECLARED_MESSAGE if is_declared else None


def find_document_failure(
    session: Session,
    worker_id: int,
    worker_type: WorkerType,
    activity_type: str,
    activity_date: date,
) -> Optional[SubmissionResult]:
    """Check the contract, then the qualification; give the first failure or None (R12.1).

    The contract must be one of the worker's type (R12.10).
    """
    query = sa.select(Authorisation).where(Authorisation.worker_id == worker_id)
    authorisations = list(session.scalars(query))

    has_contract = has_valid_contract(
        authorisations=authorisations,
        worker_type=worker_type,
        activity_type=activity_type,
        activity_date=activity_date,
    )
    if not has_contract:
        message = worker_messages.build_no_contract_message(
            worker_type=worker_type,
            activity_type=activity_type,
            activity_date=activity_date,
        )
        return SubmissionResult(outcome='no_contract', level='error', message=message)

    has_qualification = has_valid_document(
        authorisations=authorisations,
        document_type=DocumentType.QUALIFICATION,
        activity_type=activity_type,
        activity_date=activity_date,
    )
    if not has_qualification:
        message = worker_messages.build_no_qualification_message(
            activity_type=activity_type,
            activity_date=activity_date,
        )
        return SubmissionResult(outcome='no_qualification', level='error', message=message)
    return None


def find_rate_amount(
    session: Session,
    worker_id: int,
    rate_code: str,
    activity_date: date,
) -> Decimal:
    """Give the worker's rate for an activity type or a supplement, valid on the date (R6.7).

    Every worker gets all rates at creation and a rate stays valid until a newer one, so a
    missing rate is a data error, not something the worker can solve.
    """
    query = sa.select(CompensationRate).where(
        CompensationRate.worker_id == worker_id,
        CompensationRate.activity_type == rate_code,
    )
    rates = list(session.scalars(query))
    rate = find_rate(rates=rates, activity_date=activity_date)
    if rate is None:
        raise ValueError(f'Worker {worker_id} has no rate for {rate_code}.')
    return rate.amount


def build_activity(
    session: Session,
    worker: Worker,
    activity_type: ActivityType,
    supplement: Optional[str],
    form: ActivityForm,
) -> Activity:
    """Build the unsaved activity with the rates valid on its date (R8.3).

    The worker type, model, rate, supplement and amount are copied onto the activity (R17.3);
    the amount includes the supplement (R6.10).
    """
    activity_date = form.activity_date
    rate = find_rate_amount(
        session=session,
        worker_id=worker.id,
        rate_code=activity_type.code,
        activity_date=activity_date,
    )
    supplement_amount = Decimal('0')
    if supplement is not None:
        supplement_amount = find_rate_amount(
            session=session,
            worker_id=worker.id,
            rate_code=supplement,
            activity_date=activity_date,
        )

    compensation_model = activity_type.compensation_model
    duration_hours = form.duration_hours
    base_amount = compute_compensation(
        compensation_model=compensation_model,
        rate=rate,
        duration_hours=duration_hours,
    )
    compensation_amount = base_amount + supplement_amount
    description = form.description.strip() or None
    is_flexi_job = worker.worker_type == WorkerType.FLEXI_JOB
    start_time = form.start_time if is_flexi_job else None
    return Activity(
        worker_id=worker.id,
        worker_type=worker.worker_type,
        activity_date=activity_date,
        activity_type=activity_type.code,
        description=description,
        duration_hours=duration_hours,
        start_time=start_time,
        compensation_model=compensation_model,
        rate_applied=rate,
        supplement_amount=supplement_amount,
        compensation_amount=compensation_amount,
    )


def build_dimona_result(outcome: DeclarationOutcome, activity: Activity) -> SubmissionResult:
    """Describe a registered Dimona activity to the worker, after the real answer (R17.4)."""
    activity_id = activity.id
    if outcome.status == 'accepted':
        message = worker_messages.build_accepted_message(
            declaration_id=outcome.declaration_id,
            amount=activity.compensation_amount,
        )
        return SubmissionResult(
            outcome='accepted',
            level='success',
            message=message,
            activity_id=activity_id,
        )
    if outcome.status == 'rejected':
        message = worker_messages.build_rejected_message(reason=outcome.message)
        return SubmissionResult(
            outcome='rejected',
            level='error',
            message=message,
            activity_id=activity_id,
        )
    message = worker_messages.PENDING_MESSAGE
    return SubmissionResult(
        outcome='pending',
        level='warning',
        message=message,
        activity_id=activity_id,
    )


def build_declaration(worker: Worker, activity: Activity) -> DimonaDeclaration:
    """Build the Dimona IN of one activity (R8.5)."""
    return DimonaDeclaration(
        national_register_number=worker.national_register_number,
        worker_type=activity.worker_type,
        activity_date=activity.activity_date,
        planned_hours=int(activity.duration_hours),
        start_time=activity.start_time,
    )


def declare_article_17(
    dimona_client: DimonaClient,
    worker: Worker,
    activity: Activity,
    day_activities: list[Activity],
) -> DeclarationOutcome:
    """Open the period of the day, or add the activity's hours to it (R8.5, R8.9).

    The RSZ keeps one article 17 period per worker and day: the first accepted activity of
    the day opens it with a Dimona IN, every later one updates its planned hours to the
    hours of all the day's accepted activities plus its own.
    """
    declaration_id = find_period_declaration_id(activities=day_activities)
    if declaration_id is None:
        declaration = build_declaration(worker=worker, activity=activity)
        return dimona_client.declare(declaration=declaration)
    day_hours = sum_planned_hours(activities=day_activities)
    planned_hours = day_hours + int(activity.duration_hours)
    logger.info(f'Article 17 period of worker {worker.id} raised to {planned_hours} hours.')
    return dimona_client.update_hours(declaration_id=declaration_id, planned_hours=planned_hours)


def submit_activity(
    session: Session,
    dimona_client: DimonaClient,
    worker_id: int,
    form: ActivityForm,
    today: date,
) -> SubmissionResult:
    """Run the submission gate for one activity and register it when every check passes."""
    worker = session.get(Worker, worker_id)
    if form.activity_type not in ACTIVITY_TYPE_CODES:
        raise ValueError('Unknown activity type.')
    activity_type = session.get(ActivityType, form.activity_type)
    if worker is None or not worker.is_active or activity_type is None:
        raise ValueError('Unknown or inactive worker, or unknown activity type.')
    # A ticked box only counts on an activity type that offers a supplement (R6.9)
    supplement = activity_type.supplement if form.with_supplement else None
    worker_type = worker.worker_type
    activity_date = form.activity_date

    # Check the input (step 1); the minimum hours of a flexi-job follow the year of the date
    min_hours = None
    if activity_date is not None:
        min_hours = find_min_hours(session=session, year=activity_date.year)
    input_error = find_input_error(
        form=form,
        activity_type=activity_type,
        worker_type=worker_type,
        min_hours=min_hours,
        today=today,
    )
    if input_error is not None:
        logger.info(f'Activity of worker {worker_id} refused: invalid input.')
        return SubmissionResult(outcome='invalid_input', level='error', message=input_error)
    supplement_error = find_supplement_error(
        session=session,
        worker_id=worker_id,
        activity_date=activity_date,
        supplement=supplement,
    )
    if supplement_error is not None:
        logger.info(f'Activity of worker {worker_id} refused: supplement already declared.')
        return SubmissionResult(outcome='invalid_input', level='error', message=supplement_error)

    # Check the contract and the qualification (steps 2 and 3)
    document_failure = find_document_failure(
        session=session,
        worker_id=worker_id,
        worker_type=worker_type,
        activity_type=activity_type.code,
        activity_date=activity_date,
    )
    if document_failure is not None:
        logger.info(f'Activity of worker {worker_id} refused: {document_failure.outcome}.')
        return document_failure

    # Compute the compensation (step 4)
    activity = build_activity(
        session=session,
        worker=worker,
        activity_type=activity_type,
        supplement=supplement,
        form=form,
    )

    # Volunteers and freelancers: registered at once, without Dimona (step 5)
    if not requires_dimona(worker_type=worker_type):
        activity.dimona_status = DimonaStatus.NOT_APPLICABLE
        session.add(activity)
        session.flush()
        logger.info(f'Activity {activity.id} registered without Dimona.')
        amount = activity.compensation_amount
        message = worker_messages.build_confirmed_message(amount=amount)
        return SubmissionResult(
            outcome='confirmed',
            level='success',
            message=message,
            activity_id=activity.id,
        )

    # Send the declaration and store what the service really answered (steps 6 to 9)
    if worker_type == WorkerType.ARTICLE_17:
        day_activities = find_day_activities(
            session=session,
            worker_id=worker_id,
            activity_date=activity_date,
        )
        if has_pending_declaration(activities=day_activities):
            logger.info(f'Activity of worker {worker_id} refused: Dimona pending that day.')
            message = worker_messages.PENDING_DAY_MESSAGE
            return SubmissionResult(outcome='pending_day', level='error', message=message)
        outcome = declare_article_17(
            dimona_client=dimona_client,
            worker=worker,
            activity=activity,
            day_activities=day_activities,
        )
    else:
        declaration = build_declaration(worker=worker, activity=activity)
        outcome = dimona_client.declare(declaration=declaration)
    activity.dimona_status = DIMONA_STATUSES[outcome.status]
    activity.dimona_declaration_id = outcome.declaration_id
    activity.dimona_message = outcome.message
    session.add(activity)
    session.flush()
    logger.info(f'Activity {activity.id} registered with Dimona status {activity.dimona_status}.')
    return build_dimona_result(outcome=outcome, activity=activity)
