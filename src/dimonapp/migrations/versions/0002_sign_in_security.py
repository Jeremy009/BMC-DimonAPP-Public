"""Sign-in security: the lock after wrong passwords and the last action of every account.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the sign_in_failures (R4.14) and last_actions (R4.13) tables."""
    op.create_table(
        'sign_in_failures',
        sa.Column('username_digest', sa.Text(), nullable=False),
        sa.Column('n_failures', sa.Integer(), nullable=False),
        sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('username_digest', name='pk_sign_in_failures'),
    )
    op.create_table(
        'last_actions',
        sa.Column('account_kind', sa.Text(), nullable=False),
        sa.Column('account_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('acted_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('account_kind', 'account_id', name='pk_last_actions'),
        sa.CheckConstraint(
            "account_kind IN ('admin', 'worker')",
            name='ck_last_actions_account_kind_known',
        ),
    )


def downgrade() -> None:
    """Drop the two tables."""
    op.drop_table('last_actions')
    op.drop_table('sign_in_failures')
