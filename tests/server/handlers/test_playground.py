"""
Tests for PlaygroundHandler - Public demo endpoint for the debate engine.

Tests cover:
- Path routing (can_handle)
- Status endpoint (GET /api/v1/playground/status)
- Successful debate with default params (POST /api/v1/playground/debate)
- Custom topic, rounds, and agent count
- Input validation (topic length, parameter clamping)
- Rate limiting enforcement
- Import failure graceful degradation
"""

from __future__ import annotations

import io
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.playground import (
    PlaygroundHandler,
    _check_rate_limit,
    _reset_rate_limits,
    _PLAYGROUND_RATE_LIMIT,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def clean_rate_limits():
    """Reset rate limit state before each test."""
    _reset_rate_limits()
    yield
    _reset_rate_limits()


@pytest.fixture
def handler():
    """Create a PlaygroundHandler with empty context."""
    return PlaygroundHandler({})


class _MockHeaders:
    """Minimal mock of http.server headers that supports .get() and int()."""

    def __init__(self, raw_len: int):
        self._data = {
            "Content-Type": "application/json",
            "Content-Length": str(raw_len),
        }

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP request handler with a JSON body helper."""

    def _make(body: dict[str, Any] | None = None, client_ip: str = "10.0.0.1"):
        h = MagicMock()
        h.client_address = (client_ip, 12345)

        if body is not None:
            raw = json.dumps(body).encode()
        else:
            raw = b""

        h.headers = _MockHeaders(len(raw))
        h.rfile = io.BytesIO(raw)

        return h

    return _make


def _parse_result(result) -> tuple[dict[str, Any], int]:
    """Parse a HandlerResult into (body_dict, status_code)."""
    assert result is not None, "Expected a result, got None"
    body = result.body
    if isinstance(body, (bytes, str)):
        data = json.loads(body)
    else:
        data = body
    return data, result.status_code


# ===========================================================================
# Test: can_handle
# ===========================================================================


class TestCanHandle:
    def test_handles_debate_path(self, handler):
        assert handler.can_handle("/api/v1/playground/debate") is True

    def test_handles_status_path(self, handler):
        assert handler.can_handle("/api/v1/playground/status") is True

    def test_rejects_other_paths(self, handler):
        assert handler.can_handle("/api/v1/playground") is False
        assert handler.can_handle("/api/v1/debates") is False
        assert handler.can_handle("/api/v1/playground/debate/extra") is False


# ===========================================================================
# Test: GET /api/v1/playground/status
# ===========================================================================


class TestStatusEndpoint:
    def test_status_returns_ok(self, handler):
        result = handler.handle("/api/v1/playground/status", {}, None)
        data, status = _parse_result(result)

        assert status == 200
        assert data["status"] == "ok"
        assert data["engine"] == "aragora-debate"
        assert data["mock_agents"] is True
        assert "max_rounds" in data
        assert "max_agents" in data
        assert "rate_limit" in data

    def test_status_returns_none_for_wrong_path(self, handler):
        result = handler.handle("/api/v1/playground/debate", {}, None)
        assert result is None


# ===========================================================================
# Test: POST /api/v1/playground/debate - successful runs
# ===========================================================================


class TestDebateEndpoint:
    def test_debate_with_defaults(self, handler, mock_http_handler):
        """Running a debate with default parameters succeeds."""
        h = mock_http_handler({})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200
        assert "id" in data
        assert data["topic"] == "Should we use microservices or a monolith?"
        assert data["rounds_used"] >= 1
        assert "proposals" in data
        assert "critiques" in data
        assert "votes" in data
        assert "receipt" in data
        assert "receipt_hash" in data
        assert "participants" in data
        assert len(data["participants"]) == 3  # default agent count
        assert data["duration_seconds"] >= 0

    def test_debate_with_custom_topic(self, handler, mock_http_handler):
        """Custom topic is passed through correctly."""
        h = mock_http_handler({"topic": "Should we use Rust or Go?"})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200
        assert data["topic"] == "Should we use Rust or Go?"

    def test_debate_with_custom_agents(self, handler, mock_http_handler):
        """Custom agent count is respected."""
        h = mock_http_handler({"agents": 4})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200
        assert len(data["participants"]) == 4

    def test_debate_with_one_round(self, handler, mock_http_handler):
        """Single round debates work."""
        h = mock_http_handler({"rounds": 1})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200
        assert data["rounds_used"] >= 1

    def test_debate_response_structure(self, handler, mock_http_handler):
        """Verify the full response structure."""
        h = mock_http_handler({"topic": "Test topic"})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200

        # Required top-level fields
        required_fields = [
            "id",
            "topic",
            "status",
            "rounds_used",
            "consensus_reached",
            "confidence",
            "verdict",
            "duration_seconds",
            "participants",
            "proposals",
            "critiques",
            "votes",
            "dissenting_views",
            "final_answer",
            "receipt",
            "receipt_hash",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        # Proposals should be a dict mapping agent name -> text
        assert isinstance(data["proposals"], dict)
        assert len(data["proposals"]) > 0

        # Critiques should be a list of dicts
        assert isinstance(data["critiques"], list)
        if data["critiques"]:
            c = data["critiques"][0]
            assert "agent" in c
            assert "target_agent" in c
            assert "issues" in c
            assert "severity" in c

        # Votes should be a list of dicts
        assert isinstance(data["votes"], list)
        if data["votes"]:
            v = data["votes"][0]
            assert "agent" in v
            assert "choice" in v
            assert "confidence" in v

    def test_debate_returns_none_for_wrong_path(self, handler, mock_http_handler):
        h = mock_http_handler({})
        result = handler.handle_post("/api/v1/playground/status", {}, h)
        assert result is None


# ===========================================================================
# Test: Input validation
# ===========================================================================


class TestInputValidation:
    def test_topic_too_long(self, handler, mock_http_handler):
        """Topics over 100,000 characters are rejected."""
        h = mock_http_handler({"topic": "x" * 100_001})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 400
        assert "100000 characters" in data.get("error", "")

    def test_rounds_clamped_to_max(self, handler, mock_http_handler):
        """Rounds above 2 are clamped to 2."""
        h = mock_http_handler({"rounds": 10})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)

        assert status == 200
        assert data["rounds_used"] <= 2

    def test_agents_clamped_to_range(self, handler, mock_http_handler):
        """Agent count is clamped between 2 and 5."""
        # Below minimum
        h = mock_http_handler({"agents": 1})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)
        assert status == 200
        assert len(data["participants"]) == 2

        # Above maximum
        _reset_rate_limits()
        h2 = mock_http_handler({"agents": 20})
        result2 = handler.handle_post("/api/v1/playground/debate", {}, h2)
        data2, status2 = _parse_result(result2)
        assert status2 == 200
        assert len(data2["participants"]) == 5

    def test_invalid_rounds_uses_default(self, handler, mock_http_handler):
        """Non-integer rounds fall back to default."""
        h = mock_http_handler({"rounds": "not-a-number"})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)
        assert status == 200

    def test_empty_topic_uses_default(self, handler, mock_http_handler):
        """Empty string topic falls back to default."""
        h = mock_http_handler({"topic": ""})
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)
        assert status == 200
        assert data["topic"] == "Should we use microservices or a monolith?"

    def test_null_body_uses_defaults(self, handler, mock_http_handler):
        """No body at all uses all defaults."""
        h = mock_http_handler(None)
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)
        assert status == 200


# ===========================================================================
# Test: Rate limiting
# ===========================================================================


class TestRateLimiting:
    def test_allows_requests_within_limit(self):
        """Requests within the limit are allowed."""
        for _ in range(_PLAYGROUND_RATE_LIMIT):
            allowed, _ = _check_rate_limit("192.168.1.1")
            assert allowed is True

    def test_blocks_requests_over_limit(self):
        """Requests beyond the limit are blocked."""
        for _ in range(_PLAYGROUND_RATE_LIMIT):
            _check_rate_limit("192.168.1.2")

        allowed, retry_after = _check_rate_limit("192.168.1.2")
        assert allowed is False
        assert retry_after > 0

    def test_different_ips_have_separate_limits(self):
        """Each IP gets its own rate limit bucket."""
        for _ in range(_PLAYGROUND_RATE_LIMIT):
            _check_rate_limit("192.168.1.3")

        # Different IP should still be allowed
        allowed, _ = _check_rate_limit("192.168.1.4")
        assert allowed is True

    @patch("aragora.storage.debate_store.DebateResultStore.get_by_cache_key", return_value=None)
    def test_rate_limit_returns_429(self, _mock_cache, handler, mock_http_handler):
        """Handler returns 429 when rate limit is exceeded.

        Cache is patched to always miss so that every request goes through
        the rate limiter (cached results intentionally bypass rate limiting).
        """
        client_ip = "10.99.99.99"

        for _ in range(_PLAYGROUND_RATE_LIMIT):
            h = mock_http_handler({}, client_ip=client_ip)
            result = handler.handle_post("/api/v1/playground/debate", {}, h)
            _, status = _parse_result(result)
            assert status == 200

        # Next request should be rate limited
        h = mock_http_handler({}, client_ip=client_ip)
        result = handler.handle_post("/api/v1/playground/debate", {}, h)
        data, status = _parse_result(result)
        assert status == 429
        assert "rate_limit_exceeded" in data.get("code", "")
        assert "retry_after" in data

    def test_reset_clears_limits(self):
        """_reset_rate_limits clears all state."""
        for _ in range(_PLAYGROUND_RATE_LIMIT):
            _check_rate_limit("192.168.1.5")

        _reset_rate_limits()
        allowed, _ = _check_rate_limit("192.168.1.5")
        assert allowed is True


# ===========================================================================
# Test: Graceful degradation
# ===========================================================================


class TestGracefulDegradation:
    def test_missing_aragora_debate_uses_inline_fallback(self, handler, mock_http_handler):
        """When aragora-debate is not installed, falls back to inline mock."""
        h = mock_http_handler({})

        with patch.dict(
            "sys.modules",
            {
                "aragora_debate.styled_mock": None,
                "aragora_debate.arena": None,
                "aragora_debate.types": None,
            },
        ):
            # Force the import to fail by patching builtins.__import__
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def failing_import(name, *args, **kwargs):
                if name.startswith("aragora_debate"):
                    raise ImportError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=failing_import):
                result = handler._run_debate("test", 1, 2)
                data, status = _parse_result(result)
                # Falls back to inline mock instead of returning 503
                assert status == 200
                assert "proposals" in data
                assert "critiques" in data
                assert "votes" in data
                assert "receipt" in data
                assert data["topic"] == "test"
