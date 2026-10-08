"""
Debate context container for pipeline execution.

This module defines the shared state container used by all debate phases.
The DebateContext is passed between phases, allowing them to read and
modify debate state without tight coupling to the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core import Agent, Critique, DebateResult, Environment, Message
    from aragora.debate.cancellation import CancellationToken
    from aragora.protocols import EventEmitterProtocol


def _default_environment() -> Environment:
    """Create a minimal Environment for tests or standalone usage."""
    from aragora.core import Environment

    return Environment(task="default")


@dataclass
class AgentWorkspace:
    """
    Isolated workspace for an agent during debate execution.

    Prevents crosstalk between agents by providing dedicated storage for:
    - Agent-specific scratch memory
    - Tool execution results
    - Isolated state variables

    This supports the clawdbot pattern of agent workspace isolation,
    ensuring each agent operates independently without shared mutable state.

    Example:
        workspace = context.get_workspace("claude-opus")
        workspace.memory["planning_notes"] = "..."
        workspace.tool_results["search"] = search_results
        workspace.state["iteration"] = 2
    """

    agent_id: str
    memory: dict[str, Any] = field(default_factory=dict)
    """Agent-specific scratch memory."""

    tool_results: dict[str, Any] = field(default_factory=dict)
    """Cached results from tool executions."""

    state: dict[str, Any] = field(default_factory=dict)
    """Isolated state variables for the agent."""

    created_at: float = field(default_factory=lambda: __import__("time").time())
    """Timestamp when workspace was created."""

    def clear(self) -> None:
        """Clear all workspace data."""
        self.memory.clear()
        self.tool_results.clear()
        self.state.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize workspace to dictionary."""
        return {
            "agent_id": self.agent_id,
            "memory": dict(self.memory),
            "tool_results": dict(self.tool_results),
            "state": dict(self.state),
            "created_at": self.created_at,
        }


@dataclass
class DebateContext:
    """
    Shared state container for debate execution pipeline.

    This class holds all mutable and immutable state needed during debate execution.
    It is created at the start of _run_inner() and passed to each phase for
    reading and mutation.

    Phases should:
    - Read from context to get current state
    - Write to context to update state
    - Not store references to the orchestrator (use callbacks if needed)
    """

    # =========================================================================
    # Immutable Inputs (set once at debate start)
    # =========================================================================

    env: Environment = field(default_factory=_default_environment)
    """The debate environment containing task, context, and configuration."""

    agents: list[Agent] = field(default_factory=list)
    """All agents participating in the debate."""

    start_time: float = 0.0
    """Unix timestamp when debate started."""

    debate_id: str = ""
    """Unique identifier for this debate."""

    correlation_id: str = ""
    """Request correlation ID for distributed tracing across services."""

    domain: str = "general"
    """Extracted domain for metrics and specialization."""

    session_id: str = ""
    """Session ID for session lifecycle tracking."""

    org_id: str = ""
    """Organization ID for multi-tenancy and budget tracking."""

    auth_context: Any | None = None
    """Optional authorization context for RBAC-aware context retrieval."""

    budget_check_callback: Any | None = None
    """Optional callback for mid-execution budget checks.

    If set, this should be a callable that returns (allowed: bool, reason: str).
    The debate rounds phase will call this before each round to check if
    the organization still has budget to continue.
    """

    cancellation_token: CancellationToken | None = None
    """Cancellation token for cooperative cancellation of long-running operations."""

    hook_manager: Any | None = None
    """HookManager for extended lifecycle hooks (PRE_ROUND, POST_ROUND, etc)."""

    channel_integration: Any | None = None
    """Optional ChannelIntegration for agent-to-agent messaging."""

    checkpoint_bridge: Any | None = None
    """Optional CheckpointBridge for unified molecule/checkpoint recovery."""

    molecule_orchestrator: Any | None = None
    """Optional MoleculeOrchestrator for debate phase tracking."""

    # =========================================================================
    # Agent Subsets (computed at phase boundaries)
    # =========================================================================

    proposers: list[Agent] = field(default_factory=list)
    """Agents with proposer role (or fallback to first agent)."""

    critics: list[Agent] = field(default_factory=list)
    """Agents that will provide critiques this round."""

    available_agents: list[Agent] = field(default_factory=list)
    """Agents that passed circuit breaker filter."""

    hierarchy_assignments: dict[str, Any] = field(default_factory=dict)
    """Gastown-inspired role assignments (agent_name -> RoleAssignment)."""

    # =========================================================================
    # Core Debate State (mutated during execution)
    # =========================================================================

    proposals: dict[str, str] = field(default_factory=dict)
    """Agent name -> proposal text mapping."""

    agent_failures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """Agent name -> list of failure records (phase, type, message, timestamp)."""

    context_messages: list[Message] = field(default_factory=list)
    """All messages in debate context (for prompt building)."""

    result: DebateResult | None = None
    """The DebateResult being built up during execution."""

    # =========================================================================
    # Round State (mutated each round)
    # =========================================================================

    current_round: int = 0
    """Current round number (0 = proposals, 1+ = critique/revision)."""

    previous_round_responses: dict[str, str] = field(default_factory=dict)
    """Agent name -> previous response (for revision prompts)."""

    round_critiques: list[Critique] = field(default_factory=list)
    """Critiques collected in the current round."""

    # =========================================================================
    # Timeout Recovery (for partial results on timeout)
    # =========================================================================

    partial_messages: list[Message] = field(default_factory=list)
    """Messages accumulated for timeout recovery."""

    partial_critiques: list[Critique] = field(default_factory=list)
    """Critiques accumulated for timeout recovery."""

    partial_rounds: int = 0
    """Number of rounds completed before timeout."""

    # =========================================================================
    # Voting State (set during consensus phase)
    # =========================================================================

    vote_tally: dict[str, float] = field(default_factory=dict)
    """Final weighted vote counts per choice."""

    choice_mapping: dict[str, str] = field(default_factory=dict)
    """Variant -> canonical choice mapping from vote grouping."""

    vote_weight_cache: dict[str, float] = field(default_factory=dict)
    """Pre-computed vote weights per agent."""

    winner_agent: str | None = None
    """Name of winning agent (set after consensus)."""

    # =========================================================================
    # Caches (populated once, read by multiple phases)
    # =========================================================================

    historical_context_cache: str = ""
    """Fetched historical debate context for institutional memory."""

    continuum_context_cache: str = ""
    """Context from ContinuumMemory retrieval."""

    research_context: str | None = None
    """Pre-debate research results."""

    evidence_pack: Any = None
    """Collected evidence pack from EvidenceCollector."""

    rlm_context: Any = None
    """Hierarchical RLM context from HierarchicalCompressor.

    When RLM compression is enabled, this holds a RLMContext object
    that provides drill-down access to different abstraction levels
    (ABSTRACT, SUMMARY, DETAILED, FULL) of the accumulated context.

    See aragora.rlm.types.RLMContext for the interface.
    """

    rlm_compressed_context: str | None = None
    """Compressed context summary from RLM compression.

    When RLM compression is enabled during context initialization,
    this holds the compressed summary of the accumulated context.
    This can be used as a fallback when the full context is too large.
    """

    use_compressed_context: bool = False
    """When True, use RLM summary level in prompts instead of full context."""

    ratings_cache: dict[str, Any] = field(default_factory=dict)
    """Batch-fetched AgentRating objects by agent name."""

    data_loaders: Any = None
    """Request-scoped DataLoaders for batched queries (DebateLoaders instance)."""

    event_emitter: EventEmitterProtocol | None = None
    """Optional event emitter for WebSocket event streaming."""

    loop_id: str = ""
    """Loop ID for event correlation."""

    applied_insight_ids: list[str] = field(default_factory=list)
    """IDs of insights that were injected into this debate (for usage tracking)."""

    # =========================================================================
    # Background Tasks (for parallel research/evidence collection)
    # =========================================================================

    background_research_task: Any = None
    """Background asyncio.Task for pre-debate research (runs parallel to proposals)."""

    background_evidence_task: Any = None
    """Background asyncio.Task for evidence collection (runs parallel to proposals)."""

    # =========================================================================
    # Convergence State
    # =========================================================================

    convergence_status: str = ""
    """Current convergence status: 'converged', 'refining', 'diverging', ''."""

    convergence_similarity: float = 0.0
    """Average semantic similarity between responses."""

    per_agent_similarity: dict[str, float] = field(default_factory=dict)
    """Per-agent similarity scores."""

    early_termination: bool = False
    """Flag set when debate should terminate early due to convergence."""

    # =========================================================================
    # Belief Network (optional reasoning subsystem)
    # =========================================================================

    belief_network: Any = None
    """BeliefNetwork for tracking claim confidence and crux detection.

    When enabled via ArenaConfig.enable_km_belief_sync, this is initialized
    at debate start and seeded with prior beliefs from Knowledge Mound.
    """

    # =========================================================================
    # Novelty State
    # =========================================================================

    per_agent_novelty: dict[str, list[float]] = field(default_factory=dict)
    """Per-agent novelty scores across rounds. Each list tracks novelty over time."""

    avg_novelty: float = 1.0
    """Average novelty across all agents (1.0 = maximally novel, 0.0 = repetitive)."""

    low_novelty_agents: list[str] = field(default_factory=list)
    """Agents whose proposals are too similar to prior proposals (below threshold)."""

    # =========================================================================
    # Agent Workspaces (isolated per-agent state)
    # =========================================================================

    agent_workspaces: dict[str, AgentWorkspace] = field(default_factory=dict)
    """Per-agent isolated workspaces to prevent crosstalk."""

    # =========================================================================
    # Checkpoint State (set when restored from checkpoint)
    # =========================================================================

    _restored_from_checkpoint: str | None = None
    """Checkpoint ID if this context was restored from a checkpoint."""

    _checkpoint_resume_round: int | None = None
    """Round number to resume from if restored from checkpoint."""

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_agent_by_name(self, name: str) -> Agent | None:
        """Look up an agent by name."""
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    def get_workspace(self, agent_id: str) -> AgentWorkspace:
        """
        Get or create an isolated workspace for an agent.

        This ensures each agent has dedicated storage that cannot
        be accidentally shared with other agents.

        Args:
            agent_id: ID of the agent

        Returns:
            AgentWorkspace instance for this agent
        """
        if agent_id not in self.agent_workspaces:
            self.agent_workspaces[agent_id] = AgentWorkspace(agent_id=agent_id)
        return self.agent_workspaces[agent_id]

    def clear_workspaces(self) -> None:
        """Clear all agent workspaces."""
        for workspace in self.agent_workspaces.values():
            workspace.clear()
        self.agent_workspaces.clear()

    def get_proposal(self, agent_name: str) -> str:
        """Get proposal for an agent, or empty string if none."""
        return self.proposals.get(agent_name, "")

    def add_message(self, msg: Message) -> None:
        """Record one message in context, recovery, and final-result tracking."""
        self.context_messages.append(msg)
        self.partial_messages.append(msg)
        if self.result is not None:
            self.result.messages.append(msg)

    def record_agent_failure(
        self,
        agent_name: str,
        phase: str,
        error_type: str,
        message: str,
        provider: str | None = None,
    ) -> None:
        """Record an agent failure for post-run diagnostics."""
        import time

        if not agent_name:
            agent_name = "unknown"

        record = {
            "phase": phase,
            "error_type": error_type,
            "message": message,
            "provider": provider or "",
            "timestamp": time.time(),
        }
        self.agent_failures.setdefault(agent_name, []).append(record)

    def add_critique(self, critique: Critique) -> None:
        """Add a critique to both result and partial tracking."""
        self.round_critiques.append(critique)
        self.partial_critiques.append(critique)
        if self.result:
            self.result.critiques.append(critique)

    def finalize_result(self) -> DebateResult:
        """
        Finalize and return the debate result.

        Sets duration, rounds used, and other final fields.
        """
        import time

        if self.result:
            self.result.duration_seconds = time.time() - self.start_time
            # Resolve rounds_used by precedence:
            #   1. self.current_round (only set explicitly by graph-style flows)
            #   2. self.result.rounds_used (set by debate_rounds._execute_round
            #      after each round's revision phase completes)
            #   3. self.partial_rounds (set at the *start* of each round, so a
            #      round that fails after partial work still contributes; this
            #      ensures a debate that crashed in critique/revision/novelty
            #      does not silently report rounds_used == rounds_completed == 0)
            rounds_used = self.current_round or self.result.rounds_used or self.partial_rounds
            self.result.rounds_used = rounds_used
            self.result.rounds_completed = rounds_used
            if self.winner_agent:
                self.result.winner = self.winner_agent
            # Copy novelty tracking data
            self.result.per_agent_novelty = dict(self.per_agent_novelty)
            self.result.avg_novelty = self.avg_novelty
            self.result.agent_failures = dict(self.agent_failures)
            self.result.proposals = dict(self.proposals)
            self.result.participants = [agent.name for agent in self.agents]
            if self.debate_id:
                self.result.debate_id = self.debate_id
                self.result.id = self.debate_id
            if not self.result.status:
                self.result.status = (
                    "consensus_reached" if self.result.consensus_reached else "completed"
                )
        return self.result

    def to_summary_dict(self) -> dict:
        """Return a summary dict for logging/debugging."""
        return {
            "debate_id": self.debate_id,
            "correlation_id": self.correlation_id,
            "domain": self.domain,
            "session_id": self.session_id,
            "agents": [a.name for a in self.agents],
            "proposers": [a.name for a in self.proposers],
            "current_round": self.current_round,
            "num_proposals": len(self.proposals),
            "num_messages": len(self.context_messages),
            "winner": self.winner_agent,
            "convergence_status": self.convergence_status,
            "avg_novelty": self.avg_novelty,
            "low_novelty_agents": self.low_novelty_agents,
        }

    def check_cancellation(self) -> None:
        """
        Check if cancellation was requested and raise if so.

        Use this at cancellation points in phase execution:
            ctx.check_cancellation()  # Raises DebateCancelled if cancelled
        """
        if self.cancellation_token is not None:
            self.cancellation_token.check()

    @property
    def is_cancelled(self) -> bool:
        """Check if the debate has been cancelled."""
        if self.cancellation_token is None:
            return False
        return self.cancellation_token.is_cancelled

    @property
    def critiques(self) -> list:
        """Backwards-compatible alias for round_critiques.

        Some code (e.g., synthesis_generator) expects ctx.critiques.
        This property provides that while the canonical attribute is round_critiques.
        """
        return self.round_critiques
