"""The dashboard tab of the admin console: cost of the month, alerts and calendar (R10).

The figures and the wording live in dashboard.py and the calendar in month_calendar.py; this
module only draws and passes on.
"""

from datetime import date

import sqlalchemy as sa
import streamlit as st

from dimonapp.dashboard import (
    RESOLUTION_LABELS,
    Dashboard,
    PendingAlert,
    load_dashboard,
    resolve_pending_activity,
)
from dimonapp.database import open_session
from dimonapp.french import format_amount, format_month_title
from dimonapp.month_calendar import build_calendar_html, find_calendar_entries
from dimonapp.months import find_month_start
from dimonapp.widgets import keep_result, show_kept_result

DASHBOARD_TAB = 'Tableau de bord'
COST_LABEL = 'Coût prévu ce mois'
ACTIVE_WORKERS_LABEL = 'Travailleurs actifs'
PENDING_LABEL = 'Dimona en attente'
LIMIT_ALERTS_LABEL = 'Alertes de limites'
ALERTS_HEADING = 'Alertes'
RESOLVE_AS_LABEL = 'Résoudre comme'
DECLARATION_ID_LABEL = 'ID de déclaration Dimona (si OK)'
RESOLVE_LABEL = 'Résoudre'
FEEDBACK_KEY = 'dashboard_feedback'
CALENDAR_HEADING = 'Activités du mois'
NO_ACCEPTED_ACTIVITY_TEXT = 'Aucune activité acceptée pour ce mois.'


def render_metrics(dashboard: Dashboard) -> None:
    """Render the four figures at the top of the dashboard (R10.2)."""
    cost_column, workers_column, pending_column, limits_column = st.columns(4)
    cost_column.metric(label=COST_LABEL, value=format_amount(amount=dashboard.month_cost))
    workers_column.metric(label=ACTIVE_WORKERS_LABEL, value=str(dashboard.n_active_workers))
    pending_column.metric(label=PENDING_LABEL, value=str(len(dashboard.pending_alerts)))
    limits_column.metric(label=LIMIT_ALERTS_LABEL, value=str(len(dashboard.limit_alerts)))


def render_pending_alert(engine: sa.Engine, alert: PendingAlert) -> None:
    """Render one pending declaration with its resolve action (R10.4, R10.5)."""
    activity_id = alert.activity_id
    st.warning(alert.message)
    resolution_column, id_column, button_column = st.columns(
        [1.2, 1.6, 0.8],
        vertical_alignment='bottom',
    )
    resolution = resolution_column.selectbox(
        label=RESOLVE_AS_LABEL,
        options=list(RESOLUTION_LABELS),
        format_func=lambda option: RESOLUTION_LABELS[option],
        key=f'resolve_as_{activity_id}',
    )
    declaration_id = id_column.text_input(
        label=DECLARATION_ID_LABEL,
        key=f'resolve_id_{activity_id}',
    )
    if not button_column.button(label=RESOLVE_LABEL, key=f'resolve_{activity_id}'):
        return

    with open_session(engine=engine) as session:
        result = resolve_pending_activity(
            session=session,
            activity_id=activity_id,
            resolution=resolution,
            declaration_id=declaration_id,
        )
    keep_result(key=FEEDBACK_KEY, result=result)
    st.rerun()


def render_month_calendar(
    engine: sa.Engine,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the calendar of the current month with the accepted activities only (R10.8)."""
    st.markdown(f'#### {CALENDAR_HEADING}')
    month_start = find_month_start(day=today)
    with open_session(engine=engine) as session:
        entries = find_calendar_entries(session=session, month_start=month_start)
    if not entries:
        st.info(NO_ACCEPTED_ACTIVITY_TEXT)
        return
    calendar_html = build_calendar_html(
        month_start=month_start,
        entries=entries,
        activity_labels=activity_labels,
    )
    st.html(calendar_html)


def render_dashboard_tab(
    engine: sa.Engine,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the admin landing page: the figures of the month, the alerts, the calendar (R10.1).

    The alerts heading only shows when there is an alert.
    """
    st.header(DASHBOARD_TAB)
    st.subheader(format_month_title(year=today.year, month=today.month))
    with open_session(engine=engine) as session:
        dashboard = load_dashboard(session=session, activity_labels=activity_labels, today=today)
    render_metrics(dashboard=dashboard)

    # The outcome of a resolved declaration shows even when it was the last alert
    show_kept_result(key=FEEDBACK_KEY)
    n_alerts = (
        len(dashboard.limit_alerts)
        + len(dashboard.pending_alerts)
        + len(dashboard.missing_limit_alerts)
        + len(dashboard.expiring_contract_alerts)
    )
    if n_alerts > 0:
        st.markdown(f'#### {ALERTS_HEADING}')
    for alert in dashboard.limit_alerts:
        st.error(alert)
    for pending_alert in dashboard.pending_alerts:
        render_pending_alert(engine=engine, alert=pending_alert)
    for alert in dashboard.missing_limit_alerts:
        st.warning(alert)
    for alert in dashboard.expiring_contract_alerts:
        st.info(alert)
    render_month_calendar(engine=engine, activity_labels=activity_labels, today=today)
