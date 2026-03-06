"""Tests for session circuit-breaker integration in QuotaFallbackMixin.

Verifies that auth/quota errors (401, 403, 429) are forwarded to the
SessionCircuitBreaker, and that pinned providers are skipped in favour
of the OpenRouter fallback.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal stub that satisfies QuotaFallbackMixin's expected attributes
# ---------------------------------------------------------------------------


class _StubAgent:
    """Minimal agent-like object mixed with QuotaFallbackMixin for testing."""

    def __init__(self, name: str = "test-agent"):
        from aragora.agents.fallback import QuotaFallbackMixin

        # Dynamically create a class that mixes in QuotaFallbackMixin
        self.__class__ = type(
            "AnthropicAPIAgentStub",
            (QuotaFallbackMixin,),
            {},
        )
        self.name = name
        self.model = "claude-opus-4-6"
        self.role = "proposer"
        self.timeout = 30
        self.enable_fallback = True
        self._fallback_agent = None


def _make_stub(name: str = "test-agent") -> _StubAgent:
    return _StubAgent(name=name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_circuit_breaker() -> MagicMock:
    """Create a mock SessionCircuitBreaker with the expected API."""
    cb = MagicMock()
    cb.mark_provider_failed = MagicMock()
    cb.is_provider_available = MagicMock(return_value=True)
    cb.get_fallback_provider = MagicMock(return_value="openrouter")
    return cb


def _patch_session_cb(mock_cb):
    """Patch the lazy-import helper to return *mock_cb*."""
    return patch("aragora.agents.fallback._get_session_cb", return_value=mock_cb)


# ---------------------------------------------------------------------------
# Tests: notification on failure status codes
# ---------------------------------------------------------------------------


class TestCircuitBreakerNotification:
    """Verify that fallback_generate notifies the circuit breaker."""

    def test_401_marks_provider_failed(self):
        """A 401 status code should mark the provider as failed."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        with _patch_session_cb(cb):
            stub._notify_session_circuit_breaker(401)

        cb.mark_provider_failed.assert_called_once()
        call_kwargs = cb.mark_provider_failed.call_args
        assert call_kwargs[1]["status_code"] == 401
        assert "anthropic" in call_kwargs[0][0]  # provider name

    def test_429_marks_provider_failed(self):
        """A 429 status code should mark the provider as failed."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        with _patch_session_cb(cb):
            stub._notify_session_circuit_breaker(429)

        cb.mark_provider_failed.assert_called_once()
        call_kwargs = cb.mark_provider_failed.call_args
        assert call_kwargs[1]["status_code"] == 429

    def test_403_marks_provider_failed(self):
        """A 403 status code should mark the provider as failed."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        with _patch_session_cb(cb):
            stub._notify_session_circuit_breaker(403)

        cb.mark_provider_failed.assert_called_once()
        call_kwargs = cb.mark_provider_failed.call_args
        assert call_kwargs[1]["status_code"] == 403

    def test_500_does_not_notify(self):
        """A 500 status code should NOT notify the circuit breaker directly."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        with _patch_session_cb(cb):
            stub._notify_session_circuit_breaker(500)

        cb.mark_provider_failed.assert_not_called()

    def test_fallback_generate_notifies_on_401(self):
        """fallback_generate should notify the circuit breaker when called with 401."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        # Mock the OpenRouter fallback agent
        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="fallback response")
        mock_fallback.model = "anthropic/claude-sonnet-4"
        stub._fallback_agent = mock_fallback

        with (
            _patch_session_cb(cb),
            patch("aragora.agents.fallback.record_fallback_activation"),
            patch("aragora.agents.fallback.record_fallback_success"),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                stub.fallback_generate("test prompt", status_code=401)
            )

        assert result == "fallback response"
        cb.mark_provider_failed.assert_called_once()
        assert cb.mark_provider_failed.call_args[1]["status_code"] == 401

    def test_fallback_generate_stream_notifies_on_429(self):
        """fallback_generate_stream should notify the circuit breaker on 429."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        # Mock a streaming fallback agent
        async def _fake_stream(prompt, context=None):
            yield "token1"
            yield "token2"

        mock_fallback = MagicMock()
        mock_fallback.generate_stream = _fake_stream
        mock_fallback.model = "anthropic/claude-sonnet-4"
        stub._fallback_agent = mock_fallback

        tokens = []

        async def _collect():
            async for token in stub.fallback_generate_stream("test", status_code=429):
                tokens.append(token)

        with (
            _patch_session_cb(cb),
            patch("aragora.agents.fallback.record_fallback_activation"),
            patch("aragora.agents.fallback.record_fallback_success"),
        ):
            asyncio.get_event_loop().run_until_complete(_collect())

        assert tokens == ["token1", "token2"]
        cb.mark_provider_failed.assert_called_once()
        assert cb.mark_provider_failed.call_args[1]["status_code"] == 429


# ---------------------------------------------------------------------------
# Tests: is_provider_pinned check
# ---------------------------------------------------------------------------


class TestProviderPinnedCheck:
    """Verify that is_provider_pinned reads from the circuit breaker."""

    def test_pinned_provider_returns_true(self):
        """When circuit breaker says unavailable, is_provider_pinned returns True."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()
        cb.is_provider_available.return_value = False

        with _patch_session_cb(cb):
            assert stub.is_provider_pinned() is True

        cb.is_provider_available.assert_called_once_with("anthropic")

    def test_available_provider_returns_false(self):
        """When circuit breaker says available, is_provider_pinned returns False."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()
        cb.is_provider_available.return_value = True

        with _patch_session_cb(cb):
            assert stub.is_provider_pinned() is False

    def test_after_401_provider_is_pinned(self):
        """After a 401 marks the provider as failed, is_provider_pinned should reflect it."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()

        # Initially available
        cb.is_provider_available.return_value = True
        with _patch_session_cb(cb):
            assert stub.is_provider_pinned() is False

        # After marking failed, update mock to reflect pinning
        cb.is_provider_available.return_value = False
        with _patch_session_cb(cb):
            stub._notify_session_circuit_breaker(401)
            assert stub.is_provider_pinned() is True

    def test_subsequent_calls_use_fallback(self):
        """After marking failed, fallback_generate should use OpenRouter."""
        stub = _make_stub()
        cb = _make_mock_circuit_breaker()
        cb.is_provider_available.return_value = False

        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="openrouter response")
        mock_fallback.model = "anthropic/claude-sonnet-4"
        stub._fallback_agent = mock_fallback

        with _patch_session_cb(cb):
            # Provider is pinned
            assert stub.is_provider_pinned() is True

            # But fallback_generate still works via OpenRouter
            with (
                patch("aragora.agents.fallback.record_fallback_activation"),
                patch("aragora.agents.fallback.record_fallback_success"),
            ):
                result = asyncio.get_event_loop().run_until_complete(
                    stub.fallback_generate("test prompt", status_code=429)
                )

        assert result == "openrouter response"
        mock_fallback.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: graceful degradation when circuit breaker unavailable
# ---------------------------------------------------------------------------


class TestCircuitBreakerUnavailable:
    """Verify non-breaking behavior when session_circuit_breaker is missing."""

    def test_notify_no_op_when_cb_unavailable(self):
        """_notify_session_circuit_breaker should be a no-op when module is missing."""
        stub = _make_stub()

        with _patch_session_cb(None):
            # Should not raise
            stub._notify_session_circuit_breaker(401)

    def test_is_provider_pinned_returns_false_when_cb_unavailable(self):
        """is_provider_pinned should return False when module is missing."""
        stub = _make_stub()

        with _patch_session_cb(None):
            assert stub.is_provider_pinned() is False

    def test_fallback_generate_works_without_cb(self):
        """fallback_generate should work normally when circuit breaker is absent."""
        stub = _make_stub()

        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="response without cb")
        mock_fallback.model = "anthropic/claude-sonnet-4"
        stub._fallback_agent = mock_fallback

        with (
            _patch_session_cb(None),
            patch("aragora.agents.fallback.record_fallback_activation"),
            patch("aragora.agents.fallback.record_fallback_success"),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                stub.fallback_generate("prompt", status_code=429)
            )

        assert result == "response without cb"

    def test_lazy_import_failure_is_silent(self):
        """If the import itself fails, _get_session_cb returns None silently."""
        import aragora.agents.fallback as fb

        # Reset the module-level cache to force a re-import attempt
        original_attempted = fb._session_cb_import_attempted
        original_module = fb._session_cb_module
        try:
            fb._session_cb_import_attempted = False
            fb._session_cb_module = None

            with patch.dict("sys.modules", {"aragora.routing.session_circuit_breaker": None}):
                # This should not raise; it should return None
                result = fb._get_session_cb()
                assert result is None
                assert fb._session_cb_import_attempted is True
        finally:
            fb._session_cb_import_attempted = original_attempted
            fb._session_cb_module = original_module


# ---------------------------------------------------------------------------
# Tests: provider name derivation
# ---------------------------------------------------------------------------


class TestProviderNameDerivation:
    """Verify that _derive_provider_name maps class names correctly."""

    def test_anthropic_class_name(self):
        stub = _make_stub()
        # The stub class is named AnthropicAPIAgentStub
        assert stub._derive_provider_name() == "anthropic"

    def test_openai_class_name(self):
        from aragora.agents.fallback import QuotaFallbackMixin

        obj = object.__new__(QuotaFallbackMixin)
        obj.__class__ = type("OpenAIAPIAgent", (QuotaFallbackMixin,), {})
        obj.name = "gpt-api"
        assert obj._derive_provider_name() == "openai"

    def test_gemini_class_name(self):
        from aragora.agents.fallback import QuotaFallbackMixin

        obj = object.__new__(QuotaFallbackMixin)
        obj.__class__ = type("GeminiAgent", (QuotaFallbackMixin,), {})
        obj.name = "gemini-pro"
        assert obj._derive_provider_name() == "gemini"

    def test_unknown_class_falls_back_to_name(self):
        from aragora.agents.fallback import QuotaFallbackMixin

        obj = object.__new__(QuotaFallbackMixin)
        obj.__class__ = type("CustomProvider", (QuotaFallbackMixin,), {})
        obj.name = "custom-agent-v2"
        assert obj._derive_provider_name() == "custom"
