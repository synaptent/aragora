"""Frozen execution and result contract for outcome-backed development runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from aragora.evaluation.outcome_backed_batch import (
    validate_development_packet_set,
    validate_development_plan,
)
from aragora.evaluation.outcome_backed_budget import (
    DAILY_BUDGET_CAP_USD,
    MAX_CALL_ATTEMPTS,
)
from aragora.evaluation.outcome_backed_conditions import (
    ARAGORA_TEAM,
    CLAUDE_SINGLE,
    GEMINI_SINGLE,
    OPENAI_SINGLE,
    ConditionSpec,
    preflight_condition_roster,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256
from aragora.evaluation.outcome_backed_packets import SOURCE_PACKET_SCHEMA
from aragora.evaluation.outcome_backed_scoring import (
    RECEIPT_VERIFICATION_STATES,
    validate_predicted_cruxes,
)


MANIFEST_SCHEMA = "outcome-backed-decision-quality-manifest/2.0"
RESULT_SCHEMA = "outcome-backed-decision-quality-result/2.0"
PHASE_IDS = ("single-decision", "team-proposal", "team-critique", "team-synthesis")
CONDITION_IDS = (CLAUDE_SINGLE, OPENAI_SINGLE, GEMINI_SINGLE, ARAGORA_TEAM)
DAILY_PAID_SPEND_CAP_USD = DAILY_BUDGET_CAP_USD
MAX_INFRASTRUCTURE_RETRIES_PER_CALL = MAX_CALL_ATTEMPTS - 1
ALLOWED_TRANSPORT = "vibeproxy-required"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SENSITIVE_ERROR_RE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:api[_-]?key|access[_-]?token|token|secret|password)"
    r"\s*[:=]\s*\S+|sk-[A-Za-z0-9_-]{8,})"
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "revision",
        "frozen_at",
        "corpus_sha256",
        "packet_set_sha256",
        "development_plan_sha256",
        "condition_roster_sha256",
        "phase_template_sha256",
        "implementation_sha",
        "policy",
        "manifest_sha256",
    }
)
_POLICY_KEYS = frozenset(
    {
        "daily_paid_spend_cap_usd",
        "max_infrastructure_retries_per_call",
        "allowed_transport",
        "paid_fallback_allowed",
    }
)
_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "manifest_sha256",
        "implementation_sha",
        "development_plan_sha256",
        "batch_id",
        "case_id",
        "packet_sha256",
        "split",
        "repetition",
        "condition_id",
        "started_at",
        "completed_at",
        "calls",
        "output",
        "receipt",
        "error",
        "result_sha256",
    }
)
_CALL_KEYS = frozenset(
    {
        "call_id",
        "sequence",
        "role",
        "family",
        "requested_model",
        "resolved_model",
        "transport",
        "protocol",
        "catalog_owner",
        "input_call_ids",
        "prompt_sha256",
        "response_sha256",
        "attempts",
        "usage",
        "billable_cost_usd",
        "provider_equivalent_cost_usd",
        "latency_ms",
        "normalized_output",
        "error",
    }
)
_ATTEMPT_KEYS = frozenset(
    {
        "attempt",
        "status",
        "occurred_at",
        "latency_ms",
        "response_sha256",
        "usage",
        "billable_cost_usd",
        "provider_equivalent_cost_usd",
        "error_class",
    }
)
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens"})
_OUTPUT_KEYS = frozenset(
    {
        "selected_option_id",
        "forecast_probability",
        "confidence",
        "cruxes",
        "source_ids",
        "summary",
    }
)
_CRITIQUE_OUTPUT_KEYS = frozenset({"target_call_id", "summary", "source_ids"})
_RECEIPT_KEYS = frozenset({"receipt_hash", "verification"})
_ERROR_KEYS = frozenset({"error_class", "message"})
_ATTEMPT_STATUSES = frozenset(
    {
        "success",
        "infrastructure_error",
        "output_contract_error",
        "model_error",
        "identity_error",
        "credential_error",
        "transport_error",
        "budget_error",
    }
)
_CRITIQUE_TARGET = {"claude": "openai", "openai": "gemini", "gemini": "claude"}


class OutcomeBackedContractError(ValueError):
    """Raised when a manifest or result violates the frozen contract."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OutcomeBackedContractError(f"{field} must be an object")
    return value


def _keys(value: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if missing := sorted(expected - set(value)):
        raise OutcomeBackedContractError(f"{field} is missing keys: {', '.join(missing)}")
    if unexpected := sorted(set(value) - expected):
        raise OutcomeBackedContractError(f"{field} has unexpected keys: {', '.join(unexpected)}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeBackedContractError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    digest = _text(value, field)
    if not _SHA256_RE.fullmatch(digest):
        raise OutcomeBackedContractError(f"{field} must be a lowercase SHA-256")
    return digest


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise OutcomeBackedContractError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OutcomeBackedContractError(f"{field} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        upper = f" <= {maximum}" if maximum is not None else ""
        raise OutcomeBackedContractError(f"{field} must be finite and >= 0{upper}")
    return result


def _timestamp(value: object, field: str) -> datetime:
    text = _text(value, field)
    if not text.endswith("Z"):
        raise OutcomeBackedContractError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise OutcomeBackedContractError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise OutcomeBackedContractError(f"{field} must be UTC")
    return parsed


def _sequence(value: object, field: str, *, allow_empty: bool = False) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OutcomeBackedContractError(f"{field} must be an array")
    if not allow_empty and not value:
        raise OutcomeBackedContractError(f"{field} must not be empty")
    return value


def _money_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _money(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise OutcomeBackedContractError(f"{field} must be a canonical decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise OutcomeBackedContractError(f"{field} must be a finite non-negative amount") from exc
    if not amount.is_finite() or amount < 0 or value != _money_text(amount):
        raise OutcomeBackedContractError(f"{field} must be a canonical non-negative amount")
    return amount


def sanitize_error_message(value: object) -> str:
    """Return a bounded single-line error safe for durable artifacts."""

    text = " ".join(str(value).split())
    text = _SENSITIVE_ERROR_RE.sub("<redacted>", text)
    return (text or "unspecified error")[:500]


def _validate_error(value: object, field: str) -> Mapping[str, Any]:
    error = _mapping(value, field)
    _keys(error, _ERROR_KEYS, field)
    error_class = _text(error.get("error_class"), f"{field}.error_class")
    if error_class not in _ATTEMPT_STATUSES - {"success"}:
        raise OutcomeBackedContractError(f"{field}.error_class is not recognized")
    message = _text(error.get("message"), f"{field}.message")
    if message != sanitize_error_message(message):
        raise OutcomeBackedContractError(f"{field}.message must be sanitized")
    return error


def build_execution_manifest(
    *,
    revision: str,
    frozen_at: str,
    corpus_sha256: str,
    packet_set: Mapping[str, Any],
    development_plan: Mapping[str, Any],
    phase_template_sha256: Mapping[str, str],
    implementation_sha: str,
) -> dict[str, object]:
    """Build the canonical development execution manifest from verified artifacts."""

    packet_set_sha256, _ = validate_development_packet_set(packet_set)
    plan_sha256 = validate_development_plan(development_plan)
    # The planner requires both source artifacts for a full rebuild; here its
    # self-authenticating digest plus packet-set binding is the frozen input.
    if development_plan.get("packet_set_sha256") != packet_set_sha256:
        raise OutcomeBackedContractError("development plan does not bind the packet set")
    roster = preflight_condition_roster()
    manifest: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "revision": revision,
        "frozen_at": frozen_at,
        "corpus_sha256": corpus_sha256,
        "packet_set_sha256": packet_set_sha256,
        "development_plan_sha256": plan_sha256,
        "condition_roster_sha256": roster.roster_sha256,
        "phase_template_sha256": dict(phase_template_sha256),
        "implementation_sha": implementation_sha,
        "policy": {
            "daily_paid_spend_cap_usd": _money_text(DAILY_PAID_SPEND_CAP_USD),
            "max_infrastructure_retries_per_call": MAX_INFRASTRUCTURE_RETRIES_PER_CALL,
            "allowed_transport": ALLOWED_TRANSPORT,
            "paid_fallback_allowed": False,
        },
    }
    manifest["manifest_sha256"] = canonical_json_sha256(manifest)
    validate_execution_manifest(manifest)
    return manifest


def validate_execution_manifest(
    manifest: Mapping[str, Any],
    *,
    packet_set: Mapping[str, Any] | None = None,
    development_plan: Mapping[str, Any] | None = None,
) -> str:
    """Validate an execution manifest and return its canonical digest."""

    _keys(manifest, _MANIFEST_KEYS, "manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise OutcomeBackedContractError(f"manifest.schema_version must be {MANIFEST_SCHEMA}")
    if manifest.get("benchmark_id") != BENCHMARK_ID:
        raise OutcomeBackedContractError("manifest benchmark mismatch")
    _text(manifest.get("revision"), "manifest.revision")
    _timestamp(manifest.get("frozen_at"), "manifest.frozen_at")
    _sha256(manifest.get("corpus_sha256"), "manifest.corpus_sha256")
    packet_hash = _sha256(manifest.get("packet_set_sha256"), "manifest.packet_set_sha256")
    plan_hash = _sha256(manifest.get("development_plan_sha256"), "manifest.development_plan_sha256")
    roster_hash = _sha256(
        manifest.get("condition_roster_sha256"), "manifest.condition_roster_sha256"
    )
    if roster_hash != preflight_condition_roster().roster_sha256:
        raise OutcomeBackedContractError("manifest does not bind the exact frozen roster")

    phase_hashes = _mapping(manifest.get("phase_template_sha256"), "manifest.phase_template_sha256")
    if set(phase_hashes) != set(PHASE_IDS):
        raise OutcomeBackedContractError("manifest must bind the four exact phase templates")
    for phase_id in PHASE_IDS:
        _sha256(phase_hashes.get(phase_id), f"manifest.phase_template_sha256.{phase_id}")

    implementation_sha = _text(manifest.get("implementation_sha"), "manifest.implementation_sha")
    if not _GIT_SHA_RE.fullmatch(implementation_sha):
        raise OutcomeBackedContractError("manifest.implementation_sha must be a full Git SHA")
    policy = _mapping(manifest.get("policy"), "manifest.policy")
    _keys(policy, _POLICY_KEYS, "manifest.policy")
    if (
        _money(policy.get("daily_paid_spend_cap_usd"), "manifest.policy.daily_paid_spend_cap_usd")
        != DAILY_PAID_SPEND_CAP_USD
    ):
        raise OutcomeBackedContractError("manifest daily paid-spend cap must remain USD 25")
    if policy.get("max_infrastructure_retries_per_call") != MAX_INFRASTRUCTURE_RETRIES_PER_CALL:
        raise OutcomeBackedContractError("manifest must allow exactly one infrastructure retry")
    if (
        policy.get("allowed_transport") != ALLOWED_TRANSPORT
        or policy.get("paid_fallback_allowed") is not False
    ):
        raise OutcomeBackedContractError("manifest must require VibeProxy with no paid fallback")

    claimed = _sha256(manifest.get("manifest_sha256"), "manifest.manifest_sha256")
    unhashed = dict(manifest)
    unhashed.pop("manifest_sha256")
    if canonical_json_sha256(unhashed) != claimed:
        raise OutcomeBackedContractError("manifest hash mismatch")

    if (packet_set is None) != (development_plan is None):
        raise OutcomeBackedContractError(
            "source verification requires packet_set and development_plan"
        )
    if packet_set is not None and development_plan is not None:
        observed_packet_hash, _ = validate_development_packet_set(packet_set)
        observed_plan_hash = validate_development_plan(development_plan)
        if observed_packet_hash != packet_hash or observed_plan_hash != plan_hash:
            raise OutcomeBackedContractError("manifest source-artifact binding mismatch")
        if development_plan.get("packet_set_sha256") != observed_packet_hash:
            raise OutcomeBackedContractError("development plan does not bind the packet set")
    return str(claimed)


def _packet_contract(
    packet: Mapping[str, Any],
) -> tuple[str, str, tuple[str, str], tuple[str, ...]]:
    if (
        packet.get("schema_version") != SOURCE_PACKET_SCHEMA
        or packet.get("benchmark_id") != BENCHMARK_ID
    ):
        raise OutcomeBackedContractError("source packet identity mismatch")
    claimed = _sha256(packet.get("packet_sha256"), "packet.packet_sha256")
    unhashed = dict(packet)
    unhashed.pop("packet_sha256", None)
    if canonical_json_sha256(unhashed) != claimed:
        raise OutcomeBackedContractError("source packet hash mismatch")
    case = _mapping(packet.get("case"), "packet.case")
    case_id = _text(case.get("case_id"), "packet.case.case_id")
    split = _text(case.get("split"), "packet.case.split")
    options = _sequence(case.get("options"), "packet.case.options")
    if len(options) != 2:
        raise OutcomeBackedContractError("packet.case.options must contain exactly two options")
    option_ids = tuple(
        _text(
            _mapping(item, f"packet.case.options[{index}]").get("option_id"),
            f"packet.case.options[{index}].option_id",
        )
        for index, item in enumerate(options)
    )
    if len(set(option_ids)) != 2:
        raise OutcomeBackedContractError("packet option IDs must be unique")
    sources = _sequence(packet.get("sources"), "packet.sources")
    source_ids = tuple(
        _text(
            _mapping(item, f"packet.sources[{index}]").get("source_id"),
            f"packet.sources[{index}].source_id",
        )
        for index, item in enumerate(sources)
    )
    if len(set(source_ids)) != len(source_ids):
        raise OutcomeBackedContractError("packet source IDs must be unique")
    return case_id, split, (option_ids[0], option_ids[1]), source_ids


def validate_normalized_output(
    value: object,
    *,
    option_ids: Sequence[str],
    source_ids: Sequence[str],
    field: str = "output",
) -> None:
    """Validate the runner/scorer shared normalized decision output."""

    output = _mapping(value, field)
    _keys(output, _OUTPUT_KEYS, field)
    if output.get("selected_option_id") not in option_ids:
        raise OutcomeBackedContractError(f"{field}.selected_option_id is not a case option")
    _number(output.get("forecast_probability"), f"{field}.forecast_probability", maximum=1.0)
    _number(output.get("confidence"), f"{field}.confidence", maximum=1.0)
    try:
        validate_predicted_cruxes(output.get("cruxes"), field=f"{field}.cruxes")
    except ValueError as exc:
        raise OutcomeBackedContractError(str(exc)) from exc
    cited = _sequence(output.get("source_ids"), f"{field}.source_ids", allow_empty=True)
    parsed = tuple(_text(item, f"{field}.source_ids[{index}]") for index, item in enumerate(cited))
    if len(set(parsed)) != len(parsed):
        raise OutcomeBackedContractError(f"{field}.source_ids must not contain duplicates")
    if unknown := sorted(set(parsed) - set(source_ids)):
        raise OutcomeBackedContractError(
            f"{field}.source_ids contains unknown IDs: {', '.join(unknown)}"
        )
    _text(output.get("summary"), f"{field}.summary")


def _validate_critique_output(
    value: object, *, target_call_id: str, source_ids: Sequence[str], field: str
) -> None:
    output = _mapping(value, field)
    _keys(output, _CRITIQUE_OUTPUT_KEYS, field)
    if output.get("target_call_id") != target_call_id:
        raise OutcomeBackedContractError(f"{field}.target_call_id does not match critique routing")
    _text(output.get("summary"), f"{field}.summary")
    cited = _sequence(output.get("source_ids"), f"{field}.source_ids", allow_empty=True)
    parsed = tuple(_text(item, f"{field}.source_ids[{index}]") for index, item in enumerate(cited))
    if len(set(parsed)) != len(parsed) or set(parsed) - set(source_ids):
        raise OutcomeBackedContractError(f"{field}.source_ids must be unique packet source IDs")


def _usage(value: object, field: str) -> dict[str, int]:
    usage = _mapping(value, field)
    _keys(usage, _USAGE_KEYS, field)
    input_tokens = _integer(usage.get("input_tokens"), f"{field}.input_tokens")
    output_tokens = _integer(usage.get("output_tokens"), f"{field}.output_tokens")
    total_tokens = _integer(usage.get("total_tokens"), f"{field}.total_tokens")
    if total_tokens != input_tokens + output_tokens:
        raise OutcomeBackedContractError(f"{field}.total_tokens must equal input plus output")
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _condition_map() -> dict[str, ConditionSpec]:
    return {
        condition.condition_id: condition for condition in preflight_condition_roster().conditions
    }


def _expected_calls(
    *, case_id: str, condition: ConditionSpec, synthesis_family: str | None
) -> list[tuple[str, str, str, tuple[str, ...]]]:
    prefix = f"{case_id}:{condition.condition_id}"
    families = tuple(member.family for member in condition.members)
    if condition.condition_id != ARAGORA_TEAM:
        family = families[0]
        return [(f"{prefix}:decision:{family}", "decision", family, ())]
    proposals: list[tuple[str, str, str, tuple[str, ...]]] = [
        (f"{prefix}:proposal:{family}", "proposal", family, ()) for family in families
    ]
    critiques: list[tuple[str, str, str, tuple[str, ...]]] = [
        (
            f"{prefix}:critique:{family}",
            "critique",
            family,
            (f"{prefix}:proposal:{_CRITIQUE_TARGET[family]}",),
        )
        for family in families
    ]
    if synthesis_family is None:
        return proposals + critiques
    synthesis_inputs = tuple(item[0] for item in proposals + critiques)
    return (
        proposals
        + critiques
        + [
            (
                f"{prefix}:synthesis:{synthesis_family}",
                "synthesis",
                synthesis_family,
                synthesis_inputs,
            )
        ]
    )


def _validate_attempts(
    value: object,
    *,
    field: str,
    started_at: datetime,
    completed_at: datetime,
) -> tuple[str, list[dict[str, int]], Decimal, Decimal, float, str | None]:
    attempts = _sequence(value, field)
    if len(attempts) > MAX_CALL_ATTEMPTS:
        raise OutcomeBackedContractError(f"{field} exceeds the one-infrastructure-retry policy")
    statuses: list[str] = []
    usages: list[dict[str, int]] = []
    billable = Decimal("0")
    equivalent = Decimal("0")
    latency = 0.0
    response_hash: str | None = None
    previous_occurred_at: datetime | None = None
    for index, raw in enumerate(attempts):
        attempt_field = f"{field}[{index}]"
        attempt = _mapping(raw, attempt_field)
        _keys(attempt, _ATTEMPT_KEYS, attempt_field)
        if attempt.get("attempt") != index + 1:
            raise OutcomeBackedContractError(f"{attempt_field}.attempt must be sequential from 1")
        status = _text(attempt.get("status"), f"{attempt_field}.status")
        if status not in _ATTEMPT_STATUSES:
            raise OutcomeBackedContractError(f"{attempt_field}.status is not recognized")
        occurred_at = _timestamp(attempt.get("occurred_at"), f"{attempt_field}.occurred_at")
        if not started_at <= occurred_at <= completed_at:
            raise OutcomeBackedContractError(
                f"{attempt_field}.occurred_at is outside the result window"
            )
        if previous_occurred_at is not None and occurred_at < previous_occurred_at:
            raise OutcomeBackedContractError(f"{field} attempt timestamps must be ordered")
        previous_occurred_at = occurred_at
        observed_hash = _sha256(
            attempt.get("response_sha256"), f"{attempt_field}.response_sha256", optional=True
        )
        error_class = attempt.get("error_class")
        if status == "success":
            if observed_hash is None or error_class is not None:
                raise OutcomeBackedContractError(
                    f"{attempt_field} success requires a response hash and no error"
                )
        else:
            if error_class != status:
                raise OutcomeBackedContractError(
                    f"{attempt_field}.error_class must equal its failed status"
                )
        statuses.append(status)
        usage = _usage(attempt.get("usage"), f"{attempt_field}.usage")
        if status == "success" and usage["total_tokens"] == 0:
            raise OutcomeBackedContractError(
                f"{attempt_field}.usage must record successful response tokens"
            )
        usages.append(usage)
        billable += _money(attempt.get("billable_cost_usd"), f"{attempt_field}.billable_cost_usd")
        equivalent += _money(
            attempt.get("provider_equivalent_cost_usd"),
            f"{attempt_field}.provider_equivalent_cost_usd",
        )
        latency += _number(attempt.get("latency_ms"), f"{attempt_field}.latency_ms")
        response_hash = observed_hash
    if len(statuses) == 2 and statuses[0] != "infrastructure_error":
        raise OutcomeBackedContractError(f"{field} may retry only after infrastructure_error")
    if "success" in statuses[:-1]:
        raise OutcomeBackedContractError(f"{field} must not retry after success")
    return statuses[-1], usages, billable, equivalent, latency, response_hash


def _validate_call(
    value: object,
    *,
    expected: tuple[str, str, str, tuple[str, ...]],
    sequence: int,
    condition: ConditionSpec,
    option_ids: Sequence[str],
    source_ids: Sequence[str],
    started_at: datetime,
    completed_at: datetime,
) -> tuple[str, Decimal]:
    field = f"result.calls[{sequence - 1}]"
    call = _mapping(value, field)
    _keys(call, _CALL_KEYS, field)
    expected_id, expected_role, expected_family, expected_inputs = expected
    if call.get("call_id") != expected_id or call.get("sequence") != sequence:
        raise OutcomeBackedContractError(f"{field} identity or sequence is not canonical")
    if call.get("role") != expected_role or call.get("family") != expected_family:
        raise OutcomeBackedContractError(f"{field} role/family does not match the frozen topology")
    input_ids = _sequence(call.get("input_call_ids"), f"{field}.input_call_ids", allow_empty=True)
    if tuple(input_ids) != expected_inputs:
        raise OutcomeBackedContractError(
            f"{field}.input_call_ids does not match the frozen topology"
        )

    member = next(member for member in condition.members if member.family == expected_family)
    if call.get("requested_model") != member.requested_model:
        raise OutcomeBackedContractError(
            f"{field}.requested_model does not match the frozen roster"
        )
    _sha256(call.get("prompt_sha256"), f"{field}.prompt_sha256")
    final_status, usages, billable, equivalent, latency, response_hash = _validate_attempts(
        call.get("attempts"),
        field=f"{field}.attempts",
        started_at=started_at,
        completed_at=completed_at,
    )
    identity_mismatch = (
        call.get("resolved_model") != member.expected_resolved_model
        or call.get("catalog_owner") != member.catalog_owner
    )
    transport_mismatch = (
        call.get("transport") != member.transport or call.get("protocol") != member.protocol
    )
    # Unexpected transport takes precedence because identity observed off the
    # frozen transport cannot independently satisfy the roster contract.
    if identity_mismatch and not transport_mismatch and final_status != "identity_error":
        raise OutcomeBackedContractError(
            f"{field} model/owner mismatch must fail as identity_error"
        )
    if transport_mismatch and final_status != "transport_error":
        raise OutcomeBackedContractError(f"{field} transport mismatch must fail as transport_error")
    if final_status == "identity_error" and not identity_mismatch:
        raise OutcomeBackedContractError(
            f"{field} identity_error requires an observed model/owner mismatch"
        )
    if final_status == "transport_error" and not transport_mismatch:
        raise OutcomeBackedContractError(
            f"{field} transport_error requires an observed transport/protocol mismatch"
        )
    if final_status == "success" and (identity_mismatch or transport_mismatch):
        raise OutcomeBackedContractError(
            f"{field} successful identity must match the frozen roster"
        )

    aggregate_usage = _usage(call.get("usage"), f"{field}.usage")
    for name in _USAGE_KEYS:
        if aggregate_usage[name] != sum(item[name] for item in usages):
            raise OutcomeBackedContractError(f"{field}.usage does not equal attempt usage")
    if _money(call.get("billable_cost_usd"), f"{field}.billable_cost_usd") != billable:
        raise OutcomeBackedContractError(f"{field}.billable_cost_usd does not equal attempt costs")
    if billable != 0:
        raise OutcomeBackedContractError(f"{field} violates the zero-paid-fallback policy")
    if (
        _money(call.get("provider_equivalent_cost_usd"), f"{field}.provider_equivalent_cost_usd")
        != equivalent
    ):
        raise OutcomeBackedContractError(
            f"{field}.provider_equivalent_cost_usd does not equal attempt costs"
        )
    if _number(call.get("latency_ms"), f"{field}.latency_ms") != latency:
        raise OutcomeBackedContractError(f"{field}.latency_ms does not equal attempt latency")
    if call.get("response_sha256") != response_hash:
        raise OutcomeBackedContractError(f"{field}.response_sha256 must match the final attempt")

    if final_status == "success":
        if call.get("error") is not None:
            raise OutcomeBackedContractError(f"{field}.error must be null on success")
        if expected_role == "critique":
            _validate_critique_output(
                call.get("normalized_output"),
                target_call_id=expected_inputs[0],
                source_ids=source_ids,
                field=f"{field}.normalized_output",
            )
        else:
            validate_normalized_output(
                call.get("normalized_output"),
                option_ids=option_ids,
                source_ids=source_ids,
                field=f"{field}.normalized_output",
            )
    else:
        if call.get("normalized_output") is not None:
            raise OutcomeBackedContractError(f"{field}.normalized_output must be null on failure")
        error = _validate_error(call.get("error"), f"{field}.error")
        if error.get("error_class") != final_status:
            raise OutcomeBackedContractError(f"{field}.error must match the final attempt")
    return final_status, equivalent


def _validate_receipt(value: object, *, require_verified: bool, require_missing: bool) -> None:
    receipt = _mapping(value, "result.receipt")
    _keys(receipt, _RECEIPT_KEYS, "result.receipt")
    verification = _text(receipt.get("verification"), "result.receipt.verification")
    if verification not in RECEIPT_VERIFICATION_STATES:
        raise OutcomeBackedContractError("result.receipt.verification is not recognized")
    receipt_hash = receipt.get("receipt_hash")
    if verification == "missing":
        if receipt_hash is not None:
            raise OutcomeBackedContractError("missing receipt must have a null hash")
    else:
        _sha256(receipt_hash, "result.receipt.receipt_hash")
    if require_verified and verification != "verified":
        raise OutcomeBackedContractError("successful team result requires a verified receipt")
    if require_missing and verification != "missing":
        raise OutcomeBackedContractError("result must not claim a receipt")


def validate_result_record(
    record: Mapping[str, Any], manifest: Mapping[str, Any], packet: Mapping[str, Any]
) -> dict[str, str]:
    """Validate one condition result and return its observed cost totals."""

    manifest_hash = validate_execution_manifest(manifest)
    result = _mapping(record, "result")
    _keys(result, _RESULT_KEYS, "result")
    if result.get("schema_version") != RESULT_SCHEMA or result.get("benchmark_id") != BENCHMARK_ID:
        raise OutcomeBackedContractError("result identity mismatch")
    if result.get("manifest_sha256") != manifest_hash:
        raise OutcomeBackedContractError("result does not bind the frozen manifest")
    if result.get("implementation_sha") != manifest.get("implementation_sha"):
        raise OutcomeBackedContractError("result does not bind the frozen implementation")
    if result.get("development_plan_sha256") != manifest.get("development_plan_sha256"):
        raise OutcomeBackedContractError("result does not bind the development plan")

    case_id, split, option_ids, source_ids = _packet_contract(packet)
    if result.get("case_id") != case_id or result.get("packet_sha256") != packet.get(
        "packet_sha256"
    ):
        raise OutcomeBackedContractError("result does not bind the source packet")
    if result.get("split") != split or split != "development" or result.get("repetition") != 1:
        raise OutcomeBackedContractError("result must be a development repetition-1 record")
    _text(result.get("batch_id"), "result.batch_id")
    condition_id = _text(result.get("condition_id"), "result.condition_id")
    conditions = _condition_map()
    if condition_id not in conditions:
        raise OutcomeBackedContractError("result condition is not in the frozen roster")
    condition = conditions[condition_id]
    started_at = _timestamp(result.get("started_at"), "result.started_at")
    completed_at = _timestamp(result.get("completed_at"), "result.completed_at")
    if completed_at < started_at:
        raise OutcomeBackedContractError("result completion precedes its start")

    raw_calls = _sequence(result.get("calls"), "result.calls")
    synthesis_family: str | None = None
    if condition_id == ARAGORA_TEAM and len(raw_calls) >= 7:
        synthesis_family = _text(
            _mapping(raw_calls[6], "result.calls[6]").get("family"), "result.calls[6].family"
        )
        if synthesis_family not in {member.family for member in condition.members}:
            raise OutcomeBackedContractError("team synthesis family is not in the frozen roster")
    expected = _expected_calls(
        case_id=case_id, condition=condition, synthesis_family=synthesis_family
    )
    if len(raw_calls) > len(expected):
        raise OutcomeBackedContractError("result.calls exceeds the frozen topology")
    statuses: list[str] = []
    equivalent_total = Decimal("0")
    for index, raw_call in enumerate(raw_calls, start=1):
        status, equivalent_cost = _validate_call(
            raw_call,
            expected=expected[index - 1],
            sequence=index,
            condition=condition,
            option_ids=option_ids,
            source_ids=source_ids,
            started_at=started_at,
            completed_at=completed_at,
        )
        statuses.append(status)
        equivalent_total += equivalent_cost

    successful = result.get("output") is not None
    if successful:
        if condition_id == ARAGORA_TEAM and synthesis_family is None:
            raise OutcomeBackedContractError("successful team result requires the synthesis call")
        full_expected = _expected_calls(
            case_id=case_id, condition=condition, synthesis_family=synthesis_family
        )
        if len(raw_calls) != len(full_expected) or any(status != "success" for status in statuses):
            raise OutcomeBackedContractError(
                "successful result requires the complete successful topology"
            )
        final_output = _mapping(raw_calls[-1], "result.calls[-1]").get("normalized_output")
        if result.get("output") != final_output:
            raise OutcomeBackedContractError("result.output must equal the final decision output")
        validate_normalized_output(
            result.get("output"), option_ids=option_ids, source_ids=source_ids
        )
        if result.get("error") is not None:
            raise OutcomeBackedContractError("result.error must be null on success")
    else:
        if (
            not statuses
            or statuses[-1] == "success"
            or any(status != "success" for status in statuses[:-1])
        ):
            raise OutcomeBackedContractError("failed result must stop at its first failed call")
        error = _validate_error(result.get("error"), "result.error")
        if error.get("error_class") != statuses[-1]:
            raise OutcomeBackedContractError("result.error must match the failed call")
    _validate_receipt(
        result.get("receipt"),
        require_verified=successful and condition_id == ARAGORA_TEAM,
        require_missing=not successful or condition_id != ARAGORA_TEAM,
    )

    claimed = _sha256(result.get("result_sha256"), "result.result_sha256")
    unhashed = dict(result)
    unhashed.pop("result_sha256")
    if canonical_json_sha256(unhashed) != claimed:
        raise OutcomeBackedContractError("result hash mismatch")
    return {
        "billable_cost_usd": "0",
        "provider_equivalent_cost_usd": _money_text(equivalent_total),
    }


def validate_result_batch(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    packet_set: Mapping[str, Any],
    development_plan: Mapping[str, Any],
    *,
    batch_id: str,
    packets_by_case: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    """Validate one complete four-condition development batch."""

    validate_execution_manifest(manifest, packet_set=packet_set, development_plan=development_plan)
    plan_hash = validate_development_plan(development_plan)
    if plan_hash != manifest.get("development_plan_sha256"):
        raise OutcomeBackedContractError("batch plan does not match the execution manifest")
    batch = next(
        (item for item in development_plan.get("batches", []) if item.get("batch_id") == batch_id),
        None,
    )
    if not isinstance(batch, Mapping):
        raise OutcomeBackedContractError(f"unknown development batch {batch_id}")
    case_ids = tuple(batch.get("case_ids", ()))
    packet_entries = {
        str(entry["case_id"]): str(entry["packet_sha256"])
        for entry in packet_set.get("packets", [])
    }
    expected = {(case_id, condition_id) for case_id in case_ids for condition_id in CONDITION_IDS}
    actual: set[tuple[str, str]] = set()
    equivalent_total = Decimal("0")
    for index, record in enumerate(records):
        case_id = _text(record.get("case_id"), f"records[{index}].case_id")
        condition_id = _text(record.get("condition_id"), f"records[{index}].condition_id")
        identity = (case_id, condition_id)
        if identity in actual:
            raise OutcomeBackedContractError(f"duplicate batch result {case_id}/{condition_id}")
        actual.add(identity)
        packet = packets_by_case.get(case_id)
        if packet is None:
            raise OutcomeBackedContractError(f"missing source packet for {case_id}")
        if packet.get("packet_sha256") != packet_entries.get(case_id):
            raise OutcomeBackedContractError(
                f"source packet for {case_id} does not match the frozen packet set"
            )
        if record.get("batch_id") != batch_id:
            raise OutcomeBackedContractError(f"records[{index}] has the wrong batch ID")
        totals = validate_result_record(record, manifest, packet)
        equivalent_total += Decimal(totals["provider_equivalent_cost_usd"])
    if actual != expected:
        raise OutcomeBackedContractError(
            f"result batch is incomplete or unexpected; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return {
        "batch_id": batch_id,
        "case_count": len(case_ids),
        "result_count": len(records),
        "logical_call_count": sum(len(record["calls"]) for record in records),
        "billable_cost_usd": "0",
        "provider_equivalent_cost_usd": _money_text(equivalent_total),
    }


__all__ = [
    "ALLOWED_TRANSPORT",
    "CONDITION_IDS",
    "DAILY_PAID_SPEND_CAP_USD",
    "MANIFEST_SCHEMA",
    "MAX_INFRASTRUCTURE_RETRIES_PER_CALL",
    "OutcomeBackedContractError",
    "PHASE_IDS",
    "RESULT_SCHEMA",
    "build_execution_manifest",
    "sanitize_error_message",
    "validate_execution_manifest",
    "validate_normalized_output",
    "validate_result_batch",
    "validate_result_record",
]
