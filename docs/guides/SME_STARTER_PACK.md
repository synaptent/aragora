# SME Starter Pack

**Version:** 1.0
**Status:** Scope Definition
**Target:** First debate + decision receipt in <15 minutes

---

## Overview

The SME (Small/Medium Enterprise) Starter Pack provides a streamlined onboarding experience for teams of 5-50 users. It enables organizations to run their first AI-facilitated debate and receive a decision receipt within 15 minutes of signup.

## Target Audience

- **Company Size:** 5-50 employees
- **Decision Types:** Team decisions, project planning, vendor selection, policy changes
- **Technical Level:** Low to moderate (no engineering required)
- **Budget:** $49-500/month (Pro tier: $49/seat/month)

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Time to first debate | <5 minutes | Onboarding funnel analytics |
| Time to first receipt | <15 minutes | End-to-end timing |
| Integration setup time | <10 minutes per connector | User testing |
| First-week retention | >60% | Cohort analysis |
| NPS score | >40 | Survey |

---

## Included Components

### 1. Guided Onboarding Wizard

A step-by-step wizard that walks users through:

1. **Workspace Creation** (2 min)
   - Organization name
   - Admin email verification
   - Workspace URL selection

2. **First Integration** (5 min)
   - Slack recommended (most common)
   - OAuth flow with permissions explanation
   - Test message to confirm connection

3. **First Debate** (5 min)
   - Template selection (8-12 pre-built templates)
   - Topic entry
   - Agent selection (auto-recommended)
   - Run debate

4. **Decision Receipt** (3 min)
   - View receipt in UI
   - Export options (PDF, Markdown)
   - Share to connected channel

### 2. Pre-Configured Integrations

| Integration | Status | Auth Method | Setup Time |
|-------------|--------|-------------|------------|
| Slack | Production-ready | OAuth 2.0 | 3 min |
| Gmail | Production-ready | OAuth 2.0 | 5 min |
| Google Drive | Production-ready | OAuth 2.0 | 5 min |
| Outlook | Production-ready | OAuth 2.0 | 5 min |

**Implementation References:**
- `aragora/connectors/chat/slack/` (2,304 lines, circuit breaker)
- `aragora/connectors/enterprise/communication/gmail/` (1,605 lines)
- `aragora/connectors/enterprise/documents/gdrive.py`
- `aragora/connectors/email/outlook_sync.py` (1,004 lines)

### 3. Workflow Templates Library

8-12 pre-built templates for common SME decisions:

| Category | Template | Agents | Rounds |
|----------|----------|--------|--------|
| **Team** | Hiring Decision | Claude, GPT-4 | 3 |
| **Team** | Performance Review | Claude, Gemini | 2 |
| **Project** | Feature Prioritization | Claude, GPT-4, Mistral | 3 |
| **Project** | Sprint Planning | Claude, GPT-4 | 2 |
| **Vendor** | Tool Selection | Claude, GPT-4, Gemini | 4 |
| **Vendor** | Contract Review | Claude, GPT-4 | 3 |
| **Policy** | Remote Work Policy | Claude, GPT-4, Gemini | 3 |
| **Policy** | Budget Allocation | Claude, GPT-4 | 2 |

### 4. Usage Dashboard

Real-time visibility into:

- **Debates:** Count, topics, participants
- **Spend:** API costs by model, budget remaining
- **Integrations:** Connected channels, message volume
- **Receipts:** Generated, exported, shared

### 5. Budget Controls

- **Workspace Caps:** Maximum monthly spend
- **Alerts:** 50%, 75%, 90% threshold notifications
- **Per-Debate Limits:** Optional cost ceiling per debate

---

## MVP Features (Sprint 1-2)

| Feature | Priority | Sprint |
|---------|----------|--------|
| Onboarding wizard | P0 | Sprint 2 |
| First debate flow | P0 | Sprint 2 |
| Decision receipt export | P0 | Sprint 2 |
| Slack integration wizard | P0 | Sprint 4 |
| Gmail/Drive integration wizard | P0 | Sprint 4 |
| Usage dashboard | P0 | Sprint 3 |
| Budget caps | P0 | Sprint 3 |
| Template library (8 templates) | P1 | Sprint 3 |

## Post-MVP Features (Sprint 5-6)

| Feature | Priority | Sprint |
|---------|----------|--------|
| Workspace admin UI | P0 | Sprint 5 |
| RBAC-lite (admin/member) | P0 | Sprint 5 |
| ROI dashboard | P0 | Sprint 6 |
| Template library (12 templates) | P1 | Sprint 6 |
| Audit log UI | P1 | Sprint 5 |
| User feedback collection | P1 | Sprint 6 |

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SME Starter Pack                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Onboarding │  │   Debate    │  │   Receipt   │         │
│  │    Wizard   │──│    Flow     │──│   Export    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│         │                │                │                  │
│         ▼                ▼                ▼                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Integration Layer                        │   │
│  │  ┌───────┐  ┌───────┐  ┌───────┐  ┌────────┐       │   │
│  │  │ Slack │  │ Gmail │  │ Drive │  │Outlook │       │   │
│  │  └───────┘  └───────┘  └───────┘  └────────┘       │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Core Aragora Engine                      │   │
│  │  • Debate Orchestration (Arena)                      │   │
│  │  • Agent Pool (43 agent types)                       │   │
│  │  • Receipt Generation (Gauntlet)                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Pricing Tiers (Proposed)

| Tier | Users | Debates/mo | Price |
|------|-------|------------|-------|
| Starter | 5 | 50 | $99/mo |
| Team | 15 | 200 | $249/mo |
| Business | 50 | Unlimited | $499/mo |

All tiers include:
- All 4 integrations
- All workflow templates
- Decision receipts
- Usage dashboard
- Email support

---

## Security & Compliance

### Data Protection

| Control | Implementation | Status |
|---------|----------------|--------|
| Encryption at rest | AES-256-GCM | Production-ready |
| Encryption in transit | TLS 1.3 | Production-ready |
| API authentication | JWT + API keys | Production-ready |
| Session management | Secure cookies, 24h expiry | Production-ready |

### Access Control (RBAC-lite)

SME tier includes simplified role model:

| Role | Permissions |
|------|-------------|
| **Owner** | Full workspace control, billing, member management |
| **Admin** | Manage integrations, templates, view all debates |
| **Member** | Run debates, view own results, export receipts |

**Implementation:** `aragora/rbac/` module with 420+ granular permission strings across 15 core resource types, mapped to these simplified roles for the SME tier.

### Compliance

- **SOC 2 Type II:** 98% controls implemented (see `docs/COMMERCIAL_OVERVIEW.md`)
- **GDPR:** Data export, deletion APIs available
- **Audit Logging:** All debate actions logged with 90-day retention

### Security Best Practices

```
Workspace Security Checklist:
[ ] Enable SSO (optional, available on Business tier)
[ ] Configure IP allowlisting (optional)
[ ] Review member permissions quarterly
[ ] Enable 2FA for admin accounts
[ ] Configure budget alerts
```

---

## Integration Setup Guide

### Slack Integration

**OAuth Flow:**
1. Click "Connect Slack" in integrations
2. Authorize Aragora app with requested scopes:
   - `channels:read` - List channels for debate routing
   - `chat:write` - Post debate results
   - `users:read` - Display member names
3. Select default channel for results
4. Send test message to confirm

**Error Handling:**
| Error | Resolution |
|-------|------------|
| "OAuth rejected" | Re-authorize with workspace admin |
| "Token expired" | Reconnect integration |
| "Rate limited" | Results queued, delivered within 5min |

**Implementation:** `aragora/connectors/chat/slack/` (circuit breaker enabled)

### Gmail Integration

**OAuth Flow:**
1. Click "Connect Gmail" in integrations
2. Sign in with Google account
3. Grant permissions:
   - `gmail.readonly` - Read emails for context
   - `gmail.send` - Send debate summaries
4. Configure email routing rules

**Scopes Justification:**
- Read access enables evidence collection from email threads
- Send access allows sharing receipts via email

### Google Drive Integration

**Setup:**
1. Connect Google account (shared OAuth with Gmail)
2. Select folders for document access
3. Configure auto-scan for decision-relevant documents

### Outlook Integration

**OAuth Flow:**
1. Click "Connect Outlook" in integrations
2. Sign in with Microsoft account
3. Grant permissions:
   - `Mail.Read` - Access email context
   - `Mail.Send` - Share results
4. Configure routing

---

## Budget Controls API

### Configuration

Budget controls are configured per workspace:

```python
# API: POST /api/v2/workspaces/{workspace_id}/budget
{
    "monthly_cap_usd": 500.00,
    "per_debate_limit_usd": 5.00,
    "alert_thresholds": [0.50, 0.75, 0.90],
    "hard_stop_at_cap": true,
    "notification_channels": ["email", "slack"]
}
```

### Alert Thresholds

| Threshold | Action | Notification |
|-----------|--------|--------------|
| 50% | Info alert | Email to admins |
| 75% | Warning | Email + Slack |
| 90% | Critical | Email + Slack + UI banner |
| 100% | Hard stop | Block new debates until reset |

### Cost Estimation

| Operation | Estimated Cost |
|-----------|---------------|
| 2-agent, 2-round debate | ~$0.15 |
| 3-agent, 3-round debate | ~$0.35 |
| 5-agent, 4-round debate | ~$0.80 |
| Document ingestion (per 10 pages) | ~$0.05 |

**Implementation:** `aragora/billing/budget_manager.py`, `aragora/server/handlers/costs.py`

### Webhooks

Configure budget webhooks for external monitoring:

```python
# API: POST /api/v2/workspaces/{workspace_id}/webhooks
{
    "event": "budget.threshold_reached",
    "url": "https://your-system.com/webhook",
    "threshold": 0.75
}
```

---

## Support & Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Debate timeout | Check agent availability, retry with fewer agents |
| Low confidence result | Add more context, increase rounds |
| Integration disconnected | Re-authorize OAuth in settings |
| Budget exceeded | Upgrade tier or wait for monthly reset |

### Support Channels

| Tier | Support Level | Response Time |
|------|---------------|---------------|
| Starter | Email | 48h business hours |
| Team | Email + Chat | 24h business hours |
| Business | Email + Chat + Priority | 4h business hours |

### Escalation Path

1. **Self-Service:** Check `docs/TROUBLESHOOTING.md`
2. **Email Support:** support@aragora.io
3. **Priority Escalation:** Contact your account manager (Business tier)

### SLA Definitions

| Metric | Target |
|--------|--------|
| API uptime | 99.9% |
| Debate completion rate | >99% |
| Receipt generation | <30s |

---

## Dependencies

| Dependency | Status | Risk | Mitigation |
|------------|--------|------|------------|
| OAuth UI for integrations | Gap | Medium | Build unified OAuth wizard |
| Onboarding wizard UI | Gap | Low | Use existing Live app patterns |
| Budget controls backend | Exists | Low | Wire to billing module |
| Template library | Partial | Low | Document existing templates |

---

## Related Documents

- [Feature Gap List](../FEATURE_GAP_LIST.md) - Sprint planning
- [INTEGRATION_AUDIT.md](../enterprise/INTEGRATION_AUDIT.md) - Connector assessment
- [ONBOARDING_FLOW.md](../guides/ONBOARDING_FLOW.md) - Detailed flow design

---

*Created: 2026-01-24*
*Next Review: Sprint 2 Planning*
