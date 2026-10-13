"""Pattern template endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS

PATTERN_ENDPOINTS = {
    "/api/patterns/{pattern_id}": {
        "get": {
            "tags": ["Patterns"],
            "summary": "Get pattern template",
            "operationId": "getPattern",
            "description": "Get a specific pattern template by ID.",
            "parameters": [
                {
                    "name": "pattern_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response("Pattern template details", "PatternTemplate"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
}
