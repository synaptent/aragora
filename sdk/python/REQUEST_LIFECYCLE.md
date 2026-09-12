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
Date hints must match a complete HTTP-date form (including the obsolete RFC 850
and asctime forms). Unknown zones, missing required components, trailing content,
or multiple coalesced hints are unavailable; a valid-looking prefix is not enough.
Calendar fields and the weekday must agree, and the resolved year must be at
least 1900. Four-digit years are literal, never expanded as two-digit years.
Obsolete RFC 850 two-digit years use the HTTP rolling fifty-calendar-year rule,
including the boundary time of day, rather than an email parser's fixed pivot.
The same captured UTC clock is used for century selection and the remaining delay.

Within the existing attempt budget, hints from **zero through 60 seconds** are
used before the next attempt. **Zero means no delay**, not exponential backoff.
A larger valid hint immediately raises the original `RateLimitError`, retaining
the full `retry_after` value and other diagnostics. The SDK does not sleep, clamp
the hint, or retry earlier than the server requested. This fixed one-minute
automatic-wait safety limit also covers future dates and local clock skew; it is
not a parser rejection or a total request deadline.

Unavailable hints keep the existing `retry_delay * 2**attempt` fallback, including
user-configured fallback delays above 60 seconds. The configured attempt budget
remains an upper bound; exhaustion raises the final `RateLimitError`. Other retry
behavior, including server-error handling, is unchanged.

```python
from aragora_sdk import AragoraClient, RateLimitError

with AragoraClient(base_url="http://localhost:8080", max_retries=1) as client:
    try:
        result = client.request("GET", "/api/v1/debates")
    except RateLimitError as error:
        # Do not retry unconditionally: the budget or automatic-wait limit may have stopped it.
        print(error.status_code, error.error_code, error.trace_id, error.retry_after)
```

The same diagnostics are available with `async with AragoraAsyncClient(...)`
and `await client.request(...)`. This contract does not add a global deadline,
cancellation API, or new exception type.

## Transport failures and cancellation

After the existing attempt budget is exhausted, both clients raise the existing
SDK `TimeoutError` for `httpx.TimeoutException` (including connect, read, write
and pool timeouts), or SDK `ConnectionError` for `httpx.ConnectError`.
Import these from `aragora_sdk`, not Python's built-in exception classes.
Both remain subclasses of `AragoraError`, keep the messages `Request timed out`
and `Connection failed`, and chain the final transport exception as `__cause__`.
No HTTP status, error code, trace ID or response body is fabricated.

The existing `max_retries` value is the maximum number of attempts, including
the first request. Retry counts and exponential backoff are unchanged, as is
successful recovery before exhaustion. This change does not newly wrap or retry
other transport errors, response-decoding failures or arbitrary exceptions.

```python
from aragora_sdk import AragoraClient, ConnectionError, TimeoutError

with AragoraClient(base_url="http://localhost:8080", max_retries=1) as client:
    try:
        result = client.request("GET", "/api/v1/debates")
    except (TimeoutError, ConnectionError) as error:
        # The configured attempt budget has already been consumed; do not retry blindly.
        print(type(error).__name__, error.message)
```

Use `with AragoraClient(...)` or `async with AragoraAsyncClient(...)` to close
the owned HTTP client after success or request failure. In asynchronous HTTP
usage, caller cancellation during a request or retry backoff propagates as
`asyncio.CancelledError` without another request attempt; context exit still
closes the HTTP client. Cleanup is not shielded from further cancellation.
This adds no cancellation API or total deadline and changes no WebSocket policy.
