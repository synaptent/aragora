"""
Policy Engine - The core of Aragora's trust infrastructure.

The policy engine enforces per-tool and per-task policies, ensuring that
agent actions are bounded, auditable, and reversible. This is the foundation
for enterprise trust.

Key concepts:
- Policies: Rules that govern what agents can do
- Actions: Specific invocations of tool capabilities
- Risk Budgets: Limits on cumulative risk per session
- Escalation: When actions need human approval

Usage:
    engine = PolicyEngine()

    # Check if action is allowed
    result = engine.check_action(
        agent="claude",
        tool="file_writer",
        capability="write_file",
        context={"file_path": "src/core.py"},
    )

    if result.allowed:
        # Proceed with action
        pass
    elif result.requires_human_approval:
        # Escalate to human
        await request_approval(result)
    else:
        # Action denied
        raise PolicyViolation(result.reason)
"""

from __future__ import annotations

import ast
import logging
import operator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections.abc import Callable
from typing import Any, TypeAlias

from aragora.policy.risk import RiskBudget
from aragora.policy.tools import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

PolicyPrimitive: TypeAlias = bool | int | float | str | None
PolicyValue: TypeAlias = PolicyPrimitive | list["PolicyValue"] | tuple["PolicyValue", ...]
PolicyContext: TypeAlias = dict[str, PolicyValue]
AuditEntry: TypeAlias = dict[str, object]


# Safe operators for AST-based policy condition evaluation
# Maps AST operator types to their Python implementations
def _contains(left: Any, right: Any) -> bool:
    return left in right


def _not_contains(left: Any, right: Any) -> bool:
    return left not in right


_SAFE_COMPARISON_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: _contains,
    ast.NotIn: _not_contains,
}


class PolicyDecision(Enum):
    """The outcome of a policy check."""

    ALLOW = "allow"  # Action is permitted
    DENY = "deny"  # Action is forbidden
    ESCALATE = "escalate"  # Requires human approval
    BUDGET_EXCEEDED = "budget_exceeded"  # Risk budget exceeded


@dataclass
class PolicyResult:
    """Result of a policy check.

    Contains the decision, reasoning, and any required escalation info.
    """

    decision: PolicyDecision
    allowed: bool  # Convenience: decision == ALLOW
    reason: str
    requires_human_approval: bool = False

    # Cost information
    risk_cost: float = 0.0
    budget_remaining: float = 0.0

    # Context for escalation
    agent: str = ""
    tool: str = ""
    capability: str = ""
    context: PolicyContext = field(default_factory=dict)

    # Timestamps
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PolicyViolation(Exception):
    """Raised when a policy check fails."""

    def __init__(self, result: PolicyResult):
        self.result = result
        super().__init__(f"Policy violation: {result.reason}")


@dataclass
class Policy:
    """A policy rule that governs agent actions.

    Policies can:
    - Allow/deny specific tools or capabilities
    - Require human approval for certain actions
    - Set limits on action frequency
    - Define context-specific rules
    """

    name: str
    description: str

    # What this policy applies to
    agents: list[str] = field(default_factory=list)  # Empty = all agents
    tools: list[str] = field(default_factory=list)  # Empty = all tools
    capabilities: list[str] = field(default_factory=list)  # Empty = all capabilities

    # Actions
    allow: bool = True
    require_human_approval: bool = False
    risk_multiplier: float = 1.0

    # Conditions (Python expressions evaluated with context)
    conditions: list[str] = field(default_factory=list)

    # Rate limiting
    max_uses_per_minute: int | None = None
    max_uses_per_session: int | None = None

    # Priority (higher = evaluated first)
    priority: int = 0

    # Metadata
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def matches(
        self,
        agent: str,
        tool: str,
        capability: str,
        context: PolicyContext,
    ) -> bool:
        """Check if this policy applies to the given action."""
        if not self.enabled:
            return False

        # Check agent match
        if self.agents and agent not in self.agents:
            return False

        # Check tool match
        if self.tools and tool not in self.tools:
            return False

        # Check capability match
        if self.capabilities and capability not in self.capabilities:
            return False

        # Check conditions
        for condition in self.conditions:
            try:
                if not self._eval_condition(condition, context):
                    return False
            except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
                logger.warning("Policy condition '%s' failed: %s", condition, e)
                return False

        return True

    def _eval_condition(self, condition: str, context: PolicyContext) -> bool:
        """Safely evaluate a condition expression using AST parsing.

        This replaces eval() with a secure AST-based evaluator that only
        supports comparison operators, boolean logic, and variable access.
        Attribute access and method calls are explicitly blocked.

        Supported expressions:
        - Comparisons: x == 1, y != "foo", z < 10
        - Membership: x in ["a", "b"], y not in allowed_list
        - Boolean: x == 1 and y == 2, x or y
        - Negation: not x, not (x == 1)
        """
        try:
            tree = ast.parse(condition, mode="eval")
            return bool(self._eval_node(tree.body, context))
        except (SyntaxError, ValueError, TypeError, KeyError):
            return False

    def _eval_node(self, node: ast.AST, context: PolicyContext) -> PolicyValue:
        """Recursively evaluate AST nodes safely.

        Explicitly blocks:
        - Attribute access (node.attr)
        - Method calls
        - Subscript operations beyond simple list access
        - Lambda and function definitions
        """
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                op_func = _SAFE_COMPARISON_OPS.get(type(op))
                if op_func is None:
                    raise ValueError(f"Unsupported operator: {type(op).__name__}")
                if not op_func(left, right):
                    return False
                left = right
            return True

        elif isinstance(node, ast.Name):
            # Only allow access to context variables, not builtins
            if node.id in context:
                return context[node.id]
            # Allow True/False/None as literals
            if node.id == "True":
                return True
            if node.id == "False":
                return False
            if node.id == "None":
                return None
            raise ValueError(f"Unknown variable: {node.id}")

        elif isinstance(node, ast.Constant):
            # Allow literal values (str, int, float, None, bool)
            if isinstance(node.value, (str, int, float, bool)) or node.value is None:
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")

        elif isinstance(node, ast.List):
            # Allow list literals for "in" checks
            return [self._eval_node(elt, context) for elt in node.elts]

        elif isinstance(node, ast.Tuple):
            # Allow tuple literals
            return tuple(self._eval_node(elt, context) for elt in node.elts)

        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._eval_node(v, context) for v in node.values)
            elif isinstance(node.op, ast.Or):
                return any(self._eval_node(v, context) for v in node.values)
            raise ValueError(f"Unsupported boolean operator: {type(node.op).__name__}")

        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not self._eval_node(node.operand, context)
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

        # Explicitly block dangerous node types
        elif isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            raise ValueError(f"Blocked node type for security: {type(node).__name__}")

        raise ValueError(f"Unsupported node type: {type(node).__name__}")


class PolicyEngine:
    """The policy enforcement engine.

    Evaluates policies and risk budgets to decide if actions are allowed.
    This is the gatekeeper for all agent tool usage.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        default_budget: RiskBudget | None = None,
    ):
        self.tool_registry = tool_registry or get_tool_registry()
        self.policies: list[Policy] = []
        self._budgets: dict[str, RiskBudget] = {}  # session_id -> budget
        self._default_budget_config = default_budget or RiskBudget()

        # Action tracking for rate limiting
        self._action_counts: dict[str, dict[str, int]] = {}  # agent -> capability -> count
        self._action_timestamps: dict[str, list[datetime]] = {}  # capability -> timestamps

        # Audit log
        self._audit_log: list[AuditEntry] = []

    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the engine."""
        self.policies.append(policy)
        # Sort by priority (descending)
        self.policies.sort(key=lambda p: -p.priority)
        logger.info("Added policy '%s' (priority: %s)", policy.name, policy.priority)

    def remove_policy(self, name: str) -> bool:
        """Remove a policy by name."""
        original_count = len(self.policies)
        self.policies = [p for p in self.policies if p.name != name]
        removed = len(self.policies) < original_count
        if removed:
            logger.info("Removed policy '%s'", name)
        return removed

    def get_budget(self, session_id: str) -> RiskBudget:
        """Get or create a risk budget for a session."""
        if session_id not in self._budgets:
            self._budgets[session_id] = RiskBudget(
                total=self._default_budget_config.total,
                human_approval_threshold=self._default_budget_config.human_approval_threshold,
                max_single_action=self._default_budget_config.max_single_action,
            )
        return self._budgets[session_id]

    def check_action(
        self,
        agent: str,
        tool: str,
        capability: str,
        context: PolicyContext | None = None,
        session_id: str = "default",
    ) -> PolicyResult:
        """Check if an action is allowed by policy.

        This is the main entry point for policy enforcement.

        Args:
            agent: The agent attempting the action
            tool: The tool being used
            capability: The specific capability being invoked
            context: Additional context (file paths, parameters, etc.)
            session_id: Session identifier for budget tracking

        Returns:
            PolicyResult with decision and reasoning
        """
        context = context or {}
        budget = self.get_budget(session_id)

        # Get tool and capability info
        tool_obj = self.tool_registry.get(tool)
        if not tool_obj:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                allowed=False,
                reason=f"Unknown tool: {tool}",
                agent=agent,
                tool=tool,
                capability=capability,
                context=context,
            )

        cap_obj = tool_obj.get_capability(capability)
        if not cap_obj:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                allowed=False,
                reason=f"Tool '{tool}' does not have capability '{capability}'",
                agent=agent,
                tool=tool,
                capability=capability,
                context=context,
            )

        # Calculate risk cost
        risk_cost = budget.calculate_cost(
            cap_obj.risk_level,
            cap_obj.blast_radius,
            tool_obj.cost_multiplier,
        )

        # Check policies (first match wins due to priority sorting)
        for policy in self.policies:
            if policy.matches(agent, tool, capability, context):
                # Apply policy multiplier to risk
                risk_cost *= policy.risk_multiplier

                if not policy.allow:
                    result = PolicyResult(
                        decision=PolicyDecision.DENY,
                        allowed=False,
                        reason=f"Denied by policy '{policy.name}': {policy.description}",
                        agent=agent,
                        tool=tool,
                        capability=capability,
                        context=context,
                        risk_cost=risk_cost,
                        budget_remaining=budget.remaining,
                    )
                    self._log_action(result)
                    return result

                if policy.require_human_approval:
                    result = PolicyResult(
                        decision=PolicyDecision.ESCALATE,
                        allowed=False,
                        requires_human_approval=True,
                        reason=f"Requires human approval per policy '{policy.name}'",
                        agent=agent,
                        tool=tool,
                        capability=capability,
                        context=context,
                        risk_cost=risk_cost,
                        budget_remaining=budget.remaining,
                    )
                    self._log_action(result)
                    return result

                # Policy allows - continue to budget check
                break

        # Check if capability itself requires approval
        if cap_obj.requires_human_approval or tool_obj.requires_human_approval:
            result = PolicyResult(
                decision=PolicyDecision.ESCALATE,
                allowed=False,
                requires_human_approval=True,
                reason=f"Capability '{capability}' requires human approval",
                agent=agent,
                tool=tool,
                capability=capability,
                context=context,
                risk_cost=risk_cost,
                budget_remaining=budget.remaining,
            )
            self._log_action(result)
            return result

        # Check risk budget
        if not budget.can_afford(risk_cost):
            result = PolicyResult(
                decision=PolicyDecision.BUDGET_EXCEEDED,
                allowed=False,
                reason=f"Risk budget exceeded: cost {risk_cost:.1f}, remaining {budget.remaining:.1f}",
                agent=agent,
                tool=tool,
                capability=capability,
                context=context,
                risk_cost=risk_cost,
                budget_remaining=budget.remaining,
            )
            self._log_action(result)
            return result

        # Check if budget spend would trigger approval threshold
        if not budget.can_afford_without_approval(risk_cost):
            result = PolicyResult(
                decision=PolicyDecision.ESCALATE,
                allowed=False,
                requires_human_approval=True,
                reason=f"Action would exceed human approval threshold ({budget.human_approval_threshold})",
                agent=agent,
                tool=tool,
                capability=capability,
                context=context,
                risk_cost=risk_cost,
                budget_remaining=budget.remaining,
            )
            self._log_action(result)
            return result

        # All checks passed - action is allowed
        result = PolicyResult(
            decision=PolicyDecision.ALLOW,
            allowed=True,
            reason="Action permitted",
            agent=agent,
            tool=tool,
            capability=capability,
            context=context,
            risk_cost=risk_cost,
            budget_remaining=budget.remaining - risk_cost,
        )

        # Spend budget
        budget.spend(
            risk_cost,
            f"{capability} on {context.get('file_path', 'unknown')}",
            agent=agent,
            tool=tool,
        )

        self._log_action(result)
        return result

    def record_action(
        self,
        agent: str,
        tool: str,
        capability: str,
        success: bool,
        context: PolicyContext | None = None,
        session_id: str = "default",
    ) -> None:
        """Record that an action was taken (for auditing)."""
        self._audit_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "agent": agent,
                "tool": tool,
                "capability": capability,
                "success": success,
                "context": context or {},
                "session_id": session_id,
            }
        )

    def _log_action(self, result: PolicyResult) -> None:
        """Log an action check to the audit trail."""
        self._audit_log.append(
            {
                "timestamp": result.checked_at,
                "agent": result.agent,
                "tool": result.tool,
                "capability": result.capability,
                "decision": result.decision.value,
                "allowed": result.allowed,
                "reason": result.reason,
                "risk_cost": result.risk_cost,
                "context": result.context,
            }
        )

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent audit log entries."""
        return self._audit_log[-limit:]

    def get_session_summary(self, session_id: str) -> dict[str, object]:
        """Get summary of a session's risk usage."""
        budget = self.get_budget(session_id)
        return {
            "session_id": session_id,
            "budget": budget.to_dict(),
            "actions": budget.actions,
        }


# Default policies for common scenarios
DEFAULT_POLICIES = [
    Policy(
        name="protect_core_files",
        description="Prevent modification of core Aragora files",
        tools=["file_writer"],
        capabilities=["write_file", "delete_file"],
        conditions=["'aragora/core.py' in file_path or '.nomic/constitution' in file_path"],
        allow=False,
        priority=100,
    ),
    Policy(
        name="require_approval_for_push",
        description="Require human approval for git push",
        tools=["git"],
        capabilities=["git_push"],
        require_human_approval=True,
        priority=90,
    ),
    Policy(
        name="require_approval_for_production",
        description="Require human approval for production deployments",
        tools=["code_executor"],
        capabilities=["run_shell"],
        conditions=["'deploy' in command or 'production' in command"],
        require_human_approval=True,
        priority=90,
    ),
]


def create_default_engine() -> PolicyEngine:
    """Create a policy engine with default policies."""
    engine = PolicyEngine()
    for policy in DEFAULT_POLICIES:
        engine.add_policy(policy)
    return engine


__all__ = [
    "PolicyDecision",
    "PolicyResult",
    "PolicyViolation",
    "Policy",
    "PolicyEngine",
    "DEFAULT_POLICIES",
    "create_default_engine",
]
