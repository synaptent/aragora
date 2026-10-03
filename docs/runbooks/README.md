# Incident Runbooks

Operational runbooks for responding to Aragora alerts and incidents.

## Alert Reference

| Alert | Severity | Runbook |
|-------|----------|---------|
| ServiceDown | critical | [service-down.md](./service-down.md) |
| HighErrorRate | critical | [high-error-rate.md](./high-error-rate.md) |
| HighAPILatency | warning | [high-latency.md](./high-latency.md) |
| DatabaseConnectionExhausted | critical | [database-issues.md](./database-issues.md) |
| RedisUnavailable | critical | [redis-issues.md](./redis-issues.md) |
| StartupSLOExceeded | warning | [RUNBOOK_STARTUP_ISSUES.md](./RUNBOOK_STARTUP_ISSUES.md) |
| StartupFailed | critical | [RUNBOOK_STARTUP_ISSUES.md](./RUNBOOK_STARTUP_ISSUES.md) |
| DecaySchedulerStopped | warning | [RUNBOOK_KNOWLEDGE_DECAY.md](./RUNBOOK_KNOWLEDGE_DECAY.md) |
| StaleWorkspace | warning | [RUNBOOK_KNOWLEDGE_DECAY.md](./RUNBOOK_KNOWLEDGE_DECAY.md) |

## Operational Runbooks

| Topic | Runbook | Description |
|-------|---------|-------------|
| **Disaster Recovery** | [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) | **Comprehensive DR runbook with RTO/RPO targets, failover procedures, backup verification** |
| Server Startup | [RUNBOOK_STARTUP_ISSUES.md](./RUNBOOK_STARTUP_ISSUES.md) | Startup failures, SLO violations |
| Database Migration | [RUNBOOK_DATABASE_CONSOLIDATION.md](./RUNBOOK_DATABASE_CONSOLIDATION.md) | Consolidating legacy databases |
| Knowledge Decay | [RUNBOOK_KNOWLEDGE_DECAY.md](./RUNBOOK_KNOWLEDGE_DECAY.md) | Confidence decay monitoring |
| Deployment | [RUNBOOK_DEPLOYMENT.md](./RUNBOOK_DEPLOYMENT.md) | Deployment procedures |
| Security | [RUNBOOK_SECURITY.md](./RUNBOOK_SECURITY.md) | Security incident response |
| Key Rotation | [RUNBOOK_KEY_ROTATION.md](./RUNBOOK_KEY_ROTATION.md) | Encryption key rotation |
| PostgreSQL | [RUNBOOK_POSTGRESQL_MIGRATION.md](./RUNBOOK_POSTGRESQL_MIGRATION.md) | PostgreSQL migration |
| Backup Automation | [RUNBOOK_BACKUP_AUTOMATION.md](./RUNBOOK_BACKUP_AUTOMATION.md) | Automated backup scheduling and validation |
| Redis Failover | [redis-failover.md](./redis-failover.md) | Redis HA and recovery procedures |
| Multi-Region | [RUNBOOK_MULTI_REGION_SETUP.md](./RUNBOOK_MULTI_REGION_SETUP.md) | Multi-region deployment and failover |
| Fleet Coordination | [RUNBOOK_FLEET_COORDINATION.md](./RUNBOOK_FLEET_COORDINATION.md) | Multi-agent worktree ownership and merge queue policy |
| Merge-State `UNSTABLE` Settlement | [MERGE_STATE_UNSTABLE_SETTLEMENT.md](./MERGE_STATE_UNSTABLE_SETTLEMENT.md) | Classifying GitHub merge-state blockers from required checks, advisory checks, cancelled CI runs, and the proposed allowlisted non-required cancellation predicate |
| Proof-First tmux Operator | [RUNBOOK_PROOF_FIRST_TMUX_OPERATOR.md](./RUNBOOK_PROOF_FIRST_TMUX_OPERATOR.md) | Conductor-led tmux coordination for benchmark/docs/monitor lanes without replacing the unattended proof-first shift |
| Outbox Depth Reconcile | [RUNBOOK_OUTBOX_DEPTH_RECONCILE.md](./RUNBOOK_OUTBOX_DEPTH_RECONCILE.md) | Queue-depth disposition rubric for protected, human-gated, and unparseable automation outbox items |
| First-Error Diagnostic Receipts | [first-error-receipt-protocol.md](./first-error-receipt-protocol.md) | Exact-main diagnostic ownership, durable logs and reports, outcome classification, and conservative worktree reclaim |
| Outbox Disposition | [outbox-disposition-rubric.md](./outbox-disposition-rubric.md) | Read-only rubric for classifying automation outbox-depth blockers before any publisher or reconcile mutation |
| Harvest Disposition | [harvest-disposition-rubric.md](./harvest-disposition-rubric.md) | Claim, classify, and receipt stale #8993 worktree harvest items without mutating shared-root or source worktree state |
| Second-Signal Completion | [second-signal-completion-rubric.md](./second-signal-completion-rubric.md) | Conductor rubric for completing a missing model-family signal without bypassing evidence gates |

## Incident Severity Levels

| Level | Response Time | Description |
|-------|---------------|-------------|
| SEV1 | 15 min | Complete outage, data loss risk |
| SEV2 | 1 hour | Major feature degraded |
| SEV3 | 4 hours | Minor feature impacted |
| SEV4 | Next business day | Cosmetic/low-impact issues |

## On-Call Contacts

Configure in environment:
- `ONCALL_SLACK_CHANNEL` - Slack channel for alerts
- `ONCALL_PAGERDUTY_KEY` - PagerDuty integration key
- `ONCALL_EMAIL` - Fallback email address
