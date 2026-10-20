"""Initial schema: the eight tables, the activity types and the immutability guard.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

WORKER_TYPE = postgresql.ENUM(
    'vrijwilliger',
    'article_17',
    'flexi_job',
    'freelancer',
    name='worker_type',
    create_type=False,
)
AUTH_METHOD = postgresql.ENUM('google', 'local', name='auth_method', create_type=False)
COMPENSATION_MODEL = postgresql.ENUM(
    'hourly',
    'fixed',
    name='compensation_model',
    create_type=False,
)
DIMONA_STATUS = postgresql.ENUM(
    'not_applicable',
    'ok',
    'rejected',
    'pending',
    name='dimona_status',
    create_type=False,
)
DOCUMENT_TYPE = postgresql.ENUM(
    'contract',
    'qualification',
    name='document_type',
    create_type=False,
)
ENUM_TYPES = (WORKER_TYPE, AUTH_METHOD, COMPENSATION_MODEL, DIMONA_STATUS, DOCUMENT_TYPE)

MONEY = sa.Numeric(precision=10, scale=2)
HOURS = sa.Numeric(precision=6, scale=2)

# The two supplements and the nine activity types of FDS 5.2 with their French labels (R6.1,
# R6.3, R6.8, R6.9). The supplements come first: the activity types refer to them.
ACTIVITY_TYPES = [
    {
        'code': 'group_travel',
        'label': 'Déplacement groupe',
        'compensation_model': 'fixed',
        'description_required': False,
        'supplement': None,
    },
    {
        'code': 'rope_supplement',
        'label': 'Supplément corde 9 à 14',
        'compensation_model': 'fixed',
        'description_required': False,
        'supplement': None,
    },
    {
        'code': 'permanence',
        'label': 'Permanence',
        'compensation_model': 'fixed',
        'description_required': False,
        'supplement': None,
    },
    {
        'code': 'courses',
        'label': 'Cours BMC',
        'compensation_model': 'hourly',
        'description_required': False,
        'supplement': None,
    },
    {
        'code': 'group_without_instructor',
        'label': 'Cours groupe sans mono',
        'compensation_model': 'hourly',
        'description_required': False,
        'supplement': 'group_travel',
    },
    {
        'code': 'group_with_instructor',
        'label': 'Cours groupe avec mono',
        'compensation_model': 'hourly',
        'description_required': False,
        'supplement': 'group_travel',
    },
    {
        'code': 'route_setting_easy',
        'label': 'Ouverture 4A - 5C',
        'compensation_model': 'fixed',
        'description_required': True,
        'supplement': 'rope_supplement',
    },
    {
        'code': 'route_setting_medium',
        'label': 'Ouverture 6A - 6C',
        'compensation_model': 'fixed',
        'description_required': True,
        'supplement': 'rope_supplement',
    },
    {
        'code': 'route_setting_hard',
        'label': 'Ouverture 7A et plus',
        'compensation_model': 'fixed',
        'description_required': True,
        'supplement': 'rope_supplement',
    },
    {
        'code': 'route_cleaning_easy',
        'label': 'Démontage facile',
        'compensation_model': 'fixed',
        'description_required': False,
        'supplement': None,
    },
    {
        'code': 'route_cleaning_hard',
        'label': 'Démontage difficile (cordes 9 à 14)',
        'compensation_model': 'fixed',
        'description_required': False,
        'supplement': None,
    },
]

# Activities are immutable (R17.1): no delete, and an update may only touch the cancellation
# marker or, while the declaration is pending, the Dimona fields.
CREATE_GUARD_FUNCTION = """
CREATE FUNCTION refuse_activity_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'An activity cannot be deleted.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (
        NEW.id, NEW.worker_id, NEW.worker_type, NEW.activity_date, NEW.activity_type,
        NEW.description, NEW.duration_hours, NEW.start_time, NEW.compensation_model,
        NEW.rate_applied, NEW.supplement_amount, NEW.compensation_amount, NEW.created_at
    ) IS DISTINCT FROM (
        OLD.id, OLD.worker_id, OLD.worker_type, OLD.activity_date, OLD.activity_type,
        OLD.description, OLD.duration_hours, OLD.start_time, OLD.compensation_model,
        OLD.rate_applied, OLD.supplement_amount, OLD.compensation_amount, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Only the cancellation marker and pending Dimona fields can change.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.dimona_status <> 'pending' AND (
        NEW.dimona_status, NEW.dimona_declaration_id, NEW.dimona_message
    ) IS DISTINCT FROM (
        OLD.dimona_status, OLD.dimona_declaration_id, OLD.dimona_message
    ) THEN
        RAISE EXCEPTION 'Dimona fields can only change while the declaration is pending.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

CREATE_GUARD_TRIGGER = """
CREATE TRIGGER activities_refuse_change
BEFORE UPDATE OR DELETE ON activities
FOR EACH ROW EXECUTE FUNCTION refuse_activity_change()
"""


def upgrade() -> None:
    """Create the enum types, the tables, the activity types and the immutability guard."""
    # Create the enum types shared by several tables
    connection = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind=connection, checkfirst=True)

    # Create the tables
    op.create_table(
        'workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.Text(), nullable=False),
        sa.Column('last_name', sa.Text(), nullable=False),
        sa.Column('national_register_number', sa.Text(), nullable=False),
        sa.Column('iban', sa.Text(), nullable=False),
        sa.Column('worker_type', WORKER_TYPE, nullable=False),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('auth_method', AUTH_METHOD, nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('street', sa.Text(), nullable=False),
        sa.Column('postal_code', sa.Text(), nullable=False),
        sa.Column('city', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_workers'),
        sa.UniqueConstraint('national_register_number', name='uq_workers_national_register_number'),
        sa.UniqueConstraint('username', name='uq_workers_username'),
        sa.UniqueConstraint('email', name='uq_workers_email'),
    )
    op.create_table(
        'admins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_admins'),
        sa.UniqueConstraint('email', name='uq_admins_email'),
    )
    activity_types = op.create_table(
        'activity_types',
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('compensation_model', COMPENSATION_MODEL, nullable=False),
        sa.Column('description_required', sa.Boolean(), nullable=False),
        sa.Column('supplement', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('code', name='pk_activity_types'),
        sa.ForeignKeyConstraint(
            ['supplement'],
            ['activity_types.code'],
            name='fk_activity_types_supplement_activity_types',
        ),
    )
    op.create_table(
        'compensation_rates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('activity_type', sa.Text(), nullable=False),
        sa.Column('amount', MONEY, nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_compensation_rates'),
        sa.ForeignKeyConstraint(
            ['worker_id'],
            ['workers.id'],
            name='fk_compensation_rates_worker_id_workers',
        ),
        sa.ForeignKeyConstraint(
            ['activity_type'],
            ['activity_types.code'],
            name='fk_compensation_rates_activity_type_activity_types',
        ),
        sa.UniqueConstraint(
            'worker_id',
            'activity_type',
            'valid_from',
            name='uq_compensation_rates_version',
        ),
        sa.CheckConstraint('amount >= 0', name='ck_compensation_rates_amount_not_negative'),
    )
    op.create_table(
        'activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('worker_type', WORKER_TYPE, nullable=False),
        sa.Column('activity_date', sa.Date(), nullable=False),
        sa.Column('activity_type', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_hours', HOURS, nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('compensation_model', COMPENSATION_MODEL, nullable=False),
        sa.Column('rate_applied', MONEY, nullable=False),
        sa.Column('supplement_amount', MONEY, server_default=sa.text('0'), nullable=False),
        sa.Column('compensation_amount', MONEY, nullable=False),
        sa.Column('dimona_status', DIMONA_STATUS, nullable=False),
        sa.Column('dimona_declaration_id', sa.Text(), nullable=True),
        sa.Column('dimona_message', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('is_cancelled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_activities'),
        sa.ForeignKeyConstraint(
            ['worker_id'],
            ['workers.id'],
            name='fk_activities_worker_id_workers',
        ),
        sa.ForeignKeyConstraint(
            ['activity_type'],
            ['activity_types.code'],
            name='fk_activities_activity_type_activity_types',
        ),
        sa.CheckConstraint('duration_hours > 0', name='ck_activities_duration_positive'),
        sa.CheckConstraint(
            'supplement_amount >= 0',
            name='ck_activities_supplement_not_negative',
        ),
    )
    op.create_index(
        'ix_activities_worker_id_activity_date',
        'activities',
        ['worker_id', 'activity_date'],
    )
    op.create_table(
        'yearly_limits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('worker_type', WORKER_TYPE, nullable=False),
        sa.Column('period', sa.Text(), nullable=False),
        sa.Column('hours_limit', HOURS, nullable=True),
        sa.Column('euro_limit', MONEY, nullable=True),
        sa.Column('min_hours_per_activity', HOURS, nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_yearly_limits'),
        sa.UniqueConstraint('year', 'worker_type', 'period', name='uq_yearly_limits_period'),
        sa.CheckConstraint(
            "period IN ('Q1', 'Q2', 'Q3', 'Q4', 'YEAR')",
            name='ck_yearly_limits_period_known',
        ),
    )
    op.create_table(
        'authorisations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('document_type', DOCUMENT_TYPE, nullable=False),
        sa.Column('worker_type', WORKER_TYPE, nullable=True),
        sa.Column('activity_types', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column(
            'uploaded_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name='pk_authorisations'),
        sa.ForeignKeyConstraint(
            ['worker_id'],
            ['workers.id'],
            name='fk_authorisations_worker_id_workers',
        ),
        sa.CheckConstraint(
            'cardinality(activity_types) > 0',
            name='ck_authorisations_covers_an_activity',
        ),
        sa.CheckConstraint(
            "(document_type = 'contract') = (worker_type IS NOT NULL)",
            name='ck_authorisations_contract_has_worker_type',
        ),
        sa.CheckConstraint(
            'end_date IS NULL OR end_date >= start_date',
            name='ck_authorisations_end_after_start',
        ),
    )
    op.create_table(
        'organisation_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_number', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('contact_details', sa.Text(), nullable=False),
        sa.Column('postal_code', sa.Text(), nullable=False),
        sa.Column('city', sa.Text(), nullable=False),
        sa.Column('phone', sa.Text(), nullable=False),
        sa.Column('contact_person', sa.Text(), nullable=False),
        sa.Column('iban', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_organisation_config'),
    )

    # Seed the activity types
    op.bulk_insert(activity_types, ACTIVITY_TYPES)

    # Guard the immutability of activities
    op.execute(CREATE_GUARD_FUNCTION)
    op.execute(CREATE_GUARD_TRIGGER)


def downgrade() -> None:
    """Drop everything the upgrade created."""
    op.drop_table('organisation_config')
    op.drop_table('authorisations')
    op.drop_table('yearly_limits')
    op.drop_table('activities')
    op.execute('DROP FUNCTION refuse_activity_change()')
    op.drop_table('compensation_rates')
    op.drop_table('activity_types')
    op.drop_table('admins')
    op.drop_table('workers')
    connection = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.drop(bind=connection, checkfirst=True)
