"""Helpers to run the Streamlit application headless in the tests.

Google is never called: the functions of dimonapp.google_identity are replaced.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest
import sqlalchemy as sa
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Block, Button, Widget

import dimonapp
from dimonapp import google_identity
from dimonapp.clock import read_now, read_today
from dimonapp.database import open_session
from dimonapp.google_identity import GoogleIdentity
from dimonapp.models import ACTIVITY_TYPE_CODES, RATE_CODES, Admin, DocumentType, Worker, WorkerType
from dimonapp.passwords import hash_password
from factories import (
    VALID_NATIONAL_REGISTER_NUMBER,
    build_authorisation,
    build_limit,
    build_rate,
    build_worker,
)

APP_PATH = Path(dimonapp.__file__).parent / 'app.py'
DATABASE_URL = 'postgresql+psycopg://user:password@localhost:5432/database'
PASSWORD = 'climbing-is-fun'
ADMIN_EMAIL = 'ada@example.com'
RATE = Decimal('20')
START_DATE = date(2020, 1, 1)


def run_app(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
    database_url: str = DATABASE_URL,
    identity: Optional[GoogleIdentity] = None,
) -> AppTest:
    """Run the application headless, optionally with a Google identity in the session."""
    monkeypatch.setenv('APP_ENV', app_env)
    monkeypatch.setenv('DATABASE_URL', database_url)
    monkeypatch.setattr(google_identity, 'read_google_identity', lambda: identity)
    app = AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    assert not app.exception
    return app


def render_database_url(engine: sa.Engine) -> str:
    """Give the URL of the throwaway database, password included, for the application."""
    return engine.url.render_as_string(hide_password=False)


def add_account(engine: sa.Engine, account: Worker | Admin) -> None:
    """Commit an account, so the running application sees it."""
    with open_session(engine=engine) as session:
        session.add(account)


def build_local_worker(
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    username: str = 'lotte',
    national_register_number: str = VALID_NATIONAL_REGISTER_NUMBER,
) -> Worker:
    """Build an active local worker with a known password, an e-mail and a postal address.

    The first name follows the username: lotte is Lotte Exemple.
    """
    password_hash = hash_password(password=PASSWORD)
    return build_worker(
        worker_type=worker_type,
        national_register_number=national_register_number,
        username=username,
        email=f'{username}.exemple@example.com',
        password_hash=password_hash,
        first_name=username.capitalize(),
        last_name='Exemple',
        street='Rue Imaginaire 12',
        postal_code='1050',
        city='Ixelles',
    )


def add_ready_worker(engine: sa.Engine, worker_type: WorkerType = WorkerType.ARTICLE_17) -> int:
    """Commit a local worker who may declare anything, and give the worker's id.

    The worker gets every rate, and a contract and a qualification for all activity types; the
    minimum of 3 hours per flexi-job activity is configured for this year.
    """
    with open_session(engine=engine) as session:
        worker = build_local_worker(worker_type=worker_type)
        session.add(worker)
        session.flush()
        worker_id = worker.id
        for rate_code in RATE_CODES:
            rate = build_rate(
                valid_from=START_DATE,
                amount=RATE,
                worker_id=worker_id,
                activity_type=rate_code,
            )
            session.add(rate)
        for document_type in DocumentType:
            authorisation = build_authorisation(
                document_type=document_type,
                activity_types=ACTIVITY_TYPE_CODES,
                start_date=START_DATE,
                worker_id=worker_id,
                worker_type=worker_type,
            )
            session.add(authorisation)
        flexi_minimum = build_limit(
            year=read_today().year,
            worker_type=WorkerType.FLEXI_JOB,
            min_hours_per_activity=Decimal('3'),
        )
        session.add(flexi_minimum)
    return worker_id


def sign_in_locally(app: AppTest, username: str, password: str) -> AppTest:
    """Fill in the username and password form and submit it."""
    app.text_input[0].set_value(username)
    app.text_input[1].set_value(password)
    app.button[0].click()
    app.run()
    assert not app.exception
    return app


def run_app_as_local_worker(monkeypatch: pytest.MonkeyPatch, engine: sa.Engine) -> AppTest:
    """Run the application and sign in as a committed local worker."""
    add_account(engine=engine, account=build_local_worker())
    database_url = render_database_url(engine=engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    return sign_in_locally(app=app, username='lotte', password=PASSWORD)


def sign_in_as_ready_worker(
    monkeypatch: pytest.MonkeyPatch,
    engine: sa.Engine,
    fake_dimona_outcome: str = 'accept',
) -> AppTest:
    """Run the application and sign in as the worker committed by add_ready_worker."""
    monkeypatch.setenv('FAKE_DIMONA_OUTCOME', fake_dimona_outcome)
    database_url = render_database_url(engine=engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    return sign_in_locally(app=app, username='lotte', password=PASSWORD)


def run_app_as_ready_worker(
    monkeypatch: pytest.MonkeyPatch,
    engine: sa.Engine,
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    fake_dimona_outcome: str = 'accept',
) -> AppTest:
    """Commit a worker who may declare anything and run the application signed in as them."""
    add_ready_worker(engine=engine, worker_type=worker_type)
    return sign_in_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=engine,
        fake_dimona_outcome=fake_dimona_outcome,
    )


def find_button(app: AppTest, label: str, index: int = 0) -> Button:
    """Give the button with a label; index picks one when several tabs share the label."""
    buttons = [button for button in app.button if button.label == label]
    return buttons[index]


def click_button(app: AppTest, label: str, index: int = 0) -> AppTest:
    """Click a button by its label and run the application again."""
    find_button(app=app, label=label, index=index).click()
    app.run()
    assert not app.exception
    return app


def run_app_as_admin(monkeypatch: pytest.MonkeyPatch, engine: sa.Engine) -> AppTest:
    """Commit an admin and run the application signed in as that admin, through Google."""
    add_account(engine=engine, account=Admin(email=ADMIN_EMAIL))
    database_url = render_database_url(engine=engine)
    signed_in_at = read_now()
    identity = GoogleIdentity(email=ADMIN_EMAIL, name='Ada Admin', signed_in_at=signed_in_at)
    return run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=identity,
    )


def read_tab_order(block: Block, prefix: str = '') -> list[str]:
    """Give the labels of the fields under a block in page order, the order the tab key follows.

    Only fields whose key starts with the prefix count; an empty prefix keeps every field.
    """
    fields = [node for node in block if isinstance(node, Widget) and not isinstance(node, Button)]
    return [field.label for field in fields if (field.key or '').startswith(prefix)]


def click_key(app: AppTest, key: str) -> AppTest:
    """Click a button by its key and run the application again."""
    app.button(key=key).click()
    app.run()
    assert not app.exception
    return app


def record_downloads(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Record what every download button offers: the file content and its name."""
    downloads: list[dict[str, object]] = []
    render_download_button = st.download_button

    def record_download(**arguments: object) -> bool:
        """Remember the arguments, then render the real button."""
        downloads.append(arguments)
        return render_download_button(**arguments)

    monkeypatch.setattr(st, 'download_button', record_download)
    return downloads
