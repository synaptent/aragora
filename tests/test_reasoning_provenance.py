"""
Tests for the Evidence Provenance Chain system.

Tests cover:
- SourceType and TransformationType enums
- ProvenanceRecord creation, hashing, and serialization
- ProvenanceChain operations and verification
- Citation and CitationGraph for linking claims to evidence
- MerkleTree for batch verification
- ProvenanceVerifier for integrity checking
- ProvenanceManager high-level operations
"""

import pytest
from datetime import datetime

from aragora.reasoning.provenance import (
    SourceType,
    TransformationType,
    ProvenanceRecord,
    ProvenanceChain,
    Citation,
    CitationGraph,
    MerkleTree,
    ProvenanceVerifier,
    ProvenanceManager,
)


class TestSourceTypeEnum:
    """Tests for SourceType enumeration."""

    def test_all_source_types_defined(self):
        """Verify all expected source types exist."""
        expected = [
            "agent_generated",
            "user_provided",
            "external_api",
            "web_search",
            "document",
            "code_analysis",
            "database",
            "computation",
            "synthesis",
            "audio_transcript",
            "blockchain",
            "unknown",
        ]
        actual = [st.value for st in SourceType]
        assert sorted(expected) == sorted(actual)

    def test_source_type_values(self):
        """Test specific source type values."""
        assert SourceType.AGENT_GENERATED.value == "agent_generated"
        assert SourceType.WEB_SEARCH.value == "web_search"
        assert SourceType.SYNTHESIS.value == "synthesis"


class TestTransformationTypeEnum:
    """Tests for TransformationType enumeration."""

    def test_all_transformation_types_defined(self):
        """Verify all expected transformation types exist."""
        expected = [
            "original",
            "quoted",
            "paraphrased",
            "summarized",
            "extracted",
            "computed",
            "aggregated",
            "verified",
            "refuted",
            "amended",
        ]
        actual = [tt.value for tt in TransformationType]
        assert sorted(expected) == sorted(actual)


class TestProvenanceRecord:
    """Tests for ProvenanceRecord dataclass."""

    def test_record_creation(self):
        """Test basic record creation."""
        record = ProvenanceRecord(
            id="rec-001",
            content_hash="",
            source_type=SourceType.AGENT_GENERATED,
            source_id="claude",
            content="Test evidence content",
        )
        assert record.id == "rec-001"
        assert record.source_type == SourceType.AGENT_GENERATED
        assert record.content == "Test evidence content"
        assert record.content_hash != ""  # Should be computed

    def test_content_hash_computed(self):
        """Test that content hash is computed on creation."""
        record = ProvenanceRecord(
            id="rec-001",
            content_hash="",
            source_type=SourceType.WEB_SEARCH,
            source_id="https://example.com",
            content="Some web content",
        )
        # Hash should be SHA-256 and non-empty
        assert len(record.content_hash) == 64
        assert record.content_hash.isalnum()

    def test_chain_hash_includes_previous(self):
        """Test that chain hash incorporates previous hash."""
        record1 = ProvenanceRecord(
            id="rec-001",
            content_hash="",
            source_type=SourceType.AGENT_GENERATED,
            source_id="agent1",
            content="First content",
        )
        record2 = ProvenanceRecord(
            id="rec-002",
            content_hash="",
            source_type=SourceType.AGENT_GENERATED,
            source_id="agent2",
            content="Second content",
            previous_hash=record1.chain_hash(),
        )
        # Chain hashes should be different
        assert record1.chain_hash() != record2.chain_hash()

    def test_to_dict_serialization(self):
        """Test record serialization."""
        record = ProvenanceRecord(
            id="rec-001",
            content_hash="",
            source_type=SourceType.DOCUMENT,
            source_id="/path/to/doc.pdf",
            content="Document content",
            confidence=0.9,
            verified=True,
        )
        d = record.to_dict()
        assert d["id"] == "rec-001"
        assert d["source_type"] == "document"
        assert d["confidence"] == 0.9
        assert d["verified"] is True

    def test_from_dict_deserialization(self):
        """Test record deserialization."""
        data = {
            "id": "rec-001",
            "content_hash": "abc123" * 10 + "abcd",  # 64 chars
            "source_type": "web_search",
            "source_id": "https://example.com",
            "content": "Test content",
            "timestamp": "2026-01-05T10:00:00",
            "transformation": "summarized",
            "confidence": 0.8,
        }
        record = ProvenanceRecord.from_dict(data)
        assert record.id == "rec-001"
        assert record.source_type == SourceType.WEB_SEARCH
        assert record.transformation == TransformationType.SUMMARIZED


class TestProvenanceChain:
    """Tests for ProvenanceChain class."""

    def test_chain_initialization(self):
        """Test chain initialization."""
        chain = ProvenanceChain()
        assert chain.chain_id is not None
        assert len(chain.records) == 0
        assert chain.genesis_hash is None

    def test_add_record(self):
        """Test adding a record to the chain."""
        chain = ProvenanceChain()
        record = chain.add_record(
            content="First evidence",
            source_type=SourceType.AGENT_GENERATED,
            source_id="claude",
        )
        assert len(chain.records) == 1
        assert record.previous_hash is None  # Genesis
        assert chain.genesis_hash == record.chain_hash()

    def test_chain_links_records(self):
        """Test that records are linked via hashes."""
        chain = ProvenanceChain()
        r1 = chain.add_record("First", SourceType.AGENT_GENERATED, "agent1")
        r2 = chain.add_record("Second", SourceType.AGENT_GENERATED, "agent2")
        r3 = chain.add_record("Third", SourceType.AGENT_GENERATED, "agent3")

        assert r1.previous_hash is None
        assert r2.previous_hash == r1.chain_hash()
        assert r3.previous_hash == r2.chain_hash()

    def test_verify_chain_valid(self):
        """Test verification of valid chain."""
        chain = ProvenanceChain()
        chain.add_record("First", SourceType.AGENT_GENERATED, "agent1")
        chain.add_record("Second", SourceType.AGENT_GENERATED, "agent2")

        is_valid, errors = chain.verify_chain()
        assert is_valid is True
        assert len(errors) == 0

    def test_verify_chain_empty(self):
        """Test verification of empty chain."""
        chain = ProvenanceChain()
        is_valid, errors = chain.verify_chain()
        assert is_valid is True

    def test_get_record(self):
        """Test retrieving record by ID."""
        chain = ProvenanceChain()
        r1 = chain.add_record("Test", SourceType.AGENT_GENERATED, "agent")

        found = chain.get_record(r1.id)
        assert found == r1
        assert chain.get_record("nonexistent") is None

    def test_chain_serialization(self):
        """Test chain serialization round-trip."""
        chain = ProvenanceChain()
        chain.add_record("First", SourceType.AGENT_GENERATED, "agent1")
        chain.add_record("Second", SourceType.WEB_SEARCH, "https://example.com")

        exported = chain.to_dict()
        loaded = ProvenanceChain.from_dict(exported)

        assert loaded.chain_id == chain.chain_id
        assert len(loaded.records) == 2


class TestCitation:
    """Tests for Citation dataclass."""

    def test_citation_creation(self):
        """Test basic citation creation."""
        citation = Citation(
            claim_id="claim-001",
            evidence_id="ev-001",
            relevance=0.9,
            support_type="supports",
        )
        assert citation.claim_id == "claim-001"
        assert citation.evidence_id == "ev-001"
        assert citation.relevance == 0.9


class TestCitationGraph:
    """Tests for CitationGraph class."""

    def test_graph_initialization(self):
        """Test graph initialization."""
        graph = CitationGraph()
        assert len(graph.citations) == 0

    def test_add_citation(self):
        """Test adding a citation."""
        graph = CitationGraph()
        citation = graph.add_citation(
            claim_id="claim-001",
            evidence_id="ev-001",
            relevance=0.8,
            support_type="supports",
        )
        assert len(graph.citations) == 1
        assert citation.claim_id == "claim-001"

    def test_get_claim_evidence(self):
        """Test retrieving evidence for a claim."""
        graph = CitationGraph()
        graph.add_citation("claim-001", "ev-001", support_type="supports")
        graph.add_citation("claim-001", "ev-002", support_type="contradicts")
        graph.add_citation("claim-002", "ev-003", support_type="supports")

        claim1_evidence = graph.get_claim_evidence("claim-001")
        assert len(claim1_evidence) == 2

    def test_get_supporting_evidence(self):
        """Test retrieving supporting evidence only."""
        graph = CitationGraph()
        graph.add_citation("claim-001", "ev-001", support_type="supports")
        graph.add_citation("claim-001", "ev-002", support_type="contradicts")
        graph.add_citation("claim-001", "ev-003", support_type="supports")

        supporting = graph.get_supporting_evidence("claim-001")
        assert len(supporting) == 2
        assert all(c.support_type == "supports" for c in supporting)

    def test_get_contradicting_evidence(self):
        """Test retrieving contradicting evidence only."""
        graph = CitationGraph()
        graph.add_citation("claim-001", "ev-001", support_type="supports")
        graph.add_citation("claim-001", "ev-002", support_type="contradicts")

        contradicting = graph.get_contradicting_evidence("claim-001")
        assert len(contradicting) == 1
        assert contradicting[0].evidence_id == "ev-002"

    def test_compute_support_score(self):
        """Test computing claim support score."""
        graph = CitationGraph()
        # Two supporting, one contradicting
        graph.add_citation("claim-001", "ev-001", relevance=1.0, support_type="supports")
        graph.add_citation("claim-001", "ev-002", relevance=1.0, support_type="supports")
        graph.add_citation("claim-001", "ev-003", relevance=1.0, support_type="contradicts")

        score = graph.compute_claim_support_score("claim-001")
        # (1 + 1 - 1) / 3 = 0.333...
        assert score == pytest.approx(1 / 3, abs=0.01)

    def test_compute_support_score_empty(self):
        """Test support score with no citations."""
        graph = CitationGraph()
        score = graph.compute_claim_support_score("nonexistent")
        assert score == 0.0


class TestMerkleTree:
    """Tests for MerkleTree class."""

    def test_empty_tree(self):
        """Test building empty Merkle tree."""
        tree = MerkleTree()
        # Explicitly call build with empty list (constructor skips if falsy)
        root = tree.build([])
        assert root is not None  # Hash of empty string
        assert tree.root == root

    def test_single_record_tree(self):
        """Test tree with single record."""
        record = ProvenanceRecord(
            id="rec-001",
            content_hash="",
            source_type=SourceType.AGENT_GENERATED,
            source_id="agent",
            content="Test",
        )
        tree = MerkleTree([record])
        assert tree.root is not None
        assert len(tree.leaves) >= 1

    def test_multiple_records_tree(self):
        """Test tree with multiple records."""
        records = [
            ProvenanceRecord(
                id=f"rec-{i}",
                content_hash="",
                source_type=SourceType.AGENT_GENERATED,
                source_id="agent",
                content=f"Content {i}",
            )
            for i in range(4)
        ]
        tree = MerkleTree(records)
        assert tree.root is not None
        assert len(tree.tree) > 1  # Multiple levels

    def test_proof_generation_and_verification(self):
        """Test generating and verifying Merkle proofs."""
        records = [
            ProvenanceRecord(
                id=f"rec-{i}",
                content_hash="",
                source_type=SourceType.AGENT_GENERATED,
                source_id="agent",
                content=f"Content {i}",
            )
            for i in range(4)
        ]
        tree = MerkleTree(records)

        # Get proof for first record
        proof = tree.get_proof(0)
        is_valid = tree.verify_proof(records[0].content_hash, proof, tree.root)
        assert is_valid is True

    def test_proof_verification_fails_with_wrong_leaf(self):
        """Test that proof fails with incorrect leaf."""
        records = [
            ProvenanceRecord(
                id=f"rec-{i}",
                content_hash="",
                source_type=SourceType.AGENT_GENERATED,
                source_id="agent",
                content=f"Content {i}",
            )
            for i in range(4)
        ]
        tree = MerkleTree(records)

        proof = tree.get_proof(0)
        # Use wrong leaf hash
        is_valid = tree.verify_proof("wrong_hash", proof, tree.root)
        assert is_valid is False


class TestProvenanceVerifier:
    """Tests for ProvenanceVerifier class."""

    def test_verify_valid_record(self):
        """Test verifying a valid record."""
        chain = ProvenanceChain()
        record = chain.add_record("Test content", SourceType.AGENT_GENERATED, "agent")

        verifier = ProvenanceVerifier(chain)
        is_valid, errors = verifier.verify_record(record.id)
        assert is_valid is True
        assert len(errors) == 0

    def test_verify_nonexistent_record(self):
        """Test verifying nonexistent record."""
        chain = ProvenanceChain()
        verifier = ProvenanceVerifier(chain)

        is_valid, errors = verifier.verify_record("nonexistent")
        assert is_valid is False
        assert "not found" in errors[0]

    def test_generate_provenance_report(self):
        """Test generating provenance report."""
        chain = ProvenanceChain()
        r1 = chain.add_record("Original", SourceType.WEB_SEARCH, "https://example.com")
        r2 = chain.add_record(
            "Summarized",
            SourceType.AGENT_GENERATED,
            "claude",
            transformation=TransformationType.SUMMARIZED,
        )

        verifier = ProvenanceVerifier(chain)
        report = verifier.generate_provenance_report(r2.id)

        assert report["record_id"] == r2.id
        assert "transformation_history" in report
        assert report["source"]["type"] == "agent_generated"


class TestProvenanceManager:
    """Tests for ProvenanceManager high-level operations."""

    def test_manager_initialization(self):
        """Test manager initialization."""
        manager = ProvenanceManager("debate-001")
        assert manager.debate_id == "debate-001"
        assert manager.chain is not None
        assert manager.graph is not None

    def test_record_evidence(self):
        """Test recording evidence."""
        manager = ProvenanceManager()
        record = manager.record_evidence(
            content="Important evidence",
            source_type=SourceType.WEB_SEARCH,
            source_id="https://example.com",
        )
        assert record.content == "Important evidence"
        assert len(manager.chain.records) == 1

    def test_cite_evidence(self):
        """Test creating citations."""
        manager = ProvenanceManager()
        record = manager.record_evidence(
            "Evidence content",
            SourceType.AGENT_GENERATED,
            "claude",
        )
        citation = manager.cite_evidence(
            claim_id="claim-001",
            evidence_id=record.id,
            relevance=0.9,
            support_type="supports",
        )
        assert citation.claim_id == "claim-001"
        assert citation.evidence_id == record.id

    def test_synthesize_evidence(self):
        """Test synthesizing evidence from multiple sources."""
        manager = ProvenanceManager()
        r1 = manager.record_evidence("Source 1", SourceType.WEB_SEARCH, "url1")
        r2 = manager.record_evidence("Source 2", SourceType.WEB_SEARCH, "url2")

        synthesis = manager.synthesize_evidence(
            parent_ids=[r1.id, r2.id],
            synthesized_content="Combined analysis from both sources",
            synthesizer_id="claude",
        )
        assert synthesis.source_type == SourceType.SYNTHESIS
        assert r1.id in synthesis.parent_ids
        assert r2.id in synthesis.parent_ids

    def test_verify_chain_integrity(self):
        """Test chain integrity verification."""
        manager = ProvenanceManager()
        manager.record_evidence("First", SourceType.AGENT_GENERATED, "agent1")
        manager.record_evidence("Second", SourceType.AGENT_GENERATED, "agent2")

        is_valid, errors = manager.verify_chain_integrity()
        assert is_valid is True

    def test_export_and_load(self):
        """Test export and load round-trip."""
        manager = ProvenanceManager("debate-001")
        r1 = manager.record_evidence("Evidence 1", SourceType.WEB_SEARCH, "url1")
        manager.cite_evidence("claim-001", r1.id, support_type="supports")

        exported = manager.export()
        loaded = ProvenanceManager.load(exported)

        assert loaded.debate_id == "debate-001"
        assert len(loaded.chain.records) == 1
        assert len(loaded.graph.citations) == 1

    def test_get_claim_support(self):
        """Test getting claim support status."""
        manager = ProvenanceManager()
        r1 = manager.record_evidence("Supporting", SourceType.AGENT_GENERATED, "agent")
        manager.cite_evidence("claim-001", r1.id, support_type="supports", relevance=0.9)

        support = manager.get_claim_support("claim-001")
        assert support["claim_id"] == "claim-001"
        assert support["citation_count"] == 1
        assert support["verified_count"] == 1
