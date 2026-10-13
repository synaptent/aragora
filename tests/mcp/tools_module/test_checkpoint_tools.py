"""Tests for MCP checkpoint tools execution logic."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.checkpoint import (
    create_checkpoint_tool,
    delete_checkpoint_tool,
    list_checkpoints_tool,
    resume_checkpoint_tool,
)


def _make_storage_module(db_return=None):
    """Create a mock aragora.server.storage module with get_debates_db."""
    mod = MagicMock()
    mod.get_debates_db.return_value = db_return
    return mod


def _make_checkpoint_module(**overrides):
    """Create a mock aragora.debate.checkpoint module."""
    mod = MagicMock()
    # Set defaults; callers can override via overrides dict
    for key, value in overrides.items():
        setattr(mod, key, value)
    return mod


def _make_core_module():
    """Create a mock aragora.core module with Message, Vote, Critique."""
    mod = MagicMock()
    return mod


def _make_settings_module(default_rounds=3):
    """Create a mock aragora.config.settings module with DebateSettings."""
    mod = MagicMock()
    mod.DebateSettings.return_value.default_rounds = default_rounds
    return mod


class TestCreateCheckpointTool:
    """Tests for create_checkpoint_tool."""

    @pytest.mark.asyncio
    async def test_create_empty_debate_id(self):
        """Test create with empty debate_id."""
        result = await create_checkpoint_tool(debate_id="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_no_storage(self):
        """Test create when storage unavailable."""
        mock_storage = _make_storage_module(db_return=None)
        mock_checkpoint_mod = _make_checkpoint_module()
        mock_core = _make_core_module()
        mock_settings = _make_settings_module()

        with patch.dict(
            "sys.modules",
            {
                "aragora.storage.debate_storage": mock_storage,
                "aragora.debate.checkpoint": mock_checkpoint_mod,
                "aragora.core": mock_core,
                "aragora.config.settings": mock_settings,
            },
        ):
            result = await create_checkpoint_tool(debate_id="d-001")

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_debate_not_found(self):
        """Test create for non-existent debate."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        mock_storage = _make_storage_module(db_return=mock_db)
        mock_checkpoint_mod = _make_checkpoint_module()
        mock_core = _make_core_module()
        mock_settings = _make_settings_module()

        with patch.dict(
            "sys.modules",
            {
                "aragora.storage.debate_storage": mock_storage,
                "aragora.debate.checkpoint": mock_checkpoint_mod,
                "aragora.core": mock_core,
                "aragora.config.settings": mock_settings,
            },
        ):
            result = await create_checkpoint_tool(debate_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_create_success(self):
        """Test successful checkpoint creation."""
        # Set up debate DB
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "task": "Test debate",
            "messages": [
                {"role": "proposer", "agent": "claude", "content": "Msg 1", "round": 1},
            ],
            "votes": [],
            "critiques": [],
            "agents": ["claude", "gpt4"],
            "rounds_used": 1,
            "final_answer": "Test answer",
        }

        mock_storage = _make_storage_module(db_return=mock_db)

        # Set up checkpoint mock
        mock_checkpoint_obj = MagicMock()
        mock_checkpoint_obj.checkpoint_id = "cp-001"
        mock_checkpoint_obj.current_round = 1
        mock_checkpoint_obj.messages = [MagicMock()]
        mock_checkpoint_obj.created_at = "2025-01-01T00:00:00"

        mock_manager = AsyncMock()
        mock_manager.create_checkpoint.return_value = mock_checkpoint_obj

        mock_checkpoint_mod = _make_checkpoint_module()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager
        mock_checkpoint_mod.FileCheckpointStore.return_value = MagicMock()

        mock_core = _make_core_module()
        mock_settings = _make_settings_module(default_rounds=3)

        with patch.dict(
            "sys.modules",
            {
                "aragora.storage.debate_storage": mock_storage,
                "aragora.debate.checkpoint": mock_checkpoint_mod,
                "aragora.core": mock_core,
                "aragora.config.settings": mock_settings,
            },
        ):
            result = await create_checkpoint_tool(
                debate_id="d-001",
                label="Before revision",
                storage_backend="file",
            )

        assert result["success"] is True
        assert result["checkpoint_id"] == "cp-001"
        assert result["debate_id"] == "d-001"
        assert result["label"] == "Before revision"

    @pytest.mark.asyncio
    async def test_create_import_error(self):
        """Test create when checkpoint module unavailable."""
        # Remove the module from sys.modules so import fails
        # We need the import of aragora.debate.checkpoint to raise ImportError.
        # Since create_checkpoint_tool imports aragora.server.storage first, then
        # aragora.debate.checkpoint, we provide storage but make checkpoint raise.
        mock_storage = _make_storage_module(db_return=MagicMock())
        mock_core = _make_core_module()

        # Create a module proxy that raises ImportError on attribute access
        # for CheckpointManager (simulating the from ... import failing).
        # The simplest approach: remove aragora.debate.checkpoint from sys.modules
        # and ensure it can't be imported.
        import types

        broken_checkpoint = types.ModuleType("aragora.debate.checkpoint")

        def _raise_import(*args, **kwargs):
            raise ImportError("Checkpoint not available")

        # When the function does `from aragora.debate.checkpoint import CheckpointManager`,
        # Python looks up the attribute on the module object. Making __getattr__ raise
        # will cause the import to fail with ImportError.
        broken_checkpoint.__getattr__ = lambda self, name: (_ for _ in ()).throw(
            ImportError("Checkpoint not available")
        )

        # Actually, a simpler approach: just don't put it in sys.modules and let
        # the real import fail. But that might succeed if the real module exists.
        # Safest: put a module object that lacks the needed attributes.
        class _BrokenModule(types.ModuleType):
            def __getattr__(self, name):
                raise ImportError("Checkpoint not available")

        broken = _BrokenModule("aragora.debate.checkpoint")

        with patch.dict(
            "sys.modules",
            {
                "aragora.storage.debate_storage": mock_storage,
                "aragora.core": mock_core,
                "aragora.debate.checkpoint": broken,
            },
        ):
            result = await create_checkpoint_tool(debate_id="d-001")

        assert "error" in result


class TestListCheckpointsTool:
    """Tests for list_checkpoints_tool."""

    @pytest.mark.asyncio
    async def test_list_success(self):
        """Test successful checkpoint listing."""
        mock_store = AsyncMock()
        mock_store.list_checkpoints.return_value = [
            {
                "checkpoint_id": "cp-001",
                "debate_id": "d-001",
                "task": "Test",
                "current_round": 2,
                "message_count": 6,
            },
        ]

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await list_checkpoints_tool(debate_id="d-001")

        assert result["count"] == 1
        assert result["checkpoints"][0]["checkpoint_id"] == "cp-001"
        assert result["debate_id"] == "d-001"

    @pytest.mark.asyncio
    async def test_list_all_debates(self):
        """Test listing checkpoints for all debates."""
        mock_store = AsyncMock()
        mock_store.list_checkpoints.return_value = []

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await list_checkpoints_tool()

        assert result["count"] == 0
        assert result["debate_id"] == "(all)"

    @pytest.mark.asyncio
    async def test_list_clamps_limit(self):
        """Test list clamps limit to valid range."""
        mock_store = AsyncMock()
        mock_store.list_checkpoints.return_value = []

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            # limit=0 should be clamped to 1
            result = await list_checkpoints_tool(limit=0)

        mock_store.list_checkpoints.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_import_error(self):
        """Test list when checkpoint module unavailable."""
        import types

        class _BrokenModule(types.ModuleType):
            def __getattr__(self, name):
                raise ImportError("Not available")

        broken = _BrokenModule("aragora.debate.checkpoint")

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": broken},
        ):
            result = await list_checkpoints_tool()

        assert "error" in result


class TestResumeCheckpointTool:
    """Tests for resume_checkpoint_tool."""

    @pytest.mark.asyncio
    async def test_resume_empty_id(self):
        """Test resume with empty checkpoint_id."""
        result = await resume_checkpoint_tool(checkpoint_id="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_resume_not_found(self):
        """Test resume for non-existent checkpoint."""
        mock_store = AsyncMock()
        mock_store.load.return_value = None

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await resume_checkpoint_tool(checkpoint_id="cp-nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_resume_success(self):
        """Test successful checkpoint resume."""
        mock_checkpoint = MagicMock()
        mock_checkpoint.debate_id = "d-001"
        mock_checkpoint.messages = [MagicMock(), MagicMock()]
        mock_checkpoint.current_round = 2
        mock_checkpoint.phase = "revision"
        mock_checkpoint.task = "Test debate"

        mock_store = AsyncMock()
        mock_store.load.return_value = mock_checkpoint

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await resume_checkpoint_tool(checkpoint_id="cp-001")

        assert result["success"] is True
        assert result["debate_id"] == "d-001"
        assert result["messages_count"] == 2
        assert result["round"] == 2
        assert result["phase"] == "revision"


class TestDeleteCheckpointTool:
    """Tests for delete_checkpoint_tool."""

    @pytest.mark.asyncio
    async def test_delete_empty_id(self):
        """Test delete with empty checkpoint_id."""
        result = await delete_checkpoint_tool(checkpoint_id="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test successful checkpoint deletion."""
        mock_store = AsyncMock()
        mock_store.delete.return_value = True

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await delete_checkpoint_tool(checkpoint_id="cp-001")

        assert result["success"] is True
        assert "deleted" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """Test delete for non-existent checkpoint."""
        mock_store = AsyncMock()
        mock_store.delete.return_value = False

        mock_manager = MagicMock()
        mock_manager.store = mock_store

        mock_checkpoint_mod = MagicMock()
        mock_checkpoint_mod.CheckpointManager.return_value = mock_manager

        with patch.dict(
            "sys.modules",
            {"aragora.debate.checkpoint": mock_checkpoint_mod},
        ):
            result = await delete_checkpoint_tool(checkpoint_id="cp-nonexistent")

        assert result["success"] is False
        assert "not found" in result["message"].lower()
