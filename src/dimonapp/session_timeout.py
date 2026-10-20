"""How long a sign-in lasts (R4.13).

A plain function, so the rule is tested without Streamlit. Streamlit only runs the page when the
person acts, so an expired sign-in is noticed at the next click.
"""

import datetime
from typing import Optional

SESSION_MAX_AGE = datetime.timedelta(hours=12)
IDLE_TIMEOUT = datetime.timedelta(minutes=30)


def is_session_expired(
    signed_in_at: datetime.datetime,
    last_action_at: Optional[datetime.datetime],
    now: datetime.datetime,
) -> bool:
    """Tell whether a sign-in is over: older than 12 hours, or idle for more than 30 minutes.

    The idle time runs from the last action of the account, in any browser tab or device, or
    from the sign-in when that came later: signing in is an action too.
    """
    is_too_old = now - signed_in_at > SESSION_MAX_AGE
    idle_since = signed_in_at if last_action_at is None else max(signed_in_at, last_action_at)
    is_idle = now - idle_since > IDLE_TIMEOUT
    return is_too_old or is_idle
