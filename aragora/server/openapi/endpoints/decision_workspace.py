"""Decision workspace endpoint definitions (``/api/v1/workspace``)."""

from typing import Any

from aragora.server.openapi.helpers import (
    AUTH_REQUIREMENTS,
    STANDARD_ERRORS,
    _error_response,
    _ok_response,
)

_TAGS = ["Decision Workspace"]
_SECURITY = AUTH_REQUIREMENTS["required"]["security"]
_ORG_NOTE = (
    " Requires a signed-in user with an organization (401 without a user, 403 "
    "`org_required` without an org). Another organization's decision answers "
    "exactly like a missing one (404)."
)

_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "error": {"type": "string"},
        "code": {"type": "string"},
        "field": {"type": "string", "nullable": True},
        "agent": {"type": "string"},
        "filename": {"type": "string"},
        "limit": {"type": "integer"},
    },
    "required": ["error", "code"],
}


def _error(status: str, description: str) -> dict[str, Any]:
    response = _error_response(status, description)
    response["content"] = {"application/json": {"schema": _ERROR_SCHEMA}}
    return response


DECISION_WORKSPACE_ENDPOINTS: dict[str, Any] = {
    "/api/v1/workspace/agent-options": {
        "get": {
            "tags": _TAGS,
            "summary": "List offered agents",
            "operationId": "getWorkspaceAgentOptions",
            "description": (
                "Agents a new decision can use (from `ARAGORA_WORKSPACE_AGENTS`), the "
                "intake limits and the accepted file types. With no agents configured, "
                "`configured` is false and `message` explains the missing configuration."
                + _ORG_NOTE
            ),
            "security": _SECURITY,
            "responses": {
                "200": _ok_response(
                    "Offered agents and intake limits",
                    {
                        "type": "object",
                        "properties": {
                            "configured": {"type": "boolean"},
                            "agents": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "spec": {"type": "string"},
                                        "provider": {"type": "string"},
                                        "model": {"type": "string", "nullable": True},
                                    },
                                },
                            },
                            "message": {"type": "string", "nullable": True},
                            "limits": {
                                "type": "object",
                                "properties": {
                                    "max_documents": {"type": "integer"},
                                    "max_file_bytes": {"type": "integer"},
                                    "max_pasted_chars": {"type": "integer"},
                                },
                            },
                            "accepted_extensions": {"type": "array", "items": {"type": "string"}},
                            "rounds": {
                                "type": "object",
                                "properties": {
                                    "min": {"type": "integer"},
                                    "max": {"type": "integer"},
                                    "default": {"type": "integer"},
                                },
                            },
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
            },
        }
    },
    "/api/v1/workspace/decisions": {
        "get": {
            "tags": _TAGS,
            "summary": "List workspace decisions",
            "operationId": "listWorkspaceDecisions",
            "description": "The caller's organization's decisions, newest first." + _ORG_NOTE,
            "security": _SECURITY,
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Page size (1-200).",
                    "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Number of decisions to skip.",
                    "schema": {"type": "integer", "default": 0, "minimum": 0},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Decision list",
                    {
                        "type": "object",
                        "properties": {
                            "decisions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "question": {"type": "string"},
                                        "status": {
                                            "type": "string",
                                            "enum": ["debating", "ready", "failed"],
                                        },
                                        "source_count": {"type": "integer"},
                                        "created_at": {"type": "string", "format": "date-time"},
                                        "updated_at": {"type": "string", "format": "date-time"},
                                    },
                                },
                            },
                            "total": {"type": "integer"},
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                ),
                "400": _error("400", "Invalid limit or offset"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
            },
        },
    },
}

__all__ = ["DECISION_WORKSPACE_ENDPOINTS"]
