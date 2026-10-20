"""Worker management by the admin (R11.1 to R11.6, R4.4, FDS 7.4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp import worker_admin
from dimonapp.authentication import authenticate_local_worker
from dimonapp.fake_data import build_fake_national_register_number
from dimonapp.models import (
    RATE_CODES,
    AuthMethod,
    CompensationRate,
    Worker,
    WorkerType,
)
from dimonapp.passwords import verify_password
from dimonapp.worker_admin import (
    WorkerForm,
    build_worker_form,
    build_worker_row,
    create_worker,
    find_workers,
    set_worker_password,
    update_worker,
)
from factories import VALID_NATIONAL_REGISTER_NUMBER, build_activity, build_worker

TODAY = date(2026, 10, 10)
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
PASSWORD = 'climbing-is-fun'
OTHER_NATIONAL_NUMBER = build_fake_national_register_number(
    birth_date=date(1991, 2, 3),
    sequence=123,
)


def build_form(
    national_register_number: str = '85.07.30-033.28',
    username: str = 'e.janssens',
    email: str = 'emma.janssens@example.com',
    auth_method: AuthMethod = AuthMethod.LOCAL,
    first_name: str = 'Emma',
    iban: str = 'be07 3456 7890 1234',
    worker_type: WorkerType = WorkerType.ARTICLE_17,
) -> WorkerForm:
    """Build what an admin types for a new worker."""
    return WorkerForm(
        first_name=first_name,
        last_name='Janssens',
        national_register_number=national_register_number,
        iban=iban,
        worker_type=worker_type,
        username=username,
        email=email,
        auth_method=auth_method,
        street='Rue Imaginaire 12',
        postal_code='1050',
        city='Ixelles',
    )


def build_rates(missing: Optional[str] = None) -> dict[str, Optional[Decimal]]:
    """Build each of the eleven rates, optionally leaving one out."""
    rates: dict[str, Optional[Decimal]] = {code: Decimal('20') for code in RATE_CODES}
    if missing is not None:
        rates[missing] = None
    return rates


def create(session: Session, form: WorkerForm, password: str = PASSWORD) -> str:
    """Create a worker with every rate and give the level of the result."""
    result = create_worker(
        session=session,
        form=form,
        password=password,
        rates=build_rates(),
        today=TODAY,
    )
    return result.level


def read_worker(session: Session, username: str) -> Worker:
    """Read a worker by username."""
    return session.scalars(sa.select(Worker).where(Worker.username == username)).one()


def test_r11_1_admin_creates_a_worker_with_every_field(session: Session) -> None:
    """The record holds the fields of R11.2, the numbers stored without separators."""
    form = build_form(email=' Emma@Example.com ')

    result = create_worker(
        session=session,
        form=form,
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    worker = read_worker(session=session, username='e.janssens')
    assert result.level == 'success'
    assert result.message == 'Travailleur créé : Emma Janssens.'
    assert worker.first_name == 'Emma'
    assert worker.last_name == 'Janssens'
    assert worker.national_register_number == VALID_NATIONAL_REGISTER_NUMBER
    assert worker.iban == 'BE07345678901234'
    assert worker.worker_type == WorkerType.ARTICLE_17
    assert worker.email == 'emma@example.com'
    assert worker.auth_method == AuthMethod.LOCAL
    assert worker.is_active is True


def test_r11_4_local_password_is_stored_as_a_hash_and_signs_in(session: Session) -> None:
    """The admin's password works at once, without a forced change, and is never stored."""
    create(session=session, form=build_form())

    worker = read_worker(session=session, username='e.janssens')
    sign_in = authenticate_local_worker(
        session=session, username='e.janssens', password=PASSWORD, now=NOW
    )

    assert PASSWORD not in worker.password_hash
    assert worker.password_hash.startswith('$argon2')
    assert sign_in.outcome == 'accepted'


def test_r11_4_local_worker_needs_a_password(session: Session) -> None:
    """A local account without a password is refused and nothing is stored."""
    result = create_worker(
        session=session,
        form=build_form(),
        password='',
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == worker_admin.MISSING_PASSWORD_MESSAGE
    assert find_workers(session=session) == []


def test_r11_9_password_of_a_new_worker_has_at_least_10_characters(session: Session) -> None:
    """Nine characters are refused and nothing is stored; ten are accepted."""
    refused = create_worker(
        session=session,
        form=build_form(),
        password='123456789',
        rates=build_rates(),
        today=TODAY,
    )
    n_workers_after_refusal = len(find_workers(session=session))

    level = create(session=session, form=build_form(), password='1234567890')

    assert refused.level == 'error'
    assert refused.message == worker_admin.SHORT_PASSWORD_MESSAGE
    assert n_workers_after_refusal == 0
    assert level == 'success'


def test_r11_8_iban_is_checked_when_a_worker_is_edited(session: Session) -> None:
    """A typing error in the IBAN is refused and the stored IBAN stays."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')
    form = build_worker_form(worker=worker)
    form.iban = 'BE07 3456 7890 1243'

    result = update_worker(session=session, worker_id=worker.id, form=form, is_active=True)

    assert result.level == 'error'
    assert result.message == worker_admin.INVALID_IBAN_MESSAGE
    assert worker.iban == 'BE07345678901234'


def test_r4_2_google_worker_needs_an_email_and_no_password(session: Session) -> None:
    """A Google account is refused without an e-mail, and stores no password hash."""
    without_email = build_form(auth_method=AuthMethod.GOOGLE, email=' ')
    with_email = build_form(auth_method=AuthMethod.GOOGLE, email='emma@example.com')

    refused = create_worker(
        session=session,
        form=without_email,
        password='',
        rates=build_rates(),
        today=TODAY,
    )
    level = create(session=session, form=with_email, password='')

    assert refused.message == worker_admin.MISSING_EMAIL_MESSAGE
    assert level == 'success'
    assert read_worker(session=session, username='e.janssens').password_hash is None


@pytest.mark.parametrize('number', ['85073003329', '123', '', 'abc'])
def test_r11_3_national_register_number_is_checked_on_entry(session: Session, number: str) -> None:
    """A number with a wrong checksum never reaches the database."""
    result = create_worker(
        session=session,
        form=build_form(national_register_number=number),
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == worker_admin.INVALID_NATIONAL_NUMBER_MESSAGE
    assert find_workers(session=session) == []


@pytest.mark.parametrize(
    ('form', 'message'),
    [
        (build_form(first_name='  '), worker_admin.MISSING_NAME_MESSAGE),
        (build_form(iban=' '), worker_admin.MISSING_IBAN_MESSAGE),
        (build_form(iban='BE08 3456 7890 1234'), worker_admin.INVALID_IBAN_MESSAGE),
        (build_form(username=''), worker_admin.MISSING_USERNAME_MESSAGE),
        (build_form(email=' '), worker_admin.MISSING_EMAIL_MESSAGE),
    ],
)
def test_r11_2_missing_field_is_named(session: Session, form: WorkerForm, message: str) -> None:
    """Each mandatory field has its own French message."""
    result = create_worker(
        session=session,
        form=form,
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == message


@pytest.mark.parametrize(
    ('form', 'message'),
    [
        (build_form(username='other'), worker_admin.NATIONAL_NUMBER_TAKEN_MESSAGE),
        (
            build_form(national_register_number=OTHER_NATIONAL_NUMBER),
            worker_admin.USERNAME_TAKEN_MESSAGE,
        ),
        (
            build_form(
                national_register_number=OTHER_NATIONAL_NUMBER,
                username='other',
                email='EMMA@example.com',
            ),
            worker_admin.EMAIL_TAKEN_MESSAGE,
        ),
    ],
)
def test_r11_2_unique_values_cannot_be_reused(
    session: Session,
    form: WorkerForm,
    message: str,
) -> None:
    """National register number, username and e-mail belong to one worker only."""
    create(session=session, form=build_form(email='emma@example.com'))

    result = create_worker(
        session=session,
        form=form,
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == message


def test_fds_7_4_creating_a_worker_stores_all_eleven_rates(session: Session) -> None:
    """Each activity type gets the entered rate, valid from the day of creation."""
    create(session=session, form=build_form())

    worker = read_worker(session=session, username='e.janssens')
    rates = list(
        session.scalars(sa.select(CompensationRate).where(CompensationRate.worker_id == worker.id))
    )

    assert sorted(rate.activity_type for rate in rates) == sorted(RATE_CODES)
    assert {rate.amount for rate in rates} == {Decimal('20.00')}
    assert {rate.valid_from for rate in rates} == {TODAY}


def test_fds_7_4_a_missing_rate_refuses_the_worker(session: Session) -> None:
    """Without all eleven rates no worker is created, so the gate always finds a rate."""
    result = create_worker(
        session=session,
        form=build_form(),
        password=PASSWORD,
        rates=build_rates(missing='group_travel'),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == worker_admin.MISSING_RATES_MESSAGE
    assert find_workers(session=session) == []


def test_r11_1_admin_edits_a_worker(session: Session) -> None:
    """Every field can be corrected; the worker's own values do not count as taken."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')
    form = build_worker_form(worker=worker)
    form.last_name = 'Peeters'
    form.iban = 'BE27 0000 0000 0001'

    result = update_worker(session=session, worker_id=worker.id, form=form, is_active=True)

    assert result.message == 'Travailleur modifié : Emma Peeters.'
    assert worker.last_name == 'Peeters'
    assert worker.iban == 'BE27000000000001'


@pytest.mark.parametrize(
    ('old_type', 'new_type'),
    [
        (WorkerType.VRIJWILLIGER, WorkerType.FLEXI_JOB),
        (WorkerType.FLEXI_JOB, WorkerType.VRIJWILLIGER),
        (WorkerType.ARTICLE_17, WorkerType.FREELANCER),
    ],
)
def test_r5_3_worker_type_change_is_not_checked(
    session: Session,
    old_type: WorkerType,
    new_type: WorkerType,
) -> None:
    """The ladder is the admin's rule: the application accepts any change, a downgrade too."""
    create(session=session, form=build_form(worker_type=old_type))
    worker = read_worker(session=session, username='e.janssens')
    form = build_worker_form(worker=worker)
    form.worker_type = new_type

    result = update_worker(session=session, worker_id=worker.id, form=form, is_active=True)

    assert result.level == 'success'
    assert worker.worker_type == new_type


def test_r11_5_deactivated_worker_keeps_history_and_cannot_sign_in(session: Session) -> None:
    """Deactivation blocks the sign-in; the worker and the activities stay."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')
    session.add(build_activity(worker_id=worker.id))
    session.flush()
    form = build_worker_form(worker=worker)

    update_worker(session=session, worker_id=worker.id, form=form, is_active=False)

    sign_in = authenticate_local_worker(
        session=session, username='e.janssens', password=PASSWORD, now=NOW
    )
    n_activities = session.scalar(sa.select(sa.func.count()).select_from(sa.text('activities')))
    assert sign_in.outcome == 'deactivated'
    assert worker.is_active is False
    assert n_activities == 1
    assert not hasattr(worker_admin, 'delete_worker')


def test_r11_5_worker_can_be_reactivated(session: Session) -> None:
    """An inactive worker signs in again once reactivated."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')
    form = build_worker_form(worker=worker)
    update_worker(session=session, worker_id=worker.id, form=form, is_active=False)

    update_worker(session=session, worker_id=worker.id, form=form, is_active=True)

    sign_in = authenticate_local_worker(
        session=session, username='e.janssens', password=PASSWORD, now=NOW
    )
    assert sign_in.outcome == 'accepted'


def test_r11_6_admin_resets_a_password(session: Session) -> None:
    """The new password replaces the old one and is stored as a hash only."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')

    result = set_worker_password(
        session=session,
        worker_id=worker.id,
        password='new-password',
        confirmation='new-password',
    )

    assert result.level == 'success'
    assert result.message == 'Mot de passe enregistré pour Emma Janssens.'
    assert 'new-password' not in result.message
    assert verify_password(password='new-password', password_hash=worker.password_hash)
    assert not verify_password(password=PASSWORD, password_hash=worker.password_hash)


@pytest.mark.parametrize(
    ('password', 'confirmation', 'message'),
    [
        ('', '', worker_admin.EMPTY_PASSWORD_MESSAGE),
        ('123456789', '123456789', worker_admin.SHORT_NEW_PASSWORD_MESSAGE),
        ('one-password', 'another-password', worker_admin.PASSWORD_MISMATCH_MESSAGE),
    ],
)
def test_r11_6_r11_9_password_must_be_long_enough_and_entered_twice_the_same(
    session: Session,
    password: str,
    confirmation: str,
    message: str,
) -> None:
    """An empty or short password, or a different confirmation, leaves the old one in place."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')

    result = set_worker_password(
        session=session,
        worker_id=worker.id,
        password=password,
        confirmation=confirmation,
    )

    assert result.level == 'error'
    assert result.message == message
    assert verify_password(password=PASSWORD, password_hash=worker.password_hash)


def test_r4_14_new_password_unlocks_the_username(session: Session) -> None:
    """An admin unlocks a worker at once by setting a new password."""
    create(session=session, form=build_form())
    worker = read_worker(session=session, username='e.janssens')
    for _ in range(5):
        authenticate_local_worker(session=session, username='e.janssens', password='wrong', now=NOW)

    set_worker_password(
        session=session,
        worker_id=worker.id,
        password='new-password',
        confirmation='new-password',
    )

    sign_in = authenticate_local_worker(
        session=session,
        username='e.janssens',
        password='new-password',
        now=NOW,
    )
    assert sign_in.outcome == 'accepted'


def test_r3_8_database_refusal_of_a_new_worker_shows_no_personal_data(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    session: Session,
) -> None:
    """A number another admin saved at the same moment gives a French message, nothing more.

    The check of the form is skipped, as when two admins save at once; the session goes on.
    """
    create(session=session, form=build_form())
    monkeypatch.setattr(worker_admin, 'find_worker_form_error', lambda **_: None)
    duplicate = build_form(username='other', email='other@example.com')

    result = create_worker(
        session=session,
        form=duplicate,
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == worker_admin.DATABASE_REFUSED_MESSAGE
    assert VALID_NATIONAL_REGISTER_NUMBER not in caplog.text
    assert len(find_workers(session=session)) == 1


def test_r3_8_database_refusal_of_a_worker_change_shows_no_personal_data(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    session: Session,
) -> None:
    """A change the database refuses leaves the worker as it was, with a French message."""
    create(session=session, form=build_form())
    other_form = build_form(
        national_register_number=OTHER_NATIONAL_NUMBER,
        username='other',
        email='other@example.com',
    )
    create(session=session, form=other_form)
    worker = read_worker(session=session, username='other')
    monkeypatch.setattr(worker_admin, 'find_worker_form_error', lambda **_: None)
    form = build_worker_form(worker=worker)
    duplicate = form.model_copy(update={'national_register_number': VALID_NATIONAL_REGISTER_NUMBER})

    result = update_worker(session=session, worker_id=worker.id, form=duplicate, is_active=True)

    assert result.level == 'error'
    assert result.message == worker_admin.DATABASE_REFUSED_MESSAGE
    assert VALID_NATIONAL_REGISTER_NUMBER not in caplog.text
    stored_number = read_worker(session=session, username='other').national_register_number
    assert stored_number != VALID_NATIONAL_REGISTER_NUMBER


def test_r11_6_google_worker_has_no_password_to_set(session: Session) -> None:
    """Only local accounts have a password."""
    worker = build_worker(auth_method=AuthMethod.GOOGLE, email='lotte@example.com')
    session.add(worker)
    session.flush()

    with pytest.raises(ValueError):
        set_worker_password(session=session, worker_id=worker.id, password='a', confirmation='a')


def test_r3_5_worker_table_shows_no_national_register_number(session: Session) -> None:
    """The list names the status, never the national register number."""
    local_worker = build_worker(username='lotte', is_active=False)
    google_worker = build_worker(
        national_register_number=OTHER_NATIONAL_NUMBER,
        username='sam',
        auth_method=AuthMethod.GOOGLE,
        email='sam@example.com',
    )

    local_row = build_worker_row(worker=local_worker)
    google_row = build_worker_row(worker=google_worker)

    assert list(local_row) == [
        'Prénom',
        'Nom',
        'Type de travailleur',
        'E-mail',
        'IBAN',
        'Statut',
    ]
    assert local_row['Statut'] == 'Inactif'
    assert local_row['IBAN'] == 'BE97 0000 0000 0099'
    assert google_row['E-mail'] == 'sam@example.com'
    assert google_row['Statut'] == 'Actif'
    assert VALID_NATIONAL_REGISTER_NUMBER not in local_row.values()


def test_r11_10_admin_stores_the_postal_address_of_a_worker(session: Session) -> None:
    """Street, postal code and city are stored trimmed."""
    form = build_form()
    form.street = ' Avenue Factice 7 '
    form.postal_code = ' 1030 '
    form.city = ' Schaerbeek '

    level = create(session=session, form=form)

    stored_form = build_worker_form(worker=read_worker(session=session, username='e.janssens'))
    assert level == 'success'
    assert stored_form.street == 'Avenue Factice 7'
    assert stored_form.postal_code == '1030'
    assert stored_form.city == 'Schaerbeek'


@pytest.mark.parametrize(
    ('street', 'postal_code', 'city', 'message'),
    [
        ('', '', '', worker_admin.MISSING_ADDRESS_MESSAGE),
        ('Rue Imaginaire 12', '', 'Ixelles', worker_admin.MISSING_ADDRESS_MESSAGE),
        ('', '1050', 'Ixelles', worker_admin.MISSING_ADDRESS_MESSAGE),
        ('Rue Imaginaire 12', '1050', ' ', worker_admin.MISSING_ADDRESS_MESSAGE),
        ('Rue Imaginaire 12', '105', 'Ixelles', worker_admin.INVALID_POSTAL_CODE_MESSAGE),
        ('Rue Imaginaire 12', '75001', 'Paris', worker_admin.INVALID_POSTAL_CODE_MESSAGE),
    ],
)
def test_r11_10_postal_address_is_required_and_belgian(
    session: Session,
    street: str,
    postal_code: str,
    city: str,
    message: str,
) -> None:
    """A missing part of the address or a postal code that is not Belgian is refused."""
    form = build_form()
    form.street = street
    form.postal_code = postal_code
    form.city = city

    result = create_worker(
        session=session,
        form=form,
        password=PASSWORD,
        rates=build_rates(),
        today=TODAY,
    )

    assert result.level == 'error'
    assert result.message == message


def test_r11_1_workers_are_listed_active_first_then_by_type_then_by_first_name(
    session: Session,
) -> None:
    """Inactive workers come last; the types follow volunteer, article 17, flexi-job, freelancer."""
    workers = [
        build_worker(username='a', first_name='Zoé', worker_type=WorkerType.FREELANCER),
        build_worker(username='b', first_name='Bram', worker_type=WorkerType.ARTICLE_17),
        build_worker(username='c', first_name='Anna', worker_type=WorkerType.ARTICLE_17),
        build_worker(username='d', first_name='Yara', worker_type=WorkerType.VRIJWILLIGER),
        build_worker(username='e', first_name='Xavier', worker_type=WorkerType.FLEXI_JOB),
        build_worker(
            username='f',
            first_name='Aaron',
            worker_type=WorkerType.VRIJWILLIGER,
            is_active=False,
        ),
    ]
    for sequence, worker in enumerate(workers):
        worker.national_register_number = build_fake_national_register_number(
            birth_date=date(1990, 1, 1),
            sequence=100 + sequence,
        )
    session.add_all(workers)
    session.flush()

    first_names = [worker.first_name for worker in find_workers(session=session)]

    assert first_names == ['Yara', 'Anna', 'Bram', 'Xavier', 'Zoé', 'Aaron']
