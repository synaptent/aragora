"""
Tinker API agent for fine-tuned open-source LLMs.

Uses models fine-tuned on Aragora debate data via the Tinker API
(thinkingmachines.ai).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, TypeVar
from collections.abc import AsyncIterator, Coroutine

from aragora.agents.api_agents.base import APIAgent
from aragora.agents.registry import AgentRegistry
from aragora.core import Critique, Message
from aragora.core_types import AgentRole
from aragora.training.tinker_client import TinkerClient, TinkerConfig, TinkerModel

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _run_async_in_thread(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine in a thread-safe manner.

    Creates a new event loop for the thread to avoid RuntimeError when
    asyncio.run() is called from within a ThreadPoolExecutor.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@AgentRegistry.register(
    "tinker",
    default_model="llama-3.3-70b",
    default_name="tinker",
    agent_type="API",
    env_vars="TINKER_API_KEY",
    accepts_api_key=True,
)
class TinkerAgent(APIAgent):
    """
    Agent using Aragora fine-tuned models via Tinker API.

    Supports both base models and fine-tuned adapters trained on
    Aragora debate data (SFT, DPO, adversarial).

    Example:
        # Use base model
        agent = TinkerAgent(name="tinker-base")

        # Use fine-tuned adapter
        agent = TinkerAgent(
            name="tinker-security",
            model_id="aragora-security-v1",
            adapter="security-expert",
        )
    """

    # Available base models
    SUPPORTED_MODELS = {
        "llama-3.3-70b": TinkerModel.LLAMA_3_3_70B,
        "llama-3.1-8b": TinkerModel.LLAMA_3_1_8B,
        "qwen-2.5-72b": TinkerModel.QWEN_2_5_72B,
        "qwen-3-32b": TinkerModel.QWEN_3_32B,
        "deepseek-v3": TinkerModel.DEEPSEEK_V3,
        "deepseek-r1": TinkerModel.DEEPSEEK_R1,
    }

    def __init__(
        self,
        name: str = "tinker",
        model: str = "llama-3.3-70b",
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        model_id: str | None = None,
        adapter: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """
        Initialize TinkerAgent.

        Args:
            name: Agent name
            model: Base model (llama-3.3-70b, qwen-2.5-72b, etc.)
            role: Agent role (proposer, critic, judge)
            timeout: Request timeout in seconds
            api_key: Tinker API key (or use TINKER_API_KEY env var)
            model_id: Specific fine-tuned model ID to use
            adapter: Name of LoRA adapter to apply
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        """
        resolved_api_key = api_key or os.getenv("TINKER_API_KEY") or ""
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=resolved_api_key,
            temperature=temperature,
        )
        self.agent_type = "tinker"
        self.model_id = model_id
        self.adapter = adapter
        self.max_tokens = max_tokens

        # Tinker client (lazy initialized)
        self._client: TinkerClient | None = None
        self._config = TinkerConfig(
            api_key=resolved_api_key,
            base_model=model,
            timeout=float(timeout),
        )

    @property
    def client(self) -> TinkerClient:
        """Get or create Tinker client."""
        if self._client is None:
            self._client = TinkerClient(self._config)
        return self._client

    async def close(self) -> None:
        """Close the Tinker client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response to a prompt (implements Agent.generate).

        This is the async method required by the Agent abstract base class.
        It delegates to the respond() method which contains the actual
        implementation logic.

        Args:
            prompt: The prompt to generate a response for
            context: Optional previous messages for context

        Returns:
            Generated response text
        """
        return await self.respond(prompt, context)

    def generate_sync(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response synchronously (blocking).

        This is a synchronous wrapper around generate() for use cases where
        async/await is not available. Creates a new event loop to run the
        async method.

        Args:
            prompt: The prompt to generate a response for
            context: Optional previous messages for context

        Returns:
            Generated response text
        """
        return _run_async_in_thread(self.respond(prompt, context))

    async def respond(
        self,
        task: str,
        context: list[Message] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """
        Generate a response to the task.

        Args:
            task: The debate task/prompt
            context: Previous messages in the debate
            system_prompt: Optional system prompt override

        Returns:
            Generated response text
        """
        # Build the full prompt
        prompt = self._build_prompt(task, context, system_prompt)

        try:
            # Generate response via Tinker API
            response = await self.client.sample(
                prompt=prompt,
                model_id=self.model_id,
                max_tokens=self.max_tokens,
                temperature=self.temperature or 0.7,
            )

            # Track token usage (estimate based on response length)
            # Tinker API should return actual usage, but estimate for now
            tokens_in = len(prompt.split()) * 1.3  # Rough estimate
            tokens_out = len(response.split()) * 1.3
            self._record_token_usage(int(tokens_in), int(tokens_out))

            return response.strip()

        except (OSError, ValueError, RuntimeError, TimeoutError) as e:
            logger.error("Tinker API error for %s: %s", self.name, e)

            # Circuit breaker handling
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()

            raise

    async def respond_stream(
        self,
        task: str,
        context: list[Message] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response to the task.

        Args:
            task: The debate task/prompt
            context: Previous messages in the debate
            system_prompt: Optional system prompt override

        Yields:
            Generated text chunks
        """
        prompt = self._build_prompt(task, context, system_prompt)

        try:
            async for chunk in self.client.sample_stream(
                prompt=prompt,
                model_id=self.model_id,
                max_tokens=self.max_tokens,
                temperature=self.temperature or 0.7,
            ):
                yield chunk

        except (OSError, ValueError, RuntimeError, TimeoutError) as e:
            logger.error("Tinker streaming error for %s: %s", self.name, e)
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()
            raise

    def _build_prompt(
        self,
        task: str,
        context: list[Message] | None,
        system_prompt: str | None,
    ) -> str:
        """Build the full prompt with context."""
        parts = []

        # System prompt
        if system_prompt:
            parts.append(f"System: {system_prompt}\n")
        else:
            parts.append(self._get_default_system_prompt())

        # Context from previous messages
        if context:
            context_str = self._build_context_prompt(context)
            if context_str:
                parts.append(f"\nPrevious discussion:\n{context_str}\n")

        # Current task
        parts.append(f"\nTask: {task}\n")
        parts.append(f"\n{self.name} ({self.role}):")

        return "".join(parts)

    def _get_default_system_prompt(self) -> str:
        """Get default system prompt based on role."""
        prompts = {
            "proposer": (
                "You are an expert debater participating in a structured debate. "
                "Your role is to propose well-reasoned arguments supported by evidence. "
                "Be clear, logical, and persuasive while acknowledging limitations."
            ),
            "critic": (
                "You are a critical analyst in a structured debate. "
                "Your role is to identify weaknesses, logical flaws, and missing considerations. "
                "Be constructive but thorough in your critique."
            ),
            "judge": (
                "You are an impartial judge evaluating debate arguments. "
                "Assess each argument on its merits, logical coherence, and evidence. "
                "Provide fair and well-reasoned judgments."
            ),
            "synthesizer": (
                "You are a synthesizer in a structured debate. "
                "Your role is to identify common ground and build consensus. "
                "Integrate the best elements from different positions."
            ),
        }
        return prompts.get(self.role, prompts["proposer"])

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """
        Critique a proposal using Tinker API.

        Args:
            proposal: The proposal to critique
            task: The task/prompt the proposal was for
            context: Previous messages
            target_agent: Name of the agent whose proposal is being critiqued

        Returns:
            Critique with issues, suggestions, severity, reasoning
        """
        target_desc = f" from {target_agent}" if target_agent else ""
        critique_prompt = (
            f"Critique the following proposal{target_desc} for this task:\n\n"
            f"Task: {task}\n\n"
            f"Proposal:\n{proposal}\n\n"
            "Identify:\n"
            "1. Logical issues or flaws\n"
            "2. Missing considerations\n"
            "3. Suggestions for improvement\n"
            "4. Overall severity (0.0-1.0)\n"
        )

        response = await self.respond(critique_prompt, context)
        return self._parse_critique(response, target_agent or "proposal", proposal)

    def set_adapter(self, adapter: str | None) -> None:
        """
        Switch to a different LoRA adapter.

        Args:
            adapter: Adapter name, or None for base model
        """
        self.adapter = adapter
        # Model ID may need to be updated based on adapter
        if adapter:
            self.model_id = f"{self.model}-{adapter}"
        else:
            self.model_id = None

    def get_model_info(self) -> dict[str, Any]:
        """Get information about the current model configuration."""
        return {
            "agent_name": self.name,
            "agent_type": self.agent_type,
            "base_model": self.model,
            "model_id": self.model_id,
            "adapter": self.adapter,
            "role": self.role,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


# Convenience subclasses for common configurations
@AgentRegistry.register(
    "tinker-llama",
    default_model="llama-3.3-70b",
    default_name="tinker-llama",
    agent_type="API",
    env_vars="TINKER_API_KEY",
)
class TinkerLlamaAgent(TinkerAgent):
    """Tinker agent using Llama 3.3 70B."""

    def __init__(
        self,
        name: str = "tinker-llama",
        role: AgentRole = "proposer",
        **kwargs,
    ):
        super().__init__(
            name=name,
            model="llama-3.3-70b",
            role=role,
            **kwargs,
        )


@AgentRegistry.register(
    "tinker-qwen",
    default_model="qwen-2.5-72b",
    default_name="tinker-qwen",
    agent_type="API",
    env_vars="TINKER_API_KEY",
)
class TinkerQwenAgent(TinkerAgent):
    """Tinker agent using Qwen 2.5 72B."""

    def __init__(
        self,
        name: str = "tinker-qwen",
        role: AgentRole = "proposer",
        **kwargs,
    ):
        super().__init__(
            name=name,
            model="qwen-2.5-72b",
            role=role,
            **kwargs,
        )


@AgentRegistry.register(
    "tinker-deepseek",
    default_model="deepseek-v3",
    default_name="tinker-deepseek",
    agent_type="API",
    env_vars="TINKER_API_KEY",
)
class TinkerDeepSeekAgent(TinkerAgent):
    """Tinker agent using DeepSeek V3."""

    def __init__(
        self,
        name: str = "tinker-deepseek",
        role: AgentRole = "proposer",
        **kwargs,
    ):
        super().__init__(
            name=name,
            model="deepseek-v3",
            role=role,
            **kwargs,
        )


__all__ = [
    "TinkerAgent",
    "TinkerLlamaAgent",
    "TinkerQwenAgent",
    "TinkerDeepSeekAgent",
]
