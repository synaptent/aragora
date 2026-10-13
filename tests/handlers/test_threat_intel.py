"""Tests for threat intelligence handler.

Covers:
- Handler initialization and service creation
- URL scanning (single + batch)
- IP reputation checking (single + batch)
- File hash lookup (single + batch)
- Email content scanning
- Service status endpoint
- Input validation (missing fields, empty values, limits)
- Error handling (service exceptions)
- URL auto-prefix (http/https)
- Batch size limits
- Max concurrent capping
- Route registration
- Module exports
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from aragora.server.handlers.threat_intel import (
    ThreatIntelHandler,
    get_threat_service,
    register_threat_intel_routes,
)
from aragora.services.threat_intelligence import ThreatType


# ============================================================================
# Helpers
# ============================================================================


def _body(result) -> dict:
    """Parse HandlerResult.body bytes into dict."""
    return json.loads(result.body)


def _make_request(
    method: str = "POST",
    path: str = "/",
    body: dict | None = None,
    match_info: dict | None = None,
):
    """Create a mock aiohttp request with JSON body and auth header."""
    req = MagicMock(spec=web.Request)
    req.method = method
    req.path = path
    req.headers = {"Authorization": "Bearer test-token"}

    # match_info needs to be a dict-like object with .get()
    info = match_info or {}
    req.match_info = info

    if body is not None:
        req.content_length = 100
        req.json = AsyncMock(return_value=body)
        body_bytes = json.dumps(body).encode()
        req.read = AsyncMock(return_value=body_bytes)
    else:
        req.content_length = 0
        req.json = AsyncMock(side_effect=json.JSONDecodeError("", "", 0))
        req.read = AsyncMock(return_value=b"")

    return req


# ============================================================================
# Mock data builders
# ============================================================================


def _make_threat_result(
    target: str = "https://example.com",
    target_type: str = "url",
    is_malicious: bool = False,
    threat_type: ThreatType = ThreatType.NONE,
):
    """Build a mock ThreatResult with a working to_dict()."""
    result = MagicMock()
    result.target = target
    result.target_type = target_type
    result.is_malicious = is_malicious
    result.threat_type = threat_type
    result.to_dict.return_value = {
        "target": target,
        "target_type": target_type,
        "is_malicious": is_malicious,
        "threat_type": threat_type.value,
        "severity": "NONE",
        "confidence": 0.0,
        "threat_score": 0.0,
        "sources": [],
        "details": {},
        "cached": False,
    }
    return result


def _make_ip_result(
    ip_address: str = "1.2.3.4",
    is_malicious: bool = False,
    abuse_score: int = 0,
):
    """Build a mock IPReputationResult."""
    result = MagicMock()
    result.ip_address = ip_address
    result.is_malicious = is_malicious
    result.abuse_score = abuse_score
    result.to_dict.return_value = {
        "ip_address": ip_address,
        "is_malicious": is_malicious,
        "abuse_score": abuse_score,
        "total_reports": 0,
        "last_reported": None,
        "country_code": None,
        "isp": None,
        "domain": None,
        "usage_type": None,
        "categories": [],
        "is_tor": False,
        "is_vpn": False,
        "is_proxy": False,
        "is_datacenter": False,
    }
    return result


def _make_hash_result(
    hash_value: str = "abc123def456",
    hash_type: str = "sha256",
    is_malware: bool = False,
):
    """Build a mock FileHashResult."""
    result = MagicMock()
    result.hash_value = hash_value
    result.hash_type = hash_type
    result.is_malware = is_malware
    result.to_dict.return_value = {
        "hash_value": hash_value,
        "hash_type": hash_type,
        "is_malware": is_malware,
        "malware_names": [],
        "detection_ratio": "0/70",
        "first_seen": None,
        "last_seen": None,
        "file_type": None,
        "file_size": None,
        "tags": [],
    }
    return result


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def bypass_require_auth(monkeypatch):
    """Bypass the @require_auth decorator's token check.

    The decorator is already applied to handler methods at import time, so we
    patch the auth_config singleton it reads at call time to accept any token.
    """
    from aragora.server import auth as _auth_mod

    monkeypatch.setattr(_auth_mod.auth_config, "api_token", "test-token")
    monkeypatch.setattr(_auth_mod.auth_config, "validate_token", lambda token, loop_id="": True)


@pytest.fixture
def mock_service():
    """Create a mock ThreatIntelligenceService."""
    svc = MagicMock()
    svc.check_url = AsyncMock()
    svc.check_urls_batch = AsyncMock()
    svc.check_ip = AsyncMock()
    svc.check_file_hash = AsyncMock()
    svc.check_email_content = AsyncMock()
    svc.config = MagicMock()
    svc.config.enable_virustotal = True
    svc.config.virustotal_api_key = "test-key"
    svc.config.virustotal_rate_limit = 4
    svc.config.enable_abuseipdb = True
    svc.config.abuseipdb_api_key = ""
    svc.config.abuseipdb_rate_limit = 60
    svc.config.enable_phishtank = True
    svc.config.phishtank_api_key = ""
    svc.config.phishtank_rate_limit = 30
    svc.config.enable_caching = True
    svc.config.cache_ttl_hours = 24
    return svc


@pytest.fixture
def handler(mock_service):
    """Create a ThreatIntelHandler with mocked service."""
    with patch(
        "aragora.server.handlers.threat_intel.get_threat_service",
        return_value=mock_service,
    ):
        h = ThreatIntelHandler()
    h.service = mock_service
    return h


# ============================================================================
# Initialization
# ============================================================================


class TestHandlerInit:
    """Test handler initialization."""

    def test_handler_creates_with_default_context(self):
        with patch("aragora.server.handlers.threat_intel.get_threat_service") as mock_get:
            mock_get.return_value = MagicMock()
            h = ThreatIntelHandler()
            assert h.service is not None

    def test_handler_creates_with_provided_context(self):
        ctx = {"key": "value"}
        with patch("aragora.server.handlers.threat_intel.get_threat_service") as mock_get:
            mock_get.return_value = MagicMock()
            h = ThreatIntelHandler(server_context=ctx)
            assert h.service is not None

    def test_routes_defined(self):
        assert "/api/v1/threat/url" in ThreatIntelHandler.ROUTES
        assert "/api/v1/threat/urls" in ThreatIntelHandler.ROUTES
        assert "/api/v1/threat/ips" in ThreatIntelHandler.ROUTES
        assert "/api/v1/threat/hashes" in ThreatIntelHandler.ROUTES
        assert "/api/v1/threat/email" in ThreatIntelHandler.ROUTES
        assert "/api/v1/threat/status" in ThreatIntelHandler.ROUTES

    def test_routes_count(self):
        assert len(ThreatIntelHandler.ROUTES) == 6


class TestGetThreatService:
    """Test the lazy service singleton."""

    def test_get_service_creates_instance(self):
        import aragora.server.handlers.threat_intel as mod

        original = mod._threat_service
        try:
            mod._threat_service = None
            with patch(
                "aragora.server.handlers.threat_intel.ThreatIntelligenceService"
            ) as mock_cls:
                mock_cls.return_value = MagicMock()
                svc = get_threat_service()
                assert svc is not None
                mock_cls.assert_called_once()
        finally:
            mod._threat_service = original

    def test_get_service_returns_cached(self):
        import aragora.server.handlers.threat_intel as mod

        original = mod._threat_service
        try:
            sentinel = MagicMock()
            mod._threat_service = sentinel
            svc = get_threat_service()
            assert svc is sentinel
        finally:
            mod._threat_service = original


# ============================================================================
# URL Scanning - Single
# ============================================================================


class TestCheckUrl:
    """Test POST /api/v1/threat/url endpoint."""

    @pytest.mark.asyncio
    async def test_check_url_success(self, handler, mock_service):
        threat_result = _make_threat_result("https://example.com")
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://example.com"})
        result = await handler.check_url(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["target"] == "https://example.com"
        assert body["is_malicious"] is False

    @pytest.mark.asyncio
    async def test_check_url_malicious(self, handler, mock_service):
        threat_result = _make_threat_result(
            "https://evil.com", is_malicious=True, threat_type=ThreatType.PHISHING
        )
        threat_result.to_dict.return_value["is_malicious"] = True
        threat_result.to_dict.return_value["threat_type"] = "phishing"
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://evil.com"})
        result = await handler.check_url(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["is_malicious"] is True

    @pytest.mark.asyncio
    async def test_check_url_auto_prefix_https(self, handler, mock_service):
        """URL without scheme gets https:// prefix."""
        threat_result = _make_threat_result("https://example.com")
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 200
        mock_service.check_url.assert_called_once_with(
            url="https://example.com",
            check_virustotal=True,
            check_phishtank=True,
        )

    @pytest.mark.asyncio
    async def test_check_url_preserves_http(self, handler, mock_service):
        """URL with http:// is not changed to https."""
        threat_result = _make_threat_result("http://example.com")
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "http://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 200
        mock_service.check_url.assert_called_once_with(
            url="http://example.com",
            check_virustotal=True,
            check_phishtank=True,
        )

    @pytest.mark.asyncio
    async def test_check_url_custom_flags(self, handler, mock_service):
        """Disable specific checks via request body flags."""
        threat_result = _make_threat_result()
        mock_service.check_url.return_value = threat_result

        req = _make_request(
            "POST",
            "/api/v1/threat/url",
            {"url": "https://test.com", "check_virustotal": False, "check_phishtank": False},
        )
        result = await handler.check_url(req)

        assert result.status_code == 200
        mock_service.check_url.assert_called_once_with(
            url="https://test.com",
            check_virustotal=False,
            check_phishtank=False,
        )

    @pytest.mark.asyncio
    async def test_check_url_empty_url(self, handler, mock_service):
        """Empty URL string returns 400."""
        req = _make_request("POST", "/api/v1/threat/url", {"url": ""})
        result = await handler.check_url(req)

        assert result.status_code == 400
        body = _body(result)
        assert "required" in body["error"].lower() or "URL" in body["error"]

    @pytest.mark.asyncio
    async def test_check_url_whitespace_only(self, handler, mock_service):
        """Whitespace-only URL returns 400."""
        req = _make_request("POST", "/api/v1/threat/url", {"url": "   "})
        result = await handler.check_url(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_url_missing_field(self, handler, mock_service):
        """Missing 'url' field returns 400."""
        req = _make_request("POST", "/api/v1/threat/url", {"target": "https://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_url_strips_whitespace(self, handler, mock_service):
        """URL is stripped of leading/trailing whitespace."""
        threat_result = _make_threat_result("https://example.com")
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "  https://example.com  "})
        result = await handler.check_url(req)

        assert result.status_code == 200
        mock_service.check_url.assert_called_once_with(
            url="https://example.com",
            check_virustotal=True,
            check_phishtank=True,
        )

    @pytest.mark.asyncio
    async def test_check_url_connection_error(self, handler, mock_service):
        """ConnectionError from service returns 500."""
        mock_service.check_url.side_effect = ConnectionError("API unreachable")

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 500
        body = _body(result)
        assert "error" in body

    @pytest.mark.asyncio
    async def test_check_url_timeout_error(self, handler, mock_service):
        """TimeoutError from service returns 500."""
        mock_service.check_url.side_effect = TimeoutError("Request timed out")

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_url_os_error(self, handler, mock_service):
        """OSError from service returns 500."""
        mock_service.check_url.side_effect = OSError("Network failure")

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_url_value_error(self, handler, mock_service):
        """ValueError from service returns 500."""
        mock_service.check_url.side_effect = ValueError("Bad data")

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://example.com"})
        result = await handler.check_url(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_url_invalid_json_body(self, handler, mock_service):
        """Non-JSON body returns 400 from parse_json_body."""
        req = _make_request("POST", "/api/v1/threat/url")
        req.content_length = 10
        req.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
        req.read = AsyncMock(return_value=b"not json")

        result = await handler.check_url(req)
        assert hasattr(result, "status")
        assert result.status == 400


# ============================================================================
# URL Scanning - Batch
# ============================================================================


class TestCheckUrlsBatch:
    """Test POST /api/v1/threat/urls endpoint."""

    @pytest.mark.asyncio
    async def test_batch_urls_success(self, handler, mock_service):
        r1 = _make_threat_result("https://a.com")
        r2 = _make_threat_result("https://b.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1, r2.target: r2}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com", "https://b.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["summary"]["total"] == 2
        assert body["summary"]["clean"] == 2
        assert body["summary"]["malicious"] == 0

    @pytest.mark.asyncio
    async def test_batch_urls_with_malicious(self, handler, mock_service):
        r1 = _make_threat_result("https://good.com", is_malicious=False)
        r2 = _make_threat_result(
            "https://bad.com", is_malicious=True, threat_type=ThreatType.PHISHING
        )
        mock_service.check_urls_batch.return_value = {r1.target: r1, r2.target: r2}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://good.com", "https://bad.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert body["summary"]["malicious"] == 1
        assert body["summary"]["clean"] == 1

    @pytest.mark.asyncio
    async def test_batch_urls_with_suspicious(self, handler, mock_service):
        r1 = _make_threat_result(
            "https://sus.com", is_malicious=False, threat_type=ThreatType.SUSPICIOUS
        )
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://sus.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert body["summary"]["suspicious"] == 1
        assert body["summary"]["clean"] == 0
        assert body["summary"]["malicious"] == 0

    @pytest.mark.asyncio
    async def test_batch_urls_suspicious_but_malicious_not_counted_twice(
        self, handler, mock_service
    ):
        """A malicious+suspicious result should only count as malicious."""
        r1 = _make_threat_result(
            "https://bad.com", is_malicious=True, threat_type=ThreatType.SUSPICIOUS
        )
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://bad.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert body["summary"]["malicious"] == 1
        assert body["summary"]["suspicious"] == 0

    @pytest.mark.asyncio
    async def test_batch_urls_empty_list(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/urls", {"urls": []})
        result = await handler.check_urls_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_urls_missing_field(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/urls", {"targets": ["a", "b"]})
        result = await handler.check_urls_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_urls_over_limit(self, handler, mock_service):
        urls = [f"https://site{i}.com" for i in range(51)]
        req = _make_request("POST", "/api/v1/threat/urls", {"urls": urls})
        result = await handler.check_urls_batch(req)

        assert result.status_code == 400
        body = _body(result)
        assert "50" in body["error"]

    @pytest.mark.asyncio
    async def test_batch_urls_exactly_50(self, handler, mock_service):
        urls = [f"https://site{i}.com" for i in range(50)]
        results = [_make_threat_result(u) for u in urls]
        mock_service.check_urls_batch.return_value = {r.target: r for r in results}

        req = _make_request("POST", "/api/v1/threat/urls", {"urls": urls})
        result = await handler.check_urls_batch(req)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_batch_urls_max_concurrent_capped(self, handler, mock_service):
        r1 = _make_threat_result("https://a.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com"], "max_concurrent": 100},
        )
        result = await handler.check_urls_batch(req)

        assert result.status_code == 200
        mock_service.check_urls_batch.assert_called_once_with(
            urls=["https://a.com"],
            max_concurrent=10,
        )

    @pytest.mark.asyncio
    async def test_batch_urls_default_concurrent(self, handler, mock_service):
        r1 = _make_threat_result("https://a.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com"]},
        )
        result = await handler.check_urls_batch(req)

        assert result.status_code == 200
        mock_service.check_urls_batch.assert_called_once_with(
            urls=["https://a.com"],
            max_concurrent=5,
        )

    @pytest.mark.asyncio
    async def test_batch_urls_connection_error(self, handler, mock_service):
        mock_service.check_urls_batch.side_effect = ConnectionError("fail")

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com"]},
        )
        result = await handler.check_urls_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_batch_urls_results_serialized(self, handler, mock_service):
        r1 = _make_threat_result("https://a.com")
        r2 = _make_threat_result("https://b.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1, r2.target: r2}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com", "https://b.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert len(body["results"]) == 2
        assert body["results"][0]["target"] == "https://a.com"
        assert body["results"][1]["target"] == "https://b.com"


# ============================================================================
# IP Reputation - Single
# ============================================================================


class TestCheckIp:
    """Test GET /api/v1/threat/ip/{ip_address} endpoint."""

    @pytest.mark.asyncio
    async def test_check_ip_success(self, handler, mock_service):
        ip_result = _make_ip_result("1.2.3.4")
        mock_service.check_ip.return_value = ip_result

        req = _make_request("GET", match_info={"ip_address": "1.2.3.4"})
        result = await handler.check_ip(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["ip_address"] == "1.2.3.4"
        assert body["is_malicious"] is False

    @pytest.mark.asyncio
    async def test_check_ip_malicious(self, handler, mock_service):
        ip_result = _make_ip_result("5.6.7.8", is_malicious=True, abuse_score=95)
        ip_result.to_dict.return_value["is_malicious"] = True
        ip_result.to_dict.return_value["abuse_score"] = 95
        mock_service.check_ip.return_value = ip_result

        req = _make_request("GET", match_info={"ip_address": "5.6.7.8"})
        result = await handler.check_ip(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["is_malicious"] is True
        assert body["abuse_score"] == 95

    @pytest.mark.asyncio
    async def test_check_ip_missing_address(self, handler, mock_service):
        req = _make_request("GET", match_info={})
        result = await handler.check_ip(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_ip_empty_address(self, handler, mock_service):
        req = _make_request("GET", match_info={"ip_address": ""})
        result = await handler.check_ip(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_ip_connection_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = ConnectionError("fail")

        req = _make_request("GET", match_info={"ip_address": "1.2.3.4"})
        result = await handler.check_ip(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_ip_timeout_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = TimeoutError("timeout")

        req = _make_request("GET", match_info={"ip_address": "1.2.3.4"})
        result = await handler.check_ip(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_ip_os_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = OSError("os error")

        req = _make_request("GET", match_info={"ip_address": "1.2.3.4"})
        result = await handler.check_ip(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_ip_value_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = ValueError("bad")

        req = _make_request("GET", match_info={"ip_address": "1.2.3.4"})
        result = await handler.check_ip(req)

        assert result.status_code == 500


# ============================================================================
# IP Reputation - Batch
# ============================================================================


class TestCheckIpsBatch:
    """Test POST /api/v1/threat/ips endpoint."""

    @pytest.mark.asyncio
    async def test_batch_ips_success(self, handler, mock_service):
        ip1 = _make_ip_result("1.2.3.4")
        ip2 = _make_ip_result("5.6.7.8")
        mock_service.check_ip.side_effect = [ip1, ip2]

        req = _make_request(
            "POST",
            "/api/v1/threat/ips",
            {"ips": ["1.2.3.4", "5.6.7.8"]},
        )
        result = await handler.check_ips_batch(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["summary"]["total"] == 2
        assert body["summary"]["clean"] == 2
        assert body["summary"]["malicious"] == 0

    @pytest.mark.asyncio
    async def test_batch_ips_with_malicious(self, handler, mock_service):
        ip1 = _make_ip_result("1.2.3.4", is_malicious=False)
        ip2 = _make_ip_result("10.0.0.1", is_malicious=True, abuse_score=90)
        ip2.to_dict.return_value["is_malicious"] = True
        mock_service.check_ip.side_effect = [ip1, ip2]

        req = _make_request(
            "POST",
            "/api/v1/threat/ips",
            {"ips": ["1.2.3.4", "10.0.0.1"]},
        )
        result = await handler.check_ips_batch(req)

        body = _body(result)
        assert body["summary"]["malicious"] == 1
        assert body["summary"]["clean"] == 1

    @pytest.mark.asyncio
    async def test_batch_ips_empty_list(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/ips", {"ips": []})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_ips_missing_field(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/ips", {"addresses": ["1.2.3.4"]})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_ips_over_limit(self, handler, mock_service):
        ips = [f"1.2.3.{i}" for i in range(21)]
        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ips})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 400
        body = _body(result)
        assert "20" in body["error"]

    @pytest.mark.asyncio
    async def test_batch_ips_exactly_20(self, handler, mock_service):
        ips = [f"1.2.3.{i}" for i in range(20)]
        mock_service.check_ip.side_effect = [_make_ip_result(ip) for ip in ips]

        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ips})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 200
        body = _body(result)
        assert body["summary"]["total"] == 20

    @pytest.mark.asyncio
    async def test_batch_ips_connection_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = ConnectionError("fail")

        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ["1.2.3.4"]})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_batch_ips_single_ip(self, handler, mock_service):
        ip1 = _make_ip_result("192.168.1.1")
        mock_service.check_ip.return_value = ip1

        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ["192.168.1.1"]})
        result = await handler.check_ips_batch(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["summary"]["total"] == 1


# ============================================================================
# File Hash - Single
# ============================================================================


class TestCheckHash:
    """Test GET /api/v1/threat/hash/{hash_value} endpoint."""

    @pytest.mark.asyncio
    async def test_check_hash_success(self, handler, mock_service):
        hash_result = _make_hash_result("abc123def456")
        mock_service.check_file_hash.return_value = hash_result

        req = _make_request("GET", match_info={"hash_value": "abc123def456"})
        result = await handler.check_hash(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["hash_value"] == "abc123def456"
        assert body["is_malware"] is False

    @pytest.mark.asyncio
    async def test_check_hash_malware(self, handler, mock_service):
        hash_result = _make_hash_result("evil_hash", is_malware=True)
        hash_result.to_dict.return_value["is_malware"] = True
        hash_result.to_dict.return_value["malware_names"] = ["Trojan.Win32"]
        mock_service.check_file_hash.return_value = hash_result

        req = _make_request("GET", match_info={"hash_value": "evil_hash"})
        result = await handler.check_hash(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["is_malware"] is True
        assert "Trojan.Win32" in body["malware_names"]

    @pytest.mark.asyncio
    async def test_check_hash_missing_value(self, handler, mock_service):
        req = _make_request("GET", match_info={})
        result = await handler.check_hash(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_hash_empty_value(self, handler, mock_service):
        req = _make_request("GET", match_info={"hash_value": ""})
        result = await handler.check_hash(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_hash_connection_error(self, handler, mock_service):
        mock_service.check_file_hash.side_effect = ConnectionError("fail")

        req = _make_request("GET", match_info={"hash_value": "abc123"})
        result = await handler.check_hash(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_hash_timeout_error(self, handler, mock_service):
        mock_service.check_file_hash.side_effect = TimeoutError()

        req = _make_request("GET", match_info={"hash_value": "abc123"})
        result = await handler.check_hash(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_hash_value_error(self, handler, mock_service):
        mock_service.check_file_hash.side_effect = ValueError("invalid")

        req = _make_request("GET", match_info={"hash_value": "abc123"})
        result = await handler.check_hash(req)

        assert result.status_code == 500


# ============================================================================
# File Hash - Batch
# ============================================================================


class TestCheckHashesBatch:
    """Test POST /api/v1/threat/hashes endpoint."""

    @pytest.mark.asyncio
    async def test_batch_hashes_success(self, handler, mock_service):
        h1 = _make_hash_result("hash1")
        h2 = _make_hash_result("hash2")
        mock_service.check_file_hash.side_effect = [h1, h2]

        req = _make_request(
            "POST",
            "/api/v1/threat/hashes",
            {"hashes": ["hash1", "hash2"]},
        )
        result = await handler.check_hashes_batch(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["summary"]["total"] == 2
        assert body["summary"]["clean"] == 2
        assert body["summary"]["malware"] == 0

    @pytest.mark.asyncio
    async def test_batch_hashes_with_malware(self, handler, mock_service):
        h1 = _make_hash_result("clean_hash", is_malware=False)
        h2 = _make_hash_result("bad_hash", is_malware=True)
        h2.to_dict.return_value["is_malware"] = True
        mock_service.check_file_hash.side_effect = [h1, h2]

        req = _make_request(
            "POST",
            "/api/v1/threat/hashes",
            {"hashes": ["clean_hash", "bad_hash"]},
        )
        result = await handler.check_hashes_batch(req)

        body = _body(result)
        assert body["summary"]["malware"] == 1
        assert body["summary"]["clean"] == 1

    @pytest.mark.asyncio
    async def test_batch_hashes_empty_list(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": []})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_hashes_missing_field(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/hashes", {"files": ["hash1"]})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_hashes_over_limit(self, handler, mock_service):
        hashes = [f"hash_{i}" for i in range(21)]
        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": hashes})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 400
        body = _body(result)
        assert "20" in body["error"]

    @pytest.mark.asyncio
    async def test_batch_hashes_exactly_20(self, handler, mock_service):
        hashes = [f"hash_{i}" for i in range(20)]
        mock_service.check_file_hash.side_effect = [_make_hash_result(h) for h in hashes]

        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": hashes})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 200
        body = _body(result)
        assert body["summary"]["total"] == 20

    @pytest.mark.asyncio
    async def test_batch_hashes_connection_error(self, handler, mock_service):
        mock_service.check_file_hash.side_effect = ConnectionError("fail")

        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": ["hash1"]})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_batch_hashes_results_serialized(self, handler, mock_service):
        h1 = _make_hash_result("aaa")
        h2 = _make_hash_result("bbb")
        mock_service.check_file_hash.side_effect = [h1, h2]

        req = _make_request(
            "POST",
            "/api/v1/threat/hashes",
            {"hashes": ["aaa", "bbb"]},
        )
        result = await handler.check_hashes_batch(req)

        body = _body(result)
        assert len(body["results"]) == 2
        assert body["results"][0]["hash_value"] == "aaa"


# ============================================================================
# Email Content Scanning
# ============================================================================


class TestScanEmailContent:
    """Test POST /api/v1/threat/email endpoint."""

    @pytest.mark.asyncio
    async def test_scan_email_success(self, handler, mock_service):
        mock_service.check_email_content.return_value = {
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }

        req = _make_request(
            "POST",
            "/api/v1/threat/email",
            {"body": "Hello, this is a normal email."},
        )
        result = await handler.scan_email_content(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["is_suspicious"] is False
        assert body["overall_threat_score"] == 0

    @pytest.mark.asyncio
    async def test_scan_email_with_urls(self, handler, mock_service):
        mock_service.check_email_content.return_value = {
            "urls": [{"target": "https://evil.com", "is_malicious": True}],
            "ips": [],
            "overall_threat_score": 85,
            "is_suspicious": True,
            "threat_summary": ["Found 1 malicious URLs"],
        }

        req = _make_request(
            "POST",
            "/api/v1/threat/email",
            {"body": "Check out https://evil.com"},
        )
        result = await handler.scan_email_content(req)

        body = _body(result)
        assert result.status_code == 200
        assert body["is_suspicious"] is True
        assert body["overall_threat_score"] == 85

    @pytest.mark.asyncio
    async def test_scan_email_with_headers(self, handler, mock_service):
        mock_service.check_email_content.return_value = {
            "urls": [],
            "ips": [{"ip_address": "10.0.0.1", "is_malicious": True}],
            "overall_threat_score": 70,
            "is_suspicious": True,
            "threat_summary": ["Suspicious IP in headers"],
        }

        req = _make_request(
            "POST",
            "/api/v1/threat/email",
            {"body": "Email body text", "headers": {"Received": "from [10.0.0.1]"}},
        )
        result = await handler.scan_email_content(req)

        body = _body(result)
        assert result.status_code == 200
        mock_service.check_email_content.assert_called_once_with(
            email_body="Email body text",
            email_headers={"Received": "from [10.0.0.1]"},
        )

    @pytest.mark.asyncio
    async def test_scan_email_empty_body(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/email", {"body": ""})
        result = await handler.scan_email_content(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_email_missing_body_field(self, handler, mock_service):
        req = _make_request("POST", "/api/v1/threat/email", {"content": "hello"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_email_no_headers_defaults(self, handler, mock_service):
        mock_service.check_email_content.return_value = {
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }

        req = _make_request("POST", "/api/v1/threat/email", {"body": "Normal email"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 200
        mock_service.check_email_content.assert_called_once_with(
            email_body="Normal email",
            email_headers={},
        )

    @pytest.mark.asyncio
    async def test_scan_email_connection_error(self, handler, mock_service):
        mock_service.check_email_content.side_effect = ConnectionError("fail")

        req = _make_request("POST", "/api/v1/threat/email", {"body": "Hello"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_scan_email_timeout_error(self, handler, mock_service):
        mock_service.check_email_content.side_effect = TimeoutError("timeout")

        req = _make_request("POST", "/api/v1/threat/email", {"body": "Hello"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_scan_email_value_error(self, handler, mock_service):
        mock_service.check_email_content.side_effect = ValueError("bad")

        req = _make_request("POST", "/api/v1/threat/email", {"body": "Hello"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 500


# ============================================================================
# Service Status
# ============================================================================


class TestGetStatus:
    """Test GET /api/v1/threat/status endpoint."""

    @pytest.mark.asyncio
    async def test_status_success(self, handler, mock_service):
        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert result.status_code == 200
        assert "virustotal" in body
        assert "abuseipdb" in body
        assert "phishtank" in body
        assert "caching" in body

    @pytest.mark.asyncio
    async def test_status_shows_enabled_fields(self, handler, mock_service):
        mock_service.config.enable_virustotal = True
        mock_service.config.enable_abuseipdb = False
        mock_service.config.enable_phishtank = True

        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert body["virustotal"]["enabled"] is True
        assert body["abuseipdb"]["enabled"] is False
        assert body["phishtank"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_status_shows_has_key(self, handler, mock_service):
        mock_service.config.virustotal_api_key = "some-key"
        mock_service.config.abuseipdb_api_key = ""
        mock_service.config.phishtank_api_key = None

        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert body["virustotal"]["has_key"] is True
        assert body["abuseipdb"]["has_key"] is False
        assert body["phishtank"]["has_key"] is False

    @pytest.mark.asyncio
    async def test_status_shows_rate_limits(self, handler, mock_service):
        mock_service.config.virustotal_rate_limit = 4
        mock_service.config.abuseipdb_rate_limit = 60
        mock_service.config.phishtank_rate_limit = 30

        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert body["virustotal"]["rate_limit"] == 4
        assert body["abuseipdb"]["rate_limit"] == 60
        assert body["phishtank"]["rate_limit"] == 30

    @pytest.mark.asyncio
    async def test_status_shows_cache_settings(self, handler, mock_service):
        mock_service.config.enable_caching = True
        mock_service.config.cache_ttl_hours = 24

        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert body["caching"] is True
        assert body["cache_ttl_hours"] == 24

    @pytest.mark.asyncio
    async def test_status_caching_disabled(self, handler, mock_service):
        mock_service.config.enable_caching = False

        req = _make_request("GET")
        result = await handler.get_status(req)

        body = _body(result)
        assert body["caching"] is False

    @pytest.mark.asyncio
    async def test_status_attribute_error(self, handler, mock_service):
        mock_service.config = None

        req = _make_request("GET")
        result = await handler.get_status(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_status_type_error(self, handler, mock_service):
        bad_config = MagicMock()
        type(bad_config).enable_virustotal = property(
            lambda self: (_ for _ in ()).throw(TypeError("bad"))
        )
        mock_service.config = bad_config

        req = _make_request("GET")
        result = await handler.get_status(req)

        assert result.status_code == 500


# ============================================================================
# Route Registration
# ============================================================================


class TestRegisterRoutes:
    """Test route registration."""

    def test_register_routes_adds_all(self):
        app = web.Application()
        with patch("aragora.server.handlers.threat_intel.get_threat_service") as mock_get:
            mock_get.return_value = MagicMock()
            register_threat_intel_routes(app)

        routes = [
            r.resource.canonical for r in app.router.routes() if hasattr(r.resource, "canonical")
        ]
        assert "/api/v1/threat/url" in routes
        assert "/api/v1/threat/urls" in routes
        assert "/api/v1/threat/ip/{ip_address}" in routes
        assert "/api/v1/threat/ips" in routes
        assert "/api/v1/threat/hash/{hash_value}" in routes
        assert "/api/v1/threat/hashes" in routes
        assert "/api/v1/threat/email" in routes
        assert "/api/v1/threat/status" in routes

    def test_register_routes_count(self):
        app = web.Application()
        with patch("aragora.server.handlers.threat_intel.get_threat_service") as mock_get:
            mock_get.return_value = MagicMock()
            register_threat_intel_routes(app)

        # aiohttp adds extra routes (HEAD for GET endpoints), so count
        # the unique resource canonical paths instead
        resources = {
            r.resource.canonical for r in app.router.routes() if hasattr(r.resource, "canonical")
        }
        assert len(resources) == 8


# ============================================================================
# Module Exports
# ============================================================================


class TestModuleExports:
    """Test that module __all__ exports are correct."""

    def test_exports_handler_class(self):
        from aragora.server.handlers import threat_intel

        assert hasattr(threat_intel, "ThreatIntelHandler")

    def test_exports_register_function(self):
        from aragora.server.handlers import threat_intel

        assert hasattr(threat_intel, "register_threat_intel_routes")

    def test_exports_get_service_function(self):
        from aragora.server.handlers import threat_intel

        assert hasattr(threat_intel, "get_threat_service")

    def test_all_contains_expected_items(self):
        from aragora.server.handlers.threat_intel import __all__

        assert "ThreatIntelHandler" in __all__
        assert "register_threat_intel_routes" in __all__
        assert "get_threat_service" in __all__


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_url_with_only_scheme(self, handler, mock_service):
        threat_result = _make_threat_result("https://")
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://"})
        result = await handler.check_url(req)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_batch_urls_single_item(self, handler, mock_service):
        r1 = _make_threat_result("https://only.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://only.com"]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert body["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_batch_urls_max_concurrent_small_value(self, handler, mock_service):
        r1 = _make_threat_result("https://a.com")
        mock_service.check_urls_batch.return_value = {r1.target: r1}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com"], "max_concurrent": 1},
        )
        result = await handler.check_urls_batch(req)

        mock_service.check_urls_batch.assert_called_once_with(
            urls=["https://a.com"],
            max_concurrent=1,
        )

    @pytest.mark.asyncio
    async def test_email_scan_empty_headers(self, handler, mock_service):
        mock_service.check_email_content.return_value = {
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }

        req = _make_request(
            "POST",
            "/api/v1/threat/email",
            {"body": "Hello", "headers": {}},
        )
        result = await handler.scan_email_content(req)

        assert result.status_code == 200
        mock_service.check_email_content.assert_called_once_with(
            email_body="Hello",
            email_headers={},
        )

    @pytest.mark.asyncio
    async def test_batch_hashes_single_item(self, handler, mock_service):
        h1 = _make_hash_result("single_hash")
        mock_service.check_file_hash.return_value = h1

        req = _make_request(
            "POST",
            "/api/v1/threat/hashes",
            {"hashes": ["single_hash"]},
        )
        result = await handler.check_hashes_batch(req)

        body = _body(result)
        assert body["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_batch_urls_all_malicious(self, handler, mock_service):
        results = [_make_threat_result(f"https://bad{i}.com", is_malicious=True) for i in range(3)]
        mock_service.check_urls_batch.return_value = {r.target: r for r in results}

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": [f"https://bad{i}.com" for i in range(3)]},
        )
        result = await handler.check_urls_batch(req)

        body = _body(result)
        assert body["summary"]["malicious"] == 3
        assert body["summary"]["clean"] == 0
        assert body["summary"]["suspicious"] == 0

    @pytest.mark.asyncio
    async def test_batch_ips_all_malicious(self, handler, mock_service):
        ips = ["1.1.1.1", "2.2.2.2"]
        ip_results = [_make_ip_result(ip, is_malicious=True) for ip in ips]
        for r in ip_results:
            r.to_dict.return_value["is_malicious"] = True
        mock_service.check_ip.side_effect = ip_results

        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ips})
        result = await handler.check_ips_batch(req)

        body = _body(result)
        assert body["summary"]["malicious"] == 2
        assert body["summary"]["clean"] == 0

    @pytest.mark.asyncio
    async def test_batch_hashes_all_malware(self, handler, mock_service):
        hashes = ["h1", "h2", "h3"]
        hash_results = [_make_hash_result(h, is_malware=True) for h in hashes]
        for r in hash_results:
            r.to_dict.return_value["is_malware"] = True
        mock_service.check_file_hash.side_effect = hash_results

        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": hashes})
        result = await handler.check_hashes_batch(req)

        body = _body(result)
        assert body["summary"]["malware"] == 3
        assert body["summary"]["clean"] == 0

    @pytest.mark.asyncio
    async def test_check_url_default_flags_true(self, handler, mock_service):
        threat_result = _make_threat_result()
        mock_service.check_url.return_value = threat_result

        req = _make_request("POST", "/api/v1/threat/url", {"url": "https://test.com"})
        result = await handler.check_url(req)

        assert result.status_code == 200
        mock_service.check_url.assert_called_once_with(
            url="https://test.com",
            check_virustotal=True,
            check_phishtank=True,
        )

    @pytest.mark.asyncio
    async def test_email_scan_large_body(self, handler, mock_service):
        large_body = "A" * 10000
        mock_service.check_email_content.return_value = {
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }

        req = _make_request("POST", "/api/v1/threat/email", {"body": large_body})
        result = await handler.scan_email_content(req)

        assert result.status_code == 200
        mock_service.check_email_content.assert_called_once_with(
            email_body=large_body,
            email_headers={},
        )

    @pytest.mark.asyncio
    async def test_batch_urls_os_error(self, handler, mock_service):
        mock_service.check_urls_batch.side_effect = OSError("network")

        req = _make_request(
            "POST",
            "/api/v1/threat/urls",
            {"urls": ["https://a.com"]},
        )
        result = await handler.check_urls_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_batch_ips_timeout_error(self, handler, mock_service):
        mock_service.check_ip.side_effect = TimeoutError("slow")

        req = _make_request("POST", "/api/v1/threat/ips", {"ips": ["1.2.3.4"]})
        result = await handler.check_ips_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_batch_hashes_os_error(self, handler, mock_service):
        mock_service.check_file_hash.side_effect = OSError("disk")

        req = _make_request("POST", "/api/v1/threat/hashes", {"hashes": ["h1"]})
        result = await handler.check_hashes_batch(req)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_email_scan_os_error(self, handler, mock_service):
        mock_service.check_email_content.side_effect = OSError("io")

        req = _make_request("POST", "/api/v1/threat/email", {"body": "Hello"})
        result = await handler.scan_email_content(req)

        assert result.status_code == 500
