"""Pure normalization and hashing helpers for decision receipts.

These functions define the canonical receipt payload: how legacy flags and
confidences decode, how execution linkage is normalized, which fields the
``artifact_hash`` binds, and how schema versions are chosen. Producers and
verifiers share them, so they depend on the standard library only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime
from typing import Any

__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION_CRUXES",
    "RECEIPT_SCHEMA_VERSION_EVIDENCE",
    "canonicalize_execution_outcome_linkage",
    "compute_decision_payload_hash",
    "compute_receipt_artifact_hash",
    "crux_cards_from_metadata",
    "normalize_evidence_references",
    "receipt_schema_version",
]


def _clamp_receipt_confidence(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def _normalize_receipt_boolean(value: Any, *, default: bool = False, strict: bool = False) -> bool:
    """Decode legacy flags; strict consumers reject unknowns instead of defaulting."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False if strict else default
    if isinstance(value, int | float):
        if strict and isinstance(value, float) and not math.isfinite(value):
            raise ValueError("receipt boolean must be finite")
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    if strict:
        raise ValueError("unrecognized receipt boolean")
    return default


def canonicalize_execution_outcome_linkage(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize receipt/result linkage onto one canonical execution payload."""

    canonical = dict(payload)
    receipt_view = canonical.get("receipt")
    if not isinstance(receipt_view, dict):
        receipt_view = {}
    else:
        receipt_view = dict(receipt_view)

    receipt_id = str(canonical.get("receipt_id") or receipt_view.get("id") or "").strip()
    debate_id = str(
        canonical.get("debate_id") or canonical.get("gauntlet_id") or receipt_id
    ).strip()
    gauntlet_id = str(canonical.get("gauntlet_id") or debate_id or receipt_id).strip()
    artifact_hash = str(
        canonical.get("artifact_hash")
        or canonical.get("checksum")
        or receipt_view.get("artifact_hash")
        or ""
    ).strip()

    consensus = canonical.get("consensus_reached")
    if consensus is None and isinstance(canonical.get("consensus_proof"), dict):
        consensus = canonical["consensus_proof"].get("reached")
    if consensus is None:
        consensus = receipt_view.get("consensus_reached")
    consensus_reached = _normalize_receipt_boolean(consensus)

    default_confidence = receipt_view.get("confidence", 0.0)
    if isinstance(canonical.get("consensus_proof"), dict):
        default_confidence = canonical["consensus_proof"].get("confidence", default_confidence)
    confidence = _clamp_receipt_confidence(
        canonical.get("confidence"),
        default=_clamp_receipt_confidence(default_confidence),
    )

    if receipt_id:
        canonical["receipt_id"] = receipt_id
        receipt_view["id"] = receipt_id
    if debate_id:
        canonical["debate_id"] = debate_id
    if gauntlet_id:
        canonical["gauntlet_id"] = gauntlet_id
    if artifact_hash:
        canonical["artifact_hash"] = artifact_hash
        canonical["checksum"] = artifact_hash
        receipt_view["artifact_hash"] = artifact_hash

    canonical["confidence"] = confidence
    canonical["consensus_reached"] = consensus_reached
    if "consensus" in canonical or isinstance(canonical.get("consensus_proof"), dict):
        canonical["consensus"] = consensus_reached

    receipt_view["confidence"] = confidence
    receipt_view["consensus_reached"] = consensus_reached
    participants = canonical.get("agents")
    if isinstance(participants, list) and "participants" not in receipt_view:
        receipt_view["participants"] = list(participants)
    canonical["receipt"] = receipt_view

    consensus_proof = canonical.get("consensus_proof")
    if isinstance(consensus_proof, dict):
        normalized_consensus = dict(consensus_proof)
        normalized_consensus["reached"] = consensus_reached
        normalized_consensus["confidence"] = confidence
        canonical["consensus_proof"] = normalized_consensus

    return canonical


# Receipt schema version changelog:
#   1.0 — original receipt schema
#   1.1 — current baseline (agent responses, provenance enrichment)
#   1.2 — carries a ``cruxes`` block (crux cards, #8227). Cruxes are bound
#         into ``artifact_hash`` together with ``schema_version`` itself, so
#         a 1.2→1.1 downgrade breaks verification instead of silently
#         defeating the version signal.
#   1.3 — carries evidence-linked planning decisions. The artifact hash binds
#         sorted evidence references, the decision-payload hash, and the schema
#         version; the decision-payload hash separately binds normalized goals.
#
# Hash-binding rule: ``cruxes`` is bound whenever present, and
# ``served_models`` whenever present AND non-empty (same presence gate, same
# reason: a receipt written before the field carries neither key and keeps its
# stored hash byte-for-byte). ``schema_version`` is bound ONLY when it is
# exactly 1.2 (version-gated, not presence-gated). Crux binding shipped on
# main (#9414) BEFORE the 1.2 stamp existed, so already-persisted audit
# receipts carry cruxes with schema_version 1.1 and a hash computed WITHOUT
# schema_version — those must keep verifying. Receipts stamped 1.2 bind
# schema_version, so a downgrade to 1.1 breaks verification. Pre-crux
# receipts (no cruxes) keep the original recipe untouched.
RECEIPT_SCHEMA_VERSION = "1.1"
RECEIPT_SCHEMA_VERSION_CRUXES = "1.2"
RECEIPT_SCHEMA_VERSION_EVIDENCE = "1.3"


def _canonical_decision_value(value: Any) -> Any:
    """Convert decision material to deterministic JSON primitives."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if isinstance(value, dict):
        return {
            str(key): _canonical_decision_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_decision_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonical_decision_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def normalize_evidence_references(references: Any) -> list[dict[str, Any]]:
    """Normalize and sort portable evidence references for hashing/export."""
    normalized: list[dict[str, Any]] = []
    for reference in references or []:
        value = _canonical_decision_value(reference)
        if isinstance(value, dict):
            normalized.append(value)
    return sorted(
        normalized,
        key=lambda item: (
            str(item.get("evidence_id", "")),
            str(item.get("path", "")),
            json.dumps(item, sort_keys=True, default=str),
        ),
    )


def compute_decision_payload_hash(
    decision_payload: Any,
    evidence_references: Any = None,
) -> str:
    """Hash normalized selected goals together with their sorted evidence links."""
    content = json.dumps(
        {
            "decision_payload": _canonical_decision_value(decision_payload or {}),
            "evidence_references": normalize_evidence_references(evidence_references),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode()).hexdigest()


def compute_receipt_artifact_hash(data: Any) -> str:
    """Canonical ``artifact_hash`` recipe for a receipt-shaped mapping.

    Single source of truth for the integrity hash: ``DecisionReceipt.
    _calculate_hash`` and the standalone ``aragora verify`` command both
    delegate here, so the hashed field set cannot drift between producer and
    verifier. Covers the decision-integrity fields (receipt_id, gauntlet_id,
    input_hash, risk_summary, verdict, confidence); binds ``cruxes`` whenever
    present and ``served_models`` whenever non-empty; and binds
    ``schema_version`` only for receipts stamped 1.2 (downgrade-tamper
    protection). The version binding is gated on the 1.2 stamp — NOT on crux
    presence — because #9414 shipped crux binding before the stamp existed:
    receipts with cruxes + schema_version 1.1 hashed without schema_version
    and must keep verifying (see changelog above).

    ``served_models`` is the field that states WHICH MODEL made the decision
    when a server-side fallback answered for the one the debate pinned; left
    unbound, that statement could be edited without failing
    ``verify_integrity`` (finding C-P3 on #9989). It is bound on the same
    conditional-presence terms as ``cruxes`` — and additionally skipped when
    empty, since the runner only ever attaches a non-empty map — so every
    receipt written before the field keeps its stored hash unchanged.
    """
    if not isinstance(data, dict):
        data = {}
    payload: dict[str, Any] = {
        "receipt_id": data.get("receipt_id", ""),
        "gauntlet_id": data.get("gauntlet_id", ""),
        "input_hash": data.get("input_hash", ""),
        "risk_summary": data.get("risk_summary", {}),
        "verdict": data.get("verdict", ""),
        "confidence": data.get("confidence", 0.0),
    }
    if data.get("served_models"):
        payload["served_models"] = data.get("served_models")
    if data.get("cruxes") is not None:
        payload["cruxes"] = data.get("cruxes")
        # Missing schema_version defaults to "1.0" (the from_dict convention)
        # so the same JSON cannot hash two ways.
        schema_version = data.get("schema_version", "1.0")
        if schema_version == RECEIPT_SCHEMA_VERSION_CRUXES:
            payload["schema_version"] = schema_version
    if data.get("schema_version") == RECEIPT_SCHEMA_VERSION_EVIDENCE:
        payload["schema_version"] = RECEIPT_SCHEMA_VERSION_EVIDENCE
        payload["decision_payload_hash"] = data.get("decision_payload_hash", "")
        payload["evidence_references"] = normalize_evidence_references(
            data.get("evidence_references")
        )
    content = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def receipt_schema_version(
    cruxes: dict[str, Any] | None,
    evidence_references: Any = None,
    decision_payload_hash: str | None = None,
) -> str:
    """Schema version for a receipt given its cruxes block.

    Bumps to 1.2 exactly when a cruxes block is carried, giving older
    verifiers a version signal instead of a spurious tampering report.
    Shared by ``DecisionReceipt.from_debate_result`` and the CLI receipt
    persistence so version and content cannot drift apart.
    """
    if evidence_references or decision_payload_hash:
        return RECEIPT_SCHEMA_VERSION_EVIDENCE
    return RECEIPT_SCHEMA_VERSION_CRUXES if cruxes is not None else RECEIPT_SCHEMA_VERSION


def crux_cards_from_metadata(metadata: Any) -> dict[str, Any] | None:
    """Return the crux-cards block from debate-result metadata, or None.

    Crux cards (#8227) are attached by the consensus phase when the debate ran
    with ``enable_crux_cards``. The block is only carried into receipts when it
    has items — a missing or empty block keeps flag-off receipts byte-identical
    to pre-crux output. Returns a deep copy so receipts never alias the live
    result metadata at any nesting depth (cruxes bind into ``artifact_hash``,
    so a later nested mutation must not flip ``verify_integrity``). Shared by
    ``DecisionReceipt.from_debate_result`` and the CLI receipt persistence so
    this invariant cannot drift.
    """
    if not isinstance(metadata, dict):
        return None
    crux_cards = metadata.get("crux_cards")
    if isinstance(crux_cards, dict) and crux_cards.get("items"):
        return copy.deepcopy(crux_cards)
    return None
