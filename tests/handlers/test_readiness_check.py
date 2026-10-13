"""Tests for GET /api/v1/readiness - SME onboarding readiness check.

Verifies:
- Route matching (can_handle) for both versioned and unversioned paths
- Provider detection from environment variables
- ready_to_debate logic (at least one required provider)
- Missing required / optional key reporting
- Storage backend detection (sqlite default, postgres, supabase)
- Feature availability via importlib.util.find_spec
- Unrelated paths return None
- Response shape and field types
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.readiness_check import (
    ReadinessCheckHandler,
    _check_provider,
    _detect_features,
    _detect_storage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_body(result: Any) -> dict[str, Any]:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> ReadinessCheckHandler:
    """Create a ReadinessCheckHandler instance."""
    return ReadinessCheckHandler(ctx={})


@pytest.fixture
def mock_http_handler() -> MagicMock:
    """Create a mock HTTP request handler."""
    return MagicMock()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all AI provider keys from environment."""
    for var in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "DATABASE_URL",
        "ARAGORA_POSTGRES_DSN",
        "SUPABASE_POSTGRES_DSN",
        "SUPABASE_URL",
    ]:
        monkeypatch.delenv(var, raising=False)


# ============================================================================
# Route Matching
# ============================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_handles_versioned_path(self, handler: ReadinessCheckHandler) -> None:
        assert handler.can_handle("/api/v1/readiness") is True

    def test_handles_unversioned_path(self, handler: ReadinessCheckHandler) -> None:
        assert handler.can_handle("/api/readiness") is True

    def test_rejects_unrelated_path(self, handler: ReadinessCheckHandler) -> None:
        assert handler.can_handle("/api/v1/health") is False

    def test_rejects_partial_match(self, handler: ReadinessCheckHandler) -> None:
        assert handler.can_handle("/api/v1/readiness/extra") is False

    def test_rejects_empty_path(self, handler: ReadinessCheckHandler) -> None:
        assert handler.can_handle("") is False


# ============================================================================
# Full Endpoint Response
# ============================================================================


class TestEndpointResponse:
    """Tests for the full GET /api/v1/readiness response."""

    def test_returns_200(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200

    def test_response_has_required_fields(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert "ready_to_debate" in body
        assert "providers" in body
        assert "missing_required" in body
        assert "missing_optional" in body
        assert "storage" in body
        assert "features" in body
        assert "timestamp" in body

    def test_providers_all_listed(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        expected_providers = {"anthropic", "openai", "openrouter", "mistral", "gemini", "xai"}
        assert set(body["providers"].keys()) == expected_providers

    def test_each_provider_has_available_field(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        for name, info in body["providers"].items():
            assert "available" in info, f"Provider {name} missing 'available' field"

    def test_unrelated_path_returns_none(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/health", {}, mock_http_handler)
        assert result is None

    def test_unversioned_alias_works(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/readiness", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200
        body = parse_body(result)
        assert "ready_to_debate" in body

    def test_timestamp_is_utc_isoformat(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["timestamp"].endswith("Z")

    def test_features_are_booleans(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        for key, value in body["features"].items():
            assert isinstance(value, bool), f"Feature {key} is not bool: {type(value)}"


# ============================================================================
# ready_to_debate Logic
# ============================================================================


class TestReadyToDebate:
    """Tests for the ready_to_debate flag."""

    def test_ready_when_anthropic_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-XXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is True

    def test_ready_when_openai_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-XXXXXXXXXXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is True

    def test_ready_when_both_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-XXXXXXXXXXXX")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-XXXXXXXXXXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is True
        assert body["missing_required"] == []

    def test_ready_when_only_openrouter_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-XXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is True
        assert body["missing_required"] == []

    def test_not_ready_when_no_required_providers(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is False

    def test_not_ready_when_only_optional_providers_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "XXXXXXXXXXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is False

    def test_short_key_not_counted(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keys shorter than 10 characters are treated as not set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "short")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["ready_to_debate"] is False
        assert body["providers"]["anthropic"]["available"] is False


# ============================================================================
# Missing Keys Reporting
# ============================================================================


class TestMissingKeys:
    """Tests for missing_required and missing_optional lists."""

    def test_all_required_missing_when_clean(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert "ANTHROPIC_API_KEY" in body["missing_required"]
        assert "OPENAI_API_KEY" in body["missing_required"]
        assert "OPENROUTER_API_KEY" in body["missing_required"]

    def test_optional_missing_when_clean(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert "MISTRAL_API_KEY" in body["missing_optional"]
        assert "GEMINI_API_KEY" in body["missing_optional"]
        assert "GOOGLE_API_KEY" in body["missing_optional"]
        assert "XAI_API_KEY" in body["missing_optional"]
        assert "GROK_API_KEY" in body["missing_optional"]

    def test_missing_required_sorted(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["missing_required"] == sorted(body["missing_required"])

    def test_missing_optional_sorted(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
    ) -> None:
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert body["missing_optional"] == sorted(body["missing_optional"])

    def test_anthropic_not_in_missing_when_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-XXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert "ANTHROPIC_API_KEY" not in body["missing_required"]

    def test_openrouter_not_in_missing_when_set(
        self,
        handler: ReadinessCheckHandler,
        mock_http_handler: MagicMock,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-XXXXXXXXXXXX")
        result = handler.handle("/api/v1/readiness", {}, mock_http_handler)
        body = parse_body(result)
        assert "OPENROUTER_API_KEY" not in body["missing_required"]


# ============================================================================
# Provider Details
# ============================================================================


class TestProviderDetails:
    """Tests for individual provider info in the response."""

    def test_available_provider_has_model(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-XXXXXXXXXXXX")
        result = _check_provider("anthropic")
        assert result["available"] is True
        assert "model" in result
        assert isinstance(result["model"], str)
        assert len(result["model"]) > 0

    def test_unavailable_provider_has_reason(
        self,
        clean_env: None,
    ) -> None:
        result = _check_provider("openai")
        assert result["available"] is False
        assert "reason" in result
        assert "OPENAI_API_KEY" in result["reason"]

    def test_all_providers_checkable(self, clean_env: None) -> None:
        from aragora.server.handlers.readiness_check import _PROVIDER_CONFIG

        for name in _PROVIDER_CONFIG:
            result = _check_provider(name)
            assert "available" in result

    def test_gemini_google_api_key_counts_as_available(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test-key-12345")
        result = _check_provider("gemini")
        assert result["available"] is True
        assert result["model"] == "gemini-3.1-pro-preview"

    def test_xai_grok_api_key_alias_counts_as_available(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GROK_API_KEY", "xai-test-key-12345")
        result = _check_provider("xai")
        assert result["available"] is True
        assert result["model"] == "grok-4-latest"


# ============================================================================
# Storage Detection
# ============================================================================


class TestStorageDetection:
    """Tests for _detect_storage."""

    def test_default_sqlite(self, clean_env: None) -> None:
        result = _detect_storage()
        assert result["type"] == "sqlite"
        assert result["status"] == "connected"

    def test_postgres_via_database_url(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/aragora")
        result = _detect_storage()
        assert result["type"] == "postgresql"
        assert result["status"] == "configured"

    def test_postgres_via_aragora_dsn(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://localhost:5432/aragora")
        result = _detect_storage()
        assert result["type"] == "postgresql"

    def test_supabase_detection(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
        result = _detect_storage()
        assert result["type"] == "supabase"
        assert result["status"] == "configured"

    def test_postgres_preferred_over_supabase(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When both DATABASE_URL and SUPABASE_URL are set, postgres wins."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/aragora")
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
        result = _detect_storage()
        assert result["type"] == "postgresql"


# ============================================================================
# Feature Detection
# ============================================================================


class TestFeatureDetection:
    """Tests for _detect_features."""

    def test_returns_dict_of_bools(self) -> None:
        features = _detect_features()
        assert isinstance(features, dict)
        for key, value in features.items():
            assert isinstance(value, bool), f"{key} is not bool"

    def test_core_features_present(self) -> None:
        features = _detect_features()
        expected_keys = {
            "debates",
            "receipts",
            "knowledge_mound",
            "memory",
            "pulse",
            "explainability",
            "workflows",
            "rbac",
            "compliance",
            "analytics",
        }
        assert expected_keys.issubset(set(features.keys()))

    def test_debates_feature_available(self) -> None:
        """The debate orchestrator should always be importable in this codebase."""
        features = _detect_features()
        assert features["debates"] is True

    def test_feature_false_when_module_missing(self) -> None:
        """Simulate a missing module."""
        with patch("importlib.util.find_spec", return_value=None):
            features = _detect_features()
            assert features["debates"] is False
            assert features["receipts"] is False


# ============================================================================
# Handler Construction
# ============================================================================


class TestHandlerConstruction:
    """Tests for handler initialization."""

    def test_default_ctx(self) -> None:
        handler = ReadinessCheckHandler()
        assert handler.ctx == {}

    def test_custom_ctx(self) -> None:
        ctx = {"storage": "test"}
        handler = ReadinessCheckHandler(ctx=ctx)
        assert handler.ctx is ctx

    def test_routes_attribute(self) -> None:
        handler = ReadinessCheckHandler()
        assert "/api/v1/readiness" in handler.ROUTES
        assert "/api/readiness" in handler.ROUTES


# ============================================================================
# Lazy Import Registration
# ============================================================================


class TestRegistration:
    """Tests that the handler is properly registered in the module system."""

    def test_importable_from_handlers_package(self) -> None:
        from aragora.server.handlers import ReadinessCheckHandler as H

        assert H is ReadinessCheckHandler

    def test_in_handler_modules_mapping(self) -> None:
        from aragora.server.handlers._lazy_imports import HANDLER_MODULES

        assert "ReadinessCheckHandler" in HANDLER_MODULES
        assert (
            HANDLER_MODULES["ReadinessCheckHandler"]
            == "aragora.server.handlers.sme.readiness_check"
        )

    def test_in_all_handler_names(self) -> None:
        from aragora.server.handlers._lazy_imports import ALL_HANDLER_NAMES

        assert "ReadinessCheckHandler" in ALL_HANDLER_NAMES
