# PR #9320 Successor Historical-Backfill Runbook

Status: preparation only. This document does not authorize workflow dispatch, Tier-4 settlement,
merge, immutable publication, attestation, or a claim that the successor capsule is authenticated.
Those terminal actions belong to `cdg-9320-successor-backfill-capsule-finalization` after a later
exact PR/head/receipt/release-byte delegation.

## Frozen historical identity

| Field | Exact value |
|---|---|
| Repository | `synaptent/aragora` |
| PR | `9320` |
| Recorded PR base | `14d1ef53e23c5466c0491ed93f72752944c78cd4` |
| PR head | `aba6b14c94eca3a9c825b1a303ea67684d5f8daa` |
| Squash merge | `0b28f68b9f4d204ae14814169093723ea84c1364` |
| Merge first parent | `e448b840dad03ee28accd218c14a27fa8b87c7b4` |
| Head tree | `e5c6c3d07a918cf43fffed6d4a9f472bc10a674a` |
| Merge tree | `79c1c374eed261c42468dc526d837e726e73425a` |
| First-parent patch | canonical full-index Myers diff with three context lines: `6054` bytes, SHA-256 `7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4` |
| Old immutable release | API ID `363450207`, tag `backfill-0b28f68b9f4d204ae14814169093723ea84c1364` |
| Successor tag | `backfill-v2-0b28f68b9f4d204ae14814169093723ea84c1364` |

Release `363450207` is immutable superseded historical evidence. Never edit, replace, delete,
reuse, or upload to it.

## Preparation outputs

The repository provides:

- `scripts/build_contract_drift_historical_backfill.py`, the canonical builder/verifier;
- `scripts/schemas/contract-drift-historical-backfill-capsule-v2.schema.json`, the strict payload
  schema;
- an exact-pair `workflow_dispatch` path in `Contract Drift Governance` that fetches only
  `refs/pull/9320/head`, verifies it equals the supplied immutable head SHA, and uploads the
  successful raw analyzer result;
- a completion-dispatched `Contract Drift Historical Backfill Finalizer`: after the producer's
  analyzer upload, its last step submits only the run-level analyzer artifact ID plus producer
  run/attempt/job IDs to a second workflow. Because `workflow_dispatch` queues asynchronously, the
  second workflow can authenticate that the producer run/job/check genuinely reached completed
  success, re-authenticate the six historical contexts, and upload the complete canonical receipt
  envelope;
- `backfill-v2-<merge_sha>` support in the manual `actions/attest@v4` signer workflow, with the
  successor tag targeting the merged implementation SHA and a separate exact `source_digest`
  input binding the signer workflow bytes to that same implementation SHA.

The builder emits exactly `manifest.json`, `payload.json`, and `checksums.txt`. Canonical JSON is
UTF-8 without BOM, compact sorted-key serialization, and exactly one terminal LF.

## Finalization checkpoint P0: exact authority

Before any remote mutation, record:

1. the parked Tier-4 implementation PR number, exact base SHA, exact head SHA, and complete changed
   paths;
2. a current unconsumed operator delegation naming that exact pair and the authorized actions;
3. `origin/main`, repository future-release immutability, authenticated `Administration:read`, and
   rule-suite access;
4. the OpenAPI release-envelope finalization terminal evidence required by the feature precondition;
5. release `363450207` identity and unchanged immutable status.

Any mismatch or movement stops the procedure.

## Finalization checkpoint P1: settle and merge implementation

Use the repository Tier-4 chronology only:

1. authenticate exact base/head, checks, discussion, and evidence;
2. post only delegated byte-exact model evidence;
3. run the pre-settlement quorum;
4. perform one delegated settle-only human settlement;
5. obtain a distinct post-settlement quorum success;
6. require the final `settle_tier4_pr.py --check` result to pass;
7. re-read `origin/main == BASE_SHA`;
8. merge normally, non-admin, with `--match-head-commit HEAD_SHA`;
9. prove merge first parent equals `BASE_SHA` and merge tree equals the reviewed head tree.

Do not continue from a partial or moved state. Persist the merged implementation SHA as the next
checkpoint input.

## Finalization checkpoint P2: execute the exact historical receipt

After this parked PR is normally merged, freeze that resulting merge SHA as `IMPLEMENTATION_SHA`.
Dispatch the merged `Contract Drift Governance` producer workflow at a branch or tag ref whose tip
is exactly `IMPLEMENTATION_SHA`. Record both the accepted dispatch ref and the resulting
`github.sha`, and require that resulting SHA to equal `IMPLEMENTATION_SHA`, with:

```text
historical_backfill=true
historical_base_sha=14d1ef53e23c5466c0491ed93f72752944c78cd4
historical_head_sha=aba6b14c94eca3a9c825b1a303ea67684d5f8daa
historical_merge_sha=0b28f68b9f4d204ae14814169093723ea84c1364
historical_first_parent_sha=e448b840dad03ee28accd218c14a27fa8b87c7b4
```

This preparation feature must not run that dispatch. GitHub accepts a branch or tag name, not a raw
commit SHA, for the `workflow_dispatch` API `ref`; the workflow still binds the analyzer and receipt
to the immutable resolved `github.sha`. The producer schedules the completion finalizer as its last
successful step after the analyzer artifact exists, passing `IMPLEMENTATION_SHA` in the canonical
producer identity. The finalizer checks out that immutable SHA, then waits boundedly until GitHub
reports the producer run and job as completed success before building the envelope. It must
authenticate the submitted artifact/run/attempt/job tuple against GitHub, including proving the
analyzer artifact ID belongs to that exact producer run; it must never authenticate its own
in-progress job as already successful. The publication finalizer must discover workflow runs
without conclusion filters, reconcile pagination, enumerate attempts, select the intended producer
run, and bind:

- workflow run ID and run attempt;
- attempt-specific job ID and check-run ID;
- `contract-drift-main-receipt-0b28f68b9f4d204ae14814169093723ea84c1364`;
- the receipt `source_sha`, which is the exact merged implementation/checker ref dispatched for
  the successful run and is intentionally distinct from the historical `merge_sha`;
- exact base/head/merge/first-parent tuple, both tree identities, byte-identical
  base-to-head and first-parent-to-merge patch digest/length, and semantic delta paths;
- all six successful historical required-context run/attempt/job/check/app identities.

The completion-triggered finalizer's uploaded `contract-drift-main-receipt.json` is itself the canonical
`contract-drift-historical-backfill-receipt-v1` envelope and can be inserted directly as the
builder input's `receipt` object. Persist those exact downloaded bytes and their digest. A failed,
cancelled, incomplete, missing-finalizer, raw-analyzer-only, or generic push receipt is terminal
failure.

## Finalization checkpoint P3: draft release and deterministic bytes

Only if the final payload requires `release_api_id`, create one unpublished draft release using the
distinct successor tag, then freeze its API ID. Never publish the draft in this checkpoint.

Build the final input document with:

- the successful P2 receipt identity, including `receipt.source_sha == authority_source_sha` and
  `receipt.merge_sha == 0b28f68b9f4d204ae14814169093723ea84c1364`;
- `release.tag_target_sha == attestation.source_digest == authority_source_sha ==
  IMPLEMENTATION_SHA`, while `release.exact_full_sha_tag` and the `backfill-v2-<merge_sha>` suffix
  remain the historical squash SHA;
- current exact-ref authority, dependency, inventory, public-symbol, route-boundary, category,
  original-ID, projection-schema, SDK-provenance, and SDK/core/extended partition digests;
- all `655` projection memberships and all `666` method-specific edges;
- the passing `refs/heads/main` rule-suite record of the implementation push, with
  `rule_suite.after_sha == authority_source_sha == IMPLEMENTATION_SHA` and `repository_name`
  normalized to `synaptent/aragora`;
- stable attestation identity claims for `actions/attest@v4`;
- non-precedential `historical_nonconforming` disposition;
- explicit supersession of release `363450207`.

Build twice into two nonexistent output paths. The builder creates each directory exclusively and
rejects a pre-existing path, extra file, symlink, or rogue subdirectory:

```bash
python3 -B scripts/build_contract_drift_historical_backfill.py \
  --repo-root "$REPO" --input "$INPUT" --authority-manifest "$AUTHORITY_MANIFEST" \
  --output-dir "$RUN1" --json
python3 -B scripts/build_contract_drift_historical_backfill.py \
  --repo-root "$REPO" --input "$INPUT" --authority-manifest "$AUTHORITY_MANIFEST" \
  --output-dir "$RUN2" --json
cmp "$RUN1/manifest.json" "$RUN2/manifest.json"
cmp "$RUN1/payload.json" "$RUN2/payload.json"
cmp "$RUN1/checksums.txt" "$RUN2/checksums.txt"
```

Record byte lengths and SHA-256 values for all three assets. Do not upload until the later
delegation names these exact bytes.

## Finalization checkpoint P4: immutable publication

Under an exact-byte publication delegation only:

1. re-query future release immutability and require `enabled=true`;
2. require the successor tag suffix to name the historical merge SHA while the tag resolves
   exactly to the merged implementation SHA that contains the signer workflow;
3. upload exactly the three frozen assets to the unpublished draft;
4. re-download and byte-compare every asset;
5. publish the successor release once, immutable, with no tag or asset reuse;
6. run `gh release verify` twice and `gh release verify-asset` for each asset twice;
7. capture the release API ID, asset API IDs, tag target, byte lengths, and digests.

No old release operation is permitted.

## Finalization checkpoint P5: attestation and rule suite

Dispatch `.github/workflows/contract-drift-boundary.yml` at the published successor tag only under
the later delegation, passing `source_digest=<merged implementation SHA>`. Require:

- `actions/attest@v4`;
- signer workflow `synaptent/aragora/.github/workflows/contract-drift-boundary.yml`;
- source digest equal to the exact merged implementation SHA that supplied the successful receipt
  and signer workflow, while the successor tag suffix and payload retain
  `0b28f68b9f4d204ae14814169093723ea84c1364` as the historical squash identity;
- predicate type `https://in-toto.io/attestation/release/v0.2`;
- repository `synaptent/aragora`;
- exact subject SHA-256 values for the three frozen assets.

Run `gh attestation verify` twice per asset. Capture the passing rule-suite ID/result immediately
and require `refs/heads/main`, `result=pass`, and `after_sha` equal to the exact merged
implementation SHA bound by the payload as `authority_source_sha` — never the historical squash
merge SHA, whose push predates the repository's rule-suite ledger and therefore has no record.
The raw rule-suites API returns the bare repository name (`aragora`, `repository_id 1126097105`);
normalize it to `synaptent/aragora` before comparing against the payload while persisting the raw
bytes unmodified.

## Finalization checkpoint P6: negative probes

All probes must fail closed:

- omitted required payload field;
- failed or cancelled receipt;
- absent/unverified attestation;
- payload, manifest, or checksum tamper;
- wrong subject digest;
- wrong signer workflow or signer SAN;
- wrong repository;
- failed, bypassed, or mismatched rule suite;
- incomplete/mutated projection edge set;
- release/tag/asset replacement, deletion, or reuse;
- movement of `main`, selected workflow run, or run attempt.

Never perform a destructive probe against release `363450207`.

## Finalization checkpoint P7: movement requery and terminal record

After all verification, re-query:

- current `main`;
- newest relevant workflow run and attempt;
- successor release/tag/assets;
- attestation subjects;
- rule-suite identity/result.

If any identity moved, restart from the last safe checkpoint rather than normalizing the movement
away. Only after stable equality may the finalizer write a terminal authenticated successor-capsule
record for the successor boundary. Preparation fixtures, synthetic IDs, or this runbook are not that
terminal record.

## Supersedes binding (fail-closed)

The capsule `supersedes` plane is bound to the frozen old-release identity rather than any
well-formed release shape:

- `supersedes.release_api_id` must equal `363450207` exactly
  (`PR_9320_SUPERSEDED_RELEASE_API_ID` in `scripts/build_contract_drift_historical_backfill.py`).
- `supersedes.tag_name` must equal `backfill-0b28f68b9f4d204ae14814169093723ea84c1364` exactly
  (`PR_9320_SUPERSEDED_RELEASE_TAG`, the v1 capsule tag of squash merge `0b28f68b…`).
- The capsule schema pins the same two values as `const` in its `supersedes` region, so a
  successor capsule cannot claim an unrelated release as its superseded historical evidence.

Builder validation and the schema both reject wrong or missing supersedes identity fail-closed;
the correct frozen identity passes. Behavior is proven by the supersedes tests in
`tests/scripts/test_build_contract_drift_historical_backfill.py`.

## Read-only git guard: `-c` allowlist (fail-closed)

The Tier-4 read-only subprocess guard in `scripts/check_contract_drift_ratchet.py`
(`_guard_subprocess_argv` / `_git_subcommand`) no longer skips arbitrary `git -c <key>=<value>`
pairs while classifying the subcommand. Inline `-c` bypasses the `GIT_CONFIG_GLOBAL=/dev/null` /
`GIT_CONFIG_NOSYSTEM=1` scrub applied in `_run_read_only`, and config keys such as
`core.fsmonitor`, `diff.external`, or `core.pager` execute arbitrary commands even under
read-only subcommands, so a wholesale skip silently voided the read-only invariant for any
future call site.

- Only the exact `key=value` literals used by this script's own call sites pass:
  `diff.noprefix=false`, `diff.mnemonicPrefix=false`, `diff.algorithm=myers`, `diff.context=3`
  (`_READ_ONLY_GIT_CONFIG_LITERALS`).
- Any other pair — including an allowlisted key with a different value, case variants, or a
  valueless key — is rejected fail-closed with
  `unsupported git -c configuration rejected: <pair>` before subcommand classification.
- The historical-receipt patch call sites (the four `diff.*` literals combined with
  `--no-ext-diff --no-textconv -O/dev/null`) remain accepted unchanged.

Behavior is proven by the guard allowlist tests in
`tests/scripts/test_check_contract_drift_ratchet.py` (command-executing pair rejection,
fail-closed variants, exact call-site argv acceptance, and literal-set pinning).

## Verify-dir binding: frozen derived-evidence constants (fail-closed)

The `--verify-dir` chain (`_verify_directory` → `validate_capsule_bytes` → `validate_payload`)
runs with no git access, so it previously only format-checked the four derived historical values
(`head_tree_sha`, `merge_tree_sha`, `first_parent_patch_byte_length`,
`first_parent_patch_sha256`) that `build_payload` recomputes against immutable git at build time.
A self-consistent capsule directory (manifest and checksums matching tampered payload bytes)
therefore verified with false historical evidence.

`validate_payload` now binds all four values to frozen constants, mirroring the exact-pair and
supersedes precedents:

- `historical_pull_request.head_tree_sha` must equal
  `e5c6c3d07a918cf43fffed6d4a9f472bc10a674a` (`PR_9320_HEAD_TREE_SHA`, the tree of PR head
  `aba6b14c…`).
- `historical_pull_request.merge_tree_sha` must equal
  `79c1c374eed261c42468dc526d837e726e73425a` (`PR_9320_MERGE_TREE_SHA`, the tree of squash merge
  `0b28f68b…`).
- `historical_pull_request.first_parent_patch_byte_length` must equal `6054`
  (`PR_9320_FIRST_PARENT_PATCH_BYTE_LENGTH`).
- `historical_pull_request.first_parent_patch_sha256` must equal
  `7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4`
  (`PR_9320_FIRST_PARENT_PATCH_SHA256`).

Each constant was re-derived from immutable git (`rev-parse <sha>^{tree}` and the exact frozen
patch argv) and verified equal to the canonical fixture before pinning. The capsule schema pins
the same four values as `const` in its `historical_pull_request` region. Any divergence is
rejected fail-closed with `... does not match the frozen PR #9320 evidence`; the canonical
frozen-value capsule still builds and verifies. Behavior is proven by the
`test_verify_dir_*` and `test_schema_historical_region_*` tests in
`tests/scripts/test_build_contract_drift_historical_backfill.py`.

## Read-only git guard: `--config-env` rejection (fail-closed)

`git --config-env=<key>=<envvar>` (and the two-token `--config-env <key>=<envvar>` spelling) is
the environment-sourced equivalent of `-c`: it sets arbitrary config keys, including
command-executing ones such as `core.pager`, `core.fsmonitor`, or `diff.external`, from inherited
environment variables. The joined form previously fell through the guard's generic option skip as
a plain `--`-prefixed token, bypassing the `-c` allowlist entirely; the separate form was only
rejected incidentally when its value token was misclassified as the subcommand.

`_git_subcommand` now rejects both spellings explicitly before the generic option skip,
fail-closed with `unsupported git --config-env rejected: <token>`. No call site in the checker
uses `--config-env`, so the exact historical-receipt patch argv remains accepted unchanged.
Behavior is proven by `test_read_only_git_guard_rejects_config_env_joined_form` and
`test_read_only_git_guard_rejects_config_env_separate_form` in
`tests/scripts/test_check_contract_drift_ratchet.py`.

## Rule-suite binding: implementation push identity (fail-closed)

`validate_payload` previously required `rule_suite.after_sha` to equal the historical squash
merge SHA `0b28f68b…`. That plane was unsatisfiable: the repository's rule-suite ledger did not
exist at the 2026-07-16 historical merge (ruleset `20156862` `cdg-boundary-main-evaluation` was
created `2026-07-31T23:08:36Z`, and the first `refs/heads/main` rule-suite record ever is
`3525237532` on `2026-08-01`), so no passing record with that `after_sha` ever existed or can
exist. Only the synthetic fixture record, which reused the merge SHA, masked the defect.

The rule-suite plane now binds the implementation push identity, symmetric with the attestation
plane: `rule_suite.after_sha` must equal `authority_source_sha` — the exact merged implementation
SHA whose `refs/heads/main` push produced the passing record — with `ref == refs/heads/main` and
`result == pass`, fail-closed on any mismatch. The capsule schema documents the same binding on
`rule_suite.after_sha`. The live implementation push
`057407297d7c7991bddb4cf16185ee3626100dd2` has passing record ID `3821290531`
(`before_sha 80671081ec1558aaf63460f39980b43601a7c44d`, `result pass`).

Repository-name normalization is explicit: the raw GitHub rule-suites API returns the bare
repository name (`"repository_name": "aragora"`, `repository_id 1126097105`), while the builder
validates the normalized `synaptent/aragora` form. Input construction normalizes the name to the
`owner/name` form (the preparation fixture does the same); the boundary-capsule precedent
persists raw API bytes bare and validates fields separately.

Behavior is proven by the rule-suite binding tests in
`tests/scripts/test_build_contract_drift_historical_backfill.py` and the schema region test in
`tests/scripts/test_contract_drift_historical_backfill_schema.py`.
