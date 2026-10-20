"""Activities are immutable in the database (R17.1)."""

from datetime import date, time
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.models import Activity, DimonaStatus, WorkerType
from factories import build_activity, build_worker


def save_activity(session: Session, dimona_status: DimonaStatus = DimonaStatus.OK) -> Activity:
    """Store a worker with one activity."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    activity = build_activity(worker_id=worker.id, dimona_status=dimona_status)
    session.add(activity)
    session.flush()
    return activity


@pytest.mark.parametrize(
    ('field', 'new_value'),
    [
        ('compensation_amount', Decimal('999')),
        ('rate_applied', Decimal('99')),
        ('supplement_amount', Decimal('25')),
        ('duration_hours', Decimal('8')),
        ('activity_date', date(2030, 1, 1)),
        ('activity_type', 'permanence'),
        ('worker_type', WorkerType.FLEXI_JOB),
        ('description', 'changed'),
        ('start_time', time(hour=9)),
    ],
)
def test_r17_1_declared_data_cannot_change(session: Session, field: str, new_value: object) -> None:
    """Every field copied or entered at declaration is refused by the database."""
    activity = save_activity(session=session)

    setattr(activity, field, new_value)

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_r17_1_activity_cannot_be_deleted(session: Session) -> None:
    """History is kept: a delete is refused."""
    activity = save_activity(session=session)

    session.delete(activity)

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()


def test_r17_1_cancellation_marker_can_change(session: Session) -> None:
    """Cancelling only sets the marker and leaves the rest untouched."""
    activity = save_activity(session=session)

    activity.is_cancelled = True
    session.flush()
    session.expire_all()

    assert activity.is_cancelled is True
    assert activity.compensation_amount == Decimal('30.00')


def test_r17_1_pending_declaration_can_be_resolved(session: Session) -> None:
    """An admin resolves a pending activity to ok with the declaration ID."""
    activity = save_activity(session=session, dimona_status=DimonaStatus.PENDING)

    activity.dimona_status = DimonaStatus.OK
    activity.dimona_declaration_id = '123456'
    session.flush()
    session.expire_all()

    assert activity.dimona_status == DimonaStatus.OK
    assert activity.dimona_declaration_id == '123456'


@pytest.mark.parametrize(
    ('field', 'new_value'),
    [
        ('dimona_status', DimonaStatus.REJECTED),
        ('dimona_declaration_id', '999'),
        ('dimona_message', 'changed'),
    ],
)
def test_r17_1_dimona_fields_are_frozen_once_resolved(
    session: Session,
    field: str,
    new_value: object,
) -> None:
    """A declaration that is not pending keeps its Dimona fields."""
    activity = save_activity(session=session, dimona_status=DimonaStatus.OK)

    setattr(activity, field, new_value)

    with pytest.raises(sa.exc.IntegrityError):
        session.flush()
