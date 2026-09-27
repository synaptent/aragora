# Execution Log — m-signal-9241 (reviewer integrity + settlement transport)

> Chronological, append-only. A batch listed complete with a verified receipt is complete —
> do not re-implement.

- **Plan:** docs/plans/2026-07-11-m-signal-reviewer-integrity.md
- **Branch / worktree:** elves/m-signal-9241 / .worktrees/elves-m-signal-9241
- **Default branch:** main
- **Started:** 2026-07-11 ~21:30 CT (staged; launch pending)

---

## Preflight

- `pre-commit`: runs per-commit via hooks (all-files sweep skipped at staging — 4k-file repo,
  hooks enforce on every commit; rationale in learnings #1)
- mypy (venv 2.1.0) on aragora/swarm/quorum_evidence.py: PASS (no issues)
- `pytest tests/swarm/ -q -k quorum`: 304 passed (baseline test count for the slice)
- `aragora --help`: OK on PATH; api-key list deferred to launch (reviewer CLIs confirmed working today via subscription, no raw keys in env by policy)
- Worktree + branch ownership confirmed: yes; tip recorded: 8b1144146d
- Blockers: none known; watch reviewer-CLI walls (learnings #2)

---

## Batches

## Batch 1: no-verdict reviews never count

- **Predicted tier / final tier:** 3 / 3
- **Rollback tag:** `elves/m-signal-9241/pre-batch-1` (pushed: yes)
- **Scope delivered:** EvidenceItem.__post_init__ demotes would_count unless verdict is in the
  closed canonical set ("pass", "changes_requested"); demotion reason in problems[]; 10 new
  regression tests incl. live grok preamble case + 5 forged-verdict cases.
- **Commands run + results:**
  - `pytest tests/swarm/test_quorum_evidence.py` → 225 passed (215 baseline + 10 new)
  - `pytest tests/swarm/test_quorum_receipt.py test_merge_quorum_reconcile.py` → 59 passed
  - ruff check/format → clean; mypy (venv 2.1.0) on module → clean
- **Adversarial review (repo review path, exact head):**
  - Round 1 at 1831d9a4: claude PASS + [P2] closed-set gap + [P3] date; openai CHANGES-REQUESTED
    [P2] same closed-set gap (converged finding) → revised
  - Round 2 at d03d78a9d9: claude PASS (no findings), openai PASS (no findings); counting both,
    dissent none. Independent of authoring lane: yes (CLI harnesses).
  - Evidence: .aragora/run-elves-9241/receipts/b1-pr9249-evidence{,-r2}.json
- **Receipt:** .aragora/run-elves-9241/receipts/b1-gauntlet-receipt-final.json —
  `aragora receipt verify` → VALID (3/3). (Note: gauntlet debate content degraded —
  VibeProxy proposer hiccup — logged as degraded-evidence; the PR-head model quorum above is
  the primary adversarial evidence.)
- **Settlement:** Tier 3 → PARKED, awaiting `aragora/human-settlement` from founder on PR #9249
  head d03d78a9d9 (packet = evidence-r2 + receipt + this entry).
- **Commit:** d03d78a9d9 (`Co-authored-by: claude[bot]`) — pushed: yes; draft PR #9249
- **Decisions made:** no verdict normalization — non-canonical verdict strings are untrusted
  by design; only the parser emits canonical values.
- **Time:** ~55m (incl. two gate rounds)

## Batch 2: verdict contract + truncation exposure

- **Predicted tier / final tier:** 3 / 3 (stacked with B1 on PR #9249, one settlement unit)
- **Rollback tag:** `elves/m-signal-9241/pre-batch-2` (pushed: yes)
- **Scope delivered:** truncated reviews (_TRUNCATION_MARKER, now a shared constant) never
  count; PASS carrying a blocking [P0]/[P1]/Blocker-label finding is self-contradictory and
  never counts (reuses has_blocking_finding_or_label — gate-lockstep); fresh-collect verdict
  parsed from the COMPOSED body, not raw text (openai round-2 P2: normalization over-rejection).
- **Commands run + results:** pytest test_quorum_evidence.py → 231 passed; ruff clean;
  mypy (venv 2.1.0) clean.
- **Adversarial review:** round 1 at cc96267a: claude PASS, openai CHANGES-REQUESTED [P2]
  (raw-vs-composed verdict source) → revised; round 2 at fefa9c91ef: claude PASS + openai PASS,
  both counting, dissent none. Evidence: run-elves-9241/receipts/b2-pr9249-evidence{,-r2}.json
- **Receipt:** run-elves-9241/receipts/b2-gauntlet-receipt-final.json — VALID (3/3)
- **Settlement:** Tier 3 → PARKED with B1 (single packet, PR #9249 head fefa9c91ef)
- **Commit:** fefa9c91ef (`Co-authored-by: claude[bot]`) — pushed: yes
- **Time:** ~35m

## Batch 3: full-file reviewer grounding

- **Predicted tier / final tier:** 2 / 2
- **Rollback tag:** `elves/m-signal-9241/pre-batch-3` (pushed: yes)
- **Scope delivered:** review prompts append bounded post-change contents of changed files
  (6 files x 400 lines, largest diff first, REST contents API) with an explicit
  verify-imports instruction; best-effort by contract (fetch failure never blocks).
- **Commands:** pytest → 236 passed; ruff + mypy(venv) clean.
- **Adversarial review at b425e9ce7d:** openai PASS (counting), claude PASS (advisory [P2],
  non-counting with problems=[] — ITSELF live evidence of the #9129 lint-infra bug B6 targets).
- **Dissent disposition (documented):** claude [P2] — the B2 contradiction guard can falsely
  demote a PASS that enumerates RESOLVED prior findings ("- [P1] X — addressed in <sha>").
  Failure mode is conservative (extra gate round; never a false count). Proper fix lives in
  _NO_FINDING_HEADS (review_queue.py — Tier-4, untouchable by this run). QUEUED as follow-up
  for founder: extend _NO_FINDING_HEADS with resolved/addressed/fixed heads.
- **Receipt:** run-elves-9241/receipts/b3-gauntlet-receipt.json — VALID (3/3)
- **Settlement:** Tier 2 → AUTO-SETTLED (2 heterogeneous PASS signals, zero dissent)
- **Commit:** b425e9ce7d — pushed: yes
- **Time:** ~30m

## Batch 4: credential-health preflight (+ round-2/3/4 gate hardening)

- **Predicted tier / final tier:** 2 / 3 (counting/dissent semantics changed during gate rounds; PR-level settlement covers it)
- **Rollback tag:** `elves/m-signal-9241/pre-batch-4` (pushed: yes)
- **Scope delivered:** credential walls classified `credential_unhealthy(<family>)`; walled
  primary + unconfigured fallback = explicit family-unavailable error; PLUS gate-driven
  hardening: direction-aware truncation demotion, author-controlled path safety +
  URL-encoding, prompt byte caps, full-file grounding OPT-IN default OFF (resolved openai
  [P1] egress dissent), truncated CR always blocks (resolved claude round-3 fail-open corner).
- **Adversarial review:** 4 rounds at 9f1f53fe/638755f8/ba2608fe/68bd60fb12. Final round:
  claude PASS + openai PASS (No findings), zero dissent. openai round-3 [P1] on `supportive`
  REFUTED with line evidence (conjunction already requires would_count). claude evidence
  repeatedly zeroed by lint with problems=[] — third live #9129 capture, logged for B6.
- **Receipt:** evidence artifacts b4-pr9249-evidence{,-r2,-r3,-r4}.json; gauntlet receipts at
  prior heads VALID.
- **Settlement:** rolled into the PR #9249 Tier-3 packet — PARKED for founder settlement at
  head 68bd60fb12.
- **Commits:** 9f1f53fee9, 638755f8d8, ba2608fe6f, 68bd60fb12 — pushed.
- **Time:** ~2h across 4 gate rounds (operator present and directing after round 2).

---

## Completed Archive

(empty)

---

## Open human-settlement queue

| Batch | Tier | Receipt | Packet path | Requested at | Status |
| --- | --- | --- | --- | --- | --- |
| B1 (PR #9249) | 3 | run-elves-9241/receipts/b1-gauntlet-receipt-final.json | run-elves-9241/receipts/b1-pr9249-evidence-r2.json | 2026-07-12T02:40Z | pending |
| B2 (PR #9249, stacked w/ B1) | 3 | run-elves-9241/receipts/b2-gauntlet-receipt-final.json | run-elves-9241/receipts/b2-pr9249-evidence-r2.json | 2026-07-12T02:55Z | pending |
| B4 (PR #9249, full packet B1-B4) | 3 | run-elves-9241/receipts/b4-pr9249-evidence-r4.json | PR #9249 @ 68bd60fb12 | 2026-07-12T04:15Z | pending |
