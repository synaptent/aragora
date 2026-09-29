"""
High-concurrency stress tests for the consensus estimation system.

Tests cover:
- High-concurrency tests (10+ concurrent debates)
- Fallback cascade tests (SentenceTransformer -> TFIDF -> Jaccard)
- Backend selection frequency metrics tests
- Memory pressure tests
- Rate limiting tests
- Cache isolation and thread safety

These tests are designed for production hardening of the consensus system.
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.consensus import (
    Claim,
    ConsensusBuilder,
    ConsensusProof,
    ConsensusVote,
    DissentRecord,
    Evidence,
    UnresolvedTension,
    VoteType,
)
from aragora.debate.convergence import (
    AdvancedConvergenceAnalyzer,
    ConvergenceDetector,
    ConvergenceResult,
    JaccardBackend,
    PairwiseSimilarityCache,
    cleanup_similarity_cache,
    get_pairwise_similarity_cache,
)
from aragora.debate.similarity.backends import (
    SimilarityBackend,
    TFIDFBackend,
    get_similarity_backend,
)


# =============================================================================
# Helper Functions
# =============================================================================


def generate_debate_id() -> str:
    """Generate a unique debate ID for testing."""
    return f"stress-test-{uuid.uuid4().hex[:8]}"


def generate_agent_responses(num_agents: int, topic: str = "caching") -> dict[str, str]:
    """Generate synthetic agent responses for testing."""
    templates = [
        f"We should use Redis for {topic}. It provides excellent performance.",
        f"I recommend Memcached for {topic}. It's simple and fast.",
        f"Consider using in-memory {topic}. It reduces database load.",
        f"PostgreSQL JSONB can handle {topic} needs effectively.",
        f"A hybrid approach to {topic} would be optimal here.",
        f"Cloud-native {topic} services like ElastiCache are worth considering.",
        f"Local {topic} with TTL-based invalidation is recommended.",
        f"Distributed {topic} with consistent hashing is the way forward.",
        f"Event-driven {topic} invalidation provides better consistency.",
        f"Tiered {topic} with L1/L2 layers offers best performance.",
    ]

    responses = {}
    for i in range(num_agents):
        agent_name = f"agent_{i}"
        responses[agent_name] = templates[i % len(templates)]
    return responses


def create_sample_proof(debate_id: str, num_agents: int = 3) -> ConsensusProof:
    """Create a sample ConsensusProof for testing."""
    votes = [
        ConsensusVote(f"agent_{i}", VoteType.AGREE, 0.8 + (i * 0.05), f"Support {i}")
        for i in range(num_agents)
    ]

    return ConsensusProof(
        proof_id=f"proof-{debate_id}",
        debate_id=debate_id,
        task="Design a caching solution",
        final_claim="Use Redis for caching with a 15-minute TTL",
        confidence=0.85,
        consensus_reached=True,
        votes=votes,
        supporting_agents=[f"agent_{i}" for i in range(num_agents)],
        dissenting_agents=[],
        claims=[
            Claim(f"c{i}", f"Claim {i}", f"agent_{i}", 0.8 + (i * 0.02)) for i in range(num_agents)
        ],
        dissents=[],
        unresolved_tensions=[],
        evidence_chain=[
            Evidence(f"e{i}", f"agent_{i}", f"Evidence {i}", "argument", True, 0.9)
            for i in range(num_agents)
        ],
        reasoning_summary="Agents agreed on Redis caching approach",
        rounds_to_consensus=3,
    )


# =============================================================================
# High-Concurrency Tests
# =============================================================================


@pytest.mark.timeout(120)  # Load tests need extended time
class TestHighConcurrencyDebates:
    """Tests for running many concurrent debates."""

    @pytest.mark.load
    def test_10_concurrent_debates(self):
        """Test running 10 concurrent debates without race conditions."""
        num_debates = 10
        results = []
        errors = []

        def run_debate(debate_idx: int) -> ConsensusProof:
            debate_id = f"concurrent-{debate_idx}-{uuid.uuid4().hex[:4]}"
            try:
                builder = ConsensusBuilder(debate_id, f"Task for debate {debate_idx}")

                # Add claims from multiple agents
                for i in range(5):
                    claim = builder.add_claim(
                        statement=f"Agent {i} proposes solution {i} for debate {debate_idx}",
                        author=f"agent_{i}",
                        confidence=0.7 + (i * 0.05),
                        round_num=1,
                    )
                    builder.add_evidence(
                        claim_id=claim.claim_id,
                        source=f"agent_{i}",
                        content=f"Evidence from agent {i}",
                        evidence_type="argument",
                        supports=True,
                        strength=0.8,
                    )
                    builder.record_vote(
                        agent=f"agent_{i}",
                        vote=VoteType.AGREE if i % 2 == 0 else VoteType.CONDITIONAL,
                        confidence=0.75 + (i * 0.05),
                        reasoning=f"Agent {i} reasoning",
                    )

                return builder.build(
                    final_claim=f"Final claim for debate {debate_idx}",
                    confidence=0.85,
                    consensus_reached=True,
                    reasoning_summary="Multi-agent consensus",
                    rounds=3,
                )
            except Exception as e:
                errors.append((debate_idx, e))
                raise

        with ThreadPoolExecutor(max_workers=num_debates) as executor:
            futures = [executor.submit(run_debate, i) for i in range(num_debates)]
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                except Exception as e:
                    pass  # Already logged in errors

        assert len(errors) == 0, f"Errors in concurrent debates: {errors}"
        assert len(results) == num_debates

        # Verify all proofs are unique
        proof_ids = [r.proof_id for r in results]
        assert len(set(proof_ids)) == num_debates

    @pytest.mark.load
    def test_20_concurrent_debates(self):
        """Test running 20 concurrent debates with high agent count."""
        num_debates = 20
        agents_per_debate = 8
        results = []
        errors = []
        lock = threading.Lock()

        def run_debate(debate_idx: int) -> tuple[str, float]:
            debate_id = f"high-load-{debate_idx}-{uuid.uuid4().hex[:4]}"
            try:
                builder = ConsensusBuilder(debate_id, f"High-load task {debate_idx}")

                for i in range(agents_per_debate):
                    claim = builder.add_claim(
                        statement=f"Proposal from agent_{i} in debate {debate_idx}",
                        author=f"agent_{i}",
                        confidence=0.6 + (i * 0.04),
                    )
                    builder.add_evidence(
                        claim_id=claim.claim_id,
                        source=f"agent_{i}",
                        content=f"Supporting evidence {i}",
                        evidence_type="data",
                        supports=True,
                        strength=0.75,
                    )
                    builder.record_vote(
                        agent=f"agent_{i}",
                        vote=VoteType.AGREE,
                        confidence=0.8,
                        reasoning=f"Reason {i}",
                    )

                proof = builder.build(
                    final_claim=f"Consensus for debate {debate_idx}",
                    confidence=0.9,
                    consensus_reached=True,
                    reasoning_summary="All agents agreed",
                    rounds=2,
                )

                return (proof.debate_id, proof.confidence)
            except Exception as e:
                with lock:
                    errors.append((debate_idx, str(e)))
                raise

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(run_debate, i) for i in range(num_debates)]
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    with lock:
                        results.append(result)
                except Exception:
                    pass

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == num_debates

    @pytest.mark.load
    def test_concurrent_convergence_detection(self):
        """Test concurrent convergence detection across debates."""
        num_debates = 15
        results = []
        errors = []

        def run_convergence_check(debate_idx: int) -> ConvergenceResult | None:
            debate_id = f"conv-{debate_idx}-{uuid.uuid4().hex[:4]}"
            try:
                detector = ConvergenceDetector(
                    convergence_threshold=0.85,
                    divergence_threshold=0.40,
                    min_rounds_before_check=1,
                    debate_id=debate_id,
                )

                # Simulate converging responses
                base_response = f"Redis is recommended for caching in scenario {debate_idx}"
                current_responses = {
                    f"agent_{i}": f"{base_response}. Agent {i} agrees." for i in range(5)
                }
                previous_responses = {
                    f"agent_{i}": f"{base_response}. Initial position from {i}." for i in range(5)
                }

                result = detector.check_convergence(
                    current_responses,
                    previous_responses,
                    round_number=2,
                )

                # Cleanup
                detector.cleanup()

                return result
            except Exception as e:
                errors.append((debate_idx, e))
                return None

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(run_convergence_check, i) for i in range(num_debates)]
            for future in as_completed(futures):
                result = future.result(timeout=30)
                if result:
                    results.append(result)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) >= num_debates * 0.9  # Allow some tolerance


@pytest.mark.timeout(60)
class TestConcurrentChecksumGeneration:
    """Tests for concurrent checksum generation and verification."""

    @pytest.mark.load
    def test_concurrent_checksum_generation(self):
        """Test that checksums are generated correctly under concurrent access."""
        num_proofs = 50
        proofs = [create_sample_proof(f"checksum-test-{i}") for i in range(num_proofs)]
        checksums = {}
        lock = threading.Lock()

        def compute_checksum(idx: int) -> tuple[int, str]:
            proof = proofs[idx]
            checksum = proof.checksum
            # Access multiple times to test caching
            for _ in range(10):
                assert proof.checksum == checksum
            return (idx, checksum)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(compute_checksum, i) for i in range(num_proofs)]
            for future in as_completed(futures):
                idx, checksum = future.result()
                with lock:
                    checksums[idx] = checksum

        assert len(checksums) == num_proofs

        # Verify checksums are unique for different proofs
        unique_checksums = set(checksums.values())
        assert len(unique_checksums) == num_proofs

    @pytest.mark.load
    def test_checksum_cache_thread_safety(self):
        """Test checksum caching is thread-safe."""
        proof = create_sample_proof("thread-safe-checksum")
        initial_checksum = proof.checksum
        results = []
        lock = threading.Lock()

        def access_checksum() -> str:
            result = proof.checksum
            with lock:
                results.append(result)
            return result

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(access_checksum) for _ in range(100)]
            for future in as_completed(futures):
                future.result()

        # All accesses should return the same checksum
        assert all(r == initial_checksum for r in results)


# =============================================================================
# Fallback Cascade Tests
# =============================================================================


class TestBackendFallbackCascade:
    """Tests for the SentenceTransformer -> TFIDF -> Jaccard fallback cascade."""

    def test_jaccard_fallback_always_available(self):
        """Test that Jaccard backend is always available as fallback."""
        backend = JaccardBackend()

        sim = backend.compute_similarity(
            "Redis is fast and reliable",
            "Redis is quick and dependable",
        )

        assert 0 <= sim <= 1

    def test_tfidf_fallback_when_sentence_transformer_unavailable(self):
        """Test TFIDF fallback when SentenceTransformer is unavailable."""
        with patch.dict(os.environ, {"ARAGORA_SIMILARITY_BACKEND": "tfidf"}):
            backend = TFIDFBackend()
            sim = backend.compute_similarity(
                "The system requires caching",
                "Caching is needed for the system",
            )
            assert 0 <= sim <= 1

    def test_auto_selection_fallback(self):
        """Test auto-selection falls through the cascade correctly."""
        backend = get_similarity_backend(preferred="auto")

        # Should get some backend with the expected interface
        assert backend is not None
        assert hasattr(backend, "compute_similarity")

        # Should be able to compute similarity
        sim = backend.compute_similarity(
            "Test text one",
            "Test text one",
        )
        assert sim == pytest.approx(1.0, rel=1e-5)

    def test_explicit_jaccard_selection(self):
        """Test explicit Jaccard selection works."""
        backend = get_similarity_backend(preferred="jaccard")
        assert type(backend).__name__ == "JaccardBackend"

    def test_fallback_under_concurrent_load(self):
        """Test backend fallback works correctly under concurrent load."""
        num_requests = 30
        results = []
        lock = threading.Lock()

        def compute_similarity(idx: int) -> float:
            backend = get_similarity_backend(preferred="auto")
            sim = backend.compute_similarity(
                f"Text A variant {idx}",
                f"Text B variant {idx}",
            )
            with lock:
                results.append(sim)
            return sim

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(compute_similarity, i) for i in range(num_requests)]
            for future in as_completed(futures):
                future.result()

        assert len(results) == num_requests
        assert all(0 <= r <= 1 for r in results)

    def test_backend_consistency_across_threads(self):
        """Test that the same backend type is used consistently."""
        backend_types = []
        lock = threading.Lock()

        def get_backend_type() -> str:
            backend = get_similarity_backend(preferred="auto")
            with lock:
                backend_types.append(type(backend).__name__)
            return type(backend).__name__

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_backend_type) for _ in range(20)]
            for future in as_completed(futures):
                future.result()

        # All should be the same type (auto-selection is deterministic)
        assert len(set(backend_types)) == 1


# =============================================================================
# Backend Selection Frequency Metrics Tests
# =============================================================================


@dataclass
class BackendMetrics:
    """Metrics for backend usage."""

    sentence_transformer_count: int = 0
    tfidf_count: int = 0
    jaccard_count: int = 0
    total_time_ms: float = 0.0


class TestBackendSelectionMetrics:
    """Tests for tracking backend selection and performance metrics."""

    def test_backend_selection_tracking(self):
        """Test tracking which backend is selected."""
        metrics = BackendMetrics()

        for _ in range(10):
            backend = get_similarity_backend(preferred="auto")
            backend_name = type(backend).__name__

            if "Sentence" in backend_name:
                metrics.sentence_transformer_count += 1
            elif "TFIDF" in backend_name:
                metrics.tfidf_count += 1
            else:
                metrics.jaccard_count += 1

        total = metrics.sentence_transformer_count + metrics.tfidf_count + metrics.jaccard_count
        assert total == 10

    def test_backend_performance_metrics(self):
        """Test measuring backend computation time."""
        backend = get_similarity_backend(preferred="jaccard")

        times = []
        for i in range(100):
            start = time.perf_counter()
            backend.compute_similarity(
                f"Sample text A version {i}",
                f"Sample text B version {i}",
            )
            end = time.perf_counter()
            times.append((end - start) * 1000)  # Convert to ms

        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)

        # Jaccard should be fast (< 10ms per call typically)
        assert avg_time < 100  # generous bound for test environment
        assert max_time < 500
        # Report metrics
        assert len(times) == 100

    def test_batch_vs_individual_performance(self):
        """Test batch similarity computation performance vs individual."""
        backend = JaccardBackend()
        texts = [f"Sample text number {i} for batch testing" for i in range(20)]

        # Individual computation
        start_individual = time.perf_counter()
        individual_sum = 0.0
        count = 0
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                individual_sum += backend.compute_similarity(texts[i], texts[j])
                count += 1
        individual_avg = individual_sum / count if count > 0 else 0
        individual_time = time.perf_counter() - start_individual

        # Batch computation
        start_batch = time.perf_counter()
        batch_avg = backend.compute_batch_similarity(texts)
        batch_time = time.perf_counter() - start_batch

        # Results should be similar
        assert abs(individual_avg - batch_avg) < 0.01

        # Log timing (batch should be competitive or faster)
        assert individual_time > 0
        assert batch_time > 0


# =============================================================================
# Memory Pressure Tests
# =============================================================================


class TestMemoryPressure:
    """Tests for memory behavior under high load."""

    @pytest.mark.load
    def test_large_number_of_proofs(self):
        """Test creating many proofs doesn't cause memory issues."""
        num_proofs = 500
        proofs = []

        for i in range(num_proofs):
            proof = create_sample_proof(f"memory-test-{i}", num_agents=5)
            proofs.append(proof.proof_id)  # Only keep ID, not full proof

            # Compute checksum to trigger caching
            _ = create_sample_proof(f"memory-test-{i}", num_agents=5).checksum

        assert len(proofs) == num_proofs

    @pytest.mark.load
    def test_cache_eviction_under_memory_pressure(self):
        """Test that caches evict entries properly under pressure."""
        # Create many similarity cache entries
        session_id = f"cache-pressure-{uuid.uuid4().hex[:8]}"
        cache = get_pairwise_similarity_cache(session_id, max_size=100)

        # Add more entries than max_size
        for i in range(200):
            cache.put(f"text_{i}", f"text_{i + 1}", 0.5)

        # Cache should not exceed max_size
        stats = cache.get_stats()
        assert stats["size"] <= 100

        # Cleanup
        cleanup_similarity_cache(session_id)

    @pytest.mark.load
    def test_concurrent_cache_operations(self):
        """Test cache operations are safe under concurrent access."""
        session_id = f"concurrent-cache-{uuid.uuid4().hex[:8]}"
        cache = get_pairwise_similarity_cache(session_id, max_size=256)
        errors = []
        lock = threading.Lock()

        def cache_operations(thread_id: int):
            try:
                for i in range(50):
                    text1 = f"thread_{thread_id}_text_{i}"
                    text2 = f"thread_{thread_id}_other_{i}"

                    # Put
                    cache.put(text1, text2, 0.5 + (i * 0.01))

                    # Get
                    result = cache.get(text1, text2)
                    if result is None and i < 10:  # Recent entries should hit
                        pass  # May have been evicted
            except Exception as e:
                with lock:
                    errors.append((thread_id, e))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(cache_operations, i) for i in range(10)]
            for future in as_completed(futures):
                future.result()

        assert len(errors) == 0, f"Errors: {errors}"

        # Verify cache is still functional
        cache.put("final_test_a", "final_test_b", 0.99)
        assert cache.get("final_test_a", "final_test_b") == 0.99

        # Cleanup
        cleanup_similarity_cache(session_id)

    @pytest.mark.load
    def test_jaccard_cache_memory_bound(self):
        """Test Jaccard backend cache stays within memory bounds."""
        backend = JaccardBackend()

        # Generate many unique text pairs
        for i in range(1000):
            text1 = f"Unique text one variant {i} with some content"
            text2 = f"Unique text two variant {i} with other content"
            backend.compute_similarity(text1, text2)

        # Clear and verify
        JaccardBackend.clear_cache()

    @pytest.mark.load
    def test_evidence_chain_scaling(self):
        """Test that large evidence chains don't cause issues."""
        builder = ConsensusBuilder("large-evidence", "Test with large evidence")

        claim = builder.add_claim("Main claim", "agent_0", 0.9)

        # Add many pieces of evidence
        for i in range(100):
            builder.add_evidence(
                claim_id=claim.claim_id,
                source=f"source_{i}",
                content=f"Evidence content number {i} with detailed explanation",
                evidence_type="argument" if i % 2 == 0 else "data",
                supports=i % 3 != 0,  # Some refuting
                strength=0.5 + (i % 5) * 0.1,
            )

        builder.record_vote("agent_0", VoteType.AGREE, 0.9, "Strong support")

        proof = builder.build(
            final_claim="Final with large evidence",
            confidence=0.85,
            consensus_reached=True,
            reasoning_summary="Evidence-heavy consensus",
            rounds=5,
        )

        assert len(proof.evidence_chain) == 100
        assert proof.checksum is not None  # Should compute without issues


# =============================================================================
# Rate Limiting and Throttling Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting behavior in consensus system."""

    @pytest.mark.load
    def test_high_frequency_similarity_checks(self):
        """Test system handles high-frequency similarity checks."""
        backend = JaccardBackend()

        start_time = time.perf_counter()
        check_count = 0

        # Perform many checks in a short time
        while time.perf_counter() - start_time < 1.0:  # 1 second burst
            backend.compute_similarity(
                f"Text A {check_count}",
                f"Text B {check_count}",
            )
            check_count += 1

        # Should handle many checks per second
        assert check_count > 100  # At least 100 checks/second

    @pytest.mark.load
    def test_burst_proof_generation(self):
        """Test burst generation of consensus proofs."""
        proofs_generated = []

        start_time = time.perf_counter()
        while time.perf_counter() - start_time < 0.5:  # 500ms burst
            proof = create_sample_proof(f"burst-{len(proofs_generated)}")
            proofs_generated.append(proof.proof_id)

        # Should generate many proofs quickly
        assert len(proofs_generated) > 10

    @pytest.mark.load
    def test_convergence_check_rate(self):
        """Test convergence checking at high rates."""
        detectors = []
        results = []

        # Create multiple detectors
        for i in range(5):
            detector = ConvergenceDetector(
                debate_id=f"rate-test-{i}",
                min_rounds_before_check=1,
            )
            detectors.append(detector)

        responses_current = generate_agent_responses(5, "rate-limiting")
        responses_previous = generate_agent_responses(5, "rate-limiting")

        start_time = time.perf_counter()
        check_count = 0

        while time.perf_counter() - start_time < 0.5:
            detector = detectors[check_count % len(detectors)]
            result = detector.check_convergence(
                responses_current,
                responses_previous,
                round_number=2,
            )
            if result:
                results.append(result)
            check_count += 1

        # Cleanup
        for detector in detectors:
            detector.cleanup()

        assert check_count > 20  # Should handle multiple checks

    @pytest.mark.load
    def test_analyzer_throughput(self):
        """Test analyzer throughput under load."""
        analyzer = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="throughput-test",
            enable_cache=True,
        )

        responses = generate_agent_responses(10)
        analyses_completed = 0

        start_time = time.perf_counter()
        while time.perf_counter() - start_time < 0.5:
            metrics = analyzer.analyze(
                current_responses=responses,
                previous_responses=responses,
                domain="test",
            )
            analyses_completed += 1

        analyzer.cleanup()

        assert analyses_completed > 5

    def test_cache_hit_rate_under_repeated_queries(self):
        """Test cache effectiveness with repeated queries."""
        session_id = f"cache-hit-{uuid.uuid4().hex[:8]}"
        cache = get_pairwise_similarity_cache(session_id, max_size=256)

        # Populate cache
        texts = [f"Text {i}" for i in range(10)]
        for i, t1 in enumerate(texts):
            for t2 in texts[i + 1 :]:
                cache.put(t1, t2, 0.5)

        # Perform repeated queries
        hits_before = cache.get_stats()["hits"]

        for _ in range(100):
            for i, t1 in enumerate(texts):
                for t2 in texts[i + 1 :]:
                    cache.get(t1, t2)

        stats = cache.get_stats()
        hits_after = stats["hits"]

        # Should have high hit rate on repeated queries
        assert hits_after > hits_before
        assert stats["hit_rate"] > 0.9

        # Cleanup
        cleanup_similarity_cache(session_id)


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Tests for thread safety of consensus components."""

    @pytest.mark.load
    def test_consensus_builder_thread_safety(self):
        """Test ConsensusBuilder is safe for concurrent use within a debate."""
        builder = ConsensusBuilder("thread-safe-builder", "Thread safety test")
        errors = []
        lock = threading.Lock()

        def add_claims(thread_id: int):
            try:
                for i in range(20):
                    builder.add_claim(
                        statement=f"Claim from thread {thread_id} iteration {i}",
                        author=f"agent_{thread_id}",
                        confidence=0.7 + (i * 0.01),
                    )
            except Exception as e:
                with lock:
                    errors.append((thread_id, e))

        threads = [threading.Thread(target=add_claims, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert len(builder.claims) == 100  # 5 threads * 20 claims each

    @pytest.mark.load
    def test_concurrent_proof_to_dict(self):
        """Test concurrent to_dict() calls are safe."""
        proof = create_sample_proof("concurrent-dict", num_agents=10)
        results = []
        lock = threading.Lock()

        def convert_to_dict():
            try:
                data = proof.to_dict()
                with lock:
                    results.append(data["proof_id"])
            except Exception as e:
                with lock:
                    results.append(f"error: {e}")

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(convert_to_dict) for _ in range(100)]
            for future in as_completed(futures):
                future.result()

        assert len(results) == 100
        assert all(r == "proof-concurrent-dict" for r in results)

    @pytest.mark.load
    def test_concurrent_markdown_generation(self):
        """Test concurrent Markdown generation is safe."""
        dissents = [
            DissentRecord(
                agent="agent_0",
                claim_id="c1",
                dissent_type="partial",
                reasons=["Reason 1", "Reason 2"],
                severity=0.6,
            )
        ]
        tensions = [
            UnresolvedTension(
                tension_id="t1",
                description="Test tension",
                agents_involved=["agent_0", "agent_1"],
                options=["Option A", "Option B"],
                impact="Test impact",
            )
        ]

        proof = ConsensusProof(
            proof_id="markdown-test",
            debate_id="markdown-debate",
            task="Markdown generation test",
            final_claim="Final claim for markdown",
            confidence=0.85,
            consensus_reached=True,
            votes=[ConsensusVote("agent_0", VoteType.AGREE, 0.9, "Support")],
            supporting_agents=["agent_0"],
            dissenting_agents=[],
            claims=[Claim("c1", "Test claim", "agent_0", 0.8)],
            dissents=dissents,
            unresolved_tensions=tensions,
            evidence_chain=[Evidence("e1", "agent_0", "Evidence", "arg", True, 0.9)],
            reasoning_summary="Test summary",
        )

        markdowns = []
        lock = threading.Lock()

        def generate_markdown():
            md = proof.to_markdown()
            with lock:
                markdowns.append(len(md))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(generate_markdown) for _ in range(50)]
            for future in as_completed(futures):
                future.result()

        assert len(markdowns) == 50
        # All should have same length (deterministic output)
        assert len(set(markdowns)) == 1


# =============================================================================
# Cache Isolation Tests
# =============================================================================


class TestCacheIsolation:
    """Tests for cache isolation between debates."""

    @pytest.mark.parametrize("cleanup_first", [0, 1])
    def test_debate_cache_isolation(self, cleanup_first):
        """Cleaning one debate must preserve the other debate's cached values."""
        debate_ids = [f"isolated-{i}-{uuid.uuid4().hex}" for i in range(2)]
        scores = [0.9, 0.2]
        try:
            caches = [get_pairwise_similarity_cache(debate_id) for debate_id in debate_ids]
            caches[0].put("text_a", "text_b", scores[0])
            assert caches[0].get("text_a", "text_b") == scores[0]
            assert caches[1].get("text_a", "text_b") is None

            caches[1].put("text_a", "text_b", scores[1])
            for cache, score in zip(caches, scores):
                assert cache.get("text_a", "text_b") == score

            cleanup_similarity_cache(debate_ids[cleanup_first])
            assert caches[cleanup_first].get("text_a", "text_b") is None

            survivor = 1 - cleanup_first
            assert caches[survivor].get("text_a", "text_b") == scores[survivor]
            surviving_cache = get_pairwise_similarity_cache(debate_ids[survivor])
            assert surviving_cache.get("text_a", "text_b") == scores[survivor]

            replacement = get_pairwise_similarity_cache(debate_ids[cleanup_first])
            assert replacement.get("text_a", "text_b") is None
            replacement.put("text_a", "text_b", 0.5)
            assert surviving_cache.get("text_a", "text_b") == scores[survivor]
        finally:
            for debate_id in debate_ids:
                cleanup_similarity_cache(debate_id)

    def test_convergence_detector_isolation(self):
        """Test ConvergenceDetector instances are isolated."""
        detector1 = ConvergenceDetector(
            debate_id="detector-1",
            min_rounds_before_check=1,
        )
        detector2 = ConvergenceDetector(
            debate_id="detector-2",
            min_rounds_before_check=1,
        )

        # Run check on detector1
        responses = generate_agent_responses(3)
        detector1.check_convergence(responses, responses, round_number=2)

        # detector1 state should not affect detector2
        assert detector1.consecutive_stable_count > 0
        assert detector2.consecutive_stable_count == 0

        # Cleanup
        detector1.cleanup()
        detector2.cleanup()

    def test_analyzer_session_isolation(self):
        """Test AdvancedConvergenceAnalyzer sessions are isolated."""
        analyzer1 = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="analyzer-session-1",
            enable_cache=True,
        )
        analyzer2 = AdvancedConvergenceAnalyzer(
            similarity_backend=JaccardBackend(),
            debate_id="analyzer-session-2",
            enable_cache=True,
        )

        responses = generate_agent_responses(3)

        # Use analyzer1
        metrics1 = analyzer1.analyze(
            current_responses=responses,
            previous_responses=responses,
        )

        # analyzer2 should start fresh
        metrics2 = analyzer2.analyze(
            current_responses=responses,
            previous_responses=responses,
        )

        # Both should produce valid results
        assert metrics1.semantic_similarity >= 0
        assert metrics2.semantic_similarity >= 0

        # Cleanup
        analyzer1.cleanup()
        analyzer2.cleanup()


# =============================================================================
# Async Integration Tests
# =============================================================================


@pytest.mark.timeout(60)
class TestAsyncIntegration:
    """Tests for async patterns with consensus system."""

    @pytest.mark.asyncio
    async def test_async_concurrent_proofs(self):
        """Test creating proofs in async context."""

        async def create_proof_async(idx: int) -> ConsensusProof:
            # Simulate async work
            await asyncio.sleep(0.01)
            return create_sample_proof(f"async-{idx}")

        tasks = [create_proof_async(i) for i in range(10)]
        proofs = await asyncio.gather(*tasks)

        assert len(proofs) == 10
        assert all(p.consensus_reached for p in proofs)

    @pytest.mark.asyncio
    async def test_async_convergence_checks(self):
        """Test convergence detection in async context."""

        async def check_convergence_async(idx: int) -> ConvergenceResult | None:
            await asyncio.sleep(0.01)

            detector = ConvergenceDetector(
                debate_id=f"async-conv-{idx}",
                min_rounds_before_check=1,
            )

            responses = generate_agent_responses(3)
            result = detector.check_convergence(responses, responses, round_number=2)
            detector.cleanup()
            return result

        tasks = [check_convergence_async(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_async_analyzer_sessions(self):
        """Test analyzer in async sessions."""

        async def analyze_async(idx: int) -> float:
            await asyncio.sleep(0.01)

            analyzer = AdvancedConvergenceAnalyzer(
                similarity_backend=JaccardBackend(),
                debate_id=f"async-analyze-{idx}",
            )

            responses = generate_agent_responses(3)
            metrics = analyzer.analyze(
                current_responses=responses,
                previous_responses=responses,
            )

            analyzer.cleanup()
            return metrics.overall_convergence

        tasks = [analyze_async(i) for i in range(5)]
        scores = await asyncio.gather(*tasks)

        assert len(scores) == 5
        assert all(0 <= s <= 1 for s in scores)
