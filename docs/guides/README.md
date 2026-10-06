# Guides

Task-oriented how-to guides for using, deploying, extending and developing
Aragora. Every page in this directory is listed below once, grouped by what
you are trying to do. New to Aragora? Start with the
[Quickstart](../quickstart.md) or [START_HERE](../START_HERE.md), then come
back here for a specific task. The full documentation map is in
[docs/README.md](../README.md).

Status notes in the tables come from each page's own header. Pages marked as
a record or a report describe a point in time; check the code before relying
on their numbers.

## First Steps and Evaluation

| Guide | What it covers |
|-------|----------------|
| [USE_CASES](./USE_CASES.md) | Ten real-world scenarios where adversarial multi-agent debate improves a decision |
| [USER_ONBOARDING](./USER_ONBOARDING.md) | Installation, your first debate and reading the results |
| [SMB_QUICK_START](./SMB_QUICK_START.md) | Five-minute start for small and medium businesses |
| [SME_ONBOARDING](./SME_ONBOARDING.md) | Step-by-step onboarding for small and medium enterprises |
| [SME_GA_GUIDE](./SME_GA_GUIDE.md) | SME Starter Pack general availability guide |
| [SME_STARTER_PACK](./SME_STARTER_PACK.md) | SME Starter Pack scope definition (status: scope definition) |
| [ONBOARDING_FLOW](./ONBOARDING_FLOW.md) | Design of the 15-minute flow to a first debate and decision receipt |
| [COLD_REVIEWER_GUIDE](./COLD_REVIEWER_GUIDE.md) | Shortest path for a reviewer, auditor or new maintainer with no prior context |
| [STRANGER_TEST](./STRANGER_TEST.md) | Copy-paste kit for getting cold-eyes feedback from a developer |
| [FRONTEND_ROUTES](./FRONTEND_ROUTES.md) | Map of the web UI routes in `aragora/live` and their related docs |

## SDKs and the HTTP API

| Guide | What it covers |
|-------|----------------|
| [SDK_QUICKSTART](./SDK_QUICKSTART.md) | Install to first debate in under two minutes, with no server or API keys |
| [DEVELOPER_GUIDE](./DEVELOPER_GUIDE.md) | Installation, SDK overview and common patterns for developers building on Aragora |
| [python-quickstart](./python-quickstart.md) | Python SDK walkthrough |
| [SDK_QUICKSTART_PYTHON](./SDK_QUICKSTART_PYTHON.md) | Short Python SDK quickstart |
| [typescript-quickstart](./typescript-quickstart.md) | TypeScript SDK walkthrough |
| [SDK_QUICKSTART_TYPESCRIPT](./SDK_QUICKSTART_TYPESCRIPT.md) | Short TypeScript SDK quickstart |
| [SDK_TYPESCRIPT](./SDK_TYPESCRIPT.md) | The `@aragora/sdk` TypeScript client: retries, WebSocket streaming and types |
| [SDK_COMPARISON](./SDK_COMPARISON.md) | Python and TypeScript SDKs side by side |
| [sdk-parity](./sdk-parity.md) | Feature parity between the Python and TypeScript SDKs |
| [ERROR_HANDLING](./ERROR_HANDLING.md) | Handling errors from the Python and TypeScript SDKs |
| [API_COOKBOOK](./API_COOKBOOK.md) | Twenty runnable recipes for common API operations |
| [AUTH_GUIDE](./AUTH_GUIDE.md) | Authenticating with the Aragora platform |
| [PYTHON_SDK_CONSOLIDATION](./PYTHON_SDK_CONSOLIDATION.md) | `aragora-sdk` is the canonical Python SDK; the legacy `aragora-client` is removed |
| [PYTHON_SDK_MIGRATION](./PYTHON_SDK_MIGRATION.md) | Migrating from `aragora-client` to `aragora-sdk` |
| [MIGRATION_GUIDE](./MIGRATION_GUIDE.md) | Migrating from deprecated SDK packages to the current ones |
| [V1_TO_V2_MIGRATION](./V1_TO_V2_MIGRATION.md) | Migrating from API v1 to v2 |
| [SDK_PARITY](./SDK_PARITY.md) | Generated SDK-to-API parity report (record, February 2026) |
| [SDK_HANDLER_PARITY](./SDK_HANDLER_PARITY.md) | Generated SDK-to-handler parity report (record, January 2026) |
| [SDK_ROADMAP](./SDK_ROADMAP.md) | SDK parity roadmap; the page marks it complete and keeps the January 2026 sprint record |
| [SDK_CONSOLIDATION](./SDK_CONSOLIDATION.md) | TypeScript SDK consolidation roadmap (record, January 2026) |

## Setup, Deployment and Operations

| Guide | What it covers |
|-------|----------------|
| [CLI_SETUP_GUIDE](./CLI_SETUP_GUIDE.md) | The interactive `aragora setup` wizard and its options |
| [LOCAL_DEVELOPMENT](./LOCAL_DEVELOPMENT.md) | Running Aragora locally for development, testing and debugging |
| [DATABASE_SETUP](./DATABASE_SETUP.md) | SQLite for development and PostgreSQL for production |
| [SUPABASE_SETUP](./SUPABASE_SETUP.md) | Supabase checklist for the aragora.ai production database |
| [SELF_HOSTED_QUICKSTART](./SELF_HOSTED_QUICKSTART.md) | Quick path to a self-hosted deployment |
| [SELF_HOSTED_COMPLETE_GUIDE](./SELF_HOSTED_COMPLETE_GUIDE.md) | Complete self-hosting reference |
| [STRIPE_SETUP](./STRIPE_SETUP.md) | Connecting Stripe to receive subscription payments |
| [apple-oauth-setup](./apple-oauth-setup.md) | Configuring Sign in with Apple |
| [GITHUB_APP_SETUP](./GITHUB_APP_SETUP.md) | GitHub App for automated PR reviews, issue triage and code analysis debates |
| [GITHUB_ACTION_SETUP](./GITHUB_ACTION_SETUP.md) | Adding multi-agent code review to pull requests with the GitHub Action |
| [github-actions-review](./github-actions-review.md) | Multi-agent code review for any repository through GitHub Actions |
| [BETA_REVIEW_GUIDE](./BETA_REVIEW_GUIDE.md) | Aragora Review beta: multi-agent review that debates your diffs |
| [MONITORING_SETUP](./MONITORING_SETUP.md) | Prometheus and Grafana monitoring |
| [OBSERVABILITY_SETUP](./OBSERVABILITY_SETUP.md) | Full observability stack: metrics, logging, tracing and alerting |
| [TROUBLESHOOTING](./TROUBLESHOOTING.md) | Common issues and their solutions |

## Platform Features

| Guide | What it covers |
|-------|----------------|
| [MODES_GUIDE](./MODES_GUIDE.md) | Operational modes (Architect, Coder and others) and advanced debate modes |
| [PIPELINE_GUIDE](./PIPELINE_GUIDE.md) | The four-stage Idea-to-Execution pipeline |
| [CONTROL_PLANE_GUIDE](./CONTROL_PLANE_GUIDE.md) | Enterprise control plane for managing heterogeneous agents |
| [INBOX_GUIDE](./INBOX_GUIDE.md) | Smart Inbox: prioritizing, threading and managing email |
| [SHARED_INBOX](./SHARED_INBOX.md) | Shared inbox APIs, ownership and routing rules |
| [GATEWAY_GUIDE](./GATEWAY_GUIDE.md) | Device-local message routing and the unified inbox |
| [WORKSPACE_GUIDE](./WORKSPACE_GUIDE.md) | Developer orchestration with rigs, convoys and beads |
| [FABRIC_GUIDE](./FABRIC_GUIDE.md) | High-scale agent orchestration with pools, scheduling and policies |
| [COMPUTER_USE_GUIDE](./COMPUTER_USE_GUIDE.md) | Safe computer-use automation with the Claude Computer Use API |
| [FINE_TUNING_GUIDE](./FINE_TUNING_GUIDE.md) | LoRA fine-tuning on debate outcomes |
| [ML_INTEGRATION_GUIDE](./ML_INTEGRATION_GUIDE.md) | Local ML for agent selection, quality scoring and consensus prediction |

### Recursive Language Models (RLM)

Two systems share the RLM name. `RLM_GUIDE` covers RLM-inspired debate
patterns; the other three pages cover the `aragora/rlm/` module.

| Guide | What it covers |
|-------|----------------|
| [RLM_USER_GUIDE](./RLM_USER_GUIDE.md) | What RLM is and how to use it |
| [RLM_DEVELOPER_GUIDE](./RLM_DEVELOPER_GUIDE.md) | Integrating the RLM module in applications |
| [RLM_INTEGRATION](./RLM_INTEGRATION.md) | Programmatic context access through the RLM REPL |
| [RLM_GUIDE](./RLM_GUIDE.md) | RLM-inspired patterns for efficient multi-agent debates |

## Extending Aragora

| Guide | What it covers |
|-------|----------------|
| [CUSTOM_AGENTS](./CUSTOM_AGENTS.md) | Building API and CLI agents and registering them |
| [PLUGIN_GUIDE](./PLUGIN_GUIDE.md) | Writing plugins for the control plane |
| [ADAPTER_GUIDE](./ADAPTER_GUIDE.md) | Creating Knowledge Mound adapters for external systems |
| [ADAPTER_INTEGRATION_GUIDE](./ADAPTER_INTEGRATION_GUIDE.md) | Working with the Knowledge Mound adapter system |
| [CHAT_CONNECTOR_GUIDE](./CHAT_CONNECTOR_GUIDE.md) | Chat platform connectors (Slack, Teams, Discord, Telegram and more) |
| [CONNECTORS_SETUP](./CONNECTORS_SETUP.md) | Enterprise connectors that feed the Knowledge Mound |
| [CONNECTOR_TROUBLESHOOTING](./CONNECTOR_TROUBLESHOOTING.md) | Diagnosing evidence connector problems |
| [HARNESSES_GUIDE](./HARNESSES_GUIDE.md) | Harnesses that wrap Claude Code, Codex and other analysis tools |
| [RESILIENCE_PATTERNS_GUIDE](./RESILIENCE_PATTERNS_GUIDE.md) | Resilience strategy for agents, connectors and integrations |

## Contributing and Multi-Agent Development

| Guide | What it covers |
|-------|----------------|
| [FIRST_CONTRIBUTION](./FIRST_CONTRIBUTION.md) | Making your first contribution |
| [COORDINATION_SYSTEM](./COORDINATION_SYSTEM.md) | Running several agent sessions on one repository with `aragora.coordination` |
| [CODEX_WORKTREE_AUTOPILOT](./CODEX_WORKTREE_AUTOPILOT.md) | Worktree autopilot for many concurrent Codex and Claude sessions |
| [CONDUCTOR_WORKFLOW](./CONDUCTOR_WORKFLOW.md) | One coordinating session assigning bounded lanes to workers |
| [LANE_DISPATCH](./LANE_DISPATCH.md) | Claim-first dispatch so worker sessions do not collide on the PR queue |
| [WORKER_PROMPT_PACK](./WORKER_PROMPT_PACK.md) | Worker prompts for the manual operating model |
| [SWARM_DOGFOOD_OPERATOR](./SWARM_DOGFOOD_OPERATOR.md) | Runbook for a supervised, spec-driven swarm run |
| [CAMPAIGN_OPERATOR](./CAMPAIGN_OPERATOR.md) | Multi-project campaigns with `aragora swarm campaign run` |
| [OPERATOR_QUESTIONS](./OPERATOR_QUESTIONS.md) | Asking questions that make agent fleets investigate and act well |
| [ISSUE_TRIAGE](./ISSUE_TRIAGE.md) | Calibration-only multi-model triage of the GitHub issue backlog |
| [CLAUDE_MAX_POOL](./CLAUDE_MAX_POOL.md) | Running a pool of Claude Max plans for reviews |
| [VIBEPROXY](./VIBEPROXY.md) | Using a local VibeProxy as an opt-in model transport |
| [NOMIC_LOOP_TROUBLESHOOTING](./NOMIC_LOOP_TROUBLESHOOTING.md) | Troubleshooting the Nomic Loop |

## Redirect Pages

These pages were consolidated elsewhere and stay only so existing links keep
working.

| Page | Use instead |
|------|-------------|
| [QUICKSTART](./QUICKSTART.md) | [Quickstart](../quickstart.md) |
| [QUICKSTART_DOCKER](./QUICKSTART_DOCKER.md) | [Quickstart](../quickstart.md) |
| [GETTING_STARTED](./GETTING_STARTED.md) | [Quickstart](../quickstart.md) |
| [DEVELOPER_QUICKSTART](./DEVELOPER_QUICKSTART.md) | [Quickstart](../quickstart.md) |
| [SME_QUICKSTART](./SME_QUICKSTART.md) | [Quickstart](../quickstart.md) |
| [CONTRIBUTING](./CONTRIBUTING.md) | The root [CONTRIBUTING.md](../../CONTRIBUTING.md) |
