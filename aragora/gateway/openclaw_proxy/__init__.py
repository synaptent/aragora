"""
OpenClaw Secure Proxy (compatibility path).

The secure proxy lives in :mod:`aragora.compat.openclaw_proxy`; this module
re-exports the same objects.
"""

from __future__ import annotations

from aragora.compat.openclaw_proxy import (
    OpenClawSecureProxy,
    PendingApproval,
    ProxyActionResult,
    ProxySession,
)

__all__ = ["OpenClawSecureProxy", "PendingApproval", "ProxyActionResult", "ProxySession"]
