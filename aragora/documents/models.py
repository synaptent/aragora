"""
Data models for enterprise document processing.

Defines core types for document ingestion, chunking, and auditing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast
from uuid import uuid4

from aragora.utils.datetime_helpers import parse_timestamp, utc_now


class DocumentStatus(Enum):
    """Processing status for ingested documents."""

    PENDING = "pending"  # Uploaded, awaiting processing
    PROCESSING = "processing"  # Currently being parsed/chunked
    INDEXED = "indexed"  # Processed and indexed
    FAILED = "failed"  # Processing failed
    ARCHIVED = "archived"  # Removed from active index


class ChunkType(Enum):
    """Type of content in a document chunk."""

    TEXT = "text"  # Regular paragraph text
    HEADING = "heading"  # Section header
    TABLE = "table"  # Tabular data
    CODE = "code"  # Source code block
    LIST = "list"  # Bulleted/numbered list
    IMAGE = "image"  # Image with caption/OCR
    FORMULA = "formula"  # Mathematical formula
    METADATA = "metadata"  # Document metadata
    SUMMARY = "summary"  # Summarized content (RLM hierarchical)
    ABSTRACT = "abstract"  # High-level abstract (RLM hierarchical)


@dataclass
class DocumentChunk:
    """
    A chunk of a document for RAG indexing.

    Chunks are created from larger documents to fit within LLM context windows.
    Each chunk maintains metadata for retrieval and context reconstruction.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    document_id: str = ""
    sequence: int = 0  # Order within document

    # Content
    content: str = ""
    chunk_type: ChunkType = ChunkType.TEXT

    # Location within document
    start_page: int = 0
    end_page: int = 0
    start_char: int = 0
    end_char: int = 0

    # Context for retrieval
    heading_context: str = ""  # Parent section headers (e.g., "Chapter 1 > Section 1.2")
    summary: str = ""  # Optional chunk summary

    # Embeddings (populated during indexing)
    embedding: list[float] | None = None
    embedding_model: str = ""

    # Token accounting
    token_count: int = 0
    token_model: str = ""  # Model used for counting (e.g., "gpt-4", "claude-3")

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "sequence": self.sequence,
            "content": self.content,
            "chunk_type": self.chunk_type.value,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "heading_context": self.heading_context,
            "summary": self.summary,
            "embedding": self.embedding,
            "embedding_model": self.embedding_model,
            "token_count": self.token_count,
            "token_model": self.token_model,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentChunk:
        """Create from dictionary."""
        chunk_type = data.get("chunk_type", "text")
        if isinstance(chunk_type, str):
            chunk_type = ChunkType(chunk_type)

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return cls(
            id=data.get("id", str(uuid4())),
            document_id=data.get("document_id", ""),
            sequence=data.get("sequence", 0),
            content=data.get("content", ""),
            chunk_type=chunk_type,
            start_page=data.get("start_page", 0),
            end_page=data.get("end_page", 0),
            start_char=data.get("start_char", 0),
            end_char=data.get("end_char", 0),
            heading_context=data.get("heading_context", ""),
            summary=data.get("summary", ""),
            embedding=data.get("embedding"),
            embedding_model=data.get("embedding_model", ""),
            token_count=data.get("token_count", 0),
            token_model=data.get("token_model", ""),
            created_at=created_at,
            metadata=data.get("metadata", {}),
        )


@dataclass
class IngestedDocument:
    """
    An ingested document with processing metadata.

    Represents a document uploaded to the system, including parsing results,
    chunking information, and indexing status.
    """

    id: str = field(default_factory=lambda: str(uuid4()))

    # Basic info
    filename: str = ""
    content_type: str = ""  # MIME type
    file_size: int = 0  # Bytes

    # Ownership
    workspace_id: str = ""
    uploaded_by: str = ""

    # Processing status
    status: DocumentStatus = DocumentStatus.PENDING
    error_message: str = ""

    # Content statistics
    page_count: int = 0
    word_count: int = 0
    char_count: int = 0
    total_tokens: int = 0  # Total tokens across all chunks

    # Chunking results
    chunk_count: int = 0
    chunk_ids: list[str] = field(default_factory=list)
    chunking_strategy: str = ""  # semantic, sliding, recursive
    chunk_size: int = 0  # Target chunk size in tokens
    chunk_overlap: int = 0  # Overlap between chunks

    # Parsing info
    parser_used: str = ""  # unstructured, docling, native
    parse_duration_ms: int = 0

    # Full text (optional, may be empty for large docs)
    text: str = ""
    preview: str = ""  # First ~500 chars

    # Document structure
    headings: list[str] = field(default_factory=list)  # Extracted headings
    tables_count: int = 0
    images_count: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
    indexed_at: datetime | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Generate preview if not set."""
        if not self.preview and self.text:
            self.preview = self.text[:500].strip()
            if len(self.text) > 500:
                self.preview += "..."

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "workspace_id": self.workspace_id,
            "uploaded_by": self.uploaded_by,
            "status": self.status.value,
            "error_message": self.error_message,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "total_tokens": self.total_tokens,
            "chunk_count": self.chunk_count,
            "chunk_ids": self.chunk_ids,
            "chunking_strategy": self.chunking_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "parser_used": self.parser_used,
            "parse_duration_ms": self.parse_duration_ms,
            "text": self.text,
            "preview": self.preview,
            "headings": self.headings,
            "tables_count": self.tables_count,
            "images_count": self.images_count,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestedDocument:
        """Create from dictionary."""
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = DocumentStatus(status)

        return cls(
            id=data.get("id", str(uuid4())),
            filename=data.get("filename", ""),
            content_type=data.get("content_type", ""),
            file_size=data.get("file_size", 0),
            workspace_id=data.get("workspace_id", ""),
            uploaded_by=data.get("uploaded_by", ""),
            status=status,
            error_message=data.get("error_message", ""),
            page_count=data.get("page_count", 0),
            word_count=data.get("word_count", 0),
            char_count=data.get("char_count", 0),
            total_tokens=data.get("total_tokens", 0),
            chunk_count=data.get("chunk_count", 0),
            chunk_ids=data.get("chunk_ids", []),
            chunking_strategy=data.get("chunking_strategy", ""),
            chunk_size=data.get("chunk_size", 0),
            chunk_overlap=data.get("chunk_overlap", 0),
            parser_used=data.get("parser_used", ""),
            parse_duration_ms=data.get("parse_duration_ms", 0),
            text=data.get("text", ""),
            preview=data.get("preview", ""),
            headings=data.get("headings", []),
            tables_count=data.get("tables_count", 0),
            images_count=data.get("images_count", 0),
            created_at=cast(
                datetime,
                parse_timestamp(data.get("created_at"), default=utc_now()),
            ),
            processed_at=parse_timestamp(data.get("processed_at")),
            indexed_at=parse_timestamp(data.get("indexed_at")),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
        )

    def to_summary(self) -> dict[str, Any]:
        """Return a lightweight summary for listing."""
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "status": self.status.value,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "chunk_count": self.chunk_count,
            "preview": self.preview[:100] + "..." if len(self.preview) > 100 else self.preview,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
        }


# Token limits for common models
MODEL_TOKEN_LIMITS = {
    # Anthropic
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5-sonnet": 200_000,
    "claude-3.7-sonnet": 200_000,
    # OpenAI
    "gpt-4-turbo": 128_000,
    "gpt-4o": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # Google
    "gemini-3.1-pro-preview": 1_000_000,  # 1M tokens
    "gemini-3-pro": 1_000_000,
    "gemini-2.0-pro": 1_000_000,
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    # Mistral
    "mistral-large": 128_000,
    "codestral": 32_000,
    # Default fallback
    "default": 8_192,
}


def get_model_token_limit(model: str) -> int:
    """Get the token limit for a model."""
    # Normalize model name
    model_lower = model.lower()

    # Check direct match
    if model_lower in MODEL_TOKEN_LIMITS:
        return MODEL_TOKEN_LIMITS[model_lower]

    # Check partial matches
    for key, limit in MODEL_TOKEN_LIMITS.items():
        if key in model_lower or model_lower in key:
            return limit

    return MODEL_TOKEN_LIMITS["default"]
