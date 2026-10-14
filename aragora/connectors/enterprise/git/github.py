"""
GitHub Enterprise Connector.

Full repository crawling with:
- Incremental sync using commit SHA
- File content indexing
- PR/Issue/Discussion sync
- AST parsing for Python, JS, TS
- Dependency graph extraction
- Webhook support for real-time updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

# File extensions to index
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".scala",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".env.example"}

# Files to always include
IMPORTANT_FILES = {
    "README.md",
    "readme.md",
    "README.rst",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSE.md",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "setup.py",
    "Makefile",
    "Dockerfile",
}

# Max file size to index (1MB)
MAX_FILE_SIZE = 1024 * 1024


@dataclass
class GitHubFile:
    """A file from a GitHub repository."""

    path: str
    sha: str
    content: str
    size: int
    url: str
    last_modified: datetime | None = None


@dataclass
class GitHubCommit:
    """A commit from a GitHub repository."""

    sha: str
    message: str
    author: str
    date: datetime
    files_changed: list[str] = field(default_factory=list)


class GitHubEnterpriseConnector(EnterpriseConnector):
    """
    Enterprise GitHub connector for full repository crawling.

    Features:
    - Incremental sync using commit SHA
    - Selective file indexing (code, docs, config)
    - PR/Issue content extraction
    - AST parsing for function/class extraction
    - Dependency graph from imports
    - Real-time webhook updates
    """

    def __init__(
        self,
        repo: str,  # owner/repo format
        branch: str = "main",
        token: str | None = None,
        include_prs: bool = True,
        include_issues: bool = True,
        include_discussions: bool = False,
        file_extensions: set[str] | None = None,
        exclude_paths: list[str] | None = None,
        **kwargs: Any,
    ):
        # Validate repo format
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
            raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'")

        connector_id = f"github_{repo.replace('/', '_')}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.repo = repo
        self.branch = branch
        self.token = token
        self.include_prs = include_prs
        self.include_issues = include_issues
        self.include_discussions = include_discussions

        # File filtering
        self.file_extensions = file_extensions or (
            CODE_EXTENSIONS | DOC_EXTENSIONS | CONFIG_EXTENSIONS
        )
        self.exclude_paths = exclude_paths or [
            "node_modules/",
            "vendor/",
            ".git/",
            "__pycache__/",
            "dist/",
            "build/",
        ]

        # Cache
        self._file_cache: dict[str, GitHubFile] = {}
        self._gh_available: bool | None = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.CODE_ANALYSIS

    @property
    def name(self) -> str:
        return f"GitHub ({self.repo})"

    @property
    def is_available(self) -> bool:
        """Check if gh CLI is installed."""
        return self._check_gh_cli()

    @property
    def is_configured(self) -> bool:
        """Check if authenticated (token or gh CLI auth)."""
        return bool(self.token) or self._check_gh_cli()

    async def _perform_health_check(self, timeout: float) -> bool:
        """Verify GitHub API connectivity."""
        try:
            result = await self._run_gh(["api", f"repos/{self.repo}"])
            return result is not None
        except (OSError, asyncio.TimeoutError, RuntimeError) as e:
            logger.debug("GitHub health check failed: %s", e)
            return False

    def _check_gh_cli(self) -> bool:
        """Check if gh CLI is available."""
        if self._gh_available is not None:
            return self._gh_available

        import subprocess

        try:
            result = subprocess.run(
                ["gh", "auth", "status"],  # fixed command
                capture_output=True,
                timeout=10,
            )
            self._gh_available = result.returncode == 0
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.debug("gh CLI check failed: %s", e)
            self._gh_available = False

        return self._gh_available

    async def _run_gh(self, args: list[str]) -> str | None:
        """Run gh CLI command."""
        if not self._check_gh_cli():
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                return stdout.decode("utf-8")
            logger.debug("gh command failed: %s", stderr.decode())
            return None
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("gh command timed out")
            return None
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("gh command error: %s", e)
            return None

    async def _get_latest_commit(self) -> str | None:
        """Get the latest commit SHA on the branch."""
        output = await self._run_gh(
            [
                "api",
                f"repos/{self.repo}/commits/{self.branch}",
                "--jq",
                ".sha",
            ]
        )
        return output.strip() if output else None

    async def _get_commits_since(
        self, since_sha: str | None, limit: int = 100
    ) -> list[GitHubCommit]:
        """Get commits since a specific SHA."""
        args = [
            "api",
            f"repos/{self.repo}/commits",
            "-f",
            f"sha={self.branch}",
            "-f",
            f"per_page={limit}",
        ]

        output = await self._run_gh(args)
        if not output:
            return []

        try:
            commits_data = json.loads(output)
        except json.JSONDecodeError:
            return []

        commits = []
        for c in commits_data:
            sha = c.get("sha", "")

            # Stop at the since_sha
            if since_sha and sha == since_sha:
                break

            commits.append(
                GitHubCommit(
                    sha=sha,
                    message=c.get("commit", {}).get("message", ""),
                    author=c.get("commit", {}).get("author", {}).get("name", "unknown"),
                    date=(
                        datetime.fromisoformat(
                            c.get("commit", {})
                            .get("author", {})
                            .get("date", "")
                            .replace("Z", "+00:00")
                        )
                        if c.get("commit", {}).get("author", {}).get("date")
                        else datetime.now(timezone.utc)
                    ),
                )
            )

        return commits

    async def _get_tree(self, sha: str) -> list[dict[str, Any]]:
        """Get file tree for a commit."""
        output = await self._run_gh(
            [
                "api",
                f"repos/{self.repo}/git/trees/{sha}",
                "-f",
                "recursive=1",
                "--jq",
                ".tree",
            ]
        )
        if not output:
            return []

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    async def _get_file_content(self, path: str) -> str | None:
        """Get file content from the repository."""
        output = await self._run_gh(
            [
                "api",
                f"repos/{self.repo}/contents/{path}",
                "-f",
                f"ref={self.branch}",
                "--jq",
                ".content",
            ]
        )
        if not output:
            return None

        # Decode base64 content
        import base64

        try:
            return base64.b64decode(output.strip()).decode("utf-8")
        except (ValueError, UnicodeDecodeError, TypeError) as e:
            logger.debug("Base64 decode failed for file content: %s", e)
            return None

    def _should_index_file(self, path: str, size: int) -> bool:
        """Check if a file should be indexed."""
        # Always include important files
        if Path(path).name in IMPORTANT_FILES:
            return True

        # Check exclusion paths
        for exclude in self.exclude_paths:
            if exclude in path:
                return False

        # Check file size
        if size > MAX_FILE_SIZE:
            return False

        # Check extension
        ext = Path(path).suffix.lower()
        return ext in self.file_extensions

    async def _get_issues(self, state: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        """Get issues from the repository."""
        output = await self._run_gh(
            [
                "issue",
                "list",
                "--repo",
                self.repo,
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,body,author,createdAt,url,state,labels",
            ]
        )
        if not output:
            return []

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    async def _get_prs(self, state: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        """Get PRs from the repository."""
        output = await self._run_gh(
            [
                "pr",
                "list",
                "--repo",
                self.repo,
                "--state",
                state,
                "--limit",
                str(limit),
                "--json",
                "number,title,body,author,createdAt,url,state,mergedAt",
            ]
        )
        if not output:
            return []

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    def _extract_code_elements(self, content: str, path: str) -> list[dict[str, Any]]:
        """Extract code elements (functions, classes) from file content."""
        elements = []
        ext = Path(path).suffix.lower()

        if ext == ".py":
            elements.extend(self._extract_python_elements(content, path))
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            elements.extend(self._extract_js_elements(content, path))

        return elements

    def _extract_python_elements(self, content: str, path: str) -> list[dict[str, Any]]:
        """Extract Python functions and classes using regex (fast, no AST dependency)."""
        elements = []

        # Extract class definitions
        class_pattern = r"^class\s+(\w+)(?:\([^)]*\))?:"
        for match in re.finditer(class_pattern, content, re.MULTILINE):
            elements.append(
                {
                    "type": "class",
                    "name": match.group(1),
                    "path": path,
                    "line": content[: match.start()].count("\n") + 1,
                }
            )

        # Extract function definitions
        func_pattern = r"^(?:async\s+)?def\s+(\w+)\s*\([^)]*\)(?:\s*->\s*[^:]+)?:"
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            elements.append(
                {
                    "type": "function",
                    "name": match.group(1),
                    "path": path,
                    "line": content[: match.start()].count("\n") + 1,
                }
            )

        return elements

    def _extract_js_elements(self, content: str, path: str) -> list[dict[str, Any]]:
        """Extract JavaScript/TypeScript functions and classes."""
        elements = []

        # Extract class definitions
        class_pattern = r"(?:export\s+)?class\s+(\w+)"
        for match in re.finditer(class_pattern, content):
            elements.append(
                {
                    "type": "class",
                    "name": match.group(1),
                    "path": path,
                    "line": content[: match.start()].count("\n") + 1,
                }
            )

        # Extract function definitions
        func_patterns = [
            r"(?:export\s+)?(?:async\s+)?function\s+(\w+)",  # Regular functions
            r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>",  # Arrow functions
        ]
        for pattern in func_patterns:
            for match in re.finditer(pattern, content):
                elements.append(
                    {
                        "type": "function",
                        "name": match.group(1),
                        "path": path,
                        "line": content[: match.start()].count("\n") + 1,
                    }
                )

        return elements

    def _extract_dependencies(self, content: str, path: str) -> list[str]:
        """Extract import dependencies from code."""
        dependencies = []
        ext = Path(path).suffix.lower()

        if ext == ".py":
            # Python imports
            import_pattern = r"^(?:from\s+([\w.]+)\s+)?import\s+([\w., ]+)"
            for match in re.finditer(import_pattern, content, re.MULTILINE):
                if match.group(1):
                    dependencies.append(match.group(1).split(".")[0])
                else:
                    for imp in match.group(2).split(","):
                        dependencies.append(imp.strip().split(".")[0].split(" ")[0])

        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            # JavaScript/TypeScript imports
            import_patterns = [
                r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]",
                r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            ]
            for pattern in import_patterns:
                for match in re.finditer(pattern, content):
                    dep = match.group(1)
                    if not dep.startswith("."):
                        dependencies.append(dep.split("/")[0])

        return list(set(dependencies))

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield items to sync from GitHub repository.

        Syncs:
        1. Changed files since last commit
        2. Issues (if enabled)
        3. PRs (if enabled)
        """
        # Get latest commit
        latest_sha = await self._get_latest_commit()
        if not latest_sha:
            logger.warning("[%s] Could not get latest commit", self.name)
            return

        # Get commits since last sync
        commits = await self._get_commits_since(state.cursor, limit=batch_size)

        if not commits and state.cursor == latest_sha:
            logger.info("[%s] No new commits since %s", self.name, state.cursor[:8])
        else:
            # Get file tree
            tree = await self._get_tree(latest_sha)
            state.items_total = len(tree)

            # Index files
            files_indexed = 0
            for item in tree:
                if item.get("type") != "blob":
                    continue

                path = item.get("path", "")
                size = item.get("size", 0)

                if not self._should_index_file(path, size):
                    continue

                # Get file content
                content = await self._get_file_content(path)
                if not content:
                    continue

                # Extract code elements
                elements = self._extract_code_elements(content, path)
                dependencies = self._extract_dependencies(content, path)

                # Determine domain based on file type
                ext = Path(path).suffix.lower()
                if ext in CODE_EXTENSIONS:
                    domain = "technical/code"
                elif ext in DOC_EXTENSIONS:
                    domain = "technical/documentation"
                else:
                    domain = "technical/configuration"

                yield SyncItem(
                    id=f"gh-file:{self.repo}:{item.get('sha', '')[:12]}",
                    content=content[:50000],  # Limit content size
                    source_type="code",
                    source_id=f"github/{self.repo}/blob/{self.branch}/{path}",
                    title=path,
                    url=f"https://github.com/{self.repo}/blob/{self.branch}/{path}",
                    domain=domain,
                    confidence=0.8,
                    metadata={
                        "path": path,
                        "sha": item.get("sha", ""),
                        "size": size,
                        "extension": ext,
                        "elements": elements[:20],  # Limit to 20 elements
                        "dependencies": dependencies[:30],  # Limit to 30 deps
                        "repo": self.repo,
                        "branch": self.branch,
                    },
                )

                files_indexed += 1
                if files_indexed >= batch_size:
                    break

        # Sync Issues
        if self.include_issues:
            issues = await self._get_issues(limit=batch_size)
            for issue in issues:
                yield SyncItem(
                    id=f"gh-issue:{self.repo}:{issue['number']}",
                    content=f"# {issue['title']}\n\n{issue.get('body', '')}",
                    source_type="issue",
                    source_id=f"github/{self.repo}/issues/{issue['number']}",
                    title=f"Issue #{issue['number']}: {issue['title']}",
                    url=issue.get("url", ""),
                    author=issue.get("author", {}).get("login", "unknown"),
                    created_at=(
                        datetime.fromisoformat(issue.get("createdAt", "").replace("Z", "+00:00"))
                        if issue.get("createdAt")
                        else None
                    ),
                    domain="technical/issues",
                    confidence=0.7,
                    metadata={
                        "number": issue["number"],
                        "state": issue.get("state", ""),
                        "labels": [label.get("name", "") for label in issue.get("labels", [])],
                    },
                )

        # Sync PRs
        if self.include_prs:
            prs = await self._get_prs(limit=batch_size)
            for pr in prs:
                yield SyncItem(
                    id=f"gh-pr:{self.repo}:{pr['number']}",
                    content=f"# {pr['title']}\n\n{pr.get('body', '')}",
                    source_type="pr",
                    source_id=f"github/{self.repo}/pull/{pr['number']}",
                    title=f"PR #{pr['number']}: {pr['title']}",
                    url=pr.get("url", ""),
                    author=pr.get("author", {}).get("login", "unknown"),
                    created_at=(
                        datetime.fromisoformat(pr.get("createdAt", "").replace("Z", "+00:00"))
                        if pr.get("createdAt")
                        else None
                    ),
                    domain="technical/pull-requests",
                    confidence=0.75,
                    metadata={
                        "number": pr["number"],
                        "state": pr.get("state", ""),
                        "merged": pr.get("mergedAt") is not None,
                    },
                )

        # Update cursor to latest commit
        state.cursor = latest_sha

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_type: str = "code",
        **kwargs: Any,
    ) -> list:
        """Search GitHub (delegates to existing GitHubConnector for compatibility)."""
        from aragora.connectors.github import GitHubConnector

        connector = GitHubConnector(repo=self.repo, use_gh_cli=True)
        return await connector.search(query, limit=limit, search_type=search_type, **kwargs)

    async def fetch(self, evidence_id: str) -> Any:
        """Fetch specific evidence (delegates to existing GitHubConnector)."""
        from aragora.connectors.github import GitHubConnector

        connector = GitHubConnector(repo=self.repo, use_gh_cli=True)
        return await connector.fetch(evidence_id)

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle GitHub webhook for real-time sync."""
        event_type = payload.get("action", "")

        if "push" in str(payload.get("ref", "")):
            # Push event - sync changed files
            commits = payload.get("commits", [])
            logger.info("[%s] Webhook: push with %s commits", self.name, len(commits))

            # Trigger incremental sync
            asyncio.create_task(self.sync(max_items=len(commits) * 10))
            return True

        elif event_type in {"opened", "closed", "reopened"}:
            # Issue/PR event
            issue = payload.get("issue") or payload.get("pull_request")
            if issue:
                logger.info("[%s] Webhook: %s #%s", self.name, event_type, issue.get("number"))
                return True

        return False

    def get_webhook_secret(self) -> str | None:
        """Get GitHub webhook secret from credentials."""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, use asyncio.run
            return asyncio.run(self.credentials.get_credential("GITHUB_WEBHOOK_SECRET"))
        else:
            # Loop is running, create a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run, self.credentials.get_credential("GITHUB_WEBHOOK_SECRET")
                )
                return future.result()
