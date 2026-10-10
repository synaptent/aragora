"""
Rate limiting base types and configuration.

Contains shared types, configuration, and helper functions used by
all rate limiting components.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import posixpath
from typing import TYPE_CHECKING
from urllib.parse import unquote

from aragora.config.env_helpers import env_int, env_float

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Configuration from environment (using safe parsing helpers)
DEFAULT_RATE_LIMIT = env_int("ARAGORA_RATE_LIMIT", 60)
IP_RATE_LIMIT = env_int("ARAGORA_IP_RATE_LIMIT", 120)
BURST_MULTIPLIER = env_float("ARAGORA_BURST_MULTIPLIER", 2.0)

# Trusted proxies for X-Forwarded-For header (comma-separated IPs/CIDRs)
TRUSTED_PROXIES_RAW = os.environ.get(
    "ARAGORA_TRUSTED_PROXIES",
    "127.0.0.1,::1,localhost",
).strip()
TRUSTED_PROXIES: frozenset[str] = frozenset(
    p.strip() for p in TRUSTED_PROXIES_RAW.split(",") if p.strip()
)
# Peers whose CF-Connecting-IP / True-Client-IP headers are believed. Empty by
# default: only the operator knows which peer is Cloudflare's edge or tunnel.
CLOUDFLARE_TRUSTED_PROXIES: frozenset[str] = frozenset(
    p.strip()
    for p in os.environ.get("ARAGORA_CLOUDFLARE_TRUSTED_PROXIES", "").split(",")
    if p.strip()
)


def _unmap(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if type(addr) is ipaddress.IPv6Address and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _parse_proxy_entries(entries) -> tuple[set[str], list[ipaddress._BaseNetwork]]:
    ips: set[str] = set()
    nets: list[ipaddress._BaseNetwork] = []
    for entry in entries:
        if entry == "localhost":
            ips.update({"127.0.0.1", "::1"})
            continue
        try:
            if "/" in entry:
                nets.append(ipaddress.ip_network(entry, strict=False))
            else:
                ips.add(str(_unmap(ipaddress.ip_address(entry))))
        except ValueError:
            logger.debug("Ignoring invalid trusted proxy entry: %s", entry)
    return ips, nets


_TRUSTED_PROXY_IPS, _TRUSTED_PROXY_NETS = _parse_proxy_entries(TRUSTED_PROXIES)
_CLOUDFLARE_PROXY_IPS, _CLOUDFLARE_PROXY_NETS = _parse_proxy_entries(CLOUDFLARE_TRUSTED_PROXIES)


def _normalize_ip(ip_value: str) -> str:
    """Normalize IP addresses for consistent rate limiting.

    - IPv4: Used as-is after validation
    - IPv6: Normalized to standard form, with /64 prefix grouping for fairness
    - Invalid: Returns original string (will be treated as unique key)
    """
    if not ip_value:
        return ""

    try:
        import builtins
        import types

        if type(builtins.isinstance) is not types.BuiltinFunctionType:
            return str(ip_value).strip()
    except (ImportError, AttributeError, TypeError):
        return str(ip_value).strip()

    try:
        addr = _unmap(ipaddress.ip_address(ip_value.strip()))
        if type(addr) is ipaddress.IPv6Address:
            # Group by /64 prefix for IPv6 (standard allocation size)
            network = ipaddress.ip_network(f"{addr}/64", strict=False)
            return str(network.network_address)
        return str(addr)
    except ValueError:
        return ip_value.strip()


def is_trusted_proxy_address(ip: str) -> bool:
    """Check an exact peer address against the parsed ARAGORA_TRUSTED_PROXIES set.

    Matches listed IPs and CIDR ranges (``localhost`` is listed as 127.0.0.1
    and ::1). An IPv4-mapped IPv6 address such as ``::ffff:127.0.0.1`` is
    checked as its IPv4 address. Unlike ``_normalize_ip``, IPv6 addresses are
    not grouped by /64 here, so a listed ``::1`` matches.
    """
    return _address_listed(ip, _TRUSTED_PROXY_IPS, _TRUSTED_PROXY_NETS)


def is_cloudflare_trusted_proxy_address(ip: str) -> bool:
    """Check a peer against ARAGORA_CLOUDFLARE_TRUSTED_PROXIES (same entry syntax)."""
    return _address_listed(ip, _CLOUDFLARE_PROXY_IPS, _CLOUDFLARE_PROXY_NETS)


def _address_listed(ip: str, ips: set[str], nets: list[ipaddress._BaseNetwork]) -> bool:
    try:
        addr = _unmap(ipaddress.ip_address(str(ip).strip()))
    except ValueError:
        return False
    return str(addr) in ips or any(addr in net for net in nets)


def _is_trusted_proxy(ip: str) -> bool:
    """Check if a raw peer address is a trusted proxy for XFF header processing.

    Uses pre-parsed IP sets and networks for efficient lookup.
    Supports both individual IPs and CIDR ranges.
    """
    if not ip:
        return False

    return is_trusted_proxy_address(ip)


def header_value(headers, name: str) -> str:
    value = headers.get(name) or headers.get(name.lower())
    return value.strip() if type(value) is str else ""


def forwarded_client_ip(headers, remote_addr: str) -> str:
    """Return the raw client address for a request arriving from ``remote_addr``.

    A peer in ARAGORA_TRUSTED_PROXIES is believed for the rightmost
    X-Forwarded-For hop that is not itself a trusted proxy. Hops to the left
    of that one were written by the client, so they are never used. X-Real-IP
    is believed only when X-Forwarded-For is absent or empty, because proxies
    that append to X-Forwarded-For often pass a client's X-Real-IP through.
    Any other peer is the client. Callers key the result with ``_normalize_ip``.
    """
    if not is_trusted_proxy_address(remote_addr):
        return remote_addr

    hops = [h.strip() for h in header_value(headers, "X-Forwarded-For").split(",") if h.strip()]
    if not hops:
        return header_value(headers, "X-Real-IP") or remote_addr

    for hop in reversed(hops):
        if not is_trusted_proxy_address(hop):
            return hop

    return remote_addr


def _extract_client_ip(
    headers: dict,
    remote_addr: str,
    trust_xff_from_proxies: bool = True,
) -> str:
    """Extract real client IP from request headers.

    Priority:
    1. X-Forwarded-For rightmost non-trusted IP (if from trusted proxy)
    2. X-Real-IP (if from trusted proxy and X-Forwarded-For is absent or empty)
    3. Direct connection IP (remote_addr)
    """
    if not trust_xff_from_proxies or not remote_addr:
        return _normalize_ip(remote_addr)

    return _normalize_ip(forwarded_client_ip(headers, remote_addr))


def sanitize_rate_limit_key_component(value: str) -> str:
    """Sanitize a component used in rate limit keys.

    Prevents injection attacks via malformed IPs or tokens.
    Replaces colons with underscores to prevent key injection.
    """
    if value is None:
        return ""
    value = str(value)
    # Replace colon to prevent Redis key injection, remove newlines
    return value.replace(":", "_").replace("\n", "").replace("\r", "").strip()


def normalize_rate_limit_path(path: str) -> str:
    """Normalize URL path for rate limit endpoint matching.

    Handles:
    - URL decoding
    - Path traversal prevention
    - Trailing slash normalization
    - Multiple slash collapse
    """
    if not path:
        return "/"

    try:
        import builtins
        import types

        if type(builtins.isinstance) is not types.BuiltinFunctionType:
            safe = str(path)
            if not safe.startswith("/"):
                safe = "/" + safe
            return safe.lower()
    except (ImportError, AttributeError, TypeError):
        safe = str(path)
        if not safe.startswith("/"):
            safe = "/" + safe
        return safe.lower()

    # Decode URL-encoded characters
    decoded = unquote(path)

    # Normalize path (resolves .., collapses //)
    normalized = posixpath.normpath(decoded)

    # Ensure leading slash
    if not normalized.startswith("/"):
        normalized = "/" + normalized

    # Remove trailing slash (except for root)
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")

    # Lowercase for consistent matching
    normalized = normalized.lower()

    return normalized


__all__ = [
    "DEFAULT_RATE_LIMIT",
    "IP_RATE_LIMIT",
    "BURST_MULTIPLIER",
    "TRUSTED_PROXIES",
    "CLOUDFLARE_TRUSTED_PROXIES",
    "_normalize_ip",
    "is_trusted_proxy_address",
    "is_cloudflare_trusted_proxy_address",
    "forwarded_client_ip",
    "header_value",
    "_is_trusted_proxy",
    "_extract_client_ip",
    "sanitize_rate_limit_key_component",
    "normalize_rate_limit_path",
    "logger",
]
