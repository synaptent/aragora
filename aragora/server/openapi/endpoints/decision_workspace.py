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

_DECISION_ID = {
    "name": "decision_id",
    "in": "path",
    "required": True,
    "description": "Decision id (the id of its decision plan).",
    "schema": {"type": "string"},
}
_PASSAGE_ID = {
    "name": "passage_id",
    "in": "path",
    "required": True,
    "description": "Passage id from the decision's sources.",
    "schema": {"type": "string"},
}

_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "error": {"type": "string"},
        "code": {"type": "string"},
        "field": {"type": "string", "nullable": True},
        "agent": {"type": "string"},
        "filename": {"type": "string"},
        "limit": {"type": "integer"},
        "run_id": {"type": "string", "nullable": True},
    },
    "required": ["error", "code"],
}

_PASSAGE_SUMMARY: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passage_id": {"type": "string"},
        "label": {"type": "string", "description": "S<n>:P<m>"},
        "seq": {"type": "integer"},
        "heading": {"type": "string", "nullable": True},
        "char_count": {"type": "integer"},
        "sha256": {"type": "string", "description": "SHA-256 of the passage text"},
        "in_context": {"type": "boolean"},
    },
}

_SOURCE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "label": {"type": "string", "description": "S1, S2, ... in intake order"},
        "kind": {"type": "string", "enum": ["upload", "pasted"]},
        "filename": {"type": "string", "nullable": True},
        "document_id": {"type": "string", "nullable": True},
        "content_sha256": {"type": "string"},
        "char_count": {"type": "integer"},
        "passage_count": {"type": "integer"},
        "created_at": {"type": "string", "format": "date-time"},
        "passages": {"type": "array", "items": _PASSAGE_SUMMARY},
    },
}

_DECISION_PROPERTIES: dict[str, Any] = {
    "id": {"type": "string"},
    "question": {"type": "string"},
    "status": {"type": "string", "enum": ["debating", "ready", "failed"]},
    "agents": {"type": "array", "items": {"type": "string"}},
    "rounds": {"type": "integer"},
    "created_by": {"type": "string", "nullable": True},
    "created_at": {"type": "string", "format": "date-time"},
    "updated_at": {"type": "string", "format": "date-time"},
    "current_revision_id": {"type": "string", "nullable": True},
    "budget_usd": {"type": "number", "nullable": True},
    "cost_actual_usd": {"type": "number"},
    "cost_estimated_usd": {"type": "number"},
    "source_count": {"type": "integer"},
    "passage_count": {"type": "integer"},
    "omitted_passage_count": {
        "type": "integer",
        "description": "Passages left out of the debate context by the context budget.",
    },
}

_RUN_STATUS = {
    "type": "string",
    "enum": ["running", "completed", "failed", "interrupted", "budget_exceeded"],
}

_RUN_PROPERTIES: dict[str, Any] = {
    "run_id": {"type": "string"},
    "status": _RUN_STATUS,
    "debate_id": {"type": "string", "nullable": True},
    "agents": {"type": "array", "items": {"type": "string"}},
    "rounds": {"type": "integer"},
    "started_by": {"type": "string", "nullable": True},
    "started_at": {"type": "string", "format": "date-time"},
    "finished_at": {"type": "string", "format": "date-time", "nullable": True},
    "error": {"type": "string", "nullable": True},
    "budget_usd": {"type": "number", "nullable": True},
    "cost_actual_usd": {
        "type": "number",
        "description": "Cost reported by providers billed directly (for example grok).",
    },
    "cost_estimated_usd": {
        "type": "number",
        "description": "Cost estimated from token counts for agents routed through a proxy.",
    },
}

_RUN_SUMMARY: dict[str, Any] = {"type": "object", "properties": _RUN_PROPERTIES}

_LATEST_RUN: dict[str, Any] = {
    "type": "object",
    "nullable": True,
    "properties": {
        **_RUN_PROPERTIES,
        "result": {
            "type": "object",
            "nullable": True,
            "description": (
                "What the run captured, kept when it fails: context counts, the debate "
                "record (final answer, proposals, dissenting views, cruxes, evidence "
                "suggestions, transcript), per-agent costs and the synthesis attempts."
            ),
        },
    },
}

_CHECKED_CITATION: dict[str, Any] = {
    "type": "object",
    "description": (
        "Mechanical checks only: whether the passage exists and whether the quote "
        "appears in it. Neither says the passage supports the claim."
    ),
    "properties": {
        "claim": {"type": "string"},
        "passage_label": {"type": "string"},
        "quote": {"type": "string", "nullable": True},
        "passage_id": {"type": "string", "nullable": True},
        "passage_exists": {"type": "boolean"},
        "quote_provided": {"type": "boolean"},
        "quote_found": {"type": "boolean"},
    },
}

_CITATIONS = {"type": "array", "items": _CHECKED_CITATION}

_REVISION: dict[str, Any] = {
    "type": "object",
    "nullable": True,
    "properties": {
        "revision_id": {"type": "string"},
        "number": {"type": "integer"},
        "parent_revision_id": {"type": "string", "nullable": True},
        "status": {"type": "string", "enum": ["draft", "current", "superseded"]},
        "origin": {"type": "string", "enum": ["debate", "user_edit"]},
        "author_id": {"type": "string", "nullable": True},
        "content": {
            "type": "object",
            "properties": {
                "recommendation": {"type": "string"},
                "citations": _CITATIONS,
                "alternatives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "why_not_chosen": {"type": "string"},
                            "citations": _CITATIONS,
                        },
                    },
                },
                "dissent": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {"type": "string", "nullable": True},
                            "position": {"type": "string"},
                            "citations": _CITATIONS,
                        },
                    },
                },
                "missing_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                        },
                    },
                },
                "assumptions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "basis": {"type": "string"},
                        },
                    },
                },
            },
        },
        "content_hash": {
            "type": "string",
            "description": (
                "SHA-256 of the RFC 8785 (JCS) canonical JSON of the decision id, "
                "revision number, parent revision id and `content`"
            ),
        },
        "created_at": {"type": "string", "format": "date-time"},
    },
}

_DETAIL_PROPERTIES: dict[str, Any] = {
    **_DECISION_PROPERTIES,
    "run": _LATEST_RUN,
    "runs": {
        "type": "array",
        "items": _RUN_SUMMARY,
        "description": "Every run of the decision, newest first.",
    },
    "current_revision": _REVISION,
}

_DECISION: dict[str, Any] = {"type": "object", "properties": _DETAIL_PROPERTIES}

_CREATED_DECISION: dict[str, Any] = {
    "type": "object",
    "properties": {
        **_DETAIL_PROPERTIES,
        "decision_id": {"type": "string"},
        "sources": {"type": "array", "items": _SOURCE},
    },
}

_INTAKE_FIELDS: dict[str, Any] = {
    "question": {"type": "string", "description": "The question to decide (required)."},
    "pasted_text": {
        "type": "string",
        "description": "Optional pasted evidence (source kind `pasted`).",
    },
    "rounds": {"type": "integer", "minimum": 1, "maximum": 2, "default": 1},
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
        "post": {
            "tags": _TAGS,
            "summary": "Start a workspace decision",
            "operationId": "createWorkspaceDecision",
            "description": (
                "Create a decision from a question, optional pasted text and up to "
                "`ARAGORA_WORKSPACE_MAX_DOCUMENTS` `.md`/`.txt` files, debated by the "
                "selected offered agents. Sources are labelled S1, S2, ... in intake "
                "order and split into passages S1:P1, ... with SHA-256 hashes. Any "
                "refused field answers 400/413/415 naming the field and creates nothing. "
                "Returns 202 with status `debating` and the started run; when the debate "
                "cannot be started the run and the decision are already `failed` with the "
                "reason, and the decision can be rerun. JSON bodies are accepted for "
                "decisions without files." + _ORG_NOTE
            ),
            "security": _SECURITY,
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                **_INTAKE_FIELDS,
                                "agents[]": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Offered agent specs (at least one).",
                                },
                                "files[]": {
                                    "type": "array",
                                    "items": {"type": "string", "format": "binary"},
                                    "description": "`.md` or `.txt` files.",
                                },
                            },
                            "required": ["question", "agents[]"],
                        }
                    },
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                **_INTAKE_FIELDS,
                                "agents": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["question", "agents"],
                        }
                    },
                },
            },
            "responses": {
                "202": _ok_response("Decision created; the debate is starting", _CREATED_DECISION),
                "400": _error("400", "A field was refused (see `field` and `code`)"),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "411": _error("411", "Content-Length is required"),
                "413": _error("413", "A file, the pasted text or the request is too large"),
                "415": _error("415", "Unsupported request content type"),
                "503": _error("503", "File uploads are unavailable"),
            },
        },
    },
    "/api/v1/workspace/decisions/{decision_id}": {
        "get": {
            "tags": _TAGS,
            "summary": "Get a workspace decision",
            "operationId": "getWorkspaceDecision",
            "description": (
                "One decision with its status, agents and counts, its runs (the latest "
                "with what it captured, kept when it fails) and the current revision "
                "with the structured result and its citation checks." + _ORG_NOTE
            ),
            "security": _SECURITY,
            "parameters": [_DECISION_ID],
            "responses": {
                "200": _ok_response("Decision", _DECISION),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
            },
        }
    },
    "/api/v1/workspace/decisions/{decision_id}/rerun": {
        "post": {
            "tags": _TAGS,
            "summary": "Rerun a failed decision",
            "operationId": "rerunWorkspaceDecision",
            "description": (
                "Start a new run of a `failed` decision with the same agents and rounds; "
                "earlier runs are kept. Returns 202 with the decision back in `debating`. "
                "A decision that is not `failed`, or already has a run in progress, "
                "answers 409, so a double submit starts only one run. Needs "
                "`decisions:update`." + _ORG_NOTE
            ),
            "security": _SECURITY,
            "parameters": [_DECISION_ID],
            "responses": {
                "202": _ok_response("Rerun started", _DECISION),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "409": _error(
                    "409",
                    "`run_in_progress` (with `run_id`) or `decision_not_failed`",
                ),
            },
        }
    },
    "/api/v1/workspace/decisions/{decision_id}/sources": {
        "get": {
            "tags": _TAGS,
            "summary": "List a decision's sources",
            "operationId": "listWorkspaceDecisionSources",
            "description": (
                "The decision's sources in intake order with their passage counts and "
                "passage summaries (labels, headings, hashes)." + _ORG_NOTE
            ),
            "security": _SECURITY,
            "parameters": [_DECISION_ID],
            "responses": {
                "200": _ok_response(
                    "Sources",
                    {
                        "type": "object",
                        "properties": {
                            "decision_id": {"type": "string"},
                            "sources": {"type": "array", "items": _SOURCE},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
            },
        }
    },
    "/api/v1/workspace/decisions/{decision_id}/passages/{passage_id}": {
        "get": {
            "tags": _TAGS,
            "summary": "Get a passage",
            "operationId": "getWorkspaceDecisionPassage",
            "description": (
                "The exact text of one passage, its label, heading, offsets in the "
                "source and SHA-256. A passage of another decision answers 404." + _ORG_NOTE
            ),
            "security": _SECURITY,
            "parameters": [_DECISION_ID, _PASSAGE_ID],
            "responses": {
                "200": _ok_response(
                    "Passage",
                    {
                        "type": "object",
                        "properties": {
                            "passage_id": {"type": "string"},
                            "decision_id": {"type": "string"},
                            "source_id": {"type": "string"},
                            "source_label": {"type": "string"},
                            "label": {"type": "string"},
                            "seq": {"type": "integer"},
                            "heading": {"type": "string", "nullable": True},
                            "start_char": {"type": "integer"},
                            "end_char": {"type": "integer"},
                            "text": {"type": "string"},
                            "sha256": {"type": "string"},
                            "in_context": {"type": "boolean"},
                            "created_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
            },
        }
    },
}

__all__ = ["DECISION_WORKSPACE_ENDPOINTS"]
