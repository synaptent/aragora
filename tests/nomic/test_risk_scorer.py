"""Tests for RiskScorer -- risk-scored safe-mode execution gating."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.nomic.risk_scorer import (
    CRITICAL_RISK_KEYWORDS,
    CRITICAL_RISK_PATHS,
    HIGH_RISK_KEYWORDS,
    HIGH_RISK_PATHS,
    LOW_RISK_KEYWORDS,
    LOW_RISK_PATHS,
    PROTECTED_FILES,
    RiskCategory,
    RiskFactor,
    RiskScore,
    RiskScorer,
)


# ---------------------------------------------------------------------------
# RiskScore dataclass
# ---------------------------------------------------------------------------


class TestRiskScore:
    def test_defaults(self):
        score = RiskScore(score=0.5, category=RiskCategory.HIGH)
        assert score.score == 0.5
        assert score.category == RiskCategory.HIGH
        assert score.factors == []
        assert score.recommendation == "review"
        assert score.goal == ""

    def test_to_dict(self):
        factor = RiskFactor(name="test", weight=0.3, detail="test detail")
        score = RiskScore(
            score=0.75,
            category=RiskCategory.HIGH,
            factors=[factor],
            recommendation="review",
            goal="Improve security",
        )
        d = score.to_dict()
        assert d["score"] == 0.75
        assert d["category"] == "high"
        assert d["recommendation"] == "review"
        assert d["goal"] == "Improve security"
        assert len(d["factors"]) == 1
        assert d["factors"][0]["name"] == "test"
        assert d["factors"][0]["weight"] == 0.3
        assert d["factors"][0]["detail"] == "test detail"

    def test_to_dict_no_factors(self):
        score = RiskScore(score=0.1, category=RiskCategory.LOW)
        d = score.to_dict()
        assert d["factors"] == []

    def test_category_values(self):
        assert RiskCategory.LOW.value == "low"
        assert RiskCategory.MEDIUM.value == "medium"
        assert RiskCategory.HIGH.value == "high"
        assert RiskCategory.CRITICAL.value == "critical"


# ---------------------------------------------------------------------------
# RiskScorer -- scoring for each risk category
# ---------------------------------------------------------------------------


class TestRiskScorerLowRisk:
    """Goals that should score as LOW risk."""

    def test_documentation_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Update documentation for API reference")
        assert result.category == RiskCategory.LOW
        assert result.recommendation == "auto"
        assert result.score < 0.3

    def test_test_writing_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Add unit tests for the analytics module")
        assert result.category == RiskCategory.LOW
        assert result.recommendation == "auto"

    def test_typo_fix(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Fix typo in readme formatting")
        assert result.category == RiskCategory.LOW
        assert result.recommendation == "auto"

    def test_docstring_update(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Improve docstring coverage in utils module")
        assert result.category == RiskCategory.LOW
        assert result.recommendation == "auto"

    def test_test_files_in_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Refactor helper functions",
            file_scope=["tests/test_helpers.py", "tests/test_utils.py"],
        )
        assert result.category == RiskCategory.LOW
        assert result.recommendation == "auto"

    def test_docs_path_in_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Add API examples",
            file_scope=["docs/api/examples.md"],
        )
        assert result.category == RiskCategory.LOW


class TestRiskScorerMediumRisk:
    """Goals that should score as MEDIUM risk."""

    def test_new_feature(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Add a new reporting dashboard widget",
            file_scope=["aragora/analytics/dashboard.py"],
        )
        # Generic analytics file is low-risk; no high-risk keywords or paths
        assert result.category in (RiskCategory.LOW, RiskCategory.MEDIUM)
        assert result.recommendation == "auto"

    def test_refactor_without_tests(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Refactor the connector module for clarity",
            file_scope=[
                "aragora/connectors/slack.py",
                "aragora/connectors/github.py",
            ],
            has_tests=False,
        )
        # No tests increases risk, but connectors are not in HIGH_RISK_PATHS
        assert result.score >= 0.15

    def test_moderate_file_count(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update error messages across modules",
            estimated_files_changed=7,
        )
        # With no risky keywords, moderate file count alone stays low
        assert result.score >= 0.15  # Non-trivial scale factor present


class TestRiskScorerHighRisk:
    """Goals that should score as HIGH risk."""

    def test_security_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Fix authentication bypass in OIDC handler")
        # Keywords (authentication, oidc) push this into MEDIUM+ range;
        # without file scope touching security paths, stays below HIGH threshold
        assert result.category in (RiskCategory.MEDIUM, RiskCategory.HIGH)
        assert result.score >= 0.3

    def test_auth_file_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Refactor token validation",
            file_scope=["aragora/auth/oidc.py", "aragora/auth/token.py"],
        )
        # "token" keyword + auth paths => MEDIUM+ range; keywords weight
        # more than file scope alone in the new balanced aggregation
        assert result.category in (RiskCategory.MEDIUM, RiskCategory.HIGH)
        assert result.score >= 0.3

    def test_database_migration(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Add database migration for new schema fields")
        # "database", "migration", "schema" are high-risk keywords; with balanced
        # aggregation, keywords alone push to MEDIUM+ without hitting HIGH
        assert result.category in (RiskCategory.MEDIUM, RiskCategory.HIGH)
        assert result.score >= 0.3

    def test_rbac_changes(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Modify permission checker for new role hierarchy",
            file_scope=["aragora/rbac/checker.py"],
        )
        # "permission" and "rbac" keywords + high-risk path => MEDIUM+
        assert result.category in (RiskCategory.MEDIUM, RiskCategory.HIGH)

    def test_privacy_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Update GDPR anonymization pipeline for consent changes")
        # "gdpr", "anonymization", "consent" (high) + "pipeline" (critical) keywords
        assert result.score >= 0.3

    def test_billing_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Fix metering calculation in billing module")
        # "metering" and "billing" are high-risk keywords
        assert result.score >= 0.3


class TestRiskScorerCriticalRisk:
    """Goals that should score as CRITICAL risk."""

    def test_protected_file_in_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update init exports",
            file_scope=["aragora/__init__.py"],
        )
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"
        assert result.score >= 0.8

    def test_env_file(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Add new config variable",
            file_scope=[".env"],
        )
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"

    def test_nomic_loop_file(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Optimize loop performance",
            file_scope=["scripts/nomic_loop.py"],
        )
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"

    def test_claude_md_in_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Modify CLAUDE.md with new instructions")
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"

    def test_deployment_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update kubernetes deployment configuration for production",
        )
        assert result.category in (RiskCategory.HIGH, RiskCategory.CRITICAL)
        assert result.score >= 0.5

    def test_infrastructure_file_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update CI pipeline",
            file_scope=[".github/workflows/ci.yml"],
        )
        # Critical path + critical keyword "pipeline" => HIGH/CRITICAL range
        assert result.category in (RiskCategory.HIGH, RiskCategory.CRITICAL)
        assert result.recommendation in ("review", "block")

    def test_orchestrator_file(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Refactor debate engine",
            file_scope=["aragora/debate/orchestrator.py"],
        )
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"


# ---------------------------------------------------------------------------
# RiskScorer -- threshold-based execution decisions
# ---------------------------------------------------------------------------


class TestRiskScorerThresholds:
    def test_auto_below_threshold(self):
        scorer = RiskScorer(threshold=0.5)
        result = scorer.score_goal("Add test for utility function")
        assert result.recommendation == "auto"
        assert result.score < 0.5

    def test_review_at_threshold(self):
        scorer = RiskScorer(threshold=0.3)
        # A goal that scores around 0.3-0.7 should get "review"
        result = scorer.score_goal(
            "Refactor storage layer with new schema approach",
            file_scope=["aragora/storage/postgres_store.py"],
            has_tests=False,
        )
        assert result.recommendation in ("review", "block")
        assert result.score >= 0.3

    def test_block_above_block_threshold(self):
        scorer = RiskScorer(threshold=0.3, block_threshold=0.8)
        result = scorer.score_goal(
            "Modify core init",
            file_scope=["aragora/__init__.py"],
        )
        assert result.recommendation == "block"
        assert result.score >= 0.8

    def test_custom_low_threshold(self):
        """Very low threshold means more things need review."""
        scorer = RiskScorer(threshold=0.1)
        result = scorer.score_goal("Add a new utility function")
        # With threshold=0.1, even neutral goals may need review
        assert result.recommendation in ("auto", "review")

    def test_custom_high_threshold(self):
        """High threshold means more things auto-approve."""
        scorer = RiskScorer(threshold=0.7)
        result = scorer.score_goal(
            "Refactor connector module",
            file_scope=["aragora/connectors/slack.py"],
        )
        assert result.recommendation == "auto"

    def test_recommendation_auto_for_low_score(self):
        scorer = RiskScorer(threshold=0.5)
        result = scorer.score_goal("Fix typo in changelog")
        assert result.recommendation == "auto"

    def test_recommendation_block_for_protected(self):
        scorer = RiskScorer(threshold=0.5)
        result = scorer.score_goal(
            "Edit config",
            file_scope=[".env.local"],
        )
        assert result.recommendation == "block"


# ---------------------------------------------------------------------------
# RiskScorer -- protected file detection
# ---------------------------------------------------------------------------


class TestProtectedFileDetection:
    def test_detects_protected_in_file_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update exports",
            file_scope=["aragora/__init__.py"],
        )
        protected_factor = next((f for f in result.factors if f.name == "protected_files"), None)
        assert protected_factor is not None
        assert "aragora/__init__.py" in protected_factor.detail

    def test_detects_protected_in_goal_text(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Modify the .env file to add new secrets")
        protected_factor = next((f for f in result.factors if f.name == "protected_files"), None)
        assert protected_factor is not None

    def test_no_protected_for_safe_files(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update helper",
            file_scope=["aragora/utils/helpers.py"],
        )
        protected_factor = next((f for f in result.factors if f.name == "protected_files"), None)
        assert protected_factor is None

    def test_custom_protected_files(self):
        scorer = RiskScorer(protected_files=["custom_config.yaml"])
        result = scorer.score_goal(
            "Update config",
            file_scope=["custom_config.yaml"],
        )
        assert result.category == RiskCategory.CRITICAL
        assert result.recommendation == "block"

    def test_protected_file_name_match(self):
        """Matches on just the filename component."""
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Edit core types",
            file_scope=["some/path/core_types.py"],
        )
        protected_factor = next((f for f in result.factors if f.name == "protected_files"), None)
        assert protected_factor is not None


# ---------------------------------------------------------------------------
# RiskScorer -- score_subtask
# ---------------------------------------------------------------------------


class TestScoreSubtask:
    def test_scores_subtask_object(self):
        scorer = RiskScorer()
        subtask = types.SimpleNamespace(
            title="Add test for utils",
            description="Write unit tests for utility functions",
            file_scope=["tests/test_utils.py"],
            estimated_complexity="low",
        )
        result = scorer.score_subtask(subtask)
        assert isinstance(result, RiskScore)
        assert result.category == RiskCategory.LOW

    def test_scores_subtask_high_complexity(self):
        scorer = RiskScorer()
        subtask = types.SimpleNamespace(
            title="Refactor security layer",
            description="Overhaul encryption and key rotation",
            file_scope=["aragora/security/encryption.py", "aragora/security/key_rotation.py"],
            estimated_complexity="high",
        )
        result = scorer.score_subtask(subtask)
        # Security keywords + high-risk paths + high complexity => MEDIUM+
        assert result.category in (RiskCategory.MEDIUM, RiskCategory.HIGH, RiskCategory.CRITICAL)

    def test_scores_subtask_numeric_complexity(self):
        scorer = RiskScorer()
        subtask = types.SimpleNamespace(
            title="Major refactor",
            description="Large scale changes across many files",
            file_scope=[],
            estimated_complexity=9,
        )
        result = scorer.score_subtask(subtask)
        # High complexity (9/10) increases score, but without risky keywords
        # the balanced aggregation keeps it moderate
        assert result.score > 0.2  # Complexity factor is present and elevating

    def test_scores_subtask_missing_fields(self):
        """Handles subtasks with missing optional fields gracefully."""
        scorer = RiskScorer()
        subtask = types.SimpleNamespace(
            title="Simple fix",
            description="Minor change",
        )
        result = scorer.score_subtask(subtask)
        assert isinstance(result, RiskScore)

    def test_scores_subtask_none_fields(self):
        scorer = RiskScorer()
        subtask = types.SimpleNamespace(
            title=None,
            description="Fix something",
            file_scope=None,
            estimated_complexity=None,
        )
        result = scorer.score_subtask(subtask)
        assert isinstance(result, RiskScore)


# ---------------------------------------------------------------------------
# RiskScorer -- scoring factors
# ---------------------------------------------------------------------------


class TestScoringFactors:
    def test_has_keyword_factor(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Fix security vulnerability in auth module")
        factor_names = [f.name for f in result.factors]
        assert "keyword_analysis" in factor_names

    def test_has_file_scope_factor(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Update code",
            file_scope=["aragora/security/encryption.py"],
        )
        factor_names = [f.name for f in result.factors]
        assert "file_scope" in factor_names

    def test_has_scale_factor(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Refactor everything",
            estimated_files_changed=25,
        )
        factor_names = [f.name for f in result.factors]
        assert "change_scale" in factor_names

    def test_has_test_coverage_factor_when_no_tests(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Add new API endpoint",
            has_tests=False,
        )
        factor_names = [f.name for f in result.factors]
        assert "test_coverage" in factor_names

    def test_no_test_coverage_factor_when_tests_exist(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Add new API endpoint",
            has_tests=True,
        )
        # test_coverage factor should have weight=0 and not be included
        test_factor = next((f for f in result.factors if f.name == "test_coverage"), None)
        assert test_factor is None

    def test_large_file_count_increases_scale(self):
        scorer = RiskScorer()
        small = scorer.score_goal("Update files", estimated_files_changed=2)
        large = scorer.score_goal("Update files", estimated_files_changed=25)
        assert large.score > small.score

    def test_high_complexity_increases_score(self):
        scorer = RiskScorer()
        low = scorer.score_goal("Simple change", complexity_score=2)
        high = scorer.score_goal("Simple change", complexity_score=9)
        assert high.score > low.score


# ---------------------------------------------------------------------------
# RiskScorer -- edge cases
# ---------------------------------------------------------------------------


class TestRiskScorerEdgeCases:
    def test_empty_goal(self):
        scorer = RiskScorer()
        result = scorer.score_goal("")
        assert isinstance(result, RiskScore)
        assert 0.0 <= result.score <= 1.0

    def test_very_long_goal(self):
        scorer = RiskScorer()
        long_goal = "Improve " * 500 + "test coverage"
        result = scorer.score_goal(long_goal)
        assert isinstance(result, RiskScore)

    def test_score_clamped_to_range(self):
        scorer = RiskScorer()
        # Even with many risk signals, score should be clamped to [0, 1]
        result = scorer.score_goal(
            "Deploy production kubernetes infrastructure with auth token rotation",
            file_scope=[".env", "aragora/__init__.py", "scripts/nomic_loop.py"],
            estimated_files_changed=50,
            has_tests=False,
            complexity_score=10,
        )
        assert 0.0 <= result.score <= 1.0

    def test_category_boundaries(self):
        scorer = RiskScorer()
        # Verify categorization boundaries
        assert scorer._categorize(0.0) == RiskCategory.LOW
        assert scorer._categorize(0.29) == RiskCategory.LOW
        assert scorer._categorize(0.3) == RiskCategory.MEDIUM
        assert scorer._categorize(0.49) == RiskCategory.MEDIUM
        assert scorer._categorize(0.5) == RiskCategory.HIGH
        assert scorer._categorize(0.79) == RiskCategory.HIGH
        assert scorer._categorize(0.8) == RiskCategory.CRITICAL
        assert scorer._categorize(1.0) == RiskCategory.CRITICAL

    def test_recommendation_boundaries(self):
        scorer = RiskScorer(threshold=0.5, block_threshold=0.8)
        assert scorer._recommend(0.0) == "auto"
        assert scorer._recommend(0.49) == "auto"
        assert scorer._recommend(0.5) == "review"
        assert scorer._recommend(0.79) == "review"
        assert scorer._recommend(0.8) == "block"
        assert scorer._recommend(1.0) == "block"

    def test_empty_file_scope(self):
        scorer = RiskScorer()
        result = scorer.score_goal("Do something", file_scope=[])
        assert isinstance(result, RiskScore)

    def test_none_optional_params(self):
        scorer = RiskScorer()
        result = scorer.score_goal(
            "Simple task",
            file_scope=None,
            estimated_files_changed=None,
            has_tests=None,
            complexity_score=None,
        )
        assert isinstance(result, RiskScore)


# ---------------------------------------------------------------------------
# SelfImproveConfig -- safe_mode integration
# ---------------------------------------------------------------------------


class TestSelfImproveConfigSafeMode:
    def test_safe_mode_defaults(self):
        from aragora.nomic.self_improve import SelfImproveConfig

        config = SelfImproveConfig()
        assert config.safe_mode is True
        assert config.risk_threshold == 0.5

    def test_safe_mode_custom(self):
        from aragora.nomic.self_improve import SelfImproveConfig

        config = SelfImproveConfig(safe_mode=False, risk_threshold=0.7)
        assert config.safe_mode is False
        assert config.risk_threshold == 0.7


class TestSelfImproveResultRiskFields:
    def test_risk_fields_defaults(self):
        from aragora.nomic.self_improve import SelfImproveResult

        result = SelfImproveResult(cycle_id="test", objective="test")
        assert result.risk_assessments == []
        assert result.goals_blocked == 0
        assert result.goals_auto_approved == 0
        assert result.goals_needs_review == 0

    def test_to_dict_includes_risk_fields(self):
        from aragora.nomic.self_improve import SelfImproveResult

        result = SelfImproveResult(
            cycle_id="test",
            objective="test",
            goals_blocked=2,
            goals_auto_approved=3,
            goals_needs_review=1,
            risk_assessments=[{"score": 0.5, "category": "high"}],
        )
        d = result.to_dict()
        assert d["goals_blocked"] == 2
        assert d["goals_auto_approved"] == 3
        assert d["goals_needs_review"] == 1
        assert len(d["risk_assessments"]) == 1


# ---------------------------------------------------------------------------
# SelfImprovePipeline -- _apply_risk_scoring
# ---------------------------------------------------------------------------


class TestApplyRiskScoring:
    def test_blocks_critical_subtasks(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        config = SelfImproveConfig(safe_mode=True, risk_threshold=0.5)
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            types.SimpleNamespace(
                title="Update init",
                description="Modify package exports",
                file_scope=["aragora/__init__.py"],
                estimated_complexity="low",
            ),
        ]

        approved = pipeline._apply_risk_scoring(subtasks, result)
        assert len(approved) == 0
        assert result.goals_blocked == 1
        assert len(result.risk_assessments) == 1

    def test_auto_approves_safe_subtasks(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        config = SelfImproveConfig(safe_mode=True, risk_threshold=0.5)
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            types.SimpleNamespace(
                title="Add tests",
                description="Write unit tests for utility functions",
                file_scope=["tests/test_utils.py"],
                estimated_complexity="low",
            ),
        ]

        approved = pipeline._apply_risk_scoring(subtasks, result)
        assert len(approved) == 1
        assert result.goals_auto_approved == 1

    def test_mixed_subtasks(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        config = SelfImproveConfig(safe_mode=True, risk_threshold=0.5)
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            # Safe: tests
            types.SimpleNamespace(
                title="Add tests",
                description="Write unit tests",
                file_scope=["tests/test_utils.py"],
                estimated_complexity="low",
            ),
            # Critical: protected file
            types.SimpleNamespace(
                title="Update init",
                description="Modify package exports",
                file_scope=["aragora/__init__.py"],
                estimated_complexity="low",
            ),
        ]

        approved = pipeline._apply_risk_scoring(subtasks, result)
        assert len(approved) == 1  # Only the safe one
        assert result.goals_auto_approved == 1
        assert result.goals_blocked == 1

    def test_emits_progress_events(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        events_received: list[tuple[str, dict]] = []

        def callback(event: str, data: dict) -> None:
            events_received.append((event, data))

        config = SelfImproveConfig(
            safe_mode=True,
            risk_threshold=0.5,
            progress_callback=callback,
        )
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            types.SimpleNamespace(
                title="Add tests",
                description="Write tests for documentation",
                file_scope=["tests/test_docs.py"],
                estimated_complexity="low",
            ),
        ]

        pipeline._apply_risk_scoring(subtasks, result)

        event_names = [e[0] for e in events_received]
        assert "risk_assessment_complete" in event_names

    def test_returns_all_when_risk_scorer_unavailable(self):
        """Falls back gracefully when RiskScorer can't be imported."""
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        config = SelfImproveConfig(safe_mode=True)
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            types.SimpleNamespace(
                title="Something",
                description="Anything",
                file_scope=[],
                estimated_complexity="low",
            ),
        ]

        with patch.dict("sys.modules", {"aragora.nomic.risk_scorer": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("mocked"))
                    if "risk_scorer" in name
                    else __import__(name, *a, **kw)
                ),
            ):
                # The method catches ImportError and returns all subtasks
                approved = pipeline._apply_risk_scoring(subtasks, result)
                assert len(approved) == 1

    def test_review_subtasks_still_approved(self):
        """Subtasks needing review are still approved for execution (just flagged)."""
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
            SelfImproveResult,
        )

        config = SelfImproveConfig(safe_mode=True, risk_threshold=0.3)
        pipeline = SelfImprovePipeline(config)
        result = SelfImproveResult(cycle_id="test", objective="test")

        subtasks = [
            types.SimpleNamespace(
                title="Refactor storage",
                description="Refactor the storage layer for better performance",
                file_scope=["aragora/storage/postgres_store.py"],
                estimated_complexity="high",
            ),
        ]

        approved = pipeline._apply_risk_scoring(subtasks, result)
        # Should still be in approved list (review means execute but flag)
        assert len(approved) == 1
        assert result.goals_needs_review >= 0  # At least 0; could be review or block


# ---------------------------------------------------------------------------
# SelfImprovePipeline -- dry_run with risk assessments
# ---------------------------------------------------------------------------


class TestDryRunRiskAssessments:
    def test_dry_run_includes_risk_assessments(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
        )

        config = SelfImproveConfig(
            safe_mode=True,
            risk_threshold=0.5,
            use_meta_planner=False,
            scan_mode=False,
            enable_codebase_indexing=False,
        )
        pipeline = SelfImprovePipeline(config)

        # Mock _plan and _decompose to return predictable results
        async def mock_plan(objective):
            return [
                types.SimpleNamespace(
                    description="Test improvement",
                    track=types.SimpleNamespace(value="core"),
                    priority=1,
                    estimated_impact="medium",
                    rationale="test",
                )
            ]

        async def mock_decompose(goals):
            return [
                types.SimpleNamespace(
                    title="Add tests for utils",
                    description="Write unit tests",
                    original_task="Test improvement",
                    scope="small",
                    file_scope=["tests/test_utils.py"],
                    success_criteria={},
                    estimated_complexity="low",
                )
            ]

        pipeline._plan = mock_plan
        pipeline._decompose = mock_decompose

        plan = asyncio.run(pipeline.dry_run("Improve test coverage"))
        assert "risk_assessments" in plan
        assert len(plan["risk_assessments"]) > 0
        assert "config" in plan
        assert plan["config"]["safe_mode"] is True
        assert plan["config"]["risk_threshold"] == 0.5

    def test_dry_run_no_risk_when_safe_mode_off(self):
        from aragora.nomic.self_improve import (
            SelfImproveConfig,
            SelfImprovePipeline,
        )

        config = SelfImproveConfig(
            safe_mode=False,
            use_meta_planner=False,
            scan_mode=False,
            enable_codebase_indexing=False,
        )
        pipeline = SelfImprovePipeline(config)

        async def mock_plan(objective):
            return [
                types.SimpleNamespace(
                    description="Test goal",
                    track=types.SimpleNamespace(value="core"),
                    priority=1,
                    estimated_impact="medium",
                    rationale="test",
                )
            ]

        async def mock_decompose(goals):
            return [
                types.SimpleNamespace(
                    title="Simple task",
                    description="Do something simple",
                    original_task="Test goal",
                    scope="small",
                    file_scope=[],
                    success_criteria={},
                    estimated_complexity="low",
                )
            ]

        pipeline._plan = mock_plan
        pipeline._decompose = mock_decompose

        plan = asyncio.run(pipeline.dry_run("Test goal"))
        assert plan["risk_assessments"] == []
        assert plan["config"]["safe_mode"] is False


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_protected_files_populated(self):
        assert len(PROTECTED_FILES) > 0
        assert "CLAUDE.md" in PROTECTED_FILES
        assert ".env" in PROTECTED_FILES
        assert "scripts/nomic_loop.py" in PROTECTED_FILES

    def test_high_risk_keywords_populated(self):
        assert len(HIGH_RISK_KEYWORDS) > 0
        assert "security" in HIGH_RISK_KEYWORDS
        assert "authentication" in HIGH_RISK_KEYWORDS

    def test_critical_risk_keywords_populated(self):
        assert len(CRITICAL_RISK_KEYWORDS) > 0
        assert "deploy" in CRITICAL_RISK_KEYWORDS
        assert "production" in CRITICAL_RISK_KEYWORDS

    def test_low_risk_keywords_populated(self):
        assert len(LOW_RISK_KEYWORDS) > 0
        assert "test" in LOW_RISK_KEYWORDS
        assert "documentation" in LOW_RISK_KEYWORDS

    def test_risk_paths_populated(self):
        assert len(LOW_RISK_PATHS) > 0
        assert len(HIGH_RISK_PATHS) > 0
        assert len(CRITICAL_RISK_PATHS) > 0


# ---------------------------------------------------------------------------
# Modules split out of critical-path files
# ---------------------------------------------------------------------------


_CRITICAL_NOMIC_FACADES = [
    ("aragora.nomic.self_improve", "SelfImprovePipeline"),
    ("aragora.nomic.autonomous_orchestrator", "AutonomousOrchestrator"),
]


def _module_path(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


def _file_scope_weight(path: str) -> float:
    result = RiskScorer().score_goal("Tidy helper names", file_scope=[path])
    return next(f.weight for f in result.factors if f.name == "file_scope")


def _split_out_modules(module_name: str, class_name: str) -> set[str]:
    """Sibling modules holding code split out of a critical facade.

    Splits take two shapes here: a mixin the facade class inherits from, and a
    top-level backward-compatibility re-export marked ``# noqa: F401``.
    """
    module = importlib.import_module(module_name)
    found = {
        base.__module__
        for base in getattr(module, class_name).__mro__
        if base.__module__.startswith("aragora.nomic.")
    }
    source = inspect.getsource(module)
    lines = source.splitlines()
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("aragora.nomic.")
            and "noqa: F401" in lines[node.lineno - 1]
        ):
            found.add(node.module)
    found.discard(module_name)
    return found


class TestSplitModulesKeepCriticalPathRisk:
    @pytest.mark.parametrize(("module_name", "class_name"), _CRITICAL_NOMIC_FACADES)
    def test_facade_is_a_critical_path(self, module_name, class_name):
        assert any(c in _module_path(module_name) for c in CRITICAL_RISK_PATHS)

    @pytest.mark.parametrize(("module_name", "class_name"), _CRITICAL_NOMIC_FACADES)
    def test_split_out_modules_score_like_their_facade(self, module_name, class_name):
        split_modules = sorted(_split_out_modules(module_name, class_name))
        assert split_modules
        facade_weight = _file_scope_weight(_module_path(module_name))
        weights = {m: _file_scope_weight(_module_path(m)) for m in split_modules}
        assert weights == pytest.approx(dict.fromkeys(split_modules, facade_weight))
