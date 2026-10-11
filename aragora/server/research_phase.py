"""
Pre-debate research phase for current events.

Performs web search to gather current information before debates
on time-sensitive topics.

Supports multiple search backends:
1. Claude's built-in web_search tool (primary - requires ANTHROPIC_API_KEY)
2. Brave Search API (requires BRAVE_API_KEY)
3. Serper/Google Search API (requires SERPER_API_KEY)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import httpx

from aragora.agents.errors.classifier import ErrorClassifier
from aragora.agents.fallback import get_default_fallback_enabled
from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.models.compat import first_text_block

if TYPE_CHECKING:
    import anthropic
    from aragora.agents.api_agents import OpenRouterAgent

logger = logging.getLogger(__name__)

# Use Claude's web search as primary when available
USE_CLAUDE_WEB_SEARCH = True

# Timeouts for research operations (seconds)
DEFAULT_TIMEOUT = float(os.getenv("ARAGORA_RESEARCH_HTTP_TIMEOUT", "45.0"))
CLAUDE_SEARCH_TIMEOUT = float(os.getenv("ARAGORA_CLAUDE_SEARCH_TIMEOUT", "240.0"))
SUMMARIZATION_TIMEOUT = float(os.getenv("ARAGORA_RESEARCH_SUMMARIZATION_TIMEOUT", "120.0"))

# Frontier pins (Opus 5). OpenRouter alias is used by default so research
# still runs when no direct Anthropic key is configured.
RESEARCH_MODEL = "claude-opus-5"
OPENROUTER_RESEARCH_MODEL = os.getenv(
    "ARAGORA_RESEARCH_OPENROUTER_MODEL",
    "anthropic/claude-opus-5",
)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    source: str = ""


@dataclass
class ResearchResult:
    """Result of pre-debate research."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    summary: str = ""
    sources: list[str] = field(default_factory=list)
    is_current_event: bool = False

    def to_context(self) -> str:
        """Convert to debate context string."""
        if not self.results and not self.summary:
            return ""

        parts = ["## Background Research\n"]

        if self.summary:
            parts.append(f"{self.summary}\n")

        if self.results:
            parts.append("\n### Key Sources:\n")
            for i, result in enumerate(self.results[:5], 1):
                parts.append(f"{i}. [{result.title}]({result.url})")
                if result.snippet:
                    parts.append(f"   {result.snippet[:200]}...")
                parts.append("")

        return "\n".join(parts)


class PreDebateResearcher:
    """Performs web search for current events before debates."""

    # Keywords that suggest a current event question
    CURRENT_EVENT_INDICATORS = [
        "today",
        "yesterday",
        "this week",
        "this month",
        "recent",
        "latest",
        "breaking",
        "news",
        "announced",
        "just",
        "new",
        "2024",
        "2025",
        "2026",
        "lawsuit",
        "ruling",
        "decision",
        "election",
        "happening",
        "update",
        "currently",
    ]

    def __init__(
        self,
        brave_api_key: str | None = None,
        serper_api_key: str | None = None,
        anthropic_client: anthropic.Anthropic | None = None,
        openrouter_model: str | None = None,
    ):
        """Initialize the researcher.

        Args:
            brave_api_key: Brave Search API key (from env BRAVE_API_KEY)
            serper_api_key: Serper API key (from env SERPER_API_KEY)
            anthropic_client: Optional Anthropic client for summarization
        """
        self.brave_api_key = brave_api_key or os.getenv("BRAVE_API_KEY")
        self.serper_api_key = serper_api_key or os.getenv("SERPER_API_KEY")
        self._anthropic_client = anthropic_client
        self._openrouter_model = openrouter_model or OPENROUTER_RESEARCH_MODEL
        self._enable_openrouter_fallback = get_default_fallback_enabled()
        self._openrouter_agent: OpenRouterAgent | None = None

    @property
    def anthropic_client(self) -> anthropic.Anthropic:
        """Get or create the Anthropic client."""
        if self._anthropic_client is None:
            import anthropic

            self._anthropic_client = anthropic.Anthropic()
        return self._anthropic_client

    def _should_try_openrouter_fallback(self, error: Exception) -> bool:
        """Return True when an error should trigger OpenRouter fallback."""
        return self._enable_openrouter_fallback and ErrorClassifier.should_fallback(error)

    def _get_openrouter_agent(self) -> OpenRouterAgent | None:
        """Lazily create the OpenRouter fallback agent for research tasks."""
        if not self._enable_openrouter_fallback:
            return None
        if self._openrouter_agent is not None:
            return self._openrouter_agent
        if not is_secret_presence_available(get_secret_presence("OPENROUTER_API_KEY")):
            return None

        from aragora.agents.api_agents import OpenRouterAgent

        self._openrouter_agent = OpenRouterAgent(
            name="research_openrouter_fallback",
            model=self._openrouter_model,
            role="analyst",
            timeout=int(max(SUMMARIZATION_TIMEOUT, DEFAULT_TIMEOUT)),
        )
        return self._openrouter_agent

    async def _generate_text_with_fallback(
        self,
        prompt: str,
        *,
        max_tokens: int,
        timeout_seconds: float = SUMMARIZATION_TIMEOUT,
    ) -> str:
        """
        Generate text with Anthropic first, then OpenRouter fallback on API failures.
        """
        try:
            # Offload sync Anthropic SDK call to thread pool.
            def _call_anthropic() -> Any:
                return self.anthropic_client.messages.create(
                    model=RESEARCH_MODEL,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )

            response = await asyncio.wait_for(asyncio.to_thread(_call_anthropic), timeout_seconds)
            # Opus 5 thinks by default: content[0] is a thinking block.
            text = first_text_block(response.content).strip()
            if text:
                return text

            # Empty text is a FAILURE, not a success. On a thinking-by-default
            # model an exhausted max_tokens yields thinking blocks and no text
            # block; returning "" here would look like a successful summary and
            # silently skip the OpenRouter fallback below.
            logger.warning(
                "[research] Anthropic returned no text block (thinking may have "
                "consumed max_tokens=%s); falling back to OpenRouter",
                max_tokens,
                extra={
                    "triage_diag_code": "provider_fallback",
                    "triage_diag_severity": "degraded",
                },
            )
            empty_fallback = self._get_openrouter_agent()
            if empty_fallback is None:
                return ""
            return await asyncio.wait_for(
                empty_fallback.generate(prompt),
                timeout_seconds,
            )
        except Exception as e:  # noqa: BLE001 - provider SDK raises many exception types
            if not self._should_try_openrouter_fallback(e):
                raise

            fallback_agent = self._get_openrouter_agent()
            if fallback_agent is None:
                raise

            logger.warning(
                "[research] Anthropic generation failed (%s), falling back to OpenRouter",
                type(e).__name__,
                extra={
                    "triage_diag_code": "provider_fallback",
                    "triage_diag_severity": "degraded",
                },
            )
            return await asyncio.wait_for(
                fallback_agent.generate(prompt),
                timeout_seconds,
            )

    def is_current_event(self, question: str) -> bool:
        """Check if the question relates to current events.

        Uses simple keyword matching for fast classification.
        """
        question_lower = question.lower()

        # Check for year references
        if any(year in question_lower for year in ["2024", "2025", "2026"]):
            return True

        # Check for current event indicators
        match_count = sum(
            1 for indicator in self.CURRENT_EVENT_INDICATORS if indicator in question_lower
        )

        return match_count >= 2

    async def _classify_with_llm(self, question: str) -> bool:
        """Use Claude to determine if question requires current info.

        More accurate but requires API call.
        """
        try:
            # Offload to thread pool to avoid blocking the event loop
            def _call_classify() -> Any:
                return self.anthropic_client.messages.create(
                    model=RESEARCH_MODEL,
                    # Opus 5 thinks by default and max_tokens covers thinking +
                    # response; 100 could be consumed entirely by thinking.
                    max_tokens=2048,
                    messages=[
                        {
                            "role": "user",
                            "content": f"""Does this debate question require current/recent information to answer well?

Question: {question}

Respond with just "yes" or "no".""",
                        }
                    ],
                )

            response = await asyncio.to_thread(_call_classify)
            # Opus 5 thinks by default: content[0] is a thinking block.
            content = first_text_block(response.content).strip().lower()
            return content.startswith("yes")
        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.warning("LLM classification failed: %s", e)
            return self.is_current_event(question)

    async def search_brave(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search using Brave Search API."""
        if not self.brave_api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": max_results},
                    headers={"X-Subscription-Token": self.brave_api_key},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("web", {}).get("results", [])[:max_results]:
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("url", ""),
                            snippet=item.get("description", ""),
                            source="brave",
                        )
                    )
                return results

        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Brave search failed: %s", e)
            return []

    async def search_serper(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search using Serper (Google Search) API."""
        if not self.serper_api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    "https://google.serper.dev/search",
                    json={"q": query, "num": max_results},
                    headers={
                        "X-API-KEY": self.serper_api_key,
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("organic", [])[:max_results]:
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("link", ""),
                            snippet=item.get("snippet", ""),
                            source="serper",
                        )
                    )
                return results

        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Serper search failed: %s", e)
            return []

    async def search_with_claude(self, question: str) -> ResearchResult:
        """Search using Claude's built-in web_search tool.

        This uses Claude's native web search capability which provides
        high-quality, summarized results with citations. Uses Opus 4.5
        for best quality research and longer timeout for thorough search.

        Args:
            question: The debate question to research

        Returns:
            ResearchResult with summary and sources from Claude's web search
        """
        import asyncio

        try:
            logger.info(
                "[claude_web_search] Researching with %s: %s...", RESEARCH_MODEL, question[:100]
            )

            # Define the sync API call to run in thread pool
            def _call_claude() -> Any:
                tools: list[Any] = [{"type": "web_search_20250305", "name": "web_search"}]
                return self.anthropic_client.messages.create(
                    model=RESEARCH_MODEL,
                    max_tokens=4096,
                    tools=cast(Any, tools),
                    messages=[
                        {
                            "role": "user",
                            "content": f"""Research the following topic to provide current, factual information for a debate:

Topic: {question}

Please search the web to find:
1. Current news and developments related to this topic
2. Key facts, statistics, and data points
3. Different perspectives and viewpoints
4. Recent events or announcements

Provide a comprehensive but concise summary (3-5 paragraphs) that includes:
- Current state of affairs
- Key facts with sources
- Different viewpoints if applicable
- Any recent developments

Focus on facts and cite your sources.""",
                        }
                    ],
                )

            # Run the sync call in thread pool with timeout
            response = await asyncio.wait_for(
                asyncio.to_thread(_call_claude),
                timeout=CLAUDE_SEARCH_TIMEOUT,
            )

            # Extract the summary and any citations from Claude's response
            summary_parts = []
            sources: list[str] = []
            results: list[SearchResult] = []

            for block in response.content:
                if hasattr(block, "text"):
                    summary_parts.append(block.text)
                elif hasattr(block, "type") and block.type == "tool_use":
                    # Claude used web_search tool
                    logger.debug("[claude_web_search] Tool used: %s", block.name)

            summary = "\n".join(summary_parts)

            # Extract URLs from the summary (Claude typically includes them)
            url_pattern = r"https?://[^\s\)\]\"\'<>]+"
            found_urls = re.findall(url_pattern, summary)
            sources = list(set(found_urls))[:10]

            # Create search results from extracted URLs
            for url in sources[:5]:
                results.append(
                    SearchResult(
                        title=self._extract_domain(url),
                        url=url,
                        snippet="",
                        source="claude_web_search",
                    )
                )

            logger.info(
                "[claude_web_search] Complete: %s chars, %s sources", len(summary), len(sources)
            )

            return ResearchResult(
                query=question,
                results=results,
                summary=summary,
                sources=sources,
                is_current_event=True,
            )

        except asyncio.TimeoutError:
            logger.warning("[claude_web_search] Timed out after %ss", CLAUDE_SEARCH_TIMEOUT)
            return ResearchResult(
                query=question,
                is_current_event=self.is_current_event(question),
            )
        except (OSError, ConnectionError, ValueError, RuntimeError) as e:
            logger.warning("[claude_web_search] Failed: %s", e)
            return ResearchResult(
                query=question,
                is_current_event=self.is_current_event(question),
            )
        except Exception as e:  # noqa: BLE001 - provider SDK raises typed API errors
            logger.warning("[claude_web_search] Unexpected API failure: %s", e)
            return ResearchResult(
                query=question,
                is_current_event=self.is_current_event(question),
            )

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL for display."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return parsed.netloc or url[:50]
        except ValueError:
            return url[:50]

    def _extract_search_query(self, question: str) -> str:
        """Extract an effective search query from the debate question."""
        # Remove common debate framing words
        framing_words = [
            "debate",
            "discuss",
            "argue",
            "should",
            "could",
            "would",
            "pros and cons",
            "implications",
            "what are",
            "why is",
            "how does",
        ]

        query = question
        for word in framing_words:
            query = re.sub(rf"\b{word}\b", "", query, flags=re.IGNORECASE)

        # Clean up whitespace
        query = " ".join(query.split())

        # Limit length
        words = query.split()
        if len(words) > 10:
            query = " ".join(words[:10])

        return query.strip()

    async def search(self, question: str, max_results: int = 5) -> ResearchResult:
        """Perform web search for the question.

        Tries available search APIs in order of preference:
        1. Claude's built-in web_search (always available with Anthropic API)
        2. Brave Search API
        3. Serper/Google Search API
        """
        query = self._extract_search_query(question)
        logger.info("[research] Searching for: %s", query)

        results: list[SearchResult] = []

        # Try Brave first, then Serper (for raw search results)
        if self.brave_api_key:
            results = await self.search_brave(query, max_results)

        if not results and self.serper_api_key:
            results = await self.search_serper(query, max_results)

        if not results:
            logger.info("[research] No external search results, will use Claude web search")
            return ResearchResult(
                query=query,
                is_current_event=self.is_current_event(question),
            )

        # Extract unique sources
        sources = list(set(r.url for r in results if r.url))

        return ResearchResult(
            query=query,
            results=results,
            sources=sources,
            is_current_event=True,
        )

    async def research_and_summarize(
        self, question: str, max_results: int = 5, use_claude_search: bool = True
    ) -> ResearchResult:
        """Search and summarize results for debate context.

        This provides a synthesized context for the debate by:
        1. Using Claude's web_search tool for comprehensive research (primary)
        2. Falling back to external APIs + Claude summarization if needed

        Args:
            question: The debate question to research
            max_results: Maximum results for external API fallback
            use_claude_search: If True, use Claude's built-in web search (recommended)

        Returns:
            ResearchResult with summary and sources
        """
        # Primary: Use Claude's built-in web search (best quality)
        if use_claude_search and USE_CLAUDE_WEB_SEARCH:
            logger.info("[research] Using Claude's built-in web search")
            result = await self.search_with_claude(question)
            if result.summary:
                return result
            logger.info("[research] Claude web search returned no summary, trying fallback")

        # Fallback: Use external APIs + Claude summarization
        result = await self.search(question, max_results)

        if not result.results:
            # Last resort: Use Claude to provide what it knows
            logger.info("[research] No external results, using Claude knowledge")
            return await self._research_with_claude_knowledge(question)

        # Summarize the results with Claude
        try:
            snippets = "\n\n".join(f"Source: {r.title}\n{r.snippet}" for r in result.results[:5])

            prompt = f"""Summarize these search results about: {question}

{snippets}

Provide a brief, factual summary (2-3 paragraphs) of the current situation.
Focus on facts, not opinions. Include relevant dates and specifics."""
            result.summary = await self._generate_text_with_fallback(
                prompt,
                max_tokens=4096,
                timeout_seconds=SUMMARIZATION_TIMEOUT,
            )

        except Exception as e:  # noqa: BLE001 - provider SDK + fallback provider errors
            logger.warning("[research] Summary generation failed: %s", e)

        return result

    async def _research_with_claude_knowledge(self, question: str) -> ResearchResult:
        """Use Claude's knowledge when no external search is available.

        This is a fallback that uses Claude's training data to provide
        context, with appropriate caveats about currency.
        """
        try:
            prompt = f"""Provide background context for a debate on: {question}

Please share what you know about this topic, including:
- Key facts and context
- Different perspectives
- Important considerations

Note: Clearly indicate if certain information may be outdated or requires verification."""
            summary = await self._generate_text_with_fallback(
                prompt,
                max_tokens=4096,
                timeout_seconds=SUMMARIZATION_TIMEOUT,
            )
            return ResearchResult(
                query=question,
                summary=f"## Background Context (from AI knowledge)\n\n{summary}\n\n*Note: This context is based on AI training data. For the most current information, external verification is recommended.*",
                is_current_event=False,
            )

        except Exception as e:  # noqa: BLE001 - provider SDK + fallback provider errors
            logger.warning("[research] Claude knowledge fallback failed: %s", e)
            return ResearchResult(
                query=question,
                summary="",
                is_current_event=False,
            )


async def research_question(
    question: str,
    summarize: bool = True,
    max_results: int = 5,
    force_research: bool = True,
) -> ResearchResult | None:
    """Research a debate question to provide current context.

    Always performs web search to ensure agents have current information.
    Uses Claude's built-in web_search tool as the primary search method.

    Args:
        question: The debate question
        summarize: Whether to summarize results (always True with Claude search)
        max_results: Maximum search results to fetch (for fallback APIs)
        force_research: If True, always research regardless of topic detection

    Returns:
        ResearchResult with summary and sources
    """
    researcher = PreDebateResearcher()

    # Always research if forced, otherwise check if it looks like current events
    if not force_research and not researcher.is_current_event(question):
        logger.debug("[research] Topic doesn't require current event research, skipping")
        return None

    logger.info("[research] Starting pre-debate research for: %s...", question[:80])

    if summarize:
        return await researcher.research_and_summarize(question, max_results)
    else:
        return await researcher.search(question, max_results)


async def research_for_debate(question: str) -> str:
    """Research a topic and return formatted context for debate agents.

    This is the main entry point for pre-debate research. It performs
    web search using Claude's built-in capabilities and returns a
    formatted summary to include in agent context.

    Args:
        question: The debate topic/question

    Returns:
        Formatted research context string (empty string if research fails)
    """
    try:
        result = await research_question(question, summarize=True, force_research=True)

        if not result or not result.summary:
            logger.info("[research] No research results available")
            return ""

        # Format as debate context
        context = result.to_context()
        if context:
            logger.info("[research] Prepared %s chars of research context", len(context))
        return context

    except Exception as e:  # noqa: BLE001 - provider SDK/network errors
        logger.warning("[research] Pre-debate research failed: %s", e)
        return ""
