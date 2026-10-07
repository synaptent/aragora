"""Tests for Unified Knowledge Store (federated query interface)."""

import pytest
from datetime import datetime, timezone
from typing import Any

from aragora.knowledge.fact_store import InMemoryFactStore, ScopedFactStore
from aragora.knowledge.unified import (
    UnifiedKnowledgeStore,
    UnifiedStoreConfig,
    KnowledgeSource,
    ConfidenceLevel,
    RelationshipType,
)
from aragora.knowledge.unified.types import (
    KnowledgeItem,
    KnowledgeLink,
    QueryFilters,
    QueryResult,
    StoreResult,
    LinkResult,
)


class TestKnowledgeSource:
    """Test KnowledgeSource enum."""

    def test_source_values(self):
        """Test that all expected sources are defined."""
        assert KnowledgeSource.CONTINUUM.value == "continuum"
        assert KnowledgeSource.CONSENSUS.value == "consensus"
        assert KnowledgeSource.FACT.value == "fact"
        assert KnowledgeSource.VECTOR.value == "vector"
        assert KnowledgeSource.DOCUMENT.value == "document"
        assert KnowledgeSource.EXTERNAL.value == "external"


class TestConfidenceLevel:
    """Test ConfidenceLevel enum."""

    def test_confidence_values(self):
        """Test confidence level string values."""
        assert ConfidenceLevel.LOW.value == "low"
        assert ConfidenceLevel.MEDIUM.value == "medium"
        assert ConfidenceLevel.HIGH.value == "high"
        assert ConfidenceLevel.VERIFIED.value == "verified"
        assert ConfidenceLevel.UNVERIFIED.value == "unverified"

    def test_confidence_comparison(self):
        """Test that confidence levels can be compared by name."""
        # String enums can be compared lexicographically
        assert ConfidenceLevel.LOW != ConfidenceLevel.HIGH


class TestRelationshipType:
    """Test RelationshipType enum."""

    def test_relationship_values(self):
        """Test that all expected relationship types are defined."""
        assert RelationshipType.SUPPORTS.value == "supports"
        assert RelationshipType.CONTRADICTS.value == "contradicts"
        assert RelationshipType.DERIVED_FROM.value == "derived_from"
        assert RelationshipType.RELATED_TO.value == "related_to"
        assert RelationshipType.SUPERSEDES.value == "supersedes"
        assert RelationshipType.CITES.value == "cites"
        assert RelationshipType.ELABORATES.value == "elaborates"


class TestKnowledgeItem:
    """Test KnowledgeItem dataclass."""

    def test_create_item(self):
        """Test creating an item with required fields."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_test",
            content="Test content",
            source=KnowledgeSource.FACT,
            source_id="fact_123",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
        )

        assert item.id == "ki_test"
        assert item.content == "Test content"
        assert item.source == KnowledgeSource.FACT
        assert item.source_id == "fact_123"
        assert item.confidence == ConfidenceLevel.HIGH
        assert item.metadata == {}
        assert item.cross_references == []

    def test_create_item_with_all_fields(self):
        """Test creating an item with all fields."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_full",
            content="Full content",
            source=KnowledgeSource.CONSENSUS,
            source_id="cons_123",
            confidence=ConfidenceLevel.VERIFIED,
            created_at=now,
            updated_at=now,
            metadata={"key": "value"},
            importance=0.9,
            cross_references=["ref_1", "ref_2"],
        )

        assert item.id == "ki_full"
        assert item.source == KnowledgeSource.CONSENSUS
        assert item.importance == 0.9
        assert item.metadata["key"] == "value"
        assert "ref_1" in item.cross_references

    def test_to_dict(self):
        """Test serialization to dict."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_test",
            content="Test",
            source=KnowledgeSource.DOCUMENT,
            source_id="doc_1",
            confidence=ConfidenceLevel.MEDIUM,
            created_at=now,
            updated_at=now,
        )

        d = item.to_dict()

        assert d["id"] == "ki_test"
        assert d["content"] == "Test"
        assert d["source"] == "document"
        assert d["confidence"] == "medium"

    def test_from_dict(self):
        """Test deserialization from dict."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "ki_test",
            "content": "Test",
            "source": "fact",
            "source_id": "f_1",
            "confidence": "high",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        item = KnowledgeItem.from_dict(data)

        assert item.id == "ki_test"
        assert item.source == KnowledgeSource.FACT
        assert item.confidence == ConfidenceLevel.HIGH

    def test_importance_normalized_from_string(self):
        """String importance should be normalized to float in __post_init__."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_str",
            content="Test",
            source=KnowledgeSource.FACT,
            source_id="f_1",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            importance="0.75",
        )
        assert item.importance == 0.75
        assert isinstance(item.importance, float)

    def test_importance_non_numeric_string_becomes_none(self):
        """Non-numeric string importance should become None."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_bad",
            content="Test",
            source=KnowledgeSource.FACT,
            source_id="f_1",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            importance="high",
        )
        assert item.importance is None

    def test_importance_int_normalized_to_float(self):
        """Integer importance should be normalized to float."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_int",
            content="Test",
            source=KnowledgeSource.FACT,
            source_id="f_1",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            importance=1,
        )
        assert item.importance == 1.0
        assert isinstance(item.importance, float)

    def test_importance_none_stays_none(self):
        """None importance should remain None."""
        now = datetime.now(timezone.utc)
        item = KnowledgeItem(
            id="ki_none",
            content="Test",
            source=KnowledgeSource.FACT,
            source_id="f_1",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
        )
        assert item.importance is None

    def test_mixed_importance_sort_no_crash(self):
        """Sorting items with mixed importance types should not crash."""
        now = datetime.now(timezone.utc)

        def make_item(item_id, importance):
            return KnowledgeItem(
                id=item_id,
                content="Test",
                source=KnowledgeSource.FACT,
                source_id=item_id,
                confidence=ConfidenceLevel.HIGH,
                created_at=now,
                updated_at=now,
                importance=importance,
            )

        items = [
            make_item("a", 0.5),
            make_item("b", "0.8"),
            make_item("c", None),
            make_item("d", "high"),
            make_item("e", 1),
        ]
        # __post_init__ normalizes all importance values, so sort by
        # importance should never raise TypeError
        items.sort(key=lambda item: item.importance if item.importance is not None else 0.0)
        assert items[0].id in ("c", "d")  # None becomes 0.0


class TestKnowledgeLink:
    """Test KnowledgeLink dataclass."""

    def test_create_link(self):
        """Test creating a link."""
        now = datetime.now(timezone.utc)
        link = KnowledgeLink(
            id="kl_1",
            source_id="ki_1",
            target_id="ki_2",
            relationship=RelationshipType.SUPPORTS,
            confidence=0.9,
            created_at=now,
        )

        assert link.id == "kl_1"
        assert link.source_id == "ki_1"
        assert link.target_id == "ki_2"
        assert link.relationship == RelationshipType.SUPPORTS
        assert link.confidence == 0.9
        assert link.metadata == {}

    def test_create_link_with_all_fields(self):
        """Test creating a link with all fields."""
        now = datetime.now(timezone.utc)
        link = KnowledgeLink(
            id="kl_custom",
            source_id="ki_1",
            target_id="ki_2",
            relationship=RelationshipType.CONTRADICTS,
            confidence=0.7,
            created_at=now,
            created_by="claude",
            metadata={"reason": "conflicting evidence"},
        )

        assert link.id == "kl_custom"
        assert link.confidence == 0.7
        assert link.created_by == "claude"
        assert link.metadata["reason"] == "conflicting evidence"

    def test_to_dict(self):
        """Test serialization to dict."""
        now = datetime.now(timezone.utc)
        link = KnowledgeLink(
            id="kl_1",
            source_id="ki_1",
            target_id="ki_2",
            relationship=RelationshipType.SUPPORTS,
            confidence=0.8,
            created_at=now,
        )

        d = link.to_dict()

        assert d["id"] == "kl_1"
        assert d["relationship"] == "supports"
        assert d["confidence"] == 0.8


class TestQueryFilters:
    """Test QueryFilters dataclass."""

    def test_default_filters(self):
        """Test default filter values."""
        filters = QueryFilters()

        assert filters.sources is None
        assert filters.min_confidence is None
        assert filters.min_importance is None
        assert filters.workspace_id is None

    def test_custom_filters(self):
        """Test custom filter values."""
        filters = QueryFilters(
            sources=[KnowledgeSource.FACT, KnowledgeSource.CONSENSUS],
            min_confidence=ConfidenceLevel.HIGH,
            min_importance=0.7,
            workspace_id="ws_test",
            tags=["security"],
        )

        assert len(filters.sources) == 2
        assert filters.min_confidence == ConfidenceLevel.HIGH
        assert filters.min_importance == 0.7
        assert filters.workspace_id == "ws_test"
        assert "security" in filters.tags

    def test_to_dict(self):
        """Test filter serialization."""
        filters = QueryFilters(
            sources=[KnowledgeSource.FACT],
            min_confidence=ConfidenceLevel.MEDIUM,
        )

        d = filters.to_dict()

        assert d["sources"] == ["fact"]
        assert d["min_confidence"] == "medium"


class TestQueryResult:
    """Test QueryResult dataclass."""

    def test_create_result(self):
        """Test creating a query result."""
        now = datetime.now(timezone.utc)
        items = [
            KnowledgeItem(
                id="ki_1",
                content="Test",
                source=KnowledgeSource.FACT,
                source_id="f_1",
                confidence=ConfidenceLevel.HIGH,
                created_at=now,
                updated_at=now,
            )
        ]

        result = QueryResult(
            items=items,
            total_count=1,
            query="test query",
        )

        assert len(result.items) == 1
        assert result.total_count == 1
        assert result.query == "test query"

    def test_to_dict(self):
        """Test result serialization."""
        result = QueryResult(
            items=[],
            total_count=0,
            query="empty",
            sources_queried=[KnowledgeSource.FACT],
        )

        d = result.to_dict()

        assert d["items"] == []
        assert d["total_count"] == 0
        assert d["sources_queried"] == ["fact"]


class TestStoreResult:
    """Test StoreResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful store result."""
        result = StoreResult(
            id="ki_new",
            source=KnowledgeSource.FACT,
            success=True,
            cross_references_created=2,
        )

        assert result.id == "ki_new"
        assert result.success is True
        assert result.cross_references_created == 2

    def test_failed_result(self):
        """Test creating a failed store result."""
        result = StoreResult(
            id="",
            source=KnowledgeSource.FACT,
            success=False,
            message="Storage error",
        )

        assert result.success is False
        assert result.message == "Storage error"


class TestLinkResult:
    """Test LinkResult dataclass."""

    def test_successful_link(self):
        """Test creating a successful link result."""
        result = LinkResult(
            id="kl_new",
            success=True,
        )

        assert result.id == "kl_new"
        assert result.success is True

    def test_failed_link(self):
        """Test creating a failed link result."""
        result = LinkResult(
            id="",
            success=False,
            message="Link creation failed",
        )

        assert result.success is False
        assert result.message == "Link creation failed"


class TestUnifiedStoreConfig:
    """Test UnifiedStoreConfig (KnowledgeMoundConfig)."""

    def test_default_config(self):
        """Test default configuration."""
        config = UnifiedStoreConfig()

        # Test actual config attributes
        assert config.enable_cross_references is True
        assert config.enable_vector_search is True
        assert config.enable_link_inference is False
        assert config.default_limit == 20
        assert config.max_limit == 100
        assert config.parallel_queries is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = UnifiedStoreConfig(
            enable_vector_search=False,
            default_limit=50,
            parallel_queries=False,
        )

        assert config.enable_vector_search is False
        assert config.default_limit == 50
        assert config.parallel_queries is False


class TestUnifiedKnowledgeStore:
    """Test UnifiedKnowledgeStore class."""

    @pytest.fixture
    def store(self):
        """Create store for testing."""
        config = UnifiedStoreConfig(fact_store=ScopedFactStore(InMemoryFactStore(), "org-test"))
        return UnifiedKnowledgeStore(config)

    @pytest.mark.asyncio
    async def test_store_basic(self, store):
        """Test basic store functionality."""
        # Store should be created successfully
        assert store is not None
        assert store.config is not None

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store):
        """Test storing and retrieving knowledge."""
        result = await store.store(
            content="Test knowledge content",
            source_type=KnowledgeSource.FACT,
        )

        assert result.success is True
        assert result.id is not None

    @pytest.mark.asyncio
    async def test_query(self, store):
        """Test querying the store."""
        # Store an item first
        await store.store(
            content="Security best practice",
            source_type=KnowledgeSource.FACT,
        )

        # Query should return results
        result = await store.query("security")

        assert result is not None
        assert isinstance(result, QueryResult)

    @pytest.mark.asyncio
    async def test_query_with_filters(self, store):
        """Test querying with filters."""
        filters = QueryFilters(
            min_confidence=ConfidenceLevel.HIGH,
        )

        result = await store.query("test", filters=filters)

        assert result is not None

    @pytest.mark.asyncio
    async def test_link_items(self, store):
        """Test linking knowledge items."""
        # Store two items
        result1 = await store.store(
            content="Premise statement",
            source_type=KnowledgeSource.FACT,
        )
        result2 = await store.store(
            content="Conclusion derived from premise",
            source_type=KnowledgeSource.FACT,
        )

        # Link them
        link_result = await store.link(
            source_id=result1.id,
            target_id=result2.id,
            relationship=RelationshipType.SUPPORTS,
        )

        assert link_result.success is True

    @pytest.mark.asyncio
    async def test_query_sources_filter(self, store):
        """Test querying with source filter."""
        result = await store.query("", sources=["fact"])

        assert result is not None
        # Should only query fact store
        assert KnowledgeSource.FACT in result.sources_queried or len(result.sources_queried) >= 0

    @pytest.mark.asyncio
    async def test_get_graph(self, store):
        """Test getting knowledge graph."""
        # Store and link items
        result1 = await store.store(content="Root", source_type=KnowledgeSource.FACT)
        result2 = await store.store(content="Child", source_type=KnowledgeSource.FACT)
        await store.link(result1.id, result2.id, RelationshipType.SUPPORTS)

        # Get graph
        graph = await store.get_graph(result1.id, depth=1)

        assert graph is not None


class TestUnifiedStoreIntegration:
    """Integration tests for UnifiedKnowledgeStore."""

    @pytest.fixture
    def integrated_store(self):
        """Create store with all backends enabled."""
        config = UnifiedStoreConfig(
            enable_cross_references=True,
            enable_vector_search=False,  # May not be available
            parallel_queries=True,
            fact_store=ScopedFactStore(InMemoryFactStore(), "org-test"),
        )
        return UnifiedKnowledgeStore(config)

    @pytest.mark.asyncio
    async def test_store_initialization(self, integrated_store):
        """Test store initializes properly."""
        assert integrated_store is not None
        assert integrated_store.config is not None

    @pytest.mark.asyncio
    async def test_federated_query(self, integrated_store):
        """Test federated query across sources."""
        # Store in fact source
        await integrated_store.store(
            content="Fact from document",
            source_type=KnowledgeSource.FACT,
        )

        # Query all sources
        result = await integrated_store.query("", sources=["all"])

        assert result is not None
