# PR #9320 Historical First-Parent Backfill Record

Status: `historical_backfill` + `historical_nonconforming` (the only recorded dispositions).
Recorded: 2026-08-01 (UTC) under accepted post-bootstrap Contract Drift Governance authority.
Durable capsule: immutable GitHub Release `backfill-0b28f68b9f4d204ae14814169093723ea84c1364`
(release API ID 363450207, published 2026-08-01T06:35:28Z, `immutable=true`, targeting merge commit
`0b28f68b9f4d204ae14814169093723ea84c1364`; assets `manifest.json`, `payload.json`, `checksums.txt`;
exact bytes and digests bound in the release, which is the canonical durable artifact — this
document is the in-repo pointer/record).

## 1. Scope and non-authority (binding)

This is the required historical first-parent receipt/backfill for already-merged PR #9320.
It records historical facts only. It must NOT be used as, and cannot supply:

- accepted authority or an authority transition;
- pre-merge admission evidence (`contract-drift-pr-delta` never ran for this PR);
- forward proof of no-admin merge behavior, prerequisite chronology, settlement ordering,
  or post-settlement quorum for any PR (including #9320 itself);
- forward immutable-boundary, chronology, settlement, or capsule proof.

PR #9320 must never be reopened, resettled, remerged, edited, or treated as future admission.
The old head `73cf6d4831c2cb032f31108dada6251f45571748` and every delegation bound to it remain
consumed or void. The sole accepted disposition remains `historical_nonconforming` exactly as
pinned in the accepted authority transition record (`scripts/baselines/contract_drift_inventory.json`
-> `accepted_authority.transition.historical_nonconforming[pr=9320]`).

## 2. Independently authenticated identities

Authenticated 2026-08-01 from immutable git objects plus the GitHub REST API
(`repos/synaptent/aragora/pulls/9320`, fully paginated `/files` reconciled to `changed_files=3`).

| Fact | Value |
|---|---|
| PR | #9320 `fix(sharing): warn on legacy share model access` |
| Head (exact, historical) | `aba6b14c94eca3a9c825b1a303ea67684d5f8daa` (tree `e5c6c3d07a918cf43fffed6d4a9f472bc10a674a`; parents `73cf6d4831c2cb032f31108dada6251f45571748`, `14d1ef53e23c5466c0491ed93f72752944c78cd4`) |
| Squash merge | `0b28f68b9f4d204ae14814169093723ea84c1364` (tree `79c1c374eed261c42468dc526d837e726e73425a`) |
| True first parent | `e448b840dad03ee28accd218c14a27fa8b87c7b4` (tree `01b4cf257c6864c6c14d5ac227dca185d07862dc`) |
| Recorded base (PR API) | `14d1ef53e23c5466c0491ed93f72752944c78cd4` (the #9346 squash; NOT the merge first parent — the PR merged 5 commits after its recorded base) |
| Merge actor / time | `scarmani` / `2026-07-16T20:00:49Z` |
| Branch | `structex/p4a-sharing-symbol-compat` |
| Files (reconciled) | `aragora/server/handlers/social/__init__.py` (+3/-1), `aragora/server/handlers/social/sharing.py` (+23/-0), `tests/handlers/social/test_sharing.py` (+89/-2); totals +115/-3 |
| First-parent chain | `0b28f68b...` IS on `main`'s first-parent chain; its chain predecessor is exactly `e448b840...` (adjacency verified) |
| Head-tree vs merge-tree | NOT equal (`e5c6c3d0...` vs `79c1c374...`) — expected; PR-head tree equality is neither required nor sufficient for squash binding |

Per-file blob identities (first parent -> squash merge):

- `aragora/server/handlers/social/__init__.py`: `a155b83a7ecefb13fd3c09865917fcde5ee86bce` -> `b1023f8e2052adbf5f4df1fd7a8cd4d9f226be21`
- `aragora/server/handlers/social/sharing.py`: `9b2faf18bb885375a9a9d67b02a2894c6d272fbd` -> `5389e4782ac726181482b59062292582862cc537`
- `tests/handlers/social/test_sharing.py`: `020a5ab0baae7505765cf75c9808ace08a605a47` -> `c3ee71b8d2a5a7aa4ed473d6082f7872a1eaea36`

Exact first-parent->merge patch: 5,874 bytes, SHA-256
`a5c94ff5c9d32a60c055d5ae67b21935dd7f98aae6f868ab1d68e300bb604455`
(`git diff e448b840dad03ee28accd218c14a27fa8b87c7b4 0b28f68b9f4d204ae14814169093723ea84c1364`).

## 3. Accepted authority used for measurement

Measured on fresh `origin/main` `492405a6c134745741709838caf56ee2a5d20ece`, whose analyzer-bundle
pins verify byte-for-byte against the accepted authority:

- checker `scripts/check_contract_drift_ratchet.py` = `716d360c5fd4bd5dc1b423005b5dcc4c7f2000e3d6f099a9bc0a314bd1fca4e1`
- inventory module `scripts/generate_contract_drift_inventory.py` = `1528c5cda481d83e157b973be610e820e4750d5d4a5fa59924484137877a2bb4`
- program baseline `scripts/baselines/contract_drift_program.json` = `0328ec88fa524d8ff4259f6bf1dbeb0fd1514de18d2ac472914e39e4e688921c`
- launcher = `1bcf2e69038d8c91abb260e588946aab7b3dffdaead394992bd44eaceed070c1`
- analyzer-bundle digest = `1b977ec70e9400ec5239c22474a4400753c7d99acee78c4a6426c2ce8bc47356`
- accepted-authority `manifest_sha256` = `de5c6595791c6163ffdaa6e8cb79396b8219e80064f913ce883f2da5310ec77f` (recomputed equal)
- `active_inventory_sha256` = `f6ebbb39ee71af2a91aad1bfe0261f56f413be4d8d717a8cbe89dfe5f97c33a2` (recomputed equal; 655 dispositions, all `active`)

Full `validate_accepted_authority` at the measuring tip: 655 cohort records, 598 SDK-provenance
records, 655 active dispositions — the instrument passes on current main.

## 4. Reconstructed cohort / provenance / projection (bound into the capsule)

Independently recomputed from the accepted authority's embedded canonical artifacts (byte-validated
against the mission bindings):

- Original cohort: `library/contract-drift-original-cohort-v1.json`, 1,692,125 bytes, SHA-256
  `565cd84a9a5d266f61b66bd7965e0a036e4817ef5fed32edb8c41a2dea6cc208`; 655 records
  (74/524/11/17/29 across `python_sdk_drift`/`typescript_sdk_drift`/`routes_missing_in_spec`/
  `routes_orphaned_in_spec`/`sdk_missing_from_both`); ratified ID-set digest
  `c1235670c183b1887ba3fe4280fa0320f9fd6f4a85b8f346d4332ac2aebbe269` (47,226-byte canonical set payload).
- SDK provenance: `library/contract-drift-sdk-provenance-v1.json`, 898,099 bytes, SHA-256
  `21ae1c30200cda6df51dbca7053bbbbde6241ab78a73347b0fe5e4d2ed79f07f`; 598 records, 690 exact
  source occurrences, 12 multi-atom records, 0 missing provenance, 75 core / 523 extended;
  record-digest-set `0d30ce3b083344f19949da12ae2d92952757af0aea800b3f99d447458b6eeba0` (40,143 bytes);
  partition ID-set digests: core `b3a1755f027c998d507f13f3ba9093f769cea8720d44bfac12be6beccd626787`,
  extended `bb1fc41548778022dab3041bc05fc40a4da239a1bd4ad8b1ccbcd1007d90b252`,
  sdk `51a963079136a92a86485b56f6cef42aafc7749bfad146ce5fb37293524c5762`.
- Operation projection: 655 memberships, 666 edges total; the 57 path-level memberships carry 68
  edges with route-edge distribution 48x1 / 8x2 / 1x4 (9 multi-edge originals, maximum 4);
  record-digest-set `2d6790a6f825c53047639d9433f40e3e10b5bfc9e357bcd161f6b341134775e5` (43,968 bytes).

## 5. Historical evaluation under accepted authority (the nonconformance facts)

Running the accepted receipt analyzer path (`--mode receipt`, i.e. `validate_accepted_authority`
with `live_ref=<source>` and `residue_ref=<source>^`) against the exact historical trees
fails closed — this is the truthful `historical_nonconforming` result, not an error in the record:

- At squash merge `0b28f68b...` (receipt semantics vs first parent `e448b840...`):
  `status=fail`, `error_code=accepted_authority_invalid`, diagnostic exactly
  `Duplicate baseline entry: python_sdk_drift:GET /api/podcast/episodes/{param}`.
- At first parent `e448b840...`: same fail-closed duplicate-entry diagnostic.

Root cause: both historical adjacent trees carry a duplicated
`GET /api/podcast/episodes/{param}` entry in `scripts/baselines/verify_sdk_contracts.json`.
That duplicate was removed one commit later by squash `070cfd4f92dacb2b379e5d94666cb303318e0357`
(PR #9354, "dedupe verify baseline + fail closed on duplicate baseline entries",
2026-07-16T20:20:16Z), which is also the commit that INTRODUCED the fail-closed duplicate guard
the accepted authority now enforces. Additionally, the required `contract-drift-pr-delta`
admission context did not exist when #9320 merged (its CDG admission completed after settlement),
which is why the only accepted disposition is `historical_nonconforming`.

## 6. Reconstructed first-parent semantic delta (deduplicated informational plane)

With the single duplicated literal deduplicated (set semantics — the same normalization the
inventory uses), measured at each exact historical tree against the immutable 655-record cohort:

| Measurement | First parent `e448b840...` | Squash merge `0b28f68b...` |
|---|---|---|
| Witness-baseline blobs (`verify_sdk_contracts.json`, `validate_openapi_routes.json`, `check_sdk_parity.json`, `contract_drift_program.json`) | blob-identical across the interval (`74be5e25...`, `620a2c0a...`, `0a0a9620...`, `27c1bfb6...`) | identical |
| Deduplicated live witness keys | 517 | 517 |
| In-cohort witnesses | 517 (69/420/11/17/0 by category) | 517 (identical set) |
| In-cohort witness set SHA-256 | `5637d1027e050d15fa11f3c4be0a770cfee7e92f5c628dc0a5272d49cf0ee148` | `5637d1027e050d15fa11f3c4be0a770cfee7e92f5c628dc0a5272d49cf0ee148` |
| Outside-cohort residue | 0 | 0 |
| Added / removed witness keys vs first parent | — | none / none |

Semantic delta conclusion: the exact first-parent->squash change touched only
`aragora/server/handlers/social/{__init__,sharing}.py` and `tests/handlers/social/test_sharing.py`
(the VAL-P4A-025 symbol-level deprecation shim + tests). Every governed CDG surface — witness
baselines, cohort membership, categories, provenance, projection, active inventory — is
byte-identical or set-identical across the interval: `governed_surface_delta=none`. No
`original_record_id` was added, removed, or replaced. (This measurement is informational
reconstruction under accepted authority; it does not and cannot retroactively admit the PR.)

## 7. Historical execution identities and required-context snapshot

From the historical merge record at head `aba6b14c...` (all runs event `pull_request`, attempts
enumerated from 1):

| Required context | Run (`workflow_run_id`) | `run_attempt` | Job ID | Check-run ID | Conclusion |
|---|---|---|---|---|---|
| lint | 29524359563 (Lint) | 1 | 87709243174 | 87709243174 | success |
| typecheck | 29524359563 (Lint) | 1 | 87709180560 | 87709180560 | success |
| Generate & Validate | 29524359572 (OpenAPI Spec) | 1 | 87709726971 | 87709726971 | success |
| TypeScript SDK Type Check | 29524359727 (SDK Tests) | 1 | 87709013895 | 87709013895 | success |
| sdk-parity | 29524359665 (SDK Parity Check) | 1 | 87709276751 | 87709276751 | success |
| aragora-merge-quorum | 29524359568 (Aragora Merge Quorum) | 3 (attempts 1=failure, 2=failure, 3=success) | 87728267780 | 87728267780 | success |

Historical settlement status (recorded fact only; supplies no forward chronology/no-admin proof):
`aragora/human-settlement` status ID `50605989577`, state `success`, creator `scarmani`,
created `2026-07-16T19:18:16Z`, description "Tier 4 exact-head human-risk settlement recorded for
PR #9320". CDG advisory run at the head: Contract Drift Governance run 29524359684 attempt 2
success (attempt 1 cancelled) — the legacy advisory gate, not `contract-drift-pr-delta`.
Non-required Metrics Drift run 29524359685 attempt 2 failed (pre-existing advisory, out of scope).

## 8. Durable receipt capsule (published)

The canonical durable artifact is the published immutable GitHub Release
`backfill-0b28f68b9f4d204ae14814169093723ea84c1364` (release API ID 363450207, published
2026-08-01T06:35:28Z, `draft=false`, `prerelease=false`, `immutable=true`), whose git tag points
directly at merge commit `0b28f68b9f4d204ae14814169093723ea84c1364` (the first-parent main commit
this receipt is keyed by). Tag-name note: GitHub's pre-receive rules reject branch/tag names
consisting of exactly 40 (or 64) hex characters, so a bare-SHA tag is impossible on the platform;
the capsule tag therefore embeds the full merge SHA behind the fixed `backfill-` prefix, the tag
object resolves to that exact SHA, and `payload.json`/`manifest.json` bind the bare SHA in
`merge_sha`/`first_parent_sha`.

Exactly three assets in canonical bytes (compact sorted-key UTF-8 JSON, no BOM, one terminal LF;
`checksums.txt` = `"<sha256>  manifest.json"` and `"<sha256>  payload.json"` lines), all
byte-verified after upload (download digest == local digest) and re-verified by
`gh release verify` (per-asset sha256 match):

- `payload.json` — 10,437 bytes, SHA-256
  `9c238f0aa2a7c69547a78900c6aba95f4771bdd8df68105de6e9a61cc2a4523e`, asset API ID 497649474;
  schema `contract-drift-historical-first-parent-backfill-v1`; binds every fact in §§1-7 plus the
  publication-time passing `refs/heads/main` rule-suite record (ID 3525237532,
  `after_sha=486b24fb...`, `result=pass`) and the successful `contract-drift-main-receipt`
  execution identity current at publication (run 30687788027 attempt 1, job/check 91336914751).
- `manifest.json` — 299 bytes, SHA-256
  `b2c81cc56fba3749756690a39241153c90d17bc6b2ecfdc3c38c0bc1cdafa7b5`, asset API ID 497649469;
  schema `contract-drift-historical-backfill-manifest-v1`; binds `pr`, `first_parent_sha`,
  `merge_sha`, `payload_byte_length`, `payload_sha256`.
- `checksums.txt` — 159 bytes, SHA-256
  `0d3c7dc932f6860335edac2df08104107f63a78459341ff0fd4822bc19845d56`, asset API ID 497649488;
  canonical two-line digest list.

Future GitHub Release immutability was re-verified immediately before publication
(`GET /repos/synaptent/aragora/immutable-releases` -> `{"enabled":true,...}`), and enforcement was
verified live on the published release: asset deletion is rejected with HTTP 422 "Cannot delete
asset from an immutable release", and tag/target/asset mutation and tag reuse fail at the
platform (release metadata like the display name remains editable; the capsule identity — tag,
target SHA, and asset bytes — is immutable). `actions/attest@v4` Sigstore
provenance for these exact asset bytes is produced by the Tier-4 CDG boundary workflow when it
lands (attestation binds by digest and is additive; it never mutates the immutable capsule) —
at publication `gh release verify backfill-0b28f68b9f4d204ae14814169093723ea84c1364` succeeded
(release attestation loaded from the GitHub API; all three asset digests verified) while
`gh attestation verify` reported no SLSA-provenance attestation for the asset digests (HTTP 404 —
truthful: the boundary workflow does not exist yet), and the `route_truth` boundary (sole
VAL-CDG-017 owner) revalidates the complete backfill -> route-core -> OpenAPI-rearm sequence
including capsule authentication.

## 9. Reproduction

All measurements run from a fresh detached worktree of `origin/main` (`git worktree add --detach
/tmp/... origin/main`) using only the accepted-authority bytes pinned in §3:

```bash
# identities
git cat-file -p 0b28f68b9f4d204ae14814169093723ea84c1364   # tree + parent e448b840...
git rev-list --first-parent origin/main | grep -n 0b28f68b  # first-parent chain membership
git diff --numstat e448b840dad0... 0b28f68b9f4d...          # +115/-3 across 3 files
# truthful historical evaluation (fails closed with the duplicate-entry diagnostic)
python3 scripts/check_contract_drift_ratchet.py --mode receipt \
  --ref 0b28f68b9f4d204ae14814169093723ea84c1364 --json
# capsule verification
gh release view backfill-0b28f68b9f4d204ae14814169093723ea84c1364 -R synaptent/aragora
gh release verify backfill-0b28f68b9f4d204ae14814169093723ea84c1364 -R synaptent/aragora
gh api repos/synaptent/aragora/git/ref/tags/backfill-0b28f68b9f4d204ae14814169093723ea84c1364 \
  --jq .object.sha                           # == 0b28f68b9f4d204ae14814169093723ea84c1364
shasum -a 256 manifest.json payload.json   # must match checksums.txt
```
