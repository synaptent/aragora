"""
OpenClaw Action Filter - Allowlisting and Denylisting for Actions.

Provides enterprise-grade action filtering for OpenClaw tasks with:
- Per-tenant action allowlisting (deny-by-default model)
- Pattern-based action denylisting for dangerous operations
- Risk assessment with approval workflow integration
- Comprehensive audit logging and alerting

Security Model:
- DENY BY DEFAULT: Actions must be explicitly allowed per tenant
- CRITICAL DENYLIST: Dangerous actions cannot be overridden
- RISK SCORING: Actions are scored by risk level for review/approval
- AUDIT TRAIL: All filter decisions are logged for compliance

Usage:
    from aragora.gateway.openclaw.action_filter import (
        ActionFilter,
        ActionRule,
        ActionCategory,
        RiskLevel,
    )

    # Initialize filter with tenant-specific allowlist
    filter = ActionFilter(
        tenant_id="tenant_123",
        allowed_actions={
            "browser.navigate",
            "browser.click",
            "filesystem.read",
        },
        enable_audit=True,
    )

    # Check if action is allowed
    decision = filter.check_action("filesystem.write", context={"path": "/tmp/file.txt"})
    if decision.allowed:
        # Proceed with action
        ...
    elif decision.requires_approval:
        # Request approval from authorized user
        ...
    else:
        # Action is blocked
        ...
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================


class RiskLevel(str, Enum):
    """Risk levels for action classification.

    Actions are classified by risk to determine appropriate controls:
    - LOW: Routine operations, minimal security impact
    - MEDIUM: Sensitive operations, should be monitored
    - HIGH: Potentially dangerous, requires approval
    - CRITICAL: Extremely dangerous, automatically blocked
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionCategoryType(str, Enum):
    """Categories of actions based on domain.

    Actions are grouped into categories for easier management:
    - BROWSER: Web browsing and automation
    - FILESYSTEM: File and directory operations
    - NETWORK: Network and HTTP operations
    - SYSTEM: System commands and configuration
    - DATABASE: Database queries and operations
    - CREDENTIAL: Credential and secret access
    - CODE: Code execution and evaluation
    """

    BROWSER = "browser"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    SYSTEM = "system"
    DATABASE = "database"
    CREDENTIAL = "credential"
    CODE = "code"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ActionCategory:
    """
    Category definition for grouping related actions.

    Categories provide a way to organize actions by domain and apply
    default risk levels and patterns for easier policy management.

    Attributes:
        name: Category name (e.g., "browser", "filesystem").
        description: Human-readable description of the category.
        default_risk_level: Default risk level for actions in this category.
        patterns: List of action patterns that belong to this category.
            Patterns support glob-style matching (e.g., "browser.*").
    """

    name: str
    description: str
    default_risk_level: RiskLevel = RiskLevel.MEDIUM
    patterns: list[str] = field(default_factory=list)

    def matches(self, action: str) -> bool:
        """Check if an action matches this category.

        Args:
            action: The action string to check.

        Returns:
            True if the action matches any pattern in this category.
        """
        for pattern in self.patterns:
            if fnmatch.fnmatch(action, pattern):
                return True
        return False


@dataclass
class ActionRule:
    """
    Rule for controlling action execution.

    Action rules define whether specific actions or patterns are allowed,
    blocked, or require approval. Rules are evaluated in priority order.

    Attributes:
        action_pattern: Pattern to match action names. Supports:
            - Exact match: "browser.navigate"
            - Wildcard: "browser.*"
            - Glob patterns: "filesystem.*.write"
        allowed: Whether the action is allowed (True) or blocked (False).
        risk_level: Risk level for this action.
        requires_approval: Whether the action requires human approval.
        approval_roles: Roles that can approve this action.
        description: Human-readable description of the rule.
        conditions: Additional conditions for rule evaluation.
            Keys can include: "max_per_minute", "allowed_paths", etc.
        priority: Rule priority (higher = evaluated first).
        can_override: Whether this rule can be overridden by tenant config.
            Set to False for critical security rules.
    """

    action_pattern: str
    allowed: bool = True
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    approval_roles: list[str] = field(default_factory=list)
    description: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    can_override: bool = True

    def matches(self, action: str) -> bool:
        """Check if this rule matches an action.

        Args:
            action: The action string to check.

        Returns:
            True if the action matches this rule's pattern.
        """
        # Exact match
        if self.action_pattern == action:
            return True
        # Glob pattern match
        if fnmatch.fnmatch(action, self.action_pattern):
            return True
        return False


@dataclass
class FilterDecision:
    """
    Result of an action filter check.

    Contains the decision and all relevant context for audit logging
    and approval workflow integration.

    Attributes:
        action: The action that was checked.
        allowed: Whether the action is allowed.
        reason: Human-readable explanation of the decision.
        risk_level: Assessed risk level for the action.
        risk_score: Numeric risk score (0.0 to 1.0).
        requires_approval: Whether human approval is required.
        approval_roles: Roles that can approve the action.
        matched_rule: The rule that determined the decision.
        category: Category the action belongs to.
        tenant_id: Tenant ID for the check.
        timestamp: When the decision was made (ISO format).
        context: Additional context provided for the check.
        decision_id: Unique identifier for this decision.
    """

    action: str
    allowed: bool
    reason: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_score: float = 0.5
    requires_approval: bool = False
    approval_roles: list[str] = field(default_factory=list)
    matched_rule: str | None = None
    category: str | None = None
    tenant_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        """Generate decision ID if not provided."""
        if not self.decision_id:
            # Create deterministic ID from action and timestamp
            data = f"{self.action}:{self.tenant_id}:{self.timestamp}"
            self.decision_id = hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary suitable for JSON serialization.
        """
        return {
            "decision_id": self.decision_id,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "requires_approval": self.requires_approval,
            "approval_roles": self.approval_roles,
            "matched_rule": self.matched_rule,
            "category": self.category,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp,
            "context": self.context,
        }


@dataclass
class ActionAuditEntry:
    """
    Audit log entry for action filter decisions.

    Provides a complete record of the filter decision for compliance
    and security analysis.

    Attributes:
        decision_id: ID of the filter decision.
        action: The action that was checked.
        allowed: Whether the action was allowed.
        risk_level: Assessed risk level.
        tenant_id: Tenant that requested the action.
        user_id: User who triggered the action.
        ip_address: Client IP address.
        timestamp: When the decision was made.
        matched_rule: Rule that determined the decision.
        context: Additional context from the request.
        alert_triggered: Whether an alert was triggered.
    """

    decision_id: str
    action: str
    allowed: bool
    risk_level: RiskLevel
    tenant_id: str | None = None
    user_id: str | None = None
    ip_address: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    matched_rule: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    alert_triggered: bool = False


# =============================================================================
# Default Categories
# =============================================================================

DEFAULT_CATEGORIES: dict[str, ActionCategory] = {
    ActionCategoryType.BROWSER.value: ActionCategory(
        name=ActionCategoryType.BROWSER.value,
        description="Web browser automation and navigation actions",
        default_risk_level=RiskLevel.MEDIUM,
        patterns=["browser.*", "web.*", "page.*", "dom.*"],
    ),
    ActionCategoryType.FILESYSTEM.value: ActionCategory(
        name=ActionCategoryType.FILESYSTEM.value,
        description="File and directory operations",
        default_risk_level=RiskLevel.HIGH,
        patterns=["filesystem.*", "file.*", "directory.*", "path.*"],
    ),
    ActionCategoryType.NETWORK.value: ActionCategory(
        name=ActionCategoryType.NETWORK.value,
        description="Network requests and connections",
        default_risk_level=RiskLevel.MEDIUM,
        patterns=["network.*", "http.*", "https.*", "socket.*", "fetch.*"],
    ),
    ActionCategoryType.SYSTEM.value: ActionCategory(
        name=ActionCategoryType.SYSTEM.value,
        description="System commands and shell operations",
        default_risk_level=RiskLevel.CRITICAL,
        patterns=["system.*", "shell.*", "exec.*", "process.*", "bash.*"],
    ),
    ActionCategoryType.DATABASE.value: ActionCategory(
        name=ActionCategoryType.DATABASE.value,
        description="Database queries and operations",
        default_risk_level=RiskLevel.HIGH,
        patterns=["database.*", "db.*", "sql.*", "query.*"],
    ),
    ActionCategoryType.CREDENTIAL.value: ActionCategory(
        name=ActionCategoryType.CREDENTIAL.value,
        description="Credential and secret access",
        default_risk_level=RiskLevel.CRITICAL,
        patterns=["credential.*", "secret.*", "password.*", "key.*", "token.*"],
    ),
    ActionCategoryType.CODE.value: ActionCategory(
        name=ActionCategoryType.CODE.value,
        description="Code execution and evaluation",
        default_risk_level=RiskLevel.HIGH,
        patterns=["code.*", "eval.*", "execute.*", "run.*"],
    ),
}


# =============================================================================
# Default Denylist (Critical Actions - Cannot Be Overridden)
# =============================================================================

CRITICAL_DENYLIST_RULES: list[ActionRule] = [
    # Destructive system commands
    ActionRule(
        action_pattern="system.rm_rf",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Recursive force delete - extremely destructive",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.format",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Disk formatting - irreversible data loss",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.dd",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Low-level disk write - data destruction risk",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.mkfs",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Filesystem creation - data destruction risk",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.shutdown",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="System shutdown - service disruption",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.reboot",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="System reboot - service disruption",
        can_override=False,
    ),
    # Privilege escalation
    ActionRule(
        action_pattern="system.sudo",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Sudo execution - privilege escalation",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.su",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="User switch - privilege escalation",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.chmod_777",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="World-writable permissions - security risk",
        can_override=False,
    ),
    ActionRule(
        action_pattern="system.chown_root",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Ownership change to root - privilege escalation",
        can_override=False,
    ),
    # Credential theft
    ActionRule(
        action_pattern="credential.export_all",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Bulk credential export - data exfiltration",
        can_override=False,
    ),
    ActionRule(
        action_pattern="credential.read_shadow",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Read shadow file - credential theft",
        can_override=False,
    ),
    ActionRule(
        action_pattern="credential.read_passwd",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Read passwd file - user enumeration",
        can_override=False,
    ),
    # Network attacks
    ActionRule(
        action_pattern="network.port_scan",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Port scanning - network reconnaissance",
        can_override=False,
    ),
    ActionRule(
        action_pattern="network.raw_socket",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Raw socket access - network attack capability",
        can_override=False,
    ),
    # Arbitrary code execution
    ActionRule(
        action_pattern="code.eval_arbitrary",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Arbitrary code evaluation - RCE risk",
        can_override=False,
    ),
    ActionRule(
        action_pattern="code.inject",
        allowed=False,
        risk_level=RiskLevel.CRITICAL,
        description="Code injection - security bypass",
        can_override=False,
    ),
]

# Pattern-based denylist for dangerous command patterns
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/", "Recursive force delete from root"),
    (r"rm\s+-rf\s+~", "Recursive force delete from home"),
    (r"rm\s+-rf\s+\*", "Recursive force delete with wildcard"),
    (r":\(\)\{\s*:\|:\s*&\s*\};:", "Fork bomb"),
    (r">\s*/dev/sd[a-z]", "Direct write to disk device"),
    (r"dd\s+if=.*of=/dev/sd", "DD write to disk"),
    (r"mkfs\.", "Filesystem formatting"),
    (r"format\s+[a-zA-Z]:", "Windows drive formatting"),
    (r"curl.*\|\s*sh", "Pipe URL to shell"),
    (r"wget.*\|\s*sh", "Pipe download to shell"),
    (r"curl.*\|\s*bash", "Pipe URL to bash"),
    (r"wget.*\|\s*bash", "Pipe download to bash"),
    (r"nc\s+-e", "Netcat reverse shell"),
    (r"bash\s+-i\s+>&\s+/dev/tcp", "Bash reverse shell"),
    (r"python.*-c.*socket", "Python socket execution"),
    (r"eval\s*\(\s*base64", "Base64 eval injection"),
    (r"\$\(.*\)\s*\|\s*sh", "Command substitution to shell"),
]


# =============================================================================
# Action Filter Implementation
# =============================================================================


class ActionFilter:
    """
    Action filter for OpenClaw with allowlist/denylist enforcement.

    Implements a deny-by-default security model where actions must be
    explicitly allowed per tenant. Provides risk assessment, approval
    workflows, and comprehensive audit logging.

    Security Model:
        1. Critical denylist rules are checked first (cannot be overridden)
        2. Dangerous patterns are scanned (regex-based blocking)
        3. Tenant allowlist is checked (deny by default)
        4. Risk assessment determines if approval is needed
        5. All decisions are logged for audit

    Example:
        >>> filter = ActionFilter(
        ...     tenant_id="tenant_123",
        ...     allowed_actions={"browser.navigate", "browser.click"},
        ... )
        >>> decision = filter.check_action("browser.navigate")
        >>> assert decision.allowed is True
        >>> decision = filter.check_action("system.rm_rf")
        >>> assert decision.allowed is False
        >>> assert decision.risk_level == RiskLevel.CRITICAL

    Attributes:
        tenant_id: Tenant identifier for scoped filtering.
        allowed_actions: Set of explicitly allowed actions for this tenant.
        custom_rules: List of custom action rules.
        categories: Action categories for classification.
        enable_audit: Whether to log all decisions.
        alert_callback: Callback for blocked action alerts.
    """

    def __init__(
        self,
        tenant_id: str | None = None,
        allowed_actions: set[str] | None = None,
        custom_rules: list[ActionRule] | None = None,
        categories: dict[str, ActionCategory] | None = None,
        enable_audit: bool = True,
        enable_pattern_scanning: bool = True,
        alert_callback: Callable[[FilterDecision], None] | None = None,
        high_risk_approval_roles: list[str] | None = None,
    ) -> None:
        """
        Initialize the action filter.

        Args:
            tenant_id: Tenant identifier for scoped filtering.
            allowed_actions: Set of explicitly allowed action patterns.
                Supports glob patterns (e.g., "browser.*").
            custom_rules: Additional custom rules (added to defaults).
            categories: Custom category definitions (merged with defaults).
            enable_audit: Whether to log all filter decisions.
            enable_pattern_scanning: Whether to scan for dangerous patterns.
            alert_callback: Function called when actions are blocked.
            high_risk_approval_roles: Roles that can approve high-risk actions.
        """
        self._tenant_id = tenant_id
        self._allowed_actions = allowed_actions or set()
        self._enable_audit = enable_audit
        self._enable_pattern_scanning = enable_pattern_scanning
        self._alert_callback = alert_callback
        self._high_risk_approval_roles = high_risk_approval_roles or [
            "admin",
            "security_admin",
        ]

        # Build categories (merge defaults with custom)
        self._categories = DEFAULT_CATEGORIES.copy()
        if categories:
            self._categories.update(categories)

        # Build rule set (critical denylist + custom rules)
        self._rules: list[ActionRule] = list(CRITICAL_DENYLIST_RULES)
        if custom_rules:
            self._rules.extend(custom_rules)

        # Sort rules by priority (highest first)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

        # Compile dangerous patterns
        self._dangerous_patterns: list[tuple[re.Pattern[str], str]] = [
            (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in DANGEROUS_PATTERNS
        ]

        # Audit log (in-memory, production should use persistent storage)
        self._audit_log: list[ActionAuditEntry] = []
        self._audit_lock = threading.Lock()

        # Statistics
        self._stats: dict[str, Any] = {
            "total_checks": 0,
            "allowed": 0,
            "blocked": 0,
            "pending_approval": 0,
            "alerts_triggered": 0,
        }
        self._stats_lock = threading.Lock()

        logger.info(
            "ActionFilter initialized for tenant=%s with %s allowed actions, %s rules",
            tenant_id,
            len(self._allowed_actions),
            len(self._rules),
        )

    # =========================================================================
    # Core Filtering Methods
    # =========================================================================

    def check_action(
        self,
        action: str,
        context: dict[str, Any] | None = None,
        auth_context: AuthorizationContext | None = None,
    ) -> FilterDecision:
        """
        Check if an action is allowed.

        Evaluates the action against the security policy and returns
        a decision with full context for audit and approval workflows.

        Args:
            action: The action identifier (e.g., "browser.navigate").
            context: Additional context for the action (e.g., URL, path).
            auth_context: Optional RBAC authorization context.

        Returns:
            FilterDecision with the complete decision and context.
        """
        context = context or {}
        start_time = time.monotonic()

        # Determine category
        category = self._get_category(action)

        # Step 1: Check critical denylist rules (cannot be overridden)
        for rule in self._rules:
            if not rule.can_override and rule.matches(action):
                decision = self._create_blocked_decision(
                    action=action,
                    reason=rule.description
                    or f"Action matches critical denylist rule: {rule.action_pattern}",
                    risk_level=rule.risk_level,
                    matched_rule=rule.action_pattern,
                    category=category,
                    context=context,
                )
                self._record_decision(decision, auth_context)
                return decision

        # Step 2: Check dangerous patterns (if enabled)
        if self._enable_pattern_scanning:
            pattern_match = self._check_dangerous_patterns(action, context)
            if pattern_match:
                decision = self._create_blocked_decision(
                    action=action,
                    reason=f"Action matches dangerous pattern: {pattern_match}",
                    risk_level=RiskLevel.CRITICAL,
                    matched_rule=f"pattern:{pattern_match}",
                    category=category,
                    context=context,
                )
                self._record_decision(decision, auth_context)
                return decision

        # Step 3: Check tenant allowlist (deny by default)
        if not self._is_action_allowed(action):
            decision = self._create_blocked_decision(
                action=action,
                reason=f"Action '{action}' is not in tenant allowlist (deny by default)",
                risk_level=self._get_default_risk_level(action, category),
                matched_rule="allowlist",
                category=category,
                context=context,
            )
            self._record_decision(decision, auth_context)
            return decision

        # Step 4: Check custom rules (for approval requirements)
        for rule in self._rules:
            if rule.can_override and rule.matches(action):
                if not rule.allowed:
                    decision = self._create_blocked_decision(
                        action=action,
                        reason=rule.description or f"Action blocked by rule: {rule.action_pattern}",
                        risk_level=rule.risk_level,
                        matched_rule=rule.action_pattern,
                        category=category,
                        context=context,
                    )
                    self._record_decision(decision, auth_context)
                    return decision

                if rule.requires_approval:
                    decision = self._create_approval_decision(
                        action=action,
                        reason=rule.description
                        or f"Action requires approval: {rule.action_pattern}",
                        risk_level=rule.risk_level,
                        approval_roles=rule.approval_roles or self._high_risk_approval_roles,
                        matched_rule=rule.action_pattern,
                        category=category,
                        context=context,
                    )
                    self._record_decision(decision, auth_context)
                    return decision

        # Step 5: Assess risk level and determine if approval is needed
        risk_level = self._assess_risk(action, context, category)
        if risk_level == RiskLevel.HIGH:
            decision = self._create_approval_decision(
                action=action,
                reason=f"High-risk action '{action}' requires approval",
                risk_level=risk_level,
                approval_roles=self._high_risk_approval_roles,
                matched_rule="risk_assessment",
                category=category,
                context=context,
            )
            self._record_decision(decision, auth_context)
            return decision

        # Step 6: Action is allowed
        decision = FilterDecision(
            action=action,
            allowed=True,
            reason=f"Action '{action}' is allowed",
            risk_level=risk_level,
            risk_score=self._calculate_risk_score(risk_level),
            requires_approval=False,
            matched_rule="allowlist",
            category=category,
            tenant_id=self._tenant_id,
            context=context,
        )

        self._record_decision(decision, auth_context)

        logger.debug(
            "Action check completed in %.2fms: action=%s, allowed=%s",
            (time.monotonic() - start_time) * 1000,
            action,
            decision.allowed,
        )

        return decision

    def check_actions(
        self,
        actions: list[str],
        context: dict[str, Any] | None = None,
        auth_context: AuthorizationContext | None = None,
    ) -> dict[str, FilterDecision]:
        """
        Check multiple actions at once.

        Args:
            actions: List of action identifiers to check.
            context: Shared context for all actions.
            auth_context: Optional RBAC authorization context.

        Returns:
            Dictionary mapping action names to decisions.
        """
        return {action: self.check_action(action, context, auth_context) for action in actions}

    def get_blocked_actions(
        self,
        actions: list[str],
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Get list of actions that would be blocked.

        Args:
            actions: List of actions to check.
            context: Context for the check.

        Returns:
            List of action names that would be blocked.
        """
        return [action for action in actions if not self.check_action(action, context).allowed]

    def get_allowed_actions(
        self,
        actions: list[str],
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Get list of actions that would be allowed.

        Args:
            actions: List of actions to check.
            context: Context for the check.

        Returns:
            List of action names that would be allowed.
        """
        return [action for action in actions if self.check_action(action, context).allowed]

    # =========================================================================
    # Allowlist Management
    # =========================================================================

    def add_allowed_action(self, action: str) -> None:
        """
        Add an action to the tenant allowlist.

        Args:
            action: Action pattern to allow (supports glob patterns).
        """
        self._allowed_actions.add(action)
        logger.info("Added action to allowlist: %s", action)

    def remove_allowed_action(self, action: str) -> bool:
        """
        Remove an action from the tenant allowlist.

        Args:
            action: Action pattern to remove.

        Returns:
            True if action was removed, False if not found.
        """
        if action in self._allowed_actions:
            self._allowed_actions.discard(action)
            logger.info("Removed action from allowlist: %s", action)
            return True
        return False

    def set_allowed_actions(self, actions: set[str]) -> None:
        """
        Replace the entire allowlist.

        Args:
            actions: New set of allowed action patterns.
        """
        self._allowed_actions = actions.copy()
        logger.info("Updated allowlist with %s actions", len(actions))

    def get_allowed_actions_list(self) -> list[str]:
        """
        Get the current allowlist.

        Returns:
            List of allowed action patterns.
        """
        return list(self._allowed_actions)

    def _is_action_allowed(self, action: str) -> bool:
        """Check if action matches any allowed pattern."""
        # Check exact match
        if action in self._allowed_actions:
            return True
        # Check glob patterns
        for pattern in self._allowed_actions:
            if fnmatch.fnmatch(action, pattern):
                return True
        return False

    # =========================================================================
    # Rule Management
    # =========================================================================

    def add_rule(self, rule: ActionRule) -> None:
        """
        Add a custom rule.

        Args:
            rule: The rule to add.
        """
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info("Added action rule: %s", rule.action_pattern)

    def remove_rule(self, action_pattern: str) -> bool:
        """
        Remove a rule by pattern.

        Args:
            action_pattern: The pattern of the rule to remove.

        Returns:
            True if rule was removed, False if not found.
        """
        original_count = len(self._rules)
        self._rules = [
            r for r in self._rules if r.action_pattern != action_pattern or not r.can_override
        ]
        removed = original_count - len(self._rules)
        if removed > 0:
            logger.info("Removed action rule: %s", action_pattern)
        return removed > 0

    def get_rules(self, include_critical: bool = False) -> list[ActionRule]:
        """
        Get current rules.

        Args:
            include_critical: Whether to include non-overridable critical rules.

        Returns:
            List of action rules.
        """
        if include_critical:
            return list(self._rules)
        return [r for r in self._rules if r.can_override]

    # =========================================================================
    # Risk Assessment
    # =========================================================================

    def _assess_risk(
        self,
        action: str,
        context: dict[str, Any],
        category: str | None,
    ) -> RiskLevel:
        """Assess the risk level of an action."""
        # Start with default risk level from category
        risk_level = self._get_default_risk_level(action, category)

        # Adjust based on context
        if context:
            # Sensitive paths increase risk
            path = context.get("path", "")
            if path:
                sensitive_paths = ["/etc", "/root", "~/.ssh", "~/.aws", "/var/log"]
                if any(path.startswith(p) or p in path for p in sensitive_paths):
                    risk_level = max(
                        risk_level, RiskLevel.HIGH, key=lambda r: list(RiskLevel).index(r)
                    )

            # External domains increase risk
            domain = context.get("domain", "")
            if domain and not domain.endswith(".internal"):
                if risk_level == RiskLevel.LOW:
                    risk_level = RiskLevel.MEDIUM

        return risk_level

    def _get_default_risk_level(self, action: str, category: str | None) -> RiskLevel:
        """Get default risk level for an action."""
        if category and category in self._categories:
            return self._categories[category].default_risk_level

        # Infer from action prefix
        prefix = action.split(".")[0] if "." in action else action
        if prefix in self._categories:
            return self._categories[prefix].default_risk_level

        return RiskLevel.MEDIUM

    def _calculate_risk_score(self, risk_level: RiskLevel) -> float:
        """Convert risk level to numeric score."""
        scores = {
            RiskLevel.LOW: 0.25,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.75,
            RiskLevel.CRITICAL: 1.0,
        }
        return scores.get(risk_level, 0.5)

    def _get_category(self, action: str) -> str | None:
        """Determine the category for an action."""
        for name, category in self._categories.items():
            if category.matches(action):
                return name
        # Infer from prefix
        prefix = action.split(".")[0] if "." in action else None
        if prefix and prefix in self._categories:
            return prefix
        return None

    # =========================================================================
    # Pattern Scanning
    # =========================================================================

    def _check_dangerous_patterns(
        self,
        action: str,
        context: dict[str, Any],
    ) -> str | None:
        """Check action and context for dangerous patterns.

        Returns:
            Description of matched pattern, or None if no match.
        """
        # Check action name
        for pattern, description in self._dangerous_patterns:
            if pattern.search(action):
                return description

        # Check context values
        for key, value in context.items():
            if isinstance(value, str):
                for pattern, description in self._dangerous_patterns:
                    if pattern.search(value):
                        return f"{description} (in {key})"

        return None

    # =========================================================================
    # Decision Factories
    # =========================================================================

    def _create_blocked_decision(
        self,
        action: str,
        reason: str,
        risk_level: RiskLevel,
        matched_rule: str,
        category: str | None,
        context: dict[str, Any],
    ) -> FilterDecision:
        """Create a blocked decision."""
        return FilterDecision(
            action=action,
            allowed=False,
            reason=reason,
            risk_level=risk_level,
            risk_score=self._calculate_risk_score(risk_level),
            requires_approval=False,
            matched_rule=matched_rule,
            category=category,
            tenant_id=self._tenant_id,
            context=context,
        )

    def _create_approval_decision(
        self,
        action: str,
        reason: str,
        risk_level: RiskLevel,
        approval_roles: list[str],
        matched_rule: str,
        category: str | None,
        context: dict[str, Any],
    ) -> FilterDecision:
        """Create a decision requiring approval."""
        return FilterDecision(
            action=action,
            allowed=False,  # Not immediately allowed
            reason=reason,
            risk_level=risk_level,
            risk_score=self._calculate_risk_score(risk_level),
            requires_approval=True,
            approval_roles=approval_roles,
            matched_rule=matched_rule,
            category=category,
            tenant_id=self._tenant_id,
            context=context,
        )

    # =========================================================================
    # Audit and Monitoring
    # =========================================================================

    def _record_decision(
        self,
        decision: FilterDecision,
        auth_context: AuthorizationContext | None = None,
    ) -> None:
        """Record a decision for audit."""
        with self._stats_lock:
            self._stats["total_checks"] += 1
            if decision.allowed:
                self._stats["allowed"] += 1
            elif decision.requires_approval:
                self._stats["pending_approval"] += 1
            else:
                self._stats["blocked"] += 1

        if not self._enable_audit:
            return

        # Create audit entry
        user_id = auth_context.user_id if auth_context else None
        ip_address = auth_context.ip_address if auth_context else None

        alert_triggered = False
        if not decision.allowed and not decision.requires_approval:
            alert_triggered = True
            with self._stats_lock:
                self._stats["alerts_triggered"] += 1

            # Trigger alert callback
            if self._alert_callback:
                try:
                    self._alert_callback(decision)
                except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided alert callback
                    logger.error("Alert callback failed: %s", e)

        entry = ActionAuditEntry(
            decision_id=decision.decision_id,
            action=decision.action,
            allowed=decision.allowed,
            risk_level=decision.risk_level,
            tenant_id=self._tenant_id,
            user_id=user_id,
            ip_address=ip_address,
            matched_rule=decision.matched_rule,
            context=decision.context,
            alert_triggered=alert_triggered,
        )

        with self._audit_lock:
            self._audit_log.append(entry)
            # Keep bounded (last 10000 entries)
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]

        logger.debug(
            "Audit: action=%s allowed=%s risk=%s tenant=%s",
            decision.action,
            decision.allowed,
            decision.risk_level.value,
            self._tenant_id,
        )

    def get_audit_log(
        self,
        user_id: str | None = None,
        action_pattern: str | None = None,
        allowed: bool | None = None,
        risk_level: RiskLevel | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get audit log entries with optional filtering.

        Args:
            user_id: Filter by user ID.
            action_pattern: Filter by action pattern (glob matching).
            allowed: Filter by decision result.
            risk_level: Filter by risk level.
            since: Filter entries after this ISO timestamp.
            limit: Maximum entries to return.

        Returns:
            List of audit entries as dictionaries.
        """
        with self._audit_lock:
            entries = list(self._audit_log)

        # Apply filters
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        if action_pattern:
            entries = [e for e in entries if fnmatch.fnmatch(e.action, action_pattern)]
        if allowed is not None:
            entries = [e for e in entries if e.allowed == allowed]
        if risk_level:
            entries = [e for e in entries if e.risk_level == risk_level]
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Return most recent
        entries = entries[-limit:]

        return [
            {
                "decision_id": e.decision_id,
                "action": e.action,
                "allowed": e.allowed,
                "risk_level": e.risk_level.value,
                "tenant_id": e.tenant_id,
                "user_id": e.user_id,
                "ip_address": e.ip_address,
                "timestamp": e.timestamp,
                "matched_rule": e.matched_rule,
                "context": e.context,
                "alert_triggered": e.alert_triggered,
            }
            for e in entries
        ]

    def get_stats(self) -> dict[str, Any]:
        """
        Get filter statistics.

        Returns:
            Dictionary of filter statistics.
        """
        with self._stats_lock:
            stats = dict(self._stats)

        stats.update(
            {
                "tenant_id": self._tenant_id,
                "allowed_actions_count": len(self._allowed_actions),
                "rules_count": len(self._rules),
                "categories_count": len(self._categories),
                "audit_entries": len(self._audit_log),
                "pattern_scanning_enabled": self._enable_pattern_scanning,
            }
        )

        return stats

    def clear_audit_log(self) -> int:
        """
        Clear the audit log.

        Returns:
            Number of entries cleared.
        """
        with self._audit_lock:
            count = len(self._audit_log)
            self._audit_log.clear()
        logger.info("Cleared %s audit log entries", count)
        return count


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "RiskLevel",
    "ActionCategoryType",
    # Data classes
    "ActionCategory",
    "ActionRule",
    "FilterDecision",
    "ActionAuditEntry",
    # Constants
    "DEFAULT_CATEGORIES",
    "CRITICAL_DENYLIST_RULES",
    "DANGEROUS_PATTERNS",
    # Main class
    "ActionFilter",
]
