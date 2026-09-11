"""
Version information for aragora package.

This module provides semantic versioning information following PEP 440.
Import VERSION_INFO for programmatic access to version components.
"""

from __future__ import annotations

# Version components
VERSION_MAJOR = 2
VERSION_MINOR = 10
VERSION_PATCH = 0
VERSION_SUFFIX = ""  # e.g., "a1", "b2", "rc1", or "" for final

# Construct version string
VERSION_INFO: tuple[int, int, int] = (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)
__version__ = ".".join(str(component) for component in VERSION_INFO)
if VERSION_SUFFIX:
    __version__ += VERSION_SUFFIX

# Release date (ISO 8601 format) — set when the v2.10.0 tag is pushed
RELEASE_DATE = "2026-09-04"

# Package metadata
PACKAGE_NAME = "aragora"
AUTHOR = "Agora Contributors"
LICENSE = "MIT"
REPOSITORY = "https://github.com/synaptent/aragora"


def get_version() -> str:
    """Return the current version string."""
    return __version__


def get_version_tuple() -> tuple[int, int, int]:
    """Return version as a tuple of (major, minor, patch)."""
    return VERSION_INFO


def get_version_info() -> dict[str, object]:
    """Return a dict of all version metadata."""
    return {
        "version": __version__,
        "major": VERSION_MAJOR,
        "minor": VERSION_MINOR,
        "patch": VERSION_PATCH,
        "suffix": VERSION_SUFFIX,
        "release_date": RELEASE_DATE,
        "package": PACKAGE_NAME,
        "author": AUTHOR,
        "license": LICENSE,
        "repository": REPOSITORY,
    }


def parse_version(version_string: str) -> tuple[int, int, int, str]:
    """Parse a PEP 440 version string into (major, minor, patch, suffix).

    Raises ValueError for malformed version strings.
    """
    import re

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", version_string)
    if not match:
        msg = f"Invalid version string: {version_string!r}"
        raise ValueError(msg)
    major, minor, patch, suffix = match.groups()
    return int(major), int(minor), int(patch), suffix


__all__ = [
    "__version__",
    "VERSION_INFO",
    "VERSION_MAJOR",
    "VERSION_MINOR",
    "VERSION_PATCH",
    "VERSION_SUFFIX",
    "RELEASE_DATE",
    "PACKAGE_NAME",
    "AUTHOR",
    "LICENSE",
    "REPOSITORY",
    "get_version",
    "get_version_info",
    "get_version_tuple",
    "parse_version",
]
