"""Response schema definitions for endpoints missing them.

This module adds proper response schemas to endpoints whose schemas were
either missing or lost during the OpenAPI generation pipeline (e.g. due to
_filter_unhandled_paths stripping unversioned /api/ paths before
_autogenerate_missing_paths re-adds them without schemas).

These definitions use /api/v1/ versioned paths to survive the pipeline.
"""

from typing import Any

from aragora.server.openapi.helpers import (
    AUTH_REQUIREMENTS,
    STANDARD_ERRORS,
    STANDARD_RESPONSE_HEADERS,
    _ok_response,
)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
_DASHBOARD_ENDPOINTS = {
    "/api/v1/dashboard/overview": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Dashboard overview",
            "operationId": "getDashboardOverview",
            "description": "Get dashboard overview with key metrics.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Dashboard overview data",
                    {
                        "total_debates": {"type": "integer", "description": "Total debates"},
                        "active_debates": {"type": "integer", "description": "Active debates"},
                        "completed_debates": {
                            "type": "integer",
                            "description": "Completed debates",
                        },
                        "total_agents": {"type": "integer", "description": "Total agents"},
                        "recent_activity": {"type": "array", "items": {"type": "object"}},
                        "health_status": {
                            "type": "string",
                            "enum": ["healthy", "degraded", "unhealthy"],
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/stats": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Dashboard stats",
            "operationId": "getDashboardStats",
            "description": "Get dashboard statistics.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Dashboard statistics",
                    {
                        "debates_today": {"type": "integer"},
                        "debates_this_week": {"type": "integer"},
                        "average_duration_ms": {"type": "number"},
                        "consensus_rate": {"type": "number"},
                        "agent_utilization": {"type": "number"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/activity": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Recent activity",
            "operationId": "getDashboardActivity",
            "description": "Get recent activity feed.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Activity feed",
                    {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "timestamp": {"type": "string", "format": "date-time"},
                                    "actor": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/debates/{debate_id}": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Dashboard debate detail",
            "operationId": "getDashboardDebate",
            "description": "Get debate details for dashboard view.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "debate_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Debate details",
                    {
                        "id": {"type": "string"},
                        "task": {"type": "string"},
                        "status": {"type": "string"},
                        "rounds": {"type": "integer"},
                        "agents": {"type": "array", "items": {"type": "string"}},
                        "created_at": {"type": "string", "format": "date-time"},
                        "consensus": {"type": "object"},
                        "summary": {"type": "string"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/inbox-summary": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Inbox summary",
            "operationId": "getDashboardInboxSummary",
            "description": "Get inbox summary for dashboard.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Inbox summary",
                    {
                        "unread_count": {"type": "integer"},
                        "priority_count": {"type": "integer"},
                        "recent_items": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/labels": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Dashboard labels",
            "operationId": "getDashboardLabels",
            "description": "Get labels used in dashboard.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Labels list",
                    {
                        "labels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "color": {"type": "string"},
                                    "count": {"type": "integer"},
                                },
                            },
                        }
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/pending-actions": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Pending actions",
            "operationId": "getDashboardPendingActions",
            "description": "Get pending actions for the current user.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Pending actions",
                    {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "priority": {"type": "string"},
                                    "created_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/pending-actions/{action_id}/complete": {
        "post": {
            "tags": ["Dashboard"],
            "summary": "Complete pending action",
            "operationId": "completeDashboardPendingAction",
            "description": "Mark a pending action as complete.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "action_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Action completed",
                    {
                        "action_id": {"type": "string"},
                        "completed": {"type": "boolean"},
                        "completed_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/quality-metrics": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Quality metrics",
            "operationId": "getDashboardQualityMetrics",
            "description": "Get debate quality metrics.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Quality metrics",
                    {
                        "consensus_rate": {"type": "number"},
                        "average_rounds": {"type": "number"},
                        "agent_accuracy": {"type": "number"},
                        "debate_quality_score": {"type": "number"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/quick-actions": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Quick actions",
            "operationId": "getDashboardQuickActions",
            "description": "Get available quick actions.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Quick actions",
                    {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "icon": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        }
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/quick-actions/{action_id}": {
        "post": {
            "tags": ["Dashboard"],
            "summary": "Execute quick action",
            "operationId": "executeDashboardQuickAction",
            "description": "Execute a quick action.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "action_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Action executed",
                    {
                        "action_id": {"type": "string"},
                        "result": {"type": "object"},
                        "success": {"type": "boolean"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/search": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Dashboard search",
            "operationId": "searchDashboard",
            "description": "Search across dashboard resources.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "q",
                    "in": "query",
                    "description": "Search query",
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Search results",
                    {
                        "results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string"},
                                    "title": {"type": "string"},
                                    "snippet": {"type": "string"},
                                    "score": {"type": "number"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/stat-cards": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Stat cards",
            "operationId": "getDashboardStatCards",
            "description": "Get stat card data for dashboard.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Stat cards",
                    {
                        "cards": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "value": {"type": "number"},
                                    "change": {"type": "number"},
                                    "trend": {
                                        "type": "string",
                                        "enum": ["up", "down", "stable"],
                                    },
                                },
                            },
                        }
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/team-performance": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Team performance",
            "operationId": "getDashboardTeamPerformance",
            "description": "Get team performance overview.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Team performance",
                    {
                        "teams": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "team_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "debates_completed": {"type": "integer"},
                                    "success_rate": {"type": "number"},
                                },
                            },
                        }
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/team-performance/{team_id}": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Team performance detail",
            "operationId": "getDashboardTeamPerformanceDetail",
            "description": "Get detailed team performance.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "team_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Team performance detail",
                    {
                        "team_id": {"type": "string"},
                        "name": {"type": "string"},
                        "members": {"type": "array", "items": {"type": "object"}},
                        "stats": {"type": "object"},
                        "recent_debates": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/top-senders": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Top senders",
            "operationId": "getDashboardTopSenders",
            "description": "Get top email senders.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Top senders",
                    {
                        "senders": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string"},
                                    "name": {"type": "string"},
                                    "count": {"type": "integer"},
                                    "priority_score": {"type": "number"},
                                },
                            },
                        }
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/urgent": {
        "get": {
            "tags": ["Dashboard"],
            "summary": "Urgent items",
            "operationId": "getDashboardUrgent",
            "description": "Get urgent items requiring attention.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Urgent items",
                    {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string"},
                                    "title": {"type": "string"},
                                    "severity": {"type": "string"},
                                    "created_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/dashboard/urgent/{item_id}/dismiss": {
        "post": {
            "tags": ["Dashboard"],
            "summary": "Dismiss urgent item",
            "operationId": "dismissDashboardUrgentItem",
            "description": "Dismiss an urgent item.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "item_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Item dismissed",
                    {
                        "item_id": {"type": "string"},
                        "dismissed": {"type": "boolean"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}

# ---------------------------------------------------------------------------
# Receipts (v2)
# ---------------------------------------------------------------------------
_RECEIPT_ENDPOINTS = {
    "/api/v2/receipts": {
        "get": {
            "tags": ["Receipts"],
            "summary": "List receipts",
            "operationId": "listReceipts",
            "description": "List decision receipts.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Receipt list",
                    {
                        "receipts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "debate_id": {"type": "string"},
                                    "hash": {"type": "string"},
                                    "created_at": {"type": "string", "format": "date-time"},
                                    "status": {"type": "string"},
                                },
                            },
                        },
                        "total": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/search": {
        "get": {
            "tags": ["Receipts", "Search"],
            "summary": "Search receipts",
            "operationId": "searchReceipts",
            "description": "Search decision receipts.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Search results",
                    {
                        "results": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "query": {"type": "string"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/stats": {
        "get": {
            "tags": ["Receipts", "Statistics"],
            "summary": "Receipt statistics",
            "operationId": "getReceiptStats",
            "description": "Get receipt statistics.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Receipt stats",
                    {
                        "total": {"type": "integer"},
                        "verified": {"type": "integer"},
                        "by_verdict": {"type": "object"},
                        "by_risk_level": {"type": "object"},
                        "by_framework": {"type": "object"},
                        "generated_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/signing-key": {
        "get": {
            "tags": ["Receipts"],
            "summary": "Get ODR signing public key",
            "operationId": "getReceiptSigningKey",
            "description": (
                "Return the Ed25519 public key (PEM) used to sign Open Decision "
                "Receipts on this deployment, with the derived key id. Public "
                "trust anchor for offline verification via aragora-verify; no "
                "authentication required. Also served as raw PEM at "
                "/.well-known/aragora-odr-signing-key. Returns 404 when no "
                "signing key is configured."
            ),
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "responses": {
                "200": _ok_response(
                    "Signing public key",
                    {
                        "algorithm": {"type": "string"},
                        "key_id": {"type": "string"},
                        "public_key_pem": {"type": "string"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/.well-known/aragora-odr-signing-key": {
        "get": {
            "tags": ["Receipts"],
            "summary": "Get ODR signing public key (raw PEM)",
            "operationId": "getReceiptSigningKeyWellKnown",
            "description": (
                "Well-known alias of /api/v2/receipts/signing-key serving the "
                "Ed25519 public key as raw PEM (application/x-pem-file). "
                "Unauthenticated by design. Returns 404 when no signing key is "
                "configured."
            ),
            "security": AUTH_REQUIREMENTS["none"]["security"],
            "responses": {
                "200": {
                    "description": "PEM-encoded Ed25519 public key",
                    "content": {
                        "application/x-pem-file": {"schema": {"type": "string"}},
                    },
                },
                "404": STANDARD_ERRORS["404"],
            },
        }
    },
    "/api/v1/receipts/deliveries": {
        "get": {
            "tags": ["Receipts", "Delivery"],
            "summary": "List receipt delivery history",
            "operationId": "listReceiptDeliveries",
            "description": "List recent receipt delivery attempts for operator decision-integrity surfaces.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "schema": {"type": "integer", "default": 0, "minimum": 0},
                },
                {
                    "name": "receipt_id",
                    "in": "query",
                    "description": "Filter delivery history to one receipt.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "channel_type",
                    "in": "query",
                    "description": "Filter by delivery channel type.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "status",
                    "in": "query",
                    "description": "Filter by delivery status.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Receipt delivery history",
                    {
                        "deliveries": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/receipts/recent-anchors": {
        "get": {
            "tags": ["Receipts", "Blockchain"],
            "summary": "List recently anchored receipts",
            "operationId": "listRecentReceiptAnchors",
            "description": "List recently anchored receipt hashes and verification metadata.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Recently anchored receipts",
                    {
                        "anchors": {"type": "array", "items": {"type": "object"}},
                        "total": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v1/receipts/{receipt_id}/anchor-status": {
        "get": {
            "tags": ["Receipts", "Blockchain"],
            "summary": "Get receipt anchor status",
            "operationId": "getReceiptAnchorStatus",
            "description": "Verify whether a decision receipt has an on-chain or local anchor.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "description": "Receipt ID to verify.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Receipt anchor verification status",
                    {
                        "receipt_id": {"type": "string"},
                        "anchored": {"type": "boolean"},
                        "anchors": {"type": "array", "items": {"type": "object"}},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/{receipt_id}": {
        "get": {
            "tags": ["Receipts"],
            "summary": "Get receipt",
            "operationId": "getReceiptById",
            "description": "Get a specific receipt by ID.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Receipt details",
                    {
                        "id": {"type": "string"},
                        "debate_id": {"type": "string"},
                        "hash": {"type": "string"},
                        "signature": {"type": "string"},
                        "created_at": {"type": "string", "format": "date-time"},
                        "metadata": {"type": "object"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/{receipt_id}/export": {
        "get": {
            "tags": ["Receipts", "Export"],
            "summary": "Export receipt",
            "operationId": "exportReceipt",
            "description": (
                "Export a receipt in the requested format. format=odr is public; "
                "every other format requires receipts:read."
            ),
            "security": AUTH_REQUIREMENTS["optional"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "format",
                    "in": "query",
                    "description": "Export format; odr returns the Open Decision Receipt.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "odr_version",
                    "in": "query",
                    "description": "ODR profile version for format=odr: 0.1 or 0.2.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    **_ok_response(
                        "Exported receipt",
                        {
                            "receipt_id": {"type": "string"},
                            "format": {"type": "string"},
                            "data": {"type": "string"},
                        },
                    ),
                    "headers": {
                        **STANDARD_RESPONSE_HEADERS,
                        "X-ODR-Digest": {
                            "description": (
                                "JCS content digest of the exported ODR document: "
                                "64 lowercase hex characters. Sent for format=odr."
                            ),
                            "schema": {"type": "string"},
                        },
                    },
                },
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/{receipt_id}/share": {
        "post": {
            "tags": ["Receipts", "Sharing"],
            "summary": "Share receipt",
            "operationId": "shareReceipt",
            "description": "Share a receipt publicly.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Receipt shared",
                    {
                        "success": {"type": "boolean"},
                        "receipt_id": {"type": "string"},
                        "share_url": {"type": "string"},
                        "token": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"},
                        "max_accesses": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}],
                        },
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/share/{token}": {
        "get": {
            "tags": ["Receipts", "Sharing"],
            "summary": "Get shared receipt",
            "operationId": "getSharedReceipt",
            "description": "Access a shared receipt via public token.",
            "parameters": [
                {
                    "name": "token",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "format",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string", "enum": ["html", "json"]},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Shared receipt payload",
                    {
                        "receipt": {"type": "object"},
                        "shared": {"type": "boolean"},
                        "access_count": {"type": "integer"},
                    },
                ),
                "404": STANDARD_ERRORS["404"],
                "410": {
                    "description": "Share link expired or access limit reached",
                },
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
    "/api/v2/receipts/{receipt_id}/verify": {
        "get": {
            "tags": ["Receipts", "Verification"],
            "summary": "Verify receipt",
            "operationId": "verifyReceiptById",
            "description": "Verify receipt integrity.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Verification result",
                    {
                        "receipt_id": {"type": "string"},
                        "valid": {"type": "boolean"},
                        "hash_match": {"type": "boolean"},
                        "verified_at": {"type": "string", "format": "date-time"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "post": {
            "tags": ["Receipts", "Verification"],
            "summary": "Verify receipt integrity",
            "operationId": "verifyReceiptIntegrity",
            "description": "Verify receipt integrity with payload.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Integrity verification result",
                    {
                        "receipt_id": {"type": "string"},
                        "valid": {"type": "boolean"},
                        "integrity_verified": {"type": "boolean"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/v2/receipts/{receipt_id}/verify-signature": {
        "post": {
            "tags": ["Receipts", "Verification"],
            "summary": "Verify receipt signature",
            "operationId": "verifyReceiptSignature",
            "description": "Verify the cryptographic signature of a receipt.",
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "responses": {
                "200": _ok_response(
                    "Signature verification result",
                    {
                        "receipt_id": {"type": "string"},
                        "valid": {"type": "boolean"},
                        "signer": {"type": "string"},
                        "algorithm": {"type": "string"},
                    },
                ),
                "401": STANDARD_ERRORS["401"],
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    },
}

# ---------------------------------------------------------------------------
# System / OpenAPI spec
# ---------------------------------------------------------------------------
_SYSTEM_SCHEMA_ENDPOINTS = {
    "/api/v1/openapi": {
        "get": {
            "tags": ["System"],
            "summary": "Get OpenAPI specification",
            "operationId": "getOpenAPISpec",
            "description": "Returns the full OpenAPI 3.1 specification for all Aragora API endpoints.",
            "responses": {
                "200": {
                    "description": "OpenAPI 3.1 specification",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "openapi": {
                                        "type": "string",
                                        "description": "OpenAPI version",
                                    },
                                    "info": {
                                        "type": "object",
                                        "description": "API metadata",
                                    },
                                    "paths": {
                                        "type": "object",
                                        "description": "API path definitions",
                                    },
                                    "components": {
                                        "type": "object",
                                        "description": "Reusable components",
                                    },
                                },
                            }
                        }
                    },
                },
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Monitoring / Prometheus metrics
# ---------------------------------------------------------------------------
_MONITORING_SCHEMA_ENDPOINTS = {
    "/metrics": {
        "get": {
            "tags": ["Monitoring"],
            "summary": "Prometheus metrics",
            "operationId": "getPrometheusMetrics",
            "description": "Prometheus exposition format metrics for monitoring.",
            "responses": {
                "200": {
                    "description": "Prometheus metrics in OpenMetrics format",
                    "content": {
                        "text/plain": {
                            "schema": {
                                "type": "string",
                                "description": "Prometheus exposition format metrics",
                            }
                        }
                    },
                },
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Podcast XML feed
# ---------------------------------------------------------------------------
_MEDIA_SCHEMA_ENDPOINTS = {
    "/api/v1/podcast/feed.xml": {
        "get": {
            "tags": ["Media"],
            "summary": "Podcast RSS feed",
            "operationId": "getPodcastFeed",
            "description": "Returns podcast episodes as an RSS/Atom XML feed.",
            "responses": {
                "200": {
                    "description": "RSS/Atom podcast feed in XML format",
                    "content": {
                        "application/xml": {
                            "schema": {
                                "type": "string",
                                "description": "XML-formatted RSS/Atom podcast feed",
                            }
                        }
                    },
                },
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Agent Bridge read API schemas
# ---------------------------------------------------------------------------
_NULLABLE_STRING = {"type": ["string", "null"]}
_SCHEMA_VERSION_FIELD = {"type": "integer", "enum": [1]}
_NULLABLE_DATE_TIME_FIELD = {"type": ["string", "null"], "format": "date-time"}

AGENT_BRIDGE_FOOTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "next_actor", "needs_human", "done", "artifacts", "tests_run"],
    "properties": {
        "summary": {"type": "string"},
        "next_actor": _NULLABLE_STRING,
        "needs_human": {"type": "boolean"},
        "done": {"type": "boolean"},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
    },
}

AGENT_BRIDGE_RUN_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "run_id",
        "task",
        "status",
        "created_at",
        "updated_at",
        "completed_at",
        "last_turn_index",
        "next_actor",
        "repair_budget_per_turn",
        "footer_mode",
        "worktree_cleanup_mode",
        "participants",
        "last_event_id",
    ],
    "properties": {
        "schema_version": _SCHEMA_VERSION_FIELD,
        "run_id": {"type": "string"},
        "task": {"type": "string"},
        "status": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "completed_at": _NULLABLE_DATE_TIME_FIELD,
        "last_turn_index": {"type": "integer"},
        "next_actor": _NULLABLE_STRING,
        "repair_budget_per_turn": {"type": "integer"},
        "footer_mode": {"type": "string"},
        "worktree_cleanup_mode": {"type": "string"},
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "harness", "model"],
                "properties": {
                    "role": {"type": "string"},
                    "harness": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
        },
        "last_event_id": _NULLABLE_STRING,
    },
}

AGENT_BRIDGE_SESSION_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "role",
        "harness",
        "model",
        "session_id",
        "worktree_agent_slug",
        "worktree_path",
        "branch",
        "session_status",
        "started_at",
        "last_turn_index",
        "last_completed_at",
    ],
    "properties": {
        "role": {"type": "string"},
        "harness": {"type": "string"},
        "model": {"type": "string"},
        "session_id": _NULLABLE_STRING,
        "worktree_agent_slug": _NULLABLE_STRING,
        "worktree_path": _NULLABLE_STRING,
        "branch": _NULLABLE_STRING,
        "session_status": {
            "type": "string",
            "enum": ["not_started", "active", "completed", "failed"],
        },
        "started_at": _NULLABLE_DATE_TIME_FIELD,
        "last_turn_index": {"type": "integer"},
        "last_completed_at": _NULLABLE_DATE_TIME_FIELD,
        "harness_options": {"type": "object", "additionalProperties": True},
    },
}

AGENT_BRIDGE_RUN_DETAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        *AGENT_BRIDGE_RUN_SUMMARY_SCHEMA["required"],
        "roles",
        "worktree_path",
        "worktree_agent_slug",
    ],
    "properties": {
        **AGENT_BRIDGE_RUN_SUMMARY_SCHEMA["properties"],
        "roles": {
            "type": "object",
            "additionalProperties": AGENT_BRIDGE_SESSION_ENTRY_SCHEMA,
        },
        "worktree_path": _NULLABLE_STRING,
        "worktree_agent_slug": _NULLABLE_STRING,
    },
}

AGENT_BRIDGE_EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "event_id",
        "run_id",
        "ts",
        "event_type",
        "turn_index",
        "role",
        "harness",
        "session_id",
        "parse_status",
        "payload",
    ],
    "properties": {
        "schema_version": _SCHEMA_VERSION_FIELD,
        "event_id": {"type": "string"},
        "run_id": {"type": "string"},
        "ts": {"type": "string", "format": "date-time"},
        "event_type": {
            "type": "string",
            "enum": [
                "run_started",
                "run_failed",
                "run_completed",
                "turn.started",
                "turn.result",
                "turn.completed",
                "turn.repair_requested",
                "footer_ok",
                "footer_malformed",
                "footer_missing",
            ],
        },
        "turn_index": {"type": "integer"},
        "role": {"type": "string"},
        "harness": {"type": "string"},
        "session_id": _NULLABLE_STRING,
        "parse_status": {"type": ["string", "null"], "enum": ["ok", "missing", "malformed", None]},
        "payload": {"type": "object", "additionalProperties": True},
    },
}

AGENT_BRIDGE_TURN_RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "turn_index",
        "author_role",
        "started_at",
        "completed_at",
        "parse_status",
        "footer",
        "body_markdown",
    ],
    "properties": {
        "turn_index": {"type": "integer"},
        "author_role": {"type": "string"},
        "started_at": {"type": "string", "format": "date-time"},
        "completed_at": _NULLABLE_STRING,
        "parse_status": {"type": "string", "enum": ["ok", "missing", "malformed"]},
        "footer": {"oneOf": [AGENT_BRIDGE_FOOTER_SCHEMA, {"type": "null"}]},
        "body_markdown": {"type": "string"},
    },
}

AGENT_BRIDGE_RUN_LIST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "runs"],
    "properties": {
        "schema_version": _SCHEMA_VERSION_FIELD,
        "runs": {"type": "array", "items": AGENT_BRIDGE_RUN_SUMMARY_SCHEMA},
        "next_cursor": _NULLABLE_STRING,
    },
}

AGENT_BRIDGE_EVENTS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "events"],
    "properties": {
        "schema_version": _SCHEMA_VERSION_FIELD,
        "events": {"type": "array", "items": AGENT_BRIDGE_EVENT_SCHEMA},
        "next_cursor": _NULLABLE_STRING,
    },
}

AGENT_BRIDGE_TRANSCRIPT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "turns"],
    "properties": {
        "schema_version": _SCHEMA_VERSION_FIELD,
        "turns": {"type": "array", "items": AGENT_BRIDGE_TURN_RECORD_SCHEMA},
    },
}


# ---------------------------------------------------------------------------
# Review-queue triage metrics (gap #6373, Commitment 5 of docs/THESIS.md)
# ---------------------------------------------------------------------------

# Every rate-style field is nullable so the caller can distinguish
# "zero data / sparse window" from "zero events". Counts are always
# populated so clients can render the denominator next to the rate.

_TRIAGE_WINDOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "window_label",
        "window_days",
        "window_start",
        "window_end",
        "total_decisions",
        "escalation_rate",
        "auto_handle_override_rate",
        "human_override_outcome_correlation",
        "settlement_duration_median_s",
        "settlement_duration_p95_s",
        "counts",
        "notes",
    ],
    "properties": {
        "window_label": {
            "type": "string",
            "description": "Human-readable window width (e.g. '7d', '30d')",
        },
        "window_days": {"type": "integer", "minimum": 1},
        "window_start": {"type": "string", "format": "date-time"},
        "window_end": {"type": "string", "format": "date-time"},
        "total_decisions": {"type": "integer", "minimum": 0},
        "escalation_rate": {
            "type": ["number", "null"],
            "description": "escalations_to_human / total_decisions (nullable when sparse)",
        },
        "auto_handle_override_rate": {
            "type": ["number", "null"],
            "description": (
                "overridden_auto_handles / auto_handled. Null when no auto-handle "
                "lane is active or the window is sparse."
            ),
        },
        "human_override_outcome_correlation": {
            "type": ["number", "null"],
            "minimum": -1,
            "maximum": 1,
            "description": (
                "For human-override decisions with a recorded final_outcome, the "
                "fraction that confirmed the ensemble minus the fraction that "
                "disagreed. Currently null until settlement receipts carry "
                "post-merge outcome data (follow-up to #6373)."
            ),
        },
        "settlement_duration_median_s": {
            "type": ["number", "null"],
            "description": "Median settlement duration (seconds) for escalated decisions.",
        },
        "settlement_duration_p95_s": {
            "type": ["number", "null"],
            "description": "p95 settlement duration (seconds) for escalated decisions.",
        },
        "counts": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "escalations",
                "auto_handled",
                "auto_handle_overrides",
                "human_overrides",
                "human_overrides_with_outcome",
                "settlement_samples",
            ],
            "properties": {
                "escalations": {"type": "integer", "minimum": 0},
                "auto_handled": {"type": "integer", "minimum": 0},
                "auto_handle_overrides": {"type": "integer", "minimum": 0},
                "human_overrides": {"type": "integer", "minimum": 0},
                "human_overrides_with_outcome": {"type": "integer", "minimum": 0},
                "settlement_samples": {"type": "integer", "minimum": 0},
            },
        },
        "notes": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": (
                "Explanations keyed by metric name for any null-valued metric "
                "above. Empty when no metrics were suppressed."
            ),
        },
    },
}


_TRIAGE_DRIFT_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["current", "previous", "delta", "exceeded_threshold"],
    "properties": {
        "current": {"type": ["number", "null"]},
        "previous": {"type": ["number", "null"]},
        "delta": {"type": ["number", "null"]},
        "exceeded_threshold": {"type": "boolean"},
    },
}


_REVIEW_QUEUE_TRIAGE_METRICS_ENDPOINTS: dict[str, Any] = {
    "/api/v1/review-queue/triage-metrics": {
        "get": {
            "tags": ["Review Queue"],
            "summary": "Rolling-window triage metrics",
            "operationId": "getReviewQueueTriageMetrics",
            "description": (
                "Returns rolling 7-day and 30-day aggregates for the four "
                "Commitment-5 metrics named in docs/THESIS.md: escalation "
                "rate, auto-handle override rate, human-override-outcome "
                "correlation, and time-per-settlement (median + p95). "
                "The response also includes advisory drift detection "
                "between the two windows. Metrics that cannot be computed "
                "from the current receipt schema are returned as null "
                "with an explanation in the window's ``notes`` block. "
                "Supports ETag / If-None-Match conditional GETs."
            ),
            "security": AUTH_REQUIREMENTS["required"]["security"],
            "responses": {
                "200": _ok_response(
                    "Rolling-window triage metrics",
                    {
                        "windows": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["7d", "30d"],
                            "properties": {
                                "7d": _TRIAGE_WINDOW_SCHEMA,
                                "30d": _TRIAGE_WINDOW_SCHEMA,
                            },
                        },
                        "drift": {
                            "type": "object",
                            "additionalProperties": _TRIAGE_DRIFT_ENTRY_SCHEMA,
                            "description": (
                                "Advisory drift between the latest and "
                                "previous window, keyed by metric name."
                            ),
                        },
                        "generated_at": {"type": "string", "format": "date-time"},
                        "commitment": {
                            "type": "string",
                            "description": "Source of authority (docs/THESIS.md Commitment 5).",
                        },
                    },
                ),
                "304": {"description": "Not Modified — ETag matched If-None-Match."},
                "401": STANDARD_ERRORS["401"],
                "403": STANDARD_ERRORS["403"],
                "429": STANDARD_ERRORS["429"],
                "500": STANDARD_ERRORS["500"],
            },
        }
    }
}


# ---------------------------------------------------------------------------
# Combined export
# ---------------------------------------------------------------------------
RESPONSE_SCHEMA_ENDPOINTS = {
    **_DASHBOARD_ENDPOINTS,
    **_RECEIPT_ENDPOINTS,
    **_SYSTEM_SCHEMA_ENDPOINTS,
    **_MONITORING_SCHEMA_ENDPOINTS,
    **_MEDIA_SCHEMA_ENDPOINTS,
    **_REVIEW_QUEUE_TRIAGE_METRICS_ENDPOINTS,
}

__all__ = [
    "AGENT_BRIDGE_EVENTS_RESPONSE_SCHEMA",
    "AGENT_BRIDGE_EVENT_SCHEMA",
    "AGENT_BRIDGE_FOOTER_SCHEMA",
    "AGENT_BRIDGE_RUN_DETAIL_SCHEMA",
    "AGENT_BRIDGE_RUN_LIST_RESPONSE_SCHEMA",
    "AGENT_BRIDGE_RUN_SUMMARY_SCHEMA",
    "AGENT_BRIDGE_SESSION_ENTRY_SCHEMA",
    "AGENT_BRIDGE_TRANSCRIPT_RESPONSE_SCHEMA",
    "AGENT_BRIDGE_TURN_RECORD_SCHEMA",
    "RESPONSE_SCHEMA_ENDPOINTS",
]
