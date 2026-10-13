"""Bounded repair-spec producer for decayed proof-carrying code units (DIC-22 / #6033).

Turns a :class:`~aragora.epistemic.decay_monitor.DecaySignal` into a
:class:`RepairSpec` — a bounded, auditable repair candidate that can be
reviewed by an operator, submitted as a PR, or run in shadow mode.

Invariants (never relaxed):
- ``repair_kind`` defaults to ``"report_only"``.
- ``"live_swap"`` is permanently blocked — raises ``ValueError`` unconditionally.
- Non-``"report_only"`` kinds require ``ARAGORA_REPAIR_PIPELINE_ENABLED``.
- Every non-``"report_only"`` spec carries a 64-char SHA-256 provenance hash.
- No queue mutation, no live dispatch routing, no issue creation.

``repair.py`` produces the *spec*; downstream code (Arena debate, verifier
calls, PR creation) is deferred to consumers of :class:`RepairSpec`.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from aragora.epistemic.decay_monitor import DecaySignal

UTC = timezone.utc

RepairKind = Literal["report_only", "shadow_candidate", "pr_candidate"]

_BLOCKED_KINDS: frozenset[str] = frozenset({"live_swap"})
_ALLOWED_KINDS: frozenset[str] = frozenset({"report_only", "shadow_candidate", "pr_candidate"})


def repair_pipeline_enabled() -> bool:
    """Return True when non-report-only repairs are permitted for this process."""
    raw = str(os.environ.get("ARAGORA_REPAIR_PIPELINE_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def enable_repair_pipeline() -> None:
    """Enable non-report-only repair specs for the current process (tests/demo)."""
    os.environ["ARAGORA_REPAIR_PIPELINE_ENABLED"] = "1"


@dataclass(frozen=True)
class RepairSpec:
    """Bounded repair candidate produced from a DecaySignal.

    ``repair_kind`` is ``"report_only"`` by default.  ``"shadow_candidate"``
    runs the replacement in parallel without routing; ``"pr_candidate"`` emits a
    draft PR for human review.  ``"live_swap"`` is permanently blocked.

    Non-``"report_only"`` specs carry a 64-char SHA-256 ``provenance_hash``
    over their canonical content; report-only specs have an empty hash.
    """

    spec_id: str
    code_unit_id: str
    decay_signal: DecaySignal
    repair_kind: RepairKind
    linked_claims: list[str]
    linked_crux_ids: list[str]
    validation_commands: list[str]
    receipt_context: dict[str, Any]
    proposed_patch: str
    created_at: str
    provenance_hash: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decay_signal"] = self.decay_signal.to_dict()
        return d


def propose_repair(
    decay_signal: DecaySignal,
    *,
    repair_kind: RepairKind = "report_only",
    linked_claims: list[str] | None = None,
    linked_crux_ids: list[str] | None = None,
    validation_commands: list[str] | None = None,
    receipt_context: dict[str, Any] | None = None,
    proposed_patch: str = "",
) -> RepairSpec:
    """Build a :class:`RepairSpec` from a :class:`DecaySignal`.

    ``linked_claims`` and ``linked_crux_ids`` default to claim/crux IDs
    extracted from ``decay_signal.reasons`` when not provided.
    """
    if repair_kind in _BLOCKED_KINDS:
        raise ValueError(
            f"repair_kind {repair_kind!r} is permanently blocked; "
            "live hot-swap may not be produced by propose_repair"
        )
    if repair_kind not in _ALLOWED_KINDS:
        raise ValueError(
            f"repair_kind {repair_kind!r} is not a known kind; "
            f"expected one of {sorted(_ALLOWED_KINDS)}"
        )
    if repair_kind != "report_only" and not repair_pipeline_enabled():
        raise ValueError(
            f"repair_kind {repair_kind!r} requires ARAGORA_REPAIR_PIPELINE_ENABLED=1; "
            "set the flag or use repair_kind='report_only'"
        )

    claims: list[str] = list(linked_claims or [])
    if not claims:
        claims = [r.claim_id for r in decay_signal.reasons if r.claim_id]

    crux_ids: list[str] = list(linked_crux_ids or [])
    if not crux_ids:
        crux_ids = [r.crux_id for r in decay_signal.reasons if r.crux_id]

    commands = list(validation_commands or [])
    context: dict[str, Any] = dict(receipt_context or {"code_unit_id": decay_signal.code_unit_id})
    created_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

    id_material = {
        "code_unit_id": decay_signal.code_unit_id,
        "integrity_score": decay_signal.integrity_score,
        "repair_kind": repair_kind,
        "created_at": created_at,
    }
    digest = hashlib.sha256(json.dumps(id_material, sort_keys=True).encode()).hexdigest()[:16]
    spec_id = f"repair-{digest}"

    provenance_hash = ""
    if repair_kind != "report_only":
        hash_material = {
            "spec_id": spec_id,
            "code_unit_id": decay_signal.code_unit_id,
            "repair_kind": repair_kind,
            "linked_claims": sorted(claims),
            "linked_crux_ids": sorted(crux_ids),
            "created_at": created_at,
        }
        provenance_hash = hashlib.sha256(
            json.dumps(hash_material, sort_keys=True).encode()
        ).hexdigest()

    return RepairSpec(
        spec_id=spec_id,
        code_unit_id=decay_signal.code_unit_id,
        decay_signal=decay_signal,
        repair_kind=repair_kind,
        linked_claims=claims,
        linked_crux_ids=crux_ids,
        validation_commands=commands,
        receipt_context=context,
        proposed_patch=proposed_patch,
        created_at=created_at,
        provenance_hash=provenance_hash,
    )


__all__ = [
    "RepairKind",
    "RepairSpec",
    "enable_repair_pipeline",
    "propose_repair",
    "repair_pipeline_enabled",
]
