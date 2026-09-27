---
title: Scaling Guide
description: Scaling Guide
---

# Scaling Guide

This guide covers Aragora's performance characteristics, scaling limits, and deployment strategies for production workloads.

## Quick Reference

| Resource | Default Limit | Tunable | Environment Variable |
|----------|---------------|---------|---------------------|
| Concurrent debates | 10 | Yes | `ARAGORA_MAX_CONCURRENT_DEBATES` |
| WebSocket connections (per IP) | 10 | Yes | `ARAGORA_WS_MAX_PER_IP` |
| Database connections | 10 | Yes | `ARAGORA_DB_POOL_SIZE` |
| Rate limit (per IP) | 120 req/min | Yes | `ARAGORA_IP_RATE_LIMIT` |
| Max agents per debate | 10 | Yes | `ARAGORA_MAX_AGENTS_PER_DEBATE` |

## Architecture Overview

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │  (nginx/ALB)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       ┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼─────┐
       │   Server    │ │  Server   │ │  Server   │
       │  Instance 1 │ │ Instance 2│ │ Instance N│
       └──────┬──────┘ └─────┬─────┘ └─────┬─────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       ┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼─────┐
       │   SQLite/   │ │   Redis   │ │  Supabase │
       │  PostgreSQL │ │  (cache)  │ │  (cloud)  │
       └─────────────┘ └───────────┘ └───────────┘
```

## Performance Baselines

### Single Instance Performance

Tested on AWS t3.medium (2 vCPU, 4GB RAM):

| Metric | Value | Notes |
|--------|-------|-------|
| Requests per second | 500 RPS | Static endpoints |
| WebSocket connections | 500 concurrent | With keep-alive |
| Concurrent debates | 5 | CPU-bound by LLM calls |
| Memory usage (idle) | 200 MB | Base server |
| Memory usage (loaded) | 800 MB | 5 concurrent debates |
| Debate latency (3 rounds) | 30-60s | Depends on LLM provider |

### Horizontal Scaling

| Instances | Concurrent Debates | WebSocket Connections | Notes |
|-----------|-------------------|----------------------|-------|
| 1 | 5-10 | 500 | Single instance |
| 3 | 15-30 | 1,500 | Load balanced |
| 5 | 25-50 | 2,500 | Recommended for production |
| 10 | 50-100 | 5,000 | Enterprise scale |

## Connection Limits

### WebSocket Connections

Default limits are enforced per connection/IP:

| Setting | Default | Environment Variable |
|---------|---------|----------------------|
| Max message size | 64KB | `ARAGORA_WS_MAX_MESSAGE_SIZE` |
| Heartbeat interval | 30s | `ARAGORA_WS_HEARTBEAT` |
| Connections per IP per minute | 30 | `ARAGORA_WS_CONN_RATE` |
| Max concurrent per IP | 10 | `ARAGORA_WS_MAX_PER_IP` |
| Messages per second | 10 | `ARAGORA_WS_MSG_RATE` |
| Message burst size | 20 | `ARAGORA_WS_MSG_BURST` |

There is no global connection cap; use OS limits and a load balancer to scale.

**Tuning for high concurrency:**
```bash
# Increase file descriptor limits
ulimit -n 65535

# Kernel tuning (Linux)
sysctl -w net.core.somaxconn=65535
sysctl -w net.ipv4.tcp_max_syn_backlog=65535
```

### Database Connections

**SQLite (local development):**
- Single-writer, multiple-reader model
- Connection pooling: 1-5 connections
- WAL mode enabled for better concurrency

**PostgreSQL (production):**
```bash
# Connection pool size
export ARAGORA_DB_POOL_SIZE=20
export ARAGORA_DB_POOL_MAX_OVERFLOW=10
export ARAGORA_DB_POOL_TIMEOUT=30
```

**Supabase (cloud):**
- Connection pooling via PgBouncer
- Default: 20 connections per instance
- Pooler mode: transaction

## Memory Management

### Memory Tiers

Aragora uses a multi-tier memory system to manage context:

| Tier | TTL | Size Limit | Purpose |
|------|-----|------------|---------|
| Fast | 1 min | 10 KB | Immediate context |
| Medium | 1 hour | 100 KB | Session memory |
| Slow | 1 day | 1 MB | Cross-session |
| Glacial | 1 week | 10 MB | Long-term patterns |

### Memory Usage Per Debate

| Component | Memory | Notes |
|-----------|--------|-------|
| Debate context | 50-200 KB | Depends on rounds |
| Agent state | 10-50 KB per agent | Includes persona |
| WebSocket buffer | 64 KB max | Per connection |
| Embedding cache | 5-20 MB | If ML features enabled |

**Estimating memory for N concurrent debates:**
```
Memory (MB) = 200 + (N * 500) + (agents_per_debate * 50)
```

## Rate Limiting

### Default Configuration

```python
# aragora/config/settings.py
ARAGORA_RATE_LIMIT = 60          # requests per minute (authenticated)
ARAGORA_IP_RATE_LIMIT = 120      # requests per minute (per IP)
ARAGORA_BURST_MULTIPLIER = 2.0   # burst allowance
```

### Rate Limit Tiers

| Tier | Limit | Window | Use Case |
|------|-------|--------|----------|
| Anonymous | 30/min | 60s | Public API |
| Authenticated | 60/min | 60s | Standard users |
| Premium | 300/min | 60s | Paid plans |
| Internal | Unlimited | - | Service-to-service |

### Redis-backed Rate Limiting

For distributed rate limiting across instances:

```bash
export ARAGORA_REDIS_URL=redis://localhost:6379
export ARAGORA_REDIS_KEY_PREFIX=aragora:ratelimit:
export ARAGORA_REDIS_TTL=120
```

## Horizontal Scaling

### Stateless Design

Aragora is designed to be stateless at the application layer:
- No sticky sessions required
- State stored in database/Redis
- WebSocket connections can be load-balanced

### Load Balancer Configuration

**nginx example:**
```nginx
upstream aragora {
    least_conn;
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
    server 10.0.1.12:8080;
}

server {
    listen 80;

    location / {
        proxy_pass http://aragora;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }
}
```

**AWS ALB:**
- Target group with health checks on `/api/health`
- Sticky sessions: disabled
- WebSocket support: enabled
- Connection draining: 30s

### Auto-scaling Triggers

| Metric | Scale Up | Scale Down |
|--------|----------|------------|
| CPU utilization | > 70% for 3 min | < 30% for 10 min |
| Active debates | > 80% capacity | < 20% capacity |
| WebSocket connections | > 800/instance | < 200/instance |
| Memory | > 80% | < 40% |

## Database Scaling

### SQLite to PostgreSQL Migration

For production deployments with >100 concurrent users:

```bash
# Switch to PostgreSQL
export DATABASE_URL=postgresql://user:pass@host:5432/aragora

# Run migrations
python scripts/migrate_sqlite_to_postgres.py
```

### PostgreSQL Tuning

Recommended settings for Aragora workloads:

```sql
-- Connection pooling
max_connections = 200
shared_buffers = 256MB

-- Query performance
effective_cache_size = 1GB
work_mem = 64MB

-- Write performance (for debates)
wal_level = minimal
synchronous_commit = off  # Only for non-critical data
```

### Supabase Configuration

For cloud deployments:

1. Enable connection pooler (PgBouncer)
2. Set pool mode to "transaction"
3. Configure Row Level Security for multi-tenancy
4. Enable read replicas for analytics queries

## Caching Strategy

### Redis Caching

```bash
export ARAGORA_REDIS_URL=redis://localhost:6379
export ARAGORA_CACHE_TTL=300  # 5 minutes
```

**What to cache:**
- Agent ELO ratings (60s TTL)
- Trending topics (300s TTL)
- Debate summaries (3600s TTL)
- User preferences (3600s TTL)

**What NOT to cache:**
- Active debate state (real-time)
- Authentication tokens
- Rate limit counters (use Redis directly)

### Embedding Cache

For ML features (similarity search, convergence detection):

```bash
export ARAGORA_EMBEDDING_CACHE_SIZE=1000  # Max cached embeddings
export ARAGORA_EMBEDDING_CACHE_TTL=86400  # 24 hours
```

## Monitoring

### SLO Targets (Enforced in CI)

These SLOs are enforced by the load test workflow (`.github/workflows/load-tests.yml`):

| Metric | SLO Target | Description |
|--------|------------|-------------|
| p50 latency | < 200ms | Median response time |
| p95 latency | < 500ms | 95th percentile |
| p99 latency | < 2000ms | 99th percentile |
| Error rate | < 1% | HTTP error responses |
| Throughput | > 50 RPS | Minimum requests/second |

### Key Metrics to Watch

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Response time (p99) | > 2s | > 5s | Scale up |
| Error rate | > 1% | > 5% | Investigate |
| Active debates | > 80% | > 95% | Scale up |
| Memory usage | > 70% | > 90% | Restart/scale |
| WebSocket disconnects | > 10/min | > 50/min | Check network |

### Prometheus Metrics

Enable with:
```bash
export ARAGORA_ENABLE_TELEMETRY=true
```

Key metrics exposed:
- `aragora_debates_active` - Current active debates
- `aragora_debates_total` - Total debates completed
- `aragora_websocket_connections` - Active WebSocket connections
- `aragora_api_request_duration_seconds` - Request latency histogram
- `aragora_agent_response_time_seconds` - LLM response time

### Health Check Endpoint

```
GET /api/health

Response:
{
  "status": "healthy",
  "version": "2.10.0",
  "uptime_seconds": 3600,
  "active_debates": 5,
  "websocket_connections": 150,
  "database": "connected",
  "redis": "connected"
}
```

## Load Testing

### Running Load Tests

```bash
# Install k6
brew install k6

# Run load test
k6 run scripts/load_test.js --vus 100 --duration 5m
```

### Sample Load Test Results

**Test: 100 concurrent users, 5 minutes**
```
scenarios: (100.00%) 1 scenario, 100 max VUs, 5m30s max duration
           * default: 100 looping VUs for 5m0s

     data_received..................: 45 MB  150 kB/s
     data_sent......................: 12 MB  40 kB/s
     http_req_duration..............: avg=145ms min=12ms med=98ms max=2.1s p(90)=312ms p(95)=456ms
     http_reqs......................: 20412  68/s
     vus............................: 100    min=100 max=100
     vus_max........................: 100    min=100 max=100
```

## Troubleshooting

### High Memory Usage

1. Check for memory leaks in long-running debates
2. Reduce embedding cache size
3. Lower concurrent debate limit
4. Enable memory profiling: `ARAGORA_MEMORY_PROFILING=true`

### Slow Response Times

1. Check LLM provider latency
2. Enable request tracing
3. Review database query performance
4. Check rate limit status

### WebSocket Disconnections

1. Verify load balancer WebSocket support
2. Check client-side keep-alive
3. Review server ping/pong settings
4. Check for connection limits

## Best Practices

1. **Start small**: Begin with single instance, scale based on metrics
2. **Monitor early**: Set up monitoring before scaling
3. **Use caching**: Redis caching reduces LLM calls significantly
4. **Rate limit**: Protect against abuse with tiered limits
5. **Health checks**: Use `/api/health` for load balancer routing
6. **Graceful degradation**: Queue debates when at capacity
7. **Connection pooling**: Use PgBouncer for PostgreSQL
8. **Log strategically**: Don't log full debate content in production

## Reference Links

- [Deployment Guide](./overview)
- [Operations Runbook](../operations/runbook)
- [Environment Variables](../getting-started/environment)
- [Rate Limiting](./rate-limiting)
