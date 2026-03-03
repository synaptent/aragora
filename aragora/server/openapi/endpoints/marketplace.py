"""OpenAPI endpoint definitions for FastAPI v2 marketplace routes."""

from aragora.server.openapi.helpers import _ok_response, AUTH_REQUIREMENTS, STANDARD_ERRORS

_TEMPLATE_ID_PARAM = {
    "name": "template_id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Marketplace template ID.",
}

_CREATE_TEMPLATE_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "id": {"type": "string", "maxLength": 128},
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "description": {"type": "string", "maxLength": 2000},
                    "category": {"type": "string"},
                    "template_type": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "config": {"type": "object"},
                },
            }
        }
    },
}

MARKETPLACE_ENDPOINTS = {
    "/api/v2/marketplace/templates": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "List marketplace templates",
            "operationId": "listMarketplaceTemplatesV2",
            "description": (
                "List/search marketplace templates with optional filters "
                "(query, category, type, tags, pagination)."
            ),
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "parameters": [
                {
                    "name": "q",
                    "in": "query",
                    "description": "Search query.",
                    "schema": {"type": "string", "maxLength": 500},
                },
                {
                    "name": "category",
                    "in": "query",
                    "description": "Filter by category.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "type",
                    "in": "query",
                    "description": "Filter by template type.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "tags",
                    "in": "query",
                    "description": "Comma-separated tag list.",
                    "schema": {"type": "string", "maxLength": 1000},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum number of records.",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Pagination offset.",
                    "schema": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Marketplace templates.",
                    {
                        "templates": {"type": "array", "items": {"type": "object"}},
                        "count": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "post": {
            "tags": ["Marketplace"],
            "summary": "Create marketplace template",
            "operationId": "createMarketplaceTemplateV2",
            "description": "Create/import a marketplace template. Requires `marketplace:write`.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _CREATE_TEMPLATE_BODY,
            "responses": {
                "201": _ok_response(
                    "Template created.",
                    {
                        "id": {"type": "string"},
                        "success": {"type": "boolean"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/marketplace/categories": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "List marketplace categories",
            "operationId": "listMarketplaceCategoriesV2",
            "description": "List available marketplace categories.",
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "responses": {
                "200": _ok_response(
                    "Marketplace categories.",
                    {"categories": {"type": "array", "items": {"type": "string"}}},
                ),
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/marketplace/status": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "Get marketplace status",
            "operationId": "getMarketplaceStatusV2",
            "description": "Get marketplace health/circuit-breaker status.",
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "responses": {
                "200": _ok_response(
                    "Marketplace status.",
                    {
                        "status": {"type": "string"},
                        "circuit_breaker": {"type": "object"},
                    },
                ),
            },
        }
    },
    "/api/v2/marketplace/templates/import": {
        "post": {
            "tags": ["Marketplace"],
            "summary": "Import marketplace template",
            "operationId": "importMarketplaceTemplateV2",
            "description": "Import a marketplace template. Requires `marketplace:write`.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "requestBody": _CREATE_TEMPLATE_BODY,
            "responses": {
                "201": _ok_response(
                    "Template imported.",
                    {
                        "id": {"type": "string"},
                        "success": {"type": "boolean"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/marketplace/templates/{template_id}/ratings": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "Get template ratings",
            "operationId": "getMarketplaceTemplateRatingsV2",
            "description": "Get ratings and average score for a marketplace template.",
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "responses": {
                "200": _ok_response(
                    "Template ratings.",
                    {
                        "ratings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "user_id": {"type": "string"},
                                    "score": {"type": "integer"},
                                    "review": {"type": "string"},
                                    "created_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                        "average": {"type": "number"},
                        "count": {"type": "integer"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "post": {
            "tags": ["Marketplace"],
            "summary": "Rate template",
            "operationId": "rateMarketplaceTemplateV2",
            "description": "Add a template rating. Requires `marketplace:write`.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["score"],
                            "properties": {
                                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                                "review": {"type": "string", "maxLength": 2000},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _ok_response(
                    "Template rating saved.",
                    {"success": {"type": "boolean"}, "average_rating": {"type": "number"}},
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/marketplace/templates/{template_id}/export": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "Export template",
            "operationId": "exportMarketplaceTemplateV2",
            "description": "Export a marketplace template as JSON.",
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "responses": {
                "200": {
                    "description": "Template JSON export.",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/marketplace/templates/{template_id}": {
        "get": {
            "tags": ["Marketplace"],
            "summary": "Get template",
            "operationId": "getMarketplaceTemplateV2",
            "description": "Get template details by ID.",
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "responses": {
                "200": _ok_response(
                    "Template details.",
                    {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "category": {"type": "string"},
                        "template_type": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "downloads": {"type": "integer"},
                        "stars": {"type": "integer"},
                        "average_rating": {"type": "number"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Marketplace"],
            "summary": "Delete template",
            "operationId": "deleteMarketplaceTemplateV2",
            "description": "Delete a marketplace template. Requires `marketplace:delete`.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "responses": {
                "200": _ok_response(
                    "Template deleted.",
                    {
                        "success": {"type": "boolean"},
                        "deleted": {"type": "string"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/marketplace/templates/{template_id}/star": {
        "post": {
            "tags": ["Marketplace"],
            "summary": "Star template",
            "operationId": "starMarketplaceTemplateV2",
            "description": "Star a marketplace template. Requires `marketplace:write`.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [_TEMPLATE_ID_PARAM],
            "responses": {
                "200": _ok_response(
                    "Template starred.",
                    {"success": {"type": "boolean"}, "stars": {"type": "integer"}},
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}
