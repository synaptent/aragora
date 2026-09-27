"""Focused tests for SHA-bound repository metrics."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath

import pytest

from scripts import repository_metrics as metrics
from scripts import regenerate_metrics


REPO_ROOT = Path(__file__).resolve().parents[2]
REGENERATE_SCRIPT = REPO_ROOT / "scripts" / "regenerate_metrics.py"


BASE_DEFINITION = metrics.MetricDefinition(
    "metric",
    "metric",
    "count",
    ".",
    "python_surface",
    "inventory",
    "link_only",
    "",
    "report_only",
    "none",
    "documentation only",
)


def _definition(key: str, **changes: str) -> metrics.MetricDefinition:
    return replace(BASE_DEFINITION, key=key, label=key, **changes)


def _metric(key: str, collector: str, **changes: str) -> str:
    definition = _definition(key, collector=collector, **changes)
    return (
        "[[metrics]]\n"
        + "\n".join(f"{field} = {json.dumps(value)}" for field, value in asdict(definition).items())
        + "\n"
    )


def _catalog(path: Path, *entries: str) -> Path:
    path.write_text("schema_version = 1\n" + "".join(entries), encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "metrics@example.test")
    _git(repo, "config", "user.name", "Metrics Test")
    (repo / "aragora").mkdir()
    (repo / "aragora" / "one.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo


def _snapshot(
    definition: metrics.MetricDefinition, value: object, sha: str
) -> metrics.RepositorySnapshot:
    return metrics.RepositorySnapshot(
        git_sha=sha,
        generated_at="2026-07-14T00:00:00+00:00",
        catalog_digest="digest",
        metrics=[{**asdict(definition), "value": value}],
        errors=[],
    )


def test_live_catalog_is_valid_and_deterministically_ordered() -> None:
    definitions, digest = metrics.load_catalog()
    assert [definition.key for definition in definitions] == sorted(
        definition.key for definition in definitions
    )
    assert len(definitions) == 20
    assert len(digest) == 64


@pytest.mark.parametrize(
    "body,match",
    [
        ("schema_version = 1\n[[metrics]]\nkey = 'x'\n", "missing fields"),
        (
            _metric("x", "shell_command"),
            "unsupported collector",
        ),
        (
            _metric("x", "python_surface", display="lower_bound", display_value="many"),
            "lower bound must be an integer",
        ),
    ],
)
def test_catalog_rejects_malformed_or_unregistered_collectors(
    tmp_path: Path, body: str, match: str
) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.write_text(body if body.startswith("schema") else "schema_version = 1\n" + body)
    with pytest.raises(metrics.CatalogError, match=match):
        metrics.load_catalog(catalog)


def test_ref_snapshots_are_isolated_and_ref_specific(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    catalog = _catalog(tmp_path / "catalog.toml", _metric("python_files", "python_surface"))
    base_sha = _git(repo, "rev-parse", "HEAD")

    (repo / "aragora" / "one.py").write_text("value = 999\n" * 20, encoding="utf-8")
    (repo / "aragora" / "untracked.py").write_text("value = 2\n", encoding="utf-8")
    first = metrics.collect_ref_snapshot(repo, "HEAD", catalog, "2026-07-14T00:00:00Z")

    assert first.git_sha == base_sha
    assert first.values["python_files"] == 1
    assert not first.errors

    (repo / "aragora" / "one.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "aragora" / "untracked.py").unlink()
    (repo / "aragora" / "two.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "second")
    after = metrics.collect_ref_snapshot(repo, "HEAD", catalog)

    assert after.values["python_files"] == 2
    assert first.git_sha != after.git_sha


def test_ref_snapshot_uses_resolved_sha_if_branch_moves(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    catalog = _catalog(tmp_path / "catalog.toml", _metric("python_files", "python_surface"))
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "moving", base_sha)

    (repo / "aragora" / "two.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "advance branch target")
    advanced_sha = _git(repo, "rev-parse", "HEAD")
    original_run_git = metrics._run_git
    moved = False

    def move_branch_after_resolution(repo_root: Path, *args: str) -> bytes:
        nonlocal moved
        result = original_run_git(repo_root, *args)
        if not moved and args[0] == "rev-parse":
            _git(repo, "branch", "-f", "moving", advanced_sha)
            moved = True
        return result

    monkeypatch.setattr(metrics, "_run_git", move_branch_after_resolution)
    snapshot = metrics.collect_ref_snapshot(repo, "moving", catalog)

    assert snapshot.git_sha == base_sha
    assert snapshot.values["python_files"] == 1
    assert _git(repo, "rev-parse", "moving") == advanced_sha


def test_workflow_surface_counts_only_direct_yaml_files(tmp_path: Path) -> None:
    view = metrics.RepositoryView(
        root=tmp_path,
        tracked_paths=tuple(
            PurePosixPath(path)
            for path in (
                ".github/workflows/lint.yml",
                ".github/workflows/release.yaml",
                ".github/workflows/templates/reusable.yml",
                ".github/workflows/README.md",
            )
        ),
    )

    assert metrics._workflow_surface(view) == {"ci_workflows": 2}


def test_snapshot_cli_writes_exact_ref_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "metrics.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REGENERATE_SCRIPT),
            "snapshot",
            "--ref",
            "HEAD",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["git_sha"] == _git(REPO_ROOT, "rev-parse", "HEAD")
    assert payload["status"] == "complete"
    assert payload["errors"] == []
    assert len(payload["catalog_digest"]) == 64


def test_snapshot_cli_failure_writes_diagnostic_json(tmp_path: Path) -> None:
    output = tmp_path / "missing-ref.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REGENERATE_SCRIPT),
            "snapshot",
            "--ref",
            "refs/heads/does-not-exist",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert payload["errors"][0]["collector"] == "snapshot"


def test_legacy_cli_modes_remain_available(tmp_path: Path, monkeypatch, capsys) -> None:
    snapshot = regenerate_metrics.MetricsSnapshot(
        generated_at="2026-07-17T00:00:00Z",
        git_sha="deadbeef",
        metrics=[],
    )
    monkeypatch.setattr(regenerate_metrics, "gather_metrics", lambda: snapshot)

    assert regenerate_metrics.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["git_sha"] == "deadbeef"

    monkeypatch.setattr(regenerate_metrics, "check_drift", lambda _snapshot: (False, []))
    assert regenerate_metrics.main(["--check"]) == 0

    output = tmp_path / "METRICS.md"
    monkeypatch.setattr(regenerate_metrics, "METRICS_DOC", output)
    assert regenerate_metrics.main([]) == 0
    assert output.exists()


def test_collection_reports_every_failed_collector(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "docs" / "api").mkdir(parents=True)
    (repo / "docs" / "api" / "openapi.json").write_text("not json", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "broken inputs")
    catalog = _catalog(
        tmp_path / "catalog.toml",
        _metric(
            "openapi_paths",
            "openapi_surface",
            kind="contract",
            comparison="delegated",
            policy="validate_openapi_routes",
        ),
        _metric(
            "project_version",
            "project_claims",
            kind="claim",
            display="exact",
            display_value="2.9.0",
            comparison="exact_claim",
            policy="catalog_claim",
        ),
    )

    snapshot = metrics.collect_ref_snapshot(repo, "HEAD", catalog)

    assert snapshot.status == "partial"
    assert {error["collector"] for error in snapshot.errors} == {
        "openapi_surface",
        "project_claims",
    }


def test_comparison_policies() -> None:
    def check(
        definition: metrics.MetricDefinition,
        before: object,
        after: object,
        result: str,
        code: int,
    ) -> None:
        comparison = metrics.compare_snapshots(
            _snapshot(definition, before, "a"), _snapshot(definition, after, "b"), [definition]
        )
        assert metrics.exit_code(comparison) == code
        metric_results = comparison["metrics"]
        assert isinstance(metric_results, list)
        assert isinstance(metric_results[0], dict)
        assert metric_results[0]["result"] == result

    check(_definition("files"), 10, 11, "report", 0)
    check(
        _definition(
            "debt", kind="ratchet", comparison="non_increasing", policy="mypy_baseline_ratchet"
        ),
        10,
        11,
        "violation",
        1,
    )
    check(
        _definition(
            "version",
            kind="claim",
            display="exact",
            display_value="2.9.0",
            comparison="exact_claim",
            policy="catalog_claim",
        ),
        "2.9.0",
        "3.0.0",
        "violation",
        1,
    )
    check(
        _definition(
            "routes", kind="contract", comparison="delegated", policy="validate_openapi_routes"
        ),
        10,
        9,
        "delegated",
        0,
    )
