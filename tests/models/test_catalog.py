"""Catalog invariants + mirror-consistency enforcement (phase 1).

The teeth of the canonical catalog: every runtime table that carries a row
for an ENFORCED model must agree with ``aragora.models.CATALOG``. These
tests are what previously took adversarial review rounds to discover by
hand — #9073/#9075 found eleven drifting mirrors and three live provider
reprices across their review cycles.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aragora.models import (
    CATALOG,
    ENFORCED_MODELS,
    FRONTIER,
    by_any_id,
    frontier_for,
    load_snapshot,
    spec_or_none,
)

# ---------------------------------------------------------------------------
# Catalog internal invariants
# ---------------------------------------------------------------------------


def test_catalog_ids_are_unique_across_all_spellings() -> None:
    seen: dict[str, str] = {}
    for spec in CATALOG.values():
        for mid in spec.all_ids():
            assert mid not in seen or seen[mid] == spec.canonical_id, (
                f"id {mid!r} claimed by both {seen[mid]} and {spec.canonical_id}"
            )
            seen[mid] = spec.canonical_id


def test_catalog_prices_positive_and_output_gte_input() -> None:
    for spec in CATALOG.values():
        assert spec.input_per_mtok > 0
        assert spec.output_per_mtok >= spec.input_per_mtok


def test_no_row_has_openrouter_family() -> None:
    """``aragora.models.pricing_mirror._bucketed`` only emits a row's
    SLASH-BEARING spellings under the ``openrouter`` bucket (a bare id under
    that bucket would claim a rate for a spelling no OpenRouter call ever
    sends). That rule assumes ``"openrouter"`` never names a real FAMILY —
    if it did, rule 3 there (the family bucket, emitted with every spelling,
    slash-bearing or not) would put bare ids into the openrouter bucket
    after all, reintroducing the hole the slash-only rule closes."""
    for spec in CATALOG.values():
        assert spec.family != "openrouter", (
            f"{spec.canonical_id!r} has family == 'openrouter'; this breaks "
            "the pricing_mirror slash-only invariant for that bucket"
        )


def test_openrouter_provider_rows_use_canonical_id_as_direct_id_placeholder() -> None:
    """Every ``provider == "openrouter"`` row's ``direct_id`` is documented
    (see the ``ModelSpec.direct_id`` docstring) as a PLACEHOLDER equal to
    ``canonical_id`` -- an OpenRouter naming convention, not a code any
    native provider endpoint would accept."""
    openrouter_rows = [spec for spec in CATALOG.values() if spec.provider == "openrouter"]
    assert openrouter_rows, "fixture assumption: the catalog carries at least one openrouter row"
    for spec in openrouter_rows:
        assert spec.direct_id == spec.canonical_id, (
            f"{spec.canonical_id!r} has provider == 'openrouter' but direct_id "
            f"{spec.direct_id!r} != canonical_id -- the documented placeholder "
            "invariant is violated"
        )


def test_soak_dates_only_on_recent_releases() -> None:
    for spec in CATALOG.values():
        if spec.soak_until is not None:
            assert spec.soak_until > spec.release_date
            assert (spec.soak_until - spec.release_date).days == 14


def test_is_under_soak_semantics() -> None:
    """soak_until is a must-not-adopt-BEFORE date: under soak strictly
    before it, adoptable on the date itself; None = long-established."""
    for spec in CATALOG.values():
        if spec.soak_until is None:
            assert not spec.is_under_soak()
            assert not spec.is_under_soak(today=date(2020, 1, 1))
        else:
            day_before = date.fromordinal(spec.soak_until.toordinal() - 1)
            assert spec.is_under_soak(today=day_before)
            assert not spec.is_under_soak(today=spec.soak_until)


def test_by_any_id_resolves_every_spelling() -> None:
    for spec in CATALOG.values():
        for mid in spec.all_ids():
            assert by_any_id(mid) is spec
    assert by_any_id("no-such-model") is None


# ---------------------------------------------------------------------------
# Snapshot consistency (offline; required CI never touches the network)
# ---------------------------------------------------------------------------


# Catalog rows whose OpenRouter slug is DELISTED from the live catalog, so
# ``scripts/model_catalog_drift.py`` (its ``--refresh`` and ``--add-missing``
# modes are the only writers of catalog_snapshot.json -- the file is never
# hand-edited) cannot produce a row for them. Their rates come from the model
# provider's own published pricing instead, recorded per entry. Every entry
# must be a RETIRED row: a live model missing from the snapshot is a genuine
# gap, not an exemption.
_DELISTED_FROM_OPENROUTER: dict[str, str] = {
    "mistralai/mistral-large-2411": (
        "Mistral Large 2411 is gone from openrouter.ai/api/v1/models (verified "
        "2026-09-05; only 2512/2407/mistral-large remain). Rates are Mistral La "
        "Plateforme's published $2.00/$6.00 per MTok, mirrored by the hand row "
        "in aragora/pdb/real_invoker.py that predates the catalog entry."
    ),
}


def test_catalog_matches_committed_snapshot() -> None:
    snapshot = load_snapshot()
    for spec in CATALOG.values():
        if spec.openrouter_id in _DELISTED_FROM_OPENROUTER:
            assert spec.retired, (
                f"{spec.canonical_id}: only a RETIRED row may be exempted from "
                "the snapshot -- a live model absent from the capture is a gap"
            )
            assert spec.openrouter_id not in snapshot, (
                f"{spec.openrouter_id} is back in the snapshot -- drop it from "
                f"_DELISTED_FROM_OPENROUTER ({_DELISTED_FROM_OPENROUTER[spec.openrouter_id]})"
            )
            continue
        row = snapshot.get(spec.openrouter_id)
        assert row is not None, f"snapshot missing {spec.openrouter_id}"
        assert float(row["input_per_mtok"]) == pytest.approx(spec.input_per_mtok), (
            f"{spec.canonical_id}: catalog input {spec.input_per_mtok} != "
            f"snapshot {row['input_per_mtok']} — refresh the snapshot or fix the catalog"
        )
        assert float(row["output_per_mtok"]) == pytest.approx(spec.output_per_mtok)


@pytest.mark.parametrize(
    ("canonical_id", "openrouter_id", "rates"),
    [
        ("sonar-reasoning-pro", "perplexity/sonar-reasoning-pro", (2.0, 8.0)),
        ("command-a", "cohere/command-a", (2.5, 10.0)),
        ("jamba-large-1.7", "ai21/jamba-large-1.7", (2.0, 8.0)),
    ],
)
def test_refreshed_openrouter_defaults_are_cataloged(
    canonical_id: str,
    openrouter_id: str,
    rates: tuple[float, float],
) -> None:
    spec = CATALOG[canonical_id]
    assert spec.openrouter_id == openrouter_id
    assert (spec.input_per_mtok, spec.output_per_mtok) == rates


def test_kimi_k3_runtime_metadata_and_soak_boundary() -> None:
    spec = CATALOG["kimi-k3"]

    assert spec.direct_id == "kimi-k3"
    assert spec.openrouter_id == "moonshotai/kimi-k3"
    assert (spec.input_per_mtok, spec.output_per_mtok) == (3.0, 15.0)
    assert spec.context_window == 1_048_576
    assert spec.max_output_tokens == 32_768
    assert spec.release_date == date(2026, 7, 16)
    assert spec.soak_until == date(2026, 7, 30)
    assert spec.is_under_soak(today=date(2026, 7, 29))
    assert not spec.is_under_soak(today=date(2026, 7, 30))


def test_qwen38_2_4t_a95b_runtime_metadata() -> None:
    """qwen3.8-max is superseded by qwen3.8-2.4t-a95b (canonical), which
    carries qwen3.8-max / qwen/qwen3.8-max as aliases so existing lookups by
    the old spelling keep resolving (frontier-model-refresh, controller
    ruling 2)."""
    spec = CATALOG["qwen3.8-2.4t-a95b"]

    assert spec.direct_id == "qwen3.8-2.4t-a95b"
    assert spec.openrouter_id == "qwen/qwen3.8-2.4t-a95b"
    assert (spec.input_per_mtok, spec.output_per_mtok) == (2.0, 6.0)
    assert spec.context_window == 1_048_576
    assert spec.max_output_tokens == 131_072
    assert spec.release_date == date(2026, 8, 12)
    assert spec.soak_until is None
    assert not spec.is_under_soak()
    assert by_any_id("qwen3.8-max") is spec
    assert by_any_id("qwen/qwen3.8-max") is spec


# ---------------------------------------------------------------------------
# Mirror-consistency enforcement
# ---------------------------------------------------------------------------


def _approx_pair(actual_in: float | Decimal, actual_out: float | Decimal, spec) -> None:
    assert float(actual_in) == pytest.approx(spec.input_per_mtok), (
        f"{spec.canonical_id}: input {actual_in} != catalog {spec.input_per_mtok}"
    )
    assert float(actual_out) == pytest.approx(spec.output_per_mtok), (
        f"{spec.canonical_id}: output {actual_out} != catalog {spec.output_per_mtok}"
    )


@pytest.mark.parametrize("canonical_id", ENFORCED_MODELS)
def test_pdb_price_table_matches_catalog(canonical_id: str) -> None:
    from aragora.pdb.real_invoker import _PRICE_PER_MTOK

    spec = CATALOG[canonical_id]
    for mid in (spec.direct_id, spec.canonical_id):
        if mid in _PRICE_PER_MTOK:
            _approx_pair(*_PRICE_PER_MTOK[mid], spec)
            break
    else:
        pytest.fail(f"pdb _PRICE_PER_MTOK has no row for {canonical_id}")


@pytest.mark.parametrize("canonical_id", ENFORCED_MODELS)
def test_billing_usage_matches_catalog(canonical_id: str) -> None:
    from aragora.billing.usage import PROVIDER_PRICING

    spec = CATALOG[canonical_id]
    checked = False
    for provider_key, table in PROVIDER_PRICING.items():
        for mid in spec.all_ids():
            if mid in table and f"{mid}-output" in table:
                _approx_pair(table[mid], table[f"{mid}-output"], spec)
                checked = True
    assert checked, f"billing usage.PROVIDER_PRICING has no row for {canonical_id}"


@pytest.mark.parametrize("canonical_id", ENFORCED_MODELS)
def test_metering_models_matches_catalog(canonical_id: str) -> None:
    from aragora.services.metering_models import MODEL_PRICING

    spec = CATALOG[canonical_id]
    checked = False
    for table in MODEL_PRICING.values():
        for mid in spec.all_ids():
            if mid in table and f"{mid}-output" in table:
                _approx_pair(table[mid], table[f"{mid}-output"], spec)
                checked = True
    assert checked, (
        f"metering MODEL_PRICING has no row for {canonical_id} — "
        "UsageMeter._calculate_token_cost falls back to provider/default rates "
        "for missing rows, silently mis-billing live usage; add the row to "
        "aragora/services/metering_models.py from the catalog"
    )


@pytest.mark.parametrize("canonical_id", ENFORCED_MODELS)
def test_debate_costs_matches_catalog(canonical_id: str) -> None:
    from aragora.billing.debate_costs import DEFAULT_PROVIDER_RATES

    spec = CATALOG[canonical_id]
    checked = False
    for table in DEFAULT_PROVIDER_RATES.values():
        for mid in spec.all_ids():
            pair = table.get(mid)
            if isinstance(pair, tuple) and len(pair) == 2:
                _approx_pair(pair[0], pair[1], spec)
                checked = True
    if not checked:
        pytest.skip(f"debate_costs has no row for {canonical_id} (presence not yet required)")


@pytest.mark.parametrize("canonical_id", ENFORCED_MODELS)
def test_provider_config_matches_catalog(canonical_id: str) -> None:
    """Routing is the one mirror that EXCLUDES retired rows.

    It is a candidate set for selection, and a retired id is dead on the
    wire (frontier-model-refresh final review #7). Retired models still
    price -- via ``get_estimated_cost``'s ``by_any_id`` fallback, which has
    no retirement gating -- so old receipts keep resolving.
    """
    from aragora.routing.provider_config import current_pricing_table, get_estimated_cost

    spec = CATALOG[canonical_id]
    table = current_pricing_table()

    if spec.retired:
        present = [mid for mid in spec.all_ids() if mid in table]
        assert not present, f"retired {canonical_id} must not be a routing candidate: {present}"
        # 2k/1k tokens: small enough to stay under any long-context tier
        # threshold, so the flat catalog rates are the expected answer.
        cost = get_estimated_cost(canonical_id, 2_000, 1_000)
        expected = spec.input_per_mtok * 0.002 + spec.output_per_mtok * 0.001
        assert cost == pytest.approx(expected), (
            f"retired {canonical_id} lost its price; old receipts would not resolve"
        )
        return

    checked = False
    for mid in spec.all_ids():
        row = table.get(mid)
        if row is not None:
            _approx_pair(row.input_cost_per_1k * 1000, row.output_cost_per_1k * 1000, spec)
            checked = True
    assert checked, f"provider_config has no row for {canonical_id}"


def test_model_selector_profiles_match_catalog() -> None:
    """Every model_selector profile whose model_id resolves to an ENFORCED
    catalog spec must carry the catalog's pricing (per-1k mirror of the
    per-MTok catalog values)."""
    from aragora.agents.model_selector import MODEL_PROFILES

    checked: set[str] = set()
    for profile in MODEL_PROFILES.values():
        spec = by_any_id(profile.model_id)
        if spec is None or spec.canonical_id not in ENFORCED_MODELS:
            continue
        _approx_pair(profile.cost_input_per_1k * 1000, profile.cost_output_per_1k * 1000, spec)
        checked.add(spec.canonical_id)
    # Anchor: the dedicated "claude-opus-4-8" profile is known to have a
    # selector profile pointing at that enforced row. Deleting or renaming
    # that row off-catalog fails here instead of passing vacuously.
    #
    # NOTE (frontier-model-refresh, 2026-09-04): "gpt4" no longer anchors
    # "gpt-5.5" here — the profile now points at the new frontier
    # "gpt-6-astra", which is not yet in ENFORCED_MODELS (mirror-table
    # migration is later-task scope per aragora/models/catalog.py's
    # ENFORCED_MODELS comment). gpt-5.5 itself remains cataloged and priced
    # (see tests/models/test_reachable_defaults.py for reachability), it is
    # just no longer the model_selector's chosen representative.
    assert {"claude-opus-4-8"} <= checked, (
        f"model_selector enforcement anchors missing: checked only {sorted(checked)}"
    )


# Fallback targets that intentionally have no catalog spec yet. Each entry
# needs adjudication before cataloging. Remove an entry once its model is
# cataloged; a stale entry fails the hygiene assertion below.
#
# "deepseek/deepseek-v4-pro" was removed from this allowlist
# (frontier-model-refresh, 2026-09-04): the OpenRouter agent's
# DEEPSEEK_V4_PRO_MODEL constant now points at the fully-cataloged
# "deepseek/deepseek-v4-pro-0813" slug (aragora/models/catalog.py's
# deepseek-v4-pro-0813 row), so the old uncataloged spelling no longer
# appears among fallback targets at all.
_UNCATALOGED_FALLBACK_TARGETS: set[str] = set()


def test_fallback_targets_resolve_to_catalog_specs() -> None:
    """Every OpenRouter fallback TARGET must resolve to a catalog spec (a
    dead/renamed slug fails — the dead-slug class of #9073), except for the
    explicit allowlist above; and a target resolving to an ENFORCED spec must
    be exactly that spec's ``openrouter_id``."""
    from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

    targets = set(OPENROUTER_FALLBACK_MODELS.values())
    # Allowlist hygiene: every allowlisted slug must still be a live target.
    assert _UNCATALOGED_FALLBACK_TARGETS <= targets, (
        "stale _UNCATALOGED_FALLBACK_TARGETS entries: "
        f"{sorted(_UNCATALOGED_FALLBACK_TARGETS - targets)}"
    )

    checked_enforced: set[str] = set()
    for target in sorted(targets):
        spec = by_any_id(target)
        if target in _UNCATALOGED_FALLBACK_TARGETS:
            assert spec is None, (
                f"{target!r} is now cataloged — remove it from _UNCATALOGED_FALLBACK_TARGETS"
            )
            continue
        assert spec is not None, (
            f"fallback target {target!r} resolves to no catalog spec — dead or "
            "uncataloged slug; catalog it (with live verification) or add it to "
            "_UNCATALOGED_FALLBACK_TARGETS with adjudication"
        )
        if spec.canonical_id in ENFORCED_MODELS:
            assert target == spec.openrouter_id, (
                f"fallback target {target!r} resolves to enforced "
                f"{spec.canonical_id} but is not its OpenRouter slug "
                f"{spec.openrouter_id!r}"
            )
            checked_enforced.add(spec.canonical_id)
    # Falsifiability anchor: the map is known to target gpt-5.5 and opus-4.8.
    assert checked_enforced, "no enforced fallback targets were checked"


class TestLongContextTiers:
    """Documented long-context tier pricing (xAI: prompts >= 200k tokens bill
    the higher rate for ALL tokens in the request; docs.x.ai/developers/pricing
    verified 2026-07-27, surfaced by openai review on #9064)."""

    def test_grok_tiers_recorded(self) -> None:
        g45 = CATALOG["grok-4.5"]
        assert g45.long_context_threshold == 200_000
        assert (g45.input_per_mtok_long, g45.output_per_mtok_long) == (4.00, 12.00)
        g43 = CATALOG["grok-4.3"]
        assert (g43.input_per_mtok_long, g43.output_per_mtok_long) == (2.50, 5.00)

    def test_rates_for_switches_at_threshold(self) -> None:
        spec = CATALOG["grok-4.5"]
        assert spec.rates_for(199_999) == (2.00, 6.00)
        assert spec.rates_for(200_000) == (4.00, 12.00)

    def test_flat_models_ignore_threshold(self) -> None:
        spec = CATALOG["claude-fable-5"]
        assert spec.rates_for(10_000_000) == (spec.input_per_mtok, spec.output_per_mtok)

    def test_router_estimator_is_tier_aware(self) -> None:
        from aragora.routing.provider_config import get_estimated_cost

        below = get_estimated_cost("grok-4.5", 100_000, 10_000)
        above = get_estimated_cost("grok-4.5", 300_000, 10_000)
        assert below == pytest.approx(0.1 * 2.00 + 0.01 * 6.00)
        assert above == pytest.approx(0.3 * 4.00 + 0.01 * 12.00)

    def test_pdb_estimator_is_tier_aware(self) -> None:
        from aragora.pdb.real_invoker import estimate_cost_usd

        below = estimate_cost_usd(model="x-ai/grok-4.5", tokens_in=100_000, tokens_out=10_000)
        above = estimate_cost_usd(model="x-ai/grok-4.5", tokens_in=300_000, tokens_out=10_000)
        assert below == pytest.approx(0.1 * 2.00 + 0.01 * 6.00)
        assert above == pytest.approx(0.3 * 4.00 + 0.01 * 12.00)


# ---------------------------------------------------------------------------
# Frontier model refresh (2026-09-04): capability flags + family lookup
# ---------------------------------------------------------------------------


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
    for cid in (
        "gpt-5.6-terra",
        "gemini-3.1-pro-preview",
        "gemini-3.8-flash",
        "grok-4.6",
        "mistral-medium-2604",
        "mistral-large-2512",
        "deepseek-v4-pro-0813",
        "qwen3.8-2.4t-a95b",
        "kimi-k3",
        "kimi-k2.7-code",
        "muse-spark-1.3",
        "glm-5.2",
        "minimax-m3",
    ):
        assert cid in CATALOG, cid


def test_frontier_for_each_family() -> None:
    assert FRONTIER["anthropic"] == "claude-fable-5-1"
    assert FRONTIER["openai"] == "gpt-6-astra"
    assert FRONTIER["google"] == "gemini-3.1-pro-preview"
    assert FRONTIER["xai"] == "grok-4.6"
    assert FRONTIER["mistral"] == "mistral-medium-2604"
    assert frontier_for("anthropic").canonical_id == "claude-fable-5-1"


def test_secondary_tier_rows_keep_lineage_family_not_flagship_tier() -> None:
    """family stays pretraining lineage ("anthropic"), not a synthetic
    per-tier bucket: claude-opus-5 shares Fable's family but is tier
    "fallback", so it never displaces claude-fable-5-1 as the anthropic
    frontier (frontier_for() only considers tier="flagship" rows)."""
    assert CATALOG["claude-opus-5"].family == "anthropic"
    assert CATALOG["claude-opus-5"].tier == "fallback"


def test_superseded_rows_are_retired_not_deleted() -> None:
    for cid in ("claude-fable-5", "gpt-5.6-sol", "gpt-5.5", "grok-4.5", "grok-4.3", "qwen3.7-max"):
        assert CATALOG[cid].retired is True, cid
    assert spec_or_none("anthropic/claude-fable-5") is not None
    assert spec_or_none("no-such-model") is None
