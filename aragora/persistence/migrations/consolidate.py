"""
Database Consolidation Migration Script for Aragora.

Migrates data from 32 legacy SQLite databases to 4 consolidated databases:
- core.db: debates, traces, tournaments, embeddings, positions
- memory.db: continuum, agent_memories, consensus, critiques, patterns
- analytics.db: elo, calibration, insights, prompt_evolution, meta_learning
- agents.db: personas, relationships, laboratory, genesis

Usage:
    # Dry run (show what would be migrated)
    python -m aragora.persistence.migrations.consolidate --dry-run

    # Execute migration
    python -m aragora.persistence.migrations.consolidate --migrate

    # Specify custom directories
    python -m aragora.persistence.migrations.consolidate --migrate \
        --source .nomic --target .nomic/consolidated

    # Verify migration
    python -m aragora.persistence.migrations.consolidate --verify
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)


class TableConfig(TypedDict, total=False):
    """Configuration for a single table migration."""

    target_table: str
    columns: list[str]
    transform: Callable[..., Any] | None


class MigrationConfig(TypedDict):
    """Configuration for a database migration."""

    target: str
    tables: dict[str, TableConfig]


# Schema files
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


@dataclass
class MigrationStats:
    """Statistics for a single table migration."""

    table_name: str
    source_db: str
    target_db: str
    rows_read: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ConsolidationResult:
    """Result of the consolidation migration."""

    success: bool
    tables_migrated: int
    total_rows: int
    duration_seconds: float
    stats: list[MigrationStats]
    errors: list[str]

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "tables_migrated": self.tables_migrated,
            "total_rows": self.total_rows,
            "duration_seconds": round(self.duration_seconds, 2),
            "stats": [
                {
                    "table": s.table_name,
                    "source": s.source_db,
                    "target": s.target_db,
                    "read": s.rows_read,
                    "written": s.rows_written,
                    "skipped": s.rows_skipped,
                    "errors": len(s.errors),
                }
                for s in self.stats
            ],
            "errors": self.errors[:10],  # Limit to first 10 errors
        }


# Mapping of legacy databases to their tables and target consolidated database
MIGRATION_MAP: dict[str, MigrationConfig] = {
    # =========================================================================
    # CORE.DB
    # =========================================================================
    "debates.db": {
        "target": "core.db",
        "tables": {
            "debates": {
                "target_table": "debates",
                "columns": [
                    "id",
                    "slug",
                    "task",
                    "agents",
                    "artifact_json",
                    "consensus_reached",
                    "confidence",
                    "view_count",
                    "audio_path",
                    "audio_generated_at",
                    "audio_duration_seconds",
                    "created_at",
                ],
            },
        },
    },
    "aragora_debates.db": {
        "target": "core.db",
        "tables": {
            "debate_metadata": {
                "target_table": "debate_metadata",
                "columns": ["debate_id", "config_hash", "task_hash", "metadata_json", "created_at"],
            },
        },
    },
    "traces.db": {
        "target": "core.db",
        "tables": {
            "traces": {
                "target_table": "traces",
                "columns": [
                    "trace_id",
                    "debate_id",
                    "task",
                    "agents",
                    "random_seed",
                    "checksum",
                    "trace_json",
                    "started_at",
                    "completed_at",
                ],
            },
            "trace_events": {
                "target_table": "trace_events",
                "columns": [
                    "event_id",
                    "trace_id",
                    "event_type",
                    "round_num",
                    "agent",
                    "content",
                    "timestamp",
                ],
            },
        },
    },
    "tournaments.db": {
        "target": "core.db",
        "tables": {
            "tournaments": {
                "target_table": "tournaments",
                "columns": [
                    "tournament_id",
                    "name",
                    "format",
                    "agents",
                    "tasks",
                    "standings",
                    "champion",
                    "started_at",
                    "completed_at",
                ],
            },
            "tournament_matches": {
                "target_table": "tournament_matches",
                "columns": [
                    "match_id",
                    "tournament_id",
                    "round_num",
                    "participants",
                    "task_id",
                    "scores",
                    "winner",
                    "started_at",
                    "completed_at",
                ],
            },
        },
    },
    "debate_embeddings.db": {
        "target": "core.db",
        "tables": {
            "embeddings": {
                "target_table": "embeddings",
                "columns": ["id", "text_hash", "text", "embedding", "provider", "created_at"],
            },
        },
    },
    "grounded_positions.db": {
        "target": "core.db",
        "tables": {
            "positions": {
                "target_table": "positions",
                "columns": [
                    "id",
                    "agent_name",
                    "claim",
                    "confidence",
                    "debate_id",
                    "round_num",
                    "outcome",
                    "reversed",
                    "reversal_debate_id",
                    "domain",
                    "created_at",
                    "resolved_at",
                ],
            },
            "detected_flips": {
                "target_table": "detected_flips",
                "columns": [
                    "id",
                    "agent_name",
                    "original_claim",
                    "new_claim",
                    "original_confidence",
                    "new_confidence",
                    "original_debate_id",
                    "new_debate_id",
                    "original_position_id",
                    "new_position_id",
                    "similarity_score",
                    "flip_type",
                    "domain",
                    "detected_at",
                ],
            },
        },
    },
    # =========================================================================
    # MEMORY.DB
    # =========================================================================
    "continuum.db": {
        "target": "memory.db",
        "tables": {
            "memories": cast(
                TableConfig,
                {
                    "target_table": "continuum_memory",
                    "columns": [
                        "id",
                        "tier",
                        "content",
                        "importance",
                        "surprise_score",
                        "consolidation_score",
                        "update_count",
                        "success_count",
                        "failure_count",
                        "semantic_centroid",
                        "last_promotion_at",
                        "expires_at",
                        "metadata",
                        "created_at",
                        "updated_at",
                    ],
                    # string method name resolved via getattr at runtime
                    "transform": "_transform_continuum_memory",
                },
            ),
            "tier_transitions": {
                "target_table": "tier_transitions",
                "columns": [
                    "id",
                    "memory_id",
                    "from_tier",
                    "to_tier",
                    "reason",
                    "surprise_score",
                    "created_at",
                ],
            },
            "archive": {
                "target_table": "continuum_memory_archive",
                "columns": [
                    "id",
                    "tier",
                    "content",
                    "importance",
                    "surprise_score",
                    "consolidation_score",
                    "update_count",
                    "success_count",
                    "failure_count",
                    "semantic_centroid",
                    "created_at",
                    "updated_at",
                    "archived_at",
                    "archive_reason",
                    "metadata",
                ],
            },
            "meta_learning_state": {
                "target_table": "meta_learning_state",
                "columns": [
                    "id",
                    "hyperparams",
                    "learning_efficiency",
                    "pattern_retention_rate",
                    "forgetting_rate",
                    "cycles_evaluated",
                    "created_at",
                ],
            },
        },
    },
    "agent_memories.db": {
        "target": "memory.db",
        "tables": {
            "memories": {
                "target_table": "memories",
                "columns": [
                    "id",
                    "agent_name",
                    "memory_type",
                    "content",
                    "context",
                    "importance",
                    "decay_rate",
                    "embedding",
                    "debate_id",
                    "created_at",
                    "expires_at",
                ],
            },
            "reflection_schedule": {
                "target_table": "reflection_schedule",
                "columns": [
                    "id",
                    "agent_name",
                    "reflection_type",
                    "scheduled_for",
                    "completed_at",
                    "memory_ids",
                    "result",
                    "created_at",
                ],
            },
        },
    },
    "consensus_memory.db": {
        "target": "memory.db",
        "tables": {
            "consensus": {
                "target_table": "consensus",
                "columns": [
                    "id",
                    "topic",
                    "topic_hash",
                    "conclusion",
                    "strength",
                    "confidence",
                    "domain",
                    "tags",
                    "timestamp",
                    "data",
                    "supporting_agents",
                    "opposing_agents",
                    "evidence",
                    "debate_ids",
                    "stability_score",
                    "last_challenged_at",
                    "created_at",
                    "updated_at",
                ],
            },
            "dissent": {
                "target_table": "dissent",
                "columns": [
                    "id",
                    "debate_id",
                    "agent_id",
                    "dissent_type",
                    "content",
                    "confidence",
                    "timestamp",
                    "data",
                    "reasoning",
                    "strength",
                    "resolved",
                    "resolved_at",
                    "created_at",
                ],
            },
        },
    },
    "agora_memory.db": {
        "target": "memory.db",
        "tables": {
            "debates": {
                "target_table": "debates",
                "columns": [
                    "id",
                    "task",
                    "final_answer",
                    "consensus_reached",
                    "confidence",
                    "rounds_used",
                    "duration_seconds",
                    "created_at",
                ],
            },
            "critiques": {
                "target_table": "critiques",
                "columns": [
                    "id",
                    "debate_id",
                    "agent",
                    "target_agent",
                    "issues",
                    "suggestions",
                    "severity",
                    "reasoning",
                    "led_to_improvement",
                    "expected_usefulness",
                    "actual_usefulness",
                    "prediction_error",
                    "created_at",
                ],
            },
            "patterns": {
                "target_table": "patterns",
                "columns": [
                    "id",
                    "issue_type",
                    "issue_text",
                    "suggestion_text",
                    "success_count",
                    "failure_count",
                    "avg_severity",
                    "surprise_score",
                    "base_rate",
                    "avg_prediction_error",
                    "prediction_count",
                    "example_task",
                    "created_at",
                    "updated_at",
                ],
            },
            "patterns_archive": {
                "target_table": "patterns_archive",
                "columns": [
                    "id",
                    "issue_type",
                    "issue_text",
                    "suggestion_text",
                    "success_count",
                    "failure_count",
                    "avg_severity",
                    "surprise_score",
                    "example_task",
                    "created_at",
                    "updated_at",
                    "archived_at",
                ],
            },
            "pattern_embeddings": {
                "target_table": "pattern_embeddings",
                "columns": ["pattern_id", "embedding"],
            },
            "agent_reputation": {
                "target_table": "agent_reputation",
                "columns": [
                    "agent_name",
                    "proposals_made",
                    "proposals_accepted",
                    "critiques_given",
                    "critiques_valuable",
                    "total_predictions",
                    "total_prediction_error",
                    "calibration_score",
                    "updated_at",
                ],
            },
        },
    },
    "semantic_patterns.db": {
        "target": "memory.db",
        "tables": {
            "embeddings": {
                "target_table": "semantic_embeddings",
                "columns": ["id", "text_hash", "text", "embedding", "provider", "created_at"],
            },
        },
    },
    "suggestion_feedback.db": {
        "target": "memory.db",
        "tables": {
            "suggestion_injections": {
                "target_table": "suggestion_injections",
                "columns": [
                    "id",
                    "debate_id",
                    "user_id",
                    "suggestion_type",
                    "content",
                    "target_agent",
                    "accepted",
                    "impact_score",
                    "created_at",
                ],
            },
            "contributor_stats": {
                "target_table": "contributor_stats",
                "columns": [
                    "user_id",
                    "suggestions_total",
                    "suggestions_accepted",
                    "acceptance_rate",
                    "impact_score_sum",
                    "last_contribution_at",
                    "created_at",
                    "updated_at",
                ],
            },
        },
    },
    # =========================================================================
    # ANALYTICS.DB
    # =========================================================================
    "agent_elo.db": {
        "target": "analytics.db",
        "tables": {
            "ratings": {
                "target_table": "ratings",
                "columns": [
                    "agent_name",
                    "elo",
                    "domain_elos",
                    "wins",
                    "losses",
                    "draws",
                    "debates_count",
                    "critiques_accepted",
                    "critiques_total",
                    "calibration_correct",
                    "calibration_total",
                    "calibration_brier_sum",
                    "updated_at",
                ],
            },
            "matches": {
                "target_table": "matches",
                "columns": [
                    "id",
                    "debate_id",
                    "winner",
                    "participants",
                    "domain",
                    "scores",
                    "elo_changes",
                    "created_at",
                ],
            },
            "elo_history": {
                "target_table": "elo_history",
                "columns": ["id", "agent_name", "elo", "debate_id", "created_at"],
            },
            "calibration_predictions": {
                "target_table": "calibration_predictions",
                "columns": [
                    "id",
                    "tournament_id",
                    "predictor_agent",
                    "predicted_winner",
                    "confidence",
                    "actual_winner",
                    "resolved_at",
                    "created_at",
                ],
            },
        },
    },
    "agent_calibration.db": {
        "target": "analytics.db",
        "tables": {
            "domain_calibration": {
                "target_table": "domain_calibration",
                "columns": [
                    "agent_name",
                    "domain",
                    "total_predictions",
                    "total_correct",
                    "brier_sum",
                    "updated_at",
                ],
            },
            "calibration_buckets": {
                "target_table": "calibration_buckets",
                "columns": [
                    "agent_name",
                    "domain",
                    "bucket_key",
                    "predictions",
                    "correct",
                    "brier_sum",
                ],
            },
            "predictions": {
                "target_table": "predictions",
                "columns": [
                    "id",
                    "agent",
                    "domain",
                    "predicted",
                    "actual",
                    "bucket",
                    "timestamp",
                ],
            },
            "temperature_params": {
                "target_table": "temperature_params",
                "columns": [
                    "agent",
                    "temperature",
                    "domain_temperatures",
                    "last_tuned",
                    "predictions_at_tune",
                ],
            },
        },
    },
    "aragora_insights.db": {
        "target": "analytics.db",
        "tables": {
            "insights": {
                "target_table": "insights",
                "columns": [
                    "id",
                    "type",
                    "title",
                    "description",
                    "confidence",
                    "debate_id",
                    "agents_involved",
                    "evidence",
                    "metadata",
                    "created_at",
                ],
            },
            "debate_summaries": {
                "target_table": "debate_summaries",
                "columns": [
                    "debate_id",
                    "topic",
                    "summary",
                    "key_arguments",
                    "consensus_reached",
                    "final_positions",
                    "duration_seconds",
                    "rounds_completed",
                    "created_at",
                ],
            },
            "pattern_clusters": {
                "target_table": "pattern_clusters",
                "columns": [
                    "id",
                    "cluster_name",
                    "pattern_type",
                    "centroid",
                    "member_count",
                    "sample_patterns",
                    "created_at",
                    "updated_at",
                ],
            },
            "agent_performance_history": {
                "target_table": "agent_performance_history",
                "columns": [
                    "id",
                    "agent_name",
                    "metric_name",
                    "metric_value",
                    "period",
                    "period_start",
                    "period_end",
                    "sample_size",
                    "created_at",
                ],
            },
        },
    },
    "prompt_evolution.db": {
        "target": "analytics.db",
        "tables": {
            "prompt_versions": {
                "target_table": "prompt_versions",
                "columns": [
                    "id",
                    "prompt_name",
                    "version",
                    "content",
                    "parent_version",
                    "fitness_score",
                    "usage_count",
                    "success_rate",
                    "metadata",
                    "created_at",
                ],
            },
            "evolution_history": {
                "target_table": "evolution_history",
                "columns": [
                    "id",
                    "prompt_name",
                    "from_version",
                    "to_version",
                    "mutation_type",
                    "fitness_delta",
                    "created_at",
                ],
            },
            "extracted_patterns": {
                "target_table": "extracted_patterns",
                "columns": [
                    "id",
                    "source_type",
                    "source_id",
                    "pattern_text",
                    "pattern_type",
                    "frequency",
                    "effectiveness_score",
                    "embedding",
                    "created_at",
                ],
            },
        },
    },
    "meta_learning.db": {
        "target": "analytics.db",
        "tables": {
            "meta_hyperparams": {
                "target_table": "meta_hyperparams",
                "columns": [
                    "id",
                    "param_name",
                    "param_value",
                    "context",
                    "effectiveness",
                    "sample_size",
                    "created_at",
                    "updated_at",
                ],
            },
            "meta_efficiency_log": {
                "target_table": "meta_efficiency_log",
                "columns": [
                    "id",
                    "cycle_id",
                    "learning_rate",
                    "pattern_retention_rate",
                    "forgetting_rate",
                    "convergence_speed",
                    "hyperparams_snapshot",
                    "created_at",
                ],
            },
        },
    },
    # =========================================================================
    # AGENTS.DB
    # =========================================================================
    "agent_personas.db": {
        "target": "agents.db",
        "tables": {
            "personas": {
                "target_table": "personas",
                "columns": [
                    "agent_name",
                    "description",
                    "traits",
                    "expertise",
                    "created_at",
                    "updated_at",
                ],
            },
            "performance_history": {
                "target_table": "performance_history",
                "columns": [
                    "id",
                    "agent_name",
                    "debate_id",
                    "domain",
                    "action",
                    "success",
                    "created_at",
                ],
            },
        },
    },
    "agent_relationships.db": {
        "target": "agents.db",
        "tables": {
            "relationships": {
                "target_table": "agent_relationships",
                "columns": [
                    "agent_a",
                    "agent_b",
                    "debate_count",
                    "agreement_count",
                    "critique_count_a_to_b",
                    "critique_count_b_to_a",
                    "critique_accepted_a_to_b",
                    "critique_accepted_b_to_a",
                    "position_changes_a_after_b",
                    "position_changes_b_after_a",
                    "a_wins_over_b",
                    "b_wins_over_a",
                    "updated_at",
                ],
            },
        },
    },
    "aragora_positions.db": {
        "target": "agents.db",
        "tables": {
            "position_history": {
                "target_table": "position_history",
                "columns": [
                    "id",
                    "debate_id",
                    "agent_name",
                    "position_type",
                    "position_text",
                    "round_num",
                    "confidence",
                    "was_winning_position",
                    "verified_correct",
                    "created_at",
                ],
            },
            "debate_outcomes": {
                "target_table": "debate_outcomes",
                "columns": [
                    "debate_id",
                    "winning_agent",
                    "winning_position",
                    "consensus_confidence",
                    "verified_at",
                    "verification_result",
                    "verification_source",
                    "created_at",
                ],
            },
        },
    },
    "persona_lab.db": {
        "target": "agents.db",
        "tables": {
            "experiments": {
                "target_table": "experiments",
                "columns": [
                    "experiment_id",
                    "agent_name",
                    "control_persona",
                    "variant_persona",
                    "hypothesis",
                    "status",
                    "control_successes",
                    "control_trials",
                    "variant_successes",
                    "variant_trials",
                    "created_at",
                    "completed_at",
                ],
            },
            "emergent_traits": {
                "target_table": "emergent_traits",
                "columns": [
                    "id",
                    "trait_name",
                    "source_agents",
                    "supporting_evidence",
                    "confidence",
                    "first_detected",
                ],
            },
            "trait_transfers": {
                "target_table": "trait_transfers",
                "columns": [
                    "id",
                    "from_agent",
                    "to_agent",
                    "trait",
                    "expertise_domain",
                    "success_rate_before",
                    "success_rate_after",
                    "transferred_at",
                ],
            },
            "agent_evolution_history": {
                "target_table": "agent_evolution_history",
                "columns": [
                    "id",
                    "agent_name",
                    "mutation_type",
                    "before_state",
                    "after_state",
                    "reason",
                    "created_at",
                ],
            },
        },
    },
    "genesis.db": {
        "target": "agents.db",
        "tables": {
            "genomes": {
                "target_table": "genomes",
                "columns": [
                    "genome_id",
                    "name",
                    "traits",
                    "expertise",
                    "model_preference",
                    "parent_genomes",
                    "generation",
                    "fitness_score",
                    "birth_debate_id",
                    "consensus_contributions",
                    "critiques_accepted",
                    "predictions_correct",
                    "debates_participated",
                    "created_at",
                    "updated_at",
                ],
            },
            "populations": {
                "target_table": "populations",
                "columns": [
                    "population_id",
                    "genome_ids",
                    "generation",
                    "debate_history",
                    "created_at",
                ],
            },
            "active_population": {
                "target_table": "active_population",
                "columns": ["id", "population_id"],
            },
            "genesis_events": {
                "target_table": "genesis_events",
                "columns": [
                    "event_id",
                    "event_type",
                    "timestamp",
                    "parent_event_id",
                    "content_hash",
                    "data",
                ],
            },
        },
    },
}


class DatabaseConsolidator:
    """Handles migration from legacy databases to consolidated schema."""

    def __init__(
        self,
        source_dir: Path,
        target_dir: Path | None = None,
        backup: bool = True,
    ):
        """
        Initialize the consolidator.

        Args:
            source_dir: Directory containing legacy databases
            target_dir: Directory for consolidated databases (default: source_dir)
            backup: Whether to create backups before migration
        """
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir) if target_dir else self.source_dir
        self.backup = backup
        self.stats: list[MigrationStats] = []
        self.errors: list[str] = []

    def _get_connection(self, db_path: Path) -> sqlite3.Connection | None:
        """Get a database connection with WAL mode."""
        if not db_path.exists():
            return None

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _create_target_db(self, db_name: str) -> sqlite3.Connection:
        """Create or open a target consolidated database."""
        db_path = self.target_dir / db_name
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

        # Apply schema
        schema_name = db_name.replace(".db", ".sql")
        schema_path = SCHEMAS_DIR / schema_name
        if schema_path.exists():
            schema_sql = schema_path.read_text()
            conn.executescript(schema_sql)
            conn.commit()
        else:
            logger.warning("No schema found for %s at %s", db_name, schema_path)

        return conn

    def _backup_databases(self) -> bool:
        """Create backups of all databases."""
        backup_dir = self.source_dir / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)

        for db_file in self.source_dir.glob("*.db"):
            try:
                shutil.copy2(db_file, backup_dir / db_file.name)
                logger.info("Backed up: %s", db_file.name)
            except (OSError, RuntimeError) as e:
                self.errors.append(f"Backup failed for {db_file.name}: {e}")
                return False

        logger.info("Backups created in: %s", backup_dir)
        return True

    def _get_source_columns(
        self,
        conn: sqlite3.Connection,
        table_name: str,
    ) -> list[str]:
        """Get column names from a source table."""
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        return [row["name"] for row in cursor.fetchall()]

    def _migrate_table(
        self,
        source_conn: sqlite3.Connection,
        target_conn: sqlite3.Connection,
        source_table: str,
        target_table: str,
        columns: list[str],
        source_db: str,
        target_db: str,
        transform: Callable | None = None,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Migrate a single table."""
        stats = MigrationStats(
            table_name=source_table,
            source_db=source_db,
            target_db=target_db,
        )

        try:
            # Get available columns in source
            source_columns = self._get_source_columns(source_conn, source_table)
            if not source_columns:
                stats.errors.append(f"Table {source_table} not found in source")
                return stats

            # Filter to columns that exist in both source and target
            available_columns = [c for c in columns if c in source_columns]
            if not available_columns:
                stats.errors.append(f"No matching columns for {source_table}")
                return stats

            # Read source data
            col_list = ", ".join(available_columns)
            cursor = source_conn.execute(f"SELECT {col_list} FROM {source_table}")  # noqa: S608 -- table/column name interpolation, parameterized
            rows = cursor.fetchall()
            stats.rows_read = len(rows)

            if dry_run:
                return stats

            # Write to target
            placeholders = ", ".join("?" * len(available_columns))
            insert_sql = f"""
                INSERT OR IGNORE INTO {target_table} ({col_list})
                VALUES ({placeholders})
            """  # noqa: S608 -- table name interpolation, parameterized

            for row in rows:
                try:
                    values = [row[c] for c in available_columns]
                    if transform:
                        values = transform(values, available_columns)
                    target_conn.execute(insert_sql, values)
                    stats.rows_written += 1
                except sqlite3.IntegrityError:
                    stats.rows_skipped += 1
                except (OSError, RuntimeError, ValueError) as e:
                    stats.errors.append(f"Row error: {e}")
                    stats.rows_skipped += 1

            target_conn.commit()

        except (OSError, RuntimeError, ValueError) as e:
            stats.errors.append(f"Table migration error: {e}")

        return stats

    def migrate(self, dry_run: bool = False) -> ConsolidationResult:
        """
        Execute the database consolidation migration.

        Args:
            dry_run: If True, only show what would be migrated

        Returns:
            ConsolidationResult with migration statistics
        """
        import time

        start_time = time.time()

        # Backup first
        if self.backup and not dry_run:
            if not self._backup_databases():
                return ConsolidationResult(
                    success=False,
                    tables_migrated=0,
                    total_rows=0,
                    duration_seconds=time.time() - start_time,
                    stats=[],
                    errors=self.errors,
                )

        # Track target connections
        target_conns: dict[str, sqlite3.Connection | None] = {}

        try:
            for source_db_name, config in MIGRATION_MAP.items():
                source_path = self.source_dir / source_db_name
                if not source_path.exists():
                    logger.debug("Skipping missing source: %s", source_db_name)
                    continue

                source_conn = self._get_connection(source_path)
                if not source_conn:
                    continue

                target_db_name = config["target"]

                # Get or create target connection
                if target_db_name not in target_conns:
                    if not dry_run:
                        target_conns[target_db_name] = self._create_target_db(target_db_name)
                    else:
                        # For dry run, just track stats without writing
                        target_conns[target_db_name] = None

                target_conn = target_conns[target_db_name]

                # Migrate each table
                for source_table, table_config in config["tables"].items():
                    target_table = table_config["target_table"]
                    columns = table_config["columns"]

                    logger.info(
                        "%sMigrating %s:%s -> %s:%s",
                        "[DRY RUN] " if dry_run else "",
                        source_db_name,
                        source_table,
                        target_db_name,
                        target_table,
                    )

                    if dry_run:
                        # Just count rows for dry run
                        try:
                            cursor = source_conn.execute(f"SELECT COUNT(*) FROM {source_table}")  # noqa: S608 -- table name interpolation, parameterized
                            count = cursor.fetchone()[0]
                            stats = MigrationStats(
                                table_name=source_table,
                                source_db=source_db_name,
                                target_db=target_db_name,
                                rows_read=count,
                            )
                            self.stats.append(stats)
                        except (OSError, RuntimeError, ValueError) as e:
                            logger.warning("Could not count %s: %s", source_table, e)
                    else:
                        if target_conn is None:
                            raise RuntimeError(f"Missing target connection for {target_db_name}")
                        stats = self._migrate_table(
                            source_conn=source_conn,
                            target_conn=target_conn,
                            source_table=source_table,
                            target_table=target_table,
                            columns=columns,
                            source_db=source_db_name,
                            target_db=target_db_name,
                            dry_run=dry_run,
                        )
                        self.stats.append(stats)

                        if stats.errors:
                            self.errors.extend(stats.errors)

                source_conn.close()

        finally:
            # Close all target connections
            for conn in target_conns.values():
                if conn:
                    conn.close()

        # Calculate totals
        tables_migrated = len([s for s in self.stats if s.rows_written > 0])
        total_rows = sum(s.rows_written for s in self.stats)
        duration = time.time() - start_time

        return ConsolidationResult(
            success=len(self.errors) == 0,
            tables_migrated=tables_migrated,
            total_rows=total_rows,
            duration_seconds=duration,
            stats=self.stats,
            errors=self.errors,
        )

    def verify(self) -> dict[str, Any]:
        """
        Verify the consolidated databases.

        Returns:
            Verification report with row counts and integrity checks
        """
        databases: dict[str, Any] = {}
        issues: list[str] = []

        for db_name in ["core.db", "memory.db", "analytics.db", "agents.db"]:
            db_path = self.target_dir / db_name
            if not db_path.exists():
                issues.append(f"Missing database: {db_name}")
                continue

            conn = self._get_connection(db_path)
            if not conn:
                continue

            try:
                db_tables: dict[str, int] = {}

                # Get all tables
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row["name"] for row in cursor.fetchall()]

                for table in tables:
                    if table.startswith("_"):
                        continue

                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 -- table name interpolation, parameterized
                    count = cursor.fetchone()[0]
                    db_tables[table] = count

                databases[db_name] = {"tables": db_tables, "size_bytes": db_path.stat().st_size}

            except (OSError, RuntimeError, ValueError) as e:
                issues.append(f"Error verifying {db_name}: {e}")
            finally:
                conn.close()

        return {
            "verified_at": datetime.now().isoformat(),
            "databases": databases,
            "issues": issues,
        }


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Consolidate Aragora databases from 32 to 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without executing",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Execute the consolidation migration",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify consolidated databases",
    )
    parser.add_argument(
        "--source",
        metavar="DIR",
        default=".nomic",
        help="Source directory containing legacy databases (default: .nomic)",
    )
    parser.add_argument(
        "--target",
        metavar="DIR",
        help="Target directory for consolidated databases (default: same as source)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation (not recommended)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    source_dir = Path(args.source)
    target_dir = Path(args.target) if args.target else None

    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        return 1

    consolidator = DatabaseConsolidator(
        source_dir=source_dir,
        target_dir=target_dir,
        backup=not args.no_backup,
    )

    if args.dry_run:
        print("\n=== DRY RUN: Database Consolidation ===\n")
        result = consolidator.migrate(dry_run=True)

        print(f"Source: {source_dir}")
        print(f"Target: {target_dir or source_dir}")
        print(f"\nTables to migrate: {len(result.stats)}")
        print(f"Total rows to migrate: {sum(s.rows_read for s in result.stats)}")

        print("\nMigration plan:")
        for stat in result.stats:
            print(
                f"  {stat.source_db}:{stat.table_name} -> {stat.target_db} ({stat.rows_read} rows)"
            )

        return 0

    if args.migrate:
        print("\n=== Executing Database Consolidation ===\n")
        result = consolidator.migrate(dry_run=False)

        print(f"\nMigration {'completed' if result.success else 'failed'}!")
        print(f"Tables migrated: {result.tables_migrated}")
        print(f"Total rows: {result.total_rows}")
        print(f"Duration: {result.duration_seconds:.2f}s")

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for error in result.errors[:10]:
                print(f"  - {error}")

        return 0 if result.success else 1

    if args.verify:
        print("\n=== Verifying Consolidated Databases ===\n")
        report = consolidator.verify()

        print(f"Verified at: {report['verified_at']}")

        for db_name, db_info in report["databases"].items():
            print(f"\n{db_name}:")
            print(f"  Size: {db_info['size_bytes'] / 1024:.1f} KB")
            print(f"  Tables: {len(db_info['tables'])}")
            for table, count in sorted(db_info["tables"].items()):
                print(f"    - {table}: {count} rows")

        if report["issues"]:
            print(f"\nIssues ({len(report['issues'])}):")
            for issue in report["issues"]:
                print(f"  - {issue}")
            return 1

        return 0

    # No command specified
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
