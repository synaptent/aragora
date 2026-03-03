"""OpenAPI endpoint definitions for FastAPI v2 orchestration routes."""

from aragora.server.openapi.helpers import _ok_response, AUTH_REQUIREMENTS, STANDARD_ERRORS

_REQUEST_ID_PARAM = {
    "name": "request_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Deliberation request ID.",
}

_DELIBERATE_REQUEST = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 5000},
                    "knowledge_sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "id": {"type": "string"},
                                "lookback_minutes": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 10080,
                                },
                                "max_items": {"type": "integer", "minimum": 1, "maximum": 500},
                            },
                        },
                    },
                    "workspaces": {"type": "array", "items": {"type": "string"}},
                    "team_strategy": {"type": "string"},
                    "agents": {"type": "array", "items": {"type": "string"}},
                    "output_channels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "id": {"type": "string"},
                                "thread_id": {"type": "string"},
                            },
                        },
                    },
                    "output_format": {"type": "string"},
                    "require_consensus": {"type": "boolean"},
                    "priority": {"type": "string"},
                    "max_rounds": {"type": "integer", "minimum": 1, "maximum": 20},
                    "timeout_seconds": {"type": "number", "minimum": 10, "maximum": 3600},
                    "template": {"type": "string"},
                    "notify": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                    "metadata": {"type": "object"},
                },
            }
        }
    },
}

_ASYNC_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string"},
        "status": {"type": "string"},
        "message": {"type": "string"},
        "estimated_cost_usd": {"type": "number"},
    },
}

_DRY_RUN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string"},
        "dry_run": {"type": "boolean"},
        "estimated_cost": {"type": "object"},
        "agents": {"type": "array", "items": {"type": "string"}},
        "max_rounds": {"type": "integer"},
        "message": {"type": "string"},
    },
}

_RESULT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string"},
        "success": {"type": "boolean"},
        "consensus_reached": {"type": "boolean"},
        "final_answer": {"type": "string"},
        "confidence": {"type": "number"},
        "agents_participated": {"type": "array", "items": {"type": "string"}},
        "rounds_completed": {"type": "integer"},
        "duration_seconds": {"type": "number"},
        "knowledge_context_used": {"type": "array", "items": {"type": "string"}},
        "channels_notified": {"type": "array", "items": {"type": "string"}},
        "receipt_id": {"type": "string"},
        "error": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "estimated_cost_usd": {"type": "number"},
    },
}

ORCHESTRATION_ENDPOINTS = {
    "/api/v2/orchestration/deliberate": {
        "post": {
            "tags": ["Orchestration"],
            "summary": "Start asynchronous deliberation",
            "operationId": "startOrchestrationDeliberationV2",
            "description": (
                "Start an asynchronous orchestration deliberation. "
                "Requires `orchestration:execute`."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _DELIBERATE_REQUEST,
            "responses": {
                "202": {
                    "description": "Queued response, dry-run estimate, or immediate result.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "oneOf": [
                                    _ASYNC_RESPONSE_SCHEMA,
                                    _DRY_RUN_RESPONSE_SCHEMA,
                                    _RESULT_RESPONSE_SCHEMA,
                                ]
                            }
                        }
                    },
                },
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/orchestration/deliberate/sync": {
        "post": {
            "tags": ["Orchestration"],
            "summary": "Start synchronous deliberation",
            "operationId": "startOrchestrationDeliberationSyncV2",
            "description": (
                "Run a synchronous deliberation and return completion payload. "
                "Requires `orchestration:execute`."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _DELIBERATE_REQUEST,
            "responses": {
                "200": {
                    "description": "Synchronous result or dry-run estimate.",
                    "content": {
                        "application/json": {
                            "schema": {"oneOf": [_RESULT_RESPONSE_SCHEMA, _DRY_RUN_RESPONSE_SCHEMA]}
                        }
                    },
                },
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/orchestration/status/{request_id}": {
        "get": {
            "tags": ["Orchestration"],
            "summary": "Get deliberation status",
            "operationId": "getOrchestrationDeliberationStatusV2",
            "description": "Get orchestration deliberation status and optional result payload.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_REQUEST_ID_PARAM],
            "responses": {
                "200": _ok_response(
                    "Deliberation status.",
                    {
                        "request_id": {"type": "string"},
                        "status": {"type": "string"},
                        "result": _RESULT_RESPONSE_SCHEMA,
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/orchestration/templates": {
        "get": {
            "tags": ["Orchestration"],
            "summary": "List orchestration templates",
            "operationId": "listOrchestrationTemplatesV2",
            "description": "List orchestration templates with optional filters.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "category",
                    "in": "query",
                    "description": "Filter by template category.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "search",
                    "in": "query",
                    "description": "Search term for name/description.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "tags",
                    "in": "query",
                    "description": "Comma-separated tags.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum rows to return.",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Pagination offset.",
                    "schema": {"type": "integer", "minimum": 0, "default": 0},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Orchestration template list.",
                    {
                        "templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "default_agents": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "default_knowledge_sources": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "output_format": {"type": "string"},
                                    "consensus_threshold": {"type": "number"},
                                    "max_rounds": {"type": "integer"},
                                    "personas": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                        "count": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}
