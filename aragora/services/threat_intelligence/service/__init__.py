"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.service`."""

from __future__ import annotations

from aragora.security.threat_intelligence.service import (
    ThreatIntelligenceService,
    check_threat,
)

# The old module also exposed these names, imported from its sibling threat-intelligence modules.
from aragora.security.threat_intelligence.service import (
    MALICIOUS_URL_PATTERNS,
    ThreatAssessmentMixin,
    ThreatCacheMixin,
    ThreatCheckersMixin,
    ThreatEventHandler,
    ThreatIntelConfig,
    ThreatResult,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "ThreatIntelligenceService",
    "check_threat",
    "MALICIOUS_URL_PATTERNS",
    "ThreatAssessmentMixin",
    "ThreatCacheMixin",
    "ThreatCheckersMixin",
    "ThreatEventHandler",
    "ThreatIntelConfig",
    "ThreatResult",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
