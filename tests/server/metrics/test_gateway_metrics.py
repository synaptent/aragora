"""Tests for gateway metrics module."""

import pytest

from aragora.observability.server_metrics.gateway import (
    GATEWAY_OPERATION_LATENCY,
    GATEWAY_EXTERNAL_CALLS,
    CREDENTIAL_CACHE_HITS,
    CREDENTIAL_CACHE_MISSES,
    HYBRID_VERIFICATION_TIME,
    track_gateway_operation,
    track_credential_cache,
    track_hybrid_verification,
)


class TestGatewayMetrics:
    """Tests for gateway metric instances."""

    def test_metrics_importable(self):
        """All gateway metrics are importable and non-None."""
        assert GATEWAY_OPERATION_LATENCY is not None
        assert GATEWAY_EXTERNAL_CALLS is not None
        assert CREDENTIAL_CACHE_HITS is not None
        assert CREDENTIAL_CACHE_MISSES is not None
        assert HYBRID_VERIFICATION_TIME is not None

    def test_operation_latency_is_histogram(self):
        """GATEWAY_OPERATION_LATENCY is a Histogram with correct labels."""
        from aragora.observability.server_metrics.types import Histogram

        assert isinstance(GATEWAY_OPERATION_LATENCY, Histogram)
        assert "operation" in GATEWAY_OPERATION_LATENCY.label_names
        assert "agent_type" in GATEWAY_OPERATION_LATENCY.label_names
        assert "status" in GATEWAY_OPERATION_LATENCY.label_names

    def test_external_calls_is_counter(self):
        """GATEWAY_EXTERNAL_CALLS is a Counter with correct labels."""
        from aragora.observability.server_metrics.types import Counter

        assert isinstance(GATEWAY_EXTERNAL_CALLS, Counter)
        assert "agent_type" in GATEWAY_EXTERNAL_CALLS.label_names
        assert "operation" in GATEWAY_EXTERNAL_CALLS.label_names
        assert "status" in GATEWAY_EXTERNAL_CALLS.label_names

    def test_credential_cache_hits_is_counter(self):
        """CREDENTIAL_CACHE_HITS is a Counter."""
        from aragora.observability.server_metrics.types import Counter

        assert isinstance(CREDENTIAL_CACHE_HITS, Counter)

    def test_credential_cache_misses_is_counter(self):
        """CREDENTIAL_CACHE_MISSES is a Counter."""
        from aragora.observability.server_metrics.types import Counter

        assert isinstance(CREDENTIAL_CACHE_MISSES, Counter)

    def test_hybrid_verification_time_is_histogram(self):
        """HYBRID_VERIFICATION_TIME is a Histogram with phase label."""
        from aragora.observability.server_metrics.types import Histogram

        assert isinstance(HYBRID_VERIFICATION_TIME, Histogram)
        assert "phase" in HYBRID_VERIFICATION_TIME.label_names


class TestTrackGatewayOperation:
    """Tests for track_gateway_operation context manager."""

    def test_track_gateway_operation_success(self):
        """Successful operation records success status."""
        with track_gateway_operation("generate", "openclaw"):
            pass  # Should not raise

    def test_track_gateway_operation_error(self):
        """Failed operation records error status and re-raises."""
        with pytest.raises(ValueError):
            with track_gateway_operation("generate", "openclaw"):
                raise ValueError("test error")

    def test_track_gateway_operation_increments_counter(self):
        """Operation increments the external calls counter."""
        initial = GATEWAY_EXTERNAL_CALLS.get(
            agent_type="test_agent_inc", operation="test_op", status="success"
        )

        with track_gateway_operation("test_op", "test_agent_inc"):
            pass

        after = GATEWAY_EXTERNAL_CALLS.get(
            agent_type="test_agent_inc", operation="test_op", status="success"
        )
        assert after == initial + 1

    def test_track_gateway_operation_records_latency(self):
        """Operation records latency in histogram."""
        import time

        with track_gateway_operation("latency_test", "test_agent_lat"):
            time.sleep(0.01)

        # Verify the histogram has data by checking totals
        collected = GATEWAY_OPERATION_LATENCY.collect()
        assert len(collected) > 0

    def test_track_gateway_operation_default_agent_type(self):
        """Default agent_type is 'unknown'."""
        with track_gateway_operation("test_default"):
            pass

        val = GATEWAY_EXTERNAL_CALLS.get(
            agent_type="unknown", operation="test_default", status="success"
        )
        assert val >= 1


class TestTrackCredentialCache:
    """Tests for track_credential_cache helper."""

    def test_track_credential_cache_hit(self):
        """Cache hit increments hit counter."""
        initial = CREDENTIAL_CACHE_HITS.get()
        track_credential_cache(hit=True)
        assert CREDENTIAL_CACHE_HITS.get() == initial + 1

    def test_track_credential_cache_miss(self):
        """Cache miss increments miss counter."""
        initial = CREDENTIAL_CACHE_MISSES.get()
        track_credential_cache(hit=False)
        assert CREDENTIAL_CACHE_MISSES.get() == initial + 1


class TestTrackHybridVerification:
    """Tests for track_hybrid_verification helper."""

    def test_track_hybrid_verification(self):
        """Tracks verification phase duration."""
        track_hybrid_verification("proposal", 1.5)  # Should not raise

    def test_track_hybrid_verification_records_observation(self):
        """Verification tracking records data in histogram."""
        track_hybrid_verification("critique", 2.0)

        collected = HYBRID_VERIFICATION_TIME.collect()
        assert len(collected) > 0


class TestModuleExports:
    """Tests for module exports and re-exports."""

    def test_exports_from_gateway_module(self):
        """Gateway module exposes expected attributes."""
        from aragora.observability.server_metrics import gateway

        assert hasattr(gateway, "track_gateway_operation")
        assert hasattr(gateway, "track_credential_cache")
        assert hasattr(gateway, "track_hybrid_verification")
        assert hasattr(gateway, "GATEWAY_OPERATION_LATENCY")
        assert hasattr(gateway, "GATEWAY_EXTERNAL_CALLS")
        assert hasattr(gateway, "CREDENTIAL_CACHE_HITS")
        assert hasattr(gateway, "CREDENTIAL_CACHE_MISSES")
        assert hasattr(gateway, "HYBRID_VERIFICATION_TIME")

    def test_exports_from_metrics_package(self):
        """Gateway metrics are re-exported from the metrics package."""
        from aragora.observability.server_metrics import (
            GATEWAY_OPERATION_LATENCY as pkg_latency,
            GATEWAY_EXTERNAL_CALLS as pkg_calls,
            CREDENTIAL_CACHE_HITS as pkg_hits,
            CREDENTIAL_CACHE_MISSES as pkg_misses,
            HYBRID_VERIFICATION_TIME as pkg_verification,
            track_gateway_operation as pkg_track_op,
            track_credential_cache as pkg_track_cache,
            track_hybrid_verification as pkg_track_verify,
        )

        assert pkg_latency is GATEWAY_OPERATION_LATENCY
        assert pkg_calls is GATEWAY_EXTERNAL_CALLS
        assert pkg_hits is CREDENTIAL_CACHE_HITS
        assert pkg_misses is CREDENTIAL_CACHE_MISSES
        assert pkg_verification is HYBRID_VERIFICATION_TIME
        assert pkg_track_op is track_gateway_operation
        assert pkg_track_cache is track_credential_cache
        assert pkg_track_verify is track_hybrid_verification
