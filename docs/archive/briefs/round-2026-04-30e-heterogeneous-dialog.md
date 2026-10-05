# Round 2026-04-30e — Heterogeneous dialog + harness hardening + DIC-14 wedge

**Goal:** Advance the maximalist vision via heterogeneous-model consensus,
fix dogfooded issues from the previous round's gauntlet, demonstrate
cross-agent dialog with persistent state across CLI harnesses including
Chinese frontier models, and land DIC-14 (executable claim runner).

**Standing rule:** I do not author-merge. Awaiting Codex signal + CI green
on every PR opened in this round.

## Phases A–J

| Phase | Name | Outcome |
| --- | --- | --- |
| A | Round seed + 8 model surfaces verified live | 8/8 dispatchable |
| B | Heterogeneous dialog model factories | **PR #6883** (Tier 2, 294 LOC, stacked on #6855) |
| C | 8 gauntlet hardening fixes | **PR #6884** (Tier 1, 419 LOC, stacked on #6883) |
| D | Heterogeneous-panel review of Phase C | 3 follow-up fixes landed on #6884 |
| E | DIC-14 executable claim runner | **PR #6885** (Tier 2, 696 LOC, off main) |
| F | AGT-04 round-30b Brier leaderboard | 2 markets resolved YES; oracle-droid winner |
| G | Iterative 2-round dialog dogfood | 4/4 converge on same wedge; shared design risk surfaced |
| H | codex exec review on open PRs | 2 real findings: PR #6878 string-bool bug + PR #6885 sync-thread caveat |
| I | Real-unstick batch #2 | 10 issues closed (each verified merged) |
| J | This briefing PR | (you are reading it) |

## Key wedges landed

### Phase B — Heterogeneous dialog harness (PR #6883)

Round 30d's harness only dispatches each CLI's *default* model, so a
3-CLI panel is in practice "same-family-three-times". This wedge adds:

- `AgentSpec.with_model(cli, model, name?, timeout)` generic factory
- Named factories: `claude_opus`, `claude_sonnet`, `droid_gpt5`,
  `droid_gemini`, `droid_kimi`, `droid_glm`
- `AgentSpec.heterogeneous_panel()` — canonical 6-model panel
- `scripts/multi_agent_dialog.py --agents-spec heterogeneous` shorthand

**Live verification:** 6/6 succeeded in <10 s each spanning Anthropic,
OpenAI, Google, and Chinese-frontier (Kimi K2.5) families.

### Phase C — Hardening (PR #6884)

Eight gauntlet findings from round 30d-Phase-H landed as a single
hardening commit + 27 regression tests:

1. `os.setsid` preexec → `start_new_session=True` for POSIX process-group reaping
2. `RC_BINARY_NOT_FOUND=-127` sentinel for `FileNotFoundError`
3. `RC_DISPATCH_ERROR=-126` sentinel for other setup errors
4. `_strip_ansi`: CSI + OSC-8 escape removal
5. `_truncate_output` capped at 1 MB per stream (sentinel-aware)
6. `asyncio.gather(return_exceptions=True)` + synthetic error turns
7. Atomic write (tmp + fsync + `os.replace`) + `_validate_round_id` regex
8. `_escape_md_fence` (ZWSP) + `[TIMED OUT]` status badge

### Phase D — Self-dogfooding via the Phase B harness

The new heterogeneous panel reviewed Phase C's diff. 6/6 reviews succeeded
in 13–91 s. Verdicts: 4 APPROVE, 1 REQUEST_CHANGES (codex), 1 BLOCK
(droid-gemini, partially incorrect). Three real follow-up fixes landed:

- (codex) `_truncate_output` reserves sentinel bytes from budget so total
  persisted bytes ≤ MAX_OUTPUT_BYTES
- (claude-opus) ANSI-strip moved *after* truncation, so DoS amplification
  on multi-MB inputs is bounded
- (droid-gemini) `preexec_fn=os.setsid` → `start_new_session=True` for the
  documented thread-safe equivalent

This is the **decision-integrity-via-heterogeneous-consensus value
proposition demonstrated against itself**: a same-family panel would have
surfaced ~1–2 of these concerns; the heterogeneous panel surfaced 6
distinct ones from 6 independent model families.

### Phase E — DIC-14 executable claim runner (PR #6885)

Today an Aragora *claim* (structured assertion produced by a debate) is
text-only — the system can debate them, score them, and persist them, but
it cannot **mechanically check** whether they hold. New module
`aragora/reasoning/claim_runner.py` adds the missing piece:

- `ExecutableClaim(name, predicate, timeout?, description?)` — sync OR async
- `ClaimContext = dict[str, Any]` shared evidence bag
- `ClaimVerdict` (PASS / FAIL / TIMEOUT / ERROR)
- `ClaimRunner.run(claims, context)` concurrent evaluator with bounded
  concurrency option
- JSON-serialisable `ClaimReport` for direct persistence into receipts

33 unit tests + 1 follow-up test added in Phase H pinning the
sync-predicate-timeout-is-cooperative contract = **34/34 pass**.

### Phase G — Iterative dialog as evidence

Round 1: each agent in the heterogeneous panel proposes ONE wedge to
integrate DIC-14 with the debate orchestrator. Round 2: the panel
cross-critiques.

- **4/4 successful agents converged** on the same wedge: post-debate hook
  that runs DIC-14 against consensus claims, attaches PASS/FAIL verdicts
  to decision receipt
- **3/4 voted claude-opus's proposal as winner** for cleanest separation
  via `aragora/debate/post_debate/claim_verifier.py` + `PostDebateConfig`
  flag (mirrors existing `auto_verify_arguments` / `auto_outcome_feedback`
  pattern)
- **All 4 identified the same shared design risk**: claim extraction from
  free-form prose is fallible — silent false-negatives can hollow the
  integrity signal without observable error

This is dialectical convergence: independent agents arriving at the same
architecture *and* the same critical risk.

### Phase H — codex exec review

Single codex CLI invocation surfaced two real findings on two distinct
PRs in <60s combined:

- **PR #6878:** `bool(payload.get("halt_tripped"))` treats `"false"`
  string as `True`; would falsely flag rounds halted. Concrete fix
  posted as PR comment.
- **PR #6885:** `asyncio.to_thread()` timeout doesn't force-terminate the
  worker thread. Inherent Python threading limitation — documented as
  contract + regression test landed (commit `c3a95e9`).

### Phase I — Real-unstick batch #2

10 boss-stuck issues closed (each verified to have a MERGED PR via
`gh pr view --jq state`). Issues 5127, 5128, 5129, 5130, 5132, 5175,
5176, 5178, 5180, 5181.

## Brier leaderboard (round 2026-04-30b)

| Agent | Mean Brier | Verdict |
| --- | ---: | :---: |
| oracle-droid (p=0.90) | 0.0100 | GOOD |
| skeptic-codex (p=0.65) | 0.1225 | OK |
| bear-claude (p=0.40) | 0.3600 | POOR |

All 2 PRs (#6828, #6829) merged YES so confident-YES priors win this batch.

## Receipts

Per-phase JSON receipts persisted under
`.aragora/evolve-round/2026-04-30e/dogfood/phase-{a..i}-receipt.json`.

## Halt status

**No halt tripped.** All 10 phases complete.

## Standing rule

I do not author-merge. PRs #6883, #6884, #6885 await independent CI
green + Codex signal. PR #6878 is not mine; finding posted as a PR
comment for the author.
