"""The admin console: eight tabs, the dashboard first (R10.1, R18.2).

Each tab lives in its own module; this one draws the title and the tabs.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.activity_types import load_activity_types
from dimonapp.admin_activities_tab import ACTIVITIES_TAB, render_activities_tab
from dimonapp.admin_authorisations_tab import AUTHORISATIONS_TAB, render_authorisations_tab
from dimonapp.admin_compensation_tab import COMPENSATION_TAB, render_compensation_tab
from dimonapp.admin_configuration_tab import CONFIGURATION_TAB, render_configuration_tab
from dimonapp.admin_dashboard_tab import DASHBOARD_TAB, render_dashboard_tab
from dimonapp.admin_fiches_tab import FICHES_TAB, render_fiches_tab
from dimonapp.admin_report_tab import REPORT_TAB, render_report_tab
from dimonapp.admin_workers_tab import WORKERS_TAB, render_workers_tab
from dimonapp.frame import APP_TITLE
from dimonapp.storage import FileStorage

ADMIN_SUBTITLE = 'Administration des travailleurs, des déclarations Dimona et des paiements'


def render_admin_console(engine: sa.Engine, storage: FileStorage, today: date) -> None:
    """Render the title, the subtitle and the eight admin tabs, in the FDS order."""
    st.title(APP_TITLE)
    st.write(ADMIN_SUBTITLE)

    activity_types = load_activity_types(engine=engine)
    activity_labels = {code: activity_types[code].label for code in activity_types}
    compensation_models = {code: activity_types[code].compensation_model for code in activity_types}
    tab_names = [
        DASHBOARD_TAB,
        REPORT_TAB,
        ACTIVITIES_TAB,
        WORKERS_TAB,
        AUTHORISATIONS_TAB,
        COMPENSATION_TAB,
        FICHES_TAB,
        CONFIGURATION_TAB,
    ]
    (
        dashboard_tab,
        report_tab,
        activities_tab,
        workers_tab,
        authorisations_tab,
        compensation_tab,
        fiches_tab,
        configuration_tab,
    ) = st.tabs(tab_names)
    with dashboard_tab:
        render_dashboard_tab(engine=engine, activity_labels=activity_labels, today=today)
    with report_tab:
        render_report_tab(engine=engine, today=today)
    with activities_tab:
        render_activities_tab(engine=engine, activity_labels=activity_labels, today=today)
    with workers_tab:
        render_workers_tab(engine=engine, activity_labels=activity_labels, today=today)
    with authorisations_tab:
        render_authorisations_tab(
            engine=engine,
            storage=storage,
            activity_labels=activity_labels,
            today=today,
        )
    with compensation_tab:
        render_compensation_tab(
            engine=engine,
            activity_labels=activity_labels,
            compensation_models=compensation_models,
            today=today,
        )
    with fiches_tab:
        render_fiches_tab(engine=engine, today=today)
    with configuration_tab:
        render_configuration_tab(engine=engine, today=today)
