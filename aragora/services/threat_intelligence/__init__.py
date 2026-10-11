"""
Threat Intelligence Integration Service (compatibility re-export).

The implementation moved to :mod:`aragora.security.threat_intelligence`; every
name below is the identical object.

Usage:
    from aragora.security.threat_intelligence import ThreatIntelligenceService
"""

from __future__ import annotations

from aragora.security.threat_intelligence import (
    MALICIOUS_URL_PATTERNS,
    SUSPICIOUS_TLDS,
    FileHashResult,
    IPReputationResult,
    SourceResult,
    ThreatAssessment,
    ThreatEventHandler,
    ThreatIntelConfig,
    ThreatIntelligenceService,
    ThreatResult,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
    check_threat,
)

__all__ = [
    # Enums & constants
    "ThreatType",
    "ThreatSeverity",
    "ThreatSource",
    "MALICIOUS_URL_PATTERNS",
    "SUSPICIOUS_TLDS",
    # Models
    "ThreatResult",
    "SourceResult",
    "ThreatAssessment",
    "IPReputationResult",
    "FileHashResult",
    # Config
    "ThreatIntelConfig",
    "ThreatEventHandler",
    # Service
    "ThreatIntelligenceService",
    "check_threat",
]
