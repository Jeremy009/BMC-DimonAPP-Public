"""The compensation tab of the admin console: a worker's rates and new versions (FDS 7.4).

The rules live in rate_sheets.py; this module only draws and passes on.
"""

from datetime import date
from decimal import Decimal

import sqlalchemy as sa
import streamlit as st

from dimonapp.admin_widgets import render_worker_select
from dimonapp.database import open_session
from dimonapp.labels import RATE_UNITS
from dimonapp.models import CompensationModel
from dimonapp.rate_sheets import (
    build_sheet_rows,
    build_version_rows,
    find_worker_rates,
    save_rate_version,
)
from dimonapp.widgets import keep_result, read_form_version, reset_form, show_kept_result

COMPENSATION_TAB = 'Rémunération'
NEW_VERSION_EXPANDER = 'Nouvelle version de tarif'
ALL_VERSIONS_EXPANDER = 'Toutes les versions de tarif'
ACTIVITY_TYPE_LABEL = "Type d'activité"
VALID_FROM_LABEL = 'Valable à partir du'
SAVE_RATE_LABEL = 'Enregistrer le tarif'
RATE_CAPTION = (
    'Une nouvelle activité utilise le tarif valable à sa date. Les activités déjà déclarées '
    'gardent leur montant.'
)
FEEDBACK_KEY = 'compensation_feedback'
FORM_VERSION_KEY = 'compensation_form_version'
RATE_STEP = 0.5


def render_new_version_form(
    engine: sa.Engine,
    worker_id: int,
    activity_labels: dict[str, str],
    compensation_models: dict[str, CompensationModel],
    today: date,
) -> None:
    """Render the form that adds a rate version valid from a date (R6.7)."""
    version = read_form_version(key=FORM_VERSION_KEY)
    prefix = f'rate_{worker_id}_{version}'
    type_column, amount_column, date_column = st.columns(3)
    activity_type = type_column.selectbox(
        label=ACTIVITY_TYPE_LABEL,
        options=list(activity_labels),
        format_func=lambda code: activity_labels[code],
        key=f'{prefix}_activity_type',
    )
    # The label tells which rate is entered: per hour or per activity
    unit = RATE_UNITS[compensation_models[activity_type]]
    amount = amount_column.number_input(
        label=f'Nouveau tarif (€ / {unit})',
        value=None,
        min_value=0.0,
        step=RATE_STEP,
        format='%.2f',
        key=f'{prefix}_amount',
    )
    valid_from = date_column.date_input(
        label=VALID_FROM_LABEL,
        value=today,
        format='DD/MM/YYYY',
        key=f'{prefix}_valid_from',
    )
    is_clicked = st.button(label=SAVE_RATE_LABEL, key='save_rate')
    st.caption(RATE_CAPTION)
    if not is_clicked:
        return

    with open_session(engine=engine) as session:
        result = save_rate_version(
            session=session,
            worker_id=worker_id,
            activity_type=activity_type,
            amount=Decimal(str(amount)) if amount is not None else None,
            valid_from=valid_from,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    keep_result(key=FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_compensation_tab(
    engine: sa.Engine,
    activity_labels: dict[str, str],
    compensation_models: dict[str, CompensationModel],
    today: date,
) -> None:
    """Render the compensation sheet of a worker: eleven rates with their model (R6.6)."""
    st.header(COMPENSATION_TAB)
    worker_id = render_worker_select(engine=engine, key='compensation_worker')
    if worker_id is None:
        return
    show_kept_result(key=FEEDBACK_KEY)

    with open_session(engine=engine) as session:
        rates = find_worker_rates(session=session, worker_id=worker_id)
        sheet_rows = build_sheet_rows(
            rates=rates,
            activity_labels=activity_labels,
            compensation_models=compensation_models,
            today=today,
        )
        version_rows = build_version_rows(
            rates=rates,
            activity_labels=activity_labels,
            compensation_models=compensation_models,
        )

    st.table(data=sheet_rows, hide_index=True)
    with st.expander(label=NEW_VERSION_EXPANDER):
        render_new_version_form(
            engine=engine,
            worker_id=worker_id,
            activity_labels=activity_labels,
            compensation_models=compensation_models,
            today=today,
        )
    with st.expander(label=ALL_VERSIONS_EXPANDER):
        st.table(data=version_rows, hide_index=True)
