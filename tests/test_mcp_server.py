"""The MCP server of /mcp, called through an in-memory MCP client (FDS 15.5 and 15.6).

The server reads as the database user of the MCP service, from the fake data of `make seed`
plus activities of October 2026, committed so that its own connection sees them.
"""

import json
import re
from collections.abc import AsyncIterator
from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from sqlalchemy.orm import Session

from dimonapp.database import create_database_engine
from dimonapp.fake_data import add_fake_records
from dimonapp.mcp_server import CATALOGUE_URI, build_mcp_server
from dimonapp.models import (
    Activity,
    Admin,
    DimonaStatus,
    OrganisationConfig,
    Worker,
    WorkerType,
    YearlyLimit,
)
from factories import build_activity
from mcp_data import commit_records

TODAY = date(2026, 10, 31)
OCTOBER = {'start': '2026-10-01', 'end': '2026-10-31'}
# Free text and euro amounts typed on the activities, which no output may hold (R20.3, R20.4).
DESCRIPTION = 'Remplacement de Camille Fictive, voir message'
DECLARATION_ID = 'DIMONA-0987654321'
RATE = Decimal('43.21')
SUPPLEMENT = Decimal('12.34')
COMPENSATION = Decimal('987.65')
TOOL_NAMES = ['summarise_period', 'list_daily_activities', 'find_anomalies', 'review_month']
# A database nothing listens on: every connection fails at once.
UNREACHABLE_DATABASE_URL = 'postgresql+psycopg://mcp@127.0.0.1:1/dimonapp'


def find_test_today() -> date:
    """Give the fixed "today" of these tests."""
    return TODAY


def build_october_activities(workers: list[Worker]) -> list[Activity]:
    """Build activities of October 2026 that show every kind of anomaly at least once."""
    volunteer, article_17, second_article_17, flexi_jobber, _ = workers
    first_activity = build_activity(
        worker_id=article_17.id,
        activity_date=date(2026, 10, 5),
        description=DESCRIPTION,
        dimona_declaration_id=DECLARATION_ID,
        supplement_amount=SUPPLEMENT,
        compensation_amount=COMPENSATION,
    )
    first_activity.rate_applied = RATE
    flexi_job = build_activity(
        worker_id=flexi_jobber.id,
        worker_type=WorkerType.FLEXI_JOB,
        activity_date=date(2026, 10, 7),
        compensation_amount=COMPENSATION,
    )
    flexi_job.start_time = time(18, 0)
    rejected = build_activity(
        worker_id=second_article_17.id,
        activity_date=date(2026, 10, 13),
        dimona_status=DimonaStatus.REJECTED,
    )
    rejected.dimona_message = f'Refus: {second_article_17.national_register_number} inconnu'
    return [
        first_activity,
        # 7 hours, and 9 hours that day with the first activity
        build_activity(
            worker_id=article_17.id,
            activity_date=date(2026, 10, 5),
            activity_type='permanence',
            duration_hours=Decimal('7'),
        ),
        # A third and fourth day in the week of 5 October
        build_activity(worker_id=article_17.id, activity_date=date(2026, 10, 6)),
        build_activity(worker_id=article_17.id, activity_date=date(2026, 10, 8)),
        flexi_job,
        build_activity(
            worker_id=second_article_17.id,
            activity_date=date(2026, 10, 12),
            dimona_status=DimonaStatus.PENDING,
        ),
        rejected,
        build_activity(
            worker_id=volunteer.id,
            worker_type=WorkerType.VRIJWILLIGER,
            activity_date=date(2026, 10, 14),
            dimona_status=DimonaStatus.NOT_APPLICABLE,
            is_cancelled=True,
        ),
        # 1 700 euro: at 90 % of the fake volunteer limit of 1 800 euro
        build_activity(
            worker_id=volunteer.id,
            worker_type=WorkerType.VRIJWILLIGER,
            activity_date=date(2026, 10, 20),
            dimona_status=DimonaStatus.NOT_APPLICABLE,
            compensation_amount=Decimal('1700'),
        ),
    ]


@pytest.fixture
def seeded_engine(account_engine: sa.Engine) -> sa.Engine:
    """Commit the fake data of `make seed` and the activities of October 2026."""
    with Session(bind=account_engine) as session:
        add_fake_records(session=session, today=TODAY, seed_password='fake-password')
        session.commit()
    with Session(bind=account_engine) as session:
        workers = list(session.scalars(sa.select(Worker).order_by(Worker.id)))
    activities = build_october_activities(workers=workers)
    commit_records(engine=account_engine, records=activities)
    return account_engine


@pytest.fixture
async def mcp_client(seeded_engine: sa.Engine, mcp_engine: sa.Engine) -> AsyncIterator[Client]:
    """Connect an in-memory MCP client to the server of /mcp."""
    server = build_mcp_server(engine=mcp_engine, find_today=find_test_today)
    async with Client(transport=server) as client:
        yield client


async def call_tool(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool and give its structured output."""
    result = await client.call_tool(name=name, arguments=arguments)
    return result.structured_content


async def test_r20_1_server_offers_four_read_only_tools(mcp_client: Client) -> None:
    """Curated tools only, none of which changes anything (R20.1)."""
    tools = await mcp_client.list_tools()

    assert [tool.name for tool in tools] == TOOL_NAMES
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert all(tool.output_schema for tool in tools)


async def test_r20_14_summarise_period_on_the_seeded_month(mcp_client: Client) -> None:
    """Counted hours and activities, distinct workers, and the status counts."""
    summary = await call_tool(client=mcp_client, name='summarise_period', arguments=OCTOBER)

    assert summary['n_activities'] == 7
    assert summary['hours'] == 19.0
    assert summary['n_workers'] == 4
    assert (summary['n_cancelled'], summary['n_rejected'], summary['n_pending']) == (1, 1, 1)
    labels = [total['label'] for total in summary['activity_types']]
    assert labels == ['Permanence', 'Cours BMC']


async def test_r20_15_list_daily_activities_gives_every_day(mcp_client: Client) -> None:
    """The 31 days of October, with ISO dates and English weekdays."""
    daily_activities = await call_tool(
        client=mcp_client,
        name='list_daily_activities',
        arguments=OCTOBER,
    )

    days = daily_activities['days']
    assert len(days) == 31
    assert (days[0]['day'], days[0]['weekday']) == ('2026-10-01', 'Thursday')
    flexi_job = days[6]['activities'][0]
    assert (flexi_job['worker_type'], flexi_job['start_time']) == ('flexi_job', '18:00:00')


async def test_r20_16_find_anomalies_finds_every_kind(mcp_client: Client) -> None:
    """Each kind of anomaly built into the seeded month comes back."""
    anomalies = await call_tool(client=mcp_client, name='find_anomalies', arguments=OCTOBER)

    kinds = {anomaly['kind'] for anomaly in anomalies['anomalies']}
    assert kinds == {
        'pending_dimona',
        'rejected_dimona',
        'cancelled_activity',
        'long_activity',
        'long_day',
        'many_days_in_week',
        'flexi_job_under_minimum',
        'limit_at_threshold',
    }
    assert anomalies['n_anomalies'] == len(anomalies['anomalies'])


async def test_r20_17_review_month_gives_summary_empty_days_and_anomalies(
    mcp_client: Client,
) -> None:
    """The month review holds the three parts of FDS 15.5."""
    review = await call_tool(
        client=mcp_client,
        name='review_month',
        arguments={'year': 2026, 'month': 10},
    )

    assert review['summary']['n_activities'] == 7
    empty_days = [day['day'] for day in review['days_without_activities']]
    # Counted activities on 5, 6, 7, 8, 12 and 20 October
    assert len(empty_days) == 31 - 6
    assert '2026-10-05' not in empty_days
    assert '2026-10-14' in empty_days
    assert review['anomalies']['n_anomalies'] > 0


async def test_r20_18_resource_lists_the_activity_types_without_rates(mcp_client: Client) -> None:
    """The catalogue of the nine activity types, with their French labels."""
    contents = await mcp_client.read_resource(uri=CATALOGUE_URI)

    catalogue = json.loads(contents[0].text)
    entries = catalogue['activity_types']
    assert len(entries) == 9
    assert entries[1] == {
        'code': 'courses',
        'label': 'Cours BMC',
        'compensation_model': 'hourly',
        'supplement': None,
        'supplement_label': None,
    }


async def test_r20_18_monthly_review_prompt_asks_for_an_answer_in_french(
    mcp_client: Client,
) -> None:
    """The prompt walks the model through review_month for the month asked."""
    prompts = await mcp_client.list_prompts()
    arguments = {'year': 2026, 'month': 10}
    result = await mcp_client.get_prompt(name='monthly_review', arguments=arguments)

    text = result.messages[0].content.text
    assert [prompt.name for prompt in prompts] == ['monthly_review']
    assert 'review_month with year 2026 and month 10' in text
    assert 'Answer in French.' in text


async def test_r20_19_period_longer_than_366_days_is_refused(mcp_client: Client) -> None:
    """The tool answers with an error instead of reading the database."""
    arguments = {'start': '2025-01-01', 'end': '2026-12-31'}

    with pytest.raises(ToolError):
        await mcp_client.call_tool(name='summarise_period', arguments=arguments)


async def test_r20_19_month_outside_1_to_12_is_refused(mcp_client: Client) -> None:
    """The parameters are checked before the tool runs."""
    with pytest.raises(ToolError):
        await mcp_client.call_tool(name='review_month', arguments={'year': 2026, 'month': 13})


async def test_r20_22_clear_message_of_a_tool_still_reaches_the_client(
    mcp_client: Client,
) -> None:
    """The model reads why the period is refused and can ask for a shorter one."""
    arguments = {'start': '2025-01-01', 'end': '2026-12-31'}

    with pytest.raises(ToolError, match='it may have at most 366 days'):
        await mcp_client.call_tool(name='summarise_period', arguments=arguments)


async def test_r20_22_unexpected_error_reaches_the_client_without_details() -> None:
    """A database that cannot be reached gives a fixed message, not the database's own."""
    engine = create_database_engine(database_url=UNREACHABLE_DATABASE_URL)
    server = build_mcp_server(engine=engine, find_today=find_test_today)
    async with Client(transport=server) as client:
        result = await client.call_tool(
            name='summarise_period',
            arguments=OCTOBER,
            raise_on_error=False,
        )
        with pytest.raises(MCPError) as resource_error:
            await client.read_resource(uri=CATALOGUE_URI)
    engine.dispose()

    assert result.is_error
    assert result.content[0].text == "Error calling tool 'summarise_period'"
    assert str(resource_error.value) == f"Error reading resource '{CATALOGUE_URI}'"


def list_forbidden_values(engine: sa.Engine) -> list[str]:
    """Give every seeded personal value, euro amount and free text that must never come out."""
    with Session(bind=engine) as session:
        workers = list(session.scalars(sa.select(Worker)))
        organisation = session.scalars(sa.select(OrganisationConfig)).one()
        admin_emails = list(session.scalars(sa.select(Admin.email)))
        euro_limits = list(session.scalars(sa.select(YearlyLimit.euro_limit)))
        dimona_messages = list(session.scalars(sa.select(Activity.dimona_message)))
    values = [*admin_emails, DESCRIPTION, DECLARATION_ID]
    for worker in workers:
        values.extend(
            [
                worker.first_name,
                worker.last_name,
                worker.email,
                worker.username,
                worker.national_register_number,
                worker.iban,
                worker.street,
                worker.postal_code,
                worker.city,
            ]
        )
    values.extend(
        [
            organisation.name,
            organisation.company_number,
            organisation.address,
            organisation.contact_person,
            organisation.phone,
            organisation.contact_details,
            organisation.iban,
        ]
    )
    values.extend(message for message in dimona_messages if message is not None)
    for amount in [RATE, SUPPLEMENT, COMPENSATION, *euro_limits]:
        if amount is None:
            continue
        cents = f'{amount:.2f}'
        values.extend([cents, cents.replace('.', ',')])
        # A whole amount, as the euro limits are, may also come out without its cents
        if amount == amount.to_integral_value():
            values.append(f'{amount:.0f}')
    return values


async def collect_every_output(client: Client) -> list[str]:
    """Call every tool, read every resource and prompt, and give all the text that came out."""
    outputs = [client.instructions or '']
    tools = await client.list_tools()
    outputs.append(json.dumps([tool.model_dump(mode='json') for tool in tools]))
    tool_arguments = {
        'summarise_period': OCTOBER,
        'list_daily_activities': OCTOBER,
        'find_anomalies': OCTOBER,
        'review_month': {'year': 2026, 'month': 10},
    }
    for tool in tools:
        result = await client.call_tool(name=tool.name, arguments=tool_arguments[tool.name])
        outputs.append(json.dumps(result.structured_content))
        outputs.extend(content.text for content in result.content)
    for resource in await client.list_resources():
        contents = await client.read_resource(uri=resource.uri)
        outputs.extend(content.text for content in contents)
    for prompt in await client.list_prompts():
        result = await client.get_prompt(name=prompt.name, arguments={'year': 2026, 'month': 10})
        outputs.extend(message.content.text for message in result.messages)
    return outputs


async def test_r20_20_no_seeded_personal_data_or_euro_amount_in_any_output(
    mcp_client: Client,
    seeded_engine: sa.Engine,
) -> None:
    """The leak test of FDS 15.6: nothing personal, no amount, no free text comes out."""
    forbidden_values = list_forbidden_values(engine=seeded_engine)
    outputs = await collect_every_output(client=mcp_client)

    output_text = '\n'.join(outputs)
    leaks = [
        value
        for value in forbidden_values
        if re.search(rf'\b{re.escape(value)}\b', output_text, flags=re.IGNORECASE)
    ]
    assert len(forbidden_values) > 50
    assert leaks == []
