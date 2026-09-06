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

Values derive from ``aragora.models.catalog``; bump the catalog, not this
file.

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

from aragora.config.secrets import get_secret_presence
from aragora.models.catalog import CATALOG as _CATALOG

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Frontier pins, derived from aragora.models.catalog.CATALOG
# (frontier-model-refresh, 2026-09-04)
# -----------------------------------------------------------------------------


def _pin(canonical_id: str) -> tuple[str, str]:
    """Return (direct_id, openrouter_id) for a catalog row."""
    spec = _CATALOG[canonical_id]
    return spec.direct_id, spec.openrouter_id


# Anthropic Claude Fable 5.1 - Mythos-class flagship, the frontier pick for
# every Claude role (debate roles, judge/audit roles, and the claude CLI
# agent default per the 2026-09-04 frontier-model-refresh).
FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER = _pin("claude-fable-5-1")

# Anthropic Claude Opus 5 - general fallback model. Same economics as Opus
# 4.8 ($5/$25), so this bump costs nothing per call.
# NOTE: adopted on release day (2026-07-24) by explicit operator direction;
# the 14-day availability rule was waived for this bump. See the soak comment
# on the claude-opus-5 spec in aragora/models/catalog.py.
OPUS_5_DIRECT, OPUS_5_VIA_OPENROUTER = _pin("claude-opus-5")

# Anthropic Claude Opus 4.8 - refusal-fallback model. Deliberately NOT
# re-pointed at Opus 5 or Fable 5.1: it is still Active upstream and is the
# documented fallback target for cyber-classifier refusals, so this constant
# must keep naming the real 4.8.
OPUS_48_DIRECT, OPUS_48_VIA_OPENROUTER = _pin("claude-opus-4-8")

# OpenAI GPT-6 Astra - frontier pick for every OpenAI role, including the
# merge-gate reviewer duty. This is a one-time override of the 14-day
# reviewer-availability rule in #9069 (Astra released 2026-09-03; recorded
# on #9069).
GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER = _pin("gpt-6-astra")

# OpenAI GPT-5.6 Terra - cheap/bulk-route sibling of Astra.
GPT56_TERRA_DIRECT, GPT56_TERRA_VIA_OPENROUTER = _pin("gpt-5.6-terra")

# Google Gemini 3.1 Pro - top-tier long-context + multimodal; the researcher
# role default. ``gemini-3.1-pro-preview`` is the real Gemini API code (the
# bare "gemini-3.1-pro" spelling is not a valid direct-provider id).
GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER = _pin("gemini-3.1-pro-preview")

# Google Gemini 3.8 Flash - cheap tier, added alongside Gemini 3.1 Pro.
GEMINI_38_FLASH_DIRECT, GEMINI_38_FLASH_VIA_OPENROUTER = _pin("gemini-3.8-flash")

# xAI Grok 4.6 - contrarian / devil's-advocate role default.
GROK_46_DIRECT, GROK_46_VIA_OPENROUTER = _pin("grok-4.6")

# Mistral Medium (2604) - European provider diversity, fallback-family
# flagship.
MISTRAL_MEDIUM_DIRECT, MISTRAL_MEDIUM_VIA_OPENROUTER = _pin("mistral-medium-2604")

# Mistral Large (2512) - kept resolvable/priced.
MISTRAL_LARGE_DIRECT, MISTRAL_LARGE_VIA_OPENROUTER = _pin("mistral-large-2512")


# -----------------------------------------------------------------------------
# Back-compat names (kept for importers and the canonical-metrics claim).
# They now point at the frontier ids above.
# -----------------------------------------------------------------------------
FABLE_5_DIRECT, FABLE_5_VIA_OPENROUTER = FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER
GPT56_SOL_DIRECT, GPT56_SOL_VIA_OPENROUTER = GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER
GPT55_DIRECT, GPT55_VIA_OPENROUTER = GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER
GPT54_DIRECT, GPT54_VIA_OPENROUTER = GPT55_DIRECT, GPT55_VIA_OPENROUTER
GROK_4_DIRECT, GROK_4_VIA_OPENROUTER = GROK_46_DIRECT, GROK_46_VIA_OPENROUTER
OPUS_47_DIRECT, OPUS_47_VIA_OPENROUTER = OPUS_48_DIRECT, OPUS_48_VIA_OPENROUTER


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
    # Claude Fable 5.1 leads on adversarial reasoning, nuance, and long-form
    # synthesis, so it is the default for the core debate and audit roles.
    "proposer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "critic": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "synthesizer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "devils_advocate": _RolePin(GROK_46_DIRECT, GROK_46_VIA_OPENROUTER),
    "researcher": _RolePin(GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER),
    # Reviewer routing pins GPT-6 Astra as of the 2026-09-04 frontier-model
    # refresh -- a one-time override of the 14-day reviewer-availability rule
    # (Astra released 2026-09-03; recorded on #9069).
    "reviewer": _RolePin(GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER),
    "quality_reviewer": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "security_auditor": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "compliance_auditor": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "judge": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
    "default": _RolePin(FABLE_51_DIRECT, FABLE_51_VIA_OPENROUTER),
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
    if get_secret_presence("ANTHROPIC_API_KEY").source not in {"aws", "env"}:
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
    "FABLE_51_DIRECT",
    "FABLE_51_VIA_OPENROUTER",
    "FABLE_5_DIRECT",
    "FABLE_5_VIA_OPENROUTER",
    "GPT6_ASTRA_DIRECT",
    "GPT6_ASTRA_VIA_OPENROUTER",
    "GPT56_TERRA_DIRECT",
    "GPT56_TERRA_VIA_OPENROUTER",
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
    "GEMINI_38_FLASH_DIRECT",
    "GEMINI_38_FLASH_VIA_OPENROUTER",
    "GROK_46_DIRECT",
    "GROK_46_VIA_OPENROUTER",
    "GROK_4_DIRECT",
    "GROK_4_VIA_OPENROUTER",
    "MISTRAL_MEDIUM_DIRECT",
    "MISTRAL_MEDIUM_VIA_OPENROUTER",
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
