# Decision Integrity, Dogfooded: Our Merges Are Gated by Our Own Product

**Date:** 2026-07-02
**Repo:** [synaptent/aragora](https://github.com/synaptent/aragora)
**Audience:** engineering leaders evaluating whether "AI decision gates" are real or theater.

> **Receipt-backed follow-up:** [Review, Receipt, Verify](../case-studies/dogfood/2026-07-PUBLIC-PROOF.md)
> connects eight real review artifacts to independently verified Open Decision Receipts and a
> pinned quorum-vs-single benchmark.

---

## The claim

Aragora sells decision integrity: adversarial multi-model review of a decision,
severity-classified dissent, tiered settlement, and a verifiable receipt.

The proof no vendor can fake with a demo: **this repository's own merge pipeline
runs on that product.** Over the 30-day window measured below (2026-06-02 to
2026-07-02), heterogeneous frontier-model quorums reviewed substantive PRs at
their exact head commits and dissent blocked or reshaped the code. The pipeline
hardened as it went — severity-classified dissent and the tiered merge gate
rolled out Jun 24–26, and the receipted autonomous merge executor was armed
Jul 2 — so the strongest guarantees cover the most recent merges, and the
numbers below span mechanisms of increasing strictness rather than one uniform
gate across all 30 days.

Everything below is drawn from the public PR/issue record of this repository and
from artifacts committed to its branches. Every number has a query you can run
yourself; every quote links to its source — a PR/issue comment or, where noted,
a commit message.

## The mechanism

One paragraph, end to end: when a PR is ready to settle, independent reviewers
from **distinct model families** (Claude/Anthropic and GPT/OpenAI as the
counting "western frontier" pair, with Grok/Gemini as additional adversarial
voices) each produce a grounded review **at the exact PR head SHA**, posting a
verdict (`PASS` / `CHANGES-REQUESTED`) plus per-finding severity tags
(`[P0]`–`[P3]`). **Severity-gated dissent**
([#8574](https://github.com/synaptent/aragora/pull/8574), merged 2026-06-24)
makes `[P0]`/`[P1]` findings blocking while `[P2]`/`[P3]` findings are advisory
— non-blocking but preserved verbatim as follow-up issues, never silently
dropped. **Tiered settlement**
([#8638](https://github.com/synaptent/aragora/pull/8638), merged 2026-06-26)
scales the required evidence to blast radius: low-risk Tier 0–2 changes settle
on frontier-model quorum autonomously; Tier 3–4 changes always stop for human
risk acceptance, recorded in-thread. Finally, the **merge executor**
([`scripts/merge_executor.py`](../../scripts/merge_executor.py), shipped as
[#8767](https://github.com/synaptent/aragora/pull/8767)) turns
"quorum-authorized" into "merged" without a human typing the merge command —
one bounded pass per invocation, dry-run by default, exact-head re-verification
immediately before each merge, main-health auto-halt re-checked before *every*
merge, a one-way disarm-file kill switch, and **an operator receipt JSON written
per executed merge** to `--receipt-dir`.

```
PR head SHA
   │
   ▼
Adversarial multi-model review  ──  independent frontier families, exact-head grounding
   │
   ▼
Severity-gated dissent (#8574)  ──  P0/P1 block; P2/P3 advisory, preserved as issues
   │
   ▼
Tiered settlement (#8638)       ──  Tier 0–2: model quorum; Tier 3–4: human risk acceptance
   │
   ▼
Receipted merge (executor)      ──  fail-closed, bounded, JSON receipt per merge
```

## 30 days of numbers

Window: **2026-06-02 to 2026-07-02**. Source: GitHub search API against
`repo:synaptent/aragora` (queries reproduced below, complete and runnable
as written; comment-marker counts are GitHub-search matches and therefore
approximate, not hand-audited). Counts collected 2026-07-02; re-running
later may drift slightly as the search index updates.

| Metric | Count | Search query (full) |
|---|---|---|
| PRs merged | **579** | `repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02` |
| Merged PRs carrying an "independent model review" evidence comment | **493** (85%) | `repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "independent model review" in:comments` |
| Merged PRs with an explicit `Verdict: PASS` in comments | **490** | `repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "Verdict: PASS" in:comments` |
| Merged PRs referencing the merge-quorum gate in comments | **173** | `repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "merge-quorum" in:comments` |

Run them yourself (each prints the corresponding count):

```bash
gh api -X GET search/issues \
  -f q='repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02' \
  --jq .total_count   # -> 579

gh api -X GET search/issues \
  -f q='repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "independent model review" in:comments' \
  --jq .total_count   # -> 493

gh api -X GET search/issues \
  -f q='repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "Verdict: PASS" in:comments' \
  --jq .total_count   # -> 490

gh api -X GET search/issues \
  -f q='repo:synaptent/aragora is:pr is:merged merged:2026-06-02..2026-07-02 "merge-quorum" in:comments' \
  --jq .total_count   # -> 173
```

Two honest caveats on these numbers. First, not every merged PR carried quorum
evidence: the volume includes doc-only and Tier-0 mechanical changes, plus PRs
merged before evidence-posting became universal mid-window. Second, a
comment-marker match proves evidence was *posted*, not that the gate was
*binding* for that PR on that day — the gate rolled out in stages (#8574 on
Jun 24, #8638 on Jun 26, executor armed Jul 2), so early-window PRs ran under a
weaker contract than late-window ones.

## Three bugs the gate caught (with the reviewers' own words)

### 1. [#8389](https://github.com/synaptent/aragora/pull/8389) — a tampered `key_id` would have passed signature verification

The PR that added the ODR receipt-verification engine itself (`odr_verify.py`)
was blocked and repaired by the gate — the verifier was verified. Quorum review
found that signature verification wasn't bound to the recorded key identity.
The fix commit
([`e0e7df74`](https://github.com/synaptent/aragora/commit/e0e7df74)) records
the finding it addresses:

> "Addresses the three quorum-review findings on #8389: a cryptographically
> valid signature no longer counts unless its recorded key_id matches
> compute_key_id(supplied key) — **tampered key_id now FAILs**"

Earlier in the PR's life, exact-head review on `35813c54` returned
`CHANGES_REQUESTED` **from both Claude and Grok**, which blocked a queue-drain
close outright ([comment, 2026-06-30](https://github.com/synaptent/aragora/pull/8389#issuecomment-4841335033)).
Two further review rounds forced fixes for a null-subfield crash and a
malformed-input crash class (commits `cfeffc3b`, `136f3002` — "guard verify
pipeline so malformed input is a FAIL verdict, not a crash"). At the final
head `4b56b1ed`, Claude posted `Verdict: PASS`; OpenAI still posted
`CHANGES-REQUESTED` with one `[P2]` (chain-link anchoring accepts any entry
containing the receipt digest — a real weakness in v0.1 chain checking), which
was **preserved as follow-up [#8772](https://github.com/synaptent/aragora/issues/8772)**
under the severity-gated dissent contract rather than discarded. The PR merged
2026-07-02 after 16 days in the gate.

### 2. [#8766](https://github.com/synaptent/aragora/pull/8766) — fabricated branch metadata caused a crash-loop; dissent forced a state-machine redesign

Round-1 quorum review of the mission intake→decomposition bridge caught the
orchestrator fabricating branch names that didn't exist, producing a
crash-loop. From the disposition record on
[#8758 (comment, 2026-07-01)](https://github.com/synaptent/aragora/issues/8758#issuecomment-4860885785):

> "Round-1 findings (**fabricated `metadata.branch` → crash-loop**; positional
> child-id suffixes) were repaired: children now carry `branch_hint` (no fake
> branch), IntakeBridgeDispatch parks branchless children gracefully before
> inner dispatch, ids are content-derived/order-independent"

Round 2 went deeper than a patch. Claude passed; OpenAI dissented with two
findings that required a design decision:

> "[P1] intake.py:116 — branchless children returned as non-terminal failures
> get retried to max_retries → BLOCKED; `select_for()` only claims
> PENDING/IN_PROGRESS, so the advertised worker self-heal path can't claim
> them … Needs a real 'awaiting-claim' state … [P2] intake.py:135 — decomposer
> exceptions marked terminal=True, contrary to the park-and-retry contract; a
> transient provider failure permanently blocks intake."

The gate **refused to settle** — the PR was parked at the attempt cap rather
than merged with known state-machine gaps, an operator design decision was
recorded on #8758, and the dissent produced a first-class `AWAITING_CLAIM`
state plus a retryable-`PARKED` / permanent-`TERMINAL` split (197 tests). As
of this writing #8766 is **still open**, awaiting its final evidence round.
The gate holding a useful feature out of main is the point.

### 3. [#8519](https://github.com/synaptent/aragora/pull/8519) — two model families dissented on expiry semantics, and they were right

The GitHub event-resolver PR resolved prediction claims using wall-clock
expiry. OpenAI and Grok both returned `CHANGES-REQUESTED` on that semantics —
two independent families against the design triggered an escalation instead of
autonomous settlement. The adjudication
([comment, 2026-07-02](https://github.com/synaptent/aragora/pull/8519#issuecomment-4861274218))
sided with the dissent after researching prior art:

> "The reviewer dissent (openai + grok) is CORRECT; the wall-clock
> `_check_expiry` gate should change to event-time. Best-practice research
> across Augur v2, UMA/Polymarket, Kalshi (CFTC rulebook), ISDA credit events,
> occurrence-vs-claims-made insurance, OCC options settlement, and Flink/Beam
> event-time semantics converges on one principle: **Truth is determined by
> event-time; finality is determined by processing-time.**"

The design was reimplemented (event-time expiry + 24h grace window + atomic
compare-and-swap settlement guard), pinned by 97 tests including race-order
tests, and went uncontested through six total evidence rounds across four
reviewer families. Residual dissent was exclusively advisory (`[P2]`/`[P3]`
robustness accumulation, tracked as
[#8779](https://github.com/synaptent/aragora/issues/8779)/[#8781](https://github.com/synaptent/aragora/issues/8781)),
and the operator settled KEEP under the #8574 policy. Without the gate, a
prediction market that discards correct late-arriving outcomes would have
shipped.

## The receipts

Two receipt layers exist today, and it's worth being precise about each.

**Settlement receipts (committed, verifiable now).** Branch
[`elves/close-the-loop-20260701`](https://github.com/synaptent/aragora/tree/elves/close-the-loop-20260701)
carries three `DecisionReceipt` JSONs under `docs/elves/receipts/`:

| Receipt | Decision | Verdict | Quorum recorded |
|---|---|---|---|
| `b3-8767-settlement.json` (`ctl-b3-8767-d6a1a1e0`) | Merge-executor PR #8767, Tier 2 | PASS, confidence 0.9 | claude+openai 2–0 at head `d6a1a1e0`, evidence posted |
| `b4-8768-settlement.json` | Harvest-engine PR #8768, Tier 2 | PASS, confidence 0.9 | claude+openai 2–0 at head `b15dd673` |
| `b6-cleanup-batch1.json` | Cleanup batch 1 (Tier 4, operator-authorized) | PASS, confidence 0.85 | operator G1/G2 |

All three verify with the in-tree verifier — re-run it yourself against every
receipt in the directory:

```bash
git fetch origin elves/close-the-loop-20260701
for f in b3-8767-settlement b4-8768-settlement b6-cleanup-batch1; do
  git show FETCH_HEAD:docs/elves/receipts/$f.json > /tmp/$f.json
done
python3 - <<'EOF'
import json
from aragora.gauntlet.receipt_models import DecisionReceipt
for f in ("b3-8767-settlement", "b4-8768-settlement", "b6-cleanup-batch1"):
    r = DecisionReceipt.from_dict(json.load(open(f"/tmp/{f}.json")))
    print(f, r.verdict, r.verify_integrity())
# -> b3-8767-settlement PASS True
# -> b4-8768-settlement PASS True
# -> b6-cleanup-batch1 PASS True
EOF
```

`verify_integrity()` recomputes the SHA-256 content hash over the receipt's
core verdict fields (`receipt_id`, `gauntlet_id`, `input_hash`,
`risk_summary`, `verdict`, `confidence`) and compares it to the embedded
`artifact_hash`. The B3 receipt also demonstrates dissent capture — its
`vulnerability_details` records the round-1 finding verbatim:

> `{"round": 1, "family": "openai", "finding": "[P1] stale main-health reuse;
> [P2] commit-status contexts invisible", "disposition": "repaired at
> d6a1a1e0, re-gate PASS 2-0"}`

**Merge-executor receipts (operator-side, per merge).** Every merge the armed
executor performs writes a `merge-executor-receipt/v1` JSON — PR number, head
SHA, tier, quorum-packet state, timestamp — to its `--receipt-dir`
(`.aragora/merge_executor/receipts` by default; the armed launchd instance on
the operator's machine writes to `~/.aragora/merge-executor-receipts`). These
live on the operator's machine, not in-repo, so this document describes the
mechanism ([`scripts/merge_executor.py`](../../scripts/merge_executor.py),
lines 236–240 and 368–381) rather than quoting their contents. The first two
armed-executor merges (#8776 and #8775, both Tier 0) were independently
re-verified in the operator settlement session recorded on
[#8762 (2026-07-02)](https://github.com/synaptent/aragora/issues/8762).

**Verifying a receipt as an outsider.** A step-by-step Open Decision Receipt
(ODR) verification walkthrough — schema, hash recomputation, signature and
independence checks, using only `aragora/gauntlet/odr_verify.py` — is being
written in a parallel workstream and will land at
`docs/compliance/ODR_VERIFICATION_WALKTHROUGH.md` (forthcoming; not yet on
`main` at time of writing).

## What the gate does NOT catch (read this section)

If the numbers above sound too clean, here is the failure ledger. Honesty is
the credibility of this document.

1. **Reviewer flakiness and transport failures are real and frequent.** The
   #8766 round-3 record states plainly: "Round-3 claude reviewer failed on CLI
   transport (recorded)." Reviewer harnesses hang, hit auth-state failures,
   and rate-limit; the project built retry/fallback tooling (OpenRouter
   reviewer fallback, session circuit-breakers, `settle_pr` retry paths)
   because a naive single-shot reviewer invocation is not dependable. A gate
   is only as available as its reviewers.

2. **Advisory dissent is non-blocking but also non-counting.** A `[P2]`-only
   `CHANGES-REQUESTED` doesn't block a merge, but it also isn't a PASS — so a
   PR can sit needing one more genuine PASS while reviewers keep finding new
   advisory nits each round ("the treadmill this run's discipline exists to
   refuse," as the #8519 park note put it). The cure was process, not code:
   attempt caps, park discipline, and follow-up issues.

3. **A human override path exists, by design.** #8389 was at one point merged
   on explicit owner judgment while the model-quorum check was red, with the
   authorization recorded in-thread ("the only red required check is the
   model-quorum gate"). Tier 3–4 settlements are *always* human risk
   acceptance. The gate makes overrides expensive and auditable — it does not
   make them impossible, and any vendor claiming otherwise is describing a
   system nobody could operate.

4. **The receipts committed today are hash-verified, not yet signed.** The
   three settlement receipts carry content-addressable SHA-256 integrity
   hashes (tamper-*evident* for the core verdict fields) but no Ed25519
   signatures; the integrity hash also does not cover every field of the
   receipt body. Cryptographic signing and schema hardening are the active
   ODR workstream ([#8765](https://github.com/synaptent/aragora/pull/8765)) —
   and note that the chain-link weakness in the verifier itself was found by
   this same gate (#8389's preserved `[P2]`, follow-up #8772).

5. **The gate reviews the diff, not the running system.** Model review is
   grounded at the exact head SHA of the change. It caught a crash-loop, a
   signature-binding bypass, and a settlement-semantics error — but flaky CI
   shards on main-equivalent code still blocked unrelated settlements
   (recorded as [#8770](https://github.com/synaptent/aragora/issues/8770)),
   and no review round substitutes for tests, canaries, or production
   observation.

6. **The counts are search-derived.** The 579/493/490 figures come from
   GitHub's search API with `in:comments` qualifiers, not a hand audit of 579
   threads. Treat them as accurate to search fidelity.

7. **The reviewers themselves are sometimes confidently wrong.** A companion artifact, [When Reviewers Are Wrong](2026-07-reviewer-failure-taxonomy.md), catalogs six receipted reviewer failure classes from this same gate — every documented error a false negative (a true claim wrongly doubted), none a false claim merged.

## Why this is hard to fake

A staged demo can show a model posting "LGTM." What a demo cannot fake is a
30-day public record where the gate visibly *lost arguments it should lose and
won arguments it should win*: a verification engine held out of main for 16
days by its own product, a feature still parked today because one model family
found a real state-machine gap, a design reversed because two families
dissented and were right — plus committed receipts whose hashes verify with
the verifier that lives in this repo, whose own bugs the gate caught. The
record includes its failures, which is precisely what makes the successes
checkable.

---

*Prepared 2026-07-02 as a Wave-3 artifact for epic
[#8762](https://github.com/synaptent/aragora/issues/8762). All PR/issue links
public. Corrections welcome — file an issue.*
