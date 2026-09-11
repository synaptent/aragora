"""Prompt Researcher - Investigates context around a PromptIntent.

Queries Knowledge Mound, codebase structure, and optionally web sources
to build a ResearchReport with evidence, current state analysis, and
recommendations.

Usage:
    researcher = PromptResearcher(knowledge_mound=km)
    report = await researcher.research(intent)
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.prompt_engine.processing import (
    append_context_block,
    format_answered_questions,
    format_km_context,
    parse_json_object,
    prompt_hash,
)
from aragora.prompt_engine.timing import OperationTiming, append_timing, format_timings, start_timer
from aragora.prompt_engine.types import (
    ClarifyingQuestion,
    EvidenceLink,
    PromptIntent,
    ResearchReport,
)

logger = logging.getLogger(__name__)

_KM_CACHE_MAX_SIZE = 32

_RESEARCH_PROMPT = """\
You are a senior technical researcher. Analyze the user's intent and produce
a research report covering:

1. **current_state**: What exists now relevant to this intent
2. **related_decisions**: Past decisions that affect this work (as list of dicts with title/summary/relevance)
3. **competitive_analysis**: How others solve this (if applicable)
4. **recommendations**: Ordered list of actionable recommendations

Intent summary: {summary}
Intent type: {intent_type}
Domains: {domains}
Scope: {scope}

{clarifications}

{knowledge_context}

Respond with valid JSON only. No markdown formatting.
"""


class PromptResearcher:
    """Researches context around a PromptIntent."""

    def __init__(
        self,
        agent: Any | None = None,
        knowledge_mound: Any | None = None,
    ) -> None:
        self._agent = agent
        self._km = knowledge_mound
        self._last_operation_timings: list[OperationTiming] = []
        self._km_cache: OrderedDict[str, str] = OrderedDict()

    @property
    def last_operation_timings(self) -> list[OperationTiming]:
        """Timing records from the most recent research run."""
        return list(self._last_operation_timings)

    async def _get_agent(self) -> Any:
        """Lazy-load the default agent."""
        if self._agent is not None:
            return self._agent

        try:
            from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

            self._agent = AnthropicAPIAgent(
                name="researcher",
                model="claude-sonnet-4-6",
                thinking_budget=8000,
            )
            return self._agent
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("Could not create Anthropic agent: %s", e)

        try:
            if is_secret_presence_available(get_secret_presence("OPENROUTER_API_KEY")):
                from aragora.agents.api_agents.openrouter import OpenRouterAgent

                self._agent = OpenRouterAgent(name="researcher", model="anthropic/claude-opus-5")
                return self._agent
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("Could not create OpenRouter agent: %s", e)

        raise RuntimeError("No agent available for research")

    async def research(
        self,
        intent: PromptIntent,
        answered_questions: list[ClarifyingQuestion] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ResearchReport:
        """Research context for a prompt intent.

        Args:
            intent: The decomposed prompt intent
            answered_questions: Questions that have been answered
            context: Optional additional context

        Returns:
            ResearchReport with findings
        """
        timings: list[OperationTiming] = []

        timer = start_timer()
        agent = await self._get_agent()
        append_timing(timings, "research.get_agent", timer, category="setup")

        clarification_text = format_answered_questions(
            answered_questions,
            header="Clarifications received:",
        )

        timer = start_timer()
        km_context = await self._get_km_context(intent)
        append_timing(
            timings,
            "research.km_query",
            timer,
            category="io",
            has_context=bool(km_context),
        )
        knowledge_text = (
            f"Relevant knowledge from Knowledge Mound:\n{km_context}"
            if km_context
            else "No prior knowledge found."
        )

        prompt = _RESEARCH_PROMPT.format(
            summary=intent.summary,
            intent_type=intent.intent_type.value,
            domains=", ".join(intent.domains),
            scope=intent.scope_estimate.value,
            clarifications=clarification_text,
            knowledge_context=knowledge_text,
        )

        prompt = append_context_block(prompt, context)

        timer = start_timer()
        response = await agent.generate(prompt)
        append_timing(
            timings,
            "research.agent_generate",
            timer,
            category="llm",
            prompt_chars=len(prompt),
            response_chars=len(response),
        )
        timer = start_timer()
        report = self._parse_report(response, km_context)
        append_timing(
            timings,
            "research.parse_report",
            timer,
            category="compute",
            evidence_count=len(report.evidence),
            recommendation_count=len(report.recommendations),
        )
        self._last_operation_timings = timings
        logger.debug("PromptResearcher timings: %s", format_timings(timings))
        return report

    async def _get_km_context(self, intent: PromptIntent) -> str:
        """Query Knowledge Mound for relevant context."""
        if self._km is None:
            return ""

        cache_key = self._km_cache_key(intent)
        cached = self._km_cache.get(cache_key)
        if cached is not None:
            self._km_cache.move_to_end(cache_key)
            return cached

        try:
            results = await self._km.query(
                query=intent.summary,
                limit=10,
            )
            if not isinstance(results, list) or not results:
                self._store_km_cache(cache_key, "")
                return ""

            context = format_km_context(
                results,
                limit=10,
                content_chars=300,
                include_source=True,
            )
            self._store_km_cache(cache_key, context)
            return context
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.debug("KM research query failed: %s", e)
            self._store_km_cache(cache_key, "")
            return ""

    def _parse_report(self, response: str, km_context: str) -> ResearchReport:
        """Parse LLM response into a ResearchReport."""
        data = parse_json_object(response)
        if data is None:
            logger.warning("Could not parse research response")
            return self._fallback_report(response.strip())

        try:
            evidence = []
            if km_context:
                evidence.append(
                    EvidenceLink(
                        source="km",
                        title="Knowledge Mound context",
                        snippet=km_context[:500],
                    )
                )

            for ev in data.get("evidence", []):
                if not isinstance(ev, dict):
                    continue
                evidence.append(
                    EvidenceLink(
                        source=ev.get("source", "unknown"),
                        title=ev.get("title", ""),
                        url=ev.get("url"),
                        relevance=float(ev.get("relevance", 1.0)),
                        snippet=ev.get("snippet", ""),
                    )
                )

            return ResearchReport(
                summary=data.get("summary", "Research complete"),
                current_state=data.get("current_state", ""),
                related_decisions=data.get("related_decisions", []),
                evidence=evidence,
                competitive_analysis=data.get("competitive_analysis", ""),
                recommendations=data.get("recommendations", []),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Error building ResearchReport: %s", e)
            return self._fallback_report(response.strip())

    @staticmethod
    def _fallback_report(raw_text: str) -> ResearchReport:
        """Create a minimal report when parsing fails."""
        return ResearchReport(
            summary="Research completed (unstructured)",
            current_state=raw_text[:1000],
        )

    @staticmethod
    def _km_cache_key(intent: PromptIntent) -> str:
        """Build a stable cache key for Knowledge Mound lookups."""
        scope = (
            intent.scope_estimate.value
            if hasattr(intent.scope_estimate, "value")
            else str(intent.scope_estimate)
        )
        return prompt_hash(
            "\x1f".join(
                [
                    intent.summary,
                    intent.intent_type.value,
                    scope,
                    ",".join(intent.domains),
                ]
            )
        )

    def _store_km_cache(self, key: str, value: str) -> None:
        """Store a bounded Knowledge Mound context cache entry."""
        self._km_cache[key] = value
        self._km_cache.move_to_end(key)
        while len(self._km_cache) > _KM_CACHE_MAX_SIZE:
            self._km_cache.popitem(last=False)
