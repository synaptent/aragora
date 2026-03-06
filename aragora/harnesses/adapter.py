"""
Harness Result Adapter.

Converts output from external harnesses to Aragora's AuditFinding format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aragora.harnesses.base import (
    AnalysisType,
    HarnessResult,
)

if TYPE_CHECKING:
    from aragora.audit.document_auditor import AuditFinding
    from aragora.implement.types import TaskResult

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """Configuration for harness result adaptation."""

    # Severity mapping (harness severity -> AuditFinding severity)
    severity_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
            "info": "info",
            "informational": "info",
            "warning": "medium",
            "error": "high",
        }
    )

    # Category mapping (analysis type -> audit type)
    type_mapping: dict[str, str] = field(
        default_factory=lambda: {
            AnalysisType.SECURITY.value: "security",
            AnalysisType.QUALITY.value: "quality",
            AnalysisType.ARCHITECTURE.value: "consistency",
            AnalysisType.DEPENDENCIES.value: "security",
            AnalysisType.PERFORMANCE.value: "quality",
            AnalysisType.DOCUMENTATION.value: "quality",
            AnalysisType.TESTING.value: "quality",
            AnalysisType.GENERAL.value: "quality",
        }
    )

    # Confidence adjustment based on harness
    confidence_adjustments: dict[str, float] = field(
        default_factory=lambda: {
            "claude-code": 0.0,  # No adjustment
            "codex": -0.05,  # Slight decrease
            "kilo-code": 0.0,
            "default": 0.0,
        }
    )

    # Minimum confidence threshold
    min_confidence: float = 0.5

    # Prefix for finding IDs
    id_prefix: str = "harness"


class HarnessResultAdapter:
    """
    Adapts harness results to Aragora audit findings.

    Handles conversion of:
    - Finding structure
    - Severity levels
    - Audit types
    - Confidence scores
    """

    def __init__(self, config: AdapterConfig | None = None):
        self.config = config or AdapterConfig()
        self._similarity_backend = None

    def adapt(self, result: HarnessResult) -> list[AuditFinding]:
        """
        Convert harness result to list of audit findings.

        Args:
            result: HarnessResult from a code analysis harness

        Returns:
            List of AuditFinding objects
        """
        from aragora.audit.document_auditor import (
            AuditFinding,
            AuditType,
            FindingSeverity,
            FindingStatus,
        )

        audit_findings = []

        for finding in result.findings:
            try:
                # Map severity
                severity_str = self.config.severity_mapping.get(
                    finding.severity.lower(),
                    "medium",
                )
                severity = FindingSeverity(severity_str)

                # Map audit type
                audit_type_str = self.config.type_mapping.get(
                    result.analysis_type.value,
                    "quality",
                )
                audit_type = AuditType(audit_type_str)

                # Adjust confidence
                adjustment = self.config.confidence_adjustments.get(
                    result.harness,
                    self.config.confidence_adjustments["default"],
                )
                confidence = max(
                    self.config.min_confidence,
                    min(1.0, finding.confidence + adjustment),
                )

                # Generate unique ID
                finding_id = f"{self.config.id_prefix}_{result.harness}_{finding.id}"

                # Build evidence text
                evidence_text = finding.code_snippet
                if not evidence_text and finding.description:
                    evidence_text = finding.description[:500]

                # Build evidence location
                evidence_location = finding.file_path
                if finding.line_start:
                    evidence_location += f":{finding.line_start}"
                    if finding.line_end and finding.line_end != finding.line_start:
                        evidence_location += f"-{finding.line_end}"

                audit_finding = AuditFinding(
                    id=finding_id,
                    title=finding.title,
                    description=finding.description,
                    severity=severity,
                    confidence=confidence,
                    audit_type=audit_type,
                    category=finding.category,
                    document_id=finding.file_path,  # Use file path as document ID
                    chunk_id=None,
                    evidence_text=evidence_text,
                    evidence_location=evidence_location,
                    recommendation=finding.recommendation,
                    status=FindingStatus.OPEN,
                    found_by=result.harness,
                )

                audit_findings.append(audit_finding)

            except (KeyError, ValueError, TypeError, AttributeError) as e:
                logger.warning("Failed to adapt finding %s: %s", finding.id, e)

        return audit_findings

    def adapt_batch(self, results: list[HarnessResult]) -> list[AuditFinding]:
        """
        Convert multiple harness results to audit findings.

        Args:
            results: List of HarnessResult objects

        Returns:
            Combined list of AuditFinding objects
        """
        all_findings = []
        for result in results:
            all_findings.extend(self.adapt(result))
        return all_findings

    def merge_duplicate_findings(
        self,
        findings: list[AuditFinding],
    ) -> list[AuditFinding]:
        """
        Merge duplicate findings from multiple harnesses.

        Duplicates are identified by:
        - Same file
        - Same or overlapping line range
        - Similar title

        Args:
            findings: List of findings to deduplicate

        Returns:
            Deduplicated list with merged confidence
        """
        from aragora.audit.document_auditor import AuditFinding as AuditFindingType

        merged: list[AuditFindingType] = []
        seen_keys: set[str] = set()

        for finding in findings:
            # Generate a key for deduplication
            key = f"{finding.document_id}:{finding.evidence_location}"

            if key in seen_keys:
                # Check for similar existing finding
                for existing in merged:
                    if existing.document_id == finding.document_id:
                        # Compare titles (embedding-based)
                        if self._similarity_backend is None:
                            from aragora.debate.similarity.factory import get_backend

                            self._similarity_backend = get_backend(preferred="auto")
                        similarity = self._similarity_backend.compute_similarity(
                            existing.title.lower(),
                            finding.title.lower(),
                        )

                        if similarity > 0.8:
                            # Merge - keep higher confidence
                            if finding.confidence > existing.confidence:
                                existing.confidence = finding.confidence

                            # Add cross-reference using confirmed_by field
                            existing.confirmed_by.append(finding.id)
                            break
            else:
                seen_keys.add(key)
                merged.append(finding)

        return merged


def adapt_to_audit_findings(
    result: HarnessResult,
    config: AdapterConfig | None = None,
) -> list[AuditFinding]:
    """
    Convenience function to adapt a harness result.

    Args:
        result: HarnessResult from analysis
        config: Optional adapter configuration

    Returns:
        List of AuditFinding objects
    """
    adapter = HarnessResultAdapter(config)
    return adapter.adapt(result)


def adapt_multiple_results(
    results: list[HarnessResult],
    merge_duplicates: bool = True,
    config: AdapterConfig | None = None,
) -> list[AuditFinding]:
    """
    Adapt multiple harness results and optionally merge duplicates.

    Args:
        results: List of HarnessResult objects
        merge_duplicates: Whether to merge duplicate findings
        config: Optional adapter configuration

    Returns:
        List of AuditFinding objects
    """
    adapter = HarnessResultAdapter(config)
    findings = adapter.adapt_batch(results)

    if merge_duplicates:
        findings = adapter.merge_duplicate_findings(findings)

    return findings


def adapt_to_implement_result(
    result: HarnessResult,
    task_id: str,
    diff: str = "",
) -> "TaskResult":
    """
    Convert a HarnessResult to an implement TaskResult.

    This bridges the harness analysis system with the implementation
    executor, allowing HybridExecutor to delegate to ClaudeCodeHarness
    and return a standard TaskResult.

    Args:
        result: HarnessResult from a harness run
        task_id: The implementation task ID
        diff: Git diff produced by the harness execution

    Returns:
        TaskResult suitable for the implement pipeline
    """
    from aragora.implement.types import TaskResult

    error: str | None = None
    if not result.success:
        error = result.error_message or result.error_output or "Harness execution failed"

    return TaskResult(
        task_id=task_id,
        success=result.success,
        diff=diff,
        error=error,
        model_used=f"harness:{result.harness}",
        duration_seconds=result.duration_seconds,
    )


__all__ = [
    "HarnessResultAdapter",
    "AdapterConfig",
    "adapt_to_audit_findings",
    "adapt_multiple_results",
    "adapt_to_implement_result",
]
