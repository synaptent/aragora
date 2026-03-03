"""Offline/demo golden-path behavior checks for CLI debate flows."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_debate_offline_is_network_free(monkeypatch):
    """Offline mode should not attempt audience networking and should disable network-backed subsystems."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.setenv("ARAGORA_OFFLINE", "1")

    with (
        patch.object(debate_cmd, "create_agent", return_value=MagicMock(name="demo-agent")),
        patch.object(debate_cmd, "Arena") as mock_arena,
        patch.object(
            debate_cmd,
            "get_event_emitter_if_available",
            side_effect=AssertionError("should not probe network in offline mode"),
        ),
        patch.object(debate_cmd, "CritiqueStore") as mock_store,
    ):
        mock_result = MagicMock()
        mock_arena.return_value.run = AsyncMock(return_value=mock_result)

        await debate_cmd.run_debate(
            task="test offline",
            agents_str="demo",
            rounds=1,
            learn=True,
            enable_audience=True,
        )

        mock_store.assert_not_called()
        _, kwargs = mock_arena.call_args
        assert kwargs["knowledge_mound"] is None
        assert kwargs["auto_create_knowledge_mound"] is False
        assert kwargs["enable_knowledge_retrieval"] is False
        assert kwargs["enable_knowledge_ingestion"] is False
        assert kwargs["enable_cross_debate_memory"] is False
        assert kwargs["use_rlm_limiter"] is False
        assert kwargs["enable_ml_delegation"] is False
        assert kwargs["enable_quality_gates"] is False
        assert kwargs["enable_consensus_estimation"] is False


def test_cmd_ask_demo_forces_local_offline(monkeypatch):
    """Demo mode should always execute locally with offline-safe settings."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="smoke demo",
        agents="claude,openai",
        rounds=5,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=True,
        api=False,
        local=False,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
    )

    with patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate:
        mock_result = MagicMock()
        mock_result.final_answer = "demo answer"
        mock_result.dissenting_views = []
        mock_run_debate.return_value = mock_result

        debate_cmd.cmd_ask(args)

        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["agents_str"] == "demo,demo,demo"
        assert call_kwargs["rounds"] == 2
        assert call_kwargs["learn"] is False
        assert call_kwargs["enable_audience"] is False
        assert call_kwargs["offline"] is True
        assert call_kwargs["protocol_overrides"]["enable_research"] is False
        assert call_kwargs["protocol_overrides"]["enable_llm_synthesis"] is False

    import os

    assert os.getenv("ARAGORA_OFFLINE") == "1"


def test_cmd_ask_strict_wall_clock_timeout_exits(monkeypatch, capsys):
    """Strict wall-clock timeout should terminate ask with a clear timeout message."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="strict timeout test",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
        api=False,
        local=True,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
        timeout=1,
    )

    @contextmanager
    def _always_timeout(_seconds: float):
        raise debate_cmd._StrictWallClockTimeout("forced strict timeout")
        yield

    with patch.object(debate_cmd, "_strict_wall_clock_timeout", _always_timeout):
        with pytest.raises(SystemExit) as exc_info:
            debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Debate timed out after 1s" in err
    assert "strict wall-clock" in err


def test_cmd_ask_quality_fail_closed_requires_contract(monkeypatch, capsys):
    """Fail-closed quality mode should require an explicit/derivable output contract."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="General planning question without explicit sections",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
        api=False,
        local=True,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
        timeout=30,
        post_consensus_quality=True,
        upgrade_to_good=True,
        quality_upgrade_max_loops=2,
        quality_min_score=9.0,
        quality_fail_closed=True,
        required_sections=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--quality-fail-closed requires an explicit output contract" in err


def test_cmd_ask_quality_fail_closed_invalid_output_contract_file(monkeypatch, capsys):
    """Invalid output contract file path should fail fast with clear configuration error."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="General planning task",
        agents="claude,openai",
        rounds=1,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
        api=False,
        local=True,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
        timeout=30,
        post_consensus_quality=True,
        upgrade_to_good=True,
        quality_upgrade_max_loops=2,
        quality_min_score=9.0,
        quality_fail_closed=True,
        required_sections=None,
        output_contract_file="/tmp/does_not_exist_contract.json",
    )

    with pytest.raises(SystemExit) as exc_info:
        debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "Failed to read output contract file" in err


def test_cmd_ask_quality_fail_closed_accepts_output_contract_file(monkeypatch, tmp_path):
    """A valid explicit output contract file should satisfy fail-closed preflight."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        """{
  "required_sections": [
    "Ranked High-Level Tasks",
    "Suggested Subtasks",
    "Owner module / file paths",
    "Test Plan",
    "Rollback Plan",
    "Gate Criteria",
    "JSON Payload"
  ]
}""",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        task="General planning task without explicit section hints",
        agents="anthropic-api,openai-api,gemini,grok",
        rounds=1,
        consensus="hybrid",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
        api=False,
        local=True,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
        timeout=30,
        post_consensus_quality=True,
        upgrade_to_good=True,
        quality_upgrade_max_loops=2,
        quality_min_score=9.0,
        quality_fail_closed=True,
        required_sections=None,
        output_contract_file=str(contract_path),
    )

    with patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate:
        mock_result = MagicMock()
        mock_result.final_answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents participating in multi-round consensus
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## Suggested Subtasks
- Create unit tests for settlement hook dispatch covering extract and settle lifecycle events
- Validate ERC-8004 Brier score calculation against known calibration datasets for accuracy

## Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py
- tests/debate/test_settlement_hooks.py

## Test Plan
- Run full settlement hook unit tests with both successful and failed settle paths for comprehensive coverage
- Execute integration smoke test covering debate creation through receipt persistence to validate end-to-end flow

## Rollback Plan
If settlement hook error rate exceeds 2% over a sustained 10 minute window, rollback by disabling the settlement feature flag in the control plane and redeploying the previous stable build from the artifact registry.

## Gate Criteria
- Settlement hook p95 latency <= 200ms measured over a 15 minute steady-state window
- Overall debate error rate < 0.5% over 15 minutes of production traffic with settlement enabled

## JSON Payload
```json
{"ranked_high_level_tasks": ["Settlement tracker ERC-8004 integration", "Data-feed verification"]}
```
"""
        mock_result.metadata = {}
        mock_result.dissenting_views = []
        mock_run_debate.return_value = mock_result
        debate_cmd.cmd_ask(args)
        assert mock_run_debate.called


def test_cmd_ask_upgrades_output_to_good(monkeypatch, capsys):
    """Post-consensus quality loop should repair a weak draft to a contract-compliant answer."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    weak_answer = """
## Ranked High-Level Tasks
- Task 1

## Gate Criteria
- Should be reliable.
"""
    upgraded_answer = """
## Ranked High-Level Tasks
- Implement settlement tracker integration with ERC-8004 reputation scoring for all debate agents participating in multi-round consensus
- Add automated data-feed verification for time-delayed claim resolution across consensus outcomes

## Suggested Subtasks
- Create unit tests for settlement hook dispatch covering extract and settle lifecycle events
- Validate ERC-8004 Brier score calculation against known calibration datasets for accuracy
- Add integration smoke test that runs a minimal debate and verifies receipt hash chain integrity

## Owner module / file paths
- aragora/debate/settlement_hooks.py
- aragora/debate/orchestrator.py
- tests/debate/test_settlement_hooks.py

## Test Plan
- Run full settlement hook unit tests with both successful and failed settle paths for comprehensive coverage
- Execute integration smoke test covering debate creation through receipt persistence to validate end-to-end flow
- Verify ERC-8004 reputation updates are idempotent and handle concurrent writes correctly under load

## Rollback Plan
If settlement hook error rate exceeds 2% over a sustained 10 minute window, rollback by disabling the settlement feature flag in the control plane and redeploying the previous stable build from the artifact registry.

## Gate Criteria
- Settlement hook p95 latency <= 200ms measured over a 15 minute steady-state window
- Overall debate error rate < 0.5% over 15 minutes of production traffic with settlement enabled

## JSON Payload
```json
{
  "ranked_high_level_tasks": ["Settlement tracker ERC-8004 integration", "Data-feed verification"],
  "suggested_subtasks": ["Settlement hook tests", "Brier score validation", "Receipt hash smoke test"],
  "owner_module_file_paths": ["aragora/debate/settlement_hooks.py"],
  "test_plan": ["Settlement unit tests", "Integration smoke", "ERC-8004 idempotency"],
  "rollback_plan": {"trigger": "settlement hook error > 2%", "action": "disable settlement flag"},
  "gate_criteria": [
    {"metric": "settlement_p95_latency", "op": "<=", "threshold": 200, "unit": "ms"},
    {"metric": "debate_error_rate", "op": "<", "threshold": 0.5, "unit": "%"}
  ]
}
```
"""

    args = argparse.Namespace(
        task=(
            "Smoke test: output sections Ranked High-Level Tasks, Suggested Subtasks, "
            "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
        ),
        agents="anthropic-api,openai-api,gemini,grok",
        rounds=1,
        consensus="hybrid",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
        api=False,
        local=True,
        graph=False,
        matrix=False,
        decision_integrity=False,
        auto_select=False,
        auto_select_config=None,
        enable_verticals=False,
        vertical=None,
        calibration=True,
        evidence_weighting=True,
        trending=True,
        mode=None,
        api_url="http://localhost:8080",
        api_key=None,
        verbose=False,
        graph_rounds=3,
        branch_threshold=0.7,
        max_branches=3,
        scenario=None,
        matrix_rounds=3,
        di_include_context=False,
        di_plan_strategy="single_task",
        di_execution_mode=None,
        timeout=300,
        post_consensus_quality=True,
        upgrade_to_good=True,
        quality_upgrade_max_loops=1,
        quality_min_score=9.0,
        quality_fail_closed=True,
    )

    result = DebateResult(task=args.task, final_answer=weak_answer, metadata={})
    repair_agent = MagicMock()
    repair_agent.generate = AsyncMock(return_value=upgraded_answer)

    @contextmanager
    def _no_timeout(_seconds: float):
        yield

    with (
        patch.object(debate_cmd, "_strict_wall_clock_timeout", _no_timeout),
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock, return_value=result),
        patch.object(debate_cmd, "create_agent", return_value=repair_agent),
    ):
        debate_cmd.cmd_ask(args)

    out = capsys.readouterr().out
    assert "## Suggested Subtasks" in out
    assert "[quality] verdict=good" in out
    assert "practicality=" in out
