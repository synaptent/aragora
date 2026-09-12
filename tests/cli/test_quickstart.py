"""Tests for the CLI quickstart command."""

from __future__ import annotations

import argparse
import asyncio
import builtins
import json
import os
import ssl
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.base import create_agent as create_real_agent
from aragora.cli.commands.receipt import cmd_receipt_verify
from aragora.cli.commands.quickstart import (
    _build_live_receipt,
    _build_quickstart_receipt_payload,
    _build_live_team,
    _can_reach_provider_tls,
    _configure_inline_api_key,
    _derive_receipt_id,
    _detect_agents,
    _filter_reachable_live_agents,
    _get_question,
    _load_dotenv,
    _normalize_provider,
    _open_receipt_in_browser,
    _resolve_rounds,
    _run_demo_debate,
    _run_live_debate,
    _run_quickstart_spec_first,
    _run_sync,
    _run_sync_without_runner,
    _save_receipt,
    add_quickstart_parser,
    cmd_quickstart,
)
from aragora.cli.parser import build_parser
from aragora.cli.receipt_formatter import receipt_to_html, receipt_to_markdown
from aragora.core import DebateResult
from aragora.core_types import DebateStatus, DebateStatusSource
from scripts.check_epistemic_hygiene import validate_receipt


# =============================================================================
# Parser registration
# =============================================================================


class TestQuickstartParser:
    def test_parser_registered(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "--demo"])
        assert hasattr(args, "func")
        assert args.demo is True

    def test_parser_question_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "-q", "Test question"])
        assert args.question == "Test question"

    def test_parser_topic_alias(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "--topic", "Topic question"])
        assert args.question == "Topic question"

    def test_parser_output_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "-o", "out.json"])
        assert args.output == "out.json"

    def test_parser_rounds_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "--rounds", "5"])
        assert args.rounds == 5

    def test_parser_inline_provider_key_flags(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(
            [
                "quickstart",
                "--provider",
                "openai",
                "--api-key",
                "sk-inline",
                "--save-key",
            ]
        )
        assert args.provider == "openai"
        assert args.api_key == "sk-inline"
        assert args.save_key is True

    def test_parser_format_choices(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        for fmt in ["json", "md", "html"]:
            args = parser.parse_args(["quickstart", "--format", fmt])
            assert args.format == fmt

    def test_parser_json_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "--json"])
        assert args.json is True

    def test_parser_spec_first_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_quickstart_parser(subparsers)
        args = parser.parse_args(["quickstart", "--spec-first"])
        assert args.spec_first is True

    def test_build_parser_registers_quickstart_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["quickstart", "--topic", "Topic question", "--json"])
        assert args.command == "quickstart"
        assert args.question == "Topic question"
        assert args.json is True


# =============================================================================
# Agent detection
# =============================================================================


class TestDetectAgents:
    def test_no_keys(self, monkeypatch):
        for key in [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "MISTRAL_API_KEY",
            "XAI_API_KEY",
            "GROK_API_KEY",
            "OPENROUTER_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)
        assert _detect_agents() == []

    def test_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        agents = _detect_agents()
        assert len(agents) == 1
        assert agents[0][0] == "anthropic-api"

    def test_multiple_keys(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test2")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        agents = _detect_agents()
        assert len(agents) == 2
        providers = [a[0] for a in agents]
        assert "anthropic-api" in providers
        assert "openai-api" in providers

    def test_preferred_provider_filters_detected_agents(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
        agents = _detect_agents("openai")
        assert agents == [("openai-api", "gpt-4o-mini")]

    def test_invalid_preferred_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            _detect_agents("bogus")


# =============================================================================
# .env loading
# =============================================================================


class TestLoadDotenv:
    def test_load_from_cwd(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_QUICKSTART_VAR=hello\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TEST_QUICKSTART_VAR", raising=False)
        result = _load_dotenv()
        assert result is True
        assert os.environ.get("TEST_QUICKSTART_VAR") == "hello"
        # Cleanup
        monkeypatch.delenv("TEST_QUICKSTART_VAR", raising=False)

    def test_no_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _load_dotenv()
        assert result is False

    def test_skips_comments_and_blanks(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nVALID_KEY=value\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VALID_KEY", raising=False)
        _load_dotenv()
        assert os.environ.get("VALID_KEY") == "value"
        monkeypatch.delenv("VALID_KEY", raising=False)


# =============================================================================
# Question getting
# =============================================================================


class TestGetQuestion:
    def test_from_args(self):
        args = argparse.Namespace(question="Test Q")
        assert _get_question(args) == "Test Q"

    def test_demo_uses_default_question(self):
        args = argparse.Namespace(question=None, demo=True)
        result = _get_question(args)
        assert result is not None
        assert "microservices" in result.lower() or "monolith" in result.lower()

    def test_interactive_prompt(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "Interactive Q")
        args = argparse.Namespace(question=None, demo=False)
        assert _get_question(args) == "Interactive Q"

    def test_empty_input_returns_none(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "")
        args = argparse.Namespace(question=None, demo=False)
        assert _get_question(args) is None


class TestResolveRounds:
    def test_demo_defaults_to_two_rounds(self):
        assert _resolve_rounds(None, use_demo=True) == 2

    def test_live_defaults_to_one_round(self):
        assert _resolve_rounds(None, use_demo=False) == 1

    def test_explicit_rounds_win(self):
        assert _resolve_rounds(4, use_demo=False) == 4


# =============================================================================
# Sync runner (Python 3.10 floor has no asyncio.Runner)
# =============================================================================


class TestRunSync:
    def test_run_sync_returns_coroutine_result(self):
        async def _work() -> str:
            await asyncio.sleep(0)
            return "done"

        assert _run_sync(_work()) == "done"

    def test_run_sync_uses_fallback_when_runner_is_absent(self, monkeypatch):
        monkeypatch.delattr(asyncio, "Runner", raising=False)
        calls: list[object] = []

        def _tracking_fallback(coro):
            calls.append(coro)
            return _run_sync_without_runner(coro)

        monkeypatch.setattr(
            "aragora.cli.commands.quickstart._run_sync_without_runner",
            _tracking_fallback,
        )
        seen: dict[str, object] = {}

        async def _work() -> str:
            seen["loop"] = asyncio.get_running_loop()
            return "fallback"

        assert _run_sync(_work()) == "fallback"
        assert len(calls) == 1
        assert seen["loop"].is_closed()

    def test_run_sync_prefers_runner_when_available(self, monkeypatch):
        if not hasattr(asyncio, "Runner"):
            pytest.skip("asyncio.Runner unavailable on this interpreter")
        calls: list[object] = []

        def _unexpected_fallback(coro):
            calls.append(coro)
            return _run_sync_without_runner(coro)

        monkeypatch.setattr(
            "aragora.cli.commands.quickstart._run_sync_without_runner",
            _unexpected_fallback,
        )

        async def _work() -> str:
            return "runner"

        assert _run_sync(_work()) == "runner"
        assert calls == []

    def test_fallback_cleans_up_pending_tasks_and_asyncgens(self):
        cancelled: list[bool] = []
        closed: list[bool] = []

        async def _agen():
            try:
                yield 1
                yield 2
            finally:
                closed.append(True)

        async def _background() -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def _work() -> str:
            gen = _agen()
            await gen.__anext__()
            asyncio.ensure_future(_background())
            return "cleanup"

        assert _run_sync_without_runner(_work()) == "cleanup"
        assert cancelled == [True]
        assert closed == [True]

    def test_fallback_reports_task_failures_during_shutdown(self):
        reported: list[dict[str, object]] = []

        async def _fails_on_cancel() -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise RuntimeError("cleanup failed") from None

        async def _work() -> str:
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(lambda _loop, ctx: reported.append(ctx))
            asyncio.ensure_future(_fails_on_cancel())
            return "shutdown"

        assert _run_sync_without_runner(_work()) == "shutdown"
        assert len(reported) == 1
        assert isinstance(reported[0]["exception"], RuntimeError)
        assert "shutdown" in str(reported[0]["message"])

    def test_fallback_leaves_policy_loop_untouched(self):
        outer = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(outer)

            async def _work() -> bool:
                return asyncio.get_running_loop() is not outer

            assert _run_sync_without_runner(_work()) is True
            assert asyncio.get_event_loop() is outer
        finally:
            asyncio.set_event_loop(None)
            outer.close()

    def test_fallback_propagates_exceptions_and_still_closes_loop(self):
        seen: dict[str, object] = {}

        async def _boom() -> None:
            seen["loop"] = asyncio.get_running_loop()
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_sync_without_runner(_boom())
        assert seen["loop"].is_closed()


# =============================================================================
# Receipt formatting
# =============================================================================


class TestReceiptFormatting:
    SAMPLE = {
        "question": "Migrate to K8s?",
        "verdict": "Yes",
        "confidence": 0.85,
        "rounds": 2,
        "agents": ["claude", "gpt4"],
        "summary": "Proceed with migration.",
        "dissent": [{"agent": "gpt4", "reason": "Timeline risk"}],
    }

    def test_markdown(self):
        md = receipt_to_markdown(self.SAMPLE)
        assert "# Decision Receipt" in md
        assert "Migrate to K8s?" in md
        assert "85%" in md
        assert "Timeline risk" in md

    def test_html(self):
        html = receipt_to_html(self.SAMPLE)
        assert "<!DOCTYPE html>" in html
        assert "Migrate to K8s?" in html
        assert "85%" in html

    def test_save_json(self, tmp_path):
        path = str(tmp_path / "receipt.json")
        saved_path = _save_receipt(self.SAMPLE, path, "json")
        loaded = json.loads(saved_path.read_text())
        assert loaded["verdict"] == "Yes"
        assert saved_path == Path(path).resolve()

    def test_save_md(self, tmp_path):
        path = str(tmp_path / "receipt.md")
        saved_path = _save_receipt(self.SAMPLE, path, "md")
        content = saved_path.read_text()
        assert "# Decision Receipt" in content

    def test_save_html(self, tmp_path):
        path = str(tmp_path / "receipt.html")
        saved_path = _save_receipt(self.SAMPLE, path, "html")
        content = saved_path.read_text()
        assert "<!DOCTYPE html>" in content

    def test_save_html_falls_back_to_json_when_formatter_import_fails(self, tmp_path):
        path = tmp_path / "receipt.html"
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "aragora.cli.receipt_formatter":
                raise ImportError("formatter unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            saved_path = _save_receipt(self.SAMPLE, path, "html")

        assert json.loads(saved_path.read_text())["verdict"] == "Yes"

    def test_save_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "receipt.json"
        saved_path = _save_receipt(self.SAMPLE, path, "json")
        assert saved_path.exists()

    def test_open_browser_returns_none_when_formatter_import_fails(self):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "aragora.cli.receipt_formatter":
                raise ImportError("formatter unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            assert _open_receipt_in_browser(self.SAMPLE) is None


class TestInlineApiKeys:
    def test_normalize_provider_aliases(self):
        assert _normalize_provider("openai-api") == "openai"
        assert _normalize_provider("xai") == "grok"
        assert _normalize_provider("nope") is None

    def test_configure_inline_api_key_sets_env_without_persisting(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        normalized_provider, saved_key = _configure_inline_api_key(
            "openai",
            "sk-inline",
            save_key=False,
        )
        assert normalized_provider == "openai"
        assert saved_key is None
        assert os.environ["OPENAI_API_KEY"] == "sk-inline"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_configure_inline_api_key_persists_via_secure_store(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("aragora.cli.api_keys.set_provider_key") as set_provider_key:
            set_provider_key.return_value = MagicMock(
                provider="openai",
                env_var="OPENAI_API_KEY",
                backend="macos-keychain",
                masked_value="sk-i...line",
            )
            normalized_provider, saved_key = _configure_inline_api_key(
                "openai",
                "sk-inline",
                save_key=True,
            )

        assert normalized_provider == "openai"
        assert saved_key == {
            "provider": "openai",
            "env_var": "OPENAI_API_KEY",
            "backend": "macos-keychain",
            "masked_value": "sk-i...line",
        }
        assert os.environ["OPENAI_API_KEY"] == "sk-inline"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_configure_inline_api_key_requires_provider(self):
        with pytest.raises(ValueError, match="--api-key requires --provider"):
            _configure_inline_api_key(None, "sk-inline", save_key=False)


class TestLiveQuickstartHelpers:
    def test_build_live_team_reuses_single_provider_for_real_debate(self):
        team = _build_live_team(
            [("openai-api", "gpt-4o")],
            provider="openai",
            api_key="sk-inline",
        )
        assert [agent["role"] for agent in team] == ["proposer", "critic", "synthesizer"]
        # Primary provider is openai-api; OpenRouter fallback may be mixed in
        assert team[0]["provider"] == "openai-api"
        assert team[0]["api_key"] == "sk-inline"

    def test_build_live_team_stays_single_provider_even_with_openrouter_available(self):
        team = _build_live_team(
            [
                ("anthropic-api", "claude-sonnet-4-5-20250929"),
                ("openai-api", "gpt-4o"),
                ("gemini", None),
            ]
        )

        providers = [agent["provider"] for agent in team]
        assert providers[0] == "gemini"
        assert providers == ["gemini"] * 3

    def test_build_live_receipt_surfaces_consensus_dissent_and_receipt(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        vote_for = argparse.Namespace(agent="alpha", choice="Ship it", reasoning="Best option")
        vote_against = argparse.Namespace(
            agent="beta",
            choice="Wait",
            reasoning="Timeline risk",
        )
        result = argparse.Namespace(
            debate_id="debate-123",
            participants=["alpha", "beta", "gamma"],
            final_answer="Ship it",
            confidence=0.82,
            consensus_reached=True,
            rounds_used=2,
            status="consensus_reached",
            debate_status=DebateStatus.COMPLETED.value,
            debate_status_source=DebateStatusSource.LIVE.value,
            dissenting_views=["Timeline risk remains unresolved."],
            proposals={"alpha": "Ship it"},
            votes=[vote_for, vote_against],
            metadata={"thinking_traces": {"alpha": "Consider the risk tradeoffs carefully."}},
        )

        receipt = _build_live_receipt(
            result,
            "Should we ship?",
            2,
            [
                {"name": "alpha", "provider": "openai-api"},
                {"name": "beta", "provider": "openai-api"},
                {"name": "gamma", "provider": "openai-api"},
            ],
        )

        assert receipt["receipt_id"] == "debate-123"
        assert receipt["artifact_hash"]
        assert receipt["debate_status"] == DebateStatus.COMPLETED.value
        assert receipt["debate_status_source"] == DebateStatusSource.LIVE.value
        assert receipt["synthetic"] is False
        assert receipt["consensus_proof"]["reached"] is True
        assert receipt["consensus_proof"]["supporting_agents"] == ["alpha"]
        assert receipt["consensus_proof"]["dissenting_agents"] == ["beta"]
        assert receipt["thinking_traces"] == {"alpha": "Consider the risk tradeoffs carefully."}
        assert receipt["dissent"][0]["reason"] == "Timeline risk remains unresolved."
        assert receipt["receipt"]["artifact_hash"] == receipt["artifact_hash"]
        assert DecisionReceipt.from_dict(receipt).verify_integrity() is True

    def test_build_live_receipt_clamps_confidence_into_unit_interval(self):
        result = argparse.Namespace(
            debate_id="debate-123",
            participants=["alpha"],
            final_answer="Ship it",
            confidence=1.2,
            consensus_reached=True,
            rounds_used=1,
            dissenting_views=[],
            proposals={},
            votes=[],
        )

        receipt = _build_live_receipt(
            result,
            "Should we ship?",
            1,
            [{"name": "alpha", "provider": "openai-api"}],
        )

        assert receipt["confidence"] == 1.0
        assert receipt["receipt"]["confidence"] == 1.0
        assert receipt["consensus_proof"]["confidence"] == 1.0

    def test_build_live_receipt_caps_settlement_confidence_for_sparse_debate_result(self):
        result = DebateResult(
            confidence=0.91,
            consensus_reached=True,
            debate_status=DebateStatus.COMPLETED.value,
            dissenting_views=[],
            final_answer="Proceed with a phased rollout.",
            participants=["proposer", "critic", "synthesizer"],
            rounds_used=1,
        )

        receipt = _build_live_receipt(
            result,
            "Should we proceed?",
            1,
            [
                {"name": "proposer", "provider": "openai-api"},
                {"name": "critic", "provider": "openai-api"},
                {"name": "synthesizer", "provider": "openai-api"},
            ],
        )

        strict_hygiene = validate_receipt(receipt, strict=True)
        assert strict_hygiene.passed_strict() is True
        assert receipt["confidence"] == pytest.approx(0.91)
        assert receipt["settlement"]["status"] == "needs_definition"
        assert receipt["settlement"]["claim"] == "Should we proceed?"
        assert receipt["settlement"]["review_horizon_days"] == 30
        assert receipt["settlement_metadata"]["confidence"] == pytest.approx(0.79)
        assert receipt["settlement_metadata"]["falsifiers"] == []
        assert any(
            "Quickstart could not derive explicit falsifiers" in note
            for note in receipt["settlement_metadata"]["review_notes"]
        )

    @pytest.mark.parametrize(
        ("raw_consensus", "expected"),
        [("true", True), ("false", False)],
    )
    def test_build_live_receipt_parses_string_consensus_flags(self, raw_consensus, expected):
        result = argparse.Namespace(
            debate_id="debate-123",
            participants=["alpha"],
            final_answer="Ship it",
            confidence=0.82,
            consensus_reached=raw_consensus,
            rounds_used=1,
            dissenting_views=[],
            proposals={},
            votes=[],
        )

        receipt = _build_live_receipt(
            result,
            "Should we ship?",
            1,
            [{"name": "alpha", "provider": "openai-api"}],
        )

        assert receipt["consensus_reached"] is expected
        assert receipt["consensus_proof"]["reached"] is expected

    @pytest.mark.parametrize(
        ("raw_consensus", "expected"),
        [("true", True), ("false", False)],
    )
    def test_build_quickstart_receipt_payload_parses_string_consensus_flags(
        self,
        raw_consensus,
        expected,
    ):
        payload = _build_quickstart_receipt_payload(
            {
                "question": "Should we ship?",
                "mode": "demo",
                "rounds": 1,
                "agents": ["alpha"],
                "summary": "Answer",
                "confidence": 0.82,
                "verdict": "consensus" if expected else "no_consensus",
                "consensus_reached": raw_consensus,
            }
        )

        assert payload["consensus_reached"] is expected
        assert payload["consensus_proof"]["reached"] is expected

    @pytest.mark.asyncio
    async def test_can_reach_provider_tls_normalizes_wrapped_cert_errors(self):
        with patch(
            "aragora.cli.commands.quickstart.asyncio.open_connection",
            side_effect=ssl.SSLError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
            ),
        ):
            ok, detail = await _can_reach_provider_tls("openai-api")

        assert ok is False
        assert detail == "CERTIFICATE_VERIFY_FAILED"

    @pytest.mark.asyncio
    async def test_can_reach_provider_tls_returns_unreachable_on_timeout(self, monkeypatch):
        async def blocked_connection(*args, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr("aragora.cli.commands.quickstart._LIVE_PRECHECK_TIMEOUT_SECONDS", 0.01)
        with patch(
            "aragora.cli.commands.quickstart.asyncio.open_connection",
            new=AsyncMock(side_effect=blocked_connection),
        ) as connection:
            ok, detail = await _can_reach_provider_tls("openai-api")

        assert ok is False
        assert detail == "TimeoutError"
        connection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_can_reach_provider_tls_handles_distinct_asyncio_timeout(self, monkeypatch):
        class LegacyAsyncioTimeoutError(Exception):
            pass

        # Python 3.10's asyncio timeout is not the builtin TimeoutError.
        monkeypatch.setattr(asyncio, "TimeoutError", LegacyAsyncioTimeoutError)
        with patch(
            "aragora.cli.commands.quickstart.asyncio.open_connection",
            new=AsyncMock(side_effect=LegacyAsyncioTimeoutError("TLS probe timed out")),
        ):
            ok, detail = await _can_reach_provider_tls("openai-api")

        assert ok is False
        assert detail == "TLS probe timed out"

    @pytest.mark.asyncio
    async def test_can_reach_provider_tls_ignores_close_noise_after_handshake(self):
        writer = MagicMock()
        writer.wait_closed = AsyncMock(side_effect=ConnectionResetError("socket closed"))

        with patch(
            "aragora.cli.commands.quickstart.asyncio.open_connection",
            return_value=(MagicMock(), writer),
        ):
            ok, detail = await _can_reach_provider_tls("openai-api")

        assert ok is True
        assert detail is None
        writer.close.assert_called_once()


# =============================================================================
# Command execution
# =============================================================================


class TestCmdQuickstart:
    @pytest.mark.asyncio
    async def test_run_demo_debate_uses_builtin_demo_agents(self):
        result = await _run_demo_debate("Should we ship the fallback fix?", rounds=2)

        assert result["mode"] == "demo"
        assert result["debate_status"] == DebateStatus.COMPLETED.value
        assert result["debate_status_source"] == DebateStatusSource.SYNTHETIC.value
        assert result["synthetic"] is True
        assert result["verdict"] == "approved"
        assert result["confidence"] == 0.85
        assert result["agents"] == ["analyst", "critic", "synthesizer"]
        assert "Demo synthesis for: Should we ship the fallback fix?" in result["summary"]

    @pytest.mark.asyncio
    async def test_run_demo_debate_verdict_passes_bundled_verify(self):
        """The demo receipt's verdict must be accepted by `aragora verify`.

        Regression for the quickstart lane defect where the demo hardcoded
        verdict='consensus', a value absent from verify's recognised Verdict
        set, so the headline zero-to-receipt artifact failed `aragora verify`.
        """
        from aragora.cli.commands.verify import _is_valid_verdict

        result = await _run_demo_debate("Should we ship the fallback fix?", rounds=2)

        # Verdict must be a verify-recognised Verdict value.
        assert _is_valid_verdict(result["verdict"]), result["verdict"]

        # The persisted demo receipt (post-canonicalize) must also carry a
        # recognised verdict and keep its consensus signal intact.
        payload = _build_quickstart_receipt_payload(result)
        assert _is_valid_verdict(payload["verdict"]), payload["verdict"]
        assert payload["consensus_reached"] is True

    @pytest.mark.asyncio
    async def test_run_demo_debate_payload_carries_generated_receipt_id(self):
        """The demo result payload must surface the generated stable receipt id.

        Regression for the accidental drop of the top-level ``receipt_id`` key
        while fixing the verdict to 'approved': the receipt id is still
        generated via ``_derive_receipt_id`` but must flow through to the
        result payload (and stay aligned with the nested receipt block) so
        downstream callers and receipt-building paths keep their stable id.
        The verdict fix ('approved') must remain intact alongside it.
        """
        question = "Should we ship the fallback fix?"
        rounds = 2
        expected_receipt_id = _derive_receipt_id(mode="demo", question=question, rounds=rounds)

        result = await _run_demo_debate(question, rounds=rounds)

        # The original (pre-regression) top-level receipt_id key is restored
        # and matches the deterministically derived id.
        assert result["receipt_id"] == expected_receipt_id
        # It stays consistent with the nested receipt block.
        assert result["receipt"]["id"] == expected_receipt_id
        # The verdict fix from #7566 remains intact.
        assert result["verdict"] == "approved"

    @pytest.mark.asyncio
    async def test_run_live_debate_raises_when_arena_returns_none(self):
        """Live quickstart should fail closed when Arena produces no result."""
        mock_agent = MagicMock()
        mock_agent.name = "openai-api"

        with (
            patch(
                "aragora.cli.commands.quickstart._filter_reachable_live_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch("aragora.agents.base.create_agent", return_value=mock_agent),
            patch("aragora.debate.orchestrator.Arena") as mock_arena_cls,
        ):
            mock_arena = MagicMock()
            mock_arena.run = AsyncMock(return_value=None)
            mock_arena_cls.return_value = mock_arena

            with pytest.raises(RuntimeError, match="Live debate returned no result"):
                await _run_live_debate(
                    "Should we ship the quickstart path?",
                    [("openai-api", "gpt-4o")],
                    rounds=2,
                )

    @pytest.mark.asyncio
    async def test_run_live_debate_times_out_cleanly(self, monkeypatch):
        """Live quickstart should bound long-running onboarding debates."""
        mock_agent = MagicMock()
        mock_agent.name = "openai-api"

        async def slow_run():
            await asyncio.sleep(0.05)
            return MagicMock()

        with (
            patch(
                "aragora.cli.commands.quickstart._filter_reachable_live_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch("aragora.agents.base.create_agent", return_value=mock_agent),
            patch("aragora.debate.orchestrator.Arena") as mock_arena_cls,
        ):
            mock_arena = MagicMock()
            mock_arena.run = slow_run
            mock_arena_cls.return_value = mock_arena
            monkeypatch.setattr(
                "aragora.cli.commands.quickstart._LIVE_DEBATE_TIMEOUT_SECONDS",
                0.01,
            )

            with pytest.raises(RuntimeError, match="Live debate timed out") as exc_info:
                await _run_live_debate(
                    "Should we ship the quickstart path?",
                    [("openai-api", "gpt-4o")],
                    rounds=2,
                )
            assert isinstance(exc_info.value.__cause__, asyncio.TimeoutError)

    @pytest.mark.asyncio
    async def test_run_live_debate_uses_bounded_quickstart_profile(self):
        """Live quickstart should disable heavyweight debate subsystems by default."""
        mock_agent = MagicMock()
        mock_agent.name = "openai-api"
        mock_result = argparse.Namespace()
        mock_insight_store = MagicMock()

        with (
            patch(
                "aragora.cli.commands.quickstart._filter_reachable_live_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch("aragora.agents.base.create_agent", return_value=mock_agent),
            patch("aragora.insights.store.InsightStore", return_value=mock_insight_store),
            patch(
                "aragora.cli.commands.quickstart._build_live_receipt",
                return_value={"mode": "live", "rounds": 1},
            ),
            patch("aragora.debate.orchestrator.Arena") as mock_arena_cls,
        ):
            mock_arena = MagicMock()
            mock_arena.run = AsyncMock(return_value=mock_result)
            mock_arena.knowledge_mound = object()
            mock_arena.enable_knowledge_ingestion = False
            mock_arena_cls.return_value = mock_arena

            result = await _run_live_debate(
                "Should we ship the quickstart path?",
                [("openai-api", "gpt-4o")],
                rounds=1,
            )

        protocol = mock_arena_cls.call_args.args[2]
        assert protocol.rounds == 1
        assert protocol.consensus == "majority"
        assert protocol.convergence_detection is False
        assert protocol.vote_grouping is False
        assert protocol.enable_trickster is False
        assert protocol.enable_research is False
        assert protocol.enable_trending_injection is False
        assert protocol.enable_llm_question_classification is False
        assert protocol.enable_llm_synthesis is False

        arena_kwargs = mock_arena_cls.call_args.kwargs
        assert arena_kwargs["insight_store"] is mock_insight_store
        assert arena_kwargs["disable_post_debate_pipeline"] is True
        assert mock_arena.enable_introspection is False

        # Quickstart now uses config objects instead of individual kwargs
        memory_config = arena_kwargs["memory_config"]
        assert memory_config.enable_knowledge_retrieval is True
        assert memory_config.enable_knowledge_ingestion is False
        assert memory_config.auto_create_knowledge_mound is True
        assert memory_config.enable_belief_guidance is False
        assert memory_config.enable_cross_debate_memory is False
        assert memory_config.use_rlm_limiter is False

        knowledge_config = arena_kwargs["knowledge_config"]
        assert knowledge_config.enable_knowledge_retrieval is True
        assert knowledge_config.enable_knowledge_ingestion is False
        assert knowledge_config.enable_belief_guidance is False

        ml_config = arena_kwargs["ml_config"]
        assert ml_config.enable_ml_delegation is False
        assert ml_config.enable_quality_gates is False
        assert ml_config.enable_consensus_estimation is False
        assert result["km_ingested"] is False

    @pytest.mark.asyncio
    async def test_run_live_debate_skips_crux_event_dispatch_in_bounded_profile(self):
        """Bounded quickstart should not emit crux events through the webhook dispatcher."""

        def fake_create_agent(
            agent_type: str,
            *,
            name: str,
            role: str,
            model: str | None = None,
            api_key: str | None = None,
        ):
            del agent_type, model, api_key
            return create_real_agent("demo", name=name, role=role)

        with (
            patch(
                "aragora.cli.commands.quickstart._filter_reachable_live_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch("aragora.agents.base.create_agent", side_effect=fake_create_agent),
            patch(
                "aragora.events.dispatcher.dispatch_event",
                side_effect=AssertionError("bounded quickstart should not dispatch crux events"),
            ),
        ):
            result = await _run_live_debate(
                "Should we ship the quickstart path?",
                [("openai-api", "gpt-4o")],
                rounds=1,
            )

        assert result["mode"] == "live"
        assert result["rounds"] == 1

    @pytest.mark.asyncio
    async def test_filter_reachable_live_agents_returns_empty_on_tls_failure(self):
        """When all providers fail TLS, return empty list for demo fallback."""
        with patch(
            "aragora.cli.commands.quickstart._can_reach_provider_tls",
            new=AsyncMock(return_value=(False, "CERTIFICATE_VERIFY_FAILED")),
        ):
            result = await _filter_reachable_live_agents(
                [("openai-api", "gpt-4o"), ("gemini", None)]
            )
            assert result == []

    @pytest.mark.asyncio
    async def test_filter_reachable_live_agents_treats_wrapped_tls_detail_as_cert_failure(self):
        with patch(
            "aragora.cli.commands.quickstart._can_reach_provider_tls",
            new=AsyncMock(
                return_value=(
                    False,
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
                )
            ),
        ):
            reachable = await _filter_reachable_live_agents([("openai-api", "gpt-4o")])

        assert reachable == []

    @pytest.mark.asyncio
    async def test_filter_reachable_live_agents_keeps_healthy_subset(self):
        """Providers that pass preflight should still be used."""

        async def fake_probe(provider: str) -> tuple[bool, str | None]:
            if provider == "openai-api":
                return True, None
            return False, "connection refused"

        with patch(
            "aragora.cli.commands.quickstart._can_reach_provider_tls",
            side_effect=fake_probe,
        ):
            reachable = await _filter_reachable_live_agents(
                [("openai-api", "gpt-4o"), ("gemini", None)]
            )

        assert reachable == [("openai-api", "gpt-4o")]

    def test_demo_mode(self, capsys):
        """Test quickstart runs in demo mode with mock agents."""
        args = argparse.Namespace(
            question="Should we use Rust?",
            demo=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        # Mock the aragora_debate imports
        with patch(
            "aragora.cli.commands.quickstart._run_demo_debate",
            return_value={
                "question": "Should we use Rust?",
                "verdict": "consensus",
                "confidence": 0.85,
                "rounds": 2,
                "agents": ["analyst", "critic", "synthesizer"],
                "summary": "Use Rust for performance-critical paths.",
                "dissent": [],
                "mode": "demo",
            },
        ):
            cmd_quickstart(args)

        output = capsys.readouterr().out
        assert "QUICKSTART" in output
        assert "consensus" in output.lower()

    def test_live_mode_defaults_to_one_round_when_unspecified(self, capsys):
        args = argparse.Namespace(
            question="Should we use the live default?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=None,
            no_browser=True,
        )

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                return_value={
                    "question": "Should we use the live default?",
                    "verdict": "approve",
                    "confidence": 0.8,
                    "rounds": 1,
                    "agents": ["openai-api"],
                    "summary": "Use the bounded live default.",
                    "dissent": [],
                    "mode": "live",
                },
            ) as run_live_debate,
        ):
            cmd_quickstart(args)

        assert run_live_debate.call_args.args[2] == 1

    def test_demo_mode_defaults_to_two_rounds_when_unspecified(self, capsys):
        args = argparse.Namespace(
            question="Should we use the demo default?",
            demo=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=None,
            no_browser=True,
        )

        with patch(
            "aragora.cli.commands.quickstart._run_demo_debate",
            return_value={
                "question": "Should we use the demo default?",
                "verdict": "consensus",
                "confidence": 0.85,
                "rounds": 2,
                "agents": ["analyst", "critic", "synthesizer"],
                "summary": "Keep demo defaults stable.",
                "dissent": [],
                "mode": "demo",
            },
        ) as run_demo_debate:
            cmd_quickstart(args)

        assert run_demo_debate.call_args.args[1] == 2

    def test_no_question_exits(self):
        """Test that missing question causes exit."""
        args = argparse.Namespace(
            question=None,
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(SystemExit):
                cmd_quickstart(args)

    def test_output_saves_receipt(self, tmp_path, capsys):
        """Test that --output flag saves the receipt."""
        output_path = str(tmp_path / "test_receipt.json")
        args = argparse.Namespace(
            question="Test?",
            demo=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=output_path,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        with patch(
            "aragora.cli.commands.quickstart._run_demo_debate",
            return_value={
                "question": "Test?",
                "verdict": "yes",
                "confidence": 0.9,
                "rounds": 2,
                "agents": ["a", "b"],
                "summary": "Summary",
                "dissent": [],
                "mode": "demo",
            },
        ):
            cmd_quickstart(args)

        assert Path(output_path).exists()
        data = json.loads(Path(output_path).read_text())
        assert data["verdict"] == "yes"

    def test_demo_mode_saves_receipt_that_verifies(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should we verify the saved quickstart receipt?",
            demo=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=MagicMock(),
        ):
            cmd_quickstart(args)

        artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-demo-receipt.json"
        assert artifact_path.exists()
        saved = json.loads(artifact_path.read_text())
        strict_hygiene = validate_receipt(saved, strict=True)
        assert strict_hygiene.passed_strict() is True
        assert saved["settlement_metadata"]["confidence"] == pytest.approx(0.79)
        assert saved["settlement_metadata"]["falsifiers"] == []
        assert any(
            "Quickstart could not derive explicit falsifiers" in note
            for note in saved["settlement_metadata"]["review_notes"]
        )

        capsys.readouterr()
        with pytest.raises(SystemExit) as excinfo:
            cmd_receipt_verify(argparse.Namespace(receipt=str(artifact_path), verbose=False))

        assert excinfo.value.code == 0
        output = capsys.readouterr().out
        assert "Result: VALID" in output
        saved = json.loads(artifact_path.read_text())
        strict_hygiene = validate_receipt(saved, strict=True)
        assert strict_hygiene.passed_strict() is True
        assert saved["settlement"]["status"] == "needs_definition"
        assert saved["settlement"]["claim"] == "Should we verify the saved quickstart receipt?"
        assert saved["settlement"]["falsifier"] == (
            "Define an objective falsifier for the primary claim."
        )
        assert saved["settlement"]["metric"] == (
            "Define a measurable metric for decision settlement."
        )
        assert saved["settlement"]["review_horizon_days"] == 30
        assert saved["settlement_metadata"]["confidence"] == pytest.approx(0.79)
        assert saved["settlement_metadata"]["falsifiers"] == []
        assert any(
            "Quickstart could not derive explicit falsifiers" in note
            for note in saved["settlement_metadata"]["review_notes"]
        )

    def test_live_mode_saves_default_receipt_artifact(self, tmp_path, monkeypatch, capsys):
        """Test live quickstart saves a deterministic default artifact."""
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should we ship the CLI quickstart?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        live_result = {
            "question": "Should we ship the CLI quickstart?",
            "verdict": "approve",
            "confidence": 0.91,
            "rounds": 2,
            "agents": ["openai-api"],
            "summary": "Ship the truthful quickstart flow.",
            "dissent": [],
            "verification_criteria": [
                "Saved quickstart receipts continue to pass the strict epistemic hygiene gate."
            ],
            "mode": "live",
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                return_value=live_result,
            ),
        ):
            cmd_quickstart(args)

        artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-live-receipt.json"
        assert artifact_path.exists()
        saved = json.loads(artifact_path.read_text())
        assert saved["mode"] == "live"
        strict_hygiene = validate_receipt(saved, strict=True)
        assert strict_hygiene.passed_strict() is True
        assert saved["confidence"] == pytest.approx(0.91)
        assert saved["settlement"]["status"] == "needs_definition"
        assert saved["settlement"]["claim"] == "Should we ship the CLI quickstart?"
        assert saved["settlement"]["review_horizon_days"] == 30
        assert saved["settlement_metadata"]["confidence"] == pytest.approx(0.79)
        assert saved["settlement_metadata"]["falsifiers"] == []
        assert any(
            "Quickstart could not derive explicit falsifiers" in note
            for note in saved["settlement_metadata"]["review_notes"]
        )

        output = capsys.readouterr().out
        assert "Run mode: live" in output
        assert "Agents: openai-api" in output
        assert "Mode:       Live" in output
        assert str(artifact_path.resolve()) in output

    def test_inline_provider_key_can_be_saved_and_run_live(self, tmp_path, monkeypatch, capsys):
        """Test quickstart can take one inline key and save it securely."""
        monkeypatch.chdir(tmp_path)
        for key in [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "MISTRAL_API_KEY",
            "XAI_API_KEY",
            "GROK_API_KEY",
            "OPENROUTER_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        args = argparse.Namespace(
            question="Should we ship the quickstart slice?",
            demo=False,
            provider="openai",
            api_key="sk-inline",
            save_key=True,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        live_result = {
            "question": "Should we ship the quickstart slice?",
            "verdict": "PASS",
            "confidence": 0.93,
            "rounds": 2,
            "agents": [
                "openai-api-proposer",
                "openai-api-critic",
                "openai-api-synthesizer",
            ],
            "summary": "Ship the quickstart slice.",
            "dissent": [],
            "mode": "live",
            "receipt_id": "debate-quickstart-1",
            "artifact_hash": "abc123def4567890",
            "consensus_proof": {"reached": True},
        }

        with (
            patch("aragora.cli.api_keys.set_provider_key") as set_provider_key,
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                return_value=live_result,
            ) as run_live_debate,
        ):
            set_provider_key.return_value = MagicMock(
                provider="openai",
                env_var="OPENAI_API_KEY",
                backend="macos-keychain",
                masked_value="sk-i...line",
            )
            cmd_quickstart(args)

        assert os.environ["OPENAI_API_KEY"] == "sk-inline"
        assert run_live_debate.call_args.kwargs["provider"] == "openai"
        assert run_live_debate.call_args.kwargs["api_key"] == "sk-inline"

        output = capsys.readouterr().out
        assert "Saved OPENAI_API_KEY to secure store" in output
        assert "Receipt:    debate-quickstart-1" in output
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_quickstart_persists_same_canonical_payload_to_artifact_and_store(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should we persist the quickstart receipt?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        live_result = {
            "question": "Should we persist the quickstart receipt?",
            "verdict": "PASS",
            "confidence": 0.93,
            "rounds": 2,
            "agents": [
                "openai-api-proposer",
                "openai-api-critic",
                "openai-api-synthesizer",
            ],
            "summary": "Persist the receipt so product surfaces can show it.",
            "dissent": [],
            "mode": "live",
            "receipt_id": "debate-quickstart-1",
            "artifact_hash": "abc123def4567890",
            "consensus_proof": {"reached": True},
        }
        mock_facade = MagicMock()
        saved_artifact = tmp_path / "quickstart.json"

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("openai-api", "gpt-4o")],
            ),
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                return_value=live_result,
            ),
            patch(
                "aragora.cli.commands.quickstart._save_receipt",
                return_value=saved_artifact,
            ) as save_receipt,
            patch(
                "aragora.pipeline.receipt_store_facade.get_receipt_store_facade",
                return_value=mock_facade,
            ),
        ):
            cmd_quickstart(args)

        save_receipt.assert_called_once()
        mock_facade.persist_and_save.assert_called_once()
        artifact_payload = save_receipt.call_args.args[0]
        store_payload = mock_facade.persist_and_save.call_args.args[1]
        assert artifact_payload == store_payload
        assert store_payload["receipt_id"] == "debate-quickstart-1"
        assert store_payload["debate_id"] == "debate-quickstart-1"
        assert store_payload["gauntlet_id"] == "debate-quickstart-1"
        assert store_payload["checksum"] == "abc123def4567890"
        assert store_payload["receipt"]["id"] == "debate-quickstart-1"
        assert store_payload["receipt"]["artifact_hash"] == "abc123def4567890"
        assert store_payload["verdict"] == "PASS"

    def test_no_keys_fall_back_to_demo_and_report_demo_artifact(
        self, tmp_path, monkeypatch, capsys
    ):
        """Test quickstart is explicit when it falls back to demo mode."""
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should we use the fallback?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        demo_result = {
            "question": "Should we use the fallback?",
            "verdict": "consensus",
            "confidence": 0.84,
            "rounds": 2,
            "agents": ["analyst", "critic", "synthesizer"],
            "summary": "Fallback stayed honest about using mock agents.",
            "dissent": [],
            "mode": "demo",
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[],
            ),
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                return_value=demo_result,
            ),
        ):
            cmd_quickstart(args)

        artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-demo-receipt.json"
        assert artifact_path.exists()
        saved = json.loads(artifact_path.read_text())
        assert saved["mode"] == "demo"
        assert saved["provider_path"]["blocked"] is True
        assert saved["provider_path"]["config_present"] is False
        assert saved["provider_path"]["live_ready"] is False
        assert saved["provider_path"]["next_action"]
        assert saved["fallback"]["label"] == "mock/simulated"

        output = capsys.readouterr().out
        assert "Falling back to demo mode" in output
        assert "mock/simulated" in output

    def test_live_mode_falls_back_to_demo_on_tls_failure(self, capsys):
        """TLS/provider failures should fall back to demo mode, not exit."""
        args = argparse.Namespace(
            question="Should we use the live path?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )

        mock_demo_result = {
            "question": "Should we use the live path?",
            "verdict": "consensus",
            "confidence": 0.85,
            "rounds": 2,
            "agents": ["analyst", "critic", "synthesizer"],
            "summary": "Demo result",
            "dissent": [],
            "mode": "demo",
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("gemini", None)],
            ),
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                side_effect=RuntimeError("Live debate failed: CERTIFICATE_VERIFY_FAILED"),
            ) as mock_live_debate,
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                return_value=mock_demo_result,
            ),
        ):
            cmd_quickstart(args)

        mock_live_debate.assert_called_once()
        output = capsys.readouterr().out
        assert "Falling back to demo" in output
        assert "RESULT" in output  # Demo result was displayed

    @pytest.mark.parametrize("tls_timeout", [False, True])
    def test_configured_but_unreachable_provider_falls_back_after_live_attempt(
        self, tmp_path, monkeypatch, capsys, tls_timeout
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should the provider path stay truthful?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )
        demo_result = {
            "question": args.question,
            "verdict": "consensus",
            "confidence": 0.71,
            "rounds": 2,
            "agents": ["analyst", "critic", "synthesizer"],
            "summary": "Fallback was simulated rather than live.",
            "dissent": [],
            "mode": "demo",
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("gemini", "gemini-2.0-flash")],
            ),
            patch(
                "aragora.cli.commands.quickstart.asyncio.open_connection"
                if tls_timeout
                else "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(side_effect=asyncio.TimeoutError("TLS probe timed out"))
                if tls_timeout
                else AsyncMock(return_value=(False, "connection refused")),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                side_effect=RuntimeError("No live debate team could be assembled for quickstart"),
            ) as mock_live_debate,
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                return_value=demo_result,
            ),
        ):
            cmd_quickstart(args)

        mock_live_debate.assert_awaited_once()
        artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-demo-receipt.json"
        saved = json.loads(artifact_path.read_text())
        assert saved["provider_path"]["blocked"] is True
        assert saved["provider_path"]["config_present"] is True
        assert saved["provider_path"]["live_ready"] is False
        assert saved["provider_path"]["reason"] == "providers_unreachable"
        assert saved["provider_path"]["next_action"]
        assert saved["fallback"]["label"] == "mock/simulated"

        output = capsys.readouterr().out
        assert "Live provider preflight could not verify reachability" in output
        assert "No live providers available. Falling back to demo mode." in output
        assert "mock/simulated" in output

    def test_live_mode_real_demo_fallback_survives_without_legacy_demo_package(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should we keep the real fallback path working?",
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=2,
            no_browser=True,
        )

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[("gemini", "gemini-3.1-pro")],
            ),
            patch(
                "aragora.cli.commands.quickstart._can_reach_provider_tls",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                side_effect=RuntimeError("Live debate timed out after 120s"),
            ) as mock_live_debate,
        ):
            cmd_quickstart(args)

        mock_live_debate.assert_called_once()
        artifact_path = tmp_path / ".aragora" / "receipts" / "quickstart-demo-receipt.json"
        assert artifact_path.exists()
        saved = json.loads(artifact_path.read_text())
        assert saved["mode"] == "demo"
        assert saved["agents"] == ["analyst", "critic", "synthesizer"]
        assert (
            "Demo synthesis for: Should we keep the real fallback path working?" in saved["summary"]
        )

        output = capsys.readouterr().out
        assert "Live debate failed: Live debate timed out after 120s" in output
        assert "Mode:       Demo" in output

    def test_json_mode_prints_structured_result_to_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should quickstart emit JSON?",
            demo=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=True,
            rounds=1,
            no_browser=False,
        )

        with (
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                return_value={
                    "question": "Should quickstart emit JSON?",
                    "verdict": "consensus",
                    "confidence": 0.85,
                    "rounds": 1,
                    "agents": ["analyst", "critic", "synthesizer"],
                    "summary": "Emit structured output.",
                    "dissent": [],
                    "mode": "demo",
                },
            ),
            patch("aragora.cli.commands.quickstart._open_receipt_in_browser") as open_browser,
        ):
            cmd_quickstart(args)

        output = capsys.readouterr()
        payload = json.loads(output.out)
        assert payload["receipt_id"].startswith("quickstart-demo-")
        assert payload["consensus"] is True
        assert payload["consensus_reached"] is True
        assert payload["agent_votes"] == []
        assert Path(payload["artifact_path"]).exists()
        assert "ARAGORA QUICKSTART" in output.err
        open_browser.assert_not_called()

    def test_json_mode_interactive_prompt_keeps_stdout_clean(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("builtins.input", lambda: "Should JSON prompts stay off stdout?")
        args = argparse.Namespace(
            question=None,
            demo=False,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=True,
            rounds=1,
            no_browser=True,
        )

        with (
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                return_value=[],
            ),
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                return_value={
                    "question": "Should JSON prompts stay off stdout?",
                    "verdict": "consensus",
                    "confidence": 0.85,
                    "rounds": 1,
                    "agents": ["analyst", "critic", "synthesizer"],
                    "summary": "Keep stdout reserved for machine-readable JSON.",
                    "dissent": [],
                    "mode": "demo",
                },
            ),
        ):
            cmd_quickstart(args)

        output = capsys.readouterr()
        payload = json.loads(output.out)
        assert payload["question"] == "Should JSON prompts stay off stdout?"
        assert "> " in output.err

    def test_spec_first_writes_spec_artifact_and_skips_debate_execution(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should quickstart generate a spec first?",
            demo=False,
            spec_first=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="md",
            json=False,
            rounds=None,
            no_browser=True,
        )
        spec_result = {
            "spec_bundle": {
                "title": "Spec-first quickstart",
                "problem_statement": "Create a spec before running debate.",
                "acceptance_criteria": ["save an artifact", "show the next command"],
                "rollback_plan": ["fall back to direct debate if spec generation fails"],
            },
            "pipeline": "orchestrator",
            "run_id": "run-spec-1",
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._run_quickstart_spec_first",
                new=AsyncMock(return_value=spec_result),
            ) as run_spec_first,
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                side_effect=AssertionError("spec-first should return before agent detection"),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_live_debate",
                side_effect=AssertionError("spec-first should not launch a live debate"),
            ),
            patch(
                "aragora.cli.commands.quickstart._run_demo_debate",
                side_effect=AssertionError("spec-first should not launch a demo debate"),
            ),
        ):
            cmd_quickstart(args)

        artifact_path = tmp_path / ".aragora" / "specs" / "quickstart-spec.json"
        assert artifact_path.exists()

        saved_payload = json.loads(artifact_path.read_text())
        assert saved_payload["question"] == "Should quickstart generate a spec first?"
        assert saved_payload["mode"] == "quickstart-spec"
        assert saved_payload["pipeline"] == "orchestrator"
        assert saved_payload["run_id"] == "run-spec-1"
        assert saved_payload["spec_bundle"]["acceptance_criteria"] == [
            "save an artifact",
            "show the next command",
        ]

        run_spec_first.assert_awaited_once_with("Should quickstart generate a spec first?")

        output = capsys.readouterr().out
        assert "Run mode: spec-first" in output
        assert "Spec-first quickstart always saves JSON artifacts" in output
        assert "Pipeline:   orchestrator" in output
        assert "Run:        run-spec-1" in output
        assert str(artifact_path) in output
        assert (
            f"aragora decide 'Should quickstart generate a spec first?' --spec {artifact_path}"
            in output
        )

    @pytest.mark.asyncio
    async def test_run_quickstart_spec_first_falls_back_when_orchestrator_returns_empty_spec(self):
        with patch(
            "aragora.cli.commands.spec._run_spec_pipeline",
            new=AsyncMock(
                return_value={
                    "specification": None,
                    "intent": None,
                    "research": None,
                    "questions": [],
                    "stages_completed": ["research", "extend", "debate"],
                    "auto_approved": False,
                    "timing": None,
                    "run_id": "run-empty-spec",
                    "debate_result": None,
                    "spec_bundle": None,
                }
            ),
        ) as run_spec_pipeline:
            result = await _run_quickstart_spec_first(
                "Should quickstart emit a truthful starter spec?"
            )

        spec = result["specification"]
        assert result["pipeline"] == "quickstart_fallback"
        assert result["fallback_reason"] == "orchestrator returned no structured specification"
        assert spec["problem_statement"] == "Should quickstart emit a truthful starter spec?"
        assert len(spec["success_criteria"]) == 3
        assert len(spec["risks"]) == 1
        run_spec_pipeline.assert_awaited_once_with(
            "Should quickstart emit a truthful starter spec?",
            depth="quick",
            profile="founder",
            output_format="json",
            use_orchestrator=True,
        )

    def test_spec_first_surfaces_fallback_note_when_canonical_spec_is_unavailable(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(
            question="Should quickstart emit a truthful starter spec?",
            demo=False,
            spec_first=True,
            provider=None,
            api_key=None,
            save_key=False,
            output=None,
            format="json",
            json=False,
            rounds=None,
            no_browser=True,
        )
        fallback_result = {
            "specification": {
                "title": "Should quickstart emit a truthful starter spec",
                "problem_statement": "Should quickstart emit a truthful starter spec?",
                "proposed_solution": "Start from a bounded manual spec.",
                "success_criteria": [
                    {"description": "Capture the exact decision or change in one sentence."},
                    {
                        "description": "Name at least one measurable verification step or success signal."
                    },
                    {
                        "description": "List the main constraint, risk, or rollback trigger before execution."
                    },
                ],
                "risks": [
                    {
                        "description": "The canonical prompt-to-spec pipeline did not return structured output in this environment."
                    }
                ],
                "estimated_effort": "small",
                "confidence": 0.2,
            },
            "pipeline": "quickstart_fallback",
            "fallback_reason": "orchestrator returned no structured specification",
            "stages_completed": ["fallback_spec"],
        }

        with (
            patch(
                "aragora.cli.commands.quickstart._run_quickstart_spec_first",
                new=AsyncMock(return_value=fallback_result),
            ),
            patch(
                "aragora.cli.commands.quickstart._detect_agents",
                side_effect=AssertionError("spec-first should return before agent detection"),
            ),
        ):
            cmd_quickstart(args)

        output = capsys.readouterr().out
        saved_payload = json.loads(
            (tmp_path / ".aragora" / "specs" / "quickstart-spec.json").read_text()
        )

        assert saved_payload["pipeline"] == "quickstart_fallback"
        assert "Pipeline:   quickstart_fallback" in output
        assert "Starter spec fallback (orchestrator returned no structured specification)" in output
