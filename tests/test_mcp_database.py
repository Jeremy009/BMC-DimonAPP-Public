"""The MCP service signs in to the database as its own user (FDS 15.4, R20.10, open item 9)."""

import sqlalchemy as sa
from google.oauth2.credentials import Credentials

from dimonapp.database import create_database_engine
from dimonapp.mcp_database import add_iam_login, create_mcp_engine
from dimonapp.mcp_settings import McpSettings

# Without sign-in, the MCP service only runs on the developer's machine (R20.7).
LOCAL_HOST = '127.0.0.1'


def read_current_user(engine: sa.Engine) -> str:
    """Give the database user a connection of the engine signs in as."""
    with engine.connect() as connection:
        return connection.scalar(sa.text('SELECT current_user'))


def test_r20_10_iam_login_signs_in_with_a_token_as_password(mcp_database_url: str) -> None:
    """Without a password in the URL, the token of the service account signs the user in.

    Cloud SQL accepts an access token as the password of an IAM user; here the test user's
    password plays the token.
    """
    url = sa.make_url(mcp_database_url)
    url_without_password = url.set(password=None).render_as_string(hide_password=False)
    credentials = Credentials(token=url.password)
    engine = create_database_engine(database_url=url_without_password)
    add_iam_login(engine=engine, credentials=credentials)

    current_user = read_current_user(engine=engine)
    engine.dispose()

    assert current_user == url.username


def test_r20_10_password_login_uses_the_url_as_given(mcp_database_url: str) -> None:
    """Locally, and in the tests, the URL holds the password of the MCP user."""
    settings = McpSettings(app_env='TEST', mcp_host=LOCAL_HOST, mcp_database_url=mcp_database_url)
    engine = create_mcp_engine(settings=settings)

    current_user = read_current_user(engine=engine)
    engine.dispose()

    assert current_user == sa.make_url(mcp_database_url).username
