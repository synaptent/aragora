"""Request client-IP extraction with trusted-proxy handling."""

from __future__ import annotations

import ipaddress
import os
from typing import Any


def _get_trusted_proxy_cidrs() -> list[str]:
    """Return configured trusted proxy CIDRs."""
    raw = os.getenv("TRUSTED_PROXY_CIDRS", "").strip()
    if not raw:
        return []
    return [cidr.strip() for cidr in raw.split(",") if cidr.strip()]


def _ip_in_cidrs(ip_str: str, cidrs: list[str]) -> bool:
    """Return whether an IP is contained by any valid configured CIDR."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def extract_client_ip(handler: Any) -> str | None:
    """Extract a request client IP, trusting forwarded data only from configured proxies."""
    if handler is None:
        return None

    direct_ip: str | None = None
    if hasattr(handler, "client_address"):
        addr = handler.client_address
        if isinstance(addr, tuple) and len(addr) >= 1:
            direct_ip = str(addr[0])

    if hasattr(handler, "headers"):
        forwarded = handler.headers.get("X-Forwarded-For", "")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            trusted_cidrs = _get_trusted_proxy_cidrs()
            if direct_ip and trusted_cidrs and _ip_in_cidrs(direct_ip, trusted_cidrs):
                return parts[0]
            if direct_ip is None and parts:
                return parts[-1]

    return direct_ip


__all__ = ["extract_client_ip"]
