"""Tests for orchestrator_hooks.py - Bead management and GUPP recovery helpers.

Tests cover:
- create_debate_bead: Bead creation for completed debates
- create_pending_debate_bead: Pending bead for work tracking
- update_debate_bead: Status updates on completion
- init_hook_tracking: GUPP hook queue initialization
- complete_hook_tracking: Hook completion/failure
- recover_pending_debates: GUPP recovery on startup
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Mock module setup for local imports
# =============================================================================


def create_mock_beads_module():
    """Create a mock aragora.nomic.beads module."""
    mock_module = MagicMock()
    mock_module.Bead = MagicMock()
    mock_module.BeadStore = MagicMock()
    mock_module.BeadType = MagicMock()
    mock_module.BeadType.DEBATE_DECISION = "DEBATE_DECISION"
    mock_module.BeadPriority = MagicMock()
    mock_module.BeadPriority.HIGH = "HIGH"
    mock_module.BeadPriority.NORMAL = "NORMAL"
    mock_module.BeadPriority.LOW = "LOW"
    mock_module.BeadStatus = MagicMock()
    mock_module.BeadStatus.COMPLETED = "COMPLETED"
    mock_module.BeadStatus.FAILED = "FAILED"
    mock_module.BeadStatus.PENDING = "PENDING"
    return mock_module


def create_mock_hook_queue_module():
    """Create a mock aragora.nomic.hook_queue module."""
    mock_module = MagicMock()
    mock_module.HookQueueRegistry = MagicMock()
    return mock_module


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_result():
    """Create a mock DebateResult."""
    result = MagicMock()
    result.id = "result-123"
    result.debate_id = "debate-456"
    result.task = "Test debate task for testing purposes"
    result.final_answer = "The conclusion is that testing is important."
    result.confidence = 0.85
    result.consensus_reached = True
    result.rounds_used = 3
    result.participants = ["agent-1", "agent-2"]
    result.winner = "agent-1"
    result.status = "completed"
    result.messages = []
    result.votes = []
    return result


@pytest.fixture
def mock_protocol():
    """Create a mock protocol."""
    protocol = MagicMock()
    protocol.enable_bead_tracking = True
    protocol.bead_min_confidence = 0.5
    protocol.bead_auto_commit = False
    protocol.enable_hook_tracking = True
    return protocol


@pytest.fixture
def mock_env():
    """Create a mock environment."""
    env = MagicMock()
    env.context = {"bead_dir": ".test-beads"}
    return env


@pytest.fixture
def mock_bead_store():
    """Create a mock BeadStore."""
    store = MagicMock()
    store.initialize = AsyncMock()
    store.create = AsyncMock(return_value="bead-789")
    store.get = AsyncMock(return_value=MagicMock(metadata={}))
    store.update_status = AsyncMock()
    return store


@pytest.fixture
def mock_agents():
    """Create mock agents."""
    agents = []
    for i in range(3):
        agent = MagicMock()
        agent.name = f"agent-{i}"
        agents.append(agent)
    return agents


@pytest.fixture
def mock_beads_module():
    """Create mock beads module for patching."""
    return create_mock_beads_module()


@pytest.fixture
def mock_hook_queue_module():
    """Create mock hook queue module for patching."""
    return create_mock_hook_queue_module()


# =============================================================================
# Tests for create_debate_bead
# =============================================================================


class TestCreateDebateBead:
    """Tests for create_debate_bead function."""

    @pytest.mark.asyncio
    async def test_skips_when_bead_tracking_disabled(self, mock_result, mock_env):
        """When bead tracking is disabled, return None."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        protocol = MagicMock()
        protocol.enable_bead_tracking = False

        result = await create_debate_bead(
            result=mock_result,
            protocol=protocol,
            env=mock_env,
            bead_store_holder=MagicMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_confidence_below_minimum(self, mock_result, mock_protocol, mock_env):
        """When confidence is below threshold, return None."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        mock_result.confidence = 0.3
        mock_protocol.bead_min_confidence = 0.5

        result = await create_debate_bead(
            result=mock_result,
            protocol=mock_protocol,
            env=mock_env,
            bead_store_holder=MagicMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_bead_on_success(
        self, mock_result, mock_protocol, mock_env, mock_bead_store, mock_beads_module
    ):
        """When conditions met, create bead and return ID."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            result = await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

        assert result == "bead-789"

    @pytest.mark.asyncio
    async def test_high_priority_for_high_confidence(
        self, mock_result, mock_protocol, mock_env, mock_bead_store, mock_beads_module
    ):
        """Confidence >= 0.9 results in HIGH priority."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        mock_result.confidence = 0.95
        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

            # Verify HIGH priority was used
            call_kwargs = mock_beads_module.Bead.create.call_args[1]
            assert call_kwargs["priority"] == mock_beads_module.BeadPriority.HIGH

    @pytest.mark.asyncio
    async def test_normal_priority_for_medium_confidence(
        self, mock_result, mock_protocol, mock_env, mock_bead_store, mock_beads_module
    ):
        """Confidence 0.7-0.9 results in NORMAL priority."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        mock_result.confidence = 0.75
        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

            call_kwargs = mock_beads_module.Bead.create.call_args[1]
            assert call_kwargs["priority"] == mock_beads_module.BeadPriority.NORMAL

    @pytest.mark.asyncio
    async def test_low_priority_for_low_confidence(
        self, mock_result, mock_protocol, mock_env, mock_bead_store, mock_beads_module
    ):
        """Confidence < 0.7 results in LOW priority."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        mock_result.confidence = 0.55
        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

            call_kwargs = mock_beads_module.Bead.create.call_args[1]
            assert call_kwargs["priority"] == mock_beads_module.BeadPriority.LOW

    @pytest.mark.asyncio
    async def test_initializes_bead_store_if_missing(
        self, mock_result, mock_protocol, mock_env, mock_beads_module
    ):
        """When bead_store is None, initialize a new one."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        holder = MagicMock()
        holder._bead_store = None

        mock_store_instance = MagicMock()
        mock_store_instance.initialize = AsyncMock()
        mock_store_instance.create = AsyncMock(return_value="new-bead-id")
        mock_beads_module.BeadStore.return_value = mock_store_instance
        mock_beads_module.Bead.create.return_value = MagicMock()

        mock_canonical = MagicMock()
        mock_canonical.bead_store = AsyncMock(return_value=mock_store_instance)

        with (
            patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}),
            patch(
                "aragora.debate.orchestrator_hooks.get_workspace_stores",
                return_value=mock_canonical,
            ),
        ):
            result = await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

        assert result == "new-bead-id"
        mock_store_instance.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_import_error(self, mock_result, mock_protocol, mock_env):
        """When import fails, return None."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        holder = MagicMock()

        # Set module to None to cause ImportError
        with patch.dict(sys.modules, {"aragora.nomic.beads": None}):
            result = await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_os_error_gracefully(
        self, mock_result, mock_protocol, mock_env, mock_bead_store, mock_beads_module
    ):
        """When OSError occurs, return None."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store
        mock_bead_store.create.side_effect = OSError("Disk full")

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            result = await create_debate_bead(
                result=mock_result,
                protocol=mock_protocol,
                env=mock_env,
                bead_store_holder=holder,
            )

        assert result is None


# =============================================================================
# Tests for create_pending_debate_bead
# =============================================================================


class TestCreatePendingDebateBead:
    """Tests for create_pending_debate_bead function."""

    @pytest.mark.asyncio
    async def test_skips_when_hook_tracking_disabled(self, mock_env, mock_agents):
        """When hook tracking is disabled, return None."""
        from aragora.debate.orchestrator_hooks import create_pending_debate_bead

        protocol = MagicMock()
        protocol.enable_hook_tracking = False

        result = await create_pending_debate_bead(
            debate_id="debate-123",
            task="Test task",
            protocol=protocol,
            env=mock_env,
            agents=mock_agents,
            bead_store_holder=MagicMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_pending_bead(
        self, mock_protocol, mock_env, mock_agents, mock_bead_store, mock_beads_module
    ):
        """When enabled, create pending bead."""
        from aragora.debate.orchestrator_hooks import create_pending_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            result = await create_pending_debate_bead(
                debate_id="debate-123",
                task="Test task",
                protocol=mock_protocol,
                env=mock_env,
                agents=mock_agents,
                bead_store_holder=holder,
            )

        assert result == "bead-789"

    @pytest.mark.asyncio
    async def test_bead_marked_as_pending(
        self, mock_protocol, mock_env, mock_agents, mock_bead_store, mock_beads_module
    ):
        """Pending bead has [Pending] in title."""
        from aragora.debate.orchestrator_hooks import create_pending_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await create_pending_debate_bead(
                debate_id="debate-123",
                task="Test task",
                protocol=mock_protocol,
                env=mock_env,
                agents=mock_agents,
                bead_store_holder=holder,
            )

            call_kwargs = mock_beads_module.Bead.create.call_args[1]
            assert "[Pending]" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_bead_marked_as_gupp_tracked(
        self, mock_protocol, mock_env, mock_agents, mock_bead_store, mock_beads_module
    ):
        """Pending bead has gupp-tracked tag."""
        from aragora.debate.orchestrator_hooks import create_pending_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store

        mock_beads_module.Bead.create.return_value = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await create_pending_debate_bead(
                debate_id="debate-123",
                task="Test task",
                protocol=mock_protocol,
                env=mock_env,
                agents=mock_agents,
                bead_store_holder=holder,
            )

            call_kwargs = mock_beads_module.Bead.create.call_args[1]
            assert "gupp-tracked" in call_kwargs["tags"]


# =============================================================================
# Tests for update_debate_bead
# =============================================================================


class TestUpdateDebateBead:
    """Tests for update_debate_bead function."""

    @pytest.mark.asyncio
    async def test_skips_when_bead_id_is_empty(self, mock_result):
        """When bead_id is empty, return without action."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        await update_debate_bead(
            bead_id="",
            result=mock_result,
            success=True,
            bead_store_holder=MagicMock(),
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_skips_when_bead_store_missing(self, mock_result):
        """When bead_store is None, return without action."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        holder = MagicMock()
        holder._bead_store = None

        await update_debate_bead(
            bead_id="bead-123",
            result=mock_result,
            success=True,
            bead_store_holder=holder,
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_skips_when_bead_not_found(self, mock_result, mock_bead_store, mock_beads_module):
        """When bead not found, return without action."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store
        mock_bead_store.get = AsyncMock(return_value=None)

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await update_debate_bead(
                bead_id="bead-123",
                result=mock_result,
                success=True,
                bead_store_holder=holder,
            )
        # Should not raise

    @pytest.mark.asyncio
    async def test_sets_status_completed_on_success(
        self, mock_result, mock_bead_store, mock_beads_module
    ):
        """When success=True, set status to COMPLETED."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store
        mock_bead = MagicMock()
        mock_bead.metadata = {}
        mock_bead_store.get = AsyncMock(return_value=mock_bead)

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await update_debate_bead(
                bead_id="bead-123",
                result=mock_result,
                success=True,
                bead_store_holder=holder,
            )

            mock_bead_store.update_status.assert_called_once_with(
                "bead-123", mock_beads_module.BeadStatus.COMPLETED
            )

    @pytest.mark.asyncio
    async def test_sets_status_failed_on_failure(
        self, mock_result, mock_bead_store, mock_beads_module
    ):
        """When success=False, set status to FAILED."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        holder = MagicMock()
        holder._bead_store = mock_bead_store
        mock_bead = MagicMock()
        mock_bead.metadata = {}
        mock_bead_store.get = AsyncMock(return_value=mock_bead)

        with patch.dict(sys.modules, {"aragora.nomic.beads": mock_beads_module}):
            await update_debate_bead(
                bead_id="bead-123",
                result=mock_result,
                success=False,
                bead_store_holder=holder,
            )

            mock_bead_store.update_status.assert_called_once_with(
                "bead-123", mock_beads_module.BeadStatus.FAILED
            )


# =============================================================================
# Tests for init_hook_tracking
# =============================================================================


class TestInitHookTracking:
    """Tests for init_hook_tracking function."""

    @pytest.fixture
    def mock_hook_registry(self):
        registry = MagicMock()
        mock_queue = MagicMock()
        mock_entry = MagicMock()
        mock_entry.id = "entry-123"
        mock_queue.push = AsyncMock(return_value=mock_entry)
        registry.get_queue = AsyncMock(return_value=mock_queue)
        return registry

    @pytest.mark.asyncio
    async def test_skips_when_hook_tracking_disabled(self, mock_agents):
        """When hook tracking is disabled, return empty dict."""
        from aragora.debate.orchestrator_hooks import init_hook_tracking

        protocol = MagicMock()
        protocol.enable_hook_tracking = False

        result = await init_hook_tracking(
            debate_id="debate-123",
            bead_id="bead-456",
            protocol=protocol,
            agents=mock_agents,
            hook_registry_holder=MagicMock(),
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_when_bead_id_empty(self, mock_protocol, mock_agents):
        """When bead_id is empty, return empty dict."""
        from aragora.debate.orchestrator_hooks import init_hook_tracking

        result = await init_hook_tracking(
            debate_id="debate-123",
            bead_id="",
            protocol=mock_protocol,
            agents=mock_agents,
            hook_registry_holder=MagicMock(),
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_pushes_to_all_agent_hooks(
        self, mock_protocol, mock_agents, mock_hook_registry, mock_hook_queue_module
    ):
        """When enabled, push to each agent's hook queue."""
        from aragora.debate.orchestrator_hooks import init_hook_tracking

        holder = MagicMock()
        holder._hook_registry = mock_hook_registry
        holder._bead_store = MagicMock()

        with patch.dict(sys.modules, {"aragora.nomic.hook_queue": mock_hook_queue_module}):
            result = await init_hook_tracking(
                debate_id="debate-123",
                bead_id="bead-456",
                protocol=mock_protocol,
                agents=mock_agents,
                hook_registry_holder=holder,
            )

        assert len(result) == len(mock_agents)

    @pytest.mark.asyncio
    async def test_handles_individual_agent_failures(
        self, mock_protocol, mock_agents, mock_hook_registry, mock_hook_queue_module
    ):
        """When one agent fails, continue with others."""
        from aragora.debate.orchestrator_hooks import init_hook_tracking

        holder = MagicMock()
        holder._hook_registry = mock_hook_registry
        holder._bead_store = MagicMock()

        # Make first agent fail
        call_count = [0]

        async def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Failed")
            mock_entry = MagicMock()
            mock_entry.id = f"entry-{call_count[0]}"
            return mock_entry

        mock_queue = MagicMock()
        mock_queue.push = side_effect
        mock_hook_registry.get_queue = AsyncMock(return_value=mock_queue)

        with patch.dict(sys.modules, {"aragora.nomic.hook_queue": mock_hook_queue_module}):
            result = await init_hook_tracking(
                debate_id="debate-123",
                bead_id="bead-456",
                protocol=mock_protocol,
                agents=mock_agents,
                hook_registry_holder=holder,
            )

        # Should have 2 successful entries (3 agents, 1 failed)
        assert len(result) == 2


# =============================================================================
# Tests for complete_hook_tracking
# =============================================================================


class TestCompleteHookTracking:
    """Tests for complete_hook_tracking function."""

    @pytest.fixture
    def mock_hook_registry(self):
        registry = MagicMock()
        mock_queue = MagicMock()
        mock_queue.complete = AsyncMock()
        mock_queue.fail = AsyncMock()
        registry.get_queue = AsyncMock(return_value=mock_queue)
        return registry

    @pytest.mark.asyncio
    async def test_skips_when_hook_entries_empty(self):
        """When hook_entries is empty, return without action."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        await complete_hook_tracking(
            bead_id="bead-123",
            hook_entries={},
            success=True,
            hook_registry_holder=MagicMock(),
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_skips_when_bead_id_empty(self):
        """When bead_id is empty, return without action."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        await complete_hook_tracking(
            bead_id="",
            hook_entries={"agent-1": "entry-1"},
            success=True,
            hook_registry_holder=MagicMock(),
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_skips_when_hook_registry_missing(self):
        """When hook_registry is None, return without action."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        holder = MagicMock()
        holder._hook_registry = None

        await complete_hook_tracking(
            bead_id="bead-123",
            hook_entries={"agent-1": "entry-1"},
            success=True,
            hook_registry_holder=holder,
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_completes_on_success(self, mock_hook_registry):
        """When success=True, complete the hooks."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        holder = MagicMock()
        holder._hook_registry = mock_hook_registry

        await complete_hook_tracking(
            bead_id="bead-123",
            hook_entries={"agent-1": "entry-1"},
            success=True,
            hook_registry_holder=holder,
        )

        mock_queue = await mock_hook_registry.get_queue("agent-1")
        mock_queue.complete.assert_called_once_with("bead-123")

    @pytest.mark.asyncio
    async def test_fails_on_success_false(self, mock_hook_registry):
        """When success=False, fail the hooks."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        holder = MagicMock()
        holder._hook_registry = mock_hook_registry

        await complete_hook_tracking(
            bead_id="bead-123",
            hook_entries={"agent-1": "entry-1"},
            success=False,
            hook_registry_holder=holder,
            error_msg="Test error",
        )

        mock_queue = await mock_hook_registry.get_queue("agent-1")
        mock_queue.fail.assert_called_once_with("bead-123", "Test error")


# =============================================================================
# Tests for recover_pending_debates
# =============================================================================


class TestRecoverPendingDebates:
    """Tests for recover_pending_debates function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_work(self, mock_beads_module, mock_hook_queue_module):
        """When no pending work, return empty list."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        mock_store = MagicMock()
        mock_stores = MagicMock()
        mock_stores.bead_store = AsyncMock(return_value=mock_store)

        mock_registry = MagicMock()
        mock_registry.recover_all = AsyncMock(return_value={})
        mock_hook_queue_module.HookQueueRegistry.return_value = mock_registry

        with patch(
            "aragora.debate.orchestrator_hooks.get_workspace_stores", return_value=mock_stores
        ):
            with patch.dict(
                sys.modules,
                {
                    "aragora.nomic.beads": mock_beads_module,
                    "aragora.nomic.hook_queue": mock_hook_queue_module,
                },
            ):
                result = await recover_pending_debates()

        assert result == []

    @pytest.mark.asyncio
    async def test_recovers_pending_debates(self, mock_beads_module, mock_hook_queue_module):
        """When pending work exists, return recovery info."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        mock_store = MagicMock()
        mock_stores = MagicMock()
        mock_stores.bead_store = AsyncMock(return_value=mock_store)

        # Create mock bead
        mock_bead = MagicMock()
        mock_bead.id = "bead-123"
        mock_bead.bead_type = mock_beads_module.BeadType.DEBATE_DECISION
        mock_bead.created_at = datetime.now(timezone.utc)
        mock_bead.status = mock_beads_module.BeadStatus.PENDING
        mock_bead.metadata = {"debate_id": "debate-456"}

        mock_registry = MagicMock()
        mock_registry.recover_all = AsyncMock(
            return_value={
                "agent-1": [mock_bead],
            }
        )
        mock_hook_queue_module.HookQueueRegistry.return_value = mock_registry

        with patch(
            "aragora.debate.orchestrator_hooks.get_workspace_stores", return_value=mock_stores
        ):
            with patch.dict(
                sys.modules,
                {
                    "aragora.nomic.beads": mock_beads_module,
                    "aragora.nomic.hook_queue": mock_hook_queue_module,
                },
            ):
                result = await recover_pending_debates()

        assert len(result) == 1
        assert result[0]["debate_id"] == "debate-456"
        assert "agent-1" in result[0]["agents"]

    @pytest.mark.asyncio
    async def test_filters_by_age_max_hours(self, mock_beads_module, mock_hook_queue_module):
        """Beads older than max_age_hours are filtered out."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        mock_store = MagicMock()
        mock_stores = MagicMock()
        mock_stores.bead_store = AsyncMock(return_value=mock_store)

        # Create old bead (48 hours old)
        mock_bead = MagicMock()
        mock_bead.id = "old-bead"
        mock_bead.bead_type = mock_beads_module.BeadType.DEBATE_DECISION
        mock_bead.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
        mock_bead.status = mock_beads_module.BeadStatus.PENDING
        mock_bead.metadata = {"debate_id": "old-debate"}

        mock_registry = MagicMock()
        mock_registry.recover_all = AsyncMock(
            return_value={
                "agent-1": [mock_bead],
            }
        )
        mock_hook_queue_module.HookQueueRegistry.return_value = mock_registry

        with patch(
            "aragora.debate.orchestrator_hooks.get_workspace_stores", return_value=mock_stores
        ):
            with patch.dict(
                sys.modules,
                {
                    "aragora.nomic.beads": mock_beads_module,
                    "aragora.nomic.hook_queue": mock_hook_queue_module,
                },
            ):
                result = await recover_pending_debates(max_age_hours=24)

        assert result == []

    @pytest.mark.asyncio
    async def test_ignores_completed_beads(self, mock_beads_module, mock_hook_queue_module):
        """Completed beads are not included in recovery."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        mock_store = MagicMock()
        mock_stores = MagicMock()
        mock_stores.bead_store = AsyncMock(return_value=mock_store)

        mock_bead = MagicMock()
        mock_bead.id = "completed-bead"
        mock_bead.bead_type = mock_beads_module.BeadType.DEBATE_DECISION
        mock_bead.created_at = datetime.now(timezone.utc)
        mock_bead.status = mock_beads_module.BeadStatus.COMPLETED
        mock_bead.metadata = {"debate_id": "completed-debate"}

        mock_registry = MagicMock()
        mock_registry.recover_all = AsyncMock(
            return_value={
                "agent-1": [mock_bead],
            }
        )
        mock_hook_queue_module.HookQueueRegistry.return_value = mock_registry

        with patch(
            "aragora.debate.orchestrator_hooks.get_workspace_stores", return_value=mock_stores
        ):
            with patch.dict(
                sys.modules,
                {
                    "aragora.nomic.beads": mock_beads_module,
                    "aragora.nomic.hook_queue": mock_hook_queue_module,
                },
            ):
                result = await recover_pending_debates()

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_import_error(self):
        """When import fails, return empty list."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        with patch.dict(sys.modules, {"aragora.nomic.beads": None}):
            result = await recover_pending_debates()

        assert result == []
