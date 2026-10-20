"""The lock of a username after wrong passwords on the local form (R4.14).

Plain functions on a database session, so the rule is tested without Streamlit. The count is
kept per typed username, known or not, so a lock reveals nothing about which accounts exist.
Only a digest of the username is stored: people sometimes type their password in that field.
"""

import datetime
import hashlib

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from dimonapp.models import SignInFailure

MAX_FAILED_SIGN_INS = 5
LOCKOUT_DURATION = datetime.timedelta(minutes=15)


def digest_username(username: str) -> str:
    """Give the SHA-256 digest of a typed username, the only form in which it is stored."""
    username_bytes = username.encode('utf-8')
    return hashlib.sha256(username_bytes).hexdigest()


def is_username_locked(session: Session, username: str, now: datetime.datetime) -> bool:
    """Tell whether a username is locked: five wrong passwords, the last under 15 minutes ago."""
    username_digest = digest_username(username=username)
    failure = session.get(SignInFailure, username_digest)
    if failure is None:
        return False
    is_recent = now - failure.last_failed_at < LOCKOUT_DURATION
    return failure.n_failures >= MAX_FAILED_SIGN_INS and is_recent


def record_failed_sign_in(session: Session, username: str, now: datetime.datetime) -> None:
    """Count one more wrong password for a username, starting again after 15 quiet minutes.

    One statement adds or raises the count, so two attempts at the same moment both count.
    Counts older than 15 minutes are removed first, so the table stays small.
    """
    window_start = now - LOCKOUT_DURATION
    stale_failures = sa.delete(SignInFailure).where(SignInFailure.last_failed_at < window_start)
    session.execute(stale_failures)

    username_digest = digest_username(username=username)
    is_stale = SignInFailure.last_failed_at < window_start
    n_failures = sa.case((is_stale, 1), else_=SignInFailure.n_failures + 1)
    statement = postgresql.insert(SignInFailure).values(
        username_digest=username_digest,
        n_failures=1,
        last_failed_at=now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[SignInFailure.username_digest],
        set_={'n_failures': n_failures, 'last_failed_at': now},
    )
    session.execute(statement)


def clear_failed_sign_ins(session: Session, username: str) -> None:
    """Forget the wrong passwords of a username: after a sign-in or a new password (R4.14)."""
    username_digest = digest_username(username=username)
    statement = sa.delete(SignInFailure).where(SignInFailure.username_digest == username_digest)
    session.execute(statement)
