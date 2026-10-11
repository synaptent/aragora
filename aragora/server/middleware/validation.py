"""
Request validation middleware.

Provides centralized validation for API requests based on route patterns.
Initially operates in warning mode (logs but doesn't block) to identify
handlers that need validation, then can be promoted to blocking mode.

Usage:
    1. Register schemas in VALIDATION_REGISTRY
    2. Add ValidationMiddleware to server middleware stack
    3. Validation errors are logged and optionally blocked
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, cast
from re import Pattern
from collections.abc import Callable

from aragora.server.validation.schema import (
    AGENT_CONFIG_SCHEMA,
    ALERT_CONFIG_SCHEMA,
    BATCH_SUBMIT_SCHEMA,
    BILLING_PORTAL_SCHEMA,
    BUDGET_CREATE_SCHEMA,
    BUDGET_UPDATE_SCHEMA,
    CHECKOUT_SESSION_SCHEMA,
    COMPLIANCE_REPORT_SCHEMA,
    CONNECTOR_CREATE_SCHEMA,
    CONNECTOR_UPDATE_SCHEMA,
    DEBATE_START_SCHEMA,
    DEBATE_UPDATE_SCHEMA,
    EMAIL_CONFIG_SCHEMA,
    EVIDENCE_SUBMIT_SCHEMA,
    FORK_REQUEST_SCHEMA,
    GAUNTLET_RUN_SCHEMA,
    KNOWLEDGE_CREATE_SCHEMA,
    KNOWLEDGE_UPDATE_SCHEMA,
    MEMBER_ROLE_SCHEMA,
    MEMORY_CLEANUP_SCHEMA,
    MFA_CODE_SCHEMA,
    MFA_DISABLE_SCHEMA,
    MFA_VERIFY_SCHEMA,
    NOTIFICATION_SEND_SCHEMA,
    ORG_CREATE_SCHEMA,
    ORG_INVITE_SCHEMA,
    ORG_SWITCH_SCHEMA,
    ORG_UPDATE_SCHEMA,
    PASSWORD_CHANGE_SCHEMA,
    PLUGIN_INSTALL_SCHEMA,
    PLUGIN_MANIFEST_SCHEMA,
    PLUGIN_RUN_SCHEMA,
    POLICY_CREATE_SCHEMA,
    POLICY_UPDATE_SCHEMA,
    PROBE_RUN_SCHEMA,
    ROUTING_RULE_SCHEMA,
    SCHEDULE_CREATE_SCHEMA,
    SHARE_UPDATE_SCHEMA,
    SOCIAL_PUBLISH_SCHEMA,
    TELEGRAM_CONFIG_SCHEMA,
    TOKEN_REFRESH_SCHEMA,
    TOKEN_REVOKE_SCHEMA,
    TRIGGER_CREATE_SCHEMA,
    TRIGGER_UPDATE_SCHEMA,
    USER_LOGIN_SCHEMA,
    USER_REGISTER_SCHEMA,
    USER_UPDATE_SCHEMA,
    VERIFICATION_SCHEMA,
    WORKFLOW_CREATE_SCHEMA,
    WORKFLOW_EXECUTE_SCHEMA,
    WORKFLOW_UPDATE_SCHEMA,
    WORKSPACE_CREATE_SCHEMA,
    WORKSPACE_MEMBER_SCHEMA,
    WORKSPACE_SETTINGS_SCHEMA,
    WORKSPACE_UPDATE_SCHEMA,
    validate_against_schema,
)
from aragora.server.validation.entities import (
    validate_agent_name,
    validate_debate_id,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Validation Configuration
# =============================================================================


@dataclass
class RouteValidation:
    """Validation rules for a route pattern.

    Attributes:
        pattern: Regex pattern matching the route
        method: HTTP method (GET, POST, etc.) or * for all
        body_schema: Schema for POST/PUT body validation
        query_rules: Dict of param_name -> (min, max) for numeric params
        required_params: List of required query parameter names
        path_validators: Dict of path segment name -> validator function
        max_body_size: Maximum body size in bytes (default 1MB)
    """

    pattern: str | Pattern[str]
    method: str
    body_schema: dict | None = None
    query_rules: dict[str, tuple[int, int]] = field(default_factory=dict)
    required_params: list[str] = field(default_factory=list)
    path_validators: dict[str, Callable[[str], tuple[bool, str | None]]] = field(
        default_factory=dict
    )
    max_body_size: int = 1_048_576  # 1MB default

    def __post_init__(self) -> None:
        if isinstance(self.pattern, str):
            self.pattern = re.compile(self.pattern)

    def matches(self, path: str, method: str) -> bool:
        """Check if this rule matches the request."""
        if self.method != "*" and self.method.upper() != method.upper():
            return False
        # Pattern is always compiled in __post_init__
        pattern = cast(Pattern[str], self.pattern)
        return bool(pattern.match(path))


# =============================================================================
# Validation Registry
# =============================================================================

# Common query parameter rules
LIMIT_OFFSET_RULES = {"limit": (1, 100), "offset": (0, 100000)}
PAGINATION_RULES = {"page": (1, 10000), "per_page": (1, 100)}

# Route validation registry - add schemas here as they're created
VALIDATION_REGISTRY: list[RouteValidation] = [
    # =========================================================================
    # Debates - core functionality
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?debates?$",
        "POST",
        body_schema=DEBATE_START_SCHEMA,
        max_body_size=500_000,  # Allow large context/documents
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?/([^/]+)$",
        "GET",
        path_validators={"debate_id": validate_debate_id},
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?/([^/]+)$",
        "PUT",
        body_schema=DEBATE_UPDATE_SCHEMA,
        path_validators={"debate_id": validate_debate_id},
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?/([^/]+)/fork$",
        "POST",
        body_schema=FORK_REQUEST_SCHEMA,
        path_validators={"debate_id": validate_debate_id},
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?/([^/]+)/share$",
        "PUT",
        body_schema=SHARE_UPDATE_SCHEMA,
        path_validators={"debate_id": validate_debate_id},
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?debates?/([^/]+)/publish$",
        "POST",
        body_schema=SOCIAL_PUBLISH_SCHEMA,
        path_validators={"debate_id": validate_debate_id},
        max_body_size=50_000,
    ),
    # =========================================================================
    # Verification
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?verify$",
        "POST",
        body_schema=VERIFICATION_SCHEMA,
        max_body_size=100_000,
    ),
    # =========================================================================
    # Agents
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?agents?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?agents?$",
        "POST",
        body_schema=AGENT_CONFIG_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?agents?/([^/]+)$",
        "GET",
        path_validators={"agent_name": validate_agent_name},
    ),
    RouteValidation(
        r"^/api/(v1/)?agents?/([^/]+)$",
        "PUT",
        body_schema=AGENT_CONFIG_SCHEMA,
        path_validators={"agent_name": validate_agent_name},
        max_body_size=50_000,
    ),
    # =========================================================================
    # Probes
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?probes?/run$",
        "POST",
        body_schema=PROBE_RUN_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?probes?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Batch
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?batch$",
        "POST",
        body_schema=BATCH_SUBMIT_SCHEMA,
        max_body_size=5_000_000,  # 5MB for large batch submissions
    ),
    # =========================================================================
    # Memory
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?memory/cleanup$",
        "POST",
        body_schema=MEMORY_CLEANUP_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?memory$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Gauntlet
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?gauntlet/run$",
        "POST",
        body_schema=GAUNTLET_RUN_SCHEMA,
        max_body_size=500_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?gauntlet$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?gauntlet/receipts$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Auth - Tier 1 (Security Critical)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?auth/register$",
        "POST",
        body_schema=USER_REGISTER_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/login$",
        "POST",
        body_schema=USER_LOGIN_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/password$",
        "POST",
        body_schema=PASSWORD_CHANGE_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/refresh$",
        "POST",
        body_schema=TOKEN_REFRESH_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/revoke$",
        "POST",
        body_schema=TOKEN_REVOKE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/me$",
        "PUT",
        body_schema=USER_UPDATE_SCHEMA,
        max_body_size=5_000,
    ),
    # MFA endpoints
    RouteValidation(
        r"^/api/(v1/)?auth/mfa/enable$",
        "POST",
        body_schema=MFA_CODE_SCHEMA,
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/mfa/disable$",
        "POST",
        body_schema=MFA_DISABLE_SCHEMA,
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/mfa/verify$",
        "POST",
        body_schema=MFA_VERIFY_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?auth/mfa/backup-codes$",
        "POST",
        body_schema=MFA_CODE_SCHEMA,
        max_body_size=1_000,
    ),
    # =========================================================================
    # Organizations - Tier 1 (Security Critical)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?org$",
        "POST",
        body_schema=ORG_CREATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?org/([^/]+)$",
        "PUT",
        body_schema=ORG_UPDATE_SCHEMA,
        max_body_size=100_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?org/([^/]+)/invite$",
        "POST",
        body_schema=ORG_INVITE_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?org/([^/]+)/members/([^/]+)/role$",
        "PUT",
        body_schema=MEMBER_ROLE_SCHEMA,
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?user/organizations/switch$",
        "POST",
        body_schema=ORG_SWITCH_SCHEMA,
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?user/organizations/default$",
        "POST",
        body_schema=ORG_SWITCH_SCHEMA,
        max_body_size=1_000,
    ),
    # =========================================================================
    # Billing - Tier 1 (Financial Operations)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?billing/checkout$",
        "POST",
        body_schema=CHECKOUT_SESSION_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/portal$",
        "POST",
        body_schema=BILLING_PORTAL_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/cancel$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/resume$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    # =========================================================================
    # Knowledge - Tier 2 (Data Integrity)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?knowledge$",
        "POST",
        body_schema=KNOWLEDGE_CREATE_SCHEMA,
        max_body_size=500_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?knowledge$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?knowledge/([^/]+)$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?knowledge/([^/]+)$",
        "PUT",
        body_schema=KNOWLEDGE_UPDATE_SCHEMA,
        max_body_size=500_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?knowledge/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?knowledge/search$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Workspaces - Tier 2 (Access Control)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?workspaces?$",
        "POST",
        body_schema=WORKSPACE_CREATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)$",
        "PUT",
        body_schema=WORKSPACE_UPDATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)/members$",
        "POST",
        body_schema=WORKSPACE_MEMBER_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)/members$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?workspaces?/([^/]+)/settings$",
        "PUT",
        body_schema=WORKSPACE_SETTINGS_SCHEMA,
        max_body_size=10_000,
    ),
    # =========================================================================
    # Workflows - Tier 2 (Execution Control)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?workflows?$",
        "POST",
        body_schema=WORKFLOW_CREATE_SCHEMA,
        max_body_size=100_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workflows?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?workflows?/([^/]+)$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?workflows?/([^/]+)$",
        "PUT",
        body_schema=WORKFLOW_UPDATE_SCHEMA,
        max_body_size=100_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workflows?/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?workflows?/([^/]+)/execute$",
        "POST",
        body_schema=WORKFLOW_EXECUTE_SCHEMA,
        max_body_size=100_000,
    ),
    # =========================================================================
    # Connectors - Tier 2 (Integration Security)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?connectors?$",
        "POST",
        body_schema=CONNECTOR_CREATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?connectors?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?connectors?/([^/]+)$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?connectors?/([^/]+)$",
        "PUT",
        body_schema=CONNECTOR_UPDATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?connectors?/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    # =========================================================================
    # Policies - Tier 2 (Governance)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?policies$",
        "POST",
        body_schema=POLICY_CREATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?policies$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?policies/([^/]+)$",
        "PUT",
        body_schema=POLICY_UPDATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?policies/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    # =========================================================================
    # Budgets - Tier 2 (Financial)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?budgets?$",
        "POST",
        body_schema=BUDGET_CREATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?budgets?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?budgets?/([^/]+)$",
        "PUT",
        body_schema=BUDGET_UPDATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?budgets?/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    # =========================================================================
    # Evidence - Tier 2 (Data Integrity)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?evidence$",
        "POST",
        body_schema=EVIDENCE_SUBMIT_SCHEMA,
        max_body_size=500_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?evidence$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Costs / Usage
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?costs$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?usage$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Compliance
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?compliance/report$",
        "POST",
        body_schema=COMPLIANCE_REPORT_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?compliance$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Plugins
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?plugins?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?plugins?/submit$",
        "POST",
        body_schema=PLUGIN_MANIFEST_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?plugins?/([^/]+)/run$",
        "POST",
        body_schema=PLUGIN_RUN_SCHEMA,
        max_body_size=500_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?plugins?/([^/]+)/install$",
        "POST",
        body_schema=PLUGIN_INSTALL_SCHEMA,
        max_body_size=50_000,
    ),
    # =========================================================================
    # Notifications
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?notifications?/send$",
        "POST",
        body_schema=NOTIFICATION_SEND_SCHEMA,
        max_body_size=100_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?notifications?/email/config$",
        "PUT",
        body_schema=EMAIL_CONFIG_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?notifications?/telegram/config$",
        "PUT",
        body_schema=TELEGRAM_CONFIG_SCHEMA,
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?notifications?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Autonomous - Triggers & Alerts
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?triggers?$",
        "POST",
        body_schema=TRIGGER_CREATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?triggers?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?triggers?/([^/]+)$",
        "PUT",
        body_schema=TRIGGER_UPDATE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?triggers?/([^/]+)$",
        "DELETE",
        max_body_size=1_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?alerts?/config$",
        "POST",
        body_schema=ALERT_CONFIG_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?alerts?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Routing Rules
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?routing/rules$",
        "POST",
        body_schema=ROUTING_RULE_SCHEMA,
        max_body_size=50_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?routing/rules$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Scheduler
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?schedules?$",
        "POST",
        body_schema=SCHEDULE_CREATE_SCHEMA,
        max_body_size=10_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?schedules?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Social Publishing
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?social/publish$",
        "POST",
        body_schema=SOCIAL_PUBLISH_SCHEMA,
        max_body_size=50_000,
    ),
    # =========================================================================
    # Rankings / ELO
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?rankings?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Receipts
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?receipts?$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Admin endpoints (high body size limits for bulk operations)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/users$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/metrics$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/audit$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Admin User Management (Security Critical - Tier 1)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/users/[^/]+/deactivate$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/users/[^/]+/activate$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/users/[^/]+/unlock$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/impersonate/[^/]+$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    # =========================================================================
    # Admin Organizations (Tier 3)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/organizations$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Admin Nomic Control (Tier 2)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/status$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/circuit-breakers$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/reset$",
        "POST",
        body_schema={
            "target_phase": {"type": "string", "max_length": 50},
            "clear_errors": {"type": "boolean"},
            "reason": {"type": "string", "max_length": 500},
        },
        max_body_size=5_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/pause$",
        "POST",
        body_schema={
            "reason": {"type": "string", "max_length": 500},
        },
        max_body_size=2_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/resume$",
        "POST",
        body_schema={
            "target_phase": {"type": "string", "max_length": 50},
        },
        max_body_size=2_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/nomic/circuit-breakers/reset$",
        "POST",
        max_body_size=0,  # No body expected
    ),
    # =========================================================================
    # Billing GET Endpoints (Tier 3)
    # Note: POST endpoints (checkout, portal, cancel, resume) defined earlier
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?billing/plans$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/usage$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/subscription$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/invoices$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/usage/export$",
        "GET",
    ),
    RouteValidation(
        r"^/api/(v1/)?billing/usage/forecast$",
        "GET",
    ),
    # =========================================================================
    # Admin Health Endpoints
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/health.*$",
        "GET",
    ),
    # =========================================================================
    # Admin Dashboard Endpoints
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/dashboard.*$",
        "GET",
        query_rules=LIMIT_OFFSET_RULES,
    ),
    # =========================================================================
    # Admin Cache Operations (Tier 2)
    # =========================================================================
    RouteValidation(
        r"^/api/(v1/)?admin/cache/clear$",
        "POST",
        body_schema={
            "cache_type": {"type": "string", "max_length": 50},
            "pattern": {"type": "string", "max_length": 200},
        },
        max_body_size=2_000,
    ),
    RouteValidation(
        r"^/api/(v1/)?admin/cache/stats$",
        "GET",
    ),
]

# =============================================================================
# Validation Middleware
# =============================================================================


@dataclass
class ValidationConfig:
    """Configuration for validation middleware.

    Attributes:
        enabled: Whether validation is enabled
        blocking: If True, block invalid requests; if False, just log warnings
        log_all: Log all validation attempts, not just failures
        max_body_size: Default max body size (can be overridden per route)
    """

    enabled: bool = True
    blocking: bool = True  # Block invalid requests for security
    log_all: bool = False
    max_body_size: int = 10_485_760  # 10MB default


@dataclass
class MiddlewareValidationResult:
    """Result of request validation in the middleware layer.

    Note: This is distinct from aragora.core.types.ValidationResult which uses
    `is_valid` instead of `valid`. This class is specific to HTTP request
    validation middleware.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_message(self) -> str:
        return "; ".join(self.errors) if self.errors else ""


# Backward compatibility alias - deprecated, use MiddlewareValidationResult
ValidationResult = MiddlewareValidationResult


class ValidationMiddleware:
    """Middleware for validating API requests.

    Validates requests based on registered route patterns and schemas.
    Can operate in warning mode (log only) or blocking mode.
    """

    def __init__(
        self,
        config: ValidationConfig | None = None,
        registry: list[RouteValidation] | None = None,
    ) -> None:
        self.config = config or ValidationConfig()
        self.registry = registry or VALIDATION_REGISTRY

        # Metrics (protected by _metrics_lock for thread safety)
        self._metrics_lock = threading.Lock()
        self._validation_count = 0
        self._validation_failures = 0
        self._unvalidated_routes: set[str] = set()

    def validate_request(
        self,
        path: str,
        method: str,
        query_params: dict[str, Any] | None = None,
        body: bytes | None = None,
        body_parsed: dict | None = None,
    ) -> MiddlewareValidationResult:
        """Validate an incoming request.

        Args:
            path: Request path
            method: HTTP method
            query_params: Query parameters
            body: Raw request body (for size check)
            body_parsed: Parsed JSON body (for schema validation)

        Returns:
            MiddlewareValidationResult with validation status and any errors
        """
        if not self.config.enabled:
            return MiddlewareValidationResult(valid=True)

        with self._metrics_lock:
            self._validation_count += 1
        result = MiddlewareValidationResult(valid=True)
        query_params = query_params or {}

        # Find matching validation rule
        rule = self._find_rule(path, method)
        if rule is None:
            # No validation rule - track for coverage metrics
            route_key = f"{method} {path.split('?')[0]}"
            if route_key not in self._unvalidated_routes:
                self._unvalidated_routes.add(route_key)
                if self.config.log_all:
                    logger.debug("No validation rule for: %s", route_key)
            return result

        # Validate body size
        if body is not None and len(body) > rule.max_body_size:
            result.valid = False
            result.errors.append(
                f"Request body too large: {len(body)} bytes (max {rule.max_body_size})"
            )

        # Validate required params
        for param in rule.required_params:
            if param not in query_params or not query_params[param]:
                result.valid = False
                result.errors.append(f"Missing required parameter: {param}")

        # Validate query param ranges
        for param, (min_val, max_val) in rule.query_rules.items():
            if param in query_params:
                try:
                    val = int(query_params[param])
                    if val < min_val or val > max_val:
                        result.valid = False
                        result.errors.append(
                            f"Parameter '{param}' out of range: {val} (allowed {min_val}-{max_val})"
                        )
                except (ValueError, TypeError):
                    result.warnings.append(f"Parameter '{param}' is not a valid integer")

        # Validate path segments
        for name, validator in rule.path_validators.items():
            segment = self._extract_path_segment(path, name)
            if segment:
                is_valid, err = validator(segment)
                if not is_valid:
                    result.valid = False
                    result.errors.append(f"Invalid {name}: {err}")

        # Validate body schema
        if rule.body_schema and body_parsed is not None:
            schema_result = validate_against_schema(body_parsed, rule.body_schema)
            if not schema_result.is_valid:
                result.valid = False
                result.errors.append(f"Body validation failed: {schema_result.error}")

        # Log result
        if not result.valid:
            with self._metrics_lock:
                self._validation_failures += 1
            log_level = logging.WARNING if not self.config.blocking else logging.ERROR
            logger.log(
                log_level,
                "Validation failed for %s %s: %s",
                method,
                path,
                result.error_message,
            )

            # Emit audit event for validation failures (security/compliance requirement)
            try:
                from aragora.audit.unified import audit_security

                audit_security(
                    event_type="validation_failure",
                    severity="warning" if not self.config.blocking else "error",
                    path=path,
                    method=method,
                    errors=result.errors,
                    blocking=self.config.blocking,
                )
            except ImportError:
                pass  # Audit module not available
            except (RuntimeError, ValueError, TypeError, OSError) as e:
                logger.debug("Failed to emit validation audit event: %s", e)

        elif self.config.log_all:
            logger.debug("Validation passed for %s %s", method, path)

        return result

    def _find_rule(self, path: str, method: str) -> RouteValidation | None:
        """Find the first matching validation rule."""
        for rule in self.registry:
            if rule.matches(path, method):
                return rule
        return None

    def _extract_path_segment(self, path: str, name: str) -> str | None:
        """Extract a named segment from the path."""
        parts = path.strip("/").split("/")

        # Common segment positions
        segment_positions = {
            "debate_id": 2,  # /api/debates/{id}
            "agent_name": 2,  # /api/agents/{name}
            "receipt_id": 2,  # /api/receipts/{id}
            "workflow_id": 2,  # /api/workflows/{id}
        }

        pos = segment_positions.get(name)
        if pos is not None and len(parts) > pos:
            return parts[pos]

        return None

    def get_metrics(self) -> dict[str, Any]:
        """Get validation metrics."""
        with self._metrics_lock:
            return {
                "total_validations": self._validation_count,
                "failures": self._validation_failures,
                "failure_rate": (
                    self._validation_failures / self._validation_count
                    if self._validation_count > 0
                    else 0
                ),
                "unvalidated_route_count": len(self._unvalidated_routes),
                "blocking_mode": self.config.blocking,
            }

    def get_unvalidated_routes(self) -> list[str]:
        """Get list of routes that have no validation rules."""
        return sorted(self._unvalidated_routes)


# =============================================================================
# Utility Functions
# =============================================================================


def create_validation_middleware(
    blocking: bool = True,
    enabled: bool = True,
) -> ValidationMiddleware:
    """Create a validation middleware with standard configuration.

    Args:
        blocking: If True, return errors for invalid requests
        enabled: If False, skip all validation

    Returns:
        Configured ValidationMiddleware instance
    """
    config = ValidationConfig(
        enabled=enabled,
        blocking=blocking,
        log_all=False,
    )
    return ValidationMiddleware(config=config)


def add_route_validation(
    pattern: str,
    method: str,
    body_schema: dict | None = None,
    query_rules: dict[str, tuple[int, int]] | None = None,
    required_params: list[str] | None = None,
) -> None:
    """Add a validation rule to the global registry.

    Args:
        pattern: Regex pattern for the route
        method: HTTP method
        body_schema: Schema for body validation
        query_rules: Rules for query parameter ranges
        required_params: Required query parameters
    """
    rule = RouteValidation(
        pattern=pattern,
        method=method,
        body_schema=body_schema,
        query_rules=query_rules or {},
        required_params=required_params or [],
    )
    VALIDATION_REGISTRY.append(rule)
    logger.info("Added validation rule: %s %s", method, pattern)
