"""Tests for EvidenceStrategy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.context_strategies.evidence import (
    EVIDENCE_TIMEOUT,
    MAX_EVIDENCE_CACHE_SIZE,
    EvidenceStrategy,
)
from aragora.runtime import connector_factory


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeEvidencePack:
    """Minimal stand-in for EvidencePack."""

    snippets: list[str]
    _context: str = "formatted evidence"

    def to_context_string(self) -> str:
        return self._context


@dataclass
class _EmptyEvidencePack:
    """Evidence pack with no snippets."""

    snippets: list[str]

    def __init__(self) -> None:
        self.snippets = []

    def to_context_string(self) -> str:
        return ""


class _FakeCollector:
    """Minimal stand-in for EvidenceCollector."""

    def __init__(self, pack: Any = None) -> None:
        self._pack = pack or _FakeEvidencePack(snippets=["s1", "s2"])
        self._connectors: dict[str, Any] = {}

    def add_connector(self, name: str, connector: Any) -> None:
        self._connectors[name] = connector

    async def collect_evidence(self, task: str, **kwargs: Any) -> Any:
        return self._pack


# ---------------------------------------------------------------------------
# Attribute tests
# ---------------------------------------------------------------------------


class TestEvidenceStrategyAttributes:
    """Test class-level attributes and init."""

    def test_name(self) -> None:
        s = EvidenceStrategy()
        assert s.name == "evidence"

    def test_default_timeout(self) -> None:
        s = EvidenceStrategy()
        assert s.default_timeout == EVIDENCE_TIMEOUT

    def test_max_cache_size(self) -> None:
        assert EvidenceStrategy.max_cache_size == MAX_EVIDENCE_CACHE_SIZE

    def test_default_init(self) -> None:
        s = EvidenceStrategy()
        assert s._project_root == Path.cwd()
        assert s._prompt_builder is None
        assert s._evidence_store_callback is None
        assert s._evidence_packs == {}

    def test_custom_init(self) -> None:
        root = Path("/tmp/project")
        pb = MagicMock()
        cb = MagicMock()
        s = EvidenceStrategy(project_root=root, prompt_builder=pb, evidence_store_callback=cb)
        assert s._project_root == root
        assert s._prompt_builder is pb
        assert s._evidence_store_callback is cb


class TestEvidenceStrategyHelpers:
    """Test helper methods."""

    def test_set_prompt_builder(self) -> None:
        s = EvidenceStrategy()
        pb = MagicMock()
        s.set_prompt_builder(pb)
        assert s._prompt_builder is pb

    def test_get_evidence_pack_miss(self) -> None:
        s = EvidenceStrategy()
        assert s.get_evidence_pack("unknown-task") is None

    def test_get_evidence_pack_hit(self) -> None:
        s = EvidenceStrategy()
        pack = _FakeEvidencePack(snippets=["a"])
        key = s._get_cache_key("my-task")
        s._evidence_packs[key] = pack
        assert s.get_evidence_pack("my-task") is pack


class TestEvidenceStrategyIsAvailable:
    """Test is_available."""

    def test_available_when_collector_importable(self) -> None:
        s = EvidenceStrategy()
        # If EvidenceCollector can be imported, it's available
        try:
            from aragora.evidence.collector import EvidenceCollector  # noqa: F401

            assert s.is_available() is True
        except ImportError:
            # Module doesn't exist in test env -> falls through to unavailable
            assert s.is_available() is False

    def test_unavailable_when_import_fails(self) -> None:
        s = EvidenceStrategy()
        with patch(
            "builtins.__import__",
            side_effect=_import_error_for("aragora.evidence.collector"),
        ):
            assert s.is_available() is False


# ---------------------------------------------------------------------------
# gather tests
# ---------------------------------------------------------------------------


class TestEvidenceStrategyGather:
    """Test gather method."""

    @pytest.mark.asyncio
    async def test_gather_success(self) -> None:
        s = EvidenceStrategy()
        pack = _FakeEvidencePack(snippets=["s1", "s2"], _context="web evidence")
        collector = _FakeCollector(pack=pack)

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather("test topic")

        assert result is not None
        assert "EVIDENCE CONTEXT" in result
        assert "web evidence" in result

    @pytest.mark.asyncio
    async def test_gather_caches_evidence_pack(self) -> None:
        s = EvidenceStrategy()
        pack = _FakeEvidencePack(snippets=["s1"])
        collector = _FakeCollector(pack=pack)

        with _patch_evidence_imports(collector, web_available=True):
            await s.gather("my-task")

        assert s.get_evidence_pack("my-task") is pack

    @pytest.mark.asyncio
    async def test_gather_updates_prompt_builder(self) -> None:
        pb = MagicMock()
        s = EvidenceStrategy(prompt_builder=pb)
        pack = _FakeEvidencePack(snippets=["s1"])
        collector = _FakeCollector(pack=pack)

        with _patch_evidence_imports(collector, web_available=True):
            await s.gather("task")

        pb.set_evidence_pack.assert_called_once_with(pack)

    @pytest.mark.asyncio
    async def test_gather_calls_store_callback(self) -> None:
        cb = MagicMock()
        s = EvidenceStrategy(evidence_store_callback=cb)
        pack = _FakeEvidencePack(snippets=["s1", "s2"])
        collector = _FakeCollector(pack=pack)

        with _patch_evidence_imports(collector, web_available=True):
            await s.gather("task")

        cb.assert_called_once_with(["s1", "s2"], "task")

    @pytest.mark.asyncio
    async def test_gather_no_connectors_returns_none(self) -> None:
        s = EvidenceStrategy()
        collector = _FakeCollector()

        with _patch_evidence_imports(
            collector,
            web_available=False,
            github_available=False,
            local_available=False,
        ):
            result = await s.gather("task")

        assert result is None

    @pytest.mark.asyncio
    async def test_gather_empty_snippets_returns_none(self) -> None:
        s = EvidenceStrategy()
        collector = _FakeCollector(pack=_EmptyEvidencePack())

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather("task")

        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_import_error(self) -> None:
        s = EvidenceStrategy()
        with patch(
            "builtins.__import__",
            side_effect=_import_error_for("aragora.evidence.collector"),
        ):
            result = await s.gather("task")
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_connection_error(self) -> None:
        s = EvidenceStrategy()
        collector = MagicMock()
        collector.add_connector = MagicMock()
        collector.collect_evidence = AsyncMock(side_effect=ConnectionError("down"))

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather("task")
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_value_error(self) -> None:
        s = EvidenceStrategy()
        collector = MagicMock()
        collector.add_connector = MagicMock()
        collector.collect_evidence = AsyncMock(side_effect=ValueError("bad"))

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather("task")
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_handles_unexpected_error(self) -> None:
        s = EvidenceStrategy()
        collector = MagicMock()
        collector.add_connector = MagicMock()
        collector.collect_evidence = AsyncMock(side_effect=Exception("weird"))

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather("task")
        assert result is None

    @pytest.mark.asyncio
    async def test_gather_with_timeout_integration(self) -> None:
        s = EvidenceStrategy()
        pack = _FakeEvidencePack(snippets=["s1"])
        collector = _FakeCollector(pack=pack)

        with _patch_evidence_imports(collector, web_available=True):
            result = await s.gather_with_timeout("task", timeout=5.0)
        assert result is not None


class TestEvidenceCachingBehavior:
    """Test inherited caching from CachingStrategy."""

    def test_cache_key_consistency(self) -> None:
        s = EvidenceStrategy()
        k1 = s._get_cache_key("task-a")
        k2 = s._get_cache_key("task-a")
        assert k1 == k2

    def test_set_and_get_cached(self) -> None:
        s = EvidenceStrategy()
        s.set_cached("task-1", "cached-value")
        assert s.get_cached("task-1") == "cached-value"

    def test_clear_cache(self) -> None:
        s = EvidenceStrategy()
        s.set_cached("task-1", "v1")
        s.clear_cache()
        assert s.get_cached("task-1") is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_real_import = __import__


def _import_error_for(module_name: str):
    """Side effect that raises ImportError for a specific module."""

    def _side_effect(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"No module named '{module_name}'")
        return _real_import(name, *args, **kwargs)

    return _side_effect


class _patch_evidence_imports:
    """Patches EvidenceCollector and serves the connectors through the connector factory hook.

    An unavailable connector raises ImportError from the factory, as a missing module does.
    """

    def __init__(
        self,
        collector: Any,
        web_available: bool = False,
        github_available: bool = False,
        local_available: bool = False,
    ) -> None:
        self._collector = collector
        self._available = {
            "web_search": web_available,
            "github": github_available,
            "local_docs": local_available,
        }
        self._patches: list[Any] = []

    def _build(self, kind: str, /, **kwargs: Any) -> Any:
        if not self._available.get(kind):
            raise ImportError(f"No connector for {kind!r}")
        return MagicMock()

    def __enter__(self) -> _patch_evidence_imports:
        collector_mod = MagicMock()
        collector_mod.EvidenceCollector = MagicMock(return_value=self._collector)
        self._patches = [
            patch.dict("sys.modules", {"aragora.evidence.collector": collector_mod}),
            patch.object(connector_factory, "_factory", self._build),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args: Any) -> None:
        for p in reversed(self._patches):
            p.stop()
