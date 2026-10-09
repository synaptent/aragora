"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.cache`."""

from __future__ import annotations

from aragora.security.threat_intelligence.cache import ThreatCacheMixin

# The old module also exposed these names, imported from its sibling threat-intelligence modules.
from aragora.security.threat_intelligence.cache import (
    ThreatResult,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "ThreatCacheMixin",
    "ThreatResult",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
