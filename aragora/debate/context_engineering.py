"""
Debate context engineering helpers.

Builds a grounded codebase context block for debates by combining:
1. Deterministic repository inventory (via CodebaseContextBuilder / RLM scaffolding)
2. Optional multi-harness explorer synthesis (Claude, Codex, KiloCode)
3. Explicit guardrails to prevent "rebuild what already exists" plans
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aragora.agents import create_agent
from aragora.agents.cli_agents import KiloCodeAgent
from aragora.rlm.codebase_context import CodebaseContextBuilder

logger = logging.getLogger(__name__)


_ANCHOR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Debate Core",
        (
            "aragora/debate/orchestrator.py",
            "aragora/debate/phases/context_init.py",
            "aragora/debate/context_gatherer/gatherer.py",
        ),
    ),
    (
        "Idea To Execution",
        (
            "aragora/pipeline/idea_to_execution.py",
            "aragora/pipeline/dag_operations.py",
            "aragora/pipeline/receipt_generator.py",
        ),
    ),
    (
        "Interrogation And Spec",
        (
            "aragora/interrogation/engine.py",
            "aragora/prompt_engine/spec_builder.py",
        ),
    ),
    (
        "Knowledge And Memory",
        (
            "aragora/knowledge/bridges.py",
            "aragora/knowledge/mound/adapters/obsidian.py",
            "aragora/memory/cross_debate_rlm.py",
        ),
    ),
    (
        "Nomic Loop",
        (
            "scripts/nomic_loop.py",
            "aragora/nomic/context_builder.py",
            "aragora/nomic/rlm_codebase.py",
        ),
    ),
)


@dataclass(slots=True)
class ContextEngineeringConfig:
    """Configuration for pre-debate context engineering."""

    task: str
    repo_path: Path
    include_tests: bool = True
    include_rlm_full_corpus: bool = False
    include_harness_exploration: bool = False
    include_kilocode: bool = False
    max_output_chars: int = 80_000
    build_timeout_seconds: int = 240
    per_explorer_timeout_seconds: int = 180


@dataclass(slots=True)
class ContextEngineeringResult:
    """Built context block plus build metadata."""

    context: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _trim_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Trim text to max_chars while preserving head and tail."""
    if max_chars <= 0:
        return ("", len(text) > 0)
    if len(text) <= max_chars:
        return (text, False)
    if max_chars < 200:
        return (text[:max_chars], True)
    head = int(max_chars * 0.82)
    tail = max(0, max_chars - head - 36)
    trimmed = (
        text[:head].rstrip()
        + "\n\n...[truncated for context budget]...\n\n"
        + text[-tail:].lstrip()
    )
    return (trimmed, True)


def _build_anchor_inventory(repo_path: Path) -> str:
    """Build a path-grounded anchor table for known major subsystems."""
    lines = [
        "| Domain | Canonical File | Status |",
        "|---|---|---|",
    ]
    for domain, paths in _ANCHOR_GROUPS:
        for rel in paths:
            status = "present" if (repo_path / rel).exists() else "missing"
            lines.append(f"| {domain} | `{rel}` | {status} |")
    return "\n".join(lines)


def _build_guardrails() -> str:
    """Rules appended to engineered context before debate begins."""
    return """## Grounding Rules (Fail If Violated)
- Propose changes against existing files first; do not invent a new `/src/` tree.
- Every task must cite concrete owner file paths that already exist or explain why a new file is unavoidable.
- Include a `what already exists` subsection before `what to change`.
- Any proposed new file must include a collision check against nearest existing module.
- Treat missing path verification as a blocker, not a warning."""


def _exploration_prompt(repo_path: Path, task: str) -> str:
    """Prompt for explorer harnesses."""
    return (
        "Audit this repository to ground a planning debate.\n\n"
        f"Repository: {repo_path}\n"
        f"Debate task: {task}\n\n"
        "Output requirements:\n"
        "1. EXISTING COMPONENTS: list concrete modules/classes already implementing relevant behavior.\n"
        "2. VERIFIED FILE PATHS: provide exact paths, not generic architecture guesses.\n"
        "3. TRUE GAPS ONLY: list missing pieces only when no nearby implementation exists.\n"
        "4. ANTI-REINVENTION WARNINGS: call out common mistaken rewrites to avoid.\n"
    )


def _make_cli_agent(provider: str, timeout_seconds: int) -> Any:
    """Best-effort creation of CLI explorer agents."""
    return create_agent(
        model_type=provider,  # type: ignore[arg-type]
        name=f"{provider}_context_explorer",
        role="analyst",
        timeout=float(timeout_seconds),
    )


def _make_explorer_agents(
    config: ContextEngineeringConfig,
) -> tuple[list[tuple[str, Any]], list[str]]:
    """Instantiate explorer agents and collect setup errors."""
    agents: list[tuple[str, Any]] = []
    errors: list[str] = []

    for provider in ("claude", "codex"):
        try:
            agent = _make_cli_agent(provider, config.per_explorer_timeout_seconds)
            agents.append((provider, agent))
        except Exception as exc:  # noqa: BLE001 - optional best-effort path
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")

    if config.include_kilocode:
        kilo_path = shutil.which("kilo") or shutil.which("kilocode")
        if kilo_path:
            try:
                agents.append(
                    (
                        "kilocode-gemini",
                        KiloCodeAgent(
                            name="kilocode_gemini_explorer",
                            provider_id="google/gemini-3.1-pro",
                            role="analyst",
                            timeout=config.per_explorer_timeout_seconds,
                            mode="architect",
                        ),
                    )
                )
                agents.append(
                    (
                        "kilocode-grok",
                        KiloCodeAgent(
                            name="kilocode_grok_explorer",
                            provider_id="openrouter/x-ai/grok-4.5",
                            role="analyst",
                            timeout=config.per_explorer_timeout_seconds,
                            mode="architect",
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - optional best-effort path
                errors.append(f"kilocode: {type(exc).__name__}: {exc}")
        else:
            errors.append("kilocode: CLI not found (`kilo`/`kilocode` not in PATH)")

    return (agents, errors)


async def _run_single_explorer(
    *,
    name: str,
    agent: Any,
    prompt: str,
    timeout_seconds: int,
    max_chars: int,
) -> SimpleNamespace:
    """Execute one explorer with timeout and output trimming."""
    started = time.monotonic()
    run_task: asyncio.Task[Any] = asyncio.create_task(agent.generate(prompt, context=[]))
    try:
        done, pending = await asyncio.wait(
            {run_task},
            timeout=max(1, timeout_seconds),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if pending:
            run_task.cancel()
            run_task.add_done_callback(_consume_task_exception)
            cleanup: dict[str, int] | None = None
            cleanup_error: str | None = None
            try:
                from aragora.agents.cli_agents import terminate_tracked_cli_processes

                cleanup = terminate_tracked_cli_processes()
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup only
                cleanup_error = f"{type(exc).__name__}: {exc}"

            logger.warning(
                "context_engineering_explorer_timeout "
                "name=%s timeout=%ss cleanup=%s cleanup_error=%s",
                name,
                timeout_seconds,
                cleanup,
                cleanup_error,
            )
            error = f"timeout after {timeout_seconds}s"
            if cleanup:
                error += (
                    " (cleanup:"
                    f" terminated={cleanup.get('terminated', 0)}"
                    f" killed={cleanup.get('killed', 0)}"
                    f" remaining={cleanup.get('remaining', 0)})"
                )
            if cleanup_error:
                error += f" (cleanup_error={cleanup_error})"
            return SimpleNamespace(
                name=name,
                success=False,
                output="",
                truncated=False,
                error=error,
                duration_seconds=round(time.monotonic() - started, 2),
            )

        output = run_task.result()
        output = output or ""
        trimmed, truncated = _trim_text(output.strip(), max_chars=max_chars)
        return SimpleNamespace(
            name=name,
            success=bool(trimmed),
            output=trimmed,
            truncated=truncated,
            error=None,
            duration_seconds=round(time.monotonic() - started, 2),
        )
    except Exception as exc:  # noqa: BLE001 - best-effort optional path
        logger.warning("context_engineering_explorer_failed name=%s error=%s", name, exc)
        return SimpleNamespace(
            name=name,
            success=False,
            output="",
            truncated=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=round(time.monotonic() - started, 2),
        )
    finally:
        if not run_task.done():
            run_task.cancel()
            run_task.add_done_callback(_consume_task_exception)


def _consume_task_exception(task: asyncio.Task[Any]) -> None:
    """Drain task exception in callbacks to avoid unhandled-task warnings."""
    with contextlib.suppress(BaseException):
        task.result()


async def _build_base_map(config: ContextEngineeringConfig) -> tuple[str, dict[str, Any]]:
    """Build deterministic codebase map section."""
    builder = CodebaseContextBuilder(
        root_path=config.repo_path,
        include_tests=config.include_tests,
        full_corpus=config.include_rlm_full_corpus,
    )

    start = time.monotonic()
    index = await asyncio.wait_for(
        builder.build_index(),
        timeout=max(30, min(config.build_timeout_seconds, 300)),
    )
    context_map = await asyncio.wait_for(
        builder.build_debate_context(),
        timeout=max(30, config.build_timeout_seconds),
    )

    budget = max(8_000, min(config.max_output_chars // 2, 55_000))
    trimmed_map, map_truncated = _trim_text(context_map, max_chars=budget)
    anchors = _build_anchor_inventory(config.repo_path)

    header = (
        "## Deterministic Codebase Inventory\n"
        f"- Repo: `{config.repo_path}`\n"
        f"- Indexed files: {index.total_files}\n"
        f"- Indexed lines: {index.total_lines}\n"
        f"- Estimated tokens: {index.total_tokens_estimate}\n"
        f"- Full-corpus RLM summary: {'on' if config.include_rlm_full_corpus else 'off'}\n"
    )

    section = "\n\n".join(
        [
            header,
            "## Canonical Existing Anchors\n" + anchors,
            "## Codebase Structure Map\n" + trimmed_map,
        ]
    )
    meta = {
        "indexed_files": index.total_files,
        "indexed_lines": index.total_lines,
        "estimated_tokens": index.total_tokens_estimate,
        "map_truncated": map_truncated,
        "duration_seconds": round(time.monotonic() - start, 2),
    }
    return (section, meta)


async def _build_harness_section(config: ContextEngineeringConfig) -> tuple[str, dict[str, Any]]:
    """Build optional multi-harness explorer section."""
    if not config.include_harness_exploration:
        return ("", {"enabled": False})

    prompt = _exploration_prompt(config.repo_path, config.task)
    agents, setup_errors = _make_explorer_agents(config)
    if not agents:
        lines = ["## Harness Explorer Synthesis", "- No explorer agents available."]
        for err in setup_errors:
            lines.append(f"- setup error: {err}")
        return ("\n".join(lines), {"enabled": True, "successes": 0, "errors": setup_errors})

    per_agent_budget = max(2_000, min(config.max_output_chars // max(len(agents) + 2, 2), 18_000))
    results = await asyncio.gather(
        *[
            _run_single_explorer(
                name=name,
                agent=agent,
                prompt=prompt,
                timeout_seconds=config.per_explorer_timeout_seconds,
                max_chars=per_agent_budget,
            )
            for name, agent in agents
        ]
    )

    lines = ["## Harness Explorer Synthesis"]
    success_count = 0
    result_errors = list(setup_errors)

    for result in results:
        if result.success:
            success_count += 1
            lines.append(
                f"### {result.name} (duration={result.duration_seconds}s, "
                f"truncated={'yes' if result.truncated else 'no'})"
            )
            lines.append(result.output)
        else:
            result_errors.append(f"{result.name}: {result.error}")

    if success_count == 0:
        lines.append("- All explorer runs failed.")
    if result_errors:
        lines.append("### Explorer Errors")
        for err in result_errors:
            lines.append(f"- {err}")

    return (
        "\n\n".join(lines),
        {
            "enabled": True,
            "requested_agents": [name for name, _ in agents],
            "successes": success_count,
            "errors": result_errors,
        },
    )


async def build_debate_context_engineering(
    config: ContextEngineeringConfig,
) -> ContextEngineeringResult:
    """
    Build a grounded context block for debate input.

    Returns an empty context when configuration is invalid or build fails.
    """
    started = time.monotonic()
    repo_path = config.repo_path.expanduser().resolve()
    if not repo_path.exists():
        return ContextEngineeringResult(
            context="",
            metadata={
                "error": f"repo path does not exist: {repo_path}",
                "duration_seconds": round(time.monotonic() - started, 2),
            },
        )

    effective = ContextEngineeringConfig(
        task=config.task,
        repo_path=repo_path,
        include_tests=config.include_tests,
        include_rlm_full_corpus=config.include_rlm_full_corpus,
        include_harness_exploration=config.include_harness_exploration,
        include_kilocode=config.include_kilocode,
        max_output_chars=max(8_000, config.max_output_chars),
        build_timeout_seconds=max(30, config.build_timeout_seconds),
        per_explorer_timeout_seconds=max(15, config.per_explorer_timeout_seconds),
    )

    try:
        base_section, base_meta = await _build_base_map(effective)
    except Exception as exc:  # noqa: BLE001 - caller should still proceed with debate
        logger.warning("context_engineering_base_failed error=%s", exc)
        return ContextEngineeringResult(
            context="",
            metadata={
                "error": f"base context build failed: {type(exc).__name__}: {exc}",
                "duration_seconds": round(time.monotonic() - started, 2),
            },
        )

    harness_section, harness_meta = await _build_harness_section(effective)
    sections = [
        "## Codebase Reality Check (Auto-Generated)",
        (
            "Use this section as canonical repository truth. "
            "Do not propose plans that recreate already-implemented components."
        ),
        base_section,
    ]
    if harness_section:
        sections.append(harness_section)
    sections.append(_build_guardrails())

    combined = "\n\n".join(s for s in sections if s.strip())
    combined, final_truncated = _trim_text(combined, max_chars=effective.max_output_chars)

    metadata = {
        "repo_path": str(repo_path),
        "include_tests": effective.include_tests,
        "include_rlm_full_corpus": effective.include_rlm_full_corpus,
        "include_harness_exploration": effective.include_harness_exploration,
        "include_kilocode": effective.include_kilocode,
        "final_truncated": final_truncated,
        "base": base_meta,
        "harnesses": harness_meta,
        "duration_seconds": round(time.monotonic() - started, 2),
    }
    return ContextEngineeringResult(context=combined, metadata=metadata)


__all__ = [
    "ContextEngineeringConfig",
    "ContextEngineeringResult",
    "build_debate_context_engineering",
]
