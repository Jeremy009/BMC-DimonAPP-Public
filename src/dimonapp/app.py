"""Streamlit entry point of DimonAPP: sign-in, then the view of the account type (R1.8)."""

import datetime
import logging
from typing import Optional

import sqlalchemy as sa
import streamlit as st

from dimonapp.admin_console import render_admin_console
from dimonapp.authentication import (
    SignedInUser,
    find_google_user,
    is_deactivated_google_account,
    load_local_worker,
)
from dimonapp.clock import read_now, read_today
from dimonapp.database import create_database_engine, open_session
from dimonapp.frame import render_frame
from dimonapp.google_identity import GoogleIdentity, end_google_login, read_google_identity
from dimonapp.last_actions import read_last_action, record_last_action
from dimonapp.login_page import (
    LOCAL_SIGNED_IN_AT_KEY,
    LOCAL_WORKER_KEY,
    SESSION_EXPIRED_KEY,
    render_login_page,
)
from dimonapp.rsz_dimona import build_dimona_client
from dimonapp.session_timeout import is_session_expired
from dimonapp.settings import load_settings
from dimonapp.storage import FileStorage, build_file_storage
from dimonapp.widgets import forget_action_requests
from dimonapp.worker_view import render_worker_view

logger = logging.getLogger(__name__)


@st.cache_resource
def get_database_engine(database_url: str) -> sa.Engine:
    """Give the one database engine of this process; Streamlit reruns the script on each click."""
    return create_database_engine(database_url=database_url)


@st.cache_resource
def get_file_storage(storage_bucket: Optional[str], storage_folder: str) -> FileStorage:
    """Give the one document storage of this process, so the bucket client is made once."""
    return build_file_storage(storage_bucket=storage_bucket, storage_folder=storage_folder)


def find_signed_in_user(
    engine: sa.Engine,
    google_identity: Optional[GoogleIdentity],
) -> Optional[SignedInUser]:
    """Find the account of this browser session: a local worker first, then the Google identity.

    The account is read from the database on every rerun, so a deactivated account loses
    access at once (R4.7).
    """
    with open_session(engine=engine) as session:
        # Local worker kept in the session state after the username and password form
        worker_id = st.session_state.get(LOCAL_WORKER_KEY)
        if worker_id is not None:
            user = load_local_worker(session=session, worker_id=worker_id)
            if user is not None:
                return user
            forget_browser_session()

        # Google identity, matched to the admins and then to the Google workers
        if google_identity is None:
            return None
        email = google_identity.email
        google_name = google_identity.name
        return find_google_user(session=session, email=email, google_name=google_name)


def is_google_identity_deactivated(
    engine: sa.Engine,
    google_identity: Optional[GoogleIdentity],
) -> bool:
    """Tell whether the refused Google identity is a deactivated account (R4.12)."""
    if google_identity is None:
        return False
    with open_session(engine=engine) as session:
        return is_deactivated_google_account(session=session, email=google_identity.email)


def forget_browser_session() -> None:
    """Forget everything this browser session holds but the notice of an expired sign-in.

    The local worker, the forms, the choices and the pending actions all go, so whoever signs
    in next in the same tab starts afresh, as after Google's sign-out, which opens a new
    session (R4.13).
    """
    is_expired = st.session_state.get(SESSION_EXPIRED_KEY, False)
    st.session_state.clear()
    if is_expired:
        st.session_state[SESSION_EXPIRED_KEY] = True


def is_sign_in_expired(
    engine: sa.Engine,
    user: SignedInUser,
    google_identity: Optional[GoogleIdentity],
    now: datetime.datetime,
) -> bool:
    """Tell whether the sign-in of this browser session is over, and note this action (R4.13).

    A local worker signed in at the time kept by the login form, anyone else when Google says.
    Every rerun is an action of the person, so it starts the 30 idle minutes again. The last
    action is kept per account in the database, so a refresh or a new tab does not start them
    again. An expired sign-in notes nothing, or the next tab would find a fresh action.
    """
    if LOCAL_WORKER_KEY in st.session_state:
        signed_in_at = st.session_state[LOCAL_SIGNED_IN_AT_KEY]
    else:
        signed_in_at = google_identity.signed_in_at
    account_kind = user.kind
    account_id = user.account_id
    with open_session(engine=engine) as session:
        last_action_at = read_last_action(
            session=session,
            account_kind=account_kind,
            account_id=account_id,
        )
        is_expired = is_session_expired(
            signed_in_at=signed_in_at,
            last_action_at=last_action_at,
            now=now,
        )
        if not is_expired:
            record_last_action(
                session=session,
                account_kind=account_kind,
                account_id=account_id,
                acted_at=now,
            )
    return is_expired


def sign_out(google_identity: Optional[GoogleIdentity]) -> None:
    """Forget the signed-in account and this browser session, and show the login page again."""
    forget_browser_session()
    if google_identity is None:
        st.rerun()
    # Streamlit redirects the browser itself after a Google sign-out
    end_google_login()
    st.stop()


def main() -> None:
    """Render the page frame, then the login page or the view of the signed-in account."""
    settings = load_settings()
    today = read_today()
    engine = get_database_engine(database_url=settings.database_url)

    # Find out who is signed in
    google_identity = read_google_identity()
    user = find_signed_in_user(engine=engine, google_identity=google_identity)

    # End a sign-in older than 12 hours or idle for more than 30 minutes (R4.13)
    now = read_now()
    is_expired = user is not None and is_sign_in_expired(
        engine=engine,
        user=user,
        google_identity=google_identity,
        now=now,
    )
    if is_expired:
        logger.info(f'Sign-in of {user.kind} {user.account_id} expired.')
        # Only a local worker sees why: Google's sign-out reloads the page in a new session
        st.session_state[SESSION_EXPIRED_KEY] = True
        sign_out(google_identity=google_identity)

    # Frame shared by every page, with the sign-out button once signed in
    is_sign_out_clicked = render_frame(app_env=settings.app_env, today=today, user=user)
    if is_sign_out_clicked:
        sign_out(google_identity=google_identity)

    # Signed out: the login page and nothing else. A click that arrived after the sign-in
    # ended, even a late second click, never acts for the next sign-in (R4.13).
    if user is None:
        forget_action_requests()
        is_google_refused = google_identity is not None
        is_google_deactivated = is_google_identity_deactivated(
            engine=engine,
            google_identity=google_identity,
        )
        render_login_page(
            engine=engine,
            is_google_refused=is_google_refused,
            is_google_deactivated=is_google_deactivated,
        )
        return

    # Signed in: one view per account type
    storage_bucket = settings.storage_bucket
    storage_folder = settings.storage_folder
    storage = get_file_storage(storage_bucket=storage_bucket, storage_folder=storage_folder)
    if user.kind == 'admin':
        render_admin_console(engine=engine, storage=storage, today=today)
        return
    dimona_client = build_dimona_client(settings=settings)
    render_worker_view(
        engine=engine,
        dimona_client=dimona_client,
        storage=storage,
        worker_id=user.account_id,
        today=today,
    )


main()
