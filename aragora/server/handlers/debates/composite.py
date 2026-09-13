"""
Composite API handlers that aggregate data from multiple subsystems.

Stability: STABLE

These handlers provide convenient single-request access to related data
that would otherwise require multiple API calls.

Endpoints:
- GET /api/v1/debates/{id}/full-context - Memory + Knowledge + Belief context
- GET /api/v1/agents/{id}/reliability - Circuit breaker + Airlock metrics
- GET /api/v1/debates/{id}/compression-analysis - RLM compression metrics

Features:
- Circuit breaker pattern for resilient subsystem access
- Rate limiting (60 requests/minute)
- RBAC permission checks (composite:read)
- Input validation with safe ID patterns
- Error isolation (subsystem failures don't crash the whole response)
"""

from __future__ import annotations

__all__ = [
    "CompositeHandler",
    "CompositeCircuitBreaker",
    "get_circuit_breaker_status",
    "_clear_cached_components",
]

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.validation import SAFE_ID_PATTERN, validate_path_segment
from ..base import BaseHandler, HandlerResult
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for composite endpoints (60 requests per minute)
_composite_limiter = RateLimiter(requests_per_minute=60)


# =============================================================================
# Circuit Breaker for Subsystem Access
# =============================================================================

from aragora.resilience.simple_circuit_breaker import (
    SimpleCircuitBreaker as CompositeCircuitBreaker,
)


# Per-subsystem circuit breakers
_circuit_breakers: dict[str, CompositeCircuitBreaker] = {}
_circuit_breaker_lock = threading.Lock()


def _get_circuit_breaker(subsystem: str) -> CompositeCircuitBreaker:
    """Get or create a circuit breaker for a subsystem."""
    with _circuit_breaker_lock:
        if subsystem not in _circuit_breakers:
            _circuit_breakers[subsystem] = CompositeCircuitBreaker(
                name=subsystem, failure_threshold=3, half_open_max_calls=2
            )
        return _circuit_breakers[subsystem]


def get_circuit_breaker_status() -> dict[str, Any]:
    """Get status of all subsystem circuit breakers."""
    with _circuit_breaker_lock:
        return {name: cb.get_status() for name, cb in _circuit_breakers.items()}


def _clear_cached_components() -> None:
    """Clear cached components and circuit breakers (useful for testing)."""
    with _circuit_breaker_lock:
        _circuit_breakers.clear()


class CompositeHandler(BaseHandler):
    """
    Handler for composite API endpoints that aggregate multiple data sources.

    Stability: STABLE

    Endpoints:
    - GET /api/v1/debates/{id}/full-context - Memory + Knowledge + Belief context
    - GET /api/v1/agents/{id}/reliability - Circuit breaker + Airlock metrics
    - GET /api/v1/debates/{id}/compression-analysis - RLM compression metrics

    All endpoints require the 'composite:read' permission and are rate-limited
    to 60 requests per minute.
    """

    ROUTES = [
        "/api/v1/debates/*/full-context",
        "/api/v1/agents/*/reliability",
        "/api/v1/debates/*/compression-analysis",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        # Match /api/v1/debates/{id}/full-context
        if path.startswith("/api/v1/debates/") and path.endswith("/full-context"):
            return True
        # Match /api/v1/agents/{id}/reliability
        if path.startswith("/api/v1/agents/") and path.endswith("/reliability"):
            return True
        # Match /api/v1/debates/{id}/compression-analysis
        if path.startswith("/api/v1/debates/") and path.endswith("/compression-analysis"):
            return True
        return False

    @require_permission("composite:read")
    def handle(self, path: str, query_params: dict[str, str], handler: Any) -> HandlerResult | None:
        """Route to appropriate handler method with rate limiting and validation."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _composite_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for composite endpoint: %s", client_ip)
            return self._error_response("Rate limit exceeded. Please try again later.", 429)

        if path.endswith("/full-context"):
            debate_id = self._extract_id(path, "/api/v1/debates/", "/full-context")
            # Validate debate ID
            is_valid, error_msg = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
            if not is_valid:
                return self._error_response(error_msg, 400)
            return self._handle_full_context(debate_id, query_params)

        elif path.endswith("/reliability"):
            agent_id = self._extract_id(path, "/api/v1/agents/", "/reliability")
            # Validate agent ID
            is_valid, error_msg = validate_path_segment(agent_id, "agent_id", SAFE_ID_PATTERN)
            if not is_valid:
                return self._error_response(error_msg, 400)
            return self._handle_reliability(agent_id, query_params)

        elif path.endswith("/compression-analysis"):
            debate_id = self._extract_id(path, "/api/v1/debates/", "/compression-analysis")
            # Validate debate ID
            is_valid, error_msg = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
            if not is_valid:
                return self._error_response(error_msg, 400)
            return self._handle_compression_analysis(debate_id, query_params)

        return None

    def _extract_id(self, path: str, prefix: str, suffix: str) -> str:
        """Extract ID from path pattern."""
        return path[len(prefix) : -len(suffix)]

    def _handle_full_context(self, debate_id: str, query_params: dict[str, str]) -> HandlerResult:
        """
        Get full context for a debate including memory, knowledge, and belief data.

        Returns aggregated data from:
        - Continuum memory (debate outcomes, patterns)
        - Knowledge mound (related facts, concepts)
        - Belief network (cruxes, positions, confidence)
        """
        try:
            context: dict[str, Any] = {
                "debate_id": debate_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "memory": {},
                "knowledge": {},
                "belief": {},
            }

            # Fetch memory context with circuit breaker protection
            context["memory"] = self._fetch_with_circuit_breaker(
                "memory",
                lambda: self._get_memory_context(debate_id),
                {"available": False, "error": "Memory subsystem unavailable"},
            )

            # Fetch knowledge context with circuit breaker protection
            context["knowledge"] = self._fetch_with_circuit_breaker(
                "knowledge",
                lambda: self._get_knowledge_context(debate_id),
                {"available": False, "error": "Knowledge subsystem unavailable"},
            )

            # Fetch belief context with circuit breaker protection
            context["belief"] = self._fetch_with_circuit_breaker(
                "belief",
                lambda: self._get_belief_context(debate_id),
                {"available": False, "error": "Belief subsystem unavailable"},
            )

            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(context).encode(),
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error in full-context handler: %s", e)
            return self._error_response("Invalid data", 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error in full-context handler: %s", e)
            return self._error_response("Internal server error", 500)

    def _handle_reliability(self, agent_id: str, query_params: dict[str, str]) -> HandlerResult:
        """
        Get reliability metrics for an agent.

        Returns aggregated data from:
        - Circuit breaker state and history
        - Airlock proxy metrics
        - Recent error rates
        - Availability score
        """
        try:
            metrics: dict[str, Any] = {
                "agent_id": agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "circuit_breaker": {},
                "airlock": {},
                "availability": {},
                "overall_score": 0.0,
            }

            # Fetch circuit breaker state with circuit breaker protection
            metrics["circuit_breaker"] = self._fetch_with_circuit_breaker(
                "resilience",
                lambda: self._get_circuit_breaker_state(agent_id),
                {"available": False, "error": "Resilience subsystem unavailable"},
            )

            # Fetch airlock metrics with circuit breaker protection
            metrics["airlock"] = self._fetch_with_circuit_breaker(
                "airlock",
                lambda: self._get_airlock_metrics(agent_id),
                {"available": False, "error": "Airlock subsystem unavailable"},
            )

            # Calculate availability with circuit breaker protection
            metrics["availability"] = self._fetch_with_circuit_breaker(
                "availability",
                lambda: self._calculate_availability(agent_id),
                {"available": False, "error": "Availability calculation failed"},
            )

            # Calculate overall reliability score
            metrics["overall_score"] = self._calculate_reliability_score(metrics)

            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(metrics).encode(),
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error in reliability handler: %s", e)
            return self._error_response("Invalid data", 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error in reliability handler: %s", e)
            return self._error_response("Internal server error", 500)

    def _handle_compression_analysis(
        self, debate_id: str, query_params: dict[str, str]
    ) -> HandlerResult:
        """
        Get RLM compression analysis for a debate.

        Returns:
        - Compression ratios per round
        - Token savings
        - Quality metrics
        - Recommendations
        """
        try:
            analysis: dict[str, Any] = {
                "debate_id": debate_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "compression": {
                    "enabled": False,
                    "rounds_compressed": 0,
                    "original_tokens": 0,
                    "compressed_tokens": 0,
                    "ratio": 0.0,
                    "savings_percent": 0.0,
                },
                "quality": {
                    "information_retained": 0.0,
                    "coherence_score": 0.0,
                },
                "recommendations": [],
            }

            # Try to get RLM metrics with circuit breaker protection
            rlm_data = self._fetch_with_circuit_breaker(
                "rlm",
                lambda: self._get_rlm_metrics(debate_id),
                None,
            )

            if rlm_data:
                analysis["compression"].update(rlm_data.get("compression", {}))
                analysis["quality"].update(rlm_data.get("quality", {}))
                analysis["compression"]["enabled"] = True

            # Generate recommendations
            analysis["recommendations"] = self._generate_compression_recommendations(analysis)

            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(analysis).encode(),
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error in compression-analysis handler: %s", e)
            return self._error_response("Invalid data", 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error in compression-analysis handler: %s", e)
            return self._error_response("Internal server error", 500)

    # ==========================================================================
    # Circuit Breaker Protected Data Fetching
    # ==========================================================================

    def _fetch_with_circuit_breaker(
        self,
        subsystem: str,
        fetch_func: Any,
        fallback_value: Any,
    ) -> Any:
        """Fetch data with circuit breaker protection.

        Args:
            subsystem: Name of the subsystem (for circuit breaker tracking)
            fetch_func: Function to call to fetch data
            fallback_value: Value to return if circuit is open or fetch fails

        Returns:
            Fetched data or fallback value
        """
        circuit_breaker = _get_circuit_breaker(subsystem)

        if not circuit_breaker.can_proceed():
            logger.debug("Circuit breaker open for %s, returning fallback", subsystem)
            return fallback_value

        try:
            result = fetch_func()
            circuit_breaker.record_success()
            return result
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("Data error fetching %s: %s", subsystem, e)
            circuit_breaker.record_failure()
            if fallback_value is not None:
                fallback = (
                    fallback_value.copy() if isinstance(fallback_value, dict) else fallback_value
                )
                if isinstance(fallback, dict):
                    fallback["error"] = "Data unavailable"
                return fallback
            return fallback_value
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error fetching %s: %s", subsystem, e)
            circuit_breaker.record_failure()
            if fallback_value is not None:
                fallback = (
                    fallback_value.copy() if isinstance(fallback_value, dict) else fallback_value
                )
                if isinstance(fallback, dict):
                    fallback["error"] = "Internal error"
                return fallback
            return fallback_value

    # ==========================================================================
    # Data fetching helpers
    # ==========================================================================

    def _get_memory_context(self, debate_id: str) -> dict[str, Any]:
        """Fetch memory context for a debate."""
        # Try to get from continuum memory
        memory_data: dict[str, Any] = {
            "available": False,
            "outcomes": [],
            "patterns": [],
            "related_debates": [],
        }

        try:
            from aragora.memory.continuum import ContinuumMemory

            # Check if continuum memory is available in context
            continuum = self.ctx.get("continuum_memory")
            if continuum and isinstance(continuum, ContinuumMemory):
                # Get related memories; recall() added dynamically via plugin
                memories = continuum.recall(debate_id, limit=5)
                memory_data["outcomes"] = [m.to_dict() for m in memories]
                memory_data["available"] = True
        except ImportError:
            pass

        return memory_data

    def _get_knowledge_context(self, debate_id: str) -> dict[str, Any]:
        """Fetch knowledge context for a debate."""
        knowledge_data: dict[str, Any] = {
            "available": False,
            "facts": [],
            "concepts": [],
            "sources": [],
        }

        try:
            # Check for knowledge mound in context
            knowledge_mound = self.ctx.get("knowledge_mound")
            if knowledge_mound:
                # Get related knowledge items; query() on untyped ctx object
                items = knowledge_mound.query(debate_id, limit=10)
                knowledge_data["facts"] = items
                knowledge_data["available"] = True
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Expected error fetching knowledge context: %s", e)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning("Unexpected error fetching knowledge context: %s", e)

        return knowledge_data

    def _get_belief_context(self, debate_id: str) -> dict[str, Any]:
        """Fetch belief network context for a debate."""
        belief_data: dict[str, Any] = {
            "available": False,
            "cruxes": [],
            "positions": [],
            "confidence_distribution": {},
        }

        try:
            # Check for belief-related stores
            dissent_retriever = self.ctx.get("dissent_retriever")
            if dissent_retriever:
                # get_cruxes() on untyped ctx object
                cruxes = dissent_retriever.get_cruxes(debate_id, limit=5)
                belief_data["cruxes"] = cruxes
                belief_data["available"] = True
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Expected error fetching belief context: %s", e)
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning("Unexpected error fetching belief context: %s", e)

        return belief_data

    def _get_circuit_breaker_state(self, agent_id: str) -> dict[str, Any]:
        """Get circuit breaker state for an agent."""
        try:
            from aragora.resilience.simple_circuit_breaker import get_all_circuit_breakers

            all_breakers = get_all_circuit_breakers()
            # Look for a circuit breaker matching this agent_id
            cb = all_breakers.get(agent_id)
            if cb is not None:
                stats = cb.get_stats()
                return {
                    "available": True,
                    "state": stats.state.value,
                    "failure_count": stats.failure_count,
                    "success_count": stats.success_count,
                    "last_failure": stats.last_failure_time,
                    "reset_timeout": stats.cooldown_remaining,
                }
            return {"available": False, "state": "unknown"}
        except ImportError:
            return {"available": False, "state": "unknown"}

    def _get_airlock_metrics(self, agent_id: str) -> dict[str, Any]:
        """Get airlock proxy metrics for an agent.

        Note: Airlock metrics are tracked per-proxy instance, not globally by agent_id.
        To get metrics, you need access to the actual AirlockProxy instance.
        This method checks for a registered proxy in the handler context.
        """
        # Check if we have an airlock proxy registry in the context
        airlock_registry: dict[str, Any] | None = self.ctx.get("airlock_registry")
        if airlock_registry is not None:
            proxy = airlock_registry.get(agent_id)
            if proxy is not None and hasattr(proxy, "metrics"):
                metrics = proxy.metrics
                return {
                    "available": True,
                    "requests_total": metrics.total_calls,
                    "requests_blocked": metrics.fallback_responses,
                    "latency_avg_ms": metrics.avg_latency_ms,
                    "error_rate": 1.0 - (metrics.success_rate / 100.0)
                    if metrics.total_calls > 0
                    else 0.0,
                }
        return {"available": False}

    def _calculate_availability(self, agent_id: str) -> dict[str, Any]:
        """Calculate availability metrics for an agent."""
        # Default values
        return {
            "available": True,
            "uptime_percent": 99.9,
            "last_24h_errors": 0,
            "mean_response_time_ms": 500,
        }

    def _calculate_reliability_score(self, metrics: dict[str, Any]) -> float:
        """Calculate overall reliability score (0-1)."""
        score = 1.0

        # Penalize for circuit breaker issues
        cb = metrics.get("circuit_breaker", {})
        if cb.get("state") == "open":
            score *= 0.3
        elif cb.get("state") == "half-open":
            score *= 0.7

        # Penalize for high error rate
        airlock = metrics.get("airlock", {})
        error_rate = airlock.get("error_rate", 0.0)
        score *= 1.0 - min(error_rate, 0.5)

        return round(score, 3)

    def _get_rlm_metrics(self, debate_id: str) -> dict[str, Any] | None:
        """Get RLM compression metrics for a debate."""
        # Check for RLM handler in context
        rlm_handler = self.ctx.get("rlm_handler")
        if rlm_handler and hasattr(rlm_handler, "get_compression_stats"):
            try:
                return rlm_handler.get_compression_stats(debate_id)
            except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.debug("Error getting RLM metrics: %s", e)
        return None

    def _generate_compression_recommendations(self, analysis: dict[str, Any]) -> list[str]:
        """Generate recommendations based on compression analysis."""
        recommendations = []

        compression = analysis.get("compression", {})
        if not compression.get("enabled"):
            recommendations.append(
                "Enable RLM compression for debates > 3 rounds to reduce context size"
            )

        if compression.get("ratio", 0) < 0.3:
            recommendations.append(
                "Consider increasing compression levels for better token efficiency"
            )

        quality = analysis.get("quality", {})
        if quality.get("information_retained", 1.0) < 0.8:
            recommendations.append("Reduce compression level to preserve more information")

        return recommendations

    def _error_response(self, message: str, status_code: int) -> HandlerResult:
        """Create an error response."""
        return HandlerResult(
            status_code=status_code,
            content_type="application/json",
            body=json.dumps({"error": message}).encode(),
        )
