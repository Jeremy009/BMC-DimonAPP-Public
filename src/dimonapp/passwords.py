"""Hashing and verification of local passwords with Argon2 (R4.5, R4.9, R11.4).

Nothing is logged here: a password or its hash never reaches the logs.
"""

import threading
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_HASHER = PasswordHasher()
# Every Argon2 computation takes 64 MiB of memory. Only a few run at once, so a burst of
# sign-in attempts waits instead of exhausting the memory of the one instance.
ARGON2_SLOTS = threading.BoundedSemaphore(value=4)


def hash_password(password: str) -> str:
    """Give the Argon2 hash of a password; the only form in which a password is stored."""
    with ARGON2_SLOTS:
        return PASSWORD_HASHER.hash(password=password)


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    """Tell whether a password matches a stored hash; never true without a readable hash."""
    if password_hash is None:
        return False
    try:
        with ARGON2_SLOTS:
            return PASSWORD_HASHER.verify(hash=password_hash, password=password)
    except (VerificationError, InvalidHashError):
        return False
