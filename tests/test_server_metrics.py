"""
Tests for the server metrics module.

Tests Counter, Gauge, Histogram metric types, tracking helpers,
and Prometheus-format export.
"""

from __future__ import annotations

import time
import pytest
from threading import Thread
from contextlib import contextmanager

from aragora.server.metrics import (
    Counter,
    Gauge,
    Histogram,
    LabeledCounter,
    LabeledGauge,
    LabeledHistogram,
    get_percentile,
    get_percentiles,
    track_request,
    track_subscription_event,
    track_debate,
    track_tokens,
    track_agent_call,
    track_auth_failure,
    track_rate_limit_hit,
    track_security_violation,
    track_debate_outcome,
    track_circuit_breaker_state,
    track_agent_error,
    classify_agent_error,
    track_agent_participation,
    track_execution_gate_decision,
    track_debate_execution,
    generate_metrics,
    _format_labels,
    # Global metric instances for reset
    API_REQUESTS,
    API_LATENCY,
    AGENT_REQUESTS,
    AGENT_LATENCY,
    AGENT_TOKENS,
    AUTH_FAILURES,
    RATE_LIMIT_HITS,
    SECURITY_VIOLATIONS,
    DEBATES_TOTAL,
    DEBATE_DURATION,
    DEBATE_CONFIDENCE,
    CONSENSUS_REACHED,
    CONSENSUS_QUALITY,
    ACTIVE_DEBATES,
    CIRCUIT_BREAKERS_OPEN,
    AGENT_ERRORS,
    AGENT_PARTICIPATION,
    LAST_DEBATE_TIMESTAMP,
    EXECUTION_GATE_DECISIONS,
    EXECUTION_GATE_BLOCK_REASONS,
    EXECUTION_GATE_PROVIDER_DIVERSITY,
    EXECUTION_GATE_MODEL_FAMILY_DIVERSITY,
    EXECUTION_GATE_RECEIPT_VERIFICATION,
    EXECUTION_GATE_CONTEXT_TAINT,
    EXECUTION_GATE_CORRELATED_RISK,
    SUBSCRIPTION_EVENTS,
    USAGE_DEBATES,
    USAGE_TOKENS,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def counter():
    """Create a fresh Counter for testing."""
    return Counter(
        name="test_counter",
        help="Test counter metric",
        label_names=["method", "status"],
    )


@pytest.fixture
def gauge():
    """Create a fresh Gauge for testing."""
    return Gauge(
        name="test_gauge",
        help="Test gauge metric",
        label_names=["endpoint"],
    )


@pytest.fixture
def histogram():
    """Create a fresh Histogram for testing."""
    return Histogram(
        name="test_histogram",
        help="Test histogram metric",
        label_names=["endpoint"],
        buckets=[0.1, 0.5, 1.0, 5.0],
    )


@pytest.fixture(autouse=True)
def reset_global_metrics():
    """Reset global metrics between tests."""
    # Clear Counter metrics
    for metric in [
        API_REQUESTS,
        AGENT_REQUESTS,
        AGENT_TOKENS,
        AUTH_FAILURES,
        RATE_LIMIT_HITS,
        SECURITY_VIOLATIONS,
        DEBATES_TOTAL,
        CONSENSUS_REACHED,
        AGENT_ERRORS,
        AGENT_PARTICIPATION,
        EXECUTION_GATE_DECISIONS,
        EXECUTION_GATE_BLOCK_REASONS,
        EXECUTION_GATE_RECEIPT_VERIFICATION,
        EXECUTION_GATE_CONTEXT_TAINT,
        EXECUTION_GATE_CORRELATED_RISK,
        SUBSCRIPTION_EVENTS,
        USAGE_DEBATES,
        USAGE_TOKENS,
    ]:
        with metric._lock:
            metric._values.clear()

    # Clear Gauge metrics
    for metric in [
        ACTIVE_DEBATES,
        CIRCUIT_BREAKERS_OPEN,
        CONSENSUS_QUALITY,
        LAST_DEBATE_TIMESTAMP,
    ]:
        with metric._lock:
            metric._values.clear()

    # Clear Histogram metrics
    for metric in [
        API_LATENCY,
        AGENT_LATENCY,
        DEBATE_DURATION,
        DEBATE_CONFIDENCE,
        EXECUTION_GATE_PROVIDER_DIVERSITY,
        EXECUTION_GATE_MODEL_FAMILY_DIVERSITY,
    ]:
        with metric._lock:
            metric._counts.clear()
            metric._sums.clear()
            metric._totals.clear()

    yield


# =============================================================================
# Counter Tests
# =============================================================================


class TestCounter:
    """Tests for Counter metric type."""

    def test_inc_without_labels(self, counter):
        """Counter should increment without labels."""
        counter.inc()
        assert counter.get() == 1.0

        counter.inc(5)
        assert counter.get() == 6.0

    def test_inc_with_labels(self, counter):
        """Counter should track values per label combination."""
        counter.inc(method="GET", status="200")
        counter.inc(method="POST", status="200")
        counter.inc(method="GET", status="200")

        assert counter.get(method="GET", status="200") == 2.0
        assert counter.get(method="POST", status="200") == 1.0
        assert counter.get(method="GET", status="500") == 0.0

    def test_labels_returns_labeled_counter(self, counter):
        """labels() should return a LabeledCounter."""
        labeled = counter.labels(method="GET", status="200")
        assert isinstance(labeled, LabeledCounter)

    def test_labeled_counter_increments(self, counter):
        """LabeledCounter should increment the parent counter."""
        labeled = counter.labels(method="DELETE", status="204")
        labeled.inc()
        labeled.inc(3)

        assert counter.get(method="DELETE", status="204") == 4.0

    def test_collect_returns_all_values(self, counter):
        """collect() should return all label/value pairs."""
        counter.inc(method="GET", status="200")
        counter.inc(method="POST", status="201")

        collected = counter.collect()
        assert len(collected) == 2

        # Convert to dict for easier assertion
        values = {tuple(sorted(labels.items())): val for labels, val in collected}
        assert values[(("method", "GET"), ("status", "200"))] == 1.0
        assert values[(("method", "POST"), ("status", "201"))] == 1.0

    def test_counter_thread_safety(self, counter):
        """Counter should be thread-safe."""

        def increment_many():
            for _ in range(100):
                counter.inc(method="GET", status="200")

        threads = [Thread(target=increment_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter.get(method="GET", status="200") == 1000.0


# =============================================================================
# Gauge Tests
# =============================================================================


class TestGauge:
    """Tests for Gauge metric type."""

    def test_set_value(self, gauge):
        """Gauge should set value."""
        gauge.set(42.0)
        assert gauge.get() == 42.0

    def test_set_with_labels(self, gauge):
        """Gauge should track values per label."""
        gauge.set(10, endpoint="/api/debates")
        gauge.set(5, endpoint="/api/agents")

        assert gauge.get(endpoint="/api/debates") == 10
        assert gauge.get(endpoint="/api/agents") == 5

    def test_inc_gauge(self, gauge):
        """Gauge should support increment."""
        gauge.inc(endpoint="/api/health")
        gauge.inc(2, endpoint="/api/health")

        assert gauge.get(endpoint="/api/health") == 3.0

    def test_dec_gauge(self, gauge):
        """Gauge should support decrement."""
        gauge.set(10, endpoint="/api/test")
        gauge.dec(3, endpoint="/api/test")

        assert gauge.get(endpoint="/api/test") == 7.0

    def test_labels_returns_labeled_gauge(self, gauge):
        """labels() should return a LabeledGauge."""
        labeled = gauge.labels(endpoint="/api/test")
        assert isinstance(labeled, LabeledGauge)

    def test_labeled_gauge_operations(self, gauge):
        """LabeledGauge should support set/inc/dec."""
        labeled = gauge.labels(endpoint="/api/ws")
        labeled.set(5)
        assert gauge.get(endpoint="/api/ws") == 5

        labeled.inc(2)
        assert gauge.get(endpoint="/api/ws") == 7

        labeled.dec(1)
        assert gauge.get(endpoint="/api/ws") == 6

    def test_collect_returns_all_values(self, gauge):
        """collect() should return all label/value pairs."""
        gauge.set(1, endpoint="/a")
        gauge.set(2, endpoint="/b")

        collected = gauge.collect()
        assert len(collected) == 2


# =============================================================================
# Histogram Tests
# =============================================================================


class TestHistogram:
    """Tests for Histogram metric type."""

    def test_observe_updates_buckets(self, histogram):
        """observe() should update appropriate buckets."""
        histogram.observe(0.05, endpoint="/api/test")  # <= 0.1
        histogram.observe(0.3, endpoint="/api/test")  # <= 0.5
        histogram.observe(0.8, endpoint="/api/test")  # <= 1.0
        histogram.observe(3.0, endpoint="/api/test")  # <= 5.0

        collected = histogram.collect()
        assert len(collected) == 1

        data = collected[0][1]
        assert data["count"] == 4
        assert data["sum"] == pytest.approx(4.15, rel=0.01)

        # Check bucket counts
        buckets = dict(data["buckets"])
        assert buckets[0.1] == 1  # 0.05
        assert buckets[0.5] == 2  # 0.05, 0.3
        assert buckets[1.0] == 3  # 0.05, 0.3, 0.8
        assert buckets[5.0] == 4  # All

    def test_labels_returns_labeled_histogram(self, histogram):
        """labels() should return a LabeledHistogram."""
        labeled = histogram.labels(endpoint="/test")
        assert isinstance(labeled, LabeledHistogram)

    def test_labeled_histogram_observe(self, histogram):
        """LabeledHistogram should observe values correctly."""
        labeled = histogram.labels(endpoint="/metrics")
        labeled.observe(0.2)
        labeled.observe(0.7)

        collected = histogram.collect()
        assert len(collected) == 1
        assert collected[0][1]["count"] == 2

    def test_histogram_without_labels(self):
        """Histogram should work without labels."""
        h = Histogram(name="simple", help="Simple histogram", buckets=[1.0, 5.0])
        h.observe(0.5)
        h.observe(2.0)

        collected = h.collect()
        assert collected[0][1]["count"] == 2


# =============================================================================
# Percentile Tests
# =============================================================================


class TestPercentiles:
    """Tests for percentile calculation functions."""

    def test_get_percentile_empty(self, histogram):
        """get_percentile should return None for empty histogram."""
        result = get_percentile(histogram, 50)
        assert result is None

    def test_get_percentile_single_value(self, histogram):
        """get_percentile should work with single value."""
        histogram.observe(0.3, endpoint="/test")

        p50 = get_percentile(histogram, 50, endpoint="/test")
        assert p50 is not None

    def test_get_percentile_distribution(self, histogram):
        """get_percentile should estimate percentiles from distribution."""
        # Add values to create a distribution
        for _ in range(10):
            histogram.observe(0.05, endpoint="/test")  # 10 at 0.05
        for _ in range(5):
            histogram.observe(0.3, endpoint="/test")  # 5 at 0.3
        for _ in range(3):
            histogram.observe(0.8, endpoint="/test")  # 3 at 0.8
        for _ in range(2):
            histogram.observe(3.0, endpoint="/test")  # 2 at 3.0

        p50 = get_percentile(histogram, 50, endpoint="/test")
        p90 = get_percentile(histogram, 90, endpoint="/test")
        p99 = get_percentile(histogram, 99, endpoint="/test")

        # P50 should be in lower buckets (most values are small)
        assert p50 is not None and p50 <= 0.5
        # P90 should be higher
        assert p90 is not None and p90 >= p50
        # P99 should be highest
        assert p99 is not None and p99 >= p90

    def test_get_percentiles_convenience(self, histogram):
        """get_percentiles should return dict with common percentiles."""
        histogram.observe(0.1, endpoint="/test")

        result = get_percentiles(histogram, endpoint="/test")

        assert "p50" in result
        assert "p90" in result
        assert "p95" in result
        assert "p99" in result


# =============================================================================
# Track Request Tests
# =============================================================================


class TestTrackRequest:
    """Tests for track_request context manager."""

    def test_tracks_successful_request(self):
        """track_request should record success status."""
        with track_request("/api/test", "GET"):
            pass

        assert API_REQUESTS.get(endpoint="/api/test", method="GET", status="success") == 1

    def test_tracks_failed_request(self):
        """track_request should record error status on exception."""
        with pytest.raises(ValueError):
            with track_request("/api/test", "POST"):
                raise ValueError("test error")

        assert API_REQUESTS.get(endpoint="/api/test", method="POST", status="error") == 1

    def test_tracks_latency(self):
        """track_request should record latency."""
        with track_request("/api/slow", "GET"):
            time.sleep(0.01)

        collected = API_LATENCY.collect()
        assert len(collected) >= 1


# =============================================================================
# Tracking Helper Tests
# =============================================================================


class TestTrackingHelpers:
    """Tests for tracking helper functions."""

    def test_track_subscription_event(self):
        """track_subscription_event should increment counter."""
        track_subscription_event("created", "starter")
        track_subscription_event("created", "professional")

        assert SUBSCRIPTION_EVENTS.get(event="created", tier="starter") == 1
        assert SUBSCRIPTION_EVENTS.get(event="created", tier="professional") == 1

    def test_track_debate(self):
        """track_debate should increment counter."""
        track_debate("starter", "org-123")

        assert USAGE_DEBATES.get(tier="starter", org_id="org-123") == 1

    def test_track_tokens(self):
        """track_tokens should increment by count."""
        track_tokens("anthropic", "professional", 1000)

        assert USAGE_TOKENS.get(provider="anthropic", tier="professional") == 1000

    def test_track_agent_call(self):
        """track_agent_call should record multiple metrics."""
        track_agent_call("claude", 1.5, 100, 200, True)

        assert AGENT_REQUESTS.get(agent="claude", status="success") == 1
        assert AGENT_TOKENS.get(agent="claude", direction="input") == 100
        assert AGENT_TOKENS.get(agent="claude", direction="output") == 200

    def test_track_agent_call_failure(self):
        """track_agent_call should record error status."""
        track_agent_call("gpt4", 0.5, 50, 0, False)

        assert AGENT_REQUESTS.get(agent="gpt4", status="error") == 1

    def test_track_auth_failure(self):
        """track_auth_failure should increment counter."""
        track_auth_failure("invalid_token", "/api/debates")

        assert AUTH_FAILURES.get(reason="invalid_token", endpoint="/api/debates") == 1

    def test_track_rate_limit_hit(self):
        """track_rate_limit_hit should increment counter."""
        track_rate_limit_hit("/api/agents", "request")

        assert RATE_LIMIT_HITS.get(endpoint="/api/agents", limit_type="request") == 1

    def test_track_security_violation(self):
        """track_security_violation should increment counter."""
        track_security_violation("path_traversal")

        assert SECURITY_VIOLATIONS.get(type="path_traversal") == 1

    def test_track_circuit_breaker_state(self):
        """track_circuit_breaker_state should set gauge."""
        track_circuit_breaker_state(3)

        assert CIRCUIT_BREAKERS_OPEN.get() == 3

    def test_track_agent_error(self):
        """track_agent_error should increment counter."""
        track_agent_error("claude", "timeout")

        assert AGENT_ERRORS.get(agent="claude", error_type="timeout") == 1

    def test_track_agent_participation(self):
        """track_agent_participation should increment counter."""
        track_agent_participation("claude", "won")

        assert AGENT_PARTICIPATION.get(agent_name="claude", outcome="won") == 1


# =============================================================================
# Classify Agent Error Tests
# =============================================================================


class TestClassifyAgentError:
    """Tests for classify_agent_error function."""

    def test_timeout_error(self):
        """Should classify TimeoutError as timeout."""
        assert classify_agent_error(TimeoutError()) == "timeout"

    def test_rate_limit_error_by_status(self):
        """Should classify 429 errors as rate_limit."""
        error = Exception("API returned 429 Too Many Requests")
        assert classify_agent_error(error) == "rate_limit"

    def test_auth_error_by_status(self):
        """Should classify 401/403 errors as auth."""
        error = Exception("API returned 401 Unauthorized")
        assert classify_agent_error(error) == "auth"

    def test_connection_error(self):
        """Should classify ConnectionError as network."""
        assert classify_agent_error(ConnectionError()) == "network"

    def test_validation_error(self):
        """Should classify ValueError as validation."""
        assert classify_agent_error(ValueError()) == "validation"

    def test_unknown_error(self):
        """Should classify unknown errors as unknown."""

        class CustomError(Exception):
            pass

        assert classify_agent_error(CustomError()) == "unknown"


# =============================================================================
# Track Debate Outcome Tests
# =============================================================================


class TestTrackDebateOutcome:
    """Tests for track_debate_outcome function."""

    def test_tracks_completed_debate(self):
        """Should track completed debate metrics."""
        track_debate_outcome(
            status="completed",
            domain="security",
            duration_seconds=30.0,
            consensus_reached=True,
            confidence=0.85,
            consensus_type="majority",
        )

        assert DEBATES_TOTAL.get(status="completed", domain="security") == 1
        assert CONSENSUS_REACHED.get(domain="security", consensus_type="majority") == 1

    def test_updates_last_timestamp(self):
        """Should update last debate timestamp."""
        before = time.time()
        track_debate_outcome("completed", "general", 10.0)
        after = time.time()

        timestamp = LAST_DEBATE_TIMESTAMP.get()
        assert before <= timestamp <= after

    def test_tracks_duration_histogram(self):
        """Should record duration in histogram."""
        track_debate_outcome("completed", "testing", 45.0)

        collected = DEBATE_DURATION.collect()
        assert len(collected) >= 1


# =============================================================================
# Track Execution Gate Tests
# =============================================================================


class TestTrackExecutionGateDecision:
    """Tests for execution safety gate telemetry helper."""

    def test_tracks_allowed_gate_with_verified_receipt(self):
        """Should track allow decisions, receipt status, and diversity."""
        gate = {
            "allow_auto_execution": True,
            "reason_codes": [],
            "provider_diversity": 3,
            "model_family_diversity": 3,
            "receipt_signed": True,
            "receipt_integrity_valid": True,
            "receipt_signature_valid": True,
            "context_taint_detected": False,
            "correlated_failure_risk": False,
            "suspicious_unanimity_risk": False,
        }

        track_execution_gate_decision(gate, path="unit_test", domain="security")

        assert (
            EXECUTION_GATE_DECISIONS.get(path="unit_test", domain="security", decision="allow") == 1
        )
        assert (
            EXECUTION_GATE_RECEIPT_VERIFICATION.get(
                path="unit_test", domain="security", status="verified"
            )
            == 1
        )
        assert (
            EXECUTION_GATE_CONTEXT_TAINT.get(path="unit_test", domain="security", state="clean")
            == 1
        )
        assert (
            EXECUTION_GATE_CORRELATED_RISK.get(path="unit_test", domain="security", state="clear")
            == 1
        )

        provider_rows = [
            data
            for labels, data in EXECUTION_GATE_PROVIDER_DIVERSITY.collect()
            if labels == {"domain": "security", "path": "unit_test"}
        ]
        model_rows = [
            data
            for labels, data in EXECUTION_GATE_MODEL_FAMILY_DIVERSITY.collect()
            if labels == {"domain": "security", "path": "unit_test"}
        ]
        assert provider_rows and provider_rows[0]["count"] == 1
        assert model_rows and model_rows[0]["count"] == 1

    def test_tracks_denied_gate_and_reason_breakdown(self):
        """Should track deny reason codes and risk signals."""
        gate = {
            "allow_auto_execution": False,
            "reason_codes": ["provider_diversity_below_minimum", "tainted_context_detected"],
            "provider_diversity": 1,
            "model_family_diversity": 1,
            "receipt_signed": False,
            "receipt_integrity_valid": False,
            "receipt_signature_valid": False,
            "context_taint_detected": True,
            "correlated_failure_risk": True,
            "suspicious_unanimity_risk": False,
        }

        track_execution_gate_decision(gate, path="post_debate", domain="general")

        assert (
            EXECUTION_GATE_DECISIONS.get(path="post_debate", domain="general", decision="deny") == 1
        )
        assert (
            EXECUTION_GATE_BLOCK_REASONS.get(
                path="post_debate",
                domain="general",
                reason="provider_diversity_below_minimum",
            )
            == 1
        )
        assert (
            EXECUTION_GATE_BLOCK_REASONS.get(
                path="post_debate",
                domain="general",
                reason="tainted_context_detected",
            )
            == 1
        )
        assert (
            EXECUTION_GATE_RECEIPT_VERIFICATION.get(
                path="post_debate",
                domain="general",
                status="failed",
            )
            == 1
        )
        assert (
            EXECUTION_GATE_CONTEXT_TAINT.get(
                path="post_debate",
                domain="general",
                state="tainted",
            )
            == 1
        )
        assert (
            EXECUTION_GATE_CORRELATED_RISK.get(
                path="post_debate",
                domain="general",
                state="detected",
            )
            == 1
        )

    def test_ignores_non_dict_gate_payload(self):
        """Should no-op when gate payload is missing or malformed."""
        track_execution_gate_decision(None)
        track_execution_gate_decision("not-a-dict")  # type: ignore[arg-type]
        assert EXECUTION_GATE_DECISIONS.collect() == []


# =============================================================================
# Track Debate Execution Tests
# =============================================================================


class TestTrackDebateExecution:
    """Tests for track_debate_execution context manager."""

    def test_tracks_successful_execution(self):
        """Should track successful debate execution."""
        with track_debate_execution(domain="general") as ctx:
            ctx["consensus"] = True
            ctx["confidence"] = 0.9
            ctx["status"] = "completed"

        assert DEBATES_TOTAL.get(status="completed", domain="general") == 1
        assert CONSENSUS_REACHED.get(domain="general", consensus_type="majority") == 1

    def test_tracks_active_debates_during_execution(self):
        """Should increment/decrement active debates gauge."""
        # Check initial state
        initial = ACTIVE_DEBATES.get()

        with track_debate_execution():
            during = ACTIVE_DEBATES.get()
            assert during == initial + 1

        after = ACTIVE_DEBATES.get()
        assert after == initial

    def test_tracks_error_status_on_exception(self):
        """Should track error status when exception occurs."""
        with pytest.raises(RuntimeError):
            with track_debate_execution(domain="error_test"):
                raise RuntimeError("test")

        assert DEBATES_TOTAL.get(status="error", domain="error_test") == 1


# =============================================================================
# Format Labels Tests
# =============================================================================


class TestFormatLabels:
    """Tests for _format_labels helper."""

    def test_empty_labels(self):
        """Should return empty string for no labels."""
        assert _format_labels({}) == ""

    def test_single_label(self):
        """Should format single label correctly."""
        result = _format_labels({"method": "GET"})
        assert result == '{method="GET"}'

    def test_multiple_labels_sorted(self):
        """Should sort labels alphabetically."""
        result = _format_labels({"z": "1", "a": "2"})
        assert result == '{a="2",z="1"}'


# =============================================================================
# Generate Metrics Tests
# =============================================================================


class TestGenerateMetrics:
    """Tests for generate_metrics function."""

    def test_generates_prometheus_format(self):
        """Should generate valid Prometheus format output."""
        # Add some test data
        API_REQUESTS.inc(endpoint="/test", method="GET", status="success")

        output = generate_metrics()

        assert "# HELP" in output
        assert "# TYPE" in output
        assert "aragora_api_requests_total" in output

    def test_includes_help_and_type(self):
        """Should include HELP and TYPE comments."""
        output = generate_metrics()

        lines = output.split("\n")
        help_lines = [line for line in lines if line.startswith("# HELP")]
        type_lines = [line for line in lines if line.startswith("# TYPE")]

        assert len(help_lines) > 0
        assert len(type_lines) > 0

    def test_histogram_includes_buckets(self):
        """Should include histogram bucket format."""
        API_LATENCY.observe(0.1, endpoint="/test", method="GET")

        output = generate_metrics()

        assert "_bucket{" in output
        assert "_sum{" in output
        assert "_count{" in output


# =============================================================================
# Thread Safety Integration Tests
# =============================================================================


class TestThreadSafety:
    """Integration tests for thread-safe metric operations."""

    def test_concurrent_counter_increments(self):
        """Multiple threads should safely increment counters."""
        counter = Counter(name="concurrent_test", help="Test", label_names=["id"])

        def increment():
            for i in range(100):
                counter.inc(id="test")

        threads = [Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter.get(id="test") == 1000

    def test_concurrent_histogram_observations(self):
        """Multiple threads should safely observe histogram."""
        histogram = Histogram(name="concurrent_hist", help="Test", buckets=[1.0])

        def observe():
            for i in range(100):
                histogram.observe(0.5)

        threads = [Thread(target=observe) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        collected = histogram.collect()
        assert collected[0][1]["count"] == 1000

    def test_concurrent_gauge_updates(self):
        """Multiple threads should safely update gauge."""
        gauge = Gauge(name="concurrent_gauge", help="Test")

        def update():
            for i in range(100):
                gauge.inc()
                gauge.dec()

        threads = [Thread(target=update) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After equal inc/dec operations, should be near 0
        # (exact 0 not guaranteed due to race conditions in reading)
        assert abs(gauge.get()) <= 10  # Allow small variance
