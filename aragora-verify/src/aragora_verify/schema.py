"""Structural conformance checks for the ODR v0.1 content profile.

The profile is a *fixed* shape (spec §2-§4), so this module validates it
directly with the standard library — no JSON Schema engine required, honoring
the "stdlib + one crypto dep" constraint of issue #8226. When the optional
``jsonschema`` package happens to be importable, :func:`validate_structure`
*additionally* runs the bundled draft-2020-12 schema for belt-and-suspenders
rigor; its findings are merged with the structural ones.

Every check returns human-readable error strings (empty list == conformant)
rather than raising, so the CLI can print all problems at once.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

__all__ = ["load_bundled_schema", "validate_structure", "ODR_PROFILE_URI", "ODR_VERSION"]

ODR_VERSION = "0.1"
ODR_PROFILE_URI = "https://aragora.ai/specs/open-decision-receipt/v0.1"

_REQUIRED_MEMBERS = (
    "odr_version",
    "profile",
    "receipt_id",
    "issued_at",
    "subject",
    "claim",
    "reasoning",
    "quorum",
    "confidence",
    "cruxes",
    "attestation",
    "routing",
    "signatures",
)
_ALLOWED_TOP_LEVEL = frozenset(_REQUIRED_MEMBERS) | {"source", "adjudication"}


def load_bundled_schema() -> dict[str, Any]:
    """Return the bundled ODR v0.1 JSON Schema (draft 2020-12)."""
    text = resources.files("aragora_verify").joinpath("odr_schema.json").read_text("utf-8")
    return json.loads(text)


def _is_absent_marker(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") == "absent"
        and isinstance(value.get("reason"), str)
        and bool(value.get("reason"))
    )


def _check_block(errors: list[str], doc: dict[str, Any], name: str) -> None:
    value = doc.get(name)
    if not isinstance(value, dict):
        errors.append(f"{name}: must be an object")


def _check_reasoning(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("reasoning: must be a present block or an absent marker")
        return
    if not isinstance(value.get("summary"), str) or not value.get("summary"):
        errors.append("reasoning.summary: required non-empty string when present")


def _check_quorum(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("quorum: must be a present block or an absent marker")
        return
    for field in (
        "method",
        "reached",
        "supporting_agents",
        "participants",
        "independence",
        "dissent",
    ):
        if field not in value:
            errors.append(f"quorum.{field}: required when present")
    participants = value.get("participants")
    if isinstance(participants, list):
        for i, p in enumerate(participants):
            if not isinstance(p, dict) or "agent" not in p or "model_family" not in p:
                errors.append(f"quorum.participants[{i}]: requires agent and model_family")


def _check_confidence(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("confidence: must be a present block or an absent marker")
        return
    val = value.get("value")
    if not isinstance(val, (int, float)) or isinstance(val, bool) or not (0 <= val <= 1):
        errors.append("confidence.value: required number in [0, 1] when present")
    if value.get("scale") != "unit_interval":
        errors.append("confidence.scale: must be 'unit_interval' when present")


def _check_attestation(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("attestation: must be an object")
        return
    disposition = value.get("disposition")
    if disposition not in ("human_attested", "autonomous"):
        errors.append("attestation.disposition: must be 'human_attested' or 'autonomous'")
    if disposition == "human_attested" and not isinstance(value.get("attestor"), dict):
        errors.append("attestation.attestor: required object when disposition is human_attested")
    attestor = value.get("attestor")
    if "attestor" in value and not isinstance(attestor, dict):
        errors.append("attestation.attestor: must be an object")
    elif isinstance(attestor, dict):
        for key in ("id", "name", "role"):
            if key in attestor and not isinstance(attestor.get(key), str):
                errors.append(f"attestation.attestor.{key}: must be a string")
    # Oversight extension members (ODR-6 / #8230): validate shapes when
    # present, mirroring the bundled JSON schema so installs without the
    # optional jsonschema extra reject the same malformed blocks.
    execution_identity = value.get("execution_identity")
    if "execution_identity" in value and not isinstance(execution_identity, dict):
        errors.append("attestation.execution_identity: must be an object")
    elif isinstance(execution_identity, dict):
        for key in ("id", "name", "role"):
            if key in execution_identity and not isinstance(execution_identity.get(key), str):
                errors.append(f"attestation.execution_identity.{key}: must be a string")
        attestor_obj = value.get("attestor")
        attestor_id = attestor_obj.get("id") if isinstance(attestor_obj, dict) else None
        execution_id = execution_identity.get("id")
        if (
            disposition == "human_attested"
            and isinstance(attestor_id, str)
            and isinstance(execution_id, str)
            and attestor_id.strip()
            and attestor_id.strip().lower() == execution_id.strip().lower()
        ):
            errors.append(
                "attestation: attestor.id must differ from execution_identity.id "
                "(self-attestation is not oversight)"
            )
    observed = value.get("observed")
    if "observed" in value and not isinstance(observed, dict):
        errors.append("attestation.observed: must be an object")
    elif isinstance(observed, dict):
        for key in ("head_sha", "evidence_digest"):
            if key in observed and not isinstance(observed.get(key), str):
                errors.append(f"attestation.observed.{key}: must be a string")
    mechanism = value.get("mechanism")
    if "mechanism" in value and not isinstance(mechanism, dict):
        errors.append("attestation.mechanism: must be an object")
    elif isinstance(mechanism, dict):
        mech_type = mechanism.get("type")
        if not isinstance(mech_type, str) or not mech_type:
            errors.append("attestation.mechanism.type: required non-empty string")
        for key in ("context", "ref"):
            if key in mechanism and not isinstance(mechanism.get(key), str):
                errors.append(f"attestation.mechanism.{key}: must be a string")


def _check_signatures(errors: list[str], value: Any) -> None:
    if not isinstance(value, list):
        errors.append("signatures: must be an array")
        return
    for i, sig in enumerate(value):
        if not isinstance(sig, dict):
            errors.append(f"signatures[{i}]: must be an object")
            continue
        for field in ("alg", "key_id", "signature"):
            if not isinstance(sig.get(field), str) or not sig.get(field):
                errors.append(f"signatures[{i}].{field}: required non-empty string")
        if sig.get("alg") not in (None, "Ed25519") and isinstance(sig.get("alg"), str):
            errors.append(f"signatures[{i}].alg: only 'Ed25519' is defined in v0.1")


def validate_structure(doc: Any) -> list[str]:
    """Return a list of conformance errors; empty means the receipt is well-formed."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["receipt: top-level value must be a JSON object"]

    for member in _REQUIRED_MEMBERS:
        if member not in doc:
            errors.append(f"missing required member: {member}")
    for member in sorted(doc.keys() - _ALLOWED_TOP_LEVEL):
        errors.append(f"unknown top-level member: {member}")

    version = doc.get("odr_version")
    if version not in ("0.1", "0.2"):
        errors.append("odr_version: must be '0.1' or '0.2'")
    if doc.get("profile") != f"https://aragora.ai/specs/open-decision-receipt/v{version}":
        errors.append("profile: must match odr_version")
    if not isinstance(doc.get("receipt_id"), str) or not doc.get("receipt_id"):
        errors.append("receipt_id: required non-empty string")
    issued_at = doc.get("issued_at", "__missing__")
    if issued_at != "__missing__" and issued_at is not None and not isinstance(issued_at, str):
        errors.append("issued_at: must be a string or null")

    _check_block(errors, doc, "subject")
    _check_block(errors, doc, "claim")
    if isinstance(doc.get("subject"), dict):
        if not isinstance(doc["subject"].get("identifier"), str):
            errors.append("subject.identifier: required string")
        if "digest" not in doc["subject"]:
            errors.append("subject.digest: required (present block or absent marker)")
        else:
            digest = doc["subject"]["digest"]
            present_ok = (
                isinstance(digest, dict)
                and digest.get("status") == "present"
                and isinstance(digest.get("value"), str)
            )
            if not _is_absent_marker(digest) and not present_ok:
                # Reproducible without the optional jsonschema extra: a plain
                # string / malformed digest is non-conformant (review [P2]).
                errors.append("subject.digest: must be a present block or an absent marker")
    if isinstance(doc.get("claim"), dict):
        if not isinstance(doc["claim"].get("verdict"), str) or not doc["claim"].get("verdict"):
            errors.append("claim.verdict: required non-empty string")

    _check_reasoning(errors, doc.get("reasoning"))
    _check_quorum(errors, doc.get("quorum"))
    _check_confidence(errors, doc.get("confidence"))
    if "cruxes" in doc and not _is_absent_marker(doc["cruxes"]):
        cruxes = doc["cruxes"]
        if not isinstance(cruxes, dict) or cruxes.get("status") != "present":
            errors.append("cruxes: must be a present block or an absent marker")
    _check_attestation(errors, doc.get("attestation"))
    routing = doc.get("routing")
    if not isinstance(routing, dict) or routing.get("status") != "reserved":
        errors.append("routing.status: must be 'reserved' in v0.1")
    _check_signatures(errors, doc.get("signatures"))

    _validate_extensions(errors, doc, load_bundled_schema())
    errors.extend(_jsonschema_errors(doc))
    return errors


def _validate_extensions(errors: list[str], doc: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate only optional content extensions using their bundled schema definitions."""

    def member(value: Any, spec: dict[str, Any], path: str) -> None:
        if "$ref" in spec:
            spec = schema["$defs"][spec["$ref"].rsplit("/", 1)[1]]
        types: dict[str, type | tuple[type, ...]] = {
            "object": dict,
            "array": list,
            "string": str,
            "boolean": bool,
            "integer": (int, float),
            "number": (int, float),
            "null": type(None),
        }
        expected = spec.get("type", [])
        expected = [expected] if isinstance(expected, str) else expected
        if expected and not any(
            isinstance(value, types[t])
            and not (t in ("integer", "number") and isinstance(value, bool))
            and not (t == "integer" and isinstance(value, float) and not value.is_integer())
            for t in expected
        ):
            errors.append(f"{path}: must have type {expected}")
            return
        if ("enum" in spec and value not in spec["enum"]) or (
            "const" in spec and value != spec["const"]
        ):
            errors.append(f"{path}: invalid value")
        if isinstance(value, list) and "items" in spec:
            for index, item in enumerate(value):
                member(item, spec["items"], f"{path}[{index}]")
        if isinstance(value, dict) and "properties" in spec:
            for key, item in value.items():
                if key in spec["properties"]:
                    member(item, spec["properties"][key], f"{path}.{key}")
                elif spec.get("additionalProperties") is False:
                    errors.append(f"{path}.{key}: unknown member")

    paths = {
        "": ("adjudication",),
        "subject": ("repository", "pr_number", "head_sha", "base_sha"),
        "reasoning": ("observations",),
        "quorum": ("verdicts", "rule"),
        "quorum.dissent": ("findings", "severity_max", "blocking"),
        "attestation.mechanism": (
            "policy_version",
            "tier",
            "tiered_gate",
            "severity_gated",
            "action",
            "action_reason",
            "record_ref",
        ),
    }
    for path, keys in paths.items():
        value, spec = doc, schema
        for part in path.split(".") if path else []:
            value = value.get(part, {}) if isinstance(value, dict) else {}
            spec = spec["properties"][part]
            spec = spec.get("oneOf", [spec])[0]
        if not isinstance(value, dict) or value.get("status") == "absent":
            continue
        if path and spec.get("additionalProperties") is False:
            for key in value.keys() - spec["properties"].keys():
                errors.append(f"{path or 'receipt'}.{key}: unknown member")
        for key in keys:
            if key in value:
                member(value[key], spec["properties"][key], f"{path}.{key}".lstrip("."))


def _jsonschema_errors(doc: Any) -> list[str]:
    """Optional full draft-2020-12 validation when ``jsonschema`` is installed."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    try:
        validator_cls = jsonschema.Draft202012Validator  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - very old jsonschema
        return []
    validator = validator_cls(load_bundled_schema())
    out: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"schema[{location}]: {err.message}")
    return out
