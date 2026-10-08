"""Shared HMAC signing for Aragora webhook payloads."""

from __future__ import annotations

import hashlib
import hmac


def generate_signature(payload: str, secret: str) -> str:
    """Generate the HMAC-SHA256 signature for a webhook payload."""
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"


__all__ = ["generate_signature"]
