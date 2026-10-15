"""
Agent role hierarchy (compatibility path).

The module lives in :mod:`aragora.agents.roles`; this module re-exports the same objects.
The default hierarchy returned by ``get_agent_hierarchy`` lives only in the new
module; reset it with ``reset_agent_hierarchy``.
"""

from __future__ import annotations

from aragora.agents.roles import (
    AgentHierarchy,
    AgentRole,
    ROLE_CAPABILITIES,
    RoleAssignment,
    RoleBasedRouter,
    RoleCapability,
    get_agent_hierarchy,
    reset_agent_hierarchy,
)

__all__ = [
    "AgentHierarchy",
    "AgentRole",
    "ROLE_CAPABILITIES",
    "RoleAssignment",
    "RoleBasedRouter",
    "RoleCapability",
    "get_agent_hierarchy",
    "reset_agent_hierarchy",
]
