"""Debate-based decomposition for abstract, high-level goals.

``TaskDecomposer`` (``aragora.nomic.task_decomposer``) inherits these methods: it runs an
Arena debate (with OpenRouter fallback agents) to turn goals such as "Maximize utility for
SME businesses" into concrete subtasks. Import the decomposer from
``aragora.nomic.task_decomposer``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from aragora.config import get_api_key
from aragora.nomic.task_decomposer_models import SubTask, TaskDecomposition

if TYPE_CHECKING:
    from aragora.core import DebateResult, Environment
    from aragora.nomic.task_decomposer import DecomposerConfig

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.task_decomposer" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.task_decomposer")


class TaskDecomposerDebateMixin:
    """Debate-driven goal decomposition inherited by ``TaskDecomposer``."""

    config: DecomposerConfig

    if TYPE_CHECKING:

        def analyze(
            self,
            task_description: str,
            debate_result: DebateResult | None = None,
            depth: int = 0,
            *,
            file_scope_hints: list[str] | None = None,
            acceptance_criteria: list[str] | None = None,
            constraints: list[str] | None = None,
        ) -> TaskDecomposition: ...

        def _create_generic_phases(self, task: str) -> list[SubTask]: ...

        def _ground_to_codebase(self, goal: str, repo_root: str | None = None) -> str: ...

    async def analyze_with_debate(
        self,
        goal: str,
        agents: list[Any] | None = None,
        context: str = "",
        depth: int = 0,
    ) -> TaskDecomposition:
        """Analyze an abstract goal using multi-agent debate.

        Uses Arena debate to decompose high-level goals like "Maximize utility
        for SME businesses" into concrete, actionable subtasks. Multiple agents
        debate what improvements would best serve the goal and reach consensus.

        This is more powerful than heuristic decomposition for abstract goals
        but uses more tokens and takes longer.

        Args:
            goal: High-level goal to decompose (can be abstract)
            agents: Optional list of agents to use in debate. If not provided,
                   will use default API agents.
            context: Optional additional context about the codebase or project
            depth: Current recursion depth (0 = top-level)

        Returns:
            TaskDecomposition with debate-derived subtasks

        Example:
            decomposer = TaskDecomposer()
            result = await decomposer.analyze_with_debate(
                "Maximize utility for SME businesses"
            )
            for subtask in result.subtasks:
                print(f"  - {subtask.title}: {subtask.description}")
        """
        # Enforce depth limit
        if depth >= self.config.max_depth:
            logger.info(
                "debate_decomposition_depth_limit depth=%s max=%s", depth, self.config.max_depth
            )
            return self.analyze(goal, depth=self.config.max_depth)
        from aragora.core import Environment
        from aragora.protocols.debate import DebateProtocol

        # Build the debate task - ask agents to decompose the goal
        debate_task = self._build_debate_task(goal, context)

        # Get agents if not provided
        if agents is None:
            agents = await self._get_default_agents()

        # Configure debate protocol for decomposition with Trickster
        # and convergence detection for higher-quality consensus
        protocol = DebateProtocol(
            rounds=self.config.debate_rounds,
            consensus="majority",
            timeout_seconds=self.config.debate_timeout,
            enable_trickster=self.config.enable_trickster,
            trickster_sensitivity=self.config.trickster_sensitivity,
            convergence_detection=self.config.enable_convergence,
        )

        # Create environment
        env = Environment(
            task=debate_task,
            context=context,
            max_rounds=self.config.debate_rounds,
            require_consensus=True,
            consensus_threshold=0.6,
        )

        logger.info("debate_decomposition_started goal=%s...", goal[:50])

        # Try to run debate, with OpenRouter fallback on API errors
        result = await self._run_debate_with_fallback(env, agents, protocol, goal, context)

        if result is None:
            # All attempts failed, fall back to heuristic
            logger.warning("debate_decomposition_all_failed falling back to heuristic")
            return self.analyze(goal, depth=depth)

        # Parse subtasks from final answer (consensus text)
        subtasks = self._parse_debate_subtasks(result.final_answer or "")

        if not subtasks:
            logger.warning("debate_decomposition_empty falling back to heuristic")
            subtasks = self._create_generic_phases(goal)

        logger.info(
            "debate_decomposition_completed subtasks=%s confidence=%.2f",
            len(subtasks),
            result.confidence,
        )

        return TaskDecomposition(
            original_task=goal,
            complexity_score=8,  # Debate implies high complexity
            complexity_level="high",
            should_decompose=True,
            subtasks=subtasks[: self.config.max_subtasks],
            rationale=f"Debate decomposition (confidence={result.confidence:.2f}): "
            + (result.final_answer or "")[:200],
        )

    async def _run_debate_with_fallback(
        self,
        env: Environment,
        agents: list[Any],
        protocol: Any,
        goal: str,
        context: str,
    ) -> Any | None:
        """Run debate with OpenRouter fallback on API errors or poor output.

        The fallback triggers when:
        1. AgentAPIError, AgentRateLimitError, or similar billing errors occur
        2. The debate returns but the output doesn't contain valid subtasks

        Returns:
            DebateResult if successful with valid subtasks, None if all attempts failed
        """
        from aragora.agents.errors.exceptions import (
            AgentAPIError,
            AgentError,
            AgentRateLimitError,
        )
        from aragora.debate.orchestrator import Arena

        result = None
        should_fallback = False
        fallback_reason = ""

        # First attempt with provided agents
        try:
            arena = Arena(env, agents, protocol)
            result = await arena.run()

            # Check if the result has valid, parseable subtasks
            if result and result.final_answer:
                subtasks = self._parse_debate_subtasks(result.final_answer)
                if subtasks:
                    logger.info(
                        "debate_primary_succeeded subtasks=%s confidence=%.2f",
                        len(subtasks),
                        result.confidence,
                    )
                    return result
                else:
                    # Debate completed but output is not useful
                    should_fallback = True
                    fallback_reason = "output has no parseable subtasks"
            else:
                should_fallback = True
                fallback_reason = "no final answer"

        except AgentRateLimitError as e:
            should_fallback = True
            fallback_reason = f"rate limit: {e}"
        except AgentAPIError as e:
            error_msg = str(e).lower()
            # Check for billing/quota errors that warrant fallback
            if any(
                keyword in error_msg
                for keyword in [
                    "credit",
                    "balance",
                    "quota",
                    "rate limit",
                    "billing",
                    "insufficient",
                ]
            ):
                should_fallback = True
                fallback_reason = f"billing error: {e}"
            else:
                # Other API errors might not benefit from fallback
                logger.exception("debate_api_error error=%s", e)
                return None
        except AgentError as e:
            # Generic agent error - try fallback
            should_fallback = True
            fallback_reason = f"agent error: {e}"
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            # Check if exception message indicates billing/API issues
            error_msg = str(e).lower()
            if any(
                keyword in error_msg
                for keyword in [
                    "credit",
                    "balance",
                    "quota",
                    "rate limit",
                    "billing",
                    "insufficient",
                    "401",
                    "403",
                ]
            ):
                should_fallback = True
                fallback_reason = f"api error: {e}"
            else:
                logger.exception("debate_failed error=%s", e)
                return None

        if not should_fallback:
            return result

        # Fallback: try with OpenRouter agents
        logger.warning("debate_fallback_triggered reason=%s", fallback_reason)

        try:
            fallback_agents = await self._get_openrouter_agents()
            if not fallback_agents:
                logger.warning("debate_no_fallback_agents OpenRouter not available")
                # Return original result if we have one (better than nothing)
                return result

            logger.info("debate_fallback_started agents=%s", len(fallback_agents))

            # Rebuild environment and protocol for fresh debate
            from aragora.core import Environment
            from aragora.protocols.debate import DebateProtocol

            fallback_env = Environment(
                task=self._build_debate_task(goal, context),
                context=context,
                max_rounds=self.config.debate_rounds,
                require_consensus=True,
                consensus_threshold=0.6,
            )
            fallback_protocol = DebateProtocol(
                rounds=self.config.debate_rounds,
                consensus="majority",
                timeout_seconds=self.config.debate_timeout,
                enable_trickster=self.config.enable_trickster,
                trickster_sensitivity=self.config.trickster_sensitivity,
                convergence_detection=self.config.enable_convergence,
            )

            arena = Arena(fallback_env, fallback_agents, fallback_protocol)
            fallback_result = await arena.run()

            # Check if fallback result is better
            if fallback_result and fallback_result.final_answer:
                subtasks = self._parse_debate_subtasks(fallback_result.final_answer)
                if subtasks:
                    logger.info(
                        "debate_fallback_succeeded subtasks=%s confidence=%.2f",
                        len(subtasks),
                        fallback_result.confidence,
                    )
                    return fallback_result

            logger.warning("debate_fallback_no_subtasks returning original result")
            return result or fallback_result

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.exception("debate_fallback_failed error=%s", e)
            # Return original result if we have one
            return result

    async def _get_openrouter_agents(self) -> list[Any]:
        """Get OpenRouter agents for fallback."""
        openrouter_key = get_api_key("OPENROUTER_API_KEY", required=False)
        if not openrouter_key:
            return []

        try:
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            return [
                OpenRouterAgent(
                    name="or-claude",
                    model="anthropic/claude-opus-5",
                    api_key=openrouter_key,
                ),
                OpenRouterAgent(
                    name="or-gpt",
                    model="openai/gpt-5.4",
                    api_key=openrouter_key,
                ),
            ]
        except (ImportError, RuntimeError, OSError) as e:
            logger.warning("openrouter_agents_failed error=%s", e)
            return []

    def _build_debate_task(self, goal: str, context: str = "") -> str:
        """Build the debate task prompt for goal decomposition."""
        # Dynamically scan relevant codebase directories instead of hardcoding
        codebase_context = self._ground_to_codebase(goal)
        user_context = f"\n\nAdditional Context:\n{context}" if context else ""

        return f"""Decompose this high-level goal into 3-5 concrete, actionable subtasks.

GOAL: {goal}
{codebase_context}{user_context}

For each subtask, provide:
1. A clear title (2-5 words)
2. A specific description of what needs to be done
3. Estimated complexity (low/medium/high)
4. Files or areas likely affected (use ACTUAL aragora paths, NOT src/)
5. Dependencies on other subtasks (if any)

Format your response as a JSON array:
```json
[
  {{
    "title": "Subtask Title",
    "description": "Specific description of what to implement",
    "complexity": "medium",
    "files": ["aragora/path/to/file.py", "aragora/live/src/file.tsx"],
    "dependencies": []
  }},
  ...
]
```

Focus on:
- Concrete, implementable tasks (not abstract goals)
- Clear boundaries between subtasks
- Parallelizable work where possible
- Use the ACTUAL aragora file paths shown above

Prioritize by impact: which improvements would provide the most value?"""

    def _parse_debate_subtasks(self, consensus_text: str) -> list[SubTask]:
        """Parse subtasks from debate consensus text."""
        subtasks: list[SubTask] = []

        # Try to extract JSON from the consensus
        json_match = re.search(r"```json\s*([\s\S]*?)\s*```", consensus_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON array directly
            json_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", consensus_text)
            if json_match:
                json_str = json_match.group(0)
            else:
                logger.debug("No JSON found in debate consensus")
                return subtasks

        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, list):
                parsed = [parsed]

            for i, item in enumerate(parsed):
                if not isinstance(item, dict):
                    continue

                subtasks.append(
                    SubTask(
                        id=f"subtask_{i + 1}",
                        title=item.get("title", f"Subtask {i + 1}"),
                        description=item.get("description", ""),
                        dependencies=item.get("dependencies", []),
                        estimated_complexity=item.get("complexity", "medium"),
                        file_scope=item.get("files", []),
                    )
                )

        except json.JSONDecodeError as e:
            logger.debug("Failed to parse debate JSON: %s", e)

        return subtasks

    async def _get_default_agents(self) -> list[Any]:
        """Get default agents for debate decomposition.

        Uses aragora.config.secrets to load API keys from AWS Secrets Manager
        or environment variables.
        """
        from aragora.config.secrets import get_secret
        from aragora.agents.api_agents.base import APIAgent

        agents: list[APIAgent] = []
        errors: list[str] = []

        # Try Anthropic agents first (pass API key explicitly)
        anthropic_key = get_secret("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

                agents.extend(
                    [
                        AnthropicAPIAgent(
                            name="claude-strategist",
                            model="claude-opus-5",
                            api_key=anthropic_key,
                        ),
                        AnthropicAPIAgent(
                            name="claude-architect",
                            model="claude-opus-5",
                            api_key=anthropic_key,
                        ),
                    ]
                )
            except (ImportError, RuntimeError, OSError) as e:
                errors.append(f"Anthropic: {e}")

        # Try OpenAI agents (pass API key explicitly)
        openai_key = get_secret("OPENAI_API_KEY")
        if openai_key:
            try:
                from aragora.agents.api_agents.openai import OpenAIAPIAgent

                agents.append(
                    OpenAIAPIAgent(name="gpt-analyst", model="gpt-4o", api_key=openai_key)
                )
            except (ImportError, RuntimeError, OSError) as e:
                errors.append(f"OpenAI: {e}")

        # Try OpenRouter as fallback (pass API key explicitly)
        openrouter_key = get_secret("OPENROUTER_API_KEY")
        if not agents and openrouter_key:
            try:
                from aragora.agents.api_agents.openrouter import OpenRouterAgent

                # OpenRouterAgent uses OPENROUTER_API_KEY from environment
                agents.extend(
                    [
                        OpenRouterAgent(
                            name="or-claude",
                            model="anthropic/claude-opus-5",
                        ),
                        OpenRouterAgent(
                            name="or-gpt",
                            model="openai/gpt-5.4",
                        ),
                    ]
                )
            except (ImportError, RuntimeError, OSError) as e:
                errors.append(f"OpenRouter: {e}")

        if not agents:
            raise RuntimeError(
                "No API agents available for debate decomposition.\n"
                "Required: ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY\n"
                "For AWS Secrets Manager: set ARAGORA_USE_SECRETS_MANAGER=true\n"
                f"Errors: {'; '.join(errors) if errors else 'No API keys found'}"
            )

        logger.info("debate_agents_loaded count=%s", len(agents))
        return agents


__all__ = ["TaskDecomposerDebateMixin"]
