"""The last action of every signed-in account, kept in the database (R4.13).

The 30 idle minutes count per account, not per browser tab: a Google sign-in lives in a cookie
for 12 hours, so a new tab must not start them again. Plain functions on a database session.
"""

import datetime
from typing import Literal, Optional

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from dimonapp.models import LastAction

AccountKind = Literal['admin', 'worker']


def read_last_action(
    session: Session,
    account_kind: AccountKind,
    account_id: int,
) -> Optional[datetime.datetime]:
    """Give when an account last acted, or None when it never did."""
    last_action = session.get(LastAction, (account_kind, account_id))
    if last_action is None:
        return None
    return last_action.acted_at


def record_last_action(
    session: Session,
    account_kind: AccountKind,
    account_id: int,
    acted_at: datetime.datetime,
) -> None:
    """Note that an account acted now; one statement, so two tabs at once never collide."""
    statement = postgresql.insert(LastAction).values(
        account_kind=account_kind,
        account_id=account_id,
        acted_at=acted_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[LastAction.account_kind, LastAction.account_id],
        set_={'acted_at': acted_at},
    )
    session.execute(statement)
