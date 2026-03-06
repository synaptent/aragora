#!/usr/bin/env python3
"""CI classification scan for PII in source code string literals.

Walks tracked Python files (excluding tests/, docs/, .git/) and extracts
string literals via the ``ast`` module, then runs
:class:`DataClassifier.scan_for_pii` on each literal.

Exit codes:
    0 -- No PII detections (or all matches allowlisted).
    1 -- At least one un-allowlisted PII detection found.

Usage::

    python scripts/classification_scan.py
    python scripts/classification_scan.py --allowlist scripts/pii_allowlist.txt
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure repo root is importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.compliance.data_classification import DataClassifier


# ---------------------------------------------------------------------------
# Allowlist loader
# ---------------------------------------------------------------------------


def _load_allowlist(path: str | None) -> list[str]:
    """Load allowlisted patterns from *path*, one per line.

    Blank lines and lines starting with ``#`` are ignored.
    """
    if not path:
        return []
    entries: list[str] = []
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#"):
                entries.append(line)
    return entries


def _is_allowlisted(text: str, start: int, end: int, allowlist: list[str]) -> bool:
    """Return ``True`` if the matched substring is covered by *allowlist*."""
    matched = text[start:end]
    for pattern in allowlist:
        if pattern in matched:
            return True
    return False


# ---------------------------------------------------------------------------
# String literal extractor
# ---------------------------------------------------------------------------


def _extract_string_literals(source: str) -> list[str]:
    """Parse *source* as Python and return all string literal values."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            # f-string -- collect constant parts
            for val in node.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    literals.append(val.value)
    return literals


# ---------------------------------------------------------------------------
# Tracked file enumeration
# ---------------------------------------------------------------------------

_EXCLUDE_DIRS = {"tests", "docs", ".git", "__pycache__", "node_modules"}


def _git_tracked_python_files(repo_root: Path) -> list[Path]:
    """Return tracked ``*.py`` files, excluding test/doc directories."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "*.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: walk filesystem
        return _walk_python_files(repo_root)

    files: list[Path] = []
    for line in result.stdout.strip().splitlines():
        rel = Path(line)
        # Exclude paths whose first component is in the exclusion set
        parts = rel.parts
        if parts and parts[0] in _EXCLUDE_DIRS:
            continue
        full = repo_root / rel
        if full.is_file():
            files.append(full)
    return files


def _walk_python_files(repo_root: Path) -> list[Path]:
    """Filesystem fallback when ``git ls-files`` is unavailable."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                files.append(Path(dirpath) / fname)
    return files


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def scan(
    repo_root: Path,
    allowlist: list[str],
) -> dict[str, Any]:
    """Scan the repository and return a result summary dict."""
    classifier = DataClassifier()
    files = _git_tracked_python_files(repo_root)

    total_files = 0
    total_detections = 0
    detection_types: dict[str, int] = {}
    findings: list[dict[str, Any]] = []

    for filepath in files:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        total_files += 1
        literals = _extract_string_literals(source)

        for literal in literals:
            detections = classifier.scan_for_pii(literal)
            for det in detections:
                if _is_allowlisted(literal, det.start, det.end, allowlist):
                    continue
                total_detections += 1
                detection_types[det.type] = detection_types.get(det.type, 0) + 1
                findings.append(
                    {
                        "file": str(filepath.relative_to(repo_root)),
                        "type": det.type,
                        "confidence": det.confidence,
                        "snippet": literal[max(0, det.start - 10) : det.end + 10][:80],
                    }
                )

    return {
        "files_scanned": total_files,
        "pii_detections": total_detections,
        "detection_types": detection_types,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan tracked Python files for PII in string literals.",
    )
    parser.add_argument(
        "--allowlist",
        help="Path to an allowlist file (one pattern per line)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        help="Repository root directory (default: auto-detected)",
    )
    args = parser.parse_args(argv)

    allowlist = _load_allowlist(args.allowlist)
    repo_root = Path(args.repo_root)

    result = scan(repo_root, allowlist)

    # Print summary
    print("=" * 60)
    print("DATA CLASSIFICATION CI SCAN")
    print("=" * 60)
    print(f"  Files scanned:      {result['files_scanned']}")
    print(f"  PII detections:     {result['pii_detections']}")

    if result["detection_types"]:
        print("  Detection types:")
        for pii_type, count in sorted(result["detection_types"].items()):
            print(f"    {pii_type}: {count}")

    if result["findings"]:
        print()
        print("FINDINGS:")
        for finding in result["findings"][:50]:  # Cap output at 50
            print(
                f"  [{finding['type']}] {finding['file']} "
                f"(confidence={finding['confidence']:.2f}): "
                f"{finding['snippet']!r}"
            )
        if len(result["findings"]) > 50:
            print(f"  ... and {len(result['findings']) - 50} more")

    print()
    if result["pii_detections"] > 0:
        print(f"FAILED: {result['pii_detections']} PII detection(s) found.")
        return 1
    else:
        print("PASSED: No PII detections found.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
