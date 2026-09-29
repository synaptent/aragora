"""
ML (Machine Learning) endpoint handlers.

Stability: STABLE

Exposes ML capabilities via REST API for:
- Agent routing recommendations
- Response quality scoring
- Consensus prediction
- Training data export

Endpoints:
- POST /api/ml/route - Get ML-based agent routing for a task
- POST /api/ml/score - Score response quality
- POST /api/ml/score-batch - Score multiple responses
- POST /api/ml/consensus - Predict consensus likelihood
- POST /api/ml/export-training - Export debate data for training
- GET /api/ml/models - List available ML models/capabilities
- GET /api/ml/stats - Get ML module statistics

Features:
- Circuit breaker pattern for resilient ML component access
- Rate limiting (60 requests/minute for compute-intensive operations)
- RBAC permission checks (ml:read, ml:train)
- Input validation with size limits
- Comprehensive error handling with safe error messages
"""

from __future__ import annotations

__all__ = [
    "MLHandler",
    "MLCircuitBreaker",
    "get_ml_circuit_breaker_status",
    "_clear_ml_components",
]

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..utils.decorators import has_permission, require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for ML endpoints (60 requests per minute - computationally intensive)
_ml_limiter = RateLimiter(requests_per_minute=60)


# =============================================================================
# Circuit Breaker for ML Components
# =============================================================================


from aragora.resilience.simple_circuit_breaker import SimpleCircuitBreaker as MLCircuitBreaker


# Per-component circuit breakers
_ml_circuit_breakers: dict[str, MLCircuitBreaker] = {}
_circuit_breaker_lock = threading.Lock()


def _get_circuit_breaker(component: str) -> MLCircuitBreaker:
    """Get or create a circuit breaker for an ML component."""
    with _circuit_breaker_lock:
        if component not in _ml_circuit_breakers:
            _ml_circuit_breakers[component] = MLCircuitBreaker()
        return _ml_circuit_breakers[component]


# Lazy load ML components with thread safety
_ml_components: dict[str, Any] = {}
_ml_components_lock = threading.Lock()


def _get_ml_component(name: str) -> Any:
    """Lazy load ML components with circuit breaker protection.

    Args:
        name: Component name (router, scorer, predictor, embeddings, exporter)

    Returns:
        The component instance, or None if unavailable or circuit is open
    """
    # Check circuit breaker first
    circuit_breaker = _get_circuit_breaker(name)
    if not circuit_breaker.can_proceed():
        logger.debug("ML component %s circuit breaker is open, skipping", name)
        return None

    with _ml_components_lock:
        if name not in _ml_components:
            try:
                if name == "router":
                    from aragora.ml import get_agent_router

                    _ml_components[name] = get_agent_router()
                elif name == "scorer":
                    from aragora.ml import get_quality_scorer

                    _ml_components[name] = get_quality_scorer()
                elif name == "predictor":
                    from aragora.ml import get_consensus_predictor

                    _ml_components[name] = get_consensus_predictor()
                elif name == "embeddings":
                    from aragora.ml import get_embedding_service

                    _ml_components[name] = get_embedding_service()
                elif name == "exporter":
                    from aragora.debate.ml_integration import get_training_exporter

                    _ml_components[name] = get_training_exporter()
                else:
                    _ml_components[name] = None

                # Record success if component loaded
                if _ml_components.get(name) is not None:
                    circuit_breaker.record_success()
            except ImportError as e:
                logger.warning("ML component %s not available: %s", name, e)
                _ml_components[name] = None
                circuit_breaker.record_failure()
            except (RuntimeError, OSError, TypeError, ValueError, AttributeError) as e:
                logger.error("Error loading ML component %s: %s", name, e)
                _ml_components[name] = None
                circuit_breaker.record_failure()

        return _ml_components.get(name)


def _clear_ml_components() -> None:
    """Clear cached ML components (useful for testing)."""
    with _ml_components_lock:
        _ml_components.clear()
    with _circuit_breaker_lock:
        _ml_circuit_breakers.clear()


def get_ml_circuit_breaker_status() -> dict[str, Any]:
    """Get status of all ML component circuit breakers."""
    with _circuit_breaker_lock:
        return {name: cb.get_status() for name, cb in _ml_circuit_breakers.items()}


class MLHandler(BaseHandler):
    """Handler for ML endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/ml/route",
        "/api/v1/ml/score",
        "/api/v1/ml/score-batch",
        "/api/v1/ml/consensus",
        "/api/v1/ml/export-training",
        "/api/v1/ml/models",
        "/api/v1/ml/stats",
        "/api/v1/ml/embed",
        "/api/v1/ml/search",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("ml:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _ml_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for ML endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/ml/models":
            return self._handle_list_models()
        elif path == "/api/v1/ml/stats":
            return self._handle_stats()

        return None

    @require_permission("ml:read")
    @handle_errors("ML POST request")
    def handle_post(
        self,
        path: str,
        data: dict,
        handler: Any = None,
        user: Any = None,
    ) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _ml_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for ML endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/ml/export-training":
            required_permission = "ml:train"
            if not user or not has_permission(
                user.role if hasattr(user, "role") else None, required_permission
            ):
                return error_response("Permission denied", 403)
            return self._handle_export_training(data)
        if path == "/api/v1/ml/route":
            return self._handle_route(data)
        elif path == "/api/v1/ml/score":
            return self._handle_score(data)
        elif path == "/api/v1/ml/score-batch":
            return self._handle_score_batch(data)
        elif path == "/api/v1/ml/consensus":
            return self._handle_consensus(data)
        elif path == "/api/v1/ml/embed":
            return self._handle_embed(data)
        elif path == "/api/v1/ml/search":
            return self._handle_search(data)

        return None

    def _handle_route(self, data: dict) -> HandlerResult:
        """Handle ML-based agent routing.

        Request body:
            {
                "task": "Implement a caching layer",
                "available_agents": ["claude", "gpt-4", "codex"],
                "team_size": 3,
                "constraints": {"require_code": true}
            }

        Response:
            {
                "selected_agents": ["codex", "claude", "gpt-4"],
                "task_type": "coding",
                "confidence": 0.85,
                "reasoning": ["task_type=coding", "codex_strong_at_coding"],
                "agent_scores": {"codex": 0.9, "claude": 0.85, ...}
            }
        """
        router = _get_ml_component("router")
        if not router:
            return error_response("ML router not available", 503)

        task = data.get("task", "")
        if not task:
            return error_response("task is required", 400)

        available_agents = data.get("available_agents", [])
        if not available_agents:
            return error_response("available_agents is required", 400)

        team_size = data.get("team_size", 3)
        constraints = data.get("constraints", {})

        try:
            decision = router.route(
                task=task,
                available_agents=available_agents,
                team_size=team_size,
                constraints=constraints,
            )

            return json_response(
                {
                    "selected_agents": decision.selected_agents,
                    "task_type": decision.task_type.value,
                    "confidence": round(decision.confidence, 3),
                    "reasoning": decision.reasoning,
                    "agent_scores": {k: round(v, 3) for k, v in decision.agent_scores.items()},
                    "diversity_score": round(decision.diversity_score, 3),
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML routing request: %s", e)
            return error_response(safe_error_message(e, "routing"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML routing error: %s", e)
            return error_response(safe_error_message(e, "routing"), 500)

    def _handle_score(self, data: dict) -> HandlerResult:
        """Handle single response quality scoring.

        Request body:
            {
                "text": "The response text to score",
                "context": "Optional task context"
            }

        Response:
            {
                "overall": 0.75,
                "coherence": 0.8,
                "completeness": 0.7,
                "relevance": 0.75,
                "clarity": 0.78,
                "confidence": 0.6,
                "is_high_quality": true,
                "needs_review": false
            }
        """
        scorer = _get_ml_component("scorer")
        if not scorer:
            return error_response("ML scorer not available", 503)

        text = data.get("text", "")
        if not text:
            return error_response("text is required", 400)

        context = data.get("context")

        try:
            score = scorer.score(text, context=context)

            return json_response(
                {
                    "overall": round(score.overall, 3),
                    "coherence": round(score.coherence, 3),
                    "completeness": round(score.completeness, 3),
                    "relevance": round(score.relevance, 3),
                    "clarity": round(score.clarity, 3),
                    "confidence": round(score.confidence, 3),
                    "is_high_quality": score.is_high_quality,
                    "needs_review": score.needs_review,
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML scoring request: %s", e)
            return error_response(safe_error_message(e, "scoring"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML scoring error: %s", e)
            return error_response(safe_error_message(e, "scoring"), 500)

    def _handle_score_batch(self, data: dict) -> HandlerResult:
        """Handle batch response quality scoring.

        Request body:
            {
                "texts": ["response1", "response2", ...],
                "contexts": ["context1", "context2", ...]  // optional
            }

        Response:
            {
                "scores": [
                    {"overall": 0.75, "confidence": 0.6, ...},
                    {"overall": 0.82, "confidence": 0.7, ...}
                ]
            }
        """
        scorer = _get_ml_component("scorer")
        if not scorer:
            return error_response("ML scorer not available", 503)

        texts = data.get("texts", [])
        if not texts:
            return error_response("texts is required", 400)

        if len(texts) > 100:
            return error_response("Maximum 100 texts per batch", 400)

        contexts = data.get("contexts")

        try:
            scores = scorer.score_batch(texts, contexts=contexts)

            return json_response(
                {
                    "scores": [
                        {
                            "overall": round(s.overall, 3),
                            "coherence": round(s.coherence, 3),
                            "completeness": round(s.completeness, 3),
                            "relevance": round(s.relevance, 3),
                            "clarity": round(s.clarity, 3),
                            "confidence": round(s.confidence, 3),
                            "is_high_quality": s.is_high_quality,
                        }
                        for s in scores
                    ]
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML batch scoring request: %s", e)
            return error_response(safe_error_message(e, "batch scoring"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML batch scoring error: %s", e)
            return error_response(safe_error_message(e, "batch scoring"), 500)

    def _handle_consensus(self, data: dict) -> HandlerResult:
        """Handle consensus prediction.

        Request body:
            {
                "responses": [
                    ["agent1", "I agree with approach A"],
                    ["agent2", "I also support approach A"]
                ],
                "context": "Design a caching layer",
                "current_round": 2,
                "total_rounds": 3
            }

        Response:
            {
                "probability": 0.85,
                "confidence": 0.7,
                "convergence_trend": "converging",
                "estimated_rounds": 2,
                "likely_consensus": true,
                "early_termination_safe": true,
                "key_factors": ["high_semantic_similarity", "stance_agreement"]
            }
        """
        predictor = _get_ml_component("predictor")
        if not predictor:
            return error_response("ML predictor not available", 503)

        responses = data.get("responses", [])
        if not responses:
            return error_response("responses is required", 400)

        # Convert to expected format
        response_tuples = [tuple(r) for r in responses]

        context = data.get("context")
        current_round = data.get("current_round", 1)
        total_rounds = data.get("total_rounds", 3)

        try:
            prediction = predictor.predict(
                responses=response_tuples,
                context=context,
                current_round=current_round,
                total_rounds=total_rounds,
            )

            return json_response(
                {
                    "probability": round(prediction.probability, 3),
                    "confidence": round(prediction.confidence, 3),
                    "convergence_trend": prediction.convergence_trend,
                    "estimated_rounds": prediction.estimated_rounds,
                    "likely_consensus": prediction.likely_consensus,
                    "early_termination_safe": prediction.early_termination_safe,
                    "needs_intervention": prediction.needs_intervention,
                    "key_factors": prediction.key_factors,
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML consensus prediction request: %s", e)
            return error_response(safe_error_message(e, "prediction"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML consensus prediction error: %s", e)
            return error_response(safe_error_message(e, "prediction"), 500)

    def _handle_export_training(self, data: dict) -> HandlerResult:
        """Handle training data export.

        Request body:
            {
                "debates": [
                    {
                        "task": "Design a rate limiter",
                        "consensus": "Use token bucket algorithm...",
                        "rejected": ["Use simple counter..."],
                        "context": "High-traffic API"
                    }
                ],
                "format": "jsonl"  // optional, default jsonl
            }

        Response:
            {
                "examples": 5,
                "data": "jsonl string or list of dicts"
            }
        """
        exporter = _get_ml_component("exporter")
        if not exporter:
            return error_response("ML exporter not available", 503)

        debates = data.get("debates", [])
        if not debates:
            return error_response("debates is required", 400)

        output_format = data.get("format", "json")

        try:
            training_data = exporter.export_debates_batch(debates)
            if not training_data:
                return error_response("Failed to export training data", 500)

            if output_format == "jsonl":
                # Return as JSONL string
                lines = [str(ex.to_dict()) for ex in training_data.examples]
                return json_response(
                    {
                        "examples": len(training_data),
                        "format": "jsonl",
                        "data": "\n".join(lines),
                    }
                )
            else:
                # Return as JSON array
                return json_response(
                    {
                        "examples": len(training_data),
                        "format": "json",
                        "data": [ex.to_dict() for ex in training_data.examples],
                    }
                )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML export request: %s", e)
            return error_response(safe_error_message(e, "export"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML export error: %s", e)
            return error_response(safe_error_message(e, "export"), 500)

    def _handle_embed(self, data: dict) -> HandlerResult:
        """Handle text embedding.

        Request body:
            {
                "text": "Text to embed",
                // OR
                "texts": ["text1", "text2", ...]
            }

        Response:
            {
                "embeddings": [[0.1, 0.2, ...], ...],
                "dimension": 384
            }
        """
        embeddings = _get_ml_component("embeddings")
        if not embeddings:
            return error_response("ML embeddings not available", 503)

        text = data.get("text")
        texts = data.get("texts", [])

        if not text and not texts:
            return error_response("text or texts is required", 400)

        try:
            if text:
                result = [embeddings.embed(text)]
            else:
                if len(texts) > 100:
                    return error_response("Maximum 100 texts per batch", 400)
                result = embeddings.embed_batch(texts)

            return json_response(
                {
                    "embeddings": result,
                    "dimension": len(result[0]) if result else 0,
                    "count": len(result),
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML embedding request: %s", e)
            return error_response(safe_error_message(e, "embedding"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML embedding error: %s", e)
            return error_response(safe_error_message(e, "embedding"), 500)

    def _handle_search(self, data: dict) -> HandlerResult:
        """Handle semantic search.

        Request body:
            {
                "query": "Search query",
                "documents": ["doc1", "doc2", ...],
                "top_k": 5,
                "threshold": 0.5
            }

        Response:
            {
                "results": [
                    {"text": "doc1", "score": 0.95, "index": 0},
                    ...
                ]
            }
        """
        embeddings = _get_ml_component("embeddings")
        if not embeddings:
            return error_response("ML embeddings not available", 503)

        query = data.get("query", "")
        documents = data.get("documents", [])

        if not query:
            return error_response("query is required", 400)
        if not documents:
            return error_response("documents is required", 400)
        if len(documents) > 1000:
            return error_response("Maximum 1000 documents", 400)

        top_k = data.get("top_k", 5)
        threshold = data.get("threshold", 0.0)

        try:
            results = embeddings.search(
                query=query,
                documents=documents,
                top_k=top_k,
                threshold=threshold,
            )

            return json_response(
                {
                    "results": [
                        {
                            "text": r.text,
                            "score": round(r.score, 4),
                            "index": r.index,
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid ML search request: %s", e)
            return error_response(safe_error_message(e, "search"), 400)
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected ML search error: %s", e)
            return error_response(safe_error_message(e, "search"), 500)

    def _handle_list_models(self) -> HandlerResult:
        """List available ML models and capabilities."""
        capabilities = {
            "routing": _get_ml_component("router") is not None,
            "scoring": _get_ml_component("scorer") is not None,
            "consensus": _get_ml_component("predictor") is not None,
            "embeddings": _get_ml_component("embeddings") is not None,
            "training_export": _get_ml_component("exporter") is not None,
        }

        models = {}

        # Check embedding models
        embeddings = _get_ml_component("embeddings")
        if embeddings:
            models["embeddings"] = {
                "model": embeddings.model_name,
                "dimension": (
                    embeddings.dimension
                    if hasattr(embeddings, "_dimension") and embeddings._dimension
                    else "lazy"
                ),
            }

        # Check router capabilities
        router = _get_ml_component("router")
        if router:
            models["routing"] = {
                "registered_agents": len(router._capabilities),
                "task_types": [
                    "coding",
                    "analysis",
                    "creative",
                    "reasoning",
                    "research",
                    "math",
                    "general",
                ],
            }

        return json_response(
            {
                "capabilities": capabilities,
                "models": models,
                "version": "1.0.0",
            }
        )

    def _handle_stats(self) -> HandlerResult:
        """Get ML module statistics including circuit breaker status."""
        stats: dict[str, Any] = {}

        # Router stats
        router = _get_ml_component("router")
        if router:
            stats["routing"] = {
                "registered_agents": len(router._capabilities),
                "historical_records": sum(
                    len(v)
                    for agent_history in router._historical_performance.values()
                    for v in agent_history.values()
                ),
            }

        # Predictor calibration stats
        predictor = _get_ml_component("predictor")
        if predictor:
            calibration = predictor.get_calibration_stats()
            stats["consensus"] = {
                "calibration_samples": calibration.get("samples", 0),
                "accuracy": round(calibration.get("accuracy", 0), 3),
                "precision": round(calibration.get("precision", 0), 3),
                "recall": round(calibration.get("recall", 0), 3),
            }

        # Circuit breaker status
        circuit_breaker_status = get_ml_circuit_breaker_status()

        return json_response(
            {
                "stats": stats,
                "circuit_breakers": circuit_breaker_status,
                "status": "healthy" if stats else "limited",
            }
        )
