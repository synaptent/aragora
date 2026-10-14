"""Hook through which the Claude Code harness gets the MCP config for implementation sessions.

The harness runs Claude Code with Aragora's MCP server attached, which needs a config file
that ``aragora.mcp`` writes. ``aragora.harnesses`` sits below ``aragora.mcp`` and must not
import it. The first :func:`generate_impl_mcp_config` that finds no generator runs, once per
process, the registrations declared under the ``aragora.harness_mcp_configs`` entry-point
group; aragora's own ``pyproject.toml`` declares the MCP generator there. A later
registration replaces the previous generator.

:func:`generate_impl_mcp_config` raises :class:`ImplMcpConfigNotRegisteredError` when no
generator is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aragora.utils.declared_registrations import DeclaredRegistrations

IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP = "aragora.harness_mcp_configs"

# Writes the MCP config for an implementation session in a repository and returns its path.
ImplMcpConfigGenerator = Callable[[Path], Path]


class ImplMcpConfigNotRegisteredError(RuntimeError):
    """No implementation-session MCP config generator is registered."""


_generator: ImplMcpConfigGenerator | None = None
_declared = DeclaredRegistrations(IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP)


def register_impl_mcp_config_generator(generator: ImplMcpConfigGenerator) -> None:
    """Make ``generator`` write implementation-session MCP configs, replacing any earlier one."""
    global _generator
    _generator = generator


def generate_impl_mcp_config(repo_path: Path) -> Path:
    """Write the MCP config for an implementation session in ``repo_path``.

    Raises:
        ImplMcpConfigNotRegisteredError: no generator is registered, even after the
            declared registrations ran.
    """
    generator = _generator
    if generator is None:
        _declared.load()
        generator = _generator
    if generator is None:
        raise ImplMcpConfigNotRegisteredError(
            "no implementation-session MCP config generator is registered; import "
            "aragora.mcp.harness_registration and call register_harness_impl_mcp_config(), "
            f"or declare a registration under the {IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP!r} "
            "entry-point group"
        )
    return generator(repo_path)


__all__ = [
    "IMPL_MCP_CONFIGS_ENTRY_POINT_GROUP",
    "ImplMcpConfigGenerator",
    "ImplMcpConfigNotRegisteredError",
    "generate_impl_mcp_config",
    "register_impl_mcp_config_generator",
]
