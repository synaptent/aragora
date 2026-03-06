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


def write_node(node: IdeaNode, vault_path: str | Path) -> Path:
    """Write an IdeaNode to a markdown file in the vault.

    File is named ``{node.id}.md`` in the vault root.

    Args:
        node: The idea node to persist.
        vault_path: Root directory of the idea vault.

    Returns:
        Path to the written file.
    """
    vault = Path(vault_path)
    vault.mkdir(parents=True, exist_ok=True)

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

    Returns files matching the ``ic_*.md`` naming convention.
    """
    vault = Path(vault_path)
    if not vault.is_dir():
        return []
    # Match idea files by prefix; also accept any .md for flexibility
    files = sorted(vault.glob("ic_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


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
