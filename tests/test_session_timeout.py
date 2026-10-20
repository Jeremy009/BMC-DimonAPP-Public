"""How long a sign-in lasts (R4.13)."""

import datetime

from dimonapp.session_timeout import is_session_expired

NOW = datetime.datetime(2026, 10, 14, 20, 0, tzinfo=datetime.UTC)


def test_r4_13_recent_active_sign_in_is_not_expired() -> None:
    """A sign-in of this morning, used a minute ago, goes on."""
    signed_in_at = NOW - datetime.timedelta(hours=8)
    last_action_at = NOW - datetime.timedelta(minutes=1)

    assert not is_session_expired(signed_in_at=signed_in_at, last_action_at=last_action_at, now=NOW)


def test_r4_13_sign_in_ends_after_12_hours_even_when_active() -> None:
    """Exactly 12 hours is still allowed; a minute more ends the sign-in, however busy."""
    last_action_at = NOW - datetime.timedelta(minutes=1)
    signed_in_at = NOW - datetime.timedelta(hours=12)
    too_old_signed_in_at = signed_in_at - datetime.timedelta(minutes=1)

    assert not is_session_expired(signed_in_at=signed_in_at, last_action_at=last_action_at, now=NOW)
    assert is_session_expired(
        signed_in_at=too_old_signed_in_at,
        last_action_at=last_action_at,
        now=NOW,
    )


def test_r4_13_sign_in_ends_after_30_idle_minutes() -> None:
    """Exactly 30 idle minutes is still allowed; a minute more ends the sign-in."""
    signed_in_at = NOW - datetime.timedelta(hours=1)
    last_action_at = NOW - datetime.timedelta(minutes=30)
    too_idle_last_action_at = last_action_at - datetime.timedelta(minutes=1)

    assert not is_session_expired(signed_in_at=signed_in_at, last_action_at=last_action_at, now=NOW)
    assert is_session_expired(
        signed_in_at=signed_in_at,
        last_action_at=too_idle_last_action_at,
        now=NOW,
    )


def test_r4_13_idle_time_without_any_action_runs_from_the_sign_in() -> None:
    """An account that never acted is idle since its sign-in."""
    signed_in_at = NOW - datetime.timedelta(minutes=31)

    assert is_session_expired(signed_in_at=signed_in_at, last_action_at=None, now=NOW)
    assert not is_session_expired(signed_in_at=NOW, last_action_at=None, now=NOW)


def test_r4_13_fresh_sign_in_counts_as_an_action() -> None:
    """Signing in again after a long pause is not idle, whatever the old last action says."""
    signed_in_at = NOW - datetime.timedelta(minutes=1)
    last_action_at = NOW - datetime.timedelta(hours=3)

    assert not is_session_expired(signed_in_at=signed_in_at, last_action_at=last_action_at, now=NOW)
