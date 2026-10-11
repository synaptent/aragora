# Aragora CLI Reference

Aragora provides a unified CLI for running multi-agent debates, managing the decision pipeline, operating the server, and administering the platform. All commands follow the pattern `aragora <command> [subcommand] [options]`.

This page is the canonical CLI reference. The flag-level catalog in
[reference/CLI_REFERENCE.md](reference/CLI_REFERENCE.md) is generated from the parser by
`scripts/generate_cli_reference.py`; use it to confirm every option a command accepts.

## Top-Level Commands

| Command | Purpose |
|---------|---------|
| `ask` | Run a multi-agent debate on a question |
| `decide` | Full gold-path pipeline: debate → plan → approve → execute |
| `serve` | Start the HTTP/WebSocket API server |
| `analytics` | View debate statistics, agent performance, costs, trends |
| `api-key` | Securely store, inspect, and validate LLM API keys |
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

### `aragora api-key`

**Purpose:** Securely store provider API keys for CLI use, list configured providers, and validate stored credentials.

**Usage:** `aragora api-key <set|list|validate> [options]`

**Subcommands:**
- `set <provider> <key>` — store a provider key in the secure CLI store
- `list` — show configured status for supported providers
- `validate <provider>` — run a lightweight validation probe for a configured provider

**Supported providers:** `anthropic`, `openai`, `gemini`, `grok`, `openrouter`, `mistral`, `deepseek`, `kimi`

**Examples:**
```bash
aragora api-key set openai sk-...
aragora api-key list
aragora api-key validate anthropic
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

**Purpose:** CLI-first onboarding: load `.env`, get a question, run a short `live` debate only when a configured provider passes connectivity preflight, otherwise fall back to `demo`, save one result artifact, and optionally open an HTML view in the browser.

**Usage:** `aragora quickstart [options]`

**Key options:**
- `--question "<text>"` — provide the question directly instead of using the interactive prompt
- `--demo` — force demo mode with local mock agents
- `--provider <name> --api-key <key>` — run live quickstart without pre-exporting env vars
- `--save-key` — persist the inline provider key to the Aragora secure key store
- `--output <path>` — choose the saved artifact path explicitly
- `--format json|md|html` — saved artifact format (default: `json`)
- `--rounds <n>` — number of debate rounds (default: `2`)
- `--no-browser` — skip the HTML browser view

By default quickstart saves the result artifact to `.aragora/receipts/quickstart-<live|demo>-receipt.<format>`.
Live quickstart artifacts are receipt-shaped JSON and can be inspected with `aragora receipt inspect ...` or verified with `aragora receipt verify ...`.

**Example:**
```bash
aragora quickstart --demo --no-browser
aragora quickstart --question "Should we rewrite in Go?" --output ./receipt.html
aragora quickstart --provider openai --api-key sk-... --save-key --no-browser
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

**Purpose:** Launch the full swarm lifecycle: interrogate a goal → generate a spec → dispatch to agents → report results. Supervisor-backed with lease coordination, managed worktrees, and periodic reconciliation.

**Usage:** `aragora swarm [run|status|reconcile|campaign|integrator|tranche] "<goal>" [options]`

**Subcommands:**
- `run "<goal>"` — decompose goal, provision worktrees, dispatch workers (default)
- `status [--run-id <id>] [--json]` — show active/recent supervisor runs
- `reconcile [--run-id <id> | --all-runs]` — top up leases, dispatch ready workers, collect results

**Key options:**
- `--skip-interrogation` — bypass the clarification phase
- `--spec <file>` — load a pre-written SwarmSpec YAML file
- `--budget-limit <usd>`, `--dry-run`, `--profile <cto|...>`
- `--from-obsidian <vault>` — load goals from an Obsidian vault
- `--dispatch-only` — provision worktrees without waiting for results
- `--no-wait` — fire-and-forget dispatch

**Examples:**
```bash
aragora swarm "Make the dashboard faster"
aragora swarm run "Add auth" --budget-limit 10 --dry-run
aragora swarm status --json
aragora swarm reconcile --all-runs
```

#### `aragora swarm campaign`

**Purpose:** Multi-project campaign execution with persistent manifest, dependency ordering, heterogeneous review, and Ralph-safe single-iteration dispatch.

**Subcommands:**
- `run` — plan (if no manifest) then execute one iteration. Resumes from manifest on subsequent calls.
- `plan` — plan projects from input source, write manifest, do not execute.
- `status` — show campaign progress from the manifest.

**Key options:**
- `--source-file <path>` — markdown/text roadmap file (one item per line)
- `--issue-list <nums>` — comma-separated GitHub issue numbers
- `--github-query <query>` — GitHub issue search query
- `--manifest <path>` — manifest path (default: `.aragora/campaign_manifest.yaml`)
- `--max-parallel-ready-projects <n>` — projects per iteration (default: 1)
- `--worker-model <model>` — worker model (default: codex)
- `--review-model <model>` — review model, must differ from worker (default: claude)
- `--budget-limit <usd>` — total campaign budget (default: 50)

**Examples:**
```bash
# Bootstrap from a roadmap file
aragora swarm campaign run --source-file roadmap.md --json

# Resume from existing manifest
aragora swarm campaign run --json

# Check campaign progress
aragora swarm campaign status --json

# Plan only (no execution)
aragora swarm campaign plan --source-file roadmap.md --json
```

See `docs/guides/CAMPAIGN_OPERATOR.md` for the full operator guide including Ralph loop usage, prebuilt manifest workflow, and stop-reason semantics.

#### `aragora swarm tranche`

**Purpose:** Submit, validate, review, execute, integrate, and watch prompt-driven tranche workflows with durable state.

**Subcommands:**
- `submit` — intake bundle to normalized bundle, manifest, inspection result, and durable tranche state
- `plan` — compile a prompt-pack YAML/JSON file into a tracked tranche manifest
- `inspect` — resolve reference freshness, gate satisfaction, lane readiness, scope overlap, and the recommended next action
- `design-review` — run the bounded proposer/critic/synthesizer loop before writable execution
- `prepare` — create managed worktrees for ready, claimable tranche lanes and record tranche artifacts
- `run` — dispatch ready, claimable tranche lanes through the bounded supervisor path with optional cross-model review
- `review` — run first-class tranche review with tier selection
- `integrate` — assess PR/check state and optionally record or execute merge decisions
- `watch` — poll durable tranche state in observer or driver mode
- `list` — list known tranche run states under `.aragora/tranches/`

**Key options:**
- `--intake <path|->` — intake bundle input for `tranche submit`
- `--from-prompts <path>` — prompt-pack input for `tranche plan`
- `--manifest <path>` — tranche manifest path (input for inspect/prepare/run, output override for plan)
- `--output <path>` — explicit output path for `tranche plan`
- `--lane-id <id>` — operate on one tranche lane
- `--all-completed` — review every completed lane
- `--all-ready` — operate on every ready, claimable lane
- `--all-mergeable` — integrate every mergeable lane
- `--approve` — permit integration execution when policy allows it
- `--driver` — claim the tranche driver role for `watch`
- `--interval <seconds>` — watch polling interval
- `--autonomy <mode>` — tranche autonomy mode (`adaptive`, `fire_and_forget`, `checkpoint`, `spectator`)
- `--tier <auto|1|2|3>` — explicit review tier selection
- `--skip-review` — skip post-run cross-model review
- `--json` — emit machine-readable payloads

**Examples:**
```bash
# Submit a loose intake bundle and persist tranche state
aragora swarm tranche submit \
  --intake docs/examples/pmf-tranche-prompt-pack.yaml \
  --autonomy adaptive \
  --json

# Compile a prompt bundle into a tranche manifest
aragora swarm tranche plan \
  --from-prompts docs/examples/pmf-tranche-prompt-pack.yaml \
  --output .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --json

# Inspect the resulting tranche against live repo / GitHub state
aragora swarm tranche inspect \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --json

# Run bounded design review before execution
aragora swarm tranche design-review \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --json

# Prepare one ready writable lane
aragora swarm tranche prepare \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --lane-id pmf_impl \
  --json

# Run the recommended ready lane and wait for completion + review
aragora swarm tranche run \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --json

# Review and integrate completed tranche work
aragora swarm tranche review \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --all-completed \
  --tier auto \
  --json

aragora swarm tranche integrate \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --all-mergeable \
  --approve \
  --json

# Watch durable tranche state and list known tranche runs
aragora swarm tranche watch \
  --manifest .aragora/tranches/pmf-tranche-example/tranche.yaml \
  --driver \
  --interval 5 \
  --json

aragora swarm tranche list --json
```

---

### `aragora triage`

**Purpose:** Inbox triage via adversarial debate with receipt-gated actions. The trust wedge entry point: fetch Gmail → debate → signed receipt → CLI approval → execute.

**Usage:** `aragora triage [run|status] [options]`

**Subcommands:**
- `run` — fetch and triage unread emails
- `status` — show triage session status

**Key options (run):**
- `--batch <n>` — number of emails to process (default: 5)
- `--auto-approve` — use narrow auto-approval policy (ARCHIVE/STAR/LABEL/IGNORE only)
- `--provider <name>` — LLM provider for triage debate
- `--rounds <n>` — number of debate rounds

**Examples:**
```bash
aragora triage run --batch 5
aragora triage run --batch 10 --auto-approve
aragora triage status
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
