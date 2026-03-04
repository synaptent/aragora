# API Agents Module

Direct HTTP API integrations for 25+ AI model providers, enabling efficient access to cloud and local LLMs without CLI dependencies.

## Quick Start

```python
from aragora.agents.api_agents import (
    AnthropicAPIAgent,
    OpenAIAPIAgent,
    GeminiAgent,
    GrokAgent,
    OpenRouterAgent,
    DeepSeekAgent,
)

# Create an agent with automatic fallback
agent = AnthropicAPIAgent(name="claude-debate", model="claude-opus-4-5-20251101")

# Generate a response
response = await agent.generate("Analyze the trade-offs of microservices vs monoliths")

# Stream tokens as they arrive
async for chunk in agent.generate_stream("Explain quantum computing"):
    print(chunk, end="", flush=True)
```

## Overview

The `api_agents` module provides:

- **Direct API Access**: HTTP-based agent implementations that bypass CLI overhead
- **Unified Interface**: All agents implement the same `Agent` protocol (`generate`, `generate_stream`, `critique`)
- **Built-in Resilience**: Circuit breakers, rate limiting, and automatic fallback to OpenRouter
- **Token Tracking**: Per-call and cumulative token usage for billing
- **Connection Pooling**: Shared TCP connections to reduce overhead
- **Streaming Support**: SSE-based token streaming for all major providers

## Architecture

```
api_agents/
├── base.py                 # APIAgent base class with circuit breaker
├── common.py               # Shared utilities, connection pooling, SSE parsing
├── openai_compatible.py    # OpenAI-compatible mixin (150+ lines saved per agent)
├── rate_limiter.py         # Token bucket rate limiting with exponential backoff
│
├── anthropic.py            # Anthropic Claude API
├── openai.py               # OpenAI GPT API
├── gemini.py               # Google Gemini API
├── grok.py                 # xAI Grok API
├── mistral.py              # Mistral AI API (Large, Codestral)
│
├── openrouter.py           # OpenRouter unified API (17 model subclasses)
├── ollama.py               # Local Ollama inference
├── lm_studio.py            # Local LM Studio (OpenAI-compatible)
├── tinker.py               # Fine-tuned models via Tinker API
│
├── langgraph_agent.py      # LangGraph state machine framework
├── autogen_agent.py        # Microsoft AutoGen framework
├── crewai_agent.py         # CrewAI orchestration framework
└── external_framework.py   # Generic external framework proxy
```

### Class Hierarchy

```
Agent (core.py)
└── APIAgent (base.py)
    ├── AnthropicAPIAgent     # Claude models
    ├── OpenAIAPIAgent        # GPT models (uses OpenAICompatibleMixin)
    ├── GeminiAgent           # Gemini models
    ├── GrokAgent             # Grok models (uses OpenAICompatibleMixin)
    ├── MistralAPIAgent       # Mistral models (uses OpenAICompatibleMixin)
    │   └── CodestralAgent    # Code-specialized Mistral
    ├── OpenRouterAgent       # Unified access to 40+ models
    │   ├── DeepSeekAgent     # DeepSeek V3/R1
    │   ├── LlamaAgent        # Meta Llama 3.3/4
    │   ├── QwenAgent         # Alibaba Qwen 2.5/3
    │   ├── KimiK2Agent       # Moonshot Kimi K2
    │   ├── SonarAgent        # Perplexity Sonar
    │   ├── CommandRAgent     # Cohere Command R+
    │   ├── JambaAgent        # AI21 Jamba
    │   └── ...               # 10+ more model-specific agents
    ├── OllamaAgent           # Local Ollama
    ├── LMStudioAgent         # Local LM Studio
    └── TinkerAgent           # Fine-tuned models
```

## Supported Providers

### Cloud Providers

| Provider | Agent Class | Default Model | Env Var | Capabilities |
|----------|-------------|---------------|---------|--------------|
| Anthropic | `AnthropicAPIAgent` | claude-opus-4-5-20251101 | `ANTHROPIC_API_KEY` | Streaming, Web Search, Fallback |
| OpenAI | `OpenAIAPIAgent` | gpt-5.3 | `OPENAI_API_KEY` | Streaming, Web Search, Fallback |
| Google | `GeminiAgent` | gemini-3-pro-preview | `GEMINI_API_KEY` | Streaming, Google Search Grounding, Fallback |
| xAI | `GrokAgent` | grok-4-latest | `XAI_API_KEY` | Streaming, Fallback |
| Mistral | `MistralAPIAgent` | mistral-large-2512 | `MISTRAL_API_KEY` | Streaming, Fallback |
| Mistral | `CodestralAgent` | codestral-latest | `MISTRAL_API_KEY` | Code-optimized |

### OpenRouter Models (via `OPENROUTER_API_KEY`)

| Agent Class | Model | Description |
|-------------|-------|-------------|
| `DeepSeekAgent` | deepseek-reasoner | Chain-of-thought reasoning |
| `DeepSeekReasonerAgent` | deepseek-r1 | Chain-of-thought reasoning |
| `LlamaAgent` | llama-3.3-70b | Meta's flagship open model |
| `Llama4MaverickAgent` | llama-4-maverick | 400B MoE, 1M context |
| `Llama4ScoutAgent` | llama-4-scout | 109B MoE, 10M context |
| `QwenAgent` | qwen3-max | Alibaba's frontier model |
| `QwenMaxAgent` | qwen3-max | Trillion-parameter frontier |
| `MistralAgent` | mistral-large-2411 | Via OpenRouter |
| `YiAgent` | yi-large | 01.AI flagship |
| `KimiK2Agent` | kimi-k2-0905 | 1T MoE, 256K context |
| `KimiThinkingAgent` | kimi-k2-thinking | Reasoning model |
| `SonarAgent` | sonar-reasoning | DeepSeek R1 + web search |
| `CommandRAgent` | command-r-plus | RAG-optimized |
| `JambaAgent` | jamba-1.6-large | SSM-Transformer hybrid |

### Local Inference

| Provider | Agent Class | Default Model | Requirements |
|----------|-------------|---------------|--------------|
| Ollama | `OllamaAgent` | llama3.2 | `ollama serve` running |
| LM Studio | `LMStudioAgent` | local-model | LM Studio running |

### Fine-Tuned Models

| Agent Class | Base Model | Description |
|-------------|------------|-------------|
| `TinkerAgent` | llama-3.3-70b | Aragora debate-tuned |
| `TinkerLlamaAgent` | llama-3.3-70b | Llama preset |
| `TinkerQwenAgent` | qwen-2.5-72b | Qwen preset |
| `TinkerDeepSeekAgent` | deepseek-v3 | DeepSeek preset |

## Rate Limiting

### How It Works

Rate limiting uses a **token bucket algorithm** with provider-specific tiers:

```python
from aragora.agents.api_agents.rate_limiter import (
    get_provider_limiter,
    get_openrouter_limiter,
    set_openrouter_tier,
)

# Get rate limiter for a provider
limiter = get_provider_limiter("anthropic")

# Use with context manager
async with limiter.request(timeout=30.0) as ctx:
    if ctx:
        response = await make_api_call()
    else:
        raise TimeoutError("Rate limit timeout")

# Set OpenRouter tier
set_openrouter_tier("premium")  # free, basic, standard, premium, unlimited
```

### Default Rate Limits

| Provider | RPM | Burst | Env Override |
|----------|-----|-------|--------------|
| Anthropic | 1000 | 50 | `ARAGORA_ANTHROPIC_RPM` |
| OpenAI | 500 | 30 | `ARAGORA_OPENAI_RPM` |
| Mistral | 300 | 20 | `ARAGORA_MISTRAL_RPM` |
| Gemini | 60 | 15 | `ARAGORA_GEMINI_RPM` |
| Grok | 500 | 30 | `ARAGORA_GROK_RPM` |
| OpenRouter | 200 | 30 | `OPENROUTER_TIER` |
| Ollama | 1000 | 100 | `ARAGORA_OLLAMA_RPM` |

### OpenRouter Tiers

| Tier | RPM | Burst |
|------|-----|-------|
| free | 20 | 5 |
| basic | 60 | 15 |
| standard | 200 | 30 |
| premium | 500 | 50 |
| unlimited | 1000 | 100 |

### Fallback Strategies

When a provider fails (rate limit, quota exceeded, auth error), agents automatically fall back to OpenRouter:

```python
# Enable fallback (default: enabled via ARAGORA_ENABLE_OPENROUTER_FALLBACK=true)
agent = AnthropicAPIAgent(enable_fallback=True)

# Fallback chain for OpenRouter models
# qwen/qwen3-235b -> deepseek/deepseek-chat -> openai/gpt-4o-mini
```

#### Fallback Model Chain

```python
OPENROUTER_FALLBACK_MODELS = {
    "qwen/qwen3-235b-a22b": "deepseek/deepseek-chat",
    "deepseek/deepseek-chat": "openai/gpt-4o-mini",
    "deepseek/deepseek-reasoner": "anthropic/claude-3-haiku",
    "moonshotai/kimi-k2-0905": "anthropic/claude-3-haiku",
    "meta-llama/llama-3.3-70b-instruct": "openai/gpt-4o-mini",
    # ... more mappings
}
```

## Adding New Providers

### Step 1: Create Agent Class

```python
# aragora/agents/api_agents/my_provider.py
from aragora.agents.api_agents.base import APIAgent
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.api_agents.common import (
    get_primary_api_key,
    handle_agent_errors,
    AgentRateLimitError,
    AgentConnectionError,
    AgentTimeoutError,
)
from aragora.agents.registry import AgentRegistry

@AgentRegistry.register(
    "my-provider",
    default_model="my-model-v1",
    agent_type="API",
    env_vars="MY_PROVIDER_API_KEY",
)
class MyProviderAgent(OpenAICompatibleMixin, APIAgent):
    """Agent for My Provider API."""

    # Map models to OpenRouter equivalents for fallback
    OPENROUTER_MODEL_MAP = {
        "my-model-v1": "openai/gpt-4o",
    }
    DEFAULT_FALLBACK_MODEL = "openai/gpt-4o"

    def __init__(
        self,
        name: str = "my-provider",
        model: str = "my-model-v1",
        role: str = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,
    ):
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key or get_primary_api_key(
                "MY_PROVIDER_API_KEY",
                allow_openrouter_fallback=True,
            ),
            base_url="https://api.myprovider.com/v1",
        )
        self.agent_type = "my-provider"

        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled
            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
```

### Step 2: For Non-OpenAI-Compatible APIs

If the provider doesn't use OpenAI-compatible format, implement `generate` directly:

```python
@handle_agent_errors(
    max_retries=3,
    retry_delay=1.0,
    retry_backoff=2.0,
    retryable_exceptions=(AgentRateLimitError, AgentConnectionError, AgentTimeoutError),
)
async def generate(self, prompt: str, context: list | None = None) -> str:
    """Generate using custom API format."""
    from aragora.agents.api_agents.common import create_client_session

    full_prompt = prompt
    if context:
        full_prompt = self._build_context_prompt(context) + prompt

    payload = {
        "input": full_prompt,
        "model": self.model,
        # Provider-specific format
    }

    async with create_client_session(timeout=self.timeout) as session:
        async with session.post(
            f"{self.base_url}/generate",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        ) as response:
            if response.status != 200:
                # Handle errors
                pass
            data = await response.json()
            return data["output"]  # Provider-specific parsing
```

### Step 3: Export in `__init__.py`

```python
# Add to aragora/agents/api_agents/__init__.py
from aragora.agents.api_agents.my_provider import MyProviderAgent

__all__ = [
    # ...existing exports...
    "MyProviderAgent",
]
```

### Step 4: Add Rate Limiter (Optional)

```python
# In rate_limiter.py, add to PROVIDER_DEFAULT_TIERS
PROVIDER_DEFAULT_TIERS["my_provider"] = ProviderTier(
    name="my_provider",
    requests_per_minute=100,
    burst_size=10,
)
```

## Configuration

### Environment Variables

```bash
# Required (at least one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Recommended (fallback)
OPENROUTER_API_KEY=sk-or-...

# Optional providers
GEMINI_API_KEY=...
GOOGLE_API_KEY=...          # Alternative for Gemini
XAI_API_KEY=...
GROK_API_KEY=...            # Alternative for Grok
MISTRAL_API_KEY=...
KIMI_API_KEY=...            # Direct Moonshot API
TINKER_API_KEY=...

# Local inference
OLLAMA_HOST=http://localhost:11434
LM_STUDIO_HOST=http://localhost:1234

# Rate limiting overrides
OPENROUTER_TIER=standard    # free, basic, standard, premium, unlimited
ARAGORA_ANTHROPIC_RPM=1000
ARAGORA_OPENAI_RPM=500

# Fallback control
ARAGORA_ENABLE_OPENROUTER_FALLBACK=true

# Connection tuning
ARAGORA_STREAM_BUFFER_SIZE=10485760  # 10MB max buffer
ARAGORA_STREAM_CHUNK_TIMEOUT=90      # Seconds between chunks
```

### Programmatic Configuration

```python
from aragora.agents.api_agents.rate_limiter import (
    set_openrouter_tier,
    get_provider_limiter,
)

# Set OpenRouter tier
set_openrouter_tier("premium")

# Custom rate limit for specific provider
limiter = get_provider_limiter("anthropic", rpm=2000, burst=100)
```

## Streaming vs Non-Streaming

### Non-Streaming (Default)

```python
# Wait for complete response
response = await agent.generate("Explain machine learning")
print(response)
```

### Streaming

```python
# Get tokens as they arrive
async for chunk in agent.generate_stream("Explain machine learning"):
    print(chunk, end="", flush=True)
print()  # Final newline
```

### SSE Parsing

All streaming uses Server-Sent Events (SSE). The module provides parsers:

```python
from aragora.agents.api_agents.common import (
    create_openai_sse_parser,
    create_anthropic_sse_parser,
    SSEStreamParser,
)

# OpenAI-compatible providers
parser = create_openai_sse_parser()
async for content in parser.parse_stream(response.content, agent_name):
    yield content

# Anthropic format
parser = create_anthropic_sse_parser()
async for content in parser.parse_stream(response.content, agent_name):
    yield content

# Custom provider
parser = SSEStreamParser(
    content_extractor=lambda event: event.get("text", ""),
    done_marker="[END]",
)
```

## Examples

### Basic Usage

```python
from aragora.agents.api_agents import AnthropicAPIAgent

agent = AnthropicAPIAgent()
response = await agent.generate("What is the capital of France?")
print(response)
```

### With Context

```python
from aragora.core import Message

context = [
    Message(agent="user", role="user", content="Let's discuss AI ethics"),
    Message(agent="claude", role="proposer", content="AI ethics involves..."),
]

response = await agent.generate(
    "What about bias in AI systems?",
    context=context,
)
```

### Critique Another Proposal

```python
critique = await agent.critique(
    proposal="We should implement a simple rate limiter...",
    task="Design a rate limiting system",
    target_agent="gpt-4",
)

print(f"Severity: {critique.severity}")
print(f"Issues: {critique.issues}")
print(f"Suggestions: {critique.suggestions}")
```

### Token Usage Tracking

```python
agent = AnthropicAPIAgent()
await agent.generate("Hello, world!")

print(f"Last call: {agent.last_tokens_in} in, {agent.last_tokens_out} out")
print(f"Total: {agent.total_tokens_in} in, {agent.total_tokens_out} out")

# Get full usage dict
usage = agent.get_token_usage()
print(usage)
```

### Circuit Breaker Status

```python
# Check if circuit is open (blocking requests)
if agent.is_circuit_open():
    print("Circuit breaker is open - too many failures")
else:
    response = await agent.generate("...")
```

### Local Model with Ollama

```python
from aragora.agents.api_agents import OllamaAgent

agent = OllamaAgent(model="llama3.2")

# Check if Ollama is running
if await agent.is_available():
    # List available models
    models = await agent.list_models()
    print(f"Available: {[m['name'] for m in models]}")

    # Generate response
    response = await agent.generate("Explain recursion")
```

### OpenRouter with Specific Model

```python
from aragora.agents.api_agents import OpenRouterAgent, DeepSeekAgent

# Generic OpenRouter with any model
agent = OpenRouterAgent(model="anthropic/claude-3.5-sonnet")

# Or use model-specific class for defaults
agent = DeepSeekAgent()  # Uses deepseek-v3.2
```

### Fine-Tuned Models

```python
from aragora.agents.api_agents import TinkerAgent

# Base model
agent = TinkerAgent(model="llama-3.3-70b")

# With LoRA adapter
agent = TinkerAgent(
    model="llama-3.3-70b",
    adapter="security-expert",
)

# Stream response
async for chunk in agent.respond_stream("Analyze this vulnerability..."):
    print(chunk, end="")
```

## Related Documentation

- [../README.md](../README.md) - Parent agents module overview
- [../../CLAUDE.md](../../CLAUDE.md) - Project overview
- [../../docs/AGENT_DEVELOPMENT.md](../../docs/AGENT_DEVELOPMENT.md) - Agent development guide
- [../../docs/ENVIRONMENT.md](../../docs/ENVIRONMENT.md) - Full environment variable reference
