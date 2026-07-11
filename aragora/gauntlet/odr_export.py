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

Canonicalization follows RFC 8785 (JSON Canonicalization Scheme, JCS):
UTF-8 output, no insignificant whitespace, object members sorted by UTF-16
code units, and numbers serialized using the ECMAScript
``Number::toString`` shortest-round-trip algorithm. No external dependency is
required; :func:`jcs_canonicalize` implements the subset of JCS needed for
I-JSON-safe payloads (which all ODR payloads are) and is covered by
byte-stability tests against the RFC 8785 examples.

The profile is designed to ride standard envelopes (SCITT / COSE detached
signatures) rather than inventing one: ``signatures[]`` is emitted empty and
reserved for the Ed25519 detached-signature work tracked in issue #8225.
"""

from __future__ import annotations

import hashlib
import json
import math
from importlib import resources
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.gauntlet.receipt_models import DecisionReceipt

ODR_VERSION = "0.1"
ODR_PROFILE_URI = "https://aragora.ai/specs/open-decision-receipt/v0.1"

__all__ = [
    "ODR_VERSION",
    "ODR_PROFILE_URI",
    "absent",
    "calibration_provenance_for_receipt",
    "decision_receipt_to_odr",
    "jcs_canonicalize",
    "load_odr_schema",
    "odr_content_digest",
]


# ---------------------------------------------------------------------------
# RFC 8785 (JCS) canonicalization
# ---------------------------------------------------------------------------


def _es_number_to_string(value: float) -> str:
    """Serialize a float per ECMAScript ``Number::toString`` (RFC 8785 3.2.2.3).

    Raises:
        ValueError: for NaN or +/-Infinity, which JCS forbids.
    """
    if math.isnan(value) or math.isinf(value):
        raise ValueError("NaN and Infinity cannot be canonicalized per RFC 8785")
    if value == 0:
        # Covers -0.0 as well: JCS serializes negative zero as "0".
        return "0"

    sign = "-" if value < 0 else ""
    # Python's repr() yields the shortest digit string that round-trips the
    # IEEE-754 double, which is the same digit selection ECMAScript uses.
    # Only the *formatting* rules differ; they are applied below.
    text = repr(abs(value))
    if "e" in text or "E" in text:
        mantissa, _, exp_text = text.lower().partition("e")
        exponent = int(exp_text)
    else:
        mantissa, exponent = text, 0

    if "." in mantissa:
        int_part, frac_part = mantissa.split(".", 1)
    else:
        int_part, frac_part = mantissa, ""

    digits = int_part + frac_part
    # Position of the decimal point measured in digits from the left of
    # ``digits``: value == 0.<digits> * 10**point.
    point = len(int_part) + exponent

    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")

    k = len(digits)
    n = point
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        head = digits[0] + ("." + digits[1:] if k > 1 else "")
        out = f"{head}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + out


_ES_INT_LIMIT = 10**21  # ECMAScript switches to exponent notation at 1e21.


def _jcs_serialize(value: Any, out: list[str]) -> None:
    """Append the JCS serialization of ``value`` to ``out``."""
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        # json.dumps applies exactly the JCS string rules: minimal escaping,
        # two-character escapes for the common controls, lowercase \u00xx for
        # the rest, and raw UTF-8 for everything else (ensure_ascii=False).
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, int):
        if abs(value) < _ES_INT_LIMIT:
            out.append(str(value))
        else:
            out.append(_es_number_to_string(float(value)))
    elif isinstance(value, float):
        out.append(_es_number_to_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _jcs_serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        # RFC 8785 sorts member names by UTF-16 code units; comparing the
        # UTF-16BE encodings byte-wise is equivalent.
        keys = sorted(value.keys(), key=lambda k: str(k).encode("utf-16-be"))
        for i, key in enumerate(keys):
            if i:
                out.append(",")
            if not isinstance(key, str):
                raise TypeError(f"JCS object member names must be strings, got {type(key)!r}")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _jcs_serialize(value[key], out)
        out.append("}")
    else:
        raise TypeError(f"Type {type(value)!r} is not JCS-serializable")


def jcs_canonicalize(value: Any) -> bytes:
    """Canonicalize ``value`` to RFC 8785 (JCS) UTF-8 bytes.

    The output is byte-stable: equal inputs (regardless of dict insertion
    order) always produce identical bytes, which is the hashing basis for the
    ODR profile.
    """
    out: list[str] = []
    _jcs_serialize(value, out)
    return "".join(out).encode("utf-8")


def odr_content_digest(odr: dict[str, Any]) -> str:
    """SHA-256 hex digest over the JCS bytes of the ODR payload.

    The ``signatures`` array is excluded so that attaching detached
    signatures (SCITT/COSE, Ed25519 per #8225) never changes the digest the
    signatures cover.
    """
    payload = {k: v for k, v in odr.items() if k != "signatures"}
    return hashlib.sha256(jcs_canonicalize(payload)).hexdigest()


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


def _map_cruxes(crux_set: list[dict[str, Any]] | None) -> dict[str, Any]:
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


def _map_epistemic(receipt: DecisionReceipt) -> dict[str, Any] | None:
    block: dict[str, Any] = {"status": "present"}
    if receipt.unverified:
        block["unverified"] = list(receipt.unverified)
    if receipt.assumptions:
        block["assumptions"] = list(receipt.assumptions)
    if receipt.falsification:
        block["falsification"] = dict(receipt.falsification)
    return block if len(block) > 1 else None


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
    odr: dict[str, Any] = {
        "odr_version": ODR_VERSION,
        "profile": ODR_PROFILE_URI,
        "receipt_id": receipt.receipt_id,
        "issued_at": receipt.timestamp or None,
        "subject": _map_subject(receipt),
        "claim": _map_claim(receipt),
        "reasoning": _map_reasoning(receipt),
        "quorum": _map_quorum(receipt),
        "confidence": _map_confidence(receipt, calibration_provenance),
        "cruxes": _map_cruxes(crux_set),
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
    epistemic = _map_epistemic(receipt)
    if epistemic is not None:
        odr["epistemic"] = epistemic
    return odr


def load_odr_schema() -> dict[str, Any]:
    """Load the bundled ODR JSON Schema (draft 2020-12)."""
    text = resources.files("aragora.gauntlet").joinpath("odr_schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema
