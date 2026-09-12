"""Built-in mock agent for testing and demos -- no API keys required."""

from __future__ import annotations

from typing import Any

from aragora_debate.types import Agent, Critique, Message, Vote


class MockAgent(Agent):
    """A deterministic agent that returns canned responses.

    Useful for testing, CI pipelines, and demos where real LLM calls
    are not desired.  Pass ``proposal`` and ``vote_for`` to control
    outputs, or leave defaults for simple round-trip tests.
    """

    def __init__(
        self,
        name: str = "mock",
        *,
        proposal: str = "This is my proposal based on careful analysis.",
        vote_for: str = "",
        critique_issues: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model="mock", **kwargs)
        self._proposal = proposal
        self._vote_for = vote_for
        self._critique_issues = critique_issues or ["Needs more supporting evidence"]

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        return self._proposal

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=list(self._critique_issues),
            suggestions=["Consider adding data to support claims"],
            severity=5.0,
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        choice = self._vote_for or list(proposals.keys())[0]
        return Vote(
            agent=self.name,
            choice=choice,
            confidence=0.8,
            reasoning="Selected based on strength of argument",
        )
