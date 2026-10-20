"""Contracts and qualifications as the admin manages them: upload, edit, delete (FDS 7.3).

Plain functions on a database session and a file storage, so the rules are tested without
Streamlit. Every document is backed by its uploaded file, stored as-is (R12.9). Nothing here
touches an activity: the gate is checked once, at declaration time (R12.8). A document an
activity relied on is the evidence of that work, so it is kept (R12.6, R12.7).
"""

import logging
from datetime import date
from typing import Optional

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dimonapp.clock import BELGIAN_TIME_ZONE
from dimonapp.french import format_date
from dimonapp.models import ACTIVITY_TYPE_CODES, Activity, Authorisation, DocumentType, WorkerType
from dimonapp.results import ActionResult
from dimonapp.storage import FileStorage, build_object_path
from dimonapp.worker_tables import (
    COURSE_ACTIVITY_TYPES,
    COURSE_CLEARANCE_LABEL,
    ROUTE_ACTIVITY_TYPES,
    ROUTE_CLEARANCE_LABEL,
    build_authorisation_row,
)

logger = logging.getLogger(__name__)

# The three choices of covered activities and the activity types each one stores (FDS 7.3).
# The course types are one choice and route setting and route cleaning are one choice: a
# document covers all types of a clearance or none.
PERMANENCE_CHOICE = 'permanence'
COURSE_CHOICE = 'courses'
ROUTE_CHOICE = 'route'
CHOICE_ACTIVITY_TYPES = {
    PERMANENCE_CHOICE: ('permanence',),
    COURSE_CHOICE: COURSE_ACTIVITY_TYPES,
    ROUTE_CHOICE: ROUTE_ACTIVITY_TYPES,
}
COVER_CHOICES = tuple(CHOICE_ACTIVITY_TYPES)

NOT_SAVED_PREFIX = 'Document non enregistré : '
MISSING_FILE_MESSAGE = f'{NOT_SAVED_PREFIX}choisissez le fichier du document.'
EMPTY_FILE_MESSAGE = f'{NOT_SAVED_PREFIX}le fichier est vide.'
MISSING_WORKER_TYPE_MESSAGE = f'{NOT_SAVED_PREFIX}choisissez le type de travailleur du contrat.'
MISSING_ACTIVITIES_MESSAGE = f'{NOT_SAVED_PREFIX}choisissez au moins une activité couverte.'
MISSING_START_DATE_MESSAGE = f'{NOT_SAVED_PREFIX}indiquez la date de début.'
END_BEFORE_START_MESSAGE = (
    f'{NOT_SAVED_PREFIX}la date de fin ne peut pas précéder la date de début.'
)
SAVED_MESSAGE = 'Document enregistré.'
UPDATED_MESSAGE = 'Document modifié.'
DELETED_MESSAGE = 'Document supprimé, avec son fichier.'
IN_USE_NOTE = (
    'Ce document a servi à déclarer des activités : il ne peut plus être supprimé, '
    'et seule sa date de fin peut encore être modifiée.'
)
IN_USE_EDIT_MESSAGE = (
    f'{NOT_SAVED_PREFIX}il a servi à déclarer des activités, seule sa date de fin peut '
    'encore être modifiée.'
)
IN_USE_DELETE_MESSAGE = (
    'Document non supprimé : il a servi à déclarer des activités. Indiquez plutôt une date '
    "de fin, pour qu'il ne couvre plus de nouvelles activités."
)


class DocumentForm(BaseModel):
    """What the admin enters about a contract or qualification (R12.3).

    The worker type is that of a contract; it is ignored for a qualification (R12.10).
    """

    document_type: DocumentType
    worker_type: Optional[WorkerType]
    cover_choices: list[str]
    start_date: Optional[date]
    end_date: Optional[date]


class UploadedDocument(BaseModel):
    """An uploaded file: its original name and its content, untouched."""

    filename: str
    content: bytes


def build_cover_labels(activity_labels: dict[str, str]) -> dict[str, str]:
    """Give the French label of each choice of covered activities."""
    return {
        PERMANENCE_CHOICE: activity_labels[PERMANENCE_CHOICE],
        COURSE_CHOICE: COURSE_CLEARANCE_LABEL,
        ROUTE_CHOICE: ROUTE_CLEARANCE_LABEL,
    }


def expand_cover_choices(cover_choices: list[str]) -> list[str]:
    """Give the activity types to store for the chosen cover, in the order of FDS 5.2."""
    covered_types: set[str] = set()
    for choice in cover_choices:
        covered_types.update(CHOICE_ACTIVITY_TYPES.get(choice, ()))
    return [code for code in ACTIVITY_TYPE_CODES if code in covered_types]


def collapse_activity_types(activity_types: list[str]) -> list[str]:
    """Give the cover choices that match stored activity types, to open the edit form on."""
    cover_choices = []
    for choice in COVER_CHOICES:
        has_choice_type = any(code in CHOICE_ACTIVITY_TYPES[choice] for code in activity_types)
        if has_choice_type:
            cover_choices.append(choice)
    return cover_choices


def build_document_form(authorisation: Authorisation) -> DocumentForm:
    """Give the stored values of a document, to open the edit form on."""
    cover_choices = collapse_activity_types(activity_types=authorisation.activity_types)
    return DocumentForm(
        document_type=authorisation.document_type,
        worker_type=authorisation.worker_type,
        cover_choices=cover_choices,
        start_date=authorisation.start_date,
        end_date=authorisation.end_date,
    )


def find_contract_worker_type(form: DocumentForm) -> Optional[WorkerType]:
    """Give the worker type to store: that of a contract, none for a qualification (R12.10)."""
    if form.document_type != DocumentType.CONTRACT:
        return None
    return form.worker_type


def find_document_form_error(form: DocumentForm) -> Optional[str]:
    """Give the French message of the first problem in a document form, or None."""
    if form.document_type == DocumentType.CONTRACT and form.worker_type is None:
        return MISSING_WORKER_TYPE_MESSAGE
    if not expand_cover_choices(cover_choices=form.cover_choices):
        return MISSING_ACTIVITIES_MESSAGE
    if form.start_date is None:
        return MISSING_START_DATE_MESSAGE
    if form.end_date is not None and form.end_date < form.start_date:
        return END_BEFORE_START_MESSAGE
    return None


def find_file_error(document: Optional[UploadedDocument], is_required: bool) -> Optional[str]:
    """Give the French message of a missing or empty file, or None."""
    if document is None:
        return MISSING_FILE_MESSAGE if is_required else None
    if not document.content:
        return EMPTY_FILE_MESSAGE
    return None


def is_authorisation_in_use(session: Session, authorisation: Authorisation) -> bool:
    """Tell whether an activity relied on a document, so it must be kept (R12.6, R12.7).

    Activities do not record which document the gate used, so every document that covered a
    registered activity counts: same worker, a covered type and date, the contract's worker
    type, and declared once the document was on file. Cancelled and rejected activities count
    too, as they passed the gate.
    """
    conditions = [
        Activity.worker_id == authorisation.worker_id,
        Activity.activity_type.in_(authorisation.activity_types),
        Activity.activity_date >= authorisation.start_date,
        Activity.created_at >= authorisation.uploaded_at,
    ]
    if authorisation.end_date is not None:
        conditions.append(Activity.activity_date <= authorisation.end_date)
    if authorisation.document_type == DocumentType.CONTRACT:
        conditions.append(Activity.worker_type == authorisation.worker_type)
    statement = sa.select(sa.exists().where(*conditions))
    return session.scalar(statement)


def changes_more_than_end_date(
    authorisation: Authorisation,
    form: DocumentForm,
    document: Optional[UploadedDocument],
) -> bool:
    """Tell whether an edit changes anything but the end date, or replaces the file."""
    activity_types = expand_cover_choices(cover_choices=form.cover_choices)
    worker_type = find_contract_worker_type(form=form)
    return (
        document is not None
        or form.document_type != authorisation.document_type
        or worker_type != authorisation.worker_type
        or activity_types != authorisation.activity_types
        or form.start_date != authorisation.start_date
    )


def add_authorisation(
    session: Session,
    storage: FileStorage,
    worker_id: int,
    form: DocumentForm,
    document: Optional[UploadedDocument],
) -> ActionResult:
    """Store an uploaded contract or qualification of a worker (R12.3, R12.9)."""
    error = find_file_error(document=document, is_required=True)
    error = error or find_document_form_error(form=form)
    if error is not None:
        return ActionResult(level='error', message=error)

    # Store the file first, so a record never points at nothing
    object_path = build_object_path(worker_id=worker_id, filename=document.filename)
    storage.save(object_path=object_path, content=document.content)
    authorisation = Authorisation(
        worker_id=worker_id,
        document_type=form.document_type,
        worker_type=find_contract_worker_type(form=form),
        activity_types=expand_cover_choices(cover_choices=form.cover_choices),
        start_date=form.start_date,
        end_date=form.end_date,
        file_path=object_path,
        original_filename=document.filename,
    )
    session.add(authorisation)
    session.flush()
    logger.info(f'Authorisation {authorisation.id} added for worker {worker_id}.')
    return ActionResult(level='success', message=SAVED_MESSAGE)


def update_authorisation(
    session: Session,
    storage: FileStorage,
    authorisation_id: int,
    form: DocumentForm,
    document: Optional[UploadedDocument],
) -> ActionResult:
    """Correct a document and, when a new file is given, replace its file (R12.6).

    Of a document in use only the end date can change.
    """
    authorisation = session.get(Authorisation, authorisation_id)
    if authorisation is None:
        raise ValueError('Unknown authorisation.')
    is_in_use = is_authorisation_in_use(session=session, authorisation=authorisation)
    is_locked_change = changes_more_than_end_date(
        authorisation=authorisation,
        form=form,
        document=document,
    )
    if is_in_use and is_locked_change:
        logger.info(f'Edit of authorisation {authorisation_id} refused: it is in use.')
        return ActionResult(level='error', message=IN_USE_EDIT_MESSAGE)
    error = find_file_error(document=document, is_required=False)
    error = error or find_document_form_error(form=form)
    if error is not None:
        return ActionResult(level='error', message=error)

    # Correct the record
    authorisation.document_type = form.document_type
    authorisation.worker_type = find_contract_worker_type(form=form)
    authorisation.activity_types = expand_cover_choices(cover_choices=form.cover_choices)
    authorisation.start_date = form.start_date
    authorisation.end_date = form.end_date

    # Replace the file: the new one is stored before the old one goes
    if document is not None:
        worker_id = authorisation.worker_id
        old_object_path = authorisation.file_path
        object_path = build_object_path(worker_id=worker_id, filename=document.filename)
        storage.save(object_path=object_path, content=document.content)
        authorisation.file_path = object_path
        authorisation.original_filename = document.filename
        authorisation.uploaded_at = sa.func.now()
        storage.delete(object_path=old_object_path)
    session.flush()
    logger.info(f'Authorisation {authorisation_id} updated.')
    return ActionResult(level='success', message=UPDATED_MESSAGE)


def delete_authorisation(
    session: Session,
    storage: FileStorage,
    authorisation_id: int,
) -> ActionResult:
    """Remove a document and its stored file (R12.7); the view asks for confirmation first.

    A document in use is kept, record and file.
    """
    authorisation = session.get(Authorisation, authorisation_id)
    if authorisation is None:
        raise ValueError('Unknown authorisation.')
    if is_authorisation_in_use(session=session, authorisation=authorisation):
        logger.info(f'Delete of authorisation {authorisation_id} refused: it is in use.')
        return ActionResult(level='error', message=IN_USE_DELETE_MESSAGE)
    object_path = authorisation.file_path
    session.delete(authorisation)
    session.flush()
    storage.delete(object_path=object_path)
    logger.info(f'Authorisation {authorisation_id} deleted.')
    return ActionResult(level='success', message=DELETED_MESSAGE)


def find_worker_authorisations(session: Session, worker_id: int) -> list[Authorisation]:
    """Give the contracts and qualifications of one worker, contracts first (R12.2)."""
    query = (
        sa.select(Authorisation)
        .where(Authorisation.worker_id == worker_id)
        .order_by(Authorisation.document_type, Authorisation.start_date, Authorisation.id)
    )
    return list(session.scalars(query))


def build_admin_authorisation_row(
    authorisation: Authorisation,
    activity_labels: dict[str, str],
    today: date,
) -> dict[str, str]:
    """Build the admin's table row of one document: the worker's row plus the upload date."""
    row = build_authorisation_row(
        authorisation=authorisation,
        activity_labels=activity_labels,
        today=today,
    )
    upload_day = authorisation.uploaded_at.astimezone(tz=BELGIAN_TIME_ZONE).date()
    row['Ajouté le'] = format_date(day=upload_day)
    return row
