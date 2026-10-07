"""Decision endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS, AUTH_REQUIREMENTS

DECISION_ENDPOINTS = {
    "/api/v1/decisions": {
        "get": {
            "tags": ["Decisions"],
            "summary": "List decisions",
            "operationId": "listDecisions",
            "description": "List recent decision records (most recent first).",
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 20, "maximum": 200},
                }
            ],
            "responses": {
                "200": _ok_response("Decision list", "DecisionList"),
                "500": STANDARD_ERRORS["500"],
            },
        },
        "post": {
            "tags": ["Decisions"],
            "summary": "Create decision",
            "operationId": "createDecisions",
            "description": "Submit a decision request for debate, workflow, or gauntlet routing.",
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/DecisionRequest"}}
                },
            },
            "responses": {
                "200": _ok_response("Decision result", "DecisionResult"),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/decisions/{request_id}": {
        "get": {
            "tags": ["Decisions"],
            "summary": "Get decision",
            "operationId": "getDecision",
            "description": "Get a decision result by request ID.",
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "parameters": [
                {
                    "name": "request_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Decision result", "DecisionResult"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/decisions/{request_id}/status": {
        "get": {
            "tags": ["Decisions"],
            "summary": "Get decision status",
            "operationId": "getDecisionsStatu",
            "description": "Get decision status for polling.",
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "parameters": [
                {
                    "name": "request_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response("Decision status", "DecisionStatus"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/decisions/{request_id}/explain": {
        "get": {
            "tags": ["Decisions"],
            "summary": "Explain decision",
            "operationId": "explainDecision",
            "description": "Get a detailed explanation for a decision.",
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "parameters": [
                {
                    "name": "request_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Decision explanation",
                    {
                        "request_id": {"type": "string", "description": "Decision request ID"},
                        "summary": {
                            "type": "string",
                            "description": "Natural language explanation summary",
                        },
                        "factors": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Contributing factors to the decision",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score (0.0-1.0)",
                        },
                        "counterfactuals": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Alternative outcomes under different conditions",
                        },
                    },
                ),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}
