"""The first admin of an environment, added at start-up (R4.11)."""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app_runner import render_database_url
from dimonapp import startup
from dimonapp.authentication import find_google_user
from dimonapp.database import open_session
from dimonapp.first_admin import add_first_admin
from dimonapp.models import Admin
from dimonapp.settings import load_settings


def read_admin_emails(session: Session) -> list[str]:
    """Give the addresses of every admin."""
    return list(session.scalars(sa.select(Admin.email).order_by(Admin.id)))


def test_r4_11_first_admin_is_added_to_an_empty_table_and_can_sign_in(session: Session) -> None:
    """The address is stored in the form a Google sign-in is matched with."""
    is_added = add_first_admin(session=session, email=' Ada@Example.com ')

    user = find_google_user(session=session, email='ada@example.com', google_name='Ada Admin')
    assert is_added
    assert read_admin_emails(session=session) == ['ada@example.com']
    assert user is not None
    assert user.kind == 'admin'


def test_r4_11_setting_changes_nothing_once_an_admin_exists(session: Session) -> None:
    """No second admin is added, and a deactivated admin is not replaced."""
    session.add(Admin(email='ada@example.com', is_active=False))
    session.flush()

    is_added = add_first_admin(session=session, email='other@example.com')

    assert not is_added
    assert read_admin_emails(session=session) == ['ada@example.com']


def test_r4_11_first_admin_logs_no_address(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log names the admin by id only."""
    caplog.set_level('INFO')

    add_first_admin(session=session, email='ada@example.com')

    assert 'First admin added' in caplog.text
    assert 'ada@example.com' not in caplog.text


def test_r4_11_start_up_adds_the_admin_of_the_settings(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """FIRST_ADMIN_EMAIL is read at start-up; without it nothing is added."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', render_database_url(engine=account_engine))

    startup.ensure_first_admin(settings=load_settings())
    with open_session(engine=account_engine) as session:
        emails_without_setting = read_admin_emails(session=session)
    monkeypatch.setenv('FIRST_ADMIN_EMAIL', 'ada@example.com')
    startup.ensure_first_admin(settings=load_settings())

    with open_session(engine=account_engine) as session:
        emails = read_admin_emails(session=session)
    assert emails_without_setting == []
    assert emails == ['ada@example.com']
