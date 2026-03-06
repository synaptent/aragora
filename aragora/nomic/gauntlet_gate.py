"""
Gauntlet Approval Gate for the Nomic Loop.

Runs a lightweight Gauntlet benchmark as a verification gate during
the Nomic Loop's verify phase. If the Gauntlet produces CRITICAL or HIGH
severity findings, the approval is blocked.

This gate is opt-in (disabled by default) and designed to run in a
lightweight mode -- skipping the full scenario matrix and using minimal
attack/probe rounds -- to avoid slowing down the self-improvement cycle.

Usage in autonomous orchestrator:
    orchestrator = AutonomousOrchestrator(
        enable_gauntlet_gate=True,  # existing flag
    )

Usage standalone:
    gate = GauntletApprovalGate()
    result = await gate.evaluate(
        content="The design spec or implementation diff",
        context="Additional context about the change",
    )
    if result.blocked:
        print(f"Blocked: {result.reason}")
        for f in result.blocking_findings:
            print(f"  - [{f.severity}] {f.title}")
"""

from __future__ import annotations

__all__ = [
    "GauntletApprovalGate",
    "GauntletGateConfig",
    "GauntletGateResult",
    "GauntletQualityResult",
]

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Runtime imports for Gauntlet components (optional dependency)
_GauntletRunner: Any = None
_GauntletConfig: Any = None
_AttackCategory: Any = None
_ProbeCategory: Any = None
_SeverityLevel: Any = None
_GAUNTLET_AVAILABLE = False

try:
    from aragora.gauntlet.config import AttackCategory as _AttackCategory  # noqa: N811
    from aragora.gauntlet.config import GauntletConfig as _GauntletConfig  # noqa: N811
    from aragora.gauntlet.config import ProbeCategory as _ProbeCategory  # noqa: N811
    from aragora.gauntlet.result import SeverityLevel as _SeverityLevel  # noqa: N811
    from aragora.gauntlet.runner import GauntletRunner as _GauntletRunner  # noqa: N811

    _GAUNTLET_AVAILABLE = True
except ImportError:
    pass


@dataclass
class GauntletGateConfig:
    """Configuration for the Gauntlet approval gate.

    Attributes:
        enabled: Whether the gate is active (default False).
        max_critical: Maximum number of CRITICAL findings before blocking.
            Default 0 means any critical finding blocks.
        max_high: Maximum number of HIGH findings before blocking.
            Default 0 means any high finding blocks.
        attack_rounds: Number of red-team attack rounds (1 for lightweight).
        probes_per_category: Number of probes per category (1 for lightweight).
        run_scenario_matrix: Whether to run the scenario matrix (False for lightweight).
        timeout_seconds: Maximum time for the Gauntlet run.
        agents: Agent names to use for the Gauntlet. Empty list uses defaults.
    """

    enabled: bool = False
    max_critical: int = 0
    max_high: int = 0
    attack_rounds: int = 1
    probes_per_category: int = 1
    run_scenario_matrix: bool = False
    timeout_seconds: int = 120
    agents: list[str] = field(default_factory=lambda: ["anthropic-api", "openai-api"])


@dataclass
class BlockingFinding:
    """A finding that contributed to blocking approval."""

    severity: str
    title: str
    description: str
    category: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "source": self.source,
        }


@dataclass
class GauntletGateResult:
    """Result of a Gauntlet approval gate evaluation.

    Attributes:
        blocked: Whether the gate blocked the approval.
        reason: Human-readable reason for the decision.
        critical_count: Number of CRITICAL findings.
        high_count: Number of HIGH findings.
        total_findings: Total number of findings across all severities.
        blocking_findings: List of findings that caused the block.
        gauntlet_id: ID of the Gauntlet run for traceability.
        duration_seconds: How long the Gauntlet run took.
        skipped: True if the gate was skipped (e.g., disabled or import error).
        error: Error message if the gate failed to run.
    """

    blocked: bool = False
    reason: str = ""
    critical_count: int = 0
    high_count: int = 0
    total_findings: int = 0
    blocking_findings: list[BlockingFinding] = field(default_factory=list)
    gauntlet_id: str = ""
    duration_seconds: float = 0.0
    skipped: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        """Convenience: True when the gate did not block."""
        return not self.blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "passed": self.passed,
            "reason": self.reason,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "total_findings": self.total_findings,
            "blocking_findings": [f.to_dict() for f in self.blocking_findings],
            "gauntlet_id": self.gauntlet_id,
            "duration_seconds": self.duration_seconds,
            "skipped": self.skipped,
            "error": self.error,
        }


@dataclass
class GauntletQualityResult:
    """Result of a gauntlet quality regression check.

    Attributes:
        passed: True if the score did not regress beyond the allowed threshold.
        baseline_score: The baseline robustness score that was compared against.
        current_score: The robustness score from the new gauntlet run.
        regression_pct: Percentage of regression (positive means worse).
        max_regression_pct: The configured maximum allowed regression.
        reason: Human-readable explanation.
        gauntlet_id: ID of the gauntlet run for traceability.
    """

    passed: bool = True
    baseline_score: float = 1.0
    current_score: float = 1.0
    regression_pct: float = 0.0
    max_regression_pct: float = 10.0
    reason: str = ""
    gauntlet_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "baseline_score": self.baseline_score,
            "current_score": self.current_score,
            "regression_pct": round(self.regression_pct, 2),
            "max_regression_pct": self.max_regression_pct,
            "reason": self.reason,
            "gauntlet_id": self.gauntlet_id,
        }


class GauntletApprovalGate:
    """Runs a lightweight Gauntlet benchmark as a verification gate.

    The gate creates a GauntletRunner with a minimal configuration
    (few attack rounds, minimal probes, no scenario matrix) and evaluates
    the findings against configurable thresholds.

    If the number of CRITICAL or HIGH severity findings exceeds the
    configured thresholds, the gate blocks the approval.
    """

    def __init__(self, config: GauntletGateConfig | None = None):
        self.config = config or GauntletGateConfig()

    async def evaluate(
        self,
        content: str,
        context: str = "",
    ) -> GauntletGateResult:
        """Run the Gauntlet and evaluate findings against thresholds.

        Args:
            content: The content to validate (design spec, implementation diff,
                or description of changes).
            context: Additional context for the validation.

        Returns:
            GauntletGateResult indicating whether the gate passed or blocked.
        """
        if not self.config.enabled:
            return GauntletGateResult(
                blocked=False,
                reason="Gauntlet gate disabled",
                skipped=True,
            )

        if not _GAUNTLET_AVAILABLE:
            logger.debug("Gauntlet gate skipped: gauntlet module unavailable")
            return GauntletGateResult(
                blocked=False,
                reason="Gauntlet module not available",
                skipped=True,
                error="aragora.gauntlet not installed",
            )

        # Build lightweight Gauntlet configuration
        gauntlet_config = _GauntletConfig(
            name="Nomic Loop Approval Gate",
            description="Lightweight adversarial validation for self-improvement gate",
            attack_categories=[
                _AttackCategory.SECURITY,
                _AttackCategory.LOGIC,
            ],
            attack_rounds=self.config.attack_rounds,
            attacks_per_category=2,
            probe_categories=[
                _ProbeCategory.CONTRADICTION,
                _ProbeCategory.HALLUCINATION,
            ],
            probes_per_category=self.config.probes_per_category,
            run_scenario_matrix=self.config.run_scenario_matrix,
            enable_scenario_analysis=self.config.run_scenario_matrix,
            agents=self.config.agents,
            max_agents=2,
            critical_threshold=self.config.max_critical,
            high_threshold=self.config.max_high,
            timeout_seconds=self.config.timeout_seconds,
        )

        runner = _GauntletRunner(config=gauntlet_config)

        try:
            gauntlet_result = await runner.run(
                input_content=content,
                context=context,
            )
        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.warning("Gauntlet gate run failed: %s", e)
            return GauntletGateResult(
                blocked=False,
                reason=f"Gauntlet run failed (non-blocking): {type(e).__name__}",
                skipped=True,
                error=str(e),
            )

        # Count findings by severity
        critical_count = gauntlet_result.risk_summary.critical
        high_count = gauntlet_result.risk_summary.high
        total_findings = len(gauntlet_result.vulnerabilities)

        # Collect blocking findings
        blocking_findings: list[BlockingFinding] = []
        for vuln in gauntlet_result.vulnerabilities:
            if vuln.severity in (_SeverityLevel.CRITICAL, _SeverityLevel.HIGH):
                blocking_findings.append(
                    BlockingFinding(
                        severity=vuln.severity.value,
                        title=vuln.title,
                        description=vuln.description[:300],
                        category=vuln.category,
                        source=vuln.source,
                    )
                )

        # Evaluate thresholds
        blocked = False
        reasons: list[str] = []

        if critical_count > self.config.max_critical:
            blocked = True
            reasons.append(
                f"{critical_count} CRITICAL findings (threshold: {self.config.max_critical})"
            )

        if high_count > self.config.max_high:
            blocked = True
            reasons.append(f"{high_count} HIGH findings (threshold: {self.config.max_high})")

        if blocked:
            reason = "Gauntlet gate BLOCKED: " + "; ".join(reasons)
        else:
            reason = (
                f"Gauntlet gate passed ({total_findings} total findings, "
                f"{critical_count} critical, {high_count} high)"
            )

        logger.info(
            "gauntlet_gate_result blocked=%s critical=%d high=%d total=%d",
            blocked,
            critical_count,
            high_count,
            total_findings,
        )

        return GauntletGateResult(
            blocked=blocked,
            reason=reason,
            critical_count=critical_count,
            high_count=high_count,
            total_findings=total_findings,
            blocking_findings=blocking_findings,
            gauntlet_id=gauntlet_result.gauntlet_id,
            duration_seconds=gauntlet_result.duration_seconds,
        )

    async def check_quality_regression(
        self,
        content: str,
        baseline_score: float,
        context: str = "",
        max_regression_pct: float = 10.0,
    ) -> GauntletQualityResult:
        """Run the gauntlet and reject if robustness score regresses >N% from baseline.

        This complements the severity-threshold ``evaluate()`` method with a
        *relative* quality check: even if no CRITICAL/HIGH findings exist, a
        significant drop in robustness score indicates quality regression that
        should block the change.

        Args:
            content: The content to validate.
            baseline_score: Previous robustness score (0-1) to compare against.
            context: Additional context for the validation.
            max_regression_pct: Maximum allowed regression percentage (default 10%).

        Returns:
            GauntletQualityResult with pass/fail and regression details.
        """
        if not self.config.enabled:
            return GauntletQualityResult(
                passed=True,
                baseline_score=baseline_score,
                current_score=baseline_score,
                reason="Gauntlet gate disabled — quality check skipped",
            )

        if not _GAUNTLET_AVAILABLE:
            logger.debug("Gauntlet quality check skipped: gauntlet module unavailable")
            return GauntletQualityResult(
                passed=True,
                baseline_score=baseline_score,
                current_score=baseline_score,
                reason="Gauntlet module not available — quality check skipped",
            )

        # Build lightweight Gauntlet configuration (same as evaluate)
        gauntlet_config = _GauntletConfig(
            name="Nomic Loop Quality Regression Check",
            description="Quality regression check for self-improvement gate",
            attack_categories=[
                _AttackCategory.SECURITY,
                _AttackCategory.LOGIC,
            ],
            attack_rounds=self.config.attack_rounds,
            attacks_per_category=2,
            probe_categories=[
                _ProbeCategory.CONTRADICTION,
                _ProbeCategory.HALLUCINATION,
            ],
            probes_per_category=self.config.probes_per_category,
            run_scenario_matrix=self.config.run_scenario_matrix,
            enable_scenario_analysis=self.config.run_scenario_matrix,
            agents=self.config.agents,
            max_agents=2,
            critical_threshold=self.config.max_critical,
            high_threshold=self.config.max_high,
            timeout_seconds=self.config.timeout_seconds,
        )

        runner = _GauntletRunner(config=gauntlet_config)

        try:
            gauntlet_result = await runner.run(
                input_content=content,
                context=context,
            )
        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.warning("Gauntlet quality check failed: %s", e)
            return GauntletQualityResult(
                passed=True,
                baseline_score=baseline_score,
                current_score=baseline_score,
                reason=f"Gauntlet run failed (non-blocking): {type(e).__name__}",
            )

        current_score = gauntlet_result.attack_summary.robustness_score

        # Calculate regression percentage relative to baseline
        if baseline_score > 0:
            regression_pct = ((baseline_score - current_score) / baseline_score) * 100.0
        else:
            # Baseline is zero: any score >= 0 is acceptable
            regression_pct = 0.0

        passed = regression_pct <= max_regression_pct

        if passed:
            reason = (
                f"Quality check passed: robustness {current_score:.2f} "
                f"(baseline {baseline_score:.2f}, regression {regression_pct:.1f}%"
                f" <= {max_regression_pct:.1f}% threshold)"
            )
        else:
            reason = (
                f"Quality regression detected: robustness dropped from "
                f"{baseline_score:.2f} to {current_score:.2f} "
                f"({regression_pct:.1f}% > {max_regression_pct:.1f}% threshold)"
            )

        logger.info(
            "gauntlet_quality_check passed=%s baseline=%.2f current=%.2f regression=%.1f%%",
            passed,
            baseline_score,
            current_score,
            regression_pct,
        )

        return GauntletQualityResult(
            passed=passed,
            baseline_score=baseline_score,
            current_score=current_score,
            regression_pct=regression_pct,
            max_regression_pct=max_regression_pct,
            reason=reason,
            gauntlet_id=gauntlet_result.gauntlet_id,
        )
