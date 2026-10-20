"""Settings come from environment variables and the local .env file (R2.4, R2.5)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from dimonapp.settings import load_settings

DATABASE_URL = 'postgresql+psycopg://user:password@localhost:5432/database'


def test_r2_4_settings_are_read_from_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
) -> None:
    """Every setting is taken from its environment variable."""
    monkeypatch.setenv('APP_ENV', 'PROD')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('PORT', '9000')
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client-id')

    settings = load_settings()

    assert settings.app_env == 'PROD'
    assert settings.database_url == DATABASE_URL
    assert settings.port == 9000
    assert settings.google_client_id == 'client-id'
    assert settings.google_client_secret is None


def test_r2_4_missing_app_env_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application does not guess its environment label."""
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)

    with pytest.raises(ValidationError):
        load_settings()


def test_r2_4_missing_database_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application does not start without a database connection."""
    monkeypatch.setenv('APP_ENV', 'TEST')

    with pytest.raises(ValidationError):
        load_settings()


def test_r18_6_unknown_app_env_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only TEST, ACC and PROD are valid environment labels."""
    monkeypatch.setenv('APP_ENV', 'DEV')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)

    with pytest.raises(ValidationError):
        load_settings()


def test_r2_7_settings_error_does_not_show_the_values_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused configuration names the faulty setting without echoing any value."""
    monkeypatch.setenv('APP_ENV', 'not-a-valid-label')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)

    with pytest.raises(ValidationError) as error:
        load_settings()

    assert 'app_env' in str(error.value)
    assert 'not-a-valid-label' not in str(error.value)


def test_r2_5_settings_are_loaded_from_local_env_file(tmp_path: Path) -> None:
    """A .env file in the working directory is read, and its unrelated keys are ignored."""
    env_lines = ['APP_ENV=TEST', f'DATABASE_URL={DATABASE_URL}', 'UNRELATED_KEY=value']
    env_path = tmp_path / '.env'
    env_path.write_text('\n'.join(env_lines), encoding='utf-8')

    settings = load_settings()

    assert settings.app_env == 'TEST'
    assert settings.database_url == DATABASE_URL


def test_r2_5_environment_variable_wins_over_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rsz_environment: None,
) -> None:
    """A real environment variable overrides the value of the .env file."""
    env_lines = ['APP_ENV=TEST', f'DATABASE_URL={DATABASE_URL}']
    env_path = tmp_path / '.env'
    env_path.write_text('\n'.join(env_lines), encoding='utf-8')
    monkeypatch.setenv('APP_ENV', 'PROD')

    settings = load_settings()

    assert settings.app_env == 'PROD'


@pytest.mark.parametrize('app_env', ['ACC', 'PROD'])
def test_r2_3_environment_with_dimona_calls_needs_its_settings(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    """ACC and PROD do not start half configured, and name what is missing."""
    monkeypatch.setenv('APP_ENV', app_env)
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('DIMONA_ENTERPRISE_NUMBER', '0123456789')

    with pytest.raises(ValidationError) as error:
        load_settings()

    assert 'dimona_client_id' in str(error.value)
    assert 'dimona_enterprise_number' not in str(error.value)


def test_r2_7_environment_with_dimona_calls_needs_one_private_key(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
) -> None:
    """The key comes as text or as a file: not neither, not both."""
    monkeypatch.setenv('APP_ENV', 'ACC')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('DIMONA_PRIVATE_KEY_PATH', '/somewhere/company_key.pem')

    with pytest.raises(ValidationError):
        load_settings()

    monkeypatch.delenv('DIMONA_PRIVATE_KEY')
    monkeypatch.delenv('DIMONA_PRIVATE_KEY_PATH')
    with pytest.raises(ValidationError):
        load_settings()


def test_r2_3_test_environment_needs_no_dimona_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST makes no Dimona call, so it starts without any Dimona setting."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)

    settings = load_settings()

    assert settings.dimona_client_id is None


def test_r2_6_values_are_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret stored with a line break at its end is read without it."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:password@localhost/database\n')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', ' secret-value\n')
    monkeypatch.setenv('STORAGE_BUCKET', 'example-dimonapp-documents')
    monkeypatch.setenv('FIRST_ADMIN_EMAIL', 'ada@example.com')

    settings = load_settings()

    assert settings.database_url == 'postgresql+psycopg://user:password@localhost/database'
    assert settings.google_client_secret == 'secret-value'
    assert settings.storage_bucket == 'example-dimonapp-documents'
    assert settings.first_admin_email == 'ada@example.com'
