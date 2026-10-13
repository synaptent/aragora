"""Tests for HTTP client connection pooling."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.observability.http_client_pool import (
    HTTPClientPool,
    HTTPPoolConfig,
    HTTPPoolMetrics,
    ProviderMetrics,
    PROVIDER_CONFIGS,
    get_http_pool,
)


class TestHTTPPoolConfig:
    """Test HTTP pool configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = HTTPPoolConfig()

        assert config.pool_size == 20
        assert config.max_overflow == 10
        assert config.connect_timeout == 10.0
        assert config.read_timeout == 60.0
        assert config.max_retries == 3

    def test_custom_config(self):
        """Test custom configuration."""
        config = HTTPPoolConfig(
            pool_size=50,
            max_overflow=20,
            connect_timeout=5.0,
            read_timeout=120.0,
        )

        assert config.pool_size == 50
        assert config.max_overflow == 20
        assert config.connect_timeout == 5.0
        assert config.read_timeout == 120.0


class TestProviderConfigs:
    """Test provider-specific configurations."""

    def test_anthropic_config(self):
        """Test Anthropic has higher pool size."""
        config = PROVIDER_CONFIGS["anthropic"]

        assert config["pool_size"] >= 20
        assert config["read_timeout"] >= 90  # Claude needs longer timeout

    def test_openrouter_fallback_config(self):
        """Test OpenRouter has adequate capacity for fallback."""
        config = PROVIDER_CONFIGS["openrouter"]

        assert config["pool_size"] >= 15  # Needs capacity for fallback

    def test_all_providers_have_base_url(self):
        """Test all providers have base URL defined."""
        for provider, config in PROVIDER_CONFIGS.items():
            assert "base_url" in config, f"{provider} missing base_url"
            assert config["base_url"].startswith("https://"), f"{provider} should use HTTPS"


class TestProviderMetrics:
    """Test provider metrics tracking."""

    def test_initial_metrics(self):
        """Test initial metric values."""
        metrics = ProviderMetrics()

        assert metrics.requests_total == 0
        assert metrics.requests_success == 0
        assert metrics.requests_failed == 0
        assert metrics.rate_limits_hit == 0
        assert metrics.timeouts == 0

    def test_metrics_tracking(self):
        """Test metric values can be updated."""
        metrics = ProviderMetrics()

        metrics.requests_total = 100
        metrics.requests_success = 95
        metrics.requests_failed = 5
        metrics.rate_limits_hit = 3
        metrics.total_latency_ms = 5000.0

        assert metrics.requests_total == 100
        assert metrics.requests_success == 95
        avg_latency = metrics.total_latency_ms / metrics.requests_total
        assert avg_latency == 50.0


class TestHTTPPoolMetrics:
    """Test aggregated pool metrics."""

    def test_get_provider_metrics_creates_new(self):
        """Test getting metrics creates new entry."""
        metrics = HTTPPoolMetrics()

        provider_metrics = metrics.get_provider_metrics("anthropic")

        assert "anthropic" in metrics.providers
        assert provider_metrics.requests_total == 0

    def test_get_provider_metrics_returns_existing(self):
        """Test getting metrics returns existing entry."""
        metrics = HTTPPoolMetrics()

        metrics.get_provider_metrics("openai").requests_total = 50
        provider_metrics = metrics.get_provider_metrics("openai")

        assert provider_metrics.requests_total == 50


class TestHTTPClientPool:
    """Test HTTP client pool functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        HTTPClientPool.reset_instance()

    def teardown_method(self):
        """Cleanup after each test."""
        HTTPClientPool.reset_instance()

    def test_singleton_instance(self):
        """Test singleton pattern."""
        pool1 = HTTPClientPool.get_instance()
        pool2 = HTTPClientPool.get_instance()

        assert pool1 is pool2

    def test_reset_instance(self):
        """Test singleton reset."""
        pool1 = HTTPClientPool.get_instance()
        HTTPClientPool.reset_instance()
        pool2 = HTTPClientPool.get_instance()

        assert pool1 is not pool2

    def test_get_http_pool_convenience(self):
        """Test convenience function."""
        pool = get_http_pool()

        assert isinstance(pool, HTTPClientPool)
        assert pool is HTTPClientPool.get_instance()

    def test_load_config_from_env(self):
        """Test environment variable configuration."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_HTTP_POOL_SIZE": "30",
                "ARAGORA_HTTP_TIMEOUT": "90",
                "ARAGORA_HTTP_MAX_RETRIES": "5",
            },
        ):
            pool = HTTPClientPool()

            assert pool.config.pool_size == 30
            assert pool.config.read_timeout == 90.0
            assert pool.config.max_retries == 5

    def test_get_provider_config(self):
        """Test provider config merging."""
        pool = HTTPClientPool()

        config = pool._get_provider_config("anthropic")

        assert "pool_size" in config
        assert "read_timeout" in config
        assert config["read_timeout"] == 120.0  # From provider config

    def test_get_provider_config_unknown(self):
        """Test config for unknown provider uses defaults."""
        pool = HTTPClientPool()

        config = pool._get_provider_config("unknown_provider")

        assert config["pool_size"] == pool.config.pool_size
        assert config["read_timeout"] == pool.config.read_timeout

    def test_get_sync_session(self):
        """Test sync session creation."""
        pool = HTTPClientPool()

        with patch.dict("sys.modules", {"requests": MagicMock()}):
            import sys

            mock_requests = sys.modules["requests"]
            mock_session = MagicMock()
            mock_requests.Session.return_value = mock_session

            # Clear any cached session
            pool._sync_sessions.clear()

            # Patch the module import inside the method
            with patch.object(pool, "_create_sync_session") as mock_create:
                mock_create.return_value = mock_session
                session = pool.get_sync_session("anthropic")

                assert session is mock_session
                mock_create.assert_called_once_with("anthropic")

    def test_sync_session_reuse(self):
        """Test sync session is reused."""
        pool = HTTPClientPool()
        mock_session = MagicMock()

        with patch.object(pool, "_create_sync_session", return_value=mock_session) as mock_create:
            session1 = pool.get_sync_session("anthropic")
            session2 = pool.get_sync_session("anthropic")

            assert session1 is session2
            assert mock_create.call_count == 1  # Only created once

    def test_sync_session_after_close_raises(self):
        """Test getting session after close raises error."""
        pool = HTTPClientPool()
        pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            pool.get_sync_session("anthropic")

    def test_get_metrics(self):
        """Test metrics retrieval."""
        pool = HTTPClientPool()

        # Simulate some activity
        pool.metrics.get_provider_metrics("anthropic").requests_total = 100
        pool.metrics.get_provider_metrics("anthropic").requests_success = 95

        metrics = pool.get_metrics()

        assert "providers" in metrics
        assert "anthropic" in metrics["providers"]
        assert metrics["providers"]["anthropic"]["requests_total"] == 100

    def test_metrics_avg_latency(self):
        """Test average latency calculation."""
        pool = HTTPClientPool()

        pm = pool.metrics.get_provider_metrics("openai")
        pm.requests_total = 10
        pm.total_latency_ms = 5000.0

        metrics = pool.get_metrics()

        assert metrics["providers"]["openai"]["avg_latency_ms"] == 500.0

    def test_metrics_avg_latency_zero_requests(self):
        """Test average latency is zero with no requests."""
        pool = HTTPClientPool()

        pool.metrics.get_provider_metrics("mistral")

        metrics = pool.get_metrics()

        assert metrics["providers"]["mistral"]["avg_latency_ms"] == 0

    def test_close_clears_sessions(self):
        """Test close clears all sessions."""
        pool = HTTPClientPool()
        pool._sync_sessions["test"] = MagicMock()

        pool.close()

        assert len(pool._sync_sessions) == 0
        assert pool._closed


class TestHTTPClientPoolAsync:
    """Test async functionality of HTTP client pool."""

    def setup_method(self):
        """Reset singleton before each test."""
        HTTPClientPool.reset_instance()

    def teardown_method(self):
        """Cleanup after each test."""
        HTTPClientPool.reset_instance()

    @pytest.mark.asyncio
    async def test_get_session_context_manager(self):
        """Test async session context manager."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            async with pool.get_session("anthropic") as client:
                assert client is mock_client

    @pytest.mark.asyncio
    async def test_session_reuse_increments_counter(self, monkeypatch):
        """Test session reuse is tracked."""
        # Disable test-isolation branch so the production reuse path is exercised
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            async with pool.get_session("anthropic"):
                pass

            async with pool.get_session("anthropic"):
                pass

            metrics = pool.metrics.get_provider_metrics("anthropic")
            assert metrics.connections_reused >= 1

    @pytest.mark.asyncio
    async def test_session_tracks_success(self):
        """Test successful requests are tracked."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            async with pool.get_session("openai"):
                pass

            metrics = pool.metrics.get_provider_metrics("openai")
            assert metrics.requests_success == 1
            assert metrics.requests_total == 1

    @pytest.mark.asyncio
    async def test_session_tracks_failure(self):
        """Test failed requests are tracked."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            try:
                async with pool.get_session("mistral"):
                    raise ConnectionError("Test error")
            except ConnectionError:
                pass

            metrics = pool.metrics.get_provider_metrics("mistral")
            assert metrics.requests_failed == 1

    @pytest.mark.asyncio
    async def test_session_tracks_rate_limit(self):
        """Test rate limit errors are tracked."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            try:
                async with pool.get_session("anthropic"):
                    raise ConnectionError("429 rate limit exceeded")
            except ConnectionError:
                pass

            metrics = pool.metrics.get_provider_metrics("anthropic")
            assert metrics.rate_limits_hit == 1

    @pytest.mark.asyncio
    async def test_session_tracks_timeout(self):
        """Test timeout errors are tracked."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            try:
                async with pool.get_session("openai"):
                    raise TimeoutError("Connection timeout")
            except Exception:
                pass

            metrics = pool.metrics.get_provider_metrics("openai")
            assert metrics.timeouts == 1

    @pytest.mark.asyncio
    async def test_session_tracks_latency(self):
        """Test latency is tracked."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            async with pool.get_session("anthropic"):
                await asyncio.sleep(0.01)  # 10ms

            metrics = pool.metrics.get_provider_metrics("anthropic")
            assert metrics.total_latency_ms >= 10

    @pytest.mark.asyncio
    async def test_aclose(self):
        """Test async close."""
        pool = HTTPClientPool()

        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        pool._async_clients["test"] = mock_client

        await pool.aclose()

        mock_client.aclose.assert_called_once()
        assert len(pool._async_clients) == 0


class TestHTTPClientPoolRetry:
    """Test retry functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        HTTPClientPool.reset_instance()

    def teardown_method(self):
        """Cleanup after each test."""
        HTTPClientPool.reset_instance()

    @pytest.mark.asyncio
    async def test_request_with_retry_success(self):
        """Test successful request without retry."""
        pool = HTTPClientPool()

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            response = await pool.request_with_retry(
                "anthropic",
                "POST",
                "https://api.anthropic.com/v1/messages",
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_with_retry_on_429(self):
        """Test retry on rate limit."""
        pool = HTTPClientPool(HTTPPoolConfig(max_retries=2, retry_delay=0.01))

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[mock_response_429, mock_response_200])

        with patch.object(pool, "_create_async_client", return_value=mock_client):
            response = await pool.request_with_retry(
                "anthropic",
                "POST",
                "https://api.anthropic.com/v1/messages",
            )

            assert response.status_code == 200
            metrics = pool.metrics.get_provider_metrics("anthropic")
            assert metrics.rate_limits_hit == 1
            assert metrics.requests_retried >= 1

    @pytest.mark.asyncio
    async def test_request_with_retry_respects_retry_after(self):
        """Test Retry-After header is respected."""
        pool = HTTPClientPool(HTTPPoolConfig(max_retries=2, retry_delay=0.01))

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "0.01"}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[mock_response_429, mock_response_200])

        start = time.time()
        with patch.object(pool, "_create_async_client", return_value=mock_client):
            response = await pool.request_with_retry(
                "openai",
                "POST",
                "https://api.openai.com/v1/chat/completions",
            )
            elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed >= 0.01  # Respected Retry-After

    @pytest.mark.asyncio
    async def test_request_with_retry_exponential_backoff(self):
        """Test exponential backoff on retry."""
        pool = HTTPClientPool(
            HTTPPoolConfig(
                max_retries=3,
                retry_delay=0.01,
                retry_multiplier=2.0,
            )
        )

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=ConnectionError("Connection error"))

        start = time.time()
        with patch.object(pool, "_create_async_client", return_value=mock_client):
            with pytest.raises(ConnectionError, match="Connection error"):
                await pool.request_with_retry(
                    "mistral",
                    "POST",
                    "https://api.mistral.ai/v1/chat/completions",
                )
            elapsed = time.time() - start

        # Should have delays: 0.01 + 0.02 + 0.04 = 0.07 minimum
        assert elapsed >= 0.07

    @pytest.mark.asyncio
    async def test_request_with_retry_max_delay(self):
        """Test max delay is respected."""
        # Use small values to make test fast
        pool = HTTPClientPool(
            HTTPPoolConfig(
                max_retries=3,
                retry_delay=0.01,  # Small base delay
                retry_multiplier=100.0,  # Would grow very fast without cap
                retry_max_delay=0.02,  # Cap prevents exponential growth
            )
        )

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=ConnectionError("Error"))

        start = time.time()
        with patch.object(pool, "_create_async_client", return_value=mock_client):
            with pytest.raises(ConnectionError):
                await pool.request_with_retry(
                    "xai",
                    "GET",
                    "https://api.x.ai/v1/test",
                )
            elapsed = time.time() - start

        # With cap: delays are 0.01, 0.02 (capped), 0.02 (capped) = 0.05
        # Without cap: delays would be 0.01, 1.0, 100.0 = very long
        # Just verify it completed reasonably fast
        assert elapsed < 0.5  # Should complete in well under 500ms
