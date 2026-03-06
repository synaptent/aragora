"""ImplementationSpecExtractor -- debate result to implementation spec.

Extracts a focused implementation specification from a DebateResult's
natural-language final_answer. Uses simple string parsing (regex for
file paths, keyword extraction) -- NOT an LLM call. This is a best-effort
extraction; the harness handles ambiguity.

Usage:
    from aragora.pipeline.spec_extractor import extract_implementation_spec

    spec = extract_implementation_spec(debate_result)
    # spec.implementation_prompt, spec.files_to_modify, spec.rollback_plan
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImplementationSpec:
    """Focused implementation instructions extracted from a debate result."""

    implementation_prompt: str
    files_to_modify: list[str] = field(default_factory=list)
    rollback_plan: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation_prompt": self.implementation_prompt,
            "files_to_modify": self.files_to_modify,
            "rollback_plan": self.rollback_plan,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImplementationSpec:
        return cls(
            implementation_prompt=str(data.get("implementation_prompt", "")),
            files_to_modify=list(data.get("files_to_modify", [])),
            rollback_plan=str(data.get("rollback_plan", "")),
        )


# Patterns for extracting file paths from natural language
_FILE_PATH_PATTERNS = [
    # Backtick-quoted paths: `aragora/foo/bar.py`
    re.compile(r"`([a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+)`"),
    # Quoted paths: "aragora/foo/bar.py" or 'aragora/foo/bar.py'
    re.compile(r"""['"]([a-zA-Z0-9_./\-]+\.[a-zA-Z0-9]+)['"]"""),
    # Bare paths that look like code files (word boundary, slash-separated, common extensions)
    re.compile(r"\b([a-zA-Z0-9_]+(?:/[a-zA-Z0-9_]+)*\.[a-z]{1,4})\b"),
]

# Extensions that indicate code files
_CODE_EXTENSIONS = frozenset(
    {
        "py",
        "ts",
        "tsx",
        "js",
        "jsx",
        "rs",
        "go",
        "java",
        "rb",
        "cpp",
        "c",
        "h",
        "hpp",
        "cs",
        "swift",
        "kt",
        "scala",
        "sql",
        "yaml",
        "yml",
        "json",
        "toml",
        "cfg",
        "ini",
        "md",
        "txt",
        "sh",
        "bash",
    }
)

# Keywords that signal rollback/safety instructions
_ROLLBACK_KEYWORDS = frozenset(
    {
        "rollback",
        "revert",
        "undo",
        "backup",
        "restore",
        "fallback",
        "if fail",
        "on failure",
        "safety",
        "risk",
    }
)

# Keywords that signal actionable implementation instructions
_ACTION_KEYWORDS = frozenset(
    {
        "implement",
        "create",
        "add",
        "modify",
        "update",
        "refactor",
        "fix",
        "change",
        "write",
        "build",
        "configure",
        "set up",
        "integrate",
        "install",
        "remove",
        "delete",
        "replace",
        "move",
        "rename",
        "extract",
        "split",
        "merge",
        "wrap",
        "extend",
    }
)


def extract_implementation_spec(debate_result: Any) -> ImplementationSpec:
    """Extract a focused implementation spec from a debate result.

    Args:
        debate_result: A DebateResult (or duck-typed equivalent) with
            ``final_answer`` and ``task`` attributes.

    Returns:
        ImplementationSpec with extracted prompt, files, and rollback plan.
    """
    final_answer = str(getattr(debate_result, "final_answer", "") or "")
    task = str(getattr(debate_result, "task", "") or "")

    # Extract file paths
    files = _extract_file_paths(final_answer)

    # Extract rollback plan
    rollback_plan = _extract_rollback_plan(final_answer)

    # Build implementation prompt
    implementation_prompt = _build_implementation_prompt(final_answer, task)

    return ImplementationSpec(
        implementation_prompt=implementation_prompt,
        files_to_modify=files,
        rollback_plan=rollback_plan,
    )


def _extract_file_paths(text: str) -> list[str]:
    """Extract file paths from natural language text.

    Deduplicates while preserving order. Only includes paths with
    recognized code-file extensions.
    """
    seen: set[str] = set()
    paths: list[str] = []

    for pattern in _FILE_PATH_PATTERNS:
        for match in pattern.finditer(text):
            path = match.group(1).strip()
            # Validate extension
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext not in _CODE_EXTENSIONS:
                continue
            if path not in seen:
                seen.add(path)
                paths.append(path)

    return paths


def _extract_rollback_plan(text: str) -> str:
    """Extract rollback/safety instructions from the final answer.

    Scans for lines containing rollback keywords and collects them
    into a single rollback plan string.
    """
    rollback_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(keyword in lower for keyword in _ROLLBACK_KEYWORDS):
            rollback_lines.append(stripped)

    if rollback_lines:
        return " ".join(rollback_lines)
    return (
        "No explicit rollback plan found. Ensure changes are committed on a branch for easy revert."
    )


def _build_implementation_prompt(final_answer: str, task: str) -> str:
    """Build a focused implementation prompt from the debate output.

    Extracts actionable lines from the final answer and combines them
    with the original task for context.
    """
    if not final_answer.strip():
        return (
            f"Implement the following: {task}"
            if task
            else "No implementation instructions available."
        )

    # Extract actionable lines (numbered steps, bullets with action verbs)
    actionable: list[str] = []
    for line in final_answer.split("\n"):
        stripped = line.strip()
        if not stripped or len(stripped) < 10:
            continue

        lower = stripped.lower()

        # Skip rollback/safety lines (already captured separately)
        if any(keyword in lower for keyword in _ROLLBACK_KEYWORDS):
            continue

        # Include numbered items, bullets, or lines with action keywords
        is_list_item = (
            stripped[0].isdigit()
            or stripped.startswith("-")
            or stripped.startswith("*")
            or stripped.startswith("+")
        )
        has_action = any(keyword in lower for keyword in _ACTION_KEYWORDS)

        if is_list_item or has_action:
            actionable.append(stripped)

    if actionable:
        steps = "\n".join(actionable)
        prompt = f"Task: {task}\n\nImplementation steps:\n{steps}"
    else:
        # Fall back to the full final answer
        prompt = f"Task: {task}\n\nDebate conclusion:\n{final_answer.strip()}"

    return prompt
