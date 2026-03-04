"""Tests for deterministic repo-grounding practicality heuristics."""

from __future__ import annotations

from pathlib import Path

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
    from aragora.debate.repo_grounding import _line_concreteness

    # Bare filename without path separator - no _PATH_RE match but _FILE_EXT_RE hits
    score_bare = _line_concreteness("Update output_quality.py to add validation")
    assert score_bare >= 0.55  # action_verb(0.35) + file_ext(0.2)

    # Full path still scores higher
    score_full = _line_concreteness("Update aragora/debate/output_quality.py to add validation")
    assert score_full >= 0.7  # action_verb(0.35) + path(0.35)
    assert score_full > score_bare
