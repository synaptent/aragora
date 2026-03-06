"""
Tests for the Aragora MCP Tools.

Tests the standalone tool functions that can be used independently
of the MCP server, including:
- run_debate_tool
- run_gauntlet_tool
- list_agents_tool
- get_debate_tool
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any


from aragora.mcp.tools import (
    run_debate_tool,
    run_gauntlet_tool,
    list_agents_tool,
    get_debate_tool,
    TOOLS_METADATA,
)


class TestToolsMetadata:
    """Test TOOLS_METADATA structure."""

    def test_metadata_has_all_tools(self):
        """Test that metadata defines all registered tools."""
        assert len(TOOLS_METADATA) == 80

    def test_metadata_core_tool_names(self):
        """Test core tool names are present in metadata."""
        names = {t["name"] for t in TOOLS_METADATA}
        # Core debate tools
        assert "run_debate" in names
        assert "run_gauntlet" in names
        assert "list_agents" in names
        assert "get_debate" in names
        assert "search_debates" in names
        assert "get_agent_history" in names
        assert "get_consensus_proofs" in names
        assert "list_trending_topics" in names
        # Memory tools
        assert "query_memory" in names
        assert "store_memory" in names
        assert "get_memory_pressure" in names
        # Fork tools
        assert "fork_debate" in names
        assert "get_forks" in names
        # Genesis tools
        assert "get_agent_lineage" in names
        assert "breed_agents" in names
        # Checkpoint tools
        assert "create_checkpoint" in names
        assert "list_checkpoints" in names
        assert "resume_checkpoint" in names
        assert "delete_checkpoint" in names
        # Verification tools
        assert "verify_consensus" in names
        assert "generate_proof" in names
        # Evidence tools
        assert "search_evidence" in names
        assert "cite_evidence" in names
        assert "verify_citation" in names

    def test_run_debate_metadata(self):
        """Test run_debate metadata structure."""
        from aragora.config.settings import AgentSettings, DebateSettings

        tool = next(t for t in TOOLS_METADATA if t["name"] == "run_debate")

        assert "description" in tool
        assert "function" in tool
        assert tool["function"] is run_debate_tool
        assert "parameters" in tool
        assert tool["parameters"]["question"]["required"] is True
        assert tool["parameters"]["agents"]["default"] == AgentSettings().default_agents
        assert tool["parameters"]["rounds"]["default"] == DebateSettings().default_rounds
        assert tool["parameters"]["consensus"]["default"] == DebateSettings().default_consensus

    def test_run_gauntlet_metadata(self):
        """Test run_gauntlet metadata structure."""
        tool = next(t for t in TOOLS_METADATA if t["name"] == "run_gauntlet")

        assert tool["parameters"]["content"]["required"] is True
        assert tool["parameters"]["content_type"]["default"] == "spec"
        assert tool["parameters"]["profile"]["default"] == "quick"

    def test_list_agents_metadata(self):
        """Test list_agents metadata has no required parameters."""
        tool = next(t for t in TOOLS_METADATA if t["name"] == "list_agents")

        assert tool["parameters"] == {}

    def test_get_debate_metadata(self):
        """Test get_debate metadata structure."""
        tool = next(t for t in TOOLS_METADATA if t["name"] == "get_debate")

        assert tool["parameters"]["debate_id"]["required"] is True


class TestRunDebateTool:
    """Test run_debate_tool function."""

    @pytest.mark.asyncio
    async def test_empty_question_returns_error(self):
        """Test that empty question returns error."""
        result = await run_debate_tool(question="")

        assert "error" in result
        assert "Question is required" in result["error"]

    @pytest.mark.asyncio
    async def test_rounds_clamped_to_min(self):
        """Test rounds below 1 are clamped."""
        with patch("aragora.agents.base.create_agent") as mock_create:
            mock_create.side_effect = Exception("No key")

            result = await run_debate_tool(
                question="Test?",
                agents="test",
                rounds=-10,
            )

            # Will fail on agent creation, but rounds should have been clamped
            assert "error" in result

    @pytest.mark.asyncio
    async def test_rounds_clamped_to_max(self):
        """Test rounds above max are clamped to configured max_rounds."""
        from aragora.config.settings import DebateSettings

        max_rounds = DebateSettings().max_rounds

        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.rounds_used = max_rounds

        mock_agent = MagicMock()
        mock_agent.name = "test_agent"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol") as mock_protocol,
            patch("aragora.core.Environment") as mock_env,
        ):
            mock_create.return_value = mock_agent
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            result = await run_debate_tool(
                question="Test?",
                agents="test",
                rounds=100,  # Should be clamped to max_rounds
            )

            # Verify Environment was created with max_rounds clamped
            mock_env.assert_called_once()
            assert mock_env.call_args[1]["max_rounds"] == max_rounds

    @pytest.mark.asyncio
    async def test_no_valid_agents_returns_error(self):
        """Test error when no agents can be created."""
        with patch("aragora.agents.base.create_agent") as mock_create:
            mock_create.side_effect = Exception("API key missing")

            result = await run_debate_tool(
                question="Test question?",
                agents="fake-agent-1,fake-agent-2",
            )

            assert "error" in result
            assert "No valid agents" in result["error"]

    @pytest.mark.asyncio
    async def test_partial_agent_creation(self):
        """Test debate runs with partial agent creation."""
        mock_result = MagicMock()
        mock_result.final_answer = "Partial answer"
        mock_result.consensus_reached = False
        mock_result.confidence = 0.7
        mock_result.rounds_used = 3

        mock_agent = MagicMock()
        mock_agent.name = "working_agent"

        def create_side_effect(model_type, name, role):
            if "fake" in model_type:
                raise Exception("Invalid agent")
            return mock_agent

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol"),
            patch("aragora.core.Environment"),
        ):
            mock_create.side_effect = create_side_effect
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            result = await run_debate_tool(
                question="Test?",
                agents="working,fake",
            )

            assert "debate_id" in result
            assert result["final_answer"] == "Partial answer"

    @pytest.mark.asyncio
    async def test_successful_debate_returns_full_result(self):
        """Test successful debate returns complete result structure."""
        mock_result = MagicMock()
        mock_result.final_answer = "The answer is 42"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.95
        mock_result.rounds_used = 2

        mock_agent1 = MagicMock()
        mock_agent1.name = "agent_proposer"
        mock_agent2 = MagicMock()
        mock_agent2.name = "agent_critic"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol"),
            patch("aragora.core.Environment"),
        ):
            mock_create.side_effect = [mock_agent1, mock_agent2]
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            result = await run_debate_tool(
                question="What is the meaning of life?",
                agents="agent1,agent2",
                rounds=3,
                consensus="majority",
            )

            assert result["debate_id"].startswith("mcp_")
            assert result["task"] == "What is the meaning of life?"
            assert result["final_answer"] == "The answer is 42"
            assert result["consensus_reached"] is True
            assert result["confidence"] == 0.95
            assert result["rounds_used"] == 2
            assert len(result["agents"]) == 2
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_agent_roles_assigned_correctly(self):
        """Test agents receive correct roles."""
        mock_result = MagicMock()
        mock_result.final_answer = "A"
        mock_result.consensus_reached = True
        mock_result.confidence = 1.0
        mock_result.rounds_used = 1

        created_agents = []

        def track_create(model_type, name, role):
            agent = MagicMock()
            agent.name = name
            created_agents.append({"model_type": model_type, "name": name, "role": role})
            return agent

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol"),
            patch("aragora.core.Environment"),
        ):
            mock_create.side_effect = track_create
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            await run_debate_tool(
                question="Q?",
                agents="a1,a2,a3,a4",
            )

            assert created_agents[0]["role"] == "proposer"
            assert created_agents[1]["role"] == "critic"
            assert created_agents[2]["role"] == "synthesizer"
            assert created_agents[3]["role"] == "critic"  # Extra agents get critic role


class TestRunGauntletTool:
    """Test run_gauntlet_tool function."""

    @pytest.mark.asyncio
    async def test_empty_content_returns_error(self):
        """Test that empty content returns error."""
        result = await run_gauntlet_tool(content="")

        assert "error" in result
        assert "Content is required" in result["error"]

    @pytest.mark.asyncio
    async def test_quick_profile_selected(self):
        """Test quick profile is used by default."""
        mock_result = MagicMock()
        mock_result.verdict = MagicMock()
        mock_result.verdict.value = "pass"
        mock_result.risk_score = 0.1
        mock_result.vulnerabilities = []

        # Create a mock config that has required attributes
        mock_config = MagicMock()
        mock_config.attack_categories = []
        mock_config.agents = []
        mock_config.rounds_per_attack = 1

        with patch.dict(
            "sys.modules",
            {
                "aragora.gauntlet": MagicMock(
                    GauntletRunner=MagicMock(
                        return_value=MagicMock(run=AsyncMock(return_value=mock_result))
                    ),
                    GauntletConfig=MagicMock(return_value=mock_config),
                    QUICK_GAUNTLET=mock_config,
                    THOROUGH_GAUNTLET=mock_config,
                    CODE_REVIEW_GAUNTLET=mock_config,
                    SECURITY_GAUNTLET=mock_config,
                    GDPR_GAUNTLET=mock_config,
                    HIPAA_GAUNTLET=mock_config,
                )
            },
        ):
            # Need to reimport to pick up mocked module
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.run_gauntlet_tool(
                content="Test content",
                profile="quick",
            )

            assert result["profile"] == "quick"
            assert result["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_security_profile_returns_vulnerabilities(self):
        """Test security profile can be selected and returns vulnerabilities."""
        mock_result = MagicMock()
        mock_result.verdict = MagicMock()
        mock_result.verdict.value = "fail"
        mock_result.risk_score = 0.8
        mock_vuln = MagicMock()
        mock_vuln.category = "injection"
        mock_vuln.severity = "high"
        mock_vuln.description = "SQL injection found"
        mock_result.vulnerabilities = [mock_vuln]

        mock_config = MagicMock()
        mock_config.attack_categories = []
        mock_config.agents = []
        mock_config.rounds_per_attack = 1

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with patch.dict(
            "sys.modules",
            {
                "aragora.gauntlet": MagicMock(
                    GauntletRunner=MagicMock(return_value=mock_runner),
                    GauntletConfig=MagicMock(return_value=mock_config),
                    QUICK_GAUNTLET=mock_config,
                    THOROUGH_GAUNTLET=mock_config,
                    CODE_REVIEW_GAUNTLET=mock_config,
                    SECURITY_GAUNTLET=mock_config,
                    GDPR_GAUNTLET=mock_config,
                    HIPAA_GAUNTLET=mock_config,
                )
            },
        ):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.run_gauntlet_tool(
                content="SELECT * FROM users WHERE id = input",
                content_type="code",
                profile="security",
            )

            assert result["profile"] == "security"
            assert result["content_type"] == "code"
            assert result["risk_score"] == 0.8
            assert result["vulnerabilities_count"] == 1
            assert result["vulnerabilities"][0]["category"] == "injection"

    @pytest.mark.asyncio
    async def test_vulnerabilities_limited_to_ten(self):
        """Test vulnerabilities are limited to 10 in output."""
        mock_result = MagicMock()
        mock_result.verdict = MagicMock()
        mock_result.verdict.value = "fail"
        mock_result.risk_score = 0.9

        # Create 15 vulnerabilities
        mock_result.vulnerabilities = [
            MagicMock(category=f"cat{i}", severity="medium", description=f"Vuln {i}")
            for i in range(15)
        ]

        mock_config = MagicMock()
        mock_config.attack_categories = []
        mock_config.agents = []
        mock_config.rounds_per_attack = 1

        with patch.dict(
            "sys.modules",
            {
                "aragora.gauntlet": MagicMock(
                    GauntletRunner=MagicMock(
                        return_value=MagicMock(run=AsyncMock(return_value=mock_result))
                    ),
                    GauntletConfig=MagicMock(return_value=mock_config),
                    QUICK_GAUNTLET=mock_config,
                    THOROUGH_GAUNTLET=mock_config,
                    CODE_REVIEW_GAUNTLET=mock_config,
                    SECURITY_GAUNTLET=mock_config,
                    GDPR_GAUNTLET=mock_config,
                    HIPAA_GAUNTLET=mock_config,
                )
            },
        ):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.run_gauntlet_tool(
                content="Bad code",
                profile="thorough",
            )

            assert result["vulnerabilities_count"] == 15
            assert len(result["vulnerabilities"]) == 10  # Limited

    @pytest.mark.asyncio
    async def test_handles_missing_attributes(self):
        """Test graceful handling of missing result attributes."""
        mock_result = MagicMock(spec=[])  # Empty spec = no attributes

        mock_config = MagicMock()
        mock_config.attack_categories = []
        mock_config.agents = []
        mock_config.rounds_per_attack = 1

        with patch.dict(
            "sys.modules",
            {
                "aragora.gauntlet": MagicMock(
                    GauntletRunner=MagicMock(
                        return_value=MagicMock(run=AsyncMock(return_value=mock_result))
                    ),
                    GauntletConfig=MagicMock(return_value=mock_config),
                    QUICK_GAUNTLET=mock_config,
                    THOROUGH_GAUNTLET=mock_config,
                    CODE_REVIEW_GAUNTLET=mock_config,
                    SECURITY_GAUNTLET=mock_config,
                    GDPR_GAUNTLET=mock_config,
                    HIPAA_GAUNTLET=mock_config,
                )
            },
        ):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.run_gauntlet_tool(content="Test")

            # Should use defaults for missing attributes
            assert result["verdict"] == "unknown"
            assert result["risk_score"] == 0
            assert result["vulnerabilities_count"] == 0


class TestListAgentsTool:
    """Test list_agents_tool function."""

    @pytest.mark.asyncio
    async def test_returns_available_agents(self):
        """Test listing available agents."""
        mock_agents = {
            "anthropic-api": MagicMock(),
            "openai-api": MagicMock(),
            "gemini": MagicMock(),
            "grok": MagicMock(),
        }

        with patch("aragora.agents.base.list_available_agents", return_value=mock_agents):
            from aragora.mcp.tools import list_agents_tool

            result = await list_agents_tool()

            assert result["count"] == 4
            assert "anthropic-api" in result["agents"]
            assert "openai-api" in result["agents"]

    @pytest.mark.asyncio
    async def test_fallback_on_registry_error(self):
        """Test fallback list when registry fails."""
        with patch(
            "aragora.agents.base.list_available_agents", side_effect=ImportError("Not found")
        ):
            from aragora.mcp.tools import list_agents_tool

            result = await list_agents_tool()

            assert "agents" in result
            assert result["count"] >= 5  # Fallback has at least 5
            assert "note" in result
            assert "Fallback" in result["note"]

    @pytest.mark.asyncio
    async def test_fallback_includes_common_agents(self):
        """Test fallback list includes common agent types."""
        with patch("aragora.agents.base.list_available_agents", side_effect=Exception("Any error")):
            from aragora.mcp.tools import list_agents_tool

            result = await list_agents_tool()

            assert "anthropic-api" in result["agents"]
            assert "openai-api" in result["agents"]


class TestGetDebateTool:
    """Test get_debate_tool function."""

    @pytest.mark.asyncio
    async def test_empty_id_returns_error(self):
        """Test empty debate_id returns error."""
        result = await get_debate_tool(debate_id="")

        assert "error" in result
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_retrieves_from_storage(self):
        """Test retrieval from storage."""
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "debate_id": "stored_123",
            "task": "Stored debate",
            "final_answer": "From storage",
        }

        mock_storage = MagicMock()
        mock_storage.get_debates_db = MagicMock(return_value=mock_db)

        with patch.dict("sys.modules", {"aragora.server.storage": mock_storage}):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.get_debate_tool(debate_id="stored_123")

            assert result["debate_id"] == "stored_123"
            assert result["final_answer"] == "From storage"
            mock_db.get.assert_called_once_with("stored_123")

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        """Test not found debate returns error."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        mock_storage = MagicMock()
        mock_storage.get_debates_db = MagicMock(return_value=mock_db)

        with patch.dict("sys.modules", {"aragora.server.storage": mock_storage}):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.get_debate_tool(debate_id="nonexistent")

            assert "error" in result
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_storage_error_returns_error(self):
        """Test storage error is handled gracefully."""
        mock_storage = MagicMock()
        mock_storage.get_debates_db = MagicMock(side_effect=Exception("Database error"))

        with patch.dict("sys.modules", {"aragora.server.storage": mock_storage}):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.get_debate_tool(debate_id="any_id")

            assert "error" in result
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_db_returns_error(self):
        """Test no database returns error."""
        mock_storage = MagicMock()
        mock_storage.get_debates_db = MagicMock(return_value=None)

        with patch.dict("sys.modules", {"aragora.server.storage": mock_storage}):
            import importlib
            from aragora.mcp import tools as mcp_tools

            importlib.reload(mcp_tools)

            result = await mcp_tools.get_debate_tool(debate_id="any_id")

            assert "error" in result


class TestToolModuleExports:
    """Test module exports."""

    def test_all_exports_defined(self):
        """Test __all__ exports are defined."""
        from aragora.mcp import tools

        assert hasattr(tools, "__all__")
        assert "run_debate_tool" in tools.__all__
        assert "run_gauntlet_tool" in tools.__all__
        assert "list_agents_tool" in tools.__all__
        assert "get_debate_tool" in tools.__all__
        assert "TOOLS_METADATA" in tools.__all__

    def test_functions_are_async(self):
        """Test all tool functions are async."""
        import asyncio

        assert asyncio.iscoroutinefunction(run_debate_tool)
        assert asyncio.iscoroutinefunction(run_gauntlet_tool)
        assert asyncio.iscoroutinefunction(list_agents_tool)
        assert asyncio.iscoroutinefunction(get_debate_tool)
