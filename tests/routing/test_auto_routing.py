"""
Tests for auto_route and domain leaderboard functionality in AgentSelector.

Tests cover:
- auto_route() method for automatic task-to-team routing
- get_domain_leaderboard() method for domain-specific rankings
- create_with_defaults() factory method
- Integration between DomainDetector and AgentSelector
- Edge cases in automatic routing
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.routing.domain_matcher import DomainDetector
from aragora.routing.selection import (
    AgentProfile,
    AgentSelector,
    TaskRequirements,
    TeamComposition,
    DEFAULT_AGENT_EXPERTISE,
)


# =============================================================================
# TestAutoRoute - Automatic Task-to-Team Routing
# =============================================================================


class TestAutoRoute:
    """Tests for AgentSelector.auto_route() method."""

    def test_auto_route_detects_domain_and_selects_team(self):
        """auto_route should detect domain and select appropriate team."""
        selector = AgentSelector()

        # Register agents with different expertise
        security_expert = AgentProfile(
            name="security_expert",
            agent_type="claude",
            expertise={"security": 0.95, "api": 0.6},
        )
        api_expert = AgentProfile(
            name="api_expert",
            agent_type="gemini",
            expertise={"security": 0.5, "api": 0.9},
        )
        selector.register_agent(security_expert)
        selector.register_agent(api_expert)

        # Route a security-focused task
        team = selector.auto_route(
            "Fix the authentication vulnerability and add rate limiting",
            task_id="sec-001",
        )

        assert isinstance(team, TeamComposition)
        assert team.task_id == "sec-001"
        # Security expert should be in the team
        agent_names = [a.name for a in team.agents]
        assert "security_expert" in agent_names

    def test_auto_route_generates_task_id(self):
        """auto_route should generate task_id if not provided."""
        selector = AgentSelector()
        selector.register_agent(AgentProfile(name="agent", agent_type="claude"))

        team = selector.auto_route("Some task description")

        assert team.task_id is not None
        assert team.task_id.startswith("task-")

    def test_auto_route_respects_exclude(self):
        """auto_route should respect exclude parameter."""
        selector = AgentSelector()

        selector.register_agent(AgentProfile(name="a1", agent_type="claude"))
        selector.register_agent(AgentProfile(name="a2", agent_type="gemini"))
        selector.register_agent(AgentProfile(name="a3", agent_type="codex"))

        team = selector.auto_route("Some task", exclude=["a1", "a2"])

        agent_names = [a.name for a in team.agents]
        assert "a1" not in agent_names
        assert "a2" not in agent_names

    def test_auto_route_creates_correct_requirements(self):
        """auto_route should create appropriate TaskRequirements."""
        selector = AgentSelector()

        selector.register_agent(
            AgentProfile(name="agent", agent_type="claude", expertise={"performance": 0.9})
        )

        # Use a performance-focused task
        team = selector.auto_route("Optimize the cache and improve latency")

        # The team should have been selected based on performance domain
        # Verify the team composition is valid
        assert len(team.agents) >= 1

    def test_auto_route_detects_multiple_domains(self):
        """auto_route should detect and use multiple domains."""
        selector = AgentSelector()

        # Register multi-domain expert
        multi_expert = AgentProfile(
            name="multi",
            agent_type="claude",
            expertise={"security": 0.8, "api": 0.8, "testing": 0.7},
        )
        selector.register_agent(multi_expert)

        # Task with multiple domains
        team = selector.auto_route("Add authentication tests for the API endpoints")

        assert len(team.agents) >= 1

    def test_auto_route_with_empty_task_text(self):
        """auto_route should handle empty task text (default to general)."""
        selector = AgentSelector()
        selector.register_agent(AgentProfile(name="agent", agent_type="claude"))

        team = selector.auto_route("")

        # Should still select a team using 'general' domain
        assert len(team.agents) >= 1

    def test_auto_route_logs_routing_decision(self):
        """auto_route should log the routing decision."""
        selector = AgentSelector()
        selector.register_agent(AgentProfile(name="agent", agent_type="claude"))

        with patch("aragora.routing.selection.logger") as mock_logger:
            selector.auto_route("Security vulnerability fix", task_id="test-123")

            # Verify info was logged
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            assert "ROUTING" in call_args or "test-123" in call_args

    def test_auto_route_prefers_domain_experts(self):
        """auto_route should prefer agents with domain expertise."""
        selector = AgentSelector()

        # Security expert with high security expertise
        sec_expert = AgentProfile(
            name="sec_expert",
            agent_type="claude",
            elo_rating=1500,
            expertise={"security": 0.95},
        )
        # Generalist with low security expertise
        generalist = AgentProfile(
            name="generalist",
            agent_type="gemini",
            elo_rating=1600,  # Higher ELO
            expertise={"security": 0.3},
        )

        selector.register_agent(sec_expert)
        selector.register_agent(generalist)

        # For a security task, expert should be preferred despite lower ELO
        team = selector.auto_route("Fix authentication vulnerability", task_id="sec-task")

        agent_names = [a.name for a in team.agents]
        # Security expert should be in the team
        assert "sec_expert" in agent_names

    def test_auto_route_with_trait_detection(self):
        """auto_route should detect traits from task text."""
        selector = AgentSelector()

        # Agent with security trait
        secure_agent = AgentProfile(
            name="secure",
            agent_type="claude",
            traits=["security"],
            expertise={"general": 0.8},
        )
        # Agent without security trait
        other_agent = AgentProfile(
            name="other",
            agent_type="gemini",
            traits=[],
            expertise={"general": 0.8},
        )

        selector.register_agent(secure_agent)
        selector.register_agent(other_agent)

        # Task requiring security trait
        team = selector.auto_route("Make this application secure and safe")

        # Both should be in team but secure agent should have advantage
        assert len(team.agents) >= 1


# =============================================================================
# TestGetDomainLeaderboard - Domain-Specific Rankings
# =============================================================================


class TestGetDomainLeaderboard:
    """Tests for AgentSelector.get_domain_leaderboard() method."""

    def test_returns_ranked_list(self):
        """get_domain_leaderboard should return a ranked list."""
        selector = AgentSelector()

        selector.register_agent(
            AgentProfile(name="a1", agent_type="claude", expertise={"security": 0.9})
        )
        selector.register_agent(
            AgentProfile(name="a2", agent_type="gemini", expertise={"security": 0.7})
        )
        selector.register_agent(
            AgentProfile(name="a3", agent_type="codex", expertise={"security": 0.5})
        )

        leaderboard = selector.get_domain_leaderboard("security")

        assert len(leaderboard) == 3
        # Should be ranked by domain score
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[1]["rank"] == 2
        assert leaderboard[2]["rank"] == 3

    def test_ranks_by_expertise(self):
        """get_domain_leaderboard should rank by expertise."""
        selector = AgentSelector()

        # Agent with high expertise
        selector.register_agent(
            AgentProfile(
                name="expert",
                agent_type="claude",
                elo_rating=1500,
                expertise={"backend": 0.95},
            )
        )
        # Agent with low expertise but high ELO
        selector.register_agent(
            AgentProfile(
                name="high_elo",
                agent_type="gemini",
                elo_rating=1900,
                expertise={"backend": 0.3},
            )
        )

        leaderboard = selector.get_domain_leaderboard("backend")

        # Expert should rank higher for this domain
        assert leaderboard[0]["name"] == "expert"

    def test_ranks_by_domain_elo(self):
        """get_domain_leaderboard should consider domain ELO."""
        selector = AgentSelector()

        # Agent with high domain ELO
        selector.register_agent(
            AgentProfile(
                name="domain_expert",
                agent_type="claude",
                elo_rating=1500,
                domain_ratings={"api": 1900},
                expertise={"api": 0.7},
            )
        )
        # Agent without domain-specific ELO
        selector.register_agent(
            AgentProfile(
                name="generalist",
                agent_type="gemini",
                elo_rating=1700,
                domain_ratings={},
                expertise={"api": 0.7},
            )
        )

        leaderboard = selector.get_domain_leaderboard("api")

        # Domain expert should rank higher
        assert leaderboard[0]["name"] == "domain_expert"

    def test_respects_limit(self):
        """get_domain_leaderboard should respect limit parameter."""
        selector = AgentSelector()

        for i in range(20):
            selector.register_agent(AgentProfile(name=f"agent-{i}", agent_type="claude"))

        leaderboard = selector.get_domain_leaderboard("general", limit=5)

        assert len(leaderboard) == 5

    def test_includes_bench_status(self):
        """get_domain_leaderboard should include bench status."""
        selector = AgentSelector()

        selector.register_agent(AgentProfile(name="active", agent_type="claude"))
        selector.register_agent(AgentProfile(name="benched", agent_type="gemini"))
        selector.move_to_bench("benched")

        leaderboard = selector.get_domain_leaderboard("general")

        active_entry = next(e for e in leaderboard if e["name"] == "active")
        benched_entry = next(e for e in leaderboard if e["name"] == "benched")

        assert active_entry["on_bench"] is False
        assert benched_entry["on_bench"] is True

    def test_returns_domain_specific_fields(self):
        """get_domain_leaderboard should include domain-specific fields."""
        selector = AgentSelector()

        selector.register_agent(
            AgentProfile(
                name="agent",
                agent_type="claude",
                elo_rating=1600,
                expertise={"security": 0.85},
                domain_ratings={"security": 1750},
            )
        )

        leaderboard = selector.get_domain_leaderboard("security")

        entry = leaderboard[0]
        assert "rank" in entry
        assert "name" in entry
        assert "type" in entry
        assert "domain_score" in entry
        assert "expertise" in entry
        assert "domain_elo" in entry
        assert "overall_elo" in entry
        assert "on_bench" in entry

    def test_handles_missing_expertise(self):
        """get_domain_leaderboard should handle agents without expertise."""
        selector = AgentSelector()

        # Agent without expertise for the domain
        selector.register_agent(AgentProfile(name="agent", agent_type="claude", expertise={}))

        leaderboard = selector.get_domain_leaderboard("unknown_domain")

        # Should use default expertise value (0.5)
        assert len(leaderboard) == 1
        assert leaderboard[0]["expertise"] == 0.5

    def test_empty_pool_returns_empty_list(self):
        """get_domain_leaderboard should return empty list for empty pool."""
        selector = AgentSelector()

        leaderboard = selector.get_domain_leaderboard("security")

        assert leaderboard == []


# =============================================================================
# TestCreateWithDefaults - Factory Method
# =============================================================================


class TestCreateWithDefaults:
    """Tests for AgentSelector.create_with_defaults() factory method."""

    @pytest.fixture(autouse=True)
    def _isolate_optional_agent_flags(self, monkeypatch):
        """Keep factory tests independent of ambient optional-agent flags."""
        monkeypatch.delenv("ARAGORA_ENABLE_KIMI_CLI", raising=False)
        monkeypatch.setenv("ARAGORA_ENABLE_FUSION", "0")

    @pytest.mark.parametrize(
        ("enable_kimi", "enable_fusion"),
        [(False, False), (True, False), (True, True)],
    )
    def test_creates_selector_with_default_agents(
        self,
        monkeypatch,
        enable_kimi,
        enable_fusion,
    ):
        """create_with_defaults should register default agents."""
        if enable_kimi:
            monkeypatch.setenv("ARAGORA_ENABLE_KIMI_CLI", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_FUSION", str(int(enable_fusion)))

        selector = AgentSelector.create_with_defaults()

        expected_agents = set(DEFAULT_AGENT_EXPERTISE)
        if not enable_kimi:
            expected_agents.remove("kimi")
        if enable_fusion:
            expected_agents.add("fusion")

        assert "fusion" not in DEFAULT_AGENT_EXPERTISE
        assert set(selector.agent_pool) == expected_agents

    def test_default_agents_have_expertise(self):
        """Default agents should have expertise profiles."""
        selector = AgentSelector.create_with_defaults()

        for agent_name, profile in selector.agent_pool.items():
            assert len(profile.expertise) > 0
            # Each agent should have expertise in multiple domains
            assert len(profile.expertise) >= 3

    def test_accepts_elo_system(self):
        """create_with_defaults should accept ELO system."""
        mock_elo = MagicMock()
        mock_elo.get_ratings_batch.return_value = {}

        selector = AgentSelector.create_with_defaults(elo_system=mock_elo)

        assert selector.elo_system is mock_elo

    def test_accepts_persona_manager(self):
        """create_with_defaults should accept persona manager."""
        mock_persona = MagicMock()

        selector = AgentSelector.create_with_defaults(persona_manager=mock_persona)

        assert selector.persona_manager is mock_persona

    def test_syncs_from_elo_system(self):
        """create_with_defaults should sync from ELO system if provided."""
        mock_elo = MagicMock()
        mock_rating = MagicMock()
        mock_rating.elo = 1700
        mock_rating.domain_elos = {"security": 1800}
        mock_rating.win_rate = 0.8
        mock_elo.get_ratings_batch.return_value = {"claude": mock_rating}

        selector = AgentSelector.create_with_defaults(elo_system=mock_elo)

        # Claude's rating should be updated
        assert selector.agent_pool["claude"].elo_rating == 1700

    @pytest.mark.parametrize("enable_fusion", [False, True])
    def test_default_expertise_matches_constant(self, monkeypatch, enable_fusion):
        """Default expertise should match DEFAULT_AGENT_EXPERTISE constant."""
        monkeypatch.setenv("ARAGORA_ENABLE_KIMI_CLI", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_FUSION", str(int(enable_fusion)))
        selector = AgentSelector.create_with_defaults()

        expected_agents = set(DEFAULT_AGENT_EXPERTISE)
        if enable_fusion:
            expected_agents.add("fusion")
        assert set(selector.agent_pool) == expected_agents
        for agent_name, expected_expertise in DEFAULT_AGENT_EXPERTISE.items():
            actual_expertise = selector.agent_pool[agent_name].expertise
            assert actual_expertise == expected_expertise


# =============================================================================
# TestAutoRouteIntegration - Integration Tests
# =============================================================================


class TestAutoRouteIntegration:
    """Integration tests for auto_route with real components."""

    def test_full_routing_pipeline(self):
        """Test complete routing from task text to team selection."""
        # Create selector with default agents
        selector = AgentSelector.create_with_defaults()

        # Route a real-world task
        team = selector.auto_route(
            "We need to add rate limiting to the REST API endpoints to prevent abuse",
            task_id="api-ratelimit-001",
        )

        # Verify team composition
        assert isinstance(team, TeamComposition)
        assert len(team.agents) >= 2
        assert len(team.roles) == len(team.agents)
        assert team.expected_quality > 0
        assert team.rationale is not None

    def test_routing_records_history(self):
        """auto_route should record selection in history."""
        selector = AgentSelector.create_with_defaults()

        selector.auto_route("Test task", task_id="history-test")

        history = selector.get_selection_history()
        assert len(history) >= 1
        assert any(h["task_id"] == "history-test" for h in history)

    def test_routing_different_domains(self):
        """auto_route should handle different domain tasks."""
        selector = AgentSelector.create_with_defaults()

        # Security task
        sec_team = selector.auto_route("Fix XSS vulnerability and SQL injection")

        # Performance task
        perf_team = selector.auto_route("Optimize database queries and add caching")

        # Both should produce valid teams
        assert len(sec_team.agents) >= 2
        assert len(perf_team.agents) >= 2

        # Teams might be different based on domain expertise
        # (but with default expertise, they might overlap)

    def test_routing_with_exclusions(self):
        """auto_route should work with agent exclusions."""
        selector = AgentSelector.create_with_defaults()

        # Exclude some agents
        team = selector.auto_route(
            "Some task",
            exclude=["claude", "codex"],
        )

        agent_names = [a.name for a in team.agents]
        assert "claude" not in agent_names
        assert "codex" not in agent_names

    def test_routing_preserves_agent_types(self):
        """auto_route should preserve agent type information."""
        selector = AgentSelector.create_with_defaults()

        team = selector.auto_route("Test task")

        for agent in team.agents:
            assert agent.agent_type == selector.agent_pool[agent.name].agent_type


# =============================================================================
# TestDomainDetectorIntegration - DomainDetector Integration
# =============================================================================


class TestDomainDetectorIntegration:
    """Tests for DomainDetector integration with AgentSelector."""

    def test_detector_creates_valid_requirements(self):
        """DomainDetector should create TaskRequirements compatible with AgentSelector."""
        detector = DomainDetector(use_llm=False)
        selector = AgentSelector.create_with_defaults()

        # Get requirements from detector
        requirements = detector.get_task_requirements(
            "Fix the authentication security issue",
            task_id="det-001",
        )

        # Requirements should be usable by selector
        team = selector.select_team(requirements)

        assert isinstance(team, TeamComposition)
        assert team.task_id == "det-001"

    def test_detector_domain_matches_agent_expertise(self):
        """Detected domains should match agent expertise keys."""
        detector = DomainDetector(use_llm=False)

        # Get detected domains
        domains = detector.detect("security testing api database", top_n=5)
        detected_domain_names = [d for d, _ in domains]

        # All detected domains should be valid expertise keys
        valid_domains = set(DEFAULT_AGENT_EXPERTISE["claude"].keys())
        for domain in detected_domain_names:
            # Domain should either be in expertise or be 'general'
            assert (
                domain in valid_domains
                or domain == "general"
                or domain
                in [
                    "debugging",
                    "devops",
                    "frontend",
                    "documentation",
                    "ethics",
                    "philosophy",
                    "data_analysis",
                ]
            )


# =============================================================================
# TestAutoRouteEdgeCases - Edge Cases
# =============================================================================


class TestAutoRouteEdgeCases:
    """Tests for edge cases in auto_route."""

    def test_all_agents_excluded_raises_error(self):
        """auto_route should raise error if all agents are excluded."""
        selector = AgentSelector()
        selector.register_agent(AgentProfile(name="only_agent", agent_type="claude"))

        with pytest.raises(ValueError, match="No available agents"):
            selector.auto_route("Test task", exclude=["only_agent"])

    def test_all_agents_on_bench_raises_error(self):
        """auto_route should raise error if all agents are benched."""
        selector = AgentSelector()
        selector.register_agent(AgentProfile(name="agent", agent_type="claude"))
        selector.move_to_bench("agent")

        with pytest.raises(ValueError, match="No available agents"):
            selector.auto_route("Test task")

    def test_very_long_task_text(self):
        """auto_route should handle very long task text."""
        selector = AgentSelector.create_with_defaults()

        long_text = "security authentication " * 500
        team = selector.auto_route(long_text)

        assert len(team.agents) >= 2

    def test_special_characters_in_task(self):
        """auto_route should handle special characters."""
        selector = AgentSelector.create_with_defaults()

        team = selector.auto_route("Fix bug #123 with SQL injection <script>alert('xss')</script>")

        assert len(team.agents) >= 2

    def test_unicode_task_text(self):
        """auto_route should handle unicode text."""
        selector = AgentSelector.create_with_defaults()

        team = selector.auto_route("Fix security issue with authentication \u00e9\u00e8")

        assert len(team.agents) >= 2
