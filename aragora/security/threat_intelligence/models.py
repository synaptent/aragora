"""
Threat intelligence data models.

Dataclasses for threat results, assessments, and related types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import ThreatSeverity, ThreatSource, ThreatType


@dataclass
class ThreatResult:
    """Result of a threat intelligence lookup."""

    target: str  # URL, IP, or hash that was checked
    target_type: str  # "url", "ip", "hash", "email"
    is_malicious: bool
    threat_type: ThreatType
    severity: ThreatSeverity
    confidence: float  # 0.0 to 1.0
    sources: list[ThreatSource]
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)
    cached: bool = False

    # Source-specific scores
    virustotal_positives: int = 0
    virustotal_total: int = 0
    abuseipdb_score: int = 0
    phishtank_verified: bool = False

    @property
    def threat_score(self) -> float:
        """Combined threat score (0-100)."""
        scores = []

        if self.virustotal_total > 0:
            vt_score = (self.virustotal_positives / self.virustotal_total) * 100
            scores.append(vt_score)

        if self.abuseipdb_score > 0:
            scores.append(self.abuseipdb_score)

        if self.phishtank_verified:
            scores.append(100)

        if not scores:
            return 0.0

        return sum(scores) / len(scores)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "target": self.target,
            "target_type": self.target_type,
            "is_malicious": self.is_malicious,
            "threat_type": self.threat_type.value,
            "severity": self.severity.name,
            "severity_value": self.severity.value,
            "confidence": self.confidence,
            "threat_score": self.threat_score,
            "sources": [s.value for s in self.sources],
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
            "cached": self.cached,
            "virustotal": {
                "positives": self.virustotal_positives,
                "total": self.virustotal_total,
            },
            "abuseipdb_score": self.abuseipdb_score,
            "phishtank_verified": self.phishtank_verified,
        }


@dataclass
class SourceResult:
    """Result from a single threat intelligence source."""

    source: ThreatSource
    is_malicious: bool
    confidence: float  # 0.0 to 1.0
    threat_types: list[str] = field(default_factory=list)
    raw_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source.value,
            "is_malicious": self.is_malicious,
            "confidence": self.confidence,
            "threat_types": self.threat_types,
            "raw_score": self.raw_score,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
            "error": self.error,
        }


@dataclass
class ThreatAssessment:
    """
    Unified threat assessment aggregating results from multiple sources.

    Provides weighted confidence scores and comprehensive threat analysis.
    """

    target: str
    target_type: str  # "url", "ip", "hash"
    overall_risk: float  # 0.0 to 1.0
    is_malicious: bool
    threat_types: list[str] = field(default_factory=list)
    sources: dict[str, SourceResult] = field(default_factory=dict)
    weighted_confidence: float = 0.0
    checked_at: datetime = field(default_factory=datetime.now)

    # Risk breakdown
    max_source_risk: float = 0.0
    avg_source_risk: float = 0.0
    source_agreement: float = 0.0  # How much sources agree (0-1)

    # Metadata
    sources_checked: int = 0
    sources_responding: int = 0
    cache_hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "target": self.target,
            "target_type": self.target_type,
            "overall_risk": self.overall_risk,
            "is_malicious": self.is_malicious,
            "threat_types": self.threat_types,
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            "weighted_confidence": self.weighted_confidence,
            "checked_at": self.checked_at.isoformat(),
            "risk_breakdown": {
                "max_source_risk": self.max_source_risk,
                "avg_source_risk": self.avg_source_risk,
                "source_agreement": self.source_agreement,
            },
            "metadata": {
                "sources_checked": self.sources_checked,
                "sources_responding": self.sources_responding,
                "cache_hits": self.cache_hits,
            },
        }


@dataclass
class IPReputationResult:
    """Result of IP reputation check."""

    ip_address: str
    is_malicious: bool
    abuse_score: int  # 0-100
    total_reports: int
    last_reported: datetime | None
    country_code: str | None
    isp: str | None
    domain: str | None
    usage_type: str | None
    categories: list[str] = field(default_factory=list)
    is_tor: bool = False
    is_vpn: bool = False
    is_proxy: bool = False
    is_datacenter: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ip_address": self.ip_address,
            "is_malicious": self.is_malicious,
            "abuse_score": self.abuse_score,
            "total_reports": self.total_reports,
            "last_reported": self.last_reported.isoformat() if self.last_reported else None,
            "country_code": self.country_code,
            "isp": self.isp,
            "domain": self.domain,
            "usage_type": self.usage_type,
            "categories": self.categories,
            "is_tor": self.is_tor,
            "is_vpn": self.is_vpn,
            "is_proxy": self.is_proxy,
            "is_datacenter": self.is_datacenter,
        }


@dataclass
class FileHashResult:
    """Result of file hash lookup."""

    hash_value: str
    hash_type: str  # "md5", "sha1", "sha256"
    is_malware: bool
    malware_names: list[str] = field(default_factory=list)
    detection_ratio: str = "0/0"
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    file_type: str | None = None
    file_size: int | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hash_value": self.hash_value,
            "hash_type": self.hash_type,
            "is_malware": self.is_malware,
            "malware_names": self.malware_names,
            "detection_ratio": self.detection_ratio,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "tags": self.tags,
        }
