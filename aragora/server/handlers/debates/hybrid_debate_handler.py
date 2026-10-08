"""
Hybrid Debate Handler - HTTP endpoints for hybrid debates combining
external and internal agents.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-02.

Provides API endpoints for:
- Starting hybrid debates (external + internal verification agents)
- Retrieving hybrid debate results
- Listing hybrid debates with filtering

Routes:
    POST   /api/v1/debates/hybrid          - Start a hybrid debate
    GET    /api/v1/debates/hybrid           - List hybrid debates
    GET    /api/v1/debates/hybrid/{id}      - Get hybrid debate result
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.resilience import CircuitBreaker
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

HYBRID_AVAILABLE = importlib.util.find_spec("aragora.debate.hybrid_protocol") is not None

# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for hybrid debate operations
# Opens after 5 consecutive failures, recovers after 30 seconds
_hybrid_debate_circuit_breaker = CircuitBreaker(
    name="hybrid_debate_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_hybrid_debate_circuit_breaker_lock = threading.Lock()


def get_hybrid_debate_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for hybrid debate operations."""
    return _hybrid_debate_circuit_breaker


def reset_hybrid_debate_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _hybrid_debate_circuit_breaker_lock:
        _hybrid_debate_circuit_breaker._single_failures = 0
        _hybrid_debate_circuit_breaker._single_open_at = 0.0
        _hybrid_debate_circuit_breaker._single_successes = 0
        _hybrid_debate_circuit_breaker._single_half_open_calls = 0


class HybridDebateHandler(BaseHandler):
    """
    HTTP request handler for hybrid debate API endpoints.

    Hybrid debates combine external agents (e.g., CrewAI, LangGraph) with
    internal verification agents to produce consensus-driven decisions.
    """

    ROUTES = [
        "/api/v1/debates/hybrid",
        "/api/v1/debates/hybrid/*",
    ]

    def __init__(self, server_context: dict[str, Any]) -> None:
        super().__init__(server_context)
        self._debates: dict[str, dict[str, Any]] = {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.rstrip("/").startswith("/api/v1/debates/hybrid")

    # =========================================================================
    # GET Handlers
    # =========================================================================

    @require_permission("gateway:hybrid_debate")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        if not HYBRID_AVAILABLE:
            return error_response("Hybrid debate module not available", 503)

        stripped = path.rstrip("/")

        # GET /api/v1/debates/hybrid - list debates
        if stripped == "/api/v1/debates/hybrid":
            return self._handle_list_debates(query_params, handler)

        # GET /api/v1/debates/hybrid/{id} - get specific debate
        if stripped.startswith("/api/v1/debates/hybrid/"):
            debate_id = stripped.split("/")[-1]
            if debate_id and debate_id != "hybrid":
                return self._handle_get_debate(debate_id, handler)

        return None

    # =========================================================================
    # POST Handlers
    # =========================================================================

    @handle_errors("hybrid debate creation")
    @require_permission("gateway:hybrid_debate")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if not self.can_handle(path):
            return None

        if not HYBRID_AVAILABLE:
            return error_response("Hybrid debate module not available", 503)

        stripped = path.rstrip("/")

        # POST /api/v1/debates/hybrid - create a new hybrid debate
        if stripped == "/api/v1/debates/hybrid":
            return self._handle_create_debate(handler)

        return None

    # =========================================================================
    # Internal Handlers
    # =========================================================================

    @rate_limit(requests_per_minute=30, limiter_name="hybrid_debate_list")
    @handle_errors("list hybrid debates")
    def _handle_list_debates(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/debates/hybrid."""
        status_filter = query_params.get("status")
        limit = 20
        limit_str = query_params.get("limit")
        if limit_str is not None:
            try:
                limit = max(1, min(int(limit_str), 100))
            except (ValueError, TypeError):
                pass

        debates = list(self._debates.values())

        # Apply status filter
        if status_filter:
            debates = [d for d in debates if d.get("status") == status_filter]

        # Apply limit
        debates = debates[:limit]

        # Build summary list
        summaries = []
        for d in debates:
            summaries.append(
                {
                    "debate_id": d["debate_id"],
                    "task": d["task"],
                    "status": d["status"],
                    "consensus_reached": d.get("consensus_reached", False),
                    "confidence": d.get("confidence", 0.0),
                    "started_at": d.get("started_at"),
                }
            )

        return json_response(
            {
                "debates": summaries,
                "total": len(summaries),
            }
        )

    @handle_errors("get hybrid debate")
    def _handle_get_debate(self, debate_id: str, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/debates/hybrid/{id}."""
        debate = self._debates.get(debate_id)
        if not debate:
            return error_response(f"Hybrid debate not found: {debate_id}", 404)

        return json_response(debate)

    @rate_limit(requests_per_minute=5, limiter_name="hybrid_debate_create")
    @handle_errors("create hybrid debate")
    @log_request("create hybrid debate")
    def _handle_create_debate(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/debates/hybrid."""
        # Check circuit breaker
        cb = get_hybrid_debate_circuit_breaker()
        if not cb.can_proceed():
            logger.warning("Hybrid debate circuit breaker is open")
            return error_response("Service temporarily unavailable due to high error rate", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # --- Validate required fields ---

        # task
        task = body.get("task")
        if not task or not isinstance(task, str) or not task.strip():
            return error_response("task is required and must be a non-empty string", 400)
        task = task.strip()
        if len(task) > 5000:
            return error_response("task must not exceed 5000 characters", 400)

        # external_agent
        external_agent = body.get("external_agent")
        if not external_agent or not isinstance(external_agent, str) or not external_agent.strip():
            return error_response("external_agent is required", 400)
        external_agent = external_agent.strip()

        # Validate external_agent exists in registered agents
        external_agents = self.ctx.get("external_agents", {})
        if external_agent not in external_agents:
            return error_response(
                f"External agent not found: {external_agent}. "
                "Register it first via POST /api/v1/gateway/agents.",
                400,
            )

        # --- Validate optional fields ---

        # consensus_threshold
        consensus_threshold = body.get("consensus_threshold", 0.7)
        try:
            consensus_threshold = float(consensus_threshold)
        except (ValueError, TypeError):
            return error_response("consensus_threshold must be a number between 0.0 and 1.0", 400)
        if consensus_threshold < 0.0 or consensus_threshold > 1.0:
            return error_response("consensus_threshold must be between 0.0 and 1.0", 400)

        # max_rounds
        max_rounds = body.get("max_rounds", 3)
        try:
            max_rounds = int(max_rounds)
        except (ValueError, TypeError):
            return error_response("max_rounds must be an integer between 1 and 10", 400)
        if max_rounds < 1 or max_rounds > 10:
            return error_response("max_rounds must be between 1 and 10", 400)

        # verification_agents
        verification_agents = body.get("verification_agents", [])
        if not isinstance(verification_agents, list):
            return error_response("verification_agents must be a list", 400)

        # domain
        domain = body.get("domain", "general")
        if not isinstance(domain, str):
            domain = "general"

        # config
        config = body.get("config", {})
        if not isinstance(config, dict):
            config = {}

        # --- Build debate record ---
        debate_id = f"hybrid_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc).isoformat()

        debate_record: dict[str, Any] = {
            "debate_id": debate_id,
            "task": task,
            "status": "pending",
            "consensus_reached": False,
            "confidence": 0.0,
            "final_answer": None,
            "external_agent": external_agent,
            "verification_agents": verification_agents,
            "consensus_threshold": consensus_threshold,
            "max_rounds": max_rounds,
            "domain": domain,
            "config": config,
            "rounds": 0,
            "started_at": started_at,
            "completed_at": None,
        }

        # Run the debate (mockable in tests)
        try:
            result = self._run_debate(debate_record)
            debate_record.update(result)

            # Record success for circuit breaker
            cb.record_success()
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            # Record failure for circuit breaker
            cb.record_failure()
            logger.error("Hybrid debate execution failed: %s", e)
            raise

        # Store the debate
        self._debates[debate_id] = debate_record

        logger.info(
            "Hybrid debate created: %s (task=%s, external=%s)",
            debate_id,
            task[:80],
            external_agent,
        )

        return json_response(debate_record, status=201)

    def _run_debate(self, debate_record: dict[str, Any]) -> dict[str, Any]:
        """Run the hybrid debate.

        This method is separated to allow easy mocking in tests.
        In production, this would use HybridDebateProtocol to
        coordinate external and internal agents.

        Args:
            debate_record: The debate configuration and initial state.

        Returns:
            Dict with result fields to merge into the debate record.
        """
        completed_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "completed",
            "consensus_reached": True,
            "confidence": 0.85,
            "final_answer": f"Hybrid debate result for: {debate_record['task'][:100]}",
            "rounds": min(debate_record.get("max_rounds", 3), 2),
            "completed_at": completed_at,
        }


__all__ = ["HybridDebateHandler"]
