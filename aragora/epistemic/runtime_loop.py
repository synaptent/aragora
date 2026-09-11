"""DIC-23 Dialectical Runtime Loop orchestrator.

Connects the decay monitor (DIC-20), quarantine policy (DIC-21), and
repair pipeline (DIC-22) into a single, observable, receipt-carrying trace:

    DecaySignal
        → apply_quarantine_policy          (DIC-21)
        → propose_repair (optional)        (DIC-22)
        → crux_probe (optional, DIC-15)    (this module)
        → DialecticalEvent                 (this module)

Default posture is *report-only*: no state is mutated, no issues are
created, and nothing is routed to the live queue.

Crux probing is opt-in via ``enable_crux_probe=True`` and
``crux_question=<context string>`` on :func:`run_dialectical_loop`.
When enabled *and* ``ARAGORA_CRUXSET_EMISSION_ENABLED`` is set, the
loop synthesises a minimal crux-analysis payload from the
:class:`~aragora.epistemic.decay_monitor.DecaySignal` reasons and calls
:func:`aragora.reasoning.cruxset_emission.maybe_emit_cruxset`.  A
successful probe sets ``crux_probe_skipped=False`` on the event and
stores a summary under ``metadata["crux_probe"]``.  Any failure (flag
off, no cruxes found, import error) leaves ``crux_probe_skipped=True``
and is swallowed — the probe must not cause loop failures.

Flag: ``ARAGORA_DIALECTICAL_RUNTIME_ENABLED`` (default off).
Dataclasses and ``run_dialectical_loop`` are always importable; the
flag is checked only when ``require_enabled=True`` (the default for
production callers) to avoid silent no-ops. Tests and demos should set
the flag at the process boundary; this module does not mutate
``os.environ``.

Advances: #6217 (DIC-23)
See also: ``docs/plans/2026-04-18-dialectical-runtime-synthesis.md``
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from aragora.epistemic.decay_monitor import DecaySignal
from aragora.epistemic.quarantine_policy import (
    DEFAULT_POLICIES,
    QuarantinePolicy,
    apply_quarantine_policy,
)
from aragora.epistemic.repair import RepairSpec, propose_repair

UTC = timezone.utc

_FLAG = "ARAGORA_DIALECTICAL_RUNTIME_ENABLED"

logger = logging.getLogger(__name__)

# Maps decay-reason kind to a synthetic crux_score used when building the
# analysis payload passed to maybe_emit_cruxset().  Higher scores model
# higher load-bearing potential: a failed claim is a stronger crux candidate
# than merely missing receipts.
_REASON_CRUX_SCORE: dict[str, float] = {
    "failed_claim": 0.85,
    "unresolved_crux": 0.80,
    "verifier_error": 0.75,
    "stale_evidence": 0.60,
    "missing_receipt": 0.50,
}
_DEFAULT_CRUX_SCORE = 0.50


def dialectical_runtime_enabled() -> bool:
    """Return True if the DIC-23 runtime loop is enabled for this process."""
    raw = str(os.environ.get(_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _event_id(unit_id: str, recommended_action: str, ts: str) -> str:
    material = f"drt|{unit_id}|{recommended_action}|{ts}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"drt_{digest}"


def _build_synthetic_crux_payload(signal: DecaySignal, question: str) -> dict[str, Any]:
    """Build a CruxAnalysisResult-shaped dict from a DecaySignal.

    Each reason becomes one crux entry with a score keyed by kind.
    Passed to ``maybe_emit_cruxset`` via the ``analysis_payload`` path.
    """
    cruxes = []
    for i, reason in enumerate(signal.reasons):
        score = _REASON_CRUX_SCORE.get(reason.kind, _DEFAULT_CRUX_SCORE)
        claim_id = reason.claim_id or reason.crux_id or f"decay_reason_{i}"
        cruxes.append(
            {
                "claim_id": claim_id,
                "statement": reason.detail or f"Decay reason: {reason.kind}",
                "author": "decay_monitor",
                "crux_score": score,
                "influence_score": round(score * 0.9, 4),
                "disagreement_score": round(score * 0.7, 4),
                "uncertainty_score": round(1.0 - signal.integrity_score, 4),
                "centrality_score": round(score * 0.8, 4),
                "affected_claims": [claim_id] if reason.claim_id else [],
                "contesting_agents": [],
                "resolution_impact": round(score * (1.0 - signal.integrity_score), 4),
            }
        )

    if not cruxes:
        # No explicit reasons; add one synthetic root cause crux.
        cruxes.append(
            {
                "claim_id": f"decay_root.{signal.code_unit_id}",
                "statement": f"Proof-unit {signal.code_unit_id!r} integrity has decayed.",
                "author": "decay_monitor",
                "crux_score": round(1.0 - signal.integrity_score, 4),
                "influence_score": 0.5,
                "disagreement_score": 0.5,
                "uncertainty_score": round(1.0 - signal.integrity_score, 4),
                "centrality_score": 0.5,
                "affected_claims": [],
                "contesting_agents": [],
                "resolution_impact": round(1.0 - signal.integrity_score, 4),
            }
        )

    return {
        "cruxes": cruxes,
        "total_claims": len(cruxes),
        "total_disagreements": sum(1 for r in signal.reasons if r.kind == "unresolved_crux"),
        "average_uncertainty": round(1.0 - signal.integrity_score, 4),
        "convergence_barrier": round(1.0 - signal.integrity_score, 4),
        "recommended_focus": [c["claim_id"] for c in cruxes[:3]],
    }


def _attempt_crux_probe(signal: DecaySignal, question: str) -> dict[str, Any] | None:
    """Emit a CruxSet from the decay signal; return a summary dict or None.

    Returns None when emission is disabled, no cruxes are found, or any
    exception occurs. Errors are swallowed — probe must not cause failures.
    """
    try:
        from aragora.reasoning.cruxset_emission import maybe_emit_cruxset  # lazy import

        payload = _build_synthetic_crux_payload(signal, question)
        cruxset = maybe_emit_cruxset(
            question=question,
            analysis_payload=payload,
            decision=None,
            provenance={"code_unit_id": signal.code_unit_id, "source": "dialectical_runtime"},
        )
        if cruxset is None:
            return None
        crux_list = list(cruxset.cruxes)
        barrier = round(max((c.load_bearing_score for c in crux_list), default=0.0), 4)
        return {
            "cruxset_id": cruxset.cruxset_id,
            "crux_count": len(crux_list),
            "top_crux_ids": [c.crux_id for c in crux_list[:3]],
            "convergence_barrier": barrier,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("DIC-23 crux probe suppressed: %s", exc)
        return None


@dataclass(frozen=True)
class DialecticalEvent:
    """Canonical trace record for one DIC-23 orchestration pass.

    Carries the decay summary, the quarantine decision, and (optionally) a
    repair spec.  ``crux_probe_skipped`` is ``False`` when the crux probe
    ran successfully and a CruxSet was emitted; ``True`` otherwise (probe
    disabled, emission flag off, no cruxes found, or any transient error).

    When ``crux_probe_skipped`` is ``False``, ``metadata["crux_probe"]``
    holds a lightweight summary with ``cruxset_id``, ``crux_count``,
    ``top_crux_ids``, and ``convergence_barrier``.

    ``prior_receipt_ids`` is the caller-supplied ancestry chain stored as
    an immutable tuple.  ``metadata`` is stored as a shallow-frozen mapping:
    the outer mapping is immutable but nested mutable values are not
    deep-copied.  Callers must not store references to mutable nested
    objects in metadata when receipt-chain immutability matters.
    """

    event_id: str
    code_unit_id: str
    integrity_score: float
    recommended_action: str
    quarantine_action: str
    crux_probe_skipped: bool
    repair_spec: RepairSpec | None
    prior_receipt_ids: tuple[str, ...]
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "code_unit_id": self.code_unit_id,
            "integrity_score": round(self.integrity_score, 4),
            "recommended_action": self.recommended_action,
            "quarantine_action": self.quarantine_action,
            "crux_probe_skipped": self.crux_probe_skipped,
            "repair_spec": self.repair_spec.to_dict() if self.repair_spec else None,
            "prior_receipt_ids": list(self.prior_receipt_ids),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class DialecticalRuntimeError(RuntimeError):
    """Raised when the loop is invoked but the feature flag is off."""


def run_dialectical_loop(
    signal: DecaySignal,
    *,
    policy: QuarantinePolicy | None = None,
    code_unit_class: str = "default",
    enable_repair_proposal: bool = False,
    enable_crux_probe: bool = False,
    crux_question: str | None = None,
    prior_receipt_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    require_enabled: bool = True,
) -> DialecticalEvent:
    """Run one DIC-23 orchestration pass and return a :class:`DialecticalEvent`.

    Parameters
    ----------
    signal:
        The :class:`~aragora.epistemic.decay_monitor.DecaySignal` to act on.
    policy:
        Explicit :class:`~aragora.epistemic.quarantine_policy.QuarantinePolicy`.
        When ``None``, resolves from
        :data:`~aragora.epistemic.quarantine_policy.DEFAULT_POLICIES` using
        ``code_unit_class``.
    code_unit_class:
        Policy class key used when ``policy`` is ``None``.
    enable_repair_proposal:
        When ``True`` *and* the quarantine decision is
        ``"repair_required"``, calls
        :func:`~aragora.epistemic.repair.propose_repair` to produce a
        ``report_only`` :class:`~aragora.epistemic.repair.RepairSpec`.
        Defaults to ``False`` — pure report-only trace with no spec.
    enable_crux_probe:
        When ``True`` *and* ``crux_question`` is non-empty *and*
        ``ARAGORA_CRUXSET_EMISSION_ENABLED`` is set, synthesises a crux
        analysis from the decay signal and calls
        :func:`aragora.reasoning.cruxset_emission.maybe_emit_cruxset`.
        A successful probe sets ``crux_probe_skipped=False`` on the
        returned event and populates ``metadata["crux_probe"]`` with a
        lightweight CruxSet summary.  Any failure is swallowed — the
        probe must not cause loop failures.  Defaults to ``False``.
    crux_question:
        Human-readable context question passed to the crux emitter.
        Only used when ``enable_crux_probe=True``.
    prior_receipt_ids:
        Receipt IDs to attach to the event's ancestry chain.
    metadata:
        Arbitrary pass-through payload stored in the event.
    require_enabled:
        When ``True`` (default), raises :class:`DialecticalRuntimeError`
        if ``ARAGORA_DIALECTICAL_RUNTIME_ENABLED`` is not set.  Pass
        ``False`` in unit tests to build events without touching the
        environment.

    Returns
    -------
    DialecticalEvent
        Immutable trace record.  Never mutates claim manifests, never
        creates issues, never routes to the live queue.
    """
    if require_enabled and not dialectical_runtime_enabled():
        raise DialecticalRuntimeError(
            "DIC-23 dialectical runtime is disabled; "
            "set ARAGORA_DIALECTICAL_RUNTIME_ENABLED=1 at the process boundary"
        )

    resolved_policy = policy or DEFAULT_POLICIES.get(code_unit_class, DEFAULT_POLICIES["default"])
    quarantine = apply_quarantine_policy(signal, resolved_policy)

    repair_spec: RepairSpec | None = None
    if enable_repair_proposal and quarantine.policy_action == "repair_required":
        repair_spec = propose_repair(signal)

    merged_metadata: dict[str, Any] = dict(metadata or {})
    crux_probe_skipped = True

    if enable_crux_probe and crux_question and crux_question.strip():
        try:
            probe_result = _attempt_crux_probe(signal, crux_question.strip())
        except Exception as exc:  # noqa: BLE001
            logger.debug("DIC-23 crux probe (outer guard) suppressed: %s", exc)
            probe_result = None
        if probe_result is not None:
            crux_probe_skipped = False
            merged_metadata["crux_probe"] = probe_result

    ts = _utc_now_iso()
    event_id = _event_id(signal.code_unit_id, signal.recommended_action, ts)

    return DialecticalEvent(
        event_id=event_id,
        code_unit_id=signal.code_unit_id,
        integrity_score=signal.integrity_score,
        recommended_action=signal.recommended_action,
        quarantine_action=quarantine.policy_action,
        crux_probe_skipped=crux_probe_skipped,
        repair_spec=repair_spec,
        prior_receipt_ids=tuple(prior_receipt_ids or []),
        created_at=ts,
        metadata=merged_metadata,
    )


__all__ = [
    "DialecticalEvent",
    "DialecticalRuntimeError",
    "dialectical_runtime_enabled",
    "run_dialectical_loop",
]
