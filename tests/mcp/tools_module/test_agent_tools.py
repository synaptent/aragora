"""Tests for MCP agent tools execution logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.agent import (
    breed_agents_tool,
    get_agent_history_tool,
    get_agent_lineage_tool,
    list_agents_tool,
)


class TestListAgentsTool:
    """Tests for list_agents_tool."""

    @pytest.mark.asyncio
    async def test_list_success(self):
        """Test successful agent listing."""
        mock_agents = {
            "anthropic-api": {},
            "openai-api": {},
            "gemini": {},
        }

        with patch(
            "aragora.agents.base.list_available_agents",
            return_value=mock_agents,
        ):
            result = await list_agents_tool()

        assert result["count"] == 3
        assert "anthropic-api" in result["agents"]
        assert "note" not in result

    @pytest.mark.asyncio
    async def test_list_empty_on_error(self):
        """Test list_agents fails closed with an empty list and error when an error occurs."""
        with patch(
            "aragora.agents.base.list_available_agents",
            side_effect=Exception("Import error"),
        ):
            result = await list_agents_tool()

        assert result["count"] == 0
        assert result["agents"] == []
        assert "error" in result
        assert "Could not list agents" in result["error"]


class TestGetAgentHistoryTool:
    """Tests for get_agent_history_tool."""

    @pytest.mark.asyncio
    async def test_history_missing_agent_name(self):
        """Test history with missing agent name."""
        result = await get_agent_history_tool(agent_name="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_history_with_elo(self):
        """Test history retrieves ELO rating."""
        mock_rating = MagicMock()
        mock_rating.elo = 1650
        mock_rating.wins = 10
        mock_rating.losses = 5
        mock_rating.debates_count = 15

        mock_elo_system = MagicMock()
        mock_elo_system.get_rating.return_value = mock_rating

        with patch(
            "aragora.ranking.elo.EloSystem",
            return_value=mock_elo_system,
        ):
            result = await get_agent_history_tool(
                agent_name="anthropic-api",
                include_debates=False,
            )

        assert result["agent_name"] == "anthropic-api"
        assert result["elo_rating"] == 1650
        assert result["wins"] == 10
        assert result["losses"] == 5

    @pytest.mark.asyncio
    async def test_history_with_storage_stats(self):
        """Test history retrieves storage stats."""
        mock_db = MagicMock()
        mock_db.get_agent_stats.return_value = {
            "total_debates": 25,
            "consensus_rate": 0.8,
            "win_rate": 0.65,
            "avg_confidence": 0.85,
        }

        with (
            patch(
                "aragora.ranking.elo.EloSystem",
                side_effect=Exception("No ELO"),
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
        ):
            result = await get_agent_history_tool(
                agent_name="openai-api",
                include_debates=False,
            )

        assert result["total_debates"] == 25
        assert result["consensus_rate"] == 0.8

    @pytest.mark.asyncio
    async def test_history_with_debates(self):
        """Test history includes recent debates."""
        mock_debate = {
            "debate_id": "debate-123",
            "task": "Test question",
            "agents": ["anthropic-api", "openai-api"],
            "consensus_reached": True,
            "timestamp": "2024-01-01",
        }

        mock_db = MagicMock()
        mock_db.search.return_value = ([mock_debate], 1)

        with (
            patch(
                "aragora.ranking.elo.EloSystem",
                side_effect=Exception("No ELO"),
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
        ):
            result = await get_agent_history_tool(
                agent_name="anthropic-api",
                include_debates=True,
                limit=5,
            )

        assert "recent_debates" in result
        assert len(result["recent_debates"]) == 1
        assert result["recent_debates"][0]["debate_id"] == "debate-123"

    @pytest.mark.asyncio
    async def test_history_graceful_failure(self):
        """Test history returns defaults on all failures."""
        with (
            patch(
                "aragora.ranking.elo.EloSystem",
                side_effect=Exception("No ELO"),
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=None,
            ),
        ):
            result = await get_agent_history_tool(agent_name="test-agent")

        assert result["agent_name"] == "test-agent"
        assert result["elo_rating"] == 1500  # Default
        assert result["total_debates"] == 0


class TestGetAgentLineageTool:
    """Tests for get_agent_lineage_tool."""

    @pytest.mark.asyncio
    async def test_lineage_missing_agent_name(self):
        """Test lineage with missing agent name."""
        result = await get_agent_lineage_tool(agent_name="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_lineage_success(self):
        """Test successful lineage retrieval."""
        mock_genome = MagicMock()
        mock_genome.genome_id = "gen-123"
        mock_genome.name = "evolved-agent"
        mock_genome.generation = 3
        mock_genome.fitness_score = 0.85
        mock_genome.parent_genomes = ["gen-122"]
        mock_genome.model_preference = "gpt-4"
        mock_genome.birth_debate_id = "debate-001"

        mock_parent = MagicMock()
        mock_parent.genome_id = "gen-122"
        mock_parent.name = "parent-agent"
        mock_parent.generation = 2
        mock_parent.fitness_score = 0.8
        mock_parent.parent_genomes = []
        mock_parent.model_preference = "gpt-4"
        mock_parent.birth_debate_id = "debate-000"

        mock_store = MagicMock()
        mock_store.get_by_name.return_value = mock_genome
        mock_store.get.side_effect = lambda x: mock_parent if x == "gen-122" else None

        with patch(
            "aragora.genesis.genome.GenomeStore",
            return_value=mock_store,
        ):
            result = await get_agent_lineage_tool(
                agent_name="evolved-agent",
                depth=5,
            )

        assert result["agent_name"] == "evolved-agent"
        assert result["genome_id"] == "gen-123"
        assert result["generation"] == 3
        assert result["depth_traced"] == 2
        assert len(result["lineage"]) == 2

    @pytest.mark.asyncio
    async def test_lineage_agent_not_found(self):
        """Test lineage when agent not in genesis database."""
        mock_store = MagicMock()
        mock_store.get_by_name.return_value = None
        mock_store.get.return_value = None

        with patch(
            "aragora.genesis.genome.GenomeStore",
            return_value=mock_store,
        ):
            result = await get_agent_lineage_tool(agent_name="unknown-agent")

        assert result["agent_name"] == "unknown-agent"
        assert result["lineage"] == []
        assert result["generation"] == 0
        assert "note" in result

    @pytest.mark.asyncio
    async def test_lineage_depth_clamped(self):
        """Test that depth is clamped to valid range."""
        mock_store = MagicMock()
        mock_store.get_by_name.return_value = None
        mock_store.get.return_value = None

        with patch(
            "aragora.genesis.genome.GenomeStore",
            return_value=mock_store,
        ):
            # Depth below minimum
            result = await get_agent_lineage_tool(agent_name="test", depth=0)
            assert "note" in result  # Returns not found

            # Depth above maximum
            result = await get_agent_lineage_tool(agent_name="test", depth=100)
            assert "note" in result

    @pytest.mark.asyncio
    async def test_lineage_import_error(self):
        """Test lineage when genesis module not available."""
        with patch(
            "aragora.genesis.genome.GenomeStore",
            side_effect=ImportError("Not installed"),
        ):
            result = await get_agent_lineage_tool(agent_name="test-agent")

        assert "error" in result
        assert "not available" in result["error"].lower()


class TestBreedAgentsTool:
    """Tests for breed_agents_tool."""

    @pytest.mark.asyncio
    async def test_breed_missing_parent_a(self):
        """Test breed with missing parent_a."""
        result = await breed_agents_tool(parent_a="", parent_b="agent-b")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_breed_missing_parent_b(self):
        """Test breed with missing parent_b."""
        result = await breed_agents_tool(parent_a="agent-a", parent_b="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_breed_success(self):
        """Test successful agent breeding."""
        mock_genome_a = MagicMock()
        mock_genome_a.genome_id = "gen-a"
        mock_genome_a.name = "agent-a"
        mock_genome_a.generation = 1

        mock_genome_b = MagicMock()
        mock_genome_b.genome_id = "gen-b"
        mock_genome_b.name = "agent-b"
        mock_genome_b.generation = 1

        mock_offspring = MagicMock()
        mock_offspring.genome_id = "gen-offspring"
        mock_offspring.name = "offspring"
        mock_offspring.generation = 2
        mock_offspring.parent_genomes = ["gen-a", "gen-b"]
        mock_offspring.model_preference = "gpt-4"
        mock_offspring.fitness_score = 0.5
        mock_offspring.traits = ["trait1"]
        mock_offspring.expertise = ["expertise1"]

        mock_store = MagicMock()
        mock_store.get_by_name.side_effect = lambda x: (
            mock_genome_a if x == "agent-a" else mock_genome_b if x == "agent-b" else None
        )

        mock_breeder = MagicMock()
        mock_breeder.crossover.return_value = mock_offspring
        mock_breeder.mutate.return_value = mock_offspring

        with (
            patch(
                "aragora.genesis.genome.GenomeStore",
                return_value=mock_store,
            ),
            patch(
                "aragora.genesis.breeding.GenomeBreeder",
                return_value=mock_breeder,
            ),
        ):
            result = await breed_agents_tool(
                parent_a="agent-a",
                parent_b="agent-b",
                mutation_rate=0.2,
            )

        assert result["success"] is True
        assert result["offspring"]["genome_id"] == "gen-offspring"
        assert result["offspring"]["generation"] == 2
        assert result["mutation_rate"] == 0.2
        mock_store.save.assert_called_once_with(mock_offspring)

    @pytest.mark.asyncio
    async def test_breed_parent_not_found(self):
        """Test breed when parent not found."""
        mock_store = MagicMock()
        mock_store.get_by_name.return_value = None
        mock_store.get.return_value = None

        with patch(
            "aragora.genesis.genome.GenomeStore",
            return_value=mock_store,
        ):
            result = await breed_agents_tool(
                parent_a="unknown-a",
                parent_b="unknown-b",
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_breed_mutation_rate_clamped(self):
        """Test that mutation rate is clamped to valid range."""
        mock_genome_a = MagicMock()
        mock_genome_a.genome_id = "gen-a"
        mock_genome_a.name = "agent-a"
        mock_genome_a.generation = 1

        mock_genome_b = MagicMock()
        mock_genome_b.genome_id = "gen-b"
        mock_genome_b.name = "agent-b"
        mock_genome_b.generation = 1

        mock_offspring = MagicMock()
        mock_offspring.genome_id = "gen-off"
        mock_offspring.name = "offspring"
        mock_offspring.generation = 2
        mock_offspring.parent_genomes = []
        mock_offspring.model_preference = "gpt-4"
        mock_offspring.fitness_score = 0.5
        mock_offspring.traits = []
        mock_offspring.expertise = []

        mock_store = MagicMock()
        mock_store.get_by_name.side_effect = lambda x: (
            mock_genome_a if x == "agent-a" else mock_genome_b if x == "agent-b" else None
        )

        mock_breeder = MagicMock()
        mock_breeder.crossover.return_value = mock_offspring
        mock_breeder.mutate.return_value = mock_offspring

        with (
            patch(
                "aragora.genesis.genome.GenomeStore",
                return_value=mock_store,
            ),
            patch(
                "aragora.genesis.breeding.GenomeBreeder",
                return_value=mock_breeder,
            ),
        ):
            # Rate above 1.0 should be clamped
            result = await breed_agents_tool(
                parent_a="agent-a",
                parent_b="agent-b",
                mutation_rate=2.0,
            )
            assert result["mutation_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_breed_import_error(self):
        """Test breed when genesis module not available."""
        with patch(
            "aragora.genesis.genome.GenomeStore",
            side_effect=ImportError("Not installed"),
        ):
            result = await breed_agents_tool(
                parent_a="agent-a",
                parent_b="agent-b",
            )

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_breed_no_mutation(self):
        """Test breed with zero mutation rate."""
        mock_genome_a = MagicMock()
        mock_genome_a.genome_id = "gen-a"
        mock_genome_a.name = "agent-a"
        mock_genome_a.generation = 1

        mock_genome_b = MagicMock()
        mock_genome_b.genome_id = "gen-b"
        mock_genome_b.name = "agent-b"
        mock_genome_b.generation = 1

        mock_offspring = MagicMock()
        mock_offspring.genome_id = "gen-off"
        mock_offspring.name = "offspring"
        mock_offspring.generation = 2
        mock_offspring.parent_genomes = []
        mock_offspring.model_preference = "gpt-4"
        mock_offspring.fitness_score = 0.5
        mock_offspring.traits = []
        mock_offspring.expertise = []

        mock_store = MagicMock()
        mock_store.get_by_name.side_effect = lambda x: (
            mock_genome_a if x == "agent-a" else mock_genome_b if x == "agent-b" else None
        )

        mock_breeder = MagicMock()
        mock_breeder.crossover.return_value = mock_offspring

        with (
            patch(
                "aragora.genesis.genome.GenomeStore",
                return_value=mock_store,
            ),
            patch(
                "aragora.genesis.breeding.GenomeBreeder",
                return_value=mock_breeder,
            ),
        ):
            result = await breed_agents_tool(
                parent_a="agent-a",
                parent_b="agent-b",
                mutation_rate=0.0,
            )

        assert result["success"] is True
        # mutate should not be called when rate is 0
        mock_breeder.mutate.assert_not_called()
