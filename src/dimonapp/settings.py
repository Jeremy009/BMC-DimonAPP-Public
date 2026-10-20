"""Application settings, read from environment variables (R2.4, R2.5).

APP_ENV names the environment and decides the Dimona service (R2.3): TEST makes no Dimona
call at all, ACC calls the RSZ test service, PROD calls the live service.
"""

from typing import Literal, Optional, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dimonapp.dimona import FakeDimonaOutcome

AppEnvironment = Literal['TEST', 'ACC', 'PROD']
# The only environment without Dimona calls: a fake service answers there (R2.3).
FAKE_DIMONA_ENVIRONMENT = 'TEST'

# What the real Dimona client cannot work without.
REQUIRED_DIMONA_SETTINGS = (
    'dimona_client_id',
    'dimona_enterprise_number',
    'dimona_employer_id',
    'dimona_joint_commission_article_17',
    'dimona_joint_commission_flexi_job',
)


class Settings(BaseSettings):
    """Every value the application needs from its environment.

    Locally the values come from the git-ignored .env file, in GCP from Secret Manager.
    Real environment variables win over the .env file.
    """

    # Validation errors never echo the values read, so no secret reaches the page or the logs.
    # Values are trimmed: a secret typed or piped into Secret Manager often ends with a line
    # break, which would silently break a sign-in or a connection.
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )

    app_env: AppEnvironment
    database_url: str
    port: int = 8080

    # Where the uploaded contracts and qualifications go: the Cloud Storage bucket named here
    # (GCP), or without one the local folder (development).
    storage_bucket: Optional[str] = None
    storage_folder: str = 'local_storage'

    # The Google address that becomes the admin of an environment whose admins table is still
    # empty (R4.11). Without effect once an admin exists.
    first_admin_email: Optional[str] = None

    # Google sign-in, used to generate .streamlit/secrets.toml.
    auth_redirect_uri: Optional[str] = None
    auth_cookie_secret: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

    # How the fake Dimona service of TEST answers every call: accept, reject or timeout.
    fake_dimona_outcome: FakeDimonaOutcome = 'accept'

    # BMC at the RSZ Dimona service, needed in ACC and PROD. The service itself (test or
    # live) follows from APP_ENV and is not a setting, so the two can never be mixed up.
    dimona_client_id: Optional[str] = None
    dimona_enterprise_number: Optional[str] = None
    dimona_employer_id: Optional[str] = None
    dimona_joint_commission_article_17: Optional[str] = None
    dimona_joint_commission_flexi_job: Optional[str] = None

    # The private key registered at the RSZ: its PEM text, or the path of a PEM file outside
    # the repository (R2.7). Never printed with the settings.
    dimona_private_key: Optional[str] = Field(default=None, repr=False)
    dimona_private_key_path: Optional[str] = None
    dimona_private_key_password: Optional[str] = Field(default=None, repr=False)

    # Read by `make seed` only, to make the fake accounts of the local database usable.
    seed_admin_email: Optional[str] = None
    seed_password: Optional[str] = None

    @model_validator(mode='after')
    def check_dimona_settings(self) -> Self:
        """Refuse to start in ACC or PROD with the Dimona service half configured.

        A missing value would otherwise only show up when a worker declares an activity.
        """
        if self.app_env == FAKE_DIMONA_ENVIRONMENT:
            return self
        missing = [name for name in REQUIRED_DIMONA_SETTINGS if not getattr(self, name)]
        if missing:
            names = ', '.join(missing)
            raise ValueError(f'APP_ENV={self.app_env} needs these settings: {names}.')
        has_key_text = bool(self.dimona_private_key)
        has_key_path = bool(self.dimona_private_key_path)
        if has_key_text == has_key_path:
            raise ValueError(
                f'APP_ENV={self.app_env} needs exactly one of dimona_private_key and '
                'dimona_private_key_path.'
            )
        return self


def load_settings() -> Settings:
    """Read and validate the settings from the environment and the local .env file."""
    return Settings()
