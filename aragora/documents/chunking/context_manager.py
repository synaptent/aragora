"""
Large context manager for document processing.

Handles intelligent context construction for different model capabilities:
- Full context for models with large context windows (Gemini 3 Pro: 1M tokens)
- RAG-based retrieval for smaller context models (Claude: 200K, GPT-4: 128K)
- Hybrid strategies that combine both approaches

Usage:
    from aragora.documents.chunking.context_manager import ContextManager

    manager = ContextManager()
    context = await manager.build_context(
        document_ids=["doc1", "doc2"],
        query="Find security vulnerabilities",
        model="gemini-3-pro",
        max_tokens=500000,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.config.model_pins import GPT6_ASTRA_DIRECT
from aragora.documents.models import DocumentChunk, MODEL_TOKEN_LIMITS
from aragora.documents.chunking.token_counter import TokenCounter, get_token_counter
from aragora.models.catalog import CATALOG
from aragora.models.pricing_mirror import per_mtok_rows

logger = logging.getLogger(__name__)

# Pricing in USD per 1M tokens, consulted by ``ContextManager.estimate_cost``.
# The hand-written rows are HISTORICAL snapshots kept so a preview for an
# archived document run still quotes the price that run was billed at; the
# generated rows come from the catalog (one per spelling of every active
# row) so a preview for a CURRENT model no longer falls back to the
# module's $5/$15 guess. Module-level rather than function-local (where it
# used to live) so the table is inspectable and testable, and the catalog
# projection is built once instead of on every call.
_LEGACY_PRICING: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-pro": {"input": 1.25, "output": 5.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3.1-pro": {"input": 1.25, "output": 5.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
}

PRICING: dict[str, dict[str, float]] = {**_LEGACY_PRICING, **per_mtok_rows()}

# Context-window band boundaries, in tokens.
LARGE_CONTEXT_TOKENS = 1_000_000
MEDIUM_CONTEXT_TOKENS = 128_000


def _catalog_context_models(low: int, high: int | None) -> set[str]:
    """Every spelling of every ACTIVE catalog row whose ``context_window``
    is at least ``low`` and (when ``high`` is given) below it."""
    return {
        spelling
        for spec in CATALOG.values()
        if not spec.retired
        and spec.context_window >= low
        and (high is None or spec.context_window < high)
        for spelling in spec.all_ids()
    }


class ContextStrategy(str, Enum):
    """Strategy for building model context."""

    FULL = "full"  # Include entire document(s)
    RAG = "rag"  # Use RAG retrieval
    HYBRID = "hybrid"  # Full context + RAG augmentation
    CHUNKED = "chunked"  # Process in sequential chunks
    AUTO = "auto"  # Automatically select best strategy


@dataclass
class ContextWindow:
    """A prepared context window for model consumption."""

    content: str
    token_count: int
    model: str
    strategy: ContextStrategy
    document_ids: list[str]
    chunk_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def utilization(self) -> float:
        """Return context window utilization (0-1)."""
        limit = MODEL_TOKEN_LIMITS.get(self.model, 128000)
        return self.token_count / limit

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "token_count": self.token_count,
            "model": self.model,
            "strategy": self.strategy.value,
            "document_ids": self.document_ids,
            "chunk_ids": self.chunk_ids,
            "utilization": self.utilization,
            "metadata": self.metadata,
        }


@dataclass
class ContextConfig:
    """Configuration for context building."""

    # Target model (affects strategy selection). Pinned to the catalog's
    # current OpenAI frontier: the previous default "gpt-4-turbo" is an
    # UPGRADES key, so the config's model depended on the upgrade map to
    # name anything live, and its 128K context limit under-sized every
    # window this config built (2026-09-05 merge-gate addendum on #9989).
    model: str = GPT6_ASTRA_DIRECT

    # Maximum tokens to use (None = use model's limit)
    max_tokens: int | None = None

    # Strategy override (None = auto-select)
    strategy: ContextStrategy | None = None

    # RAG settings
    rag_top_k: int = 20
    rag_min_score: float = 0.5

    # Reserved tokens for output
    output_reserve_tokens: int = 4096

    # Include metadata in context
    include_metadata: bool = True
    include_page_numbers: bool = True

    # Chunk ordering
    preserve_document_order: bool = True


class ContextManager:
    """
    Manages context construction for different model capabilities.

    Intelligently selects between full-context and RAG strategies
    based on document size and model limits.
    """

    # Models with large context windows (1M+ tokens). Historical spellings
    # kept (they are the only rows for models the catalog no longer carries)
    # plus every active catalog row whose context_window reaches 1M -- which
    # is now most of the frontier, and none of which this set named before
    # (2026-09-04 controller ruling, wave 3).
    LARGE_CONTEXT_MODELS = {
        "gemini-3-pro",
        "gemini-3-pro-preview",
        "gemini-3.1-pro",
        "gemini-1.5-pro",  # 2M tokens
    } | _catalog_context_models(LARGE_CONTEXT_TOKENS, None)

    # Models with context windows between 128K and 1M tokens.
    MEDIUM_CONTEXT_MODELS = {
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4o",
        "claude-3-opus",
        "claude-3-sonnet",
        "claude-3-haiku",
        "claude-3.5-sonnet",
    } | _catalog_context_models(MEDIUM_CONTEXT_TOKENS, LARGE_CONTEXT_TOKENS)

    def __init__(
        self,
        token_counter: TokenCounter | None = None,
        hybrid_searcher: Any | None = None,  # HybridSearcher
    ):
        """
        Initialize context manager.

        Args:
            token_counter: Token counter instance
            hybrid_searcher: Optional hybrid searcher for RAG
        """
        self.token_counter = token_counter or get_token_counter()
        self.hybrid_searcher = hybrid_searcher

    def select_strategy(
        self,
        total_tokens: int,
        model: str,
        config: ContextConfig | None = None,
    ) -> ContextStrategy:
        """
        Select optimal context strategy based on document size and model.

        Args:
            total_tokens: Total tokens in documents
            model: Target model name
            config: Optional configuration

        Returns:
            Recommended context strategy
        """
        config = config or ContextConfig(model=model)

        # If strategy is explicitly set, use it
        if config.strategy and config.strategy != ContextStrategy.AUTO:
            return config.strategy

        # Get model's context limit
        max_tokens = config.max_tokens or MODEL_TOKEN_LIMITS.get(model, 128000)
        available_tokens = max_tokens - config.output_reserve_tokens

        # Large context models can handle most documents fully
        if model in self.LARGE_CONTEXT_MODELS:
            if total_tokens <= available_tokens:
                return ContextStrategy.FULL
            elif total_tokens <= available_tokens * 2:
                return ContextStrategy.HYBRID
            else:
                return ContextStrategy.CHUNKED

        # Medium context models need RAG for larger documents
        if total_tokens <= available_tokens * 0.8:
            return ContextStrategy.FULL
        elif total_tokens <= available_tokens * 3:
            return ContextStrategy.RAG
        else:
            return ContextStrategy.CHUNKED

    def recommend_model(
        self,
        total_tokens: int,
        prefer_reasoning: bool = False,
    ) -> str:
        """
        Recommend best model for a given document size.

        Args:
            total_tokens: Total tokens in documents
            prefer_reasoning: Prefer models with strong reasoning

        Returns:
            Recommended model name
        """
        if total_tokens > 500000:
            # Need Gemini 3 Pro for very large documents
            return "gemini-3-pro"
        elif total_tokens > 100000:
            # Large but manageable
            if prefer_reasoning:
                return "claude-3.5-sonnet"
            return "gemini-3-pro"
        elif total_tokens > 50000:
            # Medium documents
            if prefer_reasoning:
                return "claude-3.5-sonnet"
            return "gpt-4-turbo"
        else:
            # Small documents - any model works
            if prefer_reasoning:
                return "claude-3.5-sonnet"
            return "gpt-4-turbo"

    async def build_context(
        self,
        chunks: list[DocumentChunk],
        query: str | None = None,
        config: ContextConfig | None = None,
    ) -> ContextWindow:
        """
        Build context window from document chunks.

        Args:
            chunks: List of document chunks
            query: Optional query for RAG filtering
            config: Context configuration

        Returns:
            Prepared context window
        """
        config = config or ContextConfig()

        # Calculate total tokens
        total_tokens = sum(c.token_count for c in chunks)

        # Select strategy
        strategy = self.select_strategy(total_tokens, config.model, config)

        logger.info(
            "Building context: %s tokens, strategy=%s, model=%s",
            total_tokens,
            strategy.value,
            config.model,
        )

        if strategy == ContextStrategy.FULL:
            return await self._build_full_context(chunks, config)
        elif strategy == ContextStrategy.RAG:
            return await self._build_rag_context(chunks, query, config)
        elif strategy == ContextStrategy.HYBRID:
            return await self._build_hybrid_context(chunks, query, config)
        elif strategy == ContextStrategy.CHUNKED:
            # Return first chunk that fits
            return await self._build_chunked_context(chunks, config)
        else:
            return await self._build_full_context(chunks, config)

    async def _build_full_context(
        self,
        chunks: list[DocumentChunk],
        config: ContextConfig,
    ) -> ContextWindow:
        """Build context with all chunks included."""
        if config.preserve_document_order:
            chunks = sorted(chunks, key=lambda c: (c.document_id, c.sequence))

        content_parts = []
        chunk_ids = []
        document_ids = set()

        for chunk in chunks:
            document_ids.add(chunk.document_id)
            chunk_ids.append(chunk.id)

            # Build chunk representation
            chunk_text = self._format_chunk(chunk, config)
            content_parts.append(chunk_text)

        content = "\n\n".join(content_parts)
        token_count = self.token_counter.count(content, config.model)

        return ContextWindow(
            content=content,
            token_count=token_count,
            model=config.model,
            strategy=ContextStrategy.FULL,
            document_ids=list(document_ids),
            chunk_ids=chunk_ids,
            metadata={
                "total_chunks": len(chunks),
                "strategy_reason": "document fits in context window",
            },
        )

    async def _build_rag_context(
        self,
        chunks: list[DocumentChunk],
        query: str | None,
        config: ContextConfig,
    ) -> ContextWindow:
        """Build context using RAG retrieval."""
        if not query:
            # Fall back to full context if no query
            logger.warning("RAG strategy requires query, falling back to truncated full context")
            return await self._build_truncated_context(chunks, config)

        if not self.hybrid_searcher:
            logger.warning("No hybrid searcher available, falling back to truncated full context")
            return await self._build_truncated_context(chunks, config)

        # Get document IDs for filtering
        document_ids = list({c.document_id for c in chunks})

        # Search for relevant chunks
        results = await self.hybrid_searcher.search(
            query=query,
            limit=config.rag_top_k,
            document_ids=document_ids,
        )

        # Build context from search results
        max_tokens = (
            config.max_tokens or MODEL_TOKEN_LIMITS.get(config.model, 128000)
        ) - config.output_reserve_tokens

        content_parts = []
        chunk_ids = []
        current_tokens = 0

        # Create chunk lookup
        chunk_map = {c.id: c for c in chunks}

        for result in results:
            if result.combined_score < config.rag_min_score:
                continue

            chunk = chunk_map.get(result.chunk_id)
            if not chunk:
                continue

            chunk_text = self._format_chunk(chunk, config)
            chunk_tokens = self.token_counter.count(chunk_text, config.model)

            if current_tokens + chunk_tokens > max_tokens:
                break

            content_parts.append(chunk_text)
            chunk_ids.append(chunk.id)
            current_tokens += chunk_tokens

        content = "\n\n".join(content_parts)

        return ContextWindow(
            content=content,
            token_count=current_tokens,
            model=config.model,
            strategy=ContextStrategy.RAG,
            document_ids=document_ids,
            chunk_ids=chunk_ids,
            metadata={
                "query": query,
                "retrieved_chunks": len(chunk_ids),
                "total_chunks": len(chunks),
                "strategy_reason": "document too large, using RAG retrieval",
            },
        )

    async def _build_hybrid_context(
        self,
        chunks: list[DocumentChunk],
        query: str | None,
        config: ContextConfig,
    ) -> ContextWindow:
        """Build context with full document + RAG augmentation."""
        # Start with truncated full context
        full_context = await self._build_truncated_context(chunks, config, reserve_ratio=0.3)

        if not query or not self.hybrid_searcher:
            return full_context

        # Get document IDs
        document_ids = list({c.document_id for c in chunks})

        # Search for highly relevant chunks not already included
        results = await self.hybrid_searcher.search(
            query=query,
            limit=config.rag_top_k,
            document_ids=document_ids,
        )

        # Calculate remaining token budget
        max_tokens = (
            config.max_tokens or MODEL_TOKEN_LIMITS.get(config.model, 128000)
        ) - config.output_reserve_tokens
        remaining_tokens = max_tokens - full_context.token_count

        # Add high-relevance chunks that aren't already included
        augmented_parts = []
        augmented_ids = []
        current_tokens = 0

        included_ids = set(full_context.chunk_ids)
        chunk_map = {c.id: c for c in chunks}

        for result in results:
            if result.chunk_id in included_ids:
                continue
            if result.combined_score < config.rag_min_score:
                continue

            chunk = chunk_map.get(result.chunk_id)
            if not chunk:
                continue

            chunk_text = self._format_chunk(chunk, config)
            chunk_tokens = self.token_counter.count(chunk_text, config.model)

            if current_tokens + chunk_tokens > remaining_tokens:
                break

            augmented_parts.append(f"[HIGHLY RELEVANT]\n{chunk_text}")
            augmented_ids.append(chunk.id)
            current_tokens += chunk_tokens

        # Combine full context with augmented chunks
        if augmented_parts:
            augmented_section = "\n\n--- ADDITIONAL RELEVANT CONTEXT ---\n\n" + "\n\n".join(
                augmented_parts
            )
            content = full_context.content + augmented_section
        else:
            content = full_context.content

        return ContextWindow(
            content=content,
            token_count=full_context.token_count + current_tokens,
            model=config.model,
            strategy=ContextStrategy.HYBRID,
            document_ids=document_ids,
            chunk_ids=full_context.chunk_ids + augmented_ids,
            metadata={
                "query": query,
                "base_chunks": len(full_context.chunk_ids),
                "augmented_chunks": len(augmented_ids),
                "total_chunks": len(chunks),
                "strategy_reason": "hybrid: full context + RAG augmentation",
            },
        )

    async def _build_chunked_context(
        self,
        chunks: list[DocumentChunk],
        config: ContextConfig,
    ) -> ContextWindow:
        """Build context for first chunk of sequential processing."""
        return await self._build_truncated_context(chunks, config)

    async def _build_truncated_context(
        self,
        chunks: list[DocumentChunk],
        config: ContextConfig,
        reserve_ratio: float = 0.0,
    ) -> ContextWindow:
        """Build context with truncation to fit token limit."""
        if config.preserve_document_order:
            chunks = sorted(chunks, key=lambda c: (c.document_id, c.sequence))

        max_tokens = (
            config.max_tokens or MODEL_TOKEN_LIMITS.get(config.model, 128000)
        ) - config.output_reserve_tokens
        max_tokens = int(max_tokens * (1 - reserve_ratio))

        content_parts = []
        chunk_ids = []
        document_ids = set()
        current_tokens = 0

        for chunk in chunks:
            chunk_text = self._format_chunk(chunk, config)
            chunk_tokens = self.token_counter.count(chunk_text, config.model)

            if current_tokens + chunk_tokens > max_tokens:
                break

            document_ids.add(chunk.document_id)
            chunk_ids.append(chunk.id)
            content_parts.append(chunk_text)
            current_tokens += chunk_tokens

        content = "\n\n".join(content_parts)

        return ContextWindow(
            content=content,
            token_count=current_tokens,
            model=config.model,
            strategy=ContextStrategy.FULL,
            document_ids=list(document_ids),
            chunk_ids=chunk_ids,
            metadata={
                "truncated": len(chunk_ids) < len(chunks),
                "included_chunks": len(chunk_ids),
                "total_chunks": len(chunks),
            },
        )

    def _format_chunk(
        self,
        chunk: DocumentChunk,
        config: ContextConfig,
    ) -> str:
        """Format a chunk for context inclusion."""
        parts = []

        if config.include_metadata and chunk.heading_context:
            parts.append(f"[Section: {chunk.heading_context}]")

        if config.include_page_numbers and chunk.start_page > 0:
            if chunk.start_page == chunk.end_page:
                parts.append(f"[Page {chunk.start_page}]")
            else:
                parts.append(f"[Pages {chunk.start_page}-{chunk.end_page}]")

        parts.append(chunk.content)
        return "\n".join(parts)

    def estimate_cost(
        self,
        total_tokens: int,
        model: str,
    ) -> dict[str, float | int | str]:
        """
        Estimate cost for processing with given model.

        Args:
            total_tokens: Total tokens to process
            model: Model name

        Returns:
            Cost estimate dictionary
        """
        pricing = PRICING.get(model, {"input": 5.00, "output": 15.00})
        input_cost = (total_tokens / 1_000_000) * pricing["input"]
        # Estimate output as 20% of input
        output_cost = (total_tokens * 0.2 / 1_000_000) * pricing["output"]

        return {
            "input_tokens": total_tokens,
            "estimated_output_tokens": int(total_tokens * 0.2),
            "input_cost_usd": round(input_cost, 4),
            "output_cost_usd": round(output_cost, 4),
            "total_cost_usd": round(input_cost + output_cost, 4),
            "model": model,
        }


# Global instance
_manager: ContextManager | None = None


def get_context_manager() -> ContextManager:
    """Get or create global context manager instance."""
    global _manager
    if _manager is None:
        _manager = ContextManager()
    return _manager


__all__ = [
    "ContextManager",
    "ContextWindow",
    "ContextConfig",
    "ContextStrategy",
    "get_context_manager",
]
