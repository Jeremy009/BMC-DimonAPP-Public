"""The MCP service reads its own, small set of settings (R2.4, R20.7, R20.9)."""

import pytest
from pydantic import ValidationError

from dimonapp.mcp_settings import McpSettings, has_sign_in, load_mcp_settings

SIGN_IN_ENVIRONMENT = {
    'MCP_BASE_URL': 'https://mcp.example.com',
    'MCP_GOOGLE_CLIENT_ID': 'mcp-client.apps.googleusercontent.com',
    'MCP_GOOGLE_CLIENT_SECRET': 'mcp-client-secret',
    'MCP_JWT_SIGNING_KEY': 'mcp-signing-key-of-sixty-four-characters-or-so-made-up-for-tests',
    'MCP_OAUTH_FOLDER': 'oauth',
}


@pytest.fixture
def sign_in_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set made-up values for the Google sign-in of /mcp."""
    for name, value in SIGN_IN_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_r2_4_mcp_settings_are_read_from_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment, the port and the host come from environment variables."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('PORT', '9000')
    monkeypatch.setenv('MCP_HOST', '127.0.0.1')

    settings = load_mcp_settings()

    assert settings.app_env == 'TEST'
    assert settings.port == 9000
    assert settings.mcp_host == '127.0.0.1'


def test_r2_4_mcp_service_listens_on_every_interface_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In the container, Cloud Run reaches the service on port 8080 of any interface."""
    monkeypatch.setenv('APP_ENV', 'TEST')

    settings = load_mcp_settings()

    assert settings.port == 8080
    assert settings.mcp_host == '0.0.0.0'


def test_r2_4_mcp_service_without_app_env_is_refused() -> None:
    """The MCP service does not guess its environment either."""
    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_r20_9_mcp_settings_hold_no_secret_of_the_application() -> None:
    """The MCP service gets neither the database URL, the sign-in secrets nor the Dimona key.

    Its own sign-in values have names of their own.
    """
    setting_names = set(McpSettings.model_fields)

    assert setting_names == {
        'app_env',
        'port',
        'mcp_host',
        'k_service',
        'mcp_database_url',
        'mcp_database_iam_login',
        'mcp_base_url',
        'mcp_google_client_id',
        'mcp_google_client_secret',
        'mcp_jwt_signing_key',
        'mcp_oauth_folder',
    }


def test_r20_9_mcp_settings_ignore_the_google_client_of_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The application's Google client, in the same .env locally, is not the MCP service's."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'app-client.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'app-client-secret')

    settings = load_mcp_settings()

    assert settings.mcp_google_client_id is None
    assert settings.mcp_google_client_secret is None


@pytest.mark.parametrize('app_env', ['ACC', 'PROD'])
def test_r20_7_mcp_service_refuses_to_start_without_sign_in(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    """In acceptance and production the data tools are never online without sign-in."""
    monkeypatch.setenv('APP_ENV', app_env)
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')

    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_r20_7_mcp_service_refuses_to_start_without_its_database_user(
    monkeypatch: pytest.MonkeyPatch,
    sign_in_environment: None,
) -> None:
    """In acceptance the MCP service is there for /mcp, which needs its database user."""
    monkeypatch.setenv('APP_ENV', 'ACC')

    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_r20_7_mcp_service_starts_in_acceptance_with_sign_in(
    monkeypatch: pytest.MonkeyPatch,
    sign_in_environment: None,
) -> None:
    """With sign-in and its database user, acceptance loads its settings."""
    monkeypatch.setenv('APP_ENV', 'ACC')
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')
    monkeypatch.setenv('MCP_DATABASE_IAM_LOGIN', 'true')

    settings = load_mcp_settings()

    assert has_sign_in(settings=settings)
    assert settings.mcp_database_iam_login


def test_r20_7_half_configured_sign_in_is_refused_in_test(
    monkeypatch: pytest.MonkeyPatch,
    sign_in_environment: None,
) -> None:
    """A missing sign-in value is a mistake, not a choice to run without sign-in."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.delenv('MCP_JWT_SIGNING_KEY')

    with pytest.raises(ValidationError):
        load_mcp_settings()


@pytest.mark.parametrize('mcp_host', ['127.0.0.1', 'localhost', '::1'])
def test_r20_7_test_may_run_without_sign_in_on_the_developer_machine(
    monkeypatch: pytest.MonkeyPatch,
    mcp_host: str,
) -> None:
    """Locally the tools may run without sign-in, on the local database (FDS 15.2)."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('MCP_HOST', mcp_host)
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')

    settings = load_mcp_settings()

    assert not has_sign_in(settings=settings)


@pytest.mark.parametrize('mcp_host', ['0.0.0.0', '192.168.1.20', '::'])
def test_r20_7_test_without_sign_in_refuses_to_listen_beyond_the_machine(
    monkeypatch: pytest.MonkeyPatch,
    mcp_host: str,
) -> None:
    """Every interface, a local network address: the tools would be open to other machines."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('MCP_HOST', mcp_host)
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')

    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_r20_7_test_without_sign_in_refuses_to_start_in_cloud_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment with APP_ENV=TEST by mistake does not put the tools online without sign-in."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('K_SERVICE', 'dimonapp-mcp-acc')
    monkeypatch.setenv('MCP_HOST', '127.0.0.1')
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')

    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_r20_7_test_with_sign_in_may_run_in_cloud_run(
    monkeypatch: pytest.MonkeyPatch,
    sign_in_environment: None,
) -> None:
    """With sign-in, the check of the developer's machine does not apply."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('K_SERVICE', 'dimonapp-mcp-test')
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp@localhost/db')

    settings = load_mcp_settings()

    assert has_sign_in(settings=settings)
    assert settings.k_service == 'dimonapp-mcp-test'


def test_r20_7_test_without_mcp_database_may_listen_on_every_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without its database user the service only serves the public endpoint, which has no data."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('K_SERVICE', 'dimonapp-mcp-test')

    settings = load_mcp_settings()

    assert settings.mcp_host == '0.0.0.0'


def test_r20_10_mcp_database_url_is_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The connection URL of the MCP database user holds its password."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('MCP_HOST', '127.0.0.1')
    monkeypatch.setenv('MCP_DATABASE_URL', 'postgresql+psycopg://mcp:secret-word@localhost/db')

    settings = load_mcp_settings()

    assert settings.mcp_database_url.endswith('@localhost/db')
    assert 'secret-word' not in repr(settings)


def test_r20_9_sign_in_secrets_are_never_printed(
    monkeypatch: pytest.MonkeyPatch,
    sign_in_environment: None,
) -> None:
    """The client secret and the signing key stay out of the printed settings."""
    monkeypatch.setenv('APP_ENV', 'TEST')

    settings = load_mcp_settings()

    assert 'mcp-client-secret' not in repr(settings)
    assert 'mcp-signing-key' not in repr(settings)
    assert 'mcp-client.apps.googleusercontent.com' in repr(settings)
