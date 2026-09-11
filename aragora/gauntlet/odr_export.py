"""
Open Decision Receipt (ODR) exporter.

Maps the native :class:`aragora.gauntlet.receipt_models.DecisionReceipt` onto
the vendor-neutral Open Decision Receipt content profile (ODR v0.1) defined in
``docs/specs/OPEN_DECISION_RECEIPT.md`` and machine-validated by
``aragora/gauntlet/odr_schema.json`` (JSON Schema draft 2020-12).

Two guarantees drive every line of this module:

1. **Losslessness where the source has data** — every ODR field is copied or
   derived from an actual ``DecisionReceipt`` field, never synthesized.
2. **Honesty where it does not** — fields the source receipt cannot supply are
   emitted as explicit absent markers (``{"status": "absent", "reason": ...}``)
   rather than fabricated values.

Canonicalization follows RFC 8785 (JSON Canonicalization Scheme, JCS) and is
implemented in the dependency-free leaf :mod:`aragora.gauntlet.odr_jcs`;
:func:`jcs_canonicalize` and :func:`odr_content_digest` are re-exported here
so this module remains the reference emitter surface.

The profile is designed to ride standard envelopes (SCITT / COSE detached
signatures) rather than inventing one: ``signatures[]`` is emitted empty and
reserved for the Ed25519 detached-signature work tracked in issue #8225.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import TYPE_CHECKING, Any, Callable

from aragora.gauntlet.odr_jcs import jcs_canonicalize, odr_content_digest

if TYPE_CHECKING:
    from aragora.gauntlet.receipt_models import DecisionReceipt

ODR_VERSION = "0.1"
ODR_PROFILE_URI = "https://aragora.ai/specs/open-decision-receipt/v0.1"

logger = logging.getLogger(__name__)

__all__ = [
    "ODR_VERSION",
    "ODR_PROFILE_URI",
    "absent",
    "calibration_provenance_for_receipt",
    "decision_receipt_to_odr",
    "jcs_canonicalize",
    "load_odr_schema",
    "odr_content_digest",
    "sign_odr_if_configured",
]


# ---------------------------------------------------------------------------
# Absent markers
# ---------------------------------------------------------------------------


def absent(reason: str) -> dict[str, str]:
    """Build an explicit absent marker.

    ODR never fabricates data: when the source receipt cannot supply a field,
    the field carries ``{"status": "absent", "reason": <why>}`` instead.
    """
    return {"status": "absent", "reason": reason}


def _present(block: dict[str, Any]) -> dict[str, Any]:
    return {"status": "present", **block}


# ---------------------------------------------------------------------------
# DecisionReceipt -> ODR mapping
# ---------------------------------------------------------------------------


def _map_subject(receipt: DecisionReceipt) -> dict[str, Any]:
    digest: dict[str, Any]
    if receipt.input_hash:
        digest = _present({"alg": "sha-256", "value": receipt.input_hash})
    else:
        digest = absent("source receipt has no input_hash")
    subject: dict[str, Any] = {
        "identifier": receipt.gauntlet_id or receipt.receipt_id,
        "digest": digest,
    }
    if receipt.input_summary:
        subject["summary"] = receipt.input_summary
    return subject


def _map_claim(receipt: DecisionReceipt) -> dict[str, Any]:
    claim: dict[str, Any] = {"verdict": receipt.verdict or "UNKNOWN"}
    if receipt.input_summary:
        claim["statement"] = receipt.input_summary
    else:
        claim["statement"] = absent("source receipt has no input_summary")
    return claim


def _map_reasoning(receipt: DecisionReceipt) -> dict[str, Any]:
    if receipt.verdict_reasoning:
        return _present({"summary": receipt.verdict_reasoning})
    return absent("source receipt has no verdict_reasoning")


def _map_participants(receipt: DecisionReceipt) -> list[dict[str, Any]]:
    """Collect participant -> model-family/model-id rows without fabricating.

    Provider/model metadata comes from ``agent_responses`` when the debate
    recorded it; agents with no recorded metadata are listed with explicit
    ``"undisclosed"`` markers rather than guessed families.
    """
    by_agent: dict[str, dict[str, Any]] = {}
    for response in receipt.agent_responses:
        name = (response.agent or "").strip()
        if not name:
            continue
        row = by_agent.setdefault(
            name,
            {"agent": name, "model_family": "undisclosed", "model_id": "undisclosed"},
        )
        if response.provider and row["model_family"] == "undisclosed":
            row["model_family"] = response.provider
        if response.model and row["model_id"] == "undisclosed":
            row["model_id"] = response.model

    proof = receipt.consensus_proof
    if proof is not None:
        for name in list(proof.supporting_agents) + list(proof.dissenting_agents):
            normalized = str(name).strip()
            if normalized and normalized not in by_agent:
                by_agent[normalized] = {
                    "agent": normalized,
                    "model_family": "undisclosed",
                    "model_id": "undisclosed",
                }

    return [by_agent[name] for name in sorted(by_agent)]


def _map_quorum(receipt: DecisionReceipt) -> dict[str, Any]:
    proof = receipt.consensus_proof
    if proof is None:
        return absent("source receipt has no consensus_proof")

    participants = _map_participants(receipt)
    families = sorted(
        {row["model_family"] for row in participants if row["model_family"] != "undisclosed"}
    )
    disclosed = bool(families)
    independence: dict[str, Any] = {
        "disclosed": disclosed,
        "distinct_model_families": len(families),
        "model_families": families,
    }
    if not disclosed:
        independence["note"] = (
            "source receipt recorded no per-agent provider metadata; "
            "model-family independence cannot be asserted"
        )

    dissenting_agents = [str(a) for a in proof.dissenting_agents]
    dissent_views = [str(v) for v in receipt.dissenting_views]
    dissent: dict[str, Any] = {
        "present": bool(dissenting_agents or dissent_views),
        "dissenting_agents": dissenting_agents,
        "views": dissent_views,
    }

    return _present(
        {
            "method": proof.method,
            "reached": bool(proof.reached),
            "supporting_agents": [str(a) for a in proof.supporting_agents],
            "participants": participants,
            "independence": independence,
            "dissent": dissent,
        }
    )


def calibration_provenance_for_receipt(receipt: DecisionReceipt) -> dict[str, Any] | None:
    """Best-effort calibration provenance for the receipt's participants.

    Looks up the participating agents in the existing calibration stores
    (issue #8229) and returns a ``provenance_ref`` block pointing at each
    agent's ``/api/v1/agents/{id}/calibration-report`` endpoint, including
    per-agent sample sizes.

    Returns ``None`` when no participant has recorded calibration data or the
    calibration subsystem is unavailable — the confidence block then carries
    an explicit absent marker instead. Never fabricates provenance.
    """
    agent_names = [row["agent"] for row in _map_participants(receipt)]
    if not agent_names:
        return None
    try:
        from aragora.ranking.calibration_report import build_odr_calibration_provenance

        return build_odr_calibration_provenance(agent_names)
    except Exception:  # noqa: BLE001 - best-effort enrichment must never break export
        return None


def _map_confidence(
    receipt: DecisionReceipt,
    calibration_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calibration: dict[str, Any]
    if calibration_provenance is not None:
        calibration = _present({"provenance_ref": dict(calibration_provenance)})
    elif receipt.settlement_metadata:
        calibration = _present(
            {
                "provenance_ref": {
                    "type": "aragora.settlement_metadata",
                    "receipt_id": receipt.receipt_id,
                }
            }
        )
    else:
        calibration = absent(
            "source receipt records raw consensus confidence with no "
            "calibration provenance (settlement_metadata not populated)"
        )
    return _present(
        {
            "value": float(receipt.confidence),
            "scale": "unit_interval",
            "calibration": calibration,
        }
    )


def _map_cruxes(
    crux_set: list[dict[str, Any]] | None,
    receipt: DecisionReceipt | None = None,
) -> dict[str, Any]:
    if not crux_set and receipt is not None:
        # Crux cards (#8227): receipts from enable_crux_cards debates carry
        # their own cruxes block; an explicit crux_set= still takes precedence.
        receipt_cruxes = getattr(receipt, "cruxes", None)
        if isinstance(receipt_cruxes, dict):
            items = receipt_cruxes.get("items")
            if items:
                crux_set = list(items)
    if crux_set:
        return _present({"items": [dict(item) for item in crux_set]})
    return absent(
        "no crux set recorded for this decision "
        "(DecisionReceipt does not carry one; supply crux_set= from a CruxReceipt)"
    )


def _map_attestation(attestation: dict[str, Any] | None) -> dict[str, Any]:
    if attestation is None:
        return {"disposition": "autonomous"}
    block = dict(attestation)
    block.setdefault("disposition", "human_attested")
    return block


def decision_receipt_to_odr(
    receipt: DecisionReceipt,
    *,
    crux_set: list[dict[str, Any]] | None = None,
    attestation: dict[str, Any] | None = None,
    calibration_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a :class:`DecisionReceipt` onto the ODR v0.1 content profile.

    Args:
        receipt: The source receipt. Fields are copied, never invented.
        crux_set: Optional crux items (e.g. from a ``CruxReceipt``) to include;
            when omitted, the ``cruxes`` block carries an absent marker.
        attestation: Optional human-attestation block. When omitted, the
            decision is honestly recorded with the ``autonomous`` disposition.
        calibration_provenance: Optional calibration ``provenance_ref`` block
            (e.g. from :func:`calibration_provenance_for_receipt`) making the
            confidence figure auditable against the per-agent calibration
            report endpoint (issue #8229). Supply only when calibration data
            actually exists; when omitted the existing settlement-metadata /
            absent logic applies.

    Returns:
        A JSON-serializable dict conforming to ``aragora/gauntlet/odr_schema.json``.
    """
    return {
        "odr_version": ODR_VERSION,
        "profile": ODR_PROFILE_URI,
        "receipt_id": receipt.receipt_id,
        "issued_at": receipt.timestamp or None,
        "subject": _map_subject(receipt),
        "claim": _map_claim(receipt),
        "reasoning": _map_reasoning(receipt),
        "quorum": _map_quorum(receipt),
        "confidence": _map_confidence(receipt, calibration_provenance),
        "cruxes": _map_cruxes(crux_set, receipt),
        "attestation": _map_attestation(attestation),
        "routing": {"status": "reserved"},
        "signatures": [],
        "source": {
            "system": "aragora",
            "schema": "aragora.gauntlet.DecisionReceipt",
            "schema_version": receipt.schema_version,
            "receipt_id": receipt.receipt_id,
            "artifact_hash": receipt.artifact_hash,
        },
    }


def sign_odr_if_configured(
    odr: dict[str, Any],
    *,
    key_loader: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Sign an ODR export when the production key is available.

    A genuinely UNCONFIGURED key (Secrets Manager disabled, or the secret was
    never provisioned) is an expected deployment state, so export stays
    available and explicitly unsigned. A key that is configured but cannot be
    loaded (unreadable secret, bad AWS setup, invalid key material) propagates
    instead — silently publishing an unsigned receipt from a deployment that
    was expected to sign would fail open. Once a key is loaded, signing errors
    always propagate.
    """
    from aragora.gauntlet import odr_signing

    loader = key_loader or odr_signing.load_signing_key_from_secrets
    try:
        private_key = loader()
    except odr_signing.OdrSigningUnconfiguredError as exc:
        logger.warning("ODR signing key not configured; exporting unsigned ODR receipt: %s", exc)
        return odr
    return odr_signing.sign_odr_receipt(odr, private_key)


def load_odr_schema() -> dict[str, Any]:
    """Load the bundled ODR JSON Schema (draft 2020-12)."""
    text = resources.files("aragora.gauntlet").joinpath("odr_schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema
