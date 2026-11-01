"""Google sign-in of /mcp, for active admins only (FDS 15.2 and 15.3, R20.6, R20.9, R20.23).

FastMCP's GoogleProvider is an OAuth proxy in front of Google. Google offers no dynamic client
registration, so MCP clients register with the proxy instead, or name themselves by the address
of a client description (CIMD), as Claude does; the proxy sends the sign-in back only to known
redirect addresses. The admin signs in with Google and the proxy hands the client a token of
its own, signed with a key from Secret Manager. On every request to /mcp the proxy checks
that token and the Google token behind it. Here the e-mail of that Google account must then
also be an active admin, asked of the database function is_active_admin, so any other account
is refused before a tool is reached, a Google worker account included.
"""

import logging
from functools import partial
from pathlib import Path
from typing import Any, Optional

import anyio
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.google import GoogleProvider
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from dimonapp.mcp_settings import McpSettings

logger = logging.getLogger(__name__)

# openid identifies the Google account, email gives its address for the admin check.
GOOGLE_SCOPES = ['openid', 'email']
# Derives the key that encrypts the store of the OAuth proxy from its signing key.
STORAGE_KEY_SALT = 'dimonapp-mcp-oauth-storage'
# The only redirect addresses the proxy sends a sign-in back to (R20.23): Claude's, and any port
# and path on the admin's own machine, for Claude Code, the MCP Inspector and FastMCP's client.
# Anyone may register a client, so any other address could hand an admin's sign-in to someone
# else once the admin approves it.
ALLOWED_REDIRECT_URIS = (
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    'http://localhost:*',
    'http://127.0.0.1:*',
)


def check_active_admin(engine: sa.Engine, email: str) -> bool:
    """Ask the database whether the e-mail is an active admin (R20.13)."""
    query = sa.text('SELECT mcp.is_active_admin(:email)')
    with engine.connect() as connection:
        return bool(connection.scalar(query, {'email': email}))


def read_verified_email(access_token: AccessToken) -> Optional[str]:
    """Give the e-mail of the Google account behind a token, if Google has verified it.

    An address Google has not verified proves nothing about its owner. Google's tokeninfo
    gives email_verified as the text 'true', its userinfo as a boolean.
    """
    claims = access_token.claims or {}
    email = claims.get('email')
    is_verified = claims.get('email_verified') in (True, 'true')
    if not email or not is_verified:
        return None
    return email


class AdminGoogleProvider(GoogleProvider):
    """GoogleProvider that lets in active admins only.

    A subclass, because FastMCP checks the token of every request through a method of its
    provider; the admin check runs there, on top of Google's.
    """

    def __init__(self, *, engine: sa.Engine, **options: Any) -> None:
        """Set up the Google sign-in with the options of GoogleProvider."""
        super().__init__(**options)
        self.engine = engine

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Check the token as GoogleProvider does, then refuse it unless an active admin's."""
        access_token = await super().load_access_token(token=token)
        if access_token is None:
            return None
        email = read_verified_email(access_token=access_token)
        if email is None:
            logger.warning('MCP sign-in refused: no verified e-mail.')
            return None
        # The database call blocks, so it runs in a worker thread, off the event loop.
        check = partial(check_active_admin, engine=self.engine, email=email)
        if not await anyio.to_thread.run_sync(check):
            logger.warning('MCP sign-in refused: not an active admin.')
            return None
        return access_token


def build_oauth_storage(folder: Path, jwt_signing_key: str) -> AsyncKeyValue:
    """Give the store of the OAuth proxy: encrypted files in a folder that survives restarts.

    The proxy keeps there the clients it registered and the Google tokens it holds for them.
    In GCP the folder is a Cloud Storage bucket that Cloud Run mounts, as the disk of an
    instance is lost on every restart and scale to zero. Every value is encrypted with a key
    derived from the signing key, so the bucket alone gives nothing away.
    """
    folder.mkdir(parents=True, exist_ok=True)
    encryption_key = derive_jwt_key(high_entropy_material=jwt_signing_key, salt=STORAGE_KEY_SALT)
    key_strategy = FileTreeV1KeySanitizationStrategy(directory=folder)
    collection_strategy = FileTreeV1CollectionSanitizationStrategy(directory=folder)
    file_store = FileTreeStore(
        data_directory=folder,
        key_sanitization_strategy=key_strategy,
        collection_sanitization_strategy=collection_strategy,
    )
    # A value that no longer decrypts, after a new signing key, counts as missing: the MCP
    # client then registers and signs in again.
    return FernetEncryptionWrapper(
        key_value=file_store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


def build_google_provider(settings: McpSettings, engine: sa.Engine) -> AdminGoogleProvider:
    """Build the Google sign-in of /mcp from the settings of the MCP service."""
    folder = Path(settings.mcp_oauth_folder)
    jwt_signing_key = settings.mcp_jwt_signing_key
    storage = build_oauth_storage(folder=folder, jwt_signing_key=jwt_signing_key)
    return AdminGoogleProvider(
        engine=engine,
        client_id=settings.mcp_google_client_id,
        client_secret=settings.mcp_google_client_secret,
        base_url=settings.mcp_base_url,
        required_scopes=GOOGLE_SCOPES,
        allowed_client_redirect_uris=list(ALLOWED_REDIRECT_URIS),
        client_storage=storage,
        jwt_signing_key=jwt_signing_key,
    )
