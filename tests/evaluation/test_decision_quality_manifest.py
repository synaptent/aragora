from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

import aragora.evaluation.decision_quality_manifest as manifest_module
from aragora.evaluation.decision_quality_manifest import (
    EXPECTED_CORPUS_SHA256,
    EXPECTED_MANIFEST_SHA256,
    EXPECTED_OUTCOMES_SHA256,
    canonical_sha256,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "docs/benchmarks/decision_quality"
MANIFEST = BENCHMARK_DIR / "benchmark-manifest.json"


def _copy_contract(tmp_path: Path) -> Path:
    destination = tmp_path / "decision_quality"
    shutil.copytree(BENCHMARK_DIR, destination)
    return destination / "benchmark-manifest.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}  # type: ignore[attr-defined]


def test_live_manifest_binds_all_merged_tranches() -> None:
    report = validate_manifest(MANIFEST)

    assert report.ok, report.to_dict()
    assert report.manifest_sha256 == EXPECTED_MANIFEST_SHA256
    assert report.corpus_sha256 == EXPECTED_CORPUS_SHA256
    assert report.outcomes_sha256 == EXPECTED_OUTCOMES_SHA256
    assert report.case_count == 24
    assert report.outcome_count == 24


def _scorer_module(manifest: dict[str, Any]) -> None:
    manifest["scorer"]["module"] = "other.module"


def _primary_metrics(manifest: dict[str, Any]) -> None:
    manifest["scorer"]["primary_metrics"] = ["binary_brier"]


def _holdout_cases(manifest: dict[str, Any]) -> None:
    manifest["holdout"]["cases_per_domain"] = 3


def _holdout_invalidation(manifest: dict[str, Any]) -> None:
    manifest["holdout"]["invalidate_on_change"] = ["corpus"]


def _holdout_bool(manifest: dict[str, Any]) -> None:
    manifest["holdout"]["repetitions"] = True


def _retry_bool(manifest: dict[str, Any]) -> None:
    manifest["budget"]["infrastructure_retries_per_call"] = True


def _paid_bool(manifest: dict[str, Any]) -> None:
    manifest["budget"]["paid_api_daily_usd"] = True


@pytest.mark.parametrize(
    ("mutate", "issue_code"),
    [
        (_scorer_module, "scorer_contract_mismatch"),
        (_primary_metrics, "scorer_contract_mismatch"),
        (_holdout_cases, "holdout_contract_mismatch"),
        (_holdout_invalidation, "holdout_contract_mismatch"),
        (_holdout_bool, "holdout_contract_mismatch"),
        (_retry_bool, "budget_contract_mismatch"),
        (_paid_bool, "budget_contract_mismatch"),
    ],
)
def test_manifest_rejects_frozen_semantic_drift(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    issue_code: str,
) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest = _read_manifest(manifest_path)
    mutate(manifest)
    _write_manifest(manifest_path, manifest)

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "manifest_hash_mismatch" in _issue_codes(report)
    assert issue_code in _issue_codes(report)


def test_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest = _read_manifest(manifest_path)
    manifest["future_override"] = True
    manifest["holdout"]["future_override"] = True
    _write_manifest(manifest_path, manifest)

    report = validate_manifest(manifest_path)

    unknown_paths = {issue.path for issue in report.issues if issue.code == "unknown_field"}
    assert "$.future_override" in unknown_paths
    assert "$.holdout.future_override" in unknown_paths


def test_manifest_rejects_prompt_drift(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    prompt_path = manifest_path.parent / "prompt.md"
    prompt_path.write_text(
        prompt_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8"
    )

    report = validate_manifest(manifest_path)

    assert "artifact_hash_mismatch" in _issue_codes(report)


def test_manifest_rejects_path_escape(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest = _read_manifest(manifest_path)
    manifest["prompt"]["path"] = "../prompt.md"
    _write_manifest(manifest_path, manifest)

    report = validate_manifest(manifest_path)

    assert "unsafe_artifact_path" in _issue_codes(report)


def test_manifest_rejects_coordinated_roster_and_digest_drift(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    roster_path = manifest_path.parent / "roster.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    roster["conditions"]["single_openai"]["members"][0]["requested_model"] = "other/model"
    roster_path.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")
    manifest = _read_manifest(manifest_path)
    manifest["roster"]["sha256"] = canonical_sha256(roster)
    _write_manifest(manifest_path, manifest)

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "manifest_hash_mismatch" in _issue_codes(report)
    assert "roster_contract_mismatch" in _issue_codes(report)
    assert "artifact_hash_mismatch" in _issue_codes(report)


def test_manifest_rejects_coordinated_tranche_and_digest_drift(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest = _read_manifest(manifest_path)
    corpus_path = manifest_path.parent / manifest["tranches"][0]["corpus_path"]
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["cases"][0]["title"] = "drifted title"
    corpus_path.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    manifest["tranches"][0]["corpus_sha256"] = canonical_sha256(corpus)
    _write_manifest(manifest_path, manifest)

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "manifest_hash_mismatch" in _issue_codes(report)
    assert "tranche_contract_mismatch" in _issue_codes(report)


def test_manifest_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest_path.write_text('{"schema_version":"one","schema_version":"two"}\n', encoding="utf-8")

    report = validate_manifest(manifest_path)

    assert "invalid_json" in _issue_codes(report)


def test_manifest_rejects_nonfinite_roster_values(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    roster_path = manifest_path.parent / "roster.json"
    roster_path.write_text('{"conditions": NaN}\n', encoding="utf-8")

    report = validate_manifest(manifest_path)

    assert "invalid_json" in _issue_codes(report)


def test_manifest_rejects_json_null_document(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    manifest_path.write_text("null\n", encoding="utf-8")

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "invalid_type" in _issue_codes(report)


def test_manifest_rejects_json_null_roster(tmp_path: Path) -> None:
    manifest_path = _copy_contract(tmp_path)
    (manifest_path.parent / "roster.json").write_text("null\n", encoding="utf-8")

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "invalid_type" in _issue_codes(report)


def test_manifest_fails_closed_when_scorer_module_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _copy_contract(tmp_path)

    def unavailable(_name: str) -> object:
        raise ModuleNotFoundError("scorer unavailable")

    monkeypatch.setattr(manifest_module, "import_module", unavailable)

    report = validate_manifest(manifest_path)

    assert not report.ok
    assert "scorer_module_unavailable" in _issue_codes(report)
