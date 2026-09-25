"""AGT-06 sidecar signal bridge: DIC-20 EpistemicDecayBatchReport → VIAH counters.

Supplies ``failed_claims_promoted_without_repair`` — the sidecar parameter that
:func:`aragora.evaluation.viah.compute_viah` accepts for the VIAH negative signal.

A code unit is counted when its :class:`~aragora.epistemic.decay_monitor.DecaySignal`
meets both conditions:

1. ``recommended_action`` is ``"fail_closed"`` or ``"repair_required"``
2. At least one reason has ``kind`` of ``"failed_claim"`` or ``"verifier_error"``

Stale-evidence-only and unresolved-crux-only units are excluded: those decay classes
carry their own repair pathways and do not constitute "promoted without repair."

Flag: ``ARAGORA_VIAH_TREND_ENABLED`` (default off, same gate as viah_signals.py).
All computation is side-effect-free; no queue mutation.

Advances issue #6067 (AGT-06) — wires DIC-20 decay output into VIAH negative signal,
closing the loop between epistemic claim decay and the productivity metric.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.epistemic.decay_monitor import EpistemicDecayBatchReport

_VIAH_FLAG = "ARAGORA_VIAH_TREND_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_ACTIONABLE_ACTIONS = frozenset({"fail_closed", "repair_required"})
_CLAIM_FAILURE_KINDS = frozenset({"failed_claim", "verifier_error"})


def _viah_enabled() -> bool:
    return os.environ.get(_VIAH_FLAG, "").strip().lower() in _TRUTHY


def count_failed_claims_from_decay(
    report: "EpistemicDecayBatchReport",
) -> int:
    """Count code units with actionable claim failures from a batch decay report.

    Returns the number of units where the recommended action is ``"fail_closed"``
    or ``"repair_required"`` AND at least one reason is a claim failure
    (``"failed_claim"`` or ``"verifier_error"``).

    Returns 0 when ``ARAGORA_VIAH_TREND_ENABLED`` is not set so the sidecar
    produces no signal until the operator opts in.
    """
    if not _viah_enabled():
        return 0
    count = 0
    for signal in report.signals:
        if signal.recommended_action not in _ACTIONABLE_ACTIONS:
            continue
        if any(r.kind in _CLAIM_FAILURE_KINDS for r in signal.reasons):
            count += 1
    return count
