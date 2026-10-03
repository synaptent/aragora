"""
Tests for the CLI demo command.

Validates the demo command runs a self-contained adversarial debate
without requiring API keys, produces visible output, and supports
all flags (--list, --topic, --server).
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora_debate  # noqa: F401

from aragora.cli.commands.receipt import cmd_receipt_verify
from aragora.cli.demo import (
    DEMO_TASKS,
    _AGENT_CONFIGS,
    _DEFAULT_DEMO,
    _build_builtin_demo_result,
    _build_receipt_data,
    _print_banner,
    _print_result,
    _run_mock_demo,
    _save_demo_receipt,
    _wrap,
    list_demos,
    main,
    run_demo,
)


# ---------------------------------------------------------------------------
# DEMO_TASKS configuration
# ---------------------------------------------------------------------------


class TestDemoTasks:
    """Tests for DEMO_TASKS configuration."""

    def test_demo_tasks_not_empty(self):
        assert len(DEMO_TASKS) > 0

    def test_all_demos_have_required_fields(self):
        for name, demo in DEMO_TASKS.items():
            assert "topic" in demo, f"Demo '{name}' missing 'topic'"
            assert "description" in demo, f"Demo '{name}' missing 'description'"

    def test_all_demos_have_string_topics(self):
        for name, demo in DEMO_TASKS.items():
            assert isinstance(demo["topic"], str)
            assert len(demo["topic"]) > 10, f"Demo '{name}' topic too short"

    def test_default_demo_exists(self):
        assert _DEFAULT_DEMO in DEMO_TASKS

    def test_microservices_demo_exists(self):
        assert "microservices" in DEMO_TASKS

    def test_rate_limiter_demo_exists(self):
        assert "rate-limiter" in DEMO_TASKS

    def test_demo_names_are_lowercase(self):
        for name in DEMO_TASKS:
            assert name == name.lower(), f"Demo name '{name}' should be lowercase"
            assert " " not in name, f"Demo name '{name}' should not have spaces"


# ---------------------------------------------------------------------------
# list_demos
# ---------------------------------------------------------------------------


class TestListDemos:
    def test_returns_list(self):
        assert isinstance(list_demos(), list)

    def test_returns_all_demo_names(self):
        assert set(list_demos()) == set(DEMO_TASKS.keys())


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------


class TestAgentConfigs:
    def test_has_four_agents(self):
        assert len(_AGENT_CONFIGS) == 4

    def test_each_agent_has_name_and_style(self):
        for name, style in _AGENT_CONFIGS:
            assert isinstance(name, str)
            assert style in ("supportive", "critical", "balanced", "contrarian")

    def test_has_diverse_styles(self):
        styles = {s for _, s in _AGENT_CONFIGS}
        assert len(styles) >= 3, "Agents should have diverse styles"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestWrap:
    def test_short_text_single_line(self):
        assert _wrap("hello world", width=72) == ["hello world"]

    def test_long_text_wraps(self):
        text = "word " * 20
        lines = _wrap(text.strip(), width=30)
        assert len(lines) > 1
        assert all(len(line) <= 35 for line in lines)  # allow slight overflow for words

    def test_empty_string(self):
        assert _wrap("") == [""]


class TestPrintBanner:
    def test_prints_topic_and_agents(self, capsys):
        _print_banner("Test topic", ["Agent1", "Agent2"])
        captured = capsys.readouterr()
        assert "Test topic" in captured.out
        assert "Agent1" in captured.out
        assert "ARAGORA DEMO" in captured.out


class TestPrintResult:
    def test_prints_verdict_and_confidence(self, capsys):
        from aragora_debate.types import (
            DebateResult,
            DecisionReceipt,
            Verdict,
            Consensus,
            ConsensusMethod,
        )

        receipt = DecisionReceipt(
            receipt_id="DR-TEST-abc123",
            question="Test?",
            verdict=Verdict.APPROVED,
            confidence=0.85,
            consensus=Consensus(
                reached=True,
                method=ConsensusMethod.MAJORITY,
                confidence=0.85,
                supporting_agents=["a", "b"],
            ),
            agents=["a", "b"],
            rounds_used=2,
            signature="abc123def456",
            signature_algorithm="SHA-256-content-hash",
        )
        result = DebateResult(
            task="Test?",
            final_answer="We should proceed.",
            confidence=0.85,
            consensus_reached=True,
            verdict=Verdict.APPROVED,
            rounds_used=2,
            participants=["a", "b"],
            proposals={"a": "Proposal A text", "b": "Proposal B text"},
            receipt=receipt,
        )
        _print_result(result, 0.5)
        captured = capsys.readouterr()
        assert "Approved" in captured.out
        assert "85%" in captured.out
        assert "WINNING POSITION" in captured.out
        assert "DECISION RECEIPT" in captured.out
        assert "DR-TEST-abc123" in captured.out
        assert "SUGGESTED NEXT STEPS" in captured.out


# ---------------------------------------------------------------------------
# run_demo
# ---------------------------------------------------------------------------


class TestRunDemo:
    def test_unknown_demo_prints_error(self, capsys):
        result = run_demo("nonexistent_demo_xyz")
        assert result is None
        captured = capsys.readouterr()
        assert "Unknown demo" in captured.out

    def test_unknown_demo_shows_available(self, capsys):
        run_demo("nonexistent")
        captured = capsys.readouterr()
        for demo_name in DEMO_TASKS:
            if demo_name in captured.out:
                return
        pytest.fail("Available demos not shown")

    @patch("aragora.cli.demo._run_demo_debate")
    def test_valid_demo_runs(self, mock_run):
        from aragora_debate.types import DebateResult

        mock_result = DebateResult(task="test", confidence=0.8, consensus_reached=True)
        mock_run.return_value = (mock_result, 0.1)

        with patch("aragora.cli.demo.asyncio") as mock_asyncio:
            mock_asyncio.run.return_value = (mock_result, 0.1)
            result = run_demo("microservices")

        # The function was called (either via asyncio.run or directly)
        assert result is not None or mock_run.called or mock_asyncio.run.called


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_list_flag(self, capsys):
        args = argparse.Namespace(
            list_demos=True,
            server=False,
            topic=None,
            name=None,
        )
        main(args)
        captured = capsys.readouterr()
        assert "Available demos:" in captured.out
        assert "microservices" in captured.out

    @patch("aragora.cli.demo._run_server_demo")
    def test_server_flag(self, mock_server):
        args = argparse.Namespace(
            list_demos=False,
            server=True,
            topic=None,
            name=None,
        )
        main(args)
        mock_server.assert_called_once()

    @patch("aragora.cli.demo._run_mock_demo")
    @patch("aragora.cli.demo._has_any_api_key", return_value=False)
    def test_custom_topic(self, _mock_has_any_api_key, mock_run_mock_demo):
        args = argparse.Namespace(
            list_demos=False,
            server=False,
            topic="Should we use Rust?",
            name=None,
        )
        main(args)
        mock_run_mock_demo.assert_called_once_with(args)

    @patch("aragora.cli.demo._run_mock_demo")
    @patch("aragora.cli.demo._has_any_api_key", return_value=False)
    def test_named_demo(self, _mock_has_any_api_key, mock_run_mock_demo):
        args = argparse.Namespace(
            list_demos=False,
            server=False,
            topic=None,
            name="auth",
        )
        main(args)
        mock_run_mock_demo.assert_called_once_with(args)

    @patch("aragora.cli.demo._run_mock_demo")
    @patch("aragora.cli.demo._has_any_api_key", return_value=False)
    def test_defaults_to_microservices(self, _mock_has_any_api_key, mock_run_mock_demo):
        args = argparse.Namespace(
            list_demos=False,
            server=False,
            topic=None,
            name=None,
        )
        main(args)
        mock_run_mock_demo.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# Integration test: full demo runs end-to-end
# ---------------------------------------------------------------------------


class TestDemoIntegration:
    """Run the actual demo and verify it produces output."""

    def test_full_demo_runs_without_error(self, capsys):
        """The demo runs end-to-end with mock agents and produces output."""
        import asyncio
        from aragora.cli.demo import _run_demo_debate

        result, elapsed = asyncio.run(_run_demo_debate("Should we adopt microservices?"))

        assert result is not None
        assert result.consensus is not None
        assert result.rounds_used == 2
        assert result.receipt is not None
        assert elapsed < 5.0  # Should complete in under 5 seconds

        captured = capsys.readouterr()
        assert "ARAGORA DEMO" in captured.out
        assert "Mode:   Offline (mock agents, no API keys needed)" in captured.out
        assert "DECISION SUMMARY" in captured.out
        assert "WINNING POSITION" in captured.out
        assert "DECISION RECEIPT" in captured.out
        assert "package unavailable" not in captured.out

    def test_demo_has_proposals_and_votes(self):
        """The demo produces proposals, critiques, and votes."""
        import asyncio
        from aragora.cli.demo import _run_demo_debate

        result, _ = asyncio.run(_run_demo_debate("Design a cache system"))

        assert len(result.proposals) == 4  # 4 agents
        assert len(result.votes) > 0
        assert len(result.critiques) > 0
        assert len(result.messages) > 0

    def test_demo_produces_receipt(self):
        """The demo generates a decision receipt with integrity hash."""
        import asyncio
        from aragora.cli.demo import _run_demo_debate

        result, _ = asyncio.run(_run_demo_debate("Should we use Kubernetes?"))

        assert result.receipt is not None
        assert result.receipt.receipt_id.startswith("DR-")
        assert result.receipt.signature is not None
        assert result.receipt.signature_algorithm == "SHA-256-content-hash"

    def test_demo_receipt_payload_is_canonical_and_verifiable(self, tmp_path, capsys):
        """Saved demo receipts round-trip through the receipt verifier."""
        from aragora.gauntlet.receipt_models import DecisionReceipt

        result = _build_builtin_demo_result("Should we use Kubernetes?")
        receipt_data = _build_receipt_data(result, elapsed=0.25)

        assert receipt_data["question"] == "Should we use Kubernetes?"
        assert receipt_data["summary"]
        assert receipt_data["artifact_hash"]
        assert DecisionReceipt.from_dict(receipt_data).verify_integrity() is True

        receipt_path = tmp_path / "demo-receipt.json"
        _save_demo_receipt(result, 0.25, str(receipt_path))

        saved = json.loads(receipt_path.read_text())
        assert DecisionReceipt.from_dict(saved).verify_integrity() is True

        with pytest.raises(SystemExit) as exc:
            cmd_receipt_verify(argparse.Namespace(receipt=str(receipt_path), verbose=True))

        assert exc.value.code == 0
        assert "Result: VALID" in capsys.readouterr().out

    def test_demo_receipt_passes_top_level_verify(self, tmp_path, capsys):
        """Saved demo receipts must verify VALID under the top-level ``aragora verify``.

        Regression for the producer/consumer contract mismatch: ``_save_demo_receipt``
        emits ``artifact_hash`` (the canonical content hash) but no ``checksum`` key,
        while ``aragora verify`` previously treated a missing ``checksum`` as a hard
        failure. The documented onboarding next-step (``aragora verify <receipt>``)
        must report the demo receipt as valid. Drives the same code path the
        ``aragora demo --offline`` CLI uses (``_run_demo_debate``).
        """
        import asyncio

        from aragora.cli.commands.verify import _verify_receipt, cmd_verify
        from aragora.cli.demo import _run_demo_debate

        result, elapsed = asyncio.run(
            _run_demo_debate("Should we adopt microservices or keep our monolith?")
        )
        capsys.readouterr()  # drain demo output

        receipt_path = tmp_path / "aragora-demo-receipt.json"
        _save_demo_receipt(result, elapsed, str(receipt_path))

        saved = json.loads(receipt_path.read_text())
        # The producer emits artifact_hash, not a literal checksum key.
        assert saved.get("artifact_hash")
        assert "checksum" not in saved

        # Direct invariant: the verifier accepts the canonical artifact_hash.
        report = _verify_receipt(saved)
        checksum_check = next(c for c in report["checks"] if c["name"] == "integrity")
        assert checksum_check["passed"] is True, checksum_check["detail"]
        assert report["valid"] is True, report["checks"]

        # End-to-end: the CLI entry point returns exit code 0.
        args = argparse.Namespace(
            receipt_path=str(receipt_path), output_format="json", verbose=False
        )
        rc = cmd_verify(args)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["valid"] is True

    def test_demo_receipt_top_level_verify_detects_tampering(self, tmp_path, capsys):
        """Tampering a demo receipt's verdict must be caught by ``aragora verify``."""
        import asyncio

        from aragora.cli.commands.verify import _verify_receipt
        from aragora.cli.demo import _run_demo_debate

        result, elapsed = asyncio.run(
            _run_demo_debate("Should we adopt microservices or keep our monolith?")
        )
        capsys.readouterr()  # drain demo output

        receipt_path = tmp_path / "aragora-demo-receipt.json"
        _save_demo_receipt(result, elapsed, str(receipt_path))

        saved = json.loads(receipt_path.read_text())
        # Sanity: untampered receipt verifies.
        assert _verify_receipt(saved)["valid"] is True

        # Tamper the verdict without recomputing artifact_hash.
        saved["verdict"] = "rejected" if saved["verdict"] != "rejected" else "approved"
        report = _verify_receipt(saved)
        integrity_check = next(c for c in report["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert report["valid"] is False

    def test_demo_receipt_integrity_coverage_is_honest(self, tmp_path, capsys):
        """The integrity check must report an accurate ``covers`` scope.

        Codex P1: ``aragora verify`` must not overclaim. The artifact_hash only
        protects the decision-integrity fields, so the reported coverage must list
        exactly those fields and must NOT include presentational fields like
        ``timestamp`` or ``schema_version``. Conversely, tampering a covered field
        (confidence) must still FAIL.
        """
        import asyncio

        from aragora.cli.commands.verify import _INTEGRITY_HASH_FIELDS, _verify_receipt
        from aragora.cli.demo import _run_demo_debate

        result, elapsed = asyncio.run(
            _run_demo_debate("Should we adopt microservices or keep our monolith?")
        )
        capsys.readouterr()

        receipt_path = tmp_path / "aragora-demo-receipt.json"
        _save_demo_receipt(result, elapsed, str(receipt_path))
        saved = json.loads(receipt_path.read_text())

        report = _verify_receipt(saved)
        integrity_check = next(c for c in report["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is True

        # Coverage is explicit and accurate: exactly the decision-integrity fields.
        covers = set(integrity_check.get("covers", []))
        assert covers == set(_INTEGRITY_HASH_FIELDS)
        # Presentational fields are NOT claimed as integrity-protected.
        assert "timestamp" not in covers
        assert "schema_version" not in covers
        # But the fields the hash DOES cover are present in the claim.
        assert {"verdict", "confidence", "receipt_id"} <= covers

        # Tampering a covered decision field (confidence) must still FAIL.
        tampered = dict(saved)
        tampered["confidence"] = 0.0 if saved.get("confidence") != 0.0 else 1.0
        tampered_report = _verify_receipt(tampered)
        tampered_check = next(c for c in tampered_report["checks"] if c["name"] == "integrity")
        assert tampered_check["passed"] is False
        assert tampered_report["valid"] is False

    def test_demo_receipt_verify_result_wording_is_scoped(self, tmp_path, capsys):
        """An unsigned demo receipt's VALID result must not claim whole-payload safety."""
        import asyncio

        from aragora.cli.commands.verify import cmd_verify
        from aragora.cli.demo import _run_demo_debate

        result, elapsed = asyncio.run(
            _run_demo_debate("Should we adopt microservices or keep our monolith?")
        )
        capsys.readouterr()

        receipt_path = tmp_path / "aragora-demo-receipt.json"
        _save_demo_receipt(result, elapsed, str(receipt_path))

        args = argparse.Namespace(
            receipt_path=str(receipt_path), output_format="text", verbose=False
        )
        rc = cmd_verify(args)
        out = capsys.readouterr().out
        assert rc == 0
        # Result must be scoped to decision-integrity fields, not "not tampered with".
        assert "VALID -- decision-integrity fields verified" in out
        assert "not tamper-evidence" in out
        # Must not overclaim full-payload integrity on an unsigned receipt.
        assert "full-payload integrity verified" not in out


class TestOfflineMockFallback:
    def test_builtin_fallback_prints_standard_markers(self, capsys):
        args = argparse.Namespace(name="microservices", topic=None, receipt=None)

        with patch("aragora.cli.demo.HAS_ARAGORA_DEBATE", False):
            _run_mock_demo(args)

        captured = capsys.readouterr()
        assert "ARAGORA DEMO" in captured.out
        assert "DECISION SUMMARY" in captured.out
        assert "WINNING POSITION" in captured.out
        assert "DECISION RECEIPT" in captured.out


class TestReceiptSingleWrite:
    """A --receipt run writes exactly one receipt file and the banner names it.

    Regression for the dual-write bug: ``_run_demo_debate`` always wrote
    ``aragora-demo-receipt.json`` (and the banner pointed at it) while the
    user's ``--receipt`` path was written silently as a second file.
    """

    def test_builtin_fallback_receipt_flag_writes_only_requested_file(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(name="microservices", topic=None, receipt="r.json")

        with patch("aragora.cli.demo.HAS_ARAGORA_DEBATE", False):
            _run_mock_demo(args)

        assert (tmp_path / "r.json").exists()
        assert not (tmp_path / "aragora-demo-receipt.json").exists()
        captured = capsys.readouterr()
        assert "Full receipt saved to: ./r.json" in captured.out

    def test_custom_topic_receipt_flag_writes_only_requested_file(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(name=None, topic="Should we use Kubernetes?", receipt="r.json")

        _run_mock_demo(args)

        assert (tmp_path / "r.json").exists()
        assert not (tmp_path / "aragora-demo-receipt.json").exists()
        captured = capsys.readouterr()
        assert "Full receipt saved to: ./r.json" in captured.out

    def test_named_demo_receipt_flag_writes_only_requested_file(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(name="microservices", topic=None, receipt="r.json")

        _run_mock_demo(args)

        assert (tmp_path / "r.json").exists()
        assert not (tmp_path / "aragora-demo-receipt.json").exists()
        captured = capsys.readouterr()
        assert "Full receipt saved to: ./r.json" in captured.out

    def test_absolute_receipt_path_named_without_dot_slash_prefix(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        receipt_path = tmp_path / "sub" / "r.json"
        receipt_path.parent.mkdir()
        args = argparse.Namespace(name="microservices", topic=None, receipt=str(receipt_path))

        _run_mock_demo(args)

        assert receipt_path.exists()
        assert not (tmp_path / "aragora-demo-receipt.json").exists()
        captured = capsys.readouterr()
        assert f"Full receipt saved to: {receipt_path}" in captured.out
        assert f"./{receipt_path}" not in captured.out

    def test_no_receipt_flag_keeps_default_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(name="microservices", topic=None, receipt=None)

        _run_mock_demo(args)

        assert (tmp_path / "aragora-demo-receipt.json").exists()
        captured = capsys.readouterr()
        assert "Full receipt saved to: ./aragora-demo-receipt.json" in captured.out

    def test_requested_receipt_verifies(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(name="microservices", topic=None, receipt="r.json")

        _run_mock_demo(args)
        capsys.readouterr()  # drain demo output

        saved = json.loads((tmp_path / "r.json").read_text())
        assert saved.get("artifact_hash")
        with pytest.raises(SystemExit) as exc_info:
            cmd_receipt_verify(argparse.Namespace(receipt="r.json", verbose=False))
        assert exc_info.value.code == 0


class TestServerDemoHelper:
    def test_run_server_demo_uses_serve_demo_flag(self, capsys):
        from aragora.cli import demo as demo_module

        with patch("subprocess.run") as mock_run:
            demo_module._run_server_demo()

        mock_run.assert_called_once_with(
            [demo_module.sys.executable, "-m", "aragora.cli.main", "serve", "--demo"],
            check=False,
        )
        captured = capsys.readouterr()
        assert "ARAGORA SERVER DEMO" in captured.out
