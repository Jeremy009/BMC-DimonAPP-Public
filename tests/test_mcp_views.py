"""The database layer of the privacy rule: role, views and functions of the MCP server.

R20.10 to R20.13: the role of the MCP service reads the views and nothing else, the views
leave out every euro amount and free text, the limits are checked inside the database, and the
admin check answers true or false without the role reading the admins table.
"""

from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.compliance import find_configured_years, find_limit_flags
from dimonapp.fake_data import build_fake_limits
from dimonapp.models import (
    Activity,
    Admin,
    Base,
    DimonaStatus,
    Period,
    Worker,
    WorkerType,
    YearlyLimit,
)
from factories import build_activity
from mcp_data import commit_fake_workers, commit_records

TABLE_NAMES = sorted([*Base.metadata.tables, 'alembic_version'])
VIEW_NAMES = (
    'mcp.activities',
    'mcp.activity_types',
    'mcp.yearly_limits',
    'mcp.configured_years',
    'mcp.limit_thresholds',
)


def read_view_columns(engine: sa.Engine, view_name: str) -> set[str]:
    """Give the column names of one view of the mcp schema."""
    query = sa.text(
        'SELECT column_name FROM information_schema.columns '
        "WHERE table_schema = 'mcp' AND table_name = :view_name"
    )
    with engine.connect() as connection:
        return set(connection.scalars(query, {'view_name': view_name}))


def check_is_active_admin(engine: sa.Engine, email: str) -> bool:
    """Ask the admin check of the database, as the MCP service will."""
    query = sa.text('SELECT mcp.is_active_admin(:email)')
    with engine.connect() as connection:
        return connection.scalar(query, {'email': email})


@pytest.mark.parametrize('table_name', TABLE_NAMES)
def test_r20_10_mcp_role_cannot_read_any_table(mcp_engine: sa.Engine, table_name: str) -> None:
    """A SELECT on a table, workers and admins included, fails with permission denied."""
    query = sa.text(f'SELECT * FROM public.{table_name} LIMIT 1')
    with mcp_engine.connect() as connection:
        with pytest.raises(sa.exc.ProgrammingError):
            connection.execute(query)


@pytest.mark.parametrize('view_name', VIEW_NAMES)
def test_r20_10_mcp_role_reads_the_views(mcp_engine: sa.Engine, view_name: str) -> None:
    """Each view answers the role of the MCP service."""
    query = sa.text(f'SELECT count(*) FROM {view_name}')
    with mcp_engine.connect() as connection:
        n_rows = connection.scalar(query)

    assert n_rows >= 0


@pytest.mark.parametrize(
    'statement',
    [
        'UPDATE mcp.activities SET is_cancelled = true',
        "INSERT INTO mcp.activity_types (code, label) VALUES ('new', 'Nouveau')",
        'DELETE FROM mcp.yearly_limits',
        'CREATE TABLE mcp.notes (note text)',
    ],
)
def test_r20_10_mcp_role_changes_nothing(mcp_engine: sa.Engine, statement: str) -> None:
    """A simple view can be written through, but the role only has SELECT on it."""
    with mcp_engine.connect() as connection:
        with pytest.raises(sa.exc.ProgrammingError):
            connection.execute(sa.text(statement))


def test_r20_11_activities_view_has_no_euro_and_no_free_text(migrated_engine: sa.Engine) -> None:
    """No rate, supplement or compensation, no description, Dimona message or declaration ID."""
    columns = read_view_columns(engine=migrated_engine, view_name='activities')

    assert columns == {
        'id',
        'worker_id',
        'worker_type',
        'activity_date',
        'activity_type',
        'duration_hours',
        'start_time',
        'dimona_status',
        'is_cancelled',
        'created_at',
    }


def test_r20_11_reference_views_hold_no_euro_amount(migrated_engine: sa.Engine) -> None:
    """Of the euro limit only whether it is filled in; the thresholds give no total or ratio."""
    limit_columns = read_view_columns(engine=migrated_engine, view_name='yearly_limits')
    threshold_columns = read_view_columns(engine=migrated_engine, view_name='limit_thresholds')

    assert limit_columns == {
        'year',
        'worker_type',
        'period',
        'hours_limit',
        'min_hours_per_activity',
        'has_euro_limit',
    }
    assert threshold_columns == {
        'year',
        'period',
        'worker_type',
        'kind',
        'hours_limit',
        'n_workers',
    }


def test_r20_13_is_active_admin_matches_trimmed_and_in_lower_case(
    account_engine: sa.Engine,
    mcp_engine: sa.Engine,
) -> None:
    """Only an active admin gets true, matched as the application matches it (R4.8)."""
    workers = commit_fake_workers(engine=account_engine)
    admins = [
        Admin(email='admin@example.com'),
        Admin(email='former@example.com', is_active=False),
    ]
    commit_records(engine=account_engine, records=admins)
    worker_email = workers[0].email

    assert check_is_active_admin(engine=mcp_engine, email='  Admin@Example.COM ')
    assert not check_is_active_admin(engine=mcp_engine, email='former@example.com')
    assert not check_is_active_admin(engine=mcp_engine, email=worker_email)
    assert not check_is_active_admin(engine=mcp_engine, email='someone@example.com')


def test_r16_4_configured_years_view_follows_the_compliance_engine(
    account_engine: sa.Engine,
    mcp_engine: sa.Engine,
) -> None:
    """A year with one required limit missing is not configured, in the view as in the code."""
    limits_2027 = build_fake_limits(year=2027)
    flexi_job_year = limits_2027[2]
    flexi_job_year.min_hours_per_activity = None
    limits = [*build_fake_limits(year=2026), *limits_2027]
    commit_records(engine=account_engine, records=limits)
    with Session(bind=account_engine) as session:
        stored_limits = list(session.scalars(sa.select(YearlyLimit)))
    expected_years = find_configured_years(limits=stored_limits)

    with mcp_engine.connect() as connection:
        view_years = set(connection.scalars(sa.text('SELECT year FROM mcp.configured_years')))

    assert view_years == expected_years == {2026}


def build_threshold_activities(workers: list[Worker]) -> list[Activity]:
    """Build activities that bring some workers to 90 % of a fake limit of 2026, others not.

    Fake limits: article 17 at 150 hours in Q4, a volunteer at 1 800 euro, a flexi-jobber at
    18 000 euro (fake_data.build_fake_limits).
    """
    volunteer, article_17, second_article_17, flexi_jobber, freelancer = workers
    return [
        # 140 hours in Q4: at the threshold of 135 hours
        build_activity(
            worker_id=article_17.id,
            activity_date=date(2026, 10, 5),
            duration_hours=Decimal('140'),
        ),
        # Rejected, so not counted: stays under the threshold of Q1
        build_activity(
            worker_id=article_17.id,
            activity_date=date(2026, 2, 5),
            duration_hours=Decimal('140'),
            dimona_status=DimonaStatus.REJECTED,
        ),
        # Declared under an earlier type: does not count for the current one (R5.5)
        build_activity(
            worker_id=second_article_17.id,
            worker_type=WorkerType.VRIJWILLIGER,
            activity_date=date(2026, 10, 6),
            duration_hours=Decimal('140'),
        ),
        build_activity(
            worker_id=volunteer.id,
            worker_type=WorkerType.VRIJWILLIGER,
            compensation_amount=Decimal('1700'),
        ),
        build_activity(
            worker_id=flexi_jobber.id,
            worker_type=WorkerType.FLEXI_JOB,
            duration_hours=Decimal('4'),
            compensation_amount=Decimal('16500'),
        ),
        # Never flagged, whatever the hours (R16.5)
        build_activity(
            worker_id=freelancer.id,
            worker_type=WorkerType.FREELANCER,
            duration_hours=Decimal('500'),
            compensation_amount=Decimal('50000'),
        ),
    ]


def test_r20_12_limit_thresholds_follow_the_dashboard_flags(
    account_engine: sa.Engine,
    mcp_engine: sa.Engine,
) -> None:
    """The view counts the same workers at 90 % as the flags of the admin dashboard."""
    workers = commit_fake_workers(engine=account_engine)
    activities = build_threshold_activities(workers=workers)
    commit_records(engine=account_engine, records=[*build_fake_limits(year=2026), *activities])
    with Session(bind=account_engine) as session:
        stored_workers = list(session.scalars(sa.select(Worker)))
        stored_activities = list(session.scalars(sa.select(Activity)))
        stored_limits = list(session.scalars(sa.select(YearlyLimit)))
    flags = find_limit_flags(
        workers=stored_workers,
        activities=stored_activities,
        limits=stored_limits,
    )
    expected_counts = Counter(
        (flag.year, flag.period, flag.worker_type, flag.quantity) for flag in flags
    )

    query = sa.text('SELECT * FROM mcp.limit_thresholds')
    with mcp_engine.connect() as connection:
        rows = list(connection.execute(query).mappings())
    view_counts = {
        (row['year'], row['period'], row['worker_type'], row['kind']): row['n_workers']
        for row in rows
        if row['n_workers']
    }

    assert view_counts == dict(expected_counts)
    assert view_counts == {
        (2026, Period.Q4, WorkerType.ARTICLE_17, 'hours'): 1,
        (2026, Period.YEAR, WorkerType.VRIJWILLIGER, 'euro'): 1,
        (2026, Period.YEAR, WorkerType.FLEXI_JOB, 'euro'): 1,
    }


def test_r20_12_limit_thresholds_give_the_hours_limit_only(
    account_engine: sa.Engine,
    mcp_engine: sa.Engine,
) -> None:
    """Every limit of a configured year has a row; only an hours limit shows its value."""
    commit_records(engine=account_engine, records=build_fake_limits(year=2026))

    query = sa.text('SELECT kind, hours_limit, n_workers FROM mcp.limit_thresholds')
    with mcp_engine.connect() as connection:
        rows = list(connection.execute(query).mappings())

    hours_limits = sorted(row['hours_limit'] for row in rows if row['kind'] == 'hours')
    euro_rows = [row for row in rows if row['kind'] == 'euro']
    assert hours_limits == [150, 150, 150, 285, 450]
    assert len(euro_rows) == 3
    assert all(row['hours_limit'] is None for row in euro_rows)
    assert all(row['n_workers'] == 0 for row in rows)
