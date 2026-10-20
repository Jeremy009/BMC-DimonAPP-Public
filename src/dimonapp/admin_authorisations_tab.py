"""The authorisations tab of the admin console: a worker's documents (R12.2 to R12.9).

The rules live in authorisation_admin.py; this module only draws and passes on.
"""

from datetime import date
from typing import Optional

import sqlalchemy as sa
import streamlit as st

from dimonapp.admin_widgets import render_worker_select
from dimonapp.authorisation_admin import (
    COVER_CHOICES,
    IN_USE_NOTE,
    DocumentForm,
    UploadedDocument,
    add_authorisation,
    build_admin_authorisation_row,
    build_cover_labels,
    build_document_form,
    delete_authorisation,
    find_worker_authorisations,
    is_authorisation_in_use,
    update_authorisation,
)
from dimonapp.database import open_session
from dimonapp.labels import DOCUMENT_TYPE_LABELS
from dimonapp.models import DocumentType, Worker, WorkerType
from dimonapp.results import ActionResult
from dimonapp.storage import FileStorage
from dimonapp.widgets import (
    StoredDocument,
    keep_result,
    read_form_version,
    render_document_download,
    render_document_select,
    reset_form,
    show_kept_result,
)
from dimonapp.worker_tables import build_document_option
from dimonapp.worker_types import WORKER_TYPE_LABELS

AUTHORISATIONS_TAB = 'Autorisations'
NO_DOCUMENT_TEXT = 'Aucun contrat ni qualification enregistré pour ce travailleur.'
EDIT_LABEL = 'Modifier'
DELETE_LABEL = 'Supprimer'
UPLOAD_LABEL = 'Ajouter un document'
UPLOAD_HEADING = 'Ajouter un contrat ou une qualification'
EDIT_HEADING = 'Modifier le document'
FILE_LABEL = 'Fichier (conservé tel quel, non analysé)'
REPLACE_FILE_LABEL = 'Remplacer le fichier (facultatif, conservé tel quel)'
FILE_TYPES = ['pdf', 'jpg', 'jpeg', 'png']
DOCUMENT_TYPE_LABEL = 'Type de document'
WORKER_TYPE_LABEL = 'Type de travailleur du contrat'
COVER_LABEL = 'Activités couvertes'
START_DATE_LABEL = 'Date de début'
END_DATE_LABEL = 'Date de fin (vide = sans fin)'
SAVE_DOCUMENT_LABEL = 'Enregistrer le document'
SAVE_CHANGES_LABEL = 'Enregistrer les modifications'
CLOSE_LABEL = 'Fermer'
DELETE_QUESTION = 'Supprimer définitivement ce document et son fichier ?'
CONFIRM_DELETE_LABEL = 'Confirmer la suppression'
KEEP_LABEL = 'Annuler'

FEEDBACK_KEY = 'authorisations_feedback'
FORM_VERSION_KEY = 'authorisations_form_version'
# Which form is open below the table: (panel, worker id, document id).
PANEL_KEY = 'authorisations_panel'
DATE_FORMAT = 'DD/MM/YYYY'


def open_panel(panel: str, worker_id: int, document_id: Optional[int]) -> None:
    """Open the upload form, the edit form or the delete question below the table."""
    st.session_state[PANEL_KEY] = (panel, worker_id, document_id)


def finish_action(result: ActionResult) -> None:
    """Close the open form after a saved action and show its result on the refreshed page."""
    keep_result(key=FEEDBACK_KEY, result=result)
    st.session_state.pop(PANEL_KEY, None)
    reset_form(key=FORM_VERSION_KEY)
    st.rerun()


def render_close_button(key: str) -> None:
    """Render the button that closes the open form without saving."""
    if st.button(label=CLOSE_LABEL, key=key):
        st.session_state.pop(PANEL_KEY, None)
        st.rerun()


def render_document_fields(
    prefix: str,
    defaults: DocumentForm,
    current_worker_type: WorkerType,
    file_label: str,
    cover_labels: dict[str, str],
    is_in_use: bool = False,
) -> tuple[DocumentForm, Optional[UploadedDocument]]:
    """Render the fields of a contract or qualification; give what was entered (R12.3).

    The worker type is asked for a contract only, and opens on the stored type or else on the
    worker's current type (R12.10). Of a document in use only the end date is open (R12.6).
    """
    uploaded_file = st.file_uploader(
        label=file_label,
        type=FILE_TYPES,
        disabled=is_in_use,
        key=f'{prefix}_file',
    )
    document_types = list(DocumentType)
    left_column, right_column = st.columns(2)
    document_type = left_column.radio(
        label=DOCUMENT_TYPE_LABEL,
        options=document_types,
        index=document_types.index(defaults.document_type),
        format_func=lambda option: DOCUMENT_TYPE_LABELS[option],
        horizontal=True,
        disabled=is_in_use,
        key=f'{prefix}_document_type',
    )
    worker_type = None
    if document_type == DocumentType.CONTRACT:
        worker_types = list(WorkerType)
        default_worker_type = defaults.worker_type or current_worker_type
        worker_type = right_column.selectbox(
            label=WORKER_TYPE_LABEL,
            options=worker_types,
            index=worker_types.index(default_worker_type),
            format_func=lambda option: WORKER_TYPE_LABELS[option],
            disabled=is_in_use,
            key=f'{prefix}_worker_type',
        )
    cover_choices = st.multiselect(
        label=COVER_LABEL,
        options=list(COVER_CHOICES),
        default=defaults.cover_choices,
        format_func=lambda option: cover_labels[option],
        disabled=is_in_use,
        key=f'{prefix}_cover',
    )
    left_column, right_column = st.columns(2)
    start_date = left_column.date_input(
        label=START_DATE_LABEL,
        value=defaults.start_date,
        format=DATE_FORMAT,
        disabled=is_in_use,
        key=f'{prefix}_start_date',
    )
    end_date = right_column.date_input(
        label=END_DATE_LABEL,
        value=defaults.end_date,
        format=DATE_FORMAT,
        key=f'{prefix}_end_date',
    )
    form = DocumentForm(
        document_type=document_type,
        worker_type=worker_type,
        cover_choices=cover_choices,
        start_date=start_date,
        end_date=end_date,
    )
    document = None
    if uploaded_file is not None:
        content = uploaded_file.getvalue()
        document = UploadedDocument(filename=uploaded_file.name, content=content)
    return form, document


def render_upload_form(
    engine: sa.Engine,
    storage: FileStorage,
    worker_id: int,
    worker_type: WorkerType,
    cover_labels: dict[str, str],
    today: date,
) -> None:
    """Render the upload form opened by the upload button (R12.3)."""
    st.markdown(f'#### {UPLOAD_HEADING}')
    version = read_form_version(key=FORM_VERSION_KEY)
    defaults = DocumentForm(
        document_type=DocumentType.CONTRACT,
        worker_type=worker_type,
        cover_choices=[],
        start_date=today,
        end_date=None,
    )
    form, document = render_document_fields(
        prefix=f'upload_{worker_id}_{version}',
        defaults=defaults,
        current_worker_type=worker_type,
        file_label=FILE_LABEL,
        cover_labels=cover_labels,
    )
    with st.container(horizontal=True):
        is_clicked = st.button(label=SAVE_DOCUMENT_LABEL, key='save_document')
        render_close_button(key='close_upload')
    if not is_clicked:
        return

    with open_session(engine=engine) as session:
        result = add_authorisation(
            session=session,
            storage=storage,
            worker_id=worker_id,
            form=form,
            document=document,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    finish_action(result=result)


def render_edit_form(
    engine: sa.Engine,
    storage: FileStorage,
    document_id: int,
    defaults: DocumentForm,
    worker_type: WorkerType,
    cover_labels: dict[str, str],
    is_in_use: bool,
) -> None:
    """Render the form that corrects a document and can replace its file (R12.6)."""
    st.markdown(f'#### {EDIT_HEADING}')
    version = read_form_version(key=FORM_VERSION_KEY)
    form, document = render_document_fields(
        prefix=f'edit_document_{document_id}_{version}',
        defaults=defaults,
        current_worker_type=worker_type,
        file_label=REPLACE_FILE_LABEL,
        cover_labels=cover_labels,
        is_in_use=is_in_use,
    )
    with st.container(horizontal=True):
        is_clicked = st.button(label=SAVE_CHANGES_LABEL, key='save_document_changes')
        render_close_button(key='close_edit')
    if not is_clicked:
        return

    with open_session(engine=engine) as session:
        result = update_authorisation(
            session=session,
            storage=storage,
            authorisation_id=document_id,
            form=form,
            document=document,
        )
    if result.level != 'success':
        st.error(result.message)
        return
    finish_action(result=result)


def render_delete_question(
    engine: sa.Engine,
    storage: FileStorage,
    document_id: int,
    document_label: str,
) -> None:
    """Ask for confirmation, then delete the document and its file (R12.7)."""
    st.warning(f'{DELETE_QUESTION} {document_label}')
    with st.container(horizontal=True):
        is_confirmed = st.button(label=CONFIRM_DELETE_LABEL, type='primary', key='confirm_delete')
        is_kept = st.button(label=KEEP_LABEL, key='keep_document')
    if is_kept:
        st.session_state.pop(PANEL_KEY, None)
        st.rerun()
    if not is_confirmed:
        return

    with open_session(engine=engine) as session:
        result = delete_authorisation(
            session=session,
            storage=storage,
            authorisation_id=document_id,
        )
    finish_action(result=result)


def render_authorisations_tab(
    engine: sa.Engine,
    storage: FileStorage,
    activity_labels: dict[str, str],
    today: date,
) -> None:
    """Render the worker dropdown, the worker's documents and the forms below them (R12.2)."""
    st.header(AUTHORISATIONS_TAB)
    worker_id = render_worker_select(engine=engine, key='authorisations_worker')
    if worker_id is None:
        return
    show_kept_result(key=FEEDBACK_KEY)

    # The documents of the chosen worker
    with open_session(engine=engine) as session:
        worker_type = session.get(Worker, worker_id).worker_type
        authorisations = find_worker_authorisations(session=session, worker_id=worker_id)
        rows = [
            build_admin_authorisation_row(
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
        forms = {
            authorisation.id: build_document_form(authorisation=authorisation)
            for authorisation in authorisations
        }
        in_use_ids = {
            authorisation.id
            for authorisation in authorisations
            if is_authorisation_in_use(session=session, authorisation=authorisation)
        }

    # The table, with the actions on one chosen document
    if not rows:
        st.info(NO_DOCUMENT_TEXT)
    else:
        st.table(data=rows, hide_index=True)
        document_id = render_document_select(
            documents=documents,
            key=f'authorisations_document_{worker_id}',
        )
        with st.container(horizontal=True):
            render_document_download(
                storage=storage,
                document=documents[document_id],
                key='authorisations_download',
            )
            if st.button(label=EDIT_LABEL, key='edit_document'):
                open_panel(panel='edit', worker_id=worker_id, document_id=document_id)
            is_in_use = document_id in in_use_ids
            if st.button(label=DELETE_LABEL, disabled=is_in_use, key='delete_document'):
                open_panel(panel='delete', worker_id=worker_id, document_id=document_id)
        if is_in_use:
            st.caption(IN_USE_NOTE)
    if st.button(label=UPLOAD_LABEL, type='primary', key='upload_document'):
        open_panel(panel='upload', worker_id=worker_id, document_id=None)

    # The form opened by one of the buttons, for this worker only
    panel, panel_worker_id, panel_document_id = st.session_state.get(PANEL_KEY, ('', 0, None))
    if panel_worker_id != worker_id:
        return
    cover_labels = build_cover_labels(activity_labels=activity_labels)
    if panel == 'upload':
        render_upload_form(
            engine=engine,
            storage=storage,
            worker_id=worker_id,
            worker_type=worker_type,
            cover_labels=cover_labels,
            today=today,
        )
        return
    if panel_document_id not in documents:
        return
    if panel == 'edit':
        render_edit_form(
            engine=engine,
            storage=storage,
            document_id=panel_document_id,
            defaults=forms[panel_document_id],
            worker_type=worker_type,
            cover_labels=cover_labels,
            is_in_use=panel_document_id in in_use_ids,
        )
        return
    render_delete_question(
        engine=engine,
        storage=storage,
        document_id=panel_document_id,
        document_label=documents[panel_document_id].label,
    )
