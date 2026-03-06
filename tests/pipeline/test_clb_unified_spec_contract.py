"""CLB-003: Unified execution-grade spec contract for Prompt Engine and Interrogation.

Both paths must emit the same SpecBundle shape, preserving:
- unanswered questions in open_questions
- missing execution-grade fields in missing_required_fields
- is_execution_grade flag correctly derived
"""

from __future__ import annotations

from aragora.interrogation.crystallizer import CrystallizedSpec, MoSCoWItem
from aragora.interrogation.engine import InterrogationResult, PrioritizedQuestion
from aragora.pipeline.backbone_contracts import SpecBundle
from aragora.prompt_engine.types import Specification, SpecFile


# ---------------------------------------------------------------------------
# Shared contract shape invariants
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL_KEYS = {
    "title",
    "problem_statement",
    "objectives",
    "constraints",
    "acceptance_criteria",
    "verification_plan",
    "rollback_plan",
    "owner_file_scopes",
    "open_questions",
    "confidence",
    "source_kind",
    "missing_required_fields",
    "is_execution_grade",
}


def _assert_contract_shape(bundle: SpecBundle, label: str) -> None:
    d = bundle.to_dict()
    missing_keys = _REQUIRED_TOP_LEVEL_KEYS - set(d.keys())
    assert not missing_keys, f"CLB-003 ({label}): SpecBundle.to_dict() missing keys: {missing_keys}"


# ---------------------------------------------------------------------------
# Prompt engine path
# ---------------------------------------------------------------------------


def test_prompt_engine_path_emits_shared_contract_shape() -> None:
    """CLB-003: SpecBundle.from_prompt_spec() emits all required contract keys."""
    spec = Specification(
        title="Rate limiting",
        problem_statement="API endpoints are unprotected from abuse.",
        proposed_solution="Add token-bucket rate limiting at the gateway.",
        success_criteria=["95th-pct latency < 5ms overhead", "429 returned when limit exceeded"],
        file_changes=[
            SpecFile(
                path="aragora/gateway/rate_limiter.py", action="create", description="Rate limiter"
            )
        ],
        confidence=0.85,
    )
    bundle = SpecBundle.from_prompt_spec(spec)
    _assert_contract_shape(bundle, "prompt_engine")

    assert bundle.source_kind == "prompt_engine_spec"
    assert bundle.acceptance_criteria == [
        "95th-pct latency < 5ms overhead",
        "429 returned when limit exceeded",
    ]
    assert bundle.owner_file_scopes == ["aragora/gateway/rate_limiter.py"]
    assert bundle.open_questions == []  # prompt engine has no unanswered questions
    assert "constraints" in bundle.missing_required_fields
    assert bundle.is_execution_grade is False


def test_prompt_engine_path_preserves_missing_execution_fields() -> None:
    """CLB-003: Prompt engine path surfaces all missing fields needed for execution-grade spec."""
    spec = Specification(
        title="Minimal spec",
        problem_statement="Too vague.",
        proposed_solution="",
        success_criteria=[],
        confidence=0.2,
    )
    bundle = SpecBundle.from_prompt_spec(spec)

    assert set(bundle.missing_required_fields) >= {
        "constraints",
        "acceptance_criteria",
        "verification_plan",
    }
    assert bundle.is_execution_grade is False


# ---------------------------------------------------------------------------
# Interrogation path (from_interrogation_result — full pipeline path)
# ---------------------------------------------------------------------------


def test_interrogation_result_path_emits_shared_contract_shape() -> None:
    """CLB-003: SpecBundle.from_interrogation_result() emits all required contract keys."""
    crystallized = CrystallizedSpec(
        title="Rate limiting v2",
        problem_statement="Gateway lacks per-tenant rate limiting.",
        requirements=[
            MoSCoWItem(description="Per-tenant token bucket", priority="must"),
            MoSCoWItem(description="Config via admin API", priority="should"),
        ],
        success_criteria=["Tenant limit enforced within 1%", "Admin API reflects live config"],
        risks=[{"risk": "Config lag", "mitigation": "Cache with 1s TTL"}],
        constraints=["No breaking changes to existing rate limit API"],
    )
    result = InterrogationResult(
        original_prompt="Add per-tenant rate limiting",
        dimensions=["safety", "performance"],
        research_summary="Current gateway has global limits only.",
        prioritized_questions=[
            PrioritizedQuestion(
                question="Should limits be enforced at ingress or at the service?",
                why_it_matters="Latency implications.",
                priority_score=0.9,
            )
        ],
        crystallized_spec=crystallized,
    )
    bundle = SpecBundle.from_interrogation_result(result)
    _assert_contract_shape(bundle, "interrogation_result")

    assert bundle.source_kind == "interrogation_result"
    assert bundle.constraints == ["No breaking changes to existing rate limit API"]
    assert "Should limits be enforced at ingress" in bundle.open_questions[0]
    assert "owner_file_scopes" in bundle.missing_required_fields
    assert bundle.is_execution_grade is False


def test_interrogation_result_path_preserves_open_questions() -> None:
    """CLB-003: Unanswered questions from InterrogationResult appear in open_questions."""
    crystallized = CrystallizedSpec(
        title="T",
        problem_statement="P",
        requirements=[],
        success_criteria=[],
        risks=[],
        constraints=[],
    )
    result = InterrogationResult(
        original_prompt="vague request",
        dimensions=[],
        research_summary="",
        prioritized_questions=[
            PrioritizedQuestion(
                question="Who owns this system?",
                why_it_matters="Determines rollback authority.",
                priority_score=0.95,
            ),
            PrioritizedQuestion(
                question="What is the rollback SLA?",
                why_it_matters="Recovery time objective.",
                priority_score=0.7,
            ),
        ],
        crystallized_spec=crystallized,
    )
    bundle = SpecBundle.from_interrogation_result(result)

    assert len(bundle.open_questions) == 2
    assert "Who owns this system?" in bundle.open_questions
    assert "What is the rollback SLA?" in bundle.open_questions


# ---------------------------------------------------------------------------
# Cross-path shape parity
# ---------------------------------------------------------------------------


def test_both_paths_emit_same_top_level_keys() -> None:
    """CLB-003: Both prompt_engine and interrogation SpecBundle.to_dict() have identical top-level keys."""
    # Prompt engine path
    spec = Specification(
        title="Shape parity test",
        problem_statement="Verify both outputs share the same shape.",
        proposed_solution="Run both constructors and compare keys.",
        success_criteria=["Keys match"],
        confidence=0.7,
    )
    pe_bundle = SpecBundle.from_prompt_spec(spec)
    pe_dict = pe_bundle.to_dict()

    # Interrogation path
    crystallized = CrystallizedSpec(
        title="Shape parity test",
        problem_statement="Verify both outputs share the same shape.",
        requirements=[MoSCoWItem(description="Compare keys", priority="must")],
        success_criteria=["Keys match"],
        risks=[],
        constraints=[],
    )
    result = InterrogationResult(
        original_prompt="Compare shapes",
        dimensions=[],
        research_summary="",
        prioritized_questions=[],
        crystallized_spec=crystallized,
    )
    ir_bundle = SpecBundle.from_interrogation_result(result)
    ir_dict = ir_bundle.to_dict()

    pe_keys = set(pe_dict.keys())
    ir_keys = set(ir_dict.keys())
    assert pe_keys == ir_keys, (
        f"CLB-003: Shape mismatch between prompt_engine and interrogation paths.\n"
        f"  Only in prompt_engine: {pe_keys - ir_keys}\n"
        f"  Only in interrogation: {ir_keys - pe_keys}"
    )
