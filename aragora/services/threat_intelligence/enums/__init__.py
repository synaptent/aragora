"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.enums`."""

from __future__ import annotations

from aragora.security.threat_intelligence.enums import (
    MALICIOUS_URL_PATTERNS,
    SUSPICIOUS_TLDS,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "MALICIOUS_URL_PATTERNS",
    "SUSPICIOUS_TLDS",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
