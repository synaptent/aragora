"""Generate the legacy pricing-table shapes from the catalog so a price
lives in one place.

Phase 1 (``aragora/models/catalog.py``) made ``CATALOG`` the canonical
economics record but deliberately left the five runtime pricing tables
(``aragora.billing.usage.PROVIDER_PRICING``, ``aragora.pdb.real_invoker
._PRICE_PER_MTOK``, ``aragora.billing.debate_costs.DEFAULT_PROVIDER_RATES``,
``aragora.services.metering_models.MODEL_PRICING`` and
``aragora.routing.provider_config.PROVIDER_PRICING``) hand-maintained, each
enforced only for the ``ENFORCED_MODELS`` subset. This module is phase 2:
it derives every one of those table shapes from ``CATALOG`` so a price
change only ever needs to happen in one place.

Each consumer module keeps its hand-written dict under a ``_LEGACY_*`` name
(receipts and env overrides pinned to an old spelling must keep resolving)
and publishes ``{**_LEGACY_*, **generated}`` — the generated row wins on a
key collision, since the catalog is the more recently verified source.

Retired catalog rows are still emitted (see ``_active`` below): an old
receipt referencing a retired model id must still price, so retirement
only affects *adoption* surfaces (routing enumeration, frontier picks),
never pricing lookup.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from aragora.models.catalog import CATALOG, ModelSpec

if TYPE_CHECKING:
    from datetime import date

    from aragora.routing.provider_config import ProviderPricing

__all__ = [
    "context_window_rows",
    "dec",
    "debate_cost_rows",
    "input_cost_per_1k_rows",
    "metering_rows",
    "pdb_rows",
    "per_1k_rows",
    "per_mtok_rows",
    "provider_config_rows",
    "usage_rows",
]


def dec(x: float) -> Decimal:
    """Render a catalog float as the ``Decimal`` shape the legacy tables
    use: two decimal places for round dollar-and-cents rates (``10.0`` ->
    ``Decimal("10.00")``), four for rates with finer-grained cents (e.g.
    the qwen3.7-max reprice ``1.475``, the deepseek-v4-pro-0813 live
    capture ``1.1207``).

    Public because two consumers outside this module (``billing.usage``'s
    catalog price path and its test) must render a catalog rate in exactly
    the same shape the generated tables use, and importing an underscored
    name across module boundaries hides that coupling rather than removing
    it."""
    return Decimal(f"{x:.4f}").normalize() if x != round(x, 2) else Decimal(f"{x:.2f}")


# Back-compat alias for the original private spelling.
_dec = dec


def _active() -> list[ModelSpec]:
    """Every catalog row, retired included.

    Retired rows stay priced: old receipts must still resolve to a real
    rate, even though retired models are no longer adopted by routing/
    frontier-selection surfaces (those checks live on ``ModelSpec.retired``
    itself, not here)."""
    return [s for s in CATALOG.values()]


def _current() -> list[ModelSpec]:
    """Only the rows that are still ACTIVE.

    The five phase-2 tables above deliberately price retired rows too (an
    old receipt must still resolve). The tables added in the 2026-09-05
    wave-3 pass are different: they are *forward*-looking estimate tables
    (workflow resource budgeting, document cost previews, the agent
    leaderboard's per-1K estimate) whose hand-written rows are being KEPT
    as-is for historical spellings. Emitting retired rows here would only
    restate a historical price the table already carries by hand, so these
    generators add the active frontier and nothing else -- exactly the
    "keep the historical rows, add the current ones" shape the
    frontier-model-refresh wave-3 rulings call for."""
    return [s for s in CATALOG.values() if not s.retired]


_OPENROUTER = "openrouter"

# agent_type label -> catalog family, for every label a registered API/CLI
# agent class bills under (``self.agent_type`` in
# aragora/agents/api_agents/*.py) that names NEITHER the catalog
# ``provider`` NOR the catalog ``family`` of the model it actually calls.
# Enumerated by reading every ``self.agent_type = "..."`` assignment in
# aragora/agents/api_agents/*.py and aragora/agents/cli_agents.py (CLI
# agent classes never set it -- they inherit the base ``Agent.agent_type``
# default of ``"unknown"``, so their pricing depends entirely on
# ``calculate_token_cost``'s catalog fallback, not this table) against each
# class's default model's catalog row:
#   gemini          -> google     (GeminiAgent; provider/family "google")
#   grok            -> xai        (GrokAgent; provider/family "xai")
#   kimi            -> moonshot   (KimiK3Agent, KimiLegacyAgent)
#   kimi-thinking   -> moonshot   (KimiThinkingAgent)
#   deepseek-r1     -> deepseek   (DeepSeekReasonerAgent; family "deepseek")
#   deepseek-v3     -> deepseek   (DeepSeekV3Agent; family "deepseek")
#   llama           -> meta       (LlamaAgent; family "meta", Muse Spark 1.3)
#   llama4-maverick -> meta       (Llama4MaverickAgent)
#   llama4-scout    -> meta       (Llama4ScoutAgent)
#   qwen-max        -> qwen       (QwenMaxAgent; family "qwen")
# A label already equal to its model's provider or family (anthropic,
# openai, mistral, openrouter, deepseek, qwen, ...) needs no entry -- rules
# 1-3 below already reach it. A label whose model has NO catalog row at all
# (codestral, sonar, command-r, jamba, fusion, the generic framework
# adapters) has nothing to alias TO and is out of this table's scope --
# ``calculate_token_cost``'s catalog fallback cannot invent a price either.
_LABEL_ALIASES: dict[str, str] = {
    "gemini": "google",
    "grok": "xai",
    "kimi": "moonshot",
    "kimi-thinking": "moonshot",
    "deepseek-r1": "deepseek",
    "deepseek-v3": "deepseek",
    "llama": "meta",
    "llama4-maverick": "meta",
    "llama4-scout": "meta",
    "qwen-max": "qwen",
}


def _bucketed(spec: ModelSpec) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``(bucket, spellings)`` pairs one catalog row must be emitted under.

    Bucketing a row ONLY by ``spec.provider`` (what the first cut of this
    module did) leaves two holes that the 2026-09-05 merge-gate review
    caught empirically on #9989, both of which silently bill the caller at
    the ``openrouter`` bucket's ``$2/$8`` default instead of the real rate:

    1. A native row's OpenRouter spelling never reached the ``openrouter``
       bucket. ``OpenRouterAgent.agent_type`` is ``"openrouter"``, and that
       is the ``provider`` string the monthly budget guard
       (``api_agents/base.py``) and ``debate/orchestrator_runner.py`` pass
       to ``calculate_token_cost`` — so every Claude/OpenAI/Gemini/Grok/
       Mistral call routed through OpenRouter (which the frontier refresh
       makes the default fallback target for all of them) was billed at
       the default. ``anthropic/claude-fable-5.1`` costs 6x the default.
    2. An ``openrouter``-provider row never reached its FAMILY bucket.
       ``server/handlers/debates/cost_estimation.py`` asks for the row's
       family bucket whenever the family names a real pricing bucket
       (``deepseek``), so the cataloged ``deepseek-v4-pro-0813`` rate was
       unreachable there.

    So a row is emitted under, in this order:

    1. its OWN provider bucket, every spelling (unchanged behaviour);
    2. the ``openrouter`` bucket, every SLASH-BEARING spelling — the
       ``openrouter_id`` plus any OpenRouter-shaped alias (e.g.
       ``anthropic/claude-opus-4-8``, ``google/gemini-3.1-pro``). A bare
       spelling is deliberately NOT emitted here: OpenRouter is addressed
       by slug, and a bare id under this bucket would claim a rate for a
       spelling no OpenRouter call ever sends;
    3. and its ``family`` bucket, every spelling. Hole 2 above is the case
       that needs this (``deepseek-v4-pro-0813``'s family bucket is the one
       ``cost_estimation._pricing_provider`` derives for it), but the rule
       is deliberately NOT restricted to openrouter-provider rows: emitting
       one row under a family name makes that name a live pricing bucket,
       and ``_pricing_provider`` then routes EVERY same-family row there.
       Restricting the rule would therefore have the ``qwen3.8-2.4t-a95b``
       row (provider ``openrouter``) create a ``qwen`` bucket that silently
       shadows its ``alibaba``-provider sibling ``qwen3.7-max`` down to the
       default rate — trading the reviewer's bug for a narrower copy of it.
       For the common case (``family == provider``) this rule is a no-op.
    4. every row whose family has a registered ``_LABEL_ALIASES`` entry,
       additionally under that alias label's bucket. Rule 3 only reaches a
       label that matches the catalog ``family`` string exactly, but
       several agent classes bill under a DIFFERENT runtime
       ``self.agent_type`` label than either their model's ``provider`` or
       ``family`` -- ``GeminiAgent`` is ``"gemini"`` for a ``google``-family
       row, ``GrokAgent`` is ``"grok"`` for an ``xai``-family row, the Kimi
       agent classes are ``"kimi"``/``"kimi-thinking"`` for ``moonshot``,
       and several OpenRouter convenience aliases (``"deepseek-r1"``,
       ``"deepseek-v3"``, ``"llama"``, ``"llama4-maverick"``,
       ``"llama4-scout"``, ``"qwen-max"``) name a specific model rather than
       its family. Every one of these previously missed every bucket rules
       1-3 emit and silently fell back to the ``openrouter`` default (the
       2026-09-05 gate-fix wave found this empirically for kimi, then a
       read-only recheck at the same head found it again for gemini/grok --
       see ``_LABEL_ALIASES``' own docstring for the full enumeration
       method). This rule is table-driven rather than a per-label hardcode
       so the next mismatched label is one dict entry, not a new branch.

    Rates are identical across buckets — this is one row's price made
    reachable under every provider label a caller legitimately uses for
    it, never a per-bucket price.
    """
    ids = spec.all_ids()
    buckets: list[tuple[str, tuple[str, ...]]] = [(spec.provider, ids)]
    if spec.provider != _OPENROUTER:
        slugs = tuple(i for i in ids if "/" in i)
        if slugs:
            buckets.append((_OPENROUTER, slugs))
    if spec.family and spec.family != spec.provider:
        buckets.append((spec.family, ids))
    for label, family in _LABEL_ALIASES.items():
        if spec.family == family:
            buckets.append((label, ids))
    return tuple(buckets)


def usage_rows() -> dict[str, dict[str, Decimal]]:
    """Shape of ``aragora.billing.usage.PROVIDER_PRICING``: provider ->
    {id: input_rate, f"{id}-output": output_rate}, plus
    f"{id}-cache-read" for a row that documents a cache-read rate, one
    entry per spelling in ``ModelSpec.all_ids()`` so canonical/direct/
    openrouter/alias ids all resolve, under every bucket ``_bucketed``
    emits the row for.

    The emitted rates are FLAT (``input_per_mtok``/``output_per_mtok``) and
    stay flat: the two-key-per-spelling shape this table must produce cannot
    express a documented long-context tier, which depends on the request's
    prompt length rather than on the model alone. Tier-aware pricing is
    therefore the catalog's job -- ``ModelSpec.rates_for(prompt_tokens)``,
    which ``billing.usage.calculate_token_cost`` consults BEFORE these
    buckets (finding O-P2b on #9989) -- and these rows remain the correct
    answer for the spellings the catalog cannot resolve at all.

    The ``-cache-read`` column exists for the same reason the ``-output``
    one does: ``calculate_token_cost`` is the only consumer of these
    tables that bills a cached prompt token at all, and it charged a
    hard-coded 10% of the input rate while the catalog carried the
    provider's DOCUMENTED rate (Fable 5.1: $0.25/MTok against a $10.00
    input rate, so cached Fable billed at $1.00 -- finding O-P2a on
    #9989). Only rows with ``cache_read_per_mtok`` set emit the column, so
    a spelling without a documented rate keeps the heuristic rather than
    gaining an invented price."""
    out: dict[str, dict[str, Decimal]] = {}
    for s in _active():
        for bucket, spellings in _bucketed(s):
            prov = out.setdefault(bucket, {})
            for spelling in spellings:
                prov[spelling] = _dec(s.input_per_mtok)
                prov[f"{spelling}-output"] = _dec(s.output_per_mtok)
                if s.cache_read_per_mtok is not None:
                    prov[f"{spelling}-cache-read"] = _dec(s.cache_read_per_mtok)
    return out


def pdb_rows() -> dict[str, tuple[float, float]]:
    """Shape of ``aragora.pdb.real_invoker._PRICE_PER_MTOK``: spelling ->
    (input, output) rate, flat across providers."""
    return {sp: (s.input_per_mtok, s.output_per_mtok) for s in _active() for sp in s.all_ids()}


def debate_cost_rows() -> dict[str, dict[str, tuple[Decimal, Decimal]]]:
    """Shape of ``aragora.billing.debate_costs.DEFAULT_PROVIDER_RATES``:
    provider -> {spelling: (input, output)}, under every bucket
    ``_bucketed`` emits the row for."""
    out: dict[str, dict[str, tuple[Decimal, Decimal]]] = {}
    for s in _active():
        for bucket, spellings in _bucketed(s):
            prov = out.setdefault(bucket, {})
            for sp in spellings:
                prov[sp] = (_dec(s.input_per_mtok), _dec(s.output_per_mtok))
    return out


def metering_rows() -> dict[str, dict[str, Decimal]]:
    """Shape of ``aragora.services.metering_models.MODEL_PRICING``: same
    provider -> {id: input, f"{id}-output": output} shape as
    ``usage_rows()`` (verified against the hand-written dict before writing
    this — the two tables are documented as aligned), including its
    ``-cache-read`` column. The tenant-billing path hands ``MODEL_PRICING``
    straight to ``calculate_token_cost`` as ``extra_prices``, which is the
    consumer that reads that column, so keeping the two tables identical
    keeps one price per spelling rather than splitting the shape."""
    return usage_rows()


def provider_config_rows(
    today: "date | None" = None,
    *,
    catalog: "dict[str, ModelSpec] | None" = None,
) -> "dict[str, ProviderPricing]":
    """Shape of ``aragora.routing.provider_config.PROVIDER_PRICING``'s
    catalog projection: CANONICAL id only (never alias/direct/openrouter
    spellings) so enumeration consumers never see one model occupy several
    candidate slots, and never a RETIRED row. This is the single generator
    ``aragora.routing.provider_config._catalog_projection`` calls; alias
    spellings still price via the ``by_any_id`` fallback in
    ``get_estimated_cost``, unaffected by this function.

    The filter is retirement, not soak (frontier-model-refresh final review
    #7). It used to be the other way round, which inverted the intended
    candidate set: the routing roster offered `gpt-5.5` and `grok-4.5`
    (retired, dead on the wire) while withholding `gpt-6-astra`,
    `gemini-3.8-flash` and `muse-spark-1.3` (the current defaults, merely
    soaking). Soak gating still applies to routing SELECTION, where it
    belongs, via ``provider_router._is_under_soak``; keeping it here also
    made a module-level constant calendar-dependent -- the table would
    silently gain rows on 2026-09-16/17 -- which is a latent flake for any
    membership or count assertion.

    ``today`` is retained for call-site compatibility and is unused.

    ``catalog`` defaults to ``aragora.models.catalog.CATALOG`` but accepts
    an override so ``provider_config._catalog_projection`` can pass its own
    module-level ``CATALOG`` name through unchanged -- tests monkeypatch
    that module attribute directly to inject synthetic rows, and this
    function must observe the patched value rather than re-importing the
    real catalog itself.

    ``ProviderPricing`` is imported inside the function (not at module
    scope) because ``provider_config.py`` imports this module: a top-level
    import here would cycle.
    """
    from aragora.routing.provider_config import ProviderPricing

    rows = CATALOG if catalog is None else catalog
    return {
        s.canonical_id: ProviderPricing(
            provider_name=s.provider,
            model_name=s.direct_id,
            input_cost_per_1k=s.input_per_mtok / 1000.0,
            output_cost_per_1k=s.output_per_mtok / 1000.0,
            context_window=s.context_window,
        )
        for s in rows.values()
        if not s.retired
    }


def per_1k_rows() -> dict[str, dict[str, float]]:
    """Shape of the workflow resource tables' ``MODEL_PRICING``
    (``aragora.workflow.resource_tracker`` and
    ``aragora.workflow.engine_v2``): spelling -> ``{"input": …, "output": …}``
    in USD per 1K tokens, one entry per spelling in ``ModelSpec.all_ids()``.

    Those tables budget a workflow run in per-1K units, so the catalog's
    per-MTok rates are divided by 1000 here rather than at each call site."""
    return {
        spelling: {
            "input": s.input_per_mtok / 1000.0,
            "output": s.output_per_mtok / 1000.0,
        }
        for s in _current()
        for spelling in s.all_ids()
    }


def per_mtok_rows() -> dict[str, dict[str, float]]:
    """Shape of ``aragora.documents.chunking.context_manager``'s ``PRICING``:
    spelling -> ``{"input": …, "output": …}`` in USD per 1M tokens, i.e. the
    catalog's own units, one entry per spelling in ``ModelSpec.all_ids()``."""
    return {
        spelling: {"input": s.input_per_mtok, "output": s.output_per_mtok}
        for s in _current()
        for spelling in s.all_ids()
    }


def input_cost_per_1k_rows() -> dict[str, float]:
    """Shape of
    ``aragora.server.handlers.agents.recommendations._AGENT_COST_ESTIMATES``:
    spelling -> INPUT rate in USD per 1K tokens.

    That endpoint publishes a single ``estimated_cost_per_1k_tokens`` number
    per agent, documented as the input rate; the output rate has no slot in
    the response shape."""
    return {spelling: s.input_per_mtok / 1000.0 for s in _current() for spelling in s.all_ids()}


def context_window_rows() -> dict[str, int]:
    """Shape of ``aragora.documents.models.MODEL_TOKEN_LIMITS``: spelling ->
    ``ModelSpec.context_window``, one entry per spelling in
    ``ModelSpec.all_ids()``, ACTIVE rows only.

    Not a price, but the same projection problem and the same source row:
    ``provider_config_rows`` above already emits ``context_window`` for the
    routing table, and a second module for one more field of the same
    dataclass would just split the catalog's projection layer in two. The
    consumer keys on the model spelling and falls back to a per-table
    default, exactly like the pricing tables."""
    return {spelling: s.context_window for s in _current() for spelling in s.all_ids()}
