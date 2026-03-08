from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock

import pytest


def test_import_path_has_no_secrets_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARAGORA_SKIP_SECRETS_HYDRATION", raising=False)
    package = importlib.import_module("aragora")
    assert package.__name__ == "aragora"
    assert "ARAGORA_SKIP_SECRETS_HYDRATION" not in os.environ


class MockAgent:
    def __init__(self, name: str, answer: str) -> None:
        self.name = name
        self.generate = AsyncMock(return_value=answer)


@pytest.fixture
def mock_agents() -> list[MockAgent]:
    agents: list[MockAgent] = []
    for name, answer in [
        ("agent_alpha", "Use a narrow review lane."),
        ("agent_beta", "Use a narrow review lane."),
    ]:
        agents.append(MockAgent(name, answer))
    return agents


@pytest.mark.asyncio
async def test_minimal_offline_debate_completes(mock_agents: list[MockAgent]) -> None:
    from aragora.core import Environment
    from aragora.debate import Arena, DebateProtocol

    env = Environment(task="How should we ship the debate package?")
    protocol = DebateProtocol(rounds=1, consensus="majority")
    result = await Arena(env, mock_agents, protocol).run()

    assert result.status == "completed"
    assert result.consensus_reached is True
    assert result.final_answer == "Use a narrow review lane."
    assert len(result.messages) == 2
    assert {message.agent for message in result.messages} == {
        "agent_alpha",
        "agent_beta",
    }
