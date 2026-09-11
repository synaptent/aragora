"""Append-only burn-in records and proof summaries for VibeProxy calls.

The burn-in log is deliberately separate from model-review evidence.  It records
transport outcomes and shadow-review metadata, but every record is explicitly
non-countable and contains no reviewer body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

RECORD_SCHEMA_VERSION = "aragora.vibeproxy-burnin-call.v1"
PROOF_SCHEMA_VERSION = "aragora.vibeproxy-burnin-proof.v1"
DEFAULT_RECORDS_PATH = Path("docs/status/generated/vibeproxy_burnin/calls.jsonl")
DEFAULT_PROOF_PATH = Path("docs/status/generated/vibeproxy_burnin/latest.json")

MINIMUM_SPAN_DAYS = 7
MINIMUM_CLEAN_CALLS = 100
MINIMUM_PROVIDER_FAMILIES = 3
MINIMUM_SHADOW_REVIEWS = 20

_CREDENTIAL_ERROR_CLASSES = frozenset(
    {
        "authentication_error",
        "authorization_error",
        "credential_error",
        "http_401",
        "http_403",
    }
)
_IDENTITY_ERROR_CLASSES = frozenset({"alias_disclosure_error", "family_identity_error"})
_MODEL_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude", ("anthropic/", "claude")),
    ("openai", ("openai/", "gpt-", "chatgpt", "o1", "o3", "o4", "codex")),
    ("gemini", ("google/", "gemini")),
    ("grok", ("x-ai/", "xai/", "grok")),
    ("mistral", ("mistralai/", "mistral", "codestral")),
    ("kimi", ("moonshotai/", "moonshot/", "kimi")),
    ("deepseek", ("deepseek/", "deepseek")),
    ("qwen", ("qwen/", "qwen")),
)


class BurninRecordError(ValueError):
    """Raised when a burn-in record or hash chain is malformed."""


@dataclass(frozen=True)
class CallOutcome:
    """Sanitized result of one VibeProxy inference attempt."""

    family: str
    requested_model: str
    resolved_model: str
    response_model: str | None
    latency_ms: float
    ok: bool
    error_class: str | None = None
    alias_source: str | None = None
    alias_family: str | None = None
    call_kind: str = "inference"
    pr_number: int | None = None
    pr_head_sha: str | None = None
    head_stable: bool | None = None
    review_verdict: str | None = None
    review_digest: str | None = None
    recorded_at: datetime | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise BurninRecordError("recorded_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise BurninRecordError("recorded_at must be an RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BurninRecordError(f"invalid recorded_at: {value}") from exc
    if parsed.tzinfo is None:
        raise BurninRecordError("recorded_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def infer_model_family(model: str) -> str | None:
    """Infer a logical provider family from a disclosed model identifier."""

    normalized = model.strip().lower()
    if not normalized:
        return None
    for family, markers in _MODEL_FAMILY_MARKERS:
        if any(marker in normalized for marker in markers):
            return family
    return None


def verify_family_identity(
    *,
    family: str,
    requested_model: str,
    resolved_model: str,
    response_model: str | None,
    alias_source: str | None,
    ok: bool,
    alias_family: str | None = None,
) -> tuple[bool, bool, tuple[str, ...]]:
    """Verify family identity and explicit alias disclosure for one call."""

    normalized_family = family.strip().lower()
    errors: list[str] = []
    requested_family = infer_model_family(requested_model)
    resolved_family = infer_model_family(resolved_model)
    response_family = infer_model_family(response_model or "")
    disclosed_alias_family = (alias_family or "").strip().lower() or None
    alias_applied = requested_model != resolved_model

    if not normalized_family:
        errors.append("missing_family")
    if requested_family != normalized_family:
        errors.append("requested_model_family_mismatch")
    if resolved_family != normalized_family:
        errors.append("resolved_model_family_mismatch")
    if ok:
        if response_model is None:
            errors.append("missing_response_model")
        elif response_model != resolved_model:
            errors.append("response_model_mismatch")
        if response_family != normalized_family:
            errors.append("response_model_family_mismatch")

    if alias_applied:
        source_present = bool((alias_source or "").strip())
        family_matches = (
            disclosed_alias_family is None or disclosed_alias_family == normalized_family
        )
        alias_disclosure_preserved = source_present and family_matches
        if not source_present:
            errors.append("missing_alias_disclosure")
        if not family_matches:
            errors.append("alias_family_mismatch")
    else:
        alias_disclosure_preserved = disclosed_alias_family is None
        if disclosed_alias_family is not None:
            errors.append("unexpected_alias_family")
    return not errors, alias_disclosure_preserved, tuple(errors)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _record_hash(payload: dict[str, Any]) -> str:
    unhashed = {key: value for key, value in payload.items() if key != "record_hash"}
    return hashlib.sha256(_canonical_json(unhashed)).hexdigest()


def _normalize_error_class(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _validate_loaded_record(record: dict[str, Any], *, line_number: int) -> None:
    """Recompute derived fields so summaries cannot trust forged booleans."""

    prefix = f"invalid record at line {line_number}:"
    family_value = record.get("family")
    requested_value = record.get("requested_model")
    resolved_value = record.get("resolved_model")
    response_model = record.get("response_model")
    alias = record.get("alias_disclosure")
    if not all(
        isinstance(value, str) and value
        for value in (family_value, requested_value, resolved_value)
    ):
        raise BurninRecordError(f"{prefix} missing model identity")
    family = str(family_value)
    requested_model = str(requested_value)
    resolved_model = str(resolved_value)
    if response_model is not None and not isinstance(response_model, str):
        raise BurninRecordError(f"{prefix} response_model must be a string or null")
    if not isinstance(alias, dict):
        raise BurninRecordError(f"{prefix} missing alias disclosure")
    alias_family = alias.get("family")
    if alias_family is not None and not isinstance(alias_family, str):
        raise BurninRecordError(f"{prefix} alias family must be a string or null")
    if record.get("transport") != "vibeproxy-required" or record.get("countable") is not False:
        raise BurninRecordError(f"{prefix} invalid transport/countability boundary")
    if not isinstance(record.get("ok"), bool) or not isinstance(record.get("clean"), bool):
        raise BurninRecordError(f"{prefix} invalid outcome flags")

    error_class = record.get("error_class")
    if error_class is not None and (
        not isinstance(error_class, str) or error_class != _normalize_error_class(error_class)
    ):
        raise BurninRecordError(f"{prefix} invalid error_class")
    identity_ok, alias_ok, identity_errors = verify_family_identity(
        family=family,
        requested_model=requested_model,
        resolved_model=resolved_model,
        response_model=response_model,
        alias_source=alias.get("source") if isinstance(alias.get("source"), str) else None,
        ok=record["ok"],
        alias_family=alias_family,
    )
    expected_alias_applied = requested_model != resolved_model
    if alias.get("applied") is not expected_alias_applied or alias.get("preserved") is not alias_ok:
        raise BurninRecordError(f"{prefix} alias disclosure does not match model route")
    if record.get("family_identity_ok") is not identity_ok:
        raise BurninRecordError(f"{prefix} family identity result is inconsistent")
    if record.get("identity_errors") != list(identity_errors):
        raise BurninRecordError(f"{prefix} identity errors are inconsistent")
    if record.get("credential_error") is not (error_class in _CREDENTIAL_ERROR_CLASSES):
        raise BurninRecordError(f"{prefix} credential classification is inconsistent")
    expected_clean = bool(record["ok"] and error_class is None and identity_ok and alias_ok)
    if record["clean"] is not expected_clean:
        raise BurninRecordError(f"{prefix} clean result is inconsistent")

    call_kind = record.get("call_kind")
    shadow = record.get("shadow_review")
    if call_kind == "inference" and shadow is not None:
        raise BurninRecordError(f"{prefix} inference record contains shadow metadata")
    if call_kind == "shadow_review":
        if not isinstance(shadow, dict):
            raise BurninRecordError(f"{prefix} shadow review metadata is missing")
        if shadow.get("posted") is not False or shadow.get("evidence_composed") is not False:
            raise BurninRecordError(f"{prefix} shadow review crossed the evidence boundary")
        if not isinstance(shadow.get("pr_number"), int) or not isinstance(
            shadow.get("head_sha"), str
        ):
            raise BurninRecordError(f"{prefix} shadow review is not exact-head bound")
    elif call_kind != "inference":
        raise BurninRecordError(f"{prefix} unsupported call_kind")


def _validate_outcome(outcome: CallOutcome) -> None:
    if not outcome.family.strip():
        raise BurninRecordError("family is required")
    if not outcome.requested_model.strip() or not outcome.resolved_model.strip():
        raise BurninRecordError("requested_model and resolved_model are required")
    if not math.isfinite(outcome.latency_ms) or outcome.latency_ms < 0:
        raise BurninRecordError("latency_ms must be finite and non-negative")
    if outcome.call_kind not in {"inference", "shadow_review"}:
        raise BurninRecordError("call_kind must be inference or shadow_review")
    if outcome.call_kind == "shadow_review":
        if not outcome.pr_number or not outcome.pr_head_sha:
            raise BurninRecordError("shadow reviews require pr_number and pr_head_sha")
        if outcome.head_stable is None:
            raise BurninRecordError("shadow reviews require head_stable")


class BurninRecorder:
    """Write and verify a hash-chained append-only VibeProxy burn-in log."""

    def __init__(self, path: Path = DEFAULT_RECORDS_PATH) -> None:
        self.path = Path(path)

    def append(self, outcome: CallOutcome) -> dict[str, Any]:
        _validate_outcome(outcome)
        family = outcome.family.strip().lower()
        error_class = _normalize_error_class(outcome.error_class)
        identity_ok, alias_ok, identity_errors = verify_family_identity(
            family=family,
            requested_model=outcome.requested_model,
            resolved_model=outcome.resolved_model,
            response_model=outcome.response_model,
            alias_source=outcome.alias_source,
            ok=outcome.ok,
            alias_family=outcome.alias_family,
        )
        if not identity_ok and error_class is None:
            error_class = (
                "alias_disclosure_error"
                if identity_errors == ("missing_alias_disclosure",)
                else "family_identity_error"
            )
        if outcome.call_kind == "shadow_review" and outcome.head_stable is False:
            error_class = error_class or "head_drift"

        alias_applied = outcome.requested_model != outcome.resolved_model
        record: dict[str, Any] = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "recorded_at": _timestamp(outcome.recorded_at or utc_now()),
            "call_kind": outcome.call_kind,
            "transport": "vibeproxy-required",
            "countable": False,
            "family": family,
            "requested_model": outcome.requested_model,
            "resolved_model": outcome.resolved_model,
            "response_model": outcome.response_model,
            "alias_disclosure": {
                "applied": alias_applied,
                "source": outcome.alias_source if alias_applied else None,
                "preserved": alias_ok,
            },
            "latency_ms": round(outcome.latency_ms, 3),
            "ok": outcome.ok,
            "clean": bool(outcome.ok and error_class is None and identity_ok and alias_ok),
            "error_class": error_class,
            "credential_error": error_class in _CREDENTIAL_ERROR_CLASSES,
            "family_identity_ok": identity_ok,
            "identity_errors": list(identity_errors),
            "shadow_review": None,
        }
        if outcome.alias_family is not None:
            record["alias_disclosure"]["family"] = outcome.alias_family
        if outcome.call_kind == "shadow_review":
            record["shadow_review"] = {
                "pr_number": outcome.pr_number,
                "head_sha": outcome.pr_head_sha,
                "head_stable": outcome.head_stable,
                "verdict": outcome.review_verdict,
                "response_sha256": outcome.review_digest,
                "posted": False,
                "evidence_composed": False,
            }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            previous_hash: str | None = None
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    previous = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BurninRecordError(
                        f"invalid JSONL at line {line_number}; refusing to append"
                    ) from exc
                if not isinstance(previous, dict) or previous.get("record_hash") != _record_hash(
                    previous
                ):
                    raise BurninRecordError(
                        f"invalid record hash at line {line_number}; refusing to append"
                    )
                if previous.get("previous_record_hash") != previous_hash:
                    raise BurninRecordError(
                        f"broken record chain at line {line_number}; refusing to append"
                    )
                previous_hash = str(previous["record_hash"])

            record["previous_record_hash"] = previous_hash
            record["record_hash"] = _record_hash(record)
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return record


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load a burn-in log and fail closed on schema or hash-chain damage."""

    source = Path(path)
    if not source.exists():
        return []
    records: list[dict[str, Any]] = []
    previous_hash: str | None = None
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BurninRecordError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(record, dict):
                raise BurninRecordError(f"record at line {line_number} is not an object")
            if record.get("schema_version") != RECORD_SCHEMA_VERSION:
                raise BurninRecordError(f"unsupported record schema at line {line_number}")
            if record.get("previous_record_hash") != previous_hash:
                raise BurninRecordError(f"broken record chain at line {line_number}")
            if record.get("record_hash") != _record_hash(record):
                raise BurninRecordError(f"invalid record hash at line {line_number}")
            _parse_timestamp(record.get("recorded_at"))
            _validate_loaded_record(record, line_number=line_number)
            previous_hash = str(record["record_hash"])
            records.append(record)
    return records


def build_proof_artifact(
    records: Iterable[dict[str, Any]],
    *,
    source_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Summarize progress against the bounded rollout gates in issue #9409."""

    rows = list(records)
    clean_rows = [row for row in rows if row.get("clean") is True]
    timestamps = sorted(_parse_timestamp(row.get("recorded_at")) for row in clean_rows)
    span_days = (
        (timestamps[-1] - timestamps[0]).total_seconds() / 86400 if len(timestamps) >= 2 else 0.0
    )
    families = sorted(
        {str(row.get("family")) for row in clean_rows if str(row.get("family") or "")}
    )
    credential_errors = sum(bool(row.get("credential_error")) for row in rows)
    identity_errors = sum(
        row.get("family_identity_ok") is not True
        or row.get("error_class") in _IDENTITY_ERROR_CLASSES
        for row in rows
    )
    shadow_reviews = sum(
        row.get("call_kind") == "shadow_review"
        and row.get("clean") is True
        and isinstance(row.get("shadow_review"), dict)
        and row["shadow_review"].get("head_stable") is True
        for row in rows
    )
    gates: dict[str, dict[str, Any]] = {
        "seven_day_span": {
            "required": MINIMUM_SPAN_DAYS,
            "observed": round(span_days, 6),
            "met": span_days >= MINIMUM_SPAN_DAYS,
        },
        "clean_calls": {
            "required": MINIMUM_CLEAN_CALLS,
            "observed": len(clean_rows),
            "met": len(clean_rows) >= MINIMUM_CLEAN_CALLS,
        },
        "provider_families": {
            "required": MINIMUM_PROVIDER_FAMILIES,
            "observed": len(families),
            "families": families,
            "met": len(families) >= MINIMUM_PROVIDER_FAMILIES,
        },
        "credential_errors": {
            "required_maximum": 0,
            "observed": credential_errors,
            "met": credential_errors == 0,
        },
        "family_identity_errors": {
            "required_maximum": 0,
            "observed": identity_errors,
            "met": identity_errors == 0,
        },
        "shadow_reviews": {
            "required": MINIMUM_SHADOW_REVIEWS,
            "observed": shadow_reviews,
            "met": shadow_reviews >= MINIMUM_SHADOW_REVIEWS,
        },
    }
    return {
        "schema_version": PROOF_SCHEMA_VERSION,
        "generated_at": _timestamp(generated_at or utc_now()),
        "issue": 9409,
        "transport_prerequisite_pr": 9483,
        "source_jsonl": str(source_path),
        "source_last_record_hash": rows[-1]["record_hash"] if rows else None,
        "total_records": len(rows),
        "ready": all(bool(gate["met"]) for gate in gates.values()),
        "gates": gates,
    }


def write_proof_artifact(
    records_path: Path = DEFAULT_RECORDS_PATH,
    output_path: Path = DEFAULT_PROOF_PATH,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Verify the log, then atomically publish its latest proof summary."""

    records = load_records(records_path)
    artifact = build_proof_artifact(
        records,
        source_path=records_path,
        generated_at=generated_at,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(artifact, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return artifact


__all__ = [
    "BurninRecordError",
    "BurninRecorder",
    "CallOutcome",
    "DEFAULT_PROOF_PATH",
    "DEFAULT_RECORDS_PATH",
    "PROOF_SCHEMA_VERSION",
    "RECORD_SCHEMA_VERSION",
    "build_proof_artifact",
    "infer_model_family",
    "load_records",
    "verify_family_identity",
    "write_proof_artifact",
]
