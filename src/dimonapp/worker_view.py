"""The worker view: four tabs on the worker's own data (R7.1, R7.2).

Every query takes the id of the signed-in worker, so a worker never sees someone else's data.
The rules live in submission.py and cancellation.py; this module only draws and passes on.
"""

from datetime import date, time, timedelta
from decimal import Decimal

import sqlalchemy as sa
import streamlit as st

from dimonapp import worker_messages
from dimonapp.activities import find_month_activities, sum_counted_activities
from dimonapp.activity_types import ActivityTypeChoice, load_activity_types
from dimonapp.authorisations import is_expired
from dimonapp.cancellation import cancel_activity
from dimonapp.database import open_session
from dimonapp.dimona import DimonaClient
from dimonapp.frame import APP_TITLE
from dimonapp.french import format_amount, format_hours
from dimonapp.models import ACTIVITY_TYPE_CODES, Authorisation, Worker, WorkerType
from dimonapp.results import ActionResult
from dimonapp.storage import FileStorage
from dimonapp.submission import ActivityForm, find_latest_date, submit_activity
from dimonapp.widgets import (
    StoredDocument,
    keep_result,
    render_action_button,
    render_document_download,
    render_document_select,
    render_month_navigation,
    show_kept_result,
)
from dimonapp.worker_tables import (
    ROUTE_ACTIVITY_TYPES,
    build_activity_row,
    build_authorisation_row,
    build_cancel_option,
    build_document_option,
)

WORKER_SUBTITLE = 'Déclarez et suivez vos activités'
CREATE_TAB = 'Déclarer une activité'
CANCEL_TAB = 'Annuler une activité'
OVERVIEW_TAB = 'Aperçu mensuel'
AUTHORISATIONS_TAB = 'Mes documents'

DATE_LABEL = 'Date'
DATE_HELP = "Aujourd'hui ou plus tard, au maximum 3 mois à l'avance."
DATE_KEY = 'create_date'
ACTIVITY_TYPE_LABEL = "Type d'activité"
DURATION_LABEL = 'Durée (heures)'
DESCRIPTION_LABEL = 'Description'
# What the tick box of each supplement tells the worker (R6.9, R6.11).
SUPPLEMENT_HELP = {
    'group_travel': 'Déplacement pour un groupe ou une école, au maximum une fois par jour.',
    'rope_supplement': 'Pour une voie ouverte sur les cordes 9 à 14.',
}
CONFIRM_LABEL = "Confirmer l'activité"
SUBMITTING_TEXT = "Enregistrement de l'activité et attente de la réponse Dimona…"
CREATE_FEEDBACK_KEY = 'create_feedback'

NOTHING_TO_CANCEL_TEXT = 'Aucune activité à annuler pour ce mois.'
CANCEL_SELECT_LABEL = 'Activité à annuler'
CANCEL_SELECT_PLACEHOLDER = 'Choisissez une activité'
CANCEL_SELECT_KEY = 'cancel_choice'
CANCEL_BUTTON_LABEL = 'Annuler cette activité'
CANCELLING_TEXT = "Annulation de l'activité et attente de la réponse Dimona…"
CANCEL_FEEDBACK_KEY = 'cancel_feedback'

NO_ACTIVITY_TEXT = 'Aucune activité pour ce mois.'
TOTAL_HOURS_LABEL = 'Total des heures'
TOTAL_AMOUNT_LABEL = 'Rémunération totale'

NO_AUTHORISATION_TEXT = 'Aucun contrat ni qualification enregistré.'

START_TIME_LABEL = 'Heure de début'
START_TIME_HELP = "Heure pile ou demi-heure. L'heure de fin est calculée avec la durée."
DEFAULT_START_TIME = time(hour=9)
START_TIME_STEP = timedelta(minutes=30)
DEFAULT_DURATION_HOURS = 1
MAX_DURATION_HOURS = 24


def render_create_tab(
    engine: sa.Engine,
    dimona_client: DimonaClient,
    worker_id: int,
    worker_type: WorkerType,
    activity_types: dict[str, ActivityTypeChoice],
    today: date,
) -> None:
    """Render the create form and run the submission gate on confirm (R7.3, R8.1).

    A flexi-jobber also enters a start time, and gets the calendar the RSZ accepts (R7.15, R7.16).
    """
    st.header(CREATE_TAB)
    is_flexi_job = worker_type == WorkerType.FLEXI_JOB
    start_time = None
    # One row of columns per line, so the tab key moves left to right, then down
    first_row = st.columns(2)
    second_row = st.columns(2)
    # The key keeps the picked date when the limits move at midnight. The picker opens on
    # today; afterwards a date that falls outside the limits is emptied instead of becoming
    # today, so a confirm never declares a day the worker did not pick.
    default_date = None if DATE_KEY in st.session_state else today
    activity_date = first_row[0].date_input(
        label=DATE_LABEL,
        value=default_date,
        min_value=today,
        max_value=find_latest_date(today=today, worker_type=worker_type),
        format='DD/MM/YYYY',
        help=DATE_HELP,
        key=DATE_KEY,
    )
    if is_flexi_job:
        start_time = first_row[1].time_input(
            label=START_TIME_LABEL,
            value=DEFAULT_START_TIME,
            step=START_TIME_STEP,
            help=START_TIME_HELP,
        )
    activity_type = second_row[0].selectbox(
        label=ACTIVITY_TYPE_LABEL,
        options=list(ACTIVITY_TYPE_CODES),
        format_func=lambda code: activity_types[code].label,
    )
    # Next to the date, unless a flexi-jobber's start time takes that place
    duration_column = second_row[1] if is_flexi_job else first_row[1]
    duration = duration_column.number_input(
        label=DURATION_LABEL,
        value=DEFAULT_DURATION_HOURS,
        min_value=1,
        max_value=MAX_DURATION_HOURS,
        step=1,
    )
    # Only route setting and démontage have a description, on a row of its own (R7.3)
    description = ''
    if activity_type in ROUTE_ACTIVITY_TYPES:
        description = st.text_input(label=DESCRIPTION_LABEL)
    # The tick box of the supplement, only for an activity type that offers one (R7.3)
    with_supplement = False
    supplement = activity_types[activity_type].supplement
    if supplement is not None:
        with_supplement = st.checkbox(
            label=activity_types[supplement].label,
            help=SUPPLEMENT_HELP[supplement],
            key=f'supplement_{supplement}',
        )
    compensation_model = activity_types[activity_type].compensation_model
    model_caption = worker_messages.build_model_caption(
        activity_type=activity_type,
        compensation_model=compensation_model,
    )
    st.caption(model_caption)
    is_requested = render_action_button(label=CONFIRM_LABEL, key='confirm_activity')
    show_kept_result(key=CREATE_FEEDBACK_KEY)
    if not is_requested:
        return

    duration_hours = Decimal(str(duration)) if duration is not None else None
    form = ActivityForm(
        activity_date=activity_date,
        activity_type=activity_type,
        duration_hours=duration_hours,
        description=description,
        start_time=start_time,
        with_supplement=with_supplement,
    )
    with st.spinner(text=SUBMITTING_TEXT):
        with open_session(engine=engine) as session:
            result = submit_activity(
                session=session,
                dimona_client=dimona_client,
                worker_id=worker_id,
                form=form,
                today=today,
            )
        # Kept before the spinner closes, where a click queued meanwhile takes over the run
        keep_result(key=CREATE_FEEDBACK_KEY, result=result)
    st.rerun()


def render_cancel_tab(
    engine: sa.Engine,
    dimona_client: DimonaClient,
    worker_id: int,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the month's non-cancelled activities and cancel the chosen one (R7.8, R7.9)."""
    st.header(CANCEL_TAB)
    month_start = render_month_navigation(key='cancel', today=today)

    # The worker's own non-cancelled activities of the month
    with open_session(engine=engine) as session:
        month_activities = find_month_activities(
            session=session,
            worker_id=worker_id,
            month_start=month_start,
        )
        activities = [activity for activity in month_activities if not activity.is_cancelled]
        rows = [
            build_activity_row(
                activity=activity,
                activity_labels=activity_labels,
                with_cancelled=False,
            )
            for activity in activities
        ]
        options = {
            activity.id: build_cancel_option(activity=activity, activity_labels=activity_labels)
            for activity in activities
        }

    # The result of the last cancellation, kept over the rerun that refreshes the list
    if not rows:
        st.info(NOTHING_TO_CANCEL_TEXT)
    else:
        st.table(data=rows, hide_index=True)
    show_kept_result(key=CANCEL_FEEDBACK_KEY)
    if not rows:
        return

    # Nothing is chosen in advance, and the key keeps the choice when the list changes. A
    # choice that leaves the list, cancelled meanwhile on another device, is emptied instead
    # of moving to another activity.
    activity_id = st.selectbox(
        label=CANCEL_SELECT_LABEL,
        options=list(options),
        index=None,
        format_func=lambda option: options[option],
        placeholder=CANCEL_SELECT_PLACEHOLDER,
        key=CANCEL_SELECT_KEY,
    )
    if not render_action_button(label=CANCEL_BUTTON_LABEL, key='cancel_activity'):
        return
    if activity_id is None:
        message = worker_messages.NO_ACTIVITY_CHOSEN_MESSAGE
        result = ActionResult(level='warning', message=message)
        keep_result(key=CANCEL_FEEDBACK_KEY, result=result)
        st.rerun()

    with st.spinner(text=CANCELLING_TEXT):
        with open_session(engine=engine) as session:
            result = cancel_activity(
                session=session,
                dimona_client=dimona_client,
                worker_id=worker_id,
                activity_id=activity_id,
            )
        # Kept before the spinner closes, where a click queued meanwhile takes over the run
        keep_result(key=CANCEL_FEEDBACK_KEY, result=result)
    st.rerun()


def render_overview_tab(
    engine: sa.Engine,
    worker_id: int,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the month's activities and the totals of the counted ones (R7.10, R7.12)."""
    st.header(OVERVIEW_TAB)
    month_start = render_month_navigation(key='overview', today=today)

    with open_session(engine=engine) as session:
        activities = find_month_activities(
            session=session,
            worker_id=worker_id,
            month_start=month_start,
        )
        rows = [
            build_activity_row(
                activity=activity,
                activity_labels=activity_labels,
                with_cancelled=True,
            )
            for activity in activities
        ]
        totals = sum_counted_activities(activities=activities)

    if not rows:
        st.info(NO_ACTIVITY_TEXT)
    else:
        st.table(data=rows, hide_index=True)
    hours_column, amount_column, _ = st.columns([1, 1, 2])
    hours_column.metric(label=TOTAL_HOURS_LABEL, value=format_hours(hours=totals.hours))
    amount_column.metric(label=TOTAL_AMOUNT_LABEL, value=format_amount(amount=totals.amount))


def render_authorisations_tab(
    engine: sa.Engine,
    storage: FileStorage,
    worker_id: int,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the worker's contracts and qualifications, read-only, with download (R7.13)."""
    st.header(AUTHORISATIONS_TAB)

    # Documents still running first, expired ones last
    with open_session(engine=engine) as session:
        query = (
            sa.select(Authorisation)
            .where(Authorisation.worker_id == worker_id)
            .order_by(Authorisation.document_type, Authorisation.start_date, Authorisation.id)
        )
        authorisations = list(session.scalars(query))
        authorisations.sort(key=lambda item: is_expired(authorisation=item, today=today))
        rows = [
            build_authorisation_row(
                authorisation=authorisation,
                activity_labels=activity_labels,
                today=today,
            )
            for authorisation in authorisations
        ]
        documents = {
            authorisation.id: StoredDocument(
                label=build_document_option(
                    authorisation=authorisation,
                    activity_labels=activity_labels,
                ),
                object_path=authorisation.file_path,
                filename=authorisation.original_filename,
            )
            for authorisation in authorisations
        }

    if not rows:
        st.info(NO_AUTHORISATION_TEXT)
        return
    st.table(data=rows, hide_index=True)

    # The original file of one chosen document, served through the application
    document_id = render_document_select(documents=documents, key='own_document')
    render_document_download(
        storage=storage,
        document=documents[document_id],
        key='own_document_download',
    )


def render_worker_view(
    engine: sa.Engine,
    dimona_client: DimonaClient,
    storage: FileStorage,
    worker_id: int,
    today: date,
) -> None:
    """Render the title, the subtitle and the four worker tabs (R7.1, R18.2)."""
    st.title(APP_TITLE)
    st.write(WORKER_SUBTITLE)

    activity_types = load_activity_types(engine=engine)
    with open_session(engine=engine) as session:
        worker_type = session.get(Worker, worker_id).worker_type
    activity_labels = {code: activity_types[code].label for code in activity_types}
    tab_names = [CREATE_TAB, CANCEL_TAB, OVERVIEW_TAB, AUTHORISATIONS_TAB]
    create_tab, cancel_tab, overview_tab, authorisations_tab = st.tabs(tab_names)
    with create_tab:
        render_create_tab(
            engine=engine,
            dimona_client=dimona_client,
            worker_id=worker_id,
            worker_type=worker_type,
            activity_types=activity_types,
            today=today,
        )
    with cancel_tab:
        render_cancel_tab(
            engine=engine,
            dimona_client=dimona_client,
            worker_id=worker_id,
            activity_labels=activity_labels,
            today=today,
        )
    with overview_tab:
        render_overview_tab(
            engine=engine,
            worker_id=worker_id,
            activity_labels=activity_labels,
            today=today,
        )
    with authorisations_tab:
        render_authorisations_tab(
            engine=engine,
            storage=storage,
            worker_id=worker_id,
            activity_labels=activity_labels,
            today=today,
        )
