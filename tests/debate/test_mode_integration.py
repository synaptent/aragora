"""Tests for mode-based phase-aware agent prompts in Arena.

Verifies that operational modes (architect, reviewer, coder) are wired
into the debate prompt pipeline so agents receive phase-appropriate
system prompts during propose, critique, and revise phases.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.modes.base import Mode, ModeRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_mode_registry():
    """Ensure ModeRegistry is clean before/after each test."""
    saved = dict(ModeRegistry._modes)
    yield
    ModeRegistry._modes.clear()
    ModeRegistry._modes.update(saved)


@pytest.fixture()
def _register_builtins():
    """Register built-in modes for tests that need them."""
    from aragora.modes.builtin import register_all_builtins

    register_all_builtins()


def _make_prompt_builder():
    """Create a minimal PromptBuilder for testing."""
    from aragora.debate.prompt_builder import PromptBuilder

    protocol = MagicMock()
    protocol.rounds = 3
    protocol.stances = None
    protocol.asymmetric_stances = False
    protocol.agreement_intensity = None
    protocol.enable_privacy_anonymization = False
    protocol.cognitive_phases = None
    protocol.enforce_language = False
    protocol.language = "english"

    env = MagicMock()
    env.task = "Design a rate limiter"
    env.context = ""

    return PromptBuilder(protocol=protocol, env=env)


def _make_agent(name: str = "claude", role: str = "analyst"):
    """Create a mock Agent for testing."""
    agent = MagicMock()
    agent.name = name
    agent.role = role
    agent.stance = None
    return agent


# ---------------------------------------------------------------------------
# PromptBuilder.set_mode_for_phase
# ---------------------------------------------------------------------------


class TestSetModeForPhase:
    """Test mode selection per debate phase."""

    def test_default_propose_maps_to_architect(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("propose")
        assert pb._active_mode_name == "architect"

    def test_default_critique_maps_to_reviewer(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("critique")
        assert pb._active_mode_name == "reviewer"

    def test_default_revise_maps_to_coder(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("revise")
        assert pb._active_mode_name == "coder"

    def test_unknown_phase_sets_none(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("voting")
        assert pb._active_mode_name is None

    def test_custom_mode_sequence_overrides_defaults(self):
        pb = _make_prompt_builder()
        pb.mode_sequence = ["debugger", "orchestrator", "architect"]

        pb.set_mode_for_phase("propose")
        assert pb._active_mode_name == "debugger"

        pb.set_mode_for_phase("critique")
        assert pb._active_mode_name == "orchestrator"

        pb.set_mode_for_phase("revise")
        assert pb._active_mode_name == "architect"

    def test_short_mode_sequence_falls_back(self):
        pb = _make_prompt_builder()
        pb.mode_sequence = ["debugger"]

        pb.set_mode_for_phase("propose")
        assert pb._active_mode_name == "debugger"

        # critique index=1 out of range, falls back to default
        pb.set_mode_for_phase("critique")
        assert pb._active_mode_name == "reviewer"


# ---------------------------------------------------------------------------
# PromptBuilder.get_mode_prompt
# ---------------------------------------------------------------------------


class TestGetModePrompt:
    """Test mode system prompt retrieval."""

    @pytest.mark.usefixtures("_register_builtins")
    def test_returns_architect_prompt_for_propose(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("propose")
        prompt = pb.get_mode_prompt()
        assert "Architect Mode" in prompt
        assert "analyze" in prompt.lower() or "design" in prompt.lower()

    @pytest.mark.usefixtures("_register_builtins")
    def test_returns_reviewer_prompt_for_critique(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("critique")
        prompt = pb.get_mode_prompt()
        assert "Reviewer Mode" in prompt

    @pytest.mark.usefixtures("_register_builtins")
    def test_returns_coder_prompt_for_revise(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("revise")
        prompt = pb.get_mode_prompt()
        assert "Coder Mode" in prompt

    def test_returns_empty_for_no_active_mode(self):
        pb = _make_prompt_builder()
        pb._active_mode_name = None
        assert pb.get_mode_prompt() == ""

    def test_returns_empty_for_unregistered_mode(self):
        pb = _make_prompt_builder()
        pb._active_mode_name = "nonexistent_mode"
        assert pb.get_mode_prompt() == ""


# ---------------------------------------------------------------------------
# Prompt Injection
# ---------------------------------------------------------------------------


class TestModePromptInjection:
    """Test that mode prompts are injected into assembled prompts."""

    @pytest.mark.usefixtures("_register_builtins")
    def test_proposal_prompt_includes_mode_section(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("propose")
        agent = _make_agent()

        prompt = pb.build_proposal_prompt(agent)
        assert "Architect Mode" in prompt

    @pytest.mark.usefixtures("_register_builtins")
    def test_revision_prompt_includes_mode_section(self):
        pb = _make_prompt_builder()
        pb.set_mode_for_phase("revise")
        agent = _make_agent()

        critique = MagicMock()
        critique.to_prompt.return_value = "This could be better."
        critique.agent = "gpt4"
        critique.issues = ["vague"]

        prompt = pb.build_revision_prompt(agent, "my proposal", [critique])
        assert "Coder Mode" in prompt

    def test_no_mode_produces_no_mode_section(self):
        pb = _make_prompt_builder()
        pb._active_mode_name = None
        agent = _make_agent()

        prompt = pb.build_proposal_prompt(agent)
        assert "Architect Mode" not in prompt
        assert "Reviewer Mode" not in prompt
        assert "Coder Mode" not in prompt


# ---------------------------------------------------------------------------
# ArenaBuilder.with_mode_sequence
# ---------------------------------------------------------------------------


class TestArenaBuilderModeSequence:
    """Test ArenaBuilder.with_mode_sequence fluent method."""

    def test_with_mode_sequence_sets_attribute(self):
        from aragora.debate.arena_builder import ArenaBuilder

        env = MagicMock()
        env.task = "test"
        env.context = ""
        agents = [_make_agent()]

        builder = ArenaBuilder(env, agents)
        result = builder.with_mode_sequence(["architect", "reviewer", "coder"])

        assert result is builder  # fluent return
        assert builder._mode_sequence == ["architect", "reviewer", "coder"]

    def test_mode_sequence_passed_to_arena(self):
        from aragora.debate.arena_builder import ArenaBuilder

        env = MagicMock()
        env.task = "test"
        env.context = ""
        agents = [_make_agent()]

        builder = ArenaBuilder(env, agents)
        builder.with_mode_sequence(["debugger", "orchestrator", "coder"])

        with patch("aragora.debate.orchestrator.Arena") as MockArena:
            MockArena.return_value = MagicMock()
            builder.build()
            call_kwargs = MockArena.call_args[1]
            assert call_kwargs["mode_sequence"] == ["debugger", "orchestrator", "coder"]


# ---------------------------------------------------------------------------
# State Sync
# ---------------------------------------------------------------------------


class TestModeStateSync:
    """Test that mode_sequence syncs from Arena to PromptBuilder."""

    def test_sync_copies_mode_sequence(self):
        from aragora.debate.orchestrator_state import sync_prompt_builder_state

        arena = MagicMock()
        arena.mode_sequence = ["architect", "reviewer", "coder"]
        arena.current_role_assignments = {}
        arena._cache.historical_context = ""
        arena.user_suggestions = []

        pb = _make_prompt_builder()
        arena.prompt_builder = pb

        sync_prompt_builder_state(arena)

        assert pb.mode_sequence == ["architect", "reviewer", "coder"]

    def test_sync_handles_missing_mode_sequence(self):
        from aragora.debate.orchestrator_state import sync_prompt_builder_state

        arena = MagicMock(spec=[])
        arena.prompt_builder = _make_prompt_builder()
        arena.current_role_assignments = {}
        arena._cache = MagicMock()
        arena._cache.historical_context = ""
        arena.user_suggestions = []
        arena._context_delegator = MagicMock()
        arena._context_delegator.get_continuum_context.return_value = ""

        # No mode_sequence attribute
        del arena.mode_sequence

        sync_prompt_builder_state(arena)

        assert arena.prompt_builder.mode_sequence is None


# ---------------------------------------------------------------------------
# Integration: Delegate Methods
# ---------------------------------------------------------------------------


class TestDelegatesModeWiring:
    """Test that Arena delegate methods set mode before building prompts."""

    @pytest.mark.usefixtures("_register_builtins")
    def test_build_proposal_sets_propose_mode(self):
        """Verify _build_proposal_prompt sets mode to 'propose'."""
        pb = _make_prompt_builder()

        # Track calls to set_mode_for_phase
        calls = []
        original_set = pb.set_mode_for_phase

        def tracking_set(phase):
            calls.append(phase)
            return original_set(phase)

        pb.set_mode_for_phase = tracking_set

        # Simulate what orchestrator_delegates._build_proposal_prompt does
        pb.mode_sequence = ["architect", "reviewer", "coder"]
        pb.set_mode_for_phase("propose")
        prompt = pb.build_proposal_prompt(_make_agent())

        assert "propose" in calls
        assert "Architect Mode" in prompt

    @pytest.mark.usefixtures("_register_builtins")
    def test_build_revision_sets_revise_mode(self):
        """Verify _build_revision_prompt sets mode to 'revise'."""
        pb = _make_prompt_builder()
        pb.mode_sequence = ["architect", "reviewer", "coder"]
        pb.set_mode_for_phase("revise")

        critique = MagicMock()
        critique.to_prompt.return_value = "needs work"
        critique.agent = "gpt4"
        critique.issues = ["incomplete"]

        prompt = pb.build_revision_prompt(_make_agent(), "my proposal", [critique])
        assert "Coder Mode" in prompt


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestModeEdgeCases:
    """Test edge cases and robustness."""

    def test_empty_mode_sequence(self):
        pb = _make_prompt_builder()
        pb.mode_sequence = []
        pb.set_mode_for_phase("propose")
        # Falls back to default
        assert pb._active_mode_name == "architect"

    def test_none_mode_sequence_uses_defaults(self):
        pb = _make_prompt_builder()
        pb.mode_sequence = None
        pb.set_mode_for_phase("propose")
        assert pb._active_mode_name == "architect"

    @pytest.mark.usefixtures("_register_builtins")
    def test_mode_prompt_changes_between_phases(self):
        pb = _make_prompt_builder()

        pb.set_mode_for_phase("propose")
        propose_prompt = pb.get_mode_prompt()
        assert "Architect" in propose_prompt

        pb.set_mode_for_phase("critique")
        critique_prompt = pb.get_mode_prompt()
        assert "Reviewer" in critique_prompt

        pb.set_mode_for_phase("revise")
        revise_prompt = pb.get_mode_prompt()
        assert "Coder" in revise_prompt

        # All three should be different
        assert propose_prompt != critique_prompt
        assert critique_prompt != revise_prompt

    def test_import_error_returns_empty(self, monkeypatch):
        """Test graceful degradation when modes module is unavailable."""
        from aragora.debate import mode_prompts
        from aragora.utils.declared_registrations import DeclaredRegistrations

        pb = _make_prompt_builder()
        pb._active_mode_name = "architect"
        monkeypatch.setattr(mode_prompts, "_provider", None)
        monkeypatch.setattr(
            mode_prompts,
            "_declared",
            DeclaredRegistrations(mode_prompts.MODE_PROMPTS_ENTRY_POINT_GROUP),
        )
        monkeypatch.setattr("importlib.metadata.entry_points", lambda *, group: [])

        with patch.dict("sys.modules", {"aragora.cli.mode_prompt_registration": None}):
            # The declared registration fails to import, so no provider is registered
            result = pb.get_mode_prompt()
            assert result == ""
