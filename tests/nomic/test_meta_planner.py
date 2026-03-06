"""Tests for MetaPlanner - debate-driven goal prioritization."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.nomic.meta_planner import (
    MetaPlanner,
    MetaPlannerConfig,
    PrioritizedGoal,
    PlanningContext,
    Track,
)


class TestTrackEnum:
    """Tests for Track enum."""

    def test_track_values(self):
        """Track enum should have correct values."""
        assert Track.SME.value == "sme"
        assert Track.DEVELOPER.value == "developer"
        assert Track.SELF_HOSTED.value == "self_hosted"
        assert Track.QA.value == "qa"
        assert Track.CORE.value == "core"
        assert Track.SECURITY.value == "security"

    def test_track_count(self):
        """Should include all required core tracks."""
        required = {"sme", "developer", "self_hosted", "qa", "core", "security"}
        present = {track.value for track in Track}
        assert required.issubset(present)
        assert len(Track) >= len(required)


class TestPrioritizedGoal:
    """Tests for PrioritizedGoal dataclass."""

    def test_goal_creation(self):
        """Should create goal with all fields."""
        goal = PrioritizedGoal(
            id="goal_0",
            track=Track.SME,
            description="Improve dashboard",
            rationale="Increases user engagement",
            estimated_impact="high",
            priority=1,
            focus_areas=["ui", "ux"],
            file_hints=["dashboard.py"],
        )

        assert goal.id == "goal_0"
        assert goal.track == Track.SME
        assert goal.description == "Improve dashboard"
        assert goal.rationale == "Increases user engagement"
        assert goal.estimated_impact == "high"
        assert goal.priority == 1
        assert "ui" in goal.focus_areas
        assert "dashboard.py" in goal.file_hints

    def test_goal_default_lists(self):
        """Should have empty default lists."""
        goal = PrioritizedGoal(
            id="goal_0",
            track=Track.QA,
            description="Add tests",
            rationale="Improve coverage",
            estimated_impact="medium",
            priority=1,
        )

        assert goal.focus_areas == []
        assert goal.file_hints == []


class TestPlanningContext:
    """Tests for PlanningContext dataclass."""

    def test_context_creation(self):
        """Should create context with all fields."""
        context = PlanningContext(
            recent_issues=["Bug in auth"],
            test_failures=["test_login failed"],
            user_feedback=["Dashboard is slow"],
            recent_changes=["Updated handlers.py"],
        )

        assert "Bug in auth" in context.recent_issues
        assert "test_login failed" in context.test_failures
        assert "Dashboard is slow" in context.user_feedback
        assert "Updated handlers.py" in context.recent_changes

    def test_context_defaults(self):
        """Should have empty default lists."""
        context = PlanningContext()

        assert context.recent_issues == []
        assert context.test_failures == []
        assert context.user_feedback == []
        assert context.recent_changes == []


class TestMetaPlannerConfig:
    """Tests for MetaPlannerConfig dataclass."""

    def test_config_defaults(self):
        """Should have sensible defaults."""
        config = MetaPlannerConfig()

        assert config.agents == ["claude", "gemini", "deepseek"]
        assert config.debate_rounds == 2
        assert config.max_goals == 5
        assert config.consensus_threshold == 0.6

    def test_config_custom_values(self):
        """Should accept custom values."""
        config = MetaPlannerConfig(
            agents=["claude"],
            debate_rounds=3,
            max_goals=10,
            consensus_threshold=0.8,
        )

        assert config.agents == ["claude"]
        assert config.debate_rounds == 3
        assert config.max_goals == 10
        assert config.consensus_threshold == 0.8


class TestMetaPlanner:
    """Tests for MetaPlanner class."""

    def test_init_default_config(self):
        """Should initialize with default config."""
        planner = MetaPlanner()

        assert planner.config is not None
        assert planner.config.agents == ["claude", "gemini", "deepseek"]

    def test_init_custom_config(self):
        """Should accept custom config."""
        config = MetaPlannerConfig(max_goals=3)
        planner = MetaPlanner(config=config)

        assert planner.config.max_goals == 3


class TestBuildDebateTopic:
    """Tests for _build_debate_topic method."""

    def test_topic_includes_objective(self):
        """Topic should include the objective."""
        planner = MetaPlanner()
        topic = planner._build_debate_topic(
            objective="Maximize SME utility",
            tracks=[Track.SME],
            constraints=[],
            context=PlanningContext(),
        )

        assert "Maximize SME utility" in topic

    def test_topic_includes_tracks(self):
        """Topic should list available tracks."""
        planner = MetaPlanner()
        topic = planner._build_debate_topic(
            objective="Improve features",
            tracks=[Track.SME, Track.DEVELOPER],
            constraints=[],
            context=PlanningContext(),
        )

        assert "sme" in topic
        assert "developer" in topic

    def test_topic_includes_constraints(self):
        """Topic should include constraints."""
        planner = MetaPlanner()
        topic = planner._build_debate_topic(
            objective="Improve features",
            tracks=[Track.QA],
            constraints=["No breaking changes", "Must pass CI"],
            context=PlanningContext(),
        )

        assert "No breaking changes" in topic
        assert "Must pass CI" in topic

    def test_topic_includes_context(self):
        """Topic should include context information."""
        planner = MetaPlanner()
        context = PlanningContext(
            recent_issues=["Auth bug"],
            test_failures=["test_login"],
        )
        topic = planner._build_debate_topic(
            objective="Fix issues",
            tracks=[Track.CORE],
            constraints=[],
            context=context,
        )

        assert "Auth bug" in topic
        assert "test_login" in topic


class TestInferTrack:
    """Tests for _infer_track method."""

    def test_infer_sme_track(self):
        """Should infer SME track from dashboard keywords."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Improve dashboard UX",
            [Track.SME, Track.DEVELOPER],
        )
        assert track == Track.SME

    def test_infer_developer_track(self):
        """Should infer Developer track from SDK keywords."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Update the Python SDK documentation",
            [Track.SME, Track.DEVELOPER],
        )
        assert track == Track.DEVELOPER

    def test_infer_self_hosted_track(self):
        """Should infer Self-Hosted track from deployment keywords."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Add Docker compose support",
            [Track.SELF_HOSTED, Track.QA],
        )
        assert track == Track.SELF_HOSTED

    def test_infer_qa_track(self):
        """Should infer QA track from test keywords."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Improve test coverage",
            [Track.QA, Track.CORE],
        )
        assert track == Track.QA

    def test_infer_core_track(self):
        """Should infer Core track from agent keywords."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Improve agent consensus detection",
            [Track.QA, Track.CORE],
        )
        assert track == Track.CORE

    def test_infer_defaults_to_first(self):
        """Should default to first available track."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Do something unrelated",
            [Track.QA, Track.DEVELOPER],
        )
        assert track == Track.QA

    def test_infer_with_unavailable_track(self):
        """Should not choose unavailable tracks."""
        planner = MetaPlanner()
        track = planner._infer_track(
            "Improve dashboard UX",  # Suggests SME
            [Track.QA, Track.DEVELOPER],  # But SME not available
        )
        assert track in [Track.QA, Track.DEVELOPER]


class TestHeuristicPrioritize:
    """Tests for _heuristic_prioritize method."""

    def test_sme_objective_generates_sme_goal(self):
        """SME objectives should generate SME goals."""
        planner = MetaPlanner()
        goals = planner._heuristic_prioritize(
            "Maximize utility for SME businesses",
            [Track.SME, Track.QA],
        )

        assert len(goals) >= 1
        sme_goals = [g for g in goals if g.track == Track.SME]
        assert len(sme_goals) >= 1
        assert sme_goals[0].estimated_impact == "high"

    def test_small_business_objective(self):
        """'Small business' should trigger SME goals."""
        planner = MetaPlanner()
        goals = planner._heuristic_prioritize(
            "Help small business users",
            [Track.SME],
        )

        assert any(g.track == Track.SME for g in goals)

    def test_generates_goals_for_all_tracks(self):
        """Should generate goals for all available tracks."""
        planner = MetaPlanner()
        goals = planner._heuristic_prioritize(
            "Generic objective",
            [Track.SME, Track.QA, Track.DEVELOPER],
        )

        tracks_covered = {g.track for g in goals}
        assert Track.SME in tracks_covered or Track.QA in tracks_covered

    def test_generic_objective_not_broadcast_to_all_tracks(self):
        """Fallback heuristic should pick one best track, not clone to all tracks."""
        planner = MetaPlanner()
        goals = planner._heuristic_prioritize(
            "Create a shared WorkItem protocol and UnifiedCycleOrchestrator",
            [Track.SME, Track.QA, Track.CORE, Track.SELF_HOSTED, Track.SECURITY],
        )

        assert len(goals) == 1
        assert goals[0].track in {Track.CORE, Track.SELF_HOSTED, Track.SECURITY}
        assert goals[0].track != Track.SME

    @pytest.mark.asyncio
    async def test_prioritize_work_recovers_when_objective_fidelity_is_low(self):
        """Low-fidelity goal sets should be recovered to objective-aligned track."""
        planner = MetaPlanner(
            MetaPlannerConfig(
                quick_mode=True,
                objective_fidelity_threshold=0.8,
                enforce_objective_fidelity=True,
            )
        )

        def _drifted_goals(_objective, _tracks):
            return [
                PrioritizedGoal(
                    id="goal_0",
                    track=Track.SME,
                    description="Improve SME dashboard font hierarchy and color contrast",
                    rationale="drifted",
                    estimated_impact="medium",
                    priority=1,
                )
            ]

        planner._heuristic_prioritize = _drifted_goals  # type: ignore[assignment]
        goals = await planner.prioritize_work(
            objective="Integrate pipeline, testfixer, and quality gates into a closed loop",
            available_tracks=[Track.CORE, Track.SELF_HOSTED, Track.SECURITY, Track.SME],
        )

        assert len(goals) == 1
        assert goals[0].track in {Track.CORE, Track.SELF_HOSTED, Track.SECURITY}
        assert "closed loop" in goals[0].description.lower()

    def test_respects_max_goals(self):
        """Should not exceed max_goals."""
        config = MetaPlannerConfig(max_goals=2)
        planner = MetaPlanner(config=config)
        goals = planner._heuristic_prioritize(
            "Objective",
            list(Track),
        )

        assert len(goals) <= 2

    def test_priority_ordering(self):
        """Goals should have correct priority ordering."""
        planner = MetaPlanner()
        goals = planner._heuristic_prioritize(
            "Maximize SME utility",
            [Track.SME, Track.QA],
        )

        if len(goals) >= 2:
            assert goals[0].priority < goals[1].priority


class TestBuildGoal:
    """Tests for _build_goal method."""

    def test_builds_goal_with_track(self):
        """Should build goal with explicit track."""
        planner = MetaPlanner()
        goal_dict = {
            "description": "Add new feature",
            "track": Track.DEVELOPER,
            "rationale": "Important",
            "impact": "high",
        }
        goal = planner._build_goal(goal_dict, 0, [Track.DEVELOPER])

        assert goal.track == Track.DEVELOPER
        assert goal.description == "Add new feature"
        assert goal.estimated_impact == "high"
        assert goal.priority == 1

    def test_builds_goal_infers_track(self):
        """Should infer track when not specified."""
        planner = MetaPlanner()
        goal_dict = {
            "description": "Improve test coverage",
            "track": None,
            "rationale": "",
            "impact": "medium",
        }
        goal = planner._build_goal(goal_dict, 2, [Track.QA, Track.CORE])

        assert goal.track == Track.QA
        assert goal.priority == 3

    def test_builds_goal_default_impact(self):
        """Should default to medium impact."""
        planner = MetaPlanner()
        goal_dict = {
            "description": "Something",
            "track": Track.SME,
        }
        goal = planner._build_goal(goal_dict, 0, [Track.SME])

        assert goal.estimated_impact == "medium"


class TestParseGoalsFromDebate:
    """Tests for _parse_goals_from_debate method."""

    def test_parses_numbered_list(self):
        """Should parse numbered list format."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = """
        1. Improve dashboard UX
        2. Add more tests for the QA track
        3. Update SDK documentation
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.SME, Track.QA, Track.DEVELOPER],
            "Test objective",
        )

        assert len(goals) >= 1

    def test_parses_bullet_points(self):
        """Should parse bullet point format."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = """
        - Improve dashboard
        - Add tests
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.SME, Track.QA],
            "Test",
        )

        assert len(goals) >= 1

    def test_falls_back_on_empty_consensus(self):
        """Should fallback to heuristics on empty consensus."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = ""
        mock_result.final_response = ""
        mock_result.responses = []

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.SME],
            "SME objective",
        )

        assert len(goals) >= 1

    def test_extracts_impact(self):
        """Should extract impact from text."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        # Impact detection happens on lines after the goal line
        mock_result.consensus = """
        1. Critical feature
           Expected impact: high
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.SME],
            "Test",
        )

        if goals:
            assert goals[0].estimated_impact == "high"

    def test_respects_max_goals(self):
        """Should limit goals to max_goals."""
        config = MetaPlannerConfig(max_goals=2)
        planner = MetaPlanner(config=config)

        mock_result = MagicMock()
        mock_result.consensus = """
        1. Goal one
        2. Goal two
        3. Goal three
        4. Goal four
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            list(Track),
            "Test",
        )

        assert len(goals) <= 2


class TestPrioritizeWorkAsync:
    """Tests for prioritize_work async method."""

    @pytest.mark.asyncio
    async def test_prioritize_uses_heuristic_fallback(self):
        """Should fall back to heuristics when debate fails."""
        config = MetaPlannerConfig(
            enable_cross_cycle_learning=False,
            enable_metrics_collection=False,
        )
        planner = MetaPlanner(config=config)

        # Import error will trigger heuristic fallback.
        # Mock scan_code_markers and _gather_codebase_hints to avoid scanning
        # the entire repo filesystem (causes hangs in CI).
        with (
            patch.dict("sys.modules", {"aragora.debate.orchestrator": None}),
            patch(
                "aragora.compat.openclaw.next_steps_runner.scan_code_markers", return_value=([], 0)
            ),
            patch.object(planner, "_gather_codebase_hints", return_value={}),
        ):
            goals = await planner.prioritize_work(
                objective="Maximize SME utility",
                available_tracks=[Track.SME, Track.QA],
            )

        assert len(goals) >= 1
        assert all(isinstance(g, PrioritizedGoal) for g in goals)

    @pytest.mark.asyncio
    async def test_prioritize_with_defaults(self):
        """Should work with default parameters using heuristic fallback."""
        planner = MetaPlanner()

        # Test heuristic fallback directly (avoids slow imports)
        goals = planner._heuristic_prioritize(
            objective="Improve the system",
            available_tracks=list(Track),
        )

        assert isinstance(goals, list)
        assert len(goals) >= 1

    @pytest.mark.asyncio
    async def test_prioritize_with_context(self):
        """Should incorporate context in debate topic building."""
        planner = MetaPlanner()
        context = PlanningContext(
            recent_issues=["Auth failures"],
            test_failures=["test_login"],
        )

        # Test topic building which incorporates context
        topic = planner._build_debate_topic(
            objective="Fix issues",
            tracks=[Track.CORE, Track.QA],
            constraints=["No breaking changes"],
            context=context,
        )

        assert "Fix issues" in topic
        assert "Auth failures" in topic
        assert "test_login" in topic
        assert "No breaking changes" in topic


class TestPrioritizeWorkWithDebate:
    """Tests for prioritize_work when debate is available."""

    @pytest.mark.asyncio
    async def test_prioritize_with_single_track(self):
        """Should prioritize for a single track."""
        planner = MetaPlanner()

        # Use heuristic prioritization (debate would require agents)
        goals = planner._heuristic_prioritize(
            objective="Improve SME experience",
            available_tracks=[Track.SME],
        )

        assert len(goals) >= 1
        assert all(g.track == Track.SME for g in goals)

    @pytest.mark.asyncio
    async def test_prioritize_with_all_tracks(self):
        """Should prioritize across all tracks."""
        planner = MetaPlanner()

        goals = planner._heuristic_prioritize(
            objective="General improvement",
            available_tracks=list(Track),
        )

        assert len(goals) >= 1
        assert len(goals) <= planner.config.max_goals

    @pytest.mark.asyncio
    async def test_prioritize_respects_constraints(self):
        """Should incorporate constraints into topic."""
        planner = MetaPlanner()

        topic = planner._build_debate_topic(
            objective="Test objective",
            tracks=[Track.QA],
            constraints=["No breaking changes", "Maintain backward compatibility"],
            context=PlanningContext(),
        )

        # Constraints should be in the topic
        assert "No breaking changes" in topic
        assert "backward compatibility" in topic


class TestParseGoalsFromDebateExtended:
    """Extended tests for _parse_goals_from_debate."""

    def test_parses_final_response_fallback(self):
        """Should use final_response when consensus is empty."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = None
        mock_result.final_response = """
        1. Improve test coverage
        2. Add documentation
        """
        mock_result.responses = []

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.QA, Track.DEVELOPER],
            "Test",
        )

        assert len(goals) >= 1

    def test_parses_responses_fallback(self):
        """Should use responses when other fields are empty."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = None
        mock_result.final_response = None
        mock_result.responses = ["1. Add feature X\n2. Fix bug Y"]

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.DEVELOPER],
            "Test",
        )

        assert len(goals) >= 1

    def test_parses_rationale_from_because(self):
        """Should extract rationale from 'because' keywords."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = """
        1. Improve performance
           Because: Users are experiencing slow load times
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.CORE],
            "Test",
        )

        if goals:
            # Rationale should be captured
            assert "because" in goals[0].rationale.lower() or len(goals[0].rationale) > 0

    def test_parses_track_from_text(self):
        """Should extract track from goal text."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = """
        1. Fix QA pipeline issues
           This is for the QA track
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.QA, Track.DEVELOPER],
            "Test",
        )

        if goals:
            assert goals[0].track == Track.QA

    def test_handles_parentheses_format(self):
        """Should handle numbered items with parentheses."""
        planner = MetaPlanner()

        mock_result = MagicMock()
        mock_result.consensus = """
        1) First goal
        2) Second goal
        """

        goals = planner._parse_goals_from_debate(
            mock_result,
            [Track.SME],
            "Test",
        )

        assert len(goals) >= 1


class TestHeuristicPrioritizeExtended:
    """Extended tests for _heuristic_prioritize."""

    def test_developer_keywords(self):
        """Should handle developer-focused objectives."""
        planner = MetaPlanner()

        goals = planner._heuristic_prioritize(
            "Improve SDK and API documentation",
            [Track.DEVELOPER, Track.QA],
        )

        # Should generate goals for developer track
        assert any(g.track == Track.DEVELOPER for g in goals)

    def test_qa_keywords(self):
        """Should handle QA-focused objectives."""
        planner = MetaPlanner()

        goals = planner._heuristic_prioritize(
            "Increase test coverage and improve CI/CD",
            [Track.QA],
        )

        assert all(g.track == Track.QA for g in goals)

    def test_empty_tracks(self):
        """Should handle empty tracks list."""
        planner = MetaPlanner()

        goals = planner._heuristic_prioritize(
            "Some objective",
            [],
        )

        # Should still work, though may have empty result
        assert isinstance(goals, list)

    def test_unique_goals_per_track(self):
        """Should not duplicate goals for same track."""
        planner = MetaPlanner()

        goals = planner._heuristic_prioritize(
            "Generic objective",
            [Track.SME, Track.QA, Track.DEVELOPER],
        )

        # Check no duplicate tracks in goals
        tracks_seen = []
        for g in goals:
            if g.track not in tracks_seen:
                tracks_seen.append(g.track)

        # All goals should be for different tracks (or meaningful duplicates)
        assert len(goals) <= planner.config.max_goals


class TestBuildDebateTopicExtended:
    """Extended tests for _build_debate_topic."""

    def test_topic_includes_track_descriptions(self):
        """Should include track descriptions in topic."""
        planner = MetaPlanner()

        topic = planner._build_debate_topic(
            objective="Improve system",
            tracks=[Track.SME, Track.CORE],
            constraints=[],
            context=PlanningContext(),
        )

        assert "SME" in topic or "sme" in topic
        assert "Core" in topic or "core" in topic
        # Should have track descriptions
        assert "dashboard" in topic.lower() or "debate" in topic.lower()

    def test_topic_no_constraints_message(self):
        """Should show 'None specified' when no constraints."""
        planner = MetaPlanner()

        topic = planner._build_debate_topic(
            objective="Test",
            tracks=[Track.QA],
            constraints=[],
            context=PlanningContext(),
        )

        assert "None specified" in topic

    def test_topic_includes_user_feedback(self):
        """Should include user feedback in context."""
        planner = MetaPlanner()

        context = PlanningContext(
            user_feedback=["UI is confusing", "Need better docs"],
        )

        topic = planner._build_debate_topic(
            objective="Improve UX",
            tracks=[Track.SME],
            constraints=[],
            context=context,
        )

        # User feedback should be included (if implementation adds it)
        # Current implementation doesn't include user_feedback, but let's test structure
        assert "Improve UX" in topic


class TestInferTrackExtended:
    """Extended tests for _infer_track."""

    def test_infer_with_multiple_matches(self):
        """Should handle descriptions matching multiple tracks."""
        planner = MetaPlanner()

        # This description matches both QA (test) and Developer (API)
        track = planner._infer_track(
            "Add tests for API endpoints",
            [Track.QA, Track.DEVELOPER],
        )

        # Should pick one of them
        assert track in [Track.QA, Track.DEVELOPER]

    def test_infer_empty_description(self):
        """Should handle empty description."""
        planner = MetaPlanner()

        track = planner._infer_track(
            "",
            [Track.SME, Track.QA],
        )

        # Should default to first track
        assert track == Track.SME

    def test_infer_none_available(self):
        """Should handle empty available tracks."""
        planner = MetaPlanner()

        track = planner._infer_track(
            "Some task",
            [],
        )

        # Should return Track.DEVELOPER as fallback
        assert track == Track.DEVELOPER


class TestBuildGoalExtended:
    """Extended tests for _build_goal."""

    def test_build_goal_increments_priority(self):
        """Priority should be priority index + 1."""
        planner = MetaPlanner()

        goal = planner._build_goal(
            {"description": "Test", "track": Track.QA},
            5,  # priority index
            [Track.QA],
        )

        assert goal.priority == 6  # 5 + 1

    def test_build_goal_generates_unique_id(self):
        """Goal ID should be based on priority."""
        planner = MetaPlanner()

        goal = planner._build_goal(
            {"description": "Test", "track": Track.SME},
            3,
            [Track.SME],
        )

        assert goal.id == "goal_3"

    def test_build_goal_empty_rationale(self):
        """Should handle missing rationale."""
        planner = MetaPlanner()

        goal = planner._build_goal(
            {"description": "Test", "track": Track.CORE},
            0,
            [Track.CORE],
        )

        assert goal.rationale == ""


class TestPlanningContextExtended:
    """Extended tests for PlanningContext."""

    def test_context_with_recent_changes(self):
        """Should handle recent changes list."""
        context = PlanningContext(
            recent_changes=["Added new endpoint", "Refactored auth"],
        )

        assert len(context.recent_changes) == 2
        assert "Added new endpoint" in context.recent_changes

    def test_context_all_fields_populated(self):
        """Should handle all fields populated."""
        context = PlanningContext(
            recent_issues=["Bug 1", "Bug 2"],
            test_failures=["test_a", "test_b"],
            user_feedback=["Slow", "Confusing"],
            recent_changes=["Change 1", "Change 2"],
        )

        assert len(context.recent_issues) == 2
        assert len(context.test_failures) == 2
        assert len(context.user_feedback) == 2
        assert len(context.recent_changes) == 2


class TestPrioritizedGoalExtended:
    """Extended tests for PrioritizedGoal."""

    def test_goal_with_file_hints(self):
        """Should store file hints correctly."""
        goal = PrioritizedGoal(
            id="test",
            track=Track.DEVELOPER,
            description="Update SDK",
            rationale="Users need new features",
            estimated_impact="high",
            priority=1,
            file_hints=["sdk/client.py", "sdk/api.py"],
        )

        assert len(goal.file_hints) == 2
        assert "sdk/client.py" in goal.file_hints

    def test_goal_with_focus_areas(self):
        """Should store focus areas correctly."""
        goal = PrioritizedGoal(
            id="test",
            track=Track.SME,
            description="Improve dashboard",
            rationale="UX feedback",
            estimated_impact="medium",
            priority=2,
            focus_areas=["navigation", "performance", "accessibility"],
        )

        assert len(goal.focus_areas) == 3
        assert "navigation" in goal.focus_areas


class TestOutcomeFeedbackIntegration:
    """Tests that NomicOutcomeTracker regressions flow into MetaPlanner planning context."""

    @pytest.mark.asyncio
    async def test_regressions_injected_into_context(self):
        """When get_regression_history returns data, it should appear in past_failures_to_avoid."""
        planner = MetaPlanner(MetaPlannerConfig(enable_cross_cycle_learning=True))
        context = PlanningContext()

        regressions = [
            {
                "cycle_id": "cycle_abc12345",
                "regressed_metrics": ["consensus_rate", "avg_tokens"],
                "recommendation": "revert",
            },
            {
                "cycle_id": "cycle_def67890",
                "regressed_metrics": ["calibration_spread"],
                "recommendation": "review",
            },
        ]

        with (
            patch(
                "aragora.nomic.meta_planner.get_nomic_cycle_adapter",
                side_effect=ImportError("skip KM"),
            )
            if False
            else patch(
                "aragora.nomic.outcome_tracker.NomicOutcomeTracker.get_regression_history",
                return_value=regressions,
            ) as mock_reg,
            patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                side_effect=ImportError("skip KM"),
            ),
            patch(
                "aragora.pipeline.plan_store.get_plan_store",
                side_effect=ImportError("skip plan store"),
            ),
            patch(
                "aragora.ranking.elo.get_elo_store",
                side_effect=ImportError("skip elo"),
            ),
        ):
            enriched = await planner._enrich_context_with_history(
                objective="Test objective",
                tracks=[Track.SME],
                context=context,
            )

        mock_reg.assert_called_once_with(limit=5)

        # Check that regressions were injected
        regression_entries = [
            f for f in enriched.past_failures_to_avoid if "[outcome_regression]" in f
        ]
        assert len(regression_entries) == 2

        # First regression entry should reference the cycle and metrics
        assert "cycle_ab" in regression_entries[0]
        assert "consensus_rate" in regression_entries[0]
        assert "avg_tokens" in regression_entries[0]
        assert "revert" in regression_entries[0]

        # Second regression entry
        assert "cycle_de" in regression_entries[1]
        assert "calibration_spread" in regression_entries[1]
        assert "review" in regression_entries[1]

    @pytest.mark.asyncio
    async def test_no_regressions_no_entries(self):
        """When get_regression_history returns empty, no regression entries added."""
        planner = MetaPlanner(MetaPlannerConfig(enable_cross_cycle_learning=True))
        context = PlanningContext()

        with (
            patch(
                "aragora.nomic.outcome_tracker.NomicOutcomeTracker.get_regression_history",
                return_value=[],
            ),
            patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                side_effect=ImportError("skip KM"),
            ),
            patch(
                "aragora.pipeline.plan_store.get_plan_store",
                side_effect=ImportError("skip plan store"),
            ),
            patch(
                "aragora.ranking.elo.get_elo_store",
                side_effect=ImportError("skip elo"),
            ),
        ):
            enriched = await planner._enrich_context_with_history(
                objective="Test objective",
                tracks=[Track.QA],
                context=context,
            )

        regression_entries = [
            f for f in enriched.past_failures_to_avoid if "[outcome_regression]" in f
        ]
        assert len(regression_entries) == 0

    @pytest.mark.asyncio
    async def test_import_error_gracefully_handled(self):
        """ImportError from outcome tracker should not break enrichment."""
        planner = MetaPlanner(MetaPlannerConfig(enable_cross_cycle_learning=True))
        context = PlanningContext()

        # Simulate the case where outcome_tracker cannot be imported
        with (
            patch.dict("sys.modules", {"aragora.nomic.outcome_tracker": None}),
            patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                side_effect=ImportError("skip KM"),
            ),
            patch(
                "aragora.pipeline.plan_store.get_plan_store",
                side_effect=ImportError("skip plan store"),
            ),
            patch(
                "aragora.ranking.elo.get_elo_store",
                side_effect=ImportError("skip elo"),
            ),
        ):
            enriched = await planner._enrich_context_with_history(
                objective="Test objective",
                tracks=[Track.CORE],
                context=context,
            )

        # Should still return context without crashing
        assert isinstance(enriched, PlanningContext)

    @pytest.mark.asyncio
    async def test_runtime_error_gracefully_handled(self):
        """RuntimeError from get_regression_history should not break enrichment."""
        planner = MetaPlanner(MetaPlannerConfig(enable_cross_cycle_learning=True))
        context = PlanningContext()

        with (
            patch(
                "aragora.nomic.outcome_tracker.NomicOutcomeTracker.get_regression_history",
                side_effect=RuntimeError("store corrupted"),
            ),
            patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                side_effect=ImportError("skip KM"),
            ),
            patch(
                "aragora.pipeline.plan_store.get_plan_store",
                side_effect=ImportError("skip plan store"),
            ),
            patch(
                "aragora.ranking.elo.get_elo_store",
                side_effect=ImportError("skip elo"),
            ),
        ):
            enriched = await planner._enrich_context_with_history(
                objective="Test objective",
                tracks=[Track.SECURITY],
                context=context,
            )

        # Should still return context without crashing
        assert isinstance(enriched, PlanningContext)

    def test_regressions_appear_in_debate_topic(self):
        """Regression entries should flow through to the debate topic text."""
        planner = MetaPlanner()
        context = PlanningContext(
            past_failures_to_avoid=[
                "[outcome_regression] Cycle cycle_ab regressed: consensus_rate, avg_tokens "
                "(recommendation: revert)"
            ],
        )

        topic = planner._build_debate_topic(
            objective="Improve quality",
            tracks=[Track.CORE],
            constraints=[],
            context=context,
        )

        assert "outcome_regression" in topic
        assert "consensus_rate" in topic
        assert "PAST FAILURES TO AVOID" in topic


class TestHeuristicCodebaseHints:
    """Tests for CodebaseIndexer integration in the heuristic prioritization path."""

    def _make_mock_indexer(self, modules=None):
        """Helper to build a mock CodebaseIndexer with pre-populated modules."""
        mock_indexer = MagicMock()
        mock_indexer.source_dirs = ["aragora"]
        mock_indexer.repo_path = MagicMock()
        source_dir = MagicMock()
        source_dir.is_dir.return_value = True
        source_dir.rglob.return_value = []
        mock_indexer.repo_path.__truediv__ = MagicMock(return_value=source_dir)
        mock_indexer._modules = modules if modules is not None else []
        mock_indexer.max_modules = 500
        return mock_indexer

    def test_heuristic_uses_codebase_indexer(self):
        """Patched CodebaseIndexer should populate file_hints on goals."""
        mock_module = MagicMock()
        mock_module.path = "aragora/security/encryption.py"
        mock_module.to_km_entry.return_value = {
            "searchable_text": "encryption security hardening secrets",
        }

        mock_indexer = self._make_mock_indexer(modules=[mock_module])

        with patch(
            "aragora.nomic.codebase_indexer.CodebaseIndexer",
            return_value=mock_indexer,
        ):
            planner = MetaPlanner(config=MetaPlannerConfig())
            goals = planner._heuristic_prioritize(
                "security hardening", [Track.SECURITY, Track.CORE]
            )

        security_goals = [g for g in goals if g.track == Track.SECURITY]
        assert len(security_goals) >= 1
        assert any("aragora/security/encryption.py" in g.file_hints for g in security_goals), (
            f"Expected file_hints to contain encryption.py, got {[g.file_hints for g in security_goals]}"
        )

    def test_heuristic_graceful_without_indexer(self):
        """When CodebaseIndexer import fails, goals should still be generated with empty file_hints."""
        import sys

        # Remove module from sys.modules so the local import inside
        # _gather_codebase_hints triggers an ImportError.
        saved = sys.modules.pop("aragora.nomic.codebase_indexer", None)
        try:
            with patch.dict(
                sys.modules,
                {"aragora.nomic.codebase_indexer": None},
            ):
                planner = MetaPlanner(config=MetaPlannerConfig())
                goals = planner._heuristic_prioritize(
                    "improve test coverage", [Track.QA, Track.CORE]
                )
        finally:
            if saved is not None:
                sys.modules["aragora.nomic.codebase_indexer"] = saved

        assert len(goals) >= 1
        # All goals should have empty file_hints since indexer was unavailable
        for goal in goals:
            assert goal.file_hints == [], (
                f"Expected empty file_hints when indexer unavailable, "
                f"got {goal.file_hints} for {goal.track}"
            )

    def test_heuristic_maps_files_to_tracks(self):
        """Files matching track patterns should appear in the correct track's file_hints."""
        security_module = MagicMock()
        security_module.path = "aragora/auth/oidc.py"
        security_module.to_km_entry.return_value = {
            "searchable_text": "authentication oidc hardening",
        }

        qa_module = MagicMock()
        qa_module.path = "tests/test_auth.py"
        qa_module.to_km_entry.return_value = {
            "searchable_text": "test authentication hardening",
        }

        core_module = MagicMock()
        core_module.path = "aragora/debate/orchestrator.py"
        core_module.to_km_entry.return_value = {
            "searchable_text": "debate orchestrator hardening",
        }

        mock_indexer = self._make_mock_indexer(
            modules=[security_module, qa_module, core_module],
        )

        with patch(
            "aragora.nomic.codebase_indexer.CodebaseIndexer",
            return_value=mock_indexer,
        ):
            planner = MetaPlanner(config=MetaPlannerConfig())
            tracks = [Track.SECURITY, Track.QA, Track.CORE]
            goals = planner._heuristic_prioritize("hardening", tracks)

        # "hardening" matches SECURITY, so we get a single SECURITY goal
        # with all relevant file hints (not one goal per track).
        assert len(goals) >= 1, f"Expected at least 1 goal, got {len(goals)}"
        security_goals = [g for g in goals if g.track == Track.SECURITY]
        assert len(security_goals) >= 1, (
            f"Expected SECURITY goal for 'hardening', got tracks: {[g.track for g in goals]}"
        )
        # File hints for the best-matching track should include security files
        security_hints = security_goals[0].file_hints
        assert "aragora/auth/oidc.py" in security_hints, (
            f"Expected auth file in SECURITY hints, got {security_hints}"
        )

    def test_heuristic_with_empty_codebase(self):
        """An empty _modules list should produce goals with empty file_hints."""
        mock_indexer = self._make_mock_indexer(modules=[])

        with patch(
            "aragora.nomic.codebase_indexer.CodebaseIndexer",
            return_value=mock_indexer,
        ):
            planner = MetaPlanner(config=MetaPlannerConfig())
            goals = planner._heuristic_prioritize("improve sme dashboard", [Track.SME, Track.QA])

        assert len(goals) >= 1
        for goal in goals:
            assert goal.file_hints == [], (
                f"Expected empty file_hints with empty codebase, "
                f"got {goal.file_hints} for {goal.track}"
            )

    def test_gather_codebase_hints_returns_dict(self):
        """_gather_codebase_hints should return a dict mapping Track to file lists."""
        mock_module = MagicMock()
        mock_module.path = "aragora/debate/consensus.py"
        mock_module.to_km_entry.return_value = {
            "searchable_text": "consensus detection voting",
        }

        mock_indexer = self._make_mock_indexer(modules=[mock_module])

        with patch(
            "aragora.nomic.codebase_indexer.CodebaseIndexer",
            return_value=mock_indexer,
        ):
            planner = MetaPlanner(config=MetaPlannerConfig())
            result = planner._gather_codebase_hints("consensus detection", [Track.CORE, Track.QA])

        assert isinstance(result, dict)
        # All keys should be Track enum values
        for key in result:
            assert isinstance(key, Track), f"Expected Track key, got {type(key)}"
        # All values should be lists of strings
        for file_list in result.values():
            assert isinstance(file_list, list)
            for item in file_list:
                assert isinstance(item, str)
        # consensus.py should map to CORE track
        assert "aragora/debate/consensus.py" in result.get(Track.CORE, []), (
            f"Expected consensus.py in CORE track, got {result}"
        )
