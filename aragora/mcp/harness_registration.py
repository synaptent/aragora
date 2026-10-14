"""Registers the implementation-session MCP config generator with the agent harnesses.

Reached through the ``aragora.harness_mcp_configs`` entry point in ``pyproject.toml`` on the
Claude Code harness's first MCP config request, so ``aragora.harnesses`` never imports
``aragora.mcp``.
"""

from __future__ import annotations

from pathlib import Path

from aragora.harnesses.mcp_config import register_impl_mcp_config_generator
from aragora.mcp import impl_config


def write_impl_mcp_config(repo_path: Path) -> Path:
    """Write the config with :func:`aragora.mcp.impl_config.generate_impl_mcp_config`."""
    # Looked up on each call so a patched module function applies.
    return impl_config.generate_impl_mcp_config(repo_path)


def register_harness_impl_mcp_config() -> None:
    """Register the MCP config generator; safe to call more than once."""
    register_impl_mcp_config_generator(write_impl_mcp_config)


__all__ = ["register_harness_impl_mcp_config", "write_impl_mcp_config"]
