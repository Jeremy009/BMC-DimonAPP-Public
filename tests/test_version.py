"""The version is defined in one place and follows semantic versioning (R18.8)."""

import re
from importlib import metadata

import dimonapp


def test_r18_8_version_follows_semantic_versioning() -> None:
    """The version reads MAJOR.MINOR.PATCH, with bN or rcN before the release, and is 3.x."""
    assert re.fullmatch(r'\d+\.\d+\.\d+((b|rc)\d+)?', dimonapp.__version__)
    assert dimonapp.__version__.startswith('3.')


def test_r18_8_package_metadata_uses_the_version_constant() -> None:
    """The installed package, and so the Docker image, carries the same version."""
    assert metadata.version('dimonapp') == dimonapp.__version__
