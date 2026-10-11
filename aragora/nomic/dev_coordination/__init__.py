"""Development coordination primitives for concurrent multi-agent work.

This module adds the missing control plane for high-churn concurrent work:
- Work leases with explicit write scopes and expected tests
- Completion receipts for bounded worker outputs
- Integration decisions for an explicit integrator lane
- Salvage candidates for dirty worktrees and stashes

The design intentionally builds on existing Aragora orchestration patterns:
- EventBus for cross-worktree signaling
- GlobalWorkQueue-compatible work item projection
- Receipt-style content hashes for auditability
- Git-common-dir local state so agents coordinate without tracked-file churn

Internal layout (TCP-3 PR-A split; see
``.aragora_coordination/tcp3_hotspot_split_proposals_2026-04-18.md``):

- :mod:`aragora.nomic.dev_coordination.models` — dataclasses, enums, errors
- :mod:`aragora.nomic.dev_coordination.utils`  — stateless helpers
- :mod:`aragora.nomic.dev_coordination.core`   — store and ``main`` entry point
- :mod:`aragora.nomic.dev_coordination.cli`    — argparse parser, command dispatch
- ``work_order_overlap``, ``work_order_archive``, ``merge_gate_replay``,
  ``work_order_waiting_conflict``, ``work_order_rehabilitation`` — work-order
  predicates re-imported by ``core``
- ``work_order_maintenance`` — ``WorkOrderMaintenanceMixin`` (maintenance passes,
  queue projection) inherited by ``DevCoordinationStore``

The public import surface is re-exported verbatim from this package so
external callers (``aragora.swarm.*``, ``aragora.server.handlers.*``,
``aragora.cli.commands.*``, ``aragora.nomic.dev_receipts``, tests) need no
changes.  Private helpers imported from outside the module
(``_path_matches_glob``, ``_glob_overlap``) are also re-exported.
Attribute lookups that miss the names explicitly bound here fall through
to :mod:`aragora.nomic.dev_coordination.core` via :pep:`562` module-level
``__getattr__`` — this preserves the large surface that
``aragora.nomic.dev_receipts`` consumes by attribute access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.swarm.lane_telemetry import LaneTelemetryCollector


# Mutable module-level state hosted here (rather than in ``core``) so tests
# that ``patch("aragora.nomic.dev_coordination._LANE_TELEMETRY", collector)``
# continue to work without modification.  ``_get_lane_telemetry`` is
# referenced externally as ``aragora.nomic.dev_coordination._get_lane_telemetry``
# (see ``aragora.nomic.dev_receipts``).
_LANE_TELEMETRY: LaneTelemetryCollector | None = None


def _get_lane_telemetry() -> LaneTelemetryCollector:
    global _LANE_TELEMETRY
    if _LANE_TELEMETRY is None:
        from aragora.swarm.lane_telemetry import LaneTelemetryCollector

        _LANE_TELEMETRY = LaneTelemetryCollector()
    return _LANE_TELEMETRY


# Explicit re-exports — these names are the ones external callers import
# verbatim via ``from aragora.nomic.dev_coordination import X``.  Ruff F401
# is silenced because unused-at-import is intentional (re-export surface).
from aragora.nomic.dev_coordination.models import (  # noqa: E402, F401
    CompletionReceipt,
    DeveloperTask,
    FileScopeViolationError,
    IntegrationDecision,
    IntegrationDecisionType,
    LeaseConflictError,
    LeaseStatus,
    SalvageCandidate,
    SalvageStatus,
    WorkLease,
)
from aragora.nomic.dev_coordination.utils import (  # noqa: E402, F401
    UTC,
    _artifact_hash,
    _estimate_salvage_value,
    _has_wildcard,
    _json_compatible,
    _json_dump,
    _json_loads,
    _normalize_claim,
    _parse_dt,
    _parse_worktree_entries,
    _safe_kill_probe,
    _status_paths,
    _utcnow,
)
from aragora.nomic.dev_coordination import core as _core  # noqa: E402
from aragora.nomic.dev_coordination.core import (  # noqa: E402, F401
    DevCoordinationStore,
    _glob_overlap,
    _is_docs_only_path,
    _normalize_completion_outcome,
    _path_matches_glob,
    main,
)


def __getattr__(name: str) -> Any:
    """Fall through to :mod:`aragora.nomic.dev_coordination.core`.

    ``aragora.nomic.dev_receipts`` bulk-imports ~150 symbols by attribute
    access (``_dev.Any``, ``_dev.Path``, ``_dev._work_order_should_*``…).
    Enumerating them all in an explicit re-export list would be noisy and
    fragile.  :pep:`562` lets us delegate unknown attributes to ``core``
    without a star-import (keeps linters happy) and without affecting the
    names explicitly bound above.
    """
    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


__all__ = [
    # Models
    "CompletionReceipt",
    "DeveloperTask",
    "FileScopeViolationError",
    "IntegrationDecision",
    "IntegrationDecisionType",
    "LeaseConflictError",
    "LeaseStatus",
    "SalvageCandidate",
    "SalvageStatus",
    "WorkLease",
    # Core store
    "DevCoordinationStore",
    # Public entrypoints
    "main",
]
