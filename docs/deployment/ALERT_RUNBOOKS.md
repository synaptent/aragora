# Alert Runbooks

This document provides operational procedures for responding to Aragora alerts. Each runbook includes:
- Alert description and severity
- Initial triage steps
- Resolution procedures
- Escalation paths

---

## Table of Contents

1. [API Availability Alerts](#api-availability-alerts)
2. [Latency Alerts](#latency-alerts)
3. [Debate Alerts](#debate-alerts)
4. [Agent Alerts](#agent-alerts)
5. [Security Alerts](#security-alerts)
6. [Infrastructure Alerts](#infrastructure-alerts)
7. [SLO Error Budget Alerts](#slo-error-budget-alerts)
8. [Execution Safety Gate Alerts](#execution-safety-gate-alerts)

---

## API Availability Alerts

### ServiceDown

**Severity:** Critical
**SLO Impact:** API Availability (99.9%)

**Alert Condition:**
```promql
up{job="aragora"} == 0
```

**Initial Triage:**
1. Check Kubernetes pod status: `kubectl get pods -l app=aragora`
2. View pod logs: `kubectl logs -l app=aragora --tail=100`
3. Check recent deployments: `kubectl rollout history deployment/aragora`

**Resolution Steps:**
1. If pod is CrashLoopBackOff:
   - Check logs for startup errors
   - Verify environment variables are set
   - Check secrets/configmaps are mounted
2. If pod is Pending:
   - Check node resources: `kubectl describe node`
   - Verify PVC bindings
3. If OOMKilled:
   - Increase memory limits
   - Review for memory leaks

**Escalation:**
- After 5 min: Page on-call engineer
- After 15 min: Escalate to team lead
- After 30 min: Incident commander takes over

---

### HighErrorRate

**Severity:** Critical
**SLO Impact:** API Availability (99.9%)

**Alert Condition:**
```promql
sum(rate(aragora_api_requests_total{status="error"}[5m])) /
sum(rate(aragora_api_requests_total[5m])) > 0.01
```

**Initial Triage:**
1. Check error breakdown by endpoint:
   ```promql
   sum by (endpoint) (rate(aragora_api_requests_total{status="error"}[5m]))
   ```
2. Check recent error logs: `kubectl logs -l app=aragora | grep ERROR`
3. Review recent deployments or config changes

**Resolution Steps:**
1. If specific endpoint failing:
   - Check dependent services (database, Redis, AI providers)
   - Review endpoint-specific logs
2. If all endpoints affected:
   - Check database connectivity
   - Verify Redis is healthy
   - Check AI provider API status
3. If caused by bad deployment:
   - Rollback: `kubectl rollout undo deployment/aragora`

**Escalation:**
- Page on-call immediately for >5% error rate
- Engage database team if DB-related
- Engage AI team if provider issues

---

## Latency Alerts

### HighAPILatency

**Severity:** Warning
**SLO Impact:** API Latency p99 (<2s)

**Alert Condition:**
```promql
histogram_quantile(0.99, rate(aragora_api_latency_seconds_bucket[5m])) > 2
```

**Initial Triage:**
1. Identify slow endpoints:
   ```promql
   histogram_quantile(0.99, sum by (endpoint) (rate(aragora_api_latency_seconds_bucket[5m]))) > 2
   ```
2. Check database query times
3. Check external API latencies (AI providers)

**Resolution Steps:**
1. If database slow:
   - Check for missing indexes
   - Review recent schema changes
   - Check for table locks
2. If AI provider slow:
   - Check provider status page
   - Consider fallback to OpenRouter
3. If memory pressure:
   - Scale horizontally
   - Review memory usage patterns

**Escalation:**
- Warning: Monitor for 15 min before escalating
- If sustained >30 min: Page backend engineer

---

## Agent Alerts

### HighAgentLatency

**Severity:** Warning
**SLO Impact:** Agent Reliability (98%)

**Alert Condition:**
```promql
histogram_quantile(0.99, rate(aragora_agent_latency_seconds_bucket[5m])) > 30
```

**Initial Triage:**
1. Check which agents are slow:
   ```promql
   histogram_quantile(0.99, sum by (agent) (rate(aragora_agent_latency_seconds_bucket[5m])))
   ```
2. Check AI provider status pages
3. Review circuit breaker status

**Resolution Steps:**
1. If specific provider slow:
   - Check provider status
   - Temporarily reduce traffic to that provider
   - Enable fallback routing
2. If all providers slow:
   - Check network connectivity
   - Review request complexity (token count)
3. Enable circuit breaker if needed:
   ```python
   from aragora.resilience import get_circuit_breaker
   cb = get_circuit_breaker("anthropic")
   cb.trip()  # Force open circuit
   ```

**Escalation:**
- Contact AI provider support if issue persists >1 hour

---

## Debate Alerts

### HighDebateFailureRate

**Severity:** Critical
**SLO Impact:** Debate Completion (99.5%)

**Alert Condition:**
```promql
sum(rate(aragora_debates_completed_total{status=~"error|timeout"}[5m])) /
sum(rate(aragora_debates_completed_total[5m])) > 0.005
```

**Initial Triage:**
1. Check failure reasons:
   ```promql
   sum by (status, reason) (rate(aragora_debates_completed_total{status!="completed"}[5m]))
   ```
2. Check for specific agent failures
3. Review debate logs for patterns

**Resolution Steps:**
1. If timeout failures:
   - Increase debate timeout
   - Check for slow agents
   - Review debate complexity
2. If agent failures:
   - Check circuit breakers
   - Enable fallback agents
   - Review agent error logs
3. If consensus failures:
   - Review convergence settings
   - Check for conflicting agent configurations

**Escalation:**
- >1% failure rate: Page immediately
- Engage ML team for consensus issues

---

### DebateTakingTooLong

**Severity:** Warning
**SLO Impact:** Debate Duration (95% < 5min)

**Alert Condition:**
```promql
histogram_quantile(0.95, rate(aragora_debate_duration_seconds_bucket[5m])) > 300
```

**Initial Triage:**
1. Check which debate types are slow
2. Review agent response times
3. Check round count distribution

**Resolution Steps:**
1. If too many rounds:
   - Review convergence threshold
   - Check for hollow consensus
2. If agents slow:
   - See HighAgentLatency runbook
3. If memory operations slow:
   - Check ContinuumMemory performance
   - Review Knowledge Mound latency

---

## Security Alerts

### HighAuthFailureRate

**Severity:** High
**SLO Impact:** Authentication (99.9%)

**Alert Condition:**
```promql
sum(rate(aragora_auth_failures_total[5m])) /
sum(rate(aragora_api_requests_total{endpoint=~"/api/auth/.*"}[5m])) > 0.1
```

**Initial Triage:**
1. Check failure reasons:
   ```promql
   sum by (reason) (rate(aragora_auth_failures_total[5m]))
   ```
2. Check for brute force patterns (same IP)
3. Review JWT service health

**Resolution Steps:**
1. If brute force detected:
   - Enable IP rate limiting
   - Consider temporary IP block
   - Review anomaly detection alerts
2. If JWT issues:
   - Check secret rotation status
   - Verify JWT signing key
3. If provider issues (SSO):
   - Check IdP status
   - Verify OIDC configuration

**Escalation:**
- Potential security incident: Page security team immediately
- Enable enhanced logging for forensics

---

### BruteForceAttemptDetected

**Severity:** High

**Alert Condition:**
```promql
sum by (ip_address) (rate(aragora_auth_failures_total[5m])) > 10
```

**Initial Triage:**
1. Identify source IP addresses
2. Check if any accounts were compromised
3. Review affected user accounts

**Resolution Steps:**
1. Block offending IP:
   ```bash
   kubectl exec -it aragora-pod -- python -c "
   from aragora.security.anomaly_detection import get_anomaly_detector
   # IP will be tracked automatically
   "
   ```
2. Notify affected users
3. Force password reset if needed
4. Review audit logs

**Escalation:**
- Invoke incident response if account compromise confirmed
- Engage security team

---

## Infrastructure Alerts

### CircuitBreakerOpen

**Severity:** Warning

**Alert Condition:**
```promql
aragora_circuit_breakers_open > 0
```

**Initial Triage:**
1. Check which circuit breakers are open:
   ```promql
   aragora_circuit_breaker_state{state="open"}
   ```
2. Review failure rate for affected service
3. Check service health

**Resolution Steps:**
1. Check underlying service health
2. Review error patterns in logs
3. Wait for automatic recovery or manual reset:
   ```python
   from aragora.resilience import get_circuit_breaker
   cb = get_circuit_breaker("service_name")
   cb.reset()
   ```

**Escalation:**
- If multiple circuits open: Page infrastructure team

---

### HighMemoryUsage

**Severity:** Warning

**Alert Condition:**
```promql
process_resident_memory_bytes / process_virtual_memory_bytes > 0.9
```

**Initial Triage:**
1. Check memory trend over time
2. Identify memory-heavy operations
3. Review recent traffic patterns

**Resolution Steps:**
1. If gradual increase (leak):
   - Identify leak with memory profiler
   - Schedule pod restart
2. If spike (traffic):
   - Scale horizontally
   - Enable request queuing
3. If cache issue:
   - Review cache eviction policy
   - Clear caches if needed

---

## SLO Error Budget Alerts

### FastBurnRate

**Severity:** Critical

**Alert Condition:**
```yaml
burn_rate: 14.4  # Budget exhausted in ~2 days
duration: 1h
```

**Initial Triage:**
1. Identify which SLO is burning
2. Check for recent changes (deploy, config)
3. Review error patterns

**Resolution Steps:**
1. Identify root cause using SLO-specific runbook
2. Consider rollback if deploy-related
3. Implement immediate mitigation

**Escalation:**
- Immediate page to on-call
- 30-minute status update cadence

---

### SlowBurnRate

**Severity:** Warning

**Alert Condition:**
```yaml
burn_rate: 6.0  # Budget exhausted in ~5 days
duration: 6h
```

**Initial Triage:**
1. Review error budget dashboard
2. Identify contributing factors
3. Project budget exhaustion date

**Resolution Steps:**
1. Create ticket for investigation
2. Schedule remediation work
3. Consider feature freeze if needed

**Escalation:**
- Team standup discussion
- Engineering manager if budget <50%

---

## Execution Safety Gate Alerts

### ExecutionGateDenySpike / AragoraExecutionGateDenySpike

**Severity:** High (warning in monitoring rules, high in alerting rules)
**SLO Impact:** Automation Safety Posture

**Alert Condition (conceptual):**
```promql
deny_ratio_15m > 0.25 for 10m
```

**Initial Triage:**
1. Check top deny reasons:
   ```promql
   topk(10, sum by (reason) (rate(aragora_execution_gate_blocks_total[30m])))
   ```
2. Segment by path/domain:
   ```promql
   sum by (path, domain) (rate(aragora_execution_gate_decisions_total{decision="deny"}[15m]))
   ```
3. Confirm whether a deployment or policy change happened in the last hour.

**Resolution Steps:**
1. If denials are mostly `tainted_context_detected`:
   - Treat as potential prompt-injection wave.
   - Disable risky upstream retrieval sources and enforce manual approvals.
2. If denials are mostly diversity-related:
   - Verify ensemble composition did not regress to a single provider/family.
   - Restore multi-provider participant mix.
3. If denials are mostly dissent-related:
   - Review unresolved high-severity critiques and tune task decomposition.

**Escalation:**
- 10 minutes sustained firing: page on-call platform engineer.
- 30 minutes sustained firing with user impact: escalate to incident commander.

---

### ExecutionGateReceiptVerificationFailures / AragoraExecutionGateReceiptVerificationFailures

**Severity:** Critical
**SLO Impact:** Decision Integrity and Receipt Trust

**Alert Condition (conceptual):**
```promql
receipt_verification_failure_ratio_15m > 0.02 for 10m
```

**Initial Triage:**
1. Check failure ratio split:
   ```promql
   sum by (path, domain, status) (
     rate(aragora_execution_gate_receipt_verification_total[15m])
   )
   ```
2. Inspect gate reasons for signer/freshness failures:
   ```promql
   sum by (reason) (rate(aragora_execution_gate_blocks_total[30m]))
   ```
3. Verify signing key configuration and recent key-rotation changes.

**Resolution Steps:**
1. If `receipt_signer_not_allowlisted`:
   - Add rotated signer key ID to allowlist after approval.
   - Re-run validation checks in CI.
2. If `receipt_stale` or `receipt_timestamp_in_future`:
   - Check signer clock skew and NTP sync.
   - Confirm freshness window configuration is correct.
3. If `receipt_verification_failed`:
   - Validate receipt signing key is present and consistent across workers.
   - Force manual approval mode for auto-execution until receipt trust is healthy.

**Escalation:**
- Immediate page to on-call and security lead.
- If failure persists beyond 15 minutes, declare incident and freeze autonomous execution.

---

## General Procedures

### Incident Response Flow

1. **Acknowledge** alert within 5 minutes
2. **Assess** severity and impact
3. **Communicate** via incident channel
4. **Mitigate** to restore service
5. **Resolve** root cause
6. **Review** in post-incident meeting

### Communication Templates

**Initial Update:**
```
[INCIDENT] Aragora - {AlertName}
Impact: {Description of user impact}
Status: Investigating
ETA: Assessing
```

**Resolution Update:**
```
[RESOLVED] Aragora - {AlertName}
Impact: {Description of user impact}
Resolution: {What fixed it}
Duration: {How long}
Follow-up: {Any follow-up actions}
```

### Useful Commands

```bash
# Check pod status
kubectl get pods -l app=aragora -o wide

# View logs
kubectl logs -l app=aragora --tail=100 -f

# Check metrics
curl http://localhost:9090/api/v1/query?query=up{job="aragora"}

# Rollback deployment
kubectl rollout undo deployment/aragora

# Scale up
kubectl scale deployment/aragora --replicas=5

# Check circuit breakers
curl http://aragora:8080/api/health/circuits
```

---

## Contact Information

| Role | Contact | Escalation Time |
|------|---------|-----------------|
| On-Call Engineer | PagerDuty | Immediate |
| Backend Lead | Slack @backend-lead | 15 min |
| Security Team | Slack #security-ops | For security alerts |
| Infrastructure | Slack #infrastructure | For infra alerts |
| Incident Commander | PagerDuty escalation | 30 min |

---

**Document Version:** 1.0
**Last Updated:** March 5, 2026
**Owner:** Platform Team
