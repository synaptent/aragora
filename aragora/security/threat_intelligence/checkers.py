"""
Threat Intelligence API Checkers.

Extracted from service.py to reduce file size.
Contains URL, IP, and file hash checking against external threat feeds.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from .enums import (
    SUSPICIOUS_TLDS,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)
from .models import FileHashResult, IPReputationResult, ThreatResult

logger = logging.getLogger(__name__)


class ThreatCheckersMixin:
    """Mixin providing URL, IP, and file hash checking against threat feeds."""

    # These attributes/methods are defined in the main class or other mixins
    config: Any
    _malicious_patterns: list[re.Pattern]
    _circuit_breakers: dict[str, Any]
    _get_cached: Any
    _set_cached: Any
    _emit_event: Any
    _check_rate_limit: Any
    _get_http_session: Any
    _is_circuit_open: Any
    _record_api_success: Any
    _record_api_failure: Any

    # =========================================================================
    # URL Checking
    # =========================================================================

    async def check_url(
        self,
        url: str,
        check_virustotal: bool = True,
        check_phishtank: bool = True,
        check_urlhaus: bool = True,
    ) -> ThreatResult:
        """Check a URL against threat intelligence sources."""
        cached = await self._get_cached(url, "url")
        if cached:
            return cached

        sources: list[ThreatSource] = []
        is_malicious = False
        threat_type = ThreatType.NONE
        severity = ThreatSeverity.NONE
        confidence = 0.0
        details: dict[str, Any] = {}
        vt_positives = 0
        vt_total = 0
        pt_verified = False
        uh_malware = False

        local_result = self._check_url_patterns(url)
        if local_result:
            sources.append(ThreatSource.LOCAL_RULES)
            is_malicious = True
            threat_type = local_result["threat_type"]
            severity = ThreatSeverity.MEDIUM
            confidence = 0.6
            details["local_match"] = local_result["pattern"]

        if check_virustotal and self.config.enable_virustotal and self.config.virustotal_api_key:
            vt_result = await self._check_url_virustotal(url)
            if vt_result:
                sources.append(ThreatSource.VIRUSTOTAL)
                vt_positives = vt_result.get("positives", 0)
                vt_total = vt_result.get("total", 0)
                details["virustotal"] = vt_result

                if vt_positives >= self.config.virustotal_malicious_threshold:
                    is_malicious = True
                    threat_type = self._classify_vt_threat(vt_result)
                    severity = self._vt_severity(vt_positives, vt_total)
                    confidence = max(confidence, vt_positives / max(vt_total, 1))

        if check_phishtank and self.config.enable_phishtank:
            pt_result = await self._check_url_phishtank(url)
            if pt_result:
                sources.append(ThreatSource.PHISHTANK)
                pt_verified = pt_result.get("verified", False)
                details["phishtank"] = pt_result

                if pt_verified:
                    is_malicious = True
                    threat_type = ThreatType.PHISHING
                    severity = ThreatSeverity.HIGH
                    confidence = max(confidence, 0.95)

        if check_urlhaus and self.config.enable_urlhaus:
            uh_result = await self._check_url_urlhaus(url)
            if uh_result:
                sources.append(ThreatSource.URLHAUS)
                uh_malware = uh_result.get("is_malware", False)
                details["urlhaus"] = uh_result

                if uh_malware:
                    is_malicious = True
                    uh_tags = uh_result.get("tags", [])
                    uh_threat = uh_result.get("threat", "")
                    if "ransomware" in uh_tags or "ransomware" in uh_threat.lower():
                        threat_type = ThreatType.RANSOMWARE
                    elif "trojan" in uh_tags or "trojan" in uh_threat.lower():
                        threat_type = ThreatType.TROJAN
                    elif "botnet" in uh_tags or "c2" in uh_tags:
                        threat_type = ThreatType.COMMAND_AND_CONTROL
                    else:
                        threat_type = ThreatType.MALWARE
                    severity = ThreatSeverity.CRITICAL
                    confidence = max(confidence, 0.90)

        result = ThreatResult(
            target=url,
            target_type="url",
            is_malicious=is_malicious,
            threat_type=threat_type,
            severity=severity,
            confidence=confidence,
            sources=sources if sources else [ThreatSource.LOCAL_RULES],
            details=details,
            virustotal_positives=vt_positives,
            virustotal_total=vt_total,
            phishtank_verified=pt_verified,
        )

        await self._set_cached(result)

        if result.is_malicious and result.confidence >= self.config.high_risk_threshold:
            self._emit_event(
                "high_risk_url",
                {
                    "target": url,
                    "threat_type": result.threat_type.value,
                    "severity": result.severity.name,
                    "confidence": result.confidence,
                    "sources": [s.value for s in result.sources],
                    "details": details,
                },
            )

        return result

    def _check_url_patterns(self, url: str) -> dict[str, Any] | None:
        """Check URL against local malicious patterns."""
        for pattern in self._malicious_patterns:
            if pattern.search(url):
                return {
                    "threat_type": ThreatType.PHISHING,
                    "pattern": pattern.pattern,
                }

        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            for tld in SUSPICIOUS_TLDS:
                if domain.endswith(tld):
                    return {
                        "threat_type": ThreatType.SUSPICIOUS,
                        "pattern": f"suspicious_tld:{tld}",
                    }
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Failed to parse URL for suspicious TLD check: %s", e)

        return None

    async def _check_url_virustotal(self, url: str) -> dict[str, Any] | None:
        """Check URL with VirusTotal API."""
        if self._is_circuit_open("virustotal"):
            logger.debug("VirusTotal circuit breaker open, skipping")
            return None

        if not await self._check_rate_limit("virustotal"):
            logger.warning("VirusTotal rate limit reached")
            return None

        session = await self._get_http_session()
        if not session:
            return None

        try:
            url_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
            headers = {"x-apikey": self.config.virustotal_api_key}

            async with session.get(
                f"https://www.virustotal.com/api/v3/urls/{url_id}",
                headers=headers,
            ) as response:
                if response.status == 200:
                    self._record_api_success("virustotal")
                    data = await response.json()
                    attrs = data.get("data", {}).get("attributes", {})
                    stats = attrs.get("last_analysis_stats", {})

                    return {
                        "positives": stats.get("malicious", 0) + stats.get("suspicious", 0),
                        "total": sum(stats.values()),
                        "categories": attrs.get("categories", {}),
                        "reputation": attrs.get("reputation", 0),
                        "last_analysis_date": attrs.get("last_analysis_date"),
                    }
                elif response.status == 404:
                    self._record_api_success("virustotal")
                    return await self._submit_url_virustotal(url)
                else:
                    self._record_api_failure("virustotal")
                    logger.warning("VirusTotal returned status %s", response.status)

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            self._record_api_failure("virustotal")
            logger.warning("VirusTotal URL check failed: %s", e)

        return None

    async def _submit_url_virustotal(self, url: str) -> dict[str, Any] | None:
        """Submit a URL to VirusTotal for scanning."""
        if not await self._check_rate_limit("virustotal"):
            return None

        session = await self._get_http_session()
        if not session:
            return None

        try:
            headers = {
                "x-apikey": self.config.virustotal_api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            async with session.post(
                "https://www.virustotal.com/api/v3/urls",
                headers=headers,
                data={"url": url},
            ) as response:
                if response.status == 200:
                    return {
                        "positives": 0,
                        "total": 0,
                        "pending": True,
                    }

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("VirusTotal URL submit failed: %s", e)

        return None

    async def _check_url_phishtank(self, url: str) -> dict[str, Any] | None:
        """Check URL with PhishTank API."""
        if self._is_circuit_open("phishtank"):
            logger.debug("PhishTank circuit breaker open, skipping")
            return None

        if not await self._check_rate_limit("phishtank"):
            logger.warning("PhishTank rate limit reached")
            return None

        session = await self._get_http_session()
        if not session:
            return None

        try:
            data = {
                "url": url,
                "format": "json",
            }
            if self.config.phishtank_api_key:
                data["app_key"] = self.config.phishtank_api_key

            async with session.post(
                "https://checkurl.phishtank.com/checkurl/",
                data=data,
            ) as response:
                if response.status == 200:
                    self._record_api_success("phishtank")
                    result = await response.json()
                    results = result.get("results", {})

                    return {
                        "in_database": results.get("in_database", False),
                        "verified": results.get("verified", False),
                        "phish_id": results.get("phish_id"),
                        "phish_detail_url": results.get("phish_detail_page"),
                    }
                else:
                    self._record_api_failure("phishtank")

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            self._record_api_failure("phishtank")
            logger.warning("PhishTank check failed: %s", e)

        return None

    async def _check_url_urlhaus(self, url: str) -> dict[str, Any] | None:
        """Check URL with URLhaus API."""
        if self._is_circuit_open("urlhaus"):
            logger.debug("URLhaus circuit breaker open, skipping")
            return None

        if not await self._check_rate_limit("urlhaus"):
            logger.warning("URLhaus rate limit reached")
            return None

        session = await self._get_http_session()
        if not session:
            return None

        try:
            async with session.post(
                "https://urlhaus-api.abuse.ch/v1/url/",
                data={"url": url},
            ) as response:
                if response.status == 200:
                    self._record_api_success("urlhaus")
                    result = await response.json()

                    query_status = result.get("query_status", "")
                    if query_status == "ok":
                        tags = result.get("tags", [])
                        return {
                            "is_malware": True,
                            "url_status": result.get("url_status", ""),
                            "threat": result.get("threat", ""),
                            "tags": tags if isinstance(tags, list) else [],
                            "host": result.get("host", ""),
                            "date_added": result.get("date_added", ""),
                            "reporter": result.get("reporter", ""),
                            "payloads": result.get("payloads", [])[:5],
                        }
                    elif query_status == "no_results":
                        return {
                            "is_malware": False,
                            "query_status": "not_found",
                        }
                else:
                    self._record_api_failure("urlhaus")
                    logger.warning("URLhaus returned status %s", response.status)

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            self._record_api_failure("urlhaus")
            logger.warning("URLhaus check failed: %s", e)

        return None

    def _classify_vt_threat(self, vt_result: dict[str, Any]) -> ThreatType:
        """Classify threat type from VirusTotal result."""
        categories = vt_result.get("categories", {})

        for vendor, category in categories.items():
            category_lower = category.lower() if category else ""
            if "phish" in category_lower:
                return ThreatType.PHISHING
            if "malware" in category_lower:
                return ThreatType.MALWARE
            if "spam" in category_lower:
                return ThreatType.SPAM

        if vt_result.get("positives", 0) > 0:
            return ThreatType.SUSPICIOUS

        return ThreatType.NONE

    def _vt_severity(self, positives: int, total: int) -> ThreatSeverity:
        """Calculate severity from VirusTotal results."""
        if total == 0:
            return ThreatSeverity.NONE

        ratio = positives / total

        if ratio >= 0.5:
            return ThreatSeverity.CRITICAL
        elif ratio >= 0.25:
            return ThreatSeverity.HIGH
        elif ratio >= 0.1:
            return ThreatSeverity.MEDIUM
        elif positives > 0:
            return ThreatSeverity.LOW

        return ThreatSeverity.NONE

    # =========================================================================
    # IP Checking
    # =========================================================================

    async def check_ip(self, ip_address: str) -> IPReputationResult:
        """Check an IP address against threat intelligence sources."""
        if not self._is_valid_ip(ip_address):
            return IPReputationResult(
                ip_address=ip_address,
                is_malicious=False,
                abuse_score=0,
                total_reports=0,
                last_reported=None,
                country_code=None,
                isp=None,
                domain=None,
                usage_type=None,
            )

        if self.config.enable_abuseipdb and self.config.abuseipdb_api_key:
            return await self._check_ip_abuseipdb(ip_address)

        return IPReputationResult(
            ip_address=ip_address,
            is_malicious=False,
            abuse_score=0,
            total_reports=0,
            last_reported=None,
            country_code=None,
            isp=None,
            domain=None,
            usage_type=None,
        )

    def _is_valid_ip(self, ip: str) -> bool:
        """Check if string is a valid IP address."""
        ipv4_pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
        if re.match(ipv4_pattern, ip):
            return True

        if ":" in ip and all(c in "0123456789abcdefABCDEF:" for c in ip):
            return True

        return False

    async def _check_ip_abuseipdb(self, ip_address: str) -> IPReputationResult:
        """Check IP with AbuseIPDB API."""
        default_result = IPReputationResult(
            ip_address=ip_address,
            is_malicious=False,
            abuse_score=0,
            total_reports=0,
            last_reported=None,
            country_code=None,
            isp=None,
            domain=None,
            usage_type=None,
        )

        if self._is_circuit_open("abuseipdb"):
            logger.debug("AbuseIPDB circuit breaker open, skipping")
            return default_result

        if not await self._check_rate_limit("abuseipdb"):
            logger.warning("AbuseIPDB rate limit reached")
            return default_result

        session = await self._get_http_session()
        if not session:
            return default_result

        try:
            headers = {
                "Key": self.config.abuseipdb_api_key,
                "Accept": "application/json",
            }

            params = {
                "ipAddress": ip_address,
                "maxAgeInDays": 90,
                "verbose": "",
            }

            async with session.get(
                "https://api.abuseipdb.com/api/v2/check",
                headers=headers,
                params=params,
            ) as response:
                if response.status == 200:
                    self._record_api_success("abuseipdb")
                    data = await response.json()
                    result = data.get("data", {})

                    abuse_score = result.get("abuseConfidenceScore", 0)
                    last_reported = None
                    if result.get("lastReportedAt"):
                        try:
                            last_reported = datetime.fromisoformat(
                                result["lastReportedAt"].replace("Z", "+00:00")
                            )
                        except ValueError as e:
                            logger.debug("Failed to parse datetime value: %s", e)

                    return IPReputationResult(
                        ip_address=ip_address,
                        is_malicious=abuse_score >= self.config.abuseipdb_malicious_threshold,
                        abuse_score=abuse_score,
                        total_reports=result.get("totalReports", 0),
                        last_reported=last_reported,
                        country_code=result.get("countryCode"),
                        isp=result.get("isp"),
                        domain=result.get("domain"),
                        usage_type=result.get("usageType"),
                        is_tor=result.get("isTor", False),
                    )
                else:
                    self._record_api_failure("abuseipdb")

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            self._record_api_failure("abuseipdb")
            logger.warning("AbuseIPDB check failed: %s", e)

        return default_result

    # =========================================================================
    # File Hash Checking
    # =========================================================================

    async def check_file_hash(
        self,
        hash_value: str,
        hash_type: str | None = None,
    ) -> FileHashResult:
        """Check a file hash against VirusTotal."""
        if not hash_type:
            hash_type = self._detect_hash_type(hash_value)

        if not hash_type:
            return FileHashResult(
                hash_value=hash_value,
                hash_type="unknown",
                is_malware=False,
            )

        if self.config.enable_virustotal and self.config.virustotal_api_key:
            return await self._check_hash_virustotal(hash_value, hash_type)

        return FileHashResult(
            hash_value=hash_value,
            hash_type=hash_type,
            is_malware=False,
        )

    def _detect_hash_type(self, hash_value: str) -> str | None:
        """Detect hash type from length."""
        hash_value = hash_value.strip().lower()

        if not all(c in "0123456789abcdef" for c in hash_value):
            return None

        if len(hash_value) == 32:
            return "md5"
        elif len(hash_value) == 40:
            return "sha1"
        elif len(hash_value) == 64:
            return "sha256"

        return None

    async def _check_hash_virustotal(self, hash_value: str, hash_type: str) -> FileHashResult:
        """Check file hash with VirusTotal API."""
        if not await self._check_rate_limit("virustotal"):
            logger.warning("VirusTotal rate limit reached")
            return FileHashResult(
                hash_value=hash_value,
                hash_type=hash_type,
                is_malware=False,
            )

        session = await self._get_http_session()
        if not session:
            return FileHashResult(
                hash_value=hash_value,
                hash_type=hash_type,
                is_malware=False,
            )

        try:
            headers = {"x-apikey": self.config.virustotal_api_key}

            async with session.get(
                f"https://www.virustotal.com/api/v3/files/{hash_value}",
                headers=headers,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    attrs = data.get("data", {}).get("attributes", {})
                    stats = attrs.get("last_analysis_stats", {})

                    malicious = stats.get("malicious", 0)
                    suspicious = stats.get("suspicious", 0)
                    total = sum(stats.values())

                    malware_names = []
                    results = attrs.get("last_analysis_results", {})
                    for vendor, result in results.items():
                        if result.get("category") == "malicious" and result.get("result"):
                            malware_names.append(result["result"])

                    first_seen = None
                    last_seen = None
                    if attrs.get("first_submission_date"):
                        first_seen = datetime.fromtimestamp(attrs["first_submission_date"])
                    if attrs.get("last_analysis_date"):
                        last_seen = datetime.fromtimestamp(attrs["last_analysis_date"])

                    return FileHashResult(
                        hash_value=hash_value,
                        hash_type=hash_type,
                        is_malware=malicious >= self.config.virustotal_malicious_threshold,
                        malware_names=malware_names[:10],
                        detection_ratio=f"{malicious + suspicious}/{total}",
                        first_seen=first_seen,
                        last_seen=last_seen,
                        file_type=attrs.get("type_description"),
                        file_size=attrs.get("size"),
                        tags=attrs.get("tags", [])[:10],
                    )

                elif response.status == 404:
                    return FileHashResult(
                        hash_value=hash_value,
                        hash_type=hash_type,
                        is_malware=False,
                    )

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("VirusTotal hash check failed: %s", e)

        return FileHashResult(
            hash_value=hash_value,
            hash_type=hash_type,
            is_malware=False,
        )
