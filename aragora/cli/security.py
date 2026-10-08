"""
CLI commands for security operations.

Commands:
    aragora security status - Show encryption and key status
    aragora security rotate-key - Rotate encryption key
    aragora security rotate-token - Rotate a service token (PyPI, npm, GitHub PAT)
    aragora security list-tokens - List managed service tokens
    aragora security verify-token - Verify a service token works
    aragora security migrate - Migrate plaintext to encrypted
    aragora security health - Check encryption health
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def create_security_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add security subcommand to CLI."""
    security_parser = subparsers.add_parser(
        "security",
        help="Security operations (encryption, key rotation)",
        description="""
Manage encryption keys, perform key rotation, and check security health.

Examples:
    aragora security status                    # Show encryption status
    aragora security rotate-key --dry-run      # Preview key rotation
    aragora security rotate-key                # Perform key rotation
    aragora security migrate --dry-run         # Preview data migration
    aragora security health                    # Check encryption health
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    security_subparsers = security_parser.add_subparsers(
        dest="security_action",
        help="Security action",
    )

    # Status command
    status_parser = security_subparsers.add_parser(
        "status",
        help="Show encryption and key status",
    )
    status_parser.set_defaults(func=cmd_security_status)

    # Rotate key command
    rotate_parser = security_subparsers.add_parser(
        "rotate-key",
        help="Rotate encryption key",
    )
    rotate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview rotation without making changes",
    )
    rotate_parser.add_argument(
        "--stores",
        type=str,
        default="integration,gmail,sync",
        help="Comma-separated stores to re-encrypt (default: all)",
    )
    rotate_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force rotation even if key is recent",
    )
    rotate_parser.set_defaults(func=cmd_rotate_key)

    # Migrate command
    migrate_parser = security_subparsers.add_parser(
        "migrate",
        help="Migrate plaintext data to encrypted",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    migrate_parser.add_argument(
        "--stores",
        type=str,
        default="integration,gmail,sync",
        help="Comma-separated stores to migrate (default: all)",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    # Health check command
    health_parser = security_subparsers.add_parser(
        "health",
        help="Check encryption health",
    )
    health_parser.add_argument(
        "--detailed",
        "-d",
        action="store_true",
        help="Show detailed health information",
    )
    health_parser.set_defaults(func=cmd_health)

    # Rotate token command
    rotate_token_parser = security_subparsers.add_parser(
        "rotate-token",
        help="Rotate a service token (PyPI, npm, GitHub PAT)",
        description="""
Rotate a service token by storing the new value in configured backends
(AWS Secrets Manager, GitHub repository/org secrets).

Note: Token creation/revocation happens via provider web UIs.
This command handles storage and distribution of the new token.

Examples:
    aragora security rotate-token pypi --token "pypi-..."
    aragora security rotate-token pypi --token "pypi-..." --stores aws
    aragora security rotate-token npm --token "npm_..." --github-repo myorg/myrepo
    aragora security rotate-token github_pat --token "ghp_..." --dry-run
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rotate_token_parser.add_argument(
        "token_type",
        choices=["pypi", "npm", "github_pat", "custom"],
        help="Type of token to rotate",
    )
    rotate_token_parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="New token value (reads from stdin if not provided)",
    )
    rotate_token_parser.add_argument(
        "--stores",
        type=str,
        default=None,
        help="Comma-separated stores to write to (default: aws,github)",
    )
    rotate_token_parser.add_argument(
        "--github-owner",
        type=str,
        default=None,
        help="GitHub org/user for secret storage",
    )
    rotate_token_parser.add_argument(
        "--github-repo",
        type=str,
        default=None,
        help="GitHub repo (owner/repo format) for secret storage",
    )
    rotate_token_parser.add_argument(
        "--aws-secret-name",
        type=str,
        default=None,
        help="AWS Secrets Manager secret name override",
    )
    rotate_token_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview rotation without making changes",
    )
    rotate_token_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip confirmation prompt",
    )
    rotate_token_parser.set_defaults(func=cmd_rotate_token)

    # List tokens command
    list_tokens_parser = security_subparsers.add_parser(
        "list-tokens",
        help="List managed service tokens",
    )
    list_tokens_parser.set_defaults(func=cmd_list_tokens)

    # Verify token command
    verify_token_parser = security_subparsers.add_parser(
        "verify-token",
        help="Verify a service token works",
    )
    verify_token_parser.add_argument(
        "token_type",
        choices=["pypi", "npm", "github_pat"],
        help="Type of token to verify",
    )
    verify_token_parser.set_defaults(func=cmd_verify_token)

    security_parser.set_defaults(func=lambda args: security_parser.print_help())


def cmd_security_status(args: argparse.Namespace) -> int:
    """Show encryption and key status."""
    try:
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        if not CRYPTO_AVAILABLE:
            print("❌ Encryption not available (cryptography library not installed)")
            return 1

        service = get_encryption_service()
        active_key = service.get_active_key()

        print("\n📊 Encryption Status")
        print("=" * 50)
        print("  Cryptography available: ✓")
        print(f"  Active key ID: {service.get_active_key_id()}")

        if active_key:
            age_days = (datetime.now(timezone.utc) - active_key.created_at).days
            print(f"  Key version: {active_key.version}")
            print(f"  Key age: {age_days} days")
            print(f"  Created: {active_key.created_at.isoformat()}")

            # Key age warning
            if age_days > 90:
                print(f"\n  ⚠️  Key is {age_days} days old. Consider rotation.")
            elif age_days > 60:
                print(
                    f"\n  ℹ️  Key is {age_days} days old. Rotation recommended in {90 - age_days} days."
                )
        else:
            print("  ⚠️  No active key found")

        # Show registered keys
        all_keys = service.list_keys()
        if len(all_keys) > 1:
            print(f"\n  Total keys: {len(all_keys)}")
            for key in all_keys:
                key_id = key["key_id"]
                version = key["version"]
                marker = "* " if key_id == service.get_active_key_id() else "  "
                print(f"    {marker}{key_id} v{version}")

        print()
        return 0

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_rotate_key(args: argparse.Namespace) -> int:
    """Rotate encryption key."""
    try:
        from aragora.ops.security_edge_adapters import register_security_migration_adapters
        from aragora.security.migration import rotate_encryption_key

        register_security_migration_adapters()
        stores = [s.strip() for s in args.stores.split(",")]

        print("\n🔑 Key Rotation")
        print("=" * 50)

        if args.dry_run:
            print("  Mode: DRY RUN (no changes will be made)")
        else:
            print("  Mode: LIVE ROTATION")
        print(f"  Stores: {', '.join(stores)}")
        print()

        if not args.dry_run and not args.force:
            response = input("  Proceed with key rotation? [y/N] ")
            if response.lower() != "y":
                print("  Aborted.")
                return 0

        result = rotate_encryption_key(
            stores=stores,
            dry_run=args.dry_run,
        )

        if result.success:
            print("\n✓ Key rotation completed successfully")
            print(f"  Old version: {result.old_key_version}")
            print(f"  New version: {result.new_key_version}")
            print(f"  Stores processed: {result.stores_processed}")
            print(f"  Records re-encrypted: {result.records_reencrypted}")
            print(f"  Duration: {result.duration_seconds:.2f}s")
        else:
            print("\n❌ Key rotation failed")
            print(f"  Failed records: {result.failed_records}")
            for error in result.errors[:5]:
                print(f"    - {error}")

        return 0 if result.success else 1

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_migrate(args: argparse.Namespace) -> int:
    """Migrate plaintext data to encrypted."""
    try:
        from aragora.ops.security_edge_adapters import register_security_migration_adapters
        from aragora.security.migration import (
            run_startup_migration,
            StartupMigrationConfig,
        )

        register_security_migration_adapters()
        stores = [s.strip() for s in args.stores.split(",")]

        print("\n🔄 Data Migration (Plaintext → Encrypted)")
        print("=" * 50)

        if args.dry_run:
            print("  Mode: DRY RUN (no changes will be made)")
        else:
            print("  Mode: LIVE MIGRATION")
        print(f"  Stores: {', '.join(stores)}")
        print()

        if not args.dry_run:
            response = input("  Proceed with migration? [y/N] ")
            if response.lower() != "y":
                print("  Aborted.")
                return 0

        config = StartupMigrationConfig(
            enabled=True,
            dry_run=args.dry_run,
            stores=stores,
        )

        results = run_startup_migration(config=config)

        all_success = True
        print("\n📊 Migration Results")
        print("-" * 50)

        for result in results:
            status = "✓" if result.success else "❌"
            print(f"  {status} {result.store_name}")
            print(f"      Total: {result.total_records}")
            print(f"      Migrated: {result.migrated_records}")
            print(f"      Already encrypted: {result.already_encrypted}")
            if result.failed_records > 0:
                print(f"      Failed: {result.failed_records}")
                all_success = False
            print(f"      Duration: {result.duration_seconds:.2f}s")
            print()

        return 0 if all_success else 1

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_health(args: argparse.Namespace) -> int:
    """Check encryption health."""
    try:
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        print("\n🏥 Encryption Health Check")
        print("=" * 50)

        issues = []
        warnings = []

        # Check 1: Crypto library
        if CRYPTO_AVAILABLE:
            print("  ✓ Cryptography library installed")
        else:
            issues.append("Cryptography library not installed")
            print("  ❌ Cryptography library not installed")

        if not CRYPTO_AVAILABLE:
            print("\n" + "=" * 50)
            print("Health check failed. Fix the issues above.")
            return 1

        # Check 2: Encryption service
        try:
            service = get_encryption_service()
            print("  ✓ Encryption service initialized")
        except (OSError, RuntimeError, ValueError) as e:
            issues.append(f"Encryption service error: {e}")
            print(f"  ❌ Encryption service error: {e}")
            return 1

        # Check 3: Active key
        active_key = service.get_active_key()
        if active_key:
            print(f"  ✓ Active key: {service.get_active_key_id()} v{active_key.version}")

            # Check key age
            age_days = (datetime.now(timezone.utc) - active_key.created_at).days
            if age_days > 90:
                warnings.append(f"Key is {age_days} days old (>90 days)")
                print(f"  ⚠️  Key age: {age_days} days (rotation recommended)")
            elif age_days > 60:
                print(f"  ℹ️  Key age: {age_days} days")
            else:
                print(f"  ✓ Key age: {age_days} days (healthy)")
        else:
            issues.append("No active encryption key")
            print("  ❌ No active encryption key")

        # Check 4: Encrypt/decrypt round-trip
        try:
            test_data = b"health_check_test_data"
            encrypted = service.encrypt(test_data)
            decrypted = service.decrypt(encrypted)
            if decrypted == test_data:
                print("  ✓ Encrypt/decrypt round-trip successful")
            else:
                issues.append("Encrypt/decrypt round-trip failed")
                print("  ❌ Encrypt/decrypt round-trip failed")
        except (OSError, RuntimeError, ValueError) as e:
            issues.append(f"Encrypt/decrypt error: {e}")
            print(f"  ❌ Encrypt/decrypt error: {e}")

        # Summary
        print("\n" + "=" * 50)
        if issues:
            print(f"❌ Health check failed: {len(issues)} issue(s)")
            for issue in issues:
                print(f"   - {issue}")
            return 1
        elif warnings:
            print(f"⚠️  Health check passed with {len(warnings)} warning(s)")
            for warning in warnings:
                print(f"   - {warning}")
            return 0
        else:
            print("✓ All health checks passed")
            return 0

    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Health check error: {e}")
        return 1


def cmd_rotate_token(args: argparse.Namespace) -> int:
    """Rotate a service token."""
    import sys

    try:
        from aragora.security.token_rotation import (
            TokenRotationManager,
            TokenRotationConfig,
            TokenType,
        )

        token_type = TokenType(args.token_type)

        # Get token value from --token flag or stdin
        token_value = args.token
        if not token_value:
            if sys.stdin.isatty():
                token_value = input("  Enter new token value: ").strip()
            else:
                token_value = sys.stdin.read().strip()

        if not token_value:
            print("No token value provided. Use --token or pipe via stdin.")
            return 1

        # Build config from args + env
        config = TokenRotationConfig.from_env()
        if args.stores:
            config.stores = [s.strip() for s in args.stores.split(",")]
        if args.github_owner:
            config.github_owner = args.github_owner
        if args.github_repo:
            config.github_repo = args.github_repo

        print(f"\n🔑 Token Rotation ({token_type.value})")
        print("=" * 50)
        print(f"  Token prefix: {token_value[:8]}...")
        print(f"  Stores: {', '.join(config.stores)}")

        if args.dry_run:
            print("  Mode: DRY RUN (no changes will be made)")
            print("\n✓ Dry run complete. No changes made.")
            return 0

        print("  Mode: LIVE ROTATION")
        print()

        if not args.force:
            response = input("  Proceed with token rotation? [y/N] ")
            if response.lower() != "y":
                print("  Aborted.")
                return 0

        manager = TokenRotationManager(config=config)
        result = manager.rotate(
            token_type,
            token_value,
            secret_name_override=args.aws_secret_name,
        )

        if result.success:
            print("\n✓ Token rotation completed successfully")
            print(f"  Stores updated: {', '.join(result.stores_updated)}")
            print(f"  Rotated at: {result.rotated_at.isoformat()}")
        else:
            print("\n⚠️  Token rotation completed with errors")
            if result.stores_updated:
                print(f"  Stores updated: {', '.join(result.stores_updated)}")
            for store, error in result.errors.items():
                print(f"  ❌ {store}: {error}")

        return 0 if result.success else 1

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n  Aborted.")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_list_tokens(args: argparse.Namespace) -> int:
    """List managed service tokens."""
    try:
        from aragora.security.token_rotation import (
            TokenRotationManager,
            TokenRotationConfig,
        )

        config = TokenRotationConfig.from_env()
        manager = TokenRotationManager(config=config)

        print("\n📋 Managed Service Tokens")
        print("=" * 50)

        tokens = manager.list_managed_tokens()

        if not tokens:
            print("  No tokens found in AWS Secrets Manager.")
            print(f"  Secret name: {config.aws_secret_name}")
            return 0

        for token in tokens:
            print(f"\n  Type: {token.token_type}")
            print(f"  Prefix: {token.prefix}")
            print(f"  Last rotated: {token.last_rotated}")
            print(f"  Stores: {', '.join(token.stores)}")

        print()
        return 0

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_verify_token(args: argparse.Namespace) -> int:
    """Verify a service token works."""
    try:
        from aragora.security.token_rotation import (
            TokenRotationManager,
            TokenRotationConfig,
            TokenType,
        )

        token_type = TokenType(args.token_type)
        manager = TokenRotationManager(config=TokenRotationConfig(stores=[]))

        print(f"\n🔍 Verifying {token_type.value} token...")

        if manager.verify_token(token_type):
            print(f"  ✓ {token_type.value} token verification passed")
            return 0
        else:
            print(f"  ❌ {token_type.value} token verification failed")
            return 1

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"❌ Error: {e}")
        return 1
