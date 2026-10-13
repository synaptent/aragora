"""
Compatibility layer for versioning module.

Provides backward-compatible functions for existing code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from aragora.__version__ import __version__
from aragora.server.versioning.router import APIVersion

# Current release version, sent as X-API-Release. Derived from the package
# version (kept aligned by scripts/check_version_alignment.py) instead of a
# literal that went stale at 2.0.3.
API_RELEASE_VERSION = __version__


@dataclass
class VersionConfig:
    """Configuration for API versioning."""

    current: APIVersion = APIVersion.V2
    supported: set[APIVersion] = field(default_factory=lambda: {APIVersion.V1, APIVersion.V2})
    deprecated: set[APIVersion] = field(default_factory=lambda: {APIVersion.V1})
    sunset_dates: dict[APIVersion, str] = field(
        default_factory=lambda: {
            APIVersion.V1: "2026-06-01",
        }
    )
    default_for_legacy: APIVersion = APIVersion.V1

    def is_supported(self, version: APIVersion) -> bool:
        return version in self.supported

    def is_deprecated(self, version: APIVersion) -> bool:
        return version in self.deprecated

    def get_sunset_date(self, version: APIVersion) -> str | None:
        return self.sunset_dates.get(version)


# Global config
_config = VersionConfig()


def get_version_config() -> VersionConfig:
    """Get current version configuration."""
    return _config


def set_version_config(config: VersionConfig) -> None:
    """Set version configuration."""
    global _config
    _config = config


def extract_version(path: str, headers: dict[str, str] | None = None) -> tuple[APIVersion, bool]:
    """
    Extract API version from request path or headers.

    Returns:
        Tuple of (version, is_legacy)
    """
    config = get_version_config()

    # Check path prefix
    match = re.match(r"^/api/(v\d+)/", path)
    if match:
        version_str = match.group(1)
        version = APIVersion.from_string(version_str)
        if version and config.is_supported(version):
            return version, False
        # Invalid or unsupported version - return current
        return config.current, False

    # Check headers
    if headers:
        # Check X-API-Version header
        header_version = headers.get("X-API-Version") or headers.get("x-api-version")
        if header_version:
            version = APIVersion.from_string(header_version)
            if version and config.is_supported(version):
                return version, False

        # Check Accept header for version
        accept = headers.get("Accept") or headers.get("accept") or ""
        accept_match = re.search(r"vnd\.aragora\.v(\d+)", accept)
        if accept_match:
            version = APIVersion.from_string(accept_match.group(1))
            if version and config.is_supported(version):
                return version, False

    # Non-API path - return current
    if not path.startswith("/api/"):
        return config.current, False

    # Legacy path (no version prefix)
    return config.default_for_legacy, True


def _deprecation_level(sunset: str | None) -> str:
    if not sunset:
        return "warning"
    try:
        sunset_date = date.fromisoformat(sunset)
    except ValueError:
        return "warning"
    days_left = (sunset_date - date.today()).days
    if days_left < 0:
        return "sunset"
    if days_left < 30:
        return "critical"
    return "warning"


def version_response_headers(
    version: APIVersion,
    is_legacy: bool = False,
    *,
    path: str | None = None,
) -> dict[str, str]:
    """Generate response headers for a version."""
    config = get_version_config()
    supported = ",".join(v.value for v in config.supported)

    headers = {
        "X-API-Version": version.value,
        "X-API-Release": API_RELEASE_VERSION,
        "X-API-Supported-Versions": supported,
    }

    if is_legacy:
        headers["X-API-Legacy"] = "true"
        headers["X-API-Migration"] = (
            f"Use /api/{config.current.value}/ prefix for versioned endpoints"
        )

    deprecated = config.is_deprecated(version) or is_legacy
    if deprecated:
        headers["X-API-Deprecated"] = "true"
        sunset = config.get_sunset_date(version) or config.get_sunset_date(
            config.default_for_legacy
        )
        if sunset:
            headers["X-API-Sunset"] = sunset
            headers["Sunset"] = sunset
        headers["Deprecation"] = "true"
        headers["X-Deprecation-Level"] = _deprecation_level(sunset)
        if path and path.startswith("/api/"):
            replacement = normalize_path_version(strip_version_prefix(path), config.current)
            headers["Link"] = f'<{replacement}>; rel="successor-version"'

    return headers


def normalize_path_version(path: str, target_version: APIVersion | None = None) -> str:
    """Normalize path to use specific version prefix."""
    config = get_version_config()
    target = target_version or config.current

    # Non-API path - return as-is
    if not path.startswith("/api/"):
        return path

    # Already versioned - preserve
    if is_versioned_path(path):
        return path

    # Add version prefix to legacy path
    rest = path[4:]  # Remove /api
    return f"/api/{target.value}{rest}"


def strip_version_prefix(path: str) -> str:
    """Remove version prefix from path, keeping /api/."""
    match = re.match(r"^/api/v\d+(/.*)?$", path)
    if match:
        rest = match.group(1) or ""
        return f"/api{rest}"
    # Already no version prefix, return as-is
    return path


def is_versioned_path(path: str) -> bool:
    """Check if path has version prefix."""
    return bool(re.match(r"^/api/v\d+/", path))


def is_legacy_path(path: str) -> bool:
    """Check if path is legacy (no version)."""
    return path.startswith("/api/") and not is_versioned_path(path)


def get_path_version(path: str) -> APIVersion | None:
    """Extract version from path, or None if not versioned."""
    match = re.match(r"^/api/(v\d+)/", path)
    if match:
        return APIVersion.from_string(match.group(1))
    return None
