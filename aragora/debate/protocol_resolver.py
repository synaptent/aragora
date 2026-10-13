"""Resolve the default debate protocol, honoring debate profile overrides."""

from __future__ import annotations

import logging
import os

from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)

__all__ = ["resolve_default_protocol"]


def resolve_default_protocol(
    protocol: DebateProtocol | None = None,
) -> DebateProtocol:
    """Resolve the default protocol, honoring debate profile overrides."""
    if protocol is not None:
        return protocol

    profile = os.environ.get("ARAGORA_DEBATE_PROFILE", "").lower()
    if profile in {"full", "nomic", "structured"}:
        try:
            # Deferred: aragora.nomic sits above aragora.debate in the layer order.
            from aragora.nomic.debate_profile import NomicDebateProfile

            return NomicDebateProfile.from_env().to_protocol()
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
            logger.warning("Failed to apply debate profile '%s': %s", profile, exc)

    return DebateProtocol()
