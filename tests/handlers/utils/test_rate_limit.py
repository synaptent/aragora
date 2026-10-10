"""Comprehensive tests for aragora.server.handlers.utils.rate_limit module.

Tests the rate limiting functions and classes directly:
- RateLimiter (token bucket implementation)
- _DistributedLimiterAdapter
- get_client_ip (IP extraction with proxy trust)
- _normalize_ip
- _is_multi_instance_mode / _is_redis_configured / _is_production_mode / _should_use_strict_mode
- validate_rate_limit_configuration
- rate_limit decorator (sync + async)
- auth_rate_limit decorator (sync + async)
- _get_limiter / clear_all_limiters
- RATE_LIMITING_DISABLED bypass
- TRUSTED_PROXIES configuration
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeHandler:
    """Minimal handler object for get_client_ip tests."""

    client_address: tuple[str, int] | None = None
    headers: dict[str, str] | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}


class DictHeaders:
    """Dict-like headers object that supports .get()."""

    def __init__(self, d: dict[str, str]):
        self._d = d

    def get(self, key: str, default=None):
        return self._d.get(key, default)


@dataclass
class FakeHandlerWithDictHeaders:
    """Handler using DictHeaders."""

    client_address: tuple[str, int] | None = None
    headers: DictHeaders | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_limiters():
    """Reset global limiter registry before each test."""
    from aragora.server.handlers.utils.rate_limit import _limiters, _limiters_lock

    with _limiters_lock:
        _limiters.clear()
    yield
    with _limiters_lock:
        _limiters.clear()


@pytest.fixture()
def limiter():
    """Create a fresh RateLimiter instance."""
    from aragora.server.handlers.utils.rate_limit import RateLimiter

    return RateLimiter(requests_per_minute=10, cleanup_interval=5)


@pytest.fixture()
def fast_limiter():
    """Create a limiter with very low RPM for quick tests."""
    from aragora.server.handlers.utils.rate_limit import RateLimiter

    return RateLimiter(requests_per_minute=3, cleanup_interval=1)


# ===========================================================================
# RateLimiter class tests
# ===========================================================================


class TestRateLimiterBasic:
    """Basic RateLimiter functionality."""

    def test_init_defaults(self):
        from aragora.server.handlers.utils.rate_limit import RateLimiter

        rl = RateLimiter()
        assert rl.rpm == 60
        assert rl.cleanup_interval == 300

    def test_init_custom(self):
        from aragora.server.handlers.utils.rate_limit import RateLimiter

        rl = RateLimiter(requests_per_minute=100, cleanup_interval=600)
        assert rl.rpm == 100
        assert rl.cleanup_interval == 600

    def test_requests_alias(self, limiter):
        """_requests is a backward-compatible alias for _buckets."""
        assert limiter._requests is limiter._buckets

    def test_is_allowed_under_limit(self, limiter):
        assert limiter.is_allowed("test_key") is True

    def test_is_allowed_at_limit(self, fast_limiter):
        for _ in range(3):
            assert fast_limiter.is_allowed("key") is True
        # 4th request should be blocked
        assert fast_limiter.is_allowed("key") is False

    def test_is_allowed_different_keys_independent(self, fast_limiter):
        for _ in range(3):
            fast_limiter.is_allowed("key_a")
        assert fast_limiter.is_allowed("key_a") is False
        # key_b should still be allowed
        assert fast_limiter.is_allowed("key_b") is True

    def test_is_allowed_returns_bool(self, limiter):
        result = limiter.is_allowed("k")
        assert type(result) is bool

    def test_multiple_requests_tracked(self, limiter):
        for i in range(10):
            assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is False

    def test_expired_timestamps_removed(self, fast_limiter):
        """Timestamps older than 60s are evicted on next check."""
        now = time.time()
        with fast_limiter._lock:
            fast_limiter._buckets["old_key"] = [now - 120, now - 90, now - 61]
        # The old timestamps should be pruned, allowing new requests
        assert fast_limiter.is_allowed("old_key") is True


class TestRateLimiterGetRemaining:
    """get_remaining method."""

    def test_full_remaining(self, limiter):
        assert limiter.get_remaining("fresh_key") == 10

    def test_remaining_decreases(self, limiter):
        limiter.is_allowed("k")
        assert limiter.get_remaining("k") == 9

    def test_remaining_at_zero(self, fast_limiter):
        for _ in range(3):
            fast_limiter.is_allowed("k")
        assert fast_limiter.get_remaining("k") == 0

    def test_remaining_never_negative(self, fast_limiter):
        for _ in range(10):
            fast_limiter.is_allowed("k")
        assert fast_limiter.get_remaining("k") == 0


class TestRateLimiterReset:
    """reset and clear methods."""

    def test_reset_single_key(self, fast_limiter):
        for _ in range(3):
            fast_limiter.is_allowed("k")
        assert fast_limiter.is_allowed("k") is False
        fast_limiter.reset("k")
        assert fast_limiter.is_allowed("k") is True

    def test_reset_nonexistent_key(self, limiter):
        # Should not raise
        limiter.reset("nonexistent")

    def test_clear_all(self, limiter):
        limiter.is_allowed("a")
        limiter.is_allowed("b")
        limiter.clear()
        assert limiter.get_remaining("a") == 10
        assert limiter.get_remaining("b") == 10

    def test_clear_empty(self, limiter):
        limiter.clear()  # No error


class TestRateLimiterCleanup:
    """Periodic cleanup of expired buckets."""

    def test_cleanup_removes_fully_expired(self, limiter):
        now = time.time()
        with limiter._lock:
            limiter._buckets["expired"] = [now - 200]
            limiter._buckets["active"] = [now]
            limiter._last_cleanup = now - limiter.cleanup_interval - 1

        # Trigger cleanup via is_allowed
        limiter.is_allowed("trigger")
        with limiter._lock:
            assert "expired" not in limiter._buckets
            assert "active" in limiter._buckets

    def test_cleanup_removes_empty_buckets(self, limiter):
        now = time.time()
        with limiter._lock:
            limiter._buckets["empty"] = []
            limiter._last_cleanup = now - limiter.cleanup_interval - 1

        limiter.is_allowed("trigger")
        with limiter._lock:
            assert "empty" not in limiter._buckets

    def test_no_cleanup_before_interval(self, limiter):
        now = time.time()
        with limiter._lock:
            limiter._buckets["expired"] = [now - 200]
            limiter._last_cleanup = now  # Just cleaned up

        limiter.is_allowed("trigger")
        with limiter._lock:
            # expired key should still be there (cleanup didn't fire)
            assert "expired" in limiter._buckets


class TestRateLimiterThreadSafety:
    """Concurrent access to RateLimiter."""

    def test_concurrent_is_allowed(self):
        from aragora.server.handlers.utils.rate_limit import RateLimiter

        rl = RateLimiter(requests_per_minute=100)
        results = []
        errors = []

        def worker():
            try:
                for _ in range(20):
                    results.append(rl.is_allowed("shared_key"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 100
        allowed_count = sum(1 for r in results if r)
        assert allowed_count == 100  # All should be allowed (100 RPM, 100 requests)

    def test_concurrent_exceeds_limit(self):
        from aragora.server.handlers.utils.rate_limit import RateLimiter

        rl = RateLimiter(requests_per_minute=10)
        results = []

        def worker():
            for _ in range(5):
                results.append(rl.is_allowed("shared"))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 25
        allowed = sum(1 for r in results if r)
        # At most 10 should be allowed
        assert allowed <= 10


class TestRateLimiterDisabled:
    """RATE_LIMITING_DISABLED bypass."""

    def test_disabled_always_allows(self, fast_limiter):
        with patch("aragora.server.handlers.utils.rate_limit.RATE_LIMITING_DISABLED", True):
            for _ in range(100):
                assert fast_limiter.is_allowed("k") is True


# ===========================================================================
# _normalize_ip tests
# ===========================================================================


class TestNormalizeIp:
    """IP address normalization."""

    def test_ipv4(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        assert _normalize_ip("192.168.1.1") == "192.168.1.1"

    def test_ipv6_full(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        result = _normalize_ip("::1")
        assert result == "::1"

    def test_ipv6_expanded(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        result = _normalize_ip("0000:0000:0000:0000:0000:0000:0000:0001")
        assert result == "::1"

    def test_empty_string(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        assert _normalize_ip("") == ""

    def test_invalid_ip(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        assert _normalize_ip("not-an-ip") == "not-an-ip"

    def test_whitespace_stripped(self):
        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        assert _normalize_ip("  10.0.0.1  ") == "10.0.0.1"


# ===========================================================================
# get_client_ip tests
# ===========================================================================


class TestGetClientIp:
    """Client IP extraction from handler objects."""

    def test_none_handler(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        assert get_client_ip(None) == "unknown"

    def test_basic_client_address(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(client_address=("10.0.0.5", 12345))
        assert get_client_ip(handler) == "10.0.0.5"

    def test_no_client_address(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = MagicMock(spec=[])
        assert get_client_ip(handler) == "unknown"

    def test_x_forwarded_for_trusted_proxy(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("127.0.0.1", 80),
            headers={"X-Forwarded-For": "198.51.100.66, 203.0.113.50, 127.0.0.1"},
        )
        assert get_client_ip(handler) == "203.0.113.50"

    def test_x_forwarded_for_untrusted_proxy(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("10.99.99.99", 80),
            headers={"X-Forwarded-For": "203.0.113.50"},
        )
        # Untrusted proxy: should return the direct IP, not the forwarded one
        assert get_client_ip(handler) == "10.99.99.99"

    def test_x_real_ip_trusted_proxy(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("127.0.0.1", 80),
            headers={"X-Real-IP": "198.51.100.1"},
        )
        assert get_client_ip(handler) == "198.51.100.1"

    def test_cloudflare_cf_connecting_ip(self, proxy_env):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        proxy_env(cloudflare="172.16.0.1")
        handler = FakeHandler(
            client_address=("172.16.0.1", 80),
            headers={
                "CF-RAY": "abc123",
                "CF-Connecting-IP": "198.51.100.42",
            },
        )
        assert get_client_ip(handler) == "198.51.100.42"

    def test_cloudflare_true_client_ip(self, proxy_env):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        proxy_env(cloudflare="172.16.0.1")
        handler = FakeHandler(
            client_address=("172.16.0.1", 80),
            headers={
                "CF-RAY": "abc123",
                "True-Client-IP": "198.51.100.43",
            },
        )
        assert get_client_ip(handler) == "198.51.100.43"

    def test_cloudflare_without_cf_ray_ignored(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("10.0.0.1", 80),
            headers={"CF-Connecting-IP": "198.51.100.42"},
        )
        # Without CF-RAY, CF-Connecting-IP should NOT be trusted
        assert get_client_ip(handler) == "10.0.0.1"

    def test_handler_with_dict_headers(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        h = FakeHandlerWithDictHeaders(
            client_address=("127.0.0.1", 80),
            headers=DictHeaders({"X-Forwarded-For": "1.2.3.4"}),
        )
        assert get_client_ip(h) == "1.2.3.4"

    def test_client_address_not_tuple(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = MagicMock()
        handler.client_address = "10.0.0.1"  # string, not tuple
        handler.headers = {}
        # type(client_address) is tuple check fails, should return "unknown" or similar
        result = get_client_ip(handler)
        # Should fall through to "unknown" since client_address is not a real tuple
        assert isinstance(result, str)

    def test_lowercase_header_variants(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("127.0.0.1", 80),
            headers={"x-forwarded-for": "5.6.7.8"},
        )
        assert get_client_ip(handler) == "5.6.7.8"

    def test_ipv6_client(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(client_address=("::1", 80))
        assert get_client_ip(handler) == "::1"

    def test_trusted_proxy_ipv6_loopback(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=("::1", 80),
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        assert get_client_ip(handler) == "203.0.113.1"


class TestGetClientIpCloudflareTrust:
    """Cloudflare client-IP headers count only when the direct peer is a trusted proxy."""

    UNTRUSTED_PEER = "203.0.113.9"

    @pytest.mark.parametrize(
        "client_header",
        ["CF-Connecting-IP", "cf-connecting-ip", "True-Client-IP", "true-client-ip"],
    )
    def test_forged_cloudflare_headers_from_untrusted_peer_key_on_peer(self, client_header):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=(self.UNTRUSTED_PEER, 443),
            headers={"CF-RAY": "8a1b2c3d4e5f-AMS", client_header: "198.51.100.42"},
        )
        assert get_client_ip(handler) == self.UNTRUSTED_PEER

    def test_forged_cloudflare_headers_do_not_bypass_xff_rule(self):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=(self.UNTRUSTED_PEER, 443),
            headers={
                "CF-RAY": "8a1b2c3d4e5f-AMS",
                "CF-Connecting-IP": "198.51.100.42",
                "X-Forwarded-For": "198.51.100.43",
            },
        )
        assert get_client_ip(handler) == self.UNTRUSTED_PEER

    def test_rotating_forged_cf_ip_shares_one_rate_limit_bucket(self, monkeypatch):
        import sys

        from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip

        # The package re-exports a `rate_limit` decorator that shadows the submodule name.
        rl_module = sys.modules["aragora.server.handlers.utils.rate_limit"]
        monkeypatch.setattr(rl_module, "RATE_LIMITING_DISABLED", False)
        limiter = RateLimiter(requests_per_minute=2)
        allowed = [
            limiter.is_allowed(
                get_client_ip(
                    FakeHandler(
                        client_address=(self.UNTRUSTED_PEER, 443),
                        headers={"CF-RAY": "x", "CF-Connecting-IP": f"198.51.100.{n}"},
                    )
                )
            )
            for n in range(1, 6)
        ]
        assert allowed == [True, True, False, False, False]

    @pytest.mark.parametrize(
        ("client_header", "expected"),
        [("CF-Connecting-IP", "198.51.100.42"), ("True-Client-IP", "198.51.100.43")],
    )
    def test_cloudflare_headers_from_listed_loopback_proxy_honoured(
        self, proxy_env, client_header, expected
    ):
        proxy_env(cloudflare="localhost")
        headers = {"CF-RAY": "8a1b2c3d4e5f-AMS", client_header: expected}
        assert _client_ip("127.0.0.1", headers) == expected

    def test_cf_connecting_ip_preferred_over_forwarding_headers_from_listed_proxy(self, proxy_env):
        proxy_env("127.0.0.1,172.18.0.1", cloudflare="172.18.0.1")
        headers = {
            "CF-RAY": "8a1b2c3d4e5f-AMS",
            "CF-Connecting-IP": "198.51.100.42",
            "X-Forwarded-For": "198.51.100.43, 172.70.1.1",
            "X-Real-IP": "198.51.100.44",
        }
        assert _client_ip("172.18.0.1", headers) == "198.51.100.42"

    @pytest.mark.parametrize(
        ("peer", "expected"),
        [("127.0.0.1", "198.51.100.43"), ("203.0.113.9", "203.0.113.9")],
    )
    def test_xff_without_cf_ray_unchanged(self, peer, expected):
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = FakeHandler(
            client_address=(peer, 52000),
            headers={"CF-Connecting-IP": "198.51.100.42", "X-Forwarded-For": "198.51.100.43"},
        )
        assert get_client_ip(handler) == expected


@pytest.fixture
def proxy_env(monkeypatch):
    """Set the proxy settings in the environment and re-run the module's own parsing.

    ``None`` leaves a setting unset, so the module default applies.
    """
    import importlib

    from aragora.server.middleware.rate_limit import base as rl_base

    def apply(trusted: str | None = None, cloudflare: str | None = None) -> None:
        for name, value in (
            ("ARAGORA_TRUSTED_PROXIES", trusted),
            ("ARAGORA_CLOUDFLARE_TRUSTED_PROXIES", cloudflare),
        ):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        importlib.reload(rl_base)

    yield apply
    monkeypatch.undo()
    importlib.reload(rl_base)


def _client_ip(peer: str, headers: dict[str, str]) -> str:
    from aragora.server.handlers.utils.rate_limit import get_client_ip

    return get_client_ip(FakeHandler(client_address=(peer, 52000), headers=dict(headers)))


class TestGetClientIpParsedTrustedProxies:
    """One client-IP rule for the handler helper and the middleware.

    A peer in ARAGORA_TRUSTED_PROXIES (IPs, CIDR ranges, localhost) is believed
    for X-Real-IP, then the rightmost X-Forwarded-For hop that is not a trusted
    proxy; only a peer in ARAGORA_CLOUDFLARE_TRUSTED_PROXIES is believed for
    the Cloudflare headers.
    """

    # The shipped nginx stack: CIDR-listed proxy, X-Real-IP $remote_addr,
    # X-Forwarded-For appended to whatever the client sent.
    NGINX = "127.0.0.1,::1,localhost,172.16.0.0/12"
    CF = {
        "CF-RAY": "8a1b2c3d4e5f-AMS",
        "CF-Connecting-IP": "198.51.100.42",
        "True-Client-IP": "198.51.100.45",
    }
    FORGED = {**CF, "X-Forwarded-For": "198.51.100.43", "X-Real-IP": "198.51.100.44"}

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            ({"X-Forwarded-For": "198.51.100.43, 172.18.0.1"}, "198.51.100.43"),
            ({"X-Real-IP": "198.51.100.44"}, "198.51.100.44"),
        ],
    )
    def test_cidr_listed_peer_forwarded_headers_honoured(self, proxy_env, headers, expected):
        proxy_env(self.NGINX)
        assert _client_ip("172.18.0.1", headers) == expected

    def test_nginx_peer_keys_on_x_real_ip_not_the_forged_xff_entry(self, proxy_env):
        proxy_env(self.NGINX)
        headers = {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.66, 203.0.113.7"}
        assert _client_ip("172.18.0.5", headers) == "203.0.113.7"

    def test_xff_without_x_real_ip_keys_on_rightmost_untrusted_hop(self, proxy_env):
        proxy_env(self.NGINX)
        headers = {"X-Forwarded-For": "198.51.100.66, 203.0.113.7, 172.18.0.9"}
        assert _client_ip("172.18.0.5", headers) == "203.0.113.7"

    @pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "172.18.0.5"])
    def test_trusted_peer_outside_cloudflare_list_ignores_cf_headers(self, proxy_env, peer):
        proxy_env(self.NGINX)
        assert _client_ip(peer, self.CF) == peer
        assert _client_ip(peer, {**self.CF, "X-Real-IP": "203.0.113.7"}) == "203.0.113.7"

    @pytest.mark.parametrize("peer", ["172.18.0.2", "::ffff:172.18.0.2", "::1"])
    def test_cloudflare_listed_peer_keys_on_cf_connecting_ip(self, proxy_env, peer):
        proxy_env("127.0.0.1", cloudflare="localhost,172.18.0.0/16")
        assert _client_ip(peer, {**self.CF, "X-Real-IP": "203.0.113.7"}) == "198.51.100.42"

    @pytest.mark.parametrize("peer", ["::ffff:127.0.0.1", "::ffff:172.18.0.1"])
    def test_ipv4_mapped_peer_is_trusted(self, proxy_env, peer):
        proxy_env(self.NGINX)
        assert _client_ip(peer, {"X-Forwarded-For": "198.51.100.43"}) == "198.51.100.43"
        assert _client_ip(peer, {"X-Real-IP": "198.51.100.44"}) == "198.51.100.44"

    @pytest.mark.parametrize(
        "peer", ["203.0.113.9", "10.0.0.1", "::ffff:203.0.113.9", "2001:db8::9"]
    )
    def test_untrusted_peer_forged_headers_key_on_peer(self, proxy_env, peer):
        import ipaddress

        proxy_env(self.NGINX, cloudflare="172.18.0.0/16")
        assert _client_ip(peer, self.FORGED) == str(ipaddress.ip_address(peer))

    def test_cf_ray_from_unlisted_peer_warns_once_per_process(self, proxy_env, monkeypatch, caplog):
        import logging
        import sys

        rl_module = sys.modules["aragora.server.handlers.utils.rate_limit"]
        monkeypatch.setattr(rl_module, "_cf_ray_warning_logged", False, raising=False)
        proxy_env(self.NGINX)
        with caplog.at_level(logging.WARNING, logger=rl_module.__name__):
            for peer in ("172.18.0.5", "172.18.0.6", "203.0.113.9", "172.18.0.5"):
                _client_ip(peer, self.CF)
        warned = [
            r for r in caplog.records if "ARAGORA_CLOUDFLARE_TRUSTED_PROXIES" in r.getMessage()
        ]
        assert len(warned) == 1

    @pytest.mark.parametrize("peer", ["::1", "::ffff:127.0.0.1"])
    def test_middleware_trusts_listed_ipv6_loopback_and_mapped_proxies(self, proxy_env, peer):
        proxy_env("127.0.0.1,::1")
        from aragora.server.middleware.rate_limit.base import _extract_client_ip, _is_trusted_proxy

        assert _is_trusted_proxy(peer) is True
        assert _extract_client_ip({"X-Real-IP": "203.0.113.7"}, peer) == "203.0.113.7"

    @pytest.mark.parametrize(
        ("peer", "headers"),
        [
            ("172.18.0.5", {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.66"}),
            ("172.18.0.5", {"X-Forwarded-For": "198.51.100.66, 203.0.113.7, 172.18.0.9"}),
            ("172.18.0.5", {"X-Forwarded-For": "172.18.0.8, 172.18.0.9"}),
            ("203.0.113.9", {"X-Real-IP": "198.51.100.69"}),
        ],
    )
    def test_middleware_derives_the_same_client(self, proxy_env, peer, headers):
        proxy_env(self.NGINX)
        from aragora.server.middleware.rate_limit.base import _extract_client_ip

        assert _extract_client_ip(headers, peer) == _client_ip(peer, headers)


# ===========================================================================
# Multi-instance detection / env checks
# ===========================================================================


class TestIsMultiInstanceMode:
    """_is_multi_instance_mode environment detection."""

    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.delenv("ARAGORA_REPLICA_COUNT", raising=False)
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is False

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is True

    def test_explicit_1(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "1")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is True

    def test_explicit_yes(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "yes")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is True

    def test_replica_count_2(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_REPLICA_COUNT", "2")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is True

    def test_replica_count_1(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_REPLICA_COUNT", "1")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is False

    def test_replica_count_invalid(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_REPLICA_COUNT", "abc")
        from aragora.server.handlers.utils.rate_limit import _is_multi_instance_mode

        assert _is_multi_instance_mode() is False


class TestIsRedisConfigured:
    """_is_redis_configured environment detection."""

    def test_no_redis(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        from aragora.server.handlers.utils.rate_limit import _is_redis_configured

        assert _is_redis_configured() is False

    def test_redis_url(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        from aragora.server.handlers.utils.rate_limit import _is_redis_configured

        assert _is_redis_configured() is True

    def test_aragora_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("ARAGORA_REDIS_URL", "redis://localhost:6379")
        from aragora.server.handlers.utils.rate_limit import _is_redis_configured

        assert _is_redis_configured() is True

    def test_empty_redis_url(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        from aragora.server.handlers.utils.rate_limit import _is_redis_configured

        assert _is_redis_configured() is False

    def test_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "   ")
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        from aragora.server.handlers.utils.rate_limit import _is_redis_configured

        assert _is_redis_configured() is False


class TestIsProductionMode:
    """_is_production_mode environment detection."""

    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.delenv("NODE_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is False

    def test_aragora_env_production(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "production")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is True

    def test_aragora_env_prod(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "prod")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is True

    def test_node_env_production(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.setenv("NODE_ENV", "production")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is True

    def test_environment_prod(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.delenv("NODE_ENV", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "prod")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is True

    def test_development_mode(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "development")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is False

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "PRODUCTION")
        from aragora.server.handlers.utils.rate_limit import _is_production_mode

        assert _is_production_mode() is True


class TestShouldUseStrictMode:
    """_should_use_strict_mode logic."""

    def test_explicit_true(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "true")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is True

    def test_explicit_false(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "false")
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is False

    def test_auto_production_multi_instance(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is True

    def test_production_single_instance(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.delenv("ARAGORA_REPLICA_COUNT", raising=False)
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is False

    def test_dev_multi_instance(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.delenv("NODE_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is False

    def test_explicit_1(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "1")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is True

    def test_explicit_0(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "0")
        from aragora.server.handlers.utils.rate_limit import _should_use_strict_mode

        assert _should_use_strict_mode() is False


# ===========================================================================
# validate_rate_limit_configuration
# ===========================================================================


class TestValidateRateLimitConfiguration:
    """Configuration validation for multi-instance deployments."""

    def test_single_instance_ok(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.delenv("ARAGORA_REPLICA_COUNT", raising=False)
        from aragora.server.handlers.utils.rate_limit import validate_rate_limit_configuration

        # Should not raise or log critical
        validate_rate_limit_configuration()

    def test_multi_instance_with_redis_ok(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        from aragora.server.handlers.utils.rate_limit import validate_rate_limit_configuration

        validate_rate_limit_configuration()

    def test_multi_instance_strict_no_redis_raises(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "true")
        from aragora.server.handlers.utils.rate_limit import validate_rate_limit_configuration

        with pytest.raises(RuntimeError, match="Multi-instance deployment detected"):
            validate_rate_limit_configuration()

    def test_multi_instance_no_strict_no_redis_warns(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        monkeypatch.delenv("ARAGORA_RATE_LIMIT_STRICT", raising=False)
        monkeypatch.delenv("ARAGORA_ENV", raising=False)
        monkeypatch.delenv("NODE_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        from aragora.server.handlers.utils.rate_limit import validate_rate_limit_configuration

        # Should not raise, just log
        validate_rate_limit_configuration()

    def test_production_multi_instance_no_redis_logs_critical(self, monkeypatch, caplog):
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        # Auto-strict would be enabled, but explicit setting overrides
        monkeypatch.setenv("ARAGORA_RATE_LIMIT_STRICT", "false")
        import logging
        from aragora.server.handlers.utils.rate_limit import validate_rate_limit_configuration

        with caplog.at_level(logging.CRITICAL):
            validate_rate_limit_configuration()
        assert "CRITICAL" in caplog.text or "Multi-instance" in caplog.text


# ===========================================================================
# _get_limiter and clear_all_limiters
# ===========================================================================


class TestGetLimiter:
    """Named limiter registry."""

    def test_creates_new_limiter(self):
        from aragora.server.handlers.utils.rate_limit import _get_limiter

        lim = _get_limiter("test_ep", 30)
        assert lim.rpm == 30

    def test_returns_same_instance(self):
        from aragora.server.handlers.utils.rate_limit import _get_limiter

        lim1 = _get_limiter("ep", 30)
        lim2 = _get_limiter("ep", 30)
        assert lim1 is lim2

    def test_different_names_different_instances(self):
        from aragora.server.handlers.utils.rate_limit import _get_limiter

        lim1 = _get_limiter("ep1", 30)
        lim2 = _get_limiter("ep2", 30)
        assert lim1 is not lim2


class TestClearAllLimiters:
    """clear_all_limiters utility."""

    def test_returns_count(self):
        from aragora.server.handlers.utils.rate_limit import _get_limiter, clear_all_limiters

        _get_limiter("a", 10)
        _get_limiter("b", 10)
        count = clear_all_limiters()
        assert count == 2

    def test_clears_buckets(self):
        from aragora.server.handlers.utils.rate_limit import _get_limiter, clear_all_limiters

        lim = _get_limiter("ep", 5)
        for _ in range(5):
            lim.is_allowed("k")
        assert lim.is_allowed("k") is False
        clear_all_limiters()
        assert lim.is_allowed("k") is True

    def test_returns_zero_when_empty(self):
        from aragora.server.handlers.utils.rate_limit import clear_all_limiters

        assert clear_all_limiters() == 0


# ===========================================================================
# _DistributedLimiterAdapter
# ===========================================================================


class TestDistributedLimiterAdapter:
    """Adapter wrapping DistributedRateLimiter with RateLimiter-like API."""

    def test_is_allowed_delegates(self):
        from aragora.server.handlers.utils.rate_limit import _DistributedLimiterAdapter

        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=True, remaining=9)

        adapter = _DistributedLimiterAdapter(mock_limiter, "/api/test", 10)
        assert adapter.is_allowed("1.2.3.4") is True
        mock_limiter.allow.assert_called_with(client_ip="1.2.3.4", endpoint="/api/test")

    def test_is_allowed_denied(self):
        from aragora.server.handlers.utils.rate_limit import _DistributedLimiterAdapter

        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=False, remaining=0)

        adapter = _DistributedLimiterAdapter(mock_limiter, "/api/test", 10)
        assert adapter.is_allowed("1.2.3.4") is False

    def test_get_remaining_delegates(self):
        from aragora.server.handlers.utils.rate_limit import _DistributedLimiterAdapter

        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=True, remaining=7)

        adapter = _DistributedLimiterAdapter(mock_limiter, "/api/test", 10)
        assert adapter.get_remaining("1.2.3.4") == 7

    def test_rpm_attribute(self):
        from aragora.server.handlers.utils.rate_limit import _DistributedLimiterAdapter

        mock_limiter = MagicMock()
        adapter = _DistributedLimiterAdapter(mock_limiter, "/ep", 42)
        assert adapter.rpm == 42


# ===========================================================================
# rate_limit decorator
# ===========================================================================


class TestRateLimitDecorator:
    """The @rate_limit decorator for handler methods."""

    def test_sync_function_allowed(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_sync_allowed")
        def my_handler(handler):
            return "ok"

        mock = FakeHandler(client_address=("10.0.0.1", 80))
        result = my_handler(mock)
        assert result == "ok"

    def test_sync_function_blocked(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_sync_blocked")
        def my_handler(handler):
            return "ok"

        mock = FakeHandler(client_address=("10.0.0.2", 80))
        my_handler(mock)
        my_handler(mock)
        result = my_handler(mock)
        # Should be a 429 error response
        assert result != "ok"
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_async_function_allowed(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_async_allowed")
        async def my_handler(handler):
            return "async_ok"

        mock = FakeHandler(client_address=("10.0.0.3", 80))
        result = asyncio.run(my_handler(mock))
        assert result == "async_ok"

    def test_async_function_blocked(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_async_blocked")
        async def my_handler(handler):
            return "async_ok"

        mock = FakeHandler(client_address=("10.0.0.4", 80))

        async def run_all():
            await my_handler(mock)
            await my_handler(mock)
            return await my_handler(mock)

        result = asyncio.run(run_all())
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_requests_per_minute_alias(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(requests_per_minute=2, use_distributed=False, limiter_name="test_rpm_alias")
        def my_handler(handler):
            return "ok"

        mock = FakeHandler(client_address=("10.0.0.5", 80))
        my_handler(mock)
        my_handler(mock)
        result = my_handler(mock)
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_custom_key_func(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(
            rpm=2,
            key_func=lambda h: "static_key",
            use_distributed=False,
            limiter_name="test_keyfunc",
        )
        def my_handler(handler):
            return "ok"

        mock1 = FakeHandler(client_address=("10.0.0.1", 80))
        mock2 = FakeHandler(client_address=("10.0.0.2", 80))
        my_handler(mock1)
        my_handler(mock2)
        # Both share the same key, so 3rd call blocked
        result = my_handler(mock1)
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_rate_limited_attribute_set(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_attr")
        def my_handler(handler):
            return "ok"

        assert getattr(my_handler, "_rate_limited") is True
        assert getattr(my_handler, "_rate_limiter") is not None

    def test_rate_limited_attribute_on_async(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_attr_async")
        async def my_handler(handler):
            return "ok"

        assert getattr(my_handler, "_rate_limited") is True

    def test_wraps_preserves_name(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_wraps")
        def my_special_handler(handler):
            """My docstring."""
            return "ok"

        assert my_special_handler.__name__ == "my_special_handler"
        assert my_special_handler.__doc__ == "My docstring."

    def test_different_ips_independent_limits(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_indep")
        def my_handler(handler):
            return "ok"

        h1 = FakeHandler(client_address=("1.1.1.1", 80))
        h2 = FakeHandler(client_address=("2.2.2.2", 80))
        my_handler(h1)
        my_handler(h1)
        assert my_handler(h1).status_code == 429
        # h2 should still be fine
        assert my_handler(h2) == "ok"

    def test_limiter_name_shared(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=3, use_distributed=False, limiter_name="shared_limiter_1")
        def handler_a(handler):
            return "a"

        @rate_limit(rpm=3, use_distributed=False, limiter_name="shared_limiter_1")
        def handler_b(handler):
            return "b"

        h = FakeHandler(client_address=("3.3.3.3", 80))
        handler_a(h)
        handler_a(h)
        handler_b(h)
        # 4th call should be blocked since they share the limiter
        result = handler_a(h)
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_kwargs_validated_client_ip(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_kwarg_ip")
        def my_handler(**kwargs):
            return "ok"

        my_handler(validated_client_ip="9.9.9.9")
        my_handler(validated_client_ip="9.9.9.9")
        result = my_handler(validated_client_ip="9.9.9.9")
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_kwargs_headers_fallback(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_headers_fb")
        def my_handler(**kwargs):
            return "ok"

        headers = {"User-Agent": "TestBot/1.0", "Accept-Language": "en"}
        my_handler(headers=headers)
        my_handler(headers=headers)
        result = my_handler(headers=headers)
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_kwargs_unknown_fallback(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_unknown_fb")
        def my_handler(**kwargs):
            return "ok"

        # No handler, no validated_client_ip, no headers => "unknown"
        my_handler()
        my_handler()
        result = my_handler()
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_distributed_flag_attribute(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, limiter_name="test_dist_flag_false")
        def handler_local(handler):
            return "ok"

        assert getattr(handler_local, "_rate_limit_distributed") is False

    def test_key_func_with_kwargs_pattern(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(
            rpm=2,
            key_func=lambda kw: kw.get("user_id", "anon"),
            use_distributed=False,
            limiter_name="test_keyfunc_kw",
        )
        def my_handler(**kwargs):
            return "ok"

        my_handler(user_id="u1")
        my_handler(user_id="u1")
        result = my_handler(user_id="u1")
        assert hasattr(result, "status_code")
        assert result.status_code == 429
        # Different user still allowed
        assert my_handler(user_id="u2") == "ok"


class TestRateLimitDecoratorTenantAware:
    """Tenant-aware rate limiting via the decorator."""

    def test_tenant_id_from_kwargs(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=10, use_distributed=False, tenant_aware=True, limiter_name="test_tenant_kw")
        def my_handler(handler, **kwargs):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        result = my_handler(h, tenant_id="t1")
        assert result == "ok"

    def test_tenant_id_from_handler_attr(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(
            rpm=10, use_distributed=False, tenant_aware=True, limiter_name="test_tenant_attr"
        )
        def my_handler(handler):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        h.tenant_id = "tenant-abc"  # type: ignore[attr-defined]
        result = my_handler(h)
        assert result == "ok"

    def test_tenant_id_from_header(self):
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(
            rpm=10, use_distributed=False, tenant_aware=True, limiter_name="test_tenant_hdr"
        )
        def my_handler(handler):
            return "ok"

        h = FakeHandler(
            client_address=("10.0.0.1", 80),
            headers={"X-Tenant-ID": "tenant-xyz"},
        )
        result = my_handler(h)
        assert result == "ok"


# ===========================================================================
# auth_rate_limit decorator
# ===========================================================================


class TestAuthRateLimitDecorator:
    """The @auth_rate_limit decorator for authentication endpoints."""

    def test_sync_allowed(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=5, limiter_name="test_auth_sync")
        def login(handler):
            return "logged_in"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        assert login(h) == "logged_in"

    def test_sync_blocked(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_sync_blocked")
        def login(handler):
            return "logged_in"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        login(h)
        login(h)
        result = login(h)
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_async_allowed(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=5, limiter_name="test_auth_async")
        async def login(handler):
            return "async_logged_in"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        result = asyncio.run(login(h))
        assert result == "async_logged_in"

    def test_async_blocked(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_async_blocked")
        async def login(handler):
            return "async_logged_in"

        h = FakeHandler(client_address=("10.0.0.1", 80))

        async def run_all():
            await login(h)
            await login(h)
            return await login(h)

        result = asyncio.run(run_all())
        assert hasattr(result, "status_code")
        assert result.status_code == 429

    def test_requests_per_minute_alias(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(requests_per_minute=2, limiter_name="test_auth_rpm_alias")
        def login(handler):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        login(h)
        login(h)
        result = login(h)
        assert result.status_code == 429

    def test_error_message_auth_specific(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit
        import json as json_mod

        @auth_rate_limit(rpm=1, limiter_name="test_auth_msg")
        def login(handler):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        login(h)
        result = login(h)
        body = json_mod.loads(result.body)
        assert (
            "authentication" in body.get("error", "").lower()
            or "auth" in body.get("error", "").lower()
        )

    def test_rate_limited_attribute(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=5, limiter_name="test_auth_attr")
        def login(handler):
            return "ok"

        assert getattr(login, "_rate_limited") is True

    def test_custom_key_func(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(
            rpm=2,
            key_func=lambda h: "fixed_auth_key",
            limiter_name="test_auth_keyfunc",
        )
        def login(handler):
            return "ok"

        h1 = FakeHandler(client_address=("1.1.1.1", 80))
        h2 = FakeHandler(client_address=("2.2.2.2", 80))
        login(h1)
        login(h2)
        result = login(h1)
        assert result.status_code == 429

    def test_endpoint_name_in_logs(self, caplog):
        import logging
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=1, limiter_name="test_auth_epname", endpoint_name="SSO Login")
        def login(handler):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        with caplog.at_level(logging.WARNING):
            login(h)
            login(h)
        assert "SSO Login" in caplog.text

    def test_validated_client_ip_kwarg(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_valip")
        def login(**kwargs):
            return "ok"

        login(validated_client_ip="8.8.8.8")
        login(validated_client_ip="8.8.8.8")
        result = login(validated_client_ip="8.8.8.8")
        assert result.status_code == 429

    def test_headers_hash_fallback(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_headers_hash")
        def login(**kwargs):
            return "ok"

        headers = {"User-Agent": "AuthBot/1.0"}
        login(headers=headers)
        login(headers=headers)
        result = login(headers=headers)
        assert result.status_code == 429

    def test_unknown_fallback(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_unknown")
        def login(**kwargs):
            return "ok"

        login()
        login()
        result = login()
        assert result.status_code == 429

    def test_security_audit_logging(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=1, limiter_name="test_auth_audit_log")
        def login(handler):
            return "ok"

        h = FakeHandler(client_address=("10.0.0.1", 80))
        login(h)
        # The security event log should be attempted (we don't need to verify
        # audit_security call, just that it doesn't crash)
        result = login(h)
        assert result.status_code == 429

    def test_wraps_preserves_name(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=5, limiter_name="test_auth_wraps")
        def my_login_endpoint(handler):
            """Login endpoint docstring."""
            return "ok"

        assert my_login_endpoint.__name__ == "my_login_endpoint"
        assert my_login_endpoint.__doc__ == "Login endpoint docstring."

    def test_different_ips_separate_limits(self):
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        @auth_rate_limit(rpm=2, limiter_name="test_auth_sep_ip")
        def login(handler):
            return "ok"

        h1 = FakeHandler(client_address=("1.1.1.1", 80))
        h2 = FakeHandler(client_address=("2.2.2.2", 80))
        login(h1)
        login(h1)
        assert login(h1).status_code == 429
        assert login(h2) == "ok"

    def test_bound_method_uses_handler_arg_not_self(self):
        """Auth decorators on bound methods should key on handler arg."""
        from aragora.server.handlers.utils.rate_limit import auth_rate_limit

        class AuthLike:
            @auth_rate_limit(rpm=1, limiter_name="test_auth_bound_method_ip")
            def login(self, handler):
                return "ok"

        auth_like = AuthLike()
        h1 = FakeHandler(client_address=("1.1.1.1", 80))
        h2 = FakeHandler(client_address=("2.2.2.2", 80))

        assert auth_like.login(h1) == "ok"
        # Different IP should not be throttled by h1's prior call.
        assert auth_like.login(h2) == "ok"


# ===========================================================================
# Edge cases and integration
# ===========================================================================


class TestEdgeCases:
    """Edge cases and integration behavior."""

    def test_empty_key(self, limiter):
        """Empty string key should work."""
        assert limiter.is_allowed("") is True

    def test_very_long_key(self, limiter):
        key = "x" * 10000
        assert limiter.is_allowed(key) is True

    def test_unicode_key(self, limiter):
        assert limiter.is_allowed("user@example.com") is True

    def test_get_remaining_unknown_key(self, limiter):
        assert limiter.get_remaining("never_seen") == 10

    def test_rate_limit_decorator_no_args_handler(self):
        """Handler with no arguments at all should still work (unknown key)."""
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=100, use_distributed=False, limiter_name="test_no_args")
        def my_handler():
            return "no_args"

        assert my_handler() == "no_args"

    def test_rate_limit_handler_in_later_arg(self):
        """If the first arg doesn't look like a handler, scan all args."""
        from aragora.server.handlers.utils.rate_limit import rate_limit

        @rate_limit(rpm=2, use_distributed=False, limiter_name="test_later_arg")
        def my_handler(self_obj, handler):
            return "ok"

        self_mock = MagicMock(spec=[])  # No .headers
        h = FakeHandler(client_address=("10.0.0.1", 80))
        assert my_handler(self_mock, h) == "ok"

    def test_normalize_ip_ipv4_mapped_ipv6(self):
        import ipaddress

        from aragora.server.handlers.utils.rate_limit import _normalize_ip

        # IPv4-mapped IPv6 addresses get normalized by Python's ipaddress module
        result = _normalize_ip("::ffff:192.168.1.1")
        # Accept semantically equivalent textual forms across runtimes/plugins.
        assert ipaddress.ip_address(result) == ipaddress.ip_address("::ffff:192.168.1.1")

    def test_get_client_ip_no_headers_attr(self):
        """Handler without headers attribute."""
        from aragora.server.handlers.utils.rate_limit import get_client_ip

        handler = MagicMock(spec=["client_address"])
        handler.client_address = ("5.5.5.5", 80)
        result = get_client_ip(handler)
        # Should use client_address since no headers to inspect
        assert result == "5.5.5.5"

    def test_self_obj_instance_key(self):
        """When no handler is found, uses instance-based key."""
        from aragora.server.handlers.utils.rate_limit import rate_limit

        class MyHandler:
            @rate_limit(rpm=100, use_distributed=False, limiter_name="test_self_inst")
            def handle(self):
                return "self_ok"

        h = MyHandler()
        result = h.handle()
        assert result == "self_ok"


class TestModuleExports:
    """Verify module-level exports and re-exports."""

    def test_all_exports(self):
        import sys

        rl_module = sys.modules["aragora.server.handlers.utils.rate_limit"]
        assert hasattr(rl_module, "RateLimiter")
        assert hasattr(rl_module, "rate_limit")
        assert hasattr(rl_module, "auth_rate_limit")
        assert hasattr(rl_module, "get_client_ip")
        assert hasattr(rl_module, "clear_all_limiters")
        assert hasattr(rl_module, "validate_rate_limit_configuration")
        assert hasattr(rl_module, "middleware_rate_limit")
        assert hasattr(rl_module, "RateLimitResult")
        assert hasattr(rl_module, "rate_limit_headers")
        assert hasattr(rl_module, "get_distributed_limiter")
        assert hasattr(rl_module, "DistributedRateLimiter")
        assert hasattr(rl_module, "USE_DISTRIBUTED_LIMITER")

    def test_rate_limiting_disabled_attr(self):
        import sys

        rl_module = sys.modules["aragora.server.handlers.utils.rate_limit"]
        assert hasattr(rl_module, "RATE_LIMITING_DISABLED")
        assert isinstance(rl_module.RATE_LIMITING_DISABLED, bool)

    def test_trusted_proxies_attr(self):
        import sys

        rl_module = sys.modules["aragora.server.handlers.utils.rate_limit"]
        assert hasattr(rl_module, "TRUSTED_PROXIES")
        assert isinstance(rl_module.TRUSTED_PROXIES, frozenset)


class TestTrustedProxiesDefault:
    """Default TRUSTED_PROXIES values."""

    def test_default_includes_loopback(self):
        from aragora.server.handlers.utils.rate_limit import TRUSTED_PROXIES

        assert "127.0.0.1" in TRUSTED_PROXIES

    def test_default_includes_ipv6_loopback(self):
        from aragora.server.handlers.utils.rate_limit import TRUSTED_PROXIES

        assert "::1" in TRUSTED_PROXIES

    def test_default_includes_localhost(self):
        from aragora.server.handlers.utils.rate_limit import TRUSTED_PROXIES

        assert "localhost" in TRUSTED_PROXIES
