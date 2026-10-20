"""Container start-up: secrets file, database migrations, first admin, then Streamlit (FDS 3.6)."""

import logging
import os
from pathlib import Path

from dimonapp.database import create_database_engine, open_session, run_migrations
from dimonapp.first_admin import add_first_admin
from dimonapp.secrets_file import SECRETS_PATH, write_secrets_file
from dimonapp.settings import Settings, load_settings

logger = logging.getLogger(__name__)

APP_PATH = Path(__file__).parent / 'app.py'


def build_streamlit_command(port: int) -> list[str]:
    """Build the command that serves the application on every network interface."""
    return [
        'streamlit',
        'run',
        str(APP_PATH),
        f'--server.port={port}',
        '--server.address=0.0.0.0',
        '--server.headless=true',
    ]


def ensure_first_admin(settings: Settings) -> None:
    """Add the admin of FIRST_ADMIN_EMAIL when the environment has no admin yet (R4.11)."""
    if not settings.first_admin_email:
        return
    engine = create_database_engine(database_url=settings.database_url)
    with open_session(engine=engine) as session:
        add_first_admin(session=session, email=settings.first_admin_email)
    engine.dispose()


def main() -> None:
    """Prepare the container and hand the process over to Streamlit."""
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()

    # Write the Streamlit secrets file from the environment variables
    write_secrets_file(settings=settings, path=SECRETS_PATH)

    # Apply the database migrations before the application starts
    run_migrations()

    # Make sure somebody can sign in to a new environment
    ensure_first_admin(settings=settings)

    # Replace this process with Streamlit, so it receives the container signals
    command = build_streamlit_command(port=settings.port)
    logger.info('Starting Streamlit.')
    os.execvp(file=command[0], args=command)


if __name__ == '__main__':
    main()
