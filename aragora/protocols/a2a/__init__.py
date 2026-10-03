"""
A2A (Agent-to-Agent Protocol) definitions and client.

Implements the A2A protocol for inter-agent communication,
allowing Aragora agents to be discovered and invoked by external systems.

Based on the Linux Foundation A2A specification:
https://github.com/a2aproject/A2A

Key concepts:
- AgentCard: Describes an agent's capabilities
- TaskRequest: Request for an agent to perform work
- TaskResult: Result of agent work
"""

import importlib

from aragora.protocols.a2a.types import (
    AgentCard,
    AgentCapability,
    TaskRequest,
    TaskResult,
    TaskStatus,
    TaskPriority,
    ContextItem,
    SecurityCard,
)

try:
    from aragora.protocols.a2a.client import A2AClient
except ImportError:
    # httpx is an optional dependency in lean CI environments. Keep the
    # broader protocols package importable when the client transport is absent.
    A2AClient = None  # type: ignore[misc,assignment]

__all__ = [
    # Types
    "AgentCard",
    "AgentCapability",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    "TaskPriority",
    "ContextItem",
    "SecurityCard",
    # Client/Server
    "A2AClient",
    "A2AServer",
]


def __getattr__(name: str):
    if name == "A2AServer":
        runtime = importlib.import_module("aragora.server.a2a_runtime")
        server = runtime.A2AServer
        globals()[name] = server
        return server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
