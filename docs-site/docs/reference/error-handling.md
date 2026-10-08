---
title: Error Handling Patterns
description: Error Handling Patterns
---

# Error Handling Patterns

Comprehensive guide to error handling patterns in Aragora, covering the exception hierarchy,
circuit breakers, retry strategies, fallback chains, graceful degradation, and SDK error handling.

## Table of Contents

- [Exception Hierarchy](#exception-hierarchy)
- [Error Categories and HTTP Mapping](#error-categories-and-http-mapping)
- [Circuit Breakers](#circuit-breakers)
- [Retry Strategies](#retry-strategies)
- [OpenRouter Fallback](#openrouter-fallback)
- [Fallback Chains](#fallback-chains)
- [Agent Error Handling](#agent-error-handling)
- [Server Middleware](#server-middleware)
- [Graceful Degradation](#graceful-degradation)
- [SDK Error Handling](#sdk-error-handling)
- [Custom Error Types](#custom-error-types)
- [Best Practices](#best-practices)

---

## Exception Hierarchy

All Aragora exceptions inherit from `AragoraError`, enabling unified error handling
across the entire codebase. The hierarchy is defined in `aragora/exceptions.py`:

```
AragoraError (base)
├── DebateError
│   ├── DebateNotFoundError
│   ├── DebateConfigurationError
│   ├── ConsensusError
│   ├── ConsensusTimeoutError
│   ├── PhaseExecutionError
│   ├── EarlyStopError
│   └── RoundLimitExceededError
├── ValidationError
│   ├── InputValidationError
│   ├── SchemaValidationError
│   └── JSONParseError
├── StorageError
│   ├── DatabaseError
│   ├── DatabaseConnectionError
│   └── RecordNotFoundError
├── MemoryError
│   ├── MemoryRetrievalError
│   ├── MemoryStorageError
│   ├── TierTransitionError
│   └── EmbeddingError
├── AuthError
│   ├── AuthenticationError
│   ├── AuthorizationError
│   ├── TokenExpiredError
│   └── RateLimitExceededError
├── InfrastructureError
│   ├── RedisUnavailableError
│   ├── ExternalServiceError
│   └── CircuitBreakerError
├── AgentError (aragora.agents.errors)
│   ├── AgentConnectionError
│   ├── AgentTimeoutError
│   ├── AgentRateLimitError
│   ├── AgentAPIError
│   ├── AgentResponseError
│   ├── AgentStreamError
│   ├── AgentCircuitOpenError
│   └── CLIAgentError
├── ConnectorError (aragora.connectors.exceptions)
│   ├── ConnectorTimeoutError
│   ├── ConnectorRateLimitError
│   └── ConnectorNetworkError
├── NomicError
│   ├── NomicCycleError
│   ├── NomicPhaseError
│   └── NomicTimeoutError
└── StreamingError
    ├── WebSocketError
    └── StreamConnectionError
```

Every `AragoraError` carries a `message` and a `details` dict for structured context:

```python
from aragora.exceptions import AragoraError

try:
    await some_operation()
except AragoraError as e:
    logger.error(f"Operation failed: {e.message}", extra=e.details)
```

---

## Error Categories and HTTP Mapping

The exception handler middleware (`aragora/server/middleware/exception_handler.py`)
maps every exception type to an HTTP status code. The full mapping is in the
`EXCEPTION_STATUS_MAP` dictionary.

### Key Mappings

| Category | Exception Types | HTTP Status |
|----------|----------------|-------------|
| **Client Errors** | `ValueError`, `ValidationError`, `InputValidationError` | 400 |
| **Not Found** | `FileNotFoundError`, `DebateNotFoundError`, `RecordNotFoundError` | 404 |
| **Authentication** | `AuthenticationError`, `TokenExpiredError`, `APIKeyError` | 401 |
| **Authorization** | `PermissionError`, `AuthorizationError` | 403 |
| **Rate Limiting** | `RateLimitExceededError`, `AgentRateLimitError` | 429 |
| **Server Errors** | `RuntimeError`, `DatabaseError`, `DebateError` | 500 |
| **Service Unavailable** | `DatabaseConnectionError`, `AgentCircuitOpenError` | 503 |
| **Timeout** | `TimeoutError`, `AgentTimeoutError`, `ConsensusTimeoutError` | 504 |
| **Graceful Stop** | `EarlyStopError`, `RoundLimitExceededError` | 200 |

### Utility Functions

```python
from aragora.server.middleware.exception_handler import (
    is_client_error,
    is_server_error,
    is_retryable,
    is_authentication_error,
    map_exception_to_status,
)

# Check error category
if is_retryable(exc):
    # Status 429, 502, 503, or 504 - safe to retry
    await retry_operation()
elif is_client_error(exc):
    # Status 4xx - do not retry, fix the request
    return error_response(exc)
```

---

## Circuit Breakers

Circuit breakers prevent cascading failures by temporarily blocking calls to
failing services. The implementation lives in `aragora/resilience/circuit_breaker.py`.

### States

| State | Behavior |
|-------|----------|
| **CLOSED** | Normal operation. Requests flow through. Failures are counted. |
| **OPEN** | After `failure_threshold` consecutive failures. All requests are blocked. |
| **HALF-OPEN** | After `cooldown_seconds` elapse. Trial requests are allowed; successes close the circuit. |

### Basic Usage

```python
from aragora.resilience.circuit_breaker import CircuitBreaker

# Single-entity mode
breaker = CircuitBreaker(
    name="my-service",
    failure_threshold=3,      # Open after 3 failures
    cooldown_seconds=60.0,    # Wait 60s before retrying
)

if breaker.can_proceed():
    try:
        result = await call_api()
        breaker.record_success()
    except Exception:
        breaker.record_failure()
```

### Multi-Entity Mode

Track circuit state per provider or agent independently:

```python
breaker = CircuitBreaker(
    name="agents",
    failure_threshold=3,
    cooldown_seconds=60.0,
    half_open_success_threshold=2,  # 2 successes to fully close
)

# Each agent has independent state
if breaker.is_available("claude"):
    try:
        result = await claude_agent.generate(prompt)
        breaker.record_success("claude")
    except Exception:
        breaker.record_failure("claude")

# Check which agents are available
available = breaker.get_available_providers()
```

### Protected Call Context Manager

The recommended pattern uses the `protected_call` context manager:

```python
from aragora.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError

breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

try:
    async with breaker.protected_call(entity="openai"):
        result = await openai_agent.generate(prompt)
        # Success is automatically recorded
except CircuitOpenError as e:
    logger.warning(f"Circuit open: {e.circuit_name}, retry in {e.cooldown_remaining:.1f}s")
except Exception:
    # Failure is automatically recorded by the context manager
    pass
```

### Per-Provider Configuration

Each AI provider has tuned circuit breaker defaults in `aragora/resilience_config.py`:

| Provider | Failure Threshold | Cooldown (s) | Success Threshold | Half-Open Max Calls |
|----------|:-----------------:|:------------:|:-----------------:|:-------------------:|
| Anthropic | 3 | 30 | 2 | 2 |
| OpenAI | 5 | 60 | 2 | 3 |
| Mistral | 4 | 45 | 2 | 2 |
| OpenRouter | 5 | 90 | 3 | 2 |
| xAI/Grok | 3 | 60 | 2 | 2 |
| Gemini | 4 | 45 | 2 | 3 |
| Default | 5 | 60 | 2 | 3 |

```python
from aragora.resilience_config import get_circuit_breaker_config, CircuitBreakerConfig
from aragora.resilience.circuit_breaker import CircuitBreaker

# Get provider-specific config
config = get_circuit_breaker_config(provider="anthropic")
breaker = CircuitBreaker.from_config(config, name="anthropic-cb")

# Register custom agent-level config
from aragora.resilience_config import register_agent_config

register_agent_config(
    "claude-sonnet",
    CircuitBreakerConfig(failure_threshold=10, timeout_seconds=120)
)
```

### Environment Variable Overrides

Override circuit breaker settings globally via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_CB_FAILURE_THRESHOLD` | (per-provider) | Failures before opening |
| `ARAGORA_CB_SUCCESS_THRESHOLD` | (per-provider) | Successes to close in half-open |
| `ARAGORA_CB_TIMEOUT_SECONDS` | (per-provider) | Cooldown duration |
| `ARAGORA_CB_HALF_OPEN_MAX_CALLS` | (per-provider) | Max calls in half-open state |

---

## Retry Strategies

Retry logic is built into the agent error decorators (`aragora/agents/errors/decorators.py`).

### Exponential Backoff with Jitter

The `calculate_retry_delay_with_jitter` function computes retry delays:

```python
from aragora.agents.errors.decorators import calculate_retry_delay_with_jitter

# Attempt 0: ~1.0s (± 30% jitter)
# Attempt 1: ~2.0s (± 30% jitter)
# Attempt 2: ~4.0s (± 30% jitter)
# Attempt 3: capped at max_delay

delay = calculate_retry_delay_with_jitter(
    attempt=2,          # 0-indexed attempt number
    base_delay=1.0,     # Initial delay in seconds
    max_delay=30.0,     # Maximum delay cap
    jitter_factor=0.3,  # ±30% randomization
)
```

Jitter prevents thundering herd problems when multiple clients recover simultaneously.

### Agent Error Decorator

The `@handle_agent_errors` decorator provides retry + circuit breaker integration:

```python
from aragora.agents.errors.decorators import handle_agent_errors

class MyAPIAgent:
    @handle_agent_errors(
        max_retries=3,
        retry_delay=1.0,
        retry_backoff=2.0,
        max_delay=30.0,
        retryable_exceptions=(AgentConnectionError, AgentTimeoutError, AgentRateLimitError),
        circuit_breaker_attr="_circuit_breaker",
    )
    async def generate(self, prompt: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json={"prompt": prompt}) as resp:
                return await resp.text()
```

### Retryable vs Non-Retryable Errors

| Error Type | Retryable | Reason |
|------------|:---------:|--------|
| `AgentConnectionError` | Yes | Network issues are transient |
| `AgentTimeoutError` | Yes | Server may have been temporarily slow |
| `AgentRateLimitError` | Yes | Wait and retry after backoff |
| `AgentStreamError` | Yes | Streaming interruptions are transient |
| `AgentAPIError` (4xx) | No | Bad request, fix the input |
| `AgentAPIError` (5xx) | Yes | Server error, may recover |
| `AgentResponseError` | No | Response parsing failed, won't change on retry |
| `AgentCircuitOpenError` | Yes | Wait for cooldown, then retry |

### When to Retry vs Fail Fast

**Retry these errors:**
- 429 Too Many Requests (rate limit)
- 500, 502, 503, 504 (server errors)
- Connection timeouts
- Network errors

**Fail fast on these errors:**
- 400 Bad Request (client error)
- 401/403 (authentication/authorization)
- 404 Not Found
- Business logic errors

### Rate Limit Handling with Retry-After

When a provider returns HTTP 429 with a `Retry-After` header, the system
respects the provider's requested wait time:

```python
# Handled automatically by _handle_response_error in decorators.py
# 1. Parse Retry-After header
# 2. Cap at max_delay
# 3. Add 10% jitter to prevent synchronized retries
# 4. Use as override delay instead of exponential backoff
```

---

## OpenRouter Fallback

Aragora automatically falls back to OpenRouter when primary providers hit quota or rate limits.
This provides seamless failover without requiring code changes.

### Automatic Fallback via Mixin

The `QuotaFallbackMixin` provides automatic fallback for API agents:

```python
from aragora.agents.fallback import QuotaFallbackMixin

class MyAPIAgent(APIAgent, QuotaFallbackMixin):
    OPENROUTER_MODEL_MAP = {
        "gpt-4o": "openai/gpt-4o",
        "claude-3-opus": "anthropic/claude-3-opus",
    }
    DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4"

    async def generate(self, prompt, context):
        try:
            return await self._call_primary_api(prompt)
        except RateLimitError as e:
            if self.is_quota_error(e.status_code, str(e)):
                result = await self.fallback_generate(prompt, context)
                if result is not None:
                    return result
            raise
```

### Quota Error Detection

The `is_quota_error` method detects these conditions:

| HTTP Status | Condition |
|:-----------:|-----------|
| 429 | Rate limit (all providers) |
| 403 | Quota exceeded (with keyword match) |
| 400 | Billing/credit exhaustion (with keyword match) |
| 408, 504, 524 | Timeout errors |

Keywords that indicate quota/billing issues:
- `rate limit`, `rate_limit`, `ratelimit`, `too many requests`
- `quota`, `exceeded`, `limit exceeded`, `resource exhausted`
- `billing`, `credit balance`, `insufficient`, `purchase credits`

### Cost Implications

Fallback to OpenRouter incurs additional costs:

| Provider | Approximate Cost Multiplier |
|----------|----------------------------|
| Direct API | 1.0x (baseline) |
| OpenRouter | 1.0x - 1.3x (varies by model) |
| Local LLM | 0x (self-hosted) |

### OpenRouter Fallback

OpenRouter fallback is enabled by default when `OPENROUTER_API_KEY` is
available from the configured secret provider. In production and founder-run
calibration flows, store that key in AWS Secrets Manager rather than exporting
raw model API keys into the local shell.

```bash
export ARAGORA_USE_SECRETS_MANAGER=true
export ARAGORA_OPENROUTER_FALLBACK_ENABLED=true  # optional; true is the default
```

Set `ARAGORA_OPENROUTER_FALLBACK_ENABLED=false` only for an explicit opt-out.

---

## Fallback Chains

When a primary provider fails, Aragora can automatically route to alternative
providers. The implementation is in `aragora/agents/fallback.py`.

### QuotaFallbackMixin

The simplest fallback pattern routes to OpenRouter when the primary provider
hits rate limits or quota errors:

```python
from aragora.agents.fallback import QuotaFallbackMixin

class MyAgent(APIAgent, QuotaFallbackMixin):
    OPENROUTER_MODEL_MAP = {
        "gpt-4o": "openai/gpt-4o",
        "gpt-4": "openai/gpt-4",
    }
    DEFAULT_FALLBACK_MODEL = "openai/gpt-4o"

    async def generate(self, prompt, context=None):
        try:
            return await self._call_primary_api(prompt)
        except APIError as e:
            if self.is_quota_error(e.status_code, str(e)):
                result = await self.fallback_generate(prompt, context, e.status_code)
                if result is not None:
                    return result
            raise
```

### Quota Error Detection

The `is_quota_error` method detects these conditions:

| HTTP Status | Condition |
|:-----------:|-----------|
| 429 | Rate limit (all providers) |
| 403 | Quota exceeded (with keyword match) |
| 400 | Billing/credit exhaustion (with keyword match) |
| 408, 504, 524 | Timeout errors |

Keywords checked: `rate limit`, `quota`, `exceeded`, `billing`, `credit balance`,
`insufficient`, `timeout`, `timed out`.

### AgentFallbackChain

For multi-provider sequencing with full circuit breaker integration:

```python
from aragora.agents.fallback import AgentFallbackChain
from aragora.resilience.circuit_breaker import CircuitBreaker

chain = AgentFallbackChain(
    providers=["openai", "openrouter", "anthropic"],
    circuit_breaker=CircuitBreaker(failure_threshold=3, cooldown_seconds=60),
    max_retries=3,            # Try at most 3 providers
    max_fallback_time=30.0,   # Give up after 30 seconds total
)

# Register provider factories
chain.register_provider("openai", lambda: OpenAIAPIAgent(model="gpt-4o"))
chain.register_provider("openrouter", lambda: OpenRouterAgent(model="openai/gpt-4o"))
chain.register_provider("anthropic", lambda: AnthropicAPIAgent(model="claude-sonnet-4"))

# Generate with automatic fallback
result = await chain.generate(prompt, context)

# Monitor health
status = chain.get_status()
print(f"Fallback rate: {status['metrics']['fallback_rate']}")
print(f"Available: {status['available_providers']}")
```

### Including Local LLMs in Fallback

```python
from aragora.agents.fallback import build_fallback_chain_with_local

# Default: OpenAI -> OpenRouter -> Ollama/LM Studio -> Anthropic
providers = build_fallback_chain_with_local(
    primary_providers=["openai", "openrouter", "anthropic"],
    include_local=True,
)

# Priority local: OpenAI -> Ollama/LM Studio -> OpenRouter -> Anthropic
providers = build_fallback_chain_with_local(
    primary_providers=["openai", "openrouter", "anthropic"],
    include_local=True,
    local_priority=True,
)
```

### Fallback Error Types

| Error | Raised When |
|-------|-------------|
| `AllProvidersExhaustedError` | Every provider in the chain failed |
| `FallbackTimeoutError` | `max_fallback_time` exceeded before a provider succeeded |

### Enabling Fallback

OpenRouter fallback is enabled by default when an OpenRouter key is available
from the configured secret provider:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_OPENROUTER_FALLBACK_ENABLED` | `true` | OpenRouter fallback toggle; set `false` to opt out |
| `OPENROUTER_API_KEY` | (none) | Required for OpenRouter fallback; load from the configured secret provider |

---

## Agent Error Handling

The agent error hierarchy (`aragora/agents/errors/exceptions.py`) adds
agent-specific context to errors:

```python
from aragora.agents.errors.exceptions import (
    AgentError,
    AgentTimeoutError,
    AgentRateLimitError,
    AgentCircuitOpenError,
)

try:
    result = await agent.generate(prompt)
except AgentCircuitOpenError as e:
    # Circuit breaker is protecting this agent
    logger.warning(f"Agent {e.agent_name} circuit open, cooldown: {e.cooldown_seconds}s")
except AgentRateLimitError as e:
    # Provider rate limit hit
    if e.retry_after:
        await asyncio.sleep(e.retry_after)
except AgentTimeoutError as e:
    # Agent took too long
    if e.partial_content:
        # Use partial response if available
        result = e.partial_content
except AgentError as e:
    # Any agent error
    if e.recoverable:
        # Safe to retry
        pass
    logger.error(f"Agent error: {e}", extra={"cause": e.cause})
```

---

## Server Middleware

The exception handler middleware provides three usage patterns.

### Decorator Style

```python
from aragora.server.middleware.exception_handler import (
    handle_exceptions,
    async_handle_exceptions,
)

# Sync handler
@handle_exceptions("leaderboard retrieval")
def get_leaderboard(self, query_params):
    return self.db.get_leaderboard()

# Async handler
@async_handle_exceptions("agent generation")
async def generate_response(self, prompt):
    return await self.agent.generate(prompt)
```

### Context Manager Style

```python
from aragora.server.middleware.exception_handler import (
    ExceptionHandler,
    async_exception_handler,
)

# Sync context manager
with ExceptionHandler("debate creation") as ctx:
    result = create_debate()
    ctx.success(result)

if ctx.error:
    return ctx.error_response  # Sanitized error dict

# Async context manager
async with async_exception_handler("agent generation") as ctx:
    result = await agent.generate(prompt)
    ctx.success(result)
```

### Error Response Format

All error responses follow a consistent structure with trace IDs for debugging:

```json
{
    "error": "Failed to create debate: invalid configuration",
    "status": 400,
    "trace_id": "a1b2c3d4",
    "error_type": "DebateConfigurationError",
    "context": "debate creation"
}
```

The `X-Trace-Id` header is also set in the HTTP response for correlation.

---

## Graceful Degradation

Graceful degradation ensures the system continues to function (perhaps with reduced
capabilities) when some components fail.

### Feature Flags

Use feature flags to disable non-critical functionality during outages:

```python
from aragora.config import get_feature_flag

async def process_debate(debate):
    result = await core_debate_logic(debate)

    # Optional: Add evidence collection if available
    if get_feature_flag("evidence_collection_enabled"):
        try:
            result.evidence = await collect_evidence(debate)
        except ServiceUnavailableError:
            logger.warning("Evidence collection unavailable, continuing without")
            result.evidence = None

    return result
```

### Partial Response Handling

Return partial results when some components fail:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DebateResult:
    verdict: str
    confidence: float
    agent_responses: list[str]
    # Optional enrichments
    evidence: Optional[list] = None
    explanations: Optional[dict] = None
    errors: list[str] = field(default_factory=list)

async def run_enriched_debate(debate):
    result = await run_core_debate(debate)

    # Attempt enrichments with graceful degradation
    enrichment_tasks = [
        ("evidence", collect_evidence(debate)),
        ("explanations", generate_explanations(debate)),
    ]

    for name, task in enrichment_tasks:
        try:
            setattr(result, name, await asyncio.wait_for(task, timeout=5.0))
        except asyncio.TimeoutError:
            result.errors.append(f"{name}: timeout")
        except Exception as e:
            result.errors.append(f"{name}: {e}")

    return result
```

### Timeout Handling

```python
from aragora.resilience import with_timeout, asyncio_timeout

# Decorator-based
@with_timeout(30.0)  # 30 second timeout
async def bounded_operation():
    return await slow_service.call()

# Context manager with fallback
async def with_timeout_fallback():
    try:
        async with asyncio_timeout(10.0):
            return await primary_service.call()
    except asyncio.TimeoutError:
        return await fallback_service.call()
```

### Cache Fallbacks

Use cached data when live data is unavailable:

```python
from aragora.cache import get_cache

cache = get_cache("debate_results")

async def get_debate_result(debate_id: str):
    # Try live data first
    try:
        result = await fetch_live_result(debate_id)
        await cache.set(debate_id, result, ttl=3600)
        return result
    except ServiceUnavailableError:
        # Fall back to cached data
        cached = await cache.get(debate_id)
        if cached:
            cached.is_stale = True
            return cached
        raise
```

### Health-Based Routing

Route requests based on service health:

```python
from aragora.resilience import HealthChecker, get_global_health_registry

# Register health checkers
primary_health = HealthChecker("primary-api")
backup_health = HealthChecker("backup-api")

async def resilient_api_call(request):
    if primary_health.get_status().is_healthy:
        try:
            result = await primary_api.call(request)
            primary_health.record_success()
            return result
        except Exception as e:
            primary_health.record_failure(str(e))

    if backup_health.get_status().is_healthy:
        result = await backup_api.call(request)
        backup_health.record_success()
        return result

    raise ServiceUnavailableError("All APIs unhealthy")
```

---

## SDK Error Handling

Error types and handling patterns for SDK clients.

### Error Response Format

All API errors return consistent JSON:

```json
{
  "error": "Human-readable error message",
  "code": "ERROR_CODE",
  "details": "Additional context",
  "suggestion": "How to fix the issue",
  "trace_id": "abc123"
}
```

### Error Codes Summary

See [ERROR_CODES.md](./error-codes) for complete reference. Key categories:

| Category | Status | Example Codes |
|----------|--------|---------------|
| Authentication | 401 | `AUTH_REQUIRED`, `TOKEN_EXPIRED` |
| Authorization | 403 | `FORBIDDEN`, `QUOTA_EXCEEDED` |
| Validation | 400 | `VALIDATION_ERROR`, `INVALID_AGENT` |
| Not Found | 404 | `DEBATE_NOT_FOUND`, `AGENT_NOT_FOUND` |
| Rate Limit | 429 | `RATE_LIMITED`, `API_RATE_LIMITED` |
| Server | 500 | `INTERNAL_ERROR`, `DATABASE_ERROR` |
| Unavailable | 503 | `SERVICE_UNAVAILABLE`, `AGENT_UNAVAILABLE` |

### Python SDK Error Handling

```python
from aragora import AragoraClient
from aragora.exceptions import (
    AragoraError,
    RateLimitExceededError,
    AuthorizationError,
    ValidationError,
)

client = AragoraClient()

try:
    debate = await client.debates.create(task="Analyze this proposal")
except RateLimitExceededError as e:
    # Retry with exponential backoff
    if hasattr(e, 'retry_after') and e.retry_after:
        await asyncio.sleep(e.retry_after)
        debate = await client.debates.create(task="Analyze this proposal")
except AuthorizationError as e:
    if "quota" in str(e).lower():
        # Upgrade plan or wait for quota reset
        raise UserFacingError("Monthly quota exceeded. Please upgrade your plan.")
    raise
except ValidationError as e:
    # Fix input and retry
    logger.error(f"Invalid input: {e.details}")
    raise
except AragoraError as e:
    # Generic error handling
    logger.error(f"API Error: {e.message}", extra=e.details)
    raise
```

### TypeScript SDK Error Handling

```typescript
import { AragoraClient, AragoraError } from '@aragora/sdk';

const client = new AragoraClient();

try {
  const debate = await client.debates.create({ task: '...' });
} catch (error) {
  if (error instanceof AragoraError) {
    switch (error.code) {
      case 'RATE_LIMITED':
        await delay(error.retryAfter * 1000);
        return retry();
      case 'QUOTA_EXCEEDED':
        showUpgradePrompt();
        break;
      case 'VALIDATION_ERROR':
        showValidationErrors(error.details);
        break;
      case 'TOKEN_EXPIRED':
        await refreshToken();
        return retry();
      default:
        logError(error);
        showGenericError();
    }
  }
}
```

### SDK Best Practices

1. **Always include trace_id in error reports**
   ```python
   except AragoraError as e:
       logger.error(f"Error: {e.message}", trace_id=e.details.get("trace_id"))
   ```

2. **Implement exponential backoff for rate limits**
   ```python
   async def retry_with_backoff(func, max_retries=3):
       for attempt in range(max_retries):
           try:
               return await func()
           except RateLimitExceededError as e:
               if attempt == max_retries - 1:
                   raise
               delay = getattr(e, 'retry_after', None) or (2 ** attempt + random.random())
               await asyncio.sleep(delay)
   ```

3. **Handle partial failures gracefully**
   ```python
   result = await client.debates.create(task=task)
   if hasattr(result, 'warnings') and result.warnings:
       for warning in result.warnings:
           logger.warning(f"Partial failure: {warning}")
   ```

4. **Cache responses where appropriate**
   - Debate results after completion
   - Agent rankings (refresh hourly)
   - Static configuration

5. **Use webhooks instead of polling**
   ```python
   await client.webhooks.create(
       url="https://your-app.com/webhook",
       events=["debate.completed", "debate.verdict"]
   )
   ```

---

## Custom Error Types

When creating new error types, follow these conventions:

### For Domain Errors

Inherit from `AragoraError` and include structured details:

```python
from aragora.exceptions import AragoraError

class MyDomainError(AragoraError):
    """Raised when my domain operation fails."""

    def __init__(self, resource_id: str, reason: str):
        super().__init__(
            f"Operation failed for {resource_id}: {reason}",
            {"resource_id": resource_id, "reason": reason},
        )
        self.resource_id = resource_id
        self.reason = reason
```

### For Agent Errors

Inherit from `AgentError` and set the `recoverable` flag:

```python
from aragora.agents.errors.exceptions import AgentError

class MyAgentError(AgentError):
    def __init__(self, message: str, agent_name: str, recoverable: bool = True):
        super().__init__(message, agent_name=agent_name, recoverable=recoverable)
```

### Register HTTP Status Mapping

Add new exceptions to the exception handler middleware:

```python
# In aragora/server/middleware/exception_handler.py
EXCEPTION_STATUS_MAP["MyDomainError"] = 422  # Unprocessable Entity
```

---

## Best Practices

1. **Use specific exception types.** Catch `AgentTimeoutError` rather than bare `Exception`.
   This enables proper retry logic and HTTP status mapping.

2. **Always include context.** Pass `details` dicts to `AragoraError` for structured logging.

3. **Respect the `recoverable` flag.** Agent errors with `recoverable=True` are safe to retry.
   Errors with `recoverable=False` indicate permanent failures (bad input, auth issues).

4. **Use circuit breakers for external calls.** Any call to an AI provider, database, or
   external service should be wrapped with a circuit breaker.

5. **Configure per-provider thresholds.** Use `get_circuit_breaker_config(provider="...")` to
   get tuned defaults rather than hardcoding values.

6. **Keep fallback chains available for production.** OpenRouter fallback is enabled by
   default; store `OPENROUTER_API_KEY` in the configured secret provider to prevent
   single-provider outages from blocking debates.

7. **Use the middleware decorators in handlers.** Wrap all HTTP handlers with
   `@handle_exceptions` or `@async_handle_exceptions` for consistent error responses.

8. **Log with trace IDs.** The `ExceptionHandler` context manager generates trace IDs
   automatically. Include them in all error logs for debugging.

9. **Never expose internal errors to clients.** The middleware uses `safe_error_message()`
   to sanitize error messages before sending them to clients.

10. **Test error paths.** Use `CircuitBreaker.from_dict()` and `CircuitBreaker.to_dict()`
    to simulate and verify circuit breaker state transitions in tests.

---

## Prometheus Metrics

The resilience patterns export Prometheus metrics automatically:

| Metric | Type | Description |
|--------|------|-------------|
| `aragora_circuit_breaker_state` | Gauge | Current circuit state (0=closed, 1=open, 2=half-open) |
| `aragora_circuit_breaker_failures_total` | Counter | Total failure count per circuit |
| `aragora_circuit_breaker_state_changes_total` | Counter | State transition count |
| `aragora_retry_attempts_total` | Counter | Total retry attempts |
| `aragora_retry_exhausted_total` | Counter | Retries that exhausted all attempts |
| `aragora_timeout_total` | Counter | Operations that timed out |
| `aragora_fallback_activations_total` | Counter | Fallback chain activations |
| `aragora_fallback_success_total` | Counter | Successful fallback completions |
| `aragora_health_status` | Gauge | Component health (0=unhealthy, 1=healthy) |

### Monitoring Circuit Breaker Status

```python
from aragora.resilience import get_circuit_breaker_status, get_all_circuit_breakers_status

# Single circuit status
status = get_circuit_breaker_status("my-service")
# {"status": "closed", "failures": 0, "half_open_successes": 0}

# All circuits
all_status = get_all_circuit_breakers_status()
```

---

## Related Documentation

- [API Rate Limits](../api/rate-limits) - Rate limiting details
- [Error Codes](./error-codes) - Complete error code reference
- [Resilience Patterns](https://github.com/synaptent/aragora/blob/main/docs/resilience/RESILIENCE_PATTERNS.md) - Module overview
- [Agent Development](../core-concepts/agent-development) - Building resilient agents
- [Observability](../deployment/observability) - Metrics and monitoring
