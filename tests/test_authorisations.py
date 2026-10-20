"""Validity of contracts and qualifications (R12.4, R12.5, R12.10)."""

from datetime import date

from dimonapp.authorisations import covers_activity, has_valid_contract, has_valid_document
from dimonapp.models import DocumentType, WorkerType
from factories import build_authorisation


def is_covered_on(activity_date: date, activity_type: str = 'courses') -> bool:
    """Check a contract for two course types running from 01/01/2026 to 30/06/2026."""
    authorisation = build_authorisation(
        activity_types=('courses', 'group_with_instructor'),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
    )
    return covers_activity(
        authorisation=authorisation,
        activity_type=activity_type,
        activity_date=activity_date,
    )


def test_r12_5_start_and_end_dates_are_inclusive() -> None:
    """The first and the last day are covered, the days just outside are not."""
    assert is_covered_on(activity_date=date(2026, 1, 1))
    assert is_covered_on(activity_date=date(2026, 6, 30))
    assert not is_covered_on(activity_date=date(2025, 12, 31))
    assert not is_covered_on(activity_date=date(2026, 7, 1))


def test_r12_5_no_end_date_is_valid_indefinitely() -> None:
    """A document without an end date still covers an activity years later."""
    authorisation = build_authorisation(start_date=date(2026, 1, 1), end_date=None)

    is_covered = covers_activity(
        authorisation=authorisation,
        activity_type='courses',
        activity_date=date(2040, 1, 1),
    )

    assert is_covered


def test_r12_5_activity_type_outside_the_covered_list_is_not_covered() -> None:
    """A valid date is not enough: the activity type must be listed."""
    assert not is_covered_on(activity_date=date(2026, 3, 1), activity_type='permanence')


def test_r12_4_one_document_covers_several_activity_types() -> None:
    """Both listed activity types are covered by the same document."""
    assert is_covered_on(activity_date=date(2026, 3, 1), activity_type='courses')
    assert is_covered_on(activity_date=date(2026, 3, 1), activity_type='group_with_instructor')


def test_r12_5_contract_does_not_count_as_qualification() -> None:
    """Each document type is checked on its own."""
    authorisations = [build_authorisation(document_type=DocumentType.CONTRACT)]

    has_contract = has_valid_document(
        authorisations=authorisations,
        document_type=DocumentType.CONTRACT,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )
    has_qualification = has_valid_document(
        authorisations=authorisations,
        document_type=DocumentType.QUALIFICATION,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )

    assert has_contract
    assert not has_qualification


def test_r12_5_expired_document_is_ignored_when_another_one_is_valid() -> None:
    """One valid document among expired ones is enough."""
    expired = build_authorisation(start_date=date(2025, 1, 1), end_date=date(2025, 12, 31))
    current = build_authorisation(start_date=date(2026, 1, 1))

    has_contract = has_valid_document(
        authorisations=[expired, current],
        document_type=DocumentType.CONTRACT,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )

    assert has_contract


def test_r12_10_contract_counts_only_for_its_own_worker_type() -> None:
    """An article 17 contract is not a flexi-job contract."""
    authorisations = [build_authorisation(worker_type=WorkerType.ARTICLE_17)]

    has_own_contract = has_valid_contract(
        authorisations=authorisations,
        worker_type=WorkerType.ARTICLE_17,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )
    has_flexi_contract = has_valid_contract(
        authorisations=authorisations,
        worker_type=WorkerType.FLEXI_JOB,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )

    assert has_own_contract
    assert not has_flexi_contract


def test_r12_10_contract_of_the_right_type_still_needs_the_activity_and_the_date() -> None:
    """The worker type comes on top of the covered activities and the dates (R12.5)."""
    contract = build_authorisation(
        activity_types=('courses',),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        worker_type=WorkerType.FLEXI_JOB,
    )

    covers_other_activity = has_valid_contract(
        authorisations=[contract],
        worker_type=WorkerType.FLEXI_JOB,
        activity_type='permanence',
        activity_date=date(2026, 3, 1),
    )
    covers_later_date = has_valid_contract(
        authorisations=[contract],
        worker_type=WorkerType.FLEXI_JOB,
        activity_type='courses',
        activity_date=date(2026, 7, 1),
    )

    assert not covers_other_activity
    assert not covers_later_date


def test_r12_10_qualification_has_no_worker_type_and_is_never_a_contract() -> None:
    """A qualification belongs to activities only."""
    qualification = build_authorisation(document_type=DocumentType.QUALIFICATION)

    has_contract = has_valid_contract(
        authorisations=[qualification],
        worker_type=WorkerType.ARTICLE_17,
        activity_type='courses',
        activity_date=date(2026, 3, 1),
    )

    assert qualification.worker_type is None
    assert not has_contract
