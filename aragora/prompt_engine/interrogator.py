"""Prompt Interrogator - Generates clarifying questions from ambiguities.

Takes a PromptIntent and produces targeted ClarifyingQuestions that resolve
ambiguities before building a specification.

Usage:
    interrogator = PromptInterrogator()
    questions = await interrogator.interrogate(intent, depth="thorough")
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.config.secrets import get_secret_presence
from aragora.epistemic.question_batteries import QuestionBattery, build_intake_battery_questions
from aragora.prompt_engine.processing import append_context_block, parse_json_object
from aragora.prompt_engine.timing import OperationTiming, append_timing, format_timings, start_timer
from aragora.prompt_engine.types import (
    ClarifyingQuestion,
    InterrogationDepth,
    PromptIntent,
    QuestionOption,
)

logger = logging.getLogger(__name__)

_DEPTH_LIMITS = {
    InterrogationDepth.QUICK: (3, 5),
    InterrogationDepth.THOROUGH: (10, 15),
    InterrogationDepth.EXHAUSTIVE: (20, 30),
}

_INTERROGATION_PROMPT = """\
You are a senior product analyst. Given a user's intent, generate clarifying
questions that MUST be answered before building an implementation specification.

Focus on questions that change the architecture, scope, or approach. Skip
trivial clarifications.

Reusable epistemic question patterns to consider when the prompt is vague:
- What do you need from me?
- What would make this wrong?
- What did we assume?
- Should this be done?

For each question provide:
- question: The question text
- why_it_matters: Why this affects the implementation
- options: 2-4 suggested answers, each with label, description, and tradeoffs
- default: Your recommended answer (or null if genuinely ambiguous)

Intent summary: {summary}
Intent type: {intent_type}
Domains: {domains}
Scope: {scope}

Known ambiguities:
{ambiguities}

Known assumptions:
{assumptions}

Generate {min_q} to {max_q} questions. Respond with valid JSON only:
{{"questions": [...]}}
"""


class PromptInterrogator:
    """Generates clarifying questions from a PromptIntent."""

    def __init__(self, agent: Any | None = None) -> None:
        self._agent = agent
        self._last_operation_timings: list[OperationTiming] = []

    @property
    def last_operation_timings(self) -> list[OperationTiming]:
        """Timing records from the most recent interrogation run."""
        return list(self._last_operation_timings)

    async def _get_agent(self) -> Any:
        """Lazy-load the default agent."""
        if self._agent is not None:
            return self._agent

        try:
            from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

            self._agent = AnthropicAPIAgent(
                name="interrogator",
                model="claude-sonnet-4-6",
                thinking_budget=4000,
            )
            return self._agent
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("Could not create Anthropic agent: %s", e)

        try:
            if get_secret_presence("OPENROUTER_API_KEY").source in {"aws", "env"}:
                from aragora.agents.api_agents.openrouter import OpenRouterAgent

                self._agent = OpenRouterAgent(
                    name="interrogator", model="anthropic/claude-opus-4.8"
                )
                return self._agent
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("Could not create OpenRouter agent: %s", e)

        raise RuntimeError("No agent available for interrogation")

    async def interrogate(
        self,
        intent: PromptIntent,
        depth: InterrogationDepth | str = InterrogationDepth.THOROUGH,
        context: dict[str, Any] | None = None,
    ) -> list[ClarifyingQuestion]:
        """Generate clarifying questions for a prompt intent.

        Args:
            intent: The decomposed prompt intent
            depth: How many questions to generate
            context: Optional additional context

        Returns:
            List of ClarifyingQuestion objects
        """
        if isinstance(depth, str):
            try:
                depth = InterrogationDepth(depth)
            except ValueError:
                depth = InterrogationDepth.THOROUGH

        min_q, max_q = _DEPTH_LIMITS.get(depth, (10, 15))

        ambiguity_text = (
            "\n".join(f"- {a.description} (impact: {a.impact})" for a in intent.ambiguities)
            or "None detected"
        )

        assumption_text = (
            "\n".join(f"- {a.description} (confidence: {a.confidence})" for a in intent.assumptions)
            or "None detected"
        )

        prompt = _INTERROGATION_PROMPT.format(
            summary=intent.summary,
            intent_type=intent.intent_type.value,
            domains=", ".join(intent.domains),
            scope=intent.scope_estimate.value,
            ambiguities=ambiguity_text,
            assumptions=assumption_text,
            min_q=min_q,
            max_q=max_q,
        )

        prompt = append_context_block(prompt, context)

        timings: list[OperationTiming] = []
        timer = start_timer()
        agent = await self._get_agent()
        append_timing(timings, "interrogate.get_agent", timer, category="setup")
        timer = start_timer()
        response = await agent.generate(prompt)
        append_timing(
            timings,
            "interrogate.agent_generate",
            timer,
            category="llm",
            prompt_chars=len(prompt),
            response_chars=len(response),
        )
        timer = start_timer()
        questions = self._parse_questions(response, intent)
        append_timing(
            timings,
            "interrogate.parse_questions",
            timer,
            category="compute",
            question_count=len(questions),
        )
        self._last_operation_timings = timings
        logger.debug("PromptInterrogator timings: %s", format_timings(timings))
        return questions

    def _parse_questions(self, response: str, intent: PromptIntent) -> list[ClarifyingQuestion]:
        """Parse LLM response into ClarifyingQuestion objects."""
        data = parse_json_object(response)
        if data is None:
            logger.warning("Could not parse interrogation response")
            return self._fallback_questions(intent)

        questions_data = data.get("questions", [])
        if not isinstance(questions_data, list) or not questions_data:
            return self._fallback_questions(intent)

        questions = []
        for i, q in enumerate(questions_data):
            if not isinstance(q, dict):
                continue
            try:
                options = [
                    QuestionOption(
                        label=opt.get("label", f"Option {j + 1}"),
                        description=opt.get("description", ""),
                        tradeoffs=opt.get("tradeoffs", ""),
                    )
                    for j, opt in enumerate(q.get("options", []))
                    if isinstance(opt, dict)
                ]

                ambiguity_ref = None
                if i < len(intent.ambiguities):
                    ambiguity_ref = intent.ambiguities[i]

                questions.append(
                    ClarifyingQuestion(
                        question=q.get("question", ""),
                        why_it_matters=q.get("why_it_matters", ""),
                        options=options,
                        default=q.get("default"),
                        ambiguity_ref=ambiguity_ref,
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                logger.debug("Skipping malformed question: %s", e)

        return questions or self._fallback_questions(intent)

    @staticmethod
    def _fallback_questions(intent: PromptIntent) -> list[ClarifyingQuestion]:
        """Generate minimal questions from ambiguities when parsing fails."""
        questions = []
        for amb in intent.ambiguities:
            options = [QuestionOption(label=opt, description=opt) for opt in amb.options[:4]]
            questions.append(
                ClarifyingQuestion(
                    question=amb.description,
                    why_it_matters=amb.impact,
                    options=options,
                    default=amb.recommended,
                    ambiguity_ref=amb,
                )
            )
        prompt_text = intent.raw_prompt or intent.summary
        battery_questions = [
            PromptInterrogator._battery_to_clarifying_question(battery)
            for battery in build_intake_battery_questions(prompt_text)
        ]
        if questions:
            return questions + battery_questions
        return [
            ClarifyingQuestion(
                question="What is the primary goal of this request?",
                why_it_matters="Determines scope and approach",
                options=[
                    QuestionOption(
                        label="Quick fix",
                        description="Minimal change to address the immediate need",
                    ),
                    QuestionOption(
                        label="Comprehensive solution",
                        description="Full implementation with tests and documentation",
                    ),
                ],
            )
        ] + battery_questions

    @staticmethod
    def _battery_to_clarifying_question(battery: QuestionBattery) -> ClarifyingQuestion:
        options = [
            QuestionOption(label=option, description=option, tradeoffs="")
            for option in battery.options[:4]
        ]
        return ClarifyingQuestion(
            question=battery.question,
            why_it_matters=battery.why_it_matters,
            options=options,
            default=battery.options[0] if battery.options else None,
        )
