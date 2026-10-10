"""Machine checks for docs/READINESS_REPORT.md.

The report carries one ``Signal | Before | After | Evidence`` table per audit
scope. ``Before`` cells are copied from Factory readiness report
``85b9e93d-baf1-4c85-94eb-36a387c40877``; these tests keep the tables, the
evidence rule and the Summary arithmetic consistent with each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "READINESS_REPORT.md"

HEADER = "| Signal | Before | After | Evidence |"
SCOPES = ("repo", "root", "debate", "verify", "live", "docs", "vscode", "operator")
EXPECTED_ROWS = {"repo": 46, **dict.fromkeys(SCOPES[1:], 38)}
VALUES = {"pass", "fail", "n/a"}
COMMAND_PREFIXES = ("make ", "npm ", "npx ", "python", "go ", "gh ", "pytest", "ruff", "curl")
# Signals the mission declares out of scope for an app keep After == Before.
OUT_OF_SCOPE = {
    ("vscode", "duplicate_code_detection"),
    ("operator", "structured_logging"),
    ("root", "heavy_dependency_detection"),
    ("debate", "heavy_dependency_detection"),
    ("verify", "heavy_dependency_detection"),
}
AUDIT_BEFORE_SCORE = "115/258"
SCOPE_HEADING = re.compile(r"^## Scope `([a-z]+)`")
SIGNAL_CELL = re.compile(r"^`([a-z0-9_]+)`$")
SCORE = re.compile(r"`(\d+)/258`")


@dataclass(frozen=True)
class Row:
    scope: str
    signal: str
    before: str
    after: str
    evidence: str


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse(text: str) -> tuple[list[str], list[Row]]:
    scopes: list[str] = []
    rows: list[Row] = []
    lines = text.splitlines()
    scope = None
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = SCOPE_HEADING.match(line)
        if heading:
            scope = heading.group(1)
        if line.strip() == HEADER:
            assert scope is not None, f"table at line {index + 1} has no scope heading"
            assert scope not in scopes, f"scope {scope} has two tables"
            scopes.append(scope)
            separator = _cells(lines[index + 1])
            assert len(separator) == 4 and all(set(cell) <= set("-:") for cell in separator)
            index += 2
            while index < len(lines) and lines[index].startswith("|"):
                cells = _cells(lines[index])
                assert len(cells) == 4, f"line {index + 1} does not have 4 cells: {lines[index]}"
                rows.append(Row(scope, *cells))
                index += 1
            continue
        index += 1
    return scopes, rows


def _section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, f"report has no '## {title}' section"
    return match.group(1)


def _evidence_is_valid(cell: str) -> bool:
    text = cell.strip()
    if len(text) > 1 and text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    if not text:
        return False
    if text.startswith(COMMAND_PREFIXES):
        return True
    path = Path(text)
    return not path.is_absolute() and ".." not in path.parts and (ROOT / path).exists()


def _invalid_cells(rows: list[Row]) -> list[str]:
    problems = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        where = f"{row.scope}:{row.signal}"
        if not SIGNAL_CELL.match(row.signal):
            problems.append(f"{where}: signal cell is not a backticked signal id")
        if (row.scope, row.signal) in seen:
            problems.append(f"{where}: duplicate signal")
        seen.add((row.scope, row.signal))
        for column, value in (("Before", row.before), ("After", row.after)):
            if value not in VALUES:
                problems.append(f"{where}: {column} {value!r} is not one of {sorted(VALUES)}")
        if row.after != row.before and not row.evidence:
            problems.append(f"{where}: After differs from Before without evidence")
        if row.evidence and not _evidence_is_valid(row.evidence):
            problems.append(
                f"{where}: evidence {row.evidence!r} is neither a repo path nor a command"
            )
    return problems


def _counts(rows: list[Row]) -> dict[str, dict[str, int]]:
    counts = {scope: {"rows": 0, "evaluated": 0, "before": 0, "after": 0} for scope in SCOPES}
    for row in rows:
        entry = counts[row.scope]
        entry["rows"] += 1
        if row.before != "n/a" or row.after != "n/a":
            entry["evaluated"] += 1
        entry["before"] += row.before == "pass"
        entry["after"] += row.after == "pass"
    return counts


@pytest.fixture(scope="module")
def report() -> str:
    assert REPORT.is_file(), "docs/READINESS_REPORT.md is missing"
    return REPORT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(report: str) -> tuple[list[str], list[Row]]:
    return _parse(report)


def test_one_table_per_scope_with_the_exact_header(report: str, parsed) -> None:
    scopes, _ = parsed
    assert report.count(HEADER) == len(SCOPES)
    assert tuple(scopes) == SCOPES


def test_row_counts_per_scope(parsed) -> None:
    _, rows = parsed
    counts = _counts(rows)
    assert {scope: counts[scope]["rows"] for scope in SCOPES} == EXPECTED_ROWS
    assert len(rows) == sum(EXPECTED_ROWS.values()) == 312
    assert sum(entry["evaluated"] for entry in counts.values()) == 258


def test_cells_and_evidence_are_valid(parsed) -> None:
    _, rows = parsed
    assert _invalid_cells(rows) == []


def test_evidence_rule_rejects_bad_cells() -> None:
    rows = [
        Row("repo", "`a`", "fail", "pass", ""),
        Row("repo", "`b`", "fail", "pass", "no/such/file.md"),
        Row("repo", "`c`", "fail", "yes", "make readiness-lint"),
        Row("repo", "`d`", "fail", "pass", "../README.md"),
        Row("repo", "`e`", "fail", "pass", "`docs/RATCHETS.md`"),
        Row("repo", "`f`", "fail", "pass", "gh issue list --state open"),
    ]
    problems = _invalid_cells(rows)
    assert [problem.split(":")[1] for problem in problems] == ["`a`", "`b`", "`c`", "`d`"]


def test_na_and_out_of_scope_rows_keep_their_before_value(parsed) -> None:
    _, rows = parsed
    by_key = {(row.scope, row.signal.strip("`")): row for row in rows}
    for key in OUT_OF_SCOPE:
        assert by_key[key].after == by_key[key].before, key
    for row in rows:
        if row.before == "n/a":
            assert row.after == "n/a", (row.scope, row.signal)


def test_summary_states_both_scores_and_per_scope_counts(report: str, parsed) -> None:
    _, rows = parsed
    counts = _counts(rows)
    summary = _section(report, "Summary")
    before = sum(entry["before"] for entry in counts.values())
    after = sum(entry["after"] for entry in counts.values())
    assert f"`{before}/258`" == f"`{AUDIT_BEFORE_SCORE}`"
    assert SCORE.findall(summary) == ["115", str(after)]
    table = {}
    for line in summary.splitlines():
        cells = _cells(line)
        if line.startswith("| `") and len(cells) == 5:
            table[cells[0].strip("`")] = [int(cell) for cell in cells[1:]]
    assert table == {
        scope: [counts[scope][key] for key in ("rows", "evaluated", "before", "after")]
        for scope in SCOPES
    }
    assert "`test-fast-gate`" in summary and "not yet a required check" in summary


def test_report_carries_the_protected_file_proposal(report: str) -> None:
    section = _section(report, "Proposed protected-file changes")
    assert "AGENTS.md" in section and "CLAUDE.md" in section


def test_parser_output(parsed, capsys) -> None:
    _, rows = parsed
    counts = _counts(rows)
    invalid = _invalid_cells(rows)
    with capsys.disabled():
        print()
        for scope in SCOPES:
            entry = counts[scope]
            print(
                f"readiness-report {scope}: rows={entry['rows']} evaluated={entry['evaluated']} "
                f"pass_before={entry['before']} pass_after={entry['after']}"
            )
        print(f"readiness-report total: rows={len(rows)} invalid_cells={len(invalid)}")
    assert invalid == []
