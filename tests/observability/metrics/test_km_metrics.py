"""Tests for observability/metrics/km.py — Knowledge Mound metrics."""

from unittest.mock import patch

import pytest

from aragora.observability.metrics import km as mod
from aragora.observability.metrics.km import (
    init_km_metrics,
    record_calibration_fusion,
    record_cp_capability_record,
    record_cp_cross_workspace_share,
    record_cp_recommendation_query,
    record_cp_task_outcome,
    record_cross_debate_reuse,
    record_forward_sync_latency,
    record_km_adapter_sync,
    record_km_cache_access,
    record_km_event_emitted,
    record_km_federated_query,
    record_km_operation,
    record_reverse_query_latency,
    record_semantic_search,
    record_validation_feedback,
    register_km_health_provider,
    set_km_active_adapters,
    set_km_health_status,
    sync_km_metrics_to_prometheus,
)


@pytest.fixture(autouse=True)
def _reset_module():
    mod._initialized = False
    register_km_health_provider(None)
    yield
    register_km_health_provider(None)
    mod._initialized = False


@pytest.fixture()
def _init_noop():
    with patch("aragora.observability.metrics.km.get_metrics_enabled", return_value=False):
        init_km_metrics()


class TestInitialization:
    def test_init_noop(self, _init_noop):
        assert mod._initialized is True
        assert mod.KM_OPERATIONS_TOTAL is not None

    def test_init_idempotent(self, _init_noop):
        first = mod.KM_OPERATIONS_TOTAL
        init_km_metrics()
        assert mod.KM_OPERATIONS_TOTAL is first


class TestCoreOperations:
    def test_record_operation_success(self, _init_noop):
        record_km_operation("query", success=True, latency_seconds=0.1)

    def test_record_operation_failure(self, _init_noop):
        record_km_operation("store", success=False, latency_seconds=0.5)

    def test_record_cache_hit(self, _init_noop):
        record_km_cache_access(hit=True, adapter="consensus")

    def test_record_cache_miss(self, _init_noop):
        record_km_cache_access(hit=False, adapter="global")

    def test_set_health_status(self, _init_noop):
        set_km_health_status(3)  # healthy

    def test_record_adapter_sync(self, _init_noop):
        record_km_adapter_sync("continuum", "forward", success=True)

    def test_record_federated_query(self, _init_noop):
        record_km_federated_query(5, success=True)

    def test_record_event_emitted(self, _init_noop):
        record_km_event_emitted("km_batch")

    def test_set_active_adapters(self, _init_noop):
        set_km_active_adapters(25)


class TestControlPlaneMetrics:
    def test_record_task_outcome(self, _init_noop):
        record_cp_task_outcome("debate", success=True)

    def test_record_capability_record(self, _init_noop):
        record_cp_capability_record("code_review")

    def test_record_cross_workspace_share(self, _init_noop):
        record_cp_cross_workspace_share("workspace-1")

    def test_record_recommendation_query(self, _init_noop):
        record_cp_recommendation_query("security_audit")


class TestBidirectionalFlowMetrics:
    def test_record_forward_sync_latency(self, _init_noop):
        record_forward_sync_latency("consensus", 0.025)

    def test_record_reverse_query_latency(self, _init_noop):
        record_reverse_query_latency("elo", 0.01)

    def test_record_semantic_search(self, _init_noop):
        record_semantic_search("evidence", success=True)
        record_semantic_search("evidence", success=False)

    def test_record_validation_feedback(self, _init_noop):
        record_validation_feedback("consensus", positive=True)
        record_validation_feedback("consensus", positive=False)

    def test_record_cross_debate_reuse(self, _init_noop):
        record_cross_debate_reuse("consensus")


class TestCalibrationFusionMetrics:
    def test_record_calibration_fusion_success(self, _init_noop):
        record_calibration_fusion(
            strategy="weighted_average",
            success=True,
            consensus_strength=0.85,
            agreement_ratio=0.9,
            outlier_count=0,
        )

    def test_record_calibration_fusion_with_outliers(self, _init_noop):
        record_calibration_fusion(
            strategy="median",
            success=True,
            consensus_strength=0.6,
            agreement_ratio=0.7,
            outlier_count=3,
        )

    def test_record_calibration_fusion_failure(self, _init_noop):
        record_calibration_fusion(
            strategy="weighted_average",
            success=False,
            consensus_strength=0.2,
            agreement_ratio=0.3,
            outlier_count=5,
        )


class TestSyncToPrometheus:
    def test_sync_handles_missing_provider(self, _init_noop):
        with patch("aragora.observability.metrics.km.set_km_health_status") as set_health:
            sync_km_metrics_to_prometheus()
        set_health.assert_not_called()

    def test_sync_handles_exception(self, _init_noop):
        register_km_health_provider(lambda: 3)
        with patch(
            "aragora.observability.metrics.km.set_km_health_status",
            side_effect=Exception("test"),
        ):
            # Should not raise
            sync_km_metrics_to_prometheus()

    def test_sync_uses_registered_health_provider(self, _init_noop):
        register_km_health_provider(lambda: 2)
        with patch("aragora.observability.metrics.km.set_km_health_status") as set_health:
            sync_km_metrics_to_prometheus()
        set_health.assert_called_once_with(2)
