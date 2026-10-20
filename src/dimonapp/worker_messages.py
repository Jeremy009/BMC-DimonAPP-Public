"""French messages of the worker view (R8.2, R17.4, R18.1).

Plain text builders, so the wording is tested without Streamlit.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from dimonapp.french import format_amount, format_date, format_hours
from dimonapp.models import CompensationModel, WorkerType
from dimonapp.worker_types import WORKER_TYPE_LABELS

# Each activity type as it reads inside a sentence, with the matching form of "payé".
ACTIVITY_PHRASES = {
    'permanence': ('la permanence', 'payée'),
    'courses': ('le cours BMC', 'payé'),
    'group_without_instructor': ('le cours groupe sans mono', 'payé'),
    'group_with_instructor': ('le cours groupe avec mono', 'payé'),
    'route_setting_easy': ("l'ouverture 4A - 5C", 'payée'),
    'route_setting_medium': ("l'ouverture 6A - 6C", 'payée'),
    'route_setting_hard': ("l'ouverture 7A et plus", 'payée'),
    'route_cleaning_easy': ('le démontage facile', 'payé'),
    'route_cleaning_hard': ('le démontage difficile', 'payé'),
}

NOT_REGISTERED_PREFIX = 'Activité non enregistrée : '
MISSING_DATE_MESSAGE = f"{NOT_REGISTERED_PREFIX}indiquez la date de l'activité."
PAST_DATE_MESSAGE = f"{NOT_REGISTERED_PREFIX}la date doit être aujourd'hui ou plus tard."
TOO_FAR_AHEAD_MESSAGE = (
    f"{NOT_REGISTERED_PREFIX}une activité se déclare au maximum 3 mois à l'avance."
)
MISSING_DURATION_MESSAGE = f"{NOT_REGISTERED_PREFIX}indiquez la durée de l'activité en heures."
MISSING_START_TIME_MESSAGE = (
    f"{NOT_REGISTERED_PREFIX}indiquez l'heure de début, à l'heure pile ou à la demi-heure."
)
WHOLE_HOURS_MESSAGE = f'{NOT_REGISTERED_PREFIX}la durée se déclare en heures entières.'
MISSING_DESCRIPTION_MESSAGE = (
    f"{NOT_REGISTERED_PREFIX}une description courte est obligatoire pour l'ouverture de voies."
)
SUPPLEMENT_ALREADY_DECLARED_MESSAGE = (
    f'{NOT_REGISTERED_PREFIX}le déplacement groupe est déjà déclaré pour ce jour. '
    'Il est payé au maximum une fois par jour.'
)
PENDING_DAY_MESSAGE = (
    f'{NOT_REGISTERED_PREFIX}une déclaration Dimona de ce jour est encore en attente. '
    "Réessayez quand un administrateur l'aura résolue."
)
PENDING_MESSAGE = (
    "Activité enregistrée EN ATTENTE : le service Dimona n'a pas répondu dans les 2 minutes. "
    'Un administrateur fera le suivi.'
)

CANCELLED_MESSAGE = 'Activité annulée.'
CANCELLED_WITH_DIMONA_MESSAGE = 'Activité annulée. Annulation confirmée par le service Dimona.'
CANCELLED_WITH_DIMONA_UPDATE_MESSAGE = (
    'Activité annulée. Le service Dimona a confirmé les heures restantes du jour.'
)
CANCELLATION_PENDING_DAY_MESSAGE = (
    'Activité non annulée : une déclaration Dimona de ce jour est encore en attente. '
    "Réessayez quand un administrateur l'aura résolue."
)
NO_DECLARATION_ID_MESSAGE = (
    "Activité non annulée : elle n'a pas d'identifiant de déclaration Dimona. "
    'Contactez un administrateur BMC.'
)
NO_ACTIVITY_CHOSEN_MESSAGE = "Activité non annulée : choisissez l'activité à annuler."
CANCELLATION_NO_ANSWER_MESSAGE = (
    "Activité non annulée : le service Dimona n'a pas répondu dans les 2 minutes. "
    "L'activité reste active."
)


def build_model_caption(activity_type: str, compensation_model: CompensationModel) -> str:
    """Explain under the create form how the chosen activity type is paid."""
    phrase, paid = ACTIVITY_PHRASES[activity_type]
    subject = phrase[0].upper() + phrase[1:]
    if compensation_model == CompensationModel.FIXED:
        return (
            f'{subject} est {paid} à prix fixe par activité. '
            'Les heures sont enregistrées mais ne changent pas la rémunération.'
        )
    return f"{subject} est {paid} à l'heure : le tarif horaire multiplié par les heures saisies."


def build_flexi_too_far_message(latest_date: date) -> str:
    """Tell a flexi-jobber that the RSZ does not take a declaration for that quarter yet (R7.16)."""
    formatted_date = format_date(day=latest_date)
    return (
        f'{NOT_REGISTERED_PREFIX}une activité Flexijob se déclare au plus tôt un mois avant le '
        f"début de son trimestre. Aujourd'hui, la date peut aller jusqu'au {formatted_date}."
    )


def build_min_hours_message(min_hours: Decimal) -> str:
    """Tell a flexi-jobber that the activity is shorter than the configured minimum (R7.7)."""
    formatted_hours = format_hours(hours=min_hours)
    return f'{NOT_REGISTERED_PREFIX}une activité Flexijob dure au minimum {formatted_hours}.'


def build_no_contract_message(
    worker_type: WorkerType,
    activity_type: str,
    activity_date: date,
) -> str:
    """Name the failed contract check, with the worker type the contract must have (R8.2)."""
    type_label = WORKER_TYPE_LABELS[worker_type]
    phrase, _ = ACTIVITY_PHRASES[activity_type]
    formatted_date = format_date(day=activity_date)
    return (
        f'{NOT_REGISTERED_PREFIX}aucun contrat {type_label} valide ne couvre {phrase} '
        f'le {formatted_date}.'
    )


def build_no_qualification_message(activity_type: str, activity_date: date) -> str:
    """Name the failed qualification check (R8.2)."""
    phrase, _ = ACTIVITY_PHRASES[activity_type]
    formatted_date = format_date(day=activity_date)
    return (
        f'{NOT_REGISTERED_PREFIX}aucune qualification valide ne couvre {phrase} '
        f'le {formatted_date}.'
    )


def build_confirmed_message(amount: Decimal) -> str:
    """Confirm an activity that needs no Dimona declaration (R8.4)."""
    return f'Activité confirmée. Rémunération : {format_amount(amount=amount)}'


def build_accepted_message(declaration_id: Optional[str], amount: Decimal) -> str:
    """Confirm an activity whose Dimona declaration was accepted (R8.6)."""
    formatted_amount = format_amount(amount=amount)
    return (
        f'Activité confirmée. Déclaration Dimona acceptée (ID {declaration_id}). '
        f'Rémunération : {formatted_amount}'
    )


def build_rejected_message(reason: Optional[str]) -> str:
    """Report a rejected Dimona declaration with the reason of the service (R8.7)."""
    shown_reason = reason or 'aucune raison communiquée'
    return f'Déclaration Dimona refusée : {shown_reason}. Activité enregistrée comme refusée.'


def build_cancellation_refused_message(reason: Optional[str]) -> str:
    """Report a cancellation the Dimona service refused or could not handle (R9.4)."""
    shown_reason = reason or 'aucune raison communiquée'
    return (
        f"Activité non annulée : le service Dimona a refusé l'annulation ({shown_reason}). "
        "L'activité reste active."
    )
