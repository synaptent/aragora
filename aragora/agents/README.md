# Agents Module

Multi-provider AI agent orchestration with intelligent fallback and resilience.

## Overview

The agents module supports 25+ AI model providers through a unified interface. It handles CLI-based agents (subprocess invocation) and API agents (direct HTTP calls) with automatic fallback, circuit breakers, and performance tracking.

## Quick Start

```python
from aragora.agents import create_agent

# Create an agent
agent = create_agent("anthropic-api", name="claude", role="proposer")

# Generate a response
response = await agent.generate("Explain quantum computing")

# Critique a proposal
critique = await agent.critique(proposal, task)
```

### With Fallback Chain

```python
from aragora.agents import AgentFallbackChain

chain = AgentFallbackChain(
    providers=["openai", "anthropic", "openrouter"],
)
chain.register_provider("openai", lambda: OpenAIAPIAgent())
chain.register_provider("anthropic", lambda: AnthropicAPIAgent())
chain.register_provider("openrouter", lambda: OpenRouterAgent())

# Automatic fallback on provider failure
result = await chain.generate(prompt, context)
```

## Key Files

| File | Purpose |
|------|---------|
| `cli_agents.py` | CLI-based agent wrappers (Claude, Gemini, Grok, etc.) |
| `api_agents/` | Direct HTTP API implementations (18 agent types) |
| `fallback.py` | Quota detection, OpenRouter fallback, chain orchestration |
| `airlock.py` | Resilience wrapper with timeouts and sanitization |
| `registry.py` | Factory pattern agent creation with LRU caching |
| `base.py` | Abstract Agent class, CritiqueMixin, debate interfaces |
| `performance_monitor.py` | Agent metrics tracking |
| `personas/` | Persona management for agent specialization |

## Agent Types

### CLI Agents

Invoke external CLI tools with automatic fallback to OpenRouter API:

| Agent | CLI Tool | Installation |
|-------|----------|--------------|
| `ClaudeAgent` | claude | `npm install -g @anthropic-ai/claude-code` |
| `GeminiCLIAgent` | gemini | `npm install -g @google/gemini-cli` |
| `GrokCLIAgent` | grok | `npm install -g grok-cli` |
| `QwenCLIAgent` | qwen | `npm install -g @qwen-code/qwen-code` |
| `DeepseekCLIAgent` | deepseek | `pip install deepseek-cli` |
| `CodexAgent` | codex | (built-in) |
| `OpenAIAgent` | openai | `pip install openai` |

### API Agents

Direct HTTP integrations without CLI overhead:

**Cloud Providers:**
- `AnthropicAPIAgent` - Claude models
- `OpenAIAPIAgent` - GPT models
- `GeminiAgent` - Gemini models
- `GrokAgent` - xAI Grok
- `MistralAPIAgent` - Mistral Large, Codestral

**OpenRouter Gateway (40+ models):**
- `DeepSeekAgent`, `DeepSeekReasonerAgent` - DeepSeek V3/R1
- `LlamaAgent`, `Llama4MaverickAgent` - Meta Llama 3.3/4
- `QwenAgent`, `QwenMaxAgent` - Alibaba Qwen
- `KimiK3Agent` (`KimiK2Agent` compatibility alias) - Moonshot Kimi K3
- `SonarAgent` - Perplexity (reasoning + web search)
- `CommandRAgent` - Cohere (RAG-optimized)

**Local Inference:**
- `OllamaAgent` - Local Ollama
- `LMStudioAgent` - LM Studio

## Resilience Patterns

### Circuit Breaker

Prevents cascade failures when providers are degraded:

```python
# CLI agents: failure_threshold=15, cooldown=120s
# API agents: failure_threshold=5, cooldown=60s

agent = create_agent("gemini", name="gemini")
# Circuit breaker auto-opens after threshold failures
```

### Airlock Proxy

Wraps agents with timeout protection and response sanitization:

```python
from aragora.agents import AirlockProxy, AirlockConfig

config = AirlockConfig(
    generate_timeout=240.0,
    critique_timeout=180.0,
    extract_json=True,
    strip_markdown_fences=True,
    fallback_on_timeout=True,
)
safe_agent = AirlockProxy(agent, config)
```

### Quota Fallback

Automatic fallback to OpenRouter when primary provider fails:

```python
# Detected conditions:
# - HTTP 429: Rate limit
# - HTTP 403 with "quota exceeded": Quota exhausted
# - HTTP 400 with "credit balance": Billing exhaustion
```

## Adding a New Agent

1. **Create the agent class:**

```python
# aragora/agents/api_agents/replicate.py
from aragora.agents.api_agents.base import APIAgent
from aragora.agents.registry import AgentRegistry

@AgentRegistry.register(
    "replicate",
    default_model="replicate/model",
    agent_type="API",
    env_vars="REPLICATE_API_KEY",
)
class ReplicateAgent(APIAgent):
    async def generate(self, prompt: str, context=None) -> str:
        # Implementation
        pass

    async def critique(self, proposal: str, task: str, context=None) -> Critique:
        # Implementation
        pass
```

2. **Export in `__init__.py`:**

```python
# aragora/agents/api_agents/__init__.py
from aragora.agents.api_agents.replicate import ReplicateAgent
```

3. **Use via factory:**

```python
agent = create_agent("replicate", name="my-replicate")
```

## CLI vs API Agents

| Aspect | CLI Agents | API Agents |
|--------|-----------|-----------|
| Invocation | Subprocess | HTTP requests |
| Overhead | Higher (process spawn) | Lower (connection pooling) |
| Latency | 100-500ms+ | 10-100ms |
| Concurrency | Semaphore limited (10) | Unlimited with pooling |
| Circuit Breaker | 15 failures, 120s cooldown | 5 failures, 60s cooldown |
| Use Case | Local tools, CLI workflows | Production, concurrent debates |

## Environment Variables

**Required (at least one):**
- `ANTHROPIC_API_KEY` - Anthropic Claude
- `OPENAI_API_KEY` - OpenAI GPT

**Fallback:**
- `OPENROUTER_API_KEY` - Fallback when primary fails
- `ARAGORA_OPENROUTER_FALLBACK_ENABLED` - OpenRouter fallback toggle (default on; set `false` to opt out)

**Optional:**
- `GEMINI_API_KEY` - Google Gemini
- `XAI_API_KEY` - xAI Grok
- `MISTRAL_API_KEY` - Mistral API

**Performance:**
- `ARAGORA_MAX_CLI_SUBPROCESSES` - CLI subprocess limit (default: 10)
- `ARAGORA_MAX_CLI_PROMPT_CHARS` - Stdin threshold (default: 100KB)

## Token Tracking

```python
agent = create_agent("openai-api", name="gpt")
await agent.generate(prompt)

print(f"Input tokens: {agent.last_tokens_in}")
print(f"Output tokens: {agent.last_tokens_out}")
print(f"Total: {agent.total_tokens_in + agent.total_tokens_out}")
```

## Related Modules

- `aragora.debate` - Uses agents for debate orchestration
- `aragora.resilience` - CircuitBreaker implementation
- `aragora.ranking` - ELO tracking for agent selection
