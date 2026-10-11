"""Belief Coherence Monitor (DIC-26 / #6220).

Scans a belief ledger for systemic incoherence — contradictions, evidence
conflicts, and confidence rot — without triggering repair or queue writes.

Default: **OFF**. Set ``ARAGORA_COHERENCE_MONITOR_ENABLED=1`` to enable.
Pure function — no queue mutation, no issue creation, no dispatch changes.
Activation gate: same proof-first Foreman gate as DIC-23..28.

DIC-17 bridge (optional):
    Pass ``emit_followup_proposals=True`` to ``scan_coherence()`` to have
    error-severity issues forwarded to :func:`propose_followup_for_coherence_issue`.
    This requires *both* ``ARAGORA_COHERENCE_MONITOR_ENABLED=1`` and
    ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED=1``. Default is OFF; the bridge
    never fires unless the caller explicitly enables it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.epistemic.followup import FollowupProposal

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_PASSING = frozenset({"pass", "unsupported"})
_FAILING = frozenset({"fail", "stale", "error", "contested"})
_DEFAULT_CONTRADICTION_GAP: float = 0.5
_DEFAULT_MIN_CONFIDENCE: float = 0.3


class IncoherenceKind(str, Enum):
    CONTRADICTION = "contradiction"
    EVIDENCE_CONFLICT = "evidence_conflict"
    CONFIDENCE_ROT = "confidence_rot"


@dataclass(frozen=True)
class BeliefEntry:
    """Flattened belief record for coherence scanning."""

    belief_id: str
    subject: str
    confidence: float
    status: str = "unknown"
    evidence_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "belief_id": self.belief_id,
            "subject": self.subject,
            "confidence": self.confidence,
            "status": self.status,
            "evidence_paths": list(self.evidence_paths),
        }


@dataclass(frozen=True)
class CoherenceIssue:
    kind: IncoherenceKind
    belief_ids: tuple[str, ...]
    detail: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "belief_ids": list(self.belief_ids),
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class CoherenceReport:
    scanned: int
    issues: list[CoherenceIssue] = field(default_factory=list)
    enabled: bool = True
    # DIC-17 bridge output — populated by scan_coherence() only when
    # emit_followup_proposals=True AND epistemic_followup_enabled().
    # Default is empty; callers must not assume proposals are always present.
    proposals: list[FollowupProposal] = field(default_factory=list)

    @property
    def coherent(self) -> bool:
        return not self.issues

    @property
    def contradiction_count(self) -> int:
        return sum(1 for i in self.issues if i.kind == IncoherenceKind.CONTRADICTION)

    @property
    def evidence_conflict_count(self) -> int:
        return sum(1 for i in self.issues if i.kind == IncoherenceKind.EVIDENCE_CONFLICT)

    @property
    def confidence_rot_count(self) -> int:
        return sum(1 for i in self.issues if i.kind == IncoherenceKind.CONFIDENCE_ROT)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "scanned": self.scanned,
            "coherent": self.coherent,
            "issue_count": len(self.issues),
            "contradiction_count": self.contradiction_count,
            "evidence_conflict_count": self.evidence_conflict_count,
            "confidence_rot_count": self.confidence_rot_count,
            "issues": [i.to_dict() for i in self.issues],
            "enabled": self.enabled,
        }
        if self.proposals:
            d["proposals"] = [p.to_dict() for p in self.proposals]
        return d


def coherence_monitor_enabled() -> bool:
    """Return True when ``ARAGORA_COHERENCE_MONITOR_ENABLED`` is truthy."""
    raw = str(os.environ.get("ARAGORA_COHERENCE_MONITOR_ENABLED") or "").strip().lower()
    return raw in _TRUTHY


def _detect_contradictions(entries: list[BeliefEntry], gap: float) -> list[CoherenceIssue]:
    by_subject: dict[str, list[BeliefEntry]] = {}
    for e in entries:
        by_subject.setdefault(e.subject, []).append(e)
    issues: list[CoherenceIssue] = []
    for subject, group in by_subject.items():
        if len(group) < 2:
            continue
        high = [e for e in group if e.confidence >= 1.0 - gap]
        low = [e for e in group if e.confidence <= gap]
        if not (high and low):
            continue
        ids = tuple(e.belief_id for e in high + low)
        hi_s = ", ".join(f"{e.belief_id}({e.confidence:.2f})" for e in high)
        lo_s = ", ".join(f"{e.belief_id}({e.confidence:.2f})" for e in low)
        issues.append(
            CoherenceIssue(
                kind=IncoherenceKind.CONTRADICTION,
                belief_ids=ids,
                detail=f"Subject {subject!r}: high [{hi_s}] contradicts low [{lo_s}].",
                severity="error",
            )
        )
    return issues


def _detect_evidence_conflicts(entries: list[BeliefEntry]) -> list[CoherenceIssue]:
    path_map: dict[str, list[BeliefEntry]] = {}
    for e in entries:
        for path in e.evidence_paths:
            path_map.setdefault(path, []).append(e)
    issues: list[CoherenceIssue] = []
    for path, group in path_map.items():
        if len(group) < 2:
            continue
        statuses = {e.status for e in group}
        if statuses & _PASSING and statuses & _FAILING:
            ids = tuple(e.belief_id for e in group)
            issues.append(
                CoherenceIssue(
                    kind=IncoherenceKind.EVIDENCE_CONFLICT,
                    belief_ids=ids,
                    detail=(
                        f"Evidence {path!r} cited by {len(ids)} beliefs with "
                        f"conflicting outcomes: {sorted(statuses)}."
                    ),
                    severity="warning",
                )
            )
    return issues


def _detect_confidence_rot(
    entries: list[BeliefEntry], min_confidence: float
) -> list[CoherenceIssue]:
    issues: list[CoherenceIssue] = []
    for e in entries:
        if e.confidence < min_confidence:
            severity = "error" if e.confidence < min_confidence / 2 else "warning"
            issues.append(
                CoherenceIssue(
                    kind=IncoherenceKind.CONFIDENCE_ROT,
                    belief_ids=(e.belief_id,),
                    detail=(
                        f"Belief {e.belief_id!r} confidence {e.confidence:.2f} "
                        f"below minimum {min_confidence:.2f}."
                    ),
                    severity=severity,
                )
            )
    return issues


def scan_coherence(
    entries: list[BeliefEntry],
    *,
    contradiction_gap: float = _DEFAULT_CONTRADICTION_GAP,
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    enabled: bool | None = None,
    emit_followup_proposals: bool = False,
) -> CoherenceReport:
    """Scan a belief ledger for contradiction, evidence conflict, and rot.

    Args:
        entries: Belief entries to scan.
        contradiction_gap: Confidence delta that constitutes a contradiction.
        min_confidence: Minimum acceptable confidence; lower triggers rot.
        enabled: Override the ``ARAGORA_COHERENCE_MONITOR_ENABLED`` flag.
            ``None`` reads the env var (default behaviour).
        emit_followup_proposals: When True AND ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED``
            is set, error-severity issues are forwarded to the DIC-17 bridge
            and proposals are attached to the returned report. Default False
            per DIC-26 spec: bridge output is opt-in only.
    """
    if enabled is None:
        enabled = coherence_monitor_enabled()
    if not enabled:
        return CoherenceReport(scanned=len(entries), issues=[], enabled=False)
    issues: list[CoherenceIssue] = []
    issues.extend(_detect_contradictions(entries, contradiction_gap))
    issues.extend(_detect_evidence_conflicts(entries))
    issues.extend(_detect_confidence_rot(entries, min_confidence))

    report = CoherenceReport(scanned=len(entries), issues=issues, enabled=True)

    if emit_followup_proposals:
        from aragora.epistemic import epistemic_followup_enabled
        from aragora.epistemic.followup import propose_followup_for_coherence_issue

        if epistemic_followup_enabled():
            for issue in issues:
                proposal = propose_followup_for_coherence_issue(issue)
                if proposal is not None:
                    report.proposals.append(proposal)

    return report


def from_belief_node(node: Any) -> BeliefEntry:
    """Extract a :class:`BeliefEntry` from a ``BeliefNode`` (duck-typed)."""
    status = getattr(getattr(node, "status", None), "value", "unknown")
    posterior = getattr(node, "posterior", None)
    confidence = float(getattr(posterior, "p_true", 0.5))
    evidence_paths = tuple(str(p) for p in getattr(node, "evidence_paths", []))
    return BeliefEntry(
        belief_id=str(getattr(node, "belief_id", "")),
        subject=str(getattr(node, "claim_id", "")),
        confidence=confidence,
        status=status,
        evidence_paths=evidence_paths,
    )
