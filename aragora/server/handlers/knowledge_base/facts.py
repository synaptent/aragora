"""
Facts Operations Mixin for Knowledge Handler.

Provides fact CRUD operations:
- List facts with filtering
- Get specific fact
- Create/update/delete facts
- Add relations between facts
- Get contradictions
- Verify facts with agents
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.knowledge import (
    FactFilters,
    FactRelationType,
    ValidationStatus,
)
from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    get_bool_param,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    handle_errors,
    json_response,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint

if TYPE_CHECKING:
    from aragora.knowledge import DatasetQueryEngine, FactStore, SimpleQueryEngine

logger = logging.getLogger(__name__)

# Cache TTLs
CACHE_TTL_FACTS = 60  # 1 minute for fact listings

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "statement": {"type": "string"},
        "confidence": {"type": "number"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "workspace_id": {"type": "string"},
        "validation_status": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
    "additionalProperties": True,
}

RELATION_SCHEMA = {
    "type": "object",
    "properties": {
        "relation_type": {"type": "string"},
        "source_fact_id": {"type": "string"},
        "target_fact_id": {"type": "string"},
    },
    "additionalProperties": True,
}


class FactsHandlerProtocol(Protocol):
    """Protocol for handlers that use FactsOperationsMixin."""

    def _get_fact_store(self) -> FactStore: ...
    def _get_query_engine(self) -> DatasetQueryEngine | SimpleQueryEngine: ...
    def require_auth_or_error(self, handler: Any) -> tuple[Any, HandlerResult | None]: ...


class FactsOperationsMixin:
    """Mixin providing fact CRUD operations for KnowledgeHandler."""

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/facts",
        summary="List facts with filtering",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "workspace_id",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Filter by workspace ID",
            },
            {
                "name": "topic",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Filter by topic",
            },
            {
                "name": "min_confidence",
                "in": "query",
                "schema": {"type": "number", "default": 0.0},
                "description": "Minimum confidence threshold (0.0-1.0)",
            },
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Filter by validation status",
            },
            {
                "name": "include_superseded",
                "in": "query",
                "schema": {"type": "boolean", "default": False},
                "description": "Include superseded facts",
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 50},
                "description": "Maximum number of facts to return (1-200)",
            },
            {
                "name": "offset",
                "in": "query",
                "schema": {"type": "integer", "default": 0},
                "description": "Offset for pagination",
            },
        ],
        responses={
            "200": {
                "description": "List of facts matching the filters",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "facts": {"type": "array", "items": FACT_SCHEMA},
                                "total": {"type": "integer"},
                                "limit": {"type": "integer"},
                                "offset": {"type": "integer"},
                            },
                        }
                    }
                },
            },
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "429": {"description": "Rate limit exceeded"},
        },
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_FACTS, key_prefix="knowledge_facts", skip_first=True)
    @handle_errors("list facts")
    @require_permission("knowledge:read")
    def _handle_list_facts(
        self: FactsHandlerProtocol, query_params: dict, handler: Any = None
    ) -> HandlerResult:
        """Handle GET /api/knowledge/facts - List facts.

        ``handler`` is unused here; ``@require_permission`` reads the request's
        authorization context from it.
        """
        workspace_id = get_bounded_string_param(query_params, "workspace_id", None, max_length=100)
        topic = get_bounded_string_param(query_params, "topic", None, max_length=200)
        min_confidence = get_bounded_float_param(
            query_params, "min_confidence", 0.0, min_val=0.0, max_val=1.0
        )
        status = get_bounded_string_param(query_params, "status", None, max_length=50)
        include_superseded = get_bool_param(query_params, "include_superseded", False)
        limit = get_clamped_int_param(query_params, "limit", 50, min_val=1, max_val=200)
        offset = get_clamped_int_param(query_params, "offset", 0, min_val=0, max_val=10000)

        filters = FactFilters(
            workspace_id=workspace_id,
            topics=[topic] if topic else None,
            min_confidence=min_confidence,
            validation_status=ValidationStatus(status) if status else None,
            include_superseded=include_superseded,
            limit=limit,
            offset=offset,
        )

        store = self._get_fact_store()
        facts = store.list_facts(filters)

        return json_response(
            {
                "facts": [f.to_dict() for f in facts],
                "total": len(facts),
                "limit": limit,
                "offset": offset,
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/facts/{fact_id}",
        summary="Get a specific fact by ID",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID",
            },
        ],
        responses={
            "200": {
                "description": "Fact details",
                "content": {"application/json": {"schema": FACT_SCHEMA}},
            },
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
        },
    )
    @handle_errors("get fact")
    def _handle_get_fact(self: FactsHandlerProtocol, fact_id: str) -> HandlerResult:
        """Handle GET /api/knowledge/facts/:id - Get specific fact."""
        store = self._get_fact_store()
        fact = store.get_fact(fact_id)

        if not fact:
            return error_response(f"Fact not found: {fact_id}", 404)

        return json_response(fact.to_dict())

    @api_endpoint(
        method="POST",
        path="/api/v1/knowledge/facts",
        summary="Create a new fact",
        tags=["Knowledge Base"],
        request_body={
            "description": "Fact creation payload",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["statement"],
                        "properties": {
                            "statement": {"type": "string", "description": "The fact statement"},
                            "workspace_id": {"type": "string", "default": "default"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "source_documents": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "default": 0.5},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "metadata": {"type": "object"},
                        },
                    }
                }
            },
        },
        responses={
            "201": {
                "description": "Fact created successfully",
                "content": {"application/json": {"schema": FACT_SCHEMA}},
            },
            "400": {"description": "Invalid request body or missing statement"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
        },
    )
    @handle_errors("create fact")
    def _handle_create_fact(self: FactsHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/facts - Create new fact."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                return error_response("Request body required", 400)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        statement = data.get("statement", "")
        if not statement or not statement.strip():
            return error_response("Statement is required", 400)

        workspace_id = data.get("workspace_id", "default")

        store = self._get_fact_store()
        fact = store.add_fact(
            statement=statement,
            workspace_id=workspace_id,
            evidence_ids=data.get("evidence_ids", []),
            source_documents=data.get("source_documents", []),
            confidence=data.get("confidence", 0.5),
            topics=data.get("topics", []),
            metadata=data.get("metadata", {}),
        )

        return json_response(fact.to_dict(), status=201)

    @api_endpoint(
        method="PUT",
        path="/api/v1/knowledge/facts/{fact_id}",
        summary="Update an existing fact",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID to update",
            },
        ],
        request_body={
            "description": "Fields to update on the fact",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "confidence": {"type": "number"},
                            "validation_status": {"type": "string"},
                            "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "metadata": {"type": "object"},
                            "superseded_by": {"type": "string"},
                        },
                    }
                }
            },
        },
        responses={
            "200": {
                "description": "Fact updated successfully",
                "content": {"application/json": {"schema": FACT_SCHEMA}},
            },
            "400": {"description": "Invalid request body"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
        },
    )
    @handle_errors("update fact")
    def _handle_update_fact(
        self: FactsHandlerProtocol, fact_id: str, handler: Any
    ) -> HandlerResult:
        """Handle PUT /api/knowledge/facts/:id - Update fact."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                return error_response("Request body required", 400)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        store = self._get_fact_store()

        kwargs = {}
        if "confidence" in data:
            kwargs["confidence"] = data["confidence"]
        if "validation_status" in data:
            kwargs["validation_status"] = ValidationStatus(data["validation_status"])
        if "evidence_ids" in data:
            kwargs["evidence_ids"] = data["evidence_ids"]
        if "topics" in data:
            kwargs["topics"] = data["topics"]
        if "metadata" in data:
            kwargs["metadata"] = data["metadata"]
        if "superseded_by" in data:
            kwargs["superseded_by"] = data["superseded_by"]

        updated = store.update_fact(fact_id, **kwargs)

        if not updated:
            return error_response(f"Fact not found: {fact_id}", 404)

        return json_response(updated.to_dict())

    @api_endpoint(
        method="DELETE",
        path="/api/v1/knowledge/facts/{fact_id}",
        summary="Delete a fact",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID to delete",
            },
        ],
        responses={
            "200": {"description": "Fact deleted successfully"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
        },
    )
    @handle_errors("delete fact")
    def _handle_delete_fact(
        self: FactsHandlerProtocol, fact_id: str, handler: Any
    ) -> HandlerResult:
        """Handle DELETE /api/knowledge/facts/:id - Delete fact."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        store = self._get_fact_store()
        deleted = store.delete_fact(fact_id)

        if not deleted:
            return error_response(f"Fact not found: {fact_id}", 404)

        return json_response({"deleted": True, "fact_id": fact_id})

    @api_endpoint(
        method="POST",
        path="/api/v1/knowledge/facts/{fact_id}/verify",
        summary="Verify a fact using AI agents",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID to verify",
            },
        ],
        responses={
            "200": {"description": "Verification result or queued status"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
            "500": {"description": "Verification failed"},
        },
    )
    @handle_errors("verify fact")
    def _handle_verify_fact(
        self: FactsHandlerProtocol, fact_id: str, handler: Any
    ) -> HandlerResult:
        """Handle POST /api/knowledge/facts/:id/verify - Verify fact."""
        from aragora.knowledge import DatasetQueryEngine
        from aragora.server.http_utils import run_async as _run_async

        store = self._get_fact_store()
        fact = store.get_fact(fact_id)

        if not fact:
            return error_response(f"Fact not found: {fact_id}", 404)

        engine = self._get_query_engine()

        if not isinstance(engine, DatasetQueryEngine):
            store.update_fact(
                fact_id,
                metadata={
                    **fact.metadata,
                    "_pending_verification": True,
                    "_verification_queued_at": __import__("time").time(),
                },
            )
            return json_response(
                {
                    "fact_id": fact_id,
                    "verified": None,
                    "status": "queued",
                    "message": "Agent verification not currently available. Fact queued for verification when capability becomes available.",
                }
            )

        try:
            verified = _run_async(engine.verify_fact(fact_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Verification failed: %s", e)
            return error_response("Verification failed", 500)

        return json_response(verified.to_dict())

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/facts/{fact_id}/contradictions",
        summary="Get contradicting facts for a given fact",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID to check for contradictions",
            },
        ],
        responses={
            "200": {
                "description": "List of contradicting facts",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "fact_id": {"type": "string"},
                                "contradictions": {
                                    "type": "array",
                                    "items": FACT_SCHEMA,
                                },
                                "count": {"type": "integer"},
                            },
                        }
                    }
                },
            },
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
        },
    )
    @handle_errors("get contradictions")
    def _handle_get_contradictions(self: FactsHandlerProtocol, fact_id: str) -> HandlerResult:
        """Handle GET /api/knowledge/facts/:id/contradictions."""
        store = self._get_fact_store()

        fact = store.get_fact(fact_id)
        if not fact:
            return error_response(f"Fact not found: {fact_id}", 404)

        contradictions = store.get_contradictions(fact_id)

        return json_response(
            {
                "fact_id": fact_id,
                "contradictions": [c.to_dict() for c in contradictions],
                "count": len(contradictions),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/knowledge/facts/{fact_id}/relations",
        summary="Get relations for a given fact",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The fact ID",
            },
            {
                "name": "type",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Filter by relation type",
            },
            {
                "name": "as_source",
                "in": "query",
                "schema": {"type": "boolean", "default": True},
                "description": "Include relations where this fact is the source",
            },
            {
                "name": "as_target",
                "in": "query",
                "schema": {"type": "boolean", "default": True},
                "description": "Include relations where this fact is the target",
            },
        ],
        responses={
            "200": {
                "description": "List of fact relations",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "fact_id": {"type": "string"},
                                "relations": {"type": "array", "items": RELATION_SCHEMA},
                                "count": {"type": "integer"},
                            },
                        }
                    }
                },
            },
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Fact not found"},
        },
    )
    @handle_errors("get relations")
    def _handle_get_relations(
        self: FactsHandlerProtocol, fact_id: str, query_params: dict
    ) -> HandlerResult:
        """Handle GET /api/knowledge/facts/:id/relations."""
        store = self._get_fact_store()

        fact = store.get_fact(fact_id)
        if not fact:
            return error_response(f"Fact not found: {fact_id}", 404)

        relation_type_str = get_bounded_string_param(query_params, "type", None, max_length=50)
        relation_type = FactRelationType(relation_type_str) if relation_type_str else None

        as_source = get_bool_param(query_params, "as_source", True)
        as_target = get_bool_param(query_params, "as_target", True)

        relations = store.get_relations(
            fact_id,
            relation_type=relation_type,
            as_source=as_source,
            as_target=as_target,
        )

        return json_response(
            {
                "fact_id": fact_id,
                "relations": [r.to_dict() for r in relations],
                "count": len(relations),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/knowledge/facts/{fact_id}/relations",
        summary="Add a relation from a specific fact to another",
        tags=["Knowledge Base"],
        parameters=[
            {
                "name": "fact_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The source fact ID",
            },
        ],
        request_body={
            "description": "Relation details",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["target_fact_id", "relation_type"],
                        "properties": {
                            "target_fact_id": {
                                "type": "string",
                                "description": "The target fact ID",
                            },
                            "relation_type": {"type": "string", "description": "Type of relation"},
                            "confidence": {"type": "number", "default": 0.5},
                            "created_by": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    }
                }
            },
        },
        responses={
            "201": {"description": "Relation created successfully"},
            "400": {"description": "Invalid request body or missing required fields"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
            "404": {"description": "Source or target fact not found"},
        },
    )
    @handle_errors("add relation")
    def _handle_add_relation(
        self: FactsHandlerProtocol, fact_id: str, handler: Any
    ) -> HandlerResult:
        """Handle POST /api/knowledge/facts/:id/relations - Add relation from fact."""
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                return error_response("Request body required", 400)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        target_fact_id = data.get("target_fact_id")
        if not target_fact_id:
            return error_response("target_fact_id is required", 400)

        relation_type_str = data.get("relation_type")
        if not relation_type_str:
            return error_response("relation_type is required", 400)

        try:
            relation_type = FactRelationType(relation_type_str)
        except ValueError:
            return error_response(f"Invalid relation_type: {relation_type_str}", 400)

        store = self._get_fact_store()

        if not store.get_fact(fact_id):
            return error_response(f"Source fact not found: {fact_id}", 404)
        if not store.get_fact(target_fact_id):
            return error_response(f"Target fact not found: {target_fact_id}", 404)

        relation = store.add_relation(
            source_fact_id=fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            confidence=data.get("confidence", 0.5),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata"),
        )

        return json_response(relation.to_dict(), status=201)

    @api_endpoint(
        method="POST",
        path="/api/v1/knowledge/facts/relations",
        summary="Add a relation between two facts",
        tags=["Knowledge Base"],
        request_body={
            "description": "Relation details with source and target fact IDs",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["source_fact_id", "target_fact_id", "relation_type"],
                        "properties": {
                            "source_fact_id": {
                                "type": "string",
                                "description": "The source fact ID",
                            },
                            "target_fact_id": {
                                "type": "string",
                                "description": "The target fact ID",
                            },
                            "relation_type": {"type": "string", "description": "Type of relation"},
                            "confidence": {"type": "number", "default": 0.5},
                            "created_by": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    }
                }
            },
        },
        responses={
            "201": {"description": "Relation created successfully"},
            "400": {"description": "Invalid request body or missing required fields"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
        },
    )
    @handle_errors("add relation bulk")
    def _handle_add_relation_bulk(self: FactsHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/facts/relations - Add relation between facts."""
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                return error_response("Request body required", 400)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        source_fact_id = data.get("source_fact_id")
        target_fact_id = data.get("target_fact_id")
        relation_type_str = data.get("relation_type")

        if not source_fact_id:
            return error_response("source_fact_id is required", 400)
        if not target_fact_id:
            return error_response("target_fact_id is required", 400)
        if not relation_type_str:
            return error_response("relation_type is required", 400)

        try:
            relation_type = FactRelationType(relation_type_str)
        except ValueError:
            return error_response(f"Invalid relation_type: {relation_type_str}", 400)

        store = self._get_fact_store()

        relation = store.add_relation(
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            confidence=data.get("confidence", 0.5),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata"),
        )

        return json_response(relation.to_dict(), status=201)
