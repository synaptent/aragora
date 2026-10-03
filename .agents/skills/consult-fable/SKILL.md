---
name: consult-fable
description: Bounded advisory consult of Claude Fable 5 from inside the aragora repo. Use when you are stuck on prioritization ("what should I work on next?"), need a second opinion on a design or a reviewer deadlock, want a plan sanity-checked, or were asked to "ask Claude / Fable" something. Runs scripts/consult_claude.py with a per-attempt timeout and a derived total timeout, strict empty MCP config for CLI calls, and fail-closed backend attempts. Advice is input, not authority — it cannot approve merges, settle quorum, or override gates.
license: MIT
compatibility: Works with Codex (.agents/skills), Claude Code (.claude/skills), and any Agent Skills platform. Requires python3; uses the local `claude` CLI by default, supports an explicitly selected local VibeProxy for exact Claude models, and uses paid APIs only when explicitly requested.
metadata:
  author: Synaptent (aragora)
  version: "1.1.0"
  argument-hint: The question to ask, or a path to a prompt file.
---

# Consult Fable (bounded Claude Fable 5 advisory)

Ask Claude Fable 5 a question and get an answer back through bounded backend
attempts. This replaces ad-hoc `timeout 120 claude -p "..."` calls, which hang
or expire with no output. The default backend order is `claude-fable-5` then
`claude-opus-5` through the local `claude` CLI. CLI attempts pass the prompt
via stdin and use an empty MCP configuration. Explicit
`ARAGORA_MODEL_TRANSPORT=vibeproxy-prefer` tries those exact models through
VibeProxy before the CLI; `vibeproxy-required` fails closed instead of using
CLI or paid API fallbacks.

`--timeout` is the maximum for one backend attempt. By default, the total
consult budget is derived from every enabled attempt, so a full-timeout
VibeProxy attempt cannot consume the CLI fallback budget. Pass
`--overall-timeout` to set an explicit cap shared across all attempts.
Prompts from inline args, `--prompt-file`, and stdin are capped at 512 KiB and
are rejected before any backend attempt, so oversized context cannot
silently burn API tokens when `--api-fallback` is enabled. The cap also applies
to programmatic `consult()` calls after any `--system`/system preamble is
combined with the user prompt.

API fallback is off by default because it can consume Anthropic API credits or
billing when `ANTHROPIC_API_KEY` or aragora secrets are configured. Use
`--api-fallback` only when paid API fallback is acceptable; unsupported
CLI-only model ids such as `claude-fable-5` are skipped for direct API calls.
If no API key is available, the API backend records a normal failed attempt in
the JSON envelope instead of being omitted.

## How to invoke

From the repo root (any worktree):

```bash
# Inline question, defaults: model claude-fable-5, timeout 600s per attempt
# Default total budget is timeout multiplied by enabled backend attempts.
python3 scripts/consult_claude.py "One-paragraph question with the live state inlined."

# Long prompt from a file, machine-readable result
python3 scripts/consult_claude.py --prompt-file /tmp/question.md --json

# Require the local proxy and prohibit transport fallback
ARAGORA_MODEL_TRANSPORT=vibeproxy-required \
  python3 scripts/consult_claude.py --json "Reply with exactly READY"

# Prefer the local proxy, then fall back to the default CLI path
ARAGORA_MODEL_TRANSPORT=vibeproxy-prefer \
  python3 scripts/consult_claude.py --json "Reply with exactly READY"

# Bigger total budget for a hard question
python3 scripts/consult_claude.py --timeout 300 --overall-timeout 1200 --prompt-file /tmp/question.md

# Explicit paid API fallback after CLI attempts fail
python3 scripts/consult_claude.py --api-fallback --prompt-file /tmp/question.md
```

`--json` returns `{ok, model, backend, elapsed_s, text, attempts}`. Exit codes:
`0` ok, `2` timed out, `3` no prompt, `4` all backends failed or the explicit
overall budget was exhausted before all fallback attempts could run, `64`
usage/config error. In JSON, budget exhaustion is reported as
`budget_exhausted: true`, distinct from backend `timed_out: true`.

If `scripts/consult_claude.py` does not exist in your checkout yet, use an
installed user skill copy such as `~/.codex/skills/consult-fable/consult_claude.py`.
The tracked repo skill itself expects the tracked repo script.

## Writing a good consult prompt

Fable has **no access to your session state**. Inline everything it needs:

- The decision you are facing and the 2-4 options you see.
- Live facts, verified this cycle: PR numbers with head SHAs, gate/quorum
  state, dissent findings, owner state. Never paste stale transcript claims.
- Constraints that bind you (operating contract tier limits, no `--admin`,
  shared-root read-only, anti-treadmill rules).
- Ask for a **single recommendation with reasoning**, not a survey.

For "what should I work on next?" consults, a good shape is: list the
candidate progress units with one line of live state each, state the
anti-treadmill rules that apply, and ask Fable to pick exactly one and say why.

## Hard rules

1. **Advisory only.** The answer is one input to your decision. It is never
   authority to merge, settle, post evidence, or bypass a gate. Verify any
   factual claim in the answer against live repo state before acting on it.
   VibeProxy does not create a reviewer family, and this skill's output is not
   countable merge-quorum evidence.
2. **One consult per decision.** Do not loop consults on the same question;
   if the answer doesn't unblock you, the blocker is information, not advice.
3. **Bounded always.** Keep the default 600s per-attempt timeout or raise it
   explicitly; never wrap this tool in an outer retry loop.
4. **No secrets in prompts.** Inline repo state, not credentials or tokens.

## Failure handling

- Exit 2 (timeout) or 4 (all backends failed): report the consult as
  unavailable and proceed with your own judgment. Do not retry more than once.
- Exit 64 is a usage or configuration error. Correct the invalid argument or
  `ARAGORA_MODEL_TRANSPORT` value before retrying; do not treat it as backend
  unavailability.
- In `vibeproxy-prefer`, proxy unavailability is recorded in `attempts` before
  the CLI fallback runs. In `vibeproxy-required`, it is the final failure.
- If only the API backend fails with a missing-key error, the local `claude`
  CLI is the expected path; check `which claude` before concluding anything.
