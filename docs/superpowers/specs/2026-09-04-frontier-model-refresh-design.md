# Frontier Model Refresh — Design

**Date:** 2026-09-04
**Status:** Approved by founder (chat, 2026-09-04) — implementation plan: `docs/superpowers/plans/2026-09-04-frontier-model-refresh.md`
**Supersedes the July frontier plan in #9069 phases P0–P3; P4 (Muse Spark) folded in as an OpenRouter family row.**

## Goal

Move every per-provider default in the repository to the current frontier model, make the model catalog the
single load-bearing source of truth so the next refresh is a one-file change plus a generated sweep, and harden
the two API agents for the request-shape rules of the new model generations.

## Founder decisions this design implements

1. **Claude Fable 5.1 everywhere Claude is used.** Every Claude role, agent default, CLI default, reviewer duty.
   Opus 5 remains the fallback model; Opus 4.8 remains the refusal fallback (`model_pins.py` note).
2. **GPT-6 Astra everywhere now, including merge-gate reviewer duty.** This is a one-time override of the
   14-day reviewer-availability rule in #9069 (Astra released 2026-09-03). Recorded in the PR body and on #9069.
3. **Aggressive sweep.** Every old model literal under `aragora/`, `scripts/`, `sdk/`, `docs/`, `docs-site/`, and
   `tests/` is rewritten through a single upgrade map. Generated, not hand-edited.
4. **Gemini 3.1 Pro stays the Google researcher default; Gemini 3.8 Flash is added as the cheap tier.**

## Findings the design rests on (measured 2026-09-04, origin/main `a584c786`)

- `aragora/models/catalog.py` (14 `ModelSpec`, `ENFORCED_MODELS`) and `aragora/config/model_pins.py`
  (role pins) are declared canonical but are not load-bearing: 14 files import the pins, 12 import the catalog,
  **251 files under `aragora/` carry raw model-ID literals**; 2,448 literal hits in `aragora/`, 1,594 files repo-wide
  (715 under `tests/`).
- Six independent pricing tables (`billing/usage.py`, `pdb/real_invoker.py`, `services/metering_models.py`,
  `billing/debate_costs.py`, `routing/provider_config.py`, `server/handlers/debates/cost_estimation.py`) plus the
  resolver `routing/pricing.py`. Tests check catalog→tables only; nothing checks that every reachable default has a
  catalog row, so Gemini, Mistral, DeepSeek, Llama, GLM, MiniMax are priced by the legacy table or the conservative
  default and drift silently (catalog docstring admits it).
- Three separate legacy-ID maps: `api_agents/anthropic.py:98-110 OPENROUTER_MODEL_MAP`,
  `api_agents/gemini.py:56-81 GEMINI_MODEL_ALIASES`, `cli_agents.py:234-281 OPENROUTER_MODEL_MAP`.
- Anthropic agent request shape is guarded by a **name regex** (`models/compat.py:33-41 _MODERN_CLAUDE`); a new
  family name would not match and sampling params would be sent (400 on Fable/Opus 5).
- OpenAI agent (`api_agents/openai_compatible.py:172-190`) always sends `max_tokens`, sends `temperature`/`top_p`/
  `frequency_penalty` unconditionally, has no `reasoning_effort`, and no sampling-strip equivalent.
- `docs/status/claims/canonical_metrics.yaml:120-135` (claim `security.model_pins.frontier_aligned`) asserts the
  constants `OPUS_4_7`, `GPT_5_4`, `GEMINI_3_1_PRO` still exist in `model_pins.py`. They must stay as aliases.
- `GEMINI_31_PRO_DIRECT = "gemini-3.1-pro"` is not a Gemini API code; the API string is `gemini-3.1-pro-preview`
  (Google model list, 2026-09-04). Fix in passing.
- Open PRs touching the same files: #9848 (`model_pins.py`), #9832/#9147/#9081 (`quorum_evidence.py`).

## Target model table (single source: `aragora/models/catalog.py`)

| Family | Direct ID | OpenRouter slug | $/1M in / out | Context | Released | Role |
|---|---|---|---|---|---|---|
| anthropic | `claude-fable-5-1` | `anthropic/claude-fable-5.1` | 10 / 50 (cache read 0.25) | 1M | pre-Jun-24 | all Claude roles |
| anthropic (fallback) | `claude-opus-5` | `anthropic/claude-opus-5` | 5 / 25 | 1M | Jul 24 | fallback |
| anthropic (refusal fallback) | `claude-opus-4-8` | `anthropic/claude-opus-4.8` | 5 / 25 | 1M | — | refusal fallback |
| openai | `gpt-6-astra` | `openai/gpt-6-astra` | 10 / 50 (cached 1) | 1.05M / 128K out | Sep 3 | agent default, reviewer, Codex harness |
| openai (value) | `gpt-5.6-terra` | `openai/gpt-5.6-terra` | 2 / 12 | 1.05M | Jul 9 | cheap/bulk routes |
| google | `gemini-3.1-pro-preview` | `google/gemini-3.1-pro-preview` | 2 / 12 | 1M | Feb 19 | researcher |
| google (cheap) | `gemini-3.8-flash` | `google/gemini-3.8-flash` | 0.75 / 3.75 (1.50/7.50 from 2027-01-01) | 1M | Sep 2 | cheap tier |
| xai | `grok-4.6` | `x-ai/grok-4.6` | 2 / 6 (2x ≥200K) | 500K | Aug 12 | devil's advocate |
| mistral | `mistral-medium-2604` | `mistralai/mistral-medium-3-5` | 1.5 / 7.5 | 262K | Apr 30 | fallback family flagship |
| mistral (open) | `mistral-large-2512` | `mistralai/mistral-large-2512` | 0.5 / 1.5 | 262K | Dec 1 | kept |
| deepseek | — | `deepseek/deepseek-v4-pro-0813` | 1.12 / 3.36 | 1M | Aug 12 | reviewer diversity |
| qwen | `qwen3.8-max` (Alibaba) | `qwen/qwen3.8-2.4t-a95b` | 2 / 6 | 1M | Aug 12 | reviewer diversity |
| moonshot | — | `moonshotai/kimi-k3` | 3 / 15 | 1M | Jul 16 | reviewer diversity |
| moonshot (code) | — | `moonshotai/kimi-k2.7-code` | 0.66 / 3.40 | 262K | Jun 12 | coding routes |
| meta | — | `meta/muse-spark-1.3` | 1.25 / 4.25 | 1M | Sep 2 | new-family diversity |
| zai | — | `z-ai/glm-5.2` | (catalog verifies) | 1M | — | diversity |
| minimax | — | `minimax/minimax-m3` | 0.30 / 1.20 | 1M | May 31 | diversity |

Prices from OpenAI/Anthropic/xAI/Google/Mistral docs and the live OpenRouter catalog on 2026-09-04. The catalog
row is the only place a price lives; every table below mirrors it.

## Architecture

### 1. Catalog becomes load-bearing
- `ModelSpec` gains capability flags: `supports_sampling_params: bool`, `thinking_default_on: bool`,
  `forced_tool_choice_allowed: bool`, `max_tokens_param: Literal["max_tokens","max_completion_tokens"]`,
  `reasoning_effort_default: str | None`, `cache_read_price`, `family`, `released_on`, `retired: bool`.
- `model_pins.py` constants are derived from the catalog (`FABLE_51_DIRECT = catalog["claude-fable-5-1"].direct_id`
  style), keeping the legacy constant names as aliases so `canonical_metrics.yaml` keeps passing.
- Every definer reads the catalog/pins instead of a literal: the six `api_agents/*` defaults, `cli_agents.py`
  per-CLI defaults and default panel, `model_selector.py` `MODEL_PROFILES`, `swarm/quorum_evidence.py`
  `_OPENROUTER_REVIEWER_MODELS` and `_CODEX_DEFAULT_MODELS`, `scripts/consult_claude.py`, `scripts/fable_goal_cycle.py`,
  `server/handlers/debates/cost_estimation.py` `DEFAULT_MODELS`, `cli/audit.py`, `cli/document_audit.py`,
  `cli/documents.py` `--model` defaults, and the six pricing tables (generated from the catalog at import time).
- New reverse test: every model reachable from any default, profile, reviewer map, or alias resolves to a catalog
  row with non-zero input and output prices.

### 2. One upgrade map, two consumers
- `aragora/models/upgrade_map.py`: `UPGRADES: dict[str, str]` old→current for every retired or superseded ID
  observed in the repo (gpt-4*, gpt-4o*, gpt-5.3/5.4/5.5, gpt-5.6-sol→gpt-6-astra, claude-3*, claude-sonnet-4*,
  claude-opus-4*, claude-fable-5→5-1, gemini-1.5/2.0/2.5/3-pro/3.5-flash→3.1-pro-preview or 3.8-flash,
  grok-2/3/4-latest/4.5→4.6, mistral-large→2512, mistral-medium-latest→2604, deepseek-r1/v4-pro→v4-pro-0813,
  qwen3-max/3.5/3.7→3.8, kimi-k2/k2.5/k2.6→k3, llama-3.3/4→muse-spark-1.3).
- Runtime consumer: `resolve_model_id(id) -> str` replaces the three legacy maps; each agent calls it once.
- Build-time consumer: `scripts/refresh_model_literals.py` rewrites literals in the configured paths using the
  same map, with an `--check` mode that fails when any retired ID remains outside an allowlist file
  (`scripts/baselines/retired_model_literals_allowlist.txt`, for historical docs such as release notes and
  benchmark records). Wired later as a non-required job in `metrics-drift.yml` (Tier 4, separate PR, ceiling-safe).

### 3. Request-shape hardening
- Anthropic: `compat.strip_sampling_params` and thinking defaults keyed on catalog flags, not the name regex; the
  regex stays only as a fallback for IDs absent from the catalog. `tool_choice` `any`/`tool` is never emitted for
  models with `forced_tool_choice_allowed=False`. Server-side refusal fallback (`betas=["server-side-fallback-2026-07-01"]`,
  `fallbacks="default"`) on by default for `claude-fable-5-1` and `claude-opus-5`, opt-out via settings.
  `max_tokens` floor raised from 4096 to the catalog `max_output_tokens` cap, streaming above 16K.
- OpenAI: `_build_payload` emits `max_completion_tokens` when `max_tokens_param` says so, omits sampling params when
  `supports_sampling_params=False`, and sends `reasoning_effort` (default `high`; `xhigh` for reviewer role).
  Response parsing unchanged (chat completions supported by Astra).

### 4. Merge gate
- `_OPENROUTER_REVIEWER_MODELS`: claude→`anthropic/claude-fable-5.1`, openai→`openai/gpt-6-astra`,
  grok→`x-ai/grok-4.6`, gemini→`google/gemini-3.1-pro-preview`, deepseek→`deepseek/deepseek-v4-pro-0813`,
  qwen→`qwen/qwen3.8-2.4t-a95b`, kimi→`moonshotai/kimi-k3`, meta→`meta/muse-spark-1.3`.
- `_CODEX_DEFAULT_MODELS = ("gpt-6-astra", "gpt-5.6-sol")`.
- `_resolve_model_review_identity` / `canonical_family` recognise the new IDs; family = pretraining lineage
  (Astra = openai; Fable 5.1 = anthropic; Muse Spark = meta).

## Data flow
catalog row → pins/derived constants → agent default / selector profile / reviewer map → request builder reads
capability flags → pricing tables generated from the same row → receipts and Pareto optimizer never see $0.00.
Old ID entering anywhere → `resolve_model_id` → current ID before any lookup.

## Error handling
- Unknown model at runtime: `resolve_model_id` returns the input unchanged and logs once; the agent falls back to the
  name regex path; pricing resolver falls back to `PRICING_SOURCE_DEFAULT` and marks the receipt row as estimated.
- Refusal (`stop_reason == "refusal"`) on Fable 5.1 → server-side fallback; if the whole chain refuses, the agent
  returns a structured refusal result, never an empty string.
- 400 from a rejected parameter → the agent strips the offending parameter once and retries (existing retry hook),
  logging the model ID so the catalog flag can be corrected.

## Testing
- Unit: catalog schema, reverse completeness, pins derivation, upgrade-map coverage (every retired literal found by
  the sweep script has a target), request-shape builders for Fable 5.1 and Astra (payload snapshots), pricing
  mirror equality, identity resolution and family classification for the new IDs.
- Smoke (no API keys): VibeProxy on 127.0.0.1:8318 serves `claude-fable-5-1` (Anthropic shape) and `gpt-6-astra`
  (OpenAI shape); one request each, asserting no 400 and a text block.
- Sweep: `scripts/refresh_model_literals.py --check` clean on the branch; snapshot fixtures regenerated by their own
  generators, never hand-edited.
- Gate: `make ci-required` green; `python scripts/check_canonical_metrics.py` green (constant aliases kept).

## Delivery (four PRs, tiers per docs/AGENT_OPERATING_CONTRACT.md)
1. **PR 1 — core (Tier 2):** catalog flags and rows, pins derivation, upgrade map + `resolve_model_id`, agent
   defaults, selector profiles, pricing tables generated, request-shape hardening, reverse test, sweep script.
2. **PR 2 — merge gate (Tier 4, operator signature):** reviewer family map, Codex harness default, identity
   resolver rows, consult scripts. Body records the 14-day-rule override.
3. **PR 3 — sweep (Tier 1):** generated literal rewrite across `aragora/`, `scripts/`, `sdk/`, `docs/`, `docs-site/`,
   `tests/`; allowlist for historical records. Sequenced after the old mission's SDK paydown PR #9983 merges.
4. **PR 4 — CI check (Tier 4, small):** `refresh_model_literals.py --check` as a job inside `metrics-drift.yml`
   (no new workflow file; ceilings respected).

Outside the repo (no PR): Factory custom models already carry Fable 5.1 and GPT-6 Astra; Codex config is on
`gpt-6-astra`; verify the Claude reviewer profiles resolve `claude -p` to Fable 5.1.

## Constraints
- No new top-level package, no new workflow file, no new docs page (the sweep edits existing pages only).
- Protected files untouched (`CLAUDE.md`, `aragora/__init__.py`, `.env`, `scripts/nomic_loop.py`).
- Keep `OPUS_4_7`, `GPT_5_4`, `GEMINI_3_1_PRO` exported from `model_pins.py`.
- Every PR body carries a "Reviewed design tradeoffs" section and the exit metric it serves.
- Before opening each PR, re-check `gh pr list` for #9848, #9832, #9147, #9081 and rebase if they merged.

## Out of scope
- Changing which families count toward quorum (`WESTERN_FRONTIER_FAMILIES` stays `{claude, openai}`).
- Prompt re-tuning for Fable 5.1 behavioral shifts (tracked separately; prompt audit after PR 1 lands).
- Responses API migration for OpenAI (chat completions remains the transport).

## Rollback
The upgrade map and catalog rows are data. Reverting PR 1 restores the previous defaults; PR 3's rewrite is
regenerable in either direction from the map.
