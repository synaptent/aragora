"""
Secrets Rotation Runner

Entrypoint for scheduled secrets rotation.
Can be run as a standalone script or via Kubernetes CronJob.

Usage:
    python -m aragora.scheduler.run_rotation [OPTIONS]

Options:
    --dry-run           Only check what needs rotation, don't rotate
    --secret-id ID      Only rotate a specific secret
    --force             Force rotation even if not due
    --notify-on-failure Send notifications on failure
    --log-level LEVEL   Logging level (debug, info, warning, error)
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load rotation configuration."""
    # Default config paths
    paths: list[str | Path | None] = [
        config_path,
        os.environ.get("ROTATION_CONFIG_PATH"),
        "/etc/aragora/rotation/rotation.yaml",
        Path(__file__).parent.parent.parent / "deploy" / "k8s" / "secrets-rotation" / "config.yaml",
    ]

    for path in paths:
        if path is None:
            continue
        path_obj = Path(path) if isinstance(path, str) else path
        if path_obj.exists():
            with path_obj.open() as f:
                config = yaml.safe_load(f)
                logger.info("Loaded config from %s", path)
                return config.get("rotation", {})

    # Return default config if no file found
    logger.warning("No config file found, using defaults")
    return {
        "dry_run": True,
        "secrets": [],
    }


async def should_rotate(
    secret_config: dict[str, Any],
    last_rotation: datetime | None,
) -> bool:
    """Check if a secret is due for rotation."""
    interval_days = secret_config.get("rotation_interval_days", 90)

    if last_rotation is None:
        return True

    from datetime import timedelta

    next_rotation = last_rotation + timedelta(days=interval_days)
    return datetime.now(timezone.utc) >= next_rotation


async def get_handler(secret_type: str):
    """Get the appropriate rotation handler for a secret type."""
    from aragora.scheduler.rotation_handlers import (
        APIKeyRotationHandler,
        DatabaseRotationHandler,
        EncryptionKeyRotationHandler,
        OAuthRotationHandler,
    )

    handlers = {
        "database": DatabaseRotationHandler,
        "oauth": OAuthRotationHandler,
        "api_key": APIKeyRotationHandler,
        "encryption_key": EncryptionKeyRotationHandler,
    }

    handler_class = handlers.get(secret_type)
    if not handler_class:
        raise ValueError(f"Unknown secret type: {secret_type}")

    return handler_class()


async def get_rotation_history(secret_id: str) -> datetime | None:
    """Get last rotation time for a secret."""
    # Try to get from secrets rotation scheduler if available
    try:
        from aragora.scheduler.secrets_rotation_scheduler import SecretsRotationScheduler

        scheduler = SecretsRotationScheduler()
        metadata = scheduler.get_secret(secret_id)
        if metadata and metadata.last_rotated_at:
            return metadata.last_rotated_at
    except ImportError:
        pass
    except (OSError, RuntimeError, AttributeError) as e:
        logger.warning("Could not get rotation history for %s: %s", secret_id, e)

    return None


async def get_current_secret_value(secret_id: str) -> str | None:
    """Get current secret value from secrets manager."""
    try:
        from aragora.config.secrets import get_secret

        return get_secret(secret_id)
    except (ImportError, OSError, KeyError, RuntimeError) as e:
        logger.warning("Could not get current value for %s: %s", secret_id, e)
        return None


async def store_new_secret(
    secret_id: str,
    new_value: str,
    metadata: dict[str, Any],
) -> bool:
    """Store rotated secret in secrets manager."""
    try:
        # Update AWS Secrets Manager
        import boto3

        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-2"),
        )

        # Try to update existing secret
        try:
            client.put_secret_value(
                SecretId=secret_id,
                SecretString=new_value,
            )
            logger.info("Updated secret %s in AWS Secrets Manager", secret_id)
            return True
        except client.exceptions.ResourceNotFoundException:
            # Create new secret
            client.create_secret(
                Name=secret_id,
                SecretString=new_value,
                Tags=[
                    {"Key": "rotated_at", "Value": datetime.now(timezone.utc).isoformat()},
                    {"Key": "managed_by", "Value": "aragora-rotation"},
                ],
            )
            logger.info("Created secret %s in AWS Secrets Manager", secret_id)
            return True

    except ImportError:
        logger.warning("boto3 not installed, skipping AWS Secrets Manager update")
        return True
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Failed to store secret %s: %s", secret_id, e)
        return False


async def sync_to_github(
    github_secret_name: str,
    secret_value: str,
    config: dict[str, Any],
) -> bool:
    """
    Sync a rotated secret to GitHub repository secrets.

    This is a post-rotation hook that pushes the new value to GitHub.
    Failures are logged and notified but don't fail the rotation
    (AWS Secrets Manager is the source of truth).

    Args:
        github_secret_name: Name of the secret in GitHub
        secret_value: The new secret value to push
        config: Rotation config (contains repo info)

    Returns:
        True if sync succeeded, False otherwise
    """
    github_config = config.get("github_sync", {})
    repo = github_config.get("repo") or os.environ.get("GITHUB_REPO")
    if not repo:
        logger.debug("No GitHub repo configured, skipping sync for %s", github_secret_name)
        return False

    try:
        from aragora.scheduler.rotation_handlers.github_sync import GitHubSecretsSyncBackend

        token = github_config.get("token") or os.environ.get("GITHUB_ROTATION_TOKEN")
        backend = GitHubSecretsSyncBackend(repo=repo, token=token)
        success = await backend.sync_secret(github_secret_name, secret_value)

        if success:
            logger.info("Synced %s to GitHub Secrets", github_secret_name)
        else:
            logger.warning("Failed to sync %s to GitHub Secrets", github_secret_name)
            await send_notification(
                github_secret_name,
                "warning",
                f"Secret rotated in AWS but GitHub sync failed for {github_secret_name}",
                config,
            )

        return success

    except ImportError as e:
        logger.warning("GitHub sync unavailable (missing dependency): %s", e)
        return False
    except (OSError, RuntimeError, ValueError) as e:
        logger.error("GitHub sync error for %s: %s", github_secret_name, e)
        await send_notification(
            github_secret_name,
            "warning",
            f"Secret rotated in AWS but GitHub sync failed: {e}",
            config,
        )
        return False


async def send_notification(
    secret_id: str,
    status: str,
    message: str,
    config: dict[str, Any],
) -> None:
    """Send notification about rotation status."""
    notifications = config.get("notifications", {})

    # Slack notification
    slack_config = notifications.get("slack", {})
    if slack_config.get("enabled"):
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
        if webhook_url:
            try:
                from aragora.observability.http_client_pool import get_http_pool

                payload = {
                    "channel": slack_config.get("channel", "#aragora-security"),
                    "text": f"*Secret Rotation {status.upper()}*\n"
                    f"Secret: `{secret_id}`\n"
                    f"Message: {message}",
                    "username": "Aragora Security",
                    "icon_emoji": ":key:" if status == "success" else ":warning:",
                }

                if status == "failure" and slack_config.get("mention_on_failure"):
                    payload["text"] = f"{slack_config['mention_on_failure']} " + payload["text"]

                pool = get_http_pool()
                async with pool.get_session("slack") as client:
                    await client.post(webhook_url, json=payload, timeout=10.0)
                    logger.info("Sent Slack notification for %s", secret_id)

            except (ImportError, OSError, RuntimeError, ValueError) as e:
                logger.error("Failed to send Slack notification: %s", e)


async def rotate_secret(
    secret_config: dict[str, Any],
    dry_run: bool,
    force: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Rotate a single secret."""
    secret_id = secret_config["id"]
    secret_type = secret_config["type"]
    metadata = secret_config.get("metadata", {})

    result = {
        "secret_id": secret_id,
        "type": secret_type,
        "status": "skipped",
        "message": "",
    }

    try:
        # Check if rotation is due
        last_rotation = await get_rotation_history(secret_id)
        needs_rotation = await should_rotate(secret_config, last_rotation)

        if not needs_rotation and not force:
            result["status"] = "skipped"
            result["message"] = f"Not due for rotation (last: {last_rotation})"
            logger.info("Skipping %s: not due for rotation", secret_id)
            return result

        if dry_run:
            result["status"] = "would_rotate"
            result["message"] = "Dry run - would rotate"
            logger.info("[DRY RUN] Would rotate %s", secret_id)
            return result

        # Get handler and current value
        handler = await get_handler(secret_type)
        current_value = await get_current_secret_value(secret_id)

        # Perform rotation
        logger.info("Rotating %s (%s)", secret_id, secret_type)
        rotation_result = await handler.rotate(secret_id, current_value, metadata)

        if rotation_result.status.value == "success":
            # Store new secret
            new_value = rotation_result.metadata.get("new_value")
            if new_value:
                stored = await store_new_secret(secret_id, new_value, rotation_result.metadata)
                if not stored:
                    result["status"] = "failed"
                    result["message"] = "Failed to store new secret"
                    return result

            result["status"] = "success"
            result["message"] = f"Rotated successfully (version: {rotation_result.new_version})"
            result["new_version"] = rotation_result.new_version

            # Sync to GitHub if configured
            github_name = metadata.get("github_secret_name")
            if github_name and new_value:
                github_ok = await sync_to_github(github_name, new_value, config)
                result["github_synced"] = github_ok

            await send_notification(secret_id, "success", result["message"], config)

        else:
            result["status"] = "failed"
            result["message"] = rotation_result.error_message or "Rotation failed"

            await send_notification(secret_id, "failure", result["message"], config)

    except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as e:
        logger.exception("Error rotating %s: %s", secret_id, e)
        result["status"] = "error"
        result["message"] = "Secret rotation failed"

        await send_notification(secret_id, "failure", "Secret rotation failed", config)

    return result


async def main(args: argparse.Namespace) -> int:
    """Main rotation runner."""
    # Set log level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    logger.info("Starting secrets rotation")

    # Load config
    config = await load_config(args.config)

    # Get secrets to rotate
    secrets = config.get("secrets", [])

    # Filter to specific secret if requested
    if args.secret_id:
        secrets = [s for s in secrets if s["id"] == args.secret_id]
        if not secrets:
            logger.error("Secret %s not found in config", args.secret_id)
            return 1

    # Override dry_run if specified
    dry_run = args.dry_run if args.dry_run is not None else config.get("dry_run", False)

    if dry_run:
        logger.info("Running in DRY RUN mode")

    # Process secrets
    results = []
    for secret_config in secrets:
        result = await rotate_secret(
            secret_config,
            dry_run=dry_run,
            force=args.force,
            config=config,
        )
        results.append(result)

    # Summary
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] in ("failed", "error"))
    skipped_count = sum(1 for r in results if r["status"] in ("skipped", "would_rotate"))

    logger.info(
        "Rotation complete: %s succeeded, %s failed, %s skipped",
        success_count,
        failed_count,
        skipped_count,
    )

    # Print results
    for result in results:
        status_icon = {
            "success": "[OK]",
            "failed": "[FAIL]",
            "error": "[ERR]",
            "skipped": "[SKIP]",
            "would_rotate": "[DRY]",
        }.get(result["status"], "[?]")

        logger.info("%s %s: %s", status_icon, result["secret_id"], result["message"])

    # Return non-zero if any failures and notify requested
    if failed_count > 0:
        if args.notify_on_failure:
            await send_notification(
                "rotation-summary",
                "failure",
                f"{failed_count} secret(s) failed to rotate",
                config,
            )
        return 1

    return 0


def cli():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Run secrets rotation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Only check what needs rotation, don't rotate",
    )

    parser.add_argument(
        "--secret-id",
        help="Only rotate a specific secret",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rotation even if not due",
    )

    parser.add_argument(
        "--notify-on-failure",
        action="store_true",
        help="Send notifications on failure",
    )

    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level",
    )

    parser.add_argument(
        "--config",
        help="Path to rotation config file",
    )

    args = parser.parse_args()

    return asyncio.run(main(args))


if __name__ == "__main__":
    sys.exit(cli())
