"""Frozen holdout registry and exposure custody for outcome-backed evaluation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib
import json
import os
from pathlib import Path
import re
import threading
from types import ModuleType
from typing import Any, TextIO

from aragora.evaluation.outcome_backed_analysis import ANALYSIS_CONTRACT_VERSION
from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    SPLIT_COUNTS,
    canonical_json_sha256,
    validate_corpus_directory,
)
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION

try:
    fcntl: ModuleType | None = importlib.import_module("fcntl")
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


HOLDOUT_CONTRACT_VERSION = "outcome-backed-decision-quality-holdout/1.0"
HOLDOUT_LEDGER_SCHEMA = "outcome-backed-decision-quality-holdout-ledger/1.0"
MAX_HOLDOUT_EXPOSURES = 3

_REGISTRY_KEYS = frozenset(
    {"contract_version", "benchmark_id", "holdout_count", "cases", "registry_hash"}
)
_REGISTRY_CASE_KEYS = frozenset({"case_id", "case_outcome_sha256"})
_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "holdout_contract_version",
        "benchmark_id",
        "sequence",
        "event_id",
        "registry_hash",
        "scorer_contract_version",
        "analysis_contract_version",
        "run_label",
        "purpose",
        "recorded_at",
        "previous_event_sha256",
        "event_sha256",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ZERO_HASH = "0" * 64
_PROCESS_LOCK = threading.RLock()


class HoldoutLedgerError(RuntimeError):
    """Raised when holdout custody state is malformed or inconsistent."""


class HoldoutExposureLimitError(HoldoutLedgerError):
    """Raised before an exposure would exceed the frozen custody limit."""


@dataclass(frozen=True)
class RegistryExposureSummary:
    """Exposure state for one frozen holdout registry."""

    registry_hash: str
    exposure_count: int
    remaining_exposures: int
    run_labels: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "registry_hash": self.registry_hash,
            "exposure_count": self.exposure_count,
            "remaining_exposures": self.remaining_exposures,
            "run_labels": list(self.run_labels),
        }


@dataclass(frozen=True)
class HoldoutLedgerSnapshot:
    """Deterministic summary of all recorded holdout exposures."""

    event_count: int
    registries: tuple[RegistryExposureSummary, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "holdout_contract_version": HOLDOUT_CONTRACT_VERSION,
            "max_exposures_per_registry": MAX_HOLDOUT_EXPOSURES,
            "event_count": self.event_count,
            "registries": [registry.to_dict() for registry in self.registries],
        }


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HoldoutLedgerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be an explicit UTC timestamp")
    if value.utcoffset() != timedelta(0):
        raise ValueError("recorded_at must use UTC")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_document(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load validated corpus document {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"validated corpus document {path} must be an object")
    return value


def build_holdout_registry(corpus_dir: Path | str) -> dict[str, object]:
    """Build a deterministic registry binding every holdout case to its outcome."""

    root = Path(corpus_dir)
    report = validate_corpus_directory(root)
    if not report.valid:
        summary = "; ".join(
            f"{issue.code}@{issue.path}: {issue.message}" for issue in report.issues[:5]
        )
        raise ValueError(f"outcome-backed corpus is invalid: {summary}")

    entries: list[dict[str, str]] = []
    for corpus_path in sorted(root.glob("*.corpus.json")):
        corpus = _load_document(corpus_path)
        outcome_path = corpus_path.with_name(
            corpus_path.name.replace(".corpus.json", ".outcomes.json")
        )
        sidecar = _load_document(outcome_path)
        outcomes = {
            str(outcome["case_id"]): outcome
            for outcome in sidecar["outcomes"]
            if isinstance(outcome, dict)
        }
        for case in corpus["cases"]:
            if not isinstance(case, dict) or case.get("split") != "holdout":
                continue
            case_id = str(case["case_id"])
            outcome = outcomes.get(case_id)
            if outcome is None:
                raise ValueError(f"validated corpus is missing outcome for holdout {case_id}")
            entries.append(
                {
                    "case_id": case_id,
                    "case_outcome_sha256": canonical_json_sha256(
                        {"case": case, "outcome": outcome}
                    ),
                }
            )
    entries.sort(key=lambda item: item["case_id"])
    expected_holdouts = SPLIT_COUNTS["holdout"]
    if len(entries) != expected_holdouts:
        raise ValueError(f"expected {expected_holdouts} holdout cases, found {len(entries)}")
    unhashed: dict[str, object] = {
        "contract_version": HOLDOUT_CONTRACT_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "holdout_count": expected_holdouts,
        "cases": entries,
    }
    return {**unhashed, "registry_hash": canonical_json_sha256(unhashed)}


def _validate_registry(registry: Mapping[str, object]) -> str:
    if set(registry) != _REGISTRY_KEYS:
        raise ValueError("holdout registry has unexpected or missing fields")
    if registry.get("contract_version") != HOLDOUT_CONTRACT_VERSION:
        raise ValueError("holdout registry contract version mismatch")
    if registry.get("benchmark_id") != BENCHMARK_ID:
        raise ValueError("holdout registry benchmark mismatch")
    expected_count = SPLIT_COUNTS["holdout"]
    if registry.get("holdout_count") != expected_count:
        raise ValueError(f"holdout registry must contain {expected_count} cases")
    cases = registry.get("cases")
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise ValueError(f"holdout registry must contain {expected_count} case entries")
    case_ids: list[str] = []
    for index, item in enumerate(cases):
        if not isinstance(item, dict) or set(item) != _REGISTRY_CASE_KEYS:
            raise ValueError(f"invalid holdout registry case at index {index}")
        case_id = _required_text(item.get("case_id"), "case_id")
        digest = item.get("case_outcome_sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ValueError(f"invalid case/outcome hash for {case_id}")
        case_ids.append(case_id)
    if case_ids != sorted(case_ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError("holdout registry case IDs must be unique and sorted")
    claimed_hash = registry.get("registry_hash")
    if not isinstance(claimed_hash, str) or not _SHA256_RE.fullmatch(claimed_hash):
        raise ValueError("invalid holdout registry hash")
    unhashed = dict(registry)
    unhashed.pop("registry_hash")
    if canonical_json_sha256(unhashed) != claimed_hash:
        raise ValueError("holdout registry hash mismatch")
    return claimed_hash


class OutcomeBackedHoldoutLedger:
    """Cross-process-safe append-only exposure ledger for frozen holdouts."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def _locked(self, *, create: bool, exclusive: bool) -> Iterator[TextIO | None]:
        with _PROCESS_LOCK:
            if not create and not self.path.exists():
                yield None
                return
            try:
                if create:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open("a+" if create else "r", encoding="utf-8")
            except OSError as exc:
                raise HoldoutLedgerError(f"cannot open holdout ledger: {exc}") from exc
            try:
                if fcntl is not None:
                    lock = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                    fcntl.flock(handle.fileno(), lock)
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    def _read_events(self, handle: TextIO | None) -> list[dict[str, object]]:
        if handle is None:
            return []
        handle.seek(0)
        events: list[dict[str, object]] = []
        previous_hash = _ZERO_HASH
        run_labels: set[str] = set()
        registry_counts: Counter[str] = Counter()
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith("\n") or not raw.strip():
                raise HoldoutLedgerError(f"invalid ledger record at line {line_number}")
            try:
                event = json.loads(raw, object_pairs_hook=_object_pairs)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise HoldoutLedgerError(
                    f"invalid ledger JSON at line {line_number}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                raise HoldoutLedgerError(f"ledger record {line_number} must be an object")
            self._validate_event(event, line_number=line_number, previous_hash=previous_hash)
            run_label = str(event["run_label"])
            if run_label in run_labels:
                raise HoldoutLedgerError(f"duplicate run label at line {line_number}")
            run_labels.add(run_label)
            registry_hash = str(event["registry_hash"])
            registry_counts[registry_hash] += 1
            if registry_counts[registry_hash] > MAX_HOLDOUT_EXPOSURES:
                raise HoldoutLedgerError(f"holdout exposure limit exceeded at line {line_number}")
            previous_hash = str(event["event_sha256"])
            events.append(event)
        return events

    def _validate_event(
        self, event: dict[str, object], *, line_number: int, previous_hash: str
    ) -> None:
        if set(event) != _EVENT_KEYS:
            raise HoldoutLedgerError(f"unexpected ledger fields at line {line_number}")
        if event.get("schema_version") != HOLDOUT_LEDGER_SCHEMA:
            raise HoldoutLedgerError(f"ledger schema mismatch at line {line_number}")
        if event.get("holdout_contract_version") != HOLDOUT_CONTRACT_VERSION:
            raise HoldoutLedgerError(f"holdout contract mismatch at line {line_number}")
        if event.get("benchmark_id") != BENCHMARK_ID:
            raise HoldoutLedgerError(f"benchmark mismatch at line {line_number}")
        if event.get("sequence") != line_number:
            raise HoldoutLedgerError(f"non-contiguous sequence at line {line_number}")
        if event.get("previous_event_sha256") != previous_hash:
            raise HoldoutLedgerError(f"hash-chain mismatch at line {line_number}")
        registry_hash = event.get("registry_hash")
        if not isinstance(registry_hash, str) or not _SHA256_RE.fullmatch(registry_hash):
            raise HoldoutLedgerError(f"invalid registry hash at line {line_number}")
        for field in ("run_label", "purpose"):
            try:
                _required_text(event.get(field), field)
            except ValueError as exc:
                raise HoldoutLedgerError(f"{exc} at line {line_number}") from exc
        if event.get("scorer_contract_version") != SCORER_CONTRACT_VERSION:
            raise HoldoutLedgerError(f"scorer contract mismatch at line {line_number}")
        if event.get("analysis_contract_version") != ANALYSIS_CONTRACT_VERSION:
            raise HoldoutLedgerError(f"analysis contract mismatch at line {line_number}")
        recorded_at = event.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at.endswith("Z"):
            raise HoldoutLedgerError(f"invalid UTC timestamp at line {line_number}")
        try:
            instant = datetime.fromisoformat(recorded_at[:-1] + "+00:00")
        except ValueError as exc:
            raise HoldoutLedgerError(f"invalid UTC timestamp at line {line_number}") from exc
        if instant.utcoffset() != timedelta(0):
            raise HoldoutLedgerError(f"non-UTC timestamp at line {line_number}")
        expected_id = f"exposure:{registry_hash}:{event['run_label']}"
        if event.get("event_id") != expected_id:
            raise HoldoutLedgerError(f"invalid event ID at line {line_number}")
        claimed_hash = event.get("event_sha256")
        if not isinstance(claimed_hash, str) or not _SHA256_RE.fullmatch(claimed_hash):
            raise HoldoutLedgerError(f"invalid event hash at line {line_number}")
        unhashed = dict(event)
        unhashed.pop("event_sha256")
        if canonical_json_sha256(unhashed) != claimed_hash:
            raise HoldoutLedgerError(f"event hash mismatch at line {line_number}")

    def _append(
        self, handle: TextIO, events: list[dict[str, object]], event: dict[str, object]
    ) -> None:
        event["sequence"] = len(events) + 1
        event["previous_event_sha256"] = str(events[-1]["event_sha256"]) if events else _ZERO_HASH
        unhashed = dict(event)
        unhashed.pop("event_sha256")
        event["event_sha256"] = canonical_json_sha256(unhashed)
        try:
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            raise HoldoutLedgerError(f"cannot append holdout ledger: {exc}") from exc

    def record_exposure(
        self,
        *,
        registry: Mapping[str, object],
        registry_hash: str,
        scorer_contract_version: str,
        analysis_contract_version: str,
        run_label: str,
        purpose: str,
        recorded_at: datetime,
    ) -> dict[str, object]:
        """Record one explicit holdout exposure after validating frozen identity."""

        validated_hash = _validate_registry(registry)
        if registry_hash != validated_hash:
            raise ValueError("supplied registry_hash does not match the holdout registry")
        if scorer_contract_version != SCORER_CONTRACT_VERSION:
            raise ValueError("scorer_contract_version does not match the frozen scorer")
        if analysis_contract_version != ANALYSIS_CONTRACT_VERSION:
            raise ValueError(
                "analysis_contract_version does not match the frozen analysis contract"
            )
        run_label = _required_text(run_label, "run_label")
        purpose = _required_text(purpose, "purpose")
        timestamp = _utc_text(recorded_at)

        with self._locked(create=True, exclusive=True) as handle:
            if handle is None:
                raise HoldoutLedgerError("holdout ledger handle unavailable")
            events = self._read_events(handle)
            if any(event["run_label"] == run_label for event in events):
                raise HoldoutLedgerError(f"duplicate run label: {run_label}")
            exposures = sum(event["registry_hash"] == registry_hash for event in events)
            if exposures >= MAX_HOLDOUT_EXPOSURES:
                raise HoldoutExposureLimitError(
                    f"holdout registry {registry_hash} already has {exposures} exposures; "
                    f"limit is {MAX_HOLDOUT_EXPOSURES}"
                )
            event: dict[str, object] = {
                "schema_version": HOLDOUT_LEDGER_SCHEMA,
                "holdout_contract_version": HOLDOUT_CONTRACT_VERSION,
                "benchmark_id": BENCHMARK_ID,
                "sequence": 0,
                "event_id": f"exposure:{registry_hash}:{run_label}",
                "registry_hash": registry_hash,
                "scorer_contract_version": scorer_contract_version,
                "analysis_contract_version": analysis_contract_version,
                "run_label": run_label,
                "purpose": purpose,
                "recorded_at": timestamp,
                "previous_event_sha256": "",
                "event_sha256": "",
            }
            self._append(handle, events, event)
            self._read_events(handle)
            return event

    def snapshot(self) -> HoldoutLedgerSnapshot:
        with self._locked(create=False, exclusive=False) as handle:
            events = self._read_events(handle)
        grouped: dict[str, list[str]] = {}
        for event in events:
            grouped.setdefault(str(event["registry_hash"]), []).append(str(event["run_label"]))
        summaries = tuple(
            RegistryExposureSummary(
                registry_hash=registry_hash,
                exposure_count=len(labels),
                remaining_exposures=MAX_HOLDOUT_EXPOSURES - len(labels),
                run_labels=tuple(labels),
            )
            for registry_hash, labels in sorted(grouped.items())
        )
        return HoldoutLedgerSnapshot(event_count=len(events), registries=summaries)


__all__ = [
    "HOLDOUT_CONTRACT_VERSION",
    "HOLDOUT_LEDGER_SCHEMA",
    "MAX_HOLDOUT_EXPOSURES",
    "HoldoutExposureLimitError",
    "HoldoutLedgerError",
    "HoldoutLedgerSnapshot",
    "OutcomeBackedHoldoutLedger",
    "RegistryExposureSummary",
    "build_holdout_registry",
]
