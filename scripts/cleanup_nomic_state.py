#!/usr/bin/env python3
"""
Cleanup script for the .nomic/ directory.

Safely removes obsolete data while preserving essential databases and recent backups.
Always run with --dry-run first to preview changes.

Usage:
    # Preview what would be deleted
    python scripts/cleanup_nomic_state.py --dry-run

    # Actually perform cleanup
    python scripts/cleanup_nomic_state.py

    # Customize retention
    python scripts/cleanup_nomic_state.py --backup-days 14 --session-days 3

    # Archive instead of delete
    python scripts/cleanup_nomic_state.py --archive-to /path/to/archive
"""

import argparse
import gzip
import json
import os
import shutil
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

# Essential databases that should never be deleted
ESSENTIAL_DATABASES = {
    # Core functionality
    "core.db",
    "memory.db",
    "agents.db",
    "analytics.db",
    "debates.db",
    # Agent systems
    "agent_elo.db",
    "agent_memories.db",
    "agent_calibration.db",
    "agent_personas.db",
    "agent_relationships.db",
    # Memory systems
    "continuum.db",
    "continuum_memory.db",
    "consensus_memory.db",
    # Aragora-specific
    "aragora_insights.db",
    "aragora_positions.db",
    "aragora_debates.db",
    "aragora_evolution_tracker.db",
    # Configuration
    "circuit_breaker.db",
    "genesis.db",
    # User data
    "users.db",
    "share_links.db",
    "scheduled_debates.db",
    "payment_recovery.db",
    "token_blacklist.db",
    "webhook_events.db",
    "usage.db",
}

# Directories that can be cleaned up
CLEANABLE_DIRECTORIES = {
    "backups",  # Nomic loop cycle backups
    "checkpoints",  # Debate checkpoints
    "sessions",  # Session telemetry data
    "root-artifacts",  # Timestamped artifacts
}

# Session directories that should be preserved
PRESERVED_SESSIONS = {
    "default_telemetry",  # Current active session
}

# File patterns that can be safely removed
CLEANABLE_FILE_PATTERNS = {
    "*.db-wal",  # WAL files (will be recreated)
    "*.db-shm",  # Shared memory files (will be recreated)
    "*.log",  # Old log files
}

# Files that are obsolete and can be removed
OBSOLETE_FILES = {
    "agora_memory.db",  # Superseded by agent_memories.db
    "elo.db",  # Superseded by agent_elo.db
    "personas.db",  # Superseded by agent_personas.db
    "aragora_personas.db",  # Duplicate
    "nomic_proposals.db",  # Historical, no longer used
    "position_ledger.db",  # Historical, no longer used
    "meta_learning.db",  # Historical, no longer used
    "debate_embeddings.db",  # Can be regenerated
    "semantic_patterns.db",  # Can be regenerated
    "grounded_positions.db",  # Historical, no longer used
    "prompt_evolution.db",  # Historical, no longer used
    "suggestion_feedback.db",  # Historical, no longer used
    "persona_lab.db",  # Historical, no longer used
}


@dataclass
class CleanupStats:
    """Statistics for cleanup operation."""

    files_removed: int = 0
    dirs_removed: int = 0
    bytes_freed: int = 0
    files_archived: int = 0
    bytes_archived: int = 0
    errors: list = field(default_factory=list)

    @property
    def freed_mb(self) -> float:
        return self.bytes_freed / (1024 * 1024)

    @property
    def archived_mb(self) -> float:
        return self.bytes_archived / (1024 * 1024)


def get_dir_age(path: Path) -> timedelta:
    """Get age of a directory based on its modification time."""
    mtime = path.stat().st_mtime
    return datetime.now() - datetime.fromtimestamp(mtime)


def get_dir_size(path: Path) -> int:
    """Get total size of a directory in bytes."""
    total = 0
    if path.is_file():
        return path.stat().st_size
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def parse_backup_timestamp(name: str) -> datetime | None:
    """Parse timestamp from backup directory name.

    Format: backup_cycle_N_YYYYMMDD_HHMMSS
    """
    try:
        parts = name.split("_")
        if len(parts) >= 4 and parts[0] == "backup":
            date_str = parts[-2]
            time_str = parts[-1]
            return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        pass
    return None


def parse_checkpoint_timestamp(name: str) -> datetime | None:
    """Parse timestamp from checkpoint filename.

    Format: cp-HEXID-NNN-HASH.json.gz (sorted by creation time)
    """
    # Checkpoints don't have embedded timestamps, use file mtime
    return None


def parse_artifact_timestamp(name: str) -> datetime | None:
    """Parse timestamp from artifact directory name.

    Format: YYYYMMDDTHHMMSSZ
    """
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%SZ")
    except ValueError:
        pass
    return None


def should_clean_backup(path: Path, max_age_days: int, keep_latest: int = 5) -> tuple[bool, str]:
    """Determine if a backup directory should be cleaned up."""
    timestamp = parse_backup_timestamp(path.name)
    if timestamp is None:
        return False, "Could not parse timestamp"

    age = datetime.now() - timestamp
    if age.days > max_age_days:
        return True, f"Age: {age.days} days (max: {max_age_days})"
    return False, f"Recent: {age.days} days old"


def should_clean_session(path: Path, max_age_days: int) -> tuple[bool, str]:
    """Determine if a session directory should be cleaned up."""
    if path.name in PRESERVED_SESSIONS:
        return False, "Preserved session"

    # Check if it's a test session (can be cleaned more aggressively)
    is_test = path.name.startswith("test_")

    age = get_dir_age(path)
    if is_test and age.days >= 1:
        return True, f"Test session, age: {age.days} days"
    if age.days > max_age_days:
        return True, f"Age: {age.days} days (max: {max_age_days})"
    return False, f"Recent: {age.days} days old"


def should_clean_checkpoint(path: Path, max_age_days: int) -> tuple[bool, str]:
    """Determine if a checkpoint file should be cleaned up."""
    age = get_dir_age(path)
    if age.days > max_age_days:
        return True, f"Age: {age.days} days (max: {max_age_days})"
    return False, f"Recent: {age.days} days old"


def should_clean_artifact(path: Path, max_age_days: int) -> tuple[bool, str]:
    """Determine if an artifact directory should be cleaned up."""
    timestamp = parse_artifact_timestamp(path.name)
    if timestamp:
        age = datetime.now() - timestamp
        if age.days > max_age_days:
            return True, f"Age: {age.days} days (max: {max_age_days})"
        return False, f"Recent: {age.days} days old"

    # Fall back to file modification time
    age = get_dir_age(path)
    if age.days > max_age_days:
        return True, f"Age: {age.days} days (estimated)"
    return False, f"Recent: {age.days} days (estimated)"


def archive_path(path: Path, archive_dir: Path) -> Path:
    """Create a compressed archive of a path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if path.is_dir():
        archive_name = f"{path.name}_{timestamp}.tar.gz"
    else:
        archive_name = f"{path.name}_{timestamp}.gz"

    archive_path = archive_dir / archive_name

    if path.is_dir():
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(path, arcname=path.name)
    else:
        with open(path, "rb") as f_in:
            with gzip.open(archive_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    return archive_path


def cleanup_backups(
    nomic_dir: Path,
    max_age_days: int,
    keep_latest: int,
    dry_run: bool,
    archive_dir: Path | None,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up old backup directories."""
    actions: list[tuple[Path, str, str]] = []
    backups_dir = nomic_dir / "backups"
    if not backups_dir.exists():
        return actions

    # Get all backup directories sorted by timestamp
    backups = []
    for path in backups_dir.iterdir():
        if path.is_dir() and path.name.startswith("backup_"):
            timestamp = parse_backup_timestamp(path.name)
            if timestamp:
                backups.append((timestamp, path))

    backups.sort(key=lambda x: x[0], reverse=True)

    # Keep the N most recent regardless of age
    for i, (timestamp, path) in enumerate(backups):
        if i < keep_latest:
            actions.append((path, "keep", f"Recent backup ({i + 1}/{keep_latest})"))
            continue

        should_clean, reason = should_clean_backup(path, max_age_days)
        if should_clean:
            size = get_dir_size(path)
            if archive_dir and not dry_run:
                try:
                    archive_path(path, archive_dir)
                    stats.files_archived += 1
                    stats.bytes_archived += size
                except Exception as e:
                    stats.errors.append((path, str(e)))
                    continue

            if not dry_run:
                try:
                    shutil.rmtree(path)
                    stats.dirs_removed += 1
                    stats.bytes_freed += size
                except Exception as e:
                    stats.errors.append((path, str(e)))
                    continue

            action = "archive+delete" if archive_dir else "delete"
            actions.append((path, action, reason))
        else:
            actions.append((path, "keep", reason))

    return actions


def cleanup_sessions(
    nomic_dir: Path,
    max_age_days: int,
    dry_run: bool,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up old session directories."""
    actions: list[tuple[Path, str, str]] = []
    sessions_dir = nomic_dir / "sessions"
    if not sessions_dir.exists():
        return actions

    for path in sessions_dir.iterdir():
        if not path.is_dir():
            continue

        should_clean, reason = should_clean_session(path, max_age_days)
        if should_clean:
            size = get_dir_size(path)
            if not dry_run:
                try:
                    shutil.rmtree(path)
                    stats.dirs_removed += 1
                    stats.bytes_freed += size
                except Exception as e:
                    stats.errors.append((path, str(e)))
                    continue

            actions.append((path, "delete", reason))
        else:
            actions.append((path, "keep", reason))

    return actions


def cleanup_checkpoints(
    nomic_dir: Path,
    max_age_days: int,
    dry_run: bool,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up old checkpoint files."""
    actions: list[tuple[Path, str, str]] = []
    checkpoints_dir = nomic_dir / "checkpoints"
    if not checkpoints_dir.exists():
        return actions

    for path in checkpoints_dir.iterdir():
        if not path.is_file():
            continue

        should_clean, reason = should_clean_checkpoint(path, max_age_days)
        if should_clean:
            size = path.stat().st_size
            if not dry_run:
                try:
                    path.unlink()
                    stats.files_removed += 1
                    stats.bytes_freed += size
                except Exception as e:
                    stats.errors.append((path, str(e)))
                    continue

            actions.append((path, "delete", reason))
        else:
            actions.append((path, "keep", reason))

    return actions


def cleanup_artifacts(
    nomic_dir: Path,
    max_age_days: int,
    dry_run: bool,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up old artifact directories in root-artifacts."""
    actions: list[tuple[Path, str, str]] = []
    artifacts_dir = nomic_dir / "root-artifacts"
    if not artifacts_dir.exists():
        return actions

    for path in artifacts_dir.iterdir():
        # Skip database files in artifacts directory
        if path.is_file() and path.suffix == ".db":
            continue
        # Skip WAL/SHM files
        if path.is_file() and path.suffix in (".db-wal", ".db-shm"):
            continue

        if path.is_dir():
            should_clean, reason = should_clean_artifact(path, max_age_days)
            if should_clean:
                size = get_dir_size(path)
                if not dry_run:
                    try:
                        shutil.rmtree(path)
                        stats.dirs_removed += 1
                        stats.bytes_freed += size
                    except Exception as e:
                        stats.errors.append((path, str(e)))
                        continue

                actions.append((path, "delete", reason))
            else:
                actions.append((path, "keep", reason))

    return actions


def cleanup_obsolete_files(
    nomic_dir: Path,
    dry_run: bool,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up obsolete database files."""
    actions: list[tuple[Path, str, str]] = []

    for filename in OBSOLETE_FILES:
        path = nomic_dir / filename
        if path.exists():
            size = path.stat().st_size
            if not dry_run:
                try:
                    path.unlink()
                    stats.files_removed += 1
                    stats.bytes_freed += size
                except Exception as e:
                    stats.errors.append((path, str(e)))
                    continue

            actions.append((path, "delete", "Obsolete database"))

    return actions


def cleanup_wal_files(
    nomic_dir: Path,
    dry_run: bool,
    stats: CleanupStats,
) -> list[tuple[Path, str, str]]:
    """Clean up orphaned WAL and SHM files.

    Only removes WAL/SHM files for databases that don't exist.
    """
    actions: list[tuple[Path, str, str]] = []

    for pattern in ("*.db-wal", "*.db-shm"):
        for path in nomic_dir.glob(pattern):
            # Check if the parent database exists
            db_path = path.with_suffix("").with_suffix(".db")
            if not db_path.exists():
                size = path.stat().st_size
                if not dry_run:
                    try:
                        path.unlink()
                        stats.files_removed += 1
                        stats.bytes_freed += size
                    except Exception as e:
                        stats.errors.append((path, str(e)))
                        continue

                actions.append((path, "delete", "Orphaned WAL/SHM file"))

    return actions


def analyze_directory(nomic_dir: Path) -> dict:
    """Analyze the .nomic directory and return statistics."""
    stats: dict[str, float] = {
        "total_size_mb": 0,
        "db_count": 0,
        "db_size_mb": 0,
        "backup_count": 0,
        "backup_size_mb": 0,
        "checkpoint_count": 0,
        "checkpoint_size_mb": 0,
        "session_count": 0,
        "session_size_mb": 0,
        "artifact_count": 0,
        "artifact_size_mb": 0,
        "cleanable_estimate_mb": 0,
    }

    total_size = get_dir_size(nomic_dir)
    stats["total_size_mb"] = total_size / (1024 * 1024)

    # Count databases
    for path in nomic_dir.glob("*.db"):
        stats["db_count"] += 1
        stats["db_size_mb"] += path.stat().st_size / (1024 * 1024)

    # Count backups
    backups_dir = nomic_dir / "backups"
    if backups_dir.exists():
        for path in backups_dir.iterdir():
            if path.is_dir():
                stats["backup_count"] += 1
                stats["backup_size_mb"] += get_dir_size(path) / (1024 * 1024)

    # Count checkpoints
    checkpoints_dir = nomic_dir / "checkpoints"
    if checkpoints_dir.exists():
        for path in checkpoints_dir.glob("*.json.gz"):
            stats["checkpoint_count"] += 1
            stats["checkpoint_size_mb"] += path.stat().st_size / (1024 * 1024)

    # Count sessions
    sessions_dir = nomic_dir / "sessions"
    if sessions_dir.exists():
        for path in sessions_dir.iterdir():
            if path.is_dir():
                stats["session_count"] += 1
                stats["session_size_mb"] += get_dir_size(path) / (1024 * 1024)

    # Count artifacts
    artifacts_dir = nomic_dir / "root-artifacts"
    if artifacts_dir.exists():
        for path in artifacts_dir.iterdir():
            if path.is_dir():
                stats["artifact_count"] += 1
                stats["artifact_size_mb"] += get_dir_size(path) / (1024 * 1024)

    return stats


def print_analysis(stats: dict):
    """Print analysis of the .nomic directory."""
    print("\n=== .nomic/ Directory Analysis ===\n")
    print(f"Total size: {stats['total_size_mb']:.1f} MB")
    print()
    print(f"Databases: {stats['db_count']} files ({stats['db_size_mb']:.1f} MB)")
    print(f"Backups: {stats['backup_count']} directories ({stats['backup_size_mb']:.1f} MB)")
    print(f"Checkpoints: {stats['checkpoint_count']} files ({stats['checkpoint_size_mb']:.1f} MB)")
    print(f"Sessions: {stats['session_count']} directories ({stats['session_size_mb']:.1f} MB)")
    print(f"Artifacts: {stats['artifact_count']} directories ({stats['artifact_size_mb']:.1f} MB)")


def print_actions(
    actions: list[tuple[Path, str, str]],
    category: str,
    verbose: bool = False,
):
    """Print planned/executed actions."""
    if not actions:
        return

    delete_count = sum(1 for _, action, _ in actions if action in ("delete", "archive+delete"))
    keep_count = sum(1 for _, action, _ in actions if action == "keep")

    print(f"\n{category}:")
    print(f"  Delete: {delete_count}, Keep: {keep_count}")

    if verbose:
        for path, action, reason in actions:
            if action in ("delete", "archive+delete"):
                print(f"    - {path.name}: {reason}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean up old/obsolete data in .nomic/ directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Preview what would be cleaned up
    python scripts/cleanup_nomic_state.py --dry-run

    # Perform cleanup with default settings (7 days retention)
    python scripts/cleanup_nomic_state.py

    # Keep backups for 14 days instead of 7
    python scripts/cleanup_nomic_state.py --backup-days 14

    # Archive old backups before deleting
    python scripts/cleanup_nomic_state.py --archive-to ./archived_nomic

    # Only analyze, don't show cleanup plan
    python scripts/cleanup_nomic_state.py --analyze-only
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without actually deleting anything",
    )
    parser.add_argument(
        "--backup-days",
        type=int,
        default=7,
        help="Keep backups newer than N days (default: 7)",
    )
    parser.add_argument(
        "--backup-keep",
        type=int,
        default=5,
        help="Always keep the N most recent backups regardless of age (default: 5)",
    )
    parser.add_argument(
        "--session-days",
        type=int,
        default=3,
        help="Keep sessions newer than N days (default: 3)",
    )
    parser.add_argument(
        "--checkpoint-days",
        type=int,
        default=7,
        help="Keep checkpoints newer than N days (default: 7)",
    )
    parser.add_argument(
        "--artifact-days",
        type=int,
        default=7,
        help="Keep artifacts newer than N days (default: 7)",
    )
    parser.add_argument(
        "--archive-to",
        type=Path,
        default=None,
        help="Archive deleted files to this directory before removing",
    )
    parser.add_argument(
        "--nomic-dir",
        type=Path,
        default=None,
        help="Path to .nomic directory (default: auto-detect from project root)",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only show analysis, don't plan cleanup",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed information about each action",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt (use with caution)",
    )
    parser.add_argument(
        "--clean-obsolete",
        action="store_true",
        help="Remove obsolete database files (use with caution)",
    )

    args = parser.parse_args()

    # Find .nomic directory
    if args.nomic_dir:
        nomic_dir = args.nomic_dir
    else:
        # Default to project root / .nomic
        project_root = Path(__file__).parent.parent
        nomic_dir = project_root / ".nomic"

    if not nomic_dir.exists():
        print(f"Error: .nomic directory not found at {nomic_dir}")
        return 1

    nomic_dir = nomic_dir.resolve()
    print(f"Nomic directory: {nomic_dir}")

    # Analyze directory
    analysis = analyze_directory(nomic_dir)
    print_analysis(analysis)

    if args.analyze_only:
        return 0

    # Create archive directory if needed
    if args.archive_to:
        args.archive_to.mkdir(parents=True, exist_ok=True)
        print(f"\nArchive directory: {args.archive_to}")

    # Collect all cleanup actions
    stats = CleanupStats()
    all_actions = []

    print("\n=== Cleanup Plan ===")
    if args.dry_run:
        print("(DRY RUN - no changes will be made)")

    # Backups
    actions = cleanup_backups(
        nomic_dir,
        args.backup_days,
        args.backup_keep,
        dry_run=True,  # Always dry-run first to collect actions
        archive_dir=args.archive_to,
        stats=CleanupStats(),  # Temp stats for planning
    )
    print_actions(actions, "Backups", args.verbose)
    all_actions.extend(("backups", a) for a in actions if a[1] in ("delete", "archive+delete"))

    # Sessions
    actions = cleanup_sessions(
        nomic_dir,
        args.session_days,
        dry_run=True,
        stats=CleanupStats(),
    )
    print_actions(actions, "Sessions", args.verbose)
    all_actions.extend(("sessions", a) for a in actions if a[1] == "delete")

    # Checkpoints
    actions = cleanup_checkpoints(
        nomic_dir,
        args.checkpoint_days,
        dry_run=True,
        stats=CleanupStats(),
    )
    print_actions(actions, "Checkpoints", args.verbose)
    all_actions.extend(("checkpoints", a) for a in actions if a[1] == "delete")

    # Artifacts
    actions = cleanup_artifacts(
        nomic_dir,
        args.artifact_days,
        dry_run=True,
        stats=CleanupStats(),
    )
    print_actions(actions, "Artifacts", args.verbose)
    all_actions.extend(("artifacts", a) for a in actions if a[1] == "delete")

    # Obsolete files (only if explicitly requested)
    if args.clean_obsolete:
        actions = cleanup_obsolete_files(
            nomic_dir,
            dry_run=True,
            stats=CleanupStats(),
        )
        print_actions(actions, "Obsolete Files", args.verbose)
        all_actions.extend(("obsolete", a) for a in actions if a[1] == "delete")

    # Orphaned WAL files
    actions = cleanup_wal_files(
        nomic_dir,
        dry_run=True,
        stats=CleanupStats(),
    )
    print_actions(actions, "Orphaned WAL/SHM Files", args.verbose)
    all_actions.extend(("wal", a) for a in actions if a[1] == "delete")

    if not all_actions:
        print("\nNo cleanup needed.")
        return 0

    # Estimate space to be freed
    total_to_free = 0
    for category, (path, action, reason) in all_actions:
        if path.exists():
            total_to_free += get_dir_size(path)

    print(f"\nTotal items to clean: {len(all_actions)}")
    print(f"Estimated space to free: {total_to_free / (1024 * 1024):.1f} MB")

    if args.dry_run:
        print("\nRun without --dry-run to perform cleanup.")
        return 0

    # Confirmation
    if not args.yes:
        response = input("\nProceed with cleanup? [y/N] ")
        if response.lower() != "y":
            print("Cleanup cancelled.")
            return 0

    # Execute cleanup
    print("\n=== Executing Cleanup ===\n")

    # Re-run with dry_run=False
    cleanup_backups(
        nomic_dir,
        args.backup_days,
        args.backup_keep,
        dry_run=False,
        archive_dir=args.archive_to,
        stats=stats,
    )

    cleanup_sessions(nomic_dir, args.session_days, dry_run=False, stats=stats)
    cleanup_checkpoints(nomic_dir, args.checkpoint_days, dry_run=False, stats=stats)
    cleanup_artifacts(nomic_dir, args.artifact_days, dry_run=False, stats=stats)

    if args.clean_obsolete:
        cleanup_obsolete_files(nomic_dir, dry_run=False, stats=stats)

    cleanup_wal_files(nomic_dir, dry_run=False, stats=stats)

    # Print results
    print("\n=== Cleanup Complete ===\n")
    print(f"Files removed: {stats.files_removed}")
    print(f"Directories removed: {stats.dirs_removed}")
    print(f"Space freed: {stats.freed_mb:.1f} MB")

    if stats.files_archived > 0:
        print(f"Files archived: {stats.files_archived}")
        print(f"Archive size: {stats.archived_mb:.1f} MB")

    if stats.errors:
        print(f"\nErrors: {len(stats.errors)}")
        for path, error in stats.errors:
            print(f"  - {path}: {error}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
