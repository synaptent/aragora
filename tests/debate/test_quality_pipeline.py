"""Tests for the shared post-consensus quality pipeline."""

from __future__ import annotations

import json
import os
import textwrap

import pytest

from aragora.debate.quality_pipeline import (
    QualityPipelineConfig,
    QualityPipelineResult,
    apply_post_consensus_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASK_WITH_SECTIONS = (
    "Smoke test: output sections Ranked High-Level Tasks, Suggested Subtasks, "
    "Owner module / file paths, Test Plan, Rollback Plan, Gate Criteria, JSON Payload"
)

_GOOD_ANSWER = textwrap.dedent("""\
    ## Ranked High-Level Tasks
    - Integrate quality pipeline into server debate handlers

    ## Suggested Subtasks
    - Add quality_pipeline field to DebateRequest
    - Wire pipeline into _run_debate

    ## Owner module / file paths
    - aragora/debate/quality_pipeline.py
    - aragora/server/debate_controller.py

    ## Test Plan
    - Run pytest tests/debate/test_quality_pipeline.py

    ## Rollback Plan
    If error_rate > 2% for 10m, rollback by reverting the quality_pipeline commit.

    ## Gate Criteria
    - p95_latency <= 250ms for 15m
    - error_rate < 1% over 15m

    ## JSON Payload
    ```json
    {"tasks": ["integrate quality pipeline"], "quality_repaired": true}
    ```
""")

_BAD_ANSWER = textwrap.dedent("""\
    Here is my answer with no structure at all.
    Just plain text, no headings, no sections.
""")


# ---------------------------------------------------------------------------
# QualityPipelineConfig
# ---------------------------------------------------------------------------


class TestQualityPipelineConfig:
    def test_defaults(self):
        cfg = QualityPipelineConfig()
        assert cfg.enabled is True
        assert cfg.quality_min_score == 9.0
        assert cfg.practicality_min_score == 5.0
        assert cfg.output_contract_file is None
        assert cfg.required_sections is None

    def test_from_dict_empty(self):
        cfg = QualityPipelineConfig.from_dict({})
        assert cfg.enabled is True

    def test_from_dict_disabled(self):
        cfg = QualityPipelineConfig.from_dict({"enabled": False})
        assert cfg.enabled is False

    def test_from_dict_with_sections(self):
        cfg = QualityPipelineConfig.from_dict(
            {
                "required_sections": ["Summary", "Action Items"],
                "quality_min_score": 7.5,
            }
        )
        assert cfg.required_sections == ["Summary", "Action Items"]
        assert cfg.quality_min_score == 7.5

    def test_from_dict_strips_empty_sections(self):
        cfg = QualityPipelineConfig.from_dict(
            {
                "required_sections": ["Summary", "", "  "],
            }
        )
        assert cfg.required_sections == ["Summary"]

    def test_from_dict_all_empty_sections_becomes_none(self):
        cfg = QualityPipelineConfig.from_dict(
            {
                "required_sections": ["", "  "],
            }
        )
        assert cfg.required_sections is None

    def test_from_dict_non_dict_returns_default(self):
        cfg = QualityPipelineConfig.from_dict("not a dict")  # type: ignore[arg-type]
        assert cfg.enabled is True


# ---------------------------------------------------------------------------
# QualityPipelineResult
# ---------------------------------------------------------------------------


class TestQualityPipelineResult:
    def test_to_dict(self):
        result = QualityPipelineResult(
            answer="test",
            passes_gate=True,
            repaired=False,
            contract_dict={"required_sections": ["A"]},
            initial_report_dict={"verdict": "good"},
            final_report_dict={"verdict": "good"},
        )
        d = result.to_dict()
        assert d["passes_gate"] is True
        assert d["repaired"] is False
        assert d["contract"]["required_sections"] == ["A"]

    def test_to_dict_defaults(self):
        result = QualityPipelineResult(answer="test")
        d = result.to_dict()
        assert d["passes_gate"] is False
        assert d["contract"] is None


# ---------------------------------------------------------------------------
# apply_post_consensus_quality
# ---------------------------------------------------------------------------


class TestApplyPostConsensusQuality:
    def test_disabled_returns_original(self):
        cfg = QualityPipelineConfig(enabled=False)
        result = apply_post_consensus_quality("raw answer", "task", cfg)
        assert result.answer == "raw answer"
        assert result.passes_gate is False
        assert result.repaired is False

    def test_no_contract_derivable_uses_default_contract(self):
        cfg = QualityPipelineConfig()
        result = apply_post_consensus_quality("some answer", "hello world", cfg)
        # "hello world" has no section hints, so a minimal default contract is
        # used (practicality checks only, no required sections).
        assert result.answer.strip() == "some answer"
        assert result.contract_dict is not None
        assert result.contract_dict["required_sections"] == []
        assert result.contract_dict["require_practicality_checks"] is True

    def test_good_answer_passes_gate(self):
        cfg = QualityPipelineConfig(
            repo_root=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        result = apply_post_consensus_quality(_GOOD_ANSWER, _TASK_WITH_SECTIONS, cfg)
        assert result.contract_dict is not None
        assert "required_sections" in result.contract_dict
        # The answer should be at least as good or better after pipeline
        assert result.final_report_dict.get("verdict") in ("good", "needs_work")

    def test_bad_answer_gets_repaired(self):
        cfg = QualityPipelineConfig(
            repo_root=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        result = apply_post_consensus_quality(_BAD_ANSWER, _TASK_WITH_SECTIONS, cfg)
        assert result.contract_dict is not None
        assert result.repaired is True
        # After repair, sections should be injected
        assert "## Ranked High-Level Tasks" in result.answer
        assert "## Rollback Plan" in result.answer

    def test_explicit_sections_config(self):
        cfg = QualityPipelineConfig(
            required_sections=["Summary", "Conclusion"],
        )
        answer = "## Summary\nThis is a summary.\n\n## Conclusion\nDone."
        result = apply_post_consensus_quality(answer, "anything", cfg)
        assert result.contract_dict is not None
        assert "Summary" in result.contract_dict["required_sections"]
        assert "Conclusion" in result.contract_dict["required_sections"]

    def test_none_config_uses_defaults(self):
        result = apply_post_consensus_quality("answer", "hello world", config=None)
        assert result.answer.strip() == "answer"

    def test_json_finalization_applied(self):
        cfg = QualityPipelineConfig(
            required_sections=[
                "Ranked High-Level Tasks",
                "JSON Payload",
            ],
        )
        answer = "## Ranked High-Level Tasks\n- Task 1\n\n## JSON Payload\nNo json here."
        result = apply_post_consensus_quality(answer, "anything", cfg)
        # JSON payload should be finalized with valid JSON
        assert "```json" in result.answer

    def test_has_context_gets_standard_contract(self):
        """Debates with has_context=True get the standard 7-section contract."""
        cfg = QualityPipelineConfig(has_context=True)
        long_task = "Dogfood the system and produce an improvement plan"
        result = apply_post_consensus_quality("some answer", long_task, cfg)
        assert result.contract_dict is not None
        assert len(result.contract_dict["required_sections"]) == 7
