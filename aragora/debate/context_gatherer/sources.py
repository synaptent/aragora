"""
Context source gathering mixin for ContextGatherer.

Contains methods for gathering context from various sources:
- Claude web search
- Evidence connectors
- Trending/Pulse topics
- Knowledge Mound
- Threat intelligence
- Belief crux analysis
- Culture patterns
"""

import asyncio
import logging
from typing import Any
from collections.abc import Callable

from .constants import (
    CLAUDE_SEARCH_TIMEOUT,
    EVIDENCE_TIMEOUT,
    TRENDING_TIMEOUT,
    KNOWLEDGE_MOUND_TIMEOUT,
    THREAT_INTEL_TIMEOUT,
    BELIEF_CRUX_TIMEOUT,
    DOCUMENT_STORE_TIMEOUT,
    EVIDENCE_STORE_TIMEOUT,
    MAX_EVIDENCE_CACHE_SIZE,
    MAX_TRENDING_CACHE_SIZE,
)

logger = logging.getLogger(__name__)


class SourceGatheringMixin:
    """Mixin providing context source gathering methods."""

    # Type hints for attributes defined in main class
    _enable_trending_context: bool
    _knowledge_mound: Any
    _knowledge_workspace_id: str
    _enable_knowledge_grounding: bool
    _enable_threat_intel: bool
    _threat_intel_enrichment: Any
    _enable_belief_guidance: bool
    _belief_analyzer: Any
    _evidence_store_callback: Callable[..., Any] | None
    _prompt_builder: Any
    _project_root: Any
    _research_evidence_pack: dict[str, Any]
    _trending_topics_cache: list[Any]
    _document_store: Any | None
    _evidence_store: Any | None
    _document_ids: list[str] | None
    _document_org_id: str | None
    _enable_document_context: bool
    _enable_evidence_store_context: bool
    _max_document_context_items: int
    _max_evidence_context_items: int
    _auth_context: Any

    # Method from CompressionMixin
    async def _compress_with_rlm(
        self, content: str, source_type: str = "documentation", max_chars: int = 3000
    ) -> str:
        """
        Delegate compression to CompressionMixin implementation.

        This method intentionally forwards to the next class in MRO so
        SourceGatheringMixin can call `_compress_with_rlm` without shadowing
        CompressionMixin's concrete logic.
        """
        return await super()._compress_with_rlm(  # type: ignore[misc]
            content=content,
            source_type=source_type,
            max_chars=max_chars,
        )

    def _get_task_hash(self, task: str) -> str:
        """Generate a cache key from task to prevent cache leaks between debates."""
        raise NotImplementedError("Must be implemented by main class")

    def _enforce_cache_limit(self, cache: dict, max_size: int) -> None:
        """Enforce maximum cache size using FIFO eviction."""
        raise NotImplementedError("Must be implemented by main class")

    async def _gather_claude_web_search(self, task: str) -> str | None:
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

    async def _gather_evidence_with_timeout(self, task: str) -> str | None:
        """Gather evidence with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_evidence_context(task), timeout=EVIDENCE_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Evidence collection timed out after %ss", EVIDENCE_TIMEOUT)
            return None

    async def _gather_trending_with_timeout(self) -> str | None:
        """Gather trending context with timeout protection."""
        try:
            return await asyncio.wait_for(self.gather_trending_context(), timeout=TRENDING_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Trending context timed out after %ss", TRENDING_TIMEOUT)
            return None

    async def _gather_knowledge_mound_with_timeout(self, task: str) -> str | None:
        """Gather knowledge mound context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_knowledge_mound_context(task), timeout=KNOWLEDGE_MOUND_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Knowledge mound context timed out after %ss", KNOWLEDGE_MOUND_TIMEOUT)
            return None

    async def _gather_threat_intel_with_timeout(self, task: str) -> str | None:
        """Gather threat intelligence context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_threat_intel_context(task), timeout=THREAT_INTEL_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Threat intel context timed out after %ss", THREAT_INTEL_TIMEOUT)
            return None

    async def _gather_belief_with_timeout(self, task: str) -> str | None:
        """Gather belief crux context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_belief_crux_context(task),
                timeout=BELIEF_CRUX_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[belief] Crux gathering timed out after %ss", BELIEF_CRUX_TIMEOUT)
            return None

    async def _gather_culture_with_timeout(self, task: str) -> str | None:
        """Gather culture patterns context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_culture_patterns_context(task),
                timeout=5.0,  # Culture patterns should be fast (local query)
            )
        except asyncio.TimeoutError:
            logger.warning("[culture] Culture pattern gathering timed out")
            return None

    async def _gather_document_store_with_timeout(self, task: str) -> str | None:
        """Gather uploaded document context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_document_store_context(task),
                timeout=DOCUMENT_STORE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[documents] Document store context timed out after %ss",
                DOCUMENT_STORE_TIMEOUT,
            )
            return None

    async def _gather_evidence_store_with_timeout(self, task: str) -> str | None:
        """Gather evidence store context with timeout protection."""
        try:
            return await asyncio.wait_for(
                self.gather_evidence_store_context(task),
                timeout=EVIDENCE_STORE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[evidence] Evidence store context timed out after %ss",
                EVIDENCE_STORE_TIMEOUT,
            )
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
        if not self._enable_threat_intel or not self._threat_intel_enrichment:
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

    async def gather_evidence_context(self, task: str) -> str | None:
        """
        Gather evidence from web, GitHub, and local docs connectors.

        Uses EvidenceCollector with available connectors:
        - WebConnector: DuckDuckGo search (if duckduckgo_search installed)
        - GitHubConnector: Code/docs from GitHub (if GITHUB_TOKEN set)
        - LocalDocsConnector: Local documentation files

        Args:
            task: The debate topic/task description.

        Returns:
            Formatted evidence context, or None if unavailable.
        """
        try:
            import os
            from aragora.evidence.collector import EvidenceCollector

            collector = EvidenceCollector()
            enabled_connectors = []

            # Add web connector if available
            try:
                from aragora.connectors.web import DDGS_AVAILABLE, WebConnector

                if DDGS_AVAILABLE:
                    collector.add_connector("web", WebConnector())
                    enabled_connectors.append("web")
            except ImportError:
                logger.debug("WebConnector not available: duckduckgo_search not installed")

            # Add GitHub connector if available
            try:
                from aragora.connectors.github import GitHubConnector

                if os.environ.get("GITHUB_TOKEN"):
                    collector.add_connector("github", GitHubConnector())
                    enabled_connectors.append("github")
            except ImportError:
                logger.debug("GitHubConnector not available")

            # Add local docs connector
            try:
                from aragora.connectors.local_docs import LocalDocsConnector

                collector.add_connector(
                    "local_docs",
                    LocalDocsConnector(
                        root_path=str(self._project_root / "docs"), file_types="docs"
                    ),
                )
                enabled_connectors.append("local_docs")
            except ImportError:
                logger.debug("LocalDocsConnector not available")

            if not enabled_connectors:
                return None

            evidence_pack = await collector.collect_evidence(
                task, enabled_connectors=enabled_connectors
            )

            if evidence_pack.snippets:
                task_hash = self._get_task_hash(task)
                self._enforce_cache_limit(self._research_evidence_pack, MAX_EVIDENCE_CACHE_SIZE)
                self._research_evidence_pack[task_hash] = evidence_pack

                # Update prompt builder if available
                if self._prompt_builder:
                    self._prompt_builder.set_evidence_pack(evidence_pack)

                # Store evidence via callback if provided
                if self._evidence_store_callback and callable(self._evidence_store_callback):
                    self._evidence_store_callback(evidence_pack.snippets, task)

                return f"## EVIDENCE CONTEXT\n{evidence_pack.to_context_string()}"

        except ImportError as e:
            logger.debug("Evidence collector not available: %s", e)
        except (ConnectionError, OSError) as e:
            logger.warning("Evidence collection network/IO error: %s", e)
        except (ValueError, RuntimeError) as e:
            logger.warning("Evidence collection failed: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error in evidence collection: %s", e)

        return None

    async def gather_document_store_context(self, task: str) -> str | None:
        """Gather context from the debate org's uploaded documents (DocumentStore)."""
        if not self._enable_document_context or not self._document_store:
            return None
        org_id = getattr(self, "_document_org_id", None)
        if not isinstance(org_id, str) or not org_id:
            return None

        try:
            docs = []
            if self._document_ids:
                for doc_id in self._document_ids[: self._max_document_context_items]:
                    doc = self._document_store.get(doc_id)
                    if doc and getattr(doc, "org_id", None) == org_id:
                        docs.append(doc)
            else:
                items = self._document_store.list_for_org(org_id) or []
                if not items:
                    return None

                import re

                tokens = [t for t in re.split(r"\W+", task.lower()) if t and len(t) > 3]
                for item in items:
                    haystack = f"{item.get('filename', '')} {item.get('preview', '')}".lower()
                    score = sum(1 for t in tokens if t in haystack)
                    item["score"] = score
                items.sort(key=lambda x: x.get("score", 0), reverse=True)

                selected = items[: self._max_document_context_items]
                for item in selected:
                    doc = self._document_store.get(item.get("id", ""))
                    if doc and getattr(doc, "org_id", None) == org_id:
                        docs.append(doc)

            if not docs:
                return None

            context_parts = [
                "## DOCUMENT CONTEXT",
                "Relevant uploaded documents:",
                "",
            ]
            for doc in docs:
                filename = getattr(doc, "filename", "document")
                text = getattr(doc, "text", "") or ""
                snippet = await self._compress_with_rlm(
                    text,
                    source_type="document",
                    max_chars=2000,
                )
                context_parts.append(f"### {filename}")
                context_parts.append(snippet)
                context_parts.append("")

            return "\n".join(context_parts).strip()

        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("[documents] Failed to gather document store context: %s", e)
            return None

    async def gather_evidence_store_context(self, task: str) -> str | None:
        """Gather context from stored evidence snippets."""
        if not self._enable_evidence_store_context or not self._evidence_store:
            return None

        try:
            evidence = self._evidence_store.search_evidence(
                task, limit=self._max_evidence_context_items
            )
            if not evidence:
                return None

            context_parts = [
                "## EVIDENCE STORE CONTEXT",
                "Relevant evidence snippets from prior work:",
                "",
            ]
            for item in evidence[: self._max_evidence_context_items]:
                snippet = (item.get("snippet") or "").strip()
                if not snippet:
                    continue
                source = item.get("source", "unknown")
                reliability = item.get("reliability_score", 0.0)
                url = item.get("url")
                prefix = f"- [{source} | {reliability:.0%}]"
                line = f"{prefix} {snippet[:240]}"
                if url:
                    line += f" ({url})"
                context_parts.append(line)

            if len(context_parts) <= 3:
                return None

            return "\n".join(context_parts)

        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("[evidence] Failed to gather evidence store context: %s", e)
            return None

    async def gather_trending_context(self) -> str | None:
        """
        Gather pulse/trending context from social platforms.

        Uses PulseManager with available ingestors:
        - Twitter
        - Hacker News
        - Reddit
        - GitHub Trending
        - Google Trends

        Also caches TrendingTopic objects for prompt_builder injection.

        Returns:
            Formatted trending topics context, or None if unavailable.
        """
        if not self._enable_trending_context:
            logger.debug("[pulse] Trending context disabled")
            return None
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
            manager.add_ingestor("google", GoogleTrendsIngestor())  # Real Google Trends
            manager.add_ingestor("hackernews", HackerNewsIngestor())  # Real HN front page
            manager.add_ingestor("reddit", RedditIngestor())  # Real Reddit hot posts
            manager.add_ingestor("github", GitHubTrendingIngestor())  # Real GitHub trending

            topics = await manager.get_trending_topics(limit_per_platform=3)

            if topics:
                # Cache TrendingTopic objects for PromptBuilder injection
                # Limit cache size to prevent unbounded memory growth
                self._trending_topics_cache = list(topics)[:MAX_TRENDING_CACHE_SIZE]

                # Pass to prompt builder if available
                if self._prompt_builder:
                    self._prompt_builder.set_trending_topics(self._trending_topics_cache)
                    logger.debug(
                        "[pulse] Injected %s trending topics into PromptBuilder",
                        len(self._trending_topics_cache),
                    )

                trending_context = (
                    "## TRENDING CONTEXT\nCurrent trending topics that may be relevant:\n"
                )
                for t in topics[:5]:
                    trending_context += (
                        f"- {t.topic} ({t.platform}, {t.volume:,} engagement, {t.category})\n"
                    )
                return trending_context

        except ImportError as e:
            logger.debug("Pulse module not available: %s", e)
        except (ConnectionError, OSError) as e:
            logger.debug("Pulse context network error: %s", e)
        except (ValueError, RuntimeError) as e:
            logger.debug("Pulse context unavailable: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error getting pulse context: %s", e)

        return None

    def get_trending_topics(self) -> list[Any]:
        """Get cached trending topics.

        Returns:
            List of TrendingTopic objects from the last gather_trending_context call.
        """
        return self._trending_topics_cache

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
        if not self._enable_knowledge_grounding or not self._knowledge_mound:
            return None

        try:
            # Query knowledge mound for relevant items (RBAC-aware when possible)
            if getattr(self, "_auth_context", None) and hasattr(
                self._knowledge_mound, "query_with_visibility"
            ):
                actor_id = getattr(self._auth_context, "user_id", "") or ""
                workspace_id = getattr(self._auth_context, "workspace_id", "") or ""
                org_id = getattr(self._auth_context, "org_id", None)
                if actor_id and workspace_id:
                    result = await self._knowledge_mound.query_with_visibility(
                        task,
                        actor_id=actor_id,
                        actor_workspace_id=workspace_id,
                        actor_org_id=org_id,
                        limit=10,
                    )
                else:
                    result = await self._knowledge_mound.query(
                        query=task,
                        sources=("all",),  # Query all knowledge sources
                        limit=10,
                    )
            else:
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
        except Exception as e:  # noqa: BLE001 - KM adapters may raise driver-specific errors
            logger.warning("[knowledge] Knowledge Mound query error: %s", e)
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
        if not self._enable_belief_guidance or not self._belief_analyzer:
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

            # Get or create accumulator from mound (or mound's internal accumulator)
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

    async def refresh_evidence_for_round(
        self,
        combined_text: str,
        evidence_collector: Any,
        task: str,
        evidence_store_callback: Callable[..., Any] | None = None,
    ) -> tuple[int, Any]:
        """Refresh evidence based on claims made during a debate round.

        Called after the critique phase to gather fresh evidence for claims
        that emerged in proposals and critiques.

        Args:
            combined_text: Combined text from proposals and critiques
            evidence_collector: EvidenceCollector instance
            task: The debate task
            evidence_store_callback: Optional callback to store evidence in memory

        Returns:
            Tuple of:
            - Number of new evidence snippets added
            - Updated evidence pack (or None)
        """
        if not evidence_collector:
            return 0, None

        try:
            # Extract claims from the combined text
            claims = evidence_collector.extract_claims_from_text(combined_text)
            if not claims:
                return 0, None

            logger.debug("evidence_refresh extracting from %s claims", len(claims))

            # Collect evidence for the claims
            evidence_pack = await evidence_collector.collect_for_claims(claims)

            if not evidence_pack.snippets:
                return 0, None

            # Merge with existing evidence pack, avoiding duplicates
            task_hash = self._get_task_hash(task)
            existing_pack = self._research_evidence_pack.get(task_hash)
            if existing_pack:
                existing_ids = {s.id for s in existing_pack.snippets}
                new_snippets = [s for s in evidence_pack.snippets if s.id not in existing_ids]
                existing_pack.snippets.extend(new_snippets)
                existing_pack.total_searched += evidence_pack.total_searched
            else:
                self._enforce_cache_limit(self._research_evidence_pack, MAX_EVIDENCE_CACHE_SIZE)
                self._research_evidence_pack[task_hash] = evidence_pack

            # Store in memory for future debates
            if (
                evidence_pack.snippets
                and evidence_store_callback
                and callable(evidence_store_callback)
            ):
                evidence_store_callback(evidence_pack.snippets, task)

            return len(evidence_pack.snippets), self._research_evidence_pack.get(task_hash)

        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Evidence refresh failed: %s", e)
            return 0, None
