"""Pure protocol bridge definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Protocol(str, Enum):
    """Supported protocols."""

    MCP = "mcp"
    A2A = "a2a"


@dataclass
class ExternalResource:
    """An external resource accessible via protocol."""

    protocol: Protocol
    uri: str
    name: str
    description: str = ""
    mime_type: str = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BridgeConfig:
    """Configuration for the protocol bridge."""

    enable_mcp: bool = True
    mcp_timeout: float = 60.0
    enable_a2a: bool = True
    a2a_timeout: float = 300.0
    a2a_registries: list[str] = field(default_factory=list)
    default_protocol: Protocol = Protocol.A2A
    cache_agent_cards: bool = True


__all__ = [
    "Protocol",
    "ExternalResource",
    "BridgeConfig",
]
