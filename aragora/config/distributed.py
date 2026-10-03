"""Environment policy for deciding when distributed state is required."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def is_distributed_state_required() -> bool:
    """Return whether the current deployment requires a distributed backend."""
    if os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED", "").lower() in ("true", "1", "yes"):
        return True
    if os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED_STATE", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        logger.warning(
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE is deprecated, use "
            "ARAGORA_REQUIRE_DISTRIBUTED instead"
        )
        return True
    if os.environ.get("ARAGORA_MULTI_INSTANCE", "").lower() in ("true", "1", "yes"):
        return True
    if os.environ.get("ARAGORA_ENV") == "production":
        return os.environ.get("ARAGORA_SINGLE_INSTANCE", "").lower() not in (
            "true",
            "1",
            "yes",
        )
    return False


__all__ = ["is_distributed_state_required"]
