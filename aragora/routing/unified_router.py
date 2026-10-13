"""
Unified Decision Router - Chains business logic with execution routing.

Integrates:
- Gateway Router: Business criteria routing (financial thresholds, risk levels,
  compliance requirements) - decides IF debate is needed vs direct execution
- Core Router: Engine selection routing (Debate, Workflow, Gauntlet, Quick)

When DecisionType.AUTO is specified, the unified router:
1. Evaluates business criteria via Gateway router
2. Maps the routing decision to appropriate Core router path
3. Executes and returns the result

This provides intelligent routing that considers both business requirements
and execution strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.core.decision_models import DecisionRequest, DecisionResult

logger = logging.getLogger(__name__)


@dataclass
class UnifiedRoutingResult:
    """Result of unified routing decision."""

    gateway_decision: dict[str, Any] | None = None
    core_result: Any | None = None
    routing_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class UnifiedDecisionRouter:
    """
    Unified router that chains Gateway and Core routing.

    Flow:
        1. If decision_type == AUTO:
           - Use Gateway router to determine debate vs execute
           - Map to appropriate Core router path
        2. Otherwise:
           - Route directly through Core router

    This enables intelligent routing based on business criteria while
    preserving explicit routing control when needed.

    Example:
        >>> router = UnifiedDecisionRouter()
        >>> result = await router.route(request)

        # For AUTO type, it evaluates business criteria:
        # - Financial threshold exceeded? → DEBATE
        # - High risk action? → DEBATE
        # - Compliance requirements? → DEBATE
        # - Otherwise → QUICK execution
    """

    def __init__(
        self,
        gateway_router: Any | None = None,
        core_router: Any | None = None,
        document_store: Any | None = None,
        evidence_store: Any | None = None,
    ):
        """
        Initialize unified router.

        Args:
            gateway_router: Optional pre-configured Gateway router
            core_router: Optional pre-configured Core router
            document_store: Document store for Core router
            evidence_store: Evidence store for Core router
        """
        self._gateway_router = gateway_router
        self._core_router = core_router
        self._document_store = document_store
        self._evidence_store = evidence_store

    def _get_gateway_router(self) -> Any:
        """Lazy-load Gateway router."""
        if self._gateway_router is None:
            try:
                from aragora.routing.gateway_decision_router import (
                    DecisionRouter as GatewayRouter,
                    RoutingCriteria,
                )
                from aragora.routing.config import load_gateway_routing_config

                cfg = load_gateway_routing_config()
                criteria = RoutingCriteria(
                    financial_threshold=cfg.financial_threshold,
                    risk_levels=cfg.risk_levels,
                    compliance_flags=cfg.compliance_flags,
                    stakeholder_threshold=cfg.stakeholder_threshold,
                    require_debate_keywords=cfg.require_debate_keywords,
                    require_execute_keywords=cfg.require_execute_keywords,
                    time_sensitive_threshold_seconds=cfg.time_sensitive_threshold_seconds,
                    confidence_threshold=cfg.confidence_threshold,
                )
                self._gateway_router = GatewayRouter(
                    criteria=criteria,
                )
                logger.debug("Gateway router initialized with configured criteria")
            except ImportError as e:
                logger.warning("Gateway router not available: %s", e)
        return self._gateway_router

    def _get_core_router(self) -> Any:
        """Lazy-load Core router."""
        if self._core_router is None:
            try:
                from aragora.core.decision_router import (
                    DecisionRouter as CoreRouter,
                )

                self._core_router = CoreRouter(
                    document_store=self._document_store,
                    evidence_store=self._evidence_store,
                )
                logger.debug("Core router initialized")
            except ImportError as e:
                logger.warning("Core router not available: %s", e)
        return self._core_router

    async def route(self, request: DecisionRequest) -> DecisionResult:
        """
        Route a decision request through the unified routing pipeline.

        Args:
            request: Decision request to route

        Returns:
            DecisionResult with outcome
        """
        from aragora.core.decision_types import DecisionType

        # For explicit types, route directly through Core
        if request.decision_type != DecisionType.AUTO:
            logger.debug(
                "Explicit decision type %s, routing directly to Core router",
                request.decision_type.value,
            )
            return await self._route_via_core(request)

        # For AUTO, use Gateway to determine the path
        logger.debug("AUTO decision type, evaluating via Gateway router")
        return await self._route_auto(request)

    async def _route_auto(self, request: DecisionRequest) -> DecisionResult:
        """
        Route AUTO type using Gateway business logic.

        Evaluates business criteria to decide between:
        - DEBATE: For high-stakes, compliance, or multi-stakeholder decisions
        - QUICK: For straightforward execution
        """
        from aragora.core.decision_types import DecisionType
        from aragora.core.decision_models import DecisionResult

        gateway = self._get_gateway_router()

        if gateway is None:
            # Fallback: default to DEBATE if Gateway unavailable
            logger.warning("Gateway router unavailable, defaulting to DEBATE")
            request.decision_type = DecisionType.DEBATE
            return await self._route_via_core(request)

        try:
            # Build request dict for Gateway router
            gateway_request = self._build_gateway_request(request)
            gateway_context = self._build_gateway_context(request)

            # Get routing decision from Gateway
            decision = await gateway.route(gateway_request, gateway_context)

            logger.info(
                "Gateway routing decision: %s (reason: %s...)",
                decision.destination.value,
                decision.reason[:80],
            )

            # Map Gateway destination to Core decision type
            from aragora.routing.gateway_decision_router import RouteDestination

            if decision.destination == RouteDestination.DEBATE:
                request.decision_type = DecisionType.DEBATE
            elif decision.destination == RouteDestination.EXECUTE:
                request.decision_type = DecisionType.QUICK
            elif decision.destination == RouteDestination.HYBRID_DEBATE_THEN_EXECUTE:
                # Debate first, then we'd execute - start with debate
                request.decision_type = DecisionType.DEBATE
                # Store hybrid intent in metadata for post-processing
                if request.context.metadata is None:
                    request.context.metadata = {}
                request.context.metadata["hybrid_mode"] = "debate_then_execute"
            elif decision.destination == RouteDestination.HYBRID_EXECUTE_WITH_VALIDATION:
                # Execute with post-validation debate
                request.decision_type = DecisionType.QUICK
                if request.context.metadata is None:
                    request.context.metadata = {}
                request.context.metadata["hybrid_mode"] = "execute_with_validation"
            elif decision.destination == RouteDestination.REJECT:
                # Request rejected by business logic
                return DecisionResult(
                    request_id=request.request_id,
                    decision_type=DecisionType.AUTO,
                    answer="",
                    confidence=0.0,
                    consensus_reached=False,
                    success=False,
                    error=f"Request rejected: {decision.reason}",
                )
            else:
                # Unknown destination, default to DEBATE
                logger.warning(
                    "Unknown gateway destination %s, defaulting to DEBATE", decision.destination
                )
                request.decision_type = DecisionType.DEBATE

            # Route through Core with the resolved decision type
            result = await self._route_via_core(request)

            # Attach gateway decision metadata
            if result.metadata is None:
                result.metadata = {}
            result.metadata["gateway_decision"] = {
                "destination": decision.destination.value,
                "reason": decision.reason,
                "criteria_matched": decision.criteria_matched,
                "confidence": decision.confidence,
            }

            return result

        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            logger.error("Gateway routing failed: %s", e, exc_info=True)
            # Fallback to DEBATE
            request.decision_type = DecisionType.DEBATE
            return await self._route_via_core(request)

    async def _route_via_core(self, request: DecisionRequest) -> DecisionResult:
        """Route through Core router."""
        core = self._get_core_router()

        if core is None:
            from aragora.core.decision_models import DecisionResult

            return DecisionResult(
                request_id=request.request_id,
                decision_type=request.decision_type,
                answer="",
                confidence=0.0,
                consensus_reached=False,
                success=False,
                error="Core decision router not available",
            )

        return await core.route(request)

    def _build_gateway_request(self, request: DecisionRequest) -> dict[str, Any]:
        """Convert DecisionRequest to Gateway router request dict."""
        gateway_request: dict[str, Any] = {
            "content": request.content,
            "description": request.content[:500] if request.content else "",
        }

        # Extract financial amount if present in metadata
        if request.context.metadata:
            meta = request.context.metadata
            if "amount" in meta:
                gateway_request["amount"] = meta["amount"]
            if "risk_level" in meta:
                gateway_request["risk_level"] = meta["risk_level"]
            if "compliance_flags" in meta:
                gateway_request["compliance_flags"] = meta["compliance_flags"]
            if "stakeholders" in meta:
                gateway_request["stakeholders"] = meta["stakeholders"]
            if "category" in meta:
                gateway_request["category"] = meta["category"]

        # Extract from config if available
        if request.config:
            cfg = request.config
            if hasattr(cfg, "financial_amount") and cfg.financial_amount:
                gateway_request["amount"] = cfg.financial_amount
            if hasattr(cfg, "risk_level") and cfg.risk_level:
                gateway_request["risk_level"] = cfg.risk_level

        return gateway_request

    def _build_gateway_context(self, request: DecisionRequest) -> dict[str, Any]:
        """Build Gateway router context from DecisionRequest."""
        return {
            "tenant_id": request.context.tenant_id,
            "workspace_id": request.context.workspace_id,
            "user_id": request.context.user_id,
        }

    def configure_gateway(
        self,
        financial_threshold: float | None = None,
        risk_levels: set[str] | None = None,
        compliance_flags: set[str] | None = None,
    ) -> None:
        """
        Configure Gateway router criteria.

        Args:
            financial_threshold: Amount above which debates are required
            risk_levels: Risk levels requiring debate
            compliance_flags: Compliance categories requiring debate
        """
        gateway = self._get_gateway_router()
        if gateway is None:
            logger.warning("Cannot configure Gateway router - not available")
            return

        try:
            from aragora.routing.gateway_decision_router import RoutingCriteria

            from aragora.routing.config import load_gateway_routing_config

            cfg = load_gateway_routing_config()
            criteria = RoutingCriteria(
                financial_threshold=financial_threshold
                if financial_threshold is not None
                else cfg.financial_threshold,
                risk_levels=risk_levels or cfg.risk_levels,
                compliance_flags=compliance_flags or cfg.compliance_flags,
                stakeholder_threshold=cfg.stakeholder_threshold,
                require_debate_keywords=cfg.require_debate_keywords,
                require_execute_keywords=cfg.require_execute_keywords,
                time_sensitive_threshold_seconds=cfg.time_sensitive_threshold_seconds,
                confidence_threshold=cfg.confidence_threshold,
            )
            gateway.update_criteria(criteria)
            logger.info(
                "Gateway criteria updated: threshold=$%s, risk_levels=%s",
                financial_threshold,
                risk_levels,
            )
        except ImportError:
            logger.warning("Gateway router criteria update failed - module not available")

    def add_routing_rule(
        self,
        rule_id: str,
        condition: Any,
        destination: str,
        priority: int = 0,
        reason: str = "",
    ) -> None:
        """
        Add a custom routing rule to Gateway router.

        Args:
            rule_id: Unique rule identifier
            condition: Callable that returns True if rule matches
            destination: "debate", "execute", or "reject"
            priority: Higher priority rules evaluated first
            reason: Explanation for the routing decision
        """
        gateway = self._get_gateway_router()
        if gateway is None:
            logger.warning("Cannot add rule - Gateway router not available")
            return

        try:
            from aragora.routing.gateway_decision_router import RouteDestination, RoutingRule

            dest_map = {
                "debate": RouteDestination.DEBATE,
                "execute": RouteDestination.EXECUTE,
                "reject": RouteDestination.REJECT,
                "hybrid_debate_execute": RouteDestination.HYBRID_DEBATE_THEN_EXECUTE,
                "hybrid_execute_validate": RouteDestination.HYBRID_EXECUTE_WITH_VALIDATION,
            }

            rule = RoutingRule(
                rule_id=rule_id,
                condition=condition,
                destination=dest_map.get(destination, RouteDestination.DEBATE),
                priority=priority,
                reason=reason,
            )
            gateway.add_rule(rule)
            logger.info("Added routing rule: %s -> %s", rule_id, destination)
        except ImportError:
            logger.warning("Gateway routing rule add failed - module not available")


# =============================================================================
# Singleton management
# =============================================================================

_unified_router: UnifiedDecisionRouter | None = None


def get_unified_router(
    document_store: Any | None = None,
    evidence_store: Any | None = None,
) -> UnifiedDecisionRouter:
    """Get or create the global unified decision router."""
    global _unified_router
    if _unified_router is None:
        _unified_router = UnifiedDecisionRouter(
            document_store=document_store,
            evidence_store=evidence_store,
        )
    return _unified_router


def reset_unified_router() -> None:
    """Reset the global unified router (for testing)."""
    global _unified_router
    _unified_router = None


async def route_decision_auto(
    content: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """
    Convenience function for AUTO routing.

    Uses unified router to intelligently decide between debate and execution.

    Args:
        content: The question/task to route
        user_id: Optional user identifier
        workspace_id: Optional workspace identifier
        tenant_id: Optional tenant identifier
        metadata: Additional metadata (amount, risk_level, etc.)
        **kwargs: Additional DecisionRequest fields

    Returns:
        DecisionResult with outcome
    """
    from aragora.core.decision_models import DecisionRequest, RequestContext
    from aragora.core.decision_types import DecisionType

    # Build context
    context = RequestContext(
        user_id=user_id,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        metadata=metadata or {},
    )

    # Build request
    request = DecisionRequest(
        content=content,
        decision_type=DecisionType.AUTO,
        context=context,
        **kwargs,
    )

    # Route
    router = get_unified_router()
    return await router.route(request)


__all__ = [
    "UnifiedDecisionRouter",
    "UnifiedRoutingResult",
    "get_unified_router",
    "reset_unified_router",
    "route_decision_auto",
]
