"""Relocation tolerance of scripts/ci/check_tool_baseline.py.

A NEW key ``P::X`` is *relocated* when ``P`` exists in the tree, exactly one
baseline key ``Q::X`` (``Q != P``, same basename) points at a path that no
longer exists, and that baseline key is claimed by no other NEW key. Relocated
keys are neither new nor resolved and never change the exit code; shrink-only
``--update`` rekeys them count-neutrally and records a ``relocation_log``
entry. Every other case (ambiguity, copies, changed identity, missing file,
count growth) fails closed as NEW. The runner is driven in-process through
``main(argv)`` with a Python "fake tool", as in ``test_check_tool_baseline.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_CI = REPO_ROOT / "scripts" / "ci"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_CI / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parsers = _load("tool_baseline_parsers")
ctb = _load("check_tool_baseline")

OS_LINE = "import os\n"
SYS_LINE = "import sys\n"
JSON_LINE = "import json\n"
MOD = OS_LINE + SYS_LINE  # two F401 findings with distinct line hashes
OTHER = "unused = 1\n"


def _key(path: str, line: str, rule: str) -> str:
    return f"{path}::{parsers.line_hash(line)}::{rule}"


def _f401(path: str, line: int, name: str) -> str:
    return f"{path}:{line}:8: F401 [*] `{name}` imported but unused\n"


def _f841(path: str, line: int) -> str:
    return f"{path}:{line}:1: F841 Local variable `unused` is assigned to but never used\n"


def _write(root: Path, files: dict[str, str | None]) -> None:
    """Write ``files`` under ``root``; a ``None`` value deletes the path."""
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _fake_tool(root: Path, stdout: str, rc: int = 1) -> list[str]:
    script = root / f"fake_tool_{abs(hash((stdout, rc)))}.py"
    script.write_text(
        f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({rc})\n", encoding="utf-8"
    )
    return [sys.executable, str(script)]


def _run(baseline: Path, cwd: Path, stdout: str, *extra: str, report: Path | None = None) -> int:
    argv = ["--tool", "ruff", "--baseline", str(baseline), "--cwd", str(cwd)]
    if report is not None:
        argv += ["--report-json", str(report)]
    argv += [*extra, "--", *_fake_tool(cwd, stdout)]
    return ctb.main(argv)


def _report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


OLD_OUT = (
    _f401("pkg/old/mod.py", 1, "os") + _f401("pkg/old/mod.py", 2, "sys") + _f841("pkg/other.py", 1)
)
NEW_OUT = (
    _f401("pkg/new/mod.py", 1, "os") + _f401("pkg/new/mod.py", 2, "sys") + _f841("pkg/other.py", 1)
)
OLD_OS = _key("pkg/old/mod.py", OS_LINE, "F401")
OLD_SYS = _key("pkg/old/mod.py", SYS_LINE, "F401")
NEW_OS = _key("pkg/new/mod.py", OS_LINE, "F401")
NEW_SYS = _key("pkg/new/mod.py", SYS_LINE, "F401")
OTHER_KEY = _key("pkg/other.py", OTHER, "F841")


@pytest.fixture
def moved(tmp_path: Path) -> tuple[Path, Path]:
    """Baseline generated with pkg/old/mod.py; the file is then moved to pkg/new/mod.py."""
    _write(tmp_path, {"pkg/old/mod.py": MOD, "pkg/other.py": OTHER})
    baseline = tmp_path / "b.json"
    assert _run(baseline, tmp_path, OLD_OUT, "--update") == 0
    _write(tmp_path, {"pkg/old/mod.py": None, "pkg/new/mod.py": MOD})
    return baseline, tmp_path


# --- classification at check time --------------------------------------------


def test_move_only_tree_reports_relocated_and_exits_zero(moved: tuple[Path, Path], capsys):
    baseline, root = moved
    before = baseline.read_bytes()
    report = root / "report.json"
    assert _run(baseline, root, NEW_OUT, report=report) == 0
    out = capsys.readouterr().out
    data = _report(report)
    assert data["exit_code"] == 0
    assert data["new_count"] == 0 and data["new_findings"] == []
    assert data["resolved_count"] == 0
    assert data["relocated_count"] == 2
    assert {(r["from"], r["to"], r["count"]) for r in data["relocated_findings"]} == {
        (OLD_OS, NEW_OS, 1),
        (OLD_SYS, NEW_SYS, 1),
    }
    assert f"RELOCATED {OLD_OS} -> {NEW_OS}" in out
    assert f"RELOCATED {OLD_SYS} -> {NEW_SYS}" in out
    assert "ruff: 0 new findings (3 baselined, 0 resolved)" in out
    assert "  NEW " not in out
    assert baseline.read_bytes() == before


def test_move_plus_genuine_new_key_names_only_the_genuine_key(moved: tuple[Path, Path], capsys):
    baseline, root = moved
    _write(root, {"pkg/new/mod.py": MOD + JSON_LINE})
    genuine = _key("pkg/new/mod.py", JSON_LINE, "F401")
    report = root / "report.json"
    assert _run(baseline, root, NEW_OUT + _f401("pkg/new/mod.py", 3, "json"), report=report) == 1
    out = capsys.readouterr().out
    data = _report(report)
    assert data["exit_code"] == 1
    assert data["new_findings"] == [genuine] and data["new_count"] == 1
    assert data["relocated_count"] == 2
    assert f"  NEW {genuine}" in out
    assert out.count("  NEW ") == 1
    assert f"RELOCATED {OLD_OS} -> {NEW_OS}" in out


def test_ambiguous_two_removed_candidates_stay_new(tmp_path: Path):
    _write(tmp_path, {"pkg/a/mod.py": OS_LINE, "pkg/b/mod.py": OS_LINE})
    baseline = tmp_path / "b.json"
    both = _f401("pkg/a/mod.py", 1, "os") + _f401("pkg/b/mod.py", 1, "os")
    assert _run(baseline, tmp_path, both, "--update") == 0
    _write(tmp_path, {"pkg/a/mod.py": None, "pkg/b/mod.py": None, "pkg/c/mod.py": OS_LINE})
    report = tmp_path / "report.json"
    assert _run(baseline, tmp_path, _f401("pkg/c/mod.py", 1, "os"), report=report) == 1
    data = _report(report)
    assert data["relocated_count"] == 0 and data["relocated_findings"] == []
    assert data["new_findings"] == [_key("pkg/c/mod.py", OS_LINE, "F401")]
    assert data["resolved_count"] == 2


def test_old_path_still_present_stays_new(tmp_path: Path):
    """A copy keeps the old path in the tree, so nothing was relocated."""
    _write(tmp_path, {"pkg/old/mod.py": MOD, "pkg/other.py": OTHER})
    baseline = tmp_path / "b.json"
    assert _run(baseline, tmp_path, OLD_OUT, "--update") == 0
    _write(tmp_path, {"pkg/new/mod.py": MOD})
    copied = OLD_OUT + _f401("pkg/new/mod.py", 1, "os") + _f401("pkg/new/mod.py", 2, "sys")
    report = tmp_path / "report.json"
    assert _run(baseline, tmp_path, copied, report=report) == 1
    data = _report(report)
    assert data["relocated_count"] == 0
    assert data["new_findings"] == sorted([NEW_OS, NEW_SYS])
    assert data["resolved_count"] == 0


def test_one_to_one_matching_is_enforced(tmp_path: Path):
    _write(tmp_path, {"pkg/old/mod.py": OS_LINE})
    baseline = tmp_path / "b.json"
    assert _run(baseline, tmp_path, _f401("pkg/old/mod.py", 1, "os"), "--update") == 0
    _write(tmp_path, {"pkg/old/mod.py": None, "pkg/x/mod.py": OS_LINE, "pkg/y/mod.py": OS_LINE})
    split = _f401("pkg/x/mod.py", 1, "os") + _f401("pkg/y/mod.py", 1, "os")
    report = tmp_path / "report.json"
    assert _run(baseline, tmp_path, split, report=report) == 1
    data = _report(report)
    assert data["relocated_count"] == 0
    assert data["new_count"] == 2 and data["resolved_count"] == 1


def test_relocated_key_with_count_growth_stays_new(tmp_path: Path, capsys):
    """Relocation moves the baselined count to the new path; any excess is still NEW."""
    _write(tmp_path, {"pkg/old/mod.py": OS_LINE})
    baseline = tmp_path / "b.json"
    assert _run(baseline, tmp_path, _f401("pkg/old/mod.py", 1, "os"), "--update") == 0
    _write(tmp_path, {"pkg/old/mod.py": None, "pkg/new/mod.py": OS_LINE + OS_LINE})
    twice = _f401("pkg/new/mod.py", 1, "os") + _f401("pkg/new/mod.py", 2, "os")
    report = tmp_path / "report.json"
    assert _run(baseline, tmp_path, twice, report=report) == 1
    data = _report(report)
    assert data["relocated_count"] == 1
    assert data["new_findings"] == [NEW_OS]
    assert "[count 2 > baselined 1]" in capsys.readouterr().out


def test_key_baselined_at_both_paths_absorbs_only_the_old_count(tmp_path: Path, capsys):
    """P::X baselined 1 and Q::X baselined 2: P may carry 3; a 4th occurrence is new."""
    _write(tmp_path, {"pkg/old/mod.py": OS_LINE * 2, "pkg/new/mod.py": OS_LINE})
    baseline = tmp_path / "b.json"
    seed = (
        _f401("pkg/old/mod.py", 1, "os")
        + _f401("pkg/old/mod.py", 2, "os")
        + _f401("pkg/new/mod.py", 1, "os")
    )
    assert _run(baseline, tmp_path, seed, "--update") == 0
    _write(tmp_path, {"pkg/old/mod.py": None, "pkg/new/mod.py": OS_LINE * 4})
    three = "".join(_f401("pkg/new/mod.py", n, "os") for n in (1, 2, 3))
    report = tmp_path / "report.json"
    assert _run(baseline, tmp_path, three, report=report) == 0
    data = _report(report)
    assert data["relocated_findings"] == [{"from": OLD_OS, "to": NEW_OS, "count": 2}]
    assert data["new_count"] == 0 and data["resolved_count"] == 0
    four = three + _f401("pkg/new/mod.py", 4, "os")
    assert _run(baseline, tmp_path, four, report=report) == 1
    assert _report(report)["new_findings"] == [NEW_OS]
    assert "[count 4 > baselined 3]" in capsys.readouterr().out


def test_classify_relocations_conditions(tmp_path: Path):
    """Each condition of the rule in isolation, on the pure classifier."""
    _write(tmp_path, {"pkg/new/mod.py": OS_LINE, "pkg/new/other.py": OS_LINE})
    base = {"pkg/old/mod.py::h::F401": 1}
    assert ctb.classify_relocations({"pkg/new/mod.py::h::F401": 1}, base, tmp_path) == {
        "pkg/new/mod.py::h::F401": "pkg/old/mod.py::h::F401"
    }
    # 1. the new path must exist in the tree
    assert ctb.classify_relocations({"pkg/gone/mod.py::h::F401": 1}, base, tmp_path) == {}
    # 2. same basename, same symbol, same rule
    assert ctb.classify_relocations({"pkg/new/other.py::h::F401": 1}, base, tmp_path) == {}
    assert ctb.classify_relocations({"pkg/new/mod.py::g::F401": 1}, base, tmp_path) == {}
    assert ctb.classify_relocations({"pkg/new/mod.py::h::F811": 1}, base, tmp_path) == {}
    # keys that are not new are never relocated
    assert (
        ctb.classify_relocations(
            {"pkg/new/mod.py::h::F401": 1}, {**base, "pkg/new/mod.py::h::F401": 1}, tmp_path
        )
        == {}
    )
    # 2. the old path must be absent (a copy is not a move)
    _write(tmp_path, {"pkg/old/mod.py": OS_LINE})
    assert ctb.classify_relocations({"pkg/new/mod.py::h::F401": 1}, base, tmp_path) == {}


def test_check_findings_defaults_tree_root_to_cwd(moved: tuple[Path, Path], monkeypatch):
    """Callers that pass keyed findings without ``cwd`` (the mypy JSON gate) get the same rule."""
    baseline, root = moved
    monkeypatch.chdir(root)
    loaded = ctb.load_baseline(baseline, "ruff")
    findings = ctb.key_findings(parsers.parse_ruff(NEW_OUT), parsers.PARSERS["ruff"], root)
    report = root / "report.json"
    assert ctb.check_findings(baseline, loaded, findings, report_json=report) == 0
    assert _report(report)["relocated_count"] == 2


# --- --update -----------------------------------------------------------------


def test_update_rewrites_relocated_keys_count_neutrally(
    moved: tuple[Path, Path], monkeypatch, capsys
):
    baseline, root = moved
    before = json.loads(baseline.read_text(encoding="utf-8"))
    monkeypatch.setattr(ctb, "_utc_now", lambda: "2099-01-01T00:00:00Z")
    assert _run(baseline, root, NEW_OUT, "--update") == 0
    after = json.loads(baseline.read_text(encoding="utf-8"))
    assert sum(after["findings"].values()) == sum(before["findings"].values()) == 3
    assert len(after["findings"]) == len(before["findings"]) == 3
    assert set(after["findings"]) == {NEW_OS, NEW_SYS, OTHER_KEY}
    assert "growth_log" not in before and "growth_log" not in after
    assert after["relocation_log"] == [{"at": "2099-01-01T00:00:00Z", "relocated": 2}]
    assert "rekeyed" in capsys.readouterr().out
    # Byte-stable on a second --update, and the plain check is green with nothing relocated.
    first = baseline.read_bytes()
    assert _run(baseline, root, NEW_OUT, "--update") == 0
    assert baseline.read_bytes() == first
    report = root / "report.json"
    assert _run(baseline, root, NEW_OUT, report=report) == 0
    assert _report(report)["relocated_count"] == 0


def test_update_refused_with_genuine_new_key(moved: tuple[Path, Path], capsys):
    baseline, root = moved
    _write(root, {"pkg/new/mod.py": MOD + JSON_LINE})
    before = baseline.read_bytes()
    grown = NEW_OUT + _f401("pkg/new/mod.py", 3, "json")
    assert _run(baseline, root, grown, "--update") == 1
    err = capsys.readouterr().err
    assert "REFUSED" in err and "by 1 key(s)" in err
    assert baseline.read_bytes() == before


def test_allow_grow_records_genuine_growth_and_relocations_separately(
    moved: tuple[Path, Path], monkeypatch
):
    baseline, root = moved
    _write(root, {"pkg/new/mod.py": MOD + JSON_LINE})
    monkeypatch.setattr(ctb, "_utc_now", lambda: "2099-01-01T00:00:00Z")
    grown = NEW_OUT + _f401("pkg/new/mod.py", 3, "json")
    assert (
        _run(baseline, root, grown, "--update", "--allow-grow", "--reason", "fixture growth") == 0
    )
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["growth_log"] == [
        {"at": "2099-01-01T00:00:00Z", "reason": "fixture growth", "added": 1}
    ]
    assert data["relocation_log"] == [{"at": "2099-01-01T00:00:00Z", "relocated": 2}]
    assert len(data["findings"]) == 4 and sum(data["findings"].values()) == 4


def test_relocation_log_round_trips_and_is_validated(tmp_path: Path, monkeypatch, capsys):
    _write(tmp_path, {"pkg/old/mod.py": MOD})
    baseline = tmp_path / "b.json"
    out = _f401("pkg/old/mod.py", 1, "os") + _f401("pkg/old/mod.py", 2, "sys")
    assert _run(baseline, tmp_path, out, "--update") == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["relocation_log"] = [{"at": "2000-01-01T00:00:00Z", "relocated": 7}]
    baseline.write_text(json.dumps(data), encoding="utf-8")
    # A later shrink preserves the recorded history.
    monkeypatch.setattr(ctb, "_utc_now", lambda: "2099-01-01T00:00:00Z")
    assert _run(baseline, tmp_path, _f401("pkg/old/mod.py", 1, "os"), "--update") == 0
    shrunk = json.loads(baseline.read_text(encoding="utf-8"))
    assert shrunk["relocation_log"] == [{"at": "2000-01-01T00:00:00Z", "relocated": 7}]
    assert "growth_log" not in shrunk
    # A malformed log is a baseline shape error, like growth_log.
    data["relocation_log"] = "nope"
    baseline.write_text(json.dumps(data), encoding="utf-8")
    assert _run(baseline, tmp_path, out) == 2
    assert "relocation_log" in capsys.readouterr().err


def test_report_json_schema_is_additive(moved: tuple[Path, Path]):
    baseline, root = moved
    report = root / "report.json"
    assert _run(baseline, root, NEW_OUT, report=report) == 0
    data = _report(report)
    assert set(data) >= {
        "tool",
        "baseline",
        "exit_code",
        "new_findings",
        "new_count",
        "baselined_count",
        "resolved_count",
        "current_keys",
        "current_occurrences",
        "relocated_count",
        "relocated_findings",
    }
    assert data["baselined_count"] == 3 and data["current_keys"] == 3
    assert data["current_occurrences"] == 3
