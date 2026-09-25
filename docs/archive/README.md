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
| `2026-02-03-ARCHITECTURE_REVIEW_RESPONSE.md` | [../architecture/ARCHITECTURE_REVIEW_RESPONSE.md](../architecture/ARCHITECTURE_REVIEW_RESPONSE.md) (identical content, canonical location) | Exact duplicate of the doc already living under `docs/architecture/`; the top-level copy is now a redirect stub so existing links continue to resolve while the canonical content remains under `docs/architecture/`. |
| `2026-03-18-Idea-to-Execution-Pipeline-Research.md` | Historical research snapshot | Relocated from the repository root after confirming zero inbound references and no Markdown links whose relative targets could change. The prefix records its last pre-archive content commit. |
| `2026-02-11-NEXT_STEPS.md` | [../status/NEXT_STEPS_CANONICAL.md](../status/NEXT_STEPS_CANONICAL.md) | Redundant legacy root pointer; the canonical next-steps document and existing compatibility pointers under `docs/` remain live. The prefix records its last pre-archive content commit. |
| `2026-06-04-SECURITY_AUDIT_INPUT_VALIDATION.md` | Historical security-audit snapshot | Relocated from the repository root after confirming zero inbound references and no Markdown links whose relative targets could change. The prefix records its last pre-archive content commit. |
| `aragora_logo.png` | Docusaurus-owned SVG logo asset | Unreferenced legacy root PNG; tracked-file scans found no product or documentation consumer. It retains its basename under the recorded non-Markdown exception above. |
| `favicon.png` | Docusaurus-owned favicon asset | Unreferenced legacy root PNG; tracked-file scans found no product or documentation consumer. It retains its basename under the recorded non-Markdown exception above. |

## Policy

- **Do not link to archived docs as current-state references.** They are snapshots, not live source of truth.
- **Do not update archived docs.** If something is wrong, fix it in the superseding canonical doc and leave the archive as-is.
- Content relocations and deprecations are tracked in [../STRATEGY_INDEX.md](../STRATEGY_INDEX.md) where applicable.
