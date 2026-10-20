"""The first migration applies, reverts and applies again (R1.10)."""

import pytest
import sqlalchemy as sa
from alembic import command

from dimonapp.database import build_alembic_config


def test_r1_10_migration_upgrades_downgrades_and_upgrades_again(
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
) -> None:
    """On a second, empty database in the same container, the full round trip succeeds."""
    # Create an empty database next to the one the other tests use
    admin_engine = sa.create_engine(url=postgres_url, isolation_level='AUTOCOMMIT')
    with admin_engine.connect() as connection:
        connection.execute(sa.text('CREATE DATABASE migration_round_trip'))
    admin_engine.dispose()
    database_url = sa.make_url(postgres_url).set(database='migration_round_trip')
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', database_url.render_as_string(hide_password=False))
    alembic_config = build_alembic_config()

    command.upgrade(config=alembic_config, revision='head')
    command.downgrade(config=alembic_config, revision='base')
    command.upgrade(config=alembic_config, revision='head')

    engine = sa.create_engine(url=database_url)
    with engine.connect() as connection:
        n_activity_types = connection.scalar(sa.text('SELECT count(*) FROM activity_types'))
    engine.dispose()
    assert n_activity_types == 11
