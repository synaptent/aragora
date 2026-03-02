"""MCP config generator for implementation sessions.

Creates a temporary MCP config pointing to Aragora's MCP server
so that Claude Code can use Aragora tools during implementation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_IMPL_CONFIG_SUBDIR = ".nomic/mcp"


def generate_impl_mcp_config(repo_path: Path) -> Path:
    """Generate MCP config JSON for implementation sessions.

    The config points to Aragora's MCP server in stdio transport mode
    with ARAGORA_MCP_IMPL_MODE=1 to scope available tools.

    Args:
        repo_path: Repository root path

    Returns:
        Path to the generated config JSON file
    """
    repo_path = Path(repo_path) if isinstance(repo_path, str) else repo_path
    config_dir = repo_path / _IMPL_CONFIG_SUBDIR
    config_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "mcpServers": {
            "aragora": {
                "command": "python",
                "args": ["-m", "aragora.mcp.server", "--transport", "stdio"],
                "env": {
                    "ARAGORA_MCP_IMPL_MODE": "1",
                    "ARAGORA_REPO_PATH": str(repo_path),
                },
                "cwd": str(repo_path),
            }
        }
    }

    config_path = config_dir / "impl_config.json"
    config_path.write_text(json.dumps(config, indent=2))

    logger.debug("Generated MCP impl config at %s", config_path)
    return config_path
