"""Who may sign in, and as what (R4.2, R4.3, R4.6, R4.7, R4.8, R4.12, R4.14).

Plain functions on a database session, so the rules are tested without Streamlit. A signed-in
user is always exactly one account: an admin or a worker, never both (R4.6).
"""

import datetime
import logging
from typing import Literal, Optional

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.models import Admin, AuthMethod, Worker
from dimonapp.passwords import hash_password, verify_password
from dimonapp.sign_in_lockout import (
    clear_failed_sign_ins,
    is_username_locked,
    record_failed_sign_in,
)
from dimonapp.worker_types import ADMIN_LABEL, WORKER_TYPE_LABELS, build_worker_name

logger = logging.getLogger(__name__)

# Verified when the username is unknown, so that answer takes as long as a wrong password.
UNKNOWN_USER_HASH = hash_password(password='unknown-user')


class SignedInUser(BaseModel):
    """The account behind the current browser session."""

    kind: Literal['admin', 'worker']
    account_id: int
    display_name: str
    type_label: str


class LocalSignIn(BaseModel):
    """How a sign-in with a username and password ended; the worker only when accepted."""

    outcome: Literal['accepted', 'deactivated', 'locked', 'refused']
    worker_id: Optional[int] = None


def normalise_email(email: str) -> str:
    """Give an e-mail address in the form used for matching: trimmed and lower case."""
    return email.strip().lower()


def build_worker_user(worker: Worker) -> SignedInUser:
    """Describe a worker as the signed-in user: full name and French worker type."""
    display_name = build_worker_name(worker=worker)
    type_label = WORKER_TYPE_LABELS[worker.worker_type]
    return SignedInUser(
        kind='worker',
        account_id=worker.id,
        display_name=display_name,
        type_label=type_label,
    )


def find_google_user(
    session: Session,
    email: str,
    google_name: Optional[str],
) -> Optional[SignedInUser]:
    """Match a Google e-mail to an active admin, then to an active Google worker (R4.8).

    Any other e-mail gives None and is refused. The admins table holds no name, so an admin
    is shown with the name Google gives, or the e-mail when there is none. Called on every
    rerun, so a deactivation takes effect at once (R4.7); that is also why nothing is logged.
    """
    matched_email = normalise_email(email=email)

    # Admins first: an address in both tables signs in as admin (R4.6)
    admin_query = sa.select(Admin).where(
        sa.func.lower(Admin.email) == matched_email,
        Admin.is_active.is_(True),
    )
    admin = session.scalars(admin_query).first()
    if admin is not None:
        display_name = google_name or admin.email
        return SignedInUser(
            kind='admin',
            account_id=admin.id,
            display_name=display_name,
            type_label=ADMIN_LABEL,
        )

    # Then the active workers whose login method is Google
    worker_query = sa.select(Worker).where(
        sa.func.lower(Worker.email) == matched_email,
        Worker.auth_method == AuthMethod.GOOGLE,
        Worker.is_active.is_(True),
    )
    worker = session.scalars(worker_query).first()
    if worker is None:
        return None
    return build_worker_user(worker=worker)


def authenticate_local_worker(
    session: Session,
    username: str,
    password: str,
    now: datetime.datetime,
) -> LocalSignIn:
    """Check a username and password against the local workers (R4.2, R4.7, R4.12, R4.14).

    Every refusal looks the same, so the form reveals nothing about accounts. Only a deactivated
    worker with the right password is told apart: the password proves who is asking. Five wrong
    passwords lock the typed username for 15 minutes, whether an account has it or not.
    """
    # A locked username is refused before its password is even checked
    if is_username_locked(session=session, username=username, now=now):
        logger.warning('Local sign-in refused: username locked after wrong passwords.')
        return LocalSignIn(outcome='locked')

    worker_query = sa.select(Worker).where(
        Worker.username == username,
        Worker.auth_method == AuthMethod.LOCAL,
    )
    worker = session.scalars(worker_query).first()

    # An unknown username still costs one password check, so it takes as long as a wrong password
    password_hash = worker.password_hash if worker is not None else UNKNOWN_USER_HASH
    is_password_right = verify_password(password=password, password_hash=password_hash)
    if worker is None or not is_password_right:
        record_failed_sign_in(session=session, username=username, now=now)
        logger.warning('Local sign-in refused.')
        return LocalSignIn(outcome='refused')
    clear_failed_sign_ins(session=session, username=username)
    if not worker.is_active:
        logger.warning(f'Local sign-in refused: worker {worker.id} is deactivated.')
        return LocalSignIn(outcome='deactivated')

    logger.info(f'Local sign-in accepted for worker {worker.id}.')
    return LocalSignIn(outcome='accepted', worker_id=worker.id)


def is_deactivated_google_account(session: Session, email: str) -> bool:
    """Tell whether a refused Google e-mail belongs to a deactivated admin or Google worker.

    Google has proven who is asking, so the refusal may say why (R4.12).
    """
    matched_email = normalise_email(email=email)
    admin_query = sa.select(Admin.id).where(
        sa.func.lower(Admin.email) == matched_email,
        Admin.is_active.is_(False),
    )
    worker_query = sa.select(Worker.id).where(
        sa.func.lower(Worker.email) == matched_email,
        Worker.auth_method == AuthMethod.GOOGLE,
        Worker.is_active.is_(False),
    )
    admin_id = session.scalars(admin_query).first()
    worker_id = session.scalars(worker_query).first()
    return admin_id is not None or worker_id is not None


def load_local_worker(session: Session, worker_id: int) -> Optional[SignedInUser]:
    """Read the signed-in local worker again; None once inactive, removed or no longer local.

    Called on every rerun, so a deactivation takes effect at once (R4.7).
    """
    worker = session.get(Worker, worker_id)
    if worker is None or not worker.is_active or worker.auth_method != AuthMethod.LOCAL:
        return None
    return build_worker_user(worker=worker)
