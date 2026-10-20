"""Validity of contracts and qualifications (R12.4, R12.5, R12.10)."""

from datetime import date

from dimonapp.models import Authorisation, DocumentType, WorkerType


def covers_activity(authorisation: Authorisation, activity_type: str, activity_date: date) -> bool:
    """Tell whether a document covers an activity type on a date (R12.5).

    Start and end dates are inclusive; no end date means valid indefinitely.
    """
    if activity_type not in authorisation.activity_types:
        return False
    if activity_date < authorisation.start_date:
        return False
    return authorisation.end_date is None or activity_date <= authorisation.end_date


def has_valid_document(
    authorisations: list[Authorisation],
    document_type: DocumentType,
    activity_type: str,
    activity_date: date,
) -> bool:
    """Tell whether at least one document of the given type covers the activity."""
    for authorisation in authorisations:
        if authorisation.document_type != document_type:
            continue
        is_covered = covers_activity(
            authorisation=authorisation,
            activity_type=activity_type,
            activity_date=activity_date,
        )
        if is_covered:
            return True
    return False


def has_valid_contract(
    authorisations: list[Authorisation],
    worker_type: WorkerType,
    activity_type: str,
    activity_date: date,
) -> bool:
    """Tell whether a contract of the worker's type covers the activity (R12.10).

    An article 17 contract is not a flexi-job contract: after a change of type, the contracts
    of the previous type no longer count.
    """
    contracts = [
        authorisation
        for authorisation in authorisations
        if authorisation.worker_type == worker_type
    ]
    return has_valid_document(
        authorisations=contracts,
        document_type=DocumentType.CONTRACT,
        activity_type=activity_type,
        activity_date=activity_date,
    )


def is_expired(authorisation: Authorisation, today: date) -> bool:
    """Tell whether a document ended before today; without end date it never expires (R7.13)."""
    return authorisation.end_date is not None and authorisation.end_date < today
