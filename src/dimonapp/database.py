"""Database engine, sessions and migrations (R1.9, R1.10)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIGRATIONS_FOLDER = Path(__file__).parent / 'migrations'


def create_database_engine(database_url: str) -> sa.Engine:
    """Create the SQLAlchemy engine for a postgresql+psycopg URL.

    A database error leaves out the values of its statement, which can be a national register
    number or an IBAN, so they never reach a log or the page (R3.5, R3.8).
    """
    return sa.create_engine(url=database_url, hide_parameters=True)


@contextmanager
def open_session(engine: sa.Engine) -> Iterator[Session]:
    """Give a session that commits on success, rolls back on error and always closes."""
    with Session(bind=engine) as session:
        with session.begin():
            yield session


def build_alembic_config() -> Config:
    """Point Alembic at the migrations shipped inside the package."""
    alembic_config = Config()
    alembic_config.set_main_option('script_location', str(MIGRATIONS_FOLDER))
    return alembic_config


def run_migrations() -> None:
    """Bring the database schema to the latest migration (alembic upgrade head).

    The database URL is read from the settings by migrations/env.py.
    """
    alembic_config = build_alembic_config()
    logger.info('Applying database migrations.')
    command.upgrade(config=alembic_config, revision='head')
    logger.info('Database migrations applied.')
