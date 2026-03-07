"""SwarmInterrogator: conversational requirement gathering for non-developers."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.harnesses.adapter import AnalysisType
from aragora.swarm.config import InterrogatorConfig
from aragora.swarm.spec import SwarmSpec

logger = logging.getLogger(__name__)

# Sentinel indicating Claude has enough information
SPEC_READY_MARKER = "SPEC_READY"

# Fixed fallback questions when Claude CLI is unavailable
FALLBACK_QUESTIONS = [
    "Tell me what you'd like to happen. What's the end result you're looking for?",
    "What's the problem this would solve? Why does it matter right now?",
    "Should this affect the whole system or just specific parts? Which ones?",
    "How will you know it worked? What does 'done' look like to you?",
    "Is there anything that should NOT be changed, or any budget limits to keep in mind?",
    "Based on what you've described, is there anything else we should tackle while we're at it?",
]

SPEC_EXTRACTION_PROMPT = """\
You are a CTO summarizing a conversation you just had with your CEO. \
Extract their requirements into a structured format your engineering team can use.

Conversation:
{conversation}

Produce a JSON object with these fields:
- "refined_goal": A clear 1-2 sentence goal statement (in plain language)
- "acceptance_criteria": Array of measurable success conditions
- "constraints": Array of things that must NOT change
- "track_hints": Array from ["sme", "developer", "self_hosted", "qa", "core", "security"] \
(pick the most relevant, or empty if unsure)
- "file_scope_hints": Array of file/directory paths mentioned (empty if none)
- "estimated_complexity": "low", "medium", or "high"
- "requires_approval": true if the user wants to review changes before they are applied
- "proactive_suggestions": Array of additional improvements you suggested during the conversation

Respond with ONLY the JSON object, no other text.
"""


class SwarmInterrogator:
    """Gathers requirements from a non-developer user via conversational Q&A.

    Uses Claude (via ClaudeCodeHarness in --print mode) to ask clarifying
    questions until enough information is gathered, then synthesizes the
    conversation into a structured SwarmSpec.

    Falls back to fixed questions if the Claude CLI is unavailable.
    """

    def __init__(self, config: InterrogatorConfig | None = None) -> None:
        self.config = config or InterrogatorConfig()
        self._conversation: list[dict[str, str]] = []
        self._harness: Any = None

    async def interrogate(
        self,
        initial_goal: str,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> SwarmSpec:
        """Run the interrogation loop.

        Args:
            initial_goal: The user's initial goal statement.
            input_fn: Function to get user input (default: builtin input).
            print_fn: Function to print output (default: builtin print).

        Returns:
            A SwarmSpec capturing the user's requirements.
        """
        _input = input_fn or input
        _print = print_fn or print

        self._conversation = [{"role": "user", "content": initial_goal}]

        _print("\n" + "=" * 60)
        _print("Let's figure out exactly what you need.")
        _print("=" * 60)
        _print(f"\nYour goal: {initial_goal}\n")

        harness = await self._get_harness()
        if harness is not None:
            await self._interrogate_with_llm(harness, _input, _print)
        elif self.config.fallback_to_fixed_questions:
            self._interrogate_with_fixed_questions(_input, _print)
        else:
            logger.warning("No Claude CLI available and fallback disabled")

        spec = await self._produce_spec(initial_goal, harness)

        _print("\n" + "-" * 60)
        _print("SPEC SUMMARY")
        _print("-" * 60)
        _print(spec.summary())
        _print("")

        return spec

    async def _interrogate_with_llm(
        self,
        harness: Any,
        _input: Any,
        _print: Any,
    ) -> None:
        """Run conversational interrogation using Claude."""
        conversation_text = f"User's initial goal: {self._conversation[0]['content']}"

        for turn in range(self.config.max_turns):
            prompt = (
                f"{self.config.system_prompt}\n\n"
                f"Conversation so far:\n{conversation_text}\n\n"
                "Ask your next clarifying question, or respond with "
                f"SPEC_READY if you have enough information."
            )

            try:
                result = await harness.analyze_repository(
                    repo_path=Path.cwd(),
                    analysis_type=AnalysisType.GENERAL,
                    prompt=prompt,
                )
                response = result.raw_output if hasattr(result, "raw_output") else str(result)
            except Exception:
                logger.warning("Claude interrogation failed, using fixed questions")
                remaining = FALLBACK_QUESTIONS[turn:]
                for q in remaining:
                    _print(f"\n{q}")
                    answer = self._safe_input(_input, "> ")
                    if answer is None:
                        return
                    self._conversation.append({"role": "assistant", "content": q})
                    self._conversation.append({"role": "user", "content": answer})
                return

            if SPEC_READY_MARKER in response:
                _print("\nI have enough information to proceed.\n")
                break

            # Extract the question from Claude's response
            question = response.strip()
            self._conversation.append({"role": "assistant", "content": question})

            _print(f"\n{question}")
            answer = self._safe_input(_input, "> ")
            if answer is None:
                break
            self._conversation.append({"role": "user", "content": answer})

            conversation_text += f"\nAssistant: {question}\nUser: {answer}"

    def _interrogate_with_fixed_questions(
        self,
        _input: Any,
        _print: Any,
    ) -> None:
        """Fallback: ask fixed questions when Claude is unavailable."""
        _print("(Using guided questions mode)\n")

        for question in FALLBACK_QUESTIONS:
            _print(f"\n{question}")
            answer = self._safe_input(_input, "> ")
            if answer is None:
                return
            if answer.strip():
                self._conversation.append({"role": "assistant", "content": question})
                self._conversation.append({"role": "user", "content": answer})

    async def _produce_spec(
        self,
        initial_goal: str,
        harness: Any,
    ) -> SwarmSpec:
        """Synthesize conversation into a SwarmSpec.

        Uses Claude to extract structured data from the conversation.
        Falls back to heuristic extraction if Claude is unavailable.
        """
        conversation_text = "\n".join(
            f"{msg['role'].title()}: {msg['content']}" for msg in self._conversation
        )

        spec_data: dict[str, Any] | None = None

        if harness is not None:
            try:
                prompt = SPEC_EXTRACTION_PROMPT.format(conversation=conversation_text)
                result = await harness.analyze_repository(
                    repo_path=Path.cwd(),
                    analysis_type=AnalysisType.GENERAL,
                    prompt=prompt,
                )
                raw = result.raw_output if hasattr(result, "raw_output") else str(result)
                spec_data = self._parse_json_from_response(raw)
            except Exception:
                logger.warning("LLM spec extraction failed, using heuristic")

        if spec_data is None:
            spec_data = self._heuristic_spec_extraction()

        return SwarmSpec(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            raw_goal=initial_goal,
            refined_goal=spec_data.get("refined_goal", initial_goal),
            acceptance_criteria=spec_data.get("acceptance_criteria", []),
            constraints=spec_data.get("constraints", []),
            budget_limit_usd=spec_data.get("budget_limit_usd"),
            track_hints=spec_data.get("track_hints", []),
            file_scope_hints=spec_data.get("file_scope_hints", []),
            estimated_complexity=spec_data.get("estimated_complexity", "medium"),
            requires_approval=spec_data.get("requires_approval", False),
            proactive_suggestions=spec_data.get("proactive_suggestions", []),
            interrogation_turns=len([m for m in self._conversation if m["role"] == "user"]),
            user_expertise=spec_data.get("user_expertise", "non-developer"),
        )

    def _parse_json_from_response(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from LLM response text."""
        # Try direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON block
        for start_marker in ["{", "```json\n", "```\n"]:
            start = text.find(start_marker)
            if start == -1:
                continue
            if start_marker.startswith("```"):
                start += len(start_marker)
            end = text.find("}", start)
            if end == -1:
                continue
            # Find the last closing brace
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _heuristic_spec_extraction(self) -> dict[str, Any]:
        """Extract spec data from conversation without LLM."""
        user_messages = [m["content"] for m in self._conversation if m["role"] == "user"]
        combined = " ".join(user_messages)

        # Simple heuristic: first message is the goal, rest is context
        refined_goal = user_messages[0] if user_messages else ""

        # Look for track keywords
        track_keywords = {
            "test": "qa",
            "security": "security",
            "sdk": "developer",
            "api": "developer",
            "dashboard": "sme",
            "ui": "sme",
            "deploy": "self_hosted",
            "docker": "self_hosted",
        }
        hints = []
        lower = combined.lower()
        for keyword, track in track_keywords.items():
            if keyword in lower and track not in hints:
                hints.append(track)

        return {
            "refined_goal": refined_goal,
            "acceptance_criteria": [],
            "constraints": [],
            "track_hints": hints,
            "file_scope_hints": [],
            "estimated_complexity": "medium",
            "requires_approval": False,
        }

    async def _get_harness(self) -> Any:
        """Try to initialize the Claude Code harness."""
        if self._harness is not None:
            return self._harness
        try:
            from aragora.harnesses.claude_code import ClaudeCodeHarness

            harness = ClaudeCodeHarness()
            if await harness.initialize():
                self._harness = harness
                return harness
        except (ImportError, Exception):
            pass
        return None

    @staticmethod
    def _safe_input(input_fn: Any, prompt: str) -> str | None:
        """Read one input safely, returning None on EOF/non-interactive stdin."""
        try:
            return input_fn(prompt)
        except EOFError:
            logger.info("Interrogation input ended early; proceeding with gathered context")
            return None
