"""
Tests for Prometheus metrics module.

Tests both the prometheus_client integration and the fallback SimpleMetrics
implementation used when prometheus_client is not available.
"""

import pytest
from unittest.mock import patch, MagicMock

from aragora.observability.prometheus import (
    # Public API
    get_metrics_output,
    is_prometheus_available,
    record_debate_completed,
    record_tokens_used,
    record_agent_generation,
    record_agent_failure,
    set_circuit_breaker_state,
    record_http_request,
    set_websocket_connections,
    record_websocket_message,
    record_rate_limit_hit,
    set_rate_limit_tokens_tracked,
    set_cache_size,
    record_cache_hit,
    record_cache_miss,
    set_server_info,
    # Decorators
    timed_http_request,
    timed_agent_generation,
    # Internal for testing
    SimpleMetrics,
    PROMETHEUS_AVAILABLE,
)


class TestPrometheusAvailability:
    """Tests for prometheus_client availability detection."""

    def test_is_prometheus_available_returns_bool(self):
        """is_prometheus_available should return a boolean."""
        result = is_prometheus_available()
        assert isinstance(result, bool)

    def test_prometheus_constant_matches_function(self):
        """PROMETHEUS_AVAILABLE constant should match function result."""
        assert is_prometheus_available() == PROMETHEUS_AVAILABLE


class TestSimpleMetrics:
    """Tests for SimpleMetrics fallback implementation."""

    def test_counter_increment(self):
        """Counter increment works correctly."""
        metrics = SimpleMetrics()
        metrics.inc_counter("test_counter")
        metrics.inc_counter("test_counter")
        assert metrics.counters.get("test_counter") == 2

    def test_counter_increment_with_value(self):
        """Counter increment with custom value works."""
        metrics = SimpleMetrics()
        metrics.inc_counter("test_counter", value=5)
        assert metrics.counters.get("test_counter") == 5

    def test_counter_with_labels(self):
        """Counter with labels creates unique keys."""
        metrics = SimpleMetrics()
        metrics.inc_counter("requests", {"method": "GET", "status": "200"})
        metrics.inc_counter("requests", {"method": "POST", "status": "201"})

        assert len(metrics.counters) == 2
        # Keys should include labels
        keys = list(metrics.counters.keys())
        assert any("GET" in k for k in keys)
        assert any("POST" in k for k in keys)

    def test_gauge_set(self):
        """Gauge set works correctly."""
        metrics = SimpleMetrics()
        metrics.set_gauge("connections", 10)
        assert metrics.gauges.get("connections") == 10

        # Setting again should overwrite
        metrics.set_gauge("connections", 5)
        assert metrics.gauges.get("connections") == 5

    def test_gauge_with_labels(self):
        """Gauge with labels works correctly."""
        metrics = SimpleMetrics()
        metrics.set_gauge("cache_size", 100, {"cache_name": "handler"})

        keys = list(metrics.gauges.keys())
        assert any("handler" in k for k in keys)

    def test_histogram_observe(self):
        """Histogram observe collects values."""
        metrics = SimpleMetrics()
        metrics.observe_histogram("latency", 0.5)
        metrics.observe_histogram("latency", 1.0)
        metrics.observe_histogram("latency", 0.3)

        assert len(metrics.histograms.get("latency", [])) == 3

    def test_info_set(self):
        """Info metric set works correctly."""
        metrics = SimpleMetrics()
        metrics.set_info("server", {"version": "1.0", "env": "test"})

        assert "server" in metrics.info
        assert metrics.info["server"]["version"] == "1.0"

    def test_generate_output_format(self):
        """generate_output produces Prometheus-compatible format."""
        metrics = SimpleMetrics()
        metrics.inc_counter("test_requests")
        metrics.set_gauge("test_gauge", 42)
        metrics.observe_histogram("test_latency", 0.5)
        metrics.set_info("test_info", {"key": "value"})

        output = metrics.generate_output()

        # Should contain counter
        assert "test_requests" in output
        # Should contain gauge
        assert "test_gauge 42" in output
        # Should contain histogram count and sum
        assert "test_latency_count" in output
        assert "test_latency_sum" in output
        # Should contain info
        assert "test_info_info" in output
        # Should end with newline
        assert output.endswith("\n")

    def test_make_key_without_labels(self):
        """_make_key without labels returns just the name."""
        metrics = SimpleMetrics()
        key = metrics._make_key("test_metric")
        assert key == "test_metric"

    def test_make_key_with_labels(self):
        """_make_key with labels returns formatted key."""
        metrics = SimpleMetrics()
        key = metrics._make_key("test_metric", {"a": "1", "b": "2"})
        # Labels should be sorted alphabetically
        assert 'a="1"' in key
        assert 'b="2"' in key


class TestRecordDebateCompleted:
    """Tests for record_debate_completed function."""

    def test_records_consensus_debate(self):
        """Record a debate that reached consensus."""
        # Should not raise any exceptions
        record_debate_completed(
            duration_seconds=45.5,
            rounds_used=3,
            outcome="consensus",
            agent_count=4,
        )

    def test_records_no_consensus_debate(self):
        """Record a debate that did not reach consensus."""
        record_debate_completed(
            duration_seconds=120.0,
            rounds_used=5,
            outcome="no_consensus",
            agent_count=2,
        )

    def test_records_error_debate(self):
        """Record a debate that ended in error."""
        record_debate_completed(
            duration_seconds=5.0,
            rounds_used=1,
            outcome="error",
            agent_count=3,
        )

    def test_records_timeout_debate(self):
        """Record a debate that timed out."""
        record_debate_completed(
            duration_seconds=300.0,
            rounds_used=2,
            outcome="timeout",
            agent_count=4,
        )


class TestRecordTokensUsed:
    """Tests for record_tokens_used function."""

    def test_records_token_usage(self):
        """Record token usage for a model."""
        record_tokens_used(
            model="gpt-4",
            input_tokens=1000,
            output_tokens=500,
        )

    def test_records_zero_tokens(self):
        """Record zero tokens doesn't fail."""
        record_tokens_used(
            model="claude-3",
            input_tokens=0,
            output_tokens=0,
        )


class TestRecordAgentGeneration:
    """Tests for record_agent_generation function."""

    def test_records_generation_time(self):
        """Record agent generation time."""
        record_agent_generation(
            agent_type="anthropic",
            model="claude-3-opus",
            duration_seconds=2.5,
        )


class TestRecordAgentFailure:
    """Tests for record_agent_failure function."""

    def test_records_timeout_failure(self):
        """Record timeout failure."""
        record_agent_failure(
            agent_type="openai",
            error_type="TimeoutError",
        )

    def test_records_api_failure(self):
        """Record API error failure."""
        record_agent_failure(
            agent_type="gemini",
            error_type="APIError",
        )


class TestSetCircuitBreakerState:
    """Tests for set_circuit_breaker_state function."""

    def test_set_closed_state(self):
        """Set circuit breaker to closed (0)."""
        set_circuit_breaker_state("anthropic", 0)

    def test_set_open_state(self):
        """Set circuit breaker to open (1)."""
        set_circuit_breaker_state("openai", 1)

    def test_set_half_open_state(self):
        """Set circuit breaker to half-open (2)."""
        set_circuit_breaker_state("gemini", 2)


class TestRecordHttpRequest:
    """Tests for record_http_request function."""

    def test_records_successful_request(self):
        """Record a successful HTTP request."""
        record_http_request(
            method="GET",
            endpoint="/api/debates",
            status=200,
            duration_seconds=0.05,
        )

    def test_records_error_request(self):
        """Record a failed HTTP request."""
        record_http_request(
            method="POST",
            endpoint="/api/debate",
            status=500,
            duration_seconds=0.1,
        )


class TestWebSocketMetrics:
    """Tests for WebSocket metric functions."""

    def test_set_websocket_connections(self):
        """Set active WebSocket connection count."""
        set_websocket_connections(10)
        set_websocket_connections(0)

    def test_record_websocket_message_sent(self):
        """Record a sent WebSocket message."""
        record_websocket_message(
            direction="sent",
            message_type="debate_update",
        )

    def test_record_websocket_message_received(self):
        """Record a received WebSocket message."""
        record_websocket_message(
            direction="received",
            message_type="user_vote",
        )


class TestRateLimitMetrics:
    """Tests for rate limit metric functions."""

    def test_record_token_rate_limit(self):
        """Record token-based rate limit hit."""
        record_rate_limit_hit("token")

    def test_record_ip_rate_limit(self):
        """Record IP-based rate limit hit."""
        record_rate_limit_hit("ip")

    def test_set_tokens_tracked(self):
        """Set number of tokens being tracked."""
        set_rate_limit_tokens_tracked(500)


class TestCacheMetrics:
    """Tests for cache metric functions."""

    def test_set_cache_size(self):
        """Set cache size for a named cache."""
        set_cache_size("handler_cache", 100)

    def test_record_cache_hit(self):
        """Record a cache hit."""
        record_cache_hit("handler_cache")

    def test_record_cache_miss(self):
        """Record a cache miss."""
        record_cache_miss("handler_cache")


class TestSetServerInfo:
    """Tests for set_server_info function."""

    def test_set_server_info(self):
        """Set server information."""
        set_server_info(
            version="0.8.0",
            python_version="3.11.0",
            start_time=1704067200.0,
        )


class TestGetMetricsOutput:
    """Tests for get_metrics_output function."""

    def test_returns_tuple(self):
        """get_metrics_output returns (content, content_type) tuple."""
        content, content_type = get_metrics_output()

        assert isinstance(content, str)
        assert isinstance(content_type, str)

    def test_content_type_is_prometheus_format(self):
        """Content type should indicate prometheus format."""
        _, content_type = get_metrics_output()

        assert "text/" in content_type


class TestTimedHttpRequestDecorator:
    """Tests for timed_http_request decorator."""

    def test_decorator_times_function(self):
        """Decorator should time function execution."""

        @timed_http_request("/api/test")
        def test_handler():
            return MagicMock(status_code=200)

        result = test_handler()
        assert result is not None

    def test_decorator_handles_exception(self):
        """Decorator should record 500 on exception."""

        @timed_http_request("/api/test")
        def failing_handler():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_handler()


class TestTimedAgentGenerationDecorator:
    """Tests for timed_agent_generation decorator."""

    @pytest.mark.asyncio
    async def test_decorator_times_async_function(self):
        """Decorator should time async function execution."""

        @timed_agent_generation("test_agent", "test_model")
        async def test_generate():
            return "Generated text"

        result = await test_generate()
        assert result == "Generated text"

    @pytest.mark.asyncio
    async def test_decorator_records_failure(self):
        """Decorator should record failure on exception."""

        @timed_agent_generation("test_agent", "test_model")
        async def failing_generate():
            raise RuntimeError("Generation failed")

        with pytest.raises(RuntimeError):
            await failing_generate()


class TestMetricsIntegration:
    """Integration tests for metrics recording."""

    def test_full_debate_metrics_flow(self):
        """Test recording a complete debate metrics flow."""
        # Record debate start metrics
        set_websocket_connections(5)

        # Record agent generation
        record_agent_generation("anthropic", "claude-3", 2.0)
        record_agent_generation("openai", "gpt-4", 1.5)

        # Record token usage
        record_tokens_used("claude-3", 1000, 500)
        record_tokens_used("gpt-4", 800, 400)

        # Record debate completion
        record_debate_completed(
            duration_seconds=60.0,
            rounds_used=3,
            outcome="consensus",
            agent_count=2,
        )

        # Get metrics output
        content, content_type = get_metrics_output()

        # Verify output is non-empty
        assert len(content) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
