"""
Hierarchical Context Compressor for RLM.

Builds multi-level abstraction trees from long content, enabling
efficient navigation from high-level summaries to detailed content.

Performance optimizations:
- LRU cache with configurable size and TTL
- Parallel sub-LM calls for batch compression
- Async semaphore for concurrency control
- Content-hash based deduplication
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from .types import (
    AbstractionLevel,
    AbstractionNode,
    CompressionResult,
    RLMConfig,
    RLMContext,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Entry in the compression cache with TTL."""

    context: RLMContext
    created_at: float
    access_count: int = 0


class LRUCompressionCache:
    """
    LRU cache for compression results with TTL expiration.

    Performance features:
    - O(1) lookups and insertions
    - Automatic eviction of oldest entries
    - TTL-based expiration
    - Access tracking for metrics
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600.0):
        """
        Initialize the cache.

        Args:
            max_size: Maximum number of entries to cache
            ttl_seconds: Time-to-live for cache entries (default 1 hour)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> RLMContext | None:
        """Get a value from the cache, returning None if expired or missing."""
        if key not in self._cache:
            self._misses += 1
            return None

        entry = self._cache[key]

        # Check TTL
        if time.time() - entry.created_at > self.ttl_seconds:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        entry.access_count += 1
        self._hits += 1

        return entry.context

    def set(self, key: str, context: RLMContext) -> None:
        """Set a value in the cache, evicting old entries if necessary."""
        # Remove oldest if at capacity
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        self._cache[key] = CacheEntry(
            context=context,
            created_at=time.time(),
        )

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }


# Global compression cache (LRU with 1-hour TTL)
_compression_cache = LRUCompressionCache(max_size=1000, ttl_seconds=3600.0)

# Semaphore for controlling concurrent LLM calls
_call_semaphore: asyncio.Semaphore | None = None


def get_call_semaphore(max_concurrent: int = 10) -> asyncio.Semaphore:
    """Get or create the global semaphore for LLM call concurrency control."""
    global _call_semaphore
    if _call_semaphore is None:
        _call_semaphore = asyncio.Semaphore(max_concurrent)
    return _call_semaphore


@dataclass
class ChunkInfo:
    """Information about a chunk for processing."""

    index: int
    content: str
    token_count: int
    start_char: int
    end_char: int


class HierarchicalCompressor:
    """
    Builds hierarchical abstraction trees from long content.

    Compression levels:
    - Level 0 (FULL): Original content split into chunks
    - Level 1 (DETAILED): 50% compression, key details preserved
    - Level 2 (SUMMARY): 80% compression, main points only
    - Level 3 (ABSTRACT): 95% compression, high-level overview
    - Level 4 (METADATA): Tags and routing info only

    The compressor uses LLM calls to generate semantically meaningful
    summaries at each level, rather than simple truncation.
    """

    # Prompts for compression at each level
    COMPRESSION_PROMPTS = {
        AbstractionLevel.DETAILED: """Summarize the following content, preserving key details and specific information.
Keep approximately 50% of the original length. Maintain technical accuracy.

Content:
{content}

Detailed summary:""",
        AbstractionLevel.SUMMARY: """Summarize the following content into key points.
Keep approximately 20% of the original length. Focus on main ideas and conclusions.

Content:
{content}

Key points summary:""",
        AbstractionLevel.ABSTRACT: """Provide a brief high-level abstract of the following content.
Keep to 2-3 sentences maximum. Capture the essential theme and purpose.

Content:
{content}

Abstract:""",
        AbstractionLevel.METADATA: """Extract metadata tags from the following content.
Return as a comma-separated list of key topics, entities, and themes.

Content:
{content}

Tags:""",
    }

    # Debate-specific prompts
    DEBATE_COMPRESSION_PROMPTS = {
        AbstractionLevel.DETAILED: """Summarize this debate round, preserving:
- Each agent's key arguments
- Specific critiques raised
- Points of agreement and disagreement

Debate round:
{content}

Detailed summary:""",
        AbstractionLevel.SUMMARY: """Summarize the key points from this debate:
- Main positions taken
- Critical disagreements
- Emerging consensus (if any)

Debate:
{content}

Summary:""",
        AbstractionLevel.ABSTRACT: """In 1-2 sentences, what was decided or concluded in this debate?

Debate:
{content}

Conclusion:""",
    }

    def __init__(
        self,
        config: RLMConfig | None = None,
        agent_call: Callable[[str, str], str] | None = None,
        event_emitter: Any | None = None,
    ):
        """
        Initialize the compressor.

        Args:
            config: RLM configuration
            agent_call: Callback to invoke LLM for compression
                       Signature: (prompt, model) -> response
            event_emitter: Optional event emitter for cross-subsystem integration
        """
        self.config = config or RLMConfig()
        self.agent_call = agent_call
        self._event_emitter = event_emitter

    async def compress(
        self,
        content: str,
        source_type: str = "text",
        max_levels: int = 4,
    ) -> CompressionResult:
        """
        Compress content into hierarchical representation.

        Args:
            content: Original content to compress
            source_type: Type of content (text, debate, code, document)
            max_levels: Maximum abstraction levels to create

        Returns:
            CompressionResult with hierarchical context

        Raises:
            ValueError: If content exceeds max_content_bytes limit
        """
        start_time = time.time()

        # Production hardening: Validate content size before processing
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > self.config.max_content_bytes:
            logger.warning(
                "Content size %s bytes exceeds limit %s bytes",
                content_bytes,
                self.config.max_content_bytes,
            )
            raise ValueError(
                f"Content size ({content_bytes:,} bytes) exceeds maximum allowed "
                f"({self.config.max_content_bytes:,} bytes). Consider chunking the content."
            )

        # Check cache (LRU with TTL)
        cache_key = self._cache_key(content, source_type, max_levels)
        if self.config.cache_compressions:
            cached = _compression_cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for compression: %s...", cache_key[:16])
                return CompressionResult(
                    context=cached,
                    original_tokens=cached.original_tokens,
                    compressed_tokens={},
                    compression_ratio={},
                    time_seconds=0.0,
                    sub_calls_made=0,
                    cache_hits=1,
                    estimated_fidelity=0.9,
                    key_topics_extracted=[],
                )

        # Estimate token count
        original_tokens = self._count_tokens(content)

        # Build base context
        context = RLMContext(
            original_content=content,
            original_tokens=original_tokens,
            levels={},
            nodes_by_id={},
            source_type=source_type,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        sub_calls = 0
        compressed_tokens: dict[AbstractionLevel, int] = {}
        compression_ratios: dict[AbstractionLevel, float] = {}

        # Level 0: Chunk the original content
        chunks = self._chunk_content(content)
        level_0_nodes = []
        for chunk in chunks:
            node = AbstractionNode(
                id=f"L0_{chunk.index}",
                level=AbstractionLevel.FULL,
                content=chunk.content,
                token_count=chunk.token_count,
                source_range=(chunk.start_char, chunk.end_char),
            )
            level_0_nodes.append(node)
            context.nodes_by_id[node.id] = node

        context.levels[AbstractionLevel.FULL] = level_0_nodes
        compressed_tokens[AbstractionLevel.FULL] = original_tokens
        compression_ratios[AbstractionLevel.FULL] = 1.0

        # Select prompts based on source type
        prompts = (
            self.DEBATE_COMPRESSION_PROMPTS if source_type == "debate" else self.COMPRESSION_PROMPTS
        )

        # Build higher abstraction levels
        previous_nodes = level_0_nodes

        for level in [
            AbstractionLevel.DETAILED,
            AbstractionLevel.SUMMARY,
            AbstractionLevel.ABSTRACT,
            AbstractionLevel.METADATA,
        ]:
            if level.value > max_levels:
                break

            if level not in prompts:
                continue

            # Compress from previous level
            level_nodes, calls = await self._compress_level(
                previous_nodes,
                level,
                prompts[level],
                context,
            )
            sub_calls += calls

            if level_nodes:
                context.levels[level] = level_nodes
                for node in level_nodes:
                    context.nodes_by_id[node.id] = node

                level_tokens = sum(n.token_count for n in level_nodes)
                compressed_tokens[level] = level_tokens
                compression_ratios[level] = (
                    level_tokens / original_tokens if original_tokens > 0 else 0
                )

                previous_nodes = level_nodes

        # Extract key topics from metadata level
        key_topics: list[str] = []
        if AbstractionLevel.METADATA in context.levels:
            for node in context.levels[AbstractionLevel.METADATA]:
                key_topics.extend(
                    topic.strip() for topic in node.content.split(",") if topic.strip()
                )

        # Cache result (LRU with TTL)
        if self.config.cache_compressions:
            _compression_cache.set(cache_key, context)

        elapsed = time.time() - start_time

        result = CompressionResult(
            context=context,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratios,
            time_seconds=elapsed,
            sub_calls_made=sub_calls,
            cache_hits=0,
            estimated_fidelity=self._estimate_fidelity(compression_ratios),
            key_topics_extracted=key_topics[:20],
        )

        # Emit compression event for cross-subsystem integration
        self._emit_compression_event(result, source_type, key_topics)

        return result

    async def compress_debate_history(
        self,
        rounds: list[dict[str, Any]],
    ) -> CompressionResult:
        """
        Compress debate history with round-aware structure.

        Args:
            rounds: List of debate rounds, each with:
                - round_number: int
                - proposals: list of proposal dicts
                - critiques: list of critique dicts
                - votes: optional voting results

        Returns:
            CompressionResult with debate-structured hierarchy
        """
        # Format rounds into structured text
        formatted_parts = []
        for r in rounds:
            round_text = f"## Round {r.get('round_number', '?')}\n\n"

            # Add proposals
            for p in r.get("proposals", []):
                agent = p.get("agent", "unknown")
                content = p.get("content", "")
                round_text += f"### {agent}'s Proposal\n{content}\n\n"

            # Add critiques
            for c in r.get("critiques", []):
                critic = c.get("critic", "unknown")
                target = c.get("target", "unknown")
                content = c.get("content", "")
                round_text += f"**{critic} → {target}**: {content}\n\n"

            # Add votes if present
            if "votes" in r:
                round_text += f"**Votes**: {r['votes']}\n\n"

            formatted_parts.append(round_text)

        full_content = "\n---\n".join(formatted_parts)

        return await self.compress(full_content, source_type="debate")

    async def _compress_level(
        self,
        source_nodes: list[AbstractionNode],
        target_level: AbstractionLevel,
        prompt_template: str,
        context: RLMContext,
    ) -> tuple[list[AbstractionNode], int]:
        """
        Compress nodes from one level to a higher abstraction level.

        Returns:
            (list of new nodes, number of LLM calls made)
        """
        if not self.agent_call:
            # Fallback: simple truncation
            logger.warning("No agent_call configured, using truncation fallback")
            return self._truncation_fallback(source_nodes, target_level, context), 0

        # Group source nodes for batch compression
        # Higher levels compress more nodes together
        group_size = {
            AbstractionLevel.DETAILED: 3,
            AbstractionLevel.SUMMARY: 5,
            AbstractionLevel.ABSTRACT: 10,
            AbstractionLevel.METADATA: len(source_nodes),  # All at once
        }.get(target_level, 5)

        if not source_nodes or group_size < 1:
            return [], 0

        groups = [source_nodes[i : i + group_size] for i in range(0, len(source_nodes), group_size)]

        new_nodes = []
        calls = 0

        # Process groups (optionally in parallel)
        if self.config.parallel_sub_calls and len(groups) > 1:
            tasks = [
                self._compress_group(group, i, target_level, prompt_template, context)
                for i, group in enumerate(groups)
            ]
            results = await asyncio.gather(*tasks)
            for node, c in results:
                if node:
                    new_nodes.append(node)
                calls += c
        else:
            for i, group in enumerate(groups):
                node, c = await self._compress_group(
                    group, i, target_level, prompt_template, context
                )
                if node:
                    new_nodes.append(node)
                calls += c

        # Link parent-child relationships
        for node in new_nodes:
            for child_id in node.source_chunks:
                child = context.nodes_by_id.get(child_id)
                if child:
                    child.parent_id = node.id

        return new_nodes, calls

    async def _compress_group(
        self,
        nodes: list[AbstractionNode],
        group_index: int,
        target_level: AbstractionLevel,
        prompt_template: str,
        context: RLMContext,
    ) -> tuple[AbstractionNode | None, int]:
        """Compress a group of nodes into a single higher-level node."""
        # Combine content from nodes
        combined = "\n\n".join(node.content for node in nodes)

        # Apply compression prompt
        prompt = prompt_template.format(content=combined)

        try:
            agent_call = self.agent_call
            if agent_call is None:
                raise RuntimeError("agent_call is required for LLM compression")

            # Use semaphore to control concurrent LLM calls
            semaphore = get_call_semaphore(self.config.max_sub_calls)
            async with semaphore:
                result = agent_call(prompt, self.config.root_model)
                if inspect.isawaitable(result):
                    response = await result
                else:
                    response = result

            # Create new node
            node = AbstractionNode(
                id=f"L{target_level.value}_{group_index}",
                level=target_level,
                content=response,
                token_count=self._count_tokens(response),
                source_chunks=[n.id for n in nodes],
                child_ids=[n.id for n in nodes],
            )

            # Extract key topics if present in response
            if target_level == AbstractionLevel.METADATA:
                node.key_topics = [t.strip() for t in response.split(",") if t.strip()]

            return node, 1

        except (RuntimeError, ValueError, TimeoutError, ConnectionError, OSError) as e:
            logger.error("Compression failed for group %s: %s", group_index, e)
            # Fallback to truncation
            truncated = combined[: self.config.target_tokens * 4]
            node = AbstractionNode(
                id=f"L{target_level.value}_{group_index}",
                level=target_level,
                content=truncated + "..." if len(combined) > len(truncated) else truncated,
                token_count=self._count_tokens(truncated),
                source_chunks=[n.id for n in nodes],
                child_ids=[n.id for n in nodes],
            )
            return node, 0

    def _truncation_fallback(
        self,
        source_nodes: list[AbstractionNode],
        target_level: AbstractionLevel,
        context: RLMContext,
    ) -> list[AbstractionNode]:
        """Simple truncation fallback when no LLM available."""
        compression = {
            AbstractionLevel.DETAILED: 0.5,
            AbstractionLevel.SUMMARY: 0.2,
            AbstractionLevel.ABSTRACT: 0.05,
            AbstractionLevel.METADATA: 0.01,
        }.get(target_level, 0.5)

        new_nodes = []
        for i, node in enumerate(source_nodes):
            target_len = int(len(node.content) * compression)
            truncated = node.content[:target_len]
            if len(node.content) > target_len:
                truncated += "..."

            new_node = AbstractionNode(
                id=f"L{target_level.value}_{i}",
                level=target_level,
                content=truncated,
                token_count=self._count_tokens(truncated),
                source_chunks=[node.id],
                child_ids=[node.id],
            )
            new_nodes.append(new_node)

        return new_nodes

    def _chunk_content(self, content: str) -> list[ChunkInfo]:
        """Split content into chunks."""
        chunks = []
        chunk_size = self.config.target_tokens * 4  # ~4 chars per token
        overlap = self.config.overlap_tokens * 4

        i = 0
        chunk_idx = 0
        while i < len(content):
            end = min(i + chunk_size, len(content))

            # Try to break at sentence boundary
            if end < len(content):
                for boundary in [". ", ".\n", "\n\n", "\n", " "]:
                    boundary_pos = content.rfind(boundary, i + chunk_size // 2, end)
                    if boundary_pos > i:
                        end = boundary_pos + len(boundary)
                        break

            chunk_content = content[i:end]
            chunks.append(
                ChunkInfo(
                    index=chunk_idx,
                    content=chunk_content,
                    token_count=self._count_tokens(chunk_content),
                    start_char=i,
                    end_char=end,
                )
            )

            i = end - overlap if end < len(content) else end
            chunk_idx += 1

        return chunks

    def _count_tokens(self, text: str) -> int:
        """Estimate token count."""
        # Rough approximation: ~4 chars per token
        return len(text) // 4

    def _cache_key(self, content: str, source_type: str, max_levels: int) -> str:
        """Generate cache key for content."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"{source_type}_{max_levels}_{content_hash}"

    def _estimate_fidelity(self, compression_ratios: dict[AbstractionLevel, float]) -> float:
        """Estimate semantic fidelity based on compression ratios."""
        # Higher compression means lower fidelity
        # But RLM-based compression preserves more than simple truncation
        if not compression_ratios:
            return 1.0

        min_ratio = min(compression_ratios.values())
        # Assume RLM preserves ~80% of semantic content even at high compression
        return max(0.4, 0.8 + (0.2 * min_ratio))

    def _emit_compression_event(
        self,
        result: CompressionResult,
        source_type: str,
        key_topics: list[str],
    ) -> None:
        """Emit RLM_COMPRESSION_COMPLETE event for cross-subsystem integration."""
        if self._event_emitter is None:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            # Only emit for significant compressions (high value score)
            value_score = result.estimated_fidelity
            if value_score < 0.7:  # Skip low-fidelity compressions
                return

            # Get the best compression ratio achieved
            best_ratio = 1.0
            if result.compression_ratio:
                best_ratio = min(result.compression_ratio.values())

            event = StreamEvent(
                type=StreamEventType.RLM_COMPRESSION_COMPLETE,
                data={
                    "original_tokens": result.original_tokens,
                    "best_compression_ratio": best_ratio,
                    "value_score": value_score,
                    "source_type": source_type,
                    "content_markers": key_topics[:10],  # Top 10 topics as markers
                    "sub_calls_made": result.sub_calls_made,
                    "time_seconds": result.time_seconds,
                    "levels_created": len(result.compression_ratio),
                },
            )

            if hasattr(self._event_emitter, "emit"):
                self._event_emitter.emit(event)
            elif hasattr(self._event_emitter, "publish"):
                self._event_emitter.publish(event)
            elif callable(self._event_emitter):
                self._event_emitter(event)

            logger.debug(
                f"Emitted RLM_COMPRESSION_COMPLETE: ratio={best_ratio:.2f}, "
                f"fidelity={value_score:.2f}, topics={len(key_topics)}"
            )

        except ImportError:
            pass  # Events module not available
        except (AttributeError, TypeError, RuntimeError, ValueError) as e:
            logger.warning("Failed to emit compression event: %s", e)


def clear_compression_cache() -> None:
    """Clear the compression cache."""
    _compression_cache.clear()


def get_compression_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the compression cache.

    Returns:
        Dict with cache size, hit rate, and other metrics
    """
    return _compression_cache.get_stats()


def configure_compression_cache(
    max_size: int = 1000,
    ttl_seconds: float = 3600.0,
) -> None:
    """
    Configure the compression cache.

    Args:
        max_size: Maximum number of entries to cache
        ttl_seconds: Time-to-live for cache entries
    """
    global _compression_cache
    _compression_cache = LRUCompressionCache(
        max_size=max_size,
        ttl_seconds=ttl_seconds,
    )
