"""
Obsidian Connector.

Integration with Obsidian vaults for knowledge management:
- Note search and retrieval
- Frontmatter metadata extraction
- Wikilink/backlink resolution
- Tag-based filtering
- Decision receipt writing

Supports both local vault access and Obsidian REST API (via community plugin).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator, Iterator, Mapping

import yaml

from aragora.connectors.base import BaseConnector, Evidence, ConnectorCapabilities
from aragora.connectors.enterprise.base import SyncItem, SyncResult, SyncState
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


class NoteType(str, Enum):
    """Obsidian note types based on content/tags."""

    DAILY = "daily"
    DECISION = "decision"
    RESEARCH = "research"
    MEETING = "meeting"
    PROJECT = "project"
    REFERENCE = "reference"
    TEMPLATE = "template"
    UNKNOWN = "unknown"


@dataclass
class ObsidianConfig:
    """Configuration for Obsidian connector."""

    vault_path: str  # Local path to vault
    api_url: str | None = None  # Optional REST API URL
    api_key: str | None = None  # API key for REST plugin
    watch_tags: list[str] = field(default_factory=lambda: ["#debate", "#decision", "#aragora"])
    ignore_folders: list[str] = field(default_factory=lambda: [".obsidian", ".trash", "templates"])
    sync_attachments: bool = False
    parse_dataview: bool = True  # Parse dataview inline fields

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ObsidianConfig | None:
        """Create config from environment variables.

        Supported variables:
            ARAGORA_OBSIDIAN_VAULT_PATH or OBSIDIAN_VAULT_PATH
            ARAGORA_OBSIDIAN_API_URL
            ARAGORA_OBSIDIAN_API_KEY
            ARAGORA_OBSIDIAN_TAGS (comma-separated)
            ARAGORA_OBSIDIAN_IGNORE_FOLDERS (comma-separated)
            ARAGORA_OBSIDIAN_SYNC_ATTACHMENTS (true/false)
            ARAGORA_OBSIDIAN_PARSE_DATAVIEW (true/false)
        """
        env = env or dict(os.environ)
        vault_path = env.get("ARAGORA_OBSIDIAN_VAULT_PATH") or env.get("OBSIDIAN_VAULT_PATH")
        if not vault_path:
            return None

        def _parse_list(value: str | None) -> list[str]:
            if not value:
                return []
            return [item.strip() for item in value.split(",") if item.strip()]

        def _parse_bool(value: str | None, default: bool) -> bool:
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        watch_tags = _parse_list(env.get("ARAGORA_OBSIDIAN_TAGS"))
        ignore_folders = _parse_list(env.get("ARAGORA_OBSIDIAN_IGNORE_FOLDERS"))

        return cls(
            vault_path=vault_path,
            api_url=env.get("ARAGORA_OBSIDIAN_API_URL"),
            api_key=env.get("ARAGORA_OBSIDIAN_API_KEY"),
            watch_tags=watch_tags or ["#debate", "#decision", "#aragora"],
            ignore_folders=ignore_folders or [".obsidian", ".trash", "templates"],
            sync_attachments=_parse_bool(env.get("ARAGORA_OBSIDIAN_SYNC_ATTACHMENTS"), False),
            parse_dataview=_parse_bool(env.get("ARAGORA_OBSIDIAN_PARSE_DATAVIEW"), True),
        )


@dataclass
class Frontmatter:
    """Parsed YAML frontmatter from a note."""

    title: str | None = None
    date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    aragora_id: str | None = None
    debate_id: str | None = None
    consensus: bool | None = None
    confidence: float | None = None
    related_issues: list[str] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Frontmatter:
        """Parse frontmatter from YAML string."""
        try:
            data = yaml.safe_load(yaml_str) or {}
        except yaml.YAMLError:
            return cls()

        # Parse date (YAML may parse dates as date objects, not datetime)
        date_val = data.get("date")
        date = None
        if isinstance(date_val, datetime):
            date = date_val
        elif hasattr(date_val, "year") and hasattr(date_val, "month"):
            # YAML parsed as date object - convert to datetime
            from datetime import date as date_type

            if isinstance(date_val, date_type):
                date = datetime(date_val.year, date_val.month, date_val.day)
        elif isinstance(date_val, str):
            try:
                date = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            except ValueError as e:
                logger.warning("Failed to parse datetime value: %s", e)

        # Extract known fields
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        aliases = data.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",")]

        related = data.get("related_issues", data.get("related-issues", []))
        if isinstance(related, str):
            related = [r.strip() for r in related.split(",")]

        # Custom fields
        known_keys = {
            "title",
            "date",
            "tags",
            "aliases",
            "aragora_id",
            "aragora-id",
            "debate_id",
            "debate-id",
            "consensus",
            "confidence",
            "related_issues",
            "related-issues",
        }
        custom = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            title=data.get("title"),
            date=date,
            tags=tags,
            aliases=aliases,
            aragora_id=data.get("aragora_id", data.get("aragora-id")),
            debate_id=data.get("debate_id", data.get("debate-id")),
            consensus=data.get("consensus"),
            confidence=data.get("confidence"),
            related_issues=related,
            custom=custom,
        )

    def to_yaml(self) -> str:
        """Serialize frontmatter to YAML."""
        data: dict[str, Any] = {}
        if self.title:
            data["title"] = self.title
        if self.date:
            data["date"] = self.date.isoformat()
        if self.tags:
            data["tags"] = self.tags
        if self.aliases:
            data["aliases"] = self.aliases
        if self.aragora_id:
            data["aragora_id"] = self.aragora_id
        if self.debate_id:
            data["debate_id"] = self.debate_id
        if self.consensus is not None:
            data["consensus"] = self.consensus
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.related_issues:
            data["related_issues"] = self.related_issues
        data.update(self.custom)
        return yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)


@dataclass
class ObsidianNote:
    """An Obsidian note with parsed content."""

    path: str  # Relative path within vault
    name: str  # Filename without extension
    content: str  # Raw content (without frontmatter)
    frontmatter: Frontmatter
    note_type: NoteType = NoteType.UNKNOWN

    # Extracted links
    wikilinks: list[str] = field(default_factory=list)  # [[link]]
    backlinks: list[str] = field(default_factory=list)  # Notes linking to this
    tags: list[str] = field(default_factory=list)  # #tag (inline + frontmatter)
    urls: list[str] = field(default_factory=list)  # External URLs

    # Metadata
    created_at: datetime | None = None
    modified_at: datetime | None = None
    word_count: int = 0

    @classmethod
    def from_file(cls, vault_path: Path, file_path: Path) -> ObsidianNote:
        """Parse a note from file."""
        rel_path = str(file_path.relative_to(vault_path))
        name = file_path.stem

        try:
            raw_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to read %s: %s", file_path, e)
            return cls(
                path=rel_path,
                name=name,
                content="",
                frontmatter=Frontmatter(),
            )

        # Extract frontmatter
        frontmatter = Frontmatter()
        content = raw_content

        if raw_content.startswith("---"):
            parts = raw_content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = Frontmatter.from_yaml(parts[1])
                content = parts[2].strip()

        # Extract wikilinks
        wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)

        # Extract inline tags
        inline_tags = re.findall(r"(?:^|\s)#([a-zA-Z0-9_/-]+)", content)
        all_tags = list(set(frontmatter.tags + [f"#{t}" for t in inline_tags]))

        # Extract URLs
        urls = re.findall(r"https?://[^\s\)>\]]+", content)

        # Determine note type
        note_type = _classify_note(name, all_tags, frontmatter)

        # File metadata
        stat = file_path.stat()
        created_at = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        return cls(
            path=rel_path,
            name=name,
            content=content,
            frontmatter=frontmatter,
            note_type=note_type,
            wikilinks=wikilinks,
            tags=all_tags,
            urls=urls,
            created_at=created_at,
            modified_at=modified_at,
            word_count=len(content.split()),
        )

    def to_evidence(self, vault_path: Path | None = None) -> Evidence:
        """Convert note to Evidence for Knowledge Mound."""
        abs_path = None
        if vault_path is not None:
            try:
                abs_path = str((vault_path / self.path).resolve())
            except OSError:
                abs_path = None
        return Evidence(
            id=f"obsidian-note-{hashlib.sha256(self.path.encode()).hexdigest()[:12]}",
            source_type=SourceType.DOCUMENT,
            source_id=self.path,
            content=self.content,
            title=self.frontmatter.title or self.name,
            created_at=self.created_at.isoformat() if self.created_at else None,
            url=f"obsidian://open?path={abs_path or self.path}",
            metadata={
                "type": "obsidian_note",
                "note_type": self.note_type.value,
                "tags": self.tags,
                "wikilinks": self.wikilinks,
                "word_count": self.word_count,
                "frontmatter": {
                    "aragora_id": self.frontmatter.aragora_id,
                    "debate_id": self.frontmatter.debate_id,
                    "consensus": self.frontmatter.consensus,
                    "confidence": self.frontmatter.confidence,
                },
            },
        )


def _classify_note(name: str, tags: list[str], frontmatter: Frontmatter) -> NoteType:
    """Classify note type based on name, tags, and frontmatter."""
    name_lower = name.lower()
    tags_lower = [t.lower() for t in tags]

    # Check for daily notes (date patterns)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", name):
        return NoteType.DAILY

    # Check for decisions
    if frontmatter.debate_id or frontmatter.aragora_id:
        return NoteType.DECISION
    if any(t in tags_lower for t in ["#decision", "#debate", "#aragora"]):
        return NoteType.DECISION

    # Check for meetings
    if "meeting" in name_lower or any("meeting" in t for t in tags_lower):
        return NoteType.MEETING

    # Check for projects
    if "project" in name_lower or any("project" in t for t in tags_lower):
        return NoteType.PROJECT

    # Check for templates
    if "template" in name_lower:
        return NoteType.TEMPLATE

    # Check for research
    if any(t in tags_lower for t in ["#research", "#literature", "#paper"]):
        return NoteType.RESEARCH

    return NoteType.UNKNOWN


# =============================================================================
# Obsidian Connector
# =============================================================================


class ObsidianConnector(BaseConnector):
    """
    Obsidian vault connector for knowledge management integration.

    Provides:
    - Note search and retrieval
    - Frontmatter metadata extraction
    - Wikilink graph traversal
    - Decision receipt writing
    - Knowledge Mound synchronization
    """

    def __init__(
        self,
        config: ObsidianConfig,
        **kwargs: Any,
    ):
        """Initialize Obsidian connector.

        Args:
            config: Obsidian configuration
            **kwargs: Additional BaseConnector arguments
        """
        super().__init__(**kwargs)
        self._config = config
        self._vault_path = Path(config.vault_path).expanduser().resolve()
        self._note_cache: dict[str, ObsidianNote] = {}
        self._backlink_index: dict[str, list[str]] = {}  # note -> notes linking to it

    @property
    def name(self) -> str:
        """Human-readable name for this connector."""
        return "Obsidian"

    @property
    def source_type(self) -> SourceType:
        """The source type for this connector."""
        return SourceType.DOCUMENT

    @property
    def is_available(self) -> bool:
        """Check if vault is accessible."""
        return self._vault_path.exists() and self._vault_path.is_dir()

    @property
    def is_configured(self) -> bool:
        """Check if connector is properly configured."""
        return bool(self._config.vault_path) and self.is_available

    def capabilities(self) -> ConnectorCapabilities:
        """Report connector capabilities."""
        return ConnectorCapabilities(
            can_send=True,  # Can write notes
            can_receive=True,  # Can read notes
            can_search=True,
            can_sync=True,
            can_stream=False,
            can_batch=True,
            is_stateful=False,
            requires_auth=False,  # Local vault doesn't need auth
            supports_oauth=False,
            supports_webhooks=False,
            supports_files=True,  # Markdown files
            supports_rich_text=True,
            supports_retry=True,
            has_circuit_breaker=False,
            platform_features=["wikilinks", "frontmatter", "tags", "backlinks"],
        )

    # =========================================================================
    # Search & Fetch (BaseConnector Interface)
    # =========================================================================

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[Evidence]:
        """Search vault for notes matching query.

        Args:
            query: Search query (supports text, tags, note types)
            limit: Maximum results
            **kwargs: Additional options
                - tags: list[str] - Filter by tags
                - note_type: NoteType - Filter by type
                - folder: str - Limit to folder
                - since: datetime - Modified since

        Returns:
            List of Evidence objects
        """
        tags_filter = kwargs.get("tags", [])
        note_type_filter = kwargs.get("note_type")
        folder_filter = kwargs.get("folder")
        since_filter = kwargs.get("since")

        results: list[Evidence] = []

        for note in self._iter_notes():
            # Apply filters
            if tags_filter:
                if not any(t in note.tags for t in tags_filter):
                    continue

            if note_type_filter and note.note_type != note_type_filter:
                continue

            if folder_filter and not note.path.startswith(folder_filter):
                continue

            if since_filter and note.modified_at:
                if note.modified_at < since_filter:
                    continue

            # Text search in content and title
            query_lower = query.lower()
            if query_lower not in note.content.lower() and query_lower not in note.name.lower():
                if not any(query_lower in t.lower() for t in note.tags):
                    continue

            results.append(note.to_evidence(self._vault_path))

            if len(results) >= limit:
                break

        return results

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """Fetch a specific note by evidence ID.

        Args:
            evidence_id: Evidence ID (format: obsidian-note-{hash})

        Returns:
            Evidence object or None if not found
        """
        # Evidence ID contains hash of path
        if not evidence_id.startswith("obsidian-note-"):
            return None

        # Search through notes to find matching hash
        target_hash = evidence_id.replace("obsidian-note-", "")

        for note in self._iter_notes():
            path_hash = hashlib.sha256(note.path.encode()).hexdigest()[:12]
            if path_hash == target_hash:
                return note.to_evidence(self._vault_path)

        return None

    # =========================================================================
    # Note Operations
    # =========================================================================

    def get_note(self, path: str) -> ObsidianNote | None:
        """Get a note by its path within the vault.

        Args:
            path: Relative path (e.g., "folder/note.md")

        Returns:
            ObsidianNote or None
        """
        file_path = self._vault_path / path
        if not file_path.exists():
            # Try with .md extension
            file_path = self._vault_path / f"{path}.md"
            if not file_path.exists():
                return None

        return ObsidianNote.from_file(self._vault_path, file_path)

    def get_note_by_name(self, name: str) -> ObsidianNote | None:
        """Get a note by name (searches all folders).

        Args:
            name: Note name (without .md extension)

        Returns:
            First matching ObsidianNote or None
        """
        for note in self._iter_notes():
            if note.name.lower() == name.lower():
                return note
        return None

    def list_notes(
        self,
        folder: str | None = None,
        note_type: NoteType | None = None,
        tags: list[str] | None = None,
    ) -> list[ObsidianNote]:
        """List notes with optional filtering.

        Args:
            folder: Limit to folder
            note_type: Filter by type
            tags: Filter by tags

        Returns:
            List of matching notes
        """
        results = []

        for note in self._iter_notes():
            if folder and not note.path.startswith(folder):
                continue
            if note_type and note.note_type != note_type:
                continue
            if tags and not any(t in note.tags for t in tags):
                continue
            results.append(note)

        return results

    def get_backlinks(self, note_name: str) -> list[ObsidianNote]:
        """Get all notes that link to the given note.

        Args:
            note_name: Name of note to find backlinks for

        Returns:
            List of notes that contain [[note_name]] links
        """
        backlinks = []
        name_lower = note_name.lower()

        for note in self._iter_notes():
            if any(link.lower() == name_lower for link in note.wikilinks):
                backlinks.append(note)

        return backlinks

    def get_linked_notes(self, note: ObsidianNote) -> list[ObsidianNote]:
        """Get all notes that this note links to.

        Args:
            note: Source note

        Returns:
            List of linked notes (resolved wikilinks)
        """
        linked = []

        for link in note.wikilinks:
            linked_note = self.get_note_by_name(link)
            if linked_note:
                linked.append(linked_note)

        return linked

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write_note(
        self,
        path: str,
        content: str,
        frontmatter: Frontmatter | Mapping[str, Any] | None = None,
        overwrite: bool = False,
    ) -> ObsidianNote | None:
        """Write a note to the vault.

        Args:
            path: Relative path for the note
            content: Note content (markdown)
            frontmatter: Optional frontmatter, or a mapping of ``Frontmatter`` fields
            overwrite: Whether to overwrite existing note

        Returns:
            Created/updated ObsidianNote or None on failure
        """
        if isinstance(frontmatter, Mapping):
            frontmatter = Frontmatter(**frontmatter)
        file_path = self._vault_path / path
        if not path.endswith(".md"):
            file_path = self._vault_path / f"{path}.md"

        if file_path.exists() and not overwrite:
            logger.warning("Note already exists: %s", path)
            return None

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Build content with frontmatter
        full_content = ""
        if frontmatter:
            full_content = f"---\n{frontmatter.to_yaml()}---\n\n"
        full_content += content

        try:
            file_path.write_text(full_content, encoding="utf-8")
            logger.info("Wrote note: %s", path)
            return ObsidianNote.from_file(self._vault_path, file_path)
        except OSError as e:
            logger.error("Failed to write note %s: %s", path, e)
            return None

    async def write_decision_receipt(
        self,
        debate_id: str,
        title: str,
        summary: str,
        consensus: bool,
        confidence: float,
        dissent_trail: list[str],
        agents: list[str],
        evidence_ids: list[str],
        folder: str = "decisions",
    ) -> ObsidianNote | None:
        """Write a decision receipt as an Obsidian note.

        Args:
            debate_id: Aragora debate ID
            title: Decision title
            summary: Decision summary
            consensus: Whether consensus was reached
            confidence: Confidence score (0-1)
            dissent_trail: List of dissenting points
            agents: List of participating agents
            evidence_ids: List of evidence IDs used
            folder: Folder to write to

        Returns:
            Created ObsidianNote or None on failure
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Create frontmatter
        frontmatter = Frontmatter(
            title=title,
            date=now,
            tags=["#decision", "#aragora", "#debate-receipt"],
            aragora_id=debate_id,
            debate_id=debate_id,
            consensus=consensus,
            confidence=confidence,
            custom={
                "agents": agents,
                "evidence_count": len(evidence_ids),
            },
        )

        # Build content
        content = f"""# {title}

## Summary

{summary}

## Decision Details

- **Consensus Reached**: {"Yes" if consensus else "No"}
- **Confidence**: {confidence:.1%}
- **Date**: {date_str}
- **Debate ID**: `{debate_id}`

## Participating Agents

{chr(10).join(f"- {agent}" for agent in agents)}

## Evidence Used

{chr(10).join(f"- `{eid}`" for eid in evidence_ids)}

"""

        if dissent_trail:
            content += """## Dissent Trail

"""
            for i, dissent in enumerate(dissent_trail, 1):
                content += f"{i}. {dissent}\n"

        content += f"""
---

*This decision receipt was automatically generated by Aragora on {now.isoformat()}*
"""

        # Generate filename with -receipt suffix for decision receipts
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-")[:50]
        filename = f"{date_str}-{safe_title}-receipt"
        path = f"{folder}/{filename}.md"

        return await self.write_note(path, content, frontmatter, overwrite=False)

    async def write_decision_integrity_package(
        self,
        package: Any,
        title: str | None = None,
        folder: str = "decisions",
        include_context: bool | None = None,
        verification: dict[str, Any] | None = None,
    ) -> ObsidianNote | None:
        """Write a Decision Integrity package to an Obsidian note.

        Args:
            package: DecisionIntegrityPackage or dict representation.
            title: Optional title override for the note.
            folder: Folder to write to within the vault.
            include_context: Override whether to include context snapshot section.

        Returns:
            Created ObsidianNote or None on failure.
        """
        if package is None:
            return None

        package_dict = package.to_dict() if hasattr(package, "to_dict") else dict(package)
        receipt = package_dict.get("receipt") or {}
        plan = package_dict.get("plan") or {}
        context = package_dict.get("context_snapshot") or {}

        debate_id = (
            package_dict.get("debate_id")
            or receipt.get("debate_id")
            or receipt.get("gauntlet_id")
            or "unknown"
        )
        consensus_info = receipt.get("consensus_proof") or {}
        consensus_reached = consensus_info.get("reached")
        if consensus_reached is None and receipt.get("verdict"):
            consensus_reached = str(receipt.get("verdict", "")).upper() in {"PASS", "CONDITIONAL"}
        confidence = (
            consensus_info.get("confidence")
            if consensus_info.get("confidence") is not None
            else receipt.get("confidence")
        )
        confidence = float(confidence or 0.0)

        summary = receipt.get("verdict_reasoning") or receipt.get("input_summary") or ""
        note_title = title or receipt.get("input_summary") or f"Decision {debate_id}"
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Determine if context should be included
        if include_context is None:
            include_context = bool(context)

        verification_summary: dict[str, Any] | None = None
        if verification:
            # Normalize verification payloads (either summary or raw results)
            if "signature_valid" in verification or "integrity_valid" in verification:
                verification_summary = dict(verification)
            else:
                signature = (
                    verification.get("signature", {}) if isinstance(verification, dict) else {}
                )
                integrity = (
                    verification.get("integrity", {}) if isinstance(verification, dict) else {}
                )
                signature_valid = signature.get("signature_valid")
                if signature_valid is None:
                    signature_valid = signature.get("is_valid")
                verification_summary = {
                    "signature_valid": signature_valid,
                    "integrity_valid": integrity.get("integrity_valid"),
                    "signature_error": signature.get("error"),
                    "integrity_error": integrity.get("error"),
                    "verified_at": signature.get("verification_timestamp")
                    or integrity.get("verified_at"),
                }
            if verification_summary:
                verification_summary = {
                    k: v for k, v in verification_summary.items() if v is not None
                }

        custom_fields: dict[str, Any] = {
            "receipt_id": receipt.get("receipt_id"),
            "plan_task_count": len(plan.get("tasks", []) or []),
            "has_context_snapshot": bool(context),
        }
        if verification_summary:
            custom_fields["verification"] = verification_summary

        # Frontmatter
        frontmatter = Frontmatter(
            title=note_title,
            date=now,
            tags=["#decision", "#aragora", "#decision-integrity"],
            aragora_id=str(debate_id),
            debate_id=str(debate_id),
            consensus=bool(consensus_reached) if consensus_reached is not None else None,
            confidence=confidence,
            custom=custom_fields,
        )

        # Build content
        content_lines = [
            f"# {note_title}",
            "",
            "## Summary",
            "",
            summary or "Decision integrity package generated by Aragora.",
            "",
            "## Receipt",
            "",
            f"- **Debate ID**: `{debate_id}`",
        ]
        if consensus_reached is not None:
            content_lines.append(f"- **Consensus Reached**: {'Yes' if consensus_reached else 'No'}")
        content_lines.append(f"- **Confidence**: {confidence:.1%}")
        if receipt.get("verdict"):
            content_lines.append(f"- **Verdict**: {receipt.get('verdict')}")
        if receipt.get("timestamp"):
            content_lines.append(f"- **Timestamp**: {receipt.get('timestamp')}")
        if receipt.get("signature"):
            content_lines.append("- **Signed**: Yes")
        else:
            content_lines.append("- **Signed**: No")

        dissent = receipt.get("dissenting_views") or []
        if dissent:
            content_lines.extend(
                [
                    "",
                    "## Dissent Trail",
                    "",
                    *[f"{idx + 1}. {item}" for idx, item in enumerate(dissent)],
                ]
            )

        tasks = plan.get("tasks") or []
        if tasks:
            content_lines.extend(
                [
                    "",
                    "## Implementation Plan",
                    "",
                    *[
                        f"- [ ] {task.get('id', '')}: {task.get('description', '')}"
                        + (f" ({task.get('complexity')})" if task.get("complexity") else "")
                        + (
                            f" — Files: {', '.join(task.get('files', []))}"
                            if task.get("files")
                            else ""
                        )
                        for task in tasks
                    ],
                ]
            )

        if include_context:
            context_lines = [
                "",
                "## Context Snapshot",
                "",
                f"- Continuum entries: {len(context.get('continuum_entries', []) or [])}",
                f"- Cross-debate references: {len(context.get('cross_debate_ids', []) or [])}",
                f"- Knowledge items: {len(context.get('knowledge_items', []) or [])}",
                f"- Knowledge sources: {', '.join(context.get('knowledge_sources', []) or [])}",
                f"- Document items: {len(context.get('document_items', []) or [])}",
                f"- Evidence items: {len(context.get('evidence_items', []) or [])}",
            ]
            content_lines.extend(context_lines)

        content_lines.append("")
        content_lines.append("---")
        content_lines.append("")
        content_lines.append(
            f"*Decision integrity package generated by Aragora on {now.isoformat()}*"
        )

        content = "\n".join(content_lines)

        safe_title = re.sub(r"[^\w\s-]", "", note_title).strip().replace(" ", "-")[:50]
        filename = f"{date_str}-{safe_title}-integrity"
        path = f"{folder}/{filename}.md"

        return await self.write_note(path, content, frontmatter, overwrite=False)

    async def update_note_frontmatter(
        self,
        path: str,
        updates: dict[str, Any],
    ) -> ObsidianNote | None:
        """Update frontmatter of an existing note.

        Args:
            path: Note path
            updates: Frontmatter fields to update

        Returns:
            Updated ObsidianNote or None
        """
        note = self.get_note(path)
        if not note:
            return None

        # Merge updates into frontmatter
        for key, value in updates.items():
            if hasattr(note.frontmatter, key):
                setattr(note.frontmatter, key, value)
            else:
                note.frontmatter.custom[key] = value

        # Rewrite note
        return await self.write_note(path, note.content, note.frontmatter, overwrite=True)

    # =========================================================================
    # Sync Operations
    # =========================================================================

    def new_sync_state(self, since: datetime | None = None) -> SyncState:
        """A sync state for :meth:`sync_items` that skips notes not modified after ``since``."""
        return SyncState(connector_id=self.name, last_sync_at=since)

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """Sync notes from vault for Knowledge Mound.

        Args:
            state: Sync state with cursor/timestamp
            batch_size: Notes per batch

        Yields:
            SyncItem objects for notes
        """
        since = state.last_sync_at
        count = 0

        for note in self._iter_notes():
            # Filter by modification time if incremental sync
            if since and note.modified_at and note.modified_at <= since:
                continue

            # Skip templates
            if note.note_type == NoteType.TEMPLATE:
                continue

            abs_path = str((self._vault_path / note.path).resolve())
            yield SyncItem(
                id=f"obsidian-note-{hashlib.sha256(note.path.encode()).hexdigest()[:12]}",
                content=note.content,
                source_type="obsidian_note",
                source_id=note.path,
                title=note.frontmatter.title or note.name,
                url=f"obsidian://open?path={abs_path}",
                updated_at=note.modified_at,
                created_at=note.created_at,
                metadata={
                    "note_type": note.note_type.value,
                    "tags": note.tags,
                    "wikilinks": note.wikilinks,
                    "word_count": note.word_count,
                    "aragora_id": note.frontmatter.aragora_id,
                },
            )

            count += 1
            if count >= batch_size:
                break

    async def full_sync(self) -> SyncResult:
        """Perform full sync of vault."""
        start_time = datetime.now(timezone.utc)
        items_synced = 0
        errors: list[str] = []

        try:
            sync_state = SyncState(connector_id=self.name)
            async for _ in self.sync_items(sync_state, batch_size=1000):
                items_synced += 1
        except (OSError, ValueError) as e:
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        return SyncResult(
            connector_id=self.name,
            success=len(errors) == 0,
            items_synced=items_synced,
            items_updated=0,
            items_skipped=0,
            items_failed=len(errors),
            duration_ms=duration,
            errors=errors,
        )

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _iter_notes(self) -> Iterator[ObsidianNote]:
        """Iterate over all notes in vault."""
        for md_file in self._vault_path.rglob("*.md"):
            # Skip ignored folders
            rel_path = md_file.relative_to(self._vault_path)
            if any(part in self._config.ignore_folders for part in rel_path.parts):
                continue

            yield ObsidianNote.from_file(self._vault_path, md_file)

    async def _perform_health_check(self, timeout: float) -> bool:
        """Perform health check on vault."""
        try:
            # Check vault exists and is readable
            if not self._vault_path.exists():
                return False

            # Try to list files
            list(self._vault_path.iterdir())
            return True
        except (OSError, PermissionError):
            return False


# =============================================================================
# Factory Functions
# =============================================================================


def create_obsidian_connector(
    vault_path: str,
    watch_tags: list[str] | None = None,
    **kwargs: Any,
) -> ObsidianConnector:
    """Create an Obsidian connector.

    Args:
        vault_path: Path to Obsidian vault
        watch_tags: Tags to watch for Aragora integration
        **kwargs: Additional configuration

    Returns:
        Configured ObsidianConnector
    """
    config = ObsidianConfig(
        vault_path=vault_path,
        watch_tags=watch_tags or ["#debate", "#decision", "#aragora"],
        **kwargs,
    )
    return ObsidianConnector(config)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ObsidianConnector",
    "ObsidianConfig",
    "ObsidianNote",
    "Frontmatter",
    "NoteType",
    "create_obsidian_connector",
]
