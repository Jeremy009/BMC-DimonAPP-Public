"""Shared test fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from dimonapp.database import create_database_engine, run_migrations

SETTING_NAMES = (
    'APP_ENV',
    'DATABASE_URL',
    'PORT',
    'STORAGE_BUCKET',
    'STORAGE_FOLDER',
    'FIRST_ADMIN_EMAIL',
    'AUTH_REDIRECT_URI',
    'AUTH_COOKIE_SECRET',
    'GOOGLE_CLIENT_ID',
    'GOOGLE_CLIENT_SECRET',
    'SEED_ADMIN_EMAIL',
    'SEED_PASSWORD',
    'FAKE_DIMONA_OUTCOME',
    'DIMONA_CLIENT_ID',
    'DIMONA_ENTERPRISE_NUMBER',
    'DIMONA_EMPLOYER_ID',
    'DIMONA_JOINT_COMMISSION_ARTICLE_17',
    'DIMONA_JOINT_COMMISSION_FLEXI_JOB',
    'DIMONA_PRIVATE_KEY',
    'DIMONA_PRIVATE_KEY_PATH',
    'DIMONA_PRIVATE_KEY_PASSWORD',
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hide the developer's own settings from every test.

    Tests run in an empty folder, so no local .env is read, and start without any of the
    application's environment variables.
    """
    monkeypatch.chdir(tmp_path)
    for setting_name in SETTING_NAMES:
        monkeypatch.delenv(setting_name, raising=False)


@pytest.fixture
def rsz_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set made-up Dimona settings, which ACC and PROD refuse to start without (R2.3).

    The key is not a real one: enough to load the settings, not to build the client.
    """
    monkeypatch.setenv('DIMONA_CLIENT_ID', 'self_service_client')
    monkeypatch.setenv('DIMONA_ENTERPRISE_NUMBER', '0123456789')
    monkeypatch.setenv('DIMONA_EMPLOYER_ID', '123456')
    monkeypatch.setenv('DIMONA_JOINT_COMMISSION_ARTICLE_17', 'XXX')
    monkeypatch.setenv('DIMONA_JOINT_COMMISSION_FLEXI_JOB', 'XXX')
    monkeypatch.setenv('DIMONA_PRIVATE_KEY', 'not-a-real-key')


@pytest.fixture(scope='session')
def postgres_url() -> Iterator[str]:
    """Start a throwaway PostgreSQL and give its SQLAlchemy URL (R1.11)."""
    with PostgresContainer(image='postgres:16', driver='psycopg') as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope='session')
def migrated_engine(postgres_url: str) -> Iterator[sa.Engine]:
    """Apply the migrations once to the throwaway PostgreSQL and give an engine on it."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv('APP_ENV', 'TEST')
        monkeypatch.setenv('DATABASE_URL', postgres_url)
        run_migrations()
    engine = create_database_engine(database_url=postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: sa.Engine) -> Iterator[Session]:
    """Give a session whose changes are rolled back after the test, so tests share no state."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


@pytest.fixture
def account_engine(migrated_engine: sa.Engine) -> Iterator[sa.Engine]:
    """Give an engine for tests that commit rows, and empty the tables afterwards.

    The running application opens its own connections, so it only sees committed rows.
    Activities refuse a delete (R17.1), so the tables are truncated; the cascade takes the
    activities, rates and documents of the workers along and leaves the activity types.
    """
    yield migrated_engine
    with Session(bind=migrated_engine) as cleanup_session:
        cleanup_session.execute(
            sa.text(
                'TRUNCATE workers, admins, yearly_limits, organisation_config, '
                'sign_in_failures, last_actions CASCADE'
            )
        )
        cleanup_session.commit()
