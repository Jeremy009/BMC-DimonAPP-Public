"""Worker management by the admin: create, edit, deactivate and set a password (FDS 7.2).

Plain functions on a database session, so the rules are tested without Streamlit. Workers are
never deleted (R11.5). National register numbers, IBANs and passwords never reach the logs
(R3.5): only the worker id is logged. A database refusal carries the values it was given, so it
becomes a French message and is never shown or logged as it is (R3.8).
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dimonapp.authentication import normalise_email
from dimonapp.configuration import is_belgian_postal_code
from dimonapp.french import format_iban
from dimonapp.iban import is_valid_iban, normalise_iban
from dimonapp.labels import ACTIVE_LABEL, INACTIVE_LABEL
from dimonapp.models import RATE_CODES, AuthMethod, CompensationRate, Worker, WorkerType
from dimonapp.national_register import (
    is_valid_national_register_number,
    normalise_national_register_number,
)
from dimonapp.passwords import hash_password
from dimonapp.results import ActionResult
from dimonapp.sign_in_lockout import clear_failed_sign_ins
from dimonapp.worker_types import WORKER_TYPE_LABELS, build_worker_name

logger = logging.getLogger(__name__)

NOT_SAVED_PREFIX = 'Travailleur non enregistré : '
MISSING_NAME_MESSAGE = f'{NOT_SAVED_PREFIX}indiquez le prénom et le nom.'
INVALID_NATIONAL_NUMBER_MESSAGE = (
    f"{NOT_SAVED_PREFIX}le numéro de registre national n'est pas valide (clé de contrôle)."
)
MISSING_IBAN_MESSAGE = f"{NOT_SAVED_PREFIX}indiquez l'IBAN."
INVALID_IBAN_MESSAGE = f"{NOT_SAVED_PREFIX}l'IBAN n'est pas valide (clé de contrôle)."
MISSING_USERNAME_MESSAGE = f"{NOT_SAVED_PREFIX}indiquez le nom d'utilisateur."
MISSING_EMAIL_MESSAGE = f"{NOT_SAVED_PREFIX}indiquez l'adresse e-mail."
NATIONAL_NUMBER_TAKEN_MESSAGE = (
    f'{NOT_SAVED_PREFIX}ce numéro de registre national est déjà utilisé.'
)
USERNAME_TAKEN_MESSAGE = f"{NOT_SAVED_PREFIX}ce nom d'utilisateur est déjà utilisé."
EMAIL_TAKEN_MESSAGE = f'{NOT_SAVED_PREFIX}cette adresse e-mail est déjà utilisée.'
MISSING_ADDRESS_MESSAGE = (
    f'{NOT_SAVED_PREFIX}indiquez la rue et le numéro, le code postal et la commune.'
)
INVALID_POSTAL_CODE_MESSAGE = (
    f'{NOT_SAVED_PREFIX}le code postal doit être un code postal belge (quatre chiffres).'
)
MISSING_PASSWORD_MESSAGE = f'{NOT_SAVED_PREFIX}indiquez un mot de passe pour le compte local.'
DATABASE_REFUSED_MESSAGE = (
    f"{NOT_SAVED_PREFIX}la base de données a refusé l'enregistrement. Réessayez."
)
# A password set by the admin has at least this many characters (R11.9).
MIN_PASSWORD_LENGTH = 10
SHORT_PASSWORD_TEXT = f'le mot de passe doit compter au moins {MIN_PASSWORD_LENGTH} caractères.'
SHORT_PASSWORD_MESSAGE = f'{NOT_SAVED_PREFIX}{SHORT_PASSWORD_TEXT}'
MISSING_RATES_MESSAGE = (
    f"{NOT_SAVED_PREFIX}indiquez un tarif pour chacun des huit types d'activité."
)

PASSWORD_NOT_SAVED_PREFIX = 'Mot de passe non enregistré : '
EMPTY_PASSWORD_MESSAGE = f'{PASSWORD_NOT_SAVED_PREFIX}indiquez le nouveau mot de passe.'
SHORT_NEW_PASSWORD_MESSAGE = f'{PASSWORD_NOT_SAVED_PREFIX}{SHORT_PASSWORD_TEXT}'
PASSWORD_MISMATCH_MESSAGE = (
    f'{PASSWORD_NOT_SAVED_PREFIX}les deux mots de passe ne sont pas identiques.'
)


class WorkerForm(BaseModel):
    """What the admin enters about a worker (R11.2), all of it required.

    The postal address (street and number, postal code, city) is printed on the fiche 281.27
    (R11.10).
    """

    first_name: str
    last_name: str
    national_register_number: str
    iban: str
    worker_type: WorkerType
    username: str
    email: str
    auth_method: AuthMethod
    street: str
    postal_code: str
    city: str


def clean_worker_form(form: WorkerForm) -> WorkerForm:
    """Give the form as it is stored: trimmed, the numbers without separators.

    The e-mail is kept in the form used to match a Google sign-in.
    """
    national_register_number = normalise_national_register_number(
        number=form.national_register_number,
    )
    iban = normalise_iban(iban=form.iban)
    return WorkerForm(
        first_name=form.first_name.strip(),
        last_name=form.last_name.strip(),
        national_register_number=national_register_number,
        iban=iban,
        worker_type=form.worker_type,
        username=form.username.strip(),
        email=normalise_email(email=form.email),
        auth_method=form.auth_method,
        street=form.street.strip(),
        postal_code=form.postal_code.strip(),
        city=form.city.strip(),
    )


def build_worker_form(worker: Worker) -> WorkerForm:
    """Give the stored values of a worker, to open the edit form on."""
    return WorkerForm(
        first_name=worker.first_name,
        last_name=worker.last_name,
        national_register_number=worker.national_register_number,
        iban=worker.iban,
        worker_type=worker.worker_type,
        username=worker.username,
        email=worker.email,
        auth_method=worker.auth_method,
        street=worker.street,
        postal_code=worker.postal_code,
        city=worker.city,
    )


def is_taken(session: Session, condition: sa.ColumnElement[bool], worker_id: Optional[int]) -> bool:
    """Tell whether another worker than the one being edited matches a condition."""
    query = sa.select(Worker.id).where(condition)
    if worker_id is not None:
        query = query.where(Worker.id != worker_id)
    return session.scalars(query).first() is not None


def find_worker_form_error(
    session: Session,
    form: WorkerForm,
    worker_id: Optional[int],
) -> Optional[str]:
    """Give the French message of the first problem in a cleaned form, or None.

    The national register number and the IBAN are checked with their checksum (R11.3, R11.8).
    The e-mail address and the Belgian postal address are required (R11.2, R11.10).
    worker_id is the worker being edited, or None for a new one.
    """
    # Check the values themselves
    if not form.first_name or not form.last_name:
        return MISSING_NAME_MESSAGE
    if not is_valid_national_register_number(number=form.national_register_number):
        return INVALID_NATIONAL_NUMBER_MESSAGE
    if not form.iban:
        return MISSING_IBAN_MESSAGE
    if not is_valid_iban(iban=form.iban):
        return INVALID_IBAN_MESSAGE
    if not form.username:
        return MISSING_USERNAME_MESSAGE
    if not form.email:
        return MISSING_EMAIL_MESSAGE
    if not form.street or not form.postal_code or not form.city:
        return MISSING_ADDRESS_MESSAGE
    if not is_belgian_postal_code(postal_code=form.postal_code):
        return INVALID_POSTAL_CODE_MESSAGE

    # Check what must be unique among the workers
    same_number = Worker.national_register_number == form.national_register_number
    if is_taken(session=session, condition=same_number, worker_id=worker_id):
        return NATIONAL_NUMBER_TAKEN_MESSAGE
    same_username = Worker.username == form.username
    if is_taken(session=session, condition=same_username, worker_id=worker_id):
        return USERNAME_TAKEN_MESSAGE
    same_email = sa.func.lower(Worker.email) == form.email
    if is_taken(session=session, condition=same_email, worker_id=worker_id):
        return EMAIL_TAKEN_MESSAGE
    return None


def apply_worker_form(worker: Worker, form: WorkerForm) -> None:
    """Copy a cleaned form onto a worker."""
    worker.first_name = form.first_name
    worker.last_name = form.last_name
    worker.national_register_number = form.national_register_number
    worker.iban = form.iban
    worker.worker_type = form.worker_type
    worker.username = form.username
    worker.email = form.email
    worker.auth_method = form.auth_method
    worker.street = form.street
    worker.postal_code = form.postal_code
    worker.city = form.city


def create_worker(
    session: Session,
    form: WorkerForm,
    password: str,
    rates: dict[str, Optional[Decimal]],
    today: date,
) -> ActionResult:
    """Create a worker account with its eleven rates, valid from today (R11.1, FDS 7.4).

    All eleven rates are required, so the submission gate always finds a rate. A local account
    needs a password of at least 10 characters, stored as its hash only (R11.4, R11.9); there is
    no forced change at first login.
    """
    # Check the form, the password and the rates
    cleaned_form = clean_worker_form(form=form)
    form_error = find_worker_form_error(session=session, form=cleaned_form, worker_id=None)
    if form_error is not None:
        return ActionResult(level='error', message=form_error)
    is_local = cleaned_form.auth_method == AuthMethod.LOCAL
    if is_local and not password:
        return ActionResult(level='error', message=MISSING_PASSWORD_MESSAGE)
    if is_local and len(password) < MIN_PASSWORD_LENGTH:
        return ActionResult(level='error', message=SHORT_PASSWORD_MESSAGE)
    missing_rates = [code for code in RATE_CODES if rates.get(code) is None]
    if missing_rates:
        return ActionResult(level='error', message=MISSING_RATES_MESSAGE)

    # Store the worker; a refusal of the database, such as a number another admin saved at the
    # same moment, rolls back this worker only
    worker = Worker(is_active=True)
    apply_worker_form(worker=worker, form=cleaned_form)
    if is_local:
        worker.password_hash = hash_password(password=password)
    try:
        with session.begin_nested():
            session.add(worker)
            session.flush()
    except IntegrityError:
        logger.warning('Worker not created: refused by the database.')
        return ActionResult(level='error', message=DATABASE_REFUSED_MESSAGE)

    # Store the compensation sheet
    for activity_type in RATE_CODES:
        rate = CompensationRate(
            worker_id=worker.id,
            activity_type=activity_type,
            amount=rates[activity_type],
            valid_from=today,
        )
        session.add(rate)
    session.flush()
    logger.info(f'Worker {worker.id} created.')
    name = build_worker_name(worker=worker)
    return ActionResult(level='success', message=f'Travailleur créé : {name}.')


def update_worker(
    session: Session,
    worker_id: int,
    form: WorkerForm,
    is_active: bool,
) -> ActionResult:
    """Change a worker account, and deactivate or reactivate it (R11.1, R11.5).

    The worker type ladder of FDS 5.1 is applied by the admin and not checked here (R5.3).
    """
    worker = session.get(Worker, worker_id)
    if worker is None:
        raise ValueError('Unknown worker.')
    cleaned_form = clean_worker_form(form=form)
    form_error = find_worker_form_error(session=session, form=cleaned_form, worker_id=worker_id)
    if form_error is not None:
        return ActionResult(level='error', message=form_error)

    # A refusal of the database rolls back this change only
    try:
        with session.begin_nested():
            apply_worker_form(worker=worker, form=cleaned_form)
            worker.is_active = is_active
            session.flush()
    except IntegrityError:
        logger.warning(f'Worker {worker_id} not updated: refused by the database.')
        return ActionResult(level='error', message=DATABASE_REFUSED_MESSAGE)
    logger.info(f'Worker {worker_id} updated; active: {is_active}.')
    name = build_worker_name(worker=worker)
    return ActionResult(level='success', message=f'Travailleur modifié : {name}.')


def set_worker_password(
    session: Session,
    worker_id: int,
    password: str,
    confirmation: str,
) -> ActionResult:
    """Set or reset the password of a local worker, entered twice (R11.6, R11.9).

    Only the Argon2 hash is stored; the password itself is never kept, shown or logged. A new
    password also unlocks the username after wrong passwords (R4.14).
    """
    worker = session.get(Worker, worker_id)
    if worker is None or worker.auth_method != AuthMethod.LOCAL:
        raise ValueError('Unknown worker, or not a local account.')
    if not password:
        return ActionResult(level='error', message=EMPTY_PASSWORD_MESSAGE)
    if len(password) < MIN_PASSWORD_LENGTH:
        return ActionResult(level='error', message=SHORT_NEW_PASSWORD_MESSAGE)
    if password != confirmation:
        return ActionResult(level='error', message=PASSWORD_MISMATCH_MESSAGE)

    worker.password_hash = hash_password(password=password)
    clear_failed_sign_ins(session=session, username=worker.username)
    session.flush()
    logger.info(f'Password set for worker {worker_id}.')
    name = build_worker_name(worker=worker)
    return ActionResult(level='success', message=f'Mot de passe enregistré pour {name}.')


def find_workers(session: Session) -> list[Worker]:
    """Give every worker: active ones first, then by worker type, then by first name.

    The worker types follow the order of FDS section 5: volunteer, article 17, flexi-job,
    freelancer.
    """
    query = sa.select(Worker).order_by(
        Worker.is_active.desc(),
        Worker.worker_type,
        Worker.first_name,
        Worker.last_name,
        Worker.id,
    )
    return list(session.scalars(query))


def build_worker_row(worker: Worker) -> dict[str, str]:
    """Build the table row of one worker; the national register number is not shown."""
    return {
        'Prénom': worker.first_name,
        'Nom': worker.last_name,
        'Type de travailleur': WORKER_TYPE_LABELS[worker.worker_type],
        'E-mail': worker.email,
        'IBAN': format_iban(iban=worker.iban),
        'Statut': ACTIVE_LABEL if worker.is_active else INACTIVE_LABEL,
    }
