"""
Tests for API Versioning module.

Tests cover:
- Version extraction from paths and headers
- Response header generation
- Path normalization
- Legacy path detection
- Deprecation handling
"""

import pytest

from aragora.server.versioning import (
    APIVersion,
    API_RELEASE_VERSION,
    VersionConfig,
    get_version_config,
    set_version_config,
    extract_version,
    version_response_headers,
    normalize_path_version,
    strip_version_prefix,
    is_versioned_path,
    is_legacy_path,
    get_path_version,
)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset version config before each test."""
    set_version_config(VersionConfig())
    yield
    set_version_config(VersionConfig())


class TestAPIVersion:
    """Tests for APIVersion enum."""

    def test_v1_value(self):
        """V1 should have value 'v1'."""
        assert APIVersion.V1.value == "v1"

    def test_v2_value(self):
        """V2 should have value 'v2'."""
        assert APIVersion.V2.value == "v2"


class TestVersionConfig:
    """Tests for VersionConfig dataclass."""

    def test_default_current_is_v2(self):
        """Default current version should be V2."""
        config = VersionConfig()
        assert config.current == APIVersion.V2

    def test_default_supports_v1_and_v2(self):
        """Default config should support V1 and V2."""
        config = VersionConfig()
        assert config.is_supported(APIVersion.V1)
        assert config.is_supported(APIVersion.V2)

    def test_v1_is_deprecated(self):
        """V1 should be deprecated by default."""
        config = VersionConfig()
        assert config.is_deprecated(APIVersion.V1)
        assert not config.is_deprecated(APIVersion.V2)

    def test_v1_has_sunset_date(self):
        """V1 should have a sunset date."""
        config = VersionConfig()
        sunset = config.get_sunset_date(APIVersion.V1)
        assert sunset is not None
        assert "2026" in sunset

    def test_legacy_defaults_to_v1(self):
        """Legacy paths should default to V1."""
        config = VersionConfig()
        assert config.default_for_legacy == APIVersion.V1


class TestExtractVersion:
    """Tests for extract_version function."""

    def test_extracts_v1_from_path(self):
        """Should extract V1 from /api/v1/ path."""
        version, is_legacy = extract_version("/api/v1/debates")
        assert version == APIVersion.V1
        assert is_legacy is False

    def test_extracts_v2_from_path(self):
        """Should extract V2 from /api/v2/ path."""
        version, is_legacy = extract_version("/api/v2/debates")
        assert version == APIVersion.V2
        assert is_legacy is False

    def test_legacy_path_returns_v1(self):
        """Legacy paths should return V1 with is_legacy=True."""
        version, is_legacy = extract_version("/api/debates")
        assert version == APIVersion.V1
        assert is_legacy is True

    def test_header_based_versioning(self):
        """Should extract version from Accept header."""
        headers = {"Accept": "application/vnd.aragora.v1+json"}
        version, is_legacy = extract_version("/api/debates", headers)
        assert version == APIVersion.V1
        assert is_legacy is False

    def test_path_takes_precedence_over_header(self):
        """Path-based version should take precedence over header."""
        headers = {"Accept": "application/vnd.aragora.v1+json"}
        version, is_legacy = extract_version("/api/v2/debates", headers)
        assert version == APIVersion.V2

    def test_non_api_path_returns_current(self):
        """Non-API paths should return current version."""
        version, is_legacy = extract_version("/static/file.js")
        assert version == APIVersion.V2
        assert is_legacy is False

    def test_invalid_version_returns_current(self):
        """Invalid version should fallback to current."""
        version, is_legacy = extract_version("/api/v99/debates")
        assert version == APIVersion.V2


class TestVersionResponseHeaders:
    """Tests for version_response_headers function."""

    def test_includes_api_version(self):
        """Should include X-API-Version header."""
        headers = version_response_headers(APIVersion.V1)
        assert headers["X-API-Version"] == "v1"

    def test_includes_release_version(self):
        """Should include X-API-Release header."""
        headers = version_response_headers(APIVersion.V1)
        assert "X-API-Release" in headers
        assert headers["X-API-Release"] == API_RELEASE_VERSION

    def test_includes_supported_versions(self):
        """Should include X-API-Supported-Versions header."""
        headers = version_response_headers(APIVersion.V1)
        assert "v1" in headers["X-API-Supported-Versions"]
        assert "v2" in headers["X-API-Supported-Versions"]

    def test_legacy_path_gets_migration_hint(self):
        """Legacy paths should get migration hint headers."""
        headers = version_response_headers(APIVersion.V1, is_legacy=True)
        assert headers["X-API-Legacy"] == "true"
        assert "X-API-Migration" in headers

    def test_deprecated_version_gets_sunset_header(self):
        """Deprecated versions should get deprecation headers."""
        headers = version_response_headers(APIVersion.V1)
        assert headers["X-API-Deprecated"] == "true"
        assert "X-API-Sunset" in headers
        assert headers["Deprecation"] == "true"

    def test_legacy_path_includes_successor_link(self):
        """Legacy paths should include successor-version link header."""
        headers = version_response_headers(APIVersion.V1, is_legacy=True, path="/api/debates")
        assert headers["Deprecation"] == "true"
        assert "Sunset" in headers
        assert headers["Link"] == '</api/v2/debates>; rel="successor-version"'

    def test_current_version_no_deprecation(self):
        """Current version should not have deprecation headers."""
        headers = version_response_headers(APIVersion.V2)
        assert "X-API-Deprecated" not in headers


class TestNormalizePathVersion:
    """Tests for normalize_path_version function."""

    def test_adds_version_to_legacy_path(self):
        """Should add version prefix to legacy paths."""
        result = normalize_path_version("/api/debates")
        assert result == "/api/v2/debates"  # Uses current version

    def test_preserves_versioned_path(self):
        """Should not modify already versioned paths."""
        result = normalize_path_version("/api/v1/debates")
        assert result == "/api/v1/debates"

    def test_preserves_non_api_path(self):
        """Should not modify non-API paths."""
        result = normalize_path_version("/static/file.js")
        assert result == "/static/file.js"

    def test_respects_target_version(self):
        """Should use target version when specified."""
        result = normalize_path_version("/api/debates", target_version=APIVersion.V1)
        assert result == "/api/v1/debates"


class TestStripVersionPrefix:
    """Tests for strip_version_prefix function."""

    def test_strips_v1_prefix(self):
        """Should strip /api/v1/ prefix."""
        result = strip_version_prefix("/api/v1/debates")
        assert result == "/api/debates"

    def test_strips_v2_prefix(self):
        """Should strip /api/v2/ prefix."""
        result = strip_version_prefix("/api/v2/debates/123")
        assert result == "/api/debates/123"

    def test_preserves_unversioned_path(self):
        """Should not modify unversioned paths."""
        result = strip_version_prefix("/api/debates")
        assert result == "/api/debates"

    def test_preserves_non_api_path(self):
        """Should not modify non-API paths."""
        result = strip_version_prefix("/static/file.js")
        assert result == "/static/file.js"


class TestIsVersionedPath:
    """Tests for is_versioned_path function."""

    def test_versioned_path_returns_true(self):
        """Versioned paths should return True."""
        assert is_versioned_path("/api/v1/debates") is True
        assert is_versioned_path("/api/v2/agents") is True

    def test_legacy_path_returns_false(self):
        """Legacy paths should return False."""
        assert is_versioned_path("/api/debates") is False

    def test_non_api_path_returns_false(self):
        """Non-API paths should return False."""
        assert is_versioned_path("/static/file.js") is False


class TestIsLegacyPath:
    """Tests for is_legacy_path function."""

    def test_legacy_path_returns_true(self):
        """Legacy API paths should return True."""
        assert is_legacy_path("/api/debates") is True
        assert is_legacy_path("/api/agents/123") is True

    def test_versioned_path_returns_false(self):
        """Versioned paths should return False."""
        assert is_legacy_path("/api/v1/debates") is False

    def test_non_api_path_returns_false(self):
        """Non-API paths should return False."""
        assert is_legacy_path("/static/file.js") is False


class TestGetPathVersion:
    """Tests for get_path_version function."""

    def test_extracts_v1(self):
        """Should extract V1 from path."""
        assert get_path_version("/api/v1/debates") == APIVersion.V1

    def test_extracts_v2(self):
        """Should extract V2 from path."""
        assert get_path_version("/api/v2/debates") == APIVersion.V2

    def test_returns_none_for_unversioned(self):
        """Should return None for unversioned paths."""
        assert get_path_version("/api/debates") is None

    def test_returns_none_for_invalid_version(self):
        """Should return None for invalid version."""
        assert get_path_version("/api/v99/debates") is None


def test_api_release_version_is_the_package_version():
    from aragora.__version__ import __version__

    assert API_RELEASE_VERSION == __version__
    assert API_RELEASE_VERSION != "2.0.3"
