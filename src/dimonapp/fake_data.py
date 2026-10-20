"""Fake data for the local throwaway database (R3.7). Run with `make seed`.

Every person, number and amount here is invented. Real data never leaves GCP.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.database import create_database_engine, open_session
from dimonapp.iban import compute_iban_check_digits
from dimonapp.models import (
    ACTIVITY_TYPE_CODES,
    RATE_CODES,
    Admin,
    AuthMethod,
    Authorisation,
    Base,
    CompensationRate,
    DocumentType,
    OrganisationConfig,
    Period,
    Worker,
    WorkerType,
    YearlyLimit,
)
from dimonapp.national_register import compute_check_digits
from dimonapp.passwords import hash_password
from dimonapp.settings import load_settings

logger = logging.getLogger(__name__)

FAKE_RATE = Decimal('15.00')
FAKE_ADMIN_EMAIL = 'admin@example.com'


def build_fake_national_register_number(birth_date: date, sequence: int) -> str:
    """Build an invented national register number with a correct checksum."""
    first_nine_digits = f'{birth_date:%y%m%d}{sequence:03d}'
    born_from_2000 = birth_date.year >= 2000
    check_digits = compute_check_digits(
        first_nine_digits=first_nine_digits,
        born_from_2000=born_from_2000,
    )
    return f'{first_nine_digits}{check_digits:02d}'


def build_fake_iban(sequence: int) -> str:
    """Build an invented Belgian IBAN with a correct checksum."""
    account_number = f'{sequence:012d}'
    check_digits = compute_iban_check_digits(country_code='BE', account_number=account_number)
    return f'BE{check_digits}{account_number}'


def build_fake_workers() -> list[Worker]:
    """Build one invented worker per worker type, plus a second article 17 worker."""
    return [
        Worker(
            first_name='Camille',
            last_name='Fictive',
            national_register_number=build_fake_national_register_number(
                birth_date=date(1990, 1, 15),
                sequence=101,
            ),
            iban=build_fake_iban(sequence=1),
            worker_type=WorkerType.VRIJWILLIGER,
            username='camille',
            email='camille.fictive@example.com',
            auth_method=AuthMethod.LOCAL,
            street='Rue Fictive 3',
            postal_code='1000',
            city='Bruxelles',
        ),
        Worker(
            first_name='Noor',
            last_name='Exemple',
            national_register_number=build_fake_national_register_number(
                birth_date=date(1995, 6, 2),
                sequence=202,
            ),
            iban=build_fake_iban(sequence=2),
            worker_type=WorkerType.ARTICLE_17,
            username='noor',
            email='noor.exemple@example.com',
            auth_method=AuthMethod.LOCAL,
            street='Rue Imaginaire 12',
            postal_code='1050',
            city='Ixelles',
        ),
        Worker(
            first_name='Sam',
            last_name='Factice',
            national_register_number=build_fake_national_register_number(
                birth_date=date(2001, 3, 20),
                sequence=303,
            ),
            iban=build_fake_iban(sequence=3),
            worker_type=WorkerType.ARTICLE_17,
            username='sam',
            email='sam.factice@example.com',
            auth_method=AuthMethod.GOOGLE,
            street='Avenue Factice 7',
            postal_code='1030',
            city='Schaerbeek',
        ),
        Worker(
            first_name='Robin',
            last_name='Inventé',
            national_register_number=build_fake_national_register_number(
                birth_date=date(1988, 11, 9),
                sequence=404,
            ),
            iban=build_fake_iban(sequence=4),
            worker_type=WorkerType.FLEXI_JOB,
            username='robin',
            email='robin.invente@example.com',
            auth_method=AuthMethod.LOCAL,
            street='Chaussée Inventée 21',
            postal_code='1060',
            city='Saint-Gilles',
        ),
        Worker(
            first_name='Alex',
            last_name='Imaginaire',
            national_register_number=build_fake_national_register_number(
                birth_date=date(1992, 8, 27),
                sequence=505,
            ),
            iban=build_fake_iban(sequence=5),
            worker_type=WorkerType.FREELANCER,
            username='alex',
            email='alex.imaginaire@example.com',
            auth_method=AuthMethod.LOCAL,
            street='Place Imaginaire 5',
            postal_code='1180',
            city='Uccle',
        ),
    ]


def build_fake_limits(year: int) -> list[YearlyLimit]:
    """Build an invented, complete set of limits for one year; not the official figures."""
    quarter_hours = {Period.Q1: '150', Period.Q2: '150', Period.Q3: '285', Period.Q4: '150'}
    limits = [
        YearlyLimit(
            year=year,
            worker_type=WorkerType.VRIJWILLIGER,
            period=Period.YEAR,
            euro_limit=Decimal('1800'),
        ),
        YearlyLimit(
            year=year,
            worker_type=WorkerType.ARTICLE_17,
            period=Period.YEAR,
            hours_limit=Decimal('450'),
            euro_limit=Decimal('7700'),
        ),
        YearlyLimit(
            year=year,
            worker_type=WorkerType.FLEXI_JOB,
            period=Period.YEAR,
            euro_limit=Decimal('18000'),
            min_hours_per_activity=Decimal('3'),
        ),
    ]
    for period in quarter_hours:
        hours_limit = Decimal(quarter_hours[period])
        limit = YearlyLimit(
            year=year,
            worker_type=WorkerType.ARTICLE_17,
            period=period,
            hours_limit=hours_limit,
        )
        limits.append(limit)
    return limits


def build_fake_worker_records(worker: Worker, start_date: date) -> list[Base]:
    """Build the rates, the contract and the qualification of one fake worker.

    The contract is one of the worker's own type, so the worker may declare (R12.10).
    """
    worker_id = worker.id
    activity_types = list(ACTIVITY_TYPE_CODES)
    records: list[Base] = [
        CompensationRate(
            worker_id=worker_id,
            activity_type=rate_code,
            amount=FAKE_RATE,
            valid_from=start_date,
        )
        for rate_code in RATE_CODES
    ]
    for document_type in DocumentType:
        authorisation = Authorisation(
            worker_id=worker_id,
            document_type=document_type,
            worker_type=worker.worker_type if document_type == DocumentType.CONTRACT else None,
            activity_types=activity_types,
            start_date=start_date,
            file_path=f'fake/{worker_id}/{document_type.value}.pdf',
            original_filename=f'{document_type.value}_fictif.pdf',
        )
        records.append(authorisation)
    return records


def set_seed_password(workers: list[Worker], seed_password: str) -> None:
    """Give every fake local worker the same password, stored as its Argon2 hash."""
    password_hash = hash_password(password=seed_password)
    for worker in workers:
        if worker.auth_method == AuthMethod.LOCAL:
            worker.password_hash = password_hash


def add_fake_records(
    session: Session,
    today: date,
    seed_admin_email: Optional[str] = None,
    seed_password: Optional[str] = None,
) -> None:
    """Add the fake workers and everything they need to declare activities.

    The fake accounts cannot sign in by themselves: the developer's own Google address
    (seed_admin_email) becomes the admin, and seed_password the password of the local workers.
    """
    # Workers first, so their identifiers exist for the rates and documents
    workers = build_fake_workers()
    if seed_password:
        set_seed_password(workers=workers, seed_password=seed_password)
    session.add_all(workers)
    session.flush()

    # Rates, contract and qualification per worker, valid from the start of the year
    start_date = date(year=today.year, month=1, day=1)
    for worker in workers:
        worker_records = build_fake_worker_records(worker=worker, start_date=start_date)
        session.add_all(worker_records)

    # Limits for this year and the next, one admin and the organisation details
    session.add_all(build_fake_limits(year=today.year))
    session.add_all(build_fake_limits(year=today.year + 1))
    admin_email = seed_admin_email or FAKE_ADMIN_EMAIL
    session.add(Admin(email=admin_email))
    organisation = OrganisationConfig(
        company_number='0000.000.000',
        name='Association Fictive ASBL',
        address='Rue Inventée 1',
        postal_code='1000',
        city='Bruxelles',
        contact_person='Dominique Fictif',
        phone='020000000',
        contact_details='contact@example.com',
        iban=build_fake_iban(sequence=9),
    )
    session.add(organisation)


def main() -> None:
    """Fill an empty local database with the fake data; never in production."""
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if settings.app_env == 'PROD':
        raise SystemExit('Fake data is never loaded in production.')

    engine = create_database_engine(database_url=settings.database_url)
    with open_session(engine=engine) as session:
        n_workers = session.scalar(sa.select(sa.func.count()).select_from(Worker))
        if n_workers:
            raise SystemExit('The database already holds workers; no fake data added.')
        add_fake_records(
            session=session,
            today=date.today(),
            seed_admin_email=settings.seed_admin_email,
            seed_password=settings.seed_password,
        )
    engine.dispose()
    logger.info('Fake data added.')


if __name__ == '__main__':
    main()
