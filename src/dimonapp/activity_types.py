"""The seeded activity types and supplements, as the views need them (R6.1, R6.9, FDS 5.2)."""

from typing import Optional

import sqlalchemy as sa
from pydantic import BaseModel

from dimonapp.database import open_session
from dimonapp.models import RATE_CODES, ActivityType, CompensationModel


class ActivityTypeChoice(BaseModel):
    """What a form or a table needs to know about an activity type or a supplement."""

    label: str
    compensation_model: CompensationModel
    # The code of the supplement this activity type offers, if any (R6.9).
    supplement: Optional[str] = None


def load_activity_types(engine: sa.Engine) -> dict[str, ActivityTypeChoice]:
    """Read the activity types and supplements, in the order of the compensation sheet.

    A form that declares an activity only offers the codes of ACTIVITY_TYPE_CODES.
    """
    with open_session(engine=engine) as session:
        activity_types = {}
        for code in RATE_CODES:
            activity_type = session.get(ActivityType, code)
            activity_types[code] = ActivityTypeChoice(
                label=activity_type.label,
                compensation_model=activity_type.compensation_model,
                supplement=activity_type.supplement,
            )
    return activity_types
