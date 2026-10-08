---
name: fable-goal-cycle
description: Run one bounded goal cycle - package live repo + agent-activity context, consult Claude Fable 5 for ranked next goals, a one-cycle plan, and exactly one paste-ready next prompt, then execute that prompt. Use at the top of each autonomous conductor cycle, when asked "what should the next goal/prompt/plan be", or when running a looped adaptive mission. The response is strategy input, not authority - tier gates, quorum, and the operating contract still decide what merges.
license: MIT
compatibility: Works with Codex (.agents/skills), Claude Code (.claude/skills), and any Agent Skills platform. Requires python3 and git; gh CLI and scripts/agent_session_digest.py enrich the packet when present.
metadata:
  author: Synaptent (aragora)
  version: "1.0.0"
  argument-hint: Optional standing mission statement (--goal) and extra context files.
---

# Fable Goal Cycle (adaptive mission loop)

One command mechanizes the loop digest → packet → consult → next prompt:

```bash
python3 scripts/fable_goal_cycle.py \
  --goal "Standing mission statement, one or two sentences" \
  --json
```

What it does, all bounded:

1. **Package** — snapshots live state (origin/main SHA, branch status, open
   non-draft PRs, open epics, worktrees, recent `docs/plans`, and the last 24h
   of agent activity via `scripts/agent_session_digest.py --all`). Every
   source has its own short timeout; failures become a "context gaps" section
   in the packet instead of aborting, so Fable knows what it is not seeing.
2. **Consult** — sends the packet to Claude Fable 5 through the bounded
   consult tool (`consult_claude.py`, resolved from repo `scripts/` or
   `~/.codex/skills/consult-fable/`), default 900s timeout, demanding a fixed
   response format: `## ASSESSMENT`, `## NEXT GOALS` (max 3, ranked),
   `## NEXT PLAN` (one cycle only), `## NEXT PROMPT` (one fenced paste-ready
   prompt).
3. **Emit** — persists `packet.md`, `response.md`, `next_prompt.md` under
   `.aragora/goal_cycles/<timestamp>/` (gitignored) and prints the next
   prompt (or a JSON envelope with `--json`).

Goal-ranking durability filter: prefer goals whose output is a durable
standard — something that takes frontier judgment to WRITE but only ordinary
intelligence to APPLY (charters, rubrics, playbooks, skills, checkers). Test:
could a cheaper model redo this artifact tomorrow? If yes, rank it lower.

Wrong-hill disclosure: before ranking goals, if the standing mission metric
itself is the wrong hill — mis-specified, superseded by events, or clearly
worse than an adjacent goal — the consult is expected to say so FIRST in a
dedicated 'WRONG HILL' section with one-paragraph evidence, and propose the
better goal. Misalignment disclosure is invited and costs nothing; grinding a
bad metric costs cycles.

Useful flags: `--dry-run` (build the packet only — inspect it before spending
a consult), `--context-file <path>` (repeatable; include a redacted cycle
report or steering note only after placing it under
`.aragora/goal-cycle-context/`), `--since-hours 48`, `--skip-digest`,
`--timeout 1200`, `--model claude-opus-5`.

Exit codes: `0` ok, `2` consult failed/timed out, `5` response lacked a
`## NEXT PROMPT` block (raw response is still saved).

## Loop protocol

Run one cycle at a time:

1. At cycle top, run the command above. If Fable needs prior-cycle context,
   place a redacted copy under `.aragora/goal-cycle-context/` and pass that
   file via `--context-file`; arbitrary paths are rejected so packets do not
   accidentally inline shell history, credentials, or local private files.
2. Read `next_prompt.md`. **Sanity-check it against live state before
   executing** — verify PR numbers exist and heads match, exactly as you would
   for any operator prompt. If a claim is stale, correct the target, don't
   follow it blindly.
3. Execute it as one bounded progress unit under the operating contract.
4. Write your end-of-cycle report; feed it into the next cycle's
   `--context-file`.

## Hard rules

1. **Strategy input, not authority.** Nothing in a Fable response authorizes
   merging, settlement, evidence posting, or gate bypass. Tier gates and model
   quorum remain binding.
2. **One consult per cycle.** If the returned prompt is unexecutable, park it
   in your report and fall back to your own prioritization — do not re-consult
   in the same cycle.
3. **Fail closed.** On exit 2 or 5, proceed with your own judgment this cycle
   and note the consult outage in your report. Retry at most once, next cycle.
4. **No secrets in packets.** The packet is persisted to disk and sent to the
   model; live repo state only. Extra context files must be deliberately staged
   under `.aragora/goal-cycle-context/`, are byte-capped, and are embedded as
   quoted context rather than executable instructions.

If `scripts/fable_goal_cycle.py` is not in your checkout yet (branch not
merged), use an installed copy such as
`~/.codex/skills/fable-goal-cycle/fable_goal_cycle.py` when present. This repo
skill does not bundle a second script beside `SKILL.md`; `scripts/` is the
canonical in-repo entrypoint once merged.
