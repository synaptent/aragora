"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.assessment`."""

from __future__ import annotations

from aragora.security.threat_intelligence.assessment import ThreatAssessmentMixin

# The old module also exposed these names, imported from its sibling threat-intelligence modules.
from aragora.security.threat_intelligence.assessment import (
    SourceResult,
    ThreatAssessment,
    ThreatResult,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "ThreatAssessmentMixin",
    "SourceResult",
    "ThreatAssessment",
    "ThreatResult",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
