---
title: Aragora CLI Reference
description: Generated Aragora CLI command catalog from live parser
---

# Aragora CLI Reference

> Source of truth: generated from `aragora/cli/parser.py` via `python scripts/generate_cli_reference.py`.

## Scope

This reference documents the command surface as implemented in code. It includes all top-level commands and known aliases.

- Canonical top-level commands: **110**
- Total top-level invocations (including aliases): **111**

## Installation

```bash
pip install aragora
```

## Global Usage

```bash
aragora [--version] [--db PATH] [--verbose] <command> [options]
```

### Global Options

| Option | Default | Description |
|--------|---------|-------------|
| `--version, -V` | `-` | show program's version number and exit |
| `--db` | `agora_memory.db` | SQLite database path |
| `-v, --verbose` | `false` | Verbose output |

For full runtime configuration, see [ENVIRONMENT](../getting-started/environment).

## Command Catalog

| Command | Aliases | Summary | Subcommands |
|---------|---------|---------|-------------|
| `agent` | - | Run autonomous agents (DevOps, review, triage) | `run` |
| `agents` | - | List available agents and their configuration | - |
| `analytics` | - | View debate analytics and platform usage | `agents`, `costs`, `summary`, `trends` |
| `api-key` | - | Manage LLM API keys | `list`, `set`, `validate` |
| `ask` | - | Run a decision stress-test (debate engine) | - |
| `assess` | - | Run canonical repository assessment | - |
| `audit` | - | Document compliance and audit commands | `create`, `export`, `findings`, `preset`, `presets`, `report`, `start`, `status`, `types` |
| `autopilot` | - | Autonomous GTM task orchestration | - |
| `backup` | - | Database backup and restore commands | `cleanup`, `create`, `list`, `restore`, `verify` |
| `badge` | - | Generate Aragora badge for your README | - |
| `batch` | - | Process multiple debates from a file | - |
| `bench` | - | Benchmark agents | - |
| `billing` | - | Manage billing, usage, and subscriptions | `invoices`, `portal`, `status`, `subscribe`, `usage` |
| `build` | - | Turn a vague idea into executed, reviewed, merged code | - |
| `calibration` | - | AGT-03.3: per-agent rolling-window Brier reports from market data | `leaderboard`, `report` |
| `codebase-audit` | - | Run a staged repo audit with triage, threat-surface ranking, and deep audit | - |
| `codex` | - | Read-only inspector for Codex Desktop local state | `insights`, `sessions` |
| `coherence-scan` | - | DIC-26: scan a belief ledger for contradictions, evidence conflicts, and confidence rot | - |
| `compliance` | - | Compliance framework and EU AI Act tools | `audit`, `check`, `classify`, `eu-ai-act`, `evidence`, `export`, `oversight-pack`, `report`, `status` |
| `computer-use` | - | Computer use task management | `list`, `run`, `status` |
| `config` | - | Manage configuration | - |
| `connectors` | - | Connector management commands | `list`, `status`, `test` |
| `consensus` | - | Analyze consensus from debate proposals or check debate consensus status | `detect`, `status` |
| `context` | - | Build codebase context for RLM-powered analysis | - |
| `control-plane` | - | Control plane status and management | - |
| `coordinate` | - | Multi-agent worktree coordination | `events`, `merge`, `plan`, `register`, `scope`, `status`, `sync` |
| `costs` | - | Cost tracking and billing management commands | `agents`, `budget`, `dashboard`, `forecast`, `report`, `usage` |
| `cross-pollination` | `xpoll` | Cross-pollination event system diagnostics | - |
| `crux` | - | Find load-bearing disagreements on a question (crux-finder debate) | - |
| `crux-arbitrate` | - | DIC-27: resolve persistent cruxes as reversible signed arbitration receipts | - |
| `crux-followup` | - | Generate DIC-17 follow-up proposals from a CruxSet (flag-gated filing) | - |
| `crux-garden` | - | DIC-28: proactive re-examination of cruxes for staleness and contradictions | - |
| `cruxset` | - | AGT-01: inspect CruxSet payloads emitted by the debate path | `show` |
| `decay-monitor` | - | DIC-20: report epistemic decay for proof-carrying code units | - |
| `decide` | - | Run full decision pipeline: debate → plan → execute | - |
| `demo` | - | Run a self-contained adversarial debate demo (no API keys needed) | - |
| `deploy` | - | Deployment validation and configuration | `secrets`, `start`, `status`, `stop`, `validate` |
| `doctor` | - | Run system health checks | - |
| `document-audit` | - | Audit documents using multi-agent analysis | `report`, `scan`, `status`, `upload` |
| `documents` | - | Document management (upload, list, show) | `list`, `show`, `upload` |
| `elo` | - | View ELO ratings, leaderboards, and match history | - |
| `epistemic-check` | - | DIC-14: verify executable claim manifests and emit a status report | - |
| `essay` | - | Refine raw ideas into a polished essay or score an existing draft | `refine`, `score` |
| `explain` | - | Explain a debate decision (evidence chains, vote pivots, counterfactuals) | - |
| `export` | - | Export debate artifacts | - |
| `factory` | - | Read-only inspector for Factory/Droid local session metadata | `sessions` |
| `gauntlet` | - | Adversarial stress-test a specification, architecture, or policy | - |
| `genealogy` | - | DIC-24: inspect epistemic genealogy ledger for proof-carrying code units | `report`, `show` |
| `handlers` | - | List registered HTTP handlers and routes | `list`, `routes` |
| `healthcare` | - | Healthcare vertical: adversarial clinical decision review | `review` |
| `idea` | - | Clarify a vague idea into a structured initiative brief | `intake`, `review`, `triage` |
| `ideacloud` | - | Manage the Idea Cloud knowledge graph | `cluster`, `export`, `link`, `list`, `load`, `promote`, `pulse`, `rss`, `search`, `show`, `stats`, `sync-km` |
| `improve` | - | Self-improvement mode using AutonomousOrchestrator | - |
| `inbox-wedge` | - | Receipt-gated inbox trust wedge commands | `create`, `execute`, `export`, `list`, `report`, `review`, `show` |
| `init` | - | Initialize Aragora project | - |
| `km` | - | Knowledge Mound management commands | `query`, `stats`, `store` |
| `knowledge` | - | Knowledge base operations | `facts`, `jobs`, `process`, `query`, `search`, `stats` |
| `marketplace` | - | Manage agent template marketplace | - |
| `markets` | - | AGT-04: inspect and interact with synthetic GitHub prediction markets | `create`, `list`, `predict`, `resolve` |
| `mcp-server` | - | Run the MCP (Model Context Protocol) server | - |
| `memory` | - | Memory management commands | `promote`, `query`, `stats`, `store` |
| `metrics` | - | AGT-06: read VIAH and other operator metrics | `status`, `viah` |
| `mission` | - | Run or manage native missions | - |
| `modes` | - | List available operational modes | - |
| `nomic` | - | Nomic loop self-improvement commands | `history`, `resume`, `run`, `status` |
| `openclaw` | - | OpenClaw Enterprise Gateway management | `audit`, `init`, `next-steps`, `policy`, `review`, `serve`, `status`, `watch` |
| `outcome` | - | Record and search decision outcomes | `record`, `search` |
| `patterns` | - | Show learned patterns | - |
| `pipeline` | - | Run idea-to-execution pipeline operations | `dogfood`, `run`, `self-improve`, `status` |
| `plans` | - | Manage decision plans | `approve`, `execute`, `list`, `reject`, `show` |
| `playbook` | - | List and run decision playbooks | `list`, `run` |
| `proof-units` | - | DIC-19: inspect proof-carrying code unit constraint graph | - |
| `publish` | - | Build, test, and publish packages to PyPI/npm | - |
| `quickstart` | - | Guided zero-to-receipt first debate (new user onboarding) | - |
| `ralph` | - | Ralph campaign supervisor — autonomous incident commander | - |
| `rbac` | - | RBAC management commands | `assign`, `check`, `check-local`, `list-permissions`, `list-roles`, `permissions`, `roles` |
| `receipt` | - | View, verify, and export decision receipts | `export`, `inspect`, `list`, `show`, `verify`, `view` |
| `repl` | - | Interactive debate mode | - |
| `replay` | - | Replay stored debates | - |
| `review` | - | Run AI code review on a diff or PR | - |
| `review-local` | - | Run a non-OpenAI (Claude Max pool) review on a LOCAL diff, no GitHub required | - |
| `review-pr` | - | Review a live GitHub PR head and optionally run a fixer loop | - |
| `review-queue` | - | PR review queue + advisory packets + human settlement | `act`, `baseline`, `build`, `collect-evidence`, `conductor`, `evidence-lint`, `health`, `health-alert`, `lint-comment`, `merge-packet`, `observe-outcomes`, `packet`, `record-settlement`, `run` |
| `rlm` | - | RLM (Recursive Language Models) operations | `clear-cache`, `compress`, `query`, `stats` |
| `secrets` | - | Inspect AWS Secrets Manager-backed secret presence | `health`, `hydrate` |
| `security` | - | Security operations (encryption, key rotation) | `health`, `list-tokens`, `migrate`, `rotate-key`, `rotate-token`, `status`, `verify-token` |
| `self-improve` | - | Run self-improvement pipeline with worktree isolation and validation | - |
| `serve` | - | Run live debate server | - |
| `setup` | - | Interactive setup wizard for API keys and configuration | - |
| `signing` | - | Sign and verify context files for Nomic Loop provenance (G1) | `show`, `sign`, `verify` |
| `skills` | - | Skill marketplace commands | `info`, `install`, `list`, `scan`, `search`, `stats`, `uninstall` |
| `spec` | - | Transform a vague idea into a structured specification | - |
| `starter` | - | SME Starter Pack -- install to decision receipt in 15 minutes | - |
| `stats` | - | Show memory statistics | - |
| `status` | - | Show environment health, agent availability, or founder ops status | - |
| `swarm` | - | Launch a swarm of AI agents to accomplish a goal | - |
| `tasks` | - | Inspect and operate the developer task queue | `claim`, `complete`, `heartbeat`, `leases`, `list`, `release`, `salvage`, `show`, `stats`, `sync` |
| `template` | - | Manage workflow templates | `list`, `package`, `run`, `show`, `validate` |
| `templates` | - | List available debate templates | - |
| `tenant` | - | Manage multi-tenant deployments | `activate`, `create`, `delete`, `export`, `list`, `quota-get`, `quota-set`, `suspend` |
| `testfixer` | - | Run automated test-fix loop | - |
| `triage` | - | Inbox triage via adversarial debate with receipt-gated actions | `audit`, `auth`, `calibrate`, `digest`, `label`, `queue`, `run`, `status` |
| `truth-map` | - | DIC-18: read-only organizational truth map of claim and crux status | - |
| `validate` | - | Run a full health check, including live API-key validation | - |
| `validate-env` | - | Validate environment configuration and backend connectivity | - |
| `verify` | - | Verify a decision receipt's integrity | - |
| `verticals` | - | Manage vertical specialist configurations | - |
| `work` | - | Inspect the read-only Aragora work board | `graph`, `list`, `robot`, `show` |
| `workflow` | - | Workflow engine commands | `categories`, `list`, `patterns`, `run`, `status`, `templates` |
| `worktree` | - | Manage git worktrees for parallel agent sessions | `autopilot`, `cleanup`, `conflicts`, `create`, `fleet-claim`, `fleet-claims`, `fleet-queue-add`, `fleet-queue-list`, `fleet-queue-process-next`, `fleet-reap-claims`, `fleet-release`, `fleet-status`, `list`, `merge`, `merge-all` |

## Core Workflows

```bash
# Fast onboarding
aragora quickstart --demo

# Debate
aragora ask "Design a rate limiter" --agents anthropic-api,openai-api --rounds 3

# Full decision pipeline
aragora decide "Roll out SSO" --auto-approve --budget-limit 10.00

# Receipt validation
aragora receipt verify receipt.json
aragora verify receipt.json

# Start API + WebSocket server
aragora serve --api-port 8080 --ws-port 8765
```

## Notes

- There is **no** top-level `training` CLI command in the current parser.
- For any command-specific flags, use `aragora <command> --help`.
- For nested commands, use `aragora <command> <subcommand> --help`.

## See Also

- [SDK Guide](../guides/sdk)
- [Receipt and Gauntlet Guidance](../guides/gauntlet)
- [API Reference](./reference)
