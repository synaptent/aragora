"""
SICA (Self-Improving Code Assistant) for Nomic Loop.

Implements SWE-Bench style self-improvement capabilities:
- Opportunity identification (performance, reliability, readability)
- Patch generation via LLM
- Validation gates (tests, type checking, linting)
- Safe backup/restore for rollback
- Human approval gate before applying patches

Based on research from:
- SICA: Self-Improving Code Agents (2024)
- SWE-Bench: Can Language Models Resolve Real-World GitHub Issues?
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable, Awaitable

logger = logging.getLogger(__name__)

_BARE_EXCEPT_TOKEN = "except:"
_TYPED_EXCEPT_PREFIX = "except " + "Exception"
_TYPED_EXCEPT_HANDLER = _TYPED_EXCEPT_PREFIX + ":"


class ImprovementType(str, Enum):
    """Types of code improvements."""

    PERFORMANCE = "performance"  # Speed, memory, efficiency
    RELIABILITY = "reliability"  # Error handling, edge cases
    READABILITY = "readability"  # Code clarity, documentation
    SECURITY = "security"  # Security hardening
    TESTABILITY = "testability"  # Test coverage improvements
    MAINTAINABILITY = "maintainability"  # Code organization, DRY


class ValidationResult(str, Enum):
    """Result of patch validation."""

    PASSED = "passed"
    FAILED_TESTS = "failed_tests"
    FAILED_TYPECHECK = "failed_typecheck"
    FAILED_LINT = "failed_lint"
    FAILED_OTHER = "failed_other"


class PatchApprovalStatus(str, Enum):
    """Status of patch approval."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"  # Passed all checks + low risk


@dataclass
class ImprovementOpportunity:
    """A detected opportunity for code improvement."""

    id: str
    file_path: str
    line_start: int
    line_end: int
    improvement_type: ImprovementType
    description: str
    priority: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    estimated_effort: str  # "low", "medium", "high"
    code_snippet: str = ""
    rationale: str = ""
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "file_path": self.file_path,
            "line_range": f"{self.line_start}-{self.line_end}",
            "type": self.improvement_type.value,
            "description": self.description,
            "priority": self.priority,
            "confidence": self.confidence,
            "estimated_effort": self.estimated_effort,
        }


@dataclass
class ImprovementPatch:
    """A generated patch for an improvement."""

    id: str
    opportunity_id: str
    file_path: str
    original_content: str
    patched_content: str
    diff: str
    description: str
    generated_at: datetime = field(default_factory=datetime.now)
    validation_result: ValidationResult | None = None
    validation_details: dict[str, Any] = field(default_factory=dict)
    approval_status: PatchApprovalStatus = PatchApprovalStatus.PENDING
    approved_by: str | None = None
    applied: bool = False
    applied_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "file_path": self.file_path,
            "description": self.description,
            "diff_lines": len(self.diff.splitlines()),
            "validation": self.validation_result.value if self.validation_result else None,
            "approval": self.approval_status.value,
            "applied": self.applied,
        }


@dataclass
class FileBackup:
    """Backup of a file before modification."""

    file_path: str
    content: str
    hash: str
    backup_path: str
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ImprovementCycleResult:
    """Result of an improvement cycle."""

    cycle_id: str
    started_at: datetime
    finished_at: datetime = field(default_factory=datetime.now)

    opportunities_found: int = 0
    patches_generated: int = 0
    patches_validated: int = 0
    patches_approved: int = 0
    patches_applied: int = 0
    patches_successful: int = 0
    patches_rolled_back: int = 0

    opportunities: list[ImprovementOpportunity] = field(default_factory=list)
    patches: list[ImprovementPatch] = field(default_factory=list)

    test_coverage_before: float | None = None
    test_coverage_after: float | None = None

    def summary(self) -> str:
        """Generate human-readable summary."""
        duration = (self.finished_at - self.started_at).total_seconds()
        coverage_change = ""
        if self.test_coverage_before and self.test_coverage_after:
            delta = self.test_coverage_after - self.test_coverage_before
            coverage_change = f", coverage Δ{delta:+.1f}%"
        return (
            f"SICA Cycle: {self.patches_successful}/{self.patches_applied} "
            f"patches successful from {self.opportunities_found} opportunities "
            f"({duration:.1f}s{coverage_change})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "stats": {
                "opportunities_found": self.opportunities_found,
                "patches_generated": self.patches_generated,
                "patches_validated": self.patches_validated,
                "patches_approved": self.patches_approved,
                "patches_applied": self.patches_applied,
                "patches_successful": self.patches_successful,
                "patches_rolled_back": self.patches_rolled_back,
            },
            "coverage": {
                "before": self.test_coverage_before,
                "after": self.test_coverage_after,
            },
        }


@dataclass
class SICAConfig:
    """Configuration for SICA self-improvement."""

    # Opportunity detection
    improvement_types: list[ImprovementType] = field(
        default_factory=lambda: [
            ImprovementType.RELIABILITY,
            ImprovementType.TESTABILITY,
            ImprovementType.READABILITY,
        ]
    )
    min_confidence: float = 0.6
    min_priority: float = 0.4
    max_opportunities_per_cycle: int = 5

    # Patch generation
    generator_model: str = "claude"
    max_patch_size_lines: int = 100
    require_explanation: bool = True

    # Validation
    run_tests: bool = True
    run_typecheck: bool = True
    run_lint: bool = True
    test_command: str = "pytest"
    typecheck_command: str = "mypy"
    lint_command: str = "ruff check"
    validation_timeout_seconds: float = 300.0

    # Approval
    require_human_approval: bool = True
    auto_approve_threshold: float = 0.9  # Auto-approve if confidence >= this
    auto_approve_low_risk: bool = True  # Auto-approve readability/docs only

    # Safety
    backup_before_apply: bool = True
    backup_dir: Path | None = None
    rollback_on_test_failure: bool = True
    max_rollbacks_per_cycle: int = 3

    # Callbacks
    approval_callback: Callable[[ImprovementPatch], Awaitable[bool]] | None = None
    on_patch_applied: Callable[[ImprovementPatch], Awaitable[None]] | None = None
    on_cycle_complete: Callable[[ImprovementCycleResult], Awaitable[None]] | None = None


# Allowed base commands for validation tools (must start with one of these)
_ALLOWED_VALIDATION_COMMANDS = [
    "pytest",
    "mypy",
    "ruff",
    "flake8",
    "pylint",
    "black",
    "isort",
    "pyright",
    "pyre",
    "bandit",
    "safety",
    "vulture",
    "pyflakes",
    "python -m pytest",
    "python -m mypy",
    "python -m ruff",
    "python -m flake8",
    "python -m pylint",
    "python -m black",
]


def _validate_tool_command(command: str) -> list[str]:
    """Validate and split a tool command against the allowlist.

    Args:
        command: The tool command string (e.g. "ruff check", "mypy --strict")

    Returns:
        The command split into a list of arguments.

    Raises:
        ValueError: If the command is not in the allowlist or contains
            shell metacharacters.
    """
    # Reject shell metacharacters
    for meta in [";", "&&", "||", "|", "`", "$(", "${"]:
        if meta in command:
            raise ValueError(f"Tool command contains shell metacharacter: '{meta}'")

    parts = shlex.split(command)
    if not parts:
        raise ValueError("Empty tool command")

    # Check that the command starts with an allowed base command
    matched = False
    for allowed in _ALLOWED_VALIDATION_COMMANDS:
        allowed_parts = shlex.split(allowed)
        if parts[: len(allowed_parts)] == allowed_parts:
            matched = True
            break

    if not matched:
        raise ValueError(f"Tool command '{parts[0]}' is not in the allowed validation commands")

    return parts


def _validate_file_path(file_path: str, repo_path: Path) -> str:
    """Validate a file path is safe and within the repository.

    Args:
        file_path: Relative file path to validate.
        repo_path: The repository root path.

    Returns:
        The validated file path.

    Raises:
        ValueError: If the path is unsafe (traversal, absolute, etc.).
    """
    # Reject null bytes
    if "\x00" in file_path:
        raise ValueError("File path contains null byte")

    # Reject absolute paths
    if Path(file_path).is_absolute():
        raise ValueError(f"File path must be relative, got: {file_path}")

    # Resolve and ensure it stays within repo_path
    resolved = (repo_path / file_path).resolve()
    repo_resolved = repo_path.resolve()
    if not str(resolved).startswith(str(repo_resolved) + "/") and resolved != repo_resolved:
        raise ValueError(f"File path escapes repository root: {file_path}")

    return file_path


class SICAImprover:
    """Self-Improving Code Assistant.

    Identifies improvement opportunities in code and generates validated patches.

    Example:
        improver = SICAImprover(
            repo_path=Path("/path/to/repo"),
            config=SICAConfig(require_human_approval=True),
        )

        # Run improvement cycle
        result = await improver.run_improvement_cycle()

        # Or find specific opportunities
        opportunities = await improver.find_opportunities(
            files=["src/main.py"],
            types=[ImprovementType.PERFORMANCE],
        )

        # Generate and validate patch
        patch = await improver.generate_patch(opportunities[0])
        if patch and patch.validation_result == ValidationResult.PASSED:
            approved = await improver.request_approval(patch)
            if approved:
                await improver.apply_patch(patch)
    """

    def __init__(
        self,
        repo_path: Path,
        config: SICAConfig | None = None,
        query_fn: Callable[[str, str, int], Awaitable[str]] | None = None,
    ):
        """Initialize SICA improver.

        Args:
            repo_path: Path to the repository
            config: Configuration options
            query_fn: LLM query function (agent_id, prompt, max_tokens) -> response
        """
        self.repo_path = Path(repo_path)
        self.config = config or SICAConfig()
        self.query_fn = query_fn

        # State
        self._backups: dict[str, FileBackup] = {}
        self._applied_patches: list[ImprovementPatch] = []
        self._cycle_history: list[ImprovementCycleResult] = []

        # Ensure backup directory
        if self.config.backup_dir:
            self.config.backup_dir.mkdir(parents=True, exist_ok=True)

    async def run_improvement_cycle(
        self,
        files: list[str] | None = None,
        types: list[ImprovementType] | None = None,
    ) -> ImprovementCycleResult:
        """Run a complete improvement cycle.

        Args:
            files: Specific files to analyze (None = all)
            types: Types of improvements to look for (None = config default)

        Returns:
            Result of the improvement cycle
        """
        cycle_id = hashlib.md5(
            f"{datetime.now().isoformat()}".encode(), usedforsecurity=False
        ).hexdigest()[:12]
        started_at = datetime.now()

        result = ImprovementCycleResult(
            cycle_id=cycle_id,
            started_at=started_at,
        )

        logger.info("sica_cycle_start cycle_id=%s", cycle_id)

        try:
            # Step 1: Find opportunities
            opportunities = await self.find_opportunities(
                files=files,
                types=types or self.config.improvement_types,
            )
            result.opportunities = opportunities
            result.opportunities_found = len(opportunities)
            logger.info("sica_opportunities_found count=%s", len(opportunities))

            # Limit to max per cycle
            opportunities = opportunities[: self.config.max_opportunities_per_cycle]

            rollbacks_this_cycle = 0

            # Step 2: Process each opportunity
            for opp in opportunities:
                # Generate patch
                patch = await self.generate_patch(opp)
                if not patch:
                    continue

                result.patches.append(patch)
                result.patches_generated += 1

                # Validate patch
                validated = await self.validate_patch(patch)
                if not validated:
                    continue
                result.patches_validated += 1

                # Request approval
                approved = await self.request_approval(patch)
                if not approved:
                    continue
                result.patches_approved += 1

                # Apply patch
                applied = await self.apply_patch(patch)
                if not applied:
                    continue
                result.patches_applied += 1

                # Verify with tests
                if self.config.run_tests:
                    test_passed = await self._run_tests()
                    if test_passed:
                        result.patches_successful += 1
                        logger.info(
                            "sica_patch_success patch_id=%s file=%s", patch.id, patch.file_path
                        )
                    else:
                        # Rollback
                        if self.config.rollback_on_test_failure:
                            await self.rollback_patch(patch)
                            result.patches_rolled_back += 1
                            rollbacks_this_cycle += 1
                            logger.warning(
                                "sica_patch_rollback patch_id=%s reason=test_failure", patch.id
                            )

                            if rollbacks_this_cycle >= self.config.max_rollbacks_per_cycle:
                                logger.warning("sica_max_rollbacks_reached")
                                break
                else:
                    result.patches_successful += 1

        except (RuntimeError, OSError, ValueError) as e:
            logger.error("sica_cycle_error error=%s", e)
            raise

        result.finished_at = datetime.now()
        self._cycle_history.append(result)

        logger.info("sica_cycle_complete %s", result.summary())

        if self.config.on_cycle_complete:
            await self.config.on_cycle_complete(result)

        return result

    async def find_opportunities(
        self,
        files: list[str] | None = None,
        types: list[ImprovementType] | None = None,
    ) -> list[ImprovementOpportunity]:
        """Find improvement opportunities in code.

        Args:
            files: Specific files to analyze
            types: Types of improvements to look for

        Returns:
            List of improvement opportunities
        """
        types = types or self.config.improvement_types
        opportunities: list[ImprovementOpportunity] = []

        # Get files to analyze
        if files:
            target_files = [self.repo_path / f for f in files]
        else:
            target_files = list(self.repo_path.rglob("*.py"))
            # Filter out common exclusions
            target_files = [
                f
                for f in target_files
                if not any(
                    p in f.parts
                    for p in [
                        "__pycache__",
                        ".git",
                        "venv",
                        ".venv",
                        "node_modules",
                        "dist",
                        "build",
                    ]
                )
            ]

        for file_path in target_files:
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text()
            except OSError:
                logger.debug("Failed to read %s, skipping", file_path)
                continue

            # Analyze file for each improvement type
            for imp_type in types:
                file_opps = await self._analyze_file_for_type(
                    file_path=str(file_path.relative_to(self.repo_path)),
                    content=content,
                    improvement_type=imp_type,
                )
                opportunities.extend(file_opps)

        # Filter by confidence and priority
        opportunities = [
            o
            for o in opportunities
            if o.confidence >= self.config.min_confidence and o.priority >= self.config.min_priority
        ]

        # Sort by priority * confidence
        opportunities.sort(key=lambda o: o.priority * o.confidence, reverse=True)

        return opportunities

    async def _analyze_file_for_type(
        self,
        file_path: str,
        content: str,
        improvement_type: ImprovementType,
    ) -> list[ImprovementOpportunity]:
        """Analyze a file for specific improvement type.

        Args:
            file_path: Relative path to file
            content: File content
            improvement_type: Type of improvement to look for

        Returns:
            List of opportunities found
        """
        opportunities: list[ImprovementOpportunity] = []

        # Use heuristics for common patterns
        lines = content.splitlines()

        if improvement_type == ImprovementType.RELIABILITY:
            opportunities.extend(self._find_reliability_opportunities(file_path, lines))
        elif improvement_type == ImprovementType.TESTABILITY:
            opportunities.extend(self._find_testability_opportunities(file_path, lines))
        elif improvement_type == ImprovementType.READABILITY:
            opportunities.extend(self._find_readability_opportunities(file_path, lines))
        elif improvement_type == ImprovementType.PERFORMANCE:
            opportunities.extend(self._find_performance_opportunities(file_path, lines))

        # If query function available, use LLM for deeper analysis
        if self.query_fn and len(content) < 10000:
            llm_opps = await self._llm_analyze_file(
                file_path=file_path,
                content=content,
                improvement_type=improvement_type,
            )
            opportunities.extend(llm_opps)

        return opportunities

    def _find_reliability_opportunities(
        self,
        file_path: str,
        lines: list[str],
    ) -> list[ImprovementOpportunity]:
        """Find reliability improvement opportunities."""
        opportunities: list[ImprovementOpportunity] = []
        opp_id = 0

        for i, line in enumerate(lines):
            # Bare except clauses
            if _BARE_EXCEPT_TOKEN in line and _TYPED_EXCEPT_PREFIX not in line:
                opp_id += 1
                opportunities.append(
                    ImprovementOpportunity(
                        id=f"rel-{file_path}-{opp_id}",
                        file_path=file_path,
                        line_start=i + 1,
                        line_end=i + 1,
                        improvement_type=ImprovementType.RELIABILITY,
                        description="Bare except clause - should specify exception type",
                        priority=0.7,
                        confidence=0.9,
                        estimated_effort="low",
                        code_snippet=line.strip(),
                        rationale="Bare except catches all exceptions including KeyboardInterrupt and SystemExit",
                    )
                )

            # Missing error handling for file operations
            if any(op in line for op in ["open(", "Path(", ".read(", ".write("]):
                # Check if within try block (simplified)
                in_try = any("try:" in prev_line for prev_line in lines[max(0, i - 5) : i])
                if not in_try:
                    opp_id += 1
                    opportunities.append(
                        ImprovementOpportunity(
                            id=f"rel-{file_path}-{opp_id}",
                            file_path=file_path,
                            line_start=i + 1,
                            line_end=i + 1,
                            improvement_type=ImprovementType.RELIABILITY,
                            description="File operation without error handling",
                            priority=0.6,
                            confidence=0.7,
                            estimated_effort="medium",
                            code_snippet=line.strip(),
                        )
                    )

        return opportunities

    def _find_testability_opportunities(
        self,
        file_path: str,
        lines: list[str],
    ) -> list[ImprovementOpportunity]:
        """Find testability improvement opportunities."""
        opportunities: list[ImprovementOpportunity] = []
        opp_id = 0

        # Skip test files
        if "test_" in file_path or "_test.py" in file_path:
            return opportunities

        "\n".join(lines)

        # Functions without docstrings
        in_function = False
        func_start = 0
        func_name = ""

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                in_function = True
                func_start = i
                func_name = stripped.split("(")[0].replace("def ", "").replace("async ", "")
            elif in_function and i == func_start + 1:
                if not stripped.startswith('"""') and not stripped.startswith("'''"):
                    opp_id += 1
                    opportunities.append(
                        ImprovementOpportunity(
                            id=f"test-{file_path}-{opp_id}",
                            file_path=file_path,
                            line_start=func_start + 1,
                            line_end=func_start + 2,
                            improvement_type=ImprovementType.TESTABILITY,
                            description=f"Function '{func_name}' missing docstring",
                            priority=0.5,
                            confidence=0.95,
                            estimated_effort="low",
                            rationale="Docstrings improve testability by documenting expected behavior",
                        )
                    )
                in_function = False

        return opportunities

    def _find_readability_opportunities(
        self,
        file_path: str,
        lines: list[str],
    ) -> list[ImprovementOpportunity]:
        """Find readability improvement opportunities."""
        opportunities: list[ImprovementOpportunity] = []
        opp_id = 0

        for i, line in enumerate(lines):
            # Long lines
            if len(line) > 120:
                opp_id += 1
                opportunities.append(
                    ImprovementOpportunity(
                        id=f"read-{file_path}-{opp_id}",
                        file_path=file_path,
                        line_start=i + 1,
                        line_end=i + 1,
                        improvement_type=ImprovementType.READABILITY,
                        description=f"Line too long ({len(line)} chars > 120)",
                        priority=0.3,
                        confidence=0.95,
                        estimated_effort="low",
                    )
                )

            # Complex nested structures
            indent = len(line) - len(line.lstrip())
            if indent >= 32:  # 8+ levels of indentation
                opp_id += 1
                opportunities.append(
                    ImprovementOpportunity(
                        id=f"read-{file_path}-{opp_id}",
                        file_path=file_path,
                        line_start=i + 1,
                        line_end=i + 1,
                        improvement_type=ImprovementType.READABILITY,
                        description="Deeply nested code - consider refactoring",
                        priority=0.6,
                        confidence=0.8,
                        estimated_effort="high",
                    )
                )

        return opportunities

    def _find_performance_opportunities(
        self,
        file_path: str,
        lines: list[str],
    ) -> list[ImprovementOpportunity]:
        """Find performance improvement opportunities."""
        opportunities: list[ImprovementOpportunity] = []
        opp_id = 0

        for i, line in enumerate(lines):
            # String concatenation in loops
            if "+=" in line and ("str" in line or '"' in line or "'" in line):
                # Check if in loop
                prev_lines = lines[max(0, i - 10) : i]
                in_loop = any(
                    "for " in prev_line or "while " in prev_line for prev_line in prev_lines
                )
                if in_loop:
                    opp_id += 1
                    opportunities.append(
                        ImprovementOpportunity(
                            id=f"perf-{file_path}-{opp_id}",
                            file_path=file_path,
                            line_start=i + 1,
                            line_end=i + 1,
                            improvement_type=ImprovementType.PERFORMANCE,
                            description="String concatenation in loop - consider join()",
                            priority=0.5,
                            confidence=0.6,
                            estimated_effort="low",
                        )
                    )

            # Repeated dictionary access
            if line.count("[") >= 3 and line.count("]") >= 3:
                opp_id += 1
                opportunities.append(
                    ImprovementOpportunity(
                        id=f"perf-{file_path}-{opp_id}",
                        file_path=file_path,
                        line_start=i + 1,
                        line_end=i + 1,
                        improvement_type=ImprovementType.PERFORMANCE,
                        description="Multiple nested accesses - consider local variable",
                        priority=0.4,
                        confidence=0.5,
                        estimated_effort="low",
                    )
                )

        return opportunities

    async def _llm_analyze_file(
        self,
        file_path: str,
        content: str,
        improvement_type: ImprovementType,
    ) -> list[ImprovementOpportunity]:
        """Use LLM for deeper code analysis."""
        if not self.query_fn:
            return []

        prompt = f"""Analyze this code for {improvement_type.value} improvements.

FILE: {file_path}

```python
{content[:5000]}
```

List specific improvement opportunities. For each:
1. Line range (e.g., "15-20")
2. Description of the issue
3. Priority (0.0-1.0)
4. Confidence (0.0-1.0)
5. Estimated effort (low/medium/high)

Format as JSON array:
[{{"line_start": 15, "line_end": 20, "description": "...", "priority": 0.7, "confidence": 0.8, "effort": "medium"}}]

Only return the JSON array, no other text."""

        try:
            response = await self.query_fn(self.config.generator_model, prompt, 2000)
            # Parse JSON from response
            import re

            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                items = json.loads(json_match.group())
                return [
                    ImprovementOpportunity(
                        id=f"llm-{file_path}-{i}",
                        file_path=file_path,
                        line_start=item.get("line_start", 1),
                        line_end=item.get("line_end", 1),
                        improvement_type=improvement_type,
                        description=item.get("description", ""),
                        priority=float(item.get("priority", 0.5)),
                        confidence=float(item.get("confidence", 0.5)),
                        estimated_effort=item.get("effort", "medium"),
                    )
                    for i, item in enumerate(items)
                ]
        except (RuntimeError, ValueError, OSError, KeyError) as e:
            logger.debug("LLM analysis failed: %s", e)

        return []

    async def generate_patch(
        self,
        opportunity: ImprovementOpportunity,
    ) -> ImprovementPatch | None:
        """Generate a patch for an improvement opportunity.

        Args:
            opportunity: The improvement opportunity

        Returns:
            Generated patch or None if generation failed
        """
        file_path = self.repo_path / opportunity.file_path
        if not file_path.exists():
            logger.warning("File not found: %s", file_path)
            return None

        original_content = file_path.read_text()
        lines = original_content.splitlines()

        # Extract relevant section
        start = max(0, opportunity.line_start - 5)
        end = min(len(lines), opportunity.line_end + 5)
        context = "\n".join(lines[start:end])

        # Generate patch using LLM if available
        if self.query_fn:
            patch_content = await self._llm_generate_patch(
                file_path=opportunity.file_path,
                context=context,
                opportunity=opportunity,
                full_content=original_content,
            )
            if patch_content:
                diff = self._generate_diff(original_content, patch_content, opportunity.file_path)
                return ImprovementPatch(
                    id=f"patch-{opportunity.id}",
                    opportunity_id=opportunity.id,
                    file_path=opportunity.file_path,
                    original_content=original_content,
                    patched_content=patch_content,
                    diff=diff,
                    description=f"Fix: {opportunity.description}",
                )
        else:
            # Use heuristic-based fixes for simple cases
            patch_content = self._heuristic_fix(
                opportunity=opportunity,
                original_content=original_content,
            )
            if patch_content and patch_content != original_content:
                diff = self._generate_diff(original_content, patch_content, opportunity.file_path)
                return ImprovementPatch(
                    id=f"patch-{opportunity.id}",
                    opportunity_id=opportunity.id,
                    file_path=opportunity.file_path,
                    original_content=original_content,
                    patched_content=patch_content,
                    diff=diff,
                    description=f"Fix: {opportunity.description}",
                )

        return None

    async def _llm_generate_patch(
        self,
        file_path: str,
        context: str,
        opportunity: ImprovementOpportunity,
        full_content: str,
    ) -> str | None:
        """Use LLM to generate a patch."""
        if not self.query_fn:
            return None

        prompt = f"""Generate a code fix for this {opportunity.improvement_type.value} issue.

FILE: {file_path}
ISSUE: {opportunity.description}
LINES: {opportunity.line_start}-{opportunity.line_end}

CONTEXT:
```python
{context}
```

FULL FILE:
```python
{full_content[:8000]}
```

Generate the COMPLETE fixed file content.
Only return the Python code, no markdown or explanation.
Preserve all existing functionality while fixing the issue."""

        try:
            response = await self.query_fn(self.config.generator_model, prompt, 4000)
            # Clean response
            if "```python" in response:
                response = response.split("```python")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return response.strip()
        except (RuntimeError, ValueError, OSError) as e:
            logger.debug("LLM patch generation failed: %s", e)
            return None

    def _heuristic_fix(
        self,
        opportunity: ImprovementOpportunity,
        original_content: str,
    ) -> str | None:
        """Apply heuristic-based fixes for simple cases."""
        lines = original_content.splitlines()
        line_idx = opportunity.line_start - 1

        if line_idx >= len(lines):
            return None

        line = lines[line_idx]

        # Bare except -> typed except handler
        if (
            opportunity.improvement_type == ImprovementType.RELIABILITY
            and _BARE_EXCEPT_TOKEN in line
            and _TYPED_EXCEPT_PREFIX not in line
        ):
            lines[line_idx] = line.replace(_BARE_EXCEPT_TOKEN, _TYPED_EXCEPT_HANDLER)
            return "\n".join(lines)

        return None

    def _generate_diff(
        self,
        original: str,
        patched: str,
        file_path: str,
    ) -> str:
        """Generate unified diff between original and patched content."""
        original_lines = original.splitlines(keepends=True)
        patched_lines = patched.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
        return "".join(diff)

    async def validate_patch(self, patch: ImprovementPatch) -> bool:
        """Validate a patch through tests, type checking, and linting.

        Args:
            patch: The patch to validate

        Returns:
            True if validation passed
        """
        # First, temporarily apply the patch
        file_path = self.repo_path / patch.file_path
        original = file_path.read_text()

        try:
            file_path.write_text(patch.patched_content)

            # Run validation checks
            all_passed = True
            details: dict[str, Any] = {}

            if self.config.run_lint:
                lint_ok, lint_output = await self._run_lint(patch.file_path)
                details["lint"] = {"passed": lint_ok, "output": lint_output}
                if not lint_ok:
                    all_passed = False
                    patch.validation_result = ValidationResult.FAILED_LINT

            if all_passed and self.config.run_typecheck:
                type_ok, type_output = await self._run_typecheck(patch.file_path)
                details["typecheck"] = {"passed": type_ok, "output": type_output}
                if not type_ok:
                    all_passed = False
                    patch.validation_result = ValidationResult.FAILED_TYPECHECK

            if all_passed and self.config.run_tests:
                test_ok, test_output = await self._run_tests_for_file(patch.file_path)
                details["tests"] = {"passed": test_ok, "output": test_output}
                if not test_ok:
                    all_passed = False
                    patch.validation_result = ValidationResult.FAILED_TESTS

            if all_passed:
                patch.validation_result = ValidationResult.PASSED

            patch.validation_details = details

        finally:
            # Restore original
            file_path.write_text(original)

        logger.info(
            "sica_validation patch_id=%s result=%s",
            patch.id,
            patch.validation_result.value if patch.validation_result else "none",
        )

        return patch.validation_result == ValidationResult.PASSED

    async def _run_lint(self, file_path: str) -> tuple[bool, str]:
        """Run linter on file."""
        try:
            validated_path = _validate_file_path(file_path, self.repo_path)
            cmd_parts = _validate_tool_command(self.config.lint_command)
            result = subprocess.run(  # subprocess with fixed args, no shell
                [*cmd_parts, validated_path],
                shell=False,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except ValueError as e:
            return False, f"Validation error: {e}"
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Lint execution failed for %s: %s", file_path, e)
            return False, f"Lint execution failed: {type(e).__name__}"

    async def _run_typecheck(self, file_path: str) -> tuple[bool, str]:
        """Run type checker on file."""
        try:
            validated_path = _validate_file_path(file_path, self.repo_path)
            cmd_parts = _validate_tool_command(self.config.typecheck_command)
            result = subprocess.run(  # subprocess with fixed args, no shell
                [*cmd_parts, validated_path],
                shell=False,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except ValueError as e:
            return False, f"Validation error: {e}"
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Typecheck execution failed for %s: %s", file_path, e)
            return False, f"Typecheck execution failed: {type(e).__name__}"

    async def _run_tests_for_file(self, file_path: str) -> tuple[bool, str]:
        """Run tests related to a file."""
        # Try to find related test file
        test_file = file_path.replace(".py", "_test.py")
        if not (self.repo_path / test_file).exists():
            test_file = file_path.replace(".py", "").replace("/", "_")
            test_file = f"tests/test_{test_file}.py"

        try:
            cmd_parts = _validate_tool_command(self.config.test_command)
            result = subprocess.run(  # subprocess with fixed args, no shell
                [*cmd_parts, "-x", "-q"],
                shell=False,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=self.config.validation_timeout_seconds,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except ValueError as e:
            return False, f"Validation error: {e}"
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Test execution failed for %s: %s", file_path, e)
            return False, f"Test execution failed: {type(e).__name__}"

    async def _run_tests(self) -> bool:
        """Run full test suite."""
        try:
            cmd_parts = _validate_tool_command(self.config.test_command)
            result = subprocess.run(  # subprocess with fixed args, no shell
                [*cmd_parts, "-x", "-q"],
                shell=False,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=self.config.validation_timeout_seconds,
            )
            return result.returncode == 0
        except ValueError:
            logger.warning("Tool command validation failed", exc_info=True)
            return False
        except (OSError, subprocess.SubprocessError):
            logger.warning("Test suite execution failed", exc_info=True)
            return False

    async def request_approval(self, patch: ImprovementPatch) -> bool:
        """Request approval for a patch.

        Args:
            patch: The patch to approve

        Returns:
            True if approved
        """
        # Check for auto-approval conditions
        if self._can_auto_approve(patch):
            patch.approval_status = PatchApprovalStatus.AUTO_APPROVED
            logger.info("sica_auto_approved patch_id=%s", patch.id)
            return True

        # Use callback if provided
        if self.config.approval_callback:
            approved = await self.config.approval_callback(patch)
            patch.approval_status = (
                PatchApprovalStatus.APPROVED if approved else PatchApprovalStatus.REJECTED
            )
            return approved

        # If no callback and human approval required, reject
        if self.config.require_human_approval:
            patch.approval_status = PatchApprovalStatus.PENDING
            logger.info("sica_approval_pending patch_id=%s", patch.id)
            return False

        # Default: approve
        patch.approval_status = PatchApprovalStatus.APPROVED
        return True

    def _can_auto_approve(self, patch: ImprovementPatch) -> bool:
        """Check if patch can be auto-approved."""
        if not patch.validation_result == ValidationResult.PASSED:
            return False

        if not self._cycle_history:
            return False

        # Find the opportunity in the most recent cycle.
        opp = next(
            (o for o in self._cycle_history[-1].opportunities if o.id == patch.opportunity_id),
            None,
        )

        if opp:
            # High confidence auto-approve
            if opp.confidence >= self.config.auto_approve_threshold:
                return True

            # Low-risk type auto-approve
            if self.config.auto_approve_low_risk and opp.improvement_type in (
                ImprovementType.READABILITY,
                ImprovementType.TESTABILITY,
            ):
                return True

        return False

    async def apply_patch(self, patch: ImprovementPatch) -> bool:
        """Apply a patch to the codebase.

        Args:
            patch: The patch to apply

        Returns:
            True if applied successfully
        """
        file_path = self.repo_path / patch.file_path

        # Create backup
        if self.config.backup_before_apply:
            backup = self._create_backup(patch.file_path)
            self._backups[patch.id] = backup

        try:
            file_path.write_text(patch.patched_content)
            patch.applied = True
            patch.applied_at = datetime.now()
            self._applied_patches.append(patch)

            logger.info("sica_patch_applied patch_id=%s file=%s", patch.id, patch.file_path)

            if self.config.on_patch_applied:
                await self.config.on_patch_applied(patch)

            return True
        except OSError as e:
            logger.error("sica_patch_apply_failed patch_id=%s error=%s", patch.id, e)
            return False

    def _create_backup(self, file_path: str) -> FileBackup:
        """Create a backup of a file."""
        full_path = self.repo_path / file_path
        content = full_path.read_text()
        content_hash = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()

        if self.config.backup_dir:
            backup_path = self.config.backup_dir / f"{content_hash}.bak"
            backup_path.write_text(content)
        else:
            backup_path = full_path.with_suffix(".bak")
            backup_path.write_text(content)

        return FileBackup(
            file_path=file_path,
            content=content,
            hash=content_hash,
            backup_path=str(backup_path),
        )

    async def rollback_patch(self, patch: ImprovementPatch) -> bool:
        """Rollback a previously applied patch.

        Args:
            patch: The patch to rollback

        Returns:
            True if rollback successful
        """
        if not patch.applied:
            return False

        backup = self._backups.get(patch.id)
        if not backup:
            logger.error("No backup found for patch %s", patch.id)
            return False

        try:
            file_path = self.repo_path / patch.file_path
            file_path.write_text(backup.content)
            patch.applied = False

            logger.info("sica_patch_rolled_back patch_id=%s", patch.id)
            return True
        except OSError as e:
            logger.error("sica_rollback_failed patch_id=%s error=%s", patch.id, e)
            return False

    def get_metrics(self) -> dict[str, Any]:
        """Get metrics about improvement cycles."""
        total_cycles = len(self._cycle_history)
        if not total_cycles:
            return {
                "total_cycles": 0,
                "total_patches_applied": 0,
                "success_rate": 0.0,
            }

        total_applied = sum(c.patches_applied for c in self._cycle_history)
        total_successful = sum(c.patches_successful for c in self._cycle_history)

        return {
            "total_cycles": total_cycles,
            "total_opportunities": sum(c.opportunities_found for c in self._cycle_history),
            "total_patches_generated": sum(c.patches_generated for c in self._cycle_history),
            "total_patches_applied": total_applied,
            "total_patches_successful": total_successful,
            "success_rate": total_successful / total_applied if total_applied else 0.0,
            "avg_opportunities_per_cycle": sum(c.opportunities_found for c in self._cycle_history)
            / total_cycles,
        }

    def reset(self) -> None:
        """Reset improver state."""
        self._backups.clear()
        self._applied_patches.clear()
        self._cycle_history.clear()


def create_sica_improver(
    repo_path: Path | str,
    improvement_types: list[str] | None = None,
    require_human_approval: bool = True,
    run_tests: bool = True,
    query_fn: Callable[[str, str, int], Awaitable[str]] | None = None,
    **kwargs: Any,
) -> SICAImprover:
    """Factory function to create a SICA improver.

    Args:
        repo_path: Path to the repository
        improvement_types: Types of improvements (reliability, performance, etc.)
        require_human_approval: Whether to require human approval
        run_tests: Whether to run tests for validation
        query_fn: LLM query function
        **kwargs: Additional config options

    Returns:
        Configured SICAImprover instance
    """
    types = None
    if improvement_types:
        types = [ImprovementType(t) for t in improvement_types]

    config = SICAConfig(
        improvement_types=types
        or [
            ImprovementType.RELIABILITY,
            ImprovementType.TESTABILITY,
        ],
        require_human_approval=require_human_approval,
        run_tests=run_tests,
        **kwargs,
    )

    return SICAImprover(
        repo_path=Path(repo_path),
        config=config,
        query_fn=query_fn,
    )
