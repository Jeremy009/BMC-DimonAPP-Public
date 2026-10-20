"""Small Streamlit building blocks shared by the worker view and the admin console."""

from datetime import date
from typing import Optional

import streamlit as st
from pydantic import BaseModel
from streamlit.delta_generator import DeltaGenerator

from dimonapp.french import format_month_title
from dimonapp.months import find_month_start, shift_month
from dimonapp.results import ActionResult
from dimonapp.storage import FileStorage

DOCUMENT_SELECT_LABEL = 'Document'
DOWNLOAD_LABEL = 'Télécharger le document'
FILE_NOT_FOUND_TEXT = 'Le fichier de ce document est introuvable dans le stockage.'
PREVIOUS_LABEL = ':material/arrow_back:'
NEXT_LABEL = ':material/arrow_forward:'
PREVIOUS_HELP = 'Mois précédent'
NEXT_HELP = 'Mois suivant'
# The keys of the action buttons that were clicked and whose action has not run yet.
ACTION_REQUESTS_KEY = 'action_requests'


class StoredDocument(BaseModel):
    """What is needed to offer a stored document for download."""

    label: str
    object_path: str
    filename: str


def show_message(level: str, message: str) -> None:
    """Show a result as a success, an error or a warning (R17.4)."""
    if level == 'success':
        st.success(message)
        return
    if level == 'error':
        st.error(message)
        return
    st.warning(message)


def keep_result(key: str, result: ActionResult) -> None:
    """Keep the result of an action over the rerun that refreshes the page."""
    st.session_state[key] = result


def show_kept_result(key: str) -> None:
    """Show the result kept by keep_result, once."""
    result = st.session_state.pop(key, None)
    if result is not None:
        show_message(level=result.level, message=result.message)


def request_action(key: str, token: int) -> None:
    """Note that the action of a button was asked for, unless the click is an outdated one.

    Called by Streamlit on click, before the run. The token of a button drawn before the last
    accepted click is out of date: such a click left the browser before the disabled button
    arrived, and must not repeat the action.
    """
    token_key = f'{key}_token'
    if token != st.session_state.get(token_key, 0):
        return
    st.session_state[token_key] = token + 1
    requested_keys = st.session_state.get(ACTION_REQUESTS_KEY, set())
    st.session_state[ACTION_REQUESTS_KEY] = {*requested_keys, key}


def forget_action_requests() -> None:
    """Drop every action that was asked for and has not run yet.

    Called whenever nobody is signed in: a click that reached the page after the sign-in ended
    never acts, not even for whoever signs in next in the same browser tab (R4.13).
    """
    st.session_state.pop(ACTION_REQUESTS_KEY, None)


def render_action_button(label: str, key: str) -> bool:
    """Render a primary button that is disabled while its action runs; tell whether to run it.

    The page stays clickable while a run waits on the Dimona service, and every click queues
    one more run, so the action would be repeated as often as the button was clicked. The
    caller runs the action at once, keeps its result before any other Streamlit call (the point
    where a queued run takes over) and then calls st.rerun() to enable the button again.
    """
    requested_keys = st.session_state.get(ACTION_REQUESTS_KEY, set())
    if key not in requested_keys:
        token = st.session_state.get(f'{key}_token', 0)
        arguments = {'key': key, 'token': token}
        st.button(label=label, type='primary', key=key, on_click=request_action, kwargs=arguments)
        return False

    # A disabled copy under its own key, so a late click on the first one keeps its old token
    st.button(label=label, type='primary', key=f'{key}_busy', disabled=True)
    # Cleared only now: a run stopped while drawing the button still runs the action next time
    st.session_state[ACTION_REQUESTS_KEY] = requested_keys - {key}
    return True


def build_grid_cells(n_cells: int, n_columns: int) -> list[DeltaGenerator]:
    """Give the cells of a grid of fields, filled left to right, then top to bottom.

    Streamlit fills one column from top to bottom before the next, and the tab key follows
    that order. A new row of columns for every line keeps the tab key moving across first.
    """
    cells = []
    while len(cells) < n_cells:
        cells.extend(st.columns(n_columns))
    return cells[:n_cells]


def read_form_version(key: str) -> int:
    """Give the version of a form; it is part of the keys of the form's fields."""
    return st.session_state.get(key, 0)


def reset_form(key: str) -> None:
    """Empty a form after it was saved, by giving its fields new keys."""
    st.session_state[key] = read_form_version(key=key) + 1


def render_document_select(documents: dict[int, StoredDocument], key: str) -> Optional[int]:
    """Render the list to pick one document from; give the id of the chosen one."""
    return st.selectbox(
        label=DOCUMENT_SELECT_LABEL,
        options=list(documents),
        format_func=lambda document_id: documents[document_id].label,
        key=key,
    )


def render_document_download(storage: FileStorage, document: StoredDocument, key: str) -> None:
    """Render the button that downloads the original file of a document (R7.13, R12.2).

    The file is served through the application, under its original name; the storage itself
    is never reachable from outside.
    """
    content = storage.read(object_path=document.object_path)
    if content is None:
        st.button(label=DOWNLOAD_LABEL, key=key, disabled=True, help=FILE_NOT_FOUND_TEXT)
        return
    st.download_button(
        label=DOWNLOAD_LABEL,
        data=content,
        file_name=document.filename,
        key=key,
    )


def render_month_navigation(key: str, today: date) -> date:
    """Render the previous and next arrows around the month name; give the selected month.

    Each tab keeps its own month and opens on the current one (R7.8, R7.11, R13.1).
    """
    state_key = f'{key}_month'
    month_start = st.session_state.get(state_key, find_month_start(day=today))
    previous_column, title_column, next_column = st.columns([0.6, 3, 0.6])
    previous_key = f'{key}_previous'
    next_key = f'{key}_next'
    if previous_column.button(label=PREVIOUS_LABEL, key=previous_key, help=PREVIOUS_HELP):
        month_start = shift_month(month_start=month_start, n_months=-1)
    # The next arrow sits against the right edge, as the previous one against the left
    next_container = next_column.container(horizontal_alignment='right')
    if next_container.button(label=NEXT_LABEL, key=next_key, help=NEXT_HELP):
        month_start = shift_month(month_start=month_start, n_months=1)
    st.session_state[state_key] = month_start
    month_name = format_month_title(year=month_start.year, month=month_start.month)
    title_column.markdown(f'#### {month_name}', text_alignment='center')
    return month_start
