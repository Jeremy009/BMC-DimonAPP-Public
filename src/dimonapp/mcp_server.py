"""The MCP server of /mcp: curated, read-only tools over the views (FDS section 15.5).

Every tool reads through the database role of the MCP service, which sees the views of
migration 0003 and nothing else (R20.10), and answers with a model of mcp_models (R20.2 to
R20.4). There is no free-form query and no tool that writes (R20.1).
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Annotated, Optional

import sqlalchemy as sa
from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from pydantic import Field

import dimonapp
from dimonapp import mcp_tools
from dimonapp.clock import read_today
from dimonapp.mcp_models import (
    Anomalies,
    DailyActivities,
    MonthReview,
    PeriodSummary,
)
from dimonapp.mcp_public import READ_ONLY, SERVER_NAME, SUMMARY

logger = logging.getLogger(__name__)

CATALOGUE_URI = 'dimonapp://activity-types'
INSTRUCTIONS = '\n'.join(
    [
        SUMMARY,
        '',
        'The tools read the activities that workers declared in DimonAPP. Counted activities are '
        'those not cancelled and not rejected by the Dimona service; pending ones count. A '
        'period runs from a start to an end date, both included, of at most 366 days.',
        '',
        'The tools only return hours, counts, dates, activity types, worker types, Dimona '
        'statuses and activity ids: never a name, an identifier or an amount in euro. Anything '
        'that needs a follow-up comes as an activity id and its date, which an admin opens in '
        'DimonAPP. Activity types come with their French labels.',
    ]
)

StartDate = Annotated[date, Field(description='First day of the period, included (YYYY-MM-DD).')]
EndDate = Annotated[date, Field(description='Last day of the period, included (YYYY-MM-DD).')]
Year = Annotated[int, Field(ge=2000, le=2100)]
Month = Annotated[int, Field(ge=1, le=12, description='Month number, 1 for January.')]


def build_monthly_review_prompt(year: int, month: int) -> str:
    """Write the request of the monthly review prompt (R20.18)."""
    return (
        f'Review the declared activities of month {month} of {year} in DimonAPP. Call the tool '
        f'review_month with year {year} and month {month}. Then go through the summary of the '
        'month, the days without a counted activity and each anomaly. For every anomaly that '
        'needs a follow-up, give the activity ids and dates, which an admin opens in DimonAPP. '
        'End with whether the month looks correct. Answer in French.'
    )


def build_mcp_server(
    engine: sa.Engine,
    auth: Optional[AuthProvider] = None,
    find_today: Callable[[], date] = read_today,
) -> FastMCP:
    """Build the MCP server of /mcp on an engine that signs in as the MCP role.

    With a sign-in, FastMCP refuses every request without a valid token before any tool is
    reached; without one, only allowed locally, every request gets in (FDS 15.2). An
    unexpected error reaches the client without its details, as the message of a database
    error names the instance and its user; a ToolError keeps its message (R20.22).
    """
    version = dimonapp.__version__
    server = FastMCP(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        version=version,
        auth=auth,
        mask_error_details=True,
    )

    @server.tool(annotations=READ_ONLY)
    def summarise_period(start: StartDate, end: EndDate) -> PeriodSummary:
        """Sum the counted hours and activities of a period per activity type and worker type.

        Also gives the number of distinct workers with a counted activity and the number of
        cancelled, Dimona-rejected and pending activities.
        """
        logger.info(f'MCP tool summarise_period from {start} to {end}.')
        with engine.connect() as connection:
            return mcp_tools.summarise_period(connection=connection, start=start, end=end)

    @server.tool(annotations=READ_ONLY)
    def list_daily_activities(start: StartDate, end: EndDate) -> DailyActivities:
        """List every day of a period with its weekday and its counted activities.

        A day without any counted activity is listed with an empty list.
        """
        logger.info(f'MCP tool list_daily_activities from {start} to {end}.')
        with engine.connect() as connection:
            return mcp_tools.list_daily_activities(connection=connection, start=start, end=end)

    @server.tool(annotations=READ_ONLY)
    def find_anomalies(start: StartDate, end: EndDate) -> Anomalies:
        """Find everything in a period that needs a look, each with a fixed explanation.

        Pending and rejected Dimona declarations, cancellations, activities over 5 hours, days
        over 8 hours for one worker, weeks with more than 2 days for one worker, flexi-jobs
        under the minimum hours, years without complete limits and limits at 90 %.
        """
        logger.info(f'MCP tool find_anomalies from {start} to {end}.')
        today = find_today()
        with engine.connect() as connection:
            return mcp_tools.find_anomalies(
                connection=connection,
                start=start,
                end=end,
                today=today,
            )

    @server.tool(annotations=READ_ONLY)
    def review_month(year: Year, month: Month) -> MonthReview:
        """Tell whether a month looks correct: its summary, its empty days and its anomalies."""
        logger.info(f'MCP tool review_month for {year}-{month:02d}.')
        today = find_today()
        with engine.connect() as connection:
            return mcp_tools.review_month(
                connection=connection,
                year=year,
                month=month,
                today=today,
            )

    @server.resource(uri=CATALOGUE_URI, mime_type='application/json')
    def activity_types() -> str:
        """The activity types a worker declares: code, French label, model and supplement."""
        logger.info('MCP resource activity-types read.')
        with engine.connect() as connection:
            catalogue = mcp_tools.read_catalogue(connection=connection)
        return catalogue.model_dump_json()

    @server.prompt
    def monthly_review(year: Year, month: Month) -> str:
        """Review one month of declared activities and answer in French."""
        return build_monthly_review_prompt(year=year, month=month)

    return server
