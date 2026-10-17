"""Client-IP rule of the rate-limit middleware.

A peer in ARAGORA_TRUSTED_PROXIES (exact address, CIDR, localhost, or the
IPv4-mapped form of either) is believed for the header that
ARAGORA_TRUSTED_PROXY_HEADER names: by default the rightmost X-Forwarded-For hop
that is not a trusted proxy, with X-Real-IP only when X-Forwarded-For is absent.
Only a peer in ARAGORA_CLOUDFLARE_TRUSTED_PROXIES is believed for
CF-Connecting-IP / True-Client-IP, on every middleware key path.
"""

from __future__ import annotations

import importlib
import logging

import pytest

NGINX = "127.0.0.1,::1,localhost,172.16.0.0/12"
P = "172.18.0.5"
CF = {
    "CF-RAY": "8a1b2c3d4e5f-AMS",
    "CF-Connecting-IP": "198.51.100.42",
    "True-Client-IP": "198.51.100.45",
}
FWD = {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.66, 203.0.113.8"}
REAL_IP_AND_CLIENT_XFF = {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.66"}
MULTI_HOP = {"X-Real-IP": "6.6.6.6", "X-Forwarded-For": "6.6.6.7, 203.0.113.9, 172.18.0.9"}


class _Headers:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _Handler:
    def __init__(self, peer: str, headers: dict[str, str]):
        self.client_address = (peer, 52000)
        self.headers = _Headers(dict(headers))


@pytest.fixture
def proxy_env(monkeypatch):
    """Set the proxy settings (``None`` = unset) and re-run the module's own parsing."""
    from aragora.server.middleware.rate_limit import base

    def apply(trusted: str | None = None, cloudflare: str | None = None, header=None):
        for name, value in (
            ("ARAGORA_TRUSTED_PROXIES", trusted),
            ("ARAGORA_CLOUDFLARE_TRUSTED_PROXIES", cloudflare),
            ("ARAGORA_TRUSTED_PROXY_HEADER", header),
        ):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(base)

    yield apply
    monkeypatch.undo()
    importlib.reload(base)


def _keys(peer: str, headers: dict[str, str]) -> set[str]:
    """The key each middleware path derives for one request."""
    from aragora.server.middleware.rate_limit import base
    from aragora.server.middleware.rate_limit.default_limiter import determine_auth_tier
    from aragora.server.middleware.rate_limit.limiter import RateLimiter
    from aragora.server.middleware.rate_limit.tenant_limiter import _extract_tenant_id

    handler = _Handler(peer, headers)
    return {
        base.sanitize_rate_limit_key_component(base._extract_client_ip(dict(headers), peer)),
        RateLimiter().get_client_key(handler),
        determine_auth_tier(handler)[1],
        _extract_tenant_id(handler),
    }


@pytest.mark.parametrize(
    ("header", "peer", "headers", "expected"),
    [
        (None, P, REAL_IP_AND_CLIENT_XFF, "198.51.100.66"),
        (None, P, MULTI_HOP, "203.0.113.9"),
        (None, P, {"X-Real-IP": "203.0.113.7"}, "203.0.113.7"),
        (None, P, {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": " , "}, "203.0.113.7"),
        (None, P, {"X-Forwarded-For": "172.18.0.8, 172.18.0.9"}, P),
        (None, "203.0.113.9", {"X-Real-IP": "198.51.100.69"}, "203.0.113.9"),
        ("x-real-ip", P, REAL_IP_AND_CLIENT_XFF, "203.0.113.7"),
        (" X-Real-IP ", P, MULTI_HOP, "6.6.6.6"),
        ("x-real-ip", P, {"X-Forwarded-For": "198.51.100.66"}, P),
        ("x-real-ip", "::ffff:" + P, {"X-Real-IP": "2001:db8:1:2::c"}, "2001:db8:1:2::"),
        ("bogus", P, {"X-Real-IP": "203.0.113.7"}, P),
    ],
)
def test_header_mode_picks_the_client(proxy_env, header, peer, headers, expected):
    base = proxy_env(NGINX, header=header)
    assert base._extract_client_ip(headers, peer) == expected


@pytest.mark.parametrize("peer", ["::1", "::ffff:127.0.0.1"])
def test_listed_ipv6_loopback_and_mapped_proxies_are_trusted(proxy_env, peer):
    base = proxy_env("127.0.0.1,::1")
    assert base._is_trusted_proxy(peer) is True
    assert base._extract_client_ip({"X-Real-IP": "203.0.113.7"}, peer) == "203.0.113.7"


def test_ipv4_mapped_peer_inside_a_listed_cidr_is_trusted(proxy_env):
    base = proxy_env(NGINX)
    assert base._extract_client_ip({"X-Forwarded-For": "198.51.100.43"}, "::ffff:172.18.0.1") == (
        "198.51.100.43"
    )


@pytest.mark.parametrize(
    ("peer", "headers", "key"),
    [
        ("2001:db8:1:2::a", {}, "2001:db8:1:2::"),
        ("::ffff:198.51.100.7", {}, "198.51.100.7"),
        (P, {"X-Forwarded-For": "2001:db8:1:2::b"}, "2001:db8:1:2::"),
        ("::1", {"X-Forwarded-For": "::ffff:198.51.100.7"}, "198.51.100.7"),
    ],
)
def test_keys_group_ipv6_by_64_and_unwrap_mapped_ipv4(proxy_env, peer, headers, key):
    base = proxy_env(NGINX)
    assert base._extract_client_ip(headers, peer) == key


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        ("198.18.0.1", CF, "198.51.100.42"),
        ("198.18.0.1", {**CF, "CF-Connecting-IP": ""}, "198.51.100.45"),
        ("198.18.0.1", {**CF, **FWD}, "198.51.100.42"),
        ("::ffff:198.18.0.1", CF, "198.51.100.42"),
    ],
)
def test_every_key_path_believes_cloudflare_headers_from_a_listed_peer(
    proxy_env, peer, headers, expected
):
    proxy_env("127.0.0.1", cloudflare="198.18.0.0/15")
    assert _keys(peer, headers) == {expected}


@pytest.mark.parametrize(("peer", "key"), [(P, "203.0.113.8"), ("203.0.113.9", "203.0.113.9")])
def test_every_key_path_ignores_cloudflare_headers_from_an_unlisted_peer(proxy_env, peer, key):
    proxy_env(NGINX, cloudflare="198.18.0.0/15")
    assert _keys(peer, {**CF, **FWD}) == {key}


def test_cloudflared_peer_without_the_cloudflare_list_keys_on_the_rightmost_hop(proxy_env):
    proxy_env()
    headers = {**CF, "X-Real-IP": "6.6.6.6", "X-Forwarded-For": "6.6.6.7, 198.51.100.42"}
    assert _keys("127.0.0.1", headers) == {"198.51.100.42"}


@pytest.mark.parametrize(
    ("peer", "key"), [("203.0.113.9", "203.0.113.9"), ("2001:db8::9", "2001:db8::")]
)
def test_untrusted_peer_with_forged_headers_is_keyed_on_itself(proxy_env, peer, key):
    base = proxy_env(NGINX, cloudflare="172.18.0.0/16")
    forged = {**CF, "X-Forwarded-For": "198.51.100.43", "X-Real-IP": "198.51.100.44"}
    assert base._extract_client_ip(forged, peer) == key


def test_cf_ray_from_an_unlisted_peer_warns_once_per_process(proxy_env, monkeypatch, caplog):
    base = proxy_env(NGINX)
    monkeypatch.setattr(base, "_cf_ray_warning_logged", False, raising=False)
    with caplog.at_level(logging.WARNING, logger=base.__name__):
        for peer in (P, "172.18.0.6", "203.0.113.9", P):
            base._extract_client_ip(CF, peer)
    warned = [m for m in caplog.messages if "ARAGORA_CLOUDFLARE_TRUSTED_PROXIES" in m]
    assert len(warned) == 1
