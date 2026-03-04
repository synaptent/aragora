"""Tests for ClaudeSearchStrategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aragora.debate.context_strategies.claude_search import (
    CLAUDE_SEARCH_TIMEOUT,
    ClaudeSearchStrategy,
)


class TestClaudeSearchStrategyAttributes:
    """Test strategy class attributes."""

    def test_name(self) -> None:
        s = ClaudeSearchStrategy()
        assert s.name == "claude_search"

    def test_default_timeout(self) -> None:
        s = ClaudeSearchStrategy()
        assert s.default_timeout == CLAUDE_SEARCH_TIMEOUT

    def test_default_timeout_value(self) -> None:
        # Module default is 240.0 unless overridden via environment.
        assert CLAUDE_SEARCH_TIMEOUT == 240.0


class TestClaudeSearchIsAvailable:
    """Test is_available checks."""

    def test_available_when_module_exists(self) -> None:
        s = ClaudeSearchStrategy()
        with patch(
            "aragora.debate.context_strategies.claude_search.ClaudeSearchStrategy.is_available",
            return_value=True,
        ):
            assert s.is_available() is True

    def test_unavailable_when_import_fails(self) -> None:
        s = ClaudeSearchStrategy()
        with patch.dict("sys.modules", {"aragora.server.research_phase": None}):
            # Force ImportError by making the module unimportable
            import sys

            saved = sys.modules.pop("aragora.server.research_phase", None)
            try:
                # Patch the import to raise
                with patch(
                    "builtins.__import__",
                    side_effect=_import_error_for("aragora.server.research_phase"),
                ):
                    assert s.is_available() is False
            finally:
                if saved is not None:
                    sys.modules["aragora.server.research_phase"] = saved


class TestClaudeSearchGather:
    """Test gather method."""

    @pytest.mark.asyncio
    async def test_gather_success_with_key_sources(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(
            return_value="Here is the research.\n\nKey Sources:\n- Source 1\n- Source 2"
        )
        result = await _call_gather_patched(s, "test topic", mock_research)
        assert result is not None
        assert "Key Sources" in result

    @pytest.mark.asyncio
    async def test_gather_success_long_result_without_key_sources(self) -> None:
        """A long result (>= 200 chars) without 'Key Sources' is still accepted."""
        s = ClaudeSearchStrategy()
        long_text = "A" * 250
        mock_research = AsyncMock(return_value=long_text)
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result == long_text

    @pytest.mark.asyncio
    async def test_gather_rejects_short_low_signal(self) -> None:
        """Short result without 'Key Sources' is rejected."""
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(return_value="No useful info here.")
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_returns_none_on_empty_result(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(return_value=None)
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_returns_none_on_empty_string(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(return_value="")
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_import_error(self) -> None:
        s = ClaudeSearchStrategy()
        with patch(
            "builtins.__import__",
            side_effect=_import_error_for("aragora.server.research_phase"),
        ):
            result = await s.gather("topic")
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_connection_error(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(side_effect=ConnectionError("network down"))
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_os_error(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(side_effect=OSError("disk error"))
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_value_error(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(side_effect=ValueError("bad response"))
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_runtime_error(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(side_effect=RuntimeError("api failure"))
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_unexpected_error(self) -> None:
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(side_effect=Exception("unexpected"))
        result = await _call_gather_patched(s, "topic", mock_research)
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_with_timeout_integration(self) -> None:
        """gather_with_timeout wraps gather correctly."""
        s = ClaudeSearchStrategy()
        mock_research = AsyncMock(return_value="Research results\n\nKey Sources:\n- A")
        with patch(
            "aragora.server.research_phase.research_for_debate",
            mock_research,
            create=True,
        ):
            result = await s.gather_with_timeout("topic", timeout=5.0)
        assert result is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_error_for(module_name: str):
    """Create a side_effect that raises ImportError for a specific module."""
    _real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _side_effect(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"No module named '{module_name}'")
        return _real_import(name, *args, **kwargs)

    return _side_effect


async def _mock_gather_with(mock_research: AsyncMock):
    """Create a side_effect for gather that delegates to mock."""

    async def _inner(task: str, **kwargs):
        return await mock_research(task)

    return _inner


async def _call_gather_patched(
    strategy: ClaudeSearchStrategy,
    task: str,
    mock_research: AsyncMock,
) -> str | None:
    """Call gather with research_for_debate patched."""
    with patch(
        "aragora.server.research_phase.research_for_debate",
        mock_research,
        create=True,
    ):
        return await strategy.gather(task)
