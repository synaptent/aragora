"""
Core infrastructure for handler registry.

This module provides:
- Safe import utility for graceful handler degradation
- Async coroutine runner for HTTP threads
- RouteIndex for O(1) handler dispatch
- Handler validation functions
- HandlerRegistryMixin base class

All other handler registry modules depend on this core.
"""

from __future__ import annotations

import asyncio
import glob as glob_mod
import importlib
import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Optional, cast

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type alias for handler classes that may be None when handlers are unavailable
# This allows proper type hints without requiring type: ignore comments
HandlerType = Optional[type[Any]]

# =============================================================================
# Handler Tier Classification
# =============================================================================
# Tiers control which handlers are loaded at startup.
# Set ARAGORA_HANDLER_TIERS env var to a comma-separated list of tiers
# to load (e.g., "core,extended"). Default: all tiers.

HANDLER_TIERS: dict[str, str] = {
    # ── Core (always loaded) ──────────────────────────────────────────
    "_health_handler": "core",
    "_build_info_handler": "core",
    "_deploy_status_handler": "core",
    "_system_handler": "core",
    "_docs_handler": "core",
    "_debates_handler": "core",
    "_agents_handler": "core",
    "_auth_handler": "core",
    "_oauth_handler": "core",
    "_consensus_handler": "core",
    "_receipts_handler": "core",
    "_gauntlet_handler": "core",
    "_gauntlet_secure_handler": "core",
    "_skills_handler": "core",
    "_webhook_handler": "core",
    "_features_handler": "core",
    "_tournament_handler": "core",
    "_playground_handler": "core",
    "_ranking_handler": "core",
    "_leaderboard_handler": "core",
    "_onboarding_handler": "core",
    "_status_page_handler": "core",
    "_platform_config_handler": "core",
    "_readiness_check_handler": "core",
    # /metrics owner — must stay core so tier-filtered (minimal) deployments
    # keep the Prometheus scrape endpoint (previously guaranteed via
    # SystemHandler, which no longer claims /metrics).
    "_metrics_handler": "core",
    # ── Extended (loaded by default, can disable) ─────────────────────
    "_nomic_handler": "extended",
    "_analytics_dashboard_handler": "extended",
    "_analytics_metrics_handler": "extended",
    "_endpoint_analytics_handler": "extended",
    "_pulse_handler": "extended",
    "_memory_handler": "extended",
    "_document_handler": "extended",
    "_document_batch_handler": "extended",
    "_belief_handler": "extended",
    "_knowledge_handler": "extended",
    "_knowledge_chat_handler": "extended",
    "_insights_handler": "extended",
    "_learning_handler": "extended",
    "_gallery_handler": "extended",
    "_moments_handler": "extended",
    "_persona_handler": "extended",
    "_calibration_handler": "extended",
    "_replays_handler": "extended",
    "_graph_debates_handler": "extended",
    "_matrix_debates_handler": "extended",
    "_decision_explain_handler": "extended",
    "_decision_handler": "extended",
    "_critique_handler": "extended",
    "_explainability_handler": "extended",
    "_dashboard_handler": "extended",
    "_notification_handler": "extended",
    "_code_review_handler": "extended",
    "_pr_review_handler": "extended",
    "_receipt_delivery_handler": "extended",
    "_plans_handler": "extended",
    "_decision_pipeline_handler": "extended",
    "_unified_memory_handler": "extended",
    "_canvas_pipeline_handler": "extended",
    "_idea_canvas_handler": "extended",
    "_goal_canvas_handler": "extended",
    "_action_canvas_handler": "extended",
    "_orchestration_canvas_handler": "extended",
    "_universal_graph_handler": "extended",
    "_pipeline_transitions_handler": "extended",
    "_outcome_handler": "extended",
    "_decision_analytics_handler": "extended",
    "_benchmarking_handler": "extended",
    "_self_improve_details_handler": "extended",
    "_knowledge_flow_handler": "extended",
    "_system_health_dashboard_handler": "extended",
    "_memory_unified_handler": "extended",
    "_km_gap_handler": "extended",
    "_spend_analytics_dashboard_handler": "extended",
    "_debate_stats_handler": "extended",
    "_debate_share_handler": "extended",
    "_debate_interventions_handler": "extended",
    "_composite_handler": "extended",
    "_settlement_handler": "extended",
    "_review_queue_handler": "extended",
    "_spectate_stream_handler": "extended",
    "_receipt_export_handler": "extended",
    "_decision_package_handler": "extended",
    "_pipeline_execute_handler": "extended",
    "_pipeline_graph_handler": "extended",
    "_plan_management_handler": "extended",
    "_receipt_explorer_handler": "extended",
    "_decomposition_handler": "extended",
    "_differentiation_handler": "extended",
    "_moderation_analytics_handler": "extended",
    "_context_budget_handler": "extended",
    "_agent_recommendation_handler": "extended",
    "_feedback_handler": "extended",
    "_email_triage_handler": "extended",
    "_feedback_hub_handler": "extended",
    "_notification_history_handler": "extended",
    "_notification_preferences_handler": "extended",
    "_notification_templates_handler": "extended",
    "_spend_analytics_handler": "extended",
    "_feature_flags_handler": "extended",
    "_workflow_builder_handler": "extended",
    "_template_registry_handler": "extended",
    "_marketplace_pilot_handler": "extended",
    "_agent_bridge_handler": "extended",
    # ── Enterprise (loaded only with ARAGORA_ENTERPRISE=1) ────────────
    "_admin_handler": "enterprise",
    "_control_plane_handler": "enterprise",
    "_policy_handler": "enterprise",
    "_security_handler": "enterprise",
    "_moderation_handler": "enterprise",
    "_oauth_wizard_handler": "enterprise",
    "_scim_handler": "enterprise",
    "_sso_handler": "enterprise",
    "_billing_handler": "enterprise",
    "_budget_handler": "enterprise",
    "_budget_controls_handler": "enterprise",
    "_credits_admin_handler": "enterprise",
    "_organizations_handler": "enterprise",
    "_workspace_handler": "enterprise",
    "_compliance_handler": "enterprise",
    "_backup_handler": "enterprise",
    "_dr_handler": "enterprise",
    "_privacy_handler": "enterprise",
    "_audit_trail_handler": "enterprise",
    "_audit_sessions_handler": "enterprise",
    "_csp_report_handler": "enterprise",
    "_rbac_handler": "enterprise",
    "_emergency_access_handler": "enterprise",
    "_unified_approvals_handler": "enterprise",
    "_connector_management_handler": "enterprise",
    "_task_execution_handler": "enterprise",
    "_compliance_report_handler": "enterprise",
    "_eu_ai_act_compliance_handler": "enterprise",
    "_gdpr_deletion_handler": "enterprise",
    "_mfa_compliance_handler": "enterprise",
    "_backup_offsite_handler": "enterprise",
    # ── Experimental (loaded only with ARAGORA_EXPERIMENTAL=1) ────────
    "_genesis_handler": "experimental",
    "_erc8004_handler": "experimental",
    "_evolution_handler": "experimental",
    "_evolution_ab_testing_handler": "experimental",
    "_computer_use_handler": "experimental",
    "_laboratory_handler": "experimental",
    "_probes_handler": "experimental",
    "_breakpoints_handler": "experimental",
    "_introspection_handler": "experimental",
    "_rlm_context_handler": "experimental",
    "_rlm_handler": "experimental",
    "_ml_handler": "experimental",
    "_verticals_handler": "experimental",
    "_canvas_handler": "experimental",
    "_harnesses_handler": "experimental",
    "_sandbox_handler": "experimental",
    "_visualization_handler": "experimental",
    # ── Optional (feature-specific, loaded by default) ────────────────
    "_gateway_handler": "optional",
    "_openclaw_gateway_handler": "optional",
    "_gateway_credentials_handler": "optional",
    "_gateway_health_handler": "optional",
    "_gateway_config_handler": "optional",
    "_external_integrations_handler": "optional",
    "_integration_management_handler": "optional",
    "_feature_integrations_handler": "optional",
    "_connectors_handler": "optional",
    "_streaming_connector_handler": "optional",
    "_marketplace_handler": "optional",
    "_automation_handler": "optional",
    "_workflow_handler": "optional",
    "_queue_handler": "optional",
    "_workflow_templates_handler": "optional",
    "_workflow_patterns_handler": "optional",
    "_workflow_categories_handler": "optional",
    "_workflow_pattern_templates_handler": "optional",
    "_sme_workflows_handler": "optional",
    "_plugins_handler": "optional",
    "_devices_handler": "optional",
    "_relationship_handler": "optional",
    "_routing_handler": "optional",
    "_routing_rules_handler": "optional",
    "_advertising_handler": "optional",
    "_crm_handler": "optional",
    "_support_handler": "optional",
    "_ecommerce_handler": "optional",
    "_reconciliation_handler": "optional",
    "_codebase_audit_handler": "optional",
    "_legal_handler": "optional",
    "_devops_handler": "optional",
    "_ap_automation_handler": "optional",
    "_ar_automation_handler": "optional",
    "_invoice_handler": "optional",
    "_expense_handler": "optional",
    "_skill_marketplace_handler": "optional",
    "_template_marketplace_handler": "optional",
    "_template_recommendations_handler": "optional",
    "_audit_github_bridge_handler": "optional",
    "_bindings_handler": "optional",
    "_dependency_analysis_handler": "optional",
    "_repository_handler": "optional",
    "_scheduler_handler": "optional",
    "_threat_intel_handler": "optional",
    "_finding_workflow_handler": "optional",
    "_quick_scan_handler": "optional",
    "_cloud_storage_handler": "optional",
    "_smart_upload_handler": "optional",
    "_partner_handler": "optional",
    "_alert_handler": "optional",
    "_approval_handler": "optional",
    "_trigger_handler": "optional",
    "_monitoring_handler": "optional",
    "_cost_dashboard_handler": "optional",
    "_gastown_dashboard_handler": "optional",
    "_sme_usage_dashboard_handler": "optional",
    "_sme_success_dashboard_handler": "optional",
    "_agent_dashboard_handler": "optional",
    "_code_intelligence_handler": "optional",
    "_auditing_handler": "optional",
    "_uncertainty_handler": "optional",
    "_verification_handler": "optional",
    "_deliberations_handler": "optional",
    "_orchestration_handler": "optional",
    "_voice_handler": "optional",
    "_playbook_handler": "optional",
}


def get_active_tiers() -> set[str]:
    """Determine which handler tiers should be loaded.

    Controlled by ARAGORA_HANDLER_TIERS env var (comma-separated).
    Defaults to all tiers. Core is always included.
    """
    tiers_env = os.environ.get("ARAGORA_HANDLER_TIERS", "").strip()
    if tiers_env:
        tiers = {t.strip() for t in tiers_env.split(",") if t.strip()}
        tiers.add("core")  # Core is always loaded
        return tiers

    # Default: load all tiers, but respect feature flags
    tiers = {"core", "extended", "optional"}
    if os.environ.get("ARAGORA_ENTERPRISE", "").strip() in ("1", "true", "yes"):
        tiers.add("enterprise")
    if os.environ.get("ARAGORA_EXPERIMENTAL", "").strip() in ("1", "true", "yes"):
        tiers.add("experimental")

    # If neither enterprise nor experimental flag is set but no tier filter
    # is configured, load everything for backward compatibility
    if not tiers_env:
        tiers.update({"enterprise", "experimental"})

    return tiers


def filter_registry_by_tier(
    registry: list[tuple[str, Any]],
    active_tiers: set[str] | None = None,
) -> list[tuple[str, Any]]:
    """Filter handler registry to only include handlers in active tiers.

    Handlers not in HANDLER_TIERS are assumed to be 'extended' (loaded by default).
    """
    if active_tiers is None:
        active_tiers = get_active_tiers()

    filtered = []
    for attr_name, handler_class in registry:
        tier = HANDLER_TIERS.get(attr_name, "extended")
        if tier in active_tiers:
            filtered.append((attr_name, handler_class))
        else:
            logger.debug("[handlers] Skipping %s (tier=%s)", attr_name, tier)

    return filtered


_SENTINEL = object()


class _DeferredImport:
    """Lazy handler class proxy that defers module import until resolution.

    Instead of eagerly importing handler modules at server startup,
    stores the import spec (module_path, class_name) and only triggers
    the actual import when resolve() is called during _init_handlers().

    This reduces server module load time from ~165 handler imports to 0,
    deferring the cost to first-request handler initialization.
    """

    __slots__ = ("_module_path", "_class_name", "_resolved")

    def __init__(self, module_path: str, class_name: str):
        self._module_path = module_path
        self._class_name = class_name
        self._resolved = _SENTINEL

    def resolve(self) -> HandlerType:
        """Resolve the deferred import, returning the handler class or None."""
        if self._resolved is _SENTINEL:
            try:
                mod = importlib.import_module(self._module_path)
                self._resolved = getattr(mod, self._class_name)
            except (ImportError, AttributeError, TypeError) as e:
                logger.warning(
                    "Failed to import %s from %s: %s",
                    self._class_name,
                    self._module_path,
                    e,
                )
                self._resolved = None
        return cast(HandlerType, self._resolved)

    def __bool__(self) -> bool:
        # Always truthy before resolution — assume import will succeed
        return True

    def __repr__(self) -> str:
        if self._resolved is not _SENTINEL:
            return repr(self._resolved)
        return f"<DeferredImport {self._module_path}:{self._class_name}>"

    @property
    def __name__(self) -> str:
        """Expose the underlying class name for diagnostics and test discovery."""
        resolved = self.resolve()
        if resolved is not None:
            return resolved.__name__
        return self._class_name

    def __getattr__(self, name: str) -> Any:
        """Proxy class metadata access to the resolved handler class.

        This keeps registry introspection working for diagnostics, OpenAPI-style
        route discovery, and tests that examine ``ROUTES``/``can_handle`` on the
        lazy registry entries directly.
        """
        resolved = self.resolve()
        if resolved is None:
            raise AttributeError(f"{self._class_name} could not be imported; no attribute {name!r}")
        return getattr(resolved, name)


def _safe_import(module_path: str, class_name: str) -> _DeferredImport:
    """Create a deferred import spec for a handler class.

    Returns a _DeferredImport proxy that defers the actual module import
    until resolve() is called. This avoids eagerly importing all 165+
    handler modules at server startup.

    Call .resolve() to get the actual handler class (or None on failure).
    """
    return _DeferredImport(module_path, class_name)


def _eager_import(module_path: str, class_name: str) -> HandlerType:
    """Eagerly import a handler class (for critical handlers only).

    Use this instead of _safe_import when the handler MUST be available
    at module load time (e.g., for health checks).
    """
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError, TypeError) as e:
        logger.warning("Failed to import %s from %s: %s", class_name, module_path, e)
        return None


def _run_handler_coroutine(coro: Any) -> Any:
    """Run an async handler coroutine from the sync HTTP thread.

    When a PostgreSQL pool is initialized, schedules the coroutine on the
    main event loop (where asyncpg pool lives) using run_coroutine_threadsafe.
    This ensures:
    - asyncpg pool.acquire() works (same event loop)
    - nest_asyncio allows nested run_until_complete() from sync store wrappers

    Falls back to creating a local event loop when no pool is configured
    (SQLite-only mode).
    """
    # Try to use the main event loop (where asyncpg pool was created)
    try:
        from aragora.storage.pool_manager import get_pool_event_loop

        main_loop = get_pool_event_loop()
        if main_loop is not None and main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, main_loop)
            return future.result(timeout=60)
    except ImportError:
        # pool_manager not available - use fallback below
        pass
    except TimeoutError:
        # Timeout waiting for coroutine - close it and re-raise
        coro.close()
        raise
    except (RuntimeError, OSError):
        # Coroutine may have started execution - cannot reuse, must re-raise
        # (e.g., if sync store methods called run_async() from async context)
        coro.close()
        raise

    # Fallback: create a local event loop (works for SQLite-only mode)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(asyncio.wait_for(coro, timeout=60))


class RouteIndex:
    """O(1) route lookup index for handler dispatch.

    Builds an index of exact paths and prefix patterns at initialization,
    enabling fast route resolution without iterating through all handlers.

    Performance:
    - Exact paths: O(1) dict lookup
    - Dynamic paths: O(1) LRU cache hit, O(n) cache miss with prefix scan
    """

    def __init__(self) -> None:
        # Exact path -> (attr_name, handler) mapping
        self._exact_routes: dict[str, tuple[str, Any]] = {}
        # Prefix patterns for dynamic routes: [(prefix, attr_name, handler)]
        self._prefix_routes: list[tuple[str, str, Any]] = []
        # Cache for resolved dynamic routes
        self._cache_size: int = 500

    def build(self, registry_mixin: Any, handler_registry: list[tuple[str, Any]]) -> None:
        """Build route index from initialized handlers.

        Extracts ROUTES from each handler for exact matching,
        and identifies prefix patterns from can_handle logic.

        Args:
            registry_mixin: The HandlerRegistryMixin instance with initialized handlers
            handler_registry: List of (attr_name, handler_class) pairs
        """
        self._exact_routes.clear()
        self._prefix_routes.clear()

        # Known prefix patterns by handler (extracted from can_handle implementations)
        PREFIX_PATTERNS = {
            "_health_handler": ["/healthz", "/readyz", "/api/health"],
            "_nomic_handler": ["/api/nomic/", "/api/modes"],
            "_docs_handler": ["/api/openapi", "/api/docs", "/api/redoc", "/api/postman"],
            "_debates_handler": ["/api/debate", "/api/debates", "/api/debates/", "/api/search"],
            # Without this entry the version-stripped path falls into
            # DebatesHandler's slug lookup, which skips the is_public check.
            "_public_debate_viewer_handler": ["/api/v1/debates/public/"],
            # Share writes check that the caller's org owns the debate; without
            # this entry DebatesHandler's slug lookup answered them with a 404.
            "_debate_share_handler": ["/api/v1/debates/"],
            "_agents_handler": [
                "/api/agent/",
                "/api/agents",
                "/api/leaderboard",
                "/api/rankings",
                "/api/calibration/leaderboard",
                "/api/matches/recent",
            ],
            "_pulse_handler": ["/api/pulse/"],
            "_analytics_dashboard_handler": ["/api/analytics/"],
            "_endpoint_analytics_handler": ["/api/analytics/endpoints"],
            "_analytics_metrics_handler": ["/api/v1/analytics/"],
            "_consensus_handler": ["/api/consensus/"],
            "_belief_handler": ["/api/belief-network/", "/api/laboratory/"],
            "_decision_explain_handler": ["/api/v1/decisions/"],
            "_decision_pipeline_handler": ["/api/v1/decisions/plans"],
            "_decision_handler": ["/api/decisions"],
            "_genesis_handler": ["/api/genesis/"],
            "_replays_handler": ["/api/replays/"],
            "_tournament_handler": ["/api/tournaments/"],
            "_memory_handler": ["/api/memory/"],
            "_unified_memory_handler": ["/api/v1/memory/unified/"],
            "_canvas_pipeline_handler": ["/api/v1/canvas/", "/api/canvas/"],
            "_idea_canvas_handler": ["/api/v1/ideas"],
            "_goal_canvas_handler": ["/api/v1/goals"],
            "_action_canvas_handler": ["/api/v1/actions"],
            "_orchestration_canvas_handler": ["/api/v1/orchestration/canvas"],
            "_universal_graph_handler": ["/api/v1/pipeline/graphs"],
            "_pipeline_transitions_handler": ["/api/v1/pipeline/transitions"],
            "_outcome_handler": [
                "/api/v1/decisions/",
                "/api/decisions/",
                "/api/v1/outcomes/",
                "/api/outcomes/",
            ],
            "_benchmarking_handler": ["/api/benchmarks"],
            "_document_handler": ["/api/documents/"],
            "_document_batch_handler": ["/api/documents/batch", "/api/documents/processing/"],
            "_auditing_handler": [
                "/api/debates/capability-probe",
                "/api/debates/deep-audit",
                "/api/redteam/",
            ],
            "_relationship_handler": ["/api/relationship/"],
            "_moments_handler": ["/api/moments/"],
            "_persona_handler": ["/api/personas", "/api/agent/"],
            "_introspection_handler": ["/api/introspection/"],
            "_harnesses_handler": ["/api/v1/harnesses"],
            "_sandbox_handler": ["/api/sandbox/"],
            "_visualization_handler": ["/api/v1/visualization/"],
            "_calibration_handler": ["/api/agent/"],
            "_evolution_handler": ["/api/evolution/"],
            "_plugins_handler": ["/api/plugins/", "/api/v1/plugins/"],
            "_audio_handler": ["/audio/", "/api/podcast/"],
            "_devices_handler": ["/api/devices/", "/api/v1/devices/"],
            "_social_handler": ["/api/youtube/"],
            "_broadcast_handler": ["/api/podcast/"],
            "_insights_handler": ["/api/insights/"],
            "_learning_handler": ["/api/learning/"],
            "_gallery_handler": ["/api/gallery/"],
            "_auth_handler": ["/api/auth/", "/api/v1/auth/"],
            "_billing_handler": ["/api/billing/", "/api/v1/billing/"],
            "_budget_handler": ["/api/v1/budgets"],
            "_checkpoint_handler": ["/api/checkpoints"],
            "_graph_debates_handler": ["/api/debates/graph"],
            "_matrix_debates_handler": ["/api/debates/matrix"],
            "_feature_integrations_handler": ["/api/v1/integrations", "/api/integrations"],
            "_external_integrations_handler": [
                "/api/v1/integrations/zapier",
                "/api/v1/integrations/make",
                "/api/v1/integrations/n8n",
                "/api/integrations/zapier",
                "/api/integrations/make",
                "/api/integrations/n8n",
            ],
            "_integration_management_handler": ["/api/v2/integrations"],
            "_oauth_wizard_handler": ["/api/v2/integrations/wizard"],
            "_gauntlet_handler": ["/api/gauntlet/"],
            "_organizations_handler": [
                "/api/org/",
                "/api/user/organizations",
                "/api/invitations/",
            ],
            "_oauth_handler": ["/api/auth/oauth/", "/api/v1/auth/oauth/"],
            "_reviews_handler": ["/api/reviews/"],
            "_review_queue_handler": [
                "/api/review-queue",
                "/api/review-queue/",
                "/api/v1/review-queue",
                "/api/v1/review-queue/",
            ],
            "_formal_verification_handler": ["/api/verify/"],
            "_evidence_handler": ["/api/evidence"],
            "_folder_upload_handler": ["/api/documents/folder", "/api/documents/folders"],
            "_webhook_handler": ["/api/webhooks"],
            "_admin_handler": ["/api/admin"],
            "_control_plane_handler": ["/api/control-plane/"],
            "_knowledge_handler": ["/api/knowledge/"],
            "_knowledge_mound_handler": ["/api/knowledge/mound/"],
            "_policy_handler": ["/api/policies", "/api/compliance/"],
            "_queue_handler": ["/api/queue/"],
            "_moderation_handler": ["/api/moderation/"],
            "_rlm_context_handler": ["/api/rlm/"],
            "_training_handler": ["/api/training/"],
            "_transcription_handler": ["/api/transcription/", "/api/transcribe/"],
            "_uncertainty_handler": ["/api/uncertainty/"],
            "_verticals_handler": ["/api/verticals"],
            "_workspace_handler": [
                "/api/workspaces",
                "/api/retention/",
                "/api/classify",
                "/api/audit/",
            ],
            "_email_handler": [
                "/api/email/",
            ],
            "_teams_oauth_handler": [
                "/api/integrations/teams/install",
                "/api/integrations/teams/callback",
                "/api/integrations/teams/refresh",
            ],
            "_discord_oauth_handler": [
                "/api/integrations/discord/install",
                "/api/integrations/discord/callback",
                "/api/integrations/discord/uninstall",
            ],
            "_teams_integration_handler": [
                "/api/v1/integrations/teams",
            ],
            "_google_chat_handler": [
                "/api/bots/google-chat/",
            ],
            "_explainability_handler": [
                "/api/v1/debates/",
                "/api/v1/explain/",
                "/api/debates/",
                "/api/explain/",
            ],
            "_a2a_handler": [
                "/api/a2a/",
                "/.well-known/agent.json",
            ],
            "_code_intelligence_handler": [
                "/api/codebase/",
                "/api/v1/codebase/",
            ],
            "_advertising_handler": [
                "/api/advertising/",
                "/api/v1/advertising/",
            ],
            "_analytics_platforms_handler": [
                "/api/analytics-platforms/",
                "/api/v1/analytics-platforms/",
            ],
            "_crm_handler": [
                "/api/crm/",
                "/api/v1/crm/",
            ],
            "_support_handler": [
                "/api/support/",
                "/api/v1/support/",
            ],
            "_ecommerce_handler": [
                "/api/ecommerce/",
                "/api/v1/ecommerce/",
            ],
            "_receipts_handler": [
                "/api/v2/receipts",
                "/api/v2/receipts/",
                "/api/v1/receipts",
            ],
            "_backup_handler": [
                "/api/v2/backups",
                "/api/v2/backups/",
            ],
            "_dr_handler": [
                "/api/v2/dr",
                "/api/v2/dr/",
            ],
            "_compliance_handler": [
                "/api/v2/compliance",
                "/api/v2/compliance/",
            ],
            "_routing_handler": [
                "/api/routing/",
                "/api/v1/routing/",
            ],
            "_workflow_handler": [
                "/api/workflows",
                "/api/workflow-templates",
                "/api/workflow-executions",
                "/api/v1/workflows",
            ],
            "_slo_handler": [
                "/api/slos",
                "/api/slos/",
                "/api/v1/slos",
            ],
            "_connectors_handler": [
                "/api/connectors",
                "/api/connectors/",
                "/api/v1/connectors",
            ],
            "_marketplace_handler": [
                "/api/marketplace",
                "/api/marketplace/",
                "/api/v1/marketplace",
            ],
            "_onboarding_handler": [
                "/api/onboarding/",
                "/api/v1/onboarding/",
            ],
            "_sme_usage_dashboard_handler": [
                "/api/v1/usage/",
            ],
            "_canvas_handler": [
                "/api/v1/canvas",
                "/api/v1/canvas/",
            ],
            "_gateway_handler": [
                "/api/v1/gateway/",
            ],
            "_openclaw_gateway_handler": [
                "/api/openclaw/",
                "/api/v1/openclaw/",
                "/api/gateway/openclaw/",
                "/api/v1/gateway/openclaw/",
            ],
            "_scim_handler": [
                "/scim/",
                "/scim/v2/",
            ],
            "_computer_use_handler": [
                "/api/v1/computer-use/",
            ],
            "_unified_approvals_handler": [
                "/api/v1/approvals",
            ],
            "_rbac_handler": [
                "/api/v1/rbac/",
            ],
            "_cost_dashboard_handler": [
                "/api/v1/billing/dashboard",
            ],
            "_gastown_dashboard_handler": [
                "/api/v1/dashboard/gastown/",
            ],
            "_connector_management_handler": [
                "/api/v1/connectors/",
            ],
            "_task_execution_handler": [
                "/api/v2/tasks",
                "/api/v2/tasks/",
            ],
            "_security_debate_handler": [
                "/api/v1/audit/security/debate",
            ],
            "_autonomous_learning_handler": [
                "/api/v2/learning/",
            ],
            "_voice_handler": [
                "/api/v1/voice/",
                "/api/voice/",
            ],
            "_automation_handler": [
                "/api/v1/webhooks/",
                "/api/v1/n8n/",
            ],
            "_audit_trail_handler": [
                "/api/v1/audit-trails",
            ],
            "_playbook_handler": [
                "/api/playbooks",
                "/api/playbooks/",
                "/api/v1/playbooks",
                "/api/v1/playbooks/",
            ],
        }

        for attr_name, _ in handler_registry:
            handler = getattr(registry_mixin, attr_name, None)
            if handler is None:
                continue

            # Extract exact routes from ROUTES attribute
            routes = getattr(handler, "ROUTES", [])
            for path in routes:
                if path not in self._exact_routes:
                    self._exact_routes[path] = (attr_name, handler)

            # Add prefix patterns (static mapping + handler-provided prefixes)
            prefixes = list(PREFIX_PATTERNS.get(attr_name, []))
            handler_prefixes = getattr(handler, "ROUTE_PREFIXES", None)
            if handler_prefixes:
                for prefix in handler_prefixes:
                    if prefix not in prefixes:
                        prefixes.append(prefix)
            for prefix in prefixes:
                self._prefix_routes.append((prefix, attr_name, handler))

        # Clear the LRU cache when index is rebuilt
        self._get_handler_cached.cache_clear()

        logger.debug(
            "[route-index] Built index: %s exact, %s prefix patterns",
            len(self._exact_routes),
            len(self._prefix_routes),
        )

    def get_handler(self, path: str) -> tuple[str, Any] | None:
        """Get handler for path with O(1) lookup for known routes.

        Supports both versioned (/api/v1/debates) and legacy (/api/debates) paths.
        Versioned paths are normalized by stripping the version prefix before matching.

        Args:
            path: URL path to match

        Returns:
            Tuple of (attr_name, handler) or None if no match
        """
        from aragora.server.versioning import strip_version_prefix

        # Fast path: exact match (for legacy paths)
        if path in self._exact_routes:
            return self._exact_routes[path]

        # Try matching with version stripped (for /api/v1/* paths)
        normalized_path = strip_version_prefix(path)
        if normalized_path != path and normalized_path in self._exact_routes:
            return self._exact_routes[normalized_path]

        # Cached prefix lookup for dynamic routes
        return self._get_handler_cached(path, normalized_path)

    @lru_cache(maxsize=500)
    def _get_handler_cached(self, path: str, normalized_path: str) -> tuple[str, Any] | None:
        """Cached prefix matching for dynamic routes.

        Tries matching both the original path and the normalized (version-stripped) path.
        """
        # Try original path first
        for prefix, attr_name, handler in self._prefix_routes:
            if path.startswith(prefix):
                # Verify with handler's can_handle for complex patterns
                can_handle_fn = getattr(handler, "can_handle", None)
                if can_handle_fn is None or can_handle_fn(path):
                    return (attr_name, handler)

        # Try normalized path for versioned routes (/api/v1/debates -> /api/debates)
        if normalized_path != path:
            for prefix, attr_name, handler in self._prefix_routes:
                if normalized_path.startswith(prefix):
                    # Check if handler can handle the normalized path
                    can_handle_fn = getattr(handler, "can_handle", None)
                    if can_handle_fn is None or can_handle_fn(normalized_path):
                        return (attr_name, handler)

        return None


# Global route index instance (thread-safe singleton)
_route_index: RouteIndex | None = None
_route_index_lock = __import__("threading").Lock()


def get_route_index() -> RouteIndex:
    """Get or create the global route index.

    Thread-safe: uses double-checked locking to prevent multiple instances.
    """
    global _route_index
    if _route_index is None:
        with _route_index_lock:
            if _route_index is None:
                _route_index = RouteIndex()
    return _route_index


# =============================================================================
# Handler Validation
# =============================================================================


class HandlerValidationError(Exception):
    """Raised when a handler fails validation."""

    pass


def _supports_route_dispatch_without_can_handle(handler: Any) -> bool:
    """Return True when a handler uses registered route dispatch without can_handle()."""
    has_routes = hasattr(handler, "ROUTES")
    has_register = hasattr(handler, "register_routes") and callable(
        getattr(handler, "register_routes")
    )
    has_handle_star = any(
        attr.startswith("handle_")
        for attr in dir(handler)
        if not attr.startswith("__") and callable(getattr(handler, attr, None))
    )
    return has_routes or has_register or has_handle_star


def validate_handler_class(handler_class: Any, handler_name: str) -> list[str]:
    """
    Validate that a handler class has required methods and attributes.

    Args:
        handler_class: The handler class to validate
        handler_name: Name for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[str] = []

    if handler_class is None:
        errors.append(f"{handler_name}: Handler class is None")
        return errors

    # Handlers use varied dispatch patterns:
    # - can_handle + handle (standard BaseHandler)
    # - ROUTES + handle_* methods (cost, voice, inbox)
    # - register_routes (alert, autonomous)
    # - ROUTES only (facade handlers for OpenAPI discovery)
    can_handle_attr = getattr(handler_class, "can_handle", None)
    handle_attr = getattr(handler_class, "handle", None)
    has_can_handle_attr = hasattr(handler_class, "can_handle")
    has_handle_attr = hasattr(handler_class, "handle")
    has_can_handle = has_can_handle_attr and callable(can_handle_attr)
    has_handle = has_handle_attr and callable(handle_attr)
    has_handle_star = any(
        attr.startswith("handle_")
        for attr in dir(handler_class)
        if not attr.startswith("__") and callable(getattr(handler_class, attr, None))
    )
    has_register = hasattr(handler_class, "register_routes") and callable(
        getattr(handler_class, "register_routes")
    )
    has_routes = hasattr(handler_class, "ROUTES")

    if has_can_handle_attr and not has_can_handle:
        errors.append(f"{handler_name}: Method 'can_handle' is not callable")
    elif not has_can_handle:
        if _supports_route_dispatch_without_can_handle(handler_class):
            logger.debug(
                "%s: No can_handle() method (dispatched via ROUTES/handle*/register_routes)",
                handler_name,
            )
        else:
            errors.append(f"{handler_name}: Missing required method 'can_handle'")

    if has_handle_attr and not has_handle:
        errors.append(f"{handler_name}: Method 'handle' is not callable")
    elif not has_handle and not has_handle_star and not has_register:
        if has_routes:
            logger.debug(
                "%s: No handle() method (ROUTES-only facade for OpenAPI discovery)",
                handler_name,
            )
        else:
            errors.append(f"{handler_name}: Missing required method 'handle'")

    # Optional but recommended: ROUTES attribute for exact path matching
    if not has_routes:
        logger.debug("%s: No ROUTES attribute (will use prefix matching only)", handler_name)

    return errors


def validate_handler_instance(handler: Any, handler_name: str) -> list[str]:
    """
    Validate an instantiated handler works correctly.

    Args:
        handler: The handler instance
        handler_name: Name for error messages

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[str] = []

    if handler is None:
        errors.append(f"{handler_name}: Handler instance is None")
        return errors

    has_can_handle_attr = hasattr(handler, "can_handle")
    can_handle_attr = getattr(handler, "can_handle", None)
    has_can_handle = has_can_handle_attr and callable(can_handle_attr)
    if has_can_handle_attr and not has_can_handle:
        errors.append(f"{handler_name}: Method 'can_handle' is not callable")
        return errors
    if not has_can_handle:
        if _supports_route_dispatch_without_can_handle(handler):
            return errors
        errors.append(f"{handler_name}: Missing required method 'can_handle'")
        return errors

    # Verify can_handle doesn't crash with a test path
    try:
        result = handler.can_handle("/api/test-path-validation")
        if not isinstance(result, bool):
            errors.append(f"{handler_name}: can_handle() returned non-bool: {type(result)}")
    except (AttributeError, TypeError, ValueError, RuntimeError) as e:
        errors.append(f"{handler_name}: can_handle() raised exception: {e}")

    return errors


def validate_all_handlers(
    handler_registry: list[tuple[str, Any]],
    handlers_available: bool,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """
    Validate all registered handler classes.

    This should be called at startup to catch configuration issues early.

    Args:
        handler_registry: List of (attr_name, handler_class) pairs
        handlers_available: Whether handler imports succeeded
        raise_on_error: If True, raise exception on validation failures

    Returns:
        Dict with validation results:
        - valid: List of valid handler names
        - invalid: Dict of handler name -> error messages
        - missing: List of handlers that couldn't be imported
    """
    if not handlers_available:
        logger.debug("[handler-validation] Handler imports failed, skipping validation")
        return {
            "valid": [],
            "invalid": {},
            "missing": [name for name, _ in handler_registry],
            "status": "imports_failed",
        }

    results: dict[str, Any] = {
        "valid": [],
        "invalid": {},
        "missing": [],
        "status": "ok",
    }

    for attr_name, handler_class in handler_registry:
        handler_name = attr_name.replace("_handler", "").replace("_", " ").title()

        if handler_class is None:
            results["missing"].append(handler_name)
            continue

        errors = validate_handler_class(handler_class, handler_name)
        if errors:
            results["invalid"][handler_name] = errors
        else:
            results["valid"].append(handler_name)

    # Log summary
    valid_count = len(results["valid"])
    invalid_count = len(results["invalid"])
    missing_count = len(results["missing"])
    total = valid_count + invalid_count + missing_count

    if invalid_count > 0 or missing_count > 0:
        logger.warning(
            "[handler-validation] %s/%s handlers valid, %s invalid, %s missing",
            valid_count,
            total,
            invalid_count,
            missing_count,
        )
        for name, errors in results["invalid"].items():
            for error in errors:
                logger.warning("[handler-validation] %s", error)
        results["status"] = "validation_errors"
    else:
        logger.info("[handler-validation] All %s handlers validated successfully", valid_count)

    if raise_on_error and (invalid_count > 0 or missing_count > 0):
        raise HandlerValidationError(
            f"Handler validation failed: {invalid_count} invalid, {missing_count} missing"
        )

    return results


def check_handler_coverage(handler_registry: list[tuple[str, Any]]) -> None:
    """Log warnings for handler classes that exist in the codebase but aren't registered.

    Scans aragora/server/handlers/ for classes ending in 'Handler' and compares
    against handler_registry. Unregistered handlers are logged as warnings.
    Called during _init_handlers to surface gaps early.

    Gated by ARAGORA_CHECK_HANDLER_COVERAGE env var to avoid slowing server
    startup (AST-parses 580+ handler files).
    """
    if not os.environ.get("ARAGORA_CHECK_HANDLER_COVERAGE"):
        return

    import ast

    registered_names = set()
    for _, handler_class in handler_registry:
        if handler_class is None:
            continue
        if isinstance(handler_class, _DeferredImport):
            registered_names.add(handler_class._class_name)
        else:
            registered_names.add(handler_class.__name__)

    # Also include intended registrations from _safe_import calls in registry files.
    # This prevents false positives when a handler fails to import at runtime
    # (e.g. due to missing env vars) but is properly listed in the registry.
    registry_dir = os.path.dirname(__file__)
    for registry_file in glob_mod.glob(os.path.join(registry_dir, "*.py")):
        if os.path.basename(registry_file) in ("__init__.py", "core.py"):
            continue
        try:
            with open(registry_file) as rf:
                reg_tree = ast.parse(rf.read(), filename=registry_file)
            for node in ast.walk(reg_tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_safe_import"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                ):
                    class_name = node.args[1].value
                    if isinstance(class_name, str):
                        registered_names.add(class_name)
        except (SyntaxError, OSError):
            continue

    # Also include base/abstract classes that shouldn't be registered
    skip_names = {
        "BaseHandler",
        "BaseHTTPRequestHandler",
        "SecureHandler",
        "AuthenticatedHandler",
        "AsyncTypedHandler",
        "TypedHandler",
        "ResourceHandler",
        "VersionedAPIHandler",
        # "CompositeHandler" - now registered (provides /debates/*/full-context, /agents/*/reliability, /debates/*/compression-analysis)
        "PermissionHandler",
        "ExampleAsyncHandler",
        "ExampleAuthenticatedHandler",
        "ExamplePermissionHandler",
        "ExampleResourceHandler",
        "ExampleTypedHandler",
        "HandlerResult",
        "MockHandler",
        "MyHandler",
        "MyResourceHandler",
        "MyBotHandler",
        # ABCs and aliased handlers (registered under different names)
        "GauntletSecureHandler",
        "IntelligenceHandler",
        "IntegrationsHandler",
    }

    handler_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "handlers")
    if not os.path.isdir(handler_dir):
        return

    unregistered = []
    for py_file in glob_mod.glob(os.path.join(handler_dir, "**", "*.py"), recursive=True):
        try:
            with open(py_file) as f:
                tree = ast.parse(f.read(), filename=py_file)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Handler"):
                name = node.name
                if name not in registered_names and name not in skip_names:
                    rel_path = os.path.relpath(py_file, handler_dir)
                    unregistered.append((name, rel_path))

    if unregistered:
        logger.warning(
            "[handlers] %s handler class(es) found but not registered:", len(unregistered)
        )
        for name, path in sorted(unregistered):
            logger.warning("[handlers]   - %s (%s)", name, path)
    else:
        logger.info("[handlers] All handler classes are registered or skip-listed")


def validate_handlers_on_init(
    registry_mixin: Any,
    handler_registry: list[tuple[str, Any]],
) -> dict[str, Any]:
    """
    Validate instantiated handlers after initialization.

    Called from _init_handlers to verify all handlers work correctly.

    Args:
        registry_mixin: The HandlerRegistryMixin instance with initialized handlers
        handler_registry: List of (attr_name, handler_class) pairs

    Returns:
        Dict with validation results
    """
    results: dict[str, Any] = {
        "valid": [],
        "invalid": {},
        "not_initialized": [],
    }

    for attr_name, handler_class in handler_registry:
        handler_name = attr_name.replace("_handler", "").replace("_", " ").title()
        handler = getattr(registry_mixin, attr_name, None)

        if handler is None:
            results["not_initialized"].append(handler_name)
            continue

        errors = validate_handler_instance(handler, handler_name)
        if errors:
            results["invalid"][handler_name] = errors
        else:
            results["valid"].append(handler_name)

    if results["invalid"]:
        for name, errors in results["invalid"].items():
            for error in errors:
                logger.warning("[handler-instance-validation] %s", error)

    return results


__all__ = [
    # Types
    "HandlerType",
    # Utilities
    "_safe_import",
    "_run_handler_coroutine",
    # Route index
    "RouteIndex",
    "get_route_index",
    # Validation
    "HandlerValidationError",
    "validate_handler_class",
    "validate_handler_instance",
    "validate_all_handlers",
    "validate_handlers_on_init",
    "check_handler_coverage",
]
