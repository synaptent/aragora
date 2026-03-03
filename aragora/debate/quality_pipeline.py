"""
Shared post-consensus quality pipeline.

This module provides a single entry-point that both the CLI and server
debate paths can call after consensus to apply deterministic quality
checks and repairs.  It intentionally does NOT include LLM upgrade loops
(those are optional and live in the CLI path) -- the pipeline here is
pure-deterministic and fast.

The pipeline stages are:
1. Derive or load an OutputContract from the task / caller config.
2. Validate the consensus answer against the contract.
3. Apply deterministic quality repairs for common structured-output defects.
4. Finalize the JSON payload section (if required by the contract).
5. Re-validate and return a quality report alongside the (possibly improved) answer.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityPipelineConfig:
    """Configuration for the post-consensus quality pipeline.

    All fields have safe defaults so callers can construct with just
    ``QualityPipelineConfig()`` to get the standard pipeline.
    """

    enabled: bool = True

    # OutputContract source (mutually exclusive; first non-None wins):
    output_contract_file: str | None = None
    required_sections: list[str] | None = None
    # If neither is set, the contract is derived from the task text.

    # Repo root for path-existence checks (defaults to cwd).
    repo_root: str | None = None

    # Whether the debate has additional context (--context flag).
    # Substantial tasks get the standard 7-section contract.
    has_context: bool = False

    # Score thresholds -- used only for the ``passes_gate`` flag in the
    # result; the deterministic pipeline always runs.
    quality_min_score: float = 9.0
    practicality_min_score: float = 5.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityPipelineConfig:
        """Construct from a JSON-compatible dict (e.g. API request body)."""
        if not isinstance(data, dict):
            return cls()

        sections_raw = data.get("required_sections")
        sections: list[str] | None = None
        if isinstance(sections_raw, list):
            sections = [str(s).strip() for s in sections_raw if str(s).strip()]
            if not sections:
                sections = None

        return cls(
            enabled=bool(data.get("enabled", True)),
            output_contract_file=data.get("output_contract_file"),
            required_sections=sections,
            repo_root=data.get("repo_root"),
            has_context=bool(data.get("has_context", False)),
            quality_min_score=float(data.get("quality_min_score", 9.0)),
            practicality_min_score=float(data.get("practicality_min_score", 6.0)),
        )


@dataclass
class QualityPipelineResult:
    """Result of the post-consensus quality pipeline."""

    # The (possibly repaired) answer text.
    answer: str

    # Whether the quality gate passes.
    passes_gate: bool = False

    # Contract that was used (None if no contract could be derived).
    contract_dict: dict[str, Any] | None = None

    # Initial validation report (before repairs).
    initial_report_dict: dict[str, Any] = field(default_factory=dict)

    # Final validation report (after repairs).
    final_report_dict: dict[str, Any] = field(default_factory=dict)

    # Whether any deterministic repairs were applied.
    repaired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passes_gate": self.passes_gate,
            "repaired": self.repaired,
            "contract": self.contract_dict,
            "initial_report": self.initial_report_dict,
            "final_report": self.final_report_dict,
        }


def _resolve_contract(
    task: str,
    config: QualityPipelineConfig,
):
    """Resolve an OutputContract from the config or task text."""
    from aragora.debate.output_quality import (
        derive_output_contract_from_task,
        load_output_contract_from_file,
    )

    # 1. Explicit file path
    if config.output_contract_file:
        return load_output_contract_from_file(config.output_contract_file)

    # 2. Explicit section list
    if config.required_sections:
        normalized = ", ".join(config.required_sections)
        return derive_output_contract_from_task(f"output sections {normalized}")

    # 3. Derive from task text (pass context hint for smart defaulting)
    return derive_output_contract_from_task(task, has_context=config.has_context)


def _quality_gate_passes(
    report,
    *,
    quality_min: float,
    practicality_min: float,
) -> bool:
    return bool(
        report.verdict == "good"
        and report.quality_score_10 >= quality_min
        and float(getattr(report, "practicality_score_10", 0.0)) >= practicality_min
    )


def apply_post_consensus_quality(
    answer: str,
    task: str,
    config: QualityPipelineConfig | None = None,
) -> QualityPipelineResult:
    """Run the deterministic post-consensus quality pipeline.

    This is the single entry point for both CLI and server paths.
    It never makes LLM calls -- only deterministic validation and repair.

    Args:
        answer: The consensus answer text to validate / repair.
        task: The original debate task / question.
        config: Pipeline configuration.  ``None`` means use defaults.

    Returns:
        ``QualityPipelineResult`` with the (possibly improved) answer and
        quality metadata.
    """
    if config is None:
        config = QualityPipelineConfig()

    if not config.enabled:
        return QualityPipelineResult(answer=answer)

    # Lazy imports to avoid pulling heavy modules at import time.
    from aragora.debate.output_quality import (
        apply_deterministic_quality_repairs,
        finalize_json_payload,
        validate_output_against_contract,
    )

    # Resolve the contract.
    try:
        contract = _resolve_contract(task, config)
    except ValueError as exc:
        logger.warning("quality_pipeline: contract resolution failed: %s", exc)
        return QualityPipelineResult(answer=answer)

    if contract is None:
        # No contract could be derived -- nothing to validate against.
        return QualityPipelineResult(answer=answer)

    repo_root = config.repo_root or os.getcwd()

    # Stage 1: initial validation.
    initial_report = validate_output_against_contract(
        answer,
        contract,
        repo_root=repo_root,
    )

    best_answer = answer
    best_report = initial_report
    repaired = False

    # Stage 2: deterministic repairs (if needed).
    if initial_report.verdict != "good":
        repaired_answer = apply_deterministic_quality_repairs(answer, contract, initial_report)
        repaired_report = validate_output_against_contract(
            repaired_answer,
            contract,
            repo_root=repo_root,
        )
        # Accept if the repair is at least as good.
        if (
            repaired_report.quality_score_10 >= initial_report.quality_score_10
            or repaired_report.verdict == "good"
        ):
            best_answer = repaired_answer
            best_report = repaired_report
            repaired = True

    # Stage 3: JSON payload finalization.
    if contract.require_json_payload:
        json_answer = finalize_json_payload(best_answer, contract)
        json_report = validate_output_against_contract(
            json_answer,
            contract,
            repo_root=repo_root,
        )
        if (
            json_report.quality_score_10 >= best_report.quality_score_10
            or json_report.has_valid_json_payload
        ):
            if best_answer != json_answer:
                repaired = True
            best_answer = json_answer
            best_report = json_report

    passes = _quality_gate_passes(
        best_report,
        quality_min=config.quality_min_score,
        practicality_min=config.practicality_min_score,
    )

    return QualityPipelineResult(
        answer=best_answer,
        passes_gate=passes,
        contract_dict=contract.to_dict(),
        initial_report_dict=initial_report.to_dict(),
        final_report_dict=best_report.to_dict(),
        repaired=repaired,
    )
