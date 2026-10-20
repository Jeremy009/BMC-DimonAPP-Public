"""Rows of the worker view tables (R7.9, R7.10, R7.13, R18.1)."""

from datetime import date
from decimal import Decimal

from dimonapp.models import DimonaStatus, DocumentType, WorkerType
from dimonapp.worker_tables import (
    build_activity_row,
    build_authorisation_row,
    build_cancel_option,
)
from factories import build_activity, build_authorisation

ACTIVITY_LABELS = {
    'permanence': 'Permanence',
    'courses': 'Cours BMC',
    'route_setting_easy': 'Ouverture 4A - 5C',
    'route_setting_medium': 'Ouverture 6A - 6C',
    'route_setting_hard': 'Ouverture 7A et plus',
    'route_cleaning_easy': 'Démontage facile',
    'route_cleaning_hard': 'Démontage difficile (cordes 9 à 14)',
}
TODAY = date(2026, 10, 10)


def test_r7_10_overview_row_shows_every_column_in_french() -> None:
    """Date, type, description, duration, compensation, Dimona status and cancelled flag."""
    activity = build_activity(
        activity_date=date(2026, 10, 7),
        duration_hours=Decimal('2.50'),
        compensation_amount=Decimal('1234.5'),
        dimona_status=DimonaStatus.PENDING,
        is_cancelled=True,
        description='Groupe enfants',
    )

    row = build_activity_row(
        activity=activity,
        activity_labels=ACTIVITY_LABELS,
        with_cancelled=True,
    )

    assert row == {
        'Date': '07/10/2026',
        'Activité': 'Cours BMC',
        'Description': 'Groupe enfants',
        'Heures': '2,5',
        'Supplément': '',
        'Rémunération': '1 234,50 €',
        'Dimona': 'En attente',
        'Annulée': 'Annulée',
    }


def test_r7_10_dimona_statuses_have_french_labels() -> None:
    """OK, En attente, Refusée and Non applicable (FDS 3.4)."""
    labels = {}
    for dimona_status in DimonaStatus:
        activity = build_activity(dimona_status=dimona_status)
        row = build_activity_row(
            activity=activity,
            activity_labels=ACTIVITY_LABELS,
            with_cancelled=True,
        )
        labels[dimona_status] = row['Dimona']
        assert row['Annulée'] == ''

    assert labels == {
        DimonaStatus.NOT_APPLICABLE: 'Non applicable',
        DimonaStatus.OK: 'OK',
        DimonaStatus.REJECTED: 'Refusée',
        DimonaStatus.PENDING: 'En attente',
    }


def test_r7_9_cancel_row_has_no_cancelled_column() -> None:
    """The cancel list only holds non-cancelled activities, so the flag is left out."""
    row = build_activity_row(
        activity=build_activity(),
        activity_labels=ACTIVITY_LABELS,
        with_cancelled=False,
    )

    assert list(row) == [
        'Date',
        'Activité',
        'Description',
        'Heures',
        'Supplément',
        'Rémunération',
        'Dimona',
    ]


def test_r7_9_cancel_option_names_the_activity() -> None:
    """Date, type and description, as in mockup 05; the description only when there is one."""
    with_description = build_activity(
        activity_date=date(2026, 10, 14), description='Groupe enfants'
    )
    without_description = build_activity(activity_date=date(2026, 10, 14))

    first_option = build_cancel_option(activity=with_description, activity_labels=ACTIVITY_LABELS)
    second_option = build_cancel_option(
        activity=without_description,
        activity_labels=ACTIVITY_LABELS,
    )

    assert first_option == '14/10/2026 · Cours BMC · Groupe enfants'
    assert second_option == '14/10/2026 · Cours BMC'


def test_r7_13_valid_document_row() -> None:
    """A running qualification without end date: every covered activity, an empty end date."""
    authorisation = build_authorisation(
        document_type=DocumentType.QUALIFICATION,
        activity_types=('courses', 'group_with_instructor', 'permanence'),
        start_date=date(2024, 3, 15),
    )

    row = build_authorisation_row(
        authorisation=authorisation,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )

    assert row == {
        'Type': 'Qualification',
        'Couvre': 'Cours, Permanence',
        'Début': '15/03/2024',
        'Fin': '',
        'Statut': 'Valide',
        'Fichier': 'document.pdf',
    }


def test_r7_13_expired_document_is_marked() -> None:
    """A contract that ended before today is shown as expired; ending today is still valid."""
    expired = build_authorisation(start_date=date(2025, 9, 1), end_date=date(2026, 10, 9))
    last_day = build_authorisation(start_date=date(2025, 9, 1), end_date=TODAY)

    expired_row = build_authorisation_row(
        authorisation=expired,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )
    last_day_row = build_authorisation_row(
        authorisation=last_day,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )

    assert expired_row['Type'] == 'Contrat (Article 17)'
    assert expired_row['Fin'] == '09/10/2026'
    assert expired_row['Statut'] == 'Expiré'
    assert last_day_row['Statut'] == 'Valide'


def test_r7_13_route_setting_and_cleaning_are_named_once() -> None:
    """Route setting and cleaning in every difficulty are one clearance, named once."""
    authorisation = build_authorisation(
        activity_types=(
            'courses',
            'route_setting_easy',
            'route_setting_medium',
            'route_setting_hard',
            'route_cleaning_easy',
            'route_cleaning_hard',
        ),
    )

    row = build_authorisation_row(
        authorisation=authorisation,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )

    assert row['Couvre'] == 'Cours, Ouverture de voies'


def test_r7_13_any_route_type_shows_the_route_clearance() -> None:
    """The clearance is route setting as a whole, whichever of its types the document lists."""
    authorisation = build_authorisation(activity_types=('route_cleaning_easy', 'permanence'))

    row = build_authorisation_row(
        authorisation=authorisation,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )

    assert row['Couvre'] == 'Ouverture de voies, Permanence'


def test_r7_10_overview_row_shows_the_supplement_of_an_activity() -> None:
    """The supplement has a column of its own; the compensation includes it (R6.10)."""
    activity = build_activity(
        activity_type='courses',
        compensation_amount=Decimal('65'),
        supplement_amount=Decimal('25'),
    )

    row = build_activity_row(
        activity=activity,
        activity_labels=ACTIVITY_LABELS,
        with_cancelled=False,
    )

    assert row['Supplément'] == '25,00 €'
    assert row['Rémunération'] == '65,00 €'


def test_r7_13_contract_is_named_with_its_worker_type() -> None:
    """A contract shows the worker type it belongs to, a qualification has none (R12.10)."""
    contract = build_authorisation(worker_type=WorkerType.FLEXI_JOB)
    qualification = build_authorisation(document_type=DocumentType.QUALIFICATION)

    contract_row = build_authorisation_row(
        authorisation=contract,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )
    qualification_row = build_authorisation_row(
        authorisation=qualification,
        activity_labels=ACTIVITY_LABELS,
        today=TODAY,
    )

    assert contract_row['Type'] == 'Contrat (Flexijob)'
    assert qualification_row['Type'] == 'Qualification'
