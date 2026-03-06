"""Benchmark tests for synthesis practicality scoring.

Validates that _line_concreteness() and assess_repo_grounding() correctly
distinguish high-quality actionable outputs from vague/placeholder-filled
outputs.  Target: good outputs score >= 7.5/10, bad outputs score < 5.0/10.
"""

from __future__ import annotations

import pytest

from aragora.debate.repo_grounding import (
    _line_concreteness,
    assess_repo_grounding,
)


# ---------------------------------------------------------------------------
# _line_concreteness benchmarks
# ---------------------------------------------------------------------------


class TestLineConcreteness:
    """Verify _line_concreteness correctly rewards concrete lines and penalizes vague ones."""

    # --- High-concreteness lines (action verb + path + threshold) ---

    @pytest.mark.parametrize(
        "line,min_score",
        [
            # Action verb + file path + threshold
            (
                "Refactor `aragora/debate/orchestrator.py:Arena.run()` to emit phase-transition events — Verify: `pytest tests/debate/test_orchestrator.py -v`",
                0.7,
            ),
            # Action verb + file path (no threshold, but long enough for +0.1)
            (
                "Add validation to `aragora/server/handlers/auth.py:login()` for OIDC tokens",
                0.7,
            ),
            # Threshold + path (no action verb — path 0.35 + threshold 0.2 + length 0.1 = 0.65)
            (
                "coverage >= 80% on modified files in aragora/debate/",
                0.6,
            ),
            # pytest command line (has path + action verb)
            (
                "Run `pytest tests/debate/test_consensus.py -v --cov=aragora/debate/consensus`",
                0.7,
            ),
            # Gate criterion with numeric threshold and path (no action verb — 0.35 + 0.2 + 0.1 = 0.65)
            (
                "p95 latency <= 250ms for aragora/server/handlers/debate.py endpoints",
                0.6,
            ),
            # Serialize action with file path
            (
                "Serialize the response payload in aragora/server/handlers/export.py using msgpack",
                0.7,
            ),
        ],
        ids=[
            "action+path+verify",
            "action+path+detail",
            "threshold+path",
            "pytest+path",
            "gate+threshold+path",
            "serialize+path",
        ],
    )
    def test_high_concreteness_lines(self, line: str, min_score: float) -> None:
        score = _line_concreteness(line)
        assert score >= min_score, f"Expected >= {min_score}, got {score} for: {line!r}"

    # --- Low-concreteness lines (vague, no paths, no thresholds) ---

    @pytest.mark.parametrize(
        "line,max_score",
        [
            ("Improve the system", 0.25),
            ("Enhance performance", 0.25),
            ("TBD", 0.0),
            ("", 0.0),
            ("Consider adding better error handling", 0.35),
            ("Various approaches could be explored", 0.25),
            ("This should be improved as needed", 0.25),
            ("[NEW] placeholder for future work", 0.15),
        ],
        ids=[
            "improve_vague",
            "enhance_vague",
            "tbd",
            "empty",
            "consider_adding_hedge",
            "various_approaches",
            "should_as_needed",
            "new_placeholder",
        ],
    )
    def test_low_concreteness_lines(self, line: str, max_score: float) -> None:
        score = _line_concreteness(line)
        assert score <= max_score, f"Expected <= {max_score}, got {score} for: {line!r}"

    def test_action_verb_beats_directional_verb(self) -> None:
        """Action verbs (add, create) should score higher than directional (improve, enhance)."""
        action_score = _line_concreteness("Add rate limiting to the endpoint handler module")
        directional_score = _line_concreteness(
            "Improve rate limiting in the endpoint handler module"
        )
        assert action_score > directional_score

    def test_path_adds_significant_score(self) -> None:
        """Lines with file paths should score notably higher than those without."""
        with_path = _line_concreteness("Add validation to aragora/debate/orchestrator.py")
        without_path = _line_concreteness("Add validation to the orchestrator")
        assert with_path >= without_path + 0.2

    def test_threshold_adds_score(self) -> None:
        """Numeric thresholds (>= 80%) should boost the concreteness score."""
        with_threshold = _line_concreteness("coverage >= 80% on modified files")
        without_threshold = _line_concreteness("coverage on modified files should be high")
        assert with_threshold > without_threshold

    def test_hedging_reduces_score(self) -> None:
        """Hedging phrases like 'as needed' should reduce concreteness."""
        clean = _line_concreteness("Add input validation to aragora/server/handlers/auth.py")
        hedged = _line_concreteness(
            "Add input validation to aragora/server/handlers/auth.py as needed"
        )
        assert clean > hedged


# ---------------------------------------------------------------------------
# assess_repo_grounding benchmarks
# ---------------------------------------------------------------------------


class TestAssessRepoGroundingBenchmarks:
    """Benchmark tests ensuring good outputs score >= 7.5 and bad outputs score < 5.0."""

    def test_good_output_scores_above_threshold(self) -> None:
        """A well-structured synthesis with all 7 sections should score >= 7.5."""
        good_output = """\
## Ranked High-Level Tasks
1. **Refactor `aragora/debate/orchestrator.py:Arena.run()` to extract phase dispatch into separate methods** — Verify: `pytest tests/debate/test_orchestrator.py -v`
2. **Add circuit-breaker wrapper in `aragora/resilience/circuit_breaker.py:CircuitBreaker.call()` for agent timeouts** — Verify: `pytest tests/resilience/test_circuit_breaker.py -v`
3. **Migrate consensus detection from `aragora/debate/consensus.py` to use weighted evidence scoring** — Verify: `pytest tests/debate/test_consensus.py -v`

## Suggested Subtasks
- Extract `_dispatch_phase()` helper from `aragora/debate/orchestrator.py` — Verify: `pytest tests/debate/test_orchestrator.py::test_dispatch_phase -v`
- Add `TimeoutError` handling in `aragora/agents/airlock.py:AirlockProxy.forward()` — Verify: `pytest tests/agents/test_airlock.py -v`

## Owner module / file paths
- `aragora/debate/orchestrator.py`
- `aragora/resilience/circuit_breaker.py`
- `aragora/debate/consensus.py`
- `aragora/agents/airlock.py`

## Test Plan
- `pytest tests/debate/test_orchestrator.py -v --cov=aragora/debate/orchestrator --cov-fail-under=85`
- `pytest tests/resilience/test_circuit_breaker.py -v`
- `pytest tests/debate/test_consensus.py -v`
- Coverage threshold: >= 85% on modified files

## Rollback Plan
- **Trigger**: If `pytest tests/debate/ -v` fails or coverage drops below 85%
- **Action**: `git revert HEAD` to undo the refactor commit
- **Trigger**: If p95 latency exceeds 500ms after deploy
- **Action**: Revert the deploy and restore previous container image

## Gate Criteria
- Test coverage >= 85% on modified files
- p95 latency <= 500ms for debate endpoints
- 0 new lint errors (ruff check passes)
- All 7 required section headers present
- Error rate < 1.0% on staging for 30 minutes

## JSON Payload
```json
{
  "tasks": 3,
  "subtasks": 2,
  "owner_files": 4,
  "coverage_threshold": 85,
  "latency_threshold_ms": 500
}
```
"""
        report = assess_repo_grounding(good_output)
        assert report.practicality_score_10 >= 7.5, (
            f"Good output scored {report.practicality_score_10}/10, expected >= 7.5. "
            f"concreteness={report.first_batch_concreteness}, "
            f"path_rate={report.path_existence_rate}, "
            f"placeholder_rate={report.placeholder_rate}"
        )

    def test_bad_output_scores_below_threshold(self) -> None:
        """A vague output with placeholders and no paths should score < 5.0."""
        bad_output = """\
## Summary
The debate covered various approaches to improving the system.

## Recommendations
- Improve overall performance as needed
- Enhance the user experience
- Consider adding better error handling
- TBD: determine the best approach
- Various methods could be explored

## Next Steps
- To be determined based on requirements
- Future enhancement: add monitoring
- Optional: implement caching if applicable
"""
        report = assess_repo_grounding(bad_output)
        assert report.practicality_score_10 < 5.0, (
            f"Bad output scored {report.practicality_score_10}/10, expected < 5.0. "
            f"concreteness={report.first_batch_concreteness}, "
            f"placeholder_rate={report.placeholder_rate}"
        )

    def test_partial_output_scores_middle(self) -> None:
        """An output with some structure but missing concreteness lands in 4-7 range."""
        partial_output = """\
## Ranked High-Level Tasks
1. Improve the debate orchestrator performance
2. Enhance consensus detection accuracy
3. Strengthen error handling across modules

## Suggested Subtasks
- Add more tests
- Update documentation

## Owner module / file paths
- aragora/debate/orchestrator.py

## Test Plan
- Run the test suite

## Rollback Plan
- Revert if something breaks

## Gate Criteria
- Tests should pass
- No regressions

## JSON Payload
```json
{"status": "planned"}
```
"""
        report = assess_repo_grounding(partial_output)
        assert 3.0 <= report.practicality_score_10 <= 7.5, (
            f"Partial output scored {report.practicality_score_10}/10, expected 3.0-7.5. "
            f"concreteness={report.first_batch_concreteness}"
        )

    def test_placeholder_heavy_output_penalized(self) -> None:
        """Output with heavy placeholder usage should be penalized severely."""
        placeholder_output = """\
## Ranked High-Level Tasks
1. [NEW] TBD workstream for system improvement
2. [INFERRED] TODO: determine approach
3. Placeholder task for future enhancement...

## Suggested Subtasks
- [Section not produced]
- TBD

## Owner module / file paths
- <fill in paths>

## Test Plan
- To be determined

## Rollback Plan
- TBD

## Gate Criteria
- As appropriate

## JSON Payload
```json
{}
```
"""
        report = assess_repo_grounding(placeholder_output)
        assert report.placeholder_rate > 0.0
        assert report.practicality_score_10 < 4.0, (
            f"Placeholder-heavy output scored {report.practicality_score_10}/10, expected < 4.0"
        )

    def test_new_action_verbs_recognized(self) -> None:
        """Newly added action verbs (migrate, extract, inject, etc.) should score well."""
        output = """\
## Ranked High-Level Tasks
1. **Migrate `aragora/storage/postgres_store.py` from sync to async driver** — Verify: `pytest tests/storage/test_postgres.py -v`
2. **Extract shared validation logic into `aragora/debate/validators.py`** — Verify: `pytest tests/debate/test_validators.py -v`
3. **Inject telemetry hooks into `aragora/observability/tracing.py`** — Verify: `pytest tests/observability/test_tracing.py -v`

## Suggested Subtasks
- Configure rate limiting in `aragora/server/handlers/auth.py` — Verify: `pytest tests/server/test_auth.py -v`
- Benchmark `aragora/debate/orchestrator.py:Arena.run()` latency — Verify: `pytest tests/debate/test_bench.py -v`

## Owner module / file paths
- `aragora/storage/postgres_store.py`
- `aragora/debate/validators.py`
- `aragora/observability/tracing.py`

## Test Plan
- `pytest tests/storage/test_postgres.py -v --cov-fail-under=80`
- `pytest tests/debate/test_validators.py -v`
- Coverage >= 80% on modified files

## Rollback Plan
- **Trigger**: If migration tests fail
- **Action**: `git revert HEAD` to restore sync driver

## Gate Criteria
- Coverage >= 80% on modified files
- p95 latency <= 300ms
- 0 new lint errors

## JSON Payload
```json
{"tasks": 3, "subtasks": 2, "coverage_threshold": 80}
```
"""
        report = assess_repo_grounding(output)
        assert report.practicality_score_10 >= 7.0, (
            f"New-verb output scored {report.practicality_score_10}/10, expected >= 7.0. "
            f"concreteness={report.first_batch_concreteness}"
        )

    def test_concreteness_spread_across_sections(self) -> None:
        """All scored sections (Tasks, Subtasks, Test Plan, Rollback, Gate) contribute."""
        output = """\
## Ranked High-Level Tasks
1. **Add request validation to `aragora/server/handlers/debate.py`** — Verify: `pytest tests/server/test_debate_handler.py -v`

## Suggested Subtasks
- Validate JSON schema in `aragora/server/handlers/debate.py:handle_create()` — Verify: `pytest tests/server/test_debate_handler.py::test_schema_validation -v`

## Owner module / file paths
- `aragora/server/handlers/debate.py`

## Test Plan
- `pytest tests/server/test_debate_handler.py -v --cov=aragora/server/handlers/debate --cov-fail-under=90`

## Rollback Plan
- **Trigger**: If `pytest tests/server/ -v` shows any failures
- **Action**: `git revert HEAD` and redeploy previous version

## Gate Criteria
- Coverage >= 90% on `aragora/server/handlers/debate.py`
- p95 latency <= 200ms for POST /api/v1/debates
- 0 new lint errors
- All existing tests must pass

## JSON Payload
```json
{"tasks": 1, "subtasks": 1, "coverage_threshold": 90}
```
"""
        report = assess_repo_grounding(output)
        assert report.first_batch_concreteness >= 0.6, (
            f"Section-spread concreteness {report.first_batch_concreteness}, expected >= 0.6"
        )
        assert report.practicality_score_10 >= 7.0
