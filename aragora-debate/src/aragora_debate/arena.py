"""Arena — the core debate orchestrator.

Runs a structured adversarial debate across multiple agents::

    from aragora_debate import Arena, Agent, DebateConfig

    agents = [ClaudeAgent("claude"), GPTAgent("gpt4")]
    arena = Arena(
        question="Should we migrate to microservices?",
        agents=agents,
    )
    result = await arena.run()
    print(result.receipt.to_markdown())
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from aragora_debate.convergence import ConvergenceDetector
from aragora_debate.events import EventEmitter, EventType
from aragora_debate.receipt import ReceiptBuilder
from aragora_debate.trickster import EvidencePoweredTrickster, TricksterConfig
from aragora_debate.types import (
    Agent,
    Claim,
    Consensus,
    ConsensusMethod,
    Critique,
    DebateConfig,
    DebateResult,
    DissentRecord,
    Evidence,
    Message,
    Proposal,
    Vote,
)

logger = logging.getLogger(__name__)


@dataclass
class Arena:
    """Orchestrates an adversarial multi-model debate.

    Parameters
    ----------
    question : str
        The decision or question to debate.
    agents : list[Agent]
        Two or more agents that will participate.
    config : DebateConfig | None
        Protocol settings (rounds, consensus method, thresholds).
        Defaults to 3 rounds with majority consensus.
    context : str
        Optional background information provided to all agents.
    """

    question: str
    agents: list[Agent]
    config: DebateConfig | None = None
    context: str = ""
    on_event: Any = None  # Callable[[DebateEvent], Any] | None

    # Internal state
    _messages: list[Message] = field(default_factory=list, init=False, repr=False)
    _proposals: dict[str, Proposal] = field(default_factory=dict, init=False, repr=False)
    _critiques: list[Critique] = field(default_factory=list, init=False, repr=False)
    _votes: list[Vote] = field(default_factory=list, init=False, repr=False)
    _claims: list[Claim] = field(default_factory=list, init=False, repr=False)
    _evidence: list[Evidence] = field(default_factory=list, init=False, repr=False)

    # Feature components (created in __post_init__)
    _emitter: EventEmitter = field(default=None, init=False, repr=False)  # type: ignore[assignment]
    _convergence: ConvergenceDetector | None = field(default=None, init=False, repr=False)
    _trickster: EvidencePoweredTrickster | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.agents) < 2:
            raise ValueError("Arena requires at least 2 agents")
        if self.config is None:
            self.config = DebateConfig()

        # Event emitter
        self._emitter = EventEmitter()
        if self.on_event is not None:
            # Register for all event types
            for et in EventType:
                self._emitter.on(et)(self.on_event)

        # Convergence detector
        if self.config.enable_convergence:
            self._convergence = ConvergenceDetector(
                threshold=self.config.convergence_threshold,
            )

        # Trickster
        if self.config.enable_trickster:
            self._trickster = EvidencePoweredTrickster(
                config=TricksterConfig(
                    sensitivity=self.config.trickster_sensitivity,
                ),
            )

    async def run(self) -> DebateResult:
        """Execute the full debate and return the result with receipt."""
        assert self.config is not None
        start = time.monotonic()
        debate_id = uuid.uuid4().hex[:16]
        agent_names = [a.name for a in self.agents]

        logger.info(
            "Starting debate %s: %r with %d agents, %d rounds",
            debate_id,
            self.question,
            len(self.agents),
            self.config.rounds,
        )

        await self._emitter.emit(
            EventType.DEBATE_START,
            data={"question": self.question, "agents": agent_names, "rounds": self.config.rounds},
        )

        consensus: Consensus | None = None
        rounds_used = 0
        trickster_interventions = 0
        convergence_detected = False
        final_similarity = 0.0

        for round_num in range(1, self.config.rounds + 1):
            rounds_used = round_num
            logger.info("Round %d/%d", round_num, self.config.rounds)

            await self._emitter.emit(EventType.ROUND_START, round_num=round_num)

            # Phase 1: Propose
            await self._run_propose(round_num)

            # Convergence check after proposals
            if self._convergence is not None:
                proposals_map = {name: p.content for name, p in self._proposals.items()}
                conv_result = self._convergence.check(proposals_map, round_num)
                final_similarity = conv_result.similarity

                if conv_result.converged:
                    convergence_detected = True
                    await self._emitter.emit(
                        EventType.CONVERGENCE_DETECTED,
                        round_num=round_num,
                        data={
                            "similarity": conv_result.similarity,
                            "pair_similarities": conv_result.pair_similarities,
                        },
                    )

            # Trickster check after proposals
            if self._trickster is not None:
                proposals_map = {name: p.content for name, p in self._proposals.items()}
                similarity = final_similarity if self._convergence else 0.0
                intervention = self._trickster.check_and_intervene(
                    responses=proposals_map,
                    convergence_similarity=similarity,
                    round_num=round_num,
                )
                if intervention is not None:
                    trickster_interventions += 1
                    await self._emitter.emit(
                        EventType.TRICKSTER_INTERVENTION,
                        round_num=round_num,
                        data={
                            "type": intervention.intervention_type.value,
                            "targets": intervention.target_agents,
                            "priority": intervention.priority,
                        },
                    )
                    # Inject challenge as a trickster message
                    self._messages.append(
                        Message(
                            role="trickster",
                            agent="trickster",
                            content=intervention.challenge_text,
                            round=round_num,
                        )
                    )

            # Phase 2: Critique
            await self._run_critique(round_num)

            # Phase 3: Vote
            votes = await self._run_vote(round_num)
            consensus = self._evaluate_consensus(votes, agent_names)

            await self._emitter.emit(
                EventType.CONSENSUS_CHECK,
                round_num=round_num,
                data={
                    "reached": consensus.reached,
                    "confidence": consensus.confidence,
                },
            )

            await self._emitter.emit(EventType.ROUND_END, round_num=round_num)

            if (
                consensus.reached
                and self.config.early_stopping
                and round_num >= self.config.min_rounds
            ):
                logger.info("Consensus reached in round %d", round_num)
                break

        duration = time.monotonic() - start

        # Build result
        winning_agent = self._pick_winner(consensus)
        final_answer = self._proposals.get(winning_agent, Proposal(agent="", content="")).content

        # Apply confidence penalty when the Trickster detected hollow
        # consensus.  Each intervention reduces confidence by 5%, capped so
        # confidence never drops below 10%.  This correctly reflects that a
        # consensus built on thin evidence should carry less weight.
        raw_confidence = consensus.confidence if consensus else 0.0
        if trickster_interventions > 0:
            penalty = 0.05 * trickster_interventions
            adjusted_confidence = max(0.10, raw_confidence - penalty)
            logger.info(
                "Trickster confidence adjustment: %.3f -> %.3f (%d interventions)",
                raw_confidence,
                adjusted_confidence,
                trickster_interventions,
            )
        else:
            adjusted_confidence = raw_confidence

        result = DebateResult(
            id=debate_id,
            task=self.question,
            final_answer=final_answer,
            confidence=adjusted_confidence,
            consensus_reached=consensus.reached if consensus else False,
            consensus=consensus,
            rounds_used=rounds_used,
            status="consensus_reached" if (consensus and consensus.reached) else "completed",
            duration_seconds=duration,
            participants=agent_names,
            proposals={name: p.content for name, p in self._proposals.items()},
            messages=list(self._messages),
            critiques=list(self._critiques),
            votes=list(self._votes),
            dissenting_views=[
                f"{d.agent}: {'; '.join(d.reasons)}"
                for d in (consensus.dissents if consensus else [])
            ],
            claims=list(self._claims),
            evidence=list(self._evidence),
            trickster_interventions=trickster_interventions,
            convergence_detected=convergence_detected,
            final_similarity=final_similarity,
        )

        # Attach decision receipt
        result.receipt = ReceiptBuilder.from_result(result)
        result.verdict = result.receipt.verdict

        await self._emitter.emit(
            EventType.DEBATE_END,
            data={
                "status": result.status,
                "rounds_used": rounds_used,
                "consensus_reached": result.consensus_reached,
                "trickster_interventions": trickster_interventions,
                "convergence_detected": convergence_detected,
            },
        )

        logger.info(
            "Debate %s complete: %s (%.1fs, %d rounds)",
            debate_id,
            result.status,
            duration,
            rounds_used,
        )
        return result

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _run_propose(self, round_num: int) -> None:
        """All agents generate proposals concurrently."""
        prompt = self._build_propose_prompt(round_num)

        async def _propose(agent: Agent) -> Proposal:
            content = await agent.generate(prompt, context=self._messages)
            return Proposal(agent=agent.name, content=content, round=round_num)

        proposals = await asyncio.gather(
            *[_propose(a) for a in self.agents],
            return_exceptions=True,
        )

        for result in proposals:
            if isinstance(result, Exception):
                logger.warning("Agent proposal failed: %s", result)
                continue
            # Preserve Exception-only handling; casting does not swallow BaseException.
            result = cast(Proposal, result)
            self._proposals[result.agent] = result
            self._messages.append(
                Message(
                    role="proposer",
                    agent=result.agent,
                    content=result.content,
                    round=round_num,
                )
            )

    async def _run_critique(self, round_num: int) -> None:
        """Each agent critiques every other agent's proposal."""
        assert self.config is not None
        tasks: list[asyncio.Task[Critique | Exception]] = []

        for agent in self.agents:
            for target_name, proposal in self._proposals.items():
                if target_name == agent.name:
                    continue  # don't self-critique
                tasks.append(
                    asyncio.ensure_future(
                        self._safe_critique(agent, target_name, proposal.content, round_num)
                    )
                )

        critiques = await asyncio.gather(*tasks, return_exceptions=True)

        for result in critiques:
            if isinstance(result, Exception):
                logger.warning("Critique failed: %s", result)
                continue
            result = cast(Critique, result)
            self._critiques.append(result)
            self._messages.append(
                Message(
                    role="critic",
                    agent=result.agent,
                    content=result.content,
                    round=round_num,
                )
            )

    async def _safe_critique(
        self,
        agent: Agent,
        target: str,
        proposal_content: str,
        round_num: int,
    ) -> Critique:
        return await agent.critique(
            proposal=proposal_content,
            task=self.question,
            context=self._messages,
            target_agent=target,
        )

    async def _run_vote(self, round_num: int) -> list[Vote]:
        """All agents vote on the proposals."""
        proposals_map = {name: p.content for name, p in self._proposals.items()}

        async def _vote(agent: Agent) -> Vote:
            return await agent.vote(proposals_map, self.question)

        results = await asyncio.gather(
            *[_vote(a) for a in self.agents],
            return_exceptions=True,
        )

        votes: list[Vote] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Vote failed: %s", result)
                continue
            result = cast(Vote, result)
            votes.append(result)
            self._votes.append(result)
            self._messages.append(
                Message(
                    role="voter",
                    agent=result.agent,
                    content=f"Voted for {result.choice}: {result.reasoning}",
                    round=round_num,
                )
            )

        return votes

    # ------------------------------------------------------------------
    # Consensus evaluation
    # ------------------------------------------------------------------

    def _evaluate_consensus(
        self,
        votes: list[Vote],
        agent_names: list[str],
    ) -> Consensus:
        """Evaluate whether consensus has been reached."""
        assert self.config is not None
        method = self.config.consensus_method

        if not votes:
            return Consensus(
                reached=False,
                method=method,
                confidence=0.0,
                supporting_agents=[],
                dissenting_agents=agent_names,
            )

        # Tally votes (weighted by confidence)
        tally: dict[str, float] = {}
        voter_choices: dict[str, str] = {}
        for v in votes:
            tally[v.choice] = tally.get(v.choice, 0) + v.confidence
            voter_choices[v.agent] = v.choice

        total_weight = sum(tally.values())
        if total_weight == 0:
            return Consensus(
                reached=False,
                method=method,
                confidence=0.0,
                supporting_agents=[],
                dissenting_agents=agent_names,
            )

        # Find the leading choice
        leading_choice = max(tally, key=lambda k: tally[k])
        leading_weight = tally[leading_choice]
        ratio = leading_weight / total_weight

        # Determine if consensus is reached based on method
        thresholds = {
            ConsensusMethod.MAJORITY: 0.5,
            ConsensusMethod.SUPERMAJORITY: 0.667,
            ConsensusMethod.UNANIMOUS: 1.0,
            ConsensusMethod.JUDGE: 0.5,
            ConsensusMethod.WEIGHTED: self.config.consensus_threshold,
        }
        threshold = thresholds.get(method, self.config.consensus_threshold)
        reached = ratio >= threshold

        supporting = [name for name, choice in voter_choices.items() if choice == leading_choice]
        dissenting = [name for name in agent_names if name not in supporting]

        # Build dissent records
        dissents: list[DissentRecord] = []
        for v in votes:
            if v.choice != leading_choice:
                dissents.append(
                    DissentRecord(
                        agent=v.agent,
                        reasons=[v.reasoning] if v.reasoning else ["Voted differently"],
                        alternative_view=f"Preferred: {v.choice}",
                    )
                )

        return Consensus(
            reached=reached,
            method=method,
            confidence=ratio,
            supporting_agents=supporting,
            dissenting_agents=dissenting,
            dissents=dissents,
            statement=self._proposals.get(leading_choice, Proposal(agent="", content="")).content[
                :500
            ],
        )

    def _pick_winner(self, consensus: Consensus | None) -> str:
        """Return the name of the agent whose proposal won."""
        if consensus and consensus.supporting_agents:
            # The choice the supporting agents voted for
            for v in reversed(self._votes):
                if v.agent in consensus.supporting_agents:
                    return v.choice
        # Fallback: first agent
        return self.agents[0].name if self.agents else ""

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_propose_prompt(self, round_num: int) -> str:
        parts = [f"## Debate Round {round_num}"]
        parts.append(f"\n**Question:** {self.question}\n")
        if self.context:
            parts.append(f"**Context:** {self.context}\n")

        if round_num > 1 and self._critiques:
            parts.append("### Previous critiques to address:\n")
            recent = [c for c in self._critiques if True][-6:]  # last 6
            for c in recent:
                parts.append(f"- **{c.agent}** on {c.target_agent}: {c.content[:300]}")
            parts.append("")

        parts.append(
            "Provide your proposal. Be specific, cite evidence where possible, "
            "and acknowledge tradeoffs."
        )
        return "\n".join(parts)
