"""
Repository Crawler for large codebase analysis.

Provides unified crawling interface for:
- Local git repositories
- Remote git repositories (via clone)
- Incremental indexing based on commit history
- AST parsing for code structure extraction
- Integration with Knowledge Mound

Features:
- Language-aware file parsing
- Dependency graph extraction
- Symbol table generation
- Incremental updates based on git diff
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileType(str, Enum):
    """Recognized file types for specialized parsing."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    CPP = "cpp"
    C = "c"
    CSHARP = "csharp"
    RUBY = "ruby"
    PHP = "php"
    SWIFT = "swift"
    KOTLIN = "kotlin"
    SCALA = "scala"
    SQL = "sql"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    XML = "xml"
    HTML = "html"
    CSS = "css"
    SHELL = "shell"
    DOCKERFILE = "dockerfile"
    MAKEFILE = "makefile"
    OTHER = "other"


# Extension to file type mapping
EXTENSION_MAP: dict[str, FileType] = {
    ".py": FileType.PYTHON,
    ".pyi": FileType.PYTHON,
    ".js": FileType.JAVASCRIPT,
    ".mjs": FileType.JAVASCRIPT,
    ".jsx": FileType.JAVASCRIPT,
    ".ts": FileType.TYPESCRIPT,
    ".tsx": FileType.TYPESCRIPT,
    ".java": FileType.JAVA,
    ".go": FileType.GO,
    ".rs": FileType.RUST,
    ".cpp": FileType.CPP,
    ".cc": FileType.CPP,
    ".cxx": FileType.CPP,
    ".hpp": FileType.CPP,
    ".h": FileType.C,
    ".c": FileType.C,
    ".cs": FileType.CSHARP,
    ".rb": FileType.RUBY,
    ".php": FileType.PHP,
    ".swift": FileType.SWIFT,
    ".kt": FileType.KOTLIN,
    ".kts": FileType.KOTLIN,
    ".scala": FileType.SCALA,
    ".sql": FileType.SQL,
    ".md": FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".json": FileType.JSON,
    ".yaml": FileType.YAML,
    ".yml": FileType.YAML,
    ".toml": FileType.TOML,
    ".xml": FileType.XML,
    ".html": FileType.HTML,
    ".htm": FileType.HTML,
    ".css": FileType.CSS,
    ".scss": FileType.CSS,
    ".less": FileType.CSS,
    ".sh": FileType.SHELL,
    ".bash": FileType.SHELL,
    ".zsh": FileType.SHELL,
}


@dataclass
class CrawlConfig:
    """Configuration for repository crawling."""

    # File inclusion/exclusion
    include_patterns: list[str] = field(default_factory=lambda: ["*", "**/*"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/__pycache__/**",
            "**/.venv/**",
            "**/dist/**",
            "**/build/**",
            "**/.next/**",
            "**/target/**",
            "**/.cache/**",
            "**/coverage/**",
        ]
    )

    # File type filtering
    include_types: list[FileType] | None = None
    exclude_types: list[FileType] = field(default_factory=list)

    # Size limits
    max_file_size_bytes: int = 1_000_000  # 1MB
    max_files: int = 10_000

    # Parsing options
    extract_symbols: bool = True
    extract_dependencies: bool = True
    extract_docstrings: bool = True

    # Git options
    include_git_history: bool = False
    max_commits: int = 100
    since_commit: str | None = None

    # Concurrency
    max_concurrent_files: int = 20

    # Chunking for large files
    chunk_size_lines: int = 500
    chunk_overlap_lines: int = 50


@dataclass
class FileSymbol:
    """A symbol extracted from source code."""

    name: str
    kind: str  # function, class, method, variable, import, export
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    parent: str | None = None


@dataclass
class FileDependency:
    """A dependency reference from source code."""

    source: str
    target: str
    kind: str  # import, require, include
    line: int


@dataclass
class CrawledFile:
    """A crawled and parsed file."""

    path: str
    relative_path: str
    file_type: FileType
    content: str
    content_hash: str
    size_bytes: int
    line_count: int
    symbols: list[FileSymbol] = field(default_factory=list)
    dependencies: list[FileDependency] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    last_modified: datetime | None = None
    git_blame: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "file_type": self.file_type.value,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "line_count": self.line_count,
            "symbols": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                    "signature": s.signature,
                    "docstring": s.docstring,
                    "parent": s.parent,
                }
                for s in self.symbols
            ],
            "dependencies": [
                {
                    "source": d.source,
                    "target": d.target,
                    "kind": d.kind,
                    "line": d.line,
                }
                for d in self.dependencies
            ],
            "chunk_count": len(self.chunks),
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
        }


@dataclass
class CrawlResult:
    """Result of a repository crawl."""

    repository_path: str
    repository_name: str
    files: list[CrawledFile]
    total_files: int
    total_lines: int
    total_bytes: int
    file_type_counts: dict[str, int]
    symbol_counts: dict[str, int]
    dependency_graph: dict[str, list[str]]
    crawl_duration_ms: float
    errors: list[str]
    warnings: list[str]
    git_info: dict[str, Any] | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "repository_path": self.repository_path,
            "repository_name": self.repository_name,
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "total_bytes": self.total_bytes,
            "file_type_counts": self.file_type_counts,
            "symbol_counts": self.symbol_counts,
            "crawl_duration_ms": self.crawl_duration_ms,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "git_info": self.git_info,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class CrawlState:
    """Persisted state for incremental crawling."""

    repository_path: str
    last_crawl: datetime
    last_commit: str | None = None
    file_hashes: dict[str, str] = field(default_factory=dict)
    total_crawls: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "repository_path": self.repository_path,
            "last_crawl": self.last_crawl.isoformat(),
            "last_commit": self.last_commit,
            "file_hashes": self.file_hashes,
            "total_crawls": self.total_crawls,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrawlState:
        """Create from dictionary."""
        return cls(
            repository_path=data["repository_path"],
            last_crawl=datetime.fromisoformat(data["last_crawl"]),
            last_commit=data.get("last_commit"),
            file_hashes=data.get("file_hashes", {}),
            total_crawls=data.get("total_crawls", 0),
        )


class RepositoryCrawler:
    """
    Crawls git repositories for codebase analysis.

    Supports both local and remote repositories with incremental
    updates based on git history.
    """

    def __init__(
        self,
        config: CrawlConfig | None = None,
        workspace_id: str | None = None,
    ):
        """
        Initialize repository crawler.

        Args:
            config: Crawl configuration
            workspace_id: Workspace for isolation
        """
        self._config = config or CrawlConfig()
        self._workspace_id = workspace_id
        self._state: CrawlState | None = None

    async def crawl(
        self,
        source: str,
        incremental: bool = True,
    ) -> CrawlResult:
        """
        Crawl a repository.

        Args:
            source: Path to local repo or git URL for remote
            incremental: Whether to use incremental crawling

        Returns:
            Crawl result with all extracted information
        """
        start_time = datetime.now(timezone.utc)

        # Determine if local or remote
        if source.startswith(("http://", "https://", "git://", "git@", "ssh://")):
            self._validate_git_url(source)
            repo_path = await self._clone_repository(source)
            repo_name = self._extract_repo_name(source)
        else:
            repo_path = Path(source).resolve()
            if not repo_path.exists():
                raise ValueError(f"Repository path does not exist: {source}")
            repo_name = repo_path.name

        # Load previous state if incremental
        changed_files: set[str] | None = None
        if incremental and self._state:
            changed_files = await self._get_changed_files(repo_path)
            if not changed_files:
                logger.info("No changes detected since last crawl")

        # Get git info
        git_info = await self._get_git_info(repo_path)

        # Discover files
        files_to_process = await self._discover_files(repo_path, changed_files)

        # Process files concurrently
        crawled_files: list[CrawledFile] = []
        errors: list[str] = []
        warnings: list[str] = []

        semaphore = asyncio.Semaphore(self._config.max_concurrent_files)

        async def process_file(file_path: Path) -> CrawledFile | None:
            async with semaphore:
                try:
                    return await self._process_file(file_path, repo_path)
                except (OSError, RuntimeError, ValueError) as e:
                    errors.append(f"Error processing {file_path}: {e}")
                    return None

        tasks = [process_file(f) for f in files_to_process[: self._config.max_files]]
        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                crawled_files.append(result)

        if len(files_to_process) > self._config.max_files:
            warnings.append(
                f"Truncated to {self._config.max_files} files (found {len(files_to_process)})"
            )

        # Build dependency graph
        dependency_graph = self._build_dependency_graph(crawled_files)

        # Calculate statistics
        total_lines = sum(f.line_count for f in crawled_files)
        total_bytes = sum(f.size_bytes for f in crawled_files)

        file_type_counts: dict[str, int] = {}
        symbol_counts: dict[str, int] = {}

        for cf in crawled_files:
            ft = cf.file_type.value
            file_type_counts[ft] = file_type_counts.get(ft, 0) + 1

            for symbol in cf.symbols:
                symbol_counts[symbol.kind] = symbol_counts.get(symbol.kind, 0) + 1

        completed_at = datetime.now(timezone.utc)
        duration_ms = (completed_at - start_time).total_seconds() * 1000

        # Update state
        self._state = CrawlState(
            repository_path=str(repo_path),
            last_crawl=completed_at,
            last_commit=git_info.get("head_commit") if git_info else None,
            file_hashes={f.relative_path: f.content_hash for f in crawled_files},
            total_crawls=(self._state.total_crawls + 1) if self._state else 1,
        )

        return CrawlResult(
            repository_path=str(repo_path),
            repository_name=repo_name,
            files=crawled_files,
            total_files=len(crawled_files),
            total_lines=total_lines,
            total_bytes=total_bytes,
            file_type_counts=file_type_counts,
            symbol_counts=symbol_counts,
            dependency_graph=dependency_graph,
            crawl_duration_ms=duration_ms,
            errors=errors,
            warnings=warnings,
            git_info=git_info,
            started_at=start_time,
            completed_at=completed_at,
        )

    async def index_to_mound(
        self,
        crawl_result: CrawlResult,
        mound: Any,  # KnowledgeMound
    ) -> int:
        """
        Index crawl results to a Knowledge Mound.

        Args:
            crawl_result: Results from crawl
            mound: Knowledge Mound instance

        Returns:
            Number of nodes created
        """
        nodes_created = 0

        for cf in crawl_result.files:
            # Index file metadata
            metadata = {
                "source": "repository_crawler",
                "repository": crawl_result.repository_name,
                "file_path": cf.relative_path,
                "file_type": cf.file_type.value,
                "line_count": cf.line_count,
                "symbol_count": len(cf.symbols),
            }

            # Index file chunks
            for chunk in cf.chunks:
                try:
                    await mound.add(
                        content=chunk["content"],
                        metadata={
                            **metadata,
                            "chunk_index": chunk["index"],
                            "start_line": chunk["start_line"],
                            "end_line": chunk["end_line"],
                        },
                        workspace_id=self._workspace_id,
                    )
                    nodes_created += 1
                except (ValueError, RuntimeError, OSError) as e:
                    logger.warning("Failed to index chunk from %s: %s", cf.relative_path, e)

            # Index symbols
            for symbol in cf.symbols:
                if symbol.docstring:
                    try:
                        await mound.add(
                            content=f"{symbol.kind} {symbol.name}: {symbol.docstring}",
                            metadata={
                                **metadata,
                                "symbol_name": symbol.name,
                                "symbol_kind": symbol.kind,
                                "line_start": symbol.line_start,
                            },
                            workspace_id=self._workspace_id,
                        )
                        nodes_created += 1
                    except (ValueError, RuntimeError, OSError) as e:
                        logger.warning("Failed to index symbol %s: %s", symbol.name, e)

        return nodes_created

    @staticmethod
    def _validate_git_url(url: str) -> None:
        """Validate a git URL to prevent command injection.

        Rejects:
        - URLs starting with '-' (git argument injection)
        - URLs containing 'ext::' (arbitrary command execution via git)
        - URLs with schemes other than https, http, git, ssh, or git@ SCP syntax

        Raises:
            ValueError: If the URL is unsafe for use with git.
        """
        if url.startswith("-"):
            raise ValueError(
                f"Rejected git URL starting with '-' (argument injection risk): {url!r}"
            )
        if "ext::" in url:
            raise ValueError(
                f"Rejected git URL containing 'ext::' (arbitrary command execution risk): {url!r}"
            )
        allowed_prefixes = ("https://", "http://", "git://", "ssh://", "git@")
        if not url.startswith(allowed_prefixes):
            raise ValueError(
                f"Rejected git URL with disallowed scheme: {url!r}. "
                f"Allowed: https://, http://, git://, ssh://, git@"
            )

    async def _clone_repository(self, url: str) -> Path:
        """Clone a remote repository to temp directory."""
        import tempfile

        self._validate_git_url(url)

        temp_dir = Path(tempfile.mkdtemp(prefix="aragora_crawl_"))
        repo_name = self._extract_repo_name(url)
        repo_path = temp_dir / repo_name

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth=1",
                url,
                str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(f"Git clone failed: {stderr.decode()}")

            return repo_path

        except OSError as e:
            raise RuntimeError(f"Failed to clone repository: {e}")

    def _extract_repo_name(self, url: str) -> str:
        """Extract repository name from URL."""
        # Handle various URL formats
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]

        parts = url.split("/")
        return parts[-1] if parts else "unknown"

    async def _get_git_info(self, repo_path: Path) -> dict[str, Any] | None:
        """Get git repository information."""
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            return None

        try:
            # Get current commit
            head_result = await self._run_git_command(repo_path, ["rev-parse", "HEAD"])

            # Get branch
            branch_result = await self._run_git_command(
                repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]
            )

            # Get remote URL
            remote_result = await self._run_git_command(
                repo_path, ["config", "--get", "remote.origin.url"]
            )

            # Get commit count
            count_result = await self._run_git_command(repo_path, ["rev-list", "--count", "HEAD"])

            return {
                "head_commit": head_result.strip() if head_result else None,
                "branch": branch_result.strip() if branch_result else None,
                "remote_url": remote_result.strip() if remote_result else None,
                "commit_count": int(count_result.strip()) if count_result else 0,
            }

        except (OSError, ValueError) as e:
            logger.warning("Failed to get git info: %s", e)
            return None

    async def _run_git_command(
        self,
        repo_path: Path,
        args: list[str],
    ) -> str | None:
        """Run a git command and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="replace")
            return None

        except OSError as e:
            logger.debug("Git command failed: %s", e)
            return None

    async def _get_changed_files(self, repo_path: Path) -> set[str] | None:
        """Get files changed since last crawl."""
        if not self._state or not self._state.last_commit:
            return None

        try:
            result = await self._run_git_command(
                repo_path,
                ["diff", "--name-only", self._state.last_commit, "HEAD"],
            )

            if result:
                return set(result.strip().split("\n"))
            return None

        except (OSError, ValueError) as e:
            logger.debug("Failed to get changed files: %s", e)
            return None

    async def _discover_files(
        self,
        repo_path: Path,
        changed_files: set[str] | None = None,
    ) -> list[Path]:
        """Discover files to process."""
        import fnmatch

        files: list[Path] = []

        for path in repo_path.rglob("*"):
            if not path.is_file():
                continue

            relative = str(path.relative_to(repo_path))

            # Check exclusions
            excluded = False
            for pattern in self._config.exclude_patterns:
                if fnmatch.fnmatch(relative, pattern):
                    excluded = True
                    break

            if excluded:
                continue

            # Check inclusions
            included = False
            for pattern in self._config.include_patterns:
                if fnmatch.fnmatch(relative, pattern):
                    included = True
                    break

            if not included:
                continue

            # Check file type
            file_type = self._get_file_type(path)
            if self._config.include_types and file_type not in self._config.include_types:
                continue
            if file_type in self._config.exclude_types:
                continue

            # Check size
            try:
                if path.stat().st_size > self._config.max_file_size_bytes:
                    continue
            except OSError:
                continue

            # Check if changed (for incremental)
            if changed_files is not None and relative not in changed_files:
                continue

            files.append(path)

        return sorted(files)

    def _get_file_type(self, path: Path) -> FileType:
        """Determine file type from path."""
        # Check special filenames
        name = path.name.lower()
        if name == "dockerfile":
            return FileType.DOCKERFILE
        if name == "makefile":
            return FileType.MAKEFILE

        # Check extension
        suffix = path.suffix.lower()
        return EXTENSION_MAP.get(suffix, FileType.OTHER)

    async def _process_file(
        self,
        file_path: Path,
        repo_path: Path,
    ) -> CrawledFile:
        """Process a single file."""
        relative_path = str(file_path.relative_to(repo_path))
        file_type = self._get_file_type(file_path)

        # Read content
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise RuntimeError(f"Failed to read file: {e}")

        # Calculate hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Count lines
        lines = content.split("\n")
        line_count = len(lines)

        # Get file stats
        stat = file_path.stat()
        size_bytes = stat.st_size
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        # Extract symbols
        symbols: list[FileSymbol] = []
        if self._config.extract_symbols:
            symbols = self._extract_symbols(content, file_type)

        # Extract dependencies
        dependencies: list[FileDependency] = []
        if self._config.extract_dependencies:
            dependencies = self._extract_dependencies(content, file_type, relative_path)

        # Create chunks
        chunks = self._create_chunks(content, lines)

        return CrawledFile(
            path=str(file_path),
            relative_path=relative_path,
            file_type=file_type,
            content=content,
            content_hash=content_hash,
            size_bytes=size_bytes,
            line_count=line_count,
            symbols=symbols,
            dependencies=dependencies,
            chunks=chunks,
            last_modified=last_modified,
        )

    def _extract_symbols(
        self,
        content: str,
        file_type: FileType,
    ) -> list[FileSymbol]:
        """Extract symbols from source code."""
        symbols: list[FileSymbol] = []

        if file_type == FileType.PYTHON:
            symbols = self._extract_python_symbols(content)
        elif file_type in (FileType.JAVASCRIPT, FileType.TYPESCRIPT):
            symbols = self._extract_js_symbols(content)
        elif file_type == FileType.GO:
            symbols = self._extract_go_symbols(content)
        elif file_type == FileType.JAVA:
            symbols = self._extract_java_symbols(content)
        elif file_type == FileType.RUST:
            symbols = self._extract_rust_symbols(content)

        return symbols

    def _extract_python_symbols(self, content: str) -> list[FileSymbol]:
        """Extract symbols from Python code."""
        symbols: list[FileSymbol] = []

        try:
            import ast

            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols.append(
                        FileSymbol(
                            name=node.name,
                            kind="function",
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                            signature=self._get_python_signature(node),
                            docstring=ast.get_docstring(node),
                        )
                    )
                elif isinstance(node, ast.AsyncFunctionDef):
                    symbols.append(
                        FileSymbol(
                            name=node.name,
                            kind="async_function",
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                            signature=self._get_python_signature(node),
                            docstring=ast.get_docstring(node),
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    symbols.append(
                        FileSymbol(
                            name=node.name,
                            kind="class",
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                            docstring=ast.get_docstring(node),
                        )
                    )

        except SyntaxError:
            # Fall back to regex for malformed Python
            symbols = self._extract_python_symbols_regex(content)

        return symbols

    def _get_python_signature(self, node: Any) -> str:
        """Get function signature from AST node."""
        try:
            import ast

            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)

            sig = f"def {node.name}({', '.join(args)})"
            if node.returns:
                sig += f" -> {ast.unparse(node.returns)}"
            return sig

        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("Failed to extract function signature for %s: %s", node.name, e)
            return f"def {node.name}(...)"

    def _extract_python_symbols_regex(self, content: str) -> list[FileSymbol]:
        """Extract Python symbols using regex (fallback)."""
        symbols: list[FileSymbol] = []
        lines = content.split("\n")

        # Function pattern
        func_pattern = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")
        # Class pattern
        class_pattern = re.compile(r"^(\s*)class\s+(\w+)")

        for i, line in enumerate(lines, 1):
            func_match = func_pattern.match(line)
            if func_match:
                symbols.append(
                    FileSymbol(
                        name=func_match.group(2),
                        kind="function",
                        line_start=i,
                        line_end=i,
                    )
                )
                continue

            class_match = class_pattern.match(line)
            if class_match:
                symbols.append(
                    FileSymbol(
                        name=class_match.group(2),
                        kind="class",
                        line_start=i,
                        line_end=i,
                    )
                )

        return symbols

    def _extract_js_symbols(self, content: str) -> list[FileSymbol]:
        """Extract symbols from JavaScript/TypeScript."""
        symbols: list[FileSymbol] = []
        lines = content.split("\n")

        # Patterns for JS/TS
        patterns = [
            (r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(", "function"),
            (r"(?:export\s+)?class\s+(\w+)", "class"),
            (r"(?:export\s+)?interface\s+(\w+)", "interface"),
            (r"(?:export\s+)?type\s+(\w+)", "type"),
            (r"(?:export\s+)?enum\s+(\w+)", "enum"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.search(pattern, line)
                if match:
                    symbols.append(
                        FileSymbol(
                            name=match.group(1),
                            kind=kind,
                            line_start=i,
                            line_end=i,
                        )
                    )
                    break

        return symbols

    def _extract_go_symbols(self, content: str) -> list[FileSymbol]:
        """Extract symbols from Go code."""
        symbols: list[FileSymbol] = []
        lines = content.split("\n")

        patterns = [
            (r"^func\s+(\w+)\s*\(", "function"),
            (r"^func\s+\([^)]+\)\s+(\w+)\s*\(", "method"),
            (r"^type\s+(\w+)\s+struct", "struct"),
            (r"^type\s+(\w+)\s+interface", "interface"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.match(pattern, line)
                if match:
                    symbols.append(
                        FileSymbol(
                            name=match.group(1),
                            kind=kind,
                            line_start=i,
                            line_end=i,
                        )
                    )
                    break

        return symbols

    def _extract_java_symbols(self, content: str) -> list[FileSymbol]:
        """Extract symbols from Java code."""
        symbols: list[FileSymbol] = []
        lines = content.split("\n")

        patterns = [
            (r"(?:public|private|protected)?\s*(?:static)?\s*class\s+(\w+)", "class"),
            (r"(?:public|private|protected)?\s*interface\s+(\w+)", "interface"),
            (r"(?:public|private|protected)?\s*enum\s+(\w+)", "enum"),
            (
                r"(?:public|private|protected)?\s*(?:static)?\s*\w+\s+(\w+)\s*\(",
                "method",
            ),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.search(pattern, line)
                if match:
                    symbols.append(
                        FileSymbol(
                            name=match.group(1),
                            kind=kind,
                            line_start=i,
                            line_end=i,
                        )
                    )
                    break

        return symbols

    def _extract_rust_symbols(self, content: str) -> list[FileSymbol]:
        """Extract symbols from Rust code."""
        symbols: list[FileSymbol] = []
        lines = content.split("\n")

        patterns = [
            (r"^(?:pub\s+)?fn\s+(\w+)", "function"),
            (r"^(?:pub\s+)?struct\s+(\w+)", "struct"),
            (r"^(?:pub\s+)?enum\s+(\w+)", "enum"),
            (r"^(?:pub\s+)?trait\s+(\w+)", "trait"),
            (r"^impl(?:<[^>]+>)?\s+(\w+)", "impl"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.match(pattern, line)
                if match:
                    symbols.append(
                        FileSymbol(
                            name=match.group(1),
                            kind=kind,
                            line_start=i,
                            line_end=i,
                        )
                    )
                    break

        return symbols

    def _extract_dependencies(
        self,
        content: str,
        file_type: FileType,
        source_path: str,
    ) -> list[FileDependency]:
        """Extract dependencies from source code."""
        dependencies: list[FileDependency] = []
        lines = content.split("\n")

        if file_type == FileType.PYTHON:
            patterns = [
                (r"^import\s+(\S+)", "import"),
                (r"^from\s+(\S+)\s+import", "import"),
            ]
        elif file_type in (FileType.JAVASCRIPT, FileType.TYPESCRIPT):
            patterns = [
                (r"import\s+.*\s+from\s+['\"]([^'\"]+)['\"]", "import"),
                (r"require\(['\"]([^'\"]+)['\"]\)", "require"),
            ]
        elif file_type == FileType.GO:
            patterns = [
                (r"^\s*\"([^\"]+)\"", "import"),
            ]
        elif file_type == FileType.JAVA:
            patterns = [
                (r"^import\s+(\S+);", "import"),
            ]
        elif file_type == FileType.RUST:
            patterns = [
                (r"^use\s+(\S+);", "use"),
                (r"^extern\s+crate\s+(\w+)", "extern"),
            ]
        else:
            patterns = []

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.search(pattern, line)
                if match:
                    dependencies.append(
                        FileDependency(
                            source=source_path,
                            target=match.group(1),
                            kind=kind,
                            line=i,
                        )
                    )

        return dependencies

    def _create_chunks(
        self,
        content: str,
        lines: list[str],
    ) -> list[dict[str, Any]]:
        """Split content into overlapping chunks."""
        chunks: list[dict[str, Any]] = []

        chunk_size = self._config.chunk_size_lines
        overlap = self._config.chunk_overlap_lines

        if len(lines) <= chunk_size:
            # Single chunk
            chunks.append(
                {
                    "index": 0,
                    "content": content,
                    "start_line": 1,
                    "end_line": len(lines),
                }
            )
        else:
            # Multiple chunks with overlap
            start = 0
            chunk_index = 0

            while start < len(lines):
                end = min(start + chunk_size, len(lines))
                chunk_lines = lines[start:end]

                chunks.append(
                    {
                        "index": chunk_index,
                        "content": "\n".join(chunk_lines),
                        "start_line": start + 1,
                        "end_line": end,
                    }
                )

                start = end - overlap
                chunk_index += 1

                if end >= len(lines):
                    break

        return chunks

    def _build_dependency_graph(
        self,
        files: list[CrawledFile],
    ) -> dict[str, list[str]]:
        """Build a dependency graph from all files."""
        graph: dict[str, list[str]] = {}

        for cf in files:
            if cf.dependencies:
                graph[cf.relative_path] = [d.target for d in cf.dependencies]

        return graph

    def set_state(self, state: CrawlState) -> None:
        """Set crawl state for incremental crawling."""
        self._state = state

    def get_state(self) -> CrawlState | None:
        """Get current crawl state."""
        return self._state


async def crawl_repository(
    source: str,
    config: CrawlConfig | None = None,
    workspace_id: str | None = None,
) -> CrawlResult:
    """
    Convenience function to crawl a repository.

    Args:
        source: Path to local repo or git URL
        config: Crawl configuration
        workspace_id: Workspace for isolation

    Returns:
        Crawl result
    """
    crawler = RepositoryCrawler(config=config, workspace_id=workspace_id)
    return await crawler.crawl(source)


__all__ = [
    "RepositoryCrawler",
    "CrawlConfig",
    "CrawlResult",
    "CrawlState",
    "CrawledFile",
    "FileSymbol",
    "FileDependency",
    "FileType",
    "crawl_repository",
]
