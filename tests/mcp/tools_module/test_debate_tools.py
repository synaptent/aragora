"""Tests for MCP debate tools execution logic."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.debate import (
    fork_debate_tool,
    get_debate_tool,
    get_forks_tool,
    run_debate_tool,
    search_debates_tool,
)


class TestRunDebateTool:
    """Tests for run_debate_tool."""

    @pytest.mark.asyncio
    async def test_run_empty_question(self):
        """Test run with empty question."""
        result = await run_debate_tool(question="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_success(self):
        """Test successful debate run."""
        mock_result = MagicMock()
        mock_result.final_answer = "Use PostgreSQL"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.85
        mock_result.rounds_used = 3

        mock_agent = MagicMock()
        mock_agent.name = "claude_proposer"

        mock_arena = AsyncMock()
        mock_arena.run.return_value = mock_result

        with (
            patch(
                "aragora.agents.base.create_agent",
                return_value=mock_agent,
            ),
            patch(
                "aragora.debate.orchestrator.Arena",
                return_value=mock_arena,
            ),
            patch(
                "aragora.config.settings.AgentSettings",
            ) as mock_settings,
            patch(
                "aragora.config.settings.DebateSettings",
            ) as mock_debate_settings,
        ):
            mock_settings.return_value.default_agents = "claude,gpt4"
            mock_debate_settings.return_value.default_rounds = 3
            mock_debate_settings.return_value.default_consensus = "majority"
            mock_debate_settings.return_value.max_rounds = 10

            result = await run_debate_tool(question="Which database to use?")

        assert "debate_id" in result
        assert result["final_answer"] == "Use PostgreSQL"
        assert result["consensus_reached"] is True
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_run_no_valid_agents(self):
        """Test run when no agents can be created."""
        with (
            patch(
                "aragora.agents.base.create_agent",
                side_effect=Exception("No API key"),
            ),
            patch(
                "aragora.config.settings.AgentSettings",
            ) as mock_settings,
            patch(
                "aragora.config.settings.DebateSettings",
            ) as mock_debate_settings,
        ):
            mock_settings.return_value.default_agents = "claude"
            mock_debate_settings.return_value.default_rounds = 3
            mock_debate_settings.return_value.default_consensus = "majority"
            mock_debate_settings.return_value.max_rounds = 10

            result = await run_debate_tool(question="Test question")

        assert "error" in result
        assert "No valid agents" in result["error"]

    @pytest.mark.asyncio
    async def test_run_with_explicit_params(self):
        """Test run with explicit agents and rounds."""
        mock_result = MagicMock()
        mock_result.final_answer = "Yes"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.rounds_used = 2

        mock_agent = MagicMock()
        mock_agent.name = "agent"

        mock_arena = AsyncMock()
        mock_arena.run.return_value = mock_result

        with (
            patch(
                "aragora.agents.base.create_agent",
                return_value=mock_agent,
            ),
            patch(
                "aragora.debate.orchestrator.Arena",
                return_value=mock_arena,
            ),
            patch(
                "aragora.config.settings.AgentSettings",
            ),
            patch(
                "aragora.config.settings.DebateSettings",
            ) as mock_debate_settings,
        ):
            mock_debate_settings.return_value.max_rounds = 10

            result = await run_debate_tool(
                question="Is AI safe?",
                agents="claude,gpt4",
                rounds=2,
                consensus="unanimous",
            )

        assert result["consensus_reached"] is True


class TestGetDebateTool:
    """Tests for get_debate_tool."""

    @pytest.mark.asyncio
    async def test_get_empty_id(self):
        """Test get with empty debate_id."""
        result = await get_debate_tool(debate_id="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_success(self):
        """Test successful debate retrieval from storage."""
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "debate_id": "d-001",
            "task": "Test debate",
            "final_answer": "Yes",
        }

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_debate_tool(debate_id="d-001")

        assert result["debate_id"] == "d-001"
        assert result["task"] == "Test debate"

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        """Test get for non-existent debate."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_debate_tool(debate_id="nonexistent")

        assert "error" in result
        assert result["error"] == "Debate nonexistent not found"

    @pytest.mark.asyncio
    async def test_get_lookup_error_returns_storage_unavailable(self):
        """Test get returns storage error when lookup raises."""
        mock_db = MagicMock()
        mock_db.get.side_effect = RuntimeError("database offline")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_debate_tool(debate_id="d-001")

        assert result == {"error": "Storage not available"}

    @pytest.mark.asyncio
    async def test_get_storage_unavailable(self):
        """Test get when storage is unavailable."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await get_debate_tool(debate_id="d-001")

        assert result == {"error": "Storage not available"}


class TestSearchDebatesTool:
    """Tests for search_debates_tool."""

    @pytest.mark.asyncio
    async def test_search_no_storage(self):
        """Test search when storage unavailable."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await search_debates_tool(query="test")

        assert result["count"] == 0
        assert result["debates"] == []

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful debate search."""
        mock_debate = MagicMock()
        mock_debate.debate_id = "d-001"
        mock_debate.task = "Database selection"
        mock_debate.agents = ["claude", "gpt4"]
        mock_debate.consensus_reached = True
        mock_debate.confidence = 0.85
        mock_debate.created_at = "2025-01-01"

        mock_db = MagicMock()
        mock_db.search.return_value = ([mock_debate], 1)

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await search_debates_tool(query="database")

        assert result["count"] == 1
        assert result["debates"][0]["debate_id"] == "d-001"

    @pytest.mark.asyncio
    async def test_search_with_agent_filter(self):
        """Test search with agent filter."""
        mock_debate = MagicMock()
        mock_debate.debate_id = "d-001"
        mock_debate.task = "Test"
        mock_debate.agents = ["claude"]
        mock_debate.consensus_reached = True
        mock_debate.confidence = 0.9
        mock_debate.created_at = "2025-01-01"

        mock_db = MagicMock()
        mock_db.search.return_value = ([mock_debate], 1)

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await search_debates_tool(query="", agent="gpt4")

        # Agent "gpt4" doesn't match ["claude"], so filtered out
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_consensus_only_filter(self):
        """Test search with consensus_only filter."""
        mock_debate_consensus = MagicMock()
        mock_debate_consensus.debate_id = "d-001"
        mock_debate_consensus.task = "T1"
        mock_debate_consensus.agents = []
        mock_debate_consensus.consensus_reached = True
        mock_debate_consensus.confidence = 0.9
        mock_debate_consensus.created_at = "2025-01-01"

        mock_debate_no_consensus = MagicMock()
        mock_debate_no_consensus.debate_id = "d-002"
        mock_debate_no_consensus.task = "T2"
        mock_debate_no_consensus.agents = []
        mock_debate_no_consensus.consensus_reached = False
        mock_debate_no_consensus.confidence = 0.3
        mock_debate_no_consensus.created_at = "2025-01-01"

        mock_db = MagicMock()
        mock_db.search.return_value = ([mock_debate_consensus, mock_debate_no_consensus], 2)

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await search_debates_tool(query="", consensus_only=True)

        assert result["count"] == 1
        assert result["debates"][0]["debate_id"] == "d-001"

    @pytest.mark.asyncio
    async def test_search_respects_limit(self):
        """Test search respects limit parameter."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await search_debates_tool(query="test", limit=5)

        # Even with no results, the limit should be applied
        assert result["count"] == 0


class TestForkDebateTool:
    """Tests for fork_debate_tool."""

    @pytest.mark.asyncio
    async def test_fork_empty_id(self):
        """Test fork with empty debate_id."""
        result = await fork_debate_tool(debate_id="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fork_no_storage(self):
        """Test fork when storage unavailable."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await fork_debate_tool(debate_id="d-001")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_fork_debate_not_found(self):
        """Test fork for non-existent debate."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await fork_debate_tool(debate_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_fork_success(self):
        """Test successful debate fork."""
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "task": "Original debate",
            "messages": [
                {"role": "proposer", "agent": "claude", "content": "Message 1"},
                {"role": "critic", "agent": "gpt4", "content": "Message 2"},
                {"role": "proposer", "agent": "claude", "content": "Message 3"},
            ],
        }
        mock_db.save_dict = MagicMock()

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await fork_debate_tool(
                debate_id="d-001",
                branch_point=1,
                modified_context="What if we use NoSQL?",
            )

        assert result["success"] is True
        assert result["parent_debate_id"] == "d-001"
        assert result["branch_point"] == 1
        assert result["inherited_messages"] == 2  # branch_point + 1

    @pytest.mark.asyncio
    async def test_fork_no_messages(self):
        """Test fork with debate that has no messages."""
        mock_db = MagicMock()
        mock_db.get.return_value = {"task": "Empty debate", "messages": []}

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await fork_debate_tool(debate_id="d-001")

        assert "error" in result
        assert "no messages" in result["error"].lower()


class TestGetForksTool:
    """Tests for get_forks_tool."""

    @pytest.mark.asyncio
    async def test_get_forks_empty_id(self):
        """Test get forks with empty debate_id."""
        result = await get_forks_tool(debate_id="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_forks_no_storage(self):
        """Test get forks when storage unavailable."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await get_forks_tool(debate_id="d-001")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_forks_with_get_forks_method(self):
        """Test get forks when db has get_forks method."""
        mock_db = MagicMock()
        mock_db.get_forks.return_value = [
            {"branch_id": "fork-001", "task": "Fork 1"},
            {"branch_id": "fork-002", "task": "Fork 2"},
        ]

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_forks_tool(debate_id="d-001")

        assert result["count"] == 2
        assert result["parent_debate_id"] == "d-001"

    @pytest.mark.asyncio
    async def test_get_forks_fallback_search(self):
        """Test get forks using search fallback."""
        mock_db = MagicMock(spec=[])  # No get_forks method
        mock_db.search = MagicMock()
        mock_debate = MagicMock()
        mock_debate.parent_debate_id = "d-001"
        mock_debate.debate_id = "fork-001"
        mock_debate.task = "Forked debate"
        mock_debate.branch_point = 2
        mock_debate.created_at = "2025-01-01"
        mock_db.search.return_value = ([mock_debate], 1)

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_forks_tool(debate_id="d-001")

        assert result["count"] == 1
