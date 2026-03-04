"""Tests for deterministic repo-grounding practicality heuristics."""

from __future__ import annotations

from aragora.debate.repo_grounding import assess_repo_grounding


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


def test_fuzzy_path_matching_finds_close_matches():
    """LLM agents hallucinate shortened file names — fuzzy matching should recover."""
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
