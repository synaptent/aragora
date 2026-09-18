"""Freeze and validate the outcome-backed decision-quality manifest.

This module binds the already-merged corpus tranches to one exact benchmark
contract. It deliberately does not execute models or claim that the separate
structural/leakage validator has landed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "decision-quality-benchmark/1.0"
BENCHMARK_ID = "outcome-backed-decision-quality-v1"
BENCHMARK_REVISION = "v1"
FROZEN_AT = "2026-08-30T03:52:00Z"
CANONICAL_JSON_CONVENTION = "python-json-sort-keys-compact-utf8-no-nan-v1"
EXPECTED_MANIFEST_SHA256 = "d593152d89d948afec22ac53574076dbe9d6e2441958dec0dd666beaf4c80ead"
EXPECTED_CORPUS_SHA256 = "3a46198fe33e4cc984cf777c6db7f046e4adb7db10840e775f83e9a46e87172b"
EXPECTED_OUTCOMES_SHA256 = "98702fe5d220d171e77fd0276d5803ec851e46c6900445dd73ccb4cbfdbf194d"
EXPECTED_PROMPT_SHA256 = "767f6552a17ae179fed027ff1bc2f737d893a1f72859c090b1a5730979439647"
EXPECTED_ROSTER_SHA256 = "2d7027906c5da8fe137cca2f52773eb2a9b2f2864753884c715774d54df2df71"
EXPECTED_SCORER_MODULE = "aragora.evaluation.outcome_decision_quality"

EXPECTED_CONDITIONS = (
    "single_claude",
    "single_openai",
    "single_gemini",
    "aragora_team",
)
EXPECTED_PRIMARY_METRICS = (
    "binary_brier",
    "directional_accuracy",
    "crux_recall",
    "provenance_completeness",
    "receipt_verification_rate",
    "latency",
    "model_calls",
    "cost",
)
EXPECTED_HOLDOUT_INVALIDATION = (
    "corpus",
    "outcomes",
    "prompt",
    "roster",
    "scorer_contract",
    "implementation_sha",
)

EXPECTED_TRANCHES: tuple[dict[str, str], ...] = (
    {
        "corpus_path": "tranches/business-operations-1.corpus.json",
        "outcomes_path": "tranches/business-operations-1.outcomes.json",
        "corpus_sha256": "ac9676ff9715b724a436ac3f697e3599aba8416e061fe009088eea4360ad8bba",
        "outcomes_sha256": "ce281b2caab29f79b07d7784c3d19a08243ad914e1e384226dd17ff63f1452d4",
    },
    {
        "corpus_path": "tranches/business-operations-holdout-1.corpus.json",
        "outcomes_path": "tranches/business-operations-holdout-1.outcomes.json",
        "corpus_sha256": "2036afb2a909e1ffd16d5764fefd1fbccbeb298dd29924222d6034ec30d7e855",
        "outcomes_sha256": "05a6640cbee4878d0726d8dbbe92f6e9ebcb97a7eae7b0a03939cea2829358ff",
    },
    {
        "corpus_path": "tranches/policy-compliance-1.corpus.json",
        "outcomes_path": "tranches/policy-compliance-1.outcomes.json",
        "corpus_sha256": "17bce195c719c30c128b0ce86e906754c076e2c03da4a10f6421d9e80f57943b",
        "outcomes_sha256": "171cb032ca3047305ecb2086ad0913417d5a95fcfaec8dc228ba1b4f1dcf197b",
    },
    {
        "corpus_path": "tranches/policy-compliance-holdout-1.corpus.json",
        "outcomes_path": "tranches/policy-compliance-holdout-1.outcomes.json",
        "corpus_sha256": "318c209ccfc5d24b82f6083f284334fb89f752a9dfc6a8ab0ee68d6f5a5dbd4d",
        "outcomes_sha256": "247848041189c398c20a57547901aafff6d30d51fd98206e5e5a5e0c4689e8a1",
    },
    {
        "corpus_path": "tranches/science-forecasting-1.corpus.json",
        "outcomes_path": "tranches/science-forecasting-1.outcomes.json",
        "corpus_sha256": "2fc5525c8b7a23c5f57faed12967cb170be1e83c6afcba58ac45b43cefa18445",
        "outcomes_sha256": "061f6dc846889b01a22e3562b998d6b2b43f3bcf24efbe048f33b2089286de38",
    },
    {
        "corpus_path": "tranches/science-forecasting-holdout-1.corpus.json",
        "outcomes_path": "tranches/science-forecasting-holdout-1.outcomes.json",
        "corpus_sha256": "503a5cc94a26fcd38f8c0bb264413ac82b2ae7a3489da8d22e6d646254702ed6",
        "outcomes_sha256": "9d93b2f085b1c8586f67ee73538219bc1a98888ef0d4b3d11f196b9976b4e7d4",
    },
    {
        "corpus_path": "tranches/software-development-1.corpus.json",
        "outcomes_path": "tranches/software-development-1.outcomes.json",
        "corpus_sha256": "e9ec5a9a62b6d2d9a6cd9664989d3be6e45b7cc7cbfe0d57919a4238e0770b27",
        "outcomes_sha256": "cb3f1c0b7762b144142044a510f8c0cb489a15699ce6a7c6e262e2f35b17938d",
    },
    {
        "corpus_path": "tranches/software-engineering-holdout-1.corpus.json",
        "outcomes_path": "tranches/software-engineering-holdout-1.outcomes.json",
        "corpus_sha256": "97da356b5d70618c332e5fc52a0510996e28c6723aa00111206e663dc581295e",
        "outcomes_sha256": "1db3bd542e913b09c820af98a9ce4237f7dbfe8bbfed53d77f35fcf7f0bce292",
    },
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "benchmark_id",
    "revision",
    "frozen_at",
    "canonical_json",
    "conditions",
    "tranches",
    "aggregate",
    "prompt",
    "roster",
    "scorer",
    "budget",
    "holdout",
}
_TRANCHE_KEYS = {"corpus_path", "outcomes_path", "corpus_sha256", "outcomes_sha256"}
_AGGREGATE_KEYS = {"case_count", "corpus_sha256", "outcomes_sha256"}
_ARTIFACT_KEYS = {"path", "sha256"}
_SCORER_KEYS = {"contract_version", "module", "primary_metrics"}
_BUDGET_KEYS = {"paid_api_daily_usd", "infrastructure_retries_per_call"}
_HOLDOUT_KEYS = {"repetitions", "cases_per_domain", "invalidate_on_change"}


class DuplicateObjectKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


_JSON_LOAD_FAILED = object()


@dataclass(frozen=True)
class ManifestIssue:
    path: str
    code: str
    message: str


@dataclass
class ManifestValidationReport:
    manifest_sha256: str | None = None
    corpus_sha256: str | None = None
    outcomes_sha256: str | None = None
    case_count: int = 0
    outcome_count: int = 0
    issues: list[ManifestIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "manifest_sha256": self.manifest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "outcomes_sha256": self.outcomes_sha256,
            "case_count": self.case_count,
            "outcome_count": self.outcome_count,
            "issues": [asdict(issue) for issue in self.issues],
        }


def canonical_json_bytes(value: Any) -> bytes:
    """Return the benchmark's canonical JSON encoding."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateObjectKeyError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _issue(report: ManifestValidationReport, path: str, code: str, message: str) -> None:
    report.issues.append(ManifestIssue(path, code, message))


def _load_json(path: Path, report: ManifestValidationReport, issue_path: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except OSError as exc:
        _issue(report, issue_path, "read_error", str(exc))
    except UnicodeError as exc:
        _issue(report, issue_path, "invalid_utf8", str(exc))
    except (json.JSONDecodeError, DuplicateObjectKeyError, ValueError) as exc:
        _issue(report, issue_path, "invalid_json", str(exc))
    return _JSON_LOAD_FAILED


def _exact_keys(
    value: dict[str, Any], expected: set[str], path: str, report: ManifestValidationReport
) -> None:
    for key in sorted(expected - value.keys()):
        _issue(report, f"{path}.{key}", "missing_field", "field is required")
    for key in sorted(value.keys() - expected):
        _issue(report, f"{path}.{key}", "unknown_field", "field is not permitted")


def _safe_path(
    root: Path, relative: Any, report: ManifestValidationReport, path: str
) -> Path | None:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        _issue(report, path, "unsafe_artifact_path", "must be a non-empty relative path")
        return None
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        _issue(report, path, "unsafe_artifact_path", "path escapes the benchmark directory")
        return None
    return resolved


def _object(
    value: Any, path: str, keys: set[str], report: ManifestValidationReport
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _issue(report, path, "invalid_type", "must be an object")
        return None
    _exact_keys(value, keys, path, report)
    return value


def _validate_semantics(manifest: dict[str, Any], report: ManifestValidationReport) -> None:
    _exact_keys(manifest, _TOP_LEVEL_KEYS, "$", report)
    expected_scalars = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "revision": BENCHMARK_REVISION,
        "frozen_at": FROZEN_AT,
        "canonical_json": CANONICAL_JSON_CONVENTION,
    }
    for key, expected in expected_scalars.items():
        if manifest.get(key) != expected:
            _issue(report, f"$.{key}", "manifest_contract_mismatch", f"must equal {expected!r}")
    if manifest.get("conditions") != list(EXPECTED_CONDITIONS):
        _issue(
            report,
            "$.conditions",
            "condition_contract_mismatch",
            f"must equal {list(EXPECTED_CONDITIONS)!r}",
        )

    tranches = manifest.get("tranches")
    if not isinstance(tranches, list):
        _issue(report, "$.tranches", "invalid_type", "must be an array")
    else:
        for index, value in enumerate(tranches):
            if isinstance(value, dict):
                _exact_keys(value, _TRANCHE_KEYS, f"$.tranches[{index}]", report)
        if tranches != list(EXPECTED_TRANCHES):
            _issue(report, "$.tranches", "tranche_contract_mismatch", "exact tranche set required")

    aggregate = _object(manifest.get("aggregate"), "$.aggregate", _AGGREGATE_KEYS, report)
    if aggregate is not None and aggregate != {
        "case_count": 24,
        "corpus_sha256": EXPECTED_CORPUS_SHA256,
        "outcomes_sha256": EXPECTED_OUTCOMES_SHA256,
    }:
        _issue(report, "$.aggregate", "aggregate_contract_mismatch", "exact aggregate required")

    prompt = _object(manifest.get("prompt"), "$.prompt", _ARTIFACT_KEYS, report)
    if prompt is not None and prompt != {
        "path": "prompt.md",
        "sha256": EXPECTED_PROMPT_SHA256,
    }:
        _issue(report, "$.prompt", "prompt_contract_mismatch", "exact prompt binding required")
    roster = _object(manifest.get("roster"), "$.roster", _ARTIFACT_KEYS, report)
    if roster is not None and roster != {
        "path": "roster.json",
        "sha256": EXPECTED_ROSTER_SHA256,
    }:
        _issue(report, "$.roster", "roster_contract_mismatch", "exact roster binding required")

    scorer = _object(manifest.get("scorer"), "$.scorer", _SCORER_KEYS, report)
    if scorer is not None and scorer != {
        "contract_version": "outcome-decision-quality-scorer/1.0",
        "module": EXPECTED_SCORER_MODULE,
        "primary_metrics": list(EXPECTED_PRIMARY_METRICS),
    }:
        _issue(report, "$.scorer", "scorer_contract_mismatch", "exact scorer contract required")

    budget = _object(manifest.get("budget"), "$.budget", _BUDGET_KEYS, report)
    if budget is not None:
        paid = budget.get("paid_api_daily_usd")
        retries = budget.get("infrastructure_retries_per_call")
        if isinstance(paid, bool) or not isinstance(paid, (int, float)) or float(paid) != 25.0:
            _issue(report, "$.budget.paid_api_daily_usd", "budget_contract_mismatch", "must be 25")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries != 1:
            _issue(
                report,
                "$.budget.infrastructure_retries_per_call",
                "budget_contract_mismatch",
                "must be integer 1",
            )

    holdout = _object(manifest.get("holdout"), "$.holdout", _HOLDOUT_KEYS, report)
    if holdout is not None:
        repetitions = holdout.get("repetitions")
        cases_per_domain = holdout.get("cases_per_domain")
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions != 2:
            _issue(report, "$.holdout.repetitions", "holdout_contract_mismatch", "must be 2")
        if (
            isinstance(cases_per_domain, bool)
            or not isinstance(cases_per_domain, int)
            or cases_per_domain != 2
        ):
            _issue(
                report,
                "$.holdout.cases_per_domain",
                "holdout_contract_mismatch",
                "must be 2",
            )
        if holdout.get("invalidate_on_change") != list(EXPECTED_HOLDOUT_INVALIDATION):
            _issue(
                report,
                "$.holdout.invalidate_on_change",
                "holdout_contract_mismatch",
                "exact invalidation set required",
            )


def _verify_text_artifact(
    root: Path,
    spec: Any,
    expected_sha256: str,
    path: str,
    report: ManifestValidationReport,
) -> None:
    if not isinstance(spec, dict):
        return
    artifact = _safe_path(root, spec.get("path"), report, f"{path}.path")
    if artifact is None:
        return
    try:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    except OSError as exc:
        _issue(report, path, "read_error", str(exc))
        return
    if digest != expected_sha256:
        _issue(report, f"{path}.sha256", "artifact_hash_mismatch", digest)


def _verify_roster(root: Path, spec: Any, report: ManifestValidationReport) -> None:
    if not isinstance(spec, dict):
        return
    roster_path = _safe_path(root, spec.get("path"), report, "$.roster.path")
    if roster_path is None:
        return
    roster = _load_json(roster_path, report, "$.roster")
    if roster is _JSON_LOAD_FAILED:
        return
    if not isinstance(roster, dict):
        _issue(report, "$.roster", "invalid_type", "roster must be an object")
        return
    try:
        digest = canonical_sha256(roster)
    except (TypeError, ValueError) as exc:
        _issue(report, "$.roster", "non_canonical_json", str(exc))
        return
    if digest != EXPECTED_ROSTER_SHA256:
        _issue(report, "$.roster.sha256", "artifact_hash_mismatch", digest)


def _verify_scorer(manifest: dict[str, Any], report: ManifestValidationReport) -> None:
    spec = manifest.get("scorer")
    if not isinstance(spec, dict) or spec.get("module") != EXPECTED_SCORER_MODULE:
        return
    try:
        module = import_module(EXPECTED_SCORER_MODULE)
    except ImportError as exc:
        _issue(report, "$.scorer.module", "scorer_module_unavailable", str(exc))
        return
    if getattr(module, "SCORER_CONTRACT_VERSION", None) != spec.get("contract_version"):
        _issue(
            report,
            "$.scorer.contract_version",
            "scorer_runtime_mismatch",
            "runtime scorer contract version does not match the manifest",
        )
    if tuple(getattr(module, "PRIMARY_METRICS", ())) != tuple(spec.get("primary_metrics", ())):
        _issue(
            report,
            "$.scorer.primary_metrics",
            "scorer_runtime_mismatch",
            "runtime scorer metrics do not match the manifest",
        )


def _collect_records(
    document: Any,
    list_key: str,
    id_key: str,
    path: str,
    seen: set[str],
    report: ManifestValidationReport,
) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get(list_key), list):
        _issue(report, path, "invalid_tranche_shape", f"must contain {list_key!r} array")
        return []
    records: list[dict[str, Any]] = []
    for index, value in enumerate(document[list_key]):
        record_path = f"{path}.{list_key}[{index}]"
        if not isinstance(value, dict) or not isinstance(value.get(id_key), str):
            _issue(report, record_path, "invalid_record_identity", f"{id_key!r} required")
            continue
        identity = value[id_key]
        if identity in seen:
            _issue(report, f"{record_path}.{id_key}", "duplicate_record_identity", identity)
            continue
        seen.add(identity)
        records.append(value)
    return records


def _verify_tranches(
    root: Path, manifest: dict[str, Any], report: ManifestValidationReport
) -> None:
    if manifest.get("tranches") != list(EXPECTED_TRANCHES):
        return
    cases: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    outcome_ids: set[str] = set()
    for index, spec in enumerate(EXPECTED_TRANCHES):
        corpus_path = _safe_path(root, spec["corpus_path"], report, f"$.tranches[{index}].corpus")
        outcomes_path = _safe_path(
            root, spec["outcomes_path"], report, f"$.tranches[{index}].outcomes"
        )
        if corpus_path is None or outcomes_path is None:
            continue
        corpus = _load_json(corpus_path, report, f"$.tranches[{index}].corpus")
        sidecar = _load_json(outcomes_path, report, f"$.tranches[{index}].outcomes")
        for value, expected, path in (
            (corpus, spec["corpus_sha256"], f"$.tranches[{index}].corpus_sha256"),
            (sidecar, spec["outcomes_sha256"], f"$.tranches[{index}].outcomes_sha256"),
        ):
            if value is _JSON_LOAD_FAILED:
                continue
            try:
                actual = canonical_sha256(value)
            except (TypeError, ValueError) as exc:
                _issue(report, path, "non_canonical_json", str(exc))
                continue
            if actual != expected:
                _issue(report, path, "tranche_hash_mismatch", actual)
        if corpus is not _JSON_LOAD_FAILED:
            cases.extend(
                _collect_records(
                    corpus, "cases", "case_id", f"$.tranches[{index}]", case_ids, report
                )
            )
        if sidecar is not _JSON_LOAD_FAILED:
            outcomes.extend(
                _collect_records(
                    sidecar,
                    "outcomes",
                    "case_id",
                    f"$.tranches[{index}]",
                    outcome_ids,
                    report,
                )
            )

    report.case_count = len(cases)
    report.outcome_count = len(outcomes)
    if report.case_count != 24:
        _issue(report, "$.aggregate.case_count", "aggregate_mismatch", str(report.case_count))
    if case_ids != outcome_ids:
        _issue(report, "$.aggregate", "case_outcome_mismatch", "case and outcome IDs must match")
    if report.issues:
        return
    corpus = {
        "schema_version": "decision-quality-corpus/1.0",
        "benchmark_id": BENCHMARK_ID,
        "revision": BENCHMARK_REVISION,
        "frozen_at": FROZEN_AT,
        "cases": sorted(cases, key=lambda item: item["case_id"]),
    }
    report.corpus_sha256 = canonical_sha256(corpus)
    outcome_sidecar = {
        "schema_version": "decision-quality-outcomes/1.0",
        "benchmark_id": BENCHMARK_ID,
        "corpus_sha256": report.corpus_sha256,
        "outcomes": sorted(outcomes, key=lambda item: item["case_id"]),
    }
    report.outcomes_sha256 = canonical_sha256(outcome_sidecar)
    if report.corpus_sha256 != EXPECTED_CORPUS_SHA256:
        _issue(report, "$.aggregate.corpus_sha256", "aggregate_mismatch", report.corpus_sha256)
    if report.outcomes_sha256 != EXPECTED_OUTCOMES_SHA256:
        _issue(
            report,
            "$.aggregate.outcomes_sha256",
            "aggregate_mismatch",
            report.outcomes_sha256,
        )


def validate_manifest(manifest_path: Path) -> ManifestValidationReport:
    """Validate the exact frozen manifest and every artifact it binds."""
    report = ManifestValidationReport()
    manifest = _load_json(manifest_path, report, "$")
    if manifest is _JSON_LOAD_FAILED:
        return report
    if not isinstance(manifest, dict):
        _issue(report, "$", "invalid_type", "manifest must be an object")
        return report
    try:
        report.manifest_sha256 = canonical_sha256(manifest)
    except (TypeError, ValueError) as exc:
        _issue(report, "$", "non_canonical_json", str(exc))
        return report
    if report.manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        _issue(report, "$", "manifest_hash_mismatch", report.manifest_sha256)
    _validate_semantics(manifest, report)
    _verify_scorer(manifest, report)

    root = manifest_path.resolve().parent
    _verify_text_artifact(root, manifest.get("prompt"), EXPECTED_PROMPT_SHA256, "$.prompt", report)
    _verify_roster(root, manifest.get("roster"), report)
    _verify_tranches(root, manifest, report)
    return report


__all__ = [
    "BENCHMARK_ID",
    "BENCHMARK_REVISION",
    "CANONICAL_JSON_CONVENTION",
    "EXPECTED_CONDITIONS",
    "EXPECTED_CORPUS_SHA256",
    "EXPECTED_HOLDOUT_INVALIDATION",
    "EXPECTED_MANIFEST_SHA256",
    "EXPECTED_OUTCOMES_SHA256",
    "EXPECTED_PRIMARY_METRICS",
    "EXPECTED_SCORER_MODULE",
    "EXPECTED_PROMPT_SHA256",
    "EXPECTED_ROSTER_SHA256",
    "EXPECTED_TRANCHES",
    "FROZEN_AT",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestIssue",
    "ManifestValidationReport",
    "canonical_json_bytes",
    "canonical_sha256",
    "validate_manifest",
]
