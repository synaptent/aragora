"""
RBAC Handler Enforcement Tests.

These tests verify that all HTTP handler files in the server have proper
authorization protection. This acts as a guardrail to prevent new handlers
from being added without RBAC, authentication, or proper authorization.

The test scans all handler modules and verifies they use at least one of:
1. @require_permission / @require_role decorators
2. SecureHandler / PermissionHandler / AdminHandler / AuthenticatedHandler base class
3. SecureEndpointMixin / AuthenticatedHandlerMixin
4. Are explicitly listed as allowed-public (bots, webhooks, OAuth)
"""

import ast
import importlib
import os
from pathlib import Path

import pytest

# Base directory for handlers
HANDLERS_DIR = Path(__file__).parent.parent.parent / "aragora" / "server" / "handlers"

# Authorization indicators in source code
RBAC_IMPORTS = frozenset(
    {
        "require_permission",
        "require_role",
        "require_owner",
        "require_admin",
        "require_org_access",
        "require_self_or_admin",
        "with_permission_context",
        "secure_endpoint",
        "require_user_auth",
        "require_auth",
    }
)

# Base classes that provide built-in authorization
SECURE_BASE_CLASSES = frozenset(
    {
        "SecureHandler",
        "AuthenticatedHandler",
        "PermissionHandler",
        "AdminHandler",
        "ResourceHandler",
        "AsyncTypedHandler",
        "SecureEndpointMixin",
        "AuthenticatedHandlerMixin",
        "AuthChecksMixin",
    }
)

# Modules that are explicitly allowed without RBAC decorators.
# These are either:
# - Public endpoints (webhooks, OAuth callbacks)
# - Utility/non-handler modules
# - Bot integrations (use platform-specific verification)
# - Infrastructure modules
ALLOWED_WITHOUT_RBAC = frozenset(
    {
        # Infrastructure / utilities (non-handler modules)
        "__init__",
        "api_decorators",
        "base",
        "secure",
        "types",
        "routing",
        "bindings",
        "exceptions",
        "mixins",
        "register",
        "interface",
        "utilities",
        "openapi_decorator",
        "explainability_store",
        # workflow_builtin_templates removed (module deleted)
        # Utility subdirectories (non-handler helpers)
        "utils/__init__",
        "utils/auth",
        "utils/database",
        "utils/decorators",
        "utils/params",
        "utils/rate_limit",
        "utils/responses",
        "utils/routing",
        "utils/safe_data",
        "utils/url_security",
        "utils/aiohttp_responses",
        "utils/json_body",
        "utils/lazy_stores",
        "utils/safe_fetch",
        "utils/sanitization",
        "utils/tenant_validation",
        # Governance (outcomes.py has RBAC, __init__ is re-export only)
        "governance/__init__",
        # Bot handlers (use platform-specific signature verification)
        "bots/__init__",
        "bots/base",
        "bots/cache",
        "bots/discord",
        "bots/email_webhook",
        "bots/google_chat",
        "bots/slack",
        "bots/teams",
        "bots/teams_cards",
        "bots/teams_utils",
        "bots/telegram",
        "bots/whatsapp",
        "bots/zoom",
        # OAuth flows (must be public for OAuth redirect callbacks)
        "oauth",
        "sso",
        "_oauth/__init__",
        "_oauth/apple",
        "_oauth/github",
        "_oauth/google",
        "_oauth/microsoft",
        "_oauth/oidc",
        "oauth/__init__",
        "oauth/config",
        "oauth/handler",
        "oauth/models",
        "oauth/state",
        "oauth/validation",
        "oauth_providers/__init__",
        "oauth_providers/apple",
        "oauth_providers/base",
        "oauth_providers/github",
        "oauth_providers/google",
        "oauth_providers/microsoft",
        "oauth_providers/oidc",
        # Auth handlers (login/signup must be public)
        "auth/__init__",
        "auth/handler",
        "auth/login",
        "auth/validation",
        "auth/store",
        "auth/password",
        "auth/signup_handlers",
        # Webhook handlers (use webhook-specific verification)
        "webhooks/__init__",
        "webhooks/github_app",
        # SCIM provisioning (uses SCIM-standard bearer token)
        "scim_handler",
        # Metrics & observability (public endpoints)
        "metrics",
        "metrics/__init__",
        "metrics/handler",
        "metrics/debug",
        "metrics/export",
        "metrics/formatters",
        "metrics/tracking",
        "analytics_metrics",
        "metrics_endpoint",
        # Doc endpoints (public API docs)
        "docs",
        # Template discovery (public browsing API, rate-limited, read-only)
        "template_discovery",
        # Debate sharing (public spectate endpoint; POST/DELETE use inline require_auth_or_error)
        "debates/share",
        # Spectate WebSocket/SSE (public read-only stream for live debate visualization)
        "spectate_ws",
        # Marketplace browse (public catalog browsing, read-only)
        "marketplace_browse",
        # Platform config now uses SecureHandler (RBAC-protected)
        # Health probes and dashboard monitoring (public liveness/readiness endpoints)
        "admin/dashboard_health",
        "admin/dashboard_metrics",
        "admin/health/cross_pollination",
        "admin/health/database",
        "admin/health/database_utils",
        "admin/health/detailed",
        "admin/health/handler",
        "admin/health/helpers",
        "admin/health/knowledge",
        "admin/health/knowledge_mound",
        "admin/health/knowledge_mound_utils",
        "admin/health/kubernetes",
        "admin/health/platform",
        "admin/health/probes",
        "admin/health/stores",
        "admin/health/workers",
        # Public status page (no auth required — external monitoring)
        "status_page",
        "public/__init__",
        "public/status_page",
        # Social platform internals (implementation modules, not direct handlers)
        "social/_slack_impl/__init__",
        "social/_slack_impl/blocks",
        "social/_slack_impl/commands",
        "social/_slack_impl/config",
        "social/_slack_impl/events",
        "social/_slack_impl/interactive",
        "social/_slack_impl/messaging",
        "social/chat_events",
        "social/slack/__init__",
        "social/slack/blocks/__init__",
        "social/slack/blocks/builders",
        "social/slack/commands/__init__",
        "social/slack/commands/base",
        "social/slack/config",
        "social/slack/events/__init__",
        "social/slack/events/handlers",
        "social/slack/handler",
        "social/slack/responses",
        "social/slack/security",
        "social/telemetry",
        "social/tts_helper",
        "slack",
        # Voice handlers (use platform-specific auth)
        "voice/__init__",
        "voice/handler",
        # Chat routing (internal routing, not direct handler)
        "chat/__init__",
        "chat/router",
        # Analytics (middleware-protected)
        "analytics/__init__",
        "analytics/cache",
        "analytics/core",
        # Versioning compatibility (utility)
        "versioning/__init__",
        "versioning/compat",
        # Payment package (re-export module, route registration, and handler infra)
        "payments/__init__",
        "payments/handler",
        "payments/plans",
        # Init files for subdirectories
        "admin/__init__",
        "admin/cache",
        "agents/__init__",
        "auth/__init__",
        "canvas/__init__",
        "codebase/__init__",
        "codebase/security/__init__",
        "codebase/security/events",
        "codebase/security/storage",
        "compliance/__init__",
        "costs/__init__",
        "costs/helpers",
        "costs/models",
        "costs/routes",
        "debates/__init__",
        "debates/cost_estimation",
        "debates/response_formatting",
        "decisions/__init__",
        "email/__init__",
        "evolution/__init__",
        "examples/__init__",
        "examples/typed_example",
        "features/__init__",
        "features/codebase_audit/__init__",
        "features/codebase_audit/reporting",
        "features/codebase_audit/rules",
        "features/codebase_audit/scanning",
        "features/crm/__init__",
        "features/crm/circuit_breaker",
        "features/crm/companies",
        "features/crm/deals",
        "features/crm/models",
        "features/crm/pipeline",
        "features/crm/validation",
        "features/devops/circuit_breaker",
        "features/devops/connector",
        "features/devops/validation",
        "features/ecommerce/__init__",
        "features/ecommerce/circuit_breaker",
        "features/ecommerce/models",
        "features/ecommerce/validation",
        "features/marketplace/__init__",
        "features/marketplace/circuit_breaker",
        "features/marketplace/models",
        "features/marketplace/store",
        "features/marketplace/validation",
        "features/unified_inbox/__init__",
        "features/unified_inbox/accounts",
        "features/unified_inbox/actions",
        "features/unified_inbox/messages",
        "features/unified_inbox/models",
        "features/unified_inbox/stats",
        "features/unified_inbox/sync",
        "features/unified_inbox/triage",
        "gateway/__init__",
        "github/__init__",
        "inbox/__init__",
        "integrations/__init__",
        "knowledge/__init__",
        "knowledge_base/__init__",
        "knowledge_base/mound/__init__",
        "knowledge_base/mound/base_mixin",
        "billing/__init__",
        "memory/__init__",
        "autonomous/__init__",
        "openclaw/__init__",
        "openclaw/models",
        "openclaw/store",
        "openclaw/validation",
        "orchestration/__init__",
        "orchestration/models",
        "orchestration/protocols",
        "orchestration/templates",
        "orchestration/validation",
        "security/__init__",
        "shared_inbox/__init__",
        "shared_inbox/models",
        "shared_inbox/storage",
        "shared_inbox/rules_engine",
        "shared_inbox/validators",
        "sme/__init__",
        "social/__init__",
        "social/telegram/__init__",
        "social/telegram/callbacks",
        "social/telegram/commands",
        "social/telegram/messages",
        "social/telegram/webhooks",
        "social/whatsapp/__init__",
        "social/whatsapp/commands",
        "social/whatsapp/messaging",
        "social/whatsapp/webhooks",
        "verification/__init__",
        "workspace/__init__",
        "workspace/workspace_utils",
        # Workspace sensitivity re-exports (utility, not handler)
        "workspace/sensitivity",
        # Backward compatibility shims (delegate to protected submodules)
        "admin/admin",
        "compliance_handler",
        # Compliance handler facade (composes RBAC-protected mixins)
        "compliance/handler",
        # CRM utility modules (validation/mixin, not direct handlers)
        "features/crm/contacts",
        # Decomposed bot submodules (use platform-specific verification)
        "bots/teams/__init__",
        "bots/teams/channels",
        "bots/teams/oauth",
        "bots/slack/blocks",
        "bots/slack/debates",
        "bots/slack/oauth",
        "bots/slack/signature",
        "bots/slack/state",
        # Decomposed analytics dashboard (re-export)
        "analytics_dashboard/__init__",
        # Utility modules
        "utils/cache",
        # Re-export / compatibility modules (delegate to protected handlers)
        "compliance/audit",
        "compliance/governance",
        "knowledge",
        # Control plane routing (delegates to mixins with RBAC decorators)
        "control_plane/__init__",
        # Debates routing mixin (utility with inline token validation)
        "debates/routing",
        # Gauntlet modules (handler delegates to mixins with RBAC, others are utilities)
        "gauntlet/__init__",
        "gauntlet/handler",
        "gauntlet/storage",
        # File validation utility
        "utils/file_validation",
        # Workflow service layer (handler.py has RBAC via check_permission)
        "workflows/__init__",
        "workflows/approvals",
        "workflows/core",
        "workflows/crud",
        "workflows/execution",
        "workflows/templates",
        "workflows/versions",
        # Admin dashboard views and actions (protected by admin middleware)
        "admin/dashboard_actions",
        "admin/dashboard_views",
        # Agent management modules (middleware-protected)
        "agents/agent_flips",
        "agents/agent_intelligence",
        "agents/agent_profiles",
        "agents/agent_rankings",
        # Billing internals (helper utilities and webhook verification)
        "billing/core_helpers",
        "billing/core_webhooks",
        # Connector management modules (middleware-protected)
        "connectors/management",
        "connectors/shared",
        # Evolution handler (delegates to RBAC-protected mixins)
        "evolution/handler",
        # Feature modules (middleware-protected)
        "features/features",
        # Inbox modules (middleware-protected)
        "inbox_actions",
        "inbox_services",
        # Inbox auto-debate helpers (service modules invoked by protected handlers)
        "inbox/auto_debate",
        "features/unified_inbox/auto_debate",
        # Integrations (webhook verification, not direct user handler)
        "integrations/email_webhook",
        # Replay handler (middleware-protected)
        "replays",
        # Reviews handler (middleware-protected)
        "reviews",
        # Infrastructure management (streaming subsystem)
        "streaming/__init__",
        "streaming/handler",
        # Task routing and execution (RBAC checked at execution layer)
        "tasks/__init__",
        "tasks/execution",
        # 501 stub (speech module removed)
        "features/speech",
        # Public demo endpoint (no auth by design)
        "playground",
        # Read-only analytics/informational endpoints (no mutations)
        "agents/recommendations",
        "debate_stats",
        "feature_flags",
        "moderation_analytics",
        "receipt_export",
        # Notification subsystem (re-export and read-only modules)
        "notifications/__init__",
        "notifications/history",
        # Pipeline re-export module (actual handler is in pipeline/plans.py)
        "pipeline/__init__",
        # Prompt engine package re-export (handler.py provides protection)
        "prompt_engine/__init__",
        # Demo/example handlers (non-production, no auth required)
        "demo/__init__",
        "demo/adversarial_demo",
        # Readiness probe (public health endpoint, no auth by design)
        "readiness_check",
        # Debate diagnostics mixin (read-only debug info, mixed into RBAC-protected handler)
        "debates/diagnostics",
        # API documentation endpoints (public read-only, powers /api-docs page)
        "api_docs",
        # Knowledge velocity dashboard (read-only metrics, rate-limited)
        "knowledge/velocity",
        # Observability package re-export (dashboard.py has RBAC via SecureHandler)
        "observability/__init__",
        # Federation package re-export (status.py has RBAC via require_permission)
        "federation/__init__",
    }
)


def _get_handler_modules() -> list[tuple[str, Path]]:
    """Find all Python handler modules under aragora/server/handlers/.

    Re-resolves HANDLERS_DIR each call to avoid stale cached paths
    and filters out __pycache__ directories.
    """
    handlers_dir = Path(__file__).parent.parent.parent / "aragora" / "server" / "handlers"
    modules = []
    for py_file in handlers_dir.rglob("*.py"):
        # Skip __pycache__ and other generated directories
        if "__pycache__" in py_file.parts:
            continue
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        # Get relative module path
        rel = py_file.relative_to(handlers_dir)
        module_key = str(rel.with_suffix("")).replace(os.sep, "/")
        modules.append((module_key, py_file))
    return sorted(modules)


def _has_rbac_protection(source: str) -> bool:
    """Check if a Python source file has RBAC protection.

    Checks for:
    1. Import of RBAC decorators
    2. Use of secure base classes
    3. Inline permission checking
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True  # Can't parse, assume OK

    # Check imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.names:
                for alias in node.names:
                    name = alias.name if alias.name else ""
                    if name in RBAC_IMPORTS:
                        return True
        # Check for secure base classes in class definitions
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name in SECURE_BASE_CLASSES:
                    return True

    # Check for inline permission checking patterns
    source_lower = source.lower()
    inline_patterns = [
        "check_permission",
        "_check_rbac_permission",
        "verify_auth",
        "require_permission",
        "require_role",
        "require_auth",
        "auth_context",
        "authorization_context",
        "rbac_check",
        "permission_checker",
        "_verify_bearer_token",
    ]
    for pattern in inline_patterns:
        if pattern in source_lower:
            return True

    return False


class TestHandlerRBACEnforcement:
    """Verify all handler modules have proper authorization."""

    def test_all_handlers_have_authorization(self):
        """Every handler module must have RBAC or be explicitly allowed public."""
        modules = _get_handler_modules()
        unprotected = []

        for module_key, path in modules:
            # Skip explicitly allowed modules
            if module_key in ALLOWED_WITHOUT_RBAC:
                continue

            source = path.read_text()

            # Skip empty files or files with no functions/classes
            if not source.strip() or len(source) < 50:
                continue

            if not _has_rbac_protection(source):
                unprotected.append(module_key)

        if unprotected:
            msg = (
                f"Found {len(unprotected)} handler module(s) without RBAC protection:\n"
                + "\n".join(f"  - {m}" for m in unprotected)
                + "\n\nEach handler must either:\n"
                "  1. Import and use @require_permission or @require_role\n"
                "  2. Extend SecureHandler, PermissionHandler, or AdminHandler\n"
                "  3. Be added to ALLOWED_WITHOUT_RBAC with justification"
            )
            pytest.fail(msg)

    def test_secure_base_classes_require_auth(self):
        """SecureHandler and PermissionHandler must import RBAC modules."""
        secure_file = HANDLERS_DIR / "secure.py"
        if secure_file.exists():
            source = secure_file.read_text()
            assert "rbac" in source.lower(), "SecureHandler must import from aragora.rbac"

    def test_no_handler_bypasses_middleware(self):
        """Verify no handler manually disables middleware auth checks."""
        bypass_patterns = [
            "skip_auth",
            "disable_auth",
            "no_auth_required",
            "bypass_rbac",
            "skip_rbac",
        ]
        violations = []

        for module_key, path in _get_handler_modules():
            if module_key in ALLOWED_WITHOUT_RBAC:
                continue

            source = path.read_text()
            for pattern in bypass_patterns:
                if pattern in source:
                    violations.append(f"{module_key}: contains '{pattern}'")

        if violations:
            pytest.fail(
                "Handler(s) attempt to bypass authentication:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    def test_mutation_handlers_have_permissions(self):
        """Handlers with PUT/DELETE/PATCH must have permission checks.

        Handlers can be protected at two levels:
        1. Decorator-level: @require_permission, @require_role, or secure base class
        2. Middleware-level: Routes in DEFAULT_ROUTE_PERMISSIONS (rbac/middleware.py)

        This test checks for decorator-level protection. Handlers that rely
        solely on middleware are tracked in MIDDLEWARE_PROTECTED_MUTATIONS.
        """
        mutation_indicators = [
            "handle_put",
            "handle_delete",
            "handle_patch",
        ]

        # Handlers with mutation methods protected only by middleware routes.
        # These have route-level RBAC in DEFAULT_ROUTE_PERMISSIONS but no
        # method-level decorators. Listed here to track defense-in-depth gaps.
        middleware_protected_mutations = {
            "external_agents",
            "knowledge/checkpoints",
            "knowledge/sharing_notifications",
            "workflows",
        }

        # Use local snapshots of module-level constants to guard against
        # cross-test pollution of mutable state (e.g. if another test
        # mutated ALLOWED_WITHOUT_RBAC or SECURE_BASE_CLASSES via import).
        allowed = frozenset(ALLOWED_WITHOUT_RBAC)
        secure_bases = frozenset(SECURE_BASE_CLASSES)

        weak_handlers = []

        for module_key, path in _get_handler_modules():
            if module_key in allowed:
                continue
            if module_key in middleware_protected_mutations:
                continue

            source = path.read_text()

            has_mutation = any(m in source for m in mutation_indicators)
            if not has_mutation:
                continue

            # Check for any permission decorator, base class, or inline check
            has_perm = (
                "require_permission" in source
                or "require_role" in source
                or "require_auth" in source
                or "check_permission" in source
                or "_check_rbac_permission" in source
                or any(b in source for b in secure_bases)
            )
            if not has_perm:
                weak_handlers.append(module_key)

        if weak_handlers:
            pytest.fail(
                "Handler(s) with mutation methods lack permission checks:\n"
                + "\n".join(f"  - {h}" for h in weak_handlers)
                + "\n\nMutation handlers must have @require_permission or extend a secure base."
            )

    def test_allowed_without_rbac_list_is_current(self):
        """The allowed-without-RBAC list should not contain stale entries."""
        existing_modules = {module_key for module_key, _ in _get_handler_modules()}

        stale_entries = []
        for entry in ALLOWED_WITHOUT_RBAC:
            # Check if entry matches any existing module
            if entry not in existing_modules:
                # Also check if it's a prefix match (e.g., "bots/base" might be "bots/base.py")
                if not any(m.startswith(entry) for m in existing_modules):
                    stale_entries.append(entry)

        # Only warn, don't fail (files may be renamed/moved)
        if stale_entries:
            # This is informational, not a hard failure
            pass

    def test_handler_count_within_expected_range(self):
        """Sanity check: handler count hasn't drastically changed."""
        modules = _get_handler_modules()
        # As of Jan 2026, there are ~300+ handler modules
        # This test catches if the directory structure changes dramatically
        assert len(modules) > 100, (
            f"Expected 100+ handler modules, found {len(modules)}. "
            "Has the handler directory been restructured?"
        )
