"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.checkers`."""

from __future__ import annotations

from aragora.security.threat_intelligence.checkers import ThreatCheckersMixin

# The old module also exposed these names, imported from its sibling threat-intelligence modules.
from aragora.security.threat_intelligence.checkers import (
    SUSPICIOUS_TLDS,
    FileHashResult,
    IPReputationResult,
    ThreatResult,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "ThreatCheckersMixin",
    "SUSPICIOUS_TLDS",
    "FileHashResult",
    "IPReputationResult",
    "ThreatResult",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
