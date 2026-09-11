# Python HTTP request lifecycle

## Rate limits

Both `AragoraClient` and `AragoraAsyncClient` preserve HTTP 429 responses as
`RateLimitError`, including the status, message, error code, trace ID and decoded
response body. `retry_after` remains an integer number of seconds or `None`.

The SDK accepts non-negative integer `Retry-After` delay-seconds and HTTP dates,
as described in [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).
Future dates use the local UTC clock and round the remaining delay up to whole
seconds; past dates yield zero. Keep the client machine's clock synchronized.
Malformed, negative, missing, or platform-timer-unrepresentable hints yield
`None`, without hiding the original rate-limit diagnostics.

Within the existing attempt budget, a usable hint is the delay before the next
attempt. **Zero means no delay**, not exponential backoff. Unavailable hints keep
the existing `retry_delay * 2**attempt` fallback. This does not change which
requests are retried, the number of attempts, or server-error retry behavior.
After the budget is exhausted, the final `RateLimitError` is raised.

```python
from aragora_sdk import AragoraClient, RateLimitError

with AragoraClient(base_url="http://localhost:8080", max_retries=1) as client:
    try:
        result = client.request("GET", "/api/v1/debates")
    except RateLimitError as error:
        # Do not add an unconditional retry: the SDK already used its configured budget.
        print(error.status_code, error.error_code, error.trace_id, error.retry_after)
```

The same diagnostics are available with `async with AragoraAsyncClient(...)`
and `await client.request(...)`. This contract does not add a global deadline,
cancellation API, or new exception type.
