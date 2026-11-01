"""Settings of the MCP service, read from environment variables (FDS section 15.3, R2.4).

The MCP service has a small set of settings of its own. It never receives the database URL
of the application, its sign-in secrets or the Dimona key (R20.9), so it cannot use
`Settings`, which needs some of them. Its own Google sign-in values have names of their own,
so the local .env file can hold those of the application next to them.
"""

from typing import Optional, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dimonapp.settings import AppEnvironment

# The only environment where the data tools may run without sign-in, against the fake data of
# the local database (FDS 15.2).
LOCAL_ENVIRONMENT = 'TEST'
# The addresses that only the developer's own machine reaches; the data tools without sign-in
# listen on nothing else (R20.7).
LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '::1')

# What the Google sign-in of /mcp cannot work without (R20.6, R20.9).
SIGN_IN_SETTINGS = (
    'mcp_base_url',
    'mcp_google_client_id',
    'mcp_google_client_secret',
    'mcp_jwt_signing_key',
    'mcp_oauth_folder',
)


class McpSettings(BaseSettings):
    """Every value the MCP service needs from its environment.

    Locally the values come from the git-ignored .env file, in GCP from the Cloud Run service.
    Real environment variables win over the .env file.
    """

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )

    app_env: AppEnvironment
    port: int = 8080
    # Every network interface in the container; `make mcp` keeps it on the developer's machine,
    # as the data tools without sign-in need (R20.7).
    mcp_host: str = '0.0.0.0'
    # The name of the service, which Cloud Run sets in every container; never set locally.
    k_service: Optional[str] = None
    # The connection URL of the MCP service's own database user, a member of the read-only role
    # dimonapp_mcp (R20.10); never the URL of the application. Never printed with the settings.
    mcp_database_url: Optional[str] = Field(default=None, repr=False)
    # Sign in to the database as the Cloud SQL IAM user of the service account, with a token of
    # that account as the password, instead of a password in the URL (FDS 15.4, open item 9).
    mcp_database_iam_login: bool = False

    # Google sign-in of /mcp (FDS 15.3): the public address of the service, its own OAuth
    # client, the key that signs the tokens of the OAuth proxy and the folder where the proxy
    # keeps its encrypted state. Never printed with the settings.
    mcp_base_url: Optional[str] = None
    mcp_google_client_id: Optional[str] = None
    mcp_google_client_secret: Optional[str] = Field(default=None, repr=False)
    mcp_jwt_signing_key: Optional[str] = Field(default=None, repr=False)
    mcp_oauth_folder: Optional[str] = None

    @model_validator(mode='after')
    def check_sign_in_settings(self) -> Self:
        """Refuse to start with sign-in half configured, or in ACC or PROD without it (R20.7).

        In TEST the data tools may run without sign-in, but only on the developer's machine:
        a deployment with APP_ENV=TEST by mistake does not start. The data tools are then never
        online without sign-in.
        """
        missing = [name for name in SIGN_IN_SETTINGS if not getattr(self, name)]
        if missing and len(missing) < len(SIGN_IN_SETTINGS):
            names = ', '.join(missing)
            raise ValueError(f'The sign-in of the MCP service needs these settings: {names}.')
        if self.app_env == LOCAL_ENVIRONMENT:
            serves_tools_without_sign_in = bool(missing) and bool(self.mcp_database_url)
            if serves_tools_without_sign_in and not is_on_developer_machine(settings=self):
                raise ValueError(
                    "Without sign-in, /mcp is only served on the developer's machine: set "
                    'MCP_HOST to 127.0.0.1, outside Cloud Run.'
                )
            return self
        if missing:
            raise ValueError(f'APP_ENV={self.app_env} needs the sign-in of the MCP service.')
        if not self.mcp_database_url:
            raise ValueError(f'APP_ENV={self.app_env} needs mcp_database_url.')
        return self


def is_on_developer_machine(settings: McpSettings) -> bool:
    """Tell whether the service listens on a loopback address only, outside Cloud Run."""
    return settings.k_service is None and settings.mcp_host in LOOPBACK_HOSTS


def has_sign_in(settings: McpSettings) -> bool:
    """Tell whether the Google sign-in of /mcp is configured."""
    return all(getattr(settings, name) for name in SIGN_IN_SETTINGS)


def load_mcp_settings() -> McpSettings:
    """Read and validate the settings of the MCP service."""
    return McpSettings()
