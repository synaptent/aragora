"""Tests for the MCPToolsHandler (GET /api/v1/mcp/tools)."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import aragora.mcp.tools as _mcp_tools_mod

from aragora.server.handlers.mcp_tools_handler import MCPToolsHandler, _serialize_tool


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FAKE_TOOLS_METADATA = [
    {
        "name": "run_debate",
        "description": "Run a debate",
        "function": MagicMock(),
        "parameters": {
            "question": {"type": "string", "required": True},
            "rounds": {"type": "integer", "required": False, "default": 3},
        },
    },
    {
        "name": "list_agents",
        "description": "List agents",
        "function": MagicMock(),
        "parameters": {},
    },
    {
        "name": "run_gauntlet",
        "description": "Run gauntlet",
        "function": MagicMock(),
        "parameters": {
            "content": {"type": "string", "required": True},
        },
    },
]


def _make_handler() -> MCPToolsHandler:
    return MCPToolsHandler(server_context={})


# ---------------------------------------------------------------------------
# _serialize_tool unit tests
# ---------------------------------------------------------------------------


def test_serialize_tool_required_param() -> None:
    meta = _FAKE_TOOLS_METADATA[0]
    out = _serialize_tool(meta)
    assert out["name"] == "run_debate"
    assert out["description"] == "Run a debate"
    assert out["parameters"]["question"]["required"] is True
    assert out["parameters"]["rounds"]["required"] is False
    assert out["parameters"]["rounds"]["default"] == 3


def test_serialize_tool_no_params() -> None:
    meta = _FAKE_TOOLS_METADATA[1]
    out = _serialize_tool(meta)
    assert out["name"] == "list_agents"
    assert out["parameters"] == {}


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


def test_can_handle_exact_path() -> None:
    h = _make_handler()
    assert h.can_handle("/api/v1/mcp/tools", "GET") is True


def test_can_handle_tool_detail_path() -> None:
    h = _make_handler()
    assert h.can_handle("/api/v1/mcp/tools/run_debate", "GET") is True


def test_cannot_handle_post() -> None:
    h = _make_handler()
    assert h.can_handle("/api/v1/mcp/tools", "POST") is False


def test_cannot_handle_unrelated_path() -> None:
    h = _make_handler()
    assert h.can_handle("/api/v1/debates", "GET") is False


# ---------------------------------------------------------------------------
# _list_tools
# ---------------------------------------------------------------------------


def test_list_tools_returns_all_tools() -> None:
    h = _make_handler()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h._list_tools({})

    assert result.status_code == 200
    body = json.loads(result.body)
    assert body["count"] == 3
    assert len(body["tools"]) == 3


def test_list_tools_category_filter() -> None:
    h = _make_handler()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h._list_tools({"category": "run"})

    assert result.status_code == 200
    body = json.loads(result.body)
    # "run_debate" and "run_gauntlet" both start with "run"
    assert body["count"] == 2
    names = [t["name"] for t in body["tools"]]
    assert "run_debate" in names
    assert "run_gauntlet" in names
    assert "list_agents" not in names


def test_list_tools_empty_category_filter_returns_all() -> None:
    h = _make_handler()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h._list_tools({"category": ""})

    body = json.loads(result.body)
    assert body["count"] == 3


def test_list_tools_import_error_returns_503() -> None:
    """When the mcp.tools module is unavailable, _list_tools returns 503."""
    h = _make_handler()
    saved = sys.modules.get("aragora.mcp.tools")
    try:
        sys.modules["aragora.mcp.tools"] = None  # type: ignore[assignment]
        result = h._list_tools({})
        assert result.status_code in (503, 500)
    finally:
        if saved is not None:
            sys.modules["aragora.mcp.tools"] = saved
        else:
            sys.modules.pop("aragora.mcp.tools", None)


# ---------------------------------------------------------------------------
# _get_tool
# ---------------------------------------------------------------------------


def test_get_tool_found() -> None:
    h = _make_handler()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h._get_tool("run_debate")

    assert result.status_code == 200
    body = json.loads(result.body)
    assert body["tool"]["name"] == "run_debate"


def test_get_tool_not_found_returns_404() -> None:
    h = _make_handler()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h._get_tool("nonexistent_tool")

    assert result.status_code == 404


# ---------------------------------------------------------------------------
# Full handle() routing
# ---------------------------------------------------------------------------


def test_handle_routes_to_list() -> None:
    h = _make_handler()
    mock_handler = MagicMock()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h.handle("/api/v1/mcp/tools", {}, mock_handler)

    assert result is not None
    assert result.status_code == 200


def test_handle_routes_to_detail() -> None:
    h = _make_handler()
    mock_handler = MagicMock()
    with patch.object(_mcp_tools_mod, "TOOLS_METADATA", _FAKE_TOOLS_METADATA):
        result = h.handle("/api/v1/mcp/tools/list_agents", {}, mock_handler)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body)
    assert body["tool"]["name"] == "list_agents"


def test_handle_unknown_path_returns_none() -> None:
    h = _make_handler()
    result = h.handle("/api/v1/something_else", {}, MagicMock())
    assert result is None
