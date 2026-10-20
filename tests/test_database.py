"""Database migrations against a throwaway PostgreSQL (R1.11)."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dimonapp.database import create_database_engine, run_migrations
from factories import FAKE_IBAN, build_worker


def test_r1_11_migrations_run_against_testcontainers_postgres(
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
) -> None:
    """Upgrading to head works on an empty database and records the Alembic version table."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', postgres_url)

    run_migrations()

    engine = sa.create_engine(postgres_url)
    with engine.connect() as connection:
        table_names = sa.inspect(connection).get_table_names()
    engine.dispose()
    assert 'alembic_version' in table_names


def test_r3_3_engine_accepts_the_cloud_sql_socket_url() -> None:
    """In GCP only the URL differs: the Unix socket of Cloud Run's Cloud SQL connection."""
    database_url = (
        'postgresql+psycopg://dimonapp:password@/dimonapp'
        '?host=/cloudsql/example-project:europe-west1:dimonapp-test'
    )

    engine = create_database_engine(database_url=database_url)

    assert engine.url.database == 'dimonapp'
    assert engine.url.query['host'] == '/cloudsql/example-project:europe-west1:dimonapp-test'
    assert engine.url.host is None


def test_r3_8_database_error_leaves_out_the_values_of_its_statement(session: Session) -> None:
    """A refused insert does not repeat the IBAN and the other values it was given."""
    session.add(build_worker(username='lotte'))
    session.flush()
    session.add(build_worker(username='camille'))

    with pytest.raises(IntegrityError) as error_info:
        session.flush()

    error_text = str(error_info.value)
    assert 'hide_parameters=True' in error_text
    assert FAKE_IBAN not in error_text
    assert 'camille' not in error_text
