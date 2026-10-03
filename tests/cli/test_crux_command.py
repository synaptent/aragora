"""Tests for the `aragora crux` CLI verb (Crux A3 / #6039)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aragora.cli.commands import crux as crux_cmd
from aragora.cli.parser import build_parser
from aragora.debate.crux_mode import CRUX_FINDER_ENV_VAR


@pytest.fixture(autouse=True)
def _enable_crux_finder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep existing live-path tests on the explicitly enabled path."""
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, "1")


def _fake_proof(*, debate_id: str = "debate-xyz") -> SimpleNamespace:
    """Minimal stand-in for an `aragora.debate.consensus.ConsensusProof`.

    Only the attributes the CLI reads are populated.
    """
    return SimpleNamespace(
        debate_id=debate_id,
        task="Should we ship?",
        final_claim="__CRUX_MAP__: no verdict by design; see CruxReceipt.cruxes",
        metadata={
            "consensus_mode": "crux_finder",
            "approach": "A",
            "cruxes": [
                {
                    "claim_id": "c1",
                    "statement": "Is the core assumption sound?",
                    "author": "agent-alpha",
                    "crux_score": 0.82,
                    "influence_score": 0.7,
                    "disagreement_score": 0.6,
                    "uncertainty_score": 0.5,
                    "centrality_score": 0.8,
                    "affected_claims": ["c2"],
                    "contesting_agents": ["agent-alpha", "agent-beta"],
                    "resolution_impact": 0.4,
                }
            ],
            "counterfactuals": [
                {
                    "claim_id": "c1",
                    "condition": "Resolve c1 to high confidence",
                    "outcome_change": "Reduces total network uncertainty by 0.400",
                    "likelihood": 0.5,
                    "affected_claims": ["c2"],
                }
            ],
            "recommended_focus": ["c1"],
            "convergence_barrier": 0.62,
            "crux_count": 1,
        },
    )


def _fake_debate_result(*, debate_id: str = "debate-xyz") -> SimpleNamespace:
    return SimpleNamespace(
        debate_id=debate_id,
        consensus_proof=_fake_proof(debate_id=debate_id),
        proposals={"agent-alpha": "proposal-alpha", "agent-beta": "proposal-beta"},
    )


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def test_crux_parser_registered_and_dispatches_to_cmd_crux() -> None:
    parser = build_parser()
    args = parser.parse_args(["crux", "Should we ship?", "--rounds", "2", "--top-k", "3"])
    assert args.command == "crux"
    assert args.question == "Should we ship?"
    assert args.rounds == 2
    assert args.top_k == 3
    # Lazy loader resolves to cmd_crux.
    assert callable(args.func)


def test_crux_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["crux", "Q"])
    assert args.rounds == 3
    assert args.top_k == 5
    assert args.min_score == pytest.approx(0.3)
    assert args.format == "markdown"
    assert args.no_counterfactuals is False
    assert args.dry_run is False


# ---------------------------------------------------------------------------
# Dry-run fast path — no debate executed
# ---------------------------------------------------------------------------


def test_cmd_crux_dry_run_does_not_invoke_debate(capsys) -> None:
    args = argparse.Namespace(
        question="Should we ship?",
        agents=None,
        rounds=3,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=True,
    )

    with patch.object(crux_cmd, "_run_crux_debate") as mock_run:
        crux_cmd.cmd_crux(args)

    mock_run.assert_not_called()
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert "crux-finder" in captured.out


def test_cmd_crux_empty_question_exits() -> None:
    args = argparse.Namespace(
        question="   ",
        agents=None,
        rounds=3,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )
    with pytest.raises(SystemExit) as exc_info:
        crux_cmd.cmd_crux(args)
    assert exc_info.value.code == 1


def test_cmd_crux_disabled_fails_before_debate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, "0")
    args = argparse.Namespace(
        question="Should we ship?",
        agents=None,
        rounds=3,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )

    with patch.object(crux_cmd, "_run_crux_debate") as mock_run:
        with pytest.raises(SystemExit) as exc_info:
            crux_cmd.cmd_crux(args)

    assert exc_info.value.code == 1
    mock_run.assert_not_called()
    assert CRUX_FINDER_ENV_VAR in capsys.readouterr().err


# ---------------------------------------------------------------------------
# End-to-end with a mocked debate
# ---------------------------------------------------------------------------


def test_cmd_crux_full_path_prints_markdown(capsys) -> None:
    args = argparse.Namespace(
        question="Should we ship?",
        agents="alpha,beta",
        rounds=2,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        return _fake_debate_result()

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        crux_cmd.cmd_crux(args)

    captured = capsys.readouterr()
    # Markdown headline is the crux map, not a decision.
    assert captured.out.startswith("# Crux Map — Should we ship?")
    assert "Is the core assumption sound?" in captured.out
    # Receipt id + checksum emitted for audit trail.
    assert "crux-" in captured.out


def test_cmd_crux_writes_receipt_and_output_files(tmp_path: Path, capsys) -> None:
    receipt_path = tmp_path / "crux.json"
    output_path = tmp_path / "crux.md"
    args = argparse.Namespace(
        question="Should we ship?",
        agents="alpha,beta",
        rounds=2,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=str(receipt_path),
        output=str(output_path),
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        return _fake_debate_result()

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        crux_cmd.cmd_crux(args)

    # Receipt file: JSON with stable fields.
    payload = json.loads(receipt_path.read_text())
    assert payload["question"] == "Should we ship?"
    assert payload["checksum"]
    assert len(payload["checksum"]) == 16
    assert payload["cruxes"], "cruxes should round-trip via the receipt file"

    # Rendered output file matches stdout.
    rendered = output_path.read_text()
    assert rendered.startswith("# Crux Map — Should we ship?")

    err = capsys.readouterr().err
    assert "Receipt saved to" in err
    assert "Rendered output saved to" in err


def test_cmd_crux_json_output_serializes_receipt(capsys) -> None:
    args = argparse.Namespace(
        question="Q",
        agents="a,b",
        rounds=1,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="json",
        receipt=None,
        output=None,
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        return _fake_debate_result()

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        crux_cmd.cmd_crux(args)

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["question"] == "Q"
    assert payload["cruxes"][0]["claim_id"] == "c1"
    assert payload["checksum"] and len(payload["checksum"]) == 16


def test_cmd_crux_rejects_result_without_crux_proof(capsys) -> None:
    args = argparse.Namespace(
        question="Q",
        agents="a",
        rounds=1,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        # No consensus_proof at all — simulates a mode fall-back or early failure.
        return SimpleNamespace(consensus_proof=None, proposals={})

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        with pytest.raises(SystemExit) as exc_info:
            crux_cmd.cmd_crux(args)
    assert exc_info.value.code == 1
    assert "could not build receipt" in capsys.readouterr().err


def test_cmd_crux_rejects_non_crux_proof(capsys) -> None:
    """Rejects a ConsensusProof that wasn't produced by crux-finder mode."""
    wrong_proof = SimpleNamespace(
        debate_id="d",
        task="q",
        final_claim="some verdict",
        metadata={"consensus_mode": "majority"},
    )
    args = argparse.Namespace(
        question="Q",
        agents="a",
        rounds=1,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        return SimpleNamespace(consensus_proof=wrong_proof, proposals={})

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        with pytest.raises(SystemExit) as exc_info:
            crux_cmd.cmd_crux(args)
    assert exc_info.value.code == 1
    assert "crux-finder" in capsys.readouterr().err


def test_run_crux_debate_imports_resolve_without_error() -> None:
    """Regression: the inner imports must resolve without raising.

    The CLI used to import a non-existent ``get_default_agents`` from
    ``aragora.agents`` (Phase F dogfood finding, Round 2026-04-30c). The
    existing test bank patches ``_run_crux_debate`` directly so it never
    executed the inner import path, allowing the break to live undetected.

    This test exercises the import path by invoking the function with all
    its collaborators stubbed; if the import fails the test fails with
    ImportError before any stub is reached.
    """
    import asyncio

    mock_arena = MagicMock()

    async def _fake_arena_run() -> SimpleNamespace:
        return SimpleNamespace(consensus_proof=None, proposals={})

    mock_arena.run = _fake_arena_run

    with (
        patch("aragora.Arena", return_value=mock_arena),
        patch("aragora.Environment", return_value=MagicMock()),
        patch("aragora.agents.get_agents_by_names", return_value=[]),
    ):
        # Smoke-test only: passes as long as no ImportError is raised.
        result = asyncio.run(
            crux_cmd._run_crux_debate(
                "Sample question?",
                agents=["demo"],
                rounds=1,
                top_k=3,
                min_score=0.3,
                counterfactual_validation=False,
            )
        )
    assert result is not None  # the mock returns a SimpleNamespace


# ---------------------------------------------------------------------------
# Round 2026-04-30d Phase E: improved diagnostic when consensus_proof is None
# Found via Phase C dogfood — `aragora crux --agents demo` produced a confusing
# "no consensus_proof" error after running the entire debate. The actual cause
# (crux-finder fell back to majority because no belief network) was buried in
# WARNING logs.
# ---------------------------------------------------------------------------


def test_diagnose_missing_proof_no_metadata() -> None:
    """When result has no metadata, fall back to the original generic error."""
    result = SimpleNamespace(consensus_proof=None)
    msg = crux_cmd._diagnose_missing_proof(result)
    assert "no consensus_proof" in msg
    assert "Inspect debate logs" in msg


def test_diagnose_missing_proof_no_belief_network_with_remedy() -> None:
    """``no_belief_network`` skip surfaces the agent-config remedy."""
    result = SimpleNamespace(
        consensus_proof=None,
        metadata={
            "crux_finder_skipped_reason": "no_belief_network",
            "crux_finder_fallback_consensus": "majority",
        },
    )
    msg = crux_cmd._diagnose_missing_proof(result)
    assert "no_belief_network" in msg
    assert "fell_back_to=majority" in msg
    # Remedy mentions the actionable fix path.
    assert "real LLM agents" in msg
    assert "--agents claude,codex" in msg
    assert "ANTHROPIC_API_KEY" in msg


def test_diagnose_missing_proof_other_skip_reason_no_remedy() -> None:
    """Skip reasons other than ``no_belief_network`` get a generic hint, no remedy."""
    result = SimpleNamespace(
        consensus_proof=None,
        metadata={
            "crux_finder_skipped_reason": "some_other_reason",
            "crux_finder_fallback_consensus": "majority",
        },
    )
    msg = crux_cmd._diagnose_missing_proof(result)
    assert "reason=some_other_reason" in msg
    assert "fell_back_to=majority" in msg
    assert "real LLM agents" not in msg  # remedy is no_belief_network-specific


def test_diagnose_missing_proof_only_fallback_no_reason() -> None:
    """When fallback is set but reason isn't, both surface but no remedy fires."""
    result = SimpleNamespace(
        consensus_proof=None,
        metadata={"crux_finder_fallback_consensus": "majority"},
    )
    msg = crux_cmd._diagnose_missing_proof(result)
    assert "fell_back_to=majority" in msg
    # No reason string, so no specific remedy.


def test_diagnose_missing_proof_handles_non_dict_metadata() -> None:
    """Defensive: metadata that isn't a dict (e.g., None) doesn't crash."""
    result_none = SimpleNamespace(consensus_proof=None, metadata=None)
    result_str = SimpleNamespace(consensus_proof=None, metadata="not a dict")
    for r in (result_none, result_str):
        msg = crux_cmd._diagnose_missing_proof(r)
        assert "no consensus_proof" in msg


def test_cmd_crux_no_belief_network_error_surfaces_remedy(capsys) -> None:
    """End-to-end: cmd_crux exits 1 with the remedy message when crux-finder is skipped."""
    args = argparse.Namespace(
        question="Q",
        agents="demo",
        rounds=1,
        top_k=5,
        min_score=0.3,
        no_counterfactuals=False,
        format="markdown",
        receipt=None,
        output=None,
        dry_run=False,
    )

    async def _fake_run(*_a, **_k):
        return SimpleNamespace(
            consensus_proof=None,
            proposals={},
            metadata={
                "crux_finder_skipped_reason": "no_belief_network",
                "crux_finder_fallback_consensus": "majority",
            },
        )

    with patch.object(crux_cmd, "_run_crux_debate", side_effect=_fake_run):
        with pytest.raises(SystemExit) as exc_info:
            crux_cmd.cmd_crux(args)
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "no_belief_network" in err
    assert "real LLM agents" in err  # operator-actionable remedy
