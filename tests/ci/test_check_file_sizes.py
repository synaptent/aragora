"""Unit tests for scripts/ci/check_file_sizes.py.

These exercise the pure measurement/offender/freeze logic and the ``main`` CLI
wiring against a temporary fake checkout (``REPO_ROOT`` and
``list_source_files`` are monkeypatched), plus real git enumeration in isolated
temporary repositories. They never depend on the real census. Behavior against the real ``aragora``
package (green on clean tree, oversized-newcomer tamper, baseline shrink-only)
is covered by the VAL-P0-004/005 acceptance checks.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECKER_PATH = REPO_ROOT / "scripts" / "ci" / "check_file_sizes.py"

_spec = importlib.util.spec_from_file_location("check_file_sizes", _CHECKER_PATH)
cfs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfs)


def _make_file(root: Path, rel: str, lines: int) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# pad\n" * lines, encoding="utf-8")


# --- pure logic -------------------------------------------------------------


def test_count_lines_matches_splitlines(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    assert cfs.count_lines(f) == 3
    # missing file counts as 0, never raises
    assert cfs.count_lines(tmp_path / "missing.py") == 0


def test_find_offenders_flags_new_and_skips_baselined():
    oversized = {"aragora/new_big.py": 2500, "aragora/known_big.py": 2400}
    baseline = {"aragora/known_big.py"}
    offenders = cfs.find_offenders(oversized, baseline)
    assert offenders == {"aragora/new_big.py": 2500}


def test_measure_oversized_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    _make_file(tmp_path, "aragora/big.py", 2100)
    _make_file(tmp_path, "aragora/exact.py", cfs.LIMIT)  # exactly at limit: not over
    _make_file(tmp_path, "aragora/small.py", 10)
    oversized = cfs.measure_oversized(["aragora/big.py", "aragora/exact.py", "aragora/small.py"])
    assert oversized == {"aragora/big.py": 2100}


# --- CLI: check mode --------------------------------------------------------


def test_main_green_when_oversized_baselined(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: ["aragora/big.py"])
    _make_file(tmp_path, "aragora/big.py", 2100)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {"aragora/big.py": 2100}}), encoding="utf-8")
    assert cfs.main(["--baseline", str(baseline)]) == 0
    assert "OK:" in capsys.readouterr().out


def test_main_fails_and_names_unbaselined_oversized(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: ["aragora/newcomer.py"])
    _make_file(tmp_path, "aragora/newcomer.py", 2100)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert cfs.main(["--baseline", str(baseline)]) == 1
    assert "aragora/newcomer.py" in capsys.readouterr().out


def test_main_missing_baseline_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: [])
    assert cfs.main(["--baseline", str(tmp_path / "nope.json")]) == 2


# --- CLI: freeze (shrink-only) ---------------------------------------------


@pytest.mark.parametrize("census", [{}, {"aragora/big.py": 2100}])
@pytest.mark.parametrize("adopt", [False, True])
def test_freeze_unchanged_census_preserves_bytes(tmp_path, monkeypatch, capsys, census, adopt):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: list(census))
    monkeypatch.setattr(cfs, "_git_head", lambda: "new-head")
    for rel, lines in census.items():
        _make_file(tmp_path, rel, lines)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "files": census,
                "frozen_from_ref": "old-head",
                "frozen_at": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    before = baseline.read_bytes()
    args = ["--freeze", "--baseline", str(baseline)]
    if adopt:
        args.append("--adopt")
    assert cfs.main(args) == 0
    assert baseline.read_bytes() == before
    assert capsys.readouterr().out == (
        f"Baseline unchanged ({len(census)} oversized file(s) > 2000 lines); "
        f"not rewritten -> {baseline}\n"
    )


def test_freeze_refuses_to_grow_without_adopt(tmp_path, monkeypatch):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: ["aragora/big.py"])
    _make_file(tmp_path, "aragora/big.py", 2100)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {}}), encoding="utf-8")  # empty -> big.py is new
    before = baseline.read_bytes()
    # exit code 2 (shrink-only violation), baseline unchanged
    assert cfs.main(["--freeze", "--baseline", str(baseline)]) == 2
    assert baseline.read_bytes() == before


@pytest.mark.parametrize("existing", [False, True])
def test_freeze_adopt_writes_full_census(tmp_path, monkeypatch, existing):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        cfs, "list_source_files", lambda globs: ["aragora/big.py", "aragora/small.py"]
    )
    _make_file(tmp_path, "aragora/big.py", 2100)
    _make_file(tmp_path, "aragora/small.py", 10)
    baseline = tmp_path / "baseline.json"
    if existing:
        baseline.write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert cfs.main(["--freeze", "--adopt", "--baseline", str(baseline)]) == 0
    written = json.loads(baseline.read_text())
    assert written["files"] == {"aragora/big.py": 2100}
    assert written["limit"] == cfs.LIMIT


def test_freeze_allows_shrink(tmp_path, monkeypatch):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "_git_head", lambda: "new-head")
    # baseline has two entries; only one is still oversized -> shrink is allowed
    monkeypatch.setattr(
        cfs, "list_source_files", lambda globs: ["aragora/big.py", "aragora/shrunk.py"]
    )
    _make_file(tmp_path, "aragora/big.py", 2100)
    _make_file(tmp_path, "aragora/shrunk.py", 50)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "files": {"aragora/big.py": 2100, "aragora/shrunk.py": 2400},
                "frozen_from_ref": "old-head",
                "frozen_at": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    before = baseline.read_bytes()
    assert cfs.main(["--freeze", "--baseline", str(baseline)]) == 0
    assert baseline.read_bytes() != before
    written = json.loads(baseline.read_text())
    assert written["files"] == {"aragora/big.py": 2100}
    assert written["frozen_from_ref"] == "new-head"
    assert written["frozen_at"] != "2020-01-01T00:00:00Z"


@pytest.mark.parametrize("lines", [2050, 2200])
def test_freeze_rewrites_changed_counts_without_new_entries(tmp_path, monkeypatch, lines):
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cfs, "list_source_files", lambda globs: ["aragora/big.py"])
    _make_file(tmp_path, "aragora/big.py", lines)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {"aragora/big.py": 2100}}), encoding="utf-8")
    before = baseline.read_bytes()
    assert cfs.main(["--freeze", "--baseline", str(baseline)]) == 0
    assert baseline.read_bytes() != before
    assert json.loads(baseline.read_text())["files"] == {"aragora/big.py": lines}


# --- Real git enumeration (no mocked file list) -----------------------------


@pytest.fixture
def git_checkout(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(cfs, "REPO_ROOT", tmp_path)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {}}), encoding="utf-8")
    return tmp_path, baseline


def test_main_reports_untracked_oversized_python(git_checkout, capsys):
    root, baseline = git_checkout
    rel = "aragora/_val_bigfile_probe.py"
    _make_file(root, rel, 2100)
    tracked = subprocess.check_output(["git", "ls-files", "--", rel], cwd=root, text=True)
    assert tracked == ""
    assert cfs.main(["--baseline", str(baseline)]) == 1
    assert f"NEW {rel} (2100 lines)" in capsys.readouterr().out
    (root / rel).unlink()
    assert cfs.main(["--baseline", str(baseline)]) == 0


def test_default_scope_includes_tracked_and_untracked_python_only(git_checkout, capsys):
    root, baseline = git_checkout
    tracked = "aragora/tracked.py"
    untracked = "aragora/nested/untracked.py"
    for rel in (
        tracked,
        untracked,
        "aragora/ignored/big.py",
        "aragora/big.ts",
        "other/big.py",
    ):
        _make_file(root, rel, 2100)
    subprocess.run(["git", "add", "--", tracked], cwd=root, check=True)
    assert cfs.main(["--baseline", str(baseline), "--json"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["offenders"] == {tracked: 2100, untracked: 2100}


@pytest.mark.parametrize(
    "globs",
    [
        ["--glob", "app/src/**/*.ts", "--glob", "app/src/**/*.tsx"],
        ["--glob", "app/src/**/*.{ts,tsx}"],
    ],
)
def test_glob_is_repeatable_recursive_and_replaces_python_default(git_checkout, capsys, globs):
    root, baseline = git_checkout
    expected = {"app/src/top.ts": 2100, "app/src/nested/view.tsx": 2100}
    for rel in [*expected, "app/src/ignored/big.ts", "app/src/big.js", "aragora/big.py"]:
        _make_file(root, rel, 2100)
    subprocess.run(["git", "add", "--", "app/src/top.ts"], cwd=root, check=True)
    assert (
        cfs.main(
            [
                *globs,
                "--baseline",
                str(baseline),
                "--json",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["offenders"] == expected


def test_glob_freeze_uses_custom_baseline_and_stays_shrink_only(git_checkout, capsys):
    root, baseline = git_checkout
    rel = "operator/nested/main.go"
    _make_file(root, rel, 2100)
    _make_file(root, "aragora/big.py", 2100)
    args = ["--glob", "operator/**/*.go", "--baseline", str(baseline)]
    original = baseline.read_bytes()
    assert cfs.main([*args, "--freeze"]) == 2
    assert baseline.read_bytes() == original
    assert cfs.main([*args, "--freeze", "--adopt"]) == 0
    written = json.loads(baseline.read_text())
    assert written["files"] == {rel: 2100}
    assert cfs.main(args) == 0
    (root / rel).unlink()
    assert cfs.main([*args, "--freeze"]) == 0
    assert json.loads(baseline.read_text())["files"] == {}


def test_help_documents_glob_and_baseline(capsys):
    with pytest.raises(SystemExit) as exc:
        cfs.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--glob PATTERN" in help_text
    assert "repeatable" in help_text
    assert "--baseline" in help_text
