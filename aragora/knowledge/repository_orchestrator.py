"""
Repository Orchestrator for coordinating codebase indexing.

This orchestrator wraps the RepositoryCrawler and integrates it with
KnowledgeMound for persistent storage and querying of code knowledge.

Features:
- Concurrent crawling of multiple repositories
- Progress tracking and resumption
- Integration with KnowledgeMound for unified storage
- Relationship graph building from code dependencies
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Sequence

from aragora.analysis.codebase.repository_crawler import (
    CrawlConfig,
    CrawledFile,
    FileSymbol,
    RepositoryCrawler,
)

logger = logging.getLogger(__name__)


@dataclass
class RepoConfig:
    """Configuration for a single repository to index."""

    path: str  # Local path or git URL
    workspace_id: str
    name: str | None = None  # Override auto-detected name
    crawl_config: CrawlConfig | None = None
    priority: int = 0  # Higher = process first
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexResult:
    """Result of indexing a single repository."""

    repository_name: str
    repository_path: str
    workspace_id: str
    files_indexed: int
    nodes_created: int
    relationships_created: int
    symbols_indexed: int
    errors: list[str]
    warnings: list[str]
    duration_ms: float
    git_info: dict[str, Any] | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "repository_name": self.repository_name,
            "repository_path": self.repository_path,
            "workspace_id": self.workspace_id,
            "files_indexed": self.files_indexed,
            "nodes_created": self.nodes_created,
            "relationships_created": self.relationships_created,
            "symbols_indexed": self.symbols_indexed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "duration_ms": self.duration_ms,
            "git_info": self.git_info,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class BatchResult:
    """Result of indexing multiple repositories."""

    repositories: list[IndexResult]
    total_files: int
    total_nodes: int
    total_relationships: int
    total_duration_ms: float
    successful: int
    failed: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "repositories": [r.to_dict() for r in self.repositories],
            "total_files": self.total_files,
            "total_nodes": self.total_nodes,
            "total_relationships": self.total_relationships,
            "total_duration_ms": self.total_duration_ms,
            "successful": self.successful,
            "failed": self.failed,
        }


@dataclass
class OrchestratorConfig:
    """Configuration for the Repository Orchestrator."""

    # Concurrency settings
    max_concurrent_repos: int = 3
    max_concurrent_files_per_repo: int = 20

    # Storage settings
    store_file_content: bool = True
    store_symbols: bool = True
    store_dependencies: bool = True
    store_chunks: bool = True

    # Progress tracking
    checkpoint_enabled: bool = True
    checkpoint_interval_files: int = 100


@dataclass
class IndexProgress:
    """Progress tracking for indexing operations."""

    repository_path: str
    workspace_id: str
    status: str  # pending, crawling, indexing, completed, failed
    files_discovered: int = 0
    files_processed: int = 0
    nodes_created: int = 0
    current_file: str | None = None
    started_at: datetime | None = None
    last_updated: datetime | None = None
    error: str | None = None


class RepositoryOrchestrator:
    """
    High-level orchestrator for managing repository crawling and indexing.

    Coordinates between RepositoryCrawler (for crawling) and KnowledgeMound
    (for storage), providing progress tracking, resumption, and batch operations.
    """

    def __init__(
        self,
        mound: Any,  # KnowledgeMound instance
        config: OrchestratorConfig | None = None,
    ):
        """
        Initialize the Repository Orchestrator.

        Args:
            mound: KnowledgeMound instance for storage
            config: Orchestrator configuration
        """
        self.mound = mound
        self.config = config or OrchestratorConfig()
        self._crawler = RepositoryCrawler()
        self._progress: dict[str, IndexProgress] = {}
        self._active_tasks: dict[str, asyncio.Task[IndexResult]] = {}

    async def index_repository(
        self,
        repo_path: str,
        workspace_id: str,
        crawl_config: CrawlConfig | None = None,
        incremental: bool = True,
    ) -> IndexResult:
        """
        Index a single repository into KnowledgeMound.

        Args:
            repo_path: Path to local repo or git URL
            workspace_id: Workspace for storage isolation
            crawl_config: Optional custom crawl configuration
            incremental: Whether to use incremental crawling

        Returns:
            IndexResult with statistics and any errors
        """
        start_time = datetime.now(timezone.utc)
        errors: list[str] = []
        warnings: list[str] = []

        # Initialize progress tracking
        progress = IndexProgress(
            repository_path=repo_path,
            workspace_id=workspace_id,
            status="crawling",
            started_at=start_time,
        )
        self._progress[repo_path] = progress

        try:
            # Configure crawler
            if crawl_config:
                self._crawler._config = crawl_config
            self._crawler._workspace_id = workspace_id

            # Perform crawl
            logger.info("Starting crawl of %s for workspace %s", repo_path, workspace_id)
            crawl_result = await self._crawler.crawl(repo_path, incremental=incremental)

            progress.status = "indexing"
            progress.files_discovered = crawl_result.total_files

            # Index to mound
            nodes_created = 0
            relationships_created = 0
            symbols_indexed = 0

            for i, crawled_file in enumerate(crawl_result.files):
                try:
                    file_nodes, file_rels, file_syms = await self._index_file(
                        crawled_file, crawl_result.repository_name, workspace_id
                    )
                    nodes_created += file_nodes
                    relationships_created += file_rels
                    symbols_indexed += file_syms

                    progress.files_processed = i + 1
                    progress.nodes_created = nodes_created
                    progress.current_file = crawled_file.relative_path
                    progress.last_updated = datetime.now(timezone.utc)

                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    errors.append(f"Failed to index {crawled_file.relative_path}: {e}")
                    logger.warning("Failed to index file: %s", e)

            # Index dependency graph relationships
            try:
                graph_rels = await self._index_dependency_graph(
                    crawl_result.dependency_graph,
                    crawl_result.repository_name,
                    workspace_id,
                )
                relationships_created += graph_rels
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                warnings.append(f"Failed to index dependency graph: {e}")

            # Calculate duration
            completed_at = datetime.now(timezone.utc)
            duration_ms = (completed_at - start_time).total_seconds() * 1000

            progress.status = "completed"
            progress.last_updated = completed_at

            return IndexResult(
                repository_name=crawl_result.repository_name,
                repository_path=repo_path,
                workspace_id=workspace_id,
                files_indexed=crawl_result.total_files,
                nodes_created=nodes_created,
                relationships_created=relationships_created,
                symbols_indexed=symbols_indexed,
                errors=errors + crawl_result.errors,
                warnings=warnings + crawl_result.warnings,
                duration_ms=duration_ms,
                git_info=crawl_result.git_info,
                started_at=start_time,
                completed_at=completed_at,
            )

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            progress.status = "failed"
            progress.error = f"Indexing failed: {type(e).__name__}"
            logger.warning("Repository indexing failed: %s", e)

            completed_at = datetime.now(timezone.utc)
            duration_ms = (completed_at - start_time).total_seconds() * 1000

            return IndexResult(
                repository_name=Path(repo_path).name,
                repository_path=repo_path,
                workspace_id=workspace_id,
                files_indexed=0,
                nodes_created=0,
                relationships_created=0,
                symbols_indexed=0,
                errors=["Repository indexing failed"],
                warnings=warnings,
                duration_ms=duration_ms,
                started_at=start_time,
                completed_at=completed_at,
            )

    async def incremental_update(
        self,
        repo_path: str,
        workspace_id: str,
    ) -> IndexResult:
        """
        Perform incremental update since last crawl.

        Args:
            repo_path: Path to local repository
            workspace_id: Workspace for storage isolation

        Returns:
            IndexResult with update statistics
        """
        return await self.index_repository(repo_path, workspace_id, incremental=True)

    async def index_multiple(
        self,
        repos: Sequence[RepoConfig],
    ) -> BatchResult:
        """
        Index multiple repositories concurrently.

        Args:
            repos: List of repository configurations

        Returns:
            BatchResult with aggregate statistics
        """
        start_time = datetime.now(timezone.utc)

        # Sort by priority (higher first)
        sorted_repos = sorted(repos, key=lambda r: r.priority, reverse=True)

        # Process in batches based on concurrency limit
        results: list[IndexResult] = []
        semaphore = asyncio.Semaphore(self.config.max_concurrent_repos)

        async def index_with_semaphore(repo: RepoConfig) -> IndexResult:
            async with semaphore:
                return await self.index_repository(
                    repo_path=repo.path,
                    workspace_id=repo.workspace_id,
                    crawl_config=repo.crawl_config,
                    incremental=True,
                )

        tasks = [index_with_semaphore(repo) for repo in sorted_repos]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Calculate aggregates
        total_files = sum(r.files_indexed for r in results)
        total_nodes = sum(r.nodes_created for r in results)
        total_relationships = sum(r.relationships_created for r in results)
        successful = sum(1 for r in results if not r.errors)
        failed = len(results) - successful

        completed_at = datetime.now(timezone.utc)
        duration_ms = (completed_at - start_time).total_seconds() * 1000

        return BatchResult(
            repositories=results,
            total_files=total_files,
            total_nodes=total_nodes,
            total_relationships=total_relationships,
            total_duration_ms=duration_ms,
            successful=successful,
            failed=failed,
        )

    def get_progress(self, repo_path: str) -> IndexProgress | None:
        """Get progress for an ongoing indexing operation."""
        return self._progress.get(repo_path)

    def get_all_progress(self) -> dict[str, IndexProgress]:
        """Get progress for all tracked indexing operations."""
        return dict(self._progress)

    async def _index_file(
        self,
        crawled_file: CrawledFile,
        repository_name: str,
        workspace_id: str,
    ) -> tuple[int, int, int]:
        """
        Index a single crawled file to KnowledgeMound.

        Returns:
            Tuple of (nodes_created, relationships_created, symbols_indexed)
        """
        nodes_created = 0
        relationships_created = 0
        symbols_indexed = 0

        base_metadata = {
            "source": "repository_crawler",
            "repository": repository_name,
            "file_path": crawled_file.relative_path,
            "file_type": crawled_file.file_type.value,
            "line_count": crawled_file.line_count,
            "content_hash": crawled_file.content_hash,
        }

        # Index file chunks
        if self.config.store_chunks and crawled_file.chunks:
            for chunk in crawled_file.chunks:
                try:
                    await self.mound.add(
                        content=chunk["content"],
                        metadata={
                            **base_metadata,
                            "chunk_index": chunk["index"],
                            "start_line": chunk["start_line"],
                            "end_line": chunk["end_line"],
                        },
                        workspace_id=workspace_id,
                        node_type="code_chunk",
                    )
                    nodes_created += 1
                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    logger.debug("Failed to index chunk: %s", e)

        # Index symbols
        if self.config.store_symbols:
            for symbol in crawled_file.symbols:
                symbols_indexed += 1
                if symbol.docstring or symbol.signature:
                    content = self._format_symbol_content(symbol, crawled_file.relative_path)
                    try:
                        await self.mound.add(
                            content=content,
                            metadata={
                                **base_metadata,
                                "symbol_name": symbol.name,
                                "symbol_kind": symbol.kind,
                                "line_start": symbol.line_start,
                                "line_end": symbol.line_end,
                                "parent": symbol.parent,
                            },
                            workspace_id=workspace_id,
                            node_type="code_symbol",
                        )
                        nodes_created += 1
                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        logger.debug("Failed to index symbol: %s", e)

        # Index file-level dependencies as relationships
        if self.config.store_dependencies:
            for dep in crawled_file.dependencies:
                try:
                    # Store dependency as a fact
                    await self.mound.add(
                        content=f"{crawled_file.relative_path} {dep.kind}s {dep.target}",
                        metadata={
                            **base_metadata,
                            "dependency_target": dep.target,
                            "dependency_kind": dep.kind,
                            "dependency_line": dep.line,
                        },
                        workspace_id=workspace_id,
                        node_type="code_dependency",
                    )
                    relationships_created += 1
                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    logger.debug("Failed to index dependency: %s", e)

        return nodes_created, relationships_created, symbols_indexed

    async def _index_dependency_graph(
        self,
        dependency_graph: dict[str, list[str]],
        repository_name: str,
        workspace_id: str,
    ) -> int:
        """
        Index the repository's dependency graph.

        Returns:
            Number of relationships created
        """
        relationships_created = 0

        for source, targets in dependency_graph.items():
            for target in targets:
                try:
                    await self.mound.add(
                        content=f"File dependency: {source} -> {target}",
                        metadata={
                            "source": "repository_crawler",
                            "repository": repository_name,
                            "relationship_type": "depends_on",
                            "source_file": source,
                            "target_file": target,
                        },
                        workspace_id=workspace_id,
                        node_type="code_relationship",
                    )
                    relationships_created += 1
                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    logger.debug("Failed to index graph edge: %s", e)

        return relationships_created

    def _format_symbol_content(self, symbol: FileSymbol, file_path: str) -> str:
        """Format a symbol for indexing."""
        parts = [f"{symbol.kind} {symbol.name}"]

        if symbol.parent:
            parts.append(f"in {symbol.parent}")

        parts.append(f"({file_path}:{symbol.line_start})")

        if symbol.signature:
            parts.append(f"\nSignature: {symbol.signature}")

        if symbol.docstring:
            parts.append(f"\n{symbol.docstring}")

        return " ".join(parts)

    async def remove_repository(
        self,
        repository_name: str,
        workspace_id: str,
    ) -> int:
        """
        Remove all indexed content for a repository.

        Args:
            repository_name: Name of the repository
            workspace_id: Workspace containing the repository

        Returns:
            Number of nodes removed
        """
        # Query for all nodes from this repository
        try:
            results = await self.mound.query(
                query=f"repository:{repository_name}",
                limit=10000,
            )
            removed = 0
            for item in results.items:
                if hasattr(self.mound, "delete"):
                    await self.mound.delete(item.id)
                    removed += 1
            return removed
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to remove repository %s: %s", repository_name, e)
            return 0

    async def get_repository_stats(
        self,
        repository_name: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        """
        Get statistics for an indexed repository.

        Args:
            repository_name: Name of the repository
            workspace_id: Workspace containing the repository

        Returns:
            Dictionary with repository statistics
        """
        try:
            # Query for repository content
            results = await self.mound.query(
                query=f"repository:{repository_name}",
                limit=1,
            )

            # Get counts by node type
            stats = {
                "repository_name": repository_name,
                "workspace_id": workspace_id,
                "indexed": results.total_count > 0,
                "total_nodes": results.total_count,
            }

            return stats
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to get stats for %s: %s", repository_name, e)
            return {
                "repository_name": repository_name,
                "workspace_id": workspace_id,
                "indexed": False,
                "error": "Failed to get repository stats",
            }
