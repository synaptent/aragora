"""
Threat Intelligence Assessment and Batch Operations.

Extracted from service.py to reduce file size.
Contains aggregate threat assessment, batch scanning, and email content checking.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from .enums import ThreatSeverity, ThreatSource, ThreatType
from .models import SourceResult, ThreatAssessment, ThreatResult

logger = logging.getLogger(__name__)


class ThreatAssessmentMixin:
    """Mixin providing aggregate assessment, batch operations, and email scanning."""

    # These attributes/methods are defined in the main class or other mixins
    config: Any
    _emit_event: Any
    check_url: Any
    check_ip: Any
    check_file_hash: Any
    _check_url_virustotal: Any
    _check_url_phishtank: Any
    _check_url_urlhaus: Any
    _check_url_patterns: Any
    _check_ip_abuseipdb: Any
    _classify_vt_threat: Any
    _is_valid_ip: Any
    _detect_hash_type: Any

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def check_urls_batch(
        self,
        urls: list[str],
        max_concurrent: int = 5,
    ) -> dict[str, ThreatResult]:
        """Check multiple URLs concurrently."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def check_with_semaphore(url: str) -> tuple:
            async with semaphore:
                result = await self.check_url(url)
                return (url, result)

        tasks = [check_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return dict(results)

    async def check_ips_batch(
        self,
        ips: list[str],
        max_concurrent: int = 5,
    ) -> dict[str, ThreatResult]:
        """Check multiple IPs concurrently."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def check_with_semaphore(ip: str) -> tuple:
            async with semaphore:
                ip_result = await self.check_ip(ip)
                threat_result = ThreatResult(
                    target=ip,
                    target_type="ip",
                    is_malicious=ip_result.is_malicious,
                    threat_type=(
                        ThreatType.MALICIOUS_IP if ip_result.is_malicious else ThreatType.NONE
                    ),
                    severity=ThreatSeverity.HIGH if ip_result.is_malicious else ThreatSeverity.NONE,
                    confidence=ip_result.abuse_score / 100,
                    sources=[ThreatSource.ABUSEIPDB],
                    abuseipdb_score=ip_result.abuse_score,
                    details=ip_result.to_dict(),
                )
                return (ip, threat_result)

        tasks = [check_with_semaphore(ip) for ip in ips]
        results = await asyncio.gather(*tasks)
        return dict(results)

    # =========================================================================
    # Aggregate Threat Assessment
    # =========================================================================

    async def assess_threat(
        self,
        target: str,
        target_type: str = "auto",
    ) -> ThreatAssessment:
        """Perform comprehensive threat assessment with weighted confidence scoring."""
        if target_type == "auto":
            if target.startswith(("http://", "https://")):
                target_type = "url"
            elif self._is_valid_ip(target):
                target_type = "ip"
            elif self._detect_hash_type(target):
                target_type = "hash"
            else:
                target_type = "url"

        source_results: dict[str, SourceResult] = {}
        threat_types_found: list[str] = []
        cache_hits = 0

        if target_type == "url":
            tasks = []

            if self.config.enable_virustotal and self.config.virustotal_api_key:
                tasks.append(("virustotal", self._check_url_virustotal(target)))

            if self.config.enable_phishtank:
                tasks.append(("phishtank", self._check_url_phishtank(target)))

            if self.config.enable_urlhaus:
                tasks.append(("urlhaus", self._check_url_urlhaus(target)))

            local_result = self._check_url_patterns(target)
            if local_result:
                source_results["local_rules"] = SourceResult(
                    source=ThreatSource.LOCAL_RULES,
                    is_malicious=True,
                    confidence=0.6,
                    threat_types=[local_result["threat_type"].value],
                    details={"pattern": local_result["pattern"]},
                )
                threat_types_found.append(local_result["threat_type"].value)

            if tasks:
                api_results = await asyncio.gather(
                    *[task for _, task in tasks], return_exceptions=True
                )

                for i, (source_name, _) in enumerate(tasks):
                    result = api_results[i]
                    if isinstance(result, Exception):
                        source_results[source_name] = SourceResult(
                            source=ThreatSource(source_name),
                            is_malicious=False,
                            confidence=0.0,
                            error=str(result),
                        )
                        continue

                    if result is None:
                        continue

                    if not isinstance(result, dict):
                        raise TypeError(
                            f"Expected dict from threat source, got {type(result).__name__}"
                        )
                    source_results[source_name] = self._parse_source_result(
                        source_name, result, threat_types_found
                    )

        elif target_type == "ip":
            if self.config.enable_abuseipdb and self.config.abuseipdb_api_key:
                ip_result = await self._check_ip_abuseipdb(target)
                is_malicious = ip_result.is_malicious
                confidence = ip_result.abuse_score / 100

                source_results["abuseipdb"] = SourceResult(
                    source=ThreatSource.ABUSEIPDB,
                    is_malicious=is_malicious,
                    confidence=confidence,
                    threat_types=[ThreatType.MALICIOUS_IP.value] if is_malicious else [],
                    raw_score=ip_result.abuse_score,
                    details=ip_result.to_dict(),
                )
                if is_malicious:
                    threat_types_found.append(ThreatType.MALICIOUS_IP.value)

        elif target_type == "hash":
            if self.config.enable_virustotal and self.config.virustotal_api_key:
                hash_result = await self.check_file_hash(target)
                is_malicious = hash_result.is_malware

                try:
                    positives, total = hash_result.detection_ratio.split("/")
                    confidence = int(positives) / max(int(total), 1) if total else 0.0
                except (ValueError, AttributeError):
                    confidence = 0.9 if is_malicious else 0.0

                source_results["virustotal"] = SourceResult(
                    source=ThreatSource.VIRUSTOTAL,
                    is_malicious=is_malicious,
                    confidence=confidence,
                    threat_types=[ThreatType.MALWARE.value] if is_malicious else [],
                    details=hash_result.to_dict(),
                )
                if is_malicious:
                    threat_types_found.append(ThreatType.MALWARE.value)

        overall_risk, weighted_confidence, is_malicious = self._calculate_aggregate_risk(
            source_results
        )

        risks = [sr.confidence for sr in source_results.values() if sr.confidence > 0]
        max_risk = max(risks) if risks else 0.0
        avg_risk = sum(risks) / len(risks) if risks else 0.0

        malicious_votes = sum(1 for sr in source_results.values() if sr.is_malicious)
        total_sources = len(source_results)
        agreement = malicious_votes / total_sources if total_sources > 0 else 0.0

        assessment = ThreatAssessment(
            target=target,
            target_type=target_type,
            overall_risk=overall_risk,
            is_malicious=is_malicious,
            threat_types=list(set(threat_types_found)),
            sources=source_results,
            weighted_confidence=weighted_confidence,
            max_source_risk=max_risk,
            avg_source_risk=avg_risk,
            source_agreement=agreement,
            sources_checked=total_sources,
            sources_responding=len([sr for sr in source_results.values() if sr.error is None]),
            cache_hits=cache_hits,
        )

        if is_malicious and overall_risk >= self.config.high_risk_threshold:
            self._emit_event(
                "high_risk_assessment",
                {
                    "target": target,
                    "target_type": target_type,
                    "overall_risk": overall_risk,
                    "threat_types": threat_types_found,
                    "sources": list(source_results.keys()),
                    "weighted_confidence": weighted_confidence,
                },
            )

        return assessment

    def _parse_source_result(
        self,
        source_name: str,
        result: dict[str, Any],
        threat_types_found: list[str],
    ) -> SourceResult:
        """Parse API result into SourceResult."""
        if source_name == "virustotal":
            positives = result.get("positives", 0)
            total = result.get("total", 0)
            is_malicious = positives >= self.config.virustotal_malicious_threshold
            confidence = positives / max(total, 1)

            threat_type = ThreatType.NONE
            if is_malicious:
                threat_type = self._classify_vt_threat(result)
                threat_types_found.append(threat_type.value)

            return SourceResult(
                source=ThreatSource.VIRUSTOTAL,
                is_malicious=is_malicious,
                confidence=confidence,
                threat_types=[threat_type.value] if threat_type != ThreatType.NONE else [],
                raw_score=positives,
                details=result,
            )

        elif source_name == "phishtank":
            verified = result.get("verified", False)
            in_db = result.get("in_database", False)
            is_malicious = verified
            confidence = 0.95 if verified else (0.5 if in_db else 0.0)

            if verified:
                threat_types_found.append(ThreatType.PHISHING.value)

            return SourceResult(
                source=ThreatSource.PHISHTANK,
                is_malicious=is_malicious,
                confidence=confidence,
                threat_types=[ThreatType.PHISHING.value] if verified else [],
                details=result,
            )

        elif source_name == "urlhaus":
            is_malware = result.get("is_malware", False)
            tags = result.get("tags", [])
            is_malicious = is_malware
            confidence = 0.90 if is_malware else 0.0

            detected_types = []
            if is_malware:
                threat = result.get("threat", "").lower()
                if "ransomware" in tags or "ransomware" in threat:
                    detected_types.append(ThreatType.RANSOMWARE.value)
                elif "trojan" in tags or "trojan" in threat:
                    detected_types.append(ThreatType.TROJAN.value)
                elif "botnet" in tags or "c2" in tags:
                    detected_types.append(ThreatType.COMMAND_AND_CONTROL.value)
                else:
                    detected_types.append(ThreatType.MALWARE.value)
                threat_types_found.extend(detected_types)

            return SourceResult(
                source=ThreatSource.URLHAUS,
                is_malicious=is_malicious,
                confidence=confidence,
                threat_types=detected_types,
                details=result,
            )

        return SourceResult(
            source=ThreatSource.CACHED,
            is_malicious=False,
            confidence=0.0,
            details=result,
        )

    def _calculate_aggregate_risk(
        self,
        source_results: dict[str, SourceResult],
    ) -> tuple:
        """Calculate aggregate risk score with weighted confidence."""
        if not source_results:
            return (0.0, 0.0, False)

        weights = self.config.source_weights
        total_weight = 0.0
        weighted_sum = 0.0
        malicious_weighted_sum = 0.0

        for source_name, result in source_results.items():
            weight = weights.get(source_name, 0.5)

            if result.error:
                continue

            total_weight += weight
            weighted_sum += result.confidence * weight

            if result.is_malicious:
                malicious_weighted_sum += weight

        if total_weight == 0:
            return (0.0, 0.0, False)

        weighted_confidence = weighted_sum / total_weight
        malicious_ratio = malicious_weighted_sum / total_weight
        overall_risk = min(1.0, weighted_confidence * 0.6 + malicious_ratio * 0.4)
        is_malicious = overall_risk >= self.config.malicious_threshold

        return (overall_risk, weighted_confidence, is_malicious)

    # =========================================================================
    # Email content checking
    # =========================================================================

    async def check_email_content(
        self,
        email_body: str,
        email_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Check email content for threats."""
        results: dict[str, Any] = {
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }

        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = list(set(re.findall(url_pattern, email_body)))

        if urls:
            url_results = await self.check_urls_batch(urls[:10])
            results["urls"] = [r.to_dict() for r in url_results.values()]

            malicious_urls = [r for r in url_results.values() if r.is_malicious]
            if malicious_urls:
                results["is_suspicious"] = True
                results["threat_summary"].append(f"Found {len(malicious_urls)} malicious URLs")

        if email_headers:
            received = email_headers.get("Received", "")
            ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
            ips = re.findall(ip_pattern, received)

            for ip in ips[:3]:
                if ip.startswith(("10.", "192.168.", "172.")):
                    continue
                ip_result = await self.check_ip(ip)
                results["ips"].append(ip_result.to_dict())

                if ip_result.is_malicious:
                    results["is_suspicious"] = True
                    results["threat_summary"].append(
                        f"Sender IP {ip} has abuse score {ip_result.abuse_score}"
                    )

        scores = []
        for url_result in results["urls"]:
            scores.append(url_result.get("threat_score", 0))
        for ip_result in results["ips"]:
            scores.append(ip_result.get("abuse_score", 0))

        if scores:
            results["overall_threat_score"] = sum(scores) / len(scores)

        return results
