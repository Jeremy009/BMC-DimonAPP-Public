"""MCP server: the read-only role, its views and the admin check (FDS section 15.4).

The views and functions live in a schema of their own, `mcp`. They run with the rights of
their owner, the role that applies the migrations, so the role dimonapp_mcp reads them without
any privilege on the tables below (R20.10). The role cannot sign in: the database user of the
MCP service becomes a member of it (docs/DEPLOYMENT.md, `make mcp-user` locally).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

MCP_ROLE = 'dimonapp_mcp'

# A role belongs to the whole PostgreSQL server, not to one database, so it may exist already.
CREATE_ROLE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{MCP_ROLE}') THEN
        CREATE ROLE {MCP_ROLE} NOLOGIN;
    END IF;
END
$$
"""

# Every column the MCP server may read of an activity; no euro, no free text (R20.11). The
# worker id is only a key to group by.
CREATE_ACTIVITIES_VIEW = """
CREATE VIEW mcp.activities AS
SELECT
    id,
    worker_id,
    worker_type,
    activity_date,
    activity_type,
    duration_hours,
    start_time,
    dimona_status,
    is_cancelled,
    created_at
FROM public.activities
"""

CREATE_ACTIVITY_TYPES_VIEW = """
CREATE VIEW mcp.activity_types AS
SELECT code, label, compensation_model, description_required, supplement
FROM public.activity_types
"""

# The hours values of the limits; of the euro limit only whether it is filled in.
CREATE_YEARLY_LIMITS_VIEW = """
CREATE VIEW mcp.yearly_limits AS
SELECT
    year,
    worker_type,
    period,
    hours_limit,
    min_hours_per_activity,
    euro_limit IS NOT NULL AS has_euro_limit
FROM public.yearly_limits
"""

# The years with a complete set of limits, as compliance.REQUIRED_LIMITS defines it (R16.4).
# A migration never changes afterwards, so the list is written out here.
CREATE_CONFIGURED_YEARS_VIEW = """
CREATE VIEW mcp.configured_years AS
WITH required_limits (worker_type, period, field) AS (
    VALUES
        ('vrijwilliger', 'YEAR', 'euro_limit'),
        ('article_17', 'Q1', 'hours_limit'),
        ('article_17', 'Q2', 'hours_limit'),
        ('article_17', 'Q3', 'hours_limit'),
        ('article_17', 'Q4', 'hours_limit'),
        ('article_17', 'YEAR', 'hours_limit'),
        ('article_17', 'YEAR', 'euro_limit'),
        ('flexi_job', 'YEAR', 'euro_limit'),
        ('flexi_job', 'YEAR', 'min_hours_per_activity')
),
filled_limits AS (
    SELECT limits.year
    FROM public.yearly_limits AS limits
    JOIN required_limits AS required
        ON required.worker_type = limits.worker_type::text AND required.period = limits.period
    WHERE (required.field = 'hours_limit' AND limits.hours_limit IS NOT NULL)
        OR (required.field = 'euro_limit' AND limits.euro_limit IS NOT NULL)
        OR (
            required.field = 'min_hours_per_activity'
            AND limits.min_hours_per_activity IS NOT NULL
        )
)
SELECT year
FROM filled_limits
GROUP BY year
HAVING count(*) = (SELECT count(*) FROM required_limits)
"""

# Per limit of a configured year, the number of workers at or above 90 % of it, following the
# dashboard flags (R16.1 to R16.5, compliance.find_limit_flags): counted activities declared
# under the worker's current type, never a freelancer. Only a count and, for an hours limit,
# the limit come out: never a total or a ratio, so no euro amount can be worked back (R20.12).
CREATE_LIMIT_THRESHOLDS_VIEW = """
CREATE VIEW mcp.limit_thresholds AS
WITH counted_activities AS (
    SELECT
        activities.worker_id,
        activities.worker_type,
        extract(year FROM activities.activity_date)::integer AS year,
        'Q' || extract(quarter FROM activities.activity_date) AS quarter,
        activities.duration_hours,
        activities.compensation_amount
    FROM public.activities AS activities
    JOIN public.workers AS workers
        ON workers.id = activities.worker_id AND workers.worker_type = activities.worker_type
    WHERE NOT activities.is_cancelled
        AND activities.dimona_status <> 'rejected'
        AND activities.worker_type <> 'freelancer'
),
worker_totals AS (
    SELECT
        limits.id AS limit_id,
        counted.worker_id,
        sum(counted.duration_hours) AS total_hours,
        sum(counted.compensation_amount) AS total_euro
    FROM public.yearly_limits AS limits
    JOIN counted_activities AS counted
        ON counted.worker_type = limits.worker_type
        AND counted.year = limits.year
        AND (limits.period = 'YEAR' OR limits.period = counted.quarter)
    GROUP BY limits.id, counted.worker_id
),
limit_kinds (kind) AS (
    VALUES ('hours'), ('euro')
)
SELECT
    limits.year,
    limits.period,
    limits.worker_type,
    kinds.kind,
    CASE WHEN kinds.kind = 'hours' THEN limits.hours_limit END AS hours_limit,
    count(totals.worker_id) FILTER (
        WHERE (kinds.kind = 'hours' AND totals.total_hours >= limits.hours_limit * 0.9)
            OR (kinds.kind = 'euro' AND totals.total_euro >= limits.euro_limit * 0.9)
    ) AS n_workers
FROM public.yearly_limits AS limits
JOIN mcp.configured_years AS configured ON configured.year = limits.year
CROSS JOIN limit_kinds AS kinds
LEFT JOIN worker_totals AS totals ON totals.limit_id = limits.id
WHERE limits.worker_type <> 'freelancer'
    AND (
        (kinds.kind = 'hours' AND limits.hours_limit IS NOT NULL)
        OR (kinds.kind = 'euro' AND limits.euro_limit IS NOT NULL)
    )
GROUP BY limits.id, limits.year, limits.period, limits.worker_type, kinds.kind
"""

# True or false only: whether an e-mail is an active admin, matched trimmed and in lower case
# as the application matches it (R4.8). SECURITY DEFINER reads the admins table with the
# rights of the owner; the fixed search_path stops a caller from slipping in objects of its
# own (R20.13).
CREATE_IS_ACTIVE_ADMIN = """
CREATE FUNCTION mcp.is_active_admin(email text) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.admins
        WHERE admins.is_active AND lower(admins.email) = lower(btrim(is_active_admin.email))
    )
$$
"""

VIEWS = (
    'mcp.activities',
    'mcp.activity_types',
    'mcp.yearly_limits',
    'mcp.configured_years',
    'mcp.limit_thresholds',
)


def upgrade() -> None:
    """Create the schema, the views, the function, the role and its grants."""
    op.execute('CREATE SCHEMA mcp')
    op.execute(CREATE_ACTIVITIES_VIEW)
    op.execute(CREATE_ACTIVITY_TYPES_VIEW)
    op.execute(CREATE_YEARLY_LIMITS_VIEW)
    op.execute(CREATE_CONFIGURED_YEARS_VIEW)
    op.execute(CREATE_LIMIT_THRESHOLDS_VIEW)
    op.execute(CREATE_IS_ACTIVE_ADMIN)

    # Every role may execute a new function by default; only the MCP role may run this one
    op.execute('REVOKE EXECUTE ON FUNCTION mcp.is_active_admin(text) FROM PUBLIC')
    op.execute(CREATE_ROLE)
    views = ', '.join(VIEWS)
    op.execute(f'GRANT USAGE ON SCHEMA mcp TO {MCP_ROLE}')
    op.execute(f'GRANT SELECT ON {views} TO {MCP_ROLE}')
    op.execute(f'GRANT EXECUTE ON FUNCTION mcp.is_active_admin(text) TO {MCP_ROLE}')


def downgrade() -> None:
    """Drop the schema with its views and function; the grants go with them.

    The role stays: it belongs to the whole server, where another database may still use it.
    """
    op.execute('DROP SCHEMA mcp CASCADE')
