"""
TRUE RLM REPL helpers for ContinuumMemory context navigation.

Based on arXiv:2512.24601 "Recursive Language Models":
These helpers enable LLMs to programmatically navigate multi-tier memory
stored as Python variables in a REPL environment.

ContinuumMemory tiers:
- Fast: 1 min TTL, immediate context
- Medium: 1 hour TTL, session memory
- Slow: 1 day TTL, cross-session learning
- Glacial: 1 week TTL, long-term patterns

Usage in TRUE RLM REPL:
    # Context is stored as a variable, not in the prompt
    mem = load_memory_context(continuum)

    # LLM writes code to query memory
    important = filter_by_importance(mem.entries, threshold=0.8)
    red_lines = filter_red_line(mem.entries)
    matches = search_memory(mem, r"rate limit|throttl")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry from ContinuumMemory."""

    id: str
    tier: str  # "fast", "medium", "slow", "glacial"
    content: str
    importance: float  # 0.0-1.0
    surprise_score: float  # 0.0-1.0
    success_rate: float  # 0.0-1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    red_line: bool = False  # If True, this is a critical constraint


@dataclass
class MemoryREPLContext:
    """
    Structured ContinuumMemory context for TRUE RLM REPL navigation.

    Memory entries are stored in Python data structures that the
    LLM can query programmatically rather than stuffing into prompts.
    """

    entries: list[MemoryEntry]
    by_tier: dict[str, list[MemoryEntry]]
    by_id: dict[str, MemoryEntry]
    total_entries: int
    tier_counts: dict[str, int]
    avg_importance: float


def load_memory_context(
    continuum: Any,
    limit: int = 200,
    query: str | None = None,
) -> MemoryREPLContext:
    """
    Load ContinuumMemory into a structured context for REPL navigation.

    Args:
        continuum: ContinuumMemory instance
        limit: Maximum entries to load per tier
        query: Optional query to pre-filter entries

    Returns:
        MemoryREPLContext with indexed access to memory

    Example in TRUE RLM REPL:
        >>> mem = load_memory_context(continuum)
        >>> print(f"Total: {mem.total_entries}, Tiers: {mem.tier_counts}")
    """
    entries: list[MemoryEntry] = []
    by_tier: dict[str, list[MemoryEntry]] = {}
    by_id: dict[str, MemoryEntry] = {}

    tiers = ["fast", "medium", "slow", "glacial"]

    for tier in tiers:
        tier_entries: list[MemoryEntry] = []
        try:
            # Try common memory retrieval patterns
            raw_entries = None
            if query and hasattr(continuum, "search"):
                raw_entries = continuum.search(query, tier=tier, limit=limit)
            elif hasattr(continuum, "get_entries"):
                raw_entries = continuum.get_entries(tier=tier, limit=limit)
            elif hasattr(continuum, "get_tier"):
                raw_entries = continuum.get_tier(tier, limit=limit)
            elif hasattr(continuum, "retrieve"):
                raw_entries = continuum.retrieve(tier=tier, limit=limit)

            for raw in raw_entries or []:
                entry = _to_memory_entry(raw, tier)
                tier_entries.append(entry)
                entries.append(entry)
                by_id[entry.id] = entry
        except (AttributeError, TypeError) as e:
            logger.debug("Memory tier %s access failed: %s", tier, e)

        by_tier[tier] = tier_entries

    total = len(entries)
    avg_importance = sum(e.importance for e in entries) / total if total > 0 else 0.0
    tier_counts = {tier: len(items) for tier, items in by_tier.items()}

    return MemoryREPLContext(
        entries=entries,
        by_tier=by_tier,
        by_id=by_id,
        total_entries=total,
        tier_counts=tier_counts,
        avg_importance=avg_importance,
    )


def _to_memory_entry(raw: Any, tier: str) -> MemoryEntry:
    """Convert raw memory data to MemoryEntry."""
    if isinstance(raw, dict):
        content = raw.get("content")
        if content is None:
            content = raw.get("text")
        if content is None:
            content = str(raw)

        surprise_score = raw.get("surprise_score")
        if surprise_score is None:
            surprise_score = raw.get("surprise")
        if surprise_score is None:
            surprise_score = 0.0

        return MemoryEntry(
            id=raw.get("id", str(hash(str(raw)))),
            tier=raw.get("tier", tier),
            content=content,
            importance=raw.get("importance", 0.5),
            surprise_score=surprise_score,
            success_rate=raw.get("success_rate", 0.5),
            metadata=raw.get("metadata", {}),
            red_line=raw.get("red_line", False),
        )
    elif hasattr(raw, "model_dump"):
        return _to_memory_entry(raw.model_dump(), tier)
    elif hasattr(raw, "__dict__"):
        return _to_memory_entry(vars(raw), tier)
    else:
        return MemoryEntry(
            id=str(hash(str(raw))),
            tier=tier,
            content=str(raw),
            importance=0.5,
            surprise_score=0.0,
            success_rate=0.5,
        )


def get_tier(
    context: MemoryREPLContext,
    tier: str,
) -> list[MemoryEntry]:
    """
    Get all memory entries from a specific tier.

    Args:
        context: The memory REPL context
        tier: Tier name ("fast", "medium", "slow", "glacial")

    Returns:
        List of entries from that tier
    """
    return context.by_tier.get(tier, [])


def filter_by_importance(
    entries: list[MemoryEntry],
    threshold: float = 0.7,
) -> list[MemoryEntry]:
    """
    Filter memory entries by importance score.

    Args:
        entries: List of memory entries
        threshold: Minimum importance threshold

    Returns:
        Filtered list of important entries
    """
    return [e for e in entries if e.importance >= threshold]


def filter_red_line(
    entries: list[MemoryEntry],
) -> list[MemoryEntry]:
    """
    Get all red-line (critical constraint) memory entries.

    Args:
        entries: List of memory entries

    Returns:
        List of red-line entries
    """
    return [e for e in entries if e.red_line]


def search_memory(
    context: MemoryREPLContext,
    pattern: str,
    case_insensitive: bool = True,
) -> list[MemoryEntry]:
    """
    Search memory entries using regex pattern.

    This is the "grep" operation from the RLM paper.

    Args:
        context: The memory REPL context
        pattern: Regex pattern to match
        case_insensitive: Whether to ignore case

    Returns:
        List of matching entries
    """
    flags = re.IGNORECASE if case_insensitive else 0
    regex = re.compile(pattern, flags)
    return [e for e in context.entries if regex.search(e.content)]


def sort_by_surprise(
    entries: list[MemoryEntry],
    descending: bool = True,
) -> list[MemoryEntry]:
    """
    Sort memory entries by surprise score.

    Args:
        entries: List of memory entries
        descending: If True, most surprising first

    Returns:
        Sorted list of entries
    """
    return sorted(entries, key=lambda e: e.surprise_score, reverse=descending)


def get_memory_helpers(
    include_rlm_primitives: bool = False,
) -> dict[str, Any]:
    """
    Get all memory REPL helpers as a dictionary.

    This is used to inject helpers into a TRUE RLM REPL environment.

    Args:
        include_rlm_primitives: If True, include llm_query/FINAL placeholders

    Returns:
        Dictionary of helper functions
    """
    helpers: dict[str, Any] = {
        # Types
        "MemoryEntry": MemoryEntry,
        "MemoryREPLContext": MemoryREPLContext,
        # Context loading
        "load_memory_context": load_memory_context,
        # Navigation
        "get_tier": get_tier,
        "filter_by_importance": filter_by_importance,
        "filter_red_line": filter_red_line,
        "search_memory": search_memory,
        "sort_by_surprise": sort_by_surprise,
    }

    if include_rlm_primitives:
        helpers["llm_query"] = lambda prompt: f"[llm_query placeholder: {prompt[:100]}]"
        helpers["FINAL"] = lambda answer: answer

    return helpers


__all__ = [
    "MemoryEntry",
    "MemoryREPLContext",
    "load_memory_context",
    "get_tier",
    "filter_by_importance",
    "filter_red_line",
    "search_memory",
    "sort_by_surprise",
    "get_memory_helpers",
]
