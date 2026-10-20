"""The cancellation flow (FDS section 9). The Dimona service is always the fake (R1.11)."""

from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy.orm import Session

from dimonapp.cancellation import cancel_activity
from dimonapp.dimona import FakeDimonaClient
from dimonapp.models import Activity, DimonaStatus, WorkerType
from factories import build_activity, build_worker


def save_activity(
    session: Session,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    dimona_status: DimonaStatus = DimonaStatus.OK,
    dimona_declaration_id: Optional[str] = '123456',
    is_cancelled: bool = False,
) -> Activity:
    """Store a worker with one activity."""
    worker = build_worker(worker_type=worker_type)
    session.add(worker)
    session.flush()
    activity = build_activity(
        worker_id=worker.id,
        worker_type=worker_type,
        dimona_status=dimona_status,
        dimona_declaration_id=dimona_declaration_id,
        is_cancelled=is_cancelled,
    )
    session.add(activity)
    session.flush()
    return activity


@pytest.mark.parametrize('worker_type', [WorkerType.VRIJWILLIGER, WorkerType.FREELANCER])
def test_r9_1_activity_without_dimona_is_cancelled_at_once(
    session: Session,
    worker_type: WorkerType,
) -> None:
    """Volunteer and freelancer activities are cancelled without any Dimona call."""
    activity = save_activity(
        session=session,
        worker_type=worker_type,
        dimona_status=DimonaStatus.NOT_APPLICABLE,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='reject')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'cancelled'
    assert result.level == 'success'
    assert result.message == 'Activité annulée.'
    assert activity.is_cancelled is True
    assert client.cancelled_declaration_ids == []


@pytest.mark.parametrize('dimona_status', [DimonaStatus.REJECTED, DimonaStatus.PENDING])
def test_r9_2_no_declaration_id_stops_with_a_warning(
    session: Session,
    dimona_status: DimonaStatus,
) -> None:
    """A rejected or pending declaration has no ID: warning, no API call, still active."""
    activity = save_activity(
        session=session,
        dimona_status=dimona_status,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='accept')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'no_declaration_id'
    assert result.level == 'warning'
    assert "pas d'identifiant de déclaration Dimona" in result.message
    assert activity.is_cancelled is False
    assert client.cancelled_declaration_ids == []


def test_r9_4_confirmed_cancellation_marks_the_activity(session: Session) -> None:
    """With a declaration ID the service is asked, and its confirmation cancels the activity."""
    activity = save_activity(session=session)
    client = FakeDimonaClient(outcome='accept')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'cancelled'
    assert result.level == 'success'
    assert result.message == 'Activité annulée. Annulation confirmée par le service Dimona.'
    assert activity.is_cancelled is True
    assert client.cancelled_declaration_ids == ['123456']


@pytest.mark.parametrize(
    ('fake_outcome', 'expected_outcome'),
    [('reject', 'refused'), ('timeout', 'no_answer')],
)
def test_r9_4_activity_stays_active_without_confirmation(
    session: Session,
    fake_outcome: str,
    expected_outcome: str,
) -> None:
    """A refusal or two minutes without answer: a warning and the activity stays active."""
    activity = save_activity(session=session)
    client = FakeDimonaClient(outcome=fake_outcome)

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == expected_outcome
    assert result.level == 'warning'
    assert result.message.startswith('Activité non annulée')
    assert result.message.endswith("L'activité reste active.")
    assert activity.is_cancelled is False


def test_r9_5_cancellation_only_sets_the_marker(session: Session) -> None:
    """Every other field of the activity is the same after cancelling, and the row remains."""
    activity = save_activity(session=session)
    activity_id = activity.id
    client = FakeDimonaClient(outcome='accept')

    cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity_id,
    )
    session.expire_all()

    stored = session.get(Activity, activity_id)
    assert stored.is_cancelled is True
    assert stored.dimona_status == DimonaStatus.OK
    assert stored.dimona_declaration_id == '123456'
    assert stored.compensation_amount == Decimal('30.00')
    assert stored.duration_hours == Decimal('2.00')


def test_r7_2_worker_cannot_cancel_someone_else_s_activity(session: Session) -> None:
    """An activity of another worker is refused and stays active."""
    activity = save_activity(session=session)
    client = FakeDimonaClient(outcome='accept')

    with pytest.raises(ValueError):
        cancel_activity(
            session=session,
            dimona_client=client,
            worker_id=activity.worker_id + 1,
            activity_id=activity.id,
        )
    assert activity.is_cancelled is False
    assert client.cancelled_declaration_ids == []


def test_r7_9_cancelled_activity_cannot_be_cancelled_again(session: Session) -> None:
    """Only non-cancelled activities can be cancelled; no second Dimona call is made."""
    activity = save_activity(session=session, is_cancelled=True)
    client = FakeDimonaClient(outcome='accept')

    with pytest.raises(ValueError):
        cancel_activity(
            session=session,
            dimona_client=client,
            worker_id=activity.worker_id,
            activity_id=activity.id,
        )
    assert client.cancelled_declaration_ids == []


def save_day_activity(
    session: Session,
    worker_id: int,
    duration_hours: Decimal = Decimal('2'),
    dimona_status: DimonaStatus = DimonaStatus.OK,
    dimona_declaration_id: Optional[str] = '222',
    is_cancelled: bool = False,
) -> Activity:
    """Store another article 17 activity of the worker on the day of save_activity."""
    activity = build_activity(
        worker_id=worker_id,
        duration_hours=duration_hours,
        dimona_status=dimona_status,
        dimona_declaration_id=dimona_declaration_id,
        is_cancelled=is_cancelled,
    )
    session.add(activity)
    session.flush()
    return activity


def test_r9_6_cancelling_with_others_left_lowers_the_hours_of_the_day(session: Session) -> None:
    """The period keeps the hours of the remaining accepted activities and is not cancelled."""
    activity = save_activity(session=session)
    save_day_activity(session=session, worker_id=activity.worker_id, duration_hours=Decimal('3'))
    client = FakeDimonaClient(outcome='accept')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'cancelled'
    assert result.level == 'success'
    assert result.message == (
        'Activité annulée. Le service Dimona a confirmé les heures restantes du jour.'
    )
    assert activity.is_cancelled is True
    assert client.hour_updates == [('123456', 3)]
    assert client.cancelled_declaration_ids == []


def test_r9_6_last_accepted_activity_of_the_day_cancels_the_period(session: Session) -> None:
    """Cancelled and rejected activities of the day hold no hours: the period is cancelled."""
    activity = save_activity(session=session)
    worker_id = activity.worker_id
    save_day_activity(session=session, worker_id=worker_id, is_cancelled=True)
    save_day_activity(
        session=session,
        worker_id=worker_id,
        dimona_status=DimonaStatus.REJECTED,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='accept')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'cancelled'
    assert client.cancelled_declaration_ids == ['123456']
    assert client.hour_updates == []


@pytest.mark.parametrize(
    ('fake_outcome', 'expected_outcome'),
    [('reject', 'refused'), ('timeout', 'no_answer')],
)
def test_r9_6_activity_stays_active_without_a_confirmed_update(
    session: Session,
    fake_outcome: str,
    expected_outcome: str,
) -> None:
    """A refused or unanswered update leaves the activity active, with a warning (R9.4)."""
    activity = save_activity(session=session)
    save_day_activity(session=session, worker_id=activity.worker_id)
    client = FakeDimonaClient(outcome=fake_outcome)

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == expected_outcome
    assert result.level == 'warning'
    assert result.message.endswith("L'activité reste active.")
    assert activity.is_cancelled is False


def test_r9_6_flexi_job_cancels_its_own_period(session: Session) -> None:
    """Flexi-job activities each have their own period, whatever else happens that day."""
    activity = save_activity(session=session, worker_type=WorkerType.FLEXI_JOB)
    other_activity = build_activity(
        worker_id=activity.worker_id,
        worker_type=WorkerType.FLEXI_JOB,
        dimona_declaration_id='222',
    )
    session.add(other_activity)
    session.flush()
    client = FakeDimonaClient(outcome='accept')

    cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert client.cancelled_declaration_ids == ['123456']
    assert client.hour_updates == []


def test_r9_7_pending_declaration_that_day_stops_the_cancellation(session: Session) -> None:
    """While the hours at the RSZ are unknown, nothing is sent and the activity stays active."""
    activity = save_activity(session=session)
    save_day_activity(
        session=session,
        worker_id=activity.worker_id,
        dimona_status=DimonaStatus.PENDING,
        dimona_declaration_id=None,
    )
    client = FakeDimonaClient(outcome='accept')

    result = cancel_activity(
        session=session,
        dimona_client=client,
        worker_id=activity.worker_id,
        activity_id=activity.id,
    )

    assert result.outcome == 'pending_day'
    assert result.level == 'warning'
    assert result.message == (
        'Activité non annulée : une déclaration Dimona de ce jour est encore en attente. '
        "Réessayez quand un administrateur l'aura résolue."
    )
    assert activity.is_cancelled is False
    assert client.cancelled_declaration_ids == []
    assert client.hour_updates == []
