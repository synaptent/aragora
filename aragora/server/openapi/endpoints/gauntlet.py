"""Gauntlet API endpoint definitions."""

from aragora.server.openapi.helpers import _ok_response, STANDARD_ERRORS

GAUNTLET_ENDPOINTS = {
    "/api/gauntlet/receipts": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "List decision receipts",
            "operationId": "listGauntletReceipts",
            "description": "Get list of decision receipts with optional filtering.",
            "parameters": [
                {
                    "name": "debate_id",
                    "in": "query",
                    "description": "Filter by debate ID",
                    "schema": {"type": "string"},
                },
                {
                    "name": "from_date",
                    "in": "query",
                    "description": "Filter by date range start (ISO 8601)",
                    "schema": {"type": "string", "format": "date-time"},
                },
                {
                    "name": "to_date",
                    "in": "query",
                    "description": "Filter by date range end (ISO 8601)",
                    "schema": {"type": "string", "format": "date-time"},
                },
                {
                    "name": "consensus_reached",
                    "in": "query",
                    "description": "Filter by consensus status",
                    "schema": {"type": "boolean"},
                },
                {
                    "name": "min_confidence",
                    "in": "query",
                    "description": "Filter by minimum confidence",
                    "schema": {"type": "number", "minimum": 0, "maximum": 1},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 50, "maximum": 200},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "schema": {"type": "integer", "default": 0},
                },
            ],
            "responses": {
                "200": _ok_response("List of decision receipts", "ReceiptList"),
            },
        },
    },
    # Declared under /api/v1 directly so no deprecated unversioned alias is
    # minted: dispatch strips the version prefix, so both forms reach the same
    # handler and the alias only ever duplicated this operation.
    "/api/v1/gauntlet/receipts/{receipt_id}": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Get decision receipt",
            "operationId": "getGauntletReceipt",
            "description": "Get a specific decision receipt by ID.",
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response("Decision receipt details", "DecisionReceipt"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/gauntlet/receipts/{receipt_id}/export": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Export decision receipt",
            "operationId": "getGauntletReceiptsExport",
            "description": "Export a decision receipt in various formats.",
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
                    "description": "Export format",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "enum": ["json", "markdown", "html", "csv", "sarif"],
                    },
                },
                {
                    "name": "include_metadata",
                    "in": "query",
                    "description": "Include metadata in export",
                    "schema": {"type": "boolean", "default": True},
                },
                {
                    "name": "include_evidence",
                    "in": "query",
                    "description": "Include evidence in export",
                    "schema": {"type": "boolean", "default": True},
                },
                {
                    "name": "include_dissent",
                    "in": "query",
                    "description": "Include dissenting views in export",
                    "schema": {"type": "boolean", "default": True},
                },
                {
                    "name": "pretty_print",
                    "in": "query",
                    "description": "Pretty print output (for JSON)",
                    "schema": {"type": "boolean", "default": True},
                },
            ],
            "responses": {
                "200": {
                    "description": "Exported receipt content",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "receipt": {"type": "object"},
                                    "metadata": {"type": "object"},
                                },
                            },
                        },
                        "text/markdown": {
                            "schema": {"type": "string"},
                        },
                        "text/html": {
                            "schema": {"type": "string"},
                        },
                        "text/csv": {
                            "schema": {"type": "string"},
                        },
                    },
                },
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/gauntlet/receipts/export/bundle": {
        "post": {
            "tags": ["Gauntlet"],
            "summary": "Export receipts bundle",
            "operationId": "createGauntletReceiptsExportBundle",
            "description": "Export multiple receipts as a bundle.",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["receipt_ids"],
                            "properties": {
                                "receipt_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of receipt IDs to export",
                                },
                                "format": {
                                    "type": "string",
                                    "enum": ["json", "csv", "markdown"],
                                    "default": "json",
                                },
                                "include_metadata": {"type": "boolean", "default": True},
                                "include_evidence": {"type": "boolean", "default": True},
                                "include_dissent": {"type": "boolean", "default": True},
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": _ok_response(
                    "Bundle of exported receipts",
                    {
                        "receipts": {"type": "array", "items": {"type": "object"}},
                        "exported_count": {"type": "integer"},
                        "format": {"type": "string"},
                    },
                ),
                "400": STANDARD_ERRORS["400"],
            },
        },
    },
    "/api/v1/gauntlet/{gauntlet_id}": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Get gauntlet run",
            "operationId": "getGauntletRun",
            "description": "Get details of a specific gauntlet run by ID.",
            "parameters": [
                {
                    "name": "gauntlet_id",
                    "in": "path",
                    "required": True,
                    "description": "ID of the gauntlet run",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response("Gauntlet run details", "GauntletRun"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
        "delete": {
            "tags": ["Gauntlet"],
            "summary": "Delete gauntlet run",
            "operationId": "deleteGauntletRun",
            "description": "Delete a specific gauntlet run and its associated data.",
            "parameters": [
                {
                    "name": "gauntlet_id",
                    "in": "path",
                    "required": True,
                    "description": "ID of the gauntlet run to delete",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response(
                    "Gauntlet run deleted",
                    {"deleted": {"type": "boolean"}, "gauntlet_id": {"type": "string"}},
                ),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
            "security": [{"bearerAuth": []}],
        },
    },
    "/api/v1/gauntlet/{gauntlet_id}/compare/{other_id}": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Compare gauntlet runs",
            "operationId": "compareGauntletRuns",
            "description": """Compare two gauntlet runs side-by-side.

**Response includes:**
- Finding overlap and differences
- Severity distribution comparison
- Agent performance deltas
- Consensus divergence analysis""",
            "parameters": [
                {
                    "name": "gauntlet_id",
                    "in": "path",
                    "required": True,
                    "description": "ID of the first gauntlet run",
                    "schema": {"type": "string"},
                },
                {
                    "name": "other_id",
                    "in": "path",
                    "required": True,
                    "description": "ID of the second gauntlet run to compare against",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response("Gauntlet comparison results", "GauntletComparison"),
                "404": STANDARD_ERRORS["404"],
                "500": STANDARD_ERRORS["500"],
            },
        },
    },
    "/api/gauntlet/heatmaps": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "List risk heatmaps",
            "operationId": "listGauntletHeatmaps",
            "description": "Get list of generated risk heatmaps.",
            "parameters": [
                {
                    "name": "gauntlet_id",
                    "in": "query",
                    "description": "Filter by gauntlet ID",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "default": 20},
                },
            ],
            "responses": {
                "200": _ok_response("List of risk heatmaps", "HeatmapList"),
            },
        },
    },
    "/api/gauntlet/heatmaps/{heatmap_id}": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Get risk heatmap",
            "operationId": "getGauntletHeatmap",
            "description": "Get a specific risk heatmap by ID.",
            "parameters": [
                {
                    "name": "heatmap_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": _ok_response("Risk heatmap details", "RiskHeatmap"),
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/gauntlet/heatmaps/{heatmap_id}/export": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Export risk heatmap",
            "operationId": "getGauntletHeatmapsExport",
            "description": "Export a risk heatmap in various formats.",
            "parameters": [
                {
                    "name": "heatmap_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {
                    "name": "format",
                    "in": "query",
                    "description": "Export format",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "enum": ["json", "csv", "html"],
                    },
                },
            ],
            "responses": {
                "200": {
                    "description": "Exported heatmap content",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "heatmap": {"type": "object"},
                                    "cells": {"type": "array", "items": {"type": "object"}},
                                },
                            },
                        },
                        "text/csv": {
                            "schema": {"type": "string"},
                        },
                        "text/html": {
                            "schema": {"type": "string"},
                        },
                    },
                },
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
    "/api/gauntlet/receipts/{receipt_id}/stream": {
        "get": {
            "tags": ["Gauntlet"],
            "summary": "Stream receipt export",
            "operationId": "getGauntletReceiptsStream",
            "description": "Stream receipt export for large receipts.",
            "parameters": [
                {
                    "name": "receipt_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    "description": "Streaming JSON response",
                    "content": {
                        "application/x-ndjson": {
                            "schema": {"type": "string"},
                        },
                    },
                },
                "404": STANDARD_ERRORS["404"],
            },
        },
    },
}
