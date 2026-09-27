"""Tests for scripts/audit_test_skips.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts import audit_test_skips  # noqa: E402


def test_emit_output_mutes_stdout_after_broken_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    muted = []

    class BrokenStdout:
        def write(self, _output: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise AssertionError("flush should not run after a broken write")

    monkeypatch.setattr(audit_test_skips.sys, "stdout", BrokenStdout())
    monkeypatch.setattr(
        audit_test_skips,
        "_mute_stdout_after_broken_pipe",
        lambda: muted.append(True),
    )

    audit_test_skips._emit_output("payload")

    assert muted == [True]


def test_main_json_uses_pipe_safe_emitter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    emitted: list[str] = []
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_test_skips.py", "--json", "--tests-dir", str(tests_dir)],
    )
    monkeypatch.setattr(audit_test_skips, "audit_skips", lambda _tests_dir: [])
    monkeypatch.setattr(
        audit_test_skips,
        "generate_report",
        lambda _markers: {
            "total": 0,
            "by_category": {},
            "by_type": {},
            "by_file": {},
            "high_skip_files": [],
            "markers": [],
            "generated_at": "2026-06-13T00:00:00",
        },
    )
    monkeypatch.setattr(audit_test_skips, "_emit_output", emitted.append)

    audit_test_skips.main()

    assert json.loads(emitted[0])["total"] == 0


def test_main_default_summary_uses_pipe_safe_emitter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    emitted: list[str] = []
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_test_skips.py", "--tests-dir", str(tests_dir)],
    )
    monkeypatch.setattr(audit_test_skips, "audit_skips", lambda _tests_dir: [])
    monkeypatch.setattr(
        audit_test_skips,
        "generate_report",
        lambda _markers: {
            "total": 2,
            "by_category": {"known_bug": 1, "optional_dependency": 1},
            "by_type": {"skip": 2},
            "by_file": {"tests/test_example.py": 2},
            "high_skip_files": [{"file": "tests/test_example.py", "count": 2}],
            "markers": [],
            "generated_at": "2026-06-13T00:00:00",
        },
    )
    monkeypatch.setattr(audit_test_skips, "_emit_output", emitted.append)

    audit_test_skips.main()

    assert "Total skip markers: 2" in emitted[0]
    assert "known_bug: 1" in emitted[0]
    assert "tests/test_example.py: 2" in emitted[0]


def test_main_update_docs_writes_baseline_with_trailing_newline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_test_skips.py", "--update-docs", "--tests-dir", str(tests_dir)],
    )
    monkeypatch.setattr(audit_test_skips, "audit_skips", lambda _tests_dir: [])
    monkeypatch.setattr(
        audit_test_skips,
        "generate_report",
        lambda _markers: {
            "total": 7,
            "by_category": {},
            "by_type": {},
            "by_file": {},
            "high_skip_files": [],
            "markers": [],
            "generated_at": "2026-06-13T00:00:00",
        },
    )
    monkeypatch.setattr(audit_test_skips, "generate_markdown", lambda _report: "# stub\n")
    monkeypatch.setattr(audit_test_skips, "_emit_output", lambda _output: None)

    audit_test_skips.main()

    assert (tests_dir / "SKIP_AUDIT.md").read_text() == "# stub\n"
    # The committed tests/.skip_baseline convention is a single integer plus LF.
    assert (tests_dir / ".skip_baseline").read_text() == "7\n"
