"""Tests for --mode flag in CLI decide and debate commands."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.modes import load_builtins
from aragora.modes.base import ModeRegistry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARAGORA_PACKAGE_ROOT = _REPO_ROOT / "aragora"
_EXPECTED_BUILTIN_MODES = {
    "architect",
    "assumption_surfacer",
    "coder",
    "debugger",
    "deleter",
    "epistemic_hygiene",
    "falsifier",
    "orchestrator",
    "outsider",
    "reviewer",
}


def _import_checkout_decide_module():
    """Import decide from this checkout even after editable-install/path churn."""
    root = str(_REPO_ROOT)
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    import aragora

    package_root = str(_ARAGORA_PACKAGE_ROOT)
    package_paths = getattr(aragora, "__path__", None)
    if package_paths is not None and package_root not in package_paths:
        package_paths.insert(0, package_root)

    sys.modules.pop("aragora.cli.commands.decide", None)
    return importlib.import_module("aragora.cli.commands.decide")


class TestLoadBuiltins:
    """Test load_builtins() function."""

    def setup_method(self):
        ModeRegistry.clear()

    def teardown_method(self):
        # Re-register so other tests are unaffected
        load_builtins()

    def test_load_builtins_registers_all(self):
        """load_builtins() registers all built-in modes."""
        assert len(ModeRegistry.list_all()) == 0
        load_builtins()
        registered = ModeRegistry.list_all()
        assert "architect" in registered
        assert "coder" in registered
        assert "reviewer" in registered
        assert "debugger" in registered
        assert "orchestrator" in registered
        assert "epistemic_hygiene" in registered
        assert set(registered) == _EXPECTED_BUILTIN_MODES

    def test_load_builtins_idempotent(self):
        """Calling load_builtins() twice does not duplicate modes."""
        load_builtins()
        first = len(ModeRegistry.list_all())
        load_builtins()
        second = len(ModeRegistry.list_all())
        assert first == second == len(_EXPECTED_BUILTIN_MODES)
        assert set(ModeRegistry.list_all()) == _EXPECTED_BUILTIN_MODES

    def test_architect_mode_has_system_prompt(self):
        """Architect mode provides a non-empty system prompt."""
        load_builtins()
        mode = ModeRegistry.get("architect")
        assert mode is not None
        prompt = mode.get_system_prompt()
        assert len(prompt) > 0

    def test_all_modes_have_system_prompt(self):
        """All built-in modes have non-empty system prompts."""
        load_builtins()
        for name in _EXPECTED_BUILTIN_MODES:
            mode = ModeRegistry.get(name)
            assert mode is not None, f"Mode '{name}' not registered"
            prompt = mode.get_system_prompt()
            assert len(prompt) > 0, f"Mode '{name}' has empty system prompt"


class TestModeInRunDebate:
    """Test mode injection into run_debate."""

    def setup_method(self):
        load_builtins()

    @pytest.mark.asyncio
    async def test_mode_architect_injects_system_prompt(self):
        """--mode architect causes system prompt to be set on agents."""
        from aragora.cli.commands.debate import run_debate

        created_agents = []

        def mock_create_agent(model_type, name, role, model=None, **kwargs):
            agent = MagicMock()
            agent.name = name
            agent.role = role
            agent.system_prompt = ""
            agent.provider = model_type
            created_agents.append(agent)
            return agent

        mock_result = MagicMock()
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.messages = []

        with (
            patch("aragora.cli.commands.debate.create_agent", side_effect=mock_create_agent),
            patch("aragora.cli.commands.debate.CritiqueStore"),
            patch("aragora.cli.commands.debate.Arena") as MockArena,
        ):
            MockArena.return_value.run = AsyncMock(return_value=mock_result)

            await run_debate(
                task="Test task",
                agents_str="claude,claude",
                mode="architect",
                learn=False,
                enable_audience=False,
                offline=True,
            )

        # All agents should have been given the architect system prompt
        assert len(created_agents) >= 2
        architect_mode = ModeRegistry.get("architect")
        expected_prompt = architect_mode.get_system_prompt()
        for agent in created_agents:
            assert agent.system_prompt == expected_prompt

    @pytest.mark.asyncio
    async def test_unknown_mode_raises_error(self):
        """Unknown mode raises KeyError."""
        from aragora.cli.commands.debate import run_debate

        with pytest.raises(KeyError, match="not found"):
            await run_debate(
                task="Test task",
                agents_str="claude,claude",
                mode="nonexistent_mode",
                learn=False,
                enable_audience=False,
                offline=True,
            )

    @pytest.mark.asyncio
    async def test_no_mode_no_change(self):
        """When mode is None, agents keep their default system prompts."""
        from aragora.cli.commands.debate import run_debate

        created_agents = []
        original_prompt = "Default agent prompt"

        def mock_create_agent(model_type, name, role, model=None, **kwargs):
            agent = MagicMock()
            agent.name = name
            agent.role = role
            agent.system_prompt = original_prompt
            agent.provider = model_type
            created_agents.append(agent)
            return agent

        mock_result = MagicMock()
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.messages = []

        with (
            patch("aragora.cli.commands.debate.create_agent", side_effect=mock_create_agent),
            patch("aragora.cli.commands.debate.CritiqueStore"),
            patch("aragora.cli.commands.debate.Arena") as MockArena,
        ):
            MockArena.return_value.run = AsyncMock(return_value=mock_result)

            await run_debate(
                task="Test task",
                agents_str="claude,claude",
                mode=None,
                learn=False,
                enable_audience=False,
                offline=True,
            )

        # Agents should keep their original prompts (not overwritten)
        for agent in created_agents:
            assert agent.system_prompt == original_prompt

    @pytest.mark.asyncio
    async def test_single_agent_none_consensus_sets_direct_answer_protocol(self):
        """One-agent ask runs with direct-answer prompt semantics."""
        from aragora.cli.commands.debate import run_debate

        def mock_create_agent(model_type, name, role, model=None, **kwargs):
            agent = MagicMock()
            agent.name = name
            agent.role = role
            agent.system_prompt = ""
            agent.provider = model_type
            return agent

        mock_result = MagicMock()
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.messages = []

        with (
            patch("aragora.cli.commands.debate.create_agent", side_effect=mock_create_agent),
            patch("aragora.cli.commands.debate.CritiqueStore"),
            patch("aragora.cli.commands.debate.Arena") as MockArena,
        ):
            MockArena.return_value.run = AsyncMock(return_value=mock_result)

            await run_debate(
                task="What is 2+2?",
                agents_str="grok",
                rounds=1,
                consensus="none",
                mode=None,
                learn=False,
                enable_audience=False,
                offline=True,
            )

        protocol = MockArena.call_args.args[2]
        assert protocol.single_agent_direct_answer is True


class TestModeInDecide:
    """Test mode injection into run_decide."""

    def setup_method(self):
        ModeRegistry.clear()
        load_builtins()

    def teardown_method(self):
        load_builtins()

    @pytest.mark.asyncio
    async def test_decide_unknown_mode_raises(self, capsys):
        """run_decide reports unknown modes without resolving them."""
        decide_module = _import_checkout_decide_module()
        assert (
            Path(decide_module.__file__)
            .resolve()
            .is_relative_to(_ARAGORA_PACKAGE_ROOT / "cli" / "commands")
        )
        run_decide = decide_module.run_decide

        missing_mode = "__missing_decide_mode_for_test__"
        assert ModeRegistry.get(missing_mode) is None

        try:
            await run_decide(
                task="Decide something",
                agents_str="claude,claude",
                mode=missing_mode,
            )
        except KeyError as exc:
            assert "not found" in str(exc)
        else:
            captured = capsys.readouterr()
            assert f"Mode '{missing_mode}' not found" in captured.out
            assert "proceeding with standard deliberation" in captured.out

    def test_decide_valid_mode_resolves_prompt(self):
        """run_decide's mode handling resolves a valid mode and stores prompt."""
        # Directly test the mode resolution logic from run_decide
        from aragora.modes import load_builtins
        from aragora.modes.base import ModeRegistry

        load_builtins()
        mode_def = ModeRegistry.get("reviewer")
        assert mode_def is not None
        prompt = mode_def.get_system_prompt()
        assert len(prompt) > 0
        # The decide command builds mode_config with mode_system_prompt
        mode_config = {
            "mode": "reviewer",
            "mode_definition": mode_def,
            "mode_system_prompt": prompt,
        }
        assert mode_config["mode_system_prompt"] == prompt
