#!/usr/bin/env python3
"""Status Document Reconciliation Report.

Cross-checks capability matrix, GA checklist, roadmap, and status docs
for contradictions and drift. Generates a report as artifact and optionally
fails on critical mismatches.

Usage:
    python scripts/reconcile_status_docs.py             # Report only
    python scripts/reconcile_status_docs.py --strict     # Fail on critical drift
    python scripts/reconcile_status_docs.py --json       # JSON output
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files to reconcile
CAPABILITY_MATRIX = REPO_ROOT / "docs" / "CAPABILITY_MATRIX.md"
CAPABILITY_YAML = REPO_ROOT / "aragora" / "capability_surfaces.yaml"
GA_CHECKLIST = REPO_ROOT / "docs" / "GA_CHECKLIST.md"
STATUS_DOC = REPO_ROOT / "docs" / "STATUS.md"
STATUS_DIR = REPO_ROOT / "docs" / "status" / "STATUS.md"
ROADMAP = REPO_ROOT / "ROADMAP.md"
CONNECTOR_STATUS = REPO_ROOT / "docs" / "connectors" / "STATUS.md"
EXECUTION_PROGRAM = REPO_ROOT / "docs" / "status" / "EXECUTION_PROGRAM_2026Q2_Q4.md"
CANONICAL_GOALS = REPO_ROOT / "docs" / "CANONICAL_GOALS.md"
FEATURE_DISCOVERY = REPO_ROOT / "docs" / "FEATURE_DISCOVERY.md"
FEATURE_DISCOVERY_STATUS = REPO_ROOT / "docs" / "status" / "FEATURE_DISCOVERY.md"
COMMERCIAL_OVERVIEW_STATUS = REPO_ROOT / "docs" / "status" / "COMMERCIAL_OVERVIEW.md"
OPENAPI_GENERATED = REPO_ROOT / "docs" / "api" / "openapi_generated.json"
CONNECTOR_ROOT = REPO_ROOT / "aragora" / "connectors"

API_METRIC_DOCS = [
    (CANONICAL_GOALS, "CANONICAL_GOALS.md"),
    (FEATURE_DISCOVERY, "FEATURE_DISCOVERY.md"),
    (FEATURE_DISCOVERY_STATUS, "status/FEATURE_DISCOVERY.md"),
    (GA_CHECKLIST, "GA_CHECKLIST.md"),
    (STATUS_DOC, "STATUS.md"),
    (STATUS_DIR, "status/STATUS.md"),
    (ROADMAP, "ROADMAP.md"),
]

LAUNCH_READINESS_DOCS = [
    (CANONICAL_GOALS, "CANONICAL_GOALS.md"),
    (STATUS_DOC, "STATUS.md"),
    (STATUS_DIR, "status/STATUS.md"),
    (ROADMAP, "ROADMAP.md"),
    (COMMERCIAL_OVERVIEW_STATUS, "status/COMMERCIAL_OVERVIEW.md"),
]

API_CLAIM_PATTERNS = [
    re.compile(
        r"(?P<ops>\d[\d,]*)\+\s+API operations(?:\s+across\s+(?P<paths>\d[\d,]*)\+\s+paths)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<ops>\d[\d,]*)\+\s+operations\s+across\s+(?P<paths>\d[\d,]*)\+\s+paths",
        re.IGNORECASE,
    ),
]

LAUNCH_READINESS_PATTERNS = [
    re.compile(r"98%\s+GA-ready", re.IGNORECASE),
    re.compile(r"98%\s*\(1 blocker:\s*external pentest\)", re.IGNORECASE),
    re.compile(r"98%\s+Production Ready", re.IGNORECASE),
    re.compile(r"only named GA blocker", re.IGNORECASE),
    re.compile(
        r"pending only an external vendor-dependent milestone before public launch", re.IGNORECASE
    ),
    re.compile(r"\|\s*\*\*OVERALL\*\*\s*\|\s*\*\*98%\*\*\s*\|\s*\*\*GA Ready\*\*", re.IGNORECASE),
]


def _file_age_days(path: Path) -> int | None:
    """Get age of file in days based on content date markers or mtime."""
    if not path.exists():
        return None
    # Try to find last_updated or Generated date in content
    content = path.read_text(encoding="utf-8", errors="replace")
    for pattern in [
        r'last_updated:\s*"?(\d{4}-\d{2}-\d{2})"?',
        r"Last updated:\s*(\d{4}-\d{2}-\d{2})",
        r"Generated:\s*(\d{4}-\d{2}-\d{2})",
        r"Updated:\s*(\d{4}-\d{2}-\d{2})",
    ]:
        m = re.search(pattern, content)
        if m:
            try:
                d = date.fromisoformat(m.group(1))
                return (date.today() - d).days
            except ValueError:
                pass
    # Fall back to file mtime
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime).days


def _count_pattern(path: Path, pattern: str) -> int:
    """Count occurrences of a pattern in a file."""
    if not path.exists():
        return 0
    content = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(pattern, content))


def _extract_checklist_stats(path: Path) -> dict:
    """Extract completed/total from a markdown checklist."""
    if not path.exists():
        return {"complete": 0, "total": 0}
    content = path.read_text(encoding="utf-8", errors="replace")
    checked = len(re.findall(r"- \[x\]", content, re.IGNORECASE))
    unchecked = len(re.findall(r"- \[ \]", content))
    return {"complete": checked, "total": checked + unchecked}


def _check_capability_matrix_freshness() -> list[dict]:
    """Check if capability matrix is up to date with YAML source."""
    findings = []

    if not CAPABILITY_YAML.exists():
        findings.append(
            {
                "severity": "critical",
                "source": "capability_surfaces.yaml",
                "message": "Capability surfaces YAML not found",
            }
        )
        return findings

    yaml_age = _file_age_days(CAPABILITY_YAML)
    matrix_age = _file_age_days(CAPABILITY_MATRIX)

    if yaml_age is not None and matrix_age is not None and matrix_age > yaml_age + 7:
        findings.append(
            {
                "severity": "warning",
                "source": "CAPABILITY_MATRIX.md",
                "message": f"Matrix ({matrix_age}d old) is significantly older than YAML source ({yaml_age}d old). Run: python scripts/generate_capability_matrix.py",
            }
        )

    # Check if generated matrix matches
    try:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_capability_matrix_sync.py")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            findings.append(
                {
                    "severity": "critical",
                    "source": "CAPABILITY_MATRIX.md",
                    "message": "Matrix is out of sync with YAML. Run: python scripts/generate_capability_matrix.py",
                }
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        findings.append(
            {
                "severity": "warning",
                "source": "check_capability_matrix_sync.py",
                "message": "Could not run matrix sync check",
            }
        )

    return findings


def _check_ga_checklist() -> list[dict]:
    """Check GA checklist for completion and blockers."""
    findings = []

    if not GA_CHECKLIST.exists():
        findings.append(
            {
                "severity": "warning",
                "source": "GA_CHECKLIST.md",
                "message": "GA checklist not found",
            }
        )
        return findings

    stats = _extract_checklist_stats(GA_CHECKLIST)
    age = _file_age_days(GA_CHECKLIST)

    if stats["total"] > 0:
        completion = stats["complete"] / stats["total"] * 100
        if completion < 100 and age and age > 14:
            findings.append(
                {
                    "severity": "warning",
                    "source": "GA_CHECKLIST.md",
                    "message": f"GA checklist {completion:.0f}% complete ({stats['complete']}/{stats['total']}) and {age}d since last update",
                }
            )

    # Check for explicit blockers
    content = GA_CHECKLIST.read_text(encoding="utf-8", errors="replace")
    blocker_count = len(re.findall(r"(?i)blocker|blocked|blocking", content))
    if blocker_count > 0:
        findings.append(
            {
                "severity": "info",
                "source": "GA_CHECKLIST.md",
                "message": f"GA checklist references {blocker_count} blocker mentions",
            }
        )

    return findings


def _check_connector_status() -> list[dict]:
    """Check connector status for stubs and beta counts."""
    findings = []

    if not CONNECTOR_STATUS.exists():
        return findings

    content = CONNECTOR_STATUS.read_text(encoding="utf-8", errors="replace")
    # Prefer explicit summary counts when present to avoid false positives from
    # status-definition prose ("Stub | Definition", etc.).
    prod_match = re.search(r"(?im)^\s*-\s*\*\*Production\*\*:\s*(\d+)\s+connectors", content)
    beta_match = re.search(r"(?im)^\s*-\s*\*\*Beta\*\*:\s*(\d+)\s+connectors", content)
    stub_match = re.search(r"(?im)^\s*-\s*\*\*Stub\*\*:\s*(\d+)\s+connectors", content)

    if prod_match and beta_match and stub_match:
        prod_count = int(prod_match.group(1))
        beta_count = int(beta_match.group(1))
        stub_count = int(stub_match.group(1))
    else:
        # Fallback heuristic for non-standard connector status files.
        stub_count = len(re.findall(r"(?i)\bstub\b", content))
        beta_count = len(re.findall(r"(?i)\bbeta\b", content))
        prod_count = len(re.findall(r"(?i)\bproduction\b", content))

    if stub_count > 0:
        findings.append(
            {
                "severity": "warning",
                "source": "connectors/STATUS.md",
                "message": f"Connector status has {stub_count} stub references (target: 0)",
            }
        )

    findings.append(
        {
            "severity": "info",
            "source": "connectors/STATUS.md",
            "message": f"Connectors: ~{prod_count} production, ~{beta_count} beta, ~{stub_count} stub mentions",
        }
    )

    return findings


def _extract_openapi_counts() -> tuple[int, int] | None:
    """Return (paths, operations) from the generated OpenAPI spec."""
    if not OPENAPI_GENERATED.exists():
        return None

    try:
        spec = json.loads(OPENAPI_GENERATED.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    paths = spec.get("paths", {})
    operations = 0
    valid_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    for path_item in paths.values():
        if isinstance(path_item, dict):
            operations += sum(1 for method in path_item if method.lower() in valid_methods)
    return len(paths), operations


def _check_api_metric_claims() -> list[dict]:
    """Fail when launch/status docs overstate OpenAPI path or operation counts."""
    findings = []
    counts = _extract_openapi_counts()
    if counts is None:
        findings.append(
            {
                "severity": "warning",
                "source": "docs/api/openapi_generated.json",
                "message": "Could not load generated OpenAPI counts for reconciliation",
            }
        )
        return findings

    actual_paths, actual_operations = counts

    for path, label in API_METRIC_DOCS:
        if not path.exists():
            continue

        content = path.read_text(encoding="utf-8", errors="replace")
        seen_spans: set[tuple[int, int]] = set()

        for pattern in API_CLAIM_PATTERNS:
            for match in pattern.finditer(content):
                span = match.span()
                if span in seen_spans:
                    continue
                seen_spans.add(span)

                ops_floor = int(match.group("ops").replace(",", ""))
                paths_group = match.groupdict().get("paths")
                paths_floor = int(paths_group.replace(",", "")) if paths_group else None

                if ops_floor > actual_operations or (
                    paths_floor is not None and paths_floor > actual_paths
                ):
                    excerpt = " ".join(match.group(0).split())
                    findings.append(
                        {
                            "severity": "critical",
                            "source": label,
                            "message": (
                                f"OpenAPI claim '{excerpt}' exceeds generated counts "
                                f"(actual: {actual_operations} operations across {actual_paths} paths)"
                            ),
                        }
                    )

    findings.append(
        {
            "severity": "info",
            "source": "docs/api/openapi_generated.json",
            "message": f"Generated OpenAPI counts: {actual_operations} operations across {actual_paths} paths",
        }
    )
    return findings


def _find_explicit_placeholder_connectors() -> list[Path]:
    """Return connector files that explicitly declare themselves placeholders."""
    placeholder_files: list[Path] = []
    if not CONNECTOR_ROOT.exists():
        return placeholder_files

    marker = re.compile(r"\bthis connector is a placeholder\b", re.IGNORECASE)
    for path in CONNECTOR_ROOT.rglob("*.py"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker.search(content):
            placeholder_files.append(path)
    return sorted(placeholder_files)


def _check_connector_placeholder_drift() -> list[dict]:
    """Cross-check explicit placeholder connectors against connector status docs."""
    findings = []
    if not CONNECTOR_STATUS.exists():
        return findings

    placeholder_files = _find_explicit_placeholder_connectors()
    if not placeholder_files:
        return findings

    content = CONNECTOR_STATUS.read_text(encoding="utf-8", errors="replace")
    stub_match = re.search(r"(?im)^\s*-\s*\*\*Stub\*\*:\s*(\d+)\s+connectors", content)
    documented_stub_count = int(stub_match.group(1)) if stub_match else 0

    if documented_stub_count < len(placeholder_files):
        findings.append(
            {
                "severity": "critical",
                "source": "connectors/STATUS.md",
                "message": (
                    f"Connector status documents {documented_stub_count} stub connectors, but "
                    f"{len(placeholder_files)} explicit placeholder connectors exist in code: "
                    + ", ".join(str(p.relative_to(CONNECTOR_ROOT)) for p in placeholder_files)
                ),
            }
        )

    for path in placeholder_files:
        rel = str(path.relative_to(CONNECTOR_ROOT))
        if re.search(rf"\(`{re.escape(rel)}`\)\s*\|\s*Production\s*\|", content):
            findings.append(
                {
                    "severity": "critical",
                    "source": "connectors/STATUS.md",
                    "message": f"Connector `{rel}` is listed as Production but explicitly declares itself a placeholder",
                }
            )

    return findings


def _check_launch_readiness_claims() -> list[dict]:
    """Block overconfident GA-readiness messaging in monitored docs."""
    findings = []
    for path, label in LAUNCH_READINESS_DOCS:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for pattern in LAUNCH_READINESS_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            findings.append(
                {
                    "severity": "critical",
                    "source": label,
                    "message": (
                        f"Launch-readiness claim '{match.group(0)}' is not allowed in current-source docs. "
                        "Use evidence-backed wording instead of single-blocker / percentage-ready messaging."
                    ),
                }
            )
            break
    return findings


def _check_staleness() -> list[dict]:
    """Check all status docs for staleness."""
    findings = []
    STALE_THRESHOLD_DAYS = 30

    docs_to_check = [
        (CAPABILITY_MATRIX, "CAPABILITY_MATRIX.md"),
        (GA_CHECKLIST, "GA_CHECKLIST.md"),
        (STATUS_DOC, "STATUS.md"),
        (ROADMAP, "ROADMAP.md"),
        (CONNECTOR_STATUS, "connectors/STATUS.md"),
    ]

    for path, label in docs_to_check:
        if not path.exists():
            continue
        age = _file_age_days(path)
        if age is not None and age > STALE_THRESHOLD_DAYS:
            findings.append(
                {
                    "severity": "warning",
                    "source": label,
                    "message": f"Document is {age} days old (threshold: {STALE_THRESHOLD_DAYS}d)",
                }
            )

    return findings


def reconcile(strict: bool = False) -> dict:
    """Run all reconciliation checks and return report."""
    findings = []
    findings.extend(_check_capability_matrix_freshness())
    findings.extend(_check_ga_checklist())
    findings.extend(_check_connector_status())
    findings.extend(_check_api_metric_claims())
    findings.extend(_check_connector_placeholder_drift())
    findings.extend(_check_launch_readiness_claims())
    findings.extend(_check_staleness())

    critical = [f for f in findings if f["severity"] == "critical"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    info = [f for f in findings if f["severity"] == "info"]

    report = {
        "generated": datetime.now().isoformat(),
        "findings": findings,
        "summary": {
            "critical": len(critical),
            "warning": len(warnings),
            "info": len(info),
            "total": len(findings),
        },
        "pass": len(critical) == 0 if strict else True,
    }

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile status docs for drift")
    parser.add_argument("--strict", action="store_true", help="Fail on critical findings")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--output", type=str, help="Write report to file")
    args = parser.parse_args()

    report = reconcile(strict=args.strict)

    if args.json:
        output = json.dumps(report, indent=2)
    else:
        lines = [
            "# Status Document Reconciliation Report",
            f"Generated: {report['generated'][:10]}",
            "",
            f"## Summary: {report['summary']['critical']} critical, "
            f"{report['summary']['warning']} warnings, {report['summary']['info']} info",
            "",
        ]

        for severity in ["critical", "warning", "info"]:
            items = [f for f in report["findings"] if f["severity"] == severity]
            if items:
                lines.append(f"### {severity.upper()} ({len(items)})")
                lines.append("")
                for f in items:
                    marker = {"critical": "!!", "warning": "!", "info": "-"}.get(severity, "-")
                    lines.append(f"  {marker} [{f['source']}] {f['message']}")
                lines.append("")

        if report["pass"]:
            lines.append("Result: PASS")
        else:
            lines.append("Result: FAIL (critical findings detected)")

        output = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)

    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
