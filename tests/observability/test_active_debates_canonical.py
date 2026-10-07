"""Regression tests for the canonical active-debates metric state."""

from __future__ import annotations

import warnings

import pytest

import aragora.observability.metrics as public_metrics
from aragora.observability.alerting import MetricsCollector, MetricsSnapshot
from aragora.observability.metrics import debate as debate_metrics
from aragora.observability.server_metrics import (
    ACTIVE_DEBATES as CANONICAL_ACTIVE_DEBATES,
    generate_metrics,
    track_debate_execution,
)


@pytest.fixture(autouse=True)
def reset_active_debates() -> None:
    """Keep the process-global gauge isolated between focused tests."""
    CANONICAL_ACTIVE_DEBATES.set(0)
    yield
    CANONICAL_ACTIVE_DEBATES.set(0)


def _exported_active_debate_values() -> list[float]:
    exposition = generate_metrics()
    assert exposition.endswith("\n")
    return [
        float(line.split()[-1])
        for line in exposition.splitlines()
        if line.startswith("aragora_active_debates ")
    ]


@pytest.mark.asyncio
async def test_lifecycle_alerting_and_export_share_canonical_state() -> None:
    """Lifecycle, alert collection, and public exports observe one count."""
    debate_metrics.init_debate_metrics()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from aragora.observability.server_metrics import ACTIVE_DEBATES as legacy_active_debates

    assert debate_metrics.ACTIVE_DEBATES is CANONICAL_ACTIVE_DEBATES
    assert public_metrics.ACTIVE_DEBATES is CANONICAL_ACTIVE_DEBATES
    assert legacy_active_debates is CANONICAL_ACTIVE_DEBATES

    collector = MetricsCollector()
    before = MetricsSnapshot()
    await collector._collect_debate_metrics(before)
    assert before.active_debates == 0
    assert _exported_active_debate_values() == [0.0]

    with track_debate_execution():
        assert CANONICAL_ACTIVE_DEBATES.get() == 1
        assert public_metrics.ACTIVE_DEBATES.get() == 1

        active = MetricsSnapshot()
        await collector._collect_debate_metrics(active)
        assert active.active_debates == 1
        assert _exported_active_debate_values() == [1.0]

    after = MetricsSnapshot()
    await collector._collect_debate_metrics(after)
    assert after.active_debates == 0
    assert _exported_active_debate_values() == [0.0]


def test_observability_initialization_registers_single_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initializing compatibility namespaces never duplicates the collector."""
    pytest.importorskip("prometheus_client")
    from prometheus_client import Gauge as PrometheusGauge
    from prometheus_client import REGISTRY, generate_latest

    monkeypatch.setattr(debate_metrics, "get_metrics_enabled", lambda: True)
    stale_collector = PrometheusGauge(
        "aragora_active_debates",
        "Stale active debate storage",
    )
    stale_collector.set(11)
    debate_metrics.init_debate_metrics()
    public_metrics._refresh_exports()
    debate_metrics.init_debate_metrics()

    active_collectors = {
        collector
        for name, collector in REGISTRY._names_to_collectors.items()
        if name == "aragora_active_debates"
    }
    assert len(active_collectors) == 1
    assert stale_collector not in active_collectors

    CANONICAL_ACTIVE_DEBATES.set(3)
    samples = [
        float(line.split()[-1])
        for line in generate_latest(REGISTRY).decode("utf-8").splitlines()
        if line.startswith("aragora_active_debates ")
    ]
    assert samples == [3.0]
