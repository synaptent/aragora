# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> This is the Survival Guide — your persistent memory across compactions and restarts. After any
> compaction event, read this file before touching code. If it contradicts what you think you
> remember, trust this file. Your memory is gone; this is not.
>
> Core pattern: the Ralph Loop — try, check, feed back, repeat, one sprint-sized batch at a time.
> In aragora the "check" is not just tests: it is the **aragora validation gate** — the repo's real
> proof-first loop (draft PR → required checks green → independent model-quorum evidence at the head
> → verified DecisionReceipt → merge-packet/settle clean → tier settlement) defined in
> `references/validation-gate-aragora.md`. The user plans and settles; you run the loop in the
> middle. You never admin-merge and never bypass a gate. Tier 0-2 settle by marking the draft ready
> for the protected squash + `aragora-merge-quorum` check (or a recorded merge-on-green preference);
> Tier 3 stops for human settlement; **Tier 4 stops for human PRE-APPROVAL before you implement it.**
>
> Recommended read order after compaction: survival guide → `.elves-session.json` → learnings →
> plan → execution log → `docs/AGENT_OPERATING_CONTRACT.md` → `docs/REVIEW_AUTHORITY_PRINCIPLES.md`.

---

## Mission

[2-3 sentences. Be specific about scope and the non-negotiable invariants — e.g. "must not change
the SDK public surface", "no schema migrations".]

---

## Run Control

- **Run mode:** [finite | open-ended]
- **Stop policy:** [deadline | explicit-user-stop | blocker-only]
- **User intent:** [exact controlling instruction, e.g. "Back at 8am ET"]
- **Checkpoint due by:** [YYYY-MM-DD HH:MM tz | none]
- **Checkpoint semantics:** [delivery target only | hard stop | none]
- **May continue after checkpoint:** [yes | no]
- **Actual stop conditions:** [one sentence]
- **Workspace ownership:** [dedicated worktree at `../aragora-<branch>`] — never shared with another active agent
- **Branch tip at start (collision tripwire):** [`git rev-parse HEAD` recorded at staging]
- **Merge policy:** [user-merges (default — you never admin-merge / never bypass a gate) | mark-ready-on-green (opt-in, Tier 0-2 only: mark the draft ready for the repo's protected squash + `aragora-merge-quorum` check; never `--admin`)]
- **Highest tier auto-settle allowed:** [Tier 2] — Tier 3 hard-stops for human settlement; Tier 4 hard-stops for human PRE-APPROVAL before implementation
- **Final-response policy:** [allowed | disallowed until stop]
- **Batch completion rule:** A batch is complete only after the full aragora gate passes (gate steps 1-9: draft PR, required checks green, head-grounded model quorum, verified receipt, clean merge-packet/settle, tier settlement) and the closing commit+push lands.
- **Re-read rule:** Immediately after every commit and push, re-read this survival guide.

---

## Stop Gate

> Rewrite in place. The explicit answer to "may I stop now?"

- **Planned batches remaining:** [N]
- **Batches blocked on human settlement (Tier 3-4):** [list, or none]
- **Stop allowed right now:** [yes | no]
- **Why:** [one sentence]
- **Next required action:** [one sentence]

If batches remain and no real stop condition applies, `Stop allowed right now` is `no`. A Tier 3-4
batch awaiting human settlement does **not** end the run if other unblocked batches remain — move
to the next unblocked batch. Only checkpoint-and-wait when every remaining batch is blocked.

---

## Forbidden Stop Reasons

Not valid reasons to stop while unblocked work remains: a checkpoint time was reached; a commit/push
succeeded; CI is green; a receipt was written; the user is silent; you wrote a summary; the current
batch is done but later batches remain; "this is a lot for one turn" (the volume is the point);
"this feels like a natural place to check in" (there is no one to check in with). Update docs,
commit, push, re-read this file, continue.

A genuine Tier 3-4 human-settlement block **is** a valid pause for *that batch only*.

---

## Non-Negotiables

- **Never admin-merge. Never bypass a gate.** Tier 0-2 settle by marking the draft ready for the
  protected squash + `aragora-merge-quorum` check (never `--admin`). Tier 3-4 require explicit human
  risk acceptance (`aragora/human-settlement`); **Tier 4 also requires human pre-approval BEFORE
  implementation** (and again before merge).
- **The batch gate is PR-grounded and uses real surfaces.** Local tests alone never close a batch:
  draft PR → `gh pr checks <pr> --required` green → `aragora review-pr <pr> --reviewer claude` +
  `--reviewer codex` evidence (`review-queue evidence-lint`) → verified receipt → `review-queue
  merge-packet` + `scripts/settle_one_pr.py` clean (only blocker == 'PR is draft').
- **Every batch produces a verified `DecisionReceipt`** (`aragora verify`). No receipt → not done.
- **Unresolved adversarial dissent blocks the batch.** Never silence a reviewer to clear the gate.
- **Never modify a test to make it pass.** Fix the code. Total test count never decreases.
- **Respect the operating contract's approval-required surfaces and auto-halts** (see gate doc).
- One run owns one branch + one worktree. Surprise tip move = collision → stop.
- No destructive git: `reset --hard`, `checkout .`, `clean -fd`, `push --force`, rebase on shared.
- Rollback tags namespaced by branch (`elves/<branch>/pre-batch-N`); never bare.
- Stage specific files; never `git add -A`. Scope ≤800 LOC delta per batch.
- Every closing commit carries `Co-authored-by: codex[bot]` (or `claude[bot]`).
- [Project-specific non-negotiable from the plan, e.g. "do not touch `review_queue.py`"]

---

## Launch Readiness

- [ ] Plan cleaned and saved to disk
- [ ] Survival guide updated from the current plan
- [ ] Learnings + execution log initialized with batch breakdown and preflight notes
- [ ] Dedicated worktree created; branch + checkout ownership confirmed; tip recorded
- [ ] Preflight run (`pre-commit run --all-files`, `mypy`, target `pytest` slice) and critical failures cleared
- [ ] `aragora --help` confirmed on PATH; review agents/API keys available (`aragora api-key list`)
- [ ] Each planned batch pre-classified by merge tier (0-4); Tier 3-4 flagged as human-settlement stops
- [ ] Run mode, return time, merge policy, and non-negotiables recorded above
- [ ] Stop Gate initialized with `Stop allowed right now: no`
- [ ] Launch prompt prepared for the next call

---

## Current Phase

> Rewrite in place. History belongs in the execution log.

**Status:** [Staging / Launch-ready / In progress / Awaiting human settlement / All batches complete / Blocked]
**Active batch:** [Batch N: Name — Tier X]
**What was just finished:** [one sentence incl. receipt path + settlement state]
**Single next action:** [one sentence]

---

## Next Exact Batch

**Batch:** [N: Name]
**Predicted merge tier:** [0-4] — if 3, ends in a human-settlement stop after the gate; if 4 (or an approval-required surface), HARD STOP for human PRE-APPROVAL *before* implementing
**Scope:**
- [Task 1]
- [Task 2]
**Acceptance criteria:**
- [ ] [Criterion]
**Risk:** [one sentence]
**Rollback tag:** `elves/<branch>/pre-batch-N` _(namespaced; create before starting)_

---

## Acceptance Checks (per batch)

Run the full gate in `references/validation-gate-aragora.md`. Summary:

- [ ] Tier 4 / approval-required batch? Human pre-approval obtained BEFORE implementing (else not started)
- [ ] Namespaced rollback tag created before the batch started (`elves/<branch>/pre-batch-N`)
- [ ] Local truth green: `pre-commit run --all-files`, `mypy` (no new errors vs `.mypy-baseline`), `pytest` slice; test count not decreased
- [ ] Draft PR opened; required checks green at exact head: `gh pr checks <pr> --required`
- [ ] Independent model-quorum evidence at exact head: `aragora review-pr <pr> --reviewer claude` + `--reviewer codex`; `review-queue evidence-lint` would_count true; evidence comment posted; quorum facts recorded (head SHA, families, independence, recommendation, dissent, dogfood)
- [ ] No unresolved dissent
- [ ] `DecisionReceipt` produced and `aragora verify` passes
- [ ] `review-queue merge-packet --pr <pr> --json` satisfied (not blocked except draft); `scripts/settle_one_pr.py --pr <pr> --json` blockers == `['PR is draft']`
- [ ] Merge tier classified; Tier 0-2 → mark ready + protected squash (never `--admin`); Tier 3 paused for human settlement; Tier 4 paused for human pre-approval (already gated before impl)
- [ ] Execution log updated (PR #, SHA, commands, results, required-checks, quorum, receipt path, merge-packet/settle, tier, settlement state)
- [ ] Survival guide Current Phase / Stop Gate / Next Exact Batch updated
- [ ] Closing commit (with `Co-authored-by:` trailer) + push done before any later work
- [ ] Survival guide re-read immediately after that push

---

## Tool Configuration (aragora ground truth)

```yaml
# --- Local truth ---
lint: pre-commit run --all-files
typecheck: mypy aragora        # compare against .mypy-baseline; no new errors
test: pytest                   # narrow to the relevant slice per batch
mypy-baseline: .mypy-baseline

# --- Required CI checks (must be green at exact PR head) ---
required-checks-cmd: gh pr checks <pr> --required
required-checks: [lint, typecheck, sdk-parity, "Generate & Validate", "TypeScript SDK Type Check", aragora-merge-quorum]

# --- Independent model-quorum evidence (head-grounded; replaces github-pr-comments) ---
review-claude: aragora review-pr <pr> --reviewer claude --json   # Anthropic family
review-codex:  aragora review-pr <pr> --reviewer codex --json    # OpenAI family (distinct)
evidence-lint: aragora review-queue evidence-lint --pr <pr> --head-sha <sha> --body-file <file> --json
review-gate-workflow: aragora-review-gate.yml      # advisory
merge-quorum-workflow: aragora-merge-quorum.yml    # enforcing, required check on main
# Optional adjunct only (not countable; real flags): aragora ask "<prompt>" --agents anthropic-api,openai-api,grok --decision-integrity

# --- Receipts ---
receipt-verify: aragora verify <receipt.json>      # --format json available
receipt-dir: .aragora/receipts

# --- Authorization surfaces (read-only unless marked OPERATOR ONLY; none of these is a merge) ---
merge-packet: aragora review-queue merge-packet --pr <pr> --json
settle-dry-run: python3 scripts/settle_one_pr.py --pr <pr> --json   # expect blockers == ['PR is draft']
settle-tier4-check: python3 scripts/settle_tier4_pr.py --check --pr <pr> --head <sha>   # read-only exact-head Tier 4 gate evaluation; mutates nothing
settle-tier4-settle-only: python3 scripts/settle_tier4_pr.py --settle-only --pr <pr> --head <sha> --trusted-operator-login <login>   # OPERATOR ONLY: exact-head settlement mutation (comment + status); never merges
# settle_tier4_pr.py --merge-apply is a legacy ADMIN-BYPASS mode (`gh pr merge --admin`): FORBIDDEN — never run, never recommend, never packet it
protected-merge: gh pr merge <pr> --squash --match-head-commit <sha>   # the ONLY merge route, after the required operator settlement
record-settlement: aragora review-queue record-settlement   # or: aragora review-queue act <pr> --approve|--defer

# --- Settlement / tiers ---
tier-policy-doc: docs/REVIEW_AUTHORITY_PRINCIPLES.md
human-settlement-signal: aragora/human-settlement   # commit status set by operator
approvals-dir: .approvals

# --- Notification ---
notification: pr-comment        # or slack-webhook via ELVES_SLACK_WEBHOOK
```

### Tier 4 settlement helper modes (`scripts/settle_tier4_pr.py`)

The helper takes exactly one of three mutually exclusive modes. They are not interchangeable:

- **`--check`** — read-only. Evaluates the exact-head Tier 4 gate (head match, counted model
  evidence, required checks, the operator's settlement markers, branch-protection preflight) and
  prints `ok`/blockers. It writes nothing to GitHub. This is the only mode you run.
- **`--settle-only`** — an operator mutation, never yours. Refuses unless the exact-head
  preconditions hold AND the invoking `gh` login is in the `--trusted-operator-login` allowlist
  with admin/OWNER authority; then posts the `Tier-4 Human Settlement Authorization` comment and
  the `aragora/human-settlement` success status on that head. It never merges.
- **`--merge-apply`** — legacy admin-bypass. It runs `gh pr merge --squash --admin` on the settled
  head (plus optional branch-protection reconcile). **Forbidden:** do not run it, do not recommend
  it, do not put it in a settlement packet. Mentioning it here is a warning, not an instruction.

After the required operator settlement, the merge is the normal protected route and nothing else:
`gh pr merge <pr> --squash --match-head-commit <sha>`. That command honours branch protection
and the `aragora-merge-quorum` check; `--admin` in any form bypasses them and is never used.

---

## Rollback and Safety Rules

1. Tag before every batch, namespaced by branch so remote tags never collide across runs:
   `B=$(git rev-parse --abbrev-ref HEAD); git tag "elves/$B/pre-batch-N" && git push origin "elves/$B/pre-batch-N"`.
2. Never force-push or rebase the working branch (invalidates rollback tags).
3. Never admin-merge and never bypass a gate. Tier 0-2 settle by marking the draft ready for the protected squash; Tier 3-4 never auto-settle (Tier 4 also needs pre-approval before implementation).
4. On serious breakage, branch from the last good tag (`git checkout -b recovery/from-pre-batch-N "elves/$B/pre-batch-N"`), document in the execution log, stop. Leave the original branch intact.
5. Stage specific files; know what you commit.
6. Surprise branch-tip move = collision → stop, do not commit on top, surface to user.

---

## After Any Compaction

1. Read this file (doing it now).
2. Read Run Control + Stop Gate. Recover run mode, stop policy, checkpoint semantics, and which batches are blocked on human settlement.
3. Read `.elves-session.json` (current batch, receipt paths, test baseline, `continuation_guard`).
4. Read learnings, then the plan (compare hash), then the execution log (last completed batch + last receipt + last settlement state).
5. Skim `docs/AGENT_OPERATING_CONTRACT.md` auto-halts and `docs/REVIEW_AUTHORITY_PRINCIPLES.md` tiers.
6. If `continuation_guard.stop_allowed` is false, continue without re-deciding.
7. Identify the first unblocked incomplete batch and resume. Do not redo completed batches — a verified receipt in the log means done.

---

# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART
