"""
Power sampling mixin for API agents.

Provides inference-time reasoning improvement by generating multiple samples
and selecting the best one using power-law weighted selection.

Usage:
    from aragora.agents.power_sampling_mixin import PowerSamplingMixin

    class MyAgent(PowerSamplingMixin, APIAgent):
        async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
            if self.power_sampling_enabled:
                return await self.generate_with_power_sampling(prompt, context)
            return await super().generate(prompt, context)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable, Awaitable

if TYPE_CHECKING:
    from aragora.core import Message
    from aragora.debate.arena_sub_configs import PowerSamplingConfig

logger = logging.getLogger(__name__)


class PowerSamplingMixin:
    """Mixin providing power sampling capabilities for agents.

    When enabled, generates multiple responses and selects the best one
    using power-law weighted selection based on quality scoring.

    Requires the agent to have a `generate` method that takes
    (prompt, context) and returns a string.
    """

    # Power sampling configuration (set by Arena or manually)
    _power_sampling_config: PowerSamplingConfig | None = None
    _power_sampling_scorer: Callable[[str], float] | None = None

    @property
    def power_sampling_enabled(self) -> bool:
        """Check if power sampling is enabled."""
        if self._power_sampling_config is None:
            return False
        return self._power_sampling_config.enable_power_sampling

    def configure_power_sampling(
        self,
        config: PowerSamplingConfig | None = None,
        scorer: Callable[[str], float] | None = None,
    ) -> None:
        """Configure power sampling for this agent.

        Args:
            config: Power sampling configuration
            scorer: Optional custom quality scorer function
        """
        self._power_sampling_config = config
        self._power_sampling_scorer = scorer

    async def generate_with_power_sampling(
        self,
        prompt: str,
        context: list[Message] | None = None,
        generator: Callable[[str, Any], Awaitable[str]] | None = None,
    ) -> str:
        """Generate response using power sampling.

        Generates multiple samples and selects the best one based on
        quality scoring with power-law weighting.

        Args:
            prompt: The prompt to generate a response for
            context: Optional conversation context
            generator: Optional custom generator function

        Returns:
            The best selected response
        """
        from aragora.reasoning.sampling.power_sampling import (
            power_law_weights,
            select_diverse_samples,
        )

        config = self._power_sampling_config
        if config is None:
            # Fallback to default generation if not configured
            if generator:
                return await generator(prompt, context)
            return await self._base_generate(prompt, context)

        n_samples = config.n_samples
        alpha = config.alpha
        k_diverse = config.k_diverse
        timeout = config.sample_timeout
        min_quality = config.min_quality_threshold

        # Generate samples concurrently
        logger.debug(
            "[%s] Power sampling: generating %s samples", getattr(self, "name", "agent"), n_samples
        )

        async def generate_one() -> str | None:
            try:
                if generator:
                    return await asyncio.wait_for(generator(prompt, context), timeout=timeout)
                return await asyncio.wait_for(self._base_generate(prompt, context), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("[%s] Sample generation timed out", getattr(self, "name", "agent"))
                return None
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                logger.warning(
                    "[%s] Sample generation failed: %s", getattr(self, "name", "agent"), e
                )
                return None

        tasks = [generate_one() for _ in range(n_samples)]
        results = await asyncio.gather(*tasks)

        # Filter out failed samples
        samples = [r for r in results if r is not None and len(r.strip()) > 0]

        if not samples:
            logger.warning(
                "[%s] All power samples failed, falling back to single generation",
                getattr(self, "name", "agent"),
            )
            if generator:
                return await generator(prompt, context)
            return await self._base_generate(prompt, context)

        # Score samples
        scorer = self._power_sampling_scorer or self._default_scorer
        scores = [scorer(s) for s in samples]

        # Filter by minimum quality threshold
        quality_samples = [(s, score) for s, score in zip(samples, scores) if score >= min_quality]

        if not quality_samples:
            # If nothing meets threshold, use the best we have
            best_idx = scores.index(max(scores))
            logger.debug(
                "[%s] No samples met quality threshold, using best available (score=%.2f)",
                getattr(self, "name", "agent"),
                scores[best_idx],
            )
            return samples[best_idx]

        # Select diverse high-quality samples
        filtered_samples = [s for s, _ in quality_samples]
        filtered_scores = [score for _, score in quality_samples]

        if len(filtered_samples) <= k_diverse:
            # Use power-law weighted selection directly
            weights = power_law_weights(filtered_scores, alpha)
            selected_idx = self._weighted_sample(weights)
            selected = filtered_samples[selected_idx]
        else:
            # Convert to ScoredSample objects for the diversity selector
            from aragora.reasoning.sampling.power_sampling import ScoredSample

            scored_samples = [
                ScoredSample(response=s, score=score)
                for s, score in zip(filtered_samples, filtered_scores)
            ]
            # Select k diverse samples, then choose best
            diverse_indices = select_diverse_samples(scored_samples, k=k_diverse)
            selected = filtered_samples[diverse_indices[0]]  # Best diverse sample

        logger.debug(
            "[%s] Power sampling: selected from %s samples (best score=%.2f)",
            getattr(self, "name", "agent"),
            len(samples),
            max(scores),
        )

        return selected

    async def _base_generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        """Base generation method - should be overridden by actual agent class.

        This method is called by generate_with_power_sampling and should
        be the parent class's generate method. Agents mixing in PowerSamplingMixin
        should ensure this calls the actual LLM generation.
        """
        # Try to call parent's generate
        if hasattr(super(), "generate"):
            return await super().generate(prompt, context)  # type: ignore[misc]
        raise NotImplementedError("PowerSamplingMixin requires the agent to have a generate method")

    def _default_scorer(self, response: str) -> float:
        """Default quality scorer based on response characteristics.

        Scores based on:
        - Length (longer responses tend to be more complete)
        - Structure (presence of reasoning markers)
        - Coherence signals

        Args:
            response: The response to score

        Returns:
            Quality score from 0.0 to 1.0
        """
        if not response or not response.strip():
            return 0.0

        score = 0.5  # Base score

        # Length factor (diminishing returns after ~500 chars)
        length = len(response.strip())
        length_factor = min(1.0, length / 500) * 0.2
        score += length_factor

        # Reasoning markers
        reasoning_markers = [
            "because",
            "therefore",
            "however",
            "first",
            "second",
            "importantly",
            "consider",
            "analysis",
            "reason",
            "conclude",
            "step",
            "approach",
            "solution",
            "problem",
        ]
        response_lower = response.lower()
        marker_count = sum(1 for m in reasoning_markers if m in response_lower)
        reasoning_factor = min(0.2, marker_count * 0.04)
        score += reasoning_factor

        # Structure markers (code blocks, lists, headers)
        structure_markers = ["```", "- ", "1.", "2.", "**", "##"]
        structure_count = sum(1 for m in structure_markers if m in response)
        structure_factor = min(0.1, structure_count * 0.02)
        score += structure_factor

        return min(1.0, score)

    def _weighted_sample(self, weights: list[float]) -> int:
        """Select an index based on weights.

        Args:
            weights: Probability weights (should sum to 1)

        Returns:
            Selected index
        """
        import random

        r = random.random()  # noqa: S311 -- probabilistic sampling
        cumsum = 0.0
        for i, w in enumerate(weights):
            cumsum += w
            if r <= cumsum:
                return i
        return len(weights) - 1  # Fallback to last


__all__ = ["PowerSamplingMixin"]
