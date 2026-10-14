# Observe-Outcomes First --write Verified — 2026-05-13

This note records the first end-to-end `observe-outcomes --write` execution and
its independent three-model cross-family verification. It complements the
Proof Loop First Closure note from 2026-05-12
(`PROOF_LOOP_FIRST_CLOSURE_2026-05-12.md`, now an archived dated snapshot),
which captured the dry-run-only state.

## What ran

Exact command, with operator authorization recorded in chat:

    python3 -m aragora.cli.main review-queue observe-outcomes \
        --window-days 14 --max-receipts 10 --write --json

Executed at `2026-05-13T15:21:27Z` against the first 10 receipts in
`.aragora/review-queue/receipts/`. Each receipt's five v2 outcome signals were
derived from the post-merge GitHub timeline of its PR and written into the
receipt JSON.

The 10 receipts cover the following merged PRs:
`#7060`, `#7079`, `#7097`, `#7101`, `#7105`, `#7107`, `#7114`, `#7121`,
`#7123`, `#7124`.

## Observed result

All five outcome signals on all ten receipts wrote as `false`:

- `outcome_revert_within_window`
- `outcome_post_merge_incident`
- `outcome_human_override_redo`
- `outcome_rollback`
- `outcome_reopened_pr`

`outcome_observed_at` is uniformly `2026-05-13T15:21:27Z` across the batch.

The reading is: every observed PR had a clean post-merge timeline with no
invalidation event in the 14-day window.

## Independent verification

Three frontier models from three providers independently verified that the
recorded signals match the actual GitHub timelines, with no false-positives
and no false-negatives:

| Verifier | Model | Provider | Verdict | Latency |
| --- | --- | --- | --- | --- |
| Claude (operator session) | Sonnet 4.5 | Anthropic | CLEAN, 10/10 | direct |
| Codex | GPT-5.5 | OpenAI | CLEAN, 10/10 | 26.1s |
| Droid-Gemini | Gemini latest | Google | CLEAN, 10/10 | 65.5s |

Codex and Droid-Gemini were dispatched in parallel via
`scripts/multi_agent_dialog.py` with the verification prompt and full JSON
context (10 receipts + paginated timelines for each PR). The complete dialog
transcript is archived in git (three-model verification dialog).
The JSONL remains in git under
`docs/receipts/observe-outcomes/2026-05-13-three-model-verification-dialog.jsonl`.
The dispatch context bundle (prompts + raw timeline events) is also preserved locally under
`.aragora/evolve-round/2026-05-13-observe-outcomes-first-write/`.

Each verifier was given the same independent task: read each receipt's five
recorded signals, fetch the corresponding PR's GitHub timeline, and report any
mismatch between recorded signals and timeline evidence. Each verifier was
specifically instructed to flag `reopened` events, `incident`/`regression`/
`revert`/`rollback` labels, and cross-references identifying revert PRs.

All three verifiers returned the same per-PR verdict for all ten PRs.

## What this proves and does not prove

This proves:

- The `observe-outcomes --write` code path executes correctly on a real
  batch of settlement receipts and produces consistent outcome data.
- For this specific 10-PR batch, the recorded "all signals false" reading
  matches the actual GitHub timelines under three independent reviews.
- The three-model cross-family consensus pattern works as a verification
  protocol; harness dependencies do not require a single-vendor trust path.

This does not prove:

- That the empirical 5% invalidation threshold from the thesis is grounded.
  All ten PRs in this batch produced zero invalidation signals; that is a
  clean batch, not a calibrated rate.
- That any future `--write` run will succeed. No CI automation has been
  granted for this command.
- That every code path in the observation pipeline is tested. The verifier
  consensus is over recorded results, not over implementation coverage.

## Non-claims

This note does not authorize unattended `observe-outcomes --write`, does not
expand the operator-driven cap from this single batch, does not change the
review-queue receipt schema, does not modify H2 panel state, and does not
close #6375.

## Bounded next steps under standing authorization

Three additional settlement receipts have been seeded since the first write
(`#6932`, `#7129`, `#7130`); they do not yet have outcome fields. The next
authorized action is a fresh dry-run over all 13 receipts to confirm the
three new receipts are dry-run clean; a subsequent bounded `--write` over
the new three remains operator-authorized as a separate event.

The first `--write` milestone is recorded as complete and verified.
