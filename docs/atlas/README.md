# Disagreement Atlas v1

**What it is.** A dataset of every reviewer verdict posted at an exact head SHA
on every pull request of [synaptent/aragora](https://github.com/synaptent/aragora)
that merged or closed since the tiered merge gate landed
([#8638](https://github.com/synaptent/aragora/pull/8638), 2026-06-26T21:04:36Z),
together with the ground-truth adjudication that resolved each disagreement:
what the PR did next, how the operator settled it, and — for the rounds
hand-labelled in the
[reviewer-failure taxonomy](../artifacts/2026-07-reviewer-failure-taxonomy.md) —
which failure class the reviewer exhibited and whether its finding was valid.

The record is one **(PR, head SHA, reviewer family, round)** tuple. Every number
in [`summary.md`](summary.md) regenerates from `atlas-v1.jsonl` (a release
asset, see *Release asset*) with one command; the JCS-canonical [`manifest.json`](manifest.json) pins the
dataset hash and record count the same way an
[Open Decision Receipt](../specs/OPEN_DECISION_RECEIPT.md#5-canonicalization-and-hashing--rfc-8785-jcs)
pins its content.

Tracking issue: [#9950](https://github.com/synaptent/aragora/issues/9950).
Successor to [#8860](https://github.com/synaptent/aragora/issues/8860).

## Files

| File | Purpose |
|---|---|
| `atlas-v1.jsonl` | The dataset: one JSON object per line, sorted by PR, round, head, family. Committed when ≤ 5 MB; otherwise only `atlas-v1.sample.jsonl` (200 records) is committed and the full file ships as a release asset (see *Release asset*). |
| `schema.json` | JSON Schema (draft 2020-12) for a record, including the controlled vocabularies. |
| `manifest.json` | JCS-canonical manifest: SHA-256 and byte length of the dataset, record and PR counts, source window, vocabularies, `content_digest`, and a `signatures[]` array in the ODR detached-signature shape. |
| `summary.md` | Headline tables — regenerated, never hand-edited. |
| `../../scripts/build_disagreement_atlas.py` | The generator (collect / build / summary / verify / make-fixture). |
| `../../tests/scripts/test_build_disagreement_atlas.py` | Schema conformance + determinism on a three-PR fixture. |

## Where the records come from (provenance)

All inputs are public GitHub data or files committed in this repository. No
secret is read; the only credential is a read-scope `gh` login.

| Source | REST endpoint / path | What it contributes |
|---|---|---|
| PR list | `GET repos/{repo}/pulls?state=closed&sort=updated` | Every PR with `closed_at ≥ since` (merged **and** closed-unmerged). |
| Evidence comments | `GET repos/{repo}/issues/{pr}/comments` | The reviewer verdicts. Each is an "independent model review" comment composed by `scripts/collect_quorum_evidence.py`: heading, `Model family:` disclosure, `Head: <7> (<40>), committed <ts>`, `Verdict:` line, `[Pn]` findings. Operator park/settlement comments in the same thread drive the adjudication inference. |
| Review objects | `GET repos/{repo}/pulls/{pr}/reviews` | Mirrored model reviews posted as GitHub reviews (`commit_id` is the exact head). Human reviews without a disclosed model family are not records. |
| Commits | `GET repos/{repo}/pulls/{pr}/commits` | Resolves 7-char head prefixes to full SHAs and supplies commit times for round ordering. |
| Statuses | `GET repos/{repo}/commits/{head}/statuses` | The `aragora/human-settlement` commit status on the final head (Tier 3-4 human risk acceptance). |
| Eval fixture | `tests/governance/fixtures/adjudicator_eval_cases.json` | Verbatim reviewer bodies from prepare-only rounds (recorded by the collector at the exact head but not posted), plus the hand-labelled ground truth: failure classes, `findings_valid`, disposition, resolution mechanism. |
| Receipts | `docs/receipts/**`, `docs/elves/receipts/**`, `docs/status/settlement-packets/**` | Committed settlement receipts that mention a PR are attached as `receipt_refs`. |

**Parsers are the gate's own.** Verdicts come from
`aragora.swarm.quorum_evidence._reviewer_verdict`, reviewer identity from
`aragora.cli.commands.review_queue._resolve_model_review_identity` (with the
dogfood and review-object fallbacks), findings and blocking severity from
`aragora.cli.commands.review_queue_comment_verdicts.extract_finding_lines` /
`highest_blocking_severity`, family canonicalisation from `canonical_family`
(so `codex`/`gpt` collapse into `openai`). Nothing in the atlas re-parses comment
text with a second grammar; if the gate would not count a body, the atlas does
not attribute a verdict to it.

## Record anatomy

See `schema.json` for the full contract. The load-bearing fields:

- `head_sha`, `head_resolution` — the exact head the verdict was grounded on and
  how it was established (`comment_full` from the Head line, `commits_list` from
  a resolved prefix, `review_commit_id`, `fixture`, or `prefix_only` when a
  hand-posted 7-char prefix could not be resolved).
- `round`, `rounds_total` — 1-based index of this head among the PR's heads that
  carry a verdict (ordered by commit time, then first verdict time).
- `reviewer.family`, `reviewer.counting_class` — canonical family and its gate
  jurisdiction (`western_frontier` claude/openai; `western`; `chinese_routed`;
  `advisory_only` gemini, kept but never counted).
- `verdict`, `verdict_basis`, `highest_blocking_severity`, `findings[]` — `pass` /
  `changes_requested` / `unknown`, with the basis the gate used (`verdict_line`;
  `negative_marker` for a blocking finding without a parseable token;
  `non_negative_signal` for pre-gate phrasings such as `Verdict: approve` that the
  gate's comment-signal path counts as support; `review_state`; `fixture`);
  `P0`/`P1` when the body carries a real blocking
  finding (the [severity gate](../specs/MODEL_DISSENT_SEVERITY_GATE.md) treats
  `[P2]`/`[P3]` as advisory); every `[Pn]` finding line with its text.
- `body`, `dissent_text` — the verbatim reviewer body; `dissent_text` repeats it
  for `changes_requested` verdicts and is empty otherwise.
- `adjudication.mechanism` (+ `mechanisms_secondary`) — controlled vocabulary
  from the taxonomy's resolution catalogue: `evidence_post`, `premise_removal`,
  `premise_self_expiry`, `severity_gating`, `operator_adjudication`, `re_filing`,
  `grounding_fix`; plus the mechanical outcomes `revision` (head advanced before
  merge), `re_gate_flip` (same head, same family, later PASS with no recorded
  refutation), `none_required` (PASS), `closed_unmerged`, `unresolved` (blocking
  dissent at the merged head with no recorded adjudication), `not_applicable`.
- `adjudication.source` — `labeled` when the (PR, head) is in the eval fixture
  (hand labels win; the inferred mechanism is kept as a secondary), else
  `inferred` from thread facts: PASS → `none_required`; PR closed →
  `closed_unmerged`; same-head later PASS → `evidence_post` / `premise_self_expiry`
  / `re_gate_flip`; head advanced → `revision`; merged at this head with a
  settlement signal (human-settlement status, Tier-4 marker, operator settlement
  comment) → `operator_adjudication`; merged at this head on `[P2]`/`[P3]`-only
  dissent → `severity_gating`; otherwise `unresolved`.
- `adjudication.ground_truth` — the fixture's `disposition`, `findings_valid`,
  verbatim `mechanism_text`, note and receipt URLs (labelled records only).
- `taxonomy_classes` — hand-labelled failure classes (`diff_blind_grounding`,
  `stale_external_world`, `temporal_reasoning`, `verbatim_repeat_dissent`,
  `out_of_scope_carousel`, `cross_family_contradiction`, `control`).
- `pr.outcome`, `pr.merge_commit_sha`, `pr.final_head_sha`, `pr.tier`,
  `follow_up_issues[]`, `receipt_refs[]`, timestamps throughout.

## Regenerate

```bash
# 1. Cache every raw GitHub response (re-runs cost zero API calls).
python3 scripts/build_disagreement_atlas.py collect --cache-dir /tmp/atlas-cache
#    --since accepts an ISO timestamp or a PR number; the default anchors on
#    PR #8638's merged_at. Add --refresh-index to re-enumerate the PR list.

# 2. Build the dataset and the manifest.
python3 scripts/build_disagreement_atlas.py build --cache-dir /tmp/atlas-cache \
    --out docs/atlas/atlas-v1.jsonl

# 3. Regenerate the headline tables.
python3 scripts/build_disagreement_atlas.py summary \
    --dataset docs/atlas/atlas-v1.jsonl --out docs/atlas/summary.md
```

The build has two inputs: the GitHub cache and the checkout's receipt files
(`docs/receipts/`, `docs/elves/receipts/`, `docs/status/settlement-packets/`),
which feed `receipt_refs[]`. Rebuilding from the same cache and the same receipt
files is byte-identical (the tests pin this under input reordering). Rebuilding
can differ only if GitHub content changed after a fresh `collect` (a comment
edited, a status added) or a receipt file that mentions an in-window PR was
added or edited; the manifest's `receipt_inputs.files` pins the SHA-256 of every
receipt file the records cite so `verify` reports that case as a receipt-input
mismatch rather than a dataset mismatch.

## Verify

```bash
# The full dataset is a release asset, not a tracked file (see *Release asset*).
gh release download atlas-v1 -R synaptent/aragora -p atlas-v1.jsonl -D docs/atlas
python3 scripts/build_disagreement_atlas.py verify --manifest docs/atlas/manifest.json
```

recomputes the dataset SHA-256, byte length and record count, the `schema.json`
hash, and `content_digest = SHA-256(JCS(manifest minus content_digest and
signatures))` using the ODR reference canonicaliser
(`aragora.gauntlet.odr_export.jcs_canonicalize`). Exit code 0 and the word
`VERIFIED` mean every check passed. Without the download, `verify` still checks
the sample, the schema hash and the content digest, and reports the dataset line
as `SKIPPED` (with the expected SHA-256) rather than failing.

The manifest carries the same detached-signature shape as an ODR receipt. To
sign, pass `--sign-key <ed25519.pem>` to `build` (this calls
`aragora.gauntlet.odr_signing.sign_odr_receipt` on the manifest); to check a
signature, pass `--public-key <pub.pem>` to `verify`. The committed manifest is
unsigned (`"signatures": []`) — the repo's production ODR key lives in Secrets
Manager and is not used from a workstation. `aragora-verify` itself checks ODR
documents, not this manifest; the `verify` subcommand is the documented
equivalent and shares its digest algorithm.

## Release asset

If `atlas-v1.jsonl` exceeds 5 MB it is **not** committed. `build` then also
writes `atlas-v1.sample.jsonl` (all hand-labelled records plus an evenly spaced
selection, 200 records) which is committed with `manifest.json` (whose
`dataset.sha256` still covers the full file) and `summary.md`. The full file is
attached to the GitHub release tagged `atlas-v1` as `atlas-v1.jsonl`; download
it next to `manifest.json` and run `verify`.

## Limitations — read before citing

1. **Posted verdicts only, plus the committed fixture.** Tier 3-4 PRs run the
   collector in prepare-only mode: their reviewer bodies are quoted in
   evidence-round comments but not posted verbatim. Those rounds appear only
   where the eval fixture carries the body (10 cases). Coverage is therefore
   complete for *posted* verdicts, not for every review round that ran.
2. **Inferred adjudication is mechanical.** `revision` means the head advanced
   before merge — which also happens on main-merges; `vindicated` in
   `summary.md` is an upper bound on dissent validity for the same reason. Only
   `labeled` records carry a human judgement of whether a finding was valid.
3. **Follow-up issue detection is keyword-based** (filed / re-filed / tracked /
   follow-up + `#N`), excluding numbers known to be PRs in the window; open PRs
   or PRs outside the window can leak through as "issues".
4. **Two counting families dominate.** The gate's default reviewer pair is
   claude + openai; grok/mistral/gemini/Chinese-routed families appear only where
   an operator invoked them. Family-level rates are this repo's, not the models'.
5. **The operator is not a neutral referee.** Ground-truth labels encode the
   repo operator's recorded dispositions (see the taxonomy's limitations).
   Dispute one by filing an issue against the fixture.
6. **Bodies may be truncated by the collector** (`[reviewer output truncated]`
   marker) exactly as they were posted; the atlas never re-truncates.

## Privacy and licence

The dataset contains only content already public on the referenced PRs and
issues: reviewer bodies, operator comments (referenced by URL, quoted only where
a reviewer body quotes them), and the GitHub logins of PR authors and evidence
posters. No email addresses, tokens or other secret material are present; the
tests assert schema conformance and the build reads no secrets.

Released under the repository's [MIT License](../../LICENSE), like the code that
generates it. Publication outside the repository was approved by the founder on
2026-09-01 (operator decision on #9950).
