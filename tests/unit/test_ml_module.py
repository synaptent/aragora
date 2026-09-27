"""
Unit Tests for Aragora ML Module.

Tests local ML capabilities including embeddings, quality scoring,
consensus prediction, agent routing, and fine-tuning.
"""

from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestMLPackageImports:
    """Test optional dependency isolation at the package boundary."""

    def test_consensus_predictor_imports_without_numpy(self):
        """Pure-Python consensus fallback must not import NumPy-only modules."""
        script = """
import importlib.abc
import sys


class BlockNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ModuleNotFoundError("numpy intentionally unavailable")
        return None


sys.meta_path.insert(0, BlockNumpy())
from aragora.ml import ConsensusPredictor

predictor = ConsensusPredictor()
assert predictor.config is not None
assert "aragora.ml.embeddings" not in sys.modules
assert "aragora.ml.agent_router" not in sys.modules
"""
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestQualityScorer:
    """Test QualityScorer functionality."""

    def test_scorer_initialization(self):
        """Test scorer initializes correctly."""
        from aragora.ml import QualityScorer, QualityScorerConfig

        scorer = QualityScorer()
        assert scorer.config is not None

        config = QualityScorerConfig(min_response_length=100)
        scorer = QualityScorer(config=config)
        assert scorer.config.min_response_length == 100

    def test_score_empty_text(self):
        """Test scoring empty text returns zero."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()
        score = scorer.score("")

        assert score.overall == 0.0
        assert score.confidence == 1.0

    def test_score_simple_text(self):
        """Test scoring simple text."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()
        text = "This is a simple response."
        score = scorer.score(text)

        assert 0.0 <= score.overall <= 1.0
        assert 0.0 <= score.coherence <= 1.0
        assert 0.0 <= score.clarity <= 1.0
        assert 0.0 <= score.completeness <= 1.0

    def test_score_high_quality_text(self):
        """Test high quality text gets higher scores."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()

        low_quality = "ok"
        high_quality = """
        This is a comprehensive response that explains the concept in detail.
        Because of this approach, we can achieve better results. Furthermore,
        the implementation follows best practices and includes proper error handling.

        Here are the key points:
        - First, we establish the foundation
        - Second, we build upon that foundation
        - Third, we validate our approach

        In conclusion, this provides a robust solution to the problem.
        """

        low_score = scorer.score(low_quality)
        high_score = scorer.score(high_quality)

        assert high_score.overall > low_score.overall

    def test_score_batch(self):
        """Test batch scoring."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()
        texts = [
            "Short response.",
            "Medium length response with some detail.",
            "This is a longer response with more comprehensive explanation and detail.",
        ]

        scores = scorer.score_batch(texts)

        assert len(scores) == 3
        for score in scores:
            assert 0.0 <= score.overall <= 1.0

    def test_score_with_context(self):
        """Test scoring with context."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()
        text = "The algorithm implements sorting."
        context = "Implement a sorting algorithm"

        score_with_context = scorer.score(text, context=context)
        score_without_context = scorer.score(text)

        assert score_with_context.relevance != score_without_context.relevance

    def test_filter_quality(self):
        """Test quality filtering."""
        from aragora.ml import get_quality_scorer

        scorer = get_quality_scorer()
        texts = [
            "ok",  # Low quality
            "This is a comprehensive response.",  # Medium quality
        ]

        # Very low threshold to ensure at least one passes
        filtered = scorer.filter_quality(texts, threshold=0.1)
        assert len(filtered) >= 1

    def test_quality_score_properties(self):
        """Test QualityScore properties."""
        from aragora.ml.quality_scorer import QualityScore

        # High quality score
        high = QualityScore(
            overall=0.8,
            coherence=0.8,
            completeness=0.8,
            relevance=0.8,
            clarity=0.8,
            confidence=0.6,
        )
        assert high.is_high_quality is True
        assert high.needs_review is False

        # Low quality score
        low = QualityScore(
            overall=0.3,
            coherence=0.3,
            completeness=0.3,
            relevance=0.3,
            clarity=0.3,
            confidence=0.2,
        )
        assert low.is_high_quality is False
        assert low.needs_review is True


class TestConsensusPredictor:
    """Test ConsensusPredictor functionality."""

    def test_predictor_initialization(self):
        """Test predictor initializes correctly."""
        from aragora.ml import ConsensusPredictor

        predictor = ConsensusPredictor()
        assert predictor.config is not None

    def test_predict_empty_responses(self):
        """Test prediction with empty responses."""
        from aragora.ml import get_consensus_predictor

        predictor = get_consensus_predictor()
        prediction = predictor.predict([])

        assert prediction.probability == 0.0
        assert prediction.confidence == 0.0

    @pytest.mark.slow
    def test_predict_agreeing_responses(self):
        """Test prediction with agreeing responses (requires real embeddings)."""
        from aragora.ml import get_consensus_predictor

        predictor = get_consensus_predictor()
        responses = [
            ("agent1", "I agree with approach A. It's the best solution."),
            ("agent2", "I concur, approach A is correct."),
            ("agent3", "Exactly right, approach A should be used."),
        ]

        prediction = predictor.predict(responses)

        assert prediction.probability > 0.5
        # Historical outcomes from other tests may affect convergence_trend
        assert prediction.convergence_trend in ("agree", "stable")

    def test_predict_disagreeing_responses(self):
        """Test prediction with disagreeing responses."""
        from aragora.ml import get_consensus_predictor

        predictor = get_consensus_predictor()
        responses = [
            ("agent1", "I disagree, approach A is wrong."),
            ("agent2", "On the contrary, approach B is better."),
            ("agent3", "However, I would argue for approach C instead."),
        ]

        prediction = predictor.predict(responses)

        # Disagreement should lower probability
        assert prediction.probability < 0.7

    def test_predict_with_round_info(self):
        """Test prediction with round information."""
        from aragora.ml import get_consensus_predictor

        predictor = get_consensus_predictor()
        responses = [
            ("agent1", "Some response"),
            ("agent2", "Another response"),
        ]

        pred_early = predictor.predict(responses, current_round=1, total_rounds=5)
        pred_late = predictor.predict(responses, current_round=5, total_rounds=5)

        # Later rounds should have higher consensus probability
        assert pred_late.probability >= pred_early.probability

    def test_consensus_prediction_properties(self):
        """Test ConsensusPrediction properties."""
        from aragora.ml.consensus_predictor import ConsensusPrediction

        # Likely consensus
        likely = ConsensusPrediction(
            probability=0.85,
            confidence=0.7,
            estimated_rounds=2,
            convergence_trend="converging",
            key_factors=["high_semantic_similarity"],
        )
        assert likely.likely_consensus is True
        assert likely.early_termination_safe is True

        # Unlikely consensus
        unlikely = ConsensusPrediction(
            probability=0.25,  # Below 0.3 threshold
            confidence=0.5,
            estimated_rounds=5,
            convergence_trend="diverging",
            key_factors=["stance_disagreement"],
        )
        assert unlikely.likely_consensus is False
        assert unlikely.needs_intervention is True

    def test_record_outcome(self):
        """Test recording outcomes for calibration."""
        from aragora.ml import get_consensus_predictor

        predictor = get_consensus_predictor()

        # Record some outcomes
        predictor.record_outcome("debate1", True)
        predictor.record_outcome("debate2", False)

        stats = predictor.get_calibration_stats()
        assert stats["samples"] >= 0


class TestAgentRouter:
    """Test AgentRouter functionality."""

    def test_router_initialization(self):
        """Test router initializes with default capabilities."""
        from aragora.ml import AgentRouter

        router = AgentRouter()
        assert len(router._capabilities) > 0
        assert "claude" in router._capabilities

    def test_route_coding_task(self):
        """Test routing a coding task."""
        from aragora.ml import get_agent_router, TaskType

        router = get_agent_router()
        decision = router.route(
            "Implement a binary search algorithm in Python",
            available_agents=["claude", "gpt-4", "codex", "gemini"],
            team_size=3,
        )

        assert decision.task_type == TaskType.CODING
        assert len(decision.selected_agents) == 3
        assert decision.confidence > 0

    def test_route_analysis_task(self):
        """Test routing an analysis task."""
        from aragora.ml import get_agent_router, TaskType

        router = get_agent_router()
        decision = router.route(
            "Analyze the pros and cons of microservices architecture",
            available_agents=["claude", "gpt-4", "gemini"],
            team_size=2,
        )

        assert decision.task_type == TaskType.ANALYSIS
        assert len(decision.selected_agents) == 2

    def test_route_creative_task(self):
        """Test routing a creative task."""
        from aragora.ml import get_agent_router, TaskType

        router = get_agent_router()
        decision = router.route(
            "Write a short story about AI",
            available_agents=["claude", "gpt-4", "grok"],
            team_size=2,
        )

        assert decision.task_type == TaskType.CREATIVE

    def test_route_math_task(self):
        """Test routing a math task."""
        from aragora.ml import get_agent_router, TaskType

        router = get_agent_router()
        decision = router.route(
            "Calculate the derivative of x^2 + 3x",
            available_agents=["claude", "gpt-4", "deepseek"],
            team_size=2,
        )

        assert decision.task_type == TaskType.MATH

    def test_route_empty_agents(self):
        """Test routing with no agents."""
        from aragora.ml import get_agent_router

        router = get_agent_router()
        decision = router.route(
            "Some task",
            available_agents=[],
            team_size=3,
        )

        assert len(decision.selected_agents) == 0
        assert decision.confidence == 0.0

    def test_route_with_constraints(self):
        """Test routing with constraints."""
        from aragora.ml import get_agent_router

        router = get_agent_router()
        decision = router.route(
            "Analyze this image",
            available_agents=["claude", "gpt-4", "llama"],
            team_size=2,
            constraints={"require_vision": True},
        )

        # Agents without vision support should be deprioritized
        assert len(decision.selected_agents) == 2

    def test_record_performance(self):
        """Test recording agent performance."""
        from aragora.ml import get_agent_router

        router = get_agent_router()

        router.record_performance("claude", "coding", success=True)
        router.record_performance("claude", "coding", success=True)
        router.record_performance("claude", "coding", success=False)

        stats = router.get_agent_stats("claude")
        assert stats["total_tasks"] >= 3

    def test_update_elo(self):
        """Test updating agent ELO."""
        from aragora.ml import get_agent_router

        router = get_agent_router()

        router.update_elo("claude", 1150.0)
        stats = router.get_agent_stats("claude")
        assert stats["elo_rating"] == 1150.0

    def test_routing_decision_serialization(self):
        """Test RoutingDecision can be serialized."""
        from aragora.ml import get_agent_router

        router = get_agent_router()
        decision = router.route(
            "Test task",
            available_agents=["claude", "gpt-4"],
            team_size=2,
        )

        data = decision.to_dict()
        assert "selected_agents" in data
        assert "task_type" in data
        assert "confidence" in data


class TestLocalEmbeddings:
    """Test LocalEmbeddingService (requires sentence-transformers)."""

    def test_embedding_model_enum(self):
        """Test EmbeddingModel enum values."""
        from aragora.ml import EmbeddingModel

        assert EmbeddingModel.MINILM.value == "all-MiniLM-L6-v2"
        assert EmbeddingModel.MPNET.value == "all-mpnet-base-v2"

    def test_service_initialization(self):
        """Test service initialization."""
        from aragora.ml import LocalEmbeddingService, LocalEmbeddingConfig

        config = LocalEmbeddingConfig(device="cpu")
        service = LocalEmbeddingService(config)
        assert service.model_name == "all-MiniLM-L6-v2"

    @pytest.mark.slow
    def test_embed_single(self):
        """Test embedding single text (requires model download)."""
        from aragora.ml import get_embedding_service

        service = get_embedding_service()
        embedding = service.embed("Hello world")

        assert isinstance(embedding, list)
        assert len(embedding) == 384  # MiniLM dimension

    @pytest.mark.slow
    def test_embed_batch(self):
        """Test batch embedding."""
        from aragora.ml import get_embedding_service

        service = get_embedding_service()
        embeddings = service.embed_batch(["Hello", "World"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 384

    @pytest.mark.slow
    def test_similarity(self):
        """Test similarity calculation."""
        from aragora.ml import get_embedding_service

        service = get_embedding_service()
        emb1 = service.embed("cat")
        emb2 = service.embed("dog")
        emb3 = service.embed("programming")

        # Cat and dog should be more similar than cat and programming
        sim_cat_dog = service.similarity(emb1, emb2)
        sim_cat_prog = service.similarity(emb1, emb3)

        assert sim_cat_dog > sim_cat_prog

    @pytest.mark.slow
    def test_search(self):
        """Test similarity search."""
        from aragora.ml import get_embedding_service

        service = get_embedding_service()
        documents = [
            "The cat sat on the mat",
            "Dogs are loyal pets",
            "Python is a programming language",
        ]

        results = service.search("pets and animals", documents, top_k=2)

        assert len(results) <= 2
        # Animal documents should be more similar than programming
        assert "Python" not in results[0].text


class TestFineTuning:
    """Test fine-tuning components."""

    def test_training_example_creation(self):
        """Test creating training examples."""
        from aragora.ml import TrainingExample

        example = TrainingExample(
            instruction="Explain sorting",
            input_text="Quick sort algorithm",
            output="Quick sort is a divide and conquer algorithm...",
        )

        assert example.instruction == "Explain sorting"
        data = example.to_dict()
        assert "instruction" in data

    def test_training_example_from_debate(self):
        """Test creating training example from debate."""
        from aragora.ml import TrainingExample

        example = TrainingExample.from_debate(
            task="Design an API",
            winning_response="Use REST with proper versioning...",
            losing_response="Just use random endpoints...",
            context="Enterprise application",
        )

        assert example.instruction == "Design an API"
        assert example.output == "Use REST with proper versioning..."
        assert example.rejected == "Just use random endpoints..."

    def test_training_data_creation(self):
        """Test creating training data."""
        from aragora.ml import TrainingData, TrainingExample

        data = TrainingData()
        data.add(
            TrainingExample(
                instruction="Test",
                output="Output",
            )
        )

        assert len(data) == 1

    def test_training_data_from_debates(self):
        """Test creating training data from debate outcomes."""
        from aragora.ml import TrainingData

        outcomes = [
            {
                "task": "Design pattern",
                "consensus": "Use factory pattern for...",
                "rejected": ["Don't use patterns"],
            },
            {
                "task": "Database choice",
                "consensus": "PostgreSQL for relational...",
            },
        ]

        data = TrainingData.from_debates(outcomes)
        assert len(data) == 2

    def test_finetune_config(self):
        """Test fine-tune configuration."""
        from aragora.ml import FineTuneConfig

        config = FineTuneConfig(
            base_model="microsoft/phi-2",
            lora_r=16,
            epochs=5,
        )

        assert config.base_model == "microsoft/phi-2"
        assert config.lora_r == 16
        assert config.epochs == 5

    def test_create_fine_tuner(self):
        """Test fine-tuner factory."""
        from aragora.ml import create_fine_tuner, LocalFineTuner

        tuner = create_fine_tuner(method="lora")
        assert isinstance(tuner, LocalFineTuner)


class TestMLModuleIntegration:
    """Integration tests for ML module components."""

    def test_quality_scorer_with_router(self):
        """Test quality scorer informing router decisions."""
        from aragora.ml import get_quality_scorer, get_agent_router

        scorer = get_quality_scorer()
        router = get_agent_router()

        # Score some hypothetical responses
        responses = [
            ("claude", "Comprehensive analysis of the problem..."),
            ("gpt-4", "Brief answer."),
        ]

        scores = {}
        for agent_id, text in responses:
            scores[agent_id] = scorer.score(text).overall

        # Use scores to inform routing
        decision = router.route(
            "Analyze a complex problem",
            available_agents=["claude", "gpt-4"],
            team_size=2,
        )

        assert len(decision.selected_agents) == 2

    def test_consensus_predictor_with_quality(self):
        """Test consensus predictor using quality scores."""
        from aragora.ml import get_consensus_predictor, get_quality_scorer

        predictor = get_consensus_predictor()
        scorer = get_quality_scorer()

        responses = [
            ("agent1", "I agree with the comprehensive approach described above."),
            ("agent2", "Building on that, I also support this methodology."),
        ]

        # Get quality scores
        for agent_id, text in responses:
            score = scorer.score(text)
            assert score.overall > 0

        # Predict consensus
        prediction = predictor.predict(responses)
        assert prediction.probability > 0.5

    def test_full_workflow(self):
        """Test complete ML workflow."""
        from aragora.ml import (
            get_agent_router,
            get_quality_scorer,
            get_consensus_predictor,
            TrainingData,
            TrainingExample,
        )

        # 1. Route task to agents
        router = get_agent_router()
        decision = router.route(
            "Implement error handling",
            available_agents=["claude", "codex", "gpt-4"],
            team_size=2,
        )
        assert len(decision.selected_agents) == 2

        # 2. Score responses (simulated)
        scorer = get_quality_scorer()
        response_text = "Implement try-catch blocks with proper logging..."
        score = scorer.score(response_text, context="error handling")
        assert score.overall > 0

        # 3. Predict consensus
        predictor = get_consensus_predictor()
        responses = [
            ("claude", "Use structured error handling..."),
            ("codex", "Implement exception classes..."),
        ]
        prediction = predictor.predict(responses)
        assert prediction.probability > 0

        # 4. Create training data
        data = TrainingData()
        data.add(
            TrainingExample(
                instruction="Implement error handling",
                output="Use structured error handling with proper logging...",
            )
        )
        assert len(data) == 1
