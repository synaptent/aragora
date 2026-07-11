"""Tests for the interrogation questioner module."""

import pytest

from aragora.interrogation.questioner import InterrogationQuestioner, Question, QuestionSet
from aragora.interrogation.decomposer import Dimension
from aragora.interrogation.researcher import ResearchResult, Finding, ResearchSource


class TestInterrogationQuestioner:
    @pytest.fixture
    def questioner(self):
        return InterrogationQuestioner()

    @pytest.fixture
    def dimensions_with_research(self):
        dims = [
            Dimension(
                name="performance",
                description="Speed improvements",
                vagueness_score=0.7,
                keywords=["fast"],
            ),
        ]
        research = ResearchResult(
            findings={
                "performance": [
                    Finding(
                        source=ResearchSource.KNOWLEDGE_MOUND,
                        content="Prior debate: caching vs CDN",
                        relevance=0.8,
                    ),
                ]
            }
        )
        return dims, research

    def test_generate_questions_returns_question_set(self, questioner, dimensions_with_research):
        dims, research = dimensions_with_research
        result = questioner.generate(dims, research)
        assert isinstance(result, QuestionSet)
        assert len(result.questions) >= 1

    def test_question_has_required_fields(self, questioner, dimensions_with_research):
        dims, research = dimensions_with_research
        result = questioner.generate(dims, research)
        q = result.questions[0]
        assert q.text
        assert q.why
        assert q.dimension_name
        assert isinstance(q.options, list)

    def test_questions_sorted_by_priority(self, questioner):
        dims = [
            Dimension(name="a", description="Low vagueness", vagueness_score=0.2, keywords=[]),
            Dimension(name="b", description="High vagueness", vagueness_score=0.9, keywords=[]),
        ]
        research = ResearchResult()
        result = questioner.generate(dims, research)
        if len(result.questions) >= 2:
            assert result.questions[0].priority >= result.questions[1].priority

    def test_no_questions_for_concrete_dimensions(self, questioner):
        dims = [
            Dimension(
                name="typo", description="Fix typo in readme", vagueness_score=0.1, keywords=[]
            )
        ]
        research = ResearchResult()
        result = questioner.generate(dims, research)
        assert len(result.questions) == 0

    def test_vague_dimensions_include_epistemic_battery_questions(self, questioner):
        dims = [
            Dimension(
                name="product",
                description="Make our product better",
                vagueness_score=0.8,
                keywords=["product", "better"],
            )
        ]
        result = questioner.generate(dims, ResearchResult())
        texts = [q.text for q in result.questions]
        assert any("What do you need from me" in text for text in texts)
        assert any("What would make this wrong" in text for text in texts)
        assert any(q.dimension_name == "epistemic:falsifier" for q in result.questions)

    def test_question_includes_research_context(self, questioner, dimensions_with_research):
        dims, research = dimensions_with_research
        result = questioner.generate(dims, research)
        if result.questions:
            q = result.questions[0]
            assert q.context
