"""The sign-in of /mcp: the Google e-mail and the store of the OAuth proxy (R20.6, R20.9)."""

from pathlib import Path
from typing import Any

import pytest
from fastmcp.server.auth import AccessToken

from dimonapp.mcp_auth import build_oauth_storage, read_verified_email

SIGNING_KEY = 'mcp-signing-key-made-up-for-the-tests-of-the-oauth-store'
UPSTREAM_TOKEN = 'ya29.google-access-token-made-up-for-the-tests'


def build_google_token(claims: dict[str, Any]) -> AccessToken:
    """Give a checked Google token with these claims."""
    return AccessToken(token='google-token', client_id='google', scopes=['openid'], claims=claims)


@pytest.mark.parametrize('email_verified', [True, 'true'])
def test_r20_6_verified_email_is_read_from_the_token(email_verified: Any) -> None:
    """Google gives the verification as a boolean or as text, depending on the endpoint."""
    claims = {'email': 'admin@example.com', 'email_verified': email_verified}
    access_token = build_google_token(claims=claims)

    assert read_verified_email(access_token=access_token) == 'admin@example.com'


@pytest.mark.parametrize(
    'claims',
    [
        {'email': 'admin@example.com', 'email_verified': 'false'},
        {'email': 'admin@example.com'},
        {'email_verified': 'true'},
        {},
    ],
)
def test_r20_6_unverified_or_missing_email_gives_nothing(claims: dict[str, Any]) -> None:
    """An address Google has not verified proves nothing about its owner."""
    access_token = build_google_token(claims=claims)

    assert read_verified_email(access_token=access_token) is None


def read_stored_bytes(folder: Path) -> bytes:
    """Give the content of every file the store wrote in its folder."""
    files = [path for path in folder.rglob('*') if path.is_file()]
    return b''.join(path.read_bytes() for path in files)


async def test_r20_9_oauth_store_keeps_its_values_encrypted_on_disk(tmp_path: Path) -> None:
    """A Google token held for an MCP client never lies in the folder as plain text."""
    store = build_oauth_storage(folder=tmp_path, jwt_signing_key=SIGNING_KEY)
    await store.put(key='upstream', value={'access_token': UPSTREAM_TOKEN}, collection='tokens')

    stored_bytes = read_stored_bytes(folder=tmp_path)

    assert stored_bytes
    assert UPSTREAM_TOKEN.encode() not in stored_bytes


async def test_r20_9_oauth_store_survives_a_restart(tmp_path: Path) -> None:
    """A new instance of the service, with the same folder and key, reads what was stored."""
    first_store = build_oauth_storage(folder=tmp_path, jwt_signing_key=SIGNING_KEY)
    await first_store.put(key='client', value={'client_id': 'claude'}, collection='clients')

    next_store = build_oauth_storage(folder=tmp_path, jwt_signing_key=SIGNING_KEY)
    value = await next_store.get(key='client', collection='clients')

    assert value == {'client_id': 'claude'}


async def test_r20_9_oauth_store_reads_nothing_with_another_key(tmp_path: Path) -> None:
    """After a new signing key the old values count as missing: clients sign in again."""
    first_store = build_oauth_storage(folder=tmp_path, jwt_signing_key=SIGNING_KEY)
    await first_store.put(key='client', value={'client_id': 'claude'}, collection='clients')

    other_store = build_oauth_storage(folder=tmp_path, jwt_signing_key=f'{SIGNING_KEY}-new')
    value = await other_store.get(key='client', collection='clients')

    assert value is None
