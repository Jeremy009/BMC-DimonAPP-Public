"""What the tools, the resource and the prompt of /mcp give back (FDS section 15.5).

These models are the code layer of the privacy rule (FDS 15.1, R20.2 to R20.4): they hold hours,
counts, dates, activity types, worker types, Dimona statuses and activity ids, and have no field
for a name, an identifier, a worker id, an amount in euro or free text. MCP clients read their
schema, so field names and descriptions are in English (R20.19).
"""

from datetime import date, time
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from dimonapp.models import CompensationModel, DimonaStatus, Period, WorkerType

LimitKind = Literal['hours', 'euro']

# What counts as unusual (FDS 15.5): constants of the code, as the 90 % of the limits is.
LONG_ACTIVITY_HOURS = 5
LONG_DAY_HOURS = 8
MAX_DAYS_PER_WEEK = 2


class ActivityTypeTotal(BaseModel):
    """The counted hours and activities of one activity type."""

    activity_type: str = Field(description='Code of the activity type.')
    label: str = Field(description='French label of the activity type, as shown in DimonAPP.')
    hours: float
    n_activities: int


class WorkerTypeTotal(BaseModel):
    """The counted hours and activities of one worker type."""

    worker_type: WorkerType
    hours: float
    n_activities: int


class PeriodSummary(BaseModel):
    """The counted hours and activities of a period, both days included (R20.14)."""

    start: date
    end: date
    hours: float = Field(description='Counted hours: not cancelled and not Dimona-rejected.')
    n_activities: int = Field(description='Number of counted activities.')
    n_workers: int = Field(description='Number of distinct workers with a counted activity.')
    activity_types: list[ActivityTypeTotal]
    worker_types: list[WorkerTypeTotal]
    n_cancelled: int = Field(description='Number of cancelled activities.')
    n_rejected: int = Field(description='Number of not cancelled, Dimona-rejected activities.')
    n_pending: int = Field(description='Number of not cancelled activities with Dimona pending.')


class DayActivity(BaseModel):
    """One counted activity of a day."""

    activity_id: int
    activity_type: str
    label: str
    hours: float
    start_time: Optional[time] = Field(description='Start time, for a flexi-job only.')
    worker_type: WorkerType
    dimona_status: DimonaStatus


class Day(BaseModel):
    """One day of a period with its counted activities; none on a day without any."""

    day: date
    weekday: str
    activities: list[DayActivity]


class DailyActivities(BaseModel):
    """Every day of a period, in order (R20.15)."""

    start: date
    end: date
    days: list[Day]


class PendingDimona(BaseModel):
    """A counted activity whose Dimona declaration is still pending."""

    kind: Literal['pending_dimona'] = 'pending_dimona'
    explanation: str = (
        'The RSZ did not answer the Dimona declaration in time. An admin checks it in DimonAPP.'
    )
    activity_id: int
    activity_date: date
    days_pending: int = Field(description='Days since the activity was declared.')


class RejectedDimona(BaseModel):
    """An activity whose Dimona declaration the RSZ rejected."""

    kind: Literal['rejected_dimona'] = 'rejected_dimona'
    explanation: str = (
        'The RSZ rejected the Dimona declaration, so the activity does not count. An admin '
        'checks why in DimonAPP.'
    )
    activity_id: int
    activity_date: date


class CancelledActivity(BaseModel):
    """A cancelled activity."""

    kind: Literal['cancelled_activity'] = 'cancelled_activity'
    explanation: str = 'The activity was cancelled and does not count.'
    activity_id: int
    activity_date: date


class LongActivity(BaseModel):
    """A counted activity longer than usual."""

    kind: Literal['long_activity'] = 'long_activity'
    explanation: str = f'The activity lasts more than {LONG_ACTIVITY_HOURS} hours.'
    activity_id: int
    activity_date: date
    activity_type: str
    label: str
    hours: float


class LongDay(BaseModel):
    """A day on which one worker's counted activities add up to more than usual."""

    kind: Literal['long_day'] = 'long_day'
    explanation: str = (
        f'The counted activities of one worker on this day add up to more than {LONG_DAY_HOURS} '
        'hours.'
    )
    activity_date: date
    activity_ids: list[int]
    hours: float


class BusyWeek(BaseModel):
    """A week, Monday to Sunday, in which one worker has counted activities on many days."""

    kind: Literal['many_days_in_week'] = 'many_days_in_week'
    explanation: str = (
        f'One worker has counted activities on more than {MAX_DAYS_PER_WEEK} days of this week.'
    )
    week_start: date
    week_end: date
    n_days: int
    dates: list[date]
    activity_ids: list[int]


class ShortFlexiJob(BaseModel):
    """A counted flexi-job activity below the minimum hours per activity of its year."""

    kind: Literal['flexi_job_under_minimum'] = 'flexi_job_under_minimum'
    explanation: str = (
        'The flexi-job activity is shorter than the minimum hours per activity of its year, '
        'which was set or raised after the declaration.'
    )
    activity_id: int
    activity_date: date
    hours: float
    min_hours: float


class YearWithoutLimits(BaseModel):
    """A year with counted activities but without a complete set of limits."""

    kind: Literal['year_without_limits'] = 'year_without_limits'
    explanation: str = (
        'The year has counted activities but not every legal limit is filled in, so DimonAPP '
        'cannot check the limits of that year. An admin completes them in the configuration.'
    )
    year: int
    n_activities: int


class LimitAtThreshold(BaseModel):
    """The number of workers at or above 90 % of one legal limit."""

    kind: Literal['limit_at_threshold'] = 'limit_at_threshold'
    explanation: str = (
        'Workers have reached 90 % or more of this legal limit. The admin dashboard of DimonAPP '
        'shows who.'
    )
    year: int
    period: Period
    worker_type: WorkerType
    limit_kind: LimitKind
    hours_limit: Optional[float] = Field(description='The limit, for an hours limit only.')
    n_workers: int


Anomaly = Annotated[
    Union[
        PendingDimona,
        RejectedDimona,
        CancelledActivity,
        LongActivity,
        LongDay,
        BusyWeek,
        ShortFlexiJob,
        YearWithoutLimits,
        LimitAtThreshold,
    ],
    Field(discriminator='kind'),
]


class Anomalies(BaseModel):
    """Everything in a period that needs a look, each with a fixed explanation (R20.16)."""

    start: date
    end: date
    n_anomalies: int
    anomalies: list[Anomaly]


class MonthReview(BaseModel):
    """The summary of a month, its days without a counted activity and its anomalies (R20.17)."""

    year: int
    month: int
    summary: PeriodSummary
    days_without_activities: list[Day]
    anomalies: Anomalies


class ActivityTypeEntry(BaseModel):
    """One activity type of the catalogue, without any rate."""

    code: str
    label: str = Field(description='French label, as shown in DimonAPP.')
    compensation_model: CompensationModel = Field(description='Paid per hour or at a fixed price.')
    supplement: Optional[str] = Field(description='Code of the supplement it offers, if any.')
    supplement_label: Optional[str]


class ActivityTypeCatalogue(BaseModel):
    """The activity types a worker declares (R20.18)."""

    activity_types: list[ActivityTypeEntry]
