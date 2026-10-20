"""Enums and ORM models for the ten tables of FDS section 11 (R1.9)."""

import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class WorkerType(enum.StrEnum):
    """The four worker types (R5.1)."""

    VRIJWILLIGER = 'vrijwilliger'
    ARTICLE_17 = 'article_17'
    FLEXI_JOB = 'flexi_job'
    FREELANCER = 'freelancer'


class AuthMethod(enum.StrEnum):
    """How a worker signs in."""

    GOOGLE = 'google'
    LOCAL = 'local'


class CompensationModel(enum.StrEnum):
    """The two compensation models (R6.2)."""

    HOURLY = 'hourly'
    FIXED = 'fixed'


class DimonaStatus(enum.StrEnum):
    """Outcome of the Dimona declaration of an activity."""

    NOT_APPLICABLE = 'not_applicable'
    OK = 'ok'
    REJECTED = 'rejected'
    PENDING = 'pending'


class DocumentType(enum.StrEnum):
    """The two kinds of authorisation documents."""

    CONTRACT = 'contract'
    QUALIFICATION = 'qualification'


class Period(enum.StrEnum):
    """Period a yearly limit applies to: one quarter or the whole calendar year."""

    Q1 = 'Q1'
    Q2 = 'Q2'
    Q3 = 'Q3'
    Q4 = 'Q4'
    YEAR = 'YEAR'


# The nine activity types a worker declares, in the order of FDS 5.2 (R6.1); the table itself
# has no sort column.
ACTIVITY_TYPE_CODES = (
    'permanence',
    'courses',
    'group_without_instructor',
    'group_with_instructor',
    'route_setting_easy',
    'route_setting_medium',
    'route_setting_hard',
    'route_cleaning_easy',
    'route_cleaning_hard',
)
# The two supplements: never declared alone, added to an activity of a type that offers one (R6.9).
SUPPLEMENT_CODES = ('group_travel', 'rope_supplement')
# Everything a worker has a rate for, in the order of the compensation sheet: each supplement
# follows the activity types that offer it (R6.6).
RATE_CODES = (
    'permanence',
    'courses',
    'group_without_instructor',
    'group_with_instructor',
    'group_travel',
    'route_setting_easy',
    'route_setting_medium',
    'route_setting_hard',
    'rope_supplement',
    'route_cleaning_easy',
    'route_cleaning_hard',
)

# Fixed constraint names, so the migrations and the models always agree.
NAMING_CONVENTION = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}


def list_enum_values(enum_class: type[enum.Enum]) -> list[str]:
    """Give the values of an enum, so the database stores 'article_17' and not 'ARTICLE_17'."""
    return [member.value for member in enum_class]


WORKER_TYPE = sa.Enum(WorkerType, name='worker_type', values_callable=list_enum_values)
AUTH_METHOD = sa.Enum(AuthMethod, name='auth_method', values_callable=list_enum_values)
COMPENSATION_MODEL = sa.Enum(
    CompensationModel,
    name='compensation_model',
    values_callable=list_enum_values,
)
DIMONA_STATUS = sa.Enum(DimonaStatus, name='dimona_status', values_callable=list_enum_values)
DOCUMENT_TYPE = sa.Enum(DocumentType, name='document_type', values_callable=list_enum_values)

# Exact decimals: euro amounts to the cent, hours to the hundredth.
MONEY = sa.Numeric(precision=10, scale=2)
HOURS = sa.Numeric(precision=6, scale=2)


class Base(DeclarativeBase):
    """Base of every ORM model."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {str: sa.Text, datetime: sa.DateTime(timezone=True)}


class Worker(Base):
    """A worker account; the only table holding national register numbers and IBANs (R3.5)."""

    __tablename__ = 'workers'

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str]
    last_name: Mapped[str]
    national_register_number: Mapped[str] = mapped_column(unique=True)
    iban: Mapped[str]
    worker_type: Mapped[WorkerType] = mapped_column(WORKER_TYPE)
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    auth_method: Mapped[AuthMethod] = mapped_column(AUTH_METHOD)
    password_hash: Mapped[Optional[str]]
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())
    # Postal address in Belgium, printed on the fiche 281.27 (R11.10).
    street: Mapped[str]
    postal_code: Mapped[str]
    city: Mapped[str]


class Admin(Base):
    """An admin account, separate from the worker accounts (R4.1)."""

    __tablename__ = 'admins'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())


class ActivityType(Base):
    """One of the seeded activity types or supplements (R6.1, R6.8, R6.9).

    An activity type that offers a supplement names it; a supplement is a row of its own, so it
    has a label and a rate per worker like an activity type.
    """

    __tablename__ = 'activity_types'

    code: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str]
    compensation_model: Mapped[CompensationModel] = mapped_column(COMPENSATION_MODEL)
    description_required: Mapped[bool]
    supplement: Mapped[Optional[str]] = mapped_column(sa.ForeignKey('activity_types.code'))


class CompensationRate(Base):
    """One version of a worker's rate, valid from a date (R6.6, R6.7).

    The rate of an activity type or of a supplement.
    """

    __tablename__ = 'compensation_rates'
    __table_args__ = (
        sa.UniqueConstraint(
            'worker_id',
            'activity_type',
            'valid_from',
            name='uq_compensation_rates_version',
        ),
        sa.CheckConstraint('amount >= 0', name='amount_not_negative'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(sa.ForeignKey('workers.id'))
    activity_type: Mapped[str] = mapped_column(sa.ForeignKey('activity_types.code'))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    valid_from: Mapped[date]


class Activity(Base):
    """A declared activity; immutable apart from cancellation and pending Dimona fields (R17.1).

    The worker type, model, rate, supplement and amount are copies taken at declaration
    (R17.3). The compensation amount includes the supplement (R6.10).
    """

    __tablename__ = 'activities'
    __table_args__ = (
        sa.CheckConstraint('duration_hours > 0', name='duration_positive'),
        sa.CheckConstraint('supplement_amount >= 0', name='supplement_not_negative'),
        sa.Index('ix_activities_worker_id_activity_date', 'worker_id', 'activity_date'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(sa.ForeignKey('workers.id'))
    worker_type: Mapped[WorkerType] = mapped_column(WORKER_TYPE)
    activity_date: Mapped[date]
    activity_type: Mapped[str] = mapped_column(sa.ForeignKey('activity_types.code'))
    description: Mapped[Optional[str]]
    duration_hours: Mapped[Decimal] = mapped_column(HOURS)
    # Flexi-job activities only: the RSZ wants a start and an end time (R7.15).
    start_time: Mapped[Optional[time]]
    compensation_model: Mapped[CompensationModel] = mapped_column(COMPENSATION_MODEL)
    rate_applied: Mapped[Decimal] = mapped_column(MONEY)
    supplement_amount: Mapped[Decimal] = mapped_column(MONEY, server_default=sa.text('0'))
    compensation_amount: Mapped[Decimal] = mapped_column(MONEY)
    dimona_status: Mapped[DimonaStatus] = mapped_column(DIMONA_STATUS)
    dimona_declaration_id: Mapped[Optional[str]]
    dimona_message: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    is_cancelled: Mapped[bool] = mapped_column(server_default=sa.false())


class YearlyLimit(Base):
    """The legal limits of one worker type for one period of one year (R15.2)."""

    __tablename__ = 'yearly_limits'
    __table_args__ = (
        sa.UniqueConstraint('year', 'worker_type', 'period', name='uq_yearly_limits_period'),
        sa.CheckConstraint("period IN ('Q1', 'Q2', 'Q3', 'Q4', 'YEAR')", name='period_known'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int]
    worker_type: Mapped[WorkerType] = mapped_column(WORKER_TYPE)
    period: Mapped[str]
    hours_limit: Mapped[Optional[Decimal]] = mapped_column(HOURS)
    euro_limit: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    min_hours_per_activity: Mapped[Optional[Decimal]] = mapped_column(HOURS)


class Authorisation(Base):
    """A contract or qualification covering one or more activity types (R12.4).

    A contract belongs to one worker type, a qualification to none (R12.10).
    """

    __tablename__ = 'authorisations'
    __table_args__ = (
        sa.CheckConstraint('cardinality(activity_types) > 0', name='covers_an_activity'),
        sa.CheckConstraint(
            "(document_type = 'contract') = (worker_type IS NOT NULL)",
            name='contract_has_worker_type',
        ),
        sa.CheckConstraint('end_date IS NULL OR end_date >= start_date', name='end_after_start'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(sa.ForeignKey('workers.id'))
    document_type: Mapped[DocumentType] = mapped_column(DOCUMENT_TYPE)
    worker_type: Mapped[Optional[WorkerType]] = mapped_column(WORKER_TYPE)
    activity_types: Mapped[list[str]] = mapped_column(postgresql.ARRAY(sa.Text))
    start_date: Mapped[date]
    end_date: Mapped[Optional[date]]
    file_path: Mapped[str]
    original_filename: Mapped[str]
    uploaded_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())


class OrganisationConfig(Base):
    """BMC's own details, used for the fiche 281.27, Belcotax and the payment file (R15.4).

    A single row; address is the street and number, contact_details the contact e-mail address.
    """

    __tablename__ = 'organisation_config'

    id: Mapped[int] = mapped_column(primary_key=True)
    company_number: Mapped[str]
    name: Mapped[str]
    address: Mapped[str]
    contact_details: Mapped[str]
    postal_code: Mapped[str]
    city: Mapped[str]
    phone: Mapped[str]
    contact_person: Mapped[str]
    iban: Mapped[str]


class SignInFailure(Base):
    """Wrong passwords in a row for one username typed in the local form (R4.14).

    The username is kept as a digest only: people sometimes type their password in that field.
    """

    __tablename__ = 'sign_in_failures'

    username_digest: Mapped[str] = mapped_column(primary_key=True)
    n_failures: Mapped[int]
    last_failed_at: Mapped[datetime]


class LastAction(Base):
    """When a signed-in account last acted, in any browser tab or device (R4.13)."""

    __tablename__ = 'last_actions'
    __table_args__ = (
        sa.CheckConstraint("account_kind IN ('admin', 'worker')", name='account_kind_known'),
    )

    account_kind: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    acted_at: Mapped[datetime]
