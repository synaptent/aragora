#!/usr/bin/env node
/**
 * Sync documentation from main docs/ directory to Docusaurus structure.
 *
 * This script copies and transforms markdown files from the main docs/
 * directory to the Docusaurus docs/ directory with proper structure.
 *
 * Usage:
 *   node scripts/sync-docs.js
 */

const fs = require('fs');
const path = require('path');

// Source and destination directories
const REPO_ROOT = path.join(__dirname, '../..');
const SOURCE_DIR = path.join(REPO_ROOT, 'docs');
const DEST_DIR = path.join(__dirname, '../docs');

// Document mapping: source -> destination with category organization. Keys are literal
// docs/<path>.md sources; a key that does not exist fails the sync.
const DOC_MAP = {
  // `docs-site/docs/enterprise/positioning.md` is intentionally hand-maintained
  // as a redirect-style stub after archiving `docs/status/COMMERCIAL_POSITIONING.md`.

  // =========================================================================
  // Getting Started
  // =========================================================================
  'docs/guides/GETTING_STARTED.md': 'getting-started/overview.md',
  'docs/quickstart.md': 'getting-started/quickstart.md',
  'docs/reference/CONFIGURATION.md': 'getting-started/configuration.md',
  'docs/reference/ENVIRONMENT.md': 'getting-started/environment.md',

  // =========================================================================
  // Core Concepts
  // =========================================================================
  'docs/debate/DEBATE_PHASES.md': 'core-concepts/debates.md',
  'docs/debate/DEBATE_INTERNALS.md': 'core-concepts/debate-internals.md',
  'docs/debate/AGENTS.md': 'core-concepts/agents.md',
  'docs/debate/AGENT_DEVELOPMENT.md': 'core-concepts/agent-development.md',
  'docs/debate/AGENT_SELECTION.md': 'core-concepts/agent-selection.md',
  'docs/algorithms/CONSENSUS.md': 'core-concepts/consensus.md',
  'docs/knowledge/MEMORY_TIERS.md': 'core-concepts/memory.md',
  'docs/knowledge/MEMORY.md': 'core-concepts/memory-overview.md',
  'docs/knowledge/MEMORY_STRATEGY.md': 'core-concepts/memory-strategy.md',
  'docs/knowledge/KNOWLEDGE_MOUND.md': 'core-concepts/knowledge-mound.md',
  'docs/architecture/ARCHITECTURE.md': 'core-concepts/architecture.md',
  'docs/workflow/REASONING.md': 'core-concepts/reasoning.md',
  'docs/workflow/WORKFLOW_ENGINE.md': 'core-concepts/workflow-engine.md',

  // =========================================================================
  // Guides
  // =========================================================================
  'docs/receipts/VERIFY_IN_60_SECONDS.md': 'guides/verify-in-60-seconds.md',
  'docs/SDK_GUIDE.md': 'guides/sdk.md',
  'docs/guides/SDK_QUICKSTART.md': 'guides/sdk-quickstart.md',
  'docs/guides/PYTHON_SDK_MIGRATION.md': 'guides/python-sdk-migration.md',
  'docs/api/API_REFERENCE_CURATED.md': 'api-reference/index.md',
  'docs/api/API_QUICK_START.md': 'guides/api-quickstart.md',
  'docs/api/API_USAGE.md': 'guides/api-usage.md',
  'docs/workflow/WORKFLOWS.md': 'guides/workflows.md',
  'docs/workflow/SKILLS.md': 'guides/skills.md',
  'docs/workflow/TEMPLATES.md': 'guides/templates.md',
  'docs/integrations/INTEGRATIONS.md': 'guides/integrations.md',
  'docs/reference/DOCUMENTS.md': 'guides/documents.md',
  'docs/integrations/CHANNELS.md': 'guides/channels.md',
  'docs/integrations/BOT_INTEGRATIONS.md': 'guides/bot-integrations.md',
  'docs/guides/CUSTOM_AGENTS.md': 'guides/custom-agents.md',
  'docs/guides/CHAT_CONNECTOR_GUIDE.md': 'guides/chat-connector.md',
  'docs/integrations/CONNECTORS.md': 'guides/connectors.md',
  'docs/connectors/CONNECTOR_CATALOG.md': 'guides/connector-catalog.md',
  'docs/guides/CONNECTORS_SETUP.md': 'guides/connectors-setup.md',
  'docs/guides/CONNECTOR_TROUBLESHOOTING.md': 'guides/connector-troubleshooting.md',
  'docs/integrations/HOOKS.md': 'guides/hooks.md',
  'docs/reference/ACCOUNTING.md': 'guides/accounting.md',
  'docs/debate/EVIDENCE.md': 'guides/evidence.md',
  'docs/api/EVIDENCE_API_GUIDE.md': 'api/evidence.md',
  'docs/debate/GRAPH_DEBATES.md': 'guides/graph-debates.md',
  'docs/debate/MATRIX_DEBATES.md': 'guides/matrix-debates.md',
  'docs/debate/GAUNTLET.md': 'guides/gauntlet.md',
  'docs/architecture/GAUNTLET_ARCHITECTURE.md': 'guides/gauntlet-architecture.md',
  'docs/debate/PROBE_STRATEGIES.md': 'guides/probe-strategies.md',
  'docs/guides/HARNESSES_GUIDE.md': 'guides/harnesses.md',
  'docs/guides/MODES_GUIDE.md': 'guides/modes.md',
  'docs/workflow/MODES_REFERENCE.md': 'guides/modes-reference.md',
  'docs/guides/USER_ONBOARDING.md': 'guides/user-onboarding.md',
  'docs/integrations/AUTOMATION_INTEGRATIONS.md': 'guides/automation.md',
  'docs/integrations/EMAIL_PRIORITIZATION.md': 'guides/email-prioritization.md',
  'docs/guides/SHARED_INBOX.md': 'guides/shared-inbox.md',
  'docs/observability/COST_VISIBILITY.md': 'guides/cost-visibility.md',
  'docs/architecture/CODING_ASSISTANCE.md': 'guides/coding-assistance.md',
  'docs/integrations/BROADCAST.md': 'guides/broadcast.md',
  'docs/resilience/PULSE.md': 'guides/pulse.md',
  'docs/streaming/WEBSOCKET_EVENTS.md': 'guides/websocket-events.md',
  'docs/guides/SDK_TYPESCRIPT.md': 'guides/sdk-typescript.md',
  'docs/guides/SDK_PARITY.md': 'guides/sdk-parity.md',
  'docs/guides/SDK_CONSOLIDATION.md': 'guides/sdk-consolidation.md',
  'docs/reference/LIBRARY_USAGE.md': 'guides/library-usage.md',
  'docs/guides/PLUGIN_GUIDE.md': 'guides/plugin-guide.md',
  'docs/guides/GITHUB_ACTION_SETUP.md': 'guides/github-action-setup.md',
  'docs/guides/github-actions-review.md': 'guides/github-actions-review.md',

  // =========================================================================
  // API Reference
  // =========================================================================
  'docs/api/API_REFERENCE.md': 'api/reference.md',
  'docs/API_ENDPOINTS.md': 'api/endpoints.md',
  'docs/api/API_EXAMPLES.md': 'api/examples.md',
  'docs/api/API_VERSIONING.md': 'api/versioning.md',
  'docs/api/API_RATE_LIMITS.md': 'api/rate-limits.md',
  'docs/api/API_STABILITY.md': 'api/stability.md',
  'docs/api/API_DISCOVERY.md': 'api/discovery.md',
  'docs/api/SUPPORTED_SURFACE.md': 'api/supported-surface.md',
  'docs/reference/CLI_REFERENCE.md': 'api/cli.md',
  'docs/integrations/GITHUB_PR_REVIEW.md': 'api/github-pr-review.md',
  'docs/api/WEBHOOKS.md': 'api/webhooks.md',

  // =========================================================================
  // Deployment
  // =========================================================================
  'docs/DEPLOYMENT.md': 'deployment/overview.md',
  'docs/deployment/SECURITY_DEPLOYMENT.md': 'deployment/security.md',
  'docs/deployment/SCALING.md': 'deployment/scaling.md',
  'docs/deployment/CAPACITY_PLANNING.md': 'deployment/capacity-planning.md',
  'docs/deployment/REDIS_HA.md': 'deployment/redis-ha.md',
  'docs/deployment/KUBERNETES.md': 'deployment/kubernetes.md',
  'docs/deployment/STREAMING_DEPLOYMENT.md': 'deployment/streaming.md',
  'docs/deployment/ASYNC_GATEWAY.md': 'deployment/async-gateway.md',
  'docs/deployment/CONTAINER_VOLUMES.md': 'deployment/container-volumes.md',
  'docs/deployment/PRODUCTION_DEPLOYMENT.md': 'deployment/production-deployment.md',
  'docs/guides/DATABASE_SETUP.md': 'deployment/database-setup.md',
  'docs/reference/DATABASE.md': 'deployment/database.md',
  'docs/reference/DATABASE_SCHEMA.md': 'deployment/database-schema.md',
  'docs/deployment/DISASTER_RECOVERY.md': 'deployment/disaster-recovery.md',
  'docs/deployment/POSTGRES_HA.md': 'deployment/postgres-ha.md',
  'docs/enterprise/RBAC_MATRIX.md': 'deployment/RBAC_MATRIX.md',
  'docs/deployment/DR_DRILL_PROCEDURES.md': 'deployment/dr-drills.md',
  'docs/observability/OBSERVABILITY.md': 'deployment/observability.md',
  'docs/observability/WATCHDOG.md': 'operations/watchdog.md',
  'docs/guides/OBSERVABILITY_SETUP.md': 'deployment/observability-setup.md',
  'docs/guides/MONITORING_SETUP.md': 'guides/monitoring-setup.md',
  'docs/deployment/DEPLOYMENT_DECISION_MATRIX.md': 'deployment/decision-matrix.md',
  'docs/deployment/TLS.md': 'deployment/tls.md',
  'docs/enterprise/SECRETS_MIGRATION.md': 'deployment/secrets-migration.md',

  // =========================================================================
  // Operations / Runbooks
  // =========================================================================
  'docs/runbooks/RUNBOOK_DEPLOYMENT.md': 'operations/runbook-deployment.md',
  'docs/runbooks/RUNBOOK_INCIDENT.md': 'operations/runbook-incident.md',
  'docs/runbooks/RUNBOOK_DATABASE_ISSUES.md': 'operations/runbook-database.md',
  'docs/runbooks/RUNBOOK_PROVIDER_FAILURE.md': 'operations/runbook-provider.md',
  'docs/runbooks/RUNBOOK_BACKUP_AUTOMATION.md': 'operations/runbook-backup-automation.md',
  'docs/runbooks/RUNBOOK_MULTI_REGION_SETUP.md': 'operations/runbook-multi-region-setup.md',
  'docs/runbooks/RUNBOOK_POSTGRESQL_REPLICATION.md': 'operations/runbook-postgresql-replication.md',
  'docs/runbooks/RUNBOOK_POSTGRESQL_MIGRATION.md': 'operations/runbook-postgresql-migration.md',
  'docs/runbooks/redis-failover.md': 'operations/redis-failover.md',
  'docs/runbooks/database-migration.md': 'operations/database-migration.md',
  'docs/runbooks/incident-response.md': 'operations/incident-response-procedures.md',
  'docs/runbooks/scaling.md': 'operations/scaling.md',
  'docs/runbooks/monitoring-setup.md': 'operations/monitoring-setup.md',
  'docs/runbooks/DISASTER_RECOVERY.md': 'operations/disaster-recovery-runbook.md',
  'docs/deployment/ALERT_RUNBOOKS.md': 'operations/alert-runbooks.md',
  'docs/ops/RUNBOOK.md': 'operations/runbook.md',
  'docs/deployment/PRODUCTION_RUNBOOK.md': 'operations/production-runbook.md',
  'docs/deployment/RUNBOOK_METRICS.md': 'operations/runbook-metrics.md',
  'docs/runbooks/INCIDENT_RESPONSE.md': 'operations/incident-response.md',
  'docs/deployment/INCIDENT_RESPONSE_PLAYBOOKS.md': 'operations/incident-response-playbooks.md',
  'docs/deployment/INCIDENT_COMMUNICATION.md': 'operations/incident-communication.md',

  // =========================================================================
  // Enterprise
  // =========================================================================
  'docs/enterprise/GOVERNANCE.md': 'enterprise/governance.md',
  'docs/reference/CONTROL_PLANE.md': 'enterprise/control-plane-overview.md',
  'docs/guides/CONTROL_PLANE_GUIDE.md': 'enterprise/control-plane.md',
  'docs/ENTERPRISE_FEATURES.md': 'enterprise/features.md',
  'docs/enterprise/ENTERPRISE_SUPPORT.md': 'enterprise/support.md',
  'docs/enterprise/DISASTER_RECOVERY.md': 'enterprise/disaster-recovery.md',
  'docs/COMMERCIAL_OVERVIEW.md': 'enterprise/commercial-overview.md',
  'docs/WHY_ARAGORA.md': 'enterprise/why-aragora.md',
  'docs/strategy/PRICING.md': 'enterprise/pricing.md',
  'docs/reference/BILLING.md': 'enterprise/billing.md',
  'docs/reference/BILLING_UNITS.md': 'enterprise/billing-units.md',
  'docs/enterprise/SSO_SETUP.md': 'enterprise/sso.md',
  'docs/guides/STRIPE_SETUP.md': 'enterprise/stripe-setup.md',
  'docs/reference/SLA.md': 'enterprise/sla.md',

  // =========================================================================
  // Security & Compliance
  // =========================================================================
  'docs/enterprise/SECURITY.md': 'security/overview.md',
  'docs/guides/AUTH_GUIDE.md': 'security/authentication.md',
  'docs/enterprise/COMPLIANCE.md': 'enterprise/compliance.md',
  'docs/enterprise/COMPLIANCE_PRESETS.md': 'security/compliance-presets.md',
  'docs/compliance/DATA_CLASSIFICATION.md': 'security/data-classification.md',
  'docs/enterprise/DATA_RESIDENCY.md': 'security/data-residency.md',
  'docs/enterprise/PRIVACY_POLICY.md': 'security/privacy-policy.md',
  'docs/enterprise/BREACH_NOTIFICATION_SLA.md': 'security/breach-notification.md',
  'docs/enterprise/CI_CD_SECURITY.md': 'security/ci-cd.md',
  'docs/enterprise/REMOTE_WORK_SECURITY.md': 'security/remote-work.md',
  'docs/enterprise/DSAR_WORKFLOW.md': 'security/dsar.md',
  'docs/enterprise/SECURITY_RUNTIME.md': 'security/runtime.md',
  'docs/enterprise/SECURITY_PATTERNS.md': 'security/patterns.md',
  'docs/enterprise/OAUTH_GUIDE.md': 'security/oauth-guide.md',
  'docs/enterprise/OAUTH_SETUP.md': 'security/oauth-setup.md',
  'docs/enterprise/SESSION_MANAGEMENT.md': 'security/session-management.md',
  'docs/compliance/EU_AI_ACT_GUIDE.md': 'security/eu-ai-act-guide.md',

  // =========================================================================
  // Admin & Management
  // =========================================================================
  'docs/reference/ADMIN.md': 'admin/overview.md',
  'docs/testing/A_B_TESTING.md': 'admin/ab-testing.md',
  'docs/workflow/NOMIC_LOOP.md': 'admin/nomic-loop.md',

  // =========================================================================
  // Advanced Topics
  // =========================================================================
  'docs/guides/RLM_GUIDE.md': 'advanced/rlm.md',
  'docs/guides/RLM_USER_GUIDE.md': 'advanced/rlm-user.md',
  'docs/guides/RLM_DEVELOPER_GUIDE.md': 'advanced/rlm-developer.md',
  'docs/integrations/INTEGRATION_RLM.md': 'advanced/rlm-integration.md',
  'docs/integrations/CROSS_POLLINATION.md': 'advanced/cross-pollination.md',
  'docs/architecture/CROSS_FUNCTIONAL_FEATURES.md': 'advanced/cross-functional.md',
  'docs/debate/TRICKSTER.md': 'advanced/trickster.md',
  'docs/workflow/FORMAL_VERIFICATION.md': 'advanced/formal-verification.md',
  'docs/resilience/RESILIENCE.md': 'advanced/resilience.md',
  'docs/status/PROPULSION.md': 'advanced/propulsion.md',

  // =========================================================================
  // Analysis & Metrics
  // =========================================================================
  'docs/architecture/ANALYSIS.md': 'analysis/overview.md',
  'docs/architecture/CODEBASE_ANALYSIS.md': 'analysis/codebase.md',
  'docs/testing/BENCHMARK_RESULTS.md': 'analysis/benchmarks.md',
  'docs/case-studies/README.md': 'analysis/case-studies/index.md',
  'docs/case-studies/architecture-stress-test.md': 'analysis/case-studies/architecture-stress-test.md',
  'docs/case-studies/gdpr-compliance-audit.md': 'analysis/case-studies/gdpr-compliance-audit.md',
  'docs/case-studies/epic-strategic-debate.md': 'analysis/case-studies/epic-strategic-debate.md',
  'docs/case-studies/security-api-review.md': 'analysis/case-studies/security-api-review.md',

  // =========================================================================
  // Architecture Decision Records
  // =========================================================================
  'docs/ADR/README.md': 'analysis/adr/index.md',
  'docs/ADR/001-phase-based-debate-execution.md': 'analysis/adr/001-phase-based-debate-execution.md',
  'docs/ADR/002-agent-fallback-openrouter.md': 'analysis/adr/002-agent-fallback-openrouter.md',
  'docs/ADR/003-multi-tier-memory-system.md': 'analysis/adr/003-multi-tier-memory-system.md',
  'docs/ADR/004-incremental-type-safety.md': 'analysis/adr/004-incremental-type-safety.md',
  'docs/ADR/005-composition-over-inheritance.md': 'analysis/adr/005-composition-over-inheritance.md',
  'docs/ADR/006-api-versioning-strategy.md': 'analysis/adr/006-api-versioning-strategy.md',
  'docs/ADR/007-selection-plugin-architecture.md': 'analysis/adr/007-selection-plugin-architecture.md',
  'docs/ADR/008-rlm-semantic-compression.md': 'analysis/adr/008-rlm-semantic-compression.md',
  'docs/ADR/009-control-plane-architecture.md': 'analysis/adr/009-control-plane-architecture.md',
  'docs/ADR/010-debate-orchestration-pattern.md': 'analysis/adr/010-debate-orchestration-pattern.md',
  'docs/ADR/011-multi-tier-memory-comparison.md': 'analysis/adr/011-multi-tier-memory-comparison.md',
  'docs/ADR/012-agent-fallback-strategy.md': 'analysis/adr/012-agent-fallback-strategy.md',
  'docs/ADR/013-workflow-dag-design.md': 'analysis/adr/013-workflow-dag-design.md',
  'docs/ADR/014-knowledge-mound-architecture.md': 'analysis/adr/014-knowledge-mound-architecture.md',
  'docs/ADR/015-lazy-import-patterns.md': 'analysis/adr/015-lazy-import-patterns.md',
  'docs/ADR/016-marketplace-architecture.md': 'analysis/adr/016-marketplace-architecture.md',

  // =========================================================================
  // Contributing
  // =========================================================================
  'docs/guides/CONTRIBUTING.md': 'contributing/guide.md',
  'docs/NEXT_STEPS.md': 'contributing/next-steps.md',
  'docs/guides/FIRST_CONTRIBUTION.md': 'contributing/first-contribution.md',
  'docs/INDEX.md': 'contributing/documentation-index.md',
  'docs/guides/COLD_REVIEWER_GUIDE.md': 'contributing/cold-reviewer-guide.md',
  'docs/guides/INBOX_GUIDE.md': 'contributing/INBOX_GUIDE.md',
  'docs/reference/DEPRECATION_POLICY.md': 'contributing/deprecation.md',
  'docs/STATUS.md': 'contributing/status.md',
  'docs/reference/DEPENDENCIES.md': 'contributing/dependencies.md',
  'docs/debate/FRONTEND_DEVELOPMENT.md': 'contributing/frontend-development.md',
  'docs/guides/FRONTEND_ROUTES.md': 'contributing/frontend-routes.md',
  'docs/debate/HANDLER_DEVELOPMENT.md': 'contributing/handler-development.md',
  'docs/testing/TESTING.md': 'contributing/testing.md',
  'docs/reference/HANDLERS.md': 'contributing/handlers.md',
  'docs/status/FEATURE_DISCOVERY.md': 'contributing/feature-discovery.md',
  'docs/FEATURE_GAP_LIST.md': 'contributing/feature-gap-list.md',
  'docs/status/ACTIVE_EXECUTION_ISSUES.md': 'contributing/active-execution-issues.md',
  'docs/status/ROADMAP_INTAKE_REGISTER.md': 'contributing/roadmap-intake-register.md',
  'docs/status/B0_BENCHMARK_TRUTH_STATUS.md': 'contributing/b0-benchmark-truth-status.md',
  'docs/status/NEXT_STEPS_CANONICAL.md': 'contributing/next-steps-canonical.md',
  'docs/status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md':
    'contributing/execution-next-6-weeks-2026-03-05.md',
  'docs/status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md':
    'contributing/documentation-hygiene-and-gap-register.md',
  'docs/status/PMF_SCORECARD.md': 'contributing/pmf-scorecard.md',
  'docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md':
    'contributing/tw03-rescue-productization-status.md',
  'docs/CANONICAL_GOALS.md': 'contributing/canonical-goals.md',
  'docs/EXTENDED_README.md': 'contributing/extended-readme.md',
  'docs/plans/ARAGORA_EVOLUTION_ROADMAP.md': 'contributing/aragora-evolution-roadmap.md',
  'docs/plans/PMF_DOGFOOD_EXECUTION_PLAN.md': 'contributing/pmf-dogfood-execution-plan.md',
  'docs/plans/2026-03-26-pmf-14-day-execution-plan.md':
    'contributing/2026-03-26-pmf-14-day-execution-plan.md',
  'docs/superpowers/specs/2026-06-26-strategy-as-bounded-mission-cadence-design.md':
    'contributing/strategy-as-bounded-mission-cadence-design.md',
  'docs/superpowers/plans/2026-06-26-mission-cadence-m0-m1.md':
    'contributing/mission-cadence-m0-m1.md',
  'docs/guides/CONDUCTOR_WORKFLOW.md': 'guides/conductor-workflow.md',
  'docs/guides/SWARM_DOGFOOD_OPERATOR.md': 'guides/swarm-dogfood-operator.md',
  'docs/guides/WORKER_PROMPT_PACK.md': 'guides/worker-prompt-pack.md',
  'docs/architecture/DEV_SWARM_COORDINATION.md': 'contributing/dev-swarm-coordination.md',
  'docs/enterprise/SECRETS.md': 'enterprise/secrets.md',
  'docs/plans/2026-03-07-conductor-control-plane.md':
    'contributing/conductor-control-plane-implementation-spec.md',
  'docs/workflow/MARKETPLACE.md': 'guides/marketplace.md',

  // =========================================================================
  // Specifications
  //
  // docs/specs/** design/governance specs. Intra-directory links between these
  // files (e.g. 'TAMPER_EVIDENT_TRAIL.md' from OPEN_DECISION_RECEIPT.md) resolve
  // via the source-relative lookup below, not through this table directly.
  // =========================================================================
  'docs/specs/ADVISORY_REVIEW_RECOGNIZABLE_HEADER.md':
    'specs/advisory-review-recognizable-header.md',
  'docs/specs/ARAGORA_ROADMAP_REVISION_ADVOCATES.md':
    'specs/aragora-roadmap-revision-advocates.md',
  'docs/specs/CHINESE_ROUTED_REVIEWER_FAMILIES_9071.md':
    'specs/chinese-routed-reviewer-families-9071.md',
  'docs/specs/ESSAY_REFINEMENT_PIPELINE.md': 'specs/essay-refinement-pipeline.md',
  'docs/specs/FINDING_SEVERITY_GATE.md': 'specs/finding-severity-gate.md',
  'docs/specs/INDEPENDENT_VERIFIER_GUIDE.md': 'specs/independent-verifier-guide.md',
  'docs/specs/LOCAL_ADVOCATE_TRAINING_PIPELINE.md': 'specs/local-advocate-training-pipeline.md',
  'docs/specs/MODEL_DISSENT_SEVERITY_GATE.md': 'specs/model-dissent-severity-gate.md',
  'docs/specs/MODEL_LINEAGE_DISCLOSURE.md': 'specs/model-lineage-disclosure.md',
  'docs/specs/MODEL_QUORUM_FAMILY_EXPANSION.md': 'specs/model-quorum-family-expansion.md',
  'docs/specs/OPEN_DECISION_RECEIPT.md': 'specs/open-decision-receipt.md',
  'docs/specs/QUORUM_EVIDENCE_RETRIGGER.md': 'specs/quorum-evidence-retrigger.md',
  'docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md': 'specs/receipt-lineage-reconciliation.md',
  'docs/specs/TAMPER_EVIDENT_TRAIL.md': 'specs/tamper-evident-trail.md',
  'docs/specs/TIER4_SETTLEMENT_PROBE_TIMEOUT_REPORTING.md':
    'specs/tier4-settlement-probe-timeout-reporting.md',
  'docs/specs/TIERED_MERGE_GATE_QUORUM_POLICY.md': 'specs/tiered-merge-gate-quorum-policy.md',
  'docs/specs/odr-native-mapping.md': 'specs/odr-native-mapping.md',

  // =========================================================================
  // Reference
  //
  // docs/reference/** technical reference material, mirrored as its own
  // `reference/` category (parallel to Specifications above). Several files
  // in this directory intentionally have no entry here because they already
  // are published by a pre-existing DOC_MAP entry elsewhere -- see
  // ACCOUNTING.md, ADMIN.md, BILLING.md, BILLING_UNITS.md, CONTROL_PLANE.md,
  // DATABASE.md, DATABASE_SCHEMA.md, DEPENDENCIES.md, DEPRECATION_POLICY.md,
  // DOCUMENTS.md, ENVIRONMENT.md, HANDLERS.md, LIBRARY_USAGE.md and SLA.md
  // above, plus reference/CLI_REFERENCE.md under API Reference. Adding a
  // second reference/ entry for those would publish the same content at two
  // docs-site URLs.
  // =========================================================================
  // Hand-written CLI guide; the generated command catalog is api/cli.md.
  'docs/CLI_REFERENCE.md': 'reference/cli-reference.md',
  'docs/reference/BINDINGS.md': 'reference/bindings.md',
  'docs/reference/BREAKING_CHANGES.md': 'reference/breaking-changes.md',
  'docs/reference/CANONICAL_STORES.md': 'reference/canonical-stores.md',
  'docs/reference/CREDITS.md': 'reference/credits.md',
  'docs/reference/ENVIRONMENT_COMPLETE.md': 'reference/environment-complete.md',
  'docs/reference/ERROR_CODES.md': 'reference/error-codes.md',
  'docs/reference/ERROR_HANDLING.md': 'reference/error-handling.md',
  'docs/reference/ERROR_TRACKING.md': 'reference/error-tracking.md',
  'docs/reference/IMPLEMENT.md': 'reference/implement.md',
  // Not reference/index.md: that filename is reserved for the auto-generated
  // category index createIndexFile() writes below, which would otherwise
  // silently overwrite this file's synced content.
  'docs/reference/INDEX.md': 'reference/reference-index.md',
  'docs/reference/INSTALL_MATRIX.md': 'reference/install-matrix.md',
  'docs/reference/ROOT_ALLOWLIST.md': 'reference/root-allowlist.md',
  'docs/reference/TYPE_CHECKING.md': 'reference/type-checking.md',

  // Disagreement Atlas, included by the autogenerated Reference sidebar.
  'docs/atlas/README.md': 'reference/atlas/overview.md',
  'docs/atlas/summary.md': 'reference/atlas/summary.md',

  // =========================================================================
  // Additional Missing Files (commonly referenced)
  // =========================================================================
  // Core
  'docs/guides/TROUBLESHOOTING.md': 'operations/troubleshooting.md',
  'docs/resilience/QUEUE.md': 'guides/queue.md',
  'docs/api/RATE_LIMITING.md': 'deployment/rate-limiting.md',
  'docs/enterprise/SECRETS_MANAGEMENT.md': 'deployment/secrets-management.md',
  'docs/knowledge/MEMORY_ANALYTICS.md': 'core-concepts/memory-analytics.md',

  // API
  'docs/integrations/MCP_INTEGRATION.md': 'guides/mcp-integration.md',
  'docs/integrations/MCP_ADVANCED.md': 'guides/mcp-advanced.md',

  // Operations
  'docs/deployment/PERFORMANCE_TARGETS.md': 'operations/performance-targets.md',
  'docs/deployment/PRODUCTION_READINESS.md': 'operations/production-readiness.md',

  // Advanced
  'docs/workflow/GENESIS.md': 'advanced/genesis.md',
  'docs/workflow/EVOLUTION_PATTERNS.md': 'advanced/evolution-patterns.md',

  // Admin

  // Security

  // Integration / Enterprise
  'docs/status/POSTGRESQL_MIGRATION.md': 'deployment/postgresql-migration.md',

  // Algorithms
  'docs/algorithms/CONVERGENCE.md': 'core-concepts/convergence-algorithm.md',
  'docs/algorithms/ELO_CALIBRATION.md': 'core-concepts/elo-calibration.md',

  // Documents
  'docs/status/FEATURES.md': 'guides/features.md',
  'docs/status/VERTICALS.md': 'guides/verticals.md',
  'docs/operations/OPERATIONS.md': 'operations/overview.md',
};

// Repository files outside docs/ that are published as pages (repo-relative source -> destination).
// Pages under docs/ link to them as '../CLAUDE.md' and '../ROADMAP.md'.
const REPO_SOURCE_MAP = {
  'CLAUDE.md': 'contributing/claude.md',
  'ROADMAP.md': 'contributing/roadmap.md',
};

// Repository files outside docs/ that are link targets only: REPO_MARKDOWN_LINKS rewrites links to
// them, and they are never published as pages of their own.
const REPO_SOURCE_LINK_ONLY = [
  'aragora/gauntlet/README.md',
];

// Files in docs/*.md and the curated docs/ directories that stay off the site. Each of those files
// is either a DOC_MAP key or listed here with the reason it is not published.
const DOCSITE_EXCLUDE = {
  'docs/AGENT_ASSIGNMENTS.md': 'agent and maintainer process for this repository',
  'docs/AGENT_FLYWHEEL_ARAGORA_NATIVE.md': 'architecture design record or plan for maintainers',
  'docs/AGENT_OPERATING_CONTRACT.md': 'agent and maintainer process for this repository',
  'docs/BREAKING_CHANGES.md': 'v3.0 planning; docs/reference/BREAKING_CHANGES.md is published',
  'docs/CAPABILITY_MATRIX.md':
    'generated; scripts/generate_capability_matrix.py writes contributing/capability-matrix.md',
  'docs/CI_LANES.md': 'agent and maintainer process for this repository',
  'docs/COORDINATION.md': 'agent and maintainer process for this repository',
  'docs/EU_AI_ACT_COMPLIANCE.md': 'overlaps the published docs/compliance/EU_AI_ACT_GUIDE.md',
  'docs/FEATURE_DISCOVERY.md': 'redirect stub; docs/status/FEATURE_DISCOVERY.md is published',
  'docs/GA_CHECKLIST.md': 'release readiness checklist for maintainers',
  'docs/LANDING_PAGE.md': 'marketing landing page copy',
  'docs/METRICS.md': 'generated counts; linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/PACKAGING.md': 'linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/RECEIPT_CONTRACT.md': 'linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/REVIEW_AUTHORITY_PRINCIPLES.md': 'repository governance record',
  'docs/SDK_COMPARISON.md': 'not yet reviewed for the public docs site',
  'docs/SDK_QUICKSTART_PYTHON.md': 'linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/START_HERE.md': 'repository navigation index; the site has its own sidebar',
  'docs/THESIS.md': 'internal strategy and positioning material',
  'docs/architecture/ARCHITECTURE_REVIEW_RESPONSE.md': 'architecture design record or plan for maintainers',
  'docs/architecture/ARCHITECTURE_THREE_LAYER.md': 'architecture design record or plan for maintainers',
  'docs/architecture/BUILD_VS_INTEGRATE.md': 'architecture design record or plan for maintainers',
  'docs/architecture/BUILD_VS_INTEGRATE_DECISION.md': 'architecture design record or plan for maintainers',
  'docs/architecture/CHARTER_COMPLIANCE_CHECKER.md': 'architecture design record or plan for maintainers',
  'docs/architecture/CLOSED_LOOP_BACKBONE.md': 'architecture design record or plan for maintainers',
  'docs/architecture/EXTENSION_CONTRACTS.md': 'architecture design record or plan for maintainers',
  'docs/architecture/GATEWAY_ARCHITECTURE.md': 'not yet reviewed for the public docs site',
  'docs/architecture/HANDLER_PATTERNS.md': 'architecture design record or plan for maintainers',
  'docs/architecture/IMPORT_LAYERS.md': 'architecture design record or plan for maintainers',
  'docs/architecture/INTENDED_ARCHITECTURE.md': 'linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/architecture/MODEL_CATALOG.md': 'architecture design record or plan for maintainers',
  'docs/architecture/MODULE_QUARANTINE_PROPOSAL.md': 'architecture design record or plan for maintainers',
  'docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md': 'architecture design record or plan for maintainers',
  'docs/architecture/P4A_LAYERING_DISPOSITION.md': 'architecture design record or plan for maintainers',
  'docs/architecture/P4B_HANDLERS_DECOMPOSITION.md': 'architecture design record or plan for maintainers',
  'docs/architecture/P5_CLI_PARSER_SPLIT_DESIGN.md': 'architecture design record or plan for maintainers',
  'docs/architecture/P5_REVIEW_QUEUE_SPLIT_DESIGN.md': 'architecture design record or plan for maintainers',
  'docs/architecture/PACKAGING_AND_DISTRIBUTION.md': 'linked on GitHub through REPO_MARKDOWN_LINKS',
  'docs/architecture/QUEUE_ADOPTION_DISPOSITION.md': 'architecture design record or plan for maintainers',
  'docs/architecture/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/architecture/SOC2_GAP_ANALYSIS.md': 'internal compliance gap analysis',
  'docs/architecture/SYSTEM_DIAGRAM.md': 'not yet reviewed for the public docs site',
  'docs/architecture/TEST_PLAN_CRITICAL_MODULES.md': 'architecture design record or plan for maintainers',
  'docs/architecture/TRUST_PORTABILITY.md': 'architecture design record or plan for maintainers',
  'docs/architecture/canonical-apis.md': 'architecture design record or plan for maintainers',
  'docs/architecture/debate-flow.md': 'not yet reviewed for the public docs site',
  'docs/architecture/defaults-drift-audit.md': 'architecture design record or plan for maintainers',
  'docs/architecture/memory-tiers.md': 'not yet reviewed for the public docs site',
  'docs/architecture/metrics-refactoring-plan.md': 'architecture design record or plan for maintainers',
  'docs/architecture/n+1-query-audit.md': 'architecture design record or plan for maintainers',
  'docs/architecture/nomic-context-builder-plan.md': 'architecture design record or plan for maintainers',
  'docs/architecture/nomic-loop.md': 'not yet reviewed for the public docs site',
  'docs/architecture/nomic-true-test-plan.md': 'architecture design record or plan for maintainers',
  'docs/architecture/nomic-true-test-spec.md': 'architecture design record or plan for maintainers',
  'docs/architecture/primitive-consolidation.md': 'architecture design record or plan for maintainers',
  'docs/architecture/shims.md': 'architecture design record or plan for maintainers',
  'docs/architecture/system-overview.md': 'not yet reviewed for the public docs site',
  'docs/getting-started/LOCAL_DEVELOPMENT.md': 'not yet reviewed for the public docs site',
  'docs/getting-started/SME_QUICKSTART.md': 'redirect stub to the published quickstart',
  'docs/getting-started/ZERO_CONFIG.md': 'not yet reviewed for the public docs site',
  'docs/governance/ADC_v0.1-v0.4_STACK_AUDIT.md': 'repository governance record',
  'docs/governance/AGENT_DISPATCH_REACH_PLAN.md': 'repository governance record',
  'docs/governance/BOSS_LOOP_MERGE_GATE_PHASE3_DESIGN.md': 'repository governance record',
  'docs/governance/BOUNDED_OPERATOR_DELEGATION_PROPOSAL.md': 'repository governance record',
  'docs/governance/DELEGATION_CONTRACT_V0_1_SPEC.md': 'repository governance record',
  'docs/governance/LOOP_CONTROL_PLANE.md': 'repository governance record',
  'docs/governance/MERGE_GATE_CARRY_FORWARD_THREAT_MODEL.md': 'repository governance record',
  'docs/governance/MERGE_GATE_RECONCILIATION.md': 'repository governance record',
  'docs/governance/MODULE_TIER_DRIFT_GUARDIAN.md': 'repository governance record',
  'docs/governance/OPERATOR_DELEGATION_POLICY.md': 'repository governance record',
  'docs/governance/OPERATOR_GRANT_VERIFICATION.md': 'repository governance record',
  'docs/governance/PR9320_SUCCESSOR_BACKFILL_RUNBOOK.md': 'repository governance record',
  'docs/governance/PR_RUN_CANCELLATION_DIAGNOSIS.md': 'repository governance record',
  'docs/governance/QUORUM_EVIDENCE_RUNBOOK.md': 'repository governance record',
  'docs/governance/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/governance/TIERED_MERGE_GATE_ENABLEMENT.md': 'repository governance record',
  'docs/governance/ci-main-guardrails.md': 'repository governance record',
  'docs/governance/deprecation-candidates.md': 'repository governance record',
  'docs/governance/duplicate-subsystem-resolution.md': 'repository governance record',
  'docs/governance/gmail-failures-history-decision.md': 'repository governance record',
  'docs/governance/phase1-scope-boundaries.md': 'repository governance record',
  'docs/governance/receipt-enforcement.md': 'repository governance record',
  'docs/governance/records/20260716T2200Z-gemini-reviewer-reliability-record.md': 'repository governance record',
  'docs/governance/subsystem-ledger.md': 'repository governance record',
  'docs/governance/test-taxonomy.md': 'repository governance record',
  'docs/guides/ADAPTER_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/ADAPTER_INTEGRATION_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/API_COOKBOOK.md': 'not yet reviewed for the public docs site',
  'docs/guides/BETA_REVIEW_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/CAMPAIGN_OPERATOR.md': 'not yet reviewed for the public docs site',
  'docs/guides/CLAUDE_CAPACITY_INVENTORY.md': 'agent and maintainer process for this repository',
  'docs/guides/CLAUDE_MAX_POOL.md': 'agent and maintainer process for this repository',
  'docs/guides/CLI_SETUP_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/CODEX_WORKTREE_AUTOPILOT.md': 'agent and maintainer process for this repository',
  'docs/guides/COMPUTER_USE_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/COORDINATION_SYSTEM.md': 'not yet reviewed for the public docs site',
  'docs/guides/DEVELOPER_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/DEVELOPER_QUICKSTART.md': 'redirect stub to the published quickstart',
  'docs/guides/ERROR_HANDLING.md': 'not yet reviewed for the public docs site',
  'docs/guides/FABRIC_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/FINE_TUNING_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/GATEWAY_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/GITHUB_APP_SETUP.md': 'not yet reviewed for the public docs site',
  'docs/guides/ISSUE_TRIAGE.md': 'agent and maintainer process for this repository',
  'docs/guides/LANE_DISPATCH.md': 'agent and maintainer process for this repository',
  'docs/guides/LOCAL_DEVELOPMENT.md': 'not yet reviewed for the public docs site',
  'docs/guides/MIGRATION_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/ML_INTEGRATION_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/NOMIC_LOOP_TROUBLESHOOTING.md': 'not yet reviewed for the public docs site',
  'docs/guides/ONBOARDING_FLOW.md': 'not yet reviewed for the public docs site',
  'docs/guides/OPERATOR_QUESTIONS.md': 'agent and maintainer process for this repository',
  'docs/guides/PIPELINE_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/PYTHON_SDK_CONSOLIDATION.md': 'short note; docs/guides/SDK_CONSOLIDATION.md is published',
  'docs/guides/QUICKSTART.md': 'redirect stub to the published quickstart',
  'docs/guides/QUICKSTART_DOCKER.md': 'redirect stub to the published quickstart',
  'docs/guides/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/guides/RESILIENCE_PATTERNS_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/RLM_INTEGRATION.md': 'not yet reviewed for the public docs site',
  'docs/guides/SDK_COMPARISON.md': 'not yet reviewed for the public docs site',
  'docs/guides/SDK_HANDLER_PARITY.md': 'generated parity report for maintainers',
  'docs/guides/SDK_QUICKSTART_PYTHON.md': 'not yet reviewed for the public docs site',
  'docs/guides/SDK_QUICKSTART_TYPESCRIPT.md': 'not yet reviewed for the public docs site',
  'docs/guides/SDK_ROADMAP.md': 'completed SDK parity plan for maintainers',
  'docs/guides/SELF_HOSTED_COMPLETE_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/SELF_HOSTED_QUICKSTART.md': 'not yet reviewed for the public docs site',
  'docs/guides/SMB_QUICK_START.md': 'not yet reviewed for the public docs site',
  'docs/guides/SME_GA_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/SME_ONBOARDING.md': 'not yet reviewed for the public docs site',
  'docs/guides/SME_QUICKSTART.md': 'redirect stub to the published quickstart',
  'docs/guides/SME_STARTER_PACK.md': 'product scope definition for maintainers',
  'docs/guides/STRANGER_TEST.md': 'agent and maintainer process for this repository',
  'docs/guides/SUPABASE_SETUP.md': 'setup checklist for the hosted aragora.ai deployment',
  'docs/guides/USE_CASES.md': 'not yet reviewed for the public docs site',
  'docs/guides/V1_TO_V2_MIGRATION.md': 'not yet reviewed for the public docs site',
  'docs/guides/VIBEPROXY.md': 'agent and maintainer process for this repository',
  'docs/guides/WORKSPACE_GUIDE.md': 'not yet reviewed for the public docs site',
  'docs/guides/apple-oauth-setup.md': 'not yet reviewed for the public docs site',
  'docs/guides/python-quickstart.md': 'not yet reviewed for the public docs site',
  'docs/guides/sdk-parity.md': 'not yet reviewed for the public docs site',
  'docs/guides/typescript-quickstart.md': 'not yet reviewed for the public docs site',
  'docs/operations/PRODUCTION_RUNBOOK.md': 'overlaps the published docs/deployment/PRODUCTION_RUNBOOK.md',
  'docs/operations/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/operations/REVERSE_PROXY.md': 'not yet reviewed for the public docs site',
  'docs/operations/SELF_HOSTED_RUNNER_DOCKER.md': 'CI runner provisioning for this repository',
  'docs/operations/SELF_HOSTING.md': 'not yet reviewed for the public docs site',
  'docs/operations/agent_bridge_first_real_run.md': 'agent and maintainer process for this repository',
  'docs/operations/round-discipline.md': 'agent and maintainer process for this repository',
  'docs/reference/PRICING_TIERS.md': 'withheld publication: internal pricing',
  'docs/strategy/2026-07-05-durable-strategy-capture.md': 'internal strategy and positioning material',
  'docs/strategy/BOUNDARIES_AND_SCOPE.md': 'internal strategy and positioning material',
  'docs/strategy/COMPARISON_MATRIX.md': 'internal strategy and positioning material',
  'docs/strategy/COMPETITIVE_INBOX_TRIAGE_LANDSCAPE.md': 'internal strategy and positioning material',
  'docs/strategy/FOCUS.md': 'internal strategy and positioning material',
  'docs/strategy/HONEST_ASSESSMENT.md': 'internal strategy and positioning material',
  'docs/strategy/INBOX_TRIAGE_INSTRUMENTATION_PLAN.md': 'internal strategy and positioning material',
  'docs/strategy/LEARNING_AND_KNOWLEDGE_MOUND.md': 'internal strategy and positioning material',
  'docs/strategy/MARKET_TIMING_AND_EXPANSION.md': 'internal strategy and positioning material',
  'docs/strategy/OPERATOR_ACTION_PROMPTS.md': 'internal strategy and positioning material',
  'docs/strategy/POSITIONING_AND_MESSAGING.md': 'internal strategy and positioning material',
  'docs/strategy/PRECISION_AND_TERMS.md': 'internal strategy and positioning material',
  'docs/strategy/PROOF_AND_EVIDENCE.md': 'internal strategy and positioning material',
  'docs/strategy/README.md': 'repository navigation index; the site has its own sidebar',
  'docs/strategy/RECEIPTS_DISSENT_EVIDENCE_NARRATIVE_2026_03.md': 'internal strategy and positioning material',
  'docs/strategy/ROADMAP_30_60_90.md': 'internal strategy and positioning material',
  'docs/strategy/STRATEGY_INDEX.md': 'internal strategy and positioning material',
  'docs/strategy/WHY_ADVERSARIAL_DEBATE.md': 'internal strategy and positioning material',
};

// Pages under docs-site/docs/ that no DOC_MAP source writes, and that a DOC_MAP destination
// must not overwrite. All are edited by hand except contributing/capability-matrix.md, which
// scripts/generate_capability_matrix.py renders from the capability YAML. Category index pages
// come from createIndexFile() instead.
const DOCSITE_HAND_MAINTAINED = [
  'api-reference/agents/list.md',
  'api-reference/agents/overview.md',
  'api-reference/agents/stats.md',
  'api-reference/debates/consensus.md',
  'api-reference/debates/create.md',
  'api-reference/debates/get.md',
  'api-reference/debates/list.md',
  'api-reference/debates/overview.md',
  'api-reference/knowledge/overview.md',
  'api-reference/knowledge/query.md',
  'api-reference/knowledge/store.md',
  'api-reference/workflows/execute.md',
  'api-reference/workflows/overview.md',
  'contributing/DOCUMENTATION_HUB.md',
  'contributing/capability-matrix.md',
  'contributing/documentation-map.md',
  'core-concepts/agent-catalog.md',
  'deployment/database-consolidation.md',
  'deployment/redis.md',
  'deployment/runbook.md',
  'enterprise/audit-logs.md',
  'enterprise/control-plane-feasibility.md',
  'enterprise/incident-response.md',
  'enterprise/multi-tenancy.md',
  'enterprise/positioning.md',
  'getting-started/first-debate.md',
  'getting-started/installation.md',
  'getting-started/introduction.md',
  'guides/inbox-guide.md',
  'security/compliance.md',
];

// Add frontmatter to markdown files
function addFrontmatter(content, title, description, slug) {
  // Check if already has frontmatter
  if (content.startsWith('---')) {
    return content;
  }

  // Escape title for YAML (quote if contains special chars)
  const escapeYaml = (str) => {
    if (str.includes(':') || str.includes('#') || str.includes("'") || str.includes('"') || str.includes('\n')) {
      // Double-quote and escape internal double quotes
      return `"${str.replace(/"/g, '\\"')}"`;
    }
    return str;
  };

  const safeTitle = escapeYaml(title);
  const safeDesc = escapeYaml(description || title);

  const slugLine = slug ? `slug: ${slug}\n` : '';
  const frontmatter = `---
${slugLine}title: ${safeTitle}
description: ${safeDesc}
---

`;

  return frontmatter + content;
}

// Extract title from markdown
function extractTitle(content) {
  const match = content.match(/^#\s+(.+)$/m);
  return match ? match[1].replace(/[`*_]/g, '') : 'Documentation';
}

function escapeUrlParamBracesOutsideCodeFences(content) {
  let fenceDepth = 0;
  let inBraceList = false;
  return content
    .split('\n')
    .map(line => {
      if (/^\s*```/.test(line)) {
        if (fenceDepth === 0) {
          fenceDepth = 1;
        } else if (/^\s*```\S+/.test(line)) {
          fenceDepth += 1;
        } else {
          fenceDepth = Math.max(0, fenceDepth - 1);
        }
        return line;
      }
      if (fenceDepth > 0) {
        return line;
      }

      let escaped = '';
      let inInlineCode = false;
      for (let index = 0; index < line.length; index += 1) {
        const char = line[index];
        if (char === '`') {
          inInlineCode = !inInlineCode;
          escaped += char;
          continue;
        }
        const rest = line.slice(index + 1);
        const urlParam = rest.match(/^([\w-]+)\}/);
        if (char === '{' && urlParam) {
          escaped += `\\{${urlParam[1]}\\}`;
          index += urlParam[1].length + 1;
          continue;
        }
        if (inInlineCode) {
          escaped += char;
          continue;
        }
        if (inBraceList) {
          if (char === '}') {
            escaped += '\\}';
            inBraceList = false;
          } else {
            escaped += char;
          }
          continue;
        }
        if (char !== '{') {
          escaped += char;
          continue;
        }

        if (rest.includes(',')) {
          escaped += '\\{';
          inBraceList = true;
          continue;
        }
        escaped += char;
      }
      return escaped;
    })
    .join('\n');
}

// Build reverse lookup from source file to destination path.
//
// REVERSE_LOOKUP is keyed by the full (qualified) source path -- e.g.
// "deployment/DISASTER_RECOVERY.md", "runbooks/DISASTER_RECOVERY.md" -- which is
// always unambiguous because DOC_MAP keys are themselves unique.
//
// BASENAME_LOOKUP is a secondary, basename-only index (e.g. "DISASTER_RECOVERY.md")
// used as a last-resort fallback when a link can't be resolved relative to its own
// source directory either (see sourceRelativeLinkTarget below). Several DOC_MAP
// entries legitimately share a basename (deployment/, runbooks/, and enterprise/
// each have their own DISASTER_RECOVERY.md; similarly README.md), so a basename-
// only key is only safe to use when it maps to exactly one DOC_MAP entry --
// populating it unconditionally would let whichever entry is defined last silently
// win over the others for every ambiguous basename. Ambiguous basenames are
// intentionally left out of BASENAME_LOOKUP so callers fall through to "no match"
// instead of guessing.
const REVERSE_LOOKUP = {};
const BASENAME_LOOKUP = {};
const REPO_BLOB_BASE = 'https://github.com/synaptent/aragora/blob/main';
const REPO_MARKDOWN_LINKS = {
  '../README.md': `${REPO_BLOB_BASE}/README.md`,
  'README.md': `${REPO_BLOB_BASE}/docs/README.md`,
  // METRICS.md is auto-regenerated and not published to docs-site; repo-relative
  // links from any docs/ page must resolve to the canonical repo copy.
  'METRICS.md': `${REPO_BLOB_BASE}/docs/METRICS.md`,
  '../aragora/mcp/README.md': `${REPO_BLOB_BASE}/aragora/mcp/README.md`,
  'algorithms/README.md': `${REPO_BLOB_BASE}/docs/algorithms/README.md`,
  '../deploy/README.md': `${REPO_BLOB_BASE}/deploy/README.md`,
  '../aragora/gauntlet/README.md': 'guides/gauntlet.md',
  '../aragora-verify/README.md': `${REPO_BLOB_BASE}/aragora-verify/README.md`,
  // RECEIPT_CONTRACT.md is operator-gated (canonical receipt-lineage statement) --
  // point off-site rather than adding a DOC_MAP mirror entry for it.
  'RECEIPT_CONTRACT.md': `${REPO_BLOB_BASE}/docs/RECEIPT_CONTRACT.md`,
  // Neither is in DOC_MAP (charters.yaml isn't even markdown), so ARCHITECTURE.md's
  // bare links to its siblings would otherwise survive unrewritten and 404.
  'architecture/INTENDED_ARCHITECTURE.md':
    `${REPO_BLOB_BASE}/docs/architecture/INTENDED_ARCHITECTURE.md`,
  'architecture/charters.yaml': `${REPO_BLOB_BASE}/docs/architecture/charters.yaml`,
  // reference/INSTALL_MATRIX.md links to these files; none are in DOC_MAP
  // (two are outside docs/ entirely), so its links to them would otherwise
  // survive unrewritten and 404.
  'architecture/PACKAGING_AND_DISTRIBUTION.md':
    `${REPO_BLOB_BASE}/docs/architecture/PACKAGING_AND_DISTRIBUTION.md`,
  'PACKAGING.md': `${REPO_BLOB_BASE}/docs/PACKAGING.md`,
  'SDK_QUICKSTART_PYTHON.md': `${REPO_BLOB_BASE}/docs/SDK_QUICKSTART_PYTHON.md`,
  '../DEVELOPMENT.md': `${REPO_BLOB_BASE}/DEVELOPMENT.md`,
  '../INSTALL.md': `${REPO_BLOB_BASE}/INSTALL.md`,
  // reference/INDEX.md links to these two; neither is in DOC_MAP, so its
  // links to them would otherwise survive unrewritten and 404.
  'CAPABILITY_MATRIX.md': `${REPO_BLOB_BASE}/docs/CAPABILITY_MATRIX.md`,
  'debate/EXECUTION_SAFETY_GATE.md': `${REPO_BLOB_BASE}/docs/debate/EXECUTION_SAFETY_GATE.md`,
  // reference/BREAKING_CHANGES.md links to these four; none are in DOC_MAP
  // (the migrations/ target is under docs/deprecated/, deliberately outside
  // the mirror), so its links to them would otherwise survive unrewritten
  // and 404.
  'status/MIGRATION_V1_TO_V2.md': `${REPO_BLOB_BASE}/docs/status/MIGRATION_V1_TO_V2.md`,
  'deprecated/migrations/MIGRATION_0.8_to_1.0.md':
    `${REPO_BLOB_BASE}/docs/deprecated/migrations/MIGRATION_0.8_to_1.0.md`,
  'templates/breaking_change_template.md':
    `${REPO_BLOB_BASE}/docs/templates/breaking_change_template.md`,
  'deployment/RELEASE_NOTES.md': `${REPO_BLOB_BASE}/docs/deployment/RELEASE_NOTES.md`,
  '../CHANGELOG.md': `${REPO_BLOB_BASE}/CHANGELOG.md`,
  // reference/ERROR_HANDLING.md links to this; not in DOC_MAP, so its link
  // would otherwise survive unrewritten and 404.
  'resilience/RESILIENCE_PATTERNS.md': `${REPO_BLOB_BASE}/docs/resilience/RESILIENCE_PATTERNS.md`,
  // Atlas supporting artifacts stay in the repository rather than the mirror.
  'artifacts/2026-07-reviewer-failure-taxonomy.md':
    `${REPO_BLOB_BASE}/docs/artifacts/2026-07-reviewer-failure-taxonomy.md`,
  'atlas/manifest.json': `${REPO_BLOB_BASE}/docs/atlas/manifest.json`,
  '../LICENSE': `${REPO_BLOB_BASE}/LICENSE`,
};
const SOURCE_SPECIFIC_REPO_MARKDOWN_LINKS = {
  'guides/SDK_CONSOLIDATION.md|README.md': `${REPO_BLOB_BASE}/sdk/typescript/README.md`,
};
const PUBLIC_DOC_CONTENT_OVERRIDES = {
  'deployment/DISASTER_RECOVERY.md': [
    '# Deployment Disaster Recovery Overview',
    '',
    'Aragora deployment documentation includes disaster recovery planning for',
    'backup verification, service restoration, failover readiness, and customer',
    'communication during major incidents.',
    '',
    'Detailed infrastructure topology, cloud-provider commands, bucket names,',
    'hostnames, and operational response sequences are restricted to authorized',
    'operators and enterprise support channels.',
    '',
    '## Public Control Summary',
    '',
    '- Deployment recovery procedures are defined for production environments.',
    '- Backup and restore paths are validated on a recurring schedule.',
    '- Failover readiness is reviewed as part of operational preparedness.',
    '- Provider-specific execution details are not published in the public docs.',
    '',
    '## Related Documentation',
    '',
    '- [Operations disaster recovery overview](../operations/disaster-recovery-runbook)',
    '- [Enterprise disaster recovery overview](../enterprise/disaster-recovery)',
    '- [Production readiness](../operations/production-readiness)',
    '',
  ].join('\n'),
  'runbooks/DISASTER_RECOVERY.md': [
    '# Operations Disaster Recovery Runbook Overview',
    '',
    'Aragora maintains operational disaster recovery runbooks for incident',
    'classification, backup validation, restoration sequencing, failover',
    'coordination, and post-incident review.',
    '',
    'Detailed commands, environment names, provider-specific identifiers,',
    'internal dashboards, and escalation paths are restricted to authorized',
    'operators and enterprise support channels.',
    '',
    '## Public Control Summary',
    '',
    '- Incident roles and escalation paths are defined internally.',
    '- Recovery actions are practiced through tabletop and restore exercises.',
    '- Customer communication procedures are maintained for major incidents.',
    '- Operational execution details are withheld from public documentation.',
    '',
    '## Related Documentation',
    '',
    '- [Deployment disaster recovery overview](../deployment/disaster-recovery)',
    '- [Enterprise disaster recovery overview](../enterprise/disaster-recovery)',
    '- [Incident response](./incident-response)',
    '',
  ].join('\n'),
  'enterprise/DISASTER_RECOVERY.md': [
    '# Enterprise Disaster Recovery Overview',
    '',
    'Aragora maintains disaster recovery procedures for enterprise deployments,',
    'including defined recovery objectives, backup verification, regional',
    'failover planning, customer communication, and periodic tabletop review.',
    '',
    'Detailed operational runbooks, infrastructure diagrams, command sequences,',
    'hostnames, escalation rosters, and other internal response procedures are',
    'available only through authorized enterprise support channels.',
    '',
    '## Recovery Objectives',
    '',
    'Recovery objectives are defined contractually per enterprise deployment',
    'and reviewed during disaster recovery planning and validation.',
    '',
    '## Public Control Summary',
    '',
    '- Recovery objectives are defined and reviewed for enterprise deployments.',
    '- Backup and restore procedures are exercised on a recurring schedule.',
    '- Regional failover and customer communication procedures are maintained.',
    '- Operational response details are restricted to authorized recipients.',
    '',
    '## Related Documentation',
    '',
    '- [Operations disaster recovery runbook](../operations/disaster-recovery-runbook)',
    '- [Security overview](../security/overview)',
    '- [Data residency](../security/data-residency)',
    '',
  ].join('\n'),
};
// Every published page as { src (repo-relative), rel (relative to docs/), dest }. Links inside
// docs/ are written relative to docs/, so the lookups use `rel` (CLAUDE.md -> ../CLAUDE.md).
const PUBLISHED_SOURCES = [
  ...Object.entries(DOC_MAP),
  ...Object.entries(REPO_SOURCE_MAP),
].map(([src, dest]) => ({
  src,
  rel: path.relative(SOURCE_DIR, path.join(REPO_ROOT, src)).replace(/\\/g, '/'),
  dest,
}));
const PUBLISHED_PAGES = new Set(PUBLISHED_SOURCES.map(({ dest }) => dest.replace(/\.md$/, '')));
const basenameCounts = new Map();
for (const { rel } of PUBLISHED_SOURCES) {
  const srcName = path.basename(rel);
  basenameCounts.set(srcName, (basenameCounts.get(srcName) || 0) + 1);
}
for (const { rel, dest } of PUBLISHED_SOURCES) {
  const srcName = path.basename(rel);

  // Store both with and without .md extension
  REVERSE_LOOKUP[rel] = dest;
  REVERSE_LOOKUP[rel.replace('.md', '')] = dest.replace('.md', '');

  if (basenameCounts.get(srcName) === 1) {
    BASENAME_LOOKUP[srcName] = dest;
    BASENAME_LOOKUP[srcName.replace('.md', '')] = dest.replace('.md', '');
  }
}

// Resolve a link target relative to the directory of the file that contains it,
// e.g. "./DISASTER_RECOVERY.md" written inside deployment/CONTAINER_VOLUMES.md
// means deployment/DISASTER_RECOVERY.md -- not whichever DOC_MAP entry sharing
// that basename happens to be defined last. Checking this first lets a bare
// filename resolve unambiguously whenever the target is a real sibling (or
// reachable via "../") of the linking source, before falling back to the basename
// guess below.
function sourceRelativeLinkTarget(rawTarget, relSrcPath) {
  const sourceDir = path.posix.dirname(relSrcPath.replace(/\\/g, '/'));
  return path.posix.normalize(path.posix.join(sourceDir, rawTarget));
}

function resolveLinkDestination(normalized, relSrcPath, rawTarget) {
  if (relSrcPath && rawTarget) {
    const sourceTarget = sourceRelativeLinkTarget(rawTarget, relSrcPath);
    const sourceResolved = REVERSE_LOOKUP[sourceTarget];
    if (sourceResolved) {
      return sourceResolved;
    }
    const sourceSpecificKey = `${relSrcPath.replace(/\\/g, '/')}|${sourceTarget}`;
    if (SOURCE_SPECIFIC_REPO_MARKDOWN_LINKS[sourceSpecificKey]) {
      return SOURCE_SPECIFIC_REPO_MARKDOWN_LINKS[sourceSpecificKey];
    }
    if (REPO_MARKDOWN_LINKS[sourceTarget]) {
      return REPO_MARKDOWN_LINKS[sourceTarget];
    }
  }
  // BASENAME_LOOKUP only contains basenames proven unique across DOC_MAP.
  // Ambiguous names are intentionally absent so this fallback fails closed
  // instead of guessing which same-named DOC_MAP entry the link meant.
  return (
    REVERSE_LOOKUP[normalized] ||
    REPO_MARKDOWN_LINKS[normalized] ||
    BASENAME_LOOKUP[path.basename(normalized)]
  );
}

function rewriteLinkTarget(newPath, currentDir, anchor) {
  if (/^https?:\/\//.test(newPath)) {
    return `](${newPath}${anchor || ''})`;
  }

  const targetDir = path.dirname(newPath);
  const targetFile = path.basename(newPath, '.md');
  const isIndex = targetFile === 'index';

  // If same directory, use ./ or filename
  if (targetDir === currentDir) {
    return isIndex ? `](./${anchor || ''})` : `](./${targetFile}${anchor || ''})`;
  }

  // Calculate relative path
  const relativePath = path.relative(currentDir, targetDir);
  const relativeLink = isIndex
    ? relativePath
    : `${relativePath ? `${relativePath}/` : ''}${targetFile}`;
  return `](${relativeLink}${anchor || ''})`;
}

// Fix content for Docusaurus compatibility
function fixContent(content, destPath, relSrcPath) {
  // Fix escaped backticks (common in generated docs)
  content = content.replace(/\\`\\`\\`/g, '```');
  content = content.replace(/\\`([^`\\]+)\\`/g, '`$1`');
  content = content.replace(/[ \t]+$/gm, '');

  // Escape curly braces in URL patterns (e.g., {id} -> \{id\})
  // Only escape braces that look like URL params (word chars inside)
  content = escapeUrlParamBracesOutsideCodeFences(content);

  // Escape angle brackets in comparisons (e.g., <0.3 -> &lt;0.3)
  content = content.replace(/<(\d)/g, '&lt;$1');

  // Get the current doc's directory for relative path calculation
  const currentDir = path.dirname(destPath);

  // Transform internal doc links to Docusaurus paths
  // Match links like [text](./FILE.md), [text](../FILE.md), [text](FILE.md)
  content = content.replace(
    /\]\(((?:\.\.\/|\.\/)?)([A-Za-z0-9_./-]+\.md)(#[^)]+)?\)/g,
    (match, prefix, filePath, anchor) => {
      // Try to find the destination path in our mapping
      const normalized = filePath.replace(/^\.\.\//, '').replace(/^\.\//, '');
      const newPath = resolveLinkDestination(normalized, relSrcPath, `${prefix}${filePath}`);

      if (newPath) {
        return rewriteLinkTarget(newPath, currentDir, anchor);
      }

      // If not found, keep original but log it
      return match;
    }
  );

  // Also fix links without .md extension when they match known docs
  content = content.replace(
    /\]\(((?:\.\.\/|\.\/)?)([A-Za-z0-9_./-]+)(#[^)]+)?\)(?!\.md)/g,
    (match, prefix, filePath, anchor) => {
      const rawTarget = `${prefix}${filePath}`;
      // Links rewritten by the pass above already name a published page; resolving their
      // slug again by basename would send e.g. operations/incident-response to the page of
      // runbooks/incident-response.md.
      if (PUBLISHED_PAGES.has(path.posix.normalize(path.posix.join(currentDir, rawTarget)))) {
        return match;
      }
      const normalized = filePath.replace(/^\.\.\//, '').replace(/^\.\//, '');
      const newPath =
        resolveLinkDestination(normalized, relSrcPath, rawTarget) ||
        resolveLinkDestination(normalized + '.md', relSrcPath, `${rawTarget}.md`);

      if (newPath) {
        return rewriteLinkTarget(newPath, currentDir, anchor);
      }
      return match;
    }
  );

  return content;
}

function injectConnectorCatalogBanner(content, relSrcPath) {
  if (relSrcPath !== 'CONNECTORS.md') {
    return content;
  }

  const banner = [
    ':::tip',
    'Looking for the full inventory? See the [Connector Catalog](./connector-catalog).',
    ':::',
    '',
    '',
  ].join('\n');

  if (content.startsWith('---')) {
    const match = content.match(/^---\n[\s\S]*?\n---\n/);
    if (match) {
      const end = match[0].length;
      return content.slice(0, end) + '\n' + banner + content.slice(end);
    }
  }

  return banner + content;
}

// A source must exist with exactly this spelling (fs.existsSync alone is case-insensitive on macOS).
function sourceExists(src) {
  let current = REPO_ROOT;
  for (const part of src.split('/')) {
    if (!fs.existsSync(current) || !fs.readdirSync(current).includes(part)) {
      return false;
    }
    current = path.join(current, part);
  }
  return fs.statSync(current).isFile();
}

// Every key must name an existing file and every destination must be unique. Nothing guesses a
// source from its basename, so a moved or renamed file fails here instead of publishing another page.
function sourceMapProblems() {
  const problems = [];
  const owners = new Map();
  for (const key of Object.keys(DOC_MAP)) {
    if (!/^docs\/.+\.md$/.test(key)) {
      problems.push(`DOC_MAP key '${key}' is not a literal docs/<path>.md source`);
    }
    if (key in DOCSITE_EXCLUDE) {
      problems.push(`'${key}' is both a DOC_MAP key and a DOCSITE_EXCLUDE entry`);
    }
  }
  for (const { src, dest } of PUBLISHED_SOURCES) {
    if (!sourceExists(src)) {
      problems.push(`source '${src}' (-> ${dest}) does not exist`);
    }
    if (owners.has(dest)) {
      problems.push(`destination ${dest} is claimed by both '${owners.get(dest)}' and '${src}'`);
    }
    if (DOCSITE_HAND_MAINTAINED.includes(dest)) {
      problems.push(`destination ${dest} of '${src}' would overwrite a hand-maintained page`);
    }
    owners.set(dest, src);
  }
  for (const src of REPO_SOURCE_LINK_ONLY) {
    if (!REPO_MARKDOWN_LINKS[`../${src}`] || src in REPO_SOURCE_MAP) {
      problems.push(`REPO_SOURCE_LINK_ONLY entry '${src}' needs a REPO_MARKDOWN_LINKS alias and no page`);
    }
  }
  return problems;
}

// Process a single file
function processFile(src, destPath) {
  const srcPath = path.join(REPO_ROOT, src);
  let content = fs.readFileSync(srcPath, 'utf8');
  const relSrcPath = path.relative(SOURCE_DIR, srcPath);
  const normalizedRelSrcPath = relSrcPath.replace(/\\/g, '/');
  content = PUBLIC_DOC_CONTENT_OVERRIDES[normalizedRelSrcPath] || content;
  const title = extractTitle(content);
  const baseName = path.basename(relSrcPath, '.md');
  const isAdr = relSrcPath.startsWith('ADR' + path.sep);
  const slug = isAdr && baseName !== 'README' ? baseName : null;

  const description =
    normalizedRelSrcPath === 'reference/CLI_REFERENCE.md'
      ? 'Generated Aragora CLI command catalog from live parser'
      : undefined;

  // Add frontmatter
  content = addFrontmatter(content, title, description, slug);

  // Fix content for compatibility (pass relative dest path)
  const relDestPath = destPath.replace(DEST_DIR + '/', '');
  content = fixContent(content, relDestPath, normalizedRelSrcPath);
  content = injectConnectorCatalogBanner(content, relSrcPath);

  // Ensure destination directory exists
  const destDir = path.dirname(destPath);
  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }

  fs.writeFileSync(destPath, content);
  console.log(`  ✓ ${src} -> ${relDestPath}`);
}

// Create index file for a category
function createIndexFile(category, title, description, items = []) {
  const indexPath = path.join(DEST_DIR, category, 'index.md');

  let itemsList = '';
  if (items.length > 0) {
    itemsList = '\n\n## In This Section\n\n' + items.map(item => `- [${item.title}](${item.path})`).join('\n');
  }

  const content = `---
title: ${title}
description: ${description}
sidebar_position: 1
---

# ${title}

${description}

Explore the documentation in this section to learn more.${itemsList}
`;

  if (!fs.existsSync(path.dirname(indexPath))) {
    fs.mkdirSync(path.dirname(indexPath), { recursive: true });
  }

  fs.writeFileSync(indexPath, content);
  console.log(`  ✓ Created index: ${category}/index.md`);
}

function docsSpecsItems() {
  return PUBLISHED_SOURCES
    .filter(({ src, dest }) => src.startsWith('docs/specs/') && dest.startsWith('specs/'))
    .map(({ src, dest }) => {
      const title = extractTitle(fs.readFileSync(path.join(REPO_ROOT, src), 'utf8'));
      return {
        title,
        path: `./${path.basename(dest, '.md')}`,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title));
}

function docsReferenceItems() {
  return PUBLISHED_SOURCES
    .filter(({ src, dest }) => src.startsWith('docs/reference/') && dest.startsWith('reference/'))
    .map(({ src, dest }) => {
      const title = extractTitle(fs.readFileSync(path.join(REPO_ROOT, src), 'utf8'));
      return {
        title,
        path: `./${path.basename(dest, '.md')}`,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title));
}

// Main sync function
function syncDocs() {
  console.log('\\n📚 Syncing documentation...\\n');

  const problems = sourceMapProblems();
  if (problems.length > 0) {
    for (const problem of problems) {
      console.error(`  ✗ ${problem}`);
    }
    console.error('\nSync aborted before writing any page: fix the source maps above.');
    process.exit(1);
  }

  // Ensure destination directory exists
  if (!fs.existsSync(DEST_DIR)) {
    fs.mkdirSync(DEST_DIR, { recursive: true });
  }

  for (const { src, dest } of PUBLISHED_SOURCES) {
    processFile(src, path.join(DEST_DIR, dest));
  }

  // Create index files for each category
  console.log('\\n📁 Creating category index files...\\n');

  const categories = [
    { path: 'getting-started', title: 'Getting Started', desc: 'Learn how to get started with Aragora' },
    { path: 'core-concepts', title: 'Core Concepts', desc: 'Understand the key concepts of Aragora' },
    { path: 'guides', title: 'Guides', desc: 'Step-by-step guides for common tasks' },
    { path: 'api', title: 'API Reference', desc: 'Complete API documentation' },
    { path: 'deployment', title: 'Deployment', desc: 'Deploy Aragora in production' },
    { path: 'operations', title: 'Operations', desc: 'Runbooks and operational procedures' },
    { path: 'enterprise', title: 'Enterprise', desc: 'Enterprise features and compliance' },
    { path: 'security', title: 'Security & Compliance', desc: 'Security, authentication, and compliance' },
    { path: 'admin', title: 'Administration', desc: 'Administrative features and management' },
    { path: 'advanced', title: 'Advanced Topics', desc: 'Advanced features and internals' },
    { path: 'analysis', title: 'Analysis & Metrics', desc: 'Performance analysis and benchmarks' },
    { path: 'contributing', title: 'Contributing', desc: 'How to contribute to Aragora' },
    {
      path: 'specs',
      title: 'Specifications',
      desc: 'Design and governance specifications for receipts, quorum policy, and related protocols',
    },
    {
      path: 'reference',
      title: 'Reference',
      desc: 'Technical reference material covering configuration, environment variables, error codes, and other detailed references',
    },
  ];

  for (const cat of categories) {
    const items =
      cat.path === 'specs'
        ? docsSpecsItems()
        : cat.path === 'reference'
          ? docsReferenceItems()
          : [];
    createIndexFile(cat.path, cat.title, cat.desc, items);
  }

  console.log(`\\n✅ Done! Synced ${PUBLISHED_SOURCES.length} files\\n`);
}

// Run sync
syncDocs();
