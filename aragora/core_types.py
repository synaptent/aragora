"""
Core abstractions for the Aragora control plane for multi-agent vetted decisionmaking.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Literal
from collections.abc import Callable

# Type aliases for agent role and stance
AgentRole = Literal[
    "proposer", "critic", "synthesizer", "judge", "analyst", "implementer", "planner"
]
AgentStance = Literal["affirmative", "negative", "neutral"]


class TaskComplexity(Enum):
    """Classification of task complexity for timeout scaling.

    Used by AdaptiveComplexityGovernor to scale timeouts based on
    estimated task difficulty.
    """

    SIMPLE = "simple"  # Quick surveys, simple questions, definitions
    MODERATE = "moderate"  # Standard design/analysis tasks
    COMPLEX = "complex"  # Deep reasoning, multi-step problems, formal proofs
    UNKNOWN = "unknown"  # Fallback when classification is uncertain


class Verdict(str, Enum):
    """Canonical verdict for decision receipts and gauntlet results.

    Unified verdict taxonomy used across:
    - ``aragora.export.decision_receipt.DecisionReceipt``
    - ``aragora.gauntlet.receipt_models.DecisionReceipt``
    - ``aragora.gauntlet.types.Verdict`` (extends with PASS/FAIL/CONDITIONAL aliases)

    Because this inherits from ``str``, verdict values can be compared
    directly with plain strings for backward compatibility::

        verdict = Verdict.APPROVED
        assert verdict == "approved"
        assert verdict.value == "approved"
    """

    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class DebateStatus(str, Enum):
    """Canonical lifecycle state for backend debate execution."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class DebateStatusSource(str, Enum):
    """Source classification for a debate result state."""

    LIVE = "live"
    SYNTHETIC = "synthetic"


def normalize_debate_status(
    value: Any,
    *,
    default: DebateStatus = DebateStatus.PENDING,
) -> DebateStatus:
    """Coerce legacy and canonical debate status strings into the shared model."""
    if isinstance(value, DebateStatus):
        return value

    normalized = str(value or "").strip().lower()
    if not normalized:
        return default

    if normalized in {"pending", "queued", "created", "initialized"}:
        return DebateStatus.PENDING
    if normalized in {"running", "in_progress", "active", "started"}:
        return DebateStatus.RUNNING
    if normalized in {"blocked", "timeout", "timed_out", "aborted", "paused"}:
        return DebateStatus.BLOCKED
    if normalized in {
        "failed",
        "failure",
        "error",
        "process_verification_failed",
        "verification_failed",
    }:
        return DebateStatus.FAILED
    if normalized in {
        "completed",
        "complete",
        "consensus_reached",
        "success",
        "succeeded",
        "settled",
        "no_consensus",
    }:
        return DebateStatus.COMPLETED

    return default


def normalize_debate_status_source(
    value: Any,
    *,
    default: DebateStatusSource = DebateStatusSource.LIVE,
) -> DebateStatusSource:
    """Coerce live/demo/mock labels into the shared debate status source model."""
    if isinstance(value, DebateStatusSource):
        return value

    normalized = str(value or "").strip().lower()
    if normalized in {"synthetic", "demo", "mock"}:
        return DebateStatusSource.SYNTHETIC
    if normalized in {"live", "real"}:
        return DebateStatusSource.LIVE
    return default


def legacy_debate_status(
    debate_status: DebateStatus,
    *,
    consensus_reached: bool = False,
) -> str:
    """Project the canonical lifecycle model into the legacy status field."""
    if debate_status == DebateStatus.COMPLETED:
        return "consensus_reached" if consensus_reached else "completed"
    return debate_status.value


@dataclass
class Message:
    """A message in a debate."""

    role: str  # "proposer", "critic", "synthesizer", etc.
    agent: str  # agent name
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    round: int = 0

    def __str__(self) -> str:
        return f"[{self.role}:{self.agent}] {self.content[:100]}..."


@dataclass
class Critique:
    """A critique of a proposal from one agent to another.

    Generated during the critique phase when agents evaluate each other's
    proposals. Critiques influence consensus by highlighting issues that
    should be addressed in revisions.

    Attributes:
        agent: Name of the agent providing the critique.
        target_agent: Name of the agent whose proposal is being critiqued.
        target_content: The specific content being critiqued.
        issues: List of problems identified (actionable items).
        suggestions: List of recommended improvements.
        severity: Impact score from 0-10:
            - 0-2: Minor/cosmetic issues
            - 3-5: Moderate concerns that should be addressed
            - 6-8: Significant problems affecting correctness
            - 9-10: Critical flaws that invalidate the proposal
        reasoning: Explanation of why these issues matter.

    Properties:
        target: Alias for target_agent (backward compatibility).
        content: Formatted text representation via to_prompt().

    Impact on Consensus:
        - High-severity critiques (7+) can prevent consensus
        - Proposals with many moderate critiques get lower vote weights
        - Addressed critiques in revisions improve consensus likelihood
    """

    agent: str
    target_agent: str
    target_content: str
    issues: list[str]
    suggestions: list[str]
    severity: float  # 0-10 scale (0=trivial, 10=critical)
    reasoning: str

    @property
    def target(self) -> str:
        """Alias for target_agent for backward compatibility."""
        return self.target_agent

    @property
    def content(self) -> str:
        """Get the critique's content as formatted text."""
        return self.to_prompt()

    def to_prompt(self) -> str:
        """Format critique for inclusion in prompts."""
        issues_str = "\n".join(f"  - {i}" for i in self.issues)
        suggestions_str = "\n".join(f"  - {s}" for s in self.suggestions)
        return f"""Critique from {self.agent} (severity: {self.severity:.1f}):
Issues:
{issues_str}
Suggestions:
{suggestions_str}
Reasoning: {self.reasoning}"""


@dataclass
class Vote:
    """An agent's vote for a proposal during the voting phase.

    Votes are collected after proposals and critiques to determine which
    proposal (or synthesized answer) wins. Votes can be weighted by
    confidence and agent ELO ratings.

    Attributes:
        agent: Name of the voting agent.
        choice: Name of the agent/proposal they're voting for. Can also
            be special values like "consensus" or "synthesis".
        reasoning: Explanation for why this choice was made.
        confidence: Vote weight from 0.0-1.0 (default 1.0). Lower values
            indicate uncertainty. Used in weighted voting schemes.
        continue_debate: Whether this agent believes the debate should
            continue for another round. If most agents vote False,
            early termination may occur.

    Voting Schemes:
        - majority: Simple count, most votes wins
        - weighted: Votes scaled by agent ELO ratings
        - confidence_weighted: Votes scaled by confidence values
        - supermajority: Requires threshold (e.g., 66%) to win
    """

    agent: str
    choice: str  # which proposal/agent they vote for
    reasoning: str
    confidence: float = 1.0  # 0-1, default to full confidence
    continue_debate: bool = True  # Whether agent thinks debate should continue


@dataclass
class DisagreementReport:
    """
    Surfaces explicit agreement/disagreement patterns from debates.

    Inspired by Heavy3.ai's insight: "When all models agree your argument is weak—fix it.
    When they disagree, you see the risk before you commit."
    """

    # Issues all agents unanimously agree on - high confidence problems
    unanimous_critiques: list[str] = field(default_factory=list)

    # Topics where agents split - each tuple is (topic, [agreeing_agents], [disagreeing_agents])
    split_opinions: list[tuple[str, list[str], list[str]]] = field(default_factory=list)

    # Risk areas identified from divergence patterns
    risk_areas: list[str] = field(default_factory=list)

    # Agreement score: 1.0 = complete unanimity, 0.0 = complete disagreement
    agreement_score: float = 0.0

    # Per-agent alignment with final consensus
    agent_alignment: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable disagreement summary."""
        lines = ["=== Disagreement Report ==="]

        if self.unanimous_critiques:
            lines.append(
                f"\n🚨 UNANIMOUS ISSUES ({len(self.unanimous_critiques)}) - Address these:"
            )
            for critique in self.unanimous_critiques[:5]:
                lines.append(f"  • {critique[:200]}")

        if self.split_opinions:
            lines.append(f"\n⚠️ SPLIT OPINIONS ({len(self.split_opinions)}) - Risks to consider:")
            for topic, agree, disagree in self.split_opinions[:5]:
                lines.append(f"  • {topic[:100]}")
                lines.append(f"    Agree: {', '.join(agree)} | Disagree: {', '.join(disagree)}")

        if self.risk_areas:
            lines.append(f"\n🔍 RISK AREAS ({len(self.risk_areas)}):")
            for risk in self.risk_areas[:5]:
                lines.append(f"  • {risk[:200]}")

        lines.append(f"\nAgreement Score: {self.agreement_score:.0%}")

        return "\n".join(lines)


@dataclass
class DebateResult:
    """The result of a multi-agent debate.

    Contains all outputs from Arena.run(), including the final answer,
    consensus metrics, agent contributions, and diagnostic information.

    Core Fields:
        id: Unique identifier for this result (defaults to debate_id).
        debate_id: Unique identifier for the debate session.
        task: The original task/question that was debated.
        final_answer: The synthesized conclusion from the debate.
        confidence: Overall confidence score (0.0-1.0).
        consensus_reached: Whether agents reached agreement.
        rounds_used: Number of debate rounds executed.
        status: Legacy state string preserved for backward compatibility.
        debate_status: Canonical lifecycle state ("pending", "running",
            "blocked", "failed", "completed").
        debate_status_source: Whether the result came from a live or synthetic path.

    Participant Data:
        participants: List of agent names that participated.
        proposals: Mapping of agent name to their final proposal.
        messages: Full conversation history as Message objects.
        critiques: List of Critique objects from the critique phase.
        votes: List of Vote objects from the voting phase.
        winner: Name of the agent whose proposal was selected (if any).

    Consensus & Convergence:
        consensus_strength: "strong" (variance < 1), "medium" (< 2), "weak" (>= 2).
        consensus_variance: Statistical variance in agent positions.
        convergence_status: "converged", "refining", "diverging", or "".
        convergence_similarity: Average semantic similarity at debate end.
        per_agent_similarity: Per-agent similarity scores.

    Disagreement Analysis:
        dissenting_views: Minority opinions that didn't reach consensus.
        disagreement_report: Structured disagreement analysis.
        debate_cruxes: Key claims driving disagreement (from belief network).
        evidence_suggestions: Claims that would benefit from more evidence.

    Verification & Grounding:
        grounded_verdict: Evidence grounding analysis result.
        verification_results: Per-agent claim verification counts.
        verification_bonuses: Vote bonuses from verification.
        formal_verification: Results from formal verification (Z3/Lean4).

    Cost & Performance:
        duration_seconds: Total debate execution time.
        total_cost_usd: Total API cost if cost tracking enabled.
        total_tokens: Total tokens consumed.
        per_agent_cost: Per-agent cost breakdown.
        budget_limit_usd: Budget cap if set.
        agent_failures: Per-agent failure records.

    Extensions:
        synthesis: Long-form synthesis (1200+ words) if enabled.
        translations: Multi-language translations of final_answer.
        export_links: Download URLs for exported formats.
        bead_id: Link to git-backed work unit if GUPP enabled.
        metadata: Arbitrary key-value metadata.

    Example:
        result = await arena.run()
        if result.consensus_reached:
            print(f"Answer: {result.final_answer}")
            print(f"Confidence: {result.confidence:.0%}")
            print(f"Strength: {result.consensus_strength}")
        else:
            print(f"No consensus after {result.rounds_used} rounds")
            for view in result.dissenting_views:
                print(f"  - {view}")
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    debate_id: str = ""
    task: str = ""
    final_answer: str = ""
    confidence: float = 0.0
    consensus_reached: bool = False
    rounds_used: int = 0
    rounds_completed: int = 0
    status: str = ""
    debate_status: str = DebateStatus.PENDING.value
    debate_status_source: str = DebateStatusSource.LIVE.value
    participants: list[str] = field(default_factory=list)
    agent_failures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    proposals: dict[str, str] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    winning_patterns: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    winner: str | None = None  # Winning agent name (set after consensus)
    # Convergence detection results
    convergence_status: str = ""  # "converged", "refining", "diverging", ""
    convergence_similarity: float = 0.0  # Average similarity at end
    per_agent_similarity: dict[str, float] = field(default_factory=dict)  # Agent -> similarity
    # Consensus strength: "strong" (var < 1), "medium" (var < 2), "weak" (var >= 2)
    consensus_strength: str = ""
    consensus_variance: float = 0.0
    # Disagreement surfacing (Heavy3-inspired)
    disagreement_report: DisagreementReport | None = None
    # Evidence grounding (Heavy3-inspired)
    grounded_verdict: Any | None = None  # GroundedVerdict from aragora.reasoning.citations
    # Belief network analysis - identifies key claims that drive disagreement
    debate_cruxes: list[dict[str, Any]] = field(
        default_factory=list
    )  # From BeliefPropagationAnalyzer
    evidence_suggestions: list[dict[str, Any]] = field(
        default_factory=list
    )  # Claims needing evidence
    # Verification results - claim verification during consensus
    # Contains both verified_claim_count (int) and evidence_quality scores (float)
    verification_results: dict[str, int | float] = field(
        default_factory=dict
    )  # Agent -> verified_claim_count or quality score
    verification_bonuses: dict[str, float] = field(
        default_factory=dict
    )  # Agent -> vote_bonus_applied
    # Novelty tracking - semantic distance from prior proposals
    per_agent_novelty: dict[str, list[float]] = field(
        default_factory=dict
    )  # Agent -> novelty by round
    avg_novelty: float = 1.0  # Average novelty (1.0 = fresh ideas, 0.0 = repetitive)
    # Formal verification result (from Lean4/Z3)
    formal_verification: dict[str, Any] | None = None  # FormalProofResult.to_dict()
    # Export download links (populated after debate completion for aragora.ai)
    export_links: dict[str, str] | None = None  # Format -> URL mapping
    # Final synthesis from Claude Opus 4.5 (1200-word comprehensive summary)
    synthesis: str = ""
    # Cost/usage data (populated by extensions if cost tracking enabled)
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    per_agent_cost: dict[str, float] = field(default_factory=dict)
    budget_limit_usd: float | None = None
    # Bead tracking - links debate decision to git-backed work unit
    bead_id: str | None = None
    # Multi-language translations - maps language code to translated final_answer
    # Example: {"es": "Spanish translation...", "fr": "French translation..."}
    translations: dict[str, str] = field(default_factory=dict)
    # Partial consensus - tracks which sub-questions/topics reached agreement
    # when overall consensus wasn't achieved. Enables plans to proceed with agreed portions.
    partial_consensus: Any | None = None  # PartialConsensus from aragora.debate.consensus
    # Topic modeling - categorizes the debate for routing and analysis
    topic_id: str | None = None  # Canonical ID for the primary topic
    topic_tags: list[str] = field(default_factory=list)  # Associated tags

    def __post_init__(self) -> None:
        if self.debate_id:
            self.id = self.debate_id
        else:
            self.debate_id = self.id

        if self.rounds_completed and not self.rounds_used:
            self.rounds_used = self.rounds_completed
        elif self.rounds_used and not self.rounds_completed:
            self.rounds_completed = self.rounds_used
        elif self.rounds_completed != self.rounds_used:
            self.rounds_used = self.rounds_completed

        status_text = str(self.status or "").strip()
        debate_status_text = str(self.debate_status or "").strip()
        if status_text and (
            not debate_status_text or debate_status_text == DebateStatus.PENDING.value
        ):
            debate_status_text = status_text
        debate_status = normalize_debate_status(
            debate_status_text,
            default=DebateStatus.PENDING,
        )
        self.debate_status = debate_status.value
        self.debate_status_source = normalize_debate_status_source(
            self.debate_status_source,
            default=DebateStatusSource.LIVE,
        ).value

        if not status_text:
            self.status = legacy_debate_status(
                debate_status,
                consensus_reached=bool(self.consensus_reached),
            )

    @property
    def history(self) -> list[Message]:
        """Alias for messages (backward compatibility)."""
        return self.messages

    def to_dict(self) -> dict[str, Any]:
        """Serialize core fields for JSON export."""
        result = {
            "debate_id": self.debate_id,
            "task": self.task,
            "status": self.status,
            "debate_status": self.debate_status,
            "debate_status_source": self.debate_status_source,
            "final_answer": self.final_answer,
            "consensus_reached": self.consensus_reached,
            "confidence": self.confidence,
            "rounds_used": self.rounds_used,
            "rounds_completed": self.rounds_completed,
            "participants": list(self.participants),
            "agent_failures": self.agent_failures,
            "duration_seconds": self.duration_seconds,
            "winner": self.winner,
            "topic_id": self.topic_id,
            "topic_tags": self.topic_tags,
        }
        # Include cost data if present
        if self.total_cost_usd > 0 or self.total_tokens > 0:
            result["total_cost_usd"] = self.total_cost_usd
            result["total_tokens"] = self.total_tokens
            result["per_agent_cost"] = dict(self.per_agent_cost)
            if self.budget_limit_usd is not None:
                result["budget_limit_usd"] = self.budget_limit_usd
        # Include translations if present
        if self.translations:
            result["translations"] = dict(self.translations)
        # Include partial consensus if present
        if self.partial_consensus is not None:
            if hasattr(self.partial_consensus, "to_dict"):
                result["partial_consensus"] = self.partial_consensus.to_dict()
            else:
                result["partial_consensus"] = self.partial_consensus
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateResult:
        """Deserialize from a dictionary."""
        return cls(
            id=data.get("id") or data.get("debate_id", ""),
            debate_id=data.get("debate_id", ""),
            task=data.get("task", ""),
            status=data.get("status", ""),
            debate_status=data.get("debate_status", ""),
            debate_status_source=data.get("debate_status_source", ""),
            final_answer=data.get("final_answer", ""),
            consensus_reached=data.get("consensus_reached", False),
            confidence=data.get("confidence", 0.0),
            rounds_used=data.get("rounds_used", data.get("rounds_completed", 0)),
            rounds_completed=data.get("rounds_completed", data.get("rounds_used", 0)),
            participants=data.get("participants", []),
            agent_failures=data.get("agent_failures", {}),
            proposals=data.get("proposals", {}),
            duration_seconds=data.get("duration_seconds", 0.0),
            winner=data.get("winner"),
            translations=data.get("translations", {}),
            topic_id=data.get("topic_id"),
            topic_tags=data.get("topic_tags", []),
        )

    def summary(self) -> str:
        """Human-readable summary of the debate."""
        base = f"""Debate Result ({self.id[:8]}):
Task: {self.task[:100]}...
Rounds: {self.rounds_used}
Consensus: {"Yes" if self.consensus_reached else "No"} (confidence: {self.confidence:.1%})
Critiques: {len(self.critiques)}
Dissenting views: {len(self.dissenting_views)}
Duration: {self.duration_seconds:.1f}s

Final Answer:
{self.final_answer}"""

        if self.disagreement_report:
            base += f"\n\n{self.disagreement_report.summary()}"

        if self.grounded_verdict:
            base += f"\n\nGrounding Score: {self.grounded_verdict.grounding_score:.0%}"
            if hasattr(self.grounded_verdict, "all_citations"):
                base += f" ({len(self.grounded_verdict.all_citations)} citations)"

        return base


@dataclass
class Environment:
    """Defines a task environment for multi-agent debate.

    The Environment specifies what problem to solve and constraints on how
    the debate should proceed. This is one of the three core inputs to Arena
    (along with agents and protocol).

    Attributes:
        task: The problem, question, or goal to debate. Required, non-empty,
            max 100,000 characters (~15k words). Cannot contain null bytes.
        context: Additional background information to provide to all agents.
            Use for domain knowledge, constraints, or prior decisions.
        roles: List of cognitive roles to assign. Defaults to
            ["proposer", "critic", "synthesizer"]. Common roles include:
            - proposer: Generates solution proposals
            - critic: Identifies issues and weaknesses
            - synthesizer: Combines proposals into unified answers
            - judge: Evaluates and scores proposals
            - analyst: Deep-dives on specific aspects
        success_fn: Optional scoring function (str -> float 0-1) to evaluate
            proposals. If provided, used to guide consensus toward
            higher-scoring answers.
        max_rounds: Maximum debate rounds before forced termination.
            Defaults to 3. Higher values allow more refinement but
            increase cost and latency.
        require_consensus: If True, debate continues until consensus or
            max_rounds. If False, may terminate early on strong agreement.
        consensus_threshold: Fraction of agents that must agree for
            consensus (0.0-1.0). Default 0.7 means 70% agreement required.
        documents: List of document IDs to attach to this debate for
            evidence grounding. Documents are fetched and provided to
            agents during the debate.

    Validation:
        - task must be non-empty
        - task cannot exceed MAX_TASK_LENGTH (100,000 chars)
        - task cannot contain null bytes (security measure)

    Example:
        # Simple task
        env = Environment(task="Design a rate limiter for our API")

        # With context and custom roles
        env = Environment(
            task="Review this architecture proposal",
            context="We need <100ms latency and 10k RPS capacity",
            roles=["proposer", "critic", "analyst"],
            max_rounds=5,
            consensus_threshold=0.8,
        )

        # With document grounding
        env = Environment(
            task="Analyze risks in this contract",
            documents=["doc-123", "doc-456"],
        )
    """

    # Maximum task length (prevents DoS via very long strings)
    MAX_TASK_LENGTH: ClassVar[int] = 100_000  # ~15k words

    task: str
    context: str = ""  # additional context
    roles: list[str] = field(default_factory=lambda: ["proposer", "critic", "synthesizer"])
    success_fn: Callable[[str], float] | None = None  # 0-1 score
    max_rounds: int = 3
    require_consensus: bool = False
    consensus_threshold: float = 0.7  # fraction of agents that must agree
    # Document IDs attached to this debate (Heavy3-inspired)
    documents: list[str] = field(default_factory=list)
    # Topic modeling - used for agent routing and analytics
    topic_id: str | None = None
    topic_tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate task input for safety."""
        if not self.task or not self.task.strip():
            raise ValueError("Task cannot be empty")
        if len(self.task) > self.MAX_TASK_LENGTH:
            raise ValueError(f"Task exceeds maximum length of {self.MAX_TASK_LENGTH} characters")
        if "\x00" in self.task:
            raise ValueError("Task contains invalid null bytes")


@dataclass
class ToolManifest:
    """
    Defines available tools and permissions for an agent.

    Used to restrict which tools an agent can use during debate,
    enabling fine-grained control over agent capabilities.

    Example:
        manifest = ToolManifest(
            available_tools=["web_search", "code_execution"],
            permissions=["read_files", "write_files"],
            max_parallel=3,
        )
        if manifest.has_tool("web_search"):
            # Agent can use web search
            pass
    """

    available_tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    max_parallel: int = 3
    blocked_tools: list[str] = field(default_factory=list)
    tool_configs: dict[str, Any] = field(default_factory=dict)

    def has_tool(self, tool_name: str) -> bool:
        """Check if agent has access to a specific tool."""
        if tool_name in self.blocked_tools:
            return False
        if not self.available_tools:
            return True  # No restrictions if no tools specified
        return tool_name in self.available_tools

    def has_permission(self, permission: str) -> bool:
        """Check if agent has a specific permission."""
        if not self.permissions:
            return True  # No restrictions if no permissions specified
        return permission in self.permissions

    def get_tool_config(self, tool_name: str) -> dict[str, Any]:
        """Get configuration for a specific tool."""
        return self.tool_configs.get(tool_name, {})


class Agent(ABC):
    """Abstract base class for all agents.

    Attributes:
        name: Unique identifier for the agent
        model: The underlying model (e.g., "claude-3-opus", "gpt-4o")
        role: The agent's role in the debate (proposer, critic, synthesizer, judge)
        system_prompt: Custom system prompt for the agent
        agent_type: Agent type identifier for routing and role assignment
        stance: The agent's stance for asymmetric debate
    """

    name: str
    model: str
    role: AgentRole
    system_prompt: str
    agent_type: str
    stance: AgentStance
    tool_manifest: ToolManifest | None

    def __init__(self, name: str, model: str, role: AgentRole = "proposer"):
        self.name = name
        self.model = model
        self.role = role
        self.system_prompt = ""
        # Agent type identifier for routing and role assignment
        self.agent_type = "unknown"
        # Stance for asymmetric debate: "affirmative", "negative", or "neutral"
        # - Affirmative: Defend/support proposals
        # - Negative: Challenge/critique proposals
        # - Neutral: Evaluate fairly without bias
        self.stance: AgentStance = "neutral"
        # Tool manifest for controlling which tools the agent can use
        self.tool_manifest: ToolManifest | None = None

    @abstractmethod
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response to a prompt."""
        pass

    @abstractmethod
    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal.

        Args:
            proposal: The proposal/response to critique
            task: The task or question being addressed
            context: Optional conversation context
            target_agent: Name of the agent whose proposal is being critiqued
        """
        pass

    async def vote(self, proposals: dict[str, str], task: str) -> Vote:
        """Vote on which proposal is best."""
        # Default implementation - can be overridden
        prompt = f"""Task: {task}

Proposals to evaluate:
{chr(10).join(f"{agent}: {prop[:500]}..." for agent, prop in proposals.items())}

Which proposal best addresses the task? Respond with:
CHOICE: <agent_name>
CONFIDENCE: <0.0-1.0>
CONTINUE: <yes/no> (whether more debate rounds would help improve the answer)
REASONING: <brief explanation>"""

        response = await self.generate(prompt)
        # Parse response (simple extraction)
        lines = response.strip().split("\n")
        choice = ""
        confidence = 0.5
        reasoning = ""
        continue_debate = True

        for line in lines:
            if line.startswith("CHOICE:"):
                choice = line.replace("CHOICE:", "").strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.replace("CONFIDENCE:", "").strip())
                except (ValueError, TypeError):
                    confidence = 0.5  # Default confidence on parse error
            elif line.startswith("CONTINUE:"):
                cont_val = line.replace("CONTINUE:", "").strip().lower()
                continue_debate = cont_val not in ("no", "false", "0", "n")
            elif line.startswith("REASONING:"):
                reasoning = line.replace("REASONING:", "").strip()

        return Vote(
            agent=self.name,
            choice=choice,
            confidence=confidence,
            reasoning=reasoning,
            continue_debate=continue_debate,
        )

    def set_system_prompt(self, prompt: str) -> None:
        """Update the agent's system prompt (for self-improvement)."""
        self.system_prompt = prompt

    def has_tool_permission(self, tool_name: str) -> bool:
        """
        Check if agent has permission to use a specific tool.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if agent can use the tool, False otherwise
        """
        if self.tool_manifest is None:
            return True  # No restrictions
        return self.tool_manifest.has_tool(tool_name)

    def set_tool_manifest(self, manifest: ToolManifest) -> None:
        """Set the tool manifest for this agent."""
        self.tool_manifest = manifest

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, model={self.model}, role={self.role})"


def __getattr__(name: str) -> Any:
    if name == "DebateProtocol":
        from aragora.protocols.debate import DebateProtocol

        return DebateProtocol
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + ["DebateProtocol"])
