"""
Codebase Indexer — builds searchable code structure in Knowledge Mound.

Scans the codebase to create KM entries for:
- Module descriptions (from docstrings)
- Function/class signatures with file locations
- Test file → source file mappings
- Import dependency graph (lightweight)

This enables debate agents to query "where is the consensus logic?"
or "what tests cover the billing module?" during planning.

Usage:
    indexer = CodebaseIndexer(repo_path=".")
    stats = await indexer.index()

    # Query the index
    results = await indexer.query("consensus detection")
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache directory for index data
_CACHE_DIR = Path.home() / ".aragora" / "index_cache"


@dataclass
class ModuleInfo:
    """Information about a Python module."""

    path: str  # Relative path from repo root
    docstring: str  # Module-level docstring (first 200 chars)
    classes: list[str]  # Class names defined
    functions: list[str]  # Top-level function names
    imports_from: list[str]  # Modules imported from aragora.*
    line_count: int = 0

    def to_km_entry(self) -> dict[str, Any]:
        """Serialize to a Knowledge Mound entry dict."""
        return {
            "type": "module",
            "path": self.path,
            "docstring": self.docstring,
            "classes": self.classes,
            "functions": self.functions,
            "imports_from": self.imports_from,
            "line_count": self.line_count,
            "searchable_text": (
                f"{self.path} {self.docstring} {' '.join(self.classes)} {' '.join(self.functions)}"
            ),
        }


@dataclass
class IndexStats:
    """Statistics from an indexing run."""

    modules_indexed: int = 0
    classes_found: int = 0
    functions_found: int = 0
    test_files_found: int = 0
    total_lines: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize statistics to a dictionary."""
        return {
            "modules_indexed": self.modules_indexed,
            "classes_found": self.classes_found,
            "functions_found": self.functions_found,
            "test_files_found": self.test_files_found,
            "total_lines": self.total_lines,
            "errors_count": len(self.errors),
        }


class CodebaseIndexer:
    """Indexes codebase structure into Knowledge Mound entries.

    Performs lightweight AST analysis to extract module structure
    without executing any code. Results are stored in the KM
    for query by planning agents.
    """

    def __init__(
        self,
        repo_path: str | Path = ".",
        source_dirs: list[str] | None = None,
        test_dirs: list[str] | None = None,
        max_modules: int = 500,
    ):
        self.repo_path = Path(repo_path)
        self.source_dirs = source_dirs if source_dirs is not None else ["aragora"]
        self.test_dirs = test_dirs if test_dirs is not None else ["tests"]
        self.max_modules = max_modules
        self._modules: list[ModuleInfo] = []
        self._test_map: dict[str, list[str]] = {}  # source_path -> [test_paths]

    def _get_git_hash(self) -> str:
        """Get current git HEAD hash for cache invalidation."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],  # fixed command
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def _load_cached_index(self) -> IndexStats | None:
        """Load cached index if git hash matches.

        Returns IndexStats and populates self._modules and self._test_map
        from cache, or None if cache is invalid/missing.
        """
        git_hash = self._get_git_hash()
        if not git_hash:
            return None

        cache_file = _CACHE_DIR / f"index_{git_hash[:12]}.json"
        if not cache_file.exists():
            return None

        try:
            data = json.loads(cache_file.read_text())
            self._modules = [
                ModuleInfo(
                    path=m["path"],
                    docstring=m["docstring"],
                    classes=m["classes"],
                    functions=m["functions"],
                    imports_from=m["imports_from"],
                    line_count=m.get("line_count", 0),
                )
                for m in data.get("modules", [])
            ]
            self._test_map = data.get("test_map", {})
            stats = IndexStats(
                modules_indexed=data.get("modules_indexed", len(self._modules)),
                classes_found=data.get("classes_found", 0),
                functions_found=data.get("functions_found", 0),
                test_files_found=data.get("test_files_found", 0),
                total_lines=data.get("total_lines", 0),
            )
            logger.info(
                "codebase_index_cache_hit hash=%s modules=%d",
                git_hash[:12],
                stats.modules_indexed,
            )
            return stats
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.debug("Index cache load failed: %s", exc)
            return None

    def _save_index_cache(self, stats: IndexStats) -> None:
        """Save index to cache keyed by git hash."""
        git_hash = self._get_git_hash()
        if not git_hash:
            return

        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = _CACHE_DIR / f"index_{git_hash[:12]}.json"
            data = {
                "modules": [m.to_km_entry() for m in self._modules],
                "test_map": self._test_map,
                "modules_indexed": stats.modules_indexed,
                "classes_found": stats.classes_found,
                "functions_found": stats.functions_found,
                "test_files_found": stats.test_files_found,
                "total_lines": stats.total_lines,
            }
            cache_file.write_text(json.dumps(data))
            logger.debug("codebase_index_cached hash=%s", git_hash[:12])

            # Clean old cache files (keep last 5)
            cache_files = sorted(
                _CACHE_DIR.glob("index_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old_file in cache_files[5:]:
                old_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Index cache save failed: %s", exc)

    async def index(self) -> IndexStats:
        """Scan the codebase and build the index.

        Uses a git-hash-based cache to skip re-indexing when the
        codebase hasn't changed.

        Returns:
            IndexStats with counts and any errors encountered.
        """
        # Try cache first
        cached = self._load_cached_index()
        if cached is not None:
            return cached

        stats = IndexStats()

        # Scan source modules
        for source_dir in self.source_dirs:
            source_path = self.repo_path / source_dir
            if not source_path.is_dir():
                continue

            for py_file in sorted(source_path.rglob("*.py")):
                if stats.modules_indexed >= self.max_modules:
                    break
                if py_file.name.startswith("_") and py_file.name != "__init__.py":
                    continue

                try:
                    info = self._analyze_module(py_file)
                    if info:
                        self._modules.append(info)
                        stats.modules_indexed += 1
                        stats.classes_found += len(info.classes)
                        stats.functions_found += len(info.functions)
                        stats.total_lines += info.line_count
                except (SyntaxError, UnicodeDecodeError) as e:
                    stats.errors.append(f"{py_file}: {e}")

        # Scan test files and build test map
        for test_dir in self.test_dirs:
            test_path = self.repo_path / test_dir
            if not test_path.is_dir():
                continue

            for py_file in sorted(test_path.rglob("test_*.py")):
                stats.test_files_found += 1
                self._map_test_to_source(py_file)

        # Persist to KM if available
        await self._persist_to_km(stats)

        # Save to local cache for fast subsequent loads
        self._save_index_cache(stats)

        logger.info(
            "codebase_index_complete modules=%d classes=%d functions=%d tests=%d",
            stats.modules_indexed,
            stats.classes_found,
            stats.functions_found,
            stats.test_files_found,
        )

        return stats

    def _analyze_module(self, py_file: Path) -> ModuleInfo | None:
        """Extract structure from a Python file using AST.

        Args:
            py_file: Path to the Python file to analyze.

        Returns:
            ModuleInfo if the file could be parsed, None otherwise.
        """
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        # Extract module docstring
        docstring = ""
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            docstring = tree.body[0].value.value[:200].strip()

        # Extract classes, functions, and imports
        classes: list[str] = []
        functions: list[str] = []
        imports_from: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only top-level functions (not methods inside classes)
                if hasattr(node, "col_offset") and node.col_offset == 0:
                    functions.append(node.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("aragora."):
                    imports_from.append(node.module)

        rel_path = str(py_file.relative_to(self.repo_path))

        return ModuleInfo(
            path=rel_path,
            docstring=docstring,
            classes=classes,
            functions=functions,
            imports_from=sorted(set(imports_from)),
            line_count=len(source.splitlines()),
        )

    def _map_test_to_source(self, test_file: Path) -> None:
        """Map test file to likely source files based on imports.

        Scans the test file's AST for ``from aragora.xxx import ...``
        statements and records the mapping.
        """
        try:
            source = test_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError, UnicodeDecodeError):
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("aragora."):
                    # Convert module path to file path
                    module_path = node.module.replace(".", "/") + ".py"
                    if module_path not in self._test_map:
                        self._test_map[module_path] = []
                    rel_test = str(test_file.relative_to(self.repo_path))
                    if rel_test not in self._test_map[module_path]:
                        self._test_map[module_path].append(rel_test)

    async def query(self, search_text: str, limit: int = 10) -> list[ModuleInfo]:
        """Search the index for modules matching a query.

        Uses simple keyword matching against docstrings, class names,
        function names, and file paths. For production use, this would
        delegate to the Knowledge Mound's semantic search.

        Args:
            search_text: Space-separated keywords to search for.
            limit: Maximum number of results to return.

        Returns:
            List of ModuleInfo sorted by relevance (best first).
        """
        search_lower = search_text.lower()
        scored: list[tuple[int, ModuleInfo]] = []

        for module in self._modules:
            score = 0
            searchable = module.to_km_entry()["searchable_text"].lower()

            for word in search_lower.split():
                if word in searchable:
                    score += 1
                if word in module.path.lower():
                    score += 2  # Path matches are more valuable

            if score > 0:
                scored.append((score, module))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def get_tests_for_module(self, module_path: str) -> list[str]:
        """Get test files that import from a given module.

        Args:
            module_path: Relative path to the source module
                         (e.g. ``aragora/debate/consensus.py``).

        Returns:
            List of relative test file paths.
        """
        return self._test_map.get(module_path, [])

    async def _persist_to_km(self, stats: IndexStats) -> None:
        """Persist indexed modules to Knowledge Mound.

        Uses the NomicCycleAdapter to store the index as an observation.
        Falls back gracefully if the KM infrastructure is unavailable.
        """
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                NomicCycleAdapter,
            )

            adapter = NomicCycleAdapter()

            # Store as a single cycle outcome with codebase index data
            await adapter.ingest_cycle_outcome(
                outcome=_build_index_outcome(stats, self._modules, self._test_map),
            )

            logger.info(
                "codebase_index_persisted_to_km modules=%d",
                stats.modules_indexed,
            )

        except ImportError:
            logger.debug("KM adapter not available, index stored in memory only")
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("KM persistence failed (non-critical): %s", e)


def _build_index_outcome(
    stats: IndexStats,
    modules: list[ModuleInfo],
    test_map: dict[str, list[str]],
) -> Any:
    """Build a lightweight dict that represents the index for KM storage.

    We avoid importing NomicCycleOutcome directly so that KM is truly
    optional. The adapter's ``ingest_cycle_outcome`` accepts any object
    with a ``to_dict`` method or a plain dict.
    """

    class _IndexOutcome:
        """Minimal outcome wrapper for KM ingestion."""

        def __init__(
            self,
            stats: IndexStats,
            modules: list[ModuleInfo],
            test_map: dict[str, list[str]],
        ):
            self._stats = stats
            self._modules = modules
            self._test_map = test_map
            # Attributes required by NomicCycleAdapter._generate_cycle_id
            self.objective = "Codebase structure indexing"
            self.started_at = __import__("datetime").datetime.now(
                tz=__import__("datetime").timezone.utc
            )

        def to_dict(self) -> dict[str, Any]:
            return {
                "cycle_id": "codebase_index",
                "objective": self.objective,
                "status": "success",
                "stats": self._stats.to_dict(),
                "modules": [m.to_km_entry() for m in self._modules[:100]],
                "test_map_size": len(self._test_map),
            }

    return _IndexOutcome(stats, modules, test_map)
