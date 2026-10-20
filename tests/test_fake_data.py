"""Fake data for the local database (R3.7)."""

from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.compliance import find_configured_years
from dimonapp.fake_data import add_fake_records, build_fake_workers, main
from dimonapp.iban import is_valid_iban
from dimonapp.models import (
    Admin,
    AuthMethod,
    Authorisation,
    CompensationRate,
    DocumentType,
    Worker,
    WorkerType,
    YearlyLimit,
)
from dimonapp.national_register import is_valid_national_register_number
from dimonapp.passwords import verify_password


def test_r3_7_fake_national_register_numbers_pass_the_checksum() -> None:
    """The invented numbers are well-formed, so the fake workers behave like real ones."""
    workers = build_fake_workers()

    numbers = [worker.national_register_number for worker in workers]
    assert all(is_valid_national_register_number(number=number) for number in numbers)


def test_r3_7_fake_workers_cover_every_worker_type() -> None:
    """There is at least one fake worker of each type to try the application with."""
    worker_types = {worker.worker_type for worker in build_fake_workers()}

    assert worker_types == set(WorkerType)


def test_r3_7_fake_records_fit_the_schema(session: Session) -> None:
    """The fake data inserts into the migrated database with rates, documents and limits."""
    add_fake_records(session=session, today=date(2026, 10, 10))
    session.flush()

    n_workers = session.scalar(sa.select(sa.func.count()).select_from(Worker))
    n_rates = session.scalar(sa.select(sa.func.count()).select_from(CompensationRate))
    n_authorisations = session.scalar(sa.select(sa.func.count()).select_from(Authorisation))
    limits = list(session.scalars(sa.select(YearlyLimit)).all())
    assert n_rates == n_workers * 11
    assert n_authorisations == n_workers * 2
    contract_query = sa.select(Authorisation, Worker).join(Worker)
    contract_query = contract_query.where(Authorisation.document_type == DocumentType.CONTRACT)
    contract_rows = session.execute(contract_query).all()
    assert len(contract_rows) == n_workers
    assert all(contract.worker_type == worker.worker_type for contract, worker in contract_rows)
    assert find_configured_years(limits=limits) == {2026, 2027}


def test_r3_7_fake_accounts_cannot_sign_in_by_default(session: Session) -> None:
    """Without the seed variables no fake worker has a password and the admin is invented."""
    add_fake_records(session=session, today=date(2026, 10, 10))
    session.flush()

    workers = session.scalars(sa.select(Worker)).all()
    admin_emails = session.scalars(sa.select(Admin.email)).all()
    assert all(worker.password_hash is None for worker in workers)
    assert admin_emails == ['admin@example.com']


def test_r3_7_seed_variables_make_the_fake_accounts_usable(session: Session) -> None:
    """The developer's address becomes the admin and the local workers get a hashed password."""
    add_fake_records(
        session=session,
        today=date(2026, 10, 10),
        seed_admin_email='developer@example.com',
        seed_password='seed-password',
    )
    session.flush()

    workers = session.scalars(sa.select(Worker)).all()
    local_workers = [worker for worker in workers if worker.auth_method == AuthMethod.LOCAL]
    google_workers = [worker for worker in workers if worker.auth_method == AuthMethod.GOOGLE]
    admin_emails = session.scalars(sa.select(Admin.email)).all()
    assert admin_emails == ['developer@example.com']
    assert all(
        verify_password(password='seed-password', password_hash=worker.password_hash)
        for worker in local_workers
    )
    assert all(worker.password_hash is None for worker in google_workers)


def test_r3_7_fake_data_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
) -> None:
    """The seed command stops before touching a production database."""
    monkeypatch.setenv('APP_ENV', 'PROD')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://nobody@localhost:1/nothing')

    with pytest.raises(SystemExit):
        main()


def test_r11_8_fake_workers_have_ibans_with_a_correct_checksum() -> None:
    """The seeded workers can be edited by the admin: their IBAN passes the check."""
    workers = build_fake_workers()

    ibans = [worker.iban for worker in workers]

    assert len(set(ibans)) == len(workers)
    for iban in ibans:
        assert is_valid_iban(iban=iban)
