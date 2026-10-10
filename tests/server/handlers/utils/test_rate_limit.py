"""Tests for rate_limit module."""

from __future__ import annotations

import sys
import types as _types_mod

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m


import os
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.utils.rate_limit import (
    RateLimiter,
    _normalize_ip,
    get_client_ip,
    rate_limit,
    _get_limiter,
    clear_all_limiters,
    TRUSTED_PROXIES,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_limiters():
    """Clean up rate limiters after each test."""
    yield
    clear_all_limiters()


@pytest.fixture
def limiter():
    """Create a fresh rate limiter for testing."""
    return RateLimiter(requests_per_minute=10)


# =============================================================================
# Test _normalize_ip
# =============================================================================


class TestNormalizeIP:
    """Tests for _normalize_ip function."""

    def test_normalizes_ipv4(self):
        """Should normalize valid IPv4 address."""
        assert _normalize_ip("192.168.1.1") == "192.168.1.1"
        assert _normalize_ip(" 192.168.1.1 ") == "192.168.1.1"

    def test_normalizes_ipv6(self):
        """Should normalize valid IPv6 address."""
        assert _normalize_ip("::1") == "::1"
        assert _normalize_ip("2001:db8::1") == "2001:db8::1"

    def test_returns_empty_for_empty_input(self):
        """Should return empty string for empty input."""
        assert _normalize_ip("") == ""
        assert _normalize_ip(None) == ""

    def test_returns_original_for_invalid_ip(self):
        """Should return original string for non-IP values."""
        assert _normalize_ip("localhost") == "localhost"
        assert _normalize_ip("invalid") == "invalid"


# =============================================================================
# Test get_client_ip
# =============================================================================


class TestGetClientIP:
    """Tests for get_client_ip function."""

    def test_returns_unknown_for_none_handler(self):
        """Should return 'unknown' when handler is None."""
        assert get_client_ip(None) == "unknown"

    def test_extracts_from_client_address(self):
        """Should extract IP from client_address tuple."""
        handler = MagicMock()
        handler.client_address = ("192.168.1.100", 12345)
        handler.headers = {}

        ip = get_client_ip(handler)
        assert ip == "192.168.1.100"

    def test_trusts_forwarded_for_from_trusted_proxy(self):
        """Should trust X-Forwarded-For when direct IP is trusted proxy."""
        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = MagicMock()
        handler.headers.get = lambda h, d=None: (
            "203.0.113.50, 127.0.0.1" if "Forwarded" in h else None
        )

        ip = get_client_ip(handler)
        assert ip == "203.0.113.50"

    def test_ignores_forwarded_for_from_untrusted_source(self):
        """Should ignore X-Forwarded-For when source is not trusted."""
        handler = MagicMock()
        handler.client_address = ("192.168.1.100", 12345)
        handler.headers = MagicMock()
        handler.headers.get = lambda h, d=None: "10.0.0.1" if "Forwarded" in h else None

        ip = get_client_ip(handler)
        # Should use the direct client IP since 192.168.1.100 is not trusted
        assert ip == "192.168.1.100"

    def test_uses_x_real_ip_from_trusted_proxy(self):
        """Should use X-Real-IP when from trusted proxy."""
        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = MagicMock()

        def mock_get(header, default=None):
            if "Real-IP" in header:
                return "203.0.113.75"
            return None

        handler.headers.get = mock_get

        ip = get_client_ip(handler)
        assert ip == "203.0.113.75"

    def test_trusts_cloudflare_connecting_ip(self, monkeypatch):
        """Should trust CF-Connecting-IP with CF-RAY from a peer listed as Cloudflare-facing."""
        from aragora.server.middleware.rate_limit import base as rl_base

        monkeypatch.setattr(rl_base, "_CLOUDFLARE_PROXY_IPS", {"192.168.1.100"})
        handler = MagicMock()
        handler.client_address = ("192.168.1.100", 12345)
        handler.headers = MagicMock()

        def mock_get(header, default=None):
            if header.lower() == "cf-ray":
                return "abcd1234"
            if header.lower() == "cf-connecting-ip":
                return "198.51.100.77"
            return None

        handler.headers.get = mock_get

        ip = get_client_ip(handler)
        assert ip == "198.51.100.77"

    def test_returns_unknown_for_missing_client_address(self):
        """Should return 'unknown' when client_address is missing."""
        handler = MagicMock()
        handler.client_address = None
        handler.headers = {}

        ip = get_client_ip(handler)
        assert ip == "unknown"


# =============================================================================
# Test RateLimiter
# =============================================================================


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_allows_requests_under_limit(self, limiter):
        """Should allow requests under the rate limit."""
        for _ in range(10):
            assert limiter.is_allowed("client-1") is True

    def test_blocks_requests_over_limit(self, limiter):
        """Should block requests over the rate limit."""
        for _ in range(10):
            limiter.is_allowed("client-1")

        assert limiter.is_allowed("client-1") is False

    def test_separate_limits_per_key(self, limiter):
        """Should maintain separate limits per key."""
        for _ in range(10):
            limiter.is_allowed("client-1")

        # client-1 is rate limited
        assert limiter.is_allowed("client-1") is False
        # client-2 is not
        assert limiter.is_allowed("client-2") is True

    def test_get_remaining_returns_correct_count(self, limiter):
        """Should return correct remaining count."""
        assert limiter.get_remaining("client-1") == 10

        for _ in range(3):
            limiter.is_allowed("client-1")

        assert limiter.get_remaining("client-1") == 7

    def test_reset_clears_key_limit(self, limiter):
        """Should reset limit for a specific key."""
        for _ in range(10):
            limiter.is_allowed("client-1")

        assert limiter.is_allowed("client-1") is False

        limiter.reset("client-1")
        assert limiter.is_allowed("client-1") is True

    def test_clear_removes_all_buckets(self, limiter):
        """Should clear all rate limit buckets."""
        for _ in range(5):
            limiter.is_allowed("client-1")
            limiter.is_allowed("client-2")

        limiter.clear()

        assert limiter.get_remaining("client-1") == 10
        assert limiter.get_remaining("client-2") == 10

    def test_thread_safety(self):
        """Should be thread-safe for concurrent access."""
        limiter = RateLimiter(requests_per_minute=100)
        results = []

        def make_requests():
            for _ in range(50):
                results.append(limiter.is_allowed("shared-key"))

        threads = [threading.Thread(target=make_requests) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 100 should be allowed
        allowed = sum(1 for r in results if r)
        assert allowed == 100

    def test_expired_timestamps_cleaned_up(self):
        """Should clean up expired timestamps."""
        limiter = RateLimiter(requests_per_minute=5, cleanup_interval=0)

        # Fill up the bucket
        for _ in range(5):
            limiter.is_allowed("client-1")

        # Manipulate timestamps to be old
        with limiter._lock:
            limiter._buckets["client-1"] = [time.time() - 120]  # 2 minutes ago

        # Should allow requests now since old ones expired
        assert limiter.is_allowed("client-1") is True


class TestRateLimiterBypass:
    """Tests for rate limiter bypass via environment variable."""

    def test_bypasses_when_disabled(self, monkeypatch):
        """Should bypass rate limiting when globally disabled."""
        from importlib import import_module

        # Need to use import_module because the package __init__ exports a function
        rate_limit_module = import_module("aragora.server.handlers.utils.rate_limit")

        monkeypatch.setattr(rate_limit_module, "RATE_LIMITING_DISABLED", True)

        limiter = RateLimiter(requests_per_minute=1)

        # Should allow unlimited requests
        for _ in range(100):
            assert limiter.is_allowed("client-1") is True


# =============================================================================
# Test rate_limit decorator
# =============================================================================


class TestRateLimitDecorator:
    """Tests for @rate_limit decorator."""

    def test_allows_requests_under_limit(self):
        """Should allow requests under the rate limit."""

        class Handler:
            @rate_limit(rpm=5, limiter_name="test_handler_1", use_distributed=False)
            def handle(self, handler):
                return {"success": True}

        h = Handler()
        mock_handler = MagicMock()
        mock_handler.client_address = ("192.168.1.1", 12345)
        mock_handler.headers = {}

        for _ in range(5):
            result = h.handle(mock_handler)
            assert result == {"success": True}

    def test_blocks_requests_over_limit(self):
        """Should return 429 error when over limit."""

        class Handler:
            @rate_limit(rpm=3, limiter_name="test_handler_2", use_distributed=False)
            def handle(self, handler):
                return {"success": True}

        h = Handler()
        mock_handler = MagicMock()
        mock_handler.client_address = ("192.168.1.2", 12345)
        mock_handler.headers = {}

        for _ in range(3):
            h.handle(mock_handler)

        result = h.handle(mock_handler)
        assert result.status_code == 429

    def test_uses_custom_key_func(self):
        """Should use custom key function when provided."""

        class Handler:
            @rate_limit(
                rpm=2,
                key_func=lambda h: "custom-key",
                limiter_name="test_handler_3",
                use_distributed=False,
            )
            def handle(self, handler):
                return {"success": True}

        h = Handler()
        mock_handler = MagicMock()
        mock_handler.client_address = ("192.168.1.3", 12345)
        mock_handler.headers = {}

        # All requests share the same key
        h.handle(mock_handler)
        h.handle(mock_handler)

        result = h.handle(mock_handler)
        assert result.status_code == 429

    def test_async_handler_support(self):
        """Should support async handlers."""
        import asyncio

        class Handler:
            @rate_limit(rpm=2, limiter_name="test_handler_4", use_distributed=False)
            async def handle(self, handler):
                return {"success": True}

        h = Handler()
        mock_handler = MagicMock()
        mock_handler.client_address = ("192.168.1.4", 12345)
        mock_handler.headers = {}

        async def run():
            for _ in range(2):
                result = await h.handle(mock_handler)
                assert result == {"success": True}

            result = await h.handle(mock_handler)
            assert result.status_code == 429

        asyncio.run(run())

    def test_requests_per_minute_alias(self):
        """Should accept requests_per_minute as alias for rpm."""

        class Handler:
            @rate_limit(requests_per_minute=2, limiter_name="test_handler_5", use_distributed=False)
            def handle(self, handler):
                return {"success": True}

        h = Handler()
        mock_handler = MagicMock()
        mock_handler.client_address = ("192.168.1.5", 12345)
        mock_handler.headers = {}

        h.handle(mock_handler)
        h.handle(mock_handler)

        result = h.handle(mock_handler)
        assert result.status_code == 429

    def test_uses_validated_client_ip_kwarg(self):
        """Should use validated_client_ip kwarg when provided."""

        class Handler:
            @rate_limit(rpm=2, limiter_name="test_handler_6", use_distributed=False)
            def handle(self, validated_client_ip=None, headers=None):
                return {"success": True}

        h = Handler()

        # Use validated_client_ip kwarg
        h.handle(validated_client_ip="10.0.0.1", headers={})
        h.handle(validated_client_ip="10.0.0.1", headers={})

        result = h.handle(validated_client_ip="10.0.0.1", headers={})
        assert result.status_code == 429


# =============================================================================
# Test _get_limiter and clear_all_limiters
# =============================================================================


class TestLimiterRegistry:
    """Tests for limiter registry functions."""

    def test_get_limiter_creates_new(self):
        """Should create a new limiter if not exists."""
        limiter = _get_limiter("new-limiter", 60)
        assert limiter is not None
        assert limiter.rpm == 60

    def test_get_limiter_returns_existing(self):
        """Should return existing limiter if exists."""
        limiter1 = _get_limiter("existing-limiter", 60)
        limiter2 = _get_limiter("existing-limiter", 100)  # Different rpm ignored

        assert limiter1 is limiter2
        assert limiter1.rpm == 60  # Original rpm preserved

    def test_clear_all_limiters_clears_all(self):
        """Should clear all registered limiters."""
        limiter1 = _get_limiter("limiter-a", 60)
        limiter2 = _get_limiter("limiter-b", 60)

        for _ in range(30):
            limiter1.is_allowed("client")
            limiter2.is_allowed("client")

        count = clear_all_limiters()
        assert count >= 2

        # Limiters should have been cleared
        assert limiter1.get_remaining("client") == 60
        assert limiter2.get_remaining("client") == 60


# =============================================================================
# Test Multi-Instance Strict Mode
# =============================================================================


class TestStrictModeDetection:
    """Tests for automatic strict mode detection in multi-instance deployments."""

    def test_strict_mode_enabled_when_explicitly_set(self, monkeypatch):
        """Should enable strict mode when ARAGORA_RATE_LIMIT_STRICT=true."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "true")
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)

        assert _should_use_strict_mode() is True

    def test_strict_mode_disabled_when_explicitly_false(self, monkeypatch):
        """Should disable strict mode when ARAGORA_RATE_LIMIT_STRICT=false."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "false")
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")

        assert _should_use_strict_mode() is False

    def test_strict_mode_auto_enabled_in_production_multi_instance(self, monkeypatch):
        """Should auto-enable strict mode in production + multi-instance."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")

        assert _should_use_strict_mode() is True

    def test_strict_mode_disabled_in_development(self, monkeypatch):
        """Should not auto-enable strict mode in development."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "development")
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")

        assert _should_use_strict_mode() is False

    def test_strict_mode_disabled_in_single_instance(self, monkeypatch):
        """Should not auto-enable strict mode in single-instance production."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_REPLICA_COUNT", "1")

        assert _should_use_strict_mode() is False

    def test_multi_instance_detected_via_replica_count(self, monkeypatch):
        """Should detect multi-instance via ARAGORA_REPLICA_COUNT > 1."""
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_REPLICA_COUNT", "3")

        assert _should_use_strict_mode() is True
