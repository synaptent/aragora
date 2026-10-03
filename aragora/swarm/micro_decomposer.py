"""Micro-task decomposition for worker-friendly issue dispatch.

Claude Code workers in large repos (3000+ modules) succeed on small, focused
tasks but fail on broad ones — they spend all their time reading instead of
writing. This module decomposes broad issues into single-file, single-commit
micro-tasks with explicit instructions.

The key insight: workers need to know EXACTLY what file to edit, EXACTLY what
to change, and EXACTLY what test to run. Vague "analyze and implement" tasks
cause 60-minute timeouts with zero output.

Usage in boss_loop._dispatch_issue():
    spec.work_orders = build_micro_work_orders(
        goal=goal,
        file_scope_hints=scope_hints,
        acceptance_criteria=spec.acceptance_criteria,
        repo_root=Path.cwd(),
    )
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_micro_work_orders(
    *,
    goal: str,
    file_scope_hints: list[str],
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, str | list[str] | dict[str, list[str]]]]:
    """Decompose a goal into single-file micro work orders.

    Strategy:
    1. If file_scope_hints contains specific files (with extensions),
       create one work order per file.
    2. If file_scope_hints contains directories, scan for relevant files
       and create one work order per file.
    3. Each work order gets an explicit, focused description that tells
       the worker exactly what to do in that file.
    4. A final work order runs the acceptance test.

    Returns empty list if decomposition isn't possible (caller falls back
    to normal decomposition).
    """
    root = repo_root or Path.cwd()
    if not file_scope_hints:
        return []

    # Resolve file hints to actual files
    resolved_files = _resolve_file_hints(file_scope_hints, root)
    if not resolved_files:
        return []

    # Separate implementation files from test files
    impl_files = [f for f in resolved_files if not _is_test_file(f)]
    test_files = [f for f in resolved_files if _is_test_file(f)]

    if not impl_files and not test_files:
        return []

    work_orders: list[dict] = []
    order_idx = 0
    requires_test_only = _requires_test_only_resolution(
        goal=goal,
        acceptance_criteria=acceptance_criteria,
    )
    prefers_test_first = _prefers_test_first_resolution(
        goal=goal,
        acceptance_criteria=acceptance_criteria,
        impl_files=impl_files,
        test_files=test_files,
    )

    # Some issues explicitly prefer a test-only confirmation step before any
    # implementation work. In that case, skip the implementation-only lanes and
    # let the final validation lane touch implementation files only if the new
    # tests prove it is actually necessary.
    if prefers_test_first and test_files:
        order_idx += 1
        test_wo = _build_test_work_order(
            index=order_idx,
            test_files=test_files,
            goal=goal,
            impl_files=impl_files,
            root=root,
        )
        work_orders.append(test_wo)
    else:
        # Create one work order per implementation file
        for filepath in impl_files[:5]:  # Cap at 5 files to avoid sprawl
            order_idx += 1
            wo = _build_file_work_order(
                index=order_idx,
                filepath=filepath,
                goal=goal,
                constraints=constraints,
                root=root,
            )
            work_orders.append(wo)

        # Create one work order for test files (grouped)
        if test_files:
            order_idx += 1
            test_wo = _build_test_work_order(
                index=order_idx,
                test_files=test_files,
                goal=goal,
                impl_files=impl_files,
                root=root,
            )
            work_orders.append(test_wo)

    # Final validation work order
    if acceptance_criteria:
        order_idx += 1
        validation_wo = _build_validation_work_order(
            index=order_idx,
            acceptance_criteria=acceptance_criteria,
            file_scope=test_files if requires_test_only and test_files else file_scope_hints,
            dependency_ids=[wo["pipeline_task_id"] for wo in work_orders],
        )
        work_orders.append(validation_wo)
        for work_order in work_orders[:-1]:
            metadata = dict(work_order.get("metadata") or {})
            metadata["deferred_verification_to_dependency_ids"] = [
                str(validation_wo["pipeline_task_id"])
            ]
            work_order["metadata"] = metadata

    if work_orders:
        logger.info(
            "Micro-decomposed into %d work orders for %d files",
            len(work_orders),
            len(resolved_files),
        )

    return work_orders


def _prefers_test_first_resolution(
    *,
    goal: str,
    acceptance_criteria: list[str] | None,
    impl_files: list[str],
    test_files: list[str],
) -> bool:
    """Detect issues that should start with tests, not implementation.

    This targets narrow cases like:
    - "Prefer a test-only fix if X already works"
    - implementation files included only conditionally ("only if current ...")

    For these, emitting an implementation-only lane first creates wasted churn.
    A test lane plus a final validation/fix lane is a better bounded sequence.
    """
    if not acceptance_criteria or not impl_files or not test_files:
        return False

    lowered = _normalized_resolution_text(
        goal=goal,
        acceptance_criteria=acceptance_criteria,
    )
    prefers_test_only = _requires_test_only_resolution(
        goal=goal,
        acceptance_criteria=acceptance_criteria,
    ) or any(
        marker in lowered
        for marker in (
            "prefer a test-only fix",
            "prefer a test only fix",
            "only create/modify test files",
            "only create or modify test files",
        )
    )
    conditional_impl = any(
        marker in lowered
        for marker in (
            "only if current",
            "only if the current",
            "only if parser",
            "if the current parser already",
            "if the current",
            "if current",
        )
    )
    test_led_acceptance = all(
        any(token in item.lower() for token in ("pytest", "test", "tests/"))
        for item in acceptance_criteria
    )
    return prefers_test_only or (conditional_impl and test_led_acceptance)


def _normalized_resolution_text(
    *,
    goal: str,
    acceptance_criteria: list[str] | None,
) -> str:
    return " ".join(
        part.strip().lower()
        for part in [goal, *(acceptance_criteria or [])]
        if part and part.strip()
    )


def _requires_test_only_resolution(
    *,
    goal: str,
    acceptance_criteria: list[str] | None,
) -> bool:
    """Return true when the issue explicitly forbids implementation edits."""
    lowered = _normalized_resolution_text(
        goal=goal,
        acceptance_criteria=acceptance_criteria,
    )
    return any(
        marker in lowered
        for marker in (
            "only create/modify test files",
            "only create or modify test files",
            "no modifications to the source module",
            "no modifications to source module",
            "no source modifications",
            "do not modify the source module",
            "do not modify source files",
        )
    )


def _resolve_file_hints(hints: list[str], root: Path) -> list[str]:
    """Resolve existing scope hints and explicit create targets."""
    resolved: list[str] = []
    for hint in hints:
        hint = hint.strip().removeprefix("./")
        if not hint:
            continue
        path = root / hint
        if path.is_file():
            resolved.append(hint)
        elif path.is_dir():
            # Scan directory for Python files (limit to avoid explosion)
            for py_file in sorted(path.rglob("*.py"))[:20]:
                rel = str(py_file.relative_to(root))
                if "__pycache__" not in rel and not rel.endswith("__init__.py"):
                    resolved.append(rel)
        elif _is_creatable_file_hint(hint, root):
            resolved.append(hint)
    return resolved[:15]  # Hard cap


def _is_creatable_file_hint(hint: str, root: Path) -> bool:
    """Accept a missing test file only when its existing parent bounds it."""
    relative = Path(hint)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.suffix
        or not _is_test_file(hint)
    ):
        return False
    return (root / relative).parent.is_dir()


def _is_test_file(filepath: str) -> bool:
    """Check if a file is a test file."""
    name = filepath.rsplit("/", 1)[-1]
    return name.startswith("test_") or "/tests/" in filepath or "/test_" in filepath


def _build_file_work_order(
    *,
    index: int,
    filepath: str,
    goal: str,
    constraints: list[str] | None,
    root: Path,
) -> dict:
    """Build a focused work order for a single implementation file."""
    # Read the file to understand its structure (first 50 lines)
    file_preview = ""
    try:
        full_path = root / filepath
        if full_path.exists():
            lines = full_path.read_text(errors="replace").splitlines()[:50]
            file_preview = "\n".join(lines)
    except OSError:
        pass

    filename = filepath.rsplit("/", 1)[-1]
    file_exists = (root / filepath).exists()

    if file_exists:
        description = (
            f"Edit `{filepath}` to contribute to: {goal[:200]}\n\n"
            f"Focus on what this specific file (`{filename}`) needs for the goal above.\n"
            f"Do NOT rewrite the entire file. Make the minimal targeted edit.\n\n"
        )
    else:
        description = (
            f"Create `{filepath}` as part of: {goal[:200]}\n\n"
            f"Write a focused, minimal implementation for `{filename}`.\n\n"
        )

    description += (
        f"CRITICAL WORKFLOW:\n"
        f"1. Read `{filepath}` (if it exists)\n"
        f"2. Make your change (keep it small and focused)\n"
        f"3. IMMEDIATELY commit: `git add {filepath} && "
        f"git commit -m 'fix: update {filename}'`\n"
        f"4. Do NOT explore other files. Do NOT run tests. Just commit.\n"
    )
    if file_preview:
        # Only show first 30 lines to keep prompt short
        short_preview = "\n".join(file_preview.splitlines()[:30])
        description += f"\nFile preview:\n```python\n{short_preview}\n```\n"

    constraint_list = list(constraints or [])
    constraint_list.append(f"Only modify {filepath}")
    constraint_list.append("Commit immediately after making changes")

    return {
        "work_order_id": f"micro-{index}",
        "pipeline_task_id": f"micro-task-{index}",
        "title": f"Update {filepath.rsplit('/', 1)[-1]}",
        "description": description,
        "file_scope": [filepath],
        "target_agent": "claude",
        "estimated_complexity": "low",
        "approval_required": True,
        "metadata": {
            "source": "micro_decomposer",
            "constraints": constraint_list,
        },
    }


def _build_test_work_order(
    *,
    index: int,
    test_files: list[str],
    goal: str,
    impl_files: list[str],
    root: Path,
) -> dict:
    """Build a work order for creating/updating test files."""
    impl_names = ", ".join(f"`{f}`" for f in impl_files[:3])
    test_names = ", ".join(f"`{f}`" for f in test_files[:3])

    description = (
        f"Write or update tests in {test_names} for the changes made to {impl_names}.\n\n"
        f"Goal: {goal}\n\n"
        f"IMPORTANT: Only create/modify test files. Do not modify implementation files.\n"
        f"After writing tests, run:\n"
        f"  git add {' '.join(test_files[:3])}\n"
        f"  git commit -m 'test: add tests for {impl_files[0].rsplit('/', 1)[-1] if impl_files else 'changes'}'\n"
    )

    return {
        "work_order_id": f"micro-{index}",
        "pipeline_task_id": f"micro-task-{index}",
        "title": f"Write tests for {impl_files[0].rsplit('/', 1)[-1] if impl_files else 'changes'}",
        "description": description,
        "file_scope": test_files[:5],
        "target_agent": "claude",
        "estimated_complexity": "low",
        "approval_required": True,
        "dependency_ids": [f"micro-task-{i}" for i in range(1, index)],
        "metadata": {"source": "micro_decomposer"},
    }


def _build_validation_work_order(
    *,
    index: int,
    acceptance_criteria: list[str],
    file_scope: list[str],
    dependency_ids: list[str],
) -> dict:
    """Build a validation-only work order that runs acceptance tests."""
    criteria_text = "\n".join(f"  - {c}" for c in acceptance_criteria)

    return {
        "work_order_id": f"micro-{index}",
        "pipeline_task_id": f"micro-task-{index}",
        "title": "Run validation and fix failures",
        "description": (
            f"Run the following acceptance tests and fix any failures:\n\n"
            f"{criteria_text}\n\n"
            f"If tests fail, fix the issues and commit the fixes.\n"
            f"If tests pass, commit a no-op marker:\n"
            f"  git commit --allow-empty -m 'test: validation passed'\n"
        ),
        "file_scope": file_scope,
        "target_agent": "claude",
        "estimated_complexity": "low",
        "approval_required": True,
        "dependency_ids": dependency_ids,
        "metadata": {"source": "micro_decomposer"},
    }
