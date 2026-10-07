"""
Conversation Ingestor Connector - Parse and search ChatGPT/Claude conversation exports.

Supports:
- ChatGPT data exports (conversations.json)
- Claude data exports (similar JSON format)
- Topic clustering via embeddings
- Claim extraction for debate synthesis
- Attribution finding via connected evidence sources

This connector enables users to:
1. Export their conversation history from ChatGPT/Claude
2. Feed it into aragora for analysis
3. Extract intellectual positions and claims
4. Find scholarly attribution for ideas
5. Run multi-agent debate to stress-test positions
"""

from __future__ import annotations

__all__ = [
    "ConversationIngestorConnector",
    "Conversation",
    "ConversationMessage",
    "ConversationExport",
    "ClaimExtraction",
]

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from collections.abc import Iterator

from aragora.connectors.base import BaseConnector, Evidence
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

# Environment variables for configuration
CONFIG_ENV_VARS = ()  # No required env vars - works with local files
OPTIONAL_ENV_VARS = ("CONVERSATION_EXPORT_PATH",)


def get_config_status() -> dict[str, Any]:
    """Return configuration status for this connector."""
    export_path = os.environ.get("CONVERSATION_EXPORT_PATH")
    return {
        "configured": True,  # Always configured - uses local files
        "required": list(CONFIG_ENV_VARS),
        "optional": list(OPTIONAL_ENV_VARS),
        "missing_required": [],
        "missing_optional": [k for k in OPTIONAL_ENV_VARS if not os.environ.get(k)],
        "notes": "Works with local ChatGPT/Claude export files. Set CONVERSATION_EXPORT_PATH for default location.",
        "export_path": export_path,
    }


@dataclass
class ConversationMessage:
    """A single message in a conversation."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime | None = None
    model: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Compute content hash for deduplication."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    @property
    def word_count(self) -> int:
        """Approximate word count."""
        return len(self.content.split())

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "model": self.model,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "word_count": self.word_count,
        }


@dataclass
class Conversation:
    """A complete conversation with metadata."""

    id: str
    title: str
    messages: list[ConversationMessage]
    source: Literal["chatgpt", "claude", "unknown"]
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def total_words(self) -> int:
        return sum(m.word_count for m in self.messages)

    @property
    def user_messages(self) -> list[ConversationMessage]:
        return [m for m in self.messages if m.role == "user"]

    @property
    def assistant_messages(self) -> list[ConversationMessage]:
        return [m for m in self.messages if m.role == "assistant"]

    @property
    def full_text(self) -> str:
        """Concatenate all messages into full text."""
        parts = []
        for msg in self.messages:
            prefix = "USER:" if msg.role == "user" else "ASSISTANT:"
            parts.append(f"{prefix}\n{msg.content}")
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "message_count": self.message_count,
            "total_words": self.total_words,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
        }


@dataclass
class ClaimExtraction:
    """An extracted claim or position from a conversation."""

    claim: str
    context: str
    conversation_id: str
    confidence: float = 0.5
    claim_type: Literal[
        "assertion",
        "question",
        "hypothesis",
        "preference",
        "value",
        "counterargument",
    ] = "assertion"
    topics: list[str] = field(default_factory=list)
    related_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "context": self.context,
            "conversation_id": self.conversation_id,
            "confidence": self.confidence,
            "claim_type": self.claim_type,
            "topics": self.topics,
            "related_claims": self.related_claims,
        }


@dataclass
class ConversationExport:
    """A complete export containing multiple conversations."""

    conversations: list[Conversation]
    source: Literal["chatgpt", "claude", "mixed"]
    export_date: datetime | None = None
    account_email: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def conversation_count(self) -> int:
        return len(self.conversations)

    @property
    def total_messages(self) -> int:
        return sum(c.message_count for c in self.conversations)

    @property
    def total_words(self) -> int:
        return sum(c.total_words for c in self.conversations)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "conversation_count": self.conversation_count,
            "total_messages": self.total_messages,
            "total_words": self.total_words,
            "export_date": self.export_date.isoformat() if self.export_date else None,
            "account_email": self.account_email,
            "metadata": self.metadata,
        }


class ConversationIngestorConnector(BaseConnector):
    """
    Connector for ingesting ChatGPT and Claude conversation exports.

    Parses exported JSON files, extracts conversations, and provides
    search, clustering, and claim extraction capabilities.

    Usage:
        # Load from file
        connector = ConversationIngestorConnector()
        export = connector.load_export("/path/to/conversations.json")

        # Search across conversations
        results = await connector.search("AI alignment")

        # Extract claims
        claims = connector.extract_claims(export)

        # Get topic clusters
        clusters = connector.cluster_by_topic(export)
    """

    def __init__(
        self,
        export_path: str | Path | None = None,
        provenance=None,
    ):
        super().__init__(provenance=provenance, default_confidence=0.8)
        self.export_path = Path(export_path) if export_path else None
        self._loaded_exports: list[ConversationExport] = []
        self._conversation_index: dict[str, Conversation] = {}

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return "Conversation Ingestor"

    # =========================================================================
    # Export Loading
    # =========================================================================

    def load_export(self, path: str | Path) -> ConversationExport:
        """
        Load a conversation export file.

        Automatically detects ChatGPT vs Claude format.

        Args:
            path: Path to the export JSON file

        Returns:
            ConversationExport containing parsed conversations
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Export file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Detect format and parse
        if self._is_chatgpt_format(data):
            export = self._parse_chatgpt_export(data, path)
        elif self._is_claude_format(data):
            export = self._parse_claude_export(data, path)
        else:
            # Try to parse as generic format
            export = self._parse_generic_export(data, path)

        # Index conversations
        self._loaded_exports.append(export)
        for conv in export.conversations:
            self._conversation_index[conv.id] = conv

        logger.info(
            f"Loaded {export.conversation_count} conversations "
            f"({export.total_messages} messages, {export.total_words:,} words) "
            f"from {export.source}"
        )

        return export

    def load_directory(self, directory: str | Path) -> list[ConversationExport]:
        """
        Load all export files from a directory.

        Args:
            directory: Path to directory containing export files

        Returns:
            List of loaded ConversationExports
        """
        directory = Path(directory)
        exports = []

        for path in directory.glob("*.json"):
            try:
                export = self.load_export(path)
                exports.append(export)
            except (
                FileNotFoundError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                ValueError,
                KeyError,
            ) as e:
                logger.warning("Failed to load %s: %s", path, e)

        return exports

    # =========================================================================
    # Format Detection
    # =========================================================================

    def _is_chatgpt_format(self, data: Any) -> bool:
        """Detect ChatGPT export format."""
        # ChatGPT exports are typically a list of conversation objects
        # Each has 'title', 'create_time', 'mapping' (message tree)
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            return isinstance(first, dict) and "mapping" in first
        return False

    def _is_claude_format(self, data: Any) -> bool:
        """Detect Claude export format."""
        # Claude exports have 'conversations' key or similar structure
        if isinstance(data, dict):
            if "conversations" in data:
                return True
            # Check for Claude-specific fields
            if "chat_messages" in data or "uuid" in data:
                return True
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            # Claude conversations have 'uuid' and 'chat_messages'
            return isinstance(first, dict) and ("chat_messages" in first or "uuid" in first)
        return False

    # =========================================================================
    # ChatGPT Parsing
    # =========================================================================

    def _parse_chatgpt_export(self, data: list[dict], source_path: Path) -> ConversationExport:
        """Parse ChatGPT export format."""
        conversations = []

        for conv_data in data:
            try:
                conv = self._parse_chatgpt_conversation(conv_data)
                if conv and conv.messages:  # Only include non-empty conversations
                    conversations.append(conv)
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                logger.debug("Failed to parse ChatGPT conversation: %s", e)

        return ConversationExport(
            conversations=conversations,
            source="chatgpt",
            export_date=datetime.now(),
            metadata={"source_file": str(source_path)},
        )

    def _parse_chatgpt_conversation(self, data: dict) -> Conversation | None:
        """Parse a single ChatGPT conversation."""
        conv_id = data.get(
            "id",
            data.get(
                "conversation_id",
                hashlib.md5(str(data).encode(), usedforsecurity=False).hexdigest()[:16],
            ),
        )
        title = data.get("title", "Untitled Conversation")

        # Parse timestamps
        create_time = data.get("create_time")
        update_time = data.get("update_time")
        created_at = datetime.fromtimestamp(create_time) if create_time else None
        updated_at = datetime.fromtimestamp(update_time) if update_time else None

        # Extract messages from mapping (ChatGPT uses a tree structure)
        messages = []
        mapping = data.get("mapping", {})

        # Find message order by following parent links
        message_nodes = []
        for node_id, node in mapping.items():
            msg = node.get("message")
            if msg and msg.get("content", {}).get("parts"):
                message_nodes.append((node_id, node, msg))

        # Sort by create_time if available
        message_nodes.sort(key=lambda x: x[2].get("create_time", 0) or 0)

        for node_id, node, msg in message_nodes:
            role = msg.get("author", {}).get("role", "unknown")
            if role not in ("user", "assistant", "system"):
                continue

            content_parts = msg.get("content", {}).get("parts", [])
            content = "\n".join(str(p) for p in content_parts if p)

            if not content.strip():
                continue

            msg_time = msg.get("create_time")
            timestamp = datetime.fromtimestamp(msg_time) if msg_time else None

            model = msg.get("metadata", {}).get("model_slug")

            messages.append(
                ConversationMessage(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    model=model,
                    metadata=msg.get("metadata", {}),
                )
            )

        if not messages:
            return None

        return Conversation(
            id=conv_id,
            title=title,
            messages=messages,
            source="chatgpt",
            created_at=created_at,
            updated_at=updated_at,
            metadata=data.get("metadata", {}),
        )

    # =========================================================================
    # Claude Parsing
    # =========================================================================

    def _parse_claude_export(self, data: Any, source_path: Path) -> ConversationExport:
        """Parse Claude export format."""
        conversations = []

        # Handle different Claude export structures
        if isinstance(data, dict) and "conversations" in data:
            conv_list = data["conversations"]
        elif isinstance(data, list):
            conv_list = data
        else:
            conv_list = [data]

        for conv_data in conv_list:
            try:
                conv = self._parse_claude_conversation(conv_data)
                if conv and conv.messages:
                    conversations.append(conv)
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                logger.debug("Failed to parse Claude conversation: %s", e)

        return ConversationExport(
            conversations=conversations,
            source="claude",
            export_date=datetime.now(),
            metadata={"source_file": str(source_path)},
        )

    def _parse_claude_conversation(self, data: dict) -> Conversation | None:
        """Parse a single Claude conversation."""
        conv_id = data.get(
            "uuid",
            data.get("id", hashlib.md5(str(data).encode(), usedforsecurity=False).hexdigest()[:16]),
        )
        title = data.get("name", data.get("title", "Untitled Conversation"))

        # Parse timestamps
        created_at = None
        updated_at = None
        if "created_at" in data:
            try:
                created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                logger.debug("Failed to parse datetime value: %s", e)
        if "updated_at" in data:
            try:
                updated_at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                logger.debug("Failed to parse datetime value: %s", e)

        # Extract messages
        messages = []
        chat_messages = data.get("chat_messages", data.get("messages", []))

        for msg_data in chat_messages:
            role = msg_data.get("sender", msg_data.get("role", "unknown"))
            # Normalize role names
            if role in ("human", "user"):
                role = "user"
            elif role in ("assistant", "claude"):
                role = "assistant"
            elif role != "system":
                continue

            # Handle different content structures
            content = msg_data.get("text", "")
            if not content and "content" in msg_data:
                content_data = msg_data["content"]
                if isinstance(content_data, str):
                    content = content_data
                elif isinstance(content_data, list):
                    content = "\n".join(
                        c.get("text", str(c)) if isinstance(c, dict) else str(c)
                        for c in content_data
                    )

            if not content.strip():
                continue

            # Parse timestamp
            timestamp = None
            if "created_at" in msg_data:
                try:
                    timestamp = datetime.fromisoformat(
                        msg_data["created_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError) as e:
                    logger.debug("Failed to parse datetime value: %s", e)

            messages.append(
                ConversationMessage(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    model=msg_data.get("model"),
                    metadata={
                        k: v
                        for k, v in msg_data.items()
                        if k not in ("text", "content", "sender", "role")
                    },
                )
            )

        if not messages:
            return None

        return Conversation(
            id=conv_id,
            title=title,
            messages=messages,
            source="claude",
            created_at=created_at,
            updated_at=updated_at,
            metadata={k: v for k, v in data.items() if k not in ("chat_messages", "messages")},
        )

    # =========================================================================
    # Generic Parsing
    # =========================================================================

    def _parse_generic_export(self, data: Any, source_path: Path) -> ConversationExport:
        """Parse unknown format - best effort."""
        conversations = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    conv = self._parse_generic_conversation(item)
                    if conv:
                        conversations.append(conv)
        elif isinstance(data, dict):
            conv = self._parse_generic_conversation(data)
            if conv:
                conversations.append(conv)

        return ConversationExport(
            conversations=conversations,
            source="mixed",  # type: ignore[arg-type]
            export_date=datetime.now(),
            metadata={"source_file": str(source_path)},
        )

    def _parse_generic_conversation(self, data: dict) -> Conversation | None:
        """Best-effort parsing of unknown conversation format."""
        conv_id = str(
            data.get(
                "id",
                data.get(
                    "uuid", hashlib.md5(str(data).encode(), usedforsecurity=False).hexdigest()[:16]
                ),
            )
        )
        title = str(data.get("title", data.get("name", "Untitled")))

        # Try to find messages in various keys
        messages_data = None
        for key in ("messages", "chat_messages", "conversation", "turns", "history"):
            if key in data and isinstance(data[key], list):
                messages_data = data[key]
                break

        if not messages_data:
            return None

        messages = []
        for msg in messages_data:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", msg.get("sender", msg.get("author", "unknown")))
            if role in ("human", "user"):
                role = "user"
            elif role in ("assistant", "bot", "ai"):
                role = "assistant"

            content = msg.get("content", msg.get("text", msg.get("message", "")))
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            content = str(content)

            if content.strip() and role in ("user", "assistant", "system"):
                messages.append(ConversationMessage(role=role, content=content))

        if not messages:
            return None

        return Conversation(
            id=conv_id,
            title=title,
            messages=messages,
            source="unknown",
        )

    # =========================================================================
    # Search
    # =========================================================================

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_titles: bool = True,
        search_content: bool = True,
        regex: bool = False,
        **kwargs,
    ) -> list[Evidence]:
        """
        Search across loaded conversations.

        Args:
            query: Search query (text or regex)
            limit: Maximum results to return
            search_titles: Search in conversation titles
            search_content: Search in message content
            regex: Treat query as regex pattern

        Returns:
            List of Evidence objects for matching content
        """
        if regex:
            pattern = re.compile(query, re.IGNORECASE)
        else:
            # Escape regex special chars for literal search
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        results = []

        for conv in self._conversation_index.values():
            # Search title
            if search_titles and pattern.search(conv.title):
                results.append(self._conversation_to_evidence(conv, f"Title match: {conv.title}"))

            # Search messages
            if search_content:
                for i, msg in enumerate(conv.messages):
                    if pattern.search(msg.content):
                        # Get context (surrounding messages)
                        context_start = max(0, i - 1)
                        context_end = min(len(conv.messages), i + 2)
                        context_msgs = conv.messages[context_start:context_end]
                        context = "\n---\n".join(
                            f"[{m.role}]: {m.content[:500]}..."
                            if len(m.content) > 500
                            else f"[{m.role}]: {m.content}"
                            for m in context_msgs
                        )

                        results.append(
                            self._message_to_evidence(
                                msg,
                                conv,
                                context,
                                match_preview=self._get_match_preview(msg.content, pattern),
                            )
                        )

            if len(results) >= limit:
                break

        return results[:limit]

    def _get_match_preview(
        self, content: str, pattern: re.Pattern, context_chars: int = 100
    ) -> str:
        """Get preview of match with surrounding context."""
        match = pattern.search(content)
        if not match:
            return content[:200]

        start = max(0, match.start() - context_chars)
        end = min(len(content), match.end() + context_chars)

        preview = content[start:end]
        if start > 0:
            preview = "..." + preview
        if end < len(content):
            preview = preview + "..."

        return preview

    def _conversation_to_evidence(self, conv: Conversation, title: str | None = None) -> Evidence:
        """Convert conversation to Evidence object."""
        return Evidence(
            id=f"conv_{conv.id}",
            source_type=SourceType.DOCUMENT,
            source_id=conv.id,
            content=conv.full_text[:5000],  # Truncate for evidence
            title=title or conv.title,
            created_at=conv.created_at.isoformat() if conv.created_at else None,
            confidence=0.9,  # High confidence - it's user's own data
            authority=0.7,
            metadata={
                "source": conv.source,
                "message_count": conv.message_count,
                "total_words": conv.total_words,
            },
        )

    def _message_to_evidence(
        self,
        msg: ConversationMessage,
        conv: Conversation,
        context: str,
        match_preview: str | None = None,
    ) -> Evidence:
        """Convert message to Evidence object."""
        return Evidence(
            id=f"msg_{conv.id}_{msg.content_hash}",
            source_type=SourceType.DOCUMENT,
            source_id=conv.id,
            content=context,
            title=f"{conv.title} - {msg.role} message",
            created_at=msg.timestamp.isoformat() if msg.timestamp else None,
            confidence=0.9,
            authority=0.7 if msg.role == "user" else 0.6,
            metadata={
                "source": conv.source,
                "role": msg.role,
                "model": msg.model,
                "match_preview": match_preview,
                "conversation_title": conv.title,
            },
        )

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """Fetch specific evidence by ID."""
        # Parse ID to find conversation
        if evidence_id.startswith("conv_"):
            conv_id = evidence_id[5:]
            if conv_id in self._conversation_index:
                return self._conversation_to_evidence(self._conversation_index[conv_id])
        elif evidence_id.startswith("msg_"):
            parts = evidence_id[4:].split("_", 1)
            if len(parts) == 2:
                conv_id, msg_hash = parts
                if conv_id in self._conversation_index:
                    conv = self._conversation_index[conv_id]
                    for msg in conv.messages:
                        if msg.content_hash == msg_hash:
                            return self._message_to_evidence(msg, conv, msg.content)
        return None

    # =========================================================================
    # Claim Extraction
    # =========================================================================

    def extract_claims(
        self,
        export: ConversationExport | None = None,
        min_length: int = 50,
        patterns: list[str] | None = None,
        include_assistant: bool = False,
        assistant_patterns: list[str] | None = None,
    ) -> list[ClaimExtraction]:
        """
        Extract claims and positions from conversations.

        Uses pattern matching to identify:
        - Assertions ("I think...", "I believe...")
        - Preferences ("I prefer...", "I like...")
        - Values ("I value...", "It's important...")
        - Hypotheses ("My hypothesis is...", "I suspect...")

        Args:
            export: ConversationExport to analyze (or use all loaded)
            min_length: Minimum claim length in characters
            patterns: Custom regex patterns for extraction
            include_assistant: Include assistant counterarguments when True
            assistant_patterns: Custom regex patterns for assistant counterarguments

        Returns:
            List of ClaimExtraction objects
        """
        default_patterns = [
            # Assertions
            (r"I think\s+(.{50,500}?)(?:\.|$)", "assertion"),
            (r"I believe\s+(.{50,500}?)(?:\.|$)", "assertion"),
            (r"My view is\s+(.{50,500}?)(?:\.|$)", "assertion"),
            (r"My position is\s+(.{50,500}?)(?:\.|$)", "assertion"),
            (r"I would argue\s+(.{50,500}?)(?:\.|$)", "assertion"),
            # Preferences
            (r"I prefer\s+(.{30,300}?)(?:\.|$)", "preference"),
            (r"I like\s+(.{30,300}?)(?:\.|$)", "preference"),
            (r"I love\s+(.{30,300}?)(?:\.|$)", "preference"),
            (r"I enjoy\s+(.{30,300}?)(?:\.|$)", "preference"),
            # Values
            (r"I value\s+(.{30,300}?)(?:\.|$)", "value"),
            (r"It(?:'s| is) important (?:to me )?\s*(?:that )?(.{30,300}?)(?:\.|$)", "value"),
            (r"I care about\s+(.{30,300}?)(?:\.|$)", "value"),
            # Hypotheses
            (r"My hypothesis is\s+(.{50,500}?)(?:\.|$)", "hypothesis"),
            (r"I suspect\s+(.{50,500}?)(?:\.|$)", "hypothesis"),
            (r"I predict\s+(.{50,500}?)(?:\.|$)", "hypothesis"),
            # Questions (user's deep questions)
            (
                r"(?:Why|How|What) (?:do|does|is|are|can|should|would)\s+(.{30,300}\?)(?:\s|$)",
                "question",
            ),
        ]

        compiled_patterns = [(re.compile(p, re.IGNORECASE), t) for p, t in default_patterns]

        if patterns:
            for p in patterns:
                compiled_patterns.append((re.compile(p, re.IGNORECASE), "assertion"))

        assistant_default_patterns = [
            (r"(?:However|On the other hand|That said)\s+(.{50,500}?)(?:\.|$)", "counterargument"),
            (
                r"(?:A common objection is|A strong counterargument is|The strongest objection is)\s+(.{50,500}?)(?:\.|$)",
                "counterargument",
            ),
            (
                r"(?:The risk is|The downside is|The problem is)\s+(.{50,500}?)(?:\.|$)",
                "counterargument",
            ),
            (r"(?:One could argue|You could argue)\s+(.{50,500}?)(?:\.|$)", "counterargument"),
        ]
        assistant_compiled = [
            (re.compile(p, re.IGNORECASE), t) for p, t in assistant_default_patterns
        ]

        if assistant_patterns:
            for p in assistant_patterns:
                assistant_compiled.append((re.compile(p, re.IGNORECASE), "counterargument"))

        claims = []
        conversations = export.conversations if export else list(self._conversation_index.values())

        for conv in conversations:
            for msg in conv.user_messages:  # Focus on user's own claims
                for pattern, claim_type in compiled_patterns:
                    for match in pattern.finditer(msg.content):
                        claim_text = match.group(1) if match.groups() else match.group(0)
                        claim_text = claim_text.strip()

                        if len(claim_text) >= min_length:
                            # Get surrounding context
                            start = max(0, match.start() - 100)
                            end = min(len(msg.content), match.end() + 100)
                            context = msg.content[start:end]

                            claims.append(
                                ClaimExtraction(
                                    claim=claim_text,
                                    context=context,
                                    conversation_id=conv.id,
                                    confidence=0.7,
                                    claim_type=claim_type,  # type: ignore[arg-type]
                                )
                            )

            if include_assistant:
                for msg in conv.assistant_messages:
                    for pattern, claim_type in assistant_compiled:
                        for match in pattern.finditer(msg.content):
                            claim_text = match.group(1) if match.groups() else match.group(0)
                            claim_text = claim_text.strip()

                            if len(claim_text) >= min_length:
                                start = max(0, match.start() - 100)
                                end = min(len(msg.content), match.end() + 100)
                                context = msg.content[start:end]

                                claims.append(
                                    ClaimExtraction(
                                        claim=claim_text,
                                        context=context,
                                        conversation_id=conv.id,
                                        confidence=0.6,
                                        claim_type=claim_type,  # type: ignore[arg-type]
                                    )
                                )

        return claims

    # =========================================================================
    # Topic Analysis
    # =========================================================================

    def get_topic_keywords(self) -> dict[str, int]:
        """
        Extract keyword frequencies across all conversations.

        Returns dict mapping keywords to occurrence counts.
        """
        # Simple keyword extraction - could be enhanced with TF-IDF or embeddings
        word_counts: dict[str, int] = {}
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "and",
            "but",
            "if",
            "or",
            "because",
            "as",
            "until",
            "while",
            "it",
            "its",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "we",
            "they",
            "what",
            "which",
            "who",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "our",
            "their",
            "about",
            "like",
            "think",
            "know",
            "get",
            "make",
            "go",
            "see",
            "want",
            "use",
            "find",
            "give",
            "tell",
            "work",
            "seem",
            "feel",
            "try",
            "leave",
            "call",
            "good",
            "new",
            "first",
            "last",
            "long",
            "great",
            "little",
            "thing",
            "things",
            "way",
            "also",
            "well",
            "even",
            "back",
            "much",
            "one",
            "two",
            "something",
            "anything",
            "nothing",
            "everything",
        }

        for conv in self._conversation_index.values():
            for msg in conv.user_messages:
                # Extract words
                words = re.findall(r"\b[a-zA-Z]{4,}\b", msg.content.lower())
                for word in words:
                    if word not in stopwords:
                        word_counts[word] = word_counts.get(word, 0) + 1

        # Sort by frequency
        return dict(sorted(word_counts.items(), key=lambda x: -x[1]))

    def get_conversations_by_topic(self, topic: str) -> list[Conversation]:
        """Get conversations mentioning a specific topic."""
        pattern = re.compile(re.escape(topic), re.IGNORECASE)
        matches = []

        for conv in self._conversation_index.values():
            if pattern.search(conv.full_text):
                matches.append(conv)

        return matches

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about loaded conversations."""
        if not self._conversation_index:
            return {"loaded": False}

        total_user_words = 0
        total_assistant_words = 0
        conversations_by_source: dict[str, int] = {}
        messages_by_month: dict[str, int] = {}

        for conv in self._conversation_index.values():
            # Count by source
            conversations_by_source[conv.source] = conversations_by_source.get(conv.source, 0) + 1

            for msg in conv.messages:
                if msg.role == "user":
                    total_user_words += msg.word_count
                else:
                    total_assistant_words += msg.word_count

                # Count by month
                if msg.timestamp:
                    month_key = msg.timestamp.strftime("%Y-%m")
                    messages_by_month[month_key] = messages_by_month.get(month_key, 0) + 1

        return {
            "loaded": True,
            "total_conversations": len(self._conversation_index),
            "total_exports": len(self._loaded_exports),
            "total_user_words": total_user_words,
            "total_assistant_words": total_assistant_words,
            "conversations_by_source": conversations_by_source,
            "messages_by_month": dict(sorted(messages_by_month.items())),
            "top_keywords": dict(list(self.get_topic_keywords().items())[:20]),
        }

    # =========================================================================
    # Iteration
    # =========================================================================

    def iter_conversations(self) -> Iterator[Conversation]:
        """Iterate over all loaded conversations."""
        yield from self._conversation_index.values()

    def iter_user_messages(self) -> Iterator[tuple[Conversation, ConversationMessage]]:
        """Iterate over all user messages with their conversations."""
        for conv in self._conversation_index.values():
            for msg in conv.user_messages:
                yield conv, msg

    def __len__(self) -> int:
        return len(self._conversation_index)

    def __iter__(self):
        return self.iter_conversations()
