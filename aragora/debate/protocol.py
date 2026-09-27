"""Compatibility shim for the foundation-owned debate protocol contract."""

from __future__ import annotations

import logging
import os
import warnings

warnings.warn(
    "aragora.debate.protocol is deprecated; import debate configuration from "
    "aragora.protocols.debate instead.",
    DeprecationWarning,
    stacklevel=2,
)

from aragora.protocols.debate import (  # noqa: E402
    ARAGORA_AI_LIGHT_PROTOCOL,
    ARAGORA_AI_PROTOCOL,
    STRUCTURED_LIGHT_ROUND_PHASES,
    STRUCTURED_ROUND_PHASES,
    DebateProtocol,
    RoundPhase,
    user_vote_multiplier,
)
from aragora.resilience import CircuitBreaker  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = [
    "ARAGORA_AI_LIGHT_PROTOCOL",
    "ARAGORA_AI_PROTOCOL",
    "CircuitBreaker",
    "DebateProtocol",
    "RoundPhase",
    "STRUCTURED_LIGHT_ROUND_PHASES",
    "STRUCTURED_ROUND_PHASES",
    "resolve_default_protocol",
    "user_vote_multiplier",
]


def resolve_default_protocol(
    protocol: DebateProtocol | None = None,
) -> DebateProtocol:
    """Resolve the default protocol, honoring debate profile overrides."""
    if protocol is not None:
        return protocol

    profile = os.environ.get("ARAGORA_DEBATE_PROFILE", "").lower()
    if profile in {"full", "nomic", "structured"}:
        try:
            from aragora.nomic.debate_profile import NomicDebateProfile

            return NomicDebateProfile.from_env().to_protocol()
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
            logger.warning("Failed to apply debate profile '%s': %s", profile, exc)

    return DebateProtocol()
