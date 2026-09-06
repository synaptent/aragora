"""Constructor-time upgrade of retired explicit model ids on native agents.

2026-09-05 merge-gate fix wave, finding O-P2a on #9989: the native API
agents send ``model`` straight to their provider endpoint, so an explicitly
configured id the provider has since retired (``gpt-5.5``, ``grok-4-latest``)
failed the call instead of upgrading. ``gemini.py`` already resolved its id
at construction; ``anthropic``/``openai``/``grok``/``mistral`` did not.

The contract these tests pin, per agent:

* a RETIRED (or explicitly upgrade-mapped) id is replaced by its current id;
* an ACTIVE id -- including an active alias -- is left EXACTLY as passed;
* an UNKNOWN id is left exactly as passed, so a model newer than the catalog
  is still callable.
"""

from __future__ import annotations

import logging

import pytest

from aragora.agents.api_agents import common
from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
from aragora.agents.api_agents.grok import GrokAgent
from aragora.agents.api_agents.mistral import CodestralAgent, MistralAPIAgent
from aragora.agents.api_agents.openai import OpenAIAPIAgent
from aragora.config.model_pins import (
    FABLE_51_DIRECT,
    GPT56_TERRA_DIRECT,
    GPT6_ASTRA_DIRECT,
    GROK_46_DIRECT,
    MISTRAL_LARGE_DIRECT,
)

# Every base-URL override the four gated agents read. Cleared for EVERY test
# in this module: with any of them set in the ambient environment (a .env /
# direnv-provided BYOK gateway is normal on a developer box) the constructor
# skips the rewrite, and every "is upgraded" assertion below would pass
# vacuously against an unchanged id -- the exact reason the raw-env-var gate
# survived review the first time (finding O-P2a, round 2).
_BASE_URL_ENV_VARS = (
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "XAI_BASE_URL",
    "MISTRAL_BASE_URL",
)


@pytest.fixture(autouse=True)
def _official_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _BASE_URL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# (agent class, retired id, its upgrade target, active id, unknown id)
_CASES = [
    pytest.param(
        AnthropicAPIAgent,
        "claude-fable-5",
        FABLE_51_DIRECT,
        "claude-fable-5-1",
        "claude-zeta-9-20991231",
        id="anthropic",
    ),
    pytest.param(
        OpenAIAPIAgent,
        "gpt-5.5",
        GPT6_ASTRA_DIRECT,
        "gpt-6-astra",
        "gpt-7-nova",
        id="openai",
    ),
    pytest.param(
        GrokAgent,
        "grok-4-latest",
        GROK_46_DIRECT,
        "grok-4.6",
        "grok-9-hyper",
        id="grok",
    ),
    pytest.param(
        MistralAPIAgent,
        "mistral-large-2411",
        MISTRAL_LARGE_DIRECT,
        "mistral-medium-2604",
        "mistral-nova-9",
        id="mistral",
    ),
]


@pytest.mark.parametrize(("agent_cls", "retired", "upgraded", "active", "unknown"), _CASES)
def test_retired_explicit_id_is_upgraded(
    agent_cls, retired: str, upgraded: str, active: str, unknown: str
) -> None:
    assert agent_cls(model=retired, api_key="test-key").model == upgraded
    assert agent_cls(model=retired, api_key="test-key").model != retired


@pytest.mark.parametrize(("agent_cls", "retired", "upgraded", "active", "unknown"), _CASES)
def test_active_explicit_id_passes_through_unchanged(
    agent_cls, retired: str, upgraded: str, active: str, unknown: str
) -> None:
    assert agent_cls(model=active, api_key="test-key").model == active


@pytest.mark.parametrize(("agent_cls", "retired", "upgraded", "active", "unknown"), _CASES)
def test_unknown_explicit_id_passes_through_unchanged(
    agent_cls, retired: str, upgraded: str, active: str, unknown: str
) -> None:
    """A model newer than the catalog must still be callable verbatim."""
    assert agent_cls(model=unknown, api_key="test-key").model == unknown


def test_active_alias_is_not_canonicalized() -> None:
    """An active ALIAS is a working native id; the agent must not rewrite it
    to the canonical spelling (that is a resolve_model_id() behaviour this
    deliberately does not use)."""
    assert AnthropicAPIAgent(model="claude-fable-5.1", api_key="k").model == "claude-fable-5.1"
    assert MistralAPIAgent(model="mistral-medium-latest", api_key="k").model == (
        "mistral-medium-latest"
    )


def test_codestral_keeps_its_own_live_sku() -> None:
    """``codestral-latest`` is an UPGRADES key only because the catalog has
    no Codestral row (which makes mistral-medium the right OpenRouter
    fallback target). It is a live native SKU, so CodestralAgent opts out of
    the constructor-time rewrite and keeps calling the code model."""
    assert CodestralAgent(api_key="test-key").model == "codestral-latest"
    assert CodestralAgent.UPGRADE_RETIRED_MODEL_ID is False
    assert MistralAPIAgent.UPGRADE_RETIRED_MODEL_ID is True


def test_upgrade_logs_once_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    common._LOGGED_MODEL_UPGRADES.discard(("gpt-5.5", GPT6_ASTRA_DIRECT))
    with caplog.at_level(logging.WARNING, logger=common.__name__):
        OpenAIAPIAgent(model="gpt-5.5", api_key="test-key")
        OpenAIAPIAgent(model="gpt-5.5", api_key="test-key")
    upgrade_records = [r for r in caplog.records if "upgraded to" in r.getMessage()]
    assert len(upgrade_records) == 1
    assert upgrade_records[0].levelno == logging.WARNING
    assert "gpt-5.5" in upgrade_records[0].getMessage()
    assert GPT6_ASTRA_DIRECT in upgrade_records[0].getMessage()


class TestUpgradeHelper:
    """Direct unit coverage of the shared helper the four agents call."""

    def test_retired_catalog_row_upgrades(self) -> None:
        assert common.upgrade_retired_model_id("grok-4.5") == GROK_46_DIRECT

    def test_upgrades_key_absent_from_catalog_upgrades(self) -> None:
        # gpt-4o has no catalog row at all; it is a plain UPGRADES key, and
        # its target is the VALUE row (round-4 re-review of C-P3 on #9989).
        assert common.upgrade_retired_model_id("gpt-4o") == GPT56_TERRA_DIRECT
        # A flagship-line key still upgrades to the flagship.
        assert common.upgrade_retired_model_id("gpt-5.5") == GPT6_ASTRA_DIRECT

    def test_active_row_unchanged(self) -> None:
        assert common.upgrade_retired_model_id("gpt-6-astra") == "gpt-6-astra"

    def test_unknown_unchanged(self) -> None:
        assert common.upgrade_retired_model_id("totally-new-model-2099") == (
            "totally-new-model-2099"
        )

    def test_empty_unchanged(self) -> None:
        assert common.upgrade_retired_model_id("") == ""


# ---------------------------------------------------------------------------
# Endpoint gating (finding O-P2a, round 2)
# ---------------------------------------------------------------------------

# agent class -> (base-URL env var, official endpoint host spelling, retired
# id, its upgrade target)
_ENDPOINT_CASES = [
    pytest.param(
        AnthropicAPIAgent,
        "ANTHROPIC_BASE_URL",
        "https://api.anthropic.com",
        "claude-fable-5",
        FABLE_51_DIRECT,
        id="anthropic",
    ),
    pytest.param(
        OpenAIAPIAgent,
        "OPENAI_BASE_URL",
        "https://api.openai.com",
        "gpt-5.5",
        GPT6_ASTRA_DIRECT,
        id="openai",
    ),
    pytest.param(
        GrokAgent,
        "XAI_BASE_URL",
        "https://api.x.ai",
        "grok-4-latest",
        GROK_46_DIRECT,
        id="grok",
    ),
    pytest.param(
        MistralAPIAgent,
        "MISTRAL_BASE_URL",
        "https://api.mistral.ai",
        "mistral-large-2411",
        MISTRAL_LARGE_DIRECT,
        id="mistral",
    ),
]


@pytest.mark.parametrize(
    ("agent_cls", "env_var", "official_host", "retired", "upgraded"), _ENDPOINT_CASES
)
@pytest.mark.parametrize("suffix", ["", "/v1", "/v1/", "/"], ids=["bare", "v1", "v1slash", "slash"])
def test_env_var_naming_the_official_endpoint_still_upgrades(
    agent_cls,
    env_var: str,
    official_host: str,
    retired: str,
    upgraded: str,
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every spelling of the official endpoint normalizes to the same URL, so
    the retired id must still be rewritten. Gating on raw env-var PRESENCE
    (the bug) makes each of these silently send the dead id."""
    monkeypatch.setenv(env_var, official_host + suffix)
    assert agent_cls(model=retired, api_key="test-key").model == upgraded


@pytest.mark.parametrize(
    ("agent_cls", "env_var", "official_host", "retired", "upgraded"), _ENDPOINT_CASES
)
def test_gateway_base_url_skips_the_upgrade(
    agent_cls,
    env_var: str,
    official_host: str,
    retired: str,
    upgraded: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real BYOK gateway may serve ids under its own meaning (issue #9304),
    so the id reaches it byte-for-byte."""
    monkeypatch.setenv(env_var, "http://localhost:8318/v1")
    agent = agent_cls(model=retired, api_key="test-key")
    assert agent.model == retired
    assert agent.base_url == "http://localhost:8318/v1"


def test_openai_upgrade_gate_is_separate_from_the_vibeproxy_routing_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_uses_official_openai_endpoint`` gates VibeProxy exact-chat routing
    and keeps its raw-env-var meaning: the proxy slice is contract-tested
    against an unconfigured client. Only the UPGRADE decision moved to the
    resolved-URL comparison, so the two disagree exactly here."""
    from aragora.agents.api_agents import openai as openai_mod

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
    agent = OpenAIAPIAgent(model="gpt-5.5", api_key="test-key")
    assert agent._uses_official_openai_endpoint is False
    assert openai_mod._targets_official_openai_endpoint() is True
    assert agent.model == GPT6_ASTRA_DIRECT


# ---------------------------------------------------------------------------
# Wire id is direct_id, never canonical_id (finding C-P3, round 2)
# ---------------------------------------------------------------------------


class TestWireIdIsTheDirectId:
    """``resolve_model_id()`` answers with a ``canonical_id`` -- the catalog's
    INTERNAL name for a row. Every native row in today's catalog happens to
    have ``canonical_id == direct_id``, so using the canonical spelling as the
    wire id works by coincidence; a row like Cohere's ``command-a-03-2025``
    (canonical) / ``command-a`` (direct) breaks it silently, sending an id no
    endpoint accepts.

    A synthetic row where the two genuinely differ is the only way to make
    that difference observable, so these tests inject one.
    """

    @pytest.fixture
    def split_id_row(self, monkeypatch: pytest.MonkeyPatch):
        from datetime import date

        from aragora.models import catalog as catalog_mod
        from aragora.models.catalog import ModelSpec

        row = ModelSpec(
            canonical_id="testfam-flagship-20990101",
            provider="testfam",
            family="testfam",
            direct_id="testfam-flagship",
            openrouter_id="testfam/testfam-flagship",
            input_per_mtok=1.0,
            output_per_mtok=2.0,
            context_window=100_000,
            max_output_tokens=8_000,
            release_date=date(2099, 1, 1),
        )
        retired = ModelSpec(
            canonical_id="testfam-old",
            provider="testfam",
            family="testfam",
            retired=True,
            direct_id="testfam-old",
            openrouter_id="testfam/testfam-old",
            input_per_mtok=1.0,
            output_per_mtok=2.0,
            context_window=100_000,
            max_output_tokens=8_000,
            release_date=date(2098, 1, 1),
        )
        patched_catalog = {
            **catalog_mod.CATALOG,
            row.canonical_id: row,
            retired.canonical_id: retired,
        }
        patched_index = dict(catalog_mod._ID_INDEX)
        for spec in (row, retired):
            for mid in spec.all_ids():
                patched_index[mid] = spec
        monkeypatch.setattr(catalog_mod, "CATALOG", patched_catalog)
        monkeypatch.setattr(catalog_mod, "_ID_INDEX", patched_index)
        return row

    def test_canonical_and_direct_really_differ(self, split_id_row) -> None:
        """Guard-rail: without this the assertions below pass vacuously."""
        assert split_id_row.canonical_id != split_id_row.direct_id

    def test_native_model_id_returns_the_direct_id(self, split_id_row) -> None:
        assert common.native_model_id("testfam-old") == "testfam-flagship"
        assert common.native_model_id("testfam-flagship-20990101") == "testfam-flagship"

    def test_upgrade_retired_model_id_returns_the_direct_id(self, split_id_row) -> None:
        from aragora.models.upgrade_map import resolve_model_id

        # The bare resolver still answers with the canonical spelling...
        assert resolve_model_id("testfam-old") == "testfam-flagship-20990101"
        # ...but the wire id the agent sends is the direct one.
        assert common.upgrade_retired_model_id("testfam-old") == "testfam-flagship"

    def test_unknown_spelling_is_still_returned_verbatim(self, split_id_row) -> None:
        assert common.native_model_id("testfam-model-from-the-future") == (
            "testfam-model-from-the-future"
        )
        assert common.native_model_id("") == ""

    def test_gemini_agent_sends_the_direct_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """gemini.py resolves its id at construction and that value is the
        wire id for generativelanguage.googleapis.com."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from aragora.models.catalog import spec_or_none

        agent = GeminiAgent(model="gemini-3.1-pro", api_key="test-key")
        spec = spec_or_none(agent.model)
        assert spec is not None
        assert agent.model == spec.direct_id
