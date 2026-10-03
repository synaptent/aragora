"""Tests for explicit higher-layer observability data providers."""

from __future__ import annotations

import builtins
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from aragora.observability import prometheus_recording
from aragora.observability.prometheus_recording import (
    register_v1_sunset_days_provider,
    update_v1_days_until_sunset,
)
from aragora.observability.server_metrics.export import (
    generate_metrics,
    register_nomic_metrics_provider,
)


@pytest.fixture(autouse=True)
def reset_layered_providers() -> Iterator[None]:
    """Keep process-global provider state isolated between focused tests."""
    register_nomic_metrics_provider(None)
    register_v1_sunset_days_provider(None)
    yield
    register_nomic_metrics_provider(None)
    register_v1_sunset_days_provider(None)


def _sample_value(exposition: str, prefix: str) -> float:
    """Return the first sample value for an exact Prometheus line prefix."""
    line = next(line for line in exposition.splitlines() if line.startswith(prefix))
    return float(line.rsplit(" ", 1)[1])


def test_registered_nomic_data_is_exported() -> None:
    """The Nomic composition adapter exposes the live metric objects."""
    from aragora.nomic import metrics as nomic_metrics

    before = nomic_metrics.NOMIC_PHASE_TRANSITIONS.get(
        from_phase="provider_test",
        to_phase="export",
    )
    nomic_metrics.NOMIC_PHASE_TRANSITIONS.inc(
        from_phase="provider_test",
        to_phase="export",
    )
    nomic_metrics.NOMIC_PHASE_DURATION.observe(2.5, phase="provider_test")

    assert nomic_metrics.register_prometheus_metrics_provider() is True

    exposition = generate_metrics()
    assert (
        _sample_value(
            exposition,
            'aragora_nomic_phase_transitions_total{from_phase="provider_test",to_phase="export"} ',
        )
        == before + 1
    )
    assert 'aragora_nomic_phase_duration_seconds_count{phase="provider_test"} 1' in exposition
    for name in (
        "aragora_nomic_phase_transitions_total",
        "aragora_nomic_cycles_total",
        "aragora_nomic_errors_total",
        "aragora_nomic_recovery_decisions_total",
        "aragora_nomic_retries_total",
        "aragora_nomic_current_phase",
        "aragora_nomic_cycles_in_progress",
        "aragora_nomic_phase_last_transition_timestamp",
        "aragora_nomic_circuit_breakers_open",
        "aragora_nomic_phase_duration_seconds",
    ):
        assert f"# HELP {name} " in exposition


def test_registered_versioning_data_updates_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered server callback supplies the current sunset value."""
    gauge = MagicMock()
    monkeypatch.setattr(prometheus_recording, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(prometheus_recording, "V1_API_DAYS_UNTIL_SUNSET", gauge, raising=False)
    register_v1_sunset_days_provider(lambda: 17)

    update_v1_days_until_sunset()

    gauge.set.assert_called_once_with(17)


def test_absent_providers_fail_soft_without_upward_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional data disappears cleanly without importing higher layers."""
    gauge = MagicMock()
    monkeypatch.setattr(prometheus_recording, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(prometheus_recording, "V1_API_DAYS_UNTIL_SUNSET", gauge, raising=False)

    original_import = builtins.__import__
    forbidden = {
        "aragora.nomic.metrics",
        "aragora.server.versioning.constants",
    }

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name in forbidden:
            raise AssertionError(f"unexpected upward import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    exposition = generate_metrics()
    update_v1_days_until_sunset()

    assert "# HELP aragora_nomic_phase_transitions_total " not in exposition
    gauge.set.assert_not_called()


def test_registered_provider_failures_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failures cannot break metrics export or sunset startup."""
    gauge = MagicMock()
    monkeypatch.setattr(prometheus_recording, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(prometheus_recording, "V1_API_DAYS_UNTIL_SUNSET", gauge, raising=False)

    def fail() -> object:
        raise RuntimeError("provider unavailable")

    register_nomic_metrics_provider(fail)
    register_v1_sunset_days_provider(fail)

    exposition = generate_metrics()
    update_v1_days_until_sunset()

    assert "# HELP aragora_api_requests_total " in exposition
    assert "# HELP aragora_nomic_phase_transitions_total " not in exposition
    gauge.set.assert_not_called()


def test_higher_layer_roots_register_both_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nomic and server composition roots explicitly wire their callbacks."""
    from aragora.nomic import metrics as nomic_metrics
    from aragora.server.middleware import deprecation_enforcer
    from aragora.server.versioning.constants import days_until_v1_sunset

    monkeypatch.setattr(deprecation_enforcer, "register_deprecated_endpoint", MagicMock())

    assert nomic_metrics.register_prometheus_metrics_provider() is True
    deprecation_enforcer.register_default_deprecations()

    nomic_exposition = generate_metrics()
    assert "# HELP aragora_nomic_phase_transitions_total " in nomic_exposition

    gauge = MagicMock()
    monkeypatch.setattr(prometheus_recording, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(prometheus_recording, "V1_API_DAYS_UNTIL_SUNSET", gauge, raising=False)
    update_v1_days_until_sunset()
    gauge.set.assert_called_once_with(days_until_v1_sunset())
