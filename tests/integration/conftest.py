"""Fixtures of the integration tests, which call real services with the developer's settings."""

import pytest


@pytest.fixture(autouse=True)
def isolated_environment() -> None:
    """Keep the developer's own settings: these tests need the real .env and environment.

    Replaces the fixture of the same name in tests/conftest.py, which hides them.
    """
