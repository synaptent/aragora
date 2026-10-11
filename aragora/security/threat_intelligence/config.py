"""
Threat intelligence configuration and protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ThreatIntelConfig:
    """Configuration for threat intelligence service."""

    # API Keys
    virustotal_api_key: str | None = None
    abuseipdb_api_key: str | None = None
    phishtank_api_key: str | None = None
    urlhaus_api_key: str | None = None  # URLhaus doesn't require API key but supports it

    # Rate limiting (requests per minute)
    virustotal_rate_limit: int = 4  # Free tier: 4/min
    abuseipdb_rate_limit: int = 60  # Free tier: 1000/day
    phishtank_rate_limit: int = 30
    urlhaus_rate_limit: int = 60  # URLhaus has generous limits

    # Cache settings - tiered TTL
    cache_ttl_hours: int = 24  # Default TTL (for URLs)
    cache_ip_ttl_hours: int = 1  # Shorter TTL for IPs (more volatile)
    cache_url_ttl_hours: int = 24  # Longer TTL for URLs
    cache_hash_ttl_hours: int = 168  # 7 days for file hashes (stable)
    cache_db_path: str = "threat_intel_cache.db"

    # Redis cache backend (optional)
    redis_url: str | None = None  # e.g., "redis://localhost:6379/0"
    use_redis_cache: bool = False  # Enable Redis backend

    # Thresholds
    virustotal_malicious_threshold: int = 3  # Positives to consider malicious
    abuseipdb_malicious_threshold: int = 50  # Abuse score to consider malicious
    urlhaus_tags_threshold: int = 1  # Number of malware tags to consider malicious

    # Source reliability weights for aggregate scoring (0-1)
    source_weights: dict[str, float] = field(
        default_factory=lambda: {
            "virustotal": 0.9,  # Highly reliable, multiple engines
            "abuseipdb": 0.8,  # Community-driven, reliable for IPs
            "phishtank": 0.85,  # Verified phishing, high confidence
            "urlhaus": 0.85,  # Malware-focused, well-maintained
            "local_rules": 0.5,  # Lower confidence for pattern matching
        }
    )

    # Risk thresholds
    high_risk_threshold: float = 0.7  # Emit events above this
    malicious_threshold: float = 0.5  # Consider malicious above this

    # Timeouts
    request_timeout_seconds: float = 10.0

    # Feature flags
    enable_virustotal: bool = True
    enable_abuseipdb: bool = True
    enable_phishtank: bool = True
    enable_urlhaus: bool = True
    enable_caching: bool = True
    enable_event_emission: bool = True  # Emit events for high-risk findings


class ThreatEventHandler(Protocol):
    """Protocol for threat event handlers."""

    def __call__(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle a threat event."""
        ...
