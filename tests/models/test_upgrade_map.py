"""Tests for the single old→current model upgrade map.

See ``aragora/models/upgrade_map.py`` for the contract. Controller rulings
(frontier-model-refresh, Task 2, 2026-09-04) refine the original brief:

1. ``UPGRADES`` keys must be spellings of RETIRED or ABSENT models only —
   several brief-listed spellings turned out to be aliases Task 1 attached
   to ACTIVE rows (a collision class Task 1 itself hit once already, for
   ``mistral-large`` / ``gemini-3.1-pro``), so those spellings were dropped
   from the key lists in ``upgrade_map.py``. ``mistral-large`` and
   ``gemini-3.1-pro`` themselves stay as UPGRADES keys: Task 1 deliberately
   kept those two bare spellings OFF their rows' aliases (they collide with
   static routing hand-rows), so the upgrade map is their only path back to
   the current id.
2. ``resolve_model_id`` also handles retired-but-catalogued spellings that
   are *not* UPGRADES keys: it falls back to the retired row's family
   frontier via ``frontier_for``.
3. ``RETIRED_PATTERN`` must never match a spelling belonging to an ACTIVE
   catalog row — including as a *prefix* of a longer active spelling (e.g.
   retired key ``"claude-fable-5"`` must not match inside active canonical
   id ``"claude-fable-5-1"``; retired-adjacent key ``"kimi-k2"`` must not
   match inside active canonical id ``"kimi-k2.7-code"``).
"""

from __future__ import annotations

import pytest

from aragora.models.catalog import CATALOG
from aragora.models.upgrade_map import RETIRED_PATTERN, UPGRADES, resolve_model_id


@pytest.mark.parametrize(
    "old,new",
    [
        ("claude-fable-5", "claude-fable-5-1"),
        ("anthropic/claude-fable-5", "claude-fable-5-1"),
        ("claude-3-opus-20240229", "claude-fable-5-1"),
        # Tier preservation (finding C-P3 on #9989): Sonnet and Haiku
        # spellings land on their own family's value rows, not on the
        # $10/$50 Fable flagship.
        ("claude-sonnet-4-6", "claude-sonnet-5"),
        ("claude-sonnet-4.6", "claude-sonnet-5"),
        ("anthropic/claude-sonnet-4.6", "claude-sonnet-5"),
        ("claude-3-5-sonnet-20241022", "claude-sonnet-5"),
        ("claude-3-haiku-20240307", "claude-haiku-4-5-20251001"),
        ("claude-3-5-haiku-20241022", "claude-haiku-4-5-20251001"),
        ("anthropic/claude-3-haiku", "claude-haiku-4-5-20251001"),
        # Opus and Fable spellings are flagship-class and stay on Fable.
        ("claude-opus-4-7", "claude-fable-5-1"),
        # Tier preservation on OpenAI too (round-4 re-review of finding
        # C-P3 on #9989): the whole GPT-4 line was value-tier by price
        # (gpt-4o listed at $2.50/$10), so an explicit gpt-4o pin used to be
        # rewritten to the $10/$50 Astra flagship while its own gpt-4o-mini
        # sibling correctly landed on Terra.
        ("gpt-4", "gpt-5.6-terra"),
        ("gpt-4-turbo", "gpt-5.6-terra"),
        ("gpt-4-turbo-preview", "gpt-5.6-terra"),
        ("gpt-4o", "gpt-5.6-terra"),
        ("openai/gpt-4o", "gpt-5.6-terra"),
        ("gpt-4.1", "gpt-5.6-terra"),
        ("gpt-4o-mini", "gpt-5.6-terra"),
        ("gpt-4.1-mini", "gpt-5.6-terra"),
        ("o1-mini", "gpt-5.6-terra"),
        ("o3-mini", "gpt-5.6-terra"),
        ("o4-mini", "gpt-5.6-terra"),
        # Flagship-line spellings stay on Astra. gpt-4.5 was OpenAI's
        # flagship research preview ($75/$150), well above the 4o line.
        ("gpt-4.5", "gpt-6-astra"),
        ("gpt-5", "gpt-6-astra"),
        ("gpt-5.5", "gpt-6-astra"),
        ("gpt-5.6-sol", "gpt-6-astra"),
        ("o3-pro", "gpt-6-astra"),
        ("openai/gpt-5.3", "gpt-6-astra"),
        # Controller ruling 4: new case, not in the original brief list.
        ("openai/gpt-5.5", "gpt-6-astra"),
        ("gemini-2.0-flash", "gemini-3.8-flash"),
        ("gemini-1.5-flash", "gemini-3.8-flash"),
        ("gemini-3-pro", "gemini-3.1-pro-preview"),
        # Kept per controller ruling 1: "gemini-3.1-pro" is not a catalog
        # alias (Task 1 kept it off the row to avoid a routing hand-row
        # collision), so this resolves via UPGRADES, not alias lookup.
        ("gemini-3.1-pro", "gemini-3.1-pro-preview"),
        # Review fix round 1, item 5 (frontier-model-refresh, 2026-09-04):
        # these six spellings were falling through resolve_model_id
        # unresolved (no UPGRADES key, no catalog row) after gemini.py's
        # GEMINI_MODEL_ALIASES dict was deleted in favor of resolve_model_id.
        ("gemini-3-pro-preview", "gemini-3.1-pro-preview"),
        ("google/gemini-3-pro-preview", "gemini-3.1-pro-preview"),
        ("gemini-3-flash-preview", "gemini-3.8-flash"),
        ("gemini-flash", "gemini-3.8-flash"),
        ("gemini-1.5-flash-001", "gemini-3.8-flash"),
        ("gemini-1.5-flash-latest", "gemini-3.8-flash"),
        ("grok-2", "grok-4.6"),
        ("grok-4-latest", "grok-4.6"),
        ("x-ai/grok-4.5", "grok-4.6"),
        # Kept per controller ruling 1: same rationale as gemini-3.1-pro.
        ("mistral-large", "mistral-large-2512"),
        # Resolves via alias lookup now (mistral-medium-2604 carries this
        # spelling as a catalog alias), NOT via UPGRADES — controller
        # ruling 1 removed it as an UPGRADES key since it collides with an
        # active row's alias.
        ("mistral-medium-latest", "mistral-medium-2604"),
        ("deepseek-r1", "deepseek-v4-pro-0813"),
        ("deepseek/deepseek-v4-pro", "deepseek-v4-pro-0813"),
        ("qwen3-max", "qwen3.8-2.4t-a95b"),
        ("qwen/qwen3.7-max", "qwen3.8-2.4t-a95b"),
        # Controller ruling 4: new case. Resolves via alias lookup (the
        # active qwen3.8-2.4t-a95b row carries this spelling as a catalog
        # alias), NOT via UPGRADES — ruling 1 removed it as a key.
        ("qwen/qwen3.8-max", "qwen3.8-2.4t-a95b"),
        ("kimi-k2", "kimi-k3"),
        ("moonshotai/kimi-k2-thinking", "kimi-k3"),
        ("llama-3.3-70b", "muse-spark-1.3"),
        ("meta-llama/llama-4-maverick", "muse-spark-1.3"),
    ],
)
def test_known_upgrades(old: str, new: str) -> None:
    assert resolve_model_id(old) == new


def test_bare_o1_and_o3_are_not_keys_while_hyphenated_siblings_are() -> None:
    """Wave-6 ruling (sweep gap 4, #9989): RETIRED_PATTERN is built from these
    keys and drives scripts/refresh_model_literals.py over the whole repo, and
    a bare two-character token cannot be told apart from an ordinary
    identifier or a plan/route id by shape -- the 2026-09-05 re-sweep rewrote
    ``"o1"``/``"o3"`` in 25 files where none was a model. Dropping them costs
    the runtime upgrade of a literal ``o1``/``o3`` pin, which then falls
    through resolve_model_id unchanged; every hyphenated o-series spelling is
    unambiguous and stays."""
    assert "o1" not in UPGRADES
    assert "o3" not in UPGRADES
    assert not RETIRED_PATTERN.search("o1")
    assert not RETIRED_PATTERN.search("o3")
    for hyphenated in ("o1-mini", "o3-mini", "o3-pro", "o4-mini"):
        assert hyphenated in UPGRADES, hyphenated
    assert resolve_model_id("o1") == "o1"
    assert resolve_model_id("o3") == "o3"


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


def test_retired_pattern_only_contains_retired_or_absent_spellings() -> None:
    """Controller ruling 1: every UPGRADES key must belong to a RETIRED or
    ABSENT catalog row — never an ACTIVE row's canonical/direct/openrouter
    id or alias. This is the direct guard for the collision class the
    ruling identifies (spellings Task 1 attached as aliases to active rows,
    e.g. ``mistral-medium-latest``, ``qwen/qwen3.8-max``)."""
    active_spellings: set[str] = set()
    for spec in CATALOG.values():
        if not spec.retired:
            active_spellings.update(spec.all_ids())
    collisions = sorted(set(UPGRADES) & active_spellings)
    assert not collisions, collisions


def test_retired_pattern_never_matches_any_active_catalog_spelling() -> None:
    """Controller ruling 3: guards the collision class Task 1 hit, where a
    retired-row spelling (e.g. ``"claude-fable-5"``, ``"kimi-k2"``,
    ``"deepseek-v4-pro"``) is a literal *prefix* of a longer ACTIVE row's
    id (``"claude-fable-5-1"``, ``"kimi-k2.7-code"``,
    ``"deepseek-v4-pro-0813"``). A naive substring pattern would falsely
    flag/rewrite the active id; RETIRED_PATTERN must not match it."""
    for spec in CATALOG.values():
        if spec.retired:
            continue
        for spelling in spec.all_ids():
            assert not RETIRED_PATTERN.search(spelling), (spec.canonical_id, spelling)


def test_retired_row_spellings_without_upgrades_entry_use_family_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_model_id ruling 2's third branch: a spelling that belongs to
    a RETIRED catalog row but has no UPGRADES entry still resolves to that
    row's family frontier via spec_or_none + frontier_for. Every current
    retired row's spellings already have UPGRADES entries (belt-and-braces
    from the brief's exhaustive listing), so this branch is exercised here
    by removing one to prove the fallback works independently of the map."""
    assert "qwen3.7-max" in UPGRADES  # sanity: brief already covers it directly
    monkeypatch.delitem(UPGRADES, "qwen3.7-max")
    assert resolve_model_id("qwen3.7-max") == "qwen3.8-2.4t-a95b"


def test_removed_active_alias_spellings_are_not_upgrades_keys() -> None:
    """Controller ruling 1's exact removal list: these spellings collide
    with aliases Task 1 attached to ACTIVE rows, so they must not be
    UPGRADES keys — even though resolve_model_id still maps them correctly
    via catalog alias resolution (see test_known_upgrades)."""
    removed = {
        "claude-fable-5.1",
        "anthropic/claude-fable-5.1",
        "anthropic/claude-fable-5-1",
        "google/gemini-3.1-pro",
        "mistral-large-latest",
        "mistral-medium-3.5",
        "mistral-medium-latest",
        "qwen3.8-max",
        "qwen/qwen3.8-max",
    }
    assert not (removed & set(UPGRADES))
    for spelling in removed:
        spec = CATALOG.get(
            next(
                (s.canonical_id for s in CATALOG.values() if spelling in s.all_ids()),
                "",
            )
        )
        if spec is not None:
            assert not spec.retired, spelling


def test_anthropic_legacy_spellings_preserve_their_tier() -> None:
    """A cheap Claude spelling must not resolve to the $10/$50 flagship.

    Finding C-P3 on #9989: every Anthropic legacy spelling -- Haiku and
    Sonnet included -- mapped to Fable, so a caller pinned to a value SKU
    silently paid flagship rates, while the OpenAI and Google blocks in the
    same table routed their "mini"/"flash" spellings to value rows.
    """
    flagship = CATALOG["claude-fable-5-1"]
    for old, new in UPGRADES.items():
        spec = CATALOG[new]
        if spec.family != "anthropic":
            continue
        lowered = old.lower()
        if "haiku" in lowered:
            assert spec.canonical_id == "claude-haiku-4-5-20251001", (
                f"{old!r} -> {new!r}: a Haiku spelling must land on the Haiku "
                "value row, not a pricier tier"
            )
        elif "sonnet" in lowered:
            assert spec.canonical_id == "claude-sonnet-5", (
                f"{old!r} -> {new!r}: a Sonnet spelling must land on the Sonnet row"
            )
        else:
            assert spec.canonical_id == flagship.canonical_id, (
                f"{old!r} -> {new!r}: Fable/Opus spellings are flagship-class"
            )
        assert spec.input_per_mtok <= flagship.input_per_mtok
        assert spec.output_per_mtok <= flagship.output_per_mtok


def test_anthropic_tier_targets_are_active_priced_rows() -> None:
    for canonical_id in ("claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-fable-5-1"):
        spec = CATALOG[canonical_id]
        assert not spec.retired
        assert spec.family == "anthropic"
        assert spec.input_per_mtok > 0 and spec.output_per_mtok > 0
    # The value rows must not be able to displace the frontier pick.
    from aragora.models.catalog import frontier_for

    assert frontier_for("anthropic").canonical_id == "claude-fable-5-1"


def test_one_successor_per_retired_row_whatever_the_spelling() -> None:
    """A retired row must upgrade the same way however it is written.

    Finding C-P3 on #9989: ``mistral-large-2411`` was an UPGRADES key and
    resolved to ``mistral-large-2512``, but its OpenRouter spelling
    ``mistralai/mistral-large-2411`` was not a key and fell through to the
    family-frontier branch, giving the same model two successors.
    """
    assert (
        resolve_model_id("mistralai/mistral-large-2411")
        == resolve_model_id("mistral-large-2411")
        == "mistral-large-2512"
    )

    for spec in CATALOG.values():
        if not spec.retired:
            continue
        answers = {resolve_model_id(mid) for mid in spec.all_ids()}
        assert len(answers) == 1, (
            f"{spec.canonical_id}: spellings {spec.all_ids()} resolve to {answers}"
        )
        (answer,) = answers
        target = CATALOG.get(answer)
        assert target is not None and not target.retired, (
            f"{spec.canonical_id} upgrades to {answer!r}, which is not an active row"
        )


def test_row_successor_index_only_covers_retired_rows() -> None:
    from aragora.models.upgrade_map import _ROW_SUCCESSOR

    for canonical_id, successor in _ROW_SUCCESSOR.items():
        assert CATALOG[canonical_id].retired, (
            f"{canonical_id} is active; the per-row successor index is for retired rows"
        )
        assert not CATALOG[successor].retired


def test_row_successor_index_rejects_disagreeing_spellings() -> None:
    """Two spellings of one retired row may not name different successors."""
    import pytest as _pytest

    from aragora.models import upgrade_map as um

    retired = next(s for s in CATALOG.values() if s.retired and len(set(s.all_ids())) > 1)
    a, b = sorted(set(retired.all_ids()))[:2]
    conflicting = {a: "claude-fable-5-1", b: "gpt-6-astra"}
    original = um.UPGRADES
    um.UPGRADES = conflicting  # type: ignore[assignment]
    try:
        with _pytest.raises(ValueError, match="two successors"):
            um._build_row_successors()
    finally:
        um.UPGRADES = original  # type: ignore[assignment]
