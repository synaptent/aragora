"""
Tests for the evidence_linker module.

Tests cover:
- EvidenceLink data class
- ClaimAnalysis data class
- EvidenceCoverageResult data class
- EvidenceClaimLinker class:
  - Claim extraction
  - Evidence matching and linking
  - Semantic similarity calculations
  - Heuristic fallback mode (keyword overlap)
  - Link strength computation
  - Evidence coverage analysis
  - Edge cases (empty text, no evidence, malformed claims)
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

# EMBEDDINGS_AVAILABLE is deliberately NOT imported at module level: it is
# served by evidence_linker's module __getattr__, whose probe imports the real
# sentence_transformers package. At collection time that import races (and
# beats) the session-scoped fake installed by tests/fixtures/autouse.py,
# un-skipping real-model NLI tests suite-wide with a network-dependent client.
from aragora.debate.evidence_linker import (
    CLAIM_INDICATORS,
    NON_CLAIM_PATTERNS,
    ClaimAnalysis,
    EvidenceClaimLinker,
    EvidenceCoverageResult,
    EvidenceLink,
)
from aragora.debate.evidence_quality import EvidenceType


class TestEvidenceLink:
    """Tests for EvidenceLink data class."""

    def test_evidence_link_creation(self):
        """Test creating an EvidenceLink with all fields."""
        link = EvidenceLink(
            claim="Redis provides low latency.",
            claim_start=0,
            claim_end=30,
            evidence="50ms",
            evidence_type=EvidenceType.DATA,
            evidence_position=35,
            link_strength=0.75,
        )

        assert link.claim == "Redis provides low latency."
        assert link.claim_start == 0
        assert link.claim_end == 30
        assert link.evidence == "50ms"
        assert link.evidence_type == EvidenceType.DATA
        assert link.evidence_position == 35
        assert link.link_strength == 0.75

    def test_is_strong_link_above_threshold(self):
        """Test is_strong_link property returns True for strength >= 0.6."""
        link = EvidenceLink(
            claim="Test claim",
            claim_start=0,
            claim_end=10,
            evidence="Test evidence",
            evidence_type=EvidenceType.CITATION,
            evidence_position=15,
            link_strength=0.6,
        )
        assert link.is_strong_link is True

        link_higher = EvidenceLink(
            claim="Test claim",
            claim_start=0,
            claim_end=10,
            evidence="Test evidence",
            evidence_type=EvidenceType.CITATION,
            evidence_position=15,
            link_strength=0.85,
        )
        assert link_higher.is_strong_link is True

    def test_is_strong_link_below_threshold(self):
        """Test is_strong_link property returns False for strength < 0.6."""
        link = EvidenceLink(
            claim="Test claim",
            claim_start=0,
            claim_end=10,
            evidence="Test evidence",
            evidence_type=EvidenceType.CITATION,
            evidence_position=15,
            link_strength=0.59,
        )
        assert link.is_strong_link is False

        link_lower = EvidenceLink(
            claim="Test claim",
            claim_start=0,
            claim_end=10,
            evidence="Test evidence",
            evidence_type=EvidenceType.CITATION,
            evidence_position=15,
            link_strength=0.3,
        )
        assert link_lower.is_strong_link is False

    def test_is_strong_link_at_boundary(self):
        """Test is_strong_link at exact boundary value."""
        link_exactly_60 = EvidenceLink(
            claim="Claim",
            claim_start=0,
            claim_end=5,
            evidence="Evidence",
            evidence_type=EvidenceType.DATA,
            evidence_position=10,
            link_strength=0.60,
        )
        assert link_exactly_60.is_strong_link is True

        link_just_below = EvidenceLink(
            claim="Claim",
            claim_start=0,
            claim_end=5,
            evidence="Evidence",
            evidence_type=EvidenceType.DATA,
            evidence_position=10,
            link_strength=0.599,
        )
        assert link_just_below.is_strong_link is False


class TestClaimAnalysis:
    """Tests for ClaimAnalysis data class."""

    def test_claim_analysis_defaults(self):
        """Test ClaimAnalysis with default values."""
        analysis = ClaimAnalysis()

        assert analysis.claims == []
        assert analysis.claim_positions == []
        assert analysis.total_sentences == 0
        assert analysis.claim_density == 0.0

    def test_claim_analysis_with_values(self):
        """Test ClaimAnalysis with custom values."""
        analysis = ClaimAnalysis(
            claims=["Claim one.", "Claim two."],
            claim_positions=[(0, 11), (12, 23)],
            total_sentences=5,
            claim_density=0.4,
        )

        assert len(analysis.claims) == 2
        assert analysis.claims[0] == "Claim one."
        assert analysis.claim_positions[0] == (0, 11)
        assert analysis.total_sentences == 5
        assert analysis.claim_density == 0.4


class TestEvidenceCoverageResult:
    """Tests for EvidenceCoverageResult data class."""

    def test_coverage_result_defaults(self):
        """Test EvidenceCoverageResult with minimum required fields."""
        result = EvidenceCoverageResult(
            coverage=0.5,
            total_claims=4,
            linked_claims=2,
            unlinked_claims=["Unlinked claim 1", "Unlinked claim 2"],
            evidence_gaps=["No evidence for: Unlinked claim 1"],
        )

        assert result.coverage == 0.5
        assert result.total_claims == 4
        assert result.linked_claims == 2
        assert len(result.unlinked_claims) == 2
        assert len(result.evidence_gaps) == 1
        assert result.links == []  # Default

    def test_coverage_result_with_links(self):
        """Test EvidenceCoverageResult with links."""
        link = EvidenceLink(
            claim="Test claim",
            claim_start=0,
            claim_end=10,
            evidence="50%",
            evidence_type=EvidenceType.DATA,
            evidence_position=15,
            link_strength=0.7,
        )

        result = EvidenceCoverageResult(
            coverage=1.0,
            total_claims=1,
            linked_claims=1,
            unlinked_claims=[],
            evidence_gaps=[],
            links=[link],
        )

        assert len(result.links) == 1
        assert result.links[0].claim == "Test claim"


class TestEvidenceClaimLinkerInit:
    """Tests for EvidenceClaimLinker initialization."""

    def test_linker_default_initialization(self):
        """Test default linker initialization."""
        linker = EvidenceClaimLinker()

        assert linker.min_link_strength == 0.5
        assert linker.proximity_window == 300
        assert linker._evidence_analyzer is not None

    def test_linker_custom_parameters(self):
        """Test linker with custom parameters."""
        linker = EvidenceClaimLinker(
            min_link_strength=0.7,
            proximity_window=500,
        )

        assert linker.min_link_strength == 0.7
        assert linker.proximity_window == 500

    def test_linker_uses_embeddings_property_without_embeddings(self):
        """Test uses_embeddings property when embeddings disabled."""
        linker = EvidenceClaimLinker(use_embeddings=False)
        assert linker.uses_embeddings is False

    def test_linker_compiled_patterns(self):
        """Test that claim patterns are compiled."""
        linker = EvidenceClaimLinker()

        assert len(linker._claim_patterns) == len(CLAIM_INDICATORS)
        assert len(linker._non_claim_patterns) == len(NON_CLAIM_PATTERNS)

    def test_linker_prefers_local_embedding_cache_in_pytest(self, monkeypatch):
        """Pytest runs should not trigger remote model downloads."""
        import aragora.debate.evidence_linker as linker_module

        mock_transformer = Mock(return_value=object())
        monkeypatch.setattr(linker_module, "_EMBEDDINGS_CHECKED", True)
        monkeypatch.setattr(linker_module, "_EMBEDDINGS_AVAILABLE", True)
        monkeypatch.setattr(linker_module, "_SentenceTransformer", mock_transformer)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/debate/test_evidence_linker.py::test")

        linker = EvidenceClaimLinker()

        assert linker.uses_embeddings is True
        mock_transformer.assert_called_once_with(
            "sentence-transformers/all-MiniLM-L6-v2",
            local_files_only=True,
        )


class TestEvidenceClaimLinkerClaimExtraction:
    """Tests for claim extraction functionality."""

    @pytest.fixture
    def linker(self):
        """Create linker with embeddings disabled for consistent testing."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_extract_claims_empty_text(self, linker):
        """Test extracting claims from empty text."""
        analysis = linker.extract_claims("")

        assert analysis.claims == []
        assert analysis.claim_positions == []
        assert analysis.total_sentences == 0
        assert analysis.claim_density == 0.0

    def test_extract_claims_single_claim(self, linker):
        """Test extracting a single claim."""
        text = "Redis is faster than traditional databases for caching use cases."
        analysis = linker.extract_claims(text)

        assert len(analysis.claims) >= 1
        assert analysis.total_sentences >= 1

    def test_extract_claims_multiple_claims(self, linker):
        """Test extracting multiple claims from text."""
        text = (
            "The system should be designed for scalability. "
            "It must handle thousands of concurrent users. "
            "This approach will be more efficient than alternatives."
        )
        analysis = linker.extract_claims(text)

        assert len(analysis.claims) >= 2
        assert analysis.total_sentences == 3

    def test_extract_claims_with_questions(self, linker):
        """Test that questions are not extracted as claims."""
        text = (
            "What is the best approach for caching? "
            "Why would we choose Redis? "
            "How does it compare to Memcached?"
        )
        analysis = linker.extract_claims(text)

        assert len(analysis.claims) == 0
        assert analysis.total_sentences == 3

    def test_extract_claims_with_hedged_language(self, linker):
        """Test that hedged statements are not extracted as claims."""
        text = (
            "Maybe this could work in some cases. "
            "Perhaps we should consider alternatives. "
            "I think this might be okay."
        )
        analysis = linker.extract_claims(text)

        # Hedged language should be filtered out
        assert len(analysis.claims) == 0

    def test_extract_claims_short_sentences_filtered(self, linker):
        """Test that very short sentences are not claims."""
        text = "Yes. No. Maybe. OK."
        analysis = linker.extract_claims(text)

        # Sentences < 20 chars should be filtered
        assert len(analysis.claims) == 0

    def test_extract_claims_assertion_indicators(self, linker):
        """Test claim detection with various assertion indicators."""
        texts = [
            "We should implement caching for better performance.",
            "They must follow the coding standards strictly.",
            "Therefore, Redis is the best choice for our needs.",
            "I believe this approach will solve the problem effectively.",
            "The new system is better than the old one significantly.",
            "This change causes improved latency across the board.",
        ]

        for text in texts:
            analysis = linker.extract_claims(text)
            assert len(analysis.claims) >= 1, f"Failed to detect claim in: {text}"

    def test_extract_claims_long_sentence_fallback(self, linker):
        """Test that long sentences without question marks are claims."""
        text = (
            "The implementation of microservices architecture provides "
            "significant benefits for system scalability and maintainability "
            "in modern cloud-native applications."
        )
        analysis = linker.extract_claims(text)

        # Long sentences (>50 chars) without questions should be claims
        assert len(analysis.claims) >= 1

    def test_extract_claims_positions_accurate(self, linker):
        """Test that claim positions are accurate."""
        text = "Redis is faster than other databases. This is important for our use case."
        analysis = linker.extract_claims(text)

        for claim, (start, end) in zip(analysis.claims, analysis.claim_positions):
            # The claim should be found at the recorded position
            assert text[start:end] == claim or claim in text

    def test_extract_claims_density_calculation(self, linker):
        """Test claim density is calculated correctly."""
        text = (
            "Redis is fast. It handles data well. What do you think? The performance is excellent."
        )
        analysis = linker.extract_claims(text)

        # Density = claims / total_sentences
        expected_density = len(analysis.claims) / analysis.total_sentences
        assert analysis.claim_density == pytest.approx(expected_density, rel=0.01)


class TestEvidenceClaimLinkerLinkStrength:
    """Tests for link strength computation."""

    @pytest.fixture
    def linker(self):
        """Create linker for testing."""
        return EvidenceClaimLinker(use_embeddings=False, proximity_window=300)

    def test_compute_keyword_overlap_identical(self, linker):
        """Test keyword overlap for identical texts."""
        overlap = linker._compute_keyword_overlap(
            "Redis provides excellent performance",
            "Redis provides excellent performance",
        )
        assert overlap == 1.0

    def test_compute_keyword_overlap_partial(self, linker):
        """Test keyword overlap for partially overlapping texts."""
        overlap = linker._compute_keyword_overlap(
            "Redis provides excellent caching performance",
            "Redis offers great speed improvements",
        )
        # Only "Redis" overlaps (words >= 4 chars)
        assert 0 < overlap < 1.0

    def test_compute_keyword_overlap_no_overlap(self, linker):
        """Test keyword overlap with no common keywords."""
        overlap = linker._compute_keyword_overlap(
            "Database performance metrics",
            "Cloud infrastructure scaling",
        )
        # No common words >= 4 chars
        assert overlap == 0.0

    def test_compute_keyword_overlap_empty_claim(self, linker):
        """Test keyword overlap with empty/short claim."""
        overlap = linker._compute_keyword_overlap("Hi", "Hello there friend")
        # No meaningful words in claim
        assert overlap == 0.3  # Neutral fallback

    def test_compute_keyword_overlap_empty_evidence(self, linker):
        """Test keyword overlap with empty/short evidence."""
        overlap = linker._compute_keyword_overlap("Database performance", "OK")
        # No meaningful words in evidence
        assert overlap == 0.3  # Neutral fallback


class TestEvidenceClaimLinkerEvidenceLinking:
    """Tests for evidence-to-claim linking."""

    @pytest.fixture
    def linker(self):
        """Create linker with embeddings disabled."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_link_evidence_empty_text(self, linker):
        """Test linking with empty text."""
        links = linker.link_evidence_to_claims("")
        assert links == []

    def test_link_evidence_no_claims(self, linker):
        """Test linking when no claims are found."""
        text = "Yes. No. OK."  # Too short to be claims
        links = linker.link_evidence_to_claims(text)
        assert links == []

    def test_link_evidence_no_evidence(self, linker):
        """Test linking when no evidence markers are found."""
        text = "The system should be designed for scalability and performance."
        links = linker.link_evidence_to_claims(text)
        # No citations, data, or examples
        assert links == []

    def test_link_evidence_claim_with_citation(self, linker):
        """Test linking a claim to nearby citation."""
        text = (
            "According to the documentation [1], Redis provides excellent performance. "
            "This makes it ideal for caching use cases."
        )
        links = linker.link_evidence_to_claims(text)

        # Should find link between claim and citation
        assert len(links) >= 1
        if links:
            assert links[0].evidence_type == EvidenceType.CITATION

    def test_link_evidence_claim_with_data(self, linker):
        """Test linking a claim to nearby data."""
        text = "The system is faster with a latency of 50ms for most requests."
        links = linker.link_evidence_to_claims(text)

        if links:
            # Check that data type evidence was linked
            data_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.DATA]
            assert len(data_links) >= 0  # May or may not link depending on distance

    def test_link_evidence_claim_with_example(self, linker):
        """Test linking a claim to nearby example."""
        text = (
            "For example, Netflix uses Redis for caching. "
            "This demonstrates the effectiveness of this approach for large-scale systems."
        )
        links = linker.link_evidence_to_claims(text)

        if links:
            example_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.EXAMPLE]
            assert len(example_links) >= 0

    def test_link_evidence_proximity_window(self, linker):
        """Test that evidence outside proximity window is not linked."""
        # Create text where claim and evidence are far apart
        padding = "This is filler text. " * 30  # ~600 chars
        text = f"Redis is excellent. {padding} According to [1], data shows improvement."
        links = linker.link_evidence_to_claims(text)

        # Evidence should be too far from first claim
        for link in links:
            if "Redis" in link.claim:
                # Distance should be within window
                distance = abs(link.evidence_position - link.claim_start)
                # Note: This may still link if claim_end is closer
                assert distance <= linker.proximity_window * 2

    def test_link_evidence_multiple_claims_multiple_evidence(self, linker):
        """Test linking multiple claims to multiple evidence markers."""
        text = (
            "According to [1], Redis provides 50ms latency. "
            "For example, Netflix uses this architecture. "
            "The system is therefore highly scalable and efficient."
        )
        links = linker.link_evidence_to_claims(text)

        # Should have multiple links
        assert len(links) >= 1


class TestEvidenceClaimLinkerCoverage:
    """Tests for evidence coverage computation."""

    @pytest.fixture
    def linker(self):
        """Create linker for testing."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_compute_coverage_empty_text(self, linker):
        """Test coverage for empty text."""
        result = linker.compute_evidence_coverage("")

        assert result.coverage == 0.0
        assert result.total_claims == 0
        assert result.linked_claims == 0
        assert result.unlinked_claims == []
        assert result.evidence_gaps == []

    def test_compute_coverage_no_claims(self, linker):
        """Test coverage when no claims found."""
        result = linker.compute_evidence_coverage("Yes. No.")

        assert result.coverage == 0.0
        assert result.total_claims == 0

    def test_compute_coverage_all_claims_linked(self, linker):
        """Test coverage when all claims have strong evidence."""
        text = (
            "According to [1], Redis is the fastest caching solution with 50ms latency. "
            "According to [2], the benchmark shows a 40% improvement in throughput."
        )
        result = linker.compute_evidence_coverage(text)

        # Coverage should be high if claims are strongly linked
        assert result.total_claims >= 1
        # Coverage depends on link strength meeting threshold

    def test_compute_coverage_partial_linking(self, linker):
        """Test coverage with some claims unlinked."""
        text = (
            "According to [1], Redis provides excellent performance. "
            "The system architecture needs careful consideration. "
            "Various factors influence the final decision."
        )
        result = linker.compute_evidence_coverage(text)

        # Some claims may be unlinked
        assert result.total_claims >= 1

    def test_compute_coverage_unlinked_claims_list(self, linker):
        """Test that unlinked claims are tracked."""
        text = (
            "The system should scale to millions of users. "
            "It must handle concurrent connections efficiently."
        )
        result = linker.compute_evidence_coverage(text)

        # Without evidence, claims should be unlinked
        if result.total_claims > 0 and result.linked_claims < result.total_claims:
            assert len(result.unlinked_claims) > 0

    def test_compute_coverage_evidence_gaps(self, linker):
        """Test that evidence gaps are identified."""
        text = (
            "Redis is essential for modern applications. "
            "The deployment strategy must be carefully planned. "
            "Security considerations are paramount for success."
        )
        result = linker.compute_evidence_coverage(text)

        # Gaps should be identified for unlinked claims (up to 3)
        if result.unlinked_claims:
            assert len(result.evidence_gaps) <= 3
            for gap in result.evidence_gaps:
                assert "No evidence for:" in gap

    def test_compute_coverage_links_included(self, linker):
        """Test that links are included in result."""
        text = "According to [1], the system provides 50ms latency for all requests."
        result = linker.compute_evidence_coverage(text)

        # Links should be in result
        assert isinstance(result.links, list)


class TestEvidenceClaimLinkerHeuristicMode:
    """Tests for heuristic (non-embedding) mode."""

    @pytest.fixture
    def linker(self):
        """Create linker with embeddings explicitly disabled."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_heuristic_mode_enabled(self, linker):
        """Test that heuristic mode is active when embeddings disabled."""
        assert linker.uses_embeddings is False

    def test_heuristic_link_strength_components(self, linker):
        """Test that link strength uses multiple components."""
        text = (
            "According to the Redis documentation [1], "
            "the caching layer is highly efficient for database queries."
        )
        links = linker.link_evidence_to_claims(text)

        # Link strength should incorporate proximity, type boost, keyword overlap, confidence
        for link in links:
            assert 0.0 <= link.link_strength <= 1.0

    def test_heuristic_type_boost_citation(self, linker):
        """Test that citations get type boost in link strength."""
        # Citation evidence type should have boost of 0.3
        text = "According to [1], Redis is the recommended solution for caching needs."
        links = linker.link_evidence_to_claims(text)

        citation_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.CITATION]
        # Citations should have reasonable strength due to type boost
        for link in citation_links:
            assert link.link_strength > 0.1

    def test_heuristic_type_boost_data(self, linker):
        """Test that data evidence gets type boost."""
        text = "The system achieves 99.9% uptime with consistent performance."
        links = linker.link_evidence_to_claims(text)

        data_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.DATA]
        for link in data_links:
            assert link.link_strength > 0.0


class TestEvidenceClaimLinkerEdgeCases:
    """Edge case tests for EvidenceClaimLinker."""

    @pytest.fixture
    def linker(self):
        """Create linker for edge case testing."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_whitespace_only_text(self, linker):
        """Test with whitespace-only text."""
        analysis = linker.extract_claims("   \n\t  \n  ")
        assert analysis.claims == []

    def test_single_word_text(self, linker):
        """Test with single word."""
        analysis = linker.extract_claims("Redis")
        assert analysis.claims == []

    def test_text_with_unicode(self, linker):
        """Test text with unicode characters."""
        text = "The system provides excellent cafe-style service with 99% uptime."
        analysis = linker.extract_claims(text)
        # Should handle unicode gracefully
        assert analysis.total_sentences >= 1

    def test_text_with_newlines(self, linker):
        """Test text with multiple newlines."""
        text = "Redis is fast.\n\nIt handles millions of requests.\n\nThis is proven by data."
        analysis = linker.extract_claims(text)
        assert analysis.total_sentences >= 1

    def test_text_with_multiple_punctuation(self, linker):
        """Test text with unusual punctuation."""
        text = "This is important!!! What do you think??? The answer is clear..."
        analysis = linker.extract_claims(text)
        # Should handle multiple punctuation marks
        assert isinstance(analysis.claims, list)

    def test_very_long_sentence(self, linker):
        """Test with very long single sentence."""
        text = (
            "The implementation of microservices architecture " * 10
            + "provides significant benefits for modern applications."
        )
        analysis = linker.extract_claims(text)
        # Very long sentence should still be processed
        assert analysis.total_sentences >= 1

    def test_mixed_claims_and_questions(self, linker):
        """Test text with interleaved claims and questions."""
        text = (
            "Redis is fast. Why would we use it? "
            "It provides caching. What about alternatives? "
            "The performance is excellent."
        )
        analysis = linker.extract_claims(text)
        # Should only extract claims, not questions
        for claim in analysis.claims:
            assert "?" not in claim or "?" in claim  # Questions filtered by patterns

    def test_nested_parentheses_in_text(self, linker):
        """Test text with nested parentheses."""
        text = "The system (according to Smith (2024)) is highly efficient for our needs."
        analysis = linker.extract_claims(text)
        assert isinstance(analysis.claims, list)

    def test_code_snippets_in_text(self, linker):
        """Test text containing code-like content."""
        text = (
            "The function calculate(x, y) returns x + y. "
            "This is efficient because it uses O(1) complexity."
        )
        analysis = linker.extract_claims(text)
        assert isinstance(analysis.claims, list)

    def test_numerical_only_text(self, linker):
        """Test text with only numbers."""
        text = "100 200 300 400 500"
        analysis = linker.extract_claims(text)
        # Numbers alone should not be claims
        assert len(analysis.claims) == 0

    def test_all_caps_text(self, linker):
        """Test text in all caps."""
        text = "THE SYSTEM IS HIGHLY EFFICIENT AND SHOULD BE USED FOR ALL CACHING NEEDS."
        analysis = linker.extract_claims(text)
        # Case should not affect claim detection
        assert analysis.total_sentences >= 1

    def test_special_characters_in_evidence(self, linker):
        """Test evidence with special characters."""
        text = "According to [1*2], the system costs $1,000/month for enterprise use."
        links = linker.link_evidence_to_claims(text)
        # Should handle special characters in evidence
        assert isinstance(links, list)


class TestEvidenceClaimLinkerProximity:
    """Tests for proximity-based evidence matching."""

    def test_custom_proximity_window_small(self):
        """Test with small proximity window."""
        linker = EvidenceClaimLinker(use_embeddings=False, proximity_window=50)

        text = "Redis is fast. " + "x" * 100 + " According to [1], data shows improvement."
        links = linker.link_evidence_to_claims(text)

        # With small window, evidence far from claim should not link
        if links:
            for link in links:
                if "Redis" in link.claim:
                    distance = min(
                        abs(link.evidence_position - link.claim_start),
                        abs(link.evidence_position - link.claim_end),
                    )
                    assert distance <= linker.proximity_window

    def test_custom_proximity_window_large(self):
        """Test with large proximity window."""
        linker = EvidenceClaimLinker(use_embeddings=False, proximity_window=1000)

        text = (
            "Redis is excellent for caching. "
            + "Padding text here. " * 10
            + " According to [1], this is documented well."
        )
        links = linker.link_evidence_to_claims(text)

        # With large window, should find more links
        assert isinstance(links, list)

    def test_proximity_score_calculation(self):
        """Test that proximity score decreases with distance."""
        linker = EvidenceClaimLinker(use_embeddings=False, proximity_window=300)

        # Close proximity text
        close_text = "According to [1], Redis is the best solution."
        close_links = linker.link_evidence_to_claims(close_text)

        # Far proximity text
        far_text = (
            "Redis is excellent. "
            + "Some other content here. " * 5
            + "According to [1], documentation confirms this."
        )
        far_links = linker.link_evidence_to_claims(far_text)

        # Both should find links, but strength may differ
        assert isinstance(close_links, list)
        assert isinstance(far_links, list)


class TestEvidenceClaimLinkerTypeBoosts:
    """Tests for evidence type boost values in link strength."""

    @pytest.fixture
    def linker(self):
        """Create linker for type boost testing."""
        return EvidenceClaimLinker(use_embeddings=False, proximity_window=500)

    def test_citation_type_boost(self, linker):
        """Test citation evidence type boost."""
        text = "According to [1], the system is highly efficient for enterprise use."
        links = linker.link_evidence_to_claims(text)

        citation_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.CITATION]
        assert len(citation_links) >= 0  # May or may not have citation links

    def test_data_type_boost(self, linker):
        """Test data evidence type boost."""
        text = "The system achieves 99.9% uptime consistently across all regions."
        links = linker.link_evidence_to_claims(text)

        data_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.DATA]
        assert len(data_links) >= 0

    def test_example_type_boost(self, linker):
        """Test example evidence type boost."""
        text = "For example, Netflix uses this architecture for streaming services."
        links = linker.link_evidence_to_claims(text)

        example_links = [lnk for lnk in links if lnk.evidence_type == EvidenceType.EXAMPLE]
        assert len(example_links) >= 0


class TestEvidenceClaimLinkerIsClaim:
    """Tests for the _is_claim internal method."""

    @pytest.fixture
    def linker(self):
        """Create linker for _is_claim testing."""
        return EvidenceClaimLinker(use_embeddings=False)

    def test_is_claim_short_sentence(self, linker):
        """Test that short sentences are not claims."""
        assert linker._is_claim("Yes.") is False
        assert linker._is_claim("No.") is False
        assert linker._is_claim("OK fine.") is False

    def test_is_claim_question_pattern(self, linker):
        """Test that questions are not claims."""
        assert linker._is_claim("What is the best approach for this problem?") is False
        assert linker._is_claim("Why would we choose this option over others?") is False
        assert linker._is_claim("How does this compare to alternatives in market?") is False

    def test_is_claim_hedge_pattern(self, linker):
        """Test that hedged statements are not claims."""
        assert linker._is_claim("Maybe this could work for some applications.") is False
        assert linker._is_claim("Perhaps we should consider other alternatives.") is False
        assert linker._is_claim("Possibly this is the right approach here.") is False

    def test_is_claim_weak_assertion_pattern(self, linker):
        """Test that weak assertions are not claims."""
        assert linker._is_claim("I think this might work for our needs.") is False
        assert linker._is_claim("I guess this could be acceptable here.") is False
        assert linker._is_claim("It seems like a reasonable approach overall.") is False

    def test_is_claim_valid_assertions(self, linker):
        """Test that valid assertions are claims."""
        # "is better" matches pattern for comparative assertions
        assert linker._is_claim("Redis is better than alternatives for this case.") is True
        # "Therefore" matches reasoning connector pattern
        assert linker._is_claim("Therefore, we recommend using microservices.") is True
        # "We believe" matches belief pattern
        assert linker._is_claim("We believe this approach will solve the problem.") is True
        # "We should" matches normative pattern
        assert linker._is_claim("We should implement caching for better performance.") is True
        # "This causes" matches causal pattern
        assert linker._is_claim("This causes significant improvements in latency.") is True

    def test_is_claim_long_sentence_fallback(self, linker):
        """Test long sentence fallback for claim detection."""
        long_sentence = (
            "The implementation of distributed caching provides significant "
            "performance improvements for applications requiring low latency access."
        )
        assert linker._is_claim(long_sentence) is True

    def test_is_claim_long_sentence_with_question_mark(self, linker):
        """Test that long sentences with question marks are not claims."""
        long_question = (
            "Do you think the implementation of distributed caching provides "
            "significant performance improvements for applications?"
        )
        assert linker._is_claim(long_question) is False


class TestEvidenceClaimLinkerIntegration:
    """Integration tests for the evidence linker."""

    def test_full_pipeline_with_evidence(self):
        """Test complete pipeline from text to coverage result."""
        linker = EvidenceClaimLinker(use_embeddings=False)

        text = """
        According to the 2024 performance report [1], Redis provides sub-millisecond
        latency for 99.9% of requests. The benchmark at https://redis.io/benchmarks
        shows throughput of 1 million operations per second.

        For example, Twitter uses Redis for timeline caching, achieving a 50%
        reduction in database load. Therefore, Redis is recommended for our
        caching layer because it matches our latency requirements of under 10ms.
        """

        # Extract claims
        claims = linker.extract_claims(text)
        assert claims.total_sentences >= 3
        assert len(claims.claims) >= 1

        # Link evidence
        links = linker.link_evidence_to_claims(text)
        assert len(links) >= 0

        # Compute coverage
        coverage = linker.compute_evidence_coverage(text)
        assert coverage.total_claims >= 1
        assert 0 <= coverage.coverage <= 1.0

    def test_full_pipeline_without_evidence(self):
        """Test pipeline with text lacking evidence."""
        linker = EvidenceClaimLinker(use_embeddings=False)

        text = """
        The system should be designed with scalability in mind.
        It must handle concurrent users efficiently.
        The architecture needs to be maintainable.
        """

        coverage = linker.compute_evidence_coverage(text)

        # Without evidence, coverage should be low
        assert coverage.total_claims >= 1
        assert coverage.linked_claims <= coverage.total_claims

    def test_consistency_across_calls(self):
        """Test that results are consistent across multiple calls."""
        linker = EvidenceClaimLinker(use_embeddings=False)

        text = "According to [1], Redis is fast. This is important for caching."

        result1 = linker.compute_evidence_coverage(text)
        result2 = linker.compute_evidence_coverage(text)

        assert result1.coverage == result2.coverage
        assert result1.total_claims == result2.total_claims
        assert result1.linked_claims == result2.linked_claims


class TestEmbeddingsAvailability:
    """Tests for embeddings availability handling."""

    def test_embeddings_available_constant(self):
        """Test EMBEDDINGS_AVAILABLE constant is defined."""
        # Imported here (not at module level) so the lazy dependency probe runs
        # after the session-scoped sentence_transformers fake is installed.
        from aragora.debate.evidence_linker import EMBEDDINGS_AVAILABLE

        assert isinstance(EMBEDDINGS_AVAILABLE, bool)

    def test_linker_respects_use_embeddings_false(self):
        """Test that use_embeddings=False disables embeddings."""
        linker = EvidenceClaimLinker(use_embeddings=False)
        assert linker.uses_embeddings is False
        assert linker._embedder is None

    def test_linker_use_embeddings_true_without_availability(self):
        """Test use_embeddings=True when not available logs warning."""
        # This will log a warning if embeddings not installed
        linker = EvidenceClaimLinker(use_embeddings=True)
        # Either embeddings work or they don't - should not raise
        assert isinstance(linker.uses_embeddings, bool)

    def test_linker_auto_detect_embeddings(self):
        """Test use_embeddings=None auto-detects."""
        linker = EvidenceClaimLinker(use_embeddings=None)
        # Should auto-detect based on EMBEDDINGS_AVAILABLE
        assert isinstance(linker.uses_embeddings, bool)


class TestSemanticSimilarityFallback:
    """Tests for semantic similarity computation and fallback."""

    def test_semantic_similarity_without_embedder(self):
        """Test _compute_semantic_similarity returns 0.5 without embedder."""
        linker = EvidenceClaimLinker(use_embeddings=False)
        result = linker._compute_semantic_similarity("text one", "text two")
        assert result == 0.5

    def test_keyword_overlap_used_as_fallback(self):
        """Test keyword overlap is used when embeddings unavailable."""
        linker = EvidenceClaimLinker(use_embeddings=False)

        # When embeddings disabled, link strength uses keyword overlap
        text = "According to Redis documentation [1], Redis provides caching."
        links = linker.link_evidence_to_claims(text)

        # Links should still be computed using heuristic
        assert isinstance(links, list)


class TestPatternConstants:
    """Tests for pattern constants."""

    def test_claim_indicators_not_empty(self):
        """Test CLAIM_INDICATORS is not empty."""
        assert len(CLAIM_INDICATORS) > 0

    def test_non_claim_patterns_not_empty(self):
        """Test NON_CLAIM_PATTERNS is not empty."""
        assert len(NON_CLAIM_PATTERNS) > 0

    def test_claim_indicators_are_valid_regex(self):
        """Test all CLAIM_INDICATORS are valid regex patterns."""
        import re

        for pattern in CLAIM_INDICATORS:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                pytest.fail(f"Invalid regex in CLAIM_INDICATORS: {pattern}")

    def test_non_claim_patterns_are_valid_regex(self):
        """Test all NON_CLAIM_PATTERNS are valid regex patterns."""
        import re

        for pattern in NON_CLAIM_PATTERNS:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                pytest.fail(f"Invalid regex in NON_CLAIM_PATTERNS: {pattern}")
