"""
Playbook HTTP handler.

Endpoints for discovering and running decision playbooks:
- GET  /api/v1/playbooks          - List available playbooks
- GET  /api/v1/playbooks/{id}     - Get playbook details
- POST /api/v1/playbooks/{id}/run - Run a playbook (starts debate with playbook config)

Follows the BaseHandler pattern from base.py with HandlerResult.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.decorators import require_permission

logger = logging.getLogger(__name__)


class PlaybookHandler(BaseHandler):
    """Handler for playbook API endpoints.

    Provides REST APIs for decision playbook discovery and execution.
    Extends BaseHandler for standard handler dispatch integration.
    """

    ROUTES = [
        "/api/playbooks",
    ]

    ROUTE_PREFIXES = [
        "/api/playbooks",
        "/api/playbooks/",
        "/api/v1/playbooks",
        "/api/v1/playbooks/",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        """Initialize handler with server context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given request."""
        normalized = strip_version_prefix(path)
        return normalized == "/api/playbooks" or normalized.startswith("/api/playbooks/")

    @require_permission("playbooks:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        normalized = strip_version_prefix(path)
        path_clean = normalized.rstrip("/")

        if path_clean == "/api/playbooks":
            return self._list_playbooks(query_params)

        if "/playbooks/" in normalized and not path_clean.endswith("/run"):
            return self._get_playbook(normalized)

        return None

    @handle_errors("run playbook")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests."""
        normalized = strip_version_prefix(path)
        path_clean = normalized.rstrip("/")

        if path_clean.endswith("/run"):
            body = self.read_json_body(handler)
            if body is None:
                return error_response("Invalid JSON body", 400)
            return self._run_playbook(normalized, body)

        return None

    # ------------------------------------------------------------------
    # GET /api/v1/playbooks
    # ------------------------------------------------------------------

    @handle_errors("list playbooks")
    def _list_playbooks(self, query_params: dict[str, Any]) -> HandlerResult:
        """List available playbooks with optional category/tag filtering.

        Query params:
            category: Filter by category (e.g. "healthcare", "finance")
            tags: Comma-separated tag filter (OR matching)
        """
        from aragora.playbooks.registry import get_playbook_registry

        registry = get_playbook_registry()

        category = query_params.get("category")
        tags_raw = query_params.get("tags", "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

        playbooks = registry.list(category=category, tags=tags)

        return json_response(
            {
                "playbooks": [p.to_dict() for p in playbooks],
                "count": len(playbooks),
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/playbooks/{id}
    # ------------------------------------------------------------------

    @handle_errors("get playbook")
    def _get_playbook(self, path: str) -> HandlerResult:
        """Get a single playbook by ID."""
        from aragora.playbooks.registry import get_playbook_registry

        playbook_id = self._extract_playbook_id(path)
        if not playbook_id:
            return error_response("Missing playbook ID", 400)

        registry = get_playbook_registry()
        playbook = registry.get(playbook_id)

        if not playbook:
            return error_response(f"Playbook not found: {playbook_id}", 404)

        return json_response(playbook.to_dict())

    # ------------------------------------------------------------------
    # POST /api/v1/playbooks/{id}/run
    # ------------------------------------------------------------------

    def _run_playbook(self, path: str, body: dict[str, Any]) -> HandlerResult:
        """Start a debate using the playbook's configuration.

        Body:
            input: str  -- The question/topic for the playbook (required)
            context: dict -- Additional context variables
        """
        from aragora.playbooks.registry import get_playbook_registry

        playbook_id = self._extract_playbook_id(path, strip_run=True)
        if not playbook_id:
            return error_response("Missing playbook ID", 400)

        registry = get_playbook_registry()
        playbook = registry.get(playbook_id)

        if not playbook:
            return error_response(f"Playbook not found: {playbook_id}", 404)

        input_text = body.get("input", "")
        if not input_text:
            return error_response("input is required", 400)

        context = body.get("context", {})
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Build the execution plan
        execution = {
            "run_id": run_id,
            "playbook_id": playbook.id,
            "playbook_name": playbook.name,
            "input": input_text,
            "context": context,
            "status": "queued",
            "created_at": now.isoformat(),
            "steps": [s.to_dict() for s in playbook.steps],
            "config": {
                "template_name": playbook.template_name,
                "vertical_profile": playbook.vertical_profile,
                "min_agents": playbook.min_agents,
                "max_agents": playbook.max_agents,
                "max_rounds": playbook.max_rounds,
                "consensus_threshold": playbook.consensus_threshold,
            },
        }

        logger.info(
            "Playbook run queued: %s (playbook=%s, input=%s)",
            run_id,
            playbook.id,
            input_text[:100],
        )

        return json_response(execution, status=202)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_playbook_id(path: str, strip_run: bool = False) -> str | None:
        """Extract playbook ID from a path like /api/playbooks/{id}[/run]."""
        segments = path.strip("/").split("/")
        for i, seg in enumerate(segments):
            if seg == "playbooks" and i + 1 < len(segments):
                pid = segments[i + 1]
                if pid == "run":
                    return None
                return pid
        return None


__all__ = ["PlaybookHandler"]
