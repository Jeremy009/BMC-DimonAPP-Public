"""The year-end fiches tab of the admin console: totals and the zip (R14.1 to R14.4).

The figures and the files live in fiches.py, belcotax.py and fiche_pdf.py; this module only
draws.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.belcotax import BELCOTAX_SCHEMA_FILE, BELCOTAX_SCHEMA_YEAR
from dimonapp.configuration import load_organisation
from dimonapp.database import open_session
from dimonapp.fiches import (
    build_fiche_lines,
    build_fiche_row,
    build_fiches_file_name,
    build_fiches_zip,
    find_fiche_problem,
    find_fiche_years,
)

FICHES_TAB = 'Fiches fiscales'
YEAR_LABEL = 'Année de revenus'
NO_FICHE_TEXT = 'Aucune activité article 17 acceptée par Dimona pour cette année.'
TOTALS_CAPTION = (
    'Totaux = activités article 17 non annulées et acceptées par Dimona. Pour un travailleur '
    "passé à un autre statut en cours d'année, seules ses activités article 17 comptent."
)
GENERATE_LABEL = 'Générer les fiches 281.27 (PDF) + XML Belcotax-on-web (zip)'


def build_deadline_text(year: int) -> str:
    """Give the legal deadline of a year and the schema of the Belcotax file (R14.4).

    For a year later than the schema stored with the code, the text says which schema must
    replace it before the fiches are submitted.
    """
    text = f'Échéance légale : fin février {year + 1}. Schéma XML : {BELCOTAX_SCHEMA_FILE}'
    if year <= BELCOTAX_SCHEMA_YEAR:
        return f'{text}.'
    return f'{text}, à mettre à jour vers belcotax-{year}.xsd dès sa publication.'


def render_fiches_tab(engine: sa.Engine, today: date) -> None:
    """Render the year dropdown, the totals per article 17 worker and the one button."""
    st.header(FICHES_TAB)
    with open_session(engine=engine) as session:
        years = find_fiche_years(session=session, today=today)
    year = st.selectbox(
        label=YEAR_LABEL,
        options=years,
        index=years.index(today.year),
        key='fiches_year',
    )

    with open_session(engine=engine) as session:
        lines = build_fiche_lines(session=session, year=year)
        organisation = load_organisation(session=session)
    if not lines:
        st.info(NO_FICHE_TEXT)
    else:
        rows = [build_fiche_row(line=line, year=year) for line in lines]
        st.table(data=rows, hide_index=True)
    st.caption(TOTALS_CAPTION)

    # The zip is only built when the admin asks for it (R14.1)
    problem = find_fiche_problem(organisation=organisation) if lines else None
    if problem is not None:
        st.warning(problem)
    if not lines or problem is not None:
        st.button(label=GENERATE_LABEL, type='primary', disabled=True, key='generate_fiches')
    else:
        st.download_button(
            label=GENERATE_LABEL,
            data=lambda: build_fiches_zip(
                lines=lines,
                organisation=organisation,
                year=year,
                created_on=today,
            ),
            file_name=build_fiches_file_name(year=year),
            mime='application/zip',
            type='primary',
            key='generate_fiches',
        )
    st.info(build_deadline_text(year=year))
