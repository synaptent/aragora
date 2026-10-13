"""DIC-20 → DIC-21 pipeline helper (epistemic decision pipeline).

Chains :func:`~aragora.epistemic.decay_monitor.evaluate_unit` (DIC-20) with
:func:`~aragora.epistemic.quarantine_policy.apply_quarantine_policy` (DIC-21)
in a single call, returning both the :class:`DecaySignal` and the
:class:`QuarantineDecision` together.

This module adds no new logic; it is a convenience composition so callers
don't have to import two modules and repeat the chaining boilerplate. Each
constituent function may still be called independently.

Flag gate
---------
``ARAGORA_EPISTEMIC_PIPELINE_ENABLED`` (default ``off``).
:class:`EpistemicPipelineResult` construction is always importable, but
:func:`evaluate_and_quarantine` raises :class:`RuntimeError` when the flag
is not set so callers know the pipeline is not yet operational.

Live queue effect
-----------------
None — read-only, no state mutation, no issue creation.

Advances
--------
Issues #6031 (DIC-20) and #6032 (DIC-21).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .claim_verifier import ClaimResult
    from .decay_monitor import DecaySignal
    from .proof_unit import ProofCarryingCodeUnit
    from .quarantine_policy import QuarantineDecision, QuarantinePolicy

_FLAG = "ARAGORA_EPISTEMIC_PIPELINE_ENABLED"


def epistemic_pipeline_enabled() -> bool:
    """Return True when :func:`evaluate_and_quarantine` may be called.

    Reads ``ARAGORA_EPISTEMIC_PIPELINE_ENABLED`` from the environment.
    Default is ``False``; :class:`EpistemicPipelineResult` construction
    is always safe regardless of this flag.
    """
    return os.environ.get(_FLAG, "").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EpistemicPipelineResult:
    """Combined output of the DIC-20 → DIC-21 chain.

    Both fields are set; neither is optional.  Callers should inspect
    ``quarantine_decision.policy_action`` to decide whether to surface
    the result to operators.
    """

    decay_signal: "DecaySignal"
    quarantine_decision: "QuarantineDecision"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of both stages."""
        return {
            "decay_signal": self.decay_signal.to_dict(),
            "quarantine_decision": self.quarantine_decision.to_dict(),
        }


def evaluate_and_quarantine(
    unit: "ProofCarryingCodeUnit",
    *,
    claim_results: "dict[str, ClaimResult] | None" = None,
    unresolved_crux_ids: "frozenset[str] | None" = None,
    code_unit_class: str = "default",
    policy: "QuarantinePolicy | None" = None,
) -> EpistemicPipelineResult:
    """Chain DIC-20 decay evaluation with DIC-21 quarantine policy in one call.

    Parameters
    ----------
    unit:
        The :class:`~aragora.epistemic.proof_unit.ProofCarryingCodeUnit` to
        evaluate.  Should already have passed ``unit.validate()``.
    claim_results:
        Optional mapping of claim ID → :class:`~aragora.epistemic.claim_verifier.ClaimResult`.
        Passed through to :func:`~aragora.epistemic.decay_monitor.evaluate_unit`.
    unresolved_crux_ids:
        Optional set of crux IDs whose resolution is still outstanding.
        Passed through to :func:`~aragora.epistemic.decay_monitor.evaluate_unit`.
    code_unit_class:
        Selects the :class:`~aragora.epistemic.quarantine_policy.QuarantinePolicy`
        from ``DEFAULT_POLICIES``.  Ignored when *policy* is provided explicitly.
        Defaults to ``"default"``.
    policy:
        Override policy; when provided, *code_unit_class* is ignored.
        Passed through to
        :func:`~aragora.epistemic.quarantine_policy.apply_quarantine_policy`.

    Returns
    -------
    EpistemicPipelineResult
        Contains both the :class:`~aragora.epistemic.decay_monitor.DecaySignal`
        and the :class:`~aragora.epistemic.quarantine_policy.QuarantineDecision`.

    Raises
    ------
    RuntimeError
        When ``ARAGORA_EPISTEMIC_PIPELINE_ENABLED`` is not set.
    """
    if not epistemic_pipeline_enabled():
        raise RuntimeError(f"{_FLAG} is not set; set it to '1' to enable the epistemic pipeline")

    from .decay_monitor import evaluate_unit
    from .quarantine_policy import apply_quarantine_policy

    signal = evaluate_unit(
        unit,
        claim_results=claim_results,
        unresolved_crux_ids=unresolved_crux_ids,
    )
    decision = apply_quarantine_policy(
        signal,
        policy=policy,
        code_unit_class=code_unit_class,
    )
    return EpistemicPipelineResult(decay_signal=signal, quarantine_decision=decision)


__all__ = [
    "EpistemicPipelineResult",
    "epistemic_pipeline_enabled",
    "evaluate_and_quarantine",
]
