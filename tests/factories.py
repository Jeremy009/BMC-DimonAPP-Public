"""Builders of unsaved ORM objects with fake defaults, for the tests."""

from datetime import date
from decimal import Decimal
from typing import Optional

from dimonapp.configuration import OrganisationForm
from dimonapp.fiche_lines import FicheLine
from dimonapp.models import (
    Activity,
    AuthMethod,
    Authorisation,
    CompensationModel,
    CompensationRate,
    DimonaStatus,
    DocumentType,
    Period,
    Worker,
    WorkerType,
    YearlyLimit,
)

VALID_NATIONAL_REGISTER_NUMBER = '85073003328'
FAKE_IBAN = 'BE97000000000099'
HIGH_LIMIT = Decimal('999999')


def build_worker(
    worker_id: Optional[int] = None,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    national_register_number: str = VALID_NATIONAL_REGISTER_NUMBER,
    username: str = 'worker',
    email: Optional[str] = None,
    auth_method: AuthMethod = AuthMethod.LOCAL,
    password_hash: Optional[str] = None,
    is_active: bool = True,
    first_name: str = 'Test',
    last_name: str = 'Worker',
    street: str = 'Rue Exemple 1',
    postal_code: str = '1000',
    city: str = 'Bruxelles',
) -> Worker:
    """Build a fake worker; the e-mail address follows the username unless one is given."""
    return Worker(
        id=worker_id,
        first_name=first_name,
        last_name=last_name,
        national_register_number=national_register_number,
        iban=FAKE_IBAN,
        worker_type=worker_type,
        username=username,
        email=email or f'{username}@example.com',
        auth_method=auth_method,
        password_hash=password_hash,
        is_active=is_active,
        street=street,
        postal_code=postal_code,
        city=city,
    )


def build_activity(
    worker_id: int = 1,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    activity_date: date = date(2026, 5, 10),
    activity_type: str = 'courses',
    duration_hours: Decimal = Decimal('2'),
    compensation_amount: Decimal = Decimal('30'),
    dimona_status: DimonaStatus = DimonaStatus.OK,
    dimona_declaration_id: Optional[str] = None,
    is_cancelled: bool = False,
    description: Optional[str] = None,
    supplement_amount: Decimal = Decimal('0'),
) -> Activity:
    """Build a fake hourly activity."""
    return Activity(
        worker_id=worker_id,
        worker_type=worker_type,
        activity_date=activity_date,
        activity_type=activity_type,
        description=description,
        duration_hours=duration_hours,
        compensation_model=CompensationModel.HOURLY,
        rate_applied=Decimal('15'),
        supplement_amount=supplement_amount,
        compensation_amount=compensation_amount,
        dimona_status=dimona_status,
        dimona_declaration_id=dimona_declaration_id,
        is_cancelled=is_cancelled,
    )


def build_rate(
    valid_from: date,
    amount: Decimal = Decimal('15'),
    worker_id: int = 1,
    activity_type: str = 'courses',
) -> CompensationRate:
    """Build a fake rate version."""
    return CompensationRate(
        worker_id=worker_id,
        activity_type=activity_type,
        amount=amount,
        valid_from=valid_from,
    )


def build_limit(
    year: int = 2026,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    period: Period = Period.YEAR,
    hours_limit: Optional[Decimal] = None,
    euro_limit: Optional[Decimal] = None,
    min_hours_per_activity: Optional[Decimal] = None,
) -> YearlyLimit:
    """Build a fake limit row."""
    return YearlyLimit(
        year=year,
        worker_type=worker_type,
        period=period,
        hours_limit=hours_limit,
        euro_limit=euro_limit,
        min_hours_per_activity=min_hours_per_activity,
    )


def build_complete_limits(year: int = 2026) -> list[YearlyLimit]:
    """Build every required limit of a year, so high that nothing is flagged by accident.

    The order is fixed: vrijwilliger YEAR, article 17 YEAR, flexi-job YEAR, then article 17
    Q1 to Q4.
    """
    article_17 = WorkerType.ARTICLE_17
    limits = [
        build_limit(year=year, worker_type=WorkerType.VRIJWILLIGER, euro_limit=HIGH_LIMIT),
        build_limit(
            year=year,
            worker_type=article_17,
            hours_limit=HIGH_LIMIT,
            euro_limit=HIGH_LIMIT,
        ),
        build_limit(
            year=year,
            worker_type=WorkerType.FLEXI_JOB,
            euro_limit=HIGH_LIMIT,
            min_hours_per_activity=Decimal('3'),
        ),
    ]
    for period in (Period.Q1, Period.Q2, Period.Q3, Period.Q4):
        quarter_limit = build_limit(
            year=year,
            worker_type=article_17,
            period=period,
            hours_limit=HIGH_LIMIT,
        )
        limits.append(quarter_limit)
    return limits


def build_authorisation(
    document_type: DocumentType = DocumentType.CONTRACT,
    activity_types: tuple[str, ...] = ('courses',),
    start_date: date = date(2026, 1, 1),
    end_date: Optional[date] = None,
    worker_id: int = 1,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
) -> Authorisation:
    """Build a fake contract or qualification; only a contract keeps the worker type."""
    is_contract = document_type == DocumentType.CONTRACT
    return Authorisation(
        worker_id=worker_id,
        document_type=document_type,
        worker_type=worker_type if is_contract else None,
        activity_types=list(activity_types),
        start_date=start_date,
        end_date=end_date,
        file_path='fake/document.pdf',
        original_filename='document.pdf',
    )


def build_organisation_form() -> OrganisationForm:
    """Build the complete details of a fake organisation, as the admin enters them."""
    return OrganisationForm(
        company_number='0123.456.789',
        name='Brussels Monkeys Climbing ASBL',
        address='Rue Exemple 1',
        postal_code='1000',
        city='Bruxelles',
        contact_person='Ada Admin',
        phone='021234567',
        contact_details='info@example.com',
        iban=FAKE_IBAN,
    )


def build_fiche_line(
    first_name: str = 'Lotte',
    last_name: str = 'Peeters',
    amount: Decimal = Decimal('1234.50'),
    first_quarter_hours: Decimal = Decimal('10.5'),
    third_quarter_hours: Decimal = Decimal('3'),
    street: str = 'Rue Imaginaire 12',
) -> FicheLine:
    """Build the fiche totals of a fake worker, with hours in the first and third quarter."""
    quarter_hours = {
        Period.Q1: first_quarter_hours,
        Period.Q2: Decimal('0'),
        Period.Q3: third_quarter_hours,
        Period.Q4: Decimal('0'),
    }
    return FicheLine(
        first_name=first_name,
        last_name=last_name,
        national_register_number=VALID_NATIONAL_REGISTER_NUMBER,
        street=street,
        postal_code='1050',
        city='Ixelles',
        amount=amount,
        quarter_hours=quarter_hours,
    )
