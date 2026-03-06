#!/usr/bin/env python3
"""Enforce `python -m pip install` usage in GitHub workflows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    column: int
    message: str


WORKFLOW_ROOT = Path(".github/workflows")
WORKFLOW_GLOBS = ("*.yml", "*.yaml")
BARE_PIP_INSTALL_PATTERN = re.compile(r"(?<!-m[ \t])\bpip install\b")


def find_bare_pip_install_violations(workflow_text: str) -> list[tuple[int, int, str]]:
    """Return violations as (line, column, message) tuples."""
    violations: list[tuple[int, int, str]] = []
    run_line_re = re.compile(r"^\s*(?:-\s*)?run:\s*(.*)$")
    in_run_block = False
    run_block_indent = 0

    for line_number, line in enumerate(workflow_text.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if in_run_block:
            if stripped and indent <= run_block_indent:
                in_run_block = False
            else:
                if not stripped or stripped.startswith("#"):
                    continue
                match = BARE_PIP_INSTALL_PATTERN.search(line)
                if match is not None:
                    violations.append(
                        (
                            line_number,
                            match.start() + 1,
                            "use `python -m pip install` instead of bare `pip install`",
                        )
                    )
                continue

        run_match = run_line_re.match(line)
        if run_match is None:
            continue

        run_value = run_match.group(1).strip()
        if run_value.startswith("|") or run_value.startswith(">"):
            in_run_block = True
            run_block_indent = line.find("run:")
            continue

        if not run_value or run_value.startswith("#"):
            continue

        match = BARE_PIP_INSTALL_PATTERN.search(run_value)
        if match is not None:
            value_start = line.find(run_value)
            violations.append(
                (
                    line_number,
                    value_start + match.start() + 1,
                    "use `python -m pip install` instead of bare `pip install`",
                )
            )
    return violations


def _iter_workflow_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    workflow_dir = repo_root / WORKFLOW_ROOT
    if not workflow_dir.exists():
        return files
    for pattern in WORKFLOW_GLOBS:
        files.extend(sorted(workflow_dir.rglob(pattern)))
    return sorted(set(files))


def check_repo(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    workflow_files = _iter_workflow_files(repo_root)

    if not workflow_files:
        return [
            Violation(
                path=str(WORKFLOW_ROOT),
                line=1,
                column=1,
                message="workflow directory not found or empty",
            )
        ]

    for workflow_file in workflow_files:
        text = workflow_file.read_text(encoding="utf-8")
        rel = workflow_file.relative_to(repo_root)
        for line, column, message in find_bare_pip_install_violations(text):
            violations.append(Violation(path=str(rel), line=line, column=column, message=message))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce python -m pip install usage in workflow run commands."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to check",
    )
    args = parser.parse_args()

    violations = check_repo(Path(args.repo_root).resolve())
    if not violations:
        print("Workflow pip policy check passed")
        return 0

    print("Workflow pip policy violations detected:")
    for v in violations:
        print(f"- {v.path}:{v.line}:{v.column}: {v.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
