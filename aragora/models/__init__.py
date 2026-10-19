"""Canonical model catalog (phase 1). See catalog.py for the contract."""

from aragora.models.catalog import (
    CATALOG,
    ENFORCED_MODELS,
    FRONTIER,
    ModelSpec,
    by_any_id,
    frontier_for,
    load_snapshot,
    snapshot_path,
    spec_or_none,
    utc_today,
)
from aragora.models.compat import (
    first_text_block,
    rejects_sampling_params,
    strip_sampling_params,
)
from aragora.models.upgrade_map import (
    RETIRED_PATTERN,
    UPGRADES,
    resolve_model_id,
)

__all__ = [
    "CATALOG",
    "ENFORCED_MODELS",
    "FRONTIER",
    "RETIRED_PATTERN",
    "UPGRADES",
    "ModelSpec",
    "by_any_id",
    "first_text_block",
    "frontier_for",
    "load_snapshot",
    "rejects_sampling_params",
    "resolve_model_id",
    "strip_sampling_params",
    "snapshot_path",
    "spec_or_none",
    "utc_today",
]
