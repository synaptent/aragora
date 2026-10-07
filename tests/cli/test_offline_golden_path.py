"""Offline/demo golden-path behavior checks for CLI debate flows."""

from __future__ import annotations

import asyncio
import argparse
import gc
import inspect
import json
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _restore_aragora_offline_env():
    """cmd_ask demo mode sets ARAGORA_OFFLINE=1 in os.environ as a product side
    effect. monkeypatch.delenv of an absent var registers nothing to undo, so
    without this the leaked value poisons later tests on the same xdist worker
    (run_debate silently goes offline -> learn=False -> CritiqueStore skipped).
    """
    import os

    prev = os.environ.get("ARAGORA_OFFLINE")
    yield
    if prev is None:
        os.environ.pop("ARAGORA_OFFLINE", None)
    else:
        os.environ["ARAGORA_OFFLINE"] = prev


@pytest.fixture(autouse=True)
def _stub_cmd_ask_global_side_effects(request):
    """Keep cmd_ask tests hermetic unless a test explicitly exercises cleanup semantics."""
    from aragora.cli.commands import debate as debate_cmd

    async def _fake_shutdown() -> None:
        await asyncio.sleep(0)

    provider_report = SimpleNamespace(
        any_configured=True,
        configured_providers=("anthropic", "openai", "gemini", "xai", "openrouter"),
    )
    provider_readiness_patches = (
        patch(
            "aragora.config.provider_readiness.discover_provider_credentials",
            return_value=provider_report,
        ),
        patch(
            "aragora.config.provider_readiness.agent_type_has_configured_provider",
            return_value=True,
        ),
    )
    cleanup_sensitive_tests = {
        "test_cmd_ask_demo_forces_local_offline",
        # Demo quality finalization can leave selector sockets pending on
        # Python 3.11 unless the real cleanup coroutine runs on the same loop.
        "test_cmd_ask_demo_quality_pipeline_skips_provider_repairs",
        "test_cmd_ask_upgrades_output_to_good",
        "test_cmd_ask_cleans_shared_resources_on_debate_loop",
        "test_cmd_ask_compare_mode_reuses_single_loop_for_cleanup",
        "test_cmd_ask_no_context_init_rlm_sets_use_rlm_limiter_false",
        # CI on Python 3.11 surfaces loop/socket leaks in this path unless the
        # real cmd_ask cleanup coroutine runs on the active event loop.
        "test_cmd_ask_grounding_fail_closed_rejects_ungrounded_output",
        "test_cmd_ask_quality_fail_closed_accepts_output_contract_file",
        "test_cmd_ask_quality_retry_switches_models_after_timeout_and_low_quality",
    }

    receipt_patch = patch.object(debate_cmd, "_persist_debate_receipt", return_value=None)
    if request.node.name in cleanup_sensitive_tests:
        with ExitStack() as stack:
            for provider_patch in provider_readiness_patches:
                stack.enter_context(provider_patch)
            stack.enter_context(receipt_patch)
            yield
        return

    with ExitStack() as stack:
        for provider_patch in provider_readiness_patches:
            stack.enter_context(provider_patch)
        stack.enter_context(
            patch.object(
                debate_cmd,
                "_shutdown_cmd_ask_resources",
                new=AsyncMock(side_effect=_fake_shutdown),
            )
        )
        stack.enter_context(receipt_patch)
        yield


@pytest.fixture(autouse=True)
def _collect_garbage_between_tests():
    """Force deferred loop/socket finalizers to surface in the test that created them."""
    yield
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and not loop.is_closed():
        loop.close()
        asyncio.set_event_loop(None)
    gc.collect()
    gc.collect()


@pytest.mark.asyncio
async def test_run_debate_offline_is_network_free(monkeypatch):
    """Offline mode should not attempt audience networking and should disable network-backed subsystems."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.debate.orchestrator import Arena as RealArena

    monkeypatch.setenv("ARAGORA_OFFLINE", "1")
    real_arena_signature = inspect.signature(RealArena.__init__)

    with (
        patch.object(debate_cmd, "create_agent", return_value=MagicMock(name="demo-agent")),
        patch.object(debate_cmd, "Arena") as mock_arena,
        patch.object(
            debate_cmd,
            "get_event_emitter_if_available",
            side_effect=AssertionError("should not probe network in offline mode"),
        ),
        patch.object(debate_cmd, "CritiqueStore") as mock_store,
        patch("inspect.signature", return_value=real_arena_signature),
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
        assert kwargs["disable_post_debate_pipeline"] is True


def test_build_parser_parses_compare_against() -> None:
    """Ask parser should accept repeated comparison agent combinations."""
    from aragora.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "ask",
            "compare teams",
            "--agents",
            "anthropic-api,openai-api",
            "--compare-against",
            "openai-api,gemini",
            "--compare-against",
            "anthropic-api,gemini",
        ]
    )

    assert args.compare_against == ["openai-api,gemini", "anthropic-api,gemini"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_demo_forces_local_offline(monkeypatch):
    """Demo mode should always execute locally with offline-safe settings."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

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
        mock_result = DebateResult(task=args.task, final_answer="demo answer", metadata={})
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


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_crux_cards_flag_sets_protocol_override(monkeypatch):
    """--crux-cards should plumb enable_crux_cards into the debate protocol."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    monkeypatch.delenv("ARAGORA_API_URL", raising=False)

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
        crux_cards=True,
        mode=None,
        api_url=None,
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

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_trusted_server_available", return_value=False),
    ):
        mock_result = DebateResult(task=args.task, final_answer="demo answer", metadata={})
        mock_run_debate.return_value = mock_result

        debate_cmd.cmd_ask(args)

        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["protocol_overrides"]["enable_crux_cards"] is True


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_crux_cards_forces_local_over_auto_api(monkeypatch, tmp_path, capsys):
    """Plain --crux-cards (no explicit API config) must force local execution,
    print a Note (never a silent path), and never probe or auto-select a
    trusted API server."""
    from pathlib import Path

    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    monkeypatch.delenv("ARAGORA_API_URL", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    args = argparse.Namespace(
        task="smoke demo",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=False,
        db=":memory:",
        demo=False,
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
        crux_cards=True,
        post_consensus_quality=False,
        upgrade_to_good=False,
        quality_fail_closed=False,
        mode=None,
        api_url=None,
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

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_trusted_server_available") as mock_trusted,
        patch(
            "aragora.config.provider_readiness.agent_type_has_configured_provider",
            return_value=True,
        ),
    ):
        mock_result = DebateResult(task=args.task, final_answer="answer", metadata={})
        mock_run_debate.return_value = mock_result

        debate_cmd.cmd_ask(args)

        mock_trusted.assert_not_called()
        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["protocol_overrides"]["enable_crux_cards"] is True

    assert "Note: --crux-cards" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
@pytest.mark.parametrize(
    "local_mode",
    [
        pytest.param("local", id="local-flag-with-env-api-url"),
        pytest.param("demo", id="demo-flag-with-env-api-url"),
        pytest.param("offline", id="offline-env-with-env-api-url"),
    ],
)
def test_cmd_ask_crux_cards_allows_already_local_runs(monkeypatch, tmp_path, local_mode):
    """A merely-exported ARAGORA_API_URL must not reject runs that are already
    local (--local, --demo, ARAGORA_OFFLINE=1): they can never dispatch to an
    API server, so the explicit-API rejection does not apply."""
    from pathlib import Path

    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    monkeypatch.setenv("ARAGORA_API_URL", "http://localhost:8080")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if local_mode == "offline":
        monkeypatch.setenv("ARAGORA_OFFLINE", "1")

    args = argparse.Namespace(
        task="smoke demo",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=False,
        db=":memory:",
        demo=(local_mode == "demo"),
        api=False,
        local=(local_mode == "local"),
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
        crux_cards=True,
        post_consensus_quality=False,
        upgrade_to_good=False,
        quality_fail_closed=False,
        mode=None,
        api_url=None,
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

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_trusted_server_available", return_value=False),
        patch(
            "aragora.config.provider_readiness.agent_type_has_configured_provider",
            return_value=True,
        ),
    ):
        mock_result = DebateResult(task=args.task, final_answer="answer", metadata={})
        mock_run_debate.return_value = mock_result

        debate_cmd.cmd_ask(args)

        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["protocol_overrides"]["enable_crux_cards"] is True


@pytest.mark.parametrize(
    "explicit_config",
    [
        pytest.param({"api": True}, id="api-flag"),
        pytest.param({"api_url": "http://localhost:8080"}, id="api-url-flag"),
        pytest.param({"graph": True}, id="graph"),
        pytest.param({"matrix": True}, id="matrix"),
        pytest.param("env", id="aragora-api-url-env"),
    ],
)
def test_cmd_ask_crux_cards_rejects_explicit_api_config(monkeypatch, explicit_config):
    """--crux-cards is local-only: every explicit API configuration (--api,
    --api-url, ARAGORA_API_URL, --graph, --matrix) must fail closed (exit 2)
    before dispatch instead of silently dropping the promised cruxes block."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    monkeypatch.delenv("ARAGORA_API_URL", raising=False)
    if explicit_config == "env":
        monkeypatch.setenv("ARAGORA_API_URL", "http://localhost:8080")
        overrides = {}
    else:
        overrides = explicit_config

    args = argparse.Namespace(
        task="smoke demo",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=False,
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
        crux_cards=True,
        mode=None,
        api_url=None,
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
    for key, value in overrides.items():
        setattr(args, key, value)

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_trusted_server_available", return_value=False),
    ):
        with pytest.raises(SystemExit) as excinfo:
            debate_cmd.cmd_ask(args)

    assert excinfo.value.code == 2
    mock_run_debate.assert_not_called()


def test_cmd_ask_demo_quality_pipeline_skips_provider_repairs(monkeypatch):
    """Demo/offline asks should not invoke provider repair agents in quality loops."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task=(
            "Output sections: Ranked High-Level Tasks, Suggested Subtasks, "
            "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
        ),
        agents="claude,openai",
        rounds=2,
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
        timeout=30,
        post_consensus_quality=True,
        upgrade_to_good=True,
        quality_upgrade_max_loops=3,
        quality_concretize_max_rounds=2,
        quality_extra_assessment_rounds=2,
    )

    weak_answer = "## Ranked High-Level Tasks\n- One task only."
    result = DebateResult(task=args.task, final_answer=weak_answer, metadata={})

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock, return_value=result),
        patch.object(
            debate_cmd,
            "create_agent",
            side_effect=AssertionError(
                "create_agent should not run in demo/offline quality repair"
            ),
        ),
    ):
        debate_cmd.cmd_ask(args)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_cleans_shared_resources_on_debate_loop(monkeypatch):
    """CLI ask cleanup should run on the same loop that executed the debate."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    loop_ids: dict[str, int] = {}
    result = DebateResult(task="smoke demo", final_answer="loop-safe answer", metadata={})

    args = argparse.Namespace(
        task="smoke demo with cleanup",
        agents="claude,openai",
        rounds=2,
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
        compare_against=None,
        timeout=30,
        post_consensus_quality=False,
    )

    async def fake_run_debate(*_args, **_kwargs):
        loop_ids["run"] = id(asyncio.get_running_loop())
        return result

    original_shutdown = debate_cmd._shutdown_cmd_ask_resources

    async def fake_shutdown() -> None:
        loop_ids["shutdown"] = id(asyncio.get_running_loop())
        await original_shutdown()

    with (
        patch.object(debate_cmd, "run_debate", new=AsyncMock(side_effect=fake_run_debate)),
        patch.object(
            debate_cmd,
            "_shutdown_cmd_ask_resources",
            new=AsyncMock(side_effect=fake_shutdown),
        ),
        patch.object(debate_cmd, "_persist_debate_receipt", return_value=None),
    ):
        debate_cmd.cmd_ask(args)

    assert loop_ids["run"] == loop_ids["shutdown"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_compare_mode_picks_best_result(monkeypatch, capsys):
    """Compare mode should run each combination and keep the highest-scoring result."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.cli.parser import build_parser
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    parser = build_parser()
    args = parser.parse_args(
        [
            "ask",
            (
                "Smoke test: output sections Ranked High-Level Tasks, Suggested Subtasks, "
                "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
            ),
            "--local",
            "--rounds",
            "1",
            "--consensus",
            "judge",
            "--agents",
            "anthropic-api,openai-api",
            "--compare-against",
            "openai-api,gemini",
            "--compare-against",
            "anthropic-api,gemini",
            "--no-upgrade-to-good",
            "--quality-concretize-max-rounds",
            "0",
            "--quality-extra-assessment-rounds",
            "0",
        ]
    )
    args.db = ":memory:"

    weak_answer = """
## Ranked High-Level Tasks
- Task 1

## Gate Criteria
- Should be reliable.
"""
    strong_answer = """
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

    def _result_for_agents(agents_str: str) -> DebateResult:
        if agents_str == "openai-api,gemini":
            return DebateResult(
                task=args.task,
                debate_id="debate-best",
                final_answer=strong_answer,
                metadata={},
                confidence=0.84,
                consensus_reached=True,
                rounds_used=1,
            )
        return DebateResult(
            task=args.task,
            debate_id=f"debate-{agents_str.replace(',', '-')}",
            final_answer=weak_answer,
            metadata={},
            confidence=0.51,
            consensus_reached=False,
            rounds_used=1,
        )

    @contextmanager
    def _no_timeout(_seconds: float):
        yield

    async def _fake_run_debate(**kwargs):
        return _result_for_agents(kwargs["agents_str"])

    with (
        patch.object(debate_cmd, "_strict_wall_clock_timeout", _no_timeout),
        patch.object(
            debate_cmd, "run_debate", new_callable=AsyncMock, side_effect=_fake_run_debate
        ) as mock_run,
        patch.object(debate_cmd, "_persist_debate_receipt", return_value=None) as mock_receipt,
    ):
        debate_cmd.cmd_ask(args)

    out = capsys.readouterr().out
    assert [call.kwargs["agents_str"] for call in mock_run.await_args_list] == [
        "anthropic-api,openai-api",
        "openai-api,gemini",
        "anthropic-api,gemini",
    ]
    assert "MODEL COMPARISON" in out
    assert "[compare] selected agents=openai-api,gemini" in out
    assert "Settlement tracker ERC-8004 integration" in out

    selected_result = mock_receipt.call_args.args[0]
    assert selected_result.metadata["model_comparison"]["selected_agents"] == "openai-api,gemini"
    assert len(selected_result.metadata["model_comparison"]["candidates"]) == 3


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_compare_mode_reuses_single_loop_for_cleanup(monkeypatch):
    """Compare mode should keep all candidates and cleanup on one event loop."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.cli.parser import build_parser
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    parser = build_parser()
    args = parser.parse_args(
        [
            "ask",
            (
                "Smoke test: output sections Ranked High-Level Tasks, Suggested Subtasks, "
                "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
            ),
            "--local",
            "--rounds",
            "1",
            "--consensus",
            "judge",
            "--agents",
            "anthropic-api,openai-api",
            "--compare-against",
            "openai-api,gemini",
            "--compare-against",
            "anthropic-api,gemini",
            "--no-upgrade-to-good",
            "--quality-concretize-max-rounds",
            "0",
            "--quality-extra-assessment-rounds",
            "0",
        ]
    )
    args.db = ":memory:"

    answer = """
## Ranked High-Level Tasks
- Task 1

## Suggested Subtasks
- Subtask 1

## Owner module / file paths
- aragora/debate/orchestrator.py

## Test Plan
- Run the focused test.

## Rollback Plan
- Revert the change.

## Gate Criteria
- Keep the contract stable.

## JSON Payload
```json
{"ranked_high_level_tasks":["Task 1"]}
```
"""

    loop_ids: list[int] = []
    shutdown_loop_ids: list[int] = []

    @contextmanager
    def _no_timeout(_seconds: float):
        yield

    async def _fake_run_debate(**kwargs):
        loop_ids.append(id(asyncio.get_running_loop()))
        return DebateResult(
            task=args.task,
            debate_id=f"debate-{kwargs['agents_str'].replace(',', '-')}",
            final_answer=answer,
            metadata={},
            confidence=0.8,
            consensus_reached=True,
            rounds_used=1,
        )

    original_shutdown = debate_cmd._shutdown_cmd_ask_resources

    async def _fake_shutdown() -> None:
        shutdown_loop_ids.append(id(asyncio.get_running_loop()))
        await original_shutdown()

    with (
        patch.object(debate_cmd, "_strict_wall_clock_timeout", _no_timeout),
        patch.object(
            debate_cmd, "run_debate", new_callable=AsyncMock, side_effect=_fake_run_debate
        ),
        patch.object(
            debate_cmd,
            "_shutdown_cmd_ask_resources",
            new=AsyncMock(side_effect=_fake_shutdown),
        ) as mock_shutdown,
        patch.object(debate_cmd, "_persist_debate_receipt", return_value=None),
    ):
        debate_cmd.cmd_ask(args)

    assert len(loop_ids) == 3
    assert len(set(loop_ids)) == 1
    assert shutdown_loop_ids == [loop_ids[0]]
    assert mock_shutdown.await_count == 1


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

    with (
        patch.object(debate_cmd, "_strict_wall_clock_timeout", _always_timeout),
        patch.object(
            debate_cmd,
            "_cleanup_cli_subprocesses_for_timeout",
            return_value={"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0},
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    err = captured.err
    timeout_line = next(
        line for line in captured.out.splitlines() if line.startswith("ARAGORA_TIMEOUT_JSON=")
    )
    payload = json.loads(timeout_line.split("=", 1)[1])
    assert "Debate timed out after 1s" in err
    assert "strict wall-clock" in err
    assert payload["status"] == "timeout"
    assert payload["error_type"] == "strict_wall_clock_timeout"
    assert payload["timeout_seconds"] == 1
    assert payload["final_answer"] == ""


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_async_timeout_emits_machine_payload(monkeypatch, capsys):
    """Async wait_for timeout should emit machine-readable timeout JSON."""
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="async timeout test",
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

    async def _raise_async_timeout(**_kwargs):
        raise asyncio.TimeoutError()

    async def _fake_shutdown() -> None:
        await asyncio.sleep(0)

    with (
        patch.object(
            debate_cmd,
            "run_debate",
            new_callable=AsyncMock,
            side_effect=_raise_async_timeout,
        ),
        patch.object(
            debate_cmd,
            "_shutdown_cmd_ask_resources",
            new=AsyncMock(side_effect=_fake_shutdown),
        ),
        patch.object(
            debate_cmd,
            "_cleanup_cli_subprocesses_for_timeout",
            return_value={"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0},
        ),
    ):
        with pytest.raises(SystemExit) as exc_info:
            debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    err = captured.err
    timeout_line = next(
        line for line in captured.out.splitlines() if line.startswith("ARAGORA_TIMEOUT_JSON=")
    )
    payload = json.loads(timeout_line.split("=", 1)[1])
    assert "Debate timed out after 1s" in err
    assert "async wait_for" in err
    assert payload["status"] == "timeout"
    assert payload["error_type"] == "async_wait_for_timeout"
    assert payload["timeout_seconds"] == 1
    assert payload["final_answer"] == ""


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_no_context_init_rlm_sets_use_rlm_limiter_false(monkeypatch):
    """Explicit CLI flag should disable context-init RLM limiter in local debates."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "ask",
            "review timeout behavior",
            "--local",
            "--agents",
            "demo,demo",
            "--rounds",
            "1",
            "--no-context-init-rlm",
        ]
    )
    args.learn = False
    args.db = ":memory:"
    args.demo = False
    args.post_consensus_quality = False

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_persist_debate_receipt", return_value=None),
    ):
        mock_result = MagicMock()
        mock_result.final_answer = "ok"
        mock_result.dissenting_views = []
        mock_result.consensus = MagicMock(final_answer="ok")
        mock_run_debate.return_value = mock_result

        debate_cmd.cmd_ask(args)

        call_kwargs = mock_run_debate.call_args.kwargs
        assert call_kwargs["use_rlm_limiter"] is False


def test_cmd_ask_grounding_fail_closed_rejects_ungrounded_output(monkeypatch, capsys):
    """Grounding fail-closed should reject outputs without verifiable repo paths."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="Grounding gate test",
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
        post_consensus_quality=False,
        grounding_fail_closed=True,
        grounding_min_verified_paths=0.8,
    )

    result = DebateResult(
        task=args.task, final_answer="No concrete file paths are listed.", metadata={}
    )

    with patch.object(debate_cmd, "run_debate", new_callable=AsyncMock, return_value=result):
        with pytest.raises(SystemExit) as exc_info:
            debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 1
    assert "Debate failed grounding gate" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore:unclosed <socket.socket.*:ResourceWarning")
def test_cmd_ask_grounding_fail_closed_accepts_grounded_output(monkeypatch, capsys):
    """Grounding fail-closed should pass when existing repo path ratio meets threshold."""
    from aragora.cli.commands import debate as debate_cmd
    from aragora.core import DebateResult

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)

    args = argparse.Namespace(
        task="Grounding gate pass test",
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
        post_consensus_quality=False,
        grounding_fail_closed=True,
        grounding_min_verified_paths=0.5,
    )

    result = DebateResult(
        task=args.task,
        final_answer="Update aragora/cli/commands/debate.py and tests/cli/test_offline_golden_path.py.",
        metadata={},
    )

    with patch.object(debate_cmd, "run_debate", new_callable=AsyncMock, return_value=result):
        debate_cmd.cmd_ask(args)

    out = capsys.readouterr().out
    assert "[path-check] grounded=" in out


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
        timeout=1,
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


def test_cmd_ask_quality_fail_closed_conflicts_with_no_post_consensus_quality(
    monkeypatch, capsys, tmp_path
):
    """--quality-fail-closed must not be silently dropped when post-consensus
    quality is disabled.

    Regression: combining --quality-fail-closed with --no-post-consensus-quality
    used to bypass both the config-validation guard and the runtime gate, so the
    command exited 0 even when output violated the contract (a false CI green).
    The contradictory combination must now fail closed with a clear configuration
    error.
    """
    from aragora.cli.commands import debate as debate_cmd

    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        '{"required_sections": ["Decision", "Rollback Plan", "Success Metrics"]}',
        encoding="utf-8",
    )

    args = argparse.Namespace(
        task="Should we adopt a four day work week for the team",
        agents="claude,openai",
        rounds=2,
        consensus="judge",
        context="",
        learn=True,
        db=":memory:",
        demo=True,
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
        post_consensus_quality=False,
        upgrade_to_good=True,
        quality_upgrade_max_loops=2,
        quality_min_score=9.0,
        quality_fail_closed=True,
        required_sections=None,
        output_contract_file=str(contract_path),
    )

    with pytest.raises(SystemExit) as exc_info:
        debate_cmd.cmd_ask(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--quality-fail-closed cannot be" in err
    assert "--no-post-consensus-quality" in err


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

    with (
        patch.object(debate_cmd, "run_debate", new_callable=AsyncMock) as mock_run_debate,
        patch.object(debate_cmd, "_persist_debate_receipt", return_value=None),
    ):
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


def test_cmd_ask_quality_retry_switches_models_after_timeout_and_low_quality(monkeypatch, capsys):
    """Repair retries should promote a different model after timeout and low-quality outputs."""
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
        agents="anthropic-api|claude-opus-4-7,openai-api|gpt-5.4,gemini|gemini-3.1-pro-preview",
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
        quality_upgrade_max_loops=2,
        quality_min_score=9.0,
        quality_practical_min_score=5.0,
        quality_fail_closed=True,
        quality_concretize_max_rounds=0,
        quality_extra_assessment_rounds=0,
        required_sections=None,
        output_contract_file=None,
    )

    result = DebateResult(task=args.task, final_answer=weak_answer, metadata={})

    class _FakeRepairAgent:
        def __init__(self, behavior: str):
            self.behavior = behavior
            self.system_prompt = ""

        async def generate(self, _prompt: str) -> str:
            if self.behavior == "timeout":
                raise TimeoutError("request timed out")
            if self.behavior == "weak":
                return weak_answer
            return upgraded_answer

    timed_out_agent = _FakeRepairAgent("timeout")
    low_quality_agent = _FakeRepairAgent("weak")
    upgraded_agent = _FakeRepairAgent("good")
    created_specs: list[tuple[str, str | None]] = []

    def _fake_create_agent(*, model_type, name, role, model=None, **_kwargs):
        created_specs.append((model_type, model))
        key = (model_type, model)
        if key == ("gemini", "gemini-3.1-pro-preview"):
            return timed_out_agent
        if key == ("anthropic-api", "claude-opus-4-7"):
            return low_quality_agent
        if key == ("openai-api", "gpt-5.4"):
            return upgraded_agent
        raise AssertionError(f"Unexpected repair agent: {key}")

    @contextmanager
    def _no_timeout(_seconds: float):
        yield

    async def _fake_run_debate(**_kwargs):
        return result

    with (
        patch.object(debate_cmd, "_strict_wall_clock_timeout", _no_timeout),
        patch.object(debate_cmd, "run_debate", new=_fake_run_debate),
        patch.object(debate_cmd, "create_agent", side_effect=_fake_create_agent),
    ):
        debate_cmd.cmd_ask(args)

    out = capsys.readouterr().out
    assert created_specs[:3] == [
        ("gemini", "gemini-3.1-pro-preview"),
        ("anthropic-api", "claude-opus-4-7"),
        ("openai-api", "gpt-5.4"),
    ]
    assert "## Suggested Subtasks" in out
    assert "[quality] verdict=good" in out
