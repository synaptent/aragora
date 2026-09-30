"""Style-based mock agents for demos and testing -- no API keys required.

Four debate styles control tone, critique severity, and voting behaviour,
enabling realistic multi-perspective debates without any API calls.

Usage::

    from aragora_debate.styled_mock import StyledMockAgent

    agents = [
        StyledMockAgent("analyst", style="supportive"),
        StyledMockAgent("critic", style="critical"),
        StyledMockAgent("pm", style="balanced"),
    ]
"""

from __future__ import annotations

import random
from typing import Any, Literal

from aragora_debate.types import Agent, Critique, Message, Vote

# ---------------------------------------------------------------------------
# Style-specific response templates
# ---------------------------------------------------------------------------

PROPOSALS: dict[str, list[str]] = {
    "supportive": [
        "After careful analysis, I strongly endorse this approach. "
        "The benefits clearly outweigh the costs: reduced operational overhead, "
        "improved developer velocity, and better alignment with industry best practices. "
        "I recommend proceeding with a phased rollout starting with non-critical services.",
        "This is a sound strategy. The evidence points toward significant gains in "
        "maintainability and team productivity. Key advantages include clearer ownership "
        "boundaries, independent deployability, and the ability to scale components "
        "individually as demand requires.",
        "I see strong alignment between this proposal and our technical objectives. "
        "The approach is well-supported by industry data showing 40-60% reduction in "
        "deployment friction for organizations that have adopted similar patterns.",
    ],
    "critical": [
        "I have significant concerns about this approach. The migration cost is "
        "severely underestimated -- distributed systems introduce network partitioning, "
        "data consistency challenges, and operational complexity that monoliths avoid. "
        "Before committing, we need a detailed total-cost-of-ownership analysis.",
        "This proposal overlooks critical failure modes. The added latency from "
        "inter-service communication, the complexity of distributed tracing, and the "
        "talent cost of hiring engineers fluent in distributed architectures make "
        "this a high-risk endeavour with uncertain payoff.",
        "The claimed benefits are overstated. Most organizations that attempted this "
        "migration underestimated the operational burden by 3-5x. I recommend a "
        "modular monolith as the safer path that captures 80% of the benefits.",
    ],
    "balanced": [
        "There are valid arguments on both sides. The proposed approach offers "
        "scalability and team autonomy, but introduces operational complexity. "
        "I recommend a hybrid strategy: identify 2-3 bounded contexts that would "
        "benefit most, migrate those first, and measure results before expanding.",
        "The tradeoffs here are real. On one hand, the current architecture limits "
        "independent scaling and deployment. On the other, the migration carries "
        "execution risk and requires new tooling. A staged approach with clear "
        "success criteria at each gate would manage both sides effectively.",
        "Both approaches have merit. The key question isn't which is theoretically "
        "better, but which fits our team's current capabilities and growth trajectory. "
        "I suggest a 90-day proof-of-concept with measurable KPIs before committing.",
    ],
    "contrarian": [
        "I disagree with the prevailing direction. The popular choice is often wrong "
        "because it optimises for the visible problem while ignoring systemic risks. "
        "We should consider the opposite approach -- the simplest architecture that "
        "meets our actual (not hypothetical) requirements.",
        "Everyone seems to be converging too quickly. That's a red flag. Let me "
        "argue the unpopular position: our current approach, with targeted improvements, "
        "may outperform a wholesale migration. The grass isn't always greener.",
        "I'm intentionally taking the opposing view because premature consensus is "
        "dangerous. If we can't defend the mainstream proposal against serious "
        "objections, it's not ready for adoption. Here's my strongest counter-argument.",
    ],
    # Hollow consensus style: agents agree using vague, evidence-free language.
    # All templates share similar structure/wording to produce high convergence
    # similarity while containing zero citations, data, or concrete examples.
    "hollow": [
        "I think the first option is generally better for most teams. "
        "It is typically the right choice in various situations and usually "
        "leads to good outcomes. The important aspects make it a solid approach "
        "that many organizations would benefit from. Overall this seems like "
        "the common approach and industry standard that best practices recommend.",
        "The first option is generally the way to go. It usually works well "
        "in many situations and typically delivers good results. The key elements "
        "of this approach align with common best practices and the significant impact "
        "it could potentially have makes it a strong choice for most teams.",
        "Generally speaking, the first option is the better path forward. "
        "It is typically recommended and usually considered the industry standard. "
        "Various factors suggest it might be the right approach for most scenarios "
        "and many considerations point to it being a solid, common choice overall.",
    ],
}

CRITIQUE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "supportive": {
        "issues": [
            "Could benefit from more quantitative evidence",
            "The timeline might be slightly optimistic",
        ],
        "suggestions": [
            "Consider adding metrics from similar past initiatives",
            "Include a brief risk acknowledgment for completeness",
        ],
    },
    "critical": {
        "issues": [
            "Missing cost analysis for migration and ongoing operations",
            "No rollback strategy if the approach fails",
            "Assumes team expertise that hasn't been validated",
            "Ignores the operational overhead of distributed monitoring",
        ],
        "suggestions": [
            "Provide a total-cost-of-ownership comparison",
            "Define explicit success/failure criteria and rollback triggers",
            "Conduct a team skills assessment before committing",
        ],
    },
    "balanced": {
        "issues": [
            "The proposal could better acknowledge the opposing viewpoint",
            "Risk assessment could be more specific to our context",
        ],
        "suggestions": [
            "Add a pros/cons matrix to help stakeholders weigh tradeoffs",
            "Include a decision framework for when to revisit the choice",
        ],
    },
    "contrarian": {
        "issues": [
            "The group appears to be converging prematurely",
            "Confirmation bias may be inflating confidence in this direction",
            "Alternative approaches have not been seriously considered",
        ],
        "suggestions": [
            "Assign someone to argue the opposing case formally",
            "Delay the decision by one round to stress-test assumptions",
        ],
    },
    "hollow": {
        "issues": [
            "Could benefit from some additional considerations",
        ],
        "suggestions": [
            "Maybe think about a few more things",
        ],
    },
}

SEVERITY_RANGES: dict[str, tuple[float, float]] = {
    "supportive": (2.0, 4.0),
    "critical": (6.0, 9.0),
    "balanced": (4.0, 6.0),
    "contrarian": (5.0, 8.0),
    "hollow": (1.0, 3.0),
}

Style = Literal["supportive", "critical", "balanced", "contrarian", "hollow"]


class StyledMockAgent(Agent):
    """A mock agent that returns style-appropriate canned responses.

    Useful for demos and tests where real LLM calls are not desired.

    Parameters
    ----------
    name : str
        Agent display name.
    style : str
        One of ``"supportive"``, ``"critical"``, ``"balanced"`` (default),
        or ``"contrarian"``.  Controls tone, critique severity, and voting
        behaviour.
    proposal : str | None
        Override the generated proposal text (bypasses style templates).
    vote_for : str
        Force the agent to vote for a specific agent name.
    critique_issues : list[str] | None
        Override critique issues (bypasses style templates).
    """

    def __init__(
        self,
        name: str = "mock",
        *,
        style: Style = "balanced",
        proposal: str | None = None,
        vote_for: str = "",
        critique_issues: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, model="mock", **kwargs)
        if style not in PROPOSALS:
            raise ValueError(
                f"Unknown style {style!r}. Choose from: supportive, critical, balanced, contrarian"
            )
        self.style: Style = style
        self._proposal_override = proposal
        self._vote_for = vote_for
        self._critique_issues_override = critique_issues

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        if self._proposal_override is not None:
            return self._proposal_override
        return random.choice(PROPOSALS[self.style])

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        tpl = CRITIQUE_TEMPLATES[self.style]
        issues = (
            list(self._critique_issues_override)
            if self._critique_issues_override is not None
            else list(tpl["issues"])
        )
        suggestions = list(tpl["suggestions"])
        lo, hi = SEVERITY_RANGES[self.style]
        severity = round(random.uniform(lo, hi), 1)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal,
            issues=issues,
            suggestions=suggestions,
            severity=severity,
        )

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        names = [n for n in proposals if n != self.name]
        if not names:
            names = list(proposals.keys())

        if self._vote_for and self._vote_for in proposals:
            choice = self._vote_for
        elif self.style == "supportive":
            # Picks the first agent (tends to endorse the initiator)
            choice = names[0]
        elif self.style == "contrarian":
            # Picks the last agent (minority voice)
            choice = names[-1]
        elif self.style == "hollow":
            # Hollow agents always follow the majority -- pick first agent
            choice = names[0]
        else:
            # balanced / critical: pick randomly
            choice = random.choice(names)

        # Add slight randomness to confidence (±0.05)
        base_confidence = {
            "supportive": 0.85,
            "critical": 0.60,
            "balanced": 0.70,
            "contrarian": 0.50,
            "hollow": 0.90,  # High confidence despite no evidence
        }.get(self.style, 0.7)
        confidence = round(max(0.1, min(1.0, base_confidence + random.uniform(-0.05, 0.05))), 2)

        # Topic-aware reasoning (truncate at word boundary)
        topic_snippet = task[:80] if task else "the proposal"
        if len(task) > 80:
            topic_snippet = topic_snippet.rsplit(" ", 1)[0] + "..."
        topic_snippet = topic_snippet.rstrip(".!? ")
        reasoning_templates = {
            "supportive": [
                f"{choice}'s proposal on '{topic_snippet}' is the strongest -- clear benefits with manageable risks",
                f"After weighing all arguments on '{topic_snippet}', {choice} presents the most actionable path forward",
            ],
            "critical": [
                f"{choice}'s argument best addresses the risks I raised about '{topic_snippet}'",
                f"While I remain cautious about '{topic_snippet}', {choice}'s position is the most defensible",
            ],
            "balanced": [
                f"{choice} strikes the right balance between ambition and pragmatism on '{topic_snippet}'",
                f"On '{topic_snippet}', {choice}'s staged approach manages risk while enabling progress",
            ],
            "contrarian": [
                f"Reluctantly voting for {choice} -- their view on '{topic_snippet}' at least considers the downsides",
                f"None of the proposals fully satisfy my concerns, but {choice}'s position on '{topic_snippet}' is least risky",
            ],
            "hollow": [
                f"I agree with {choice} on '{topic_snippet}' -- it generally seems like the right approach",
                f"{choice}'s take on '{topic_snippet}' is typically what most people would recommend",
            ],
        }
        reasoning = random.choice(reasoning_templates.get(self.style, [f"Selected {choice}"]))

        return Vote(
            agent=self.name,
            choice=choice,
            confidence=confidence,
            reasoning=reasoning,
        )
