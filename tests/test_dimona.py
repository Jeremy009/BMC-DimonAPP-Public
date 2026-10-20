"""The Dimona client interface and its fake (R1.11); the real service is never called."""

from datetime import date

from dimonapp.dimona import DimonaDeclaration, FakeDimonaClient
from dimonapp.models import WorkerType
from factories import VALID_NATIONAL_REGISTER_NUMBER

DECLARATION = DimonaDeclaration(
    national_register_number=VALID_NATIONAL_REGISTER_NUMBER,
    worker_type=WorkerType.ARTICLE_17,
    activity_date=date(2026, 10, 10),
    planned_hours=3,
)


def test_r8_6_fake_accepts_with_a_declaration_id() -> None:
    """An accepting fake gives a declaration ID, a new one for each declaration."""
    client = FakeDimonaClient(outcome='accept')

    first_outcome = client.declare(declaration=DECLARATION)
    second_outcome = client.declare(declaration=DECLARATION)

    assert first_outcome.status == 'accepted'
    assert first_outcome.declaration_id
    assert first_outcome.declaration_id != second_outcome.declaration_id
    assert client.declarations == [DECLARATION, DECLARATION]


def test_r8_7_fake_rejects_with_a_reason() -> None:
    """A rejecting fake gives a reason and no declaration ID."""
    outcome = FakeDimonaClient(outcome='reject').declare(declaration=DECLARATION)

    assert outcome.status == 'rejected'
    assert outcome.declaration_id is None
    assert outcome.message


def test_r8_8_fake_times_out_without_an_answer() -> None:
    """A fake that times out gives no ID and no message."""
    outcome = FakeDimonaClient(outcome='timeout').declare(declaration=DECLARATION)

    assert outcome.status == 'no_answer'
    assert outcome.declaration_id is None
    assert outcome.message is None


def test_r9_4_fake_cancellation_follows_the_configured_outcome() -> None:
    """The fake confirms, refuses or leaves a cancellation unanswered."""
    statuses = {}
    for fake_outcome in ('accept', 'reject', 'timeout'):
        client = FakeDimonaClient(outcome=fake_outcome)
        statuses[fake_outcome] = client.cancel(declaration_id='123').status
        assert client.cancelled_declaration_ids == ['123']

    assert statuses == {'accept': 'confirmed', 'reject': 'refused', 'timeout': 'no_answer'}


def test_r8_9_fake_update_follows_the_configured_outcome() -> None:
    """The fake accepts an update with a new ID, refuses it or leaves it unanswered."""
    statuses = {}
    for fake_outcome in ('accept', 'reject', 'timeout'):
        client = FakeDimonaClient(outcome=fake_outcome)
        statuses[fake_outcome] = client.update_hours(declaration_id='123', planned_hours=5).status
        assert client.hour_updates == [('123', 5)]
        assert client.declarations == []

    assert statuses == {'accept': 'accepted', 'reject': 'rejected', 'timeout': 'no_answer'}


def test_r3_5_declaration_hides_the_national_register_number_when_printed() -> None:
    """The number never shows up when a declaration ends in a log line or an error."""
    assert VALID_NATIONAL_REGISTER_NUMBER not in repr(DECLARATION)
    assert VALID_NATIONAL_REGISTER_NUMBER not in str(DECLARATION)
