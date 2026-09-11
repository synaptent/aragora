"""
Base utilities for creating agents.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


__all__ = [
    "CritiqueMixin",
    "BaseDebateAgent",
    "AgentType",
    "create_agent",
    "list_available_agents",
    "MAX_CONTEXT_CHARS",
    "MAX_MESSAGE_CHARS",
]

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from aragora.core import Agent, Critique, Message
from aragora.core_types import AgentRole

if TYPE_CHECKING:
    from aragora.agents.api_agents import APIAgent
    from aragora.agents.cli_agents import CLIAgent

    # Type alias for agent instances - note: Agent already imported above from aragora.core
    AgentInstance: TypeAlias = APIAgent | CLIAgent


# Context window limits (in characters, ~4 chars per token)
# Use 60% of available window to leave room for response
MAX_CONTEXT_CHARS = 120_000  # ~30k tokens, safe for most models
MAX_MESSAGE_CHARS = 20_000  # Individual message truncation limit


class BaseDebateAgent(Agent):
    """Base class for specialized debate agents.

    Extends the core Agent class with additional functionality
    for persona-based debate participation. Used by email agents,
    specialized domain agents, and other custom agent implementations.

    Provides stub implementations for abstract methods from Agent,
    allowing subclasses to focus on specialized analysis methods
    without requiring LLM integration.
    """

    persona: str = ""
    focus: str = ""

    def __init__(
        self,
        name: str = "agent",
        model: str = "default",
        role: AgentRole = "proposer",
        persona: str = "",
        focus: str = "",
        system_prompt: str = "",
    ):
        """Initialize a base debate agent.

        Args:
            name: Agent name
            model: Model identifier (default: "default" for non-LLM agents)
            role: Role in debate (proposer, critic, synthesizer, judge)
            persona: Character/style description for the agent
            focus: Specific area of focus for analysis
            system_prompt: Optional system prompt for the agent
        """
        super().__init__(name=name, model=model, role=role)
        self.persona = persona or self.persona
        self.focus = focus or self.focus
        if system_prompt:
            self.system_prompt = system_prompt

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response - stub implementation for specialized agents.

        Subclasses that need LLM generation should override this method.
        Non-LLM agents use specialized analysis methods instead.

        Args:
            prompt: The prompt to generate a response for
            context: Optional list of previous messages

        Returns:
            Empty string (stub implementation)
        """
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal - stub implementation for specialized agents.

        Subclasses that need critique functionality should override this method.
        Non-LLM agents use specialized analysis methods instead.

        Args:
            proposal: The proposal/response to critique
            task: The task or question being addressed
            context: Optional conversation context
            target_agent: Name of the agent whose proposal is being critiqued

        Returns:
            A minimal Critique object (stub implementation)
        """
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200] if proposal else "",
            issues=[],
            suggestions=[],
            severity=5.0,
            reasoning="Stub critique - this agent uses specialized analysis methods",
        )


class CritiqueMixin:
    """Mixin providing shared critique parsing and context building methods.

    Used by both CLIAgent and APIAgent to avoid code duplication.
    """

    # Required attributes (provided by subclasses)
    name: str

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: Callable[[str], str] | None = None,
    ) -> str:
        """Build context from previous messages.

        Args:
            context: List of previous messages
            truncate: Whether to truncate long messages/context (CLI agents should use True)
            sanitize_fn: Optional function to sanitize content (for CLI safety)

        Returns:
            Formatted context string
        """
        if not context:
            return ""

        if not truncate:
            # Simple mode (API agents) - no truncation
            context_str = "\n\n".join(
                [f"[Round {m.round}] {m.role} ({m.agent}):\n{m.content}" for m in context[-10:]]
            )
            return f"\n\nPrevious discussion:\n{context_str}\n\n"

        # Truncation mode (CLI agents) - handle large contexts
        messages = []
        total_chars = 0

        for m in context[-10:]:
            content = m.content
            if sanitize_fn:
                content = sanitize_fn(content)

            # Truncate individual messages that are too long
            if len(content) > MAX_MESSAGE_CHARS:
                half = MAX_MESSAGE_CHARS // 2 - 50
                content = (
                    content[:half]
                    + f"\n\n[... {len(m.content) - MAX_MESSAGE_CHARS} chars truncated ...]\n\n"
                    + content[-half:]
                )

            msg_str = f"[Round {m.round}] {m.role} ({m.agent}):\n{content}"

            # Check if adding this message would exceed total limit
            if total_chars + len(msg_str) > MAX_CONTEXT_CHARS:
                remaining = MAX_CONTEXT_CHARS - total_chars - 100
                if remaining > 500:
                    msg_str = msg_str[:remaining] + "\n[... truncated ...]"
                    messages.append(msg_str)
                break

            messages.append(msg_str)
            total_chars += len(msg_str) + 4

        context_str = "\n\n".join(messages)
        return f"\n\nPrevious discussion:\n{context_str}\n\n"

    def _parse_critique(self, response: str, target_agent: str, target_content: str) -> Critique:
        """Parse a critique response into structured format.

        Extracts issues, suggestions, and severity from natural language critique.
        """
        issues = []
        suggestions = []
        severity = 5.0  # Default to middle of 0-10 scale
        reasoning = ""

        lines = response.split("\n")
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            lower = line.lower()
            if "issue" in lower or "problem" in lower or "concern" in lower:
                current_section = "issues"
            elif "suggest" in lower or "recommend" in lower or "improvement" in lower:
                current_section = "suggestions"
            elif "severity" in lower:
                match = re.search(r"(\d+\.?\d*)", line)
                if match:
                    try:
                        raw_severity = float(match.group(1))
                        # Normalize to 0-10 scale
                        if raw_severity <= 1.0:
                            # Given as 0-1 scale, convert to 0-10
                            raw_severity = raw_severity * 10.0
                        severity = min(10.0, max(0.0, raw_severity))
                    except (ValueError, TypeError) as e:
                        logger.debug("Failed to parse numeric value: %s", e)
            elif line.startswith(("-", "*", "•")):
                item = line.lstrip("-*• ").strip()
                if current_section == "issues":
                    issues.append(item)
                elif current_section == "suggestions":
                    suggestions.append(item)
                else:
                    # Default to issues
                    issues.append(item)

        # If no structured extraction, use the whole response
        if not issues and not suggestions:
            sentences = [s.strip() for s in response.replace("\n", " ").split(".") if s.strip()]
            mid = len(sentences) // 2
            if sentences:
                issues = sentences[:mid]
                suggestions = sentences[mid:] if len(sentences) > mid else []
            else:
                # No sentences found - use full response as single issue
                # This preserves content instead of showing unhelpful placeholder
                full_response = response.strip()
                issues = [full_response] if full_response else ["Agent response was empty"]
                suggestions = []
            reasoning = response[:500]
        else:
            reasoning = response[:500]

        return Critique(
            agent=self.name,
            target_agent=target_agent,
            target_content=target_content[:200],
            issues=issues[:5],  # Limit to 5 issues
            suggestions=suggestions[:5],  # Limit to 5 suggestions
            severity=severity,
            reasoning=reasoning,
        )


AgentType = Literal[
    # Built-in
    "demo",
    # CLI-based
    "codex",
    "claude",
    "openai",
    "gemini-cli",
    "grok-cli",
    "qwen-cli",
    "deepseek-cli",
    "kilocode",
    # API-based (direct)
    "gemini",
    "ollama",
    "anthropic-api",
    "openai-api",
    "grok",
    # API-based (via OpenRouter)
    "deepseek",
    "deepseek-r1",
    "llama",
    "mistral",
    "qwen",
    "qwen-max",
    "kimi",
    "kimi-thinking",
    "llama4-maverick",
    "llama4-scout",
    "sonar",
    "command-r",
    "jamba",
    "openrouter",
]


def create_agent(
    model_type: AgentType,
    name: str | None = None,
    role: str = "proposer",
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    enable_fallback: bool | None = None,
) -> Agent:
    """
    Factory function to create agents by type.

    Uses the AgentRegistry for type lookup. All agent types are registered
    via decorators in cli_agents.py and api_agents.py.

    Args:
        model_type: Type of agent to create (see AgentRegistry.list_all())
        name: Agent name (defaults to model_type)
        role: Agent role ("proposer", "critic", "synthesizer")
        model: Specific model to use (optional)
        api_key: API key for API-based agents (optional, uses env vars)
        enable_fallback: Enable OpenRouter fallback on quota errors (None = use config)

    Returns:
        Agent instance (either CLIAgent or APIAgent)

    Raises:
        ValueError: If model_type is not registered
    """
    from aragora.agents.registry import AgentRegistry, register_all_agents

    # Ensure all agents are registered (imports trigger decorators)
    register_all_agents()

    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if enable_fallback is not None:
        kwargs["enable_fallback"] = enable_fallback

    return AgentRegistry.create(
        model_type=model_type,
        name=name,
        role=role,
        model=model,
        api_key=api_key,
        **kwargs,
    )


def list_available_agents() -> dict[str, dict[str, Any]]:
    """List all available agent types and their requirements.

    Returns:
        Dict mapping agent type names to their specifications
    """
    from aragora.agents.registry import AgentRegistry, register_all_agents

    # Ensure all agents are registered
    register_all_agents()

    return AgentRegistry.list_all()
