"""A debate decision stores the rendered debate summary as its reasoning."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


async def test_debate_decision_reasoning_is_the_rendered_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.core.decision_models import DecisionConfig, DecisionRequest, DecisionType
    from aragora.core.decision_router import DecisionRouter

    monkeypatch.setattr("aragora.agents.get_agents_by_names", lambda _agents=None: [])

    class _Result(SimpleNamespace):
        def summary(self) -> str:
            return "Rendered summary"

    class _Arena:
        def __init__(self, environment: Any, agents: Any, protocol: Any, **_kwargs: Any) -> None:
            pass

        async def run(self) -> _Result:
            return _Result(final_answer="ok", consensus_reached=True, confidence=0.9)

    request = DecisionRequest(
        content="Pick a roadmap",
        decision_type=DecisionType.DEBATE,
        config=DecisionConfig(rounds=1, agents=[], use_knowledge_mound=False),
    )
    result = await DecisionRouter(debate_engine=_Arena).route(request)

    assert result.reasoning == "Rendered summary"
