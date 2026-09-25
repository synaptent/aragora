"""
Unified Orchestration Handler for Aragora Control Plane.

Provides a single API that embodies "Control plane for multi-agent
vetted decisionmaking across org knowledge and channels":

- Accept knowledge context sources (Slack channel, Confluence page, etc.)
- Auto-fetch content as vetted decisionmaking context
- Run vetted decisionmaking with specified or auto-selected agent team
- Route results to output channels
- Return receipt with full provenance

Endpoints:
    POST /api/v1/orchestration/deliberate     - Unified vetted decisionmaking endpoint
    GET  /api/v1/orchestration/status/:id     - Get vetted decisionmaking status
    GET  /api/v1/orchestration/templates      - List available templates
    POST /api/v1/orchestration/deliberate/sync - Synchronous vetted decisionmaking
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, cast

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.http_utils import run_async

from aragora.server.handlers.orchestration.models import (
    KnowledgeContextSource,
    OrchestrationRequest,
    OrchestrationResult,
    OutputChannel,
    OutputFormat,
    TeamStrategy,
)
from aragora.server.handlers.orchestration.validation import (
    PERM_CHANNEL_DISCORD,
    PERM_CHANNEL_EMAIL,
    PERM_CHANNEL_SLACK,
    PERM_CHANNEL_TEAMS,
    PERM_CHANNEL_TELEGRAM,
    PERM_CHANNEL_WEBHOOK,
    PERM_KNOWLEDGE_CONFLUENCE,
    PERM_KNOWLEDGE_DOCUMENT,
    PERM_KNOWLEDGE_GITHUB,
    PERM_KNOWLEDGE_JIRA,
    PERM_KNOWLEDGE_SLACK,
    PERM_ORCH_ADMIN,
    PERM_ORCH_CHANNELS_WRITE,
    PERM_ORCH_DELIBERATE,
    PERM_ORCH_KNOWLEDGE_READ,
    SourceIdValidationError,
    safe_source_id,
    validate_channel_id,
)
from aragora.server.handlers.orchestration.templates import TEMPLATES

logger = logging.getLogger(__name__)

# =============================================================================
# In-Memory State (Production would use Redis/DB)
# =============================================================================

_orchestration_requests: dict[str, OrchestrationRequest] = {}
_orchestration_results: dict[str, OrchestrationResult] = {}

# =============================================================================
# Handler Implementation
# =============================================================================


class OrchestrationHandler(SecureHandler):
    """
    Unified orchestration handler for the Aragora control plane.

    This handler provides the primary API for the "Control plane for
    multi-agent vetted decisionmaking across org knowledge and channels" positioning.

    RBAC Permissions:
    - orchestration:read - View templates and deliberation status
    - orchestration:execute - Run deliberations
    - orchestration:deliberate:create - Create new deliberations
    - orchestration:knowledge:read - Access knowledge sources
    - orchestration:knowledge:{type} - Access specific knowledge source types
    - orchestration:channels:write - Write to output channels
    - orchestration:channel:{type} - Write to specific channel types
    - orchestration:admin - Administrative operations
    """

    RESOURCE_TYPE = "orchestration"

    # Knowledge source type to permission mapping
    KNOWLEDGE_SOURCE_PERMISSIONS: dict[str, str] = {
        "slack": PERM_KNOWLEDGE_SLACK,
        "teams": PERM_KNOWLEDGE_SLACK,  # Reuse Slack permission for chat platforms
        "discord": PERM_KNOWLEDGE_SLACK,
        "telegram": PERM_KNOWLEDGE_SLACK,
        "whatsapp": PERM_KNOWLEDGE_SLACK,
        "google_chat": PERM_KNOWLEDGE_SLACK,
        "confluence": PERM_KNOWLEDGE_CONFLUENCE,
        "github": PERM_KNOWLEDGE_GITHUB,
        "jira": PERM_KNOWLEDGE_JIRA,
        "document": PERM_KNOWLEDGE_DOCUMENT,
        "doc": PERM_KNOWLEDGE_DOCUMENT,
        "km": PERM_KNOWLEDGE_DOCUMENT,
    }

    # Channel type to permission mapping
    CHANNEL_PERMISSIONS: dict[str, str] = {
        "slack": PERM_CHANNEL_SLACK,
        "teams": PERM_CHANNEL_TEAMS,
        "discord": PERM_CHANNEL_DISCORD,
        "telegram": PERM_CHANNEL_TELEGRAM,
        "email": PERM_CHANNEL_EMAIL,
        "webhook": PERM_CHANNEL_WEBHOOK,
    }

    def _check_permission(
        self,
        auth_context: Any,
        permission: str,
        resource_id: str | None = None,
    ) -> HandlerResult | None:
        """
        Check if the user has a specific permission.

        Args:
            auth_context: The authorization context from get_auth_context()
            permission: The permission string to check
            resource_id: Optional resource ID for resource-specific checks

        Returns:
            None if permission is granted, error HandlerResult if denied
        """
        try:
            self.check_permission(auth_context, permission, resource_id)
            return None
        except ForbiddenError:
            logger.warning("Permission denied: %s for user %s", permission, auth_context.user_id)
            return error_response("Permission denied", 403)

    def _validate_knowledge_source(
        self,
        source: KnowledgeContextSource,
        auth_context: Any,
    ) -> HandlerResult | None:
        """
        Validate a knowledge source for security and RBAC.

        Performs:
        1. Path traversal prevention on source_id
        2. RBAC permission check for the source type
        3. Format validation

        Args:
            source: The knowledge source to validate
            auth_context: User's authorization context

        Returns:
            None if valid, error HandlerResult if validation fails
        """
        # Validate source_id for path traversal
        try:
            safe_source_id(source.source_id)
        except SourceIdValidationError as e:
            logger.warning("[SECURITY] Invalid source_id from user %s: %s", auth_context.user_id, e)
            return error_response("Invalid source identifier", 400)

        # Check knowledge source type permission
        source_type = source.source_type.lower()
        if source_type in self.KNOWLEDGE_SOURCE_PERMISSIONS:
            perm = self.KNOWLEDGE_SOURCE_PERMISSIONS[source_type]
            perm_error = self._check_permission(auth_context, perm, source.source_id)
            if perm_error:
                return perm_error
        else:
            # Unknown source type - require admin permission
            perm_error = self._check_permission(auth_context, PERM_ORCH_ADMIN)
            if perm_error:
                logger.warning(
                    "Unknown knowledge source type '%s' requires admin permission", source_type
                )
                return error_response(f"Unknown knowledge source type: {source_type}", 400)

        # Also check general knowledge read permission
        perm_error = self._check_permission(
            auth_context, PERM_ORCH_KNOWLEDGE_READ, source.source_id
        )
        if perm_error:
            return perm_error

        return None

    def _validate_output_channel(
        self,
        channel: OutputChannel,
        auth_context: Any,
    ) -> HandlerResult | None:
        """
        Validate an output channel for security and RBAC.

        Performs:
        1. Channel ID validation (path traversal prevention)
        2. RBAC permission check for the channel type
        3. Format validation for webhooks

        Args:
            channel: The output channel to validate
            auth_context: User's authorization context

        Returns:
            None if valid, error HandlerResult if validation fails
        """
        # Validate channel_id
        try:
            validate_channel_id(channel.channel_id, channel.channel_type.lower())
        except ValueError as e:
            logger.warning(
                "[SECURITY] Invalid channel_id from user %s: %s", auth_context.user_id, e
            )
            return error_response("Invalid channel identifier", 400)

        # Check channel type permission
        channel_type = channel.channel_type.lower()
        if channel_type in self.CHANNEL_PERMISSIONS:
            perm = self.CHANNEL_PERMISSIONS[channel_type]
            perm_error = self._check_permission(auth_context, perm, channel.channel_id)
            if perm_error:
                return perm_error
        else:
            # Unknown channel type - require admin permission
            perm_error = self._check_permission(auth_context, PERM_ORCH_ADMIN)
            if perm_error:
                logger.warning("Unknown channel type '%s' requires admin permission", channel_type)
                return error_response(f"Unknown channel type: {channel_type}", 400)

        # Also check general channel write permission
        perm_error = self._check_permission(
            auth_context, PERM_ORCH_CHANNELS_WRITE, channel.channel_id
        )
        if perm_error:
            return perm_error

        return None

    ROUTES = [
        "/api/v1/orchestration/deliberate",
        "/api/v1/orchestration/deliberate/sync",
        "/api/v1/orchestration/status/*",
        "/api/v1/orchestration/templates",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path.startswith("/api/v1/orchestration/")

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests."""
        # Require authentication for all orchestration operations
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)
        except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Authentication failed for orchestration request: %s", exc)
            return error_response("Authentication required", 401)

        # Check read permission
        try:
            self.check_permission(auth_context, "orchestration:read")
        except ForbiddenError:
            logger.warning("Orchestration read denied for user %s", auth_context.user_id)
            return error_response("Permission denied", 403)

        if path == "/api/v1/orchestration/templates":
            return self._get_templates(query_params)

        if path.startswith("/api/v1/orchestration/status/"):
            request_id = path.split("/")[-1]
            return self._get_status(request_id)

        return None

    # Signature differs from BaseHandler to support data-first calling convention
    # used by unified_server's POST routing. This is intentional.
    @handle_errors("orchestration creation")
    async def handle_post(  # type: ignore[override]
        self,
        path: str,
        data: dict[str, Any],
        query_params: dict[str, Any] | Any | None = None,
        handler: Any | None = None,
    ) -> HandlerResult | None:
        """Route POST requests."""
        if handler is None and query_params is not None and not isinstance(query_params, dict):
            handler = query_params
            query_params = {}
        if query_params is None:
            query_params = {}
        # Require authentication for all orchestration operations
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # Execute operations require execute permission
        try:
            self.check_permission(auth_context, "orchestration:execute")
        except ForbiddenError:
            logger.warning("Orchestration execute denied for user %s", auth_context.user_id)
            return error_response("Permission denied", 403)

        # Also check deliberate permission for deliberation endpoints
        if path in ("/api/v1/orchestration/deliberate", "/api/v1/orchestration/deliberate/sync"):
            try:
                self.check_permission(auth_context, PERM_ORCH_DELIBERATE)
            except ForbiddenError:
                logger.warning("Deliberation create denied for user %s", auth_context.user_id)
                return error_response("Permission denied", 403)

        if path == "/api/v1/orchestration/deliberate":
            return self._handle_deliberate(data, handler, auth_context, sync=False)

        if path == "/api/v1/orchestration/deliberate/sync":
            return self._handle_deliberate(data, handler, auth_context, sync=True)

        return None

    # =========================================================================
    # Endpoint Handlers
    # =========================================================================

    def _get_templates(self, query_params: dict[str, Any]) -> HandlerResult:
        """
        GET /api/v1/orchestration/templates

        Returns list of available vetted decisionmaking templates.

        Query params:
            category: Filter by category (e.g. "business", "code", "legal")
            search: Text search in name and description
            tags: Comma-separated tag filter (OR matching)
            limit: Max results (default 50)
            offset: Pagination offset (default 0)
        """
        from aragora.server.handlers.orchestration.templates import _list_templates

        category = query_params.get("category")
        search = query_params.get("search")
        tags_raw = query_params.get("tags")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

        try:
            limit = max(1, min(int(query_params.get("limit", 50)), 500))
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = max(0, int(query_params.get("offset", 0)))
        except (ValueError, TypeError):
            offset = 0

        if _list_templates is not None:
            templates = _list_templates(
                category=category,
                search=search,
                tags=tags,
                limit=limit,
                offset=offset,
            )
            template_dicts = [t.to_dict() for t in templates]
        else:
            # Fallback: unfiltered from TEMPLATES dict
            template_dicts = [t.to_dict() for t in TEMPLATES.values()]

        return json_response(
            {
                "templates": template_dicts,
                "count": len(template_dicts),
            }
        )

    def _get_status(self, request_id: str) -> HandlerResult:
        """
        GET /api/v1/orchestration/status/:id

        Returns status of a vetted decisionmaking request.
        """
        if request_id in _orchestration_results:
            result = _orchestration_results[request_id]
            return json_response(
                {
                    "request_id": request_id,
                    "status": "completed" if result.success else "failed",
                    "result": result.to_dict(),
                }
            )

        if request_id in _orchestration_requests:
            return json_response(
                {
                    "request_id": request_id,
                    "status": "in_progress",
                    "result": None,
                }
            )

        return error_response("Request not found", 404)

    @rate_limit(requests_per_minute=30)
    def _handle_deliberate(
        self, data: dict[str, Any], handler: Any, auth_context: Any, sync: bool = False
    ) -> HandlerResult:
        """
        POST /api/v1/orchestration/deliberate
        POST /api/v1/orchestration/deliberate/sync

        Unified vetted decisionmaking endpoint that:
        1. Validates knowledge sources and output channels (RBAC + path traversal)
        2. Fetches context from knowledge sources
        3. Selects agent team based on strategy
        4. Runs vetted decisionmaking
        5. Routes results to output channels
        6. Returns receipt with provenance

        Security checks:
        - Path traversal prevention on all source_ids and channel_ids
        - RBAC permission checks for each knowledge source type
        - RBAC permission checks for each output channel type
        - Input validation and sanitization
        """
        try:
            # Parse request
            request = OrchestrationRequest.from_dict(data)

            # Validate question
            if not request.question:
                return error_response("Question is required", 400)

            # Apply template if specified
            if request.template and request.template in TEMPLATES:
                template = TEMPLATES[request.template]
                if not request.agents:
                    request.agents = template.default_agents
                if not request.knowledge_sources:
                    for src in template.default_knowledge_sources:
                        request.knowledge_sources.append(KnowledgeContextSource.from_string(src))
                request.output_format = cast(OutputFormat, template.output_format)
                request.max_rounds = template.max_rounds

            # ================================================================
            # SECURITY: Validate all knowledge sources before processing
            # ================================================================
            for source in request.knowledge_sources:
                validation_error = self._validate_knowledge_source(source, auth_context)
                if validation_error:
                    logger.warning(
                        "[SECURITY] Knowledge source validation failed for user %s: %s:%s",
                        auth_context.user_id,
                        source.source_type,
                        source.source_id,
                    )
                    return validation_error

            # ================================================================
            # SECURITY: Validate all output channels before processing
            # ================================================================
            for channel in request.output_channels:
                validation_error = self._validate_output_channel(channel, auth_context)
                if validation_error:
                    logger.warning(
                        "[SECURITY] Output channel validation failed for user %s: %s:%s",
                        auth_context.user_id,
                        channel.channel_type,
                        channel.channel_id,
                    )
                    return validation_error

            # ================================================================
            # Cost estimation
            # ================================================================
            cost_estimate = None
            try:
                from aragora.server.handlers.debates.cost_estimation import estimate_debate_cost

                cost_estimate = estimate_debate_cost(
                    num_agents=len(request.agents) or 3,
                    num_rounds=request.max_rounds,
                    model_types=request.agents if request.agents else None,
                )
            except (ImportError, ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.warning("Cost estimation failed (non-blocking): %s", exc)

            # Handle dry_run - return estimate only
            if request.dry_run:
                return json_response(
                    {
                        "request_id": request.request_id,
                        "dry_run": True,
                        "estimated_cost": cost_estimate,
                        "agents": request.agents,
                        "max_rounds": request.max_rounds,
                        "message": "Dry run — no debate executed",
                    }
                )

            # Extract total cost as float for non-dry-run responses
            estimated_cost_usd = None
            if cost_estimate and "total_estimated_cost_usd" in cost_estimate:
                estimated_cost_usd = float(cost_estimate["total_estimated_cost_usd"])

            # Store request
            _orchestration_requests[request.request_id] = request

            if sync:
                # Synchronous execution
                result = run_async(self._execute_deliberation(request))
                _orchestration_results[request.request_id] = result
                response_data = result.to_dict()
                if estimated_cost_usd is not None:
                    response_data["estimated_cost_usd"] = estimated_cost_usd
                return json_response(response_data)
            else:
                # Async execution - queue and return immediately
                task = asyncio.create_task(self._execute_and_store(request))
                task.add_done_callback(
                    lambda t: logger.error("Async deliberation failed: %s", t.exception())
                    if not t.cancelled() and t.exception()
                    else None
                )
                response_data = {
                    "request_id": request.request_id,
                    "status": "queued",
                    "message": "Deliberation queued. Check status at /api/v1/orchestration/status/{request_id}",
                }
                if estimated_cost_usd is not None:
                    response_data["estimated_cost_usd"] = estimated_cost_usd
                return json_response(
                    response_data,
                    status=202,
                )

        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
            OSError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Orchestration error: %s", e)
            return error_response("Orchestration failed", 500)

    # =========================================================================
    # Core Orchestration Logic
    # =========================================================================

    async def _execute_and_store(self, request: OrchestrationRequest) -> None:
        """Execute vetted decisionmaking and store result."""
        try:
            result = await self._execute_deliberation(request)
            _orchestration_results[request.request_id] = result
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
            OSError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Async vetted decisionmaking failed: %s", e)
            _orchestration_results[request.request_id] = OrchestrationResult(
                request_id=request.request_id,
                success=False,
                error="Orchestration failed",
            )
        finally:
            # Clean up request from in-progress
            _orchestration_requests.pop(request.request_id, None)

    async def _execute_deliberation(self, request: OrchestrationRequest) -> OrchestrationResult:
        """
        Execute a unified orchestration vetted decisionmaking session.

        This is the core method that ties together:
        - Knowledge context fetching
        - Agent team selection
        - Deliberation execution
        - Output channel routing
        """
        import time

        start_time = time.time()
        knowledge_context_used: list[str] = []
        channels_notified: list[str] = []

        try:
            # Step 1: Fetch knowledge context
            context_parts: list[str] = []
            for source in request.knowledge_sources:
                try:
                    context = await self._fetch_knowledge_context(source)
                    if context:
                        context_parts.append(
                            f"[{source.source_type}:{source.source_id}]\n{context}"
                        )
                        knowledge_context_used.append(f"{source.source_type}:{source.source_id}")
                except (
                    ConnectionError,
                    TimeoutError,
                    OSError,
                    ValueError,
                    ImportError,
                    AttributeError,
                ) as e:
                    logger.warning(
                        "Failed to fetch context from %s:%s: %s",
                        source.source_type,
                        source.source_id,
                        e,
                    )

            # Combine context with question
            full_context = "\n\n".join(context_parts) if context_parts else None

            # Step 2: Select agent team
            agents = await self._select_agent_team(request)

            # Step 3: Run vetted decisionmaking
            from typing import cast as typing_cast
            from aragora.control_plane.deliberation import DeliberationManager
            from aragora.control_plane.coordinator import ControlPlaneCoordinator

            # coordinator may be None if not configured in server context
            raw_coordinator = self.ctx.get("control_plane_coordinator")
            coordinator: ControlPlaneCoordinator | None = (
                typing_cast(ControlPlaneCoordinator, raw_coordinator)
                if raw_coordinator is not None
                else None
            )
            manager = DeliberationManager(coordinator=coordinator)

            if coordinator:
                # Use control plane task scheduling
                task_id = await manager.submit_deliberation(
                    question=request.question,
                    context=full_context,
                    agents=agents,
                    priority=request.priority,
                    timeout_seconds=request.timeout_seconds,
                    max_rounds=request.max_rounds,
                    consensus_required=request.require_consensus,
                    metadata={
                        "orchestration_request_id": request.request_id,
                        "knowledge_sources": knowledge_context_used,
                        "auto_notify": request.notify,
                        "output_channels": [
                            f"{c.channel_type}:{c.channel_id}" for c in request.output_channels
                        ],
                    },
                )

                # Wait for result
                outcome = await manager.wait_for_outcome(
                    task_id, timeout=request.timeout_seconds + 30
                )

                if outcome:
                    # Build result from outcome
                    result = OrchestrationResult(
                        request_id=request.request_id,
                        success=outcome.success,
                        consensus_reached=outcome.consensus_reached,
                        final_answer=outcome.winning_position,
                        confidence=outcome.consensus_confidence,
                        agents_participated=agents,
                        rounds_completed=0,  # Would come from outcome
                        duration_seconds=time.time() - start_time,
                        knowledge_context_used=knowledge_context_used,
                        receipt_id=task_id,
                    )
                else:
                    result = OrchestrationResult(
                        request_id=request.request_id,
                        success=False,
                        error="Deliberation timed out",
                        duration_seconds=time.time() - start_time,
                        knowledge_context_used=knowledge_context_used,
                    )
            else:
                # Fallback: Direct vetted decisionmaking without control plane
                from aragora.core.decision import DecisionRequest, get_decision_router, DecisionType

                from aragora.core.decision import RequestContext

                decision_request = DecisionRequest(
                    content=request.question,
                    decision_type=DecisionType.DEBATE,
                    context=RequestContext(
                        metadata={"auto_notify": request.notify},
                    ),
                )

                router = get_decision_router()
                decision_result = await router.route(decision_request)

                result = OrchestrationResult(
                    request_id=request.request_id,
                    success=decision_result.success,
                    consensus_reached=getattr(decision_result, "consensus_reached", False),
                    final_answer=getattr(decision_result, "final_answer", None),
                    confidence=getattr(decision_result, "confidence", None),
                    agents_participated=agents,
                    rounds_completed=getattr(decision_result, "rounds", 0),
                    duration_seconds=time.time() - start_time,
                    knowledge_context_used=knowledge_context_used,
                )

            # Step 4: Route results to output channels
            if result.success:
                for channel in request.output_channels:
                    try:
                        await self._route_to_channel(channel, result, request)
                        channels_notified.append(f"{channel.channel_type}:{channel.channel_id}")
                    except (
                        ConnectionError,
                        TimeoutError,
                        OSError,
                        ValueError,
                        ImportError,
                        AttributeError,
                    ) as e:
                        logger.warning(
                            "Failed to route to %s:%s: %s",
                            channel.channel_type,
                            channel.channel_id,
                            e,
                        )

            result.channels_notified = channels_notified
            return result

        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Deliberation execution failed: %s", e)
            return OrchestrationResult(
                request_id=request.request_id,
                success=False,
                error="Deliberation execution failed",
                duration_seconds=time.time() - start_time,
                knowledge_context_used=knowledge_context_used,
            )

    async def _fetch_knowledge_context(self, source: KnowledgeContextSource) -> str | None:
        """Fetch context from a knowledge source."""
        source_type = source.source_type.lower()

        # Chat platform channels (Slack, Teams, Discord, Telegram, WhatsApp)
        chat_platforms = {"slack", "teams", "discord", "telegram", "whatsapp", "google_chat"}
        if source_type in chat_platforms:
            return await self._fetch_chat_context(source_type, source)

        # Confluence page
        if source_type == "confluence":
            return await self._fetch_confluence_context(source)

        # GitHub PR/issue
        if source_type == "github":
            return await self._fetch_github_context(source)

        # Document from knowledge mound
        if source_type in ("document", "doc", "km"):
            return await self._fetch_document_context(source)

        # Jira issue
        if source_type == "jira":
            return await self._fetch_jira_context(source)

        logger.warning("Unknown knowledge source type: %s", source_type)
        return None

    async def _fetch_chat_context(
        self, platform: str, source: KnowledgeContextSource
    ) -> str | None:
        """
        Fetch context from any chat platform using the registry.

        Supports: Slack, Teams, Discord, Telegram, WhatsApp, Google Chat.
        """
        try:
            from aragora.connectors.chat.registry import get_connector

            connector = get_connector(platform)
            if connector is None:
                logger.warning("No %s connector available", platform)
                return None

            ctx = await connector.fetch_context(
                channel_id=source.source_id,
                lookback_minutes=source.lookback_minutes,
                max_messages=source.max_items,
            )
            if ctx and ctx.messages:
                return ctx.to_context_string(max_messages=source.max_items)

            return None
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to fetch %s context: %s", platform, e)
        return None

    async def _fetch_confluence_context(self, source: KnowledgeContextSource) -> str | None:
        """Fetch content from a Confluence page.

        Note: ConfluenceConnector requires base_url configuration. This method
        expects the connector to be configured via environment or context.
        The source_id could be a page_id like "confluence-12345" or just "12345".
        """
        try:
            import os
            from aragora.connectors.enterprise.collaboration.confluence import ConfluenceConnector

            # Get base_url from context or environment
            ctx_url = self.ctx.get("confluence_url")
            confluence_url: str = (
                str(ctx_url) if ctx_url else os.environ.get("CONFLUENCE_BASE_URL", "")
            )
            if not confluence_url:
                logger.warning("Confluence base URL not configured")
                return None

            connector = ConfluenceConnector(base_url=confluence_url)
            # Use the fetch method which exists on the connector
            # source_id could be page_id or space_key/page_title
            page_id = source.source_id
            if not page_id.startswith("confluence-"):
                page_id = f"confluence-{page_id}"
            evidence = await connector.fetch(page_id)
            if evidence:
                return str(getattr(evidence, "content", ""))
            return None
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to fetch Confluence context: %s", e)
        return None

    async def _fetch_github_context(self, source: KnowledgeContextSource) -> str | None:
        """Fetch content from a GitHub PR or issue.

        Uses the GitHubConnector's search method to retrieve content.
        source_id format: owner/repo/pr/123 or owner/repo/issue/123

        Security: Validates source_id before splitting to prevent path traversal.
        """
        try:
            from aragora.connectors.github import GitHubConnector

            # SECURITY: Defense-in-depth validation before splitting
            # Note: Primary validation happens in _validate_knowledge_source,
            # but we add another check here in case this method is called directly
            source_id = source.source_id
            if ".." in source_id or source_id.startswith("/"):
                logger.warning(
                    "[SECURITY] Path traversal attempt in GitHub source_id: %s", source_id[:50]
                )
                return None

            # source_id format: owner/repo/pr/123 or owner/repo/issue/123
            parts = source_id.split("/")
            if len(parts) >= 4:
                owner, repo, item_type, number = parts[0], parts[1], parts[2], parts[3]

                # SECURITY: Validate each component
                # Owner and repo should be alphanumeric with hyphens/underscores
                owner_pattern = re.compile(r"^[a-zA-Z0-9_\-]+$")
                if not owner_pattern.match(owner) or not owner_pattern.match(repo):
                    logger.warning(
                        "[SECURITY] Invalid GitHub owner/repo format: %s/%s", owner, repo
                    )
                    return None

                # Item type must be either 'pr' or 'issue'
                if item_type not in ("pr", "issue", "prs", "issues"):
                    logger.warning("[SECURITY] Invalid GitHub item type: %s", item_type)
                    return None

                # Number must be numeric
                if not number.isdigit():
                    logger.warning("[SECURITY] Invalid GitHub PR/issue number: %s", number)
                    return None

                full_repo = f"{owner}/{repo}"
                connector = GitHubConnector(repo=full_repo)

                # Use search to find the specific PR/issue
                search_type = "prs" if item_type in ("pr", "prs") else "issues"
                results = await connector.search(
                    query=f"#{number}",
                    limit=1,
                    search_type=search_type,
                )
                if results:
                    # Evidence objects have content attribute
                    return str(getattr(results[0], "content", ""))
            return None
        except SourceIdValidationError as e:
            logger.warning("[SECURITY] GitHub source_id validation failed: %s", e)
            return None
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to fetch GitHub context: %s", e)
        return None

    async def _fetch_document_context(self, source: KnowledgeContextSource) -> str | None:
        """Fetch content from knowledge mound."""
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            mound = get_knowledge_mound()
            if mound:
                # Query for relevant knowledge using the KnowledgeMound API
                results = await mound.query(source.source_id, limit=source.max_items)
                if results and hasattr(results, "items"):
                    # QueryResult has an items attribute with KnowledgeItem objects
                    return "\n\n".join(
                        str(getattr(item, "content", ""))
                        for item in results.items
                        if getattr(item, "content", None)
                    )
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to fetch document context: %s", e)
        return None

    async def _fetch_jira_context(self, source: KnowledgeContextSource) -> str | None:
        """Fetch content from a Jira issue.

        Note: JiraConnector requires base_url configuration. This method
        expects the connector to be configured via environment or context.
        The source_id should be a Jira issue key like "PROJ-123".
        """
        try:
            import os
            from aragora.connectors.enterprise.collaboration.jira import JiraConnector

            # Get base_url from context or environment
            ctx_url = self.ctx.get("jira_url")
            jira_url: str = str(ctx_url) if ctx_url else os.environ.get("JIRA_BASE_URL", "")
            if not jira_url:
                logger.warning("Jira base URL not configured")
                return None

            connector = JiraConnector(base_url=jira_url)
            # Use the fetch method which exists on the connector
            issue_key = source.source_id
            if not issue_key.startswith("jira-"):
                issue_key = f"jira-{issue_key}"
            evidence = await connector.fetch(issue_key)
            if evidence:
                return str(getattr(evidence, "content", ""))
            return None
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to fetch Jira context: %s", e)
        return None

    async def _select_agent_team(self, request: OrchestrationRequest) -> list[str]:
        """Select agent team based on strategy."""
        # If agents explicitly specified, use them
        if request.agents:
            return request.agents

        # Default agent pool
        default_agents = ["anthropic-api", "openai-api", "gemini", "mistral"]

        if request.team_strategy == TeamStrategy.SPECIFIED:
            return request.agents or default_agents[:2]

        if request.team_strategy == TeamStrategy.FAST:
            return default_agents[:2]

        if request.team_strategy == TeamStrategy.DIVERSE:
            return default_agents

        if request.team_strategy == TeamStrategy.RANDOM:
            import random

            return random.sample(default_agents, min(3, len(default_agents)))

        # BEST_FOR_DOMAIN - use routing handler if available
        try:
            import aragora.server.handlers.agents.routing as routing_module

            recommend_fn = getattr(routing_module, "recommend_agents", None)
            if recommend_fn is not None:
                recommended = await recommend_fn(request.question)
                if recommended:
                    return recommended[:4]
        except (ImportError, AttributeError) as e:
            logger.debug("Routing handler not available: %s", e)
        except (ValueError, TypeError, RuntimeError, OSError) as e:
            logger.warning("Agent routing failed: %s", e)

        return default_agents[:3]

    async def _route_to_channel(
        self,
        channel: OutputChannel,
        result: OrchestrationResult,
        request: OrchestrationRequest,
    ) -> None:
        """Route vetted decisionmaking result to an output channel."""
        channel_type = channel.channel_type.lower()

        # Format message based on output format
        message = self._format_result_for_channel(result, request)

        if channel_type == "slack":
            await self._send_to_slack(channel, message)
        elif channel_type == "teams":
            await self._send_to_teams(channel, message)
        elif channel_type == "discord":
            await self._send_to_discord(channel, message)
        elif channel_type == "telegram":
            await self._send_to_telegram(channel, message)
        elif channel_type == "email":
            await self._send_to_email(channel, message, request)
        elif channel_type == "webhook":
            await self._send_to_webhook(channel, result)
        else:
            logger.warning("Unknown channel type: %s", channel_type)

    def _format_result_for_channel(
        self, result: OrchestrationResult, request: OrchestrationRequest
    ) -> str:
        """Format result for channel delivery."""
        if request.output_format == OutputFormat.SUMMARY:
            return f"**Deliberation Complete**\n\n{result.final_answer or 'No conclusion reached.'}"

        consensus_status = "Consensus reached" if result.consensus_reached else "No consensus"
        confidence_str = f" ({result.confidence:.0%} confidence)" if result.confidence else ""

        return (
            f"**Deliberation Result**\n\n"
            f"**Question:** {request.question[:200]}...\n\n"
            f"**Status:** {consensus_status}{confidence_str}\n\n"
            f"**Answer:**\n{result.final_answer or 'No conclusion reached.'}\n\n"
            f"**Agents:** {', '.join(result.agents_participated)}\n"
            f"**Duration:** {result.duration_seconds:.1f}s\n"
            f"**Request ID:** `{result.request_id}`"
        )

    async def _send_to_slack(self, channel: OutputChannel, message: str) -> None:
        """Send result to Slack."""
        try:
            from aragora.connectors.chat.registry import get_connector

            connector = get_connector("slack")
            if connector:
                await connector.send_message(
                    channel.channel_id,
                    message,
                    thread_ts=channel.thread_id,
                )
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send to Slack: %s", e)

    async def _send_to_teams(self, channel: OutputChannel, message: str) -> None:
        """Send result to Microsoft Teams."""
        try:
            from aragora.connectors.chat.registry import get_connector

            connector = get_connector("teams")
            if connector:
                await connector.send_message(channel.channel_id, message)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send to Teams: %s", e)

    async def _send_to_discord(self, channel: OutputChannel, message: str) -> None:
        """Send result to Discord."""
        try:
            from aragora.connectors.chat.registry import get_connector

            connector = get_connector("discord")
            if connector:
                await connector.send_message(channel.channel_id, message)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send to Discord: %s", e)

    async def _send_to_telegram(self, channel: OutputChannel, message: str) -> None:
        """Send result to Telegram."""
        try:
            from aragora.connectors.chat.registry import get_connector

            connector = get_connector("telegram")
            if connector:
                await connector.send_message(channel.channel_id, message)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send to Telegram: %s", e)

    async def _send_to_email(
        self, channel: OutputChannel, message: str, request: OrchestrationRequest
    ) -> None:
        """Send result via email."""
        try:
            import aragora.connectors.email as email_module

            send_fn = getattr(email_module, "send_email", None)
            if send_fn is not None:
                await send_fn(
                    to=channel.channel_id,
                    subject=f"Deliberation Result: {request.question[:50]}...",
                    body=message,
                )
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send email: %s", e)

    async def _send_to_webhook(self, channel: OutputChannel, result: OrchestrationResult) -> None:
        """Send result to webhook."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    channel.channel_id,
                    json=result.to_dict(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status >= 400:
                        logger.warning("Webhook returned %s", response.status)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            AttributeError,
        ) as e:
            logger.warning("Failed to send to webhook: %s", e)


# =============================================================================
# Module-level singleton
# =============================================================================

handler = OrchestrationHandler({})
