"""
Tests for aragora.types.protocols - structural typing protocols.

Tests cover:
- EventEmitterProtocol runtime checking
- StorageProtocol runtime checking
- CacheProtocol runtime checking
- AgentProtocol runtime checking
- MemoryProtocol runtime checking
- Type alias definitions
- Protocol satisfaction with conforming classes
- Protocol rejection of non-conforming classes
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aragora.types.protocols import (
    AgentProtocol,
    CacheProtocol,
    EventData,
    EventEmitterProtocol,
    EventHandlerProtocol,
    MemoryProtocol,
    StorageProtocol,
    SyncEventHandlerProtocol,
)


# =============================================================================
# Conforming implementations for testing
# =============================================================================


class ConformingEventEmitter:
    """A class that satisfies EventEmitterProtocol."""

    def __init__(self) -> None:
        self._handlers: dict[str, list] = {}

    def subscribe(self, event_type: str, handler: EventHandlerProtocol) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_sync(self, event_type: str, handler: SyncEventHandlerProtocol) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandlerProtocol) -> bool:
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)
            return True
        return False

    async def emit(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        pass

    def emit_sync(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        pass


class ConformingStorage:
    """A class that satisfies StorageProtocol."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        return self._data.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self._data


class ConformingCache:
    """A class that satisfies CacheProtocol."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._cache[key] = value

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()


class ConformingAgent:
    """A class that satisfies AgentProtocol."""

    @property
    def name(self) -> str:
        return "test-agent"

    @property
    def model(self) -> str:
        return "test-model-v1"

    async def generate(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        return f"Response to: {prompt}"


class ConformingMemory:
    """A class that satisfies MemoryProtocol."""

    def __init__(self) -> None:
        self._memories: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        self._counter += 1
        mid = f"mem-{self._counter}"
        self._memories[mid] = {"content": content, "metadata": metadata or {}}
        return mid

    async def retrieve(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return list(self._memories.values())[:limit]

    async def forget(self, memory_id: str) -> bool:
        return self._memories.pop(memory_id, None) is not None


class NonConformingClass:
    """A class that does NOT satisfy any protocol."""

    def unrelated_method(self) -> str:
        return "not a protocol"


class PartialEventEmitter:
    """Has some methods but not all of EventEmitterProtocol."""

    def subscribe(self, event_type: str, handler: Any) -> None:
        pass

    # Missing subscribe_sync, unsubscribe, emit, emit_sync


# =============================================================================
# EventEmitterProtocol Tests
# =============================================================================


class TestEventEmitterProtocol:
    """Tests for EventEmitterProtocol runtime checking."""

    def test_conforming_class_is_instance(self):
        """Conforming class should pass isinstance check."""
        emitter = ConformingEventEmitter()
        assert isinstance(emitter, EventEmitterProtocol)

    def test_non_conforming_class_is_not_instance(self):
        """Non-conforming class should fail isinstance check."""
        obj = NonConformingClass()
        assert not isinstance(obj, EventEmitterProtocol)

    def test_partial_implementation_is_not_instance(self):
        """Partial implementation should fail isinstance check."""
        obj = PartialEventEmitter()
        assert not isinstance(obj, EventEmitterProtocol)

    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self):
        """Test basic subscribe/emit flow with conforming class."""
        emitter = ConformingEventEmitter()
        handler = AsyncMock()
        emitter.subscribe("test_event", handler)
        assert "test_event" in emitter._handlers
        assert handler in emitter._handlers["test_event"]

    def test_subscribe_sync(self):
        """Test sync handler subscription."""
        emitter = ConformingEventEmitter()

        def handler(event):
            return None

        emitter.subscribe_sync("sync_event", handler)
        assert handler in emitter._handlers["sync_event"]

    def test_unsubscribe(self):
        """Test handler removal."""
        emitter = ConformingEventEmitter()
        handler = AsyncMock()
        emitter.subscribe("event", handler)
        result = emitter.unsubscribe("event", handler)
        assert result is True
        assert handler not in emitter._handlers["event"]


# =============================================================================
# StorageProtocol Tests
# =============================================================================


class TestStorageProtocol:
    """Tests for StorageProtocol runtime checking."""

    def test_conforming_class_is_instance(self):
        """Conforming storage should pass isinstance check."""
        storage = ConformingStorage()
        assert isinstance(storage, StorageProtocol)

    def test_non_conforming_is_not_instance(self):
        """Non-conforming class should fail isinstance check."""
        assert not isinstance(NonConformingClass(), StorageProtocol)

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Test basic set/get operations."""
        storage = ConformingStorage()
        await storage.set("key1", "value1")
        result = await storage.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        """Test get returns None for missing key."""
        storage = ConformingStorage()
        result = await storage.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test delete removes key."""
        storage = ConformingStorage()
        await storage.set("key1", "value1")
        result = await storage.delete("key1")
        assert result is True
        assert await storage.get("key1") is None

    @pytest.mark.asyncio
    async def test_exists(self):
        """Test exists check."""
        storage = ConformingStorage()
        assert await storage.exists("key1") is False
        await storage.set("key1", "value1")
        assert await storage.exists("key1") is True


# =============================================================================
# CacheProtocol Tests
# =============================================================================


class TestCacheProtocol:
    """Tests for CacheProtocol runtime checking."""

    def test_conforming_class_is_instance(self):
        """Conforming cache should pass isinstance check."""
        cache = ConformingCache()
        assert isinstance(cache, CacheProtocol)

    def test_non_conforming_is_not_instance(self):
        """Non-conforming class should fail isinstance check."""
        assert not isinstance(NonConformingClass(), CacheProtocol)

    def test_set_and_get(self):
        """Test basic cache operations."""
        cache = ConformingCache()
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_delete(self):
        """Test cache deletion."""
        cache = ConformingCache()
        cache.set("k", "v")
        cache.delete("k")
        assert cache.get("k") is None

    def test_clear(self):
        """Test cache clear."""
        cache = ConformingCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


# =============================================================================
# AgentProtocol Tests
# =============================================================================


class TestAgentProtocol:
    """Tests for AgentProtocol runtime checking."""

    def test_conforming_class_is_instance(self):
        """Conforming agent should pass isinstance check."""
        agent = ConformingAgent()
        assert isinstance(agent, AgentProtocol)

    def test_non_conforming_is_not_instance(self):
        """Non-conforming class should fail isinstance check."""
        assert not isinstance(NonConformingClass(), AgentProtocol)

    def test_name_property(self):
        """Test agent name property."""
        agent = ConformingAgent()
        assert agent.name == "test-agent"

    def test_model_property(self):
        """Test agent model property."""
        agent = ConformingAgent()
        assert agent.model == "test-model-v1"

    @pytest.mark.asyncio
    async def test_generate(self):
        """Test agent generate method."""
        agent = ConformingAgent()
        result = await agent.generate("Hello")
        assert "Hello" in result


# =============================================================================
# MemoryProtocol Tests
# =============================================================================


class TestMemoryProtocol:
    """Tests for MemoryProtocol runtime checking."""

    def test_conforming_class_is_instance(self):
        """Conforming memory should pass isinstance check."""
        memory = ConformingMemory()
        assert isinstance(memory, MemoryProtocol)

    def test_non_conforming_is_not_instance(self):
        """Non-conforming class should fail isinstance check."""
        assert not isinstance(NonConformingClass(), MemoryProtocol)

    @pytest.mark.asyncio
    async def test_store_returns_id(self):
        """Test store returns a memory ID."""
        memory = ConformingMemory()
        mid = await memory.store("test content")
        assert mid.startswith("mem-")

    @pytest.mark.asyncio
    async def test_retrieve(self):
        """Test retrieve returns stored memories."""
        memory = ConformingMemory()
        await memory.store("content 1")
        await memory.store("content 2")
        results = await memory.retrieve("query")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_retrieve_with_limit(self):
        """Test retrieve respects limit."""
        memory = ConformingMemory()
        for i in range(5):
            await memory.store(f"content {i}")
        results = await memory.retrieve("query", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_forget(self):
        """Test forget removes memory."""
        memory = ConformingMemory()
        mid = await memory.store("to forget")
        result = await memory.forget(mid)
        assert result is True

    @pytest.mark.asyncio
    async def test_forget_nonexistent(self):
        """Test forget returns False for nonexistent ID."""
        memory = ConformingMemory()
        result = await memory.forget("nonexistent")
        assert result is False


# =============================================================================
# Type Alias Tests
# =============================================================================


class TestTypeAliases:
    """Tests for type alias definitions."""

    def test_event_data_is_dict_type(self):
        """EventData should be a dict alias."""
        data: EventData = {"key": "value", "count": 42}
        assert isinstance(data, dict)

    def test_event_handler_is_callable(self):
        """EventHandlerProtocol should accept async callables."""

        async def handler(event: Any) -> None:
            pass

        # Just verify the type alias exists and is callable
        h: EventHandlerProtocol = handler
        assert callable(h)

    def test_sync_event_handler_is_callable(self):
        """SyncEventHandlerProtocol should accept sync callables."""

        def handler(event: Any) -> None:
            pass

        h: SyncEventHandlerProtocol = handler
        assert callable(h)


# =============================================================================
# Module Import Tests
# =============================================================================


class TestModuleExports:
    """Tests for aragora.types module exports."""

    def test_legacy_protocol_paths_preserve_canonical_identity(self):
        """Existing protocol shims should return canonical objects unchanged."""
        from aragora.core_protocols import StorageBackend as CoreStorageBackend
        from aragora.protocols import AgentProtocol as CanonicalAgentProtocol
        from aragora.protocols import StorageBackend as CanonicalStorageBackend
        from aragora.type_protocols import AgentProtocol as TypeAgentProtocol

        assert CoreStorageBackend is CanonicalStorageBackend
        assert TypeAgentProtocol is CanonicalAgentProtocol

    def test_types_protocols_warns_with_legacy_path(self):
        """Reloading the legacy types module should emit its deprecation warning."""
        legacy = importlib.import_module("aragora.types.protocols")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.reload(legacy)

        assert any(
            issubclass(item.category, DeprecationWarning) and "types.protocols" in str(item.message)
            for item in caught
        )

    def test_types_protocols_shared_exports_preserve_identity(self):
        """Non-conflicting legacy contracts should be canonical package exports."""
        import aragora.protocols as canonical
        import aragora.types.protocols as legacy

        shared = (
            "CacheProtocol",
            "StorageProtocol",
            "EventData",
            "EventHandlerProtocol",
            "SyncEventHandlerProtocol",
        )

        assert all(getattr(canonical, name) is getattr(legacy, name) for name in shared)

    def test_types_protocols_incompatible_contracts_remain_distinct(self):
        """Legacy contracts with incompatible methods must not replace newer ones."""
        import aragora.protocols as canonical
        import aragora.types.protocols as legacy

        incompatible = ("AgentProtocol", "MemoryProtocol", "EventEmitterProtocol")
        assert all(
            getattr(legacy, name).__module__.startswith("aragora.protocols.")
            for name in incompatible
        )
        assert all(getattr(canonical, name) is not getattr(legacy, name) for name in incompatible)
        assert hasattr(legacy.AgentProtocol, "generate")
        assert hasattr(legacy.MemoryProtocol, "retrieve")
        assert hasattr(legacy.EventEmitterProtocol, "subscribe")
        assert hasattr(canonical.AgentProtocol, "respond")
        assert not hasattr(canonical.AgentProtocol, "generate")
        assert hasattr(canonical.MemoryProtocol, "query")
        assert not hasattr(canonical.MemoryProtocol, "retrieve")
        assert hasattr(canonical.EventEmitterProtocol, "on")
        assert not hasattr(canonical.EventEmitterProtocol, "subscribe")

    def test_import_from_package(self):
        """Test importing from aragora.types package."""
        from aragora.protocols import LegacyEventEmitterProtocol
        from aragora.types import (
            EventEmitterProtocol,
            EventHandlerProtocol,
            SyncEventHandlerProtocol,
        )

        assert EventEmitterProtocol is LegacyEventEmitterProtocol
        assert EventHandlerProtocol is not None
        assert SyncEventHandlerProtocol is not None

    def test_import_from_protocols_module(self):
        """Test importing directly from protocols module."""
        from aragora.types.protocols import (
            AgentProtocol,
            CacheProtocol,
            MemoryProtocol,
            StorageProtocol,
        )

        assert AgentProtocol is not None
        assert CacheProtocol is not None
        assert MemoryProtocol is not None
        assert StorageProtocol is not None

    def test_protocols_are_runtime_checkable(self):
        """All protocols should be runtime_checkable."""
        for proto in [
            EventEmitterProtocol,
            StorageProtocol,
            CacheProtocol,
            AgentProtocol,
            MemoryProtocol,
        ]:
            assert hasattr(proto, "__protocol_attrs__") or hasattr(proto, "_is_runtime_protocol"), (
                f"{proto.__name__} should be runtime_checkable"
            )
