"""Tests for :mod:`aragora.models.pricing_mirror`.

Verifies the generated table shapes cover every catalog spelling with the
exact catalog rate, and that the legacy tables each module publishes
(``PROVIDER_PRICING`` / ``_PRICE_PER_MTOK`` / ``DEFAULT_PROVIDER_RATES`` /
``MODEL_PRICING`` / routing ``PROVIDER_PRICING``) contain the mirrored
rows -- the catalog is the single source of truth and the generated row
wins on a key collision with the hand-written legacy dict.
"""

from __future__ import annotations

from decimal import Decimal

from aragora.models import pricing_mirror as pm
from aragora.models.catalog import CATALOG


def test_usage_rows_cover_every_active_row_with_exact_prices() -> None:
    rows = pm.usage_rows()
    spec = CATALOG["gpt-6-astra"]
    assert rows["openai"]["gpt-6-astra"] == Decimal("10.00")
    assert rows["openai"]["gpt-6-astra-output"] == Decimal("50.00")
    for s in CATALOG.values():
        if s.retired:
            continue
        assert rows[s.provider][s.canonical_id] == Decimal(str(s.input_per_mtok))


def test_usage_rows_include_retired_rows_too() -> None:
    """Old receipts referencing a retired model id must still resolve."""
    rows = pm.usage_rows()
    for s in CATALOG.values():
        if not s.retired:
            continue
        assert rows[s.provider][s.canonical_id] == Decimal(str(s.input_per_mtok))
        assert rows[s.provider][f"{s.canonical_id}-output"] == Decimal(str(s.output_per_mtok))


def test_usage_rows_cover_every_spelling_including_aliases() -> None:
    rows = pm.usage_rows()
    for s in CATALOG.values():
        for spelling in s.all_ids():
            assert rows[s.provider][spelling] == Decimal(str(s.input_per_mtok))
            assert rows[s.provider][f"{spelling}-output"] == Decimal(str(s.output_per_mtok))


def test_usage_rows_emit_a_cache_read_column_only_where_documented() -> None:
    """``billing.usage.calculate_token_cost`` bills a cached prompt token at
    the DOCUMENTED rate; a row without one keeps the 10%-of-input heuristic
    rather than gaining an invented price (finding O-P2a on #9989)."""
    rows = pm.usage_rows()
    documented = [s for s in CATALOG.values() if s.cache_read_per_mtok is not None]
    assert documented, "no catalog row documents a cache-read rate"
    for s in documented:
        for spelling in s.all_ids():
            assert rows[s.provider][f"{spelling}-cache-read"] == Decimal(str(s.cache_read_per_mtok))
    for s in CATALOG.values():
        if s.cache_read_per_mtok is not None:
            continue
        for spelling in s.all_ids():
            assert f"{spelling}-cache-read" not in rows[s.provider], spelling


def test_pdb_rows_cover_every_spelling() -> None:
    rows = pm.pdb_rows()
    for s in CATALOG.values():
        for sp in s.all_ids():
            assert rows[sp] == (s.input_per_mtok, s.output_per_mtok)


def test_debate_cost_rows_cover_every_spelling() -> None:
    rows = pm.debate_cost_rows()
    for s in CATALOG.values():
        for sp in s.all_ids():
            assert rows[s.provider][sp] == (
                Decimal(str(s.input_per_mtok)),
                Decimal(str(s.output_per_mtok)),
            )


def test_metering_rows_matches_usage_rows_shape() -> None:
    """MODEL_PRICING's hand-written value shape (provider -> {id: Decimal,
    f"{id}-output": Decimal}) matches PROVIDER_PRICING's exactly, so the
    generator output must too."""
    assert pm.metering_rows() == pm.usage_rows()


def test_provider_config_rows_keys_only_canonical_ids() -> None:
    """Enumeration consumers must never see an alias/direct/openrouter
    spelling occupy its own candidate slot."""
    rows = pm.provider_config_rows()
    for s in CATALOG.values():
        if s.retired:
            continue
        assert s.canonical_id in rows
    for key in rows:
        assert key in CATALOG, f"provider_config_rows() key {key!r} is not a canonical catalog id"


def test_provider_config_rows_excludes_retired_rows() -> None:
    """The routing roster is a candidate set: a retired row is dead on the
    wire, so offering it is worse than useless."""
    rows = pm.provider_config_rows()
    retired = [s.canonical_id for s in CATALOG.values() if s.retired]
    assert retired, "fixture assumption: the catalog carries at least one retired row"
    for canonical_id in retired:
        assert canonical_id not in rows, f"{canonical_id} is retired and must not be projected"


def test_provider_config_rows_are_not_calendar_dependent() -> None:
    """Soak is NOT a projection filter (final review #7).

    Filtering the enumerated table by soak inverted the candidate set (it
    withheld the current defaults while offering retired ids) and made a
    module-level constant change contents on a wall-clock date, which is a
    latent flake for any membership or count assertion. Soak gating lives on
    the SELECTION path instead (provider_router._is_under_soak).
    """
    from datetime import date

    soaking = [
        (s, s.soak_until) for s in CATALOG.values() if s.soak_until is not None and not s.retired
    ]
    assert soaking, "fixture assumption: the catalog carries at least one soaking row"

    baseline = set(pm.provider_config_rows())
    for spec, soak_until in soaking:
        assert soak_until is not None
        assert spec.canonical_id in baseline, (
            f"{spec.canonical_id} is soaking but active; it must still be a routing candidate"
        )
        mid_soak = spec.release_date + (soak_until - spec.release_date) // 2
        assert set(pm.provider_config_rows(today=mid_soak)) == baseline
    assert set(pm.provider_config_rows(today=date(2099, 1, 1))) == baseline


def test_legacy_tables_contain_mirror_rows() -> None:
    from aragora.billing.usage import PROVIDER_PRICING
    from aragora.pdb.real_invoker import _PRICE_PER_MTOK
    from aragora.billing.debate_costs import DEFAULT_PROVIDER_RATES
    from aragora.routing.provider_config import PROVIDER_PRICING as ROUTING

    assert PROVIDER_PRICING["anthropic"]["claude-fable-5-1"] == Decimal("10.00")
    assert _PRICE_PER_MTOK["claude-fable-5-1"] == (10.00, 50.00)
    assert DEFAULT_PROVIDER_RATES["openai"]["gpt-6-astra"] == (Decimal("10.00"), Decimal("50.00"))
    assert (
        ROUTING["grok-4.6"].input_cost_per_1k == 0.002
        and ROUTING["grok-4.6"].output_cost_per_1k == 0.006
    )


def test_legacy_tables_still_resolve_pre_existing_hand_rows() -> None:
    """The mirror must not delete hand rows for models the catalog doesn't
    know about (receipts pinned to those spellings must keep resolving)."""
    from aragora.billing.usage import PROVIDER_PRICING
    from aragora.pdb.real_invoker import _PRICE_PER_MTOK

    assert PROVIDER_PRICING["openai"]["gpt-4o"] == Decimal("2.50")
    assert _PRICE_PER_MTOK["gpt-4o"] == (2.50, 10.00)


# ---------------------------------------------------------------------------
# Bucket emission (2026-09-05 merge-gate fix wave: C-P1 / O-P2c on #9989)
#
# Every row must price under EVERY provider label a caller legitimately
# passes for it, not only under ``ModelSpec.provider``:
#   * ``openrouter`` -- OpenRouterAgent.agent_type is "openrouter", and that
#     is what the monthly budget guard and orchestrator_runner hand
#     ``calculate_token_cost``;
#   * the FAMILY bucket for an openrouter-provider row -- what
#     ``cost_estimation._pricing_provider`` derives for it.
# ---------------------------------------------------------------------------


def _default_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """Cost of the openrouter bucket's documented $2/$8 default rate."""
    return (Decimal(tokens_in) / Decimal(10**6)) * Decimal("2.00") + (
        Decimal(tokens_out) / Decimal(10**6)
    ) * Decimal("8.00")


def _expected_cost(spec, tokens_in: int, tokens_out: int) -> Decimal:
    """Tier-aware, like ``calculate_token_cost`` itself: a prompt at or above
    a row's documented ``long_context_threshold`` bills every token in the
    request at the higher rate (finding O-P2b on #9989). Using the flat
    fields here would make this helper disagree with the code it checks for
    exactly the rows the tier exists for (``gpt-6-astra``, ``grok-4.6``)."""
    input_rate, output_rate = spec.rates_for(tokens_in)
    return (Decimal(tokens_in) / Decimal(10**6)) * Decimal(str(input_rate)) + (
        Decimal(tokens_out) / Decimal(10**6)
    ) * Decimal(str(output_rate))


def test_openrouter_bucket_prices_every_openrouter_slug() -> None:
    """Every catalog row's OpenRouter slug prices at the catalog rate under
    ``provider="openrouter"`` -- the exact regression the reviewer measured
    (``anthropic/claude-fable-5.1`` billed $10 instead of $60 per MTok
    pair, a ~6x under-count of Fable-via-OpenRouter spend)."""
    from aragora.billing.usage import calculate_token_cost

    assert calculate_token_cost(
        "openrouter", "anthropic/claude-fable-5.1", 1_000_000, 1_000_000
    ) == Decimal("60.00")

    for s in CATALOG.values():
        for slug in (i for i in s.all_ids() if "/" in i):
            assert calculate_token_cost("openrouter", slug, 1_000, 500) == _expected_cost(
                s, 1_000, 500
            ), f"{slug} does not price under the openrouter bucket"


def test_every_via_openrouter_pin_prices_non_default() -> None:
    """Every ``*_VIA_OPENROUTER`` model pin -- the fallback target of every
    native agent after the frontier refresh -- must price at its catalog
    rate, never at the bucket default."""
    from aragora.billing.usage import calculate_token_cost
    from aragora.config import model_pins
    from aragora.models.catalog import by_any_id

    pins = {n: getattr(model_pins, n) for n in dir(model_pins) if n.endswith("_VIA_OPENROUTER")}
    assert len(pins) >= 10, f"pin discovery found only {sorted(pins)}"
    for name, slug in sorted(pins.items()):
        spec = by_any_id(slug)
        assert spec is not None, f"{name} pins uncataloged slug {slug!r}"
        cost = calculate_token_cost("openrouter", slug, 1_000_000, 1_000_000)
        assert cost == _expected_cost(spec, 1_000_000, 1_000_000), name
        if _expected_cost(spec, 1_000_000, 1_000_000) != _default_cost(1_000_000, 1_000_000):
            assert cost != _default_cost(1_000_000, 1_000_000), (
                f"{name} ({slug}) silently billed at the openrouter default rate"
            )


def test_openrouter_bucket_does_not_gain_bare_spellings() -> None:
    """Only slash-bearing (OpenRouter-shaped) spellings enter the
    ``openrouter`` bucket from a NATIVE row: a bare id under that bucket
    would claim a rate for a spelling no OpenRouter call ever sends."""
    rows = pm.usage_rows()
    native_bare = {
        s.canonical_id
        for s in CATALOG.values()
        if s.provider != "openrouter"
        for spelling in s.all_ids()
        if "/" not in spelling
    }
    leaked = sorted(m for m in native_bare if m in rows["openrouter"])
    assert not leaked, f"bare native spellings leaked into the openrouter bucket: {leaked}"


def test_every_row_also_prices_under_its_family_bucket() -> None:
    """``cost_estimation._pricing_provider`` asks for the FAMILY bucket
    whenever that family names a live pricing bucket (``deepseek`` for
    ``deepseek-v4-pro-0813``), so every row of a family must be emitted
    there -- including a same-family row reached through a DIFFERENT
    provider (``qwen3.7-max`` is provider ``alibaba``, family ``qwen``),
    which would otherwise be shadowed down to the default rate by its
    openrouter-provider sibling creating the bucket."""
    rows = pm.usage_rows()
    for s in CATALOG.values():
        if not s.family:
            continue
        for spelling in s.all_ids():
            assert rows[s.family][spelling] == Decimal(str(s.input_per_mtok)), (
                f"{spelling} missing from the {s.family!r} bucket"
            )
    assert rows["qwen"]["qwen3.7-max"] == Decimal(str(CATALOG["qwen3.7-max"].input_per_mtok))


def test_cost_estimation_pairs_all_price_non_default() -> None:
    """Every (provider, model_key) pair ``cost_estimation`` can emit prices
    at a real catalog rate. This is the reviewer's O-P2c finding generalized:
    the DeepSeek pair was silently falling back to $2/$8."""
    from aragora.billing.usage import calculate_token_cost
    from aragora.models.catalog import by_any_id
    from aragora.server.handlers.debates.cost_estimation import MODEL_PROVIDER_MAP

    for spelling, (provider, model_key) in sorted(MODEL_PROVIDER_MAP.items()):
        spec = by_any_id(model_key) or by_any_id(spelling)
        if spec is None:
            continue  # legacy hand row for an uncataloged spelling
        assert calculate_token_cost(provider, model_key, 1_000, 500) == _expected_cost(
            spec, 1_000, 500
        ), f"{spelling!r} -> ({provider}, {model_key}) does not price at its catalog rate"


def test_deepseek_cost_estimation_pair_is_non_default() -> None:
    """Falsifiability anchor for the pair above (the reviewer's exact case)."""
    from aragora.billing.usage import calculate_token_cost
    from aragora.server.handlers.debates.cost_estimation import MODEL_PROVIDER_MAP

    provider, model_key = MODEL_PROVIDER_MAP["deepseek-v4-pro-0813"]
    assert (provider, model_key) == ("deepseek", "deepseek-v4-pro-0813")
    cost = calculate_token_cost(provider, model_key, 1_000_000, 1_000_000)
    assert cost == Decimal("1.1207") + Decimal("3.362")
    assert cost != _default_cost(1_000_000, 1_000_000)


def test_pre_pr_explicit_openrouter_rows_price_as_before() -> None:
    """The three OpenRouter spellings that had explicit hand rows before the
    frontier refresh must keep their exact pre-PR prices."""
    from aragora.billing.usage import calculate_token_cost

    assert calculate_token_cost(
        "openrouter", "anthropic/claude-opus-5", 1_000_000, 1_000_000
    ) == Decimal("30.00")
    assert calculate_token_cost(
        "openrouter", "anthropic/claude-fable-5", 1_000_000, 1_000_000
    ) == Decimal("60.00")
    assert calculate_token_cost("openrouter", "openai/gpt-5.5", 1_000_000, 1_000_000) == Decimal(
        "35.00"
    )


# ---------------------------------------------------------------------------
# Wave-3 generators (2026-09-04 controller rulings): the hand-maintained
# estimate tables PR 1's spec inventory missed. Unlike the five phase-2
# tables these emit ACTIVE rows only -- each consumer keeps its historical
# hand rows verbatim, so re-emitting a retired row would only restate a
# price the table already carries.
# ---------------------------------------------------------------------------


def test_per_1k_rows_are_the_catalog_rate_divided_by_1000() -> None:
    rows = pm.per_1k_rows()
    astra = CATALOG["gpt-6-astra"]
    assert rows["gpt-6-astra"] == {
        "input": astra.input_per_mtok / 1000.0,
        "output": astra.output_per_mtok / 1000.0,
    }


def test_per_mtok_rows_are_the_catalog_rate_verbatim() -> None:
    rows = pm.per_mtok_rows()
    fable = CATALOG["claude-fable-5-1"]
    assert rows["claude-fable-5-1"] == {
        "input": fable.input_per_mtok,
        "output": fable.output_per_mtok,
    }


def test_input_cost_per_1k_rows_use_the_input_rate() -> None:
    rows = pm.input_cost_per_1k_rows()
    grok = CATALOG["grok-4.6"]
    assert rows["grok-4.6"] == grok.input_per_mtok / 1000.0


def test_wave3_generators_cover_every_active_spelling_and_no_retired_row() -> None:
    active = {sp for s in CATALOG.values() if not s.retired for sp in s.all_ids()}
    retired_only = {sp for s in CATALOG.values() if s.retired for sp in s.all_ids()} - active
    for rows in (pm.per_1k_rows(), pm.per_mtok_rows(), pm.input_cost_per_1k_rows()):
        assert active <= set(rows)
        assert not (retired_only & set(rows))


def test_workflow_tables_gained_the_frontier_and_kept_their_history() -> None:
    """Both workflow ``MODEL_PRICING`` tables had no row for any current
    frontier model, so every live call billed at the ``default`` estimate."""
    from aragora.workflow.engine_v2 import MODEL_PRICING as ENGINE_PRICING
    from aragora.workflow.resource_tracker import MODEL_PRICING as TRACKER_PRICING

    per_1k = pm.per_1k_rows()
    for table in (ENGINE_PRICING, TRACKER_PRICING):
        # Historical rows and family labels survive untouched.
        assert table["gpt-4"] == {"input": 0.03, "output": 0.06}
        assert table["claude"] == {"input": 0.003, "output": 0.015}
        assert table["default"] == {"input": 0.003, "output": 0.015}
        # ... and every active catalog spelling is now priced explicitly.
        for spelling, rates in per_1k.items():
            assert table[spelling] == rates
        assert table["gpt-6-astra"] != table["default"]


def test_context_manager_pricing_gained_the_frontier_and_kept_its_history() -> None:
    from aragora.documents.chunking.context_manager import PRICING, ContextManager

    assert PRICING["gpt-4-turbo"] == {"input": 10.00, "output": 30.00}
    for spelling, rates in pm.per_mtok_rows().items():
        assert PRICING[spelling] == rates

    # A preview for a current model no longer falls back to the $5/$15 guess.
    astra = CATALOG["gpt-6-astra"]
    estimate = ContextManager().estimate_cost(total_tokens=1_000_000, model="gpt-6-astra")
    assert estimate["input_cost_usd"] == round(astra.input_per_mtok, 4)


def test_agent_cost_estimates_gained_the_frontier_and_kept_prefix_matching() -> None:
    from aragora.server.handlers.agents.recommendations import _AGENT_COST_ESTIMATES

    assert _AGENT_COST_ESTIMATES["claude"] == 0.015
    assert _AGENT_COST_ESTIMATES["gpt-4o"] == 0.005
    # The family labels must still come FIRST so prefix matching (which
    # walks the dict in insertion order) still reaches them.
    keys = list(_AGENT_COST_ESTIMATES)
    assert keys.index("claude") < keys.index("claude-fable-5-1")
    for spelling, rate in pm.input_cost_per_1k_rows().items():
        assert _AGENT_COST_ESTIMATES[spelling] == rate


def test_context_window_rows_mirror_the_catalog_field() -> None:
    rows = pm.context_window_rows()
    for s in CATALOG.values():
        if s.retired:
            continue
        for spelling in s.all_ids():
            assert rows[spelling] == s.context_window


def test_model_token_limits_gained_the_frontier_and_kept_its_history() -> None:
    """The historical rows are the only source for spellings the catalog
    dropped, and their POSITION drives ``get_model_token_limit``'s substring
    fallback."""
    from aragora.documents.models import MODEL_TOKEN_LIMITS, get_model_token_limit

    assert get_model_token_limit("gpt-4") == 8_192
    assert get_model_token_limit("gpt-4-turbo") == 128_000
    assert get_model_token_limit("gpt-3.5-turbo") == 16_385
    # Substring fallback still reaches the historical gpt-4o row first.
    assert get_model_token_limit("gpt-4o-mini") == 128_000
    # "default" must stay LAST so it is only reached after every real model.
    assert list(MODEL_TOKEN_LIMITS)[-1] == "default"
    assert get_model_token_limit("unknown-model-xyz123") == MODEL_TOKEN_LIMITS["default"]

    for spelling, window in pm.context_window_rows().items():
        assert MODEL_TOKEN_LIMITS[spelling] == window
    # The frontier is no longer stuck on the 128K fallback.
    assert get_model_token_limit("gpt-6-astra") == CATALOG["gpt-6-astra"].context_window


def test_bare_family_names_reach_their_frontier_row_context_window() -> None:
    """A bare family word now resolves through the generated rows.

    ``get_model_token_limit`` falls back to substring matching, and before
    the catalog-generated rows landed a bare family word like "deepseek" or
    "kimi" matched no row at all and fell through to the 8,192 default --
    so a chunker asked to size a window for a family name sized it for a
    model two generations behind. Documented here because the behaviour is
    a consequence of the generated rows rather than an explicit branch, and
    a future row rename would silently take it away again (2026-09-05
    merge-gate addendum on #9989).
    """
    from aragora.documents.models import MODEL_TOKEN_LIMITS, get_model_token_limit

    expected = {
        "deepseek": CATALOG["deepseek-v4-pro-0813"].context_window,
        "kimi": CATALOG["kimi-k3"].context_window,
        "qwen": CATALOG["qwen3.8-2.4t-a95b"].context_window,
        "grok": CATALOG["grok-4.6"].context_window,
    }
    for family_word, window in expected.items():
        got = get_model_token_limit(family_word)
        assert got == window, f"{family_word}: {got} != {window}"
        assert got > MODEL_TOKEN_LIMITS["default"]


def test_model_encodings_put_post_gpt4o_openai_rows_on_o200k() -> None:
    from aragora.documents.chunking.token_counter import MODEL_ENCODINGS

    # Both historical GPT-4-line encodings survive, distinctly.
    assert MODEL_ENCODINGS["gpt-4"] == "cl100k_base"
    assert MODEL_ENCODINGS["gpt-4-turbo"] == "cl100k_base"
    assert MODEL_ENCODINGS["gpt-4o"] == "o200k_base"
    assert MODEL_ENCODINGS["default"] == "cl100k_base"

    for spec in CATALOG.values():
        if spec.retired:
            continue
        expected = "o200k_base" if spec.provider == "openai" else "cl100k_base"
        for spelling in spec.all_ids():
            assert MODEL_ENCODINGS[spelling] == expected, spelling


def test_context_bands_are_derived_from_the_catalog_and_do_not_overlap() -> None:
    from aragora.documents.chunking.context_manager import (
        LARGE_CONTEXT_TOKENS,
        MEDIUM_CONTEXT_TOKENS,
        ContextManager,
    )

    large = ContextManager.LARGE_CONTEXT_MODELS
    medium = ContextManager.MEDIUM_CONTEXT_MODELS
    assert not (large & medium)
    # Historical spellings survive.
    assert {"gemini-3-pro", "gemini-1.5-pro"} <= large
    assert {"gpt-4-turbo", "claude-3-opus"} <= medium

    for spec in CATALOG.values():
        if spec.retired:
            continue
        target = large if spec.context_window >= LARGE_CONTEXT_TOKENS else medium
        if spec.context_window < MEDIUM_CONTEXT_TOKENS:
            continue
        for spelling in spec.all_ids():
            assert spelling in target, spelling
    assert "gpt-6-astra" in large
