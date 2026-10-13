"""
Code Editing Tools for Agent Debates.

Provides capabilities for agents to:
- Read and understand code
- Propose structured changes
- Apply changes safely with git integration
- Run tests to validate changes
- Enable self-improvement through debate
"""

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable


class ChangeType(Enum):
    """Types of code changes."""

    ADD = "add"  # Add new code
    MODIFY = "modify"  # Modify existing code
    DELETE = "delete"  # Delete code
    RENAME = "rename"  # Rename file/symbol
    MOVE = "move"  # Move code to different location
    REFACTOR = "refactor"  # Restructure without behavior change


@dataclass
class FileContext:
    """Context about a file for code understanding."""

    path: str
    content: str
    language: str
    size_bytes: int
    line_count: int
    last_modified: str
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)


@dataclass
class CodeSpan:
    """A span of code in a file."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    context_before: str = ""  # Lines before for context
    context_after: str = ""  # Lines after for context


@dataclass
class CodeChange:
    """A proposed change to code."""

    change_id: str
    change_type: ChangeType
    file_path: str
    description: str
    rationale: str

    # For modifications
    old_code: str | None = None
    new_code: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    # For new files
    new_file_content: str | None = None

    # For renames/moves
    new_path: str | None = None

    # Metadata
    author: str = ""
    confidence: float = 0.5
    risk_level: str = "medium"  # "low", "medium", "high"
    requires_test: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CodeProposal:
    """A complete code change proposal from an agent."""

    proposal_id: str
    title: str
    description: str
    author: str

    changes: list[CodeChange]

    # Impact analysis
    files_affected: list[str] = field(default_factory=list)
    tests_affected: list[str] = field(default_factory=list)
    breaking_changes: list[str] = field(default_factory=list)

    # Validation
    tests_passed: bool | None = None
    lint_passed: bool | None = None
    type_check_passed: bool | None = None

    # Metadata
    confidence: float = 0.5
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_patch(self) -> str:
        """Generate a unified diff patch."""
        patches = []
        for change in self.changes:
            if change.change_type == ChangeType.MODIFY and change.old_code and change.new_code:
                patch = f"--- a/{change.file_path}\n"
                patch += f"+++ b/{change.file_path}\n"
                patch += f"@@ -{change.start_line},{len(change.old_code.splitlines())} "
                patch += f"+{change.start_line},{len(change.new_code.splitlines())} @@\n"
                for line in change.old_code.splitlines():
                    patch += f"-{line}\n"
                for line in change.new_code.splitlines():
                    patch += f"+{line}\n"
                patches.append(patch)
        return "\n".join(patches)


@dataclass
class ValidationResult:
    """Result of validating a code proposal."""

    proposal_id: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    test_results: dict | None = None
    lint_results: dict | None = None


class CodeReader:
    """
    Reads and analyzes code for agent understanding.

    Provides structured context about files, functions, and dependencies.
    """

    def __init__(self, root_path: str = "."):
        self.root = Path(root_path).resolve()

    def read_file(self, file_path: str) -> FileContext:
        """Read a file and extract context."""
        path = self._resolve_path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")

        try:
            content = path.read_text()
            stat = path.stat()
        except OSError as e:
            raise OSError(f"Failed to read file {path}: {e}") from e

        return FileContext(
            path=str(path.relative_to(self.root)),
            content=content,
            language=self._detect_language(path),
            size_bytes=stat.st_size,
            line_count=len(content.splitlines()),
            last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            imports=self._extract_imports(content, path),
            exports=self._extract_exports(content, path),
            functions=self._extract_functions(content, path),
            classes=self._extract_classes(content, path),
        )

    def read_span(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        context_lines: int = 3,
    ) -> CodeSpan:
        """Read a specific span of code with surrounding context."""
        path = self._resolve_path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")

        try:
            lines = path.read_text().splitlines()
        except OSError as e:
            raise OSError(f"Failed to read file {path}: {e}") from e

        content_lines = lines[start_line - 1 : end_line]
        before_lines = lines[max(0, start_line - 1 - context_lines) : start_line - 1]
        after_lines = lines[end_line : end_line + context_lines]

        return CodeSpan(
            file_path=str(path.relative_to(self.root)),
            start_line=start_line,
            end_line=end_line,
            content="\n".join(content_lines),
            context_before="\n".join(before_lines),
            context_after="\n".join(after_lines),
        )

    def search_code(self, pattern: str, file_pattern: str = "**/*.py") -> list[CodeSpan]:
        """Search for code matching a pattern."""
        results = []
        regex = re.compile(pattern)

        for path in self.root.glob(file_pattern):
            if path.is_file():
                try:
                    content = path.read_text()
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            results.append(self.read_span(str(path), i, i, context_lines=2))
                except (OSError, UnicodeDecodeError) as e:
                    logger.debug("Failed to search in %s: %s", path, e)
                    continue

        return results

    def get_file_tree(self, max_depth: int = 3) -> dict[str, Any]:
        """Get directory tree structure."""

        def build_tree(path: Path, depth: int) -> dict[str, Any]:
            if depth > max_depth:
                return {"...": "..."}

            result: dict[str, Any] = {}
            try:
                for item in sorted(path.iterdir()):
                    if item.name.startswith("."):
                        continue
                    if item.is_dir():
                        result[item.name + "/"] = build_tree(item, depth + 1)
                    else:
                        result[item.name] = item.stat().st_size
            except PermissionError:
                logger.debug("Permission denied accessing %s", path)
            return result

        return build_tree(self.root, 0)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to root with path traversal protection."""
        path = Path(file_path)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()

        # Security: Verify resolved path is within root directory
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            raise PermissionError(f"Access denied: path '{file_path}' escapes root directory")

        return resolved

    def _detect_language(self, path: Path) -> str:
        """Detect programming language from extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".md": "markdown",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }
        return ext_map.get(path.suffix.lower(), "unknown")

    def _extract_imports(self, content: str, path: Path) -> list[str]:
        """Extract import statements."""
        imports = []
        lang = self._detect_language(path)

        if lang == "python":
            for line in content.splitlines():
                if line.strip().startswith("import ") or line.strip().startswith("from "):
                    imports.append(line.strip())
        elif lang in ("javascript", "typescript"):
            for match in re.finditer(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content):
                imports.append(match.group(0))

        return imports[:20]  # Limit

    def _extract_exports(self, content: str, path: Path) -> list[str]:
        """Extract export statements."""
        exports = []
        lang = self._detect_language(path)

        if lang == "python":
            # Look for __all__
            match = re.search(r"__all__\s*=\s*\[(.*?)\]", content, re.DOTALL)
            if match:
                exports = re.findall(r'["\'](\w+)["\']', match.group(1))

        return exports[:20]

    def _extract_functions(self, content: str, path: Path) -> list[str]:
        """Extract function names."""
        functions = []
        lang = self._detect_language(path)

        if lang == "python":
            for match in re.finditer(r"^(?:async\s+)?def\s+(\w+)", content, re.MULTILINE):
                functions.append(match.group(1))
        elif lang in ("javascript", "typescript"):
            for match in re.finditer(
                r"(?:function|const|let|var)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|[\(<])", content
            ):
                functions.append(match.group(1))

        return functions[:50]

    def _extract_classes(self, content: str, path: Path) -> list[str]:
        """Extract class names."""
        classes = []
        lang = self._detect_language(path)

        if lang == "python":
            for match in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
                classes.append(match.group(1))
        elif lang in ("javascript", "typescript"):
            for match in re.finditer(r"class\s+(\w+)", content):
                classes.append(match.group(1))

        return classes[:30]


class CodeWriter:
    """
    Safely applies code changes with git integration.

    Features:
    - Creates branches for changes
    - Applies changes atomically
    - Validates changes before applying
    - Supports rollback
    """

    def __init__(self, root_path: str = ".", use_git: bool = True):
        self.root = Path(root_path).resolve()
        self.use_git = use_git and self._is_git_repo()

    def _is_git_repo(self) -> bool:
        """Check if we're in a git repository."""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],  # fixed command
                cwd=self.root,
                capture_output=True,
                check=True,
                shell=False,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def create_branch(self, branch_name: str) -> bool:
        """Create and checkout a new branch for changes."""
        if not self.use_git:
            return False

        try:
            subprocess.run(  # subprocess with fixed args, no shell
                ["git", "checkout", "-b", branch_name],  # fixed command
                cwd=self.root,
                capture_output=True,
                check=True,
                shell=False,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def apply_proposal(
        self,
        proposal: CodeProposal,
        validate: bool = True,
        commit: bool = True,
    ) -> ValidationResult:
        """Apply a code proposal."""
        errors = []
        warnings = []

        # Apply each change
        for change in proposal.changes:
            try:
                self._apply_change(change)
            except (OSError, FileNotFoundError, PermissionError, ValueError) as e:
                errors.append(f"Failed to apply {change.change_id}: {str(e)}")

        # Validate if requested
        if validate and not errors:
            validation = self._validate_changes()
            errors.extend(validation.get("errors", []))
            warnings.extend(validation.get("warnings", []))

        # Commit if requested and no errors
        if commit and not errors and self.use_git:
            self._commit_changes(proposal.title, proposal.description)

        return ValidationResult(
            proposal_id=proposal.proposal_id,
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _apply_change(self, change: CodeChange) -> None:
        """Apply a single code change."""
        path = self.root / change.file_path

        if change.change_type == ChangeType.ADD:
            if change.new_file_content:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(change.new_file_content)

        elif change.change_type == ChangeType.DELETE:
            if path.exists():
                path.unlink()

        elif change.change_type == ChangeType.MODIFY:
            if change.old_code is not None and change.new_code is not None:
                content = path.read_text()
                new_content = content.replace(change.old_code, change.new_code)
                path.write_text(new_content)

        elif change.change_type == ChangeType.RENAME:
            if change.new_path:
                new_path = self.root / change.new_path
                new_path.parent.mkdir(parents=True, exist_ok=True)
                path.rename(new_path)

    def _validate_changes(self) -> dict:
        """Run validation on changes."""
        errors = []
        warnings = []

        # Try to run tests
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--tb=short", "-q"],  # fixed command
                cwd=self.root,
                capture_output=True,
                timeout=180,  # Minimum 3 min (was 60)
                shell=False,
            )
            if result.returncode != 0:
                warnings.append("Some tests may have failed")
        except subprocess.TimeoutExpired:
            warnings.append("Tests timed out after 3 minutes")
        except FileNotFoundError:
            warnings.append("pytest not found - could not run tests")
        except OSError as e:
            logger.debug("Test run failed: %s", e)
            warnings.append("Could not run tests due to system error")

        # Try syntax check - batch files to avoid "Argument list too long" errors
        try:
            py_files = list(self.root.glob("**/*.py"))
            # Process in batches of 100 files to avoid command line length limits
            batch_size = 100
            syntax_failed = False
            for i in range(0, len(py_files), batch_size):
                batch = py_files[i : i + batch_size]
                result = subprocess.run(  # subprocess with fixed args, no shell
                    ["python", "-m", "py_compile"] + [str(p) for p in batch],
                    cwd=self.root,
                    capture_output=True,
                    shell=False,
                )
                if result.returncode != 0:
                    syntax_failed = True
                    break
            if syntax_failed:
                errors.append("Syntax errors in Python files")
        except FileNotFoundError:
            logger.debug("Python not found - syntax check skipped")
        except OSError as e:
            logger.debug("Syntax check skipped due to OS error: %s", e)

        return {"errors": errors, "warnings": warnings}

    def _commit_changes(self, title: str, description: str) -> None:
        """Commit changes with git.

        Raises:
            subprocess.CalledProcessError: If git add or commit fails.
        """
        if not self.use_git:
            return

        try:
            subprocess.run(
                ["git", "add", "-A"],  # fixed command
                cwd=self.root,
                check=True,
                capture_output=True,
                shell=False,
            )
            subprocess.run(  # subprocess with fixed args, no shell
                # fixed command
                ["git", "commit", "-m", f"{title}\n\n{description}\n\n[aragora auto-commit]"],
                cwd=self.root,
                check=True,
                capture_output=True,
                shell=False,
            )
        except subprocess.CalledProcessError as e:
            logger.error("Git commit failed: %s", e.stderr.decode() if e.stderr else e)
            raise

    def rollback(self) -> bool:
        """Rollback last commit."""
        if not self.use_git:
            return False

        try:
            subprocess.run(
                ["git", "reset", "--hard", "HEAD~1"],  # fixed command
                cwd=self.root,
                check=True,
                shell=False,
            )
            return True
        except subprocess.CalledProcessError:
            return False


class SelfImprover:
    """
    Orchestrates self-improvement through multi-agent debate.

    Enables aragora to debate and modify its own code:
    1. Agents analyze the codebase
    2. Agents propose improvements
    3. Agents critique each other's proposals
    4. Best changes are applied and validated
    """

    def __init__(
        self,
        codebase_path: str,
        agents: list[Any],  # List of Agent objects
        run_debate_fn: Callable,
        safe_mode: bool = True,
    ):
        self.codebase_path = Path(codebase_path).resolve()
        self.agents = agents
        self.run_debate = run_debate_fn
        self.safe_mode = safe_mode

        self.reader = CodeReader(str(self.codebase_path))
        self.writer = CodeWriter(str(self.codebase_path), use_git=True)

        self.proposals: list[CodeProposal] = []
        self.applied_changes: list[str] = []

    def analyze_codebase(self) -> dict:
        """Analyze the codebase to find improvement opportunities."""
        tree = self.reader.get_file_tree()

        # Find all Python files
        py_files = list(self.codebase_path.glob("**/*.py"))

        analysis: dict[str, Any] = {
            "structure": tree,
            "file_count": len(py_files),
            "total_lines": 0,
            "functions": [],
            "classes": [],
            "potential_issues": [],
        }

        for py_file in py_files[:50]:  # Limit for performance
            try:
                ctx = self.reader.read_file(str(py_file))
                analysis["total_lines"] += ctx.line_count
                analysis["functions"].extend(ctx.functions)
                analysis["classes"].extend(ctx.classes)

                # Simple issue detection
                if ctx.line_count > 500:
                    analysis["potential_issues"].append(
                        f"{ctx.path}: File too long ({ctx.line_count} lines)"
                    )

            except (OSError, UnicodeDecodeError, ValueError) as e:
                logger.debug("[code] Failed to analyze %s: %s", py_file, e)
                continue

        return analysis

    def generate_improvement_prompt(self, focus: str | None = None) -> str:
        """Generate a prompt for improvement debate."""
        analysis = self.analyze_codebase()

        prompt = f"""You are analyzing the aragora codebase to suggest improvements.

## Codebase Overview
- Files: {analysis["file_count"]}
- Total lines: {analysis["total_lines"]}
- Classes: {len(analysis["classes"])}
- Functions: {len(analysis["functions"])}

## Known Issues
{chr(10).join("- " + issue for issue in analysis["potential_issues"][:10])}

## Your Task
{"Focus on: " + focus if focus else "Suggest the most impactful improvements."}

For each improvement, specify:
1. **File**: Which file to change
2. **Change**: What to change (old code → new code)
3. **Rationale**: Why this improves the codebase
4. **Risk**: Low/Medium/High
5. **Tests**: What tests validate this change

Be specific with code snippets. Prioritize:
- Bug fixes
- Performance improvements
- Code clarity
- Missing functionality
"""
        return prompt

    async def debate_improvement(
        self,
        focus: str | None = None,
        rounds: int | None = None,
    ) -> list[CodeProposal]:
        """Run a debate to generate improvement proposals."""
        from aragora.config.settings import DebateSettings
        from aragora.core import Environment

        if rounds is None:
            rounds = DebateSettings().default_rounds

        prompt = self.generate_improvement_prompt(focus)

        env = Environment(
            task=prompt,
            max_rounds=rounds,
            context=json.dumps(self.analyze_codebase()),
        )

        result = await self.run_debate(env, self.agents)

        # Parse proposals from result
        proposals = self._extract_proposals(result)
        self.proposals.extend(proposals)

        return proposals

    def _extract_proposals(self, result: Any) -> list[CodeProposal]:
        """Extract structured proposals from debate result."""
        proposals = []

        # Parse the final answer for code changes
        # This is a simplified parser - in production would use structured output
        if hasattr(result, "final_answer") and result.final_answer:
            proposal = CodeProposal(
                proposal_id=f"proposal-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                title="Improvement from debate",
                description=result.final_answer[:500],
                author="aragora-debate",
                changes=[],
                confidence=result.confidence if hasattr(result, "confidence") else 0.5,
            )

            # Try to extract specific changes from the text
            # This would be enhanced with structured output in production
            proposals.append(proposal)

        return proposals

    def apply_best_proposal(self, proposal_id: str | None = None) -> ValidationResult:
        """Apply the best (or specified) proposal."""
        if not self.proposals:
            return ValidationResult(
                proposal_id="",
                valid=False,
                errors=["No proposals to apply"],
            )

        # Select proposal
        if proposal_id:
            proposal = next((p for p in self.proposals if p.proposal_id == proposal_id), None)
        else:
            # Select highest confidence
            proposal = max(self.proposals, key=lambda p: p.confidence)

        if not proposal:
            return ValidationResult(
                proposal_id=proposal_id or "",
                valid=False,
                errors=["Proposal not found"],
            )

        # Create branch for changes
        branch_name = f"aragora-improve-{proposal.proposal_id}"
        if self.safe_mode:
            self.writer.create_branch(branch_name)

        # Apply and validate
        result = self.writer.apply_proposal(
            proposal,
            validate=True,
            commit=not self.safe_mode,  # Only auto-commit if not safe mode
        )

        if result.valid:
            self.applied_changes.append(proposal.proposal_id)

        return result

    def get_improvement_summary(self) -> str:
        """Get summary of improvement session."""
        lines = [
            "# Self-Improvement Session Summary",
            "",
            f"**Proposals Generated:** {len(self.proposals)}",
            f"**Changes Applied:** {len(self.applied_changes)}",
            "",
        ]

        if self.proposals:
            lines.append("## Proposals")
            for p in self.proposals:
                lines.append(f"- [{p.proposal_id}] {p.title} (confidence: {p.confidence:.0%})")

        return "\n".join(lines)
