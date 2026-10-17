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
import re
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
        from aragora.rlm.context_builder import NomicContextBuilder

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


def build_static_inventory(
    repo_root: str | None = None,
    max_chars: int = 20_000,
) -> str:
    """Build a compact deterministic codebase inventory from CLAUDE.md.

    This helper is synchronous and intentionally lightweight so it can be used
    in CLI preflight paths without triggering index builds.
    """
    root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        logger.debug("Static inventory skipped: missing %s", claude_md)
        return ""

    try:
        content = claude_md.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Static inventory read failed: %s", e)
        return ""

    lines = content.splitlines()
    quick_reference_table = _extract_quick_reference_table(lines)
    feature_status = _extract_feature_status(lines)
    codebase_scale = _extract_codebase_scale(lines)

    sections: list[str] = []
    if quick_reference_table:
        verified = _verify_table_paths(quick_reference_table, root)
        sections.append("### Quick Reference (Verified)\n" + "\n".join(verified))
    if feature_status:
        sections.append("### Feature Status\n" + "\n".join(feature_status))
    if codebase_scale:
        sections.append("### Codebase Scale\n" + codebase_scale)

    if not sections:
        return ""

    result = (
        "## CODEBASE INVENTORY (DO NOT REINVENT EXISTING MODULES)\n"
        "These modules/features already exist in this repository.\n"
        "Propose modifications against existing files before proposing new ones.\n\n"
        + "\n\n".join(sections)
    )
    if max_chars > 0 and len(result) > max_chars:
        return result[:max_chars].rstrip() + "\n...[truncated]"
    return result


def _extract_quick_reference_table(lines: list[str]) -> list[str]:
    """Extract the markdown table under '## Quick Reference'."""
    collected: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == "## Quick Reference":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        if line.lstrip().startswith("|"):
            collected.append(line)
        elif collected and not line.strip():
            break
    return collected


def _extract_feature_status(lines: list[str]) -> list[str]:
    """Extract Core/Integrated/Enterprise status bullets from CLAUDE.md."""
    collected: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Core (stable):**"):
            started = True
        if not started:
            continue
        collected.append(line)
        if stripped.startswith("See `docs/STATUS.md`"):
            break
    return [line for line in collected if line.strip()]


def _extract_codebase_scale(lines: list[str]) -> str:
    """Extract the first `**Codebase Scale:**` line."""
    for line in lines:
        if line.startswith("**Codebase Scale:**"):
            return line.strip()
    return ""


def _verify_table_paths(table_lines: list[str], repo_root: Path) -> list[str]:
    """Annotate table rows when referenced paths do not exist."""
    verified: list[str] = []
    for line in table_lines:
        stripped = line.strip()
        if stripped.startswith("| What ") or stripped.startswith("|---"):
            verified.append(line)
            continue
        missing = []
        for raw in re.findall(r"`([^`]+)`", line):
            candidate = raw.strip()
            if "/" not in candidate:
                continue
            candidate = candidate.rstrip(",")
            if not (repo_root / candidate).exists():
                missing.append(candidate)
        if missing:
            verified.append(f"{line} [MISSING: {', '.join(missing)}]")
        else:
            verified.append(line)
    return verified


__all__ = [
    "CodebaseContextConfig",
    "CodebaseContextProvider",
    "build_static_inventory",
]
