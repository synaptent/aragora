# Module Quarantine Boundary — Proposal (M7 legibility)

**Status:** **PROPOSE-ONLY.** This document is a proposal. It executes **zero** structural moves.
No files are renamed, relocated, gated, deprecated, or refactored by it. No `aragora/**` paths are
moved into any quarantine directory, no scripts/** are rewired, and no imports/charters are amended
in the same change. Operators/adopters who want any of the *consequences* described in §3-§6 to
ship must do so in a **separate, sequenced PR** with its own review and scoring — this document is
intentionally inert so reviewers can argue about the boundary shape without committing to (or
arguing over) the relocation cost.

**Author:** docs-worker (factory/pum-m7-module-quarantine-proposal)
**Mission:** Aragora Public Utility & DecisionReceipt Productization, milestone M7 — repo legibility.
**Companion docs:**
- `docs/architecture/ARCHITECTURE.md` — descriptive layer model (hand-curated overview)
- `docs/architecture/INTENDED_ARCHITECTURE.md` — operator-gated intent charter (`charters.yaml`)
- `docs/governance/MODULE_TIER_DRIFT_GUARDIAN.md` — current tier drift tripwire (tier movement only,
  not count drift; cf. its **rejected** blanket auto-regen plan, §"Guardian options")
- `aragora/module_tiers.yaml` — auto-generated maturity classification (144 top-level `aragora/*`
  packages: 21 core, 91 integrated, 29 experimental, 3 deprecated)

The boundary set below is the proposal half of milestone M7 — repo legibility. The companion
`factory/pum-m7-root-clutter-relocation` PR handles actual tracked-clutter relocations; this doc
proposes only the boundary model.

---

## 1. The problem this proposal names (not solves)

The Aragora `aragora/` tree currently exposes **144** top-level packages. The existing
maturity tiering — `core` (21) / `integrated` (91) / `experimental` (29) / `deprecated` (3) —
distinguishes *how mature* each package is, but does **not** state *which boundary it belongs to*
or *which contract it owes*:

1. **Maturity is not a boundary.** A `tier: integrated` module can be (a) on the public
   utility surface, (b) on the CI gate, (c) a receipt-emission dependency, (d) an SDK re-export,
   (e) a private internal subsystem, or (f) a contributor scaffolding. The tier label says
   "shipped and wired"; it does not say "owed X contract or frozen against Y change". Two
   `integrated` modules with equal importer counts can have wildly different public-API stakes.
2. **Cross-package surfaces leak across tiers.** The receipt spine (`aragora/gauntlet`) is
   consumed by the Action wedge, by the in-tree ODR verifier, by `aragora.receipts` re-exports,
   by `aragora/server/handlers/*`, and by `aragora-debate`. None of those consumers is itself a
   "receipt boundary" — they merely *depend on* one. Cross-tier coupling is invisible from
   `aragora/module_tiers.yaml` alone.
3. **The historical 145→50 module-reduction goal is parked.** Earlier strategy notes used
   the then-current 145 top-level modules as the baseline for "Reducing the 145 top-level
   modules to ~50 (M3 quarantines behind a boundary; full re-architecture is deferred)."
   The generated inventory is now 144; the quoted 145 remains the historical goal label,
   not a competing current count. That target is *the destination state* this proposal
   hand-waves toward; we are **not** proposing to execute it.
4. **Adopters cannot navigate by boundary.** The current maps — `CLAUDE.md` module index,
   `EXTENDED_README.md`, `STATUS.md`, `module_tiers.yaml`, `charters.yaml` — describe modules
   by *name* and *tier*, not by *what an adopter has to know to depend on them*. A reader who
   lands on `aragora/agents/api_agents/anthropic.py` has to discover, by import-graph grep,
   whether the path is part of the public utility surface or an internal wiring detail.

This proposal introduces a **six-boundary quarantine classification** layered on top of the
existing tier classification. It does not replace tiers; tiers describe maturity, boundaries
describe *what a module owes and to whom*.

---

## 2. The six-boundary set (what this proposal names)

Each boundary is named, given a scope statement, a candidate aragora-* and external path list,
the contract its modules owe, and the "what is explicitly NOT in this boundary" notes. No entry
below implies that relocations or contract enforcement happen in this PR — these are
**proposal slots**.

### Boundary 1 — `core` (type-system + mainline orchestration)

**Scope:** The root type hierarchy, the Arena mainline, persistent state, and the modules that
**every other surface transitively imports**. A change here is a foundation change: every adopter
sees it.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| type hierarchy | `aragora/core/`, `aragora/core_types.py`, `aragora/errors.py`, `aragora/exceptions.py` | root type bundle; the "load bearing" override_reason row in `aragora/module_tiers.yaml` |
| agent factory | `aragora/agents/` (including `calibration.py`) | the registry of 46+ agent types; Boundary 4 consumes calibration data without splitting ownership of the package |
| persistent state | `aragora/memory/` (including `consensus.py` and `coordinator.py`) | the persistent substrate for debates; Boundary 4 consumes post-debate bookkeeping without splitting ownership of the package |
| knowledge substrate | `aragora/knowledge/` (bridges, mound/, adapters/) | the unified knowledge management plane |
| settings/allowlist | `aragora/config/` | Pydantic settings + agent-type allowlist — load-bearing |
| store layer | `aragora/storage/`, `aragora/db/`, `aragora/persistence/` | persistence layer |
| observation | `aragora/observability/` (metrics, tracing, slo, logging) | telemetry re-exported as `aragora.telemetry` |

**Owed contract:** semver-aware version bumps on public exports; deprecated symbols must keep a
`DeprecationWarning` shim for at least one release per the in-tree
`aragora/metrics/__init__.py` shim pattern (cf. INTENDED_ARCHITECTURE CHR-X-007).
**NOT in this boundary:** the debate engine (`aragora/debate/` + `aragora/ranking/elo.py` +
`aragora/reasoning/` primitives), the receipt spine, the Action wedge, the SDK surface, the CI gate
scripts. The debate engine belongs to Boundary 4; the other surfaces are separate boundaries below.

### Boundary 2 — `receipts+verifier` (DecisionReceipt lineage + standalone verifier)

**Scope:** The canonical-internal DecisionReceipt, the ODR v0.1 public profile, and the
no-trust standalone verifier. The boundary is **structurally offline-by-construction**:
`aragora-verify` must validate receipts *without* trusting an installed `aragora/` (it depends
only on stdlib + `cryptography`); the in-tree ODR engine must stay locked-step with the
standalone verifier's hand-rolled schema mirror.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| native receipt model + receipt helpers | `aragora/gauntlet/receipt_models.py`, `aragora/gauntlet/receipt.py`, `aragora/receipts/` (`__init__.py` re-exports `DecisionReceipt`; `lane.py` and `provenance.py` hold receipt-adjacent runtime metadata) | `schema_version="1.1"`; SHA-256 over 6-field subset → `artifact_hash`; the standalone verifier does not import the runtime helpers |
| ODR export + signing | `aragora/gauntlet/odr_export.py` (`decision_receipt_to_odr`, `jcs_canonicalize`, `odr_content_digest`), `aragora/gauntlet/odr_signing.py` (`generate_signing_key`, `sign_odr_receipt`, `public_key_pem`) | the only CLI producer is `aragora receipt export --format odr` |
| ODR verifier engine (in-tree) | `aragora/gauntlet/odr_verify.py` (landed #8389) | module docstring softened in #8871 — **not yet wired to any shipped CLI/HTTP entry point**; kept lockstep with `aragora-verify` |
| ODR schema (canonical) | `aragora/gauntlet/odr_schema.json` | byte-identical mirror at `aragora-verify/src/aragora_verify/odr_schema.json`; `diff` empty drift-check |
| standalone verifier (offline) | `aragora-verify/` (separate top-level package; sibling to `aragora/`) | stdlib + `cryptography` only; 0.1.1 live on PyPI since 2026-07-04T03:28Z; console script `aragora-verify` |
| lineaged docs | `docs/specs/OPEN_DECISION_RECEIPT.md`, `docs/specs/odr-native-mapping.md`, `docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md` | `docs/specs/**` IS mirrored by `docs-site/scripts/sync-docs.js` (PR #8953), with deliberate exclusions such as `docs/RECEIPT_CONTRACT.md` and allowlisted operator-only packets |
| example fixtures | `docs/specs/examples/` (committed `docs/specs/examples/example-decision-receipt.odr.json`, `docs/specs/examples/example-merge-quorum-receipt.odr.json`, plus the unsigned-state fixtures from #8822) | the "weak-bar/warning" surface; `signatures: []` is the current shipping default |

**Owed contract:**
- `aragora-verify` exit codes 0/1/2/3 stated verbatim across every doc that mentions them
  (per VAL-CROSS-002, verbatim contract in M3 doc, M4 Action doc, install matrix, both
  landings, quickstart, reconciliation doc).
- The two `odr_schema.json` copies stay byte-identical (VAL-VERIFY-009). When they drift, both
  copies must be regenerated in the **same PR** — never landed as separate edits.
- Signing is opt-in (flipping a shipping default to signed turns `aragora-verify` exit 0 → 3
  for every consumer that doesn't yet have the pubkey, silently breaking the Action's own
  verify step; see `docs/specs/OPEN_DECISION_RECEIPT.md` and `aragora/gauntlet/odr_signing.py`).
- Native `aragora verify` / `aragora receipt verify` are a **separate validation verb** for the
  native gauntlet receipt — they validate `artifact_hash`/signature, not an ODR
  (VAL-VERIFY-004 disambiguation).
**NOT in this boundary:** the Action wedge that *emits* receipts (next boundary); the API
handlers that expose `/api/v2/receipts/*` (server is Boundary 5); the in-tree
`aragora.server.handlers.*` which verify native or legacy, not ODR (per reconciliation doc's
"Two verifiers" section).

### Boundary 3 — `action+CI-gate` (the GitHub Action surface + receipt-emission scripts)

**Scope:** The composite root Action, the receipt-emission + collect-quorum-evidence scripts
the Action invokes, and the readonly support utilities. **The Action is the public utility
wedge**; everything inside this boundary is what an adopter drops into their own `.github/`
to get a verifiable unsigned ODR on a PR.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| root Action | `action.yml` (root, "Aragora AI Code Review") | `emit-receipt`, `receipt-reviewers`, `use-secrets-manager`, `aws-region` inputs; `receipt-path`, `receipt-verdict`, `receipt-digest`, `receipt-verified` outputs |
| nested composite actions (NOT receipt-bearing) | `.github/actions/aragora-review/action.yml`, `.github/actions/aragora-code-review/action.yml` | these have **zero** `emit-receipt` references — `uses:` for the receipt story must point at the ROOT action only (VAL-ACTION-006) |
| receipt emission script | `scripts/emit_pr_receipt.py` | dry-run quorum → `DecisionReceipt` → ODR export → verify → upload; called only by the root Action's "Emit decision receipt" step |
| review-counts parser | `scripts/extract_review_counts.py` | parses reviewer output posted to PR; called only by the root Action |
| collect-quorum-evidence | `scripts/collect_quorum_evidence.py` | groups reviewers by family for `quorum.independence.distinct_model_families`; called by the root Action and by M8 dogfood |
| Action docs | `docs/GITHUB_ACTION_SETUP.md`, `docs/guides/github-actions-review.md` | the root-vs-nested disambiguation lives here |
| CLAUDE.md cross-link | `CLAUDE.md` §"Quick Reference" — `Gauntlet` row + `Backup` row | the canonical front-door quickly locates the wedge |

**Owed contract:**
- The Action **emits UNSIGNED ODRs today.** Verified live 2026-07-07 (origin/main): the root
  `action.yml` `emit-receipt` step calls only `collect_quorum_evidence.py` +
  `emit_pr_receipt.py`; `odr_signing.sign_odr_receipt` is NEVER called from the action
  path. `use-secrets-manager` hydrates provider API keys only (`MANAGED_SECRETS` has no ODR
  signing key), not signing material. `signatures: []` reserved for future Ed25519 wiring
  (issue #8225; VAL-ACTION-003 amended).
- `receipt-reviewers` default is `'claude openai'` (`action.yml`); reviewers must be
  **reachable** providers — `claude` / `openai` defaults are not universally available
  (mission environment lacks `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`; reachable families =
  OpenRouter, Mistral, xAI/Grok, Gemini). Adopters must override with reachable families +
  keys. Stated default matches `action.yml` (VAL-ACTION-007 field-for-field check).
- No workflow/`.github/workflows/*` edit (operator-gated). Any polish to `action.yml` is
  prepare-and-park, not auto-merged (VAL-ACTION-004; ACR tier rules).
**NOT in this boundary:** the receipts themselves (Boundary 2); the API surface that exposes
`/api/v2/receipts/...` endpoints (Boundary 5); the receipt *consumer* (adopter's CI step
that uploads the artifact and reads `receipt-verified`).

### Boundary 4 — `debate+quorum` (adversarial review + heterogeneous-model consensus)

**Scope:** The adversarial review flow + the heterogeneous-model quorum mechanics. This is
**the doctrinal core** — the thing the receipts certify — but it is **not** the receipt
itself. Confusion between (4) the consensus that produces a verdict and (2) the receipt that
certifies it is the most common mental-model error an adopter hits.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| Arena + DebateProtocol | `aragora/debate/orchestrator.py`, `aragora/debate/protocol.py`, `aragora/debate/consensus.py`, `aragora/debate/phases/` | the mainline engine itself |
| team selection | `aragora/debate/team_selector.py`, `aragora/ranking/elo.py` | ELO + calibration feeds team selection |
| belief/claim primitives | `aragora/reasoning/belief.py`, `aragora/reasoning/provenance.py`, `aragora/reasoning/claims.py` | ingested by debate and by receipt `cruxes`, `quorum.dissent`, `claim` blocks |
| dissent trace capture | `aragora/debate/traces.py` | heterogeneous-family independence and dissent-bearing trace capture; calibration remains package-owned by Boundary 1 under `aragora/agents/` |
| quorum evidence (NOT a public CLI) | `aragora/swarm/quorum_evidence.py`, `aragora/swarm/merge_quorum_io.py` | the merge-gate machinery; **operator-gated Tier-4** surface; do NOT co-edit during dogfood (VAL-DOGFOOD-010) |
| judge-based consensus helper | `aragora/heterogeneity/judge.py` | judge role + family-diversity consensus |

**Owed contract:**
- A debate run produces a `verdict` + a heterogeneous-quorum history; the ODR mirrors those
  into `claim.verdict`, `quorum.participants[]`, `quorum.independence.distinct_model_families`,
  `quorum.dissent`. If the quorum produces a dissent-bearing verdict, an ODR must mirror it
  as a structured `quorum.dissent` block (or `false` for clean consensus), not elide it
  (VAL-RECON-001/003; ODR spec §6).
- The quorum machinery's surfaced families must be **disclosed**; absent disclosure flips
  the ODR to attestation: autonomous (weak-bar WARN, not FAIL — VAL-RECON-009).
- Boundary 4 consumes `aragora/agents/calibration.py` and the consensus/coordinator helpers
  under `aragora/memory/`, but those files remain package-owned by Boundary 1. Consumption
  does not create file-level ownership exceptions.
- Merge-gate / quorum-evidence code (`aragora/swarm/quorum_*`) is **Tier-4 operator-gated**.
  Workers do not self-modify this surface during dogfood (VAL-DOGFOOD-006/010).
**NOT in this boundary:** the receipts that certify a verdict (Boundary 2); the Action that
emits ODRs from a quorum (Boundary 3); the API that exposes `/api/v2/debates/*` (Boundary 5).

### Boundary 5 — `SDK+API` (Python SDK + REST/WS API + CLI)

**Scope:** The public programmer surface: the type-safe Python SDK, the FastAPI server's ~3K
operations, the CLI, and the WebSocket event stream. This is what an adopter **imports or
calls** — Boundary 4 produces results that *this* boundary exposes.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| Python SDK | `sdk/python/` (the standalone distribution); also re-exported via `pyproject.toml [tool.setuptools.packages.find]` under `aragora.client` (cf. `aragora/client/`) | `pip install ./sdk/python && python -c "import aragora_sdk"` (VAL-INSTALL-007) |
| REST/WS API | `aragora/server/` (handlers/, unified_server.py, stream/), `aragora/server/handlers/social/` (chat platform handlers) | ~3K API operations; FastAPI + uvicorn (`[gateway]` extra) |
| CLI | `aragora/cli/` (main.py, parser.py, repl.py, commands/) | console entry point `aragora` (`[project.scripts]`); verbs include `ask`, `serve`, `quickstart`, `gauntlet`, `receipt`, `verify`, `demo`, `review`, `triage` |
| WebSocket event types | `aragora/server/stream/` (190+ event types: `debate_start`, `round_start`, `agent_message`, `critique`, `vote`, `consensus`, `debate_end`) | the live debate observation interface |

**Owed contract:**
- The CLI exposes the **disambiguated** verb set: `aragora-verify` (Boundary 2 ↔ ODR),
  `aragora verify` / `aragora receipt verify` (Boundary 2 ↔ native receipt), `aragora review`
  (Boundary 4 queue → Boundary 3 emit if `--emit-receipt`), `aragora serve` (this boundary
  ↔ API), `aragora quickstart --demo` (this boundary ↔ Boundary 4 demo path). No CLI verb
  may apply to an `.odr.json` artifact without Boundary 2 install
  (`pip install "aragora-verify>=0.1.1"` per VAL-INSTALL-001/VAL-VERIFY-007).
- API public surface (`aragora/server/handlers/`, `aragora/server/stream/`): semver-aware;
  deprecated endpoints get a `Deprecation` header for at least one release before removal;
  receipt-facing endpoints (`/api/v2/receipts/...`) currently verify native-or-legacy, not
  ODR (per `docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md` "Two verifiers" section and
  `docs/specs/OPEN_DECISION_RECEIPT.md`).
- SDK versioning tracks `pyproject.toml` ([project].version); floor-pin install is
  `pip install "aragora-verify>=0.1.1"`, not `==` (per `docs/AGENT_OPERATING_CONTRACT.md`
  merge-policy convention; VAL-INSTALL-001/VAL-VERIFY-001/007).
**NOT in this boundary:** the Action's `uses:` references (Boundary 3); the SDK does not
emit receipts itself (a SDK caller invokes Boundary 3 for that); the in-tree web frontend
`aragora/live/` is out of mission scope (`docs/architecture/ARCHITECTURE.md` §7).

### Boundary 6 — `experimental+contrib+archive` (opt-in modules, community surface, deprecated)

**Scope:** Everything outside the five boundaries above, plus deprecated modules. The point
of this boundary is **fence-and-disclosure, not promotion**: a module in this boundary is
*correctly named as not-yet-canonical* — an adopter who imports it is opting in.

| Proposed slot | Current path(s) | Notes |
|---|---|---|
| experimental modules | `aragora/<pkg>` for the 29 `tier: experimental` rows in `aragora/module_tiers.yaml` (advocates, approvals, brief_engine, codex, embeddings, factory, fixtures, maintenance, moderation, monitoring, onboarding, performance, playbooks, prediction, prompts, reports, shared, sync, tasks, telemetry, tools, tournaments, trail, transcription, types, uncertainty, webhooks, work; `aragora/receipts/` is classified wholly in Boundary 2 despite its generated maturity tier) | most have ≤7 importers and ≤4 test files; no current charter pressure to graduate. Boundary ownership stays package-granular even when the generated maturity tier and proposed mission boundary differ |
| standalone contrib wedge | `aragora-debate/` (a sibling package, `pip install aragora-debate` for the legacy receipt story; cf. `docs/architecture/PACKAGING_AND_DISTRIBUTION.md` §1, §7) | the only currently-shipped contrib slice |
| dep-installed extras (DO NOT IMPORT ARAGORA-MAIN) | the `[blockchain]`, `[gateway]`, `[experimental]`, `[connectors]`, `[enterprise]` optional-dependency slices — each adds an opt-in dependency set | base install omits these by design |
| deprecated modules | the 3 `tier: deprecated` rows in `aragora/module_tiers.yaml` (`aragora/metrics/`, `aragora/operations/`, `aragora/schedulers/`); plus past movers under `docs/archive/` and `docs/deprecated/` | removal-candidate zone; `aragora/metrics` has a soft-shim `DeprecationWarning` per CHR-X-007 (the only entry binding while INTENDED_ARCHITECTURE is DRAFT) |
| archived docs | `docs/archive/`, `docs/status/` (status snapshots), `docs/internal/`, `docs/deprecated/`, `docs/migration/` (where applicable) | the docs-side analog; archived columns carry the `(Amended YYYY-MM-DD)` lineage |
| contrib patterns | `scripts/` (except `scripts/emit_pr_receipt.py`, `scripts/extract_review_counts.py`, `scripts/collect_quorum_evidence.py`), `examples/`, `demos/`, `templates/`, `tutorials/` | adopter-facing but not module-promotion paths; no importer-count-based tier pressure; the three excepted scripts are Boundary 3 (Action receipt/quorum plumbing) |
| harness plugins | `aragora/harnesses/` (Claude Code / Codex CLI integration), `aragora/extensions/` (gastown, moltbot), `aragora/plugins/` (manifest-based) | human/external-agent wiring; opt-in |

**Owed contract:**
- An `experimental` module MUST NOT be promoted to `integrated`/`core` by a worker's
  PR without an operator-approved amendment to `aragora/module_tiers.yaml`
  `MANUAL_TIER_OVERRIDES` map (the existing tripwire per `MODULE_TIER_DRIFT_GUARDIAN.md`
  §"What the check actually guards"; silent promotion is the exact hazard the tripwire
  prevents). The blank-tier-mutation pre-commit hook option in that doc is **deliberately
  REJECTED** — the tripwire value is the human-review pause, not auto-gen.
- Dependencies introduced by experimental/contrib: each must declare its floor (e.g.
  `cryptography>=48.0.1` security floor per `pyproject.toml [tool.uv] constraint-dependencies`)
  and document the risk; floor-pinned install pins and exact pins (e.g. `cryptography==48.x`)
  both have known failure modes — exact pins go stale on the next security bump.
- Archived content carries a clear "ARCHIVE — superseded by <link>" banner; adopters who
  land on an archived page via stale bookmarks or web search get the redirect/link to the
  live replacement within the first paragraph.
**NOT in this boundary:** anything that has been chartered to a specific authority module
in `docs/architecture/charters.yaml` (those are addressed by the operator-gated intent chart,
not by this proposal); any module that an outside adopter's CI relies on (those belong in
boundaries 1-5 by definition).

---

## 3. Boundary cross-talk: who can import whom (proposal rules, not enforcement)

Each boundary in §2 lists what it owes its adopters. The default coupling rule is **no
backwards imports** — a module in a *lower-numbered* boundary does not import from a
*higher-numbered* one unless the table marks a named, narrow adapter edge with **✓**. The
table below is read as **"row MAY import column"** (the row
boundary is the importer, the column boundary is the importee). A cell is marked **yes** for
always-allowed self/lower-boundary imports, **✓** for an important allowed cross-boundary
edge that the prose calls out, and **—** for edges that the no-backwards-import rule forbids.
This keeps the public utility surface (`1→6`, "core to archive") *importable without opt-in
extras* and prevents accidental coupling to experimental/deprecated paths.

| from ↓ / to → | 1 `core` | 2 `receipts+verifier` | 3 `action+CI-gate` | 4 `debate+quorum` | 5 `SDK+API` | 6 `experimental+contrib+archive` |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| 1 `core` | yes | — | — | — | — | — |
| 2 `receipts+verifier` | ✓ (receipts import core) | yes | — | — | — | — |
| 3 `action+CI-gate` | ✓ (Action uses core types) | ✓ (Action imports ODR machinery) | yes | ✓ (evidence collector invokes quorum adapter) | — | — |
| 4 `debate+quorum` | ✓ (debate uses core types) | ✓ (writes receipts after verdict) | — | yes | — | — |
| 5 `SDK+API` | ✓ (SDK/CLI uses core types) | ✓ (verifier callable from CLI) | — (invoke the Action externally; never import its scripts) | ✓ (CLI/API surface) | yes | — |
| 6 `experimental+contrib+archive` | limited (the legacy bridge) | limited (only for external `aragora-debate` HMAC) | — | limited (opt-in extensions may consume debate APIs) | limited (opt-in modules may consume public SDK/API) | yes (opt-in) |

**What this table does NOT do:**
- It does **not** add a CI script that rejects any of these import edges. The current
  importlint config does NOT enforce it.
- It does **not** add a `BLESSED_BOUNDARY = ...` constant. The boundary identity is
  *advisory classification* for legibility — a worker must read this doc to know which
  boundary they are extending, just as they read `module_tiers.yaml` to know the tier.
- It does **not** modify the `tools/`, `scripts/`, or `aragora/**` to flag boundary
  violations. That is a separate, future proposal (cf. the **REJECTED** option (A) in
  `MODULE_TIER_DRIFT_GUARDIAN.md` — blanket auto-mutation hooks are the documented wrong
  fix).

**Corrected classification note:** `aragora/debate/`, `aragora/ranking/elo.py`, and the
`aragora/reasoning/` primitives now sit exclusively in Boundary 4 (`debate+quorum`). Boundary 1
(`core`) keeps the type hierarchy, agent factory, persistent/knowledge substrate, config,
storage, and observation layers. Therefore Boundary 1 does not import from Boundary 4; Boundary 4
imports from Boundary 1 for type foundations, and Boundary 5 exposes the debate results to
adopters.

---

## 4. What this proposal EXPLICITLY does NOT do

Restating for the contract surface (so reviewers cannot misread "mod-quarantine" as
"mod-relocate"):

1. **No `git mv` under `aragora/**`.** No module is renamed, relocated, or topically
   re-grouped. `git diff --name-status origin/main...HEAD` over `aragora/**` reports
   **zero** `R` / `D` / `A` entries.
2. **No edits to `aragora/module_tiers.yaml`.** That file is auto-generated by
   `scripts/regenerate_module_tiers.py`; touching it by hand triggers the tier-drift
   tripwire; any tier change for a promotion/demotion this proposal might motivate is a
   *follow-on* PR with its own `MANUAL_TIER_OVERRIDES` amendment.
3. **No edits to `docs/architecture/INTENDED_ARCHITECTURE.md` or `charters.yaml`.**
   That file is operator-gated and its binding-precedence block (DRAFT) names the entries
   that are operative today; this proposal is additive context, not a charter edit.
4. **No edits to `action.yml` or `.github/workflows/**`.** Action/workflow is the
   Tier-3/4 operator-gated surface per `docs/AGENT_OPERATING_CONTRACT.md`; proposals here are
   ADVISORY context only.
5. **No new CI script.** Per the `MODULE_TIER_DRIFT_GUARDIAN.md` anti-pattern log, every
   "make the boundary enforced automatically" path was reviewed and intentionally not
   shipped (the blanket auto-regen hook is REJECTED for the same reason: silent mutation
   defeats the tripwire).
6. **No `pyproject.toml` floors bumped, no extras added/removed.** The four distribution
   floors (`aragora`, `aragora-debate`, `aragora-sdk`, `aragora-verify`) and the extras
   (`[test]`, `[gateway]`, `[blockchain]`, `[enterprise]`, `[connectors]`,
   `[experimental]`, `[dev]`, `[all]`) stay byte-identical.
7. **No relocate of root clutter.** Root clutter relocation is the
   `factory/pum-m7-root-clutter-relocation` companion PR, separately scoped. This proposal
   inherits that PR's disposition (FireShot PNGs + the `.docx` are gitignored
   *local-only*, never tracked, never moved) and adds **zero new** root-clutter claims.
8. **No edit to the operator-gated doctrine chain.** `docs/THESIS.md`,
   `docs/CANONICAL_GOALS.md`, the top-line claim sentence, `docs/RECEIPT_CONTRACT.md`,
   `docs/AGENT_OPERATING_CONTRACT.md` are untouched by this proposal.
9. **No `CLAUDE.md` churn.** `CLAUDE.md` holds the canonical front-door; touching its
   module index currently collides with #8795 and draft #8716 (path-freeze per
   `docs/AGENT_OPERATING_CONTRACT.md`), so any "adopt the boundary slots in the module index" change
   is a *follow-on*, separately routed.
10. **No `git mv` of `docs/archive/**` content.** ARCHIVE_REFERENCE_WHITELIST in
    `scripts/check_docs_consistency.py` is unchanged; this proposal does not introduce
    new redirects into `docs/archive/`.

If a reviewer wants any of #1-#10 to actually happen, the right format is a **separate
sequenced PR** (and for many of them, the right *content* is a separate proposal doc under
`docs/plans/` naming the boundary pressure being applied).

---

## 5. Decision points needing operator input

The proposal is named without shipping; several slots have material downstream consequences
that the operator should weigh in on before ANY boundary-relocation PR is opened:

| # | Slot | Question | Owner |
|---|---|---|---|
| Q1 | Post-`aragora-verify` schema pin | When `aragora-verify` requires a schema bump, do we keep two byte-identical `odr_schema.json` copies in lockstep (current `diff`-guarded state), or generate both package-local copies from one versioned source during release? Either option must preserve standalone offline verification; runtime loading from a shared checkout is not valid. | operator |
| Q2 | Action signing path | `signatures: []` is reserved for future Ed25519 wiring per #8225; what is the operator-approved signing key distribution mechanism once `aragora-verify --pubkey` is the no-trust default? (Current `--pubkey` path is manual and per-receipt; pubkey endpoints `/.well-known/aragora-odr-signing-key` / `/api/v2/receipts/signing-key` do NOT exist.) | operator + #8804 |
| Q3 | Tier pre-publish hook | `MODULE_TIER_DRIFT_GUARDIAN.md` lists five guardian options; option (B) — `stages: [pre-push]` tier-only mirror — is the only one reviewers have not rejected. Operator should signal whether to fund (B), or stay on CI-only with the documented cancellation noise. | operator |
| Q4 | historical 145→50 module reduction | Out-of-scope per `docs/superpowers/specs/2026-06-26-strategy-as-bounded-mission-cadence-design.md` §"Out of scope (YAGNI)"; confirm the deferral is the intended status while this proposal is the legibility-only deliverable. The current generated inventory is 144. | operator |
| Q5 | Boundary enforcement | The cross-talk rules (§3) are anti-pattern avoided by current importlint config. If operator wants ANY automatic enforcement, the right shape is a pre-push hook that REPORTS without mutating (mirrors the existing tier-drift pattern). Funding would need a separate feature. | operator |
| Q6 | SDK + API versioning cadence | The SDK and the API share `pyproject.toml` `[project].version`. After a feature that touches only the SDK (e.g. `sdk/python/`), should the API also bump by patch/minor? Currently the answer is no (semver only), but the boundary separation is implicit. | operator |
| Q7 | Archived content manifests | `docs/archive/`, `docs/status/`, `docs/deprecated/` have grown without a unified manifest. Worth funding an audit (preferably machine-checked) before `m6`/`m7` further archive churn? | operator |

Until those answers arrive, this proposal stays inert.

---

## 6. The `git diff --name-status origin/main...HEAD` contract

The proposal doc itself is the only file this PR creates. Validator can verify:

```text
# Expected diff status (origin/main...HEAD on factory/pum-m7-quarantine-proposal-fixes):
A  docs/architecture/MODULE_QUARANTINE_PROPOSAL.md

# NOT expected (any of):
#   M aragora/**        (no module moved/edited)
#   M scripts/**        (no new CI/importer check)
#   M pyproject.toml    (no floor bump, no new extra, no rename)
#   M action.yml        (no input/output added)
#   M CLAUDE.md         (no module-index churn on this PR's side)
#   M aragora/module_tiers.yaml    (regenerated by hand would trip the tripwire)
#   M docs/architecture/INTENDED_ARCHITECTURE.md     (operator-gated)
#   M docs/architecture/charters.yaml               (operator-gated)
```

A reviewer (or `git diff --name-status origin/main...HEAD`) reading the actual diff MUST see
exactly one `A` line on `docs/architecture/MODULE_QUARANTINE_PROPOSAL.md` plus zero lines
under `aragora/`, `scripts/`, `pyproject.toml`, or any other boundary path. The
`git diff --name-status origin/main...HEAD | awk '$1!="A"||$2!="docs/architecture/MODULE_QUARANTINE_PROPOSAL.md"{print}'`
filter is empty by construction.

For the cross-feature contract pair:
- **VAL-LEGIB-004** (user's main checkout untouched) — verified by
  `git -C "${ARAGORA_REPO_ROOT:-/path/to/aragora}" status --porcelain` (or `git status --porcelain`
  run from the user's main checkout on `main`) returning empty; this proposal does NOT add
  `untracked` files, `git mv`s, or rename staging to the user's working tree.
- **VAL-LEGIB-002** (tracked clutter git-renamed) — owned by the sibling
  `factory/pum-m7-root-clutter-relocation` PR (#9091) and explicitly NOT re-litigated
  here. This doc only *references* the companion PR outcome.
- **VAL-LEGIB-001** (root clutter inventoried) — also companion PR territory; this proposal
  inherits the inventory verbatim from there.

---

## 7. References (verified as live on `origin/main`)

- `docs/architecture/ARCHITECTURE.md` — descriptive layer model (hand-curated overview of the
  core debate subsystems; ~13 of ~169 packages; the canonical front-door says "see
  `CLAUDE.md` for the full module index").
- `docs/architecture/INTENDED_ARCHITECTURE.md` + `charters.yaml` — operator-gated intent
  charter. `Status: DRAFT v0.5`; while DRAFT, only the §0 binding-status entries are
  operative (`CHR-P4A-001..004`, `CHR-X-007`). This proposal sits **adjacent to** the
  charter (legibility layer), not **inside** it (placement layer).
- `docs/governance/MODULE_TIER_DRIFT_GUARDIAN.md` — the current drift-tripwire design,
  including the deliberately-rejected blanket auto-regen path. The only-allowed fallback
  mentioned (option B) is tier-only + pre-push + report-only.
- `aragora/module_tiers.yaml` — auto-generated. Counts (2026-07-09):
  21 core / 91 integrated / 29 experimental / 3 deprecated / 144 total. The boundary
  classification proposed here is *layered on top of* these tiers; it does not contradict
  them.
- `docs/specs/OPEN_DECISION_RECEIPT.md` + `docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md` — the
  ODR v0.1 public profile and the canonical-internal vs public-canonical reconciliation.
  The reconciliation also records that `odr_verify.py` is not yet wired to a shipped
  CLI/HTTP entry point and disambiguates the two verifier paths.
  `docs/specs/**` is mirrored by `docs-site/scripts/sync-docs.js` (PR #8953) with deliberate
  exclusions (e.g. `docs/RECEIPT_CONTRACT.md`, allowlisted operator-only packets).
- `docs/reference/ROOT_ALLOWLIST.md` + `scripts/ci/check_root_allowlist.py` — the
  repo-root hygiene guard (#8258). Companion PR #9091 (`factory/pum-m7-root-clutter-relocation`)
  expands the allowlist disposition with a tracked-vs-gitignored inventory.
- `docs/AGENT_OPERATING_CONTRACT.md` — merge-policy tiers, path-freeze, and the `scripts/**`
  touch precedent that this proposal deliberately avoids.
- `docs/status/PUBLIC_UTILITY_MISSION_BASELINE.md` — milestone M7 baseline and the bounded-PR
  sequence this proposal belongs to.
---

## 8. Changelog (this doc)

- **2026-07-10** — Initial PROPOSE-ONLY draft authored by docs-worker (M7
  legibility). No `aragora/**`, `scripts/**`, or operator-gated doc touched. Diff
  contract: single `A` on this file only.
- **2026-07-10 (round 4)** — Resolved the original parent/child ownership conflict
  by assigning `aragora/receipts/__init__.py` to Boundary 2 and the remaining
  receipt helpers to Boundary 6. Round 5 supersedes that split so ownership is
  package-granular.
- **2026-07-13 (round 5)** — Kept boundary ownership package-granular by assigning all
  of `aragora/receipts/` to Boundary 2, while noting that its runtime helpers are not
  standalone-verifier dependencies. Corrected the import matrix so SDK/API code invokes
  Action tooling externally rather than importing unpackaged scripts, and so opt-in
  modules may consume the stable debate and SDK/API surfaces. Removed a duplicate
  architecture reference.
- **2026-07-13 (round 6)** — Removed the remaining file-level ownership splits under
  `aragora/agents/` and `aragora/memory/`. Documented the Action evidence collector's
  narrow adapter edge into quorum machinery and corrected the copy-paste checkout command.
- **2026-07-13 (round 7)** — Removed a schema-source option that would have violated the
  standalone verifier's offline contract; both alternatives now ship package-local schemas.
