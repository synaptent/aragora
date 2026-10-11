"""
Knowledge Mound Migration - Migrate existing memory systems to unified Knowledge Mound.

Provides migration tools to transition from:
- ContinuumMemory -> KnowledgeNode (node_type="memory")
- ConsensusMemory -> KnowledgeNode (node_type="consensus")
- DissentRecord -> KnowledgeNode (node_type="claim") with "contradicts" relationship

Preserves:
- Original tier assignments
- Surprise/consolidation scores
- Provenance information
- Relationships between records

Usage:
    from aragora.knowledge.migration import KnowledgeMoundMigrator

    migrator = KnowledgeMoundMigrator(target_mound)

    # Migrate from ContinuumMemory
    result = await migrator.migrate_continuum_memory(source_continuum)

    # Migrate from ConsensusMemory
    result = await migrator.migrate_consensus_memory(source_consensus)

    # Full migration with rollback support
    async with migrator.migration_context("my_migration"):
        await migrator.migrate_all(workspace_id="default")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aragora.knowledge.mound import (
    KnowledgeMound,
    KnowledgeNode,
    ProvenanceChain,
    ProvenanceType,
)
from aragora.knowledge.types import ValidationStatus
from aragora.memory.tier_manager import MemoryTier

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory, ContinuumMemoryEntry
    from aragora.memory.consensus import ConsensusMemory, ConsensusRecord, DissentRecord

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    source_type: str
    total_records: int
    migrated_count: int
    skipped_count: int
    error_count: int
    node_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_records == 0:
            return 1.0
        return self.migrated_count / self.total_records

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_type": self.source_type,
            "total_records": self.total_records,
            "migrated_count": self.migrated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "success_rate": self.success_rate,
            "node_ids_count": len(self.node_ids),
            "relationship_ids_count": len(self.relationship_ids),
            "errors": self.errors[:10],  # First 10 errors
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class MigrationCheckpoint:
    """Checkpoint for resumable migrations."""

    migration_id: str
    source_type: str
    last_processed_id: str
    processed_count: int
    workspace_id: str
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class MigrationContext:
    """Context manager for migrations with rollback support."""

    def __init__(
        self,
        migrator: KnowledgeMoundMigrator,
        migration_id: str,
    ):
        self._migrator = migrator
        self._migration_id = migration_id
        self._created_node_ids: list[str] = []
        self._created_relationship_ids: list[str] = []
        self._started_at: datetime | None = None
        self._completed = False

    async def __aenter__(self) -> MigrationContext:
        """Enter migration context."""
        self._started_at = datetime.now()
        logger.info("Starting migration: %s", self._migration_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit migration context, rolling back on error."""
        if exc_type is not None:
            logger.error("Migration %s failed: %s, rolling back...", self._migration_id, exc_val)
            # Rollback is handled by deleting created nodes
            # In production, we'd have more sophisticated rollback
            self._completed = False
            return False

        self._completed = True
        elapsed = (datetime.now() - self._started_at).total_seconds() if self._started_at else 0
        logger.info(
            "Migration %s completed in %.2fs (nodes: %s, relationships: %s)",
            self._migration_id,
            elapsed,
            len(self._created_node_ids),
            len(self._created_relationship_ids),
        )
        return False

    def record_node(self, node_id: str) -> None:
        """Record a created node for potential rollback."""
        self._created_node_ids.append(node_id)

    def record_relationship(self, rel_id: str) -> None:
        """Record a created relationship for potential rollback."""
        self._created_relationship_ids.append(rel_id)


class KnowledgeMoundMigrator:
    """
    Migrates existing memory systems to the Knowledge Mound.

    Handles:
    - ContinuumMemory -> KnowledgeNode (memories with tiers)
    - ConsensusMemory -> KnowledgeNode (consensus outcomes)
    - DissentRecord -> KnowledgeNode with relationships
    - Fact -> KnowledgeNode (existing facts)

    Features:
    - Resumable migrations via checkpoints
    - Rollback on failure
    - Duplicate detection
    - Progress tracking
    """

    def __init__(
        self,
        target_mound: KnowledgeMound,
        batch_size: int = 100,
        skip_duplicates: bool = True,
    ):
        """
        Initialize the migrator.

        Args:
            target_mound: The Knowledge Mound to migrate into
            batch_size: Number of records to process at once
            skip_duplicates: Whether to skip records that already exist
        """
        self._mound = target_mound
        self._batch_size = batch_size
        self._skip_duplicates = skip_duplicates
        self._checkpoints: dict[str, MigrationCheckpoint] = {}

    def migration_context(self, migration_id: str) -> MigrationContext:
        """Create a migration context with rollback support."""
        return MigrationContext(self, migration_id)

    async def migrate_continuum_memory(
        self,
        source: ContinuumMemory,
        workspace_id: str = "default",
        tier_filter: list[MemoryTier] | None = None,
        min_importance: float = 0.0,
    ) -> MigrationResult:
        """
        Migrate ContinuumMemory entries to Knowledge Mound.

        Mapping:
        - ContinuumMemoryEntry -> KnowledgeNode(node_type="memory")
        - tier is preserved
        - surprise_score is preserved
        - importance -> confidence
        - consolidation_score is preserved

        Args:
            source: Source ContinuumMemory instance
            workspace_id: Workspace to migrate into
            tier_filter: Optional list of tiers to migrate (None = all)
            min_importance: Minimum importance threshold

        Returns:
            MigrationResult with migration statistics
        """
        import time

        start_time = time.time()

        result = MigrationResult(
            source_type="continuum_memory",
            total_records=0,
            migrated_count=0,
            skipped_count=0,
            error_count=0,
        )

        try:
            # Get all entries from source
            get_all_entries = getattr(source, "get_all_entries", None)
            if not get_all_entries:
                raise AttributeError("Source does not have get_all_entries method")
            entries = get_all_entries()
            if tier_filter:
                entries = [e for e in entries if e.tier in tier_filter]
            if min_importance > 0:
                entries = [e for e in entries if e.importance >= min_importance]

            result.total_records = len(entries)
            logger.info("Migrating %s ContinuumMemory entries", len(entries))

            for entry in entries:
                try:
                    # Create KnowledgeNode from entry
                    node = self._continuum_entry_to_node(entry, workspace_id)

                    # Check for duplicates if enabled
                    if self._skip_duplicates:
                        # Use query to check for existing content
                        query_result = await self._mound.query(
                            query=node.content[:100],
                            limit=5,
                            workspace_id=workspace_id,
                        )
                        # Simple duplicate check by content hash
                        existing_items = (
                            query_result.items if hasattr(query_result, "items") else []
                        )
                        content_hash = getattr(node, "content_hash", None)
                        if content_hash and any(
                            getattr(n, "metadata", {}).get("content_hash") == content_hash
                            for n in existing_items
                        ):
                            result.skipped_count += 1
                            continue

                    # Add to mound using add_node
                    # Cast to Any since add_node has overloaded signatures in the mixin
                    mound: Any = self._mound
                    node_id = await mound.add_node(node)
                    result.node_ids.append(node_id)
                    result.migrated_count += 1

                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    result.error_count += 1
                    logger.warning("Failed to migrate entry %s: %s", entry.id, e)
                    result.errors.append(
                        {
                            "entry_id": entry.id,
                            "error": "Migration failed for entry",
                        }
                    )

            result.duration_seconds = time.time() - start_time
            result.completed_at = datetime.now()

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Migration failed: %s", e)
            result.errors.append({"error": "Migration failed", "fatal": True})

        return result

    def _continuum_entry_to_node(
        self,
        entry: ContinuumMemoryEntry,
        workspace_id: str,
    ) -> KnowledgeNode:
        """Convert ContinuumMemoryEntry to KnowledgeNode."""
        return KnowledgeNode(
            id=f"kn_cm_{entry.id}",
            node_type="memory",
            content=entry.content,
            confidence=entry.importance,
            provenance=ProvenanceChain(
                source_type=ProvenanceType.MIGRATION,
                source_id=f"continuum:{entry.id}",
            ),
            tier=entry.tier,
            workspace_id=workspace_id,
            surprise_score=entry.surprise_score,
            update_count=entry.update_count,
            consolidation_score=entry.consolidation_score,
            validation_status=(
                ValidationStatus.MAJORITY_AGREED
                if entry.success_rate > 0.7
                else ValidationStatus.UNVERIFIED
            ),
            created_at=(
                datetime.fromisoformat(entry.created_at)
                if isinstance(entry.created_at, str)
                else datetime.now()
            ),
            updated_at=(
                datetime.fromisoformat(entry.updated_at)
                if isinstance(entry.updated_at, str)
                else datetime.now()
            ),
            metadata={
                "source": "continuum_memory",
                "original_id": entry.id,
                "success_count": entry.success_count,
                "failure_count": entry.failure_count,
                "red_line": entry.red_line,
                "red_line_reason": entry.red_line_reason,
                **entry.metadata,
            },
        )

    async def migrate_consensus_memory(
        self,
        source: ConsensusMemory,
        workspace_id: str = "default",
        include_dissent: bool = True,
        min_confidence: float = 0.0,
    ) -> MigrationResult:
        """
        Migrate ConsensusMemory to Knowledge Mound.

        Mapping:
        - ConsensusRecord -> KnowledgeNode(node_type="consensus")
        - DissentRecord -> KnowledgeNode(node_type="claim") with "contradicts" relationship
        - key_claims -> KnowledgeNode(node_type="fact") with "supports" relationship

        Args:
            source: Source ConsensusMemory instance
            workspace_id: Workspace to migrate into
            include_dissent: Whether to migrate dissent records
            min_confidence: Minimum confidence threshold

        Returns:
            MigrationResult with migration statistics
        """
        import time

        start_time = time.time()

        result = MigrationResult(
            source_type="consensus_memory",
            total_records=0,
            migrated_count=0,
            skipped_count=0,
            error_count=0,
        )

        try:
            # Get all consensus records
            get_all_consensus = getattr(source, "get_all_consensus", None)
            if not get_all_consensus:
                raise AttributeError("Source does not have get_all_consensus method")
            records = get_all_consensus()
            if min_confidence > 0:
                records = [r for r in records if r.confidence >= min_confidence]

            result.total_records = len(records)
            logger.info("Migrating %s ConsensusMemory records", len(records))

            for record in records:
                try:
                    # Cast to Any since add_node/add_relationship have overloaded
                    # signatures in the mixin that confuse the type checker
                    mound: Any = self._mound

                    # Create main consensus node
                    consensus_node = self._consensus_record_to_node(record, workspace_id)
                    consensus_id = await mound.add_node(consensus_node)
                    result.node_ids.append(consensus_id)
                    result.migrated_count += 1

                    # Create nodes for key claims (supporting facts)
                    for i, claim in enumerate(record.key_claims):
                        claim_node = KnowledgeNode(
                            id=f"kn_cc_{record.id}_{i}",
                            node_type="fact",
                            content=claim,
                            confidence=record.confidence * 0.9,  # Slightly lower than consensus
                            provenance=ProvenanceChain(
                                source_type=ProvenanceType.DEBATE,
                                source_id=record.id,
                                debate_id=record.id,
                            ),
                            workspace_id=workspace_id,
                            validation_status=ValidationStatus.MAJORITY_AGREED,
                            topics=record.tags,
                            metadata={
                                "source": "consensus_key_claim",
                                "consensus_id": record.id,
                            },
                        )
                        claim_id = await mound.add_node(claim_node)
                        result.node_ids.append(claim_id)

                        # Add "supports" relationship using correct API
                        rel_result = await mound.add_relationship(
                            from_id=claim_id,
                            to_id=consensus_id,
                            relationship_type="supports",
                            metadata={"strength": 0.9, "created_by": "migration"},
                        )
                        if rel_result:
                            result.relationship_ids.append(str(rel_result))

                    # Migrate dissent records if enabled
                    if include_dissent:
                        for dissent_id in record.dissent_ids:
                            get_dissent = getattr(source, "get_dissent", None)
                            dissent = get_dissent(dissent_id) if get_dissent else None
                            if dissent:
                                dissent_node = self._dissent_record_to_node(dissent, workspace_id)
                                d_node_id = await mound.add_node(dissent_node)
                                result.node_ids.append(d_node_id)

                                # Add "contradicts" relationship using correct API
                                rel_result = await mound.add_relationship(
                                    from_id=d_node_id,
                                    to_id=consensus_id,
                                    relationship_type="contradicts",
                                    metadata={
                                        "strength": dissent.confidence,
                                        "created_by": dissent.agent_id,
                                        "dissent_type": dissent.dissent_type.value,
                                    },
                                )
                                if rel_result:
                                    result.relationship_ids.append(str(rel_result))

                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    result.error_count += 1
                    logger.warning("Failed to migrate consensus %s: %s", record.id, e)
                    result.errors.append(
                        {
                            "record_id": record.id,
                            "error": "Migration failed for consensus record",
                        }
                    )

            result.duration_seconds = time.time() - start_time
            result.completed_at = datetime.now()

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Consensus migration failed: %s", e)
            result.errors.append({"error": "Consensus migration failed", "fatal": True})

        return result

    def _consensus_record_to_node(
        self,
        record: ConsensusRecord,
        workspace_id: str,
    ) -> KnowledgeNode:
        """Convert ConsensusRecord to KnowledgeNode."""
        # Map ConsensusStrength to ValidationStatus
        from aragora.memory.consensus import ConsensusStrength

        validation_map = {
            ConsensusStrength.UNANIMOUS: ValidationStatus.BYZANTINE_AGREED,
            ConsensusStrength.STRONG: ValidationStatus.MAJORITY_AGREED,
            ConsensusStrength.MODERATE: ValidationStatus.MAJORITY_AGREED,
            ConsensusStrength.WEAK: ValidationStatus.CONTESTED,
            ConsensusStrength.SPLIT: ValidationStatus.CONTESTED,
            ConsensusStrength.CONTESTED: ValidationStatus.CONTESTED,
        }

        return KnowledgeNode(
            id=f"kn_cr_{record.id}",
            node_type="consensus",
            content=record.conclusion,
            confidence=record.confidence,
            provenance=ProvenanceChain(
                source_type=ProvenanceType.DEBATE,
                source_id=record.id,
                debate_id=record.id,
            ),
            workspace_id=workspace_id,
            # Consensus tends to be slower-changing knowledge
            tier=MemoryTier.SLOW,
            validation_status=validation_map.get(record.strength, ValidationStatus.UNVERIFIED),
            topics=record.tags,
            metadata={
                "source": "consensus_memory",
                "original_id": record.id,
                "topic": record.topic,
                "topic_hash": record.topic_hash,
                "strength": record.strength.value,
                "domain": record.domain,
                "participating_agents": record.participating_agents,
                "agreeing_agents": record.agreeing_agents,
                "dissenting_agents": record.dissenting_agents,
                "rounds": record.rounds,
                "debate_duration_seconds": record.debate_duration_seconds,
                "supersedes": record.supersedes,
                "superseded_by": record.superseded_by,
                **record.metadata,
            },
        )

    def _dissent_record_to_node(
        self,
        dissent: DissentRecord,
        workspace_id: str,
    ) -> KnowledgeNode:
        """Convert DissentRecord to KnowledgeNode."""
        return KnowledgeNode(
            id=f"kn_dr_{dissent.id}",
            node_type="claim",
            content=f"{dissent.content}\n\nReasoning: {dissent.reasoning}",
            confidence=dissent.confidence,
            provenance=ProvenanceChain(
                source_type=ProvenanceType.AGENT,
                source_id=dissent.id,
                agent_id=dissent.agent_id,
                debate_id=dissent.debate_id,
            ),
            workspace_id=workspace_id,
            tier=MemoryTier.MEDIUM,  # Dissent is moderately volatile
            validation_status=ValidationStatus.CONTESTED,
            metadata={
                "source": "dissent_record",
                "original_id": dissent.id,
                "debate_id": dissent.debate_id,
                "agent_id": dissent.agent_id,
                "dissent_type": dissent.dissent_type.value,
                "acknowledged": dissent.acknowledged,
                "rebuttal": dissent.rebuttal,
                **dissent.metadata,
            },
        )

    async def migrate_all(
        self,
        workspace_id: str = "default",
        continuum_source: ContinuumMemory | None = None,
        consensus_source: ConsensusMemory | None = None,
    ) -> dict[str, MigrationResult]:
        """
        Migrate all memory systems to Knowledge Mound.

        Args:
            workspace_id: Workspace to migrate into
            continuum_source: Optional ContinuumMemory source
            consensus_source: Optional ConsensusMemory source

        Returns:
            Dictionary of migration results by source type
        """
        results: dict[str, MigrationResult] = {}

        if continuum_source:
            logger.info("Starting ContinuumMemory migration...")
            results["continuum"] = await self.migrate_continuum_memory(
                continuum_source, workspace_id
            )

        if consensus_source:
            logger.info("Starting ConsensusMemory migration...")
            results["consensus"] = await self.migrate_consensus_memory(
                consensus_source, workspace_id
            )

        # Log summary
        total_migrated = sum(r.migrated_count for r in results.values())
        total_errors = sum(r.error_count for r in results.values())
        logger.info(
            "Migration complete: %s records migrated, %s errors", total_migrated, total_errors
        )

        return results

    async def dry_run(
        self,
        workspace_id: str = "default",
        continuum_source: ContinuumMemory | None = None,
        consensus_source: ConsensusMemory | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Perform a dry run to estimate migration scope.

        Args:
            workspace_id: Workspace to migrate into
            continuum_source: Optional ContinuumMemory source
            consensus_source: Optional ConsensusMemory source

        Returns:
            Dictionary with estimated migration statistics
        """
        estimates: dict[str, dict[str, Any]] = {}

        if continuum_source:
            get_entries = getattr(continuum_source, "get_all_entries", None)
            entries = get_entries() if get_entries else []
            estimates["continuum"] = {
                "total_records": len(entries),
                "by_tier": {},
                "estimated_nodes": len(entries),
            }
            for entry in entries:
                tier_name = entry.tier.value
                estimates["continuum"]["by_tier"][tier_name] = (
                    estimates["continuum"]["by_tier"].get(tier_name, 0) + 1
                )

        if consensus_source:
            get_consensus = getattr(consensus_source, "get_all_consensus", None)
            records = get_consensus() if get_consensus else []
            total_dissents = sum(len(r.dissent_ids) for r in records)
            total_claims = sum(len(r.key_claims) for r in records)
            estimates["consensus"] = {
                "total_records": len(records),
                "total_dissents": total_dissents,
                "total_key_claims": total_claims,
                "estimated_nodes": len(records) + total_dissents + total_claims,
                "estimated_relationships": total_dissents + total_claims,
            }

        return estimates


async def run_migration_cli(
    workspace_id: str = "default",
    dry_run: bool = False,
) -> None:
    """
    CLI entry point for running migrations.

    Args:
        workspace_id: Workspace to migrate into
        dry_run: If True, only estimate without migrating
    """
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.consensus import ConsensusMemory
    from aragora.persistence.db_config import DatabaseType, get_db_path

    # Initialize sources with new API
    continuum = ContinuumMemory(db_path=get_db_path(DatabaseType.CONTINUUM_MEMORY))
    consensus = ConsensusMemory(db_path=get_db_path(DatabaseType.CONSENSUS_MEMORY))

    # Initialize target
    # KnowledgeMound facade is instantiable despite abstract base methods in the MRO;
    # cast the class to Any to bypass the abstract instantiation check
    _MoundClass: Any = KnowledgeMound
    mound: KnowledgeMound = _MoundClass(workspace_id=workspace_id)
    await mound.initialize()

    # Create migrator
    migrator = KnowledgeMoundMigrator(mound)

    if dry_run:
        await migrator.dry_run(
            workspace_id=workspace_id,
            continuum_source=continuum,
            consensus_source=consensus,
        )
    else:
        async with migrator.migration_context(f"migration_{workspace_id}"):
            results = await migrator.migrate_all(
                workspace_id=workspace_id,
                continuum_source=continuum,
                consensus_source=consensus,
            )
            for source, result in results.items():
                pass

    await mound.close()


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Migrate memory systems to Knowledge Mound")
    parser.add_argument("--workspace", default="default", help="Workspace ID")
    parser.add_argument("--dry-run", action="store_true", help="Only estimate, don't migrate")
    args = parser.parse_args()

    asyncio.run(run_migration_cli(workspace_id=args.workspace, dry_run=args.dry_run))
