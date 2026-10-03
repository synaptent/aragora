# Generated-Docs Drift Repair and Prevention Spec

- **Date:** 2026-07-13
- **Status:** draft repair specification
- **Tracking issue:** [#9273](https://github.com/synaptent/aragora/issues/9273)
- **Observed main:** `271d84edbe6932e60507a877fcb54ff3b4b0a4be`
- **Original failing run:** [Build Documentation job 86947363443](https://github.com/synaptent/aragora/actions/runs/29288360667/job/86947363443)

## Scope

This document packages the generated-document drift reported in #9273 into an
operator-decidable repair plan. It is intentionally docs-only. It does not edit
`CLAUDE.md`, generated metric blocks, `scripts/doc_stats.py`, workflows, or
branch protection.

Both implementation options below touch `CLAUDE.md`, an approval-required
agent-governance file under
[`docs/AGENT_OPERATING_CONTRACT.md`](../AGENT_OPERATING_CONTRACT.md). Treat
either implementation as Tier 4: it needs exact protected-file approval before
implementation, fresh exact-head model review, and human settlement before
merge. Approval to write this spec is not implementation or merge authority.

## Reproduction Receipt

The Build Documentation workflow runs these commands before its
`Ensure docs are synced` assertion:

```bash
python3 scripts/doc_stats.py --write
node docs-site/scripts/sync-docs.js
```

The drift was reproduced in two separate detached worktrees at the original
main `a36cad1f060221bae788fd53b4885a76b022757f` and current main
`271d84edbe6932e60507a877fcb54ff3b4b0a4be`. Both produced the same patch:

- Diff SHA-256: `25aa44d8bc6a6341f55692f115b7e7de847bf2ad37dbad270c9e9f13e07f5835`
- Changed files: 12
- Insertions: 16
- Deletions: 16
- Canonical test count: `223,739` -> `223,768`
- Canonical Python LOC: `1,980,676` -> `1,980,901`

The exact changed paths are:

```text
CLAUDE.md
docs/CANONICAL_GOALS.md
docs/EXTENDED_README.md
docs/STATUS.md
docs/architecture/ARCHITECTURE.md
docs/status/FEATURE_DISCOVERY.md
docs-site/docs/contributing/canonical-goals.md
docs-site/docs/contributing/claude.md
docs-site/docs/contributing/extended-readme.md
docs-site/docs/contributing/feature-discovery.md
docs-site/docs/contributing/status.md
docs-site/docs/core-concepts/architecture.md
```

Reproduce from a fresh detached worktree, not a dirty shared checkout:

```bash
git fetch origin main
git worktree add --detach /tmp/aragora-9273-repro origin/main
cd /tmp/aragora-9273-repro
python3 scripts/doc_stats.py --write
node docs-site/scripts/sync-docs.js
git diff --name-only
git diff --stat
git diff --binary --no-ext-diff | shasum -a 256
```

The hash above is an observation pinned to the stated heads, not a perpetual
expected value. If `origin/main`, `docs/METRICS.md`, the generator, or a source
mirror changes before implementation, regenerate the receipt and bind any new
authority to the new main SHA and exact path set.

## Root Cause

`docs/METRICS.md` already owns exact project counts. `scripts/doc_stats.py`
reads those canonical rows and rewrites delimited metric blocks in six source
documents. `docs-site/scripts/sync-docs.js` then copies the source documents to
six site mirrors. The canonical rows advanced, but the generated consumers did
not advance in the same commit.

Two of those generated blocks are in `CLAUDE.md`:

- `claude-codebase-scale`
- `claude-test-suite`

That makes an otherwise mechanical metrics refresh cross an approval-required
governance boundary. The Build Documentation check correctly fails closed, but
routine metric drift cannot be repaired autonomously because the deterministic
output includes a protected file.

## Option A: One-Time Authorized Sync

### Proposed Diff

From the operator-approved main SHA, run the two workflow commands and commit
only their deterministic output. For the observed head, the permitted path set
is exactly the 12 files in the reproduction receipt and the expected patch hash
is `25aa44d8bc6a6341f55692f115b7e7de847bf2ad37dbad270c9e9f13e07f5835`.

Do not edit prose, generator behavior, `docs/METRICS.md`, workflows, or any
other file in the same implementation. If the patch path set or hash differs,
stop and request refreshed authority instead of broadening the repair.

### Tier and Exact Authority

This is Tier 4 and approval-required because its deterministic output edits
protected `CLAUDE.md`. The generated values are mechanical, but the file
boundary still controls authorization.

Exact implementation authority sentence:

> I authorize a bounded Tier 4 implementation of #9273 Option A from main
> `271d84edbe6932e60507a877fcb54ff3b4b0a4be`, limited to committing the exact
> deterministic output of `python3 scripts/doc_stats.py --write` and
> `node docs-site/scripts/sync-docs.js` across the 12 paths listed in the
> approved spec, including `CLAUDE.md`, with expected diff SHA-256
> `25aa44d8bc6a6341f55692f115b7e7de847bf2ad37dbad270c9e9f13e07f5835`.
> No prose, governance, generator, workflow, settlement, or merge change is
> authorized; stop if the main SHA, path set, or patch hash differs.

### Verification

1. Confirm the implementation branch starts at the authorized main SHA.
2. Run both generators and verify the exact 12-path allowlist and patch hash.
3. Run both generators a second time and verify they add no further diff.
4. Run `python3 scripts/check_docs_consistency.py` and the focused doc-stats
   tests.
5. Run `npm --prefix docs-site run build` after the repository's documented
   dependency setup.
6. Push a probe branch and require Build Documentation to pass its generator,
   docs build, and broken-link steps.
7. Collect fresh exact-head model evidence and require Tier 4 human settlement
   before merge. The implementation grant above does not satisfy settlement.

### Rollback

Revert the authorized sync commit as one unit only if the generated content is
wrong or breaks documentation. Reverting `CLAUDE.md` is another protected-file
mutation and requires exact authority. Preserve the failing run and patch
receipt; do not weaken or skip the Build Documentation assertion as rollback.

## Option B: Remove Volatile Counts from `CLAUDE.md`

### Proposed Diff

Keep exact counts canonical in `docs/METRICS.md`, where they already live, and
make `CLAUDE.md` point there without embedding volatile values:

```markdown
**Codebase metrics:** See `docs/METRICS.md` for canonical generated counts.

**Test suite metrics:** See `docs/METRICS.md` for canonical generated counts.
```

In the same bounded change:

1. Replace the two `CLAUDE.md` generated blocks with the static pointers above
   and remove their metric-block delimiters.
2. Remove only the `claude-codebase-scale` and `claude-test-suite` renderers and
   registry entries from `scripts/doc_stats.py`.
3. Add focused tests proving `doc_stats.py --write` never changes
   `CLAUDE.md`, rejects unknown remaining block keys, and still updates every
   non-protected metric consumer.
4. Regenerate the remaining source blocks and all documentation-site mirrors.
5. Keep the Build Documentation drift assertion fail-closed and unchanged.

The one-time implementation still edits `CLAUDE.md` and its site mirror. After
it lands, future canonical metric refreshes can update `docs/METRICS.md` and
ordinary generated consumers without rewriting an agent-governance file.

### Tier and Exact Authority

This is Tier 4 and approval-required because it changes protected
`CLAUDE.md` and the generator contract for that file. It does not change merge
authority or CI policy, but the protected governance boundary requires human
preapproval and exact-head human settlement.

Exact implementation authority sentence:

> I authorize a bounded Tier 4 implementation of #9273 Option B from main
> `271d84edbe6932e60507a877fcb54ff3b4b0a4be`, limited to replacing the two
> generated metric blocks in `CLAUDE.md` with static pointers to
> `docs/METRICS.md`, removing only the corresponding two renderers from
> `scripts/doc_stats.py`, adding focused non-rewrite and fail-closed tests, and
> regenerating the affected ordinary docs and site mirrors. Keep exact counts
> in `docs/METRICS.md` and keep the Build Documentation drift gate unchanged.
> No unrelated prose, workflow, settlement, or merge change is authorized;
> stop if implementation requires a broader path set or behavior change.

### Verification

1. Pin the implementation to the authorized main SHA and record the final path
   allowlist before editing.
2. Run focused doc-stats tests, including a fixture with `CLAUDE.md` present,
   and prove repeated writes leave it byte-identical.
3. Run both documentation generators twice; the second run must be idempotent.
4. Confirm `rg -n "metrics:begin claude-" CLAUDE.md` returns no matches and
   both static pointers resolve to the canonical metrics file.
5. Confirm every remaining generated block still has a registered renderer and
   every required `docs/METRICS.md` row is enforced fail-closed.
6. Run docs consistency, documentation-site build, and broken-link checks.
7. Push a probe branch and require Build Documentation to pass.
8. Collect fresh exact-head model evidence and require Tier 4 human settlement
   before merge.

### Rollback

Revert the protected pointer and generator changes together. Restore the two
renderers, restore their metric blocks in `CLAUDE.md`, rerun both generators,
and prove idempotence. Because rollback rewrites `CLAUDE.md`, it requires its
own exact protected-file authority. Do not leave block markers without
renderers or renderers without owned blocks.

## Recommendation

Prefer Option B. Option A is the smallest immediate repair, but it preserves a
design in which every metrics refresh can require special authority because a
volatile generated count lives in `CLAUDE.md`. Option B pays the protected-file
cost once, keeps canonical numbers in their existing home, and turns future
metric refreshes back into ordinary generated-doc maintenance.

If the operator needs the fastest possible main-health repair before reviewing
the generator contract, authorize Option A only. Do not combine A and B in one
implementation, and do not infer approval for either option from approval of
this specification.
