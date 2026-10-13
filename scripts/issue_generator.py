#!/usr/bin/env python3
"""
Issue Generator for Nomic Loop

Scans the codebase to generate specific, actionable issues for the nomic loop
to debate. This replaces vague open-ended topics with concrete problems.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


@dataclass
class Issue:
    """A specific, actionable issue for the nomic loop to address."""

    id: str
    title: str
    description: str
    category: Literal["bug", "perf", "debt", "feature"]
    priority: int  # 1-5 (1 = highest)
    file_hints: list[str] = field(default_factory=list)
    complexity: Literal["small", "medium", "large"] = "medium"
    source: str = ""  # Where the issue was found (e.g., "TODO", "grep", "analysis")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "file_hints": self.file_hints,
            "complexity": self.complexity,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Issue:
        return cls(**data)


class IssueGenerator:
    """Generates specific, actionable issues from codebase analysis."""

    # Patterns to ignore
    IGNORE_DIRS = {
        ".git",
        "__pycache__",
        ".nomic",
        "node_modules",
        ".venv",
        "venv",
        ".comparison",
        "dist",
        "build",
    }
    IGNORE_FILES = {"package-lock.json", "yarn.lock", "poetry.lock"}

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        self._issues: list[Issue] = []

    def scan_for_issues(self) -> list[Issue]:
        """Scan codebase for concrete issues."""
        issues: list[Issue] = []

        # 1. Find TODO/FIXME comments
        issues.extend(self._extract_todo_issues())

        # 2. Find broad exception handlers
        issues.extend(self._find_exception_debt())

        # 3. Find large files (>500 LOC)
        issues.extend(self._find_large_files())

        # 4. Find untested modules
        issues.extend(self._find_untested_modules())

        # 5. Find deprecated patterns
        issues.extend(self._find_deprecated_usage())

        # Deduplicate by ID
        seen = set()
        unique_issues = []
        for issue in issues:
            if issue.id not in seen:
                seen.add(issue.id)
                unique_issues.append(issue)

        # Sort by priority
        return sorted(unique_issues, key=lambda i: (i.priority, i.title))

    def _generate_id(self, content: str) -> str:
        """Generate stable ID from content."""
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def _run_grep(self, pattern: str, glob: str = "*.py") -> list[tuple[str, int, str]]:
        """Run grep and return (file, line, content) tuples."""
        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include",
                    glob,
                    pattern,
                    str(self.repo_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            matches = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    file_path = parts[0]
                    # Skip ignored directories
                    if any(d in file_path for d in self.IGNORE_DIRS):
                        continue
                    try:
                        line_num = int(parts[1])
                        content = parts[2]
                        matches.append((file_path, line_num, content))
                    except ValueError:
                        continue
            return matches
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _read_module(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _extract_functions(self, content: str) -> list[str]:
        return [
            match.group(1)
            for match in re.finditer(r"(?:def|async def)\s+(\w+)\s*\(", content)
            if not match.group(1).startswith("_")
        ]

    def _extract_classes(self, content: str) -> list[str]:
        return [match.group(1) for match in re.finditer(r"class\s+(\w+)\s*[:(]", content)]

    def _extract_imports(self, content: str) -> list[str]:
        imports: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    def _extract_docstring(self, content: str) -> str:
        docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if not docstring_match:
            return ""
        return " ".join(docstring_match.group(1).strip().split())[:200]

    def _needs_mocking(self, imports: list[str]) -> list[str]:
        mock_patterns = [
            "redis",
            "postgres",
            "sqlite",
            "database",
            "db",
            "httpx",
            "requests",
            "aiohttp",
            "subprocess",
            "os.environ",
            "anthropic",
            "openai",
            "boto3",
            "s3",
        ]
        hints: list[str] = []
        for imp in imports:
            lowered = imp.lower()
            for pattern in mock_patterns:
                if pattern in lowered:
                    hints.append(f"Mock `{imp.split()[-1]}` — external dependency")
                    break
        return hints

    def _estimate_test_complexity(
        self,
        *,
        loc: int,
        num_functions: int,
        num_imports: int,
        has_async: bool,
    ) -> Literal["small", "medium", "large"]:
        if loc < 30 and num_functions <= 3:
            return "small"
        if loc < 100 and num_functions <= 7 and num_imports < 5 and not has_async:
            return "small"
        if loc < 300 and num_functions <= 15:
            return "medium"
        return "large"

    def _suggest_test_path(self, rel_path: Path) -> Path:
        if rel_path.parts and rel_path.parts[0] == "aragora":
            return Path("tests") / Path(*rel_path.parts[1:-1]) / f"test_{rel_path.name}"
        if rel_path.parts and rel_path.parts[0] == "scripts":
            return Path("tests") / "scripts" / f"test_{rel_path.stem}.py"
        return Path("tests") / f"test_{rel_path.stem}.py"

    def _extract_todo_issues(self) -> list[Issue]:
        """Convert TODO/FIXME comments to issues."""
        issues: list[Issue] = []

        for pattern, priority in [("FIXME", 2), ("TODO", 3), ("HACK", 3), ("XXX", 2)]:
            matches = self._run_grep(pattern)
            for file_path, line_num, content in matches:
                # Extract the actual message
                match = re.search(rf"{pattern}[:\s]+(.+)", content, re.IGNORECASE)
                if match:
                    message = match.group(1).strip()
                    # Skip very short or generic messages
                    if len(message) < 10:
                        continue

                    rel_path = Path(file_path).relative_to(self.repo_path)
                    issue = Issue(
                        id=self._generate_id(f"{file_path}:{line_num}:{pattern}"),
                        title=f"Address {pattern} in {rel_path.name}:{line_num}",
                        description=f"Found {pattern} comment: {message}\n\nLocation: {rel_path}:{line_num}",
                        category="debt",
                        priority=priority,
                        file_hints=[str(rel_path)],
                        complexity="small" if len(message) < 50 else "medium",
                        source=f"{pattern}:{file_path}:{line_num}",
                    )
                    issues.append(issue)

        return issues[:20]  # Limit to prevent overwhelming

    def _find_exception_debt(self) -> list[Issue]:
        """Find broad 'except Exception:' patterns."""
        issues: list[Issue] = []
        pattern = r"except\s+Exception\s*:"
        matches = self._run_grep(pattern)

        # Group by file
        by_file: dict[str, list[int]] = {}
        for file_path, line_num, _ in matches:
            rel_path = str(Path(file_path).relative_to(self.repo_path))
            if rel_path not in by_file:
                by_file[rel_path] = []
            by_file[rel_path].append(line_num)

        for rel_path, line_nums in by_file.items():
            issue = Issue(
                id=self._generate_id(f"broad_exception:{rel_path}"),
                title=f"Replace {len(line_nums)} broad exception handlers in {Path(rel_path).name}",
                description=(
                    f"Found {len(line_nums)} instances of 'except Exception:' in {rel_path}.\n\n"
                    f"Lines: {', '.join(str(n) for n in line_nums[:10])}"
                    f"{'...' if len(line_nums) > 10 else ''}\n\n"
                    "These should be replaced with specific exception types for better error handling."
                ),
                category="debt",
                priority=2,
                file_hints=[rel_path],
                complexity="medium" if len(line_nums) <= 5 else "large",
                source=f"grep:except_exception:{rel_path}",
            )
            issues.append(issue)

        return issues

    def _find_large_files(self) -> list[Issue]:
        """Find files larger than 500 lines."""
        issues: list[Issue] = []
        threshold = 500

        for py_file in self.repo_path.rglob("*.py"):
            # Skip ignored directories
            if any(d in str(py_file) for d in self.IGNORE_DIRS):
                continue

            try:
                with open(py_file, encoding="utf-8") as f:
                    lines = sum(1 for _ in f)

                if lines > threshold:
                    rel_path = py_file.relative_to(self.repo_path)
                    issue = Issue(
                        id=self._generate_id(f"large_file:{rel_path}"),
                        title=f"Refactor {rel_path.name} ({lines} LOC)",
                        description=(
                            f"File {rel_path} has {lines} lines of code, exceeding the "
                            f"{threshold} line threshold.\n\n"
                            "Consider breaking it into smaller, focused modules."
                        ),
                        category="debt",
                        priority=3 if lines < 800 else 2,
                        file_hints=[str(rel_path)],
                        complexity="large",
                        source=f"analysis:large_file:{rel_path}",
                    )
                    issues.append(issue)
            except (OSError, UnicodeDecodeError):
                continue

        def _loc(issue: Issue) -> int:
            match = re.search(r"\((\d+)", issue.title)
            return int(match.group(1)) if match else 0

        return sorted(issues, key=lambda i: -_loc(i))[:10]

    def _find_untested_modules(self) -> list[Issue]:
        """Find modules without corresponding test files."""
        issues: list[Issue] = []
        test_dir = self.repo_path / "tests"

        if not test_dir.exists():
            return issues

        # Get all test file names
        test_files = set()
        for test_file in test_dir.rglob("test_*.py"):
            # Extract module name from test_foo.py -> foo
            name = test_file.stem
            if name.startswith("test_"):
                test_files.add(name[5:])

        # Check main source files
        src_dirs = [self.repo_path / "aragora", self.repo_path / "scripts"]

        for src_dir in src_dirs:
            if not src_dir.exists():
                continue

            for py_file in src_dir.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                if any(d in str(py_file) for d in self.IGNORE_DIRS):
                    continue

                module_name = py_file.stem
                if module_name not in test_files:
                    rel_path = py_file.relative_to(self.repo_path)

                    # Check file size - only report for substantial files
                    try:
                        content = self._read_module(py_file)
                        if content is None:
                            continue
                        lines = len(content.splitlines())
                        if lines < 50:
                            continue
                    except OSError:
                        continue

                    functions = self._extract_functions(content)
                    classes = self._extract_classes(content)
                    imports = self._extract_imports(content)
                    docstring = self._extract_docstring(content)
                    has_async = "async def" in content
                    mock_hints = self._needs_mocking(imports)
                    suggested_test_path = self._suggest_test_path(rel_path)
                    complexity = self._estimate_test_complexity(
                        loc=lines,
                        num_functions=len(functions),
                        num_imports=len(imports),
                        has_async=has_async,
                    )
                    function_text = (
                        ", ".join(f"{name}()" for name in functions[:8])
                        if functions
                        else "no public functions found"
                    )
                    class_text = ", ".join(classes[:6]) if classes else "no classes found"
                    mock_text = (
                        "; ".join(mock_hints[:4])
                        if mock_hints
                        else "No obvious external dependencies"
                    )

                    issue = Issue(
                        id=self._generate_id(f"untested:{rel_path}"),
                        title=f"Add focused tests for {rel_path}",
                        description=(
                            f"Module {rel_path} ({lines} LOC) has no corresponding focused test file.\n\n"
                            f"Module purpose: {docstring or 'No module docstring found.'}\n"
                            f"Public API candidates: {function_text}\n"
                            f"Classes: {class_text}\n"
                            f"Mocking hints: {mock_text}\n"
                            f"Suggested test file: {suggested_test_path}"
                        ),
                        category="debt",
                        priority=4,
                        file_hints=[str(rel_path), str(suggested_test_path)],
                        complexity=complexity,
                        source=f"analysis:untested:{rel_path}",
                    )
                    issues.append(issue)

        return issues[:15]  # Limit

    def _find_deprecated_usage(self) -> list[Issue]:
        """Find deprecated patterns and APIs."""
        issues: list[Issue] = []

        deprecated_patterns = [
            (
                r"from typing import Optional",
                "Use X | None instead of Optional[X] (Python 3.10+)",
                4,
            ),
            (r"asyncio\.get_event_loop\(\)", "Use asyncio.get_running_loop() instead", 3),
            (r"\.format\(", "Consider using f-strings instead of .format()", 5),
            (r"os\.path\.", "Consider using pathlib.Path instead of os.path", 5),
        ]

        for pattern, description, priority in deprecated_patterns:
            matches = self._run_grep(pattern)
            if len(matches) >= 3:  # Only report if multiple occurrences
                files = list(set(Path(m[0]).relative_to(self.repo_path) for m in matches))
                issue = Issue(
                    id=self._generate_id(f"deprecated:{pattern}"),
                    title=f"Modernize: {description[:50]}",
                    description=(
                        f"{description}\n\n"
                        f"Found {len(matches)} occurrences in {len(files)} files:\n"
                        + "\n".join(f"- {f}" for f in files[:5])
                        + (f"\n... and {len(files) - 5} more" if len(files) > 5 else "")
                    ),
                    category="debt",
                    priority=priority,
                    file_hints=[str(f) for f in files[:5]],
                    complexity="medium" if len(matches) <= 10 else "large",
                    source=f"grep:deprecated:{pattern}",
                )
                issues.append(issue)

        return issues


class IssueSelector:
    """Select next issue for nomic cycle."""

    def __init__(self, backlog: list[Issue], history: list[dict] | None = None):
        self.backlog = backlog
        self.history = {h["id"] for h in (history or [])}

    def select_next(self) -> Issue | None:
        """Select highest priority unworked issue."""
        for issue in self.backlog:
            if issue.id not in self.history:
                return issue
        return None

    def get_top_n(self, n: int = 5) -> list[Issue]:
        """Get top N unworked issues."""
        result = []
        for issue in self.backlog:
            if issue.id not in self.history:
                result.append(issue)
                if len(result) >= n:
                    break
        return result


def load_issue_history(nomic_dir: Path) -> list[dict]:
    """Load issue history from nomic directory."""
    history_file = nomic_dir / "issue_history.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_issue_attempt(nomic_dir: Path, issue: Issue, outcome: str, cycle: int) -> None:
    """Save issue attempt to history."""
    from datetime import datetime

    history = load_issue_history(nomic_dir)
    history.append(
        {
            "id": issue.id,
            "title": issue.title,
            "cycle": cycle,
            "outcome": outcome,
            "timestamp": datetime.now().isoformat(),
        }
    )

    history_file = nomic_dir / "issue_history.json"
    history_file.write_text(json.dumps(history, indent=2))


if __name__ == "__main__":
    import sys

    # When run directly, scan and print issues
    repo_path = Path.cwd()
    if len(sys.argv) > 1:
        repo_path = Path(sys.argv[1])

    print(f"Scanning {repo_path} for issues...")
    generator = IssueGenerator(repo_path)
    issues = generator.scan_for_issues()

    print(f"\nFound {len(issues)} issues:\n")
    for i, issue in enumerate(issues, 1):
        print(f"{i}. [{issue.category}] {issue.title}")
        print(f"   Priority: {issue.priority}, Complexity: {issue.complexity}")
        print(f"   Files: {', '.join(issue.file_hints[:3])}")
        print(f"   {issue.description[:100]}...")
        print()
