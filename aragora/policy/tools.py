"""
Tool registration and capability declarations.

Every tool in Aragora should declare its capabilities, risk level,
and required permissions. This enables:
1. Policy enforcement at invocation time
2. Dynamic permission grants based on context
3. Audit logging of tool usage
4. Risk budget calculation

This mirrors the Multi-Agent Card Protocol (MCP) concept:
tools declare what they can do, and the policy engine decides
whether an agent can use them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from aragora.policy.risk import BlastRadius, RiskLevel

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Categories of tools for policy grouping."""

    READ = "read"  # Read files, APIs, databases
    WRITE = "write"  # Write files, create resources
    EXECUTE = "execute"  # Run code, shell commands
    NETWORK = "network"  # External API calls
    DATABASE = "database"  # Database operations
    SYSTEM = "system"  # System administration
    BILLING = "billing"  # Actions with cost


@dataclass
class ToolCapability:
    """A specific capability that a tool provides.

    Example: A file tool might have capabilities:
    - read_file (risk: NONE, blast: READ_ONLY)
    - write_file (risk: MEDIUM, blast: LOCAL)
    - delete_file (risk: HIGH, blast: LOCAL)
    """

    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    blast_radius: BlastRadius = BlastRadius.LOCAL
    requires_human_approval: bool = False
    max_uses_per_session: int | None = None  # None = unlimited
    cooldown_seconds: float = 0.0  # Minimum time between uses


@dataclass
class Tool:
    """A tool that agents can use, with declared capabilities.

    Tools must be registered with the ToolRegistry before agents
    can use them. Each tool declares:
    - What it can do (capabilities)
    - Its overall risk level
    - Whether human approval is ever required
    - Cost multiplier for billing/budgeting
    """

    name: str
    description: str
    category: ToolCategory
    capabilities: list[ToolCapability] = field(default_factory=list)

    # Overall risk (max of capability risks)
    risk_level: RiskLevel = RiskLevel.LOW
    blast_radius: BlastRadius = BlastRadius.LOCAL

    # Approval requirements
    requires_human_approval: bool = False
    human_approval_capabilities: list[str] = field(default_factory=list)

    # Budget multipliers
    cost_multiplier: float = 1.0  # Multiply risk cost by this

    # Metadata
    version: str = "1.0.0"
    maintainer: str = "aragora"
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_capability(self, name: str) -> ToolCapability | None:
        """Get a capability by name."""
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None

    def has_capability(self, name: str) -> bool:
        """Check if tool has a capability."""
        return self.get_capability(name) is not None

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "capabilities": [
                {
                    "name": c.name,
                    "description": c.description,
                    "risk_level": c.risk_level.name,
                    "blast_radius": c.blast_radius.name,
                    "requires_human_approval": c.requires_human_approval,
                }
                for c in self.capabilities
            ],
            "risk_level": self.risk_level.name,
            "blast_radius": self.blast_radius.name,
            "requires_human_approval": self.requires_human_approval,
            "cost_multiplier": self.cost_multiplier,
            "version": self.version,
        }


class ToolRegistry:
    """Registry of available tools and their capabilities.

    The registry is the source of truth for what tools exist
    and what they can do. The policy engine queries it when
    checking if an action is allowed.

    Usage:
        registry = ToolRegistry()

        # Register a tool
        registry.register(Tool(
            name="code_writer",
            description="Write and modify code files",
            category=ToolCategory.WRITE,
            capabilities=[
                ToolCapability("write_file", "Write to a file", RiskLevel.MEDIUM),
                ToolCapability("delete_file", "Delete a file", RiskLevel.HIGH),
            ],
        ))

        # Get tool info
        tool = registry.get("code_writer")
        cap = tool.get_capability("write_file")
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._capability_index: dict[str, list[str]] = {}  # capability -> tool names

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting", tool.name)

        self._tools[tool.name] = tool

        # Index capabilities
        for cap in tool.capabilities:
            if cap.name not in self._capability_index:
                self._capability_index[cap.name] = []
            if tool.name not in self._capability_index[cap.name]:
                self._capability_index[cap.name].append(tool.name)

        logger.info(
            "Registered tool '%s' with %s capabilities (risk: %s, blast: %s)",
            tool.name,
            len(tool.capabilities),
            tool.risk_level.name,
            tool.blast_radius.name,
        )

    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
        if name not in self._tools:
            return False

        tool = self._tools.pop(name)
        for cap in tool.capabilities:
            if cap.name in self._capability_index:
                self._capability_index[cap.name] = [
                    t for t in self._capability_index[cap.name] if t != name
                ]

        logger.info("Unregistered tool '%s'", name)
        return True

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def find_tools_with_capability(self, capability: str) -> list[Tool]:
        """Find all tools that have a specific capability."""
        tool_names = self._capability_index.get(capability, [])
        return [self._tools[name] for name in tool_names if name in self._tools]

    def list_all_capabilities(self) -> dict[str, list[str]]:
        """List all capabilities and which tools provide them."""
        return dict(self._capability_index)

    def to_dict(self) -> dict[str, object]:
        """Convert registry to dictionary."""
        return {
            "tools": {name: tool.to_dict() for name, tool in self._tools.items()},
            "capability_index": self._capability_index,
        }


# Global registry singleton
_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        _register_builtin_tools(_global_registry)
    return _global_registry


def _register_builtin_tools(registry: ToolRegistry) -> None:
    """Register built-in Aragora tools."""

    # File reading tool
    registry.register(
        Tool(
            name="file_reader",
            description="Read files from the filesystem",
            category=ToolCategory.READ,
            risk_level=RiskLevel.NONE,
            blast_radius=BlastRadius.READ_ONLY,
            capabilities=[
                ToolCapability(
                    "read_file",
                    "Read contents of a file",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "list_directory",
                    "List files in a directory",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "search_files",
                    "Search for files by pattern",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
            ],
        )
    )

    # File writing tool
    registry.register(
        Tool(
            name="file_writer",
            description="Write and modify files",
            category=ToolCategory.WRITE,
            risk_level=RiskLevel.MEDIUM,
            blast_radius=BlastRadius.LOCAL,
            capabilities=[
                ToolCapability(
                    "write_file",
                    "Write contents to a file",
                    risk_level=RiskLevel.MEDIUM,
                    blast_radius=BlastRadius.LOCAL,
                ),
                ToolCapability(
                    "create_file",
                    "Create a new file",
                    risk_level=RiskLevel.LOW,
                    blast_radius=BlastRadius.LOCAL,
                ),
                ToolCapability(
                    "delete_file",
                    "Delete a file",
                    risk_level=RiskLevel.HIGH,
                    blast_radius=BlastRadius.LOCAL,
                    requires_human_approval=True,
                ),
            ],
        )
    )

    # Code execution tool
    registry.register(
        Tool(
            name="code_executor",
            description="Execute code and shell commands",
            category=ToolCategory.EXECUTE,
            risk_level=RiskLevel.HIGH,
            blast_radius=BlastRadius.LOCAL,
            requires_human_approval=True,
            capabilities=[
                ToolCapability(
                    "run_python",
                    "Execute Python code",
                    risk_level=RiskLevel.HIGH,
                    blast_radius=BlastRadius.LOCAL,
                ),
                ToolCapability(
                    "run_shell",
                    "Execute shell commands",
                    risk_level=RiskLevel.CRITICAL,
                    blast_radius=BlastRadius.SHARED,
                    requires_human_approval=True,
                ),
                ToolCapability(
                    "run_tests",
                    "Run test suite",
                    risk_level=RiskLevel.LOW,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
            ],
        )
    )

    # Git tool
    registry.register(
        Tool(
            name="git",
            description="Git version control operations",
            category=ToolCategory.WRITE,
            risk_level=RiskLevel.MEDIUM,
            blast_radius=BlastRadius.LOCAL,
            capabilities=[
                ToolCapability(
                    "git_status",
                    "Check git status",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "git_diff",
                    "Show changes",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "git_commit",
                    "Commit changes",
                    risk_level=RiskLevel.MEDIUM,
                    blast_radius=BlastRadius.LOCAL,
                ),
                ToolCapability(
                    "git_push",
                    "Push to remote",
                    risk_level=RiskLevel.HIGH,
                    blast_radius=BlastRadius.SHARED,
                    requires_human_approval=True,
                ),
            ],
        )
    )

    # Database tool
    registry.register(
        Tool(
            name="database",
            description="Database operations",
            category=ToolCategory.DATABASE,
            risk_level=RiskLevel.MEDIUM,
            blast_radius=BlastRadius.SHARED,
            capabilities=[
                ToolCapability(
                    "db_query",
                    "Run read-only queries",
                    risk_level=RiskLevel.NONE,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "db_insert",
                    "Insert records",
                    risk_level=RiskLevel.MEDIUM,
                    blast_radius=BlastRadius.SHARED,
                ),
                ToolCapability(
                    "db_update",
                    "Update records",
                    risk_level=RiskLevel.HIGH,
                    blast_radius=BlastRadius.SHARED,
                ),
                ToolCapability(
                    "db_delete",
                    "Delete records",
                    risk_level=RiskLevel.CRITICAL,
                    blast_radius=BlastRadius.SHARED,
                    requires_human_approval=True,
                ),
            ],
        )
    )

    # External API tool
    registry.register(
        Tool(
            name="external_api",
            description="Call external APIs",
            category=ToolCategory.NETWORK,
            risk_level=RiskLevel.MEDIUM,
            blast_radius=BlastRadius.SHARED,
            cost_multiplier=2.0,  # External calls may have real costs
            capabilities=[
                ToolCapability(
                    "api_get",
                    "GET request to external API",
                    risk_level=RiskLevel.LOW,
                    blast_radius=BlastRadius.READ_ONLY,
                ),
                ToolCapability(
                    "api_post",
                    "POST request to external API",
                    risk_level=RiskLevel.MEDIUM,
                    blast_radius=BlastRadius.SHARED,
                ),
                ToolCapability(
                    "api_delete",
                    "DELETE request to external API",
                    risk_level=RiskLevel.HIGH,
                    blast_radius=BlastRadius.SHARED,
                    requires_human_approval=True,
                ),
            ],
        )
    )


__all__ = [
    "ToolCategory",
    "ToolCapability",
    "Tool",
    "ToolRegistry",
    "get_tool_registry",
]
