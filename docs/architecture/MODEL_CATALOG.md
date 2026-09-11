# Canonical Model Catalog

**Status:** Catalog-first (frontier-model-refresh, 2026-09-04). `aragora/models/catalog.py`
is now the load-bearing source for model identity, pricing, and provider
request-shape behavior — every pin, agent, and pricing table reads it instead
of hand-maintaining its own copy.

## Why

The #9073 and #9075 reviews (2026-07-16) empirically demonstrated that model
identity and pricing were duplicated across **eleven runtime tables** (model
pins, model selector, routing provider config, billing usage, services
metering, debate costs, pdb invoker, two agent fallback maps, server cost
estimation, billing optimizer tiers). Adversarial review discovered the drift
one table per round — including **three live provider reprices caught
mid-review** (gpt-5.5 $2.50/$10 → $5/$30; qwen3.7-max $1.25/$3.75 →
$1.475/$4.425; kimi-k2.7-code $0.72 → $0.75). Review rounds are the most
expensive drift detector the project owns; this catalog makes the detection
mechanical.

The 2026-09-04 frontier-model-refresh went further: instead of adding another
table each definer had to remember to update by hand, every pin and pricing
table now *derives* from the catalog (`aragora/config/model_pins.py`,
`aragora/models/pricing_mirror.py`), and a single upgrade map
(`aragora/models/upgrade_map.py`) plus a sweep script
(`scripts/refresh_model_literals.py`) replace the three legacy alias dicts
that had already drifted to retired slugs.

## The design (three rules)

1. **One typed source.** `aragora/models/catalog.py` defines `ModelSpec`
   (canonical/direct/OpenRouter ids, aliases, USD-per-MTok pricing, context
   and output limits, release + soak dates, plus the request-shape
   capability flags and lineage fields described below). `by_any_id()`
   resolves every accepted spelling.
2. **Offline validation, advisory liveness.** Required CI never calls the
   network: it validates against the committed
   `aragora/models/catalog_snapshot.json`. `scripts/model_catalog_drift.py`
   is the advisory live-vs-snapshot differ (`--refresh` rewrites the whole
   snapshot for a reviewed commit; `--add-missing` captures ONLY the ids the
   snapshot lacks, so a PR that adds one catalog row does not have to absorb
   every unrelated reprice and delisting accumulated since the last
   whole-file capture — those keep being reported by the default mode, where
   they can be adjudicated on their own). A scheduled advisory workflow may
   invoke either, but it must never gate a PR on live-catalog reachability.
3. **Governance stays out.** Quorum-family *eligibility* — which model may
   produce merge-authority evidence — lives in
   `aragora/swarm/quorum_evidence.py` under Tier-4 control, never in the
   catalog. The catalog knows prices, soak dates, and request shapes; it
   does not decide authority. (`soak_until` records the 14-day availability
   rule so reviewers/tools can check it; enforcement of the rule remains
   policy.)

## The current catalog

Generate this table straight from `CATALOG` — never hand-edit the rows,
they will drift the moment a price or id changes underneath them:

```bash
python3 - <<'EOF'
from aragora.models.catalog import CATALOG

rows = sorted(CATALOG.values(), key=lambda s: (s.family, s.tier != "flagship", s.canonical_id))
print("| Family | Canonical ID | Direct ID | OpenRouter slug | $/1M in | $/1M out | Context | Tier | Retired |")
print("|---|---|---|---|---:|---:|---:|---|---|")
for s in rows:
    print(
        f"| {s.family} | `{s.canonical_id}` | `{s.direct_id}` | `{s.openrouter_id}` | "
        f"{s.input_per_mtok:g} | {s.output_per_mtok:g} | {s.context_window:,} | {s.tier} | {s.retired} |"
    )
EOF
```

Output as of this commit (29 rows):

| Family | Canonical ID | Direct ID | OpenRouter slug | $/1M in | $/1M out | Context | Tier | Retired |
|---|---|---|---|---:|---:|---:|---|---|
| ai21 | `jamba-large-1.7` | `jamba-large` | `ai21/jamba-large-1.7` | 2 | 8 | 256,000 | flagship | False |
| anthropic | `claude-fable-5` | `claude-fable-5` | `anthropic/claude-fable-5` | 10 | 50 | 1,000,000 | flagship | True |
| anthropic | `claude-fable-5-1` | `claude-fable-5-1` | `anthropic/claude-fable-5.1` | 10 | 50 | 1,000,000 | flagship | False |
| anthropic | `claude-haiku-4-5-20251001` | `claude-haiku-4-5-20251001` | `anthropic/claude-haiku-4.5` | 1 | 5 | 200,000 | value | False |
| anthropic | `claude-opus-4-8` | `claude-opus-4-8` | `anthropic/claude-opus-4.8` | 5 | 25 | 1,000,000 | fallback | False |
| anthropic | `claude-opus-5` | `claude-opus-5` | `anthropic/claude-opus-5` | 5 | 25 | 1,000,000 | fallback | False |
| anthropic | `claude-sonnet-5` | `claude-sonnet-5` | `anthropic/claude-sonnet-5` | 2 | 10 | 1,000,000 | value | False |
| cohere | `command-a` | `command-a-03-2025` | `cohere/command-a` | 2.5 | 10 | 256,000 | flagship | False |
| deepseek | `deepseek-v4-pro-0813` | `deepseek-v4-pro-0813` | `deepseek/deepseek-v4-pro-0813` | 1.1207 | 3.362 | 1,048,576 | flagship | False |
| google | `gemini-3.1-pro-preview` | `gemini-3.1-pro-preview` | `google/gemini-3.1-pro-preview` | 2 | 12 | 1,048,576 | flagship | False |
| google | `gemini-3.8-flash` | `gemini-3.8-flash` | `google/gemini-3.8-flash` | 0.75 | 3.75 | 1,048,576 | value | False |
| meta | `muse-spark-1.3` | `muse-spark-1.3` | `meta/muse-spark-1.3` | 1.25 | 4.25 | 1,048,576 | flagship | False |
| minimax | `minimax-m3` | `minimax-m3` | `minimax/minimax-m3` | 0.3 | 1.2 | 1,048,576 | flagship | False |
| mistral | `mistral-medium-2604` | `mistral-medium-2604` | `mistralai/mistral-medium-3-5` | 1.5 | 7.5 | 262,144 | flagship | False |
| mistral | `mistral-large-2411` | `mistral-large-2411` | `mistralai/mistral-large-2411` | 2 | 6 | 131,072 | fallback | True |
| mistral | `mistral-large-2512` | `mistral-large-2512` | `mistralai/mistral-large-2512` | 0.5 | 1.5 | 262,144 | fallback | False |
| moonshot | `kimi-k3` | `kimi-k3` | `moonshotai/kimi-k3` | 3 | 15 | 1,048,576 | flagship | False |
| moonshot | `kimi-k2.7-code` | `kimi-k2.7-code` | `moonshotai/kimi-k2.7-code` | 0.66 | 3.4 | 262,144 | code | False |
| openai | `gpt-5.5` | `gpt-5.5` | `openai/gpt-5.5` | 5 | 30 | 1,050,000 | flagship | True |
| openai | `gpt-5.6-sol` | `gpt-5.6-sol` | `openai/gpt-5.6-sol` | 5 | 30 | 1,050,000 | flagship | True |
| openai | `gpt-6-astra` | `gpt-6-astra` | `openai/gpt-6-astra` | 10 | 50 | 1,050,000 | flagship | False |
| openai | `gpt-5.6-terra` | `gpt-5.6-terra` | `openai/gpt-5.6-terra` | 2 | 12 | 1,050,000 | value | False |
| perplexity | `sonar-reasoning-pro` | `sonar-reasoning-pro` | `perplexity/sonar-reasoning-pro` | 2 | 8 | 128,000 | flagship | False |
| qwen | `qwen3.7-max` | `qwen3.7-max` | `qwen/qwen3.7-max` | 1.475 | 4.425 | 1,000,000 | flagship | True |
| qwen | `qwen3.8-2.4t-a95b` | `qwen3.8-2.4t-a95b` | `qwen/qwen3.8-2.4t-a95b` | 2 | 6 | 1,048,576 | flagship | False |
| xai | `grok-4.3` | `grok-4.3` | `x-ai/grok-4.3` | 1.25 | 2.5 | 1,000,000 | flagship | True |
| xai | `grok-4.5` | `grok-4.5` | `x-ai/grok-4.5` | 2 | 6 | 500,000 | flagship | True |
| xai | `grok-4.6` | `grok-4.6` | `x-ai/grok-4.6` | 2 | 6 | 500,000 | flagship | False |
| zai | `glm-5.2` | `glm-5.2` | `z-ai/glm-5.2` | 0.966 | 3.036 | 1,048,576 | flagship | False |

Retired rows (`claude-fable-5`, `gpt-5.5`, `gpt-5.6-sol`, `qwen3.7-max`,
`grok-4.3`, `grok-4.5`, `mistral-large-2411`) are kept in `CATALOG`, not deleted: an old receipt
or cost report that names one must still resolve and price correctly. They
are simply excluded from `frontier_for()`/`FRONTIER` and from routing
enumeration (`ModelSpec.is_under_soak()` / `retired` both gate *adoption*
surfaces, never id resolution or pricing).

`family` (pretraining lineage: `anthropic`, `openai`, `google`, `xai`,
`mistral`, `deepseek`, `qwen`, `moonshot`, `meta`, `zai`, `minimax`, `ai21`,
`cohere`, `perplexity`) plus `tier` (`flagship` / `value` / `fallback` /
`code`) drive `frontier_for(family)` / `FRONTIER`: the newest non-retired
`tier="flagship"` row per family, so a same-family `value`/`fallback`/`code`
row released later than the flagship (e.g. Gemini 3.8 Flash after 3.1 Pro,
Opus 5 after Fable 5.1) never displaces it as the "current default" for
that provider.

## Capability flags (request-shape hardening)

`ModelSpec` also carries the fields that drive the Anthropic/OpenAI
request-shape hardening (`aragora/models/compat.py`,
`aragora/agents/api_agents/anthropic.py`,
`aragora/agents/api_agents/openai.py`) — set once per catalog row instead of
inferred per call site from a name regex:

| Flag | Meaning |
|---|---|
| `supports_sampling_params` | `False` when `temperature`/`top_p`/`top_k` return `400 invalid_request_error` (current Claude generations, current OpenAI reasoning models). |
| `thinking_default_on` | `True` when the response's first content block is a thinking block, not text — callers must use `first_text_block()` instead of `content[0].text`. |
| `forced_tool_choice_allowed` | `False` when a forced `tool_choice` (`any`/`tool`) must be downgraded to `auto`. |
| `max_tokens_param` | Request field name for the output-token cap: `"max_tokens"` or `"max_completion_tokens"`. |
| `reasoning_effort_default` | Default `reasoning_effort` value for models that take one, else `None`. |
| `cache_read_per_mtok` | Optional prompt-cache-read rate, distinct from the flat input/output rates. |
| `long_context_threshold` / `input_per_mtok_long` / `output_per_mtok_long` | Documented long-context pricing tier (xAI, per provider pricing pages): a prompt at or above the threshold bills the `*_long` rates for the whole request. |

An id the catalog does not (yet) know about (a legacy spelling, an
uncatalogued OpenRouter alias) falls back to a conservative default —
`aragora/models/compat.py`'s `_MODERN_CLAUDE` regex for
`rejects_sampling_params` specifically, `False`/`"max_tokens"`/`None`
elsewhere — so behavior for uncatalogued ids never regresses.

## Bump the catalog, not the pins

`aragora/config/model_pins.py` derives every constant it exports
(`FABLE_51_DIRECT`, `GPT6_ASTRA_VIA_OPENROUTER`, the `Role` → pin map, …)
from `CATALOG` via a single `_pin(canonical_id)` helper. **The rule this
enforces: reprice or replace a model by editing its `ModelSpec` in
`aragora/models/catalog.py`; never hand-edit a pin, a pricing table, or an
agent's default-model literal.** Every consumer listed below reads the
catalog (directly or through `model_pins`/`pricing_mirror`), so one
`ModelSpec` edit propagates everywhere:

- Every API agent (`aragora/agents/api_agents/*.py`) and the CLI agents
  (`aragora/agents/cli_agents.py`) resolve their default model and fallback
  targets from `model_pins`/`CATALOG`.
- `aragora/agents/model_selector.py`'s profiles resolve through
  `spec_or_none`/`CATALOG` instead of hardcoding price/context/capability
  numbers per profile.
- `aragora/server/handlers/debates/cost_estimation.py`'s `DEFAULT_MODELS`
  is `[FABLE_51_DIRECT, GPT6_ASTRA_DIRECT, GEMINI_31_PRO_DIRECT]` — pins,
  not literals.
- `scripts/consult_claude.py` and `scripts/fable_goal_cycle.py` read the
  catalog and pins for their default model choice.

## The upgrade map and the literal sweep

`aragora/models/upgrade_map.py` replaces the three legacy alias dicts with
one map:

- **`UPGRADES: dict[str, str]`** — every retired-or-absent spelling
  (old Claude/GPT/Gemini/Grok/Mistral/DeepSeek/Qwen/Kimi/Llama ids) mapped
  to its current canonical id. A spelling Task 1 attached as a catalog
  *alias* on an active row (e.g. `mistral-medium-latest`,
  `qwen/qwen3.8-max`) is deliberately **not** an `UPGRADES` key — it already
  resolves via `by_any_id()`, and duplicating it here would risk the two
  paths drifting apart. Targets preserve **tier** wherever the provider has
  an active value row: a `flash`/`mini`/`haiku`/`sonnet` spelling lands on
  that row rather than over-paying for the flagship, and only a family whose
  rows are all flagship-class has nowhere cheaper to land.
- **`resolve_model_id(model_id)`** — the runtime normalizer: exact
  `UPGRADES` hit wins; else an active catalog row returns its own
  `canonical_id`; else a retired row returns the successor `UPGRADES`
  declares for that **row** under any of its spellings, falling back to
  `frontier_for(spec.family).canonical_id`; else the input passes through
  unchanged. The per-row step is what makes the answer spelling-independent:
  `UPGRADES` is keyed by spelling, so a retired row whose bare id was a key
  but whose OpenRouter slug was not used to get two different successors.
- **`RETIRED_PATTERN`** — `UPGRADES` keys compiled into one regex with
  token-boundary lookarounds, so a retired key that is a literal prefix of
  a longer active spelling (`"claude-fable-5"` vs. active
  `"claude-fable-5-1"`; `"kimi-k2"` vs. active `"kimi-k2.7-code"`) never
  falsely matches the active spelling.

`scripts/refresh_model_literals.py` consumes both to find or rewrite
retired literals anywhere in the repo:

```bash
python3 scripts/refresh_model_literals.py --check   # report offenders, exit 1 if any
python3 scripts/refresh_model_literals.py --write   # rewrite them to the current spelling
```

Paths in `SKIP_PATHS` (the catalog/upgrade-map/pricing-mirror source files,
the hand-maintained pricing tables, `tests/models/`, the script and its own
test) are never touched — they are the retired-id source of truth, not
drift. `scripts/baselines/retired_model_literals_allowlist.txt` allowlists
paths that legitimately name a retired id on purpose (changelogs, dated
release notes, archived status docs); `--check` fails only on offenders
outside both. As of this commit `--check` still reports a large number of
pre-existing offenders (ordinary source files and tests written against
now-retired ids before this map existed) — clearing that backlog with
`--write` is separate, later-task scope; `CHANGELOG.md` itself is on the
allowlist, so historical entries may keep naming old ids.

## Pricing mirror (five generated tables)

`aragora/models/pricing_mirror.py` is phase 2 of the design: it derives
every hand-maintained pricing-table *shape* from `CATALOG` so a price only
ever changes in one place. Each of the five consumers below keeps its
hand-written dict under a `_LEGACY_*` name (so a receipt or env override
pinned to an old spelling keeps resolving) and publishes
`{**_LEGACY_*, **generated}` — the generated row wins on a key collision,
since the catalog is the more recently verified source:

| Consumer | Table |
|---|---|
| `aragora.billing.usage` | `PROVIDER_PRICING` |
| `aragora.pdb.real_invoker` | `_PRICE_PER_MTOK` |
| `aragora.billing.debate_costs` | `DEFAULT_PROVIDER_RATES` |
| `aragora.services.metering_models` | `MODEL_PRICING` |
| `aragora.routing.provider_config` | `PROVIDER_PRICING` (canonical-id-only projection; a model still inside `soak_until` is excluded — an adoption surface must not offer it yet) |

Retired catalog rows are still emitted into every one of these: an old
receipt referencing a retired model id must still price, even though
retired models are excluded from routing enumeration and `frontier_for()`.

## Enforcement (`ENFORCED_MODELS`)

`tests/models/test_catalog.py` asserts that every runtime-table row for an
**enforced** model agrees with its catalog spec — a covered drifting mirror
fails tests in seconds instead of consuming an adversarial review round.
`ENFORCED_MODELS` currently covers 13 of the catalog's 26 rows (the
pre-frontier-refresh models verified live through #9073/#9075); the 13 rows
added by the 2026-09-04 frontier refresh are catalogued and priced but not
yet added to `ENFORCED_MODELS` — their runtime-table mirrors are wired via
`model_pins`/`pricing_mirror` (this PR) but full per-row test enforcement is
later-task scope, same as the pre-existing known-stale legacy rows
(deepseek-v4-pro, qwen3-max) that still need adjudication before entering
enforcement.

## How to add or reprice a model

1. Edit `aragora/models/catalog.py` (one `ModelSpec`). Set `family`/`tier`
   correctly if it should become (or stop being) a `frontier_for()` pick,
   and the request-shape flags if its provider generation changed
   behavior.
2. Run `python3 scripts/model_catalog_drift.py --refresh` and commit the
   snapshot diff (live verification receipt).
3. Run `python3 -m pytest tests/models/` — it lists every enforced mirror
   row that must change; change them in the same commit. Unenforced rows
   still propagate automatically through `model_pins.py`/
   `pricing_mirror.py` since both derive from `CATALOG`.
4. If the change retires an id, add its old spellings to `UPGRADES` in
   `aragora/models/upgrade_map.py` (unless already a catalog alias) and run
   `python3 scripts/refresh_model_literals.py --check` to see what the
   sweep would touch.
5. New model on a merge-authority surface? Check `soak_until` and the
   governance pins (`aragora/swarm/quorum_evidence.py`) first.
