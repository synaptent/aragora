"""Comprehensive tests for the prompt_engine module.

Tests all stages: types, decomposer, interrogator, researcher,
spec_builder, and conductor orchestration. All LLM calls are mocked.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from aragora.prompt_engine.types import (
    Ambiguity,
    Assumption,
    AutonomyLevel,
    ClarifyingQuestion,
    IntentType,
    InterrogationDepth,
    PromptIntent,
    ResearchReport,
    ScopeEstimate,
    UserProfile,
    PROFILE_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intent(
    prompt: str = "Improve the onboarding",
    intent_type: IntentType = IntentType.IMPROVEMENT,
    ambiguities: list[Ambiguity] | None = None,
    assumptions: list[Assumption] | None = None,
) -> PromptIntent:
    if ambiguities is None:
        ambiguities = [
            Ambiguity(
                description="Which onboarding?",
                impact="Different flows",
                options=["web", "mobile"],
            )
        ]
    if assumptions is None:
        assumptions = [Assumption(description="Existing flow works", confidence=0.7)]
    return PromptIntent(
        raw_prompt=prompt,
        intent_type=intent_type,
        summary=prompt,
        domains=["frontend", "auth"],
        ambiguities=ambiguities,
        assumptions=assumptions,
    )


# ===========================================================================
# Types tests
# ===========================================================================


class TestIntentType:
    def test_values(self) -> None:
        assert IntentType.FEATURE.value == "feature"
        assert IntentType.FIX.value == "fix"
        assert IntentType.STRATEGIC.value == "strategic"

    def test_str_enum(self) -> None:
        assert isinstance(IntentType.FEATURE, str)


class TestScopeEstimate:
    def test_values(self) -> None:
        assert ScopeEstimate.SMALL.value == "small"
        assert ScopeEstimate.EPIC.value == "epic"


class TestPromptIntent:
    def test_needs_clarification_with_ambiguities(self) -> None:
        intent = _make_intent()
        assert intent.needs_clarification is True

    def test_no_clarification_without_ambiguities(self) -> None:
        intent = _make_intent(ambiguities=[])
        assert intent.needs_clarification is False

    def test_high_impact_ambiguities(self) -> None:
        a1 = Ambiguity(description="unclear", impact="big", recommended=None)
        a2 = Ambiguity(description="minor", impact="small", recommended="go with A")
        intent = _make_intent(ambiguities=[a1, a2])
        high = intent.high_impact_ambiguities
        assert len(high) == 1
        assert high[0].description == "unclear"


class TestClarifyingQuestion:
    def test_is_answered_false(self) -> None:
        q = ClarifyingQuestion(question="What?", why_it_matters="Scope")
        assert q.is_answered is False

    def test_is_answered_true(self) -> None:
        q = ClarifyingQuestion(question="What?", why_it_matters="Scope", answer="Option A")
        assert q.is_answered is True


class TestSpecification:
    def test_high_confidence_threshold(self) -> None:
        from aragora.prompt_engine.types import Specification

        spec = Specification(
            title="t", problem_statement="p", proposed_solution="s", confidence=0.85
        )
        assert spec.is_high_confidence is True

    def test_low_confidence(self) -> None:
        from aragora.prompt_engine.types import Specification

        spec = Specification(
            title="t", problem_statement="p", proposed_solution="s", confidence=0.5
        )
        assert spec.is_high_confidence is False


class TestProfileDefaults:
    def test_founder_profile(self) -> None:
        d = PROFILE_DEFAULTS["founder"]
        assert d["require_approval"] is False

    def test_all_profiles_exist(self) -> None:
        for profile in UserProfile:
            assert profile.value in PROFILE_DEFAULTS


# ===========================================================================
# Decomposer tests
# ===========================================================================


class TestPromptDecomposer:
    @pytest.fixture()
    def mock_agent(self) -> AsyncMock:
        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "intent_type": "feature",
                    "summary": "Add dark mode to settings page",
                    "domains": ["frontend", "settings"],
                    "ambiguities": [
                        {
                            "description": "Which pages?",
                            "impact": "Scope varies",
                            "options": ["all", "settings only"],
                            "recommended": "settings only",
                        }
                    ],
                    "assumptions": [
                        {
                            "description": "CSS vars exist",
                            "confidence": 0.9,
                            "alternative": "Need to add them",
                        }
                    ],
                    "scope_estimate": "medium",
                }
            )
        )
        return agent

    @pytest.mark.asyncio()
    async def test_decompose_basic(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        decomposer = PromptDecomposer(agent=mock_agent)
        intent = await decomposer.decompose("Add dark mode")
        assert intent.intent_type == IntentType.FEATURE
        assert "dark mode" in intent.summary.lower()
        assert len(intent.domains) == 2

    @pytest.mark.asyncio()
    async def test_decompose_with_context(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        decomposer = PromptDecomposer(agent=mock_agent)
        await decomposer.decompose("Add dark mode", context={"priority": "high"})
        call_args = mock_agent.generate.call_args[0][0]
        assert "priority" in call_args

    @pytest.mark.asyncio()
    async def test_decompose_with_km(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        km = AsyncMock()
        km.query = AsyncMock(return_value=[{"title": "Dark mode decision", "content": "CSS vars"}])
        decomposer = PromptDecomposer(agent=mock_agent, knowledge_mound=km)
        intent = await decomposer.decompose("Add dark mode")
        assert intent.related_knowledge
        km.query.assert_called_once()

        operation_names = [timing.operation for timing in decomposer.last_operation_timings]
        assert operation_names == [
            "decompose.get_agent",
            "decompose.km_query",
            "decompose.agent_generate",
            "decompose.parse_response",
        ]

    @pytest.mark.asyncio()
    async def test_decompose_fallback_on_bad_json(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="This is not JSON at all")
        decomposer = PromptDecomposer(agent=agent)
        intent = await decomposer.decompose("Do something")
        assert intent.intent_type == IntentType.IMPROVEMENT
        assert intent.domains == ["unknown"]

    @pytest.mark.asyncio()
    async def test_decompose_markdown_wrapped_json(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        data = {
            "intent_type": "fix",
            "summary": "Fix the login bug",
            "domains": ["auth"],
            "ambiguities": [],
            "assumptions": [],
            "scope_estimate": "small",
        }
        agent = AsyncMock()
        agent.generate = AsyncMock(return_value=f"```json\n{json.dumps(data)}\n```")
        decomposer = PromptDecomposer(agent=agent)
        intent = await decomposer.decompose("Fix login")
        assert intent.intent_type == IntentType.FIX

    @pytest.mark.asyncio()
    async def test_decompose_llm_preface_and_code_block(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        data = {
            "intent_type": "feature",
            "summary": "Add exports",
            "domains": ["reporting"],
            "ambiguities": [],
            "assumptions": [],
            "scope_estimate": "small",
        }
        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=f"Here is the analysis:\n```json\n{json.dumps(data)}\n```\nProceed."
        )
        decomposer = PromptDecomposer(agent=agent)
        intent = await decomposer.decompose("Add exports")
        assert intent.intent_type == IntentType.FEATURE
        assert intent.summary == "Add exports"

    @pytest.mark.asyncio()
    async def test_decompose_invalid_intent_type_fallback(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        data = {
            "intent_type": "not_a_real_type",
            "summary": "Something",
            "domains": ["general"],
            "ambiguities": [],
            "assumptions": [],
            "scope_estimate": "small",
        }
        agent = AsyncMock()
        agent.generate = AsyncMock(return_value=json.dumps(data))
        decomposer = PromptDecomposer(agent=agent)
        intent = await decomposer.decompose("Something")
        assert intent.intent_type == IntentType.IMPROVEMENT

    def test_prompt_hash_deterministic(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        h1 = PromptDecomposer.prompt_hash("hello")
        h2 = PromptDecomposer.prompt_hash("hello")
        h3 = PromptDecomposer.prompt_hash("world")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 16

    @pytest.mark.asyncio()
    async def test_km_failure_graceful(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "intent_type": "feature",
                    "summary": "test",
                    "domains": ["x"],
                    "ambiguities": [],
                    "assumptions": [],
                    "scope_estimate": "small",
                }
            )
        )
        km = AsyncMock()
        km.query = AsyncMock(side_effect=RuntimeError("KM down"))
        decomposer = PromptDecomposer(agent=agent, knowledge_mound=km)
        intent = await decomposer.decompose("test")
        assert intent.summary == "test"

    @pytest.mark.asyncio()
    async def test_decompose_reuses_km_cache_for_same_prompt(self) -> None:
        from aragora.prompt_engine.decomposer import PromptDecomposer

        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "intent_type": "feature",
                    "summary": "test",
                    "domains": ["x"],
                    "ambiguities": [],
                    "assumptions": [],
                    "scope_estimate": "small",
                }
            )
        )
        km = AsyncMock()
        km.query = AsyncMock(return_value=[{"title": "Dark mode", "content": "cached"}])
        decomposer = PromptDecomposer(agent=agent, knowledge_mound=km)

        await decomposer.decompose("test")
        await decomposer.decompose("test")

        km.query.assert_called_once()


# ===========================================================================
# Interrogator tests
# ===========================================================================


class TestPromptInterrogator:
    @pytest.fixture()
    def mock_agent(self) -> AsyncMock:
        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "questions": [
                        {
                            "question": "Which pages need dark mode?",
                            "why_it_matters": "Scope determination",
                            "options": [
                                {
                                    "label": "All pages",
                                    "description": "Full app dark mode",
                                    "tradeoffs": "More work",
                                },
                                {
                                    "label": "Settings only",
                                    "description": "Just settings",
                                    "tradeoffs": "Less work",
                                },
                            ],
                            "default": "Settings only",
                        },
                        {
                            "question": "Auto-detect OS preference?",
                            "why_it_matters": "UX quality",
                            "options": [
                                {"label": "Yes", "description": "Auto-detect"},
                                {"label": "No", "description": "Manual toggle"},
                            ],
                            "default": "Yes",
                        },
                    ]
                }
            )
        )
        return agent

    @pytest.mark.asyncio()
    async def test_interrogate_basic(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        interrogator = PromptInterrogator(agent=mock_agent)
        intent = _make_intent()
        questions = await interrogator.interrogate(intent)
        assert len(questions) == 2
        assert questions[0].question == "Which pages need dark mode?"
        assert len(questions[0].options) == 2

    @pytest.mark.asyncio()
    async def test_interrogate_depth_string(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        interrogator = PromptInterrogator(agent=mock_agent)
        intent = _make_intent()
        questions = await interrogator.interrogate(intent, depth="quick")
        assert len(questions) >= 1

    @pytest.mark.asyncio()
    async def test_interrogate_fallback_no_ambiguities(self) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="not json")
        interrogator = PromptInterrogator(agent=agent)
        intent = _make_intent(ambiguities=[])
        questions = await interrogator.interrogate(intent)
        assert len(questions) >= 1
        assert "primary goal" in questions[0].question.lower()

    @pytest.mark.asyncio()
    async def test_interrogate_fallback_adds_epistemic_battery_for_vague_prompt(self) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="not json")
        interrogator = PromptInterrogator(agent=agent)
        intent = _make_intent(
            prompt="Make our product better for enterprise customers",
            ambiguities=[],
            assumptions=[],
        )
        questions = await interrogator.interrogate(intent)
        texts = [q.question for q in questions]

        assert any("What would make this wrong" in text for text in texts)
        assert any("What did we assume" in text for text in texts)
        assert any("Should this be done" in text for text in texts)

    @pytest.mark.asyncio()
    async def test_interrogate_fallback_with_ambiguities(self) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="not json")
        interrogator = PromptInterrogator(agent=agent)
        intent = _make_intent()
        questions = await interrogator.interrogate(intent)
        assert len(questions) >= 1
        assert questions[0].question == "Which onboarding?"

    @pytest.mark.asyncio()
    async def test_interrogate_empty_questions_list(self) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value=json.dumps({"questions": []}))
        interrogator = PromptInterrogator(agent=agent)
        intent = _make_intent()
        questions = await interrogator.interrogate(intent)
        assert len(questions) >= 1

    @pytest.mark.asyncio()
    async def test_interrogate_llm_preface_and_code_block(self) -> None:
        from aragora.prompt_engine.interrogator import PromptInterrogator

        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=(
                "Questions follow:\n```json\n"
                + json.dumps(
                    {
                        "questions": [
                            {
                                "question": "Which audience?",
                                "why_it_matters": "Changes UX",
                                "options": [{"label": "New", "description": "New users"}],
                            }
                        ]
                    }
                )
                + "\n```"
            )
        )
        interrogator = PromptInterrogator(agent=agent)
        intent = _make_intent()
        questions = await interrogator.interrogate(intent)
        assert questions[0].question == "Which audience?"


# ===========================================================================
# Researcher tests
# ===========================================================================


class TestPromptResearcher:
    @pytest.fixture()
    def mock_agent(self) -> AsyncMock:
        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "summary": "Onboarding flow analysis complete",
                    "current_state": "3-step wizard with 40% drop-off",
                    "related_decisions": [
                        {"title": "Q1 redesign", "summary": "Planned", "relevance": 0.9}
                    ],
                    "competitive_analysis": "Competitors use single-page",
                    "recommendations": ["Reduce to 2 steps", "Add progress indicator"],
                }
            )
        )
        return agent

    @pytest.mark.asyncio()
    async def test_research_basic(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        researcher = PromptResearcher(agent=mock_agent)
        intent = _make_intent()
        report = await researcher.research(intent)
        assert "analysis complete" in report.summary.lower()
        assert len(report.recommendations) == 2

    @pytest.mark.asyncio()
    async def test_research_with_km(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        km = AsyncMock()
        km.query = AsyncMock(
            return_value=[
                {
                    "title": "Prior debate",
                    "content": "Keep it simple",
                    "metadata": {"source": "debate"},
                }
            ]
        )
        researcher = PromptResearcher(agent=mock_agent, knowledge_mound=km)
        intent = _make_intent()
        report = await researcher.research(intent)
        assert len(report.evidence) >= 1

    @pytest.mark.asyncio()
    async def test_research_with_answered_questions(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        researcher = PromptResearcher(agent=mock_agent)
        intent = _make_intent()
        questions = [
            ClarifyingQuestion(question="Which flow?", why_it_matters="scope", answer="web")
        ]
        await researcher.research(intent, answered_questions=questions)
        call_prompt = mock_agent.generate.call_args[0][0]
        assert "web" in call_prompt

    @pytest.mark.asyncio()
    async def test_research_fallback(self) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="unstructured text")
        researcher = PromptResearcher(agent=agent)
        intent = _make_intent()
        report = await researcher.research(intent)
        assert "unstructured" in report.summary.lower()

    @pytest.mark.asyncio()
    async def test_research_llm_preface_and_code_block(self) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=(
                "Research complete:\n```json\n"
                + json.dumps(
                    {
                        "summary": "Done",
                        "current_state": "Existing flow",
                        "related_decisions": [],
                        "recommendations": ["Keep it simple"],
                    }
                )
                + "\n```"
            )
        )
        researcher = PromptResearcher(agent=agent)
        intent = _make_intent()
        report = await researcher.research(intent)
        assert report.summary == "Done"

    @pytest.mark.asyncio()
    async def test_research_reuses_km_cache_for_same_intent(self) -> None:
        from aragora.prompt_engine.researcher import PromptResearcher

        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "summary": "Done",
                    "current_state": "Existing flow",
                    "related_decisions": [],
                    "recommendations": ["Keep it simple"],
                }
            )
        )
        km = AsyncMock()
        km.query = AsyncMock(
            return_value=[
                {
                    "title": "Prior debate",
                    "content": "Keep it simple",
                    "metadata": {"source": "debate"},
                }
            ]
        )
        researcher = PromptResearcher(agent=agent, knowledge_mound=km)
        intent = _make_intent()

        await researcher.research(intent)
        await researcher.research(intent)

        km.query.assert_called_once()


# ===========================================================================
# SpecBuilder tests
# ===========================================================================


class TestSpecBuilder:
    @pytest.fixture()
    def mock_agent(self) -> AsyncMock:
        agent = AsyncMock()
        agent.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "title": "Dark Mode Implementation",
                    "problem_statement": "Users want dark mode",
                    "proposed_solution": "CSS custom properties with toggle",
                    "alternatives_considered": ["Tailwind dark:", "Separate CSS"],
                    "file_changes": [
                        {
                            "path": "src/styles/theme.css",
                            "action": "modify",
                            "description": "Add dark mode variables",
                            "estimated_lines": 50,
                        }
                    ],
                    "dependencies": [],
                    "risks": [
                        {
                            "description": "Colors may not meet WCAG",
                            "likelihood": "medium",
                            "impact": "high",
                            "mitigation": "Use contrast checker",
                        }
                    ],
                    "success_criteria": [
                        {
                            "description": "All pages render",
                            "measurement": "Visual regression",
                            "target": "0 failures",
                        }
                    ],
                    "estimated_effort": "medium",
                    "confidence": 0.85,
                }
            )
        )
        return agent

    @pytest.mark.asyncio()
    async def test_build_basic(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.spec_builder import SpecBuilder

        builder = SpecBuilder(agent=mock_agent)
        intent = _make_intent()
        spec = await builder.build(intent)
        assert spec.title == "Dark Mode Implementation"
        assert spec.is_high_confidence
        assert len(spec.file_changes) == 1
        assert spec.provenance is not None
        assert spec.provenance.original_prompt == intent.raw_prompt

    @pytest.mark.asyncio()
    async def test_build_with_research(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.spec_builder import SpecBuilder

        builder = SpecBuilder(agent=mock_agent)
        intent = _make_intent()
        report = ResearchReport(
            summary="Good findings",
            current_state="No dark mode",
            recommendations=["Use CSS vars"],
            competitive_analysis="Everyone has dark mode",
        )
        spec = await builder.build(intent, research=report)
        call_prompt = mock_agent.generate.call_args[0][0]
        assert "CSS vars" in call_prompt

    @pytest.mark.asyncio()
    async def test_build_fallback(self) -> None:
        from aragora.prompt_engine.spec_builder import SpecBuilder

        agent = AsyncMock()
        agent.generate = AsyncMock(return_value="just some text")
        builder = SpecBuilder(agent=agent)
        intent = _make_intent()
        spec = await builder.build(intent)
        assert spec.confidence == 0.1
        assert "manual" in spec.proposed_solution.lower()


# ===========================================================================
# ConductorConfig tests
# ===========================================================================


class TestConductorConfig:
    def test_default_config(self) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig

        config = ConductorConfig()
        assert config.autonomy == AutonomyLevel.PROPOSE_AND_APPROVE
        assert config.interrogation_depth == InterrogationDepth.THOROUGH

    def test_from_profile_founder(self) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig

        config = ConductorConfig.from_profile("founder")
        assert config.interrogation_depth == InterrogationDepth.QUICK
        assert config.auto_execute_threshold == 0.8

    def test_from_profile_enum(self) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig

        config = ConductorConfig.from_profile(UserProfile.CTO)
        assert config.interrogation_depth == InterrogationDepth.THOROUGH
        assert config.auto_execute_threshold == 0.9

    def test_from_profile_invalid(self) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig

        config = ConductorConfig.from_profile("nonexistent")
        assert config.autonomy == AutonomyLevel.PROPOSE_AND_APPROVE


# ===========================================================================
# Conductor tests
# ===========================================================================


_DECOMPOSE_RESPONSE = json.dumps(
    {
        "intent_type": "improvement",
        "summary": "Improve the onboarding flow",
        "domains": ["frontend"],
        "ambiguities": [
            {
                "description": "Which onboarding?",
                "impact": "Scope",
                "options": ["web", "mobile"],
                "recommended": "web",
            }
        ],
        "assumptions": [],
        "scope_estimate": "medium",
    }
)

_INTERROGATE_RESPONSE = json.dumps(
    {
        "questions": [
            {
                "question": "Target audience?",
                "why_it_matters": "UX design",
                "options": [
                    {"label": "New users", "description": "First-time"},
                    {"label": "Returning", "description": "Existing"},
                ],
                "default": "New users",
            }
        ]
    }
)

_RESEARCH_RESPONSE = json.dumps(
    {
        "summary": "Context gathered",
        "current_state": "3-step wizard",
        "related_decisions": [],
        "recommendations": ["Simplify"],
    }
)

_SPEC_RESPONSE = json.dumps(
    {
        "title": "Onboarding Improvement",
        "problem_statement": "Drop-off too high",
        "proposed_solution": "Reduce steps",
        "alternatives_considered": [],
        "file_changes": [],
        "dependencies": [],
        "risks": [],
        "success_criteria": [],
        "estimated_effort": "medium",
        "confidence": 0.88,
    }
)


class TestPromptConductor:
    @pytest.fixture()
    def mock_agent(self) -> AsyncMock:
        """Agent that returns valid JSON for all pipeline stages.

        Uses keyword matching on the prompt to return appropriate responses.
        Order matters: more specific patterns checked first.
        """
        agent = AsyncMock()
        call_count = {"n": 0}

        def side_effect(prompt: str) -> str:
            call_count["n"] += 1
            p = prompt.lower()
            # Decompose: contains "product analyst" from _DECOMPOSITION_PROMPT
            if "product analyst" in p:
                return _DECOMPOSE_RESPONSE
            # Interrogate: contains "clarifying" from _INTERROGATION_PROMPT
            if "clarifying" in p:
                return _INTERROGATE_RESPONSE
            # Spec: contains "software architect" from _SPEC_PROMPT
            if "software architect" in p or "specification" in p:
                return _SPEC_RESPONSE
            # Research: contains "technical researcher" from _RESEARCH_PROMPT
            if "technical researcher" in p:
                return _RESEARCH_RESPONSE
            # Fallback to spec response for anything else
            return _SPEC_RESPONSE

        agent.generate = AsyncMock(side_effect=side_effect)
        return agent

    @pytest.mark.asyncio()
    async def test_full_pipeline(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(autonomy=AutonomyLevel.FULL_AUTO)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")

        assert result.specification.title == "Onboarding Improvement"
        assert result.intent.intent_type == IntentType.IMPROVEMENT
        assert "decompose" in result.stages_completed
        assert "interrogate" in result.stages_completed
        assert "research" in result.stages_completed
        assert "specify" in result.stages_completed
        assert result.timing.is_within_target is True
        assert set(result.timing.stage_durations_ms) == {
            "decompose",
            "interrogate",
            "research",
            "specify",
        }
        assert result.timing.slowest_stage_name in {
            "decompose",
            "interrogate",
            "research",
            "specify",
        }
        assert any(
            item.operation.endswith(".agent_generate") for item in result.timing.operation_timings
        )
        top_durations = [item.duration_ms for item in result.timing.top_operations()]
        assert top_durations == sorted(top_durations, reverse=True)
        serialized_timing = result.timing.to_dict()
        assert serialized_timing["slowest_stage"]["stage"] == result.timing.slowest_stage_name
        assert (
            serialized_timing["top_operations"][0]["operation"]
            == result.timing.top_operations(limit=1)[0].operation
        )
        assert "llm" in serialized_timing["category_durations_ms"]

    @pytest.mark.asyncio()
    async def test_full_pipeline_reports_bottlenecks_against_target(self) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        async def side_effect(prompt: str) -> str:
            prompt_lower = prompt.lower()
            if "technical researcher" in prompt_lower:
                await asyncio.sleep(0.03)
                return _RESEARCH_RESPONSE
            if "clarifying" in prompt_lower:
                await asyncio.sleep(0.005)
                return _INTERROGATE_RESPONSE
            if "software architect" in prompt_lower or "specification" in prompt_lower:
                await asyncio.sleep(0.02)
                return _SPEC_RESPONSE
            await asyncio.sleep(0.005)
            return _DECOMPOSE_RESPONSE

        agent = AsyncMock()
        agent.generate = AsyncMock(side_effect=side_effect)

        config = ConductorConfig(
            autonomy=AutonomyLevel.FULL_AUTO,
            latency_target_ms=25,
        )
        conductor = PromptConductor(config=config, agent=agent)
        result = await conductor.run("Improve onboarding")

        assert result.timing.is_within_target is False
        bottlenecks = result.timing.bottlenecks()
        assert [timing.operation for timing in bottlenecks[:2]] == [
            "research.agent_generate",
            "specify.agent_generate",
        ]
        assert result.timing.slowest_stage_name == "research"

    @pytest.mark.asyncio()
    async def test_skip_interrogation(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(skip_interrogation=True)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")
        assert "interrogate" not in result.stages_completed
        assert len(result.questions) == 0

    @pytest.mark.asyncio()
    async def test_skip_research(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(skip_research=True)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")
        assert "research" not in result.stages_completed
        assert result.research is None

    @pytest.mark.asyncio()
    async def test_auto_approved_full_auto(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(autonomy=AutonomyLevel.FULL_AUTO, auto_execute_threshold=0.85)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")
        assert result.auto_approved is True

    @pytest.mark.asyncio()
    async def test_not_auto_approved_non_full_auto(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(autonomy=AutonomyLevel.PROPOSE_AND_APPROVE)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")
        assert result.auto_approved is False

    @pytest.mark.asyncio()
    async def test_question_handler_called(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        handler = AsyncMock(side_effect=lambda qs: qs)
        config = ConductorConfig()
        conductor = PromptConductor(config=config, agent=mock_agent, on_questions=handler)
        result = await conductor.run("Improve onboarding")
        handler.assert_called_once()
        assert len(result.questions) >= 1

    @pytest.mark.asyncio()
    async def test_decompose_only(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import PromptConductor

        conductor = PromptConductor(agent=mock_agent)
        intent = await conductor.decompose_only("Improve onboarding")
        assert intent.intent_type == IntentType.IMPROVEMENT
        assert mock_agent.generate.call_count == 1

    @pytest.mark.asyncio()
    async def test_full_auto_fills_defaults(self, mock_agent: AsyncMock) -> None:
        from aragora.prompt_engine.conductor import ConductorConfig, PromptConductor

        config = ConductorConfig(autonomy=AutonomyLevel.FULL_AUTO)
        conductor = PromptConductor(config=config, agent=mock_agent)
        result = await conductor.run("Improve onboarding")
        for q in result.questions:
            if q.default:
                assert q.is_answered
