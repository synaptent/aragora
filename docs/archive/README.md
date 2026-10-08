# Archived Docs

This directory holds dated snapshots of documents that were retired or superseded but whose content is still valuable as a historical reference.

**Naming convention:** `YYYY-MM[-DD]-<ORIGINAL_FILENAME>.md` — the date reflects the last meaningful update of the archived doc, not the date it was archived.

**Recorded exception:** non-Markdown binary assets retain their original
basenames. The date-prefix convention applies to document snapshots;
`aragora_logo.png` and `favicon.png` remain byte-for-byte under their source
names so the root-relocation provenance stays explicit.

## What lives here and why

| Archived file | Superseded by | Why archived |
|---|---|---|
| `2026-02-25-OMNIVOROUS_ROADMAP.md` | [../CANONICAL_GOALS.md](../CANONICAL_GOALS.md) (vision), [../FEATURE_DISCOVERY.md](../FEATURE_DISCOVERY.md) (current capabilities), [../plans/ARAGORA_EVOLUTION_ROADMAP.md](../plans/ARAGORA_EVOLUTION_ROADMAP.md) (sequencing) | Competed with CANONICAL_GOALS on vision framing; included Phase-completion claims that did not match FEATURE_GAP_LIST reality. Useful as a February 2026 snapshot of the multi-channel integration roadmap and connector/environment details. |
| `2026-01-OMNIVOROUS_ROADMAP_v2.5.md` | Same as the 2026-02-25 entry | A still-older copy that lived under `docs/status/` and was already flagged as superseded. Kept for version-history provenance; defer to the 2026-02-25 snapshot or current canonical homes. |
| `2026-02-ARAGORA_BUSINESS_SUMMARY_v2.8.0.md` | [../COMMERCIAL_OVERVIEW.md](../COMMERCIAL_OVERVIEW.md) (current commercial positioning), [../CANONICAL_GOALS.md](../CANONICAL_GOALS.md) (vision), [../WHY_ARAGORA.md](../WHY_ARAGORA.md) (category claim) | Competed with COMMERCIAL_OVERVIEW on "here's Aragora for business" framing; contained dated metric snapshots (45 adapters vs canonical 42; 208K tests vs canonical 210K+) and completion claims ahead of measured proof. Useful as a February 2026 snapshot of revenue projections, pricing tiers, and competitive comparison. |
| `2026-01-27-GETTING_STARTED.md` | [../quickstart.md](../quickstart.md) (onboarding), [../reference/CLI_REFERENCE.md](../reference/CLI_REFERENCE.md) (CLI), [../api/API_REFERENCE.md](../api/API_REFERENCE.md) (API), [../debate/GAUNTLET.md](../debate/GAUNTLET.md) (Gauntlet), [../guides/TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md) (troubleshooting) | Competed with `docs/quickstart.md` as a second "canonical" onboarding guide — the two documentation landings (`docs/INDEX.md` and `docs/README.md`) routed to different ones (M6 docs canonicalization). Its CLI/API/Gauntlet/troubleshooting sections duplicated already-canonical, better-maintained docs. `docs/guides/GETTING_STARTED.md` is now a short redirect stub, mirroring the existing `docs/guides/QUICKSTART.md` pattern. |
| `2026-02-25-COMMERCIAL_POSITIONING.md` | [../COMMERCIAL_OVERVIEW.md](../COMMERCIAL_OVERVIEW.md) (current commercial positioning) | Dated February 2026 snapshot (pricing tiers, competitive comparison) pinned to distribution v2.8.0; superseded by the canonical commercial-positioning doc. `docs/status/COMMERCIAL_POSITIONING.md` remains a redirect stub so old links continue to resolve before pointing readers here for the frozen snapshot. |
| `2026-06-10-EU_AI_ACT_WALKTHROUGH.md` | [../compliance/EU_AI_ACT_GUIDE.md](../compliance/EU_AI_ACT_GUIDE.md) (article mappings and artifact schemas) | Self-declared "dated proof artifact" — a real CLI run transcript captured 2026-06-10 against `aragora 2.8.0`. Freezing the transcript preserves an accurate historical record instead of rewriting a completed run to claim a version it was never executed against. `docs/compliance/EU_AI_ACT_WALKTHROUGH_2026-06.md` remains a redirect stub for existing links. |
| `2026-02-03-ARCHITECTURE_REVIEW_RESPONSE.md` | [../architecture/ARCHITECTURE_REVIEW_RESPONSE.md](../architecture/ARCHITECTURE_REVIEW_RESPONSE.md) (identical content, canonical location) | Exact duplicate of the doc already living under `docs/architecture/`; the canonical content remains under `docs/architecture/`. The former top-level redirect stub was removed once it had no inbound links. |
| `2026-03-18-Idea-to-Execution-Pipeline-Research.md` | Historical research snapshot | Relocated from the repository root after confirming zero inbound references and no Markdown links whose relative targets could change. The prefix records its last pre-archive content commit. |
| `2026-02-11-NEXT_STEPS.md` | [../status/NEXT_STEPS_CANONICAL.md](../status/NEXT_STEPS_CANONICAL.md) | Redundant legacy root pointer; the canonical next-steps document and existing compatibility pointers under `docs/` remain live. The prefix records its last pre-archive content commit. |
| `2026-01-25-DEPLOYMENT.md` | [../DEPLOYMENT.md](../DEPLOYMENT.md) (deployment guide), [../deployment/KUBERNETES.md](../deployment/KUBERNETES.md), [../deployment/TLS.md](../deployment/TLS.md), [../reference/ENVIRONMENT.md](../reference/ENVIRONMENT.md) | Formerly `docs/deployment/DEPLOYMENT.md`, a second "Deployment Guide" self-dated v2.3.0 / January 25, 2026. It competed with the release-maintained `docs/DEPLOYMENT.md` (version-pinned by `scripts/check_version_alignment.py`); its later Docker-path pointers already live in the canonical guide. Two same-directory links were re-pointed at `../deployment/` so the snapshot still resolves. |
| `2026-06-04-SECURITY_AUDIT_INPUT_VALIDATION.md` | Historical security-audit snapshot | Relocated from the repository root after confirming zero inbound references and no Markdown links whose relative targets could change. The prefix records its last pre-archive content commit. |
| `2026-02-13-PYTHON_SDK_CONSOLIDATION.md` | [../SDK_GUIDE.md](../SDK_GUIDE.md), [../guides/PYTHON_SDK_CONSOLIDATION.md](../guides/PYTHON_SDK_CONSOLIDATION.md) (current SDK guidance) | Formerly `docs/PYTHON_SDK_CONSOLIDATION.md`, a self-declared historical roadmap for merging `aragora-client` into `aragora-sdk`; the legacy client was removed in February 2026. Three relative links were re-based so the snapshot still resolves. The prefix records its last pre-archive content commit. |
| `2026-03-06-STRANDED_FEATURES_AUDIT.md` | [../status/FEATURE_DISCOVERY.md](../status/FEATURE_DISCOVERY.md), [../FEATURE_GAP_LIST.md](../FEATURE_GAP_LIST.md) | Formerly `docs/STRANDED_FEATURES_AUDIT.md`, a point-in-time (2026-02-24) audit of built-but-unwired features with feature-local test counts. Moved from the `docs/` root with no live inbound Markdown links; the backticked path mentions in frozen `docs/plans/` documents are historical and were not rewritten. The prefix records its last pre-archive content commit. |
| `2026-07-15-STRATEGIC_ANALYSIS.md` | [../COMMERCIAL_OVERVIEW.md](../COMMERCIAL_OVERVIEW.md), [../WHY_ARAGORA.md](../WHY_ARAGORA.md), [../strategy/STRATEGY_INDEX.md](../strategy/STRATEGY_INDEX.md) | Formerly `docs/STRATEGIC_ANALYSIS.md`, a February 2026 product-market-fit snapshot whose counts were preserved as a historical audit narrative. Moved from the `docs/` root with no live inbound Markdown links. The prefix records its last pre-archive content commit. |
| `aragora_logo.png` | Docusaurus-owned SVG logo asset | Unreferenced legacy root PNG; tracked-file scans found no product or documentation consumer. It retains its basename under the recorded non-Markdown exception above. |
| `favicon.png` | Docusaurus-owned favicon asset | Unreferenced legacy root PNG; tracked-file scans found no product or documentation consumer. It retains its basename under the recorded non-Markdown exception above. |

## Dated documents archived under their original sub-directory

Documents whose file name already carries a `YYYY-MM-DD` date are archived under
`docs/archive/<original-subdirectory>/` with their basename unchanged, so the former path
`docs/<subdir>/<name>` maps to `docs/archive/<subdir>/<name>` without a rename. Live docs that
mentioned them now name the file without linking it (policy below); backticked mentions in frozen
`docs/plans/` documents, generated records under `docs/status/generated/` and research receipts
under `docs/research/receipts/` are historical and were not rewritten.

| Archived file | Why archived |
|---|---|
| [`architecture/ground-up-assessment-2026-01-29.md`](architecture/ground-up-assessment-2026-01-29.md) | Self-declared January 2026 snapshot; CHR-X-025 in [../architecture/charters.yaml](../architecture/charters.yaml) lists it among superseded architecture docs to stamp or archive (current model: [../architecture/INTENDED_ARCHITECTURE.md](../architecture/INTENDED_ARCHITECTURE.md)). The charter entry now names the archived path. |
| [`benchmarks/corpus_honesty_audit_2026-04-17.md`](benchmarks/corpus_honesty_audit_2026-04-17.md) | 2026-04-17 audit of corpus rev-2; its outcome lives in `docs/benchmarks/corpus.json`; the corpus rev-3 changelog entry and the code comments that cite the audit now name the archived path. |
| [`briefs/round-2026-04-30e-heterogeneous-dialog.md`](briefs/round-2026-04-30e-heterogeneous-dialog.md) | Completed round brief (2026-04-30); no inbound references. |
| [`methodology/H2_PARTIAL_MULTI_SEEDED_2026-05-04.md`](methodology/H2_PARTIAL_MULTI_SEEDED_2026-05-04.md) | Round 31b H2 judge-contract note (2026-05-04); no inbound references. |
| [`methodology/H2_TRANSCRIPT_PROVENANCE_2026-05-05.md`](methodology/H2_TRANSCRIPT_PROVENANCE_2026-05-05.md) | Round 31b H2 transcript-provenance note (2026-05-05); no inbound references. |
| [`research/2026-08-26-x-bookmarks-triage.md`](research/2026-08-26-x-bookmarks-triage.md) | Non-canonical 2026-08-26 research triage; register rows in [../status/ROADMAP_INTAKE_REGISTER.md](../status/ROADMAP_INTAKE_REGISTER.md) carry its outcomes. Its relative links were re-based so the snapshot still resolves. |
| [`research/2026-08-26-anthropic-multiagent-patterns-brief.md`](research/2026-08-26-anthropic-multiagent-patterns-brief.md) | Non-canonical deep-dive brief from the same triage. |
| [`research/2026-08-26-simile-confidence-model-brief.md`](research/2026-08-26-simile-confidence-model-brief.md) | Non-canonical deep-dive brief from the same triage. |
| [`research/2026-08-26-yc-qm-brief.md`](research/2026-08-26-yc-qm-brief.md) | Non-canonical deep-dive brief from the same triage; the summary row lives in [../strategy/COMPARISON_MATRIX.md](../strategy/COMPARISON_MATRIX.md). |
| [`reviews/swarm_prs_2026-04-17.md`](reviews/swarm_prs_2026-04-17.md) | 2026-04-17 cross-family review of five swarm PRs; cited only from a frozen `docs/plans/` design. |
| [`runbooks/2026-07-08-outbox-triage-ledger.md`](runbooks/2026-07-08-outbox-triage-ledger.md) | Read-only outbox classification snapshot (2026-07-08); no inbound references. |
| [`specs/2026-07-01-adjudicator-wiring-tier4-packet.md`](specs/2026-07-01-adjudicator-wiring-tier4-packet.md) | Self-declared archival, prepare-only Tier-4 packet; it was never published to the docs site. |
| [`status/B0_ZERO_HEADLINE_DIAGNOSTIC_2026-05-19.md`](status/B0_ZERO_HEADLINE_DIAGNOSTIC_2026-05-19.md) | 2026-05-19 diagnostic; its Move 4 explainer stays live at [../benchmarks/B0_PROXY_METRIC_INTERPRETATION.md](../benchmarks/B0_PROXY_METRIC_INTERPRETATION.md). |
| [`status/EXECUTION_GATE_STAGED_ROLLOUT_2026-03-05.md`](status/EXECUTION_GATE_STAGED_ROLLOUT_2026-03-05.md) | 2026-03-05 rollout plan; no inbound references. |
| [`status/EXECUTION_GATE_TUNING_2026-03-05.md`](status/EXECUTION_GATE_TUNING_2026-03-05.md) | Generated 2026-03-05 tuning report; the workflow lives in [../debate/EXECUTION_SAFETY_GATE.md](../debate/EXECUTION_SAFETY_GATE.md). |
| [`status/EXTERNAL_PROOF_2026-06-18.md`](status/EXTERNAL_PROOF_2026-06-18.md) | 2026-06-18 external proof run record; no inbound references. |
| [`status/PROJECT_ASSESSMENT_2026-05-19_30D.md`](status/PROJECT_ASSESSMENT_2026-05-19_30D.md) | 30-day assessment for 2026-04-19 to 2026-05-19. |
| [`status/PROOF_LOOP_FIRST_CLOSURE_2026-05-12.md`](status/PROOF_LOOP_FIRST_CLOSURE_2026-05-12.md) | 2026-05-12 proof-loop closure receipt; the timeline entry in [../status/STATUS.md](../status/STATUS.md) still describes it. |
| [`status/SDK_CROSS_PARITY_DEBT_PLAN_2026-02-25.md`](status/SDK_CROSS_PARITY_DEBT_PLAN_2026-02-25.md) | 2026-02-25 plan snapshot; the live baseline is `scripts/baselines/cross_sdk_parity.json`, referenced from [../status/PARITY_BACKLOG.md](../status/PARITY_BACKLOG.md). |

## Policy

- **Do not link to archived docs as current-state references.** They are snapshots, not live source of truth.
- **Do not update archived docs.** If something is wrong, fix it in the superseding canonical doc and leave the archive as-is.
- Content relocations and deprecations are tracked in [../strategy/STRATEGY_INDEX.md](../strategy/STRATEGY_INDEX.md) where applicable.
