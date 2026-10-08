from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.ci import check_boundary_edges as checker


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATTERN = (
    r"^(?:\.pre-commit-config\.yaml|aragora/.*|aragora-verify/src/aragora_verify/.*|"
    r"scripts/baselines/boundary2_edges_baseline\.json|"
    r"scripts/ci/boundary_maps/receipts_verifier\.json|"
    r"scripts/ci/check_boundary_edges\.py)$"
)


def _write_repo(tmp_path: Path, source: str = "") -> tuple[Path, Path]:
    files = {
        "aragora/__init__.py": "",
        "aragora/core/__init__.py": "",
        "aragora/gauntlet/__init__.py": "",
        "aragora/gauntlet/odr_export.py": "",
        "aragora/gauntlet/runner.py": "",
        "aragora/receipts/__init__.py": source,
        "aragora-verify/src/aragora_verify/__init__.py": "",
        "scripts/ci/check_boundary_edges.py": "",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    map_path = tmp_path / checker.MAP_PATH
    map_path.parent.mkdir(parents=True, exist_ok=True)
    policy = {
        "schema_version": 1,
        "boundary": {"id": 2, "name": "receipts+verifier", "provenance": "test"},
        "module_roots": [
            {"path": "aragora", "package": "aragora"},
            {"path": "aragora-verify/src/aragora_verify", "package": "aragora_verify"},
        ],
        "sources": ["aragora/receipts", "aragora-verify/src/aragora_verify"],
        "allowed_internal_prefixes": ["aragora.core", "aragora.gauntlet.odr_export"],
        "hook": {"id": "boundary2-edges", "files": HOOK_PATTERN},
    }
    map_path.write_text(json.dumps(policy), encoding="utf-8")
    baseline_path = tmp_path / checker.BASELINE_PATH
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    _write_baseline(baseline_path, [])
    _write_hook(tmp_path)
    return map_path, baseline_path


def _write_baseline(path: Path, violations: list[str], frozen_ref: str = "f" * 40) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "boundary": {"id": 2, "name": "receipts+verifier"},
                "map": checker.MAP_PATH.as_posix(),
                "frozen_from_ref": frozen_ref,
                "violations": violations,
            }
        ),
        encoding="utf-8",
    )


def _write_hook(
    tmp_path: Path, *, files: str = HOOK_PATTERN, stages: str = "[pre-commit, pre-push]"
) -> None:
    (tmp_path / checker.HOOK_PATH).write_text(
        "# Install: pre-commit install --hook-type pre-commit --hook-type pre-push\n"
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: boundary2-edges\n"
        "        entry: python3 scripts/ci/check_boundary_edges.py\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        f"        files: {files}\n"
        f"        stages: {stages}\n",
        encoding="utf-8",
    )


def _run(tmp_path: Path, map_path: Path, baseline_path: Path) -> int:
    return checker.main(
        ["--repo-root", str(tmp_path), "--map", str(map_path), "--baseline", str(baseline_path)]
    )


def test_resolves_absolute_relative_and_offline_imports(tmp_path: Path) -> None:
    source = "\n".join(
        [
            "from aragora import core",
            "from aragora.gauntlet import runner",
            "from ..gauntlet import odr_export",
        ]
    )
    map_path, _ = _write_repo(tmp_path, source)
    verifier = tmp_path / "aragora-verify/src/aragora_verify/verifier.py"
    verifier.write_text("import aragora.core\n", encoding="utf-8")
    policy = checker.load_policy(tmp_path, map_path)
    assert checker.scan(tmp_path, policy) == {
        "import aragora.receipts -> aragora.gauntlet.runner",
        "offline aragora_verify.verifier -> aragora.core",
    }


def test_dotted_child_is_not_absorbed_by_baselined_parent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    map_path, baseline_path = _write_repo(tmp_path, "from aragora.gauntlet import runner\n")
    _write_baseline(baseline_path, ["import aragora.receipts -> aragora.gauntlet"])
    assert _run(tmp_path, map_path, baseline_path) == 1
    output = capsys.readouterr().out
    assert "NEW: import aragora.receipts -> aragora.gauntlet.runner" in output
    assert "STALE: import aragora.receipts -> aragora.gauntlet" in output


def test_stale_baseline_entry_fails(tmp_path: Path) -> None:
    map_path, baseline_path = _write_repo(tmp_path)
    _write_baseline(baseline_path, ["import aragora.receipts -> aragora.debate"])
    assert _run(tmp_path, map_path, baseline_path) == 1


def test_unreachable_frozen_ref_is_informational(tmp_path: Path) -> None:
    map_path, baseline_path = _write_repo(tmp_path)
    _write_baseline(baseline_path, [], frozen_ref="0" * 40)
    assert _run(tmp_path, map_path, baseline_path) == 0


def test_malformed_python_fails_closed(tmp_path: Path) -> None:
    map_path, baseline_path = _write_repo(tmp_path, "from [\n")
    assert _run(tmp_path, map_path, baseline_path) == 2


def test_duplicate_map_entry_is_rejected(tmp_path: Path) -> None:
    map_path, _ = _write_repo(tmp_path)
    data = json.loads(map_path.read_text())
    data["sources"].append(data["sources"][0])
    map_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(checker.PolicyError, match="duplicate"):
        checker.load_policy(tmp_path, map_path)


def test_new_map_root_without_hook_coverage_is_rejected(tmp_path: Path) -> None:
    map_path, _ = _write_repo(tmp_path)
    extra = tmp_path / "other_boundary"
    extra.mkdir()
    (extra / "__init__.py").write_text("", encoding="utf-8")
    data = json.loads(map_path.read_text())
    data["module_roots"].append({"path": "other_boundary", "package": "other_boundary"})
    data["sources"].append("other_boundary")
    map_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(checker.PolicyError, match="hook.files does not cover"):
        checker.load_policy(tmp_path, map_path)


@pytest.mark.parametrize(
    ("files", "stages"),
    [(r"^aragora/.*$", "[pre-commit, pre-push]"), (HOOK_PATTERN, "[pre-push]")],
)
def test_hook_drift_fails_closed(tmp_path: Path, files: str, stages: str) -> None:
    map_path, _ = _write_repo(tmp_path)
    _write_hook(tmp_path, files=files, stages=stages)
    policy = checker.load_policy(tmp_path, map_path)
    with pytest.raises(checker.PolicyError, match="hook drift"):
        checker.validate_hook(tmp_path, policy)


@pytest.mark.parametrize(
    "violations",
    [
        ["z", "a"],
        ["duplicate", "duplicate"],
    ],
)
def test_baseline_must_be_sorted_and_unique(tmp_path: Path, violations: list[str]) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path, violations)
    with pytest.raises(checker.PolicyError):
        checker.load_baseline(path)


def test_repository_policy_is_current() -> None:
    policy = checker.load_policy(REPO_ROOT, REPO_ROOT / checker.MAP_PATH)
    checker.validate_hook(REPO_ROOT, policy)
    assert checker.scan(REPO_ROOT, policy) == checker.load_baseline(
        REPO_ROOT / checker.BASELINE_PATH
    )


def test_required_lint_job_runs_boundary_checker() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/lint.yml").read_text())
    steps = workflow["jobs"]["lint-run"]["steps"]
    matching = [
        step for step in steps if "scripts/ci/check_boundary_edges.py" in str(step.get("run", ""))
    ]
    assert len(matching) == 1
    assert matching[0]["name"] == "Enforce Boundary 2 module-edge policy"
