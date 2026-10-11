"""
Cross-debate RLM memory for institutional knowledge.

Uses official RLM (when installed) or hierarchical compression as fallback
to maintain context from previous debates, enabling agents to reference
and build upon past discussions.

The official RLM approach (github.com/alexzhang13/rlm) stores context as a
Python variable in a REPL environment (NOT in prompts). The LLM writes code
to programmatically examine/grep/partition the context. Compression-based
approaches are used as fallbacks when the official library is unavailable.

Usage:
    from aragora.memory.cross_debate_rlm import CrossDebateMemory

    memory = CrossDebateMemory()
    await memory.add_debate(debate_result)

    # Query past debates using official RLM (preferred) or fallback
    if memory.has_real_rlm:
        answer = await memory.query_past_debates("What consensus was reached?")
    else:
        context = await memory.get_relevant_context(task="Design a new API")

Install official RLM support:
    pip install rlm
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core import DebateResult

# Check for RLM library (use factory for consistent initialization)
try:
    from aragora.rlm import get_rlm, get_compressor, HAS_OFFICIAL_RLM

    HAS_RLM_FACTORY = True
except ImportError:
    HAS_OFFICIAL_RLM = False
    HAS_RLM_FACTORY = False
    get_rlm = None  # type: ignore[assignment]  # optional import fallback: function -> None when module unavailable
    get_compressor = None  # type: ignore[assignment]  # optional import fallback: function -> None when module unavailable

logger = logging.getLogger(__name__)


class AccessTier(Enum):
    """Access recency tiers for cross-debate context.

    NOTE: This is distinct from aragora.memory.tier_manager.MemoryTier which
    tracks UPDATE FREQUENCY (FAST/MEDIUM/SLOW/GLACIAL). AccessTier tracks
    RECENCY of access for debate context retrieval.

    - HOT: Recently accessed debates, full detail preserved
    - WARM: Less recent debates, summary-level context
    - COLD: Older debates, abstract-level context
    - ARCHIVE: Very old debates, minimal context retained
    """

    HOT = "hot"  # Recent debates, full detail
    WARM = "warm"  # Older debates, summary level
    COLD = "cold"  # Old debates, abstract level
    ARCHIVE = "archive"  # Very old, minimal context


# Backward compatibility alias
MemoryTier = AccessTier


@dataclass
class DebateMemoryEntry:
    """Entry in the cross-debate memory."""

    debate_id: str
    task: str
    domain: str
    timestamp: datetime
    tier: MemoryTier
    participants: list[str]
    consensus_reached: bool
    final_answer: str
    key_insights: list[str]
    compressed_context: str
    rlm_context: Any | None = None
    token_count: int = 0
    access_count: int = 0
    last_accessed: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "debate_id": self.debate_id,
            "task": self.task,
            "domain": self.domain,
            "timestamp": self.timestamp.isoformat(),
            "tier": self.tier.value,
            "participants": self.participants,
            "consensus_reached": self.consensus_reached,
            "final_answer": self.final_answer,
            "key_insights": self.key_insights,
            "compressed_context": self.compressed_context,
            "token_count": self.token_count,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateMemoryEntry:
        """Create from dictionary."""
        return cls(
            debate_id=data["debate_id"],
            task=data["task"],
            domain=data.get("domain", "general"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            tier=MemoryTier(data.get("tier", "warm")),
            participants=data.get("participants", []),
            consensus_reached=data.get("consensus_reached", False),
            final_answer=data.get("final_answer", ""),
            key_insights=data.get("key_insights", []),
            compressed_context=data.get("compressed_context", ""),
            token_count=data.get("token_count", 0),
            access_count=data.get("access_count", 0),
            last_accessed=(
                datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None
            ),
        )


@dataclass
class CrossDebateConfig:
    """Configuration for cross-debate memory."""

    # Tier thresholds
    hot_duration: timedelta = field(default_factory=lambda: timedelta(hours=24))
    warm_duration: timedelta = field(default_factory=lambda: timedelta(days=7))
    cold_duration: timedelta = field(default_factory=lambda: timedelta(days=30))

    # Memory limits
    max_entries: int = 1000
    max_hot_entries: int = 50
    max_warm_entries: int = 200
    max_cold_entries: int = 500

    # Token budgets per tier
    hot_token_budget: int = 5000
    warm_token_budget: int = 2000
    cold_token_budget: int = 500

    # Compression settings
    enable_rlm: bool = True
    compression_levels: int = 3

    # Persistence
    persist_to_disk: bool = True
    storage_path: Path | None = None

    # Knowledge Mound integration (enriches context with KM-sourced insights)
    enable_km_integration: bool = True
    km_max_results: int = 5

    def __post_init__(self) -> None:
        """Validate config and set defaults."""
        import logging
        import warnings

        # If persist_to_disk is True but no storage_path, set a default
        if self.persist_to_disk and self.storage_path is None:
            from aragora.persistence.db_config import get_nomic_dir

            try:
                nomic_dir = get_nomic_dir()
                self.storage_path = nomic_dir / "cross_debate_memory.json"
                logging.getLogger(__name__).debug(
                    "CrossDebateConfig: Using default storage_path: %s", self.storage_path
                )
            except (OSError, PermissionError, FileNotFoundError) as e:
                # Expected errors: path resolution, permission, or missing directory
                logging.getLogger(__name__).warning(
                    "CrossDebateConfig: Could not determine default storage path: %s", e
                )
                warnings.warn(
                    "CrossDebateConfig: persist_to_disk=True but no storage_path and "
                    "couldn't determine default path. Disabling disk persistence.",
                    UserWarning,
                    stacklevel=2,
                )
                self.persist_to_disk = False
            except RuntimeError as e:
                logging.getLogger(__name__).exception(
                    "CrossDebateConfig: Unexpected error determining storage path: %s", e
                )
                warnings.warn(
                    "CrossDebateConfig: persist_to_disk=True but no storage_path and "
                    "couldn't determine default path. Disabling disk persistence.",
                    UserWarning,
                    stacklevel=2,
                )
                self.persist_to_disk = False


class CrossDebateMemory:
    """
    Cross-debate memory with RLM compression.

    Maintains institutional knowledge from past debates,
    automatically managing memory tiers and compression.
    """

    def __init__(
        self,
        config: CrossDebateConfig | None = None,
        continuum_memory: Any | None = None,
    ):
        """Initialize cross-debate memory.

        Args:
            config: Configuration for cross-debate memory.
            continuum_memory: Optional ContinuumMemory for bridging
                institutional knowledge to the slow tier.
        """
        self.config = config or CrossDebateConfig()
        self._entries: dict[str, DebateMemoryEntry] = {}
        self._compressor: Any = None
        self._rlm: Any = None  # Official RLM instance (preferred over compression)
        self._km_debate_adapter: Any = None  # DebateAdapter for KM integration
        self._continuum_memory = continuum_memory
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def has_real_rlm(self) -> bool:
        """Check if official RLM library is available.

        When True, query_past_debates() uses the REPL-based approach where
        context is stored as a Python variable and queried programmatically.

        When False, falls back to compression-based context retrieval.
        """
        return HAS_OFFICIAL_RLM

    async def _get_rlm(self) -> Any:
        """Get AragoraRLM instance via factory (routes to TRUE RLM when available).

        Returns:
            AragoraRLM instance. Will use TRUE RLM (REPL-based) if official
            library is installed, otherwise uses compression fallback.
        """
        if not self.config.enable_rlm:
            return None
        if not HAS_RLM_FACTORY or get_rlm is None:
            return None

        if self._rlm is None:
            try:
                self._rlm = get_rlm()
                if HAS_OFFICIAL_RLM:
                    logger.info(
                        "[CrossDebateMemory] TRUE RLM initialized via factory "
                        "(REPL-based, model writes code to examine context)"
                    )
                else:
                    logger.info(
                        "[CrossDebateMemory] AragoraRLM initialized via factory "
                        "(will use compression fallback since official RLM not installed)"
                    )
            except (ImportError, AttributeError, TypeError, RuntimeError) as e:
                logger.warning("[CrossDebateMemory] Failed to get RLM from factory: %s", e)
        return self._rlm

    async def initialize(self) -> None:
        """Initialize the memory system."""
        if self._initialized:
            return

        if self.config.persist_to_disk and self.config.storage_path:
            await self._load_from_disk()

        self._initialized = True

    async def _get_compressor(self) -> Any:
        """Lazy-load the RLM compressor via factory."""
        if self._compressor is None and self.config.enable_rlm:
            if get_compressor is not None:
                try:
                    self._compressor = get_compressor()
                except (ImportError, AttributeError, TypeError, RuntimeError) as e:
                    logger.warning("Failed to get compressor from factory: %s", e)
            else:
                logger.warning("RLM factory not available for cross-debate memory")
        return self._compressor

    def _get_km_debate_adapter(self) -> Any:
        """Lazy-load Knowledge Mound DebateAdapter for enriched context.

        Returns:
            DebateAdapter instance or None if not available.
        """
        if self._km_debate_adapter is not None:
            return self._km_debate_adapter

        if not self.config.enable_km_integration:
            return None

        try:
            from aragora.knowledge.mound.adapters.debate_adapter import DebateAdapter

            self._km_debate_adapter = DebateAdapter()
            logger.info(
                "[CrossDebateMemory] Knowledge Mound DebateAdapter initialized "
                "for enriched cross-debate context"
            )
        except ImportError:
            logger.debug("DebateAdapter not available - KM integration disabled")
        except (RuntimeError, TypeError, AttributeError) as e:
            logger.warning("Failed to initialize KM DebateAdapter: %s", e)

        return self._km_debate_adapter

    async def _query_km_debates(
        self,
        topic: str,
        domain: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for relevant past debates.

        Args:
            topic: Topic/task to search for
            domain: Optional domain filter
            limit: Maximum results to return

        Returns:
            List of debate summaries from Knowledge Mound
        """
        adapter = self._get_km_debate_adapter()
        if adapter is None:
            return []

        try:
            results = adapter.search_by_topic(
                topic=topic,
                limit=limit,
            )
            # Filter by domain if specified
            if domain:
                results = [r for r in results if r.get("domain") == domain]

            km_summaries = []
            for result in results[:limit]:
                km_summaries.append(
                    {
                        "debate_id": result.get("debate_id", ""),
                        "topic": result.get("topic", ""),
                        "consensus_reached": result.get("consensus_reached", False),
                        "conclusion": result.get("conclusion", ""),
                        "key_insights": result.get("key_insights", []),
                        "confidence": result.get("confidence", 0.5),
                        "source": "knowledge_mound",
                    }
                )
            return km_summaries
        except (RuntimeError, TypeError, AttributeError, KeyError) as e:
            logger.warning("KM debate query failed: %s", e)
            return []

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count."""
        return len(text) // 4

    def _generate_id(self, task: str, timestamp: datetime) -> str:
        """Generate a unique ID for a debate entry."""
        content = f"{task}{timestamp.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _determine_tier(self, timestamp: datetime) -> MemoryTier:
        """Determine the appropriate tier based on age."""
        age = datetime.now() - timestamp

        if age < self.config.hot_duration:
            return MemoryTier.HOT
        if age < self.config.warm_duration:
            return MemoryTier.WARM
        if age < self.config.cold_duration:
            return MemoryTier.COLD
        return MemoryTier.ARCHIVE

    async def add_debate(self, result: DebateResult) -> str:
        """
        Add a debate result to memory.

        Args:
            result: The debate result to add

        Returns:
            The ID of the memory entry
        """
        await self.initialize()
        async with self._lock:
            timestamp = datetime.now()
            debate_id = getattr(result, "debate_id", None) or self._generate_id(
                getattr(result, "task", ""), timestamp
            )

            # Extract key information
            task = getattr(result, "task", "")
            domain = getattr(result, "domain", "general")
            participants = getattr(result, "participants", [])
            consensus_reached = getattr(result, "consensus_reached", False)
            final_answer = getattr(result, "final_answer", "")

            # Extract key insights from messages
            key_insights = await self._extract_insights(result)

            # Build context for compression
            full_context = self._build_debate_context(result)

            # Compress the context
            compressed_context = await self._compress_context(full_context)

            # Create entry
            entry = DebateMemoryEntry(
                debate_id=debate_id,
                task=task,
                domain=domain,
                timestamp=timestamp,
                tier=MemoryTier.HOT,
                participants=participants,
                consensus_reached=consensus_reached,
                final_answer=final_answer,
                key_insights=key_insights,
                compressed_context=compressed_context,
                token_count=self._estimate_tokens(compressed_context),
            )

            self._entries[debate_id] = entry

            # Bridge: write institutional knowledge to Continuum slow tier
            if self._continuum_memory:
                try:
                    continuum_content = f"Debate conclusion [{domain}]: {final_answer}"
                    if hasattr(self._continuum_memory, "store_pattern"):
                        self._continuum_memory.store_pattern(
                            content=continuum_content,
                            importance=0.6 if consensus_reached else 0.3,
                            metadata={
                                "debate_id": debate_id,
                                "domain": domain,
                                "source": "cross_debate_bridge",
                                "tier_hint": "slow",
                            },
                        )
                    elif hasattr(self._continuum_memory, "add"):
                        self._continuum_memory.add(
                            id=f"xdebate_{debate_id}",
                            content=continuum_content,
                            importance=0.6 if consensus_reached else 0.3,
                            metadata={"debate_id": debate_id, "source": "cross_debate_bridge"},
                        )
                except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
                    logger.warning("Continuum bridge write failed: %s", exc)

            # Manage memory limits
            await self._manage_memory_limits()

            # Persist if enabled
            if self.config.persist_to_disk:
                await self._save_to_disk()

            return debate_id

    async def store_debate(
        self,
        debate_id: str,
        topic: str,
        consensus: str = "",
        key_points: list[str] | None = None,
        domain: str = "general",
        participants: list[str] | None = None,
        timestamp_hours_ago: float | None = None,
    ) -> str:
        """
        Convenience method to store a debate with explicit fields.

        This is an alternative to add_debate() that accepts individual fields
        rather than a DebateResult object.

        Args:
            debate_id: Unique identifier for the debate
            topic: The debate topic/task
            consensus: The final consensus or answer
            key_points: Key points or insights from the debate
            domain: Domain category for the debate
            participants: List of participant agent IDs
            timestamp_hours_ago: Optional hours in the past for the timestamp
                (useful for testing tier transitions)

        Returns:
            The debate ID
        """
        await self.initialize()
        async with self._lock:
            if timestamp_hours_ago is not None:
                timestamp = datetime.now() - timedelta(hours=timestamp_hours_ago)
            else:
                timestamp = datetime.now()

            # Build compressed context from the provided fields
            context_parts = [f"Topic: {topic}", f"Consensus: {consensus}"]
            if key_points:
                context_parts.append("Key Points:")
                for point in key_points:
                    context_parts.append(f"  - {point}")
            full_context = "\n".join(context_parts)

            # Compress the context
            compressed_context = await self._compress_context(full_context)

            # Determine tier based on timestamp
            tier = self._determine_tier(timestamp)

            # Create entry
            entry = DebateMemoryEntry(
                debate_id=debate_id,
                task=topic,
                domain=domain,
                timestamp=timestamp,
                tier=tier,
                participants=participants or [],
                consensus_reached=True,
                final_answer=consensus,
                key_insights=key_points or [],
                compressed_context=compressed_context,
                token_count=self._estimate_tokens(compressed_context),
            )

            self._entries[debate_id] = entry

            # Bridge: write institutional knowledge to Continuum slow tier
            if self._continuum_memory:
                try:
                    continuum_content = f"Debate conclusion [{domain}]: {consensus}"
                    if hasattr(self._continuum_memory, "store_pattern"):
                        self._continuum_memory.store_pattern(
                            content=continuum_content,
                            importance=0.6,
                            metadata={
                                "debate_id": debate_id,
                                "domain": domain,
                                "source": "cross_debate_bridge",
                                "tier_hint": "slow",
                            },
                        )
                    elif hasattr(self._continuum_memory, "add"):
                        self._continuum_memory.add(
                            id=f"xdebate_{debate_id}",
                            content=continuum_content,
                            importance=0.6,
                            metadata={"debate_id": debate_id, "source": "cross_debate_bridge"},
                        )
                except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
                    logger.warning("Continuum bridge write failed: %s", exc)

            # Manage memory limits
            await self._manage_memory_limits()

            # Persist if enabled
            if self.config.persist_to_disk:
                await self._save_to_disk()

            return debate_id

    def get_tier(self, debate_id: str) -> MemoryTier | None:
        """
        Get the memory tier for a debate entry.

        Args:
            debate_id: The debate ID to look up

        Returns:
            The MemoryTier for the debate, or None if not found
        """
        entry = self._entries.get(debate_id)
        if entry:
            return entry.tier
        return None

    async def _extract_insights(self, result: DebateResult) -> list[str]:
        """Extract key insights from a debate result."""
        insights = []

        # Extract from final answer
        if hasattr(result, "final_answer") and result.final_answer:
            insights.append(f"Conclusion: {result.final_answer[:200]}")

        # Extract from critiques
        if hasattr(result, "critiques"):
            for critique in result.critiques[:3]:
                if hasattr(critique, "summary") and critique.summary:
                    insights.append(f"Insight: {critique.summary[:150]}")

        # Extract consensus points
        if hasattr(result, "consensus_reached") and result.consensus_reached:
            insights.append("Consensus was reached among participants.")

        return insights[:5]  # Limit to 5 insights

    def _build_debate_context(self, result: DebateResult) -> str:
        """Build full context from debate result."""
        parts = []

        if hasattr(result, "task"):
            parts.append(f"Task: {result.task}")

        if hasattr(result, "messages"):
            for msg in result.messages[:20]:  # Limit messages
                agent = getattr(msg, "agent", "unknown")
                content = getattr(msg, "content", "")[:500]
                parts.append(f"{agent}: {content}")

        if hasattr(result, "final_answer"):
            parts.append(f"Final Answer: {result.final_answer}")

        return "\n\n".join(parts)

    async def _compress_context(self, context: str) -> str:
        """Compress context using RLM.

        Prioritizes AragoraRLM (routes to TRUE RLM when available),
        falls back to HierarchicalCompressor, then to simple truncation.
        """
        if not context:
            return ""

        # PRIMARY: Try AragoraRLM (routes to TRUE RLM if available)
        rlm = await self._get_rlm()
        if rlm:
            try:
                logger.debug(
                    "[CrossDebateMemory] Using AragoraRLM for compression "
                    "(routes to TRUE RLM if available)"
                )
                result = await rlm.compress_and_query(
                    query="Create a concise summary of this debate context",
                    content=context,
                    source_type="debate_memory",
                )
                if result.answer and len(result.answer) < len(context):
                    approach = "TRUE RLM" if result.used_true_rlm else "compression fallback"
                    logger.debug(
                        "[CrossDebateMemory] Compressed %s -> %s chars via %s",
                        len(context),
                        len(result.answer),
                        approach,
                    )
                    return result.answer
            except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                logger.warning("[CrossDebateMemory] AragoraRLM compression failed: %s", e)

        # FALLBACK: Try HierarchicalCompressor directly
        compressor = await self._get_compressor()
        if compressor:
            try:
                logger.debug(
                    "[CrossDebateMemory] Falling back to HierarchicalCompressor "
                    "(compression-only, no TRUE RLM)"
                )
                result = await compressor.compress(
                    context,
                    source_type="debate_memory",
                    max_levels=self.config.compression_levels,
                )

                if result and result.context:
                    from aragora.rlm.types import AbstractionLevel

                    return result.context.get_at_level(AbstractionLevel.SUMMARY) or context[:2000]
            except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                logger.warning("[CrossDebateMemory] HierarchicalCompressor failed: %s", e)

        # FINAL FALLBACK: Simple truncation
        logger.debug("[CrossDebateMemory] All RLM approaches failed, using simple truncation")
        return context[:2000]

    async def get_relevant_context(
        self,
        task: str,
        domain: str | None = None,
        max_tokens: int = 2000,
        include_tiers: list[MemoryTier] | None = None,
    ) -> str:
        """
        Get relevant context from past debates.

        Args:
            task: The current task/question
            domain: Optional domain filter
            max_tokens: Maximum tokens to return
            include_tiers: Tiers to include (default: all)

        Returns:
            Formatted context from relevant past debates
        """
        await self.initialize()

        tiers = include_tiers or [MemoryTier.HOT, MemoryTier.WARM, MemoryTier.COLD]
        relevant_entries = []

        # Score entries by relevance
        task_words = set(task.lower().split())

        # Take a snapshot under lock to prevent race conditions with concurrent writes
        async with self._lock:
            snapshot = list(self._entries.values())

        # Process snapshot without lock (safe read-only iteration)
        for entry in snapshot:
            if entry.tier not in tiers:
                continue

            if domain and entry.domain != domain:
                continue

            # Score by word overlap
            entry_words = set(entry.task.lower().split())
            overlap = len(task_words & entry_words)

            if overlap > 0:
                relevant_entries.append((overlap, entry))

        # Sort by relevance
        relevant_entries.sort(reverse=True, key=lambda x: x[0])

        # Build context within token budget
        parts = []
        tokens_used = 0
        accessed_entries = []

        for _, entry in relevant_entries[:10]:
            # Get token budget based on tier
            tier_budget = {
                MemoryTier.HOT: self.config.hot_token_budget,
                MemoryTier.WARM: self.config.warm_token_budget,
                MemoryTier.COLD: self.config.cold_token_budget,
                MemoryTier.ARCHIVE: 200,
            }.get(entry.tier, 500)

            available = min(tier_budget, max_tokens - tokens_used)
            if available <= 0:
                break

            # Format entry
            entry_text = self._format_entry(entry, available)
            entry_tokens = self._estimate_tokens(entry_text)

            if tokens_used + entry_tokens <= max_tokens:
                parts.append(entry_text)
                tokens_used += entry_tokens
                accessed_entries.append(entry)

        # Update access tracking under lock (safe mutation)
        if accessed_entries:
            async with self._lock:
                now = datetime.now()
                for entry in accessed_entries:
                    # Verify entry still exists (may have been removed concurrently)
                    if entry.debate_id in self._entries:
                        entry.access_count += 1
                        entry.last_accessed = now

        # Optionally enrich with Knowledge Mound insights
        if self.config.enable_km_integration:
            km_results = await self._query_km_debates(
                topic=task,
                domain=domain,
                limit=self.config.km_max_results,
            )
            if km_results:
                km_section = self._format_km_results(km_results, max_tokens - tokens_used)
                if km_section:
                    parts.append(km_section)

        return "\n\n---\n\n".join(parts)

    async def query_past_debates(
        self,
        query: str,
        max_debates: int = 5,
        strategy: str = "auto",
    ) -> str:
        """
        Query past debates using AragoraRLM (routes to TRUE RLM when available).

        When official RLM is installed, uses TRUE RLM (REPL-based approach) where
        context is stored as a Python variable and the model writes code to
        programmatically examine/grep/partition the context.

        When official RLM is unavailable, AragoraRLM falls back to compression-based
        approach. If that fails, falls back to keyword-based search.

        Args:
            query: Natural language query about past debates
            max_debates: Maximum number of debates to include in context
            strategy: RLM strategy (auto, peek, grep, partition_map)

        Returns:
            Answer to the query based on past debate context

        Example:
            >>> answer = await memory.query_past_debates(
            ...     "What consensus was reached about API design?",
            ...     max_debates=10,
            ... )
        """
        await self.initialize()

        # Try AragoraRLM (routes to TRUE RLM if available, compression fallback otherwise)
        rlm = await self._get_rlm()
        if rlm:
            try:
                # Build context string
                context_str = self._build_rlm_context(max_debates)
                if not context_str:
                    return "No past debates available."

                # Create RLMContext object for AragoraRLM
                from aragora.rlm.types import RLMContext

                context = RLMContext(
                    original_content=context_str,
                    original_tokens=len(context_str) // 4,
                    source_type="debate_memory",
                )

                # Query using AragoraRLM (routes to TRUE RLM if available)
                result = await rlm.query(query, context, strategy=strategy)

                # Log which approach was used
                if result.used_true_rlm:
                    logger.info(
                        "[CrossDebateMemory] query_past_debates used TRUE RLM (REPL-based), strategy=%s",
                        strategy,
                    )
                elif result.used_compression_fallback:
                    logger.info(
                        "[CrossDebateMemory] query_past_debates used compression fallback, strategy=%s",
                        strategy,
                    )

                return result.answer if hasattr(result, "answer") else str(result)

            except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                logger.warning("[CrossDebateMemory] AragoraRLM query failed, using fallback: %s", e)

        # FINAL FALLBACK: keyword-based search on compressed context
        logger.debug("[CrossDebateMemory] Using keyword-based fallback search")
        return self._fallback_query(query, max_debates)

    def _build_rlm_context(self, max_debates: int = 5) -> str:
        """Build context string for official RLM REPL."""
        # Take snapshot to avoid race conditions with concurrent modifications
        # (dict.values() returns a view that can change during iteration)
        entries_snapshot = list(self._entries.values())

        # Get most relevant entries by recency
        entries = sorted(
            entries_snapshot,
            key=lambda e: e.timestamp,
            reverse=True,
        )[:max_debates]

        if not entries:
            return ""

        parts = []
        for entry in entries:
            parts.append(f"""
## Debate: {entry.task}
Date: {entry.timestamp.strftime("%Y-%m-%d")}
Participants: {", ".join(entry.participants)}
Consensus: {"Yes" if entry.consensus_reached else "No"}

### Key Insights:
{chr(10).join(f"- {i}" for i in entry.key_insights)}

### Conclusion:
{entry.final_answer}

### Context:
{entry.compressed_context}
""")
        return "\n---\n".join(parts)

    def _fallback_query(self, query: str, max_debates: int = 5) -> str:
        """Keyword-based search fallback when official RLM unavailable."""
        query_terms = set(query.lower().split())
        relevant_entries = []

        # Take snapshot to avoid race conditions with concurrent modifications
        entries_snapshot = list(self._entries.values())
        for entry in entries_snapshot:
            # Score by keyword overlap
            entry_text = f"{entry.task} {entry.final_answer} {' '.join(entry.key_insights)}"
            entry_words = set(entry_text.lower().split())
            overlap = len(query_terms & entry_words)

            if overlap > 0:
                relevant_entries.append((overlap, entry))

        # Sort by relevance
        relevant_entries.sort(reverse=True, key=lambda x: x[0])

        if not relevant_entries:
            return "No relevant past debates found for this query."

        # Build response from top matches
        parts = [f"Found {len(relevant_entries[:max_debates])} relevant past debates:"]
        for _, entry in relevant_entries[:max_debates]:
            parts.append(f"""
**{entry.task}** ({entry.timestamp.strftime("%Y-%m-%d")})
Consensus: {"Yes" if entry.consensus_reached else "No"}
Key insight: {entry.key_insights[0] if entry.key_insights else "N/A"}
""")

        return "\n".join(parts)

    def _format_entry(self, entry: DebateMemoryEntry, max_tokens: int) -> str:
        """Format a memory entry for context."""
        max_chars = max_tokens * 4

        parts = [
            f"## Previous Debate: {entry.task[:100]}",
            f"Date: {entry.timestamp.strftime('%Y-%m-%d')}",
            f"Consensus: {'Yes' if entry.consensus_reached else 'No'}",
        ]

        if entry.key_insights:
            parts.append("Key Insights:")
            for insight in entry.key_insights[:3]:
                parts.append(f"- {insight}")

        if entry.final_answer:
            answer_preview = entry.final_answer[:500]
            parts.append(f"Conclusion: {answer_preview}")

        result = "\n".join(parts)
        return result[:max_chars]

    def _format_km_results(
        self,
        km_results: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        """Format Knowledge Mound results for context injection.

        Args:
            km_results: Results from _query_km_debates
            max_tokens: Token budget for this section

        Returns:
            Formatted string with KM insights
        """
        if not km_results or max_tokens <= 0:
            return ""

        max_chars = max_tokens * 4
        parts = ["## Knowledge Mound Insights"]

        for result in km_results:
            if len("\n".join(parts)) >= max_chars:
                break

            entry_parts = [
                f"\n### {result.get('topic', 'Unknown Topic')[:80]}",
            ]

            if result.get("consensus_reached"):
                entry_parts.append("  Consensus: Yes")
            else:
                entry_parts.append("  Consensus: No")

            conclusion = result.get("conclusion", "")
            if conclusion:
                entry_parts.append(f"  Conclusion: {conclusion[:200]}")

            insights = result.get("key_insights", [])
            if insights:
                entry_parts.append("  Insights:")
                for insight in insights[:2]:
                    entry_parts.append(f"    - {insight[:100]}")

            parts.extend(entry_parts)

        formatted = "\n".join(parts)
        return formatted[:max_chars]

    async def _manage_memory_limits(self) -> None:
        """Manage memory limits and tier transitions."""
        datetime.now()

        # Update tiers based on age
        for entry in self._entries.values():
            new_tier = self._determine_tier(entry.timestamp)
            if new_tier != entry.tier:
                entry.tier = new_tier

                # Recompress if needed
                if new_tier in [MemoryTier.COLD, MemoryTier.ARCHIVE]:
                    # Further compress for cold storage
                    entry.compressed_context = entry.compressed_context[:500]
                    entry.token_count = self._estimate_tokens(entry.compressed_context)

        # Enforce limits per tier
        tier_counts: dict[MemoryTier, list[DebateMemoryEntry]] = {tier: [] for tier in MemoryTier}

        for entry in self._entries.values():
            tier_counts[entry.tier].append(entry)

        # Remove excess entries (oldest first)
        limits = {
            MemoryTier.HOT: self.config.max_hot_entries,
            MemoryTier.WARM: self.config.max_warm_entries,
            MemoryTier.COLD: self.config.max_cold_entries,
            MemoryTier.ARCHIVE: self.config.max_entries
            - sum(
                [
                    self.config.max_hot_entries,
                    self.config.max_warm_entries,
                    self.config.max_cold_entries,
                ]
            ),
        }

        for tier, entries in tier_counts.items():
            limit = limits.get(tier, 100)
            if len(entries) > limit:
                # Sort by last accessed, remove least accessed
                entries.sort(key=lambda e: e.last_accessed or e.timestamp)
                to_remove = entries[: len(entries) - limit]
                for entry in to_remove:
                    del self._entries[entry.debate_id]

    async def _save_to_disk(self) -> None:
        """Save memory to disk."""
        if not self.config.storage_path:
            return

        try:
            self.config.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            self.config.storage_path.write_text(json.dumps(data, indent=2))
        except (OSError, PermissionError) as e:
            logger.error("Failed to save cross-debate memory (I/O): %s", e)
        except (TypeError, ValueError) as e:
            logger.error("Failed to save cross-debate memory (serialization): %s", e)

    async def _load_from_disk(self) -> None:
        """Load memory from disk."""
        if not self.config.storage_path or not self.config.storage_path.exists():
            return

        try:
            data = json.loads(self.config.storage_path.read_text())
            for entry_data in data.get("entries", []):
                entry = DebateMemoryEntry.from_dict(entry_data)
                self._entries[entry.debate_id] = entry
        except (OSError, PermissionError) as e:
            logger.error("Failed to load cross-debate memory (I/O): %s", e)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            logger.error("Failed to load cross-debate memory (parse): %s", e)

    def get_statistics(self) -> dict[str, Any]:
        """Get memory statistics."""
        tier_stats = {tier.value: 0 for tier in MemoryTier}
        total_tokens = 0

        # Take snapshot to avoid race conditions with concurrent modifications
        entries_snapshot = list(self._entries.values())
        for entry in entries_snapshot:
            tier_stats[entry.tier.value] += 1
            total_tokens += entry.token_count

        return {
            "total_entries": len(entries_snapshot),
            "tier_distribution": tier_stats,
            "total_tokens": total_tokens,
        }

    async def clear(self) -> None:
        """Clear all memory."""
        async with self._lock:
            self._entries.clear()
            if self.config.persist_to_disk and self.config.storage_path:
                self.config.storage_path.unlink(missing_ok=True)
