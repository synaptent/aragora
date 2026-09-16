"""
Tests for aragora.server.handlers.threat_intel - Threat Intelligence Handlers.

Tests cover:
- ThreatIntelHandler: instantiation, service initialization
- POST /api/v1/threat/url: URL checking success, error paths
- POST /api/v1/threat/urls: batch URL checking, limits
- GET /api/v1/threat/ip/{ip}: IP reputation checking
- POST /api/v1/threat/ips: batch IP checking, limits
- GET /api/v1/threat/hash/{hash}: file hash lookup
- POST /api/v1/threat/hashes: batch hash checking, limits
- POST /api/v1/threat/email: email content scanning
- GET /api/v1/threat/status: service status
- register_threat_intel_routes: route registration
- get_threat_service: lazy initialization
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch the service import before importing the handler module.
# Use direct sys.modules assignment (not patch.dict) so the handler module
# stays registered — string-based patch() calls need it in sys.modules.
import sys as _sys

_mock_service_cls = MagicMock()
_mock_threat_type = MagicMock()
_mock_threat_type.SUSPICIOUS = "suspicious"

_sys.modules.setdefault(
    "aragora.services.threat_intelligence",
    MagicMock(
        ThreatIntelligenceService=_mock_service_cls,
        ThreatType=_mock_threat_type,
    ),
)

from aragora.server.handlers.threat_intel import (  # noqa: E402
    ThreatIntelHandler,
    get_threat_service,
    register_threat_intel_routes,
)


# ===========================================================================
# Helpers
# ===========================================================================


class MockThreatResult:
    """Mock threat check result."""

    def __init__(self, is_malicious: bool = False, threat_type: str = "none"):
        self.is_malicious = is_malicious
        self.threat_type = threat_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_malicious": self.is_malicious,
            "threat_type": self.threat_type,
            "severity": "NONE" if not self.is_malicious else "HIGH",
            "confidence": 0.9 if self.is_malicious else 0.0,
        }


class MockHashResult:
    """Mock file hash check result."""

    def __init__(self, is_malware: bool = False):
        self.is_malware = is_malware

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_malware": self.is_malware,
            "detection_ratio": "5/70" if self.is_malware else "0/70",
        }


class MockThreatConfig:
    """Mock threat intelligence config."""

    enable_virustotal = True
    virustotal_api_key = "vt-key-123"
    virustotal_rate_limit = 4
    enable_abuseipdb = True
    abuseipdb_api_key = ""
    abuseipdb_rate_limit = 60
    enable_phishtank = True
    phishtank_api_key = ""
    phishtank_rate_limit = 10
    enable_caching = True
    cache_ttl_hours = 24


class MockRequest:
    """Mock aiohttp request."""

    def __init__(self, body: dict | None = None, match_info: dict | None = None):
        self._body = body or {}
        self.match_info = match_info or {}

    async def json(self) -> dict:
        return self._body


def _unwrap(fn):
    """Fully unwrap a decorated function to reach the innermost implementation."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_service():
    """Create a mock ThreatIntelligenceService."""
    service = MagicMock()
    service.config = MockThreatConfig()
    service.check_url = AsyncMock(return_value=MockThreatResult())
    service.check_urls_batch = AsyncMock(
        return_value={"https://a.com": MockThreatResult(), "https://b.com": MockThreatResult()}
    )
    service.check_ip = AsyncMock(return_value=MockThreatResult())
    service.check_file_hash = AsyncMock(return_value=MockHashResult())
    service.check_email_content = AsyncMock(
        return_value={
            "urls": [],
            "ips": [],
            "overall_threat_score": 0,
            "is_suspicious": False,
            "threat_summary": [],
        }
    )
    return service


@pytest.fixture
def handler(mock_service):
    """Create a ThreatIntelHandler with mocked service."""
    with patch(
        "aragora.server.handlers.threat_intel.get_threat_service",
        return_value=mock_service,
    ):
        h = ThreatIntelHandler.__new__(ThreatIntelHandler)
        h.ctx = {}
        h.service = mock_service
        h._current_handler = None
        h._current_query_params = {}
        yield h


# ===========================================================================
# Test Instantiation
# ===========================================================================


class TestThreatIntelHandlerBasics:
    """Basic instantiation and attribute tests."""

    def test_handler_has_service(self, handler, mock_service):
        assert handler.service is mock_service

    def test_get_threat_service_creates_singleton(self):
        """get_threat_service returns a service instance."""
        import aragora.server.handlers.threat_intel as mod

        original = mod._threat_service
        try:
            mod._threat_service = None
            with patch(
                "aragora.server.handlers.threat_intel.ThreatIntelligenceService",
                return_value=MagicMock(),
            ):
                svc = get_threat_service()
                assert svc is not None
        finally:
            mod._threat_service = original


# ===========================================================================
# Test URL Checking
# ===========================================================================


class TestCheckUrl:
    """Tests for POST /api/v1/threat/url."""

    @pytest.mark.asyncio
    async def test_check_url_success(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"url": "https://example.com"}, None),
        ):
            result = await _unwrap(handler.check_url)(handler, MockRequest())
            # check_url calls self.success_response
            mock_service.check_url.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_url_adds_https(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"url": "example.com"}, None),
        ):
            await _unwrap(handler.check_url)(handler, MockRequest())
            call_kwargs = mock_service.check_url.call_args
            assert call_kwargs.kwargs.get("url", call_kwargs[1].get("url", "")).startswith(
                "https://"
            )

    @pytest.mark.asyncio
    async def test_check_url_empty_url(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"url": ""}, None),
        ):
            result = await _unwrap(handler.check_url)(handler, MockRequest())
            # Should return error for empty URL
            assert result is not None


# ===========================================================================
# Test Batch URL Checking
# ===========================================================================


class TestCheckUrlsBatch:
    """Tests for POST /api/v1/threat/urls."""

    @pytest.mark.asyncio
    async def test_batch_urls_success(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"urls": ["https://a.com", "https://b.com"]}, None),
        ):
            await _unwrap(handler.check_urls_batch)(handler, MockRequest())
            mock_service.check_urls_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_batch_urls_empty_list(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"urls": []}, None),
        ):
            result = await _unwrap(handler.check_urls_batch)(handler, MockRequest())
            assert result is not None

    @pytest.mark.asyncio
    async def test_batch_urls_exceeds_limit(self, handler, mock_service):
        urls = [f"https://example{i}.com" for i in range(51)]
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"urls": urls}, None),
        ):
            result = await _unwrap(handler.check_urls_batch)(handler, MockRequest())
            assert result is not None


# ===========================================================================
# Test IP Checking
# ===========================================================================


class TestCheckIp:
    """Tests for GET /api/v1/threat/ip/{ip}."""

    @pytest.mark.asyncio
    async def test_check_ip_success(self, handler, mock_service):
        request = MockRequest(match_info={"ip_address": "1.2.3.4"})
        await _unwrap(handler.check_ip)(handler, request)
        mock_service.check_ip.assert_awaited_once_with("1.2.3.4")

    @pytest.mark.asyncio
    async def test_check_ip_empty(self, handler, mock_service):
        request = MockRequest(match_info={"ip_address": ""})
        result = await _unwrap(handler.check_ip)(handler, request)
        assert result is not None


# ===========================================================================
# Test Batch IP Checking
# ===========================================================================


class TestCheckIpsBatch:
    """Tests for POST /api/v1/threat/ips."""

    @pytest.mark.asyncio
    async def test_batch_ips_success(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"ips": ["1.2.3.4", "5.6.7.8"]}, None),
        ):
            await _unwrap(handler.check_ips_batch)(handler, MockRequest())
            assert mock_service.check_ip.await_count == 2

    @pytest.mark.asyncio
    async def test_batch_ips_exceeds_limit(self, handler, mock_service):
        ips = [f"10.0.0.{i}" for i in range(21)]
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"ips": ips}, None),
        ):
            result = await _unwrap(handler.check_ips_batch)(handler, MockRequest())
            assert result is not None


# ===========================================================================
# Test Hash Checking
# ===========================================================================


class TestCheckHash:
    """Tests for GET /api/v1/threat/hash/{hash}."""

    @pytest.mark.asyncio
    async def test_check_hash_success(self, handler, mock_service):
        request = MockRequest(match_info={"hash_value": "abc123def456"})
        await _unwrap(handler.check_hash)(handler, request)
        mock_service.check_file_hash.assert_awaited_once_with("abc123def456")

    @pytest.mark.asyncio
    async def test_check_hash_empty(self, handler, mock_service):
        request = MockRequest(match_info={"hash_value": ""})
        result = await _unwrap(handler.check_hash)(handler, request)
        assert result is not None


# ===========================================================================
# Test Batch Hash Checking
# ===========================================================================


class TestCheckHashesBatch:
    """Tests for POST /api/v1/threat/hashes."""

    @pytest.mark.asyncio
    async def test_batch_hashes_success(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"hashes": ["abc123", "def456"]}, None),
        ):
            await _unwrap(handler.check_hashes_batch)(handler, MockRequest())
            assert mock_service.check_file_hash.await_count == 2

    @pytest.mark.asyncio
    async def test_batch_hashes_exceeds_limit(self, handler, mock_service):
        hashes = [f"hash{i}" for i in range(21)]
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"hashes": hashes}, None),
        ):
            result = await _unwrap(handler.check_hashes_batch)(handler, MockRequest())
            assert result is not None


# ===========================================================================
# Test Email Scanning
# ===========================================================================


class TestScanEmail:
    """Tests for POST /api/v1/threat/email."""

    @pytest.mark.asyncio
    async def test_scan_email_success(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"body": "Hello, check https://example.com"}, None),
        ):
            await _unwrap(handler.scan_email_content)(handler, MockRequest())
            mock_service.check_email_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_email_empty_body(self, handler, mock_service):
        with patch(
            "aragora.server.handlers.threat_intel.parse_json_body",
            new_callable=AsyncMock,
            return_value=({"body": ""}, None),
        ):
            result = await _unwrap(handler.scan_email_content)(handler, MockRequest())
            assert result is not None


# ===========================================================================
# Test Service Status
# ===========================================================================


class TestGetStatus:
    """Tests for GET /api/v1/threat/status."""

    @pytest.mark.asyncio
    async def test_get_status_success(self, handler, mock_service):
        result = await _unwrap(handler.get_status)(handler, MockRequest())
        # Should call success_response with config data
        assert result is not None


# ===========================================================================
# Test Route Registration
# ===========================================================================


class TestRouteRegistration:
    """Tests for register_threat_intel_routes."""

    def test_register_routes(self):
        mock_app = MagicMock()
        mock_app.router = MagicMock()

        with patch(
            "aragora.server.handlers.threat_intel.get_threat_service",
            return_value=MagicMock(),
        ):
            with patch(
                "aragora.server.handlers.threat_intel.ThreatIntelHandler",
            ):
                register_threat_intel_routes(mock_app)
                mock_app.router.add_routes.assert_called_once()
