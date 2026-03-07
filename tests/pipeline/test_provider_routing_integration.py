"""Test ProviderRouter integration in UnifiedOrchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    UnifiedOrchestrator,
)


@pytest.fixture
def mock_arena_factory():
    result = MagicMock()
    result.final_answer = "Use approach A"
    result.participants = ["agent-claude", "agent-gpt"]
    result.consensus_reached = True
    result.metadata = {}
    return AsyncMock(return_value=result)


@pytest.fixture
def mock_provider_router():
    router = MagicMock()
    router.select_providers_for_debate.return_value = [
        "claude-sonnet-4",
        "gpt-4o",
        "deepseek-r1",
    ]
    return router


@pytest.mark.asyncio
async def test_provider_router_selects_before_debate(mock_arena_factory, mock_provider_router):
    """ProviderRouter selections are passed to arena_factory."""
    orch = UnifiedOrchestrator(
        arena_factory=mock_arena_factory,
        provider_router=mock_provider_router,
    )

    result = await orch.run("Design a rate limiter")

    # Router was called
    mock_provider_router.select_providers_for_debate.assert_called_once()

    # Arena factory received provider hints
    call_kwargs = mock_arena_factory.call_args
    assert call_kwargs is not None
    assert "provider_hints" in (call_kwargs.kwargs or {})


@pytest.mark.asyncio
async def test_provider_router_records_outcome(mock_arena_factory, mock_provider_router):
    """After debate, outcomes are recorded back to the router."""
    orch = UnifiedOrchestrator(
        arena_factory=mock_arena_factory,
        provider_router=mock_provider_router,
    )

    await orch.run("Design a rate limiter")

    # Outcome is recorded against provider IDs, not agent display names.
    recorded = [call.args[0] for call in mock_provider_router.record_outcome.call_args_list]
    assert recorded == ["claude-sonnet-4", "gpt-4o", "deepseek-r1"]


@pytest.mark.asyncio
async def test_provider_router_does_not_break_factory_without_provider_hints_kwarg(
    mock_provider_router,
):
    """Factories that don't accept provider_hints still run successfully."""

    async def arena_factory(
        prompt: str,
        agents=None,
        rounds: int = 3,
        agent_count: int = 3,
        consensus_threshold: float = 0.6,
    ):
        result = MagicMock()
        result.final_answer = "Use approach A"
        result.participants = ["agent-claude", "agent-gpt"]
        result.consensus_reached = True
        result.metadata = {}
        return result

    orch = UnifiedOrchestrator(
        arena_factory=arena_factory,
        provider_router=mock_provider_router,
    )

    result = await orch.run("Design a rate limiter")

    assert "debate" in result.stages_completed
    assert result.errors == []


@pytest.mark.asyncio
async def test_no_router_no_change(mock_arena_factory):
    """Without a provider_router, debate runs as normal."""
    orch = UnifiedOrchestrator(arena_factory=mock_arena_factory)
    result = await orch.run("Design a rate limiter")

    assert "debate" in result.stages_completed
