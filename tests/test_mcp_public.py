"""The public endpoint describes the server and offers no data (R20.5, R20.19)."""

from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

import dimonapp
from dimonapp.mcp_public import SERVER_NAME, build_public_server


@pytest.fixture
async def public_client() -> AsyncIterator[Client]:
    """Connect an in-memory MCP client to the public server."""
    async with Client(transport=build_public_server()) as client:
        yield client


async def test_r20_5_public_server_offers_only_the_about_tool(public_client: Client) -> None:
    """No data tool, resource or prompt is reachable without sign-in."""
    tools = await public_client.list_tools()
    resources = await public_client.list_resources()
    prompts = await public_client.list_prompts()

    assert [tool.name for tool in tools] == ['about']
    assert resources == []
    assert prompts == []


async def test_r20_5_about_tool_is_read_only(public_client: Client) -> None:
    """The tool tells MCP clients that it changes nothing and reaches nothing outside."""
    tools = await public_client.list_tools()

    annotations = tools[0].annotations
    assert annotations.read_only_hint
    assert not annotations.open_world_hint


async def test_r20_5_about_says_what_the_server_is_and_that_sign_in_is_needed(
    public_client: Client,
) -> None:
    """The description names the server, its version and the sign-in of the full tools."""
    result = await public_client.call_tool(name='about', arguments={})

    description = result.structured_content
    assert description['name'] == SERVER_NAME
    assert description['version'] == dimonapp.__version__
    assert 'MCP server' in description['summary']
    assert len(description['signed_in_tools']) == 4
    assert 'Google sign-in as an active BMC admin' in description['sign_in']


async def test_r20_5_about_has_an_output_schema(public_client: Client) -> None:
    """The output is a typed model, so MCP clients can read its schema (FDS 15.5)."""
    tools = await public_client.list_tools()

    output_schema = tools[0].output_schema
    assert set(output_schema['properties']) == {
        'name',
        'version',
        'summary',
        'signed_in_tools',
        'sign_in',
    }


async def test_r20_19_server_instructions_describe_the_server_in_english(
    public_client: Client,
) -> None:
    """The instructions the model reads say the same as the about tool."""
    instructions = public_client.instructions

    assert 'DimonAPP MCP server' in instructions
    assert 'Signed-in tools:' in instructions
    assert 'never a name, an identifier or an amount in euro' in instructions
