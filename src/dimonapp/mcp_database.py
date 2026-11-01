"""The database connection of the MCP service (FDS section 15.4, open item 9).

In GCP the service signs in to Cloud SQL as the IAM database user of its service account: a
fresh access token of that account is the password of every new connection, so there is no
database password at all. Locally, and in the tests, the URL holds the password of a user that
`make mcp-user` created. Either way the user is a member of the read-only role dimonapp_mcp.
"""

import logging
from typing import Any

import google.auth
import sqlalchemy as sa
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request

from dimonapp.database import create_database_engine
from dimonapp.mcp_settings import McpSettings

logger = logging.getLogger(__name__)

# The scope a token needs to sign in to Cloud SQL as an IAM database user.
SQL_LOGIN_SCOPE = 'https://www.googleapis.com/auth/sqlservice.login'


def read_login_token(credentials: Credentials) -> str:
    """Give an access token of the service account, refreshed first when it has expired."""
    if not credentials.valid:
        credentials.refresh(request=Request())
    return credentials.token


def add_iam_login(engine: sa.Engine, credentials: Credentials) -> None:
    """Give every new connection of the engine a fresh token as its password.

    Cloud SQL checks the token only when a connection signs in, so a pooled connection stays
    usable after its token expires.
    """

    def set_token_password(
        dialect: sa.Dialect,
        connection_record: sa.pool.ConnectionPoolEntry,
        cargs: list[Any],
        cparams: dict[str, Any],
    ) -> None:
        """Put the token in the connection parameters, as SQLAlchemy calls it on connect."""
        cparams['password'] = read_login_token(credentials=credentials)

    sa.event.listen(target=engine, identifier='do_connect', fn=set_token_password)


def create_mcp_engine(settings: McpSettings) -> sa.Engine:
    """Create the engine of the MCP service's own database user."""
    engine = create_database_engine(database_url=settings.mcp_database_url)
    if settings.mcp_database_iam_login:
        credentials, _ = google.auth.default(scopes=[SQL_LOGIN_SCOPE])
        add_iam_login(engine=engine, credentials=credentials)
        logger.info('The MCP service signs in to the database as the IAM user of its account.')
    return engine
