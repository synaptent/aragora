"""
Document chunking strategies for RAG and large document processing.

Provides multiple chunking approaches optimized for different document types:
- SemanticChunking: Best for narrative documents (reports, contracts)
- SlidingWindowChunking: Fast, good for code and structured data
- RecursiveChunking: Preserves hierarchical structure (specs, manuals)

Research-backed defaults:
- Chunk size: 256-512 tokens for 70% accuracy improvement
- Overlap: 10-20% for context preservation

Usage:
    from aragora.documents.chunking.strategies import (
        SemanticChunking,
        SlidingWindowChunking,
        RecursiveChunking,
        get_chunking_strategy,
    )

    strategy = get_chunking_strategy("semantic", chunk_size=512, overlap=50)
    chunks = strategy.chunk(document_text)
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from aragora.documents.chunking.token_counter import get_token_counter
from aragora.documents.models import ChunkType, DocumentChunk

logger = logging.getLogger(__name__)

ChunkingStrategyType = Literal["semantic", "sliding", "recursive", "fixed", "rlm"]


@dataclass
class ChunkingConfig:
    """Configuration for chunking strategies."""

    # Target chunk size in tokens
    chunk_size: int = 512

    # Overlap between chunks in tokens
    overlap: int = 50

    # Minimum chunk size (avoid tiny chunks)
    min_chunk_size: int = 50

    # Maximum chunk size (hard limit)
    max_chunk_size: int = 2048

    # Model for token counting
    model: str = "gpt-4"

    # Whether to preserve paragraph boundaries
    preserve_paragraphs: bool = True

    # Whether to preserve sentence boundaries
    preserve_sentences: bool = True

    # Include heading context in each chunk
    include_heading_context: bool = True


class ChunkingStrategy(ABC):
    """
    Abstract base class for chunking strategies.

    All strategies produce DocumentChunk objects with metadata
    for retrieval and context reconstruction.
    """

    def __init__(self, config: ChunkingConfig | None = None):
        self.config = config or ChunkingConfig()
        self.token_counter = get_token_counter()

    @abstractmethod
    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        """
        Split text into chunks.

        Args:
            text: The full document text
            document_id: ID of the parent document
            metadata: Additional metadata to include in chunks

        Returns:
            List of DocumentChunk objects
        """
        pass

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Return the strategy name."""
        pass

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return self.token_counter.count(text, self.config.model)

    def _extract_headings(self, text: str) -> list[tuple[int, str, int]]:
        """
        Extract headings and their positions.

        Returns list of (position, heading_text, level).
        """
        headings = []

        # Markdown headings
        for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
            level = len(match.group(1))
            headings.append((match.start(), match.group(2).strip(), level))

        # Underlined headings
        for match in re.finditer(r"^(.+)\n[=]{3,}$", text, re.MULTILINE):
            headings.append((match.start(), match.group(1).strip(), 1))
        for match in re.finditer(r"^(.+)\n[-]{3,}$", text, re.MULTILINE):
            headings.append((match.start(), match.group(1).strip(), 2))

        # Sort by position
        headings.sort(key=lambda x: x[0])
        return headings

    def _get_heading_context(
        self,
        position: int,
        headings: list[tuple[int, str, int]],
    ) -> str:
        """Get the heading context for a position in the text."""
        context_parts = []
        current_levels: dict[int, str] = {}

        for pos, heading, level in headings:
            if pos > position:
                break

            # Clear lower-level headings when a higher-level one appears
            current_levels = {k: v for k, v in current_levels.items() if k < level}
            current_levels[level] = heading

        # Build hierarchical context
        for level in sorted(current_levels.keys()):
            context_parts.append(current_levels[level])

        return " > ".join(context_parts) if context_parts else ""

    def _create_chunk(
        self,
        content: str,
        document_id: str,
        sequence: int,
        start_char: int,
        end_char: int,
        heading_context: str = "",
        chunk_type: ChunkType = ChunkType.TEXT,
        metadata: dict | None = None,
    ) -> DocumentChunk:
        """Create a DocumentChunk with proper metadata."""
        return DocumentChunk(
            document_id=document_id,
            sequence=sequence,
            content=content,
            chunk_type=chunk_type,
            start_char=start_char,
            end_char=end_char,
            heading_context=heading_context,
            token_count=self._count_tokens(content),
            token_model=self.config.model,
            metadata=metadata or {},
        )


class SlidingWindowChunking(ChunkingStrategy):
    """
    Sliding window chunking with fixed overlap.

    Best for:
    - Code and technical documentation
    - Structured data with consistent formatting
    - Fast processing with acceptable quality

    Creates chunks of approximately chunk_size tokens with
    overlap tokens shared between adjacent chunks.
    """

    @property
    def strategy_name(self) -> str:
        return "sliding"

    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        if not text.strip():
            return []

        chunks = []
        headings = self._extract_headings(text) if self.config.include_heading_context else []

        # Split into sentences for cleaner boundaries
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        current_chunk_sentences: list[str] = []
        current_tokens = 0
        chunk_start_char = 0
        sequence = 0

        for sentence, sent_start, sent_end in sentences:
            sent_tokens = self._count_tokens(sentence)

            # Check if adding this sentence exceeds limit
            if current_tokens + sent_tokens > self.config.chunk_size and current_chunk_sentences:
                # Create chunk from current sentences
                chunk_content = " ".join(current_chunk_sentences)
                chunk_end_char = sent_start

                heading_context = ""
                if self.config.include_heading_context:
                    heading_context = self._get_heading_context(chunk_start_char, headings)

                chunks.append(
                    self._create_chunk(
                        content=chunk_content,
                        document_id=document_id,
                        sequence=sequence,
                        start_char=chunk_start_char,
                        end_char=chunk_end_char,
                        heading_context=heading_context,
                        metadata=metadata,
                    )
                )
                sequence += 1

                # Start new chunk with overlap
                overlap_sentences = self._get_overlap_sentences(
                    current_chunk_sentences, self.config.overlap
                )
                current_chunk_sentences = overlap_sentences
                current_tokens = sum(self._count_tokens(s) for s in overlap_sentences)
                chunk_start_char = sent_start - sum(len(s) + 1 for s in overlap_sentences)
                chunk_start_char = max(0, chunk_start_char)

            current_chunk_sentences.append(sentence)
            current_tokens += sent_tokens

        # Create final chunk
        if current_chunk_sentences:
            chunk_content = " ".join(current_chunk_sentences)
            heading_context = ""
            if self.config.include_heading_context:
                heading_context = self._get_heading_context(chunk_start_char, headings)

            chunks.append(
                self._create_chunk(
                    content=chunk_content,
                    document_id=document_id,
                    sequence=sequence,
                    start_char=chunk_start_char,
                    end_char=len(text),
                    heading_context=heading_context,
                    metadata=metadata,
                )
            )

        return chunks

    def _split_sentences(self, text: str) -> list[tuple[str, int, int]]:
        """Split text into sentences with positions."""
        # Simple sentence splitting - handles common cases
        sentence_endings = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

        sentences = []
        last_end = 0

        for match in sentence_endings.finditer(text):
            sentence = text[last_end : match.start() + 1].strip()
            if sentence:
                sentences.append((sentence, last_end, match.start() + 1))
            last_end = match.end()

        # Add final sentence
        final = text[last_end:].strip()
        if final:
            sentences.append((final, last_end, len(text)))

        return sentences

    def _get_overlap_sentences(self, sentences: list[str], target_overlap_tokens: int) -> list[str]:
        """Get sentences from end to achieve target overlap."""
        overlap: list[str] = []
        tokens = 0

        for sentence in reversed(sentences):
            sent_tokens = self._count_tokens(sentence)
            if tokens + sent_tokens > target_overlap_tokens and overlap:
                break
            overlap.insert(0, sentence)
            tokens += sent_tokens

        return overlap


class SemanticChunking(ChunkingStrategy):
    """
    Semantic chunking based on natural document boundaries.

    Best for:
    - Narrative documents (reports, articles)
    - Legal contracts and agreements
    - Any document with clear paragraph structure

    Chunks on paragraph boundaries, attempting to keep related
    content together based on semantic markers.
    """

    @property
    def strategy_name(self) -> str:
        return "semantic"

    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        if not text.strip():
            return []

        chunks = []
        headings = self._extract_headings(text) if self.config.include_heading_context else []

        # Split into paragraphs
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return []

        current_paragraphs: list[tuple[str, int, int]] = []
        current_tokens = 0
        sequence = 0

        for para, para_start, para_end in paragraphs:
            para_tokens = self._count_tokens(para)

            # Single paragraph exceeds chunk size - need to split it
            if para_tokens > self.config.chunk_size:
                # First, flush current buffer
                if current_paragraphs:
                    chunks.extend(
                        self._create_chunks_from_paragraphs(
                            current_paragraphs, document_id, sequence, headings, metadata
                        )
                    )
                    sequence += len(chunks) - sequence

                # Split large paragraph using sliding window
                sub_chunks = SlidingWindowChunking(self.config).chunk(para, document_id, metadata)
                for i, sub_chunk in enumerate(sub_chunks):
                    sub_chunk.sequence = sequence + i
                    sub_chunk.start_char += para_start
                    sub_chunk.end_char = min(sub_chunk.end_char + para_start, para_end)
                    if self.config.include_heading_context:
                        sub_chunk.heading_context = self._get_heading_context(
                            sub_chunk.start_char, headings
                        )
                chunks.extend(sub_chunks)
                sequence += len(sub_chunks)
                current_paragraphs = []
                current_tokens = 0
                continue

            # Check if adding paragraph exceeds limit
            if current_tokens + para_tokens > self.config.chunk_size and current_paragraphs:
                # Create chunk(s) from current paragraphs
                new_chunks = self._create_chunks_from_paragraphs(
                    current_paragraphs, document_id, sequence, headings, metadata
                )
                chunks.extend(new_chunks)
                sequence += len(new_chunks)

                # Start new buffer
                current_paragraphs = []
                current_tokens = 0

            current_paragraphs.append((para, para_start, para_end))
            current_tokens += para_tokens

        # Create final chunk(s)
        if current_paragraphs:
            new_chunks = self._create_chunks_from_paragraphs(
                current_paragraphs, document_id, sequence, headings, metadata
            )
            chunks.extend(new_chunks)

        return chunks

    def _split_paragraphs(self, text: str) -> list[tuple[str, int, int]]:
        """Split text into paragraphs with positions."""
        paragraphs = []
        # Split on double newlines or multiple whitespace lines
        pattern = re.compile(r"\n\s*\n+")

        last_end = 0
        for match in pattern.finditer(text):
            para = text[last_end : match.start()].strip()
            if para:
                paragraphs.append((para, last_end, match.start()))
            last_end = match.end()

        # Add final paragraph
        final = text[last_end:].strip()
        if final:
            paragraphs.append((final, last_end, len(text)))

        return paragraphs

    def _create_chunks_from_paragraphs(
        self,
        paragraphs: list[tuple[str, int, int]],
        document_id: str,
        start_sequence: int,
        headings: list[tuple[int, str, int]],
        metadata: dict | None,
    ) -> list[DocumentChunk]:
        """Create chunks from a list of paragraphs."""
        if not paragraphs:
            return []

        content = "\n\n".join(p[0] for p in paragraphs)
        start_char = paragraphs[0][1]
        end_char = paragraphs[-1][2]

        heading_context = ""
        if self.config.include_heading_context:
            heading_context = self._get_heading_context(start_char, headings)

        return [
            self._create_chunk(
                content=content,
                document_id=document_id,
                sequence=start_sequence,
                start_char=start_char,
                end_char=end_char,
                heading_context=heading_context,
                metadata=metadata,
            )
        ]


class RecursiveChunking(ChunkingStrategy):
    """
    Recursive chunking that preserves document hierarchy.

    Best for:
    - Technical specifications and manuals
    - Documents with clear section structure
    - Hierarchical content (chapters, sections, subsections)

    Splits on increasingly fine-grained separators until
    chunks are within the target size.
    """

    # Separators in order of preference (coarse to fine)
    SEPARATORS = [
        "\n\n\n",  # Major section break
        "\n\n",  # Paragraph break
        "\n",  # Line break
        ". ",  # Sentence break
        ", ",  # Clause break
        " ",  # Word break
    ]

    @property
    def strategy_name(self) -> str:
        return "recursive"

    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        if not text.strip():
            return []

        headings = self._extract_headings(text) if self.config.include_heading_context else []

        # Recursively split
        raw_chunks = self._recursive_split(text, 0)

        # Convert to DocumentChunks with metadata
        chunks = []
        char_offset = 0

        for i, chunk_text in enumerate(raw_chunks):
            start_char = text.find(chunk_text, char_offset)
            if start_char == -1:
                start_char = char_offset
            end_char = start_char + len(chunk_text)
            char_offset = end_char

            heading_context = ""
            if self.config.include_heading_context:
                heading_context = self._get_heading_context(start_char, headings)

            chunks.append(
                self._create_chunk(
                    content=chunk_text,
                    document_id=document_id,
                    sequence=i,
                    start_char=start_char,
                    end_char=end_char,
                    heading_context=heading_context,
                    metadata=metadata,
                )
            )

        return chunks

    def _recursive_split(self, text: str, separator_index: int) -> list[str]:
        """Recursively split text using increasingly fine separators."""
        if not text.strip():
            return []

        tokens = self._count_tokens(text)

        # If text fits in chunk size, return as-is
        if tokens <= self.config.chunk_size:
            return [text.strip()] if text.strip() else []

        # If we've exhausted separators, force split by characters
        if separator_index >= len(self.SEPARATORS):
            return self._force_split(text)

        separator = self.SEPARATORS[separator_index]
        parts = text.split(separator)

        # If we can't split further with this separator, try next
        if len(parts) == 1:
            return self._recursive_split(text, separator_index + 1)

        # Process each part recursively and merge small chunks
        result = []
        current_chunk = ""

        for part in parts:
            part = part.strip()
            if not part:
                continue

            potential = current_chunk + separator + part if current_chunk else part
            potential_tokens = self._count_tokens(potential)

            if potential_tokens <= self.config.chunk_size:
                current_chunk = potential
            else:
                # Save current chunk if exists
                if current_chunk:
                    result.append(current_chunk)

                # Process this part (might need further splitting)
                part_tokens = self._count_tokens(part)
                if part_tokens <= self.config.chunk_size:
                    current_chunk = part
                else:
                    # Recursively split the part
                    sub_chunks = self._recursive_split(part, separator_index + 1)
                    if sub_chunks:
                        result.extend(sub_chunks[:-1])
                        current_chunk = sub_chunks[-1]
                    else:
                        current_chunk = ""

        if current_chunk:
            result.append(current_chunk)

        return result

    def _force_split(self, text: str) -> list[str]:
        """Force split text when no separator works."""
        chunks = []
        words = text.split()
        current_chunk: list[str] = []
        current_tokens = 0

        for word in words:
            word_tokens = self._count_tokens(word)

            if current_tokens + word_tokens > self.config.chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            current_chunk.append(word)
            current_tokens += word_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks


class FixedSizeChunking(ChunkingStrategy):
    """
    Simple fixed-size chunking by token count.

    Best for:
    - Quick processing without quality requirements
    - Testing and debugging
    - When document structure doesn't matter

    Splits strictly by token count with optional overlap.
    """

    @property
    def strategy_name(self) -> str:
        return "fixed"

    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        if not text.strip():
            return []

        headings = self._extract_headings(text) if self.config.include_heading_context else []

        chunks = []
        words = text.split()
        current_words: list[str] = []
        current_tokens = 0
        char_offset = 0
        sequence = 0

        for word in words:
            word_tokens = self._count_tokens(word)

            if current_tokens + word_tokens > self.config.chunk_size and current_words:
                # Create chunk
                chunk_text = " ".join(current_words)
                start_char = text.find(chunk_text, char_offset)
                if start_char == -1:
                    start_char = char_offset
                end_char = start_char + len(chunk_text)

                heading_context = ""
                if self.config.include_heading_context:
                    heading_context = self._get_heading_context(start_char, headings)

                chunks.append(
                    self._create_chunk(
                        content=chunk_text,
                        document_id=document_id,
                        sequence=sequence,
                        start_char=start_char,
                        end_char=end_char,
                        heading_context=heading_context,
                        metadata=metadata,
                    )
                )
                sequence += 1
                char_offset = end_char

                # Handle overlap
                if self.config.overlap > 0:
                    overlap_words = self._get_overlap_words(current_words, self.config.overlap)
                    current_words = overlap_words
                    current_tokens = sum(self._count_tokens(w) for w in overlap_words)
                else:
                    current_words = []
                    current_tokens = 0

            current_words.append(word)
            current_tokens += word_tokens

        # Final chunk
        if current_words:
            chunk_text = " ".join(current_words)
            start_char = text.find(chunk_text, char_offset)
            if start_char == -1:
                start_char = char_offset

            heading_context = ""
            if self.config.include_heading_context:
                heading_context = self._get_heading_context(start_char, headings)

            chunks.append(
                self._create_chunk(
                    content=chunk_text,
                    document_id=document_id,
                    sequence=sequence,
                    start_char=start_char,
                    end_char=len(text),
                    heading_context=heading_context,
                    metadata=metadata,
                )
            )

        return chunks

    def _get_overlap_words(self, words: list[str], target_overlap_tokens: int) -> list[str]:
        """Get words from end to achieve target overlap."""
        overlap: list[str] = []
        tokens = 0

        for word in reversed(words):
            word_tokens = self._count_tokens(word)
            if tokens + word_tokens > target_overlap_tokens and overlap:
                break
            overlap.insert(0, word)
            tokens += word_tokens

        return overlap


# RLM availability check (use factory for consistent initialization).
#
# The optional import binds these three names, so pre-declaring them at
# module scope AND importing them under the same names is a redefinition
# mypy rejects ([no-redef], x3). Import under private aliases and bind each
# public name exactly once, in one expression, so the fallback stays a plain
# ``None`` at runtime and the names keep their ``Any`` type statically.
try:
    from aragora.rlm import (
        AbstractionLevel as _AbstractionLevel,
        RLMConfig as _RLMConfig,
        get_compressor as _get_compressor,
    )

    HAS_RLM = True
except ImportError:
    _get_compressor = None  # type: ignore[assignment]
    _RLMConfig = None  # type: ignore[assignment,misc]
    _AbstractionLevel = None  # type: ignore[assignment,misc]
    HAS_RLM = False

get_compressor: Any = _get_compressor
RLMConfig: Any = _RLMConfig
AbstractionLevel: Any = _AbstractionLevel


class RLMChunking(ChunkingStrategy):
    """
    RLM-based hierarchical chunking strategy.

    Based on the "Recursive Language Models" paper (arXiv:2512.24601),
    this strategy creates multi-level chunk hierarchies that enable
    efficient navigation from summaries to details.

    Best for:
    - Very long documents (100K+ tokens)
    - Documents that need to be queried at multiple detail levels
    - Debate context that exceeds agent context windows

    Creates three levels of chunks:
    - Level 0 (FULL): Original chunks with full content
    - Level 1 (SUMMARY): Compressed summaries of groups of chunks
    - Level 2 (ABSTRACT): High-level overviews

    Each chunk includes a `hierarchy_id` linking to parent summaries,
    enabling drill-down retrieval.
    """

    def __init__(
        self,
        config: ChunkingConfig | None = None,
        rlm_config: Any | None = None,
        agent_call: Any | None = None,
    ):
        super().__init__(config)
        self._rlm_config = rlm_config
        self._agent_call = agent_call
        self._compressor = None

        if HAS_RLM and get_compressor is not None:
            try:
                config_obj = rlm_config if rlm_config else (RLMConfig() if RLMConfig else None)
                self._compressor = get_compressor(config=config_obj)
                # Set agent_call if the compressor supports it
                if agent_call and hasattr(self._compressor, "agent_call"):
                    self._compressor.agent_call = agent_call
            except (RuntimeError, OSError, ValueError, ImportError) as e:
                logger.warning("Failed to initialize RLM compressor: %s", e)

    @property
    def strategy_name(self) -> str:
        return "rlm"

    def chunk(
        self,
        text: str,
        document_id: str = "",
        metadata: dict | None = None,
    ) -> list[DocumentChunk]:
        """
        Create hierarchical chunks using RLM compression.

        Returns chunks at multiple abstraction levels, with hierarchy_id
        metadata linking children to their parent summaries.
        """
        if not text.strip():
            return []

        # Fall back to semantic chunking if RLM not available
        if not self._compressor:
            logger.warning("RLM not available, falling back to semantic chunking")
            fallback = SemanticChunking(self.config)
            return fallback.chunk(text, document_id, metadata)

        import asyncio

        # Run compression synchronously
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            compression_result = loop.run_until_complete(
                self._compressor.compress(text, source_type="text", max_levels=3)
            )
        except (RuntimeError, ValueError, OSError, TypeError) as e:
            logger.error("RLM compression failed: %s, falling back to semantic", e)
            fallback = SemanticChunking(self.config)
            return fallback.chunk(text, document_id, metadata)

        context = compression_result.context
        chunks = []
        sequence = 0

        # Process each level of the hierarchy
        for level in [
            AbstractionLevel.FULL,
            AbstractionLevel.DETAILED,
            AbstractionLevel.SUMMARY,
            AbstractionLevel.ABSTRACT,
        ]:
            if level not in context.levels:
                continue

            level_name = level.name.lower()

            for node in context.levels[level]:
                # Determine chunk type based on level
                if level == AbstractionLevel.FULL:
                    chunk_type = ChunkType.TEXT
                elif level in (AbstractionLevel.DETAILED, AbstractionLevel.SUMMARY):
                    chunk_type = ChunkType.SUMMARY
                else:
                    chunk_type = ChunkType.ABSTRACT

                # Build metadata with hierarchy info
                chunk_metadata = {
                    **(metadata or {}),
                    "hierarchy_level": level_name,
                    "hierarchy_id": node.id,
                    "parent_id": node.parent_id,
                    "child_ids": node.child_ids,
                    "key_topics": node.key_topics,
                    "rlm_compressed": True,
                }

                chunk = DocumentChunk(
                    id=f"{document_id}_{node.id}" if document_id else node.id,
                    document_id=document_id,
                    content=node.content,
                    token_count=node.token_count,
                    sequence=sequence,
                    start_char=node.source_range[0],
                    end_char=node.source_range[1],
                    chunk_type=chunk_type,
                    heading_context=f"[{level_name.upper()}]",
                    metadata=chunk_metadata,
                )
                chunks.append(chunk)
                sequence += 1

        logger.info(
            "RLM chunking created %d chunks at %d levels",
            len(chunks),
            len(context.levels),
        )

        return chunks


class HierarchicalChunkNavigator:
    """
    Navigator for cross-level chunk hierarchy traversal.

    Enables efficient drill-down from abstract summaries to detailed
    content, and roll-up from details to summaries.

    Usage:
        navigator = HierarchicalChunkNavigator(rlm_chunks)

        # Get all chunks at abstract level
        abstracts = navigator.get_level("abstract")

        # Drill down from an abstract chunk to its children
        children = navigator.drill_down("chunk_abstract_123")

        # Get full detail for a specific chunk
        detailed = navigator.get_detailed("chunk_summary_456")

        # Search across all levels
        results = navigator.search("contract requirements")
    """

    def __init__(self, chunks: list[DocumentChunk]):
        """
        Initialize navigator with hierarchical chunks.

        Args:
            chunks: List of DocumentChunks created by RLMChunking
        """
        self._chunks = {c.id: c for c in chunks if c.id}
        self._by_level: dict[str, list[DocumentChunk]] = {}
        self._by_parent: dict[str, list[DocumentChunk]] = {}

        # Index chunks by level and parent
        for chunk in chunks:
            level = chunk.metadata.get("hierarchy_level", "full")
            if level not in self._by_level:
                self._by_level[level] = []
            self._by_level[level].append(chunk)

            parent_id = chunk.metadata.get("parent_id")
            if parent_id:
                if parent_id not in self._by_parent:
                    self._by_parent[parent_id] = []
                self._by_parent[parent_id].append(chunk)

    def get_level(self, level: str) -> list[DocumentChunk]:
        """
        Get all chunks at a specific abstraction level.

        Args:
            level: One of "full", "detailed", "summary", "abstract"

        Returns:
            List of chunks at that level
        """
        return self._by_level.get(level.lower(), [])

    def drill_down(self, chunk_id: str) -> list[DocumentChunk]:
        """
        Get child chunks of a parent chunk.

        Navigates from summary/abstract to more detailed children.

        Args:
            chunk_id: ID of parent chunk

        Returns:
            List of child chunks at the next detail level
        """
        return self._by_parent.get(chunk_id, [])

    def roll_up(self, chunk_id: str) -> DocumentChunk | None:
        """
        Get the parent summary of a detailed chunk.

        Navigates from detailed content to parent summary.

        Args:
            chunk_id: ID of child chunk

        Returns:
            Parent chunk, or None if at top level
        """
        chunk = self._chunks.get(chunk_id)
        if not chunk:
            return None

        parent_id = chunk.metadata.get("parent_id")
        if parent_id:
            return self._chunks.get(parent_id)
        return None

    def get_detailed(self, chunk_id: str, max_depth: int = 3) -> list[DocumentChunk]:
        """
        Recursively get all detailed descendants of a chunk.

        Useful for getting full content under a summary.

        Args:
            chunk_id: ID of starting chunk
            max_depth: Maximum recursion depth

        Returns:
            List of all descendant chunks
        """
        if max_depth <= 0:
            return []

        result = []
        children = self.drill_down(chunk_id)

        for child in children:
            result.append(child)
            if child.id:
                result.extend(self.get_detailed(child.id, max_depth - 1))

        return result

    def get_path_to_root(self, chunk_id: str) -> list[DocumentChunk]:
        """
        Get the path from a chunk to the root (most abstract level).

        Useful for understanding context of a detailed chunk.

        Args:
            chunk_id: ID of starting chunk

        Returns:
            List of chunks from detail to abstract
        """
        path = []
        current = self._chunks.get(chunk_id)

        while current:
            path.append(current)
            parent = self.roll_up(current.id) if current.id else None
            current = parent

        return path

    def search(
        self,
        query: str,
        level: str | None = None,
        limit: int = 10,
    ) -> list[tuple[DocumentChunk, float]]:
        """
        Search chunks with simple keyword matching.

        For production use, integrate with vector search.

        Args:
            query: Search query
            level: Optional level filter
            limit: Maximum results

        Returns:
            List of (chunk, score) tuples
        """
        query_terms = set(query.lower().split())
        results: list[tuple[DocumentChunk, float]] = []

        search_chunks: list[DocumentChunk] = list(self._chunks.values())
        if level:
            search_chunks = self.get_level(level)

        for chunk in search_chunks:
            content_terms = set(chunk.content.lower().split())
            matches = len(query_terms & content_terms)
            if matches > 0:
                score = matches / len(query_terms)
                results.append((chunk, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_context_for_query(
        self,
        query: str,
        start_level: str = "summary",
        include_children: bool = True,
    ) -> str:
        """
        Get optimized context for a query.

        Starts at the specified level, finds relevant chunks,
        and optionally includes their detailed children.

        Args:
            query: Search query
            start_level: Level to start search at
            include_children: Whether to include child chunks

        Returns:
            Formatted context string
        """
        results = self.search(query, level=start_level, limit=3)

        if not results:
            # Try abstract level
            results = self.search(query, level="abstract", limit=3)

        if not results:
            return ""

        context_parts = []

        for chunk, score in results:
            context_parts.append(
                f"## [{chunk.metadata.get('hierarchy_level', 'unknown').upper()}] (relevance: {score:.0%})"
            )
            context_parts.append(chunk.content)

            # Include children if requested and score is high
            if include_children and score >= 0.5 and chunk.id:
                children = self.drill_down(chunk.id)[:2]  # Limit children
                for child in children:
                    context_parts.append("\n### Details:")
                    context_parts.append(
                        child.content[:500] + "..." if len(child.content) > 500 else child.content
                    )

            context_parts.append("")

        return "\n".join(context_parts)


# Strategy registry
CHUNKING_STRATEGIES: dict[ChunkingStrategyType, type[ChunkingStrategy]] = {
    "semantic": SemanticChunking,
    "sliding": SlidingWindowChunking,
    "recursive": RecursiveChunking,
    "fixed": FixedSizeChunking,
    "rlm": RLMChunking,
}


def get_chunking_strategy(
    strategy_type: ChunkingStrategyType = "semantic",
    chunk_size: int = 512,
    overlap: int = 50,
    model: str = "gpt-4",
    **kwargs,
) -> ChunkingStrategy:
    """
    Get a chunking strategy instance.

    Args:
        strategy_type: Type of strategy (semantic, sliding, recursive, fixed)
        chunk_size: Target tokens per chunk
        overlap: Token overlap between chunks
        model: Model for token counting
        **kwargs: Additional config options

    Returns:
        Configured chunking strategy instance
    """
    config = ChunkingConfig(
        chunk_size=chunk_size,
        overlap=overlap,
        model=model,
        **kwargs,
    )

    strategy_class = CHUNKING_STRATEGIES.get(strategy_type, SemanticChunking)
    return strategy_class(config)


def auto_select_strategy(
    text: str,
    filename: str = "",
) -> ChunkingStrategyType:
    """
    Automatically select best chunking strategy based on content.

    Args:
        text: Document text
        filename: Optional filename for hints

    Returns:
        Recommended strategy type
    """
    filename_lower = filename.lower()

    # Code files - use sliding window
    code_extensions = {".py", ".js", ".ts", ".java", ".cpp", ".c", ".go", ".rs", ".rb"}
    if any(filename_lower.endswith(ext) for ext in code_extensions):
        return "sliding"

    # Check content characteristics
    lines = text.split("\n")
    total_lines = len(lines)

    # Count heading-like patterns
    heading_count = len(re.findall(r"^#+\s+.+$", text, re.MULTILINE))
    heading_count += len(re.findall(r"^.+\n[=-]{3,}$", text, re.MULTILINE))

    # Count code blocks
    code_blocks = len(re.findall(r"```[\s\S]*?```", text))

    # Structured documents with many headings - use recursive
    if total_lines > 50 and heading_count > 5:
        return "recursive"

    # Documents with code - use sliding
    if code_blocks > 3:
        return "sliding"

    # Default to semantic for narrative content
    return "semantic"


__all__ = [
    "ChunkingConfig",
    "ChunkingStrategy",
    "ChunkingStrategyType",
    "SemanticChunking",
    "SlidingWindowChunking",
    "RecursiveChunking",
    "FixedSizeChunking",
    "RLMChunking",
    "HierarchicalChunkNavigator",
    "get_chunking_strategy",
    "auto_select_strategy",
    "CHUNKING_STRATEGIES",
    "HAS_RLM",
]
