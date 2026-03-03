---
title: Aragora CLI Reference
description: Aragora CLI Reference
---

# Aragora CLI Reference

> Source of truth: generated from `aragora/cli/parser.py` via `python scripts/generate_cli_reference.py`.

## Scope

This reference documents the command surface as implemented in code. It includes all top-level commands and known aliases.

- Canonical top-level commands: **75**
- Total top-level invocations (including aliases): **76**

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
| `ask` | - | Run a decision stress-test (debate engine) | - |
| `audit` | - | Document compliance and audit commands | `create`, `export`, `findings`, `preset`, `presets`, `report`, `start`, `status`, `types` |
| `autopilot` | - | Autonomous GTM task orchestration | - |
| `backup` | - | Database backup and restore commands | `cleanup`, `create`, `list`, `restore`, `verify` |
| `badge` | - | Generate Aragora badge for your README | - |
| `batch` | - | Process multiple debates from a file | - |
| `bench` | - | Benchmark agents | - |
| `billing` | - | Manage billing, usage, and subscriptions | `invoices`, `portal`, `status`, `subscribe`, `usage` |
| `compliance` | - | Compliance framework and EU AI Act tools | `audit`, `check`, `classify`, `eu-ai-act`, `report`, `status` |
| `computer-use` | - | Computer use task management | `list`, `run`, `status` |
| `config` | - | Manage configuration | - |
| `connectors` | - | Connector management commands | `list`, `status`, `test` |
| `consensus` | - | Analyze consensus from debate proposals or check debate consensus status | `detect`, `status` |
| `context` | - | Build codebase context for RLM-powered analysis | - |
| `control-plane` | - | Control plane status and management | - |
| `coordinate` | - | Multi-agent worktree coordination | `events`, `merge`, `plan`, `register`, `scope`, `status`, `sync` |
| `costs` | - | Cost tracking and billing management commands | `agents`, `budget`, `dashboard`, `forecast`, `report`, `usage` |
| `cross-pollination` | `xpoll` | Cross-pollination event system diagnostics | - |
| `decide` | - | Run full decision pipeline: debate → plan → execute | - |
| `demo` | - | Run a self-contained adversarial debate demo (no API keys needed) | - |
| `deploy` | - | Deployment validation and configuration | `secrets`, `start`, `status`, `stop`, `validate` |
| `doctor` | - | Run system health checks | - |
| `document-audit` | - | Audit documents using multi-agent analysis | `report`, `scan`, `status`, `upload` |
| `documents` | - | Document management (upload, list, show) | `list`, `show`, `upload` |
| `elo` | - | View ELO ratings, leaderboards, and match history | - |
| `explain` | - | Explain a debate decision (evidence chains, vote pivots, counterfactuals) | - |
| `export` | - | Export debate artifacts | - |
| `gauntlet` | - | Adversarial stress-test a specification, architecture, or policy | - |
| `handlers` | - | List registered HTTP handlers and routes | `list`, `routes` |
| `healthcare` | - | Healthcare vertical: adversarial clinical decision review | `review` |
| `improve` | - | Self-improvement mode using AutonomousOrchestrator | - |
| `init` | - | Initialize Aragora project | - |
| `km` | - | Knowledge Mound management commands | `query`, `stats`, `store` |
| `knowledge` | - | Knowledge base operations | `facts`, `jobs`, `process`, `query`, `search`, `stats` |
| `marketplace` | - | Manage agent template marketplace | - |
| `mcp-server` | - | Run the MCP (Model Context Protocol) server | - |
| `memory` | - | Memory management commands | `promote`, `query`, `stats`, `store` |
| `modes` | - | List available operational modes | - |
| `nomic` | - | Nomic loop self-improvement commands | `history`, `resume`, `run`, `status` |
| `openclaw` | - | OpenClaw Enterprise Gateway management | `audit`, `init`, `next-steps`, `policy`, `review`, `serve`, `status` |
| `outcome` | - | Record and search decision outcomes | `record`, `search` |
| `patterns` | - | Show learned patterns | - |
| `pipeline` | - | Run idea-to-execution pipeline operations | `run`, `self-improve`, `status` |
| `plans` | - | Manage decision plans | `approve`, `execute`, `list`, `reject`, `show` |
| `playbook` | - | List and run decision playbooks | `list`, `run` |
| `publish` | - | Build, test, and publish packages to PyPI/npm | - |
| `quickstart` | - | Guided zero-to-receipt first debate (new user onboarding) | - |
| `rbac` | - | RBAC management commands | `assign`, `check`, `check-local`, `list-permissions`, `list-roles`, `permissions`, `roles` |
| `receipt` | - | View, verify, and export decision receipts | `export`, `inspect`, `list`, `show`, `verify`, `view` |
| `repl` | - | Interactive debate mode | - |
| `replay` | - | Replay stored debates | - |
| `review` | - | Run AI code review on a diff or PR | - |
| `rlm` | - | RLM (Recursive Language Models) operations | `clear-cache`, `compress`, `query`, `stats` |
| `security` | - | Security operations (encryption, key rotation) | `health`, `list-tokens`, `migrate`, `rotate-key`, `rotate-token`, `status`, `verify-token` |
| `self-improve` | - | Run self-improvement pipeline with worktree isolation and validation | - |
| `serve` | - | Run live debate server | - |
| `setup` | - | Interactive setup wizard for API keys and configuration | - |
| `skills` | - | Skill marketplace commands | `info`, `install`, `list`, `scan`, `search`, `stats`, `uninstall` |
| `starter` | - | SME Starter Pack -- install to decision receipt in 15 minutes | - |
| `stats` | - | Show memory statistics | - |
| `status` | - | Show environment health and agent availability | - |
| `swarm` | - | Launch a swarm of AI agents to accomplish a goal | - |
| `template` | - | Manage workflow templates | `list`, `package`, `run`, `show`, `validate` |
| `templates` | - | List available debate templates | - |
| `tenant` | - | Manage multi-tenant deployments | `activate`, `create`, `delete`, `export`, `list`, `quota-get`, `quota-set`, `suspend` |
| `testfixer` | - | Run automated test-fix loop | - |
| `validate` | - | Validate API keys by making test calls | - |
| `validate-env` | - | Validate environment configuration and backend connectivity | - |
| `verify` | - | Verify a decision receipt's integrity | - |
| `verticals` | - | Manage vertical specialist configurations | - |
| `workflow` | - | Workflow engine commands | `categories`, `list`, `patterns`, `run`, `status`, `templates` |
| `worktree` | - | Manage git worktrees for parallel agent sessions | `autopilot`, `cleanup`, `conflicts`, `create`, `fleet-claim`, `fleet-claims`, `fleet-queue-add`, `fleet-queue-list`, `fleet-release`, `fleet-status`, `list`, `merge`, `merge-all` |

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
