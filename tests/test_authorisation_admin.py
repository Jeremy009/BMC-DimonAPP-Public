"""Contracts and qualifications as the admin manages them (R12.2 to R12.9, FDS 7.3)."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp import authorisation_admin
from dimonapp.authorisation_admin import (
    DocumentForm,
    UploadedDocument,
    add_authorisation,
    build_admin_authorisation_row,
    build_cover_labels,
    collapse_activity_types,
    delete_authorisation,
    expand_cover_choices,
    find_worker_authorisations,
    is_authorisation_in_use,
    update_authorisation,
)
from dimonapp.authorisations import has_valid_document
from dimonapp.models import Activity, Authorisation, DimonaStatus, DocumentType, WorkerType
from dimonapp.storage import LocalFileStorage
from dimonapp.worker_tables import COURSE_ACTIVITY_TYPES, ROUTE_ACTIVITY_TYPES
from factories import build_activity, build_worker

TODAY = date(2026, 10, 10)
CONTENT = b'%PDF-1.4 original \x00\xff bytes'
LABELS = {'permanence': 'Permanence', 'courses': 'Cours BMC'}


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    """Give an empty local storage in a temporary folder."""
    return LocalFileStorage(folder=tmp_path / 'storage')


@pytest.fixture
def worker_id(session: Session) -> int:
    """Store a worker and give the id."""
    worker = build_worker()
    session.add(worker)
    session.flush()
    return worker.id


def build_form(
    cover_choices: tuple[str, ...] = ('courses',),
    document_type: DocumentType = DocumentType.CONTRACT,
    start_date: Optional[date] = date(2026, 9, 1),
    end_date: Optional[date] = None,
    worker_type: Optional[WorkerType] = WorkerType.ARTICLE_17,
) -> DocumentForm:
    """Build what an admin enters in the upload form."""
    return DocumentForm(
        document_type=document_type,
        worker_type=worker_type,
        cover_choices=list(cover_choices),
        start_date=start_date,
        end_date=end_date,
    )


def upload(session: Session, storage: LocalFileStorage, worker_id: int) -> Authorisation:
    """Upload a contract for courses and give the stored record."""
    document = UploadedDocument(filename='contrat_2026.pdf', content=CONTENT)
    add_authorisation(
        session=session,
        storage=storage,
        worker_id=worker_id,
        form=build_form(),
        document=document,
    )
    return find_worker_authorisations(session=session, worker_id=worker_id)[0]


def declare(
    session: Session,
    worker_id: int,
    activity_date: date = date(2026, 10, 12),
    activity_type: str = 'courses',
    worker_type: WorkerType = WorkerType.ARTICLE_17,
    dimona_status: DimonaStatus = DimonaStatus.OK,
    is_cancelled: bool = False,
    created_at: Optional[datetime] = None,
) -> int:
    """Register an activity of the worker, by default one the uploaded contract covers."""
    activity = build_activity(
        worker_id=worker_id,
        worker_type=worker_type,
        activity_date=activity_date,
        activity_type=activity_type,
        dimona_status=dimona_status,
        is_cancelled=is_cancelled,
    )
    if created_at is not None:
        activity.created_at = created_at
    session.add(activity)
    session.flush()
    return activity.id


def test_r12_3_upload_stores_the_record_and_the_file(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """The record holds the form and the object path; the file is stored as-is (R3.6, R12.9)."""
    document = UploadedDocument(filename='contrat_2026.pdf', content=CONTENT)
    form = build_form(
        cover_choices=('permanence', 'courses'),
        document_type=DocumentType.QUALIFICATION,
        end_date=date(2027, 8, 31),
    )

    result = add_authorisation(
        session=session,
        storage=storage,
        worker_id=worker_id,
        form=form,
        document=document,
    )

    authorisation = find_worker_authorisations(session=session, worker_id=worker_id)[0]
    assert result.level == 'success'
    assert authorisation.document_type == DocumentType.QUALIFICATION
    assert authorisation.activity_types == ['permanence', *COURSE_ACTIVITY_TYPES]
    assert authorisation.start_date == date(2026, 9, 1)
    assert authorisation.end_date == date(2027, 8, 31)
    assert authorisation.original_filename == 'contrat_2026.pdf'
    assert authorisation.uploaded_at is not None
    assert storage.read(object_path=authorisation.file_path) == CONTENT


@pytest.mark.parametrize(
    ('form', 'document', 'message'),
    [
        (build_form(), None, authorisation_admin.MISSING_FILE_MESSAGE),
        (
            build_form(),
            UploadedDocument(filename='empty.pdf', content=b''),
            authorisation_admin.EMPTY_FILE_MESSAGE,
        ),
        (
            build_form(worker_type=None),
            UploadedDocument(filename='a.pdf', content=CONTENT),
            authorisation_admin.MISSING_WORKER_TYPE_MESSAGE,
        ),
        (
            build_form(cover_choices=()),
            UploadedDocument(filename='a.pdf', content=CONTENT),
            authorisation_admin.MISSING_ACTIVITIES_MESSAGE,
        ),
        (
            build_form(start_date=None),
            UploadedDocument(filename='a.pdf', content=CONTENT),
            authorisation_admin.MISSING_START_DATE_MESSAGE,
        ),
        (
            build_form(end_date=date(2026, 8, 31)),
            UploadedDocument(filename='a.pdf', content=CONTENT),
            authorisation_admin.END_BEFORE_START_MESSAGE,
        ),
    ],
)
def test_r12_3_every_field_but_the_end_date_is_mandatory(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
    form: DocumentForm,
    document: Optional[UploadedDocument],
    message: str,
) -> None:
    """A document without file (R12.9), activity or start date is refused; nothing is stored."""
    result = add_authorisation(
        session=session,
        storage=storage,
        worker_id=worker_id,
        form=form,
        document=document,
    )

    assert result.level == 'error'
    assert result.message == message
    assert find_worker_authorisations(session=session, worker_id=worker_id) == []
    assert not storage.folder.exists()


def test_fds_7_3_route_choice_is_stored_as_the_five_activity_types() -> None:
    """ "Ouverture de voies" is one choice covering route setting and route cleaning."""
    covered_types = expand_cover_choices(cover_choices=['route', 'permanence'])

    assert covered_types == ['permanence', *ROUTE_ACTIVITY_TYPES]
    assert build_cover_labels(activity_labels=LABELS) == {
        'permanence': 'Permanence',
        'courses': 'Cours',
        'route': 'Ouverture de voies',
    }


def test_fds_7_3_course_choice_is_stored_as_the_three_course_types() -> None:
    """ "Cours" is one choice covering the BMC courses and both group course types."""
    covered_types = expand_cover_choices(cover_choices=['courses'])

    assert covered_types == ['courses', 'group_without_instructor', 'group_with_instructor']
    assert collapse_activity_types(activity_types=covered_types) == ['courses']


def test_fds_7_3_stored_route_types_open_as_the_single_choice() -> None:
    """The edit form shows the five stored types as "Ouverture de voies" again."""
    activity_types = ['courses', *ROUTE_ACTIVITY_TYPES]

    assert collapse_activity_types(activity_types=activity_types) == ['courses', 'route']


def test_r12_6_admin_edits_every_field(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """Type, covered activities and dates are corrected; the file stays when none is given."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    object_path = authorisation.file_path
    form = build_form(
        cover_choices=('route',),
        document_type=DocumentType.QUALIFICATION,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )

    result = update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=form,
        document=None,
    )

    assert result.level == 'success'
    assert authorisation.document_type == DocumentType.QUALIFICATION
    assert authorisation.activity_types == list(ROUTE_ACTIVITY_TYPES)
    assert authorisation.start_date == date(2026, 1, 1)
    assert authorisation.end_date == date(2026, 12, 31)
    assert authorisation.file_path == object_path
    assert storage.read(object_path=object_path) == CONTENT


def test_r12_6_admin_replaces_the_file(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """The new file is stored under a new path and the old file is removed."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    old_object_path = authorisation.file_path
    replacement = UploadedDocument(filename='contrat_signe.png', content=b'new file')

    update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=build_form(),
        document=replacement,
    )

    assert authorisation.file_path != old_object_path
    assert authorisation.original_filename == 'contrat_signe.png'
    assert storage.read(object_path=authorisation.file_path) == b'new file'
    assert storage.read(object_path=old_object_path) is None


def test_r12_6_invalid_edit_changes_nothing(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A refused edit leaves the record and its file as they were."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)

    result = update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=build_form(cover_choices=()),
        document=UploadedDocument(filename='b.pdf', content=b'new file'),
    )

    assert result.level == 'error'
    assert authorisation.activity_types == list(COURSE_ACTIVITY_TYPES)
    assert storage.read(object_path=authorisation.file_path) == CONTENT


def test_r12_7_delete_removes_the_record_and_the_file(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """After a delete neither the record nor the stored file exists."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    object_path = authorisation.file_path

    result = delete_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
    )

    assert result.level == 'success'
    assert find_worker_authorisations(session=session, worker_id=worker_id) == []
    assert storage.read(object_path=object_path) is None


def test_r12_8_new_end_date_leaves_registered_activities_alone(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """An activity declared under a document stays as it is once the document ends before it."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    activity_id = declare(session=session, worker_id=worker_id)

    update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=build_form(end_date=date(2026, 9, 30)),
        document=None,
    )

    session.expire_all()
    kept_activity = session.get(Activity, activity_id)
    remaining = find_worker_authorisations(session=session, worker_id=worker_id)
    is_still_covered = has_valid_document(
        authorisations=remaining,
        document_type=DocumentType.CONTRACT,
        activity_type='courses',
        activity_date=date(2026, 10, 12),
    )
    assert kept_activity.is_cancelled is False
    assert kept_activity.activity_type == 'courses'
    assert not is_still_covered


def test_r12_2_table_lists_only_the_documents_of_the_chosen_worker(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """The row has the worker's columns plus the upload date."""
    other_worker = build_worker(national_register_number='00000000097', username='other')
    session.add(other_worker)
    session.flush()
    upload(session=session, storage=storage, worker_id=other_worker.id)
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)

    authorisations = find_worker_authorisations(session=session, worker_id=worker_id)
    row = build_admin_authorisation_row(
        authorisation=authorisation,
        activity_labels=LABELS,
        today=TODAY,
    )

    n_authorisations = session.scalar(sa.select(sa.func.count()).select_from(Authorisation))
    assert authorisations == [authorisation]
    assert n_authorisations == 2
    assert list(row) == ['Type', 'Couvre', 'Début', 'Fin', 'Statut', 'Fichier', 'Ajouté le']
    assert row['Fichier'] == 'contrat_2026.pdf'
    assert len(row['Ajouté le']) == len('10/10/2026')


def test_r12_10_contract_stores_its_worker_type_and_a_qualification_none(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """The worker type of the form is kept for a contract and dropped for a qualification."""
    document = UploadedDocument(filename='document.pdf', content=CONTENT)
    forms = [
        build_form(worker_type=WorkerType.FLEXI_JOB),
        build_form(document_type=DocumentType.QUALIFICATION, worker_type=WorkerType.FLEXI_JOB),
    ]

    for form in forms:
        add_authorisation(
            session=session,
            storage=storage,
            worker_id=worker_id,
            form=form,
            document=document,
        )

    contract, qualification = find_worker_authorisations(session=session, worker_id=worker_id)
    assert contract.worker_type == WorkerType.FLEXI_JOB
    assert qualification.worker_type is None


def test_r12_10_edit_changes_the_worker_type_of_a_contract(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A contract filed under the wrong type is corrected; as a qualification it loses it."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    authorisation_id = authorisation.id

    update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation_id,
        form=build_form(worker_type=WorkerType.VRIJWILLIGER),
        document=None,
    )
    corrected_type = authorisation.worker_type
    update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation_id,
        form=build_form(document_type=DocumentType.QUALIFICATION),
        document=None,
    )

    assert corrected_type == WorkerType.VRIJWILLIGER
    assert authorisation.worker_type is None


def test_r12_7_document_in_use_is_kept_with_its_file(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A contract an activity relied on is refused for deletion; record and file stay."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    declare(session=session, worker_id=worker_id)

    result = delete_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
    )

    assert result.level == 'error'
    assert result.message == (
        'Document non supprimé : il a servi à déclarer des activités. Indiquez plutôt une date '
        "de fin, pour qu'il ne couvre plus de nouvelles activités."
    )
    assert find_worker_authorisations(session=session, worker_id=worker_id) == [authorisation]
    assert storage.read(object_path=authorisation.file_path) == CONTENT


@pytest.mark.parametrize(
    argnames=('dimona_status', 'is_cancelled'),
    argvalues=[
        (DimonaStatus.OK, False),
        (DimonaStatus.OK, True),
        (DimonaStatus.REJECTED, False),
        (DimonaStatus.PENDING, False),
    ],
)
def test_r12_7_every_registered_activity_puts_a_document_in_use(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
    dimona_status: DimonaStatus,
    is_cancelled: bool,
) -> None:
    """Cancelled and rejected activities passed the gate too, so they count."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    declare(
        session=session,
        worker_id=worker_id,
        dimona_status=dimona_status,
        is_cancelled=is_cancelled,
    )

    assert is_authorisation_in_use(session=session, authorisation=authorisation)


@pytest.mark.parametrize(
    argnames=('activity_date', 'activity_type', 'worker_type'),
    argvalues=[
        (date(2026, 8, 31), 'courses', WorkerType.ARTICLE_17),
        (date(2026, 10, 12), 'permanence', WorkerType.ARTICLE_17),
        (date(2026, 10, 12), 'courses', WorkerType.FLEXI_JOB),
    ],
    ids=['before_the_start_date', 'activity_type_not_covered', 'other_worker_type'],
)
def test_r12_7_activity_the_document_did_not_cover_leaves_it_free(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
    activity_date: date,
    activity_type: str,
    worker_type: WorkerType,
) -> None:
    """Only an activity of a covered type, date and, for a contract, worker type counts."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    declare(
        session=session,
        worker_id=worker_id,
        activity_date=activity_date,
        activity_type=activity_type,
        worker_type=worker_type,
    )

    assert not is_authorisation_in_use(session=session, authorisation=authorisation)


def test_r12_7_activity_after_the_end_date_leaves_the_document_free(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A document that ended before the activity did not cover it."""
    document = UploadedDocument(filename='contrat_septembre.pdf', content=CONTENT)
    form = build_form(end_date=date(2026, 9, 30))
    add_authorisation(
        session=session,
        storage=storage,
        worker_id=worker_id,
        form=form,
        document=document,
    )
    authorisation = find_worker_authorisations(session=session, worker_id=worker_id)[0]
    declare(session=session, worker_id=worker_id)

    assert not is_authorisation_in_use(session=session, authorisation=authorisation)


def test_r12_7_activity_declared_before_the_upload_leaves_the_document_free(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """An activity registered before the document was on file cannot have relied on it."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    declare(session=session, worker_id=worker_id, created_at=earlier)

    result = delete_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
    )

    assert result.level == 'success'


def test_r12_7_activity_of_another_worker_leaves_the_document_free(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A document is only in use through its own worker's activities."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    other_worker = build_worker(username='noor', national_register_number='90010112372')
    session.add(other_worker)
    session.flush()
    declare(session=session, worker_id=other_worker.id)

    assert not is_authorisation_in_use(session=session, authorisation=authorisation)


def test_r12_7_qualification_is_in_use_whatever_the_worker_type(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """A qualification belongs to no worker type, so any covered activity counts."""
    document = UploadedDocument(filename='formation.pdf', content=CONTENT)
    form = build_form(document_type=DocumentType.QUALIFICATION, worker_type=None)
    add_authorisation(
        session=session,
        storage=storage,
        worker_id=worker_id,
        form=form,
        document=document,
    )
    authorisation = find_worker_authorisations(session=session, worker_id=worker_id)[0]
    declare(session=session, worker_id=worker_id, worker_type=WorkerType.FLEXI_JOB)

    assert is_authorisation_in_use(session=session, authorisation=authorisation)


def test_r12_6_end_date_of_a_document_in_use_can_change(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
) -> None:
    """Ending a document in use stops new declarations, also before its last activity."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    declare(session=session, worker_id=worker_id)

    result = update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=build_form(end_date=date(2026, 9, 30)),
        document=None,
    )

    assert result.level == 'success'
    assert authorisation.end_date == date(2026, 9, 30)


@pytest.mark.parametrize(
    argnames=('form', 'document'),
    argvalues=[
        (build_form(cover_choices=('courses', 'route')), None),
        (build_form(start_date=date(2026, 10, 1)), None),
        (build_form(document_type=DocumentType.QUALIFICATION, worker_type=None), None),
        (build_form(worker_type=WorkerType.FLEXI_JOB), None),
        (build_form(), UploadedDocument(filename='autre.pdf', content=b'new file')),
    ],
    ids=['covered_activities', 'start_date', 'document_type', 'worker_type', 'file'],
)
def test_r12_6_other_fields_of_a_document_in_use_are_locked(
    session: Session,
    storage: LocalFileStorage,
    worker_id: int,
    form: DocumentForm,
    document: Optional[UploadedDocument],
) -> None:
    """Any change but the end date is refused and changes nothing, file included."""
    authorisation = upload(session=session, storage=storage, worker_id=worker_id)
    object_path = authorisation.file_path
    declare(session=session, worker_id=worker_id)

    result = update_authorisation(
        session=session,
        storage=storage,
        authorisation_id=authorisation.id,
        form=form,
        document=document,
    )

    assert result.level == 'error'
    assert result.message == (
        'Document non enregistré : il a servi à déclarer des activités, seule sa date de fin '
        'peut encore être modifiée.'
    )
    assert authorisation.document_type == DocumentType.CONTRACT
    assert authorisation.worker_type == WorkerType.ARTICLE_17
    assert authorisation.activity_types == list(COURSE_ACTIVITY_TYPES)
    assert authorisation.start_date == date(2026, 9, 1)
    assert authorisation.file_path == object_path
    assert storage.read(object_path=object_path) == CONTENT
