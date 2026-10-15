"""
Source fetching for context gathering.

Handles fetching context from various sources:
- Claude web search (primary)
- Evidence connectors (web, GitHub, local docs)
- Pulse/trending topics
- Knowledge Mound
- Threat intelligence
- Culture patterns
- Belief crux analysis
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.runtime.connector_factory import ConnectorFactoryNotRegisteredError, create_connector

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_CONNECTOR_UNAVAILABLE = (ImportError, ConnectorFactoryNotRegisteredError)

# Configurable timeouts (in seconds)
CLAUDE_SEARCH_TIMEOUT = float(os.getenv("ARAGORA_CLAUDE_SEARCH_TIMEOUT", "240.0"))
EVIDENCE_TIMEOUT = float(os.getenv("ARAGORA_EVIDENCE_TIMEOUT", "30.0"))
TRENDING_TIMEOUT = float(os.getenv("ARAGORA_TRENDING_TIMEOUT", "5.0"))
KNOWLEDGE_MOUND_TIMEOUT = float(os.getenv("ARAGORA_KNOWLEDGE_MOUND_TIMEOUT", "10.0"))
BELIEF_CRUX_TIMEOUT = float(os.getenv("ARAGORA_BELIEF_CRUX_TIMEOUT", "5.0"))
THREAT_INTEL_TIMEOUT = float(os.getenv("ARAGORA_THREAT_INTEL_TIMEOUT", "10.0"))


class SourceFetcher:
    """
    Fetches context from various sources for debate grounding.

    Handles communication with external sources and services:
    - Claude's web search API
    - Evidence collector connectors
    - Pulse/trending topics manager
    - Knowledge Mound queries
    - Threat intelligence enrichment
    - Culture pattern retrieval
    - Belief crux analysis
    """

    def __init__(
        self,
        project_root: Path | None = None,
        knowledge_mound: Any | None = None,
        knowledge_workspace_id: str | None = None,
        threat_intel_enrichment: Any | None = None,
        belief_analyzer: Any | None = None,
        enable_trending_context: bool = True,
    ):
        """
        Initialize the source fetcher.

        Args:
            project_root: Project root path for local docs.
            knowledge_mound: KnowledgeMound instance for knowledge queries.
            knowledge_workspace_id: Workspace ID for knowledge queries.
            threat_intel_enrichment: ThreatIntelEnrichment instance.
            belief_analyzer: DebateBeliefAnalyzer instance.
            enable_trending_context: Whether to gather Pulse trending context.
        """
        self._project_root = project_root or Path(__file__).parent.parent.parent.parent
        self._knowledge_mound = knowledge_mound
        self._knowledge_workspace_id = knowledge_workspace_id or "debate"
        self._threat_intel_enrichment = threat_intel_enrichment
        self._belief_analyzer = belief_analyzer
        self._enable_trending_context = enable_trending_context

    async def gather_claude_web_search(self, task: str) -> str | None:
        """
        Perform web search using Claude's built-in web_search tool.

        This is the primary research method - uses Claude Opus 4.5 with
        web search capability to provide high-quality, current information.

        Args:
            task: The debate topic/task description.

        Returns:
            Formatted research context, or None if search fails.
        """
        try:
            from aragora.server.research_phase import research_for_debate

            logger.info("[research] Starting Claude web search for debate context...")

            result = await asyncio.wait_for(
                research_for_debate(task),
                timeout=CLAUDE_SEARCH_TIMEOUT,
            )

            if result:
                trimmed = result.strip()
                if "Key Sources" not in trimmed and len(trimmed) < 200:
                    logger.info(
                        "[research] Claude web search returned low-signal summary; ignoring"
                    )
                    return None
                logger.info("[research] Claude web search complete: %s chars", len(result))
                return result
            else:
                logger.info("[research] Claude web search returned no results")
                return None

        except asyncio.TimeoutError:
            logger.warning(
                "[research] Claude web search timed out after %ss", CLAUDE_SEARCH_TIMEOUT
            )
            return None
        except ImportError:
            logger.debug("[research] research_phase module not available")
            return None
        except (ConnectionError, OSError) as e:
            logger.warning("[research] Claude web search network error: %s", e)
            return None
        except (ValueError, RuntimeError) as e:
            logger.warning("[research] Claude web search failed: %s", e)
            return None
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("[research] Unexpected error in Claude web search: %s", e)
            return None

    async def gather_evidence_context(
        self,
        task: str,
        evidence_store_callback: Callable[..., Any] | None = None,
        prompt_builder: Any | None = None,
    ) -> tuple[str | None, Any | None]:
        """
        Gather evidence from web, GitHub, and local docs connectors.

        Uses EvidenceCollector with available connectors:
        - WebConnector: DuckDuckGo search (if duckduckgo_search installed)
        - GitHubConnector: Code/docs from GitHub (if GITHUB_TOKEN set)
        - LocalDocsConnector: Local documentation files

        Args:
            task: The debate topic/task description.
            evidence_store_callback: Optional callback to store evidence.
            prompt_builder: Optional PromptBuilder to receive evidence pack.

        Returns:
            Tuple of (formatted context string, evidence pack) or (None, None).
        """
        try:
            from aragora.evidence.collector import EvidenceCollector

            collector = EvidenceCollector()
            enabled_connectors = []

            # Add web connector if available (None without duckduckgo_search)
            try:
                web = create_connector("web_search")
                if web is not None:
                    collector.add_connector("web", web)
                    enabled_connectors.append("web")
            except _CONNECTOR_UNAVAILABLE:
                logger.debug("WebConnector not available: duckduckgo_search not installed")

            # Add GitHub connector if available
            try:
                if os.environ.get("GITHUB_TOKEN"):
                    collector.add_connector("github", create_connector("github"))
                    enabled_connectors.append("github")
            except _CONNECTOR_UNAVAILABLE:
                logger.debug("GitHubConnector not available")

            # Add local docs connector
            try:
                collector.add_connector(
                    "local_docs",
                    create_connector(
                        "local_docs", root_path=str(self._project_root / "docs"), file_types="docs"
                    ),
                )
                enabled_connectors.append("local_docs")
            except _CONNECTOR_UNAVAILABLE:
                logger.debug("LocalDocsConnector not available")

            if not enabled_connectors:
                return None, None

            evidence_pack = await collector.collect_evidence(
                task, enabled_connectors=enabled_connectors
            )

            if evidence_pack.snippets:
                # Update prompt builder if available
                if prompt_builder:
                    prompt_builder.set_evidence_pack(evidence_pack)

                # Store evidence via callback if provided
                if evidence_store_callback and callable(evidence_store_callback):
                    evidence_store_callback(evidence_pack.snippets, task)

                return f"## EVIDENCE CONTEXT\n{evidence_pack.to_context_string()}", evidence_pack

        except ImportError as e:
            logger.debug("Evidence collector not available: %s", e)
        except (ConnectionError, OSError) as e:
            logger.warning("Evidence collection network/IO error: %s", e)
        except (ValueError, RuntimeError) as e:
            logger.warning("Evidence collection failed: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error in evidence collection: %s", e)

        return None, None

    async def gather_trending_context(
        self,
        prompt_builder: Any | None = None,
    ) -> tuple[str | None, list[Any]]:
        """
        Gather pulse/trending context from social platforms.

        Uses PulseManager with available ingestors:
        - Twitter
        - Hacker News
        - Reddit
        - GitHub Trending
        - Google Trends

        Args:
            prompt_builder: Optional PromptBuilder to receive trending topics.

        Returns:
            Tuple of (formatted context string, list of TrendingTopic objects).
        """
        if not self._enable_trending_context:
            logger.debug("[pulse] Trending context disabled")
            return None, []
        try:
            from aragora.pulse.ingestor import (
                GitHubTrendingIngestor,
                GoogleTrendsIngestor,
                HackerNewsIngestor,
                PulseManager,
                RedditIngestor,
            )

            manager = PulseManager()
            # Free, no-auth sources for real trending data:
            manager.add_ingestor("google", GoogleTrendsIngestor())
            manager.add_ingestor("hackernews", HackerNewsIngestor())
            manager.add_ingestor("reddit", RedditIngestor())
            manager.add_ingestor("github", GitHubTrendingIngestor())

            topics = await manager.get_trending_topics(limit_per_platform=3)

            if topics:
                topics_list = list(topics)

                # Pass to prompt builder if available
                if prompt_builder:
                    prompt_builder.set_trending_topics(topics_list)
                    logger.debug(
                        "[pulse] Injected %s trending topics into PromptBuilder",
                        len(topics_list),
                    )

                trending_context = (
                    "## TRENDING CONTEXT\nCurrent trending topics that may be relevant:\n"
                )
                for t in topics[:5]:
                    trending_context += (
                        f"- {t.topic} ({t.platform}, {t.volume:,} engagement, {t.category})\n"
                    )
                return trending_context, topics_list

        except ImportError as e:
            logger.debug("Pulse module not available: %s", e)
        except (ConnectionError, OSError) as e:
            logger.debug("Pulse context network error: %s", e)
        except (ValueError, RuntimeError) as e:
            logger.debug("Pulse context unavailable: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error getting pulse context: %s", e)

        return None, []

    async def gather_knowledge_mound_context(self, task: str) -> str | None:
        """
        Query Knowledge Mound for relevant facts and evidence.

        Auto-grounds debates with institutional knowledge from:
        - Previous debate outcomes and consensus
        - Extracted facts from documents
        - Evidence snippets with provenance
        - Cross-debate patterns and insights

        Args:
            task: The debate topic/task description.

        Returns:
            Formatted knowledge context, or None if unavailable.
        """
        if not self._knowledge_mound:
            return None

        try:
            # Query knowledge mound for relevant items
            result = await self._knowledge_mound.query(
                query=task,
                sources=("all",),  # Query all knowledge sources
                limit=10,
            )

            if not result.items:
                logger.debug("[knowledge] No relevant knowledge found for task")
                return None

            # Format knowledge context
            context_parts = [
                "## KNOWLEDGE MOUND CONTEXT",
                "Relevant institutional knowledge from previous debates and analyses:",
                "",
            ]
            confidence_map = {
                "verified": 0.95,
                "high": 0.8,
                "medium": 0.6,
                "low": 0.3,
                "unverified": 0.2,
            }

            def _confidence_to_float(value: Any) -> float:
                if isinstance(value, (int, float)):
                    return float(value)
                if hasattr(value, "value"):
                    value = value.value
                if isinstance(value, str):
                    return confidence_map.get(value.lower(), 0.5)
                return 0.5

            # Group by source type for better organization
            facts = []
            evidence = []
            insights = []

            for item in result.items:
                source: Any = getattr(item, "source", None)
                source_name = (
                    source.value
                    if hasattr(source, "value")
                    else str(source)
                    if source
                    else "unknown"
                )
                content = item.content[:500] if item.content else ""
                confidence = _confidence_to_float(getattr(item, "confidence", 0.5))

                if source_name in ("fact", "fact_store"):
                    facts.append((content, confidence))
                elif source_name in ("evidence", "evidence_store"):
                    evidence.append((content, confidence))
                else:
                    insights.append((content, confidence, source_name))

            # Format facts
            if facts:
                context_parts.append("### Verified Facts")
                for content, conf in facts[:3]:
                    conf_label = "HIGH" if conf > 0.7 else "MEDIUM" if conf > 0.4 else "LOW"
                    context_parts.append(f"- [{conf_label}] {content}")
                context_parts.append("")

            # Format evidence
            if evidence:
                context_parts.append("### Supporting Evidence")
                for content, conf in evidence[:3]:
                    context_parts.append(f"- {content}")
                context_parts.append("")

            # Format insights
            if insights:
                context_parts.append("### Related Insights")
                for content, conf, source in insights[:4]:
                    context_parts.append(f"- ({source}) {content}")
                context_parts.append("")

            if len(context_parts) <= 3:
                # Only header, no actual content
                return None

            logger.info(
                "[knowledge] Injected %s knowledge items "
                "(%s facts, %s evidence, %s insights) "
                "in %sms",
                len(result.items),
                len(facts),
                len(evidence),
                len(insights),
                int(result.execution_time_ms),
            )

            return "\n".join(context_parts)

        except (ConnectionError, OSError) as e:
            logger.warning("[knowledge] Knowledge Mound query failed (IO error): %s", e)
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.warning("[knowledge] Knowledge Mound query failed: %s", e)
            return None
        except (RuntimeError, TypeError) as e:
            logger.warning("[knowledge] Unexpected error in Knowledge Mound query: %s", e)
            return None

    async def gather_threat_intel_context(self, task: str) -> str | None:
        """
        Gather threat intelligence context for security-related topics.

        When the debate topic involves security (vulnerabilities, CVEs, attacks, etc.),
        this method enriches the context with relevant threat intelligence:
        - CVE vulnerability details
        - IP/domain/URL reputation
        - File hash malware analysis
        - Attack patterns and mitigations

        Args:
            task: The debate topic/task description.

        Returns:
            Formatted threat intelligence context, or None if not applicable.
        """
        if not self._threat_intel_enrichment:
            return None

        try:
            # Check if the topic is security-related first (fast, local check)
            if not self._threat_intel_enrichment.is_security_topic(task):
                logger.debug("[threat_intel] Task is not security-related, skipping enrichment")
                return None

            # Enrich with threat intelligence
            context = await self._threat_intel_enrichment.enrich_context(
                topic=task,
                existing_context="",
            )

            if context:
                formatted = self._threat_intel_enrichment.format_for_debate(context)
                indicator_count = len(context.indicators)
                cve_count = len(context.relevant_cves)
                logger.info(
                    "[threat_intel] Enriched security context with %s indicators and %s CVEs",
                    indicator_count,
                    cve_count,
                )
                return formatted

            logger.debug("[threat_intel] No enrichment data available for topic")
            return None

        except (ConnectionError, OSError) as e:
            logger.warning("[threat_intel] Enrichment network error: %s", e)
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.warning("[threat_intel] Enrichment failed: %s", e)
            return None
        except (RuntimeError, TypeError) as e:
            logger.warning("[threat_intel] Unexpected error in enrichment: %s", e)
            return None

    async def gather_belief_crux_context(
        self,
        task: str,
        messages: list | None = None,
        top_k_cruxes: int = 3,
    ) -> str | None:
        """Gather crux claims from belief network analysis.

        Analyzes debate messages (if provided) or queries historical debates
        for crux claims that can inform the current debate.

        Args:
            task: The debate task description.
            messages: Optional list of debate messages to analyze.
            top_k_cruxes: Number of top crux claims to extract.

        Returns:
            Formatted crux context string, or None if not available.
        """
        if not self._belief_analyzer:
            return None

        try:
            # If messages provided, analyze them for cruxes
            if messages:
                result = self._belief_analyzer.analyze_messages(
                    messages,
                    top_k_cruxes=top_k_cruxes,
                )

                if result.analysis_error:
                    logger.debug("[belief] Crux analysis error: %s", result.analysis_error)
                    return None

                if not result.cruxes:
                    return None

                context_parts = [
                    "## Key Crux Points (Belief Network Analysis)",
                    "",
                    "The following crux claims represent pivotal points of disagreement",
                    "that may determine the outcome of this debate:",
                    "",
                ]

                for i, crux in enumerate(result.cruxes[:top_k_cruxes], 1):
                    statement = crux.get("statement", crux.get("claim", ""))
                    confidence = crux.get("confidence", 0.5)
                    entropy = crux.get("entropy", 0.5)

                    conf_label = (
                        "HIGH" if confidence > 0.7 else "MEDIUM" if confidence > 0.4 else "LOW"
                    )
                    contested = " (CONTESTED)" if entropy > 0.8 else ""
                    context_parts.append(f"{i}. [{conf_label}{contested}] {statement}")

                if result.evidence_suggestions:
                    context_parts.extend(
                        [
                            "",
                            "### Evidence Needed",
                            "The following evidence would help resolve these cruxes:",
                        ]
                    )
                    for suggestion in result.evidence_suggestions[:3]:
                        context_parts.append(f"- {suggestion}")

                logger.info(
                    "[belief] Extracted %s cruxes from %s messages",
                    len(result.cruxes),
                    len(messages),
                )

                return "\n".join(context_parts)

            # No messages - could query historical debates for similar topic cruxes
            return None

        except (ValueError, AttributeError) as e:
            logger.debug("[belief] Crux gathering failed: %s", e)
            return None
        except (RuntimeError, TypeError, KeyError) as e:
            logger.warning("[belief] Unexpected error gathering cruxes: %s", e)
            return None

    async def gather_culture_patterns_context(
        self,
        task: str,
        workspace_id: str | None = None,
    ) -> str | None:
        """
        Gather learned culture patterns from Knowledge Mound.

        Retrieves organizational patterns learned from previous debates:
        - Successful argumentation strategies
        - Consensus-building patterns
        - Domain-specific debate styles
        - Protocol effectiveness patterns

        Args:
            task: The debate task description.
            workspace_id: Optional workspace filter.

        Returns:
            Formatted culture patterns context, or None if unavailable.
        """
        try:
            # Use the mound's culture context API if available
            if self._knowledge_mound and hasattr(self._knowledge_mound, "get_culture_context"):
                ws_id = workspace_id or self._knowledge_workspace_id or "default"
                context = await self._knowledge_mound.get_culture_context(
                    org_id=ws_id,
                    task=task,
                    max_documents=5,
                )
                if context:
                    logger.info("[culture] Injected culture context from mound")
                    return context
                logger.debug("[culture] No relevant culture context from mound")
                return None

            # Fallback: use CultureAccumulator with mound reference
            if not self._knowledge_mound:
                logger.debug("[culture] Knowledge mound not available for culture patterns")
                return None

            from aragora.knowledge.mound.culture.accumulator import CultureAccumulator

            # Get or create accumulator from mound
            if (
                hasattr(self._knowledge_mound, "_culture_accumulator")
                and self._knowledge_mound._culture_accumulator
            ):
                accumulator = self._knowledge_mound._culture_accumulator
            else:
                accumulator = CultureAccumulator(mound=self._knowledge_mound)

            # Query for patterns relevant to this workspace
            ws_id = workspace_id or self._knowledge_workspace_id or "default"
            patterns = accumulator.get_patterns(
                workspace_id=ws_id,
                min_confidence=0.3,
            )

            if not patterns:
                logger.debug("[culture] No relevant culture patterns found")
                return None

            context_parts = [
                "## ORGANIZATIONAL CULTURE PATTERNS",
                "Learned patterns from previous debates in this workspace:",
                "",
            ]

            for pattern in patterns[:5]:  # Limit to top 5
                pattern_type = getattr(pattern, "pattern_type", None) or "general"
                description = getattr(pattern, "description", "") or ""
                confidence = getattr(pattern, "confidence", 0.5)
                observations = getattr(pattern, "observations", 0)

                if not description:
                    continue

                # Convert enum to string if needed
                if hasattr(pattern_type, "value"):
                    pattern_type = pattern_type.value

                conf_label = (
                    "Strong" if confidence > 0.7 else "Moderate" if confidence > 0.4 else "Emerging"
                )
                context_parts.append(
                    f"- **{str(pattern_type).title()}** [{conf_label}, {observations} uses]: {description}"
                )

            if len(context_parts) <= 3:
                return None

            logger.info("[culture] Injected %s culture patterns", min(len(patterns), 5))
            return "\n".join(context_parts)

        except ImportError:
            logger.debug("[culture] CultureAccumulator not available")
            return None
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("[culture] Failed to gather culture patterns: %s", e)
            return None

    # Timeout wrapper methods

    async def gather_evidence_with_timeout(
        self,
        task: str,
        evidence_store_callback: Callable[..., Any] | None = None,
        prompt_builder: Any | None = None,
    ) -> tuple[str | None, Any | None]:
        """Gather evidence with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_evidence_context(task, evidence_store_callback, prompt_builder),
                timeout=EVIDENCE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Evidence collection timed out after %ss", EVIDENCE_TIMEOUT)
            return None, None

    async def gather_trending_with_timeout(
        self,
        prompt_builder: Any | None = None,
    ) -> tuple[str | None, list[Any]]:
        """Gather trending context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_trending_context(prompt_builder),
                timeout=TRENDING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Trending context timed out after %ss", TRENDING_TIMEOUT)
            return None, []

    async def gather_knowledge_mound_with_timeout(self, task: str) -> str | None:
        """Gather knowledge mound context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_knowledge_mound_context(task),
                timeout=KNOWLEDGE_MOUND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Knowledge mound context timed out after %ss", KNOWLEDGE_MOUND_TIMEOUT)
            return None

    async def gather_threat_intel_with_timeout(self, task: str) -> str | None:
        """Gather threat intelligence context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_threat_intel_context(task),
                timeout=THREAT_INTEL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Threat intel context timed out after %ss", THREAT_INTEL_TIMEOUT)
            return None

    async def gather_belief_with_timeout(
        self,
        task: str,
        messages: list | None = None,
        top_k_cruxes: int = 3,
    ) -> str | None:
        """Gather belief crux context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_belief_crux_context(task, messages, top_k_cruxes),
                timeout=BELIEF_CRUX_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[belief] Crux gathering timed out after %ss", BELIEF_CRUX_TIMEOUT)
            return None

    async def gather_culture_with_timeout(
        self,
        task: str,
        workspace_id: str | None = None,
    ) -> str | None:
        """Gather culture patterns context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_culture_patterns_context(task, workspace_id),
                timeout=5.0,  # Culture patterns should be fast (local query)
            )
        except asyncio.TimeoutError:
            logger.warning("[culture] Culture pattern gathering timed out")
            return None


# Re-export timeout constants for backwards compatibility
__all__ = [
    "SourceFetcher",
    "CLAUDE_SEARCH_TIMEOUT",
    "EVIDENCE_TIMEOUT",
    "TRENDING_TIMEOUT",
    "KNOWLEDGE_MOUND_TIMEOUT",
    "BELIEF_CRUX_TIMEOUT",
    "THREAT_INTEL_TIMEOUT",
]
