# HTTP request lifecycle

## Successful responses are not replayed on a decoding failure

Once the TypeScript client's HTTP request receives a successful response
(`Response.ok`), reading or decoding that response cannot trigger another network
attempt. This applies to `request`, the HTTP helpers, and namespaces using them,
even when retries are enabled. An unrelated failed body read propagates its
original error; invalid JSON propagates `SyntaxError`. The client's own deadline
abort becomes the existing SDK `TimeoutError`, without replaying the request.

This intentionally changes older SDK behavior that could repeat an operation
after its successful response failed to decode. The server may already have
performed the operation: do not blindly retry a creation or other side effect
from a catch handler. Inspect its state through an existing lookup interface
before deciding whether another operation is appropriate. This is not a guarantee
of exactly-once execution or an idempotency mechanism.

```typescript
try {
  const result = await client.post('/api/v1/debates', { task: 'Compare approaches' });
  console.log(result);
} catch (error) {
  // Handle the interruption; this catch intentionally sends no second request.
  console.error('Request failed; inspect operation state before retrying.', error);
}
```

JSON, text, and empty-response return values are unchanged. Failed HTTP responses
and failures before a response keep their existing retry rules, attempt counts,
backoff, and error classification, except that the configured attempt deadline
now also covers response-body consumption.

## Attempt deadlines and cleanup

Each attempt's existing timeout remains active from the start of `fetch` through
reading a successful or error response body. Per-request `timeout` overrides the
client default as before. A stalled body is interrupted with the existing SDK
`TimeoutError`; an error-body parsing fallback cannot hide this deadline abort.
The client clears its attempt timer on success, decoding failure, fetch failure,
and timeout, before any retry backoff. Concurrent requests own separate timers.

The deadline relies on Fetch's abort-aware body consumption. It does not preempt
synchronous JavaScript such as JSON decoding, create an overall retry deadline,
or change WebSocket/reconnect behavior. A timeout after successful headers still
does not prove the server operation failed: inspect its state before retrying.
