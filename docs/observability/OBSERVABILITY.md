# Observability Guide

This guide covers distributed tracing, metrics, and monitoring for Aragora deployments.

## Table of Contents

- [Overview](#overview)
- [OpenTelemetry Tracing](#opentelemetry-tracing)
- [Prometheus Metrics](#prometheus-metrics)
- [N+1 Query Detection](#n1-query-detection)
- [Grafana Dashboards](#grafana-dashboards)
- [Local Development](#local-development)
- [Production Setup](#production-setup)
- [Cross-Pollination Metrics](#cross-pollination-metrics)
- [Platform Integration Metrics](#platform-integration-metrics)
- [Troubleshooting](#troubleshooting)

---

## Overview

Aragora provides comprehensive observability through:

1. **Distributed Tracing** - OpenTelemetry spans for request flows
2. **Prometheus Metrics** - Request rates, latencies, and business metrics
3. **Grafana Dashboards** - Pre-built visualizations

### Architecture

```
                                    ┌─────────────────┐
                                    │   Grafana       │
                                    │   Dashboard     │
                                    └────────┬────────┘
                                             │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
            ┌───────▼───────┐       ┌───────▼───────┐       ┌──────▼──────┐
            │  Prometheus   │       │    Jaeger     │       │   Alerting  │
            │   (Metrics)   │       │   (Traces)    │       │             │
            └───────▲───────┘       └───────▲───────┘       └─────────────┘
                    │                       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Aragora Server      │
                    │  ┌─────────────────┐  │
                    │  │ Observability   │  │
                    │  │    Module       │  │
                    │  └─────────────────┘  │
                    └───────────────────────┘
```

---

## OpenTelemetry Tracing

### Configuration

Aragora supports both standard OpenTelemetry environment variables and Aragora-specific ones.
Standard OTEL_* variables take precedence when both are set.

#### Standard OpenTelemetry Variables (Recommended)

```bash
# OTLP collector endpoint - setting this auto-enables tracing
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Service name in traces
export OTEL_SERVICE_NAME=aragora

# Sampler type (controls which traces are recorded)
# Options: always_on, always_off, traceidratio,
#          parentbased_always_on, parentbased_always_off, parentbased_traceidratio
export OTEL_TRACES_SAMPLER=parentbased_traceidratio

# Sampler argument (e.g., ratio for traceidratio samplers)
# 0.1 = 10% of traces, 1.0 = 100% of traces
export OTEL_TRACES_SAMPLER_ARG=1.0

# Context propagation format (default: tracecontext,baggage)
export OTEL_PROPAGATORS=tracecontext,baggage

# Additional resource attributes (optional)
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.version=2.6.3
```

#### Legacy/Compatibility Variables

```bash
# Enable tracing (auto-enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set)
export OTEL_ENABLED=true

# Sample rate (use OTEL_TRACES_SAMPLER_ARG instead)
export OTEL_SAMPLE_RATE=1.0
```

#### Aragora-Specific Variables (Fallback)

These are used when standard OTEL_* variables are not set:

```bash
# Exporter type: none, jaeger, zipkin, otlp_grpc, otlp_http, datadog
export ARAGORA_OTLP_EXPORTER=otlp_grpc

# Collector endpoint
export ARAGORA_OTLP_ENDPOINT=http://localhost:4317

# Service identification
export ARAGORA_SERVICE_NAME=aragora
export ARAGORA_SERVICE_VERSION=1.0.0
export ARAGORA_ENVIRONMENT=production

# Sampling (use OTEL_TRACES_SAMPLER_ARG instead)
export ARAGORA_TRACE_SAMPLE_RATE=1.0

# Advanced settings
export ARAGORA_OTLP_BATCH_SIZE=512
export ARAGORA_OTLP_EXPORT_TIMEOUT_MS=30000
export ARAGORA_OTLP_INSECURE=false

# Headers for authenticated endpoints (JSON format)
export ARAGORA_OTLP_HEADERS='{"Authorization": "Bearer token"}'

# Datadog-specific
export DATADOG_API_KEY=your-api-key
```

### Sampling Strategies

Choose a sampling strategy based on your needs:

| Strategy | Env Variable Value | Use Case |
|----------|-------------------|----------|
| Always On | `always_on` | Development, debugging |
| Always Off | `always_off` | Disabled tracing |
| Trace ID Ratio | `traceidratio` | Fixed percentage sampling |
| Parent-Based Always On | `parentbased_always_on` | Follow parent decision, sample if root |
| Parent-Based Always Off | `parentbased_always_off` | Follow parent decision, don't sample if root |
| Parent-Based Trace ID Ratio | `parentbased_traceidratio` | **Recommended for production** |

**Production Recommendation:**
```bash
# Sample 10% of traces, but follow parent's decision for child spans
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1
```

### Usage

#### Trace HTTP Handlers

```python
from aragora.observability import trace_handler

class DebatesHandler(BaseHandler):
    @trace_handler("debates.create")
    def _create_debate(self, handler):
        # Automatically creates span with HTTP attributes
        ...
```

#### Trace Agent Calls

```python
from aragora.observability import trace_agent_call

class ClaudeAgent:
    @trace_agent_call("anthropic")
    async def respond(self, prompt: str) -> str:
        # Automatically creates span with agent attributes
        ...
```

#### Manual Spans

```python
from aragora.observability import get_tracer, create_span

tracer = get_tracer()

# Using context manager
with create_span("custom_operation", {"key": "value"}) as span:
    result = do_work()
    span.set_attribute("result_size", len(result))

# Using tracer directly
with tracer.start_as_current_span("another_operation") as span:
    span.set_attribute("custom.attribute", "value")
    ...
```

### Span Attributes

Automatically captured attributes:

| Attribute | Description |
|-----------|-------------|
| `http.path` | Request path |
| `http.method` | HTTP method |
| `http.status_code` | Response status |
| `agent.name` | Agent identifier |
| `agent.prompt_length` | Input prompt size |
| `agent.response_length` | Output response size |

---

## Prometheus Metrics

### Available Metrics

#### Request Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_requests_total` | Counter | method, endpoint, status | Total HTTP requests |
| `aragora_request_latency_seconds` | Histogram | endpoint | Request latency |

#### Agent Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_agent_calls_total` | Counter | agent, status | Total agent API calls |
| `aragora_agent_latency_seconds` | Histogram | agent | Agent response latency |
| `aragora_fallback_activations_total` | Counter | primary_agent, fallback_provider, error_type | Fallback activations |
| `aragora_fallback_success_total` | Counter | fallback_provider, status | Fallback outcomes |
| `aragora_fallback_latency_seconds` | Histogram | fallback_provider | Fallback latency |

#### Debate Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_active_debates` | Gauge | - | Currently active debates |
| `aragora_consensus_rate` | Gauge | - | Rate of consensus reached |

#### System Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_websocket_connections` | Gauge | - | Active WebSocket connections |
| `aragora_memory_operations_total` | Counter | operation, tier | Memory operations |

For alert thresholds and response playbooks, see `RUNBOOK_METRICS.md`.

### Configuration

```bash
# Enable metrics (default: true)
export METRICS_ENABLED=true

# Metrics endpoint port (default: 9090)
export METRICS_PORT=9090
```

### Usage

```python
from aragora.observability import (
    record_request,
    record_agent_call,
    track_debate,
)

# Record an HTTP request
record_request("GET", "/api/debates", 200, 0.05)

# Record an agent call
record_agent_call("anthropic-api", success=True, latency=1.2)

# Track active debates
with track_debate():
    await arena.run()
```

### Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'aragora'
    static_configs:
      - targets: ['aragora:9090']
    scrape_interval: 15s
```

## N+1 Query Detection

Aragora can detect N+1 query patterns at runtime and emit warnings or errors.

**Configuration:**
- `ARAGORA_N1_DETECTION=off|warn|error` (default: `off`)
- `ARAGORA_N1_THRESHOLD=5` (queries per table before alert)

**Example:**

```python
from aragora.observability.n1_detector import detect_n1

@detect_n1(threshold=3)
async def handle_request(request):
    # Database access that might trigger N+1 patterns
    ...
```

When enabled, the detector logs the table/query patterns and raises an error
in `error` mode.

---

## Grafana Dashboards

### Import Dashboard

1. Open Grafana
2. Go to Dashboards → Import
3. Upload `deploy/grafana/aragora-dashboard.json`
4. Select your Prometheus datasource
5. Click Import

### Dashboard Panels

| Panel | Description |
|-------|-------------|
| Request Rate | Requests per second |
| P95 Latency | 95th percentile response time |
| Active Debates | Currently running debates |
| Consensus Rate | Rate of successful consensus |
| Request Rate by Endpoint | Per-endpoint request rates |
| Request Latency by Endpoint | Per-endpoint latencies |
| Agent Calls by Status | Success/error rates by agent |
| Agent Response Latency | Per-agent latencies |
| Error Rates | 4xx and 5xx error percentages |
| WebSocket Connections | Active WebSocket clients |

---

## Local Development

### Quick Start with Docker Compose

Create `docker-compose.observability.yml`:

```yaml
version: '3.8'

services:
  jaeger:
    image: jaegertracing/all-in-one:1.50
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP gRPC
      - "4318:4318"    # OTLP HTTP

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9091:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./deploy/grafana:/var/lib/grafana/dashboards
```

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'aragora'
    static_configs:
      - targets: ['host.docker.internal:9090']
```

Start:

```bash
docker-compose -f docker-compose.observability.yml up -d
```

### Start Aragora with Observability

```bash
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export METRICS_ENABLED=true

aragora serve --api-port 8080 --ws-port 8765
```

### View Traces

Open Jaeger UI: http://localhost:16686

### View Metrics

Open Grafana: http://localhost:3000 (admin/admin)

---

## Production Setup

### Kubernetes with Jaeger Operator

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: aragora-jaeger
spec:
  strategy: production
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch:9200
```

### Prometheus Operator

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: aragora
  labels:
    app: aragora
spec:
  selector:
    matchLabels:
      app: aragora
  endpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

### Environment Variables

```yaml
# Kubernetes deployment - using standard OTEL variables
env:
  # OpenTelemetry tracing (standard variables)
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://jaeger-collector.observability:4317"
  - name: OTEL_SERVICE_NAME
    value: "aragora"
  - name: OTEL_TRACES_SAMPLER
    value: "parentbased_traceidratio"
  - name: OTEL_TRACES_SAMPLER_ARG
    value: "0.1"  # 10% sampling in production
  - name: OTEL_PROPAGATORS
    value: "tracecontext,baggage"
  # Prometheus metrics
  - name: METRICS_ENABLED
    value: "true"
  - name: METRICS_PORT
    value: "9090"
  # Service metadata
  - name: ARAGORA_SERVICE_VERSION
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['app.kubernetes.io/version']
  - name: ARAGORA_ENVIRONMENT
    value: "production"
```

---

## Cross-Pollination Metrics

These metrics track feature integrations that connect Aragora's subsystems.

### ELO Skill Weighting

```promql
# ELO-adjusted vote weights applied
rate(aragora_selection_feedback_adjustments_total[5m])

# ELO rating distribution
histogram_quantile(0.95, aragora_elo_rating_distribution)
```

**Key metrics:**
- `aragora_selection_feedback_adjustments_total` - Count of ELO-based weight adjustments
- `aragora_learning_bonuses_total` - Learning efficiency bonuses applied

### Calibration Tracking

```promql
# Calibration adjustments per agent
sum by (agent) (rate(aragora_calibration_adjustments_total[5m]))

# Voting accuracy updates
rate(aragora_voting_accuracy_updates_total{result="correct"}[5m])
```

**Key metrics:**
- `aragora_calibration_adjustments_total` - Calibration temperature scaling applications
- `aragora_voting_accuracy_updates_total` - Voting accuracy tracking (correct/incorrect)

### Evidence Quality

```promql
# Evidence citation bonuses applied
rate(aragora_evidence_citation_bonuses_total[5m])

# Process evaluation bonuses
rate(aragora_process_evaluation_bonuses_total[5m])
```

**Key metrics:**
- `aragora_evidence_citation_bonuses_total` - Evidence quality weighted bonuses
- `aragora_process_evaluation_bonuses_total` - Process-based evaluation bonuses

### RLM Hierarchy Caching

```promql
# Cache hit rate
rate(aragora_rlm_cache_hits_total[5m]) /
(rate(aragora_rlm_cache_hits_total[5m]) + rate(aragora_rlm_cache_misses_total[5m]))

# Cache efficiency
aragora_rlm_cache_hits_total / (aragora_rlm_cache_hits_total + aragora_rlm_cache_misses_total)
```

**Key metrics:**
- `aragora_rlm_cache_hits_total` - Compression hierarchy cache hits
- `aragora_rlm_cache_misses_total` - Compression hierarchy cache misses

### Verification → Confidence

```promql
# Verification bonuses applied to consensus
sum(rate(aragora_verification_bonuses_total[5m]))
```

**Key metrics:**
- `aragora_convergence_checks_total` - Convergence detection checks
- Verification results adjust vote confidence (verified +30%, disproven -70%)

### Knowledge Mound Integration

```promql
# KM operations by type
sum by (operation) (rate(aragora_km_operations_total[5m]))

# Consensus ingestion rate
rate(aragora_consensus_evidence_linked_total[5m])
```

**Key metrics:**
- `aragora_km_operations_total` - Knowledge Mound CRUD operations
- `aragora_km_cache_hits_total` - KM query cache hits
- `aragora_consensus_evidence_linked_total` - Evidence linked to consensus

### Platform Integration Metrics

Metrics for chat platform integrations (Slack, Discord, Teams, Telegram, WhatsApp, Matrix).

```promql
# Request success rate by platform
sum by (platform) (rate(aragora_platform_requests_total{status="success"}[5m])) /
sum by (platform) (rate(aragora_platform_requests_total[5m]))

# Platform latency P95
histogram_quantile(0.95, rate(aragora_platform_request_latency_seconds_bucket[5m]))

# Dead letter queue pending messages
aragora_dlq_pending
```

**Platform Request Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_platform_requests_total` | Counter | platform, operation, status | Total platform API requests |
| `aragora_platform_request_latency_seconds` | Histogram | platform, operation | Request latency by platform |
| `aragora_platform_errors_total` | Counter | platform, error_type | Platform errors by type |

**Circuit Breaker Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_platform_circuit_state` | Gauge | platform, state | Circuit breaker state (0=closed, 1=open, 2=half-open) |

**Dead Letter Queue Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_dlq_enqueued_total` | Counter | platform | Messages enqueued to DLQ |
| `aragora_dlq_processed_total` | Counter | platform | Messages successfully reprocessed |
| `aragora_dlq_failed_total` | Counter | platform | Messages that exceeded retry limit |
| `aragora_dlq_pending` | Gauge | platform | Current pending messages in DLQ |
| `aragora_dlq_retry_latency_seconds` | Histogram | platform | Time between retries |

**Rate Limiting Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_platform_rate_limit_total` | Counter | platform, result | Rate limit checks (allowed/blocked) |

**Webhook Delivery Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_webhook_delivery_total` | Counter | platform, status | Webhook delivery attempts |
| `aragora_webhook_retry_total` | Counter | platform | Webhook retries |

**Bot Command Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `aragora_bot_command_total` | Counter | platform, command, status | Bot command processing |
| `aragora_bot_command_latency_seconds` | Histogram | platform, command | Command processing time |
| `aragora_bot_command_timeout_total` | Counter | platform, command | Command timeouts |

#### Platform Health Endpoint

Check platform health via the `/api/platform/health` endpoint:

```bash
curl http://localhost:8080/api/platform/health | jq
```

Response includes:
- Rate limiter status per platform
- Circuit breaker states
- DLQ statistics
- Prometheus metrics availability

#### Platform-Specific Rate Limits

| Platform | RPM | Burst | Daily Limit |
|----------|-----|-------|-------------|
| Slack | 10 | 5 | - |
| Discord | 30 | 10 | - |
| Teams | 10 | 5 | - |
| Telegram | 20 | 5 | - |
| WhatsApp | 5 | 2 | 100 |
| Matrix | 10 | 5 | - |
| Email | 10 | 3 | 500 |

### Recommended Alerting Rules

```yaml
groups:
  - name: cross-pollination
    rules:
      - alert: LowCacheHitRate
        expr: |
          rate(aragora_rlm_cache_hits_total[5m]) /
          (rate(aragora_rlm_cache_hits_total[5m]) + rate(aragora_rlm_cache_misses_total[5m])) < 0.3
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: RLM cache hit rate below 30%

      - alert: HighCalibrationError
        expr: avg(aragora_calibration_ece) > 0.15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: Agent calibration error (ECE) above 15%

  - name: platform-integration
    rules:
      - alert: PlatformCircuitOpen
        expr: aragora_platform_circuit_state == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Platform {{ $labels.platform }} circuit breaker is OPEN"
          description: "Platform API is unavailable, messages will be queued to DLQ"

      - alert: HighDLQPending
        expr: aragora_dlq_pending > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DLQ has {{ $value }} pending messages for {{ $labels.platform }}"

      - alert: PlatformHighErrorRate
        expr: |
          sum by (platform) (rate(aragora_platform_requests_total{status="error"}[5m])) /
          sum by (platform) (rate(aragora_platform_requests_total[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Platform {{ $labels.platform }} error rate above 10%"

      - alert: PlatformHighLatency
        expr: |
          histogram_quantile(0.95, rate(aragora_platform_request_latency_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Platform P95 latency above 5 seconds"
```

---

## Troubleshooting

### Traces Not Appearing

1. Check OTEL_ENABLED is "true"
2. Verify OTLP endpoint is reachable
3. Check Jaeger logs for errors
4. Verify sample rate is > 0

```bash
# Test OTLP endpoint
curl -v http://localhost:4317
```

### Metrics Not Scraped

1. Check METRICS_ENABLED is "true"
2. Verify port 9090 is accessible
3. Check Prometheus targets in UI
4. Verify network policies allow scraping

```bash
# Test metrics endpoint
curl http://localhost:9090/metrics
```

### High Latency from Tracing

1. Reduce sample rate (OTEL_SAMPLE_RATE=0.1)
2. Use batch export (default)
3. Increase export timeout

### Memory Issues

1. Limit trace context propagation
2. Reduce histogram bucket count
3. Enable metric aggregation

---

## Production Observability Stack

For production deployments, use the complete observability stack in `deploy/monitoring/`:

### Configuration Files

| File | Purpose |
|------|---------|
| `prometheus.yml` | Prometheus scrape configs with alerting |
| `alertmanager.yml` | Alert routing and notifications |
| `docker-compose.observability.yml` | Full observability stack |
| `blackbox.yml` | Synthetic monitoring probes |
| `loki.yml` | Log aggregation configuration |
| `promtail.yml` | Log shipping to Loki |

### Quick Start

```bash
cd deploy/monitoring

# Set required environment variables
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export GRAFANA_ADMIN_PASSWORD="secure-password"

# Start the stack
docker-compose -f docker-compose.observability.yml up -d
```

### Components Included

- **Prometheus** (port 9090) - Metrics collection with 30-day retention
- **AlertManager** (port 9093) - Alert routing to Slack, PagerDuty, Email
- **Grafana** (port 3000) - 16 pre-built dashboards
- **Jaeger** (port 16686) - Distributed tracing with OTLP support
- **Loki** (port 3100) - Log aggregation with 30-day retention
- **Promtail** - Log shipping agent
- **Node Exporter** (port 9100) - Host metrics
- **cAdvisor** (port 8081) - Container metrics
- **Redis Exporter** (port 9121) - Redis metrics
- **Postgres Exporter** (port 9187) - PostgreSQL metrics
- **Blackbox Exporter** (port 9115) - Synthetic monitoring

### Alert Channels

Configure these environment variables for notifications:

```bash
SLACK_WEBHOOK_URL      # Slack incoming webhook
PAGERDUTY_SERVICE_KEY  # PagerDuty integration key
SMTP_HOST              # SMTP server (default: smtp.gmail.com:587)
SMTP_USER              # SMTP username
SMTP_PASSWORD          # SMTP password
```

### SLO Tracking

SLOs are defined in `aragora/monitoring/slos.yml`:

| SLO | Target | Window |
|-----|--------|--------|
| API Availability | 99.9% | 30 days |
| API Latency (p99 < 2s) | 99% | 30 days |
| Debate Completion | 99.5% | 30 days |
| Agent Reliability | 98% | 7 days |

### Alert Rules

Over 100 alert rules in `aragora/monitoring/alerts/prometheus_rules.yml` covering:
- Availability and latency
- Debate quality and consensus
- Security (RBAC, auth failures)
- SLO burn rates
- Resource capacity
- Knowledge Mound health

---

## See Also

- [DEPLOYMENT.md](../DEPLOYMENT.md) - Deployment guide (Docker Compose, Kubernetes, TLS, backups)
- [RATE_LIMITING.md](../api/RATE_LIMITING.md) - Rate limiting configuration
- [SECURITY.md](../enterprise/SECURITY.md) - Security configuration
- [ENTERPRISE_FEATURES.md](../ENTERPRISE_FEATURES.md) - Enterprise capabilities
- Alert Rules: `aragora/monitoring/alerts/prometheus_rules.yml`
- SLO Definitions: `aragora/monitoring/slos.yml`
- Dashboards: `deploy/grafana/dashboards/`
