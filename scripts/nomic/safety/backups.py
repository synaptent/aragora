"""
Backup and restore functionality for nomic loop safety.

Provides mechanisms to create, restore, and manage backups of
protected files before and after self-improvement cycles.
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections.abc import Callable

from .checksums import PROTECTED_FILES


def create_backup(
    aragora_path: Path,
    backup_dir: Path,
    reason: str = "pre_cycle",
    cycle_count: int = 0,
    log_func: Callable = print,
    stream_emit: Callable | None = None,
) -> Path:
    """
    Create a backup of protected files before making changes.

    Args:
        aragora_path: Root path of the aragora project
        backup_dir: Directory to store backups
        reason: Reason for the backup (e.g., "pre_cycle", "pre_implement")
        cycle_count: Current cycle number
        log_func: Function to log messages
        stream_emit: Optional function to emit stream events

    Returns:
        Path to the created backup directory
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{reason}_{timestamp}"
    backup_path = backup_dir / backup_name
    backup_path.mkdir(parents=True, exist_ok=True)

    log_func(f"  Creating backup: {backup_name}")

    backed_up = []
    for rel_path in PROTECTED_FILES:
        src = aragora_path / rel_path
        if src.exists():
            dst = backup_path / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            backed_up.append(rel_path)

    # Save manifest
    manifest = {
        "created_at": datetime.now().isoformat(),
        "reason": reason,
        "cycle": cycle_count,
        "files": backed_up,
    }
    with open(backup_path / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    log_func(f"  Backup complete: {len(backed_up)} files")

    if stream_emit:
        stream_emit("on_backup_created", backup_name, len(backed_up), reason)

    return backup_path


def restore_backup(
    backup_path: Path,
    aragora_path: Path,
    log_func: Callable = print,
    stream_emit: Callable | None = None,
) -> bool:
    """
    Restore protected files from a backup.

    Args:
        backup_path: Path to the backup directory
        aragora_path: Root path of the aragora project
        log_func: Function to log messages
        stream_emit: Optional function to emit stream events

    Returns:
        True if restore succeeded, False otherwise
    """
    manifest_file = backup_path / "manifest.json"
    if not manifest_file.exists():
        log_func(f"  No manifest found in {backup_path}")
        return False

    with open(manifest_file) as f:
        manifest = json.load(f)

    log_func(f"  Restoring backup from {manifest['created_at']}")

    restored = []
    for rel_path in manifest["files"]:
        src = backup_path / rel_path
        dst = aragora_path / rel_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel_path)

    log_func(f"  Restored {len(restored)} files")

    if stream_emit:
        stream_emit("on_backup_restored", backup_path.name, len(restored), "verification_failed")

    return True


def get_latest_backup(backup_dir: Path) -> Path | None:
    """
    Get the most recent backup directory.

    Args:
        backup_dir: Directory containing backups

    Returns:
        Path to the latest backup with a valid manifest, or None
    """
    if not backup_dir.exists():
        return None

    backups = sorted(backup_dir.iterdir(), reverse=True)
    for backup in backups:
        if backup.is_dir() and (backup / "manifest.json").exists():
            return backup
    return None


def verify_protected_files(aragora_path: Path, log_func: Callable = print) -> list[str]:
    """
    Verify protected files still exist and are importable.

    Args:
        aragora_path: Root path of the aragora project
        log_func: Function to log messages

    Returns:
        List of issues found (empty if all OK)
    """
    issues = []

    for rel_path in PROTECTED_FILES:
        full_path = aragora_path / rel_path
        if not full_path.exists():
            issues.append(f"MISSING: {rel_path}")
            continue

        # Check if Python file is syntactically valid
        if rel_path.endswith(".py"):
            try:
                result = subprocess.run(
                    ["python", "-m", "py_compile", str(full_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,  # 30s is plenty for syntax check
                )
                if result.returncode != 0:
                    issues.append(f"SYNTAX ERROR: {rel_path}")
            except Exception as e:
                issues.append(f"CHECK FAILED: {rel_path} - {e}")

    return issues


def list_backups(backup_dir: Path) -> list[dict]:
    """
    List all available backups with their metadata.

    Args:
        backup_dir: Directory containing backups

    Returns:
        List of backup info dictionaries
    """
    if not backup_dir.exists():
        return []

    backups = []
    for backup_path in sorted(backup_dir.iterdir(), reverse=True):
        if not backup_path.is_dir():
            continue

        manifest_file = backup_path / "manifest.json"
        if manifest_file.exists():
            try:
                with open(manifest_file) as f:
                    manifest = json.load(f)
                backups.append(
                    {
                        "name": backup_path.name,
                        "path": backup_path,
                        "created_at": manifest.get("created_at"),
                        "reason": manifest.get("reason"),
                        "cycle": manifest.get("cycle"),
                        "file_count": len(manifest.get("files", [])),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                # Include backup even if manifest is corrupt
                backups.append(
                    {
                        "name": backup_path.name,
                        "path": backup_path,
                        "created_at": None,
                        "reason": "unknown",
                        "cycle": None,
                        "file_count": 0,
                    }
                )

    return backups
