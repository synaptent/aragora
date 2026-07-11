"""Generate prioritized questions from dimensions and research findings."""

from __future__ import annotations

from dataclasses import dataclass, field

from aragora.epistemic.question_batteries import build_intake_battery_questions
from aragora.interrogation.decomposer import Dimension
from aragora.interrogation.researcher import ResearchResult


@dataclass
class Question:
    """A question to ask the user during interrogation."""

    text: str
    why: str
    dimension_name: str
    priority: float
    options: list[str] = field(default_factory=list)
    context: str = ""


@dataclass
class QuestionSet:
    """Prioritized set of questions for the user."""

    questions: list[Question] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.questions)


_VAGUENESS_THRESHOLD = 0.25


class InterrogationQuestioner:
    """Generates questions from decomposed dimensions and research findings."""

    def generate(
        self,
        dimensions: list[Dimension],
        research: ResearchResult,
    ) -> QuestionSet:
        questions: list[Question] = []

        for dim in dimensions:
            if dim.vagueness_score < _VAGUENESS_THRESHOLD:
                continue

            findings = research.for_dimension(dim.name)
            context = self._build_context(findings)

            q = Question(
                text=self._formulate_question(dim),
                why=self._explain_why(dim),
                dimension_name=dim.name,
                priority=dim.vagueness_score,
                options=self._suggest_options(dim, findings),
                context=context,
            )
            questions.append(q)

        vague_prompt = " ".join(dim.description or dim.name for dim in dimensions)
        max_vagueness = max((dim.vagueness_score for dim in dimensions), default=0.0)
        if max_vagueness >= _VAGUENESS_THRESHOLD:
            battery_priority = max_vagueness * 0.75
            for battery in build_intake_battery_questions(vague_prompt):
                questions.append(
                    Question(
                        text=battery.question,
                        why=battery.why_it_matters,
                        dimension_name=battery.dimension,
                        priority=battery_priority,
                        options=list(battery.options),
                        context=f"Epistemic question battery: {battery.name}",
                    )
                )

        questions.sort(key=lambda q: q.priority, reverse=True)
        return QuestionSet(questions=questions)

    def _formulate_question(self, dim: Dimension) -> str:
        templates = {
            "performance": "What specific performance aspects matter most?",
            "user-experience": "What UX improvements would have the biggest impact?",
            "quality": "Which quality dimensions should we prioritize?",
            "functionality": "What specific capabilities do you want to add?",
            "security": "What security requirements apply here?",
            "infrastructure": "What infrastructure changes are needed?",
            "documentation": "What should be documented?",
            "maintainability": "What code quality issues should we address?",
        }
        return templates.get(dim.name, f"Can you be more specific about '{dim.name}'?")

    def _explain_why(self, dim: Dimension) -> str:
        return (
            f"This question matters because '{dim.name}' is vague "
            f"(score: {dim.vagueness_score:.1f}). Without clarification, "
            f"agents may pursue the wrong approach."
        )

    def _suggest_options(self, dim: Dimension, findings: list) -> list[str]:
        options: list[str] = []
        if findings:
            options.append("Build on prior work (found related context)")
        options.append("Start fresh with new approach")
        options.append("Let agents decide based on debate")
        return options

    def _build_context(self, findings: list) -> str:
        if not findings:
            return ""
        summaries = [f.content[:200] for f in findings[:3]]
        return "Related context found: " + " | ".join(summaries)
