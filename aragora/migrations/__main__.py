"""
Command-line interface for Aragora database migrations.

Usage:
    python -m aragora.migrations upgrade          # Apply all pending migrations
    python -m aragora.migrations downgrade        # Rollback last migration
    python -m aragora.migrations downgrade --steps 3  # Rollback last 3 migrations
    python -m aragora.migrations downgrade --dry-run  # Preview rollback
    python -m aragora.migrations rollback-history  # View rollback audit log
    python -m aragora.migrations status           # Show migration status
    python -m aragora.migrations create "Name"    # Create new migration file
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from aragora.migrations.runner import (
    DATABASE_ERRORS,
    get_migration_runner,
    reset_runner,
)


def cmd_upgrade(args: argparse.Namespace) -> int:
    """Apply pending migrations."""
    try:
        runner = get_migration_runner(
            db_path=args.db_path,
            database_url=args.database_url,
        )
        applied = runner.upgrade(target_version=args.target)
        if applied:
            print(f"Applied {len(applied)} migration(s):")
            for m in applied:
                print(f"  - {m.version}: {m.name}")
        else:
            print("No pending migrations.")
        return 0
    except DATABASE_ERRORS + (RuntimeError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        reset_runner()


def cmd_downgrade(args: argparse.Namespace) -> int:
    """Rollback migrations."""
    dry_run = getattr(args, "dry_run", False)
    steps = getattr(args, "steps", None)
    reason = getattr(args, "reason", None)
    use_stored = getattr(args, "use_stored_rollback", False)

    try:
        runner = get_migration_runner(
            db_path=args.db_path,
            database_url=args.database_url,
        )
        # Determine rollback mode
        if steps is not None:
            # Validate first
            validation = runner.validate_rollback(steps=steps)
            if not validation.safe:
                print("Rollback validation failed:")
                for err in validation.errors:
                    print(f"  ERROR: {err}")
                return 1

            if validation.warnings:
                for warn in validation.warnings:
                    print(f"  WARNING: {warn}")

            rolled_back = runner.rollback_steps(
                steps=steps,
                dry_run=dry_run,
                reason=reason,
                use_stored_rollback=use_stored,
            )
        else:
            # Validate first
            validation = runner.validate_rollback(target_version=args.target)
            if not validation.safe:
                print("Rollback validation failed:")
                for err in validation.errors:
                    print(f"  ERROR: {err}")
                return 1

            if validation.warnings:
                for warn in validation.warnings:
                    print(f"  WARNING: {warn}")

            rolled_back = runner.downgrade(
                target_version=args.target,
                dry_run=dry_run,
                reason=reason,
                use_stored_rollback=use_stored,
            )

        prefix = "[DRY RUN] Would roll back" if dry_run else "Rolled back"
        if rolled_back:
            print(f"{prefix} {len(rolled_back)} migration(s):")
            for m in rolled_back:
                print(f"  - {m.version}: {m.name}")
        else:
            print("No migrations to rollback.")
        return 0
    except DATABASE_ERRORS + (RuntimeError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        reset_runner()


def cmd_rollback_history(args: argparse.Namespace) -> int:
    """Show rollback history."""
    try:
        runner = get_migration_runner(
            db_path=args.db_path,
            database_url=args.database_url,
        )
        history = runner.get_rollback_history()
        if not history:
            print("No rollback history found.")
            return 0

        print(f"Rollback History ({len(history)} records):")
        print()
        for record in history:
            reason_text = f" reason={record.reason}" if record.reason else ""
            print(f"  [{record.rolled_back_at}] v{record.version}: {record.name}")
            print(f"    by: {record.rolled_back_by}{reason_text}")
            print()
        return 0
    except DATABASE_ERRORS + (RuntimeError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        reset_runner()


def cmd_status(args: argparse.Namespace) -> int:
    """Show migration status."""
    try:
        runner = get_migration_runner(
            db_path=args.db_path,
            database_url=args.database_url,
        )
        status = runner.status()
        print("Migration Status:")
        print(f"  Backend: {runner._backend.backend_type}")
        print(f"  Applied: {status['applied_count']}")
        print(f"  Pending: {status['pending_count']}")
        print(f"  Latest applied: {status['latest_applied'] or 'None'}")
        print(f"  Latest available: {status['latest_available'] or 'None'}")

        if status["pending_versions"]:
            print("\nPending migrations:")
            for v in status["pending_versions"]:
                print(f"  - {v}")

        return 0
    except DATABASE_ERRORS + (RuntimeError, OSError, ValueError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        reset_runner()


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new migration file."""
    # Generate version from timestamp
    version = int(datetime.now().strftime("%Y%m%d%H%M%S"))

    # Sanitize name for filename
    name_slug = args.name.lower().replace(" ", "_").replace("-", "_")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "_")

    filename = f"v{version}_{name_slug}.py"
    filepath = Path(__file__).parent / "versions" / filename

    template = f'''"""
{args.name}

Migration created: {datetime.now().isoformat()}
"""

from aragora.migrations.runner import Migration

migration = Migration(
    version={version},
    name="{args.name}",
    up_sql="""
        -- Add your upgrade SQL here
    """,
    down_sql="""
        -- Add your rollback SQL here (optional but recommended)
    """,
)
'''

    try:
        filepath.write_text(template)
        print(f"Created migration: {filepath}")
        return 0
    except OSError as e:
        print(f"Error creating migration: {e}", file=sys.stderr)
        return 1


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add common database arguments to a parser."""
    parser.add_argument(
        "--db-path",
        default="aragora.db",
        help="SQLite database path (default: aragora.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (or set DATABASE_URL env var)",
    )


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Aragora database migration tool",
        prog="python -m aragora.migrations",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # upgrade command
    upgrade_parser = subparsers.add_parser("upgrade", help="Apply pending migrations")
    add_common_args(upgrade_parser)
    upgrade_parser.add_argument(
        "--target",
        type=int,
        help="Maximum version to apply",
    )
    upgrade_parser.set_defaults(func=cmd_upgrade)

    # downgrade command
    downgrade_parser = subparsers.add_parser("downgrade", help="Rollback migrations")
    add_common_args(downgrade_parser)
    downgrade_parser.add_argument(
        "--target",
        type=int,
        help="Minimum version to keep (default: rollback one)",
    )
    downgrade_parser.add_argument(
        "--steps",
        type=int,
        help="Number of migrations to rollback (alternative to --target)",
    )
    downgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview what would be rolled back without executing",
    )
    downgrade_parser.add_argument(
        "--reason",
        type=str,
        help="Reason for the rollback (stored in rollback history)",
    )
    downgrade_parser.add_argument(
        "--use-stored-rollback",
        action="store_true",
        default=False,
        help="Use stored rollback SQL from database instead of migration files",
    )
    downgrade_parser.set_defaults(func=cmd_downgrade)

    # rollback-history command
    history_parser = subparsers.add_parser("rollback-history", help="Show rollback audit history")
    add_common_args(history_parser)
    history_parser.set_defaults(func=cmd_rollback_history)

    # status command
    status_parser = subparsers.add_parser("status", help="Show migration status")
    add_common_args(status_parser)
    status_parser.set_defaults(func=cmd_status)

    # create command
    create_parser = subparsers.add_parser("create", help="Create new migration file")
    create_parser.add_argument("name", help="Migration name (e.g., 'Add users table')")
    create_parser.set_defaults(func=cmd_create)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
