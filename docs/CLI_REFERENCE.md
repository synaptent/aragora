# Aragora CLI Reference

Aragora provides a unified CLI for running multi-agent debates, managing the decision pipeline, operating the server, and administering the platform. All commands follow the pattern `aragora <command> [subcommand] [options]`.

## Top-Level Commands

| Command | Purpose |
|---------|---------|
| `ask` | Run a multi-agent debate on a question |
| `decide` | Full gold-path pipeline: debate → plan → approve → execute |
| `serve` | Start the HTTP/WebSocket API server |
| `analytics` | View debate statistics, agent performance, costs, trends |
| `autopilot` | Autonomous GTM task orchestration (publish, outreach, etc.) |
| `compliance` | EU AI Act compliance tools: audit, classify, export bundles |
| `consensus` | Detect and inspect consensus across agent proposals |
| `coordinate` | Multi-agent worktree coordination: plan, merge, sync, scope |
| `costs` | Billing usage summary, budget status, cost forecast |
| `computer-use` | Run and manage computer-use tasks via the API |
| `deploy` | Start/stop Docker services, validate readiness, generate secrets |
| `explain` | Show evidence chains, vote pivots, and counterfactuals for a debate |
| `healthcare` | HIPAA-compliant clinical review pipeline with FHIR input support |
| `km` | Query, store, and inspect the Knowledge Mound |
| `memory` | Search, store, promote entries across the multi-tier memory system |
| `nomic` | Run or inspect autonomous self-improvement cycles |
| `outcome` | Record and search real-world outcomes tied to debate decisions |
| `pipeline` | Idea-to-execution 4-stage pipeline (Ideas→Goals→Actions→Orchestration) |
| `playbook` | List and run pre-built end-to-end decision workflows |
| `plans` | List, inspect, approve, reject, and execute decision plans |
| `publish` | Build and publish packages to PyPI/npm |
| `quickstart` | Zero-to-receipt onboarding in one command |
| `rbac` | Manage roles and permissions (assign, check, list) |
| `receipt` | View, verify, inspect, and export decision receipts |
| `self-improve` | Run the hardened autonomous self-improvement pipeline |
| `skills` | Search, install, and manage skills from the marketplace |
| `swarm` | Launch a full swarm lifecycle: interrogate → spec → dispatch → report |
| `testfix` | Auto-fix failing tests using AI-powered diagnosis |
| `verify` | Verify a decision receipt's SHA-256 integrity and signature |
| `verticals` | List and query vertical specialist configurations |
| `workflow` | Run and manage DAG-based automation workflows |
| `worktree` | Manage git worktrees for parallel agent sessions |

---

## Command Details

### `aragora ask`

**Purpose:** Run a multi-agent adversarial debate on any question or decision.

**Usage:** `aragora ask "<question>" [options]`

**Key options:**
- `--agents` — comma-separated agent list (e.g. `anthropic-api,openai-api,grok`); supports `provider:role` and `provider|model|persona|role` formats
- `--rounds` — number of debate rounds (default: configured in `aragora/config.py`)
- `--consensus` — consensus method: `majority`, `unanimous`, `judge`, `hybrid`, `none`
- `--auto-select` — automatically pick the best agent team for the task
- `--context` / `--context-file` — inject additional background into the debate
- `--spectate` — stream live debate events to the terminal

**Examples:**
```bash
aragora ask "Should we migrate to microservices?"
aragora ask "Design a rate limiter" --agents anthropic-api,openai-api,grok --rounds 5
```

---

### `aragora decide`

**Purpose:** Run the full decision gold-path: debate then generate an actionable plan, optionally executing it.

**Usage:** `aragora decide "<question>" [options]`

**Key options:**
- `--agents` / `--rounds` — same as `ask`
- `--auto-approve` — skip human approval gate and execute the plan immediately
- `--dry-run` — create the plan without executing it
- `--budget-limit <usd>` — cap execution cost
- `--execution-mode` — `workflow`, `hybrid`, `fabric`, or `computer_use`
- `--template <id>` — use a pre-built workflow template (see `--list-templates`)
- `--demo` — run offline with mock agents, no API keys required

**Examples:**
```bash
aragora decide "Build a rate limiter" --agents anthropic-api,openai-api --auto-approve
aragora decide "Adopt Kubernetes?" --dry-run --list-templates
```

---

### `aragora serve`

**Purpose:** Start the unified HTTP and WebSocket API server.

**Usage:** `aragora serve [options]`

**Key options:**
- `--api-port` — HTTP API port (default: 8080)
- `--ws-port` — WebSocket port (default: 8765)
- `--demo` — offline mode with SQLite, no API keys required

**Example:**
```bash
aragora serve --api-port 8080 --ws-port 8765
aragora serve --demo
```

---

### `aragora analytics`

**Purpose:** View debate statistics, agent performance leaderboards, cost breakdowns, and usage trends.

**Usage:** `aragora analytics <subcommand>`

**Subcommands:** `summary`, `agents`, `costs`, `trends`

**Example:**
```bash
aragora analytics summary
aragora analytics agents
```

---

### `aragora autopilot`

**Purpose:** Autonomous GTM task orchestration — checks what needs doing and does it (GitHub auth, PyPI/npm publishing, demo data seeding, outreach draft generation).

**Usage:** `aragora autopilot [tasks...] [options]`

**Key options:**
- `--status` — check status of all tasks without executing
- `--dry-run` — preview what would happen without running
- task names: `gh-auth`, `pr-review`, `publish`, `demo-data`, `outreach`, `quickstart`

**Examples:**
```bash
aragora autopilot --status
aragora autopilot publish outreach
```

---

### `aragora compliance`

**Purpose:** EU AI Act compliance tooling — classify use cases, generate conformity reports, and export full compliance bundles mapped to Articles 9, 12–15.

**Usage:** `aragora compliance <subcommand> [options]`

**Subcommands:** `audit`, `classify`, `eu-ai-act`, `export`, `status`, `report`, `check`

**Key options for `export`:**
- `--debate-id <id>` — source debate to export
- `--output-dir <dir>` — directory for the bundle
- `--format` — `markdown`, `html`, or `json`
- `--demo` — generate a sample bundle without a real debate

**Examples:**
```bash
aragora compliance classify --use-case "loan approval"
aragora compliance export --framework eu-ai-act --debate-id abc123 --output-dir ./pack
```

---

### `aragora consensus`

**Purpose:** Detect and inspect consensus across a set of agent proposals, or check the consensus status of an existing debate.

**Usage:** `aragora consensus <detect|status> [options]`

**Key options:**
- `--file <path>` / `--proposals <json>` / `--stdin` — input source for `detect`
- `--threshold <float>` — confidence threshold (default: 0.7)
- `--format json` — machine-readable output

**Examples:**
```bash
aragora consensus detect --task "Choose a DB" --proposals '["PostgreSQL", "MySQL"]'
aragora consensus status abc123 --format json
```

---

### `aragora coordinate`

**Purpose:** Coordinate parallel agent work across isolated git worktrees.

**Usage:** `aragora coordinate <subcommand> [options]`

**Subcommands:** `plan`, `status`, `merge`, `sync`, `scope`, `events`, `register`

**Examples:**
```bash
aragora coordinate status
aragora coordinate plan "Improve test coverage" --tracks qa core
aragora coordinate merge --dry-run
```

---

### `aragora costs`

**Purpose:** View billing usage, budget status, and cost forecasts via the API.

**Usage:** `aragora costs <usage|budget|forecast>`

**Example:**
```bash
aragora costs usage
aragora costs budget
```

---

### `aragora computer-use`

**Purpose:** Start and monitor computer-use tasks that interact with desktop/browser environments.

**Usage:** `aragora computer-use <run|status|list> [options]`

**Example:**
```bash
aragora computer-use run "Fill out the expense form"
aragora computer-use status <task_id>
```

---

### `aragora deploy`

**Purpose:** One-command Docker Compose deployment, deployment validation, and security secret generation.

**Usage:** `aragora deploy <subcommand> [options]`

**Subcommands:** `start`, `stop`, `validate`, `secrets`, `status`

**Key options for `start`:**
- `--profile` — `simple`, `sme`, `production`, or `dev` (default: `simple`)
- `--setup` — run interactive configuration before starting
- `--dry-run` — preview without executing

**Examples:**
```bash
aragora deploy start --profile sme
aragora deploy secrets --type all --output .env.secrets
aragora deploy validate --strict --production
```

---

### `aragora explain`

**Purpose:** Show a structured explanation of how a debate reached its decision, including evidence chains, vote pivots, and counterfactual analysis.

**Usage:** `aragora explain <debate_id> [options]`

**Key options:** `--format json`, `--no-counterfactuals`

**Example:**
```bash
aragora explain abc123
aragora explain abc123 --format json
```

---

### `aragora healthcare`

**Purpose:** Run adversarial clinical decision reviews with HIPAA-compliant PHI redaction and FHIR bundle input support.

**Usage:** `aragora healthcare review <input> [options]`

**Key options:**
- `--fhir <path>` — read a FHIR bundle as input
- `--demo` — run with a built-in sample scenario

**Example:**
```bash
aragora healthcare review "Patient presents with chest pain" --demo
aragora healthcare review --fhir patient-bundle.json
```

---

### `aragora km`

**Purpose:** Query, store, and inspect entries in the Knowledge Mound via the server API.

**Usage:** `aragora km <query|store|stats> [options]`

**Examples:**
```bash
aragora km query "rate limiter patterns"
aragora km store "Key insight from last quarter" --source debate-abc123
aragora km stats
```

---

### `aragora memory`

**Purpose:** Search, store, and promote entries across the four-tier memory system (fast/medium/slow/glacial).

**Usage:** `aragora memory <query|store|stats|promote> [options]`

**Key options for `store`:** `--tier fast|medium|slow|glacial`

**Examples:**
```bash
aragora memory query "database migration"
aragora memory store "Prefer PostgreSQL for OLTP" --tier slow
aragora memory promote <id> --to glacial
```

---

### `aragora nomic`

**Purpose:** Run or inspect the autonomous self-improvement Nomic Loop.

**Usage:** `aragora nomic <run|status|history|resume> [options]`

**Key options for `run`:** `--cycles <n>`

**Examples:**
```bash
aragora nomic run --cycles 3
aragora nomic status
aragora nomic history
```

---

### `aragora outcome`

**Purpose:** Record real-world outcomes for completed debates and search past outcomes to close the decision feedback loop.

**Usage:** `aragora outcome <record|search> [options]`

**Examples:**
```bash
aragora outcome record --debate-id abc123 --result "Adopted PostgreSQL, 40% latency reduction"
aragora outcome search "database"
```

---

### `aragora pipeline`

**Purpose:** Run the full four-stage idea-to-execution pipeline (Ideas → Goals → Actions → Orchestration), or a goal-driven self-improvement variant.

**Usage:** `aragora pipeline <run|self-improve|status> "<input>" [options]`

**Key options:** `--dry-run`, `--budget-limit`

**Examples:**
```bash
aragora pipeline run "Build rate limiter, Add caching"
aragora pipeline self-improve "Maximize utility for SMEs" --budget-limit 5
```

---

### `aragora plans`

**Purpose:** List, inspect, approve, reject, and manually execute decision plans created by `decide`.

**Usage:** `aragora plans [show|approve|reject|execute] [plan_id] [options]`

**Examples:**
```bash
aragora plans
aragora plans show <plan_id>
aragora plans approve <plan_id> --reason "Reviewed and accepted"
aragora plans execute <plan_id>
```

---

### `aragora playbook`

**Purpose:** List and run pre-built end-to-end decision workflows that combine debate templates, compliance artifacts, vertical scoring, and approval gates.

**Usage:** `aragora playbook <list|run> [options]`

**Example:**
```bash
aragora playbook list
aragora playbook run sme-decision
```

---

### `aragora publish`

**Purpose:** Build, test, and publish Aragora packages to PyPI and npm.

**Usage:** `aragora publish [package] [options]`

**Key options:** `--all`, `--dry-run`

**Examples:**
```bash
aragora publish --all --dry-run
aragora publish python-sdk
aragora publish debate
```

---

### `aragora quickstart`

**Purpose:** Zero-to-receipt onboarding: auto-detects API keys, runs a short debate, displays the verdict, and opens an HTML receipt in the browser.

**Usage:** `aragora quickstart [options]`

**Key options:** `--question "<text>"`, `--no-browser`

**Example:**
```bash
aragora quickstart
aragora quickstart --question "Should we rewrite in Go?"
```

---

### `aragora rbac`

**Purpose:** Manage roles and permissions. API-backed commands require a running server; `list-roles`, `list-permissions`, and `check-local` work offline.

**Usage:** `aragora rbac <subcommand> [options]`

**Subcommands:** `roles`, `permissions`, `assign`, `check`, `list-roles`, `list-permissions`, `check-local`

**Examples:**
```bash
aragora rbac list-roles
aragora rbac assign user-123 analyst
aragora rbac check user-123 backups:read
```

---

### `aragora receipt`

**Purpose:** View, verify, inspect, and convert decision receipt files.

**Usage:** `aragora receipt <view|verify|inspect|export> <file> [options]`

**Key options for `export`:** `--format html|md|json|sarif|pdf|csv`

**Examples:**
```bash
aragora receipt view .aragora/receipts/debate-abc.json
aragora receipt verify receipt.json
aragora receipt export receipt.json --format sarif
```

---

### `aragora self-improve`

**Purpose:** Run the full worktree-isolated self-improvement pipeline: MetaPlanner debate → TaskDecomposer → WorktreeManager → HardenedOrchestrator → BranchCoordinator → audit receipts.

**Usage:** `aragora self-improve "<goal>" [options]`

**Key options:**
- `--tracks` — comma-separated tracks: `sme`, `developer`, `qa`, `core`, `security`, `self_hosted`
- `--dry-run`, `--require-approval`, `--budget-limit <usd>`
- `--spectate` — stream live events; `--receipt` — generate audit receipts

**Examples:**
```bash
aragora self-improve "Improve test coverage" --tracks qa --budget-limit 5
aragora self-improve "Harden security" --dry-run
```

---

### `aragora skills`

**Purpose:** Search, install, uninstall, and inspect agent skills from the marketplace.

**Usage:** `aragora skills <search|list|install|uninstall|info|stats> [options]`

**Examples:**
```bash
aragora skills search "summarization"
aragora skills install summarize-v2
aragora skills list
```

---

### `aragora swarm`

**Purpose:** Launch the full swarm lifecycle: interrogate a goal → generate a spec → dispatch to agents → report results.

**Usage:** `aragora swarm "<goal>" [options]`

**Key options:**
- `--skip-interrogation` — bypass the clarification phase
- `--spec <file>` — load a pre-written YAML spec
- `--budget-limit <usd>`, `--dry-run`, `--profile <cto|...>`
- `--from-obsidian <vault>` — load goals from an Obsidian vault

**Examples:**
```bash
aragora swarm "Make the dashboard faster"
aragora swarm "Add auth" --budget-limit 10 --dry-run
```

---

### `aragora testfix`

**Purpose:** Automatically diagnose and fix failing tests using AI-powered forward analysis.

**Usage:** `aragora testfix [options]`

**Example:**
```bash
aragora testfix
```

---

### `aragora verify`

**Purpose:** Verify a decision receipt JSON file has not been tampered with by recomputing its SHA-256 checksum and validating required fields and any cryptographic signature chain.

**Usage:** `aragora verify <receipt_file>`

**Example:**
```bash
aragora verify .aragora/receipts/debate-abc.json
```

---

### `aragora verticals`

**Purpose:** List and query vertical specialist configurations (healthcare, financial, legal, etc.) and get compliance tool recommendations for a given task.

**Usage:** `aragora verticals <list|get|tools|compliance|suggest> [options]`

**Examples:**
```bash
aragora verticals list
aragora verticals suggest --task "Loan approval workflow"
aragora verticals compliance healthcare
```

---

### `aragora workflow`

**Purpose:** Run and manage DAG-based automation workflows, including listing 50+ pre-built templates and patterns.

**Usage:** `aragora workflow <list|run|status|templates|patterns> [options]`

**Examples:**
```bash
aragora workflow templates
aragora workflow run <workflow_id>
aragora workflow status <execution_id>
```

---

### `aragora worktree`

**Purpose:** Manage git worktrees for parallel multi-agent development sessions, including creation, merging, conflict detection, and cleanup.

**Usage:** `aragora worktree <create|list|merge|merge-all|conflicts|cleanup> [options]`

**Key options for `create`:** `--tracks sme developer qa`

**Examples:**
```bash
aragora worktree create --tracks sme developer qa
aragora worktree list
aragora worktree merge-all --test-first
aragora worktree cleanup
```
