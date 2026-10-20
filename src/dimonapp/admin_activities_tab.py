"""The activities tab of the admin console: every worker's activities of a month (R19.1).

Read only: the same columns as the worker's monthly overview, with the worker's name, in an
interactive table the admin can sort, search and download.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.activities import find_all_month_activities
from dimonapp.database import open_session
from dimonapp.models import Activity, Worker
from dimonapp.widgets import render_month_navigation
from dimonapp.worker_tables import build_activity_row
from dimonapp.worker_types import build_worker_name

ACTIVITIES_TAB = 'Activités'
WORKER_COLUMN = 'Travailleur'
NO_ACTIVITY_TEXT = 'Aucune activité pour ce mois.'


def build_admin_activity_row(
    activity: Activity,
    worker: Worker,
    activity_labels: dict[str, str],
) -> dict[str, str]:
    """Build the row of one activity: the worker's monthly overview row with the worker's name."""
    row = build_activity_row(
        activity=activity,
        activity_labels=activity_labels,
        with_cancelled=True,
    )
    worker_name = build_worker_name(worker=worker)
    activity_date = row.pop('Date')
    return {'Date': activity_date, WORKER_COLUMN: worker_name, **row}


def render_activities_tab(engine: sa.Engine, activity_labels: dict[str, str], today: date) -> None:
    """Render the month arrows and every activity of the month, cancelled ones included."""
    st.header(ACTIVITIES_TAB)
    month_start = render_month_navigation(key='activities', today=today)
    with open_session(engine=engine) as session:
        activities = find_all_month_activities(session=session, month_start=month_start)
        rows = [
            build_admin_activity_row(
                activity=activity,
                worker=worker,
                activity_labels=activity_labels,
            )
            for activity, worker in activities
        ]
    if not rows:
        st.info(NO_ACTIVITY_TEXT)
        return
    # The one interactive table of the interface: its English menus are accepted (R18.1)
    st.dataframe(data=rows, hide_index=True)
