"""The monthly report: per worker the hours and amount due of a month, with the IBAN (R13.1).

Plain functions on a database session. The IBAN is shown to the admin and never logged (R3.5).
"""

from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.activities import sum_counted_activities
from dimonapp.french import format_amount, format_decimal, format_iban
from dimonapp.models import Activity, Worker, WorkerType
from dimonapp.months import shift_month
from dimonapp.worker_types import WORKER_TYPE_LABELS, build_worker_name


class ReportLine(BaseModel):
    """The totals of one worker for one month."""

    worker_name: str
    worker_type: WorkerType
    hours: Decimal
    amount: Decimal
    iban: str


def build_monthly_report(session: Session, month_start: date) -> list[ReportLine]:
    """Sum the counted activities of one month per worker, by name (R13.1).

    A worker without a counted activity in the month is left out: nothing is due.
    """
    next_month_start = shift_month(month_start=month_start, n_months=1)
    query = sa.select(Activity).where(
        Activity.activity_date >= month_start,
        Activity.activity_date < next_month_start,
    )
    activities = list(session.scalars(query))
    worker_ids = {activity.worker_id for activity in activities}
    workers_query = (
        sa.select(Worker)
        .where(Worker.id.in_(worker_ids))
        .order_by(Worker.last_name, Worker.first_name, Worker.id)
    )
    lines = []
    for worker in session.scalars(workers_query):
        worker_id = worker.id
        own_activities = [activity for activity in activities if activity.worker_id == worker_id]
        totals = sum_counted_activities(activities=own_activities)
        if totals.hours == 0:
            continue
        line = ReportLine(
            worker_name=build_worker_name(worker=worker),
            worker_type=worker.worker_type,
            hours=totals.hours,
            amount=totals.amount,
            iban=worker.iban,
        )
        lines.append(line)
    return lines


def sum_report(lines: list[ReportLine]) -> Decimal:
    """Give the total amount due of a report."""
    return sum((line.amount for line in lines), start=Decimal('0'))


def build_report_row(line: ReportLine) -> dict[str, str]:
    """Build the table row of one worker, formatted in French."""
    return {
        'Travailleur': line.worker_name,
        'Type': WORKER_TYPE_LABELS[line.worker_type],
        'Heures': format_decimal(value=line.hours),
        'Montant dû': format_amount(amount=line.amount),
        'IBAN': format_iban(iban=line.iban),
    }
