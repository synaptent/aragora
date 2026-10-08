"""
Content processing for context gathering.

Handles content transformation and compression:
- RLM-based compression for large documents
- Aragora documentation processing
- Codebase context building
- Continuum memory formatting
- Evidence refresh and merging
"""

import asyncio
import functools
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.rlm.compressor import HierarchicalCompressor

logger = logging.getLogger(__name__)

# Configurable timeout
CODEBASE_CONTEXT_TIMEOUT = float(os.getenv("ARAGORA_CODEBASE_CONTEXT_TIMEOUT", "60.0"))

# Define fallback values before imports to avoid redefinition errors
_get_rlm: Callable[[], Any] | None = None
_get_compressor: Callable[[], Any] | None = None

# Check for RLM availability (use factory for consistent initialization)
try:
    from aragora.rlm import get_rlm as _imported_get_rlm
    from aragora.rlm import get_compressor as _imported_get_compressor
    from aragora.rlm import HAS_OFFICIAL_RLM

    HAS_RLM = True
    _get_rlm = _imported_get_rlm
    _get_compressor = _imported_get_compressor
except ImportError:
    HAS_RLM = False
    HAS_OFFICIAL_RLM = False

# Alias for cleaner usage
get_rlm = _get_rlm
get_compressor = _get_compressor


class ContentProcessor:
    """
    Processes and transforms content for context gathering.

    Handles:
    - RLM-based hierarchical compression
    - Aragora documentation extraction
    - Codebase context building
    - Continuum memory formatting
    - Evidence refresh for mid-debate updates
    """

    def __init__(
        self,
        project_root: Path | None = None,
        enable_rlm_compression: bool = True,
        rlm_compressor: Optional["HierarchicalCompressor"] = None,
        rlm_compression_threshold: int = 3000,
        knowledge_mound: Any | None = None,
    ):
        """
        Initialize the content processor.

        Args:
            project_root: Project root path for documentation lookup.
            enable_rlm_compression: Whether to use RLM for large document compression.
            rlm_compressor: Optional pre-configured HierarchicalCompressor.
            rlm_compression_threshold: Char count above which to apply RLM compression.
            knowledge_mound: Optional KnowledgeMound for codebase context.
        """
        self._project_root = project_root or Path(__file__).parent.parent.parent.parent
        self._rlm_threshold = rlm_compression_threshold
        self._knowledge_mound = knowledge_mound

        # RLM configuration - use factory for consistent initialization
        self._enable_rlm = enable_rlm_compression and HAS_RLM
        self._rlm_compressor = rlm_compressor
        self._aragora_rlm: Any | None = None
        self._codebase_context_builder: Any = None

        if self._enable_rlm and get_rlm is not None:
            # Use factory to get AragoraRLM (routes to TRUE RLM when available)
            try:
                self._aragora_rlm = get_rlm()
                if HAS_OFFICIAL_RLM:
                    logger.info(
                        "[rlm] ContentProcessor: TRUE RLM enabled via factory "
                        "(REPL-based, model writes code to examine context)"
                    )
                else:
                    logger.info(
                        "[rlm] ContentProcessor: AragoraRLM enabled via factory "
                        "(will use compression fallback since official RLM not installed)"
                    )
            except ImportError as e:
                logger.debug("[rlm] RLM module not available: %s", e)
            except (RuntimeError, ValueError) as e:
                logger.warning("[rlm] Failed to initialize RLM: %s", e)
            except (OSError, TypeError, KeyError) as e:
                logger.warning("[rlm] Unexpected error getting RLM from factory: %s", e)

            # Fallback: get compressor from factory (compression-only)
            if not self._rlm_compressor and get_compressor is not None:
                try:
                    self._rlm_compressor = get_compressor()
                    logger.debug(
                        "[rlm] ContentProcessor: HierarchicalCompressor fallback via factory"
                    )
                except ImportError as e:
                    logger.debug("[rlm] Compressor module not available: %s", e)
                except (RuntimeError, ValueError) as e:
                    logger.warning("[rlm] Failed to initialize compressor: %s", e)
                except (OSError, TypeError, KeyError) as e:
                    logger.warning("[rlm] Unexpected error getting compressor: %s", e)

    async def compress_with_rlm(
        self,
        content: str,
        source_type: str = "documentation",
        max_chars: int = 3000,
    ) -> str:
        """
        Compress large content using RLM.

        Prioritizes TRUE RLM (REPL-based) via AragoraRLM when available:
        - Model writes code to examine/summarize content
        - Model has agency in deciding how to compress

        Falls back to HierarchicalCompressor (compression-only) if:
        - Official RLM not installed
        - AragoraRLM fails

        Falls back to truncation if all else fails.

        Args:
            content: The content to compress
            source_type: Type of content (for compression hints)
            max_chars: Target character limit

        Returns:
            Compressed or truncated content
        """
        # If content is under threshold, return as-is
        if len(content) <= self._rlm_threshold:
            return content[:max_chars] if len(content) > max_chars else content

        # If RLM is not enabled, use simple truncation
        if not self._enable_rlm:
            return (
                content[: max_chars - 30] + "... [truncated]"
                if len(content) > max_chars
                else content
            )

        # PRIMARY: Try AragoraRLM (routes to TRUE RLM if available)
        if self._aragora_rlm:
            try:
                logger.debug(
                    "[rlm] Using AragoraRLM for compression (routes to TRUE RLM if available)"
                )
                result = await asyncio.wait_for(
                    self._aragora_rlm.compress_and_query(
                        query=f"Summarize this {source_type} in under {max_chars} characters",
                        content=content,
                        source_type=source_type,
                    ),
                    timeout=15.0,
                )

                if result.answer and len(result.answer) < len(content):
                    approach = "TRUE RLM" if result.used_true_rlm else "compression fallback"
                    logger.debug(
                        "[rlm] Compressed %s -> %s chars (%s%%) via %s",
                        len(content),
                        len(result.answer),
                        int(len(result.answer) / len(content) * 100),
                        approach,
                    )
                    return (
                        result.answer[:max_chars]
                        if len(result.answer) > max_chars
                        else result.answer
                    )

            except asyncio.TimeoutError:
                logger.debug("[rlm] AragoraRLM compression timed out")
            except (ValueError, RuntimeError) as e:
                logger.debug("[rlm] AragoraRLM compression failed: %s", e)
            except (OSError, TypeError, KeyError, AttributeError) as e:
                logger.warning("[rlm] Unexpected error in AragoraRLM compression: %s", e)

        # FALLBACK: Try direct HierarchicalCompressor (compression-only)
        if self._rlm_compressor:
            try:
                logger.debug(
                    "[rlm] Falling back to HierarchicalCompressor (compression-only, no TRUE RLM)"
                )
                compression_result = await asyncio.wait_for(
                    self._rlm_compressor.compress(
                        content=content,
                        source_type=source_type,
                        max_levels=2,  # ABSTRACT and SUMMARY for faster compression
                    ),
                    timeout=10.0,
                )

                # Get summary level (or abstract if summary is too long)
                try:
                    from aragora.rlm.types import AbstractionLevel

                    summary = compression_result.context.get_at_level(AbstractionLevel.SUMMARY)
                    if summary and len(summary) > max_chars:
                        summary = compression_result.context.get_at_level(AbstractionLevel.ABSTRACT)
                except (ImportError, AttributeError):
                    summary = None

                if summary and len(summary) < len(content):
                    logger.debug(
                        "[rlm] Compressed %s -> %s chars (%s%%) via HierarchicalCompressor",
                        len(content),
                        len(summary),
                        int(len(summary) / len(content) * 100),
                    )
                    return summary[:max_chars] if len(summary) > max_chars else summary

            except asyncio.TimeoutError:
                logger.debug("[rlm] HierarchicalCompressor timed out")
            except (ValueError, RuntimeError) as e:
                logger.debug("[rlm] HierarchicalCompressor failed: %s", e)
            except (OSError, TypeError, KeyError, AttributeError) as e:
                logger.warning("[rlm] Unexpected error in HierarchicalCompressor: %s", e)

        # FINAL FALLBACK: Simple truncation
        logger.debug("[rlm] All RLM approaches failed, using simple truncation")
        return (
            content[: max_chars - 30] + "... [truncated]" if len(content) > max_chars else content
        )

    async def query_with_true_rlm(
        self,
        query: str,
        content: str,
        source_type: str = "documentation",
    ) -> str | None:
        """
        Query content using TRUE RLM (REPL-based) when available.

        TRUE RLM allows the model to write code to examine context stored
        as Python variables in a REPL environment, rather than having the
        context stuffed into prompts.

        Args:
            query: The question to answer about the content
            content: The content to query
            source_type: Type of content (for context hints)

        Returns:
            Answer from TRUE RLM, or None if not available
        """
        if not self._enable_rlm or not self._aragora_rlm:
            return None

        try:
            # Check if TRUE RLM is available (not just compression fallback)
            if HAS_RLM and HAS_OFFICIAL_RLM:
                logger.debug(
                    "[rlm] Using TRUE RLM for query: '%s...' on %s chars of %s",
                    query[:50],
                    len(content),
                    source_type,
                )

                result = await asyncio.wait_for(
                    self._aragora_rlm.query(
                        query=query,
                        context=content,
                        strategy="auto",  # Let RLM decide: grep, partition, peek, etc.
                    ),
                    timeout=20.0,
                )

                if result.used_true_rlm and result.answer:
                    logger.debug(
                        "[rlm] TRUE RLM query successful: %s chars, confidence=%s",
                        len(result.answer),
                        result.confidence,
                    )
                    return result.answer

            # TRUE RLM not available - fall back to compress_and_query
            logger.debug("[rlm] TRUE RLM not available for query, using compress_and_query")
            result = await asyncio.wait_for(
                self._aragora_rlm.compress_and_query(
                    query=query,
                    content=content,
                    source_type=source_type,
                ),
                timeout=15.0,
            )

            if result.answer:
                approach = "TRUE RLM" if result.used_true_rlm else "compression"
                logger.debug("[rlm] Query via %s: %s chars", approach, len(result.answer))
                return result.answer

        except asyncio.TimeoutError:
            logger.debug("[rlm] TRUE RLM query timed out for: '%s...'", query[:30])
        except (ValueError, RuntimeError) as e:
            logger.debug("[rlm] TRUE RLM query failed: %s", e)
        except (OSError, TypeError, KeyError, AttributeError) as e:
            logger.warning("[rlm] Unexpected error in TRUE RLM query: %s", e)

        return None

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
        is_aragora_topic = any(
            kw in task_lower
            for kw in [
                "aragora",
                "multi-agent debate",
                "decision stress-test",
                "ai red team",
                "adversarial validation",
                "gauntlet",
                "nomic loop",
                "debate framework",
            ]
        )

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
                    compressed = await self.compress_with_rlm(
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
                compressed = await self.compress_with_rlm(
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
            logger.warning("Failed to load Aragora context (file error): %s", e)
        except (ValueError, RuntimeError) as e:
            logger.warning("Failed to load Aragora context: %s", e)
        except (TypeError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error loading Aragora context: %s", e)

        return None

    async def _gather_codebase_context(self) -> str | None:
        """Build a deep codebase context map using TRUE RLM when available."""
        use_env = os.getenv("ARAGORA_CONTEXT_USE_CODEBASE") or os.getenv(
            "NOMIC_CONTEXT_USE_CODEBASE"
        )
        if use_env is None:
            use_codebase = True
        else:
            use_codebase = use_env.strip().lower() in {"1", "true", "yes", "on"}
        if not use_codebase:
            return None

        if not self._project_root.is_dir():
            logger.debug(
                "Codebase context skipped: project root %s is not a directory",
                self._project_root,
            )
            return None

        try:
            from aragora.rlm.codebase_context import CodebaseContextBuilder
        except (ImportError, OSError) as exc:
            logger.debug("Codebase context unavailable: %s", exc)
            return None

        if self._codebase_context_builder is None:
            try:
                self._codebase_context_builder = CodebaseContextBuilder(
                    root_path=self._project_root,
                    knowledge_mound=self._knowledge_mound,
                )
            except (RuntimeError, ValueError, OSError, TypeError) as exc:
                logger.warning("Failed to initialize codebase context builder: %s", exc)
                return None

        if self._codebase_context_builder is None:
            logger.warning("Codebase context builder not initialized")
            return None

        try:
            context = await asyncio.wait_for(
                self._codebase_context_builder.build_debate_context(),
                timeout=CODEBASE_CONTEXT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Codebase context build timed out")
            return None
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
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

    def get_continuum_context(
        self,
        continuum_memory: Any,
        domain: str,
        task: str,
        include_glacial_insights: bool = True,
        tenant_id: str | None = None,
        auth_context: Any | None = None,
    ) -> tuple[str, list[str], dict[str, Any]]:
        """Retrieve relevant memories from ContinuumMemory for debate context.

        Uses the debate task and domain to query for related past learnings.
        Enhanced with tier-aware retrieval, confidence markers, and glacial insights.

        Args:
            continuum_memory: ContinuumMemory instance to query
            domain: The debate domain (e.g., "programming", "ethics")
            task: The debate task description
            include_glacial_insights: Whether to include long-term glacial tier insights

        Returns:
            Tuple of:
            - Formatted context string
            - List of retrieved memory IDs (for outcome tracking)
            - Dict mapping memory ID to tier (for analytics)
        """
        if not continuum_memory:
            return "", [], {}

        try:
            try:
                from aragora.memory.access import (
                    emit_denial_telemetry,
                    filter_entries,
                    has_memory_read_access,
                )
            except (ImportError, AttributeError):
                emit_denial_telemetry = None  # type: ignore[assignment]
                filter_entries = None  # type: ignore[assignment]
                has_memory_read_access = None  # type: ignore[assignment]

            if (
                auth_context is not None
                and has_memory_read_access is not None
                and not has_memory_read_access(auth_context)
            ):
                if emit_denial_telemetry is not None:
                    emit_denial_telemetry(
                        "debate.context.continuum",
                        auth_context,
                        "missing_memory_read_permission",
                    )
                return "", [], {}

            query = f"{domain}: {task[:200]}"
            all_memories = []
            retrieved_ids = []
            retrieved_tiers = {}

            # 1. Retrieve recent memories from fast/medium/slow tiers
            memories = continuum_memory.retrieve(
                query=query,
                limit=5,
                min_importance=0.3,
                include_glacial=False,  # Get recent memories first
                tenant_id=tenant_id,
            )
            all_memories.extend(memories)

            # 2. Also retrieve glacial tier insights for cross-session learning
            if include_glacial_insights and hasattr(continuum_memory, "get_glacial_insights"):
                glacial_insights = continuum_memory.get_glacial_insights(
                    topic=task[:100],
                    limit=3,
                    min_importance=0.4,  # Higher threshold for long-term patterns
                )
                if tenant_id:
                    glacial_insights = [
                        m
                        for m in glacial_insights
                        if getattr(m, "metadata", {}).get("tenant_id") == tenant_id
                    ]
                if glacial_insights:
                    logger.info(
                        "  [continuum] Retrieved %s glacial insights for cross-session learning",
                        len(glacial_insights),
                    )
                    all_memories.extend(glacial_insights)

            if filter_entries is not None and auth_context is not None:
                all_memories = filter_entries(
                    all_memories,
                    auth_context,
                    source="debate.context.continuum",
                )

            if not all_memories:
                return "", [], {}

            # Track retrieved memory IDs and tiers for outcome updates and analytics
            retrieved_ids = [mem_id for mem in all_memories if (mem_id := getattr(mem, "id", None))]
            retrieved_tiers = {
                mem_id: tier
                for mem in all_memories
                if (mem_id := getattr(mem, "id", None)) and (tier := getattr(mem, "tier", None))
            }

            # Format memories with confidence markers based on consolidation
            context_parts = ["[Previous learnings relevant to this debate:]"]

            # Format recent memories (fast/medium/slow)
            recent_mems = [
                m
                for m in all_memories
                if getattr(m, "tier", None) and getattr(m, "tier").value != "glacial"
            ]
            for mem in recent_mems[:3]:
                content = mem.content[:200] if hasattr(mem, "content") else str(mem)[:200]
                tier = mem.tier.value if hasattr(mem, "tier") else "unknown"
                consolidation = getattr(mem, "consolidation_score", 0.5)
                confidence = (
                    "high" if consolidation > 0.7 else "medium" if consolidation > 0.4 else "low"
                )
                context_parts.append(f"- [{tier}|{confidence}] {content}")

            # Format glacial insights separately (long-term patterns)
            glacial_mems = [
                m
                for m in all_memories
                if getattr(m, "tier", None) and getattr(m, "tier").value == "glacial"
            ]
            if glacial_mems:
                context_parts.append("\n[Long-term patterns from previous sessions:]")
                for mem in glacial_mems[:2]:
                    content = mem.content[:250] if hasattr(mem, "content") else str(mem)[:250]
                    context_parts.append(f"- [glacial|foundational] {content}")

            context = "\n".join(context_parts)
            logger.info(
                "  [continuum] Retrieved %s recent + %s glacial memories for domain '%s'",
                len(recent_mems),
                len(glacial_mems),
                domain,
            )
            return context, retrieved_ids, retrieved_tiers
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning("  [continuum] Memory retrieval error: %s", e)
            return "", [], {}
        except (KeyError, IndexError, RuntimeError, OSError) as e:
            logger.warning(
                "  [continuum] Unexpected memory error (type=%s): %s", type(e).__name__, e
            )
            return "", [], {}

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

            # Store in memory for future debates
            if (
                evidence_pack.snippets
                and evidence_store_callback
                and callable(evidence_store_callback)
            ):
                evidence_store_callback(evidence_pack.snippets, task)

            return len(evidence_pack.snippets), evidence_pack

        except (ConnectionError, OSError, ValueError, RuntimeError, AttributeError, TypeError) as e:
            logger.warning("Evidence refresh failed: %s", e)
            return 0, None

    async def query_knowledge_with_true_rlm(
        self,
        task: str,
        knowledge_mound: Any,
        knowledge_workspace_id: str = "debate",
        max_items: int = 10,
    ) -> str | None:
        """
        Query Knowledge Mound using TRUE RLM for better answer quality.

        When TRUE RLM is available, creates a REPL environment where the
        model can write code to navigate and query knowledge items.

        Args:
            task: The debate task/query
            knowledge_mound: KnowledgeMound instance
            knowledge_workspace_id: Workspace ID for queries
            max_items: Maximum knowledge items to include in context

        Returns:
            Synthesized answer from knowledge, or None if unavailable
        """
        if not knowledge_mound:
            return None

        if not (HAS_RLM and HAS_OFFICIAL_RLM):
            # TRUE RLM not available - caller should use standard query
            return None

        try:
            from aragora.rlm import get_repl_adapter
            from .cache import ContextCache

            adapter = get_repl_adapter()
            task_hash = ContextCache.get_task_hash(task)

            # Create REPL environment for knowledge queries
            env = adapter.create_repl_for_knowledge(
                mound=knowledge_mound,
                workspace_id=knowledge_workspace_id,
                content_id=f"km_{task_hash}",
            )

            if not env:
                return None

            # Get REPL prompt for agent
            repl_prompt = adapter.get_repl_prompt(
                content_id=f"km_{task_hash}",
                content_type="knowledge",
            )

            logger.info(
                "[rlm] Created TRUE RLM REPL environment for knowledge query: '%s...'",
                task[:50],
            )

            # Return the REPL prompt - the agent will use it to write code
            return (
                "## KNOWLEDGE MOUND CONTEXT (TRUE RLM)\n"
                f"A REPL environment is available for knowledge queries.\n\n"
                f"{repl_prompt}\n"
            )

        except ImportError:
            logger.debug("[rlm] REPL adapter not available for knowledge queries")
        except (RuntimeError, ValueError, OSError, TypeError, KeyError) as e:
            logger.warning("[rlm] Failed to create knowledge REPL: %s", e)

        return None


# Re-export for backwards compatibility
__all__ = [
    "ContentProcessor",
    "CODEBASE_CONTEXT_TIMEOUT",
    "HAS_RLM",
    "HAS_OFFICIAL_RLM",
    "get_rlm",
    "get_compressor",
]
