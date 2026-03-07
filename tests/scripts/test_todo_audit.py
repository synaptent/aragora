from __future__ import annotations

from pathlib import Path

from scripts.todo_audit import iter_markers, main


def test_iter_markers_counts_comment_markers_only(tmp_path: Path) -> None:
    root = tmp_path / "aragora"
    root.mkdir()
    (root / "one.py").write_text(
        "# TODO: keep me\ntext = 'TODO in string should not count'\n  # FIXME later\n",
        encoding="utf-8",
    )
    (root / "two.py").write_text(
        "def noop():\n    return '# HACK in string should not count'\n# XXX final marker\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("# TODO in txt should not count\n", encoding="utf-8")

    markers = iter_markers(root)

    assert [(path.name, line_no, content) for path, line_no, content in markers] == [
        ("one.py", 1, "# TODO: keep me"),
        ("one.py", 3, "# FIXME later"),
        ("two.py", 3, "# XXX final marker"),
    ]


def test_main_list_respects_limit(tmp_path: Path, capsys: object, monkeypatch: object) -> None:
    root = tmp_path / "aragora"
    root.mkdir()
    (root / "a.py").write_text("# TODO first\n", encoding="utf-8")
    (root / "b.py").write_text("# FIXME second\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["todo_audit.py", "--mode", "list", "--root", str(root), "--limit", "1"],
    )

    assert main() == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line]
    assert len(lines) == 1
    assert lines[0].endswith(":1:# TODO first")
