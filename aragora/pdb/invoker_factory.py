"""Factory for building the real :class:`aragora.pdb.real_invoker.RealProviderInvoker`.

Responsibilities:

- Read the environment (core keys ``ANTHROPIC_API_KEY`` and
  ``OPENAI_API_KEY``; optional heterodox/regulatory keys
  ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` / ``XAI_API_KEY`` /
  ``GROK_API_KEY`` / ``OPENROUTER_API_KEY`` / ``MISTRAL_API_KEY``) and
  instantiate one agent per family for which a key is present.
- Mark each slot as **unavailable** whenever its family's API key is
  missing, so the executor surfaces the slot in ``degrade_reasons``
  instead of failing a whole brief for an optional lens.
- **Fail closed** when both core keys are missing — without either core
  slot there is no meaningful heterogeneous brief.

The factory is deliberately thin; rate-limit retries, caching, and
sophisticated model selection live inside the base agent classes
(``resilience.py`` / ``rate_limiter.py``). See
``aragora.pdb.real_invoker`` for the per-call logic.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from aragora.config.model_pins import FABLE_51_DIRECT
from aragora.models import CATALOG
from aragora.pdb.panel_config import PDBPanelConfig, load_panel_config
from aragora.pdb.protocol import ProviderInvoker
from aragora.pdb.real_invoker import (
    FAMILY_CLAUDE,
    FAMILY_DEEPSEEK,
    FAMILY_GEMINI,
    FAMILY_GPT,
    FAMILY_GROK,
    FAMILY_KIMI,
    FAMILY_MISTRAL,
    FAMILY_QWEN,
    RealProviderInvoker,
)

logger = logging.getLogger(__name__)

__all__ = [
    "InvokerFactoryError",
    "build_default_invoker",
    "default_invoker_factory",
    "unavailable_slots_for",
]


# ---------------------------------------------------------------------------
# Env-var names
# ---------------------------------------------------------------------------


ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
OPENAI_KEY_ENV = "OPENAI_API_KEY"
GEMINI_KEY_ENV = "GEMINI_API_KEY"
GOOGLE_KEY_ENV = "GOOGLE_API_KEY"
GROK_KEY_ENV = "GROK_API_KEY"
XAI_KEY_ENV = "XAI_API_KEY"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
MISTRAL_KEY_ENV = "MISTRAL_API_KEY"

CLAUDE_MODEL_ENV = "ARAGORA_PDB_CLAUDE_MODEL"
OPENAI_MODEL_ENV = "ARAGORA_PDB_OPENAI_MODEL"
GEMINI_MODEL_ENV = "ARAGORA_PDB_GEMINI_MODEL"
GROK_MODEL_ENV = "ARAGORA_PDB_GROK_MODEL"
DEEPSEEK_MODEL_ENV = "ARAGORA_PDB_DEEPSEEK_MODEL"
KIMI_MODEL_ENV = "ARAGORA_PDB_KIMI_MODEL"
QWEN_MODEL_ENV = "ARAGORA_PDB_QWEN_MODEL"
MISTRAL_MODEL_ENV = "ARAGORA_PDB_MISTRAL_MODEL"

# Same class as OPENAI_MODEL_DEFAULT below: "claude-sonnet-4-6" is an
# UPGRADES key, so AnthropicAPIAgent rewrote the PDB Claude slot at
# construction and the slot's identity (and its price, ~3x) depended on that
# rewrite rather than on what this constant says (finding C-P3 on #9989).
# Pinned explicitly to the canonical Claude frontier -- Fable everywhere
# Claude is used, per the frontier-model-refresh founder decision -- so the
# slot names the model it actually runs.
CLAUDE_MODEL_DEFAULT = FABLE_51_DIRECT
# Same class as DEEPSEEK_MODEL_DEFAULT below: "gpt-5.5" is a RETIRED catalog
# row, so pinning it here made the gpt_core slot depend on
# OpenAIAPIAgent's construction-time upgrade to stay callable at all, and
# priced the slot at the retired row's rate. Derived from the catalog's
# current OpenAI frontier instead (finding C-P2 on #9989, same wave).
OPENAI_MODEL_DEFAULT = CATALOG["gpt-6-astra"].direct_id
GEMINI_MODEL_DEFAULT = "gemini-3.1-pro-preview"
# Grok default pins the reasoning-capable 4.20 snapshot. The prior default
# ``grok-4.2`` was never a valid xAI model id and every Mode 3 brief that
# tried to use the ``grok_heterodox`` slot failed with
# ``Model not found: grok-4.2``. ``grok-4.20-0309-reasoning`` is published
# on xAI's models page (https://docs.x.ai/developers/models) and matches
# the panel's role — the heterodox slot does adversarial code review.
GROK_MODEL_DEFAULT = "grok-4.20-0309-reasoning"
# The mission brief anchors these to specific provider model ids.
# Derived from the catalog rather than written as a literal: the bare
# "deepseek/deepseek-v4-pro" spelling this used to carry is an UPGRADES key
# (i.e. a slug this repo declares dead), OpenRouterAgent does no
# retired-id upgrade at construction, and the fallback table had no entry
# for it -- so the PDB DeepSeek slot sent a dead slug and, on retry
# exhaustion, raised instead of falling back (finding C-P2 on #9989).
DEEPSEEK_MODEL_DEFAULT = CATALOG["deepseek-v4-pro-0813"].openrouter_id
KIMI_MODEL_DEFAULT = CATALOG["kimi-k3"].openrouter_id
QWEN_MODEL_DEFAULT = CATALOG["qwen3.8-2.4t-a95b"].openrouter_id
MISTRAL_MODEL_DEFAULT = "mistral-large-2512"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvokerFactoryError(RuntimeError):
    """Raised when the factory cannot build a viable invoker.

    The HTTP layer catches this and surfaces a 503 with the message so
    the UI can explain which API key is missing rather than fail with
    a generic ``NotImplementedError``.
    """


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def unavailable_slots_for(
    *,
    config: PDBPanelConfig | None = None,
    have_claude: bool,
    have_gpt: bool,
    have_gemini: bool = False,
    have_grok: bool = False,
    have_openrouter: bool = False,
    have_mistral: bool = False,
) -> frozenset[str]:
    """Return the set of slot ids that the invoker must mark unavailable.

    A slot is unavailable when its family has no usable credential:

    - ``claude`` family requires ``have_claude`` (``ANTHROPIC_API_KEY``)
    - ``gpt`` family requires ``have_gpt`` (``OPENAI_API_KEY``)
    - ``gemini`` family requires ``have_gemini``
      (``GEMINI_API_KEY`` or ``GOOGLE_API_KEY``)
    - ``grok`` family requires ``have_grok``
      (``GROK_API_KEY`` or ``XAI_API_KEY``)
    - ``deepseek`` / ``kimi`` / ``qwen`` share ``have_openrouter``
      (``OPENROUTER_API_KEY``) because all three are routed through
      OpenRouter
    - ``mistral`` family requires ``have_mistral``
      (``MISTRAL_API_KEY``)

    Unknown families are marked unavailable defensively so an
    accidental typo in the yaml surfaces as a degrade reason rather
    than a silent pass-through.
    """
    cfg = config if config is not None else load_panel_config()
    unavailable: set[str] = set()
    family_availability: dict[str, bool] = {
        FAMILY_CLAUDE: have_claude,
        FAMILY_GPT: have_gpt,
        FAMILY_GEMINI: have_gemini,
        FAMILY_GROK: have_grok,
        FAMILY_DEEPSEEK: have_openrouter,
        FAMILY_KIMI: have_openrouter,
        FAMILY_QWEN: have_openrouter,
        FAMILY_MISTRAL: have_mistral,
    }
    for slot_id, slot in cfg.slots.items():
        if slot.family not in family_availability:
            unavailable.add(slot_id)
            continue
        if not family_availability[slot.family]:
            unavailable.add(slot_id)
    return frozenset(unavailable)


def build_default_invoker(
    *,
    config: PDBPanelConfig | None = None,
    env: dict[str, str] | None = None,
    anthropic_agent_factory: Callable[[str, str | None], Any] | None = None,
    openai_agent_factory: Callable[[str, str | None], Any] | None = None,
    gemini_agent_factory: Callable[[str, str | None], Any] | None = None,
    grok_agent_factory: Callable[[str, str | None], Any] | None = None,
    openrouter_agent_factory: Callable[[str, str | None], Any] | None = None,
    mistral_agent_factory: Callable[[str, str | None], Any] | None = None,
) -> RealProviderInvoker:
    """Construct the process-wide :class:`RealProviderInvoker`.

    Parameters
    ----------
    config:
        Optional panel config. If ``None`` we load the committed
        default via :func:`aragora.pdb.panel_config.load_panel_config`.
    env:
        Optional env mapping — tests pass this so the factory is
        deterministic without touching real ``os.environ``. Defaults to
        ``os.environ``.
    anthropic_agent_factory / openai_agent_factory / gemini_agent_factory
    / grok_agent_factory / openrouter_agent_factory / mistral_agent_factory:
        Optional factories that build the underlying agents. Injected
        by tests so real network-capable agents don't get instantiated.
        Each takes ``(model, api_key)`` and returns any object that
        satisfies the :class:`_AgentLike` contract used by
        :class:`RealProviderInvoker`. The ``openrouter_agent_factory``
        is invoked once per OpenRouter-backed family (deepseek / kimi
        / qwen) with the family-specific model id.

    Raises
    ------
    InvokerFactoryError:
        When neither ``ANTHROPIC_API_KEY`` nor ``OPENAI_API_KEY`` is
        set. Without either core slot the executor's heterogeneity
        floor would fail closed on every brief anyway, so we fail
        closed first with a clearer error.
    """
    environment = env if env is not None else dict(os.environ)
    anthropic_key = (environment.get(ANTHROPIC_KEY_ENV) or "").strip() or None
    openai_key = (environment.get(OPENAI_KEY_ENV) or "").strip() or None
    gemini_key = (
        (environment.get(GEMINI_KEY_ENV) or "").strip()
        or (environment.get(GOOGLE_KEY_ENV) or "").strip()
        or None
    )
    grok_key = (
        (environment.get(XAI_KEY_ENV) or "").strip()
        or (environment.get(GROK_KEY_ENV) or "").strip()
        or None
    )
    openrouter_key = (environment.get(OPENROUTER_KEY_ENV) or "").strip() or None
    mistral_key = (environment.get(MISTRAL_KEY_ENV) or "").strip() or None

    if anthropic_key is None and openai_key is None:
        raise InvokerFactoryError(
            "Cannot build PDB invoker: neither ANTHROPIC_API_KEY nor "
            "OPENAI_API_KEY is set. Mode 3 requires at least one core "
            "model family; set both for heterogeneous cross-verification."
        )

    claude_agent = None
    gpt_agent = None
    gemini_agent = None
    grok_agent = None
    deepseek_agent = None
    kimi_agent = None
    qwen_agent = None
    mistral_agent = None

    if anthropic_key is not None:
        model = _resolve_model(environment, CLAUDE_MODEL_ENV, CLAUDE_MODEL_DEFAULT)
        claude_agent = _build_claude_agent(
            model=model,
            api_key=anthropic_key,
            factory=anthropic_agent_factory,
        )
    else:
        logger.info("pdb.invoker_factory: ANTHROPIC_API_KEY unset; claude_core slot unavailable")

    if openai_key is not None:
        model = _resolve_model(environment, OPENAI_MODEL_ENV, OPENAI_MODEL_DEFAULT)
        gpt_agent = _build_openai_agent(
            model=model,
            api_key=openai_key,
            factory=openai_agent_factory,
        )
    else:
        logger.info("pdb.invoker_factory: OPENAI_API_KEY unset; gpt_core slot unavailable")

    if gemini_key is not None:
        model = _resolve_model(environment, GEMINI_MODEL_ENV, GEMINI_MODEL_DEFAULT)
        gemini_agent = _build_gemini_agent(
            model=model,
            api_key=gemini_key,
            factory=gemini_agent_factory,
        )
    else:
        logger.info(
            "pdb.invoker_factory: GEMINI_API_KEY/GOOGLE_API_KEY unset; "
            "gemini_heterodox slot unavailable"
        )

    if grok_key is not None:
        model = _resolve_model(environment, GROK_MODEL_ENV, GROK_MODEL_DEFAULT)
        grok_agent = _build_grok_agent(
            model=model,
            api_key=grok_key,
            factory=grok_agent_factory,
        )
    else:
        logger.info(
            "pdb.invoker_factory: XAI_API_KEY/GROK_API_KEY unset; grok_heterodox slot unavailable"
        )

    if openrouter_key is not None:
        deepseek_model = _resolve_model(environment, DEEPSEEK_MODEL_ENV, DEEPSEEK_MODEL_DEFAULT)
        kimi_model = _resolve_model(environment, KIMI_MODEL_ENV, KIMI_MODEL_DEFAULT)
        qwen_model = _resolve_model(environment, QWEN_MODEL_ENV, QWEN_MODEL_DEFAULT)
        deepseek_agent = _build_openrouter_agent(
            model=deepseek_model,
            api_key=openrouter_key,
            factory=openrouter_agent_factory,
            name="pdb-deepseek",
        )
        kimi_agent = _build_openrouter_agent(
            model=kimi_model,
            api_key=openrouter_key,
            factory=openrouter_agent_factory,
            name="pdb-kimi",
        )
        qwen_agent = _build_openrouter_agent(
            model=qwen_model,
            api_key=openrouter_key,
            factory=openrouter_agent_factory,
            name="pdb-qwen",
        )
    else:
        logger.info(
            "pdb.invoker_factory: OPENROUTER_API_KEY unset; "
            "deepseek/kimi/qwen heterodox slots unavailable"
        )

    if mistral_key is not None:
        model = _resolve_model(environment, MISTRAL_MODEL_ENV, MISTRAL_MODEL_DEFAULT)
        mistral_agent = _build_mistral_agent(
            model=model,
            api_key=mistral_key,
            factory=mistral_agent_factory,
        )
    else:
        logger.info(
            "pdb.invoker_factory: MISTRAL_API_KEY unset; mistral_regulatory slot unavailable"
        )

    unavailable = unavailable_slots_for(
        config=config,
        have_claude=claude_agent is not None,
        have_gpt=gpt_agent is not None,
        have_gemini=gemini_agent is not None,
        have_grok=grok_agent is not None,
        have_openrouter=openrouter_key is not None,
        have_mistral=mistral_agent is not None,
    )

    return RealProviderInvoker(
        claude=claude_agent,
        gpt=gpt_agent,
        gemini=gemini_agent,
        grok=grok_agent,
        deepseek=deepseek_agent,
        kimi=kimi_agent,
        qwen=qwen_agent,
        mistral=mistral_agent,
        unavailable_slots=unavailable,
    )


def _resolve_model(env: dict[str, str], env_var: str, default: str) -> str:
    """Return the env-overridden model id, falling back to ``default``."""
    raw = env.get(env_var, default)
    if raw is None:
        return default
    stripped = raw.strip()
    return stripped or default


def default_invoker_factory() -> ProviderInvoker:
    """Zero-arg factory suitable for :class:`aragora.pdb.worker.JobRequest`.

    Each call returns a freshly constructed invoker. The underlying
    agent classes cache their own credentials at construction time so
    the overhead per call is small.
    """
    return build_default_invoker()


# ---------------------------------------------------------------------------
# Agent construction — isolated to ease test injection
# ---------------------------------------------------------------------------


def _build_claude_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
) -> Any:
    if factory is not None:
        agent = factory(model, api_key)
    else:
        # Imports live inside the function so test-time monkeypatching and
        # env-less import of ``aragora.pdb.invoker_factory`` stay cheap.
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent(
            name="pdb-claude",
            model=model,
            role="proposer",
            api_key=api_key,
        )
    # Mode 3 review prompts are repo-grounded and already carry the local PR
    # context. Anthropic's generic URL-triggered web search heuristic can
    # misclassify these prompts as web tasks because diff excerpts often include
    # URLs, which inflates latency on a required core slot.
    if hasattr(agent, "enable_web_search"):
        agent.enable_web_search = False
    return agent


def _build_openai_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
) -> Any:
    if factory is not None:
        return factory(model, api_key)
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    return OpenAIAPIAgent(
        name="pdb-openai",
        model=model,
        role="proposer",
        api_key=api_key,
    )


def _build_gemini_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
) -> Any:
    if factory is not None:
        return factory(model, api_key)
    from aragora.agents.api_agents.gemini import GeminiAgent

    return GeminiAgent(
        name="pdb-gemini",
        model=model,
        role="proposer",
        api_key=api_key,
        # Disable automatic OpenRouter fallback inside the agent: the
        # invoker's own error surface + executor degrade path already
        # handle credential loss, and double-fallback obscures which
        # family actually produced the text.
        enable_fallback=False,
    )


def _build_grok_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
) -> Any:
    if factory is not None:
        return factory(model, api_key)
    from aragora.agents.api_agents.grok import GrokAgent

    return GrokAgent(
        name="pdb-grok",
        model=model,
        role="proposer",
        api_key=api_key,
        enable_fallback=False,
    )


def _build_openrouter_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
    name: str,
) -> Any:
    if factory is not None:
        return factory(model, api_key)
    # The base :class:`OpenRouterAgent` reads ``OPENROUTER_API_KEY`` via
    # :func:`get_api_key`; to keep the invoker's env-passthrough
    # contract honest we temporarily export the key for this
    # construction only.
    from aragora.agents.api_agents.openrouter import OpenRouterAgent

    previous = os.environ.get(OPENROUTER_KEY_ENV)
    try:
        os.environ[OPENROUTER_KEY_ENV] = api_key
        return OpenRouterAgent(
            name=name,
            model=model,
            role="proposer",
        )
    finally:
        if previous is None:
            # Don't leak the credential back out if nothing was set.
            os.environ.pop(OPENROUTER_KEY_ENV, None)
        else:
            os.environ[OPENROUTER_KEY_ENV] = previous


def _build_mistral_agent(
    *,
    model: str,
    api_key: str,
    factory: Callable[[str, str | None], Any] | None,
) -> Any:
    if factory is not None:
        return factory(model, api_key)
    from aragora.agents.api_agents.mistral import MistralAPIAgent

    return MistralAPIAgent(
        name="pdb-mistral",
        model=model,
        role="proposer",
        api_key=api_key,
        enable_fallback=False,
    )
