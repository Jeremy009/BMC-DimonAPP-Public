"""Who may sign in, and as what (R4.2, R4.3, R4.6, R4.7, R4.8, R4.12, R4.14)."""

import datetime
from typing import Optional

from sqlalchemy.orm import Session

from dimonapp.authentication import (
    authenticate_local_worker,
    find_google_user,
    is_deactivated_google_account,
    load_local_worker,
    normalise_email,
)
from dimonapp.models import Admin, AuthMethod, Worker, WorkerType
from dimonapp.passwords import hash_password
from factories import build_worker

PASSWORD = 'climbing-is-fun'
PASSWORD_HASH = hash_password(password=PASSWORD)
EMAIL = 'lotte@example.com'
NOW = datetime.datetime(2026, 10, 14, 20, 0, tzinfo=datetime.UTC)


def add_local_worker(session: Session, is_active: bool = True) -> Worker:
    """Save a local worker with a known password."""
    worker = build_worker(username='lotte', password_hash=PASSWORD_HASH, is_active=is_active)
    session.add(worker)
    session.flush()
    return worker


def add_google_worker(
    session: Session,
    is_active: bool = True,
    password_hash: Optional[str] = None,
) -> Worker:
    """Save a worker who signs in with Google."""
    worker = build_worker(
        username='lotte',
        email=EMAIL,
        auth_method=AuthMethod.GOOGLE,
        worker_type=WorkerType.FLEXI_JOB,
        password_hash=password_hash,
        is_active=is_active,
        first_name='Lotte',
        last_name='Exemple',
    )
    session.add(worker)
    session.flush()
    return worker


def add_admin(session: Session, is_active: bool = True) -> Admin:
    """Save an admin."""
    admin = Admin(email=EMAIL, is_active=is_active)
    session.add(admin)
    session.flush()
    return admin


def test_r4_8_email_is_matched_without_case_or_spaces() -> None:
    """Google's own casing of an address does not matter."""
    assert normalise_email(email='  Lotte@Example.COM ') == 'lotte@example.com'


def test_r4_3_active_admin_signs_in_with_google(session: Session) -> None:
    """An admin e-mail is accepted and shown with the Google name and the type Admin."""
    admin = add_admin(session=session)

    user = find_google_user(session=session, email=EMAIL, google_name='Lotte Exemple')

    assert user is not None
    assert user.kind == 'admin'
    assert user.account_id == admin.id
    assert user.display_name == 'Lotte Exemple'
    assert user.type_label == 'Admin'


def test_r4_3_admin_without_google_name_is_shown_by_email(session: Session) -> None:
    """The admins table holds no name, so the e-mail stands in when Google gives none."""
    add_admin(session=session)

    user = find_google_user(session=session, email=EMAIL, google_name=None)

    assert user is not None
    assert user.display_name == EMAIL


def test_r4_8_inactive_admin_is_refused(session: Session) -> None:
    """A deactivated admin can no longer sign in."""
    add_admin(session=session, is_active=False)

    user = find_google_user(session=session, email=EMAIL, google_name=None)

    assert user is None


def test_r4_2_active_google_worker_signs_in_with_google(session: Session) -> None:
    """A Google worker is accepted and shown with the full name and the French type."""
    worker = add_google_worker(session=session)

    user = find_google_user(session=session, email='Lotte@Example.com', google_name='Ignored')

    assert user is not None
    assert user.kind == 'worker'
    assert user.account_id == worker.id
    assert user.display_name == 'Lotte Exemple'
    assert user.type_label == 'Flexijob'


def test_r4_7_inactive_google_worker_is_refused(session: Session) -> None:
    """An inactive worker cannot sign in with Google."""
    add_google_worker(session=session, is_active=False)

    user = find_google_user(session=session, email=EMAIL, google_name=None)

    assert user is None


def test_r4_8_local_worker_email_is_refused_by_google(session: Session) -> None:
    """Only workers whose login method is Google are matched by e-mail."""
    worker = build_worker(username='lotte', email=EMAIL, password_hash=PASSWORD_HASH)
    session.add(worker)
    session.flush()

    user = find_google_user(session=session, email=EMAIL, google_name=None)

    assert user is None


def test_r4_8_unknown_email_is_refused(session: Session) -> None:
    """Any other Google account is refused."""
    add_admin(session=session)

    user = find_google_user(session=session, email='stranger@example.com', google_name=None)

    assert user is None


def test_r4_6_email_in_both_tables_signs_in_as_admin(session: Session) -> None:
    """One session is one account type: the admin account wins for a shared address."""
    add_admin(session=session)
    add_google_worker(session=session)

    user = find_google_user(session=session, email=EMAIL, google_name=None)

    assert user is not None
    assert user.kind == 'admin'


def test_r4_2_local_worker_signs_in_with_username_and_password(session: Session) -> None:
    """The right username and password give the worker account."""
    worker = add_local_worker(session=session)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'accepted'
    assert sign_in.worker_id == worker.id


def test_r4_2_wrong_password_is_refused(session: Session) -> None:
    """A wrong password gives no account."""
    add_local_worker(session=session)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password='wrong', now=NOW
    )

    assert sign_in.outcome == 'refused'


def test_r4_2_unknown_username_is_refused(session: Session) -> None:
    """An unknown username gives no account."""
    add_local_worker(session=session)

    sign_in = authenticate_local_worker(
        session=session, username='nobody', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'refused'


def test_r4_7_inactive_local_worker_is_refused(session: Session) -> None:
    """An inactive worker cannot sign in, even with the right password."""
    add_local_worker(session=session, is_active=False)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome != 'accepted'
    assert sign_in.worker_id is None


def test_r4_2_google_worker_cannot_use_the_password_form(session: Session) -> None:
    """A worker whose login method is Google is refused by the form, whatever is stored."""
    add_google_worker(session=session, password_hash=PASSWORD_HASH)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'refused'


def test_r4_5_local_worker_without_password_is_refused(session: Session) -> None:
    """A local account whose password was never set accepts nothing, not even an empty one."""
    session.add(build_worker(username='lotte'))
    session.flush()

    sign_in = authenticate_local_worker(session=session, username='lotte', password='', now=NOW)

    assert sign_in.outcome == 'refused'


def test_r4_3_admin_cannot_use_the_password_form(session: Session) -> None:
    """Admins sign in with Google only: their e-mail is no username."""
    add_admin(session=session)

    sign_in = authenticate_local_worker(session=session, username=EMAIL, password=PASSWORD, now=NOW)

    assert sign_in.outcome == 'refused'


def test_r4_7_signed_in_worker_is_loaded_again(session: Session) -> None:
    """An active local worker stays signed in from one rerun to the next."""
    worker = add_local_worker(session=session)

    user = load_local_worker(session=session, worker_id=worker.id)

    assert user is not None
    assert user.account_id == worker.id


def test_r4_7_worker_deactivated_while_signed_in_loses_access(session: Session) -> None:
    """A deactivation takes effect on the next rerun of an open session."""
    worker = add_local_worker(session=session)
    worker.is_active = False
    session.flush()

    user = load_local_worker(session=session, worker_id=worker.id)

    assert user is None


def test_r4_12_deactivated_local_worker_with_the_right_password_is_recognised(
    session: Session,
) -> None:
    """The right password of a deactivated worker may be answered with the reason."""
    add_local_worker(session=session, is_active=False)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'deactivated'
    assert sign_in.worker_id is None


def test_r4_12_deactivated_local_worker_with_a_wrong_password_stays_hidden(
    session: Session,
) -> None:
    """A wrong password learns nothing about a deactivated account."""
    add_local_worker(session=session, is_active=False)

    sign_in = authenticate_local_worker(session=session, username='lotte', password='no', now=NOW)

    assert sign_in.outcome == 'refused'


def test_r4_12_deactivated_google_worker_is_recognised(session: Session) -> None:
    """A deactivated Google worker is recognised by the e-mail, whatever its casing."""
    add_google_worker(session=session, is_active=False)

    assert is_deactivated_google_account(session=session, email='Lotte@Example.com') is True


def test_r4_12_deactivated_admin_is_recognised(session: Session) -> None:
    """A deactivated admin is recognised by the e-mail."""
    add_admin(session=session, is_active=False)

    assert is_deactivated_google_account(session=session, email=EMAIL) is True


def test_r4_12_other_google_accounts_are_not_deactivated(session: Session) -> None:
    """An active account, a stranger and a deactivated local worker are not reported."""
    add_admin(session=session)
    local_worker = build_worker(username='noor', email='noor@example.com', is_active=False)
    session.add(local_worker)
    session.flush()

    assert is_deactivated_google_account(session=session, email=EMAIL) is False
    assert is_deactivated_google_account(session=session, email='stranger@example.com') is False
    assert is_deactivated_google_account(session=session, email='noor@example.com') is False


def fail_sign_ins(session: Session, username: str, n_failures: int) -> None:
    """Try a username with a wrong password a number of times."""
    for _ in range(n_failures):
        authenticate_local_worker(session=session, username=username, password='wrong', now=NOW)


def test_r4_14_five_wrong_passwords_lock_out_even_the_right_one(session: Session) -> None:
    """After five wrong passwords the right one is refused too, without being checked."""
    add_local_worker(session=session)
    fail_sign_ins(session=session, username='lotte', n_failures=5)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'locked'
    assert sign_in.worker_id is None


def test_r4_14_unknown_username_is_locked_the_same_way(session: Session) -> None:
    """A username without an account locks like a real one, so the lock reveals nothing."""
    fail_sign_ins(session=session, username='nobody', n_failures=5)

    sign_in = authenticate_local_worker(session=session, username='nobody', password='x', now=NOW)

    assert sign_in.outcome == 'locked'


def test_r4_14_right_password_clears_the_count(session: Session) -> None:
    """Four wrong passwords, a right one, then four more do not lock the username."""
    add_local_worker(session=session)
    fail_sign_ins(session=session, username='lotte', n_failures=4)
    authenticate_local_worker(session=session, username='lotte', password=PASSWORD, now=NOW)
    fail_sign_ins(session=session, username='lotte', n_failures=4)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=NOW
    )

    assert sign_in.outcome == 'accepted'


def test_r4_14_lock_ends_after_15_minutes(session: Session) -> None:
    """Fifteen minutes after the fifth wrong password the right one works again."""
    add_local_worker(session=session)
    fail_sign_ins(session=session, username='lotte', n_failures=5)
    later = NOW + datetime.timedelta(minutes=15)

    sign_in = authenticate_local_worker(
        session=session, username='lotte', password=PASSWORD, now=later
    )

    assert sign_in.outcome == 'accepted'
