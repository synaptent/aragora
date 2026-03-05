"""
Debate protocol configuration.

Contains:
- DebateProtocol: Configuration for debate execution
- user_vote_multiplier: Conviction-weighted voting calculation

Note: CircuitBreaker is now in aragora.resilience module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from aragora.config import (
    AGENT_TIMEOUT_SECONDS,
    DEBATE_TIMEOUT_SECONDS,
    DEFAULT_ROUNDS,
    MAX_CONCURRENT_CRITIQUES,
    MAX_CONCURRENT_REVISIONS,
)
from aragora.debate.role_matcher import RoleMatchingConfig
from aragora.debate.roles import RoleRotationConfig
from aragora.resilience import CircuitBreaker  # Re-export for backwards compatibility

if TYPE_CHECKING:
    from aragora.debate.breakpoints import BreakpointConfig

logger = logging.getLogger(__name__)

# Re-export CircuitBreaker for backwards compatibility
__all__ = [
    "ARAGORA_AI_LIGHT_PROTOCOL",
    "ARAGORA_AI_PROTOCOL",
    "CircuitBreaker",
    "DebateProtocol",
    "RoundPhase",
    "STRUCTURED_LIGHT_ROUND_PHASES",
    "STRUCTURED_ROUND_PHASES",
    "resolve_default_protocol",
    "user_vote_multiplier",
]


@dataclass
class RoundPhase:
    """Configuration for a structured debate round phase."""

    number: int  # Round number (1-indexed)
    name: str  # Phase name (e.g., "Initial Analysis")
    description: str  # What this phase accomplishes
    focus: str  # Key focus area for agents
    cognitive_mode: str  # Analyst, Skeptic, Lateral, Synthesizer, etc.


# Default structured debate format for aragora.ai (defaults to ARAGORA_DEFAULT_ROUNDS=9)
# Round 0 (Context Gathering) runs parallel with Round 1
# Rounds 1-7 are the core debate cycle
# Round 8 (Adjudication) handles voting, judge verdict, and final synthesis
STRUCTURED_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        number=0,
        name="Context Gathering",
        description="Gather background information, evidence, and assign personas",
        focus="Research, evidence collection, historical context, persona assignment",
        cognitive_mode="Researcher",
    ),
    RoundPhase(
        number=1,
        name="Initial Analysis",
        description="Establish foundational understanding and key considerations",
        focus="Core facts, assumptions, and initial positions",
        cognitive_mode="Analyst",
    ),
    RoundPhase(
        number=2,
        name="Skeptical Review",
        description="Challenge assumptions and identify weaknesses",
        focus="Logical flaws, unsupported claims, edge cases",
        cognitive_mode="Skeptic",
    ),
    RoundPhase(
        number=3,
        name="Lateral Exploration",
        description="Explore alternative perspectives and creative solutions",
        focus="Novel approaches, analogies, unconventional ideas",
        cognitive_mode="Lateral Thinker",
    ),
    RoundPhase(
        number=4,
        name="Devil's Advocacy",
        description="Argue the strongest opposing viewpoint",
        focus="Counter-arguments, risks, unintended consequences",
        cognitive_mode="Devil's Advocate",
    ),
    RoundPhase(
        number=5,
        name="Integration",
        description="Connect insights across perspectives, identify patterns",
        focus="Emerging patterns, bridging views, key trade-offs, areas of agreement",
        cognitive_mode="Integrator",
    ),
    RoundPhase(
        number=6,
        name="Cross-Examination",
        description="Direct questioning between agents on remaining disputes",
        focus="Clarifying disagreements, testing convictions",
        cognitive_mode="Examiner",
    ),
    RoundPhase(
        number=7,
        name="Final Synthesis",
        description="Each agent synthesizes discussion and revises proposal to final form",
        focus="Polished final positions, integrated insights, honest uncertainty",
        cognitive_mode="Synthesizer",
    ),
    RoundPhase(
        number=8,
        name="Final Adjudication",
        description="Voting, judge verdict, Opus 4.5 synthesis, download links",
        focus="Final votes, judge selection, 1200-word conclusion, export formats",
        cognitive_mode="Adjudicator",
    ),
]

# Derived defaults (kept in sync with config)
DEFAULT_MIN_ROUNDS_BEFORE_EARLY_STOP = max(DEFAULT_ROUNDS - 1, 1)


@dataclass
class DebateProtocol:
    """Configuration for how multi-agent debates are conducted.

    DebateProtocol controls the structure, rules, and behaviors of debates
    run by Arena. It defines how agents interact, when consensus is reached,
    and what optimizations are applied.

    Categories:
        Topology: How agents communicate (all-to-all, ring, star, etc.)
        Rounds: Number and structure of debate phases
        Consensus: How agreement is determined (majority, judge, weighted)
        Role Assignment: Proposers, critics, judges, and cognitive roles
        Early Termination: When to stop before max rounds
        Human Participation: User voting and suggestions
        Quality Enhancements: Verification, evidence weighting, calibration
        Bias Mitigation: Position shuffling, self-vote detection
        Timeouts: Per-debate and per-round limits

    Common Configurations:
        Default (9 rounds, judge consensus):
            protocol = DebateProtocol()

        Quick (3 rounds, majority):
            protocol = DebateProtocol(
                rounds=3,
                consensus="majority",
                use_structured_phases=False,
            )

        High-assurance (supermajority, formal verification):
            protocol = DebateProtocol(
                consensus="supermajority",
                consensus_threshold=0.8,
                formal_verification_enabled=True,
                enable_trickster=True,
            )

        Cost-optimized (early stopping, minimal rounds):
            protocol = DebateProtocol(
                early_stopping=True,
                early_stop_threshold=0.7,
                min_rounds_before_early_stop=2,
            )

    Topology Options:
        - "all-to-all": Every agent critiques every other (default)
        - "sparse": Random subset of critique connections
        - "round-robin": Sequential critique passing
        - "ring": Each agent critiques next agent in ring
        - "star": Hub agent receives/sends all critiques
        - "random-graph": Random topology each round

    Consensus Mechanisms:
        - "majority": Simple vote count, most wins
        - "supermajority": Requires threshold (e.g., 66%)
        - "unanimous": All agents must agree
        - "judge": Designated judge makes final call
        - "weighted": Votes weighted by ELO ratings
        - "byzantine": PBFT-style fault-tolerant consensus
        - "none": No consensus, return all proposals
        - "any": First valid proposal wins

    See Also:
        - Arena: Uses protocol to configure debate execution
        - ARAGORA_AI_PROTOCOL: Production configuration for aragora.ai
        - ARAGORA_AI_LIGHT_PROTOCOL: Faster 5-round variant
    """

    topology: Literal["all-to-all", "sparse", "round-robin", "ring", "star", "random-graph"] = (
        "all-to-all"
    )
    topology_sparsity: float = (
        0.5  # fraction of possible critique connections (for sparse/random-graph)
    )
    topology_hub_agent: str | None = None  # for star topology, which agent is the hub
    rounds: int = DEFAULT_ROUNDS  # Structured default format (0-8, 9 phases)

    # Structured round phases: Use predefined phase structure for each round
    # When enabled, each round has a specific focus (Analysis, Skeptic, Lateral, etc.)
    use_structured_phases: bool = True  # Enable structured 9-round format
    round_phases: list[RoundPhase] | None = (
        None  # Custom phases (uses STRUCTURED_ROUND_PHASES if None)
    )

    consensus: Literal[
        "majority",
        "unanimous",
        "judge",
        "none",
        "weighted",
        "supermajority",
        "any",
        "byzantine",
        "prover_estimator",
    ] = "judge"
    consensus_threshold: float = 0.6  # fraction needed for majority
    allow_abstain: bool = True
    require_reasoning: bool = True

    # Prover-Estimator protocol settings
    prover_estimator_max_rounds: int = 2
    prover_estimator_context: str = ""
    # Participation quorum: minimum fraction/count of agents that must vote
    min_participation_ratio: float = 0.5
    min_participation_count: int = 2

    # Role assignments
    proposer_count: int = -1  # -1 means all agents propose (default for 9-round format)
    critic_count: int = -1  # -1 means all agents critique
    critique_required: bool = True  # require critiques before consensus

    # Judge selection (for consensus="judge" mode)
    # "elo_ranked" selects highest ELO-rated agent from EloSystem (requires elo_system param)
    judge_selection: Literal[
        "random",
        "voted",
        "last",
        "elo_ranked",
        "calibrated",
        "crux_aware",
    ] = "random"

    # Agreement intensity (0-10): Controls how much agents agree vs disagree
    # 0 = strongly disagree 100% of the time (adversarial)
    # 5 = balanced (agree/disagree based on argument quality)
    # 10 = fully incorporate others' opinions (collaborative)
    # Research shows intensity=2 (slight disagreement bias) often improves accuracy
    agreement_intensity: int = 5

    # Early stopping: End debate when agents agree further rounds won't help
    # Based on ai-counsel pattern - can save 40-70% API costs
    # Default 0.85 = high bar but achievable; ARAGORA_AI_PROTOCOL overrides to 0.95
    early_stopping: bool = True
    early_stop_threshold: float = 0.85  # fraction of agents saying stop to trigger
    min_rounds_before_early_stop: int = (
        DEFAULT_MIN_ROUNDS_BEFORE_EARLY_STOP  # minimum rounds before allowing early exit
    )

    # Asymmetric debate roles: Assign affirmative/negative/neutral stances
    # Forces perspective diversity, prevents premature consensus
    asymmetric_stances: bool = False  # Enable asymmetric stance assignment
    rotate_stances: bool = True  # Rotate stances between rounds

    # Semantic convergence detection
    # Auto-detect consensus without explicit voting
    convergence_detection: bool = True
    convergence_threshold: float = (
        0.85  # Similarity for convergence (matches ConvergenceDetector default)
    )
    divergence_threshold: float = 0.40  # Below this is diverging

    # Statistical stability detection (Beta-Binomial model)
    # Uses KS-distance between vote distributions to detect when consensus has stabilized
    # Based on: https://arxiv.org/abs/2510.12697 (Multi-Agent Debate for LLM Judges)
    enable_stability_detection: bool = False  # Off by default for backwards compatibility
    stability_threshold: float = 0.85  # Probability threshold for stability
    stability_ks_threshold: float = 0.1  # Max KS-distance to consider stable
    stability_min_stable_rounds: int = 1  # Consecutive stable rounds required

    # Vote option grouping: Merge semantically similar vote choices
    # Prevents artificial disagreement from wording variations
    vote_grouping: bool = True
    vote_grouping_threshold: float = 0.85  # Similarity to merge options

    # Judge-based termination: Single judge decides when debate is conclusive
    # Different from early_stopping (agent votes) - uses a designated judge
    judge_termination: bool = False
    min_rounds_before_judge_check: int = 2  # Check only after this many rounds

    # Human participation settings
    user_vote_weight: float = (
        0.5  # Weight of user votes relative to agent votes (0.5 = half weight)
    )

    # Conviction-weighted voting (intensity 1-10 scale)
    # User votes with high conviction (8-10) count more than low conviction (1-3)
    user_vote_intensity_scale: int = 10  # Max intensity value
    user_vote_intensity_neutral: int = 5  # Neutral intensity (multiplier = 1.0)
    user_vote_intensity_min_multiplier: float = 0.5  # Multiplier at intensity=1
    user_vote_intensity_max_multiplier: float = 2.0  # Multiplier at intensity=10

    # Audience suggestion injection
    audience_injection: Literal["off", "summary", "inject"] = "off"

    # Pre-debate web research
    enable_research: bool = True  # Enable web research before debates

    # Cognitive role rotation (Heavy3-inspired)
    # Assigns different cognitive roles (Analyst, Skeptic, Lateral Thinker, Synthesizer)
    # to each agent per round, ensuring diverse perspectives
    role_rotation: bool = True  # Enable role rotation (cognitive diversity)
    role_rotation_config: RoleRotationConfig | None = None  # Custom role config

    # Dynamic role matching (calibration-based)
    # Uses agent calibration scores and expertise to assign optimal roles
    # Overrides simple rotation when enabled
    role_matching: bool = True  # Enable calibration-based role matching
    role_matching_config: RoleMatchingConfig | None = None  # Custom matching config

    # Debate timeout (seconds) - prevents runaway debates
    # Uses ARAGORA_DEBATE_TIMEOUT env var (default 900s = 15 min)
    # Set to 0 for unlimited (not recommended for production)
    # Increased to 1200s (20 min) to allow 6+ min for 7-round debates
    timeout_seconds: int = int(max(1200, DEBATE_TIMEOUT_SECONDS))  # Max time for entire debate

    # Round timeout should exceed agent timeout (AGENT_TIMEOUT_SECONDS)
    # to allow all parallel agents to complete. Minimum 90s per round for thorough analysis.
    round_timeout_seconds: int = int(max(90, AGENT_TIMEOUT_SECONDS + 60))  # Per-round timeout

    # Orchestration speed policy: fast-first routing with bounded parallelism.
    # Disabled by default for conservative backwards compatibility.
    fast_first_routing: bool = False
    # Low-contention means small debates where we can prioritize speed.
    fast_first_low_contention_agent_threshold: int = 3
    # In fast-first mode, evaluate this many critics per proposal at most.
    fast_first_max_critics_per_proposal: int = 2
    # Earliest round to start fast-first heuristics.
    fast_first_min_round: int = 2
    # Require very low critique pressure before probing early consensus exit.
    fast_first_max_total_issues: int = 2
    fast_first_max_critique_severity: float = 0.2
    # If convergence probe similarity exceeds this in low-contention mode, exit early.
    fast_first_convergence_threshold: float = 0.9
    fast_first_early_exit: bool = True
    # Per-debate parallelism bounds (hard-capped by global config in execution layer).
    max_parallel_critiques: int = MAX_CONCURRENT_CRITIQUES
    max_parallel_revisions: int = MAX_CONCURRENT_REVISIONS

    # Debate rounds phase timeout - at least 6 minutes (360s) for all rounds
    debate_rounds_timeout_seconds: int = 420  # 7 minutes for debate_rounds phase

    # Breakpoints: Human-in-the-loop intervention points
    # When enabled, debates can pause at critical moments for human guidance
    enable_breakpoints: bool = True  # Enable breakpoint detection
    breakpoint_config: BreakpointConfig | None = None  # Custom breakpoint thresholds

    # Calibration tracking: Record prediction accuracy for calibration curves
    # When enabled, agent prediction confidence is tracked against outcomes
    enable_calibration: bool = True  # Enable calibration tracking by default

    # Settlement tracking: Map debate claims to measurable future outcomes
    # When enabled, verifiable predictions are extracted from debate results
    # and tracked for later resolution against actual outcomes.
    enable_settlement_tracking: bool = False  # Opt-in: requires explicit resolution

    # Rhetorical observer: Passive commentary on debate dynamics
    # Detects patterns like concession, rebuttal, synthesis for audience engagement
    enable_rhetorical_observer: bool = True  # Enable rhetorical pattern detection

    # Trickster for hollow consensus detection
    # Challenges convergence that lacks evidence quality
    enable_trickster: bool = True  # Enable hollow consensus detection by default
    trickster_sensitivity: float = 0.7  # Threshold for triggering challenges

    # Prompt evolution: Learn from debate outcomes to improve agent prompts
    # When enabled, PromptEvolver extracts winning patterns and updates prompts
    enable_evolution: bool = True  # Enable prompt evolution from debate outcomes

    # Formal verification during consensus: Claim verification for quality
    # When enabled, claims in proposals are verified using pattern matching
    # during vote weighting. Verified claims get a weight bonus.
    # Enabled by default to improve debate quality feedback loop.
    verify_claims_during_consensus: bool = True  # Enable claim verification
    verification_weight_bonus: float = 0.2  # Boost for verified claims (0.0-1.0)
    verification_timeout_seconds: float = 5.0  # Quick timeout per verification

    # Evidence citation weighting: Reward votes that cite evidence
    # When enabled, votes that properly reference evidence from evidence_pack
    # receive a weight bonus during consensus. Encourages factual grounding.
    # Detects EVID-xxx patterns in vote reasoning.
    enable_evidence_weighting: bool = True  # Enable evidence citation bonuses
    evidence_citation_bonus: float = 0.15  # Bonus per evidence citation (0.0-1.0)

    # Pulse/Trending context injection: Inject current trending topics into prompts
    # When enabled, trending topics from Pulse (HN, Reddit, Google Trends, GitHub)
    # are formatted and injected into proposal/revision prompts for timely context.
    # Cross-pollination: Trending context provides real-time relevance for debates.
    enable_trending_injection: bool = True  # Enable trending topic injection by default
    trending_injection_max_topics: int = 3  # Max trending topics to inject per prompt
    trending_relevance_filter: bool = True  # Only include topics relevant to debate task

    # ThinkPRM: Process Reward Models for step-wise debate verification
    # When enabled, debate rounds are verified for logical consistency using
    # verbalized reasoning (arXiv:2504.16828). Runs after debate completion.
    enable_think_prm: bool = False  # Opt-in: requires extra model calls
    think_prm_verifier_agent: str = "claude"  # Agent to use for verification
    think_prm_parallel: bool = True  # Verify steps in parallel
    think_prm_max_parallel: int = 3  # Max concurrent verifications

    # LLM question classification: Improves persona selection but requires a model call.
    # In offline/demo mode, disable to avoid network-backed classification.
    enable_llm_question_classification: bool = True

    # Mandatory synthesis generation: Default uses external Anthropic models with fallback.
    # Disable in offline/demo mode to avoid attempting network calls; synthesis will be
    # produced by combining proposals instead.
    enable_llm_synthesis: bool = True

    # ===== Agent-as-a-Judge Bias Mitigation (arXiv:2508.02994) =====
    # Position bias: Shuffle proposal order and average votes across permutations
    # Research shows LLMs favor proposals in certain positions (first/last)
    enable_position_shuffling: bool = False  # Enable multi-permutation voting
    position_shuffling_permutations: int = 3  # Number of orderings to average

    # Self-enhancement bias: Detect and penalize agents voting for own proposals
    # LLMs exhibit self-preference, favoring outputs they generated
    enable_self_vote_mitigation: bool = False  # Enable self-vote detection
    self_vote_mode: str = "downweight"  # "exclude", "downweight", "log_only"
    self_vote_downweight: float = 0.5  # Weight multiplier when mode="downweight"

    # Verbosity bias: Penalize excessively long proposals
    # LLMs tend to favor longer responses regardless of quality
    enable_verbosity_normalization: bool = False  # Enable length penalty
    verbosity_target_length: int = 1000  # Ideal proposal length in chars
    verbosity_penalty_threshold: float = 3.0  # Penalize if > 3x target
    verbosity_max_penalty: float = 0.3  # Maximum 30% weight reduction

    # Judge deliberation: Judges debate before final verdict
    # Multi-agent debate among judges improves reliability
    enable_judge_deliberation: bool = False  # Enable judge debate
    judge_deliberation_rounds: int = 2  # Rounds of judge discussion

    # Process-based evaluation: Multi-criteria rubric scoring
    # Evaluate reasoning quality, not just final answer
    enable_process_evaluation: bool = False  # Enable rubric evaluation
    enable_process_verification: bool = False  # Gate consensus on process score
    process_verification_threshold: float = 0.6  # Minimum avg process score
    process_verification_hard_gate: bool = False  # Block consensus if below threshold

    # Formal proof verification: Use Lean4/Z3 to verify consensus claims
    # When enabled, attempts machine-checkable proof of final consensus
    # Requires formal verification backends to be installed (z3-solver, etc.)
    formal_verification_enabled: bool = False  # Enable formal proof verification
    formal_verification_languages: list[str] = field(
        default_factory=lambda: ["z3_smt"]
    )  # Languages to try: z3_smt, lean4
    formal_verification_timeout: float = 30.0  # Timeout for proof search (seconds)
    enable_hilbert_proofing: bool = False  # Enable recursive proof decomposition
    hilbert_max_depth: int = 2  # Max recursion depth for proofing
    hilbert_min_subclaims: int = 2  # Min subclaims to branch

    # Byzantine consensus configuration (for consensus="byzantine")
    # PBFT-style fault-tolerant consensus tolerating f faulty nodes where n >= 3f+1
    # Adapted from claude-flow (MIT License)
    byzantine_fault_tolerance: float = 0.33  # Max fraction of faulty agents (default 1/3)
    byzantine_phase_timeout: float = 30.0  # Timeout per PBFT phase (seconds)
    byzantine_max_view_changes: int = 3  # Max leader changes before failure

    # Bead tracking: Git-backed audit trail for debate decisions (Gastown pattern)
    # When enabled, creates a Bead for each debate decision that meets confidence threshold
    # Beads are stored in JSONL format with optional git backing for auditability
    enable_bead_tracking: bool = False  # Enable bead creation for debate decisions
    bead_min_confidence: float = 0.5  # Min confidence to create a bead (0.0-1.0)
    bead_auto_commit: bool = False  # Auto-commit beads to git after creation

    # Hook tracking: GUPP (Guaranteed Unconditional Processing Priority) recovery
    # When enabled, debate work is tracked via hook queues for crash recovery.
    # If an agent crashes mid-debate, work is recovered on startup.
    # Requires enable_bead_tracking=True for full functionality.
    enable_hook_tracking: bool = False  # Enable GUPP-style hook tracking
    hook_max_recovery_age_hours: int = 24  # Max age of recoverable debate work (hours)

    # Molecule tracking: Gastown-inspired work decomposition for multi-phase debates
    # When enabled, debate phases are tracked as molecules with:
    # - Capability requirements: what skills are needed per phase
    # - Agent affinity: which agents perform best on each phase type
    # - Dependency resolution: phases execute in proper order
    # - Failure recovery: failed phases can be reassigned to other agents
    enable_molecule_tracking: bool = True  # Enable molecule-based phase tracking
    molecule_max_attempts: int = 3  # Max retry attempts per molecule

    # Checkpointing: Pause/resume for long-running debates
    # When enabled, checkpoints are created at key milestones for crash recovery.
    # Checkpoints enable debate resumption from the last saved state.
    # Uses CheckpointManager from ArenaConfig (auto-created with DatabaseCheckpointStore)
    checkpoint_after_rounds: bool = True  # Save checkpoint after each round
    checkpoint_before_consensus: bool = True  # Save checkpoint before consensus phase
    checkpoint_interval_rounds: int = 1  # Create checkpoint every N rounds
    checkpoint_cleanup_on_success: bool = True  # Delete checkpoints after successful completion
    checkpoint_keep_on_success: int = (
        0  # Number of checkpoints to keep after success (0 = delete all)
    )

    # Agent channels: Peer-to-peer messaging between agents during debates
    # When enabled, agents can communicate directly via broadcast/direct messages
    # Supports threaded conversations, message handlers, and context injection
    enable_agent_channels: bool = True  # Enable peer messaging during debates
    agent_channel_max_history: int = 100  # Max messages to retain in channel history

    # Multi-language support: Translate debates for international audiences
    # When enabled, debate messages and conclusions can be translated to target languages
    # Uses LLM-based translation with caching for efficiency
    enable_translation: bool = False  # Enable multi-language debate support
    default_language: str = "en"  # Default language code (ISO 639-1)
    target_languages: list[str] = field(
        default_factory=list
    )  # Languages to translate conclusions to (e.g., ["es", "fr", "de"])
    auto_detect_language: bool = True  # Auto-detect source language of messages
    translate_messages: bool = True  # Translate messages between rounds
    translate_conclusions: bool = True  # Translate final conclusions

    # Decision plan auto-creation: Automatically create DecisionPlan after high-confidence debates
    # When enabled, a DecisionPlan is created after debate completion if confidence exceeds threshold
    # Plans can be auto-approved (for low-risk) or require manual approval (for high-risk)
    auto_create_plan: bool = False  # Enable automatic decision plan creation
    plan_min_confidence: float = 0.7  # Min confidence to create plan (0.0-1.0)
    plan_approval_mode: str = "risk_based"  # "always", "never", "risk_based"
    plan_budget_limit_usd: float | None = None  # Budget limit for plan execution

    # Deliberation template: inject domain-specific template context into prompts
    deliberation_template: str | None = None  # Template name from deliberation registry

    # Privacy anonymization: Automatically anonymize PII in debate prompts and content
    # Uses HIPAAAnonymizer to redact names, SSNs, emails, phone numbers, etc.
    enable_privacy_anonymization: bool = False
    privacy_anonymization_method: str = "redact"  # "redact", "hash", "pseudonymize"

    # Adaptive consensus: Adjusts consensus threshold based on voter calibration quality
    # Well-calibrated voters (low Brier) → lower threshold; poorly-calibrated → higher
    enable_adaptive_consensus: bool = False  # Opt-in: requires calibration data

    # Dialectical synthesis: Hegelian thesis/antithesis/synthesis after consensus
    # Generates a combined position from opposing proposals instead of just voting
    enable_synthesis: bool = False  # Opt-in: adds synthesis phase after consensus
    synthesis_confidence_threshold: float = 0.5  # Min confidence for synthesis result

    # Knowledge injection flywheel: Injects past debate receipts from KM into context
    # Completes the loop: Debate → Receipt → KM (persist) → KM (query) → Next Debate
    enable_knowledge_injection: bool = False  # Opt-in: requires Knowledge Mound
    knowledge_injection_max_receipts: int = 3  # Max past receipts to inject

    # Codebase grounding: Inject codebase structure into debate context
    # Enables code-aware debates where agents can reference actual file paths and symbols
    enable_codebase_grounding: bool = False  # Opt-in: requires codebase_path in MemoryConfig

    # Content moderation: Run spam/quality check on debate task before execution
    # Blocks debates with spam/low-quality prompts before burning API tokens
    enable_content_moderation: bool = False  # Opt-in: uses SpamModerationIntegration

    # Context trust-tiering: mark external/retrieved prompt context as untrusted
    # and instruct agents to treat such context as data, not executable instructions.
    enable_context_trust_tiering: bool = True
    detect_context_taint: bool = True  # Scan untrusted sections for injection-like patterns

    # Formal verification: Verify consensus claims using Z3/Lean theorem provers
    # Adds mathematical proof validation to debate conclusions when enabled
    # This is a convenience alias that activates formal_verification_enabled
    enable_formal_verification: bool = False  # Opt-in: requires Z3 or Lean installation

    # Epistemic hygiene: Enforce rigorous reasoning standards in debates
    # When enabled, agents must:
    # - Include at least one alternative considered and why it was rejected
    # - State what evidence would falsify each claim
    # - Express confidence levels (0-1) on their claims
    # - Surface explicit unknowns each round
    # Claims missing falsifiers or confidence are penalized in consensus scoring.
    enable_epistemic_hygiene: bool = False  # Opt-in: enforces reasoning standards
    epistemic_hygiene_penalty: float = 0.15  # Consensus penalty for missing epistemic elements
    epistemic_min_alternatives: int = 1  # Min alternatives per proposal
    epistemic_require_falsifiers: bool = True  # Require falsifiability statements
    epistemic_require_confidence: bool = True  # Require confidence intervals on claims
    epistemic_require_unknowns: bool = True  # Require explicit unknowns each round

    # Extended thinking: Enable transparent reasoning chains from Anthropic agents.
    # When set, AnthropicAPIAgent uses the thinking API to produce step-by-step
    # reasoning that is captured as debate metadata for explainability and
    # decision receipts.  Only affects Anthropic-backed agents; other providers
    # ignore this setting.
    thinking_budget: int | None = None  # Token budget for extended thinking (None = disabled)

    def get_round_phase(self, round_number: int) -> RoundPhase | None:
        """Get the phase configuration for a specific round.

        Args:
            round_number: 0-indexed round number (0 = Context Gathering, 1-7 = debate, 8 = Adjudication)

        Returns:
            RoundPhase for the round, or None if not using structured phases
        """
        if not self.use_structured_phases:
            return None

        phases = self.round_phases or STRUCTURED_ROUND_PHASES
        if 0 <= round_number < len(phases):
            return phases[round_number]
        return None

    @classmethod
    def with_gold_path(
        cls,
        min_confidence: float = 0.7,
        approval_mode: str = "risk_based",
        budget_limit_usd: float | None = None,
        **kwargs: Any,
    ) -> DebateProtocol:
        """Create a protocol with Gold Path enabled.

        Gold Path automatically creates DecisionPlans after debates that reach
        consensus with sufficient confidence. Plans can be auto-approved or
        require manual approval based on risk level.

        Args:
            min_confidence: Minimum confidence to create a plan (default 0.7)
            approval_mode: "always", "never", "risk_based", or "confidence_based"
            budget_limit_usd: Optional budget limit for plan execution
            **kwargs: Additional DebateProtocol parameters

        Returns:
            DebateProtocol with Gold Path enabled

        Example:
            protocol = DebateProtocol.with_gold_path(
                min_confidence=0.8,
                rounds=5,
            )
            arena = Arena(environment=env, agents=agents, protocol=protocol)
        """
        return cls(
            auto_create_plan=True,
            plan_min_confidence=min_confidence,
            plan_approval_mode=approval_mode,
            plan_budget_limit_usd=budget_limit_usd,
            **kwargs,
        )

    @classmethod
    def with_full_flywheel(cls, **kwargs: Any) -> DebateProtocol:
        """Create a protocol with all knowledge flywheel features enabled.

        Enables adaptive consensus, dialectical synthesis, and knowledge
        injection — the three feedback loops that make debates self-improving.

        Returns:
            DebateProtocol with all flywheel features enabled.
        """
        defaults = {
            "enable_adaptive_consensus": True,
            "enable_synthesis": True,
            "enable_knowledge_injection": True,
            "enable_trickster": True,
            "auto_create_plan": True,
        }
        defaults.update(kwargs)
        return cls(**defaults)  # type: ignore[arg-type]

    @classmethod
    def with_epistemic_hygiene(
        cls,
        penalty: float = 0.15,
        min_alternatives: int = 1,
        **kwargs: Any,
    ) -> DebateProtocol:
        """Create a protocol with epistemic hygiene enforcement.

        Agents must include alternatives considered, falsifiability statements,
        confidence intervals, and explicit unknowns in every proposal and
        revision.  Claims missing required elements are penalized during
        consensus vote weighting.

        Args:
            penalty: Consensus weight penalty for missing elements (default 0.15)
            min_alternatives: Minimum alternatives per proposal (default 1)
            **kwargs: Additional DebateProtocol parameters

        Returns:
            DebateProtocol with epistemic hygiene enabled.

        Example:
            protocol = DebateProtocol.with_epistemic_hygiene(
                penalty=0.2,
                rounds=5,
            )
            arena = Arena(environment=env, agents=agents, protocol=protocol)
        """
        return cls(
            enable_epistemic_hygiene=True,
            epistemic_hygiene_penalty=penalty,
            epistemic_min_alternatives=min_alternatives,
            epistemic_require_falsifiers=True,
            epistemic_require_confidence=True,
            epistemic_require_unknowns=True,
            **kwargs,
        )


def user_vote_multiplier(intensity: int, protocol: DebateProtocol) -> float:
    """
    Calculate conviction-weighted vote multiplier based on intensity.

    Args:
        intensity: User's conviction level (1-10)
        protocol: DebateProtocol with intensity scaling parameters

    Returns:
        Bounded weight multiplier between min_multiplier and max_multiplier
    """
    # Normalize intensity to 1-10 range
    intensity = max(1, min(protocol.user_vote_intensity_scale, intensity))

    # Calculate position relative to neutral (0 = neutral, negative = low, positive = high)
    neutral = protocol.user_vote_intensity_neutral
    scale = protocol.user_vote_intensity_scale

    if intensity == neutral:
        return 1.0

    if intensity < neutral:
        # Below neutral: interpolate between min_multiplier and 1.0
        # intensity=1 -> min_multiplier, intensity=neutral -> 1.0
        ratio = (intensity - 1) / (neutral - 1) if neutral > 1 else 0
        return (
            protocol.user_vote_intensity_min_multiplier
            + (1.0 - protocol.user_vote_intensity_min_multiplier) * ratio
        )
    else:
        # Above neutral: interpolate between 1.0 and max_multiplier
        # intensity=neutral -> 1.0, intensity=scale -> max_multiplier
        ratio = (intensity - neutral) / (scale - neutral) if scale > neutral else 0
        return 1.0 + (protocol.user_vote_intensity_max_multiplier - 1.0) * ratio


# =============================================================================
# Aragora.ai Web UI Default Protocol
# =============================================================================
# This preset is used for debates launched from the aragora.ai main input field.
# CLI, SDK, and API users retain full flexibility with custom configurations.

ARAGORA_AI_PROTOCOL = DebateProtocol(
    # Structured format (defaults to ARAGORA_DEFAULT_ROUNDS)
    rounds=DEFAULT_ROUNDS,
    use_structured_phases=True,
    round_phases=None,  # Uses STRUCTURED_ROUND_PHASES (DEFAULT_ROUNDS phases)
    # Judge-based consensus for final decision
    consensus="judge",
    consensus_threshold=0.6,
    # All agents participate
    topology="all-to-all",
    proposer_count=-1,  # All agents propose
    critic_count=-1,  # All agents critique
    # Near-impossible early stopping (require 95% uniform consensus)
    early_stopping=True,
    early_stop_threshold=0.95,
    min_rounds_before_early_stop=DEFAULT_MIN_ROUNDS_BEFORE_EARLY_STOP,
    # High convergence bar to prevent premature consensus
    convergence_detection=True,
    convergence_threshold=0.95,
    divergence_threshold=0.40,
    # Enable Trickster for hollow consensus detection
    enable_trickster=True,
    trickster_sensitivity=0.7,
    # Enable all quality features
    enable_calibration=True,
    enable_rhetorical_observer=True,
    enable_evolution=True,
    enable_evidence_weighting=True,
    verify_claims_during_consensus=True,
    enable_research=True,
    # Role rotation for cognitive diversity
    role_rotation=True,
    role_matching=True,
    # Extended timeouts for 9-round debates
    timeout_seconds=1800,  # 30 minutes total
    round_timeout_seconds=150,  # 2.5 minutes per round
    debate_rounds_timeout_seconds=900,  # 15 minutes for debate rounds phase
    # Enable breakpoints for human intervention
    enable_breakpoints=True,
)

# =============================================================================
# Aragora.ai Light Protocol - Quick Debates
# =============================================================================
# Fast 4-round format for simple questions. ~5 minutes vs ~30 minutes for full.
# Selected via debate_format="light" in API requests.

STRUCTURED_LIGHT_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        number=0,
        name="Quick Context",
        description="Minimal context gathering, core facts only",
        focus="Essential background, key facts",
        cognitive_mode="Researcher",
    ),
    RoundPhase(
        number=1,
        name="Initial Positions",
        description="Establish key viewpoints and main arguments",
        focus="Core positions, primary reasoning",
        cognitive_mode="Analyst",
    ),
    RoundPhase(
        number=2,
        name="Critique & Synthesis",
        description="Combined challenge and integration phase",
        focus="Key disagreements, emerging consensus",
        cognitive_mode="Skeptic",
    ),
    RoundPhase(
        number=3,
        name="Quick Resolution",
        description="Fast judge decision and brief synthesis",
        focus="Final answer, key takeaways",
        cognitive_mode="Adjudicator",
    ),
]

ARAGORA_AI_LIGHT_PROTOCOL = DebateProtocol(
    # 4-round quick format
    rounds=4,
    use_structured_phases=True,
    round_phases=STRUCTURED_LIGHT_ROUND_PHASES,
    # Judge-based for speed
    consensus="judge",
    consensus_threshold=0.6,
    # All agents participate but fewer rounds
    topology="all-to-all",
    proposer_count=-1,
    critic_count=-1,
    # Aggressive early stopping (70% agreement)
    early_stopping=True,
    early_stop_threshold=0.7,
    min_rounds_before_early_stop=2,
    # Lower convergence bar for faster consensus
    convergence_detection=True,
    convergence_threshold=0.8,
    divergence_threshold=0.40,
    # Disable compute-intensive features for speed
    enable_trickster=False,
    enable_calibration=False,
    enable_rhetorical_observer=False,
    enable_evolution=False,
    enable_evidence_weighting=False,
    verify_claims_during_consensus=False,
    enable_research=False,  # Skip web research
    # Simpler roles (no rotation)
    role_rotation=False,
    role_matching=False,
    # Tight timeouts for quick resolution
    timeout_seconds=300,  # 5 minutes total
    round_timeout_seconds=60,  # 1 minute per round
    debate_rounds_timeout_seconds=180,  # 3 minutes for debate rounds
    # No breakpoints in light mode
    enable_breakpoints=False,
)


def resolve_default_protocol(
    protocol: DebateProtocol | None = None,
) -> DebateProtocol:
    """Resolve the default protocol, honoring debate profile overrides."""
    if protocol is not None:
        return protocol

    import os

    profile = os.environ.get("ARAGORA_DEBATE_PROFILE", "").lower()
    if profile in {"full", "nomic", "structured"}:
        try:
            from aragora.nomic.debate_profile import NomicDebateProfile

            return NomicDebateProfile.from_env().to_protocol()
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
            logger.warning("Failed to apply debate profile '%s': %s", profile, exc)

    return DebateProtocol()
