"""Committed fake data for the tests of the MCP server, which reads with a connection of its own."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.fake_data import build_fake_workers
from dimonapp.models import Base, Worker


def commit_records(engine: sa.Engine, records: list[Base]) -> None:
    """Add records and commit them, so the database user of the MCP service sees them."""
    with Session(bind=engine) as session:
        session.add_all(records)
        session.commit()


def commit_fake_workers(engine: sa.Engine) -> list[Worker]:
    """Commit the five fake workers of `make seed` and give them with their ids.

    In order: a volunteer, two article 17 workers, a flexi-jobber and a freelancer.
    """
    workers = build_fake_workers()
    with Session(bind=engine, expire_on_commit=False) as session:
        session.add_all(workers)
        session.commit()
    return workers
