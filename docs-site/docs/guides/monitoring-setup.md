---
title: Monitoring Setup Guide
description: Monitoring Setup Guide
---

# Monitoring Setup Guide

**Last Updated:** January 18, 2026
**Document version:** 1.1.0

---

## Overview

Aragora uses a multi-layered observability stack for monitoring application health, performance, and security.

| Component | Purpose | Provider |
|-----------|---------|----------|
| Metrics | Application and infrastructure metrics | Prometheus + Grafana |
| Logging | Centralized log aggregation | Elasticsearch / CloudWatch |
| Tracing | Distributed request tracing | OpenTelemetry / Jaeger |
| Uptime | External availability monitoring | Uptime Kuma |
| Errors | Exception tracking and alerting | Sentry |
| APM | Application performance monitoring | OpenTelemetry |

---

## Environment Variables

Configure monitoring via environment variables in `.env`:

```bash
# Prometheus Metrics
METRICS_ENABLED=true
METRICS_PORT=9090

# OpenTelemetry Tracing
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=aragora-api

# Sentry Error Tracking
SENTRY_DSN=https://xxx@sentry.io/xxx
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

## Prometheus Metrics

### Enabling Metrics

```python
# Metrics are exposed by the MetricsHandler at /metrics.
from aragora.server.metrics import track_request

with track_request("/api/debates", "POST"):
    # handle request
    pass
```

### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `aragora_requests_total` | Counter | Total HTTP requests by endpoint, method, status |
| `aragora_request_duration_seconds` | Histogram | Request latency distribution |
| `aragora_debates_active` | Gauge | Currently running debates |
| `aragora_agent_calls_total` | Counter | LLM API calls by provider |
| `aragora_agent_latency_seconds` | Histogram | LLM response times |
| `aragora_consensus_reached_total` | Counter | Debates reaching consensus |
| `aragora_elo_updates_total` | Counter | ELO rating changes |
| `aragora_memory_tier_size` | Gauge | Memory tier occupancy |

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'aragora-api'
    static_configs:
      - targets: ['localhost:9090']
    metrics_path: /metrics

  - job_name: 'aragora-workers'
    static_configs:
      - targets: ['worker-1:9090', 'worker-2:9090']
```

### Key Prometheus Queries

```promql
# Request rate (per second)
rate(aragora_requests_total[5m])

# 95th percentile latency
histogram_quantile(0.95, rate(aragora_request_duration_seconds_bucket[5m]))

# Error rate
sum(rate(aragora_requests_total{status=~"5.."}[5m])) / sum(rate(aragora_requests_total[5m]))

# Active debates
aragora_debates_active

# LLM provider latency comparison
histogram_quantile(0.95, rate(aragora_agent_latency_seconds_bucket[5m])) by (provider)
```

---

## Grafana Dashboards

### Importing Dashboards

1. Access Grafana at `http://localhost:3000`
2. Go to Dashboards > Import
3. Upload JSON from `deploy/grafana/dashboards/`

### Available Dashboards

| Dashboard | ID | Description |
|-----------|-----|-------------|
| Aragora Overview | 1001 | High-level service health |
| API Performance | 1002 | Request latency and throughput |
| Agent Metrics | 1003 | LLM provider performance |
| Debate Analytics | 1004 | Consensus rates, rounds |
| Infrastructure | 1005 | CPU, memory, disk |

### Creating Alerts

```yaml
# Grafana alerting rule example
groups:
  - name: aragora-alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(aragora_requests_total{status=~"5.."}[5m]))
          / sum(rate(aragora_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }}"

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95, rate(aragora_request_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High API latency"
          description: "95th percentile latency is {{ $value }}s"

      - alert: AgentTimeout
        expr: |
          rate(aragora_agent_calls_total{status="timeout"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Agent timeouts increasing"
```

---

## OpenTelemetry Tracing

### Setup

```python
# aragora/observability/tracing.py
from aragora.observability.tracing import trace_handler

@trace_handler("debates.create")
def handle_create_debate(self, handler):
    ...
```

### Instrumented Components

| Component | Span Name | Attributes |
|-----------|-----------|------------|
| HTTP Handler | `http.request` | method, path, status |
| Debate Round | `debate.round` | round_number, agent_count |
| Agent Call | `agent.call` | provider, model, tokens |
| Database Query | `db.query` | operation, table |
| Memory Access | `memory.access` | tier, operation |

### Trace Sampling

```python
# Configure sampling rate
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

sampler = TraceIdRatioBased(0.1)  # Sample 10% of traces
provider = TracerProvider(sampler=sampler)
```

---

## Sentry Error Tracking

### Configuration

```python
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
    traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    integrations=[AsyncioIntegration()],
    # Scrub sensitive data
    before_send=scrub_pii,
)
```

### PII Scrubbing

```python
def scrub_pii(event, hint):
    """Remove PII from Sentry events."""
    if "request" in event:
        headers = event["request"].get("headers", {})
        # Remove auth headers
        headers.pop("Authorization", None)
        headers.pop("Cookie", None)
    return event
```

### Alert Rules

Configure in Sentry dashboard:
- Alert on new issues (first occurrence)
- Alert on regression (issue reoccurs after resolve)
- Alert on spike (>10 events in 5 minutes)
- Alert on specific error types (e.g., `AgentAPIError`)

---

## Uptime Kuma

### Current Monitors

Live at [status.aragora.ai](https://status.aragora.ai):

| Monitor | URL | Check Interval |
|---------|-----|----------------|
| API Health | `https://api.aragora.ai/api/health` | 60s |
| API Services | `https://api.aragora.ai/api/health/services` | 60s |
| WebSocket | `wss://api.aragora.ai/ws` | 60s |
| Website | `https://aragora.ai` | 60s |
| Live Dashboard | `https://live.aragora.ai` | 60s |
| ELO System | `https://api.aragora.ai/api/health/services` | 60s |

### Adding Monitors

1. Access Uptime Kuma at `https://status.aragora.ai/dashboard`
2. Click "Add New Monitor"
3. Configure:
   - Monitor Type: HTTP(s)
   - URL: Target endpoint
   - Heartbeat Interval: 60 seconds
   - Retries: 3
   - Keyword (optional): Expected response content

### Notification Channels

| Channel | Use For |
|---------|---------|
| Slack #alerts | All incidents |
| PagerDuty | Critical (P1) only |
| Email | Daily digest |

---

## Log Aggregation

### Structured Logging

```python
import structlog

logger = structlog.get_logger()

# Log with context
logger.info(
    "debate_started",
    debate_id=debate_id,
    agent_count=len(agents),
    topic=topic[:100],
)
```

### Log Levels

| Level | Use For | Examples |
|-------|---------|----------|
| DEBUG | Development details | Query timings, cache hits |
| INFO | Normal operations | Request handling, debate flow |
| WARNING | Recoverable issues | Rate limits, retries |
| ERROR | Failures | API errors, exceptions |
| CRITICAL | System failures | Database down, OOM |

### CloudWatch Configuration

```yaml
# cloudwatch-agent.json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/aragora/*.log",
            "log_group_name": "aragora-api",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
```

---

## SLO Definitions

### Availability SLO

| Service | Target | Measurement |
|---------|--------|-------------|
| API | 99.9% | Successful responses / Total requests |
| WebSocket | 99.5% | Connection uptime |
| Status Page | 99.99% | External ping success |

### Latency SLO

| Endpoint | P50 | P95 | P99 |
|----------|-----|-----|-----|
| `/api/health` | 10ms | 50ms | 100ms |
| `/api/debates` | 100ms | 500ms | 1s |
| Agent response | 2s | 5s | 10s |
| Consensus check | 50ms | 200ms | 500ms |

### Error Budget

```
Monthly Error Budget = 1 - SLO Target
99.9% SLO = 0.1% error budget = ~43 minutes/month downtime

Current usage: Check Grafana dashboard "SLO Tracking"
```

---

## Runbook Integration

### Alert Response

When an alert fires:

1. **Acknowledge** in alerting system
2. **Assess** severity using RUNBOOK.md
3. **Investigate** using dashboards and logs
4. **Mitigate** following runbook procedures
5. **Document** in incident tracker

### Escalation Matrix

| Severity | Response Time | Escalation |
|----------|---------------|------------|
| Critical | 5 minutes | On-call -> Engineering Lead -> CTO |
| High | 30 minutes | On-call -> Engineering Lead |
| Medium | 4 hours | On-call |
| Low | Next business day | Ticket |

---

## Quick Start

### Local Development

```bash
# Start metrics server
export METRICS_ENABLED=true
export METRICS_PORT=9090
aragora serve --api-port 8080 --ws-port 8765

# View metrics
curl http://localhost:9090/metrics
```

### Docker Compose

```yaml
# docker-compose.monitoring.yml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./deploy/prometheus:/etc/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - ./deploy/grafana:/etc/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP gRPC
```

### Verify Setup

```bash
# Check metrics endpoint
curl -s http://localhost:9090/metrics | grep aragora

# Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets'

# Check Grafana health
curl -s http://localhost:3000/api/health
```

---

## Recent Changes to Monitor (January 2026)

### Scheduler Task Handling (PR #13)

The task scheduler now uses proper Redis Streams acknowledgment:

**What Changed:**
- Tasks are acknowledged with XACK + XDEL (previously was a no-op)
- Failed tasks move to dead-letter queue after retry exhaustion
- Capability-based rejections now properly requeue tasks

**Metrics to Watch:**
```bash
# Check dead-letter queue size
redis-cli XLEN aragora:tasks:dead_letter

# Check pending tasks per priority
redis-cli XLEN aragora:tasks:high
redis-cli XLEN aragora:tasks:normal
redis-cli XLEN aragora:tasks:low

# Check pending entries list (tasks claimed but not acked)
redis-cli XPENDING aragora:tasks:high aragora-workers
```

**Alerts to Configure:**
- Dead-letter queue size > 10 (indicates recurring task failures)
- Pending entries age > 5 minutes (indicates stuck workers)
- Task rejection rate > 20% (indicates capability mismatch)

### OAuth Authentication

OAuth was added to production with Google and GitHub providers:

**Health Checks:**
```bash
# Check OAuth providers endpoint
curl -s https://api.aragora.ai/api/auth/oauth/providers

# Should return: {"providers": [{"id": "google", ...}, {"id": "github", ...}]}
```

**Metrics to Watch:**
- OAuth callback success/failure rates
- State token expiration errors (indicates clock skew or slow users)
- Redirect URL validation failures (indicates misconfiguration attempts)

**Logs to Monitor:**
```bash
# OAuth errors in CloudWatch/logs
journalctl -u aragora | grep -i "oauth\|auth"
```

### AWS Secrets Manager

Production now loads secrets from AWS Secrets Manager:

**Verify Configuration:**
```bash
# Check if secrets are loading (should show provider count > 0)
curl -s https://api.aragora.ai/api/auth/oauth/providers | jq '.providers | length'
```

**IAM Permissions Required:**
- `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:us-east-2:*:secret:aragora/production*`

---

## Related Documentation

- [RUNBOOK.md](../operations/runbook) - Operational procedures
- [INCIDENT_RESPONSE.md](../operations/incident-response) - Incident handling
- [DR_DRILL_PROCEDURES.md](../deployment/dr-drills) - Disaster recovery
