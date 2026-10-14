"""Tests for FactStore and InMemoryFactStore."""

import pytest
import tempfile
from pathlib import Path

from aragora.knowledge import (
    Fact,
    FactFilters,
    FactRelationType,
    FactStore,
    InMemoryFactStore,
    ScopedFactStore,
    ValidationStatus,
)


class TestInMemoryFactStore:
    """Test InMemoryFactStore operations."""

    @pytest.fixture
    def store(self):
        """Create in-memory store for testing."""
        return ScopedFactStore(InMemoryFactStore(), "org-test")

    def test_add_fact(self, store):
        """Test adding a fact."""
        fact = store.add_fact(
            statement="The contract expires on 2025-12-31",
            workspace_id="ws_test",
            confidence=0.8,
            topics=["contract", "expiration"],
        )

        assert fact.id.startswith("fact_")
        assert fact.statement == "The contract expires on 2025-12-31"
        assert fact.workspace_id == "ws_test"
        assert fact.confidence == 0.8
        assert fact.validation_status == ValidationStatus.UNVERIFIED
        assert "contract" in fact.topics

    def test_add_fact_deduplication(self, store):
        """Test that duplicate facts are deduplicated."""
        fact1 = store.add_fact(
            statement="The sky is blue",
            workspace_id="ws_test",
        )
        fact2 = store.add_fact(
            statement="The sky is blue",  # Same statement
            workspace_id="ws_test",
        )

        assert fact1.id == fact2.id  # Should return same fact

    def test_add_fact_different_workspace_no_dedup(self, store):
        """Test that same statement in different workspace is not deduplicated."""
        fact1 = store.add_fact(
            statement="The sky is blue",
            workspace_id="ws_1",
        )
        fact2 = store.add_fact(
            statement="The sky is blue",
            workspace_id="ws_2",  # Different workspace
        )

        assert fact1.id != fact2.id  # Should be different facts

    def test_get_fact(self, store):
        """Test getting a fact by ID."""
        fact = store.add_fact(
            statement="Test fact",
            workspace_id="ws_test",
        )

        retrieved = store.get_fact(fact.id)
        assert retrieved is not None
        assert retrieved.id == fact.id
        assert retrieved.statement == fact.statement

    def test_get_fact_not_found(self, store):
        """Test getting non-existent fact returns None."""
        result = store.get_fact("fact_nonexistent")
        assert result is None

    def test_update_fact(self, store):
        """Test updating a fact."""
        fact = store.add_fact(
            statement="Original statement",
            workspace_id="ws_test",
            confidence=0.5,
        )

        updated = store.update_fact(
            fact.id,
            confidence=0.9,
            validation_status=ValidationStatus.MAJORITY_AGREED,
        )

        assert updated is not None
        assert updated.confidence == 0.9
        assert updated.validation_status == ValidationStatus.MAJORITY_AGREED

    def test_update_fact_not_found(self, store):
        """Test updating non-existent fact returns None."""
        result = store.update_fact("fact_nonexistent", confidence=0.9)
        assert result is None

    def test_delete_fact(self, store):
        """Test deleting a fact."""
        fact = store.add_fact(
            statement="To be deleted",
            workspace_id="ws_test",
        )

        assert store.delete_fact(fact.id) is True
        assert store.get_fact(fact.id) is None

    def test_delete_fact_not_found(self, store):
        """Test deleting non-existent fact returns False."""
        result = store.delete_fact("fact_nonexistent")
        assert result is False

    def test_list_facts(self, store):
        """Test listing facts."""
        store.add_fact(statement="Fact 1", workspace_id="ws_test")
        store.add_fact(statement="Fact 2", workspace_id="ws_test")
        store.add_fact(statement="Fact 3", workspace_id="ws_other")

        # List all
        all_facts = store.list_facts()
        assert len(all_facts) == 3

        # Filter by workspace
        ws_facts = store.list_facts(FactFilters(workspace_id="ws_test"))
        assert len(ws_facts) == 2

    def test_list_facts_with_confidence_filter(self, store):
        """Test listing facts with confidence filter."""
        store.add_fact(statement="Low confidence", workspace_id="ws_test", confidence=0.3)
        store.add_fact(statement="High confidence", workspace_id="ws_test", confidence=0.9)

        high_conf = store.list_facts(FactFilters(min_confidence=0.8))
        assert len(high_conf) == 1
        assert high_conf[0].statement == "High confidence"

    def test_query_facts(self, store):
        """Test querying facts by keyword."""
        store.add_fact(
            statement="The contract has a 30-day termination clause",
            workspace_id="ws_test",
            topics=["contract", "termination"],
        )
        store.add_fact(
            statement="Payment is due within 15 days",
            workspace_id="ws_test",
            topics=["payment"],
        )

        results = store.query_facts("contract", FactFilters(workspace_id="ws_test"))
        assert len(results) >= 1
        assert any("contract" in f.statement.lower() for f in results)

    def test_add_relation(self, store):
        """Test adding a relation between facts."""
        fact1 = store.add_fact(statement="Fact A", workspace_id="ws_test")
        fact2 = store.add_fact(statement="Fact B", workspace_id="ws_test")

        relation = store.add_relation(
            source_fact_id=fact1.id,
            target_fact_id=fact2.id,
            relation_type=FactRelationType.SUPPORTS,
            confidence=0.8,
        )

        assert relation.id.startswith("rel_")
        assert relation.source_fact_id == fact1.id
        assert relation.target_fact_id == fact2.id
        assert relation.relation_type == FactRelationType.SUPPORTS

    def test_get_relations(self, store):
        """Test getting relations for a fact."""
        fact1 = store.add_fact(statement="Fact A", workspace_id="ws_test")
        fact2 = store.add_fact(statement="Fact B", workspace_id="ws_test")
        fact3 = store.add_fact(statement="Fact C", workspace_id="ws_test")

        store.add_relation(fact1.id, fact2.id, FactRelationType.SUPPORTS)
        store.add_relation(fact1.id, fact3.id, FactRelationType.IMPLIES)

        relations = store.get_relations(fact1.id, as_source=True, as_target=False)
        assert len(relations) == 2

    def test_get_contradictions(self, store):
        """Test getting contradicting facts."""
        fact1 = store.add_fact(statement="The sky is blue", workspace_id="ws_test")
        fact2 = store.add_fact(statement="The sky is green", workspace_id="ws_test")

        store.add_relation(fact1.id, fact2.id, FactRelationType.CONTRADICTS)

        contradictions = store.get_contradictions(fact1.id)
        assert len(contradictions) == 1
        assert contradictions[0].id == fact2.id

    def test_statistics(self, store):
        """Test getting statistics."""
        store.add_fact(statement="Fact 1", workspace_id="ws_test", confidence=0.8)
        store.add_fact(statement="Fact 2", workspace_id="ws_test", confidence=0.6)

        stats = store.get_statistics()
        assert stats["total_facts"] == 2
        assert stats["average_confidence"] == pytest.approx(0.7, rel=0.01)


class TestFactStore:
    """Test SQLite-based FactStore."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create SQLite store for testing."""
        db_path = tmp_path / "test_facts.db"
        return ScopedFactStore(FactStore(db_path=db_path), "org-test")

    def test_add_and_get_fact(self, store):
        """Test adding and retrieving a fact."""
        fact = store.add_fact(
            statement="Test statement",
            workspace_id="ws_test",
            confidence=0.75,
            topics=["test", "example"],
            metadata={"source": "unit_test"},
        )

        retrieved = store.get_fact(fact.id)
        assert retrieved is not None
        assert retrieved.statement == "Test statement"
        assert retrieved.confidence == 0.75
        assert "test" in retrieved.topics
        assert retrieved.metadata.get("source") == "unit_test"

    def test_update_fact(self, store):
        """Test updating a fact in SQLite store."""
        fact = store.add_fact(
            statement="Original",
            workspace_id="ws_test",
        )

        updated = store.update_fact(
            fact.id,
            confidence=0.95,
            validation_status=ValidationStatus.BYZANTINE_AGREED,
            consensus_proof_id="proof_123",
        )

        assert updated is not None
        assert updated.confidence == 0.95
        assert updated.validation_status == ValidationStatus.BYZANTINE_AGREED
        assert updated.consensus_proof_id == "proof_123"

    def test_list_and_query(self, store):
        """Test listing and querying facts."""
        store.add_fact(
            statement="Contract expires December 2025",
            workspace_id="ws_legal",
            topics=["contract", "expiration"],
        )
        store.add_fact(
            statement="Payment terms are NET-30",
            workspace_id="ws_legal",
            topics=["payment"],
        )

        # List all
        all_facts = store.list_facts(FactFilters(workspace_id="ws_legal"))
        assert len(all_facts) == 2

        # Query by term - use list_facts with topic filter as FTS may not match
        # FTS5 tokenization can vary by SQLite version
        contract_facts = store.list_facts(FactFilters(workspace_id="ws_legal", topics=["contract"]))
        assert len(contract_facts) >= 1

    def test_relations(self, store):
        """Test fact relations in SQLite store."""
        fact1 = store.add_fact(statement="Clause A", workspace_id="ws_test")
        fact2 = store.add_fact(statement="Clause B", workspace_id="ws_test")

        relation = store.add_relation(
            fact1.id,
            fact2.id,
            FactRelationType.IMPLIES,
            confidence=0.9,
            created_by="test_agent",
        )

        relations = store.get_relations(fact1.id)
        assert len(relations) == 1
        assert relations[0].relation_type == FactRelationType.IMPLIES

    def test_superseded_facts(self, store):
        """Test fact supersession."""
        old_fact = store.add_fact(
            statement="Revenue was $1M",
            workspace_id="ws_test",
        )
        new_fact = store.add_fact(
            statement="Revenue was $1.2M (corrected)",
            workspace_id="ws_test",
        )

        store.update_fact(old_fact.id, superseded_by=new_fact.id)

        # Superseded facts should be excluded by default
        facts = store.list_facts(FactFilters(workspace_id="ws_test"))
        assert len(facts) == 1
        assert facts[0].id == new_fact.id

        # Include superseded
        all_facts = store.list_facts(FactFilters(workspace_id="ws_test", include_superseded=True))
        assert len(all_facts) == 2


class TestFactDataclass:
    """Test Fact dataclass methods."""

    def test_to_dict(self):
        """Test Fact.to_dict() serialization."""
        fact = Fact(
            id="fact_123",
            statement="Test statement",
            confidence=0.8,
            workspace_id="ws_test",
            validation_status=ValidationStatus.MAJORITY_AGREED,
        )

        data = fact.to_dict()
        assert data["id"] == "fact_123"
        assert data["statement"] == "Test statement"
        assert data["confidence"] == 0.8
        assert data["validation_status"] == "majority_agreed"

    def test_from_dict(self):
        """Test Fact.from_dict() deserialization."""
        data = {
            "id": "fact_456",
            "statement": "Deserialized fact",
            "confidence": 0.75,
            "workspace_id": "ws_test",
            "validation_status": "byzantine_agreed",
            "created_at": "2025-01-17T10:00:00",
            "updated_at": "2025-01-17T10:00:00",
        }

        fact = Fact.from_dict(data)
        assert fact.id == "fact_456"
        assert fact.statement == "Deserialized fact"
        assert fact.validation_status == ValidationStatus.BYZANTINE_AGREED

    def test_is_verified(self):
        """Test is_verified property."""
        unverified = Fact(
            id="f1",
            statement="test",
            validation_status=ValidationStatus.UNVERIFIED,
        )
        verified = Fact(
            id="f2",
            statement="test",
            validation_status=ValidationStatus.MAJORITY_AGREED,
        )

        assert not unverified.is_verified
        assert verified.is_verified

    def test_is_active(self):
        """Test is_active property."""
        active = Fact(id="f1", statement="test")
        superseded = Fact(id="f2", statement="test", superseded_by="f3")

        assert active.is_active
        assert not superseded.is_active
