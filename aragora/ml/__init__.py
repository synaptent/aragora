"""
Machine Learning Module for Aragora.

Provides local ML capabilities:
- Local embedding models (sentence-transformers)
- Quality scoring
- Consensus prediction
- Agent routing
- Local fine-tuning (PEFT/LoRA)

These models run locally without external API dependencies.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.ml.agent_router import AgentRouter, RoutingDecision, TaskType, get_agent_router
    from aragora.ml.consensus_predictor import (
        ConsensusPrediction,
        ConsensusPredictor,
        get_consensus_predictor,
    )
    from aragora.ml.degradation import (
        DegradationLevel,
        MLDegradationManager,
        MLFeature,
        MLFallbackService,
        force_degradation,
        get_ml_fallback,
        get_ml_manager,
        heuristic_consensus_prediction,
        heuristic_quality_score,
        heuristic_similarity,
        reset_degradation,
    )
    from aragora.ml.embeddings import (
        EmbeddingModel,
        LocalEmbeddingConfig,
        LocalEmbeddingService,
        get_embedding_service,
    )
    from aragora.ml.local_finetuning import (
        DPOFineTuner,
        FineTuneConfig,
        FineTuneResult,
        LocalFineTuner,
        TrainingData,
        TrainingExample,
        create_fine_tuner,
    )
    from aragora.ml.quality_scorer import (
        QualityScore,
        QualityScorer,
        QualityScorerConfig,
        get_quality_scorer,
    )


_EXPORTS = {
    "LocalEmbeddingService": ("aragora.ml.embeddings", "LocalEmbeddingService"),
    "LocalEmbeddingConfig": ("aragora.ml.embeddings", "LocalEmbeddingConfig"),
    "EmbeddingModel": ("aragora.ml.embeddings", "EmbeddingModel"),
    "get_embedding_service": ("aragora.ml.embeddings", "get_embedding_service"),
    "QualityScorer": ("aragora.ml.quality_scorer", "QualityScorer"),
    "QualityScorerConfig": ("aragora.ml.quality_scorer", "QualityScorerConfig"),
    "QualityScore": ("aragora.ml.quality_scorer", "QualityScore"),
    "get_quality_scorer": ("aragora.ml.quality_scorer", "get_quality_scorer"),
    "ConsensusPredictor": ("aragora.ml.consensus_predictor", "ConsensusPredictor"),
    "ConsensusPrediction": ("aragora.ml.consensus_predictor", "ConsensusPrediction"),
    "get_consensus_predictor": (
        "aragora.ml.consensus_predictor",
        "get_consensus_predictor",
    ),
    "AgentRouter": ("aragora.ml.agent_router", "AgentRouter"),
    "RoutingDecision": ("aragora.ml.agent_router", "RoutingDecision"),
    "TaskType": ("aragora.ml.agent_router", "TaskType"),
    "get_agent_router": ("aragora.ml.agent_router", "get_agent_router"),
    "LocalFineTuner": ("aragora.ml.local_finetuning", "LocalFineTuner"),
    "DPOFineTuner": ("aragora.ml.local_finetuning", "DPOFineTuner"),
    "FineTuneConfig": ("aragora.ml.local_finetuning", "FineTuneConfig"),
    "FineTuneResult": ("aragora.ml.local_finetuning", "FineTuneResult"),
    "TrainingData": ("aragora.ml.local_finetuning", "TrainingData"),
    "TrainingExample": ("aragora.ml.local_finetuning", "TrainingExample"),
    "create_fine_tuner": ("aragora.ml.local_finetuning", "create_fine_tuner"),
    "MLFeature": ("aragora.ml.degradation", "MLFeature"),
    "DegradationLevel": ("aragora.ml.degradation", "DegradationLevel"),
    "MLDegradationManager": ("aragora.ml.degradation", "MLDegradationManager"),
    "MLFallbackService": ("aragora.ml.degradation", "MLFallbackService"),
    "get_ml_manager": ("aragora.ml.degradation", "get_ml_manager"),
    "get_ml_fallback": ("aragora.ml.degradation", "get_ml_fallback"),
    "force_degradation": ("aragora.ml.degradation", "force_degradation"),
    "reset_degradation": ("aragora.ml.degradation", "reset_degradation"),
    "heuristic_similarity": ("aragora.ml.degradation", "heuristic_similarity"),
    "heuristic_consensus_prediction": (
        "aragora.ml.degradation",
        "heuristic_consensus_prediction",
    ),
    "heuristic_quality_score": ("aragora.ml.degradation", "heuristic_quality_score"),
}

__all__ = [
    # Embeddings
    "LocalEmbeddingService",
    "LocalEmbeddingConfig",
    "EmbeddingModel",
    "get_embedding_service",
    # Quality Scoring
    "QualityScorer",
    "QualityScorerConfig",
    "QualityScore",
    "get_quality_scorer",
    # Consensus Prediction
    "ConsensusPredictor",
    "ConsensusPrediction",
    "get_consensus_predictor",
    # Agent Routing
    "AgentRouter",
    "RoutingDecision",
    "TaskType",
    "get_agent_router",
    # Fine-tuning
    "LocalFineTuner",
    "DPOFineTuner",
    "FineTuneConfig",
    "FineTuneResult",
    "TrainingData",
    "TrainingExample",
    "create_fine_tuner",
    # Degradation
    "MLFeature",
    "DegradationLevel",
    "MLDegradationManager",
    "MLFallbackService",
    "get_ml_manager",
    "get_ml_fallback",
    "force_degradation",
    "reset_degradation",
    "heuristic_similarity",
    "heuristic_consensus_prediction",
    "heuristic_quality_score",
]


def __getattr__(name: str) -> Any:
    """Load public ML features only when the caller requests them."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public exports to introspection tools."""
    return sorted(set(globals()) | set(__all__))
