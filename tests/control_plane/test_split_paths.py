"""Old aragora.control_plane paths re-export the objects that moved to lower layers."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

import aragora.blockchain.agent_registry as new_identity
import aragora.control_plane.blockchain_identity as old_identity
import aragora.control_plane.channels as channels
import aragora.control_plane.deliberation_events as old_deliberation
import aragora.control_plane.leader as old_leader
import aragora.control_plane.regional_sync as regional_sync
import aragora.control_plane.task_events as old_task_events
import aragora.events.deliberation_events as new_deliberation
import aragora.events.notification_types as notification_types
import aragora.events.task_events as new_task_events
import aragora.resilience.leader as new_leader
import aragora.resilience.regional_events as regional_events

REPO_ROOT = Path(__file__).resolve().parents[2]

LEADER_NAMES = (
    "LeaderState",
    "LeaderConfig",
    "LeaderInfo",
    "LeaderElection",
    "DistributedStateError",
    "is_distributed_state_required",
    "RegionalLeaderConfig",
    "RegionalLeaderInfo",
    "RegionalLeaderElection",
    "get_regional_leader_election",
    "set_regional_leader_election",
    "init_regional_leader_election",
)
IDENTITY_NAMES = (
    "AgentBlockchainLink",
    "BlockchainIdentityBridge",
    "get_blockchain_identity_bridge",
)
REGIONAL_EVENT_NAMES = ("RegionalEvent", "RegionalEventType")
# __all__ of aragora/control_plane/task_events.py before the move.
TASK_EVENT_NAMES = (
    "set_task_event_dispatcher",
    "get_task_event_dispatcher",
    "emit_task_submitted",
    "emit_task_claimed",
    "emit_task_completed",
    "emit_task_failed",
    "emit_task_timeout",
    "emit_task_retried",
    "emit_task_cancelled",
)
TASK_EVENT_HOOK_NAMES = (
    "TaskEvent",
    "TaskEventDispatcherNotRegisteredError",
    "register_default_task_event_dispatcher_provider",
    "registered_count",
    "resolve_task_event_dispatcher",
)
DELIBERATION_NAMES = (
    "CATEGORIES",
    "DeliberationEventType",
    "EVENT_TYPES_BY_CATEGORY",
    "TERMINAL_EVENT_TYPES",
)
NOTIFICATION_TYPE_NAMES = ("NotificationEventType", "NotificationPriority")

PAIRS = (
    [(old_leader, new_leader, name) for name in LEADER_NAMES + ("_InMemoryRedis",)]
    + [(old_identity, new_identity, name) for name in IDENTITY_NAMES]
    + [(regional_sync, regional_events, name) for name in REGIONAL_EVENT_NAMES]
    + [
        (old_task_events, new_task_events, name)
        for name in TASK_EVENT_NAMES + TASK_EVENT_HOOK_NAMES
    ]
    + [(old_deliberation, new_deliberation, name) for name in ("DeliberationEventType",)]
    + [(channels, notification_types, name) for name in NOTIFICATION_TYPE_NAMES]
)


@pytest.mark.parametrize(
    ("old", "new", "name"),
    PAIRS,
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_old_path_reexports_identical_object(old, new, name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize(
    ("old", "new", "name"),
    PAIRS,
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_implementation_lives_in_the_lower_layer(old, new, name: str) -> None:
    assert inspect.getmodule(getattr(old, name)) is new


@pytest.mark.parametrize("name", DELIBERATION_NAMES)
def test_deliberation_constants_are_shared(name: str) -> None:
    assert getattr(old_deliberation, name) is getattr(new_deliberation, name)


def test_old_path_all_lists_unchanged() -> None:
    assert sorted(old_leader.__all__) == sorted(LEADER_NAMES)
    assert sorted(old_identity.__all__) == sorted(IDENTITY_NAMES)
    assert sorted(old_deliberation.__all__) == sorted(DELIBERATION_NAMES)
    assert set(TASK_EVENT_NAMES) <= set(old_task_events.__all__)
    assert sorted(old_task_events.__all__) == sorted(new_task_events.__all__)


def test_task_event_payload_matches_at_both_paths() -> None:
    kwargs = {
        "event_type": "task_failed",
        "title": "Task Failed: debate",
        "body": "Task `abc` failed",
        "workspace_id": "ws-1",
        "metadata": {"task_id": "abc"},
    }
    old_event = old_task_events.TaskEvent(priority=channels.NotificationPriority.URGENT, **kwargs)
    new_event = new_task_events.TaskEvent(
        priority=notification_types.NotificationPriority.URGENT, **kwargs
    )
    assert old_event.to_dict() == new_event.to_dict()
    assert old_event.to_dict()["priority"] == "urgent"


def test_fixed_input_leader_calls_at_both_paths() -> None:
    old_config = old_leader.RegionalLeaderConfig(key_prefix="se2:", region_id="eu-west-1")
    new_config = new_leader.RegionalLeaderConfig(key_prefix="se2:", region_id="eu-west-1")
    assert old_config.get_region_key_prefix() == "se2:region:eu-west-1:"
    assert new_config.get_region_key_prefix() == "se2:region:eu-west-1:"

    error = old_leader.DistributedStateError("leader", "no redis")
    assert isinstance(error, new_leader.DistributedStateError)
    assert str(error).startswith(
        "Distributed state required for leader but not available: no redis."
    )


def test_regional_event_round_trip_at_both_paths() -> None:
    event = regional_sync.RegionalEvent(
        event_type=regional_sync.RegionalEventType.LEADER_ELECTED,
        source_region="us-east-1",
        entity_id="node-1",
        timestamp=1.0,
    )
    assert event.to_dict() == {
        "event_type": "leader_elected",
        "source_region": "us-east-1",
        "entity_id": "node-1",
        "timestamp": 1.0,
        "data": {},
        "version": 1,
    }
    assert regional_events.RegionalEvent.from_dict(event.to_dict()) == event


def test_regional_leader_singleton_shared() -> None:
    saved = new_leader._regional_leader_election
    election = old_leader.RegionalLeaderElection(config=old_leader.RegionalLeaderConfig())
    try:
        old_leader.set_regional_leader_election(election)
        assert new_leader.get_regional_leader_election() is election
        new_leader.set_regional_leader_election(None)
        assert old_leader.get_regional_leader_election() is None
    finally:
        new_leader._regional_leader_election = saved


def test_identity_bridge_singleton_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(new_identity, "_bridge", None)
    bridge = old_identity.get_blockchain_identity_bridge()
    assert new_identity.get_blockchain_identity_bridge() is bridge


def test_persisted_link_loads_through_both_paths(tmp_path: Path) -> None:
    state = tmp_path / "links.json"
    state.write_text(
        json.dumps(
            {
                "links": [
                    {
                        "aragora_agent_id": "claude",
                        "chain_id": 1,
                        "token_id": 42,
                        "owner_address": "0xabc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    expected = new_identity.AgentBlockchainLink("claude", 1, 42, "0xabc")
    assert (
        old_identity.BlockchainIdentityBridge(persistence_path=state).get_link("claude") == expected
    )
    assert (
        new_identity.BlockchainIdentityBridge(persistence_path=state).get_link("claude") == expected
    )


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            if node.module == "aragora":
                found.extend((node.lineno, f"aragora.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                found.append((node.lineno, node.args[0].value))
    return found


MOVED_MODULES = [
    "aragora/resilience/leader.py",
    "aragora/resilience/regional_events.py",
    "aragora/blockchain/agent_registry.py",
    "aragora/events/task_events.py",
    "aragora/events/deliberation_events.py",
    "aragora/events/notification_types.py",
    "aragora/events/agent_registry_hooks.py",
]
FLIPPED_SITES = [
    "aragora/storage/sync_store.py",
    "aragora/blockchain/receipt_settlement.py",
    "aragora/knowledge/mound/adapters/erc8004_adapter.py",
    "aragora/events/registry.py",
    "aragora/events/cross_subscribers/manager.py",
]


@pytest.mark.parametrize("relative_path", MOVED_MODULES + FLIPPED_SITES)
def test_no_import_of_control_plane_or_server(relative_path: str) -> None:
    offenders = [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _imported_modules(REPO_ROOT / relative_path)
        if ".".join(module.split(".")[:2]) in ("aragora.control_plane", "aragora.server")
    ]
    assert offenders == []
