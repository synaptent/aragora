from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.core_types import DebateResult
from aragora.debate.orchestrator_runner import _auto_execute_plan
from aragora.debate.post_debate_coordinator import PostDebateConfig


def _make_result(**overrides: object) -> DebateResult:
    defaults = {
        "task": "Evaluate auto execution",
        "debate_id": "gate-e2e-001",
        "final_answer": "Proceed with staged rollout.",
        "confidence": 0.9,
        "consensus_reached": True,
        "metadata": {},
    }
    defaults.update(overrides)
    return DebateResult(**defaults)


def _make_arena(
    *,
    agents: list[SimpleNamespace],
    config_overrides: dict[str, object] | None = None,
) -> MagicMock:
    arena = MagicMock()
    arena.auto_execution_mode = "workflow"
    arena.auto_approval_mode = "risk_based"
    arena.auto_max_risk = "low"
    arena.agents = agents

    config = PostDebateConfig()
    for key, value in (config_overrides or {}).items():
        setattr(config, key, value)
    arena.post_debate_config = config
    return arena


async def _assert_blocked_reason(
    *,
    arena: MagicMock,
    result: DebateResult,
    expected_reason: str,
) -> None:
    updated = await _auto_execute_plan(arena, result)
    assert updated.metadata["auto_execution_blocked"] == "execution_gate"
    gate = updated.metadata["execution_gate"]
    assert expected_reason in gate["reason_codes"]


def _diverse_agents() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]


@pytest.mark.asyncio
async def test_e2e_reason_receipt_verification_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (None, False, False, False),
    )
    arena = _make_arena(agents=_diverse_agents())
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="receipt_verification_failed",
    )


@pytest.mark.asyncio
async def test_e2e_reason_receipt_signer_not_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_receipt = SimpleNamespace(
        receipt_id="r-allowlist",
        signature_key_id="hmac-unapproved",
        signed_at=datetime.now(timezone.utc).isoformat(),
        to_dict=lambda: {"receipt_id": "r-allowlist"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )
    arena = _make_arena(
        agents=_diverse_agents(),
        config_overrides={
            "execution_gate_enforce_receipt_signer_allowlist": True,
            "execution_gate_allowed_receipt_signer_keys": ("hmac-approved",),
        },
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="receipt_signer_not_allowlisted",
    )


@pytest.mark.asyncio
async def test_e2e_reason_receipt_missing_signed_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_receipt = SimpleNamespace(
        receipt_id="r-no-ts",
        signature_key_id="hmac-approved",
        signed_at="",
        to_dict=lambda: {"receipt_id": "r-no-ts"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )
    arena = _make_arena(agents=_diverse_agents())
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="receipt_missing_signed_timestamp",
    )


@pytest.mark.asyncio
async def test_e2e_reason_receipt_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_receipt = SimpleNamespace(
        receipt_id="r-stale",
        signature_key_id="hmac-approved",
        signed_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        to_dict=lambda: {"receipt_id": "r-stale"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )
    arena = _make_arena(
        agents=_diverse_agents(),
        config_overrides={"execution_gate_receipt_max_age_seconds": 300},
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="receipt_stale",
    )


@pytest.mark.asyncio
async def test_e2e_reason_receipt_timestamp_in_future(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_receipt = SimpleNamespace(
        receipt_id="r-future",
        signature_key_id="hmac-approved",
        signed_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        to_dict=lambda: {"receipt_id": "r-future"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )
    arena = _make_arena(
        agents=_diverse_agents(),
        config_overrides={"execution_gate_receipt_max_future_skew_seconds": 30},
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="receipt_timestamp_in_future",
    )


@pytest.mark.asyncio
async def test_e2e_reason_provider_diversity_below_minimum() -> None:
    arena = _make_arena(
        agents=[
            SimpleNamespace(name="gpt1", model="gpt-4.1", agent_type="openai-api"),
            SimpleNamespace(name="gpt2", model="o3-mini", agent_type="openai-api"),
        ],
        config_overrides={
            "execution_gate_min_provider_diversity": 2,
            "execution_gate_min_model_family_diversity": 1,
        },
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="provider_diversity_below_minimum",
    )


@pytest.mark.asyncio
async def test_e2e_reason_model_family_diversity_below_minimum() -> None:
    arena = _make_arena(
        agents=[
            SimpleNamespace(name="a", model="custom-model-a", agent_type="openai-api"),
            SimpleNamespace(name="b", model="custom-model-b", agent_type="anthropic-api"),
        ],
        config_overrides={
            "execution_gate_min_provider_diversity": 1,
            "execution_gate_min_model_family_diversity": 2,
        },
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="model_family_diversity_below_minimum",
    )


@pytest.mark.asyncio
async def test_e2e_reason_tainted_context_detected() -> None:
    arena = _make_arena(agents=_diverse_agents())
    result = _make_result(
        metadata={
            "context_taint_detected": True,
            "context_taint_patterns": ["ignore_previous_instructions"],
        }
    )
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="tainted_context_detected",
    )


@pytest.mark.asyncio
async def test_e2e_reason_high_severity_dissent_detected() -> None:
    arena = _make_arena(agents=_diverse_agents())
    result = _make_result()
    result.critiques = [SimpleNamespace(severity=0.95)]
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="high_severity_dissent_detected",
    )


@pytest.mark.asyncio
async def test_e2e_reason_correlated_failure_risk() -> None:
    arena = _make_arena(
        agents=[
            SimpleNamespace(name="gpt1", model="gpt-4.1", agent_type="openai-api"),
            SimpleNamespace(name="gpt2", model="gpt-4o", agent_type="openai-api"),
        ],
        config_overrides={
            "execution_gate_min_provider_diversity": 2,
            "execution_gate_min_model_family_diversity": 1,
        },
    )
    result = _make_result()
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="correlated_failure_risk",
    )


@pytest.mark.asyncio
async def test_e2e_reason_suspicious_unanimity_risk() -> None:
    arena = _make_arena(
        agents=[
            SimpleNamespace(name="gpt1", model="gpt-4.1", agent_type="openai-api"),
            SimpleNamespace(name="gpt2", model="o3-mini", agent_type="openai-api"),
        ],
        config_overrides={
            "execution_gate_min_provider_diversity": 1,
            "execution_gate_min_model_family_diversity": 1,
        },
    )
    result = _make_result(confidence=0.97, consensus_reached=True)
    await _assert_blocked_reason(
        arena=arena,
        result=result,
        expected_reason="suspicious_unanimity_risk",
    )
