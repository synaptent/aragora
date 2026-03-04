# Agent Selection Guide

This guide helps you choose the right AI agents for your Aragora stress-tests based on task type, cost, and capability requirements.

Perspective coverage note: Mistral adds an EU lens, and Chinese models like DeepSeek, Qwen, and Kimi provide a Chinese perspective (use the providers and keys listed below).

## Available Agents

### Primary Providers (Direct API)

| Agent ID | Provider | Model | Best For | Cost |
|----------|----------|-------|----------|------|
| `anthropic-api` | Anthropic | claude-opus-4-5-20251101 | Code review, reasoning | $$ |
| `openai-api` | OpenAI | gpt-5.3 | General tasks, creativity | $$ |
| `gemini` | Google | gemini-3-pro-preview | Long context, analysis | $ |
| `mistral-api` | Mistral | mistral-large-2512 | European compliance, multilingual | $$ |
| `grok` | xAI | grok-4-latest | Real-time knowledge | $$ |

### OpenRouter Providers (Fallback/Alternative)

| Agent ID | Model | Best For | Cost |
|----------|-------|----------|------|
| `openrouter` | model parameter (default: deepseek/deepseek-chat-v3-0324) | Fallback when primary fails | Varies |
| `deepseek` | deepseek/deepseek-reasoner | Code, math, reasoning | $ |
| `deepseek-r1` | deepseek/deepseek-r1 | Chain-of-thought reasoning | $ |
| `mistral` | mistralai/mistral-large-2411 | Fast, high-quality reasoning | $$ |
| `qwen` | qwen/qwen3-max | Multilingual, code | $ |
| `qwen-max` | qwen/qwen3-max | Flagship reasoning | $$ |
| `llama` | meta-llama/llama-3.3-70b-instruct | General, open weights | $ |
| `yi` | 01-ai/yi-large | Chinese/English | $ |

**Cost Legend:** $ = Low ($0.001-0.01/1K tokens), $$ = Medium ($0.01-0.05/1K), $$$ = High ($0.05+/1K)

### Local Providers (No API Key)

| Agent ID | Model | Best For | Cost |
|----------|-------|----------|------|
| `ollama` | Local Ollama model | Air-gapped/private deployments | $ |
| `lm-studio` | Local LM Studio model | Desktop/local inference | $ |

**Environment variables:**
```bash
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=llama2
export LM_STUDIO_HOST=http://localhost:1234
```

**CLI usage:**
```bash
aragora ask "Review this policy" --agents ollama
aragora ask "Summarize this spec" --agents lm-studio
```

**Python autodetection:**
```python
from aragora.agents import LocalLLMDetector

status = await LocalLLMDetector().detect_all()
if status.any_available:
    print(status.recommended_server, status.recommended_model)
```

**API endpoints:**
```bash
curl -s http://localhost:8080/api/agents/local
curl -s http://localhost:8080/api/agents/local/status
```

## Task-Based Recommendations

### Code Review

**Recommended:** `anthropic-api,openai-api`

```bash
git diff main | aragora review --agents anthropic-api,openai-api
```

Why:
- Anthropic excels at code understanding and security analysis
- OpenAI provides creative edge case detection
- Consensus between them = high confidence findings

**Budget alternative:** `anthropic-api,deepseek`
- DeepSeek V3 is excellent at code for 1/10th the cost

### Architecture Design

**Recommended:** `anthropic-api,openai-api,gemini`

```bash
aragora ask "Review this microservices architecture" \
  --agents anthropic-api,openai-api,gemini \
  --rounds 3
```

Why:
- Three diverse perspectives catch more issues
- Gemini handles long architecture documents well
- Multiple rounds allow deeper exploration

### Compliance Audits

**Recommended:** `anthropic-api,mistral-api`

```bash
aragora gauntlet policy.md --agents anthropic-api,mistral-api --persona gdpr
```

Why:
- Mistral is trained with European data/compliance focus
- Anthropic provides strong reasoning for legal interpretation
- Both have strong safety training

### Quick Validation

**Recommended:** `anthropic-api` (single agent)

```bash
aragora review --demo  # Or single agent for speed
aragora review --agents anthropic-api
```

Why:
- Fastest response time
- Anthropic alone catches most critical issues
- Use for early-stage development feedback

### High-Stakes Decisions

**Recommended:** `anthropic-api,openai-api,gemini,mistral-api`

```bash
aragora gauntlet critical_spec.md \
  --agents anthropic-api,openai-api,gemini,mistral-api \
  --profile thorough
```

Why:
- Four perspectives maximize coverage
- Different training data catches different blind spots
- Worth the cost for critical decisions

## Cost Optimization

### Single API Key Strategy

If you only have one API key:

```bash
# Anthropic only
export ANTHROPIC_API_KEY=your_key
export ARAGORA_DEFAULT_AGENTS=anthropic-api
aragora review

# OpenAI only
export OPENAI_API_KEY=your_key
export ARAGORA_DEFAULT_AGENTS=openai-api
aragora review
```

### Budget-Conscious Setup

Use OpenRouter for cost-effective multi-agent:

```bash
export OPENROUTER_API_KEY=your_key
aragora review --agents deepseek,qwen
```

Estimated costs per 10K token stress-test:
- `anthropic-api,openai-api`: ~$0.30
- `deepseek,qwen`: ~$0.03 (10x cheaper)

### Automatic Fallback

Aragora auto-falls back to OpenRouter on rate limits:

```bash
# Primary keys + fallback
export ANTHROPIC_API_KEY=your_key
export OPENAI_API_KEY=your_key
export OPENROUTER_API_KEY=fallback_key

# If primary hits rate limit, falls back automatically
aragora review --agents anthropic-api,openai-api
```

If a provider key is missing and `OPENROUTER_API_KEY` is set, Aragora will
substitute OpenRouter models to keep the debate running:

- `anthropic-api` -> `anthropic/claude-3.5-sonnet`
- `openai-api` -> `openai/gpt-4o-mini`
- `gemini` -> `google/gemini-2.0-flash-exp:free`
- `grok` -> `x-ai/grok-2-1212`
- `mistral-api` -> `mistralai/mistral-large-2411`

## Capability Matrix

| Capability | Anthropic | OpenAI | Gemini | Mistral | DeepSeek |
|------------|--------|-------|--------|---------|----------|
| Code Understanding | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★★★★ |
| Security Analysis | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★☆☆ |
| Reasoning Depth | ★★★★★ | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★☆ |
| Long Context | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★☆☆ | ★★★★☆ |
| Multilingual | ★★★☆☆ | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★★☆ |
| Creativity | ★★★★☆ | ★★★★★ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ |
| Safety/Refusals | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★★☆☆ |
| Response Speed | ★★★★☆ | ★★★☆☆ | ★★★★★ | ★★★★☆ | ★★★★☆ |

## Role Assignment

Aragora auto-assigns roles based on agent order:

```bash
aragora ask "Design auth system" --agents anthropic-api,openai-api,gemini
```

| Position | Role | Best Agent Type |
|----------|------|-----------------|
| 1st | **Proposer** | Strong reasoning (Anthropic, OpenAI) |
| 2nd-n-1 | **Critic** | Detail-oriented (Anthropic, Mistral) |
| Last | **Synthesizer** | Balanced (OpenAI, Gemini) |

### Agent Specification Formats

**Recommended - Pipe format** (`provider|model|persona|role`):
```bash
# Full specification with all fields
--agents "anthropic-api|claude-opus|philosopher|proposer,openai-api|gpt-4o|skeptic|critic"

# Provider and role only (most common)
--agents "anthropic-api|||proposer,openai-api|||critic,gemini|||synthesizer"

# Provider with persona (role auto-assigned)
--agents "anthropic-api||philosopher|,openai-api||skeptic|"
```

**Legacy - Colon format** (backward compatible):
```bash
# Role assignment
--agents anthropic-api:proposer,openai-api:critic,gemini:synthesizer

# Persona assignment (non-role words treated as personas)
--agents anthropic-api:philosopher,openai-api:skeptic
```

| Format | Example | Provider | Model | Persona | Role |
|--------|---------|----------|-------|---------|------|
| Pipe (full) | `anthropic-api\|claude-opus\|phil\|critic` | anthropic-api | claude-opus | phil | critic |
| Pipe (role) | `anthropic-api\|\|\|critic` | anthropic-api | default | - | critic |
| Pipe (persona) | `anthropic-api\|\|philosopher\|` | anthropic-api | default | philosopher | auto |
| Legacy (role) | `anthropic-api:critic` | anthropic-api | default | - | critic |
| Legacy (persona) | `anthropic-api:philosopher` | anthropic-api | default | philosopher | auto |
| Plain | `anthropic-api` | anthropic-api | default | - | auto |

**Valid roles:** `proposer`, `critic`, `synthesizer`, `judge`

## Environment Variables

```bash
# Primary providers
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GEMINI_API_KEY=AI...
export MISTRAL_API_KEY=...
export XAI_API_KEY=...

# Fallback provider
export OPENROUTER_API_KEY=sk-or-...
```

## Recommendations by Use Case

| Use Case | Agents | Rounds | Profile |
|----------|--------|--------|---------|
| Quick PR review | `anthropic-api,openai-api` | 2 | - |
| Security audit | `anthropic-api,openai-api,mistral-api` | 3 | `thorough` |
| Architecture review | `anthropic-api,openai-api,gemini` | 3 | `thorough` |
| GDPR compliance | `anthropic-api,mistral-api` | 2 | `policy` |
| Code refactoring | `anthropic-api,deepseek` | 2 | `code` |
| Budget review | `deepseek,qwen` | 2 | `quick` |
| High-stakes decision | All 4 primary | 4 | `thorough` |

## Troubleshooting

### "No API keys configured"
Set at least one provider key:
```bash
export ANTHROPIC_API_KEY=your_key
```

### Rate limiting
Add OpenRouter fallback:
```bash
export OPENROUTER_API_KEY=fallback_key
```

### Slow responses
- Use fewer agents
- Use `--rounds 1` for faster results
- Use `gemini` (fastest response time)

### Inconsistent results
- Add more agents for consensus
- Use `--rounds 3` or more
- Prefer Anthropic for consistent reasoning

## Related Documentation

- [Environment Variables](../reference/ENVIRONMENT.md) - Full API key reference
- [Gauntlet Mode](./GAUNTLET.md) - Stress testing configuration
- [API Reference](../api/API_REFERENCE.md) - Programmatic agent selection
