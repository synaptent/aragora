"""Strategic Codebase Scanner — deep assessment for self-improvement planning.

Scans the codebase to identify untested modules, complexity hotspots,
stale TODOs, integration gaps, and other strategic findings that inform
what the Nomic Loop should work on next.

Usage:
    scanner = StrategicScanner(repo_path=Path.cwd())
    assessment = scanner.scan(objective="improve test coverage")
    for f in assessment.findings[:5]:
        print(f"{f.severity}: {f.description} ({f.file_path})")

The scanner uses only stdlib tools (pathlib, subprocess, ast) so it
works in any environment without external dependencies.
"""

from __future__ import annotations

import ast
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Categories for findings
CATEGORY_UNTESTED = "untested"
CATEGORY_COMPLEX = "complex"
CATEGORY_STALE = "stale"
CATEGORY_INTEGRATION_GAP = "integration_gap"
CATEGORY_DEAD_CODE = "dead_code"

# Severity levels
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# Thresholds
LOC_THRESHOLD = 500
INDENT_DEPTH_THRESHOLD = 6
FUNCTION_COUNT_THRESHOLD = 20
STALE_DAYS_THRESHOLD = 60


@dataclass
class StrategicFinding:
    """A single finding from the strategic codebase scan."""

    category: str  # "untested", "complex", "stale", "integration_gap", "dead_code"
    severity: str  # "critical", "high", "medium", "low"
    file_path: str
    description: str
    evidence: str  # Concrete metric or code reference
    suggested_action: str
    track: str  # Maps to Track enum (SME, DEVELOPER, CORE, etc.)


@dataclass
class StrategicAssessment:
    """Result of a full strategic codebase scan."""

    findings: list[StrategicFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    focus_areas: list[str] = field(default_factory=list)
    objective: str = ""
    timestamp: float = 0.0


def _track_for_path(rel_path: str) -> str:
    """Map a file path to a development track."""
    parts = rel_path.split("/")
    if len(parts) < 2:
        return "core"

    top_dir = parts[1] if parts[0] == "aragora" else parts[0]

    track_map = {
        "debate": "core",
        "agents": "core",
        "ranking": "core",
        "consensus": "core",
        "convergence": "core",
        "server": "developer",
        "cli": "developer",
        "mcp": "developer",
        "sdk": "developer",
        "gateway": "developer",
        "connectors": "developer",
        "integrations": "developer",
        "auth": "security",
        "security": "security",
        "rbac": "security",
        "privacy": "security",
        "compliance": "security",
        "billing": "sme",
        "notifications": "sme",
        "audience": "sme",
        "skills": "sme",
        "ops": "self_hosted",
        "backup": "self_hosted",
        "storage": "self_hosted",
        "control_plane": "self_hosted",
        "tests": "qa",
        "nomic": "core",
    }
    return track_map.get(top_dir, "developer")


class StrategicScanner:
    """Scans the codebase for strategic improvement opportunities.

    Uses only pathlib, subprocess (git), and ast — no external deps.
    """

    def __init__(self, repo_path: Path | str | None = None):
        self._repo_path = Path(repo_path) if repo_path else Path.cwd()
        self._src_root = self._repo_path / "aragora"
        self._test_root = self._repo_path / "tests"

    def scan(self, objective: str = "") -> StrategicAssessment:
        """Run all analysis passes and produce a strategic assessment.

        Args:
            objective: Optional focus objective for ranking (e.g. "improve test coverage").

        Returns:
            StrategicAssessment with ranked findings and focus areas.
        """
        findings: list[StrategicFinding] = []

        findings.extend(self._find_untested_modules())
        findings.extend(self._find_complexity_hotspots())
        findings.extend(self._find_stale_todos())
        findings.extend(self._find_integration_gaps())

        ranked = self._rank_findings(findings, objective)

        # Compute metrics
        all_modules = list(self._src_root.rglob("*.py"))
        test_files = list(self._test_root.rglob("*.py")) if self._test_root.exists() else []
        untested_count = sum(1 for f in ranked if f.category == CATEGORY_UNTESTED)
        total_modules = len(all_modules)
        tested_pct = (
            round((total_modules - untested_count) / total_modules * 100, 1)
            if total_modules > 0
            else 0.0
        )

        complexity_findings = [f for f in ranked if f.category == CATEGORY_COMPLEX]
        avg_complexity = round(len(complexity_findings) / max(total_modules, 1) * 100, 1)
        stale_count = sum(1 for f in ranked if f.category == CATEGORY_STALE)

        findings_by_cat: dict[str, int] = {}
        for f in ranked:
            findings_by_cat[f.category] = findings_by_cat.get(f.category, 0) + 1
        metrics = {
            "total_modules": total_modules,
            "total_test_files": len(test_files),
            "tested_pct": tested_pct,
            "avg_complexity": avg_complexity,
            "stale_count": stale_count,
            "findings_by_category": findings_by_cat,
        }

        # Top 5 focus areas: group by track + category, pick highest-severity clusters
        focus_areas = self._compute_focus_areas(ranked)

        return StrategicAssessment(
            findings=ranked,
            metrics=metrics,
            focus_areas=focus_areas[:5],
            objective=objective,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Analysis passes
    # ------------------------------------------------------------------

    def _find_untested_modules(self) -> list[StrategicFinding]:
        """Find source modules with no corresponding test file."""
        findings: list[StrategicFinding] = []
        if not self._src_root.exists():
            return findings

        test_stems: set[str] = set()
        if self._test_root.exists():
            for tp in self._test_root.rglob("test_*.py"):
                # test_consensus.py -> consensus
                stem = tp.stem.removeprefix("test_")
                test_stems.add(stem)

        for src in self._src_root.rglob("*.py"):
            if src.name.startswith("__"):
                continue
            rel = str(src.relative_to(self._repo_path))
            stem = src.stem
            if stem not in test_stems:
                loc = self._count_lines(src)
                severity = SEVERITY_HIGH if loc > 200 else SEVERITY_MEDIUM
                findings.append(
                    StrategicFinding(
                        category=CATEGORY_UNTESTED,
                        severity=severity,
                        file_path=rel,
                        description=f"Module {stem} ({loc} LOC) has no test file",
                        evidence=f"No tests/*/test_{stem}.py found",
                        suggested_action=f"Create tests for {rel}",
                        track=_track_for_path(rel),
                    )
                )
        return findings

    def _find_complexity_hotspots(self) -> list[StrategicFinding]:
        """Find files with high LOC, deep nesting, or many functions."""
        findings: list[StrategicFinding] = []
        if not self._src_root.exists():
            return findings

        for src in self._src_root.rglob("*.py"):
            if src.name.startswith("__"):
                continue
            rel = str(src.relative_to(self._repo_path))
            try:
                content = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            loc = content.count("\n") + 1
            max_indent = self._max_indent_depth(content)
            func_count = self._count_functions(content)

            issues: list[str] = []
            if loc > LOC_THRESHOLD:
                issues.append(f"{loc} LOC (threshold {LOC_THRESHOLD})")
            if max_indent > INDENT_DEPTH_THRESHOLD:
                issues.append(f"indent depth {max_indent} (threshold {INDENT_DEPTH_THRESHOLD})")
            if func_count > FUNCTION_COUNT_THRESHOLD:
                issues.append(f"{func_count} functions (threshold {FUNCTION_COUNT_THRESHOLD})")

            if not issues:
                continue

            severity = SEVERITY_HIGH if len(issues) >= 2 else SEVERITY_MEDIUM
            if loc > LOC_THRESHOLD * 2:
                severity = SEVERITY_CRITICAL

            findings.append(
                StrategicFinding(
                    category=CATEGORY_COMPLEX,
                    severity=severity,
                    file_path=rel,
                    description=f"Complexity hotspot: {', '.join(issues)}",
                    evidence=f"LOC={loc}, indent={max_indent}, functions={func_count}",
                    suggested_action=f"Refactor {rel} — extract classes or split module",
                    track=_track_for_path(rel),
                )
            )
        return findings

    def _find_stale_todos(self) -> list[StrategicFinding]:
        """Find TODO/FIXME/HACK in files not modified recently."""
        findings: list[StrategicFinding] = []
        if not self._src_root.exists():
            return findings

        mod_times = self._git_file_mod_times()
        now = time.time()
        stale_cutoff = now - (STALE_DAYS_THRESHOLD * 86400)
        todo_pattern = re.compile(r"#\s*(TODO|FIXME|HACK)\b(.{0,80})", re.IGNORECASE)

        for src in self._src_root.rglob("*.py"):
            rel = str(src.relative_to(self._repo_path))
            last_mod = mod_times.get(rel)
            if last_mod is not None and last_mod > stale_cutoff:
                continue

            try:
                lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            for i, line in enumerate(lines, 1):
                m = todo_pattern.search(line)
                if m:
                    tag = m.group(1).upper()
                    text = m.group(2).strip().rstrip(".")
                    days_old = int((now - last_mod) / 86400) if last_mod else STALE_DAYS_THRESHOLD
                    severity = SEVERITY_HIGH if tag == "FIXME" else SEVERITY_MEDIUM
                    findings.append(
                        StrategicFinding(
                            category=CATEGORY_STALE,
                            severity=severity,
                            file_path=rel,
                            description=f"Stale {tag} ({days_old}d old): {text}",
                            evidence=f"Line {i}: {line.strip()[:120]}",
                            suggested_action=f"Resolve or remove stale {tag} in {rel}",
                            track=_track_for_path(rel),
                        )
                    )
        return findings

    def _find_integration_gaps(self) -> list[StrategicFinding]:
        """Find modules whose __init__.py exports are never imported elsewhere."""
        findings: list[StrategicFinding] = []
        if not self._src_root.exists():
            return findings

        # Collect all exported names from __init__.py files
        init_exports: dict[str, list[str]] = {}  # package_path -> [names]
        for init in self._src_root.rglob("__init__.py"):
            pkg_rel = str(init.parent.relative_to(self._repo_path))
            try:
                content = init.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Look for __all__ lists
            all_match = re.search(r"__all__\s*=\s*\[([^\]]*)\]", content, re.DOTALL)
            if all_match:
                names = re.findall(r'"([^"]+)"|\'([^\']+)\'', all_match.group(1))
                exported = [n[0] or n[1] for n in names]
                if exported:
                    init_exports[pkg_rel] = exported

        # Build a set of all import targets across the codebase
        all_imports: set[str] = set()
        for src in self._src_root.rglob("*.py"):
            if src.name == "__init__.py":
                continue
            try:
                content = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Capture 'from x import y' and 'import x'
            for m in re.finditer(r"(?:from|import)\s+([\w.]+)", content):
                all_imports.add(m.group(1))

        # Check for packages whose dotted path never appears in imports
        for pkg_path, exports in init_exports.items():
            dotted = pkg_path.replace("/", ".")
            # Check if any module imports from this package
            imported = any(dotted in imp for imp in all_imports)
            if not imported and len(exports) > 0:
                findings.append(
                    StrategicFinding(
                        category=CATEGORY_INTEGRATION_GAP,
                        severity=SEVERITY_LOW,
                        file_path=pkg_path + "/__init__.py",
                        description=(
                            f"Package {dotted} exports {len(exports)} names "
                            f"but is never imported elsewhere"
                        ),
                        evidence=f"Exports: {', '.join(exports[:5])}{'...' if len(exports) > 5 else ''}",
                        suggested_action=f"Verify {dotted} is used or remove dead package",
                        track=_track_for_path(pkg_path),
                    )
                )
        return findings

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_findings(
        self, findings: list[StrategicFinding], objective: str
    ) -> list[StrategicFinding]:
        """Rank findings by severity and keyword relevance to the objective."""
        severity_order = {
            SEVERITY_CRITICAL: 0,
            SEVERITY_HIGH: 1,
            SEVERITY_MEDIUM: 2,
            SEVERITY_LOW: 3,
        }
        objective_words = set(objective.lower().split()) if objective else set()

        def sort_key(f: StrategicFinding) -> tuple[int, int]:
            sev = severity_order.get(f.severity, 9)
            # Count keyword overlap with finding text
            finding_text = f"{f.description} {f.category} {f.track} {f.file_path}".lower()
            overlap = sum(1 for w in objective_words if w in finding_text)
            # More overlap = lower sort key = higher rank
            return (-overlap, sev)

        return sorted(findings, key=sort_key)

    # ------------------------------------------------------------------
    # Focus area computation
    # ------------------------------------------------------------------

    def _compute_focus_areas(self, findings: list[StrategicFinding]) -> list[str]:
        """Compute top focus areas from ranked findings."""
        # Group by (track, category) and count severity-weighted scores
        area_scores: dict[tuple[str, str], float] = {}
        severity_weights = {
            SEVERITY_CRITICAL: 4.0,
            SEVERITY_HIGH: 2.0,
            SEVERITY_MEDIUM: 1.0,
            SEVERITY_LOW: 0.5,
        }
        for f in findings:
            key = (f.track, f.category)
            weight = severity_weights.get(f.severity, 1.0)
            area_scores[key] = area_scores.get(key, 0.0) + weight

        sorted_areas = sorted(area_scores.items(), key=lambda x: -x[1])
        result: list[str] = []
        for (track, category), score in sorted_areas[:5]:
            count = sum(1 for f in findings if f.track == track and f.category == category)
            result.append(f"[{track}] {category}: {count} findings (score {score:.0f})")
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_lines(path: Path) -> int:
        """Count non-blank lines in a file."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return sum(1 for line in content.splitlines() if line.strip())
        except OSError:
            return 0

    @staticmethod
    def _max_indent_depth(content: str) -> int:
        """Find the maximum indentation depth (in units of 4 spaces)."""
        max_depth = 0
        for line in content.splitlines():
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(stripped)
            depth = indent // 4
            if depth > max_depth:
                max_depth = depth
        return max_depth

    @staticmethod
    def _count_functions(content: str) -> int:
        """Count function/method definitions via AST."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Fallback: count 'def ' lines
            return sum(1 for line in content.splitlines() if line.strip().startswith("def "))
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                count += 1
        return count

    def _git_file_mod_times(self) -> dict[str, float]:
        """Get last-modified timestamps for tracked files via git log."""
        result: dict[str, float] = {}
        try:
            proc = subprocess.run(
                # fixed command
                ["git", "log", "--format=%at", "--name-only", "--diff-filter=ACMR"],
                capture_output=True,
                text=True,
                cwd=str(self._repo_path),
                timeout=30,
            )
            if proc.returncode != 0:
                return result

            current_ts: float | None = None
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.isdigit():
                    current_ts = float(line)
                elif current_ts is not None and line not in result:
                    # First occurrence = most recent modification
                    result[line] = current_ts
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.debug("Git log failed, skipping stale detection")
        return result
