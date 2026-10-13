"""
RBAC Models - Core data structures for role-based access control.

Implements:
- Permission: Individual access rights
- Role: Collection of permissions with hierarchy support
- RoleAssignment: User-role bindings with org scope and expiration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ResourceType(str, Enum):
    """Resource types that can be protected by permissions."""

    DEBATE = "debates"
    SETTLEMENT = "settlements"
    AGENT = "agents"
    USER = "users"
    ORGANIZATION = "organization"
    API = "api"
    MEMORY = "memory"
    WORKFLOW = "workflows"
    EVIDENCE = "evidence"
    DOCUMENTS = "documents"
    UPLOAD = "upload"
    SPEECH = "speech"
    TRAINING = "training"
    ANALYTICS = "analytics"
    ADMIN = "admin"
    BILLING = "billing"
    CONNECTOR = "connectors"
    BOT = "bots"
    DEVICE = "devices"
    WEBHOOK = "webhooks"
    REPOSITORY = "repository"
    BINDINGS = "bindings"
    CHECKPOINT = "checkpoints"
    GAUNTLET = "gauntlet"  # Adversarial stress-testing
    MARKETPLACE = "marketplace"  # Template marketplace
    EXPLAINABILITY = "explainability"  # Decision explanations
    FINDINGS = "findings"  # Audit findings management
    DECISION = "decisions"  # Unified decision routing
    INTROSPECTION = "introspection"  # System introspection and status
    REASONING = "reasoning"  # Belief networks and reasoning analysis
    KNOWLEDGE = "knowledge"  # Knowledge base and mound operations
    INBOX = "inbox"  # Action items and meeting management
    SKILLS = "skills"  # Skill marketplace operations
    PROVENANCE = "provenance"  # Claim provenance and belief tracking

    # Governance and orchestration
    POLICY = "policies"  # Governance policies
    COMPLIANCE = "compliance"  # Compliance management
    CONTROL_PLANE = "control_plane"  # Control plane orchestration

    # Enterprise data governance
    DATA_CLASSIFICATION = "data_classification"  # Data sensitivity classification
    DATA_RETENTION = "data_retention"  # Data retention policies
    DATA_LINEAGE = "data_lineage"  # Data provenance tracking
    PII = "pii"  # Personally identifiable information

    # Compliance and regulatory
    COMPLIANCE_POLICY = "compliance_policy"  # Compliance rules (SOC2, GDPR, HIPAA)
    AUDIT_LOG = "audit_log"  # Audit trail management
    VENDOR = "vendor"  # Third-party vendor management

    # Team/group management
    TEAM = "team"  # Team-based access control

    # Cost and quota management
    QUOTA = "quota"  # Rate limits and quotas
    COST_CENTER = "cost_center"  # Cost tracking and chargeback
    BUDGET = "budget"  # Budget limits and alerts

    # Session and authentication
    SESSION = "session"  # Active session management
    AUTHENTICATION = "authentication"  # Auth policy management

    # Approval workflows
    APPROVAL = "approval"  # Access request approvals

    # Enterprise infrastructure
    BACKUP = "backup"  # Backup management
    DISASTER_RECOVERY = "disaster_recovery"  # DR procedures
    ROLE = "role"  # Custom role management
    API_KEY = "api_key"  # API key management
    TEMPLATE = "template"  # Workflow template management

    # Workspace management (SME RBAC-lite)
    WORKSPACE = "workspace"  # Workspace-level access control
    WORKSPACE_MEMBER = "workspace_member"  # Workspace member management

    # System operations
    QUEUE = "queue"  # Job queue management
    NOMIC = "nomic"  # Nomic self-improvement loop
    ORCHESTRATION = "orchestration"  # Multi-agent orchestration
    SYSTEM = "system"  # System-wide operations (health, etc.)

    # Autonomous operations
    AUTONOMOUS = "autonomous"  # Autonomous agent operations (triggers, monitoring, learning)
    ALERTS = "alerts"  # Alert management operations

    # Domain specialists
    VERTICALS = "verticals"  # Domain-specific AI specialists (legal, medical, etc.)

    # Interactive features
    CANVAS = "canvas"  # Visual canvas operations
    VERIFICATION = "verification"  # Formal verification operations
    CODEBASE = "codebase"  # Codebase analysis operations

    # Replay management
    REPLAY = "replays"  # Debate replay recordings

    # Breakpoint management
    BREAKPOINT = "breakpoints"  # Debate breakpoint handling (admin-only)

    # User feedback and engagement
    FEEDBACK = "feedback"  # User feedback and NPS data

    # Financial operations
    FINANCE = "finance"  # Financial operations (invoices, payments, AR/AP)
    RECEIPT = "receipts"  # Decision receipts and audit trails
    COST = "costs"  # Cost tracking and optimization

    # Scheduling operations
    SCHEDULER = "scheduler"  # Task scheduling and job management

    # Computer-use operations
    COMPUTER_USE = "computer_use"  # Computer-use orchestration (browser, shell, file access)

    # Additional handler-required resource types
    METRICS = "metrics"  # System and admin metrics
    A2A = "a2a"  # Agent-to-Agent communication protocol
    TRANSCRIPTION = "transcription"  # Speech transcription operations
    RLM = "rlm"  # Recursive Language Models
    REVIEWS = "reviews"  # User reviews and ratings
    AP = "ap"  # Accounts payable automation
    EXPENSES = "expenses"  # Expense management and tracking
    PAYMENTS = "payments"  # Payment processing operations
    HR = "hr"  # Human resources operations
    EMAIL = "email"  # Email management operations
    INTEGRATIONS = "integrations"  # Third-party integration management
    ONBOARDING = "onboarding"  # User onboarding flows
    PARTNER = "partner"  # Partner management
    EVALUATION = "evaluation"  # Evaluation and assessment operations
    PULSE = "pulse"  # Trending topics and pulse monitoring
    PLUGINS = "plugins"  # Plugin installation and management
    LEGAL = "legal"  # Legal document operations
    RECONCILIATION = "reconciliation"  # Financial reconciliation
    FEATURES = "features"  # Feature flag management
    DR = "dr"  # Disaster recovery (alias for handlers)
    EVOLUTION = "evolution"  # Prompt evolution operations
    CROSS_POLLINATION = "cross_pollination"  # Cross-subsystem event bridge and KM sync

    # External gateway integrations
    GATEWAY = "gateway"  # External AI runtime gateways (OpenClaw, etc.)

    # Security operations
    SECURITY = "security"  # CVE, SAST, SBOM, secrets, vulnerability scanning

    # Route-level resource types
    AUDITING = "auditing"  # Red team operations
    BELIEF = "belief"  # Belief network data
    CONSENSUS = "consensus"  # Consensus data
    GALLERY = "gallery"  # Gallery items
    GENESIS = "genesis"  # Genesis operations
    INSIGHTS = "insights"  # System insights
    LABORATORY = "laboratory"  # Laboratory experiments
    LEARNING = "learning"  # Learning data
    MOMENTS = "moments"  # Moments data
    PERSONAS = "personas"  # Persona profiles
    PODCAST = "podcast"  # Podcast content
    RELATIONSHIPS = "relationships"  # Relationship data
    TOURNAMENTS = "tournaments"  # Tournament events

    # Decision plans
    PLANS = "plans"  # Decision plan lifecycle (create, approve, reject)
    AGENT_BRIDGE = "agent_bridge"  # Agent bridge run visibility


class Action(str, Enum):
    """Actions that can be performed on resources."""

    # CRUD operations
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    WRITE = "write"
    DELETE = "delete"
    NOTIFY = "notify"

    # Debate-specific
    RUN = "run"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    FORK = "fork"

    # Agent-specific
    DEPLOY = "deploy"
    CONFIGURE = "configure"

    # User management
    INVITE = "invite"
    REMOVE = "remove"
    CHANGE_ROLE = "change_role"
    IMPERSONATE = "impersonate"

    # Organization
    MANAGE_BILLING = "manage_billing"
    VIEW_AUDIT = "view_audit"
    EXPORT_DATA = "export_data"

    # API
    GENERATE_KEY = "generate_key"
    REVOKE_KEY = "revoke_key"

    # Admin
    SYSTEM_CONFIG = "system_config"
    VIEW_METRICS = "view_metrics"
    MANAGE_FEATURES = "manage_features"

    # Gauntlet-specific
    SIGN = "sign"  # Sign receipts cryptographically
    COMPARE = "compare"  # Compare gauntlet runs
    VERIFY = "verify"  # Verify integrity of chains/proofs

    # Marketplace-specific
    PUBLISH = "publish"  # Publish to marketplace
    IMPORT = "import"  # Import from marketplace
    RATE = "rate"  # Rate templates
    REVIEW = "review"  # Write reviews

    # Analytics-specific
    QUERY = "query"  # Run queries against connected analytics platforms

    # Explainability-specific
    BATCH = "batch"  # Run batch operations

    # Findings-specific
    ASSIGN = "assign"  # Assign to users
    BULK = "bulk"  # Bulk operations

    # Data governance actions
    CLASSIFY = "classify"  # Classify data sensitivity
    REDACT = "redact"  # Redact sensitive data
    MASK = "mask"  # Apply data masking rules

    # Compliance actions
    ENFORCE = "enforce"  # Enforce compliance policies
    STREAM = "stream"  # Stream to external systems (SIEM)
    SEARCH = "search"  # Advanced search capabilities
    CHECK = "check"  # Run compliance checks
    GDPR = "gdpr"  # GDPR compliance operations
    SOC2 = "soc2"  # SOC2 compliance operations
    LEGAL = "legal"  # Legal hold and compliance operations
    AUDIT = "audit"  # Audit operations (distinct from VIEW_AUDIT)
    SECURITY = "security"  # Security administration operations
    SYSTEM = "system"  # System administration operations

    # Control plane actions
    SUBMIT = "submit"  # Submit tasks/requests
    CANCEL = "cancel"  # Cancel pending operations
    DELIBERATE = "deliberate"  # Start deliberation process

    # Connector lifecycle actions
    AUTHORIZE = "authorize"  # Grant OAuth/API credentials
    ROTATE = "rotate"  # Rotate credentials
    TEST = "test"  # Test connection health
    ROLLBACK = "rollback"  # Revert failed operations

    # Team management actions
    ADD_MEMBER = "add_member"  # Add user to team
    REMOVE_MEMBER = "remove_member"  # Remove user from team
    SHARE = "share"  # Share resource with team

    # Quota and cost actions
    SET_LIMIT = "set_limit"  # Set quotas/limits
    CHARGEBACK = "chargeback"  # Assign costs to cost center

    # Session and auth actions
    REVOKE = "revoke"  # Revoke sessions/credentials
    LIST_ACTIVE = "list_active"  # List active sessions
    RESET_PASSWORD = "reset_password"  # noqa: S105 -- enum value (reset user password)
    REQUIRE_MFA = "require_mfa"  # Enforce MFA

    # Approval workflow actions
    REQUEST = "request"  # Request access/approval
    GRANT = "grant"  # Grant approval
    DENY = "deny"  # Deny approval
    APPROVE = "approve"  # Approve financial transactions/documents
    SEND = "send"  # Send notifications/receipts

    # Control plane sub-operations
    AGENTS_READ = "agents.read"  # Read agent registry
    AGENTS_REGISTER = "agents.register"  # Register agents
    AGENTS_UNREGISTER = "agents.unregister"  # Unregister agents
    TASKS_READ = "tasks.read"  # Read task queue
    TASKS_SUBMIT = "tasks.submit"  # Submit tasks
    TASKS_CLAIM = "tasks.claim"  # Claim tasks for processing
    TASKS_COMPLETE = "tasks.complete"  # Mark tasks complete
    HEALTH_READ = "health.read"  # Read health status

    # Enterprise sensitive operations
    OVERRIDE = "override"  # Override quotas/limits
    DISSOLVE = "dissolve"  # Dissolve teams/groups
    LIST_ALL = "list_all"  # List all items (not just own)
    EXPORT_SECRET = "export_secret"  # noqa: S105 -- enum value (export secrets/credentials)
    EXPORT_HISTORY = "export_history"  # Export historical data
    RESTORE = "restore"  # Restore from backup
    EXECUTE = "execute"  # Execute procedures (DR, migrations)
    MANAGE = "manage"  # Manage resources (submit, retry, cancel)
    ADMIN_OP = "admin"  # Full administrative access

    # Computer-use specific actions
    BROWSER = "browser"  # Browser automation (navigate, click, type)
    SHELL = "shell"  # Shell command execution
    FILE_READ = "file_read"  # Read files from filesystem
    FILE_WRITE = "file_write"  # Write files to filesystem
    SCREENSHOT = "screenshot"  # Take screenshots
    NETWORK = "network"  # Network access (HTTP requests, etc.)

    # Skills-specific actions
    INVOKE = "invoke"  # Invoke/execute a skill

    # DR-specific actions
    DRILL = "drill"  # Execute disaster recovery drill

    # Payment-specific actions
    CHARGE = "charge"  # Charge a payment method
    CAPTURE = "capture"  # Capture an authorized payment
    REFUND = "refund"  # Refund a payment
    VOID = "void"  # Void a pending transaction

    # Plugin-specific actions
    INSTALL = "install"  # Install a plugin
    UNINSTALL = "uninstall"  # Uninstall a plugin

    # Gateway sub-operations
    AGENT_CREATE = "agent.create"  # Register external agents
    AGENT_READ = "agent.read"  # View registered agents
    AGENT_DELETE = "agent.delete"  # Remove external agents
    CREDENTIAL_CREATE = "credential.create"  # Store credentials
    CREDENTIAL_READ = "credential.read"  # View credential metadata
    CREDENTIAL_DELETE = "credential.delete"  # Delete credentials
    CREDENTIAL_ROTATE = "credential.rotate"  # Rotate credentials
    HYBRID_DEBATE = "hybrid_debate"  # Execute hybrid debates
    SESSION_CREATE = "sessions.create"
    SESSION_READ = "sessions.read"
    SESSION_DELETE = "sessions.delete"
    ACTION_EXECUTE = "actions.execute"
    ACTION_READ = "actions.read"
    ACTION_CANCEL = "actions.cancel"
    POLICY_READ = "policy.read"
    POLICY_WRITE = "policy.write"
    APPROVAL_READ = "approvals.read"
    APPROVAL_WRITE = "approvals.write"
    METRICS_READ = "metrics.read"
    AUDIT_READ = "audit.read"

    # Wildcard
    ALL = "*"


@dataclass
class Permission:
    """
    Individual permission representing access to perform an action on a resource.

    Attributes:
        id: Unique identifier
        name: Human-readable name (e.g., "Create Debates")
        resource: Resource type this permission applies to
        action: Action allowed by this permission
        description: Detailed description for documentation
        conditions: Optional conditions for ABAC (attribute-based access control)
    """

    id: str
    name: str
    resource: ResourceType
    action: Action
    description: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Generate permission key in format 'resource.action'."""
        return f"{self.resource.value}.{self.action.value}"

    @classmethod
    def from_key(cls, key: str, name: str = "", description: str = "") -> Permission:
        """Create permission from key string like 'debates.create'."""
        resource_str, action_str = key.split(".", 1)
        return cls(
            id=str(uuid4()),
            name=name or key.replace(".", " ").title(),
            resource=ResourceType(resource_str),
            action=Action(action_str),
            description=description,
        )

    def matches(self, resource: ResourceType, action: Action) -> bool:
        """Check if this permission matches the requested resource and action."""
        # Wildcard action matches all
        if self.action == Action.ALL:
            return self.resource == resource
        # Exact match
        return self.resource == resource and self.action == action


@dataclass
class Role:
    """
    Collection of permissions assigned to users.

    Supports hierarchy where a role can inherit from parent roles.

    Attributes:
        id: Unique identifier
        name: Role name (e.g., "admin", "debate_creator")
        display_name: Human-readable display name
        description: Role description
        permissions: Set of permission IDs granted by this role
        parent_roles: Roles this role inherits from
        is_system: Whether this is a built-in system role
        is_custom: Whether this is a custom org-defined role
        org_id: Organization ID for custom roles (None for system roles)
        priority: Role priority for conflict resolution (higher = more privileged)
        metadata: Additional role configuration
    """

    id: str
    name: str
    display_name: str = ""
    description: str = ""
    permissions: set[str] = field(default_factory=set)
    parent_roles: list[str] = field(default_factory=list)
    is_system: bool = True
    is_custom: bool = False
    org_id: str | None = None
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()

    def has_permission(self, permission_id: str) -> bool:
        """Check if role directly has a permission (not including inheritance)."""
        return permission_id in self.permissions

    def add_permission(self, permission_id: str) -> None:
        """Add a permission to this role."""
        self.permissions.add(permission_id)

    def remove_permission(self, permission_id: str) -> None:
        """Remove a permission from this role."""
        self.permissions.discard(permission_id)


def _permission_candidates(permission_key: str) -> set[str]:
    """Return equivalent permission key candidates for colon/dot formats."""
    candidates = {permission_key}
    if ":" in permission_key:
        candidates.add(permission_key.replace(":", "."))
    if "." in permission_key:
        candidates.add(permission_key.replace(".", ":"))
    return candidates


def _resource_candidates(permission_key: str) -> set[str]:
    """Return resource name candidates from either colon or dot formats."""
    resources: set[str] = set()
    for candidate in _permission_candidates(permission_key):
        if "." in candidate:
            resources.add(candidate.split(".", 1)[0])
        if ":" in candidate:
            resources.add(candidate.split(":", 1)[0])
    return resources


@dataclass
class RoleAssignment:
    """
    Assignment of a role to a user, scoped to an organization.

    Attributes:
        id: Unique identifier
        user_id: User receiving the role
        role_id: Role being assigned
        org_id: Organization scope (None for platform-wide roles)
        assigned_by: User who made the assignment
        assigned_at: When the assignment was made
        expires_at: When the assignment expires (None = never)
        is_active: Whether the assignment is currently active
        conditions: Additional conditions for the assignment
        metadata: Additional assignment data
    """

    id: str
    user_id: str
    role_id: str
    org_id: str | None = None
    assigned_by: str | None = None
    assigned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    is_active: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the assignment has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if the assignment is currently valid."""
        return self.is_active and not self.is_expired


@dataclass
class APIKeyScope:
    """
    Scope definition for API keys to limit their permissions.

    Attributes:
        permissions: Set of permission keys allowed for this key
        resources: Specific resource IDs the key can access (None = all)
        rate_limit: Custom rate limit for this key
        expires_at: Key expiration time
        ip_whitelist: Allowed IP addresses (None = all)
    """

    permissions: set[str] = field(default_factory=set)
    resources: dict[ResourceType, set[str]] | None = None
    rate_limit: int | None = None
    expires_at: datetime | None = None
    ip_whitelist: set[str] | None = None

    def allows_permission(self, permission_key: str) -> bool:
        """Check if this scope allows a permission."""
        # Empty permissions = full access
        if not self.permissions:
            return True
        # Check for wildcard
        if "*" in self.permissions:
            return True
        # Check exact match (colon/dot compatible)
        if any(
            candidate in self.permissions for candidate in _permission_candidates(permission_key)
        ):
            return True
        # Check resource wildcard (e.g., "debates.*" or "debates:*")
        for resource in _resource_candidates(permission_key):
            if f"{resource}.*" in self.permissions or f"{resource}:*" in self.permissions:
                return True
        return False

    def allows_resource(self, resource_type: ResourceType, resource_id: str) -> bool:
        """Check if this scope allows access to a specific resource."""
        if self.resources is None:
            return True
        if resource_type not in self.resources:
            return True
        return resource_id in self.resources[resource_type]


@dataclass
class AuthorizationContext:
    """
    Context for authorization decisions.

    Attributes:
        user_id: ID of the user making the request
        user_email: Email of the user (optional, for display/audit)
        org_id: Organization context
        workspace_id: Workspace context for multi-tenant workspaces
        roles: User's active roles
        permissions: Resolved permissions from roles
        api_key_scope: Scope if using API key (None for session auth)
        ip_address: Request IP address
        user_agent: Request user agent
        request_id: Unique request identifier for tracing
        timestamp: When the authorization context was created
    """

    user_id: str
    user_email: str | None = None
    org_id: str | None = None
    workspace_id: str | None = None
    roles: set[str] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)
    api_key_scope: APIKeyScope | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def has_permission(self, permission_key: str) -> bool:
        """Check if context has a permission."""
        # Check API key scope first if present
        if self.api_key_scope and not self.api_key_scope.allows_permission(permission_key):
            return False
        # Check resolved permissions
        if any(
            candidate in self.permissions for candidate in _permission_candidates(permission_key)
        ):
            return True
        # Check for wildcard
        for resource in _resource_candidates(permission_key):
            if f"{resource}.*" in self.permissions or f"{resource}:*" in self.permissions:
                return True
        if "*" in self.permissions:
            return True
        return False

    def has_role(self, role_name: str) -> bool:
        """Check if context has a specific role."""
        return role_name in self.roles

    def has_any_role(self, *role_names: str) -> bool:
        """Check if context has any of the specified roles."""
        return bool(self.roles & set(role_names))


@dataclass
class AuthorizationDecision:
    """
    Result of an authorization check.

    Attributes:
        allowed: Whether access is allowed
        reason: Explanation of the decision
        permission_key: Permission that was checked
        resource_id: Specific resource if applicable
        context: Authorization context used
        checked_at: When the check was performed
        cached: Whether the decision was from cache
    """

    allowed: bool
    reason: str
    permission_key: str
    resource_id: str | None = None
    context: AuthorizationContext | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "permission_key": self.permission_key,
            "resource_id": self.resource_id,
            "user_id": self.context.user_id if self.context else None,
            "org_id": self.context.org_id if self.context else None,
            "request_id": self.context.request_id if self.context else None,
            "checked_at": self.checked_at.isoformat(),
            "cached": self.cached,
        }
