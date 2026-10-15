"""
OpenClaw Policy Engine.

Provides policy-based access control for OpenClaw actions, enabling enterprise
security controls around shell commands, file access, browser operations, and
API calls.

Policy files use YAML format and support:
- Action type filtering (shell, file, browser, api)
- Path/command allowlists and denylists
- Role-based policy overrides via RBAC integration
- Approval workflows for sensitive operations
"""

from __future__ import annotations

import fnmatch
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable

import yaml

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Types of actions that can be policy-controlled."""

    SHELL = "shell"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    BROWSER = "browser"
    API = "api"
    SCREENSHOT = "screenshot"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


class PolicyDecision(str, Enum):
    """Policy evaluation outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class PolicyRule:
    """A single policy rule that matches actions."""

    name: str
    action_types: list[ActionType]
    decision: PolicyDecision
    priority: int = 0

    # Matching criteria
    path_patterns: list[str] = field(default_factory=list)
    path_deny_patterns: list[str] = field(default_factory=list)
    command_patterns: list[str] = field(default_factory=list)
    command_deny_patterns: list[str] = field(default_factory=list)
    url_patterns: list[str] = field(default_factory=list)
    url_deny_patterns: list[str] = field(default_factory=list)

    # Scope restrictions
    workspace_only: bool = False
    workspace_paths: list[str] = field(default_factory=list)

    # Role-based overrides
    allowed_roles: list[str] = field(default_factory=list)
    denied_roles: list[str] = field(default_factory=list)

    # Rate limiting
    rate_limit: int | None = None  # Max actions per minute
    rate_limit_window: int = 60  # Window in seconds

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def matches_action_type(self, action_type: ActionType) -> bool:
        """Check if rule applies to this action type."""
        return action_type in self.action_types

    def matches_path(self, path: str | None) -> bool:
        """Check if path matches this rule's patterns."""
        if not path:
            return not self.path_patterns  # Match if no patterns required

        # Check deny patterns first
        for pattern in self.path_deny_patterns:
            if fnmatch.fnmatch(path, pattern):
                return False

        # If no allow patterns, match by default
        if not self.path_patterns:
            return True

        # Check allow patterns
        for pattern in self.path_patterns:
            if fnmatch.fnmatch(path, pattern):
                return True

        return False

    def matches_command(self, command: str | None) -> bool:
        """Check if command matches this rule's patterns."""
        if not command:
            return not self.command_patterns

        # Check deny patterns first
        for pattern in self.command_deny_patterns:
            if re.search(pattern, command):
                return False

        # If no allow patterns, match by default
        if not self.command_patterns:
            return True

        # Check allow patterns
        for pattern in self.command_patterns:
            if re.search(pattern, command):
                return True

        return False

    def matches_url(self, url: str | None) -> bool:
        """Check if URL matches this rule's patterns."""
        if not url:
            return not self.url_patterns

        # Check deny patterns first
        for pattern in self.url_deny_patterns:
            if fnmatch.fnmatch(url, pattern) or re.search(pattern, url):
                return False

        # If no allow patterns, match by default
        if not self.url_patterns:
            return True

        # Check allow patterns
        for pattern in self.url_patterns:
            if fnmatch.fnmatch(url, pattern) or re.search(pattern, url):
                return True

        return False


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation for an action."""

    decision: PolicyDecision
    matched_rule: PolicyRule | None
    reason: str
    evaluation_time_ms: float
    requires_audit: bool = True
    approval_workflow: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRequest:
    """Request to perform an action that requires policy evaluation."""

    action_type: ActionType
    user_id: str
    session_id: str
    workspace_id: str = "default"

    # Action-specific fields
    path: str | None = None
    command: str | None = None
    url: str | None = None

    # Context
    roles: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class OpenClawPolicy:
    """
    Policy engine for OpenClaw action control.

    Loads policies from YAML configuration and evaluates action requests
    against the policy rules. Integrates with Aragora's RBAC system for
    role-based policy overrides.

    Example policy YAML:
    ```yaml
    version: 1
    default_decision: deny

    rules:
      - name: allow_workspace_files
        action_types: [file_read, file_write]
        decision: allow
        workspace_only: true
        path_patterns:
          - "/workspace/**"

      - name: block_system_files
        action_types: [file_read, file_write, file_delete]
        decision: deny
        priority: 100
        path_patterns:
          - "/etc/**"
          - "/sys/**"
          - "/proc/**"

      - name: approve_shell_commands
        action_types: [shell]
        decision: require_approval
        command_deny_patterns:
          - "rm -rf"
          - "sudo"
          - "chmod 777"
    ```
    """

    def __init__(
        self,
        policy_file: str | Path | None = None,
        policy_dict: dict[str, Any] | None = None,
        default_decision: PolicyDecision = PolicyDecision.DENY,
        rbac_checker: Any | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """
        Initialize the policy engine.

        Args:
            policy_file: Path to YAML policy file
            policy_dict: Policy configuration as dict (alternative to file)
            default_decision: Decision when no rules match
            rbac_checker: Optional RBAC PermissionChecker for role integration
            event_callback: Optional callback for policy events
        """
        self._rules: list[PolicyRule] = []
        self._default_decision = default_decision
        self._rbac_checker = rbac_checker
        self._event_callback = event_callback
        self._version = 1
        self._rate_limit_counters: dict[str, list[float]] = {}

        # Load policy
        if policy_file:
            self.load_from_file(policy_file)
        elif policy_dict:
            self.load_from_dict(policy_dict)

    def load_from_file(self, path: str | Path) -> None:
        """Load policy from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")

        with open(path) as f:
            policy_dict = yaml.safe_load(f)

        self.load_from_dict(policy_dict)
        logger.info("Loaded policy from %s: %s rules", path, len(self._rules))

    def load_from_dict(self, policy_dict: dict[str, Any]) -> None:
        """Load policy from dictionary."""
        self._version = policy_dict.get("version", 1)

        # Set default decision
        default = policy_dict.get("default_decision", "deny")
        self._default_decision = PolicyDecision(default)

        # Load rules
        self._rules = []
        for rule_dict in policy_dict.get("rules", []):
            rule = self._parse_rule(rule_dict)
            self._rules.append(rule)

        # Sort by priority (higher priority = checked first)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def _parse_rule(self, rule_dict: dict[str, Any]) -> PolicyRule:
        """Parse a rule from dictionary format."""
        action_types = [ActionType(at) for at in rule_dict.get("action_types", [])]

        return PolicyRule(
            name=rule_dict.get("name", "unnamed"),
            action_types=action_types,
            decision=PolicyDecision(rule_dict.get("decision", "deny")),
            priority=rule_dict.get("priority", 0),
            path_patterns=rule_dict.get("path_patterns", []),
            path_deny_patterns=rule_dict.get("path_deny_patterns", []),
            command_patterns=rule_dict.get("command_patterns", []),
            command_deny_patterns=rule_dict.get("command_deny_patterns", []),
            url_patterns=rule_dict.get("url_patterns", []),
            url_deny_patterns=rule_dict.get("url_deny_patterns", []),
            workspace_only=rule_dict.get("workspace_only", False),
            workspace_paths=rule_dict.get("workspace_paths", []),
            allowed_roles=rule_dict.get("allowed_roles", []),
            denied_roles=rule_dict.get("denied_roles", []),
            rate_limit=rule_dict.get("rate_limit"),
            rate_limit_window=rule_dict.get("rate_limit_window", 60),
            description=rule_dict.get("description", ""),
            tags=rule_dict.get("tags", []),
        )

    def evaluate(self, request: ActionRequest) -> PolicyEvaluationResult:
        """
        Evaluate an action request against the policy.

        Args:
            request: The action request to evaluate

        Returns:
            PolicyEvaluationResult with decision and metadata
        """
        start_time = time.time()

        for rule in self._rules:
            # Check action type match
            if not rule.matches_action_type(request.action_type):
                continue

            # Check role-based denials first
            if rule.denied_roles:
                if any(role in rule.denied_roles for role in request.roles):
                    continue  # Skip this rule for denied roles

            # Check role-based allows
            if rule.allowed_roles:
                if not any(role in rule.allowed_roles for role in request.roles):
                    continue  # Skip if user doesn't have allowed role

            # Check workspace restriction
            if rule.workspace_only:
                if not self._is_in_workspace(request):
                    continue

            # Check path/command/url patterns based on action type
            matches = self._check_patterns(rule, request)
            if not matches:
                continue

            # Check rate limit
            if rule.rate_limit:
                rate_key = f"{request.user_id}:{rule.name}"
                if self._is_rate_limited(rate_key, rule.rate_limit, rule.rate_limit_window):
                    return PolicyEvaluationResult(
                        decision=PolicyDecision.DENY,
                        matched_rule=rule,
                        reason=f"Rate limit exceeded for rule '{rule.name}'",
                        evaluation_time_ms=(time.time() - start_time) * 1000,
                        requires_audit=True,
                        metadata={"rate_limited": True},
                    )

            # Rule matched - return its decision
            eval_time = (time.time() - start_time) * 1000

            result = PolicyEvaluationResult(
                decision=rule.decision,
                matched_rule=rule,
                reason=f"Matched rule '{rule.name}': {rule.description or rule.decision.value}",
                evaluation_time_ms=eval_time,
                requires_audit=True,
                approval_workflow="default"
                if rule.decision == PolicyDecision.REQUIRE_APPROVAL
                else None,
            )

            self._emit_event(
                "policy_evaluated",
                {
                    "request": {
                        "action_type": request.action_type.value,
                        "user_id": request.user_id,
                        "path": request.path,
                        "command": request.command,
                    },
                    "result": {
                        "decision": result.decision.value,
                        "rule": rule.name,
                    },
                },
            )

            return result

        # No rule matched - use default decision
        eval_time = (time.time() - start_time) * 1000

        return PolicyEvaluationResult(
            decision=self._default_decision,
            matched_rule=None,
            reason=f"No matching rule; default decision: {self._default_decision.value}",
            evaluation_time_ms=eval_time,
            requires_audit=True,
        )

    def _check_patterns(self, rule: PolicyRule, request: ActionRequest) -> bool:
        """Check if request matches rule patterns."""
        action = request.action_type

        if action in (ActionType.FILE_READ, ActionType.FILE_WRITE, ActionType.FILE_DELETE):
            return rule.matches_path(request.path)
        elif action == ActionType.SHELL:
            return rule.matches_command(request.command)
        elif action == ActionType.BROWSER:
            return rule.matches_url(request.url)
        elif action in (ActionType.SCREENSHOT, ActionType.KEYBOARD, ActionType.MOUSE):
            # These actions match if no specific patterns required
            return True
        elif action == ActionType.API:
            return rule.matches_url(request.url)

        return True

    def _is_in_workspace(self, request: ActionRequest) -> bool:
        """Check if request targets workspace-scoped resources."""
        if not request.path or not request.workspace_id:
            return False

        request_path = Path(request.path)
        if not request_path.is_absolute():
            return False

        workspace_root = (Path("/workspace") / request.workspace_id).resolve(strict=False)
        request_path = request_path.resolve(strict=False)
        return request_path == workspace_root or workspace_root in request_path.parents

    def _is_rate_limited(self, key: str, limit: int, window: int) -> bool:
        """Check if action is rate limited."""
        now = time.time()

        # Get or create counter
        if key not in self._rate_limit_counters:
            self._rate_limit_counters[key] = []

        # Clean old entries
        self._rate_limit_counters[key] = [
            t for t in self._rate_limit_counters[key] if now - t < window
        ]

        # Check limit
        if len(self._rate_limit_counters[key]) >= limit:
            return True

        # Record this action
        self._rate_limit_counters[key].append(now)
        return False

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a policy event."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event callback
                logger.warning("Event callback failed: %s", e)

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a rule to the policy."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        initial_len = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < initial_len

    def get_rules(self) -> list[PolicyRule]:
        """Get all policy rules."""
        return list(self._rules)

    def get_rule(self, name: str) -> PolicyRule | None:
        """Get a rule by name."""
        for rule in self._rules:
            if rule.name == name:
                return rule
        return None

    def to_dict(self) -> dict[str, Any]:
        """Export policy to dictionary format."""
        return {
            "version": self._version,
            "default_decision": self._default_decision.value,
            "rules": [
                {
                    "name": r.name,
                    "action_types": [at.value for at in r.action_types],
                    "decision": r.decision.value,
                    "priority": r.priority,
                    "path_patterns": r.path_patterns,
                    "path_deny_patterns": r.path_deny_patterns,
                    "command_patterns": r.command_patterns,
                    "command_deny_patterns": r.command_deny_patterns,
                    "url_patterns": r.url_patterns,
                    "url_deny_patterns": r.url_deny_patterns,
                    "workspace_only": r.workspace_only,
                    "workspace_paths": r.workspace_paths,
                    "allowed_roles": r.allowed_roles,
                    "denied_roles": r.denied_roles,
                    "rate_limit": r.rate_limit,
                    "rate_limit_window": r.rate_limit_window,
                    "description": r.description,
                    "tags": r.tags,
                }
                for r in self._rules
            ],
        }

    def save_to_file(self, path: str | Path) -> None:
        """Save policy to YAML file."""
        path = Path(path)
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)


def create_enterprise_policy() -> OpenClawPolicy:
    """
    Create a default enterprise policy with security-focused rules.

    This policy:
    - Denies access to system directories (/etc, /sys, /proc, /root)
    - Requires approval for shell commands with sudo/rm -rf
    - Allows file operations within workspace
    - Rate limits API calls
    """
    policy_dict = {
        "version": 1,
        "default_decision": "deny",
        "rules": [
            # High priority: Block dangerous system paths
            {
                "name": "block_system_directories",
                "action_types": ["file_read", "file_write", "file_delete"],
                "decision": "deny",
                "priority": 100,
                "path_patterns": [
                    "/etc/**",
                    "/sys/**",
                    "/proc/**",
                    "/root/**",
                    "/boot/**",
                    "/dev/**",
                ],
                "description": "Block access to system directories",
            },
            # High priority: Block dangerous commands
            {
                "name": "block_dangerous_commands",
                "action_types": ["shell"],
                "decision": "deny",
                "priority": 100,
                "command_deny_patterns": [
                    r"rm\s+-rf\s+/",
                    r"mkfs\.",
                    r"dd\s+if=.*of=/dev/",
                    r">\s*/dev/sd[a-z]",
                    r"chmod\s+777\s+/",
                ],
                "description": "Block destructive system commands",
            },
            # Require approval for elevated commands
            {
                "name": "approve_elevated_commands",
                "action_types": ["shell"],
                "decision": "require_approval",
                "priority": 50,
                "command_patterns": [
                    r"^sudo\s+",
                    r"^su\s+",
                    r"^doas\s+",
                ],
                "description": "Require approval for elevated privilege commands",
            },
            # Allow workspace file operations
            {
                "name": "allow_workspace_files",
                "action_types": ["file_read", "file_write", "file_delete"],
                "decision": "allow",
                "priority": 10,
                "workspace_only": True,
                "description": "Allow file operations within workspace",
            },
            # Allow safe shell commands in workspace
            {
                "name": "allow_workspace_shell",
                "action_types": ["shell"],
                "decision": "allow",
                "priority": 10,
                "command_patterns": [
                    r"^(ls|cat|head|tail|grep|find|wc|echo|pwd|cd)\s+",
                    r"^(python|node|npm|pip|git)\s+",
                ],
                "description": "Allow common development commands",
            },
            # Rate limit browser actions
            {
                "name": "rate_limit_browser",
                "action_types": ["browser"],
                "decision": "allow",
                "priority": 5,
                "rate_limit": 30,
                "rate_limit_window": 60,
                "description": "Rate limit browser actions to 30/minute",
            },
            # Rate limit screenshots
            {
                "name": "rate_limit_screenshots",
                "action_types": ["screenshot"],
                "decision": "allow",
                "priority": 5,
                "rate_limit": 10,
                "rate_limit_window": 60,
                "description": "Rate limit screenshots to 10/minute",
            },
            # Block external URLs by default
            {
                "name": "block_external_urls",
                "action_types": ["browser", "api"],
                "decision": "deny",
                "priority": 1,
                "url_deny_patterns": [
                    r"^file://",
                    r"localhost",
                    r"127\.0\.0\.1",
                    r"0\.0\.0\.0",
                ],
                "description": "Block access to local URLs",
            },
        ],
    }

    return OpenClawPolicy(policy_dict=policy_dict)
