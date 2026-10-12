"""Review Adjudicator (M0, epic #8747 / issue #8748).

Escapes the PR-review "nitpick treadmill" — two adversarial reviewers who never
both PASS a substantial diff, each surfacing fresh advisory ``[P2]/[P3]`` nits —
by *adjudicating the findings themselves* instead of hand-refereeing round after
round. It **composes** existing Aragora primitives (it does NOT reimplement
them):

* :class:`EvidenceQualityAnalyzer` — scores a finding's specificity /
  concreteness / evidence diversity. Prefer the legacy ``aragora_debate``
  package when installed, otherwise use Aragora's in-tree analyzer.
* :func:`aragora.review.comment_verdicts.has_blocking_finding_or_label`
  — the SAME ``[P0]/[P1]`` detector the gate already trusts (the hard bar).

The adjudicator fires ONLY on a stall (quorum unsatisfied, dissent present, at
least one supportive signal) and returns one of:

* ``SETTLE``   — all dissent is thin (below the groundedness bar): the treadmill
  escape. Findings are preserved for follow-up, never discarded. By default,
  grounded advisory-only dissent is also capped here to honor severity-gated
  dissent; callers may explicitly promote grounded advisory findings to BLOCK.
* ``BLOCK``    — any ``[P0]/[P1]`` is present, OR a grounded advisory finding
  stands with no grounded counter-support under the explicit promotion policy.
  Never suppress a real hard-bar finding.
* ``ESCALATE`` — grounded dissent AND grounded support both exist: a genuine
  two-sided material disagreement that a human should settle (a crux). M0 emits
  a summary escalation; crux-finder bridging (#8747) is a fast-follow.
* ``NOT_APPLICABLE`` — no dissent, or no supportive signal (genuine rejection is
  not a stall). The adjudicator abstains and the existing gate decides.

The groundedness score is a deterministic heuristic composed from the analyzer's
sub-scores (see :func:`score_groundedness`). It is intentionally a fast, cheap
first pass; a fast-follow can plug :class:`aragora.evaluation.llm_judge.LLMJudge`
as the scorer for "real intelligence" on the ambiguous middle. The bias is
conservative: SETTLE requires *every* dissenting finding to be clearly thin unless
the explicit advisory-severity policy caps grounded advisory-only dissent as
follow-up. Hard-bar ``[P0]/[P1]`` findings still always block.

Gated behind ``ARAGORA_ENABLE_REVIEW_ADJUDICATOR`` (default OFF → byte-identical
to today).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, Sequence

from aragora.review.comment_verdicts import (
    has_blocking_finding_or_label,
    highest_blocking_severity,
)

# Groundedness at or above this bar means a finding is substantive enough that it
# must NOT be silently suppressed. Tuned so a concrete finding (file:line + repro
# + specific values) scores well above it and a vague "would be nice" nit well
# below. Conservative by design; override via ``groundedness_bar=``.
DEFAULT_GROUNDEDNESS_BAR = 0.5

_ENABLE_FLAG = "ARAGORA_ENABLE_REVIEW_ADJUDICATOR"
_TRUTHY = {"1", "true", "yes", "on"}


def review_adjudicator_enabled() -> bool:
    """True when the adjudicator is explicitly enabled (default OFF)."""
    return os.getenv(_ENABLE_FLAG, "").strip().lower() in _TRUTHY


def _evidence_quality_analyzer_class() -> Any:
    """Resolve the evidence analyzer without requiring the legacy package."""
    try:
        from aragora_debate.evidence import EvidenceQualityAnalyzer
    except ModuleNotFoundError as exc:
        if exc.name not in {"aragora_debate", "aragora_debate.evidence"}:
            raise
        from aragora.debate.evidence_quality import EvidenceQualityAnalyzer

    return EvidenceQualityAnalyzer


class AdjudicationVerdict(str, Enum):
    SETTLE = "adjudicated_settle"
    BLOCK = "adjudicated_block"
    ESCALATE = "adjudicated_escalate"
    NOT_APPLICABLE = "not_applicable"


class AdvisorySeverityPolicy(str, Enum):
    """How grounded advisory-only findings should affect the final verdict."""

    CAP_AT_ADVISORY = "cap_at_advisory"
    PROMOTE_GROUNDED_TO_BLOCK = "promote_grounded_to_block"


class _ReviewFinding(Protocol):
    """Duck-typed EvidenceItem: family + body + verdict + supportive."""

    family: str
    body: str
    verdict: str

    @property
    def supportive(self) -> bool: ...


@dataclass
class FindingAssessment:
    family: str
    verdict: str
    is_blocking: bool
    highest_severity: str | None
    groundedness: float
    grounded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "verdict": self.verdict,
            "is_blocking": self.is_blocking,
            "highest_severity": self.highest_severity,
            "groundedness": self.groundedness,
            "grounded": self.grounded,
        }


@dataclass
class AdjudicationResult:
    verdict: AdjudicationVerdict
    reason: str
    assessments: list[FindingAssessment] = field(default_factory=list)
    settled_findings: list[str] = field(default_factory=list)
    escalated_findings: list[str] = field(default_factory=list)
    blocking_findings: list[str] = field(default_factory=list)
    groundedness_bar: float = DEFAULT_GROUNDEDNESS_BAR
    advisory_severity_policy: AdvisorySeverityPolicy = AdvisorySeverityPolicy.CAP_AT_ADVISORY

    def to_receipt_dict(self) -> dict[str, Any]:
        """Serializable adjudication summary for the DecisionReceipt/audit log."""
        return {
            "kind": "review_adjudication.v1",
            "verdict": self.verdict.value,
            "reason": self.reason,
            "groundedness_bar": self.groundedness_bar,
            "advisory_severity_policy": self.advisory_severity_policy.value,
            "assessments": [a.to_dict() for a in self.assessments],
            "settled_findings": self.settled_findings,
            "escalated_findings": self.escalated_findings,
            "blocking_findings": self.blocking_findings,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _bounded_score(value: float, *, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite number")
    return round(_clamp(numeric), 4)


def _coerce_advisory_severity_policy(
    policy: AdvisorySeverityPolicy | str,
) -> AdvisorySeverityPolicy:
    if isinstance(policy, AdvisorySeverityPolicy):
        return policy
    try:
        return AdvisorySeverityPolicy(str(policy))
    except ValueError as exc:
        allowed = ", ".join(p.value for p in AdvisorySeverityPolicy)
        raise ValueError(f"advisory_severity_policy must be one of: {allowed}") from exc


def _normalized_verdict(item: _ReviewFinding) -> str:
    return str(getattr(item, "verdict", "")).strip().lower().replace("-", "_").replace(" ", "_")


def _is_supportive_signal(item: _ReviewFinding) -> bool:
    verdict = _normalized_verdict(item)
    if verdict == "changes_requested":
        return False
    return bool(getattr(item, "supportive", verdict == "pass"))


def _is_review_dissent(item: _ReviewFinding) -> bool:
    verdict = _normalized_verdict(item)
    if verdict == "pass":
        return False
    # EvidenceItem.dissenting means "blocking under severity gate"; the Review
    # Adjudicator still needs advisory CHANGES-REQUESTED findings so it can cap,
    # settle, or escalate them explicitly. Verdict wins over contradictory
    # supportive flags so one item cannot be both support and dissent.
    return bool(getattr(item, "dissenting", False)) or verdict == "changes_requested"


def score_groundedness(body: str, *, analyzer: Any | None = None) -> float:
    """Deterministic 0-1 groundedness heuristic for a single review finding.

    Composed from :class:`EvidenceQualityAnalyzer` sub-scores that empirically
    separate a concrete finding from a vague one on short review text:

    * ``specificity_score`` — file:line refs, concrete values, named symbols.
    * specific/(specific+vague) phrase ratio — concreteness vs hedging.
    * ``evidence_diversity`` — variety of evidence markers (repro, data, refs).

    The analyzer's own ``overall_quality`` is diluted on short findings (citation
    density / temporal relevance dominate), so we recombine the discriminating
    dimensions directly. Weights favor specificity and concreteness.
    """
    if analyzer is None:
        # Imported lazily so importing this module never hard-requires the
        # legacy aragora-debate package (keeps the gate import-light).
        analyzer = _evidence_quality_analyzer_class()()

    score = analyzer.analyze(body or "", agent="reviewer")
    total_phrases = score.specific_phrase_count + score.vague_phrase_count
    phrase_ratio = score.specific_phrase_count / total_phrases if total_phrases else 0.5
    composite = 0.5 * score.specificity_score + 0.3 * phrase_ratio + 0.2 * score.evidence_diversity
    return _bounded_score(composite, name="groundedness score")


def adjudicate(
    items: Sequence[_ReviewFinding],
    *,
    groundedness_bar: float = DEFAULT_GROUNDEDNESS_BAR,
    scorer: Callable[[str], float] | None = None,
    advisory_severity_policy: AdvisorySeverityPolicy | str = AdvisorySeverityPolicy.CAP_AT_ADVISORY,
) -> AdjudicationResult:
    """Adjudicate a stalled review over ``items`` (EvidenceItem-shaped).

    Each item is scored **exactly once**; both the recorded ``assessments`` and
    the returned verdict are driven off that single value, so the emitted receipt
    can never contradict itself even when a non-deterministic scorer (e.g.
    ``LLMJudge``) is plugged in (#8749 claude [P2]). The ``[P0]/[P1]`` hard bar is
    evaluated WITHOUT invoking the scorer, so a missing/raising scorer can never
    turn a definite block into a crash (#8749 openai [P2]). Pure and side-effect
    free; does not mutate the items and never contacts the network.

    ``scorer`` defaults to :func:`score_groundedness` bound to a single hoisted
    :class:`EvidenceQualityAnalyzer` (one build per call, not per item — #8749
    claude [P3]).

    ``advisory_severity_policy`` defaults to capping grounded [P2]/[P3]-only
    findings at advisory follow-up so the adjudicator does not reintroduce the
    merge block that severity-gated dissent deliberately removed (#8752). Pass
    ``PROMOTE_GROUNDED_TO_BLOCK`` only for callers that explicitly want the
    original M0 behavior.
    """
    items = list(items)
    groundedness_bar = _bounded_score(groundedness_bar, name="groundedness_bar")
    advisory_severity_policy = _coerce_advisory_severity_policy(advisory_severity_policy)

    # Hard bar FIRST, using ONLY the [P0]/[P1] detector — never the scorer and
    # never the default analyzer. A definite block must not depend on the scorer
    # being present or working (#8749 openai [P2]), and must not import
    # aragora_debate at all when that package is unavailable (#8749 claude [P3]).
    blocking_flags = [has_blocking_finding_or_label(it.body) for it in items]
    if any(blocking_flags):
        assessments = [
            FindingAssessment(
                family=it.family,
                verdict=it.verdict,
                is_blocking=flag,
                highest_severity=highest_blocking_severity(it.body),
                groundedness=0.0,  # deliberately unscored on the hard-bar path
                grounded=False,
            )
            for it, flag in zip(items, blocking_flags)
        ]
        return AdjudicationResult(
            verdict=AdjudicationVerdict.BLOCK,
            reason="blocking [P0]/[P1] finding present; hard bar — not adjudicable",
            assessments=assessments,
            blocking_findings=[it.body for it, flag in zip(items, blocking_flags) if flag],
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    # Applicability BEFORE scoring (#8749 openai [P2] r3): the NOT_APPLICABLE
    # cases need only the verdicts, so decide them without building the default
    # scorer/analyzer or scoring any finding (no import, no side effects on the
    # not-a-stall paths).
    def _unscored_assessments() -> list[FindingAssessment]:
        return [
            FindingAssessment(
                family=it.family,
                verdict=it.verdict,
                is_blocking=False,
                highest_severity=highest_blocking_severity(it.body),
                groundedness=0.0,
                grounded=False,
            )
            for it in items
        ]

    dissenting_items = [it for it in items if _is_review_dissent(it)]
    supportive_items = [it for it in items if _is_supportive_signal(it)]
    if not dissenting_items:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.NOT_APPLICABLE,
            reason="no dissent to adjudicate",
            assessments=_unscored_assessments(),
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )
    if not supportive_items:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.NOT_APPLICABLE,
            reason="no supportive signal; genuine rejection, not a stall",
            assessments=_unscored_assessments(),
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    # It IS a stall worth adjudicating — only now build the default scorer + its
    # single analyzer (deferred past both the hard-bar and NOT_APPLICABLE returns
    # — #8749 claude [P3] / openai [P2]).
    if scorer is None:
        _analyzer = _evidence_quality_analyzer_class()()

        def scorer(body: str) -> float:
            return score_groundedness(body, analyzer=_analyzer)

    # Score each item exactly once. A scorer failure FAILS CLOSED (openai [P2]):
    # never let an exception make a grounded finding look thin and get suppressed.
    scorer_failed = False
    assessments = []
    for it in items:
        try:
            groundedness = _bounded_score(scorer(it.body), name="scorer result")
            grounded = groundedness >= groundedness_bar
        except Exception:  # noqa: BLE001 - fail closed, never crash the gate
            scorer_failed = True
            groundedness = 0.0
            grounded = False
        assessments.append(
            FindingAssessment(
                family=it.family,
                verdict=it.verdict,
                is_blocking=False,
                highest_severity=highest_blocking_severity(it.body),
                groundedness=groundedness,
                grounded=grounded,
            )
        )

    # Drive the verdict off the single per-item assessment (never re-score).
    paired = list(zip(items, assessments))
    dissenting = [(it, a) for it, a in paired if _is_review_dissent(it)]
    supportive = [(it, a) for it, a in paired if _is_supportive_signal(it)]

    # Fail closed (openai [P2]): if groundedness scoring failed for any item, do
    # NOT risk suppressing a real finding as "thin" — escalate to human settlement.
    if scorer_failed:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.ESCALATE,
            reason=(
                "groundedness scoring failed for one or more findings; failing "
                "closed to human settlement rather than risk suppressing a real "
                "finding"
            ),
            assessments=assessments,
            escalated_findings=[it.body for it, _ in dissenting],
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    grounded_dissent = [(it, a) for it, a in dissenting if a.grounded]
    if not grounded_dissent:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.SETTLE,
            reason=(
                "all dissent is advisory and below the groundedness bar; settling "
                "and filing the findings for follow-up"
            ),
            assessments=assessments,
            settled_findings=[it.body for it, _ in dissenting],
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    grounded_support = [(it, a) for it, a in supportive if a.grounded]
    if grounded_support:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.ESCALATE,
            reason=(
                "grounded dissent AND grounded support: a material two-sided "
                "disagreement (crux) — escalating for human settlement"
            ),
            assessments=assessments,
            escalated_findings=[it.body for it, _ in grounded_dissent],
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    if advisory_severity_policy is AdvisorySeverityPolicy.CAP_AT_ADVISORY:
        return AdjudicationResult(
            verdict=AdjudicationVerdict.SETTLE,
            reason=(
                "grounded advisory-only dissent remains capped at advisory by "
                "severity policy; settling and filing the findings for follow-up"
            ),
            assessments=assessments,
            settled_findings=[it.body for it, _ in grounded_dissent],
            groundedness_bar=groundedness_bar,
            advisory_severity_policy=advisory_severity_policy,
        )

    return AdjudicationResult(
        verdict=AdjudicationVerdict.BLOCK,
        reason=(
            "grounded advisory dissent stands with no grounded counter-support; "
            "the finding must be addressed"
        ),
        assessments=assessments,
        blocking_findings=[it.body for it, _ in grounded_dissent],
        groundedness_bar=groundedness_bar,
        advisory_severity_policy=advisory_severity_policy,
    )
