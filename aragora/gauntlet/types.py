"""
Gauntlet Shared Types.

Canonical type definitions shared between:
- aragora.gauntlet.orchestrator (GauntletOrchestrator)
- aragora.gauntlet.runner (GauntletRunner)
- aragora.server.handlers.gauntlet (HTTP endpoints)

This module provides the single source of truth for:
- Enums: InputType, Verdict, SeverityLevel
- Base dataclasses used across the gauntlet system
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class InputType(Enum):
    """Types of inputs that can be stress-tested."""

    SPEC = "spec"  # Product/feature specification
    ARCHITECTURE = "architecture"  # System architecture document
    POLICY = "policy"  # Policy or compliance document
    CODE = "code"  # Source code
    STRATEGY = "strategy"  # Business strategy
    CONTRACT = "contract"  # Legal contract
    CUSTOM = "custom"  # Custom input type


class Verdict(Enum):
    """
    Final verdict from Gauntlet analysis.

    Three-tier system compatible with both orchestrator and runner:
    - PASS/APPROVED: Safe to proceed
    - CONDITIONAL/APPROVED_WITH_CONDITIONS: Proceed with mitigations
    - FAIL/REJECTED: Do not proceed
    - NEEDS_REVIEW: Requires human review (orchestrator-specific)
    """

    # Positive outcomes
    PASS = "pass"  # noqa: S105 -- enum value
    APPROVED = "approved"

    # Conditional outcomes
    CONDITIONAL = "conditional"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    NEEDS_REVIEW = "needs_review"

    # Negative outcomes
    FAIL = "fail"
    REJECTED = "rejected"

    @property
    def is_passing(self) -> bool:
        """Check if verdict indicates approval."""
        return self in (Verdict.PASS, Verdict.APPROVED)

    @property
    def is_conditional(self) -> bool:
        """Check if verdict indicates conditional approval."""
        return self in (
            Verdict.CONDITIONAL,
            Verdict.APPROVED_WITH_CONDITIONS,
            Verdict.NEEDS_REVIEW,
        )

    @property
    def is_failing(self) -> bool:
        """Check if verdict indicates rejection."""
        return self in (Verdict.FAIL, Verdict.REJECTED)


class SeverityLevel(Enum):
    """Severity levels for findings/vulnerabilities."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def numeric_value(self) -> float:
        """Convert to numeric value (0-1 scale)."""
        mapping = {
            SeverityLevel.CRITICAL: 0.95,
            SeverityLevel.HIGH: 0.75,
            SeverityLevel.MEDIUM: 0.50,
            SeverityLevel.LOW: 0.25,
            SeverityLevel.INFO: 0.10,
        }
        return mapping[self]

    @classmethod
    def from_numeric(cls, value: float) -> SeverityLevel:
        """Convert numeric value to severity level."""
        if value >= 0.9:
            return cls.CRITICAL
        elif value >= 0.7:
            return cls.HIGH
        elif value >= 0.4:
            return cls.MEDIUM
        elif value >= 0.2:
            return cls.LOW
        return cls.INFO


class GauntletPhase(Enum):
    """Phases of the Gauntlet validation pipeline."""

    NOT_STARTED = "not_started"
    INITIALIZATION = "initialization"
    RISK_ASSESSMENT = "risk_assessment"
    SCENARIO_ANALYSIS = "scenario_analysis"
    RED_TEAM = "red_team"
    ADVERSARIAL_PROBING = "adversarial_probing"
    DEEP_AUDIT = "deep_audit"
    FORMAL_VERIFICATION = "formal_verification"
    SYNTHESIS = "synthesis"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BaseFinding:
    """
    Base class for findings across both gauntlet systems.

    Extended by:
    - modes.gauntlet.Finding (orchestrator)
    - gauntlet.result.Vulnerability (runner)
    """

    id: str
    title: str
    description: str
    severity: SeverityLevel
    category: str
    source: str

    # Optional details
    evidence: str = ""
    mitigation: str | None = None

    # Verification
    is_verified: bool = False
    verification_method: str | None = None

    # Timing
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def severity_numeric(self) -> float:
        """Get numeric severity value (0-1)."""
        return self.severity.numeric_value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "severity_numeric": self.severity_numeric,
            "category": self.category,
            "source": self.source,
            "evidence": self.evidence,
            "mitigation": self.mitigation,
            "is_verified": self.is_verified,
            "verification_method": self.verification_method,
            "created_at": self.created_at,
        }


@dataclass
class RiskSummary:
    """Summary of risk findings by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        """Total number of findings."""
        return self.critical + self.high + self.medium + self.low + self.info

    @property
    def weighted_score(self) -> float:
        """Weighted risk score (critical=10, high=5, medium=2, low=1)."""
        return self.critical * 10 + self.high * 5 + self.medium * 2 + self.low * 1

    def add_finding(self, severity: SeverityLevel) -> None:
        """Add a finding of given severity."""
        if severity == SeverityLevel.CRITICAL:
            self.critical += 1
        elif severity == SeverityLevel.HIGH:
            self.high += 1
        elif severity == SeverityLevel.MEDIUM:
            self.medium += 1
        elif severity == SeverityLevel.LOW:
            self.low += 1
        else:
            self.info += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "critical": self.critical,
            "high": self.high,
            "medium": self.medium,
            "low": self.low,
            "info": self.info,
            "total": self.total,
            "weighted_score": self.weighted_score,
        }


# Type aliases for compatibility
GauntletSeverity = SeverityLevel  # Alias for backward compatibility

__all__ = [
    # Enums
    "InputType",
    "Verdict",
    "SeverityLevel",
    "GauntletSeverity",
    "GauntletPhase",
    # Base classes
    "BaseFinding",
    "RiskSummary",
]
