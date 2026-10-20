"""Alembic environment: connects with the database URL from the application settings."""

import sqlalchemy as sa
from alembic import context

from dimonapp.models import Base
from dimonapp.settings import load_settings

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """Run the migrations on a live connection, inside one transaction."""
    database_url = load_settings().database_url
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
