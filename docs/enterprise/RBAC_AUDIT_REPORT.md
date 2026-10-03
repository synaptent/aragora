# RBAC Handler Audit Report

**Generated:** 2026-01-27
**Audited by:** Claude Code

## Executive Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| Total handler files | 268 | 100% |
| Files with security decorators | 138 | 51.5% |
| **Files needing RBAC review** | **130** | **48.5%** |
| - ENDPOINT files (need RBAC) | 112 | 42% |
| - UTILITY files (may skip) | 18 | 7% |

## Security Decorator Usage

| Decorator | Usage Count |
|-----------|-------------|
| `@require_permission` | 484 |
| `@secure_endpoint` | 6 |
| `@admin_secure_endpoint` | 5 |

## Priority 1: CRITICAL (Auth/Admin/OAuth)

These endpoints handle authentication, authorization, and admin functions. **Must be secured immediately.**

| File | Risk | Notes |
|------|------|-------|
| `admin/cache.py` | CRITICAL | Cache management - admin only |
| `admin/dashboard.py` | CRITICAL | Admin dashboard |
| `auth/handler.py` | CRITICAL | Core auth endpoints |
| `auth/signup_handlers.py` | CRITICAL | User registration |
| `auth/store.py` | CRITICAL | User data access |
| `oauth_wizard.py` | CRITICAL | OAuth setup flow |
| `sso.py` | CRITICAL | SSO configuration |
| `social/*_oauth.py` (4 files) | CRITICAL | OAuth for Slack/Teams/Discord |

**Action:** Add `@require_permission` or `@admin_secure_endpoint` to all endpoints.

## Priority 2: HIGH (Data Access/External Integrations)

These endpoints access sensitive data or external systems.

### Bot/Webhook Handlers (8 files)
- `bots/discord.py`
- `bots/email_webhook.py`
- `bots/google_chat.py`
- `bots/slack.py`
- `bots/teams.py`
- `bots/telegram.py`
- `bots/whatsapp.py`
- `bots/zoom.py`

**Note:** Webhook endpoints may use signature verification instead of RBAC.

### Gmail Integration (4 files)
- `features/gmail_ingest.py`
- `features/gmail_labels.py`
- `features/gmail_query.py`
- `features/gmail_threads.py`

**Risk:** Email data access requires strict permission controls.

### Other High-Risk
- `features/cloud_storage.py` - File access
- `features/crm.py` - Customer data
- `knowledge_chat.py`, `knowledge/*.py` - Knowledge base
- `memory/*.py` (4 files) - Memory systems
- `workspace.py` - Workspace management

## Priority 3: MEDIUM (Operational)

| Category | Files |
|----------|-------|
| Agents | `agents/*.py` (4 files) |
| Analytics | `analytics.py`, `analytics_metrics.py` |
| Debates | `debates/*.py` (2 files) |
| Autonomous | `autonomous/*.py` (5 files) |
| Features | `features/control_plane.py`, `features/devops.py`, etc. |

## Priority 4: LOW (Utilities/Public)

These may not require RBAC decorators:

### Intentionally Public
- `public/status_page.py` - Health check (should be public)

### Internal Utilities (no direct HTTP exposure)
- `utils/*.py` - Helper functions
- `metrics/formatters.py` - Formatting only
- `debates/response_formatting.py` - Response helpers
- `knowledge_base/mound/base_mixin.py` - Base class

## Recommended Actions

### Immediate (Week 1)
1. Add RBAC to all Priority 1 (CRITICAL) files
2. Review bot handlers for signature verification
3. Add RBAC to Gmail integration files

### Short-term (Week 2-3)
4. Add RBAC to all Priority 2 (HIGH) files
5. Add RBAC to Priority 3 (MEDIUM) files
6. Document intentionally public endpoints

### Validation
```bash
# Check RBAC coverage after fixes
grep -rl "@require_permission\|@admin_secure_endpoint" aragora/server/handlers/ | wc -l
# Target: 200+ files (75%+)

# Run RBAC tests
pytest tests/rbac/ -v --cov=aragora/rbac
```

## Files Requiring Review

### ENDPOINT files without security decorators (112 total)

```
aragora/server/handlers/_oauth_impl.py
aragora/server/handlers/admin/cache.py
aragora/server/handlers/admin/dashboard.py
aragora/server/handlers/admin/health_utils.py
aragora/server/handlers/admin/health/probes.py
aragora/server/handlers/agents/agents.py
aragora/server/handlers/agents/calibration.py
aragora/server/handlers/agents/config.py
aragora/server/handlers/agents/leaderboard.py
aragora/server/handlers/analytics_metrics.py
aragora/server/handlers/analytics.py
aragora/server/handlers/auth/handler.py
aragora/server/handlers/auth/signup_handlers.py
aragora/server/handlers/auth/store.py
aragora/server/handlers/autonomous/alerts.py
aragora/server/handlers/autonomous/approvals.py
aragora/server/handlers/autonomous/learning.py
aragora/server/handlers/autonomous/monitoring.py
aragora/server/handlers/autonomous/triggers.py
aragora/server/handlers/bots/discord.py
aragora/server/handlers/bots/email_webhook.py
aragora/server/handlers/bots/google_chat.py
aragora/server/handlers/bots/slack.py
aragora/server/handlers/bots/teams.py
aragora/server/handlers/bots/telegram.py
aragora/server/handlers/bots/whatsapp.py
aragora/server/handlers/bots/zoom.py
aragora/server/handlers/budgets.py
aragora/server/handlers/canvas/handler.py
aragora/server/handlers/chat/router.py
aragora/server/handlers/codebase/intelligence.py
aragora/server/handlers/codebase/metrics.py
aragora/server/handlers/codebase/quick_scan.py
aragora/server/handlers/dashboard.py
aragora/server/handlers/debates/graph_debates.py
aragora/server/handlers/debates/matrix_debates.py
aragora/server/handlers/decisions/explain.py
aragora/server/handlers/deliberations.py
aragora/server/handlers/dependency_analysis.py
aragora/server/handlers/email_services.py
aragora/server/handlers/explainability_store.py
aragora/server/handlers/external_integrations.py
aragora/server/handlers/features/advertising.py
aragora/server/handlers/features/analytics_platforms.py
aragora/server/handlers/features/audio.py
aragora/server/handlers/features/audit_sessions.py
aragora/server/handlers/features/cloud_storage.py
aragora/server/handlers/features/codebase_audit.py
aragora/server/handlers/features/connectors.py
aragora/server/handlers/features/control_plane.py
aragora/server/handlers/features/crm.py
aragora/server/handlers/features/cross_platform_analytics.py
aragora/server/handlers/features/devops.py
aragora/server/handlers/features/ecommerce.py
aragora/server/handlers/features/finding_workflow.py
aragora/server/handlers/features/gmail_ingest.py
aragora/server/handlers/features/gmail_labels.py
aragora/server/handlers/features/gmail_query.py
aragora/server/handlers/features/gmail_threads.py
aragora/server/handlers/features/integrations.py
aragora/server/handlers/features/rlm.py
aragora/server/handlers/features/routing_rules.py
aragora/server/handlers/features/support.py
aragora/server/handlers/gauntlet_v1.py
aragora/server/handlers/inbox_command.py
aragora/server/handlers/inbox/action_items.py
aragora/server/handlers/integrations.py
aragora/server/handlers/knowledge_base/mound/dashboard.py
aragora/server/handlers/knowledge_chat.py
aragora/server/handlers/knowledge/analytics.py
aragora/server/handlers/knowledge/checkpoints.py
aragora/server/handlers/knowledge/sharing_notifications.py
aragora/server/handlers/memory/coordinator.py
aragora/server/handlers/memory/insights.py
aragora/server/handlers/memory/learning.py
aragora/server/handlers/memory/memory_analytics.py
aragora/server/handlers/metrics/tracking.py
aragora/server/handlers/nomic.py
aragora/server/handlers/oauth_wizard.py
aragora/server/handlers/orchestration.py
aragora/server/handlers/public/status_page.py
aragora/server/handlers/queue.py
aragora/server/handlers/repository.py
aragora/server/handlers/social/_slack_impl/handler.py
aragora/server/handlers/social/collaboration.py
aragora/server/handlers/social/discord_oauth.py
aragora/server/handlers/social/notifications.py
aragora/server/handlers/social/slack_oauth.py
aragora/server/handlers/social/teams_oauth.py
aragora/server/handlers/social/teams.py
aragora/server/handlers/social/telegram.py
aragora/server/handlers/social/telemetry.py
aragora/server/handlers/social/tts_helper.py
aragora/server/handlers/social/whatsapp.py
aragora/server/handlers/sso.py
aragora/server/handlers/verification/formal_verification.py
aragora/server/handlers/verticals.py
aragora/server/handlers/voice/handler.py
aragora/server/handlers/webhook_management.py
aragora/server/handlers/workflows.py
aragora/server/handlers/workspace.py
```

### UTILITY files (may not need RBAC) - 18 total

```
aragora/server/handlers/admin/health/handler.py
aragora/server/handlers/auth/validation.py
aragora/server/handlers/base.py
aragora/server/handlers/debates/response_formatting.py
aragora/server/handlers/exceptions.py
aragora/server/handlers/interface.py
aragora/server/handlers/knowledge_base/mound/base_mixin.py
aragora/server/handlers/knowledge_base/mound/curation.py
aragora/server/handlers/knowledge.py
aragora/server/handlers/metrics.py
aragora/server/handlers/metrics/formatters.py
aragora/server/handlers/oauth/handler.py
aragora/server/handlers/openapi_decorator.py
aragora/server/handlers/social/chat_events.py
aragora/server/handlers/social/slack/config.py
aragora/server/handlers/social/slack/handler.py
aragora/server/handlers/social/slack/security.py
aragora/server/handlers/social/slack/utils/responses.py
aragora/server/handlers/types.py
aragora/server/handlers/utilities.py
aragora/server/handlers/utils/*.py (remaining)
```
