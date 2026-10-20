"""The first admin of an environment (R4.11).

Admins sign in with Google only and there is no screen to add one, so a new environment would
have nobody who can sign in. At start-up, the address of FIRST_ADMIN_EMAIL becomes the admin
when the admins table is still empty.
"""

import logging

import sqlalchemy as sa
from sqlalchemy.orm import Session

from dimonapp.authentication import normalise_email
from dimonapp.models import Admin

logger = logging.getLogger(__name__)


def add_first_admin(session: Session, email: str) -> bool:
    """Add the first admin when there is none yet; tell whether one was added.

    With an admin already in the table nothing changes, whatever the address: the setting
    can stay in place and never adds a second admin or brings back a removed one.
    """
    n_admins = session.scalar(sa.select(sa.func.count()).select_from(Admin))
    if n_admins:
        return False
    admin = Admin(email=normalise_email(email=email), is_active=True)
    session.add(admin)
    session.flush()
    logger.info(f'First admin added (admin {admin.id}).')
    return True
