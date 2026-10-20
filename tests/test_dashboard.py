"""The admin dashboard: cost, alerts and the resolution of pending declarations (R10.2 to R10.7)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from dimonapp import dashboard
from dimonapp.compliance import LimitFlag
from dimonapp.dashboard import (
    build_dashboard,
    build_limit_alert,
    build_missing_limits_alert,
    find_expiring_contracts,
    load_dashboard,
    resolve_pending_activity,
    sum_month_cost,
)
from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import Activity, DimonaStatus, DocumentType, Period, WorkerType
from factories import (
    build_activity,
    build_authorisation,
    build_complete_limits,
    build_worker,
)

TODAY = date(2026, 10, 10)
LABELS = {'courses': 'Cours BMC', 'permanence': 'Permanence'}


def test_r10_2_month_cost_sums_counted_activities_of_the_month() -> None:
    """Planned activities count; cancelled, rejected and other months do not (R17.2)."""
    activities = [
        build_activity(activity_date=date(2026, 10, 1), compensation_amount=Decimal('100')),
        build_activity(activity_date=date(2026, 10, 31), compensation_amount=Decimal('50.50')),
        build_activity(worker_id=2, activity_date=date(2026, 10, 15)),
        build_activity(activity_date=date(2026, 10, 12), is_cancelled=True),
        build_activity(activity_date=date(2026, 10, 12), dimona_status=DimonaStatus.REJECTED),
        build_activity(activity_date=date(2026, 9, 30)),
        build_activity(activity_date=date(2026, 11, 1)),
    ]

    cost = sum_month_cost(activities=activities, month_start=date(2026, 10, 1))

    assert cost == Decimal('180.50')


def test_r10_3_limit_alert_names_worker_totals_and_period() -> None:
    """Hours and euro alerts read as in the mockup, in French format."""
    hours_flag = LimitFlag(
        worker_id=1,
        worker_type=WorkerType.ARTICLE_17,
        year=2026,
        period=Period.Q4,
        quantity='hours',
        total=Decimal('141.00'),
        limit=Decimal('150.00'),
    )
    euro_flag = LimitFlag(
        worker_id=1,
        worker_type=WorkerType.ARTICLE_17,
        year=2026,
        period=Period.YEAR,
        quantity='euro',
        total=Decimal('7310'),
        limit=Decimal('7700'),
    )

    hours_alert = build_limit_alert(flag=hours_flag, worker_name='Youssef El Amrani')
    euro_alert = build_limit_alert(flag=euro_flag, worker_name='Lotte Peeters')

    assert hours_alert == (
        '**Youssef El Amrani** (Article 17) : 141 des 150 heures utilisées au T4 2026.'
    )
    assert euro_alert == (
        f'**Lotte Peeters** (Article 17) : 7{NO_BREAK_SPACE}310,00{NO_BREAK_SPACE}€ des '
        f'7{NO_BREAK_SPACE}700,00{NO_BREAK_SPACE}€ de rémunération annuelle utilisés en 2026.'
    )


def test_r10_3_dashboard_flags_a_worker_at_90_percent() -> None:
    """A worker at 90% of a limit gets one alert; the others none."""
    workers = [build_worker(worker_id=1, first_name='Lotte', last_name='Peeters')]
    limits = build_complete_limits(year=2026)
    limits[1].hours_limit = Decimal('100')
    activities = [build_activity(duration_hours=Decimal('90'))]

    result = build_dashboard(
        workers=workers,
        activities=activities,
        limits=limits,
        authorisations=[],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert result.limit_alerts == [
        '**Lotte Peeters** (Article 17) : 90 des 100 heures utilisées en 2026.'
    ]
    assert result.missing_limit_alerts == []


def test_r10_3_flags_of_past_years_are_not_shown() -> None:
    """Only the current year and later years are shown; next year's planned work still is."""
    workers = [build_worker(worker_id=1, first_name='Lotte', last_name='Peeters')]
    limits = []
    for year in (2025, 2026, 2027):
        year_limits = build_complete_limits(year=year)
        year_limits[1].hours_limit = Decimal('100')
        limits.extend(year_limits)
    activities = [
        build_activity(activity_date=date(2025, 5, 10), duration_hours=Decimal('95')),
        build_activity(activity_date=date(2027, 1, 10), duration_hours=Decimal('95')),
    ]

    result = build_dashboard(
        workers=workers,
        activities=activities,
        limits=limits,
        authorisations=[],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert result.limit_alerts == [
        '**Lotte Peeters** (Article 17) : 95 des 100 heures utilisées en 2027.'
    ]


def test_r10_4_every_pending_activity_is_listed() -> None:
    """Only pending declarations are listed, with worker, activity and date."""
    workers = [build_worker(worker_id=1, first_name='Lotte', last_name='Peeters')]
    pending = build_activity(
        activity_date=date(2026, 10, 21),
        dimona_status=DimonaStatus.PENDING,
    )
    pending.id = 7
    accepted = build_activity(activity_date=date(2026, 10, 22))
    accepted.id = 8

    result = build_dashboard(
        workers=workers,
        activities=[accepted, pending],
        limits=build_complete_limits(year=2026),
        authorisations=[],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert [alert.activity_id for alert in result.pending_alerts] == [7]
    assert result.pending_alerts[0].message == (
        '**Dimona en attente** : Lotte Peeters, Cours BMC le 21/10/2026, pas de réponse de Dimona. '
        'Vérifiez sur le portail ONSS, puis résolvez ci-dessous.'
    )


def test_r10_4_pending_alert_shows_the_message_of_the_service() -> None:
    """What the Dimona service said, such as the number it gave, helps the admin."""
    workers = [build_worker(worker_id=1)]
    pending = build_activity(dimona_status=DimonaStatus.PENDING)
    pending.id = 7
    pending.dimona_message = 'Déclaration 123 reçue, pas encore traitée.'

    result = build_dashboard(
        workers=workers,
        activities=[pending],
        limits=[],
        authorisations=[],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert result.pending_alerts[0].message.endswith(
        'Message du service Dimona : Déclaration 123 reçue, pas encore traitée.'
    )


def save_pending_activity(session: Session) -> int:
    """Store a worker with one pending activity and give the activity id."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    activity = build_activity(worker_id=worker.id, dimona_status=DimonaStatus.PENDING)
    session.add(activity)
    session.flush()
    return activity.id


def test_r10_5_pending_activity_is_resolved_as_ok_with_the_declaration_id(
    session: Session,
) -> None:
    """Marked ok, the activity holds the declaration ID and leaves the pending list."""
    activity_id = save_pending_activity(session=session)

    result = resolve_pending_activity(
        session=session,
        activity_id=activity_id,
        resolution='ok',
        declaration_id=' 2026-10-DIM-0048390 ',
    )

    board = load_dashboard(session=session, activity_labels=LABELS, today=TODAY)
    session.expire_all()
    activity = session.get(Activity, activity_id)
    assert result.level == 'success'
    assert result.message == dashboard.RESOLVED_OK_MESSAGE
    assert activity.dimona_status == DimonaStatus.OK
    assert activity.dimona_declaration_id == '2026-10-DIM-0048390'
    assert board.pending_alerts == []


def test_r10_5_ok_without_declaration_id_is_refused(session: Session) -> None:
    """Never assume an outcome: ok needs the ID found on the RSZ portal."""
    activity_id = save_pending_activity(session=session)

    result = resolve_pending_activity(
        session=session,
        activity_id=activity_id,
        resolution='ok',
        declaration_id='  ',
    )

    board = load_dashboard(session=session, activity_labels=LABELS, today=TODAY)
    assert result.level == 'error'
    assert result.message == dashboard.MISSING_DECLARATION_ID_MESSAGE
    assert len(board.pending_alerts) == 1


def test_r10_5_pending_activity_is_resolved_as_rejected(session: Session) -> None:
    """Marked rejected, the activity no longer counts and has no declaration ID."""
    activity_id = save_pending_activity(session=session)

    result = resolve_pending_activity(
        session=session,
        activity_id=activity_id,
        resolution='rejected',
        declaration_id='ignored',
    )

    board = load_dashboard(session=session, activity_labels=LABELS, today=TODAY)
    assert result.message == dashboard.RESOLVED_REJECTED_MESSAGE
    assert board.pending_alerts == []
    assert board.month_cost == Decimal('0')


def test_r17_1_resolved_activity_cannot_be_resolved_again(session: Session) -> None:
    """A pending status is resolved once."""
    activity_id = save_pending_activity(session=session)
    resolve_pending_activity(
        session=session,
        activity_id=activity_id,
        resolution='rejected',
        declaration_id='',
    )

    result = resolve_pending_activity(
        session=session,
        activity_id=activity_id,
        resolution='ok',
        declaration_id='123',
    )

    assert result.level == 'error'
    assert result.message == dashboard.ALREADY_RESOLVED_MESSAGE


def test_r10_6_year_without_complete_limits_is_announced() -> None:
    """The warning names the year and counts its counted activities."""
    workers = [build_worker(worker_id=1)]
    activities = [
        build_activity(activity_date=date(2026, 5, 1)),
        build_activity(activity_date=date(2027, 1, 5)),
        build_activity(activity_date=date(2027, 1, 6)),
        build_activity(activity_date=date(2027, 1, 7), is_cancelled=True),
    ]

    result = build_dashboard(
        workers=workers,
        activities=activities,
        limits=build_complete_limits(year=2026),
        authorisations=[],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert result.missing_limit_alerts == [
        '**Aucune limite configurée pour 2027** : 2 activités comptabilisées tombent en 2027. '
        'Encodez les limites 2027 dans Configuration.'
    ]


def test_r10_6_single_activity_reads_in_the_singular() -> None:
    """One activity is not "activités"."""
    alert = build_missing_limits_alert(year=2027, n_activities=1)

    assert '1 activité comptabilisée tombe en 2027' in alert


@pytest.mark.parametrize(
    ('n_days', 'is_listed'),
    [(-1, False), (0, True), (30, True), (31, False)],
)
def test_r10_7_contract_ending_within_30_days_is_listed(n_days: int, is_listed: bool) -> None:
    """From today up to and including 30 days ahead; an ended contract is not "ending"."""
    workers = [build_worker(worker_id=1)]
    contract = build_authorisation(end_date=TODAY + timedelta(days=n_days))

    expiring = find_expiring_contracts(workers=workers, authorisations=[contract], today=TODAY)

    assert (expiring == [contract]) is is_listed


def test_r10_7_only_ending_contracts_of_active_workers_are_listed() -> None:
    """No end date, a qualification or an inactive worker never triggers the warning."""
    workers = [build_worker(worker_id=1), build_worker(worker_id=2, is_active=False)]
    end_date = TODAY + timedelta(days=10)
    without_end = build_authorisation(end_date=None)
    qualification = build_authorisation(
        document_type=DocumentType.QUALIFICATION,
        end_date=end_date,
    )
    of_inactive_worker = build_authorisation(end_date=end_date, worker_id=2)
    authorisations = [without_end, qualification, of_inactive_worker]

    expiring = find_expiring_contracts(workers=workers, authorisations=authorisations, today=TODAY)

    assert expiring == []


def test_r10_7_ending_contract_of_a_former_worker_type_is_not_listed() -> None:
    """Only a contract of the worker's current type lets the worker declare (R12.10)."""
    workers = [build_worker(worker_id=1, worker_type=WorkerType.FLEXI_JOB)]
    end_date = TODAY + timedelta(days=10)
    former = build_authorisation(end_date=end_date, worker_type=WorkerType.ARTICLE_17)
    current = build_authorisation(end_date=end_date, worker_type=WorkerType.FLEXI_JOB)

    expiring = find_expiring_contracts(
        workers=workers, authorisations=[former, current], today=TODAY
    )

    assert expiring == [current]


def test_r10_7_expiring_contract_alert_gives_end_date_and_covered_activities() -> None:
    """The alert reads as in the mockup, soonest first."""
    workers = [build_worker(worker_id=1, first_name='Youssef', last_name='El Amrani')]
    later = build_authorisation(activity_types=('permanence',), end_date=date(2026, 11, 6))
    sooner = build_authorisation(
        activity_types=('permanence', 'courses'),
        end_date=date(2026, 10, 31),
    )

    result = build_dashboard(
        workers=workers,
        activities=[],
        limits=[],
        authorisations=[later, sooner],
        activity_labels=LABELS,
        today=TODAY,
    )

    assert result.expiring_contract_alerts == [
        '**Contrat bientôt échu** : Youssef El Amrani, contrat Article 17 pour Permanence, Cours '
        'se termine le 31/10/2026 (dans 21 jours).',
        '**Contrat bientôt échu** : Youssef El Amrani, contrat Article 17 pour Permanence '
        'se termine le 06/11/2026 (dans 27 jours).',
    ]
    assert result.n_active_workers == 1
