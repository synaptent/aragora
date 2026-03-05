"""
Synthesis generation for consensus phase.

This module extracts the mandatory final synthesis logic from ConsensusPhase,
providing:
- LLM-based synthesis generation (Opus 4.5 with Sonnet fallback)
- Proposal combination fallback
- Synthesis prompt building
- Export link generation
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.events.context import streaming_task_context

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

_SYNTHESIS_CONTINUATION_ATTEMPTS = max(
    0, int(os.getenv("ARAGORA_SYNTHESIS_CONTINUATION_ATTEMPTS", "1"))
)
_SYNTHESIS_CONTINUATION_TIMEOUT_SECONDS = float(
    os.getenv("ARAGORA_SYNTHESIS_CONTINUATION_TIMEOUT_SECONDS", "30.0")
)
_SYNTHESIS_CONTINUATION_TAIL_CHARS = max(
    1000, int(os.getenv("ARAGORA_SYNTHESIS_CONTINUATION_TAIL_CHARS", "4000"))
)


class SynthesisGenerator:
    """Generates final synthesis for debates.

    Ensures every debate ends with a clear, synthesized conclusion
    using Claude Opus 4.5 (with Sonnet fallback).

    Usage:
        generator = SynthesisGenerator(
            protocol=protocol,
            hooks=hooks,
            notify_spectator=notify_spectator,
        )

        success = await generator.generate_mandatory_synthesis(ctx)
    """

    def __init__(
        self,
        *,
        protocol: Any = None,
        hooks: dict[str, Any] | None = None,
        notify_spectator: Callable[..., Any] | None = None,
    ) -> None:
        """Initialize the synthesis generator.

        Args:
            protocol: Debate protocol for configuration
            hooks: Event hooks dict
            notify_spectator: Spectator notification callback
        """
        self.protocol = protocol
        self.hooks = hooks or {}
        self._notify_spectator = notify_spectator

    async def generate_mandatory_synthesis(self, ctx: DebateContext) -> bool:
        """Generate mandatory final synthesis using Claude Opus 4.5.

        This runs after consensus is determined (by any mode) to ensure
        every debate ends with a clear, synthesized conclusion.

        Args:
            ctx: The DebateContext with proposals and consensus result

        Returns:
            bool: True if synthesis was successfully generated and emitted
        """
        # If no proposals, emit a minimal synthesis to avoid silent endings
        if not ctx.proposals:
            logger.warning("synthesis_fallback reason=no_proposals")
            synthesis = (
                "## Debate Summary\n\n"
                "No proposals were generated. One or more agents may have failed to respond."
            )
            ctx.result.synthesis = synthesis
            # Only set final_answer if the consensus phase didn't already set one
            if not ctx.result.final_answer:
                ctx.result.final_answer = synthesis
            self._emit_synthesis_events(ctx, synthesis, "fallback")
            self._generate_export_links(ctx)
            return True

        logger.info("synthesis_generation_start")

        synthesis = None
        synthesis_source = "opus"

        # In offline/demo mode (or when explicitly disabled), avoid attempting
        # network-backed synthesis models. Always produce a synthesis by
        # combining proposals.
        from aragora.utils.env import is_offline_mode

        if is_offline_mode() or not getattr(self.protocol, "enable_llm_synthesis", True):
            synthesis = self._combine_proposals_as_synthesis(ctx)
            synthesis_source = "combined"

        if synthesis:
            # Store synthesis in result
            ctx.result.synthesis = synthesis
            # Only set final_answer if the consensus phase didn't already set one
            if not ctx.result.final_answer:
                ctx.result.final_answer = synthesis

            # Emit explicit synthesis event (guaranteed delivery)
            self._emit_synthesis_events(ctx, synthesis, synthesis_source)

            # Generate export download links for aragora.ai debates
            self._generate_export_links(ctx)

            return True

        # Try 1: Claude Opus 4.5
        try:
            from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

            # Create dedicated synthesizer (always Opus 4.5)
            synthesizer = AnthropicAPIAgent(
                name="synthesis-agent",
                model="claude-opus-4-5-20251101",
            )

            # Build synthesis prompt
            synthesis_prompt = self._build_synthesis_prompt(ctx)

            # Generate synthesis with timeout (60s to fit within phase budget)
            with streaming_task_context("synthesis-agent:opus_synthesis"):
                synthesis = await asyncio.wait_for(
                    synthesizer.generate(synthesis_prompt, ctx.context_messages),
                    timeout=60.0,
                )
            synthesis = await self._ensure_complete_synthesis(
                ctx=ctx,
                synthesizer=synthesizer,
                synthesis=synthesis,
                source="opus",
            )
            logger.info("synthesis_generated_opus chars=%s", len(synthesis))

        except asyncio.TimeoutError:
            logger.warning("synthesis_opus_timeout timeout=60s, trying sonnet fallback")
            synthesis_source = "sonnet"
        except ImportError as e:
            logger.warning("synthesis_import_error: %s, trying sonnet fallback", e)
            synthesis_source = "sonnet"
        except Exception as e:  # noqa: BLE001 - phase isolation
            logger.warning("synthesis_opus_failed error=%s, trying sonnet fallback", e)
            synthesis_source = "sonnet"

        # Try 2: Claude Sonnet fallback
        if not synthesis:
            try:
                from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

                synthesizer = AnthropicAPIAgent(
                    name="synthesis-agent-fallback",
                    model="claude-sonnet-4-20250514",
                )
                synthesis_prompt = self._build_synthesis_prompt(ctx)
                with streaming_task_context("synthesis-agent-fallback:sonnet_synthesis"):
                    synthesis = await asyncio.wait_for(
                        synthesizer.generate(synthesis_prompt, ctx.context_messages),
                        timeout=30.0,
                    )
                synthesis = await self._ensure_complete_synthesis(
                    ctx=ctx,
                    synthesizer=synthesizer,
                    synthesis=synthesis,
                    source="sonnet",
                )
                logger.info("synthesis_generated_sonnet chars=%s", len(synthesis))
            except Exception as e:  # noqa: BLE001 - phase isolation: must not crash, fall through to proposal combination
                logger.warning("synthesis_sonnet_failed error=%s, using proposal combination", e)
                synthesis_source = "combined"

        # Try 3: Combine proposals as final fallback (always succeeds)
        if not synthesis:
            synthesis = self._combine_proposals_as_synthesis(ctx)
            logger.info("synthesis_generated_combined chars=%s", len(synthesis))

        # Post-process: concretize vague lines with real repo paths
        repo_hint = self._get_repo_path_hint()
        if repo_hint and synthesis:
            before_len = len(synthesis)
            synthesis = self.concretize_output(synthesis, repo_hint)
            if len(synthesis) != before_len:
                logger.info(
                    "synthesis_concretized delta_chars=%s",
                    len(synthesis) - before_len,
                )

        # Store synthesis in result
        ctx.result.synthesis = synthesis
        # Only set final_answer if the consensus phase didn't already set one
        if not ctx.result.final_answer:
            ctx.result.final_answer = synthesis

        # Emit explicit synthesis event (guaranteed delivery)
        self._emit_synthesis_events(ctx, synthesis, synthesis_source)

        # Generate export download links for aragora.ai debates
        self._generate_export_links(ctx)

        return True

    def _is_likely_truncated(self, synthesis: str) -> bool:
        """Heuristic check for truncated/incomplete synthesis output."""
        text = (synthesis or "").rstrip()
        if not text:
            return False
        lower = text.lower()
        truncation_markers = (
            "... [truncated]",
            "[... truncated ...]",
            "response truncated due to timeout",
            "[truncated]",
        )
        if any(marker in lower for marker in truncation_markers):
            return True
        if text.endswith(("...", "…")):
            return True
        if text[-1] in {":", ";", ",", "-", "(", "[", "{"}:
            return True
        if text.count("```") % 2 == 1:
            return True
        if text.count("{") > text.count("}") + 1:
            return True
        if text.count("[") > text.count("]") + 1:
            return True
        if text.count("(") > text.count(")") + 1:
            return True
        return False

    def _build_continuation_prompt(self, ctx: DebateContext, synthesis: str) -> str:
        """Build continuation prompt to resume a truncated synthesis."""
        task = ctx.env.task if ctx.env else "Unknown task"
        tail = synthesis[-_SYNTHESIS_CONTINUATION_TAIL_CHARS:]
        return (
            "Your previous synthesis response was cut off.\n\n"
            "Continue writing from the exact point where it stopped.\n"
            "Do NOT repeat earlier sections. Do NOT restart the answer.\n"
            "Finish remaining sections and end cleanly.\n\n"
            f"Original question:\n{task}\n\n"
            "Tail of current synthesis:\n"
            "```text\n"
            f"{tail}\n"
            "```"
        )

    def _merge_continuation(self, existing: str, continuation: str) -> str:
        """Append continuation while removing common overlap."""
        base = (existing or "").rstrip()
        extra = (continuation or "").strip()
        if not extra:
            return base
        if extra in base:
            return base
        if base and base in extra:
            return extra

        max_overlap = min(len(base), len(extra), 800)
        for overlap in range(max_overlap, 39, -1):
            if base.endswith(extra[:overlap]):
                return base + extra[overlap:]
        return f"{base}\n{extra}" if base else extra

    async def _ensure_complete_synthesis(
        self,
        *,
        ctx: DebateContext,
        synthesizer: Any,
        synthesis: str,
        source: str,
    ) -> str:
        """Detect and continue truncated synthesis outputs."""
        completed = synthesis or ""
        if not self._is_likely_truncated(completed):
            return completed
        if _SYNTHESIS_CONTINUATION_ATTEMPTS <= 0:
            logger.warning("synthesis_truncation_detected source=%s continuation=disabled", source)
            return completed

        logger.warning(
            "synthesis_truncation_detected source=%s attempts=%s",
            source,
            _SYNTHESIS_CONTINUATION_ATTEMPTS,
        )

        for attempt in range(1, _SYNTHESIS_CONTINUATION_ATTEMPTS + 1):
            continuation_prompt = self._build_continuation_prompt(ctx, completed)
            try:
                with streaming_task_context(f"synthesis-agent:{source}_continuation_{attempt}"):
                    continuation = await asyncio.wait_for(
                        synthesizer.generate(continuation_prompt, ctx.context_messages),
                        timeout=_SYNTHESIS_CONTINUATION_TIMEOUT_SECONDS,
                    )
            except Exception as e:  # noqa: BLE001 - continuation is best-effort
                logger.warning(
                    "synthesis_continuation_failed source=%s attempt=%s error=%s",
                    source,
                    attempt,
                    e,
                )
                break

            merged = self._merge_continuation(completed, continuation)
            if len(merged) <= len(completed):
                logger.warning(
                    "synthesis_continuation_no_progress source=%s attempt=%s",
                    source,
                    attempt,
                )
                break

            completed = merged
            if not self._is_likely_truncated(completed):
                logger.info(
                    "synthesis_continuation_resolved source=%s attempt=%s chars=%s",
                    source,
                    attempt,
                    len(completed),
                )
                return completed

        return completed

    def _emit_synthesis_events(
        self,
        ctx: DebateContext,
        synthesis: str,
        synthesis_source: str,
    ) -> None:
        """Emit synthesis-related events.

        Args:
            ctx: Debate context
            synthesis: Generated synthesis text
            synthesis_source: Source of synthesis (opus/sonnet/combined)
        """
        # Emit explicit synthesis event
        try:
            if self.hooks and "on_synthesis" in self.hooks:
                self.hooks["on_synthesis"](
                    content=synthesis,
                    confidence=ctx.result.confidence if ctx.result else 0.0,
                )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("on_synthesis hook failed: %s", e)

        # Also emit as agent_message for backwards compatibility
        try:
            if self.hooks and "on_message" in self.hooks:
                rounds = self.protocol.rounds if self.protocol else 3
                self.hooks["on_message"](
                    agent="synthesis-agent",
                    content=synthesis,
                    role="synthesis",  # Special role for frontend styling
                    round_num=rounds + 1,
                )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("on_message hook failed: %s", e)

        # Notify spectator
        try:
            if self._notify_spectator:
                self._notify_spectator(
                    "synthesis",
                    agent="synthesis-agent",
                    details=f"Final synthesis ({len(synthesis)} chars, source={synthesis_source})",
                    metric=ctx.result.confidence if ctx.result else 0.0,
                )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("notify_spectator failed: %s", e)

    def _generate_export_links(self, ctx: DebateContext) -> None:
        """Generate export download links for the debate.

        Args:
            ctx: Debate context
        """
        debate_id = getattr(ctx, "debate_id", None) or getattr(ctx.result, "debate_id", None)
        if not debate_id:
            return

        ctx.result.export_links = {
            "json": f"/api/debates/{debate_id}/export/json",
            "markdown": f"/api/debates/{debate_id}/export/md",
            "html": f"/api/debates/{debate_id}/export/html",
            "txt": f"/api/debates/{debate_id}/export/txt",
            "csv_summary": f"/api/debates/{debate_id}/export/csv?table=summary",
            "csv_messages": f"/api/debates/{debate_id}/export/csv?table=messages",
        }
        logger.info("export_links_generated debate_id=%s", debate_id)

        # Emit export ready event
        try:
            if self.hooks and "on_export_ready" in self.hooks:
                self.hooks["on_export_ready"](
                    debate_id=debate_id,
                    links=ctx.result.export_links,
                )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("on_export_ready hook failed: %s", e)

    def _combine_proposals_as_synthesis(self, ctx: DebateContext) -> str:
        """Combine proposals into a synthesis when LLM generation fails.

        This is a guaranteed fallback that always produces output.

        Args:
            ctx: The DebateContext with proposals

        Returns:
            Combined synthesis string
        """
        task = ctx.env.task if ctx.env else "the debate topic"
        proposals = ctx.proposals

        # If we have a winner, prioritize their proposal
        winner = ctx.result.winner if ctx.result else None
        if winner and winner in proposals:
            winner_proposal = proposals[winner]
            other_proposals = {k: v for k, v in proposals.items() if k != winner}

            synthesis = f"""## Final Synthesis

**Question:** {task}

### Winning Position ({winner})

{winner_proposal[:2000]}

### Other Perspectives

"""
            for agent, prop in list(other_proposals.items())[:3]:
                synthesis += f"**{agent}:** {prop[:500]}...\n\n"

            return synthesis

        # No winner - combine all proposals
        synthesis = f"""## Final Synthesis

**Question:** {task}

### Combined Perspectives

"""
        for agent, prop in list(proposals.items())[:5]:
            synthesis += f"**{agent}:**\n{prop[:800]}\n\n---\n\n"

        synthesis += "\n*Note: This synthesis was automatically generated from agent proposals.*"
        return synthesis

    def _build_synthesis_prompt(self, ctx: DebateContext) -> str:
        """Build prompt for final synthesis generation.

        When a quality output contract is available in the context, the synthesis
        uses the contract's required sections as the output structure instead of
        the default generic structure.  This ensures the debate's final answer
        naturally satisfies the post-consensus quality validator.

        Args:
            ctx: The DebateContext with proposals, critiques, and task

        Returns:
            Formatted synthesis prompt string
        """
        proposals = ctx.proposals
        # DebateContext uses 'round_critiques', not 'critiques'
        critiques = getattr(ctx, "round_critiques", []) or getattr(ctx, "critiques", []) or []
        task = ctx.env.task if ctx.env else "Unknown task"

        # Format proposals
        proposals_text = "\n\n---\n\n".join(
            f"**{agent}**:\n{prop[:1500]}" for agent, prop in proposals.items()
        )

        # Format critiques (if any)
        critiques_text = ""
        if critiques:
            critique_items = []
            for c in critiques[:5]:
                if hasattr(c, "agent") and hasattr(c, "target"):
                    summary = getattr(c, "summary", "")[:200] if hasattr(c, "summary") else ""
                    critique_items.append(f"- {c.agent} on {c.target}: {summary}")
            critiques_text = "\n".join(critique_items)

        # Check if a quality output contract is available in the context.
        # If none is explicitly provided, use the default contract so that
        # every synthesis goes through the contract-guided path.
        contract_block = self._extract_contract_block(ctx)
        if not contract_block:
            contract_block = self._default_output_contract()

        return self._build_contract_guided_prompt(
            task, proposals_text, critiques_text, contract_block
        )

    def _extract_contract_block(self, ctx: DebateContext) -> str | None:
        """Extract output contract instructions from the debate context, if present."""
        context = getattr(ctx.env, "context", "") if ctx.env else ""
        if not context:
            return None
        marker = "### Output Contract (Deterministic Quality Gates)"
        if marker in context:
            idx = context.index(marker)
            return context[idx:].strip()
        return None

    @staticmethod
    def _default_output_contract() -> str:
        """Return the default output contract used when none is explicitly provided.

        This ensures every synthesis follows the contract-guided path, producing
        structured output that satisfies the post-consensus quality validator.
        """
        return """### Output Contract (Deterministic Quality Gates)
Required sections:
1. Ranked High-Level Tasks — prioritized with action verbs
2. Suggested Subtasks — independently testable items
3. Owner module / file paths — reference existing repo paths
4. Test Plan — specific test commands and assertions
5. Rollback Plan — MUST include trigger condition (e.g. "if tests fail") AND action (e.g. "revert commit")
6. Gate Criteria — MUST include at least 2 numeric thresholds with explicit comparison operators.
   Example (yours MUST be similar — use numbers, not just words):
   - coverage >= 80% on modified files
   - p95 latency <= 250ms
   - zero new lint errors (0 errors)
   - all 7 required section headers present
   - error rate < 1.0%
   Do NOT write qualitative-only criteria like "tests should pass" — always include a number.
7. JSON Payload — machine-readable summary"""

    # Directories most relevant to self-improvement tasks get more file slots.
    _PRIORITY_DIRS = frozenset(
        {
            "debate",
            "nomic",
            "pipeline",
            "cli",
            "server",
            "agents",
            "knowledge",
            "memory",
            "control_plane",
            "audit",
            "gauntlet",
        }
    )

    @staticmethod
    def _get_repo_path_hint() -> str:
        """Generate a compact listing of real repo paths for grounding.

        Dynamically discovers all subdirectories under ``aragora/`` plus key
        test/script directories. Priority directories (debate, nomic, pipeline,
        etc.) get more file slots so synthesis agents can reference real paths
        instead of inventing them.
        """
        try:
            from pathlib import Path

            repo_root = Path(os.getcwd())
            lines: list[str] = []
            max_lines = 150
            max_chars = 12000

            # 1. Top-level project files
            top_files = [
                n for n in ("pyproject.toml", "CLAUDE.md", "Makefile") if (repo_root / n).is_file()
            ]
            if top_files:
                lines.append(f"  ./: {', '.join(top_files)}")

            # 2. Dynamically discover all immediate subdirs under aragora/
            aragora_root = repo_root / "aragora"
            if aragora_root.is_dir():
                subdirs = sorted(
                    d.relative_to(repo_root)
                    for d in aragora_root.iterdir()
                    if d.is_dir() and d.name != "__pycache__"
                )
                for subdir in subdirs:
                    if len(lines) >= max_lines:
                        break
                    dp = repo_root / subdir
                    suffixes = {".py"}
                    if "live" in str(subdir):
                        suffixes.update({".ts", ".tsx"})
                    is_priority = subdir.name in SynthesisGenerator._PRIORITY_DIRS
                    file_limit = 12 if is_priority else 8
                    files = sorted(
                        f.name
                        for f in dp.iterdir()
                        if f.is_file() and f.suffix in suffixes and f.name != "__init__.py"
                    )[:file_limit]
                    if files:
                        lines.append(f"  {subdir}/: {', '.join(files)}")
                        if sum(len(line) + 1 for line in lines) >= max_chars:
                            break

            # 3. Key test and script directories
            for d in (
                "tests/debate",
                "tests/cli",
                "tests/pipeline",
                "tests/nomic",
                "tests/agents",
                "tests/server",
                "tests/knowledge",
                "scripts",
            ):
                if len(lines) >= max_lines:
                    break
                dp = repo_root / d
                if dp.is_dir():
                    files = sorted(f.name for f in dp.iterdir() if f.suffix == ".py")[:8]
                    if files:
                        lines.append(f"  {d}/: {', '.join(files)}")
                        if sum(len(line) + 1 for line in lines) >= max_chars:
                            break

            if lines:
                return "Key repository paths (use these, not invented paths):\n" + "\n".join(lines)
        except (OSError, ValueError):
            pass
        return ""

    def _build_contract_guided_prompt(
        self,
        task: str,
        proposals_text: str,
        critiques_text: str,
        contract_block: str,
    ) -> str:
        """Build synthesis prompt that uses the quality contract's section structure."""
        repo_hint = self._get_repo_path_hint()
        repo_section = (
            f"\n\n## REPOSITORY FILE REFERENCE (USE THESE PATHS — DO NOT INVENT PATHS)\n{repo_hint}"
            if repo_hint
            else ""
        )

        return f"""You are Claude Opus 4.5, tasked with creating the DEFINITIVE synthesis of this multi-agent AI debate.
{repo_section}

## ORIGINAL QUESTION
{task}

## AGENT FINAL PROPOSALS
{proposals_text}

## KEY CRITIQUES
{critiques_text if critiques_text else "No critiques recorded."}

## OUTPUT FORMAT REQUIREMENTS (MANDATORY)
{contract_block}

## CONCRETE EXAMPLE (follow this style exactly)

## Ranked High-Level Tasks
1. **Refactor `aragora/debate/orchestrator.py:Arena.run()` to emit phase-transition events** — Add `self._emit("phase_change", phase=name)` calls at each phase boundary. Verify: `pytest tests/debate/test_orchestrator.py::test_phase_events -v`
2. **Update `aragora/debate/phases/synthesis_generator.py:SynthesisGenerator._build_synthesis_prompt()` to include repo path context** — Verify: `pytest tests/debate/test_output_quality.py -v`

## Suggested Subtasks
- Add `PhaseEvent` dataclass to `aragora/events/schema.py` — Verify: `pytest tests/events/test_schema.py::test_phase_event`
- Wire event emission in `aragora/debate/phases/consensus_phase.py:ConsensusPhase.run()` — Verify: `pytest tests/debate/test_consensus.py -v`

## Owner module / file paths
- `aragora/debate/orchestrator.py` (Arena class, run method)
- `aragora/events/schema.py` (PhaseEvent dataclass)
- `tests/debate/test_orchestrator.py` (new test_phase_events test)

(end of example — your output must follow this pattern with REAL paths from the REPOSITORY FILE REFERENCE above)

## YOUR TASK
Synthesize the debate into a single comprehensive answer that EXACTLY follows the output format above.

Critical rules:
- Use EXACTLY the required section headings as `## Heading` markdown headers, in the specified order.
- Each section must have **substantive content** — at least 2-3 specific, actionable items drawn from the debate.
- **PATH GROUNDING (CRITICAL)**: Every file path you mention MUST come from the REPOSITORY FILE REFERENCE at the top. Do NOT invent paths like `src/aragora/core/...` or `aragora/protocols/...` — these directories do not exist. The actual codebase uses `aragora/debate/`, `aragora/agents/`, `aragora/pipeline/`, etc. If you need a new file, mark it `NEW: aragora/existing_dir/new_file.py`.
- For "Ranked High-Level Tasks": EVERY task must include:
  - An action verb (add, create, implement, update, refactor, wire, test)
  - A real file path + class/function name (e.g., `aragora/debate/orchestrator.py:Arena.run()`)
  - A pytest command to verify (e.g., `pytest tests/debate/test_X.py::test_name -v`)
- For "Suggested Subtasks": Each must be independently testable with a specific pytest command.
- For "Owner module / file paths": reference ONLY paths from the REPOSITORY FILE REFERENCE above.
- For "Test Plan": each test item must reference a specific test file. Do NOT use generic phrases like "run unit tests".
- For "Gate Criteria": include specific thresholds with comparison operators + numbers (e.g., "coverage >= 80%", "error_rate < 1%"). Every criterion MUST contain a comparison operator.
- For "Rollback Plan": include explicit trigger conditions AND rollback actions.
- For "JSON Payload": produce valid JSON that mirrors the section content.
- Preserve DISSENT: if agents disagreed, note it in the relevant section.

## BAD vs GOOD (do NOT produce lines like the BAD examples)

BAD: "Improve the consensus detection system"
GOOD: "Update `aragora/debate/consensus.py:detect_consensus()` to emit convergence events — Verify: `pytest tests/debate/test_consensus.py -v`"

BAD: "Enhance error handling across the codebase"
GOOD: "Add circuit-breaker fallback in `aragora/resilience/circuit_breaker.py:CircuitBreaker.call()` with threshold >= 3 failures in 60s — Verify: `pytest tests/resilience/test_circuit_breaker.py -v`"

BAD: "Consider implementing better monitoring"
GOOD: "Wire `aragora/observability/metrics.py:emit_debate_metrics()` into `aragora/debate/orchestrator.py:Arena.run()` post-consensus — p95 latency <= 250ms — Verify: `pytest tests/observability/test_metrics.py -v`"
- Do NOT use placeholder text like TBD, TODO, "as needed", or "to be determined".

Write authoritatively. This is the FINAL WORD on this debate."""

    @staticmethod
    def _build_default_synthesis_prompt(task: str, proposals_text: str, critiques_text: str) -> str:
        """Build the default synthesis prompt when no output contract is present."""
        return f"""You are Claude Opus 4.5, tasked with creating the DEFINITIVE synthesis of this multi-agent AI debate.

## ORIGINAL QUESTION
{task}

## AGENT FINAL PROPOSALS
{proposals_text}

## KEY CRITIQUES
{critiques_text if critiques_text else "No critiques recorded."}

## YOUR TASK
Create a comprehensive synthesis of **approximately 1200 words** (minimum 1000, maximum 1400) that includes:

1. **DEFINITIVE ANSWER** (2-3 sentences): State the conclusion clearly and authoritatively

2. **REASONING SUMMARY** (~300 words): Present the key arguments and evidence that emerged from the debate. Identify the strongest reasoning chains.

3. **CONSENSUS ANALYSIS** (~200 words): Detail where agents agreed and areas of genuine disagreement. Note which disagreements were resolved and which remain.

4. **SYNTHESIS OF PERSPECTIVES** (~300 words): Integrate the strongest points from each agent's position. Show how different viewpoints complement or challenge each other.

5. **ACTIONABLE RECOMMENDATIONS** (~200 words): Provide concrete, practical takeaways. What should someone do with this conclusion?

6. **REMAINING QUESTIONS** (~100 words): Note any unresolved issues, edge cases, or areas that merit further exploration.

Write authoritatively. This is the FINAL WORD on this debate.
Your response MUST be approximately 1200 words to provide comprehensive coverage."""

    @staticmethod
    def concretize_output(synthesis: str, repo_hint: str) -> str:
        """Post-process synthesis to boost concreteness of vague lines.

        Rewrites task/subtask lines that lack file paths or test commands by
        injecting the closest matching path from the repo hint.  Runs before
        the quality gate so the synthesis gets a fair practicality score.
        """
        import re as _re

        if not synthesis or not repo_hint:
            return synthesis

        # Build a lookup from directory names to full paths from the hint.
        # Format: "  aragora/debate/: orchestrator.py, consensus.py, ..."
        dir_files: dict[str, list[str]] = {}
        for hint_line in repo_hint.splitlines():
            hint_line = hint_line.strip()
            if not hint_line or hint_line.startswith("Key repository"):
                continue
            parts = hint_line.split(":", 1)
            if len(parts) != 2:
                continue
            dir_path = parts[0].strip().rstrip("/")
            files = [f.strip() for f in parts[1].split(",") if f.strip()]
            if dir_path and files:
                dir_files[dir_path] = files

        if not dir_files:
            return synthesis

        # Build keyword → path index for quick lookup.
        keyword_to_path: dict[str, str] = {}
        for dir_path, files in dir_files.items():
            dir_name = dir_path.rsplit("/", 1)[-1] if "/" in dir_path else dir_path
            keyword_to_path[dir_name] = dir_path
            for f in files:
                stem = f.rsplit(".", 1)[0] if "." in f else f
                keyword_to_path[stem] = f"{dir_path}/{f}"

        # Patterns for sections where we want to concretize
        _TASK_SECTION_RE = _re.compile(
            r"(?i)^##\s+(?:ranked\s+high.level\s+tasks|suggested\s+subtasks|test\s+plan)",
        )
        _PATH_IN_LINE = _re.compile(r"(?:/?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+")
        _PYTEST_IN_LINE = _re.compile(r"(?i)\bpytest\b")
        _ACTION_VERB = _re.compile(
            r"(?i)\b(?:add|create|implement|update|refactor|wire|integrate|test|fix|extend"
            r"|improve|enhance|harden|validate|deploy|enable|configure|build|resolve)\b"
        )
        _NUMBERED_ITEM = _re.compile(r"^(\s*(?:\d+\.\s+|\-\s+|\*\s+))")

        lines = synthesis.split("\n")
        in_target_section = False
        result_lines: list[str] = []

        for line in lines:
            # Track which section we're in
            if line.startswith("##"):
                in_target_section = bool(_TASK_SECTION_RE.match(line))
                result_lines.append(line)
                continue

            if not in_target_section:
                result_lines.append(line)
                continue

            stripped = line.strip()
            # Only process bullet/numbered items
            if not stripped or not _NUMBERED_ITEM.match(stripped):
                result_lines.append(line)
                continue

            has_path = bool(_PATH_IN_LINE.search(stripped))
            has_pytest = bool(_PYTEST_IN_LINE.search(stripped))

            if has_path and has_pytest:
                # Already concrete enough
                result_lines.append(line)
                continue

            # Try to find a relevant path from keywords in the line
            words = _re.findall(r"\b[a-z_]{3,}\b", stripped.lower())
            best_path = None
            for word in words:
                if word in keyword_to_path:
                    best_path = keyword_to_path[word]
                    break

            if not best_path and not has_path:
                # Try partial match on longer words
                for word in words:
                    if len(word) >= 5:
                        for kw, path in keyword_to_path.items():
                            if word in kw or kw in word:
                                best_path = path
                                break
                    if best_path:
                        break

            augmented = stripped
            # Inject path if missing
            if not has_path and best_path:
                # Find the end of the action description (before any dash separator)
                if " — " in augmented:
                    parts = augmented.split(" — ", 1)
                    augmented = f"{parts[0]} in `{best_path}` — {parts[1]}"
                elif " - " in augmented and not augmented.startswith("- "):
                    idx = augmented.index(" - ", 2)
                    augmented = f"{augmented[:idx]} in `{best_path}`{augmented[idx:]}"
                else:
                    augmented = f"{augmented} — target: `{best_path}`"

            # Inject pytest command if missing and we have a path
            if not has_pytest:
                path_match = _PATH_IN_LINE.search(augmented)
                if path_match:
                    found_path = path_match.group(0)
                    # Derive test path from source path
                    if "tests/" in found_path:
                        test_path = found_path
                    elif found_path.endswith(".py"):
                        # aragora/debate/foo.py → tests/debate/test_foo.py
                        parts = found_path.split("/")
                        if len(parts) >= 2:
                            module = parts[-2] if parts[-1] != "__init__.py" else parts[-3]
                            fname = parts[-1]
                            test_path = f"tests/{module}/test_{fname}"
                        else:
                            test_path = None
                    else:
                        test_path = None

                    if test_path:
                        augmented = f"{augmented} — Verify: `pytest {test_path} -v`"

            # Preserve original indentation
            indent_match = _NUMBERED_ITEM.match(line)
            if indent_match and augmented != stripped:
                indent = line[: line.index(stripped)]
                result_lines.append(f"{indent}{augmented}")
            else:
                result_lines.append(line)

        return "\n".join(result_lines)


__all__ = ["SynthesisGenerator"]
