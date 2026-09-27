"""
Main ContextGatherer class that composes functionality from mixins.

This module contains the primary ContextGatherer class that orchestrates
context gathering from multiple sources for debate grounding.
"""

import asyncio
import functools
import hashlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from collections.abc import Callable

from .constants import (
    HAS_RLM,
    HAS_OFFICIAL_RLM,
    HAS_KNOWLEDGE_MOUND,
    HAS_THREAT_INTEL,
    THREAT_INTEL_ENABLED,
    KnowledgeMound,
    ThreatIntelEnrichment,
    get_rlm,
    get_compressor,
    CONTEXT_GATHER_TIMEOUT,
    CODEBASE_CONTEXT_TIMEOUT,
    MAX_CONTEXT_CACHE_SIZE,
    is_trending_disabled,
    ARAGORA_KEYWORDS,
    get_use_codebase,
)
from .sources import SourceGatheringMixin
from .compression import CompressionMixin
from .memory import MemoryMixin

if TYPE_CHECKING:
    from aragora.rlm.compressor import HierarchicalCompressor

logger = logging.getLogger(__name__)


def _package_override(name: str, default: Any) -> Any:
    """Resolve package-level monkeypatch overrides used by tests."""
    package_mod = sys.modules.get("aragora.debate.context_gatherer")
    if package_mod is not None and hasattr(package_mod, name):
        return getattr(package_mod, name)
    return default


class ContextGatherer(SourceGatheringMixin, CompressionMixin, MemoryMixin):
    """
    Gathers context from multiple sources for debate grounding.

    Sources include:
    - Aragora project documentation (for self-referential debates)
    - Web search via EvidenceCollector
    - GitHub repositories
    - Local documentation
    - Pulse/trending topics from social platforms

    IMPORTANT: ContextGatherer should be instantiated ONCE PER DEBATE.
    It maintains internal caches keyed by task hash to prevent context leakage.
    Do not reuse a single ContextGatherer instance across multiple debates.

    Usage:
        # Create per-debate (done automatically by Arena.init_phases())
        gatherer = ContextGatherer(evidence_store_callback=store_evidence)
        context = await gatherer.gather_all(task="Discuss AI safety")

        # Clear cache if reusing (not recommended)
        gatherer.clear_cache()
    """

    def __init__(
        self,
        evidence_store_callback: Callable[..., Any] | None = None,
        prompt_builder: Any | None = None,
        project_root: Path | None = None,
        enable_rlm_compression: bool = True,
        rlm_compressor: Optional["HierarchicalCompressor"] = None,
        rlm_compression_threshold: int = 3000,  # Chars above which to use RLM
        enable_knowledge_grounding: bool = True,
        knowledge_mound: Any | None = None,
        knowledge_workspace_id: str | None = None,
        enable_belief_guidance: bool = True,
        enable_threat_intel_enrichment: bool = True,
        threat_intel_enrichment: Any | None = None,
        enable_trending_context: bool = True,
        document_store: Any | None = None,
        evidence_store: Any | None = None,
        document_ids: list[str] | None = None,
        enable_document_context: bool = True,
        enable_evidence_store_context: bool = True,
        max_document_context_items: int = 5,
        max_evidence_context_items: int = 5,
        auth_context: Any | None = None,
        skip_empty_sidecars: bool = False,
    ):
        """
        Initialize the context gatherer.

        Args:
            evidence_store_callback: Optional callback to store evidence snippets.
                                    Signature: (snippets: list, task: str) -> None
            prompt_builder: Optional PromptBuilder to receive evidence pack.
            project_root: Optional project root path for documentation lookup.
                         Defaults to detecting from this file's location.
            enable_rlm_compression: Whether to use RLM for large document compression.
            rlm_compressor: Optional pre-configured HierarchicalCompressor.
            rlm_compression_threshold: Char count above which to apply RLM compression.
            enable_knowledge_grounding: Whether to auto-query Knowledge Mound for context.
            knowledge_mound: Optional pre-configured KnowledgeMound instance.
            knowledge_workspace_id: Workspace ID for knowledge queries (default: 'debate').
            enable_belief_guidance: Whether to inject historical cruxes from similar debates.
            enable_threat_intel_enrichment: Whether to enrich security topics with threat intel.
            threat_intel_enrichment: Optional pre-configured ThreatIntelEnrichment instance.
            enable_trending_context: Whether to gather Pulse trending context.
            document_store: Optional DocumentStore for uploaded document context.
            evidence_store: Optional EvidenceStore for stored evidence context.
            document_ids: Optional explicit document IDs to include.
            enable_document_context: Whether to include DocumentStore context.
            enable_evidence_store_context: Whether to include EvidenceStore context.
            max_document_context_items: Max documents to include.
            max_evidence_context_items: Max evidence snippets to include.
            skip_empty_sidecars: Skip optional research/KM sidecars for simple questions.
        """
        self._evidence_store_callback = evidence_store_callback
        self._prompt_builder = prompt_builder
        self._project_root = project_root or Path(__file__).parent.parent.parent.parent

        # Cache for evidence pack (keyed by task hash to prevent leaks between debates)
        self._research_evidence_pack: dict[str, Any] = {}

        # Cache for research context (keyed by task hash to prevent leaks between debates)
        self._research_context_cache: dict[str, str] = {}

        # Cache for continuum memory context (keyed by task hash to prevent leaks between debates)
        self._continuum_context_cache: dict[str, str] = {}

        # Cache for trending topics (TrendingTopic objects, not just formatted string)
        self._trending_topics_cache: list[Any] = []

        # Document/evidence stores (optional)
        self._document_store = document_store
        self._evidence_store = evidence_store
        self._document_ids = document_ids
        self._enable_document_context = enable_document_context
        self._enable_evidence_store_context = enable_evidence_store_context
        self._max_document_context_items = max_document_context_items
        self._max_evidence_context_items = max_evidence_context_items
        self._auth_context = auth_context
        self._skip_empty_sidecars = skip_empty_sidecars

        trending_disabled = is_trending_disabled()
        self._enable_trending_context = enable_trending_context and not trending_disabled
        if trending_disabled:
            logger.info(
                "[pulse] ContextGatherer: Trending context disabled via ARAGORA_DISABLE_TRENDING"
            )

        # RLM configuration - use factory for consistent initialization
        self._enable_rlm = enable_rlm_compression and HAS_RLM
        self._rlm_compressor = rlm_compressor
        self._aragora_rlm: Any | None = None
        self._rlm_threshold = rlm_compression_threshold

        if self._enable_rlm and get_rlm is not None:
            # Use factory to get AragoraRLM (routes to TRUE RLM when available)
            try:
                self._aragora_rlm = get_rlm()
                if HAS_OFFICIAL_RLM:
                    logger.info(
                        "[rlm] ContextGatherer: TRUE RLM enabled via factory "
                        "(REPL-based, model writes code to examine context)"
                    )
                else:
                    logger.info(
                        "[rlm] ContextGatherer: AragoraRLM enabled via factory "
                        "(will use compression fallback since official RLM not installed)"
                    )
            except ImportError as e:
                # Expected: RLM module not installed
                logger.debug("[rlm] RLM module not available: %s", e)
            except (RuntimeError, ValueError) as e:
                # Expected: RLM initialization issues
                logger.warning("[rlm] Failed to initialize RLM: %s", e)
            except (TypeError, AttributeError, OSError) as e:
                logger.warning("[rlm] Unexpected error getting RLM from factory: %s", e)

            # Fallback: get compressor from factory (compression-only)
            if not self._rlm_compressor and get_compressor is not None:
                try:
                    self._rlm_compressor = get_compressor()
                    logger.debug(
                        "[rlm] ContextGatherer: HierarchicalCompressor fallback via factory"
                    )
                except ImportError as e:
                    # Expected: compressor module not available
                    logger.debug("[rlm] Compressor module not available: %s", e)
                except (RuntimeError, ValueError) as e:
                    # Expected: compressor initialization issues
                    logger.warning("[rlm] Failed to initialize compressor: %s", e)
                except (TypeError, AttributeError, OSError) as e:
                    logger.warning("[rlm] Unexpected error getting compressor: %s", e)

        # Knowledge Mound configuration for auto-grounding
        self._enable_knowledge_grounding = enable_knowledge_grounding and HAS_KNOWLEDGE_MOUND
        self._knowledge_mound = knowledge_mound
        self._knowledge_workspace_id = knowledge_workspace_id or "debate"

        if self._enable_knowledge_grounding and KnowledgeMound is not None:
            if not self._knowledge_mound:
                try:
                    from aragora.knowledge.mound import get_knowledge_mound

                    self._knowledge_mound = get_knowledge_mound(
                        workspace_id=self._knowledge_workspace_id,
                        auto_initialize=True,
                    )
                    logger.info(
                        "[knowledge] ContextGatherer: Knowledge Mound enabled (workspace=%s)",
                        self._knowledge_workspace_id,
                    )
                except (RuntimeError, ValueError, OSError) as e:
                    # Expected: knowledge mound initialization issues
                    logger.warning("[knowledge] Failed to initialize Knowledge Mound: %s", e)
                    self._enable_knowledge_grounding = False
                except ImportError:
                    # Fallback: instantiate directly if singleton helper unavailable
                    try:
                        # KnowledgeMound is guaranteed non-None by the outer check
                        if KnowledgeMound is None:
                            raise RuntimeError(
                                "KnowledgeMound not available - knowledge module not loaded"
                            )
                        self._knowledge_mound = KnowledgeMound(
                            workspace_id=self._knowledge_workspace_id
                        )
                        logger.info(
                            "[knowledge] ContextGatherer: Knowledge Mound enabled (workspace=%s)",
                            self._knowledge_workspace_id,
                        )
                    except (RuntimeError, ValueError, OSError) as e:
                        logger.warning("[knowledge] Failed to initialize Knowledge Mound: %s", e)
                        self._enable_knowledge_grounding = False
                except (TypeError, AttributeError) as e:
                    logger.warning(
                        "[knowledge] Unexpected error initializing Knowledge Mound: %s", e
                    )
                    self._enable_knowledge_grounding = False
            else:
                logger.info("[knowledge] ContextGatherer: Using provided Knowledge Mound instance")

        # Belief guidance configuration for crux injection
        self._enable_belief_guidance = enable_belief_guidance
        self._belief_analyzer = None
        self._codebase_context_builder: Any = None
        if self._enable_belief_guidance:
            try:
                from aragora.debate.phases.belief_analysis import DebateBeliefAnalyzer

                self._belief_analyzer = DebateBeliefAnalyzer()
                logger.info("[belief] ContextGatherer: Belief guidance enabled for crux injection")
            except ImportError:
                logger.debug("[belief] Belief analyzer module not available")
                self._enable_belief_guidance = False
            except (RuntimeError, ValueError, TypeError) as e:
                logger.warning("[belief] Failed to initialize belief analyzer: %s", e)
                self._enable_belief_guidance = False

        # Threat intelligence enrichment for security topics
        self._enable_threat_intel = (
            enable_threat_intel_enrichment and HAS_THREAT_INTEL and THREAT_INTEL_ENABLED
        )
        self._threat_intel_enrichment = threat_intel_enrichment
        if self._enable_threat_intel and ThreatIntelEnrichment is not None:
            if not self._threat_intel_enrichment:
                try:
                    self._threat_intel_enrichment = ThreatIntelEnrichment()
                    logger.info(
                        "[threat_intel] ContextGatherer: Threat intel enrichment enabled "
                        "for security topics"
                    )
                except (RuntimeError, ValueError, OSError) as e:
                    logger.warning("[threat_intel] Failed to initialize enrichment: %s", e)
                    self._enable_threat_intel = False
                except (TypeError, AttributeError) as e:
                    logger.warning("[threat_intel] Unexpected error initializing enrichment: %s", e)
                    self._enable_threat_intel = False
            else:
                logger.info("[threat_intel] ContextGatherer: Using provided enrichment instance")

    @property
    def evidence_pack(self) -> Any | None:
        """Get the most recent cached evidence pack.

        For task-specific evidence, use get_evidence_pack(task) instead.
        """
        if not self._research_evidence_pack:
            return None
        # Return the most recently added pack for backward compatibility
        # In practice, callers should use get_evidence_pack(task) for isolation
        if self._research_evidence_pack:
            # Return last added pack (dict preserves insertion order in Python 3.7+)
            return list(self._research_evidence_pack.values())[-1]
        return None

    def get_evidence_pack(self, task: str) -> Any | None:
        """Get the cached evidence pack for a specific task."""
        task_hash = self._get_task_hash(task)
        return self._research_evidence_pack.get(task_hash)

    def set_prompt_builder(self, prompt_builder: Any) -> None:
        """Set or update the prompt builder reference."""
        self._prompt_builder = prompt_builder

    def _get_task_hash(self, task: str) -> str:
        """Generate a cache key from task to prevent cache leaks between debates."""
        return hashlib.sha256(task.encode()).hexdigest()[:16]

    def _enforce_cache_limit(self, cache: dict, max_size: int) -> None:
        """Enforce maximum cache size using FIFO eviction.

        When the cache exceeds max_size, removes the oldest entries
        (first-inserted) to bring it back under the limit.

        Args:
            cache: The cache dict to enforce limits on
            max_size: Maximum number of entries allowed
        """
        while len(cache) >= max_size:
            # Remove oldest entry (first key in dict - Python 3.7+ maintains order)
            oldest_key = next(iter(cache))
            del cache[oldest_key]

    def _should_skip_optional_sidecars(self, task: str) -> bool:
        """Skip high-latency sidecars for short, generic questions when opted in."""
        if not self._skip_empty_sidecars:
            return False

        normalized = " ".join(task.lower().split())
        if not normalized:
            return False

        words = normalized.split()
        is_short_question = normalized.endswith("?") and len(words) <= 8 and len(normalized) <= 80
        if not is_short_question:
            return False

        domain_keywords = (
            "api",
            "architecture",
            "auth",
            "benchmark",
            "bug",
            "cache",
            "compliance",
            "database",
            "debate",
            "debug",
            "design",
            "encryption",
            "fix",
            "gdpr",
            "implementation",
            "jwt",
            "knowledge mound",
            "latency",
            "migration",
            "obsidian",
            "oauth",
            "openapi",
            "performance",
            "pii",
            "postgres",
            "privacy",
            "python",
            "redis",
            "refactor",
            "sdk",
            "security",
            "shard",
            "sql",
            "swarm",
            "test",
            "threat",
            "typescript",
            "vector",
            "websocket",
            "worker",
        )
        return not any(keyword in normalized for keyword in domain_keywords)

    async def gather_all(self, task: str, timeout: float | None = None) -> str:
        """
        Perform multi-source research and return formatted context.

        Gathers context from:
        - Claude's web search (primary - best quality, uses Opus 4.5)
        - Aragora documentation (if task is Aragora-related)
        - Evidence connectors (web, GitHub, local docs) - fallback
        - Pulse/trending topics

        All sub-operations have individual timeouts to prevent blocking.
        Returns partial results if some sources timeout.

        Args:
            task: The debate topic/task description.
            timeout: Overall timeout in seconds (default: CONTEXT_GATHER_TIMEOUT)

        Returns:
            Formatted context string, or "No research context available."
        """
        # Check cache WITH task identity to prevent leaks between debates
        task_hash = self._get_task_hash(task)
        if task_hash in self._research_context_cache:
            return self._research_context_cache[task_hash]

        timeout = timeout or CONTEXT_GATHER_TIMEOUT
        context_parts = []

        async def _gather_with_timeout():
            nonlocal context_parts
            skip_optional_sidecars = self._should_skip_optional_sidecars(task)
            if skip_optional_sidecars:
                logger.info("[context] Skipping optional sidecars for simple task: %s", task)

            # 1. Primary: Claude's web search (best quality research)
            claude_ctx = None
            if not skip_optional_sidecars:
                claude_ctx = await self._gather_claude_web_search(task)
            if claude_ctx:
                context_parts.append(claude_ctx)

            # 2. Gather Aragora context (local files, fast)
            aragora_ctx = await self.gather_aragora_context(task)
            if aragora_ctx:
                context_parts.append(aragora_ctx)

            # 3. Gather trending context for real-time relevance (if enabled)
            trending_task = None
            if not skip_optional_sidecars and self._enable_trending_context:
                trending_task = asyncio.create_task(self._gather_trending_with_timeout())

            # 4. Gather knowledge mound context for institutional knowledge
            tasks = []
            if not skip_optional_sidecars:
                knowledge_task = asyncio.create_task(
                    self._gather_knowledge_mound_with_timeout(task)
                )
                tasks.append(knowledge_task)

                # 5. Gather belief crux context for debate guidance (fast, cached)
                belief_task = asyncio.create_task(self._gather_belief_with_timeout(task))
                tasks.append(belief_task)

                # 6. Gather culture patterns for organizational learning
                culture_task = asyncio.create_task(self._gather_culture_with_timeout(task))
                tasks.append(culture_task)

                # 7. Gather threat intelligence context for security topics
                threat_intel_task = asyncio.create_task(
                    self._gather_threat_intel_with_timeout(task)
                )
                tasks.append(threat_intel_task)

            # 8. Gather document/evidence store context (if available)
            document_task = None
            evidence_store_task = None
            if self._document_store and self._enable_document_context:
                document_task = asyncio.create_task(self._gather_document_store_with_timeout(task))
            if self._evidence_store and self._enable_evidence_store_context:
                evidence_store_task = asyncio.create_task(
                    self._gather_evidence_store_with_timeout(task)
                )

            # 9. Gather additional evidence in parallel (fallback if Claude search weak)
            if trending_task is not None:
                tasks.append(trending_task)
            if document_task is not None:
                tasks.append(document_task)
            if evidence_store_task is not None:
                tasks.append(evidence_store_task)

            if not skip_optional_sidecars and (not claude_ctx or len(claude_ctx) < 500):
                evidence_task = asyncio.create_task(self._gather_evidence_with_timeout(task))
                tasks.insert(0, evidence_task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, str) and result:
                    context_parts.append(result)
                elif isinstance(result, asyncio.TimeoutError):
                    logger.warning("Context gathering subtask timed out")
                elif isinstance(result, Exception):
                    logger.debug("Context gathering subtask failed: %s", result)

        try:
            await asyncio.wait_for(_gather_with_timeout(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Context gathering timed out after %ss, using partial results", timeout)

        if context_parts:
            result = "\n\n".join(context_parts)
            self._enforce_cache_limit(self._research_context_cache, MAX_CONTEXT_CACHE_SIZE)
            self._research_context_cache[task_hash] = result
            return result
        else:
            return "No research context available."

    async def gather_aragora_context(self, task: str) -> str | None:
        """
        Gather Aragora-specific documentation context if task is relevant.

        Only activates for tasks mentioning Aragora, multi-agent debates,
        decision stress-tests, nomic loop, or the debate framework.

        Uses RLM compression for large documents to preserve semantic content
        instead of simple truncation.

        Args:
            task: The debate topic/task description.

        Returns:
            Formatted documentation context, or None if not relevant.
        """
        task_lower = task.lower()
        is_aragora_topic = any(kw in task_lower for kw in ARAGORA_KEYWORDS)

        if not is_aragora_topic:
            return None

        try:
            docs_dir = self._project_root / "docs"
            aragora_context_parts: list[str] = []
            loop = asyncio.get_running_loop()

            def _read_file_sync(path: Path) -> str | None:
                """Read full file content without truncation."""
                try:
                    if path.exists():
                        return path.read_text()
                except (OSError, UnicodeDecodeError) as e:
                    logger.debug("Failed to read file %s: %s", path, e)
                return None

            # Read key documentation files (full content, RLM will compress)
            key_docs = ["FEATURES.md", "ARCHITECTURE.md", "QUICKSTART.md", "STATUS.md"]
            for doc_name in key_docs:
                doc_path = docs_dir / doc_name
                content = await loop.run_in_executor(
                    None,
                    functools.partial(_read_file_sync, doc_path),
                )
                if content:
                    # Use RLM to compress if content is large
                    compressed = await self._compress_with_rlm(
                        content,
                        source_type="documentation",
                        max_chars=3000,
                    )
                    aragora_context_parts.append(f"### {doc_name}\n{compressed}")

            # Optional: add a deep codebase map using TRUE RLM when available
            codebase_context = await self._gather_codebase_context()
            if codebase_context:
                aragora_context_parts.insert(0, codebase_context)

            # Also include CLAUDE.md for project overview
            claude_md = self._project_root / "CLAUDE.md"
            content = await loop.run_in_executor(None, lambda: _read_file_sync(claude_md))
            if content:
                # Compress CLAUDE.md with RLM if large
                compressed = await self._compress_with_rlm(
                    content,
                    source_type="documentation",
                    max_chars=2000,
                )
                aragora_context_parts.insert(0, f"### Project Overview (CLAUDE.md)\n{compressed}")

            if aragora_context_parts:
                logger.info("Injected Aragora project documentation context")
                return (
                    "## ARAGORA PROJECT CONTEXT\n"
                    "The following is internal documentation about the Aragora project:\n\n"
                    + "\n\n---\n\n".join(aragora_context_parts[:4])
                )

        except OSError as e:
            # Expected: file system issues reading docs
            logger.warning("Failed to load Aragora context (file error): %s", e)
        except (ValueError, RuntimeError) as e:
            # Expected: compression or parsing issues
            logger.warning("Failed to load Aragora context: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error loading Aragora context: %s", e)

        return None

    async def _gather_codebase_context(self) -> str | None:
        """Build a deep codebase context map using TRUE RLM when available."""
        if not get_use_codebase():
            return None

        if not self._project_root.is_dir():
            logger.debug(
                "Codebase context skipped: project root %s is not a directory",
                self._project_root,
            )
            return None

        try:
            from aragora.rlm.codebase_context import CodebaseContextBuilder
        except (ImportError, ModuleNotFoundError) as exc:
            logger.debug("Codebase context unavailable: %s", exc)
            return None

        if self._codebase_context_builder is None:
            try:
                self._codebase_context_builder = CodebaseContextBuilder(
                    root_path=self._project_root,
                    knowledge_mound=self._knowledge_mound,
                )
            except (RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.warning("Failed to initialize codebase context builder: %s", exc)
                return None

        if self._codebase_context_builder is None:
            logger.warning("Codebase context builder not initialized")
            return None

        try:
            timeout_seconds = float(
                _package_override("CODEBASE_CONTEXT_TIMEOUT", CODEBASE_CONTEXT_TIMEOUT)
            )
            context = await asyncio.wait_for(
                self._codebase_context_builder.build_debate_context(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Codebase context build timed out")
            return None
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as exc:
            logger.warning("Codebase context build failed: %s", exc)
            return None

        if not context:
            return None

        # An index with zero files means the root had nothing to map; a
        # header-only codebase map would be misleading, so emit nothing.
        index = getattr(self._codebase_context_builder, "_index", None)
        if index is not None and getattr(index, "total_files", None) == 0:
            logger.debug("Codebase context skipped: no files indexed")
            return None

        return "## ARAGORA CODEBASE MAP\n" + context

    def clear_cache(self, task: str | None = None) -> None:
        """Clear cached context, optionally for a specific task.

        Args:
            task: If provided, only clear cache for this specific task.
                  If None, clear all cached context.
        """
        if task is None:
            self._research_context_cache.clear()
            self._research_evidence_pack.clear()
            self._continuum_context_cache.clear()
            self._trending_topics_cache = []
        else:
            task_hash = self._get_task_hash(task)
            self._research_context_cache.pop(task_hash, None)
            self._research_evidence_pack.pop(task_hash, None)
            self._continuum_context_cache.pop(task_hash, None)
