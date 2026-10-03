"""
Tests for ProvenanceStore - Evidence provenance chain storage.

Tests cover:
- Chain CRUD operations (save, load, delete, list)
- Record storage and retrieval
- Citation storage and querying
- Manager save/load
- Chain integrity verification
- Statistics
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from aragora.reasoning.provenance import (
    Citation,
    ProvenanceChain,
    ProvenanceManager,
    ProvenanceRecord,
    SourceType,
    TransformationType,
)
from aragora.reasoning.provenance_store import ProvenanceStore


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_provenance.db"


@pytest.fixture
def provenance_store(temp_db_path):
    """Create a provenance store for testing."""
    store = ProvenanceStore(db_path=temp_db_path)
    yield store


@pytest.fixture
def sample_record():
    """Create a sample provenance record."""
    return ProvenanceRecord(
        id="rec-001",
        content_hash="",  # Will be computed
        source_type=SourceType.DOCUMENT,
        source_id="doc-001",
        content="Sample evidence content from document",
        content_type="text",
        transformation=TransformationType.ORIGINAL,
        confidence=0.9,
        verified=True,
        verifier_id="verifier-001",
    )


@pytest.fixture
def sample_chain():
    """Create a sample provenance chain with records."""
    chain = ProvenanceChain(chain_id="chain-001")

    # Add some records
    chain.add_record(
        content="First piece of evidence",
        source_type=SourceType.DOCUMENT,
        source_id="doc-001",
        transformation=TransformationType.ORIGINAL,
    )
    chain.add_record(
        content="Agent's analysis of evidence",
        source_type=SourceType.AGENT_GENERATED,
        source_id="claude",
        transformation=TransformationType.SUMMARIZED,
    )
    chain.add_record(
        content="Synthesized conclusion",
        source_type=SourceType.SYNTHESIS,
        source_id="gemini",
        transformation=TransformationType.AGGREGATED,
        parent_ids=["rec-001"],
    )

    return chain


@pytest.fixture
def sample_manager():
    """Create a sample ProvenanceManager with data."""
    manager = ProvenanceManager(debate_id="debate-001")

    # Record some evidence
    evidence1 = manager.record_evidence(
        content="The contract clause requires 30-day notice",
        source_type=SourceType.DOCUMENT,
        source_id="contract.pdf",
    )

    evidence2 = manager.record_evidence(
        content="Industry standard is 14 days",
        source_type=SourceType.WEB_SEARCH,
        source_id="industry-report.pdf",
    )

    # Create citations
    manager.cite_evidence(
        claim_id="claim-001",
        evidence_id=evidence1.id,
        relevance=0.9,
        support_type="supports",
        citation_text="30-day notice clause",
    )

    manager.cite_evidence(
        claim_id="claim-001",
        evidence_id=evidence2.id,
        relevance=0.7,
        support_type="contextualizes",
        citation_text="industry context",
    )

    return manager


# ===========================================================================
# Chain Operations Tests
# ===========================================================================


class TestChainOperations:
    """Tests for chain save/load/delete operations."""

    def test_save_and_load_chain(self, provenance_store, sample_chain):
        """Test saving and loading a chain."""
        debate_id = "debate-001"

        # Save chain
        provenance_store.save_chain(sample_chain, debate_id)

        # Load by chain_id
        loaded = provenance_store.load_chain(sample_chain.chain_id)
        assert loaded is not None
        assert loaded.chain_id == sample_chain.chain_id
        assert len(loaded.records) == len(sample_chain.records)
        assert loaded.genesis_hash == sample_chain.genesis_hash

    def test_get_chain_by_debate(self, provenance_store, sample_chain):
        """Test loading chain by debate ID."""
        debate_id = "debate-002"
        provenance_store.save_chain(sample_chain, debate_id)

        loaded = provenance_store.get_chain_by_debate(debate_id)
        assert loaded is not None
        assert loaded.chain_id == sample_chain.chain_id

    def test_load_nonexistent_chain(self, provenance_store):
        """Test loading a chain that doesn't exist returns None."""
        loaded = provenance_store.load_chain("nonexistent-chain")
        assert loaded is None

    def test_delete_chain(self, provenance_store, sample_chain):
        """Test deleting a chain."""
        debate_id = "debate-003"
        provenance_store.save_chain(sample_chain, debate_id)

        # Verify it exists
        assert provenance_store.load_chain(sample_chain.chain_id) is not None

        # Delete it
        result = provenance_store.delete_chain(sample_chain.chain_id)
        assert result is True

        # Verify it's gone
        assert provenance_store.load_chain(sample_chain.chain_id) is None

    def test_list_chains(self, provenance_store):
        """Test listing chains with pagination."""
        # Create multiple chains
        for i in range(5):
            chain = ProvenanceChain(chain_id=f"chain-{i:03d}")
            chain.add_record(
                content=f"Evidence {i}",
                source_type=SourceType.DOCUMENT,
                source_id=f"doc-{i}",
            )
            provenance_store.save_chain(chain, f"debate-{i:03d}")

        # List all
        chains = provenance_store.list_chains(limit=10)
        assert len(chains) == 5

        # List with pagination
        chains = provenance_store.list_chains(limit=2, offset=0)
        assert len(chains) == 2

        chains = provenance_store.list_chains(limit=2, offset=3)
        assert len(chains) == 2


# ===========================================================================
# Record Operations Tests
# ===========================================================================


class TestRecordOperations:
    """Tests for record storage and retrieval."""

    def test_get_record(self, provenance_store, sample_chain):
        """Test getting individual records."""
        debate_id = "debate-004"
        provenance_store.save_chain(sample_chain, debate_id)

        # Get first record
        first_record = sample_chain.records[0]
        loaded_record = provenance_store.get_record(first_record.id)

        assert loaded_record is not None
        assert loaded_record.id == first_record.id
        assert loaded_record.content == first_record.content
        assert loaded_record.source_type == first_record.source_type

    def test_get_records_by_chain(self, provenance_store, sample_chain):
        """Test getting all records for a chain."""
        debate_id = "debate-005"
        provenance_store.save_chain(sample_chain, debate_id)

        records = provenance_store.get_records_by_chain(sample_chain.chain_id)
        assert len(records) == len(sample_chain.records)

    def test_search_records_by_source_type(self, provenance_store, sample_chain):
        """Test searching records by source type."""
        debate_id = "debate-006"
        provenance_store.save_chain(sample_chain, debate_id)

        # Search for document sources
        records = provenance_store.search_records(source_type=SourceType.DOCUMENT)
        assert len(records) >= 1
        assert all(r.source_type == SourceType.DOCUMENT for r in records)

    def test_search_records_verified_only(self, provenance_store):
        """Test searching for verified records only."""
        # Create chain with verified and unverified records
        chain = ProvenanceChain(chain_id="chain-verified")
        rec1 = chain.add_record(
            content="Verified evidence",
            source_type=SourceType.DOCUMENT,
            source_id="doc-1",
        )
        rec1.verified = True
        rec1.verifier_id = "human"

        rec2 = chain.add_record(
            content="Unverified evidence",
            source_type=SourceType.WEB_SEARCH,
            source_id="web-1",
        )
        rec2.verified = False

        provenance_store.save_chain(chain, "debate-verified")

        # Search verified only
        records = provenance_store.search_records(verified_only=True)
        assert len(records) >= 1
        assert all(r.verified for r in records)


# ===========================================================================
# Citation Operations Tests
# ===========================================================================


class TestCitationOperations:
    """Tests for citation storage and retrieval."""

    def test_save_and_get_citation(self, provenance_store, sample_chain):
        """Test saving and retrieving citations."""
        debate_id = "debate-007"
        provenance_store.save_chain(sample_chain, debate_id)

        # Create a citation
        citation = Citation(
            claim_id="claim-001",
            evidence_id=sample_chain.records[0].id,
            relevance=0.85,
            support_type="supports",
            citation_text="key evidence",
        )
        provenance_store.save_citation(sample_chain.chain_id, citation)

        # Retrieve by claim
        citations = provenance_store.get_citations_by_claim("claim-001")
        assert len(citations) == 1
        assert citations[0].evidence_id == sample_chain.records[0].id
        assert citations[0].support_type == "supports"

    def test_get_citations_by_evidence(self, provenance_store, sample_chain):
        """Test getting citations by evidence ID."""
        debate_id = "debate-008"
        provenance_store.save_chain(sample_chain, debate_id)

        evidence_id = sample_chain.records[0].id

        # Create multiple citations to same evidence
        for i in range(3):
            citation = Citation(
                claim_id=f"claim-{i:03d}",
                evidence_id=evidence_id,
                relevance=0.8,
                support_type="supports",
            )
            provenance_store.save_citation(sample_chain.chain_id, citation)

        # Retrieve by evidence
        citations = provenance_store.get_citations_by_evidence(evidence_id)
        assert len(citations) == 3

    def test_load_citation_graph(self, provenance_store, sample_chain):
        """Test loading a full CitationGraph."""
        debate_id = "debate-009"
        provenance_store.save_chain(sample_chain, debate_id)

        # Add multiple citations
        for i, record in enumerate(sample_chain.records):
            citation = Citation(
                claim_id="claim-main",
                evidence_id=record.id,
                relevance=0.9 - (i * 0.1),
                support_type="supports" if i % 2 == 0 else "contextualizes",
            )
            provenance_store.save_citation(sample_chain.chain_id, citation)

        # Load the graph
        graph = provenance_store.load_citation_graph(sample_chain.chain_id)
        assert len(graph.citations) == len(sample_chain.records)

        # Check claim citations are indexed
        claim_citations = graph.get_claim_evidence("claim-main")
        assert len(claim_citations) == len(sample_chain.records)


# ===========================================================================
# Manager Operations Tests
# ===========================================================================


class TestManagerOperations:
    """Tests for ProvenanceManager save/load."""

    def test_save_and_load_manager(self, provenance_store, sample_manager):
        """Test saving and loading a full manager."""
        provenance_store.save_manager(sample_manager)

        loaded = provenance_store.load_manager(sample_manager.debate_id)
        assert loaded is not None
        assert loaded.debate_id == sample_manager.debate_id
        assert len(loaded.chain.records) == len(sample_manager.chain.records)
        assert len(loaded.graph.citations) == len(sample_manager.graph.citations)

    def test_load_nonexistent_manager(self, provenance_store):
        """Test loading a manager that doesn't exist."""
        loaded = provenance_store.load_manager("nonexistent-debate")
        assert loaded is None

    def test_manager_verifier_restored(self, provenance_store, sample_manager):
        """Test that the verifier is properly restored."""
        provenance_store.save_manager(sample_manager)

        loaded = provenance_store.load_manager(sample_manager.debate_id)
        assert loaded is not None
        assert loaded.verifier is not None
        assert loaded.verifier.chain is loaded.chain
        assert loaded.verifier.graph is loaded.graph


# ===========================================================================
# Chain Integrity Tests
# ===========================================================================


class TestChainIntegrity:
    """Tests for chain integrity verification."""

    def test_verify_valid_chain(self, provenance_store, sample_chain):
        """Test verifying a valid chain."""
        debate_id = "debate-010"
        provenance_store.save_chain(sample_chain, debate_id)

        is_valid, errors = provenance_store.verify_chain_integrity(sample_chain.chain_id)
        assert is_valid is True
        assert len(errors) == 0

    def test_verify_nonexistent_chain(self, provenance_store):
        """Test verifying a chain that doesn't exist."""
        is_valid, errors = provenance_store.verify_chain_integrity("nonexistent")
        assert is_valid is False
        assert len(errors) == 1
        assert "not found" in errors[0]


# ===========================================================================
# Statistics Tests
# ===========================================================================


class TestStatistics:
    """Tests for store statistics."""

    def test_get_stats_empty(self, provenance_store):
        """Test stats on empty store."""
        stats = provenance_store.get_stats()
        assert stats["chain_count"] == 0
        assert stats["record_count"] == 0
        assert stats["citation_count"] == 0

    def test_get_stats_with_data(self, provenance_store, sample_manager):
        """Test stats with data."""
        provenance_store.save_manager(sample_manager)

        stats = provenance_store.get_stats()
        assert stats["chain_count"] == 1
        assert stats["record_count"] == len(sample_manager.chain.records)
        assert stats["citation_count"] == len(sample_manager.graph.citations)


# ===========================================================================
# Edge Cases Tests
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_save_empty_chain(self, provenance_store):
        """Test saving a chain with no records."""
        chain = ProvenanceChain(chain_id="empty-chain")
        provenance_store.save_chain(chain, "debate-empty")

        loaded = provenance_store.load_chain("empty-chain")
        assert loaded is not None
        assert len(loaded.records) == 0

    def test_update_chain(self, provenance_store, sample_chain):
        """Test updating an existing chain."""
        debate_id = "debate-update"
        provenance_store.save_chain(sample_chain, debate_id)

        # Add more records
        sample_chain.add_record(
            content="Additional evidence",
            source_type=SourceType.USER_PROVIDED,
            source_id="user-001",
        )

        # Save again
        provenance_store.save_chain(sample_chain, debate_id)

        # Verify update
        loaded = provenance_store.load_chain(sample_chain.chain_id)
        assert len(loaded.records) == 4  # Original 3 + 1 new

    def test_record_with_special_characters(self, provenance_store):
        """Test records with special characters in content."""
        chain = ProvenanceChain(chain_id="special-chars")
        chain.add_record(
            content="Content with 'quotes' and \"double quotes\" and <html>",
            source_type=SourceType.DOCUMENT,
            source_id="doc-special",
        )
        chain.add_record(
            content="Unicode: ñ, ü, 中文, 🎉",
            source_type=SourceType.USER_PROVIDED,
            source_id="user-unicode",
        )

        provenance_store.save_chain(chain, "debate-special")

        loaded = provenance_store.load_chain("special-chars")
        assert "quotes" in loaded.records[0].content
        assert "中文" in loaded.records[1].content
