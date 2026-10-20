"""The year-end fiches 281.27 of the article 17 workers: totals and the zip (FDS 7.6).

Plain functions on a database session. The national register number leaves the database here
for the fiche and the Belcotax file only, and is never logged (R3.5).
"""

import io
import logging
import zipfile
from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.activities import QUARTERS, find_period
from dimonapp.belcotax import build_belcotax_file
from dimonapp.configuration import OrganisationForm, is_organisation_complete
from dimonapp.fiche_lines import FicheLine, sum_fiche_hours
from dimonapp.fiche_pdf import build_fiche_pdf
from dimonapp.french import format_amount, format_decimal, remove_accents
from dimonapp.models import Activity, DimonaStatus, Worker, WorkerType

logger = logging.getLogger(__name__)

ORGANISATION_INCOMPLETE_MESSAGE = (
    'Les coordonnées de BMC sont incomplètes : complétez-les dans Configuration.'
)


def find_fiche_years(session: Session, today: date) -> list[int]:
    """Give the income years the admin can pick, newest first.

    Every year with an article 17 activity, and always the current year.
    """
    activity_years = session.scalars(
        sa.select(sa.extract('year', Activity.activity_date))
        .where(Activity.worker_type == WorkerType.ARTICLE_17)
        .distinct()
    )
    years = {today.year}
    years.update(int(year) for year in activity_years)
    return sorted(years, reverse=True)


def find_fiche_activities(session: Session, year: int) -> list[Activity]:
    """Give the activities a fiche counts: article 17, not cancelled, Dimona accepted (R14.3).

    The worker type is the one copied onto the activity, so a worker who moved on to flexi-job
    during the year keeps a fiche for the article 17 part only.
    """
    query = sa.select(Activity).where(
        Activity.worker_type == WorkerType.ARTICLE_17,
        Activity.activity_date >= date(year=year, month=1, day=1),
        Activity.activity_date <= date(year=year, month=12, day=31),
        Activity.is_cancelled.is_(sa.false()),
        Activity.dimona_status == DimonaStatus.OK,
    )
    return list(session.scalars(query))


def build_fiche_lines(session: Session, year: int) -> list[FicheLine]:
    """Sum the fiche activities of a year per worker, by name (R14.1, R14.3).

    A worker without such an activity gets no fiche: there is nothing to report.
    """
    activities = find_fiche_activities(session=session, year=year)
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
        quarter_hours = {quarter: Decimal('0') for quarter in QUARTERS}
        for activity in own_activities:
            quarter = find_period(activity_date=activity.activity_date)
            quarter_hours[quarter] += activity.duration_hours
        amount = sum(
            (activity.compensation_amount for activity in own_activities),
            start=Decimal('0'),
        )
        line = FicheLine(
            first_name=worker.first_name,
            last_name=worker.last_name,
            national_register_number=worker.national_register_number,
            street=worker.street,
            postal_code=worker.postal_code,
            city=worker.city,
            amount=amount,
            quarter_hours=quarter_hours,
        )
        lines.append(line)
    return lines


def build_fiche_row(line: FicheLine, year: int) -> dict[str, str]:
    """Build the table row of one worker, formatted in French."""
    return {
        f'Travailleur (statut article 17 en {year})': f'{line.first_name} {line.last_name}',
        'Rémunération totale': format_amount(amount=line.amount),
        'Heures': format_decimal(value=sum_fiche_hours(line=line)),
    }


def find_fiche_problem(organisation: OrganisationForm) -> Optional[str]:
    """Give the French message of what keeps the fiches from being generated, or None.

    The fiche and the Belcotax file need BMC's complete details (R15.4).
    """
    if not is_organisation_complete(organisation=organisation):
        return ORGANISATION_INCOMPLETE_MESSAGE
    return None


def build_fiche_file_name(line: FicheLine, year: int, sequence_number: int) -> str:
    """Name the PDF of one worker, for example 281.27_2025_001_Peeters_Lotte.pdf."""
    name = remove_accents(text=f'{line.last_name}_{line.first_name}')
    safe_name = ''.join(character if character.isalnum() else '_' for character in name)
    return f'281.27_{year}_{sequence_number:03d}_{safe_name}.pdf'


def build_fiches_file_name(year: int) -> str:
    """Name the zip of a year, for example fiches_281_27_2025.zip."""
    return f'fiches_281_27_{year}.zip'


def build_fiches_zip(
    lines: list[FicheLine],
    organisation: OrganisationForm,
    year: int,
    created_on: date,
) -> bytes:
    """Build the zip of a year: one 281.27 PDF per worker and the Belcotax XML (R14.1, R14.2).

    The fiches are numbered in the order of the lines, the same in the PDFs and in the XML.
    """
    if not lines or find_fiche_problem(organisation=organisation) is not None:
        raise ValueError('The fiches cannot be generated.')
    belcotax_file = build_belcotax_file(
        lines=lines,
        organisation=organisation,
        year=year,
        created_on=created_on,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(file=buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'belcotax_281_27_{year}.xml', belcotax_file)
        for sequence_number, line in enumerate(lines, start=1):
            pdf = build_fiche_pdf(
                line=line,
                organisation=organisation,
                year=year,
                sequence_number=sequence_number,
            )
            file_name = build_fiche_file_name(line=line, year=year, sequence_number=sequence_number)
            archive.writestr(file_name, pdf)
    logger.info(f'Fiches 281.27 of {year} generated: {len(lines)} workers.')
    return buffer.getvalue()
