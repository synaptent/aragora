# Canonical Model Catalog

**Status:** Phase 1 (enforcement without rewiring) — adjudicated on the
#9073/#9075 review record, 2026-07-16.

## Why

The #9073 and #9075 reviews empirically demonstrated that model identity and
pricing were duplicated across **eleven runtime tables** (model pins, model
selector, routing provider config, billing usage, services metering, debate
costs, pdb invoker, two agent fallback maps, server cost estimation, billing
optimizer tiers). Adversarial review discovered the drift one table per round
— including **three live provider reprices caught mid-review** (gpt-5.5
$2.50/$10 → $5/$30; qwen3.7-max $1.25/$3.75 → $1.475/$4.425; kimi-k2.7-code
$0.72 → $0.75). Review rounds are the most expensive drift detector the
project owns; this catalog makes the detection mechanical.

## The design (three rules)

1. **One typed source.** `aragora/models/catalog.py` defines `ModelSpec`
   (canonical/direct/OpenRouter ids, aliases, USD-per-MTok pricing, context
   and output limits, release + soak dates). `by_any_id()` resolves every
   accepted spelling.
2. **Offline validation, advisory liveness.** Required CI never calls the
   network: it validates against the committed
   `aragora/models/catalog_snapshot.json`. `scripts/model_catalog_drift.py`
   is the advisory live-vs-snapshot differ (`--refresh` rewrites the
   snapshot for a reviewed commit). A scheduled advisory workflow may invoke
   it, but it must never gate a PR on live-catalog reachability.
3. **Governance stays out.** Quorum-family *eligibility* — which model may
   produce merge-authority evidence — lives in
   `aragora/swarm/quorum_evidence.py` under Tier-4 control, never in the
   catalog. The catalog knows prices and soak dates; it does not decide
   authority. (`soak_until` records the 14-day availability rule so
   reviewers/tools can check it; enforcement of the rule remains policy.)

## Phase 1: enforcement without rewiring

No runtime table changed behavior. `tests/models/test_catalog.py` asserts
that existing table rows for an **enforced** model match the catalog
(`ENFORCED_MODELS`, currently the fourteen models verified live).
A covered drifting mirror now fails tests in seconds instead of consuming
an adversarial review round.

The 2026-08-16 runtime refresh added the live OpenRouter defaults
`perplexity/sonar-reasoning-pro`, `cohere/command-a`, and
`ai21/jamba-large-1.7`; Grok's OpenRouter runtime routing now uses
`x-ai/grok-4.5` while Grok 4.6 completes its repository soak. The same live
capture recorded the Kimi K2.7 Code price change to $0.71/$3.50 per MTok
without changing its reviewer pin. The runtime-only Kimi refresh adds
`moonshotai/kimi-k3` at $3/$15 per MTok with a 1,048,576-token context after
its 14-day availability soak; `kimi-thinking` retains its distinct K2
reasoning model. The Qwen runtime refresh adds `qwen/qwen3.8-max` at $2/$6
per MTok with a 1,000,000-token context and 131,072-token output limit after
its 14-day availability soak; Qwen 3.7 and older IDs remain accepted and
priced for compatibility.

The current Anthropic frontier pin is **`claude-opus-5`** (`anthropic/claude-opus-5`
via OpenRouter), adopted 2026-07-24 at the same $5/$25 per MTok as its
predecessor. **`claude-opus-4-8` stays in the catalog and stays enforced**: it is
still Active upstream and remains Opus 5's documented fallback target, so its
spec, pricing rows, and `aragora/config/model_pins.py` constants must keep
naming the real 4.8 rather than aliasing forward to Opus 5.

Phase-1 coverage is deliberately uneven across the eleven mirrors — stated
plainly so the tests are not oversold:

* **Presence + value enforced** (a missing row for an enforced model FAILS):
  pdb `_PRICE_PER_MTOK`, billing `usage.PROVIDER_PRICING`, and services
  `metering_models.MODEL_PRICING` (the metering fallback would otherwise
  silently mis-bill live usage).
* **Value enforced only when a row exists** (deleting a row passes
  silently — the static skip-count gate does not catch runtime skips):
  billing `debate_costs.DEFAULT_PROVIDER_RATES` and routing
  `provider_config.PROVIDER_PRICING`.
* **Value enforced with named anchors**: `model_selector.MODEL_PROFILES` —
  any profile resolving to an enforced spec must match, and the gpt-5.5 and
  claude-opus-4-8 profiles are asserted present so the check cannot pass
  vacuously.
* **Slug-resolution enforced**: `OPENROUTER_FALLBACK_MODELS` targets must
  resolve to a catalog spec (dead slugs fail; explicit allowlist for the
  not-yet-cataloged deepseek-v4-pro), and targets resolving to an enforced
  spec must use its exact `openrouter_id`.
* **Not yet covered**: model pins, server cost estimation, billing
  optimizer tiers, and per-agent `OPENROUTER_MODEL_MAP` overrides. Drift
  there is still review-discovered until phase 2 (or until these tables
  gain phase-1 tests).

Known-stale legacy rows (e.g. deepseek-v4-pro at $1.74/$3.48 vs live
$0.435/$0.87; qwen3-max at $0.60/$1.80 vs live $0.78/$3.90) are deliberately
NOT enforced yet: each needs adjudication (some rows may intentionally model
non-OpenRouter direct pricing) before entering `ENFORCED_MODELS`. Add a
model to enforcement by cataloging it and fixing every mirror in the same
commit — the tests tell you exactly which rows disagree.

## Phase 2 (planned, separate PRs)

Consumers migrate to projections generated from the catalog: billing tables
become derived structures, agent fallback maps derive their targets from
`openrouter_id`, and the cost-estimation/optimizer maps import instead of
duplicating. Each migration is a bounded PR gated by the phase-1 tests.

## How to add or reprice a model

1. Edit `aragora/models/catalog.py` (one `ModelSpec`).
2. Run `python3 scripts/model_catalog_drift.py --refresh` and commit the
   snapshot diff (live verification receipt).
3. Run `python3 -m pytest tests/models/` — it lists every mirror row that
   must change; change them in the same commit.
4. New model on a merge-authority surface? Check `soak_until` and the
   governance pins first.
