"""PR intelligence brief — protocol + brief schema.

Type contracts for the heterogeneous PR review protocol described in
docs/plans/2026-04-19-pr-intelligence-brief.md (#6306).

Phase boundary: this module is **schema only**. It defines the dataclasses
and enums that successor PRs (#6307 receipt extension, #6304 UI, #6305 cost
controls) will import. There is no orchestration, no debate engine wiring,
no I/O here. Behavior ships in those successor PRs.

Safety boundary preserved from the design brief:
  - machine review is advisory; ReviewBrief.advisory_only is True by default
  - human settlement remains mandatory for merge
  - no bot-approves-bot path

Pattern note: ReviewBrief mirrors aragora.cli.commands.review_queue.ReviewPacket
in shipping ``advisory_only=True`` and ``settlement_note`` as frozen fields, so
any downstream consumer can mechanically check the no-approval property without
trusting prose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timezone
from enum import Enum
from typing import Any, Mapping

UTC = timezone.utc


# --- Enums ----------------------------------------------------------------


class ReviewRole(str, Enum):
    """Roles in a heterogeneous PR review protocol.

    Names match the suggested roles in the design brief, Section "Core
    Deliberation". A protocol run typically uses 3-5 of these; the
    synthesizer is recommended but not required if a different aggregation
    strategy is used.
    """

    LOGIC = "logic_reviewer"
    SECURITY = "security_reviewer"
    MAINTAINABILITY = "maintainability_reviewer"
    SKEPTIC = "skeptic"
    SYNTHESIZER = "synthesizer"


class Recommendation(str, Enum):
    """Top-line recommendation classes a brief can produce.

    Four classes, originally three. The ``APPROVE_WITH_FOLLOWUPS`` class
    was added under #6505 to separate "the panel surfaced real issues
    but none are hard blockers" from "the panel found a real blocker."
    The verdict rule downgrades ``REPAIR_FIRST`` to
    ``APPROVE_WITH_FOLLOWUPS`` when no slot reports a ``high``-severity
    finding, so the sharp-end class (``REPAIR_FIRST``) is reserved for
    cases where at least one lens flags a high-severity issue.

    Same class strings are used by
    ``aragora.cli.commands.review_queue.ReviewPacket`` so downstream
    consumers (queue, UI, ledger) can treat brief and packet outputs
    uniformly when both are present.
    """

    APPROVE_CANDIDATE = "approve_candidate"
    APPROVE_WITH_FOLLOWUPS = "approve_with_followups"
    NEEDS_HUMAN_ATTENTION = "needs_human_attention"
    REPAIR_FIRST = "repair_first"


class DissentPosition(str, Enum):
    """Positions a dissenting reviewer may take, distinct from the majority."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    DEFER = "defer"


# --- Constants ------------------------------------------------------------


ADVISORY_NOTE = (
    "This brief is advisory only. It does not approve or block merge. Human settlement required."
)


# --- Per-role data --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoleFinding:
    """A single role's finding within a review brief.

    One per role contributing to the brief. ``finding_text`` is intentionally
    short (one to three sentences); deep evidence belongs in the receipt
    schema introduced by #6307, not duplicated here.
    """

    role: ReviewRole
    agent: str  # human-readable agent identifier (e.g. "claude-opus-5")
    model: str  # pinned model id (e.g. "claude-opus-5")
    confidence: float  # 0.0 to 1.0
    finding_text: str
    latency_ms: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        return d


@dataclass(frozen=True, slots=True)
class DissentingView:
    """A non-majority position from one reviewer.

    Empty list of these = unanimous. Every dissent must name the agent and
    give a one-to-two-sentence reason so the operator can decide whether to
    expand the relevant evidence panel.
    """

    agent: str
    position: DissentPosition
    reason: str
    role: ReviewRole | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.value
        if self.role is not None:
            d["role"] = self.role.value
        return d


# --- Brief and protocol ---------------------------------------------------


class SynthesisPolicy(str, Enum):
    """How a panel's per-role findings get aggregated into a brief.

    The runner (a successor PR, not this module) picks one policy. Policies
    are values in the contract layer so #6307/#6305/#6304 can branch on them
    without re-defining the enum.
    """

    MAJORITY = "majority"  # plurality across role_findings
    WEIGHTED = "weighted"  # weight by per-finding confidence
    SYNTHESIZER_AGENT = "synthesizer"  # one panel agent acts as synthesizer
    UNANIMOUS_OR_ESCALATE = "unanimous_or_escalate"  # require unanimity, else escalate


@dataclass(frozen=True, slots=True)
class ReviewBrief:
    """A heterogeneous PR review brief.

    Bound to an exact ``head_sha`` so settlement can verify the brief still
    matches what the operator approved. ``advisory_only`` is a frozen field
    so downstream consumers can mechanically check the no-approval property.

    Brief-level confidence and disagreement are first-class because the UI
    (#6304), budget/escalation policy (#6305), and receipt extension (#6307)
    all need an aggregate signal — not just per-finding scores.

    Immutability: sequence fields are ``tuple[...]``, not ``list[...]``,
    because ``frozen=True`` only prevents attribute reassignment — it does
    not stop ``brief.role_findings.append(...)`` mid-flight. Tuples make
    the brief a stable artifact suitable for hashing and receipt storage.

    Packet-SHA preimage (deterministic, implementation guidance for #6307):
      1. Call ``ReviewBrief.to_dict()``.
      2. Remove the ``"packet_sha"`` key from the result.
      3. Serialize the remainder as canonical JSON:
         ``json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``.
      4. UTF-8 encode, take ``hashlib.sha256(bytes).hexdigest()``.
      This rule lives in the docstring (not in code) because the schema
      module is intentionally behavior-free; #6307 implements the hash and
      holds it under test.
    """

    pr_number: int
    repo: str  # owner/name
    head_sha: str
    base_sha: str
    packet_sha: str  # SHA-256 over to_dict() minus this key; see docstring
    recommendation: Recommendation
    top_line: str  # 1-3 sentence executive summary
    role_findings: tuple[RoleFinding, ...]
    dissent: tuple[DissentingView, ...]
    validation_summary: str  # one-paragraph validation evidence summary
    overall_confidence: float  # 0.0..1.0; aggregate across role_findings
    disagreement_score: float  # 0.0..1.0; how far apart the panel was
    total_cost_usd: float
    total_wall_clock_ms: int
    agent_roster: tuple[str, ...]  # ordered sequence of contributing agent ids
    generated_at: str  # ISO-8601 with timezone
    advisory_only: bool = True
    settlement_note: str = ADVISORY_NOTE
    # Aggregate severity counts across the panel's top findings. Keys are
    # "high" | "medium" | "low"; values are ints. Empty when no structured
    # severity signal was supplied (legacy/degraded briefs). Exposed at the
    # brief level so operators can triage without reading every finding.
    findings_severity_counts: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recommendation"] = self.recommendation.value
        d["role_findings"] = [f.to_dict() for f in self.role_findings]
        d["dissent"] = [v.to_dict() for v in self.dissent]
        d["agent_roster"] = list(self.agent_roster)
        d["findings_severity_counts"] = dict(self.findings_severity_counts)
        return d


@dataclass(frozen=True, slots=True)
class PRReviewProtocol:
    """Configuration for one PR review protocol run.

    Panel-oriented topology: a heterogeneous ``model_panel`` participates
    over ``rounds`` debate rounds, and ``synthesis_policy`` determines how
    per-role findings get aggregated into a brief. **Roles are output tags
    on findings, not input constraints binding one model to one role** —
    the runner is free to assign roles to panel members dynamically.

    What this module is NOT:
      - a budget/cost policy (lives in #6305)
      - an orchestrator (lives in a #6306 successor PR)
      - a receipt extension (lives in #6307)

    Defaults here are deliberately structural-only. Anything that smells
    like policy (cost caps, escalation thresholds, model preferences)
    belongs in a later layer.

    Output role contract: ``output_roles`` declares which ``ReviewRole``
    sections a brief produced under this protocol MUST cover (one
    ``RoleFinding`` per output role, in any order). The runner is free to
    assign each output role to any panel member — possibly the same model
    for two roles, possibly different models for the same role across
    rounds — but a brief that omits a declared role is non-conformant.
    Default coverage is the four substantive reviewer roles (LOGIC,
    SECURITY, MAINTAINABILITY, SKEPTIC); SYNTHESIZER is opt-in via
    ``SynthesisPolicy.SYNTHESIZER_AGENT``.
    """

    model_panel: tuple[str, ...]  # heterogeneous model ids participating; immutable
    output_roles: tuple[ReviewRole, ...] = (
        ReviewRole.LOGIC,
        ReviewRole.SECURITY,
        ReviewRole.MAINTAINABILITY,
        ReviewRole.SKEPTIC,
    )
    rounds: int = 1  # debate rounds; 1 = single-pass parallel
    synthesis_policy: SynthesisPolicy = SynthesisPolicy.WEIGHTED
    require_heterogeneous_models: bool = True  # at least two model families in panel
    advisory_only: bool = True  # invariant; cannot be flipped here

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["synthesis_policy"] = self.synthesis_policy.value
        d["model_panel"] = list(self.model_panel)
        d["output_roles"] = [r.value for r in self.output_roles]
        return d
