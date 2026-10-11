"""Compatibility shim for the foundation-owned debate protocol contract."""

from __future__ import annotations

import warnings

warnings.warn(
    "aragora.debate.protocol is deprecated; import debate configuration from "
    "aragora.protocols.debate instead.",
    DeprecationWarning,
    stacklevel=2,
)

from aragora.debate.protocol_resolver import resolve_default_protocol
from aragora.protocols.debate import (
    ARAGORA_AI_LIGHT_PROTOCOL,
    ARAGORA_AI_PROTOCOL,
    STRUCTURED_LIGHT_ROUND_PHASES,
    STRUCTURED_ROUND_PHASES,
    DebateProtocol,
    RoundPhase,
    user_vote_multiplier,
)
from aragora.resilience import CircuitBreaker

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
