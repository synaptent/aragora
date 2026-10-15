"""
Relationship Builder for constructing cross-file dependency graphs.

This module builds relationship graphs from CodeEntities extracted by
the RepositoryCrawler, enabling queries like "what depends on this file?"
and "what files does this function call?".

Relationship Types:
- imports: File A imports module B
- calls: Function A calls Function B
- inherits: Class A extends Class B
- implements: Class A implements Interface B
- references: Entity A references Entity B
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.analysis.codebase.repository_crawler import (
    CrawledFile,
    CrawlResult,
    FileDependency,
    FileSymbol,
)

logger = logging.getLogger(__name__)


class RelationshipKind(str, Enum):
    """Types of relationships between code entities."""

    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    CONTAINS = "contains"  # File contains symbol
    MEMBER_OF = "member_of"  # Method member of class
    USES = "uses"  # Generic usage


@dataclass
class CodeEntity:
    """A code entity that can participate in relationships."""

    id: str
    name: str
    kind: str  # file, class, function, method, variable
    file_path: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, crawled_file: CrawledFile, repository: str) -> CodeEntity:
        """Create a CodeEntity from a CrawledFile."""
        return cls(
            id=f"{repository}:{crawled_file.relative_path}",
            name=crawled_file.relative_path,
            kind="file",
            file_path=crawled_file.relative_path,
            line_start=1,
            line_end=crawled_file.line_count,
            metadata={
                "file_type": crawled_file.file_type.value,
                "content_hash": crawled_file.content_hash,
                "size_bytes": crawled_file.size_bytes,
            },
        )

    @classmethod
    def from_symbol(cls, symbol: FileSymbol, file_path: str, repository: str) -> CodeEntity:
        """Create a CodeEntity from a FileSymbol."""
        entity_id = f"{repository}:{file_path}:{symbol.name}"
        if symbol.parent:
            entity_id = f"{repository}:{file_path}:{symbol.parent}.{symbol.name}"

        return cls(
            id=entity_id,
            name=symbol.name,
            kind=symbol.kind,
            file_path=file_path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            signature=symbol.signature,
            docstring=symbol.docstring,
            parent_id=f"{repository}:{file_path}:{symbol.parent}" if symbol.parent else None,
        )


@dataclass
class Relationship:
    """A relationship between two code entities."""

    source_id: str
    target_id: str
    kind: RelationshipKind
    weight: float = 1.0
    line: int | None = None  # Line where relationship is declared
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "weight": self.weight,
            "line": self.line,
            "metadata": self.metadata,
        }


@dataclass
class RelationshipGraph:
    """A graph of code entities and their relationships."""

    entities: dict[str, CodeEntity]
    relationships: list[Relationship]
    # Adjacency lists for quick traversal
    outgoing: dict[str, list[Relationship]]  # entity_id -> outgoing relationships
    incoming: dict[str, list[Relationship]]  # entity_id -> incoming relationships

    def __init__(self):
        self.entities = {}
        self.relationships = []
        self.outgoing = defaultdict(list)
        self.incoming = defaultdict(list)

    def add_entity(self, entity: CodeEntity) -> None:
        """Add an entity to the graph."""
        self.entities[entity.id] = entity

    def add_relationship(self, relationship: Relationship) -> None:
        """Add a relationship to the graph."""
        self.relationships.append(relationship)
        self.outgoing[relationship.source_id].append(relationship)
        self.incoming[relationship.target_id].append(relationship)

    def get_dependencies(
        self,
        entity_id: str,
        relationship_kinds: set[RelationshipKind] | None = None,
    ) -> list[CodeEntity]:
        """Get entities that this entity depends on."""
        result = []
        for rel in self.outgoing.get(entity_id, []):
            if relationship_kinds is None or rel.kind in relationship_kinds:
                if rel.target_id in self.entities:
                    result.append(self.entities[rel.target_id])
        return result

    def get_dependents(
        self,
        entity_id: str,
        relationship_kinds: set[RelationshipKind] | None = None,
    ) -> list[CodeEntity]:
        """Get entities that depend on this entity."""
        result = []
        for rel in self.incoming.get(entity_id, []):
            if relationship_kinds is None or rel.kind in relationship_kinds:
                if rel.source_id in self.entities:
                    result.append(self.entities[rel.source_id])
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "entities": {
                eid: {
                    "name": e.name,
                    "kind": e.kind,
                    "file_path": e.file_path,
                }
                for eid, e in self.entities.items()
            },
            "relationships": [r.to_dict() for r in self.relationships],
        }


class RelationshipBuilder:
    """
    Builds cross-file relationship graphs from crawl results.

    Takes the output of RepositoryCrawler and constructs a queryable
    graph of relationships between files, classes, functions, etc.
    """

    def __init__(self, repository_name: str):
        """
        Initialize the RelationshipBuilder.

        Args:
            repository_name: Name of the repository being analyzed
        """
        self.repository_name = repository_name
        self._graph = RelationshipGraph()
        self._symbol_index: dict[str, str] = {}  # symbol_name -> entity_id

    async def build_graph(
        self,
        crawl_result: CrawlResult,
    ) -> RelationshipGraph:
        """
        Build a relationship graph from crawl results.

        Args:
            crawl_result: Results from RepositoryCrawler

        Returns:
            RelationshipGraph with all entities and relationships
        """
        self._graph = RelationshipGraph()
        self._symbol_index = {}

        # Phase 1: Index all entities
        for crawled_file in crawl_result.files:
            self._index_file_entities(crawled_file)

        # Phase 2: Build relationships
        for crawled_file in crawl_result.files:
            self._build_file_relationships(crawled_file)

        # Phase 3: Add dependency graph relationships
        self._build_dependency_relationships(crawl_result.dependency_graph)

        logger.info(
            "Built relationship graph: %s entities, %s relationships",
            len(self._graph.entities),
            len(self._graph.relationships),
        )

        return self._graph

    async def find_dependencies(
        self,
        entity_id: str,
        depth: int = 2,
        relationship_kinds: set[RelationshipKind] | None = None,
    ) -> list[CodeEntity]:
        """
        Find all dependencies of an entity up to a given depth.

        Args:
            entity_id: ID of the starting entity
            depth: Maximum traversal depth
            relationship_kinds: Filter by relationship kinds

        Returns:
            List of dependent entities
        """
        result: list[CodeEntity] = []
        visited: set[str] = {entity_id}
        current_level = [entity_id]

        for _ in range(depth):
            next_level = []
            for eid in current_level:
                deps = self._graph.get_dependencies(eid, relationship_kinds)
                for dep in deps:
                    if dep.id not in visited:
                        visited.add(dep.id)
                        result.append(dep)
                        next_level.append(dep.id)
            current_level = next_level
            if not current_level:
                break

        return result

    async def find_dependents(
        self,
        entity_id: str,
        depth: int = 2,
        relationship_kinds: set[RelationshipKind] | None = None,
    ) -> list[CodeEntity]:
        """
        Find all entities that depend on this entity.

        Args:
            entity_id: ID of the starting entity
            depth: Maximum traversal depth
            relationship_kinds: Filter by relationship kinds

        Returns:
            List of entities that depend on this one
        """
        result: list[CodeEntity] = []
        visited: set[str] = {entity_id}
        current_level = [entity_id]

        for _ in range(depth):
            next_level = []
            for eid in current_level:
                deps = self._graph.get_dependents(eid, relationship_kinds)
                for dep in deps:
                    if dep.id not in visited:
                        visited.add(dep.id)
                        result.append(dep)
                        next_level.append(dep.id)
            current_level = next_level
            if not current_level:
                break

        return result

    async def get_call_graph(
        self,
        function_id: str,
        depth: int = 3,
    ) -> dict[str, Any]:
        """
        Get the call graph for a function.

        Args:
            function_id: ID of the function entity
            depth: Maximum call depth

        Returns:
            Dictionary representing the call graph
        """
        calls_kinds = {RelationshipKind.CALLS}
        dependencies = await self.find_dependencies(function_id, depth, calls_kinds)

        return {
            "root": function_id,
            "depth": depth,
            "calls": [
                {
                    "id": e.id,
                    "name": e.name,
                    "file": e.file_path,
                    "line": e.line_start,
                }
                for e in dependencies
            ],
        }

    async def get_inheritance_tree(
        self,
        class_id: str,
        direction: str = "both",
    ) -> dict[str, Any]:
        """
        Get the inheritance tree for a class.

        Args:
            class_id: ID of the class entity
            direction: "up" (ancestors), "down" (descendants), or "both"

        Returns:
            Dictionary representing the inheritance tree
        """
        inherit_kinds = {RelationshipKind.INHERITS, RelationshipKind.IMPLEMENTS}

        ancestors: list[CodeEntity] = []
        descendants: list[CodeEntity] = []

        if direction in ("up", "both"):
            ancestors = await self.find_dependencies(class_id, 10, inherit_kinds)

        if direction in ("down", "both"):
            descendants = await self.find_dependents(class_id, 10, inherit_kinds)

        return {
            "class_id": class_id,
            "ancestors": [{"id": e.id, "name": e.name} for e in ancestors],
            "descendants": [{"id": e.id, "name": e.name} for e in descendants],
        }

    def _index_file_entities(self, crawled_file: CrawledFile) -> None:
        """Index all entities from a crawled file."""
        # Add file entity
        file_entity = CodeEntity.from_file(crawled_file, self.repository_name)
        self._graph.add_entity(file_entity)

        # Add symbol entities
        for symbol in crawled_file.symbols:
            entity = CodeEntity.from_symbol(
                symbol, crawled_file.relative_path, self.repository_name
            )
            self._graph.add_entity(entity)

            # Index by simple name for relationship resolution
            self._symbol_index[symbol.name] = entity.id

            # Also index fully qualified name if there's a parent
            if symbol.parent:
                qualified_name = f"{symbol.parent}.{symbol.name}"
                self._symbol_index[qualified_name] = entity.id

    def _build_file_relationships(self, crawled_file: CrawledFile) -> None:
        """Build relationships for a crawled file."""
        file_id = f"{self.repository_name}:{crawled_file.relative_path}"

        # File contains symbols
        for symbol in crawled_file.symbols:
            symbol_id = f"{self.repository_name}:{crawled_file.relative_path}:{symbol.name}"
            if symbol.parent:
                symbol_id = f"{self.repository_name}:{crawled_file.relative_path}:{symbol.parent}.{symbol.name}"

            self._graph.add_relationship(
                Relationship(
                    source_id=file_id,
                    target_id=symbol_id,
                    kind=RelationshipKind.CONTAINS,
                    line=symbol.line_start,
                )
            )

            # Handle parent-child relationships (method in class)
            if symbol.parent:
                parent_id = f"{self.repository_name}:{crawled_file.relative_path}:{symbol.parent}"
                if parent_id in self._graph.entities:
                    self._graph.add_relationship(
                        Relationship(
                            source_id=symbol_id,
                            target_id=parent_id,
                            kind=RelationshipKind.MEMBER_OF,
                            line=symbol.line_start,
                        )
                    )

        # File dependencies become import relationships
        for dep in crawled_file.dependencies:
            target_id = self._resolve_dependency_target(dep)
            if target_id:
                kind = self._dependency_kind_to_relationship(dep.kind)
                self._graph.add_relationship(
                    Relationship(
                        source_id=file_id,
                        target_id=target_id,
                        kind=kind,
                        line=dep.line,
                        metadata={"raw_target": dep.target},
                    )
                )

    def _build_dependency_relationships(self, dependency_graph: dict[str, list[str]]) -> None:
        """Build relationships from the crawl's dependency graph."""
        for source_path, target_paths in dependency_graph.items():
            source_id = f"{self.repository_name}:{source_path}"
            for target_path in target_paths:
                target_id = f"{self.repository_name}:{target_path}"

                # Only add if both entities exist
                if source_id in self._graph.entities and target_id in self._graph.entities:
                    self._graph.add_relationship(
                        Relationship(
                            source_id=source_id,
                            target_id=target_id,
                            kind=RelationshipKind.IMPORTS,
                        )
                    )

    def _resolve_dependency_target(self, dep: FileDependency) -> str | None:
        """Resolve a dependency target to an entity ID."""
        # Try exact match in symbol index
        if dep.target in self._symbol_index:
            return self._symbol_index[dep.target]

        # Try as file path
        possible_file_id = f"{self.repository_name}:{dep.target}"
        if possible_file_id in self._graph.entities:
            return possible_file_id

        # Try with common extensions
        for ext in [".py", ".ts", ".js", ".tsx", ".jsx"]:
            possible_id = f"{self.repository_name}:{dep.target}{ext}"
            if possible_id in self._graph.entities:
                return possible_id

        # Try converting module path to file path
        file_path = dep.target.replace(".", "/")
        for ext in [".py", "/index.ts", "/index.js", ".ts", ".js"]:
            possible_id = f"{self.repository_name}:{file_path}{ext}"
            if possible_id in self._graph.entities:
                return possible_id

        return None

    def _dependency_kind_to_relationship(self, kind: str) -> RelationshipKind:
        """Convert dependency kind string to RelationshipKind."""
        mapping = {
            "import": RelationshipKind.IMPORTS,
            "from_import": RelationshipKind.IMPORTS,
            "require": RelationshipKind.IMPORTS,
            "include": RelationshipKind.IMPORTS,
            "extends": RelationshipKind.INHERITS,
            "implements": RelationshipKind.IMPLEMENTS,
            "call": RelationshipKind.CALLS,
        }
        return mapping.get(kind, RelationshipKind.USES)

    def get_entity(self, entity_id: str) -> CodeEntity | None:
        """Get an entity by ID."""
        return self._graph.entities.get(entity_id)

    def get_graph(self) -> RelationshipGraph:
        """Get the current relationship graph."""
        return self._graph

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about the relationship graph."""
        kind_counts: dict[str, int] = defaultdict(int)
        entity_kind_counts: dict[str, int] = defaultdict(int)

        for rel in self._graph.relationships:
            kind_counts[rel.kind.value] += 1

        for entity in self._graph.entities.values():
            entity_kind_counts[entity.kind] += 1

        return {
            "total_entities": len(self._graph.entities),
            "total_relationships": len(self._graph.relationships),
            "entity_kinds": dict(entity_kind_counts),
            "relationship_kinds": dict(kind_counts),
        }
