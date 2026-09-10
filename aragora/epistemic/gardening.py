"""Proactive crux gardening — scheduled re-examination pass (DIC-28 / #6222).

Re-examines resolved and outstanding cruxes for:
- Evidence staleness (via DIC-14 ClaimResult status fields)
- New contradictions (via DIC-26 CoherenceIssue)
- Fragility score shifts (via DIC-25 fragility_score deltas)

Default: **OFF**. Set ``ARAGORA_CRUX_GARDENING_ENABLED=1`` to enable.
Report-only by default; DIC-17 follow-up feed is an opt-in flag.
No queue mutation, no auto-debate, no auto-issue creation.

Issue: https://github.com/synaptent/aragora/issues/6222
Gate: same proof-first Foreman gate as DIC-23..28.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus
from aragora.epistemic.coherence import CoherenceIssue, IncoherenceKind
from aragora.epistemic.crux_receipt import CruxEntry, CruxReceipt

UTC = timezone.utc

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# A fragility shift larger than this threshold surfaces as a "fragility_shift" finding.
DEFAULT_FRAGILITY_SHIFT_THRESHOLD: float = 0.15

# Explicit status enumeration. ``insufficient_evidence`` distinguishes
# "we looked and found nothing wrong" from "we did not have the data
# required to evaluate" — the panel's false-healthy concern.
GardeningStatus = Literal[
    "healthy",
    "stale_evidence",
    "new_contradiction",
    "fragility_shift",
    "insufficient_evidence",
]

STATUS_HEALTHY: GardeningStatus = "healthy"
STATUS_STALE_EVIDENCE: GardeningStatus = "stale_evidence"
STATUS_NEW_CONTRADICTION: GardeningStatus = "new_contradiction"
STATUS_FRAGILITY_SHIFT: GardeningStatus = "fragility_shift"
STATUS_INSUFFICIENT_EVIDENCE: GardeningStatus = "insufficient_evidence"


@dataclass(frozen=True)
class GardeningConfig:
    """Dependency-injected gating configuration for DIC-28 gardening.

    Construct explicitly to decouple domain logic from os.environ reads.
    The default factory (:meth:`from_env`) reads the standard env flags so
    that callers without an explicit config preserve existing behaviour.
    """

    enabled: bool = False
    followup_eligible: bool = False
    fragility_shift_threshold: float = DEFAULT_FRAGILITY_SHIFT_THRESHOLD

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GardeningConfig:
        """Construct a config by reading the standard env flags."""
        e: Mapping[str, str] = env if env is not None else os.environ
        return cls(
            enabled=str(e.get("ARAGORA_CRUX_GARDENING_ENABLED") or "").strip().lower() in _TRUTHY,
            followup_eligible=str(e.get("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED") or "").strip().lower()
            in _TRUTHY,
        )


def crux_gardening_enabled(*, override: bool | None = None) -> bool:
    """Return True when the DIC-28 gardening pass is enabled.

    Reads ``ARAGORA_CRUX_GARDENING_ENABLED``; default False.
    Override kwarg takes precedence for tests.
    """
    if override is not None:
        return override
    return GardeningConfig.from_env().enabled


@dataclass(frozen=True)
class CruxGardeningResult:
    """Per-crux finding from one gardening pass.

    ``status`` is one of: ``healthy``, ``stale_evidence``,
    ``new_contradiction``, ``fragility_shift``, ``insufficient_evidence``.

    Priority policy: when a crux has BOTH stale-evidence and contradiction
    signals, ``status`` is set to ``stale_evidence``. The contradiction
    information is still preserved in :attr:`coherence_issue_kinds` so
    downstream consumers can read both signals without the status field
    masking the contradiction. This reflects the domain policy that a
    crux with stale underlying evidence cannot be reliably evaluated for
    contradictions against current belief state.

    ``insufficient_evidence`` status is returned when the gardening pass
    lacks the upstream data required to evaluate the crux — for example,
    ``garden_resolved_crux`` with no ``claim_results`` AND no
    ``coherence_issues`` for any affected claim, or
    ``garden_outstanding_crux`` called with a missing fragility baseline.
    This is distinct from ``healthy``, which means "evaluated and found
    nothing wrong". Never return ``healthy`` when we haven't looked.

    ``needs_followup`` is True only when :attr:`GardeningConfig.followup_eligible`
    is set and the status is not ``healthy`` or ``insufficient_evidence``.
    """

    crux_id: str
    status: GardeningStatus
    detail: str
    previous_fragility: float | None = None
    current_fragility: float | None = None
    coherence_issue_kinds: tuple[str, ...] = field(default_factory=tuple)
    needs_followup: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["coherence_issue_kinds"] = list(self.coherence_issue_kinds)
        return d


@dataclass(frozen=True)
class GardeningReport:
    """Deterministic report from a full proactive crux gardening pass.

    ``generated_at`` is an ISO-8601 UTC timestamp.
    ``summary`` counts outcomes across both resolved and outstanding sets.
    """

    generated_at: str
    resolved_results: list[CruxGardeningResult]
    outstanding_results: list[CruxGardeningResult]
    summary: dict[str, int]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "resolved_results": [r.to_dict() for r in self.resolved_results],
            "outstanding_results": [r.to_dict() for r in self.outstanding_results],
            "summary": dict(self.summary),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def _coherence_kinds_for_crux(
    claim_ids: list[str],
    coherence_issues: list[CoherenceIssue],
) -> tuple[str, ...]:
    """Return IncoherenceKind values from coherence issues that touch this crux's claims."""
    claim_set = frozenset(claim_ids)
    kinds: list[str] = []
    for issue in coherence_issues:
        if frozenset(issue.belief_ids) & claim_set:
            kinds.append(issue.kind.value)
    return tuple(dict.fromkeys(kinds))  # deduplicate, preserve order


def garden_resolved_crux(
    receipt: CruxReceipt,
    *,
    config: GardeningConfig,
    claim_results: dict[str, ClaimResult] | None = None,
    coherence_issues: list[CoherenceIssue] | None = None,
) -> list[CruxGardeningResult]:
    """Examine all cruxes in a resolved CruxReceipt for staleness or new contradictions.

    Returns one :class:`CruxGardeningResult` per :class:`CruxEntry` in the
    receipt. Staleness is detected by finding a ``fail`` or ``stale``
    ClaimResult for any affected claim. Contradictions are detected via
    DIC-26 coherence issues that reference the crux's affected claims.

    Status rules (no false-healthy when upstream data is missing):

    - ``stale_evidence``: at least one affected claim has a fail/stale
      ClaimResult. Takes priority over contradictions — see the
      ``CruxGardeningResult`` docstring for the rationale. Contradiction
      kinds, if any, are still preserved in ``coherence_issue_kinds``.
    - ``new_contradiction``: no staleness, but a DIC-26 coherence issue
      of kind ``CONTRADICTION`` references at least one affected claim.
    - ``healthy``: we HAVE ClaimResults for all affected claims AND
      found no staleness, AND (if coherence_issues were provided) no
      contradiction. This means we *looked* and found nothing.
    - ``insufficient_evidence``: we lack the upstream data needed to
      evaluate. Examples: no ``claim_results`` supplied, OR no
      ``ClaimResult`` for any affected claim, AND no ``coherence_issues``
      touching them. Never silently report these as ``healthy``.

    ``config`` is REQUIRED. Callers construct it at the pass boundary
    (typically via :meth:`GardeningConfig.from_env` at the top of
    :func:`run_gardening_pass`) and pass it down, so env reads don't
    happen per-crux.
    """
    cfg = config
    results: list[CruxGardeningResult] = []
    cr = claim_results or {}
    ci = coherence_issues or []

    for entry in receipt.cruxes:
        # Per-claim state: observed + stale.
        stale_claims: list[str] = []
        observed_claims: list[str] = []
        for claim_id in entry.affected_claims:
            result = cr.get(claim_id)
            if result is None:
                continue
            observed_claims.append(claim_id)
            if result.status in (ClaimStatus.STALE, ClaimStatus.FAIL):
                stale_claims.append(claim_id)

        coh_kinds = _coherence_kinds_for_crux(entry.affected_claims, ci)
        has_contradiction = IncoherenceKind.CONTRADICTION.value in coh_kinds

        # Status resolution with explicit insufficient_evidence gate.
        # Priority: stale_evidence > new_contradiction > healthy
        #           (insufficient_evidence takes over when no data was
        #            available to evaluate). Contradiction kinds are
        #            always preserved in coherence_issue_kinds so the
        #            priority doesn't mask downstream signal.
        if stale_claims:
            status: GardeningStatus = STATUS_STALE_EVIDENCE
            detail = f"stale or failed claims: {', '.join(stale_claims)}"
        elif has_contradiction:
            status = STATUS_NEW_CONTRADICTION
            detail = f"coherence issues detected: {', '.join(coh_kinds)}"
        elif entry.affected_claims and set(observed_claims) >= set(entry.affected_claims):
            # We had ClaimResults for every affected claim and nothing
            # flagged. Partial claim coverage is insufficient evidence:
            # otherwise one passing claim can mask missing data for the
            # rest of the crux.
            status = STATUS_HEALTHY
            detail = "evidence fresh; no new contradictions"
        elif claim_results is not None and not entry.affected_claims:
            status = STATUS_HEALTHY
            detail = "no affected claims; no contradictions"
        else:
            status = STATUS_INSUFFICIENT_EVIDENCE
            detail = "missing ClaimResults for one or more affected claims; cannot evaluate"

        needs_followup = cfg.followup_eligible and status not in (
            STATUS_HEALTHY,
            STATUS_INSUFFICIENT_EVIDENCE,
        )
        results.append(
            CruxGardeningResult(
                crux_id=entry.crux_id,
                status=status,
                detail=detail,
                coherence_issue_kinds=coh_kinds,
                needs_followup=needs_followup,
            )
        )
    return results


def garden_outstanding_crux(
    entry: CruxEntry,
    *,
    config: GardeningConfig,
    previous_fragility: float | None,
    current_fragility: float | None,
    fragility_shift_threshold: float = DEFAULT_FRAGILITY_SHIFT_THRESHOLD,
) -> CruxGardeningResult:
    """Check whether an outstanding crux has materially shifted in fragility.

    - ``fragility_shift``: absolute delta >= ``fragility_shift_threshold``.
    - ``healthy``: we HAD both fragility values and the delta is within
      threshold. Means we *looked* and found no material shift.
    - ``insufficient_evidence``: either ``previous_fragility`` or
      ``current_fragility`` is None, so no comparison is possible.
      Never reported as ``healthy`` — the panel flagged false-healthy
      on missing baselines as a real defect.

    ``config`` is REQUIRED; callers construct it at the pass boundary.
    """
    cfg = config
    if previous_fragility is None or current_fragility is None:
        return CruxGardeningResult(
            crux_id=entry.crux_id,
            status=STATUS_INSUFFICIENT_EVIDENCE,
            detail="fragility baseline unavailable; cannot evaluate shift",
            previous_fragility=previous_fragility,
            current_fragility=current_fragility,
        )

    delta = abs(current_fragility - previous_fragility)
    if delta >= fragility_shift_threshold:
        direction = "increased" if current_fragility > previous_fragility else "decreased"
        status: GardeningStatus = STATUS_FRAGILITY_SHIFT
        detail = (
            f"fragility {direction} by {delta:.3f} "
            f"(prev={previous_fragility:.3f}, curr={current_fragility:.3f})"
        )
        needs_followup = cfg.followup_eligible
    else:
        status = STATUS_HEALTHY
        detail = f"fragility shift {delta:.3f} within threshold ({fragility_shift_threshold:.3f})"
        needs_followup = False

    return CruxGardeningResult(
        crux_id=entry.crux_id,
        status=status,
        detail=detail,
        previous_fragility=previous_fragility,
        current_fragility=current_fragility,
        needs_followup=needs_followup,
    )


def run_gardening_pass(
    resolved_receipts: list[CruxReceipt],
    outstanding_entries: list[CruxEntry],
    *,
    claim_results: dict[str, ClaimResult] | None = None,
    coherence_issues: list[CoherenceIssue] | None = None,
    fragility_scores: dict[str, tuple[float | None, float | None]] | None = None,
    fragility_shift_threshold: float = DEFAULT_FRAGILITY_SHIFT_THRESHOLD,
    config: GardeningConfig | None = None,
    now: datetime | None = None,
) -> GardeningReport:
    """Run a full gardening pass and return a deterministic :class:`GardeningReport`.

    Parameters
    ----------
    resolved_receipts:
        CruxReceipts from crux-finder debate runs that have been resolved.
    outstanding_entries:
        CruxEntry objects for cruxes still under deliberation.
    claim_results:
        Optional mapping of claim_id → ClaimResult from a DIC-14 verification run.
    coherence_issues:
        Optional list of CoherenceIssue from a DIC-26 coherence scan.
    fragility_scores:
        Optional mapping of crux_id → (previous_fragility, current_fragility) from DIC-25.
    fragility_shift_threshold:
        Minimum absolute delta to surface as a fragility_shift finding.
    config:
        Optional :class:`GardeningConfig`; if omitted, :meth:`GardeningConfig.from_env`
        is used so env-var reads happen once at the pass boundary, not per-crux.
    now:
        Reference time for the report timestamp; defaults to UTC now.
    """
    generated_at = (now or datetime.now(tz=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    # Env is read ONCE at this boundary. Sub-functions receive the resolved
    # config and never touch os.environ themselves.
    cfg = config if config is not None else GardeningConfig.from_env()

    resolved_results: list[CruxGardeningResult] = []
    for receipt in resolved_receipts:
        resolved_results.extend(
            garden_resolved_crux(
                receipt,
                config=cfg,
                claim_results=claim_results,
                coherence_issues=coherence_issues,
            )
        )

    scores = fragility_scores or {}
    outstanding_results: list[CruxGardeningResult] = [
        garden_outstanding_crux(
            entry,
            config=cfg,
            previous_fragility=scores.get(entry.crux_id, (None, None))[0],
            current_fragility=scores.get(entry.crux_id, (None, None))[1],
            fragility_shift_threshold=fragility_shift_threshold,
        )
        for entry in outstanding_entries
    ]

    all_results = resolved_results + outstanding_results
    summary: dict[str, int] = {
        STATUS_HEALTHY: 0,
        STATUS_STALE_EVIDENCE: 0,
        STATUS_NEW_CONTRADICTION: 0,
        STATUS_FRAGILITY_SHIFT: 0,
        STATUS_INSUFFICIENT_EVIDENCE: 0,
        "needs_followup": 0,
    }
    for r in all_results:
        if r.status in summary:
            summary[r.status] += 1
        if r.needs_followup:
            summary["needs_followup"] += 1

    return GardeningReport(
        generated_at=generated_at,
        resolved_results=resolved_results,
        outstanding_results=outstanding_results,
        summary=summary,
    )


__all__ = [
    "DEFAULT_FRAGILITY_SHIFT_THRESHOLD",
    "STATUS_FRAGILITY_SHIFT",
    "STATUS_HEALTHY",
    "STATUS_INSUFFICIENT_EVIDENCE",
    "STATUS_NEW_CONTRADICTION",
    "STATUS_STALE_EVIDENCE",
    "CruxGardeningResult",
    "GardeningConfig",
    "GardeningReport",
    "GardeningStatus",
    "crux_gardening_enabled",
    "garden_outstanding_crux",
    "garden_resolved_crux",
    "run_gardening_pass",
]
