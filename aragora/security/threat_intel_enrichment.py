"""
Threat Intelligence Enrichment for Debate Context.

Enriches debate context with relevant threat intelligence when discussing
security topics. Integrates with the existing ThreatIntelligenceService
to provide CVE lookups, indicator analysis, and mitigation recommendations.

Usage:
    from aragora.security.threat_intel_enrichment import ThreatIntelEnrichment

    enrichment = ThreatIntelEnrichment(
        threat_intel_client=threat_intel_service,
        enabled=True,
    )

    # Enrich security-related debate context
    context = await enrichment.enrich_context(
        topic="How should we respond to CVE-2024-1234?",
        existing_context="We run Python 3.11 with requests 2.28.0",
    )

    if context:
        formatted = enrichment.format_for_debate(context)
        # Inject formatted into debate prompt

Environment Variables:
    ARAGORA_THREAT_INTEL_ENRICHMENT_ENABLED: Enable enrichment (default: true)
    ARAGORA_THREAT_INTEL_MAX_INDICATORS: Max indicators to include (default: 10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.security.threat_intelligence import ThreatIntelligenceService
    from aragora.analysis.codebase.cve_client import CVEClient

logger = logging.getLogger(__name__)

# Environment configuration
ENRICHMENT_ENABLED = os.getenv("ARAGORA_THREAT_INTEL_ENRICHMENT_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
MAX_INDICATORS = int(os.getenv("ARAGORA_THREAT_INTEL_MAX_INDICATORS", "10"))


@dataclass
class ThreatIndicator:
    """Represents a threat indicator from intelligence feeds."""

    indicator_type: str  # ip, domain, hash, cve, url, etc.
    value: str
    threat_type: str  # malware, phishing, apt, ransomware, etc.
    severity: str  # low, medium, high, critical
    confidence: float  # 0.0 to 1.0
    source: str  # virustotal, abuseipdb, nvd, osv, etc.
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Initialize default tags list if None."""
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "indicator_type": self.indicator_type,
            "value": self.value,
            "threat_type": self.threat_type,
            "severity": self.severity,
            "confidence": self.confidence,
            "source": self.source,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "description": self.description,
            "tags": self.tags,
        }


@dataclass
class ThreatContext:
    """Aggregated threat context for debate enrichment."""

    indicators: list[ThreatIndicator]
    relevant_cves: list[dict[str, Any]]
    attack_patterns: list[str]
    recommended_mitigations: list[str]
    risk_summary: str
    enrichment_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "indicators": [ind.to_dict() for ind in self.indicators],
            "relevant_cves": self.relevant_cves,
            "attack_patterns": self.attack_patterns,
            "recommended_mitigations": self.recommended_mitigations,
            "risk_summary": self.risk_summary,
            "enrichment_timestamp": self.enrichment_timestamp.isoformat(),
        }


class ThreatIntelEnrichment:
    """
    Enriches debate context with threat intelligence.

    When security-related topics are detected, this class queries threat
    intelligence services to provide relevant context including:
    - CVE vulnerability details
    - IP/domain/URL reputation
    - File hash malware analysis
    - Attack patterns and mitigations

    Example:
        enrichment = ThreatIntelEnrichment()

        # Check if enrichment would apply
        if enrichment.is_security_topic("Discuss CVE-2024-1234 remediation"):
            context = await enrichment.enrich_context(
                topic="Discuss CVE-2024-1234 remediation"
            )
            if context:
                debate_context += enrichment.format_for_debate(context)
    """

    # Security-related keywords for topic detection
    SECURITY_KEYWORDS = [
        "security",
        "vulnerability",
        "exploit",
        "attack",
        "malware",
        "threat",
        "breach",
        "hack",
        "cve",
        "patch",
        "zero-day",
        "ransomware",
        "phishing",
        "apt",
        "incident",
        "forensic",
        "compromise",
        "injection",
        "xss",
        "csrf",
        "authentication",
        "authorization",
        "encryption",
        "cryptographic",
        "certificate",
        "ssl",
        "tls",
        "firewall",
        "intrusion",
        "penetration",
        "pentest",
        "audit",
        "compliance",
        "soc2",
        "pci",
        "gdpr",
        "hipaa",
    ]

    # Pattern for CVE identifiers
    CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)

    # Pattern for IP addresses
    IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

    # Pattern for URLs
    URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

    # Pattern for file hashes (MD5, SHA1, SHA256)
    HASH_PATTERNS = {
        "md5": re.compile(r"\b[a-fA-F0-9]{32}\b"),
        "sha1": re.compile(r"\b[a-fA-F0-9]{40}\b"),
        "sha256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
    }

    def __init__(
        self,
        threat_intel_client: ThreatIntelligenceService | None = None,
        cve_client: CVEClient | None = None,
        enabled: bool = ENRICHMENT_ENABLED,
        max_indicators: int = MAX_INDICATORS,
        cache_ttl_seconds: int = 3600,
    ):
        """
        Initialize threat intel enrichment.

        Args:
            threat_intel_client: Optional ThreatIntelligenceService for indicator lookups.
                                If not provided, will try to create one.
            cve_client: Optional CVEClient for CVE lookups.
                       If not provided, will try to create one.
            enabled: Whether enrichment is enabled.
            max_indicators: Maximum number of indicators to include in context.
            cache_ttl_seconds: Cache TTL for enrichment results.
        """
        self._enabled = enabled
        self._max_indicators = max_indicators
        self._cache_ttl = cache_ttl_seconds

        # Initialize threat intel client
        self._threat_client = threat_intel_client
        if self._threat_client is None and self._enabled:
            self._threat_client = self._create_threat_intel_client()

        # Initialize CVE client
        self._cve_client = cve_client
        if self._cve_client is None and self._enabled:
            self._cve_client = self._create_cve_client()

        # Simple cache: topic_hash -> (timestamp, ThreatContext)
        self._cache: dict[str, tuple[datetime, ThreatContext]] = {}

        if self._enabled:
            logger.info(
                "[threat_intel] Enrichment enabled (max_indicators=%s, threat_client=%s, cve_client=%s)",
                max_indicators,
                self._threat_client is not None,
                self._cve_client is not None,
            )

    def _create_threat_intel_client(self) -> ThreatIntelligenceService | None:
        """Create a ThreatIntelligenceService if dependencies available."""
        try:
            from aragora.security.threat_intelligence import ThreatIntelligenceService

            client = ThreatIntelligenceService()
            logger.debug("[threat_intel] Created ThreatIntelligenceService")
            return client
        except ImportError:
            logger.debug("[threat_intel] ThreatIntelligenceService not available")
            return None
        except (ValueError, TypeError, OSError) as e:
            logger.warning("[threat_intel] Failed to create ThreatIntelligenceService: %s", e)
            return None

    def _create_cve_client(self) -> CVEClient | None:
        """Create a CVEClient if dependencies available."""
        try:
            from aragora.analysis.codebase.cve_client import CVEClient

            client = CVEClient()
            logger.debug("[threat_intel] Created CVEClient")
            return client
        except ImportError:
            logger.debug("[threat_intel] CVEClient not available")
            return None
        except (ValueError, TypeError, OSError) as e:
            logger.warning("[threat_intel] Failed to create CVEClient: %s", e)
            return None

    def is_security_topic(self, topic: str) -> bool:
        """
        Check if topic is security-related.

        Args:
            topic: The debate topic/question.

        Returns:
            True if the topic contains security-related keywords.
        """
        topic_lower = topic.lower()
        return any(kw in topic_lower for kw in self.SECURITY_KEYWORDS)

    def _extract_entities(self, text: str) -> dict[str, list[Any]]:
        """
        Extract security-relevant entities from text.

        Args:
            text: Text to extract entities from.

        Returns:
            Dict mapping entity type to list of values.
        """
        entities: dict[str, list[Any]] = {
            "cves": [],
            "ips": [],
            "urls": [],
            "hashes": [],
        }

        # Extract CVEs
        cves = self.CVE_PATTERN.findall(text)
        entities["cves"] = list(set(cve.upper() for cve in cves))

        # Extract IPs (exclude common non-threat IPs)
        ips = self.IP_PATTERN.findall(text)
        entities["ips"] = [
            ip for ip in set(ips) if not ip.startswith(("10.", "192.168.", "172.16.", "127.", "0."))
        ]

        # Extract URLs
        urls = self.URL_PATTERN.findall(text)
        entities["urls"] = list(set(urls))[:10]  # Limit URLs

        # Extract file hashes
        hashes = []
        for hash_type, pattern in self.HASH_PATTERNS.items():
            matches = pattern.findall(text)
            for match in matches:
                # Verify it's likely a hash (not other hex data)
                if len(match) in (32, 40, 64):
                    hashes.append((hash_type, match.lower()))
        entities["hashes"] = list(set(hashes))[:5]  # Limit hashes

        return entities

    def _get_cache_key(self, topic: str, context: str) -> str:
        """Generate cache key from topic and context."""
        import hashlib

        content = f"{topic}:{context}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached(self, cache_key: str) -> ThreatContext | None:
        """Get cached enrichment result if not expired."""
        from datetime import timedelta

        if cache_key in self._cache:
            cached_at, context = self._cache[cache_key]
            if datetime.now(timezone.utc) - cached_at < timedelta(seconds=self._cache_ttl):
                logger.debug("[threat_intel] Cache hit for %s", cache_key)
                return context
            del self._cache[cache_key]
        return None

    def _set_cached(self, cache_key: str, context: ThreatContext) -> None:
        """Cache enrichment result."""
        self._cache[cache_key] = (datetime.now(timezone.utc), context)

        # Limit cache size
        if len(self._cache) > 100:
            # Remove oldest entries
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])
            for k in sorted_keys[:20]:
                del self._cache[k]

    async def enrich_context(
        self,
        topic: str,
        existing_context: str = "",
    ) -> ThreatContext | None:
        """
        Enrich debate context with threat intelligence.

        Args:
            topic: The debate topic/question.
            existing_context: Any existing context to analyze.

        Returns:
            ThreatContext with enriched data, or None if not applicable.
        """
        if not self._enabled:
            return None

        # Check if topic is security-related
        if not self.is_security_topic(topic):
            return None

        # Check cache
        cache_key = self._get_cache_key(topic, existing_context)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Extract entities to look up
        combined_text = f"{topic} {existing_context}"
        entities = self._extract_entities(combined_text)

        indicators: list[ThreatIndicator] = []
        cves: list[dict[str, Any]] = []

        # Look up CVEs
        for cve_id in entities["cves"][:5]:  # Limit lookups
            cve_info = await self._lookup_cve(cve_id)
            if cve_info:
                cves.append(cve_info)

        # Look up indicators via threat intel service
        if self._threat_client:
            # Look up IPs
            for ip in entities["ips"][:3]:
                indicator = await self._lookup_ip(ip)
                if indicator:
                    indicators.append(indicator)

            # Look up URLs
            for url in entities["urls"][:3]:
                indicator = await self._lookup_url(url)
                if indicator:
                    indicators.append(indicator)

            # Look up file hashes
            for hash_type, hash_value in entities["hashes"][:3]:
                indicator = await self._lookup_hash(hash_value, hash_type)
                if indicator:
                    indicators.append(indicator)

        # If no specific entities found but topic is security-related,
        # still provide contextual information
        if not indicators and not cves:
            context = self._build_generic_security_context(topic)
            if context:
                self._set_cached(cache_key, context)
                return context
            return None

        # Build threat context
        context = ThreatContext(
            indicators=indicators[: self._max_indicators],
            relevant_cves=cves,
            attack_patterns=self._extract_attack_patterns(indicators, cves),
            recommended_mitigations=self._get_mitigations(indicators, cves),
            risk_summary=self._summarize_risk(indicators, cves),
        )

        self._set_cached(cache_key, context)
        return context

    async def _lookup_cve(self, cve_id: str) -> dict[str, Any] | None:
        """Look up CVE details."""
        if not self._cve_client:
            return None

        try:
            vuln = await self._cve_client.get_cve(cve_id)
            if vuln:
                return {
                    "id": vuln.id,
                    "title": vuln.title,
                    "description": vuln.description[:500] if vuln.description else "",
                    "severity": vuln.severity.name if vuln.severity else "UNKNOWN",
                    "cvss_score": vuln.cvss_score,
                    "cvss_vector": vuln.cvss_vector,
                    "cwe_ids": vuln.cwe_ids[:5] if vuln.cwe_ids else [],
                    "fix_available": vuln.fix_available,
                    "recommended_version": vuln.recommended_version,
                    "published_at": vuln.published_at.isoformat() if vuln.published_at else None,
                }
        except (OSError, ValueError, KeyError, AttributeError, asyncio.TimeoutError) as e:
            logger.debug("[threat_intel] CVE lookup failed for %s: %s", cve_id, e)

        return None

    async def _lookup_ip(self, ip: str) -> ThreatIndicator | None:
        """Look up IP reputation."""
        if not self._threat_client:
            return None

        try:
            result = await self._threat_client.check_ip(ip)
            if result.is_malicious or result.abuse_score > 25:
                return ThreatIndicator(
                    indicator_type="ip",
                    value=ip,
                    threat_type="malicious_ip" if result.is_malicious else "suspicious_ip",
                    severity=self._abuse_score_to_severity(result.abuse_score),
                    confidence=result.abuse_score / 100,
                    source="abuseipdb",
                    description=f"Abuse score: {result.abuse_score}, Reports: {result.total_reports}",
                    tags=result.categories[:5] if result.categories else [],
                )
        except (OSError, ValueError, KeyError, AttributeError, asyncio.TimeoutError) as e:
            logger.debug("[threat_intel] IP lookup failed for %s: %s", ip, e)

        return None

    async def _lookup_url(self, url: str) -> ThreatIndicator | None:
        """Look up URL reputation."""
        if not self._threat_client:
            return None

        try:
            result = await self._threat_client.check_url(url)
            if result.is_malicious or result.confidence > 0.3:
                return ThreatIndicator(
                    indicator_type="url",
                    value=url[:100],  # Truncate long URLs
                    threat_type=result.threat_type.value if result.threat_type else "suspicious",
                    severity=result.severity.name if result.severity else "medium",
                    confidence=result.confidence,
                    source=",".join(s.value for s in result.sources[:3]),
                    description=(
                        result.details.get("description", "")[:200] if result.details else None
                    ),
                )
        except (OSError, ValueError, KeyError, AttributeError, asyncio.TimeoutError) as e:
            logger.debug("[threat_intel] URL lookup failed: %s", e)

        return None

    async def _lookup_hash(self, hash_value: str, hash_type: str) -> ThreatIndicator | None:
        """Look up file hash for malware."""
        if not self._threat_client:
            return None

        try:
            result = await self._threat_client.check_file_hash(hash_value, hash_type)
            if result.is_malware:
                return ThreatIndicator(
                    indicator_type="hash",
                    value=hash_value,
                    threat_type="malware",
                    severity="critical" if result.is_malware else "medium",
                    confidence=0.9 if result.is_malware else 0.5,
                    source="virustotal",
                    description=f"Detection: {result.detection_ratio}",
                    tags=result.malware_names[:5] if result.malware_names else [],
                    first_seen=result.first_seen,
                    last_seen=result.last_seen,
                )
        except (OSError, ValueError, KeyError, AttributeError, asyncio.TimeoutError) as e:
            logger.debug("[threat_intel] Hash lookup failed for %s: %s", hash_value, e)

        return None

    def _abuse_score_to_severity(self, score: int) -> str:
        """Convert AbuseIPDB score to severity level."""
        if score >= 80:
            return "critical"
        elif score >= 50:
            return "high"
        elif score >= 25:
            return "medium"
        return "low"

    def _extract_attack_patterns(
        self,
        indicators: list[ThreatIndicator],
        cves: list[dict[str, Any]],
    ) -> list[str]:
        """Extract attack patterns from indicators and CVEs."""
        patterns = set()

        # Extract from indicator tags and types
        for ind in indicators:
            if ind.threat_type:
                patterns.add(ind.threat_type.replace("_", " ").title())
            for tag in ind.tags[:3]:
                patterns.add(tag.title())

        # Extract from CVE CWEs
        for cve in cves:
            for cwe in cve.get("cwe_ids", [])[:2]:
                patterns.add(f"CWE: {cwe}")

        return list(patterns)[:10]

    def _get_mitigations(
        self,
        indicators: list[ThreatIndicator],
        cves: list[dict[str, Any]],
    ) -> list[str]:
        """Generate recommended mitigations based on threat data."""
        mitigations = []

        # CVE-specific mitigations
        for cve in cves:
            if cve.get("fix_available"):
                if cve.get("recommended_version"):
                    mitigations.append(
                        f"Upgrade to version {cve['recommended_version']} to fix {cve['id']}"
                    )
                else:
                    mitigations.append(f"Apply available patch for {cve['id']}")
            else:
                mitigations.append(
                    f"Monitor for patches for {cve['id']} - no fix currently available"
                )

        # Indicator-based mitigations
        malicious_ips = [ind for ind in indicators if ind.indicator_type == "ip"]
        if malicious_ips:
            mitigations.append(f"Block {len(malicious_ips)} malicious IP(s) at firewall level")

        malicious_urls = [ind for ind in indicators if ind.indicator_type == "url"]
        if malicious_urls:
            mitigations.append(f"Add {len(malicious_urls)} malicious URL(s) to proxy blocklist")

        malware_hashes = [ind for ind in indicators if ind.indicator_type == "hash"]
        if malware_hashes:
            mitigations.append(
                f"Add {len(malware_hashes)} malware hash(es) to endpoint detection rules"
            )

        # Generic security recommendations based on threat types
        threat_types = set(ind.threat_type for ind in indicators if ind.threat_type)
        if "phishing" in threat_types:
            mitigations.append("Enable email filtering and user security awareness training")
        if "ransomware" in threat_types:
            mitigations.append("Verify backup integrity and test restore procedures")
        if any("apt" in t.lower() for t in threat_types):
            mitigations.append("Implement network segmentation and enhanced monitoring")

        return mitigations[:8]

    def _summarize_risk(
        self,
        indicators: list[ThreatIndicator],
        cves: list[dict[str, Any]],
    ) -> str:
        """Generate a risk summary from threat data."""
        if not indicators and not cves:
            return "No specific threat indicators identified."

        parts = []

        # Summarize CVE severity
        critical_cves = [c for c in cves if c.get("severity") == "CRITICAL"]
        high_cves = [c for c in cves if c.get("severity") == "HIGH"]
        if critical_cves:
            parts.append(f"{len(critical_cves)} CRITICAL CVE(s)")
        if high_cves:
            parts.append(f"{len(high_cves)} HIGH severity CVE(s)")

        # Summarize indicators
        critical_indicators = [i for i in indicators if i.severity == "critical"]
        high_indicators = [i for i in indicators if i.severity == "high"]
        if critical_indicators:
            parts.append(f"{len(critical_indicators)} critical threat indicator(s)")
        if high_indicators:
            parts.append(f"{len(high_indicators)} high-severity indicator(s)")

        # Overall risk level
        if critical_cves or critical_indicators:
            risk_level = "CRITICAL"
        elif high_cves or high_indicators:
            risk_level = "HIGH"
        elif cves or indicators:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        if parts:
            return f"Overall risk: {risk_level}. Found {', '.join(parts)}."
        return f"Overall risk: {risk_level}."

    def _build_generic_security_context(self, topic: str) -> ThreatContext | None:
        """Build generic security context when no specific IOCs are found."""
        topic_lower = topic.lower()

        # Identify the security domain from the topic
        patterns = []
        mitigations = []

        if "ransomware" in topic_lower:
            patterns = ["Ransomware", "Data Encryption", "Extortion"]
            mitigations = [
                "Maintain offline backups",
                "Implement network segmentation",
                "Deploy endpoint detection and response (EDR)",
                "Enable multi-factor authentication",
            ]
        elif "phishing" in topic_lower:
            patterns = ["Phishing", "Social Engineering", "Credential Theft"]
            mitigations = [
                "Deploy email security gateway",
                "Conduct security awareness training",
                "Implement DMARC/SPF/DKIM",
                "Enable MFA for all accounts",
            ]
        elif "injection" in topic_lower or "sql" in topic_lower:
            patterns = ["SQL Injection", "Code Injection", "Input Validation Bypass"]
            mitigations = [
                "Use parameterized queries",
                "Implement input validation",
                "Deploy WAF with injection rules",
                "Apply least privilege database access",
            ]
        elif "xss" in topic_lower or "cross-site" in topic_lower:
            patterns = ["Cross-Site Scripting", "DOM Manipulation", "Session Hijacking"]
            mitigations = [
                "Implement Content Security Policy",
                "Encode output properly",
                "Use HTTPOnly and Secure cookie flags",
                "Sanitize user input",
            ]
        elif "authentication" in topic_lower or "auth" in topic_lower:
            patterns = ["Authentication Bypass", "Credential Stuffing", "Brute Force"]
            mitigations = [
                "Implement multi-factor authentication",
                "Use rate limiting on auth endpoints",
                "Deploy account lockout policies",
                "Monitor for anomalous login patterns",
            ]
        elif "encryption" in topic_lower or "cryptograph" in topic_lower:
            patterns = ["Weak Encryption", "Key Management", "Data Exposure"]
            mitigations = [
                "Use AES-256 or stronger encryption",
                "Implement proper key rotation",
                "Store keys in HSM or KMS",
                "Enforce TLS 1.3 for transport",
            ]
        else:
            # Generic security context
            patterns = ["Security Vulnerability", "Risk Assessment"]
            mitigations = [
                "Conduct thorough security assessment",
                "Apply defense in depth principles",
                "Monitor and log security events",
                "Maintain incident response procedures",
            ]

        return ThreatContext(
            indicators=[],
            relevant_cves=[],
            attack_patterns=patterns,
            recommended_mitigations=mitigations,
            risk_summary=f"Security topic identified: {topic[:50]}. Providing general guidance.",
        )

    def format_for_debate(self, context: ThreatContext) -> str:
        """
        Format threat context as debate context string.

        Args:
            context: ThreatContext to format.

        Returns:
            Formatted string suitable for injection into debate prompts.
        """
        lines = ["## Threat Intelligence Context\n"]

        # CVE section
        if context.relevant_cves:
            lines.append("### Relevant CVEs")
            for cve in context.relevant_cves[:5]:
                severity = cve.get("severity", "UNKNOWN")
                cvss = cve.get("cvss_score")
                cvss_str = f" (CVSS: {cvss})" if cvss else ""
                desc = cve.get("description", "")[:200]
                lines.append(f"- **{cve['id']}** [{severity}]{cvss_str}: {desc}")
                if cve.get("fix_available") and cve.get("recommended_version"):
                    lines.append(f"  - Fix: Upgrade to {cve['recommended_version']}")

        # Indicators section
        if context.indicators:
            lines.append("\n### Threat Indicators")
            for ind in context.indicators[:5]:
                confidence_pct = int(ind.confidence * 100)
                lines.append(
                    f"- **{ind.indicator_type.upper()}**: `{ind.value}` "
                    f"({ind.severity}, {confidence_pct}% confidence, source: {ind.source})"
                )
                if ind.description:
                    lines.append(f"  - {ind.description[:100]}")

        # Attack patterns
        if context.attack_patterns:
            lines.append("\n### Attack Patterns")
            for pattern in context.attack_patterns[:5]:
                lines.append(f"- {pattern}")

        # Mitigations
        if context.recommended_mitigations:
            lines.append("\n### Recommended Mitigations")
            for i, mit in enumerate(context.recommended_mitigations[:5], 1):
                lines.append(f"{i}. {mit}")

        # Risk summary
        lines.append(f"\n**Risk Summary**: {context.risk_summary}")

        return "\n".join(lines)

    async def close(self) -> None:
        """Close any open connections."""
        if self._threat_client:
            try:
                await self._threat_client.close()
            except (OSError, RuntimeError) as e:
                logger.debug("Error closing threat intel client: %s", e)


# Convenience function for quick enrichment
async def enrich_security_context(
    topic: str,
    existing_context: str = "",
    threat_intel_client: ThreatIntelligenceService | None = None,
) -> str | None:
    """
    Quick convenience function for threat intel enrichment.

    Args:
        topic: The debate topic/question.
        existing_context: Any existing context to analyze.
        threat_intel_client: Optional pre-configured threat intel client.

    Returns:
        Formatted threat context string, or None if not applicable.

    Example:
        context = await enrich_security_context(
            "How should we respond to CVE-2024-1234?"
        )
        if context:
            debate_prompt += context
    """
    enrichment = ThreatIntelEnrichment(
        threat_intel_client=threat_intel_client,
    )

    try:
        threat_context = await enrichment.enrich_context(topic, existing_context)
        if threat_context:
            return enrichment.format_for_debate(threat_context)
        return None
    finally:
        await enrichment.close()


__all__ = [
    "ThreatIndicator",
    "ThreatContext",
    "ThreatIntelEnrichment",
    "enrich_security_context",
    "ENRICHMENT_ENABLED",
    "MAX_INDICATORS",
]
