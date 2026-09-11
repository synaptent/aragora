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
const SOURCE_DIR = path.join(__dirname, '../../docs');
const DEST_DIR = path.join(__dirname, '../docs');

function walkMarkdownFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.name === '.git' || entry.name === 'node_modules') {
      continue;
    }
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkMarkdownFiles(fullPath));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith('.md')) {
      files.push(fullPath);
    }
  }
  return files;
}

function buildSourceIndex(rootDir) {
  const index = new Map();
  for (const fullPath of walkMarkdownFiles(rootDir)) {
    const rel = path.relative(rootDir, fullPath).replace(/\\/g, '/');
    const base = path.basename(rel);
    if (!index.has(base)) {
      index.set(base, []);
    }
    index.get(base).push(rel);
  }
  return index;
}

const SOURCE_INDEX = buildSourceIndex(SOURCE_DIR);

function resolveSourcePath(srcRelPath) {
  const directPath = path.join(SOURCE_DIR, srcRelPath);
  if (fs.existsSync(directPath)) {
    return { srcPath: directPath, resolvedFrom: srcRelPath };
  }

  const normalized = srcRelPath.replace(/\\/g, '/');
  const base = path.basename(normalized);
  const candidates = SOURCE_INDEX.get(base) || [];
  if (candidates.length === 0) {
    return null;
  }

  const srcParts = normalized.split('/').slice(0, -1).filter(p => p !== '.' && p !== '..');
  let filtered = candidates;
  if (srcParts.length > 0) {
    const hinted = candidates.filter(candidate => {
      const candidateParts = candidate.split('/');
      return srcParts.every(part => candidateParts.includes(part));
    });
    if (hinted.length > 0) {
      filtered = hinted;
    }
  }

  // Prefer non-deprecated docs when multiple matches exist.
  const nonDeprecated = filtered.filter(
    candidate => !candidate.startsWith('deprecated/') && !candidate.includes('/deprecated/')
  );
  if (nonDeprecated.length === 1) {
    return {
      srcPath: path.join(SOURCE_DIR, nonDeprecated[0]),
      resolvedFrom: nonDeprecated[0],
    };
  }
  if (nonDeprecated.length > 0) {
    filtered = nonDeprecated;
  }

  if (filtered.length === 1) {
    return { srcPath: path.join(SOURCE_DIR, filtered[0]), resolvedFrom: filtered[0] };
  }

  // As a final fallback, pick exact-case basename match with shortest path.
  const exactCase = filtered.filter(candidate => path.basename(candidate) === base);
  if (exactCase.length > 0) {
    exactCase.sort((a, b) => a.length - b.length || a.localeCompare(b));
    return { srcPath: path.join(SOURCE_DIR, exactCase[0]), resolvedFrom: exactCase[0] };
  }

  return null;
}

// Document mapping: source -> destination with category organization
const DOC_MAP = {
  // `docs-site/docs/enterprise/positioning.md` is intentionally hand-maintained
  // as a redirect-style stub after archiving `docs/status/COMMERCIAL_POSITIONING.md`.

  // =========================================================================
  // Getting Started
  // =========================================================================
  'guides/GETTING_STARTED.md': 'getting-started/overview.md',
  'quickstart.md': 'getting-started/quickstart.md',
  'CONFIGURATION.md': 'getting-started/configuration.md',
  'ENVIRONMENT.md': 'getting-started/environment.md',

  // =========================================================================
  // Core Concepts
  // =========================================================================
  'DEBATE_PHASES.md': 'core-concepts/debates.md',
  'DEBATE_INTERNALS.md': 'core-concepts/debate-internals.md',
  'AGENTS.md': 'core-concepts/agents.md',
  'AGENT_DEVELOPMENT.md': 'core-concepts/agent-development.md',
  'AGENT_SELECTION.md': 'core-concepts/agent-selection.md',
  'algorithms/CONSENSUS.md': 'core-concepts/consensus.md',
  'MEMORY_TIERS.md': 'core-concepts/memory.md',
  'MEMORY.md': 'core-concepts/memory-overview.md',
  'MEMORY_STRATEGY.md': 'core-concepts/memory-strategy.md',
  'KNOWLEDGE_MOUND.md': 'core-concepts/knowledge-mound.md',
  'ARCHITECTURE.md': 'core-concepts/architecture.md',
  'REASONING.md': 'core-concepts/reasoning.md',
  'WORKFLOW_ENGINE.md': 'core-concepts/workflow-engine.md',

  // =========================================================================
  // Guides
  // =========================================================================
  'SDK_GUIDE.md': 'guides/sdk.md',
  'SDK_QUICKSTART.md': 'guides/sdk-quickstart.md',
  'guides/PYTHON_SDK_MIGRATION.md': 'guides/python-sdk-migration.md',
  'api/API_REFERENCE_CURATED.md': 'api-reference/index.md',
  'API_QUICK_START.md': 'guides/api-quickstart.md',
  'API_USAGE.md': 'guides/api-usage.md',
  'WORKFLOWS.md': 'guides/workflows.md',
  'workflow/SKILLS.md': 'guides/skills.md',
  'TEMPLATES.md': 'guides/templates.md',
  'INTEGRATIONS.md': 'guides/integrations.md',
  'DOCUMENTS.md': 'guides/documents.md',
  'CHANNELS.md': 'guides/channels.md',
  'BOT_INTEGRATIONS.md': 'guides/bot-integrations.md',
  'CUSTOM_AGENTS.md': 'guides/custom-agents.md',
  'CHAT_CONNECTOR_GUIDE.md': 'guides/chat-connector.md',
  'CONNECTORS.md': 'guides/connectors.md',
  'connectors/CONNECTOR_CATALOG.md': 'guides/connector-catalog.md',
  'CONNECTORS_SETUP.md': 'guides/connectors-setup.md',
  'CONNECTOR_TROUBLESHOOTING.md': 'guides/connector-troubleshooting.md',
  'integrations/HOOKS.md': 'guides/hooks.md',
  'ACCOUNTING.md': 'guides/accounting.md',
  'EVIDENCE.md': 'guides/evidence.md',
  'EVIDENCE_API_GUIDE.md': 'api/evidence.md',
  'GRAPH_DEBATES.md': 'guides/graph-debates.md',
  'MATRIX_DEBATES.md': 'guides/matrix-debates.md',
  'GAUNTLET.md': 'guides/gauntlet.md',
  'GAUNTLET_ARCHITECTURE.md': 'guides/gauntlet-architecture.md',
  'PROBE_STRATEGIES.md': 'guides/probe-strategies.md',
  'HARNESSES_GUIDE.md': 'guides/harnesses.md',
  'MODES_GUIDE.md': 'guides/modes.md',
  'MODES_REFERENCE.md': 'guides/modes-reference.md',
  'USER_ONBOARDING.md': 'guides/user-onboarding.md',
  'AUTOMATION_INTEGRATIONS.md': 'guides/automation.md',
  'EMAIL_PRIORITIZATION.md': 'guides/email-prioritization.md',
  'SHARED_INBOX.md': 'guides/shared-inbox.md',
  'COST_VISIBILITY.md': 'guides/cost-visibility.md',
  'CODING_ASSISTANCE.md': 'guides/coding-assistance.md',
  'BROADCAST.md': 'guides/broadcast.md',
  'PULSE.md': 'guides/pulse.md',
  'WEBSOCKET_EVENTS.md': 'guides/websocket-events.md',
  'SDK_TYPESCRIPT.md': 'guides/sdk-typescript.md',
  'SDK_PARITY.md': 'guides/sdk-parity.md',
  'SDK_CONSOLIDATION.md': 'guides/sdk-consolidation.md',
  'LIBRARY_USAGE.md': 'guides/library-usage.md',
  'PLUGIN_GUIDE.md': 'guides/plugin-guide.md',
  'GITHUB_ACTION_SETUP.md': 'guides/github-action-setup.md',
  'guides/github-actions-review.md': 'guides/github-actions-review.md',

  // =========================================================================
  // API Reference
  // =========================================================================
  'API_REFERENCE.md': 'api/reference.md',
  'API_ENDPOINTS.md': 'api/endpoints.md',
  'API_EXAMPLES.md': 'api/examples.md',
  'API_VERSIONING.md': 'api/versioning.md',
  'API_RATE_LIMITS.md': 'api/rate-limits.md',
  'API_STABILITY.md': 'api/stability.md',
  'API_DISCOVERY.md': 'api/discovery.md',
  'api/SUPPORTED_SURFACE.md': 'api/supported-surface.md',
  'reference/CLI_REFERENCE.md': 'api/cli.md',
  'GITHUB_PR_REVIEW.md': 'api/github-pr-review.md',
  'api/WEBHOOKS.md': 'api/webhooks.md',

  // =========================================================================
  // Deployment
  // =========================================================================
  'DEPLOYMENT.md': 'deployment/overview.md',
  'SECURITY_DEPLOYMENT.md': 'deployment/security.md',
  'SCALING.md': 'deployment/scaling.md',
  'CAPACITY_PLANNING.md': 'deployment/capacity-planning.md',
  'REDIS_HA.md': 'deployment/redis-ha.md',
  'KUBERNETES.md': 'deployment/kubernetes.md',
  'STREAMING_DEPLOYMENT.md': 'deployment/streaming.md',
  'deployment/ASYNC_GATEWAY.md': 'deployment/async-gateway.md',
  'deployment/CONTAINER_VOLUMES.md': 'deployment/container-volumes.md',
  'PRODUCTION_DEPLOYMENT.md': 'deployment/production-deployment.md',
  'DATABASE_SETUP.md': 'deployment/database-setup.md',
  'DATABASE.md': 'deployment/database.md',
  'DATABASE_SCHEMA.md': 'deployment/database-schema.md',
  'deployment/DISASTER_RECOVERY.md': 'deployment/disaster-recovery.md',
  'deployment/POSTGRES_HA.md': 'deployment/postgres-ha.md',
  'RBAC_MATRIX.md': 'deployment/RBAC_MATRIX.md',
  'DR_DRILL_PROCEDURES.md': 'deployment/dr-drills.md',
  'OBSERVABILITY.md': 'deployment/observability.md',
  'observability/WATCHDOG.md': 'operations/watchdog.md',
  'OBSERVABILITY_SETUP.md': 'deployment/observability-setup.md',
  'guides/MONITORING_SETUP.md': 'guides/monitoring-setup.md',
  'deployment/DEPLOYMENT_DECISION_MATRIX.md': 'deployment/decision-matrix.md',
  'TLS.md': 'deployment/tls.md',
  'SECRETS_MIGRATION.md': 'deployment/secrets-migration.md',

  // =========================================================================
  // Operations / Runbooks
  // =========================================================================
  'runbooks/RUNBOOK_DEPLOYMENT.md': 'operations/runbook-deployment.md',
  'runbooks/RUNBOOK_INCIDENT.md': 'operations/runbook-incident.md',
  'runbooks/RUNBOOK_DATABASE_ISSUES.md': 'operations/runbook-database.md',
  'runbooks/RUNBOOK_PROVIDER_FAILURE.md': 'operations/runbook-provider.md',
  'runbooks/RUNBOOK_BACKUP_AUTOMATION.md': 'operations/runbook-backup-automation.md',
  'runbooks/RUNBOOK_MULTI_REGION_SETUP.md': 'operations/runbook-multi-region-setup.md',
  'runbooks/RUNBOOK_POSTGRESQL_REPLICATION.md': 'operations/runbook-postgresql-replication.md',
  'runbooks/RUNBOOK_POSTGRESQL_MIGRATION.md': 'operations/runbook-postgresql-migration.md',
  'runbooks/redis-failover.md': 'operations/redis-failover.md',
  'runbooks/database-migration.md': 'operations/database-migration.md',
  'runbooks/incident-response.md': 'operations/incident-response.md',
  'runbooks/scaling.md': 'operations/scaling.md',
  'runbooks/monitoring-setup.md': 'operations/monitoring-setup.md',
  'runbooks/DISASTER_RECOVERY.md': 'operations/disaster-recovery-runbook.md',
  'ALERT_RUNBOOKS.md': 'operations/alert-runbooks.md',
  'RUNBOOK.md': 'operations/runbook.md',
  'PRODUCTION_RUNBOOK.md': 'operations/production-runbook.md',
  'RUNBOOK_METRICS.md': 'operations/runbook-metrics.md',
  'INCIDENT_RESPONSE.md': 'operations/incident-response.md',
  'INCIDENT_RESPONSE_PLAYBOOKS.md': 'operations/incident-response-playbooks.md',
  'INCIDENT_COMMUNICATION.md': 'operations/incident-communication.md',

  // =========================================================================
  // Enterprise
  // =========================================================================
  'GOVERNANCE.md': 'enterprise/governance.md',
  'CONTROL_PLANE.md': 'enterprise/control-plane-overview.md',
  'CONTROL_PLANE_GUIDE.md': 'enterprise/control-plane.md',
  'ENTERPRISE_FEATURES.md': 'enterprise/features.md',
  'ENTERPRISE_SUPPORT.md': 'enterprise/support.md',
  'enterprise/DISASTER_RECOVERY.md': 'enterprise/disaster-recovery.md',
  'COMMERCIAL_OVERVIEW.md': 'enterprise/commercial-overview.md',
  'WHY_ARAGORA.md': 'enterprise/why-aragora.md',
  'PRICING.md': 'enterprise/pricing.md',
  'BILLING.md': 'enterprise/billing.md',
  'BILLING_UNITS.md': 'enterprise/billing-units.md',
  'SSO_SETUP.md': 'enterprise/sso.md',
  'STRIPE_SETUP.md': 'enterprise/stripe-setup.md',
  'SLA.md': 'enterprise/sla.md',

  // =========================================================================
  // Security & Compliance
  // =========================================================================
  'SECURITY.md': 'security/overview.md',
  'AUTH_GUIDE.md': 'security/authentication.md',
  'COMPLIANCE.md': 'enterprise/compliance.md',
  'COMPLIANCE_PRESETS.md': 'security/compliance-presets.md',
  'DATA_CLASSIFICATION.md': 'security/data-classification.md',
  'DATA_RESIDENCY.md': 'security/data-residency.md',
  'PRIVACY_POLICY.md': 'security/privacy-policy.md',
  'BREACH_NOTIFICATION_SLA.md': 'security/breach-notification.md',
  'CI_CD_SECURITY.md': 'security/ci-cd.md',
  'REMOTE_WORK_SECURITY.md': 'security/remote-work.md',
  'DSAR_WORKFLOW.md': 'security/dsar.md',
  'SECURITY_RUNTIME.md': 'security/runtime.md',
  'SECURITY_PATTERNS.md': 'security/patterns.md',
  'OAUTH_GUIDE.md': 'security/oauth-guide.md',
  'OAUTH_SETUP.md': 'security/oauth-setup.md',
  'SESSION_MANAGEMENT.md': 'security/session-management.md',
  'compliance/EU_AI_ACT_GUIDE.md': 'security/eu-ai-act-guide.md',

  // =========================================================================
  // Admin & Management
  // =========================================================================
  'ADMIN.md': 'admin/overview.md',
  'A_B_TESTING.md': 'admin/ab-testing.md',
  'NOMIC_LOOP.md': 'admin/nomic-loop.md',

  // =========================================================================
  // Advanced Topics
  // =========================================================================
  'RLM_GUIDE.md': 'advanced/rlm.md',
  'RLM_USER_GUIDE.md': 'advanced/rlm-user.md',
  'RLM_DEVELOPER_GUIDE.md': 'advanced/rlm-developer.md',
  'INTEGRATION_RLM.md': 'advanced/rlm-integration.md',
  'CROSS_POLLINATION.md': 'advanced/cross-pollination.md',
  'CROSS_FUNCTIONAL_FEATURES.md': 'advanced/cross-functional.md',
  'TRICKSTER.md': 'advanced/trickster.md',
  'FORMAL_VERIFICATION.md': 'advanced/formal-verification.md',
  'resilience/RESILIENCE.md': 'advanced/resilience.md',
  'status/PROPULSION.md': 'advanced/propulsion.md',

  // =========================================================================
  // Analysis & Metrics
  // =========================================================================
  'ANALYSIS.md': 'analysis/overview.md',
  'CODEBASE_ANALYSIS.md': 'analysis/codebase.md',
  'BENCHMARK_RESULTS.md': 'analysis/benchmarks.md',
  'case-studies/README.md': 'analysis/case-studies/index.md',
  'case-studies/architecture-stress-test.md': 'analysis/case-studies/architecture-stress-test.md',
  'case-studies/gdpr-compliance-audit.md': 'analysis/case-studies/gdpr-compliance-audit.md',
  'case-studies/epic-strategic-debate.md': 'analysis/case-studies/epic-strategic-debate.md',
  'case-studies/security-api-review.md': 'analysis/case-studies/security-api-review.md',

  // =========================================================================
  // Architecture Decision Records
  // =========================================================================
  'ADR/README.md': 'analysis/adr/index.md',
  'ADR/001-phase-based-debate-execution.md': 'analysis/adr/001-phase-based-debate-execution.md',
  'ADR/002-agent-fallback-openrouter.md': 'analysis/adr/002-agent-fallback-openrouter.md',
  'ADR/003-multi-tier-memory-system.md': 'analysis/adr/003-multi-tier-memory-system.md',
  'ADR/004-incremental-type-safety.md': 'analysis/adr/004-incremental-type-safety.md',
  'ADR/005-composition-over-inheritance.md': 'analysis/adr/005-composition-over-inheritance.md',
  'ADR/006-api-versioning-strategy.md': 'analysis/adr/006-api-versioning-strategy.md',
  'ADR/007-selection-plugin-architecture.md': 'analysis/adr/007-selection-plugin-architecture.md',
  'ADR/008-rlm-semantic-compression.md': 'analysis/adr/008-rlm-semantic-compression.md',
  'ADR/009-control-plane-architecture.md': 'analysis/adr/009-control-plane-architecture.md',
  'ADR/010-debate-orchestration-pattern.md': 'analysis/adr/010-debate-orchestration-pattern.md',
  'ADR/011-multi-tier-memory-comparison.md': 'analysis/adr/011-multi-tier-memory-comparison.md',
  'ADR/012-agent-fallback-strategy.md': 'analysis/adr/012-agent-fallback-strategy.md',
  'ADR/013-workflow-dag-design.md': 'analysis/adr/013-workflow-dag-design.md',
  'ADR/014-knowledge-mound-architecture.md': 'analysis/adr/014-knowledge-mound-architecture.md',
  'ADR/015-lazy-import-patterns.md': 'analysis/adr/015-lazy-import-patterns.md',
  'ADR/016-marketplace-architecture.md': 'analysis/adr/016-marketplace-architecture.md',

  // =========================================================================
  // Contributing
  // =========================================================================
  'CONTRIBUTING.md': 'contributing/guide.md',
  'NEXT_STEPS.md': 'contributing/next-steps.md',
  'FIRST_CONTRIBUTION.md': 'contributing/first-contribution.md',
  'INDEX.md': 'contributing/documentation-index.md',
  'COLD_REVIEWER_GUIDE.md': 'contributing/cold-reviewer-guide.md',
  'INBOX_GUIDE.md': 'contributing/INBOX_GUIDE.md',
  'DEPRECATION_POLICY.md': 'contributing/deprecation.md',
  'STATUS.md': 'contributing/status.md',
  'DEPENDENCIES.md': 'contributing/dependencies.md',
  'FRONTEND_DEVELOPMENT.md': 'contributing/frontend-development.md',
  'FRONTEND_ROUTES.md': 'contributing/frontend-routes.md',
  'HANDLER_DEVELOPMENT.md': 'contributing/handler-development.md',
  'TESTING.md': 'contributing/testing.md',
  'HANDLERS.md': 'contributing/handlers.md',
  'status/FEATURE_DISCOVERY.md': 'contributing/feature-discovery.md',
  'FEATURE_GAP_LIST.md': 'contributing/feature-gap-list.md',
  'status/ACTIVE_EXECUTION_ISSUES.md': 'contributing/active-execution-issues.md',
  'status/ROADMAP_INTAKE_REGISTER.md': 'contributing/roadmap-intake-register.md',
  'status/B0_BENCHMARK_TRUTH_STATUS.md': 'contributing/b0-benchmark-truth-status.md',
  'status/NEXT_STEPS_CANONICAL.md': 'contributing/next-steps-canonical.md',
  'status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md':
    'contributing/execution-next-6-weeks-2026-03-05.md',
  'status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md':
    'contributing/documentation-hygiene-and-gap-register.md',
  'status/PMF_SCORECARD.md': 'contributing/pmf-scorecard.md',
  'status/TW03_RESCUE_PRODUCTIZATION_STATUS.md':
    'contributing/tw03-rescue-productization-status.md',
  'CANONICAL_GOALS.md': 'contributing/canonical-goals.md',
  '../CLAUDE.md': 'contributing/claude.md',
  'EXTENDED_README.md': 'contributing/extended-readme.md',
  '../ROADMAP.md': 'contributing/roadmap.md',
  'plans/ARAGORA_EVOLUTION_ROADMAP.md': 'contributing/aragora-evolution-roadmap.md',
  'plans/PMF_DOGFOOD_EXECUTION_PLAN.md': 'contributing/pmf-dogfood-execution-plan.md',
  'plans/2026-03-26-pmf-14-day-execution-plan.md':
    'contributing/2026-03-26-pmf-14-day-execution-plan.md',
  'superpowers/specs/2026-06-26-strategy-as-bounded-mission-cadence-design.md':
    'contributing/strategy-as-bounded-mission-cadence-design.md',
  'superpowers/plans/2026-06-26-mission-cadence-m0-m1.md':
    'contributing/mission-cadence-m0-m1.md',
  'guides/CONDUCTOR_WORKFLOW.md': 'guides/conductor-workflow.md',
  'guides/SWARM_DOGFOOD_OPERATOR.md': 'guides/swarm-dogfood-operator.md',
  'guides/WORKER_PROMPT_PACK.md': 'guides/worker-prompt-pack.md',
  'architecture/DEV_SWARM_COORDINATION.md': 'contributing/dev-swarm-coordination.md',
  'enterprise/SECRETS.md': 'enterprise/secrets.md',
  'plans/2026-03-07-conductor-control-plane.md':
    'contributing/conductor-control-plane-implementation-spec.md',
  'workflow/MARKETPLACE.md': 'guides/marketplace.md',

  // =========================================================================
  // Specifications
  //
  // docs/specs/** design/governance specs. Intra-directory links between these
  // files (e.g. 'TAMPER_EVIDENT_TRAIL.md' from OPEN_DECISION_RECEIPT.md) resolve
  // via the source-relative lookup below, not through this table directly.
  // =========================================================================
  'specs/ADVISORY_REVIEW_RECOGNIZABLE_HEADER.md':
    'specs/advisory-review-recognizable-header.md',
  'specs/ARAGORA_ROADMAP_REVISION_ADVOCATES.md':
    'specs/aragora-roadmap-revision-advocates.md',
  'specs/CHINESE_ROUTED_REVIEWER_FAMILIES_9071.md':
    'specs/chinese-routed-reviewer-families-9071.md',
  'specs/ESSAY_REFINEMENT_PIPELINE.md': 'specs/essay-refinement-pipeline.md',
  'specs/FINDING_SEVERITY_GATE.md': 'specs/finding-severity-gate.md',
  'specs/INDEPENDENT_VERIFIER_GUIDE.md': 'specs/independent-verifier-guide.md',
  'specs/LOCAL_ADVOCATE_TRAINING_PIPELINE.md': 'specs/local-advocate-training-pipeline.md',
  'specs/MODEL_DISSENT_SEVERITY_GATE.md': 'specs/model-dissent-severity-gate.md',
  'specs/MODEL_LINEAGE_DISCLOSURE.md': 'specs/model-lineage-disclosure.md',
  'specs/MODEL_QUORUM_FAMILY_EXPANSION.md': 'specs/model-quorum-family-expansion.md',
  'specs/OPEN_DECISION_RECEIPT.md': 'specs/open-decision-receipt.md',
  'specs/QUORUM_EVIDENCE_RETRIGGER.md': 'specs/quorum-evidence-retrigger.md',
  'specs/RECEIPT_LINEAGE_RECONCILIATION.md': 'specs/receipt-lineage-reconciliation.md',
  'specs/TAMPER_EVIDENT_TRAIL.md': 'specs/tamper-evident-trail.md',
  'specs/TIER4_SETTLEMENT_PROBE_TIMEOUT_REPORTING.md':
    'specs/tier4-settlement-probe-timeout-reporting.md',
  'specs/TIERED_MERGE_GATE_QUORUM_POLICY.md': 'specs/tiered-merge-gate-quorum-policy.md',
  'specs/odr-native-mapping.md': 'specs/odr-native-mapping.md',

  // =========================================================================
  // Reference
  //
  // docs/reference/** technical reference material, mirrored as its own
  // `reference/` category (parallel to Specifications above). Several files
  // in this directory intentionally have no entry here because they already
  // resolve through a pre-existing DOC_MAP entry elsewhere -- see
  // ACCOUNTING.md, ADMIN.md, BILLING.md, BILLING_UNITS.md, CONTROL_PLANE.md,
  // DATABASE.md, DATABASE_SCHEMA.md, DEPENDENCIES.md, DEPRECATION_POLICY.md,
  // DOCUMENTS.md, ENVIRONMENT.md, HANDLERS.md, and LIBRARY_USAGE.md above
  // (resolveSourcePath()'s basename fallback), plus reference/CLI_REFERENCE.md
  // under API Reference. Adding a second reference/ entry for those would
  // publish the same content at two docs-site URLs.
  // =========================================================================
  'reference/BINDINGS.md': 'reference/bindings.md',
  'reference/BREAKING_CHANGES.md': 'reference/breaking-changes.md',
  'reference/CANONICAL_STORES.md': 'reference/canonical-stores.md',
  'reference/CREDITS.md': 'reference/credits.md',
  'reference/ENVIRONMENT_COMPLETE.md': 'reference/environment-complete.md',
  'reference/ERROR_CODES.md': 'reference/error-codes.md',
  'reference/ERROR_HANDLING.md': 'reference/error-handling.md',
  'reference/ERROR_TRACKING.md': 'reference/error-tracking.md',
  'reference/IMPLEMENT.md': 'reference/implement.md',
  // Not reference/index.md: that filename is reserved for the auto-generated
  // category index createIndexFile() writes below, which would otherwise
  // silently overwrite this file's synced content.
  'reference/INDEX.md': 'reference/reference-index.md',
  'reference/INSTALL_MATRIX.md': 'reference/install-matrix.md',
  'reference/ROOT_ALLOWLIST.md': 'reference/root-allowlist.md',
  'reference/TYPE_CHECKING.md': 'reference/type-checking.md',

  // =========================================================================
  // Additional Missing Files (commonly referenced)
  // =========================================================================
  // Core
  'TROUBLESHOOTING.md': 'operations/troubleshooting.md',
  'QUEUE.md': 'guides/queue.md',
  'RATE_LIMITING.md': 'deployment/rate-limiting.md',
  'SECRETS_MANAGEMENT.md': 'deployment/secrets-management.md',
  'MEMORY_ANALYTICS.md': 'core-concepts/memory-analytics.md',

  // API
  'MCP_INTEGRATION.md': 'guides/mcp-integration.md',
  'MCP_ADVANCED.md': 'guides/mcp-advanced.md',

  // Operations
  'PERFORMANCE_TARGETS.md': 'operations/performance-targets.md',
  'PRODUCTION_READINESS.md': 'operations/production-readiness.md',

  // Advanced
  'GENESIS.md': 'advanced/genesis.md',
  'EVOLUTION_PATTERNS.md': 'advanced/evolution-patterns.md',

  // Admin

  // Security

  // Integration / Enterprise
  'POSTGRESQL_MIGRATION.md': 'deployment/postgresql-migration.md',

  // Algorithms
  'algorithms/CONVERGENCE.md': 'core-concepts/convergence-algorithm.md',
  'algorithms/ELO_CALIBRATION.md': 'core-concepts/elo-calibration.md',

  // Documents
  'FEATURES.md': 'guides/features.md',
  'VERTICALS.md': 'guides/verticals.md',
  'OPERATIONS.md': 'operations/overview.md',
};

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
const basenameCounts = new Map();
for (const src of Object.keys(DOC_MAP)) {
  const srcName = path.basename(src.replace(/^\.\//, '').replace(/^\//, ''));
  basenameCounts.set(srcName, (basenameCounts.get(srcName) || 0) + 1);
}
for (const [src, dest] of Object.entries(DOC_MAP)) {
  // Normalize source path variations
  const srcBase = src.replace(/^\.\//, '').replace(/^\//, '');
  const srcName = path.basename(srcBase);

  // Store both with and without .md extension
  REVERSE_LOOKUP[srcBase] = dest;
  REVERSE_LOOKUP[srcBase.replace('.md', '')] = dest.replace('.md', '');

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
      const normalized = filePath.replace(/^\.\.\//, '').replace(/^\.\//, '');
      const rawTarget = `${prefix}${filePath}`;
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

// Process a single file
function processFile(srcRelPath, destPath) {
  const resolved = resolveSourcePath(srcRelPath);
  if (!resolved) {
    console.log(`  Skipping (not found): ${srcRelPath}`);
    return false;
  }

  const srcPath = resolved.srcPath;
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
  const sourceNote =
    resolved.resolvedFrom && resolved.resolvedFrom !== srcRelPath
      ? ` (${srcRelPath} -> ${resolved.resolvedFrom})`
      : '';
  console.log(
    `  ✓ ${path.basename(srcPath)} -> ${destPath.replace(DEST_DIR + '/', '')}${sourceNote}`
  );
  return true;
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
  return Object.entries(DOC_MAP)
    .filter(([src, dest]) => src.startsWith('specs/') && dest.startsWith('specs/'))
    .map(([src, dest]) => {
      const resolved = resolveSourcePath(src);
      const content = resolved ? fs.readFileSync(resolved.srcPath, 'utf8') : '';
      const title = content ? extractTitle(content) : path.basename(dest, '.md');
      return {
        title,
        path: `./${path.basename(dest, '.md')}`,
      };
    })
    .sort((left, right) => left.title.localeCompare(right.title));
}

function docsReferenceItems() {
  return Object.entries(DOC_MAP)
    .filter(([src, dest]) => src.startsWith('reference/') && dest.startsWith('reference/'))
    .map(([src, dest]) => {
      const resolved = resolveSourcePath(src);
      const content = resolved ? fs.readFileSync(resolved.srcPath, 'utf8') : '';
      const title = content ? extractTitle(content) : path.basename(dest, '.md');
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

  // Ensure destination directory exists
  if (!fs.existsSync(DEST_DIR)) {
    fs.mkdirSync(DEST_DIR, { recursive: true });
  }

  let synced = 0;
  let skipped = 0;

  // Process each mapped file
  for (const [src, dest] of Object.entries(DOC_MAP)) {
    const destPath = path.join(DEST_DIR, dest);
    if (processFile(src, destPath)) {
      synced++;
    } else {
      skipped++;
    }
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

  console.log(`\\n✅ Done! Synced ${synced} files, skipped ${skipped} (not found)\\n`);
}

// Run sync
syncDocs();
