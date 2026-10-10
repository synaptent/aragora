"""
Threat Intelligence Service - main service class.

Integrates with multiple threat feeds to provide comprehensive
threat assessment for URLs, IPs, and file hashes.

The implementation is split across mixin classes:
- ThreatCacheMixin (cache.py) - Multi-tier caching (memory, Redis, SQLite)
- ThreatCheckersMixin (checkers.py) - URL/IP/hash checking via external APIs
- ThreatAssessmentMixin (assessment.py) - Aggregate assessment, batch ops, email scanning
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import threading
from typing import Any

from .assessment import ThreatAssessmentMixin
from .cache import ThreatCacheMixin
from .checkers import ThreatCheckersMixin
from .config import ThreatEventHandler, ThreatIntelConfig
from .enums import (
    MALICIOUS_URL_PATTERNS,
    ThreatSeverity,
    ThreatSource,
    ThreatType,
)
from .models import ThreatResult

logger = logging.getLogger(__name__)


class ThreatIntelligenceService(
    ThreatCacheMixin,
    ThreatCheckersMixin,
    ThreatAssessmentMixin,
):
    """
    Unified threat intelligence service.

    Integrates with multiple threat feeds to provide comprehensive
    threat assessment for URLs, IPs, and file hashes.

    Features:
    - Multi-source threat intelligence (VirusTotal, AbuseIPDB, PhishTank, URLhaus)
    - Tiered caching with different TTLs per target type
    - Batch lookups returning dict[str, ThreatResult]
    - Aggregate scoring with weighted confidence
    - Event emission for high-risk findings
    - Email prioritization integration
    """

    def __init__(
        self,
        config: ThreatIntelConfig | None = None,
        virustotal_api_key: str | None = None,
        abuseipdb_api_key: str | None = None,
        phishtank_api_key: str | None = None,
        urlhaus_api_key: str | None = None,
        event_handler: ThreatEventHandler | None = None,
    ):
        """
        Initialize threat intelligence service.

        Args:
            config: Full configuration object
            virustotal_api_key: VirusTotal API key (overrides config)
            abuseipdb_api_key: AbuseIPDB API key (overrides config)
            phishtank_api_key: PhishTank API key (overrides config)
            urlhaus_api_key: URLhaus API key (optional, overrides config)
            event_handler: Optional callback for threat events
        """
        self.config = config or ThreatIntelConfig()

        # Override with explicit keys
        if virustotal_api_key:
            self.config.virustotal_api_key = virustotal_api_key
        if abuseipdb_api_key:
            self.config.abuseipdb_api_key = abuseipdb_api_key
        if phishtank_api_key:
            self.config.phishtank_api_key = phishtank_api_key
        if urlhaus_api_key:
            self.config.urlhaus_api_key = urlhaus_api_key

        # Load from environment if not set
        if not self.config.virustotal_api_key:
            self.config.virustotal_api_key = os.getenv("VIRUSTOTAL_API_KEY")
        if not self.config.abuseipdb_api_key:
            self.config.abuseipdb_api_key = os.getenv("ABUSEIPDB_API_KEY")
        if not self.config.phishtank_api_key:
            self.config.phishtank_api_key = os.getenv("PHISHTANK_API_KEY")
        if not self.config.urlhaus_api_key:
            self.config.urlhaus_api_key = os.getenv("URLHAUS_API_KEY")
        if not self.config.redis_url:
            self.config.redis_url = os.getenv("ARAGORA_REDIS_URL") or os.getenv("REDIS_URL")

        # Event handler for threat notifications
        self._event_handler = event_handler
        self._event_handlers: list[ThreatEventHandler] = []
        if event_handler:
            self._event_handlers.append(event_handler)

        # Rate limiting state
        self._rate_limits: dict[str, list[float]] = {
            "virustotal": [],
            "abuseipdb": [],
            "phishtank": [],
            "urlhaus": [],
        }

        # Circuit breakers for external APIs (auto-open after 3 failures, 60s cooldown)
        from aragora.resilience import get_circuit_breaker

        self._circuit_breakers = {
            "virustotal": get_circuit_breaker(
                "threat_intel_virustotal",
                failure_threshold=3,
                cooldown_seconds=60.0,
            ),
            "abuseipdb": get_circuit_breaker(
                "threat_intel_abuseipdb",
                failure_threshold=3,
                cooldown_seconds=60.0,
            ),
            "phishtank": get_circuit_breaker(
                "threat_intel_phishtank",
                failure_threshold=3,
                cooldown_seconds=60.0,
            ),
            "urlhaus": get_circuit_breaker(
                "threat_intel_urlhaus",
                failure_threshold=3,
                cooldown_seconds=60.0,
            ),
        }

        # Compile patterns
        self._malicious_patterns = [re.compile(p) for p in MALICIOUS_URL_PATTERNS]

        # Cache backends
        self._cache_conn: sqlite3.Connection | None = None  # SQLite backend
        self._redis_client: Any = None  # Redis backend (optional)
        self._memory_cache: dict[str, dict[str, Any]] = {}  # In-memory cache
        self._memory_cache_lock = threading.Lock()

        # HTTP session (lazy initialized)
        self._http_session: Any | None = None  # aiohttp.ClientSession

        logger.info(
            "ThreatIntelligenceService initialized (VT: %s, AIPDB: %s, PT: %s, UH: %s)",
            bool(self.config.virustotal_api_key),
            bool(self.config.abuseipdb_api_key),
            bool(self.config.phishtank_api_key),
            self.config.enable_urlhaus,
        )

    # =========================================================================
    # Event handling
    # =========================================================================

    def add_event_handler(self, handler: ThreatEventHandler) -> None:
        """Add an event handler for threat notifications."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: ThreatEventHandler) -> bool:
        """Remove an event handler. Returns True if removed."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)
            return True
        return False

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a threat event to all handlers."""
        if not self.config.enable_event_emission:
            return

        for handler in self._event_handlers:
            try:
                handler(event_type, data)
            except (RuntimeError, TypeError, ValueError) as e:
                logger.warning("Error in threat event handler: %s", e)

    # =========================================================================
    # Rate limiting and circuit breakers
    # =========================================================================

    async def _check_rate_limit(self, service: str) -> bool:
        """Check if we're within rate limits for a service."""
        limits = {
            "virustotal": self.config.virustotal_rate_limit,
            "abuseipdb": self.config.abuseipdb_rate_limit,
            "phishtank": self.config.phishtank_rate_limit,
            "urlhaus": self.config.urlhaus_rate_limit,
        }

        limit = limits.get(service, 60)
        now = time.time()
        minute_ago = now - 60

        # Clean old entries
        self._rate_limits[service] = [t for t in self._rate_limits[service] if t > minute_ago]

        # Check limit
        if len(self._rate_limits[service]) >= limit:
            return False

        # Record this request
        self._rate_limits[service].append(now)
        return True

    async def _get_http_session(self):
        """Get or create HTTP session."""
        if self._http_session is None:
            try:
                import aiohttp

                self._http_session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)
                )
            except ImportError:
                logger.warning("aiohttp not available, HTTP requests will fail")
                return None
        return self._http_session

    def _is_circuit_open(self, service: str) -> bool:
        """Check if circuit breaker is open for a service."""
        if service not in self._circuit_breakers:
            return False
        cb = self._circuit_breakers[service]
        return cb.get_status() == "open"

    def _record_api_success(self, service: str) -> None:
        """Record a successful API call for circuit breaker."""
        if service in self._circuit_breakers:
            self._circuit_breakers[service].record_success()

    def _record_api_failure(self, service: str) -> None:
        """Record a failed API call for circuit breaker."""
        if service in self._circuit_breakers:
            self._circuit_breakers[service].record_failure()
            if self._circuit_breakers[service].get_status() == "open":
                logger.warning(
                    "[ThreatIntel] Circuit breaker OPEN for %s - API calls will be skipped for %ss",
                    service,
                    self._circuit_breakers[service].cooldown_seconds,
                )

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get status of all threat intel circuit breakers."""
        return {
            service: {
                "status": cb.get_status(),
                "failures": cb.failures,
                "threshold": cb.failure_threshold,
                "cooldown_remaining": (
                    max(0, cb.cooldown_seconds - (time.time() - cb._last_failure_time))
                    if hasattr(cb, "_last_failure_time") and cb.get_status() == "open"
                    else 0
                ),
            }
            for service, cb in self._circuit_breakers.items()
        }

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Close service connections."""
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

        if self._cache_conn:
            self._cache_conn.close()
            self._cache_conn = None


# Convenience function for quick checks
async def check_threat(
    target: str,
    target_type: str = "auto",
    virustotal_api_key: str | None = None,
    abuseipdb_api_key: str | None = None,
) -> ThreatResult:
    """Quick convenience function for threat checking."""
    service = ThreatIntelligenceService(
        virustotal_api_key=virustotal_api_key,
        abuseipdb_api_key=abuseipdb_api_key,
    )

    try:
        if target_type == "auto":
            if target.startswith(("http://", "https://")):
                target_type = "url"
            elif service._is_valid_ip(target):
                target_type = "ip"
            elif service._detect_hash_type(target):
                target_type = "hash"
            else:
                target_type = "url"

        if target_type == "url":
            return await service.check_url(target)
        elif target_type == "ip":
            ip_result = await service.check_ip(target)
            return ThreatResult(
                target=target,
                target_type="ip",
                is_malicious=ip_result.is_malicious,
                threat_type=ThreatType.MALICIOUS_IP if ip_result.is_malicious else ThreatType.NONE,
                severity=ThreatSeverity.HIGH if ip_result.is_malicious else ThreatSeverity.NONE,
                confidence=ip_result.abuse_score / 100,
                sources=[ThreatSource.ABUSEIPDB],
                abuseipdb_score=ip_result.abuse_score,
            )
        elif target_type == "hash":
            hash_result = await service.check_file_hash(target)
            return ThreatResult(
                target=target,
                target_type="hash",
                is_malicious=hash_result.is_malware,
                threat_type=ThreatType.MALWARE if hash_result.is_malware else ThreatType.NONE,
                severity=ThreatSeverity.CRITICAL if hash_result.is_malware else ThreatSeverity.NONE,
                confidence=0.9 if hash_result.is_malware else 0.0,
                sources=[ThreatSource.VIRUSTOTAL],
                details={"malware_names": hash_result.malware_names},
            )

        return ThreatResult(
            target=target,
            target_type=target_type,
            is_malicious=False,
            threat_type=ThreatType.NONE,
            severity=ThreatSeverity.NONE,
            confidence=0.0,
            sources=[],
        )

    finally:
        await service.close()
