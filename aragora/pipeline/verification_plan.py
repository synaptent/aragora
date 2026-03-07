"""
Test Plan Generator - Generate verification strategy from debate outcomes.

Creates structured test plans based on:
- Key claims that need verification
- Critical functionality identified in debate
- Edge cases mentioned in critiques
- Integration points
"""

from __future__ import annotations

__all__ = [
    "CasePriority",
    "TestPriority",
    "TestType",
    "VerificationCase",
    "VerificationPlan",
    "VerificationPlanGenerator",
    "VerificationType",
    "generate_test_plan",
]

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.export.artifact import DebateArtifact


class VerificationType(Enum):
    """Types of verification tests.

    Note: Renamed from TestType to avoid pytest collection warnings.
    """

    __test__ = False  # Not a pytest test class

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"
    REGRESSION = "regression"


# Backward compatibility alias
TestType = VerificationType


class CasePriority(Enum):
    """Test case priority levels.

    Note: Renamed from TestPriority to avoid pytest collection warnings.
    """

    __test__ = False  # Not a pytest test class

    P0 = "p0"  # Critical - must pass
    P1 = "p1"  # High priority
    P2 = "p2"  # Medium priority
    P3 = "p3"  # Low priority


# Backward compatibility alias
TestPriority = CasePriority


@dataclass
class VerificationCase:
    """A single test case specification."""

    __test__ = False  # Not a pytest test class

    id: str
    title: str
    description: str
    test_type: VerificationType
    priority: CasePriority

    # Test details
    preconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    expected_result: str = ""

    # Traceability
    related_claim_ids: list[str] = field(default_factory=list)
    related_critique_ids: list[str] = field(default_factory=list)

    # Status
    automated: bool = False
    implemented: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "test_type": self.test_type.value,
            "priority": self.priority.value,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "expected_result": self.expected_result,
            "related_claim_ids": self.related_claim_ids,
            "related_critique_ids": self.related_critique_ids,
            "automated": self.automated,
            "implemented": self.implemented,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VerificationCase:
        """Deserialize a VerificationCase from a dictionary payload."""
        try:
            test_type = VerificationType(data.get("test_type", VerificationType.UNIT.value))
        except ValueError:
            test_type = VerificationType.UNIT
        try:
            priority = CasePriority(data.get("priority", CasePriority.P2.value))
        except ValueError:
            priority = CasePriority.P2
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            test_type=test_type,
            priority=priority,
            preconditions=list(data.get("preconditions", []) or []),
            steps=list(data.get("steps", []) or []),
            expected_result=data.get("expected_result", ""),
            related_claim_ids=list(data.get("related_claim_ids", []) or []),
            related_critique_ids=list(data.get("related_critique_ids", []) or []),
            automated=bool(data.get("automated", False)),
            implemented=bool(data.get("implemented", False)),
        )


@dataclass
class VerificationPlan:
    """
    Complete test plan for verifying debate outcomes.

    Contains test cases organized by type and priority,
    with traceability to debate claims and critiques.
    """

    __test__ = False  # Not a pytest test class

    debate_id: str
    title: str
    description: str
    test_cases: list[VerificationCase] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Coverage goals
    target_coverage: float = 0.8
    critical_paths: list[str] = field(default_factory=list)

    def add_test(self, test: VerificationCase) -> None:
        """Add a test case."""
        self.test_cases.append(test)

    def get_by_type(self, test_type: VerificationType) -> list[VerificationCase]:
        """Get tests by type."""
        return [t for t in self.test_cases if t.test_type == test_type]

    def get_by_priority(self, priority: CasePriority) -> list[VerificationCase]:
        """Get tests by priority."""
        return [t for t in self.test_cases if t.priority == priority]

    def get_unimplemented(self) -> list[VerificationCase]:
        """Get tests not yet implemented."""
        return [t for t in self.test_cases if not t.implemented]

    @property
    def summary(self) -> dict:
        """Generate summary statistics."""
        return {
            "total_tests": len(self.test_cases),
            "by_type": {t.value: len(self.get_by_type(t)) for t in VerificationType},
            "by_priority": {p.value: len(self.get_by_priority(p)) for p in CasePriority},
            "automated": sum(1 for t in self.test_cases if t.automated),
            "implemented": sum(1 for t in self.test_cases if t.implemented),
        }

    def to_markdown(self) -> str:
        """Generate markdown representation."""
        summary = self.summary

        tests_by_priority = ""
        for priority in CasePriority:
            priority_tests = self.get_by_priority(priority)
            if priority_tests:
                tests_by_priority += (
                    f"\n### Priority {priority.value.upper()} ({len(priority_tests)})\n\n"
                )
                for test in priority_tests:
                    status = "[x]" if test.implemented else "[ ]"
                    auto = " [AUTO]" if test.automated else ""
                    tests_by_priority += f"""
#### {status} {test.title}{auto}

**Type:** {test.test_type.value}

{test.description}

**Preconditions:**
{chr(10).join(f"- {p}" for p in test.preconditions) if test.preconditions else "- None"}

**Steps:**
{chr(10).join(f"{i + 1}. {s}" for i, s in enumerate(test.steps)) if test.steps else "1. TBD"}

**Expected Result:** {test.expected_result or "TBD"}

---
"""

        return f"""# Test Plan: {self.title}

**Debate ID:** {self.debate_id}
**Generated:** {self.created_at[:10]}
**Target Coverage:** {self.target_coverage:.0%}

---

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | {summary["total_tests"]} |
| Unit | {summary["by_type"].get("unit", 0)} |
| Integration | {summary["by_type"].get("integration", 0)} |
| E2E | {summary["by_type"].get("e2e", 0)} |
| Automated | {summary["automated"]} |
| Implemented | {summary["implemented"]} |

---

## Critical Paths

{chr(10).join(f"- {p}" for p in self.critical_paths) if self.critical_paths else "- TBD based on implementation"}

---

## Test Cases

{tests_by_priority}

---

*Generated by aragora v0.8.0*
"""

    def to_dict(self) -> dict:
        return {
            "debate_id": self.debate_id,
            "title": self.title,
            "description": self.description,
            "test_cases": [t.to_dict() for t in self.test_cases],
            "summary": self.summary,
            "target_coverage": self.target_coverage,
            "critical_paths": self.critical_paths,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VerificationPlan:
        """Deserialize a VerificationPlan from a dictionary payload."""
        return cls(
            debate_id=data.get("debate_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            test_cases=[
                VerificationCase.from_dict(item) for item in data.get("test_cases", []) or []
            ],
            created_at=data.get("created_at", datetime.now().isoformat()),
            target_coverage=float(data.get("target_coverage", 0.8) or 0.8),
            critical_paths=list(data.get("critical_paths", []) or []),
        )


class VerificationPlanGenerator:
    """
    Generates test plans from debate artifacts.

    Analyzes:
    - Final answer for testable claims
    - Critiques for edge cases
    - Verification results for already-proven properties
    """

    __test__ = False  # Not a pytest test class

    def __init__(self, artifact: DebateArtifact) -> None:
        self.artifact: DebateArtifact = artifact

    def generate(self) -> VerificationPlan:
        """Generate complete test plan."""
        plan = VerificationPlan(
            debate_id=self.artifact.debate_id,
            title=self._extract_title(),
            description=f"Test plan for: {self.artifact.task}",
        )

        # Generate tests from consensus
        self._add_consensus_tests(plan)

        # Generate tests from critiques
        self._add_critique_tests(plan)

        # Generate tests from verifications
        self._add_verification_tests(plan)

        # Add standard tests
        self._add_standard_tests(plan)

        return plan

    def _extract_title(self) -> str:
        """Extract title from task."""
        task = self.artifact.task
        if "." in task[:80]:
            return task[: task.index(".") + 1]
        return task[:60] + "..."

    def _add_consensus_tests(self, plan: VerificationPlan) -> None:
        """Add tests based on consensus conclusions."""
        consensus = self.artifact.consensus_proof
        if not consensus:
            return

        final_answer = consensus.final_answer

        # Extract testable statements
        lines = final_answer.split("\n")
        test_num = 1

        for line in lines:
            line = line.strip()
            # Look for implementation-like statements
            if any(kw in line.lower() for kw in ["implement", "use", "add", "create", "ensure"]):
                plan.add_test(
                    VerificationCase(
                        id=f"consensus-{test_num}",
                        title=f"Verify: {line[:50]}...",
                        description=f"Test that the implementation satisfies: {line}",
                        test_type=VerificationType.INTEGRATION,
                        priority=CasePriority.P1,
                        steps=[
                            "Set up test environment",
                            "Execute functionality",
                            "Verify expected behavior",
                        ],
                        expected_result="Functionality works as described in debate conclusion",
                    )
                )
                test_num += 1

                if test_num > 5:  # Limit to 5 consensus tests
                    break

    def _add_critique_tests(self, plan: VerificationPlan) -> None:
        """Add tests based on critique issues (edge cases)."""
        if not self.artifact.trace_data:
            return

        events = self.artifact.trace_data.get("events", [])
        critique_events = [e for e in events if e.get("event_type") == "agent_critique"]

        test_num = 1
        for event in critique_events[:3]:  # Top 3 critiques
            content = event.get("content", {})
            issues = content.get("issues", [])

            for issue in issues[:2]:  # Top 2 issues per critique
                plan.add_test(
                    VerificationCase(
                        id=f"critique-{test_num}",
                        title=f"Edge case: {issue[:50]}...",
                        description=f"Test edge case identified in critique: {issue}",
                        test_type=VerificationType.UNIT,
                        priority=CasePriority.P2,
                        steps=["Set up edge case conditions", "Execute", "Verify handling"],
                        expected_result="Edge case is handled gracefully",
                        related_critique_ids=[event.get("event_id", "")],
                    )
                )
                test_num += 1

    def _add_verification_tests(self, plan: VerificationPlan) -> None:
        """Add tests for formally verified properties."""
        for v in self.artifact.verification_results:
            if v.status == "verified":
                plan.add_test(
                    VerificationCase(
                        id=f"formal-{v.claim_id}",
                        title=f"Property: {v.claim_text[:50]}...",
                        description=f"Regression test for formally verified property: {v.claim_text}",
                        test_type=VerificationType.UNIT,
                        priority=CasePriority.P0,  # Critical - must not regress
                        steps=["Property was formally verified", "Implement as regression test"],
                        expected_result="Property holds",
                        automated=True,
                        related_claim_ids=[v.claim_id],
                    )
                )

    def _add_standard_tests(self, plan: VerificationPlan) -> None:
        """Add standard test categories."""
        # Always add a smoke test
        plan.add_test(
            VerificationCase(
                id="smoke-1",
                title="Smoke test: Basic functionality",
                description="Verify basic functionality works after implementation",
                test_type=VerificationType.E2E,
                priority=CasePriority.P0,
                steps=["Deploy changes", "Execute happy path", "Verify success"],
                expected_result="Basic use case succeeds",
            )
        )

        # Add regression test placeholder
        plan.add_test(
            VerificationCase(
                id="regression-1",
                title="Regression: Existing functionality",
                description="Verify existing functionality is not broken",
                test_type=VerificationType.REGRESSION,
                priority=CasePriority.P1,
                steps=["Run existing test suite", "Verify all pass"],
                expected_result="No regressions",
            )
        )


def generate_test_plan(artifact) -> VerificationPlan:
    """Convenience function to generate test plan from artifact."""
    generator = VerificationPlanGenerator(artifact)
    return generator.generate()
