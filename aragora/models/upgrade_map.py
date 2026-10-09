"""Single old→current model-ID map.

Runtime: ``resolve_model_id`` normalises any legacy or superseded spelling
before catalog or pricing lookups. Build time:
``scripts/refresh_model_literals.py`` rewrites literals with the same table.
Bringing the repo's literals into agreement with the runtime is the sweep's
job (PR 3) and keeping them there is its CI job's (PR 4); until both land the
check is ADVISORY and thousands of retired literals remain outside the
allowlist -- run ``--check`` for the current count.

Contract (frontier-model-refresh, Task 2, 2026-09-04 controller rulings):

* ``UPGRADES`` keys are spellings of RETIRED or ABSENT models ONLY. A
  spelling that Task 1 attached as a catalog *alias* to an ACTIVE row (e.g.
  ``mistral-medium-latest``, ``qwen/qwen3.8-max``) must NOT be a key here —
  it already resolves via ``spec_or_none``/``by_any_id`` alias lookup, and
  duplicating it as an UPGRADES key would risk the two paths drifting.
  Two bare spellings are the deliberate exception: ``mistral-large`` and
  ``gemini-3.1-pro`` are kept as UPGRADES keys because Task 1 kept them OFF
  their rows' ``aliases`` tuples (they collide with static routing
  hand-rows in ``aragora/routing/provider_config.py``), so this map is
  their only path back to the current id.
* ``resolve_model_id`` checks, in order: (1) ``UPGRADES`` exact-key hit;
  (2) ``spec_or_none`` resolution to an ACTIVE (non-retired) catalog row,
  returning its ``canonical_id``; (3) ``spec_or_none`` resolution to a
  RETIRED row, returning the ``UPGRADES`` target declared for ANY spelling
  of that row if there is one, else that row's family frontier
  (``frontier_for(spec.family).canonical_id``); (4) the input unchanged.
  ``None`` in, ``None`` out.
* ONE successor per retired row, whatever the spelling. Step (3) consults
  ``_ROW_SUCCESSOR`` before the family frontier because ``UPGRADES`` keys
  are individual spellings, not rows: ``mistral-large-2411`` was a key
  (-> ``mistral-large-2512``) while its OpenRouter spelling
  ``mistralai/mistral-large-2411`` was not, so the same retired model
  upgraded two different ways depending on how it was written (finding
  C-P3 on #9989). The explicit entry is authoritative for every spelling
  of its row; the family frontier stays the answer for a retired row no
  ``UPGRADES`` entry names.
* ``RETIRED_PATTERN`` is built from ``UPGRADES`` keys only, with boundary
  guards so a retired key that happens to be a literal *prefix* of a
  longer ACTIVE spelling (``"claude-fable-5"`` vs. active
  ``"claude-fable-5-1"``; ``"kimi-k2"`` vs. active ``"kimi-k2.7-code"``;
  ``"deepseek-v4-pro"`` vs. active ``"deepseek-v4-pro-0813"``) never
  matches that active spelling. ``tests/models/test_upgrade_map.py``
  asserts this against every active row's ``all_ids()``.
"""

from __future__ import annotations

import re

from aragora.models.catalog import frontier_for, spec_or_none

_ANTHROPIC = "claude-fable-5-1"
# Tier preservation inside the anthropic family (finding C-P3 on #9989):
# every legacy Sonnet and Haiku spelling used to resolve to the $10/$50
# Fable flagship, so a caller pinned to a cheap Claude SKU silently paid
# flagship rates -- the exact inconsistency the OpenAI and Google blocks
# below already avoid with their value-tier targets.
_ANTHROPIC_SONNET = "claude-sonnet-5"
_ANTHROPIC_HAIKU = "claude-haiku-4-5-20251001"
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
    # Anthropic — Fable and Opus spellings (the flagship-class lines) go to
    # the current Fable; Sonnet and Haiku spellings stay in their own tier.
    # NOTE: "claude-fable-5.1" and "anthropic/claude-fable-5.1" are
    # deliberately absent — Task 1 made both catalog aliases of the ACTIVE
    # claude-fable-5-1 row (controller ruling 1).
    **{
        k: _ANTHROPIC
        for k in (
            "claude-fable-5",
            "anthropic/claude-fable-5",
            "claude-3-opus-20240229",
            "claude-3-opus",
            "claude-opus-4-20250514",
            "claude-opus-4",
            "claude-opus-4-1-20250805",
            "claude-opus-4-5-20251101",
            "claude-opus-4-6",
            "claude-opus-4.6",
            "claude-opus-4-7",
            "claude-opus-4.7",
            "claude-opus-4.1",
            "anthropic/claude-opus-4.1",
            "anthropic/claude-opus-4",
        )
    },
    # Sonnet spellings -> the current Sonnet (value tier, $2/$10), not the
    # $10/$50 flagship. The claude-sonnet-5 row and its price are the ones
    # the Claude API reference documents; see the catalog entry.
    **{
        k: _ANTHROPIC_SONNET
        for k in (
            "claude-3-5-sonnet-20241022",
            "claude-3.5-sonnet",
            "claude-3-5-sonnet-20240620",
            "claude-3-7-sonnet-20250219",
            "claude-sonnet-4-20250514",
            "claude-sonnet-4",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-6",
            "claude-sonnet-4.6",
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-sonnet-4",
            "anthropic/claude-sonnet-4.6",
        )
    },
    # Haiku spellings -> the value-tier Haiku row, not the flagship.
    **{
        k: _ANTHROPIC_HAIKU
        for k in (
            "claude-3-haiku-20240307",
            "claude-3-5-haiku-20241022",
            "anthropic/claude-3-haiku",
        )
    },
    # OpenAI — flagship-line spellings → Astra ($10/$50); every spelling
    # whose own SKU was a VALUE tier → Terra ($2/$12). The GPT-4 family
    # (gpt-4, gpt-4-turbo, gpt-4o, gpt-4.1 and their mini/nano siblings) is
    # value-tier by price: gpt-4o listed at $2.50/$10, so routing it to the
    # $10/$50 flagship was the same silent 4x over-pay the Anthropic
    # Sonnet/Haiku rows had (finding C-P3 on #9989, round 4). gpt-4.5 stays
    # on Astra: it was OpenAI's flagship research preview at $75/$150, well
    # above the 4o line, so Terra would under-serve it.
    **{
        k: _OPENAI
        for k in (
            "gpt-4.5",
            "gpt-5",
            "gpt-5.1",
            "gpt-5.2",
            "gpt-5.3",
            "gpt-5.4",
            "gpt-5.5",
            "gpt-5.6-sol",
            # Codex/chat CLI spellings. Real names a user config or Codex
            # harness can still pin; without them the CLI fallback would send
            # an OpenAI pin cross-family to Anthropic. These stay on the
            # flagship even where their base spelling moved to Terra: the
            # codex line is OpenAI's coding flagship, not a value SKU.
            "gpt-5.3-codex",
            "gpt-4.1-codex",
            "gpt-5.3-chat-latest",
            "openai/gpt-5.3",
            # Orphan spelling from aragora/server/stream/debate_executor.py's
            # generic fallback: absent from the catalog, so PR 3's sweep would
            # otherwise leave it behind as a dead slug.
            "openai/gpt-5.3-chat",
            "openai/gpt-5.4",
            "openai/gpt-5.5",
            "openai/gpt-5.6-sol",
            # NOTE: bare "o1" and "o3" are deliberately ABSENT, while every
            # hyphenated o-series spelling stays. RETIRED_PATTERN is built
            # from these keys and is what scripts/refresh_model_literals.py
            # hunts for in source text; two-character hyphen-free tokens are
            # far more often an ordinary identifier ("o1 = _make_org(...)"),
            # a plan/route/observation id, or a word in prose ("GPT-4o, o1,
            # o3") than a model pin. The 2026-09-05 repo-wide re-sweep
            # rewrote them in 25 files where none of them was a model id, and
            # no boundary rule can tell the two apart by shape (wave-6
            # ruling, sweep gap 4, on #9989). A live "o1"/"o3" pin therefore
            # no longer upgrades through this map; it falls through
            # resolve_model_id unchanged, and each provider's own
            # DEFAULT_FALLBACK_MODEL still lands it on the frontier.
            "o3-pro",
        )
    },
    **{
        k: _OPENAI_VALUE
        for k in (
            # The GPT-4 line itself, not just its mini siblings: an explicit
            # gpt-4o pin used to be rewritten to the Astra flagship while
            # gpt-4o-mini went to Terra, so the cheap SKU was treated more
            # honestly than the one it was a sibling of.
            "gpt-4",
            "gpt-4-turbo",
            "gpt-4-turbo-preview",
            "gpt-4o",
            "gpt-4.1",
            "openai/gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-5-mini",
            "gpt-5.4-mini",
            "gpt-5.6-luna",
            "openai/gpt-4o-mini",
            # Orphan spelling from aragora/server/handlers/agents/agents.py's
            # per-provider fallback map (see openai/gpt-5.3-chat above).
            "openai/gpt-4.1-mini",
            "openai/gpt-5.4-mini",
            "openai/gpt-5.6-luna",
            "o1-mini",
            "o3-mini",
            # "o4-mini" is a mini SKU and belongs with its siblings on the
            # value tier: it used to map to the Astra flagship while
            # "o3-mini"/"gpt-4o-mini" mapped to Terra, an inconsistency the
            # 2026-09-05 merge-gate review caught (finding C-P3 on #9989).
            "o4-mini",
        )
    },
    # Google. NOTE: "google/gemini-3.1-pro" is deliberately absent — Task 1
    # made it a catalog alias of the ACTIVE gemini-3.1-pro-preview row
    # (controller ruling 1). The bare "gemini-3.1-pro" spelling stays: it
    # collides with a routing hand-row, so it is NOT a catalog alias, and
    # this map is its only path back to the current id.
    **{
        k: _GOOGLE_PRO
        for k in (
            "gemini-3-pro",
            "gemini-3.1-pro",
            "google/gemini-3-pro",
            "gemini-3-pro-preview",
            "google/gemini-3-pro-preview",
            "gemini-2.5-pro",
            "gemini-1.5-pro",
            "gemini-pro",
        )
    },
    **{
        k: _GOOGLE_FLASH
        for k in (
            "gemini-2.0-flash",
            "gemini-2.0-flash-exp",
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-001",
            "gemini-1.5-flash-latest",
            "gemini-3-flash",
            "gemini-3-flash-preview",
            "gemini-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "google/gemini-2.0-flash",
            "google/gemini-3-flash-preview",
        )
    },
    # xAI
    **{
        k: _XAI
        for k in (
            "grok-2",
            "grok-3",
            "grok-3-mini",
            "grok-4",
            "grok-4-latest",
            # xAI "fast" variant spelling used by CLI pins.
            "grok-4-1-fast",
            "grok-4.3",
            "grok-4.5",
            "x-ai/grok-4",
            # Orphan spelling from aragora/server/stream/debate_executor.py
            # (see openai/gpt-5.3-chat above).
            "x-ai/grok-4.1-fast",
            "x-ai/grok-4.3",
            "x-ai/grok-4.5",
        )
    },
    # Mistral. NOTE: "mistral-large-latest" and "mistral-medium-latest"
    # (plus "mistral-medium-3.5") are deliberately absent — Task 1 made
    # them catalog aliases of their ACTIVE rows (controller ruling 1). The
    # bare "mistral-large" spelling stays for the same reason as
    # "gemini-3.1-pro" above: it collides with a routing hand-row, so it
    # is not a catalog alias, and this map is its only path back.
    **{
        k: _MISTRAL_LARGE
        for k in ("mistral-large", "mistral-large-2411", "mistralai/mistral-large")
    },
    **{
        k: _MISTRAL_MEDIUM
        for k in (
            "mistral-medium",
            "mistral-medium-3.1",
            "mistralai/mistral-medium-3.1",
            # NOTE: "codestral-latest" is deliberately absent here — it is a
            # live Mistral SKU (see aragora/agents/api_agents/mistral.py),
            # not a retired id. Its CLI/agent fallback comes from the
            # family-aware last resort in
            # aragora/agents/cli_agents.py::_get_fallback_agent /
            # _family_frontier_openrouter_id (Mistral family -> the Mistral
            # frontier's OpenRouter slug), not from this upgrade map.
        )
    },
    # OpenRouter-routed families
    **{
        k: _DEEPSEEK
        for k in (
            "deepseek-r1",
            "deepseek/deepseek-r1",
            "deepseek-v3",
            "deepseek/deepseek-v3",
            "deepseek-v4-pro",
            "deepseek/deepseek-v4-pro",
            "deepseek-chat",
            "deepseek/deepseek-chat",
            # Seeded agent id (scripts/seed_agents.py) and the v3.2 line.
            "deepseek-coder",
            "deepseek-v3.2",
        )
    },
    # NOTE: "qwen3.8-max" and "qwen/qwen3.8-max" are deliberately absent —
    # Task 1 made both catalog aliases of the ACTIVE qwen3.8-2.4t-a95b row
    # (controller ruling 1).
    **{
        k: _QWEN
        for k in (
            "qwen3-max",
            "qwen/qwen3-max",
            "qwen3.5-plus-02-15",
            "qwen/qwen3.5-plus-02-15",
            "qwen3.7-max",
            "qwen/qwen3.7-max",
            "qwen3-coder",
            "qwen/qwen3-coder",
            "qwen-2.5-coder",
        )
    },
    **{
        k: _KIMI
        for k in (
            "kimi-k2",
            "moonshotai/kimi-k2",
            "kimi-k2.5",
            "moonshotai/kimi-k2.5",
            "kimi-k2.6",
            "moonshotai/kimi-k2.6",
            "kimi-k2-thinking",
            "moonshotai/kimi-k2-thinking",
            "moonshot-v1-8k",
        )
    },
    **{
        k: _META
        for k in (
            "llama-3.3-70b",
            "meta-llama/llama-3.3-70b-instruct",
            "llama-4-maverick",
            "meta-llama/llama-4-maverick",
            "llama-4-scout",
            "meta-llama/llama-4-scout",
            "meta/muse-spark-1.1",
            "meta/muse-spark-1.2",
        )
    },
}

# Characters that make up a single model-id "token". A match must not be
# immediately preceded or followed by one of these — otherwise a retired
# key that happens to be a literal prefix of a longer id (active or not)
# would falsely match as a substring (e.g. retired "claude-fable-5" is a
# prefix of active "claude-fable-5-1"; retired-adjacent "kimi-k2" is a
# prefix of active "kimi-k2.7-code"). This is the exact collision class
# controller ruling 3 guards against.
#
# PUBLIC because scripts/refresh_model_literals.py needs the SAME boundary
# rule to ask "does this file already contain the replacement id?" — a
# second, hand-copied character class there would be free to drift from the
# one RETIRED_PATTERN is built with, and the two answers must agree
# (2026-09-05 wave-6 ruling, sweep gap 1, on #9989).
TOKEN_CHAR = r"[A-Za-z0-9_.\-/]"

RETIRED_PATTERN: re.Pattern[str] = re.compile(
    rf"(?<!{TOKEN_CHAR})"
    rf"(?:{'|'.join(re.escape(k) for k in sorted(UPGRADES, key=len, reverse=True))})"
    rf"(?!{TOKEN_CHAR})"
)


def _build_row_successors() -> dict[str, str]:
    """``{retired canonical_id: successor}`` for every RETIRED catalog row
    that any ``UPGRADES`` key names by any of its spellings.

    ``UPGRADES`` is keyed by SPELLING, so a retired row whose bare id is a
    key but whose OpenRouter slug is not used to get two different
    successors: the bare spelling took the explicit target while the slug
    fell through to the family frontier (finding C-P3 on #9989). Collapsing
    the map onto canonical ids once, at import, gives ``resolve_model_id``
    one answer per row for free.

    A row whose spellings disagree on a target is a genuine authoring bug
    in ``UPGRADES``, not something to paper over at runtime, so it raises
    here rather than picking a winner.
    """
    successors: dict[str, str] = {}
    for old, new in UPGRADES.items():
        spec = spec_or_none(old)
        if spec is None or not spec.retired:
            continue
        existing = successors.setdefault(spec.canonical_id, new)
        if existing != new:
            raise ValueError(
                f"UPGRADES gives retired row {spec.canonical_id!r} two successors: "
                f"{existing!r} and {new!r}"
            )
    return successors


_ROW_SUCCESSOR: dict[str, str] = _build_row_successors()


def resolve_model_id(model_id: str | None) -> str | None:
    """Map a legacy or superseded model spelling to the current catalog id.

    Order: an exact ``UPGRADES`` key hit wins; otherwise a spelling that
    resolves (via any catalog spelling: canonical/direct/openrouter/alias)
    to an ACTIVE row returns that row's ``canonical_id`` unchanged; a
    spelling that resolves to a RETIRED row returns the successor
    ``UPGRADES`` declares for that ROW (under any of its spellings) if
    there is one, else the row's family frontier; anything else passes
    through unchanged. ``None`` in, ``None`` out.

    The per-ROW step is what makes the answer spelling-independent: see
    ``_build_row_successors``.
    """
    if model_id is None:
        return None
    upgraded = UPGRADES.get(model_id)
    if upgraded is not None:
        return upgraded
    spec = spec_or_none(model_id)
    if spec is None:
        return model_id
    if not spec.retired:
        return spec.canonical_id
    row_successor = _ROW_SUCCESSOR.get(spec.canonical_id)
    if row_successor is not None:
        return row_successor
    return frontier_for(spec.family).canonical_id
