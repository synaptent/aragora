"""Every row of docs/architecture/shims.md resolves to one object at both paths."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

SHIMS_DOC = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "shims.md"
COLUMNS = ["old path", "new path", "pr", "retire-after"]


def _rows() -> list[dict[str, str]]:
    lines = [
        line for line in SHIMS_DOC.read_text(encoding="utf-8").splitlines() if line.startswith("|")
    ]
    header = [cell.strip().lower() for cell in lines[0].strip("|").split("|")]
    assert header == COLUMNS
    rows = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == len(COLUMNS), line
        rows.append(dict(zip(COLUMNS, cells)))
    return rows


def _resolve(path: str) -> object:
    module_name, _, symbol = path.strip("` ").partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, symbol) if symbol else module


def test_shims_table_has_rows() -> None:
    assert _rows()


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["old path"].strip("`"))
def test_shim_row_resolves_to_the_same_object(row: dict[str, str]) -> None:
    assert re.fullmatch(r"#\d+", row["pr"]), row["pr"]
    assert row["retire-after"]
    old_path, new_path = row["old path"], row["new path"]
    assert re.fullmatch(r"`aragora(\.\w+)+(:\w+)?`", old_path), old_path
    assert re.fullmatch(r"`aragora(\.\w+)+(:\w+)?`", new_path), new_path
    old_obj, new_obj = _resolve(old_path), _resolve(new_path)
    if ":" in old_path:
        assert old_obj is new_obj
