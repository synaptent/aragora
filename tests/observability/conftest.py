"""
Pytest configuration for observability tests.

Resets Prometheus collector registry and metrics module initialization
flags between tests to prevent cross-test pollution from duplicate
metric registration.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def reset_prometheus_metrics():
    """Reset Prometheus registry and metrics init flags after each test.

    Observability metrics modules use a lazy _initialized guard that
    registers Prometheus collectors on first use.  When multiple test
    files run in the same process, the module-level _initialized flag
    stays True but the REGISTRY may have been cleared by another
    fixture, causing 'Duplicated timeseries' errors on re-registration.

    This fixture unregisters all aragora_* collectors and resets every
    metrics module's _initialized flag after each test so subsequent
    tests re-register cleanly.
    """
    yield
    _cleanup()


def _cleanup() -> None:
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        return

    # Unregister aragora collectors
    collectors_to_remove = []
    for collector in list(REGISTRY._collector_to_names.keys()):
        names = REGISTRY._collector_to_names.get(collector, [])
        if any(name.startswith("aragora_") for name in names):
            collectors_to_remove.append(collector)

    for collector in collectors_to_remove:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    # Reset all metrics module _initialized flags
    _modules = [
        "aragora.observability.metrics",
        "aragora.observability.metrics.slo",
        "aragora.observability.metrics.km",
        "aragora.observability.metrics.bridge",
        "aragora.observability.metrics.request",
        "aragora.observability.metrics.custom",
        "aragora.observability.metrics.core",
        "aragora.observability.metrics.base",
        "aragora.observability.metrics.agent",
        "aragora.observability.metrics.agents",
        "aragora.observability.metrics.debate",
        "aragora.observability.metrics.debate_slo",
        "aragora.observability.metrics.evidence",
        "aragora.observability.metrics.ranking",
        "aragora.observability.metrics.consensus",
        "aragora.observability.metrics.fabric",
        "aragora.observability.metrics.cache",
        "aragora.observability.metrics.memory",
        "aragora.observability.metrics.system",
        "aragora.observability.metrics.platform",
        "aragora.observability.metrics.security",
        "aragora.observability.metrics.governance",
        "aragora.observability.metrics.workflow",
        "aragora.observability.metrics.marketplace",
        "aragora.observability.metrics.notification",
        "aragora.observability.metrics.gauntlet",
        "aragora.observability.metrics.convergence",
        "aragora.observability.metrics.control_plane",
        "aragora.observability.metrics.user_mapping",
        "aragora.observability.metrics.stores",
        "aragora.observability.metrics.task_queue",
        "aragora.observability.metrics.checkpoint",
        "aragora.observability.metrics.tts",
        "aragora.observability.metrics.explainability",
        "aragora.observability.decision_metrics",
    ]

    for mod_name in _modules:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_initialized"):
            mod._initialized = False
            if mod_name == "aragora.observability.metrics.slo":
                mod.SLO_CHECKS_TOTAL = None
                mod.SLO_VIOLATIONS_TOTAL = None
                mod.SLO_LATENCY_HISTOGRAM = None
                mod.SLO_VIOLATION_MARGIN = None

    try:
        from aragora.observability.server_metrics import ACTIVE_DEBATES

        ACTIVE_DEBATES.set(0)
    except ImportError:
        pass
