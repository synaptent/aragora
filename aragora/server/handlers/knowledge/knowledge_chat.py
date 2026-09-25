"""
HTTP Handler for Knowledge + Chat Bridge.

Provides REST API endpoints for chat-knowledge integration:
- POST /api/v1/chat/knowledge/search - Search knowledge from chat context
- POST /api/v1/chat/knowledge/inject - Get relevant knowledge for conversation
- POST /api/v1/chat/knowledge/store - Store chat as knowledge
- GET /api/v1/chat/knowledge/channel/:id/summary - Get channel knowledge summary
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.errors import safe_error_message
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_clamped_int_param,
    success_response,
    handle_errors,
)
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.rbac.decorators import require_permission
from aragora.resilience import with_timeout

logger = logging.getLogger(__name__)

# Input bounds for validation
MAX_RESULTS_LIMIT = 100
MAX_CONTEXT_ITEMS_LIMIT = 50
MAX_ITEMS_LIMIT = 100

# Lazy-loaded bridge instance
_bridge = None


def _get_bridge():
    """Get or create the Knowledge + Chat bridge."""
    global _bridge
    if _bridge is None:
        from aragora.services.knowledge_chat_bridge import get_knowledge_chat_bridge

        _bridge = get_knowledge_chat_bridge()
    return _bridge


@api_endpoint(
    method="POST",
    path="/api/v1/chat/knowledge/search",
    summary="Search knowledge from chat context",
    description="Search for relevant knowledge based on query and workspace/channel context.",
    tags=["Knowledge", "Chat"],
    responses={
        "200": {
            "description": "Search results returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "channel_id": {"type": "string"},
                            "workspace_id": {"type": "string"},
                            "query": {"type": "string"},
                            "results": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "node_id": {"type": "string"},
                                        "content": {"type": "string"},
                                        "node_type": {"type": "string"},
                                        "confidence": {"type": "number"},
                                        "relevance_score": {"type": "number"},
                                        "source": {"type": "string"},
                                        "created_at": {"type": "string"},
                                        "metadata": {"type": "object"},
                                        "provenance": {"type": "string"},
                                    },
                                },
                            },
                            "result_count": {"type": "integer"},
                            "search_scope": {"type": "string"},
                            "search_time_ms": {"type": "number"},
                            "suggestions": {"type": "array", "items": {"type": "string"}},
                            "error": {"type": "string"},
                        },
                    }
                }
            },
        },
        "401": {"description": "Unauthorized"},
        "500": {"description": "Search failed"},
    },
)
@require_permission("knowledge:read")
@with_timeout(15.0)
async def handle_knowledge_search(
    query: str,
    workspace_id: str = "default",
    channel_id: str | None = None,
    user_id: str | None = None,
    scope: str = "workspace",
    strategy: str = "hybrid",
    node_types: list[str] | None = None,
    min_confidence: float = 0.3,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search knowledge from chat context.

    POST /api/v1/chat/knowledge/search
    {
        "query": "What's the policy on remote work?",
        "workspace_id": "ws_123",
        "channel_id": "C123456",
        "scope": "workspace",
        "strategy": "hybrid",
        "node_types": ["policy", "document"],
        "max_results": 10
    }
    """
    from aragora.services.knowledge_chat_bridge import (
        KnowledgeSearchScope,
        RelevanceStrategy,
    )

    try:
        bridge = _get_bridge()

        # Parse enums
        try:
            search_scope = KnowledgeSearchScope(scope)
        except ValueError:
            search_scope = KnowledgeSearchScope.WORKSPACE

        try:
            search_strategy = RelevanceStrategy(strategy)
        except ValueError:
            search_strategy = RelevanceStrategy.HYBRID

        # Execute search
        context = await bridge.search_knowledge(
            query=query,
            workspace_id=workspace_id,
            channel_id=channel_id,
            user_id=user_id,
            scope=search_scope,
            strategy=search_strategy,
            node_types=node_types,
            min_confidence=min_confidence,
            max_results=max_results,
        )

        return {
            "success": True,
            **context.to_dict(),
        }

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Knowledge search failed")
        return {
            "success": False,
            "error": safe_error_message(e),
        }


@api_endpoint(
    method="POST",
    path="/api/v1/chat/knowledge/inject",
    summary="Inject knowledge into conversation",
    description="Get relevant knowledge items to inject into an ongoing conversation.",
    tags=["Knowledge", "Chat"],
    responses={
        "200": {
            "description": "Knowledge context returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "context": {"type": "array", "items": {"type": "object"}},
                            "item_count": {"type": "integer"},
                            "error": {"type": "string"},
                        },
                    }
                }
            },
        },
        "401": {"description": "Unauthorized"},
        "500": {"description": "Injection failed"},
    },
)
@require_permission("knowledge:read")
@with_timeout(15.0)
async def handle_knowledge_inject(
    messages: list[dict[str, Any]],
    workspace_id: str = "default",
    channel_id: str | None = None,
    max_context_items: int = 5,
) -> dict[str, Any]:
    """
    Get relevant knowledge to inject into a conversation.

    POST /api/v1/chat/knowledge/inject
    {
        "messages": [
            {"author": "user1", "content": "What's our vacation policy?"},
            {"author": "user2", "content": "I think it's in the handbook"}
        ],
        "workspace_id": "ws_123",
        "channel_id": "C123456",
        "max_context_items": 5
    }
    """
    try:
        bridge = _get_bridge()

        results = await bridge.inject_knowledge_for_conversation(
            messages=messages,
            workspace_id=workspace_id,
            channel_id=channel_id,
            max_context_items=max_context_items,
        )

        return {
            "success": True,
            "context": [r.to_dict() for r in results],
            "item_count": len(results),
        }

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Knowledge injection failed")
        return {
            "success": False,
            "error": safe_error_message(e),
        }


@api_endpoint(
    method="POST",
    path="/api/v1/chat/knowledge/store",
    summary="Store chat as knowledge",
    description="Store chat messages as persistent knowledge for future retrieval.",
    tags=["Knowledge", "Chat"],
    responses={
        "200": {
            "description": "Chat stored as knowledge",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "node_id": {"type": "string"},
                            "message_count": {"type": "integer"},
                            "error": {"type": "string"},
                        },
                    }
                }
            },
        },
        "400": {"description": "At least 2 messages required"},
        "401": {"description": "Unauthorized"},
        "500": {"description": "Storage failed"},
    },
)
@require_permission("knowledge:update")
@with_timeout(20.0)
async def handle_store_chat_knowledge(
    messages: list[dict[str, Any]],
    workspace_id: str = "default",
    channel_id: str = "",
    channel_name: str = "",
    platform: str = "unknown",
    node_type: str = "chat_context",
) -> dict[str, Any]:
    """
    Store chat messages as knowledge.

    POST /api/v1/chat/knowledge/store
    {
        "messages": [
            {"author": "user1", "content": "We decided to use Python 3.11"},
            {"author": "user2", "content": "Agreed, it has better performance"}
        ],
        "workspace_id": "ws_123",
        "channel_id": "C123456",
        "channel_name": "#engineering",
        "platform": "slack"
    }
    """
    try:
        if len(messages) < 2:
            return {
                "success": False,
                "error": "At least 2 messages required",
            }

        bridge = _get_bridge()

        node_id = await bridge.store_chat_as_knowledge(
            messages=messages,
            workspace_id=workspace_id,
            channel_id=channel_id,
            channel_name=channel_name,
            platform=platform,
            node_type=node_type,
        )

        if node_id:
            return {
                "success": True,
                "node_id": node_id,
                "message_count": len(messages),
            }
        else:
            return {
                "success": False,
                "error": "Failed to store knowledge",
            }

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Store chat knowledge failed")
        return {
            "success": False,
            "error": safe_error_message(e),
        }


@api_endpoint(
    method="GET",
    path="/api/v1/chat/knowledge/channel/{channel_id}/summary",
    summary="Get channel knowledge summary",
    description="Get a summary of knowledge related to a specific channel.",
    tags=["Knowledge", "Chat"],
    parameters=[
        {"name": "channel_id", "in": "path", "required": True, "schema": {"type": "string"}}
    ],
    responses={
        "200": {
            "description": "Channel knowledge summary",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "success": {"type": "boolean"},
                            "error": {"type": "string"},
                        },
                        "additionalProperties": True,
                    }
                }
            },
        },
        "401": {"description": "Unauthorized"},
        "500": {"description": "Summary failed"},
    },
)
@require_permission("knowledge:read")
async def handle_channel_knowledge_summary(
    channel_id: str,
    workspace_id: str = "default",
    max_items: int = 10,
) -> dict[str, Any]:
    """
    Get a summary of knowledge related to a channel.

    GET /api/v1/chat/knowledge/channel/:id/summary
    """
    try:
        bridge = _get_bridge()

        summary = await bridge.get_channel_knowledge_summary(
            channel_id=channel_id,
            workspace_id=workspace_id,
            max_items=max_items,
        )

        return {
            "success": True,
            **summary,
        }

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.exception("Channel summary failed")
        return {
            "success": False,
            "error": safe_error_message(e),
        }


class KnowledgeChatHandler(BaseHandler):
    """
    HTTP handler for Knowledge + Chat bridge endpoints.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    # RBAC permission keys
    KNOWLEDGE_READ_PERMISSION = "knowledge.read"
    KNOWLEDGE_WRITE_PERMISSION = "knowledge.write"

    ROUTES = [
        "/api/v1/chat/knowledge/search",
        "/api/v1/chat/knowledge/inject",
        "/api/v1/chat/knowledge/store",
        "/api/v1/chat/knowledge/channel/*",
        "/api/v1/chat/knowledge/channel/*/summary",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/chat/knowledge/channel/",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request."""
        if path in self.ROUTES:
            return True
        for prefix in self.ROUTE_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    @rate_limit(requests_per_minute=60, limiter_name="knowledge_chat_read")
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle GET requests."""
        # Check read permission for all GET requests
        _, perm_error = self.require_permission_or_error(handler, self.KNOWLEDGE_READ_PERMISSION)
        if perm_error:
            return perm_error

        # GET /api/v1/chat/knowledge/channel/:id/summary
        if path.startswith("/api/v1/chat/knowledge/channel/") and path.endswith("/summary"):
            # Extract channel_id from path
            # Path: /api/v1/chat/knowledge/channel/<channel_id>/summary
            # Index:  0   1   2     3         4        5           6
            parts = path.split("/")
            if len(parts) >= 8:
                channel_id = parts[6]
                workspace_id = query_params.get("workspace_id", "default")
                # Validate and clamp max_items to bounds
                max_items = get_clamped_int_param(
                    query_params,
                    "max_items",
                    default=10,
                    min_val=1,
                    max_val=MAX_ITEMS_LIMIT,
                )

                result = await handle_channel_knowledge_summary(
                    channel_id=channel_id,
                    workspace_id=workspace_id,
                    max_items=max_items,
                )

                if result.get("success"):
                    return success_response(result)
                else:
                    return error_response(result.get("error", "Unknown error"), 400)

        return None

    @handle_errors("knowledge chat creation")
    @rate_limit(requests_per_minute=30, limiter_name="knowledge_chat_write")
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        # Check appropriate permission based on operation
        if path == "/api/v1/chat/knowledge/store":
            # Store requires write permission
            _, perm_error = self.require_permission_or_error(
                handler, self.KNOWLEDGE_WRITE_PERMISSION
            )
        else:
            # Search/inject requires read permission
            _, perm_error = self.require_permission_or_error(
                handler, self.KNOWLEDGE_READ_PERMISSION
            )
        if perm_error:
            return perm_error

        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        if path == "/api/v1/chat/knowledge/search":
            query = body.get("query")
            if not isinstance(query, str) or not query.strip():
                return error_response("query must be a non-empty string", 400)

            node_types = body.get("node_types")
            if node_types is not None and (
                not isinstance(node_types, list)
                or any(not isinstance(node_type, str) for node_type in node_types)
            ):
                return error_response("node_types must be a list of strings", 400)

            min_confidence = body.get("min_confidence", 0.3)
            if isinstance(min_confidence, bool) or not isinstance(min_confidence, int | float):
                return error_response("min_confidence must be a number", 400)

            max_results_raw = body.get("max_results", 10)
            if isinstance(max_results_raw, bool) or not isinstance(max_results_raw, int):
                return error_response("max_results must be an integer", 400)

            # Validate and clamp max_results
            max_results = min(max(1, max_results_raw), MAX_RESULTS_LIMIT)

            workspace_id = body.get("workspace_id", "default")
            if not isinstance(workspace_id, str):
                return error_response("workspace_id must be a string", 400)
            scope = body.get("scope", "workspace")
            if not isinstance(scope, str):
                return error_response("scope must be a string", 400)
            strategy = body.get("strategy", "hybrid")
            if not isinstance(strategy, str):
                return error_response("strategy must be a string", 400)
            channel_id = body.get("channel_id")
            if channel_id is not None and not isinstance(channel_id, str):
                return error_response("channel_id must be a string", 400)
            user_id = body.get("user_id")
            if user_id is not None and not isinstance(user_id, str):
                return error_response("user_id must be a string", 400)

            result = await handle_knowledge_search(
                query=query.strip(),
                workspace_id=workspace_id,
                channel_id=channel_id,
                user_id=user_id,
                scope=scope,
                strategy=strategy,
                node_types=node_types,
                min_confidence=float(min_confidence),
                max_results=max_results,
            )

        elif path == "/api/v1/chat/knowledge/inject":
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                return error_response("messages must be a non-empty list", 400)
            if any(not isinstance(message, dict) for message in messages):
                return error_response("messages must be a list of objects", 400)

            max_context_items_raw = body.get("max_context_items", 5)
            if isinstance(max_context_items_raw, bool) or not isinstance(
                max_context_items_raw, int
            ):
                return error_response("max_context_items must be an integer", 400)

            # Validate and clamp max_context_items
            max_context_items = min(max(1, max_context_items_raw), MAX_CONTEXT_ITEMS_LIMIT)

            workspace_id = body.get("workspace_id", "default")
            if not isinstance(workspace_id, str):
                return error_response("workspace_id must be a string", 400)
            channel_id = body.get("channel_id")
            if channel_id is not None and not isinstance(channel_id, str):
                return error_response("channel_id must be a string", 400)

            result = await handle_knowledge_inject(
                messages=messages,
                workspace_id=workspace_id,
                channel_id=channel_id,
                max_context_items=max_context_items,
            )

        elif path == "/api/v1/chat/knowledge/store":
            messages = body.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                return error_response("At least 2 messages required", 400)
            if any(not isinstance(message, dict) for message in messages):
                return error_response("messages must be a list of objects", 400)

            workspace_id = body.get("workspace_id", "default")
            if not isinstance(workspace_id, str):
                return error_response("workspace_id must be a string", 400)
            channel_id = body.get("channel_id", "")
            if not isinstance(channel_id, str):
                return error_response("channel_id must be a string", 400)
            channel_name = body.get("channel_name", "")
            if not isinstance(channel_name, str):
                return error_response("channel_name must be a string", 400)
            platform = body.get("platform", "unknown")
            if not isinstance(platform, str):
                return error_response("platform must be a string", 400)
            node_type = body.get("node_type", "chat_context")
            if not isinstance(node_type, str):
                return error_response("node_type must be a string", 400)

            result = await handle_store_chat_knowledge(
                messages=messages,
                workspace_id=workspace_id,
                channel_id=channel_id,
                channel_name=channel_name,
                platform=platform,
                node_type=node_type,
            )

        else:
            return None

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 400)


__all__ = [
    "KnowledgeChatHandler",
    "handle_knowledge_search",
    "handle_knowledge_inject",
    "handle_store_chat_knowledge",
    "handle_channel_knowledge_summary",
]
