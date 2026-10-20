"""Streamlit secrets file generated from environment variables (R2.4, R2.7, R4.10)."""

import tomllib
from pathlib import Path
from typing import Optional

import pytest

from dimonapp.secrets_file import SECRETS_PATH, main, write_secrets_file
from dimonapp.settings import Settings

REPOSITORY_ROOT = Path(__file__).parent.parent
DATABASE_URL = 'postgresql+psycopg://user:password@localhost:5432/database'


def build_settings(google_client_secret: Optional[str]) -> Settings:
    """Build settings with Google sign-in filled in, except possibly the client secret."""
    return Settings(
        _env_file=None,
        app_env='TEST',
        database_url=DATABASE_URL,
        auth_redirect_uri='http://localhost:8501/oauth2callback',
        auth_cookie_secret='cookie "secret" with quotes',
        google_client_id='client-id',
        google_client_secret=google_client_secret,
    )


def test_r2_4_secrets_file_holds_the_auth_section(tmp_path: Path) -> None:
    """The written file parses back to the [auth] values st.login needs."""
    settings = build_settings(google_client_secret='client-secret')
    secrets_path = tmp_path / '.streamlit' / 'secrets.toml'

    is_written = write_secrets_file(settings=settings, path=secrets_path)

    with secrets_path.open('rb') as secrets_file:
        secrets = tomllib.load(secrets_file)
    assert is_written
    assert secrets == {
        'auth': {
            'redirect_uri': 'http://localhost:8501/oauth2callback',
            'cookie_secret': 'cookie "secret" with quotes',
            'client_id': 'client-id',
            'client_secret': 'client-secret',
            'server_metadata_url': 'https://accounts.google.com/.well-known/openid-configuration',
        },
    }


def test_r2_7_secrets_file_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    """The file with the client secret is not readable by other users."""
    settings = build_settings(google_client_secret='client-secret')
    secrets_path = tmp_path / 'secrets.toml'

    write_secrets_file(settings=settings, path=secrets_path)

    assert secrets_path.stat().st_mode & 0o777 == 0o600


def test_r2_4_no_secrets_file_without_google_sign_in(tmp_path: Path) -> None:
    """Nothing is written when a Google sign-in variable is missing."""
    settings = build_settings(google_client_secret=None)
    secrets_path = tmp_path / 'secrets.toml'

    is_written = write_secrets_file(settings=settings, path=secrets_path)

    assert not is_written
    assert not secrets_path.exists()


def test_r2_7_repository_ignores_secret_files() -> None:
    """Git never tracks the local .env or the generated Streamlit secrets file."""
    ignored = (REPOSITORY_ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()

    assert '.env' in ignored
    assert '.streamlit/secrets.toml' in ignored


def test_r2_7_docker_image_excludes_secret_files() -> None:
    """The Docker build context leaves out the local .env, the secrets file and key files."""
    excluded = (REPOSITORY_ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()

    assert '.env' in excluded
    assert '.streamlit/secrets.toml' in excluded
    assert '*.pem' in excluded


def test_r4_10_secrets_file_is_generated_from_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command `make run` calls writes the [auth] section from the environment alone."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('AUTH_REDIRECT_URI', 'http://localhost:8501/oauth2callback')
    monkeypatch.setenv('AUTH_COOKIE_SECRET', 'cookie-secret')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client-id')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'client-secret')

    main()

    with SECRETS_PATH.open('rb') as secrets_file:
        secrets = tomllib.load(secrets_file)
    assert secrets['auth']['client_id'] == 'client-id'
    assert secrets['auth']['client_secret'] == 'client-secret'
