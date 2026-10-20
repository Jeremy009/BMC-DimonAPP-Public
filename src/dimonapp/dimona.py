"""Small interface around the Dimona service of the RSZ/ONSS, with a fake implementation.

The real implementation lives in dimonapp.rsz_dimona.

The rest of the application only knows DimonaClient. What is stored and shown always follows
the outcome a client returns, never an assumption (FDS section 8, key rule). The client itself
is responsible for giving up after DIMONA_TIMEOUT_SECONDS and answering 'no_answer'.
"""

import logging
import uuid
from datetime import date, time
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, Field

from dimonapp.models import WorkerType

logger = logging.getLogger(__name__)

# Without an answer after this long, a declaration is pending and a cancellation fails (R8.8).
DIMONA_TIMEOUT_SECONDS = 120

FakeDimonaOutcome = Literal['accept', 'reject', 'timeout']
FAKE_REJECTION_REASON = 'déclaration refusée par le faux service Dimona'


class DimonaDeclaration(BaseModel):
    """What the Dimona service needs to know about one activity."""

    # Never shown when the declaration is printed or logged (R3.5).
    national_register_number: str = Field(repr=False)
    worker_type: WorkerType
    activity_date: date
    # Whole hours: the RSZ takes nothing else, and the submission gate refuses parts (R7.5).
    planned_hours: int
    # Flexi-job only: the RSZ wants the start and end time instead of the planned hours (R7.15).
    start_time: Optional[time] = None


class DeclarationOutcome(BaseModel):
    """The answer of the Dimona service to a declaration, or its absence."""

    status: Literal['accepted', 'rejected', 'no_answer']
    declaration_id: Optional[str] = None
    message: Optional[str] = None


class CancellationOutcome(BaseModel):
    """The answer of the Dimona service to a cancellation, or its absence."""

    status: Literal['confirmed', 'refused', 'no_answer']
    message: Optional[str] = None


class DimonaClient(Protocol):
    """What the application asks of the Dimona service."""

    def declare(self, declaration: DimonaDeclaration) -> DeclarationOutcome:
        """Send a declaration and wait for the answer."""
        ...

    def update_hours(self, declaration_id: str, planned_hours: int) -> DeclarationOutcome:
        """Change the planned hours of the period of an accepted declaration and wait."""
        ...

    def cancel(self, declaration_id: str) -> CancellationOutcome:
        """Cancel an accepted declaration and wait for the answer."""
        ...


class FakeDimonaClient:
    """A Dimona service that never leaves the machine, for tests and local work.

    It answers every call the same, configurable way: accept, reject or time out. It does not
    really wait when it times out, and it remembers what it was asked.
    """

    def __init__(self, outcome: FakeDimonaOutcome = 'accept') -> None:
        """Set how the fake service answers."""
        self.outcome = outcome
        self.declarations: list[DimonaDeclaration] = []
        self.hour_updates: list[tuple[str, int]] = []
        self.cancelled_declaration_ids: list[str] = []

    def declare(self, declaration: DimonaDeclaration) -> DeclarationOutcome:
        """Answer a declaration the configured way."""
        self.declarations.append(declaration)
        logger.info(f'Fake Dimona declaration: {self.outcome}.')
        return self.answer_declaration()

    def answer_declaration(self) -> DeclarationOutcome:
        """Give the configured answer to a declaration or an update."""
        if self.outcome == 'reject':
            return DeclarationOutcome(status='rejected', message=FAKE_REJECTION_REASON)
        if self.outcome == 'timeout':
            return DeclarationOutcome(status='no_answer')
        declaration_id = f'FAKE-{uuid.uuid4().hex[:12]}'
        return DeclarationOutcome(status='accepted', declaration_id=declaration_id)

    def update_hours(self, declaration_id: str, planned_hours: int) -> DeclarationOutcome:
        """Answer a change of planned hours the configured way."""
        self.hour_updates.append((declaration_id, planned_hours))
        logger.info(f'Fake Dimona update: {self.outcome}.')
        return self.answer_declaration()

    def cancel(self, declaration_id: str) -> CancellationOutcome:
        """Answer a cancellation the configured way."""
        self.cancelled_declaration_ids.append(declaration_id)
        logger.info(f'Fake Dimona cancellation: {self.outcome}.')
        if self.outcome == 'reject':
            return CancellationOutcome(status='refused', message=FAKE_REJECTION_REASON)
        if self.outcome == 'timeout':
            return CancellationOutcome(status='no_answer')
        return CancellationOutcome(status='confirmed')
