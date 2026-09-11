"""Deterministic, outcome-blind development batching for the benchmark."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
from typing import Any

from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    SPLIT_COUNTS,
    canonical_json_sha256,
)
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA


DEVELOPMENT_PLAN_SCHEMA = "outcome-backed-development-plan/1.0"
DEFAULT_BATCH_SIZE = 4

_PACKET_SET_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "split",
        "packet_count",
        "source_count",
        "packets",
        "packet_set_sha256",
    }
)
_PACKET_ENTRY_KEYS = frozenset({"case_id", "packet_sha256"})
_PLAN_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "split",
        "packet_set_sha256",
        "case_count",
        "batch_size",
        "batch_count",
        "batches",
        "plan_sha256",
    }
)
_BATCH_KEYS = frozenset({"batch_id", "case_ids"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class DevelopmentBatchPlanError(ValueError):
    """Raised when a development packet set cannot be planned safely."""


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DevelopmentBatchPlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DevelopmentBatchPlanError(f"{field} must be an object")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DevelopmentBatchPlanError(f"{field} must be an integer >= {minimum}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentBatchPlanError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if not _SHA256_RE.fullmatch(digest):
        raise DevelopmentBatchPlanError(f"{field} must be a lowercase SHA-256")
    return digest


def _canonical_batch_sizes(case_count: int, batch_size: int) -> tuple[int, ...]:
    """Return the only valid batch geometry for a case count and batch size."""

    batch_count = (case_count + batch_size - 1) // batch_size
    final_size = case_count - batch_size * (batch_count - 1)
    return (batch_size,) * (batch_count - 1) + (final_size,)


def load_packet_set_manifest(path: Path | str) -> Mapping[str, Any]:
    """Load one packet-set manifest while rejecting duplicate JSON keys."""

    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
    except DevelopmentBatchPlanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevelopmentBatchPlanError(f"cannot load packet-set manifest {source}: {exc}") from exc
    return _mapping(value, "packet-set manifest")


def validate_development_packet_set(manifest: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    """Validate and return the development packet-set digest and case IDs."""

    if set(manifest) != _PACKET_SET_KEYS:
        raise DevelopmentBatchPlanError("packet-set manifest has unexpected or missing fields")
    if manifest.get("schema_version") != PACKET_SET_SCHEMA:
        raise DevelopmentBatchPlanError("packet-set schema version mismatch")
    if manifest.get("benchmark_id") != BENCHMARK_ID:
        raise DevelopmentBatchPlanError("packet-set benchmark mismatch")
    if manifest.get("split") != "development":
        raise DevelopmentBatchPlanError("packet-set split must be development")

    expected = SPLIT_COUNTS["development"]
    if _integer(manifest.get("packet_count"), "packet_count") != expected:
        raise DevelopmentBatchPlanError(f"packet-set must contain exactly {expected} packets")
    _integer(manifest.get("source_count"), "source_count", minimum=1)

    raw_packets = manifest.get("packets")
    if not isinstance(raw_packets, list) or len(raw_packets) != expected:
        raise DevelopmentBatchPlanError(f"packets must contain exactly {expected} entries")
    case_ids: list[str] = []
    for index, raw_entry in enumerate(raw_packets):
        entry = _mapping(raw_entry, f"packets[{index}]")
        if set(entry) != _PACKET_ENTRY_KEYS:
            raise DevelopmentBatchPlanError(f"packets[{index}] has unexpected or missing fields")
        case_id = _text(entry.get("case_id"), f"packets[{index}].case_id")
        if not _SAFE_ID_RE.fullmatch(case_id):
            raise DevelopmentBatchPlanError(f"packets[{index}].case_id is unsafe")
        _sha256(entry.get("packet_sha256"), f"packets[{index}].packet_sha256")
        case_ids.append(case_id)
    if case_ids != sorted(case_ids) or len(set(case_ids)) != len(case_ids):
        raise DevelopmentBatchPlanError("packet case IDs must be unique and sorted")

    claimed_hash = _sha256(manifest.get("packet_set_sha256"), "packet_set_sha256")
    unhashed = dict(manifest)
    unhashed.pop("packet_set_sha256")
    if canonical_json_sha256(unhashed) != claimed_hash:
        raise DevelopmentBatchPlanError("packet-set manifest hash mismatch")
    return claimed_hash, tuple(case_ids)


def _visible_case_ids(
    cases: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    development: list[str] = []
    holdout: list[str] = []
    all_ids: set[str] = set()
    for index, case in enumerate(cases):
        case_id = _text(case.get("case_id"), f"cases[{index}].case_id")
        if case_id in all_ids:
            raise DevelopmentBatchPlanError(f"duplicate visible case ID: {case_id}")
        all_ids.add(case_id)
        split = case.get("split")
        if split == "development":
            development.append(case_id)
        elif split == "holdout":
            holdout.append(case_id)
        else:
            raise DevelopmentBatchPlanError(f"unsupported split for visible case {case_id}")
    for split, values in (("development", development), ("holdout", holdout)):
        expected = SPLIT_COUNTS[split]
        if len(values) != expected:
            raise DevelopmentBatchPlanError(
                f"visible corpus must contain exactly {expected} {split} cases"
            )
    return tuple(sorted(development)), tuple(sorted(holdout))


def build_development_plan(
    cases: Sequence[Mapping[str, Any]],
    packet_set: Mapping[str, Any],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, object]:
    """Build a deterministic plan for development cases without opening outcomes."""

    expected = SPLIT_COUNTS["development"]
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= expected
    ):
        raise DevelopmentBatchPlanError(f"batch_size must be an integer from 1 to {expected}")

    packet_set_sha256, packet_case_ids = validate_development_packet_set(packet_set)
    development_ids, holdout_ids = _visible_case_ids(cases)
    if packet_case_ids != development_ids:
        raise DevelopmentBatchPlanError(
            "packet-set case IDs do not match the visible development corpus"
        )
    if set(packet_case_ids) & set(holdout_ids):
        raise DevelopmentBatchPlanError("development packet set contains a holdout case")

    batches = [
        {
            "batch_id": f"development-{index // batch_size + 1:02d}",
            "case_ids": list(development_ids[index : index + batch_size]),
        }
        for index in range(0, len(development_ids), batch_size)
    ]
    plan: dict[str, object] = {
        "schema_version": DEVELOPMENT_PLAN_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": "development",
        "packet_set_sha256": packet_set_sha256,
        "case_count": len(development_ids),
        "batch_size": batch_size,
        "batch_count": len(batches),
        "batches": batches,
    }
    plan["plan_sha256"] = canonical_json_sha256(plan)
    return plan


def validate_development_plan(
    plan: Mapping[str, Any],
    *,
    cases: Sequence[Mapping[str, Any]] | None = None,
    packet_set: Mapping[str, Any] | None = None,
) -> str:
    """Validate a plan and optionally rebind it to its source artifacts."""

    if set(plan) != _PLAN_KEYS:
        raise DevelopmentBatchPlanError("development plan has unexpected or missing fields")
    if plan.get("schema_version") != DEVELOPMENT_PLAN_SCHEMA:
        raise DevelopmentBatchPlanError("development plan schema version mismatch")
    if plan.get("benchmark_id") != BENCHMARK_ID or plan.get("split") != "development":
        raise DevelopmentBatchPlanError("development plan identity mismatch")
    _sha256(plan.get("packet_set_sha256"), "packet_set_sha256")
    case_count = _integer(plan.get("case_count"), "case_count")
    if case_count != SPLIT_COUNTS["development"]:
        raise DevelopmentBatchPlanError("development plan case count mismatch")
    batch_size = _integer(plan.get("batch_size"), "batch_size", minimum=1)
    if batch_size > case_count:
        raise DevelopmentBatchPlanError(
            f"batch_size must not exceed {case_count} development cases"
        )

    expected_sizes = _canonical_batch_sizes(case_count, batch_size)
    batch_count = _integer(plan.get("batch_count"), "batch_count", minimum=1)
    if batch_count != len(expected_sizes):
        raise DevelopmentBatchPlanError(
            f"development plan must contain exactly {len(expected_sizes)} canonical batches"
        )
    raw_batches = plan.get("batches")
    if not isinstance(raw_batches, list) or len(raw_batches) != batch_count:
        raise DevelopmentBatchPlanError("development plan batch count mismatch")

    planned_ids: list[str] = []
    for index, (raw_batch, expected_size) in enumerate(
        zip(raw_batches, expected_sizes, strict=True), start=1
    ):
        batch = _mapping(raw_batch, f"batches[{index - 1}]")
        if set(batch) != _BATCH_KEYS or batch.get("batch_id") != f"development-{index:02d}":
            raise DevelopmentBatchPlanError(f"invalid development batch at index {index - 1}")
        case_ids = batch.get("case_ids")
        if not isinstance(case_ids, list) or len(case_ids) != expected_size:
            raise DevelopmentBatchPlanError(
                f"batch {index} must contain exactly {expected_size} case IDs"
            )
        for case_index, value in enumerate(case_ids):
            case_id = _text(value, f"batches[{index - 1}].case_ids[{case_index}]")
            if not _SAFE_ID_RE.fullmatch(case_id):
                raise DevelopmentBatchPlanError(f"unsafe case ID in batch {index}")
            planned_ids.append(case_id)
    if len(planned_ids) != case_count or planned_ids != sorted(planned_ids):
        raise DevelopmentBatchPlanError("planned case IDs must be complete, unique, and sorted")
    if len(set(planned_ids)) != len(planned_ids):
        raise DevelopmentBatchPlanError("development plan contains duplicate case IDs")

    claimed_hash = _sha256(plan.get("plan_sha256"), "plan_sha256")
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    if canonical_json_sha256(unhashed) != claimed_hash:
        raise DevelopmentBatchPlanError("development plan hash mismatch")

    if (cases is None) != (packet_set is None):
        raise DevelopmentBatchPlanError(
            "independent plan verification requires both cases and packet_set"
        )
    if cases is not None and packet_set is not None:
        canonical = build_development_plan(cases, packet_set, batch_size=batch_size)
        if dict(plan) != canonical:
            raise DevelopmentBatchPlanError("development plan does not match canonical batching")
    return claimed_hash


def write_development_plan(
    path: Path | str,
    plan: Mapping[str, Any],
    *,
    cases: Sequence[Mapping[str, Any]] | None = None,
    packet_set: Mapping[str, Any] | None = None,
) -> None:
    """Validate and atomically write a development plan."""

    validate_development_plan(plan, cases=cases, packet_set=packet_set)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
