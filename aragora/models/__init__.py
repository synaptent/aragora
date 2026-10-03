"""Canonical model catalog (phase 1). See catalog.py for the contract."""

from aragora.models.catalog import (
    CATALOG,
    ENFORCED_MODELS,
    ModelSpec,
    by_any_id,
    load_snapshot,
    snapshot_path,
    utc_today,
)
from aragora.models.compat import (
    first_text_block,
    rejects_sampling_params,
    strip_sampling_params,
)

__all__ = [
    "CATALOG",
    "ENFORCED_MODELS",
    "ModelSpec",
    "by_any_id",
    "first_text_block",
    "load_snapshot",
    "rejects_sampling_params",
    "strip_sampling_params",
    "snapshot_path",
    "utc_today",
]
