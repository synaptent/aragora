# Aragora Agents

Aragora is the control plane for multi-agent vetted decisionmaking across organizational knowledge and channels. It implements structured vetted decisionmaking through a society of heterogeneous AI agents. This document describes the agent system architecture.

> **Operating Contract:** Autonomous CLI agents (Claude Code, Codex CLI, Factory Droid,
> Aider, the agent-bridge harnesses) working *in* this repository operate under
> [`docs/AGENT_OPERATING_CONTRACT.md`](docs/AGENT_OPERATING_CONTRACT.md) — the
> always-allowed / approval-required matrix, the "break unreleased branch behavior
> freely; never break main / public API / release flow / CI" rule, and main-red
> incident mode. That contract governs *how* agents execute against the repo. This
> document describes *what* agents are registered as runtime debate participants
> (the 46-agent registry).

## Worktree Autopilot (High-Churn Sessions)

When many agents are committing concurrently, use disposable worktrees with frequent reconciliation.

- Start sessions with `./scripts/codex_session.sh` (or `make codex-session`).
  This writes an active-session lock so background maintenance skips in-use worktrees.
- Do not delete side worktrees with raw `git worktree remove` plus `rm -rf`.
  Inspect/remove them with `python3 scripts/safe_worktree_cleanup.py` so active-session locks and open PR branches block accidental deletion.
- Auto-heal unexpected worktree/branch drift with:
  `python3 scripts/codex_worktree_autopilot.py ensure --agent codex --base main --reconcile --print-path`
- Prefer one-shot upkeep during rapid churn:
  `python3 scripts/codex_worktree_autopilot.py maintain --base main --strategy merge --ttl-hours 24`
- Reconcile managed sessions with:
  `python3 scripts/codex_worktree_autopilot.py reconcile --all --base main`
- Remove stale managed worktrees with:
  `python3 scripts/codex_worktree_autopilot.py cleanup --base main --ttl-hours 24`
- Optional macOS daemon: `make worktree-maintainer-install` for periodic background reconcile-only upkeep.

## Automation Operating Rules

For Codex-driven automations in this repo, default to maximum safe autonomy. Finish the bounded task when the next action is clear, and only stop when the remaining step is irreversible, human-gated, or materially unsafe.

- Use the shared automation merge contract in `docs/briefs/automation-merge-contract.md`.
  Before publishing local Codex app automation or Aragora boss-loop worker branches, run `bash scripts/automation_pr_preflight.sh origin/main HEAD` from the branch worktree, or run it against the explicit worker branch.
- Prefer execution over advice:
  verify the issue, make the smallest credible fix, validate it, commit it, push it, open the PR, and leave the inbox or memory handoff in the same run when the task is otherwise ready.
- Do not stop at the first blocked path:
  inspect `--help`, adapt to the actual helper interface, and try the next practical route before declaring a blocker.
- Use layered fallbacks:
  move between shell git/gh, MCP connectors, local repo inspection, and browser flows when one surface is degraded.
- Do not launch Factory/Droid in interactive Auto Off mode for normal Aragora work.
  Prompted Droid/Factory lanes should go through `scripts/tmux_session_launcher.sh`
  or `scripts/agent_bridge.py launch`, which route them through `droid exec --auto high`.
  Only use `ARAGORA_ALLOW_DROID_AUTO_OFF=1` for an explicit manual-debugging exception.
- Recover cleanly from partial failure:
  if publish or inbox delivery fails, still leave a clean committed branch or an exact handoff with the compare URL, blocker, and next action.
- Treat founder guidance as strong but verify it:
  if founder memory is fresh but imperfectly structured, verify the recommendation directly on `origin/main` instead of discarding it mechanically.
- Keep everything reversible:
  use disposable worktrees, branch-scoped commits, additive edits, and non-destructive cleanup. Never delete worktrees or branches with uncommitted changes, unique commits, or open PRs.
- Keep scope bounded:
  prefer measurable improvements on live paths over speculative breadth, and use Aragora itself when it improves decisions without dominating a small direct fix.
- Before lane work, check your operator-steering mailbox with
  `python3 scripts/read_operator_steering.py --lane-id <LANE_ID> --json` (or
  `--pr` / `--branch` when that is the only selector you know). If you read a
  message, write an outcome receipt with `--outcome obeyed|held|stale|superseded|blocked|completed`
  before mutating lane state. `_read_receipts/` is proof-of-read/outcome only;
  it is not an ack protocol, and top-level message files remain pending until a
  future explicit ack/move protocol exists.
- Active lanes must expose their next action and owner liveness. Claim/refresh
  lanes with `next_action`, `last_heartbeat_at`, and `last_steering_outcome`;
  long-running harnesses should also run `python3 scripts/agent_heartbeat.py`
  so other sessions can see owner_session, pid/thread hints, cwd, worktree,
  branch, PR number, and last_seen_at without opening raw transcripts.
- Do not paste old transcripts or accumulated logs into new prompts. Use
  `python3 scripts/build_next_prompt.py` plus the live queue/owner tools to
  rebuild concise, owner-specific prompts that begin with mailbox checking.
- Resolve stale conflict rows only through
  `python3 scripts/resolve_lane_conflicts.py --dry-run` and, when safe,
  `--apply`; it marks conflicts `superseded` with append-only receipts rather
  than deleting or rewriting unrelated ownership rows.
- Tier 4 merge/protection work can be prepared autonomously but not applied
  without exact-head, repo-visible operator settlement. Use
  `python3 scripts/settle_tier4_pr.py --check --pr <N> --head <SHA>` before
  any Tier 4 merge/protection mutation.

### Amend-guard helper

Before running `git commit --amend` (or any rebase that rewrites the
current tip), check that HEAD is not already published. Run
`bash scripts/guard_amend_pushed.sh` from the branch worktree; it exits
non-zero with `AMEND-BLOCKED: ...` when `HEAD` equals the
`origin/<branch>` tip and exits `0` when the branch is local-only or
ahead of the remote. Pass `--remote NAME` / `--branch NAME` to override
the defaults. This implements rule **R19** ("never `--amend` a pushed
commit") from the v12/v13 lessons; soft-reset and re-commit instead.

## Agent Types

Aragora currently registers 46 agent types across CLI, direct API, OpenRouter, local inference, and external framework proxies. Use `list_available_agents()` to see the full registry at runtime. Server-side validation uses the allowlist in `aragora/config/settings.py` (`ALLOWED_AGENT_TYPES`, 35 types as of 2026-06-06). Entries marked **opt-in** are registered but not allowlisted by default.

### CLI-Based Agents (allowlisted)

| Agent Type | CLI Tool | Default Model | Notes |
|------------|----------|---------------|-------|
| `claude` | `claude` (claude-code) | claude-fable-5 | Fable 5, 1M context, 128K output (subscription-priced on this surface) |
| `codex` | `codex` | gpt-4.1-codex | GPT-4.1 Codex, 1M context |
| `openai` | `openai` | gpt-4.1 | GPT-4.1, 1M context |
| `gemini-cli` | `gemini` | gemini-3.1-pro-preview | Gemini 3.1 Pro, 1M context |
| `grok-cli` | `grok` | grok-4-latest | Grok 4, 256K context |
| `grok-build` | `grok` (Grok Build CLI) | grok-build | Opt-in subscription CLI; resolves `~/.grok/bin/grok` or `ARAGORA_GROK_BUILD_BIN` |
| `antigravity` | `agy` | gemini-3.5-flash | Opt-in subscription CLI; resolves `~/.antigravity/bin/agy` or `ARAGORA_ANTIGRAVITY_BIN` |
| `qwen-cli` | `qwen` | qwen3-coder | |
| `deepseek-cli` | `deepseek` | deepseek-v4-pro | Requires `DEEPSEEK_API_KEY` |
| `kilocode` | `kilocode` | provider-specific | Defaults to `openrouter/google/gemini-3.1-pro-preview` via `provider_id` |

### Direct API Agents (cloud)

| Agent Type | Provider | Default Model | Env Var | Allowlist |
|------------|----------|---------------|---------|-----------|
| `anthropic-api` | Anthropic | claude-opus-5 | `ANTHROPIC_API_KEY` | allowlisted |
| `openai-api` | OpenAI | gpt-4.1 | `OPENAI_API_KEY` | allowlisted |
| `gemini` | Google | gemini-3.1-pro-preview | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | allowlisted |
| `grok` | xAI | grok-4-latest | `XAI_API_KEY` or `GROK_API_KEY` | allowlisted |
| `mistral-api` | Mistral | mistral-large-2512 | `MISTRAL_API_KEY` | allowlisted |
| `codestral` | Mistral | codestral-latest | `MISTRAL_API_KEY` | opt-in |

### Local & Legacy Direct Agents

| Agent Type | Provider | Default Model | Env Var | Allowlist |
|------------|----------|---------------|---------|-----------|
| `ollama` | Local Ollama | llama3.2 | `OLLAMA_HOST` (optional) | allowlisted |
| `lm-studio` | LM Studio | local-model | `LM_STUDIO_HOST` (optional) | opt-in |
| `kimi-legacy` | Moonshot | moonshot-v1-8k | `KIMI_API_KEY` | opt-in |

### OpenRouter Agents (allowlisted)

All OpenRouter agents require `OPENROUTER_API_KEY`.

| Agent Type | Default Model | Description |
|------------|---------------|-------------|
| `deepseek` | deepseek/deepseek-v4-pro | DeepSeek V4 Pro |
| `deepseek-r1` | deepseek/deepseek-v4-pro | DeepSeek V4 Pro compatibility alias |
| `llama` | meta-llama/llama-3.3-70b-instruct | Llama 3.3 70B |
| `llama4-maverick` | meta-llama/llama-4-maverick | Llama 4 Maverick |
| `llama4-scout` | meta-llama/llama-4-scout | Llama 4 Scout |
| `mistral` | mistralai/mistral-large-2411 | Mistral Large |
| `qwen` | qwen/qwen3.8-max | Qwen 3.8 Max |
| `qwen-max` | qwen/qwen3.8-max | Qwen 3.8 Max |
| `qwen-3.5` | qwen/qwen3.5-plus-02-15 | Qwen 3.5 Plus |
| `yi` | 01-ai/yi-large | Yi Large |
| `kimi` | moonshotai/kimi-k2-0905 | Kimi K2 |
| `kimi-thinking` | moonshotai/kimi-k2-thinking | Kimi K2 Thinking |
| `sonar` | perplexity/sonar-reasoning | Sonar (reasoning + web search) |
| `command-r` | cohere/command-r-plus | Command R+ (RAG-optimized) |
| `jamba` | ai21/jamba-1.6-large | Jamba (SSM-Transformer hybrid) |
| `fusion` | openrouter/fusion | OpenRouter Fusion multi-model council+judge endpoint (opt-in, not a quorum family) |
| `openrouter` | deepseek/deepseek-v4-pro | Generic OpenRouter default |

### External Framework Proxies

| Agent Type | Default Model | Env Var | Notes |
|------------|---------------|---------|-------|
| `external-framework` | external | `EXTERNAL_FRAMEWORK_URL`, `EXTERNAL_FRAMEWORK_API_KEY` (optional) | Generic proxy for external frameworks |
| `openclaw` | openclaw | `OPENCLAW_URL`, `OPENCLAW_API_KEY` | Allowlisted OpenClaw integration |
| `crewai` | crewai | `CREWAI_URL`, `CREWAI_API_KEY` | CrewAI server integration |
| `autogen` | autogen | `AUTOGEN_URL`, `AUTOGEN_API_KEY` | AutoGen Studio integration |
| `langgraph` | langgraph | `LANGGRAPH_URL`, `LANGGRAPH_API_KEY` | LangGraph Cloud/self-hosted |

### Fine-Tuned (Tinker) Agents (opt-in)

| Agent Type | Default Model | Env Var |
|------------|---------------|---------|
| `tinker` | llama-3.3-70b | `TINKER_API_KEY` |
| `tinker-llama` | llama-3.3-70b | `TINKER_API_KEY` |
| `tinker-qwen` | qwen-2.5-72b | `TINKER_API_KEY` |
| `tinker-deepseek` | deepseek-v3 | `TINKER_API_KEY` |

### Built-In

| Agent Type | Default Model | Notes |
|------------|---------------|-------|
| `demo` | demo | Offline demo agent for local/testing |

## Agent Creation

Use the factory function to create agents:

```python
from aragora.agents import create_agent

# CLI agents
agent = create_agent("claude", name="claude_proposer", role="proposer")
agent = create_agent("codex", name="codex_critic", role="critic")

# API agents
agent = create_agent("anthropic-api", name="claude_api", role="synthesizer", api_key="...")
agent = create_agent("gemini", name="gemini_judge", role="synthesizer", api_key="...")
agent = create_agent("ollama", name="local_agent", model="llama3.2")
```

## Agent Roles

Each agent has a role that determines its behavior in debates:

- **proposer** - Generates initial responses to tasks
- **critic** - Analyzes and critiques other proposals
- **synthesizer** - Produces final consensus outputs
- **judge** - Arbiter role for judge-based consensus
- **analyst** - Deep analysis / research-focused role
- **implementer** - Implements or executes plans
- **planner** - Breaks down tasks and sequences work

## Core Agent Interface

All agents implement the abstract `Agent` class from `aragora/core/`:

```python
class Agent(ABC):
    name: str
    model: str
    role: str  # "proposer", "critic", "synthesizer", "judge", "analyst", "implementer", "planner"
    system_prompt: str
    stance: str  # "affirmative", "negative", "neutral"

    async def generate(self, prompt: str, context: list[Message] = None) -> str
    async def critique(self, proposal: str, task: str, context: list[Message] = None) -> Critique
    async def vote(self, proposals: dict[str, str], task: str) -> Vote
```

## Agent Personas

Agents can have personas with expertise domains and personality traits:

**Expertise Domains:**
- security, performance, architecture, testing, error_handling
- concurrency, api_design, database, frontend, devops, documentation, code_style

**Personality Traits:**
- thorough, pragmatic, innovative, conservative
- diplomatic, direct, collaborative, contrarian

```python
from aragora.agents import PersonaManager

personas = PersonaManager("aragora_personas.db")
personas.create_persona(
    "claude_proposer",
    description="Visionary architect of solutions",
    traits=["innovative", "collaborative"],
    expertise={"architecture": 0.8, "api_design": 0.7},
)
```

## Truth-Grounded Identities

Agents maintain evidence-based identities through position tracking:

- **Position Ledger** - Records every claim, confidence level, and outcome
- **Calibration Scores** - Tracks prediction accuracy per domain
- **Relationship Metrics** - Rivalry, alliance, and influence scores between agents

## Debate Orchestration

The `Arena` class orchestrates multi-agent debates:

```python
from aragora.agents import create_agent
from aragora.debate import Arena, DebateProtocol
from aragora.core import Environment
from aragora.memory import CritiqueStore

agents = [
    create_agent("anthropic-api", name="proposer", role="proposer"),
    create_agent("openai-api", name="critic", role="critic"),
    create_agent("gemini", name="judge", role="synthesizer"),
]

env = Environment(task="Design a rate limiter", max_rounds=3)
protocol = DebateProtocol(rounds=3, consensus="majority")
memory = CritiqueStore("debates.db")

arena = Arena(env, agents, protocol, memory)
result = await arena.run()
```

### Debate Topologies

- **all-to-all** - Everyone critiques everyone
- **round-robin** - Deterministic cycle
- **ring** - Circular neighborhood critiques
- **star** - Hub agent central to all critiques
- **sparse** - Random subset based on sparsity parameter
- **random-graph** - Randomized connections

### Consensus Mechanisms

- **majority** - Plurality vote wins
- **unanimous** - All agents must agree
- **judge** - Single judge synthesizes best elements
- **none** - No voting, collect all proposals

## ELO Ranking System

Agents are ranked using an ELO-based skill system:

```python
from aragora.ranking import EloSystem

elo = EloSystem("aragora_elo.db")
elo.record_match(
    debate_id="debate_123",
    winner="claude_proposer",
    participants=["claude_proposer", "codex_critic"],
    domain="architecture",
    scores={"claude_proposer": 0.8, "codex_critic": 0.6},
)
```

## Nomic Loop Integration

The nomic loop (`scripts/nomic_loop.py`) is a self-improving cycle that leverages all agent features:

### Integrated Features

| Feature | Integration Point |
|---------|------------------|
| **Belief Analysis** | Runs on every debate, identifies contested/crux claims |
| **Capability Probing** | Probes agents before debates, weights votes by reliability |
| **Counterfactual Branches** | Resolves deadlocks by exploring alternative assumptions |
| **ELO Team Selection** | Selects agents by domain-specific expertise scores |
| **Evidence Staleness** | Checks claims against changed files, flags for re-debate |
| **Persona Evolution** | Applies winning experiment variants to agent traits |
| **Position Tracking** | Records all claims with outcomes for calibration |

### NomicIntegration Hub

The `NomicIntegration` class coordinates advanced features:

```python
from aragora.nomic.integration import create_nomic_integration

integration = create_nomic_integration(
    elo_system=elo,
    enable_probing=True,
    enable_belief_analysis=True,
    enable_staleness_check=True,
    enable_counterfactual=True,
)

# After debate
analysis = await integration.full_post_debate_analysis(
    result,
    arena=arena,
    claims_kernel=claims_kernel,
    changed_files=changed_files,
)
```

## Key Files

| File | Purpose |
|------|---------|
| `aragora/core/` | Core abstractions (Agent, Message, Critique, Vote, DebateResult) |
| `aragora/agents/base.py` | Agent factory and type definitions |
| `aragora/agents/cli_agents.py` | CLI-based agent implementations |
| `aragora/agents/api_agents.py` | API-based agent implementations |
| `aragora/agents/personas.py` | Persona management and traits |
| `aragora/agents/laboratory.py` | Emergent persona evolution experiments |
| `aragora/agents/grounded.py` | Truth-grounded identity tracking |
| `aragora/agents/truth_grounding.py` | Position ledger for evidence tracking |
| `aragora/debate/orchestrator.py` | Arena class and DebateProtocol |
| `aragora/nomic/integration.py` | NomicIntegration feature coordination hub |
| `aragora/ranking/elo.py` | ELO skill ranking system |
| `aragora/memory/store.py` | CritiqueStore pattern database |
| `scripts/nomic_loop.py` | Self-improving nomic loop orchestrator |

## Theoretical Foundation

Aragora implements Hegelian dialectics:

| Concept | Implementation |
|---------|----------------|
| Thesis → Antithesis → Synthesis | Propose → Critique → Revise loop |
| Aufhebung (sublation) | Judge synthesizes best elements |
| Contradiction as motor | Critiques drive improvement |
| Truth as totality | Emerges from multi-perspectival synthesis |
