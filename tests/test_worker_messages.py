"""French messages of the worker view, as in the mockups (R8.2, R17.4, R18.1)."""

from datetime import date
from decimal import Decimal

from dimonapp import worker_messages
from dimonapp.models import ACTIVITY_TYPE_CODES, CompensationModel, WorkerType


def test_r8_6_accepted_message_matches_the_mockup() -> None:
    """Mockup 02: the declaration ID and the compensation in French format."""
    message = worker_messages.build_accepted_message(
        declaration_id='2026-10-DIM-0048213',
        amount=Decimal('40'),
    )

    expected = (
        'Activité confirmée. Déclaration Dimona acceptée (ID 2026-10-DIM-0048213). '
        'Rémunération : 40,00 €'
    )
    assert message == expected


def test_r8_2_no_contract_message_names_the_worker_type() -> None:
    """Mockup 03, with the worker type the contract must have added to it (R12.10)."""
    message = worker_messages.build_no_contract_message(
        worker_type=WorkerType.ARTICLE_17,
        activity_type='route_setting_medium',
        activity_date=date(2026, 10, 10),
    )

    expected = (
        'Activité non enregistrée : aucun contrat Article 17 valide ne couvre '
        "l'ouverture 6A - 6C le 10/10/2026."
    )
    assert message == expected


def test_r8_2_no_qualification_message_names_the_check() -> None:
    """The qualification check has its own message."""
    message = worker_messages.build_no_qualification_message(
        activity_type='courses',
        activity_date=date(2026, 10, 10),
    )

    expected = (
        'Activité non enregistrée : aucune qualification valide ne couvre le cours BMC '
        'le 10/10/2026.'
    )
    assert message == expected


def test_r8_8_pending_message_matches_the_mockup() -> None:
    """Mockup 04: the warning of a declaration without answer."""
    expected = (
        "Activité enregistrée EN ATTENTE : le service Dimona n'a pas répondu dans les 2 minutes. "
        'Un administrateur fera le suivi.'
    )
    assert worker_messages.PENDING_MESSAGE == expected


def test_r8_7_rejected_message_gives_the_reason_of_the_service() -> None:
    """The reason returned by the Dimona service is shown to the worker."""
    message = worker_messages.build_rejected_message(reason='travailleur inconnu')

    assert 'travailleur inconnu' in message
    assert message.startswith('Déclaration Dimona refusée')


def test_r7_7_min_hours_message_gives_the_configured_minimum() -> None:
    """The minimum comes in as an argument and is shown in French format."""
    message = worker_messages.build_min_hours_message(min_hours=Decimal('3.5'))

    assert message == 'Activité non enregistrée : une activité Flexijob dure au minimum 3,5 h.'


def test_r7_5_fixed_price_caption_matches_the_mockup() -> None:
    """Mockup 02: the hours of a fixed-price activity are recorded but do not change the pay."""
    caption = worker_messages.build_model_caption(
        activity_type='route_setting_medium',
        compensation_model=CompensationModel.FIXED,
    )

    expected = (
        "L'ouverture 6A - 6C est payée à prix fixe par activité. "
        'Les heures sont enregistrées mais ne changent pas la rémunération.'
    )
    assert caption == expected


def test_r7_5_hourly_caption_says_the_hours_count() -> None:
    """An hourly activity is paid by the hours entered."""
    caption = worker_messages.build_model_caption(
        activity_type='courses',
        compensation_model=CompensationModel.HOURLY,
    )

    assert (
        caption
        == "Le cours BMC est payé à l'heure : le tarif horaire multiplié par les heures saisies."
    )


def test_r6_1_every_activity_type_has_a_phrase() -> None:
    """All nine activity types can be named in a message."""
    assert set(worker_messages.ACTIVITY_PHRASES) == set(ACTIVITY_TYPE_CODES)
