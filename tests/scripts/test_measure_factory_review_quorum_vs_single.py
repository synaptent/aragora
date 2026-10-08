"""Tests for the offline quorum-vs-single benchmark measurement."""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import measure_factory_review_quorum_vs_single as measure_script  # noqa: E402


ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "docs/benchmarks"


def _artifact(name: str) -> dict[str, Any]:
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def _inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        _artifact("factory_review_benchmark_manifest.json"),
        _artifact("factory_review_quorum_vs_single_evidence.json"),
        _artifact("factory_review_quorum_vs_single_live_collection.json"),
    )


def _measure(
    tmp_path: Path,
    monkeypatch: object,
    inputs: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    monkeypatch.setattr(measure_script, "REPO_ROOT", tmp_path.parent)
    monkeypatch.setattr(measure_script, "DEFAULT_MANIFEST", tmp_path.parent / "manifest.json")
    monkeypatch.setattr(measure_script, "DEFAULT_LIVE_COLLECTION", tmp_path.parent / "live.json")
    manifest, evidence, live = inputs or _inputs()
    return measure_script.measure(
        manifest,
        evidence,
        live,
        baseline_provider="mistral-api",
        outcome_dir=tmp_path,
    )


def test_measure_records_named_single_miss_and_emits_collect_outcome(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    result = _measure(tmp_path, monkeypatch)

    case = result["cases"][0]
    assert case["baseline"]["missed_golden_ids"] == ["2743651586"]
    assert case["quorum"]["distinct_model_families"] == 2
    assert case["quorum"]["caught_beyond_baseline_golden_ids"] == ["2743651586"]
    assert result["summary"]["single_model_miss_case_count"] == 2

    fixture = json.loads(
        (tmp_path / "droid-sentry-pr-6.collect-outcome.json").read_text(encoding="utf-8")
    )
    assert fixture["mode"] == "collect_evidence"
    assert fixture["head_sha"] == "cb7212e11dbdbc1813237ad129c7bc108f944e3d"
    assert fixture["counting_families"] == ["grok", "mistral"]
    assert "golden_comment_id=2743651586" in fixture["items"][0]["body"]
    assert "live reviewer output collection canonical sha256:" in fixture["action_reason"]
    assert result["adjudication_scope"].startswith("manual golden_comment_id mappings only")
    assert result["family_aliases"] == {"grok": "xai"}
    assert result["quorum_families"] == ["mistral", "xai"]
    assert case["models"][0]["provider"] == "grok"
    assert case["models"][0]["family"] == "xai"


def test_manifest_rejects_moving_validation_url() -> None:
    manifest, _, _ = _inputs()
    manifest["smoke_cases"][0]["validation_url"] = manifest["smoke_cases"][0][
        "validation_url"
    ].replace(manifest["source"]["benchmark_head_sha"], "main")

    try:
        measure_script._manifest_cases(manifest)
    except ValueError as exc:
        assert "not pinned" in str(exc)
    else:
        raise AssertionError("moving validation URL must fail closed")


def test_manifest_rejects_sha_outside_raw_github_ref_segment() -> None:
    manifest, _, _ = _inputs()
    benchmark_head_sha = manifest["source"]["benchmark_head_sha"]
    validation_url = manifest["smoke_cases"][0]["validation_url"]
    manifest["smoke_cases"][0]["validation_url"] = (
        validation_url.replace(f"/{benchmark_head_sha}/", "/main/")
        + f"?expected_ref={benchmark_head_sha}"
    )

    try:
        measure_script._manifest_cases(manifest)
    except ValueError as exc:
        assert "not pinned" in str(exc)
    else:
        raise AssertionError("SHA outside the raw GitHub ref segment must fail closed")


def test_manifest_rejects_missing_benchmark_head_sha() -> None:
    manifest, _, _ = _inputs()
    manifest["source"]["benchmark_head_sha"] = ""

    try:
        measure_script._manifest_cases(manifest)
    except ValueError as exc:
        assert "benchmark_head_sha must be non-empty" in str(exc)
    else:
        raise AssertionError("empty benchmark_head_sha must fail closed")


def test_validate_pinned_pr_state_accepts_matching_base_and_head(monkeypatch: object) -> None:
    target = SimpleNamespace(head_sha="head-sha")
    case = {"case_id": "case-1", "base_sha": "base-sha", "head_sha": "head-sha"}
    monkeypatch.setattr(measure_script, "_fetch_pr_base_sha", lambda _: "base-sha")

    measure_script._validate_pinned_pr_state(target, case)


def test_collect_rejects_base_drift_before_fetching_diff(monkeypatch: object) -> None:
    target = SimpleNamespace(head_sha="head-sha")
    case = {
        "case_id": "case-1",
        "repo": "owner/repo",
        "pr_url": "https://github.com/owner/repo/pull/1",
        "base_sha": "expected-base",
        "head_sha": "head-sha",
    }
    monkeypatch.setattr(measure_script, "_fetch_pr_target", lambda *args, **kwargs: target)
    monkeypatch.setattr(measure_script, "_fetch_pr_base_sha", lambda _: "moved-base")

    def unexpected_diff_fetch(_: object) -> str:
        raise AssertionError("diff must not be fetched after base drift")

    monkeypatch.setattr(measure_script, "_fetch_pr_diff", unexpected_diff_fetch)

    try:
        asyncio.run(measure_script._collect_one("grok", case))
    except ValueError as exc:
        assert "PR base drifted" in str(exc)
    else:
        raise AssertionError("base drift must fail closed")


def test_measure_rejects_same_family_quorum(tmp_path: Path, monkeypatch: object) -> None:
    manifest, evidence, live_collection = deepcopy(_inputs())
    evidence["cases"][0]["model_results"][1]["family"] = "grok"
    live_collection["cases"][0]["model_results"][1]["family"] = "grok"

    try:
        _measure(tmp_path, monkeypatch, (manifest, evidence, live_collection))
    except ValueError as exc:
        assert "fewer than two distinct families" in str(exc)
    else:
        raise AssertionError("same-family reviewers must not count as a quorum")


def test_measure_uses_live_text_instead_of_rewritten_adjudication(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    manifest, evidence, live_collection = deepcopy(_inputs())
    evidence["cases"][0]["model_results"][0]["findings"][0]["body"] = "rewritten"

    result = _measure(tmp_path, monkeypatch, (manifest, evidence, live_collection))

    assert result["cases"][0]["models"][0]["finding_set"][0]["body"].startswith(
        "In organization_auditlogs.py"
    )


def _main_measure_args(*, output: Path, outcome_dir: Path) -> list[str]:
    return [
        "measure",
        "--manifest",
        str(ARTIFACT_DIR / "factory_review_benchmark_manifest.json"),
        "--evidence",
        str(ARTIFACT_DIR / "factory_review_quorum_vs_single_evidence.json"),
        "--live-collection",
        str(ARTIFACT_DIR / "factory_review_quorum_vs_single_live_collection.json"),
        "--outcome-dir",
        str(outcome_dir),
        "--output",
        str(output),
    ]


def _configure_fake_repo(tmp_path: Path, monkeypatch: object) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(measure_script, "REPO_ROOT", repo_root)
    monkeypatch.setattr(measure_script, "DEFAULT_MANIFEST", repo_root / "manifest.json")
    monkeypatch.setattr(measure_script, "DEFAULT_LIVE_COLLECTION", repo_root / "live.json")
    return repo_root


def test_external_output_requires_explicit_opt_in(tmp_path: Path, monkeypatch: object) -> None:
    _configure_fake_repo(tmp_path, monkeypatch)
    external_dir = tmp_path / "external"
    output = external_dir / "results.json"

    assert measure_script.main(_main_measure_args(output=output, outcome_dir=external_dir)) == 2
    assert not output.exists()


def test_external_output_succeeds_with_explicit_opt_in(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    _configure_fake_repo(tmp_path, monkeypatch)
    external_dir = tmp_path / "external"
    output = external_dir / "results.json"
    args = _main_measure_args(output=output, outcome_dir=external_dir)

    assert measure_script.main([*args, "--allow-external-output"]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["cases"][0]["collect_outcome_fixture"] == str(
        (external_dir / "droid-sentry-pr-6.collect-outcome.json").resolve()
    )
    assert result["quorum_families"] == ["mistral", "xai"]


def test_default_in_tree_output_behavior_is_unchanged(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    repo_root = _configure_fake_repo(tmp_path, monkeypatch)
    outcome_dir = repo_root / "fixtures"
    output = repo_root / "results.json"

    assert measure_script.main(_main_measure_args(output=output, outcome_dir=outcome_dir)) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["cases"][0]["collect_outcome_fixture"] == (
        "fixtures/droid-sentry-pr-6.collect-outcome.json"
    )


def test_missing_input_still_fails_closed(tmp_path: Path, monkeypatch: object) -> None:
    repo_root = _configure_fake_repo(tmp_path, monkeypatch)
    output = repo_root / "results.json"
    args = _main_measure_args(output=output, outcome_dir=repo_root / "fixtures")
    missing_manifest_index = args.index("--manifest") + 1
    args[missing_manifest_index] = str(tmp_path / "missing-manifest.json")

    assert measure_script.main(args) == 2
    assert not output.exists()
