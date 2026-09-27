"""
Tests for the CLI main module.

Covers argument parsing, command handlers, and utility functions.
"""

import argparse
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import sys

import pytest

from aragora.cli import parser as cli_parser
from aragora.cli.main import (
    parse_agents,
    get_event_emitter_if_available,
    main,
    _should_hydrate_startup_secrets,
)


def test_ask_cleanup_drains_dispatcher_before_closing_webhook_store_dependencies():
    """In-flight webhook workers finish before their store dependencies close."""
    from aragora.cli.commands import debate as debate_cmd

    order: list[str] = []
    with (
        patch(
            "aragora.events.dispatcher.shutdown_dispatcher",
            side_effect=lambda *, wait: order.append(f"dispatcher:{wait}"),
        ),
        patch(
            "aragora.server.startup.database.close_postgres_pool",
            new=AsyncMock(side_effect=lambda: order.append("postgres")),
        ),
        patch(
            "aragora.storage.connection_factory.close_all_pools",
            new=AsyncMock(side_effect=lambda: order.append("connection-pools")),
        ),
        patch(
            "aragora.storage.webhook_config_store.reset_webhook_config_store",
            side_effect=lambda: order.append("store"),
        ),
    ):
        asyncio.run(debate_cmd._shutdown_cmd_ask_resources())

    assert order == ["dispatcher:True", "postgres", "connection-pools", "store"]


# =============================================================================
# Parse Agents Tests
# =============================================================================


class TestParseAgents:
    """Tests for parse_agents function.

    Note: parse_agents returns AgentSpec objects with:
    - Explicit role if second part is a valid role (claude:critic → role=critic)
    - role=None when not explicitly specified (position-based assignment happens in run_debate)
    """

    def test_single_agent(self):
        """Single agent has role=None (not yet position-assigned)."""
        result = parse_agents("codex")
        assert len(result) == 1
        assert result[0].provider == "codex"
        assert result[0].role is None  # Position-based assignment happens in run_debate

    def test_multiple_agents(self):
        """Multiple agents have role=None when not explicitly specified."""
        result = parse_agents("codex,claude,openai")
        assert len(result) == 3
        assert result[0].provider == "codex"
        assert result[0].role is None
        assert result[1].provider == "claude"
        assert result[1].role is None
        assert result[2].provider == "openai"
        assert result[2].role is None

    def test_agent_with_role(self):
        """Explicit valid role (critic) is preserved."""
        result = parse_agents("claude:critic")
        assert len(result) == 1
        assert result[0].provider == "claude"
        assert result[0].role == "critic"

    def test_mixed_agents_and_roles(self):
        """Mix of explicit roles and unspecified roles."""
        result = parse_agents("codex,claude:critic,openai:synthesizer")
        assert len(result) == 3
        assert result[0].provider == "codex"
        assert result[0].role is None  # No explicit role
        assert result[1].provider == "claude"
        assert result[1].role == "critic"  # Explicit valid role
        assert result[2].provider == "openai"
        assert result[2].role == "synthesizer"  # Explicit valid role

    def test_strips_whitespace(self):
        """Whitespace is stripped."""
        result = parse_agents(" codex , claude ")
        assert len(result) == 2
        assert result[0].provider == "codex"
        assert result[0].role is None
        assert result[1].provider == "claude"
        assert result[1].role is None

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = parse_agents("")
        assert result == []

    def test_agent_with_complex_role(self):
        """Non-valid roles treated as persona, role=None."""
        result = parse_agents("claude:super_critic")
        assert len(result) == 1
        assert result[0].provider == "claude"
        # 'super_critic' is NOT a valid role, so treated as persona
        assert result[0].persona == "super_critic"
        assert result[0].role is None


# =============================================================================
# Event Emitter Tests
# =============================================================================


class TestGetEventEmitter:
    """Tests for get_event_emitter_if_available function."""

    def test_returns_none_when_server_not_available(self):
        """Should return None when server is not reachable."""
        result = get_event_emitter_if_available("http://localhost:99999")
        assert result is None

    def test_returns_none_on_timeout(self):
        """Should return None on connection timeout."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError()
            result = get_event_emitter_if_available()
            assert result is None

    def test_returns_none_on_url_error(self):
        """Should return None on URL error."""
        import urllib.error

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            result = get_event_emitter_if_available()
            assert result is None


# =============================================================================
# Argument Parser Tests
# =============================================================================


class TestArgumentParser:
    """Tests for argument parsing."""

    @pytest.fixture
    def parser(self):
        """Create the argument parser."""
        # Re-create the parser similar to main()
        parser = argparse.ArgumentParser()
        parser.add_argument("--db", default="agora_memory.db")
        parser.add_argument("-v", "--verbose", action="store_true")

        subparsers = parser.add_subparsers(dest="command")

        # Ask command
        ask_parser = subparsers.add_parser("ask")
        ask_parser.add_argument("task")
        ask_parser.add_argument("--agents", "-a", default="codex,claude")
        ask_parser.add_argument("--rounds", "-r", type=int, default=3)
        ask_parser.add_argument("--consensus", "-c", default="majority")
        ask_parser.add_argument("--context")
        ask_parser.add_argument("--no-learn", dest="learn", action="store_false")
        ask_parser.add_argument("--demo", action="store_true")

        # Stats command
        subparsers.add_parser("stats")

        # Patterns command
        patterns_parser = subparsers.add_parser("patterns")
        patterns_parser.add_argument("--type", "-t")
        patterns_parser.add_argument("--min-success", type=int, default=1)
        patterns_parser.add_argument("--limit", "-l", type=int, default=10)

        # Demo command
        demo_parser = subparsers.add_parser("demo")
        demo_parser.add_argument("name", nargs="?")

        # Serve command
        serve_parser = subparsers.add_parser("serve")
        serve_parser.add_argument("--ws-port", type=int, default=8765)
        serve_parser.add_argument("--api-port", type=int, default=8080)
        serve_parser.add_argument("--host", default="localhost")

        return parser

    def test_parse_ask_command(self, parser):
        """Should parse ask command with task."""
        args = parser.parse_args(["ask", "Design a rate limiter"])
        assert args.command == "ask"
        assert args.task == "Design a rate limiter"
        assert args.agents == "codex,claude"
        assert args.rounds == 3

    def test_parse_ask_with_agents(self, parser):
        """Should parse ask with custom agents."""
        args = parser.parse_args(["ask", "Task", "-a", "gpt4,claude"])
        assert args.agents == "gpt4,claude"

    def test_parse_ask_with_rounds(self, parser):
        """Should parse ask with custom rounds."""
        args = parser.parse_args(["ask", "Task", "-r", "5"])
        assert args.rounds == 5

    def test_parse_ask_with_consensus(self, parser):
        """Should parse ask with consensus option."""
        args = parser.parse_args(["ask", "Task", "-c", "unanimous"])
        assert args.consensus == "unanimous"

    def test_parse_ask_with_context(self, parser):
        """Should parse ask with context."""
        args = parser.parse_args(["ask", "Task", "--context", "Extra info"])
        assert args.context == "Extra info"

    def test_parse_ask_no_learn(self, parser):
        """Should parse --no-learn flag."""
        args = parser.parse_args(["ask", "Task", "--no-learn"])
        assert args.learn is False

    def test_parse_ask_learn_default(self, parser):
        """Should default to learning enabled."""
        args = parser.parse_args(["ask", "Task"])
        assert args.learn is True
        assert args.demo is False

    def test_parse_ask_demo(self, parser):
        """Should parse --demo flag."""
        args = parser.parse_args(["ask", "Task", "--demo"])
        assert args.demo is True

    def test_parse_stats_command(self, parser):
        """Should parse stats command."""
        args = parser.parse_args(["stats"])
        assert args.command == "stats"

    def test_parse_patterns_command(self, parser):
        """Should parse patterns command."""
        args = parser.parse_args(["patterns"])
        assert args.command == "patterns"
        assert args.limit == 10

    def test_parse_patterns_with_type(self, parser):
        """Should parse patterns with type filter."""
        args = parser.parse_args(["patterns", "-t", "security"])
        assert args.type == "security"

    def test_parse_patterns_with_limit(self, parser):
        """Should parse patterns with limit."""
        args = parser.parse_args(["patterns", "-l", "20"])
        assert args.limit == 20

    def test_parse_demo_command(self, parser):
        """Should parse demo command."""
        args = parser.parse_args(["demo"])
        assert args.command == "demo"
        assert args.name is None

    def test_parse_demo_with_name(self, parser):
        """Should parse demo with name."""
        args = parser.parse_args(["demo", "rate-limiter"])
        assert args.name == "rate-limiter"

    def test_real_parser_accepts_demo_offline_receipt_path(self):
        """The public demo round-trip flags must stay wired on the real parser."""
        parser = cli_parser.build_parser()

        args = parser.parse_args(["demo", "--offline", "--receipt", "aragora-demo-receipt.json"])

        assert args.command == "demo"
        assert args.offline is True
        assert args.receipt == "aragora-demo-receipt.json"

    def test_real_parser_accepts_ask_crux_cards(self):
        """--crux-cards must stay wired on the real ask parser (default off)."""
        parser = cli_parser.build_parser()

        args = parser.parse_args(["ask", "Task", "--crux-cards"])
        assert args.crux_cards is True

        args = parser.parse_args(["ask", "Task"])
        assert args.crux_cards is False

    def test_parse_serve_command(self, parser):
        """Should parse serve command with defaults."""
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.ws_port == 8765
        assert args.api_port == 8080
        assert args.host == "localhost"

    def test_parse_serve_custom_ports(self, parser):
        """Should parse serve with custom ports."""
        args = parser.parse_args(["serve", "--ws-port", "9000", "--api-port", "9001"])
        assert args.ws_port == 9000
        assert args.api_port == 9001

    def test_parse_global_db_option(self, parser):
        """Should parse global db option."""
        args = parser.parse_args(["--db", "custom.db", "stats"])
        assert args.db == "custom.db"

    def test_parse_verbose_flag(self, parser):
        """Should parse verbose flag."""
        args = parser.parse_args(["-v", "stats"])
        assert args.verbose is True


class TestPlansExecuteParser:
    """Tests for plans execute parser options."""

    @staticmethod
    def _build_plans_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        cli_parser._add_plans_parser(subparsers)
        return parser

    def test_parse_plans_execute_allows_fabric_mode(self):
        parser = self._build_plans_parser()
        args = parser.parse_args(["plans", "execute", "plan_123", "--execution-mode", "fabric"])
        assert args.command == "plans"
        assert args.plans_action == "execute"
        assert args.execution_mode == "fabric"

    def test_parse_plans_execute_fabric_flag(self):
        parser = self._build_plans_parser()
        args = parser.parse_args(["plans", "execute", "plan_123", "--fabric"])
        assert args.command == "plans"
        assert args.plans_action == "execute"
        assert args.fabric is True


# =============================================================================
# Command Handler Tests
# =============================================================================


class TestCommandHandlers:
    """Tests for command handler functions."""

    def test_cmd_ask_runs_debate(self, monkeypatch):
        """Should run debate with parsed arguments."""
        from aragora.cli.main import cmd_ask

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        args = argparse.Namespace(
            task="Test task",
            agents="codex,claude",
            rounds=2,
            consensus="majority",
            context="",
            learn=False,
            db="test.db",
            verbose=False,
            demo=False,
            post_consensus_quality=False,
        )

        with patch("aragora.cli.commands.debate._is_server_available", return_value=False):
            with patch("aragora.cli.commands.debate.asyncio.run") as mock_run:
                mock_result = MagicMock()
                mock_result.final_answer = "Test answer"
                mock_result.dissenting_views = []
                mock_run.return_value = mock_result

                cmd_ask(args)

                mock_run.assert_called_once()

    def test_cmd_ask_exits_when_selected_agent_provider_is_missing(self, monkeypatch, capsys):
        """Should fail before debate when any selected provider cannot be configured."""
        from aragora.cli.main import cmd_ask

        monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
        monkeypatch.setenv("GROK_API_KEY", "test-grok-key")
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        args = argparse.Namespace(
            task="Test task",
            agents="grok,mistral",
            rounds=1,
            consensus="majority",
            context="",
            learn=False,
            db="test.db",
            verbose=False,
            demo=False,
            post_consensus_quality=False,
        )

        with patch("aragora.cli.commands.debate._is_server_available", return_value=False):
            with pytest.raises(SystemExit) as exc:
                cmd_ask(args)

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "selected agent providers are not configured" in captured.err
        assert "mistral" in captured.err
        assert "aragora validate-env --smoke --agents grok,mistral --verbose" in captured.err

    def test_cmd_ask_exits_when_all_agents_return_failure_placeholders(self, monkeypatch, capsys):
        """Provider smoke should fail when autonomic placeholders are the only output."""
        from aragora.cli.main import cmd_ask

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        args = argparse.Namespace(
            task="Test task",
            agents="openai",
            rounds=1,
            consensus="majority",
            context="",
            learn=False,
            db="test.db",
            verbose=False,
            demo=False,
            post_consensus_quality=False,
        )
        mock_result = MagicMock()
        mock_result.final_answer = "A wild bug appeared! openai is handling it."
        mock_result.proposals = {"openai_proposer": "A wild bug appeared! openai is handling it."}

        with patch("aragora.cli.commands.debate._is_server_available", return_value=False):
            with patch(
                "aragora.cli.commands.debate.run_debate",
                new=AsyncMock(return_value=mock_result),
            ):
                with pytest.raises(SystemExit) as exc:
                    cmd_ask(args)

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "all selected agents returned provider/error placeholders" in captured.err
        assert "aragora validate-env --smoke --agents openai --verbose" in captured.err

    def test_agent_failure_detection_keeps_mixed_successful_debates(self):
        """A valid response from any agent keeps graceful degradation semantics."""
        from aragora.cli.commands.debate import _result_has_only_agent_failure_outputs

        result = MagicMock()
        result.final_answer = "Valid synthesis"
        result.proposals = {
            "gemini_proposer": "A wild bug appeared! gemini is handling it.",
            "openai_critic": "A concrete answer from a live provider.",
        }

        assert _result_has_only_agent_failure_outputs(result) is False

    def test_cmd_stats_shows_statistics(self):
        """Should display memory statistics."""
        from aragora.cli.main import cmd_stats

        args = argparse.Namespace(db="test.db")

        mock_store = MagicMock()
        mock_store.get_stats.return_value = {
            "total_debates": 10,
            "consensus_debates": 8,
            "total_critiques": 50,
            "total_patterns": 25,
            "avg_consensus_confidence": 0.75,
            "patterns_by_type": {"security": 5, "performance": 3},
        }

        with patch("aragora.cli.commands.stats.CritiqueStore", return_value=mock_store):
            cmd_stats(args)

            mock_store.get_stats.assert_called_once()

    def test_cmd_patterns_retrieves_patterns(self):
        """Should retrieve and display patterns."""
        from aragora.cli.main import cmd_patterns

        args = argparse.Namespace(
            db="test.db",
            type=None,
            min_success=1,
            limit=10,
        )

        mock_store = MagicMock()
        mock_pattern = MagicMock()
        mock_pattern.issue_type = "security"
        mock_pattern.success_count = 5
        mock_pattern.avg_severity = 0.6
        mock_pattern.issue_text = "SQL injection vulnerability"
        mock_pattern.suggestion_text = "Use parameterized queries"
        mock_store.retrieve_patterns.return_value = [mock_pattern]

        with patch("aragora.cli.commands.stats.CritiqueStore", return_value=mock_store):
            cmd_patterns(args)

            mock_store.retrieve_patterns.assert_called_once_with(
                issue_type=None,
                min_success=1,
                limit=10,
            )

    def test_cmd_demo_runs_demo_debate(self):
        """Should run demo debate."""
        from aragora.cli.main import cmd_demo

        args = argparse.Namespace(name="rate-limiter")

        with patch("aragora.cli.demo.main") as mock_demo_main:
            mock_demo_main.return_value = None

            cmd_demo(args)

            mock_demo_main.assert_called_once_with(args)

    def test_cmd_demo_unknown_name(self, capsys):
        """Should report unknown demo name."""
        from aragora.cli.main import cmd_demo

        args = argparse.Namespace(name="unknown")
        cmd_demo(args)

        captured = capsys.readouterr()
        assert "Unknown demo" in captured.out


# =============================================================================
# Demo Tasks Tests
# =============================================================================


class TestDemoTasks:
    """Tests for demo task configurations."""

    def test_rate_limiter_demo_exists(self):
        """Should have rate-limiter demo defined."""
        # Access demo tasks by reading the function code structure
        from aragora.cli import main

        # The demo tasks are defined in cmd_demo
        assert hasattr(main, "cmd_demo")

    def test_auth_demo_exists(self):
        """Should have auth demo defined."""
        from aragora.cli.main import cmd_demo

        args = argparse.Namespace(name="auth")

        with patch("aragora.cli.demo.main") as mock_demo_main:
            mock_demo_main.return_value = None

            cmd_demo(args)
            # If it gets here without error, demo exists
            assert mock_demo_main.called

    def test_cache_demo_exists(self):
        """Should have cache demo defined."""
        from aragora.cli.main import cmd_demo

        args = argparse.Namespace(name="cache")

        with patch("aragora.cli.demo.main") as mock_demo_main:
            mock_demo_main.return_value = None

            cmd_demo(args)
            assert mock_demo_main.called


# =============================================================================
# Main Entry Point Tests
# =============================================================================


class TestMain:
    """Tests for main entry point."""

    def test_main_registers_webhook_store_before_normal_cli_initialization(self, monkeypatch):
        """Normal CLI startup should register durable webhook storage first."""
        order: list[str] = []
        fake_args = argparse.Namespace(
            command="status",
            verbose=False,
            func=lambda _args: order.append("command"),
        )
        fake_parser = Mock()
        fake_parser.parse_args.return_value = fake_args

        monkeypatch.setattr("aragora.cli.main._try_review_queue_fast_path", lambda _argv: None)
        monkeypatch.setattr(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            lambda: order.append("webhook_store"),
        )
        monkeypatch.setattr(
            "aragora.modes.register_all_builtins",
            lambda: order.append("modes"),
        )
        monkeypatch.setattr("aragora.cli.parser.build_parser", lambda: fake_parser)
        monkeypatch.setattr("aragora.cli.main._hydrate_startup_secrets", lambda: None)

        assert main() == 0
        assert order == ["webhook_store", "modes", "command"]

    def test_main_review_queue_fast_path_skips_webhook_store_registration(self, monkeypatch):
        """The lightweight review-queue path should remain registration-free."""
        register_webhook_store = Mock()
        monkeypatch.setattr(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            register_webhook_store,
        )
        monkeypatch.setattr("aragora.cli.main._try_review_queue_fast_path", lambda _argv: 17)

        assert main() == 17
        register_webhook_store.assert_not_called()

    def test_review_queue_build_accepts_repo_override(self):
        parser = cli_parser.build_parser()
        args = parser.parse_args(
            ["review-queue", "build", "--repo", "synaptent/aragora", "--limit", "7"]
        )

        assert args.command == "review-queue"
        assert args.review_queue_command == "build"
        assert args.repo == "synaptent/aragora"
        assert args.limit == 7

    def test_record_settlement_skips_startup_secret_hydration(self):
        """Receipt-only settlement recording should not need provider secrets."""
        parser = cli_parser.build_parser()
        args = parser.parse_args(
            [
                "review-queue",
                "record-settlement",
                "7495",
                "--head-sha",
                "017d33990628ed8a3369dfb600cafcc0a6548bc7",
                "--action",
                "admin_squash_merge",
                "--reason",
                "post-merge receipt",
            ]
        )

        assert _should_hydrate_startup_secrets(args) is False

    def test_model_command_keeps_startup_secret_hydration(self):
        """Commands that may invoke model providers keep startup hydration."""
        parser = cli_parser.build_parser()
        args = parser.parse_args(["ask", "Design a rate limiter"])

        assert _should_hydrate_startup_secrets(args) is True

    def test_main_record_settlement_does_not_hydrate_secrets(self, monkeypatch):
        """The main entry point should skip AWS/local secret stores for receipts."""
        fake_args = argparse.Namespace(
            command="review-queue",
            review_queue_command="record-settlement",
            verbose=False,
            func=lambda _args: 0,
        )
        fake_parser = Mock()
        fake_parser.parse_args.return_value = fake_args

        def _unexpected_hydration(*_args, **_kwargs):
            raise AssertionError("record-settlement should not hydrate startup secrets")

        monkeypatch.setattr("aragora.cli.main._try_review_queue_fast_path", lambda _argv: None)
        monkeypatch.setattr(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            lambda: None,
        )
        monkeypatch.setattr("aragora.cli.parser.build_parser", lambda: fake_parser)
        monkeypatch.setattr("aragora.modes.register_all_builtins", lambda: None)
        monkeypatch.setattr(
            "aragora.config.secrets.hydrate_env_from_secrets",
            _unexpected_hydration,
        )
        monkeypatch.setattr(
            "aragora.cli.api_keys.hydrate_env_from_secure_store",
            _unexpected_hydration,
        )

        assert main() == 0

    def test_main_no_command_shows_help(self, capsys):
        """Should show help when no command provided."""
        with patch("sys.argv", ["agora"]):
            main()
            captured = capsys.readouterr()
            # Help output goes to stdout
            assert "usage" in captured.out.lower() or captured.out == ""

    def test_main_calls_command_func(self):
        """Should call the appropriate command function."""
        with patch("sys.argv", ["agora", "stats"]):
            with patch("aragora.cli.commands.stats.CritiqueStore") as mock_store:
                mock_store.return_value.get_stats.return_value = {
                    "total_debates": 0,
                    "consensus_debates": 0,
                    "total_critiques": 0,
                    "total_patterns": 0,
                    "avg_consensus_confidence": 0.0,
                    "patterns_by_type": {},
                }
                main()
                mock_store.assert_called_once()


# =============================================================================
# Run Debate Tests
# =============================================================================


class TestRunDebate:
    """Tests for run_debate async function."""

    @pytest.mark.asyncio
    async def test_run_debate_creates_agents(self):
        """Should create agents from specification."""
        from aragora.cli.main import run_debate

        with patch("aragora.cli.commands.debate.create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_create.return_value = mock_agent

            with patch("aragora.cli.commands.debate.Arena") as mock_arena:
                mock_result = MagicMock()
                mock_arena.return_value.run = AsyncMock(return_value=mock_result)

                await run_debate(
                    task="Test",
                    agents_str="codex,claude",
                    rounds=2,
                    learn=False,
                )

                # Should create 2 agents
                assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_run_debate_assigns_default_roles(self):
        """Should assign default roles to agents."""
        from aragora.cli.main import run_debate

        created_agents = []

        def track_create(*args, **kwargs):
            agent = MagicMock()
            agent.name = kwargs.get("name")
            created_agents.append(kwargs)
            return agent

        with patch("aragora.cli.commands.debate.create_agent", side_effect=track_create):
            with patch("aragora.cli.commands.debate.Arena") as mock_arena:
                mock_result = MagicMock()
                mock_arena.return_value.run = AsyncMock(return_value=mock_result)

                await run_debate(
                    task="Test",
                    agents_str="claude,gemini,openai",  # Use valid provider names
                    rounds=2,
                    learn=False,
                )

                # First should be proposer, last should be synthesizer
                assert created_agents[0]["role"] == "proposer"
                assert created_agents[2]["role"] == "synthesizer"

    @pytest.mark.asyncio
    async def test_run_debate_uses_critique_store(self):
        """Should use CritiqueStore when learn=True."""
        from aragora.cli.main import run_debate

        store = MagicMock()

        with patch("aragora.cli.commands.debate.create_agent") as mock_create:
            mock_create.return_value = MagicMock()

            with patch("aragora.cli.commands.debate.Arena") as mock_arena:
                mock_result = MagicMock()
                mock_arena.return_value.run = AsyncMock(return_value=mock_result)

                with patch(
                    "aragora.cli.commands.debate.CritiqueStore", return_value=store
                ) as mock_store:
                    await run_debate(
                        task="Test",
                        agents_str="codex",
                        rounds=1,
                        learn=True,
                        db_path="test.db",
                    )

                    mock_store.assert_called_once_with("test.db")
                    store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_debate_closes_critique_store_on_failure(self):
        """Should close CritiqueStore even when Arena.run() fails."""
        from aragora.cli.main import run_debate

        store = MagicMock()

        with patch("aragora.cli.commands.debate.create_agent") as mock_create:
            mock_create.return_value = MagicMock()

            with patch("aragora.cli.commands.debate.Arena") as mock_arena:
                mock_arena.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))

                with patch("aragora.cli.commands.debate.CritiqueStore", return_value=store):
                    with pytest.raises(RuntimeError, match="boom"):
                        await run_debate(
                            task="Test",
                            agents_str="codex",
                            rounds=1,
                            learn=True,
                            db_path="test.db",
                        )

                    store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_debate_disables_calibration_offline(self):
        """Should fail closed on calibration-backed learning in offline mode."""
        from aragora.cli.main import run_debate

        with patch("aragora.cli.commands.debate.create_agent") as mock_create:
            mock_create.return_value = MagicMock()

            with patch("aragora.cli.commands.debate.Arena") as mock_arena:
                mock_result = MagicMock()
                mock_arena.return_value.run = AsyncMock(return_value=mock_result)

                await run_debate(
                    task="Test",
                    agents_str="codex,claude",
                    rounds=2,
                    learn=False,
                    offline=True,
                )

                protocol = mock_arena.call_args.args[2]
                assert protocol.enable_calibration is False


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_parse_agents_single_colon(self):
        """Agent with single colon - empty second part treated as persona."""
        result = parse_agents("claude:")
        assert len(result) == 1
        assert result[0].provider == "claude"
        # Empty string is not a valid role, role is None
        assert result[0].role is None

    def test_parse_agents_multiple_colons(self):
        """Multiple colons - 'role:extra' not a valid role."""
        result = parse_agents("claude:role:extra")
        assert len(result) == 1
        assert result[0].provider == "claude"
        # 'role:extra' is not a valid role, treated as persona
        assert result[0].persona == "role:extra"
        assert result[0].role is None

    def test_cmd_templates_import(self):
        """Should import templates module."""
        from aragora.cli.main import cmd_templates

        args = argparse.Namespace()

        with patch("aragora.templates.list_templates") as mock_list:
            mock_list.return_value = [
                {
                    "type": "debate",
                    "name": "Test",
                    "description": "Test template",
                    "agents": "a,b",
                    "domain": "test",
                }
            ]
            cmd_templates(args)
            mock_list.assert_called_once()


# =============================================================================
# Serve Command Tests
# =============================================================================


class TestServeCommand:
    """Tests for serve command."""

    def test_cmd_serve_starts_server(self):
        """Should start unified server."""
        from aragora.cli.main import cmd_serve

        args = argparse.Namespace(
            ws_port=8765,
            api_port=8080,
            host="localhost",
        )

        with patch("aragora.server.unified_server.run_unified_server") as mock_server:
            with patch("asyncio.run") as mock_run:
                mock_run.side_effect = KeyboardInterrupt()

                cmd_serve(args)

                # Should have been called
                mock_run.assert_called()
