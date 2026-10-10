"""
Query Operations Mixin for Knowledge Handler.

Provides natural language query handling for the knowledge base.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.knowledge import QueryOptions
from aragora.server.http_utils import run_async as _run_async
from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..openapi_decorator import api_endpoint
from .facts import caller_org_or_error

if TYPE_CHECKING:
    from aragora.knowledge import DatasetQueryEngine, SimpleQueryEngine

logger = logging.getLogger(__name__)


class QueryHandlerProtocol(Protocol):
    """Protocol for handlers that use QueryOperationsMixin."""

    def _get_query_engine(self) -> DatasetQueryEngine | SimpleQueryEngine: ...
    def require_auth_or_error(self, handler: Any) -> tuple[Any, HandlerResult | None]: ...


class QueryOperationsMixin:
    """Mixin providing query operations for KnowledgeHandler."""

    @api_endpoint(
        method="POST",
        path="/api/v1/knowledge/query",
        summary="Natural language query against the knowledge base",
        tags=["Knowledge Base"],
        request_body={
            "description": "Query payload with question and options",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["question"],
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "Natural language question to ask",
                            },
                            "workspace_id": {"type": "string", "default": "default"},
                            "options": {
                                "type": "object",
                                "properties": {
                                    "max_chunks": {"type": "integer", "default": 10},
                                    "search_alpha": {"type": "number", "default": 0.5},
                                    "use_agents": {"type": "boolean", "default": False},
                                    "extract_facts": {"type": "boolean", "default": True},
                                    "include_citations": {"type": "boolean", "default": True},
                                },
                            },
                        },
                    }
                }
            },
        },
        responses={
            "200": {
                "description": "Query result with answer and supporting evidence",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "answer": {"type": "string"},
                                "confidence": {"type": "number"},
                                "citations": {"type": "array", "items": {"type": "object"}},
                                "sources": {"type": "array", "items": {"type": "object"}},
                            },
                            "additionalProperties": True,
                        }
                    }
                },
            },
            "400": {"description": "Invalid request body or missing question"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "500": {"description": "Query execution failed"},
        },
    )
    @handle_errors("knowledge query")
    @require_permission("knowledge:read")
    def _handle_query(
        self: QueryHandlerProtocol, query_params: dict, handler: Any
    ) -> HandlerResult:
        """Handle POST /api/knowledge/query - Query the caller's organization's knowledge."""
        org_id, err = caller_org_or_error(self, handler)
        if err:
            return err

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        question = data.get("question", "")
        if not question:
            return error_response("Question is required", 400)

        workspace_id = data.get("workspace_id", "default")
        options_data = data.get("options", {})

        options = QueryOptions(
            max_chunks=options_data.get("max_chunks", 10),
            search_alpha=options_data.get("search_alpha", 0.5),
            use_agents=options_data.get("use_agents", False),
            extract_facts=options_data.get("extract_facts", True),
            include_citations=options_data.get("include_citations", True),
        )

        engine = self._get_query_engine()

        try:
            result = _run_async(engine.query(question, workspace_id, options, org_id=org_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Query execution failed: %s", e)
            return error_response("Query execution failed", 500)

        return json_response(result.to_dict())
