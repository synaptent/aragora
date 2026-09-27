"""
Threat Intelligence API Handlers.

Provides REST API endpoints for threat intelligence operations:
- URL scanning (VirusTotal, PhishTank)
- IP reputation checking (AbuseIPDB)
- File hash lookup (VirusTotal)
- Email content scanning

Endpoints:
- POST /api/v1/threat/url - Check URL for threats
- POST /api/v1/threat/urls - Batch check URLs
- GET /api/v1/threat/ip/{ip_address} - Check IP reputation
- POST /api/v1/threat/ips - Batch check IPs
- GET /api/v1/threat/hash/{hash_value} - Check file hash reputation
- POST /api/v1/threat/hashes - Batch check hashes
- POST /api/v1/threat/email - Scan email content
- GET /api/v1/threat/status - Get service status

All endpoints require authentication.
"""

from __future__ import annotations

import logging

from aiohttp import web


from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    api_endpoint,
    require_auth,
    rate_limit,
    validate_body,
)
from aragora.server.handlers.utils import parse_json_body
from aragora.rbac.decorators import require_permission
from aragora.services.threat_intelligence import (
    ThreatIntelligenceService,
    ThreatType,
)

logger = logging.getLogger(__name__)

# Global service instance (lazy initialized)
_threat_service: ThreatIntelligenceService | None = None


def get_threat_service() -> ThreatIntelligenceService:
    """Get or create threat intelligence service."""
    global _threat_service
    if _threat_service is None:
        _threat_service = ThreatIntelligenceService()
    return _threat_service


class ThreatIntelHandler(BaseHandler):
    """Handler for threat intelligence endpoints."""

    ROUTES = [
        "/api/v1/threat/email",
        "/api/v1/threat/hashes",
        "/api/v1/threat/ips",
        "/api/v1/threat/status",
        "/api/v1/threat/url",
        "/api/v1/threat/urls",
    ]

    def __init__(self, server_context=None):
        """Initialize handler."""
        super().__init__(server_context or {})
        self.service = get_threat_service()

    @require_permission("threat_intel:read")
    def handle(self, path: str, query_params: dict, handler) -> HandlerResult:
        """Route threat intel requests to appropriate methods."""
        # This handler uses @api_endpoint decorators, this is a placeholder
        # for RBAC enforcement at the handler routing level
        pass

    # =========================================================================
    # URL Scanning
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/threat/url",
        summary="Check URL for threats",
        description="Scan a URL against VirusTotal and PhishTank",
    )
    @require_auth
    @rate_limit(requests_per_minute=30)
    @validate_body(required_fields=["url"])
    async def check_url(self, request: web.Request) -> HandlerResult | web.Response:
        """
        Check a URL for threats.

        Request body:
            {
                "url": "https://example.com",
                "check_virustotal": true,
                "check_phishtank": true
            }

        Response:
            {
                "status": "success",
                "data": {
                    "target": "https://example.com",
                    "is_malicious": false,
                    "threat_type": "none",
                    "severity": "NONE",
                    "confidence": 0.0,
                    ...
                }
            }
        """
        try:
            body, err = await parse_json_body(request, context="check_url")
            if err:
                return err
            url = body.get("url", "").strip()

            if not url:
                return self.error_response("URL is required", status=400)

            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            result = await self.service.check_url(
                url=url,
                check_virustotal=body.get("check_virustotal", True),
                check_phishtank=body.get("check_phishtank", True),
            )

            return self.success_response(result.to_dict())

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("URL check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    @api_endpoint(
        method="POST",
        path="/api/v1/threat/urls",
        summary="Batch check URLs for threats",
        description="Scan multiple URLs concurrently",
    )
    @require_auth
    @rate_limit(requests_per_minute=10)
    @validate_body(required_fields=["urls"])
    async def check_urls_batch(self, request: web.Request) -> HandlerResult | web.Response:
        """
        Check multiple URLs for threats.

        Request body:
            {
                "urls": ["https://example1.com", "https://example2.com"],
                "max_concurrent": 5
            }

        Response:
            {
                "status": "success",
                "data": {
                    "results": [...],
                    "summary": {
                        "total": 2,
                        "malicious": 0,
                        "suspicious": 0,
                        "clean": 2
                    }
                }
            }
        """
        try:
            body, err = await parse_json_body(request, context="check_urls_batch")
            if err:
                return err
            urls = body.get("urls", [])

            if not urls:
                return self.error_response("URLs list is required", status=400)

            if len(urls) > 50:
                return self.error_response("Maximum 50 URLs per request", status=400)

            max_concurrent = min(body.get("max_concurrent", 5), 10)

            results = await self.service.check_urls_batch(
                urls=urls,
                max_concurrent=max_concurrent,
            )

            # Calculate summary
            malicious = sum(1 for r in results if r.is_malicious)
            suspicious = sum(
                1 for r in results if r.threat_type == ThreatType.SUSPICIOUS and not r.is_malicious
            )

            return self.success_response(
                {
                    "results": [r.to_dict() for r in results],
                    "summary": {
                        "total": len(results),
                        "malicious": malicious,
                        "suspicious": suspicious,
                        "clean": len(results) - malicious - suspicious,
                    },
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Batch URL check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    # =========================================================================
    # IP Reputation
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/threat/ip/{ip_address}",
        summary="Check IP reputation",
        description="Get reputation data for an IP address from AbuseIPDB",
    )
    @require_auth
    @rate_limit(requests_per_minute=60)
    async def check_ip(self, request: web.Request) -> HandlerResult:
        """
        Check IP address reputation.

        Path parameters:
            ip_address: The IP address to check

        Response:
            {
                "status": "success",
                "data": {
                    "ip_address": "1.2.3.4",
                    "is_malicious": false,
                    "abuse_score": 0,
                    "total_reports": 0,
                    ...
                }
            }
        """
        try:
            ip_address = request.match_info.get("ip_address", "")

            if not ip_address:
                return self.error_response("IP address is required", status=400)

            result = await self.service.check_ip(ip_address)

            return self.success_response(result.to_dict())

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("IP check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    @api_endpoint(
        method="POST",
        path="/api/v1/threat/ips",
        summary="Batch check IP addresses",
        description="Check multiple IP addresses for reputation",
    )
    @require_auth
    @rate_limit(requests_per_minute=20)
    @validate_body(required_fields=["ips"])
    async def check_ips_batch(self, request: web.Request) -> HandlerResult | web.Response:
        """
        Check multiple IP addresses.

        Request body:
            {
                "ips": ["1.2.3.4", "5.6.7.8"]
            }
        """
        try:
            body, err = await parse_json_body(request, context="check_ips_batch")
            if err:
                return err
            ips = body.get("ips", [])

            if not ips:
                return self.error_response("IPs list is required", status=400)

            if len(ips) > 20:
                return self.error_response("Maximum 20 IPs per request", status=400)

            results = []
            for ip in ips:
                result = await self.service.check_ip(ip)
                results.append(result.to_dict())

            malicious = sum(1 for r in results if r.get("is_malicious"))

            return self.success_response(
                {
                    "results": results,
                    "summary": {
                        "total": len(results),
                        "malicious": malicious,
                        "clean": len(results) - malicious,
                    },
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Batch IP check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    # =========================================================================
    # File Hash Lookup
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/threat/hash/{hash_value}",
        summary="Check file hash",
        description="Look up a file hash (MD5, SHA1, SHA256) in VirusTotal",
    )
    @require_auth
    @rate_limit(requests_per_minute=30)
    async def check_hash(self, request: web.Request) -> HandlerResult:
        """
        Check file hash for malware.

        Path parameters:
            hash_value: MD5, SHA1, or SHA256 hash

        Response:
            {
                "status": "success",
                "data": {
                    "hash_value": "abc123...",
                    "hash_type": "sha256",
                    "is_malware": false,
                    "detection_ratio": "0/70",
                    ...
                }
            }
        """
        try:
            hash_value = request.match_info.get("hash_value", "")

            if not hash_value:
                return self.error_response("Hash value is required", status=400)

            result = await self.service.check_file_hash(hash_value)

            return self.success_response(result.to_dict())

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Hash check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    @api_endpoint(
        method="POST",
        path="/api/v1/threat/hashes",
        summary="Batch check file hashes",
        description="Check multiple file hashes for malware",
    )
    @require_auth
    @rate_limit(requests_per_minute=10)
    @validate_body(required_fields=["hashes"])
    async def check_hashes_batch(self, request: web.Request) -> HandlerResult | web.Response:
        """
        Check multiple file hashes.

        Request body:
            {
                "hashes": ["abc123...", "def456..."]
            }
        """
        try:
            body, err = await parse_json_body(request, context="check_hashes_batch")
            if err:
                return err
            hashes = body.get("hashes", [])

            if not hashes:
                return self.error_response("Hashes list is required", status=400)

            if len(hashes) > 20:
                return self.error_response("Maximum 20 hashes per request", status=400)

            results = []
            for hash_value in hashes:
                result = await self.service.check_file_hash(hash_value)
                results.append(result.to_dict())

            malware = sum(1 for r in results if r.get("is_malware"))

            return self.success_response(
                {
                    "results": results,
                    "summary": {
                        "total": len(results),
                        "malware": malware,
                        "clean": len(results) - malware,
                    },
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Batch hash check failed: %s", e)
            return self.error_response("Internal server error", status=500)

    # =========================================================================
    # Email Content Scanning
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/threat/email",
        summary="Scan email content for threats",
        description="Extract and check URLs/IPs from email content",
    )
    @require_auth
    @rate_limit(requests_per_minute=20)
    @validate_body(required_fields=["body"])
    async def scan_email_content(self, request: web.Request) -> HandlerResult | web.Response:
        """
        Scan email content for threats.

        Request body:
            {
                "body": "Email body text with https://example.com links",
                "headers": {
                    "Received": "from mail.example.com [1.2.3.4]..."
                }
            }

        Response:
            {
                "status": "success",
                "data": {
                    "urls": [...],
                    "ips": [...],
                    "overall_threat_score": 0,
                    "is_suspicious": false,
                    "threat_summary": []
                }
            }
        """
        try:
            body, err = await parse_json_body(request, context="scan_email_content")
            if err:
                return err
            email_body = body.get("body", "")
            headers = body.get("headers", {})

            if not email_body:
                return self.error_response("Email body is required", status=400)

            result = await self.service.check_email_content(
                email_body=email_body,
                email_headers=headers,
            )

            return self.success_response(result)

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Email scan failed: %s", e)
            return self.error_response("Internal server error", status=500)

    # =========================================================================
    # Service Status
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/threat/status",
        summary="Get threat intel service status",
        description="Check which threat intelligence sources are available",
    )
    @require_auth
    async def get_status(self, request: web.Request) -> HandlerResult:
        """
        Get threat intelligence service status.

        Response:
            {
                "status": "success",
                "data": {
                    "virustotal": {"enabled": true, "has_key": true},
                    "abuseipdb": {"enabled": true, "has_key": false},
                    "phishtank": {"enabled": true, "has_key": false},
                    "caching": true
                }
            }
        """
        try:
            config = self.service.config

            return self.success_response(
                {
                    "virustotal": {
                        "enabled": config.enable_virustotal,
                        "has_key": bool(config.virustotal_api_key),
                        "rate_limit": config.virustotal_rate_limit,
                    },
                    "abuseipdb": {
                        "enabled": config.enable_abuseipdb,
                        "has_key": bool(config.abuseipdb_api_key),
                        "rate_limit": config.abuseipdb_rate_limit,
                    },
                    "phishtank": {
                        "enabled": config.enable_phishtank,
                        "has_key": bool(config.phishtank_api_key),
                        "rate_limit": config.phishtank_rate_limit,
                    },
                    "caching": config.enable_caching,
                    "cache_ttl_hours": config.cache_ttl_hours,
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Status check failed: %s", e)
            return self.error_response("Internal server error", status=500)


# =========================================================================
# Route Registration
# =========================================================================


def register_threat_intel_routes(app: web.Application) -> None:
    """Register threat intelligence routes with the application."""
    handler = ThreatIntelHandler()

    routes = [
        # URL scanning
        web.post("/api/v1/threat/url", handler.check_url),
        web.post("/api/v1/threat/urls", handler.check_urls_batch),
        # IP reputation
        web.get("/api/v1/threat/ip/{ip_address}", handler.check_ip),
        web.post("/api/v1/threat/ips", handler.check_ips_batch),
        # File hash lookup
        web.get("/api/v1/threat/hash/{hash_value}", handler.check_hash),
        web.post("/api/v1/threat/hashes", handler.check_hashes_batch),
        # Email scanning
        web.post("/api/v1/threat/email", handler.scan_email_content),
        # Status
        web.get("/api/v1/threat/status", handler.get_status),
    ]

    app.router.add_routes(routes)
    logger.info("Registered %s threat intelligence routes", len(routes))


# Export handler class
__all__ = [
    "ThreatIntelHandler",
    "register_threat_intel_routes",
    "get_threat_service",
]
