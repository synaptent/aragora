"""
API-based agent implementations.

These agents call AI APIs directly (HTTP), enabling use without CLI tools.
Supports Gemini, Ollama (local), and direct OpenAI/Anthropic API calls.
"""

from __future__ import annotations

from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
from aragora.agents.api_agents.autogen_agent import AutoGenAgent, AutoGenConfig

# Re-export all agents for backward compatibility
from aragora.agents.api_agents.crewai_agent import CrewAIAgent, CrewAIConfig
from aragora.agents.api_agents.base import APIAgent
from aragora.agents.api_agents.external_framework import (
    ExternalFrameworkAgent,
    ExternalFrameworkConfig,
)
from aragora.agents.api_agents.langgraph_agent import (
    LangGraphAgent,
    LangGraphConfig,
)
from aragora.agents.api_agents.common import MAX_STREAM_BUFFER_SIZE
from aragora.agents.api_agents.gemini import GeminiAgent
from aragora.agents.api_agents.grok import GrokAgent
from aragora.agents.api_agents.lm_studio import LMStudioAgent
from aragora.agents.api_agents.mistral import CodestralAgent, MistralAPIAgent
from aragora.agents.api_agents.ollama import OllamaAgent
from aragora.agents.api_agents.openai import OpenAIAPIAgent
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.api_agents.openrouter import (
    CommandRAgent,
    DeepSeekAgent,
    DeepSeekReasonerAgent,
    DeepSeekV3Agent,
    JambaAgent,
    KimiK2Agent,
    KimiK3Agent,
    KimiLegacyAgent,
    KimiThinkingAgent,
    Llama4MaverickAgent,
    Llama4ScoutAgent,
    LlamaAgent,
    MistralAgent,
    OpenRouterAgent,
    QwenAgent,
    QwenMaxAgent,
    SonarAgent,
)
from aragora.agents.api_agents.openclaw import OpenClawAgent, OpenClawConfig
from aragora.agents.api_agents.rate_limiter import (
    OPENROUTER_TIERS,
    OpenRouterRateLimiter,
    OpenRouterTier,
    get_openrouter_limiter,
    set_openrouter_tier,
)
from aragora.agents.api_agents.tinker import (
    TinkerAgent,
    TinkerDeepSeekAgent,
    TinkerLlamaAgent,
    TinkerQwenAgent,
)

__all__ = [
    # Base classes
    "APIAgent",
    "OpenAICompatibleMixin",
    # Provider agents
    "GeminiAgent",
    "AnthropicAPIAgent",
    "OpenAIAPIAgent",
    "GrokAgent",
    "OllamaAgent",
    "LMStudioAgent",
    # Mistral direct API
    "MistralAPIAgent",
    "CodestralAgent",
    # OpenRouter and subclasses
    "OpenRouterAgent",
    "DeepSeekAgent",
    "DeepSeekReasonerAgent",
    "DeepSeekV3Agent",
    "LlamaAgent",
    "MistralAgent",
    "QwenAgent",
    "QwenMaxAgent",
    "KimiK2Agent",
    "KimiK3Agent",
    "KimiThinkingAgent",
    "KimiLegacyAgent",
    "Llama4MaverickAgent",
    "Llama4ScoutAgent",
    "SonarAgent",
    "CommandRAgent",
    "JambaAgent",
    # External framework proxy
    "ExternalFrameworkAgent",
    "ExternalFrameworkConfig",
    # LangGraph (state machine agent framework)
    "LangGraphAgent",
    "LangGraphConfig",
    # AutoGen (Microsoft multi-agent framework)
    "AutoGenAgent",
    "AutoGenConfig",
    # CrewAI (multi-agent orchestration framework)
    "CrewAIAgent",
    "CrewAIConfig",
    # Tinker (fine-tuned models)
    "TinkerAgent",
    "TinkerLlamaAgent",
    "TinkerQwenAgent",
    "TinkerDeepSeekAgent",
    # OpenClaw
    "OpenClawAgent",
    "OpenClawConfig",
    # Rate limiting
    "OpenRouterRateLimiter",
    "OpenRouterTier",
    "OPENROUTER_TIERS",
    "get_openrouter_limiter",
    "set_openrouter_tier",
    # Constants
    "MAX_STREAM_BUFFER_SIZE",
]
