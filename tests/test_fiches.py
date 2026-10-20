"""The year-end fiches 281.27: who gets one, the totals and the zip (R14.1 to R14.3)."""

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from dimonapp.fiches import (
    build_fiche_lines,
    build_fiche_row,
    build_fiches_file_name,
    build_fiches_zip,
    find_fiche_problem,
    find_fiche_years,
)
from dimonapp.french import NO_BREAK_SPACE
from dimonapp.models import DimonaStatus, Period, WorkerType
from factories import (
    VALID_NATIONAL_REGISTER_NUMBER,
    build_activity,
    build_fiche_line,
    build_organisation_form,
    build_worker,
)

TODAY = date(2026, 10, 11)
OTHER_NATIONAL_NUMBER = '91020312363'


def save_worker(
    session: Session,
    username: str = 'lotte',
    last_name: str = 'Peeters',
    number: str = VALID_NATIONAL_REGISTER_NUMBER,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
) -> int:
    """Store a worker with a postal address and give the id."""
    worker = build_worker(
        worker_type=worker_type,
        national_register_number=number,
        username=username,
        first_name='Lotte',
        last_name=last_name,
        street='Rue Imaginaire 12',
        postal_code='1050',
        city='Ixelles',
    )
    session.add(worker)
    session.flush()
    return worker.id


def test_r14_3_fiche_sums_the_accepted_article_17_activities_of_the_year(
    session: Session,
) -> None:
    """Cancelled, refused, pending and other years stay out; the hours are kept per quarter."""
    worker_id = save_worker(session=session)
    activities = [
        build_activity(
            worker_id=worker_id,
            activity_date=date(2025, 2, 10),
            duration_hours=Decimal('2.5'),
            compensation_amount=Decimal('50'),
        ),
        build_activity(
            worker_id=worker_id,
            activity_date=date(2025, 12, 31),
            duration_hours=Decimal('4'),
            compensation_amount=Decimal('80.50'),
        ),
        build_activity(worker_id=worker_id, activity_date=date(2025, 3, 1), is_cancelled=True),
        build_activity(
            worker_id=worker_id,
            activity_date=date(2025, 3, 2),
            dimona_status=DimonaStatus.REJECTED,
        ),
        build_activity(
            worker_id=worker_id,
            activity_date=date(2025, 3, 3),
            dimona_status=DimonaStatus.PENDING,
        ),
        build_activity(worker_id=worker_id, activity_date=date(2024, 12, 31)),
        build_activity(worker_id=worker_id, activity_date=date(2026, 1, 1)),
    ]
    session.add_all(activities)
    session.flush()

    lines = build_fiche_lines(session=session, year=2025)

    assert len(lines) == 1
    assert lines[0].last_name == 'Peeters'
    assert lines[0].national_register_number == VALID_NATIONAL_REGISTER_NUMBER
    assert lines[0].street == 'Rue Imaginaire 12'
    assert lines[0].amount == Decimal('130.50')
    assert lines[0].quarter_hours == {
        Period.Q1: Decimal('2.5'),
        Period.Q2: Decimal('0'),
        Period.Q3: Decimal('0'),
        Period.Q4: Decimal('4'),
    }


def test_r14_1_worker_who_moved_to_flexi_job_keeps_a_fiche_for_the_article_17_part(
    session: Session,
) -> None:
    """The status copied onto each activity decides, not the worker's current type."""
    worker_id = save_worker(session=session, worker_type=WorkerType.FLEXI_JOB)
    article_17_activity = build_activity(
        worker_id=worker_id,
        activity_date=date(2025, 5, 10),
        compensation_amount=Decimal('40'),
    )
    flexi_job_activity = build_activity(
        worker_id=worker_id,
        worker_type=WorkerType.FLEXI_JOB,
        activity_date=date(2025, 10, 10),
        compensation_amount=Decimal('99'),
    )
    session.add_all([article_17_activity, flexi_job_activity])
    session.flush()

    lines = build_fiche_lines(session=session, year=2025)

    assert [line.amount for line in lines] == [Decimal('40')]


def test_r14_1_only_article_17_workers_get_a_fiche_ordered_by_name(session: Session) -> None:
    """A volunteer gets none; the fiches follow the last names."""
    second_id = save_worker(session=session, username='z', last_name='Zeta')
    first_id = save_worker(
        session=session,
        username='a',
        last_name='Alpha',
        number=OTHER_NATIONAL_NUMBER,
    )
    volunteer = build_worker(
        worker_type=WorkerType.VRIJWILLIGER,
        national_register_number='90010110154',
        username='v',
    )
    session.add(volunteer)
    session.flush()
    activities = [
        build_activity(worker_id=second_id, activity_date=date(2025, 5, 10)),
        build_activity(worker_id=first_id, activity_date=date(2025, 5, 11)),
        build_activity(
            worker_id=volunteer.id,
            worker_type=WorkerType.VRIJWILLIGER,
            activity_date=date(2025, 5, 12),
            dimona_status=DimonaStatus.NOT_APPLICABLE,
        ),
    ]
    session.add_all(activities)
    session.flush()

    lines = build_fiche_lines(session=session, year=2025)

    assert [line.last_name for line in lines] == ['Alpha', 'Zeta']


def test_r14_1_years_to_pick_are_those_with_article_17_activities_and_this_year(
    session: Session,
) -> None:
    """Newest first; a year with only other worker types is not offered."""
    worker_id = save_worker(session=session)
    activities = [
        build_activity(worker_id=worker_id, activity_date=date(2024, 5, 10)),
        build_activity(
            worker_id=worker_id,
            worker_type=WorkerType.FLEXI_JOB,
            activity_date=date(2023, 5, 10),
        ),
    ]
    session.add_all(activities)
    session.flush()

    assert find_fiche_years(session=session, today=TODAY) == [2026, 2024]


def test_r14_1_table_row_is_french() -> None:
    """The name, the total amount and the hours of the year."""
    row = build_fiche_row(line=build_fiche_line(), year=2025)

    assert row == {
        'Travailleur (statut article 17 en 2025)': 'Lotte Peeters',
        'Rémunération totale': f'1{NO_BREAK_SPACE}234,50{NO_BREAK_SPACE}€',
        'Heures': '13,5',
    }


def test_r14_2_zip_holds_one_pdf_per_worker_and_the_belcotax_file() -> None:
    """The PDFs carry the number their fiche has in the XML."""
    lines = [
        build_fiche_line(first_name='Zoé', last_name="D'Hondt"),
        build_fiche_line(first_name='Youssef', last_name='El Amrani'),
    ]

    content = build_fiches_zip(
        lines=lines,
        organisation=build_organisation_form(),
        year=2025,
        created_on=date(2026, 1, 15),
    )

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        belcotax_file = archive.read('belcotax_281_27_2025.xml')
        first_pdf = archive.read('281.27_2025_001_D_Hondt_Zoe.pdf')
    assert names == [
        'belcotax_281_27_2025.xml',
        '281.27_2025_001_D_Hondt_Zoe.pdf',
        '281.27_2025_002_El_Amrani_Youssef.pdf',
    ]
    assert belcotax_file.count(b'<Fiche28127>') == 2
    assert first_pdf.startswith(b'%PDF')
    assert build_fiches_file_name(year=2025) == 'fiches_281_27_2025.zip'


def test_r14_2_fiches_need_the_details_of_bmc() -> None:
    """What is missing is named in French, and no zip is built."""
    organisation = build_organisation_form()
    organisation.phone = ''
    lines = [build_fiche_line()]

    problem = find_fiche_problem(organisation=organisation)

    assert problem == 'Les coordonnées de BMC sont incomplètes : complétez-les dans Configuration.'
    with pytest.raises(ValueError):
        build_fiches_zip(
            lines=lines,
            organisation=organisation,
            year=2025,
            created_on=date(2026, 1, 15),
        )


def test_r14_2_complete_details_raise_no_problem() -> None:
    """With BMC's complete details the fiches can be generated."""
    problem = find_fiche_problem(organisation=build_organisation_form())

    assert problem is None
