---
title: Error Codes Reference
description: Error Codes Reference
---

# Error Codes Reference

Complete reference for Aragora API error codes and handling.

## Error Response Format

All API errors follow this format:

```json
{
  "error": "Human-readable error message",
  "code": "ERROR_CODE",
  "details": "Additional context (optional)",
  "suggestion": "How to fix the issue (optional)",
  "trace_id": "abc123"
}
```

## HTTP Status Codes

| Status | Meaning | When Used |
|--------|---------|-----------|
| 400 | Bad Request | Invalid input, validation errors |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource state conflict |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected server error |
| 502 | Bad Gateway | Upstream service error |
| 503 | Service Unavailable | Service temporarily unavailable |
| 504 | Gateway Timeout | Upstream service timeout |

## Error Codes by Category

### Authentication Errors (401)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `AUTH_REQUIRED` | Authentication required | No auth token provided | Include `Authorization: Bearer <token>` header |
| `TOKEN_INVALID` | Invalid authentication token | Token malformed or corrupted | Generate a new API token |
| `TOKEN_EXPIRED` | Authentication token has expired | JWT expired | Refresh the token or re-authenticate |
| `TOKEN_REVOKED` | Token has been revoked | Token manually invalidated | Generate a new API token |

### Authorization Errors (403)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `FORBIDDEN` | Access denied | Insufficient permissions | Request appropriate role/permissions |
| `QUOTA_EXCEEDED` | API quota exceeded | Monthly limit reached | Upgrade plan or wait for reset |
| `FEATURE_DISABLED` | Feature not available on your plan | Plan limitation | Upgrade to access feature |
| `ORG_MEMBER_LIMIT` | Organization member limit reached | Too many members | Upgrade plan or remove members |
| `LOCKOUT_ACTIVE` | Account is locked | Payment failure | Update payment method |

### Validation Errors (400)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `VALIDATION_ERROR` | Input validation failed | Invalid request data | Check request body against API docs |
| `INVALID_JSON` | Invalid JSON in request body | Malformed JSON | Validate JSON syntax |
| `MISSING_FIELD` | Required field missing: \{field\} | Missing required parameter | Include all required fields |
| `INVALID_FIELD` | Invalid value for field: \{field\} | Invalid parameter value | Check field type and constraints |
| `INVALID_AGENT` | Unknown agent: \{agent_id\} | Agent doesn't exist | Use valid agent ID from /api/agents |
| `INVALID_MODE` | Unknown debate mode: \{mode\} | Invalid mode specified | Use: standard, graph, matrix |
| `TOO_MANY_AGENTS` | Maximum \{n\} agents allowed | Too many agents requested | Reduce number of agents |
| `TOO_FEW_AGENTS` | Minimum 2 agents required | Not enough agents | Add more agents |

### Resource Not Found (404)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `DEBATE_NOT_FOUND` | Debate not found | Debate ID doesn't exist | Verify debate ID |
| `AGENT_NOT_FOUND` | Agent not found | Agent ID doesn't exist | Use valid agent ID |
| `DOCUMENT_NOT_FOUND` | Document not found | Document ID doesn't exist | Verify document ID |
| `REPLAY_NOT_FOUND` | Replay not found | Replay ID doesn't exist | Verify replay ID |
| `TOURNAMENT_NOT_FOUND` | Tournament not found | Tournament ID doesn't exist | Verify tournament ID |
| `BREAKPOINT_NOT_FOUND` | Breakpoint not found | Breakpoint ID doesn't exist | Verify breakpoint ID |
| `USER_NOT_FOUND` | User not found | User ID doesn't exist | Verify user ID |
| `ORG_NOT_FOUND` | Organization not found | Org ID doesn't exist | Verify organization ID |

### Conflict Errors (409)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `DEBATE_ALREADY_STARTED` | Debate has already started | Cannot modify running debate | Create new debate |
| `DEBATE_ALREADY_ENDED` | Debate has already ended | Cannot interact with ended debate | Access via replay API |
| `ALREADY_VOTED` | Already voted this round | Duplicate vote submission | Wait for next round |
| `BREAKPOINT_RESOLVED` | Breakpoint already resolved | Cannot modify resolved breakpoint | N/A |
| `INVITATION_USED` | Invitation already used | Token already accepted | Request new invitation |

### Rate Limiting (429)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `RATE_LIMITED` | Rate limit exceeded | Too many requests | Wait and retry with backoff |
| `DEBATE_RATE_LIMITED` | Debate creation rate limited | Too many debates | Wait \{n\} seconds |
| `API_RATE_LIMITED` | API rate limit exceeded | General rate limit | Implement exponential backoff |

Rate limit headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1705312200
Retry-After: 60
```

### Server Errors (500)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `INTERNAL_ERROR` | Internal server error | Unexpected error | Retry or contact support |
| `DATABASE_ERROR` | Database operation failed | DB connectivity issue | Retry later |
| `STORAGE_ERROR` | Storage operation failed | File system issue | Retry later |

### Service Unavailable (503)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `SERVICE_UNAVAILABLE` | Service temporarily unavailable | Maintenance or overload | Retry later |
| `AGENT_UNAVAILABLE` | Agent service unavailable | Agent API down | Use fallback agents |
| `VERIFICATION_UNAVAILABLE` | Verification backend unavailable | Z3/Lean not available | Skip verification |
| `TOURNAMENT_UNAVAILABLE` | Tournament system unavailable | Feature disabled | Check configuration |

### Gateway Errors (502, 504)

| Code | Message | Cause | Solution |
|------|---------|-------|----------|
| `AGENT_ERROR` | Agent returned an error | Upstream agent failure | Retry or use different agent |
| `AGENT_TIMEOUT` | Agent request timed out | Agent too slow | Increase timeout or use faster agent |
| `UPSTREAM_ERROR` | Upstream service error | External API failure | Retry later |

## Debate-Specific Errors

### Debate Lifecycle

| Code | Status | Message |
|------|--------|---------|
| `DEBATE_NOT_STARTED` | 400 | Debate has not started yet |
| `DEBATE_IN_PROGRESS` | 409 | Debate is currently in progress |
| `DEBATE_PAUSED` | 409 | Debate is paused |
| `DEBATE_CANCELLED` | 410 | Debate was cancelled |
| `DEBATE_FAILED` | 500 | Debate failed to complete |

### Consensus Errors

| Code | Status | Message |
|------|--------|---------|
| `NO_CONSENSUS` | 200 | Consensus not reached (not an error) |
| `CONSENSUS_TIMEOUT` | 504 | Consensus timed out |
| `HOLLOW_CONSENSUS` | 200 | Hollow consensus detected |

### Verification Errors

| Code | Status | Message |
|------|--------|---------|
| `VERIFICATION_FAILED` | 400 | Claim could not be verified |
| `PROOF_INVALID` | 400 | Proof is invalid |
| `Z3_NOT_AVAILABLE` | 503 | Z3 backend not available |
| `LEAN_NOT_AVAILABLE` | 503 | Lean backend not available |

## Billing Errors

| Code | Status | Message |
|------|--------|---------|
| `PAYMENT_REQUIRED` | 402 | Payment required |
| `PAYMENT_FAILED` | 402 | Payment processing failed |
| `SUBSCRIPTION_CANCELLED` | 403 | Subscription has been cancelled |
| `TRIAL_EXPIRED` | 403 | Trial period has expired |
| `INVOICE_NOT_FOUND` | 404 | Invoice not found |

## Error Handling Best Practices

### Retry Strategy

```python
import time
import random

def request_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait = e.retry_after or (2 ** attempt + random.random())
            time.sleep(wait)
        except ServerError as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
```

### Error Response Handling

```typescript
try {
  const debate = await client.debates.create({ task: '...' });
} catch (error) {
  if (error instanceof AragoraError) {
    switch (error.code) {
      case 'QUOTA_EXCEEDED':
        showUpgradePrompt();
        break;
      case 'RATE_LIMITED':
        await delay(error.retryAfter * 1000);
        return retry();
      case 'VALIDATION_ERROR':
        showValidationErrors(error.details);
        break;
      default:
        logError(error);
        showGenericError();
    }
  }
}
```

### Logging Errors

Always include the trace ID when reporting issues:

```python
try:
    response = client.debates.create(...)
except AragoraError as e:
    logger.error(
        "API Error",
        code=e.code,
        message=e.message,
        trace_id=e.trace_id,  # Include for support
        details=e.details,
    )
```

## Webhooks Error Payloads

Webhook error events include:

```json
{
  "event": "debate.failed",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "data": {
      "debate_id": "dbt_abc123",
      "error": {
        "code": "AGENT_TIMEOUT",
        "message": "Agent anthropic-api timed out",
        "trace_id": "xyz789"
      }
    }
  }
```

## RLM (Context Compression) Errors

| Code | Status | Message | Solution |
|------|--------|---------|----------|
| `RLM_UNAVAILABLE` | 503 | RLM compression service unavailable | RLM backend not configured |
| `CONTEXT_NOT_FOUND` | 404 | Context ID not found | Verify context ID from compress response |
| `CONTENT_TOO_LARGE` | 413 | Content exceeds 10MB limit | Split content into smaller chunks |
| `INVALID_SOURCE_TYPE` | 400 | Invalid source_type | Use: text, code, document, conversation |
| `INVALID_COMPRESSION_LEVELS` | 400 | Levels must be 1-5 | Reduce compression levels |
| `INVALID_QUERY_STRATEGY` | 400 | Invalid query strategy | Use: auto, bm25, semantic, hybrid |

## Knowledge Errors

| Code | Status | Message | Solution |
|------|--------|---------|----------|
| `KNOWLEDGE_NOT_FOUND` | 404 | Knowledge item not found | Verify item ID |
| `INGESTION_FAILED` | 500 | Knowledge ingestion failed | Check content format |
| `RETRIEVAL_FAILED` | 500 | Knowledge retrieval failed | Retry or check embeddings |

## Workflow Errors

| Code | Status | Message | Solution |
|------|--------|---------|----------|
| `WORKFLOW_NOT_FOUND` | 404 | Workflow not found | Verify workflow ID |
| `WORKFLOW_INVALID` | 400 | Invalid workflow definition | Check workflow YAML syntax |
| `NODE_EXECUTION_FAILED` | 500 | Workflow node failed | Check node configuration |
| `WORKFLOW_TIMEOUT` | 504 | Workflow execution timed out | Increase timeout or simplify workflow |

## Checkpoint Errors

| Code | Status | Message | Solution |
|------|--------|---------|----------|
| `CHECKPOINT_NOT_FOUND` | 404 | Checkpoint not found | Verify checkpoint ID |
| `CHECKPOINT_EXPIRED` | 410 | Checkpoint has expired | Checkpoints expire after 24h |
| `CHECKPOINT_CORRUPTED` | 500 | Checkpoint data corrupted | Create new debate |
| `RESUME_FAILED` | 500 | Failed to resume from checkpoint | Verify checkpoint integrity |

## Related Documentation

- [API Reference](../api/reference) - Full API documentation
- [WebSocket Events](../guides/websocket-events) - Real-time event reference
- [Rate Limiting](../api/reference#rate-limits) - Rate limit details
- [API Quick Start](../guides/api-quickstart) - Getting started guide
