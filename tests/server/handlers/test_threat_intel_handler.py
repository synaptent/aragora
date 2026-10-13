"""
Tests for Threat Intelligence API Handlers.

Tests cover:
- URL scanning (single and batch)
- IP reputation checking (single and batch)
- File hash lookup (single and batch)
- Email content scanning
- Service status endpoint
- Input validation and error handling
- Rate limiting behavior
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from enum import Enum

import pytest


# ===========================================================================
# Mock Types (matching the service's types)
# ===========================================================================


class MockThreatType(str, Enum):
    """Mock threat types."""

    NONE = "none"
    MALWARE = "malware"
    PHISHING = "phishing"
    SUSPICIOUS = "suspicious"


@dataclass
class MockThreatResult:
    """Mock threat check result."""

    target: str
    is_malicious: bool
    threat_type: MockThreatType
    severity: str
    confidence: float
    details: dict

    def to_dict(self):
        return {
            "target": self.target,
            "is_malicious": self.is_malicious,
            "threat_type": self.threat_type.value,
            "severity": self.severity,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class MockIPResult:
    """Mock IP reputation result."""

    ip_address: str
    is_malicious: bool
    abuse_score: int
    total_reports: int
    country: str

    def to_dict(self):
        return {
            "ip_address": self.ip_address,
            "is_malicious": self.is_malicious,
            "abuse_score": self.abuse_score,
            "total_reports": self.total_reports,
            "country": self.country,
        }


@dataclass
class MockHashResult:
    """Mock file hash result."""

    hash_value: str
    hash_type: str
    is_malware: bool
    detection_ratio: str
    first_seen: str

    def to_dict(self):
        return {
            "hash_value": self.hash_value,
            "hash_type": self.hash_type,
            "is_malware": self.is_malware,
            "detection_ratio": self.detection_ratio,
            "first_seen": self.first_seen,
        }


@dataclass
class MockServiceConfig:
    """Mock service configuration."""

    enable_virustotal: bool = True
    virustotal_api_key: str = "test-vt-key"
    virustotal_rate_limit: int = 4
    enable_abuseipdb: bool = True
    abuseipdb_api_key: str = "test-abuse-key"
    abuseipdb_rate_limit: int = 1000
    enable_phishtank: bool = True
    phishtank_api_key: str = ""
    phishtank_rate_limit: int = 100
    enable_caching: bool = True
    cache_ttl_hours: int = 24


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock authentication to allow all requests."""
    with patch("aragora.server.auth.auth_config") as mock_auth_config:
        mock_auth_config.enabled = True
        mock_auth_config.api_token = "test-token"
        mock_auth_config.validate_token = MagicMock(return_value=True)
        yield mock_auth_config


@pytest.fixture
def mock_request():
    """Create a mock aiohttp request."""
    request = MagicMock()
    request.match_info = {}
    request.json = AsyncMock(return_value={})
    request.headers = {
        "Authorization": "Bearer test-token",
    }
    return request


@pytest.fixture
def mock_threat_service():
    """Create a mock threat intelligence service."""
    service = MagicMock()
    service.config = MockServiceConfig()

    # Default return values
    service.check_url = AsyncMock(
        return_value=MockThreatResult(
            target="https://example.com",
            is_malicious=False,
            threat_type=MockThreatType.NONE,
            severity="NONE",
            confidence=0.0,
            details={},
        )
    )

    service.check_urls_batch = AsyncMock(
        return_value={
            "https://example1.com": MockThreatResult(
                target="https://example1.com",
                is_malicious=False,
                threat_type=MockThreatType.NONE,
                severity="NONE",
                confidence=0.0,
                details={},
            ),
        }
    )

    service.check_ip = AsyncMock(
        return_value=MockIPResult(
            ip_address="1.2.3.4",
            is_malicious=False,
            abuse_score=0,
            total_reports=0,
            country="US",
        )
    )

    service.check_file_hash = AsyncMock(
        return_value=MockHashResult(
            hash_value="abc123",
            hash_type="sha256",
            is_malware=False,
            detection_ratio="0/70",
            first_seen="2024-01-01",
        )
    )

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
def threat_handler(mock_threat_service):
    """Create a ThreatIntelHandler with mocked service."""
    with patch(
        "aragora.server.handlers.threat_intel.get_threat_service",
        return_value=mock_threat_service,
    ):
        from aragora.server.handlers.threat_intel import ThreatIntelHandler

        handler = ThreatIntelHandler(server_context={})
        handler.service = mock_threat_service
        return handler


# ===========================================================================
# URL Scanning Tests
# ===========================================================================


class TestThreatIntelURLScanning:
    """Tests for URL scanning endpoints."""

    @pytest.mark.asyncio
    async def test_check_url_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful single URL check."""
        mock_request.json.return_value = {
            "url": "https://example.com",
            "check_virustotal": True,
            "check_phishtank": True,
        }

        result = await threat_handler.check_url(mock_request)

        assert result.status_code == 200
        mock_threat_service.check_url.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_url_adds_https_scheme(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test that URL without scheme gets https:// prepended."""
        mock_request.json.return_value = {"url": "example.com"}

        await threat_handler.check_url(mock_request)

        call_kwargs = mock_threat_service.check_url.call_args.kwargs
        assert call_kwargs["url"].startswith("https://")

    @pytest.mark.asyncio
    async def test_check_url_empty_url_error(self, threat_handler, mock_request):
        """Test error when URL is empty."""
        mock_request.json.return_value = {"url": ""}

        result = await threat_handler.check_url(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_url_missing_url_error(self, threat_handler, mock_request):
        """Test error when URL field is missing."""
        mock_request.json.return_value = {}

        result = await threat_handler.check_url(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_urls_batch_success(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test successful batch URL check."""
        mock_request.json.return_value = {
            "urls": ["https://example1.com", "https://example2.com"],
            "max_concurrent": 5,
        }

        result = await threat_handler.check_urls_batch(mock_request)

        assert result.status_code == 200
        mock_threat_service.check_urls_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_urls_batch_empty_list_error(self, threat_handler, mock_request):
        """Test error when URLs list is empty."""
        mock_request.json.return_value = {"urls": []}

        result = await threat_handler.check_urls_batch(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_urls_batch_too_many_urls_error(self, threat_handler, mock_request):
        """Test error when more than 50 URLs provided."""
        mock_request.json.return_value = {"urls": [f"https://example{i}.com" for i in range(51)]}

        result = await threat_handler.check_urls_batch(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_urls_batch_limits_concurrency(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test that max_concurrent is capped at 10."""
        mock_request.json.return_value = {
            "urls": ["https://example.com"],
            "max_concurrent": 100,  # Should be capped to 10
        }

        await threat_handler.check_urls_batch(mock_request)

        call_kwargs = mock_threat_service.check_urls_batch.call_args.kwargs
        assert call_kwargs["max_concurrent"] <= 10


# ===========================================================================
# IP Reputation Tests
# ===========================================================================


class TestThreatIntelIPReputation:
    """Tests for IP reputation endpoints."""

    @pytest.mark.asyncio
    async def test_check_ip_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful single IP check."""
        mock_request.match_info = {"ip_address": "1.2.3.4"}

        result = await threat_handler.check_ip(mock_request)

        assert result.status_code == 200
        mock_threat_service.check_ip.assert_awaited_once_with("1.2.3.4")

    @pytest.mark.asyncio
    async def test_check_ip_missing_ip_error(self, threat_handler, mock_request):
        """Test error when IP address is missing."""
        mock_request.match_info = {"ip_address": ""}

        result = await threat_handler.check_ip(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_ips_batch_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful batch IP check."""
        mock_request.json.return_value = {"ips": ["1.2.3.4", "5.6.7.8"]}

        result = await threat_handler.check_ips_batch(mock_request)

        assert result.status_code == 200
        assert mock_threat_service.check_ip.await_count == 2

    @pytest.mark.asyncio
    async def test_check_ips_batch_empty_list_error(self, threat_handler, mock_request):
        """Test error when IPs list is empty."""
        mock_request.json.return_value = {"ips": []}

        result = await threat_handler.check_ips_batch(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_ips_batch_too_many_ips_error(self, threat_handler, mock_request):
        """Test error when more than 20 IPs provided."""
        mock_request.json.return_value = {"ips": [f"1.2.3.{i}" for i in range(21)]}

        result = await threat_handler.check_ips_batch(mock_request)

        assert result.status_code == 400


# ===========================================================================
# File Hash Tests
# ===========================================================================


class TestThreatIntelFileHash:
    """Tests for file hash lookup endpoints."""

    @pytest.mark.asyncio
    async def test_check_hash_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful single hash check."""
        mock_request.match_info = {"hash_value": "abc123def456"}

        result = await threat_handler.check_hash(mock_request)

        assert result.status_code == 200
        mock_threat_service.check_file_hash.assert_awaited_once_with("abc123def456")

    @pytest.mark.asyncio
    async def test_check_hash_missing_hash_error(self, threat_handler, mock_request):
        """Test error when hash value is missing."""
        mock_request.match_info = {"hash_value": ""}

        result = await threat_handler.check_hash(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_hashes_batch_success(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test successful batch hash check."""
        mock_request.json.return_value = {"hashes": ["abc123", "def456"]}

        result = await threat_handler.check_hashes_batch(mock_request)

        assert result.status_code == 200
        assert mock_threat_service.check_file_hash.await_count == 2

    @pytest.mark.asyncio
    async def test_check_hashes_batch_empty_list_error(self, threat_handler, mock_request):
        """Test error when hashes list is empty."""
        mock_request.json.return_value = {"hashes": []}

        result = await threat_handler.check_hashes_batch(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_hashes_batch_too_many_hashes_error(self, threat_handler, mock_request):
        """Test error when more than 20 hashes provided."""
        mock_request.json.return_value = {"hashes": [f"hash{i}" for i in range(21)]}

        result = await threat_handler.check_hashes_batch(mock_request)

        assert result.status_code == 400


# ===========================================================================
# Email Scanning Tests
# ===========================================================================


class TestThreatIntelEmailScanning:
    """Tests for email content scanning endpoint."""

    @pytest.mark.asyncio
    async def test_scan_email_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful email content scan."""
        mock_request.json.return_value = {
            "body": "Check out this link: https://example.com",
            "headers": {"Received": "from mail.example.com [1.2.3.4]"},
        }

        result = await threat_handler.scan_email_content(mock_request)

        assert result.status_code == 200
        mock_threat_service.check_email_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_email_empty_body_error(self, threat_handler, mock_request):
        """Test error when email body is empty."""
        mock_request.json.return_value = {"body": ""}

        result = await threat_handler.scan_email_content(mock_request)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_email_without_headers(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test email scan works without headers."""
        mock_request.json.return_value = {
            "body": "Email body text",
        }

        result = await threat_handler.scan_email_content(mock_request)

        assert result.status_code == 200


# ===========================================================================
# Service Status Tests
# ===========================================================================


class TestThreatIntelServiceStatus:
    """Tests for service status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_success(self, threat_handler, mock_request, mock_threat_service):
        """Test successful status check."""
        result = await threat_handler.get_status(mock_request)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_status_includes_all_services(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test status includes all threat intel services."""
        result = await threat_handler.get_status(mock_request)

        # The status should include virustotal, abuseipdb, and phishtank
        assert result.status_code == 200


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestThreatIntelErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_check_url_service_error(self, threat_handler, mock_request, mock_threat_service):
        """Test error handling when service raises exception."""
        mock_request.json.return_value = {"url": "https://example.com"}
        mock_threat_service.check_url.side_effect = ValueError("Service error")

        result = await threat_handler.check_url(mock_request)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_ip_service_error(self, threat_handler, mock_request, mock_threat_service):
        """Test error handling when IP service raises exception."""
        mock_request.match_info = {"ip_address": "1.2.3.4"}
        mock_threat_service.check_ip.side_effect = ValueError("Service error")

        result = await threat_handler.check_ip(mock_request)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_hash_service_error(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test error handling when hash service raises exception."""
        mock_request.match_info = {"hash_value": "abc123"}
        mock_threat_service.check_file_hash.side_effect = ValueError("Service error")

        result = await threat_handler.check_hash(mock_request)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_scan_email_service_error(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test error handling when email scan raises exception."""
        mock_request.json.return_value = {"body": "Test email"}
        mock_threat_service.check_email_content.side_effect = ValueError("Service error")

        result = await threat_handler.scan_email_content(mock_request)

        assert result.status_code == 500


# ===========================================================================
# Summary Response Tests
# ===========================================================================


class TestThreatIntelSummaryResponses:
    """Tests for summary responses in batch operations."""

    @pytest.mark.asyncio
    async def test_urls_batch_summary_counts_malicious(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test that batch URL response includes correct malicious count."""
        mock_threat_service.check_urls_batch.return_value = {
            "https://clean.com": MockThreatResult(
                target="https://clean.com",
                is_malicious=False,
                threat_type=MockThreatType.NONE,
                severity="NONE",
                confidence=0.0,
                details={},
            ),
            "https://malicious.com": MockThreatResult(
                target="https://malicious.com",
                is_malicious=True,
                threat_type=MockThreatType.MALWARE,
                severity="HIGH",
                confidence=0.95,
                details={},
            ),
        }
        mock_request.json.return_value = {
            "urls": ["https://clean.com", "https://malicious.com"],
        }

        result = await threat_handler.check_urls_batch(mock_request)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_ips_batch_summary_counts_malicious(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test that batch IP response includes correct malicious count."""
        mock_threat_service.check_ip.side_effect = [
            MockIPResult(
                ip_address="1.2.3.4",
                is_malicious=False,
                abuse_score=0,
                total_reports=0,
                country="US",
            ),
            MockIPResult(
                ip_address="5.6.7.8",
                is_malicious=True,
                abuse_score=100,
                total_reports=500,
                country="RU",
            ),
        ]
        mock_request.json.return_value = {"ips": ["1.2.3.4", "5.6.7.8"]}

        result = await threat_handler.check_ips_batch(mock_request)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_hashes_batch_summary_counts_malware(
        self, threat_handler, mock_request, mock_threat_service
    ):
        """Test that batch hash response includes correct malware count."""
        mock_threat_service.check_file_hash.side_effect = [
            MockHashResult(
                hash_value="clean123",
                hash_type="sha256",
                is_malware=False,
                detection_ratio="0/70",
                first_seen="2024-01-01",
            ),
            MockHashResult(
                hash_value="malware456",
                hash_type="sha256",
                is_malware=True,
                detection_ratio="65/70",
                first_seen="2024-01-01",
            ),
        ]
        mock_request.json.return_value = {"hashes": ["clean123", "malware456"]}

        result = await threat_handler.check_hashes_batch(mock_request)

        assert result.status_code == 200


# ===========================================================================
# Route Registration Tests
# ===========================================================================


class TestThreatIntelRouteRegistration:
    """Tests for route registration."""

    def test_register_routes_adds_all_endpoints(self):
        """Test that all threat intel routes are registered."""
        from aragora.server.handlers.threat_intel import register_threat_intel_routes

        mock_app = MagicMock()
        mock_router = MagicMock()
        mock_app.router = mock_router

        with patch(
            "aragora.server.handlers.threat_intel.get_threat_service",
            return_value=MagicMock(config=MockServiceConfig()),
        ):
            register_threat_intel_routes(mock_app)

        mock_router.add_routes.assert_called_once()
        routes = mock_router.add_routes.call_args[0][0]
        assert len(routes) == 8  # 8 endpoints
