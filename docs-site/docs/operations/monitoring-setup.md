---
title: Monitoring Setup Runbook
description: Monitoring Setup Runbook
---

# Monitoring Setup Runbook

Configure observability for Aragora deployments.

## Overview

| Component | Purpose | Tool |
|-----------|---------|------|
| Metrics | Performance data | Prometheus |
| Dashboards | Visualization | Grafana |
| Logs | Application logs | Loki/ELK |
| Tracing | Request tracing | Jaeger/Tempo |
| Alerts | Notifications | Alertmanager |

---

## Prometheus Setup

### Kubernetes

```bash
# Install Prometheus stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values prometheus-values.yaml
```

**prometheus-values.yaml:**

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelector:
      matchLabels:
        release: prometheus
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi

grafana:
  persistence:
    enabled: true
    size: 10Gi
  adminPassword: "changeme"
```

### ServiceMonitor for Aragora

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: aragora
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: aragora-api
  namespaceSelector:
    matchNames:
      - aragora
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

---

## Grafana Dashboards

### Import Aragora Dashboard

```bash
# Get Grafana admin password
kubectl get secret prometheus-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d

# Port forward
kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80

# Access at http://localhost:3000
```

### Key Dashboards

**1. API Overview**
- Request rate (RPS)
- Error rate (%)
- Latency percentiles (p50, p95, p99)
- Active connections

**2. Debate Performance**
- Debates started/completed
- Average debate duration
- Agent response times
- Consensus rate

**3. Infrastructure**
- CPU/Memory usage
- Pod restarts
- Network I/O
- Disk usage

### Dashboard JSON (API Overview)

```json
{
  "title": "Aragora API Overview",
  "panels": [
    {
      "title": "Request Rate",
      "type": "timeseries",
      "targets": [{
        "expr": "sum(rate(aragora_http_requests_total[5m]))",
        "legendFormat": "requests/sec"
      }]
    },
    {
      "title": "Error Rate",
      "type": "stat",
      "targets": [{
        "expr": "sum(rate(aragora_http_requests_total{status=~\"5..\"}[5m])) / sum(rate(aragora_http_requests_total[5m])) * 100",
        "legendFormat": "error %"
      }]
    },
    {
      "title": "Latency P95",
      "type": "timeseries",
      "targets": [{
        "expr": "histogram_quantile(0.95, sum(rate(aragora_http_request_duration_seconds_bucket[5m])) by (le))",
        "legendFormat": "p95"
      }]
    }
  ]
}
```

---

## Alert Rules

### PrometheusRule

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aragora-alerts
  namespace: monitoring
spec:
  groups:
  - name: aragora
    rules:
    # High error rate
    - alert: AragoraHighErrorRate
      expr: |
        sum(rate(aragora_http_requests_total{status=~"5.."}[5m])) /
        sum(rate(aragora_http_requests_total[5m])) > 0.05
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "High error rate detected"
        description: "Error rate is {{ $value | humanizePercentage }}"

    # High latency
    - alert: AragoraHighLatency
      expr: |
        histogram_quantile(0.95, sum(rate(aragora_http_request_duration_seconds_bucket[5m])) by (le)) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High latency detected"
        description: "P95 latency is {{ $value | humanizeDuration }}"

    # Pod restarts
    - alert: AragoraPodRestarts
      expr: |
        increase(kube_pod_container_status_restarts_total{namespace="aragora"}[1h]) > 3
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Pod restarting frequently"
        description: "Pod {{ $labels.pod }} has restarted {{ $value }} times"

    # Database connections
    - alert: AragoraDBConnections
      expr: |
        pg_stat_activity_count{datname="aragora"} > 80
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Database connections high"
        description: "{{ $value }} active connections"

    # Queue depth
    - alert: AragoraQueueBacklog
      expr: |
        aragora_queue_depth > 1000
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Queue backlog growing"
        description: "Queue depth is {{ $value }}"
```

---

## Alertmanager Configuration

```yaml
# alertmanager.yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
  - match:
      severity: critical
    receiver: 'pagerduty'
  - match:
      severity: warning
    receiver: 'slack'

receivers:
- name: 'default'
  slack_configs:
  - channel: '#alerts'
    api_url: 'https://hooks.slack.com/services/xxx'

- name: 'pagerduty'
  pagerduty_configs:
  - service_key: 'xxx'

- name: 'slack'
  slack_configs:
  - channel: '#alerts'
    api_url: 'https://hooks.slack.com/services/xxx'
    title: '{{ .Status | toUpper }}: {{ .CommonAnnotations.summary }}'
    text: '{{ .CommonAnnotations.description }}'
```

---

## Log Aggregation

### Loki Setup

```bash
helm install loki grafana/loki-stack \
  --namespace monitoring \
  --set promtail.enabled=true \
  --set loki.persistence.enabled=true \
  --set loki.persistence.size=50Gi
```

### Useful LogQL Queries

```
# All errors
{namespace="aragora"} |= "error"

# Specific pod logs
{namespace="aragora", pod=~"aragora-api-.*"}

# JSON parsing
{namespace="aragora"} | json | level="error"

# Rate of errors
sum(rate({namespace="aragora"} |= "error" [5m])) by (pod)
```

---

## Distributed Tracing

### Jaeger Setup

```bash
helm install jaeger jaegertracing/jaeger \
  --namespace monitoring \
  --set storage.type=elasticsearch \
  --set elasticsearch.host=elasticsearch.monitoring
```

### Application Configuration

```python
# Configure OpenTelemetry in Aragora
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

trace.set_tracer_provider(TracerProvider())
jaeger_exporter = JaegerExporter(
    agent_host_name="jaeger-agent.monitoring",
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)
```

---

## Health Endpoints

Aragora exposes these endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/health` | Liveness check |
| `/ready` | Readiness check |
| `/metrics` | Prometheus metrics |

### Kubernetes Probes

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

---

## Verification

```bash
# Check Prometheus targets
kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090
# Visit http://localhost:9090/targets

# Check Grafana
kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80
# Visit http://localhost:3000

# Check alerts
kubectl get prometheusrules -n monitoring
kubectl port-forward svc/prometheus-kube-prometheus-alertmanager -n monitoring 9093:9093
# Visit http://localhost:9093
```

---

## See Also

- [Incident Response Runbook](./incident-response-procedures)
- [Scaling Runbook](./scaling)
- [Deployment Decision Matrix](../deployment/decision-matrix)
