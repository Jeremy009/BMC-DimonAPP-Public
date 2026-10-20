"""The compensation sheet of a worker: effective-dated rates per activity type (FDS 7.4).

One rate per activity type and one per supplement. Plain functions on a database session. A
new version never touches a declared activity: the
amount was copied onto it at declaration (R6.7).
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.compensation import find_rate
from dimonapp.french import format_amount, format_date
from dimonapp.labels import COMPENSATION_MODEL_LABELS, RATE_UNITS
from dimonapp.models import RATE_CODES, CompensationModel, CompensationRate
from dimonapp.results import ActionResult

logger = logging.getLogger(__name__)

NOT_SAVED_PREFIX = 'Tarif non enregistré : '
MISSING_AMOUNT_MESSAGE = f'{NOT_SAVED_PREFIX}indiquez le nouveau tarif.'
NEGATIVE_AMOUNT_MESSAGE = f'{NOT_SAVED_PREFIX}le tarif ne peut pas être négatif.'
MISSING_VALID_FROM_MESSAGE = f'{NOT_SAVED_PREFIX}indiquez la date à partir de laquelle il vaut.'
NO_RATE_TEXT = 'Aucun tarif'

# The standard BMC rates the worker create form opens on (R6.12, FDS 7.4); the admin changes
# them where a worker differs.
DEFAULT_RATES = {
    'permanence': Decimal('60'),
    'courses': Decimal('18'),
    'group_without_instructor': Decimal('20'),
    'group_with_instructor': Decimal('40'),
    'group_travel': Decimal('25'),
    'route_setting_easy': Decimal('50'),
    'route_setting_medium': Decimal('60'),
    'route_setting_hard': Decimal('70'),
    'rope_supplement': Decimal('10'),
    'route_cleaning_easy': Decimal('15'),
    'route_cleaning_hard': Decimal('25'),
}


def format_rate(amount: Decimal, compensation_model: CompensationModel) -> str:
    """Format a rate with what it pays for, for example 20,00 € / heure."""
    formatted_amount = format_amount(amount=amount)
    return f'{formatted_amount} / {RATE_UNITS[compensation_model]}'


def find_worker_rates(session: Session, worker_id: int) -> list[CompensationRate]:
    """Give every rate version of one worker, newest first per activity type."""
    query = (
        sa.select(CompensationRate)
        .where(CompensationRate.worker_id == worker_id)
        .order_by(CompensationRate.valid_from.desc(), CompensationRate.id)
    )
    rates = list(session.scalars(query))
    return sorted(rates, key=lambda rate: RATE_CODES.index(rate.activity_type))


def build_sheet_rows(
    rates: list[CompensationRate],
    activity_labels: dict[str, str],
    compensation_models: dict[str, CompensationModel],
    today: date,
) -> list[dict[str, str]]:
    """Build the sheet: per activity type and supplement its model and current rate (R6.6)."""
    rows = []
    for activity_type in RATE_CODES:
        type_rates = [rate for rate in rates if rate.activity_type == activity_type]
        current_rate = find_rate(rates=type_rates, activity_date=today)
        compensation_model = compensation_models[activity_type]
        rate_text = NO_RATE_TEXT
        valid_from_text = ''
        if current_rate is not None:
            rate_text = format_rate(
                amount=current_rate.amount,
                compensation_model=compensation_model,
            )
            valid_from_text = format_date(day=current_rate.valid_from)
        row = {
            "Type d'activité": activity_labels[activity_type],
            'Modèle': COMPENSATION_MODEL_LABELS[compensation_model],
            'Tarif actuel': rate_text,
            'Valable depuis': valid_from_text,
        }
        rows.append(row)
    return rows


def build_version_rows(
    rates: list[CompensationRate],
    activity_labels: dict[str, str],
    compensation_models: dict[str, CompensationModel],
) -> list[dict[str, str]]:
    """Build the list of every rate version, so coming versions can be seen too."""
    rows = []
    for rate in rates:
        compensation_model = compensation_models[rate.activity_type]
        row = {
            "Type d'activité": activity_labels[rate.activity_type],
            'Tarif': format_rate(amount=rate.amount, compensation_model=compensation_model),
            'Valable à partir du': format_date(day=rate.valid_from),
        }
        rows.append(row)
    return rows


def save_rate_version(
    session: Session,
    worker_id: int,
    activity_type: str,
    amount: Optional[Decimal],
    valid_from: Optional[date],
) -> ActionResult:
    """Add a rate version valid from a date (R6.7).

    A version that already starts on that date is corrected instead, so a typing error can be
    put right; declared activities keep their stored amount either way.
    """
    if amount is None:
        return ActionResult(level='error', message=MISSING_AMOUNT_MESSAGE)
    if amount < 0:
        return ActionResult(level='error', message=NEGATIVE_AMOUNT_MESSAGE)
    if valid_from is None:
        return ActionResult(level='error', message=MISSING_VALID_FROM_MESSAGE)

    query = sa.select(CompensationRate).where(
        CompensationRate.worker_id == worker_id,
        CompensationRate.activity_type == activity_type,
        CompensationRate.valid_from == valid_from,
    )
    rate = session.scalars(query).first()
    if rate is None:
        rate = CompensationRate(
            worker_id=worker_id,
            activity_type=activity_type,
            valid_from=valid_from,
        )
        session.add(rate)
    rate.amount = amount
    session.flush()
    logger.info(f'Rate version {rate.id} saved for worker {worker_id}.')
    formatted_date = format_date(day=valid_from)
    return ActionResult(
        level='success',
        message=f'Tarif enregistré, valable à partir du {formatted_date}.',
    )
