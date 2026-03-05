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
            # Synthesis is the definitive final answer — always overwrite.
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
            # Synthesis is the definitive final answer — always overwrite.
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

            # Build synthesis prompt — split into system (format) and user (content)
            system_prompt, user_prompt = self._build_synthesis_prompt_parts(ctx)
            synthesizer.system_prompt = system_prompt

            # Generate synthesis with timeout (60s to fit within phase budget)
            # Pass user_prompt WITHOUT context_messages to avoid essay-pattern priming
            with streaming_task_context("synthesis-agent:opus_synthesis"):
                synthesis = await asyncio.wait_for(
                    synthesizer.generate(user_prompt),
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
                system_prompt, user_prompt = self._build_synthesis_prompt_parts(ctx)
                synthesizer.system_prompt = system_prompt
                with streaming_task_context("synthesis-agent-fallback:sonnet_synthesis"):
                    synthesis = await asyncio.wait_for(
                        synthesizer.generate(user_prompt),
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

    def _prepare_synthesis_parts(self, ctx: DebateContext) -> tuple[str, str, str, str]:
        """Extract task, proposals, critiques, and contract from context."""
        proposals = ctx.proposals
        critiques = getattr(ctx, "round_critiques", []) or getattr(ctx, "critiques", []) or []
        task = ctx.env.task if ctx.env else "Unknown task"

        proposals_text = "\n\n---\n\n".join(
            f"**{agent}**:\n{prop[:1500]}" for agent, prop in proposals.items()
        )

        critiques_text = ""
        if critiques:
            critique_items = []
            for c in critiques[:5]:
                if hasattr(c, "agent") and hasattr(c, "target"):
                    summary = getattr(c, "summary", "")[:200] if hasattr(c, "summary") else ""
                    critique_items.append(f"- {c.agent} on {c.target}: {summary}")
            critiques_text = "\n".join(critique_items)

        contract_block = self._extract_contract_block(ctx)
        if not contract_block:
            contract_block = self._default_output_contract()

        return task, proposals_text, critiques_text, contract_block

    def _build_synthesis_prompt(self, ctx: DebateContext) -> str:
        """Build prompt for final synthesis generation (single string).

        For backwards compatibility. Prefer _build_synthesis_prompt_parts
        which separates system and user content.
        """
        task, proposals_text, critiques_text, contract_block = self._prepare_synthesis_parts(ctx)
        system, user = self._build_contract_guided_prompt(
            task, proposals_text, critiques_text, contract_block
        )
        return f"{system}\n\n{user}"

    def _build_synthesis_prompt_parts(self, ctx: DebateContext) -> tuple[str, str]:
        """Build synthesis prompt as (system_prompt, user_prompt) tuple.

        Separates format constraints (system) from debate content (user)
        so the model treats structural requirements as instructions, not
        just another part of the conversation.
        """
        task, proposals_text, critiques_text, contract_block = self._prepare_synthesis_parts(ctx)
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
    ) -> tuple[str, str]:
        """Build synthesis prompt as (system_prompt, user_prompt) tuple.

        System prompt contains format constraints and repo paths.
        User prompt contains debate content to synthesize.
        """
        repo_hint = self._get_repo_path_hint()
        repo_section = (
            f"\nREPOSITORY FILE REFERENCE (use ONLY these paths — do NOT invent paths):\n{repo_hint}"
            if repo_hint
            else ""
        )

        system = f"""You are a structured action plan writer. You convert debate analysis into executable action plans.

CRITICAL OUTPUT FORMAT — NON-NEGOTIABLE:

Your ENTIRE output must use EXACTLY these 7 section headers in order.
Do NOT write prose, essays, analysis, preamble, or commentary.
Your VERY FIRST output token must be: ## Ranked High-Level Tasks

Required headers (in this exact order, using ## markdown):
1. ## Ranked High-Level Tasks
2. ## Suggested Subtasks
3. ## Owner module / file paths
4. ## Test Plan
5. ## Rollback Plan
6. ## Gate Criteria
7. ## JSON Payload

VIOLATIONS (any of these = failure):
- Writing ANY text before "## Ranked High-Level Tasks"
- Adding extra ## headers (no "## Summary", "## Analysis", "## Recommendation", "## Preamble")
- Putting placeholder text like "[Section not produced]", "TBD", "TODO"
- Inventing file paths not in REPOSITORY FILE REFERENCE
- Writing vague lines like "Improve X" — use specific actions like "Add validation to `path/file.py:function()`"

EVERY task line must include: action verb + real file path + pytest verify command.
{repo_section}

{contract_block}

EXAMPLE (follow this exact style):

## Ranked High-Level Tasks
1. **Refactor `aragora/debate/orchestrator.py:Arena.run()` to emit phase-transition events** — Verify: `pytest tests/debate/test_orchestrator.py -v`
2. **Update `aragora/debate/consensus.py:detect_consensus()` to weight by evidence quality** — Verify: `pytest tests/debate/test_consensus.py -v`

## Suggested Subtasks
- Add `PhaseEvent` dataclass to `aragora/events/schema.py` — Verify: `pytest tests/events/test_schema.py -v`

## Owner module / file paths
- `aragora/debate/orchestrator.py`
- `aragora/events/schema.py`

(continue with Test Plan, Rollback Plan, Gate Criteria, JSON Payload)"""

        user = f"""Extract actionable items from this debate and produce the structured action plan.
Do NOT reproduce the proposals as prose. EXTRACT specific actions, file paths, and test commands.

QUESTION: {task}

AGENT PROPOSALS:
{proposals_text}

CRITIQUES:
{critiques_text if critiques_text else "No critiques recorded."}

Remember: Start your response with ## Ranked High-Level Tasks — no preamble."""

        return system, user

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
        """Post-process synthesis to add pytest verify commands to lines that have paths.

        Only adds pytest commands to lines that already contain a file path but
        lack a test command.  Does NOT inject paths into lines that don't have
        them — that would be fabricating specificity the LLM didn't produce.
        """
        import re as _re

        if not synthesis or not repo_hint:
            return synthesis

        _TASK_SECTION_RE = _re.compile(
            r"(?i)^#{2,3}\s+(?:ranked\s+high.level\s+tasks|suggested\s+subtasks|test\s+plan)",
        )
        _PATH_IN_LINE = _re.compile(r"(?:/?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+")
        _PYTEST_IN_LINE = _re.compile(r"(?i)\bpytest\b")
        _NUMBERED_ITEM = _re.compile(r"^(\s*(?:\d+\.\s+|\-\s+|\*\s+))")

        lines = synthesis.split("\n")
        in_target_section = False
        result_lines: list[str] = []

        for line in lines:
            if line.startswith("##"):
                in_target_section = bool(_TASK_SECTION_RE.match(line))
                result_lines.append(line)
                continue

            if not in_target_section:
                result_lines.append(line)
                continue

            stripped = line.strip()
            if not stripped or not _NUMBERED_ITEM.match(stripped):
                result_lines.append(line)
                continue

            has_path = bool(_PATH_IN_LINE.search(stripped))
            has_pytest = bool(_PYTEST_IN_LINE.search(stripped))

            # Only add pytest command if line already has a path but lacks one
            if has_path and not has_pytest:
                path_match = _PATH_IN_LINE.search(stripped)
                if path_match:
                    found_path = path_match.group(0)
                    test_path = None
                    if "tests/" in found_path:
                        test_path = found_path
                    elif found_path.endswith(".py"):
                        parts = found_path.split("/")
                        if len(parts) >= 2:
                            module = parts[-2] if parts[-1] != "__init__.py" else parts[-3]
                            fname = parts[-1]
                            test_path = f"tests/{module}/test_{fname}"

                    if test_path:
                        indent = line[: line.index(stripped)]
                        result_lines.append(f"{indent}{stripped} — Verify: `pytest {test_path} -v`")
                        continue

            result_lines.append(line)

        return "\n".join(result_lines)


__all__ = ["SynthesisGenerator"]
