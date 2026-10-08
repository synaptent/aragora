"""
Context gathering phase for nomic loop.

Phase 0: Gather codebase understanding
- All agents explore codebase to gather context
- Each agent uses its native codebase exploration harness
- Prevents proposals for features that already exist
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable

from . import ContextResult

# Optional metrics recording (imported lazily to avoid circular imports)
_metrics_recorder: Callable[[str, str, float], None] | None = None
_agent_metrics_recorder: Callable[[str, str, float], None] | None = None


def set_metrics_recorder(
    phase_recorder: Callable[[str, str, float], None] | None = None,
    agent_recorder: Callable[[str, str, float], None] | None = None,
) -> None:
    """Set the metrics recorder callbacks for profiling.

    Args:
        phase_recorder: Callback(phase, outcome, duration_seconds)
        agent_recorder: Callback(phase, agent, duration_seconds)
    """
    global _metrics_recorder, _agent_metrics_recorder
    _metrics_recorder = phase_recorder
    _agent_metrics_recorder = agent_recorder


class ContextPhase:
    """
    Handles context gathering from multiple agents.

    Each agent uses its native codebase exploration harness:
    - Claude → Claude Code CLI (native codebase access)
    - Codex → Codex CLI (native codebase access)
    - Gemini → Kilo Code CLI (agentic codebase exploration)
    - Grok → Kilo Code CLI (agentic codebase exploration)
    """

    def __init__(
        self,
        aragora_path: Path,
        claude_agent: Any,
        codex_agent: Any,
        gemini_agent: Any = None,
        grok_agent: Any = None,
        kilocode_available: bool = False,
        skip_kilocode: bool = False,
        kilocode_agent_factory: Callable[..., Any] | None = None,
        cycle_count: int = 0,
        log_fn: Callable[..., None] | None = None,
        stream_emit_fn: Callable[..., None] | None = None,
        get_features_fn: Callable[[], str] | None = None,
        context_builder: Any | None = None,
    ):
        """
        Initialize the context gathering phase.

        Args:
            aragora_path: Path to the aragora project root
            claude_agent: Claude agent instance
            codex_agent: Codex agent instance
            kilocode_available: Whether KiloCode is available
            skip_kilocode: Whether to skip KiloCode for context gathering
            kilocode_agent_factory: Factory to create KiloCode agents
            cycle_count: Current cycle number
            log_fn: Function to log messages
            stream_emit_fn: Function to emit streaming events
            get_features_fn: Function to get current features as fallback
            context_builder: Optional NomicContextBuilder for RLM-powered context
        """
        self.aragora_path = aragora_path
        self.claude = claude_agent
        self.codex = codex_agent
        self.gemini = gemini_agent
        self.grok = grok_agent
        self.kilocode_available = kilocode_available
        self.skip_kilocode = skip_kilocode
        self.kilocode_agent_factory = kilocode_agent_factory
        self.cycle_count = cycle_count
        self._log: Callable[..., None] = log_fn or print
        self._stream_emit: Callable[..., None] = stream_emit_fn or (lambda *args: None)
        self._get_features = get_features_fn or (lambda: "No features available")
        self._context_builder = context_builder

    async def execute(self) -> ContextResult:
        """
        Execute the context gathering phase.

        Returns:
            ContextResult with gathered codebase context
        """
        phase_start = time.perf_counter()
        # Determine how many agents will participate
        skip_codex = os.environ.get("NOMIC_CONTEXT_SKIP_CODEX", "0") == "1"
        skip_claude = os.environ.get("NOMIC_CONTEXT_SKIP_CLAUDE", "0") == "1"
        skip_gemini = os.environ.get("NOMIC_CONTEXT_SKIP_GEMINI", "0") == "1"
        skip_grok = os.environ.get("NOMIC_CONTEXT_SKIP_GROK", "0") == "1"
        use_kilocode = self.kilocode_available and not self.skip_kilocode
        self._log(
            "  [context] kilocode_available="
            f"{self.kilocode_available} skip_kilocode={self.skip_kilocode} "
            f"factory={'yes' if self.kilocode_agent_factory else 'no'}"
        )
        agents_count = 0
        if self.claude and not skip_claude:
            agents_count += 1
        if self.codex and not skip_codex:
            agents_count += 1
        if use_kilocode:
            agents_count += 2  # + Gemini + Grok via Kilo Code
            self._log("\n" + "=" * 70)
            self._log("PHASE 0: CONTEXT GATHERING (All 4 agents with codebase access)")
            self._log("  Claude → Claude Code | Codex → Codex CLI")
            self._log("  Gemini → Kilo Code  | Grok → Kilo Code")
            self._log("=" * 70)
        else:
            if self.gemini and not skip_gemini:
                agents_count += 1
            if self.grok and not skip_grok:
                agents_count += 1
            self._log("\n" + "=" * 70)
            extra = []
            if self.gemini and not skip_gemini:
                extra.append("Gemini API")
            if self.grok and not skip_grok:
                extra.append("Grok API")
            extra_label = f" + {', '.join(extra)}" if extra else ""
            self._log(f"PHASE 0: CONTEXT GATHERING (Claude + Codex{extra_label})")
            if self.kilocode_available and self.skip_kilocode:
                self._log("  Note: KiloCode skipped (timeouts); Gemini/Grok join in debates")
            else:
                self._log("  Note: Install kilocode CLI to enable Gemini/Grok exploration")
            self._log("=" * 70)

        self._stream_emit("on_phase_start", "context", self.cycle_count, {"agents": agents_count})

        # Build list of exploration tasks
        exploration_tasks = []
        if self.claude and not skip_claude:
            exploration_tasks.append(self._gather_with_agent(self.claude, "claude", "Claude Code"))
        if self.codex and not skip_codex:
            exploration_tasks.append(self._gather_with_agent(self.codex, "codex", "Codex CLI"))

        # Add Gemini and Grok via Kilo Code if available (and not skipped)
        if use_kilocode and self.kilocode_agent_factory:
            gemini_explorer = self.kilocode_agent_factory(
                name="gemini-explorer",
                provider_id="google/gemini-3.1-pro",
                model="google/gemini-3.1-pro",
                role="explorer",
                timeout=600,
                mode="architect",
            )
            grok_explorer = self.kilocode_agent_factory(
                name="grok-explorer",
                provider_id="openrouter/x-ai/grok-4.5",
                model="openrouter/x-ai/grok-4.5",
                role="explorer",
                timeout=600,
                mode="architect",
            )
            exploration_tasks.extend(
                [
                    self._gather_with_agent(gemini_explorer, "gemini", "Kilo Code"),
                    self._gather_with_agent(grok_explorer, "grok", "Kilo Code"),
                ]
            )
        elif not use_kilocode:
            # Fall back to direct API agents when Kilo Code is unavailable or disabled.
            if self.gemini and not skip_gemini:
                exploration_tasks.append(
                    self._gather_with_agent(self.gemini, "gemini", "Gemini API")
                )
            if self.grok and not skip_grok:
                exploration_tasks.append(self._gather_with_agent(self.grok, "grok", "Grok API"))

        # Run all agents in parallel
        results = await asyncio.gather(*exploration_tasks, return_exceptions=True)

        # Combine the context from all agents
        combined_context = []
        for result in results:
            if isinstance(result, BaseException):
                continue
            name, harness, content = result
            if content and "Error:" not in content:
                combined_context.append(
                    f"=== {name.upper()}'S CODEBASE ANALYSIS (via {harness}) ===\n{content}"
                )

        # If all failed, fall back to basic context
        if not combined_context:
            self._log("  Warning: Context gathering failed, using basic context")
            combined_context = [f"Current features (from docstring):\n{self._get_features()}"]

        # Add RLM-powered codebase structure map from NomicContextBuilder
        if self._context_builder:
            try:
                rlm_context = await self._context_builder.build_debate_context()
                if rlm_context:
                    combined_context.insert(
                        0,
                        f"=== CODEBASE STRUCTURE MAP (via RLM Context Builder) ===\n{rlm_context}",
                    )
                    self._log("  RLM context builder: added structured codebase map")
            except (RuntimeError, ValueError, OSError) as e:
                self._log(f"  RLM context builder: failed ({e}), continuing without")

        gathered_context = "\n\n".join(combined_context)

        env_rlm_context = os.environ.get("ARAGORA_NOMIC_CONTEXT_RLM")
        use_rlm_context = True if env_rlm_context is None else env_rlm_context.lower() == "true"
        if use_rlm_context:
            # Prefer NomicContextBuilder (TRUE RLM + REPL) when available.
            if self._context_builder is not None:
                try:
                    await self._context_builder.build_rlm_context()
                    rlm_context = await self._context_builder.build_debate_context()
                    if rlm_context:
                        gathered_context = rlm_context
                        self._log("  [context] TRUE RLM context builder applied (deep index)")
                except (RuntimeError, ValueError, OSError) as e:
                    self._log(f"  [context] RLM context builder unavailable: {e}")
            else:
                try:
                    from aragora.rlm import get_rlm, RLMConfig

                    rlm_config = RLMConfig()
                    if hasattr(rlm_config, "max_content_bytes_nomic"):
                        rlm_config.max_content_bytes = rlm_config.max_content_bytes_nomic
                    env_max_bytes = os.environ.get(
                        "ARAGORA_NOMIC_MAX_CONTEXT_BYTES"
                    ) or os.environ.get("NOMIC_MAX_CONTEXT_BYTES")
                    if env_max_bytes:
                        try:
                            rlm_config.max_content_bytes = int(env_max_bytes)
                        except ValueError:
                            self._log(
                                "  [context] Invalid ARAGORA_NOMIC_MAX_CONTEXT_BYTES="
                                f"{env_max_bytes}"
                            )

                    rlm = get_rlm(config=rlm_config)
                    rlm_result = await rlm.compress_and_query(
                        query=(
                            "Provide a comprehensive, code-level summary of the aragora "
                            "codebase for debate context."
                        ),
                        content=gathered_context,
                        source_type="nomic_context",
                    )
                    if rlm_result and rlm_result.answer:
                        gathered_context = rlm_result.answer
                        self._log("  [context] TRUE RLM context builder applied")
                except (ImportError, RuntimeError, ValueError, OSError) as e:
                    self._log(f"  [context] RLM context builder unavailable: {e}")

        phase_duration = time.perf_counter() - phase_start
        success = len(combined_context) > 0
        self._log(
            f"  Context gathered from {len(combined_context)} agents in {phase_duration:.1f}s"
        )
        self._stream_emit(
            "on_phase_end",
            "context",
            self.cycle_count,
            success,
            phase_duration,
            {"agents": len(combined_context), "context_length": len(gathered_context)},
        )

        # Record metrics if configured
        if _metrics_recorder:
            _metrics_recorder("context", "success" if success else "failure", phase_duration)

        # Inject recent cycle context for cross-cycle learning only after cycle 0.
        # This prevents first-cycle runs/tests from being affected by ambient history.
        if self.cycle_count > 0:
            recent_cycle_context = self._get_recent_cycle_context()
            if recent_cycle_context:
                gathered_context = f"{gathered_context}\n\n{recent_cycle_context}"
                self._log("  [context] Injected recent cycle history for cross-cycle learning")

        return ContextResult(
            success=success,
            data={"agents_succeeded": len(combined_context)},
            duration_seconds=phase_duration,
            codebase_summary=gathered_context,
            recent_changes="",  # Can be populated if needed
            open_issues=[],
        )

    def _build_explore_prompt(self) -> str:
        """Build the codebase exploration prompt."""
        return f"""Explore the aragora codebase and provide a COMPREHENSIVE FEATURE INVENTORY.

Working directory: {self.aragora_path}

Your task:
1. Read key files: CLAUDE.md, aragora/__init__.py, aragora/debate/orchestrator.py, aragora/server/unified_server.py
2. Read module indexes: aragora/debate/__init__.py, aragora/memory/__init__.py, aragora/knowledge/__init__.py
3. List ALL existing features with their implementation locations
4. Be EXHAUSTIVE - any feature you miss may be accidentally proposed for recreation

Output format (FOLLOW EXACTLY):

## EXISTING FEATURES
## FEATURE INVENTORY (CANONICAL - DO NOT RECREATE ANY OF THESE)

### Core Debate Engine
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|
| (feature name) | aragora/debate/... | IMPLEMENTED | ClassName |

### Memory & Learning
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

### Knowledge Management
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

### API & Streaming
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

### Integrations & Connectors
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

### Enterprise & Security
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

### Self-Improvement (Nomic)
| Feature | Module | Status | Key Classes |
|---------|--------|--------|-------------|

## ARCHITECTURE OVERVIEW
## ARCHITECTURE PATTERNS
- List the main design patterns used (e.g., mixin-based handlers, adapter pattern for KM)

## IMPLEMENTATION DENSITY BY AREA
(Estimate: fully implemented, partially implemented, stub only)
- Debate: X%
- Memory: X%
- Knowledge: X%
- API: X%
- Integrations: X%

## GAPS AND OPPORTUNITIES
## GENUINE GAPS (truly missing, not variations of existing features)
Only list features that have NO existing implementation or close variant.
DO NOT list features that are already implemented under different names.

CRITICAL RULES:
1. If in doubt whether something exists, assume IT EXISTS and look harder
2. Check for alternative names (e.g., "spectator mode" might be "read-only view")
3. Check for partial implementations (e.g., WebSocket streaming exists even if not fully featured)
4. NEVER propose something that could be a configuration change to existing code"""

    async def _gather_with_agent(self, agent: Any, name: str, harness: str) -> tuple[str, str, str]:
        """Run exploration with one agent."""
        from aragora.server.stream.arena_hooks import streaming_task_context

        agent_start = time.perf_counter()
        heartbeat_task: asyncio.Task | None = None
        done_event = asyncio.Event()
        try:
            self._log(f"  {name} ({harness}): exploring codebase...", agent=name)
            prompt = self._build_explore_prompt()
            task_id = f"{name}:nomic_context"
            with streaming_task_context(task_id):
                timeout_override = os.environ.get("NOMIC_CONTEXT_AGENT_TIMEOUT", "")
                timeout = None
                if timeout_override:
                    try:
                        timeout = int(timeout_override)
                    except ValueError:
                        timeout = None
                if timeout is None:
                    timeout = getattr(agent, "timeout", None)
                if timeout is None:
                    self._log(
                        f"  {name}: no timeout configured; set NOMIC_CONTEXT_AGENT_TIMEOUT "
                        "to enforce a limit",
                        agent=name,
                    )
                else:
                    self._log(f"  {name}: timeout={timeout}s", agent=name)

                async def _heartbeat() -> None:
                    while not done_event.is_set():
                        await asyncio.sleep(60)
                        if done_event.is_set():
                            break
                        elapsed = time.perf_counter() - agent_start
                        self._log(f"  {name}: still running ({elapsed:.0f}s)...", agent=name)

                heartbeat_task = asyncio.create_task(_heartbeat())

                if timeout and timeout > 0:
                    result = await asyncio.wait_for(
                        agent.generate(prompt, context=[]),
                        timeout=timeout,
                    )
                else:
                    result = await agent.generate(prompt, context=[])
            self._log(f"  {name}: complete ({len(result) if result else 0} chars)", agent=name)
            # Emit agent's full exploration result
            if not result:
                return (name, harness, "Error: empty response")
            self._stream_emit("on_log_message", result, level="info", phase="context", agent=name)
            return (name, harness, result)
        except asyncio.TimeoutError:
            self._log(f"  {name}: timeout exceeded", agent=name)
            return (name, harness, "Error: timeout exceeded")
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            self._log(f"  {name}: error - {type(e).__name__}: {e}", agent=name)
            return (name, harness, f"Error: {type(e).__name__}: {e}")
        finally:
            done_event.set()
            if heartbeat_task:
                heartbeat_task.cancel()
            # Record per-agent metrics
            if _agent_metrics_recorder:
                agent_duration = time.perf_counter() - agent_start
                _agent_metrics_recorder("context", name, agent_duration)

    def _get_recent_cycle_context(self, n: int = 3) -> str:
        """Get summary of recent Nomic cycles for cross-cycle learning.

        Args:
            n: Number of recent cycles to include

        Returns:
            Formatted string with recent cycle summaries, or empty string if unavailable
        """
        try:
            from aragora.nomic.cycle_store import get_recent_cycles

            cycles = get_recent_cycles(n)
            if not cycles:
                return ""

            lines = ["=== RECENT NOMIC CYCLE HISTORY (for cross-cycle learning) ==="]
            lines.append(f"Last {len(cycles)} cycles:\n")

            for cycle in cycles:
                status = "SUCCESS" if cycle.success else "FAILED"
                topics = ", ".join(cycle.topics_debated[:3]) if cycle.topics_debated else "none"
                duration = f"{cycle.duration_seconds:.0f}s" if cycle.duration_seconds else "unknown"

                lines.append(f"- Cycle {cycle.cycle_id[:8]}: {status}")
                lines.append(f"  Topics: {topics}")
                lines.append(f"  Duration: {duration}")

                # Include patterns that worked
                if cycle.success and cycle.consensus_reached:
                    lines.append(f"  Consensus: {cycle.consensus_reached[0][:100]}...")

                # Include surprises/lessons
                if cycle.surprise_events:
                    for surprise in cycle.surprise_events[:1]:
                        lines.append(f"  Lesson: {surprise.description[:80]}...")

                lines.append("")

            lines.append(
                "Use this history to avoid repeating past mistakes and build on successes."
            )
            return "\n".join(lines)

        except ImportError:
            self._log("  [context] cycle_store not available, skipping cycle context")
            return ""
        except (RuntimeError, OSError, ValueError) as e:
            self._log(f"  [context] Failed to get recent cycles: {e}")
            return ""


__all__ = ["ContextPhase", "set_metrics_recorder"]
