"""
Uncertainty estimation endpoint handlers.

Exposes the uncertainty quantification system for confidence calibration
and disagreement analysis.

Endpoints:
- POST /api/uncertainty/estimate - Estimate uncertainty for a debate/response
- GET /api/uncertainty/debate/:id - Get debate uncertainty metrics
- GET /api/uncertainty/agent/:id - Get agent calibration profile
- POST /api/uncertainty/followups - Generate follow-up suggestions from cruxes
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from ..utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


class UncertaintyHandler(BaseHandler):
    """Handler for uncertainty estimation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/uncertainty/estimate",
        "/api/v1/uncertainty/followups",
        "/api/v1/uncertainty/debate",
        "/api/v1/uncertainty/debate/*",
        "/api/v1/uncertainty/agent/*",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        if path.startswith("/api/v1/uncertainty/"):
            return True
        return False

    @require_permission("uncertainty:read")
    @rate_limit(requests_per_minute=60)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any] | str,
        handler: Any = None,
    ) -> HandlerResult | None:
        """Route requests to appropriate handler method.

        Supports legacy call signature: handle(path, method, handler).
        """
        method = "GET"
        if isinstance(query_params, str):
            method = query_params.upper()
            query_params = {}

        if method == "POST":
            return await self._handle_post(path, query_params, handler)
        return await self._handle_get(path, query_params, handler)

    async def _handle_get(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route GET requests to appropriate handler method."""
        # GET /api/v1/uncertainty/debate/:id
        # Parts: ["", "api", "v1", "uncertainty", "debate", "{debate_id}"]
        if path.startswith("/api/v1/uncertainty/debate/"):
            parts = path.split("/")
            if len(parts) == 6:
                debate_id = parts[5]
                is_valid, err = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return await self._get_debate_uncertainty(debate_id)

        # GET /api/v1/uncertainty/agent/:id
        # Parts: ["", "api", "v1", "uncertainty", "agent", "{agent_id}"]
        if path.startswith("/api/v1/uncertainty/agent/"):
            parts = path.split("/")
            if len(parts) == 6:
                agent_id = parts[5]
                is_valid, err = validate_path_segment(agent_id, "agent_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err, 400)
                return self._get_agent_calibration(agent_id)

        return None

    @handle_errors("uncertainty creation")
    @require_permission("uncertainty:read")
    @rate_limit(requests_per_minute=60)
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route POST requests to appropriate handler method."""
        return await self._handle_post(path, query_params, handler)

    @handle_errors
    async def _handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Internal POST router for uncertainty endpoints."""
        # POST /api/uncertainty/estimate
        if path == "/api/v1/uncertainty/estimate":
            return await self._estimate_uncertainty(handler)

        # POST /api/uncertainty/followups
        if path == "/api/v1/uncertainty/followups":
            return await self._generate_followups(handler)

        return None

    def _get_estimator(self) -> Any | None:
        """Get the ConfidenceEstimator instance."""
        try:
            from aragora.uncertainty.estimator import ConfidenceEstimator

            # Use a shared instance from context if available
            if hasattr(self, "_ctx") and self._ctx and "confidence_estimator" in self._ctx:
                return self._ctx["confidence_estimator"]
            # Otherwise create a new instance
            return ConfidenceEstimator()
        except ImportError:
            logger.warning("Uncertainty module not available")
            return None

    def _get_analyzer(self) -> Any | None:
        """Get the DisagreementAnalyzer instance."""
        try:
            from aragora.uncertainty.estimator import DisagreementAnalyzer

            return DisagreementAnalyzer()
        except ImportError:
            logger.warning("Uncertainty module not available")
            return None

    async def _estimate_uncertainty(self, handler: Any) -> HandlerResult:
        """Estimate uncertainty for provided debate data.

        Request body:
        {
            "messages": [...],  # List of debate messages
            "votes": [...],     # List of votes
            "proposals": {}     # Agent proposals
        }
        """
        estimator = self._get_estimator()
        if estimator is None:
            return error_response("Uncertainty module not available", 503)

        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        try:
            from aragora.core import Message, Vote

            # Parse messages
            messages = []
            for msg_data in data.get("messages", []):
                if isinstance(msg_data, dict):
                    messages.append(
                        Message(
                            content=msg_data.get("content", ""),
                            agent=msg_data.get("agent", "unknown"),
                            role=msg_data.get("role", "agent"),
                            round=msg_data.get("round", 0),
                        )
                    )

            # Parse votes
            votes = []
            for vote_data in data.get("votes", []):
                if isinstance(vote_data, dict):
                    votes.append(
                        Vote(
                            agent=vote_data.get("agent", "unknown"),
                            choice=vote_data.get("choice", ""),
                            reasoning=vote_data.get("reasoning", ""),
                            confidence=vote_data.get("confidence", 0.5),
                        )
                    )

            proposals = data.get("proposals", {})

            # Analyze uncertainty
            metrics = estimator.analyze_disagreement(messages, votes, proposals)

            return json_response(
                {
                    "metrics": metrics.to_dict(),
                    "message": "Uncertainty estimated successfully",
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid data for uncertainty estimation: %s", e)
            return error_response("Invalid request data", 400)
        except (ImportError, RuntimeError, AttributeError, OSError) as e:
            logger.exception("Unexpected error estimating uncertainty: %s", e)
            return error_response("Uncertainty estimation failed", 500)

    async def _generate_followups(self, handler: Any) -> HandlerResult:
        """Generate follow-up debate suggestions from cruxes.

        Request body:
        {
            "cruxes": [...],           # List of disagreement cruxes
            "parent_debate_id": "...", # Optional parent debate ID
            "available_agents": [...]  # Optional list of available agents
        }
        """
        analyzer = self._get_analyzer()
        if analyzer is None:
            return error_response("Uncertainty module not available", 503)

        data = self.read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        try:
            from aragora.uncertainty.estimator import DisagreementCrux

            # Parse cruxes
            cruxes = []
            for crux_data in data.get("cruxes", []):
                if isinstance(crux_data, dict):
                    cruxes.append(
                        DisagreementCrux(
                            description=crux_data.get("description", ""),
                            divergent_agents=crux_data.get("divergent_agents", []),
                            evidence_needed=crux_data.get("evidence_needed", ""),
                            severity=crux_data.get("severity", 0.5),
                            crux_id=crux_data.get("id", ""),
                        )
                    )

            if not cruxes:
                return error_response("No cruxes provided", 400)

            parent_debate_id = data.get("parent_debate_id")
            available_agents = data.get("available_agents")

            # Generate follow-up suggestions
            suggestions = analyzer.suggest_followups(
                cruxes=cruxes,
                parent_debate_id=parent_debate_id,
                available_agents=available_agents,
            )

            return json_response(
                {
                    "followups": [s.to_dict() for s in suggestions],
                    "total": len(suggestions),
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid data for follow-up generation: %s", e)
            return error_response("Invalid request data", 400)
        except (ImportError, RuntimeError, AttributeError, OSError) as e:
            logger.exception("Unexpected error generating follow-ups: %s", e)
            return error_response("Follow-up generation failed", 500)

    async def _get_debate_uncertainty(self, debate_id: str) -> HandlerResult:
        """Get uncertainty metrics for a specific debate."""
        try:
            # Try to get debate from storage
            storage = self._ctx.get("storage") if hasattr(self, "_ctx") and self._ctx else None
            if storage is None:
                return error_response("Storage not available", 503)

            # Look up debate
            debate = None
            if hasattr(storage, "get_debate"):
                debate = await storage.get_debate(debate_id)
            elif hasattr(storage, "get"):
                debate = storage.get(debate_id)

            if debate is None:
                return error_response(f"Debate not found: {debate_id}", 404)

            # Get messages and votes from debate
            messages = getattr(debate, "messages", [])
            votes = getattr(debate, "votes", [])
            proposals = getattr(debate, "proposals", {})

            # If no uncertainty metrics stored, compute them
            estimator = self._get_estimator()
            if estimator is None:
                return error_response("Uncertainty module not available", 503)

            metrics = estimator.analyze_disagreement(messages, votes, proposals)

            return json_response(
                {
                    "debate_id": debate_id,
                    "metrics": metrics.to_dict(),
                }
            )

        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error getting debate uncertainty: %s", e)
            return error_response("Invalid debate data", 400)
        except (RuntimeError, ValueError, OSError, ImportError) as e:
            logger.exception("Unexpected error getting debate uncertainty: %s", e)
            return error_response("Debate uncertainty retrieval failed", 500)

    def _get_agent_calibration(self, agent_id: str) -> HandlerResult:
        """Get calibration profile for a specific agent."""
        estimator = self._get_estimator()
        if estimator is None:
            return error_response("Uncertainty module not available", 503)

        try:
            # Get calibration quality
            calibration_quality = estimator.get_agent_calibration_quality(agent_id)

            # Get confidence history if available
            confidence_history: list[dict[str, Any]] = []
            if agent_id in estimator.agent_confidences:
                for score in estimator.agent_confidences[agent_id][-10:]:  # Last 10
                    confidence_history.append(score.to_dict())

            # Get calibration history if available
            calibration_history: list[dict[str, Any]] = []
            if agent_id in estimator.calibration_history:
                for confidence, was_correct in estimator.calibration_history[agent_id][-10:]:
                    calibration_history.append(
                        {
                            "confidence": confidence,
                            "was_correct": was_correct,
                        }
                    )

            return json_response(
                {
                    "agent_id": agent_id,
                    "calibration_quality": calibration_quality,
                    "confidence_history": confidence_history,
                    "calibration_history": calibration_history,
                    "brier_score": estimator.brier_scores.get(agent_id),
                }
            )

        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error getting agent calibration: %s", e)
            return error_response("Invalid agent data", 400)
        except (RuntimeError, ValueError, OSError, ImportError) as e:
            logger.exception("Unexpected error getting agent calibration: %s", e)
            return error_response("Agent calibration retrieval failed", 500)
