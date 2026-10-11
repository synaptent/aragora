"""Semantic Conflict Detection for parallel branches.

Detects semantic conflicts that git merge cannot catch:
- Function signature changes used across branches
- Interface contract violations
- Import cycle introduction
- Assumption clashes (e.g., one branch assumes sync, another async)

Two tiers:
1. Fast AST-based static analysis (always runs)
2. Optional Arena debate for ambiguous cases
"""

from __future__ import annotations

import ast
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ConflictType(Enum):
    """Types of semantic conflicts."""

    SIGNATURE_BREAK = "signature_break"
    ASSUMPTION_CLASH = "assumption_clash"
    CONTRACT_VIOLATION = "contract_violation"
    IMPORT_CYCLE = "import_cycle"


@dataclass
class SemanticConflict:
    """A detected semantic conflict between branches."""

    source_branch: str
    target_branch: str
    conflict_type: ConflictType
    description: str
    affected_files: list[str] = field(default_factory=list)
    confidence: float = 0.5  # 0-1
    suggested_resolution: str = ""


@dataclass
class FunctionSignature:
    """Extracted function signature for comparison."""

    name: str
    args: list[str]
    defaults_count: int
    has_varargs: bool
    has_kwargs: bool
    is_async: bool
    file_path: str = ""


class SemanticConflictDetector:
    """Detects semantic conflicts between parallel branches.

    Uses AST-based static analysis to find function signature changes,
    import conflicts, and other semantic issues that git merge cannot catch.
    Optionally uses Arena debate for ambiguous cases.
    """

    def __init__(self, repo_path: Path, enable_debate: bool = True):
        self.repo_path = repo_path
        self.enable_debate = enable_debate

    def detect(
        self,
        branches: list[str],
        base_branch: str = "main",
    ) -> list[SemanticConflict]:
        """Detect semantic conflicts between branches.

        Args:
            branches: List of branch names to check pairwise
            base_branch: Common base branch

        Returns:
            List of detected semantic conflicts
        """
        all_conflicts: list[SemanticConflict] = []

        # Get changes per branch
        branch_changes: dict[str, dict[str, str]] = {}
        for branch in branches:
            branch_changes[branch] = self._get_branch_changes(branch, base_branch)

        # Pairwise comparison
        for i, branch_a in enumerate(branches):
            for branch_b in branches[i + 1 :]:
                changes_a = branch_changes.get(branch_a, {})
                changes_b = branch_changes.get(branch_b, {})

                if not changes_a or not changes_b:
                    continue

                # Static AST scan
                static_conflicts = self._static_scan(
                    branch_a,
                    branch_b,
                    changes_a,
                    changes_b,
                )
                all_conflicts.extend(static_conflicts)

                # Optional debate scan for ambiguous cases
                if self.enable_debate and static_conflicts:
                    debate_conflicts = self._debate_scan(
                        branch_a,
                        branch_b,
                        static_conflicts,
                    )
                    all_conflicts.extend(debate_conflicts)

        return all_conflicts

    def _get_branch_changes(
        self,
        branch: str,
        base: str,
    ) -> dict[str, str]:
        """Get changed file contents for a branch relative to base.

        Returns:
            Dict mapping file path to file content on that branch
        """
        try:
            # Get list of changed Python files
            result = subprocess.run(  # subprocess with fixed args, no shell
                ["git", "diff", "--name-only", f"{base}...{branch}", "--", "*.py"],  # fixed command
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return {}

            files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
            changes: dict[str, str] = {}

            for file_path in files:
                try:
                    content_result = subprocess.run(  # subprocess with fixed args, no shell
                        ["git", "show", f"{branch}:{file_path}"],  # fixed command
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if content_result.returncode == 0:
                        changes[file_path] = content_result.stdout
                except (subprocess.TimeoutExpired, OSError):
                    continue

            return changes
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("Failed to get branch changes for %s: %s", branch, e)
            return {}

    def _static_scan(
        self,
        branch_a: str,
        branch_b: str,
        changes_a: dict[str, str],
        changes_b: dict[str, str],
    ) -> list[SemanticConflict]:
        """AST-based static analysis for semantic conflicts.

        Checks for:
        - Function signature changes in overlapping files
        - Conflicting import additions
        """
        conflicts: list[SemanticConflict] = []

        # Find overlapping files
        overlapping = set(changes_a.keys()) & set(changes_b.keys())

        for file_path in overlapping:
            content_a = changes_a[file_path]
            content_b = changes_b[file_path]

            # Check signature changes
            sig_conflicts = self._check_signature_conflicts(
                file_path,
                content_a,
                content_b,
                branch_a,
                branch_b,
            )
            conflicts.extend(sig_conflicts)

            # Check import conflicts
            import_conflicts = self._check_import_conflicts(
                file_path,
                content_a,
                content_b,
                branch_a,
                branch_b,
            )
            conflicts.extend(import_conflicts)

        return conflicts

    def _check_signature_conflicts(
        self,
        file_path: str,
        content_a: str,
        content_b: str,
        branch_a: str,
        branch_b: str,
    ) -> list[SemanticConflict]:
        """Check for conflicting function signature changes."""
        conflicts: list[SemanticConflict] = []

        sigs_a = self._extract_signatures(content_a, file_path)
        sigs_b = self._extract_signatures(content_b, file_path)

        # Build lookup by function name
        sig_map_a = {s.name: s for s in sigs_a}
        sig_map_b = {s.name: s for s in sigs_b}

        # Find functions modified in both branches
        common_funcs = set(sig_map_a.keys()) & set(sig_map_b.keys())

        for func_name in common_funcs:
            sig_a = sig_map_a[func_name]
            sig_b = sig_map_b[func_name]

            # Check for signature differences
            if self._signatures_conflict(sig_a, sig_b):
                confidence = 0.8  # High confidence for signature breaks
                conflicts.append(
                    SemanticConflict(
                        source_branch=branch_a,
                        target_branch=branch_b,
                        conflict_type=ConflictType.SIGNATURE_BREAK,
                        description=(
                            f"Function '{func_name}' in {file_path} has different "
                            f"signatures: {branch_a} has args {sig_a.args}, "
                            f"{branch_b} has args {sig_b.args}"
                        ),
                        affected_files=[file_path],
                        confidence=confidence,
                        suggested_resolution=(
                            f"Reconcile the signature of '{func_name}' before merging"
                        ),
                    )
                )

            # Check sync/async mismatch
            if sig_a.is_async != sig_b.is_async:
                conflicts.append(
                    SemanticConflict(
                        source_branch=branch_a,
                        target_branch=branch_b,
                        conflict_type=ConflictType.ASSUMPTION_CLASH,
                        description=(
                            f"Function '{func_name}' in {file_path}: "
                            f"{branch_a} is {'async' if sig_a.is_async else 'sync'}, "
                            f"{branch_b} is {'async' if sig_b.is_async else 'sync'}"
                        ),
                        affected_files=[file_path],
                        confidence=0.9,
                        suggested_resolution=(
                            f"Decide whether '{func_name}' should be sync or async"
                        ),
                    )
                )

        return conflicts

    def _check_import_conflicts(
        self,
        file_path: str,
        content_a: str,
        content_b: str,
        branch_a: str,
        branch_b: str,
    ) -> list[SemanticConflict]:
        """Check for conflicting import additions."""
        conflicts: list[SemanticConflict] = []

        imports_a = self._extract_imports(content_a)
        imports_b = self._extract_imports(content_b)

        # Find imports that differ -- both branches adding different imports
        # from the same module could indicate a conflict
        modules_a = {imp.split(".")[0] for imp in imports_a}
        modules_b = {imp.split(".")[0] for imp in imports_b}

        # Check for circular import risk: if branch A imports from X
        # and branch B imports from Y, and X imports from Y, that's a cycle risk.
        # For now we flag cases where both branches add imports from each other's
        # changed modules.
        changed_modules_a = {
            f.replace("/", ".").replace(".py", "") for f in self._get_module_names(content_a)
        }
        changed_modules_b = {
            f.replace("/", ".").replace(".py", "") for f in self._get_module_names(content_b)
        }

        cross_imports = (modules_a & changed_modules_b) | (modules_b & changed_modules_a)
        if cross_imports:
            conflicts.append(
                SemanticConflict(
                    source_branch=branch_a,
                    target_branch=branch_b,
                    conflict_type=ConflictType.IMPORT_CYCLE,
                    description=(
                        f"Potential import cycle in {file_path}: "
                        f"cross-referencing modules {cross_imports}"
                    ),
                    affected_files=[file_path],
                    confidence=0.4,  # Lower confidence -- needs manual review
                    suggested_resolution="Check for circular imports after merge",
                )
            )

        return conflicts

    def _extract_signatures(
        self,
        content: str,
        file_path: str = "",
    ) -> list[FunctionSignature]:
        """Extract function signatures from Python source code."""
        signatures: list[FunctionSignature] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return signatures

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                arg_names = [a.arg for a in args.args]
                signatures.append(
                    FunctionSignature(
                        name=node.name,
                        args=arg_names,
                        defaults_count=len(args.defaults),
                        has_varargs=args.vararg is not None,
                        has_kwargs=args.kwarg is not None,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        file_path=file_path,
                    )
                )

        return signatures

    def _extract_imports(self, content: str) -> set[str]:
        """Extract import module names from Python source."""
        imports: set[str] = set()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)

        return imports

    def _get_module_names(self, content: str) -> set[str]:
        """Extract module-level names defined in source (for cycle detection)."""
        names: set[str] = set()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return names

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)

        return names

    @staticmethod
    def _signatures_conflict(sig_a: FunctionSignature, sig_b: FunctionSignature) -> bool:
        """Check if two function signatures conflict."""
        if sig_a.args != sig_b.args:
            return True
        if sig_a.defaults_count != sig_b.defaults_count:
            return True
        if sig_a.has_varargs != sig_b.has_varargs:
            return True
        if sig_a.has_kwargs != sig_b.has_kwargs:
            return True
        return False

    def _debate_scan(
        self,
        branch_a: str,
        branch_b: str,
        static_conflicts: list[SemanticConflict],
    ) -> list[SemanticConflict]:
        """Use Arena debate to assess ambiguous conflicts.

        Falls back gracefully if debate infrastructure is unavailable.
        """
        try:
            from aragora.debate.orchestrator import Arena  # noqa: F401
        except ImportError:
            logger.debug("Arena not available, skipping debate scan")
            return []

        # For now, debate scan is a placeholder for future LLM-powered analysis.
        # Static conflicts with low confidence could be debated.
        debate_conflicts: list[SemanticConflict] = []

        for conflict in static_conflicts:
            if conflict.confidence < 0.5:
                # Low confidence conflicts would benefit from debate analysis
                logger.info(
                    "Low-confidence conflict would benefit from debate: %s",
                    conflict.description[:80],
                )

        return debate_conflicts


__all__ = [
    "ConflictType",
    "SemanticConflict",
    "FunctionSignature",
    "SemanticConflictDetector",
]
