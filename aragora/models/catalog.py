"""Canonical model catalog — the single typed source of model identity.

Phase 1 of the catalog design adjudicated on #9073/#9075 (2026-07-16): those
PRs empirically demonstrated that model identity and pricing were duplicated
across at least ELEVEN runtime tables, each independently discovered drifted
by adversarial review (three live provider reprices were caught mid-review).

Contract:

* ``CATALOG`` is the canonical record: ids, aliases, pricing (USD per 1M
  tokens), context/output limits, release + soak dates.
* ``catalog_snapshot.json`` (same directory) is the committed capture of the
  live OpenRouter catalog used for OFFLINE validation: required CI never
  performs network calls. ``scripts/model_catalog_drift.py`` is the advisory
  live-vs-snapshot differ.
* Existing runtime tables (billing/metering/routing/pdb/cost-estimation) are
  NOT rewired in phase 1. Instead, ``tests/models/test_catalog.py`` enforces
  that every table row for an ENFORCED model matches this catalog, so the
  mirrors can no longer drift silently. Phase 2 migrates consumers to
  projections generated from here.
* Quorum-family ELIGIBILITY deliberately stays in governance policy
  (``aragora/swarm/quorum_evidence.py``), never in this catalog: which model
  may produce merge-authority evidence is a Tier-4 governance decision, not a
  runtime lookup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

__all__ = [
    "CATALOG",
    "ENFORCED_MODELS",
    "ModelSpec",
    "by_any_id",
    "load_snapshot",
    "snapshot_path",
    "utc_today",
]


def utc_today() -> date:
    """Canonical 'today' for soak governance, anchored to UTC.

    Soak windows are a governance boundary (must-not-adopt-before dates),
    so they must not flip earlier or later depending on the host's local
    timezone."""
    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class ModelSpec:
    """Canonical identity + economics for one model."""

    canonical_id: str
    provider: str
    direct_id: str
    openrouter_id: str
    input_per_mtok: float
    output_per_mtok: float
    context_window: int
    max_output_tokens: int
    release_date: date
    # Merge-authority surfaces must not adopt a model before this date
    # (the 14-day availability rule); None = long-established.
    soak_until: date | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    # Documented long-context tier: requests whose PROMPT reaches
    # ``long_context_threshold`` tokens are billed at the ``*_long`` rates for
    # ALL tokens in the request (xAI's documented model; source recorded per
    # entry). None = flat pricing. The OpenRouter snapshot mirrors only the
    # flat fields, so tier rates are verified against provider pricing pages.
    long_context_threshold: int | None = None
    input_per_mtok_long: float | None = None
    output_per_mtok_long: float | None = None

    def all_ids(self) -> tuple[str, ...]:
        return (self.canonical_id, self.direct_id, self.openrouter_id, *self.aliases)

    def rates_for(self, prompt_tokens: int) -> tuple[float, float]:
        """Applicable (input, output) USD-per-MTok pair for a request whose
        prompt is ``prompt_tokens`` long. Falls back to flat rates when the
        model has no documented tier."""
        if (
            self.long_context_threshold is not None
            and prompt_tokens >= self.long_context_threshold
            and self.input_per_mtok_long is not None
            and self.output_per_mtok_long is not None
        ):
            return (self.input_per_mtok_long, self.output_per_mtok_long)
        return (self.input_per_mtok, self.output_per_mtok)

    def is_under_soak(self, today: date | None = None) -> bool:
        """True while the model is inside its post-release soak window
        (before ``soak_until``; the 14-day availability rule).

        Adoption surfaces — merge-authority evidence, routing candidate
        enumeration — must not offer the model while under soak. Id
        resolution (``by_any_id``) and cost lookup for its ids remain
        valid throughout the window. Defaults to the UTC calendar date
        (``utc_today``): soak is a governance boundary and must not shift
        with the host timezone.
        """
        if self.soak_until is None:
            return False
        return (today if today is not None else utc_today()) < self.soak_until


# Prices are USD per 1M tokens, captured from the live OpenRouter catalog
# (most recently refreshed 2026-08-16; see catalog_snapshot.json for the raw
# capture). Direct-provider ids are verified against provider model lists.
CATALOG: dict[str, ModelSpec] = {
    spec.canonical_id: spec
    for spec in (
        ModelSpec(
            canonical_id="claude-fable-5",
            provider="anthropic",
            direct_id="claude-fable-5",
            openrouter_id="anthropic/claude-fable-5",
            input_per_mtok=10.00,
            output_per_mtok=50.00,
            context_window=1_000_000,
            max_output_tokens=128_000,
            release_date=date(2026, 6, 20),
        ),
        ModelSpec(
            canonical_id="claude-opus-5",
            provider="anthropic",
            direct_id="claude-opus-5",
            openrouter_id="anthropic/claude-opus-5",
            # Same economics as Opus 4.8 ($5/$25) per the provider model page.
            input_per_mtok=5.00,
            output_per_mtok=25.00,
            context_window=1_000_000,
            max_output_tokens=128_000,
            release_date=date(2026, 7, 24),
            # SOAK WAIVED BY OPERATOR (2026-07-24). Opus 5 is a day-0 model and
            # would normally carry soak_until=2026-08-07 under the 14-day
            # availability rule, which would bar it from merge-authority
            # evidence and routing candidate enumeration. The operator
            # explicitly directed an immediate repo-wide bump, so it is
            # adoptable from release. Reinstating the window is a one-line
            # change: soak_until=date(2026, 8, 7).
            soak_until=None,
        ),
        ModelSpec(
            # Retained deliberately: still Active upstream (retires no sooner
            # than 2027-05-28) AND it is Opus 5's documented fallback target for
            # cyber-classifier refusals, so it must stay resolvable and priced.
            canonical_id="claude-opus-4-8",
            provider="anthropic",
            direct_id="claude-opus-4-8",
            openrouter_id="anthropic/claude-opus-4.8",
            input_per_mtok=5.00,
            output_per_mtok=25.00,
            context_window=1_000_000,
            max_output_tokens=128_000,
            release_date=date(2026, 2, 10),
            aliases=("claude-opus-4.8", "anthropic/claude-opus-4-8"),
        ),
        ModelSpec(
            canonical_id="gpt-5.6-sol",
            provider="openai",
            direct_id="gpt-5.6-sol",
            openrouter_id="openai/gpt-5.6-sol",
            input_per_mtok=5.00,
            output_per_mtok=30.00,
            context_window=1_050_000,
            max_output_tokens=128_000,
            release_date=date(2026, 7, 9),
            soak_until=date(2026, 7, 23),
        ),
        ModelSpec(
            canonical_id="gpt-5.5",
            provider="openai",
            direct_id="gpt-5.5",
            openrouter_id="openai/gpt-5.5",
            # Provider repriced from 2.50/10.00 on ~2026-07-14 (caught live
            # during the #9073/#9075 reviews).
            input_per_mtok=5.00,
            output_per_mtok=30.00,
            context_window=1_050_000,
            max_output_tokens=128_000,
            release_date=date(2025, 11, 1),
        ),
        ModelSpec(
            canonical_id="grok-4.5",
            provider="xai",
            direct_id="grok-4.5",
            openrouter_id="x-ai/grok-4.5",
            input_per_mtok=2.00,
            output_per_mtok=6.00,
            context_window=500_000,
            max_output_tokens=64_000,
            release_date=date(2026, 7, 8),
            soak_until=date(2026, 7, 22),
            # docs.x.ai/developers/pricing (verified 2026-07-27): prompts
            # >= 200k tokens bill 2x for the whole request.
            long_context_threshold=200_000,
            input_per_mtok_long=4.00,
            output_per_mtok_long=12.00,
        ),
        ModelSpec(
            canonical_id="grok-4.3",
            provider="xai",
            direct_id="grok-4.3",
            openrouter_id="x-ai/grok-4.3",
            input_per_mtok=1.25,
            output_per_mtok=2.50,
            context_window=1_000_000,
            max_output_tokens=64_000,
            release_date=date(2026, 4, 1),
            # docs.x.ai/developers/pricing (verified 2026-07-27).
            long_context_threshold=200_000,
            input_per_mtok_long=2.50,
            output_per_mtok_long=5.00,
        ),
        ModelSpec(
            canonical_id="sonar-reasoning-pro",
            provider="perplexity",
            direct_id="sonar-reasoning-pro",
            openrouter_id="perplexity/sonar-reasoning-pro",
            input_per_mtok=2.00,
            output_per_mtok=8.00,
            context_window=128_000,
            max_output_tokens=128_000,
            release_date=date(2025, 3, 7),
        ),
        ModelSpec(
            canonical_id="command-a",
            provider="cohere",
            direct_id="command-a-03-2025",
            openrouter_id="cohere/command-a",
            input_per_mtok=2.50,
            output_per_mtok=10.00,
            context_window=256_000,
            max_output_tokens=8_192,
            release_date=date(2025, 3, 13),
        ),
        ModelSpec(
            canonical_id="jamba-large-1.7",
            provider="ai21",
            direct_id="jamba-large",
            openrouter_id="ai21/jamba-large-1.7",
            input_per_mtok=2.00,
            output_per_mtok=8.00,
            context_window=256_000,
            max_output_tokens=4_096,
            release_date=date(2025, 8, 8),
        ),
        ModelSpec(
            canonical_id="qwen3.8-max",
            provider="alibaba",
            direct_id="qwen3.8-max",
            openrouter_id="qwen/qwen3.8-max",
            input_per_mtok=2.00,
            output_per_mtok=6.00,
            context_window=1_000_000,
            max_output_tokens=131_072,
            release_date=date(2026, 8, 3),
            soak_until=date(2026, 8, 17),
        ),
        ModelSpec(
            canonical_id="qwen3.7-max",
            provider="alibaba",
            direct_id="qwen3.7-max",
            openrouter_id="qwen/qwen3.7-max",
            # Repriced from 1.25/3.75 between 2026-07-10 and 2026-07-16
            # (caught live during the #9073 drain).
            input_per_mtok=1.475,
            output_per_mtok=4.425,
            context_window=1_000_000,
            max_output_tokens=32_768,
            release_date=date(2026, 6, 1),
        ),
        ModelSpec(
            canonical_id="kimi-k3",
            provider="moonshot",
            direct_id="kimi-k3",
            openrouter_id="moonshotai/kimi-k3",
            input_per_mtok=3.00,
            output_per_mtok=15.00,
            context_window=1_048_576,
            # OpenRouter does not currently publish a completion-token cap;
            # retain the existing conservative application cap.
            max_output_tokens=32_768,
            release_date=date(2026, 7, 16),
            soak_until=date(2026, 7, 30),
        ),
        ModelSpec(
            canonical_id="kimi-k2.7-code",
            provider="moonshot",
            direct_id="kimi-k2.7-code",
            openrouter_id="moonshotai/kimi-k2.7-code",
            # Live OpenRouter reprice captured by the 2026-08-16 snapshot
            # refresh; the reviewer/runtime pin itself remains unchanged.
            input_per_mtok=0.71,
            output_per_mtok=3.50,
            context_window=262_144,
            max_output_tokens=32_768,
            release_date=date(2026, 6, 15),
            # NOTE: "moonshotai/kimi-k2.6" is deliberately NOT an alias here.
            # It is a distinct, live, separately-priced OpenRouter model
            # ($0.95/$4.00 per MTok on the live catalog, 2026-07-17), so
            # aliasing it onto k2.7-code would force k2.6 mirror rows to the
            # wrong prices. Catalog k2.6 as its own ModelSpec if it needs
            # enforcement.
        ),
    )
}

# Models whose runtime-table rows are ENFORCED against this catalog by
# tests/models/test_catalog.py. Grows as legacy rows are adjudicated (several
# older mirror rows are known-stale vs the live snapshot — e.g. the deepseek
# and qwen3-max rows — and enter enforcement only once their discrepancies
# are resolved, not silently overwritten).
ENFORCED_MODELS: tuple[str, ...] = tuple(CATALOG)

_ID_INDEX: dict[str, ModelSpec] = {}
for _spec in CATALOG.values():
    for _mid in _spec.all_ids():
        _ID_INDEX[_mid] = _spec


def by_any_id(model_id: str) -> ModelSpec | None:
    """Resolve any known spelling (canonical/direct/openrouter/alias)."""
    return _ID_INDEX.get(str(model_id).strip())


def snapshot_path() -> Path:
    return Path(__file__).resolve().parent / "catalog_snapshot.json"


def load_snapshot() -> dict[str, dict[str, float | int | str]]:
    """Load the committed live-catalog capture (offline; no network)."""
    return json.loads(snapshot_path().read_text(encoding="utf-8"))["models"]
