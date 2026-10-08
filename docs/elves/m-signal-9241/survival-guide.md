# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> This is the Survival Guide — persistent memory across compactions. After any compaction,
> read this before touching code. Read order: this file → learnings.md → the plan
> (docs/plans/2026-07-11-m-signal-reviewer-integrity.md) → execution-log.md →
> docs/AGENT_OPERATING_CONTRACT.md → docs/REVIEW_AUTHORITY_PRINCIPLES.md.

---

## Mission

Fix reviewer-evidence integrity and settlement transport (issue #9241, program #9039 campaigns
4+5): no-verdict/malformed reviews must never count toward merge quorum; reviewers get full-file
grounding; credential walls fail fast and route real fallback; GitHub access becomes quota-aware.
Invariants: NEVER touch aragora/cli/commands/review_queue.py (Tier-4 merge authority), never edit
.github/workflows (design notes only), never weaken what counts as valid evidence.

---

## Run Control

- **Run mode:** finite (7 batches: B1-B7)
- **Stop policy:** blocker-only; checkpoint is a delivery target
- **User intent:** "do the elves overnight run" on #9241; founder offline until ~08:00 CT 2026-07-12
- **Checkpoint due by:** 2026-07-12 08:00 CT — delivery target only
- **May continue after checkpoint:** yes
- **Actual stop conditions:** all batches complete/parked, or every remaining batch blocked on human settlement, or operating-contract auto-halt
- **Workspace ownership:** dedicated worktree `<repo-root>/.worktrees/elves-m-signal-9241` — confirmed unshared
- **Branch tip at start (collision tripwire):** 8b1144146d52128e979787e9dded85e2c8346d29
- **Merge policy:** user-merges (NEVER merge; self-approval boundary also enforced by harness)
- **Highest tier auto-settle allowed:** Tier 2. B1/B2 are Tier 3 → implement, gate, PARK packet.
- **Final-response policy:** allowed only at checkpoint/stop
- **Batch completion rule:** aragora gate steps 1-7 pass + closing commit/push lands
- **Re-read rule:** re-read this file after every commit+push
- **WIP cap:** ≤3 open PRs from this run (program cap 6 shared with droid missions #9239/#9242)

---

## Stop Gate

- **Planned batches remaining:** 3 (B5-B7, WIP-gated)
- **Batches blocked on human settlement (Tier 3-4):** B1+B2 (PR #9249, parked, single packet at fefa9c91ef)
- **Stop allowed right now:** no
- **Why:** B2-B7 unblocked work remains
- **Next required action:** implement B2 (truncation + PASS-with-blocking-findings)

---

## Forbidden Stop Reasons

Checkpoint reached; commit/push succeeded; CI green; receipt written; user silent; summary
written; current batch done but later batches remain; "a lot for one turn"; "natural place to
check in". A genuine Tier 3-4 settlement block pauses THAT BATCH only — move to the next.

---

## Non-Negotiables

- Never merge; never approve a merge; never record settlement for Tier 3-4.
- Every batch: verified DecisionReceipt (aragora verify) or it is not done.
- Unresolved adversarial dissent blocks the batch (parking is the documented disposition).
- Never modify a test to make it pass. Total test count never decreases.
- DO NOT TOUCH: aragora/cli/commands/review_queue.py, .github/workflows/*, CLAUDE.md,
  scripts/nomic_loop.py, .env, secrets. Workflow changes = design notes for founder.
- Stage specific files, never `git add -A`. ≤800 LOC delta per batch.
- Closing commits carry `Co-authored-by: claude[bot]`.
- No destructive git. Surprise tip move = collision → stop.
- GitHub API budget is shared: batch gh calls, prefer REST, one PR-inventory fetch per cycle
  (B5 exists because we exhausted it today).

---

## Launch Readiness

- [x] Plan cleaned and saved: docs/plans/2026-07-11-m-signal-reviewer-integrity.md
- [x] Survival guide (this file)
- [x] Learnings + execution log initialized
- [x] Dedicated worktree + branch elves/m-signal-9241; tip 8b1144146d recorded
- [x] Preflight run: mypy(venv) clean on target module; 304 quorum-slice tests pass
- [x] aragora --help confirmed on PATH
- [x] Batches pre-classified: B1/B2 Tier 3 (park), B3-B7 Tier 2
- [x] Run mode, merge policy, non-negotiables recorded
- [x] Stop Gate initialized: Stop allowed = no
- [x] Launch prompt handed to user

---

## Current Phase

**Status:** In progress
**Active batch:** none (B5-B7 held by program WIP cap until settlements land)
**What was just finished:** B4 closed after 4 gate rounds — final: claude+openai PASS, zero dissent at 68bd60fb12; PR #9249 packet parked for founder
**Single next action:** after founder settles #9249 (WIP frees), start B5 (transport) with tag pre-batch-5

---

## Next Exact Batch

**Batch:** B1: no-verdict reviews must never count
**Predicted merge tier:** 3 — ends in a PARK for human settlement, then continue to B2
**Scope:**
- quorum_evidence.py: verdict unknown/missing → would_count=False + malformed classification
- regression test: grok-style preamble-only body
**Acceptance criteria:**
- [ ] no code path counts an unknown-verdict review
- [ ] failure reason visible in collect output
**Risk:** counting-rule change could over-reject legitimate reviews — tests must cover pass/CR/unknown.
**Rollback tag:** `elves/pre-batch-1` (create before starting)

---

## Acceptance Checks (per batch)

Full gate in .claude/skills/elves-aragora/references/validation-gate-aragora.md. Summary:
rollback tag → implement → pre-commit/mypy/pytest slice → aragora adversarial debate (record
SHA, families, dissent) → DecisionReceipt verified → tier classify → Tier 2 auto-settle /
Tier 3 park → update log + this guide → commit (Co-authored-by) + push → re-read this guide.

Note (from today's session): `claude` and `codex` CLIs can usage-wall mid-run. If the debate
gate cannot run: ≤15 min diagnosis, one alternate-provider retry, then Tier 0-1 close on
degraded-evidence / Tier ≥2 park. gemini CLI is a KNOWN hallucinating reviewer for hunk-only
diffs (that's what B3 fixes) — never let a gemini-only signal settle a batch here.

---

## Tool Configuration (aragora ground truth)

```yaml
lint: pre-commit run --files <changed>   # all-files sweep is too slow on 4k files; hooks run per-commit
typecheck: $ARAGORA_PYTHON -m mypy <changed files> --ignore-missing-imports  # resolve_aragora_python from scripts/aragora_runtime.sh
  # NEVER bare `mypy` — PATH shim is 1.19.1, below the >=2.1.0 floor (caused Jul 9 phantom halt)
test: python3 -m pytest tests/swarm/ -q -p no:cacheprovider   # narrow further per batch
review-cmd: aragora ask "<adversarial review>" --agents anthropic-api,openai-api --context-file <diff> --format json
receipt-verify: aragora verify <receipt.json>
receipt-dir: .aragora/run-elves-9241/receipts
tier-policy-doc: docs/REVIEW_AUTHORITY_PRINCIPLES.md
human-settlement-signal: aragora/human-settlement
notification: pr-comment
```

---

## Rollback and Safety Rules

1. Tag before every batch: `git tag elves/pre-batch-N && git push origin elves/pre-batch-N`.
2. Never force-push/rebase the run branch.
3. Never merge — not even fast-forward.
4. Serious breakage: branch from last good tag, document, stop; leave run branch intact.
5. Stage specific files.
6. Surprise tip move = collision → stop.

---

## After Any Compaction

1. Read this file. 2. Run Control + Stop Gate. 3. learnings.md. 4. Plan (docs/plans/2026-07-11-
m-signal-reviewer-integrity.md). 5. execution-log.md (last receipt = done, don't redo).
6. Operating contract auto-halts + tier table. 7. Resume first unblocked incomplete batch.

# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART
