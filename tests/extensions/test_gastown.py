"""
Tests for the Gastown extension - Developer orchestration layer.

Tests workspace management, convoy tracking, hook persistence, and coordination.
"""

import pytest
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from aragora.extensions.gastown import (
    Workspace,
    WorkspaceConfig,
    Rig,
    RigConfig,
    Convoy,
    ConvoyStatus,
    Hook,
    HookType,
    WorkspaceManager,
    ConvoyTracker,
    HookRunner,
    Coordinator,
)


# =============================================================================
# WorkspaceManager Tests
# =============================================================================


class TestWorkspaceManager:
    """Tests for WorkspaceManager."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> WorkspaceManager:
        """Create a workspace manager with temp storage."""
        return WorkspaceManager(storage_path=tmp_path / "workspaces")

    @pytest.mark.asyncio
    async def test_create_workspace(self, manager: WorkspaceManager, tmp_path: Path):
        """Test creating a workspace."""
        config = WorkspaceConfig(
            name="test-workspace",
            root_path=str(tmp_path / "workspace"),
            description="Test workspace",
        )
        workspace = await manager.create_workspace(config, owner_id="user-1")

        assert workspace.id
        assert workspace.config.name == "test-workspace"
        assert workspace.owner_id == "user-1"
        assert workspace.status == "active"

    @pytest.mark.asyncio
    async def test_get_workspace(self, manager: WorkspaceManager, tmp_path: Path):
        """Test getting a workspace by ID."""
        config = WorkspaceConfig(name="test", root_path=str(tmp_path))
        workspace = await manager.create_workspace(config)

        found = await manager.get_workspace(workspace.id)
        assert found is not None
        assert found.id == workspace.id

        not_found = await manager.get_workspace("nonexistent")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_list_workspaces_with_filters(self, manager: WorkspaceManager, tmp_path: Path):
        """Test listing workspaces with filters."""
        config1 = WorkspaceConfig(name="ws1", root_path=str(tmp_path / "ws1"))
        config2 = WorkspaceConfig(name="ws2", root_path=str(tmp_path / "ws2"))

        await manager.create_workspace(config1, owner_id="user-1", tenant_id="tenant-a")
        await manager.create_workspace(config2, owner_id="user-2", tenant_id="tenant-a")

        # List all
        all_ws = await manager.list_workspaces()
        assert len(all_ws) == 2

        # Filter by owner
        user1_ws = await manager.list_workspaces(owner_id="user-1")
        assert len(user1_ws) == 1
        assert user1_ws[0].config.name == "ws1"

        # Filter by tenant
        tenant_ws = await manager.list_workspaces(tenant_id="tenant-a")
        assert len(tenant_ws) == 2

    @pytest.mark.asyncio
    async def test_delete_workspace(self, manager: WorkspaceManager, tmp_path: Path):
        """Test deleting a workspace."""
        config = WorkspaceConfig(name="test", root_path=str(tmp_path))
        workspace = await manager.create_workspace(config)

        result = await manager.delete_workspace(workspace.id)
        assert result is True

        found = await manager.get_workspace(workspace.id)
        assert found is None

    @pytest.mark.asyncio
    async def test_create_rig(self, manager: WorkspaceManager, tmp_path: Path):
        """Test creating a rig in a workspace."""
        # Create workspace
        ws_config = WorkspaceConfig(name="test", root_path=str(tmp_path))
        workspace = await manager.create_workspace(ws_config)

        # Create a temp repo path
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        # Create rig
        rig_config = RigConfig(
            name="test-rig",
            repo_path=str(repo_path),
            branch="main",
        )
        rig = await manager.create_rig(workspace.id, rig_config)

        assert rig.id
        assert rig.workspace_id == workspace.id
        assert rig.config.name == "test-rig"

        # Verify workspace tracks the rig
        workspace = await manager.get_workspace(workspace.id)
        assert rig.id in workspace.rigs

    @pytest.mark.asyncio
    async def test_rig_max_limit(self, manager: WorkspaceManager, tmp_path: Path):
        """Test that workspace enforces max rigs limit."""
        ws_config = WorkspaceConfig(name="test", root_path=str(tmp_path), max_rigs=1)
        workspace = await manager.create_workspace(ws_config)

        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        # Create first rig (should succeed)
        rig_config = RigConfig(name="rig1", repo_path=str(repo_path))
        await manager.create_rig(workspace.id, rig_config)

        # Create second rig (should fail)
        with pytest.raises(ValueError, match="at max rigs"):
            await manager.create_rig(workspace.id, rig_config)

    @pytest.mark.asyncio
    async def test_assign_agent(self, manager: WorkspaceManager, tmp_path: Path):
        """Test assigning agents to rigs."""
        ws_config = WorkspaceConfig(name="test", root_path=str(tmp_path))
        workspace = await manager.create_workspace(ws_config)

        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        rig_config = RigConfig(name="rig", repo_path=str(repo_path))
        rig = await manager.create_rig(workspace.id, rig_config)

        # Assign agent
        result = await manager.assign_agent(rig.id, "agent-1")
        assert result is True

        # Verify agent is assigned
        rig = await manager.get_rig(rig.id)
        assert "agent-1" in rig.agents

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: WorkspaceManager, tmp_path: Path):
        """Test getting workspace manager statistics."""
        ws_config = WorkspaceConfig(name="test", root_path=str(tmp_path))
        await manager.create_workspace(ws_config)

        stats = await manager.get_stats()
        assert stats["workspaces_total"] == 1
        assert stats["workspaces_active"] == 1


# =============================================================================
# ConvoyTracker Tests
# =============================================================================


class TestConvoyTracker:
    """Tests for ConvoyTracker."""

    @pytest.fixture
    def tracker(self, tmp_path: Path) -> ConvoyTracker:
        """Create a convoy tracker with temp storage.

        Uses a unique subdirectory per invocation to avoid state bleed
        when pytest-rerunfailures retries with the same tmp_path.
        """
        return ConvoyTracker(storage_path=tmp_path / f"convoys-{uuid.uuid4().hex[:8]}")

    @pytest.mark.asyncio
    async def test_create_convoy(self, tracker: ConvoyTracker):
        """Test creating a convoy."""
        convoy = await tracker.create_convoy(
            rig_id="rig-1",
            title="Fix bug #123",
            description="Fix the login bug",
            issue_ref="github:123",
            priority=5,
            tags=["bug", "critical"],
        )

        assert convoy.id
        assert convoy.title == "Fix bug #123"
        assert convoy.status == ConvoyStatus.PENDING
        assert convoy.priority == 5
        assert "bug" in convoy.tags

    @pytest.mark.asyncio
    async def test_convoy_lifecycle(self, tracker: ConvoyTracker):
        """Test convoy state transitions."""
        convoy = await tracker.create_convoy(
            rig_id="rig-1",
            title="Test task",
        )

        # Start work
        convoy = await tracker.start_convoy(convoy.id, "agent-1")
        assert convoy.status == ConvoyStatus.IN_PROGRESS
        assert convoy.current_agent == "agent-1"
        assert convoy.started_at is not None

        # Submit for review
        convoy = await tracker.submit_for_review(convoy.id)
        assert convoy.status == ConvoyStatus.REVIEW

        # Complete
        convoy = await tracker.complete_convoy(convoy.id, result={"output": "done"})
        assert convoy.status == ConvoyStatus.COMPLETED
        assert convoy.completed_at is not None
        assert convoy.result["output"] == "done"

    @pytest.mark.asyncio
    async def test_handoff_convoy(self, tracker: ConvoyTracker):
        """Test handing off a convoy to another agent."""
        convoy = await tracker.create_convoy(rig_id="rig-1", title="Task")
        await tracker.start_convoy(convoy.id, "agent-1")

        convoy = await tracker.handoff_convoy(
            convoy.id, "agent-1", "agent-2", notes="Need help with this"
        )

        assert convoy.current_agent == "agent-2"
        assert convoy.handoff_count == 1
        assert "agent-1" in convoy.assigned_agents
        assert "agent-2" in convoy.assigned_agents

    @pytest.mark.asyncio
    async def test_block_and_unblock(self, tracker: ConvoyTracker):
        """Test blocking and unblocking convoys."""
        convoy = await tracker.create_convoy(rig_id="rig-1", title="Task")
        await tracker.start_convoy(convoy.id, "agent-1")

        # Block
        convoy = await tracker.block_convoy(
            convoy.id, reason="Waiting for API", depends_on=["other-task"]
        )
        assert convoy.status == ConvoyStatus.BLOCKED
        assert convoy.metadata["block_reason"] == "Waiting for API"

        # Unblock
        convoy = await tracker.unblock_convoy(convoy.id)
        assert convoy.status == ConvoyStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_add_artifact(self, tracker: ConvoyTracker):
        """Test adding artifacts to a convoy."""
        convoy = await tracker.create_convoy(rig_id="rig-1", title="Task")

        artifact = await tracker.add_artifact(
            convoy_id=convoy.id,
            artifact_type="diff",
            path="/path/to/change.diff",
            content_hash="abc123",
            size_bytes=1024,
        )

        assert artifact.id
        assert artifact.type == "diff"
        assert artifact.convoy_id == convoy.id

        # List artifacts
        artifacts = await tracker.list_artifacts(convoy.id)
        assert len(artifacts) == 1

    @pytest.mark.asyncio
    async def test_list_convoys_with_filters(self, tracker: ConvoyTracker):
        """Test listing convoys with filters."""
        await tracker.create_convoy(rig_id="rig-1", title="Task 1")
        convoy2 = await tracker.create_convoy(rig_id="rig-2", title="Task 2")
        await tracker.start_convoy(convoy2.id, "agent-1")

        # Filter by rig
        rig1_convoys = await tracker.list_convoys(rig_id="rig-1")
        assert len(rig1_convoys) == 1

        # Filter by status
        in_progress = await tracker.list_convoys(status=ConvoyStatus.IN_PROGRESS)
        assert len(in_progress) == 1

    @pytest.mark.asyncio
    async def test_get_stats(self, tracker: ConvoyTracker):
        """Test getting convoy statistics."""
        await tracker.create_convoy(rig_id="rig-1", title="Task 1")
        convoy2 = await tracker.create_convoy(rig_id="rig-1", title="Task 2")
        await tracker.start_convoy(convoy2.id, "agent-1")

        stats = await tracker.get_stats()
        assert stats["convoys_total"] == 2
        assert stats["convoys_by_status"]["pending"] == 1
        assert stats["convoys_by_status"]["in_progress"] == 1


# =============================================================================
# HookRunner Tests
# =============================================================================


class TestHookRunner:
    """Tests for HookRunner."""

    @pytest.fixture
    def runner(self, tmp_path: Path) -> HookRunner:
        """Create a hook runner with temp storage."""
        return HookRunner(storage_path=tmp_path / "hooks", auto_commit=False)

    @pytest.mark.asyncio
    async def test_create_hook(self, runner: HookRunner, tmp_path: Path):
        """Test creating a git hook."""
        hook = await runner.create_hook(
            rig_id="rig-1",
            hook_type=HookType.PRE_COMMIT,
            path=str(tmp_path / "hook-script"),
            content="#!/bin/bash\nexit 0\n",
        )

        assert hook.id
        assert hook.type == HookType.PRE_COMMIT
        assert hook.enabled is True

        # Verify script was written
        script_path = Path(hook.path)
        assert script_path.exists()
        assert "exit 0" in script_path.read_text()

    @pytest.mark.asyncio
    async def test_list_hooks_with_filters(self, runner: HookRunner, tmp_path: Path):
        """Test listing hooks with filters."""
        await runner.create_hook(
            rig_id="rig-1",
            hook_type=HookType.PRE_COMMIT,
            path=str(tmp_path / "hook1"),
        )
        await runner.create_hook(
            rig_id="rig-2",
            hook_type=HookType.POST_COMMIT,
            path=str(tmp_path / "hook2"),
            enabled=False,
        )

        # Filter by rig
        rig1_hooks = await runner.list_hooks(rig_id="rig-1")
        assert len(rig1_hooks) == 1

        # Filter by type
        pre_commit_hooks = await runner.list_hooks(hook_type=HookType.PRE_COMMIT)
        assert len(pre_commit_hooks) == 1

        # Filter by enabled
        enabled_hooks = await runner.list_hooks(enabled=True)
        assert len(enabled_hooks) == 1

    @pytest.mark.asyncio
    async def test_trigger_hook(self, runner: HookRunner, tmp_path: Path):
        """Test triggering a hook execution."""
        hook = await runner.create_hook(
            rig_id="rig-1",
            hook_type=HookType.PRE_COMMIT,
            path=str(tmp_path / "hook-script"),
            content="#!/bin/bash\necho 'Hello'\nexit 0\n",
        )

        result = await runner.trigger_hook(hook.id)
        assert result["success"] is True
        assert "Hello" in result["stdout"]

        # Verify trigger was recorded
        hook = await runner.get_hook(hook.id)
        assert hook.trigger_count == 1
        assert hook.last_triggered is not None

    @pytest.mark.asyncio
    async def test_persist_and_restore_state(self, runner: HookRunner):
        """Test persisting and restoring state."""
        state = {"task": "refactor", "progress": 50}

        # Persist
        result = await runner.persist_state("rig-1", state, "Test persist")
        assert result["success"] is True
        assert result["hash"]

        # Restore
        restored = await runner.restore_state("rig-1")
        assert restored == state

    @pytest.mark.asyncio
    async def test_get_stats(self, runner: HookRunner, tmp_path: Path):
        """Test getting hook runner statistics."""
        await runner.create_hook(
            rig_id="rig-1",
            hook_type=HookType.PRE_COMMIT,
            path=str(tmp_path / "hook"),
        )

        stats = await runner.get_stats()
        assert stats["hooks_total"] == 1
        assert stats["hooks_enabled"] == 1

    @pytest.mark.asyncio
    async def test_create_worktree_delegates_to_lifecycle(self, runner: HookRunner, tmp_path: Path):
        """create_worktree delegates to shared worktree lifecycle service."""
        repo = tmp_path / "repo"
        worktree = tmp_path / "repo-wt"
        repo.mkdir(parents=True)

        mock_service = MagicMock()
        mock_service.create_worktree.return_value = MagicMock(
            success=True,
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch(
            "aragora.worktree.hook_runner.WorktreeLifecycleService", return_value=mock_service
        ):
            result = await runner.create_worktree(
                repo_path=str(repo),
                worktree_path=str(worktree),
                branch="main",
            )

        assert result["success"] is True
        mock_service.create_worktree.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_worktree_delegates_to_lifecycle(self, runner: HookRunner, tmp_path: Path):
        """remove_worktree delegates to shared worktree lifecycle service."""
        worktree = tmp_path / "repo-wt"
        worktree.mkdir(parents=True)

        mock_service = MagicMock()
        mock_service.remove_worktree.return_value = MagicMock(
            success=True,
            returncode=0,
            stdout="",
            stderr="",
        )

        with patch(
            "aragora.worktree.hook_runner.WorktreeLifecycleService", return_value=mock_service
        ):
            result = await runner.remove_worktree(str(worktree))

        assert result["success"] is True
        mock_service.remove_worktree.assert_called_once()


# =============================================================================
# Coordinator Tests
# =============================================================================


class TestCoordinator:
    """Tests for Coordinator (Mayor)."""

    @pytest.fixture
    def coordinator(self, tmp_path: Path) -> Coordinator:
        """Create a coordinator with temp storage."""
        return Coordinator(
            storage_path=tmp_path / "coordinator",
            auto_persist=False,
        )

    @pytest.mark.asyncio
    async def test_create_workspace(self, coordinator: Coordinator, tmp_path: Path):
        """Test creating a workspace through coordinator."""
        workspace = await coordinator.create_workspace(
            name="my-project",
            root_path=str(tmp_path / "project"),
            owner_id="user-1",
        )

        assert workspace.config.name == "my-project"
        assert workspace.owner_id == "user-1"

    @pytest.mark.asyncio
    async def test_setup_rig(self, coordinator: Coordinator, tmp_path: Path):
        """Test setting up a rig through coordinator."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )

        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        rig = await coordinator.setup_rig(
            workspace_id=workspace.id,
            name="main-rig",
            repo_path=str(repo_path),
        )

        assert rig.config.name == "main-rig"
        assert rig.workspace_id == workspace.id

    @pytest.mark.asyncio
    async def test_start_and_complete_work(self, coordinator: Coordinator, tmp_path: Path):
        """Test starting and completing work through coordinator."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        rig = await coordinator.setup_rig(
            workspace_id=workspace.id,
            name="rig",
            repo_path=str(repo_path),
        )

        # Start work
        convoy = await coordinator.start_work(
            rig_id=rig.id,
            title="Implement feature",
            agent_id="agent-1",
        )

        assert convoy.status == ConvoyStatus.IN_PROGRESS
        assert convoy.current_agent == "agent-1"

        # Complete work
        completed = await coordinator.complete_work(
            convoy_id=convoy.id,
            result={"code": "written"},
        )

        assert completed.status == ConvoyStatus.COMPLETED
        assert completed.result["code"] == "written"

    @pytest.mark.asyncio
    async def test_ledger_entries(self, coordinator: Coordinator, tmp_path: Path):
        """Test creating and managing ledger entries."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )

        # Create entry
        entry = await coordinator.create_ledger_entry(
            workspace_id=workspace.id,
            entry_type="issue",
            title="Bug in login",
            created_by="agent-1",
            labels=["bug"],
        )

        assert entry.type == "issue"
        assert entry.status == "open"

        # List entries
        entries = await coordinator.list_ledger_entries(
            workspace_id=workspace.id, entry_type="issue"
        )
        assert len(entries) == 1

        # Resolve entry
        resolved = await coordinator.resolve_ledger_entry(
            entry_id=entry.id, resolution="Fixed in PR #42"
        )
        assert resolved.status == "resolved"

    @pytest.mark.asyncio
    async def test_handoff_to_agent(self, coordinator: Coordinator, tmp_path: Path):
        """Test handing off work to another agent."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        rig = await coordinator.setup_rig(
            workspace_id=workspace.id,
            name="rig",
            repo_path=str(repo_path),
        )

        convoy = await coordinator.start_work(
            rig_id=rig.id,
            title="Task",
            agent_id="agent-1",
        )

        # Handoff
        convoy = await coordinator.handoff_to_agent(
            convoy_id=convoy.id,
            from_agent="agent-1",
            to_agent="agent-2",
            notes="Please review",
        )

        assert convoy.current_agent == "agent-2"
        assert convoy.handoff_count == 1

    @pytest.mark.asyncio
    async def test_get_workspace_status(self, coordinator: Coordinator, tmp_path: Path):
        """Test getting comprehensive workspace status."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        rig = await coordinator.setup_rig(
            workspace_id=workspace.id,
            name="rig",
            repo_path=str(repo_path),
        )

        await coordinator.start_work(
            rig_id=rig.id,
            title="Active task",
            agent_id="agent-1",
        )

        status = await coordinator.get_workspace_status(workspace.id)

        assert status["workspace"]["name"] == "project"
        assert len(status["rigs"]) == 1
        assert status["rigs"][0]["convoys_active"] == 1

    @pytest.mark.asyncio
    async def test_get_stats(self, coordinator: Coordinator, tmp_path: Path):
        """Test getting coordinator statistics."""
        workspace = await coordinator.create_workspace(
            name="project",
            root_path=str(tmp_path / "project"),
        )

        stats = await coordinator.get_stats()

        assert stats["workspaces"]["workspaces_total"] == 1
        assert "convoys" in stats
        assert "hooks" in stats
        assert "ledger" in stats
