"""
Tests for aragora.server.startup.control_plane module.

Tests control plane coordinator, shared state, witness patrol,
mayor coordinator, and persistent task queue initialization.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Event Registry Composition Tests
# =============================================================================


class TestControlPlaneEventRegistryComposition:
    """Tests for explicit control-plane event contributor composition."""

    def test_registers_notification_event_contributor(self) -> None:
        from aragora.control_plane.channels import NotificationEventType
        from aragora.events import registry as registry_module
        from aragora.server.startup.control_plane import register_control_plane_event_contributors

        registry_module.register_notification_event_contributor(None)
        registry_module.reset_event_registry()
        try:
            assert register_control_plane_event_contributors() is True

            registry = registry_module.get_event_registry()
            registered = {
                event.name
                for event in registry.list_events(source=registry_module.EventSource.CONTROL_PLANE)
            }
            assert registered == {event_type.value for event_type in NotificationEventType}
        finally:
            registry_module.register_notification_event_contributor(None)
            registry_module.reset_event_registry()

    def test_composes_events_before_control_plane_startup(self) -> None:
        from aragora.server.startup import _init_all_components

        source = inspect.getsource(_init_all_components)

        assert source.index("register_control_plane_event_contributors()") < source.index(
            "init_control_plane_coordinator()"
        )


# =============================================================================
# init_control_plane_coordinator Tests
# =============================================================================


class TestInitControlPlaneCoordinator:
    """Tests for init_control_plane_coordinator function."""

    @pytest.mark.asyncio
    async def test_successful_initialization_with_policy_manager(self) -> None:
        """Test successful coordinator init with policy manager."""
        mock_coordinator = MagicMock()
        mock_coordinator.policy_manager = MagicMock()
        mock_coordinator.policy_manager._policies = {"policy1": {}, "policy2": {}}

        mock_cp = MagicMock()
        mock_cp.ControlPlaneCoordinator = MagicMock()
        mock_cp.ControlPlaneCoordinator.create = AsyncMock(return_value=mock_coordinator)

        with patch.dict("sys.modules", {"aragora.control_plane.coordinator": mock_cp}):
            from aragora.server.startup.control_plane import init_control_plane_coordinator

            result = await init_control_plane_coordinator()

        assert result == mock_coordinator
        mock_cp.ControlPlaneCoordinator.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_successful_initialization_without_policy_manager(self) -> None:
        """Test successful coordinator init without policy manager."""
        mock_coordinator = MagicMock()
        mock_coordinator.policy_manager = None

        mock_cp = MagicMock()
        mock_cp.ControlPlaneCoordinator = MagicMock()
        mock_cp.ControlPlaneCoordinator.create = AsyncMock(return_value=mock_coordinator)

        with patch.dict("sys.modules", {"aragora.control_plane.coordinator": mock_cp}):
            from aragora.server.startup.control_plane import init_control_plane_coordinator

            result = await init_control_plane_coordinator()

        assert result == mock_coordinator

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Test ImportError returns None."""
        with patch.dict("sys.modules", {"aragora.control_plane.coordinator": None}):
            import importlib
            import aragora.server.startup.control_plane as cp_module

            importlib.reload(cp_module)
            result = await cp_module.init_control_plane_coordinator()

        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """Test ConnectionError returns None (Redis unavailable)."""
        mock_cp = MagicMock()
        mock_cp.ControlPlaneCoordinator = MagicMock()
        mock_cp.ControlPlaneCoordinator.create = AsyncMock(
            side_effect=ConnectionError("Redis unavailable")
        )

        with patch.dict("sys.modules", {"aragora.control_plane.coordinator": mock_cp}):
            from aragora.server.startup.control_plane import init_control_plane_coordinator

            result = await init_control_plane_coordinator()

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error(self) -> None:
        """Test TimeoutError returns None."""
        mock_cp = MagicMock()
        mock_cp.ControlPlaneCoordinator = MagicMock()
        mock_cp.ControlPlaneCoordinator.create = AsyncMock(
            side_effect=TimeoutError("connection timed out")
        )

        with patch.dict("sys.modules", {"aragora.control_plane.coordinator": mock_cp}):
            from aragora.server.startup.control_plane import init_control_plane_coordinator

            result = await init_control_plane_coordinator()

        assert result is None


# =============================================================================
# init_shared_control_plane_state Tests
# =============================================================================


class TestInitSharedControlPlaneState:
    """Tests for init_shared_control_plane_state function."""

    @pytest.mark.asyncio
    async def test_redis_connected(self) -> None:
        """Test successful Redis connection."""
        mock_state = MagicMock()
        mock_state.is_persistent = True

        mock_shared = MagicMock()
        mock_shared.get_shared_state = AsyncMock(return_value=mock_state)

        with patch.dict("sys.modules", {"aragora.control_plane.shared_state": mock_shared}):
            from aragora.server.startup.control_plane import init_shared_control_plane_state

            result = await init_shared_control_plane_state()

        assert result is True
        mock_shared.get_shared_state.assert_awaited_once_with(auto_connect=True)

    @pytest.mark.asyncio
    async def test_in_memory_fallback(self) -> None:
        """Test in-memory fallback when Redis unavailable."""
        mock_state = MagicMock()
        mock_state.is_persistent = False

        mock_shared = MagicMock()
        mock_shared.get_shared_state = AsyncMock(return_value=mock_state)

        with patch.dict("sys.modules", {"aragora.control_plane.shared_state": mock_shared}):
            from aragora.server.startup.control_plane import init_shared_control_plane_state

            result = await init_shared_control_plane_state()

        assert result is False

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict("sys.modules", {"aragora.control_plane.shared_state": None}):
            import importlib
            import aragora.server.startup.control_plane as cp_module

            importlib.reload(cp_module)
            result = await cp_module.init_shared_control_plane_state()

        assert result is False

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """Test ConnectionError returns False."""
        mock_shared = MagicMock()
        mock_shared.get_shared_state = AsyncMock(side_effect=ConnectionError("connection refused"))

        with patch.dict("sys.modules", {"aragora.control_plane.shared_state": mock_shared}):
            from aragora.server.startup.control_plane import init_shared_control_plane_state

            result = await init_shared_control_plane_state()

        assert result is False


# =============================================================================
# Witness Patrol Tests
# =============================================================================


class TestWitnessPatrol:
    """Tests for witness patrol functions."""

    def test_get_witness_behavior_initially_none(self) -> None:
        """Test get_witness_behavior returns None initially."""
        import aragora.server.startup.control_plane as cp_module

        # Reset global state
        cp_module._witness_behavior = None

        result = cp_module.get_witness_behavior()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_witness_patrol_success(self) -> None:
        """Test successful witness patrol initialization."""
        mock_hierarchy = MagicMock()
        mock_witness = MagicMock()
        mock_witness.start_patrol = AsyncMock()

        mock_witness_module = MagicMock()
        mock_witness_module.WitnessBehavior = MagicMock(return_value=mock_witness)
        mock_witness_module.WitnessConfig = MagicMock()

        mock_roles = MagicMock()
        mock_roles.AgentHierarchy = MagicMock(return_value=mock_hierarchy)

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.witness_behavior": mock_witness_module,
                "aragora.nomic.agent_roles": mock_roles,
            },
        ):
            from aragora.server.startup.control_plane import (
                init_witness_patrol,
                get_witness_behavior,
            )

            result = await init_witness_patrol()

        assert result is True
        mock_witness.start_patrol.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_witness_patrol_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict("sys.modules", {"aragora.nomic.witness_behavior": None}):
            import importlib
            import aragora.server.startup.control_plane as cp_module

            importlib.reload(cp_module)
            result = await cp_module.init_witness_patrol()

        assert result is False

    @pytest.mark.asyncio
    async def test_init_witness_patrol_runtime_error(self) -> None:
        """Test RuntimeError returns False."""
        mock_witness_module = MagicMock()
        mock_witness_module.WitnessBehavior = MagicMock(side_effect=RuntimeError("witness error"))
        mock_witness_module.WitnessConfig = MagicMock()

        mock_roles = MagicMock()
        mock_roles.AgentHierarchy = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.witness_behavior": mock_witness_module,
                "aragora.nomic.agent_roles": mock_roles,
            },
        ):
            from aragora.server.startup.control_plane import init_witness_patrol

            result = await init_witness_patrol()

        assert result is False


# =============================================================================
# Mayor Coordinator Tests
# =============================================================================


class TestMayorCoordinator:
    """Tests for mayor coordinator functions."""

    def test_get_mayor_coordinator_initially_none(self) -> None:
        """Test get_mayor_coordinator returns None initially."""
        import aragora.server.startup.control_plane as cp_module

        # Reset global state
        cp_module._mayor_coordinator = None

        result = cp_module.get_mayor_coordinator()
        assert result is None

    @pytest.mark.asyncio
    async def test_init_mayor_coordinator_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test successful mayor coordinator initialization."""
        monkeypatch.setenv("ARAGORA_NODE_ID", "node-1")
        monkeypatch.setenv("ARAGORA_REGION", "us-west-2")

        mock_hierarchy = MagicMock()
        mock_coordinator = MagicMock()
        mock_coordinator.start = AsyncMock(return_value=True)
        mock_coordinator.is_mayor = True
        mock_coordinator.node_id = "node-1"

        mock_mayor_module = MagicMock()
        mock_mayor_module.MayorCoordinator = MagicMock(return_value=mock_coordinator)

        mock_roles = MagicMock()
        mock_roles.AgentHierarchy = MagicMock(return_value=mock_hierarchy)

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.mayor_coordinator": mock_mayor_module,
                "aragora.nomic.agent_roles": mock_roles,
            },
        ):
            from aragora.server.startup.control_plane import init_mayor_coordinator

            result = await init_mayor_coordinator()

        assert result is True
        mock_coordinator.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_mayor_coordinator_start_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test when coordinator.start() returns False."""
        monkeypatch.delenv("ARAGORA_NODE_ID", raising=False)
        monkeypatch.delenv("ARAGORA_REGION", raising=False)

        mock_coordinator = MagicMock()
        mock_coordinator.start = AsyncMock(return_value=False)

        mock_mayor_module = MagicMock()
        mock_mayor_module.MayorCoordinator = MagicMock(return_value=mock_coordinator)

        mock_roles = MagicMock()
        mock_roles.AgentHierarchy = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.mayor_coordinator": mock_mayor_module,
                "aragora.nomic.agent_roles": mock_roles,
            },
        ):
            from aragora.server.startup.control_plane import init_mayor_coordinator

            result = await init_mayor_coordinator()

        assert result is False

    @pytest.mark.asyncio
    async def test_init_mayor_coordinator_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict("sys.modules", {"aragora.nomic.mayor_coordinator": None}):
            import importlib
            import aragora.server.startup.control_plane as cp_module

            importlib.reload(cp_module)
            result = await cp_module.init_mayor_coordinator()

        assert result is False

    @pytest.mark.asyncio
    async def test_init_mayor_coordinator_connection_error(self) -> None:
        """Test ConnectionError returns False."""
        mock_mayor_module = MagicMock()
        mock_mayor_module.MayorCoordinator = MagicMock(
            side_effect=ConnectionError("Redis unavailable")
        )

        mock_roles = MagicMock()
        mock_roles.AgentHierarchy = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.mayor_coordinator": mock_mayor_module,
                "aragora.nomic.agent_roles": mock_roles,
            },
        ):
            from aragora.server.startup.control_plane import init_mayor_coordinator

            result = await init_mayor_coordinator()

        assert result is False


# =============================================================================
# init_persistent_task_queue Tests
# =============================================================================


class TestInitPersistentTaskQueue:
    """Tests for init_persistent_task_queue function."""

    @pytest.mark.asyncio
    async def test_successful_initialization(self) -> None:
        """Test successful task queue initialization."""
        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()
        mock_queue.recover_tasks = AsyncMock(return_value=3)
        mock_queue.delete_completed_tasks = MagicMock(return_value=0)

        mock_workflow = MagicMock()
        mock_workflow.get_persistent_task_queue = MagicMock(return_value=mock_queue)
        mock_workflow.PersistentTaskQueue = MagicMock

        with patch.dict("sys.modules", {"aragora.workflow.queue": mock_workflow}):
            with patch("asyncio.create_task") as mock_create_task:
                from aragora.server.startup.control_plane import init_persistent_task_queue

                result = await init_persistent_task_queue()

        assert result == 3
        mock_queue.start.assert_awaited_once()
        mock_queue.recover_tasks.assert_awaited_once()
        mock_create_task.assert_called_once()  # Cleanup loop started

    @pytest.mark.asyncio
    async def test_no_tasks_recovered(self) -> None:
        """Test initialization with no tasks to recover."""
        mock_queue = MagicMock()
        mock_queue.start = AsyncMock()
        mock_queue.recover_tasks = AsyncMock(return_value=0)

        mock_workflow = MagicMock()
        mock_workflow.get_persistent_task_queue = MagicMock(return_value=mock_queue)
        mock_workflow.PersistentTaskQueue = MagicMock

        with patch.dict("sys.modules", {"aragora.workflow.queue": mock_workflow}):
            with patch("asyncio.create_task"):
                from aragora.server.startup.control_plane import init_persistent_task_queue

                result = await init_persistent_task_queue()

        assert result == 0

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Test ImportError returns 0."""
        with patch.dict("sys.modules", {"aragora.workflow.queue": None}):
            import importlib
            import aragora.server.startup.control_plane as cp_module

            importlib.reload(cp_module)
            result = await cp_module.init_persistent_task_queue()

        assert result == 0

    @pytest.mark.asyncio
    async def test_runtime_error(self) -> None:
        """Test RuntimeError returns 0."""
        mock_workflow = MagicMock()
        mock_workflow.get_persistent_task_queue = MagicMock(side_effect=RuntimeError("queue error"))
        mock_workflow.PersistentTaskQueue = MagicMock

        with patch.dict("sys.modules", {"aragora.workflow.queue": mock_workflow}):
            from aragora.server.startup.control_plane import init_persistent_task_queue

            result = await init_persistent_task_queue()

        assert result == 0
