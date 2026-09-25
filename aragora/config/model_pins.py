"""
Canonical frontier-model pin registry.

All code that needs a "best available" model for a given role should import
constants from this module instead of hardcoding IDs. The goal is:

1. One place to bump the frontier (Opus 4.8 -> Opus 5, GPT 5.5 -> 5.6, etc.)
2. OpenRouter aliases are the default transport so a missing direct-provider
   key never blocks functionality. Set ARAGORA_ROUTE_THROUGH_OPENROUTER=true
   to force every call through OpenRouter even if a direct key is present.
3. Direct-provider IDs are still exposed for code paths that prefer to hit
   the native API when a key is available and the router allows it.

Naming convention:
- ``*_VIA_OPENROUTER`` -> the alias you pass to ``OpenRouterAgent``
  (e.g. ``anthropic/claude-opus-5``).
- ``*_DIRECT``         -> the raw model ID the native provider expects
  (e.g. ``claude-opus-5``).

Role-keyed helpers (``frontier_model_for_role``, ``openrouter_alias_for_role``)
return the best pin for a debate role (proposer, critic, synthesizer, etc.).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Final, Literal

from aragora.config.secrets import get_secret_presence, is_secret_presence_available

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Frontier pins (user-requested floor: Opus 5 / GPT 5.5 / Gemini 3.1 Pro)
# -----------------------------------------------------------------------------

# Anthropic Claude Opus 5 - top-tier reasoning, debate, synthesis. Same
# economics as Opus 4.8 ($5/$25), so this bump costs nothing per call.
# NOTE: adopted on release day (2026-07-24) by explicit operator direction;
# the 14-day availability rule was waived for this bump. See the soak comment
# on the claude-opus-5 spec in aragora/models/catalog.py.
OPUS_5_DIRECT: Final = "claude-opus-5"
OPUS_5_VIA_OPENROUTER: Final = "anthropic/claude-opus-5"

# Anthropic Claude Opus 4.8 - previous frontier. Deliberately NOT re-pointed at
# Opus 5: it is still Active upstream and is Opus 5's documented fallback target
# for cyber-classifier refusals, so this constant must keep naming the real 4.8.
OPUS_48_DIRECT: Final = "claude-opus-4-8"
OPUS_48_VIA_OPENROUTER: Final = "anthropic/claude-opus-4.8"

# Anthropic Claude Fable 5 - Mythos-class flagship at 2x Opus 5 price
# ($10/$50 vs $5/$25). Pinned where quality-per-call dominates volume: judge
# and audit roles here, plus the claude CLI agent default (subscription-priced
# on that surface, so the 2x API rate does not multiply across bulk rounds).
# API-billed bulk debate roles stay on Opus 5 by design.
FABLE_5_DIRECT: Final = "claude-fable-5"
FABLE_5_VIA_OPENROUTER: Final = "anthropic/claude-fable-5"
# Backwards-compatible constant names for callers that have not migrated yet.
OPUS_47_DIRECT: Final = OPUS_48_DIRECT
OPUS_47_VIA_OPENROUTER: Final = OPUS_48_VIA_OPENROUTER

# OpenAI GPT-5.6 Sol - same price as GPT-5.5 ($5/$30), strictly better
# benchmarks (Terminal-Bench 2.1 88.8 vs 82.7). The Codex-CLI reviewer
# harness deliberately stays on gpt-5.5 until Sol passes the 14-day
# availability rule (#9069) — do not route quorum evidence through a
# day-0 model.
GPT56_SOL_DIRECT: Final = "gpt-5.6-sol"
GPT56_SOL_VIA_OPENROUTER: Final = "openai/gpt-5.6-sol"

# OpenAI GPT-5.5 - previous flagship; still the reviewer-harness pin.
GPT55_DIRECT: Final = "gpt-5.5"
GPT55_VIA_OPENROUTER: Final = "openai/gpt-5.5"
# Backwards-compatible constant names for callers that have not migrated yet.
GPT54_DIRECT: Final = GPT55_DIRECT
GPT54_VIA_OPENROUTER: Final = GPT55_VIA_OPENROUTER

# Google Gemini 3.1 Pro - top-tier long-context + multimodal
GEMINI_31_PRO_DIRECT: Final = "gemini-3.1-pro"
GEMINI_31_PRO_VIA_OPENROUTER: Final = "google/gemini-3.1-pro-preview"

# xAI Grok 4.5 - contrarian / contrarian-by-design agent. The OpenRouter path
# stays on 4.5 until Grok 4.6 completes its repository soak; the direct-provider
# ``grok-4-latest`` alias remains unchanged.
GROK_4_DIRECT: Final = "grok-4-latest"
GROK_4_VIA_OPENROUTER: Final = "x-ai/grok-4.5"

# Mistral Large (latest) - European provider diversity
MISTRAL_LARGE_DIRECT: Final = "mistral-large-2512"
MISTRAL_LARGE_VIA_OPENROUTER: Final = "mistralai/mistral-large-2512"


# -----------------------------------------------------------------------------
# Canonical-metrics + legacy underscored aliases
# -----------------------------------------------------------------------------
#
# ``docs/status/claims/canonical_metrics.yaml`` and
# ``scripts/check_canonical_metrics.py`` look for the underscored
# frontier names (``OPUS_4_7``, ``GPT_5_4``, ``GEMINI_3_1_PRO``).
# These map to the same direct-provider IDs as the ``*_DIRECT``
# constants above; expose them at module scope so the security
# canonical-metrics gate can see that the frontier floor is honored.
OPUS_4_7: Final = OPUS_47_DIRECT
OPUS_4_8: Final = OPUS_48_DIRECT
OPUS_5: Final = OPUS_5_DIRECT
GPT_5_4: Final = GPT55_DIRECT
GEMINI_3_1_PRO: Final = GEMINI_31_PRO_DIRECT


# -----------------------------------------------------------------------------
# Frontier bundle per debate role
# -----------------------------------------------------------------------------

Role = Literal[
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
]


@dataclass(frozen=True)
class _RolePin:
    """Preferred frontier pin for a role, expressed both as direct and OpenRouter IDs."""

    direct: str
    openrouter: str


_ROLE_TO_PIN: Final[dict[Role, _RolePin]] = {
    # Anthropic leads on adversarial reasoning, nuance, and long-form synthesis,
    # so it is the default for the core debate roles.
    "proposer": _RolePin(OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER),
    "critic": _RolePin(OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER),
    "synthesizer": _RolePin(OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER),
    "devils_advocate": _RolePin(GROK_4_DIRECT, GROK_4_VIA_OPENROUTER),
    "researcher": _RolePin(GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER),
    # Reviewer routing holds gpt-5.5 until Sol clears the 14-day availability
    # rule (public Jul 9 -> eligible Jul 23); flipping this pin early was a
    # convergent review finding on #9075.
    "reviewer": _RolePin(GPT55_DIRECT, GPT55_VIA_OPENROUTER),
    "quality_reviewer": _RolePin(OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER),
    "security_auditor": _RolePin(FABLE_5_DIRECT, FABLE_5_VIA_OPENROUTER),
    "compliance_auditor": _RolePin(FABLE_5_DIRECT, FABLE_5_VIA_OPENROUTER),
    "judge": _RolePin(FABLE_5_DIRECT, FABLE_5_VIA_OPENROUTER),
    "default": _RolePin(OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER),
}


# -----------------------------------------------------------------------------
# Routing policy
# -----------------------------------------------------------------------------


def route_through_openrouter() -> bool:
    """Force every frontier call through OpenRouter regardless of direct keys.

    Enabled when ``ARAGORA_ROUTE_THROUGH_OPENROUTER`` is truthy OR when no
    direct Anthropic key is set (so the benchmark never blocks on a missing
    provider key).
    """
    forced = os.environ.get("ARAGORA_ROUTE_THROUGH_OPENROUTER", "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return True

    # Auto-fallback: no direct Anthropic key -> OpenRouter becomes primary.
    if not is_secret_presence_available(get_secret_presence("ANTHROPIC_API_KEY")):
        return True

    return False


def frontier_model_for_role(role: Role = "default") -> str:
    """Return the best frontier model ID for a role.

    If OpenRouter routing is forced (see :func:`route_through_openrouter`),
    returns the OpenRouter alias so callers can pass it straight to
    ``OpenRouterAgent``. Otherwise returns the direct-provider ID.
    """
    pin = _ROLE_TO_PIN.get(role, _ROLE_TO_PIN["default"])
    return pin.openrouter if route_through_openrouter() else pin.direct


def openrouter_alias_for_role(role: Role = "default") -> str:
    """Return the OpenRouter alias for a role, regardless of routing policy."""
    pin = _ROLE_TO_PIN.get(role, _ROLE_TO_PIN["default"])
    return pin.openrouter


def direct_model_for_role(role: Role = "default") -> str:
    """Return the direct-provider model ID for a role, regardless of routing policy."""
    pin = _ROLE_TO_PIN.get(role, _ROLE_TO_PIN["default"])
    return pin.direct


__all__ = [
    "FABLE_5_DIRECT",
    "FABLE_5_VIA_OPENROUTER",
    "GPT56_SOL_DIRECT",
    "GPT56_SOL_VIA_OPENROUTER",
    "OPUS_5_DIRECT",
    "OPUS_5_VIA_OPENROUTER",
    "OPUS_48_DIRECT",
    "OPUS_48_VIA_OPENROUTER",
    "OPUS_47_DIRECT",
    "OPUS_47_VIA_OPENROUTER",
    "GPT55_DIRECT",
    "GPT55_VIA_OPENROUTER",
    "GPT54_DIRECT",
    "GPT54_VIA_OPENROUTER",
    "GEMINI_31_PRO_DIRECT",
    "GEMINI_31_PRO_VIA_OPENROUTER",
    "GROK_4_DIRECT",
    "GROK_4_VIA_OPENROUTER",
    "MISTRAL_LARGE_DIRECT",
    "MISTRAL_LARGE_VIA_OPENROUTER",
    "OPUS_4_7",
    "OPUS_4_8",
    "OPUS_5",
    "GPT_5_4",
    "GEMINI_3_1_PRO",
    "Role",
    "route_through_openrouter",
    "frontier_model_for_role",
    "openrouter_alias_for_role",
    "direct_model_for_role",
]
