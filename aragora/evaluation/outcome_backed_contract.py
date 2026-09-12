"""Pure validation for the frozen outcome-backed decision-quality execution contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
import math
import re
from typing import Any

from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    EXPECTED_CASES,
    SPLIT_COUNTS,
    canonical_json_sha256,
)
from aragora.evaluation.outcome_backed_scoring import (
    MAX_PREDICTED_CRUXES,
    MIN_PREDICTED_CRUXES,
    RECEIPT_VERIFICATION_STATES,
    SCORER_CONTRACT_VERSION,
)


MANIFEST_SCHEMA = "outcome-backed-decision-quality-manifest/1.0"
RESULT_SCHEMA = "outcome-backed-decision-quality-result/1.0"
CONDITION_IDS = ("claude_single", "openai_single", "gemini_single", "aragora_team")
MODEL_FAMILIES = ("claude", "openai", "gemini")
SINGLE_CONDITION_FAMILIES = dict(zip(CONDITION_IDS[:3], MODEL_FAMILIES, strict=True))
DAILY_COST_CAP_USD = 25.0
MAX_INFRASTRUCTURE_RETRIES_PER_CALL = 1
HOLDOUT_REPETITIONS = 2
FROZEN_CORPUS_DIGESTS = {
    "visible_sha256": "e156cf306684aeeda6796cbc88cf0678c37cf9f60fe4e161aa9846837a9db09a",
    "outcomes_sha256": "f862a78267ea3c3a2c447f6ef9c6a9b578e51433d7b416baa69af1cc3d964aae",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_KEYS = frozenset(
    "schema_version benchmark_id revision frozen_at corpus scorer_contract_version "
    "prompt_sha256 implementation_sha policy conditions".split()
)
_CORPUS_KEYS = frozenset(
    "visible_sha256 outcomes_sha256 case_count development_count holdout_count".split()
)
_PROMPT_KEYS = frozenset({"single", "team_proposal", "team_adversarial", "team_synthesis"})
_POLICY_KEYS = frozenset(
    {"daily_cost_cap_usd", "max_infrastructure_retries_per_call", "holdout_repetitions"}
)
_CONDITION_KEYS = frozenset({"condition_id", "kind", "members", "adversarial_rounds", "syntheses"})
_MEMBER_KEYS = frozenset({"family", "requested_model", "resolved_model", "transport"})
_RESULT_KEYS = frozenset(
    "schema_version benchmark_id manifest_sha256 implementation_sha case_id split repetition "
    "condition_id started_at completed_at calls output receipt error".split()
)
_CALL_KEYS = frozenset(
    {"call_id", "role", "family", "requested_model", "resolved_model", "transport", "attempts"}
)
_ATTEMPT_KEYS = frozenset(
    {"attempt", "status", "occurred_at", "latency_ms", "cost_usd", "error_class"}
)
_OUTPUT_KEYS = frozenset(
    {"selected_option_id", "forecast_probability", "cruxes", "source_ids", "text"}
)
_RECEIPT_KEYS = frozenset({"hash", "verification"})
_ERROR_KEYS = frozenset({"error_class", "message"})
_ATTEMPT_STATUSES = frozenset(
    {"success", "infrastructure_error", "model_error", "identity_error", "credential_error"}
)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _keys(value: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    actual = set(value)
    if missing := sorted(expected - actual):
        raise ValueError(f"{field} is missing keys: {', '.join(missing)}")
    if unexpected := sorted(actual - expected):
        raise ValueError(f"{field} has unexpected keys: {', '.join(unexpected)}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return text


def _timestamp(value: Any, field: str) -> datetime:
    text = _text(value, field)
    if not text.endswith("Z"):
        raise ValueError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC")
    return parsed


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: Any, field: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field} must be <= {maximum}")
    return result


def _sequence(value: Any, field: str, *, allow_empty: bool = False) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array")
    if not allow_empty and not value:
        raise ValueError(f"{field} must not be empty")
    return value


def _validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    _keys(manifest, _MANIFEST_KEYS, "manifest")
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError(f"manifest.schema_version must be {MANIFEST_SCHEMA}")
    if manifest["benchmark_id"] != BENCHMARK_ID:
        raise ValueError(f"manifest.benchmark_id must be {BENCHMARK_ID}")
    _text(manifest["revision"], "manifest.revision")
    _timestamp(manifest["frozen_at"], "manifest.frozen_at")

    corpus = _mapping(manifest["corpus"], "manifest.corpus")
    _keys(corpus, _CORPUS_KEYS, "manifest.corpus")
    for field, expected_digest in FROZEN_CORPUS_DIGESTS.items():
        digest = _sha256(corpus[field], f"manifest.corpus.{field}")
        if digest != expected_digest:
            raise ValueError(f"manifest.corpus.{field} does not match frozen corpus revision")
    if _integer(corpus["case_count"], "manifest.corpus.case_count") != EXPECTED_CASES:
        raise ValueError(f"manifest.corpus.case_count must be {EXPECTED_CASES}")
    for split, expected in SPLIT_COUNTS.items():
        field = f"{split}_count"
        if _integer(corpus[field], f"manifest.corpus.{field}") != expected:
            raise ValueError(f"manifest.corpus.{field} must be {expected}")

    if manifest["scorer_contract_version"] != SCORER_CONTRACT_VERSION:
        raise ValueError(f"manifest.scorer_contract_version must be {SCORER_CONTRACT_VERSION}")
    prompts = _mapping(manifest["prompt_sha256"], "manifest.prompt_sha256")
    _keys(prompts, _PROMPT_KEYS, "manifest.prompt_sha256")
    for name in sorted(_PROMPT_KEYS):
        _sha256(prompts[name], f"manifest.prompt_sha256.{name}")
    implementation_sha = _text(manifest["implementation_sha"], "manifest.implementation_sha")
    if not _GIT_SHA_RE.fullmatch(implementation_sha):
        raise ValueError("manifest.implementation_sha must be a 40-character lowercase Git SHA")

    policy = _mapping(manifest["policy"], "manifest.policy")
    _keys(policy, _POLICY_KEYS, "manifest.policy")
    if (
        _number(policy["daily_cost_cap_usd"], "manifest.policy.daily_cost_cap_usd")
        != DAILY_COST_CAP_USD
    ):
        raise ValueError(f"manifest.policy.daily_cost_cap_usd must be {DAILY_COST_CAP_USD}")
    if (
        _integer(
            policy["max_infrastructure_retries_per_call"],
            "manifest.policy.max_infrastructure_retries_per_call",
        )
        != MAX_INFRASTRUCTURE_RETRIES_PER_CALL
    ):
        raise ValueError(
            "manifest.policy.max_infrastructure_retries_per_call must be "
            f"{MAX_INFRASTRUCTURE_RETRIES_PER_CALL}"
        )
    if (
        _integer(policy["holdout_repetitions"], "manifest.policy.holdout_repetitions")
        != HOLDOUT_REPETITIONS
    ):
        raise ValueError(f"manifest.policy.holdout_repetitions must be {HOLDOUT_REPETITIONS}")

    conditions = _sequence(manifest["conditions"], "manifest.conditions")
    if len(conditions) != len(CONDITION_IDS):
        raise ValueError(
            f"manifest.conditions must contain exactly {len(CONDITION_IDS)} conditions"
        )
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw_condition in enumerate(conditions):
        field = f"manifest.conditions[{index}]"
        condition = _mapping(raw_condition, field)
        _keys(condition, _CONDITION_KEYS, field)
        condition_id = _text(condition["condition_id"], f"{field}.condition_id")
        kind = _text(condition["kind"], f"{field}.kind")
        adversarial_rounds = _integer(
            condition["adversarial_rounds"], f"{field}.adversarial_rounds"
        )
        syntheses = _integer(condition["syntheses"], f"{field}.syntheses")
        if condition_id in by_id:
            raise ValueError(f"manifest.conditions has duplicate condition_id {condition_id}")
        by_id[condition_id] = condition

        members = _sequence(condition["members"], f"{field}.members")
        families: list[str] = []
        for member_index, raw_member in enumerate(members):
            member_field = f"{field}.members[{member_index}]"
            member = _mapping(raw_member, member_field)
            _keys(member, _MEMBER_KEYS, member_field)
            family = _text(member["family"], f"{member_field}.family")
            if family not in MODEL_FAMILIES:
                raise ValueError(f"{member_field}.family must be a fixed benchmark family")
            families.append(family)
            for name in ("requested_model", "resolved_model", "transport"):
                _text(member[name], f"{member_field}.{name}")
        if len(set(families)) != len(families):
            raise ValueError(f"{field}.members must not repeat a model family")

        if condition_id in SINGLE_CONDITION_FAMILIES:
            expected_family = SINGLE_CONDITION_FAMILIES[condition_id]
            if kind != "single_model" or families != [expected_family]:
                raise ValueError(f"{field} must contain only the {expected_family} single model")
            if adversarial_rounds != 0 or syntheses != 0:
                raise ValueError(f"{field} single-model topology must have zero team rounds")
        elif condition_id == "aragora_team":
            if kind != "aragora_team" or set(families) != set(MODEL_FAMILIES):
                raise ValueError(f"{field} must contain exactly the three fixed model families")
            if adversarial_rounds != 1 or syntheses != 1:
                raise ValueError(f"{field} must have one adversarial round and one synthesis")
        else:
            raise ValueError(f"unknown benchmark condition_id {condition_id}")
    if set(by_id) != set(CONDITION_IDS):
        raise ValueError("manifest.conditions must contain the four fixed benchmark conditions")
    return by_id


def validate_benchmark_manifest(manifest: Mapping[str, Any]) -> str:
    """Validate a frozen benchmark manifest and return its canonical digest."""
    _validate_manifest(_mapping(manifest, "manifest"))
    return canonical_json_sha256(manifest)


def _condition_members(condition: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {member["family"]: member for member in condition["members"]}


def _validate_output(value: Any) -> None:
    output = _mapping(value, "result.output")
    _keys(output, _OUTPUT_KEYS, "result.output")
    _text(output["selected_option_id"], "result.output.selected_option_id")
    _number(output["forecast_probability"], "result.output.forecast_probability", maximum=1.0)
    _text(output["text"], "result.output.text")
    cruxes = _sequence(output["cruxes"], "result.output.cruxes")
    if not MIN_PREDICTED_CRUXES <= len(cruxes) <= MAX_PREDICTED_CRUXES:
        raise ValueError(
            f"result.output.cruxes must contain {MIN_PREDICTED_CRUXES} to {MAX_PREDICTED_CRUXES} items"
        )
    normalized_cruxes = [
        _text(item, f"result.output.cruxes[{index}]").casefold()
        for index, item in enumerate(cruxes)
    ]
    if len(set(normalized_cruxes)) != len(normalized_cruxes):
        raise ValueError("result.output.cruxes must not contain duplicates")
    sources = _sequence(output["source_ids"], "result.output.source_ids", allow_empty=True)
    normalized_sources = [
        _text(item, f"result.output.source_ids[{index}]") for index, item in enumerate(sources)
    ]
    if len(set(normalized_sources)) != len(normalized_sources):
        raise ValueError("result.output.source_ids must not contain duplicates")


def _validate_receipt(value: Any, *, require_verified: bool) -> None:
    receipt = _mapping(value, "result.receipt")
    _keys(receipt, _RECEIPT_KEYS, "result.receipt")
    verification = _text(receipt["verification"], "result.receipt.verification")
    if verification not in RECEIPT_VERIFICATION_STATES:
        raise ValueError("result.receipt.verification is not a recognized state")
    receipt_hash = receipt["hash"]
    if verification == "missing":
        if receipt_hash is not None:
            raise ValueError("result.receipt.hash must be null when the receipt is missing")
    else:
        _sha256(receipt_hash, "result.receipt.hash")
    if require_verified and verification != "verified":
        raise ValueError(
            "successful Aragora team results require an independently verified receipt"
        )


def _validate_calls(
    calls_value: Any,
    condition: Mapping[str, Any],
    *,
    started_at: datetime,
    completed_at: datetime,
) -> tuple[bool, list[tuple[datetime, float]]]:
    calls = _sequence(calls_value, "result.calls")
    members = _condition_members(condition)
    call_ids: set[str] = set()
    topology: Counter[tuple[str, str]] = Counter()
    all_succeeded = True
    costs: list[tuple[datetime, float]] = []
    for call_index, raw_call in enumerate(calls):
        field = f"result.calls[{call_index}]"
        call = _mapping(raw_call, field)
        _keys(call, _CALL_KEYS, field)
        call_id = _text(call["call_id"], f"{field}.call_id")
        if call_id in call_ids:
            raise ValueError(f"result.calls contains duplicate call_id {call_id}")
        call_ids.add(call_id)
        role = _text(call["role"], f"{field}.role")
        family = _text(call["family"], f"{field}.family")
        member = members.get(family)
        if member is None:
            raise ValueError(f"{field}.family is not in the frozen condition roster")
        for name in ("requested_model", "resolved_model", "transport"):
            if call[name] != member[name]:
                raise ValueError(f"{field}.{name} does not match the frozen model roster")
        topology[(role, family)] += 1

        attempts = _sequence(call["attempts"], f"{field}.attempts")
        if len(attempts) > MAX_INFRASTRUCTURE_RETRIES_PER_CALL + 1:
            raise ValueError(f"{field}.attempts exceeds the one-infrastructure-retry policy")
        statuses: list[str] = []
        for attempt_index, raw_attempt in enumerate(attempts):
            attempt_field = f"{field}.attempts[{attempt_index}]"
            attempt = _mapping(raw_attempt, attempt_field)
            _keys(attempt, _ATTEMPT_KEYS, attempt_field)
            if attempt["attempt"] != attempt_index + 1:
                raise ValueError(f"{attempt_field}.attempt must be sequential from 1")
            status = _text(attempt["status"], f"{attempt_field}.status")
            if status not in _ATTEMPT_STATUSES:
                raise ValueError(f"{attempt_field}.status is not recognized")
            statuses.append(status)
            occurred_at = _timestamp(attempt["occurred_at"], f"{attempt_field}.occurred_at")
            if not started_at <= occurred_at <= completed_at:
                raise ValueError(f"{attempt_field}.occurred_at must be within the result window")
            _number(attempt["latency_ms"], f"{attempt_field}.latency_ms")
            cost = _number(attempt["cost_usd"], f"{attempt_field}.cost_usd")
            costs.append((occurred_at, cost))
            error_class = attempt["error_class"]
            if status == "success":
                if error_class is not None:
                    raise ValueError(f"{attempt_field}.error_class must be null on success")
            else:
                _text(error_class, f"{attempt_field}.error_class")
        if len(statuses) == 2 and statuses[0] != "infrastructure_error":
            raise ValueError(f"{field} may retry only after an infrastructure_error")
        if "success" in statuses[:-1]:
            raise ValueError(f"{field} must not retry after success")
        all_succeeded = all_succeeded and statuses[-1] == "success"

    if condition["kind"] == "single_model":
        expected = Counter({("decision", next(iter(members))): 1})
    else:
        expected = Counter(
            {(role, family): 1 for role in ("proposal", "adversarial") for family in MODEL_FAMILIES}
        )
        synthesis_count = sum(
            count for (role, _family), count in topology.items() if role == "synthesis"
        )
        non_synthesis = Counter(
            {key: count for key, count in topology.items() if key[0] != "synthesis"}
        )
        if non_synthesis != expected or synthesis_count != 1:
            raise ValueError("result.calls does not match the frozen team topology")
        if any(role not in {"proposal", "adversarial", "synthesis"} for role, _family in topology):
            raise ValueError("result.calls contains an unknown team role")
        return all_succeeded, costs
    if topology != expected:
        raise ValueError("result.calls does not match the frozen single-model topology")
    return all_succeeded, costs


def validate_result_record(
    record: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, float]:
    """Validate one success or failure result and return its UTC-day cost entries."""
    conditions = _validate_manifest(_mapping(manifest, "manifest"))
    manifest_hash = canonical_json_sha256(manifest)
    result = _mapping(record, "result")
    _keys(result, _RESULT_KEYS, "result")
    if result["schema_version"] != RESULT_SCHEMA:
        raise ValueError(f"result.schema_version must be {RESULT_SCHEMA}")
    if result["benchmark_id"] != BENCHMARK_ID:
        raise ValueError(f"result.benchmark_id must be {BENCHMARK_ID}")
    if result["manifest_sha256"] != manifest_hash:
        raise ValueError("result.manifest_sha256 does not bind the frozen manifest")
    if result["implementation_sha"] != manifest["implementation_sha"]:
        raise ValueError("result.implementation_sha does not bind the frozen implementation")
    _text(result["case_id"], "result.case_id")
    split = result["split"]
    if split not in SPLIT_COUNTS:
        raise ValueError("result.split must be development or holdout")
    repetition = _integer(result["repetition"], "result.repetition", minimum=1)
    if split == "development" and repetition != 1:
        raise ValueError("development results must use repetition 1")
    if split == "holdout" and repetition not in range(1, HOLDOUT_REPETITIONS + 1):
        raise ValueError(f"holdout repetition must be between 1 and {HOLDOUT_REPETITIONS}")
    condition_id = _text(result["condition_id"], "result.condition_id")
    if condition_id not in conditions:
        raise ValueError("result.condition_id is not in the frozen manifest")
    started_at = _timestamp(result["started_at"], "result.started_at")
    completed_at = _timestamp(result["completed_at"], "result.completed_at")
    if completed_at < started_at:
        raise ValueError("result.completed_at must not precede result.started_at")
    all_succeeded, costs = _validate_calls(
        result["calls"], conditions[condition_id], started_at=started_at, completed_at=completed_at
    )

    successful_result = result["output"] is not None
    if successful_result:
        if not all_succeeded:
            raise ValueError("a successful result requires every logical call to succeed")
        _validate_output(result["output"])
        if result["error"] is not None:
            raise ValueError("result.error must be null on success")
    else:
        if all_succeeded:
            raise ValueError("a failed result must include a failed logical call")
        error = _mapping(result["error"], "result.error")
        _keys(error, _ERROR_KEYS, "result.error")
        _text(error["error_class"], "result.error.error_class")
        _text(error["message"], "result.error.message")
    _validate_receipt(
        result["receipt"],
        require_verified=successful_result and condition_id == "aragora_team",
    )

    totals: defaultdict[str, float] = defaultdict(float)
    for occurred_at, cost in costs:
        totals[occurred_at.date().isoformat()] += cost
    return dict(sorted(totals.items()))


def validate_result_batch(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    expected_case_ids: Sequence[str],
    split: str,
    repetition: int,
) -> dict[str, float]:
    """Validate a complete condition matrix and enforce the $25 UTC-day cap."""
    validate_benchmark_manifest(manifest)
    if split not in SPLIT_COUNTS:
        raise ValueError("split must be development or holdout")
    case_ids = tuple(_text(case_id, "expected_case_ids[]") for case_id in expected_case_ids)
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise ValueError("expected_case_ids must be a non-empty unique list")
    if len(case_ids) != SPLIT_COUNTS[split]:
        raise ValueError(
            f"expected_case_ids must contain exactly {SPLIT_COUNTS[split]} {split} cases"
        )
    expected = {(case_id, condition_id) for case_id in case_ids for condition_id in CONDITION_IDS}
    actual: set[tuple[str, str]] = set()
    daily_costs: defaultdict[str, float] = defaultdict(float)
    for index, record in enumerate(records):
        cost_entries = validate_result_record(record, manifest)
        if record["split"] != split or record["repetition"] != repetition:
            raise ValueError(f"records[{index}] does not match the requested split/repetition")
        identity = (record["case_id"], record["condition_id"])
        if identity in actual:
            raise ValueError(f"records contains duplicate result {identity[0]}/{identity[1]}")
        actual.add(identity)
        for day, cost in cost_entries.items():
            daily_costs[day] += cost
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"result batch is incomplete or unexpected; missing={missing}, unexpected={unexpected}"
        )
    for day, cost in sorted(daily_costs.items()):
        if cost > DAILY_COST_CAP_USD:
            raise ValueError(
                f"UTC-day cost cap exceeded on {day}: {cost:.6f} > {DAILY_COST_CAP_USD:.2f}"
            )
    return dict(sorted(daily_costs.items()))


__all__ = (
    "CONDITION_IDS DAILY_COST_CAP_USD FROZEN_CORPUS_DIGESTS HOLDOUT_REPETITIONS MANIFEST_SCHEMA "
    "MAX_INFRASTRUCTURE_RETRIES_PER_CALL MODEL_FAMILIES RESULT_SCHEMA "
    "validate_benchmark_manifest validate_result_batch validate_result_record"
).split()
