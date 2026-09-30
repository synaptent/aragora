"""Relocation tolerance of scripts/ci/mypy_with_baseline.py (legacy ``.mypy-baseline`` filter).

The wrapper feeds mypy output to ``mypy_baseline filter``, which matches each
error's *clean line* (``path:0: severity: message  [code]``, the identity of
the installed package) against the committed baseline. When a file is moved,
every baselined error in it would become NEW. ``_filter`` now points such
errors back at their baselined path before filtering, but only when ``P``
exists, exactly one baselined ``Q`` with the same basename is absent from the
tree and no other new error claims it. Ambiguity, copies and changed messages
or codes stay NEW; relocations never touch the exit code of a genuine error.

The end-to-end cases run the real pinned ``mypy_baseline filter`` subprocess
against a temp tree and baseline, with a fake mypy process supplying stdout.
"""

from __future__ import annotations

import importlib.util
import subprocess
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


wrapper = _load("mypy_with_baseline")

RET = 'error: Incompatible return value type (got "str", expected "int")  [return-value]'
ARG = 'error: Argument 1 to "f" has incompatible type "str"; expected "int"  [arg-type]'
NAME = 'error: Name "x" is not defined  [name-defined]'
NOTE = "note: See https://mypy.rtfd.io/en/stable/_refs.html#code-arg-type for more info"
FOUND = "Found 2 errors in 2 files (checked 2 source files)\n"


def _raw(path: str, msg: str, line: int = 3, col: int = 5) -> str:
    return f"{path}:{line}:{col}: {msg}\n"


def _clean(path: str, msg: str) -> str:
    return f"{path}:0: {msg}"


def _write(root: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _baseline(root: Path, *lines: str) -> Path:
    path = root / ".mypy-baseline"
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _fake_mypy(root: Path, stdout: str, rc: int = 1) -> subprocess.Popen[bytes]:
    script = root / "fake_mypy.py"
    script.write_text(
        f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({rc})\n", encoding="utf-8"
    )
    return subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(root),
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """Point the wrapper at a temp tree so ``_filter`` runs the real filter there."""
    monkeypatch.setattr(wrapper, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(wrapper, "BASELINE_PATH", tmp_path / ".mypy-baseline")
    return tmp_path


@pytest.fixture
def moved(repo: Path) -> Path:
    """Baseline taken with pkg/old/mod.py; the file now lives at pkg/new/mod.py."""
    _baseline(
        repo,
        _clean("pkg/old/mod.py", RET),
        _clean("pkg/old/mod.py", ARG),
        _clean("pkg/other.py", RET),
    )
    _write(repo, {"pkg/new/mod.py": "x = 1\n", "pkg/other.py": "y = 2\n"})
    return repo


MOVED_OUT = (
    _raw("pkg/new/mod.py", RET)
    + _raw("pkg/new/mod.py", ARG, line=7)
    + _raw("pkg/new/mod.py", NOTE, line=7)
    + _raw("pkg/other.py", RET, line=1, col=1)
    + FOUND
)


# --- end to end through the pinned mypy_baseline filter --------------------


def test_move_only_output_is_filtered_and_exits_zero(moved: Path, capfd):
    before = wrapper.BASELINE_PATH.read_bytes()
    assert wrapper._filter(_fake_mypy(moved, MOVED_OUT)) == 0
    out = capfd.readouterr().out
    assert f"RELOCATED {_clean('pkg/old/mod.py', RET)} -> {_clean('pkg/new/mod.py', RET)}" in out
    assert f"RELOCATED {_clean('pkg/old/mod.py', ARG)} -> {_clean('pkg/new/mod.py', ARG)}" in out
    assert "2 relocated" in out
    assert _raw("pkg/new/mod.py", RET) not in out  # matched, so the filter did not print it
    assert "new: 0" in out
    assert wrapper.BASELINE_PATH.read_bytes() == before


def test_move_plus_genuine_new_error_reports_only_the_genuine_error(moved: Path, capfd):
    genuine = _raw("pkg/new/mod.py", NAME, line=9, col=1)
    assert wrapper._filter(_fake_mypy(moved, MOVED_OUT + genuine)) == 1
    out = capfd.readouterr().out
    assert genuine in out
    assert _raw("pkg/new/mod.py", RET) not in out
    assert _raw("pkg/new/mod.py", ARG, line=7) not in out
    assert "new: 1" in out
    assert f"RELOCATED {_clean('pkg/old/mod.py', RET)} -> {_clean('pkg/new/mod.py', RET)}" in out


def test_ambiguous_two_absent_candidates_stay_new(repo: Path, capfd):
    _baseline(repo, _clean("pkg/a/mod.py", RET), _clean("pkg/b/mod.py", RET))
    _write(repo, {"pkg/c/mod.py": "x = 1\n"})
    assert wrapper._filter(_fake_mypy(repo, _raw("pkg/c/mod.py", RET) + FOUND)) == 1
    out = capfd.readouterr().out
    assert "RELOCATED" not in out
    assert _raw("pkg/c/mod.py", RET) in out


def test_old_path_still_present_stays_new(repo: Path, capfd):
    """A copy keeps the baselined file in place, so the copy's errors are new."""
    _baseline(repo, _clean("pkg/old/mod.py", RET))
    _write(repo, {"pkg/old/mod.py": "x = 1\n", "pkg/new/mod.py": "x = 1\n"})
    both = _raw("pkg/old/mod.py", RET) + _raw("pkg/new/mod.py", RET) + FOUND
    assert wrapper._filter(_fake_mypy(repo, both)) == 1
    out = capfd.readouterr().out
    assert "RELOCATED" not in out
    assert _raw("pkg/new/mod.py", RET) in out
    assert _raw("pkg/old/mod.py", RET) not in out


def test_one_to_one_matching_is_enforced(repo: Path, capfd):
    _baseline(repo, _clean("pkg/old/mod.py", RET))
    _write(repo, {"pkg/x/mod.py": "x = 1\n", "pkg/y/mod.py": "x = 1\n"})
    split = _raw("pkg/x/mod.py", RET) + _raw("pkg/y/mod.py", RET) + FOUND
    assert wrapper._filter(_fake_mypy(repo, split)) == 2
    assert "RELOCATED" not in capfd.readouterr().out


def test_new_path_missing_from_tree_stays_new(repo: Path, capfd):
    _baseline(repo, _clean("pkg/old/mod.py", RET))
    assert wrapper._filter(_fake_mypy(repo, _raw("pkg/new/mod.py", RET) + FOUND)) == 1
    assert "RELOCATED" not in capfd.readouterr().out


def test_relocation_moves_only_the_baselined_count(repo: Path, capfd):
    _baseline(repo, _clean("pkg/old/mod.py", RET))
    _write(repo, {"pkg/new/mod.py": "x = 1\n"})
    twice = _raw("pkg/new/mod.py", RET, line=3) + _raw("pkg/new/mod.py", RET, line=8) + FOUND
    assert wrapper._filter(_fake_mypy(repo, twice)) == 1
    out = capfd.readouterr().out
    assert f"RELOCATED {_clean('pkg/old/mod.py', RET)} -> {_clean('pkg/new/mod.py', RET)}" in out
    assert "new: 1" in out


def test_error_baselined_at_both_paths_absorbs_only_the_old_count(repo: Path, capfd):
    """P baselined once and Q twice: three occurrences at P pass; a fourth is new."""
    _baseline(
        repo,
        _clean("pkg/old/mod.py", RET),
        _clean("pkg/old/mod.py", RET),
        _clean("pkg/new/mod.py", RET),
    )
    _write(repo, {"pkg/new/mod.py": "x = 1\n"})
    three = "".join(_raw("pkg/new/mod.py", RET, line=n) for n in (1, 2, 3))
    assert wrapper._filter(_fake_mypy(repo, three + FOUND)) == 0
    out = capfd.readouterr().out
    assert "1 relocated error(s) (2 occurrence(s))" in out
    assert "new: 0" in out
    four = three + _raw("pkg/new/mod.py", RET, line=4)
    assert wrapper._filter(_fake_mypy(repo, four + FOUND)) == 1
    out = capfd.readouterr().out
    assert "1 relocated error(s) (2 occurrence(s))" in out
    assert "new: 1" in out


def test_no_relocations_leaves_the_stream_untouched(repo: Path, capfd):
    """The legacy path: baselined errors, one fixed entry (allow-unsynced) and one new error."""
    _baseline(repo, _clean("pkg/other.py", RET), _clean("pkg/fixed.py", ARG))
    _write(repo, {"pkg/other.py": "y = 2\n", "pkg/fixed.py": "z = 3\n"})
    out_text = _raw("pkg/other.py", RET) + _raw("pkg/other.py", NAME, line=4) + FOUND
    assert wrapper._filter(_fake_mypy(repo, out_text)) == 1
    out = capfd.readouterr().out
    assert "RELOCATED" not in out
    assert _raw("pkg/other.py", NAME, line=4) in out
    assert "fixed: 1" in out and "new: 1" in out


# --- identity is the installed mypy_baseline clean line, path swapped ------


def _relocate(
    lines: str, baseline: list[str], root: Path
) -> tuple[list[str], list[tuple[str, str, int]]]:
    rewritten, relocations = wrapper._relocate_moved_files(
        lines.splitlines(keepends=True), baseline, root
    )
    return rewritten, relocations


def test_identity_ignores_position_and_defined_on_line(tmp_path: Path):
    _write(tmp_path, {"pkg/new/mod.py": "x = 1\n"})
    redef = 'error: Name "f" already defined on line 40  [no-redef]'
    baseline = [
        _clean("pkg/old/mod.py", RET),
        _clean("pkg/old/mod.py", 'error: Name "f" already defined on line 0  [no-redef]'),
    ]
    stream = _raw("pkg/new/mod.py", RET, line=99, col=1) + _raw("pkg/new/mod.py", redef, 41) + FOUND
    rewritten, relocations = _relocate(stream, baseline, tmp_path)
    assert rewritten == [f"{baseline[0]}\n", f"{baseline[1]}\n", FOUND]
    assert relocations == [
        (baseline[0], _clean("pkg/new/mod.py", RET), 1),
        (
            baseline[1],
            _clean("pkg/new/mod.py", 'error: Name "f" already defined on line 0  [no-redef]'),
            1,
        ),
    ]


def test_changed_message_or_code_is_not_a_relocation(tmp_path: Path):
    _write(tmp_path, {"pkg/new/mod.py": "x = 1\n"})
    baseline = [_clean("pkg/old/mod.py", RET)]
    other_code = RET.replace("[return-value]", "[misc]")
    other_msg = RET.replace('"int"', '"bytes"')
    for msg in (other_code, other_msg, ARG):
        stream = _raw("pkg/new/mod.py", msg) + FOUND
        assert _relocate(stream, baseline, tmp_path) == ([_raw("pkg/new/mod.py", msg), FOUND], [])


def test_notes_and_non_error_lines_pass_through(tmp_path: Path):
    _write(tmp_path, {"pkg/new/mod.py": "x = 1\n"})
    baseline = [_clean("pkg/old/mod.py", NOTE)]
    stream = _raw("pkg/new/mod.py", NOTE) + "Success: no issues found in 1 source file\n"
    assert _relocate(stream, baseline, tmp_path) == (stream.splitlines(keepends=True), [])


def test_basename_must_match(tmp_path: Path):
    _write(tmp_path, {"pkg/new/other.py": "x = 1\n"})
    baseline = [_clean("pkg/old/mod.py", RET)]
    stream = _raw("pkg/new/other.py", RET) + FOUND
    assert _relocate(stream, baseline, tmp_path) == ([_raw("pkg/new/other.py", RET), FOUND], [])


def test_already_baselined_at_new_path_is_not_relocated(tmp_path: Path):
    _write(tmp_path, {"pkg/new/mod.py": "x = 1\n"})
    baseline = [_clean("pkg/old/mod.py", RET), _clean("pkg/new/mod.py", RET)]
    stream = _raw("pkg/new/mod.py", RET) + FOUND
    assert _relocate(stream, baseline, tmp_path) == ([_raw("pkg/new/mod.py", RET), FOUND], [])


def test_filter_flags_still_mirror_the_legacy_interface(repo: Path, monkeypatch):
    seen: list[list[str]] = []
    real_popen = wrapper.subprocess.Popen

    class _Recorder:
        def __init__(self, cmd, **kwargs):
            seen.append(list(cmd))
            self.returncode = 0

        def communicate(self, input=None):
            return b"", b""

    monkeypatch.setattr(wrapper.subprocess, "Popen", _Recorder)
    _baseline(repo, _clean("pkg/other.py", RET))
    _write(repo, {"pkg/other.py": "y = 2\n"})
    proc = real_popen(
        [sys.executable, "-c", "print('Success: no issues found in 1 source file')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert wrapper._filter(proc) == 0
    (cmd,) = seen
    assert cmd[:4] == [sys.executable, "-m", "mypy_baseline", "filter"]
    assert cmd[cmd.index("--baseline-path") + 1] == str(repo / ".mypy-baseline")
    assert "--no-colors" in cmd and "--allow-unsynced" in cmd
    assert cmd[cmd.index("--ignore-categories") + 1] == "note"
