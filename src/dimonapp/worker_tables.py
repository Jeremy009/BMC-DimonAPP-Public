"""Rows of the worker view tables, formatted in French (R7.9, R7.10, R7.13, R18.1).

Plain builders from ORM objects to text, so the tables are tested without Streamlit.
"""

from datetime import date

from dimonapp.authorisations import is_expired
from dimonapp.french import format_amount, format_date, format_decimal
from dimonapp.labels import (
    CANCELLED_LABEL,
    DIMONA_STATUS_LABELS,
    DOCUMENT_TYPE_LABELS,
    EXPIRED_LABEL,
    VALID_LABEL,
)
from dimonapp.models import Activity, Authorisation
from dimonapp.worker_types import WORKER_TYPE_LABELS

# The three course types are one clearance, "Cours", and route setting and route cleaning are
# one clearance, "Ouverture de voies": within a clearance the activity types only exist to set
# the rate, so a document is never shown per type (FDS 7.3).
COURSE_CLEARANCE_LABEL = 'Cours'
COURSE_ACTIVITY_TYPES = ('courses', 'group_without_instructor', 'group_with_instructor')
ROUTE_CLEARANCE_LABEL = 'Ouverture de voies'
ROUTE_ACTIVITY_TYPES = (
    'route_setting_easy',
    'route_setting_medium',
    'route_setting_hard',
    'route_cleaning_easy',
    'route_cleaning_hard',
)


def format_supplement(activity: Activity) -> str:
    """Give the supplement of an activity as an amount, or nothing without one (R7.10)."""
    if not activity.supplement_amount:
        return ''
    return format_amount(amount=activity.supplement_amount)


def build_activity_row(
    activity: Activity,
    activity_labels: dict[str, str],
    with_cancelled: bool,
) -> dict[str, str]:
    """Build the table row of one activity; the cancelled column only in the overview."""
    row = {
        'Date': format_date(day=activity.activity_date),
        'Activité': activity_labels[activity.activity_type],
        'Description': activity.description or '',
        'Heures': format_decimal(value=activity.duration_hours),
        'Supplément': format_supplement(activity=activity),
        'Rémunération': format_amount(amount=activity.compensation_amount),
        'Dimona': DIMONA_STATUS_LABELS[activity.dimona_status],
    }
    if with_cancelled:
        row['Annulée'] = CANCELLED_LABEL if activity.is_cancelled else ''
    return row


def build_cancel_option(activity: Activity, activity_labels: dict[str, str]) -> str:
    """Build the line that names an activity in the "activity to cancel" list."""
    parts = [format_date(day=activity.activity_date), activity_labels[activity.activity_type]]
    if activity.description:
        parts.append(activity.description)
    return ' · '.join(parts)


def find_clearance_label(activity_type: str, activity_labels: dict[str, str]) -> str:
    """Give the clearance an activity type falls under: its own label unless it shares one."""
    if activity_type in COURSE_ACTIVITY_TYPES:
        return COURSE_CLEARANCE_LABEL
    if activity_type in ROUTE_ACTIVITY_TYPES:
        return ROUTE_CLEARANCE_LABEL
    return activity_labels[activity_type]


def build_covered_text(covered_types: list[str], activity_labels: dict[str, str]) -> str:
    """List what a document covers, each shared clearance named once (R7.13)."""
    names = []
    for activity_type in covered_types:
        name = find_clearance_label(activity_type=activity_type, activity_labels=activity_labels)
        if name not in names:
            names.append(name)
    return ', '.join(names)


def build_document_type_text(authorisation: Authorisation) -> str:
    """Name the kind of document, a contract with its worker type: Contrat (Article 17)."""
    document_type = DOCUMENT_TYPE_LABELS[authorisation.document_type]
    if authorisation.worker_type is None:
        return document_type
    type_label = WORKER_TYPE_LABELS[authorisation.worker_type]
    return f'{document_type} ({type_label})'


def build_authorisation_row(
    authorisation: Authorisation,
    activity_labels: dict[str, str],
    today: date,
) -> dict[str, str]:
    """Build the table row of one contract or qualification, marked when expired (R7.13)."""
    covered_text = build_covered_text(
        covered_types=authorisation.activity_types,
        activity_labels=activity_labels,
    )
    end_date = authorisation.end_date
    status = EXPIRED_LABEL if is_expired(authorisation=authorisation, today=today) else VALID_LABEL
    return {
        'Type': build_document_type_text(authorisation=authorisation),
        'Couvre': covered_text,
        'Début': format_date(day=authorisation.start_date),
        'Fin': format_date(day=end_date) if end_date is not None else '',
        'Statut': status,
        'Fichier': authorisation.original_filename,
    }


def build_document_option(authorisation: Authorisation, activity_labels: dict[str, str]) -> str:
    """Build the line that names a document in a list of documents."""
    covered_text = build_covered_text(
        covered_types=authorisation.activity_types,
        activity_labels=activity_labels,
    )
    document_type = build_document_type_text(authorisation=authorisation)
    parts = [document_type, covered_text, authorisation.original_filename]
    return ' · '.join(parts)
