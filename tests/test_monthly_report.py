"""The monthly report per worker (R13.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import DimonaStatus, WorkerType
from dimonapp.monthly_report import (
    build_monthly_report,
    build_report_row,
    sum_report,
)
from factories import build_activity, build_worker

OCTOBER = date(2026, 10, 1)


def save_worker(session: Session, username: str, last_name: str, number: str) -> int:
    """Store a worker and give the id."""
    worker = build_worker(
        national_register_number=number,
        username=username,
        first_name='Test',
        last_name=last_name,
    )
    session.add(worker)
    session.flush()
    return worker.id


def test_r13_1_report_sums_counted_activities_per_worker(session: Session) -> None:
    """Hours and amount per worker, by name; cancelled, rejected and other months left out."""
    first_id = save_worker(session=session, username='b', last_name='Zwart', number='1')
    second_id = save_worker(session=session, username='a', last_name='Alpha', number='2')
    idle_id = save_worker(session=session, username='c', last_name='Idle', number='3')
    activities = [
        build_activity(worker_id=first_id, activity_date=date(2026, 10, 1)),
        build_activity(
            worker_id=first_id,
            activity_date=date(2026, 10, 31),
            duration_hours=Decimal('2.5'),
            compensation_amount=Decimal('1200.50'),
            dimona_status=DimonaStatus.PENDING,
        ),
        build_activity(worker_id=first_id, activity_date=date(2026, 10, 5), is_cancelled=True),
        build_activity(
            worker_id=first_id,
            activity_date=date(2026, 10, 6),
            dimona_status=DimonaStatus.REJECTED,
        ),
        build_activity(worker_id=first_id, activity_date=date(2026, 9, 30)),
        build_activity(worker_id=first_id, activity_date=date(2026, 11, 1)),
        build_activity(worker_id=second_id, activity_date=date(2026, 10, 10)),
        build_activity(worker_id=idle_id, activity_date=date(2026, 10, 10), is_cancelled=True),
    ]
    session.add_all(activities)
    session.flush()

    lines = build_monthly_report(session=session, month_start=OCTOBER)

    assert [line.worker_name for line in lines] == ['Test Alpha', 'Test Zwart']
    assert lines[1].hours == Decimal('4.50')
    assert lines[1].amount == Decimal('1230.50')
    assert lines[1].iban == 'BE97000000000099'
    assert lines[1].worker_type == WorkerType.ARTICLE_17
    assert sum_report(lines=lines) == Decimal('1260.50')


def test_r13_1_report_row_is_formatted_in_french(session: Session) -> None:
    """Hours with a comma, the amount in euro and the IBAN in groups of four (R18.1)."""
    worker_id = save_worker(session=session, username='a', last_name='Alpha', number='1')
    activity = build_activity(
        worker_id=worker_id,
        activity_date=date(2026, 10, 1),
        duration_hours=Decimal('2.5'),
        compensation_amount=Decimal('1200.5'),
    )
    session.add(activity)
    session.flush()

    line = build_monthly_report(session=session, month_start=OCTOBER)[0]

    assert build_report_row(line=line) == {
        'Travailleur': 'Test Alpha',
        'Type': 'Article 17',
        'Heures': '2,5',
        'Montant dû': f'1{NO_BREAK_SPACE}200,50{NO_BREAK_SPACE}€',
        'IBAN': 'BE97 0000 0000 0099',
    }


def test_r13_1_empty_month_has_no_line_and_no_amount(session: Session) -> None:
    """A month without activities is an empty report."""
    lines = build_monthly_report(session=session, month_start=OCTOBER)

    assert lines == []
    assert sum_report(lines=lines) == Decimal('0')
