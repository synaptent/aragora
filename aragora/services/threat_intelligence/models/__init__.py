"""Compatibility re-export of :mod:`aragora.security.threat_intelligence.models`."""

from __future__ import annotations

from aragora.security.threat_intelligence.models import (
    FileHashResult,
    IPReputationResult,
    SourceResult,
    ThreatAssessment,
    ThreatResult,
)

# The old module also exposed these names, imported from its sibling threat-intelligence modules.
from aragora.security.threat_intelligence.models import (
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)

__all__ = [
    "FileHashResult",
    "IPReputationResult",
    "SourceResult",
    "ThreatAssessment",
    "ThreatResult",
    "ThreatSeverity",
    "ThreatSource",
    "ThreatType",
]
