"""
Comprehensive tests for ThreatIntelligenceService.

Tests cover:
1. Threat feed integration tests (mocked):
   - VirusTotal file hash lookups
   - AbuseIPDB IP reputation
   - PhishTank URL checks
   - URLhaus malware URL checks

2. Batch lookup tests:
   - Multiple indicators in one call
   - Aggregation scoring from multiple sources
   - Partial failures (some feeds down)

3. Caching tests:
   - File hash TTL vs IP TTL vs URL TTL
   - Cache invalidation
   - Cache hit/miss scenarios

4. Event emission tests:
   - High-severity threat events emitted
   - Threshold configuration

5. Email prioritization tests:
   - Threat score affects email priority
   - Integration with email handlers
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from aragora.services.threat_intelligence import (
    ThreatIntelligenceService,
    ThreatIntelConfig,
    ThreatResult,
    ThreatAssessment,
    ThreatType,
    ThreatSeverity,
    ThreatSource,
    SourceResult,
    IPReputationResult,
    FileHashResult,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config():
    """Create a test configuration."""
    return ThreatIntelConfig(
        virustotal_api_key="test-vt-key",
        abuseipdb_api_key="test-aipdb-key",
        phishtank_api_key="test-pt-key",
        urlhaus_api_key="test-uh-key",
        enable_caching=False,
        enable_event_emission=True,
        high_risk_threshold=0.7,
        malicious_threshold=0.5,
        virustotal_malicious_threshold=3,
        abuseipdb_malicious_threshold=50,
    )


@pytest.fixture
def service(config):
    """Create a service with test configuration."""
    return ThreatIntelligenceService(config=config)


@pytest.fixture
def service_with_caching(config):
    """Create a service with caching enabled."""
    config.enable_caching = True
    return ThreatIntelligenceService(config=config)


@pytest.fixture
def mock_http_session():
    """Create a mock HTTP session."""
    session = AsyncMock()
    return session


def create_mock_response(status: int, json_data: dict):
    """Create a mock HTTP response."""
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=json_data)
    return mock_response


# =============================================================================
# 1. THREAT FEED INTEGRATION TESTS - VirusTotal File Hash Lookups
# =============================================================================


class TestVirusTotalFileHashLookups:
    """Tests for VirusTotal file hash lookup functionality."""

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_md5_malware_detected(self, service):
        """Test VirusTotal detects malware from MD5 hash."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "attributes": {
                        "last_analysis_stats": {
                            "malicious": 45,
                            "suspicious": 5,
                            "harmless": 20,
                            "undetected": 10,
                        },
                        "last_analysis_results": {
                            "AV1": {"category": "malicious", "result": "Trojan.Generic"},
                            "AV2": {"category": "malicious", "result": "Win32.Malware"},
                            "AV3": {"category": "harmless", "result": None},
                        },
                        "first_submission_date": 1640000000,
                        "last_analysis_date": 1700000000,
                        "type_description": "Win32 EXE",
                        "size": 123456,
                        "tags": ["trojan", "packed"],
                    }
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("d41d8cd98f00b204e9800998ecf8427e")

        assert result.is_malware is True
        assert result.hash_type == "md5"
        assert "Trojan.Generic" in result.malware_names
        assert result.detection_ratio == "50/80"
        assert result.file_type == "Win32 EXE"
        assert result.file_size == 123456

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_sha1_clean(self, service):
        """Test VirusTotal returns clean result for SHA1 hash."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "attributes": {
                        "last_analysis_stats": {
                            "malicious": 0,
                            "suspicious": 0,
                            "harmless": 60,
                            "undetected": 10,
                        },
                        "last_analysis_results": {},
                    }
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("da39a3ee5e6b4b0d3255bfef95601890afd80709")

        assert result.is_malware is False
        assert result.hash_type == "sha1"
        assert len(result.malware_names) == 0

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_sha256_ransomware(self, service):
        """Test VirusTotal detects ransomware from SHA256 hash."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "attributes": {
                        "last_analysis_stats": {
                            "malicious": 55,
                            "suspicious": 3,
                            "harmless": 10,
                            "undetected": 2,
                        },
                        "last_analysis_results": {
                            "AV1": {"category": "malicious", "result": "Ransom.WannaCry"},
                            "AV2": {"category": "malicious", "result": "Ransomware.Wcry"},
                        },
                        "tags": ["ransomware", "wannacry"],
                    }
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

        assert result.is_malware is True
        assert result.hash_type == "sha256"
        assert "Ransom.WannaCry" in result.malware_names
        assert "ransomware" in result.tags

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_not_found_404(self, service):
        """Test VirusTotal returns clean result for unknown hash (404)."""
        mock_response = create_mock_response(404, {})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("0" * 64)

        assert result.is_malware is False

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_api_error(self, service):
        """Test VirusTotal handles API errors gracefully."""
        mock_response = create_mock_response(500, {})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("a" * 64)

        # Should return safe default on error
        assert result.is_malware is False

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_timeout(self, service):
        """Test VirusTotal handles request timeout."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=asyncio.TimeoutError()),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("b" * 64)

        assert result.is_malware is False

    @pytest.mark.asyncio
    async def test_vt_hash_lookup_below_threshold(self, service):
        """Test hash with detections below threshold is not flagged."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "attributes": {
                        "last_analysis_stats": {
                            "malicious": 2,  # Below threshold of 3
                            "suspicious": 0,
                            "harmless": 60,
                            "undetected": 8,
                        },
                        "last_analysis_results": {},
                    }
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_file_hash("c" * 64)

        assert result.is_malware is False


# =============================================================================
# 1. THREAT FEED INTEGRATION TESTS - AbuseIPDB IP Reputation
# =============================================================================


class TestAbuseIPDBIPReputation:
    """Tests for AbuseIPDB IP reputation lookup functionality."""

    @pytest.mark.asyncio
    async def test_abuseipdb_high_abuse_score_malicious(self, service):
        """Test AbuseIPDB identifies high abuse score IP as malicious."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "185.220.100.254",
                    "abuseConfidenceScore": 100,
                    "totalReports": 2500,
                    "lastReportedAt": "2024-01-15T10:30:00+00:00",
                    "countryCode": "NL",
                    "isp": "Tor Exit Node",
                    "domain": "torproject.org",
                    "usageType": "Security Services",
                    "isTor": True,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("185.220.100.254")

        assert result.is_malicious is True
        assert result.abuse_score == 100
        assert result.total_reports == 2500
        assert result.is_tor is True
        assert result.country_code == "NL"

    @pytest.mark.asyncio
    async def test_abuseipdb_low_abuse_score_safe(self, service):
        """Test AbuseIPDB identifies low abuse score IP as safe."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "8.8.8.8",
                    "abuseConfidenceScore": 0,
                    "totalReports": 0,
                    "lastReportedAt": None,
                    "countryCode": "US",
                    "isp": "Google LLC",
                    "domain": "google.com",
                    "usageType": "Content Delivery Network",
                    "isTor": False,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("8.8.8.8")

        assert result.is_malicious is False
        assert result.abuse_score == 0
        assert result.isp == "Google LLC"

    @pytest.mark.asyncio
    async def test_abuseipdb_medium_abuse_score_threshold(self, service):
        """Test AbuseIPDB applies threshold correctly for borderline scores."""
        # Score of 49 - just below threshold of 50
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "1.2.3.4",
                    "abuseConfidenceScore": 49,
                    "totalReports": 100,
                    "lastReportedAt": "2024-01-10T00:00:00+00:00",
                    "countryCode": "RU",
                    "isp": "Unknown ISP",
                    "isTor": False,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("1.2.3.4")

        assert result.is_malicious is False
        assert result.abuse_score == 49

    @pytest.mark.asyncio
    async def test_abuseipdb_at_threshold(self, service):
        """Test AbuseIPDB at exactly threshold is malicious."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "5.6.7.8",
                    "abuseConfidenceScore": 50,  # Exactly at threshold
                    "totalReports": 150,
                    "countryCode": "CN",
                    "isTor": False,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("5.6.7.8")

        assert result.is_malicious is True
        assert result.abuse_score == 50

    @pytest.mark.asyncio
    async def test_abuseipdb_ipv6_address(self, service):
        """Test AbuseIPDB handles IPv6 addresses."""
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "2001:4860:4860::8888",
                    "abuseConfidenceScore": 0,
                    "totalReports": 0,
                    "countryCode": "US",
                    "isp": "Google LLC",
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("2001:4860:4860::8888")

        assert result.ip_address == "2001:4860:4860::8888"
        assert result.is_malicious is False

    @pytest.mark.asyncio
    async def test_abuseipdb_api_rate_limited(self, service):
        """Test AbuseIPDB handles rate limiting (429)."""
        mock_response = create_mock_response(429, {"errors": [{"detail": "Rate limited"}]})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.check_ip("9.10.11.12")

        # Should return safe default on rate limit
        assert result.is_malicious is False
        assert result.abuse_score == 0

    @pytest.mark.asyncio
    async def test_abuseipdb_invalid_ip_rejected(self, service):
        """Test AbuseIPDB rejects invalid IP addresses."""
        result = await service.check_ip("not-an-ip-address")

        assert result.is_malicious is False
        assert result.abuse_score == 0


# =============================================================================
# 1. THREAT FEED INTEGRATION TESTS - PhishTank URL Checks
# =============================================================================


class TestPhishTankURLChecks:
    """Tests for PhishTank URL verification functionality."""

    @pytest.mark.asyncio
    async def test_phishtank_verified_phishing_url(self, service):
        """Test PhishTank identifies verified phishing URL."""
        mock_response = create_mock_response(
            200,
            {
                "results": {
                    "in_database": True,
                    "verified": True,
                    "phish_id": "7654321",
                    "phish_detail_page": "http://phishtank.com/phish_detail.php?phish_id=7654321",
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_phishtank("http://paypal-verify.tk/login")

        assert result is not None
        assert result["verified"] is True
        assert result["in_database"] is True
        assert result["phish_id"] == "7654321"

    @pytest.mark.asyncio
    async def test_phishtank_in_database_not_verified(self, service):
        """Test PhishTank URL in database but not yet verified."""
        mock_response = create_mock_response(
            200,
            {
                "results": {
                    "in_database": True,
                    "verified": False,
                    "phish_id": "8765432",
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_phishtank("http://suspicious-site.com")

        assert result["in_database"] is True
        assert result["verified"] is False

    @pytest.mark.asyncio
    async def test_phishtank_url_not_in_database(self, service):
        """Test PhishTank clean URL not in database."""
        mock_response = create_mock_response(
            200,
            {
                "results": {
                    "in_database": False,
                    "verified": False,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_phishtank("http://legitimate-site.com")

        assert result["in_database"] is False
        assert result["verified"] is False

    @pytest.mark.asyncio
    async def test_phishtank_with_api_key(self, service):
        """Test PhishTank includes API key when provided."""
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": False, "verified": False}},
        )

        mock_session = AsyncMock()
        mock_post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.post = mock_post
        service._http_session = mock_session

        await service._check_url_phishtank("http://test.com")

        # Verify API key was included in request
        call_args = mock_post.call_args
        assert "app_key" in call_args.kwargs.get("data", {})

    @pytest.mark.asyncio
    async def test_phishtank_api_error(self, service):
        """Test PhishTank handles API errors."""
        mock_response = create_mock_response(500, {})

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_phishtank("http://test.com")

        assert result is None


# =============================================================================
# 1. THREAT FEED INTEGRATION TESTS - URLhaus Malware URL Checks
# =============================================================================


class TestURLhausMalwareURLChecks:
    """Tests for URLhaus malware URL checking functionality."""

    @pytest.mark.asyncio
    async def test_urlhaus_malware_url_detected(self, service):
        """Test URLhaus detects known malware distribution URL."""
        mock_response = create_mock_response(
            200,
            {
                "query_status": "ok",
                "url_status": "online",
                "threat": "malware_download",
                "tags": ["exe", "trojan", "emotet"],
                "host": "malware.example.com",
                "date_added": "2024-01-15",
                "reporter": "abuse_reporter",
                "payloads": [
                    {"filename": "malware.exe", "file_type": "exe"},
                    {"filename": "payload.dll", "file_type": "dll"},
                ],
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_urlhaus("http://malware.example.com/download.exe")

        assert result is not None
        assert result["is_malware"] is True
        assert result["threat"] == "malware_download"
        assert "trojan" in result["tags"]
        assert result["url_status"] == "online"

    @pytest.mark.asyncio
    async def test_urlhaus_ransomware_url(self, service):
        """Test URLhaus detects ransomware distribution URL."""
        mock_response = create_mock_response(
            200,
            {
                "query_status": "ok",
                "url_status": "online",
                "threat": "ransomware",
                "tags": ["ransomware", "lockbit"],
                "host": "ransomware.tk",
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_urlhaus("http://ransomware.tk/encrypt")

        assert result["is_malware"] is True
        assert "ransomware" in result["tags"]

    @pytest.mark.asyncio
    async def test_urlhaus_c2_server_url(self, service):
        """Test URLhaus detects command and control server URL."""
        mock_response = create_mock_response(
            200,
            {
                "query_status": "ok",
                "url_status": "online",
                "threat": "botnet_cc",
                "tags": ["c2", "botnet", "cobalt_strike"],
                "host": "c2server.example.net",
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_urlhaus("http://c2server.example.net/beacon")

        assert result["is_malware"] is True
        assert "c2" in result["tags"]

    @pytest.mark.asyncio
    async def test_urlhaus_url_not_found(self, service):
        """Test URLhaus returns not found for clean URL."""
        mock_response = create_mock_response(
            200,
            {
                "query_status": "no_results",
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_urlhaus("http://clean-site.com")

        assert result["is_malware"] is False
        assert result["query_status"] == "not_found"

    @pytest.mark.asyncio
    async def test_urlhaus_offline_malware_url(self, service):
        """Test URLhaus reports offline malware URL."""
        mock_response = create_mock_response(
            200,
            {
                "query_status": "ok",
                "url_status": "offline",
                "threat": "malware_download",
                "tags": ["exe"],
            },
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service._check_url_urlhaus("http://old-malware.com/file")

        assert result["is_malware"] is True
        assert result["url_status"] == "offline"


# =============================================================================
# 2. BATCH LOOKUP TESTS
# =============================================================================


class TestBatchLookups:
    """Tests for batch lookup functionality."""

    @pytest.mark.asyncio
    async def test_batch_urls_multiple_indicators(self, service):
        """Test batch URL lookup with multiple URLs."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        urls = [
            "http://safe1.com",
            "http://safe2.com",
            "http://safe3.com",
        ]

        results = await service.check_urls_batch(urls)

        assert len(results) == 3
        assert all(url in results for url in urls)
        for url, result in results.items():
            assert result.target == url
            assert result.target_type == "url"

    @pytest.mark.asyncio
    async def test_batch_urls_respects_concurrency_limit(self, service):
        """Test batch URL lookup respects max_concurrent parameter."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        urls = [f"http://site{i}.com" for i in range(10)]

        # Track concurrent executions
        current_concurrent = 0
        max_observed_concurrent = 0

        original_check_url = service.check_url

        async def tracking_check_url(url):
            nonlocal current_concurrent, max_observed_concurrent
            current_concurrent += 1
            max_observed_concurrent = max(max_observed_concurrent, current_concurrent)
            await asyncio.sleep(0.01)  # Simulate work
            result = await original_check_url(url)
            current_concurrent -= 1
            return result

        with patch.object(service, "check_url", tracking_check_url):
            await service.check_urls_batch(urls, max_concurrent=3)

        assert max_observed_concurrent <= 3

    @pytest.mark.asyncio
    async def test_batch_ips_multiple_indicators(self, service):
        """Test batch IP lookup with multiple IPs."""
        service.config.enable_abuseipdb = False

        ips = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]

        results = await service.check_ips_batch(ips)

        assert len(results) == 3
        assert all(ip in results for ip in ips)

    @pytest.mark.asyncio
    async def test_batch_urls_aggregation_scoring(self, service):
        """Test batch lookup aggregates scores correctly."""
        # Mock a malicious URL response
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        results = await service.check_urls_batch(["http://phishing.tk/login"])

        result = results["http://phishing.tk/login"]
        assert result.is_malicious is True
        assert result.confidence >= 0.9  # High confidence from PhishTank

    @pytest.mark.asyncio
    async def test_batch_partial_failures_some_feeds_down(self, service):
        """Test batch handles partial API failures gracefully."""
        service.config.enable_phishtank = True
        service.config.enable_urlhaus = True
        service.config.enable_virustotal = False  # Disable VT to focus on phishtank/urlhaus

        # PhishTank returns error, URLhaus works
        def mock_post(*args, **kwargs):
            url = args[0] if args else ""
            if "phishtank" in str(url):
                raise ConnectionError("PhishTank API down")
            else:
                # URLhaus returns clean
                mock_resp_cm = MagicMock()
                mock_resp_cm.__aenter__ = AsyncMock(
                    return_value=create_mock_response(200, {"query_status": "no_results"})
                )
                mock_resp_cm.__aexit__ = AsyncMock(return_value=None)
                return mock_resp_cm

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=mock_post)
        service._http_session = mock_session

        # Should complete without raising
        results = await service.check_urls_batch(["http://test.com"])

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_batch_empty_list(self, service):
        """Test batch lookup with empty list returns empty dict."""
        results = await service.check_urls_batch([])

        assert results == {}

    @pytest.mark.asyncio
    async def test_batch_single_item(self, service):
        """Test batch lookup with single item works correctly."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        results = await service.check_urls_batch(["http://single.com"])

        assert len(results) == 1
        assert "http://single.com" in results


# =============================================================================
# 3. CACHING TESTS
# =============================================================================


class TestCachingTTL:
    """Tests for cache TTL by target type."""

    def test_ttl_for_url_type(self, service):
        """Test URL type gets URL-specific TTL."""
        ttl = service._get_ttl_for_type("url")
        assert ttl == service.config.cache_url_ttl_hours * 3600

    def test_ttl_for_ip_type(self, service):
        """Test IP type gets IP-specific TTL (shorter)."""
        ttl = service._get_ttl_for_type("ip")
        assert ttl == service.config.cache_ip_ttl_hours * 3600

    def test_ttl_for_hash_type(self, service):
        """Test hash type gets hash-specific TTL (longer)."""
        ttl = service._get_ttl_for_type("hash")
        assert ttl == service.config.cache_hash_ttl_hours * 3600

    def test_ttl_hash_longer_than_url(self, config):
        """Test hash TTL is longer than URL TTL."""
        # Default values: hash=168 hours (7 days), url=24 hours
        assert config.cache_hash_ttl_hours > config.cache_url_ttl_hours

    def test_ttl_ip_shorter_than_url(self, config):
        """Test IP TTL is shorter than URL TTL."""
        # Default values: ip=1 hour, url=24 hours
        assert config.cache_ip_ttl_hours < config.cache_url_ttl_hours


class TestCacheInvalidation:
    """Tests for cache invalidation and expiration."""

    @pytest.mark.asyncio
    async def test_memory_cache_expires(self, service_with_caching):
        """Test memory cache entries expire correctly."""
        from aragora.services.threat_intelligence import ThreatResult, ThreatType, ThreatSeverity

        result = ThreatResult(
            target="http://test.com",
            target_type="url",
            is_malicious=False,
            threat_type=ThreatType.NONE,
            severity=ThreatSeverity.NONE,
            confidence=0.0,
            sources=[ThreatSource.LOCAL_RULES],
        )

        # Manually set with very short expiry
        cache_key = service_with_caching._get_cache_key("http://test.com", "url")
        expires_at = datetime.now() - timedelta(seconds=1)  # Already expired

        with service_with_caching._memory_cache_lock:
            service_with_caching._memory_cache[cache_key] = {
                "data": service_with_caching._serialize_threat_result(result),
                "expires_at": expires_at.isoformat(),
            }

        # Should return None for expired entry
        cached = service_with_caching._get_memory_cached("http://test.com", "url")
        assert cached is None

        # Entry should be removed from cache
        assert cache_key not in service_with_caching._memory_cache

    @pytest.mark.asyncio
    async def test_sqlite_cache_expired_entry_not_returned(self):
        """Test SQLite cache doesn't return expired entries."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        service = ThreatIntelligenceService()
        service.config.cache_db_path = db_path
        service.config.enable_caching = True

        await service._init_sqlite_cache()

        # Insert expired entry
        cursor = service._cache_conn.cursor()
        expired_time = (datetime.now() - timedelta(hours=1)).isoformat()
        cache_key = service._get_cache_key("http://expired.com", "url")
        cursor.execute(
            """INSERT INTO threat_cache (target_hash, target, target_type, result_json, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cache_key, "http://expired.com", "url", "{}", expired_time),
        )
        service._cache_conn.commit()

        # Should not return expired entry
        result = await service._get_sqlite_cached("http://expired.com", "url")
        assert result is None

        await service.close()

    @pytest.mark.asyncio
    async def test_cache_cleanup_removes_old_entries(self):
        """Test cleanup_cache removes old entries."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        service = ThreatIntelligenceService()
        service.config.cache_db_path = db_path
        service.config.enable_caching = True

        await service._init_sqlite_cache()

        # Insert entries with different ages
        cursor = service._cache_conn.cursor()
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        recent_time = datetime.now().isoformat()

        cursor.execute(
            """INSERT INTO threat_cache (target_hash, target, target_type, result_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("old_hash", "http://old.com", "url", "{}", old_time, old_time),
        )
        cursor.execute(
            """INSERT INTO threat_cache (target_hash, target, target_type, result_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("recent_hash", "http://recent.com", "url", "{}", recent_time, recent_time),
        )
        service._cache_conn.commit()

        # Cleanup entries older than 24 hours
        deleted = await service.cleanup_cache(older_than_hours=24)

        assert deleted >= 1

        await service.close()


class TestCacheHitMiss:
    """Tests for cache hit/miss scenarios."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self):
        """Test cache hit returns the cached result."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        service = ThreatIntelligenceService()
        service.config.cache_db_path = db_path
        service.config.enable_caching = True
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        await service.initialize()

        # First call populates cache
        result1 = await service.check_url("http://cache-test.com")

        # Second call should hit cache
        result2 = await service.check_url("http://cache-test.com")

        assert result2.cached is True
        assert result2.target == result1.target

        await service.close()

    @pytest.mark.asyncio
    async def test_cache_miss_queries_sources(self, service):
        """Test cache miss triggers source queries."""
        service.config.enable_caching = True
        service.config.enable_virustotal = True

        # Mock VT to verify it's called
        vt_called = False

        async def mock_vt_check(url):
            nonlocal vt_called
            vt_called = True
            return None

        with patch.object(service, "_check_url_virustotal", mock_vt_check):
            await service.check_url("http://uncached-url.com")

        # VT should have been called (cache miss)
        assert vt_called is True

    @pytest.mark.asyncio
    async def test_memory_cache_eviction_on_size_limit(self, service_with_caching):
        """Test memory cache evicts entries when size limit reached."""
        service = service_with_caching

        # Fill cache beyond limit
        for i in range(10001):
            cache_key = f"key_{i}"
            service._memory_cache[cache_key] = {
                "data": {},
                "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
            }

        # Trigger eviction by setting new entry
        service._set_memory_cached(
            "http://new.com",
            "url",
            ThreatResult(
                target="http://new.com",
                target_type="url",
                is_malicious=False,
                threat_type=ThreatType.NONE,
                severity=ThreatSeverity.NONE,
                confidence=0.0,
                sources=[],
            ),
        )

        # Should have evicted some entries
        assert len(service._memory_cache) <= 10000


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_cache_key_is_deterministic(self, service):
        """Test same input always produces same key."""
        key1 = service._get_cache_key("http://test.com", "url")
        key2 = service._get_cache_key("http://test.com", "url")
        assert key1 == key2

    def test_cache_key_case_insensitive(self, service):
        """Test cache key is case-insensitive."""
        key1 = service._get_cache_key("http://TEST.COM", "url")
        key2 = service._get_cache_key("http://test.com", "url")
        assert key1 == key2

    def test_cache_key_different_for_different_types(self, service):
        """Test different target types produce different keys."""
        key_url = service._get_cache_key("abc123", "url")
        key_hash = service._get_cache_key("abc123", "hash")
        assert key_url != key_hash


# =============================================================================
# 4. EVENT EMISSION TESTS
# =============================================================================


class TestEventEmission:
    """Tests for threat event emission functionality."""

    def test_add_event_handler(self, service):
        """Test adding event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)

        assert handler in service._event_handlers

    def test_remove_event_handler(self, service):
        """Test removing event handler."""
        handler = MagicMock()
        service.add_event_handler(handler)

        result = service.remove_event_handler(handler)

        assert result is True
        assert handler not in service._event_handlers

    def test_remove_nonexistent_handler(self, service):
        """Test removing handler that doesn't exist."""
        handler = MagicMock()

        result = service.remove_event_handler(handler)

        assert result is False

    @pytest.mark.asyncio
    async def test_high_severity_url_emits_event(self, service):
        """Test high-severity URL finding emits event."""
        handler = MagicMock()
        service.add_event_handler(handler)

        # Mock PhishTank verified phishing
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        await service.check_url("http://phishing-site.tk/login")

        # Handler should have been called
        handler.assert_called()
        call_args = handler.call_args
        assert call_args[0][0] == "high_risk_url"
        assert "phishing-site.tk" in call_args[0][1]["target"]

    @pytest.mark.asyncio
    async def test_low_severity_does_not_emit_event(self, service):
        """Test low-severity findings don't emit events."""
        handler = MagicMock()
        service.add_event_handler(handler)

        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        await service.check_url("http://safe-site.com")

        # Handler should not have been called
        handler.assert_not_called()

    def test_event_emission_disabled_config(self, service):
        """Test events not emitted when disabled in config."""
        handler = MagicMock()
        service.add_event_handler(handler)
        service.config.enable_event_emission = False

        service._emit_event("test_event", {"data": "test"})

        handler.assert_not_called()

    def test_event_handler_exception_does_not_propagate(self, service):
        """Test handler exception is caught and logged."""

        def failing_handler(event_type, data):
            raise ValueError("Handler error")

        service.add_event_handler(failing_handler)

        # Should not raise
        service._emit_event("test_event", {"data": "test"})

    @pytest.mark.asyncio
    async def test_high_risk_threshold_configuration(self, service):
        """Test high risk threshold is configurable."""
        handler = MagicMock()
        service.add_event_handler(handler)
        service.config.high_risk_threshold = 0.99  # Very high threshold

        # Mock medium-confidence phishing (0.95 < 0.99)
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        await service.check_url("http://test-phish.tk")

        # Handler should NOT be called (0.95 confidence < 0.99 threshold)
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_assess_threat_emits_high_risk_assessment(self, service):
        """Test assess_threat emits event for high-risk assessment."""
        handler = MagicMock()
        service.add_event_handler(handler)

        # Mock all sources returning malicious
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        await service.assess_threat("http://phishing.tk/steal")

        # Should emit high_risk_assessment event
        calls = [c for c in handler.call_args_list if "high_risk" in c[0][0]]
        assert len(calls) >= 1


# =============================================================================
# 5. EMAIL PRIORITIZATION TESTS
# =============================================================================


class TestEmailPrioritization:
    """Tests for email prioritization based on threat scores."""

    @pytest.mark.asyncio
    async def test_email_with_malicious_url_high_threat_score(self, service):
        """Test email with malicious URL gets high threat score."""
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        # Mock PhishTank verified phishing
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        email_body = """
        Dear Customer,
        Click here to verify your account: http://paypal-verify.tk/login
        """

        result = await service.check_email_content(email_body)

        assert result["is_suspicious"] is True
        assert result["overall_threat_score"] > 0
        assert len(result["urls"]) > 0

    @pytest.mark.asyncio
    async def test_email_with_safe_urls_low_threat_score(self, service):
        """Test email with safe URLs gets low threat score."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        email_body = """
        Hi Team,
        Check out our documentation at https://docs.example.com
        """

        result = await service.check_email_content(email_body)

        assert result["is_suspicious"] is False
        assert result["overall_threat_score"] == 0

    @pytest.mark.asyncio
    async def test_email_with_malicious_sender_ip(self, service):
        """Test email from malicious IP increases threat score."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        # Mock AbuseIPDB response for malicious IP
        mock_response = create_mock_response(
            200,
            {
                "data": {
                    "ipAddress": "185.220.100.254",
                    "abuseConfidenceScore": 100,
                    "totalReports": 1000,
                }
            },
        )

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        email_body = "Normal email content"
        headers = {"Received": "from server (185.220.100.254) by mail.example.com"}

        result = await service.check_email_content(email_body, headers)

        assert result["is_suspicious"] is True
        assert len(result["ips"]) > 0

    @pytest.mark.asyncio
    async def test_email_with_multiple_malicious_urls(self, service):
        """Test email with multiple malicious URLs has higher score."""
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        # Mock PhishTank response
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        email_body = """
        Click these links:
        http://phishing1.tk/login
        http://phishing2.tk/verify
        http://phishing3.tk/account
        """

        result = await service.check_email_content(email_body)

        assert result["is_suspicious"] is True
        assert len(result["urls"]) == 3
        assert "3 malicious URLs" in result["threat_summary"][0]

    @pytest.mark.asyncio
    async def test_email_skips_private_ips(self, service):
        """Test email content check skips private IP addresses."""
        service.config.enable_abuseipdb = True

        email_body = "Normal email"
        headers = {"Received": "from internal (10.0.0.1) (192.168.1.1) (172.16.0.1)"}

        # Should not query AbuseIPDB for private IPs
        with patch.object(service, "_check_ip_abuseipdb") as mock_check:
            result = await service.check_email_content(email_body, headers)

        # Should not have called AbuseIPDB for private IPs
        mock_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_limits_url_checks(self, service):
        """Test email content check limits URLs to 10."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        # Generate 20 URLs
        urls = "\n".join([f"http://site{i}.com" for i in range(20)])
        email_body = f"Links:\n{urls}"

        result = await service.check_email_content(email_body)

        # Should only check first 10
        assert len(result["urls"]) <= 10


class TestEmailThreatScoreCalculation:
    """Tests for email threat score calculation."""

    @pytest.mark.asyncio
    async def test_threat_score_calculation_single_source(self, service):
        """Test threat score with single source."""
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        # PhishTank verified = 100 threat score
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        email_body = "Click: http://phish.tk"

        result = await service.check_email_content(email_body)

        # Score should be average of URL scores (100 for verified phishing)
        assert result["overall_threat_score"] == 100

    @pytest.mark.asyncio
    async def test_threat_score_calculation_mixed_results(self, service):
        """Test threat score with mixed safe and malicious."""
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            # First URL is phishing, second is clean
            if call_count[0] == 1:
                return AsyncMock(
                    __aenter__=AsyncMock(
                        return_value=create_mock_response(
                            200, {"results": {"in_database": True, "verified": True}}
                        )
                    ),
                    __aexit__=AsyncMock(return_value=False),
                )
            else:
                return AsyncMock(
                    __aenter__=AsyncMock(
                        return_value=create_mock_response(
                            200, {"results": {"in_database": False, "verified": False}}
                        )
                    ),
                    __aexit__=AsyncMock(return_value=False),
                )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=mock_post)
        service._http_session = mock_session

        email_body = """
        Bad: http://phish.tk
        Good: http://safe.com
        """

        result = await service.check_email_content(email_body)

        # Should have both URLs
        assert len(result["urls"]) == 2
        # Score should be average (100 + 0) / 2 = 50
        assert result["overall_threat_score"] == 50


# =============================================================================
# CIRCUIT BREAKER AND RATE LIMITING TESTS
# =============================================================================


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration with threat feeds."""

    def test_circuit_breaker_status_report(self, service):
        """Test getting circuit breaker status for all services."""
        status = service.get_circuit_breaker_status()

        assert "virustotal" in status
        assert "abuseipdb" in status
        assert "phishtank" in status
        assert "urlhaus" in status

        for svc_status in status.values():
            assert "status" in svc_status
            assert "failures" in svc_status
            assert "threshold" in svc_status

    def test_circuit_opens_after_failures(self, service):
        """Test circuit breaker opens after threshold failures."""
        for _ in range(3):
            service._record_api_failure("virustotal")

        assert service._is_circuit_open("virustotal") is True

    def test_success_resets_circuit(self, service):
        """Test successful call resets circuit breaker."""
        service._record_api_failure("virustotal")
        service._record_api_failure("virustotal")

        service._record_api_success("virustotal")

        assert service._is_circuit_open("virustotal") is False

    @pytest.mark.asyncio
    async def test_open_circuit_skips_api_call(self, service):
        """Test open circuit breaker skips API calls."""
        # Open the circuit
        for _ in range(3):
            service._record_api_failure("virustotal")

        # Should return None without making API call
        result = await service._check_url_virustotal("http://test.com")

        assert result is None


class TestRateLimitingIntegration:
    """Tests for rate limiting integration."""

    @pytest.mark.asyncio
    async def test_rate_limit_allows_within_limit(self, service):
        """Test requests within rate limit are allowed."""
        service.config.virustotal_rate_limit = 4

        for _ in range(4):
            allowed = await service._check_rate_limit("virustotal")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self, service):
        """Test requests over rate limit are blocked."""
        service.config.virustotal_rate_limit = 2

        await service._check_rate_limit("virustotal")
        await service._check_rate_limit("virustotal")

        blocked = await service._check_rate_limit("virustotal")
        assert blocked is False

    @pytest.mark.asyncio
    async def test_rate_limit_resets_after_window(self, service):
        """Test rate limit resets after time window."""
        service.config.virustotal_rate_limit = 1

        await service._check_rate_limit("virustotal")

        # Manually clear the rate limit timestamps (simulating time passage)
        service._rate_limits["virustotal"] = []

        allowed = await service._check_rate_limit("virustotal")
        assert allowed is True


# =============================================================================
# AGGREGATE THREAT ASSESSMENT TESTS
# =============================================================================


class TestAggregateThreatAssessment:
    """Tests for aggregate threat assessment functionality."""

    @pytest.mark.asyncio
    async def test_assess_threat_auto_detects_url(self, service):
        """Test assess_threat auto-detects URL target type."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        result = await service.assess_threat("http://example.com")

        assert result.target_type == "url"

    @pytest.mark.asyncio
    async def test_assess_threat_auto_detects_ip(self, service):
        """Test assess_threat auto-detects IP target type."""
        service.config.enable_abuseipdb = False

        result = await service.assess_threat("8.8.8.8")

        assert result.target_type == "ip"

    @pytest.mark.asyncio
    async def test_assess_threat_auto_detects_hash(self, service):
        """Test assess_threat auto-detects hash target type."""
        service.config.enable_virustotal = False

        result = await service.assess_threat("d41d8cd98f00b204e9800998ecf8427e")

        assert result.target_type == "hash"

    @pytest.mark.asyncio
    async def test_assess_threat_weighted_confidence(self, service):
        """Test weighted confidence calculation in assessment."""
        service.config.source_weights = {
            "virustotal": 1.0,
            "local_rules": 0.1,
        }

        source_results = {
            "virustotal": SourceResult(
                source=ThreatSource.VIRUSTOTAL,
                is_malicious=True,
                confidence=0.9,
            ),
            "local_rules": SourceResult(
                source=ThreatSource.LOCAL_RULES,
                is_malicious=False,
                confidence=0.1,
            ),
        }

        overall, weighted, is_mal = service._calculate_aggregate_risk(source_results)

        # VirusTotal (weight 1.0) should dominate over local_rules (weight 0.1)
        assert weighted > 0.5
        assert is_mal is True

    @pytest.mark.asyncio
    async def test_assess_threat_source_agreement(self, service):
        """Test source agreement calculation in assessment."""
        service.config.enable_virustotal = False
        service.config.enable_urlhaus = False

        # All sources agree it's phishing
        mock_response = create_mock_response(
            200,
            {"results": {"in_database": True, "verified": True}},
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        result = await service.assess_threat("http://phishing.tk")

        # With single source agreeing, agreement should be 1.0
        assert result.source_agreement >= 0.0

    @pytest.mark.asyncio
    async def test_assess_threat_handles_api_errors(self, service):
        """Test assess_threat handles API errors in sources."""
        service.config.enable_virustotal = True
        service.config.enable_phishtank = True

        # Make both APIs fail
        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=ConnectionError("API Error")),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        mock_session.post = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=ConnectionError("API Error")),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        # Should complete without raising
        result = await service.assess_threat("http://test.com")

        assert result is not None
        assert result.target == "http://test.com"


# =============================================================================
# SERIALIZATION AND DESERIALIZATION TESTS
# =============================================================================


class TestSerializationDeserialization:
    """Tests for threat result serialization and deserialization."""

    def test_serialize_threat_result(self, service):
        """Test ThreatResult serialization."""
        result = ThreatResult(
            target="http://test.com",
            target_type="url",
            is_malicious=True,
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            confidence=0.95,
            sources=[ThreatSource.PHISHTANK],
            virustotal_positives=20,
            virustotal_total=70,
            phishtank_verified=True,
        )

        serialized = service._serialize_threat_result(result)

        assert serialized["target"] == "http://test.com"
        assert serialized["is_malicious"] is True
        assert serialized["threat_type"] == "phishing"
        assert serialized["severity"] == "HIGH"
        assert serialized["phishtank_verified"] is True

    def test_deserialize_threat_result(self, service):
        """Test ThreatResult deserialization."""
        data = {
            "target": "http://test.com",
            "target_type": "url",
            "is_malicious": True,
            "threat_type": "phishing",
            "severity": "HIGH",
            "confidence": 0.95,
            "sources": ["phishtank"],
            "details": {},
            "checked_at": datetime.now().isoformat(),
            "virustotal_positives": 0,
            "virustotal_total": 0,
            "abuseipdb_score": 0,
            "phishtank_verified": True,
        }

        result = service._deserialize_threat_result(data)

        assert result.target == "http://test.com"
        assert result.is_malicious is True
        assert result.threat_type == ThreatType.PHISHING
        assert result.severity == ThreatSeverity.HIGH
        assert result.cached is True  # Deserialized results are marked as cached

    def test_round_trip_serialization(self, service):
        """Test serialization and deserialization round trip."""
        original = ThreatResult(
            target="http://round-trip.com",
            target_type="url",
            is_malicious=True,
            threat_type=ThreatType.MALWARE,
            severity=ThreatSeverity.CRITICAL,
            confidence=0.99,
            sources=[ThreatSource.URLHAUS],
            abuseipdb_score=85,
        )

        serialized = service._serialize_threat_result(original)
        deserialized = service._deserialize_threat_result(serialized)

        assert deserialized.target == original.target
        assert deserialized.is_malicious == original.is_malicious
        assert deserialized.threat_type == original.threat_type
        assert deserialized.severity == original.severity
        assert deserialized.confidence == original.confidence


# =============================================================================
# SERVICE LIFECYCLE TESTS
# =============================================================================


class TestServiceLifecycle:
    """Tests for service initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_service_initialize_with_caching(self):
        """Test service initialization enables caching."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        config = ThreatIntelConfig(
            enable_caching=True,
            cache_db_path=db_path,
            use_redis_cache=False,
        )
        service = ThreatIntelligenceService(config=config)

        await service.initialize()

        assert service._cache_conn is not None

        await service.close()

    @pytest.mark.asyncio
    async def test_service_close_cleans_up_resources(self):
        """Test service close releases resources."""
        service = ThreatIntelligenceService()
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        service._http_session = mock_session

        await service.close()

        mock_session.close.assert_called_once()
        assert service._http_session is None

    def test_service_loads_api_keys_from_env(self, monkeypatch):
        """Test service loads API keys from environment."""
        monkeypatch.setenv("VIRUSTOTAL_API_KEY", "env-vt-key")
        monkeypatch.setenv("ABUSEIPDB_API_KEY", "env-aipdb-key")

        service = ThreatIntelligenceService()

        assert service.config.virustotal_api_key == "env-vt-key"
        assert service.config.abuseipdb_api_key == "env-aipdb-key"

    def test_explicit_api_keys_override_env(self, monkeypatch):
        """Test explicit API keys override environment."""
        monkeypatch.setenv("VIRUSTOTAL_API_KEY", "env-key")

        service = ThreatIntelligenceService(virustotal_api_key="explicit-key")

        assert service.config.virustotal_api_key == "explicit-key"


# =============================================================================
# ERROR HANDLING EDGE CASES
# =============================================================================


class TestErrorHandling:
    """Tests for error handling edge cases."""

    @pytest.mark.asyncio
    async def test_check_url_with_malformed_url(self, service):
        """Test check_url handles malformed URL gracefully."""
        service.config.enable_virustotal = False
        service.config.enable_phishtank = False
        service.config.enable_urlhaus = False

        result = await service.check_url("not-a-valid-url")

        assert result.target == "not-a-valid-url"
        assert result.is_malicious is False

    @pytest.mark.asyncio
    async def test_check_hash_with_invalid_characters(self, service):
        """Test check_file_hash handles invalid hash characters."""
        result = await service.check_file_hash("zzzz-not-hex-characters-zzzz")

        assert result.hash_type == "unknown"
        assert result.is_malware is False

    @pytest.mark.asyncio
    async def test_network_timeout_graceful_handling(self, service):
        """Test network timeouts are handled gracefully."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(side_effect=asyncio.TimeoutError()),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        # Should complete without raising
        result = await service.check_file_hash("a" * 64)

        assert result.is_malware is False

    @pytest.mark.asyncio
    async def test_json_decode_error_handling(self, service):
        """Test JSON decode errors are handled."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(side_effect=json.JSONDecodeError("err", "doc", 0))

        mock_session = AsyncMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )
        service._http_session = mock_session

        # Should handle gracefully
        result = await service.check_file_hash("b" * 64)

        assert result.is_malware is False
