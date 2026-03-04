"""
CodebaseContextProvider - Thin wrapper that builds cached codebase context for debates.

Uses NomicContextBuilder (existing) for actual indexing/summarization, and optionally
syncs to Knowledge Mound via CodebaseAdapter. Manages crawl caching across debate rounds.

Usage:
    provider = CodebaseContextProvider(
        config=CodebaseContextConfig(codebase_path=".", max_context_tokens=500)
    )
    context = await provider.build_context("Refactor the debate module")
    summary = provider.get_summary(max_tokens=500)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CodebaseContextConfig:
    """Configuration for codebase context injection into debates."""

    codebase_path: str | None = None
    max_context_tokens: int = 500
    persist_to_km: bool = False
    include_tests: bool = False
    cache_ttl_seconds: float = 300.0  # 5 minutes
    enable_rlm: bool = False  # Use TRUE RLM for deep codebase exploration


@dataclass
class _CacheEntry:
    """Internal cache entry for built context."""

    context: str
    built_at: float = field(default_factory=time.monotonic)


class CodebaseContextProvider:
    """
    Builds and caches codebase context for debate agents.

    First call builds an index via NomicContextBuilder (existing).
    Subsequent calls return cached results. Optionally syncs to KM.
    """

    def __init__(self, config: CodebaseContextConfig | None = None):
        self._config = config or CodebaseContextConfig()
        self._cache: _CacheEntry | None = None
        self._builder: Any | None = None
        self._km_adapter: Any | None = None
        self._rlm: Any | None = None

    @property
    def config(self) -> CodebaseContextConfig:
        return self._config

    async def build_context(self, task: str) -> str:
        """
        Build codebase context for a debate task.

        On first call, creates an index via NomicContextBuilder and
        optionally syncs to Knowledge Mound. Subsequent calls within
        the cache TTL return the cached result.

        Args:
            task: The debate task/question for context relevance

        Returns:
            Structured codebase context string
        """
        if not self._config.codebase_path:
            return ""

        # Check cache
        if self._cache is not None:
            age = time.monotonic() - self._cache.built_at
            if age < self._config.cache_ttl_seconds:
                return self._cache.context

        try:
            context = await self._build_fresh_context(task)
            self._cache = _CacheEntry(context=context)

            # Optionally sync to Knowledge Mound
            if self._config.persist_to_km:
                await self._sync_to_km()

            return context
        except (RuntimeError, ValueError, OSError, ImportError) as e:
            logger.warning("Failed to build codebase context: %s", e)
            return ""

    def get_summary(self, max_tokens: int | None = None) -> str:
        """
        Get a truncated summary of the codebase context.

        Args:
            max_tokens: Maximum tokens for the summary (defaults to config)

        Returns:
            Truncated context string suitable for prompt injection
        """
        if self._cache is None:
            return ""

        limit = max_tokens or self._config.max_context_tokens
        max_chars = limit * 4  # ~4 chars per token heuristic

        context = self._cache.context
        if len(context) <= max_chars:
            return context

        return context[:max_chars].rstrip() + "\n...[truncated]"

    def invalidate_cache(self) -> None:
        """Invalidate the cached context, forcing rebuild on next call."""
        self._cache = None

    async def _build_fresh_context(self, task: str) -> str:
        """Build fresh context using NomicContextBuilder, enhanced with RLM if available."""
        from aragora.nomic.context_builder import NomicContextBuilder

        path = Path(self._config.codebase_path)  # type: ignore[arg-type]
        if not path.exists():
            logger.warning("Codebase path does not exist: %s", path)
            return ""

        self._builder = NomicContextBuilder(
            aragora_path=path,
            include_tests=self._config.include_tests,
        )

        context = await self._builder.build_debate_context()

        # Enhance with RLM deep exploration if enabled
        if self._config.enable_rlm:
            rlm_context = await self._build_rlm_context(task)
            if rlm_context:
                context = f"{context}\n\n## RLM Deep Analysis\n{rlm_context}"

        return context

    async def _build_rlm_context(self, task: str) -> str:
        """Use TRUE RLM bridge for deep programmatic codebase exploration.

        RLM (arXiv:2512.24601) enables 10M+ token context without degradation,
        allowing agents to explore the full codebase programmatically rather
        than relying on static summaries.

        Returns:
            RLM-generated codebase analysis, or empty string if unavailable.
        """
        try:
            from aragora.rlm.bridge import AragoraRLM

            if self._rlm is None:
                self._rlm = AragoraRLM()

            # Query RLM for task-relevant codebase structure
            result = await self._rlm.query(  # type: ignore[call-arg]
                f"Analyze codebase structure relevant to: {task}",
                context_path=self._config.codebase_path,
                max_tokens=self._config.max_context_tokens,
            )

            return str(result) if result else ""
        except ImportError:
            logger.debug("RLM bridge not available, using standard context only")
            return ""
        except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as e:
            logger.debug("RLM context build failed: %s", e)
            return ""

    async def _sync_to_km(self) -> None:
        """Sync codebase structures to Knowledge Mound via CodebaseAdapter."""
        try:
            from aragora.knowledge.mound.adapters.codebase_adapter import CodebaseAdapter

            if self._km_adapter is None:
                self._km_adapter = CodebaseAdapter()

            if self._config.codebase_path:
                await self._km_adapter.crawl_and_sync(self._config.codebase_path)
        except (ImportError, RuntimeError, ValueError, OSError) as e:
            logger.debug("KM sync skipped: %s", e)


def _extract_table(text: str, header_pattern: str) -> list[str]:
    """Extract rows from a markdown table matching a header pattern."""
    lines = text.splitlines()
    in_table = False
    rows: list[str] = []
    for line in lines:
        stripped = line.strip()
        if header_pattern in stripped:
            in_table = True
            continue
        if in_table:
            if stripped.startswith("|") and not stripped.startswith("|--"):
                rows.append(stripped)
            elif stripped.startswith("|--"):
                continue  # separator row
            elif not stripped:
                # blank line ends the table
                break
            else:
                break
    return rows


def _verify_paths(paths: list[str], root: Path) -> dict[str, bool]:
    """Check which paths exist on disk."""
    result: dict[str, bool] = {}
    for p in paths:
        result[p] = (root / p).exists()
    return result


def _extract_feature_status(text: str) -> str:
    """Extract feature status sections from CLAUDE.md."""
    lines = text.splitlines()
    output: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith("**Core (stable):**")
            or stripped.startswith("**Integrated:**")
            or stripped.startswith("**Enterprise")
        ):
            capturing = True
            output.append(stripped)
            continue
        if capturing:
            if stripped.startswith("##") or stripped.startswith("| "):
                break
            if stripped.startswith("- ") or stripped.startswith("**"):
                output.append(stripped)
            elif not stripped:
                output.append("")
            else:
                break
    return "\n".join(output).strip()


def build_static_inventory(
    repo_root: str | None = None,
    max_chars: int = 20_000,
) -> str:
    """Build a static codebase inventory from CLAUDE.md for debate context injection.

    Reads the quick reference table and feature status sections from CLAUDE.md,
    validates paths against the filesystem, and returns a compact inventory string.

    No API calls, no async, no indexing — just reads 1 markdown file.

    Args:
        repo_root: Repository root path. Defaults to cwd.
        max_chars: Maximum characters in the output.

    Returns:
        Structured codebase inventory string, or empty string on failure.
    """
    root = Path(repo_root or os.getcwd())
    claude_md = root / "CLAUDE.md"

    if not claude_md.exists():
        logger.warning("CLAUDE.md not found at %s", claude_md)
        return ""

    try:
        content = claude_md.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to read CLAUDE.md: %s", e)
        return ""

    sections: list[str] = []
    sections.append("## CODEBASE INVENTORY (DO NOT PROPOSE FEATURES THAT ALREADY EXIST)")
    sections.append("")
    sections.append("The following modules and features already exist in this codebase.")
    sections.append(
        "Before proposing new files or features, verify they don't duplicate existing ones."
    )
    sections.append("")

    # Extract quick reference table
    table_rows = _extract_table(content, "| What | Where |")
    if table_rows:
        # Parse paths from table and verify
        all_paths: list[str] = []
        for row in table_rows:
            cells = [c.strip().strip("`") for c in row.split("|") if c.strip()]
            if len(cells) >= 2:
                path = cells[1].strip().rstrip("/")
                if path and "/" in path:
                    all_paths.append(path)

        verified = _verify_paths(all_paths, root)

        sections.append("### Module Map")
        for row in table_rows:
            cells = [c.strip() for c in row.split("|") if c.strip()]
            if len(cells) >= 2:
                path = cells[1].strip().strip("`").rstrip("/")
                exists = verified.get(path, False)
                marker = "" if exists else " [MISSING]"
                key_files = cells[2] if len(cells) >= 3 else ""
                sections.append(f"- **{cells[0]}**: `{path}`{marker} — {key_files}")

        sections.append("")

    # Extract feature status
    feature_status = _extract_feature_status(content)
    if feature_status:
        sections.append("### Feature Status")
        sections.append(feature_status)
        sections.append("")

    inventory = "\n".join(sections)

    if len(inventory) > max_chars:
        inventory = inventory[:max_chars].rstrip() + "\n...[truncated]"

    return inventory


__all__ = [
    "CodebaseContextConfig",
    "CodebaseContextProvider",
    "build_static_inventory",
]
