# BACKLOG_Q1_2026 Implementation Map (Owners + Files)

Last updated: 2026-02-12

This document maps the backlog items in `docs/status/BACKLOG_Q1_2026.md` to:
- suggested owners (by role),
- primary code/doc locations,
- concrete "definition of done" gates.

It is intended to be used during sprint planning and PR review so work lands in the right place and can be validated.

Related:
- Canonical execution order + CI gates: `docs/status/NEXT_STEPS_CANONICAL.md`
- SME wedge spec: `docs/status/SME_STARTER_PACK.md`
- Design partner program: `docs/status/DESIGN_PARTNER_PROGRAM.md`
- PMF scorecard: `docs/status/PMF_SCORECARD.md`

---

## Owner Roles (Suggested)

- Product: defines scope + success metrics + partner feedback loop
- Backend (Core): server handlers, orchestration, receipts, analytics
- Backend (Connectors): Slack/Gmail/Drive/Outlook integrations, wizard APIs
- Frontend (Live): onboarding wizard, admin UI, dashboards
- SDK: Python/TypeScript SDK, parity tests, examples
- DevOps/SRE: docker-compose, k8s, env wiring, observability bundle
- QA: e2e, smoke, connector test matrix, CI stability gates
- Docs: quickstarts, API reference, runbooks

---

## Sprint 1 (Weeks 1-2): Foundations & Audit

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-01 | Product + Docs | `docs/status/SME_STARTER_PACK.md`, `docs/status/PMF_SCORECARD.md` | Metrics + success criteria agreed; scorecard template ready for partner scoring |
| SME-02 | Backend (Connectors) | `aragora/server/handlers/oauth_wizard.py`, `aragora/connectors/chat/slack/`, `aragora/connectors/enterprise/communication/gmail/`, `aragora/connectors/enterprise/documents/gdrive.py` | Audit report: setup steps, required env vars, failure modes; top 5 fixes prioritized with repro steps |
| SME-03 | Frontend (Live) + Backend (Core) | `aragora/live/src/components/onboarding/`, `aragora/server/handlers/onboarding.py`, `docs/guides/ONBOARDING_FLOW.md` | Single golden path documented and validated against UI/API; time-to-first-receipt measurement plan defined |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-01 | SDK + Backend (Core) | `scripts/generate_openapi.py`, `scripts/export_openapi.py`, `scripts/validate_openapi_routes.py`, `docs/openapi.yaml`, `openapi.json` | OpenAPI generation is reproducible and enforced in CI; route validation blocks drift |
| DEV-02 | Docs + SDK | `docs/SDK_GUIDE.md`, `docs/reference/`, `docs/api/` | API reference includes copy/paste examples for 3 core flows (debate, receipt export, onboarding quick-start) |
| DEV-03 | SDK | `docs/guides/SDK_PARITY.md`, `tests/sdk/`, `scripts/verify_sdk_contracts.py` | Parity gap report updated; top 20 parity gaps filed as backlog items with owners |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-01 | DevOps/SRE | `docker-compose.production.yml`, `docker-compose.simple.yml`, `deploy/` | One recommended compose path identified as baseline; validated start/stop instructions |
| HOST-02 | DevOps/SRE + Docs | `.env.example`, `.env.production.example`, `.env.production.template` | All required env vars documented and grouped; no "unknown required" vars during startup |
| HOST-03 | Docs + DevOps/SRE | `deploy/README.md`, `docs/deployment/` | Self-host quickstart produces running system and "first receipt" flow in <30 minutes |

### Release Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| REL-01 | Platform + SDK | `.github/workflows/`, `scripts/check_version_alignment.py` (or equivalent) | CI blocks SDK/server/doc version drift; reproducible release checks |
| REL-02 | Release Eng + Docs | `CHANGELOG.md` | Release notes updated with user-visible changes and migration notes |

---

## Sprint 2 (Weeks 3-4): SME Starter Pack v0.1 & Dev Docs

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-04 | Frontend (Live) + Backend (Core) | `aragora/live/src/components/onboarding/`, `aragora/server/handlers/onboarding.py` | Onboarding completes end-to-end for a new org; e2e flow passes (`aragora/live/e2e/onboarding.spec.ts`) |
| SME-05 | Backend (Core) | `aragora/server/handlers/onboarding.py`, `aragora/debate/`, `aragora/export/decision_receipt.py` | Time-to-first-receipt p50 < 15 min on a clean setup; receipt export/share is part of flow |
| SME-06 | Backend (Core) + Frontend (Live) | `aragora/export/decision_receipt.py`, `aragora/cli/commands/receipt.py` | PDF/MD export works and is documented; missing optional deps fail with clear error message |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-04 | SDK | `sdk/typescript/src/namespaces/debates.ts`, `sdk/typescript/src/namespaces/receipts.ts`, `sdk/typescript/src/client.ts`, `sdk/typescript/src/websocket.ts` | TS SDK supports debate + receipt workflows including streaming; parity tests cover core flows |
| DEV-05 | SDK + Docs | `docs/guides/SDK_PARITY.md`, `tests/sdk/` | Parity doc regenerated from source of truth; CI blocks parity regressions |
| DEV-06 | SDK + Docs | `docs/SDK_GUIDE.md`, `examples/` | Streaming example exists (TS) and can be run against a local server |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-04 | Docs + Backend (Core) | `aragora/server/handlers/admin/health/__init__.py`, `aragora/server/handlers/gateway_health_handler.py`, `deploy/README.md` | Health/ready endpoints documented and used by compose/k8s readiness probes |
| HOST-05 | DevOps/SRE + QA | `scripts/check_self_host_compose.py`, `deploy/` | Smoke script exercises startup + basic API calls; used in CI gate |

---

## Sprint 3 (Weeks 5-6): Cost Controls & Examples

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-07 | Frontend (Live) + Backend (Core) | `aragora/analytics/dashboard.py`, `aragora/server/handlers/analytics*`, `aragora/live/src/` | Usage dashboard shows debates/receipts/cost; backend endpoints are stable |
| SME-08 | Backend (Core) | `aragora/control_plane/cost_enforcement.py`, `aragora/pipeline/decision_plan/core.py`, `aragora/rbac/middleware.py` | Budget caps enforced and observable; clear error surfaces to UI/CLI |
| SME-09 | Product + Backend (Core) | `aragora/server/handlers/workflow_templates.py`, `templates/`, `docs/status/SME_STARTER_PACK.md` | 8-12 templates exist with clear names, inputs, and outputs; recommended templates show up in onboarding |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-07 | SDK + Docs | `examples/`, `sdk/typescript/` | TS example app: streaming + receipts; runnable instructions |
| DEV-08 | SDK + Docs | `examples/`, `sdk/python/` | Python SDK basic usage example; runnable instructions |
| DEV-09 | Docs | `examples/README.md` (or equivalent) | examples directory has a consistent structure and quickstart |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-06 | Security + DevOps/SRE | `SECURITY.md`, `deploy/`, `docs/security/` | Secure-by-default compose: no unsafe defaults; clear hardening checklist |
| HOST-07 | DevOps/SRE + Docs | `deploy/`, `docs/deployment/` | TLS setup guide tested on a clean machine |
| HOST-08 | Docs | `docs/reference/CONFIGURATION.md`, `.env.production.example` | Env var docs are complete and match runtime config parsing |

---

## Sprint 4 (Weeks 7-8): Integration Polish & Error Handling

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-10 | Backend (Connectors) + Frontend (Live) | `aragora/server/handlers/oauth_wizard.py`, `aragora/connectors/chat/slack/`, `aragora/live/src/components/onboarding/IntegrationSelector.tsx` | Slack connect/disconnect/test is self-serve; failures are actionable |
| SME-11 | Backend (Connectors) + Frontend (Live) | `aragora/connectors/enterprise/communication/gmail/`, `aragora/connectors/enterprise/documents/gdrive.py` | Gmail/Drive setup wizard flows are self-serve; common failures documented |
| SME-12 | Backend (Core) | `aragora/audit/`, `aragora/audit/slack_audit.py` | Integration actions are auditable (connect/disconnect/config changes) |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-10 | SDK + Backend (Core) | `aragora/server/handlers/base.py`, `sdk/typescript/src/errors.ts` (or equivalent), `sdk/python/` | Error models align across server and SDKs; stable error codes |
| DEV-11 | SDK | `sdk/typescript/src/client.ts`, `sdk/python/` | Retry semantics are consistent and configurable; documented defaults |
| DEV-12 | Docs | `docs/reference/`, `docs/SDK_GUIDE.md` | Error code docs exist with examples and remediation steps |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-09 | DevOps/SRE + Backend (Core) | `deploy/observability/`, `aragora/observability/`, `docs/operations/OPERATIONS.md` | Metrics/logging bundle works out-of-the-box; dashboards load |
| HOST-10 | DevOps/SRE | `deploy/observability/`, `deploy/grafana/` (if present) | Sample Grafana dashboards are versioned and documented |

### QA Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| QA-01 | QA + Backend (Connectors) | `tests/connectors/`, `scripts/check_connector_exception_handling.py` | Connector test matrix covers Slack/Gmail/Drive; exception hygiene gate stays green |
| QA-02 | QA | `.github/workflows/` | CI uses mocks for external APIs; stable + deterministic runs |

---

## Sprint 5 (Weeks 9-10): Admin Features & Docs Polish

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-13 | Frontend (Live) + Backend (Core) | `aragora/server/handlers/workspace/`, `aragora/live/src/` | Workspace admin UI supports invites + roles + basic settings |
| SME-14 | Backend (Core) + Security | `aragora/rbac/`, `aragora/rbac/defaults/roles.py` | Simplified role model maps cleanly onto existing RBAC permissions |
| SME-15 | Frontend (Live) + Backend (Core) | `aragora/audit/`, `aragora/server/handlers/*audit*` | Audit log UI exists with search + export (at least JSON/CSV) |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-13 | Docs + Frontend (Live) | `docs-site/` or `docs/reference/` | Developer docs landing page exists; links to SDK + OpenAPI + examples |
| DEV-14 | Docs | `docs/QUICKSTART_DEVELOPER.md`, `docs/SDK_QUICKSTART_PYTHON.md` | One canonical developer path; no duplicate quickstarts |
| DEV-15 | Docs + Backend (Core) | `docs/status/MIGRATION_V1_TO_V2.md`, `docs/openapi.yaml` | Versioning policy is explicit and reflected in docs and headers |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-11 | DevOps/SRE | `deploy/`, `scripts/` | Backup/restore scripts are tested and documented |
| HOST-12 | DevOps/SRE + Docs | `docs/runbooks/`, `deploy/` | Upgrade runbook tested against one prior version |
| HOST-13 | DevOps/SRE + Docs | `deploy/DISASTER_RECOVERY.md` | DR steps are explicit and validated in a tabletop exercise |

### Release Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| REL-03 | Release Eng | `scripts/`, `CHANGELOG.md` | Changelog generation is automated and reproducible |
| REL-04 | Release Eng + QA | `.github/workflows/` | Pre-release validation gate blocks broken artifacts |

---

## Sprint 6 (Weeks 11-12): GA Polish & Release

### SME Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| SME-16 | Frontend (Live) + Backend (Core) | `aragora/analytics/`, `aragora/live/src/` | ROI/usage dashboard answers "what did we save?" with evidence |
| SME-17 | Docs | `docs/status/SME_STARTER_PACK.md`, `docs/guides/SME_GA_GUIDE.md` | GA docs for SME starter pack are complete and tested |
| SME-18 | Product + Frontend (Live) | `aragora/live/src/`, `aragora/server/handlers/feedback.py` (or equivalent) | Feedback capture is built-in and tied to receipts/workflows |

### Developer Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| DEV-16 | SDK | `tests/sdk/`, `docs/guides/SDK_PARITY.md` | TS SDK parity >= 95% on tracked namespaces; parity gate blocks regressions |
| DEV-17 | Backend (Core) + QA | `tests/server/`, `scripts/validate_openapi_routes.py` | API coverage tests exist for core workflows; CI blocks missing coverage |
| DEV-18 | Docs + Frontend (Live) | `docs-site/` | Developer portal is coherent and current |

### Self-Hosted Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| HOST-14 | DevOps/SRE + QA | `docker-compose.production.yml`, `scripts/check_self_host_compose.py` | Self-hosted GA sign-off: from clean machine to first receipt <30 min |
| HOST-15 | DevOps/SRE | `docs/deployment/`, `deploy/` | Production checklist exists and is validated |
| HOST-16 | Docs | `docs/deployment/`, `docs/status/COMMERCIAL_POSITIONING.md` | Self-hosted vs hosted comparison is explicit and honest |

### QA Track

| ID | Owner | Primary Files/Areas | Definition of Done (Gate) |
|---|---|---|---|
| QA-03 | QA | `tests/e2e/` (if present), `aragora/live/e2e/` | End-to-end smoke tests cover hosted + self-hosted happy path |
| QA-04 | QA + Platform | `.github/workflows/` | Nightly CI runs capture regressions early; failures triaged to owners |

---

## Stretch Goals (Weeks 13-16)

This set is only pursued if:
- 3+ design partners are above the "SCALE" threshold in `docs/status/PMF_SCORECARD.md`, and
- canonical stability gates remain green.

Suggested primary locations:
- Notion/Confluence: `aragora/connectors/enterprise/documents/` + `aragora/server/handlers/oauth_wizard.py`
- Jira: `aragora/connectors/enterprise/` + `aragora/server/handlers/*jira*`
- CLI scaffolding: `aragora/cli/init.py`, `aragora/cli/commands/`
- Helm: `deploy/k8s/` + `aragora-operator/`
