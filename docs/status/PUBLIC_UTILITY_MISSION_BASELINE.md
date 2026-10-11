# Public Utility Mission — Baseline Map (M0)

**Status:** DOCS-ONLY. No code, no behavior change. This document is a snapshot; it does not
modify `docs/THESIS.md`, `docs/CANONICAL_GOALS.md`, `docs/RECEIPT_CONTRACT.md`, the ODR JSON
schema, `action.yml`, or any `.github/workflows/*`.
**Snapshot date:** 2026-07-02.
**Mission:** Aragora Public Utility & DecisionReceipt Productization (`mission.md` /
`architecture.md`). This is the M0 deliverable: a map of the public-utility surface *as it exists
today*, plus a proposed bounded-PR sequence for M1–M10 and the live PR-collision list to respect
while executing it.

Every factual claim below was verified directly against `origin/main` at commit `d780bd4898`
(2026-07-02) using `grep`/`diff`/`wc`/`gh` — see §8 for the exact commands. Nothing here is
aspirational; where a capability does not exist yet it is labeled a **gap**, not implied to ship.

> **Correction (2026-07-04):** §3.1, §3.3, and §7 below describe `aragora-verify` PyPI
> publishing as "pending" as of the 2026-07-02 snapshot. That premise was **false even
> at snapshot time**: Trusted Publishing published `aragora-verify`; 0.1.0 has
> been live on PyPI since **2026-06-29T23:32Z** (GitHub release
> [`aragora-verify-v0.1.0`](https://github.com/synaptent/aragora/releases/tag/aragora-verify-v0.1.0),
> not yanked), and 0.1.1 is now the latest version. `pip install
> "aragora-verify>=0.1.1"` works from the public index today. Self-verify:
> `python3 -m pip index versions aragora-verify` or
> `curl -s https://pypi.org/pypi/aragora-verify/json`. See
> `docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md` for the corrected verifier-install story.
> The sections below are left as originally snapshotted, with the affected passages
> marked "Corrected 2026-07-04" inline, so this document's as-of framing stays intact.

---

## 1. Receipt lineages (as-is) and the canonical statement

Aragora has **three** independent receipt implementations. This section maps all three; it adds an
explicit canonical statement without editing `docs/RECEIPT_CONTRACT.md` (quoted, not modified).

| Lineage | Module path(s) | Hashing / signing | Maturity |
|---|---|---|---|
| **Native gauntlet** | `aragora/gauntlet/receipt_models.py` (`class DecisionReceipt`, `schema_version="1.1"`); re-exported `aragora/gauntlet/receipt.py` → `aragora/receipts/__init__.py` (`from aragora.gauntlet.receipt import DecisionReceipt`) | SHA-256 over a 6-field subset (`receipt_id, gauntlet_id, input_hash, risk_summary, verdict, confidence`) → `artifact_hash`. Schema doc: `docs/schemas/gauntlet_receipt.v1.json`. | Production; used by `aragora verify` / `aragora receipt verify` and the Action wedge's dry-run quorum step. |
| **ODR (Open Decision Receipt) v0.1** | `aragora/gauntlet/odr_export.py` (`decision_receipt_to_odr`, `jcs_canonicalize`, `odr_content_digest`); schema `aragora/gauntlet/odr_schema.json` (byte-identical mirror at `aragora-verify/src/aragora_verify/odr_schema.json` — confirmed via `diff`, no drift today); spec `docs/specs/OPEN_DECISION_RECEIPT.md`; signing `aragora/gauntlet/odr_signing.py` (`generate_signing_key`, `sign_odr_receipt`, `public_key_pem`) | Digest = `SHA-256(JCS(doc − signatures))` (RFC 8785). Ed25519 detached signatures — **reserved but unused**: every shipping fixture today has `signatures: []` (gap **G1**, tracked for M2/M3). | Producer ships (`aragora receipt export --format odr`); independently verified by the standalone `aragora-verify` package. Only 2 example fixtures exist today (`docs/specs/examples/example-decision-receipt.odr.json`, `example-merge-quorum-receipt.odr.json`), both UNSIGNED. |
| **Legacy / adapter** | `aragora/export/decision_receipt.py` (re-exported as `aragora.receipts.LegacyDecisionReceipt`); separately, `aragora-debate/src/aragora_debate/receipt.py` (`ReceiptBuilder.sign_hmac`/`verify_hmac`) with its own `receipt_models.py` | HMAC-SHA256 — **not** JCS-canonicalized, **not** Ed25519 → not verifiable by `aragora-verify`. | Still used by some handlers (per `RECEIPT_CONTRACT.md`); kept for backward compatibility, not part of the public verification story. |

**Canonical statement (additive — does not edit `RECEIPT_CONTRACT.md`):**

> `docs/RECEIPT_CONTRACT.md` already declares `aragora.receipts.DecisionReceipt`
> (implementation target `aragora.gauntlet.receipt.DecisionReceipt`) canonical **for new
> internal-integration code**. This mission's public-facing story is additive and compatible:
> **native gauntlet `DecisionReceipt` = canonical INTERNAL record. ODR v0.1 = canonical PUBLIC /
> portable artifact**, produced from the internal record via `decision_receipt_to_odr`. The
> legacy `aragora.export.decision_receipt` and `aragora-debate` receipts are adapters/legacy —
> neither is JCS/Ed25519-verifiable. No change to the top-line claim or to `RECEIPT_CONTRACT.md`
> is required to state this; M2 will add a dedicated reconciliation doc under `docs/receipts/` or
> `docs/specs/` that says so explicitly and adds the missing verdict-state fixtures.

Curated regression gate for this area (re-verified fresh for this baseline, 2026-07-02):
`tests/cli/test_verify.py tests/export/test_decision_receipt.py tests/gauntlet/test_receipt.py
tests/gauntlet/test_odr_verify.py tests/gauntlet/test_odr_verify_schema.py` → **229 passed**;
`aragora-verify` (`PYTHONPATH=src pytest tests`) → **52 passed**.

---

## 2. Action wedge: landed state (#8669) + residual gaps

**#8669** ("feat(action): emit verifiable Decision Receipt as a PR artifact (M2 finish)") **merged
to `main` on 2026-06-30**. Confirmed live in the current `action.yml` (root, "Aragora AI Code
Review"):

- Inputs: `emit-receipt` (bool), `receipt-reviewers` (default `'claude openai'`),
  `use-secrets-manager`, `aws-region`.
- Outputs: `receipt-path`, `receipt-verdict`, `receipt-digest`, `receipt-verified`.
- Step: "Emit decision receipt" (`if: inputs.emit-receipt == 'true'`) — dry-run quorum →
  `DecisionReceipt` → ODR export → verify → upload artifact; a follow-up step reports
  `receipt_verified != 'true'`.
- Support scripts: `scripts/emit_pr_receipt.py`, `scripts/extract_review_counts.py`.
- The two *nested* composite actions (`.github/actions/aragora-review/action.yml`,
  `.github/actions/aragora-code-review/action.yml`) have **zero** `emit-receipt` references — only
  the **root** `action.yml` can emit a receipt. Any doc that points `uses:` at a nested action for
  the receipt story is wrong.

**Residual review→receipt gaps** (none require code changes to close; all are doc/example gaps
targeted at M4):

1. **Minimal snippet.** The root README's own CI example (post-#8674 rewrite, `## The wedge`
   section) shows `uses: synaptent/aragora@<sha>` with `anthropic-api-key` /
   `openai-api-key` / `post-comment` only — **no `emit-receipt`, no `receipt-reviewers`, no
   receipt-artifact step.** There is no copy-pasteable snippet anywhere in the repo that
   demonstrates the landed #8669 flow end-to-end. `docs/GITHUB_ACTION_SETUP.md` (180 lines) has
   **zero** occurrences of `emit-receipt` either — it predates #8669.
2. **Secret-limit docs.** Nothing documents that receipts are **unsigned unless** an AWS
   Secrets-Manager ODR key is configured (`use-secrets-manager`/`aws-region`), or that
   `receipt-reviewers` defaults to `'claude openai'` — families that are **not reachable** in this
   mission's environment (ANTHROPIC_API_KEY/OPENAI_API_KEY absent; reachable = OpenRouter, Mistral,
   xAI/Grok, Gemini) and, more generally, may not be reachable for any adopter who lacks those two
   specific provider keys.
3. **Opt-in signing.** `odr_signing.py` proves sign→verify end-to-end, but no doc states that
   signing must stay **opt-in** — flipping a shipping default to "signed" would turn
   `aragora-verify`'s exit code from 0 (unsigned, WARN) to 3 (signed, no `--pubkey`) for every
   consumer who doesn't yet have the public key, silently breaking the Action's own verify step.
4. **Missing pubkey endpoint.** `docs/specs/OPEN_DECISION_RECEIPT.md` and related docs reference
   pubkey-distribution endpoints (`GET /.well-known/aragora-odr-signing-key`,
   `/api/v2/receipts/signing-key`) that **do not exist** in `aragora/` (confirmed: no route
   definitions found; only unrelated hits in `odr_signing.py`, `openclaw` integration files). The
   only working no-trust path today is manual `--pubkey <file.pem>`. (`POST
   /api/v2/receipts/{id}/verify-signature` exists but validates the *native* receipt, not ODR.)

---

## 3. Front-door state

### 3.1 README.md — rewritten via merged #8674

**#8674** ("docs(readme): DRAFT trim to control-plane narrative (M3 — needs founder sign-off)")
**merged 2026-06-29** and fully rewrote the front door (529 lines today). Confirmed present on
`main`:

- Wedge framing: `## The wedge: a governance gate for AI-written code` (line 38) — the CI-review
  wedge is now the README's second major section, ahead of the "full vision."
- Honesty apparatus survives and is **intact**: `### Proof ladder — how to verify every claim here`
  (line 215) and `### Honest current state *(docs/HONEST_ASSESSMENT.md, docs/GA_CHECKLIST.md)*`
  (line 503). Both section headings exist verbatim. This satisfies the mission's non-negotiable
  invariant (architecture.md §5.1) — the mission must not delete or water down this content.
- A PyPI badge (`https://pypi.org/project/aragora/`) is present for the root `aragora` package; at
  snapshot time the verifier row in the README's own comparison table stated `aragora-verify`
  "PyPI publish pending". **Corrected 2026-07-04:** that line (and the premise behind it) was
  false even at snapshot time — see the correction note above; README's own row is fixed by a
  separate PR (#8824).

### 3.2 pyproject.toml — "Decision Integrity Platform" drift persists

Unlike README.md, the root `pyproject.toml` was **not** touched by #8674 and still carries the old
tagline:

```
description = "Decision Integrity Platform — multi-agent vetted decisionmaking with audit-ready receipts"
readme = {text = "# Aragora\n\nThe Decision Integrity Platform: orchestrate multi-agent debates
          against your org's knowledge and deliver audit-ready decision receipts. ..."}
```

`CLAUDE.md`'s "Project Overview" line ("Aragora is the **Decision Integrity Platform**...") carries
the same phrase but is an operator-gated file (never edit without approval). The README itself no
longer uses this phrase anywhere in its 529 lines — so the front door has **two conflicting
positioning statements live simultaneously**: the rewritten README ("governance and review layer",
audit-layer/wedge framing) vs. the packaging metadata's `pip show aragora` description ("Decision
Integrity Platform"). This is the concrete M1 target (parked PR — `pyproject.toml` collides with
open PR #8713, see §7).

### 3.3 Four distributions + install paths (as documented today)

| Distribution | `pyproject.toml` path | Version | Install path documented today |
|---|---|---|---|
| `aragora` | `pyproject.toml` (root) | 2.9.0 | `pip install aragora` (PyPI, badge confirms) or `pip install -e .` from a clone (`INSTALL.md`) |
| `aragora-debate` | `aragora-debate/pyproject.toml` | 0.2.3 | `pip install aragora-debate` (`docs/quickstart.md`) — small standalone debate wedge |
| `aragora-sdk` | `sdk/python/pyproject.toml` | 2.9.0 | `pip install ./sdk/python` (local; no PyPI badge found for this one) |
| `aragora-verify` | `aragora-verify/pyproject.toml` | 0.1.0 (snapshot); 0.1.1 latest | **Corrected 2026-07-04 — PUBLISHED:** `pip install "aragora-verify>=0.1.1"` installs the current verifier from PyPI (0.1.0 live since **2026-06-29T23:32Z**, GitHub release `aragora-verify-v0.1.0`; 0.1.1 is now latest; self-verify `python3 -m pip index versions aragora-verify` or `curl -s https://pypi.org/pypi/aragora-verify/json`). From-checkout alternatives remain available: `cd aragora-verify && PYTHONPATH=src python -m aragora_verify <file>`, or `pip install ./aragora-verify` for a local console script. *(Snapshotted 2026-07-02 as "no release has been run yet" — that premise was false; see the correction note near the top of this document.)* |

A packaging-level drift also exists but is not a docs problem: `aragora-verify`'s runtime floor is
`cryptography>=41.0` while the root `[tool.uv] constraint-dependencies` floor is `>=48.0.1` (fixes
GHSA-537c-gmf6-5ccf) — flagged as gap **G6**, a prepared/parked deps PR for M5, not this baseline.

### 3.4 Strategy-doc sprawl (front-door-adjacent)

At the repo root of `docs/`, five separate top-level strategy/roadmap documents currently coexist
with no single canonical pointer between them: `OMNIVOROUS_ROADMAP.md`, `ROADMAP_30_60_90.md`,
`ROADMAP_EVOLUTION.md`, `STRATEGIC_ANALYSIS.md`, `STRATEGY_INDEX.md`. `docs/plans/` additionally
holds **123** dated planning documents. None of this is in M0's scope to fix — it is recorded here
because it is part of "the front door state" a newcomer hits immediately after the README, and
directly informs the M6 docs-collapse sequencing.

---

## 4. Docs sprawl & contradictions

### 4.1 Scale

- **1,029** tracked Markdown files under `docs/` (recursive, `git ls-files 'docs/*.md' | wc -l`).
- **64** loose top-level `docs/*.md` files (non-recursive: `git ls-files ':(glob)docs/*.md'`).
- **64** top-level subdirectories under `docs/` (`ls -d docs/*/ | wc -l`).
- `docs/status/` alone holds **173** files at its top level (**275** including subdirectories),
  including dozens of one-off `SESSION_BRIEF_*`/`*_RECEIPT_*` artifacts from prior automation runs
  and a 167,882-byte `STATUS.md`.

### 4.2 Top contradictions observed

1. **Two competing "canonical" onboarding docs.** `README.md` points new users to
   `docs/quickstart.md` (the newer, actively-maintained canonical quickstart — confirmed:
   `docs/guides/QUICKSTART.md` is *already* a redirect stub pointing to it). But `docs/INDEX.md`
   still points to `guides/GETTING_STARTED.md` — a **separate, 602-line, differently-dated**
   ("Last Updated: 2026-01-27") document that calls *itself* "the canonical onboarding guide" and
   was never folded into the `docs/quickstart.md` consolidation. Two landings (`INDEX.md` vs.
   `README.md`) route to two different "canonical" starting points.
2. **`docs/INDEX.md` has zero receipt/verifier linkage.** Confirmed via grep: `docs/INDEX.md`
   contains **no** occurrence of `aragora-verify`, `OPEN_DECISION_RECEIPT`, or `receipts` — the
   mission's core spine (review → receipt → verify) is undiscoverable from one of the two
   first-class docs landings.
3. **Verifier-command ambiguity.** Three distinct commands all get called "verify" across docs:
   the standalone `aragora-verify` (ODR, exit 0/1/2/3), the in-tree `aragora verify` (native
   receipt), and `aragora receipt verify` (also native receipt). Nothing in `docs/INDEX.md` or
   `docs/guides/GETTING_STARTED.md` disambiguates them (M3 target).
4. **Action snippet vs. landed capability.** As in §2.1, the README's own Action example doesn't
   exercise `emit-receipt`, so a reader following the front door literally never sees the
   receipt-emission capability that #8669 shipped.
5. **Version-number drift in prose tables** (outside packaging metadata, which is already
   internally correct at 2.9.0/0.2.3/0.1.0/2.9.0): several non-README docs still reference older
   `aragora`/`aragora-debate` version numbers in comparison/install tables, and none of the
   surveyed distribution tables lists `aragora-verify` as a row at all (M5 target).
6. **`docs/README.md` vs. `docs/INDEX.md`**: two files that are both plausible "landing pages" for
   the `docs/` tree with overlapping but not identical content and no cross-reference declaring
   one canonical (M6 target).

### 4.3 Not a contradiction (precedent worth reusing)

`docs/guides/QUICKSTART.md` is already a clean example of the pattern M6 should generalize: it was
turned into a short redirect stub ("Consolidated into the canonical quickstart... kept so existing
links keep working") rather than deleted. `docs/archive/` already exists as a destination
directory. Both are useful precedents, not gaps.

---

## 5. Existing benchmark & case-study assets

These are pre-existing proof-adjacent assets the M8/M9 workers should build on rather than
duplicate:

**`docs/benchmarks/`** (14 files) includes `corpus.json` (the fixed benchmark corpus manifest),
`factory_review_benchmark_manifest.json` (the manifest M9's VAL-PROOF-008 golden references point
into), `gauntlet_results.md`, `convergence_results.md`, `belief_network_results.md`,
`trickster_ab_results.md`, `admission_recovery_scenarios.json`, `auth_failure_scenarios.json`,
`benchmark_corpus_freshness.json`, `corpus_honesty_audit_2026-04-17.md` (since archived as a dated
snapshot), `corpus_rev4_staging.md`,
`rescue_productization.json`, `rescue_productization_auth_failure.md`,
`B0_PROXY_METRIC_INTERPRETATION.md`.

**`scripts/measure_*`** (7 scripts): `measure_b0_scorecard.py`, `measure_b0_progress.py`,
`measure_cost_per_settled_pr.py`, `measure_invalidation_baseline.py`, `measure_leverage_ratio.py`,
`measure_quickstart_time.py`, `measure_work_loss.py`.

**`docs/case-studies/`** (7 files): `README.md` (index), `CLAUDE.md` (contributor note),
`architecture-stress-test.md`, `gdpr-compliance-audit.md`, `epic-strategic-debate.md`,
`security-api-review.md`, `security-review.md`.

None of these currently ship a **signed, independently-verifiable ODR** artifact as evidence (they
predate the ODR spec / #8669); M9 should either point to a new dogfood-produced receipt or explain
why an existing asset is illustrative-only.

---

## 6. Proposed bounded-PR sequence

One independent branch+PR per milestone deliverable, `factory/pum-<feature-id>` off `origin/main`,
≤800 LOC each, per `architecture.md` §7. Ordering respects dependencies (M2's canonical statement
should land — or at least be drafted — before M3/M4 docs cite it; M6 collapse happens after M1–M5
land so it collapses the corrected state, not the drifted one).

| Order | Milestone | Deliverable(s) | Auto-merge? |
|---|---|---|---|
| 1 | **M0** (this doc) | `docs/status/PUBLIC_UTILITY_MISSION_BASELINE.md` | Yes — docs-only |
| 2 | **M1** | `pyproject.toml` tagline/version reconciliation (parked — collides with #8713); README/THESIS consistency audit; command/verifier consistency sweep | Docs parts yes; pyproject part parked |
| 3 | **M2** | Additive receipt-reconciliation doc (native=internal canonical / ODR=public canonical); new verdict-state + signed + chain fixtures; schema-validation + verifier tests | Tests-only parts yes; doc part yes if no gated-file touch |
| 4 | **M3** | Verifier doc (install/invocation, exit-code contract, stdlib+cryptography-only, disambiguation from native `verify`); pubkey-gap issue filed | Yes — docs-only (issue filing is a `gh` action, not a file change) |
| 5 | **M4** | Action doc + copy-paste minimal `emit-receipt` snippet; secret-limit + reviewer-default documentation | Yes — docs-only |
| 6 | **M5** | Install matrix (4 distributions, per-audience); numpy test-gate note; parked packaging-deps PR (`cryptography>=48.0.1` in `aragora-verify`) | Docs part yes; deps part parked |
| 7 | **M6** | Docs collapse: resolve top contradictions (§4.2) into one canonical form each; reconcile `INDEX.md`/`README.md`/`GETTING_STARTED.md`/`quickstart.md` routing; archive stale docs via `git mv` | Yes — docs-only (subject to LOC-class splitting) |
| 8 | **M7** | Root-clutter inventory (tracked vs. gitignored) + `git mv` relocation of tracked clutter; root allowlist doc; module-quarantine proposal (no execution) | Yes — docs-only / additive |
| 9 | **M8** | Dogfood receipts on real `synaptent/aragora` PRs (reachable providers only, budget-gated) | Parked — real LLM spend, human review |
| 10 | **M9** | Benchmark (`scripts/measure_*`) + public dogfood report | Parked — real LLM spend, human review |
| 11 | **M10** | Re-audit scorecard (`docs/status/PUBLIC_UTILITY_SCORECARD.md`) comparing this baseline's values to end-of-mission values | Yes — docs-only |

Each PR stays within its milestone's scope; none touches THESIS/CANONICAL_GOALS/RECEIPT_CONTRACT,
the ODR schema, or any `.github/workflows/*` file (operator-gated — prepare only, per
`architecture.md` §5.4).

---

## 7. Live open-PR collision list (path-freeze) + resolved former freeze set

**Re-verified live via `gh pr list --state open --limit 400` at execution time (2026-07-02: 54 open
PRs total at snapshot time).** This list drifts; re-run `gh pr list` before touching any of these
paths in a later milestone.

| File(s) | Open PR(s) | Notes |
|---|---|---|
| `README.md` | **#8795** (`docs: move volatile counts into generated blocks; doc_stats owns only delimited regions (#8792)`, not draft) + **#8716** (`fix(status): narrow TW03 publication artifacts`, **draft**) | Confirmed via `gh pr view --json files`: both PRs list `README.md` in their changed-files set. M1/M6 README-touching work must rebase-check against both before pushing. |
| `pyproject.toml`, `uv.lock` | **#8713** (`chore(deps): consolidate httpx and sdk dependency bumps`, not draft) | Confirmed via `gh pr view --json files`: exactly `pyproject.toml`, `scripts/ci_install_project.sh`, `sdk/typescript/package-lock.json`, `uv.lock`. M1/M5 pyproject work is **parked**, not pushed, until this clears or the worker coordinates a rebase. |
| `action.yml` / `.github/actions/**` / `aragora-verify/**` | *(none open as of 2026-07-02)* | M3/M4/M5 doc work referencing these paths (read-only) is currently unblocked. |
| Merge-authority (`review_queue.py`, quorum/settle scripts) | ~19 Tier-4 PRs (not enumerated here — out of this mission's editing scope entirely) | Never co-edit regardless of collision status. |

**Resolved former freeze set** (context only — these are no longer live blockers):

- **#8674** — README rewrite — **MERGED** 2026-06-29 (added the "Honest current state" + "Proof
  ladder" sections; see §3.1).
- **#8692** — dependency refresh — **MERGED** 2026-06-30.
- **#8693** — `aragora-verify` PyPI publish workflow — **MERGED** 2026-06-29. **Corrected
  2026-07-04:** Trusted Publishing published `aragora-verify` after this merge; 0.1.0
  has been live on PyPI since 2026-06-29T23:32Z, and 0.1.1 is now the latest
  public-index version (see §3.3). The snapshot's original
  guidance here ("no release has actually been published yet... do not assert `pip install
  aragora-verify`") was incorrect even at the time; `pip install "aragora-verify>=0.1.1"`
  works today.
- **#8694** — read-only reconcile/settle CLI — **CLOSED, unmerged**, 2026-06-30.

Additionally, `docs/plans/2026-06-30-*.md` (once untracked scratch content) is now **tracked** repo
content, committed via #8729 — treat it as ordinary docs content, not a local artifact, if a later
milestone touches it.

---

## 8. Verification (how this baseline was produced)

All commands below were run against `origin/main` (commit `d780bd4898`, 2026-07-02) from a
throwaway worktree; none mutated the shared root.

```bash
gh pr list --state open --limit 400 --json number,title,isDraft
gh pr view 8795 --json number,title,isDraft,files
gh pr view 8716 --json number,title,isDraft,files
gh pr view 8713 --json number,title,isDraft,files
gh pr view 8669 --json number,title,state,mergedAt,closedAt   # MERGED
gh pr view 8674 --json number,title,state,mergedAt,closedAt   # MERGED
gh pr view 8692 --json number,title,state,mergedAt,closedAt   # MERGED
gh pr view 8693 --json number,title,state,mergedAt,closedAt   # MERGED
gh pr view 8694 --json number,title,state,mergedAt,closedAt   # CLOSED, mergedAt=null

grep -n '^## \|^# ' README.md                       # section map, incl. Proof ladder / Honest current state
grep -n 'description\|readme\|version' pyproject.toml
grep -n 'emit-receipt\|receipt-reviewers\|receipt-path\|receipt-verdict\|receipt-digest\|receipt-verified' action.yml
diff aragora/gauntlet/odr_schema.json aragora-verify/src/aragora_verify/odr_schema.json  # identical
grep -n 'cryptography' pyproject.toml aragora-verify/pyproject.toml
git ls-files 'docs/*.md' | wc -l                    # 1029 (recursive)
git ls-files ':(glob)docs/*.md' | wc -l             # 64 (top-level only)
grep -rn 'well-known/aragora-odr-signing-key\|signing-key' aragora/  # no route implementation
grep -c 'emit-receipt' docs/GITHUB_ACTION_SETUP.md  # 0

# curated regression gate, re-run fresh for this baseline:
.../venv/bin/python -m pytest tests/cli/test_verify.py tests/export/test_decision_receipt.py \
  tests/gauntlet/test_receipt.py tests/gauntlet/test_odr_verify.py \
  tests/gauntlet/test_odr_verify_schema.py -q     # 229 passed
cd aragora-verify && PYTHONPATH=src .../venv/bin/python -m pytest tests -q   # 52 passed
```

This document makes no code claims that require re-running beyond the above; it is a map, not a
tutorial. Milestones M1–M10 are responsible for keeping their own doc claims runnable per
`docs-worker`'s consistency rule.
