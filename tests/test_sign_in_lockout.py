"""The lock of a username after wrong passwords on the local form (R4.14)."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.models import SignInFailure
from dimonapp.sign_in_lockout import (
    clear_failed_sign_ins,
    digest_username,
    is_username_locked,
    record_failed_sign_in,
)

NOW = datetime.datetime(2026, 10, 14, 20, 0, tzinfo=datetime.UTC)


def fail_sign_ins(session: Session, username: str, n_failures: int, now: datetime.datetime) -> None:
    """Record a number of wrong passwords for a username, one second apart."""
    for second in range(n_failures):
        failed_at = now + datetime.timedelta(seconds=second)
        record_failed_sign_in(session=session, username=username, now=failed_at)


def test_r4_14_five_wrong_passwords_lock_the_username(session: Session) -> None:
    """Four wrong passwords leave the username open; the fifth locks it."""
    fail_sign_ins(session=session, username='lotte', n_failures=4, now=NOW)
    later = NOW + datetime.timedelta(minutes=1)

    assert not is_username_locked(session=session, username='lotte', now=later)

    record_failed_sign_in(session=session, username='lotte', now=later)

    assert is_username_locked(session=session, username='lotte', now=later)
    assert not is_username_locked(session=session, username='camille', now=later)


def test_r4_14_lock_ends_after_15_minutes(session: Session) -> None:
    """The username is locked 14 minutes after the fifth wrong password, open again after 15."""
    fail_sign_ins(session=session, username='lotte', n_failures=5, now=NOW)
    last_failed_at = NOW + datetime.timedelta(seconds=4)

    still_locked_at = last_failed_at + datetime.timedelta(minutes=14)
    open_at = last_failed_at + datetime.timedelta(minutes=15)

    assert is_username_locked(session=session, username='lotte', now=still_locked_at)
    assert not is_username_locked(session=session, username='lotte', now=open_at)


def test_r4_14_count_starts_again_after_15_quiet_minutes(session: Session) -> None:
    """Wrong passwords more than 15 minutes apart are not in a row."""
    fail_sign_ins(session=session, username='lotte', n_failures=4, now=NOW)
    much_later = NOW + datetime.timedelta(minutes=30)

    record_failed_sign_in(session=session, username='lotte', now=much_later)

    assert not is_username_locked(session=session, username='lotte', now=much_later)


def test_r4_14_clearing_the_count_unlocks_the_username(session: Session) -> None:
    """After a sign-in or a new password the username is open at once."""
    fail_sign_ins(session=session, username='lotte', n_failures=5, now=NOW)

    clear_failed_sign_ins(session=session, username='lotte')

    assert not is_username_locked(session=session, username='lotte', now=NOW)


def test_r4_14_only_a_digest_of_the_username_is_stored(session: Session) -> None:
    """A password typed in the username field never ends up in the database."""
    record_failed_sign_in(session=session, username='my-secret-password', now=NOW)

    stored = session.scalars(sa.select(SignInFailure.username_digest)).all()

    assert stored == [digest_username(username='my-secret-password')]
    assert 'my-secret-password' not in stored[0]


def test_r4_14_old_counts_are_removed(session: Session) -> None:
    """A wrong password removes the counts older than 15 minutes, so the table stays small."""
    record_failed_sign_in(session=session, username='nobody', now=NOW)
    much_later = NOW + datetime.timedelta(minutes=16)

    record_failed_sign_in(session=session, username='lotte', now=much_later)

    stored = session.scalars(sa.select(SignInFailure.username_digest)).all()
    assert stored == [digest_username(username='lotte')]
