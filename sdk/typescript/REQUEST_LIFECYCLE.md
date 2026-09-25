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

## Timeout phase diagnostics

The HTTP client keeps the existing SDK `TimeoutError` type and
`SERVICE_UNAVAILABLE` code. Its message distinguishes where the interruption
was observed:

- `Response body timeout`: a response arrived, but consuming its successful or
  error body timed out.
- `Request timeout`: the attempt timed out before `fetch` returned a response.
  This includes connecting or waiting for headers; it does not identify the
  network's precise failure point.

The phase is specific to the current attempt, even after an earlier HTTP failure.
It does not change retry rules, attempt budgets, or the no-replay guarantee for
successful responses. Neither message proves that the server did not perform
an operation, and a body timeout alone does not disclose the HTTP status.

```typescript
import { TimeoutError } from '@aragora/sdk';

try {
  await client.post('/api/v1/debates', { task: 'Compare approaches' });
} catch (error) {
  if (error instanceof TimeoutError && error.message === 'Response body timeout') {
    console.error('Response interrupted; inspect operation state before retrying.');
  } else {
    console.error('Request failed; server-side outcome may still be unknown.', error);
  }
  // No automatic retry is sent from either branch.
}
```
