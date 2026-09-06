#!/usr/bin/env python3
"""Report codebase quality metrics for ratchet enforcement.

QP-01 from docs/status/TECHNICAL_DEBT.md

Produces a JSON report of:
- File counts and LOC by subsystem
- Suppression counts (noqa, type: ignore, except Exception, TODO, FIXME)
- Largest files per subsystem
- Test-to-app file ratios
- Boss loop success metrics (from metrics JSONL)

Usage:
    python scripts/report_code_quality.py                    # Print summary
    python scripts/report_code_quality.py --json             # Machine-readable
    python scripts/report_code_quality.py --check            # Exit 1 if ratchet violated
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SUBSYSTEMS = {
    "swarm": "aragora/swarm",
    "nomic": "aragora/nomic",
    "handlers": "aragora/server/handlers",
    "knowledge_mound": "aragora/knowledge/mound",
    "debate": "aragora/debate",
    "agents": "aragora/agents",
    "inbox": "aragora/inbox",
    "cli": "aragora/cli",
}

# Ratchet thresholds — these should only go DOWN over time
RATCHET = {
    "max_file_loc": 5400,  # No single file above this
    "max_except_exception": 900,  # Total across aragora/
    "max_type_ignore": 700,  # Total across aragora/
    "max_noqa": 2800,  # Total across aragora/
}

# Per-file LOC exceptions: a small allowlist of known-large files with a TRACKED
# extraction plan. These do NOT relax the global ratchet (max_file_loc stays 5400 for
# every other file) — each is a conscious, issue-linked exception kept until the file
# is split. Add a file here only with a tracking issue; remove it once extracted.
MAX_FILE_LOC_EXCEPTIONS = {
    # review_queue.py mixes the merge-quorum GATE subsystem (family/jurisdiction
    # rules, _tier_requirement, _build_model_review_quorum, recognizer/verdict
    # helpers) with the review-queue/settlement CLI. The gate logic belongs beside
    # quorum_evidence.py/merge_quorum_reconcile.py; extraction tracked in #8553.
    # Bridge ceiling until that lands (do not grow further; extract instead).
    "aragora/cli/commands/review_queue.py": 6000,
    # parser.py accumulates one _add_*_parser function per CLI subcommand.  The
    # DIC CLI track (DIC-14..DIC-22, #6024-#6033) pushed it past 5400; the plan
    # is to migrate DIC subcommand parsers into their command modules (#6033).
    "aragora/cli/parser.py": 5420,
}

LAST_RECORDED_BASELINE = {
    "date": "2026-04-12",
    "global_suppressions": {
        "except_exception": 770,
    },
}

_SUPPRESSION_PATTERNS = {
    "except_exception": re.compile(r"except\s+Exception\b"),
    "type_ignore": re.compile(r"#\s*type:\s*ignore"),
    "noqa": re.compile(r"#\s*noqa"),
    "todo": re.compile(r"#\s*TODO\b", re.IGNORECASE),
    "fixme": re.compile(r"#\s*FIXME\b", re.IGNORECASE),
}

_INVALID_BOSS_ISSUE_REASON = "invalid issue_number in v2 prompt data"


def count_lines(path: Path) -> int:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def scan_suppressions(path: Path) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(_SUPPRESSION_PATTERNS, 0)
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                for name, pattern in _SUPPRESSION_PATTERNS.items():
                    if pattern.search(line):
                        counts[name] += 1
    except OSError:
        pass
    return counts


def scan_subsystem(name: str, rel_path: str) -> dict:
    full = REPO_ROOT / rel_path
    if not full.exists():
        return {"name": name, "path": rel_path, "files": 0, "loc": 0}

    py_files = sorted(full.rglob("*.py"))
    py_files = [f for f in py_files if "__pycache__" not in f.parts]

    total_loc = 0
    total_suppressions: dict[str, int] = dict.fromkeys(_SUPPRESSION_PATTERNS, 0)
    largest_files: list[tuple[str, int]] = []

    for f in py_files:
        loc = count_lines(f)
        total_loc += loc
        rel = str(f.relative_to(REPO_ROOT))
        largest_files.append((rel, loc))
        for k, v in scan_suppressions(f).items():
            total_suppressions[k] += v

    largest_files.sort(key=lambda x: -x[1])

    # Count test files
    test_dir = REPO_ROOT / "tests" / Path(rel_path).relative_to("aragora")
    test_count = 0
    if test_dir.exists():
        test_count = len([f for f in test_dir.rglob("test_*.py") if "__pycache__" not in f.parts])

    ratio = test_count / len(py_files) if py_files else 0.0

    return {
        "name": name,
        "path": rel_path,
        "files": len(py_files),
        "loc": total_loc,
        "test_files": test_count,
        "test_ratio": round(ratio, 2),
        "suppressions": total_suppressions,
        "top5_largest": [{"file": f, "loc": l} for f, l in largest_files[:5]],
    }


def scan_all_aragora() -> dict[str, int]:
    """Global suppression counts across all of aragora/."""
    aragora = REPO_ROOT / "aragora"
    totals: dict[str, int] = dict.fromkeys(_SUPPRESSION_PATTERNS, 0)
    for f in aragora.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        for k, v in scan_suppressions(f).items():
            totals[k] += v
    return totals


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def scan_boss_metrics() -> dict:
    """Analyze latest boss metrics for success rate."""
    metrics_path = REPO_ROOT / ".aragora" / "overnight" / "boss_metrics.jsonl"
    if not metrics_path.exists():
        return {"available": False}

    rows = []
    try:
        with metrics_path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        return {"available": False}

    # Filter to v2 prompt runs
    v2_rows = [r for r in rows if r.get("prompt_chars", 0) > 0]
    if not v2_rows:
        return {"available": False, "reason": "no v2 prompt data"}

    # Per-issue latest outcome
    by_issue: dict[int, str] = {}
    for r in v2_rows:
        num = r.get("issue_number")
        if not num:
            continue
        if not _is_positive_int(num):
            return {"available": False, "reason": _INVALID_BOSS_ISSUE_REASON}
        by_issue[num] = str(r.get("worker_status") or "")

    total = len(by_issue)
    completed = sum(1 for s in by_issue.values() if s == "completed")

    return {
        "available": True,
        "total_iterations": len(v2_rows),
        "unique_issues": total,
        "issues_completed": completed,
        "per_issue_success_rate": round(completed / total, 3) if total else 0.0,
        "meets_b0_target": (completed / total >= 0.50) if total else False,
    }


def check_ratchet(global_suppressions: dict[str, int], subsystems: list[dict]) -> list[str]:
    """Check ratchet thresholds and return violations."""
    violations: list[str] = []

    if global_suppressions["except_exception"] > RATCHET["max_except_exception"]:
        violations.append(
            f"except Exception: {global_suppressions['except_exception']} > {RATCHET['max_except_exception']}"
        )
    if global_suppressions["type_ignore"] > RATCHET["max_type_ignore"]:
        violations.append(
            f"type: ignore: {global_suppressions['type_ignore']} > {RATCHET['max_type_ignore']}"
        )
    if global_suppressions["noqa"] > RATCHET["max_noqa"]:
        violations.append(f"noqa: {global_suppressions['noqa']} > {RATCHET['max_noqa']}")

    for sub in subsystems:
        for entry in sub.get("top5_largest", []):
            limit = MAX_FILE_LOC_EXCEPTIONS.get(entry["file"], RATCHET["max_file_loc"])
            if entry["loc"] > limit:
                violations.append(f"{entry['file']}: {entry['loc']} LOC > {limit}")

    return violations


def build_comparison(global_suppressions: dict[str, int]) -> dict[str, object]:
    baseline = dict(LAST_RECORDED_BASELINE)
    compared: dict[str, dict[str, int]] = {}
    for key, baseline_value in dict(baseline.get("global_suppressions", {})).items():
        current_value = int(global_suppressions.get(key, 0) or 0)
        compared[key] = {
            "baseline": int(baseline_value),
            "current": current_value,
            "delta": current_value - int(baseline_value),
        }
    return {
        "baseline_date": str(baseline.get("date", "")).strip() or None,
        "global_suppressions": compared,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report codebase quality metrics")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--check", action="store_true", help="Exit 1 if ratchet violated")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Show deltas versus the last recorded suppression baseline",
    )
    args = parser.parse_args()

    subsystems = [scan_subsystem(name, path) for name, path in SUBSYSTEMS.items()]
    global_suppressions = scan_all_aragora()
    boss_metrics = scan_boss_metrics()
    violations = check_ratchet(global_suppressions, subsystems)
    comparison = build_comparison(global_suppressions) if args.compare else None

    report = {
        "subsystems": subsystems,
        "global_suppressions": global_suppressions,
        "boss_metrics": boss_metrics,
        "ratchet_thresholds": RATCHET,
        "ratchet_violations": violations,
    }
    if comparison is not None:
        report["baseline_comparison"] = comparison

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=== Aragora Code Quality Report ===\n")

        print("Subsystem Summary:")
        for sub in subsystems:
            print(
                f"  {sub['name']:20s} {sub['files']:4d} files  {sub['loc']:7d} LOC  "
                f"test_ratio={sub['test_ratio']:.2f}  "
                f"except_exc={sub['suppressions']['except_exception']}  "
                f"noqa={sub['suppressions']['noqa']}"
            )

        print("\nGlobal Suppressions (aragora/):")
        for k, v in sorted(global_suppressions.items()):
            threshold = RATCHET.get(f"max_{k}", "")
            marker = f" (limit: {threshold})" if threshold else ""
            print(f"  {k:20s} {v:5d}{marker}")

        if boss_metrics.get("available"):
            print("\nBoss Loop Metrics:")
            print(f"  Unique issues attempted: {boss_metrics['unique_issues']}")
            print(f"  Issues completed: {boss_metrics['issues_completed']}")
            print(f"  Per-issue success rate: {boss_metrics['per_issue_success_rate']:.1%}")
            print(f"  Meets B0 target (>=50%): {boss_metrics['meets_b0_target']}")

        if comparison is not None:
            print(
                "\nBaseline Comparison:"
                f"\n  baseline_date: {comparison.get('baseline_date') or 'unknown'}"
            )
            compared = comparison.get("global_suppressions", {})
            if isinstance(compared, dict):
                for name, values in sorted(compared.items()):
                    if not isinstance(values, dict):
                        continue
                    print(
                        "  {name:20s} baseline={baseline:4d} current={current:4d} delta={delta:+d}".format(
                            name=name,
                            baseline=int(values.get("baseline", 0) or 0),
                            current=int(values.get("current", 0) or 0),
                            delta=int(values.get("delta", 0) or 0),
                        )
                    )

        if violations:
            print(f"\nRatchet Violations ({len(violations)}):")
            for v in violations:
                print(f"  FAIL: {v}")
        else:
            print("\nRatchet: PASS (all thresholds met)")

    if args.check and violations:
        sys.exit(1)


if __name__ == "__main__":
    main()
