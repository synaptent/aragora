"""
Evidence Collector.

Auto-collects citations and snippets from existing connectors
to provide factual grounding for debates.

SSRF Protection:
    URL fetching is restricted to prevent Server-Side Request Forgery attacks.
    By default, only URLs from allowlisted domains are fetched.

    Configuration via environment variables:
    - ARAGORA_URL_FETCH_ALL_ENABLED=true: Allow fetching any URL (still blocks
      private IPs and localhost for basic security).
    - ARAGORA_URL_ALLOWED_DOMAINS=domain1.com,domain2.com: Add custom domains
      to the allowlist.

    See aragora.config.settings.EvidenceSettings for details.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)
from collections.abc import Callable
from urllib.parse import urlparse

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.evidence_adapter import EvidenceAdapter
    from aragora.connectors.documents.parser import ParsedDocument

logger = logging.getLogger(__name__)

# Default allowed domains for URL fetching (SSRF protection)
# These are well-known, trusted sources for research
DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        # Code/Documentation
        "github.com",
        "raw.githubusercontent.com",
        "gist.github.com",
        "gitlab.com",
        "bitbucket.org",
        "docs.python.org",
        "docs.anthropic.com",
        "platform.openai.com",
        "cloud.google.com",
        "docs.microsoft.com",
        "learn.microsoft.com",
        "developer.mozilla.org",
        # Research/Academic
        "arxiv.org",
        "wikipedia.org",
        "en.wikipedia.org",
        "scholar.google.com",
        "pubmed.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        # Q&A/Forums
        "stackoverflow.com",
        "stackexchange.com",
        "reddit.com",
        "news.ycombinator.com",
        # News/Media
        "nytimes.com",
        "bbc.com",
        "bbc.co.uk",
        "reuters.com",
        "theguardian.com",
        # Cloud providers
        "aws.amazon.com",
        "azure.microsoft.com",
    }
)

from aragora.connectors.base import Connector
from aragora.reasoning.provenance import ProvenanceManager


@dataclass
class EvidenceSnippet:
    """A piece of evidence from a connector."""

    id: str
    source: str  # "local_docs", "github", etc.
    title: str
    snippet: str
    url: str = ""
    reliability_score: float = 0.5  # 0-1, based on source trustworthiness
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.now)

    @property
    def freshness_score(self) -> float:
        """Calculate freshness score (1.0 = very fresh, 0.0 = stale).

        Evidence degrades over time:
        - < 1 hour: 1.0 (very fresh)
        - 1-24 hours: 0.9-0.7
        - 1-7 days: 0.7-0.5
        - > 7 days: 0.5-0.3
        """
        age_seconds = (datetime.now() - self.fetched_at).total_seconds()
        age_hours = age_seconds / 3600

        if age_hours < 1:
            return 1.0
        elif age_hours < 24:
            return 0.9 - (age_hours / 24) * 0.2
        elif age_hours < 168:  # 7 days
            return 0.7 - ((age_hours - 24) / 144) * 0.2
        else:
            return max(0.3, 0.5 - (age_hours - 168) / 720 * 0.2)

    @property
    def combined_score(self) -> float:
        """Combined reliability and freshness score."""
        return self.reliability_score * 0.7 + self.freshness_score * 0.3

    def to_text_block(self) -> str:
        """Format as a text block for debate context."""
        freshness_indicator = (
            "🟢" if self.freshness_score > 0.8 else "🟡" if self.freshness_score > 0.5 else "🔴"
        )
        source_line = (
            f"Source: {self.source} ({self.reliability_score:.1f} reliability, "
            f"{freshness_indicator} {self.freshness_score:.1f} fresh)"
        )
        snippet_text = self.snippet[:500] + ("..." if len(self.snippet) > 500 else "")
        return f"""EVID-{self.id}:
{source_line}
Title: {self.title}
Snippet: {snippet_text}
URL: {self.url}
---"""

    def to_citation(self) -> str:
        """Format as an academic-style citation.

        Returns a formatted citation string like:
        [1] Title. Source (reliability: 0.9). URL
        """
        url_part = f" {self.url}" if self.url else ""
        source_info = f"{self.source.title()} (reliability: {self.reliability_score:.1f})"
        return f"[{self.id}] {self.title}. {source_info}.{url_part}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "reliability_score": self.reliability_score,
            "freshness_score": self.freshness_score,
            "combined_score": self.combined_score,
            "fetched_at": self.fetched_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class EvidencePack:
    """A collection of evidence snippets for a debate."""

    topic_keywords: list[str]
    snippets: list[EvidenceSnippet]
    search_timestamp: datetime = field(default_factory=datetime.now)
    total_searched: int = 0

    @property
    def average_reliability(self) -> float:
        """Average reliability score across all snippets."""
        if not self.snippets:
            return 0.0
        return sum(s.reliability_score for s in self.snippets) / len(self.snippets)

    @property
    def average_freshness(self) -> float:
        """Average freshness score across all snippets."""
        if not self.snippets:
            return 0.0
        return sum(s.freshness_score for s in self.snippets) / len(self.snippets)

    def to_context_string(self) -> str:
        """Convert to a formatted context string for debate."""
        if not self.snippets:
            return "No relevant evidence found."

        header = f"EVIDENCE PACK (collected {self.search_timestamp.isoformat()}):\n"
        header += f"Search terms: {', '.join(self.topic_keywords)}\n"
        header += f"Total sources searched: {self.total_searched}\n"
        header += (
            f"Quality: {self.average_reliability:.1%} reliability, "
            f"{self.average_freshness:.1%} fresh\n\n"
        )

        evidence_blocks = [snippet.to_text_block() for snippet in self.snippets]
        return header + "\n".join(evidence_blocks) + "\n\nEND EVIDENCE PACK\n"

    def to_bibliography(self) -> str:
        """Format all evidence as an academic bibliography.

        Returns numbered citation list for appending to debate output.
        """
        if not self.snippets:
            return ""

        lines = ["## References\n"]
        for i, snippet in enumerate(self.snippets, 1):
            lines.append(f"{i}. {snippet.to_citation()}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "topic_keywords": self.topic_keywords,
            "snippets": [s.to_dict() for s in self.snippets],
            "search_timestamp": self.search_timestamp.isoformat(),
            "total_searched": self.total_searched,
            "average_reliability": self.average_reliability,
            "average_freshness": self.average_freshness,
        }


class EvidenceCollector:
    """Collects evidence from multiple connectors for debate grounding.

    SSRF Protection:
        By default, URL fetching is restricted to allowlisted domains to prevent
        Server-Side Request Forgery attacks.

        Configure via environment variables:
        - ARAGORA_URL_FETCH_ALL_ENABLED=true: Allow any URL (trusted environments)
        - ARAGORA_URL_ALLOWED_DOMAINS=domain1,domain2: Extend allowlist
    """

    def __init__(
        self,
        connectors: dict[str, Connector] | None = None,
        event_emitter: Any | None = None,
        loop_id: str | None = None,
        allowed_domains: set[str] | None = None,
        require_url_consent: bool = False,
        url_consent_callback: Callable[[str, str], bool] | None = None,
        audit_callback: Callable[[str, str, str, bool], None] | None = None,
        km_adapter: EvidenceAdapter | None = None,
    ):
        """Initialize the evidence collector.

        Args:
            connectors: Dict of connector name to Connector instance
            event_emitter: Optional event emitter for real-time updates
            loop_id: Optional loop ID for event context
            allowed_domains: Set of allowed domains for URL fetching.
                           Merged with DEFAULT_ALLOWED_DOMAINS and settings.
            require_url_consent: If True, require explicit consent before fetching URLs.
                               When enabled, url_consent_callback must be provided.
            url_consent_callback: Callback to request user consent for URL fetching.
                                Signature: (url: str, org_id: str) -> bool
                                Returns True if consent is granted, False otherwise.
            audit_callback: Optional callback for audit logging of URL fetches.
                          Signature: (url: str, org_id: str, action: str, success: bool)
                          action is one of: "fetch", "blocked_ssrf", "blocked_domain", "blocked_consent"
            km_adapter: Optional Knowledge Mound adapter for querying existing evidence
        """
        self.connectors = connectors or {}
        self.provenance_manager = ProvenanceManager()
        self.max_snippets_per_connector = 3
        self.max_total_snippets = 8
        self.snippet_max_length = 1000
        self.event_emitter = event_emitter
        self.loop_id = loop_id

        # URL consent configuration
        self._require_url_consent = require_url_consent
        self._url_consent_callback = url_consent_callback
        self._audit_callback = audit_callback
        self._org_id: str | None = None  # Set via set_org_context()

        # Knowledge Mound integration
        self._km_adapter = km_adapter

        # Document parser integration
        self._document_connector: Any | None = None
        self._parsed_documents: dict[str, ParsedDocument] = {}

        if require_url_consent and url_consent_callback is None:
            raise ValueError("url_consent_callback is required when require_url_consent=True")

        # Load URL security settings
        try:
            from aragora.config.settings import get_settings

            settings = get_settings()
            self._url_fetch_all_enabled = settings.evidence.url_fetch_all_enabled
            additional_domains = settings.evidence.additional_allowed_domains
        except (ImportError, AttributeError, KeyError) as e:
            # Expected errors: module not installed, missing attribute, or config key
            logger.debug("Settings not available for evidence collector, using defaults: %s", e)
            self._url_fetch_all_enabled = False
            additional_domains = []
        except (RuntimeError, TypeError, ValueError) as e:
            logger.warning("Unexpected error loading evidence settings, using defaults: %s", e)
            self._url_fetch_all_enabled = False
            additional_domains = []

        # Build final allowlist: default + settings + explicit
        self._allowed_domains = set(DEFAULT_ALLOWED_DOMAINS)
        self._allowed_domains.update(additional_domains)
        if allowed_domains:
            self._allowed_domains.update(allowed_domains)

    def set_org_context(self, org_id: str) -> None:
        """Set the organization context for consent and audit tracking."""
        self._org_id = org_id

    def set_km_adapter(self, adapter: EvidenceAdapter) -> None:
        """Set Knowledge Mound adapter for querying existing evidence.

        Args:
            adapter: EvidenceAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def query_km_for_existing(
        self,
        topic: str,
        limit: int = 10,
        min_reliability: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for existing evidence on a topic.

        This implements the query-before-action pattern, checking KM
        for relevant evidence before collecting from external sources.

        Args:
            topic: Topic to search for
            limit: Maximum results to return
            min_reliability: Minimum reliability score

        Returns:
            List of existing evidence items from KM
        """
        if not self._km_adapter:
            return []

        try:
            return self._km_adapter.search_by_topic(
                query=topic,
                limit=limit,
                min_reliability=min_reliability,
            )
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Failed to query KM for existing evidence (network): %s", e)
            return []
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to query KM for existing evidence (data): %s", e)
            return []

    def _get_document_connector(self) -> Any:
        """Get or create the document connector (lazy initialization)."""
        if self._document_connector is None:
            try:
                from aragora.connectors.documents import DocumentConnector

                self._document_connector = DocumentConnector()
            except ImportError:
                logger.debug("DocumentConnector not available - document parsing disabled")
                return None
        return self._document_connector

    async def parse_document_file(
        self,
        file_path: str | Path,
    ) -> list[EvidenceSnippet] | None:
        """Parse a document file and return evidence snippets.

        Supports PDF, DOCX, XLSX, PPTX, HTML, JSON, YAML, XML, CSV formats.

        Args:
            file_path: Path to the document file

        Returns:
            List of EvidenceSnippet objects, or None if parsing failed
        """
        connector = self._get_document_connector()
        if connector is None:
            return None

        try:
            doc = await connector.parse_file(file_path)
            if doc is None:
                return None

            # Store for later reference
            path = Path(file_path) if isinstance(file_path, str) else file_path
            self._parsed_documents[str(path.absolute())] = doc

            return self._document_to_snippets(doc, str(path))

        except (OSError, PermissionError) as e:
            logger.error("Failed to parse document file %s (I/O error): %s", file_path, e)
            return None
        except (ValueError, TypeError, KeyError) as e:
            logger.error("Failed to parse document file %s (parse error): %s", file_path, e)
            return None

    async def parse_document_bytes(
        self,
        content: bytes,
        filename: str,
        source_url: str | None = None,
    ) -> list[EvidenceSnippet] | None:
        """Parse document bytes and return evidence snippets.

        Args:
            content: Document content as bytes
            filename: Original filename (for format detection)
            source_url: Optional source URL for the document

        Returns:
            List of EvidenceSnippet objects, or None if parsing failed
        """
        connector = self._get_document_connector()
        if connector is None:
            return None

        try:
            doc = await connector.parse_bytes(content, filename)
            if doc is None:
                return None

            if source_url:
                doc.metadata["source_url"] = source_url

            return self._document_to_snippets(doc, source_url or filename)

        except (ValueError, TypeError, KeyError) as e:
            logger.error("Failed to parse document bytes (%s): %s", filename, e)
            return None

    def _document_to_snippets(
        self,
        doc: ParsedDocument,
        source: str,
    ) -> list[EvidenceSnippet]:
        """Convert ParsedDocument to EvidenceSnippet list."""
        snippets = []

        # Get format-specific reliability score
        format_reliability = {
            "pdf": 0.85,
            "docx": 0.80,
            "xlsx": 0.90,
            "pptx": 0.70,
            "json": 0.90,
            "yaml": 0.90,
            "csv": 0.90,
            "html": 0.65,
            "txt": 0.60,
            "md": 0.70,
        }
        format_name = doc.format.value if doc.format else "unknown"
        base_reliability = format_reliability.get(format_name, 0.70)

        # Create snippets from document chunks
        for i, chunk in enumerate(doc.chunks):
            snippet_id = hashlib.sha256(f"{source}_{i}_{chunk.content[:50]}".encode()).hexdigest()[
                :12
            ]

            snippets.append(
                EvidenceSnippet(
                    id=f"doc_{snippet_id}",
                    source=f"document_{format_name}",
                    title=f"{doc.title or doc.filename} (Section {i + 1})",
                    snippet=self._truncate_snippet(chunk.content),
                    url=source if source.startswith(("http://", "https://")) else "",
                    reliability_score=base_reliability,
                    metadata={
                        "filename": doc.filename,
                        "format": format_name,
                        "page": chunk.page,
                        "section": chunk.section,
                        "chunk_index": i,
                        "total_chunks": len(doc.chunks),
                        "file_path": source if not source.startswith("http") else None,
                    },
                )
            )

        # Create snippets from tables (higher reliability - structured data)
        for j, table in enumerate(doc.tables):
            # Handle both DocumentTable objects and raw list[list[str]] data
            if isinstance(table, list):
                # Raw table data (list[list[str]])
                table_data = cast(list[list[Any]], table)
                table_headers: list[str] | None = None
                table_page: int | None = None
                table_caption: str | None = None
            else:
                # DocumentTable object
                table_data = table.data
                table_headers = table.headers
                table_page = table.page
                table_caption = table.caption

            table_content = self._format_table_for_snippet(table_data, table_headers)
            snippet_id = hashlib.sha256(
                f"{source}_table_{j}_{table_content[:50]}".encode()
            ).hexdigest()[:12]

            snippets.append(
                EvidenceSnippet(
                    id=f"doc_table_{snippet_id}",
                    source=f"document_table_{format_name}",
                    title=f"{doc.title or doc.filename} - Table {j + 1}",
                    snippet=self._truncate_snippet(table_content),
                    url=source if source.startswith(("http://", "https://")) else "",
                    reliability_score=min(1.0, base_reliability + 0.05),  # Tables are more reliable
                    metadata={
                        "filename": doc.filename,
                        "format": format_name,
                        "page": table_page,
                        "caption": table_caption,
                        "table_index": j,
                        "total_tables": len(doc.tables),
                    },
                )
            )

        logger.info(
            "Parsed document: %s -> %s evidence snippets (%s chunks, %s tables)",
            doc.filename,
            len(snippets),
            len(doc.chunks),
            len(doc.tables),
        )

        return snippets

    def _format_table_for_snippet(
        self,
        data: list[list[Any]],
        headers: list[str] | None = None,
    ) -> str:
        """Format table data as text for evidence snippet."""
        lines = []

        if headers:
            lines.append(" | ".join(str(h) for h in headers))
            lines.append("-" * 40)

        for row in data[:15]:  # Limit rows
            lines.append(" | ".join(str(cell)[:30] for cell in row))

        if len(data) > 15:
            lines.append(f"[{len(data) - 15} more rows...]")

        return "\n".join(lines)

    def _extract_document_paths(self, task: str) -> list[str]:
        """Extract document file paths from task description.

        Detects:
        - Absolute paths (/path/to/file.pdf)
        - Relative paths (./docs/file.docx)
        - Windows paths (C:\\path\\file.xlsx)
        - Quoted paths ("path with spaces/file.pdf")

        Args:
            task: Task description that may contain file paths

        Returns:
            List of detected file paths
        """
        paths = []

        # Document extensions to look for
        doc_extensions = r"\.(pdf|docx?|xlsx?|pptx?|csv|json|yaml|yml|xml|html?|txt|md)"

        # Pattern 1: Quoted paths
        quoted_pattern = rf'["\']([^"\']+{doc_extensions})["\']'
        paths.extend(re.findall(quoted_pattern, task, re.IGNORECASE))

        # Pattern 2: Unix absolute paths
        unix_pattern = rf"(/[\w./-]+{doc_extensions})\b"
        paths.extend(re.findall(unix_pattern, task, re.IGNORECASE))

        # Pattern 3: Unix relative paths
        relative_pattern = rf"(\.{1, 2}/[\w./-]+{doc_extensions})\b"
        paths.extend(re.findall(relative_pattern, task, re.IGNORECASE))

        # Pattern 4: Windows paths
        windows_pattern = rf"([A-Za-z]:\\[\w.\\-]+{doc_extensions})\b"
        paths.extend(re.findall(windows_pattern, task, re.IGNORECASE))

        # Pattern 5: Bare filenames with extensions
        bare_pattern = rf"\b([\w.-]+{doc_extensions})\b"
        for match in re.findall(bare_pattern, task, re.IGNORECASE):
            # Only add if it looks like a valid filename (not URL or path fragment)
            if "/" not in match and "\\" not in match:
                paths.append(match)

        # Deduplicate while preserving order
        seen = set()
        unique_paths = []
        for path in paths:
            # Handle tuple from group captures
            if isinstance(path, tuple):
                path = path[0] if path[0] else path[1] if len(path) > 1 else ""
            if path and path not in seen:
                seen.add(path)
                unique_paths.append(path)

        return unique_paths

    def _is_document_url(self, url: str) -> bool:
        """Check if URL points to a document file.

        Args:
            url: URL to check

        Returns:
            True if URL ends with document extension
        """
        doc_extensions = {
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".csv",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".html",
            ".htm",
            ".txt",
            ".md",
        }
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        return any(path_lower.endswith(ext) for ext in doc_extensions)

    def _check_url_consent(self, url: str) -> bool:
        """Check if URL fetch is allowed via consent gate.

        Returns True if:
        - Consent not required, OR
        - Consent callback returns True

        Logs audit event regardless of outcome.
        """
        org_id = self._org_id or "unknown"

        if not self._require_url_consent:
            return True

        if self._url_consent_callback is None:
            logger.warning("URL consent required but no callback configured. Blocking: %s", url)
            self._log_audit(url, org_id, "blocked_consent", False)
            return False

        try:
            consent_granted = self._url_consent_callback(url, org_id)
            if not consent_granted:
                logger.info("URL consent denied for: %s", url)
                self._log_audit(url, org_id, "blocked_consent", False)
            return consent_granted
        except (TypeError, ValueError, AttributeError) as e:
            logger.error("URL consent callback error: %s", e)
            self._log_audit(url, org_id, "blocked_consent", False)
            return False

    def _log_audit(self, url: str, org_id: str, action: str, success: bool) -> None:
        """Log URL fetch action for audit trail."""
        if self._audit_callback:
            try:
                self._audit_callback(url, org_id, action, success)
            except (TypeError, ValueError, AttributeError, RuntimeError) as e:
                logger.warning("Audit callback error: %s", e)

    def add_connector(self, name: str, connector: Connector) -> None:
        """Add a connector for evidence collection."""
        self.connectors[name] = connector

    def _is_domain_allowed(self, domain: str) -> bool:
        """Check if domain is in the allowlist.

        Handles subdomains (e.g., api.github.com matches github.com).
        """
        domain = domain.lower()
        for allowed in self._allowed_domains:
            if domain == allowed or domain.endswith(f".{allowed}"):
                return True
        return False

    def _is_safe_url(self, url: str) -> bool:
        """Perform SSRF safety checks on a URL.

        Blocks:
        - localhost and loopback addresses
        - Private IP ranges (10.x, 172.16-31.x, 192.168.x)
        - Link-local addresses (169.254.x)
        - Non-standard ports
        - Non-HTTP(S) schemes
        """
        try:
            parsed = urlparse(url)

            # Block non-HTTP schemes
            if parsed.scheme not in ("http", "https"):
                logger.debug("SSRF: Blocked non-HTTP scheme: %s", parsed.scheme)
                return False

            hostname = parsed.hostname
            if not hostname:
                return False

            # Block localhost variants
            if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):  # noqa: S104 - SSRF blocklist, not a bind address
                logger.debug("SSRF: Blocked localhost: %s", hostname)
                return False

            # Block private IP ranges
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    logger.debug("SSRF: Blocked private/reserved IP: %s", hostname)
                    return False
            except ValueError:
                # Not an IP address (hostname), which is fine
                pass

            # Block non-standard ports (only allow 80 and 443)
            if parsed.port and parsed.port not in (80, 443):
                logger.debug("SSRF: Blocked non-standard port: %s", parsed.port)
                return False

            return True

        except (ValueError, TypeError, AttributeError) as e:
            logger.debug("SSRF: URL parse error: %s", e)
            return False

    def _emit_evidence_events(
        self,
        snippets: list[EvidenceSnippet],
        keywords: list[str],
    ) -> None:
        """Emit evidence_found events for real-time UI updates.

        Emits a single event containing all evidence snippets found,
        allowing the frontend to display evidence as it's collected.
        """
        if not self.event_emitter:
            return

        try:
            # Format snippets for the event
            evidence_data = {
                "keywords": keywords,
                "count": len(snippets),
                "snippets": [
                    {
                        "id": s.id,
                        "source": s.source,
                        "title": s.title,
                        "snippet": s.snippet[:300],  # Truncate for event payload
                        "url": s.url,
                        "reliability_score": s.reliability_score,
                        "freshness_score": s.freshness_score,
                    }
                    for s in snippets
                ],
            }

            self.event_emitter.emit(
                "evidence_found",
                loop_id=self.loop_id,
                data=evidence_data,
            )
            logger.debug("Emitted evidence_found event with %s snippets", len(snippets))
        except (TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to emit evidence_found event: %s", e)

    async def collect_evidence(
        self,
        task: str,
        enabled_connectors: list[str] | None = None,
        fetch_urls: bool | None = None,
        document_files: list[str | Path] | None = None,
    ) -> EvidencePack:
        """Collect evidence relevant to the task.

        Supports omnivorous evidence collection from:
        - URLs mentioned in the task (with SSRF protection)
        - Document files (PDF, DOCX, XLSX, PPTX, etc.)
        - Document URLs (automatic download and parsing)
        - Registered connectors (GitHub, web search, etc.)

        Args:
            task: The task/topic to collect evidence for
            enabled_connectors: List of connector names to use
            fetch_urls: Override for URL fetching behavior.
                       - None (default): Use settings (ARAGORA_URL_FETCH_ALL_ENABLED)
                       - True: Allow any URL with safety checks
                       - False: Strict allowlist mode
            document_files: Optional list of document file paths to parse

        Returns:
            EvidencePack with collected evidence snippets
        """
        if enabled_connectors is None:
            enabled_connectors = list(self.connectors.keys())

        # Determine URL fetching mode (explicit parameter > settings > default)
        allow_all_urls = fetch_urls if fetch_urls is not None else self._url_fetch_all_enabled

        all_snippets = []
        total_searched = 0

        # Query-before-action: Check KM for existing evidence on this topic
        # This avoids redundant external API calls and leverages organizational memory
        km_evidence = self.query_km_for_existing(task, limit=10, min_reliability=0.6)
        if km_evidence:
            logger.info(
                "Found %s existing evidence items in KM for: %s...", len(km_evidence), task[:50]
            )
            # Convert KM results to EvidenceSnippet format
            for ev in km_evidence:
                snippet = EvidenceSnippet(
                    id=ev.get(
                        "id", f"km_{hashlib.sha256(ev.get('snippet', '').encode()).hexdigest()[:8]}"
                    ),
                    source=f"km:{ev.get('source', 'knowledge_mound')}",
                    title=ev.get("title", "Knowledge Mound Evidence"),
                    snippet=ev.get("snippet", ""),
                    url=ev.get("url", ""),
                    reliability_score=ev.get("reliability_score", 0.7),
                    metadata={"km_origin": True, **ev.get("metadata", {})},
                )
                all_snippets.append(snippet)
            total_searched += 1  # Count KM as one source searched

        # Parse explicitly provided document files
        if document_files:
            for file_path in document_files:
                doc_snippets = await self.parse_document_file(file_path)
                if doc_snippets:
                    all_snippets.extend(doc_snippets)
                    total_searched += 1
                    logger.info("Added %s snippets from document: %s", len(doc_snippets), file_path)

        # Detect document file paths mentioned in the task
        detected_paths = self._extract_document_paths(task)
        for path_str in detected_paths:
            path = Path(path_str)
            if path.exists() and path.is_file():
                doc_snippets = await self.parse_document_file(path)
                if doc_snippets:
                    all_snippets.extend(doc_snippets)
                    total_searched += 1
                    logger.info("Auto-detected and parsed document: %s", path)

        # First, fetch any explicit URLs mentioned in the task (with SSRF protection)
        explicit_urls = self._extract_urls(task)
        if explicit_urls:
            logger.info("Found %s URL(s) in task: %s", len(explicit_urls), explicit_urls)
            if "web" in self.connectors:
                web_connector = self.connectors["web"]
                for url in explicit_urls:
                    try:
                        # Normalize URL
                        full_url = (
                            url if url.startswith(("http://", "https://")) else f"https://{url}"
                        )
                        parsed = urlparse(full_url)

                        org_id = self._org_id or "unknown"

                        # SSRF Protection: Always check basic safety first
                        if not self._is_safe_url(full_url):
                            logger.warning("SSRF: Blocked unsafe URL: %s", full_url)
                            self._log_audit(full_url, org_id, "blocked_ssrf", False)
                            continue

                        # Then check allowlist (unless feature flag bypasses it)
                        if not allow_all_urls and not self._is_domain_allowed(parsed.netloc):
                            logger.info("Skipping non-allowlisted URL: %s", full_url)
                            self._log_audit(full_url, org_id, "blocked_domain", False)
                            continue

                        # Consent gate: require explicit consent if configured
                        if not self._check_url_consent(full_url):
                            continue

                        # Special handling for GitHub repos: fetch README
                        if self._is_github_repo_url(full_url):
                            readme_snippet = await self._fetch_github_readme(
                                full_url, web_connector
                            )
                            if readme_snippet:
                                all_snippets.append(readme_snippet)
                                total_searched += 1
                                logger.info(
                                    "Fetched GitHub README: %s (%s chars)",
                                    full_url,
                                    len(readme_snippet.snippet),
                                )
                                continue  # Skip regular URL fetch for repos

                        # Check if URL points to a document
                        if self._is_document_url(full_url):
                            # Fetch and parse document
                            if hasattr(web_connector, "fetch_bytes"):
                                try:
                                    doc_bytes = await web_connector.fetch_bytes(full_url)
                                    if doc_bytes:
                                        filename = Path(urlparse(full_url).path).name
                                        doc_snippets = await self.parse_document_bytes(
                                            doc_bytes, filename, source_url=full_url
                                        )
                                        if doc_snippets:
                                            all_snippets.extend(doc_snippets)
                                            total_searched += 1
                                            logger.info("Fetched and parsed document: %s", full_url)
                                            continue
                                except (ConnectionError, TimeoutError, OSError) as e:
                                    logger.warning(
                                        "Failed to fetch document %s (network): %s", full_url, e
                                    )
                                except (ValueError, TypeError, KeyError) as e:
                                    logger.warning(
                                        "Failed to fetch document %s (parse): %s", full_url, e
                                    )

                        # Regular URL fetch
                        if hasattr(web_connector, "fetch_url"):
                            evidence = await web_connector.fetch_url(full_url)
                            if evidence and getattr(evidence, "confidence", 0) > 0:
                                snippet = EvidenceSnippet(
                                    id=f"url_{hashlib.sha256(full_url.encode()).hexdigest()[:12]}",
                                    source="direct_url",
                                    title=getattr(evidence, "title", full_url),
                                    snippet=self._truncate_snippet(evidence.content),
                                    url=full_url,
                                    reliability_score=0.9,  # High reliability for direct URL fetch
                                    metadata={"fetched_directly": True, "original_url": url},
                                )
                                all_snippets.append(snippet)
                                total_searched += 1
                                logger.debug(
                                    "Fetched: %s (%s chars)", full_url, len(evidence.content)
                                )
                    except (ConnectionError, TimeoutError, OSError) as e:
                        logger.warning("Failed to fetch %s (network): %s", url, e)
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.warning("Failed to fetch %s (parse): %s", url, e)

        # Extract keywords from task for search
        keywords = self._extract_keywords(task)
        logger.info("Searching for keywords: %s", keywords)

        # Search all enabled connectors concurrently
        search_tasks = []
        for connector_name in enabled_connectors:
            if connector_name in self.connectors:
                connector = self.connectors[connector_name]
                search_tasks.append(self._search_connector(connector_name, connector, keywords))

        if search_tasks:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("Connector search error: %s", result)
                else:
                    connector_snippets, searched_count = result
                    all_snippets.extend(connector_snippets)
                    total_searched += searched_count

        # Rank and limit snippets
        ranked_snippets = self._rank_snippets(all_snippets, keywords)[: self.max_total_snippets]

        # Record in provenance (optional - method may not exist yet)
        if hasattr(self.provenance_manager, "record_evidence_use"):
            for snippet in ranked_snippets:
                self.provenance_manager.record_evidence_use(snippet.id, task, "debate_context")

        # Emit evidence_found events for real-time UI updates
        if self.event_emitter and ranked_snippets:
            self._emit_evidence_events(ranked_snippets, keywords)

        return EvidencePack(
            topic_keywords=keywords, snippets=ranked_snippets, total_searched=total_searched
        )

    async def _search_connector(
        self, connector_name: str, connector: Connector, keywords: list[str]
    ) -> tuple[list[EvidenceSnippet], int]:
        """Search a single connector and return snippets."""
        try:
            # Build search query from keywords
            query = " ".join(keywords[:3])  # Use top 3 keywords

            # Call connector search (assuming it has a search method)
            if hasattr(connector, "search"):
                results = await connector.search(query, limit=self.max_snippets_per_connector)
            else:
                # Fallback for connectors without search
                results = []

            snippets = []
            for i, result in enumerate(results[: self.max_snippets_per_connector]):
                # Handle Evidence objects (WebConnector) or dict results (others)
                if hasattr(result, "title"):  # Evidence object
                    snippet = EvidenceSnippet(
                        id=f"{connector_name}_{result.id}",
                        source=connector_name,
                        title=result.title,
                        snippet=self._truncate_snippet(result.content),
                        url=result.url or "",
                        reliability_score=self._calculate_reliability_from_evidence(
                            connector_name, result
                        ),
                        metadata=result.metadata,
                    )
                else:  # Dict result from other connectors
                    result_dict = cast(dict[str, Any], result)
                    snippet = EvidenceSnippet(
                        id=f"{connector_name}_{i}",
                        source=connector_name,
                        title=result_dict.get("title", result_dict.get("name", "Unknown")),
                        snippet=self._truncate_snippet(
                            result_dict.get("content", result_dict.get("text", ""))
                        ),
                        url=result_dict.get("url", ""),
                        reliability_score=self._calculate_reliability(connector_name, result_dict),
                        metadata=result_dict,
                    )
                snippets.append(snippet)

            return snippets, len(results)

        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Error searching %s (network): %s", connector_name, e)
            return [], 0
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Error searching %s (data): %s", connector_name, e)
            return [], 0

    def _extract_urls(self, task: str) -> list[str]:
        """Extract explicit URLs and domain references from task description.

        Enhanced detection includes:
        - Full URLs (http/https)
        - www URLs
        - Common domain TLDs
        - GitHub repo references (owner/repo or github.com/owner/repo)
        """
        urls = []

        # Pattern 1: Full URLs with scheme
        full_url_pattern = r"https?://[^\s)<>\[\]\"']+"
        urls.extend(re.findall(full_url_pattern, task, re.IGNORECASE))

        # Pattern 2: www URLs
        www_pattern = r"www\.[^\s)<>\[\]\"']+"
        urls.extend(re.findall(www_pattern, task, re.IGNORECASE))

        # Pattern 3: GitHub repos without scheme (github.com/owner/repo)
        github_pattern = r"\bgithub\.com/([\w.-]+)/([\w.-]+)"
        for match in re.finditer(github_pattern, task, re.IGNORECASE):
            full_match = match.group(0)
            # Only add if not already captured by full URL pattern
            if not any(full_match in url for url in urls):
                urls.append(f"https://{full_match}")

        # Pattern 4: Common domain TLDs
        domain_pattern = (
            r"\b([a-zA-Z0-9][-a-zA-Z0-9]*\."
            r"(?:com|org|net|io|ai|dev|app|co|edu|gov)"
            r"(?:/[^\s)<>\[\]\"']*)?)\b"
        )
        for match in re.findall(domain_pattern, task, re.IGNORECASE):
            if match and match not in urls:
                urls.append(match)

        # Deduplicate while preserving order, normalize trailing slashes
        seen = set()
        unique_urls = []
        for url in urls:
            # Normalize: strip trailing slashes for comparison
            url_normalized = url.rstrip("/").lower()
            if url_normalized not in seen:
                seen.add(url_normalized)
                unique_urls.append(url)
        return unique_urls

    def _is_github_repo_url(self, url: str) -> bool:
        """Check if URL points to a GitHub repository root."""
        pattern = r"^https?://github\.com/([\w.-]+)/([\w.-]+)/?$"
        return bool(re.match(pattern, url, re.IGNORECASE))

    def _parse_github_repo(self, url: str) -> tuple[str, str] | None:
        """Parse owner and repo from GitHub URL."""
        pattern = r"github\.com/([\w.-]+)/([\w.-]+)"
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
        return None

    async def _fetch_github_readme(self, url: str, web_connector: Any) -> EvidenceSnippet | None:
        """Fetch README.md from a GitHub repository.

        Tries multiple branch names (main, master, develop) and README variants.

        Args:
            url: GitHub repository URL
            web_connector: Web connector with fetch_url method

        Returns:
            EvidenceSnippet with README content, or None if not found
        """
        parsed = self._parse_github_repo(url)
        if not parsed:
            return None

        owner, repo = parsed
        branches = ["main", "master", "develop"]
        readme_files = ["README.md", "readme.md", "Readme.md", "README.rst", "README.txt"]

        for branch in branches:
            for readme_file in readme_files:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{readme_file}"
                try:
                    if hasattr(web_connector, "fetch_url"):
                        evidence = await web_connector.fetch_url(raw_url)
                        if evidence and getattr(evidence, "content", ""):
                            content = evidence.content
                            # Skip if it looks like a 404 page
                            if "404" in content[:100] or len(content) < 50:
                                continue

                            logger.info(
                                "Fetched README from %s/%s (%s/%s)",
                                owner,
                                repo,
                                branch,
                                readme_file,
                            )
                            return EvidenceSnippet(
                                id=f"gh_{owner}_{repo}_readme",
                                source="github_readme",
                                title=f"{owner}/{repo} README",
                                snippet=self._truncate_snippet(content),
                                url=f"https://github.com/{owner}/{repo}",
                                reliability_score=0.85,  # High reliability for official README
                                metadata={
                                    "owner": owner,
                                    "repo": repo,
                                    "branch": branch,
                                    "file": readme_file,
                                    "raw_url": raw_url,
                                },
                            )
                except (ConnectionError, TimeoutError, OSError) as e:
                    logger.debug("Failed to fetch %s (network): %s", raw_url, e)
                    continue
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug("Failed to fetch %s (data): %s", raw_url, e)
                    continue

        logger.warning("Could not find README for %s/%s", owner, repo)
        return None

    def _extract_keywords(self, task: str) -> list[str]:
        """Extract search keywords from task description."""
        # Simple keyword extraction - split and filter
        words = re.findall(r"\b\w+\b", task.lower())

        # Remove stop words
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
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
            "can",
            "shall",
            "over",
            "under",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "from",
            "up",
            "down",
            "out",
            "off",
            "about",
            "between",
            "against",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
        }
        keywords = [word for word in words if len(word) > 2 and word not in stop_words]

        # Get unique keywords, prioritize nouns/important terms
        unique_keywords = list(set(keywords))

        # Boost keywords that appear in task title or are technical
        boosted = []
        for keyword in unique_keywords:
            if any(char in keyword for char in ["#", "ai", "tech", "data", "system", "code"]):
                boosted.extend([keyword] * 2)  # Duplicate for higher weight
            else:
                boosted.append(keyword)

        return boosted[:5]  # Top 5 keywords

    def _truncate_snippet(self, text: str) -> str:
        """Truncate snippet to max length, trying to end at sentence boundary."""
        if len(text) <= self.snippet_max_length:
            return text

        truncated = text[: self.snippet_max_length]

        # Try to find sentence end
        last_sentence_end = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))

        if last_sentence_end > self.snippet_max_length * 0.7:  # If we can keep most of it
            return truncated[: last_sentence_end + 1]

        return truncated + "..."

    def _calculate_reliability(self, connector_name: str, result: dict[str, Any]) -> float:
        """Calculate reliability score based on source and metadata."""
        base_scores = {
            "github": 0.8,  # Code/docs from GitHub
            "local_docs": 0.9,  # Local documentation
            "web_search": 0.6,  # General web results
            "academic": 0.9,  # Academic sources
        }

        base_score = base_scores.get(connector_name, 0.5)

        # Adjust based on metadata
        if result.get("verified", False):
            base_score += 0.1
        if result.get("recent", False):
            base_score += 0.05
        if len(result.get("content", "")) > 1000:  # Substantial content
            base_score += 0.05

        return min(1.0, base_score)

    def _calculate_reliability_from_evidence(self, connector_name: str, evidence) -> float:
        """Calculate reliability score from Evidence object."""
        base_scores = {
            "github": 0.8,
            "local_docs": 0.9,
            "web": 0.6,  # WebConnector uses 'web' as source
            "academic": 0.9,
        }

        base_score = base_scores.get(connector_name, 0.5)

        # Use evidence authority and confidence
        base_score = (base_score + evidence.authority + evidence.confidence) / 3.0

        # Adjust based on content length
        if len(evidence.content) > 1000:
            base_score += 0.05

        return min(1.0, base_score)

    def _rank_snippets(
        self, snippets: list[EvidenceSnippet], keywords: list[str]
    ) -> list[EvidenceSnippet]:
        """Rank snippets by relevance, reliability, and freshness."""

        def score_snippet(snippet: EvidenceSnippet) -> float:
            relevance_score = 0.0
            text_lower = (snippet.title + " " + snippet.snippet).lower()

            for keyword in keywords:
                if keyword.lower() in text_lower:
                    relevance_score += 1

            # Boost for keyword matches in title
            title_lower = snippet.title.lower()
            for keyword in keywords:
                if keyword.lower() in title_lower:
                    relevance_score += 0.5

            # Normalize relevance (max ~5 keywords)
            relevance_normalized = min(1.0, relevance_score / 5)

            # Combined scoring: relevance (50%), reliability (35%), freshness (15%)
            return (
                relevance_normalized * 0.50
                + snippet.reliability_score * 0.35
                + snippet.freshness_score * 0.15
            )

        return sorted(snippets, key=score_snippet, reverse=True)

    async def collect_for_claims(
        self,
        claims: list[str],
        enabled_connectors: list[str] | None = None,
        max_per_claim: int = 2,
    ) -> EvidencePack:
        """Collect evidence specifically for a list of claims.

        This is used during debate rounds to refresh evidence based on
        claims that emerge from proposals and critiques.

        Args:
            claims: List of claim strings to find evidence for
            enabled_connectors: Optional list of connector names to use
            max_per_claim: Maximum snippets to collect per claim

        Returns:
            EvidencePack with evidence snippets for the claims
        """
        if enabled_connectors is None:
            enabled_connectors = list(self.connectors.keys())

        if not claims:
            return EvidencePack(
                topic_keywords=[],
                snippets=[],
                total_searched=0,
            )

        all_snippets: list[EvidenceSnippet] = []
        total_searched = 0
        all_keywords: list[str] = []

        # Process each claim
        for claim in claims[:5]:  # Limit to 5 claims to avoid API overload
            # Extract keywords from the claim
            claim_keywords = self._extract_keywords(claim)
            all_keywords.extend(claim_keywords)

            # Search connectors for this claim
            search_tasks = []
            for connector_name in enabled_connectors:
                if connector_name in self.connectors:
                    connector = self.connectors[connector_name]
                    search_tasks.append(
                        self._search_connector(connector_name, connector, claim_keywords)
                    )

            if search_tasks:
                results = await asyncio.gather(*search_tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, BaseException):
                        logger.warning("Connector search error for claim: %s", result)
                    else:
                        connector_snippets, searched_count = result
                        # Limit per claim
                        all_snippets.extend(connector_snippets[:max_per_claim])
                        total_searched += searched_count

        # Deduplicate by snippet content hash
        seen_hashes: set = set()
        unique_snippets: list[EvidenceSnippet] = []
        for snippet in all_snippets:
            content_hash = hashlib.md5(snippet.snippet.encode(), usedforsecurity=False).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique_snippets.append(snippet)

        # Rank and limit
        unique_keywords = list(set(all_keywords))
        ranked_snippets = self._rank_snippets(unique_snippets, unique_keywords)
        final_snippets = ranked_snippets[: self.max_total_snippets]

        logger.info(
            "evidence_for_claims claims=%s snippets=%s searched=%s",
            len(claims),
            len(final_snippets),
            total_searched,
        )

        return EvidencePack(
            topic_keywords=unique_keywords[:10],
            snippets=final_snippets,
            total_searched=total_searched,
        )

    def extract_claims_from_text(self, text: str) -> list[str]:
        """Extract factual claims from text that could benefit from evidence.

        Looks for:
        - Statements with numbers or statistics
        - Statements with definitive language ("is", "are", "proven")
        - Comparative statements ("better than", "faster than")
        - References to studies, research, or sources

        Args:
            text: Text to extract claims from

        Returns:
            List of claim strings
        """
        claims: list[str] = []

        # Split into sentences
        sentences = re.split(r"[.!?]\s+", text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 500:
                continue

            # Check for claim indicators
            claim_indicators = [
                r"\d+%",  # Percentages
                r"\d+ (times|percent|million|billion)",  # Quantitative claims
                r"(studies|research|evidence) (show|suggest|indicate)",
                r"(proven|demonstrated|established) that",
                r"(better|worse|faster|slower|more|less) than",
                r"according to",
                r"(is|are) (known|considered|recognized)",
                r"(always|never|all|none|every)",  # Absolute claims
            ]

            for pattern in claim_indicators:
                if re.search(pattern, sentence, re.IGNORECASE):
                    claims.append(sentence)
                    break

        # Deduplicate
        return list(dict.fromkeys(claims))[:10]  # Max 10 claims


__all__ = [
    "EvidenceSnippet",
    "EvidencePack",
    "EvidenceCollector",
    "DEFAULT_ALLOWED_DOMAINS",
]
