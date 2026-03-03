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
