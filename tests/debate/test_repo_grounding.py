"""Tests for deterministic repo-grounding practicality heuristics."""

from __future__ import annotations

from aragora.debate.repo_grounding import (
    RepoGroundingReport,
    assess_repo_grounding,
    format_path_verification_summary,
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


def test_format_path_verification_summary_all_verified():
    report = RepoGroundingReport(
        mentioned_paths=["aragora/debate/orchestrator.py", "aragora/cli/main.py"],
        existing_paths=["aragora/debate/orchestrator.py", "aragora/cli/main.py"],
        missing_paths=[],
        new_paths=[],
        path_existence_rate=1.0,
        placeholder_hits=[],
        placeholder_rate=0.0,
        first_batch_concreteness=0.8,
        practicality_score_10=9.5,
    )
    summary = format_path_verification_summary(report)
    assert "2/2 paths verified" in summary
    assert "100%" in summary
    assert "NOT FOUND" not in summary
    assert "practicality=9.5/10" in summary


def test_format_path_verification_summary_with_missing():
    report = RepoGroundingReport(
        mentioned_paths=["a.py", "b.py", "c.py"],
        existing_paths=["a.py"],
        missing_paths=["c.py"],
        new_paths=["b.py"],
        path_existence_rate=0.5,
        placeholder_hits=["tbd"],
        placeholder_rate=0.05,
        first_batch_concreteness=0.35,
        practicality_score_10=4.2,
    )
    summary = format_path_verification_summary(report)
    assert "1/3 paths verified" in summary
    assert "1 new file(s) proposed" in summary
    assert "1 path(s) NOT FOUND" in summary
    assert "c.py" in summary
    assert "placeholders detected: tbd" in summary
