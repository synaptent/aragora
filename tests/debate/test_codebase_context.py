"""Tests for CodebaseContextProvider - thin wrapper for codebase context in debates."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.debate.codebase_context import (
    CodebaseContextConfig,
    CodebaseContextProvider,
    build_static_inventory,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestCodebaseContextConfig:
    def test_defaults(self):
        config = CodebaseContextConfig()
        assert config.codebase_path is None
        assert config.max_context_tokens == 500
        assert config.persist_to_km is False
        assert config.include_tests is False

    def test_custom_values(self):
        config = CodebaseContextConfig(
            codebase_path="/repo",
            max_context_tokens=1000,
            persist_to_km=True,
            include_tests=True,
        )
        assert config.codebase_path == "/repo"
        assert config.max_context_tokens == 1000
        assert config.persist_to_km is True


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class TestCodebaseContextProvider:
    def test_init_default_config(self):
        provider = CodebaseContextProvider()
        assert provider.config.codebase_path is None

    def test_init_custom_config(self):
        config = CodebaseContextConfig(codebase_path=".")
        provider = CodebaseContextProvider(config=config)
        assert provider.config.codebase_path == "."

    @pytest.mark.asyncio
    async def test_build_context_no_path(self):
        provider = CodebaseContextProvider()
        result = await provider.build_context("some task")
        assert result == ""

    @pytest.mark.asyncio
    async def test_build_context_with_mock_builder(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path))
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(
            return_value="# Codebase (100 files)\naragora/debate/ - 50 files"
        )

        with patch(
            "aragora.nomic.context_builder.NomicContextBuilder",
            return_value=mock_builder,
        ):
            result = await provider.build_context("refactor debate module")
            assert "Codebase" in result or "aragora" in result

    @pytest.mark.asyncio
    async def test_build_context_caching(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path), cache_ttl_seconds=300)
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="cached context")

        with patch(
            "aragora.nomic.context_builder.NomicContextBuilder",
            return_value=mock_builder,
        ):
            result1 = await provider.build_context("task 1")
            result2 = await provider.build_context("task 2")

            # Should only be called once (second call uses cache)
            assert mock_builder.build_debate_context.call_count == 1
            assert result1 == result2

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path))
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="fresh context")

        with patch(
            "aragora.nomic.context_builder.NomicContextBuilder",
            return_value=mock_builder,
        ):
            await provider.build_context("task")
            provider.invalidate_cache()
            await provider.build_context("task")

            assert mock_builder.build_debate_context.call_count == 2

    @pytest.mark.asyncio
    async def test_build_context_error_fallback(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path))
        provider = CodebaseContextProvider(config=config)

        with patch(
            "aragora.nomic.context_builder.NomicContextBuilder",
            side_effect=RuntimeError("build failed"),
        ):
            result = await provider.build_context("task")
            assert result == ""

    @pytest.mark.asyncio
    async def test_persist_to_km(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path), persist_to_km=True)
        provider = CodebaseContextProvider(config=config)

        mock_builder = AsyncMock()
        mock_builder.build_debate_context = AsyncMock(return_value="context")
        mock_adapter = AsyncMock()
        mock_adapter.crawl_and_sync = AsyncMock(return_value=5)

        with (
            patch(
                "aragora.nomic.context_builder.NomicContextBuilder",
                return_value=mock_builder,
            ),
            patch(
                "aragora.knowledge.mound.adapters.codebase_adapter.CodebaseAdapter",
                return_value=mock_adapter,
            ),
        ):
            await provider.build_context("task")
            mock_adapter.crawl_and_sync.assert_called_once()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_summary_empty_cache(self):
        provider = CodebaseContextProvider()
        assert provider.get_summary() == ""

    @pytest.mark.asyncio
    async def test_summary_truncation(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path), max_context_tokens=10)
        provider = CodebaseContextProvider(config=config)

        # Manually set cache
        long_content = "x" * 10000
        from aragora.debate.codebase_context import _CacheEntry

        provider._cache = _CacheEntry(context=long_content)

        summary = provider.get_summary()
        # 10 tokens * 4 chars = 40 chars max + truncation marker
        assert len(summary) < 100
        assert "truncated" in summary

    @pytest.mark.asyncio
    async def test_summary_short_content(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path), max_context_tokens=500)
        provider = CodebaseContextProvider(config=config)

        from aragora.debate.codebase_context import _CacheEntry

        provider._cache = _CacheEntry(context="short context")

        summary = provider.get_summary()
        assert summary == "short context"

    @pytest.mark.asyncio
    async def test_summary_custom_max_tokens(self, tmp_path):
        config = CodebaseContextConfig(codebase_path=str(tmp_path))
        provider = CodebaseContextProvider(config=config)

        from aragora.debate.codebase_context import _CacheEntry

        provider._cache = _CacheEntry(context="x" * 5000)

        summary = provider.get_summary(max_tokens=50)
        assert len(summary) <= 250  # 50 * 4 + truncation


# ---------------------------------------------------------------------------
# build_static_inventory
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a minimal fake repo with CLAUDE.md."""
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        """\
## Quick Reference

| What | Where | Key Files |
|------|-------|-----------|
| Debate engine | `aragora/debate/` | `orchestrator.py`, `consensus.py` |
| CLI | `aragora/cli/` | `main.py`, `parser.py` |
| Memory | `aragora/memory/` | `continuum/`, `consensus.py` |

## Feature Status

**Core (stable):**
- Debate orchestration (Arena, consensus, convergence)
- Memory systems (CritiqueStore, ContinuumMemory)
- ELO rankings and tournaments

**Integrated:**
- Knowledge Mound - STABLE Phase A2
- Pulse (trending topics) - STABLE

**Enterprise (production-ready):**
- Authentication - OIDC/SAML SSO, MFA
""",
        encoding="utf-8",
    )
    # Create some dirs to make paths "exist"
    (tmp_path / "aragora" / "debate").mkdir(parents=True)
    (tmp_path / "aragora" / "cli").mkdir(parents=True)
    # aragora/memory/ intentionally NOT created to test [MISSING]
    return tmp_path


class TestBuildStaticInventory:
    def test_returns_nonempty_for_valid_repo(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo))
        assert result
        assert "CODEBASE INVENTORY" in result

    def test_contains_module_map(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo))
        assert "Module Map" in result
        assert "Debate engine" in result
        assert "CLI" in result

    def test_verifies_paths(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo))
        # debate/ and cli/ exist, memory/ does not
        assert "aragora/debate" in result
        assert "aragora/cli" in result
        assert "[MISSING]" in result  # memory/ doesn't exist

    def test_contains_feature_status(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo))
        assert "Feature Status" in result
        assert "Core (stable)" in result
        assert "Debate orchestration" in result

    def test_max_chars_truncation(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo), max_chars=100)
        assert len(result) <= 115  # small buffer for truncation marker
        assert result.endswith("[truncated]")

    def test_missing_claude_md(self, tmp_path):
        result = build_static_inventory(repo_root=str(tmp_path))
        assert result == ""

    def test_do_not_propose_warning(self, fake_repo):
        result = build_static_inventory(repo_root=str(fake_repo))
        assert "DO NOT PROPOSE FEATURES THAT ALREADY EXIST" in result

    def test_real_repo_if_available(self):
        """Integration test: runs against the real repo if CLAUDE.md exists."""
        repo = Path(__file__).resolve().parent.parent.parent
        if not (repo / "CLAUDE.md").exists():
            pytest.skip("Not running from within aragora repo")
        result = build_static_inventory(repo_root=str(repo))
        assert len(result) > 500
        assert "CODEBASE INVENTORY" in result
        assert "Debate engine" in result
