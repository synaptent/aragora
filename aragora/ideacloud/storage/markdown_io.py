"""Obsidian-compatible markdown I/O for Idea Cloud.

Reads and writes .md files with YAML frontmatter and wiki-linked bodies.
Compatible with Obsidian vaults — files can be opened and edited in Obsidian.

File format:
    ---
    title: "..."
    tags: [...]
    id: ic_abc1234
    ...
    ---

    Markdown body with [[wiki-links]] here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from aragora.ideacloud.graph.node import IdeaNode

logger = logging.getLogger(__name__)

# Frontmatter delimiters
FM_DELIMITER = "---"


def write_node(
    node: IdeaNode,
    vault_path: str | Path,
    hierarchical: bool = False,
) -> Path:
    """Write an IdeaNode to a markdown file in the vault.

    File is named ``{node.id}.md``. In flat mode (default), it's placed
    in the vault root. In hierarchical mode, it's placed in a subdirectory
    matching ``node.pipeline_status`` (e.g., ``inbox/``, ``prioritized/``).

    Args:
        node: The idea node to persist.
        vault_path: Root directory of the idea vault.
        hierarchical: If True, organize into status subdirectories.

    Returns:
        Path to the written file.
    """
    vault = Path(vault_path)
    vault.mkdir(parents=True, exist_ok=True)

    if hierarchical and node.pipeline_status:
        target_dir = vault / node.pipeline_status
        target_dir.mkdir(exist_ok=True)
        file_path = target_dir / f"{node.id}.md"
        # Remove from old location if it moved between statuses
        _cleanup_old_locations(vault, node.id, exclude=target_dir)
    else:
        file_path = vault / f"{node.id}.md"
    fm_dict = node.to_frontmatter_dict()

    # Build file content
    lines: list[str] = []
    lines.append(FM_DELIMITER)
    # Use default_flow_style=False for readable YAML
    fm_yaml = yaml.dump(
        fm_dict,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    lines.append(fm_yaml.rstrip())
    lines.append(FM_DELIMITER)
    lines.append("")  # blank line after frontmatter

    if node.body:
        lines.append(node.body)
    else:
        # Default body with title as heading
        lines.append(f"# {node.title}")
        lines.append("")

    content = "\n".join(lines)
    if not content.endswith("\n"):
        content += "\n"

    file_path.write_text(content, encoding="utf-8")
    logger.debug("Wrote idea %s to %s", node.id, file_path)
    return file_path


def read_node(file_path: str | Path) -> IdeaNode:
    """Read an IdeaNode from a markdown file with YAML frontmatter.

    Args:
        file_path: Path to the .md file.

    Returns:
        Parsed IdeaNode.

    Raises:
        ValueError: If the file doesn't contain valid frontmatter.
    """
    path = Path(file_path)
    raw = path.read_text(encoding="utf-8")
    fm_dict, body = _parse_frontmatter(raw)

    node = IdeaNode.from_frontmatter_dict(fm_dict, body=body)
    return node


def list_node_files(vault_path: str | Path) -> list[Path]:
    """List all idea markdown files in the vault.

    Searches both the vault root and status subdirectories
    (inbox/, candidate/, prioritized/, exported/) for files
    matching the ``ic_*.md`` naming convention.
    """
    vault = Path(vault_path)
    if not vault.is_dir():
        return []

    # Flat files in vault root
    files = list(vault.glob("ic_*.md"))

    # Hierarchical files in status subdirectories
    for subdir in _STATUS_DIRS:
        sub = vault / subdir
        if sub.is_dir():
            files.extend(sub.glob("ic_*.md"))

    # Deduplicate (in case the same file somehow exists in both)
    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        if f.name not in seen:
            seen.add(f.name)
            unique.append(f)

    unique.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return unique


# Status directories for hierarchical organization
_STATUS_DIRS = ("inbox", "candidate", "prioritized", "exported")


def delete_node_file(vault_path: str | Path, node_id: str) -> bool:
    """Delete a node's markdown file.

    Returns True if file was deleted, False if it didn't exist.
    """
    path = Path(vault_path) / f"{node_id}.md"
    if path.exists():
        path.unlink()
        logger.debug("Deleted idea file %s", path)
        return True
    return False


# ---- Internal helpers ----


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and body from raw markdown.

    Expects format:
        ---
        key: value
        ---
        body text

    Returns:
        (frontmatter_dict, body_text)
    """
    lines = raw.split("\n")

    # Find frontmatter boundaries
    if not lines or lines[0].strip() != FM_DELIMITER:
        raise ValueError("File does not start with frontmatter delimiter '---'")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_DELIMITER:
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("No closing frontmatter delimiter '---' found")

    # Parse YAML
    fm_raw = "\n".join(lines[1:end_idx])
    fm_dict = yaml.safe_load(fm_raw) or {}

    # Body is everything after the closing delimiter (skip leading blank line)
    body_lines = lines[end_idx + 1 :]
    # Strip one leading blank line if present (convention)
    if body_lines and body_lines[0].strip() == "":
        body_lines = body_lines[1:]
    body = "\n".join(body_lines).rstrip()

    return fm_dict, body


def _cleanup_old_locations(vault: Path, node_id: str, exclude: Path) -> None:
    """Remove a node file from all locations except the target directory.

    Used during hierarchical writes when a node moves between status directories.
    """
    filename = f"{node_id}.md"

    # Check vault root
    root_file = vault / filename
    if root_file.exists() and root_file.parent != exclude:
        root_file.unlink()
        logger.debug("Cleaned up %s from vault root", filename)

    # Check status subdirectories
    for subdir in _STATUS_DIRS:
        sub = vault / subdir
        old_file = sub / filename
        if old_file.exists() and sub != exclude:
            old_file.unlink()
            logger.debug("Cleaned up %s from %s/", filename, subdir)


def migrate_to_hierarchical(vault_path: str | Path) -> dict[str, int]:
    """Migrate a flat vault to hierarchical organization.

    Reads all node files from the vault root, then writes them
    into status subdirectories based on their ``pipeline_status``.

    Args:
        vault_path: Root directory of the idea vault.

    Returns:
        Dict of status → count of files moved.
    """
    vault = Path(vault_path)
    if not vault.is_dir():
        return {}

    moved: dict[str, int] = {}
    for file_path in vault.glob("ic_*.md"):
        if file_path.parent != vault:
            continue  # Already in a subdirectory

        try:
            node = read_node(file_path)
            status = node.pipeline_status or "inbox"
            target_dir = vault / status
            target_dir.mkdir(exist_ok=True)

            target_path = target_dir / file_path.name
            file_path.rename(target_path)
            moved[status] = moved.get(status, 0) + 1
            logger.debug("Migrated %s to %s/", file_path.name, status)
        except Exception as exc:
            logger.warning("Failed to migrate %s: %s", file_path.name, exc)

    return moved
