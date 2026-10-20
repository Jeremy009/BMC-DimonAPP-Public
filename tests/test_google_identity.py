"""The interface around Streamlit's Google sign-in (R4.8)."""

import datetime
import importlib

import pytest

from dimonapp import google_identity
from dimonapp.google_identity import GoogleIdentity, is_google_configured, read_google_identity

# 14/10/2026 08:00 UTC, as Google gives it in the iat claim of the ID token
ISSUED_AT = 1791964800
SIGNED_IN_AT = datetime.datetime(2026, 10, 14, 8, 0, tzinfo=datetime.UTC)


class FakeStreamlitUser(dict):
    """Stand-in for st.user: a mapping with the is_logged_in attribute."""

    @property
    def is_logged_in(self) -> bool:
        """Tell whether the fake user carries an identity."""
        return bool(self)


def use_fake_user(monkeypatch: pytest.MonkeyPatch, user_info: dict[str, object]) -> None:
    """Make Google sign-in look configured, with the given st.user content."""
    monkeypatch.setattr(google_identity, 'is_google_configured', lambda: True)
    monkeypatch.setattr(google_identity.st, 'user', FakeStreamlitUser(user_info))


def test_r4_8_google_is_not_configured_without_secrets() -> None:
    """Without a Streamlit secrets file there is no Google sign-in, and no error either."""
    assert not is_google_configured()
    assert read_google_identity() is None


def test_r4_8_nobody_is_signed_in_before_google_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured application without Google session has no identity."""
    use_fake_user(monkeypatch=monkeypatch, user_info={})

    assert read_google_identity() is None


def test_r4_8_verified_google_account_gives_its_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """The e-mail, the name and the sign-in time come from the Google session (R4.13)."""
    user_info = {
        'email': 'lotte@example.com',
        'email_verified': True,
        'name': 'Lotte Exemple',
        'iat': ISSUED_AT,
    }
    use_fake_user(monkeypatch=monkeypatch, user_info=user_info)

    identity = read_google_identity()

    assert identity == GoogleIdentity(
        email='lotte@example.com',
        name='Lotte Exemple',
        signed_in_at=SIGNED_IN_AT,
    )


def test_r4_8_unverified_email_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """An address Google has not verified does not identify anyone."""
    user_info = {
        'email': 'lotte@example.com',
        'email_verified': False,
        'name': 'Lotte Exemple',
        'iat': ISSUED_AT,
    }
    use_fake_user(monkeypatch=monkeypatch, user_info=user_info)

    assert read_google_identity() is None


def test_r4_13_google_session_without_sign_in_time_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the time Google issued the sign-in, its 12 hours cannot be checked."""
    user_info = {'email': 'lotte@example.com', 'email_verified': True, 'name': 'Lotte Exemple'}
    use_fake_user(monkeypatch=monkeypatch, user_info=user_info)

    assert read_google_identity() is None


def test_r4_8_libraries_of_the_google_sign_in_are_installed() -> None:
    """Streamlit loads its sign-in client only when the button is clicked.

    A missing library (Authlib, or httpx behind it) would otherwise only show as an internal
    server error at the first sign-in.
    """
    starlette_client = importlib.import_module('authlib.integrations.starlette_client')

    assert hasattr(starlette_client, 'OAuth')
