"""
MCP Tool Discovery Handler.

Exposes the Aragora MCP tool catalog via a REST endpoint so the frontend
and external clients can discover available tools without connecting to
the MCP server directly:

- GET /api/v1/mcp/tools          — Full tool catalog
- GET /api/v1/mcp/tools/{name}   — Details for a single tool

Reads metadata from aragora.mcp.tools.TOOLS_METADATA (the canonical source
used by the MCP server). Returns a stable, serialisable JSON shape.
"""

from __future__ import annotations

__all__ = ["MCPToolsHandler"]

import logging
import re
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)

logger = logging.getLogger(__name__)

_TOOL_NAME_RE = re.compile(r"^/api/v1/mcp/tools/([a-zA-Z0-9_-]+)$")


def _serialize_tool(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert a TOOLS_METADATA entry to a JSON-safe dict."""
    params: dict[str, Any] = {}
    raw_params = meta.get("parameters") or {}
    for param_name, param_meta in raw_params.items():
        if isinstance(param_meta, dict):
            params[param_name] = {
                "type": param_meta.get("type", "string"),
                "required": bool(param_meta.get("required", False)),
                "default": param_meta.get("default"),
            }
        else:
            params[param_name] = {"type": "string", "required": False, "default": None}

    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "parameters": params,
    }


class MCPToolsHandler(BaseHandler):
    """Handler for MCP tool discovery endpoints."""

    ROUTES = [
        "GET /api/v1/mcp/tools",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        if method != "GET":
            return False
        return path == "/api/v1/mcp/tools" or bool(_TOOL_NAME_RE.match(path))

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route MCP tool requests."""
        if path == "/api/v1/mcp/tools":
            return self._list_tools(query_params)

        m = _TOOL_NAME_RE.match(path)
        if m:
            return self._get_tool(m.group(1))

        return None

    def _list_tools(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return the full MCP tool catalog.

        Optional query param: ``category`` — filter by tool name prefix
        (e.g. ``?category=debate`` returns only debate-related tools).
        """
        try:
            from aragora.mcp.tools import TOOLS_METADATA

            tools = [_serialize_tool(m) for m in TOOLS_METADATA]

            # Optional category/prefix filter
            category = (query_params.get("category") or "").strip().lower()
            if category:
                tools = [t for t in tools if t["name"].startswith(category)]

            return json_response(
                {
                    "tools": tools,
                    "count": len(tools),
                }
            )
        except ImportError:
            logger.warning("aragora.mcp.tools not available")
            return error_response("MCP tools module not available", 503)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("MCP tool list failed: %s", exc)
            return error_response("Failed to load MCP tools", 500)

    def _get_tool(self, tool_name: str) -> HandlerResult:
        """Return details for a single MCP tool by name."""
        try:
            from aragora.mcp.tools import TOOLS_METADATA

            for meta in TOOLS_METADATA:
                if meta.get("name") == tool_name:
                    return json_response({"tool": _serialize_tool(meta)})

            return error_response(f"Tool '{tool_name}' not found", 404)
        except ImportError:
            return error_response("MCP tools module not available", 503)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("MCP tool lookup failed: %s", exc)
            return error_response("Failed to load MCP tool", 500)
