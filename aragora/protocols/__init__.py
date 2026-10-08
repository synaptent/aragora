"""
Protocol Integrations for Aragora.

This module is the canonical import point for all protocol definitions.

Supports:
- MCP (Model Context Protocol) for tool access
- A2A (Agent-to-Agent Protocol) for inter-agent communication
- Backend protocols for storage, memory, and infrastructure
- Domain protocols for agents, debates, and tracking systems

Protocol Categories
-------------------

**Backend Protocols** (sync, simple interfaces for storage implementations):
    Use these when implementing storage backends or simple wrappers.
    - StorageBackend: Debate storage (SQLite, Supabase)
    - MemoryBackend: Multi-tier memory storage
    - EloBackend: ELO rating persistence
    - EmbeddingBackend: Vector/embedding storage
    - ConsensusBackend: Consensus memory storage
    - CritiqueBackend: Critique/pattern storage
    - PersonaBackend: Agent persona storage
    - GenesisBackend: Agent genome/evolution storage

**Domain Protocols** (async, full-featured interfaces for domain logic):
    Use these when typing debate components, agents, and business logic.
    - AgentProtocol: Agent interface with async respond()
    - StreamingAgentProtocol: Agent with streaming support
    - ToolUsingAgentProtocol: Agent with tool use
    - MemoryProtocol: Basic memory interface
    - TieredMemoryProtocol: Multi-tier memory (ContinuumMemory)
    - EloSystemProtocol: Full ELO system with calibration
    - DebateStorageProtocol: Full debate storage interface
    - CalibrationTrackerProtocol: Prediction calibration
    - PositionLedgerProtocol: Agent position tracking
    - RelationshipTrackerProtocol: Agent relationship tracking
    - ConsensusMemoryProtocol: Consensus outcome storage

**Infrastructure Protocols**:
    - RedisClientProtocol: Redis client interface
    - HTTPRequestHandler: HTTP handler interface
    - AuthenticatedUser: User context interface

Usage:
    # For backend storage implementations
    from aragora.protocols import StorageBackend, MemoryBackend

    # For domain logic typing
    from aragora.protocols import AgentProtocol, EloSystemProtocol

    # For A2A communication
    from aragora.protocols import A2AClient, A2AServer
"""

import importlib

# =============================================================================
# A2A Protocol
# =============================================================================
from aragora.protocols.a2a import (
    A2AClient,
    AgentCard,
    TaskRequest,
    TaskResult,
    TaskStatus,
)

# =============================================================================
# Backend Protocols (sync, simple interfaces for storage)
# =============================================================================
from aragora.protocols.backend_protocols import (
    # Agent basics
    Agent,
    AgentRating,
    # Type aliases
    AgentRecord,
    # HTTP/Auth
    AuthenticatedUser,
    # Storage backends
    ConsensusBackend,
    CritiqueBackend,
    DebateRecord,
    EloBackend,
    EmbeddingBackend,
    GenesisBackend,
    HTTPHeaders,
    HTTPRequestHandler,
    MemoryBackend,
    MemoryRecord,
    PathSegments,
    PersonaBackend,
    QueryParams,
    StorageBackend,
)

# =============================================================================
# Domain Protocols (async, full-featured interfaces)
# Split into focused submodules for maintainability.
# =============================================================================
from aragora.protocols.agent_protocols import (
    AgentProtocol,
    StreamingAgentProtocol,
    ToolUsingAgentProtocol,
)
from aragora.protocols.memory_protocols import (
    ContinuumMemoryProtocol,
    CritiqueStoreProtocol,
    MemoryProtocol,
    TieredMemoryProtocol,
)
from aragora.protocols.event_protocols import (
    AsyncEventEmitterProtocol,
    BaseHandlerProtocol,
    EventEmitterProtocol,
    HandlerProtocol,
)
from aragora.protocols.legacy_protocols import (
    AgentProtocol as LegacyAgentProtocol,
    CacheProtocol,
    EventData,
    EventEmitterProtocol as LegacyEventEmitterProtocol,
    EventHandlerProtocol,
    MemoryProtocol as LegacyMemoryProtocol,
    StorageProtocol,
    SyncEventHandlerProtocol,
)
from aragora.protocols.debate_protocols import (
    ConsensusDetectorProtocol,
    ConsensusMemoryProtocol,
    DebateEmbeddingsProtocol,
    DebateResultProtocol,
    FlipDetectorProtocol,
    RankingSystemProtocol,
)
from aragora.protocols.tracker_protocols import (
    CalibrationTrackerProtocol,
    DissentRetrieverProtocol,
    EloSystemProtocol,
    MomentDetectorProtocol,
    PersonaManagerProtocol,
    PositionLedgerProtocol,
    PositionTrackerProtocol,
    RelationshipTrackerProtocol,
)
from aragora.protocols.storage_protocols import (
    DebateStorageProtocol,
    RedisClientProtocol,
    UserStoreProtocol,
)
from aragora.protocols.feature_protocols import (
    BroadcastPipelineProtocol,
    EvidenceCollectorProtocol,
    EvidenceProtocol,
    InsightStoreProtocol,
    PopulationManagerProtocol,
    PromptEvolverProtocol,
    PulseManagerProtocol,
    StreamEventProtocol,
    VerificationBackendProtocol,
    WebhookConfigProtocol,
)
from aragora.protocols.callback_types import (
    AgentT,
    AsyncEventCallback,
    EventCallback,
    MemoryT,
    ResponseFilter,
    Result,
    T,
    VoteCallback,
)

# =============================================================================
# Protocol Aliases (for migration)
# =============================================================================
# When both a Backend and Domain protocol exist for the same concept,
# prefer the Domain protocol for new code.
#
# Mappings:
#   MemoryBackend (sync, simple) vs MemoryProtocol/TieredMemoryProtocol (async, full)
#   EloBackend (sync, simple) vs EloSystemProtocol (async, full)
#   StorageBackend (sync, simple) vs DebateStorageProtocol (async, full)
#   CritiqueBackend (sync, simple) vs CritiqueStoreProtocol (async, full)

__all__ = [
    # A2A
    "A2AClient",
    "A2AServer",
    "AgentCard",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
    # Bridge
    "ProtocolBridge",
    # Backend protocols (sync, storage-focused)
    "Agent",
    "AgentRating",
    "AuthenticatedUser",
    "ConsensusBackend",
    "CritiqueBackend",
    "EloBackend",
    "EmbeddingBackend",
    "GenesisBackend",
    "HTTPHeaders",
    "HTTPRequestHandler",
    "MemoryBackend",
    "PersonaBackend",
    "StorageBackend",
    # Backend type aliases
    "DebateRecord",
    "MemoryRecord",
    "AgentRecord",
    "QueryParams",
    "PathSegments",
    # Domain protocols - Agents
    "AgentProtocol",
    "StreamingAgentProtocol",
    "ToolUsingAgentProtocol",
    # Domain protocols - Memory
    "MemoryProtocol",
    "TieredMemoryProtocol",
    "CritiqueStoreProtocol",
    "ContinuumMemoryProtocol",
    # Domain protocols - Events
    "EventEmitterProtocol",
    "AsyncEventEmitterProtocol",
    # Compatibility protocols from aragora.types.protocols
    "LegacyAgentProtocol",
    "LegacyMemoryProtocol",
    "LegacyEventEmitterProtocol",
    "CacheProtocol",
    "StorageProtocol",
    "EventData",
    "EventHandlerProtocol",
    "SyncEventHandlerProtocol",
    # Domain protocols - Handlers
    "HandlerProtocol",
    "BaseHandlerProtocol",
    # Domain protocols - Debate
    "DebateResultProtocol",
    "ConsensusDetectorProtocol",
    # Domain protocols - Ranking
    "RankingSystemProtocol",
    "EloSystemProtocol",
    # Domain protocols - Trackers
    "CalibrationTrackerProtocol",
    "PositionLedgerProtocol",
    "RelationshipTrackerProtocol",
    "MomentDetectorProtocol",
    "PersonaManagerProtocol",
    "DissentRetrieverProtocol",
    "PositionTrackerProtocol",
    # Domain protocols - Infrastructure
    "RedisClientProtocol",
    # Domain protocols - Storage
    "DebateStorageProtocol",
    "UserStoreProtocol",
    # Domain protocols - Verification
    "VerificationBackendProtocol",
    # Domain protocols - Feedback phase
    "DebateEmbeddingsProtocol",
    "FlipDetectorProtocol",
    "ConsensusMemoryProtocol",
    "PopulationManagerProtocol",
    "PulseManagerProtocol",
    "PromptEvolverProtocol",
    "InsightStoreProtocol",
    "BroadcastPipelineProtocol",
    "EvidenceCollectorProtocol",
    # Cross-cutting protocols
    "EvidenceProtocol",
    "StreamEventProtocol",
    "WebhookConfigProtocol",
    # Type variables
    "T",
    "AgentT",
    "MemoryT",
    # Callback types
    "EventCallback",
    "AsyncEventCallback",
    "ResponseFilter",
    "VoteCallback",
    # Result types
    "Result",
]


def __getattr__(name: str):
    if name == "A2AServer":
        runtime = importlib.import_module("aragora.server.a2a_runtime")
        value = runtime.A2AServer
    elif name == "ProtocolBridge":
        bridge = importlib.import_module("aragora.server.protocol_bridge")
        value = bridge.ProtocolBridge
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
