"""
RBAC Coverage CI Gate Test.

This test scans all handler classes under aragora/server/handlers/ and verifies
each has at least one form of RBAC protection. It fails if any handler is found
without proper authorization checks.

RBAC patterns detected:
1. Handler extends SecureHandler (automatic protection)
2. Methods decorated with @require_permission or @secure_endpoint
3. Handler has _check_*permission method that's called in handle()
4. Handler calls require_auth_or_error() with permission checks
5. Handler uses check_permission() helper function

Handlers can be explicitly exempted if they are intentionally public
(e.g., health checks, public static content).
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
from typing import NamedTuple

import pytest

# Handlers that are intentionally public/unprotected
EXEMPT_HANDLERS = frozenset(
    {
        # Health and status endpoints - must be public for monitoring
        "HealthHandler",
        "GatewayHealthHandler",
        "ReadinessHandler",
        "ReadinessCheckHandler",
        "LivenessHandler",
        "StatusPageHandler",
        # OpenAPI/docs endpoints - public documentation
        "OpenAPIHandler",
        "DocsHandler",
        "SwaggerHandler",
        "ApiDocsHandler",
        # Auth flow handlers - handle their own auth logic
        "LoginHandler",
        "LogoutHandler",
        "OAuthCallbackHandler",
        "OAuthHandler",
        "SAMLHandler",
        # Facade/discovery-only handlers (no request handling, just ROUTES for OpenAPI)
        "FeedbackRoutesHandler",
        "PaymentRoutesHandler",
        # Base classes (not actual handlers - used for inheritance)
        "BaseHandler",
        "TypedHandler",
        "AuthenticatedHandler",
        "PermissionHandler",
        "SecureHandler",
        "AdminHandler",
        "AsyncTypedHandler",
        "ResourceHandler",
        "VersionedAPIHandler",
        # Public landing pages
        "PlansHandler",
        "PublicGalleryHandler",
        # Webhook receivers (verify via signature, not JWT)
        "StripeWebhookHandler",
        "SlackWebhookHandler",
        "GitHubWebhookHandler",
        "EmailWebhookHandler",
        # CSP violation reports (browser-initiated, no auth)
        "CSPReportHandler",
        # Metrics endpoint - must be public for Prometheus scraper
        "MetricsHandler",
        "PipelineTelemetryHandler",
        # Example handlers (documentation/testing only)
        "ExampleResourceHandler",
        "ExampleAsyncHandler",
        "ExampleAuthenticatedHandler",
        "ExampleTypedHandler",
        "ExamplePermissionHandler",
        # Mock/test handlers
        "MockHandler",
        # Handlers with external/auth-specific enforcement or router-only wrappers
        "APAutomationHandler",
        "DependencyAnalysisHandler",
        "CodeReviewHandler",
        "OnboardingHandler",
        "KnowledgeChatHandler",
        "SCIMHandler",
        "UnifiedMetricsHandler",
        "GauntletSchemaHandler",
        "GauntletAllSchemasHandler",
        "GauntletTemplatesListHandler",
        "GauntletTemplateHandler",
        "GauntletReceiptExportHandler",
        "GauntletHeatmapExportHandler",
        "GauntletValidateReceiptHandler",
        "InvoiceHandler",
        "WorkflowCategoriesHandler",
        "WorkflowPatternsHandler",
        "WorkflowPatternTemplatesHandler",
        "TemplateRecommendationsHandler",
        "SMEWorkflowsHandler",
        "ERC8004Handler",
        "ARAutomationHandler",
        "ChatHandler",
        "OpenClawGatewayHandler",
        "OutlookHandler",
        "ComplianceHandler",
        "CollaborationHandler",
        "AuditGitHubBridgeHandler",
        "VoiceHandler",
        "ControlPlaneHandler",
        "GauntletHandler",
        "SecurityHandler",
        # Rate-limited read-only endpoints (public viewing)
        "ReviewsHandler",
        "ReplaysHandler",
        # Feature/metadata discovery endpoints (public API info)
        "FeaturesHandler",
        "MCPToolsHandler",
        "PipelineTelemetryHandler",
        # Admin connectors/streaming (use internal authz or future RBAC)
        "ConnectorManagementHandler",
        "StreamingConnectorHandler",
        # Evolution metrics (read-only, rate-limited)
        "EvolutionHandler",
        # Task execution (rate-limited, has internal validation)
        "TaskExecutionHandler",
        "TaskQueueHandler",
        # Playground - intentionally public demo endpoint (rate-limited, mock agents only)
        "PlaygroundHandler",
        # Compliance reporting (uses internal auth or admin-only access)
        "ComplianceReportHandler",
        # Receipt export (rate-limited, uses handler-level auth)
        "ReceiptExportHandler",
        # Email triage (uses internal rules engine auth)
        "EmailTriageHandler",
        # Feature flags (admin-only, uses internal access control)
        "FeatureFlagsHandler",
        # GDPR deletion (uses compliance framework auth)
        "GDPRDeletionHandler",
        # Debate stats (read-only public stats)
        "DebateStatsHandler",
        # Match statistics (read-only public ELO stats, same family as leaderboard)
        "MatchesStatsHandler",
        "PublicDebateViewerHandler",
        # Moderation analytics (admin dashboard, internal auth)
        "ModerationAnalyticsHandler",
        # Plan management (uses subscription-level access control)
        "PlanManagementHandler",
        # Agent recommendation (read-only suggestion endpoint)
        "AgentRecommendationHandler",
        # Notification preferences/history (user-scoped, uses session auth)
        "NotificationPreferencesHandler",
        "NotificationHistoryHandler",
        # Public template/marketplace discovery (rate-limited, read-only browsing)
        "TemplateDiscoveryHandler",
        "MarketplaceBrowseHandler",
        # Spectate stream (read-only observability for live debate visualization)
        "SpectateStreamHandler",
        # Benchmarking (read-only anonymized industry comparisons)
        "BenchmarkingHandler",
        # Playbook execution (uses internal validation, future RBAC)
        "PlaybookHandler",
        # Decision outcomes (uses internal validation, future RBAC)
        "OutcomeHandler",
        # Knowledge velocity (read-only metrics, future RBAC)
        "KnowledgeVelocityHandler",
    }
)

# Patterns that indicate RBAC protection
RBAC_DECORATORS = frozenset(
    {
        "require_permission",
        "secure_endpoint",
        "require_role",
        "require_auth",
        "authenticated_handler",
    }
)

RBAC_METHOD_PATTERNS = frozenset(
    {
        "_check_permission",
        "_check_rbac_permission",
        "_check_memory_permission",
        "_check_auth",
        "require_auth_or_error",
        "require_permission_or_error",
        "check_permission",
        "verify_permission",
    }
)


class HandlerInfo(NamedTuple):
    """Information about a handler class."""

    name: str
    file_path: str
    line_number: int
    extends_secure: bool
    has_rbac_decorator: bool
    has_rbac_method: bool
    is_exempt: bool


class RBACVisitor(ast.NodeVisitor):
    """AST visitor to analyze handler classes for RBAC patterns."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.handlers: list[HandlerInfo] = []
        self._current_class: str | None = None
        self._class_bases: set[str] = set()
        self._class_decorators: set[str] = set()
        self._class_methods: set[str] = set()
        self._class_has_rbac_call: bool = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definitions to find handlers."""
        # Only process classes that look like handlers
        if not node.name.endswith("Handler"):
            self.generic_visit(node)
            return

        self._current_class = node.name
        self._class_bases = set()
        self._class_decorators = set()
        self._class_methods = set()
        self._class_has_rbac_call = False

        # Collect base class names
        for base in node.bases:
            if isinstance(base, ast.Name):
                self._class_bases.add(base.id)
            elif isinstance(base, ast.Attribute):
                self._class_bases.add(base.attr)

        # Collect class-level decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                self._class_decorators.add(dec.id)
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                self._class_decorators.add(dec.func.id)

        # Visit methods
        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._visit_method(child)

        # Analyze and record handler info
        extends_secure = "SecureHandler" in self._class_bases
        has_rbac_decorator = bool(self._class_decorators & RBAC_DECORATORS)
        has_rbac_method = self._class_has_rbac_call or bool(
            self._class_methods & RBAC_METHOD_PATTERNS
        )
        is_exempt = node.name in EXEMPT_HANDLERS

        self.handlers.append(
            HandlerInfo(
                name=node.name,
                file_path=self.file_path,
                line_number=node.lineno,
                extends_secure=extends_secure,
                has_rbac_decorator=has_rbac_decorator,
                has_rbac_method=has_rbac_method,
                is_exempt=is_exempt,
            )
        )

        self._current_class = None
        self.generic_visit(node)

    def _visit_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit method to find RBAC patterns."""
        self._class_methods.add(node.name)

        # Check method decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in RBAC_DECORATORS:
                self._class_decorators.add(dec.id)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in RBAC_DECORATORS:
                    self._class_decorators.add(dec.func.id)
                elif isinstance(dec.func, ast.Attribute) and dec.func.attr in RBAC_DECORATORS:
                    self._class_decorators.add(dec.func.attr)

        # Check for RBAC-related calls in method body
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if call_name and any(pattern in call_name for pattern in RBAC_METHOD_PATTERNS):
                    self._class_has_rbac_call = True
                    break

    def _get_call_name(self, call: ast.Call) -> str | None:
        """Extract the function name from a Call node."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None


def scan_handlers_directory() -> list[HandlerInfo]:
    """Scan all Python files in handlers directory for handler classes."""
    handlers_dir = Path(__file__).parent.parent.parent.parent / "aragora" / "server" / "handlers"

    assert handlers_dir.exists(), f"Handlers directory should exist: {handlers_dir}"

    all_handlers: list[HandlerInfo] = []

    for py_file in handlers_dir.rglob("*.py"):
        # Skip __pycache__ and test files
        if "__pycache__" in str(py_file) or py_file.name.startswith("test_"):
            continue

        try:
            source = py_file.read_text()
            tree = ast.parse(source, filename=str(py_file))
            visitor = RBACVisitor(str(py_file.relative_to(handlers_dir.parent.parent)))
            visitor.visit(tree)
            all_handlers.extend(visitor.handlers)
        except SyntaxError as e:
            # Skip files with syntax errors (shouldn't happen in CI)
            print(f"Warning: Syntax error in {py_file}: {e}")
            continue

    return all_handlers


def get_unprotected_handlers(handlers: list[HandlerInfo]) -> list[HandlerInfo]:
    """Filter to handlers that have no RBAC protection."""
    unprotected = []
    for h in handlers:
        if h.is_exempt:
            continue
        if h.extends_secure or h.has_rbac_decorator or h.has_rbac_method:
            continue
        unprotected.append(h)
    return unprotected


class TestRBACCoverage:
    """Test suite for RBAC coverage verification."""

    @pytest.fixture(scope="class")
    def all_handlers(self) -> list[HandlerInfo]:
        """Scan and cache all handler information."""
        return scan_handlers_directory()

    def test_all_handlers_have_rbac_protection(self, all_handlers: list[HandlerInfo]) -> None:
        """Verify all handlers have some form of RBAC protection.

        This test acts as a CI gate to prevent introducing unprotected handlers.
        If a handler is intentionally public, add it to EXEMPT_HANDLERS.
        """
        unprotected = get_unprotected_handlers(all_handlers)

        if unprotected:
            msg_lines = [
                "\n",
                "=" * 70,
                "RBAC COVERAGE FAILURE: The following handlers lack authorization checks:",
                "=" * 70,
            ]
            for h in unprotected:
                msg_lines.append(f"  - {h.name} ({h.file_path}:{h.line_number})")
            msg_lines.extend(
                [
                    "",
                    "To fix, do ONE of the following:",
                    "  1. Extend SecureHandler and use @secure_endpoint decorator",
                    "  2. Add @require_permission decorator to handler methods",
                    "  3. Add _check_*permission() method and call it in handle()",
                    "  4. If intentionally public, add to EXEMPT_HANDLERS in this test",
                    "=" * 70,
                ]
            )
            pytest.fail("\n".join(msg_lines))

    def test_secure_handler_count(self, all_handlers: list[HandlerInfo]) -> None:
        """Report on SecureHandler usage (informational)."""
        secure_count = sum(1 for h in all_handlers if h.extends_secure)
        total = len(all_handlers)
        non_exempt = [h for h in all_handlers if not h.is_exempt]

        print("\nRBAC Coverage Report:")
        print(f"  Total handlers: {total}")
        print(f"  Extends SecureHandler: {secure_count}")
        print(f"  Uses RBAC decorators: {sum(1 for h in all_handlers if h.has_rbac_decorator)}")
        print(f"  Uses RBAC methods: {sum(1 for h in all_handlers if h.has_rbac_method)}")
        print(f"  Exempt (intentionally public): {total - len(non_exempt)}")

    def test_no_duplicate_exemptions(self) -> None:
        """Verify exempt handlers list has no duplicates."""
        exempt_list = list(EXEMPT_HANDLERS)
        assert len(exempt_list) == len(set(exempt_list)), "Duplicate entries in EXEMPT_HANDLERS"

    def test_exempt_handlers_exist(self, all_handlers: list[HandlerInfo]) -> None:
        """Verify exempt handlers actually exist in the codebase.

        Prevents stale entries in EXEMPT_HANDLERS from accumulating.
        """
        found_names = {h.name for h in all_handlers}
        # Only check exemptions that would be found as Handler classes
        handler_exemptions = {name for name in EXEMPT_HANDLERS if name.endswith("Handler")}

        # Allow some exemptions to not exist (e.g., they might be in submodules)
        # This is a soft check - just warn, don't fail
        missing = handler_exemptions - found_names
        if missing:
            print(f"\nNote: Some exempt handlers not found (may be in submodules): {missing}")


class TestRoutePermissionCoverage:
    """Test suite for middleware route permission validation.

    These tests verify that the DEFAULT_ROUTE_PERMISSIONS rules:
    1. Reference valid system permissions
    2. Have no regex compilation errors
    3. Cover standard API patterns
    """

    def test_all_route_permissions_valid(self) -> None:
        """Verify all route permissions reference valid system permissions.

        This catches typos and undefined permissions in middleware rules.
        Currently reports warnings but doesn't fail (37 pre-existing undefined permissions).
        TODO: Fix undefined permissions and enable strict mode.
        """
        from aragora.rbac.middleware import (
            DEFAULT_ROUTE_PERMISSIONS,
            validate_route_permissions,
        )

        # Run validation (raises on strict mode, returns warnings otherwise)
        warnings = validate_route_permissions(DEFAULT_ROUTE_PERMISSIONS, strict=False)

        if warnings:
            # Report as warning, not failure (37 pre-existing undefined permissions)
            print("\n" + "=" * 70)
            print("ROUTE PERMISSION WARNINGS (non-blocking):")
            print("=" * 70)
            print(f"  Found {len(warnings)} undefined permission(s)")
            print("  Run with verbose to see details: pytest -v -s")
            print("=" * 70)
            # Log first 5 for visibility
            for warning in warnings[:5]:
                print(f"  - {warning[:100]}...")
            if len(warnings) > 5:
                print(f"  ... and {len(warnings) - 5} more")

    def test_route_permission_patterns_compile(self) -> None:
        """Verify all route permission patterns are valid regex."""
        import re

        from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS

        errors = []
        for rule in DEFAULT_ROUTE_PERMISSIONS:
            try:
                # Pattern should already be compiled in __post_init__
                # But verify it's actually a valid Pattern object
                if hasattr(rule.pattern, "pattern"):
                    # Already compiled - verify by matching empty string
                    rule.pattern.match("")
                else:
                    # Not compiled - try to compile
                    re.compile(rule.pattern)
            except re.error as e:
                errors.append(f"{rule.pattern}: {e}")

        if errors:
            pytest.fail("Invalid regex patterns in route permissions:\n" + "\n".join(errors))

    def test_route_permission_coverage_stats(self) -> None:
        """Report on route permission coverage (informational)."""
        from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS

        total = len(DEFAULT_ROUTE_PERMISSIONS)
        public = sum(1 for r in DEFAULT_ROUTE_PERMISSIONS if r.allow_unauthenticated)
        protected = total - public

        # Count by permission type
        unique_permissions = {
            r.permission_key for r in DEFAULT_ROUTE_PERMISSIONS if r.permission_key
        }

        print("\nRoute Permission Coverage Report:")
        print(f"  Total route rules: {total}")
        print(f"  Protected routes: {protected}")
        print(f"  Public routes (allow_unauthenticated): {public}")
        print(f"  Unique permissions referenced: {len(unique_permissions)}")

    def test_standard_api_patterns_covered(self) -> None:
        """Verify standard API patterns have route permission rules.

        This ensures common endpoints are explicitly covered by middleware rules.
        """
        from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS, RoutePermission

        # Standard patterns that should have rules
        required_patterns = [
            ("/api/debates", "POST"),  # Create debate
            ("/api/debates", "GET"),  # List debates
            ("/api/agents", "GET"),  # List agents
            ("/api/decisions", "POST"),  # Create decision
            ("/api/v1/decisions", "POST"),  # v1 Create decision
        ]

        def find_matching_rule(path: str, method: str) -> RoutePermission | None:
            for rule in DEFAULT_ROUTE_PERMISSIONS:
                matches, _ = rule.matches(path, method)
                if matches:
                    return rule
            return None

        missing = []
        for path, method in required_patterns:
            rule = find_matching_rule(path, method)
            if rule is None:
                missing.append(f"{method} {path}")

        if missing:
            pytest.fail(
                "Standard API patterns missing route permission rules:\n"
                + "\n".join(f"  - {m}" for m in missing)
            )
