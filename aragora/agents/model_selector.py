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
from aragora.models.catalog import CATALOG


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
    # frontier-model-refresh, 2026-09-04: "claude" and "claude-opus" both
    # point at the Fable 5.1 flagship row (the brief's explicit mapping for
    # both keys); "claude-opus-4-8" below stays a distinct fallback-tier row.
    "claude": ModelProfile(
        model_id=CATALOG["claude-fable-5-1"].direct_id,
        display_name="Claude Fable 5.1",
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
        max_context_tokens=CATALOG["claude-fable-5-1"].context_window,
        max_output_tokens=CATALOG["claude-fable-5-1"].max_output_tokens,
        cost_input_per_1k=CATALOG["claude-fable-5-1"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["claude-fable-5-1"].output_per_mtok / 1000,
        avg_latency_ms=700,
        reliability_score=0.98,
        supports_vision=True,
    ),
    "claude-opus": ModelProfile(
        model_id=CATALOG["claude-fable-5-1"].direct_id,
        display_name="Claude Fable 5.1",
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
        max_context_tokens=CATALOG["claude-fable-5-1"].context_window,
        max_output_tokens=CATALOG["claude-fable-5-1"].max_output_tokens,
        cost_input_per_1k=CATALOG["claude-fable-5-1"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["claude-fable-5-1"].output_per_mtok / 1000,
        avg_latency_ms=1200,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # Previous Anthropic frontier. Kept selectable (and priced) because it is
    # still Active upstream and is Opus 5's documented fallback target for
    # cyber-classifier refusals.
    "claude-opus-4-8": ModelProfile(
        model_id=CATALOG["claude-opus-4-8"].direct_id,
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
        max_context_tokens=CATALOG["claude-opus-4-8"].context_window,
        max_output_tokens=CATALOG["claude-opus-4-8"].max_output_tokens,
        cost_input_per_1k=CATALOG["claude-opus-4-8"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["claude-opus-4-8"].output_per_mtok / 1000,
        avg_latency_ms=1200,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # Anthropic value tier. Both rows are ENFORCED catalog models, so the
    # selector can offer a cheap Anthropic option instead of routing every
    # Anthropic request to the $10/$50 flagship -- which is what happened
    # while "claude-haiku" was removed on the (since corrected) grounds that
    # the catalog carried no cheap Anthropic row. Capability scores are
    # derived the same way as the other value-tier profiles here (the
    # gemini/gemini-flash and gpt4/gpt-4o pairs): a few points under the
    # family flagship, LONG_CONTEXT tracking the row's own context window,
    # and a markedly lower latency. Each profile has its OWN model id --
    # never two profiles on one id with different scores (#9990).
    "claude-sonnet": ModelProfile(
        model_id=CATALOG["claude-sonnet-5"].direct_id,
        display_name="Claude Sonnet 5",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.92,
            ModelCapability.CODING: 0.93,
            ModelCapability.LEGAL: 0.88,
            ModelCapability.MEDICAL: 0.85,
            ModelCapability.FINANCIAL: 0.88,
            ModelCapability.CREATIVE: 0.87,
            ModelCapability.MATH: 0.89,
            ModelCapability.LONG_CONTEXT: 0.96,  # 1M context, as the flagship
            ModelCapability.INSTRUCTION_FOLLOWING: 0.94,
            ModelCapability.FACTUAL_ACCURACY: 0.90,
        },
        max_context_tokens=CATALOG["claude-sonnet-5"].context_window,
        max_output_tokens=CATALOG["claude-sonnet-5"].max_output_tokens,
        cost_input_per_1k=CATALOG["claude-sonnet-5"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["claude-sonnet-5"].output_per_mtok / 1000,
        avg_latency_ms=500,
        reliability_score=0.97,
        supports_vision=True,
    ),
    "claude-haiku": ModelProfile(
        model_id=CATALOG["claude-haiku-4-5-20251001"].direct_id,
        display_name="Claude Haiku 4.5",
        provider="anthropic",
        capabilities={
            ModelCapability.REASONING: 0.85,
            ModelCapability.CODING: 0.86,
            ModelCapability.LEGAL: 0.80,
            ModelCapability.MEDICAL: 0.77,
            ModelCapability.FINANCIAL: 0.80,
            ModelCapability.CREATIVE: 0.82,
            ModelCapability.MATH: 0.82,
            ModelCapability.LONG_CONTEXT: 0.88,  # 200k context
            ModelCapability.INSTRUCTION_FOLLOWING: 0.89,
            ModelCapability.FACTUAL_ACCURACY: 0.84,
        },
        max_context_tokens=CATALOG["claude-haiku-4-5-20251001"].context_window,
        max_output_tokens=CATALOG["claude-haiku-4-5-20251001"].max_output_tokens,
        cost_input_per_1k=CATALOG["claude-haiku-4-5-20251001"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["claude-haiku-4-5-20251001"].output_per_mtok / 1000,
        avg_latency_ms=250,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # OpenAI
    # frontier-model-refresh, 2026-09-04: gpt-5.5 is retired; "gpt4" now
    # points at the OpenAI flagship frontier (gpt-6-astra), which IS in
    # aragora/models/catalog.py's ENFORCED_MODELS, so this profile is
    # mirror-enforced by tests/models/test_catalog.py exactly as the old
    # gpt-5.5 row was.
    "gpt4": ModelProfile(
        model_id=CATALOG["gpt-6-astra"].direct_id,
        display_name="GPT-6 Astra",
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
        max_context_tokens=CATALOG["gpt-6-astra"].context_window,
        max_output_tokens=CATALOG["gpt-6-astra"].max_output_tokens,
        cost_input_per_1k=CATALOG["gpt-6-astra"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["gpt-6-astra"].output_per_mtok / 1000,
        avg_latency_ms=900,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # "gpt-4o" now points at the value-tier frontier sibling (gpt-5.6-terra)
    # instead of the retired gpt-4o id (frontier-model-refresh, 2026-09-04).
    "gpt-4o": ModelProfile(
        model_id=CATALOG["gpt-5.6-terra"].direct_id,
        display_name="GPT-5.6 Terra",
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
        max_context_tokens=CATALOG["gpt-5.6-terra"].context_window,
        max_output_tokens=CATALOG["gpt-5.6-terra"].max_output_tokens,
        cost_input_per_1k=CATALOG["gpt-5.6-terra"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["gpt-5.6-terra"].output_per_mtok / 1000,
        avg_latency_ms=800,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # gpt-5.4 is a retired legacy spelling with no catalog row; "gpt-5.4"
    # now points at the value-tier frontier (gpt-5.6-terra), the same
    # target as the "gpt-4o" profile (frontier-model-refresh, 2026-09-04
    # review fix round 1, item 4).
    "gpt-5.4": ModelProfile(
        model_id=CATALOG["gpt-5.6-terra"].direct_id,
        display_name="GPT-5.6 Terra",
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
        max_context_tokens=CATALOG["gpt-5.6-terra"].context_window,
        max_output_tokens=CATALOG["gpt-5.6-terra"].max_output_tokens,
        cost_input_per_1k=CATALOG["gpt-5.6-terra"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["gpt-5.6-terra"].output_per_mtok / 1000,
        avg_latency_ms=400,
        reliability_score=0.97,
        supports_vision=True,
    ),
    # Google
    "gemini": ModelProfile(
        model_id=CATALOG["gemini-3.1-pro-preview"].direct_id,
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
        max_context_tokens=CATALOG["gemini-3.1-pro-preview"].context_window,
        max_output_tokens=CATALOG["gemini-3.1-pro-preview"].max_output_tokens,
        cost_input_per_1k=CATALOG["gemini-3.1-pro-preview"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["gemini-3.1-pro-preview"].output_per_mtok / 1000,
        avg_latency_ms=900,
        reliability_score=0.96,
        supports_vision=True,
    ),
    # gemini-3-flash-preview is retired/uncataloged; "gemini-flash" now
    # points at the Gemini 3.8 Flash value tier (frontier-model-refresh,
    # 2026-09-04).
    "gemini-flash": ModelProfile(
        model_id=CATALOG["gemini-3.8-flash"].direct_id,
        display_name="Gemini 3.8 Flash",
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
        max_context_tokens=CATALOG["gemini-3.8-flash"].context_window,
        max_output_tokens=CATALOG["gemini-3.8-flash"].max_output_tokens,
        cost_input_per_1k=CATALOG["gemini-3.8-flash"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["gemini-3.8-flash"].output_per_mtok / 1000,
        avg_latency_ms=350,
        reliability_score=0.96,
        supports_vision=True,
    ),
    # Mistral. "mistral" now points at the mistral-medium-2604 flagship
    # (mistral-large-2512 is tier="fallback"; frontier-model-refresh,
    # 2026-09-04).
    "mistral": ModelProfile(
        model_id=CATALOG["mistral-medium-2604"].direct_id,
        display_name="Mistral Medium 2604",
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
        max_context_tokens=CATALOG["mistral-medium-2604"].context_window,
        max_output_tokens=CATALOG["mistral-medium-2604"].max_output_tokens,
        cost_input_per_1k=CATALOG["mistral-medium-2604"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["mistral-medium-2604"].output_per_mtok / 1000,
        avg_latency_ms=650,
        reliability_score=0.95,
        supports_vision=True,
    ),
    # DeepSeek. "deepseek"/"deepseek-r1" now point at the fully-cataloged
    # deepseek-v4-pro-0813 row (deepseek-v4-pro was an uncataloged legacy
    # spelling; frontier-model-refresh, 2026-09-04).
    "deepseek": ModelProfile(
        model_id=CATALOG["deepseek-v4-pro-0813"].direct_id,
        display_name="DeepSeek V4 Pro (0813)",
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
        max_context_tokens=CATALOG["deepseek-v4-pro-0813"].context_window,
        max_output_tokens=CATALOG["deepseek-v4-pro-0813"].max_output_tokens,
        cost_input_per_1k=CATALOG["deepseek-v4-pro-0813"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["deepseek-v4-pro-0813"].output_per_mtok / 1000,
        avg_latency_ms=500,
        reliability_score=0.92,
    ),
    "deepseek-r1": ModelProfile(
        model_id=CATALOG["deepseek-v4-pro-0813"].direct_id,
        display_name="DeepSeek V4 Pro (0813)",
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
        max_context_tokens=CATALOG["deepseek-v4-pro-0813"].context_window,
        max_output_tokens=CATALOG["deepseek-v4-pro-0813"].max_output_tokens,
        cost_input_per_1k=CATALOG["deepseek-v4-pro-0813"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["deepseek-v4-pro-0813"].output_per_mtok / 1000,
        avg_latency_ms=1800,  # Slower due to reasoning
        reliability_score=0.92,
    ),
    # Grok. "grok-4-latest" is retired; "grok" now points at the current
    # frontier (frontier-model-refresh, 2026-09-04).
    "grok": ModelProfile(
        model_id=CATALOG["grok-4.6"].direct_id,
        display_name="Grok 4.6",
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
        max_context_tokens=CATALOG["grok-4.6"].context_window,
        max_output_tokens=CATALOG["grok-4.6"].max_output_tokens,
        cost_input_per_1k=CATALOG["grok-4.6"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["grok-4.6"].output_per_mtok / 1000,
        avg_latency_ms=800,
        reliability_score=0.95,
        supports_vision=True,
    ),
    # Qwen. "qwen3.8-max" is superseded by qwen3.8-2.4t-a95b (kept as a
    # catalog alias, so it still resolves); "qwen" now reads the canonical
    # id directly (frontier-model-refresh, 2026-09-04). "qwen-3.5" (Qwen3.5
    # Plus) is removed: it is superseded with no distinct successor tier
    # (see aragora/agents/api_agents/openrouter.py's matching removal of
    # Qwen35PlusAgent).
    "qwen": ModelProfile(
        model_id=CATALOG["qwen3.8-2.4t-a95b"].direct_id,
        display_name="Qwen 3.8",
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
        max_context_tokens=CATALOG["qwen3.8-2.4t-a95b"].context_window,
        max_output_tokens=CATALOG["qwen3.8-2.4t-a95b"].max_output_tokens,
        cost_input_per_1k=CATALOG["qwen3.8-2.4t-a95b"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["qwen3.8-2.4t-a95b"].output_per_mtok / 1000,
        avg_latency_ms=700,
        reliability_score=0.93,
    ),
    # Kimi (Moonshot AI)
    "kimi": ModelProfile(
        model_id=CATALOG["kimi-k3"].direct_id,
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
        max_context_tokens=CATALOG["kimi-k3"].context_window,
        max_output_tokens=CATALOG["kimi-k3"].max_output_tokens,
        cost_input_per_1k=CATALOG["kimi-k3"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["kimi-k3"].output_per_mtok / 1000,
        avg_latency_ms=800,
        reliability_score=0.91,
        supports_vision=True,
    ),
    # Llama 4 Maverick is retired; "llama4-maverick" now points at Meta
    # Muse Spark 1.3, its successor (frontier-model-refresh, 2026-09-04).
    "llama4-maverick": ModelProfile(
        model_id=CATALOG["muse-spark-1.3"].direct_id,
        display_name="Meta Muse Spark 1.3",
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
        max_context_tokens=CATALOG["muse-spark-1.3"].context_window,
        max_output_tokens=CATALOG["muse-spark-1.3"].max_output_tokens,
        cost_input_per_1k=CATALOG["muse-spark-1.3"].input_per_mtok / 1000,
        cost_output_per_1k=CATALOG["muse-spark-1.3"].output_per_mtok / 1000,
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
