"""
Main Knowledge Mound Handler.

Combines all mixins to provide the complete Knowledge Mound API:

Knowledge Mound API (unified knowledge storage):
- POST /api/knowledge/mound/query - Semantic query against knowledge mound
- POST /api/knowledge/mound/nodes - Add a knowledge node
- GET /api/knowledge/mound/nodes/:id - Get specific node
- GET /api/knowledge/mound/nodes/:id/relationships - Get relationships for a node
- GET /api/knowledge/mound/nodes/:id/visibility - Get node visibility
- PUT /api/knowledge/mound/nodes/:id/visibility - Set node visibility
- GET /api/knowledge/mound/nodes/:id/access - List access grants
- POST /api/knowledge/mound/nodes/:id/access - Grant access
- DELETE /api/knowledge/mound/nodes/:id/access - Revoke access
- GET /api/knowledge/mound/nodes - List/filter nodes
- POST /api/knowledge/mound/relationships - Add relationship between nodes
- GET /api/knowledge/mound/graph/:id - Get graph traversal from node
- GET /api/knowledge/mound/graph/:id/lineage - Get node lineage
- GET /api/knowledge/mound/graph/:id/related - Get related nodes
- GET /api/knowledge/mound/stats - Get mound statistics
- POST /api/knowledge/mound/index/repository - Index a repository
- GET /api/knowledge/mound/culture - Get culture profile
- POST /api/knowledge/mound/culture/documents - Add culture document
- POST /api/knowledge/mound/culture/promote - Promote knowledge to culture
- GET /api/knowledge/mound/stale - Get stale knowledge items
- POST /api/knowledge/mound/revalidate/:id - Revalidate specific node
- POST /api/knowledge/mound/schedule-revalidation - Schedule batch revalidation
- POST /api/knowledge/mound/sync/continuum - Sync from ContinuumMemory
- POST /api/knowledge/mound/sync/consensus - Sync from ConsensusMemory
- POST /api/knowledge/mound/sync/facts - Sync from FactStore
- GET /api/knowledge/mound/export/d3 - Export graph as D3 JSON
- GET /api/knowledge/mound/export/graphml - Export graph as GraphML

Sharing endpoints:
- POST /api/knowledge/mound/share - Share item with workspace/user
- GET /api/knowledge/mound/shared-with-me - Get items shared with me
- DELETE /api/knowledge/mound/share - Revoke a share
- PATCH /api/knowledge/mound/share - Update share permissions
- GET /api/knowledge/mound/my-shares - List items I've shared

Global knowledge endpoints:
- POST /api/knowledge/mound/global - Store verified fact (admin)
- GET /api/knowledge/mound/global - Query global knowledge
- POST /api/knowledge/mound/global/promote - Promote to global
- GET /api/knowledge/mound/global/facts - Get all system facts
- GET /api/knowledge/mound/global/workspace-id - Get system workspace ID

Federation endpoints:
- POST /api/knowledge/mound/federation/regions - Register federated region
- GET /api/knowledge/mound/federation/regions - List federated regions
- DELETE /api/knowledge/mound/federation/regions/:id - Unregister region
- POST /api/knowledge/mound/federation/sync/push - Sync to region
- POST /api/knowledge/mound/federation/sync/pull - Pull from region
- POST /api/knowledge/mound/federation/sync/all - Sync all regions
- GET /api/knowledge/mound/federation/status - Get federation status

Deduplication endpoints:
- GET /api/knowledge/mound/dedup/clusters - Find duplicate clusters
- GET /api/knowledge/mound/dedup/report - Generate dedup report
- POST /api/knowledge/mound/dedup/merge - Merge a duplicate cluster
- POST /api/knowledge/mound/dedup/auto-merge - Auto-merge exact duplicates

Pruning endpoints:
- GET /api/knowledge/mound/pruning/items - Get prunable items
- POST /api/knowledge/mound/pruning/execute - Prune specified items
- POST /api/knowledge/mound/pruning/auto - Run auto-prune with policy
- GET /api/knowledge/mound/pruning/history - Get pruning history
- POST /api/knowledge/mound/pruning/restore - Restore archived item
- POST /api/knowledge/mound/pruning/decay - Apply confidence decay

Phase A2 - Contradiction Detection endpoints:
- POST /api/knowledge/mound/contradictions/detect - Trigger contradiction scan
- GET /api/knowledge/mound/contradictions - List unresolved contradictions
- POST /api/knowledge/mound/contradictions/:id/resolve - Resolve a contradiction
- GET /api/knowledge/mound/contradictions/stats - Get contradiction statistics

Phase A2 - Governance (RBAC + Audit) endpoints:
- POST /api/knowledge/mound/governance/roles - Create a role
- POST /api/knowledge/mound/governance/roles/assign - Assign role to user
- POST /api/knowledge/mound/governance/roles/revoke - Revoke role from user
- GET /api/knowledge/mound/governance/permissions/:user_id - Get user permissions
- POST /api/knowledge/mound/governance/permissions/check - Check permission
- GET /api/knowledge/mound/governance/audit - Query audit trail
- GET /api/knowledge/mound/governance/audit/user/:user_id - Get user activity
- GET /api/knowledge/mound/governance/stats - Get governance stats

Phase A2 - Analytics endpoints:
- GET /api/knowledge/mound/analytics/coverage - Domain coverage analysis
- GET /api/knowledge/mound/analytics/usage - Usage pattern analysis
- POST /api/knowledge/mound/analytics/usage/record - Record usage event
- POST /api/knowledge/mound/analytics/quality/snapshot - Capture quality snapshot
- GET /api/knowledge/mound/analytics/quality/trend - Quality trend over time
- GET /api/knowledge/mound/analytics/stats - Analytics statistics

Phase A2 - Extraction endpoints:
- POST /api/knowledge/mound/extraction/debate - Extract from a debate
- POST /api/knowledge/mound/extraction/promote - Promote extracted claims
- GET /api/knowledge/mound/extraction/stats - Get extraction statistics

Phase A2 - Confidence Decay endpoints:
- POST /api/knowledge/mound/confidence/decay - Apply confidence decay
- POST /api/knowledge/mound/confidence/event - Record confidence event
- GET /api/knowledge/mound/confidence/history - Get adjustment history
- GET /api/knowledge/mound/confidence/stats - Get decay statistics
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.billing.tier_gating import require_tier
from aragora.rbac.decorators import require_permission
from aragora.server.http_utils import run_async as _run_async

from ...base import (
    BaseHandler,
    HandlerResult,
    error_response,
)
from ...utils.rate_limit import RateLimiter, get_client_ip

from .analytics import AnalyticsOperationsMixin
from .confidence_decay import ConfidenceDecayOperationsMixin
from .contradiction import ContradictionOperationsMixin
from .culture import CultureOperationsMixin
from .curation import CurationOperationsMixin
from .dashboard import DashboardOperationsMixin
from .dedup import DedupOperationsMixin
from .export import ExportOperationsMixin
from .extraction import ExtractionOperationsMixin
from .federation import FederationOperationsMixin
from .global_knowledge import GlobalKnowledgeOperationsMixin
from .governance import GovernanceOperationsMixin
from .graph import GraphOperationsMixin
from .nodes import NodeOperationsMixin
from .pruning import PruningOperationsMixin
from .relationships import RelationshipOperationsMixin
from .routing import RoutingMixin
from .sharing import SharingOperationsMixin
from .staleness import StalenessOperationsMixin
from .sync import SyncOperationsMixin
from .visibility import VisibilityOperationsMixin

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeMound

logger = logging.getLogger(__name__)

# Rate limiter for knowledge endpoints (100 requests per minute per user)
_knowledge_limiter = RateLimiter(requests_per_minute=100)


class _KnowledgeMoundMixins(  # type: ignore[misc]
    RoutingMixin,
    NodeOperationsMixin,
    RelationshipOperationsMixin,
    GraphOperationsMixin,
    CultureOperationsMixin,
    CurationOperationsMixin,
    StalenessOperationsMixin,
    SyncOperationsMixin,
    ExportOperationsMixin,
    VisibilityOperationsMixin,
    SharingOperationsMixin,
    GlobalKnowledgeOperationsMixin,
    FederationOperationsMixin,
    DedupOperationsMixin,
    PruningOperationsMixin,
    DashboardOperationsMixin,
    ContradictionOperationsMixin,
    GovernanceOperationsMixin,
    AnalyticsOperationsMixin,
    ExtractionOperationsMixin,
    ConfidenceDecayOperationsMixin,
):
    """Intermediate base combining all Knowledge Mound operation mixins."""


class KnowledgeMoundHandler(  # type: ignore[misc]
    _KnowledgeMoundMixins,
    BaseHandler,
):
    """Handler for Knowledge Mound API endpoints (unified knowledge storage).

    Combines mixins for:
    - Routing (RoutingMixin) - URL dispatch via dispatch table
    - Node CRUD operations (NodeOperationsMixin)
    - Relationship management (RelationshipOperationsMixin)
    - Graph traversal (GraphOperationsMixin)
    - Culture management (CultureOperationsMixin)
    - Staleness detection (StalenessOperationsMixin)
    - Legacy sync (SyncOperationsMixin)
    - Graph export (ExportOperationsMixin)
    - Visibility control (VisibilityOperationsMixin)
    - Cross-workspace sharing (SharingOperationsMixin)
    - Global/public knowledge (GlobalKnowledgeOperationsMixin)
    - Multi-region federation (FederationOperationsMixin)
    - Deduplication (DedupOperationsMixin)
    - Pruning and archival (PruningOperationsMixin)
    """

    ROUTES = [
        "/api/v1/knowledge/mound/query",
        "/api/v1/knowledge/mound/nodes",
        "/api/v1/knowledge/mound/nodes/*",
        "/api/v1/knowledge/mound/nodes/*/relationships",
        "/api/v1/knowledge/mound/nodes/*/visibility",
        "/api/v1/knowledge/mound/nodes/*/access",
        "/api/v1/knowledge/mound/relationships",
        "/api/v1/knowledge/mound/stats",
        "/api/v1/knowledge/mound/culture",
        "/api/v1/knowledge/mound/culture/*",
        "/api/v1/knowledge/mound/stale",
        "/api/v1/knowledge/mound/revalidate",
        "/api/v1/knowledge/mound/revalidate/*",
        "/api/v1/knowledge/mound/schedule-revalidation",
        "/api/v1/knowledge/mound/sync",
        "/api/v1/knowledge/mound/sync/*",
        "/api/v1/knowledge/mound/graph/*",
        "/api/v1/knowledge/mound/graph/*/lineage",
        "/api/v1/knowledge/mound/graph/*/related",
        "/api/v1/knowledge/mound/export/d3",
        "/api/v1/knowledge/mound/export/graphml",
        # Sharing
        "/api/v1/knowledge/mound/share",
        "/api/v1/knowledge/mound/shared-with-me",
        "/api/v1/knowledge/mound/my-shares",
        # Global knowledge
        "/api/v1/knowledge/mound/global",
        "/api/v1/knowledge/mound/global/facts",
        "/api/v1/knowledge/mound/global/promote",
        # Federation
        "/api/v1/knowledge/mound/federation/regions",
        "/api/v1/knowledge/mound/federation/regions/*",
        "/api/v1/knowledge/mound/federation/status",
        "/api/v1/knowledge/mound/federation/sync/push",
        "/api/v1/knowledge/mound/federation/sync/pull",
        "/api/v1/knowledge/mound/federation/sync/all",
        # Index
        "/api/v1/knowledge/mound/index/repository",
        # Deduplication
        "/api/v1/knowledge/mound/dedup/clusters",
        "/api/v1/knowledge/mound/dedup/report",
        "/api/v1/knowledge/mound/dedup/merge",
        "/api/v1/knowledge/mound/dedup/auto-merge",
        # Pruning
        "/api/v1/knowledge/mound/pruning/items",
        "/api/v1/knowledge/mound/pruning/execute",
        "/api/v1/knowledge/mound/pruning/auto",
        "/api/v1/knowledge/mound/pruning/history",
        "/api/v1/knowledge/mound/pruning/restore",
        "/api/v1/knowledge/mound/pruning/decay",
        # Dashboard and metrics
        "/api/v1/knowledge/mound/dashboard/health",
        "/api/v1/knowledge/mound/dashboard/metrics",
        "/api/v1/knowledge/mound/dashboard/metrics/reset",
        "/api/v1/knowledge/mound/dashboard/adapters",
        "/api/v1/knowledge/mound/dashboard/queries",
        "/api/v1/knowledge/mound/dashboard/batcher",
        # Auto-curation (Phase 4)
        "/api/v1/knowledge/mound/curation/policy",
        "/api/v1/knowledge/mound/curation/status",
        "/api/v1/knowledge/mound/curation/run",
        "/api/v1/knowledge/mound/curation/history",
        "/api/v1/knowledge/mound/curation/scores",
        "/api/v1/knowledge/mound/curation/tiers",
        # Phase A2 - Contradiction detection
        "/api/v1/knowledge/mound/contradictions/detect",
        "/api/v1/knowledge/mound/contradictions",
        "/api/v1/knowledge/mound/contradictions/*/resolve",
        "/api/v1/knowledge/mound/contradictions/stats",
        # Phase A2 - Governance (RBAC + Audit)
        "/api/v1/knowledge/mound/governance/roles",
        "/api/v1/knowledge/mound/governance/roles/assign",
        "/api/v1/knowledge/mound/governance/roles/revoke",
        "/api/v1/knowledge/mound/governance/permissions",
        "/api/v1/knowledge/mound/governance/permissions/*",
        "/api/v1/knowledge/mound/governance/permissions/check",
        "/api/v1/knowledge/mound/governance/audit",
        "/api/v1/knowledge/mound/governance/audit/user",
        "/api/v1/knowledge/mound/governance/audit/user/*",
        "/api/v1/knowledge/mound/governance/stats",
        # Phase A2 - Analytics
        "/api/v1/knowledge/mound/analytics/coverage",
        "/api/v1/knowledge/mound/analytics/usage",
        "/api/v1/knowledge/mound/analytics/usage/record",
        "/api/v1/knowledge/mound/analytics/quality/snapshot",
        "/api/v1/knowledge/mound/analytics/quality/trend",
        "/api/v1/knowledge/mound/analytics/stats",
        # Phase A2 - Extraction
        "/api/v1/knowledge/mound/extraction/debate",
        "/api/v1/knowledge/mound/extraction/promote",
        "/api/v1/knowledge/mound/extraction/stats",
        # Phase A2 - Confidence decay
        "/api/v1/knowledge/mound/confidence/decay",
        "/api/v1/knowledge/mound/confidence/event",
        "/api/v1/knowledge/mound/confidence/history",
        "/api/v1/knowledge/mound/confidence/stats",
        # Culture endpoints
        "/api/v1/knowledge/mound/culture/documents",
        "/api/v1/knowledge/mound/culture/promote",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize knowledge mound handler."""
        super().__init__(server_context)
        self._mound: KnowledgeMound | None = None
        self._mound_initialized = False

    def _get_mound(self) -> KnowledgeMound | None:
        """Get or create Knowledge Mound instance."""
        if self._mound is None:
            from aragora.knowledge.mound import KnowledgeMound

            self._mound = KnowledgeMound(workspace_id="default")  # type: ignore[abstract]
            try:
                _run_async(self._mound.initialize())
                self._mound_initialized = True
            except (RuntimeError, OSError, ValueError) as e:
                logger.exception("Failed to initialize Knowledge Mound: %s", e)
                self._mound = None
        return self._mound

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path.startswith("/api/v1/knowledge/mound/")

    @require_tier("professional", feature_name="Knowledge Mound")
    @require_permission("knowledge:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route knowledge mound requests to appropriate methods.

        This method uses a dispatch table pattern via RoutingMixin._dispatch_route()
        to reduce cyclomatic complexity from 88+ to <10.
        """
        # Rate limit check using user ID if authenticated, otherwise client IP
        rate_key = self._get_rate_limit_key(handler)
        rate_error = self._check_rate_limit(rate_key)
        if rate_error:
            return rate_error

        # Require authentication for all knowledge mound endpoints
        auth_error = self._check_authentication(handler)
        if auth_error:
            return auth_error

        # Dispatch to appropriate handler via routing mixin
        return self._dispatch_route(path, query_params, handler)

    def _get_rate_limit_key(self, handler: Any) -> str:
        """Get rate limit key (user ID or client IP)."""
        auth_ctx = getattr(handler, "_auth_context", None)
        user_id = None
        if auth_ctx:
            user_id = getattr(auth_ctx, "user_id", None) or getattr(auth_ctx, "sub", None)
        return user_id if user_id else get_client_ip(handler)

    def _check_rate_limit(self, rate_key: str) -> HandlerResult | None:
        """Check rate limit and return error response if exceeded."""
        if not _knowledge_limiter.is_allowed(rate_key):
            remaining = _knowledge_limiter.get_remaining(rate_key)
            logger.warning("Rate limit exceeded for mound endpoint: %s", rate_key)
            headers = {
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": str(remaining),
                "Retry-After": "60",
            }
            return error_response(
                "Rate limit exceeded. Please try again later.", 429, headers=headers
            )
        return None

    def _check_authentication(self, handler: Any) -> HandlerResult | None:
        """Check authentication and return error response if failed."""
        try:
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
        except (ValueError, TypeError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Authentication failed for knowledge mound: %s", e)
            return error_response("Authentication required", 401)
        return None
