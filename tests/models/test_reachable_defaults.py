"""Every model a default can reach must be a priced, active catalog row."""

import pytest
from aragora.models.catalog import spec_or_none
from aragora.models.upgrade_map import resolve_model_id

# Reviewer families PR 2 (Task 10) still needs to add a catalog row for /
# move the reviewer map for. Literal allow-list (NOT computed from
# spec_or_none) so a genuine regression in any OTHER reviewer/codex_default
# entry cannot silently mask itself as an expected failure -- computing the
# xfail predicate from the same spec_or_none(resolve_model_id(...)) check
# the test itself asserts would make every marked row un-failable and every
# unmarked row un-xfailable by construction, defeating the point of this
# reverse-completeness test.
#
# "claude", "openai", "grok" and "qwen" are here because their pinned slugs
# are RETIRED spellings (anthropic/claude-fable-5, openai/gpt-5.5,
# x-ai/grok-4.5, qwen/qwen3.7-max) that the raw assertion below now catches;
# "tencent"/"bytedance" have no catalog row at all. The map itself is a
# Tier-4 governance surface this PR must not touch, so the gap is recorded
# rather than fixed. strict=True means PR 2 cannot land its rewrite without
# deleting the family from this set.
_PR2_PENDING_FAMILIES = frozenset({"claude", "openai", "grok", "qwen", "tencent", "bytedance"})

# Same module, same PR-2 ownership, same treatment: _CODEX_DEFAULT_MODELS'
# first entry is the retired "gpt-5.5" spelling. Literal for the same reason
# _PR2_PENDING_FAMILIES is literal.
_PR2_PENDING_CODEX_MODELS = frozenset({"gpt-5.5"})

# Definers whose value is deliberately NOT a catalog id: a native provider's
# own model code, for a family the catalog carries only as an OpenRouter row
# (``ModelSpec.direct_id`` is a placeholder there, not a code the native
# endpoint would accept). The literal still has to RESOLVE to an active,
# priced row -- that is what keeps cost accounting honest -- but it is
# expected to have no catalog row of its own. The assertion below is written
# so the entry must be deleted from this dict the day the catalog gains a
# real native row for it.
_NATIVE_ID_EXEMPT = {
    "registry.qwen-cli": "native-provider model code; catalog carries only the OpenRouter row",
    "registry.deepseek-cli": "native-provider model code; catalog carries only the OpenRouter row",
    "registry.kimi-legacy": "native-provider model code; catalog carries only the OpenRouter row",
    "cli_agents.KIMI_CLI_DEFAULT_MODEL": (
        "native-provider model code; catalog carries only the OpenRouter row"
    ),
}


# PDB panel defaults (aragora/pdb/invoker_factory.py) that name a PUBLISHED
# provider snapshot id the catalog carries no row for at all -- so neither the
# raw spelling nor its resolution reaches a catalog row. Such an entry is
# still held to the priced half of this test's contract, against the PDB
# hand-written price table (``real_invoker._PRICE_PER_MTOK``), so the slot
# cannot silently bill at a default rate; it is exempted only from the
# "cataloged" half. Self-removing: the assertion below fails the day the
# catalog gains a row for the id.
_UNCATALOGED_PDB_DEFAULTS = {
    "invoker_factory.GROK_MODEL_DEFAULT": (
        "xAI publishes dated reasoning snapshots (docs.x.ai/developers/models) "
        "that the catalog does not enumerate; the grok_heterodox slot pins one "
        "deliberately after the 2026-04-22 'Model not found: grok-4.2' incident "
        "(PR #6441). Priced by a hand row in aragora/pdb/real_invoker.py."
    ),
}


def _reachable_defaults() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    from aragora.config import model_pins as mp

    for role in (
        "proposer",
        "critic",
        "synthesizer",
        "devils_advocate",
        "researcher",
        "reviewer",
        "quality_reviewer",
        "security_auditor",
        "compliance_auditor",
        "judge",
        "default",
    ):
        out.append((f"pins.{role}.direct", mp.direct_model_for_role(role)))
        out.append((f"pins.{role}.openrouter", mp.openrouter_alias_for_role(role)))
    from aragora.agents.model_selector import MODEL_PROFILES

    for name, prof in MODEL_PROFILES.items():
        out.append((f"profile.{name}", prof.model_id))
    from aragora.agents.api_agents import (
        anthropic,
        openai,
        gemini,
        grok,
        mistral,
        openai_compatible,
    )

    for mod in (anthropic, openai, gemini, grok, mistral):
        out.append((f"{mod.__name__}.DEFAULT_MODEL", getattr(mod, "DEFAULT_MODEL")))
    out.append(
        ("openai_compatible.DEFAULT_FALLBACK_MODEL", openai_compatible.DEFAULT_FALLBACK_MODEL)
    )
    from aragora.server.handlers.debates import cost_estimation

    for m in cost_estimation.DEFAULT_MODELS:
        out.append(("cost_estimation.DEFAULT_MODELS", m))
    from aragora.swarm import quorum_evidence as qe

    for fam, slug in qe._OPENROUTER_REVIEWER_MODELS.items():
        where = f"reviewer.{fam}"
        if fam in _PR2_PENDING_FAMILIES:
            out.append(
                pytest.param(
                    where,
                    slug,
                    marks=pytest.mark.xfail(strict=True, reason="PR 2 moves the reviewer map"),
                )
            )
        else:
            out.append((where, slug))
    for m in qe._CODEX_DEFAULT_MODELS:
        if m in _PR2_PENDING_CODEX_MODELS:
            out.append(
                pytest.param(
                    "codex_default",
                    m,
                    marks=pytest.mark.xfail(strict=True, reason="PR 2 moves the reviewer map"),
                )
            )
        else:
            out.append(("codex_default", m))

    # The three per-provider OpenRouter fallback maps. These live on the live
    # server path and were the last unmigrated model tables in the repo.
    from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS
    from aragora.server.handlers.agents import agents as agents_handler
    from aragora.server.stream import debate_executor

    for provider, slug in debate_executor._OPENROUTER_FALLBACK_MODELS.items():
        out.append((f"debate_executor.fallback.{provider}", slug))
    out.append(
        (
            "debate_executor.generic_fallback",
            debate_executor._OPENROUTER_GENERIC_FALLBACK_MODEL,
        )
    )
    for provider, slug in agents_handler._OPENROUTER_FALLBACK_MODELS.items():
        out.append((f"agents_handler.fallback.{provider}", slug))
    # Only the VALUES: the keys are deliberately legacy/retired spellings a
    # caller may still pin, and the point of the table is to route them to a
    # live model.
    for primary, slug in OPENROUTER_FALLBACK_MODELS.items():
        out.append((f"openrouter.fallback_for[{primary}]", slug))

    # Cold-start routing roster. Before the frontier refresh this list was
    # 100% retired spellings, so a cold-start debate could not see the
    # current frontier at all.
    from aragora.routing.provider_router import DEFAULT_PROVIDER_ORDER

    for m in DEFAULT_PROVIDER_ORDER:
        out.append(("provider_router.DEFAULT_PROVIDER_ORDER", m))

    # Native-provider entry points (see _NATIVE_ID_EXEMPT): listed so the gap
    # is named and pinned rather than merely absent from this test.
    import aragora.agents.api_agents.openrouter  # noqa: F401 - registers kimi-legacy
    import aragora.agents.cli_agents  # noqa: F401 - registers the CLI agents
    from aragora.agents.registry import AgentRegistry

    for agent_type in ("qwen-cli", "deepseek-cli", "kimi-legacy"):
        registered = AgentRegistry.get_spec(agent_type)
        assert registered is not None, f"{agent_type} is no longer registered"
        out.append((f"registry.{agent_type}", registered.default_model))

    # kimi-cli registers only under ARAGORA_ENABLE_KIMI_CLI, so its default is
    # read from the module constant rather than the registry -- otherwise the
    # one CLI default in this class would be the one this test cannot see.
    from aragora.agents.cli_agents import KIMI_CLI_DEFAULT_MODEL

    out.append(("cli_agents.KIMI_CLI_DEFAULT_MODEL", KIMI_CLI_DEFAULT_MODEL))

    # The seven hand-maintained tables PR 1's spec inventory missed, wired
    # to the catalog in the 2026-09-05 wave-3 pass. Most of them are keyed
    # BY model, so they define no default; these three name one.
    from aragora.documents.chunking.context_manager import ContextConfig, ContextManager
    from aragora.documents.chunking.token_counter import TokenCounter

    out.append(("context_manager.ContextConfig.model", ContextConfig().model))
    out.append(("token_counter.TokenCounter.default_model", TokenCounter().default_model))
    # recommend_model() hands a model id straight back to the caller for a
    # real run, so each branch's return value is a reachable default.
    _recommender = ContextManager()
    for total_tokens in (10_000, 60_000, 200_000, 600_000):
        for prefer_reasoning in (False, True):
            out.append(
                (
                    "context_manager.recommend_model",
                    _recommender.recommend_model(total_tokens, prefer_reasoning),
                )
            )

    # PDB panel defaults. A whole definer module this reverse test missed
    # until the 2026-09-05 gate-fix wave (finding C-P2 on #9989): the DeepSeek
    # slot was pinned to "deepseek/deepseek-v4-pro", a slug this repo's own
    # UPGRADES map declares dead, and OpenRouterAgent performs no
    # construction-time upgrade -- so the slot sent a dead id and had no
    # fallback entry to fall back to.
    from aragora.pdb import invoker_factory as pdb_invoker_factory

    for const in (
        "CLAUDE_MODEL_DEFAULT",
        "OPENAI_MODEL_DEFAULT",
        "GEMINI_MODEL_DEFAULT",
        "GROK_MODEL_DEFAULT",
        "DEEPSEEK_MODEL_DEFAULT",
        "KIMI_MODEL_DEFAULT",
        "QWEN_MODEL_DEFAULT",
        "MISTRAL_MODEL_DEFAULT",
    ):
        out.append((f"invoker_factory.{const}", getattr(pdb_invoker_factory, const)))
    return out


@pytest.mark.parametrize("where,model_id", _reachable_defaults())
def test_reachable_default_is_priced_and_active(where: str, model_id: str) -> None:
    raw = spec_or_none(model_id)
    if where in _UNCATALOGED_PDB_DEFAULTS:
        from aragora.pdb.real_invoker import _PRICE_PER_MTOK

        assert raw is None and spec_or_none(resolve_model_id(model_id)) is None, (
            f"{where}: {model_id!r} now resolves to a catalog row -- drop it "
            f"from _UNCATALOGED_PDB_DEFAULTS ({_UNCATALOGED_PDB_DEFAULTS[where]})"
        )
        rates = _PRICE_PER_MTOK.get(model_id)
        assert rates is not None and rates[0] > 0 and rates[1] > 0, (
            f"{where}: {model_id!r} has neither a catalog row nor a PDB price "
            "row, so the slot bills at a default rate"
        )
        return
    if where in _NATIVE_ID_EXEMPT:
        assert raw is None, (
            f"{where}: {model_id!r} now has a catalog row of its own -- "
            f"drop it from _NATIVE_ID_EXEMPT ({_NATIVE_ID_EXEMPT[where]})"
        )
    # The raw spelling must not itself be a retired row. Without this,
    # "not spec.retired" below is unreachable and the test cannot fail on the
    # condition it names: resolve_model_id() returns an active row on every
    # branch (UPGRADES targets are asserted active in test_upgrade_map,
    # branch 2 returns an active row, branch 3 returns a family frontier), so
    # a definer literally pinned to a retired id passed silently.
    assert raw is None or not raw.retired, (
        f"{where}: {model_id!r} is a retired spelling; it only passes because "
        f"resolve_model_id() upgrades it to {resolve_model_id(model_id)!r}"
    )
    spec = spec_or_none(resolve_model_id(model_id))
    assert spec is not None, f"{where}: {model_id!r} has no catalog row"
    assert not spec.retired, f"{where}: {model_id!r} is retired"
    assert spec.input_per_mtok > 0 and spec.output_per_mtok > 0, f"{where}: {model_id!r} unpriced"
