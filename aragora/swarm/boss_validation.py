"""Issue body parsing, validation contract extraction, and pre-dispatch checks.

Provides utilities for sanitizing GitHub issue bodies for worker dispatch,
extracting explicit validation contracts (acceptance criteria, test commands),
running pre-dispatch validation commands, and discovering focused test files.

When a configured fast agent provider is available, semantic parsing uses an
LLM to extract structured data from the issue body.  This avoids the
brittleness of regex-only parsing.  On any LLM failure the module falls back
to the original regex pipeline transparently.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from aragora.swarm.mission import GateEvaluation, GateType, GateVerdict
from aragora.agents.semantic_extraction import ExtractionProvider, extract_json_object_llm_first

logger = logging.getLogger(__name__)


_VALIDATION_SECTION_PREFIXES = (
    "acceptance criteria",
    "acceptance",
    "test",
    "validation",
    "validation contract",
    "definition of done",
    "done when",
    "test plan",
)
_ISSUE_SECTION_PREFIXES = (
    "summary",
    "context",
    "background",
    "acceptance criteria",
    "acceptance",
    "test",
    "validation",
    "validation contract",
    "definition of done",
    "done when",
    "test plan",
    "scope hints",
    "file scope hints",
    "file scope",
    "implementation rules",
    "constraints",
)
_DISPATCH_CONTEXT_SECTION_PREFIXES = ("summary", "context", "background")
_VALIDATION_INLINE_PREFIXES = (
    "acceptance",
    "acceptance criteria",
    "test",
    "validation",
    "validation contract",
    "definition of done",
    "done when",
    "test plan",
)
_VALIDATION_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s*(?:\[(?: |x|X)\]\s*)?(?P<text>.+?)\s*$")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(?P<text>.+?)\*\*")
_PRE_DISPATCH_SAFE_COMMAND_PREFIXES = (
    "pytest ",
    "python -m pytest",
    "python3 -m pytest",
    "uv run pytest",
    "uv run python -m pytest",
    "aragora ",
    "python -m aragora",
    "python3 -m aragora",
)
_BACKTICK_COMMAND_RE = re.compile(r"`(?P<command>[^`]+)`")
_EXPLICIT_PYTEST_TARGET_RE = re.compile(r"(?<!\S)(?P<path>tests/\S+?\.py)(?:::\S+)?(?!\S)")
_DECLARED_NEW_FILE_RE = re.compile(
    r"\(\s*(?:new(?:\s+file)?|create|to\s+be\s+created|will\s+create|generated)\s*\)",
    re.IGNORECASE,
)
_BACKTICK_PATH_RE = re.compile(r"`(?P<path>[^`\n]+/[^`\n]+)`")
_TASK_HEADER_RE = re.compile(r"^#{1,6}\s*task\b", re.IGNORECASE)
_AUTO_DECOMPOSED_RE = re.compile(r"auto-decomposed|auto decomposed", re.IGNORECASE)


def _run_subprocess(
    args: list[str],
    *,
    cwd: str,
    timeout: int,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Thin wrapper around :func:`subprocess.run` for test seam injection.

    Tests can patch ``boss_validation._run_subprocess`` to avoid real process
    spawning while exercising all surrounding logic.
    """
    return subprocess.run(
        args,
        cwd=cwd,
        text=text,
        capture_output=capture_output,
        timeout=timeout,
        check=check,
    )


def _ordered_unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_validation_line(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    # GitHub issues commonly use bold inline markers like "**Acceptance:** ..."
    normalized = _MARKDOWN_BOLD_RE.sub(lambda match: match.group("text"), normalized)
    return normalized.strip()


def _match_issue_section_prefix(normalized_lower: str) -> str | None:
    for prefix in _ISSUE_SECTION_PREFIXES:
        if normalized_lower == prefix or normalized_lower.startswith(f"{prefix} "):
            return prefix
    return None


def _normalize_dispatch_text(lines: list[str]) -> str:
    normalized: list[str] = []
    previous_blank = True
    for raw in lines:
        text = str(raw).rstrip()
        if text.strip():
            normalized.append(text)
            previous_blank = False
            continue
        if previous_blank:
            continue
        normalized.append("")
        previous_blank = True
    return "\n".join(normalized).strip()


def _extract_task_block(lines: list[str]) -> list[str]:
    if not lines:
        return []
    start_idx: int | None = None
    for idx, raw in enumerate(lines):
        if _TASK_HEADER_RE.match(str(raw).strip()):
            start_idx = idx + 1
            break
    if start_idx is None:
        return []
    collected: list[str] = []
    for raw in lines[start_idx:]:
        stripped = str(raw).strip()
        if stripped.startswith("#"):
            break
        if stripped:
            collected.append(str(raw).rstrip())
    return collected


def assess_issue_body_sanitation(issue_body: str) -> tuple[bool, str | None]:
    body = str(issue_body or "").strip()
    if not body:
        return False, "empty_body"

    lines = [str(line).rstrip() for line in body.splitlines()]
    task_lines = _extract_task_block(lines)
    task_text = " ".join(line.strip() for line in task_lines if line.strip()).strip()

    if _AUTO_DECOMPOSED_RE.search(body) and not task_text:
        return False, "auto_decomposed_missing_task"

    if task_text and len(task_text) < 40:
        return False, "task_too_short"

    if any(line.rstrip().endswith("\\") for line in task_lines):
        return False, "task_truncated"

    return True, None


def sanitize_issue_body_for_dispatch(issue_body: str) -> str:
    """Keep contextual issue text while dropping sections modeled elsewhere."""
    lines = [str(line).rstrip() for line in str(issue_body or "").splitlines()]
    kept: list[str] = []
    active_section: str | None = None

    for raw_line in lines:
        stripped = raw_line.strip()
        normalized = _normalize_validation_line(stripped.lstrip("#").strip())
        normalized_lower = normalized.rstrip(":").strip().lower()
        section_prefix = _match_issue_section_prefix(normalized_lower)

        if section_prefix is not None:
            active_section = section_prefix
            if section_prefix in _DISPATCH_CONTEXT_SECTION_PREFIXES:
                if kept and kept[-1].strip():
                    kept.append("")
                kept.append(normalized.rstrip(":").strip())
            continue

        if stripped.startswith("#"):
            active_section = None

        if active_section and active_section not in _DISPATCH_CONTEXT_SECTION_PREFIXES:
            continue
        kept.append(raw_line.rstrip())

    return _normalize_dispatch_text(kept)


def _compose_issue_dispatch_goal(
    issue_number: int,
    issue_title: str,
    *,
    issue_body: str = "",
    refined_prompt: str = "",
) -> str:
    header = f"[Issue #{issue_number}] {issue_title}".strip()
    body = str(refined_prompt or "").strip() or sanitize_issue_body_for_dispatch(issue_body)
    if body.startswith(header):
        body = body[len(header) :].strip()
    if body:
        return f"{header}\n\n{body}"
    return header


def extract_issue_validation_contract(issue_body: str) -> list[str]:
    """Extract an explicit validation contract from a GitHub issue body.

    Supported forms:
    - bullets/checklists under headings such as "Acceptance Criteria" or "Validation"
    - inline markers such as "Validation: pytest -q ..."
    - standalone pytest commands anywhere in the issue body
    """
    lines = [str(line).rstrip() for line in str(issue_body or "").splitlines()]
    criteria: list[str] = []
    in_validation_section = False

    for raw_line in lines:
        stripped = raw_line.strip()
        normalized = _normalize_validation_line(stripped.lstrip("#").strip())
        normalized_lower = normalized.rstrip(":").strip().lower()

        inline_prefix, _, inline_value = normalized.partition(":")
        if inline_value and inline_prefix.strip().lower() in _VALIDATION_INLINE_PREFIXES:
            criteria.append(inline_value.strip())
            in_validation_section = False
            continue

        section_prefix = _match_issue_section_prefix(normalized_lower)
        if section_prefix is not None:
            in_validation_section = section_prefix in _VALIDATION_SECTION_PREFIXES
            continue

        if stripped.startswith("pytest ") or stripped.startswith("python -m pytest"):
            criteria.append(stripped)
            continue

        if not in_validation_section:
            continue

        if stripped.startswith("#"):
            in_validation_section = False
            continue

        bullet_match = _VALIDATION_BULLET_RE.match(stripped)
        if bullet_match:
            criteria.append(bullet_match.group("text"))
            continue

        if not stripped:
            continue

        if normalized.endswith(":"):
            in_validation_section = False
            continue

        criteria.append(stripped)

    return _ordered_unique_strings(criteria)


def _normalize_pre_dispatch_command(text: str) -> str:
    normalized = str(text).strip()
    if not normalized:
        return ""
    backtick_match = _BACKTICK_COMMAND_RE.search(normalized)
    if backtick_match:
        normalized = backtick_match.group("command").strip()
    if normalized.endswith(" passes."):
        normalized = normalized[: -len(" passes.")].strip()
    if normalized.startswith("aragora "):
        normalized = f"python3 -m aragora.cli.main {normalized[len('aragora ') :].strip()}"
    return normalized


def extract_pre_dispatch_validation_commands(issue_body: str) -> list[str]:
    """Return explicit validation commands that are safe to probe before dispatch."""
    commands: list[str] = []
    for item in extract_issue_validation_contract(issue_body):
        normalized = _normalize_pre_dispatch_command(item)
        if not normalized:
            continue
        if any(normalized.startswith(prefix) for prefix in _PRE_DISPATCH_SAFE_COMMAND_PREFIXES):
            commands.append(normalized)
    return _ordered_unique_strings(commands)


def find_missing_pre_dispatch_validation_targets(
    commands: list[str],
    *,
    repo_root: Path,
) -> list[str]:
    """Return explicit pytest file targets that do not exist on disk.

    This is intentionally narrower than executing the command: a failing test is
    a legitimate bug-fix lane, but a missing pytest target is usually a stale
    issue contract that should stop before dispatch.
    """

    missing: list[str] = []
    for command in commands:
        normalized = _normalize_pre_dispatch_command(command)
        lowered = normalized.lower()
        if not (
            lowered.startswith("pytest ")
            or lowered.startswith("python -m pytest ")
            or lowered.startswith("python3 -m pytest ")
            or lowered.startswith("uv run pytest ")
            or lowered.startswith("uv run python -m pytest ")
        ):
            continue
        for match in _EXPLICIT_PYTEST_TARGET_RE.finditer(normalized):
            path = match.group("path").strip()
            if path and not (repo_root / path).exists():
                missing.append(path)
    return _ordered_unique_strings(missing)


def extract_declared_new_file_paths(issue_body: str) -> list[str]:
    """Return file paths explicitly marked as new in the issue body.

    This keeps the missing-target gate strict for stale contracts while
    allowing lanes whose acceptance criteria intentionally point at a file the
    worker is expected to create.
    """

    declared: list[str] = []
    for raw_line in str(issue_body or "").splitlines():
        line = str(raw_line).strip()
        if not line or not _DECLARED_NEW_FILE_RE.search(line):
            continue
        for match in _BACKTICK_PATH_RE.finditer(line):
            path = str(match.group("path") or "").strip()
            if path:
                declared.append(path)
    return _ordered_unique_strings(declared)


def run_pre_dispatch_validation_commands(
    commands: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Execute bounded validation commands locally before spawning a worker lane."""
    results: list[dict[str, Any]] = []
    timeout = max(1, int(timeout_seconds))
    for command in commands:
        try:
            proc = _run_subprocess(
                ["/bin/bash", "-lc", command],
                cwd=str(cwd),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "command": command,
                    "status": "timeout",
                }
            )
            return {"satisfied": False, "results": results}
        except (FileNotFoundError, OSError) as exc:
            results.append(
                {
                    "command": command,
                    "status": "error",
                    "detail": str(exc),
                }
            )
            return {"satisfied": False, "results": results}

        results.append(
            {
                "command": command,
                "status": "passed" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode,
            }
        )
        if proc.returncode != 0:
            return {"satisfied": False, "results": results}
    return {"satisfied": True, "results": results}


def _pre_dispatch_gate_evaluation(
    *,
    sanitation_ok: bool,
    sanitation_reason: str | None,
    unresolved_missing: list[str],
    validation_commands: list[str],
) -> dict[str, Any]:
    failure_classes: list[str] = []
    notes: list[str] = []
    if not sanitation_ok:
        failure_classes.append("sanitation_failed")
        if sanitation_reason:
            notes.append(f"sanitation_reason={sanitation_reason}")
    if unresolved_missing:
        failure_classes.append("validation_target_missing")
        notes.append("missing_targets=" + ", ".join(unresolved_missing))

    verdict = GateVerdict.PASS.value if not failure_classes else GateVerdict.BLOCKED.value
    gate = GateEvaluation(
        gate_type=GateType.DISPATCH_READY.value,
        verdict=verdict,
        failure_classes=failure_classes,
        repair_eligible=bool(
            set(failure_classes).intersection({"sanitation_failed", "validation_target_missing"})
        ),
        required_evidence=["issue_body", *(["validation_command"] if validation_commands else [])],
        notes=" ".join(notes).strip(),
    )
    return gate.to_dict()


# ---------------------------------------------------------------------------
# LLM-based semantic issue parsing
# ---------------------------------------------------------------------------

_ISSUE_PARSE_PROMPT = """\
You are a pre-dispatch validator for an automated code worker system.
Given a GitHub issue body, extract structured data so the system can decide
whether to dispatch a worker.

Return ONLY a JSON object with these fields:
{{
  "file_scope": [
    {{"path": "<relative file path>", "action": "modify" | "create"}}
  ],
  "validation_commands": ["<shell command to validate the work>"],
  "task_summary": "<1-2 sentence summary of what the worker should do>",
  "is_well_formed": true | false,
  "rejection_reason": "<reason if not well-formed, else null>",
  "is_auto_decomposed": true | false
}}

Rules:
- "action" is "create" if the issue says the file should be created, generated,
  added, written, or does not exist yet.  It is "modify" if the file already exists.
- Include ALL file paths mentioned in file scope, requirements, or references.
- validation_commands: extract pytest commands or other test/check commands.
- is_well_formed: true if the issue has enough information for a developer to
  act on it.  An issue with clear file scope and validation commands IS well-formed
  even if the prose description is minimal.  Only mark false if the body is truly
  empty, truncated mid-sentence, or incoherent gibberish.
- is_auto_decomposed: true if this looks like an automatically generated
  sub-issue from a decomposition system.

Issue body:
{issue_body}
"""

_ISSUE_PARSE_OPENROUTER_MODEL = "anthropic/claude-opus-5"


def _issue_parse_providers(model: str) -> tuple[ExtractionProvider, ...]:
    return (
        ExtractionProvider(
            agent_type="anthropic-api",
            model=model,
            role="critic",
            name="boss-issue-parser",
            env_vars=("ANTHROPIC_API_KEY",),
            disable_web_search=True,
        ),
        ExtractionProvider(
            agent_type="openrouter",
            model=_ISSUE_PARSE_OPENROUTER_MODEL,
            role="critic",
            name="boss-issue-parser",
            env_vars=("OPENROUTER_API_KEY",),
        ),
    )


def _normalize_issue_parse_payload(parsed: dict[str, Any]) -> dict[str, Any] | None:
    return parsed if isinstance(parsed, dict) else None


async def parse_issue_with_llm(
    issue_body: str,
    *,
    model: str = "claude-opus-5",
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Parse an issue body using a fast LLM call.

    Tries configured agent providers in order, then returns ``None`` so
    callers fall back to the regex pipeline.
    """
    body = str(issue_body or "").strip()
    if not body:
        return None

    prompt = _ISSUE_PARSE_PROMPT.format(issue_body=body[:3000])

    result = await extract_json_object_llm_first(
        prompt,
        providers=_issue_parse_providers(model),
        normalizer=_normalize_issue_parse_payload,
        timeout=timeout,
        logger=logger,
        context="LLM issue parsing",
    )
    if result.value is None:
        logger.debug(
            "LLM issue parsing unavailable, falling back to regex: source=%s error=%s",
            result.source,
            result.error,
        )
        return None
    logger.debug("LLM issue parsing via %s", result.source)
    return result.value


def llm_result_to_declared_new_files(parsed: dict[str, Any]) -> list[str]:
    """Extract file paths marked as 'create' from an LLM parse result."""
    file_scope = parsed.get("file_scope", [])
    if not isinstance(file_scope, list):
        return []
    return _ordered_unique_strings(
        [
            str(entry.get("path", "")).strip()
            for entry in file_scope
            if isinstance(entry, dict)
            and str(entry.get("action", "")).strip().lower() == "create"
            and str(entry.get("path", "")).strip()
        ]
    )


def llm_result_to_validation_commands(parsed: dict[str, Any]) -> list[str]:
    """Extract validation commands from an LLM parse result."""
    commands = parsed.get("validation_commands", [])
    if not isinstance(commands, list):
        return []
    return _ordered_unique_strings([str(cmd).strip() for cmd in commands if str(cmd).strip()])


def llm_result_to_sanitation(parsed: dict[str, Any]) -> tuple[bool, str | None]:
    """Convert LLM parse result into a sanitation verdict."""
    if not parsed.get("is_well_formed", True):
        reason = str(parsed.get("rejection_reason", "llm_rejected")).strip()
        return False, reason or "llm_rejected"
    if parsed.get("is_auto_decomposed", False):
        # Auto-decomposed issues are acceptable if well-formed
        task_summary = str(parsed.get("task_summary", "")).strip()
        if len(task_summary) < 20:
            return False, "auto_decomposed_missing_task"
    return True, None


def llm_result_to_file_scope(parsed: dict[str, Any]) -> list[str]:
    """Extract all file paths from an LLM parse result."""
    file_scope = parsed.get("file_scope", [])
    if not isinstance(file_scope, list):
        return []
    return _ordered_unique_strings(
        [
            str(entry.get("path", "")).strip()
            for entry in file_scope
            if isinstance(entry, dict) and str(entry.get("path", "")).strip()
        ]
    )


# ---------------------------------------------------------------------------
# Unified dispatch gate (LLM-first with regex fallback)
# ---------------------------------------------------------------------------


async def check_pre_dispatch_gate(
    issue_body: str,
    *,
    repo_root: Path,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run the full pre-dispatch validation gate.

    Uses deterministic regex parsing by default.  When ``use_llm`` is true,
    tries LLM-based parsing first for robust semantic understanding and falls
    back to the regex pipeline on any LLM failure.

    Returns a dict with:
      - ``"pass"``: bool — whether dispatch should proceed
      - ``"method"``: ``"llm"`` or ``"regex"``
      - ``"sanitation_ok"``: bool
      - ``"sanitation_reason"``: str | None
      - ``"declared_new_files"``: list[str]
      - ``"validation_commands"``: list[str]
      - ``"missing_targets"``: list[str]
      - ``"unresolved_missing"``: list[str]
    """
    body = str(issue_body or "").strip()

    # --- Attempt LLM parsing only when explicitly enabled ---
    llm_parsed = await parse_issue_with_llm(body) if use_llm else None

    if llm_parsed is not None:
        san_ok, san_reason = llm_result_to_sanitation(llm_parsed)
        declared_new = llm_result_to_declared_new_files(llm_parsed)
        validation_cmds = llm_result_to_validation_commands(llm_parsed)

        # Still use filesystem check for missing targets
        pre_dispatch_cmds = []
        for cmd in validation_cmds:
            normalized_cmd = str(cmd).strip()
            if any(
                normalized_cmd.lower().startswith(prefix)
                for prefix in _PRE_DISPATCH_SAFE_COMMAND_PREFIXES
            ):
                pre_dispatch_cmds.append(normalized_cmd)
        missing = find_missing_pre_dispatch_validation_targets(
            pre_dispatch_cmds, repo_root=repo_root
        )
        unresolved = [t for t in missing if t not in set(declared_new)]
        gate = _pre_dispatch_gate_evaluation(
            sanitation_ok=san_ok,
            sanitation_reason=san_reason,
            unresolved_missing=unresolved,
            validation_commands=validation_cmds,
        )

        return {
            "pass": san_ok and not unresolved,
            "method": "llm",
            "sanitation_ok": san_ok,
            "sanitation_reason": san_reason,
            "declared_new_files": declared_new,
            "validation_commands": validation_cmds,
            "missing_targets": missing,
            "unresolved_missing": unresolved,
            "gate_evaluation": gate,
        }

    # --- Regex fallback ---
    san_ok, san_reason = assess_issue_body_sanitation(body)
    declared_new = extract_declared_new_file_paths(body)
    validation_cmds = extract_pre_dispatch_validation_commands(body)
    missing = find_missing_pre_dispatch_validation_targets(validation_cmds, repo_root=repo_root)
    unresolved = [t for t in missing if t not in set(declared_new)]
    gate = _pre_dispatch_gate_evaluation(
        sanitation_ok=san_ok,
        sanitation_reason=san_reason,
        unresolved_missing=unresolved,
        validation_commands=validation_cmds,
    )

    return {
        "pass": san_ok and not unresolved,
        "method": "regex",
        "sanitation_ok": san_ok,
        "sanitation_reason": san_reason,
        "declared_new_files": declared_new,
        "validation_commands": validation_cmds,
        "missing_targets": missing,
        "unresolved_missing": unresolved,
        "gate_evaluation": gate,
    }


# ---------------------------------------------------------------------------
# Focused Test Discovery
# ---------------------------------------------------------------------------


def discover_focused_tests(
    repo_path: Path,
    *,
    base_ref: str = "origin/main",
) -> list[str]:
    """Discover test files corresponding to source files changed since *base_ref*.

    Uses the ``tests/`` mirror convention: a source file at
    ``aragora/swarm/boss_loop.py`` maps to ``tests/swarm/test_boss_loop.py``.

    Returns a list of relative paths (strings) for test files that actually
    exist on disk.  Returns an empty list when ``git`` is unavailable or the
    diff is empty.
    """
    try:
        proc = _run_subprocess(
            ["git", "diff", "--name-only", base_ref + "..HEAD"],
            cwd=str(repo_path),
            timeout=15,
        )
        if proc.returncode != 0:
            logger.debug("git diff failed (rc=%d): %s", proc.returncode, proc.stderr.strip())
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("discover_focused_tests: git unavailable: %s", exc)
        return []

    changed = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]

    test_paths: list[str] = []
    seen: set[str] = set()

    for filepath in changed:
        parts = Path(filepath).parts
        if not filepath.endswith(".py"):
            continue

        # Source files under aragora/ -> mirror in tests/
        if parts and parts[0] == "aragora" and len(parts) >= 2:
            test_relative = Path("tests") / Path(*parts[1:])
            test_candidate = test_relative.parent / f"test_{test_relative.stem}.py"
            candidate_str = str(test_candidate)
            if candidate_str not in seen and (repo_path / test_candidate).exists():
                seen.add(candidate_str)
                test_paths.append(candidate_str)

        # Changed files already under tests/ -> include directly
        elif parts and parts[0] == "tests" and Path(filepath).name.startswith("test_"):
            if filepath not in seen and (repo_path / filepath).exists():
                seen.add(filepath)
                test_paths.append(filepath)

    return test_paths


def _should_replace_with_focused_tests(command: str) -> bool:
    text = str(command or "").strip()
    lowered = text.lower()
    if "-k" in lowered:
        return False
    if not (lowered.startswith("pytest ") or lowered.startswith("python -m pytest ")):
        return False
    explicit_file_target = re.search(r"(?<!\S)tests/\S+\.py(?:::\S+)?(?!\S)", text)
    if explicit_file_target:
        return False
    return "tests/" in text
