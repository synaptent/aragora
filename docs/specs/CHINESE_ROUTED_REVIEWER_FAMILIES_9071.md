# Chinese-Routed Reviewer Families for #9071

**Status:** implementation preapproved; merge settlement pending
**Date:** 2026-07-09
**Authority:** issue #9069 founder approval, work order #9071
**Tier:** 4 (model-family recognition changes merge-authority behavior)

## Decision

Activate GLM and MiniMax as OpenRouter-direct reviewer families and add Tencent
Hy3 and ByteDance Seed as new canonical reviewer families. All four are
Chinese-routed. They can contribute advisory diversity at every Tier, count at
Tier 0-1, and count at Tier 2 only alongside at least one Western family. They
remain advisory-only and are excluded from counted quorum at Tier 3-4.

| Canonical family | OpenRouter model | Provider lineage | Tier 3-4 |
| --- | --- | --- | --- |
| `glm` | `z-ai/glm-5.2` | Z.ai / Zhipu | Advisory-only |
| `minimax` | `minimax/minimax-m3` | MiniMax | Advisory-only |
| `tencent` | `tencent/hy3` | Tencent Hunyuan | Advisory-only |
| `bytedance` | `bytedance-seed/seed-2.0-lite` | ByteDance Seed | Advisory-only |

The slugs and non-zero prompt/completion prices were verified against the live
OpenRouter model catalog on 2026-07-09. Dispatch remains opt-in through
`ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK=1` plus `OPENROUTER_API_KEY`.

## Jurisdiction Boundary

These families may receive public OSS PR titles and diffs. They must never
receive raw email bodies, customer PII, credentials, private legal material, or
regulated data. This change does not alter payload routing policy; it only adds
reviewer identities and opt-in OpenRouter dispatch for public repository diffs.

## Gate Invariants

- `WESTERN_FAMILIES`, `WESTERN_FRONTIER_FAMILIES`, and `tier_quorum_rule` remain
  unchanged.
- Tencent and ByteDance aliases normalize to one canonical family each, so a
  provider cannot inflate distinct-family counts through naming variants.
- Tier 3-4 settlement still requires two counted Western families.
- Tier 2 still requires at least one Western family.
- Named runtime agent types and allowlist counts are not added; generic
  OpenRouter reviewer dispatch is sufficient for this work order.

## Verification

Focused tests cover OpenRouter dispatch, alias and reviewer-id normalization,
non-zero pricing, and Tier 2-4 jurisdiction behavior. LongCat 2.0, Seed 2.1 /
Doubao 2.1 Pro, and Hunyuan models beyond Hy3 remain watch items because the
approved OpenRouter catalog snapshot did not expose the requested production
slugs.

This document records implementation scope only. The draft PR must remain
unsettled until exact-head Tier-4 human settlement is recorded.
