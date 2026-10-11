# Resilience Patterns

The `aragora/resilience.py` module (34KB) implements circuit breaker patterns and fault tolerance for agent and API calls.

## Overview

The resilience module provides:
- **Circuit Breaker** - Prevent cascading failures
- **Retry Logic** - Automatic retry with backoff
- **Fallback Handlers** - Graceful degradation
- **Health Tracking** - Monitor service health

## Circuit Breaker

The circuit breaker pattern prevents repeated calls to failing services.

### States

```
CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing) → CLOSED
```

| State | Behavior |
|-------|----------|
| **CLOSED** | Requests pass through normally |
| **OPEN** | Requests fail immediately |
| **HALF_OPEN** | Limited requests to test recovery |

### Usage

```python
from aragora.resilience import CircuitBreaker, CircuitBreakerConfig

# Create circuit breaker
breaker = CircuitBreaker(
    name="openai_api",
    config=CircuitBreakerConfig(
        failure_threshold=5,      # Failures before opening
        success_threshold=3,      # Successes to close from half-open
        timeout_seconds=60,       # Time in open state before half-open
        half_open_max_calls=3,    # Max calls in half-open state
    )
)

# Use with async function
@breaker
async def call_openai(prompt: str) -> str:
    return await openai_client.complete(prompt)

# Or manually
async def call_api():
    if breaker.allow_request():
        try:
            result = await api_call()
            breaker.record_success()
            return result
        except Exception as e:
            breaker.record_failure()
            raise
    else:
        raise CircuitOpenError("Circuit is open")
```

### Global Circuit Breaker Registry

```python
from aragora.resilience import (
    get_circuit_breaker,
    reset_all_circuit_breakers,
    get_circuit_breaker_stats,
)

# Get or create circuit breaker by name
breaker = get_circuit_breaker("anthropic_api")

# Reset all breakers (useful for testing)
reset_all_circuit_breakers()

# Get statistics
stats = get_circuit_breaker_stats()
# {"anthropic_api": {"state": "closed", "failures": 0, ...}}
```

## Retry Logic

Automatic retry with configurable backoff strategies.

### Configuration

```python
from aragora.resilience import RetryConfig, with_retry

config = RetryConfig(
    max_retries=3,
    initial_delay=1.0,          # First retry delay (seconds)
    max_delay=30.0,             # Maximum delay
    backoff_multiplier=2.0,     # Exponential backoff factor
    jitter=0.1,                 # Random jitter (0.0 - 1.0)
    retry_on=[                  # Exceptions to retry
        "RateLimitError",
        "TimeoutError",
        "ConnectionError",
    ],
    dont_retry_on=[             # Exceptions to fail immediately
        "AuthenticationError",
        "InvalidRequestError",
    ],
)

@with_retry(config)
async def call_with_retry():
    return await api_call()
```

### Backoff Strategies

```python
from aragora.resilience import BackoffStrategy

# Exponential backoff (default)
# Delays: 1s, 2s, 4s, 8s, ...
config = RetryConfig(backoff_strategy=BackoffStrategy.EXPONENTIAL)

# Linear backoff
# Delays: 1s, 2s, 3s, 4s, ...
config = RetryConfig(backoff_strategy=BackoffStrategy.LINEAR)

# Constant backoff
# Delays: 1s, 1s, 1s, 1s, ...
config = RetryConfig(backoff_strategy=BackoffStrategy.CONSTANT)
```

## Fallback Handlers

Graceful degradation when primary service fails.

```python
from aragora.resilience import with_fallback, FallbackHandler

# Simple fallback value
@with_fallback(default_value={"status": "unavailable"})
async def get_status():
    return await external_service.status()

# Fallback function
async def cached_result():
    return cache.get("last_known_status")

@with_fallback(fallback_fn=cached_result)
async def get_status_with_cache():
    return await external_service.status()

# Chained fallbacks
@with_fallback(
    fallbacks=[
        cached_result,           # Try cache first
        default_status,          # Then default
    ]
)
async def get_status_resilient():
    return await external_service.status()
```

## Health Tracking

Monitor service health over time.

```python
from aragora.resilience import HealthTracker, HealthStatus

tracker = HealthTracker(
    name="openai",
    window_size=100,        # Track last 100 calls
    unhealthy_threshold=0.5 # 50% failure rate = unhealthy
)

# Record outcomes
tracker.record_success(latency_ms=150)
tracker.record_failure(error="timeout")

# Check health
status = tracker.get_status()
print(status.healthy)           # True/False
print(status.success_rate)      # 0.0 - 1.0
print(status.avg_latency_ms)    # Average latency
print(status.recent_errors)     # List of recent errors
```

### Health Aggregation

```python
from aragora.resilience import HealthAggregator

aggregator = HealthAggregator()
aggregator.add_tracker(openai_tracker)
aggregator.add_tracker(anthropic_tracker)
aggregator.add_tracker(database_tracker)

# Overall system health
overall = aggregator.get_overall_health()
print(overall.status)  # HEALTHY, DEGRADED, UNHEALTHY
print(overall.services)  # Per-service status
```

## Integration with Agents

The resilience module integrates with agent calls:

```python
from aragora.agents import Agent
from aragora.resilience import CircuitBreaker

# Agents have built-in circuit breakers
agent = Agent(
    name="gpt-4",
    circuit_breaker=CircuitBreaker(
        name="gpt-4",
        config=CircuitBreakerConfig(
            failure_threshold=3,
            timeout_seconds=30,
        )
    )
)

# Arena uses resilience for all agent calls
from aragora.debate import Arena

arena = Arena(
    agents=[agent1, agent2],
    resilience_config={
        "enable_circuit_breakers": True,
        "enable_retries": True,
        "fallback_to_openrouter": True,
    }
)
```

When `fallback_to_openrouter` is enabled and `OPENROUTER_API_KEY` is configured,
Aragora will also fall back if provider API keys are missing.

## Configuration

Environment variables:

```bash
# Circuit breaker defaults
ARAGORA_CB_FAILURE_THRESHOLD=5
ARAGORA_CB_SUCCESS_THRESHOLD=3
ARAGORA_CB_TIMEOUT_SECONDS=60

# Retry defaults
ARAGORA_RETRY_MAX_ATTEMPTS=3
ARAGORA_RETRY_INITIAL_DELAY=1.0
ARAGORA_RETRY_MAX_DELAY=30.0

# Health tracking
ARAGORA_HEALTH_WINDOW_SIZE=100
ARAGORA_HEALTH_UNHEALTHY_THRESHOLD=0.5
```

## Metrics

The resilience module exposes Prometheus metrics:

```
# Circuit breaker state changes
aragora_circuit_breaker_state{name="openai"} 0  # 0=closed, 1=open, 2=half_open

# Request outcomes
aragora_resilience_requests_total{name="openai", outcome="success"} 1234
aragora_resilience_requests_total{name="openai", outcome="failure"} 12

# Retry attempts
aragora_resilience_retries_total{name="openai"} 45

# Latency histogram
aragora_resilience_latency_seconds{name="openai", quantile="0.99"} 0.5
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Overall system health |
| `/api/health/services` | GET | Per-service health |
| `/api/admin/circuit-breakers` | GET | Circuit breaker status |
| `/api/admin/circuit-breakers/reset` | POST | Reset all breakers |

## See Also

- [AGENT_DEVELOPMENT.md](../debate/AGENT_DEVELOPMENT.md) - Agent implementation
- [MONITORING_SETUP.md](../guides/MONITORING_SETUP.md) - Metrics and monitoring
- [OPERATIONS.md](../operations/OPERATIONS.md) - Operational procedures
