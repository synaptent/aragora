"""Serve-side orphan reconciliation dispatch tests (route-debt PR-2).

Covers the 12 previously spec-orphaned operations that are now served
truthfully through registered handlers:

- ralph dashboard x6 (RalphDashboardHandler registration + ralph:read grant)
- km checkpoints compare x2 (KMCheckpointHandler uppercase ROUTES + legacy path
  normalization; the two VAL-CDG-016 original-cohort literals)
- matches/stats x2 (new MatchesStatsHandler backed by EloSystem.get_stats())
- inbox mentions x1 (TeamInboxMentionsHandler wrapping the team-inbox emitter)
- review-queue triage-metrics x1 (exact ROUTES literal)

Legacy-form dispatch is verified EMPIRICALLY through the real
``_try_modular_handler`` + ``RouteIndex`` machinery, not just can_handle
probes, per the reconciliation plan.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY, HandlerRegistryMixin
from aragora.server.handler_registry.core import RouteIndex
from aragora.server.handlers.knowledge.checkpoints import KMCheckpointHandler
from aragora.server.handlers.ralph_dashboard import RalphDashboardHandler
from aragora.server.handlers.review_queue import ReviewQueueHandler
from aragora.server.handlers.utils.decorators import PERMISSION_MATRIX, has_permission

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# The 12 serve-side orphans removed from the validator baseline in this PR.
SERVED_ORPHANS = [
    "/api/km/checkpoints/compare",
    "/api/matches/stats",
    "/api/ralph/blockers",
    "/api/ralph/campaigns",
    "/api/ralph/overview",
    "/api/v1/inbox/mentions",
    "/api/v1/km/checkpoints/compare",
    "/api/v1/matches/stats",
    "/api/v1/ralph/blockers",
    "/api/v1/ralph/campaigns",
    "/api/v1/ralph/overview",
    "/api/v1/review-queue/triage-metrics",
]

# After cdg-route-validator-fastapi-plane landed the mounted-FastAPI evidence
# plane, the 7 re-added v2 marketplace/orchestration paths count as served and
# the orphan baseline is terminal-empty.
V2_REMAINDER: list[str] = []


def _load_validator_module():
    """Import scripts/validate_openapi_routes.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "validate_openapi_routes_serve_side_test",
        PROJECT_ROOT / "scripts" / "validate_openapi_routes.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Registry + metadata assertions
# ---------------------------------------------------------------------------


class TestRegistryMembership:
    def test_ralph_dashboard_handler_registered(self) -> None:
        names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_ralph_dashboard_handler" in names

    def test_matches_stats_handler_registered(self) -> None:
        names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_matches_stats_handler" in names

    def test_team_inbox_mentions_handler_registered(self) -> None:
        names = [attr for attr, _ in HANDLER_REGISTRY]
        assert "_team_inbox_mentions_handler" in names

    def test_km_checkpoint_handler_has_uppercase_routes(self) -> None:
        assert hasattr(KMCheckpointHandler, "ROUTES")
        assert "/api/v1/km/checkpoints/compare" in KMCheckpointHandler.ROUTES
        # The bare list path is owned first-wins by KnowledgeMoundHandler
        # (pre-existing collision); this handler must not re-claim it.
        assert "/api/v1/km/checkpoints" not in KMCheckpointHandler.ROUTES

    def test_review_queue_declares_triage_metrics_literal(self) -> None:
        assert "/api/review-queue/triage-metrics" in ReviewQueueHandler.ROUTES

    def test_ralph_handler_declares_route_prefixes(self) -> None:
        prefixes = getattr(RalphDashboardHandler, "ROUTE_PREFIXES", [])
        assert "/api/ralph/" in prefixes
        assert "/api/v1/ralph/" in prefixes


class TestPermissionMatrix:
    """The RBAC decision: a registered handler must not 403 every real user."""

    def test_ralph_read_granted_to_members(self) -> None:
        assert "ralph:read" in PERMISSION_MATRIX
        assert has_permission("member", "ralph:read")
        assert has_permission("admin", "ralph:read")
        assert has_permission("owner", "ralph:read")

    def test_knowledge_read_granted_to_members(self) -> None:
        assert "knowledge:read" in PERMISSION_MATRIX
        assert has_permission("member", "knowledge:read")

    def test_knowledge_write_admin_scoped(self) -> None:
        assert has_permission("admin", "knowledge:write")
        assert not has_permission("member", "knowledge:write")

    def test_knowledge_delete_admin_scoped(self) -> None:
        assert has_permission("admin", "knowledge:delete")
        assert not has_permission("member", "knowledge:delete")


# ---------------------------------------------------------------------------
# Validator-metadata assertions (the orphan-shrink predicate itself)
# ---------------------------------------------------------------------------


class TestValidatorCoverage:
    def test_all_served_orphans_covered_by_handler_metadata(self) -> None:
        validator = _load_validator_module()
        handler_routes = validator.get_handler_routes()
        normalized_handler = {validator.normalize_route(r) for r in handler_routes}
        uncovered = [
            p for p in SERVED_ORPHANS if validator.normalize_route(p) not in normalized_handler
        ]
        assert uncovered == [], f"still orphaned by metadata: {uncovered}"

    def test_baseline_orphans_reduced_to_v2_remainder(self) -> None:
        baseline = json.loads(
            (PROJECT_ROOT / "scripts" / "baselines" / "validate_openapi_routes.json").read_text()
        )
        assert baseline["orphaned_in_spec"] == V2_REMAINDER
        assert baseline["missing_in_spec"] == []


# ---------------------------------------------------------------------------
# Empirical dispatch through _try_modular_handler
# ---------------------------------------------------------------------------


def _make_dispatch_instance(
    handlers: dict[str, Any],
    method: str = "GET",
) -> tuple[Any, RouteIndex]:
    """Build a mixin instance + REAL RouteIndex over the given handlers."""

    class _TestMixin(HandlerRegistryMixin):
        _handlers_initialized = True

    # Typed as Any: the mixin is exercised with dynamically attached
    # BaseHTTPRequestHandler attributes (command, headers, wfile, ...).
    instance: Any = _TestMixin()
    instance.command = method
    instance.headers = {}
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._auth_context = None
    instance.client_address = ("127.0.0.1", 12345)

    registry = []
    for attr_name, handler in handlers.items():
        setattr(instance, attr_name, handler)
        registry.append((attr_name, handler.__class__))

    index = RouteIndex()
    index.build(instance, registry)
    return instance, index


def _dispatch(
    instance: Any,
    index: RouteIndex,
    path: str,
    query: dict[str, Any] | None = None,
) -> tuple[bool, int | None]:
    """Run _try_modular_handler with the real machinery; return (handled, status)."""
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch("aragora.server.handler_registry.get_route_index", return_value=index),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        handled = instance._try_modular_handler(path, query or {})
    status = None
    if instance.send_response.call_args is not None:
        status = instance.send_response.call_args[0][0]
    return handled, status


def _auth_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.is_authenticated = True
    user.user_id = "user-1"
    user.email = "user@example.com"
    user.org_id = None
    user.role = role
    user.error_reason = None
    return user


class TestRalphDispatch:
    @pytest.mark.parametrize("path", ["/api/ralph/overview", "/api/v1/ralph/overview"])
    def test_overview_dispatches_both_forms(self, path: str) -> None:
        handler = RalphDashboardHandler(ctx={})
        dashboard = MagicMock()
        dashboard.get_overview.return_value = {"campaigns": 0}
        instance, index = _make_dispatch_instance({"_ralph_dashboard_handler": handler})
        with (
            patch.object(RalphDashboardHandler, "_get_dashboard", return_value=dashboard),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_auth_user("member"),
            ),
        ):
            handled, status = _dispatch(instance, index, path)
        assert handled is True
        assert status == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/api/ralph/campaigns",
            "/api/v1/ralph/campaigns",
            "/api/ralph/blockers",
            "/api/v1/ralph/blockers",
        ],
    )
    def test_campaigns_and_blockers_dispatch(self, path: str) -> None:
        handler = RalphDashboardHandler(ctx={})
        dashboard = MagicMock()
        dashboard.list_campaigns.return_value = []
        dashboard.get_blocker_breakdown.return_value = {}
        instance, index = _make_dispatch_instance({"_ralph_dashboard_handler": handler})
        with (
            patch.object(RalphDashboardHandler, "_get_dashboard", return_value=dashboard),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_auth_user("member"),
            ),
        ):
            handled, status = _dispatch(instance, index, path)
        assert handled is True
        assert status == 200

    def test_campaign_detail_dispatches_via_prefix(self) -> None:
        handler = RalphDashboardHandler(ctx={})
        dashboard = MagicMock()
        dashboard.get_campaign_detail.return_value = {"id": "c1"}
        instance, index = _make_dispatch_instance({"_ralph_dashboard_handler": handler})
        with (
            patch.object(RalphDashboardHandler, "_get_dashboard", return_value=dashboard),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_auth_user("member"),
            ),
        ):
            handled, status = _dispatch(instance, index, "/api/v1/ralph/campaigns/c1")
        assert handled is True
        assert status == 200

    @pytest.mark.no_auto_auth
    def test_unauthenticated_gets_401_not_403(self) -> None:
        """The registration must not be a failure shim: authenticated members
        pass, and anonymous callers get 401 (auth) rather than a blanket 403."""
        handler = RalphDashboardHandler(ctx={})
        unauth = MagicMock()
        unauth.is_authenticated = False
        unauth.error_reason = None
        instance, index = _make_dispatch_instance({"_ralph_dashboard_handler": handler})
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=unauth,
        ):
            handled, status = _dispatch(instance, index, "/api/ralph/overview")
        assert handled is True
        assert status == 401


class TestKMCheckpointDispatch:
    @pytest.mark.parametrize(
        "path",
        ["/api/km/checkpoints/compare", "/api/v1/km/checkpoints/compare"],
    )
    def test_compare_post_dispatches_both_forms(self, path: str) -> None:
        handler = KMCheckpointHandler()
        store = MagicMock()
        store.compare_checkpoints = AsyncMock(return_value={"nodes_added": 1})
        instance, index = _make_dispatch_instance(
            {"_km_checkpoint_handler": handler}, method="POST"
        )
        with (
            patch.object(KMCheckpointHandler, "_get_checkpoint_store", return_value=store),
            patch.object(
                KMCheckpointHandler,
                "read_json_body",
                return_value={"checkpoint_a": "a", "checkpoint_b": "b"},
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_auth_user("admin"),
            ),
        ):
            handled, status = _dispatch(instance, index, path)
        assert handled is True
        assert status == 200

    @pytest.mark.parametrize("path", ["/api/km/checkpoints", "/api/v1/km/checkpoints"])
    def test_bare_list_path_not_claimed(self, path: str) -> None:
        """The bare checkpoints list path stays owned first-wins by
        KnowledgeMoundHandler (pre-existing collision); in isolation this
        handler must NOT claim it — only the compare operation."""
        handler = KMCheckpointHandler()
        instance, index = _make_dispatch_instance({"_km_checkpoint_handler": handler})
        handled, _status = _dispatch(instance, index, path)
        assert handled is False


class TestMatchesStatsDispatch:
    @pytest.mark.parametrize("path", ["/api/matches/stats", "/api/v1/matches/stats"])
    def test_stats_dispatches_both_forms(self, path: str) -> None:
        from aragora.server.handlers.agents.matches_stats import MatchesStatsHandler

        elo = MagicMock()
        elo.get_stats.return_value = {"total_matches": 3}
        handler = MatchesStatsHandler({"elo_system": elo})
        instance, index = _make_dispatch_instance({"_matches_stats_handler": handler})
        handled, status = _dispatch(instance, index, path)
        assert handled is True
        assert status == 200
        body = instance.wfile.getvalue()
        assert b"total_matches" in body

    def test_stats_503_when_elo_unavailable(self) -> None:
        from aragora.server.handlers.agents.matches_stats import MatchesStatsHandler

        handler = MatchesStatsHandler({})
        instance, index = _make_dispatch_instance({"_matches_stats_handler": handler})
        handled, status = _dispatch(instance, index, "/api/matches/stats")
        assert handled is True
        assert status == 503

    def test_can_handle_is_exact_not_prefix(self) -> None:
        from aragora.server.handlers.agents.matches_stats import MatchesStatsHandler

        handler = MatchesStatsHandler({})
        assert handler.can_handle("/api/matches/stats")
        assert handler.can_handle("/api/v1/matches/stats")
        assert not handler.can_handle("/api/matches/stats/zz-nonexistent-canary-zz")


class TestMentionsDispatch:
    def test_mentions_get_dispatches(self) -> None:
        from aragora.server.handlers.inbox.team_inbox import TeamInboxMentionsHandler

        handler = TeamInboxMentionsHandler({})
        emitter = MagicMock()
        emitter.get_mentions_for_user = AsyncMock(return_value=[])
        instance, index = _make_dispatch_instance({"_team_inbox_mentions_handler": handler})
        with (
            patch(
                "aragora.server.handlers.inbox.team_inbox.get_team_inbox_emitter_instance",
                return_value=emitter,
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=_auth_user("member"),
            ),
        ):
            handled, status = _dispatch(instance, index, "/api/v1/inbox/mentions")
        assert handled is True
        assert status == 200
        emitter.get_mentions_for_user.assert_awaited_once()

    @pytest.mark.no_auto_auth
    def test_mentions_requires_auth(self) -> None:
        from aragora.server.handlers.inbox.team_inbox import TeamInboxMentionsHandler

        handler = TeamInboxMentionsHandler({})
        unauth = MagicMock()
        unauth.is_authenticated = False
        unauth.error_reason = None
        instance, index = _make_dispatch_instance({"_team_inbox_mentions_handler": handler})
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=unauth,
        ):
            handled, status = _dispatch(instance, index, "/api/v1/inbox/mentions")
        assert handled is True
        assert status == 401


class TestTriageMetricsDispatch:
    def test_triage_metrics_still_dispatches_via_exact_route(self) -> None:
        handler = ReviewQueueHandler({})
        instance, index = _make_dispatch_instance({"_review_queue_handler": handler})
        sentinel = MagicMock()
        sentinel.status_code = 200
        sentinel.content_type = "application/json"
        sentinel.body = b"{}"
        sentinel.headers = {}
        with patch.object(
            ReviewQueueHandler, "_get_triage_metrics", return_value=sentinel
        ) as mock_metrics:
            handled, status = _dispatch(instance, index, "/api/v1/review-queue/triage-metrics")
        assert handled is True
        assert status == 200
        mock_metrics.assert_called_once()
