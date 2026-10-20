"""Generation of .streamlit/secrets.toml from environment variables (FDS 3.6).

st.login reads its settings from secrets.toml, while every setting of the application
comes from environment variables. The file is written at start-up and never committed.
"""

import logging
from pathlib import Path
from typing import Optional

import tomli_w

from dimonapp.settings import Settings, load_settings

logger = logging.getLogger(__name__)

SECRETS_PATH = Path('.streamlit') / 'secrets.toml'
GOOGLE_METADATA_URL = 'https://accounts.google.com/.well-known/openid-configuration'


def build_auth_secrets(settings: Settings) -> Optional[dict[str, str]]:
    """Build the [auth] values for st.login, or None when Google sign-in is not configured."""
    auth_secrets = {
        'redirect_uri': settings.auth_redirect_uri,
        'cookie_secret': settings.auth_cookie_secret,
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
    }
    if not all(auth_secrets.values()):
        return None
    return {**auth_secrets, 'server_metadata_url': GOOGLE_METADATA_URL}


def write_secrets_file(settings: Settings, path: Path) -> bool:
    """Write the Streamlit secrets file and tell whether it was written.

    Nothing is written when the Google sign-in variables are not all set.
    """
    auth_secrets = build_auth_secrets(settings=settings)
    if auth_secrets is None:
        logger.warning('Google sign-in is not configured, no Streamlit secrets file written.')
        return False

    content = tomli_w.dumps({'auth': auth_secrets})
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create the file readable by its owner only before any secret goes in.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(content, encoding='utf-8')
    logger.info('Streamlit secrets file written.')
    return True


def main() -> None:
    """Write the secrets file from the local settings; `make run` calls this before Streamlit."""
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    write_secrets_file(settings=settings, path=SECRETS_PATH)


if __name__ == '__main__':
    main()
