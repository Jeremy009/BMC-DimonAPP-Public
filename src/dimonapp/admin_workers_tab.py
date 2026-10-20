"""The workers tab of the admin console: list, create, edit and set a password (R11.1 to R11.7).

The rules live in worker_admin.py; this module only draws and passes on. Password fields are
masked and never filled in by the application (R11.6).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
import streamlit as st

from dimonapp.database import open_session
from dimonapp.labels import AUTH_METHOD_LABELS
from dimonapp.models import AuthMethod, WorkerType
from dimonapp.rate_sheets import DEFAULT_RATES
from dimonapp.widgets import (
    build_grid_cells,
    keep_result,
    read_form_version,
    reset_form,
    show_kept_result,
)
from dimonapp.worker_admin import (
    WorkerForm,
    build_worker_form,
    build_worker_row,
    create_worker,
    find_workers,
    set_worker_password,
    update_worker,
)
from dimonapp.worker_types import WORKER_TYPE_LABELS, build_worker_name, build_worker_option

WORKERS_TAB = 'Travailleurs'
NO_WORKER_TEXT = 'Aucun travailleur enregistré.'
CREATE_EXPANDER = 'Ajouter un travailleur'
EDIT_EXPANDER = 'Modifier ou désactiver un travailleur'
PASSWORD_EXPANDER = "Définir le mot de passe d'un travailleur"

FIRST_NAME_LABEL = 'Prénom'
LAST_NAME_LABEL = 'Nom'
NATIONAL_NUMBER_LABEL = 'Numéro de registre national'
WORKER_TYPE_LABEL = 'Type de travailleur'
IBAN_LABEL = 'IBAN'
AUTH_METHOD_LABEL = 'Méthode de connexion'
USERNAME_LABEL = "Nom d'utilisateur"
EMAIL_LABEL = 'E-mail'
PASSWORD_LABEL = 'Mot de passe'
STREET_LABEL = 'Rue et numéro'
POSTAL_CODE_LABEL = 'Code postal'
CITY_LABEL = 'Commune'
ADDRESS_HELP = "L'adresse figure sur la fiche fiscale 281.27 (article 17)."
RATES_HEADING = 'Tarifs'
CREATE_LABEL = 'Créer le travailleur'

WORKER_LABEL = 'Travailleur'
ACTIVE_LABEL = 'Compte actif'
SAVE_LABEL = 'Enregistrer les modifications'

NO_LOCAL_WORKER_TEXT = 'Aucun travailleur avec un compte local.'
NEW_PASSWORD_LABEL = 'Nouveau mot de passe'
CONFIRM_PASSWORD_LABEL = 'Confirmer le mot de passe'
SAVE_PASSWORD_LABEL = 'Enregistrer le mot de passe'

FEEDBACK_KEY = 'workers_feedback'
FORM_VERSION_KEY = 'workers_form_version'
RATE_STEP = 0.5
# Where the note of an activity label starts; left out above the rate fields, to keep them short.
LABEL_NOTE_START = ' ('
# What the create form opens on: everything empty, the first worker type and login method.
NEW_WORKER_FORM = WorkerForm(
    first_name='',
    last_name='',
    national_register_number='',
    iban='',
    worker_type=WorkerType.VRIJWILLIGER,
    username='',
    email='',
    auth_method=AuthMethod.LOCAL,
    street='',
    postal_code='',
    city='',
)


def render_worker_fields(
    prefix: str,
    defaults: WorkerForm,
    with_password: bool,
) -> tuple[WorkerForm, str]:
    """Render the fields of a worker account; give what was entered and the password.

    The password field only exists in the create form, for a local account (R11.4).
    """
    worker_types = list(WorkerType)
    auth_methods = [AuthMethod.LOCAL, AuthMethod.GOOGLE]
    # One row of columns per line, so the tab key moves left to right, then down
    row = st.columns(3)
    first_name = row[0].text_input(
        label=FIRST_NAME_LABEL,
        value=defaults.first_name,
        key=f'{prefix}_first_name',
    )
    last_name = row[1].text_input(
        label=LAST_NAME_LABEL,
        value=defaults.last_name,
        key=f'{prefix}_last_name',
    )
    national_register_number = row[2].text_input(
        label=NATIONAL_NUMBER_LABEL,
        value=defaults.national_register_number,
        key=f'{prefix}_national_register_number',
    )
    row = st.columns(3)
    worker_type = row[0].selectbox(
        label=WORKER_TYPE_LABEL,
        options=worker_types,
        index=worker_types.index(defaults.worker_type),
        format_func=lambda option: WORKER_TYPE_LABELS[option],
        key=f'{prefix}_worker_type',
    )
    iban = row[1].text_input(
        label=IBAN_LABEL,
        value=defaults.iban,
        key=f'{prefix}_iban',
    )
    auth_method = row[2].selectbox(
        label=AUTH_METHOD_LABEL,
        options=auth_methods,
        index=auth_methods.index(defaults.auth_method),
        format_func=lambda option: AUTH_METHOD_LABELS[option],
        key=f'{prefix}_auth_method',
    )
    row = st.columns(3)
    username = row[0].text_input(
        label=USERNAME_LABEL,
        value=defaults.username,
        key=f'{prefix}_username',
    )
    email = row[1].text_input(
        label=EMAIL_LABEL,
        value=defaults.email,
        key=f'{prefix}_email',
    )
    password = ''
    if with_password and auth_method == AuthMethod.LOCAL:
        password = row[2].text_input(
            label=PASSWORD_LABEL,
            type='password',
            key=f'{prefix}_password',
        )
    # The address on its own row: the password field only exists in some forms
    street_column, postal_code_column, city_column = st.columns(3)
    street = street_column.text_input(
        label=STREET_LABEL,
        value=defaults.street,
        help=ADDRESS_HELP,
        key=f'{prefix}_street',
    )
    postal_code = postal_code_column.text_input(
        label=POSTAL_CODE_LABEL,
        value=defaults.postal_code,
        key=f'{prefix}_postal_code',
    )
    city = city_column.text_input(
        label=CITY_LABEL,
        value=defaults.city,
        key=f'{prefix}_city',
    )
    form = WorkerForm(
        first_name=first_name,
        last_name=last_name,
        national_register_number=national_register_number,
        iban=iban,
        worker_type=worker_type,
        username=username,
        email=email,
        auth_method=auth_method,
        street=street,
        postal_code=postal_code,
        city=city,
    )
    return form, password


def shorten_activity_label(label: str) -> str:
    """Shorten an activity label for a rate field: Démontage difficile, without its note."""
    return label.split(LABEL_NOTE_START)[0]


def render_rate_fields(
    prefix: str,
    activity_labels: dict[str, str],
) -> dict[str, Optional[Decimal]]:
    """Render one rate field per activity type and supplement (FDS 7.4).

    Each field opens on the standard BMC rate, which the admin changes where needed (R6.12).
    """
    st.markdown(f'**{RATES_HEADING}**')
    cells = build_grid_cells(n_cells=len(activity_labels), n_columns=4)
    rates: dict[str, Optional[Decimal]] = {}
    for cell, activity_type in zip(cells, activity_labels, strict=True):
        amount = cell.number_input(
            label=shorten_activity_label(label=activity_labels[activity_type]),
            value=float(DEFAULT_RATES[activity_type]),
            min_value=0.0,
            step=RATE_STEP,
            format='%.2f',
            key=f'{prefix}_rate_{activity_type}',
        )
        rates[activity_type] = Decimal(str(amount)) if amount is not None else None
    return rates


def render_create_form(
    engine: sa.Engine,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the form that creates a worker with the eleven rates (R11.1, R4.4)."""
    version = read_form_version(key=FORM_VERSION_KEY)
    prefix = f'create_{version}'
    form, password = render_worker_fields(
        prefix=prefix, defaults=NEW_WORKER_FORM, with_password=True
    )
    rates = render_rate_fields(prefix=prefix, activity_labels=activity_labels)
    if not st.button(label=CREATE_LABEL, type='primary', key='create_worker'):
        return

    with open_session(engine=engine) as session:
        result = create_worker(
            session=session,
            form=form,
            password=password,
            rates=rates,
            today=today,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    keep_result(key=FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_edit_form(
    engine: sa.Engine,
    forms: dict[int, WorkerForm],
    options: dict[int, str],
    active_workers: set[int],
) -> None:
    """Render the form that corrects a worker and deactivates or reactivates it (R11.1, R11.5)."""
    worker_id = st.selectbox(
        label=WORKER_LABEL,
        options=list(options),
        format_func=lambda option: options[option],
        key='edit_worker',
    )
    version = read_form_version(key=FORM_VERSION_KEY)
    prefix = f'edit_{worker_id}_{version}'
    form, _ = render_worker_fields(prefix=prefix, defaults=forms[worker_id], with_password=False)
    is_active = st.checkbox(
        label=ACTIVE_LABEL,
        value=worker_id in active_workers,
        key=f'{prefix}_is_active',
    )
    if not st.button(label=SAVE_LABEL, key='save_worker'):
        return

    with open_session(engine=engine) as session:
        result = update_worker(
            session=session,
            worker_id=worker_id,
            form=form,
            is_active=is_active,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    keep_result(key=FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_password_form(engine: sa.Engine, local_options: dict[int, str]) -> None:
    """Render the two masked fields that set a local worker's password (R11.6)."""
    if not local_options:
        st.info(NO_LOCAL_WORKER_TEXT)
        return
    version = read_form_version(key=FORM_VERSION_KEY)
    worker_column, password_column, confirmation_column = st.columns(3)
    worker_id = worker_column.selectbox(
        label=WORKER_LABEL,
        options=list(local_options),
        format_func=lambda option: local_options[option],
        key='password_worker',
    )
    password = password_column.text_input(
        label=NEW_PASSWORD_LABEL,
        type='password',
        key=f'password_{version}_new',
    )
    confirmation = confirmation_column.text_input(
        label=CONFIRM_PASSWORD_LABEL,
        type='password',
        key=f'password_{version}_confirmation',
    )
    if not st.button(label=SAVE_PASSWORD_LABEL, key='save_password'):
        return

    with open_session(engine=engine) as session:
        result = set_worker_password(
            session=session,
            worker_id=worker_id,
            password=password,
            confirmation=confirmation,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    keep_result(key=FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_workers_tab(
    engine: sa.Engine,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the list of workers and the three forms below it."""
    st.header(WORKERS_TAB)
    show_kept_result(key=FEEDBACK_KEY)

    # Everything the forms need, read in one go
    with open_session(engine=engine) as session:
        workers = find_workers(session=session)
        rows = [build_worker_row(worker=worker) for worker in workers]
        forms = {worker.id: build_worker_form(worker=worker) for worker in workers}
        options = {worker.id: build_worker_option(worker=worker) for worker in workers}
        active_workers = {worker.id for worker in workers if worker.is_active}
        local_options = {
            worker.id: f'{build_worker_name(worker=worker)} ({worker.username})'
            for worker in workers
            if worker.auth_method == AuthMethod.LOCAL
        }

    if not rows:
        st.info(NO_WORKER_TEXT)
    else:
        st.table(data=rows, hide_index=True)
    with st.expander(label=CREATE_EXPANDER):
        render_create_form(
            engine=engine,
            activity_labels=activity_labels,
            today=today,
        )
    if not rows:
        return
    with st.expander(label=EDIT_EXPANDER):
        render_edit_form(
            engine=engine,
            forms=forms,
            options=options,
            active_workers=active_workers,
        )
    with st.expander(label=PASSWORD_EXPANDER):
        render_password_form(engine=engine, local_options=local_options)
