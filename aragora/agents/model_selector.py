"""
Specialist Model Selector for Enterprise Multi-Agent Control Plane.

Selects optimal models based on:
- Vertical/domain expertise requirements
- Task complexity and type
- Cost constraints
- Latency requirements
- Context length needs

Usage:
    from aragora.agents.model_selector import SpecialistModelSelector

    selector = SpecialistModelSelector()

    # Select best model for a task
    model = selector.select_model(
        vertical=Vertical.LEGAL,
        task_type="contract_review",
        context_length=50000,
        cost_sensitive=True,
    )

    # Get capability comparison
    comparison = selector.compare_models(["claude", "gpt4", "gemini"])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.agents.vertical_personas import Vertical


class ModelCapability(Enum):
    """Model capabilities for scoring."""

    REASONING = "reasoning"
    CODING = "coding"
    LEGAL = "legal"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    CREATIVE = "creative"
    MATH = "math"
    MULTILINGUAL = "multilingual"
    LONG_CONTEXT = "long_context"
    INSTRUCTION_FOLLOWING = "instruction_following"
    FACTUAL_ACCURACY = "factual_accuracy"


@dataclass
class ModelProfile:
    """Profile of a model's capabilities and characteristics."""

    model_id: str
    display_name: str
    provider: str

    # Capability scores (0.0-1.0)
    capabilities: dict[ModelCapability, float] = field(default_factory=dict)

    # Technical specs
    max_context_tokens: int = 128000
    max_output_tokens: int = 4096

    # Cost (per 1K tokens)
    cost_input_per_1k: float = 0.003
    cost_output_per_1k: float = 0.015

    # Performance
    avg_latency_ms: float = 1000.0
    reliability_score: float = 0.95

    # Characteristics
    is_fine_tunable: bool = False
    supports_function_calling: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True

    def get_capability_score(self, capability: ModelCapability) -> float:
        """Get score for a specific capability."""
        return self.capabilities.get(capability, 0.5)

    def get_total_score(self, weights: dict[ModelCapability, float]) -> float:
        """Calculate weighted total score."""
        total = 0.0
        total_weight = 0.0
        for cap, weight in weights.items():
            total += self.get_capability_score(cap) * weight
            total_weight += weight
        return total / total_weight if total_weight > 0 else 0.5

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a request."""
        return (input_tokens / 1000) * self.cost_input_per_1k + (
            output_tokens / 1000
        ) * self.cost_output_per_1k


# Model profiles for major providers
MODEL_PROFILES: dict[str, ModelProfile] = {
    # Anthropic
    "claude": ModelProfile(
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.97,
            ModelCapability.CODING: 0.97,
            ModelCapability.LEGAL: 0.94,
            ModelCapability.MEDICAL: 0.91,
            ModelCapability.FINANCIAL: 0.94,
            ModelCapability.CREATIVE: 0.91,
            ModelCapability.MATH: 0.94,
            ModelCapability.LONG_CONTEXT: 0.96,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.98,
            ModelCapability.FACTUAL_ACCURACY: 0.95,
        },
        max_context_tokens=200000,
        max_output_tokens=64000,
        cost_input_per_1k=0.003,
        cost_output_per_1k=0.015,
        avg_latency_ms=700,
        reliability_score=0.98,
        supports_vision=True,
    ),
    "claude-opus": ModelProfile(
        model_id="claude-opus-5",
        display_name="Claude Opus 5",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.99,
            ModelCapability.CODING: 0.99,
            ModelCapability.LEGAL: 0.97,
            ModelCapability.MEDICAL: 0.96,
            ModelCapability.FINANCIAL: 0.97,
            ModelCapability.CREATIVE: 0.95,
            ModelCapability.MATH: 0.98,
            ModelCapability.LONG_CONTEXT: 0.96,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.99,
            ModelCapability.FACTUAL_ACCURACY: 0.98,
        },
        max_context_tokens=1000000,
        max_output_tokens=128000,
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.025,
        avg_latency_ms=1200,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # Previous Anthropic frontier. Kept selectable (and priced) because it is
    # still Active upstream and is Opus 5's documented fallback target for
    # cyber-classifier refusals.
    "claude-opus-4-8": ModelProfile(
        model_id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.99,
            ModelCapability.CODING: 0.99,
            ModelCapability.LEGAL: 0.97,
            ModelCapability.MEDICAL: 0.96,
            ModelCapability.FINANCIAL: 0.97,
            ModelCapability.CREATIVE: 0.95,
            ModelCapability.MATH: 0.98,
            ModelCapability.LONG_CONTEXT: 0.96,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.99,
            ModelCapability.FACTUAL_ACCURACY: 0.98,
        },
        max_context_tokens=1000000,
        max_output_tokens=128000,
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.025,
        avg_latency_ms=1200,
        reliability_score=0.97,
        supports_vision=True,
    ),
    "claude-haiku": ModelProfile(
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.82,
            ModelCapability.CODING: 0.85,
            ModelCapability.LEGAL: 0.75,
            ModelCapability.MEDICAL: 0.72,
            ModelCapability.FINANCIAL: 0.75,
            ModelCapability.CREATIVE: 0.78,
            ModelCapability.MATH: 0.78,
            ModelCapability.LONG_CONTEXT: 0.90,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.88,
            ModelCapability.FACTUAL_ACCURACY: 0.80,
        },
        max_context_tokens=200000,
        max_output_tokens=8192,
        cost_input_per_1k=0.0008,
        cost_output_per_1k=0.004,
        avg_latency_ms=300,
        reliability_score=0.98,
        supports_vision=True,
    ),
    # OpenAI
    "gpt4": ModelProfile(
        model_id="gpt-5.5",
        display_name="GPT-5.5",
        provider="openai",
        capabilities={
            ModelCapability.REASONING: 0.94,
            ModelCapability.CODING: 0.95,
            ModelCapability.LEGAL: 0.90,
            ModelCapability.MEDICAL: 0.87,
            ModelCapability.FINANCIAL: 0.90,
            ModelCapability.CREATIVE: 0.88,
            ModelCapability.MATH: 0.92,
            ModelCapability.LONG_CONTEXT: 0.97,  # 1M context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.95,
            ModelCapability.FACTUAL_ACCURACY: 0.91,
        },
        max_context_tokens=1000000,
        max_output_tokens=32768,
        # Provider repriced ~2026-07-14; must match aragora/models/catalog.py
        # ($5/$30 per MTok) — enforced by tests/models/test_catalog.py.
        cost_input_per_1k=0.005,
        cost_output_per_1k=0.030,
        avg_latency_ms=900,
        reliability_score=0.97,
        supports_vision=True,
    ),
    "gpt-4o": ModelProfile(
        model_id="gpt-4o",
        display_name="GPT-4o",
        provider="openai",
        capabilities={
            ModelCapability.REASONING: 0.90,
            ModelCapability.CODING: 0.90,
            ModelCapability.LEGAL: 0.85,
            ModelCapability.MEDICAL: 0.82,
            ModelCapability.FINANCIAL: 0.85,
            ModelCapability.CREATIVE: 0.88,
            ModelCapability.MATH: 0.85,
            ModelCapability.LONG_CONTEXT: 0.90,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.90,
            ModelCapability.FACTUAL_ACCURACY: 0.85,
        },
        max_context_tokens=128000,
        max_output_tokens=16384,
        cost_input_per_1k=0.0025,
        cost_output_per_1k=0.01,
        avg_latency_ms=800,
        reliability_score=0.97,
        supports_vision=True,
    ),
    "gpt-5.4": ModelProfile(
        model_id="gpt-5.4",
        display_name="GPT-4.1 Mini",
        provider="openai",
        capabilities={
            ModelCapability.REASONING: 0.85,
            ModelCapability.CODING: 0.88,
            ModelCapability.LEGAL: 0.80,
            ModelCapability.MEDICAL: 0.78,
            ModelCapability.FINANCIAL: 0.80,
            ModelCapability.CREATIVE: 0.82,
            ModelCapability.MATH: 0.85,
            ModelCapability.LONG_CONTEXT: 0.97,  # 1M context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.88,
            ModelCapability.FACTUAL_ACCURACY: 0.83,
        },
        max_context_tokens=1000000,
        max_output_tokens=32768,
        cost_input_per_1k=0.0004,
        cost_output_per_1k=0.0016,
        avg_latency_ms=400,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # Google
    "gemini": ModelProfile(
        model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro",
        provider="google",
        capabilities={
            ModelCapability.REASONING: 0.96,
            ModelCapability.CODING: 0.95,
            ModelCapability.LEGAL: 0.90,
            ModelCapability.MEDICAL: 0.87,
            ModelCapability.FINANCIAL: 0.90,
            ModelCapability.CREATIVE: 0.91,
            ModelCapability.MATH: 0.95,
            ModelCapability.LONG_CONTEXT: 0.99,  # 1M context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.94,
            ModelCapability.FACTUAL_ACCURACY: 0.92,
        },
        max_context_tokens=1000000,
        max_output_tokens=64000,
        cost_input_per_1k=0.002,
        cost_output_per_1k=0.012,
        avg_latency_ms=900,
        reliability_score=0.96,
        supports_vision=True,
    ),
    "gemini-flash": ModelProfile(
        model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash",
        provider="google",
        capabilities={
            ModelCapability.REASONING: 0.90,
            ModelCapability.CODING: 0.89,
            ModelCapability.LEGAL: 0.82,
            ModelCapability.MEDICAL: 0.80,
            ModelCapability.FINANCIAL: 0.82,
            ModelCapability.CREATIVE: 0.86,
            ModelCapability.MATH: 0.87,
            ModelCapability.LONG_CONTEXT: 0.98,  # 1M context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.89,
            ModelCapability.FACTUAL_ACCURACY: 0.85,
        },
        max_context_tokens=1000000,
        max_output_tokens=65536,
        cost_input_per_1k=0.0005,
        cost_output_per_1k=0.003,
        avg_latency_ms=350,
        reliability_score=0.96,
        supports_vision=True,
    ),
    # Mistral
    "mistral": ModelProfile(
        model_id="mistral-large-2512",
        display_name="Mistral Large 3",
        provider="mistral",
        capabilities={
            ModelCapability.REASONING: 0.91,
            ModelCapability.CODING: 0.92,
            ModelCapability.LEGAL: 0.83,
            ModelCapability.MEDICAL: 0.80,
            ModelCapability.FINANCIAL: 0.83,
            ModelCapability.CREATIVE: 0.85,
            ModelCapability.MATH: 0.88,
            ModelCapability.MULTILINGUAL: 0.95,
            ModelCapability.LONG_CONTEXT: 0.90,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.91,
            ModelCapability.FACTUAL_ACCURACY: 0.86,
        },
        max_context_tokens=256000,
        max_output_tokens=8192,
        cost_input_per_1k=0.002,
        cost_output_per_1k=0.006,
        avg_latency_ms=650,
        reliability_score=0.95,
        supports_vision=True,
    ),
    # DeepSeek
    "deepseek": ModelProfile(
        model_id="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        provider="deepseek",
        capabilities={
            ModelCapability.REASONING: 0.92,
            ModelCapability.CODING: 0.95,
            ModelCapability.LEGAL: 0.78,
            ModelCapability.MEDICAL: 0.72,
            ModelCapability.FINANCIAL: 0.78,
            ModelCapability.CREATIVE: 0.80,
            ModelCapability.MATH: 0.93,
            ModelCapability.LONG_CONTEXT: 0.88,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.88,
            ModelCapability.FACTUAL_ACCURACY: 0.82,
        },
        max_context_tokens=1048576,
        max_output_tokens=8192,
        cost_input_per_1k=0.00174,
        cost_output_per_1k=0.00348,
        avg_latency_ms=500,
        reliability_score=0.92,
    ),
    "deepseek-r1": ModelProfile(
        model_id="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        provider="deepseek",
        capabilities={
            ModelCapability.REASONING: 0.96,
            ModelCapability.CODING: 0.92,
            ModelCapability.LEGAL: 0.82,
            ModelCapability.MEDICAL: 0.78,
            ModelCapability.FINANCIAL: 0.84,
            ModelCapability.CREATIVE: 0.72,
            ModelCapability.MATH: 0.96,
            ModelCapability.LONG_CONTEXT: 0.85,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.90,
            ModelCapability.FACTUAL_ACCURACY: 0.87,
        },
        max_context_tokens=1048576,
        max_output_tokens=8192,
        cost_input_per_1k=0.00174,
        cost_output_per_1k=0.00348,
        avg_latency_ms=1800,  # Slower due to reasoning
        reliability_score=0.92,
    ),
    # Grok
    "grok": ModelProfile(
        model_id="grok-4-latest",
        display_name="Grok 4",
        provider="xai",
        capabilities={
            ModelCapability.REASONING: 0.94,
            ModelCapability.CODING: 0.92,
            ModelCapability.LEGAL: 0.85,
            ModelCapability.MEDICAL: 0.80,
            ModelCapability.FINANCIAL: 0.85,
            ModelCapability.CREATIVE: 0.91,
            ModelCapability.MATH: 0.92,
            ModelCapability.LONG_CONTEXT: 0.92,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.92,
            ModelCapability.FACTUAL_ACCURACY: 0.88,
        },
        max_context_tokens=256000,
        max_output_tokens=16384,
        cost_input_per_1k=0.003,
        cost_output_per_1k=0.015,
        avg_latency_ms=800,
        reliability_score=0.95,
        supports_vision=True,
    ),
    # Qwen
    "qwen": ModelProfile(
        model_id="qwen3.8-max",
        display_name="Qwen 3.8 Max",
        provider="alibaba",
        capabilities={
            ModelCapability.REASONING: 0.92,
            ModelCapability.CODING: 0.93,
            ModelCapability.LEGAL: 0.82,
            ModelCapability.MEDICAL: 0.78,
            ModelCapability.FINANCIAL: 0.82,
            ModelCapability.CREATIVE: 0.85,
            ModelCapability.MATH: 0.92,
            ModelCapability.MULTILINGUAL: 0.95,
            ModelCapability.LONG_CONTEXT: 0.92,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.90,
            ModelCapability.FACTUAL_ACCURACY: 0.84,
        },
        max_context_tokens=1_000_000,
        max_output_tokens=131_072,
        cost_input_per_1k=0.002,
        cost_output_per_1k=0.006,
        avg_latency_ms=700,
        reliability_score=0.93,
    ),
    "qwen-3.5": ModelProfile(
        model_id="qwen3.5-plus",
        display_name="Qwen3.5 Plus",
        provider="alibaba",
        capabilities={
            ModelCapability.REASONING: 0.94,
            ModelCapability.CODING: 0.94,
            ModelCapability.LEGAL: 0.84,
            ModelCapability.MEDICAL: 0.80,
            ModelCapability.FINANCIAL: 0.84,
            ModelCapability.CREATIVE: 0.87,
            ModelCapability.MATH: 0.94,
            ModelCapability.MULTILINGUAL: 0.96,
            ModelCapability.LONG_CONTEXT: 0.97,  # 1M context hosted
            ModelCapability.INSTRUCTION_FOLLOWING: 0.92,
            ModelCapability.FACTUAL_ACCURACY: 0.86,
        },
        max_context_tokens=1000000,
        max_output_tokens=8192,
        cost_input_per_1k=0.0036,
        cost_output_per_1k=0.0036,
        avg_latency_ms=650,
        reliability_score=0.93,
        supports_vision=True,
    ),
    # Kimi (Moonshot AI)
    "kimi": ModelProfile(
        model_id="kimi-k3",
        display_name="Kimi K3",
        provider="moonshot",
        capabilities={
            ModelCapability.REASONING: 0.91,
            ModelCapability.CODING: 0.92,
            ModelCapability.LEGAL: 0.78,
            ModelCapability.MEDICAL: 0.75,
            ModelCapability.FINANCIAL: 0.78,
            ModelCapability.CREATIVE: 0.82,
            ModelCapability.MATH: 0.90,
            ModelCapability.MULTILINGUAL: 0.88,
            ModelCapability.LONG_CONTEXT: 0.92,
            ModelCapability.INSTRUCTION_FOLLOWING: 0.90,
            ModelCapability.FACTUAL_ACCURACY: 0.82,
        },
        max_context_tokens=1_048_576,
        max_output_tokens=32_768,
        cost_input_per_1k=0.003,
        cost_output_per_1k=0.015,
        avg_latency_ms=800,
        reliability_score=0.91,
        supports_vision=True,
    ),
    # Llama 4
    "llama4-maverick": ModelProfile(
        model_id="llama-4-maverick",
        display_name="Llama 4 Maverick",
        provider="meta",
        capabilities={
            ModelCapability.REASONING: 0.90,
            ModelCapability.CODING: 0.90,
            ModelCapability.LEGAL: 0.80,
            ModelCapability.MEDICAL: 0.77,
            ModelCapability.FINANCIAL: 0.80,
            ModelCapability.CREATIVE: 0.88,
            ModelCapability.MATH: 0.88,
            ModelCapability.MULTILINGUAL: 0.90,
            ModelCapability.LONG_CONTEXT: 0.97,  # 1M context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.88,
            ModelCapability.FACTUAL_ACCURACY: 0.83,
        },
        max_context_tokens=1000000,
        max_output_tokens=8192,
        cost_input_per_1k=0.0005,
        cost_output_per_1k=0.002,
        avg_latency_ms=600,
        reliability_score=0.92,
        supports_vision=True,
    ),
}

# Vertical to capability mapping
VERTICAL_CAPABILITIES: dict[Vertical, dict[ModelCapability, float]] = {
    Vertical.SOFTWARE: {
        ModelCapability.CODING: 0.35,
        ModelCapability.REASONING: 0.25,
        ModelCapability.INSTRUCTION_FOLLOWING: 0.20,
        ModelCapability.FACTUAL_ACCURACY: 0.20,
    },
    Vertical.LEGAL: {
        ModelCapability.LEGAL: 0.35,
        ModelCapability.REASONING: 0.25,
        ModelCapability.FACTUAL_ACCURACY: 0.25,
        ModelCapability.LONG_CONTEXT: 0.15,
    },
    Vertical.HEALTHCARE: {
        ModelCapability.MEDICAL: 0.35,
        ModelCapability.FACTUAL_ACCURACY: 0.30,
        ModelCapability.REASONING: 0.20,
        ModelCapability.INSTRUCTION_FOLLOWING: 0.15,
    },
    Vertical.ACCOUNTING: {
        ModelCapability.FINANCIAL: 0.30,
        ModelCapability.MATH: 0.25,
        ModelCapability.FACTUAL_ACCURACY: 0.25,
        ModelCapability.REASONING: 0.20,
    },
    Vertical.ACADEMIC: {
        ModelCapability.REASONING: 0.30,
        ModelCapability.FACTUAL_ACCURACY: 0.25,
        ModelCapability.CREATIVE: 0.20,
        ModelCapability.LONG_CONTEXT: 0.25,
    },
    Vertical.GENERAL: {
        ModelCapability.REASONING: 0.25,
        ModelCapability.INSTRUCTION_FOLLOWING: 0.25,
        ModelCapability.FACTUAL_ACCURACY: 0.25,
        ModelCapability.CREATIVE: 0.25,
    },
}


@dataclass
class ModelSelection:
    """Result of model selection."""

    model_id: str
    profile: ModelProfile
    score: float
    reasoning: str
    alternatives: list[tuple[str, float]]  # (model_id, score)
    estimated_cost: float
    estimated_latency_ms: float


class SpecialistModelSelector:
    """
    Selects optimal models based on task requirements and constraints.

    Considers:
    - Vertical-specific capability weights
    - Context length requirements
    - Cost constraints
    - Latency requirements
    - Model availability
    """

    def __init__(
        self,
        model_profiles: dict[str, ModelProfile] | None = None,
        available_models: list[str] | None = None,
    ):
        self._profiles = model_profiles or MODEL_PROFILES
        self._available_models = available_models or list(self._profiles.keys())

    def select_model(
        self,
        vertical: Vertical = Vertical.GENERAL,
        task_type: str = "",
        context_length: int = 0,
        cost_sensitive: bool = False,
        latency_sensitive: bool = False,
        required_capabilities: list[ModelCapability] | None = None,
        excluded_models: list[str] | None = None,
    ) -> ModelSelection:
        """
        Select the best model for a task.

        Args:
            vertical: Industry vertical
            task_type: Type of task
            context_length: Required context length in tokens
            cost_sensitive: Prioritize lower cost
            latency_sensitive: Prioritize lower latency
            required_capabilities: Must-have capabilities
            excluded_models: Models to exclude

        Returns:
            ModelSelection with recommended model and alternatives
        """
        excluded = set(excluded_models or [])
        candidates = [
            m for m in self._available_models if m not in excluded and m in self._profiles
        ]

        # Filter by context length
        if context_length > 0:
            candidates = [
                m for m in candidates if self._profiles[m].max_context_tokens >= context_length
            ]

        if not candidates:
            # Fall back to any available model
            candidates = list(self._available_models)[:1] or ["claude"]

        # Get capability weights for vertical
        weights = VERTICAL_CAPABILITIES.get(vertical, VERTICAL_CAPABILITIES[Vertical.GENERAL])

        # Add weights for required capabilities
        if required_capabilities:
            for cap in required_capabilities:
                weights[cap] = weights.get(cap, 0.0) + 0.2

        # Score candidates
        scored: list[tuple[str, float, ModelProfile]] = []
        for model_id in candidates:
            profile = self._profiles.get(model_id)
            if not profile:
                continue

            # Base score from capabilities
            score = profile.get_total_score(weights)

            # Adjust for cost sensitivity
            if cost_sensitive:
                # Penalize expensive models
                cost_factor = profile.cost_output_per_1k / 0.015  # Normalize to Claude
                score *= 1.0 / (1.0 + cost_factor * 0.3)

            # Adjust for latency sensitivity
            if latency_sensitive:
                # Penalize slow models
                latency_factor = profile.avg_latency_ms / 1000.0  # Normalize
                score *= 1.0 / (1.0 + latency_factor * 0.2)

            # Boost reliability
            score *= profile.reliability_score

            scored.append((model_id, score, profile))

        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            # Emergency fallback
            default = self._profiles.get("claude", list(self._profiles.values())[0])
            return ModelSelection(
                model_id="claude",
                profile=default,
                score=0.5,
                reasoning="Fallback to default model",
                alternatives=[],
                estimated_cost=0.0,
                estimated_latency_ms=1000.0,
            )

        best_id, best_score, best_profile = scored[0]

        # Get alternatives
        alternatives = [(m, s) for m, s, _ in scored[1:4]]

        # Estimate cost (assuming 2K input, 1K output)
        estimated_cost = best_profile.estimate_cost(2000, 1000)

        # Generate reasoning
        reasoning = self._generate_reasoning(
            vertical, task_type, best_id, best_score, cost_sensitive, latency_sensitive
        )

        return ModelSelection(
            model_id=best_id,
            profile=best_profile,
            score=best_score,
            reasoning=reasoning,
            alternatives=alternatives,
            estimated_cost=estimated_cost,
            estimated_latency_ms=best_profile.avg_latency_ms,
        )

    def _generate_reasoning(
        self,
        vertical: Vertical,
        task_type: str,
        model_id: str,
        score: float,
        cost_sensitive: bool,
        latency_sensitive: bool,
    ) -> str:
        """Generate explanation for model selection."""
        parts = [f"Selected {model_id} for {vertical.value}"]

        if task_type:
            parts.append(f"{task_type}")

        parts.append(f"(score: {score:.2f})")

        modifiers = []
        if cost_sensitive:
            modifiers.append("cost-optimized")
        if latency_sensitive:
            modifiers.append("latency-optimized")

        if modifiers:
            parts.append(f"[{', '.join(modifiers)}]")

        return " ".join(parts)

    def compare_models(
        self,
        model_ids: list[str],
        vertical: Vertical = Vertical.GENERAL,
    ) -> dict[str, dict[str, Any]]:
        """
        Compare multiple models for a vertical.

        Args:
            model_ids: Models to compare
            vertical: Industry vertical for scoring

        Returns:
            Dict with comparison data for each model
        """
        weights = VERTICAL_CAPABILITIES.get(vertical, VERTICAL_CAPABILITIES[Vertical.GENERAL])
        comparison = {}

        for model_id in model_ids:
            profile = self._profiles.get(model_id)
            if not profile:
                continue

            comparison[model_id] = {
                "display_name": profile.display_name,
                "provider": profile.provider,
                "total_score": profile.get_total_score(weights),
                "capabilities": {
                    cap.value: profile.get_capability_score(cap) for cap in ModelCapability
                },
                "max_context": profile.max_context_tokens,
                "cost_per_1k_avg": (profile.cost_input_per_1k + profile.cost_output_per_1k) / 2,
                "avg_latency_ms": profile.avg_latency_ms,
                "reliability": profile.reliability_score,
            }

        return comparison

    def get_cheapest_capable(
        self,
        min_capability_score: float = 0.7,
        capability: ModelCapability = ModelCapability.REASONING,
    ) -> str | None:
        """
        Get the cheapest model that meets a capability threshold.

        Args:
            min_capability_score: Minimum required capability score
            capability: Capability to evaluate

        Returns:
            Model ID or None if no model qualifies
        """
        candidates = []
        for model_id in self._available_models:
            profile = self._profiles.get(model_id)
            if not profile:
                continue

            if profile.get_capability_score(capability) >= min_capability_score:
                avg_cost = (profile.cost_input_per_1k + profile.cost_output_per_1k) / 2
                candidates.append((model_id, avg_cost))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def get_fastest_capable(
        self,
        min_capability_score: float = 0.7,
        capability: ModelCapability = ModelCapability.REASONING,
    ) -> str | None:
        """
        Get the fastest model that meets a capability threshold.

        Args:
            min_capability_score: Minimum required capability score
            capability: Capability to evaluate

        Returns:
            Model ID or None if no model qualifies
        """
        candidates = []
        for model_id in self._available_models:
            profile = self._profiles.get(model_id)
            if not profile:
                continue

            if profile.get_capability_score(capability) >= min_capability_score:
                candidates.append((model_id, profile.avg_latency_ms))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]


__all__ = [
    "ModelCapability",
    "ModelProfile",
    "ModelSelection",
    "SpecialistModelSelector",
    "MODEL_PROFILES",
    "VERTICAL_CAPABILITIES",
]
