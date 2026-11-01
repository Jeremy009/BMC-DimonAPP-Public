"""The views the MCP server reads, as SQLAlchemy tables (FDS section 15.4, R20.10).

Migration 0003 creates them. They have a metadata of their own, so Alembic never takes them
for tables of the application. Only the columns listed here exist in the views: no euro
amount, no free text, nothing of the workers but the id to group by (R20.11).
"""

import sqlalchemy as sa

from dimonapp.models import COMPENSATION_MODEL, DIMONA_STATUS, HOURS, WORKER_TYPE

MCP_SCHEMA = 'mcp'

mcp_metadata = sa.MetaData(schema=MCP_SCHEMA)

activities_view = sa.Table(
    'activities',
    mcp_metadata,
    sa.Column('id', sa.Integer),
    sa.Column('worker_id', sa.Integer),
    sa.Column('worker_type', WORKER_TYPE),
    sa.Column('activity_date', sa.Date),
    sa.Column('activity_type', sa.Text),
    sa.Column('duration_hours', HOURS),
    sa.Column('start_time', sa.Time),
    sa.Column('dimona_status', DIMONA_STATUS),
    sa.Column('is_cancelled', sa.Boolean),
    sa.Column('created_at', sa.DateTime(timezone=True)),
)

activity_types_view = sa.Table(
    'activity_types',
    mcp_metadata,
    sa.Column('code', sa.Text),
    sa.Column('label', sa.Text),
    sa.Column('compensation_model', COMPENSATION_MODEL),
    sa.Column('description_required', sa.Boolean),
    sa.Column('supplement', sa.Text),
)

yearly_limits_view = sa.Table(
    'yearly_limits',
    mcp_metadata,
    sa.Column('year', sa.Integer),
    sa.Column('worker_type', WORKER_TYPE),
    sa.Column('period', sa.Text),
    sa.Column('hours_limit', HOURS),
    sa.Column('min_hours_per_activity', HOURS),
    sa.Column('has_euro_limit', sa.Boolean),
)

configured_years_view = sa.Table(
    'configured_years',
    mcp_metadata,
    sa.Column('year', sa.Integer),
)

limit_thresholds_view = sa.Table(
    'limit_thresholds',
    mcp_metadata,
    sa.Column('year', sa.Integer),
    sa.Column('period', sa.Text),
    sa.Column('worker_type', WORKER_TYPE),
    sa.Column('kind', sa.Text),
    sa.Column('hours_limit', HOURS),
    sa.Column('n_workers', sa.Integer),
)
