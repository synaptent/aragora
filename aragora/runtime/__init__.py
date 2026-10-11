"""
Runtime module for aragora - Execution optimization and control.

Provides:
- Autotuner: Budget-aware round selection and early-stop
- Metadata: Run configuration and reproducibility info
- Metrics: Quality and cost tracking
- Service registry: process-wide service singletons (``aragora.runtime.service_registry``)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.runtime.autotune import AutotuneConfig, Autotuner, RunMetrics
    from aragora.runtime.metadata import DebateMetadata, ModelConfig

__all__ = [
    "Autotuner",
    "AutotuneConfig",
    "RunMetrics",
    "DebateMetadata",
    "ModelConfig",
]

_AUTOTUNE_EXPORTS = frozenset({"Autotuner", "AutotuneConfig", "RunMetrics"})
_METADATA_EXPORTS = frozenset({"DebateMetadata", "ModelConfig"})


# The package exports resolve on first access: lower layers import
# aragora.runtime.service_registry, and an eager runtime.metadata import would
# pull aragora.config and aragora.storage into every registry import.
def __getattr__(name: str) -> Any:
    if name in _AUTOTUNE_EXPORTS:
        from aragora.runtime import autotune

        return getattr(autotune, name)
    if name in _METADATA_EXPORTS:
        from aragora.runtime import metadata

        return getattr(metadata, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
