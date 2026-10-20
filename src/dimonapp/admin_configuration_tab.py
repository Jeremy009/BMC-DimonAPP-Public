"""The configuration tab of the admin console: yearly limits and BMC's details (FDS 7.7).

The rules live in configuration.py; this module only draws and passes on.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.configuration import (
    EURO_COLUMN,
    HOURS_COLUMN,
    MIN_HOURS_COLUMN,
    PERIOD_COLUMN,
    WORKER_TYPE_COLUMN,
    OrganisationForm,
    build_limit_table,
    find_configuration_years,
    is_year_configured,
    load_limit_lines,
    load_organisation,
    read_limit_table,
    save_limit_lines,
    save_organisation,
)
from dimonapp.database import open_session
from dimonapp.french import format_iban
from dimonapp.widgets import (
    build_grid_cells,
    keep_result,
    read_form_version,
    reset_form,
    show_kept_result,
)

CONFIGURATION_TAB = 'Configuration'
LIMITS_HEADING = 'Limites légales annuelles'
YEAR_LABEL = 'Année'
NOT_CONFIGURED_SUFFIX = ' (non configurée)'
LIMITS_CAPTION = (
    "Vide = pas de limite. Les indépendants n'ont pas de limites. Chaque activité est vérifiée "
    "selon les limites de l'année de sa date."
)
SAVE_LIMITS_LABEL = 'Enregistrer les limites'
ORGANISATION_HEADING = 'Coordonnées de BMC'
COMPANY_NUMBER_LABEL = "Numéro d'entreprise"
NAME_LABEL = 'Nom'
ADDRESS_LABEL = 'Rue et numéro'
POSTAL_CODE_LABEL = 'Code postal'
CITY_LABEL = 'Commune'
CONTACT_PERSON_LABEL = 'Personne de contact'
PHONE_LABEL = 'Téléphone'
CONTACT_LABEL = 'E-mail de contact'
ORGANISATION_IBAN_LABEL = 'IBAN de BMC (compte des paiements)'
ORGANISATION_CAPTION = (
    'Ces coordonnées figurent sur les fiches 281.27, dans le fichier Belcotax et dans le '
    'fichier de paiement.'
)
# The fields of BMC's details, in the order shown, left and right in turn.
ORGANISATION_FIELDS = {
    'company_number': COMPANY_NUMBER_LABEL,
    'name': NAME_LABEL,
    'address': ADDRESS_LABEL,
    'postal_code': POSTAL_CODE_LABEL,
    'city': CITY_LABEL,
    'contact_person': CONTACT_PERSON_LABEL,
    'phone': PHONE_LABEL,
    'contact_details': CONTACT_LABEL,
    'iban': ORGANISATION_IBAN_LABEL,
}
SAVE_ORGANISATION_LABEL = 'Enregistrer les coordonnées'
LIMITS_FEEDBACK_KEY = 'limits_feedback'
ORGANISATION_FEEDBACK_KEY = 'organisation_feedback'
FORM_VERSION_KEY = 'configuration_form_version'


def render_limits(engine: sa.Engine, today: date) -> None:
    """Render the limits of one year as an editable table and save them (R15.1).

    There is no "active year": the dropdown only picks the year being edited (R15.3).
    """
    st.markdown(f'#### {LIMITS_HEADING}')
    show_kept_result(key=LIMITS_FEEDBACK_KEY)
    with open_session(engine=engine) as session:
        years = find_configuration_years(session=session, today=today)
        configured_years = {
            year for year in years if is_year_configured(session=session, year=year)
        }
    year_labels = {
        year: str(year) if year in configured_years else f'{year}{NOT_CONFIGURED_SUFFIX}'
        for year in years
    }
    year = st.selectbox(
        label=YEAR_LABEL,
        options=years,
        index=years.index(today.year),
        format_func=lambda option: year_labels[option],
        key='configuration_year',
    )

    with open_session(engine=engine) as session:
        lines = load_limit_lines(session=session, year=year)
    version = read_form_version(key=FORM_VERSION_KEY)
    number_column = st.column_config.NumberColumn(min_value=0)
    edited_rows = st.data_editor(
        data=build_limit_table(lines=lines),
        hide_index=True,
        num_rows='fixed',
        disabled=[WORKER_TYPE_COLUMN, PERIOD_COLUMN],
        column_config={
            HOURS_COLUMN: number_column,
            EURO_COLUMN: number_column,
            MIN_HOURS_COLUMN: number_column,
        },
        key=f'limits_{year}_{version}',
    )
    st.caption(LIMITS_CAPTION)
    if not st.button(label=SAVE_LIMITS_LABEL, type='primary', key='save_limits'):
        return

    edited_lines = read_limit_table(rows=edited_rows)
    with open_session(engine=engine) as session:
        result = save_limit_lines(session=session, year=year, lines=edited_lines)
    if result.level == 'error':
        st.error(result.message)
        return
    keep_result(key=LIMITS_FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_organisation(engine: sa.Engine) -> None:
    """Render BMC's company number and debtor details and save them (R15.4)."""
    st.markdown(f'#### {ORGANISATION_HEADING}')
    show_kept_result(key=ORGANISATION_FEEDBACK_KEY)
    with open_session(engine=engine) as session:
        stored = load_organisation(session=session)
    version = read_form_version(key=FORM_VERSION_KEY)
    prefix = f'organisation_{version}'
    cells = build_grid_cells(n_cells=len(ORGANISATION_FIELDS), n_columns=2)
    stored_values = stored.model_dump()
    stored_values['iban'] = format_iban(iban=stored.iban)
    values = {}
    for cell, field in zip(cells, ORGANISATION_FIELDS, strict=True):
        values[field] = cell.text_input(
            label=ORGANISATION_FIELDS[field],
            value=stored_values[field],
            key=f'{prefix}_{field}',
        )
    st.caption(ORGANISATION_CAPTION)
    if not st.button(label=SAVE_ORGANISATION_LABEL, type='primary', key='save_organisation'):
        return

    form = OrganisationForm(**values)
    with open_session(engine=engine) as session:
        result = save_organisation(session=session, form=form)
    if result.level != 'success':
        st.error(result.message)
        return
    keep_result(key=ORGANISATION_FEEDBACK_KEY, result=result)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_configuration_tab(engine: sa.Engine, today: date) -> None:
    """Render the yearly limits and, below them, BMC's details."""
    st.header(CONFIGURATION_TAB)
    render_limits(engine=engine, today=today)
    render_organisation(engine=engine)
