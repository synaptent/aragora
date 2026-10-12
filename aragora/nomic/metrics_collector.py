"""Metrics collection for self-improvement measurement.

Collects baseline and post-improvement metrics to objectively measure
whether orchestration cycles actually improved the codebase.

Supports:
- Test suite metrics (pass/fail/skip counts, coverage)
- Code quality metrics (lint errors, type errors)
- Codebase metrics (file counts, line counts)
- Custom metrics via pluggable collectors

Usage:
    collector = MetricsCollector()
    baseline = await collector.collect_baseline(goal)
    # ... run improvement ...
    after = await collector.collect_after(goal)
    delta = collector.compare(baseline, after)
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """A point-in-time snapshot of codebase metrics."""

    timestamp: float = 0.0

    # Test metrics
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    tests_errors: int = 0
    test_coverage: float | None = None  # 0.0-1.0

    # Code quality
    lint_errors: int = 0
    type_errors: int = 0

    # Codebase size (scoped to goal's file_scope if available)
    files_count: int = 0
    total_lines: int = 0

    # Custom metrics from success_criteria evaluation
    custom: dict[str, float] = field(default_factory=dict)

    # Collection metadata
    collection_errors: list[str] = field(default_factory=list)
    collection_duration_seconds: float = 0.0

    @property
    def tests_total(self) -> int:
        return self.tests_passed + self.tests_failed + self.tests_skipped + self.tests_errors

    @property
    def test_pass_rate(self) -> float:
        total = self.tests_passed + self.tests_failed + self.tests_errors
        if total == 0:
            return 0.0
        return self.tests_passed / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_skipped": self.tests_skipped,
            "tests_errors": self.tests_errors,
            "test_coverage": self.test_coverage,
            "lint_errors": self.lint_errors,
            "type_errors": self.type_errors,
            "files_count": self.files_count,
            "total_lines": self.total_lines,
            "custom": self.custom,
            "collection_errors": self.collection_errors,
            "collection_duration_seconds": self.collection_duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricSnapshot:
        return cls(
            timestamp=data.get("timestamp", 0.0),
            tests_passed=data.get("tests_passed", 0),
            tests_failed=data.get("tests_failed", 0),
            tests_skipped=data.get("tests_skipped", 0),
            tests_errors=data.get("tests_errors", 0),
            test_coverage=data.get("test_coverage"),
            lint_errors=data.get("lint_errors", 0),
            type_errors=data.get("type_errors", 0),
            files_count=data.get("files_count", 0),
            total_lines=data.get("total_lines", 0),
            custom=data.get("custom", {}),
            collection_errors=data.get("collection_errors", []),
            collection_duration_seconds=data.get("collection_duration_seconds", 0.0),
        )


@dataclass
class MetricsDelta:
    """Comparison between baseline and after metrics."""

    baseline: MetricSnapshot
    after: MetricSnapshot

    # Deltas (positive = improvement)
    tests_passed_delta: int = 0
    tests_failed_delta: int = 0  # Negative = improvement (fewer failures)
    test_pass_rate_delta: float = 0.0
    test_coverage_delta: float | None = None
    lint_errors_delta: int = 0  # Negative = improvement
    type_errors_delta: int = 0  # Negative = improvement
    custom_deltas: dict[str, float] = field(default_factory=dict)

    # Overall assessment
    improved: bool = False
    improvement_score: float = 0.0  # 0.0-1.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "after": self.after.to_dict(),
            "tests_passed_delta": self.tests_passed_delta,
            "tests_failed_delta": self.tests_failed_delta,
            "test_pass_rate_delta": self.test_pass_rate_delta,
            "test_coverage_delta": self.test_coverage_delta,
            "lint_errors_delta": self.lint_errors_delta,
            "type_errors_delta": self.type_errors_delta,
            "custom_deltas": self.custom_deltas,
            "improved": self.improved,
            "improvement_score": self.improvement_score,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricsDelta:
        return cls(
            baseline=MetricSnapshot.from_dict(data.get("baseline", {})),
            after=MetricSnapshot.from_dict(data.get("after", {})),
            tests_passed_delta=data.get("tests_passed_delta", 0),
            tests_failed_delta=data.get("tests_failed_delta", 0),
            test_pass_rate_delta=data.get("test_pass_rate_delta", 0.0),
            test_coverage_delta=data.get("test_coverage_delta"),
            lint_errors_delta=data.get("lint_errors_delta", 0),
            type_errors_delta=data.get("type_errors_delta", 0),
            custom_deltas=data.get("custom_deltas", {}),
            improved=data.get("improved", False),
            improvement_score=data.get("improvement_score", 0.0),
            summary=data.get("summary", ""),
        )


@dataclass
class MetricsCollectorConfig:
    """Configuration for metrics collection."""

    # Test collection
    test_command: str = "pytest"
    test_args: list[str] = field(default_factory=lambda: ["-x", "-q", "--tb=no"])
    test_timeout: int = 300  # seconds
    collect_coverage: bool = False

    # Lint collection
    lint_command: str = "ruff"
    lint_args: list[str] = field(default_factory=lambda: ["check", "--quiet"])
    lint_timeout: int = 60

    # Working directory (defaults to cwd)
    working_dir: str | None = None

    # Scope test collection to specific directories
    test_scope_dirs: list[str] = field(default_factory=list)


class MetricsCollector:
    """Collects codebase metrics before and after self-improvement runs.

    Provides objective measurement of whether improvements actually improved things.
    """

    def __init__(self, config: MetricsCollectorConfig | None = None):
        self.config = config or MetricsCollectorConfig()
        self._working_dir = Path(self.config.working_dir) if self.config.working_dir else Path.cwd()

    async def collect_baseline(
        self,
        goal: str,
        file_scope: list[str] | None = None,
    ) -> MetricSnapshot:
        """Collect pre-improvement baseline metrics.

        Args:
            goal: The improvement goal (used to scope metrics)
            file_scope: Optional list of files/dirs to scope metrics to
        """
        return await self._collect(goal, file_scope, label="baseline")

    async def collect_after(
        self,
        goal: str,
        file_scope: list[str] | None = None,
    ) -> MetricSnapshot:
        """Collect post-improvement metrics."""
        return await self._collect(goal, file_scope, label="after")

    def compare(self, baseline: MetricSnapshot, after: MetricSnapshot) -> MetricsDelta:
        """Compare baseline and after snapshots to compute improvement delta."""
        delta = MetricsDelta(baseline=baseline, after=after)

        # Test deltas
        delta.tests_passed_delta = after.tests_passed - baseline.tests_passed
        delta.tests_failed_delta = after.tests_failed - baseline.tests_failed
        delta.test_pass_rate_delta = after.test_pass_rate - baseline.test_pass_rate

        if baseline.test_coverage is not None and after.test_coverage is not None:
            delta.test_coverage_delta = after.test_coverage - baseline.test_coverage

        # Quality deltas (negative = improvement)
        delta.lint_errors_delta = after.lint_errors - baseline.lint_errors
        delta.type_errors_delta = after.type_errors - baseline.type_errors

        # Custom metric deltas
        all_keys = set(baseline.custom) | set(after.custom)
        for key in all_keys:
            before_val = baseline.custom.get(key, 0.0)
            after_val = after.custom.get(key, 0.0)
            delta.custom_deltas[key] = after_val - before_val

        # Compute improvement score (0.0-1.0)
        signals: list[float] = []

        # More tests passing is good
        if baseline.tests_total > 0:
            signals.append(min(delta.test_pass_rate_delta * 5.0, 1.0))

        # Fewer failures is good
        if baseline.tests_failed > 0 and delta.tests_failed_delta < 0:
            signals.append(min(abs(delta.tests_failed_delta) / max(baseline.tests_failed, 1), 1.0))

        # Coverage improvement is good
        if delta.test_coverage_delta is not None and delta.test_coverage_delta > 0:
            signals.append(min(delta.test_coverage_delta * 10.0, 1.0))

        # Fewer lint errors is good
        if baseline.lint_errors > 0 and delta.lint_errors_delta < 0:
            signals.append(min(abs(delta.lint_errors_delta) / max(baseline.lint_errors, 1), 1.0))

        # No regressions is baseline-good
        no_regression = (
            delta.tests_failed_delta <= 0
            and delta.lint_errors_delta <= 0
            and delta.type_errors_delta <= 0
        )

        if signals:
            delta.improvement_score = sum(signals) / len(signals)
        elif no_regression:
            delta.improvement_score = 0.5  # No regression, no measurable improvement
        else:
            delta.improvement_score = 0.0

        delta.improved = delta.improvement_score > 0.3 and no_regression

        # Build summary
        parts = []
        if delta.tests_passed_delta > 0:
            parts.append(f"+{delta.tests_passed_delta} tests passing")
        if delta.tests_failed_delta < 0:
            parts.append(f"{delta.tests_failed_delta} test failures")
        if delta.test_coverage_delta is not None and delta.test_coverage_delta > 0:
            parts.append(f"+{delta.test_coverage_delta:.1%} coverage")
        if delta.lint_errors_delta < 0:
            parts.append(f"{delta.lint_errors_delta} lint errors")
        if not parts:
            if no_regression:
                parts.append("no regressions detected")
            else:
                regressions = []
                if delta.tests_failed_delta > 0:
                    regressions.append(f"+{delta.tests_failed_delta} test failures")
                if delta.lint_errors_delta > 0:
                    regressions.append(f"+{delta.lint_errors_delta} lint errors")
                parts.append(f"regressions: {', '.join(regressions)}")

        delta.summary = "; ".join(parts)

        return delta

    def check_success_criteria(
        self,
        after: MetricSnapshot,
        criteria: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Check if metrics meet success criteria.

        Args:
            after: Post-improvement metrics
            criteria: Dict of criterion_name → target (e.g., {"test_pass_rate": ">0.95"})

        Returns:
            Tuple of (all_met, list of unmet criteria descriptions)
        """
        unmet: list[str] = []

        for criterion, target in criteria.items():
            actual = self._get_metric_value(after, criterion)
            if actual is None:
                unmet.append(f"{criterion}: metric not available")
                continue

            if isinstance(target, str):
                met = self._evaluate_target(actual, target)
            elif isinstance(target, (int, float)):
                met = actual >= target
            else:
                continue

            if not met:
                unmet.append(f"{criterion}: {actual} does not meet target {target}")

        return len(unmet) == 0, unmet

    # --- Internal ---

    async def _collect(
        self,
        goal: str,
        file_scope: list[str] | None,
        label: str,
    ) -> MetricSnapshot:
        """Collect all metrics."""
        start = time.time()
        snapshot = MetricSnapshot(timestamp=start)

        # Collect test metrics
        try:
            self._collect_test_metrics(snapshot, file_scope)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            snapshot.collection_errors.append(f"test_collection: {e}")
            logger.debug("metrics_collection_error label=%s phase=tests: %s", label, e)

        # Collect lint metrics
        try:
            self._collect_lint_metrics(snapshot, file_scope)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            snapshot.collection_errors.append(f"lint_collection: {e}")
            logger.debug("metrics_collection_error label=%s phase=lint: %s", label, e)

        # Collect codebase size
        try:
            self._collect_size_metrics(snapshot, file_scope)
        except (OSError, ValueError) as e:
            snapshot.collection_errors.append(f"size_collection: {e}")
            logger.debug("metrics_collection_error label=%s phase=size: %s", label, e)

        snapshot.collection_duration_seconds = time.time() - start
        logger.info(
            "metrics_collected label=%s tests=%d/%d lint=%d duration=%.1fs",
            label,
            snapshot.tests_passed,
            snapshot.tests_total,
            snapshot.lint_errors,
            snapshot.collection_duration_seconds,
        )
        return snapshot

    def _collect_test_metrics(
        self,
        snapshot: MetricSnapshot,
        file_scope: list[str] | None,
    ) -> None:
        """Run pytest and collect results."""
        cmd = [self.config.test_command] + list(self.config.test_args)

        # Scope to specific test directories
        scope_dirs = self.config.test_scope_dirs
        if file_scope:
            # Infer test directories from file scope
            for f in file_scope:
                test_path = self._infer_test_path(f)
                if test_path and test_path not in scope_dirs:
                    scope_dirs.append(test_path)

        if scope_dirs:
            cmd.extend(scope_dirs)

        result = subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.test_timeout,
            cwd=self._working_dir,
        )

        # Parse pytest output for counts
        output = result.stdout + result.stderr
        self._parse_pytest_output(output, snapshot)

    def _collect_lint_metrics(
        self,
        snapshot: MetricSnapshot,
        file_scope: list[str] | None,
    ) -> None:
        """Run linter and count errors."""
        cmd = [self.config.lint_command] + list(self.config.lint_args)

        if file_scope:
            # Scope lint to specific files
            existing = [f for f in file_scope if (self._working_dir / f).exists()]
            if existing:
                cmd.extend(existing[:50])  # Limit to avoid arg overflow

        result = subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.lint_timeout,
            cwd=self._working_dir,
        )

        # Count lint errors (one per line of output)
        if result.stdout.strip():
            snapshot.lint_errors = len(result.stdout.strip().splitlines())
        else:
            snapshot.lint_errors = 0

    def _collect_size_metrics(
        self,
        snapshot: MetricSnapshot,
        file_scope: list[str] | None,
    ) -> None:
        """Count files and lines in scope."""
        if file_scope:
            paths = [self._working_dir / f for f in file_scope]
        else:
            paths = [self._working_dir / "aragora"]

        total_files = 0
        total_lines = 0
        for path in paths:
            if path.is_file() and path.suffix == ".py":
                total_files += 1
                total_lines += sum(1 for _ in path.open())
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    total_files += 1
                    try:
                        total_lines += sum(1 for _ in py_file.open())
                    except OSError:
                        pass

        snapshot.files_count = total_files
        snapshot.total_lines = total_lines

    def _parse_pytest_output(self, output: str, snapshot: MetricSnapshot) -> None:
        """Parse pytest summary line for test counts."""
        import re

        # Match patterns like "291 passed, 1 failed, 3 skipped"
        passed_match = re.search(r"(\d+) passed", output)
        failed_match = re.search(r"(\d+) failed", output)
        skipped_match = re.search(r"(\d+) skipped", output)
        error_match = re.search(r"(\d+) error", output)

        if passed_match:
            snapshot.tests_passed = int(passed_match.group(1))
        if failed_match:
            snapshot.tests_failed = int(failed_match.group(1))
        if skipped_match:
            snapshot.tests_skipped = int(skipped_match.group(1))
        if error_match:
            snapshot.tests_errors = int(error_match.group(1))

        # Parse coverage if present
        coverage_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
        if coverage_match:
            snapshot.test_coverage = int(coverage_match.group(1)) / 100.0

    def _infer_test_path(self, file_path: str) -> str | None:
        """Infer test directory from a source file path."""
        # aragora/foo/bar.py → tests/foo/
        if file_path.startswith("aragora/"):
            parts = file_path.split("/")
            if len(parts) >= 2:
                test_dir = f"tests/{parts[1]}"
                if (self._working_dir / test_dir).exists():
                    return test_dir
        return None

    def _get_metric_value(self, snapshot: MetricSnapshot, criterion: str) -> float | None:
        """Get a metric value by name."""
        mapping: dict[str, float | None] = {
            "test_pass_rate": snapshot.test_pass_rate,
            "tests_passed": float(snapshot.tests_passed),
            "tests_failed": float(snapshot.tests_failed),
            "test_coverage": snapshot.test_coverage,
            "lint_errors": float(snapshot.lint_errors),
            "type_errors": float(snapshot.type_errors),
            "files_count": float(snapshot.files_count),
            "total_lines": float(snapshot.total_lines),
        }
        if criterion in mapping:
            return mapping[criterion]
        return snapshot.custom.get(criterion)

    @staticmethod
    def _evaluate_target(actual: float, target: str) -> bool:
        """Evaluate a target like '>0.95' or '==0' or '<=10'."""
        import re

        match = re.match(r"([<>=!]+)\s*([\d.]+)", target)
        if not match:
            return False
        op, val = match.group(1), float(match.group(2))
        ops = {
            ">": actual > val,
            ">=": actual >= val,
            "<": actual < val,
            "<=": actual <= val,
            "==": actual == val,
            "!=": actual != val,
        }
        return ops.get(op, False)
