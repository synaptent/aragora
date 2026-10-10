---
title: API Rate Limits
description: API Rate Limits
---

# API Rate Limits

> **Audience:** This guide is for **API consumers** who need to understand and work with rate limits.
> For implementation details and developer documentation, see [RATE_LIMITING.md](../deployment/rate-limiting).

Aragora implements rate limiting to ensure fair usage and service stability. This document describes the rate limiting system and how to work within its constraints.

## Rate Limit Tiers

Rate limits are based on your subscription tier:

| Tier | Requests/Minute | Burst Size | Notes |
|------|-----------------|------------|-------|
| **Free** | 10 | 60 | Unauthenticated or free tier |
| **Pro** | 200 | 400 | $49/seat/month |
| **Enterprise** | 1000 | 2000 | Custom limits available |

### What is "Burst Size"?

The burst size allows short spikes above your sustained rate. For example, a free tier user can make up to 60 requests in quick succession, but sustained usage must stay under 10 req/min.

## Default Limits

For endpoints without tier-specific limits:

| Limit Type | Default | Environment Variable |
|------------|---------|---------------------|
| Per-endpoint | 60 req/min | `ARAGORA_RATE_LIMIT` |
| Per-IP (global) | 120 req/min | `ARAGORA_IP_RATE_LIMIT` |
| Burst multiplier | 2x | `ARAGORA_BURST_MULTIPLIER` |

## Response Headers

Rate-limited responses include these headers:

```
X-RateLimit-Limit: 60          # Your rate limit
X-RateLimit-Remaining: 45      # Requests remaining in window
X-RateLimit-Reset: 1705123456  # Unix timestamp when limit resets
Retry-After: 30                # Seconds to wait (only on 429)
```

## Rate Limit Responses

When rate limited, the API returns:

```json
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 30

{
  "error": "Rate limit exceeded",
  "retry_after": 30,
  "limit": 60,
  "remaining": 0
}
```

## Best Practices

### 1. Implement Exponential Backoff

When you receive a 429 response, wait and retry with increasing delays:

```python
import time
import random

def make_request_with_backoff(url, max_retries=5):
    for attempt in range(max_retries):
        response = requests.get(url)

        if response.status_code != 429:
            return response

        # Get retry delay from header or calculate
        retry_after = int(response.headers.get('Retry-After', 0))
        if not retry_after:
            retry_after = min(60, (2 ** attempt) + random.random())

        time.sleep(retry_after)

    raise Exception("Max retries exceeded")
```

### 2. Monitor Your Usage

Check the `X-RateLimit-Remaining` header to see how many requests you have left:

```python
response = requests.get(f"{API_BASE}/api/debates")
remaining = int(response.headers.get('X-RateLimit-Remaining', 0))

if remaining < 10:
    print(f"Warning: Only {remaining} requests remaining")
```

### 3. Batch Operations When Possible

Instead of making many small requests, use batch endpoints:

```python
# Instead of this (10 requests):
for debate_id in debate_ids:
    response = requests.get(f"{API_BASE}/api/debates/{debate_id}")

# Do this (1 request):
response = requests.post(f"{API_BASE}/api/debates/batch", json={
    "debate_ids": debate_ids
})
```

### 4. Cache Responses

Cache responses that don't change frequently:

- Debate results (after completion)
- Agent rankings and ELO scores
- Historical analytics

### 5. Use Webhooks for Real-Time Updates

Instead of polling for debate status, register webhooks:

```python
requests.post(f"{API_BASE}/api/webhooks", json={
    "url": "https://your-app.com/webhook",
    "events": ["debate.completed", "debate.verdict"]
})
```

## Per-User Rate Limiting

For authenticated users, Aragora implements per-user rate limiting based on user ID rather than IP address. This provides fairer limits when users share IPs (e.g., corporate networks) and prevents abuse via IP rotation.

### Action-Based Limits

Different operations have different limits per authenticated user:

| Action | Limit (req/min) | Description |
|--------|-----------------|-------------|
| `default` | 60 | Default for authenticated requests |
| `debate_create` | 10 | Creating new debates |
| `vote` | 30 | Voting on proposals |
| `agent_call` | 120 | Calling agent APIs |
| `export` | 5 | Exporting data |
| `admin` | 300 | Admin operations |

### How It Works

1. **Authenticated requests** are rate-limited by `user_id`
2. **Unauthenticated requests** fall back to IP-based limiting
3. Each action has its own bucket (limits don't share)
4. Burst multiplier (2x) allows short spikes

### Response Headers

Per-user rate-limited responses include additional context:

```
X-RateLimit-Limit: 10           # Your limit for this action
X-RateLimit-Remaining: 7        # Requests remaining
X-RateLimit-Reset: 1705123456   # Reset timestamp
X-RateLimit-Action: debate_create  # Which action was limited
```

### Decorator Usage

Backend handlers use the `@user_rate_limit` decorator:

```python
from aragora.server.handlers.utils.rate_limit import user_rate_limit

class DebatesHandler(BaseHandler):
    @user_rate_limit(action="debate_create")
    def _create_debate(self, handler):
        # Limited to 10 debates/minute per user
        ...

    @user_rate_limit(action="vote")
    def _submit_vote(self, handler):
        # Limited to 30 votes/minute per user
        ...
```

### Checking Your Status

To see your current rate limit status across all actions:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://api.aragora.ai/api/rate-limit/status
```

Response:
```json
{
  "user_id": "user-123",
  "limits": {
    "debate_create": { "remaining": 8, "limit": 10, "retry_after": 0 },
    "vote": { "remaining": 30, "limit": 30, "retry_after": 0 }
  }
}
```

## Endpoint-Specific Limits

Some endpoints have stricter limits to prevent abuse:

| Endpoint | Limit | Notes |
|----------|-------|-------|
| `POST /api/debate` | 10/min | Debate creation is expensive |
| `POST /api/gauntlet` | 5/min | Stress tests are resource-intensive |
| `GET /api/health` | 120/min | Higher limit for monitoring |
| `GET /api/debates` | 60/min | Standard list endpoint |

## IP-Based Limits

In addition to tier limits, there's a global per-IP limit of **120 req/min** across all endpoints. This prevents a single source from overwhelming the API even with multiple accounts.

## Trusted Proxies

If you're behind a load balancer or proxy, configure `ARAGORA_TRUSTED_PROXIES` so rate limits apply to the real client IP:

```bash
export ARAGORA_TRUSTED_PROXIES="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
```

Entries are exact IPs, CIDR ranges or `localhost` (`127.0.0.1` and `::1`); an IPv4-mapped peer such as `::ffff:10.0.0.5` matches its IPv4 entry. The rate-limit middleware and handler-level limits choose and key the client IP the same way (IPv6 clients are grouped by /64; IPv4-mapped addresses are keyed as IPv4):

1. When the direct peer is listed, the rightmost `X-Forwarded-For` hop that is not itself a listed proxy is used. Earlier hops are client-supplied and never used. `X-Real-IP` is used only when `X-Forwarded-For` is absent or empty.
2. Any other peer is keyed on its own address, whatever headers it sends.

A listed proxy must add the address it saw as the last `X-Forwarded-For` hop (nginx's `$proxy_add_x_forwarded_for`, Caddy, Traefik and AWS ALB do by default); a proxy that sends no `X-Forwarded-For` must overwrite or strip a client-supplied `X-Real-IP`.

### Cloudflare

`CF-Connecting-IP` and `True-Client-IP` (sent with `CF-RAY`) are honoured only when the direct peer is listed in `ARAGORA_CLOUDFLARE_TRUSTED_PROXIES`, which uses the same entry syntax and is empty by default. List the peer that delivers Cloudflare traffic: the `cloudflared` address for a Cloudflare Tunnel, or Cloudflare's published edge ranges when the origin is reached directly. That peer must only carry traffic that came through Cloudflare, so never list a proxy (for example an nginx on the same host) that also accepts direct connections and passes client headers through.

```bash
# Cloudflare Tunnel: cloudflared on the same host connects straight to the API
export ARAGORA_CLOUDFLARE_TRUSTED_PROXIES="localhost"
```

Set it before deploying behind Cloudflare. Without it, requests are keyed on the Cloudflare peer, so clients share one bucket, or, when that peer is also in `ARAGORA_TRUSTED_PROXIES` (as `cloudflared` on `localhost` is by default), on the rightmost `X-Forwarded-For` hop, which Cloudflare's edge appends. When `CF-RAY` arrives from an unlisted peer the server logs one warning per process.

## Need Higher Limits?

Enterprise customers can request custom rate limits. Contact support or upgrade your tier at `/billing`.

## Debugging Rate Limits

To check your current rate limit status:

```bash
curl -v https://api.aragora.ai/api/health 2>&1 | grep -i ratelimit
```

Or in your code:

```python
response = requests.get(f"{API_BASE}/api/health")
print(f"Limit: {response.headers.get('X-RateLimit-Limit')}")
print(f"Remaining: {response.headers.get('X-RateLimit-Remaining')}")
print(f"Resets at: {response.headers.get('X-RateLimit-Reset')}")
```
