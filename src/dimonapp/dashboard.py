"""What the admin dashboard shows, and the resolution of pending declarations (FDS 7.1).

Plain functions, so the figures and the French alerts are tested without Streamlit. The
dashboard only warns: nothing here refuses a declaration (R16.3).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.activities import is_counted
from dimonapp.compliance import LimitFlag, find_limit_flags, find_years_without_limits
from dimonapp.french import format_amount, format_date, format_decimal
from dimonapp.labels import PERIOD_LABELS
from dimonapp.models import (
    Activity,
    Authorisation,
    DimonaStatus,
    DocumentType,
    Period,
    Worker,
    YearlyLimit,
)
from dimonapp.months import find_month_start, shift_month
from dimonapp.results import ActionResult
from dimonapp.worker_tables import build_covered_text
from dimonapp.worker_types import WORKER_TYPE_LABELS, build_worker_name

logger = logging.getLogger(__name__)

# A contract ending within this many days is announced on the dashboard (R10.7).
EXPIRY_WARNING_DAYS = 30

Resolution = Literal['ok', 'rejected']
RESOLUTION_LABELS = {'ok': 'OK', 'rejected': 'Refusée'}

MISSING_DECLARATION_ID_MESSAGE = (
    "Déclaration non résolue : indiquez l'ID de déclaration Dimona pour la marquer OK."
)
ALREADY_RESOLVED_MESSAGE = "Déclaration non résolue : elle n'est plus en attente."
RESOLVED_OK_MESSAGE = 'Déclaration Dimona résolue : marquée OK.'
RESOLVED_REJECTED_MESSAGE = 'Déclaration Dimona résolue : marquée refusée.'


class PendingAlert(BaseModel):
    """A pending Dimona declaration, with the warning that names it."""

    activity_id: int
    message: str


class Dashboard(BaseModel):
    """Everything the dashboard shows, ready to display."""

    month_cost: Decimal
    n_active_workers: int
    limit_alerts: list[str]
    pending_alerts: list[PendingAlert]
    missing_limit_alerts: list[str]
    expiring_contract_alerts: list[str]


def sum_month_cost(activities: list[Activity], month_start: date) -> Decimal:
    """Sum the compensation of the counted activities of one month, all workers (R10.2).

    Planned activities of the month count too, so this is the projected cost.
    """
    next_month_start = shift_month(month_start=month_start, n_months=1)
    amounts = [
        activity.compensation_amount
        for activity in activities
        if is_counted(activity=activity)
        and month_start <= activity.activity_date < next_month_start
    ]
    return sum(amounts, start=Decimal('0'))


def build_period_text(year: int, period: Period) -> str:
    """Name a period inside a sentence, for example "au T4 2026" or "en 2026"."""
    if period == Period.YEAR:
        return f'en {year}'
    return f'au {PERIOD_LABELS[period]} {year}'


def build_limit_alert(flag: LimitFlag, worker_name: str) -> str:
    """Tell which worker reached 90% or more of which limit (R10.3)."""
    type_label = WORKER_TYPE_LABELS[flag.worker_type]
    period_text = build_period_text(year=flag.year, period=flag.period)
    subject = f'**{worker_name}** ({type_label})'
    if flag.quantity == 'hours':
        total = format_decimal(value=flag.total)
        limit = format_decimal(value=flag.limit)
        return f'{subject} : {total} des {limit} heures utilisées {period_text}.'
    total = format_amount(amount=flag.total)
    limit = format_amount(amount=flag.limit)
    kind = 'rémunération annuelle' if flag.period == Period.YEAR else 'rémunération'
    return f'{subject} : {total} des {limit} de {kind} utilisés {period_text}.'


def build_pending_alert(activity: Activity, worker_name: str, activity_label: str) -> str:
    """Name a pending declaration and tell the admin what to do (R10.4).

    The message of the Dimona service is added when there is one: it may hold the number the
    RSZ gave the declaration.
    """
    activity_date = format_date(day=activity.activity_date)
    message = (
        f'**Dimona en attente** : {worker_name}, {activity_label} le {activity_date}, pas de '
        'réponse de Dimona. Vérifiez sur le portail ONSS, puis résolvez ci-dessous.'
    )
    if activity.dimona_message:
        return f'{message} Message du service Dimona : {activity.dimona_message}'
    return message


def build_missing_limits_alert(year: int, n_activities: int) -> str:
    """Tell that a year with counted activities has no complete set of limits (R10.6)."""
    if n_activities == 1:
        counted_text = f'1 activité comptabilisée tombe en {year}'
    else:
        counted_text = f'{n_activities} activités comptabilisées tombent en {year}'
    return (
        f'**Aucune limite configurée pour {year}** : {counted_text}. '
        f'Encodez les limites {year} dans Configuration.'
    )


def build_days_text(n_days: int) -> str:
    """Tell how far away a date is, in days."""
    if n_days == 0:
        return "aujourd'hui"
    if n_days == 1:
        return 'dans 1 jour'
    return f'dans {n_days} jours'


def build_expiring_contract_alert(
    authorisation: Authorisation,
    worker_name: str,
    activity_labels: dict[str, str],
    today: date,
) -> str:
    """Tell which contract ends soon, with its type, its end date and what it covers (R10.7)."""
    type_label = WORKER_TYPE_LABELS[authorisation.worker_type]
    covered_text = build_covered_text(
        covered_types=authorisation.activity_types,
        activity_labels=activity_labels,
    )
    end_date = authorisation.end_date
    days_text = build_days_text(n_days=(end_date - today).days)
    formatted_date = format_date(day=end_date)
    return (
        f'**Contrat bientôt échu** : {worker_name}, contrat {type_label} pour {covered_text} '
        f'se termine le {formatted_date} ({days_text}).'
    )


def find_expiring_contracts(
    workers: list[Worker],
    authorisations: list[Authorisation],
    today: date,
) -> list[Authorisation]:
    """Give the contracts of active workers that end within the next 30 days, soonest first.

    A contract without end date never ends, and a qualification is not a contract (R10.7).
    Only a contract of the worker's current type counts: another one does not let the worker
    declare, so its end blocks nobody (R12.10).
    """
    last_day = today + timedelta(days=EXPIRY_WARNING_DAYS)
    active_worker_types = {worker.id: worker.worker_type for worker in workers if worker.is_active}
    expiring_contracts = [
        authorisation
        for authorisation in authorisations
        if authorisation.document_type == DocumentType.CONTRACT
        and authorisation.worker_type == active_worker_types.get(authorisation.worker_id)
        and authorisation.end_date is not None
        and today <= authorisation.end_date <= last_day
    ]
    return sorted(expiring_contracts, key=lambda authorisation: authorisation.end_date)


def build_dashboard(
    workers: list[Worker],
    activities: list[Activity],
    limits: list[YearlyLimit],
    authorisations: list[Authorisation],
    activity_labels: dict[str, str],
    today: date,
) -> Dashboard:
    """Work out the cost of the current month and every alert of the dashboard."""
    worker_names = {worker.id: build_worker_name(worker=worker) for worker in workers}

    # Workers at 90% or more of a limit, this year and later: a past year is over (R10.3)
    flags = find_limit_flags(workers=workers, activities=activities, limits=limits)
    limit_alerts = [
        build_limit_alert(flag=flag, worker_name=worker_names[flag.worker_id])
        for flag in flags
        if flag.year >= today.year
    ]

    # Pending Dimona declarations, oldest activity first (R10.4)
    pending_activities = [
        activity for activity in activities if activity.dimona_status == DimonaStatus.PENDING
    ]
    pending_activities.sort(key=lambda activity: (activity.activity_date, activity.id))
    pending_alerts = []
    for activity in pending_activities:
        message = build_pending_alert(
            activity=activity,
            worker_name=worker_names[activity.worker_id],
            activity_label=activity_labels[activity.activity_type],
        )
        pending_alerts.append(PendingAlert(activity_id=activity.id, message=message))

    # Years with counted activities but without a complete set of limits (R10.6)
    missing_limit_alerts = []
    for year in find_years_without_limits(activities=activities, limits=limits):
        year_activities = [
            activity
            for activity in activities
            if is_counted(activity=activity) and activity.activity_date.year == year
        ]
        n_activities = len(year_activities)
        alert = build_missing_limits_alert(year=year, n_activities=n_activities)
        missing_limit_alerts.append(alert)

    # Contracts of active workers ending soon (R10.7)
    expiring_contracts = find_expiring_contracts(
        workers=workers,
        authorisations=authorisations,
        today=today,
    )
    expiring_contract_alerts = [
        build_expiring_contract_alert(
            authorisation=authorisation,
            worker_name=worker_names[authorisation.worker_id],
            activity_labels=activity_labels,
            today=today,
        )
        for authorisation in expiring_contracts
    ]

    month_cost = sum_month_cost(activities=activities, month_start=find_month_start(day=today))
    active_workers = [worker for worker in workers if worker.is_active]
    return Dashboard(
        month_cost=month_cost,
        n_active_workers=len(active_workers),
        limit_alerts=limit_alerts,
        pending_alerts=pending_alerts,
        missing_limit_alerts=missing_limit_alerts,
        expiring_contract_alerts=expiring_contract_alerts,
    )


def load_dashboard(session: Session, activity_labels: dict[str, str], today: date) -> Dashboard:
    """Read what the dashboard needs from the database and work it out."""
    workers = list(session.scalars(sa.select(Worker)))
    activities = list(session.scalars(sa.select(Activity)))
    limits = list(session.scalars(sa.select(YearlyLimit)))
    authorisations = list(session.scalars(sa.select(Authorisation)))
    return build_dashboard(
        workers=workers,
        activities=activities,
        limits=limits,
        authorisations=authorisations,
        activity_labels=activity_labels,
        today=today,
    )


def resolve_pending_activity(
    session: Session,
    activity_id: int,
    resolution: Resolution,
    declaration_id: str,
) -> ActionResult:
    """Resolve a pending declaration as the admin found it on the RSZ portal (R10.5).

    "ok" needs the Dimona declaration ID, which later allows a cancellation; "rejected" takes
    none. Only the Dimona fields change, and only once: a resolved activity is no longer
    pending (R17.1).
    """
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise ValueError('Unknown activity.')
    if activity.dimona_status != DimonaStatus.PENDING:
        return ActionResult(level='error', message=ALREADY_RESOLVED_MESSAGE)

    if resolution == 'rejected':
        activity.dimona_status = DimonaStatus.REJECTED
        session.flush()
        logger.info(f'Pending activity {activity_id} resolved as rejected.')
        return ActionResult(level='success', message=RESOLVED_REJECTED_MESSAGE)

    cleaned_declaration_id = declaration_id.strip()
    if not cleaned_declaration_id:
        return ActionResult(level='error', message=MISSING_DECLARATION_ID_MESSAGE)
    activity.dimona_status = DimonaStatus.OK
    activity.dimona_declaration_id = cleaned_declaration_id
    session.flush()
    logger.info(f'Pending activity {activity_id} resolved as ok.')
    return ActionResult(level='success', message=RESOLVED_OK_MESSAGE)
