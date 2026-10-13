"""
Intelligent Decision Router - Route between debate and task execution.

Routes requests intelligently based on configurable criteria:
- Route to Aragora Debate Engine for consensus-required decisions
- Route to OpenClaw for direct task execution
- Support hybrid routing (debate then execute, or execute with debate validation)

Routing Criteria:
- Financial thresholds (transactions above configured amount require debate)
- Risk levels (high-risk actions require consensus)
- Compliance requirements (regulated actions need multi-stakeholder approval)
- Explicit user request for debate or execution
- Multi-stakeholder decisions with conflicting interests

Usage:
    from aragora.routing.gateway_decision_router import (
        DecisionRouter,
        RoutingCriteria,
        RouteDecision,
        RoutingRule,
        RouteDestination,
    )

    # Configure router with criteria
    router = DecisionRouter(
        criteria=RoutingCriteria(
            financial_threshold=10000.0,
            risk_levels={"high", "critical"},
            compliance_flags={"pii", "financial", "hipaa"},
        ),
    )

    # Add custom rules
    router.add_rule(RoutingRule(
        rule_id="large-transactions",
        condition=lambda req: req.get("amount", 0) > 50000,
        destination=RouteDestination.DEBATE,
        priority=100,
        reason="Large financial transactions require debate consensus",
    ))

    # Route a request
    decision = await router.route(request, context)
    if decision.destination == RouteDestination.DEBATE:
        result = await arena.run()
    else:
        result = await openclaw.execute(request)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class RouteDestination(str, Enum):
    """Destination for routing decisions."""

    DEBATE = "debate"  # Route to Aragora Debate Engine
    EXECUTE = "execute"  # Route to OpenClaw task execution
    HYBRID_DEBATE_THEN_EXECUTE = "hybrid_debate_execute"  # Debate first, then execute
    HYBRID_EXECUTE_WITH_VALIDATION = (
        "hybrid_execute_validate"  # Execute with post-validation debate
    )
    REJECT = "reject"  # Reject the request


class RiskLevel(str, Enum):
    """Risk levels for actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionCategory(str, Enum):
    """Categories of actions for default routing."""

    FINANCIAL = "financial"
    COMPLIANCE = "compliance"
    SECURITY = "security"
    INFRASTRUCTURE = "infrastructure"
    DATA_MANAGEMENT = "data_management"
    USER_MANAGEMENT = "user_management"
    COMMUNICATION = "communication"
    ANALYTICS = "analytics"
    GENERAL = "general"


class RoutingEventType(str, Enum):
    """Types of routing events for monitoring."""

    ROUTE_TO_DEBATE = "route_to_debate"
    ROUTE_TO_EXECUTE = "route_to_execute"
    ROUTE_TO_HYBRID = "route_to_hybrid"
    ROUTE_REJECTED = "route_rejected"
    CRITERIA_MATCHED = "criteria_matched"
    RULE_MATCHED = "rule_matched"
    DEFAULT_ROUTE = "default_route"
    ANOMALY_DETECTED = "anomaly_detected"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RoutingCriteria:
    """
    Criteria for routing decisions.

    Defines thresholds and flags that determine when requests should be
    routed to debate vs. direct execution.

    Attributes:
        financial_threshold: Amount above which financial transactions require debate.
        risk_levels: Set of risk levels that require debate consensus.
        compliance_flags: Set of compliance categories requiring debate.
        stakeholder_threshold: Number of stakeholders above which debate is required.
        require_debate_keywords: Keywords in request that trigger debate routing.
        require_execute_keywords: Keywords that explicitly request execution.
        time_sensitive_threshold_seconds: Time limit below which execution is preferred.
        confidence_threshold: Minimum confidence for direct execution.
    """

    financial_threshold: float = 10000.0
    risk_levels: set[RiskLevel | str] = field(
        default_factory=lambda: {RiskLevel.HIGH, RiskLevel.CRITICAL}
    )
    compliance_flags: set[str] = field(
        default_factory=lambda: {"pii", "financial", "hipaa", "gdpr", "sox"}
    )
    stakeholder_threshold: int = 3
    require_debate_keywords: set[str] = field(
        default_factory=lambda: {"consensus", "debate", "discuss", "decide", "vote", "approve"}
    )
    require_execute_keywords: set[str] = field(
        default_factory=lambda: {"execute", "run", "perform", "do", "just do it"}
    )
    time_sensitive_threshold_seconds: int = 60
    confidence_threshold: float = 0.85

    def __post_init__(self) -> None:
        """Normalize risk levels to enum values."""
        normalized_levels: set[RiskLevel | str] = set()
        for level in self.risk_levels:
            if isinstance(level, str):
                try:
                    normalized_levels.add(RiskLevel(level))
                except ValueError:
                    normalized_levels.add(level)
            else:
                normalized_levels.add(level)
        self.risk_levels = normalized_levels


@dataclass
class RouteDecision:
    """
    Result of a routing decision.

    Attributes:
        destination: Where to route the request.
        reason: Human-readable explanation for the decision.
        criteria_matched: List of criteria that triggered this decision.
        rule_id: ID of the rule that matched (if any).
        confidence: Confidence in the routing decision (0.0-1.0).
        metadata: Additional routing metadata.
        decision_time_ms: Time taken to make the routing decision.
        request_id: Unique identifier for tracking.
        timestamp: When the decision was made.
    """

    destination: RouteDestination
    reason: str
    criteria_matched: list[str] = field(default_factory=list)
    rule_id: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    decision_time_ms: float = 0.0
    request_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert decision to dictionary for serialization."""
        return {
            "destination": self.destination.value,
            "reason": self.reason,
            "criteria_matched": self.criteria_matched,
            "rule_id": self.rule_id,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "decision_time_ms": self.decision_time_ms,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RoutingRule:
    """
    Custom routing rule with condition and destination.

    Attributes:
        rule_id: Unique identifier for the rule.
        condition: Callable that takes request dict and returns True if rule matches.
        destination: Where to route when condition matches.
        priority: Higher priority rules are evaluated first.
        reason: Explanation for why this rule routes to the destination.
        enabled: Whether the rule is active.
        tenant_id: Optional tenant restriction for the rule.
        action_categories: Optional set of action categories this rule applies to.
        metadata: Additional rule metadata.
    """

    rule_id: str
    condition: Callable[[dict[str, Any]], bool]
    destination: RouteDestination
    priority: int = 0
    reason: str = ""
    enabled: bool = True
    tenant_id: str | None = None
    action_categories: set[ActionCategory | str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TenantRoutingConfig:
    """
    Per-tenant routing configuration.

    Attributes:
        tenant_id: Tenant identifier.
        criteria: Tenant-specific routing criteria.
        default_destination: Default route when no rules match.
        enabled_categories: Action categories enabled for this tenant.
        override_rules: Tenant-specific routing rules.
        metadata: Additional tenant configuration.
    """

    tenant_id: str
    criteria: RoutingCriteria = field(default_factory=RoutingCriteria)
    default_destination: RouteDestination = RouteDestination.EXECUTE
    enabled_categories: set[ActionCategory | str] | None = None
    override_rules: list[RoutingRule] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategoryDefaults:
    """
    Default routing for action categories.

    Attributes:
        category: Action category.
        default_destination: Default route for this category.
        risk_level: Default risk level for actions in this category.
        requires_compliance_check: Whether compliance flags should be checked.
    """

    category: ActionCategory
    default_destination: RouteDestination
    risk_level: RiskLevel = RiskLevel.LOW
    requires_compliance_check: bool = False


@dataclass
class RoutingMetrics:
    """
    Metrics for routing decisions.

    Attributes:
        total_requests: Total number of routing decisions.
        debate_routes: Number of routes to debate.
        execute_routes: Number of routes to execution.
        hybrid_routes: Number of hybrid routes.
        rejected_routes: Number of rejected routes.
        avg_decision_time_ms: Average decision time in milliseconds.
        criteria_matches: Count of each criteria matched.
        rule_matches: Count of each rule matched.
    """

    total_requests: int = 0
    debate_routes: int = 0
    execute_routes: int = 0
    hybrid_routes: int = 0
    rejected_routes: int = 0
    avg_decision_time_ms: float = 0.0
    criteria_matches: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rule_matches: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for serialization."""
        total = self.total_requests or 1  # Avoid division by zero
        return {
            "total_requests": self.total_requests,
            "debate_routes": self.debate_routes,
            "execute_routes": self.execute_routes,
            "hybrid_routes": self.hybrid_routes,
            "rejected_routes": self.rejected_routes,
            "debate_ratio": self.debate_routes / total,
            "execute_ratio": self.execute_routes / total,
            "avg_decision_time_ms": self.avg_decision_time_ms,
            "criteria_matches": dict(self.criteria_matches),
            "rule_matches": dict(self.rule_matches),
        }


@dataclass
class RoutingAuditEntry:
    """
    Audit log entry for routing events.

    Attributes:
        timestamp: When the event occurred.
        event_type: Type of routing event.
        request_id: Request identifier.
        tenant_id: Tenant identifier.
        decision: The routing decision made.
        metadata: Additional event metadata.
    """

    timestamp: datetime
    event_type: RoutingEventType
    request_id: str
    tenant_id: str | None = None
    decision: RouteDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Protocols
# =============================================================================


class AnomalyDetectorProtocol(Protocol):
    """Protocol for anomaly detection in routing patterns."""

    def check_anomaly(
        self,
        tenant_id: str | None,
        destination: RouteDestination,
        metrics: RoutingMetrics,
    ) -> tuple[bool, str]:
        """Check if routing pattern is anomalous. Returns (is_anomaly, description)."""
        ...


class AlertHandlerProtocol(Protocol):
    """Protocol for handling routing alerts."""

    async def send_alert(
        self,
        alert_type: str,
        message: str,
        severity: str,
        metadata: dict[str, Any],
    ) -> None:
        """Send an alert for unusual routing patterns."""
        ...


# =============================================================================
# Default Category Configuration
# =============================================================================


DEFAULT_CATEGORY_CONFIGS: dict[ActionCategory, CategoryDefaults] = {
    ActionCategory.FINANCIAL: CategoryDefaults(
        category=ActionCategory.FINANCIAL,
        default_destination=RouteDestination.DEBATE,
        risk_level=RiskLevel.HIGH,
        requires_compliance_check=True,
    ),
    ActionCategory.COMPLIANCE: CategoryDefaults(
        category=ActionCategory.COMPLIANCE,
        default_destination=RouteDestination.DEBATE,
        risk_level=RiskLevel.HIGH,
        requires_compliance_check=True,
    ),
    ActionCategory.SECURITY: CategoryDefaults(
        category=ActionCategory.SECURITY,
        default_destination=RouteDestination.DEBATE,
        risk_level=RiskLevel.CRITICAL,
        requires_compliance_check=True,
    ),
    ActionCategory.INFRASTRUCTURE: CategoryDefaults(
        category=ActionCategory.INFRASTRUCTURE,
        default_destination=RouteDestination.HYBRID_DEBATE_THEN_EXECUTE,
        risk_level=RiskLevel.MEDIUM,
        requires_compliance_check=False,
    ),
    ActionCategory.DATA_MANAGEMENT: CategoryDefaults(
        category=ActionCategory.DATA_MANAGEMENT,
        default_destination=RouteDestination.DEBATE,
        risk_level=RiskLevel.MEDIUM,
        requires_compliance_check=True,
    ),
    ActionCategory.USER_MANAGEMENT: CategoryDefaults(
        category=ActionCategory.USER_MANAGEMENT,
        default_destination=RouteDestination.EXECUTE,
        risk_level=RiskLevel.MEDIUM,
        requires_compliance_check=False,
    ),
    ActionCategory.COMMUNICATION: CategoryDefaults(
        category=ActionCategory.COMMUNICATION,
        default_destination=RouteDestination.EXECUTE,
        risk_level=RiskLevel.LOW,
        requires_compliance_check=False,
    ),
    ActionCategory.ANALYTICS: CategoryDefaults(
        category=ActionCategory.ANALYTICS,
        default_destination=RouteDestination.EXECUTE,
        risk_level=RiskLevel.LOW,
        requires_compliance_check=False,
    ),
    ActionCategory.GENERAL: CategoryDefaults(
        category=ActionCategory.GENERAL,
        default_destination=RouteDestination.EXECUTE,
        risk_level=RiskLevel.LOW,
        requires_compliance_check=False,
    ),
}


# =============================================================================
# Decision Router
# =============================================================================


class DecisionRouter:
    """
    Intelligent router for deciding between debate and task execution.

    Routes requests based on configurable criteria, custom rules, and
    per-tenant configurations. Provides monitoring and alerting for
    unusual routing patterns.

    Features:
    - Financial threshold-based routing
    - Risk level assessment
    - Compliance requirement detection
    - Explicit user intent recognition
    - Multi-stakeholder decision detection
    - Per-tenant configuration
    - Action category defaults
    - Custom rule evaluation
    - Routing metrics and analytics
    - Anomaly detection and alerting

    Example:
        >>> router = DecisionRouter(
        ...     criteria=RoutingCriteria(
        ...         financial_threshold=10000.0,
        ...         risk_levels={"high", "critical"},
        ...     ),
        ... )
        >>> decision = await router.route(
        ...     {"action": "transfer", "amount": 50000},
        ...     context={"tenant_id": "acme-corp"},
        ... )
        >>> print(decision.destination)
        RouteDestination.DEBATE
    """

    def __init__(
        self,
        criteria: RoutingCriteria | None = None,
        default_destination: RouteDestination = RouteDestination.EXECUTE,
        category_configs: dict[ActionCategory, CategoryDefaults] | None = None,
        enable_audit: bool = True,
        anomaly_detector: AnomalyDetectorProtocol | None = None,
        alert_handler: AlertHandlerProtocol | None = None,
        max_audit_entries: int = 10000,
    ) -> None:
        """
        Initialize the decision router.

        Args:
            criteria: Global routing criteria.
            default_destination: Default route when no criteria match.
            category_configs: Override default category configurations.
            enable_audit: Whether to enable audit logging.
            anomaly_detector: Optional anomaly detector for pattern analysis.
            alert_handler: Optional handler for routing alerts.
            max_audit_entries: Maximum audit entries to retain.
        """
        self._criteria = criteria or RoutingCriteria()
        self._default_destination = default_destination
        self._enable_audit = enable_audit
        self._anomaly_detector = anomaly_detector
        self._alert_handler = alert_handler
        self._max_audit_entries = max_audit_entries

        # Category configurations
        self._category_configs = dict(DEFAULT_CATEGORY_CONFIGS)
        if category_configs:
            self._category_configs.update(category_configs)

        # Custom rules and tenant configs
        self._rules: dict[str, RoutingRule] = {}
        self._tenant_configs: dict[str, TenantRoutingConfig] = {}

        # Metrics and audit
        self._metrics = RoutingMetrics()
        self._tenant_metrics: dict[str, RoutingMetrics] = defaultdict(RoutingMetrics)
        self._audit_log: list[RoutingAuditEntry] = []
        self._lock = asyncio.Lock()

        # Event callbacks
        self._event_handlers: list[Callable[[RoutingAuditEntry], Any]] = []

        # Request counter for generating IDs
        self._request_counter = 0

        logger.info(
            "DecisionRouter initialized with default=%s, financial_threshold=%s",
            default_destination.value,
            self._criteria.financial_threshold,
        )

    # =========================================================================
    # Rule Management
    # =========================================================================

    def add_rule(self, rule: RoutingRule) -> None:
        """
        Add a custom routing rule.

        Args:
            rule: Routing rule to add.
        """
        self._rules[rule.rule_id] = rule
        logger.debug("Added routing rule: %s -> %s", rule.rule_id, rule.destination.value)

    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a routing rule by ID.

        Args:
            rule_id: Rule identifier.

        Returns:
            True if rule was removed, False if not found.
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            logger.debug("Removed routing rule: %s", rule_id)
            return True
        return False

    def get_rule(self, rule_id: str) -> RoutingRule | None:
        """
        Get a routing rule by ID.

        Args:
            rule_id: Rule identifier.

        Returns:
            RoutingRule or None if not found.
        """
        return self._rules.get(rule_id)

    def list_rules(self) -> list[RoutingRule]:
        """
        List all routing rules sorted by priority.

        Returns:
            List of routing rules.
        """
        rules = list(self._rules.values())
        rules.sort(key=lambda r: -r.priority)
        return rules

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a routing rule."""
        if rule_id in self._rules:
            self._rules[rule_id].enabled = True
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a routing rule."""
        if rule_id in self._rules:
            self._rules[rule_id].enabled = False
            return True
        return False

    # =========================================================================
    # Tenant Configuration
    # =========================================================================

    async def add_tenant_config(self, config: TenantRoutingConfig) -> None:
        """
        Add or update tenant-specific routing configuration.

        Args:
            config: Tenant routing configuration.
        """
        async with self._lock:
            self._tenant_configs[config.tenant_id] = config
            logger.info("Added tenant routing config for %s", config.tenant_id)

    async def remove_tenant_config(self, tenant_id: str) -> bool:
        """
        Remove tenant routing configuration.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            True if config was removed, False if not found.
        """
        async with self._lock:
            if tenant_id in self._tenant_configs:
                del self._tenant_configs[tenant_id]
                logger.info("Removed tenant routing config for %s", tenant_id)
                return True
            return False

    def get_tenant_config(self, tenant_id: str) -> TenantRoutingConfig | None:
        """
        Get tenant routing configuration.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            TenantRoutingConfig or None if not found.
        """
        return self._tenant_configs.get(tenant_id)

    def list_tenant_configs(self) -> list[TenantRoutingConfig]:
        """
        List all tenant routing configurations.

        Returns:
            List of tenant configurations.
        """
        return list(self._tenant_configs.values())

    # =========================================================================
    # Routing Decision
    # =========================================================================

    async def route(
        self,
        request: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> RouteDecision:
        """
        Route a request to the appropriate destination.

        Evaluates routing criteria, custom rules, and tenant configurations
        to determine the optimal destination for the request.

        Args:
            request: Request data containing action details.
            context: Optional context (tenant_id, user_id, etc.).

        Returns:
            RouteDecision with destination and reasoning.
        """
        start_time = time.time()
        context = context or {}

        # Generate request ID
        self._request_counter += 1
        request_id = f"route-{self._request_counter:08d}-{int(start_time * 1000) % 1000000}"

        tenant_id = context.get("tenant_id")
        action_category = self._extract_action_category(request)

        # Get effective criteria (tenant override or global)
        criteria = self._criteria
        tenant_config = self._tenant_configs.get(tenant_id) if tenant_id else None
        if tenant_config:
            criteria = tenant_config.criteria

        # Collect matched criteria
        matched_criteria: list[str] = []
        matched_rule_id: str | None = None

        # 1. Check for explicit user intent
        decision = self._check_explicit_intent(request, criteria, matched_criteria)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.CRITERIA_MATCHED)
            return decision

        # 2. Evaluate custom rules (highest priority first)
        decision, matched_rule_id = await self._evaluate_rules(request, tenant_id, action_category)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.RULE_MATCHED)
            return decision

        # 3. Check financial threshold
        decision = self._check_financial_threshold(request, criteria, matched_criteria)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.CRITERIA_MATCHED)
            return decision

        # 4. Check risk level
        decision = self._check_risk_level(request, criteria, matched_criteria)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.CRITERIA_MATCHED)
            return decision

        # 5. Check compliance requirements
        decision = self._check_compliance(request, criteria, matched_criteria)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.CRITERIA_MATCHED)
            return decision

        # 6. Check stakeholder count
        decision = self._check_stakeholders(request, criteria, matched_criteria)
        if decision:
            decision.request_id = request_id
            decision.decision_time_ms = (time.time() - start_time) * 1000
            await self._record_decision(decision, tenant_id, RoutingEventType.CRITERIA_MATCHED)
            return decision

        # 7. Use category default or global default
        decision = self._get_default_decision(action_category, tenant_config, matched_criteria)
        decision.request_id = request_id
        decision.decision_time_ms = (time.time() - start_time) * 1000
        await self._record_decision(decision, tenant_id, RoutingEventType.DEFAULT_ROUTE)

        return decision

    def _check_explicit_intent(
        self,
        request: dict[str, Any],
        criteria: RoutingCriteria,
        matched_criteria: list[str],
    ) -> RouteDecision | None:
        """Check for explicit user intent in request content."""
        content = str(request.get("content", "")).lower()
        description = str(request.get("description", "")).lower()
        text = f"{content} {description}"

        # Check for debate keywords
        for keyword in criteria.require_debate_keywords:
            if keyword.lower() in text:
                matched_criteria.append(f"explicit_debate_keyword:{keyword}")
                return RouteDecision(
                    destination=RouteDestination.DEBATE,
                    reason=f"User explicitly requested debate (keyword: '{keyword}')",
                    criteria_matched=list(matched_criteria),
                    confidence=0.95,
                )

        # Check for execute keywords
        for keyword in criteria.require_execute_keywords:
            if keyword.lower() in text:
                matched_criteria.append(f"explicit_execute_keyword:{keyword}")
                return RouteDecision(
                    destination=RouteDestination.EXECUTE,
                    reason=f"User explicitly requested execution (keyword: '{keyword}')",
                    criteria_matched=list(matched_criteria),
                    confidence=0.95,
                )

        # Check explicit routing request
        explicit_route = request.get("route_to") or request.get("destination")
        if explicit_route:
            try:
                destination = RouteDestination(explicit_route)
                matched_criteria.append(f"explicit_destination:{explicit_route}")
                return RouteDecision(
                    destination=destination,
                    reason=f"Explicit routing request to {explicit_route}",
                    criteria_matched=list(matched_criteria),
                    confidence=1.0,
                )
            except ValueError as e:
                logger.debug("decision_router operation failed: %s", e)

        return None

    async def _evaluate_rules(
        self,
        request: dict[str, Any],
        tenant_id: str | None,
        action_category: ActionCategory | None,
    ) -> tuple[RouteDecision | None, str | None]:
        """Evaluate custom routing rules."""
        # Combine global rules with tenant-specific rules
        all_rules = list(self._rules.values())

        if tenant_id:
            tenant_config = self._tenant_configs.get(tenant_id)
            if tenant_config:
                all_rules.extend(tenant_config.override_rules)

        # Sort by priority (highest first)
        all_rules.sort(key=lambda r: -r.priority)

        for rule in all_rules:
            if not rule.enabled:
                continue

            # Check tenant restriction
            if rule.tenant_id and rule.tenant_id != tenant_id:
                continue

            # Check category restriction
            if rule.action_categories:
                if action_category and action_category not in rule.action_categories:
                    if str(action_category.value) not in {str(c) for c in rule.action_categories}:
                        continue

            # Evaluate condition
            try:
                if rule.condition(request):
                    return (
                        RouteDecision(
                            destination=rule.destination,
                            reason=rule.reason or f"Matched rule: {rule.rule_id}",
                            criteria_matched=[f"rule:{rule.rule_id}"],
                            rule_id=rule.rule_id,
                            confidence=0.9,
                            metadata=rule.metadata,
                        ),
                        rule.rule_id,
                    )
            except (RuntimeError, ValueError, KeyError, TypeError) as e:  # noqa: BLE001 - user-provided rule condition callback
                logger.warning("Error evaluating rule %s: %s", rule.rule_id, e)
                continue

        return None, None

    def _check_financial_threshold(
        self,
        request: dict[str, Any],
        criteria: RoutingCriteria,
        matched_criteria: list[str],
    ) -> RouteDecision | None:
        """Check if request exceeds financial threshold."""
        amount = request.get("amount", 0)
        if not isinstance(amount, (int, float)):
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0

        if amount > criteria.financial_threshold:
            matched_criteria.append(f"financial_threshold:{amount}>{criteria.financial_threshold}")
            return RouteDecision(
                destination=RouteDestination.DEBATE,
                reason=(
                    f"Financial amount ${amount:,.2f} exceeds threshold "
                    f"${criteria.financial_threshold:,.2f}"
                ),
                criteria_matched=list(matched_criteria),
                confidence=0.95,
                metadata={"amount": amount, "threshold": criteria.financial_threshold},
            )

        return None

    def _check_risk_level(
        self,
        request: dict[str, Any],
        criteria: RoutingCriteria,
        matched_criteria: list[str],
    ) -> RouteDecision | None:
        """Check if request risk level requires debate."""
        risk_level = request.get("risk_level", request.get("risk"))
        if not risk_level:
            return None

        # Normalize to RiskLevel enum
        try:
            if isinstance(risk_level, str):
                risk_level = RiskLevel(risk_level.lower())
        except ValueError:
            return None

        # Check against criteria risk levels
        if risk_level in criteria.risk_levels or risk_level.value in {
            str(r.value) if isinstance(r, RiskLevel) else str(r) for r in criteria.risk_levels
        }:
            matched_criteria.append(f"risk_level:{risk_level.value}")
            return RouteDecision(
                destination=RouteDestination.DEBATE,
                reason=f"Risk level '{risk_level.value}' requires debate consensus",
                criteria_matched=list(matched_criteria),
                confidence=0.9,
                metadata={"risk_level": risk_level.value},
            )

        return None

    def _check_compliance(
        self,
        request: dict[str, Any],
        criteria: RoutingCriteria,
        matched_criteria: list[str],
    ) -> RouteDecision | None:
        """Check if request has compliance requirements triggering debate."""
        compliance_flags = request.get("compliance_flags", [])
        if isinstance(compliance_flags, str):
            compliance_flags = [compliance_flags]

        # Also check for compliance in tags or labels
        tags = request.get("tags", []) + request.get("labels", [])
        if isinstance(tags, str):
            tags = [tags]

        all_flags = set(str(f).lower() for f in compliance_flags + tags)
        matched_flags = all_flags & {f.lower() for f in criteria.compliance_flags}

        if matched_flags:
            matched_criteria.append(f"compliance_flags:{','.join(matched_flags)}")
            return RouteDecision(
                destination=RouteDestination.DEBATE,
                reason=f"Compliance requirements detected: {', '.join(matched_flags)}",
                criteria_matched=list(matched_criteria),
                confidence=0.92,
                metadata={"compliance_flags": list(matched_flags)},
            )

        return None

    def _check_stakeholders(
        self,
        request: dict[str, Any],
        criteria: RoutingCriteria,
        matched_criteria: list[str],
    ) -> RouteDecision | None:
        """Check if request involves multiple stakeholders requiring debate."""
        stakeholders = request.get("stakeholders", [])
        if isinstance(stakeholders, str):
            stakeholders = [s.strip() for s in stakeholders.split(",")]

        stakeholder_count = len(stakeholders)

        # Also check for approvers or reviewers
        approvers = request.get("approvers", [])
        reviewers = request.get("reviewers", [])
        if approvers:
            stakeholder_count += len(approvers) if isinstance(approvers, list) else 1
        if reviewers:
            stakeholder_count += len(reviewers) if isinstance(reviewers, list) else 1

        if stakeholder_count >= criteria.stakeholder_threshold:
            matched_criteria.append(
                f"stakeholder_count:{stakeholder_count}>={criteria.stakeholder_threshold}"
            )
            return RouteDecision(
                destination=RouteDestination.DEBATE,
                reason=(
                    f"Multi-stakeholder decision ({stakeholder_count} stakeholders) "
                    f"requires debate consensus"
                ),
                criteria_matched=list(matched_criteria),
                confidence=0.88,
                metadata={"stakeholder_count": stakeholder_count},
            )

        return None

    def _get_default_decision(
        self,
        action_category: ActionCategory | None,
        tenant_config: TenantRoutingConfig | None,
        matched_criteria: list[str],
    ) -> RouteDecision:
        """Get default routing decision based on category or global default."""
        # Check category default
        if action_category and action_category in self._category_configs:
            category_config = self._category_configs[action_category]
            matched_criteria.append(f"category_default:{action_category.value}")
            return RouteDecision(
                destination=category_config.default_destination,
                reason=f"Default routing for {action_category.value} category",
                criteria_matched=list(matched_criteria),
                confidence=0.7,
                metadata={"category": action_category.value},
            )

        # Use tenant default if available
        if tenant_config:
            matched_criteria.append(f"tenant_default:{tenant_config.tenant_id}")
            return RouteDecision(
                destination=tenant_config.default_destination,
                reason=f"Tenant default routing for {tenant_config.tenant_id}",
                criteria_matched=list(matched_criteria),
                confidence=0.6,
            )

        # Use global default
        matched_criteria.append("global_default")
        return RouteDecision(
            destination=self._default_destination,
            reason="No specific criteria matched, using default routing",
            criteria_matched=list(matched_criteria),
            confidence=0.5,
        )

    def _extract_action_category(
        self,
        request: dict[str, Any],
    ) -> ActionCategory | None:
        """Extract action category from request."""
        # Explicit category
        category = request.get("category") or request.get("action_category")
        if category:
            try:
                if isinstance(category, ActionCategory):
                    return category
                return ActionCategory(category.lower())
            except ValueError as e:
                logger.debug("extract action category encountered an error: %s", e)

        # Infer from action type
        action = str(request.get("action", "") or request.get("action_type", "")).lower()

        # Financial keywords
        if any(kw in action for kw in ["transfer", "payment", "invoice", "budget", "expense"]):
            return ActionCategory.FINANCIAL

        # Compliance keywords
        if any(kw in action for kw in ["audit", "report", "policy", "regulation"]):
            return ActionCategory.COMPLIANCE

        # Security keywords
        if any(kw in action for kw in ["security", "access", "permission", "auth"]):
            return ActionCategory.SECURITY

        # Infrastructure keywords
        if any(kw in action for kw in ["deploy", "server", "database", "infrastructure"]):
            return ActionCategory.INFRASTRUCTURE

        # Data management keywords
        if any(kw in action for kw in ["data", "backup", "restore", "migrate", "export"]):
            return ActionCategory.DATA_MANAGEMENT

        # User management keywords
        if any(kw in action for kw in ["user", "account", "profile", "role"]):
            return ActionCategory.USER_MANAGEMENT

        return ActionCategory.GENERAL

    # =========================================================================
    # Recording and Metrics
    # =========================================================================

    async def _record_decision(
        self,
        decision: RouteDecision,
        tenant_id: str | None,
        event_type: RoutingEventType,
    ) -> None:
        """Record routing decision for metrics and audit."""
        async with self._lock:
            # Update global metrics
            self._metrics.total_requests += 1
            self._update_destination_count(self._metrics, decision.destination)
            self._update_avg_decision_time(self._metrics, decision.decision_time_ms)

            for criterion in decision.criteria_matched:
                self._metrics.criteria_matches[criterion] += 1

            if decision.rule_id:
                self._metrics.rule_matches[decision.rule_id] += 1

            # Update tenant metrics
            if tenant_id:
                tenant_metrics = self._tenant_metrics[tenant_id]
                tenant_metrics.total_requests += 1
                self._update_destination_count(tenant_metrics, decision.destination)
                self._update_avg_decision_time(tenant_metrics, decision.decision_time_ms)

                for criterion in decision.criteria_matched:
                    tenant_metrics.criteria_matches[criterion] += 1

                if decision.rule_id:
                    tenant_metrics.rule_matches[decision.rule_id] += 1

            # Check for anomalies
            if self._anomaly_detector:
                is_anomaly, description = self._anomaly_detector.check_anomaly(
                    tenant_id,
                    decision.destination,
                    self._tenant_metrics.get(tenant_id, self._metrics)
                    if tenant_id
                    else self._metrics,
                )
                if is_anomaly:
                    await self._handle_anomaly(tenant_id, decision, description)

            # Audit logging
            if self._enable_audit:
                entry = RoutingAuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    event_type=event_type,
                    request_id=decision.request_id,
                    tenant_id=tenant_id,
                    decision=decision,
                    metadata={
                        "destination": decision.destination.value,
                        "criteria_matched": decision.criteria_matched,
                    },
                )
                self._audit_log.append(entry)

                # Keep audit log bounded
                if len(self._audit_log) > self._max_audit_entries:
                    self._audit_log = self._audit_log[-self._max_audit_entries :]

                # Notify event handlers
                for handler in self._event_handlers:
                    try:
                        result = handler(entry)
                        if asyncio.iscoroutine(result):
                            await result
                    except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event handler callback
                        logger.error("Event handler error: %s", e)

        logger.debug(
            "Routed %s to %s (reason: %s...)",
            decision.request_id,
            decision.destination.value,
            decision.reason[:50],
        )

    def _update_destination_count(
        self,
        metrics: RoutingMetrics,
        destination: RouteDestination,
    ) -> None:
        """Update destination count in metrics."""
        if destination == RouteDestination.DEBATE:
            metrics.debate_routes += 1
        elif destination == RouteDestination.EXECUTE:
            metrics.execute_routes += 1
        elif destination in (
            RouteDestination.HYBRID_DEBATE_THEN_EXECUTE,
            RouteDestination.HYBRID_EXECUTE_WITH_VALIDATION,
        ):
            metrics.hybrid_routes += 1
        elif destination == RouteDestination.REJECT:
            metrics.rejected_routes += 1

    def _update_avg_decision_time(
        self,
        metrics: RoutingMetrics,
        decision_time_ms: float,
    ) -> None:
        """Update average decision time in metrics."""
        total = metrics.total_requests
        if total <= 1:
            metrics.avg_decision_time_ms = decision_time_ms
        else:
            # Running average
            metrics.avg_decision_time_ms = (
                metrics.avg_decision_time_ms * (total - 1) + decision_time_ms
            ) / total

    async def _handle_anomaly(
        self,
        tenant_id: str | None,
        decision: RouteDecision,
        description: str,
    ) -> None:
        """Handle detected routing anomaly."""
        logger.warning("Routing anomaly detected for tenant=%s: %s", tenant_id, description)

        if self._enable_audit:
            entry = RoutingAuditEntry(
                timestamp=datetime.now(timezone.utc),
                event_type=RoutingEventType.ANOMALY_DETECTED,
                request_id=decision.request_id,
                tenant_id=tenant_id,
                decision=decision,
                metadata={"anomaly_description": description},
            )
            self._audit_log.append(entry)

        if self._alert_handler:
            try:
                await self._alert_handler.send_alert(
                    alert_type="routing_anomaly",
                    message=f"Unusual routing pattern detected: {description}",
                    severity="warning",
                    metadata={
                        "tenant_id": tenant_id,
                        "request_id": decision.request_id,
                        "destination": decision.destination.value,
                    },
                )
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.error("Failed to send anomaly alert: %s", e)

    # =========================================================================
    # Metrics and Monitoring
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """
        Get global routing metrics.

        Returns:
            Dictionary of routing metrics.
        """
        return self._metrics.to_dict()

    def get_tenant_metrics(self, tenant_id: str) -> dict[str, Any] | None:
        """
        Get routing metrics for a specific tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Dictionary of tenant metrics or None if not found.
        """
        if tenant_id in self._tenant_metrics:
            return self._tenant_metrics[tenant_id].to_dict()
        return None

    def get_all_tenant_metrics(self) -> dict[str, dict[str, Any]]:
        """
        Get routing metrics for all tenants.

        Returns:
            Dictionary of tenant_id to metrics.
        """
        return {tenant_id: metrics.to_dict() for tenant_id, metrics in self._tenant_metrics.items()}

    def get_debate_vs_execute_ratio(
        self,
        tenant_id: str | None = None,
    ) -> dict[str, float]:
        """
        Get the ratio of debate to execution routing.

        Args:
            tenant_id: Optional tenant to filter.

        Returns:
            Dictionary with debate_ratio and execute_ratio.
        """
        if tenant_id:
            metrics = self._tenant_metrics.get(tenant_id)
            if not metrics:
                return {"debate_ratio": 0.0, "execute_ratio": 0.0}
        else:
            metrics = self._metrics

        total = metrics.total_requests or 1
        return {
            "debate_ratio": metrics.debate_routes / total,
            "execute_ratio": metrics.execute_routes / total,
            "hybrid_ratio": metrics.hybrid_routes / total,
        }

    async def get_audit_log(
        self,
        tenant_id: str | None = None,
        event_type: RoutingEventType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get routing audit log entries.

        Args:
            tenant_id: Filter by tenant.
            event_type: Filter by event type.
            since: Filter entries after this timestamp.
            limit: Maximum entries to return.

        Returns:
            List of audit entries as dictionaries.
        """
        entries = self._audit_log

        if tenant_id:
            entries = [e for e in entries if e.tenant_id == tenant_id]
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Return most recent entries
        entries = entries[-limit:]

        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "event_type": e.event_type.value,
                "request_id": e.request_id,
                "tenant_id": e.tenant_id,
                "decision": e.decision.to_dict() if e.decision else None,
                **e.metadata,
            }
            for e in entries
        ]

    def add_event_handler(
        self,
        handler: Callable[[RoutingAuditEntry], Any],
    ) -> None:
        """
        Add an event handler for routing audit events.

        Args:
            handler: Callback function receiving RoutingAuditEntry.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(
        self,
        handler: Callable[[RoutingAuditEntry], Any],
    ) -> None:
        """
        Remove an event handler.

        Args:
            handler: Handler to remove.
        """
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    # =========================================================================
    # Configuration Updates
    # =========================================================================

    def update_criteria(self, criteria: RoutingCriteria) -> None:
        """
        Update global routing criteria.

        Args:
            criteria: New routing criteria.
        """
        self._criteria = criteria
        logger.info(
            "Updated routing criteria: financial_threshold=%s", criteria.financial_threshold
        )

    def update_category_config(
        self,
        category: ActionCategory,
        config: CategoryDefaults,
    ) -> None:
        """
        Update configuration for an action category.

        Args:
            category: Action category.
            config: New category configuration.
        """
        self._category_configs[category] = config
        logger.info(
            "Updated category config: %s -> %s", category.value, config.default_destination.value
        )

    def set_default_destination(self, destination: RouteDestination) -> None:
        """
        Set the default routing destination.

        Args:
            destination: New default destination.
        """
        self._default_destination = destination
        logger.info("Updated default destination: %s", destination.value)

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """
        Get router statistics.

        Returns:
            Dictionary of router statistics.
        """
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            "tenant_configs": len(self._tenant_configs),
            "category_configs": len(self._category_configs),
            "metrics": self._metrics.to_dict(),
            "audit_entries": len(self._audit_log),
            "audit_enabled": self._enable_audit,
            "default_destination": self._default_destination.value,
            "financial_threshold": self._criteria.financial_threshold,
        }


# =============================================================================
# Simple Anomaly Detector Implementation
# =============================================================================


class SimpleAnomalyDetector:
    """
    Simple anomaly detector for routing patterns.

    Detects unusual routing patterns based on configurable thresholds.
    """

    def __init__(
        self,
        debate_ratio_high_threshold: float = 0.9,
        debate_ratio_low_threshold: float = 0.1,
        min_samples: int = 100,
    ) -> None:
        """
        Initialize anomaly detector.

        Args:
            debate_ratio_high_threshold: Alert if debate ratio exceeds this.
            debate_ratio_low_threshold: Alert if debate ratio falls below this.
            min_samples: Minimum samples before anomaly detection activates.
        """
        self.debate_ratio_high_threshold = debate_ratio_high_threshold
        self.debate_ratio_low_threshold = debate_ratio_low_threshold
        self.min_samples = min_samples

    def check_anomaly(
        self,
        tenant_id: str | None,
        destination: RouteDestination,
        metrics: RoutingMetrics,
    ) -> tuple[bool, str]:
        """Check if routing pattern is anomalous."""
        if metrics.total_requests < self.min_samples:
            return False, ""

        total = metrics.total_requests
        debate_ratio = metrics.debate_routes / total

        if debate_ratio > self.debate_ratio_high_threshold:
            return (
                True,
                f"Unusually high debate routing ratio: {debate_ratio:.2%} "
                f"(threshold: {self.debate_ratio_high_threshold:.2%})",
            )

        if debate_ratio < self.debate_ratio_low_threshold:
            return (
                True,
                f"Unusually low debate routing ratio: {debate_ratio:.2%} "
                f"(threshold: {self.debate_ratio_low_threshold:.2%})",
            )

        return False, ""


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Enums
    "RouteDestination",
    "RiskLevel",
    "ActionCategory",
    "RoutingEventType",
    # Data classes
    "RoutingCriteria",
    "RouteDecision",
    "RoutingRule",
    "TenantRoutingConfig",
    "CategoryDefaults",
    "RoutingMetrics",
    "RoutingAuditEntry",
    # Protocols
    "AnomalyDetectorProtocol",
    "AlertHandlerProtocol",
    # Core class
    "DecisionRouter",
    # Utilities
    "SimpleAnomalyDetector",
    "DEFAULT_CATEGORY_CONFIGS",
]
