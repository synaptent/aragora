"""Tests for ``scripts/run_baseline_panel.py``'s model pinning.

The single-family baseline panel is only a valid measurement if the JUDGE
comes from a different model family than the panel it scores. PR 3's trial
sweep collapsed this script's two retired pins onto one current id and
erased the distinction silently -- nothing referenced the script, so no test
failed. The 2026-09-04 wave-3 controller ruling requires both ids to come
from ``aragora.config.model_pins`` and to stay in different families; these
tests pin that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from aragora.config.model_pins import FABLE_51_DIRECT, GPT6_ASTRA_DIRECT
from aragora.models.catalog import spec_or_none

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_baseline_panel.py"


def _load(monkeypatch: pytest.MonkeyPatch, provider: str) -> Any:
    monkeypatch.setenv("BASELINE_PROVIDER", provider)
    spec = importlib.util.spec_from_file_location(f"baseline_panel_{provider}", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_panel_and_judge_are_different_families(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    module = _load(monkeypatch, provider)
    panel = spec_or_none(module.PANEL_MODEL)
    judge = spec_or_none(module.JUDGE_MODEL)
    assert panel is not None and judge is not None
    assert panel.family != judge.family, (
        f"BASELINE_PROVIDER={provider}: judge {module.JUDGE_MODEL} shares the "
        f"panel's family {panel.family}, so it cannot score the panel independently"
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_both_models_come_from_pins_and_are_active(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    module = _load(monkeypatch, provider)
    assert {module.PANEL_MODEL, module.JUDGE_MODEL} == {FABLE_51_DIRECT, GPT6_ASTRA_DIRECT}
    for model_id in (module.PANEL_MODEL, module.JUDGE_MODEL):
        spec = spec_or_none(model_id)
        assert spec is not None and not spec.retired, model_id


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_each_role_routes_to_its_own_catalog_provider(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """Panel and judge are different providers now, so one process-wide
    provider string can no longer route both calls."""
    module = _load(monkeypatch, provider)
    assert module.PANEL_PROVIDER == spec_or_none(module.PANEL_MODEL).provider
    assert module.JUDGE_PROVIDER == spec_or_none(module.JUDGE_MODEL).provider
    assert module.PANEL_PROVIDER != module.JUDGE_PROVIDER


def test_budget_estimate_comes_from_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rail used to read a four-row hand table keyed on retired ids."""
    module = _load(monkeypatch, "anthropic")
    spec = spec_or_none(FABLE_51_DIRECT)
    assert spec is not None
    expected = (1_000 / 1_000_000) * spec.input_per_mtok + (800 / 1_000_000) * spec.output_per_mtok
    assert module._estimate_usd(FABLE_51_DIRECT, 1_000, 800) == pytest.approx(expected)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_astra_request_kwargs_use_max_completion_tokens_and_no_sampling_params(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """GPT-6 Astra rejects sampling params and renames the output cap.

    The script used to send ``temperature`` on every call and ``max_tokens``
    on the OpenAI path, so with these pins every call was an HTTP 400
    (finding C-P2 on #9989).
    """
    module = _load(monkeypatch, provider)
    kwargs = module._request_kwargs(GPT6_ASTRA_DIRECT, temperature=0.6, max_tokens=800)
    assert kwargs["max_completion_tokens"] == 800
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs
    # The row documents reasoning_effort="high"; the OpenAI wire carries it.
    assert kwargs["reasoning_effort"] == spec_or_none(GPT6_ASTRA_DIRECT).reasoning_effort_default


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_fable_request_kwargs_send_no_temperature(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    module = _load(monkeypatch, provider)
    kwargs = module._request_kwargs(FABLE_51_DIRECT, temperature=1.0, max_tokens=400)
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    # The Anthropic Messages API names the cap max_tokens unconditionally.
    assert kwargs["max_tokens"] == 400
    assert "max_completion_tokens" not in kwargs
    # No top-level reasoning_effort on the Messages API wire.
    assert "reasoning_effort" not in kwargs


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_panel_request_kwargs_never_carry_a_rejected_param(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """Every panelist temperature, on both BASELINE_PROVIDER branches."""
    module = _load(monkeypatch, provider)
    for model in (module.PANEL_MODEL, module.JUDGE_MODEL):
        spec = spec_or_none(model)
        assert spec is not None
        for temp in module.PANELIST_TEMPERATURES:
            kwargs = module._request_kwargs(model, temperature=temp, max_tokens=800)
            if spec.supports_sampling_params:
                assert kwargs["temperature"] == temp
            else:
                assert "temperature" not in kwargs


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_run_header_records_ids_and_request_shape_flags(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    module = _load(monkeypatch, provider)
    header = module._run_header()
    assert header["panel"]["model"] == spec_or_none(module.PANEL_MODEL).canonical_id
    assert header["judge"]["model"] == spec_or_none(module.JUDGE_MODEL).canonical_id
    assert header["panel"]["supports_sampling_params"] is False
    # Both current pins reject sampling params, so the sweep is inert and the
    # header must say so rather than let the receipt imply 6 decoding conditions.
    assert header["temperature_sweep_effective"] is False
    assert header["panelist_temperatures"] == module.PANELIST_TEMPERATURES
