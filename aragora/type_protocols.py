"""Domain protocol definitions for Aragora.

Provides Protocol classes for duck-typed interfaces, enabling better
type checking without requiring concrete inheritance relationships.
These are *domain* protocols with async methods and full-featured interfaces.

Note: For *backend* protocols (sync, simple storage interfaces),
see `aragora.core_protocols`.

**Canonical Import Point**: Use `aragora.protocols` for all protocol imports:

    from aragora.protocols import AgentProtocol, EloSystemProtocol

The `aragora.protocols` module provides unified access to both backend and
domain protocols with clear documentation on when to use each.

Protocol Hierarchy:
    AgentProtocol           -> Base agent interface (async respond)
    StreamingAgentProtocol  -> Extends with streaming
    ToolUsingAgentProtocol  -> Extends with tool use

    MemoryProtocol          -> Basic memory interface
    TieredMemoryProtocol    -> Full ContinuumMemory interface

    EloSystemProtocol       -> Full ELO system with calibration, voting accuracy
    CalibrationTrackerProtocol -> Prediction calibration tracking

**Implementation Note**: Protocol definitions are split into focused modules
under `aragora/protocols/`. This file re-exports everything for backward
compatibility. New code should import from `aragora.protocols` directly.
"""

import warnings

# =============================================================================
# Re-exports from focused protocol modules (backward compatibility)
# =============================================================================

from aragora.protocols.agent_protocols import (
    AgentProtocol,
    StreamingAgentProtocol,
    ToolUsingAgentProtocol,
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
from aragora.protocols.debate_protocols import (
    ConsensusDetectorProtocol,
    ConsensusMemoryProtocol,
    DebateEmbeddingsProtocol,
    DebateResultProtocol,
    FlipDetectorProtocol,
    RankingSystemProtocol,
)
from aragora.protocols.event_protocols import (
    AsyncEventEmitterProtocol,
    BaseHandlerProtocol,
    EventEmitterProtocol,
    HandlerProtocol,
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
from aragora.protocols.memory_protocols import (
    ContinuumMemoryProtocol,
    CritiqueStoreProtocol,
    MemoryProtocol,
    TieredMemoryProtocol,
)
from aragora.protocols.storage_protocols import (
    DebateStorageProtocol,
    RedisClientProtocol,
    UserStoreProtocol,
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

warnings.warn(
    "aragora.type_protocols is deprecated; import protocols from aragora.protocols "
    "instead (e.g. `from aragora.protocols import AgentProtocol`).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    # Type variables
    "T",
    "AgentT",
    "MemoryT",
    # Agent protocols
    "AgentProtocol",
    "StreamingAgentProtocol",
    "ToolUsingAgentProtocol",
    # Memory protocols
    "MemoryProtocol",
    "TieredMemoryProtocol",
    "CritiqueStoreProtocol",
    # Event protocols
    "EventEmitterProtocol",
    "AsyncEventEmitterProtocol",
    # Handler protocols
    "HandlerProtocol",
    "BaseHandlerProtocol",
    # Debate protocols
    "DebateResultProtocol",
    "ConsensusDetectorProtocol",
    # Ranking protocols
    "RankingSystemProtocol",
    # Tracker protocols
    "EloSystemProtocol",
    "CalibrationTrackerProtocol",
    "PositionLedgerProtocol",
    "RelationshipTrackerProtocol",
    "MomentDetectorProtocol",
    "PersonaManagerProtocol",
    "DissentRetrieverProtocol",
    # Infrastructure protocols
    "RedisClientProtocol",
    # Storage protocols
    "DebateStorageProtocol",
    "UserStoreProtocol",
    # Verification protocols
    "VerificationBackendProtocol",
    # Feedback phase protocols
    "DebateEmbeddingsProtocol",
    "FlipDetectorProtocol",
    "ConsensusMemoryProtocol",
    "PopulationManagerProtocol",
    "PulseManagerProtocol",
    "PromptEvolverProtocol",
    "InsightStoreProtocol",
    "BroadcastPipelineProtocol",
    # Arena config protocols
    "ContinuumMemoryProtocol",
    "PositionTrackerProtocol",
    "EvidenceCollectorProtocol",
    # Cross-cutting protocols (break circular imports)
    "EvidenceProtocol",
    "StreamEventProtocol",
    "WebhookConfigProtocol",
    # Callback types
    "EventCallback",
    "AsyncEventCallback",
    "ResponseFilter",
    "VoteCallback",
    # Result types
    "Result",
]
