"""
Route Coverage Validation Tests.

These tests verify that all registered handler route prefixes
have corresponding entries in DEFAULT_ROUTE_PERMISSIONS, ensuring
no API endpoints are accidentally exposed without RBAC protection.
"""

import re

import pytest

from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS, RBACMiddlewareConfig


# Route prefixes extracted from handler_registry.py RouteIndex.build()
# Each entry is (handler_name, [route_prefixes])
HANDLER_ROUTE_PREFIXES: list[tuple[str, list[str]]] = [
    ("health_handler", ["/healthz", "/readyz", "/api/health"]),
    ("nomic_handler", ["/api/nomic/status", "/api/modes"]),
    ("docs_handler", ["/api/openapi", "/api/docs", "/api/redoc"]),
    ("debates_handler", ["/api/debates", "/api/debates/test-123", "/api/search"]),
    ("agents_handler", ["/api/agents", "/api/agent/test-123", "/api/leaderboard", "/api/rankings"]),
    ("pulse_handler", ["/api/pulse/trending"]),
    ("analytics_handler", ["/api/analytics/dashboard", "/api/v1/analytics/metrics"]),
    ("consensus_handler", ["/api/consensus/test-123"]),
    ("belief_handler", ["/api/belief-network/test-123", "/api/laboratory/test-123"]),
    ("decision_handler", ["/api/decisions", "/api/decisions/test-123"]),
    (
        "decision_pipeline_handler",
        [
            "/api/v1/decisions/plans",
            "/api/v1/decisions/plans/test-plan-123",
            "/api/v1/decisions/plans/test-plan-123/approve",
            "/api/v1/decisions/plans/test-plan-123/reject",
            "/api/v1/decisions/plans/test-plan-123/execute",
            "/api/v1/decisions/plans/test-plan-123/outcome",
        ],
    ),
    (
        "plans_handler",
        [
            "/api/plans",
            "/api/v1/plans",
            "/api/v1/plans/test-plan-123",
            "/api/v1/plans/test-plan-123/memo",
            "/api/v1/plans/test-plan-123/approve",
            "/api/v1/plans/test-plan-123/reject",
            "/api/v1/plans/test-plan-123/execute",
        ],
    ),
    ("runs_handler", ["/api/runs", "/api/runs/test-run-123", "/api/v1/runs"]),
    ("genesis_handler", ["/api/genesis/start"]),
    ("replays_handler", ["/api/replays/test-123"]),
    ("tournament_handler", ["/api/tournaments/test-123"]),
    ("memory_handler", ["/api/memory/search"]),
    ("document_handler", ["/api/documents/test-123"]),
    ("auditing_handler", ["/api/redteam/test-123"]),
    ("relationship_handler", ["/api/relationship/test-123"]),
    ("moments_handler", ["/api/moments/test-123"]),
    ("persona_handler", ["/api/personas"]),
    ("evolution_handler", ["/api/evolution/test-123"]),
    ("plugins_handler", ["/api/plugins/test-123", "/api/v1/plugins/test-123"]),
    ("audio_handler", ["/audio/test-123", "/api/podcast/test-123"]),
    ("devices_handler", ["/api/devices/test-123", "/api/v1/devices/test-123"]),
    ("insights_handler", ["/api/insights/test-123"]),
    ("learning_handler", ["/api/learning/test-123"]),
    ("gallery_handler", ["/api/gallery/test-123"]),
    ("auth_handler", ["/api/auth/login", "/api/v1/auth/login"]),
    ("billing_handler", ["/api/billing/test-123", "/api/v1/billing/test-123"]),
    ("budget_handler", ["/api/v1/budgets"]),
    ("checkpoint_handler", ["/api/checkpoints"]),
    (
        "settlements_handler",
        [
            "/api/settlements",
            "/api/v1/settlements",
            "/api/v1/settlements/history",
            "/api/v1/settlements/test-123/settle",
        ],
    ),
    ("knowledge_handler", ["/api/knowledge/search", "/api/v1/knowledge/search"]),
    ("inbox_handler", ["/api/inbox", "/api/v1/inbox"]),
    ("canvas_handler", ["/api/canvas", "/api/v1/canvas/test-123"]),
    ("codebase_handler", ["/api/codebase", "/api/v1/codebase/search"]),
    ("workflows_handler", ["/api/workflows", "/api/workflows/test-123"]),
    ("connectors_handler", ["/api/connectors"]),
    ("webhooks_handler", ["/api/webhooks"]),
    ("evidence_handler", ["/api/evidence"]),
    ("training_handler", ["/api/training"]),
    ("users_handler", ["/api/users"]),
    ("org_handler", ["/api/org/settings"]),
    ("keys_handler", ["/api/keys"]),
    ("admin_handler", ["/api/admin/settings"]),
    ("control_plane_handler", ["/api/v1/control-plane/tasks"]),
    ("policies_handler", ["/api/v1/policies"]),
    ("compliance_handler", ["/api/v1/compliance/violations"]),
]

# Routes that intentionally bypass RBAC (health, docs, public endpoints)
BYPASS_PREFIXES = {
    "/health",
    "/healthz",
    "/ready",
    "/readyz",
    "/metrics",
    "/api/docs",
    "/api/openapi",
    "/api/redoc",
    "/api/health",
    "/audio/",  # Audio delivery endpoints
}


def _route_has_permission_coverage(path: str) -> bool:
    """Check if a route path has at least one matching permission rule.

    Checks all common HTTP methods since handlers may only support specific ones.
    """
    # Check bypass paths
    for bypass in BYPASS_PREFIXES:
        if path.startswith(bypass) or path == bypass:
            return True

    config = RBACMiddlewareConfig(route_permissions=DEFAULT_ROUTE_PERMISSIONS)
    for bypass in config.bypass_paths:
        if path == bypass or path.startswith(bypass):
            return True

    # Check against route permissions with all common methods
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    for rule in DEFAULT_ROUTE_PERMISSIONS:
        for method in methods:
            matched, _ = rule.matches(path, method)
            if matched:
                return True

    return False


class TestRouteCoverage:
    """Verify all registered handler routes have permission coverage."""

    def test_all_handler_routes_have_permission_coverage(self):
        """Every handler route prefix must match at least one RoutePermission."""
        uncovered = []

        for handler_name, prefixes in HANDLER_ROUTE_PREFIXES:
            for prefix in prefixes:
                if not _route_has_permission_coverage(prefix):
                    uncovered.append(f"{handler_name}: {prefix}")

        if uncovered:
            pytest.fail(
                f"Found {len(uncovered)} handler route(s) without RBAC permission coverage:\n"
                + "\n".join(f"  - {u}" for u in uncovered)
                + "\n\nAdd RoutePermission entries to DEFAULT_ROUTE_PERMISSIONS in "
                "aragora/rbac/middleware.py"
            )

    def test_route_permission_patterns_are_valid_regex(self):
        """All RoutePermission patterns must be valid compiled regex."""
        for i, rule in enumerate(DEFAULT_ROUTE_PERMISSIONS):
            assert isinstance(rule.pattern, re.Pattern), (
                f"Rule {i} pattern is not compiled: {rule.pattern}"
            )

    def test_no_duplicate_exact_rules(self):
        """Detect duplicate permission rules (same pattern + method)."""
        seen = set()
        duplicates = []

        for rule in DEFAULT_ROUTE_PERMISSIONS:
            key = (rule.pattern.pattern, rule.method)
            if key in seen:
                duplicates.append(f"{rule.pattern.pattern} [{rule.method}]")
            seen.add(key)

        if duplicates:
            pytest.fail(
                f"Found {len(duplicates)} duplicate route permission rule(s):\n"
                + "\n".join(f"  - {d}" for d in duplicates)
            )

    def test_permission_count_within_expected_range(self):
        """Sanity check: permission count hasn't drastically changed."""
        count = len(DEFAULT_ROUTE_PERMISSIONS)
        assert count > 200, (
            f"Expected 200+ route permission rules, found {count}. "
            "Has DEFAULT_ROUTE_PERMISSIONS been trimmed?"
        )

    @pytest.mark.parametrize(
        "path,should_match",
        [
            ("/api/debates", True),
            ("/api/debates/abc-123", True),
            ("/api/agents", True),
            ("/api/admin/settings", True),
            ("/api/auth/login", True),
            ("/api/v1/knowledge/search", True),
            ("/api/v1/canvas/abc-123", True),
            ("/api/v1/codebase/search", True),
            ("/api/v1/settlements", True),
            ("/api/v1/settlements/test-123/settle", True),
        ],
    )
    def test_specific_routes_have_coverage(self, path, should_match):
        """Verify specific critical routes match a permission rule."""
        assert _route_has_permission_coverage(path) == should_match, (
            f"Route {path} expected match={should_match}"
        )
