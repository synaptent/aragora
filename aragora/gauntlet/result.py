"""
Gauntlet Result - Aggregated results from a gauntlet run.

Combines findings from:
- Red Team attacks
- Capability probes
- Scenario matrix
- Risk analysis
"""

from __future__ import annotations

__all__ = [
    "AttackSummary",
    "GauntletResult",
    "ProbeSummary",
    "RiskSummary",
    "ScenarioSummary",
    "SeverityLevel",
    "Verdict",
    "Vulnerability",
]

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Import categories from config
from .types import RiskSummary as BaseRiskSummary

# Import shared types
from .types import SeverityLevel, Verdict


@dataclass
class Vulnerability:
    """A single vulnerability finding."""

    id: str
    title: str
    description: str
    severity: SeverityLevel
    category: str  # Attack or probe category
    source: str  # Which agent/system found it

    # Details
    evidence: str = ""
    exploit_scenario: str = ""
    mitigation: str = ""

    # Scores
    exploitability: float = 0.5  # 0-1
    impact: float = 0.5  # 0-1

    # Provenance
    agent_name: str | None = None
    round_number: int | None = None
    scenario_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def risk_score(self) -> float:
        """Calculate risk score from exploitability and impact."""
        return self.exploitability * self.impact

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "category": self.category,
            "source": self.source,
            "evidence": self.evidence,
            "exploit_scenario": self.exploit_scenario,
            "mitigation": self.mitigation,
            "exploitability": self.exploitability,
            "impact": self.impact,
            "risk_score": self.risk_score,
            "agent_name": self.agent_name,
            "round_number": self.round_number,
            "scenario_id": self.scenario_id,
            "created_at": self.created_at,
        }


# Use shared RiskSummary from types.py
RiskSummary = BaseRiskSummary


@dataclass
class AttackSummary:
    """Summary of red team attack results."""

    total_attacks: int = 0
    successful_attacks: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    robustness_score: float = 1.0
    coverage_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_attacks": self.total_attacks,
            "successful_attacks": self.successful_attacks,
            "success_rate": (
                self.successful_attacks / self.total_attacks if self.total_attacks > 0 else 0
            ),
            "by_category": self.by_category,
            "robustness_score": self.robustness_score,
            "coverage_score": self.coverage_score,
        }


@dataclass
class ProbeSummary:
    """Summary of capability probe results."""

    probes_run: int = 0
    vulnerabilities_found: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    vulnerability_rate: float = 0.0
    elo_penalty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "probes_run": self.probes_run,
            "vulnerabilities_found": self.vulnerabilities_found,
            "vulnerability_rate": self.vulnerability_rate,
            "by_category": self.by_category,
            "elo_penalty": self.elo_penalty,
        }


@dataclass
class ScenarioSummary:
    """Summary of scenario matrix results."""

    scenarios_run: int = 0
    outcome_category: str = "inconclusive"  # consistent, conditional, divergent
    avg_similarity: float = 0.0
    universal_conclusions: list[str] = field(default_factory=list)
    conditional_patterns: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios_run": self.scenarios_run,
            "outcome_category": self.outcome_category,
            "avg_similarity": self.avg_similarity,
            "universal_conclusions": self.universal_conclusions,
            "conditional_patterns": self.conditional_patterns,
        }


@dataclass
class GauntletResult:
    """
    Complete result of a Gauntlet validation run.

    Aggregates all findings from attacks, probes, and scenarios
    into a unified result with verdict and evidence.
    """

    # Identification
    gauntlet_id: str
    input_hash: str  # SHA-256 of input for integrity
    input_summary: str  # First 500 chars of input

    # Timing
    started_at: str
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Verdict
    verdict: Verdict = Verdict.CONDITIONAL
    confidence: float = 0.5
    verdict_reasoning: str = ""

    # Findings
    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    risk_summary: RiskSummary = field(default_factory=RiskSummary)

    # Component summaries
    attack_summary: AttackSummary = field(default_factory=AttackSummary)
    probe_summary: ProbeSummary = field(default_factory=ProbeSummary)
    scenario_summary: ScenarioSummary = field(default_factory=ScenarioSummary)

    # Evidence
    dissenting_views: list[str] = field(default_factory=list)
    consensus_points: list[str] = field(default_factory=list)

    # Metadata
    config_used: dict[str, Any] = field(default_factory=dict)
    agents_used: list[str] = field(default_factory=list)

    def add_vulnerability(self, vuln: Vulnerability) -> None:
        """Add a vulnerability and update risk summary."""
        self.vulnerabilities.append(vuln)

        # Update risk summary
        if vuln.severity == SeverityLevel.CRITICAL:
            self.risk_summary.critical += 1
        elif vuln.severity == SeverityLevel.HIGH:
            self.risk_summary.high += 1
        elif vuln.severity == SeverityLevel.MEDIUM:
            self.risk_summary.medium += 1
        elif vuln.severity == SeverityLevel.LOW:
            self.risk_summary.low += 1
        else:
            self.risk_summary.info += 1

    def calculate_verdict(
        self,
        critical_threshold: int = 0,
        high_threshold: int = 2,
        vulnerability_rate_threshold: float = 0.2,
        robustness_threshold: float = 0.6,
    ) -> None:
        """Calculate verdict based on thresholds."""
        # Check for automatic FAIL conditions
        if self.risk_summary.critical > critical_threshold:
            self.verdict = Verdict.FAIL
            self.verdict_reasoning = f"Critical vulnerabilities ({self.risk_summary.critical}) exceed threshold ({critical_threshold})"
            self.confidence = 0.9
            return

        if self.risk_summary.high > high_threshold:
            self.verdict = Verdict.FAIL
            self.verdict_reasoning = f"High-severity vulnerabilities ({self.risk_summary.high}) exceed threshold ({high_threshold})"
            self.confidence = 0.8
            return

        # Check probe results
        if self.probe_summary.vulnerability_rate > vulnerability_rate_threshold:
            self.verdict = Verdict.CONDITIONAL
            self.verdict_reasoning = f"Vulnerability rate ({self.probe_summary.vulnerability_rate:.1%}) exceeds threshold ({vulnerability_rate_threshold:.1%})"
            self.confidence = 0.7
            return

        # Check robustness
        if self.attack_summary.robustness_score < robustness_threshold:
            self.verdict = Verdict.CONDITIONAL
            self.verdict_reasoning = f"Robustness score ({self.attack_summary.robustness_score:.1%}) below threshold ({robustness_threshold:.1%})"
            self.confidence = 0.7
            return

        # Check scenario divergence
        if self.scenario_summary.outcome_category == "divergent":
            self.verdict = Verdict.CONDITIONAL
            self.verdict_reasoning = "Conclusions diverge significantly across scenarios"
            self.confidence = 0.6
            return

        # PASS
        self.verdict = Verdict.PASS
        reasons = []
        if self.risk_summary.total == 0:
            reasons.append("No vulnerabilities found")
        else:
            reasons.append(f"Vulnerabilities within thresholds ({self.risk_summary.total} total)")
        if self.attack_summary.robustness_score >= robustness_threshold:
            reasons.append(f"Strong robustness ({self.attack_summary.robustness_score:.1%})")
        if self.scenario_summary.outcome_category == "consistent":
            reasons.append("Consistent conclusions across scenarios")

        self.verdict_reasoning = "; ".join(reasons)
        self.confidence = min(0.95, 0.6 + self.attack_summary.robustness_score * 0.3)

    def get_critical_vulnerabilities(self) -> list[Vulnerability]:
        """Get critical and high severity vulnerabilities."""
        return [
            v
            for v in self.vulnerabilities
            if v.severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH]
        ]

    def get_rejection_summary(self) -> dict[str, Any]:
        """Generate a user-friendly rejection summary with action items.

        Returns a dict with:
        - reason: Why the gauntlet failed/was conditional
        - action_items: Specific steps to resolve each issue
        - severity_breakdown: Count by severity level
        - estimated_effort: rough effort to remediate
        """
        if self.verdict == Verdict.PASS:
            return {
                "reason": "Gauntlet passed — no rejection.",
                "action_items": [],
                "severity_breakdown": self.risk_summary.to_dict(),
                "estimated_effort": "none",
            }

        action_items = []
        for vuln in self.get_critical_vulnerabilities():
            item: dict[str, Any] = {
                "vulnerability": vuln.title,
                "severity": vuln.severity.value,
                "description": vuln.description,
            }
            if vuln.mitigation:
                item["fix"] = vuln.mitigation
            if vuln.evidence:
                item["evidence"] = vuln.evidence[:200]
            action_items.append(item)

        # Estimate effort based on finding count and severity
        total = self.risk_summary.critical + self.risk_summary.high
        if total == 0:
            effort = "low"
        elif total <= 3:
            effort = "medium"
        else:
            effort = "high"

        return {
            "reason": self.verdict_reasoning,
            "action_items": action_items,
            "severity_breakdown": self.risk_summary.to_dict(),
            "estimated_effort": effort,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "gauntlet_id": self.gauntlet_id,
            "input_hash": self.input_hash,
            "input_summary": self.input_summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "verdict_reasoning": self.verdict_reasoning,
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "risk_summary": self.risk_summary.to_dict(),
            "attack_summary": self.attack_summary.to_dict(),
            "probe_summary": self.probe_summary.to_dict(),
            "scenario_summary": self.scenario_summary.to_dict(),
            "dissenting_views": self.dissenting_views,
            "consensus_points": self.consensus_points,
            "config_used": self.config_used,
            "agents_used": self.agents_used,
            "rejection_summary": self.get_rejection_summary()
            if self.verdict != Verdict.PASS
            else None,
        }
