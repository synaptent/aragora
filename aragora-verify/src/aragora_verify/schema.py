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

import copy
import functools
import json
import re
from importlib import resources
from typing import Any

__all__ = ["load_bundled_schema", "validate_structure", "ODR_PROFILE_URI", "ODR_VERSION"]

#: Informational: the newest profile this verifier speaks. Version acceptance is
#: keyed off the document's own ``odr_version`` literal, so both 0.1 and 0.2
#: documents verify regardless of what these name.
ODR_VERSION = "0.2"
ODR_PROFILE_URI = "https://aragora.ai/specs/open-decision-receipt/v0.2"

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


@functools.lru_cache(maxsize=1)
def _load_bundled_schema_cached() -> dict[str, Any]:
    text = resources.files("aragora_verify").joinpath("odr_schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def load_bundled_schema() -> dict[str, Any]:
    """Return the bundled ODR JSON Schema (draft 2020-12) as a fresh deep copy."""
    return copy.deepcopy(_load_bundled_schema_cached())


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
    for field, expected in (("participants", list), ("dissent", dict)):
        if field in value and not isinstance(value[field], expected):
            errors.append(f"quorum.{field}: must be a {expected.__name__}")
    if "method" in value and not isinstance(value["method"], str):
        errors.append("quorum.method: must be a string")
    if "reached" in value and not isinstance(value["reached"], bool):
        errors.append("quorum.reached: must be a boolean")
    if "independence" in value and not isinstance(value["independence"], dict):
        errors.append("quorum.independence: must be an object")
    if "supporting_agents" in value:
        agents = value["supporting_agents"]
        if not isinstance(agents, list) or not all(isinstance(agent, str) for agent in agents):
            errors.append("quorum.supporting_agents: must be an array of strings")
    participants = value.get("participants")
    if isinstance(participants, list):
        for i, p in enumerate(participants):
            if (
                not isinstance(p, dict)
                or not isinstance(p.get("agent"), str)
                or "model_family" not in p
            ):
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


_SIGNATURE_ROLES = ("emitter", "reviewer", "attestor", "notary")
_SIGNATURE_MEMBERS = frozenset(
    {"alg", "key_id", "signature", "issuer", "role", "signed_at", "expires_at"}
)


def _check_signatures(errors: list[str], value: Any) -> None:
    if not isinstance(value, list):
        errors.append("signatures: must be an array")
        return
    for i, sig in enumerate(value):
        if not isinstance(sig, dict):
            errors.append(f"signatures[{i}]: must be an object")
            continue
        for key in sorted(sig.keys() - _SIGNATURE_MEMBERS):
            errors.append(f"signatures[{i}].{key}: unknown member")
        for field in ("alg", "key_id", "signature"):
            if not isinstance(sig.get(field), str) or not sig.get(field):
                errors.append(f"signatures[{i}].{field}: required non-empty string")
        if sig.get("alg") not in (None, "Ed25519") and isinstance(sig.get("alg"), str):
            errors.append(f"signatures[{i}].alg: only 'Ed25519' is defined")
        # Metadata is optional on both versions (one schema for both) but strictly
        # typed when present; only a v0.2 signature commits it (spec §6).
        if "issuer" in sig and (not isinstance(sig["issuer"], str) or not sig["issuer"]):
            errors.append(f"signatures[{i}].issuer: must be a non-empty string")
        if "role" in sig and sig["role"] not in _SIGNATURE_ROLES:
            errors.append(f"signatures[{i}].role: must be one of {', '.join(_SIGNATURE_ROLES)}")
        for key in ("signed_at", "expires_at"):
            if key in sig and not isinstance(sig[key], str):
                errors.append(f"signatures[{i}].{key}: must be a string")


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
        errors.append("routing.status: must be 'reserved'")
    _check_signatures(errors, doc.get("signatures"))

    _validate_extensions(errors, doc, load_bundled_schema())
    errors.extend(_without_restated(_jsonschema_errors(doc), errors))
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
        if isinstance(value, dict):
            for name in spec.get("required", ()):
                if name not in value:
                    errors.append(f"{path}: missing required member: {name}")
        if isinstance(value, dict) and "properties" in spec:
            for key, item in value.items():
                if key in spec["properties"]:
                    member(item, spec["properties"][key], f"{path}.{key}")
                elif spec.get("additionalProperties") is False:
                    errors.append(f"{path}.{key}: unknown member")

    # Members the v0.1 profile does not define: rejected outright on a "0.1" document.
    version_scoped = {
        "": ("adjudication",),
        "subject": ("repository", "pr_number", "head_sha", "base_sha"),
        "reasoning": ("observations",),
        "quorum": ("verdicts", "rule"),
        "quorum.dissent": ("findings", "severity_max", "blocking"),
    }
    # attestation.mechanism is additionalProperties: true, so its typed extras stay legal
    # on every version and are only shape-checked.
    paths = {
        **version_scoped,
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
    v01 = doc.get("odr_version") == "0.1"
    for path, keys in paths.items():
        value, spec = doc, schema
        for part in path.split(".") if path else []:
            value = value.get(part, {}) if isinstance(value, dict) else {}
            spec = spec["properties"][part]
            # oneOf[0] is the present-block branch; the absent-marker $ref is oneOf[1].
            spec = spec.get("oneOf", [spec])[0]
        if not isinstance(value, dict):
            continue
        # A strict absent marker carries nothing to check; a marker that also carries
        # members is neither branch of its oneOf, so those members are checked as present.
        if value.get("status") == "absent" and value.keys() <= {"status", "reason"}:
            continue
        if path and spec.get("additionalProperties") is False:
            for key in sorted(value.keys() - spec["properties"].keys()):
                errors.append(f"{path}.{key}: unknown member")
        for key in keys:
            if key not in value:
                continue
            member_path = f"{path}.{key}".lstrip(".")
            if v01 and path in version_scoped:
                errors.append(f"{member_path}: not in profile 0.1")
            else:
                member(value[key], spec["properties"][key], member_path)


_UNEXPECTED_MEMBERS = re.compile(
    r"^Additional properties are not allowed \((.*) (?:was|were) unexpected\)$"
)
_VERSION_SCOPED_MEMBER = re.compile(r"^False schema does not allow ")
_REQUIRED_MEMBER = re.compile(r"^'(.*)' is a required property$")


def _slashed(dotted: str) -> str:
    """``quorum.verdicts[0]`` in the jsonschema location form ``quorum/verdicts/0``."""
    return re.sub(r"\[(\d+)\]", r"/\1", dotted).replace(".", "/") or "<root>"


def _without_restated(schema_errors: list[str], errors: list[str]) -> list[str]:
    """Drop the jsonschema lines that restate a finding the hand-written checks already name.

    jsonschema reports an unexpected or missing required member at the object holding it and
    a version-scoped member at its parent object (or, in older releases, at the member
    itself); the checks above name the member, so one line per finding is kept.
    """
    named: set[tuple[str, str, str]] = set()
    for line in errors:
        path, _, message = line.partition(": ")
        if path == "unknown top-level member":
            path, message = message, "unknown member"
        elif path == "missing required member":
            path, message = "", line
        kind, _, name = message.partition(": ")
        if kind == "missing required member":
            named.add((kind, _slashed(path), name))
        elif kind in ("unknown member", "not in profile 0.1"):
            parent, _, name = path.rpartition(".")
            named.add((kind, _slashed(parent), name))
            named.add((kind, _slashed(path), ""))
    kept: list[str] = []
    for line in schema_errors:
        location, _, message = line.removeprefix("schema[").partition("]: ")
        unexpected = _UNEXPECTED_MEMBERS.match(message)
        required = _REQUIRED_MEMBER.match(message)
        names = re.findall(r"'([^']*)'", unexpected.group(1)) if unexpected else []
        if names and all(("unknown member", location, name) in named for name in names):
            continue
        if _VERSION_SCOPED_MEMBER.match(message) and any(
            kind == "not in profile 0.1" and where == location for kind, where, _ in named
        ):
            continue
        if required and ("missing required member", location, required.group(1)) in named:
            continue
        kept.append(line)
    return kept


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
