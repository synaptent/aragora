"""
Knowledge Mound Adapters - Connect existing memory systems to the unified Knowledge Mound.

This module provides adapter classes that bridge Aragora's existing memory systems
and subsystems to the Knowledge Mound's unified API.

Base classes and mixins:
- KnowledgeMoundAdapter: Base class with event/metrics/state utilities
- SemanticSearchMixin: Unified semantic vector search
- ReverseFlowMixin: Template for KM -> Source sync operations
- FusionMixin: Multi-adapter fusion protocol (Phase A3)

Core adapters (memory systems):
- ContinuumAdapter: Multi-tier memory (fast/medium/slow/glacial)
- ConsensusAdapter: Debate outcomes and agreements
- CritiqueAdapter: Critique patterns and feedback

Bidirectional adapters (subsystem integration):
- EvidenceAdapter: Evidence snippets with quality scores
- BeliefAdapter: Belief network nodes and cruxes
- InsightsAdapter: Debate insights and Trickster flips
- EloAdapter: Agent rankings and calibration
- PulseAdapter: Trending topics and scheduled debates
- CostAdapter: Budget alerts and cost patterns (opt-in)

The adapter pattern enables:
- Gradual migration with dual-write period
- Unified queries across all memory systems
- Consistent provenance and metadata tracking
- Backward compatibility with existing code
- Bidirectional data flow (IN/OUT/reverse)

Usage:
    from aragora.knowledge.mound.adapters import (
        KnowledgeMoundAdapter,  # Base class for new adapters
        SemanticSearchMixin,    # Add semantic search to any adapter
        ReverseFlowMixin,       # Add reverse flow sync
        FusionMixin,            # Add multi-adapter fusion (Phase A3)
        ContinuumAdapter,
        ConsensusAdapter,
        # ... etc
    )
"""

# Base classes and mixins
from ._base import KnowledgeMoundAdapter, EventCallback
from ._types import (
    SyncResult,
    ValidationSyncResult as ValidationSyncResultType,
    SearchResult,
    ValidationResult,
    BatchSyncResult,
)
from ._semantic_mixin import SemanticSearchMixin
from ._reverse_flow_base import ReverseFlowMixin, ValidationSyncResult
from ._fusion_mixin import FusionMixin, FusionSyncResult, FusionState

# Core memory adapters
from .continuum_adapter import ContinuumAdapter, ContinuumSearchResult
from .consensus_adapter import ConsensusAdapter, ConsensusSearchResult
from .critique_adapter import CritiqueAdapter, CritiqueSearchResult

# Bidirectional integration adapters
from .evidence_adapter import (
    EvidenceAdapter,
    EvidenceSearchResult,
    EvidenceAdapterError,
    EvidenceStoreUnavailableError,
    EvidenceNotFoundError,
)
from .belief_adapter import BeliefAdapter, BeliefSearchResult, CruxSearchResult
from .insights_adapter import InsightsAdapter, InsightSearchResult, FlipSearchResult
from .performance_adapter import EloAdapter, RatingSearchResult
from .pulse_adapter import PulseAdapter, TopicSearchResult
from .cost_adapter import CostAdapter, CostAnomaly, AlertSearchResult
from .performance_adapter import RankingAdapter, AgentExpertise, ExpertiseSearchResult
from .performance_adapter import PerformanceAdapter
from .rlm_adapter import RlmAdapter, CompressionPattern, ContentPriority
from .culture_adapter import CultureAdapter, StoredCulturePattern, CultureSearchResult
from .control_plane_adapter import (
    ControlPlaneAdapter,
    TaskOutcome,
    AgentCapabilityRecord,
    CrossWorkspaceInsight,
)
from .fabric_adapter import (
    FabricAdapter,
    PoolSnapshot,
    TaskSchedulingOutcome,
    BudgetUsageSnapshot,
    PolicyDecisionRecord,
)
from .workspace_adapter import (
    WorkspaceAdapter,
    RigSnapshot,
    ConvoyOutcome,
    MergeOutcome,
)
from .computer_use_adapter import (
    ComputerUseAdapter,
    TaskExecutionRecord,
    ActionPerformanceRecord,
    PolicyBlockRecord,
)
from .gateway_adapter import (
    GatewayAdapter,
    MessageRoutingRecord,
    ChannelPerformanceSnapshot,
    DeviceRegistrationRecord,
    RoutingDecisionRecord,
)
from .receipt_adapter import (
    ReceiptAdapter,
    ReceiptAdapterError,
    ReceiptNotFoundError,
    ReceiptIngestionResult,
)
from .crux_receipt_adapter import (
    CruxReceiptAdapter,
    CruxIngestionResult,
)
from .executable_claim_adapter import (
    ExecutableClaimAdapter,
    ClaimIngestionResult,
)
from .decision_plan_adapter import (
    DecisionPlanAdapter,
    DecisionPlanAdapterError,
    PlanIngestionResult,
    get_decision_plan_adapter,
)
from .calibration_fusion_adapter import (
    CalibrationFusionAdapter,
    CalibrationSearchResult,
    CalibrationSyncResult,
)
from .extraction_adapter import (
    ExtractionAdapter,
    ExtractionAdapterError,
    ExtractionNotFoundError,
    ExtractionSearchResult,
    RelationshipSearchResult,
    KnowledgeGraphNode,
    BatchExtractionResult,
)
from .openclaw_adapter import (
    OpenClawAdapter,
    OpenClawKnowledgeItem,
    ActionPattern,
    ActionStatus,
    PatternType,
    KMContextUpdate,
    TaskPrioritizationUpdate,
    KMValidationResult as OpenClawKMValidationResult,
    OpenClawKMSyncResult,
    SyncResult as OpenClawSyncResult,
)
from .erc8004_adapter import ERC8004Adapter
from .supermemory_adapter import (
    SupermemoryAdapter,
    ContextInjectionResult,
    SyncOutcomeResult,
    SupermemorySearchResult,
)
from .trickster_adapter import (
    TricksterAdapter,
    TricksterSearchResult,
    InterventionRecord,
)
from .obsidian_adapter import (
    ObsidianAdapter,
    ObsidianSyncConfig,
)
from .debate_adapter import (
    DebateAdapter,
    DebateSearchResult,
    DebateOutcome,
)
from .workflow_adapter import (
    WorkflowAdapter,
    WorkflowSearchResult,
    WorkflowOutcome,
)
from .compliance_adapter import (
    ComplianceAdapter,
    ComplianceSearchResult,
    CheckOutcome,
    ViolationOutcome,
)
from .pipeline_adapter import (
    PipelineAdapter,
    PipelineAdapterError,
    PipelineIngestionResult,
    SimilarPipeline,
    PipelineStatus,
    get_pipeline_adapter,
)

# Factory for auto-creating adapters from Arena subsystems
from .factory import AdapterFactory, AdapterSpec, CreatedAdapter, ADAPTER_SPECS

__all__ = [
    # Base classes and mixins
    "KnowledgeMoundAdapter",
    "EventCallback",
    "SemanticSearchMixin",
    "ReverseFlowMixin",
    "FusionMixin",
    "FusionSyncResult",
    "FusionState",
    # Shared types
    "SyncResult",
    "ValidationSyncResultType",
    "SearchResult",
    "ValidationResult",
    "BatchSyncResult",
    "ValidationSyncResult",
    # Core memory adapters
    "ContinuumAdapter",
    "ContinuumSearchResult",
    "ConsensusAdapter",
    "ConsensusSearchResult",
    "CritiqueAdapter",
    "CritiqueSearchResult",
    # Bidirectional integration adapters
    "EvidenceAdapter",
    "EvidenceSearchResult",
    "EvidenceAdapterError",
    "EvidenceStoreUnavailableError",
    "EvidenceNotFoundError",
    "BeliefAdapter",
    "BeliefSearchResult",
    "CruxSearchResult",
    "InsightsAdapter",
    "InsightSearchResult",
    "FlipSearchResult",
    "EloAdapter",
    "RatingSearchResult",
    "PulseAdapter",
    "TopicSearchResult",
    "CostAdapter",
    "CostAnomaly",
    "AlertSearchResult",
    "RankingAdapter",
    "AgentExpertise",
    "ExpertiseSearchResult",
    "PerformanceAdapter",
    "RlmAdapter",
    "CompressionPattern",
    "ContentPriority",
    "CultureAdapter",
    "StoredCulturePattern",
    "CultureSearchResult",
    # Control Plane adapter
    "ControlPlaneAdapter",
    "TaskOutcome",
    "AgentCapabilityRecord",
    "CrossWorkspaceInsight",
    # Fabric adapter (Agent Fabric → Knowledge Mound)
    "FabricAdapter",
    "PoolSnapshot",
    "TaskSchedulingOutcome",
    "BudgetUsageSnapshot",
    "PolicyDecisionRecord",
    # Workspace adapter (Workspace Manager → Knowledge Mound)
    "WorkspaceAdapter",
    "RigSnapshot",
    "ConvoyOutcome",
    "MergeOutcome",
    # Computer-Use adapter (Orchestrator → Knowledge Mound)
    "ComputerUseAdapter",
    "TaskExecutionRecord",
    "ActionPerformanceRecord",
    "PolicyBlockRecord",
    # Gateway adapter (LocalGateway → Knowledge Mound)
    "GatewayAdapter",
    "MessageRoutingRecord",
    "ChannelPerformanceSnapshot",
    "DeviceRegistrationRecord",
    "RoutingDecisionRecord",
    # Receipt adapter (Decision → Knowledge Mound)
    "ReceiptAdapter",
    "ReceiptAdapterError",
    "ReceiptNotFoundError",
    "ReceiptIngestionResult",
    # CruxReceipt adapter (DIC-16: crux-finder runs → Knowledge Mound)
    "CruxReceiptAdapter",
    "CruxIngestionResult",
    # ExecutableClaim adapter (DIC-16: claim verification results → Knowledge Mound)
    "ExecutableClaimAdapter",
    "ClaimIngestionResult",
    # Decision Plan adapter (Gold Path → Knowledge Mound)
    "DecisionPlanAdapter",
    "DecisionPlanAdapterError",
    "PlanIngestionResult",
    "get_decision_plan_adapter",
    # Calibration fusion adapter (Phase A3)
    "CalibrationFusionAdapter",
    "CalibrationSearchResult",
    "CalibrationSyncResult",
    # Extraction adapter (Knowledge Extraction → Knowledge Mound)
    "ExtractionAdapter",
    "ExtractionAdapterError",
    "ExtractionNotFoundError",
    "ExtractionSearchResult",
    "RelationshipSearchResult",
    "KnowledgeGraphNode",
    "BatchExtractionResult",
    # Factory for auto-creating adapters
    "AdapterFactory",
    "AdapterSpec",
    "CreatedAdapter",
    "ADAPTER_SPECS",
    # OpenClaw adapter (OpenClaw → Knowledge Mound)
    "OpenClawAdapter",
    "OpenClawKnowledgeItem",
    "ActionPattern",
    "ActionStatus",
    "PatternType",
    "KMContextUpdate",
    "TaskPrioritizationUpdate",
    "OpenClawKMValidationResult",
    "OpenClawKMSyncResult",
    "OpenClawSyncResult",
    # Blockchain adapter (ERC-8004)
    "ERC8004Adapter",
    # Supermemory adapter (External memory persistence)
    "SupermemoryAdapter",
    "ContextInjectionResult",
    "SyncOutcomeResult",
    "SupermemorySearchResult",
    # Trickster adapter (Hollow consensus → Knowledge Mound)
    "TricksterAdapter",
    "TricksterSearchResult",
    "InterventionRecord",
    "ObsidianAdapter",
    "ObsidianSyncConfig",
    # Debate adapter (Debate outcomes → Knowledge Mound)
    "DebateAdapter",
    "DebateSearchResult",
    "DebateOutcome",
    # Workflow adapter (Workflow executions → Knowledge Mound)
    "WorkflowAdapter",
    "WorkflowSearchResult",
    "WorkflowOutcome",
    # Compliance adapter (Compliance results → Knowledge Mound)
    "ComplianceAdapter",
    "ComplianceSearchResult",
    "CheckOutcome",
    "ViolationOutcome",
    # Pipeline adapter (Idea-to-Execution Pipeline → Knowledge Mound)
    "PipelineAdapter",
    "PipelineAdapterError",
    "PipelineIngestionResult",
    "SimilarPipeline",
    "PipelineStatus",
    "get_pipeline_adapter",
]
