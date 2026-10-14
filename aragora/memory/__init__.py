"""
Memory and pattern storage module.

Provides:
- CritiqueStore: SQLite-based storage for debate results and patterns
- SemanticRetriever: Embedding-based similarity search
- Pattern: Dataclass for critique patterns
- ConsensusMemory: Persistent storage of debate outcomes
- DissentRetriever: Retrieval of historical dissenting views
- TierManager: Configurable memory tier management
- Surprise scoring: Unified surprise-based memorization

Tier System:
- MemoryTier (FAST/MEDIUM/SLOW/GLACIAL): Update frequency tiers
- AccessTier (HOT/WARM/COLD/ARCHIVE): Access recency tiers for debate context
"""

from aragora.memory.consensus import (
    ConsensusMemory,
    ConsensusRecord,
    ConsensusStrength,
    DissentRecord,
    DissentRetriever,
    DissentType,
    SimilarDebate,
)
from aragora.memory.continuum import (
    ContinuumMemory,
    ContinuumMemoryEntry,
    get_continuum_memory,
    reset_continuum_memory,
)
from aragora.memory.cross_debate_rlm import AccessTier
from aragora.memory.capture import (
    ToolCapturePolicy,
    ToolMemoryCapture,
)

# No ImportError guard: embeddings defers the optional aiohttp dependency to
# the first remote embedding fetch, so a failure here is a real defect.
from aragora.memory.embeddings import (
    GeminiEmbedding,
    OllamaEmbedding,
    OpenAIEmbedding,
    SemanticRetriever,
)
from aragora.memory.hybrid_search import (
    HybridMemoryConfig,
    HybridMemorySearch,
    KeywordIndex,
    MemorySearchResult,
    get_hybrid_memory_search,
)
from aragora.memory.store import CritiqueStore, Pattern
from aragora.memory.surprise import (
    SurpriseScorer,
    calculate_base_rate,
    calculate_combined_surprise,
    calculate_surprise,
    calculate_surprise_from_db_row,
    update_surprise_ema,
)
from aragora.memory.titans_controller import TitansMemoryController
from aragora.memory.triggers import (
    MemoryTrigger,
    MemoryTriggerEngine,
    TriggerResult,
)
from aragora.memory.tier_analytics import (
    MemoryAnalytics,
    MemoryUsageEvent,
    TierAnalyticsTracker,
    TierStats,
)
from aragora.memory.tier_manager import (
    MemoryTier,
    TierConfig,
    TierManager,
    TierTransitionMetrics,
    get_tier_manager,
)

__all__ = [
    "CritiqueStore",
    "Pattern",
    "SemanticRetriever",
    "OpenAIEmbedding",
    "GeminiEmbedding",
    "OllamaEmbedding",
    "HybridMemorySearch",
    "HybridMemoryConfig",
    "MemorySearchResult",
    "KeywordIndex",
    "get_hybrid_memory_search",
    # Consensus Memory
    "ConsensusMemory",
    "ConsensusRecord",
    "ConsensusStrength",
    "DissentRecord",
    "DissentType",
    "DissentRetriever",
    "SimilarDebate",
    # Continuum Memory
    "ContinuumMemory",
    "ContinuumMemoryEntry",
    "get_continuum_memory",
    "reset_continuum_memory",
    # Tier Management
    "TierManager",
    "TierConfig",
    "TierTransitionMetrics",
    "MemoryTier",
    "AccessTier",
    "get_tier_manager",
    # Tool Capture
    "ToolCapturePolicy",
    "ToolMemoryCapture",
    # Tier Analytics
    "TierAnalyticsTracker",
    "TierStats",
    "MemoryUsageEvent",
    "MemoryAnalytics",
    # Surprise Scoring
    "SurpriseScorer",
    "calculate_surprise",
    "calculate_base_rate",
    "calculate_combined_surprise",
    "calculate_surprise_from_db_row",
    "update_surprise_ema",
    # Titans Controller
    "TitansMemoryController",
    # Memory Triggers
    "MemoryTriggerEngine",
    "MemoryTrigger",
    "TriggerResult",
]
