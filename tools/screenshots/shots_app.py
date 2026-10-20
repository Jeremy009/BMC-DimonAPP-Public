"""DimonAPP for the screenshots: `?as=admin` in the address signs in as the seeded admin.

Google is never called. Without the parameter the application runs unchanged.
"""

import datetime
import runpy
from pathlib import Path

import streamlit as st

import dimonapp
from dimonapp import google_identity
from dimonapp.fake_data import FAKE_ADMIN_EMAIL
from dimonapp.google_identity import GoogleIdentity

APP_PATH = Path(dimonapp.__file__).parent / 'app.py'
SIGNED_IN_AT = datetime.datetime.now(tz=datetime.UTC)


def read_demo_identity() -> GoogleIdentity | None:
    """Give the admin identity when the address asks for it."""
    if st.query_params.get('as') != 'admin':
        return None
    return GoogleIdentity(email=FAKE_ADMIN_EMAIL, name='Admin Démo', signed_in_at=SIGNED_IN_AT)


google_identity.read_google_identity = read_demo_identity
runpy.run_path(str(APP_PATH), run_name='__main__')
