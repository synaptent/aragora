# Frontier Model Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every per-provider default to the current frontier model (Claude Fable 5.1, GPT-6 Astra, Gemini 3.1 Pro + 3.8 Flash, Grok 4.6, Mistral Medium 3.5, current open-weight families), make `aragora/models/catalog.py` the load-bearing source of truth, and harden the Anthropic and OpenAI request builders for the new generations.

**Architecture:** The catalog gains capability flags and the new rows; `model_pins.py`, agent defaults, selector profiles, reviewer maps, and all six pricing tables derive from it. One upgrade map (`aragora/models/upgrade_map.py`) both resolves old IDs at runtime and drives a repeatable literal-rewrite script. Request builders consult catalog flags instead of name regexes.

**Tech Stack:** Python 3.11, pytest, `Decimal` pricing tables, `git grep` for sweeps, VibeProxy on 127.0.0.1:8318 for keyless smoke tests.

**Spec:** `docs/superpowers/specs/2026-09-04-frontier-model-refresh-design.md`

## Global Constraints

- Work only in the worktree `.worktrees/frontier-model-refresh` (branch `feat/frontier-model-refresh`); never edit the main checkout.
- No new top-level package under `aragora/`; no new workflow file; no new docs page.
- Do not touch `CLAUDE.md`, `aragora/__init__.py`, `.env`, `scripts/nomic_loop.py`.
- `aragora/config/model_pins.py` must keep exporting `OPUS_4_7`, `GPT_5_4`, `GEMINI_3_1_PRO` (canonical-metrics claim `security.model_pins.frontier_aligned`).
- Direct IDs are exact: `claude-fable-5-1`, `claude-opus-5`, `claude-opus-4-8`, `gpt-6-astra`, `gpt-5.6-terra`, `gemini-3.1-pro-preview`, `gemini-3.8-flash`, `grok-4.6`, `mistral-medium-2604`, `mistral-large-2512`. OpenRouter slugs: `anthropic/claude-fable-5.1`, `openai/gpt-6-astra`, `openai/gpt-5.6-terra`, `google/gemini-3.1-pro-preview`, `google/gemini-3.8-flash`, `x-ai/grok-4.6`, `mistralai/mistral-medium-3-5`, `deepseek/deepseek-v4-pro-0813`, `qwen/qwen3.8-2.4t-a95b`, `moonshotai/kimi-k3`, `moonshotai/kimi-k2.7-code`, `meta/muse-spark-1.3`, `z-ai/glm-5.2`, `minimax/minimax-m3`.
- Prices ($/1M in, out): fable-5-1 10/50; opus-5 5/25; opus-4-8 5/25; gpt-6-astra 10/50; gpt-5.6-terra 2/12; gemini-3.1-pro-preview 2/12; gemini-3.8-flash 0.75/3.75; grok-4.6 2/6 (4/12 at ≥200K prompt); mistral-medium-2604 1.5/7.5; mistral-large-2512 0.5/1.5; deepseek-v4-pro-0813 1.12/3.36; qwen3.8 2/6; kimi-k3 3/15; kimi-k2.7-code 0.66/3.40; muse-spark-1.3 1.25/4.25; minimax-m3 0.30/1.20; glm-5.2 read from live OpenRouter at snapshot time.
- Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run only the tests named in each task plus `ruff check` / `ruff format --check` on touched files; never the full suite.
- PR bodies carry Summary, exit metric served, test commands, and a section titled "Reviewed design tradeoffs".

---

## File structure

| File | Responsibility |
|---|---|
| `aragora/models/catalog.py` (modify) | `ModelSpec` gains capability flags and `retired`; new frontier rows; `frontier_for(family)` and `spec_or_none(id)` helpers |
| `aragora/models/catalog_snapshot.json` (modify) | committed live-price capture; gains rows for every new `openrouter_id` |
| `aragora/models/upgrade_map.py` (create) | `UPGRADES` old→current, `resolve_model_id()` |
| `aragora/models/pricing_mirror.py` (create) | builds the six legacy pricing-table shapes from the catalog |
| `aragora/models/compat.py` (modify) | `rejects_sampling_params` consults catalog flags first |
| `aragora/config/model_pins.py` (modify) | constants derived from catalog; aliases kept; roles re-pinned |
| `aragora/agents/api_agents/{anthropic,openai,openai_compatible,gemini,grok,mistral,openrouter}.py` (modify) | defaults from pins; request-shape hardening; legacy maps → `resolve_model_id` |
| `aragora/agents/cli_agents.py`, `aragora/agents/model_selector.py` (modify) | defaults and profiles from catalog |
| `aragora/billing/usage.py`, `aragora/pdb/real_invoker.py`, `aragora/services/metering_models.py`, `aragora/billing/debate_costs.py`, `aragora/routing/provider_config.py`, `aragora/server/handlers/debates/cost_estimation.py` (modify) | tables = legacy rows merged with `pricing_mirror` output |
| `aragora/cli/audit.py`, `aragora/cli/document_audit.py`, `aragora/cli/documents.py` (modify) | `--model` defaults from pins |
| `aragora/swarm/quorum_evidence.py` (modify, PR 2) | reviewer family map and Codex harness default |
| `scripts/consult_claude.py`, `scripts/fable_goal_cycle.py` (modify) | defaults from pins |
| `scripts/refresh_model_literals.py` (create), `scripts/baselines/retired_model_literals_allowlist.txt` (create) | generated sweep with `--check` |
| `tests/models/test_upgrade_map.py`, `tests/models/test_reachable_defaults.py`, `tests/models/test_pricing_mirror.py`, `tests/agents/api_agents/test_request_shapes.py`, `tests/scripts/test_refresh_model_literals.py` (create); `tests/models/test_catalog.py`, `tests/config/test_model_pins_aliases.py` (modify) | tests |
| `docs/architecture/MODEL_CATALOG.md`, `CHANGELOG.md` (modify) | documentation |

---

## PR 1 — core (Tier 2)

### Task 1: Catalog capability flags and frontier rows

**Files:**
- Modify: `aragora/models/catalog.py` (`ModelSpec` at ~line 44; `CATALOG` at ~97; `ENFORCED_MODELS` at ~320)
- Modify: `aragora/models/catalog_snapshot.json`
- Test: `tests/models/test_catalog.py`

**Interfaces:**
- Produces: `ModelSpec` fields `family: str`, `supports_sampling_params: bool = True`, `thinking_default_on: bool = False`, `forced_tool_choice_allowed: bool = True`, `max_tokens_param: str = "max_tokens"`, `reasoning_effort_default: str | None = None`, `cache_read_per_mtok: float | None = None`, `retired: bool = False`; helpers `spec_or_none(model_id: str) -> ModelSpec | None` (any spelling, via `by_any_id`), `frontier_for(family: str) -> ModelSpec` (newest non-retired row for the family), `FRONTIER: dict[str, str]` mapping family → canonical_id.

- [ ] **Step 1: Write the failing tests** (append to `tests/models/test_catalog.py`)

```python
from aragora.models.catalog import CATALOG, FRONTIER, frontier_for, spec_or_none

def test_frontier_rows_present_with_flags() -> None:
    fable = CATALOG["claude-fable-5-1"]
    assert fable.direct_id == "claude-fable-5-1"
    assert fable.openrouter_id == "anthropic/claude-fable-5.1"
    assert (fable.input_per_mtok, fable.output_per_mtok) == (10.0, 50.0)
    assert fable.supports_sampling_params is False
    assert fable.thinking_default_on is True
    assert fable.forced_tool_choice_allowed is False
    astra = CATALOG["gpt-6-astra"]
    assert astra.openrouter_id == "openai/gpt-6-astra"
    assert astra.max_tokens_param == "max_completion_tokens"
    assert astra.reasoning_effort_default == "high"
    assert astra.supports_sampling_params is False
    for cid in ("gpt-5.6-terra", "gemini-3.1-pro-preview", "gemini-3.8-flash", "grok-4.6",
                "mistral-medium-2604", "mistral-large-2512", "deepseek-v4-pro-0813",
                "qwen3.8-2.4t-a95b", "kimi-k3", "kimi-k2.7-code", "muse-spark-1.3",
                "glm-5.2", "minimax-m3"):
        assert cid in CATALOG, cid

def test_frontier_for_each_family() -> None:
    assert FRONTIER["anthropic"] == "claude-fable-5-1"
    assert FRONTIER["openai"] == "gpt-6-astra"
    assert FRONTIER["google"] == "gemini-3.1-pro-preview"
    assert FRONTIER["xai"] == "grok-4.6"
    assert FRONTIER["mistral"] == "mistral-medium-2604"
    assert frontier_for("anthropic").canonical_id == "claude-fable-5-1"

def test_superseded_rows_are_retired_not_deleted() -> None:
    for cid in ("claude-fable-5", "gpt-5.6-sol", "gpt-5.5", "grok-4.5", "grok-4.3", "qwen3.7-max"):
        assert CATALOG[cid].retired is True, cid
    assert spec_or_none("anthropic/claude-fable-5") is not None
    assert spec_or_none("no-such-model") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/models/test_catalog.py -q -k "frontier or retired"`
Expected: FAIL with `ImportError: cannot import name 'FRONTIER'`

- [ ] **Step 3: Extend `ModelSpec` and add rows**

In `aragora/models/catalog.py`, add to the dataclass (after `output_per_mtok_long`):

```python
    family: str = ""  # pretraining lineage: anthropic, openai, google, xai, mistral, deepseek, qwen, moonshot, meta, zai, minimax
    supports_sampling_params: bool = True
    thinking_default_on: bool = False
    forced_tool_choice_allowed: bool = True
    max_tokens_param: str = "max_tokens"  # or "max_completion_tokens"
    reasoning_effort_default: str | None = None
    cache_read_per_mtok: float | None = None
    retired: bool = False
```

Add rows to `CATALOG` (release dates from the spec; `soak_until = release + 14 days` only for rows released within 14 days of today — Astra `2026-09-17`, gemini-3.8-flash `2026-09-16`, muse-spark-1.3 `2026-09-16`; the founder override for Astra reviewer duty is applied in PR 2 by passing `allow_soak=True` at the reviewer map, not by removing soak here):

```python
    "claude-fable-5-1": ModelSpec(
        canonical_id="claude-fable-5-1", provider="anthropic", family="anthropic",
        direct_id="claude-fable-5-1", openrouter_id="anthropic/claude-fable-5.1",
        input_per_mtok=10.0, output_per_mtok=50.0, cache_read_per_mtok=0.25,
        context_window=1_000_000, max_output_tokens=128_000, release_date=date(2026, 6, 24),
        supports_sampling_params=False, thinking_default_on=True, forced_tool_choice_allowed=False,
        aliases=("claude-fable-5.1", "anthropic/claude-fable-5-1"),
    ),
    "gpt-6-astra": ModelSpec(
        canonical_id="gpt-6-astra", provider="openai", family="openai",
        direct_id="gpt-6-astra", openrouter_id="openai/gpt-6-astra",
        input_per_mtok=10.0, output_per_mtok=50.0, cache_read_per_mtok=1.0,
        context_window=1_050_000, max_output_tokens=128_000, release_date=date(2026, 9, 3),
        soak_until=date(2026, 9, 17),
        supports_sampling_params=False, max_tokens_param="max_completion_tokens",
        reasoning_effort_default="high",
        long_context_threshold=272_000, input_per_mtok_long=20.0, output_per_mtok_long=75.0,
    ),
    "gpt-5.6-terra": ModelSpec(
        canonical_id="gpt-5.6-terra", provider="openai", family="openai",
        direct_id="gpt-5.6-terra", openrouter_id="openai/gpt-5.6-terra",
        input_per_mtok=2.0, output_per_mtok=12.0, context_window=1_050_000, max_output_tokens=128_000,
        release_date=date(2026, 7, 9), supports_sampling_params=False,
        max_tokens_param="max_completion_tokens", reasoning_effort_default="medium",
    ),
    "gemini-3.1-pro-preview": ModelSpec(
        canonical_id="gemini-3.1-pro-preview", provider="google", family="google",
        direct_id="gemini-3.1-pro-preview", openrouter_id="google/gemini-3.1-pro-preview",
        input_per_mtok=2.0, output_per_mtok=12.0, context_window=1_048_576, max_output_tokens=65_536,
        release_date=date(2026, 2, 19), aliases=("gemini-3.1-pro",),
    ),
    "gemini-3.8-flash": ModelSpec(
        canonical_id="gemini-3.8-flash", provider="google", family="google",
        direct_id="gemini-3.8-flash", openrouter_id="google/gemini-3.8-flash",
        input_per_mtok=0.75, output_per_mtok=3.75, context_window=1_048_576, max_output_tokens=65_536,
        release_date=date(2026, 9, 2), soak_until=date(2026, 9, 16),
    ),
    "grok-4.6": ModelSpec(
        canonical_id="grok-4.6", provider="xai", family="xai",
        direct_id="grok-4.6", openrouter_id="x-ai/grok-4.6",
        input_per_mtok=2.0, output_per_mtok=6.0, context_window=500_000, max_output_tokens=128_000,
        release_date=date(2026, 8, 12), long_context_threshold=200_000,
        input_per_mtok_long=4.0, output_per_mtok_long=12.0,
    ),
    "mistral-medium-2604": ModelSpec(
        canonical_id="mistral-medium-2604", provider="mistral", family="mistral",
        direct_id="mistral-medium-2604", openrouter_id="mistralai/mistral-medium-3-5",
        input_per_mtok=1.5, output_per_mtok=7.5, context_window=262_144, max_output_tokens=262_144,
        release_date=date(2026, 4, 30), aliases=("mistral-medium-3.5", "mistral-medium-latest"),
    ),
    "mistral-large-2512": ModelSpec(
        canonical_id="mistral-large-2512", provider="mistral", family="mistral",
        direct_id="mistral-large-2512", openrouter_id="mistralai/mistral-large-2512",
        input_per_mtok=0.5, output_per_mtok=1.5, context_window=262_144, max_output_tokens=131_072,
        release_date=date(2025, 12, 1), aliases=("mistral-large-latest", "mistral-large"),
    ),
    "deepseek-v4-pro-0813": ModelSpec(
        canonical_id="deepseek-v4-pro-0813", provider="openrouter", family="deepseek",
        direct_id="deepseek-v4-pro-0813", openrouter_id="deepseek/deepseek-v4-pro-0813",
        input_per_mtok=1.12, output_per_mtok=3.36, context_window=1_048_576, max_output_tokens=131_072,
        release_date=date(2026, 8, 12),
    ),
    "qwen3.8-2.4t-a95b": ModelSpec(
        canonical_id="qwen3.8-2.4t-a95b", provider="openrouter", family="qwen",
        direct_id="qwen3.8-2.4t-a95b", openrouter_id="qwen/qwen3.8-2.4t-a95b",
        input_per_mtok=2.0, output_per_mtok=6.0, context_window=1_048_576, max_output_tokens=131_072,
        release_date=date(2026, 8, 12),
    ),
    "muse-spark-1.3": ModelSpec(
        canonical_id="muse-spark-1.3", provider="openrouter", family="meta",
        direct_id="muse-spark-1.3", openrouter_id="meta/muse-spark-1.3",
        input_per_mtok=1.25, output_per_mtok=4.25, context_window=1_048_576, max_output_tokens=131_072,
        release_date=date(2026, 9, 2), soak_until=date(2026, 9, 16),
    ),
    "glm-5.2": ModelSpec(
        canonical_id="glm-5.2", provider="openrouter", family="zai",
        direct_id="glm-5.2", openrouter_id="z-ai/glm-5.2",
        input_per_mtok=<from live snapshot>, output_per_mtok=<from live snapshot>,
        context_window=1_048_576, max_output_tokens=131_072, release_date=date(2026, 5, 1),
    ),
    "minimax-m3": ModelSpec(
        canonical_id="minimax-m3", provider="openrouter", family="minimax",
        direct_id="minimax-m3", openrouter_id="minimax/minimax-m3",
        input_per_mtok=0.30, output_per_mtok=1.20, context_window=1_048_576, max_output_tokens=131_072,
        release_date=date(2026, 5, 31),
    ),
```

For `glm-5.2`, read the two prices from the live OpenRouter row in Step 4 before committing (the placeholders above must not survive into the commit). Set `family=` on every existing row (`claude-*` → `anthropic`, `gpt-*` → `openai`, `grok-*` → `xai`, `sonar-*` → `perplexity`, `command-a` → `cohere`, `jamba-*` → `ai21`, `qwen*` → `qwen`, `kimi-*` → `moonshot`). Mark `retired=True` on `claude-fable-5`, `gpt-5.6-sol`, `gpt-5.5`, `grok-4.5`, `grok-4.3`, `qwen3.7-max`. Set `supports_sampling_params=False, thinking_default_on=True` on `claude-fable-5`, `claude-opus-5`, `claude-opus-4-8` and `supports_sampling_params=False, max_tokens_param="max_completion_tokens"` on `gpt-5.6-sol`, `gpt-5.5`.

Add after `ENFORCED_MODELS`:

```python
def spec_or_none(model_id: str | None) -> ModelSpec | None:
    if not model_id:
        return None
    return by_any_id(str(model_id))


def frontier_for(family: str) -> ModelSpec:
    rows = [s for s in CATALOG.values() if s.family == family and not s.retired]
    if not rows:
        raise KeyError(f"no active catalog row for family {family!r}")
    return max(rows, key=lambda s: (s.release_date, s.canonical_id))


FRONTIER: dict[str, str] = {
    fam: frontier_for(fam).canonical_id
    for fam in sorted({s.family for s in CATALOG.values() if s.family and not s.retired})
}
```

Export `spec_or_none`, `frontier_for`, `FRONTIER` in `__all__` and in `aragora/models/__init__.py`.

- [ ] **Step 4: Refresh the snapshot for the new OpenRouter slugs**

```bash
python3 - <<'EOF'
import json, urllib.request
from aragora.models.catalog import CATALOG, snapshot_path
live = {m["id"]: m for m in json.load(urllib.request.urlopen("https://openrouter.ai/api/v1/models"))["data"]}
snap = json.loads(snapshot_path().read_text())
for spec in CATALOG.values():
    m = live.get(spec.openrouter_id)
    if m is None:
        print("NOT ON OPENROUTER:", spec.openrouter_id); continue
    snap["models"][spec.openrouter_id] = {
        "input_per_mtok": round(float(m["pricing"]["prompt"]) * 1e6, 4),
        "output_per_mtok": round(float(m["pricing"]["completion"]) * 1e6, 4),
        "context_length": m.get("context_length"),
        "created": m.get("created"),
    }
snapshot_path().write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
print("snapshot rows:", len(snap["models"]))
EOF
```

Copy the printed `glm-5.2` prices into the catalog row. If a slug prints `NOT ON OPENROUTER`, fix the slug in the catalog (do not invent one).

- [ ] **Step 5: Run the catalog tests**

Run: `python3 -m pytest tests/models/test_catalog.py -q`
Expected: PASS (including `test_catalog_matches_committed_snapshot`)

- [ ] **Step 6: Commit**

```bash
git add aragora/models/catalog.py aragora/models/catalog_snapshot.json aragora/models/__init__.py tests/models/test_catalog.py
git commit -m "feat(models): add frontier rows, capability flags, and family frontier lookup to the catalog"
```

---

### Task 2: Upgrade map and `resolve_model_id`

**Files:**
- Create: `aragora/models/upgrade_map.py`
- Test: `tests/models/test_upgrade_map.py`

**Interfaces:**
- Produces: `UPGRADES: dict[str, str]` (old spelling → canonical_id in `CATALOG`), `resolve_model_id(model_id: str | None) -> str | None` (returns canonical current id for retired/legacy inputs, the input unchanged otherwise, `None` for `None`), `RETIRED_PATTERN: re.Pattern[str]` matching every key for the sweep script.

- [ ] **Step 1: Write the failing test**

```python
# tests/models/test_upgrade_map.py
import re
import pytest
from aragora.models.catalog import CATALOG
from aragora.models.upgrade_map import RETIRED_PATTERN, UPGRADES, resolve_model_id

@pytest.mark.parametrize("old,new", [
    ("claude-fable-5", "claude-fable-5-1"),
    ("anthropic/claude-fable-5", "claude-fable-5-1"),
    ("claude-3-opus-20240229", "claude-fable-5-1"),
    ("claude-sonnet-4-6", "claude-fable-5-1"),
    ("gpt-4", "gpt-6-astra"), ("gpt-4o", "gpt-6-astra"), ("gpt-4o-mini", "gpt-5.6-terra"),
    ("gpt-5.5", "gpt-6-astra"), ("gpt-5.6-sol", "gpt-6-astra"), ("openai/gpt-5.3", "gpt-6-astra"),
    ("gemini-2.0-flash", "gemini-3.8-flash"), ("gemini-1.5-flash", "gemini-3.8-flash"),
    ("gemini-3-pro", "gemini-3.1-pro-preview"), ("gemini-3.1-pro", "gemini-3.1-pro-preview"),
    ("grok-2", "grok-4.6"), ("grok-4-latest", "grok-4.6"), ("x-ai/grok-4.5", "grok-4.6"),
    ("mistral-large", "mistral-large-2512"), ("mistral-medium-latest", "mistral-medium-2604"),
    ("deepseek-r1", "deepseek-v4-pro-0813"), ("deepseek/deepseek-v4-pro", "deepseek-v4-pro-0813"),
    ("qwen3-max", "qwen3.8-2.4t-a95b"), ("qwen/qwen3.7-max", "qwen3.8-2.4t-a95b"),
    ("kimi-k2", "kimi-k3"), ("moonshotai/kimi-k2-thinking", "kimi-k3"),
    ("llama-3.3-70b", "muse-spark-1.3"), ("meta-llama/llama-4-maverick", "muse-spark-1.3"),
])
def test_known_upgrades(old: str, new: str) -> None:
    assert resolve_model_id(old) == new

def test_every_target_is_an_active_catalog_row() -> None:
    for old, new in UPGRADES.items():
        assert new in CATALOG, (old, new)
        assert not CATALOG[new].retired, (old, new)

def test_current_ids_pass_through_and_none_is_none() -> None:
    assert resolve_model_id("claude-fable-5-1") == "claude-fable-5-1"
    assert resolve_model_id("some-unknown-model") == "some-unknown-model"
    assert resolve_model_id(None) is None

def test_retired_pattern_matches_keys_only() -> None:
    for old in UPGRADES:
        assert RETIRED_PATTERN.search(old), old
    assert not RETIRED_PATTERN.search("claude-fable-5-1")
    assert not RETIRED_PATTERN.search("gpt-6-astra")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/models/test_upgrade_map.py -q`
Expected: FAIL with `ModuleNotFoundError: aragora.models.upgrade_map`

- [ ] **Step 3: Implement**

```python
# aragora/models/upgrade_map.py
"""Single old→current model-ID map.

Runtime: ``resolve_model_id`` normalises any legacy spelling before catalog or
pricing lookups. Build time: ``scripts/refresh_model_literals.py`` rewrites
literals with the same table, so the repo never disagrees with the runtime.
"""
from __future__ import annotations

import re

from aragora.models.catalog import CATALOG

_ANTHROPIC = "claude-fable-5-1"
_OPENAI = "gpt-6-astra"
_OPENAI_VALUE = "gpt-5.6-terra"
_GOOGLE_PRO = "gemini-3.1-pro-preview"
_GOOGLE_FLASH = "gemini-3.8-flash"
_XAI = "grok-4.6"
_MISTRAL_LARGE = "mistral-large-2512"
_MISTRAL_MEDIUM = "mistral-medium-2604"
_DEEPSEEK = "deepseek-v4-pro-0813"
_QWEN = "qwen3.8-2.4t-a95b"
_KIMI = "kimi-k3"
_META = "muse-spark-1.3"

UPGRADES: dict[str, str] = {
    # Anthropic — everything Claude that is not the current Fable goes to Fable 5.1
    **{k: _ANTHROPIC for k in (
        "claude-fable-5", "anthropic/claude-fable-5", "claude-fable-5.1", "anthropic/claude-fable-5.1",
        "claude-3-opus-20240229", "claude-3-opus", "claude-3-5-sonnet-20241022", "claude-3.5-sonnet",
        "claude-3-5-sonnet-20240620", "claude-3-7-sonnet-20250219", "claude-3-haiku-20240307",
        "claude-3-5-haiku-20241022", "claude-sonnet-4-20250514", "claude-sonnet-4", "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-6", "claude-sonnet-4.6", "claude-opus-4-20250514", "claude-opus-4", "claude-opus-4-1-20250805",
        "claude-opus-4-5-20251101", "claude-opus-4-6", "claude-opus-4.6", "claude-opus-4-7", "claude-opus-4.7",
        "claude-opus-4.1", "anthropic/claude-opus-4.1", "anthropic/claude-3-haiku", "anthropic/claude-3.5-sonnet",
        "anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4",
    )},
    # OpenAI — flagship spellings → Astra; small/cheap spellings → Terra
    **{k: _OPENAI for k in (
        "gpt-4", "gpt-4-turbo", "gpt-4-turbo-preview", "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", "gpt-5.1", "gpt-5.2",
        "gpt-5.3", "gpt-5.4", "gpt-5.5", "gpt-5.6-sol", "openai/gpt-4o", "openai/gpt-5.3", "openai/gpt-5.4",
        "openai/gpt-5.5", "openai/gpt-5.6-sol", "o1", "o3", "o3-pro", "o4-mini",
    )},
    **{k: _OPENAI_VALUE for k in (
        "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5-mini", "gpt-5.4-mini", "gpt-5.6-luna",
        "openai/gpt-4o-mini", "openai/gpt-5.4-mini", "openai/gpt-5.6-luna", "o1-mini", "o3-mini",
    )},
    # Google
    **{k: _GOOGLE_PRO for k in (
        "gemini-3-pro", "gemini-3.1-pro", "google/gemini-3.1-pro", "google/gemini-3-pro", "gemini-2.5-pro",
        "gemini-1.5-pro", "gemini-pro",
    )},
    **{k: _GOOGLE_FLASH for k in (
        "gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-3-flash",
        "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "google/gemini-2.0-flash", "google/gemini-3-flash-preview",
    )},
    # xAI
    **{k: _XAI for k in ("grok-2", "grok-3", "grok-3-mini", "grok-4", "grok-4-latest", "grok-4.3", "grok-4.5",
                        "x-ai/grok-4", "x-ai/grok-4.3", "x-ai/grok-4.5")},
    # Mistral
    **{k: _MISTRAL_LARGE for k in ("mistral-large", "mistral-large-latest", "mistral-large-2411", "mistralai/mistral-large")},
    **{k: _MISTRAL_MEDIUM for k in ("mistral-medium", "mistral-medium-latest", "mistral-medium-3.1", "mistralai/mistral-medium-3.1")},
    # OpenRouter-routed families
    **{k: _DEEPSEEK for k in ("deepseek-r1", "deepseek/deepseek-r1", "deepseek-v3", "deepseek/deepseek-v3", "deepseek-v4-pro",
                            "deepseek/deepseek-v4-pro", "deepseek-chat", "deepseek/deepseek-chat")},
    **{k: _QWEN for k in ("qwen3-max", "qwen/qwen3-max", "qwen3.5-plus-02-15", "qwen/qwen3.5-plus-02-15", "qwen3.7-max",
                        "qwen/qwen3.7-max", "qwen3.8-max", "qwen/qwen3.8-max", "qwen3-coder", "qwen/qwen3-coder")},
    **{k: _KIMI for k in ("kimi-k2", "moonshotai/kimi-k2", "kimi-k2.5", "moonshotai/kimi-k2.5", "kimi-k2.6",
                        "moonshotai/kimi-k2.6", "kimi-k2-thinking", "moonshotai/kimi-k2-thinking", "moonshot-v1-8k")},
    **{k: _META for k in ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct", "llama-4-maverick", "meta-llama/llama-4-maverick",
                        "llama-4-scout", "meta-llama/llama-4-scout", "meta/muse-spark-1.1", "meta/muse-spark-1.2")},
}

RETIRED_PATTERN: re.Pattern[str] = re.compile(
    "|".join(re.escape(k) for k in sorted(UPGRADES, key=len, reverse=True))
)


def resolve_model_id(model_id: str | None) -> str | None:
    """Map a legacy or superseded model spelling to the current catalog id."""
    if model_id is None:
        return None
    current = UPGRADES.get(model_id)
    if current is not None:
        return current
    return model_id
```

The literal lists above are the spellings the inventory found; `test_every_target_is_an_active_catalog_row` protects against typos in targets. Note `qwen3.8-max` keeps its own catalog row today — if the qwen team decides `qwen3.8-max` (Alibaba direct) should remain the canonical row, change `_QWEN` to `"qwen3.8-max"` and add `qwen/qwen3.8-2.4t-a95b` as its `openrouter_id`; the test suite drives the decision, not the literal.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/models/test_upgrade_map.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add aragora/models/upgrade_map.py tests/models/test_upgrade_map.py
git commit -m "feat(models): add the single old-to-current model upgrade map with resolve_model_id"
```

---

### Task 3: Pins derived from the catalog; roles re-pinned

**Files:**
- Modify: `aragora/config/model_pins.py` (constants ~45-110, `_ROLE_TO_PIN` ~139-156)
- Test: `tests/config/test_model_pins_aliases.py`

**Interfaces:**
- Produces: `FABLE_51_DIRECT`, `FABLE_51_VIA_OPENROUTER`, `GPT6_ASTRA_DIRECT`, `GPT6_ASTRA_VIA_OPENROUTER`, `GPT56_TERRA_DIRECT`, `GPT56_TERRA_VIA_OPENROUTER`, `GEMINI_38_FLASH_DIRECT`, `GEMINI_38_FLASH_VIA_OPENROUTER`, `GROK_46_DIRECT`, `GROK_46_VIA_OPENROUTER`, `MISTRAL_MEDIUM_DIRECT`, `MISTRAL_MEDIUM_VIA_OPENROUTER`; existing names kept as aliases (`FABLE_5_DIRECT = FABLE_51_DIRECT`, `GPT56_SOL_DIRECT = GPT6_ASTRA_DIRECT`, `GPT55_DIRECT = GPT6_ASTRA_DIRECT`, `GROK_4_DIRECT = GROK_46_DIRECT`, `OPUS_4_7`, `GPT_5_4`, `GEMINI_3_1_PRO` unchanged names); `frontier_model_for_role`, `direct_model_for_role`, `openrouter_alias_for_role` unchanged signatures.

- [ ] **Step 1: Write the failing test** (append)

```python
from aragora.config import model_pins as mp
from aragora.models.catalog import CATALOG

def test_pins_come_from_catalog() -> None:
    assert mp.FABLE_51_DIRECT == CATALOG["claude-fable-5-1"].direct_id
    assert mp.FABLE_51_VIA_OPENROUTER == CATALOG["claude-fable-5-1"].openrouter_id
    assert mp.GPT6_ASTRA_DIRECT == "gpt-6-astra"
    assert mp.GEMINI_31_PRO_DIRECT == "gemini-3.1-pro-preview"  # the real Gemini API code
    assert mp.GROK_46_DIRECT == "grok-4.6" and mp.GROK_46_VIA_OPENROUTER == "x-ai/grok-4.6"

def test_legacy_constant_names_still_exported() -> None:
    for name in ("OPUS_4_7", "GPT_5_4", "GEMINI_3_1_PRO", "FABLE_5_DIRECT", "GPT56_SOL_DIRECT", "GPT55_DIRECT", "GROK_4_DIRECT"):
        assert hasattr(mp, name), name

def test_every_role_pins_fable_or_astra_or_family_frontier() -> None:
    for role in ("proposer", "critic", "synthesizer", "quality_reviewer", "security_auditor",
                 "compliance_auditor", "judge", "default"):
        assert mp.direct_model_for_role(role) == "claude-fable-5-1", role
    assert mp.direct_model_for_role("reviewer") == "gpt-6-astra"
    assert mp.direct_model_for_role("devils_advocate") == "grok-4.6"
    assert mp.direct_model_for_role("researcher") == "gemini-3.1-pro-preview"
    assert mp.openrouter_alias_for_role("reviewer") == "openai/gpt-6-astra"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/config/test_model_pins_aliases.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'FABLE_51_DIRECT'`

- [ ] **Step 3: Implement**

Replace the literal constants block with derivations:

```python
from aragora.models.catalog import CATALOG as _CATALOG

def _pin(canonical_id: str) -> tuple[str, str]:
    spec = _CATALOG[canonical_id]
    return spec.direct_id, spec.openrouter_id

FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER = _pin("claude-fable-5-1")
OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER = _pin("claude-opus-5")
OPUS_48_DIRECT, OPUS_48_VIA_OPENROUTER = _pin("claude-opus-4-8")
GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER = _pin("gpt-6-astra")
GPT56_TERRA_DIRECT, GPT56_TERRA_VIA_OPENROUTER = _pin("gpt-5.6-terra")
GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER = _pin("gemini-3.1-pro-preview")
GEMINI_38_FLASH_DIRECT, GEMINI_38_FLASH_VIA_OPENROUTER = _pin("gemini-3.8-flash")
GROK_46_DIRECT, GROK_46_VIA_OPENROUTER = _pin("grok-4.6")
MISTRAL_MEDIUM_DIRECT, MISTRAL_MEDIUM_VIA_OPENROUTER = _pin("mistral-medium-2604")
MISTRAL_LARGE_DIRECT, MISTRAL_LARGE_VIA_OPENROUTER = _pin("mistral-large-2512")

# Back-compat names (kept for importers and the canonical-metrics claim). They now point at the frontier.
FABLE_5_DIRECT, FABLE_5_VIA_OPENROUTER = FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER
GPT56_SOL_DIRECT, GPT56_SOL_VIA_OPENROUTER = GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER
GPT55_DIRECT, GPT55_VIA_OPENROUTER = GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER
GPT54_DIRECT, GPT54_VIA_OPENROUTER = GPT55_DIRECT, GPT55_VIA_OPENROUTER
GROK_4_DIRECT, GROK_4_VIA_OPENROUTER = GROK_46_DIRECT, GROK_46_VIA_OPENROUTER
OPUS_47_DIRECT, OPUS_47_VIA_OPENROUTER = OPUS_48_DIRECT, OPUS_48_VIA_OPENROUTER
OPUS_4_7 = OPUS_47_DIRECT
OPUS_4_8 = OPUS_48_DIRECT
OPUS_5 = OPUS_5_DIRECT
GPT_5_4 = GPT55_DIRECT
GEMINI_3_1_PRO = GEMINI_31_PRO_DIRECT
```

Re-pin roles:

```python
_ROLE_TO_PIN: Final[dict[Role, _RolePin]] = {
    "proposer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "critic": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "synthesizer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "devils_advocate": _RolePin(GROK_46_DIRECT, GROK_46_VIA_OPENROUTER),
    "researcher": _RolePin(GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER),
    "reviewer": _RolePin(GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER),
    "quality_reviewer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "security_auditor": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "compliance_auditor": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "judge": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "default": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
}
```

Add the new names to `__all__`. Keep the module docstring's "one place to bump the frontier" sentence and add: "Values derive from `aragora.models.catalog`; bump the catalog, not this file."

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/config/test_model_pins_aliases.py -q && python3 scripts/check_canonical_metrics.py 2>&1 | tail -3`
Expected: tests PASS; canonical metrics check reports the `security.model_pins.frontier_aligned` claim green.

- [ ] **Step 5: Commit**

```bash
git add aragora/config/model_pins.py tests/config/test_model_pins_aliases.py
git commit -m "feat(config): derive model pins from the catalog and re-pin every role to the frontier"
```

---

### Task 4: Reverse completeness test (fails until Tasks 5-6 land)

**Files:**
- Create: `tests/models/test_reachable_defaults.py`

**Interfaces:**
- Consumes: `spec_or_none`, `resolve_model_id`; every definer module listed in the test.

- [ ] **Step 1: Write the test**

```python
# tests/models/test_reachable_defaults.py
"""Every model a default can reach must be a priced, active catalog row."""
import importlib
import pytest
from aragora.models.catalog import spec_or_none
from aragora.models.upgrade_map import resolve_model_id


def _reachable_defaults() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    from aragora.config import model_pins as mp
    for role in ("proposer", "critic", "synthesizer", "devils_advocate", "researcher", "reviewer",
                 "quality_reviewer", "security_auditor", "compliance_auditor", "judge", "default"):
        out.append((f"pins.{role}.direct", mp.direct_model_for_role(role)))
        out.append((f"pins.{role}.openrouter", mp.openrouter_alias_for_role(role)))
    from aragora.agents.model_selector import MODEL_PROFILES
    for name, prof in MODEL_PROFILES.items():
        out.append((f"profile.{name}", prof.model_id))
    from aragora.agents.api_agents import anthropic, openai, gemini, grok, mistral, openai_compatible
    for mod in (anthropic, openai, gemini, grok, mistral):
        out.append((f"{mod.__name__}.DEFAULT_MODEL", getattr(mod, "DEFAULT_MODEL")))
    out.append(("openai_compatible.DEFAULT_FALLBACK_MODEL", openai_compatible.DEFAULT_FALLBACK_MODEL))
    from aragora.server.handlers.debates import cost_estimation
    for m in cost_estimation.DEFAULT_MODELS:
        out.append(("cost_estimation.DEFAULT_MODELS", m))
    from aragora.swarm import quorum_evidence as qe
    for fam, slug in qe._OPENROUTER_REVIEWER_MODELS.items():
        out.append((f"reviewer.{fam}", slug))
    for m in qe._CODEX_DEFAULT_MODELS:
        out.append(("codex_default", m))
    return out


@pytest.mark.parametrize("where,model_id", _reachable_defaults())
def test_reachable_default_is_priced_and_active(where: str, model_id: str) -> None:
    spec = spec_or_none(resolve_model_id(model_id))
    assert spec is not None, f"{where}: {model_id!r} has no catalog row"
    assert not spec.retired, f"{where}: {model_id!r} is retired"
    assert spec.input_per_mtok > 0 and spec.output_per_mtok > 0, f"{where}: {model_id!r} unpriced"
```

- [ ] **Step 2: Run to verify it fails on today's definers**

Run: `python3 -m pytest tests/models/test_reachable_defaults.py -q 2>&1 | tail -5`
Expected: FAIL (e.g. `profile.claude: 'claude-sonnet-4-6' is retired`, `openai_compatible.DEFAULT_FALLBACK_MODEL: 'openai/gpt-5.3'`). Do not fix here; Tasks 5-6 make it pass. Commit the test now so the gap is on record.

- [ ] **Step 3: Commit**

```bash
git add tests/models/test_reachable_defaults.py
git commit -m "test(models): add reverse completeness check for every reachable model default"
```

---

### Task 5: Definers read the catalog and pins

**Files:**
- Modify: `aragora/agents/api_agents/anthropic.py:78,111-115` (default, `OPENROUTER_MODEL_MAP`, `DEFAULT_FALLBACK_MODEL`)
- Modify: `aragora/agents/api_agents/openai.py:82,130`
- Modify: `aragora/agents/api_agents/openai_compatible.py:95`
- Modify: `aragora/agents/api_agents/gemini.py:56-81,98,139`
- Modify: `aragora/agents/api_agents/grok.py:14,48`
- Modify: `aragora/agents/api_agents/mistral.py:16,54`
- Modify: `aragora/agents/api_agents/openrouter.py` registrations at 613/639/683/709/735/761/787/839/869/896/1015/1041
- Modify: `aragora/agents/cli_agents.py:234-281,365,730,829,870,1046,1141,1176,1242,1250,1286,1323,1335,1423-1425`
- Modify: `aragora/agents/model_selector.py:103-540`
- Modify: `aragora/server/handlers/debates/cost_estimation.py:24-48`
- Modify: `aragora/cli/audit.py:120`, `aragora/cli/document_audit.py:506`, `aragora/cli/documents.py:96`
- Modify: `scripts/consult_claude.py:71-82`, `scripts/fable_goal_cycle.py:64`
- Test: `tests/models/test_reachable_defaults.py` (from Task 4), `tests/agents/test_agent_anthropic.py`, `tests/cli/test_cli_agents.py`

**Interfaces:**
- Consumes: `model_pins.*_DIRECT/_VIA_OPENROUTER`, `resolve_model_id`, `CATALOG`.
- Produces: each api agent module exposes `DEFAULT_MODEL: str` (module constant used by the registry decorator and the constructor default).

- [ ] **Step 1: Anthropic agent**

At the top of `anthropic.py`:

```python
from aragora.config.model_pins import FABLE_51_DIRECT, OPUS_5_DIRECT
from aragora.models.upgrade_map import resolve_model_id

DEFAULT_MODEL = FABLE_51_DIRECT
DEFAULT_FALLBACK_MODEL = OPUS_5_DIRECT
```

Replace `default_model="claude-opus-5"` (line 78) with `default_model=DEFAULT_MODEL`, the constructor default (line 115) with `model: str = DEFAULT_MODEL`, and delete `OPENROUTER_MODEL_MAP` (lines 98-110); where it was consulted, call `resolve_model_id(model)`. Keep `DEFAULT_FALLBACK_MODEL` semantics (refusal fallback target stays `claude-opus-4-8` where the code says so; do not change that constant's meaning if it is the refusal fallback — read the surrounding comment).

- [ ] **Step 2: OpenAI, Gemini, Grok, Mistral, openai_compatible**

`openai.py`: `DEFAULT_MODEL = GPT6_ASTRA_DIRECT`; replace both literals. `openai_compatible.py:95`: `DEFAULT_FALLBACK_MODEL = GPT56_TERRA_VIA_OPENROUTER` (value tier; import from pins). `gemini.py`: `DEFAULT_MODEL = GEMINI_31_PRO_DIRECT`; replace `GEMINI_MODEL_ALIASES` lookups with `resolve_model_id`, deleting the dict. `grok.py`: `DEFAULT_MODEL = GROK_46_DIRECT`. `mistral.py`: `DEFAULT_MODEL = MISTRAL_MEDIUM_DIRECT`; keep `codestral-latest` for the code agent (it is a distinct product, add it to the catalog only if the reverse test reaches it).

- [ ] **Step 3: OpenRouter registrations**

For each `register(...)`/constant at the listed lines, replace the slug with `CATALOG["<canonical>"].openrouter_id`: deepseek → `deepseek-v4-pro-0813`; llama-3.3 and llama-4 → `muse-spark-1.3` (family meta; rename the agent display names accordingly); mistral → `mistral-large-2512` (unchanged value, now from catalog); qwen → `qwen3.8-2.4t-a95b`; qwen3.5-plus → remove registration (superseded); kimi-k2-thinking → `kimi-k3`; `moonshot-v1-8k` → `kimi-k3`; `01-ai/yi-large` → remove registration (retired, no catalog row).

- [ ] **Step 4: CLI agents and model selector**

`cli_agents.py`: delete `OPENROUTER_MODEL_MAP` (234-281) and route through `resolve_model_id`; replace each per-CLI default literal with the matching pin (`gpt-5.5`→`GPT6_ASTRA_DIRECT`, `claude-fable-5`→`FABLE_51_DIRECT`, `gemini-3.1-pro-preview`→`GEMINI_31_PRO_DIRECT`, `grok-4-latest`→`GROK_46_DIRECT`, `gemini-3.5-flash`→`GEMINI_38_FLASH_DIRECT`, `kimi-k2`→`CATALOG["kimi-k3"].direct_id`, `qwen3-coder`→`CATALOG["qwen3.8-2.4t-a95b"].direct_id`, `deepseek-v4-pro`→`CATALOG["deepseek-v4-pro-0813"].direct_id`); the default panel at 1423-1425 builds from `FABLE_51_DIRECT`, `GPT6_ASTRA_DIRECT`, `GEMINI_31_PRO_DIRECT`, `GROK_46_DIRECT`.

`model_selector.py`: for every profile, set `model_id=CATALOG[<canonical>].direct_id`, `cost_input_per_1k=CATALOG[...].input_per_mtok / 1000`, `cost_output_per_1k=... / 1000`, `max_context_tokens=CATALOG[...].context_window`, `max_output_tokens=CATALOG[...].max_output_tokens`. Mapping: `claude`→`claude-fable-5-1`, `claude-opus`→`claude-fable-5-1` (rename display "Claude Fable 5.1"), `gpt`/`gpt-5.5`→`gpt-6-astra`, `gpt-4o`→`gpt-5.6-terra` (value profile), `gemini`→`gemini-3.1-pro-preview`, `gemini-flash`→`gemini-3.8-flash`, `mistral`→`mistral-medium-2604`, `deepseek*`→`deepseek-v4-pro-0813`, `grok`→`grok-4.6`, `qwen`→`qwen3.8-2.4t-a95b`, `kimi`→`kimi-k3`, `llama`→`muse-spark-1.3`. Keep capability scores as they are (they are judgment, not catalog data).

- [ ] **Step 5: Cost estimation and CLI `--model` defaults**

`cost_estimation.py`: `DEFAULT_MODELS = [FABLE_51_DIRECT, GPT6_ASTRA_DIRECT, GEMINI_31_PRO_DIRECT]`; rebuild `MODEL_ALIASES` as `{spelling: (spec.provider, spec.canonical_id) for spec in CATALOG.values() for spelling in spec.all_ids()}` merged over the existing legacy rows (keep legacy rows so old receipts still resolve). `cli/audit.py:120` → `GEMINI_38_FLASH_DIRECT`; `cli/document_audit.py:506` → `GEMINI_31_PRO_DIRECT`; `cli/documents.py:96` → `GEMINI_38_FLASH_DIRECT`. `scripts/consult_claude.py`: `DEFAULT_MODEL = FABLE_51_DIRECT`, `FALLBACK_MODEL = OPUS_5_DIRECT`, `DEFAULT_OPENROUTER_MODEL` env default `FABLE_51_VIA_OPENROUTER`, `API_UNSUPPORTED_MODELS = {"claude-fable-5", "claude-fable-5-1"}` only if the direct API still refuses Fable for this org (test with VibeProxy in Task 7; if it works, empty the set). `scripts/fable_goal_cycle.py:64` → `FABLE_51_DIRECT`.

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest tests/models/test_reachable_defaults.py tests/agents/test_agent_anthropic.py tests/cli/test_cli_agents.py tests/agents/api_agents/test_openrouter.py -q 2>&1 | tail -8`
Expected: `test_reachable_defaults` PASS; the agent tests may fail on pinned legacy IDs — update those assertions to the new pins (a registry-assert test keeps the old ID alongside only if the old model is still served; retired IDs are replaced).

- [ ] **Step 7: Commit**

```bash
git add aragora/agents aragora/server/handlers/debates/cost_estimation.py aragora/cli/audit.py aragora/cli/document_audit.py aragora/cli/documents.py scripts/consult_claude.py scripts/fable_goal_cycle.py tests/agents tests/cli
git commit -m "feat(agents): every model default and profile reads the catalog and pins; legacy maps route through resolve_model_id"
```

---

### Task 6: Pricing tables generated from the catalog

**Files:**
- Create: `aragora/models/pricing_mirror.py`
- Modify: `aragora/billing/usage.py:34+`, `aragora/pdb/real_invoker.py:171+`, `aragora/services/metering_models.py` (`MODEL_PRICING`), `aragora/billing/debate_costs.py:28+`, `aragora/routing/provider_config.py:62+`
- Test: `tests/models/test_pricing_mirror.py`, `tests/models/test_catalog.py` (existing mirror tests), `tests/routing/test_pricing.py`, `tests/billing/`

**Interfaces:**
- Produces: `usage_rows() -> dict[str, dict[str, Decimal]]` (provider → `{id: in, f"{id}-output": out}`), `pdb_rows() -> dict[str, tuple[float, float]]`, `debate_cost_rows() -> dict[str, dict[str, tuple[Decimal, Decimal]]]`, `metering_rows() -> dict[str, dict[str, float]]` (match the existing `MODEL_PRICING` value shape — read it first), `provider_config_rows() -> dict[str, ProviderPricing]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/models/test_pricing_mirror.py
from decimal import Decimal
from aragora.models.catalog import CATALOG
from aragora.models import pricing_mirror as pm

def test_usage_rows_cover_every_active_row_with_exact_prices() -> None:
    rows = pm.usage_rows()
    spec = CATALOG["gpt-6-astra"]
    assert rows["openai"]["gpt-6-astra"] == Decimal("10.00")
    assert rows["openai"]["gpt-6-astra-output"] == Decimal("50.00")
    for s in CATALOG.values():
        if s.retired:
            continue
        assert rows[s.provider][s.canonical_id] == Decimal(str(s.input_per_mtok))

def test_legacy_tables_contain_mirror_rows() -> None:
    from aragora.billing.usage import PROVIDER_PRICING
    from aragora.pdb.real_invoker import _PRICE_PER_MTOK
    from aragora.billing.debate_costs import DEFAULT_PROVIDER_RATES
    from aragora.routing.provider_config import PROVIDER_PRICING as ROUTING
    assert PROVIDER_PRICING["anthropic"]["claude-fable-5-1"] == Decimal("10.00")
    assert _PRICE_PER_MTOK["claude-fable-5-1"] == (10.00, 50.00)
    assert DEFAULT_PROVIDER_RATES["openai"]["gpt-6-astra"] == (Decimal("10.00"), Decimal("50.00"))
    assert ROUTING["grok-4.6"].input_cost_per_1k == 0.002 and ROUTING["grok-4.6"].output_cost_per_1k == 0.006
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/models/test_pricing_mirror.py -q`
Expected: FAIL with `ModuleNotFoundError: aragora.models.pricing_mirror`

- [ ] **Step 3: Implement the mirror and wire the tables**

```python
# aragora/models/pricing_mirror.py
"""Generate the legacy pricing-table shapes from the catalog so a price lives in one place."""
from __future__ import annotations
from decimal import Decimal
from aragora.models.catalog import CATALOG, ModelSpec

def _dec(x: float) -> Decimal:
    return Decimal(f"{x:.4f}").normalize() if x != round(x, 2) else Decimal(f"{x:.2f}")

def _active() -> list[ModelSpec]:
    return [s for s in CATALOG.values()]  # retired rows stay priced: old receipts must still resolve

def usage_rows() -> dict[str, dict[str, Decimal]]:
    out: dict[str, dict[str, Decimal]] = {}
    for s in _active():
        prov = out.setdefault(s.provider, {})
        for spelling in s.all_ids():
            prov[spelling] = _dec(s.input_per_mtok)
            prov[f"{spelling}-output"] = _dec(s.output_per_mtok)
    return out

def pdb_rows() -> dict[str, tuple[float, float]]:
    return {sp: (s.input_per_mtok, s.output_per_mtok) for s in _active() for sp in s.all_ids()}

def debate_cost_rows() -> dict[str, dict[str, tuple[Decimal, Decimal]]]:
    out: dict[str, dict[str, tuple[Decimal, Decimal]]] = {}
    for s in _active():
        prov = out.setdefault(s.provider, {})
        for sp in s.all_ids():
            prov[sp] = (_dec(s.input_per_mtok), _dec(s.output_per_mtok))
    return out

def provider_config_rows():
    from aragora.routing.provider_config import ProviderPricing
    return {
        sp: ProviderPricing(
            provider_name=s.provider, model_name=sp,
            input_cost_per_1k=s.input_per_mtok / 1000, output_cost_per_1k=s.output_per_mtok / 1000,
            context_window=s.context_window,
        )
        for s in _active() for sp in s.all_ids()
    }
```

Add `metering_rows()` after reading `MODEL_PRICING`'s value shape in `services/metering_models.py` and mirroring it exactly. In each table module, keep the hand-written legacy dict under a `_LEGACY_*` name and define the public name as `{**_LEGACY, **mirror()}` (mirror wins), e.g. in `billing/usage.py`:

```python
from aragora.models.pricing_mirror import usage_rows
_LEGACY_PROVIDER_PRICING = PROVIDER_PRICING  # the existing literal dict, renamed
PROVIDER_PRICING = {
    prov: {**_LEGACY_PROVIDER_PRICING.get(prov, {}), **rows}
    for prov, rows in {**{p: {} for p in _LEGACY_PROVIDER_PRICING}, **usage_rows()}.items()
}
```

Watch for circular imports: `provider_config_rows` imports `ProviderPricing` inside the function for that reason; if `provider_config.py` importing `pricing_mirror` still cycles, build the rows at the bottom of `provider_config.py` with a local import.

- [ ] **Step 4: Run the pricing tests**

Run: `python3 -m pytest tests/models/test_pricing_mirror.py tests/models/test_catalog.py tests/routing/test_pricing.py tests/routing/test_provider_config.py tests/routing/test_catalog_projection.py tests/billing -q 2>&1 | tail -6`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add aragora/models/pricing_mirror.py aragora/billing aragora/pdb/real_invoker.py aragora/services/metering_models.py aragora/routing/provider_config.py tests/models/test_pricing_mirror.py
git commit -m "feat(pricing): generate every per-model pricing table from the catalog"
```

---

### Task 7: Request-shape hardening (Anthropic and OpenAI)

**Files:**
- Modify: `aragora/models/compat.py:33-55`
- Modify: `aragora/agents/api_agents/anthropic.py:295-346,554-576`
- Modify: `aragora/agents/api_agents/openai_compatible.py:172-190`
- Test: `tests/agents/api_agents/test_request_shapes.py`

**Interfaces:**
- Consumes: `spec_or_none`, catalog flags from Task 1.
- Produces: `compat.rejects_sampling_params(model_id)` true when `spec.supports_sampling_params is False` (regex only as fallback for unknown ids); `compat.thinks_by_default(model_id) -> bool`; `compat.allows_forced_tool_choice(model_id) -> bool`; `compat.max_tokens_param(model_id) -> str`; `compat.reasoning_effort_default(model_id) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/api_agents/test_request_shapes.py
import pytest
from aragora.models import compat

def test_flags_come_from_catalog() -> None:
    assert compat.rejects_sampling_params("gpt-6-astra") is True
    assert compat.rejects_sampling_params("claude-fable-5-1") is True
    assert compat.rejects_sampling_params("gemini-3.8-flash") is False
    assert compat.rejects_sampling_params("claude-newfamily-9") is False  # unknown → conservative
    assert compat.thinks_by_default("claude-fable-5-1") is True
    assert compat.allows_forced_tool_choice("claude-fable-5-1") is False
    assert compat.max_tokens_param("gpt-6-astra") == "max_completion_tokens"
    assert compat.max_tokens_param("gemini-3.8-flash") == "max_tokens"
    assert compat.reasoning_effort_default("gpt-6-astra") == "high"

def test_anthropic_payload_for_fable_51() -> None:
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    agent = AnthropicAPIAgent(name="a", model="claude-fable-5-1", temperature=0.2, top_p=0.9)
    payload = agent._build_payload("hello", max_tokens=32000)  # use the agent's actual payload-builder name
    assert "temperature" not in payload and "top_p" not in payload
    assert "thinking" not in payload or payload["thinking"] == {"type": "adaptive"}
    assert payload["max_tokens"] == 32000
    assert payload.get("tool_choice", {"type": "auto"}).get("type") in ("auto", "none")

def test_openai_payload_for_astra() -> None:
    from aragora.agents.api_agents.openai import OpenAIAPIAgent
    agent = OpenAIAPIAgent(name="o", model="gpt-6-astra", temperature=0.3)
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert "max_completion_tokens" in payload and "max_tokens" not in payload
    assert "temperature" not in payload
    assert payload["reasoning_effort"] == "high"

def test_openai_payload_for_non_reasoning_model_unchanged() -> None:
    from aragora.agents.api_agents.openai import OpenAIAPIAgent
    agent = OpenAIAPIAgent(name="o", model="some-openai-compatible-model", temperature=0.3)
    payload = agent._build_payload([{"role": "user", "content": "hi"}])
    assert "max_tokens" in payload and payload["temperature"] == 0.3 and "reasoning_effort" not in payload
```

Before writing, open `anthropic.py` and confirm the payload builder's real method name and signature (around line 295); use that name in the test.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/agents/api_agents/test_request_shapes.py -q`
Expected: FAIL (`thinks_by_default` missing; Astra payload has `max_tokens`).

- [ ] **Step 3: Implement compat flags**

```python
# in aragora/models/compat.py
from aragora.models.catalog import spec_or_none

def rejects_sampling_params(model_id: str | None) -> bool:
    if not model_id:
        return False
    spec = spec_or_none(model_id)
    if spec is not None:
        return not spec.supports_sampling_params
    return bool(_MODERN_CLAUDE.search(str(model_id)))

def thinks_by_default(model_id: str | None) -> bool:
    spec = spec_or_none(model_id)
    return bool(spec and spec.thinking_default_on)

def allows_forced_tool_choice(model_id: str | None) -> bool:
    spec = spec_or_none(model_id)
    return True if spec is None else spec.forced_tool_choice_allowed

def max_tokens_param(model_id: str | None) -> str:
    spec = spec_or_none(model_id)
    return spec.max_tokens_param if spec else "max_tokens"

def reasoning_effort_default(model_id: str | None) -> str | None:
    spec = spec_or_none(model_id)
    return spec.reasoning_effort_default if spec else None
```

Add the new names to `__all__`.

- [ ] **Step 4: Anthropic builder**

In the payload builder (~line 299-346): if `thinks_by_default(self.model)`, do not emit `thinking` with `budget_tokens` even when `thinking_budget` is set (log once that adaptive thinking is on); never emit `tool_choice` of type `any`/`tool` when `not allows_forced_tool_choice(self.model)` (downgrade to `{"type": "auto"}` and prepend "Use the <tool> tool." to the last user message); when the model is `claude-fable-5-1` or `claude-opus-5` and `settings.anthropic_refusal_fallback` (new bool setting, default True, env `ARAGORA_ANTHROPIC_REFUSAL_FALLBACK`) is on, add `"fallbacks": "default"` to the payload and `anthropic-beta: server-side-fallback-2026-07-01` to the request headers; treat `stop_reason == "refusal"` as a structured failure (`AgentError` with `reason="refusal"`, category from `stop_details`), never an empty string. Apply the same in the streaming path (~554-576). Keep `strip_sampling_params` calls; they now read the catalog.

- [ ] **Step 5: OpenAI builder**

```python
# in openai_compatible.py _build_payload
from aragora.models.compat import max_tokens_param, reasoning_effort_default, rejects_sampling_params
payload = {"model": self.model, "messages": messages, max_tokens_param(self.model): self.max_tokens}
if stream:
    payload["stream"] = True
if not rejects_sampling_params(self.model):
    if getattr(self, "temperature", None) is not None: payload["temperature"] = self.temperature
    if getattr(self, "top_p", None) is not None: payload["top_p"] = self.top_p
    if getattr(self, "frequency_penalty", None) is not None: payload["frequency_penalty"] = self.frequency_penalty
effort = getattr(self, "reasoning_effort", None) or reasoning_effort_default(self.model)
if effort:
    payload["reasoning_effort"] = effort
```

Add `reasoning_effort: str | None = None` to the OpenAI agent constructor so the reviewer role can pass `xhigh`.

- [ ] **Step 6: Keyless smoke test through VibeProxy** (skipped automatically when the proxy is absent)

```python
# append to tests/agents/api_agents/test_request_shapes.py
import json, socket, urllib.request

def _proxy_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 8318), timeout=1).close(); return True
    except OSError:
        return False

@pytest.mark.skipif(not _proxy_up(), reason="VibeProxy not running on 127.0.0.1:8318")
@pytest.mark.parametrize("model,url,body", [
    ("gpt-6-astra", "http://127.0.0.1:8318/v1/chat/completions",
     {"model": "gpt-6-astra", "messages": [{"role": "user", "content": "Reply: ok"}], "max_completion_tokens": 16, "reasoning_effort": "low"}),
    ("claude-fable-5-1", "http://127.0.0.1:8318/v1/messages",
     {"model": "claude-fable-5-1", "max_tokens": 16, "messages": [{"role": "user", "content": "Reply: ok"}]}),
])
def test_live_shape_accepted_by_proxy(model: str, url: str, body: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer local", "x-api-key": "local", "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status == 200
```

- [ ] **Step 7: Run tests**

Run: `python3 -m pytest tests/agents/api_agents/test_request_shapes.py tests/agents/test_agent_anthropic.py -q 2>&1 | tail -5`
Expected: PASS (live tests PASS locally, SKIP in CI).

- [ ] **Step 8: Commit**

```bash
git add aragora/models/compat.py aragora/agents/api_agents/anthropic.py aragora/agents/api_agents/openai.py aragora/agents/api_agents/openai_compatible.py aragora/config/settings.py tests/agents/api_agents/test_request_shapes.py
git commit -m "feat(agents): drive request shapes from catalog flags; Fable 5.1 refusal fallback; Astra max_completion_tokens and effort"
```

---

### Task 8: Sweep script with `--check`

**Files:**
- Create: `scripts/refresh_model_literals.py`
- Create: `scripts/baselines/retired_model_literals_allowlist.txt`
- Test: `tests/scripts/test_refresh_model_literals.py`

**Interfaces:**
- Consumes: `UPGRADES`, `RETIRED_PATTERN`, `CATALOG` (to map canonical → direct or OpenRouter spelling: a literal that was an OpenRouter slug is rewritten to the new OpenRouter slug; a bare id to the new direct id).
- Produces: CLI `python3 scripts/refresh_model_literals.py [--paths aragora scripts sdk docs docs-site tests] [--check] [--write] [--allowlist scripts/baselines/retired_model_literals_allowlist.txt]`; exit 0 clean, 1 when `--check` finds retired literals outside the allowlist, 2 on usage error.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_refresh_model_literals.py
import subprocess, sys
from pathlib import Path

SCRIPT = Path("scripts/refresh_model_literals.py")

def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

def test_rewrites_bare_and_openrouter_spellings(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text('A = "gpt-4o"\nB = "anthropic/claude-fable-5"\nC = "claude-fable-5-1"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'A = "gpt-6-astra"\nB = "anthropic/claude-fable-5.1"\nC = "claude-fable-5-1"\n'

def test_check_fails_on_retired_literal_and_respects_allowlist(tmp_path: Path) -> None:
    f = tmp_path / "old.md"; f.write_text("we shipped gpt-4 in 2024\n")
    allow = tmp_path / "allow.txt"; allow.write_text("")
    assert _run("--paths", str(tmp_path), "--check", "--allowlist", str(allow)).returncode == 1
    allow.write_text(f"{f}\n")
    assert _run("--paths", str(tmp_path), "--check", "--allowlist", str(allow)).returncode == 0

def test_does_not_touch_lockfiles_or_git(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text('{"x":"gpt-4"}')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0 and (tmp_path / "package-lock.json").read_text() == '{"x":"gpt-4"}'
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/scripts/test_refresh_model_literals.py -q`
Expected: FAIL (script missing → returncode 2 from Python "No such file").

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Rewrite retired model-ID literals to their current ids, or check that none remain."""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
from aragora.models.catalog import CATALOG
from aragora.models.upgrade_map import RETIRED_PATTERN, UPGRADES

SKIP_DIRS = {".git", "node_modules", ".worktrees", "__pycache__", ".venv", "dist", "build"}
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".pdf", ".ico", ".woff", ".woff2", ".pyc"}
SKIP_NAMES = {"package-lock.json", "uv.lock", "yarn.lock", "pnpm-lock.yaml", "catalog_snapshot.json", "upgrade_map.py"}
BOUNDARY = re.compile(r"(?<![A-Za-z0-9._/-])(%s)(?![A-Za-z0-9._-])" % RETIRED_PATTERN.pattern)

def replacement(old: str) -> str:
    spec = CATALOG[UPGRADES[old]]
    return spec.openrouter_id if "/" in old else spec.direct_id

def iter_files(paths: list[str]):
    for p in paths:
        root = Path(p)
        files = [root] if root.is_file() else root.rglob("*")
        for f in files:
            if not f.is_file() or f.name in SKIP_NAMES or f.suffix in SKIP_SUFFIXES: continue
            if any(part in SKIP_DIRS for part in f.parts): continue
            yield f

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", nargs="+", default=["aragora", "scripts", "sdk", "docs", "docs-site", "tests", "README.md"])
    ap.add_argument("--write", action="store_true"); ap.add_argument("--check", action="store_true")
    ap.add_argument("--allowlist", default="scripts/baselines/retired_model_literals_allowlist.txt")
    a = ap.parse_args(argv)
    if a.write == a.check:
        print("choose exactly one of --write / --check", file=sys.stderr); return 2
    allow = set()
    ap_path = Path(a.allowlist)
    if ap_path.exists():
        allow = {ln.strip() for ln in ap_path.read_text().splitlines() if ln.strip() and not ln.startswith("#")}
    offenders: list[tuple[str, int, str]] = []
    changed = 0
    for f in iter_files(a.paths):
        try: text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        if str(f) in allow: continue
        if not BOUNDARY.search(text): continue
        if a.check:
            for i, line in enumerate(text.splitlines(), 1):
                m = BOUNDARY.search(line)
                if m: offenders.append((str(f), i, m.group(1)))
        else:
            new = BOUNDARY.sub(lambda m: replacement(m.group(1)), text)
            if new != text: f.write_text(new, encoding="utf-8"); changed += 1
    if a.check:
        for path, ln, lit in offenders: print(f"{path}:{ln}: retired model id {lit}")
        print(f"{len(offenders)} retired literal(s) outside allowlist"); return 1 if offenders else 0
    print(f"rewrote {changed} file(s)"); return 0

if __name__ == "__main__":
    sys.exit(main())
```

Create `scripts/baselines/retired_model_literals_allowlist.txt` with a header comment and, initially, the historical records that must keep old IDs verbatim: `CHANGELOG.md`, every file under `docs/releases/`, `docs/benchmarks/`, `docs/artifacts/`, `docs/atlas/`, `docs/archive/`, and `docs/status/generated/` (one path per line; list them with `git ls-files docs/releases docs/benchmarks docs/artifacts docs/atlas docs/archive docs/status/generated`).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/scripts/test_refresh_model_literals.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_model_literals.py scripts/baselines/retired_model_literals_allowlist.txt tests/scripts/test_refresh_model_literals.py
git commit -m "feat(scripts): add retired-model-literal sweep with --check and historical allowlist"
```

---

### Task 9: Docs, changelog, and PR 1

**Files:**
- Modify: `docs/architecture/MODEL_CATALOG.md`, `CHANGELOG.md` (Unreleased)

- [ ] **Step 1: Update `docs/architecture/MODEL_CATALOG.md`** with the target table from the spec, the capability flags, the "bump the catalog, not the pins" rule, and the sweep command. Add a CHANGELOG `Unreleased` bullet per provider default change.

- [ ] **Step 2: Gate checks**

Run: `ruff check aragora/models aragora/config/model_pins.py aragora/agents scripts/refresh_model_literals.py && ruff format --check aragora/models aragora/config/model_pins.py scripts/refresh_model_literals.py && make ci-required 2>&1 | tail -15`
Expected: clean; the five required checks green locally.

- [ ] **Step 3: Commit and open the draft PR**

```bash
git add docs/architecture/MODEL_CATALOG.md CHANGELOG.md
git commit -m "docs(models): document the frontier refresh and the catalog-first rule"
git push -u origin feat/frontier-model-refresh
gh pr create --draft --title "feat(models): frontier model refresh — Fable 5.1, GPT-6 Astra, catalog-first pins and pricing [Tier 2]" --body-file docs/superpowers/plans/pr1-body.md
```

Write `docs/superpowers/plans/pr1-body.md` locally (do not commit it) with: Summary; exit metric served (none directly — enabling change for receipts pricing accuracy); test commands from Tasks 1-8; "Reviewed design tradeoffs" (catalog-first vs literal sweep; keeping retired rows priced for old receipts; Astra `soak_until` retained with reviewer override deferred to PR 2; sampling params stripped by flag, regex fallback kept for unknown ids); links to the spec and this plan.

---

## PR 2 — merge gate (Tier 4)

### Task 10: Reviewer family map, Codex harness default, identity recognition

**Files:**
- Modify: `aragora/swarm/quorum_evidence.py:568-569,2354-2375`
- Modify: `aragora/cli/commands/review_queue.py:4619+` (`_resolve_model_review_identity`), `aragora/debate/execution_safety.py:24+` (`_MODEL_FAMILY_PATTERNS`), `aragora/swarm/quorum_evidence.py:421` (`canonical_family`)
- Test: `tests/governance/test_model_lineage_disclosure_recognizer.py`, `tests/governance/test_tiered_merge_gate_quorum_policy.py`, `tests/cli/commands/test_review_queue.py`, `tests/swarm/test_quorum_evidence.py`

**Interfaces:**
- Consumes: `CATALOG`, pins.
- Produces: `_OPENROUTER_REVIEWER_MODELS` derived from the catalog per family; `_CODEX_DEFAULT_MODELS = (GPT6_ASTRA_DIRECT, "gpt-5.6-sol")`.

- [ ] **Step 1: Write the failing tests** (append to the governance recognizer test)

```python
import pytest
from aragora.swarm.quorum_evidence import _CODEX_DEFAULT_MODELS, _OPENROUTER_REVIEWER_MODELS, canonical_family
from aragora.cli.commands.review_queue import _resolve_model_review_identity

@pytest.mark.parametrize("text,family", [
    ("Model family: openai\nModel: gpt-6-astra", "openai"),
    ("Reviewer: claude (claude-fable-5-1)", "claude"),
    ("model=x-ai/grok-4.6", "grok"),
    ("model=meta/muse-spark-1.3", "meta"),
])
def test_identity_resolver_recognises_frontier_ids(text: str, family: str) -> None:
    assert _resolve_model_review_identity(text).family == family

def test_reviewer_map_is_frontier() -> None:
    assert _OPENROUTER_REVIEWER_MODELS["claude"] == "anthropic/claude-fable-5.1"
    assert _OPENROUTER_REVIEWER_MODELS["openai"] == "openai/gpt-6-astra"
    assert _OPENROUTER_REVIEWER_MODELS["grok"] == "x-ai/grok-4.6"
    assert _OPENROUTER_REVIEWER_MODELS["deepseek"] == "deepseek/deepseek-v4-pro-0813"
    assert _OPENROUTER_REVIEWER_MODELS["kimi"] == "moonshotai/kimi-k3"
    assert _OPENROUTER_REVIEWER_MODELS["meta"] == "meta/muse-spark-1.3"
    assert _CODEX_DEFAULT_MODELS[0] == "gpt-6-astra"
    for fam in ("claude", "openai", "grok", "gemini", "deepseek", "qwen", "kimi", "meta"):
        assert canonical_family(_OPENROUTER_REVIEWER_MODELS[fam]) == fam
```

Confirm the `ModelReviewIdentity` attribute name for the family (read the dataclass at `review_queue.py` near line 4600) and adjust `.family` if it differs.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/governance/test_model_lineage_disclosure_recognizer.py -q -k "frontier or reviewer_map"`
Expected: FAIL on `openai/gpt-5.5`.

- [ ] **Step 3: Implement**

```python
# quorum_evidence.py
from aragora.config.model_pins import GPT6_ASTRA_DIRECT
from aragora.models.catalog import CATALOG

_CODEX_DEFAULT_MODELS = (GPT6_ASTRA_DIRECT, "gpt-5.6-sol")
_CODEX_DEFAULT_MODEL = _CODEX_DEFAULT_MODELS[0]

# Founder decision 2026-09-04 (chat, recorded on #9069): GPT-6 Astra drives reviewer evidence from
# day two, overriding the 14-day soak rule once. Soak metadata on the catalog row is unchanged.
_OPENROUTER_REVIEWER_MODELS: dict[str, str] = {
    "claude": CATALOG["claude-fable-5-1"].openrouter_id,
    "openai": CATALOG["gpt-6-astra"].openrouter_id,
    "grok": CATALOG["grok-4.6"].openrouter_id,
    "gemini": CATALOG["gemini-3.1-pro-preview"].openrouter_id,
    "deepseek": CATALOG["deepseek-v4-pro-0813"].openrouter_id,
    "qwen": CATALOG["qwen3.8-2.4t-a95b"].openrouter_id,
    "kimi": CATALOG["kimi-k3"].openrouter_id,
    "meta": CATALOG["muse-spark-1.3"].openrouter_id,
    "glm": CATALOG["glm-5.2"].openrouter_id,
    "minimax": CATALOG["minimax-m3"].openrouter_id,
    "tencent": "tencent/hy3",
    "bytedance": "bytedance-seed/seed-2.0-lite",
}
```

If the reviewer selection code refuses models with `is_under_soak()` true, add a module constant `_SOAK_OVERRIDES: frozenset[str] = frozenset({"gpt-6-astra"})` consulted at that check, with the same founder-decision comment. Extend `_MODEL_FAMILY_PATTERNS` and `canonical_family` so `gpt-6*` → openai, `claude-fable*` → claude, `grok-4.6` → grok, `muse-spark*` → meta. Add `"meta"` to the family enumerations where `deepseek`/`qwen`/`kimi` are listed (not to `WESTERN_FRONTIER_FAMILIES`).

- [ ] **Step 4: Run the gate tests**

Run: `python3 -m pytest tests/governance tests/swarm/test_quorum_evidence.py tests/cli/commands/test_review_queue.py -q -x 2>&1 | tail -8`
Expected: PASS

- [ ] **Step 5: Commit, push, open draft PR 2 (stacked on PR 1's branch), and record the override**

```bash
git checkout -b feat/frontier-model-refresh-gate
git add aragora/swarm/quorum_evidence.py aragora/cli/commands/review_queue.py aragora/debate/execution_safety.py tests/governance tests/swarm tests/cli/commands
git commit -m "feat(governance): merge-gate reviewers move to Fable 5.1 and GPT-6 Astra; recognise frontier ids [Tier 4]"
git push -u origin feat/frontier-model-refresh-gate
gh pr create --draft --base feat/frontier-model-refresh --title "feat(governance): merge-gate reviewers on Fable 5.1 and GPT-6 Astra [Tier 4]" --body-file docs/superpowers/plans/pr2-body.md
gh issue comment 9069 --body "Founder decision 2026-09-04: GPT-6 Astra (released 2026-09-03) drives merge-gate reviewer evidence immediately, a one-time override of the 14-day availability rule. Implemented in the PR linked above; the catalog row keeps soak_until=2026-09-17 for every other consumer."
```

PR 2 body must include the "Reviewed design tradeoffs" section and the sentence "Overrides the 14-day reviewer rule for gpt-6-astra by founder decision 2026-09-04".

---

## PR 3 — generated sweep (Tier 1)

### Task 11: Run the sweep, regenerate snapshots, sequence after #9983

- [ ] **Step 1: Pre-flight**

Run: `gh pr view 9983 --json state,mergedAt --jq '.state'`
Expected: `MERGED` (the old mission's SDK paydown touches `sdk/`); if still open, wait and do Task 12 first.

- [ ] **Step 2: Sweep on a branch stacked on PR 1**

```bash
git checkout -b feat/frontier-model-refresh-sweep feat/frontier-model-refresh
python3 scripts/refresh_model_literals.py --write --paths aragora scripts sdk docs docs-site tests README.md
git diff --stat | tail -3
```

- [ ] **Step 3: Regenerate generated artefacts touched by the sweep** (never hand-edit): `python3 scripts/regenerate_metrics.py`, `node docs-site/scripts/sync-docs.js`, any `*_snapshot.json` whose generator script is named in its header comment.

- [ ] **Step 4: Run the tests the sweep touched**

Run: `git diff --name-only feat/frontier-model-refresh -- tests | sed 's#^#./#' | xargs python3 -m pytest -q -p no:cacheprovider 2>&1 | tail -15`
Expected: PASS. A test that fails because it asserted behavior tied to a retired ID gets its expectation updated to the new ID; a test that fails because a fixture is a frozen snapshot gets regenerated by its generator. Record each judgment call in the PR body.

- [ ] **Step 5: Check mode is clean and commit**

```bash
python3 scripts/refresh_model_literals.py --check
git add -A && git commit -m "chore(models): generated sweep of retired model ids to current frontier ids"
git push -u origin feat/frontier-model-refresh-sweep
gh pr create --draft --base feat/frontier-model-refresh --title "chore(models): generated sweep of retired model literals [Tier 1]" --body-file docs/superpowers/plans/pr3-body.md
```

---

## PR 4 — CI check (Tier 4, tiny)

### Task 12: `--check` as a job inside `metrics-drift.yml`

- [ ] **Step 1:** In `.github/workflows/metrics-drift.yml`, add a job `retired-model-literals` mirroring the existing `check` job's checkout and Python setup, running `pip install -e . --no-deps` (only if the script's imports need it; otherwise `PYTHONPATH=.`) then `python3 scripts/refresh_model_literals.py --check`. Non-required. No new workflow file.
- [ ] **Step 2:** `gh workflow run metrics-drift.yml --ref feat/frontier-model-refresh-ci` to dispatch-verify (see memory: dispatch on the branch to test workflow changes).
- [ ] **Step 3:** Draft PR 4 stacked on PR 3, Tier 4 body with the override-free tradeoffs section.

---

## Outside the repo (no PR)

### Task 13: Verify the local tool chain

- [ ] Factory `~/.factory/config.json` already lists `VP: Fable 5.1` and `VP: GPT-6 Astra` (done 2026-09-04).
- [ ] Codex `~/.codex/config.toml` `model = "gpt-6-astra"` (verified 2026-09-04).
- [ ] Claude reviewer profiles: run `CLAUDE_CONFIG_DIR=$HOME/.aragora-claude/max-01/.claude claude -p --model fable --output-format json "Reply with the exact model id you are." | head -c 400` and confirm the response names `claude-fable-5-1`; if it names Fable 5, set `"model": "fable"` in each profile's `settings.json` (create the file if absent) for profiles max-01, 02, 04, 05, 06, 07, 09, 11.

---

## Self-review against the spec

- Spec §Architecture 1 (catalog load-bearing) → Tasks 1, 3, 4, 5, 6. §2 (upgrade map, two consumers) → Tasks 2, 8, 11. §3 (request-shape) → Task 7. §4 (merge gate) → Task 10. §Testing → Tasks 1-8, 10, 11. §Delivery → Tasks 9, 10, 11, 12. §Outside repo → Task 13.
- Placeholders: the `glm-5.2` price is read from the live snapshot in Task 1 Step 4 and must be filled before the Task 1 commit; no other `<...>` remains.
- Names used consistently: `spec_or_none`, `frontier_for`, `FRONTIER`, `resolve_model_id`, `UPGRADES`, `RETIRED_PATTERN`, `FABLE_51_DIRECT`, `GPT6_ASTRA_DIRECT`, `GEMINI_31_PRO_DIRECT`, `GEMINI_38_FLASH_DIRECT`, `GROK_46_DIRECT`, `MISTRAL_MEDIUM_DIRECT`, `usage_rows`, `pdb_rows`, `debate_cost_rows`, `provider_config_rows`, `thinks_by_default`, `allows_forced_tool_choice`, `max_tokens_param`, `reasoning_effort_default`.
