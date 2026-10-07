"""Flag-gate tests for the crux_finder consensus mode (DIC-15 / #6025).

These tests verify that ``ARAGORA_CRUX_FINDER_ENABLED`` (default off) guards
the crux_finder consensus path and that a missing flag raises
``CruxFinderDisabledError`` before execution without falling back to majority.

All tests are deterministic and require no live agents, no Arena, and no
network access.
"""

from __future__ import annotations

import os

import pytest

from aragora.debate.crux_mode import (
    CRUX_FINDER_ENV_VAR,
    CruxFinderDisabledError,
    crux_finder_enabled,
    enable_crux_finder,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the flag through monkeypatch so direct writes are restored."""
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, "0")


# ---------------------------------------------------------------------------
# 1. Flag helpers
# ---------------------------------------------------------------------------


def test_flag_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``crux_finder_enabled()`` must return False when the env var is absent."""
    monkeypatch.delenv(CRUX_FINDER_ENV_VAR)
    assert not crux_finder_enabled()


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "YES", "ON"])
def test_flag_truthy_values(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, value)
    assert crux_finder_enabled()


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  ", "2"])
def test_flag_falsy_values(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, value)
    assert not crux_finder_enabled()


def test_enable_function_activates_flag() -> None:
    """``enable_crux_finder()`` must flip ``crux_finder_enabled()`` to True."""
    assert not crux_finder_enabled()
    enable_crux_finder()
    assert crux_finder_enabled()


def test_enable_function_environment_write_is_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scoped monkeypatch restores direct writes made by the enable helper."""
    monkeypatch.setenv(CRUX_FINDER_ENV_VAR, "external-value")

    with monkeypatch.context() as scoped:
        scoped.setenv(CRUX_FINDER_ENV_VAR, "0")
        enable_crux_finder()
        assert crux_finder_enabled()

    assert os.environ[CRUX_FINDER_ENV_VAR] == "external-value"


def test_env_var_name_is_stable() -> None:
    """Constant must not drift — downstream tooling hard-codes this name."""
    assert CRUX_FINDER_ENV_VAR == "ARAGORA_CRUX_FINDER_ENABLED"


def test_flag_symbols_exported_in_all() -> None:
    """All three gate symbols must be in ``__all__`` for clean star-imports."""
    import aragora.debate.crux_mode as mod

    assert "CRUX_FINDER_ENV_VAR" in mod.__all__
    assert "crux_finder_enabled" in mod.__all__
    assert "enable_crux_finder" in mod.__all__


# ---------------------------------------------------------------------------
# 2. Consensus-phase flag-off failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_raises_typed_error_without_majority_fallback() -> None:
    """A disabled explicit mode request must not silently produce a verdict."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aragora.debate.phases.consensus_phase import ConsensusPhase
    from aragora.protocols.debate import DebateProtocol

    protocol = DebateProtocol(consensus="crux_finder")
    result = SimpleNamespace(
        debate_id="d-flag-off",
        rounds_used=0,
        consensus_proof=None,
        consensus_reached=None,
        final_answer=None,
        consensus_strength=None,
        formal_verification=None,
        metadata={},
    )
    ctx = SimpleNamespace(
        env=SimpleNamespace(task="Should the flag gate work?"),
        agents=[SimpleNamespace(name="demo")],
        result=result,
        debate_id="d-flag-off",
        belief_network=None,
    )

    phase = ConsensusPhase.__new__(ConsensusPhase)
    phase.protocol = protocol
    phase._notify_spectator = None
    phase.hooks = {}
    phase._handle_majority_consensus = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(CruxFinderDisabledError, match=CRUX_FINDER_ENV_VAR):
        await phase._execute_consensus(ctx, "crux_finder")  # type: ignore[arg-type]

    phase._handle_majority_consensus.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_off_error_escapes_consensus_phase() -> None:
    """The phase wrapper must preserve the typed error for library callers."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aragora.debate.phases.consensus_phase import ConsensusPhase
    from aragora.protocols.debate import DebateProtocol

    protocol = DebateProtocol(consensus="crux_finder")
    result = SimpleNamespace(
        debate_id="d-no-proof",
        rounds_used=0,
        consensus_proof=None,
        consensus_reached=None,
        final_answer=None,
        consensus_strength=None,
        formal_verification=None,
        metadata={},
    )
    ctx = SimpleNamespace(
        env=SimpleNamespace(task="q"),
        agents=[],
        proposals={},
        result=result,
        debate_id="d-no-proof",
        belief_network=None,
        cancellation_token=None,
        hook_manager=None,
    )

    phase = ConsensusPhase.__new__(ConsensusPhase)
    phase.protocol = protocol
    phase._notify_spectator = None
    phase.hooks = {}
    phase._handle_majority_consensus = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(CruxFinderDisabledError, match=CRUX_FINDER_ENV_VAR):
        await phase.execute(ctx)  # type: ignore[arg-type]

    phase._handle_majority_consensus.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_off_arena_fails_before_debate_execution() -> None:
    """Library callers must fail before any provider-backed debate work starts."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aragora.debate.orchestrator import Arena

    arena = Arena.__new__(Arena)
    arena.protocol = SimpleNamespace(consensus="crux_finder")
    arena._run_inner = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(CruxFinderDisabledError, match=CRUX_FINDER_ENV_VAR):
        await arena.run()

    arena._run_inner.assert_not_awaited()
