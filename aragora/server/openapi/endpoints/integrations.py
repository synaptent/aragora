"""Integration management endpoint definitions."""

from typing import Any

from aragora.server.openapi.helpers import STANDARD_ERRORS


# Helper to build inline response
def _response(description: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a response with optional inline schema."""
    resp: dict[str, Any] = {"description": description}
    if schema:
        resp["content"] = {"application/json": {"schema": schema}}
    return resp


_INTEGRATION_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "type": {"type": "string"},
        "enabled": {"type": "boolean"},
        "created_at": {"type": "number"},
        "updated_at": {"type": "number"},
        "notify_on_consensus": {"type": "boolean"},
        "notify_on_debate_end": {"type": "boolean"},
        "notify_on_error": {"type": "boolean"},
        "notify_on_leaderboard": {"type": "boolean"},
        "settings": {"type": "object", "additionalProperties": True},
        "messages_sent": {"type": "integer"},
        "errors_24h": {"type": "integer"},
        "last_activity": {"type": ["number", "null"]},
        "last_error": {"type": ["string", "null"]},
        "user_id": {"type": ["string", "null"]},
        "workspace_id": {"type": ["string", "null"]},
    },
    "required": ["type", "enabled"],
}

_INTEGRATION_CONFIG_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"integration": _INTEGRATION_CONFIG_SCHEMA},
    "required": ["integration"],
}


INTEGRATION_ENDPOINTS = {
    "/api/v1/integrations/status": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration status",
            "description": "Get aggregated integration status for all providers.",
            "operationId": "getIntegrationsStatusV1",
            "responses": {
                "200": _response(
                    "Integration status",
                    {
                        "type": "object",
                        "properties": {
                            "integrations": {"type": "array", "items": {"type": "object"}},
                            "checked_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/integrations/{type}": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration configuration",
            "description": "Get configuration and status for a specific integration type.",
            "operationId": "getIntegrationV1",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _response(
                    "Integration details",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "status": {"type": "string"},
                            "config": {"type": "object"},
                            "connected_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "put": {
            "tags": ["Integrations"],
            "summary": "Configure integration",
            "description": "Create or replace an integration configuration by type.",
            "operationId": "configureIntegrationV1",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "config": {
                                    "type": "object",
                                    "description": "Integration configuration",
                                },
                                "enabled": {"type": "boolean", "description": "Enable integration"},
                                "credentials": {
                                    "type": "object",
                                    "description": "Authentication credentials",
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _response(
                    "Integration configuration updated",
                    _INTEGRATION_CONFIG_RESPONSE_SCHEMA,
                ),
                "201": _response(
                    "Integration configuration created",
                    _INTEGRATION_CONFIG_RESPONSE_SCHEMA,
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "patch": {
            "tags": ["Integrations"],
            "summary": "Update integration",
            "description": "Update an integration configuration by type.",
            "operationId": "updateIntegrationV1",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "config": {
                                    "type": "object",
                                    "description": "Updated configuration",
                                },
                                "enabled": {
                                    "type": "boolean",
                                    "description": "Enable/disable integration",
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _response(
                    "Integration updated",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "updated": {"type": "boolean"},
                            "message": {"type": "string"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Integrations"],
            "summary": "Delete integration",
            "description": "Delete an integration configuration by type.",
            "operationId": "deleteIntegrationV1",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _response(
                    "Integration deleted",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "deleted": {"type": "boolean"},
                            "message": {"type": "string"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/integrations/config/{integration_id}": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration config",
            "description": "Get configuration for a specific integration by ID.",
            "operationId": "getIntegrationConfigV1",
            "parameters": [
                {
                    "name": "integration_id",
                    "in": "path",
                    "required": True,
                    "description": "Integration ID",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _response(
                    "Integration config",
                    {
                        "type": "object",
                        "properties": {
                            "integration_id": {"type": "string"},
                            "type": {"type": "string"},
                            "config": {"type": "object"},
                            "enabled": {"type": "boolean"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "put": {
            "tags": ["Integrations"],
            "summary": "Update integration config",
            "description": "Replace the configuration for a specific integration by ID.",
            "operationId": "updateIntegrationConfigV1",
            "parameters": [
                {
                    "name": "integration_id",
                    "in": "path",
                    "required": True,
                    "description": "Integration ID",
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "config": {"type": "object", "description": "New configuration"},
                                "enabled": {
                                    "type": "boolean",
                                    "description": "Enable/disable integration",
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": _response(
                    "Integration config updated",
                    {
                        "type": "object",
                        "properties": {
                            "integration_id": {"type": "string"},
                            "updated": {"type": "boolean"},
                            "message": {"type": "string"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Integrations"],
            "summary": "Delete integration config",
            "description": "Delete the configuration for a specific integration by ID.",
            "operationId": "deleteIntegrationConfigV1",
            "parameters": [
                {
                    "name": "integration_id",
                    "in": "path",
                    "required": True,
                    "description": "Integration ID",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _response(
                    "Integration config deleted",
                    {
                        "type": "object",
                        "properties": {
                            "integration_id": {"type": "string"},
                            "deleted": {"type": "boolean"},
                            "message": {"type": "string"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v1/integrations/{type}/test": {
        "post": {
            "tags": ["Integrations"],
            "summary": "Test integration",
            "description": "Test a specific integration configuration.",
            "operationId": "testIntegrationV1",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _response(
                    "Test results",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "success": {"type": "boolean"},
                            "message": {"type": "string"},
                            "latency_ms": {"type": "number"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    # OAuth Wizard endpoints
    "/api/v2/integrations/wizard": {
        "get": {
            "tags": ["Integrations", "Wizard"],
            "summary": "Get wizard configuration",
            "description": "Get the complete OAuth wizard configuration including all providers, status, and setup guidance.",
            "operationId": "getWizardConfig",
            "responses": {
                "200": _response(
                    "Wizard configuration",
                    {
                        "type": "object",
                        "properties": {
                            "wizard": {"type": "object"},
                            "generated_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/wizard/providers": {
        "get": {
            "tags": ["Integrations", "Wizard"],
            "summary": "List available providers",
            "description": "List all available integration providers with optional filtering.",
            "operationId": "listWizardProviders",
            "parameters": [
                {
                    "name": "category",
                    "in": "query",
                    "description": "Filter by category",
                    "schema": {"type": "string", "enum": ["communication", "development"]},
                },
                {
                    "name": "configured",
                    "in": "query",
                    "description": "Filter by configuration status",
                    "schema": {"type": "boolean"},
                },
            ],
            "responses": {
                "200": _response(
                    "Provider list",
                    {
                        "type": "object",
                        "properties": {
                            "providers": {"type": "array", "items": {"type": "object"}},
                            "total": {"type": "integer"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/wizard/status": {
        "get": {
            "tags": ["Integrations", "Wizard"],
            "summary": "Get all integration statuses",
            "description": "Get detailed status of all integrations including configuration and connection status.",
            "operationId": "getWizardStatus",
            "responses": {
                "200": _response(
                    "Integration statuses",
                    {
                        "type": "object",
                        "properties": {
                            "statuses": {"type": "array", "items": {"type": "object"}},
                            "summary": {"type": "object"},
                            "checked_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/wizard/validate": {
        "post": {
            "tags": ["Integrations", "Wizard"],
            "summary": "Validate provider configuration",
            "description": "Validate configuration for a provider before connecting.",
            "operationId": "validateWizardConfig",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["provider"],
                            "properties": {
                                "provider": {"type": "string"},
                                "config": {"type": "object"},
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _response(
                    "Validation results",
                    {
                        "type": "object",
                        "properties": {
                            "provider": {"type": "string"},
                            "valid": {"type": "boolean"},
                            "checks": {"type": "array", "items": {"type": "object"}},
                            "recommendations": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    # Integration management endpoints
    "/api/v2/integrations": {
        "get": {
            "tags": ["Integrations"],
            "summary": "List all integrations",
            "description": "List all platform integrations (Slack, Teams, Discord, Email) for the current tenant.",
            "operationId": "listIntegrations",
            "parameters": [
                {
                    "name": "X-Tenant-ID",
                    "in": "header",
                    "description": "Tenant ID for multi-tenant deployments",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Maximum number of results (default: 20, max: 100)",
                    "schema": {"type": "integer", "default": 20, "maximum": 100},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "description": "Pagination offset",
                    "schema": {"type": "integer", "default": 0},
                },
                {
                    "name": "type",
                    "in": "query",
                    "description": "Filter by integration type",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "discord", "email"],
                    },
                },
                {
                    "name": "status",
                    "in": "query",
                    "description": "Filter by status",
                    "schema": {"type": "string", "enum": ["active", "inactive"]},
                },
            ],
            "responses": {
                "200": _response(
                    "List of integrations",
                    {
                        "type": "object",
                        "properties": {
                            "integrations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string"},
                                        "workspace_id": {"type": "string"},
                                        "workspace_name": {"type": "string"},
                                        "status": {"type": "string"},
                                        "installed_at": {"type": "number"},
                                    },
                                },
                            },
                            "pagination": {
                                "type": "object",
                                "properties": {
                                    "limit": {"type": "integer"},
                                    "offset": {"type": "integer"},
                                    "total": {"type": "integer"},
                                    "has_more": {"type": "boolean"},
                                },
                            },
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/{type}": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration status",
            "description": "Get the status and details of a specific integration type.",
            "operationId": "getIntegration",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "discord", "email"],
                    },
                },
                {
                    "name": "workspace_id",
                    "in": "query",
                    "description": "Specific workspace/tenant ID to query",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _response(
                    "Integration status",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "connected": {"type": "boolean"},
                            "workspaces": {"type": "array", "items": {"type": "object"}},
                            "health": {"type": "object"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Integrations"],
            "summary": "Disconnect integration",
            "description": "Disconnect/deactivate a specific integration workspace.",
            "operationId": "disconnectIntegration",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "discord", "email"],
                    },
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["workspace_id"],
                            "properties": {
                                "workspace_id": {
                                    "type": "string",
                                    "description": "Workspace/tenant ID to disconnect",
                                },
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _response(
                    "Integration disconnected",
                    {
                        "type": "object",
                        "properties": {
                            "disconnected": {"type": "boolean"},
                            "type": {"type": "string"},
                            "workspace_id": {"type": "string"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/{type}/health": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration health",
            "description": "Get detailed health status for an integration including connection status, token validity, and last successful operation.",
            "operationId": "getIntegrationHealth",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "discord", "email"],
                    },
                },
                {
                    "name": "workspace_id",
                    "in": "query",
                    "description": "Specific workspace/tenant ID to check (optional, returns aggregate if omitted)",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _response(
                    "Integration health status",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "healthy": {"type": "boolean"},
                            "status": {
                                "type": "string",
                                "enum": [
                                    "healthy",
                                    "degraded",
                                    "unhealthy",
                                    "not_configured",
                                    "token_expired",
                                    "error",
                                ],
                            },
                            "workspace_id": {"type": "string"},
                            "workspace_name": {"type": "string"},
                            "workspaces": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "workspace_id": {"type": "string"},
                                        "workspace_name": {"type": "string"},
                                        "status": {"type": "string"},
                                        "error": {"type": "string"},
                                    },
                                },
                            },
                            "error": {"type": "string"},
                        },
                        "required": ["type", "healthy"],
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/{type}/test": {
        "post": {
            "tags": ["Integrations"],
            "summary": "Test integration connectivity",
            "description": "Test the connectivity and health of a specific integration.",
            "operationId": "testIntegration",
            "parameters": [
                {
                    "name": "type",
                    "in": "path",
                    "required": True,
                    "description": "Integration type",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "discord", "email"],
                    },
                },
            ],
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "workspace_id": {
                                    "type": "string",
                                    "description": "Workspace/tenant ID to test",
                                },
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _response(
                    "Test result",
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "workspace_id": {"type": "string"},
                            "test_result": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "error": {"type": ["string", "null"]},
                                },
                            },
                            "tested_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/integrations/stats": {
        "get": {
            "tags": ["Integrations"],
            "summary": "Get integration statistics",
            "description": "Get aggregate statistics about all integrations.",
            "operationId": "getIntegrationStats",
            "responses": {
                "200": _response(
                    "Integration statistics",
                    {
                        "type": "object",
                        "properties": {
                            "stats": {
                                "type": "object",
                                "properties": {
                                    "slack": {
                                        "type": "object",
                                        "properties": {
                                            "total_workspaces": {"type": "integer"},
                                            "active_workspaces": {"type": "integer"},
                                        },
                                    },
                                    "teams": {
                                        "type": "object",
                                        "properties": {
                                            "total_workspaces": {"type": "integer"},
                                            "active_workspaces": {"type": "integer"},
                                        },
                                    },
                                    "total_integrations": {"type": "integer"},
                                },
                            },
                            "generated_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/receipts/{receipt_id}/send-to-channel": {
        "post": {
            "tags": ["Receipts", "Integrations"],
            "summary": "Send receipt to channel",
            "description": "Route a decision receipt to a specific channel (Slack, Teams, Email, Discord).",
            "operationId": "sendReceiptToChannel",
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "description": "Receipt ID",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["channel_type", "channel_id"],
                            "properties": {
                                "channel_type": {
                                    "type": "string",
                                    "enum": ["slack", "teams", "email", "discord"],
                                    "description": "Target channel type",
                                },
                                "channel_id": {
                                    "type": "string",
                                    "description": "Channel/conversation ID or email address",
                                },
                                "workspace_id": {
                                    "type": "string",
                                    "description": "Workspace/tenant ID (required for Slack/Teams)",
                                },
                                "options": {
                                    "type": "object",
                                    "properties": {
                                        "compact": {
                                            "type": "boolean",
                                            "default": False,
                                            "description": "Use compact formatting",
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _response(
                    "Receipt sent successfully",
                    {
                        "type": "object",
                        "properties": {
                            "sent": {"type": "boolean"},
                            "receipt_id": {"type": "string"},
                            "channel_type": {"type": "string"},
                            "channel_id": {"type": "string"},
                            "message_ts": {"type": "string"},
                            "message_id": {"type": "string"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
                "501": {
                    "description": "Channel not available",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
            },
        },
    },
    "/api/v1/receipts/{receipt_id}/deliver": {
        "post": {
            "tags": ["Receipts", "Integrations"],
            "summary": "Deliver receipt via legacy bridge",
            "description": "Legacy/frontend bridge that maps receipt delivery requests onto the v2 channel-delivery flow.",
            "operationId": "deliverReceiptLegacy",
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "description": "Receipt ID",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "channel_type": {
                                    "type": "string",
                                    "enum": ["slack", "teams", "email", "discord"],
                                },
                                "channel_id": {"type": "string"},
                                "channel": {"type": "string"},
                                "destination": {"type": "string"},
                                "workspace_id": {"type": "string"},
                                "message": {"type": "string"},
                                "options": {"type": "object"},
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _response(
                    "Receipt delivered successfully",
                    {
                        "type": "object",
                        "properties": {
                            "sent": {"type": "boolean"},
                            "receipt_id": {"type": "string"},
                            "channel_type": {"type": "string"},
                            "channel_id": {"type": "string"},
                            "message_ts": {"type": "string"},
                            "message_id": {"type": "string"},
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
                "501": {
                    "description": "Channel not available",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
            },
        },
    },
    "/api/v2/receipts/{receipt_id}/formatted/{channel_type}": {
        "get": {
            "tags": ["Receipts", "Integrations"],
            "summary": "Get formatted receipt",
            "description": "Get a receipt formatted for a specific channel type without sending it.",
            "operationId": "getFormattedReceipt",
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "description": "Receipt ID",
                    "schema": {"type": "string"},
                },
                {
                    "name": "channel_type",
                    "in": "path",
                    "required": True,
                    "description": "Channel type for formatting",
                    "schema": {
                        "type": "string",
                        "enum": ["slack", "teams", "email", "discord"],
                    },
                },
                {
                    "name": "compact",
                    "in": "query",
                    "description": "Use compact formatting",
                    "schema": {"type": "boolean", "default": False},
                },
            ],
            "responses": {
                "200": _response(
                    "Formatted receipt",
                    {
                        "type": "object",
                        "properties": {
                            "receipt_id": {"type": "string"},
                            "channel_type": {"type": "string"},
                            "formatted": {
                                "type": "object",
                                "description": "Channel-specific formatted content",
                            },
                        },
                    },
                ),
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    # OAuth Install/Callback endpoints for platform integrations
    "/api/integrations/slack/install": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Start Slack OAuth installation",
            "description": "Redirects to Slack OAuth authorization page to install the app in a workspace. Requires connectors.authorize permission.",
            "operationId": "installSlackIntegration",
            "parameters": [
                {
                    "name": "redirect_url",
                    "in": "query",
                    "description": "URL to redirect after OAuth completes",
                    "schema": {"type": "string", "format": "uri"},
                }
            ],
            "responses": {
                "302": {"description": "Redirect to Slack OAuth"},
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/slack/callback": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Handle Slack OAuth callback",
            "description": "Handles the OAuth callback from Slack after user authorization. Exchanges code for access token and stores workspace credentials.",
            "operationId": "slackOAuthCallback",
            "parameters": [
                {
                    "name": "code",
                    "in": "query",
                    "required": True,
                    "description": "OAuth authorization code from Slack",
                    "schema": {"type": "string"},
                },
                {
                    "name": "state",
                    "in": "query",
                    "required": True,
                    "description": "OAuth state parameter for CSRF protection",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "302": {"description": "Redirect to success page"},
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/slack/uninstall": {
        "post": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Handle Slack app uninstall webhook",
            "description": "Called by Slack when app is uninstalled from a workspace. Verified via Slack signature.",
            "operationId": "slackUninstallWebhook",
            "responses": {
                "200": _response(
                    "Uninstall acknowledged",
                    {
                        "type": "object",
                        "properties": {
                            "acknowledged": {"type": "boolean"},
                            "workspace_id": {"type": "string"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/slack/preview": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Preview Slack OAuth permissions",
            "description": "Returns a detailed preview of OAuth scopes and permissions that will be requested.",
            "operationId": "previewSlackOAuth",
            "responses": {
                "200": _response(
                    "OAuth scope preview",
                    {
                        "type": "object",
                        "properties": {
                            "scopes": {"type": "array", "items": {"type": "object"}},
                            "install_url": {"type": "string", "format": "uri"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/slack/workspaces": {
        "get": {
            "tags": ["Integrations"],
            "summary": "List connected Slack workspaces",
            "description": "Returns all Slack workspaces connected to the current organization.",
            "operationId": "listSlackWorkspaces",
            "responses": {
                "200": _response(
                    "List of connected workspaces",
                    {
                        "type": "object",
                        "properties": {
                            "workspaces": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "workspace_id": {"type": "string"},
                                        "workspace_name": {"type": "string"},
                                        "connected_at": {"type": "number"},
                                        "status": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    # Discord OAuth endpoints
    "/api/integrations/discord/install": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Start Discord OAuth installation",
            "description": "Redirects to Discord OAuth authorization page to add the bot to a server.",
            "operationId": "installDiscordIntegration",
            "responses": {
                "302": {"description": "Redirect to Discord OAuth"},
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/discord/callback": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Handle Discord OAuth callback",
            "description": "Handles the OAuth callback from Discord after user authorization.",
            "operationId": "discordOAuthCallback",
            "parameters": [
                {
                    "name": "code",
                    "in": "query",
                    "required": True,
                    "description": "OAuth authorization code",
                    "schema": {"type": "string"},
                },
                {
                    "name": "state",
                    "in": "query",
                    "required": True,
                    "description": "OAuth state parameter",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "302": {"description": "Redirect to success page"},
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/discord/uninstall": {
        "post": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Handle Discord bot removal",
            "description": "Called when bot is removed from a Discord server.",
            "operationId": "discordUninstallWebhook",
            "responses": {
                "200": _response(
                    "Uninstall acknowledged",
                    {
                        "type": "object",
                        "properties": {
                            "acknowledged": {"type": "boolean"},
                            "guild_id": {"type": "string"},
                        },
                    },
                ),
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    # Teams OAuth endpoints
    "/api/integrations/teams/install": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Start Microsoft Teams installation",
            "description": "Redirects to Microsoft OAuth authorization page to install the Teams app.",
            "operationId": "installTeamsIntegration",
            "responses": {
                "302": {"description": "Redirect to Microsoft OAuth"},
                "400": STANDARD_ERRORS["400"],
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/teams/callback": {
        "get": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Handle Teams OAuth callback",
            "description": "Handles the OAuth callback from Microsoft after user authorization.",
            "operationId": "teamsOAuthCallback",
            "parameters": [
                {
                    "name": "code",
                    "in": "query",
                    "required": True,
                    "description": "OAuth authorization code",
                    "schema": {"type": "string"},
                },
                {
                    "name": "state",
                    "in": "query",
                    "required": True,
                    "description": "OAuth state parameter",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "302": {"description": "Redirect to success page"},
                "400": STANDARD_ERRORS["400"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/integrations/teams/refresh": {
        "post": {
            "tags": ["Integrations", "OAuth"],
            "summary": "Refresh Teams OAuth token",
            "description": "Refresh the OAuth token for a Teams integration.",
            "operationId": "refreshTeamsToken",
            "responses": {
                "200": _response(
                    "Token refreshed",
                    {
                        "type": "object",
                        "properties": {
                            "refreshed": {"type": "boolean"},
                            "expires_at": {"type": "string", "format": "date-time"},
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
}
