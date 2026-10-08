"""Compatibility re-export of :mod:`aragora.resilience.leader`.

Leader election moved to the resilience layer so that storage and other
infrastructure code can use it without importing ``aragora.control_plane``.
Every name below is the identical object. Module-level state
(``_regional_leader_election``) lives only in the new module; patch or reset it
there.
"""

from __future__ import annotations

from aragora.resilience.leader import (
    DistributedStateError,
    LeaderConfig,
    LeaderElection,
    LeaderInfo,
    LeaderState,
    RegionalLeaderConfig,
    RegionalLeaderElection,
    RegionalLeaderInfo,
    _InMemoryRedis as _InMemoryRedis,
    get_regional_leader_election,
    init_regional_leader_election,
    is_distributed_state_required,
    set_regional_leader_election,
)

__all__ = [
    "LeaderState",
    "LeaderConfig",
    "LeaderInfo",
    "LeaderElection",
    "DistributedStateError",
    "is_distributed_state_required",
    # Regional
    "RegionalLeaderConfig",
    "RegionalLeaderInfo",
    "RegionalLeaderElection",
    "get_regional_leader_election",
    "set_regional_leader_election",
    "init_regional_leader_election",
]
