"""The MCP service serves its endpoints over HTTP (R20.5 to R20.8, R20.20)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx2
import pytest
import sqlalchemy as sa
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider
from starlette.applications import Starlette

from dimonapp.mcp_service import build_mcp_app
from dimonapp.mcp_settings import McpSettings
from dimonapp.models import Admin
from mcp_data import commit_fake_workers, commit_records

# FastMCP accepts a sign-in over plain HTTP on localhost only.
BASE_URL = 'http://localhost'
# Without sign-in, the MCP service only runs on the developer's machine (R20.7).
LOCAL_HOST = '127.0.0.1'
# The S256 challenge of the example verifier of RFC 7636, appendix B.
PKCE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
ADMIN_EMAIL = 'admin@example.com'
FORMER_ADMIN_EMAIL = 'former@example.com'
# The scopes the sign-in of /mcp asks of Google, as Google names them in a token.
GOOGLE_TOKEN_SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email']


def build_sign_in_settings(mcp_database_url: str, oauth_folder: Path) -> McpSettings:
    """Give the settings of acceptance: Google sign-in and the MCP database user."""
    return McpSettings(
        app_env='ACC',
        mcp_database_url=mcp_database_url,
        mcp_base_url=BASE_URL,
        mcp_google_client_id='mcp-client.apps.googleusercontent.com',
        mcp_google_client_secret='mcp-client-secret',
        mcp_jwt_signing_key='mcp-signing-key-made-up-for-the-tests-of-the-mcp-service',
        mcp_oauth_folder=str(oauth_folder),
    )


@asynccontextmanager
async def serve_mcp_app(settings: McpSettings) -> AsyncIterator[Starlette]:
    """Build the HTTP app of the service and run its lifespan, as uvicorn does.

    A context manager rather than a fixture: the lifespan must start and stop in one task.
    """
    app = build_mcp_app(settings=settings)
    async with app.router.lifespan_context(app):
        yield app


def build_http_client(app: Starlette, **options: Any) -> httpx2.AsyncClient:
    """Give an HTTP client that sends its requests to the app in memory."""
    transport = httpx2.ASGITransport(app=app)
    return httpx2.AsyncClient(transport=transport, base_url=BASE_URL, **options)


def connect_mcp_client(app: Starlette, path: str, token: Optional[str] = None) -> Client:
    """Give an MCP client that talks Streamable HTTP to one endpoint of the app."""

    def build_client(**options: Any) -> httpx2.AsyncClient:
        """Build the HTTP client of the MCP client, with the options the MCP client asks for."""
        return build_http_client(app=app, **options)

    url = f'{BASE_URL}{path}'
    transport = StreamableHttpTransport(url=url, auth=token, httpx_client_factory=build_client)
    return Client(transport=transport)


async def post_to_mcp(
    app: Starlette,
    token: Optional[str] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> int:
    """Send an MCP request to /mcp, with or without a token, and give its status code."""
    headers = {} if token is None else {'Authorization': f'Bearer {token}'}
    headers.update(extra_headers or {})
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
    async with build_http_client(app=app) as http_client:
        response = await http_client.post('/mcp', json=message, headers=headers)
    return response.status_code


def build_authorize_parameters(client_id: str, redirect_uri: str) -> dict[str, str]:
    """Give the query of a sign-in request, as an MCP client sends it to /authorize."""
    return {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code_challenge': PKCE_CHALLENGE,
        'code_challenge_method': 'S256',
        'state': 'made-up-state',
    }


@pytest.fixture
def google_accounts(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Stand in for Google: map made-up tokens to Google accounts, and commit the admins.

    The OAuth proxy of GoogleProvider checks its own token and asks Google about the token
    behind it. Here that check gives the account of a made-up token; the admin check that
    follows is the real one, against the database.
    """
    workers = commit_fake_workers(engine=account_engine)
    admins = [Admin(email=ADMIN_EMAIL), Admin(email=FORMER_ADMIN_EMAIL, is_active=False)]
    commit_records(engine=account_engine, records=admins)
    accounts = {
        'admin-token': (ADMIN_EMAIL, 'true'),
        'worker-token': (workers[0].email, 'true'),
        'former-admin-token': (FORMER_ADMIN_EMAIL, 'true'),
        'unverified-admin-token': (ADMIN_EMAIL, 'false'),
    }

    async def load_google_token(provider: GoogleProvider, token: str) -> Optional[AccessToken]:
        """Give the Google account of a made-up token, as GoogleProvider would."""
        if token not in accounts:
            return None
        email, email_verified = accounts[token]
        claims = {'email': email, 'email_verified': email_verified}
        return AccessToken(
            token=token,
            client_id='google',
            scopes=GOOGLE_TOKEN_SCOPES,
            claims=claims,
        )

    monkeypatch.setattr(GoogleProvider, 'load_access_token', load_google_token)


async def test_r20_5_public_endpoint_answers_without_a_token(
    mcp_database_url: str,
    tmp_path: Path,
) -> None:
    """With sign-in on /mcp, an MCP client without a token still reaches /public/mcp."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        async with connect_mcp_client(app=app, path='/public/mcp') as client:
            tools = await client.list_tools()
            result = await client.call_tool(name='about', arguments={})

    assert [tool.name for tool in tools] == ['about']
    assert result.structured_content['name'] == 'DimonAPP'


async def test_r20_20_mcp_refuses_a_request_without_a_token(
    mcp_database_url: str,
    tmp_path: Path,
) -> None:
    """FastMCP refuses the request before any tool is reached."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        status_code = await post_to_mcp(app=app)

    assert status_code == 401


async def test_r20_6_active_admin_reaches_the_data_tools(
    mcp_database_url: str,
    tmp_path: Path,
    google_accounts: None,
) -> None:
    """The Google account of an active admin gets the four tools."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        async with connect_mcp_client(app=app, path='/mcp', token='admin-token') as client:
            tools = await client.list_tools()

    assert len(tools) == 4


@pytest.mark.parametrize(
    'token',
    ['worker-token', 'former-admin-token', 'unverified-admin-token', 'unknown-token'],
)
async def test_r20_20_mcp_refuses_every_account_but_an_active_admin(
    mcp_database_url: str,
    tmp_path: Path,
    google_accounts: None,
    token: str,
) -> None:
    """A Google worker account, a former admin, an unverified address: all refused."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        status_code = await post_to_mcp(app=app, token=token)

    assert status_code == 401


async def test_r20_6_sign_in_routes_are_at_the_root_of_the_service(
    mcp_database_url: str,
    tmp_path: Path,
) -> None:
    """MCP clients find the sign-in where the OAuth client of the service sends Google back."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        async with build_http_client(app=app) as http_client:
            response = await http_client.get('/.well-known/oauth-protected-resource/mcp')
        route_paths = {route.path for route in app.routes[1].routes}

    assert response.status_code == 200
    assert response.json()['resource'] == f'{BASE_URL}/mcp'
    assert '/auth/callback' in route_paths


@pytest.mark.parametrize(
    'redirect_uri',
    [
        'https://claude.ai/api/mcp/auth_callback',
        'https://claude.com/api/mcp/auth_callback',
        'http://localhost:33418/callback',
        'http://127.0.0.1:6274/oauth/callback',
    ],
)
async def test_r20_23_known_mcp_client_registers_and_reaches_the_consent_step(
    mcp_database_url: str,
    tmp_path: Path,
    redirect_uri: str,
) -> None:
    """Claude, Claude Code, the MCP Inspector: their redirect addresses are accepted."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    async with serve_mcp_app(settings=settings) as app:
        async with build_http_client(app=app) as http_client:
            registration = {'redirect_uris': [redirect_uri], 'client_name': 'Claude'}
            response = await http_client.post('/register', json=registration)
            client_id = response.json()['client_id']
            parameters = build_authorize_parameters(client_id=client_id, redirect_uri=redirect_uri)
            authorize_response = await http_client.get('/authorize', params=parameters)

    assert response.status_code == 201
    assert authorize_response.status_code == 302
    assert '/consent?' in authorize_response.headers['location']


@pytest.mark.parametrize(
    'redirect_uri',
    [
        'https://attacker.example/callback',
        'https://claude.ai.attacker.example/api/mcp/auth_callback',
        'https://claude.ai/somewhere/else',
        'https://localhost:3000/callback',
        'http://localhost@attacker.example/callback',
    ],
)
async def test_r20_23_client_with_another_redirect_address_cannot_register(
    mcp_database_url: str,
    tmp_path: Path,
    redirect_uri: str,
) -> None:
    """Nobody can register a client that sends an admin's sign-in to an address of their own."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    registration = {'redirect_uris': [redirect_uri], 'client_name': 'Claude'}
    async with serve_mcp_app(settings=settings) as app:
        async with build_http_client(app=app) as http_client:
            response = await http_client.post('/register', json=registration)

    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_redirect_uri'


async def test_r20_23_sign_in_to_another_redirect_address_is_refused(
    mcp_database_url: str,
    tmp_path: Path,
) -> None:
    """Without registering, under the client ID of the OAuth client itself: refused as well."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    parameters = build_authorize_parameters(
        client_id=settings.mcp_google_client_id,
        redirect_uri='https://attacker.example/callback',
    )
    async with serve_mcp_app(settings=settings) as app:
        async with build_http_client(app=app) as http_client:
            response = await http_client.get('/authorize', params=parameters)

    assert response.status_code == 400
    assert 'location' not in response.headers


@pytest.mark.parametrize('mcp_database_url', [None, ''])
async def test_r20_7_test_without_mcp_database_serves_the_public_endpoint_only(
    mcp_database_url: Optional[str],
) -> None:
    """Without the MCP database user, or with an empty line in .env, /mcp is not served."""
    settings = McpSettings(app_env='TEST', mcp_database_url=mcp_database_url)
    async with serve_mcp_app(settings=settings) as app:
        status_code = await post_to_mcp(app=app)

    assert status_code == 404


@pytest.mark.parametrize(
    ('extra_headers', 'status_code'),
    [
        ({'Host': 'attacker.example'}, 421),
        ({'Host': 'attacker.example:8081'}, 421),
        ({'Origin': 'https://attacker.example'}, 403),
    ],
)
async def test_r20_7_without_sign_in_mcp_answers_only_the_developer_machine(
    mcp_database_url: str,
    extra_headers: dict[str, str],
    status_code: int,
) -> None:
    """A web page whose own name points to 127.0.0.1 (DNS rebinding) cannot reach the tools."""
    settings = McpSettings(app_env='TEST', mcp_host=LOCAL_HOST, mcp_database_url=mcp_database_url)
    async with serve_mcp_app(settings=settings) as app:
        response_status = await post_to_mcp(app=app, extra_headers=extra_headers)

    assert response_status == status_code


async def test_r20_7_with_sign_in_mcp_answers_its_public_address(
    mcp_database_url: str,
    tmp_path: Path,
) -> None:
    """In Cloud Run the address is the service's own: the token decides, not the host check."""
    settings = build_sign_in_settings(mcp_database_url=mcp_database_url, oauth_folder=tmp_path)
    extra_headers = {'Host': 'dimonapp-mcp-acc.example.run.app'}
    async with serve_mcp_app(settings=settings) as app:
        status_code = await post_to_mcp(app=app, extra_headers=extra_headers)

    assert status_code == 401


async def test_r20_8_test_serves_the_data_tools_at_mcp(mcp_database_url: str) -> None:
    """Locally the tools may run without sign-in, on the local database (FDS 15.2)."""
    settings = McpSettings(app_env='TEST', mcp_host=LOCAL_HOST, mcp_database_url=mcp_database_url)
    async with serve_mcp_app(settings=settings) as app:
        async with connect_mcp_client(app=app, path='/mcp') as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                name='summarise_period',
                arguments={'start': '2026-10-01', 'end': '2026-10-31'},
            )

    assert len(tools) == 4
    assert result.structured_content['start'] == '2026-10-01'
