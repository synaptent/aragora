# SDK Error Handling Guide

How to handle errors from the Aragora Python and TypeScript SDKs.

## Error Hierarchy

```
AragoraError
  |-- AuthenticationError   (401)
  |-- AuthorizationError    (403)
  |-- NotFoundError         (404)
  |-- RateLimitError        (429)
  |-- ValidationError       (400)
  |-- ServerError           (5xx)
  |-- TimeoutError
  |-- ConnectionError
```

All exceptions inherit from `AragoraError`, so a single `except AragoraError` catches everything.

## Error Properties

Every `AragoraError` carries:

| Property | Type | Description |
|----------|------|-------------|
| `message` | `str` | Human-readable error description |
| `status_code` | `int \| None` | HTTP status code (e.g. 429) |
| `error_code` | `str \| None` | Machine-readable code (e.g. `"RATE_LIMITED"`) |
| `trace_id` | `str \| None` | Unique request ID for support tickets |
| `response_body` | `Any` | Raw API response, if available |

`RateLimitError` adds `retry_after` (seconds until retry is safe).
`ValidationError` adds `errors` (list of field-level validation failures).

## Common Patterns

### 401 -- Authentication Failed

Your API key is missing, expired, or invalid.

```python
from aragora_sdk import AuthenticationError

try:
    result = client.debates.create(question="...", rounds=3)
except AuthenticationError:
    print("Check your API key. Set ARAGORA_API_KEY or pass api_key= to the client.")
```

### 429 -- Rate Limited

Honor the `retry_after` header. The SDK retries automatically up to `max_retries`.

```python
from aragora_sdk import RateLimitError
import time

try:
    result = client.debates.create(question="...", rounds=3)
except RateLimitError as e:
    wait = e.retry_after or 5
    print(f"Rate limited. Waiting {wait}s...")
    time.sleep(wait)
```

### 400 -- Validation Error

Inspect the `errors` array for field-level details.

```python
from aragora_sdk import ValidationError

try:
    result = client.debates.create(question="", rounds=-1)
except ValidationError as e:
    for err in e.errors:
        print(f"  {err['field']}: {err['message']}")
```

### 404 -- Resource Not Found

The debate or receipt ID does not exist.

```python
from aragora_sdk import NotFoundError

try:
    receipt = client.receipts.get("dbt_nonexistent")
except NotFoundError:
    print("Debate not found. Verify the debate_id.")
```

### 5xx -- Server Error

Transient failures. Retry with exponential backoff.

```python
from aragora_sdk import ServerError

try:
    result = client.debates.create(question="...", rounds=3)
except ServerError as e:
    print(f"Server error ({e.status_code}). Trace: {e.trace_id}")
```

## Retry Configuration

The SDK retries transient errors (429, 5xx, timeouts) automatically.

**Python:**

```python
client = AragoraClient(
    base_url="http://localhost:8080",
    api_key="your-key",
    max_retries=3,     # Retry up to 3 times
    retry_delay=1.0,   # Base delay (doubles each retry: 1s, 2s, 4s)
    timeout=30.0,      # Per-request timeout in seconds
)
```

**TypeScript:**

```typescript
const client = createClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'your-key',
  retryEnabled: true,  // Enable automatic retries
  timeout: 30000,      // Per-request timeout in ms
});
```

## Best Practices

1. **Catch `AragoraError` at the top level** as a safety net. Catch specific subtypes where you need custom handling.

```python
from aragora_sdk import AragoraError, RateLimitError

try:
    result = client.debates.create(question="...", rounds=3)
except RateLimitError as e:
    queue_for_retry(e.retry_after)
except AragoraError as e:
    log.error("Aragora API error: %s (trace: %s)", e.message, e.trace_id)
```

2. **Log `trace_id` for support.** Include it in bug reports -- it links to server-side request logs.

3. **Use circuit breakers for batch operations.** When running many debates in sequence, wrap calls in a circuit breaker to avoid cascading failures. See [Resilience Patterns](../resilience/RESILIENCE_PATTERNS.md).

4. **Validate inputs client-side.** Catch empty questions and invalid rounds before making API calls.

## Further Reading

- [Golden Path Tutorial](../tutorials/GOLDEN_PATH.md) -- end-to-end walkthrough
- [SDK Guide](../SDK_GUIDE.md) -- full Python and TypeScript reference
- [API Reference](../api/API_REFERENCE.md) -- REST endpoints and response schemas
- [Resilience Patterns](../resilience/RESILIENCE_PATTERNS.md) -- circuit breakers, retry, timeout
