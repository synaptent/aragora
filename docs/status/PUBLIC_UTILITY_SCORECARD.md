# Public Utility Mission Scorecard (M10)

**Re-audit date:** 2026-07-11, with the external-proof and repo-legibility
dimensions re-audited on 2026-07-16 and the Action-usability and installability
dimensions re-audited on 2026-07-21

**Baseline:** [`PUBLIC_UTILITY_MISSION_BASELINE.md`](PUBLIC_UTILITY_MISSION_BASELINE.md),
captured at `d780bd4898` on 2026-07-02

**Re-audit commit:** `258fb97b82` (`origin/main` when this re-audit began)

**External-proof delta commit:** `26f24acb40` (`origin/main` for the
2026-07-16 reproduction).

**Repo-legibility delta commit:** `7e151c13fc` (`origin/main` for the
2026-07-16 archive and boundary re-audit). Other dimension scores remain at
their 2026-07-11 values pending their own current-main re-audits.

**Action/installability delta commit:** `a4371df1cb` (`origin/main` for the
2026-07-21 Action and fresh-install re-audit).

**Target:** at least **8/10 (grade B)** in each dimension

This is an evidence-weighted closeout, not a declaration that Aragora is
"externally ready." The minimum install → quickstart → receipt → independent-verifier
chain runs, but the Action, repository-legibility, and external-proof
dimensions still have below-target blockers.

## Scoring method

| Score | Grade | Meaning |
|---:|:---:|---|
| 9-10 | A | Clear, reproducible, and supported by merged proof; only minor limitations remain. |
| 8 | B | Target met; usable and evidenced, with bounded known limitations. |
| 7 | C | Substantial capability exists, but an adoption or trust blocker remains. |
| 6 | D | Useful partial surface, with important work still parked or fragmented. |
| 0-5 | F | Target not met; proof is missing, unlanded, or too weak for the claimed outcome. |

## Eight-dimension scorecard

The evidence column cites only repository-visible artifacts and **merged** pull
requests. Open pull requests discussed later are blockers, not score evidence.

| Dimension | Score | Grade | Target | Concrete evidence | Assessment |
|---|---:|:---:|:---:|---|---|
| Product clarity | 9 | A | Met | [`README.md`](../../README.md), [`pyproject.toml`](../../pyproject.toml); merged [PR #8674](https://github.com/synaptent/aragora/pull/8674), [PR #8814](https://github.com/synaptent/aragora/pull/8814) | The front door, package metadata, wedge, product boundary, and load-bearing core now tell one audit-layer/control-plane story. |
| Receipt maturity | 8 | B | Met | [`RECEIPT_LINEAGE_RECONCILIATION.md`](../specs/RECEIPT_LINEAGE_RECONCILIATION.md), [`OPEN_DECISION_RECEIPT.md`](../specs/OPEN_DECISION_RECEIPT.md), [`example-approved-clean.odr.json`](../specs/examples/example-approved-clean.odr.json), [`example-blocked.odr.json`](../specs/examples/example-blocked.odr.json), [`example-abstained.odr.json`](../specs/examples/example-abstained.odr.json), [`example-signed.odr.json`](../specs/examples/example-signed.odr.json); merged [PR #8820](https://github.com/synaptent/aragora/pull/8820), [PR #8822](https://github.com/synaptent/aragora/pull/8822), [PR #8826](https://github.com/synaptent/aragora/pull/8826) | Native/internal and ODR/public roles are explicit; approved, blocked, inconclusive, signed, and chain fixtures are tested. Shipping producers still emit unsigned ODRs by default. |
| Verifier independence | 9 | A | Met | [`INDEPENDENT_VERIFIER_GUIDE.md`](../specs/INDEPENDENT_VERIFIER_GUIDE.md), [`aragora-verify/pyproject.toml`](../../aragora-verify/pyproject.toml), [`aragora-verify/src/aragora_verify/`](../../aragora-verify/src/aragora_verify/), [`aragora-verify/tests/`](../../aragora-verify/tests/); merged [PR #8832](https://github.com/synaptent/aragora/pull/8832), [PR #8854](https://github.com/synaptent/aragora/pull/8854) | The verifier is a separately installable package with no Aragora dependency, a documented 0/1/2/3 contract, schema-parity tests, and key-type/tamper regression coverage. Public-key discovery is not yet shipped. |
| Action usability | 7 | C | Below | [`action.yml`](../../action.yml), [`GITHUB_ACTION_SETUP.md`](../GITHUB_ACTION_SETUP.md); merged [PR #8669](https://github.com/synaptent/aragora/pull/8669), [PR #8955](https://github.com/synaptent/aragora/pull/8955), [PR #9080](https://github.com/synaptent/aragora/pull/9080), [PR #9343](https://github.com/synaptent/aragora/pull/9343) | The root Action can emit, verify, and upload an ODR, the guide has a copy-paste workflow, and `aragora review` now emits an ODR directly. Configured non-demo CLI exports can be signed. The dimension remains below target because the root Action itself still does not wire receipt signing and its default reviewer families require user-held provider keys. |
| Installability | 8 | B | Met | [`INSTALL_MATRIX.md`](../reference/INSTALL_MATRIX.md), [`SDK_GUIDE.md`](../SDK_GUIDE.md), [`pyproject.toml`](../../pyproject.toml), [`aragora-verify/pyproject.toml`](../../aragora-verify/pyproject.toml); merged [PR #8970](https://github.com/synaptent/aragora/pull/8970), [PR #9372](https://github.com/synaptent/aragora/pull/9372) | A clean Python 3.13 environment installed live `aragora` 2.9.0, `aragora-verify` 0.1.1, and `aragora-sdk` 2.8.0 together; the quickstart -> ODR export -> independent verifier chain and the published SDK's offline demo both passed. Main now carries the verifier's `cryptography>=48.0.1` floor in unreleased 0.1.2, while merged policy and a released-surface manifest bound the intentional SDK release lag. Bounded limitation: PyPI still serves verifier 0.1.1 metadata with `cryptography>=41.0`; this clean install resolved 49.0.0, and the stronger floor takes effect for users when 0.1.2 is published. |
| Docs/onboarding | 8 | B | Met | [`docs/README.md`](../README.md), [`docs/INDEX.md`](../INDEX.md), [`quickstart.md`](../quickstart.md), [`GITHUB_ACTION_SETUP.md`](../GITHUB_ACTION_SETUP.md), [`guides/GETTING_STARTED.md`](../guides/GETTING_STARTED.md); merged [PR #8991](https://github.com/synaptent/aragora/pull/8991), [PR #9001](https://github.com/synaptent/aragora/pull/9001), [PR #9003](https://github.com/synaptent/aragora/pull/9003), [PR #9059](https://github.com/synaptent/aragora/pull/9059) | The canonical route is quickstart → receipt → verifier → Action, verifier verbs and exit codes are reconciled, and stale material has a redirect route. The overall corpus is still large, but the public-utility path is singular. |
| Repo legibility | 7 | C | Below | [`ROOT_ALLOWLIST.md`](../reference/ROOT_ALLOWLIST.md), [`MODULE_QUARANTINE_PROPOSAL.md`](../architecture/MODULE_QUARANTINE_PROPOSAL.md); merged [PR #9001](https://github.com/synaptent/aragora/pull/9001), [PR #9091](https://github.com/synaptent/aragora/pull/9091), [PR #9118](https://github.com/synaptent/aragora/pull/9118), [PR #9349](https://github.com/synaptent/aragora/pull/9349) | Root clutter is relocated, the six-boundary quarantine proposal is published, and archive metadata is normalized. A pristine `7e151c13fc` current-main audit left both documentation generators byte-clean, found no stale pre-rename archive paths, and passed the root allowlist, both link validators, and 40 focused tests. This remains below target because `MODULE_QUARANTINE_PROPOSAL.md` is explicitly proposal-only: no boundary inventory is mechanically enforced, and [#8851](https://github.com/synaptent/aragora/issues/8851)'s adopt-or-retire dispositions remain open. |
| External proof | 7 | C | Below | [`2026-07-DOGFOOD.md`](../case-studies/dogfood/2026-07-DOGFOOD.md), [`2026-07-factory-review-quorum-vs-single.md`](../benchmarks/2026-07-factory-review-quorum-vs-single.md), [`factory_review_quorum_vs_single_results.json`](../benchmarks/factory_review_quorum_vs_single_results.json), [`2026-07-PUBLIC-PROOF.md`](../case-studies/dogfood/2026-07-PUBLIC-PROOF.md); merged [PR #9204](https://github.com/synaptent/aragora/pull/9204), [PR #9225](https://github.com/synaptent/aragora/pull/9225), [PR #9228](https://github.com/synaptent/aragora/pull/9228) | The M9 benchmark and public report are merged, and a pristine current-main replay reproduced all three fixtures, receipt digests, and the canonical live-collection hash. This is substantial proof, but it remains below target because no real uncoached outsider has independently run the public path, the receipts are unsigned, and the three-PR smoke slice does not beat its strongest member. Follow-ups: [#8858](https://github.com/synaptent/aragora/issues/8858), [#9231](https://github.com/synaptent/aragora/issues/9231). |

**Total:** **63/80 (78.75%)**. Five dimensions meet the 8/10 target; three remain below target.

## 2026-07-21 current-main Action and installability re-audit

This bounded re-audit ran from a pristine detached worktree at
`a4371df1cb041f34d97ecbeecfe8f44be5d4647d`. It changed only the two dimensions
whose previously named blockers had changed state.

Action usability remains **7/C**. Issues
[#8544](https://github.com/synaptent/aragora/issues/8544) and
[#9209](https://github.com/synaptent/aragora/issues/9209) are closed by merged
PRs #9080 and #9343. The direct review-to-ODR path passed nine focused tests,
and its emitted demo ODR passed the standalone verifier. The one remaining
actionable blocker is exact and repository-visible: lines 217-219 of
[`GITHUB_ACTION_SETUP.md`](../GITHUB_ACTION_SETUP.md) state that the root Action
does not wire Aragora's Ed25519 signer, so Action-produced receipts remain
unsigned even though configured CLI exports can now be signed.

Installability rises to **8/B**. PR #8970 merged the verifier's source floor and
unreleased 0.1.2 metadata; PR #9372 records the independently versioned SDK
cadence and compatibility expectation. Both fresh-install surfaces succeeded:
the public packages completed the minimum evidence chain, and the exact-main
verifier package built and installed with the stronger floor. The remaining
PyPI 0.1.1 metadata lag is recorded as a bounded release limitation rather than
hidden.

Commands and results:

```bash
grep -n 'emit-receipt\|receipt-reviewers\|receipt-path\|receipt-verdict\|receipt-digest\|receipt-verified' action.yml
# exit 0; 10 matching declaration/runtime lines

grep -c 'emit-receipt' docs/GITHUB_ACTION_SETUP.md
# exit 0; 8

PYTHONPATH=. python -m pytest tests/cli/test_review.py -k emit_odr -q
# exit 0; 9 passed, 46 deselected

PYTHONPATH=. python -m pytest tests/scripts/test_github_action_setup_doc.py -q
# exit 0; 10 passed

PYTHONPATH=. python -m pytest aragora-verify/tests/test_package_metadata.py \
  tests/scripts/test_quickstart_surface.py -q
# exit 0; 16 passed

python scripts/check_version_alignment.py
# exit 0; all checked in-tree versions aligned

python3 -m venv /private/tmp/aragora-cycle81-venv-a4371df1
/private/tmp/aragora-cycle81-venv-a4371df1/bin/pip install \
  aragora aragora-verify aragora-sdk==2.8.0
# exit 0; installed aragora 2.9.0, aragora-verify 0.1.1,
# aragora-sdk 2.8.0, and cryptography 49.0.0

/private/tmp/aragora-cycle81-venv-a4371df1/bin/aragora quickstart \
  --demo --no-browser --output /private/tmp/cycle81-quickstart-a4371df1.json
/private/tmp/aragora-cycle81-venv-a4371df1/bin/aragora receipt export \
  /private/tmp/cycle81-quickstart-a4371df1.json --format odr \
  -o /private/tmp/cycle81-quickstart-a4371df1.odr.json
/private/tmp/aragora-cycle81-venv-a4371df1/bin/aragora-verify \
  /private/tmp/cycle81-quickstart-a4371df1.odr.json --json
# exits 0/0/0; schema, digest, and quorum pass; expected unsigned warning

/private/tmp/aragora-cycle81-venv-a4371df1/bin/python - <<'PY'
import asyncio
from importlib.metadata import version
from aragora_sdk import AragoraAsyncClient

async def main():
    async with AragoraAsyncClient(demo=True) as client:
        debate = await client.debates.create(
            task="Should we use microservices?",
            agents=["demo"],
        )
        print(f"aragora-sdk={version('aragora-sdk')}")
        print(f"consensus={debate['consensus']['conclusion']}")

asyncio.run(main())
PY
# exit 0; returned a demo consensus through AragoraAsyncClient

python3 -m venv /private/tmp/aragora-cycle81-verifier-source-a4371df1
/private/tmp/aragora-cycle81-verifier-source-a4371df1/bin/pip install \
  ./aragora-verify
/private/tmp/aragora-cycle81-verifier-source-a4371df1/bin/aragora-verify \
  /private/tmp/cycle81-quickstart-a4371df1.odr.json --json
# exits 0/0; built aragora-verify 0.1.2, required cryptography>=48.0.1,
# installed cryptography 49.0.0, and verified the receipt
```

## External-proof gate

The target score for external proof is explicitly receipt-gated.

### Merged evidence

The five receipts cited by the merged M8 report were re-verified from `origin/main`
with the standalone verifier source:

```bash
for f in docs/case-studies/dogfood/pr-*-receipt.odr.json; do
  PYTHONPATH=aragora-verify/src python -m aragora_verify "$f" --json
done
```

Every invocation exited **0** with `schema_conformance=pass`,
`quorum_consistency=pass`, and `signature=warn` (unsigned):

- [`pr-9027-receipt.odr.json`](../case-studies/dogfood/pr-9027-receipt.odr.json)
- [`pr-9030-receipt.odr.json`](../case-studies/dogfood/pr-9030-receipt.odr.json)
- [`pr-9056-receipt.odr.json`](../case-studies/dogfood/pr-9056-receipt.odr.json)
- [`pr-9062-receipt.odr.json`](../case-studies/dogfood/pr-9062-receipt.odr.json)
- [`pr-9193-receipt.odr.json`](../case-studies/dogfood/pr-9193-receipt.odr.json)

### 2026-07-16 current-main M9 re-audit

Pulls [#9225](https://github.com/synaptent/aragora/pull/9225) and
[#9228](https://github.com/synaptent/aragora/pull/9228) are now **MERGED**. From
a pristine detached worktree at current-main commit `26f24acb40`, the documented
offline measurement command exited **0** and left the worktree byte-clean:

```bash
PYTHONPATH=. python3 scripts/measure_factory_review_quorum_vs_single.py measure
git status --porcelain
git diff --exit-code -- \
  docs/benchmarks/factory_review_quorum_vs_single_results.json \
  docs/benchmarks/fixtures
```

The measurement regenerated three cases. Both Git commands produced no output.
The three documented `emit_pr_receipt.py --verify` replays and all three
standalone-verifier invocations exited **0**. Each verifier result reported
`schema_conformance=pass`, `canonical_digest=pass`,
`quorum_consistency=pass`, and the expected `signature=warn` for an unsigned
receipt.

| Case | Replayed and committed content digest | Documented digest |
|---|---|---|
| Sentry PR 6 | `f586b4272e1a1915f95cee2a02fa207dce487a237a71fd32889d87e174fc4072` | match |
| Grafana PR 1 | `e64756e813dac4064562bf8b6aed2d72fcace76f97d00f7331a6783972a196e2` | match |
| Keycloak PR 7 | `bfa673e02701f0dfb727fd8d990e815f3bb089cdd32841d8564d75ccaa2a0ad2` | match |

The live collection's canonical JSON SHA-256, recomputed with the benchmark
script's sorted, compact JSON encoding, is
`8c675aa9f61d9962fcbe71f5e8265f68f9e334358d04dd5365f4fd4e59e603a9`,
matching the committed result and documentation. The focused benchmark suite
also passed **8/8** tests.

These results close the former "proof is unmerged or unreproducible" blocker and
raise external proof to **7/C**. They do not justify **8/B**: issue
[#8858](https://github.com/synaptent/aragora/issues/8858) still requires one real,
uncoached outsider to run the public install/demo/receipt path, and that evidence
cannot be replaced by another internal replay. The receipts also remain unsigned,
and [#9231](https://github.com/synaptent/aragora/issues/9231) still tracks
out-of-tree output and `grok`/`xai` family-vocabulary polish.

## M0 baseline re-run and comparison

All original M0 commands were re-run from the isolated worktree at
`258fb97b82`. Where the original command contained the literal placeholder
`.../venv/bin/python`, the literal command is not executable; the re-audit used
the same arguments with the mission venv's full path and records that substitution.

| ID | Exact M0 command | M0 value (2026-07-02) | Re-run value (2026-07-11) | Result |
|---|---|---|---|---|
| B01 | <code>gh pr list --state open --limit 400 --json number,title,isDraft</code> | 54 open PRs | 158 open PRs | Re-runnable; queue size increased. |
| B02 | <code>gh pr view 8795 --json number,title,isDraft,files</code> | Open, non-draft; included `README.md` | Merged 2026-07-03; still includes `README.md` | Former collision resolved by merge. |
| B03 | <code>gh pr view 8716 --json number,title,isDraft,files</code> | Open draft; included `README.md` | Closed unmerged 2026-07-04 | Former collision resolved by close. |
| B04 | <code>gh pr view 8713 --json number,title,isDraft,files</code> | Open, non-draft; included `pyproject.toml`, `uv.lock`, SDK lock, and install script | Closed unmerged 2026-07-03 | Former collision resolved by close. |
| B05 | <code>gh pr view 8669 --json number,title,state,mergedAt,closedAt</code> | Merged 2026-06-30 | Still merged | Action receipt emission remains landed. |
| B06 | <code>gh pr view 8674 --json number,title,state,mergedAt,closedAt</code> | Merged 2026-06-29 | Still merged | README rewrite remains landed. |
| B07 | <code>gh pr view 8692 --json number,title,state,mergedAt,closedAt</code> | Merged 2026-06-30 | Still merged | No status change. |
| B08 | <code>gh pr view 8693 --json number,title,state,mergedAt,closedAt</code> | Merged 2026-06-29 | Still merged | Publish workflow remains landed; registry state was checked separately below. |
| B09 | <code>gh pr view 8694 --json number,title,state,mergedAt,closedAt</code> | Closed, `mergedAt=null` | Still closed, unmerged | No status change. |
| B10 | <code>grep -n '^## \|^# ' README.md</code> | Wedge heading at line 38; this regex did not match the H3 honesty headings | Wedge heading at line 44; regex still does not match H3 headings | Re-runnable but blind to H3. Supplementary exact-heading grep found Proof ladder at line 254 and Honest current state at line 545. |
| B11 | <code>grep -n 'description\|readme\|version' pyproject.toml</code> | Package description/readme used "Decision Integrity Platform" | Both use "Auditable execution control plane for AI-assisted decisions"; version 2.9.0 | Positioning drift closed. |
| B12 | <code>grep -n 'emit-receipt\|receipt-reviewers\|receipt-path\|receipt-verdict\|receipt-digest\|receipt-verified' action.yml</code> | 10 matching declaration/runtime lines | 10 matching declaration/runtime lines | Action contract remains present. |
| B13 | <code>diff aragora/gauntlet/odr_schema.json aragora-verify/src/aragora_verify/odr_schema.json</code> | Exit 0, byte-identical | Exit 0, byte-identical | Schema parity preserved. |
| B14 | <code>grep -n 'cryptography' pyproject.toml aragora-verify/pyproject.toml</code> | Root floor `>=48.0.1`; verifier floor `>=41.0` | Same values | Historical 2026-07-11 result; superseded by merged PR #8970 and the 2026-07-21 re-audit above, where both source floors are `>=48.0.1`. |
| B15 | <code>git ls-files 'docs/*.md' &#124; wc -l</code> | 1,029 recursive Markdown files | 1,063 | Corpus grew by 34 files; this broad count includes delivered proof/docs artifacts. |
| B16 | <code>git ls-files ':(glob)docs/*.md' &#124; wc -l</code> | M0 document recorded 64; exact historical command at `d780bd4898` reproduces **63** | 63 | No growth in loose top-level Markdown. The scorecard preserves the recorded/reproduced discrepancy instead of hiding it. |
| B17 | <code>grep -rn 'well-known/aragora-odr-signing-key\|signing-key' aragora/</code> | Four unrelated signing-key references; no endpoint route | Four unrelated signing-key references; no endpoint route | Gap remains. Supplementary exact-path grep found no implementation of either documented endpoint. |
| B18 | <code>grep -c 'emit-receipt' docs/GITHUB_ACTION_SETUP.md</code> | 0 | 8 | Action receipt flow is now documented. |
| B19 | <code>.../venv/bin/python -m pytest tests/cli/test_verify.py tests/export/test_decision_receipt.py tests/gauntlet/test_receipt.py tests/gauntlet/test_odr_verify.py tests/gauntlet/test_odr_verify_schema.py -q</code> | 229 passed | Literal placeholder is un-runnable; full mission-venv path with identical selection: **247 passed** | Test coverage increased with zero failures. |
| B20 | <code>cd aragora-verify && PYTHONPATH=src .../venv/bin/python -m pytest tests -q</code> | 52 passed | Literal placeholder is un-runnable; full mission-venv path with identical selection: **92 passed** | Verifier coverage increased with zero failures. |

### Corrected supplementary checks

Two original checks were too broad or used a regex that missed the intended evidence:

```bash
grep -n 'Proof ladder\|Honest current state' README.md
grep -rn 'well-known/aragora-odr-signing-key\|/api/v2/receipts/signing-key' aragora/
```

The first confirms both honesty headings remain. The second returns no endpoint
implementation. These checks supplement, rather than replace, the unchanged M0 commands.

## Minimum evidence chain, without an "externally ready" claim

The local, zero-key chain was re-run:

```bash
aragora quickstart --demo --no-browser --output /tmp/m10-quickstart.json
aragora receipt export /tmp/m10-quickstart.json --format odr -o /tmp/m10-quickstart.odr.json
aragora-verify /tmp/m10-quickstart.odr.json --json
```

It produced a native receipt, exported an ODR, and the independent verifier exited
**0** (`schema_conformance=pass`, `canonical_digest=pass`,
`quorum_consistency=pass`, `signature=warn` because it is unsigned). Install
evidence is separately grounded by live PyPI state on 2026-07-11:

- `aragora` latest: **2.9.0**, uploaded 2026-07-06.
- `aragora-verify` latest: **0.1.1**, uploaded 2026-07-04.
- `aragora-sdk` latest: **2.8.0**, uploaded 2026-02-25, while
  [`sdk/python/pyproject.toml`](../../sdk/python/pyproject.toml) declares **2.9.0**.

This 2026-07-11 snapshot is preserved for reproducibility. The 2026-07-21
re-audit above supersedes its installability disposition.

## Remaining blockers and operator recommendations

### 1. Land or explicitly settle parked proof and legibility work

The former M7/M9 status list now contains both landed evidence and current
operational blockers:

- **pull/9091 is MERGED:** root-clutter relocation is on `main`;
  archive-metadata consistency is tracked by
  [issue #9229](https://github.com/synaptent/aragora/issues/9229).
- **pull/9118 is MERGED:** the corrected module-quarantine proposal is on
  `main`; repo legibility still needs its own current-main re-audit.
- **pull/9225 is MERGED:** the benchmark is on `main` and reproduced above. Its
  out-of-tree output flag and
  `grok`↔`xai` family-vocabulary normalization are tracked by
  [issue #9231](https://github.com/synaptent/aragora/issues/9231).
- **pull/9228 is MERGED:** the public M9 proof report is on `main`.
- **pull/8970 is MERGED:** main carries unreleased `aragora-verify` 0.1.2 with
  the `cryptography>=48.0.1` floor. Publishing 0.1.2 remains a separate,
  operator-gated release action.

### 2. Preserve the bounded package-release limitations

Live PyPI reports `aragora-sdk` **2.8.0** (2026-02-25), while the tree declares
**2.9.0**. Merged PR #9372 records that lag as intentional decoupled cadence,
and the fresh 2.8.0 offline smoke above passed. Live `aragora-verify` 0.1.1
still advertises `cryptography>=41.0`; main's unreleased 0.1.2 raises the floor
to `>=48.0.1`. Neither bounded lag authorizes a package publication, and any
future release remains operator-gated.

### 3. Strengthen branch and live-fact governance

Twice during this mission, externally verified PyPI facts were rewritten on an
open mission branch before merge: merged [PR #8829](https://github.com/synaptent/aragora/pull/8829)
regressed the `aragora-verify` publish fact, and foreign commit
[`337d943a`](https://github.com/synaptent/aragora/commit/337d943a5be0ccd026b017158b905280dc3053d2)
on merged [PR #8967](https://github.com/synaptent/aragora/pull/8967) rewrote the
live 0.1.1 status. Mission-side mitigations now include dated inoculation comments,
verbatim registry evidence in PR bodies, and session-end foreign-commit checks.

**Operator recommendation only:** protect mission PR branches from non-worker
pushes and/or add a pre-merge live-fact re-check to the auto-merge gate. This is
Tier 4 protection work and requires operator settlement.

### 4. Make docs synchronization enforceable

The non-required docs-build `build` job allows source/mirror or metric drift to
land when a PR skips docs-sync. The `WHY_ARAGORA.md` oversight-ring section landed
without its mirror and was caught up opportunistically in merged
[PR #9001](https://github.com/synaptent/aragora/pull/9001).

**Operator recommendation only:** make the docs-sync check required or add an
auto-sync bot.

### 5. Make tier handling match actual risk

Two tiering behaviors created avoidable mission risk:

1. Armed auto-merge on Tier>0-touching work can fire while the author is still
   investigating the tier consequence (observed during PR #9001).
2. The blanket `scripts/` entry in `TIER_2_PREFIXES` classifies docs-driven
   one-literal changes such as `ARCHIVE_REFERENCE_WHITELIST` or
   `inspect_cold_review_surface.py` assertions as Tier 2.

**Operator recommendations only:** auto-disarm merge when a diff crosses above
Tier 0, and add a narrowly defined known-safe docs-lint/config carve-out in
`review_queue.py`. Both change merge authority and require operator settlement.

## Next recommended mission

Run a bounded **External Adoption Closure** mission, in this order:

1. Land one mechanically enforced repo-legibility boundary or complete one
   adopt-or-retire disposition from #8851.
2. Preserve the now-reproduced M9 benchmark and public proof report, resolve the
   bounded #9231 harness polish, and wait for the genuine #8858 outsider result
   before raising external proof to 8/B.
3. Run a prospective, pre-merge dogfood slice with at least three reachable model
   families and record confirmed catches, false positives, misses, and cost.
4. Wire opt-in signing into the root Action without weakening unsigned
   compatibility; the direct CLI ODR path is already merged.
5. Preserve the explicit package-release boundaries above; publish only under
   a separate release authorization.
6. Decide the operator-gated governance recommendations above as separate,
   exact-head changes rather than bundling them into docs work.

The mission should finish by re-scoring only the three below-target dimensions:
Action usability, repo legibility, and external proof.
