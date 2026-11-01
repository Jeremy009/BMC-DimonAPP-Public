"""The public endpoint of the MCP server: what it is and what it offers, without data (R20.5).

It needs no sign-in and opens no database connection, so anyone can check that the server is
up. Everything it says is fixed text, in English because an AI model reads it (R20.19).
"""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel

import dimonapp

SERVER_NAME = 'DimonAPP'
SUMMARY = (
    'This is the DimonAPP MCP server of Brussels Monkeys Climbing ASBL (BMC), a climbing gym '
    'in Brussels. DimonAPP is the internal application in which BMC workers declare their '
    'activities at the gym and in which the Dimona declarations are sent to the Belgian '
    'social security (RSZ/ONSS).'
)
SIGNED_IN_TOOLS = (
    'Summarise a period: counted hours and activities per activity type and per worker type.',
    'List the activities day by day, including the days without any declaration.',
    'Find anomalies: pending or rejected Dimona declarations, cancellations, unusual '
    'durations, and legal limits that are close to being reached.',
    'Review a month: does it look correct?',
)
SIGN_IN = (
    'These tools are served at /mcp and need Google sign-in as an active BMC admin. They only '
    'return hours, counts, dates, activity types, worker types, Dimona statuses and activity '
    'ids: never a name, an identifier or an amount in euro. This public endpoint offers no '
    'other tool and no data.'
)
# Every tool of the server only reads, and reaches nothing outside DimonAPP (R20.1).
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


class ServerDescription(BaseModel):
    """What the public endpoint says about the server."""

    name: str
    version: str
    summary: str
    signed_in_tools: list[str]
    sign_in: str


def build_server_description() -> ServerDescription:
    """Describe the server, its signed-in tools and how to reach them."""
    return ServerDescription(
        name=SERVER_NAME,
        version=dimonapp.__version__,
        summary=SUMMARY,
        signed_in_tools=list(SIGNED_IN_TOOLS),
        sign_in=SIGN_IN,
    )


def build_instructions() -> str:
    """Write the server instructions: the same description, as one text for the model."""
    tool_lines = [f'- {tool}' for tool in SIGNED_IN_TOOLS]
    return '\n'.join([SUMMARY, '', 'Signed-in tools:', *tool_lines, '', SIGN_IN])


def build_public_server() -> FastMCP:
    """Build the public MCP server, whose only tool describes the server (R20.5).

    Like /mcp, it never gives the details of an unexpected error (R20.22).
    """
    instructions = build_instructions()
    version = dimonapp.__version__
    server = FastMCP(
        name=SERVER_NAME,
        instructions=instructions,
        version=version,
        mask_error_details=True,
    )
    description = build_server_description()

    @server.tool(annotations=READ_ONLY)
    def about() -> ServerDescription:
        """Say what the DimonAPP MCP server is, what its signed-in tools do and how to sign in."""
        return description

    return server
