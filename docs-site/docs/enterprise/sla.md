---
title: Aragora Service Level Agreement (SLA)
description: Aragora Service Level Agreement (SLA)
---

# Aragora Service Level Agreement (SLA)

This Service Level Agreement ("SLA") describes the service availability commitments and support terms for Aragora platform services.

## 1. Definitions

- **"Monthly Uptime Percentage"**: Total minutes in a month minus minutes of Downtime, divided by total minutes in a month.
- **"Downtime"**: Period where the Aragora API returns 5xx errors for more than 5 consecutive minutes, excluding scheduled maintenance.
- **"Scheduled Maintenance"**: Planned maintenance announced at least 72 hours in advance.
- **"Credits"**: Service credits applied to future invoices as compensation for SLA breaches.

## 2. Service Tiers

| Feature | Standard | Professional | Enterprise |
|---------|----------|--------------|------------|
| **Uptime SLA** | 99.5% | 99.9% | 99.95% |
| **Support Hours** | Business hours | Extended (16x5) | 24x7x365 |
| **Response Time (P1)** | 4 hours | 1 hour | 15 minutes |
| **Response Time (P2)** | 8 hours | 4 hours | 1 hour |
| **Response Time (P3)** | 2 business days | 1 business day | 4 hours |
| **Dedicated Support** | No | Shared | Named CSM |
| **Custom Integrations** | No | Limited | Full |
| **SLA Credits** | No | Yes | Yes |
| **Error Budget Dashboard** | No | Yes | Yes |

## 3. Uptime Commitment

### 3.1 Monthly Uptime Targets

| Tier | Monthly Uptime | Permitted Downtime |
|------|----------------|-------------------|
| Standard | 99.5% | 3 hours 36 minutes |
| Professional | 99.9% | 43 minutes |
| Enterprise | 99.95% | 21 minutes |

### 3.2 Service Credit Schedule

If Aragora fails to meet the Monthly Uptime Percentage, eligible customers receive service credits:

| Monthly Uptime | Credit (% of Monthly Fee) |
|----------------|--------------------------|
| 99.0% - 99.9% | 10% |
| 95.0% - 99.0% | 25% |
| 90.0% - 95.0% | 50% |
| Below 90.0% | 100% |

**Maximum Credit:** Total service credits cannot exceed 100% of monthly fees.

## 4. Performance Targets

### 4.1 API Latency

| Endpoint Category | P50 | P95 | P99 |
|-------------------|-----|-----|-----|
| Debate Creation | 50ms | 200ms | 500ms |
| Debate Retrieval | 10ms | 50ms | 100ms |
| Document Processing | 100ms | 300ms | 1000ms |
| WebSocket Messages | 5ms | 20ms | 50ms |

### 4.2 Debate Completion

| Debate Type | P50 | P95 |
|-------------|-----|-----|
| Standard (3 agents) | 8s | 20s |
| Extended (5+ agents) | 15s | 45s |
| Complex (10+ rounds) | 30s | 90s |

**Note:** Debate completion times depend on LLM provider response times and are best-effort targets.

### 4.3 Webhook Delivery

| Metric | Target |
|--------|--------|
| Delivery Latency (P99) | < 5 seconds |
| Delivery Success Rate | 99.9% |
| Retry Attempts | 3 (with exponential backoff) |

### 4.4 Error Rates

| Service | Target | Maximum |
|---------|--------|---------|
| API Error Rate | < 0.5% | < 1.0% |
| WebSocket Error Rate | < 1.0% | < 2.0% |
| Background Job Failure | < 0.1% | < 0.5% |

## 5. Support Response Times

### 5.1 Priority Definitions

| Priority | Description | Examples |
|----------|-------------|----------|
| **P1 - Critical** | Complete service outage, data loss risk | API unavailable, database corruption |
| **P2 - High** | Major feature unavailable, severe degradation | Debates failing, auth broken |
| **P3 - Medium** | Feature impaired, workaround available | Slow performance, UI issues |
| **P4 - Low** | Minor issue, cosmetic, feature request | Documentation, enhancement |

### 5.2 Response and Resolution Targets

| Priority | First Response | Status Update | Target Resolution |
|----------|---------------|---------------|-------------------|
| P1 | Per tier SLA | Every 30 min | 4 hours |
| P2 | Per tier SLA | Every 2 hours | 8 hours |
| P3 | Per tier SLA | Daily | 5 business days |
| P4 | 2 business days | Weekly | Best effort |

## 6. Maintenance Windows

### 6.1 Scheduled Maintenance

- **Notification**: At least 72 hours advance notice
- **Preferred Window**: Sundays 02:00-06:00 UTC
- **Frequency**: No more than once per month for major maintenance
- **Duration**: Maximum 4 hours per maintenance window

### 6.2 Emergency Maintenance

- **Notification**: As soon as reasonably possible
- **Scope**: Security patches, critical fixes only
- **Post-Incident**: Root cause analysis within 48 hours

## 7. Exclusions

The SLA does not apply to:

1. **Force Majeure**: Events beyond reasonable control
2. **Customer Actions**: Misconfiguration, abuse, or unauthorized access
3. **Third-Party Services**: LLM provider outages, cloud infrastructure failures
4. **Beta Features**: Features explicitly marked as beta or preview
5. **Free Tier**: SLA applies only to paid subscriptions
6. **API Abuse**: Requests exceeding rate limits or terms of service

## 8. Claiming Credits

### 8.1 Process

1. Submit claim within 30 days of incident
2. Include: Account ID, incident date/time, description
3. Submit to: support@aragora.ai or via support portal

### 8.2 Verification

- Aragora will verify claims against monitoring data
- Response within 10 business days
- Credits applied to next invoice cycle

## 9. Monitoring and Reporting

### 9.1 Status Page

Real-time service status available at: status.aragora.ai

### 9.2 Monthly Reports (Enterprise)

- Uptime metrics and trend analysis
- Incident summaries
- Performance against SLO targets
- Error budget consumption

### 9.3 Prometheus SLO Recording Rules

Enterprise customers receive access to SLO metrics:

```yaml
# API Availability
- record: slo:api:availability:ratio
  expr: sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))

# API Latency P99
- record: slo:api:latency:p99
  expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# Webhook Delivery Latency P99
- record: slo:webhook:delivery:latency:p99
  expr: histogram_quantile(0.99, sum(rate(webhook_delivery_seconds_bucket[5m])) by (le))

# Debate Completion P95
- record: slo:debate:completion:p95
  expr: histogram_quantile(0.95, sum(rate(debate_completion_seconds_bucket[5m])) by (le))
```

## 10. Contact Information

| Channel | Contact | Availability |
|---------|---------|--------------|
| Support Portal | support.aragora.ai | 24/7 |
| Email | support@aragora.ai | Per tier |
| Phone (Enterprise) | Dedicated line | 24/7 |
| Slack (Enterprise) | Dedicated channel | 24/7 |

## 11. SLA Revision

This SLA may be updated with 30 days notice. Current version is always available at docs.aragora.ai/sla.

---

**Effective Date:** January 28, 2026\
**Document version:** 1.0.0\
**Last Updated:** January 28, 2026
