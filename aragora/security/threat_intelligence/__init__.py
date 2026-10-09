"""
Threat Intelligence Integration Service.

Provides unified access to external threat intelligence feeds for:
- URL/attachment scanning (VirusTotal)
- IP reputation checking (AbuseIPDB)
- Phishing URL detection (PhishTank)
- Malware URL detection (URLhaus)

Features:
- Async API clients with rate limiting
- Tiered caching (1h for IPs, 24h for URLs) with Redis backend option
- Confidence scoring and threat classification
- Batch scanning capabilities with dict[str, ThreatResult] return
- Aggregate scoring from multiple sources with weighted confidence
- Event emission for high-risk findings
- Integration with email prioritization
- Fallback handling when APIs are unavailable

Usage:
    from aragora.security.threat_intelligence import ThreatIntelligenceService

    service = ThreatIntelligenceService(
        virustotal_api_key="your-key",
        abuseipdb_api_key="your-key",
    )

    # Check a URL
    result = await service.check_url("https://suspicious-site.com")
    if result.is_malicious:
        print(f"Threat detected: {result.threat_type}")
"""

from __future__ import annotations

# Re-export all public symbols for backward compatibility.
# Previously this was a single 2164-line file; it has been split into:
#   enums.py   - ThreatType, ThreatSeverity, ThreatSource, pattern constants
#   models.py  - ThreatResult, SourceResult, ThreatAssessment, etc.
#   config.py  - ThreatIntelConfig, ThreatEventHandler
#   service.py - ThreatIntelligenceService, check_threat()

from .config import ThreatEventHandler, ThreatIntelConfig
from .enums import (
    MALICIOUS_URL_PATTERNS,
    SUSPICIOUS_TLDS,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)
from .models import (
    FileHashResult,
    IPReputationResult,
    SourceResult,
    ThreatAssessment,
    ThreatResult,
)
from .service import ThreatIntelligenceService, check_threat

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
