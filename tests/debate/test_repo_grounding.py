"""Tests for deterministic repo-grounding practicality heuristics."""

from __future__ import annotations

from pathlib import Path

from aragora.debate.repo_grounding import (
    _is_subheader_line,
    _line_concreteness,
    _line_hedging_penalty,
    assess_repo_grounding,
)


def test_assess_repo_grounding_with_existing_paths():
    answer = """
## Ranked High-Level Tasks
- Implement stricter quality gate in aragora/cli/commands/debate.py with acceptance p95_latency <= 250ms.

## Suggested Subtasks
- Add unit coverage in tests/debate/test_output_quality.py and validate regression behavior.

## Owner module / file paths
- aragora/cli/commands/debate.py
- tests/debate/test_output_quality.py
"""
    report = assess_repo_grounding(answer)
    assert report.path_existence_rate == 1.0
    assert report.placeholder_hits == []
    assert report.first_batch_concreteness > 0.5
    assert report.practicality_score_10 >= 8.0


def test_assess_repo_grounding_penalizes_placeholders_and_missing_paths():
    answer = """
## Ranked High-Level Tasks
- [NEW] TBD workstream

## Suggested Subtasks
- [INFERRED] TODO

## Owner module / file paths
- aragora/not_real/missing_file.py
"""
    report = assess_repo_grounding(answer)
    # aragora/not_real/missing_file.py is a plausible new file proposal
    # (grandparent aragora/ exists), so it counts as half-grounded
    assert report.path_existence_rate == 0.5
    assert "aragora/not_real/missing_file.py" in report.new_paths
    assert report.missing_paths == []
    assert "new_marker" in report.placeholder_hits
    assert report.placeholder_rate > 0.0
    assert report.practicality_score_10 < 5.0


def test_assess_repo_grounding_handles_absolute_paths_under_repo():
    repo_root = Path(__file__).resolve().parents[2]
    absolute = repo_root / "aragora/debate/orchestrator.py"
    answer = f"""
## Owner module / file paths
- {absolute}
"""
    report = assess_repo_grounding(answer, repo_root=str(repo_root))
    assert report.path_existence_rate == 1.0
    assert "aragora/debate/orchestrator.py" in report.existing_paths
    assert all(not p.startswith("Users/") for p in report.mentioned_paths)


def test_assess_repo_grounding_handles_markdown_link_absolute_paths():
    repo_root = Path(__file__).resolve().parents[2]
    absolute = repo_root / "aragora/debate/orchestrator.py"
    answer = f"""
## Owner module / file paths
- [orchestrator.py]({absolute})
"""
    report = assess_repo_grounding(answer, repo_root=str(repo_root))
    assert "aragora/debate/orchestrator.py" in report.existing_paths


def test_fuzzy_path_matching_finds_close_matches():
    """LLM agents hallucinate shortened file names - fuzzy matching should recover."""
    answer = """
## Ranked High-Level Tasks
- Fix quality validation in aragora/debate/quality.py with threshold p95 <= 200ms.

## Owner module / file paths
- aragora/debate/quality.py
- aragora/debate/grounding.py
"""
    report = assess_repo_grounding(answer)
    # "quality.py" fuzzy-matches "output_quality.py" in aragora/debate/
    # "grounding.py" fuzzy-matches "repo_grounding.py" in aragora/debate/
    assert "aragora/debate/quality.py" in report.existing_paths
    assert "aragora/debate/grounding.py" in report.existing_paths
    assert report.path_existence_rate == 1.0


def test_line_concreteness_bare_filename_gets_partial_credit():
    """Bare filenames like output_quality.py score via _FILE_EXT_RE."""
    # Bare filename without path separator - no _PATH_RE match but _FILE_EXT_RE hits
    score_bare = _line_concreteness("Update output_quality.py to add validation")
    assert score_bare >= 0.55  # action_verb(0.35) + file_ext(0.2)

    # Full path still scores higher
    score_full = _line_concreteness("Update aragora/debate/output_quality.py to add validation")
    assert score_full >= 0.7  # action_verb(0.35) + path(0.35)
    assert score_full > score_bare


def test_expanded_verb_coverage():
    """New verbs (build, deploy, initialize, etc.) score concreteness."""
    for verb in ["build", "deploy", "configure", "initialize", "monitor", "scaffold", "verify"]:
        score = _line_concreteness(
            f"{verb.capitalize()} the authentication module for production readiness"
        )
        assert score >= 0.44, f"Verb '{verb}' scored {score}, expected >= 0.44"


def test_multi_section_concreteness_test_plan():
    """Test Plan section with test file references lifts concreteness."""
    answer = """
## Ranked High-Level Tasks
- Improve overall system performance

## Suggested Subtasks
- General improvements needed

## Test Plan
- Run pytest tests/debate/test_output_quality.py to verify scoring accuracy
- Run pytest tests/debate/test_repo_grounding.py::test_assess to validate grounding

## Gate Criteria
- coverage >= 80%
- p95_latency < 250ms
- error_rate < 1% over 15 minutes
"""
    report = assess_repo_grounding(answer)
    # Test Plan and Gate Criteria lines should push concreteness above 0.5
    assert report.first_batch_concreteness >= 0.55


def test_multi_section_concreteness_rollback_plan():
    """Rollback Plan with thresholds contributes to concreteness."""
    answer = """
## Ranked High-Level Tasks
- General improvements

## Rollback Plan
- If error_rate > 2% for 10 minutes, revert to previous deployment via aragora/ops/deploy.py
- Execute rollback script at scripts/rollback.sh within 5 minutes of detection
"""
    report = assess_repo_grounding(answer)
    assert report.first_batch_concreteness >= 0.55


def test_subheader_filtering():
    """Bold sub-header lines should be skipped, not scored."""
    assert _is_subheader_line("**Task 1 Subtasks:**") is True
    assert _is_subheader_line("**Task 1 Subtasks (Debate Engine):**") is True
    assert _is_subheader_line("  **Section Header**  ") is True
    # Not sub-headers:
    assert _is_subheader_line("- Implement **bold** feature in module") is False
    assert _is_subheader_line("Regular line of text") is False


def test_subheader_lines_excluded_from_scoring():
    """Sub-headers consuming line slots should not reduce concreteness."""
    answer = """
## Ranked High-Level Tasks
**Task 1 Subtasks:**
**Task 2 Subtasks:**
**Task 3 Subtasks:**
- Build authentication module in aragora/auth/handler.py with OAuth2 support
- Deploy monitoring dashboard to track p95_latency < 200ms
"""
    report = assess_repo_grounding(answer)
    # Without filtering, the 3 sub-headers would push actionable lines beyond the window.
    # With filtering, the actionable lines should be scored.
    assert report.first_batch_concreteness >= 0.55


def test_realistic_benchmark_output_scores_above_threshold():
    """Regression test: realistic benchmark output must score >= 6.0 practicality."""
    answer = """
## Ranked High-Level Tasks
- Implement rate limiting middleware in aragora/server/middleware/rate_limit.py with sliding window algorithm
- Add circuit breaker pattern to aragora/resilience/circuit_breaker.py for external API calls

## Suggested Subtasks
- Create unit tests in tests/server/test_rate_limit.py for window boundary conditions
- Wire rate limiter into aragora/server/unified_server.py request pipeline

## Owner module / file paths
- aragora/server/middleware/rate_limit.py
- aragora/resilience/circuit_breaker.py
- tests/server/test_rate_limit.py

## Test Plan
- Run pytest tests/server/test_rate_limit.py -v to verify window logic
- Run pytest tests/resilience/test_circuit_breaker.py to validate state transitions
- Execute integration smoke test via scripts/smoke_test.sh

## Rollback Plan
- If error_rate > 2% for 10 minutes, disable rate limiter via feature flag in aragora/config/flags.py
- Revert to previous deployment if p99_latency > 500ms persists for 5 minutes

## Gate Criteria
- p95_latency <= 250ms under load for 15 minutes
- error_rate < 1% over rolling 15 minute window
- test coverage >= 80% for new modules
"""
    report = assess_repo_grounding(answer)
    assert report.first_batch_concreteness >= 0.55
    assert report.practicality_score_10 >= 6.0, (
        f"Practicality {report.practicality_score_10} < 6.0 threshold"
    )


def test_hedging_penalty_reduces_line_concreteness():
    """Lines with hedging phrases score lower than equivalent lines without."""
    concrete = _line_concreteness("Add validation in aragora/debate/output_quality.py")
    hedged = _line_concreteness(
        "Consider adding validation in aragora/debate/output_quality.py as needed"
    )
    assert hedged < concrete


def test_tiered_hedging_severity():
    """HIGH-tier placeholders penalize more than LOW-tier weak commitment."""
    high = _line_hedging_penalty("Implement TBD module")
    medium = _line_hedging_penalty("Implement module as needed")
    low = _line_hedging_penalty("Should consider various approaches")
    assert high > medium > low


def test_hedging_penalty_capped_at_half():
    """Even many hedging matches can't reduce score below 50% of raw."""
    penalty = _line_hedging_penalty("[NEW] TBD placeholder TODO tk <fill>...")
    assert penalty == 0.5  # capped


def test_multi_line_averaging_penalizes_one_good_among_vague():
    """Mean-of-N scoring: one concrete line + vague lines scores lower than all concrete."""
    answer_one_good = """
## Ranked High-Level Tasks
- Implement rate limiter in aragora/debate/orchestrator.py with threshold p95 <= 200ms
- Improve system performance
- Enhance user experience
- Make things better
- Optimize code
"""
    answer_all_good = """
## Ranked High-Level Tasks
- Implement rate limiter in aragora/debate/orchestrator.py with threshold p95 <= 200ms
- Add circuit breaker to aragora/resilience/circuit_breaker.py for timeout >= 5s
- Create tests in tests/debate/test_orchestrator.py for arena timeout scenarios
- Wire health check in aragora/resilience/health.py with interval <= 30s
- Update aragora/server/startup.py to register new health endpoint
"""
    report_mixed = assess_repo_grounding(answer_one_good)
    report_all = assess_repo_grounding(answer_all_good)
    assert report_all.first_batch_concreteness > report_mixed.first_batch_concreteness


def test_llm_hedging_patterns_detected():
    """New LLM hedging patterns are flagged in placeholder hits."""
    answer = """
## Ranked High-Level Tasks
- Consider implementing a caching layer if applicable
- May require additional infrastructure depending on requirements

## Owner module / file paths
- aragora/debate/orchestrator.py
"""
    report = assess_repo_grounding(answer)
    assert any(
        h in report.placeholder_hits
        for h in ["consider_adding", "if_applicable", "may_require", "depending_on"]
    )


def test_concrete_verbs_score_full_credit():
    """Genuinely actionable verbs (benchmark, audit, cache, etc.) score full action credit."""
    concrete_verbs = [
        "decouple",
        "deprecate",
        "inject",
        "rewrite",
        "split",
        "measure",
        "benchmark",
        "profile",
        "audit",
        "lint",
        "throttle",
        "cache",
        "index",
        "persist",
        "flush",
        "assert",
        "mock",
        "parametrize",
        "isolate",
        "snapshot",
        "rename",
        "deduplicate",
        "prune",
        "compress",
        "encrypt",
    ]
    for verb in concrete_verbs:
        score = _line_concreteness(
            f"{verb.capitalize()} the debate output processing for better results"
        )
        assert score >= 0.44, f"Verb '{verb}' scored {score}, expected >= 0.44"


def test_directional_verbs_score_partial_credit():
    """Vague verbs like improve, enhance get partial credit (less than concrete verbs)."""
    directional_verbs = [
        "improve",
        "enhance",
        "strengthen",
        "upgrade",
        "reduce",
        "standardize",
        "consolidate",
        "simplify",
        "normalize",
    ]
    for verb in directional_verbs:
        score = _line_concreteness(
            f"{verb.capitalize()} the debate output processing for better results"
        )
        # Partial credit: 0.15 (directional) + 0.10 (6+ words) = 0.25
        assert 0.20 <= score <= 0.40, f"Verb '{verb}' scored {score}, expected 0.20-0.40"

    # Concrete verb should score strictly higher than directional verb
    concrete = _line_concreteness("Refactor the debate output processing for better results")
    directional = _line_concreteness("Improve the debate output processing for better results")
    assert concrete > directional, f"concrete={concrete} should be > directional={directional}"


def test_concretize_output_does_not_inject_paths():
    """concretize_output does NOT fabricate paths for vague lines."""
    from aragora.debate.phases.synthesis_generator import SynthesisGenerator

    synthesis = """## Ranked High-Level Tasks
1. Improve the consensus detection system
2. Update `aragora/debate/orchestrator.py:Arena.run()` to emit events — Verify: `pytest tests/debate/test_orchestrator.py -v`
"""
    repo_hint = """Key repository paths (use these, not invented paths):
  aragora/debate/: orchestrator.py, consensus.py, convergence.py
"""
    result = SynthesisGenerator.concretize_output(synthesis, repo_hint)

    # Line 1 has no path — concretize should NOT inject one
    lines = result.strip().split("\n")
    task1 = [l for l in lines if "Improve the consensus" in l][0]
    assert "aragora/" not in task1, "Should not inject paths into vague lines"

    # Line 2 was already concrete, should be unchanged
    assert "aragora/debate/orchestrator.py:Arena.run()" in result


def test_concretize_output_preserves_already_concrete_lines():
    """Lines with both paths and pytest commands are not modified."""
    from aragora.debate.phases.synthesis_generator import SynthesisGenerator

    synthesis = """## Ranked High-Level Tasks
1. Update `aragora/debate/orchestrator.py:Arena.run()` — Verify: `pytest tests/debate/test_orchestrator.py -v`
"""
    repo_hint = """Key repository paths:
  aragora/debate/: orchestrator.py
"""
    result = SynthesisGenerator.concretize_output(synthesis, repo_hint)
    assert result.strip() == synthesis.strip()


def test_concretize_output_adds_pytest_to_lines_with_paths():
    """Lines with paths but no pytest get a verify command added."""
    from aragora.debate.phases.synthesis_generator import SynthesisGenerator

    synthesis = """## Ranked High-Level Tasks
1. Refactor `aragora/debate/consensus.py` to use streaming events
"""
    repo_hint = """Key repository paths:
  aragora/debate/: consensus.py, orchestrator.py
"""
    result = SynthesisGenerator.concretize_output(synthesis, repo_hint)
    assert "pytest" in result.lower()
    assert "tests/debate/test_consensus.py" in result


def test_concretize_output_empty_inputs():
    """Empty synthesis or repo_hint returns synthesis unchanged."""
    from aragora.debate.phases.synthesis_generator import SynthesisGenerator

    assert SynthesisGenerator.concretize_output("", "hint") == ""
    assert SynthesisGenerator.concretize_output("text", "") == "text"
    assert SynthesisGenerator.concretize_output("", "") == ""
