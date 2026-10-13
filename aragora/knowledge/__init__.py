"""
Knowledge Base module for enterprise document auditing.

Provides:
- FactStore: SQLite-based storage for agreed-upon facts
- DatasetQueryEngine: Natural language query interface
- WeaviateEmbeddingService: Vector search integration
- FactExtractor: Multi-agent fact extraction from documents

The knowledge base builds on top of the Evidence system to create
a queryable layer of verified facts that have been agreed upon
through multi-agent debate and Byzantine consensus.

Usage:
    from aragora.knowledge import FactStore, Fact, ValidationStatus

    store = FactStore()
    fact = await store.add_fact(
        statement="Contract expires on 2025-12-31",
        evidence_ids=["ev_123", "ev_456"],
        source_documents=["doc_789"],
    )

    # Query facts
    facts = await store.query_facts(
        query="contract expiration",
        workspace_id="ws_abc",
    )
"""

from aragora.knowledge.types import (
    Fact,
    FactFilters,
    FactRelation,
    FactRelationType,
    QueryResult,
    ValidationStatus,
    VerificationResult,
)
from aragora.knowledge.fact_store import (
    FactStore,
    InMemoryFactStore,
    OrgScopeRequiredError,
    ScopedFactStore,
)
from aragora.knowledge.embeddings import (
    ChunkMatch,
    EmbeddingConfig,
    InMemoryEmbeddingService,
    WeaviateEmbeddingService,
)
from aragora.knowledge.query_engine import (
    DatasetQueryEngine,
    QueryOptions,
    SimpleQueryEngine,
)
from aragora.knowledge.pipeline import (
    KnowledgePipeline,
    PipelineConfig,
    ProcessingResult,
    create_pipeline,
)
from aragora.knowledge.fact_extractor import (
    ExtractionConfig,
    ExtractionResult,
    ExtractedFact,
    FactExtractor,
    create_fact_extractor,
)
from aragora.knowledge.integration import (
    KnowledgeProcessingConfig,
    ProcessingJob,
    get_all_jobs,
    get_job_status,
    get_pipeline,
    process_document_async,
    process_document_sync,
    process_text_async,
    process_text_sync,
    process_uploaded_document,
    process_uploaded_text,
    queue_document_processing,
    queue_text_processing,
    shutdown_pipeline,
)

# Import main KnowledgeMound from mound_core.py
from aragora.knowledge.mound_core import (
    KnowledgeMound,
    KnowledgeNode,
    ProvenanceChain,
    ProvenanceType,
)

# Import unified query interface
from aragora.knowledge.unified import (
    UnifiedKnowledgeStore,
    UnifiedStoreConfig,
    KnowledgeSource,
    KnowledgeItem,
)

# Import vector store
from aragora.knowledge.vector_store import (
    KnowledgeVectorStore,
    KnowledgeVectorConfig,
    KnowledgeSearchResult,
    WEAVIATE_AVAILABLE,
)

__all__ = [
    # Core types
    "Fact",
    "FactFilters",
    "FactRelation",
    "FactRelationType",
    "QueryResult",
    "ValidationStatus",
    "VerificationResult",
    # Stores
    "FactStore",
    "InMemoryFactStore",
    "OrgScopeRequiredError",
    "ScopedFactStore",
    # Embeddings
    "ChunkMatch",
    "EmbeddingConfig",
    "InMemoryEmbeddingService",
    "WeaviateEmbeddingService",
    # Query Engine
    "DatasetQueryEngine",
    "QueryOptions",
    "SimpleQueryEngine",
    # Pipeline
    "KnowledgePipeline",
    "PipelineConfig",
    "ProcessingResult",
    "create_pipeline",
    # Fact Extractor
    "ExtractionConfig",
    "ExtractionResult",
    "ExtractedFact",
    "FactExtractor",
    "create_fact_extractor",
    # Integration
    "KnowledgeProcessingConfig",
    "ProcessingJob",
    "get_all_jobs",
    "get_job_status",
    "get_pipeline",
    "process_document_async",
    "process_document_sync",
    "process_text_async",
    "process_text_sync",
    "process_uploaded_document",
    "process_uploaded_text",
    "queue_document_processing",
    "queue_text_processing",
    "shutdown_pipeline",
    # Knowledge Mound
    "KnowledgeMound",
    "KnowledgeNode",
    "ProvenanceChain",
    "ProvenanceType",
    # Unified Knowledge Store
    "UnifiedKnowledgeStore",
    "UnifiedStoreConfig",
    "KnowledgeSource",
    "KnowledgeItem",
    # Vector Store
    "KnowledgeVectorStore",
    "KnowledgeVectorConfig",
    "KnowledgeSearchResult",
    "WEAVIATE_AVAILABLE",
]
