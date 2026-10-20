"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from typing import Optional

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Optional[str] = ${repr(down_revision)}
branch_labels: Optional[str] = ${repr(branch_labels)}
depends_on: Optional[str] = ${repr(depends_on)}


def upgrade() -> None:
    """Apply this schema change."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revert this schema change."""
    ${downgrades if downgrades else "pass"}
