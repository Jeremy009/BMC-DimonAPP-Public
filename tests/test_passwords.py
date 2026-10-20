"""Argon2 hashing of local passwords (R4.5, R4.9, R11.4)."""

from dimonapp.passwords import hash_password, verify_password

PASSWORD = 'correct horse battery staple'


def test_r4_9_password_is_hashed_with_argon2() -> None:
    """The stored value is an Argon2id hash."""
    password_hash = hash_password(password=PASSWORD)

    assert password_hash.startswith('$argon2id$')


def test_r4_5_hash_never_contains_the_password() -> None:
    """The plain password cannot be read from what is stored."""
    password_hash = hash_password(password=PASSWORD)

    assert PASSWORD not in password_hash


def test_r4_5_same_password_gives_different_hashes() -> None:
    """Each hash has its own salt, so equal passwords are not recognisable in the database."""
    first_hash = hash_password(password=PASSWORD)
    second_hash = hash_password(password=PASSWORD)

    assert first_hash != second_hash


def test_r11_4_password_set_by_the_admin_verifies() -> None:
    """The password an admin sets is accepted afterwards."""
    password_hash = hash_password(password=PASSWORD)

    assert verify_password(password=PASSWORD, password_hash=password_hash)


def test_r4_9_wrong_password_is_refused() -> None:
    """Another password does not match the hash."""
    password_hash = hash_password(password=PASSWORD)

    assert not verify_password(password='wrong password', password_hash=password_hash)


def test_r4_5_missing_hash_is_refused() -> None:
    """An account without a password hash accepts no password."""
    assert not verify_password(password=PASSWORD, password_hash=None)


def test_r4_5_plain_text_in_the_hash_column_is_refused() -> None:
    """A value that is not an Argon2 hash never verifies, not even against itself."""
    assert not verify_password(password=PASSWORD, password_hash=PASSWORD)
