"""Small interface around Streamlit's built-in Google sign-in (R4.8).

Without an [auth] section in the Streamlit secrets, st.user has no is_logged_in attribute and
st.login fails, so every call first checks whether Google sign-in is configured. Tests replace
these functions; Google is never called from a test.
"""

import datetime
import logging
from typing import Optional

import streamlit as st
from pydantic import BaseModel
from streamlit.errors import StreamlitSecretNotFoundError

logger = logging.getLogger(__name__)


class GoogleIdentity(BaseModel):
    """What Google tells about the signed-in person."""

    email: str
    name: Optional[str]
    signed_in_at: datetime.datetime


def is_google_configured() -> bool:
    """Tell whether the Streamlit secrets hold the [auth] section st.login needs."""
    try:
        return 'auth' in st.secrets
    except StreamlitSecretNotFoundError:
        return False


def read_google_identity() -> Optional[GoogleIdentity]:
    """Give the Google identity of this browser session, or None when there is none.

    An address Google has not verified is ignored: it proves nothing about its owner. The time
    Google issued the sign-in (the iat claim of the ID token) is when the person signed in, so
    the sign-in can end after 12 hours (R4.13).
    """
    if not is_google_configured():
        return None
    if not st.user.is_logged_in:
        return None

    email = st.user.get('email')
    if not email or st.user.get('email_verified') is not True:
        logger.warning('Google identity ignored: no verified e-mail.')
        return None
    issued_at = st.user.get('iat')
    if not isinstance(issued_at, int):
        logger.warning('Google identity ignored: no sign-in time.')
        return None
    name = st.user.get('name')
    signed_in_at = datetime.datetime.fromtimestamp(timestamp=issued_at, tz=datetime.UTC)
    return GoogleIdentity(email=email, name=name, signed_in_at=signed_in_at)


def start_google_login() -> None:
    """Send the browser to Google to sign in."""
    st.login()


def end_google_login() -> None:
    """Forget the Google identity of this browser session."""
    st.logout()
