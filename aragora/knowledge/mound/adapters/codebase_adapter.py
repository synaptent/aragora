"""
CodebaseAdapter - Bridges codebase structure to the Knowledge Mound.

This adapter enables code-grounded debates by persisting codebase structures:

- Data flow IN: Symbols, dependency graphs, and patterns from crawl results
- Data flow IN: Code definitions with file paths and line numbers
- Reverse flow: KM can retrieve code-tagged items for debate context

The adapter provides:
- Crawl result ingestion as knowledge items (symbols, patterns, imports)
- Dependency graph persistence for structural queries
- Bidirectional sync for code-aware debate agents

"Debates about code should be grounded in the actual codebase."
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.unified.types import (
    ConfidenceLevel,
    KnowledgeItem,
    KnowledgeSource,
)

if TYPE_CHECKING:
    pass

CODEBASE_SOURCE = KnowledgeSource.DEBATE

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None]


class CodebaseAdapterError(Exception):
    """Base exception for codebase adapter errors."""


@dataclass
class CodebaseSyncResult:
    """Result of syncing codebase structures to Knowledge Mound."""

    definitions_ingested: int
    patterns_ingested: int
    imports_ingested: int
    knowledge_item_ids: list[str]
    errors: list[str]

    @property
    def total_ingested(self) -> int:
        return self.definitions_ingested + self.patterns_ingested + self.imports_ingested

    @property
    def success(self) -> bool:
        return len(self.errors) == 0 and self.total_ingested > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "definitions_ingested": self.definitions_ingested,
            "patterns_ingested": self.patterns_ingested,
            "imports_ingested": self.imports_ingested,
            "total_ingested": self.total_ingested,
            "knowledge_item_ids": self.knowledge_item_ids,
            "errors": self.errors,
            "success": self.success,
        }


class CodebaseAdapter(KnowledgeMoundAdapter):
    """
    Adapter that bridges codebase structure to the Knowledge Mound.

    Provides methods to:
    - Ingest crawl results (symbols, imports, patterns) as knowledge items
    - Query code-tagged items from KM for debate context
    - Crawl and sync in a single convenience call

    Usage:
        from aragora.knowledge.mound.adapters.codebase_adapter import CodebaseAdapter
        from aragora.knowledge.mound.core import KnowledgeMound

        mound = KnowledgeMound()
        adapter = CodebaseAdapter(mound)

        # Sync from a crawl result
        result = await adapter.sync_to_km(crawl_result, workspace_id="ws-123")

        # Query code items
        items = await adapter.sync_from_km("database connection", limit=5)
    """

    adapter_name = "codebase"

    DEFINITION_PREFIX = "cdef_"
    PATTERN_PREFIX = "cpat_"
    IMPORT_PREFIX = "cimp_"

    def __init__(
        self,
        mound: Any | None = None,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )
        self._mound = mound
        self._sync_results: dict[str, CodebaseSyncResult] = {}

    def set_mound(self, mound: Any) -> None:
        """Set the Knowledge Mound instance."""
        self._mound = mound

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                pass

    async def sync_to_km(
        self,
        crawl_result: Any,
        workspace_id: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """
        Sync codebase structures from a CrawlResult to Knowledge Mound.

        Args:
            crawl_result: A CrawlResult from RepositoryCrawler
            workspace_id: Optional workspace for scoping
            tags: Optional tags to apply to all items

        Returns:
            Number of items ingested
        """
        errors: list[str] = []
        knowledge_item_ids: list[str] = []
        definitions_ingested = 0
        patterns_ingested = 0
        imports_ingested = 0

        if not self._mound:
            errors.append("Knowledge Mound not configured")
            result = CodebaseSyncResult(
                definitions_ingested=0,
                patterns_ingested=0,
                imports_ingested=0,
                knowledge_item_ids=[],
                errors=errors,
            )
            repo_name = getattr(crawl_result, "repository_name", "unknown")
            self._sync_results[repo_name] = result
            return 0

        base_tags = list(tags or [])
        repo_name = getattr(crawl_result, "repository_name", "unknown")
        base_tags.append(f"repo:{repo_name}")

        # 1. Ingest file definitions (classes, functions from crawled files)
        files = getattr(crawl_result, "files", [])
        for crawled_file in files:
            file_path = getattr(crawled_file, "relative_path", "") or getattr(
                crawled_file, "path", ""
            )
            symbols = getattr(crawled_file, "symbols", [])
            for symbol in symbols:
                try:
                    item = self._symbol_to_knowledge_item(
                        symbol, file_path, repo_name, workspace_id, base_tags
                    )
                    item_id = await self._store_item(item)
                    if item_id:
                        knowledge_item_ids.append(item_id)
                        definitions_ingested += 1
                except (RuntimeError, ValueError, OSError, AttributeError) as e:
                    logger.warning("Symbol ingestion failed: %s", e)
                    errors.append("Failed to ingest symbol")

        # 2. Ingest dependency graph as pattern items
        dep_graph = getattr(crawl_result, "dependency_graph", {})
        for source_file, deps in dep_graph.items():
            if not deps:
                continue
            try:
                item = self._dependency_to_knowledge_item(
                    source_file, deps, repo_name, workspace_id, base_tags
                )
                item_id = await self._store_item(item)
                if item_id:
                    knowledge_item_ids.append(item_id)
                    imports_ingested += 1
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Dependency ingestion failed: %s", e)
                errors.append("Failed to ingest dependency")

        # 3. Ingest file type distribution as a pattern
        file_type_counts = getattr(crawl_result, "file_type_counts", {})
        if file_type_counts:
            try:
                item = self._file_types_to_knowledge_item(
                    file_type_counts, repo_name, workspace_id, base_tags
                )
                item_id = await self._store_item(item)
                if item_id:
                    knowledge_item_ids.append(item_id)
                    patterns_ingested += 1
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("File type pattern ingestion failed: %s", e)
                errors.append("Failed to ingest file type pattern")

        result = CodebaseSyncResult(
            definitions_ingested=definitions_ingested,
            patterns_ingested=patterns_ingested,
            imports_ingested=imports_ingested,
            knowledge_item_ids=knowledge_item_ids,
            errors=errors,
        )
        self._sync_results[repo_name] = result

        self._emit_event(
            "codebase_synced",
            {
                "repository": repo_name,
                "definitions": definitions_ingested,
                "patterns": patterns_ingested,
                "imports": imports_ingested,
            },
        )

        logger.info(
            "codebase_synced",
            extra={
                "repository": repo_name,
                "definitions": definitions_ingested,
                "patterns": patterns_ingested,
                "imports": imports_ingested,
            },
        )

        return result.total_ingested

    async def sync_from_km(
        self,
        query: str,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> list[KnowledgeItem]:
        """
        Pull code-tagged items from Knowledge Mound.

        Args:
            query: Search query
            workspace_id: Optional workspace filter
            limit: Maximum results

        Returns:
            List of code-related knowledge items
        """
        if not self._mound:
            return []

        try:
            if hasattr(self._mound, "query"):
                results = await self._mound.query(
                    query=query,
                    tags=["codebase"],
                    workspace_id=workspace_id,
                    limit=limit,
                )
                return results.items if hasattr(results, "items") else []
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to query codebase items from KM: %s", e)

        return []

    async def crawl_and_sync(
        self,
        source: str,
        workspace_id: str | None = None,
    ) -> int:
        """
        Convenience: crawl a repository and sync results to KM.

        Args:
            source: Path to repository
            workspace_id: Optional workspace for scoping

        Returns:
            Number of items ingested
        """
        try:
            from aragora.analysis.codebase.repository_crawler import RepositoryCrawler

            crawler = RepositoryCrawler()
            crawl_result = await crawler.crawl(source=source)
            return await self.sync_to_km(crawl_result, workspace_id=workspace_id)
        except ImportError:
            logger.warning("RepositoryCrawler not available")
            return 0
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Crawl and sync failed: %s", e)
            return 0

    def _symbol_to_knowledge_item(
        self,
        symbol: Any,
        file_path: str,
        repo_name: str,
        workspace_id: str | None,
        tags: list[str],
    ) -> KnowledgeItem:
        """Convert a code symbol to a knowledge item."""
        name = getattr(symbol, "name", str(symbol))
        kind = getattr(symbol, "kind", "unknown")
        line = getattr(symbol, "line", 0)
        docstring = getattr(symbol, "docstring", "") or ""

        content_hash = hashlib.sha256(f"{file_path}:{name}:{kind}".encode()).hexdigest()[:12]
        item_id = f"{self.DEFINITION_PREFIX}{content_hash}"

        content = f"[{kind}] {name} in {file_path}"
        if line:
            content += f":{line}"
        if docstring:
            content += f"\n{docstring[:300]}"

        now = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=item_id,
            content=content,
            source=CODEBASE_SOURCE,
            source_id=f"{repo_name}:{file_path}",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            metadata={
                "repository": repo_name,
                "file_path": file_path,
                "symbol_name": name,
                "symbol_kind": kind,
                "line_number": line,
                "workspace_id": workspace_id or "",
                "tags": tags + ["codebase", "code_definition", f"kind:{kind}"],
                "item_type": "code_definition",
            },
        )

    def _dependency_to_knowledge_item(
        self,
        source_file: str,
        deps: list[str],
        repo_name: str,
        workspace_id: str | None,
        tags: list[str],
    ) -> KnowledgeItem:
        """Convert a file's dependency list to a knowledge item."""
        dep_hash = hashlib.sha256(f"{source_file}:{','.join(deps[:20])}".encode()).hexdigest()[:12]
        item_id = f"{self.IMPORT_PREFIX}{dep_hash}"

        content = f"Import graph for {source_file}:\n"
        for dep in deps[:30]:
            content += f"  → {dep}\n"
        if len(deps) > 30:
            content += f"  ... and {len(deps) - 30} more\n"

        now = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=item_id,
            content=content,
            source=CODEBASE_SOURCE,
            source_id=f"{repo_name}:{source_file}",
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            metadata={
                "repository": repo_name,
                "file_path": source_file,
                "dependency_count": len(deps),
                "dependencies": deps[:50],
                "workspace_id": workspace_id or "",
                "tags": tags + ["codebase", "import_graph"],
                "item_type": "import_graph",
            },
        )

    def _file_types_to_knowledge_item(
        self,
        file_type_counts: dict[str, int],
        repo_name: str,
        workspace_id: str | None,
        tags: list[str],
    ) -> KnowledgeItem:
        """Convert file type distribution to a knowledge item."""
        content_hash = hashlib.sha256(
            f"{repo_name}:filetypes:{sum(file_type_counts.values())}".encode()
        ).hexdigest()[:12]
        item_id = f"{self.PATTERN_PREFIX}{content_hash}"

        lines = [f"File type distribution for {repo_name}:"]
        for ext, count in sorted(file_type_counts.items(), key=lambda x: -x[1])[:20]:
            lines.append(f"  {ext}: {count} files")
        content = "\n".join(lines)

        now = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=item_id,
            content=content,
            source=CODEBASE_SOURCE,
            source_id=repo_name,
            confidence=ConfidenceLevel.HIGH,
            created_at=now,
            updated_at=now,
            metadata={
                "repository": repo_name,
                "file_type_counts": file_type_counts,
                "workspace_id": workspace_id or "",
                "tags": tags + ["codebase", "code_pattern"],
                "item_type": "code_pattern",
            },
        )

    async def _store_item(self, item: KnowledgeItem) -> str | None:
        """Store a knowledge item in the mound."""
        if not self._mound:
            return None
        try:
            if hasattr(self._mound, "store"):
                result = await self._mound.store(item)
                return result.id if hasattr(result, "id") else item.id
            elif hasattr(self._mound, "ingest"):
                await self._mound.ingest(item)
                return item.id
            return item.id
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to store codebase item %s: %s", item.id, e)
            return None

    def get_sync_result(self, repo_name: str) -> CodebaseSyncResult | None:
        """Get the sync result for a repository."""
        return self._sync_results.get(repo_name)

    def get_stats(self) -> dict[str, Any]:
        """Get adapter statistics."""
        total_defs = sum(r.definitions_ingested for r in self._sync_results.values())
        total_patterns = sum(r.patterns_ingested for r in self._sync_results.values())
        total_imports = sum(r.imports_ingested for r in self._sync_results.values())
        total_errors = sum(len(r.errors) for r in self._sync_results.values())

        return {
            "repos_synced": len(self._sync_results),
            "total_definitions": total_defs,
            "total_patterns": total_patterns,
            "total_imports": total_imports,
            "total_errors": total_errors,
            "mound_connected": self._mound is not None,
        }


__all__ = [
    "CodebaseAdapter",
    "CodebaseAdapterError",
    "CodebaseSyncResult",
]
