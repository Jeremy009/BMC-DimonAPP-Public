"""The monthly report tab of the admin console: totals, IBAN and payment file (R13.1, R13.2).

The figures live in monthly_report.py and the file in payment_file.py; this module only draws.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.clock import read_now
from dimonapp.configuration import load_organisation
from dimonapp.database import open_session
from dimonapp.french import format_amount
from dimonapp.monthly_report import (
    build_monthly_report,
    build_report_row,
    sum_report,
)
from dimonapp.payment_file import (
    build_payment_file,
    build_payment_file_name,
    find_payment_file_problem,
)
from dimonapp.widgets import render_month_navigation

REPORT_TAB = 'Rapport mensuel'
NO_ACTIVITY_TEXT = 'Aucune activité comptabilisée pour ce mois.'
TOTAL_LABEL = 'Total à payer'
COUNTED_CAPTION = (
    'Activités comptabilisées uniquement : les activités annulées et refusées par Dimona '
    'sont exclues.'
)
EXPORT_LABEL = 'Exporter le fichier de paiement (SEPA pain.001 pour Belfius)'


def render_report_tab(engine: sa.Engine, today: date) -> None:
    """Render the month arrows, the table per worker, the total to pay and the export.

    The month moves with previous and next arrows, as in the worker's monthly overview.
    """
    st.header(REPORT_TAB)
    month_start = render_month_navigation(key='report', today=today)

    with open_session(engine=engine) as session:
        lines = build_monthly_report(session=session, month_start=month_start)
        organisation = load_organisation(session=session)
    rows = [build_report_row(line=line) for line in lines]
    total = sum_report(lines=lines)

    if not rows:
        st.info(NO_ACTIVITY_TEXT)
    else:
        st.table(data=rows, hide_index=True)
    st.metric(label=TOTAL_LABEL, value=format_amount(amount=total))
    st.caption(COUNTED_CAPTION)

    # The payment file is only built when the admin asks for it (R13.2)
    problem = find_payment_file_problem(lines=lines, organisation=organisation)
    if problem is not None:
        if rows:
            st.warning(problem)
        st.button(label=EXPORT_LABEL, type='primary', disabled=True, key='export_payments')
        return
    st.download_button(
        label=EXPORT_LABEL,
        data=lambda: build_payment_file(
            lines=lines,
            organisation=organisation,
            month_start=month_start,
            created_at=read_now(),
        ),
        file_name=build_payment_file_name(month_start=month_start),
        mime='application/xml',
        type='primary',
        key='export_payments',
    )
