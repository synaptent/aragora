# HTTP request lifecycle

## Successful responses are not replayed on a decoding failure

Once the TypeScript client's HTTP request receives a successful response
(`Response.ok`), reading or decoding that response cannot trigger another network
attempt. This applies to `request`, the HTTP helpers, and namespaces using them,
even when retries are enabled. A failed body read propagates its original error;
invalid JSON propagates `SyntaxError`. Neither is reclassified as a connection,
timeout, or server error by the request retry loop.

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
backoff, and error classification. This change does not extend timeout coverage,
alter timer cleanup, add automatic reconnection, or change WebSocket behavior.
