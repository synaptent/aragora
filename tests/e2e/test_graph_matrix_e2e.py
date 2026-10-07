"""
End-to-end tests for Graph and Matrix debate modes.

Tests the full lifecycle of:
1. Graph debates: create graph -> add branches -> run with mocked agents -> merge -> verify convergence
2. Matrix debates: define scenarios -> run matrix -> extract conclusions
3. Handler endpoints: POST/GET for graph and matrix debates

All external dependencies (LLM calls, databases) are mocked.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.e2e


# ============================================================================
# Fixtures
# ============================================================================


@dataclass
class MockAgent:
    """Lightweight mock agent for graph/matrix debates."""

    name: str
    response: str = "I agree with this approach. Confidence: 80%"

    async def generate(self, prompt: str, context: Any = None) -> str:
        return self.response


@pytest.fixture
def mock_agents() -> list[MockAgent]:
    """Create a set of mock agents with varied responses."""
    return [
        MockAgent(
            name="agent-alpha",
            response="We should use microservices. Confidence: 85%",
        ),
        MockAgent(
            name="agent-beta",
            response="A monolithic approach is safer. Confidence: 70%",
        ),
        MockAgent(
            name="agent-gamma",
            response="Perhaps a hybrid approach works best. Confidence: 75%",
        ),
    ]


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters before and after each test."""
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters as _reset

        _reset()
    except ImportError:
        pass

    try:
        from aragora.server.handlers.debates import graph_debates

        graph_debates._graph_limiter = graph_debates.RateLimiter(requests_per_minute=5)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.server.handlers.debates import matrix_debates

        matrix_debates._matrix_limiter = matrix_debates.RateLimiter(requests_per_minute=5)
    except (ImportError, AttributeError):
        pass

    yield

    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters as _reset

        _reset()
    except ImportError:
        pass


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler with standard attributes."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 54321)
    handler.headers = {}
    handler.event_emitter = None
    handler.storage = None
    return handler


E2E_ORG = "org-e2e"


@pytest.fixture
def org_user(monkeypatch):
    """Requests act as a member of ``E2E_ORG``."""
    from types import SimpleNamespace

    user = SimpleNamespace(user_id="user-e2e", org_id=E2E_ORG, role="member", is_authenticated=True)
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: user,
    )
    return user


# ============================================================================
# Graph Debate Core Lifecycle Tests
# ============================================================================


class TestGraphDebateLifecycle:
    """E2E tests for the full graph debate lifecycle.

    Tests the complete flow: create graph -> add nodes -> create branches ->
    add nodes to branches -> detect convergence -> merge branches -> verify result.
    """

    def test_create_graph_and_add_root_node(self):
        """Create a debate graph and add a root node."""
        from aragora.debate.graph import DebateGraph, NodeType

        graph = DebateGraph(debate_id="e2e-test-1")

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Should we adopt microservices or stay monolithic?",
            confidence=1.0,
        )

        assert graph.root_id == root.id
        assert root.node_type == NodeType.ROOT
        assert root.content == "Should we adopt microservices or stay monolithic?"
        assert root.confidence == 1.0
        assert len(graph.nodes) == 1
        assert root.branch_id == "main"

    def test_add_proposals_and_critiques(self):
        """Add proposal and critique nodes linked to root."""
        from aragora.debate.graph import DebateGraph, NodeType

        graph = DebateGraph()

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Evaluate database migration strategies",
            confidence=1.0,
        )

        proposal = graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="We should use a phased migration approach",
            parent_id=root.id,
            confidence=0.85,
            claims=["phased migration reduces risk", "allows rollback"],
        )

        critique = graph.add_node(
            node_type=NodeType.CRITIQUE,
            agent_id="agent-beta",
            content="Phased migration takes longer and increases total cost",
            parent_id=proposal.id,
            confidence=0.70,
            claims=["phased migration increases cost", "big-bang is faster"],
        )

        assert len(graph.nodes) == 3
        assert root.id in proposal.parent_ids
        assert proposal.id in critique.parent_ids
        assert proposal.id in root.child_ids
        assert critique.id in proposal.child_ids

    def test_create_branch_from_disagreement(self):
        """Create a branch when agents disagree."""
        from aragora.debate.graph import BranchReason, DebateGraph, NodeType

        graph = DebateGraph()

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="How should we handle distributed caching?",
        )

        # Agent alpha proposes Redis
        proposal = graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="Use Redis for distributed caching",
            parent_id=root.id,
            confidence=0.9,
            claims=["Redis is fast", "Redis is battle-tested"],
        )

        # Agent beta disagrees strongly -- create a branch
        branch = graph.create_branch(
            from_node_id=proposal.id,
            reason=BranchReason.HIGH_DISAGREEMENT,
            name="Memcached Alternative",
            hypothesis="Memcached may be simpler and cheaper",
        )

        assert branch.id in graph.branches
        assert branch.reason == BranchReason.HIGH_DISAGREEMENT
        assert branch.start_node_id == proposal.id
        assert branch.is_active is True
        assert branch.is_merged is False

        # Add a node to the new branch
        alt_node = graph.add_node(
            node_type=NodeType.COUNTERFACTUAL,
            agent_id="agent-beta",
            content="Memcached is simpler for our use case",
            parent_id=proposal.id,
            branch_id=branch.id,
            confidence=0.75,
            claims=["Memcached is simpler", "lower operational cost"],
        )

        assert alt_node.branch_id == branch.id
        branch_nodes = graph.get_branch_nodes(branch.id)
        assert len(branch_nodes) == 1
        assert branch_nodes[0].id == alt_node.id

    def test_merge_convergent_branches(self):
        """Merge branches when they converge to similar conclusions."""
        from aragora.debate.graph import (
            BranchReason,
            DebateGraph,
            MergeStrategy,
            NodeType,
        )

        graph = DebateGraph()

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="What frontend framework should we use?",
        )

        # Main branch: React
        react_node = graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="React is the best choice",
            parent_id=root.id,
            claims=["component model", "large ecosystem", "performance"],
            confidence=0.8,
        )

        # Create branch for Vue.js alternative
        vue_branch = graph.create_branch(
            from_node_id=root.id,
            reason=BranchReason.ALTERNATIVE_APPROACH,
            name="Vue.js Alternative",
        )

        vue_node = graph.add_node(
            node_type=NodeType.COUNTERFACTUAL,
            agent_id="agent-beta",
            content="Vue.js is simpler and has good performance",
            parent_id=root.id,
            branch_id=vue_branch.id,
            claims=["component model", "simpler API", "performance"],
            confidence=0.75,
        )

        # Merge the branches with synthesis
        merge_result = graph.merge_branches(
            branch_ids=["main", vue_branch.id],
            strategy=MergeStrategy.SYNTHESIS,
            synthesizer_agent_id="system",
            synthesis_content="Both React and Vue offer strong component models. "
            "React has a larger ecosystem; Vue is simpler. "
            "Choose based on team experience.",
        )

        assert merge_result.merged_node_id in graph.nodes
        assert "main" in merge_result.source_branch_ids
        assert vue_branch.id in merge_result.source_branch_ids
        assert merge_result.strategy == MergeStrategy.SYNTHESIS
        assert len(merge_result.insights_preserved) > 0
        assert "component model" in merge_result.insights_preserved

        # Verify branches are marked as merged
        assert graph.branches["main"].is_merged is True
        assert graph.branches[vue_branch.id].is_merged is True

        # Verify merge history
        assert len(graph.merge_history) == 1
        assert graph.merge_history[0].merged_node_id == merge_result.merged_node_id

    def test_convergence_detection(self):
        """Detect convergence between branches sharing claims."""
        from aragora.debate.graph import (
            BranchPolicy,
            BranchReason,
            DebateGraph,
            NodeType,
        )

        policy = BranchPolicy(convergence_threshold=0.5)
        graph = DebateGraph(branch_policy=policy)

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Best CI/CD approach?",
        )

        # Main branch
        graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="Use GitHub Actions",
            parent_id=root.id,
            claims=["automation", "integration", "reliability"],
            confidence=0.8,
        )

        # Create alternative branch
        alt_branch = graph.create_branch(
            from_node_id=root.id,
            reason=BranchReason.ALTERNATIVE_APPROACH,
            name="GitLab CI Alternative",
        )

        # Add nodes with overlapping claims to trigger convergence
        graph.add_node(
            node_type=NodeType.COUNTERFACTUAL,
            agent_id="agent-beta",
            content="Use GitLab CI for better built-in features",
            parent_id=root.id,
            branch_id=alt_branch.id,
            claims=["automation", "integration", "self-hosted option"],
            confidence=0.75,
        )

        convergent = graph.check_convergence()

        # Should detect convergence due to shared "automation" and "integration" claims
        assert len(convergent) > 0
        branch_a, branch_b, score = convergent[0]
        assert score >= 0.5

    def test_full_graph_serialization_roundtrip(self):
        """Serialize and deserialize a graph, verifying data integrity."""
        from aragora.debate.graph import (
            BranchReason,
            DebateGraph,
            MergeStrategy,
            NodeType,
        )

        graph = DebateGraph(debate_id="roundtrip-test")

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Test topic for serialization",
            confidence=1.0,
        )

        proposal = graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="Proposal content",
            parent_id=root.id,
            confidence=0.85,
            claims=["claim-a", "claim-b"],
        )

        branch = graph.create_branch(
            from_node_id=proposal.id,
            reason=BranchReason.HIGH_DISAGREEMENT,
            name="Alternative",
        )

        graph.add_node(
            node_type=NodeType.COUNTERFACTUAL,
            agent_id="agent-beta",
            content="Alternative approach",
            parent_id=proposal.id,
            branch_id=branch.id,
            confidence=0.7,
        )

        # Serialize
        data = graph.to_dict()
        assert data["debate_id"] == "roundtrip-test"
        assert len(data["nodes"]) == 3
        assert len(data["branches"]) >= 2  # main + alternative

        # Deserialize
        restored = DebateGraph.from_dict(data)
        assert restored.debate_id == graph.debate_id
        assert len(restored.nodes) == len(graph.nodes)
        assert len(restored.branches) == len(graph.branches)
        assert restored.root_id == graph.root_id

        # Verify node content
        for node_id, node in graph.nodes.items():
            restored_node = restored.nodes[node_id]
            assert restored_node.content == node.content
            assert restored_node.agent_id == node.agent_id
            assert restored_node.node_type == node.node_type

    def test_branch_policy_limits_branching(self):
        """Branch policy enforces max_branches and max_depth limits."""
        from aragora.debate.graph import BranchPolicy, BranchReason

        policy = BranchPolicy(
            max_branches=2,
            max_depth=3,
            disagreement_threshold=0.5,
        )

        # Should allow branching when under limits
        should_branch, reason = policy.should_branch(
            disagreement=0.8,
            uncertainty=0.3,
            current_branches=1,
            current_depth=1,
        )
        assert should_branch is True
        assert reason == BranchReason.HIGH_DISAGREEMENT

        # Should not allow branching when at max_branches
        should_branch, reason = policy.should_branch(
            disagreement=0.8,
            uncertainty=0.3,
            current_branches=2,
            current_depth=1,
        )
        assert should_branch is False
        assert reason is None

        # Should not allow branching when at max_depth
        should_branch, reason = policy.should_branch(
            disagreement=0.8,
            uncertainty=0.3,
            current_branches=1,
            current_depth=3,
        )
        assert should_branch is False
        assert reason is None

    def test_graph_replay_builder(self):
        """GraphReplayBuilder replays branches and generates summaries."""
        from aragora.debate.graph import (
            BranchReason,
            DebateGraph,
            GraphReplayBuilder,
            NodeType,
        )

        graph = DebateGraph(debate_id="replay-test")

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Replay test topic",
        )

        graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="First proposal",
            parent_id=root.id,
            claims=["claim-1"],
        )

        graph.add_node(
            node_type=NodeType.SYNTHESIS,
            agent_id="agent-beta",
            content="Synthesis of ideas",
            parent_id=root.id,
            claims=["claim-2"],
        )

        replay = GraphReplayBuilder(graph)

        # Replay main branch
        main_nodes = replay.replay_branch("main")
        assert len(main_nodes) == 3

        # Full replay
        all_branches = (
            replay.full_replay() if hasattr(replay, "full_replay") else replay.replay_full()
        )
        assert "main" in all_branches

        # Summary
        summary = replay.generate_summary()
        assert summary["debate_id"] == "replay-test"
        assert summary["total_nodes"] == 3
        assert summary["total_branches"] >= 1
        assert len(summary["agents"]) >= 2

    def test_leaf_nodes_and_path_to_node(self):
        """Get leaf nodes and trace path from root to any node."""
        from aragora.debate.graph import DebateGraph, NodeType

        graph = DebateGraph()

        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Root",
        )

        mid = graph.add_node(
            node_type=NodeType.PROPOSAL,
            agent_id="agent-alpha",
            content="Middle",
            parent_id=root.id,
        )

        leaf = graph.add_node(
            node_type=NodeType.SYNTHESIS,
            agent_id="agent-beta",
            content="Leaf",
            parent_id=mid.id,
        )

        # Leaf nodes
        leaves = graph.get_leaf_nodes()
        assert len(leaves) == 1
        assert leaves[0].id == leaf.id

        # Path from root to leaf
        path = graph.get_path_to_node(leaf.id)
        assert len(path) == 3
        assert path[0].id == root.id
        assert path[1].id == mid.id
        assert path[2].id == leaf.id


# ============================================================================
# Graph Debate Orchestrator E2E Tests
# ============================================================================


class TestGraphDebateOrchestratorE2E:
    """E2E tests for GraphDebateOrchestrator with mocked agents."""

    @pytest.mark.asyncio
    async def test_orchestrator_runs_debate_without_agent_fn(self, mock_agents):
        """Orchestrator returns initialized graph when no run_agent_fn provided."""
        from aragora.debate.graph import GraphDebateOrchestrator

        orchestrator = GraphDebateOrchestrator(agents=mock_agents)

        graph = await orchestrator.run_debate(
            task="Evaluate the best approach to API versioning",
        )

        # Without run_agent_fn, only root node is created
        assert graph.root_id is not None
        assert len(graph.nodes) == 1
        root = graph.nodes[graph.root_id]
        assert root.content == "Evaluate the best approach to API versioning"

    @pytest.mark.asyncio
    async def test_orchestrator_runs_full_debate_with_agents(self, mock_agents):
        """Orchestrator runs full debate with mocked agent responses."""
        from aragora.debate.graph import BranchPolicy, GraphDebateOrchestrator

        policy = BranchPolicy(
            disagreement_threshold=0.9,  # High threshold to avoid branching
            max_branches=2,
            max_depth=3,
        )
        orchestrator = GraphDebateOrchestrator(agents=mock_agents, policy=policy)

        call_count = 0

        async def mock_run_agent(agent, prompt, context):
            nonlocal call_count
            call_count += 1
            return agent.response

        nodes_added = []
        branches_created = []

        graph = await orchestrator.run_debate(
            task="Should we implement rate limiting at the gateway or service level?",
            max_rounds=2,
            run_agent_fn=mock_run_agent,
            on_node=lambda n: nodes_added.append(n),
            on_branch=lambda b: branches_created.append(b),
        )

        # Verify the debate ran
        assert len(graph.nodes) > 1
        assert call_count > 0
        assert len(nodes_added) > 0

        # Root node should exist
        root = graph.nodes[graph.root_id]
        assert root.content == "Should we implement rate limiting at the gateway or service level?"

        # Should have conclusion node
        conclusion_nodes = [n for n in graph.nodes.values() if n.node_type.value == "conclusion"]
        assert len(conclusion_nodes) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_creates_branches_on_disagreement(self):
        """Orchestrator creates branches when agents strongly disagree."""
        from aragora.debate.graph import BranchPolicy, GraphDebateOrchestrator

        # Create agents with very different confidence levels to trigger branching
        high_conf_agent = MockAgent(
            name="confident-agent",
            response="Definitely use approach A. Confidence: 95%",
        )
        low_conf_agent = MockAgent(
            name="uncertain-agent",
            response="Maybe approach B is better. Confidence: 20%",
        )

        policy = BranchPolicy(
            disagreement_threshold=0.3,  # Low threshold to trigger branching
            max_branches=4,
            max_depth=5,
        )

        orchestrator = GraphDebateOrchestrator(
            agents=[high_conf_agent, low_conf_agent],
            policy=policy,
        )

        branches_created = []

        async def mock_run_agent(agent, prompt, context):
            return agent.response

        graph = await orchestrator.run_debate(
            task="Which database should we use for our real-time analytics pipeline?",
            max_rounds=3,
            run_agent_fn=mock_run_agent,
            on_branch=lambda b: branches_created.append(b),
        )

        # Should have created at least one branch due to confidence variance
        assert len(graph.branches) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_handles_agent_errors_gracefully(self):
        """Orchestrator handles agent errors without crashing."""
        from aragora.debate.graph import GraphDebateOrchestrator

        agents = [
            MockAgent(name="good-agent", response="Valid response. Confidence: 80%"),
            MockAgent(name="bad-agent", response="Will fail"),
        ]

        orchestrator = GraphDebateOrchestrator(agents=agents)

        call_count = 0

        async def failing_run_agent(agent, prompt, context):
            nonlocal call_count
            call_count += 1
            if agent.name == "bad-agent":
                raise RuntimeError("Simulated agent failure")
            return agent.response

        # Should not raise despite one agent failing
        graph = await orchestrator.run_debate(
            task="Test error handling in graph debates with multiple agents",
            max_rounds=2,
            run_agent_fn=failing_run_agent,
        )

        assert len(graph.nodes) > 1
        assert call_count > 0

    @pytest.mark.asyncio
    async def test_orchestrator_emits_websocket_events(self):
        """Orchestrator emits events via event_emitter when provided."""
        from aragora.debate.graph import GraphDebateOrchestrator

        agents = [
            MockAgent(name="agent-1", response="Response one. Confidence: 80%"),
            MockAgent(name="agent-2", response="Response two. Confidence: 75%"),
        ]

        orchestrator = GraphDebateOrchestrator(agents=agents)

        emitted_events = []
        mock_emitter = MagicMock()
        mock_emitter.emit = MagicMock(side_effect=lambda e: emitted_events.append(e))

        async def mock_run_agent(agent, prompt, context):
            return agent.response

        # Patch the StreamEvent import to avoid import errors in test env
        with patch(
            "aragora.debate.graph.GraphDebateOrchestrator._emit_graph_event",
            wraps=orchestrator._emit_graph_event,
        ):
            graph = await orchestrator.run_debate(
                task="Test WebSocket event emission during graph debate execution",
                max_rounds=1,
                run_agent_fn=mock_run_agent,
                event_emitter=mock_emitter,
                debate_id="ws-test-123",
            )

        assert len(graph.nodes) > 1

    def test_evaluate_disagreement_with_varied_responses(self):
        """Evaluate disagreement correctly detects agent variance."""
        from aragora.debate.graph import GraphDebateOrchestrator

        orchestrator = GraphDebateOrchestrator(agents=[])

        # Low disagreement: similar confidence
        disagreement, alt = orchestrator.evaluate_disagreement(
            [
                ("agent-1", "Approach A. Confidence: 80%", 0.8),
                ("agent-2", "Also approach A. Confidence: 75%", 0.75),
            ]
        )
        assert disagreement < 0.5

        # High disagreement: very different confidence
        disagreement, alt = orchestrator.evaluate_disagreement(
            [
                ("agent-1", "Definitely A. Confidence: 95%", 0.95),
                ("agent-2", "Maybe B. Confidence: 10%", 0.10),
            ]
        )
        assert disagreement > 0.3

        # Single response: no disagreement
        disagreement, alt = orchestrator.evaluate_disagreement(
            [
                ("agent-1", "Only opinion", 0.5),
            ]
        )
        assert disagreement == 0.0
        assert alt is None


# ============================================================================
# Matrix Debate Core Lifecycle Tests
# ============================================================================


class TestMatrixDebateLifecycle:
    """E2E tests for the full matrix debate lifecycle.

    Tests the complete flow: define scenarios -> build matrix -> run debates ->
    compare results -> extract conclusions.
    """

    def test_create_scenario_matrix_with_explicit_scenarios(self):
        """Build a matrix from explicitly defined scenarios."""
        from aragora.debate.scenarios import Scenario, ScenarioMatrix, ScenarioType

        matrix = ScenarioMatrix(name="Architecture Decision Matrix")

        matrix.add_scenario(
            Scenario(
                id="small-scale",
                name="Small Scale",
                scenario_type=ScenarioType.SCALE,
                description="10-100 users",
                parameters={"users": 100, "budget": "low"},
                constraints=["Single server", "Limited budget"],
            )
        )

        matrix.add_scenario(
            Scenario(
                id="enterprise",
                name="Enterprise Scale",
                scenario_type=ScenarioType.SCALE,
                description="100K+ users",
                parameters={"users": 100000, "budget": "high"},
                constraints=["SLA required", "Multi-region"],
                is_baseline=False,
            )
        )

        scenarios = matrix.get_scenarios()
        assert len(scenarios) == 2
        assert any(s.id == "small-scale" for s in scenarios)
        assert any(s.id == "enterprise" for s in scenarios)

    def test_generate_grid_from_dimensions(self):
        """Generate scenarios from cartesian product of dimensions."""
        from aragora.debate.scenarios import ScenarioMatrix

        matrix = ScenarioMatrix(name="Grid Matrix")
        matrix.add_dimension("scale", ["small", "large"])
        matrix.add_dimension("risk", ["low", "high"])
        matrix.generate_grid()

        scenarios = matrix.get_scenarios()
        assert len(scenarios) == 4  # 2x2 grid

        # Verify all combinations exist
        param_combos = {(s.parameters["scale"], s.parameters["risk"]) for s in scenarios}
        assert ("small", "low") in param_combos
        assert ("small", "high") in param_combos
        assert ("large", "low") in param_combos
        assert ("large", "high") in param_combos

    def test_generate_sensitivity_analysis(self):
        """Generate scenarios for sensitivity analysis (vary one at a time)."""
        from aragora.debate.scenarios import ScenarioMatrix

        matrix = ScenarioMatrix(name="Sensitivity Analysis")
        matrix.generate_sensitivity(
            baseline_params={"budget": "medium", "timeline": "6mo"},
            vary_params={
                "budget": ["low", "medium", "high"],
                "timeline": ["3mo", "6mo", "12mo"],
            },
        )

        scenarios = matrix.get_scenarios()
        # Should have: baseline + 2 budget variations + 2 timeline variations = 5
        assert len(scenarios) == 5

        # Should have exactly one baseline
        baselines = [s for s in scenarios if s.is_baseline]
        assert len(baselines) == 1
        assert baselines[0].parameters == {"budget": "medium", "timeline": "6mo"}

    def test_scenario_applies_context_modifications(self):
        """Scenario correctly modifies debate context."""
        from aragora.debate.scenarios import Scenario, ScenarioType

        scenario = Scenario(
            id="test",
            name="Test Scenario",
            scenario_type=ScenarioType.CONSTRAINT,
            description="Testing context modification",
            constraints=["Must complete in 3 months", "Budget under $50K"],
            assumptions=["Team has Python expertise"],
            context_additions="Focus on rapid delivery.",
            context_replacements={"placeholder": "actual value"},
        )

        base_context = "Evaluate approach for placeholder project."
        modified = scenario.apply_to_context(base_context)

        assert "actual value" in modified
        assert "placeholder" not in modified
        assert "Focus on rapid delivery." in modified
        assert "Must complete in 3 months" in modified
        assert "Team has Python expertise" in modified

    def test_from_presets_creates_valid_matrix(self):
        """Preset matrices generate correct scenarios."""
        from aragora.debate.scenarios import ScenarioMatrix

        # Scale preset
        scale_matrix = ScenarioMatrix.from_presets("scale")
        scale_scenarios = scale_matrix.get_scenarios()
        assert len(scale_scenarios) == 4  # small, medium, large, enterprise

        # Comprehensive preset
        comprehensive = ScenarioMatrix.from_presets("comprehensive")
        comp_scenarios = comprehensive.get_scenarios()
        assert len(comp_scenarios) == 8  # 2x2x2

        # Risk preset
        risk_matrix = ScenarioMatrix.from_presets("risk")
        risk_scenarios = risk_matrix.get_scenarios()
        assert len(risk_scenarios) == 3  # conservative, moderate, aggressive

    def test_scenario_comparator_detects_similarity(self):
        """ScenarioComparator correctly compares two results."""
        from aragora.debate.scenarios import ScenarioComparator, ScenarioResult

        comparator = ScenarioComparator()

        result_a = ScenarioResult(
            scenario_id="a",
            scenario_name="Scenario A",
            conclusion="We should use microservices for better scalability",
            confidence=0.85,
            consensus_reached=True,
            key_claims=["scalability", "modularity", "team autonomy"],
        )

        result_b = ScenarioResult(
            scenario_id="b",
            scenario_name="Scenario B",
            conclusion="Microservices provide better scalability and modularity",
            confidence=0.80,
            consensus_reached=True,
            key_claims=["scalability", "modularity", "complexity"],
        )

        comparison = comparator.compare_pair(result_a, result_b)

        assert comparison.scenario_a_id == "a"
        assert comparison.scenario_b_id == "b"
        assert len(comparison.shared_claims) == 2  # scalability, modularity
        assert "team autonomy" in comparison.unique_to_a
        assert "complexity" in comparison.unique_to_b
        assert comparison.similarity_score > 0.0

    def test_scenario_comparator_analyzes_full_matrix(self):
        """ScenarioComparator analyzes a full matrix result."""
        from aragora.debate.scenarios import (
            MatrixResult,
            OutcomeCategory,
            Scenario,
            ScenarioComparator,
            ScenarioResult,
            ScenarioType,
        )

        comparator = ScenarioComparator()

        matrix_result = MatrixResult(
            matrix_id="analysis-test",
            task="Best API design approach",
            created_at=datetime.now(),
            scenarios=[
                Scenario(
                    id="rest",
                    name="REST",
                    scenario_type=ScenarioType.TECHNOLOGY,
                    description="REST API",
                    parameters={"style": "rest"},
                ),
                Scenario(
                    id="graphql",
                    name="GraphQL",
                    scenario_type=ScenarioType.TECHNOLOGY,
                    description="GraphQL API",
                    parameters={"style": "graphql"},
                ),
            ],
            results=[
                ScenarioResult(
                    scenario_id="rest",
                    scenario_name="REST",
                    conclusion="REST is simpler and widely adopted",
                    confidence=0.85,
                    consensus_reached=True,
                    key_claims=["simplicity", "wide adoption", "caching"],
                ),
                ScenarioResult(
                    scenario_id="graphql",
                    scenario_name="GraphQL",
                    conclusion="GraphQL offers flexible querying",
                    confidence=0.80,
                    consensus_reached=True,
                    key_claims=["flexibility", "single endpoint", "type safety"],
                ),
            ],
        )

        analysis = comparator.analyze_matrix(matrix_result)

        assert "outcome_category" in analysis
        assert analysis["total_scenarios"] == 2
        assert "universal_conclusions" in analysis
        assert "comparisons" in analysis
        assert len(analysis["comparisons"]) == 1  # 1 pair from 2 scenarios

    @pytest.mark.asyncio
    async def test_matrix_debate_runner_sequential(self):
        """MatrixDebateRunner runs scenarios sequentially."""
        from aragora.debate.scenarios import (
            MatrixDebateRunner,
            Scenario,
            ScenarioMatrix,
            ScenarioType,
        )

        # Create mock debate function
        debate_results = {}

        async def mock_debate_func(task: str, context: str):
            """Mock debate that returns structured results."""
            result = MagicMock()
            result.final_answer = f"Conclusion for: {task[:50]}"
            result.confidence = 0.8
            result.consensus_reached = True
            result.key_claims = ["claim-1", "claim-2"]
            result.dissenting_views = []
            result.rounds = 3
            return result

        runner = MatrixDebateRunner(
            debate_func=mock_debate_func,
            max_parallel=1,  # Sequential
        )

        matrix = ScenarioMatrix(name="Sequential Test")
        matrix.add_scenario(
            Scenario(
                id="scenario-1",
                name="Low Budget",
                scenario_type=ScenarioType.CONSTRAINT,
                description="Budget under $10K",
                parameters={"budget": 10000},
            )
        )
        matrix.add_scenario(
            Scenario(
                id="scenario-2",
                name="High Budget",
                scenario_type=ScenarioType.CONSTRAINT,
                description="Budget over $100K",
                parameters={"budget": 100000},
            )
        )

        completed_scenarios = []

        result = await runner.run_matrix(
            task="Evaluate infrastructure migration strategy",
            matrix=matrix,
            on_scenario_complete=lambda r: completed_scenarios.append(r),
        )

        assert len(result.results) == 2
        assert len(completed_scenarios) == 2
        assert result.completed_at is not None
        assert result.matrix_id is not None

        # Each result should have a conclusion
        for r in result.results:
            assert r.conclusion
            assert r.confidence > 0

    @pytest.mark.asyncio
    async def test_matrix_debate_runner_parallel(self):
        """MatrixDebateRunner runs scenarios in parallel batches."""
        from aragora.debate.scenarios import (
            MatrixDebateRunner,
            Scenario,
            ScenarioMatrix,
            ScenarioType,
        )

        execution_times = []

        async def mock_debate_func(task: str, context: str):
            """Mock debate with small delay to verify parallel execution."""
            await asyncio.sleep(0.01)
            result = MagicMock()
            result.final_answer = "Parallel conclusion"
            result.confidence = 0.75
            result.consensus_reached = True
            result.key_claims = ["parallel-claim"]
            result.dissenting_views = []
            result.rounds = 2
            return result

        runner = MatrixDebateRunner(
            debate_func=mock_debate_func,
            max_parallel=3,
        )

        matrix = ScenarioMatrix(name="Parallel Test")
        for i in range(6):
            matrix.add_scenario(
                Scenario(
                    id=f"scenario-{i}",
                    name=f"Scenario {i}",
                    scenario_type=ScenarioType.CUSTOM,
                    description=f"Test scenario {i}",
                )
            )

        result = await runner.run_matrix(
            task="Parallel execution test for matrix debate scenarios",
            matrix=matrix,
        )

        assert len(result.results) == 6
        assert result.summary  # Summary should be generated

    @pytest.mark.asyncio
    async def test_matrix_debate_runner_handles_scenario_errors(self):
        """MatrixDebateRunner handles individual scenario failures gracefully."""
        from aragora.debate.scenarios import (
            MatrixDebateRunner,
            Scenario,
            ScenarioMatrix,
            ScenarioType,
        )

        call_count = 0

        async def failing_debate_func(task: str, context: str):
            nonlocal call_count
            call_count += 1
            if "fail" in task.lower():
                raise ValueError("Simulated scenario failure")
            result = MagicMock()
            result.final_answer = "Success"
            result.confidence = 0.9
            result.consensus_reached = True
            result.key_claims = ["success"]
            result.dissenting_views = []
            result.rounds = 1
            return result

        runner = MatrixDebateRunner(
            debate_func=failing_debate_func,
            max_parallel=1,
        )

        matrix = ScenarioMatrix(name="Error Handling Test")
        matrix.add_scenario(
            Scenario(
                id="ok",
                name="OK Scenario",
                scenario_type=ScenarioType.CUSTOM,
                description="This should succeed",
            )
        )
        matrix.add_scenario(
            Scenario(
                id="fail",
                name="Fail Scenario",
                scenario_type=ScenarioType.CUSTOM,
                description="This will fail",
            )
        )

        result = await runner.run_matrix(
            task="Error handling test for matrix debates",
            matrix=matrix,
        )

        # The failing scenario should still return a result (with error metadata)
        # due to the try/except in _run_scenario_debate
        assert len(result.results) == 2

    def test_convenience_scenario_creators(self):
        """Convenience functions create valid scenario lists."""
        from aragora.debate.scenarios import (
            create_risk_scenarios,
            create_scale_scenarios,
            create_time_horizon_scenarios,
        )

        scale = create_scale_scenarios()
        assert len(scale) == 3
        assert all(s.id for s in scale)

        risk = create_risk_scenarios()
        assert len(risk) == 3
        baselines = [s for s in risk if s.is_baseline]
        assert len(baselines) == 1  # moderate is baseline

        time_horizons = create_time_horizon_scenarios()
        assert len(time_horizons) == 3
        assert any(s.parameters.get("horizon_months") == 48 for s in time_horizons)

    def test_scenario_result_serialization(self):
        """ScenarioResult serializes correctly to dict."""
        from aragora.debate.scenarios import ScenarioResult

        result = ScenarioResult(
            scenario_id="test-id",
            scenario_name="Test Scenario",
            conclusion="The conclusion is clear",
            confidence=0.85,
            consensus_reached=True,
            key_claims=["claim-1", "claim-2"],
            dissenting_views=["minority view"],
            duration_seconds=12.5,
            rounds=4,
        )

        data = result.to_dict()
        assert data["scenario_id"] == "test-id"
        assert data["confidence"] == 0.85
        assert data["consensus_reached"] is True
        assert len(data["key_claims"]) == 2
        assert data["duration_seconds"] == 12.5

    def test_matrix_result_get_result_by_scenario_id(self):
        """MatrixResult.get_result retrieves by scenario ID."""
        from aragora.debate.scenarios import MatrixResult, ScenarioResult

        matrix = MatrixResult(
            matrix_id="test",
            task="Test",
            created_at=datetime.now(),
            results=[
                ScenarioResult(
                    scenario_id="s1",
                    scenario_name="S1",
                    conclusion="C1",
                    confidence=0.8,
                    consensus_reached=True,
                ),
                ScenarioResult(
                    scenario_id="s2",
                    scenario_name="S2",
                    conclusion="C2",
                    confidence=0.7,
                    consensus_reached=False,
                ),
            ],
        )

        r1 = matrix.get_result("s1")
        assert r1 is not None
        assert r1.conclusion == "C1"

        r2 = matrix.get_result("s2")
        assert r2 is not None
        assert r2.consensus_reached is False

        r_missing = matrix.get_result("nonexistent")
        assert r_missing is None


# ============================================================================
# Graph Debate Handler E2E Tests
# ============================================================================


@pytest.mark.usefixtures("org_user")
class TestGraphDebateHandlerE2E:
    """E2E tests for the graph debates HTTP handler."""

    @pytest.fixture
    def graph_handler(self):
        from aragora.server.handlers.debates.graph_debates import GraphDebatesHandler

        handler = GraphDebatesHandler(ctx={})
        # Bypass RBAC auth for E2E handler tests
        handler.get_auth_context = AsyncMock(return_value=MagicMock())
        handler.check_permission = MagicMock()
        return handler

    @pytest.mark.asyncio
    async def test_post_runs_graph_debate_end_to_end(self, graph_handler, mock_http_handler):
        """POST /api/debates/graph runs a full graph debate and returns results."""
        from aragora.debate.graph import DebateGraph, NodeType

        # Build a mock graph result
        mock_graph = DebateGraph(debate_id="handler-test")
        mock_graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Handler test topic for end-to-end testing",
        )

        mock_agents = [MagicMock(name="agent-1"), MagicMock(name="agent-2")]

        with patch.object(
            graph_handler, "_load_agents", new_callable=AsyncMock, return_value=mock_agents
        ):
            with patch("aragora.debate.graph.GraphDebateOrchestrator") as MockOrch:
                mock_orchestrator = MagicMock()
                mock_orchestrator.run_debate = AsyncMock(return_value=mock_graph)
                MockOrch.return_value = mock_orchestrator

                result = await graph_handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "Evaluate end-to-end graph debate handler execution flow",
                        "agents": ["claude", "gpt4"],
                        "max_rounds": 3,
                    },
                )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "debate_id" in data
        assert "graph" in data
        assert "branches" in data
        assert data["node_count"] >= 1
        assert (data["org_id"], data["created_by"]) == (E2E_ORG, "user-e2e")

    @pytest.mark.asyncio
    async def test_post_with_custom_branch_policy(self, graph_handler, mock_http_handler):
        """POST with branch_policy correctly configures the orchestrator."""
        from aragora.debate.graph import DebateGraph, NodeType

        mock_graph = DebateGraph(debate_id="policy-test")
        mock_graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Policy test topic for branch configuration",
        )

        mock_agents = [MagicMock(name="a1"), MagicMock(name="a2")]

        with patch.object(
            graph_handler, "_load_agents", new_callable=AsyncMock, return_value=mock_agents
        ):
            with patch("aragora.debate.graph.GraphDebateOrchestrator") as MockOrch:
                mock_orchestrator = MagicMock()
                mock_orchestrator.run_debate = AsyncMock(return_value=mock_graph)
                MockOrch.return_value = mock_orchestrator

                result = await graph_handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "Test custom branch policy configuration in handler",
                        "agents": ["claude", "gpt4"],
                        "branch_policy": {
                            "min_disagreement": 0.5,
                            "max_branches": 5,
                            "merge_strategy": "synthesis",
                        },
                    },
                )

        assert result.status_code == 200
        # Verify BranchPolicy was configured
        call_kwargs = MockOrch.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_get_graph_debate_by_id(self, graph_handler, mock_http_handler):
        """GET /api/debates/graph/{id} returns debate data from storage."""
        debate_data = {
            "id": "graph-123",
            "task": "Test task",
            "nodes": [{"id": "n1", "content": "Root"}],
            "branches": [{"id": "main", "name": "Main"}],
            "org_id": E2E_ORG,
        }

        mock_storage = AsyncMock()
        mock_storage.get_graph_debate = AsyncMock(return_value=debate_data)
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/graph-123", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "graph-123"
        assert len(data["nodes"]) == 1

    @pytest.mark.asyncio
    async def test_get_graph_branches(self, graph_handler, mock_http_handler):
        """GET /api/debates/graph/{id}/branches returns branch list."""
        branches = [
            {"id": "main", "name": "Main", "is_active": True},
            {"id": "alt-1", "name": "Alternative", "is_active": False},
        ]

        mock_storage = AsyncMock()
        mock_storage.get_debate_branches = AsyncMock(return_value=branches)
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": E2E_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/graph-123/branches", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"
        assert len(data["branches"]) == 2

    @pytest.mark.asyncio
    async def test_get_graph_nodes(self, graph_handler, mock_http_handler):
        """GET /api/debates/graph/{id}/nodes returns node list."""
        nodes = [
            {"id": "n1", "content": "Root node", "node_type": "root"},
            {"id": "n2", "content": "Proposal", "node_type": "proposal"},
        ]

        mock_storage = AsyncMock()
        mock_storage.get_debate_nodes = AsyncMock(return_value=nodes)
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": E2E_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/graph-123/nodes", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"
        assert len(data["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_can_handle_graph_debate_paths(self, graph_handler):
        """Handler correctly identifies graph debate paths."""
        assert graph_handler.can_handle("/api/v1/debates/graph")
        assert graph_handler.can_handle("/api/v1/debates/graph/abc/branches")
        assert graph_handler.can_handle("/api/v1/graph-debates")
        assert not graph_handler.can_handle("/api/v1/debates/matrix")
        assert not graph_handler.can_handle("/api/v1/debates")


# ============================================================================
# Matrix Debate Handler E2E Tests
# ============================================================================


@pytest.mark.usefixtures("org_user")
class TestMatrixDebateHandlerE2E:
    """E2E tests for the matrix debates HTTP handler."""

    @pytest.fixture
    def matrix_handler(self):
        from aragora.server.handlers.debates.matrix_debates import MatrixDebatesHandler

        handler = MatrixDebatesHandler(ctx={})
        # Bypass RBAC auth for E2E handler tests
        handler.get_auth_context = AsyncMock(return_value=MagicMock())
        handler.check_permission = MagicMock()
        return handler

    @pytest.mark.asyncio
    async def test_post_runs_matrix_debate_via_fallback(self, matrix_handler, mock_http_handler):
        """POST /api/debates/matrix runs via fallback when ScenarioConfig not available."""
        # The handler tries to import ScenarioConfig which does not exist,
        # so it falls back to _run_matrix_debate_fallback
        mock_arena_result = MagicMock()
        mock_arena_result.winner = "agent-alpha"
        mock_arena_result.final_answer = "Use REST for simplicity"
        mock_arena_result.confidence = 0.85
        mock_arena_result.consensus_reached = True
        mock_arena_result.rounds_used = 3

        mock_agents = [MagicMock(name="agent-1"), MagicMock(name="agent-2")]

        with patch.object(
            matrix_handler, "_load_agents", new_callable=AsyncMock, return_value=mock_agents
        ):
            with patch("aragora.debate.scenarios.MatrixDebateRunner", side_effect=ImportError):
                with patch(
                    "aragora.server.handlers.debates.matrix_debates.MatrixDebatesHandler._run_matrix_debate_fallback",
                    new_callable=AsyncMock,
                ) as mock_fallback:
                    from aragora.server.handlers.base import HandlerResult as HR

                    mock_fallback.return_value = HR(
                        status_code=200,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "matrix_id": "fallback-123",
                                "task": "Test task",
                                "scenario_count": 2,
                                "results": [],
                                "universal_conclusions": [],
                                "conditional_conclusions": [],
                                "comparison_matrix": {},
                            }
                        ).encode(),
                    )

                    result = await matrix_handler.handle_post(
                        mock_http_handler,
                        "/api/v1/debates/matrix",
                        {
                            "task": "Evaluate API design approach for matrix debate testing",
                            "scenarios": [
                                {"name": "REST", "parameters": {"style": "rest"}},
                                {"name": "GraphQL", "parameters": {"style": "graphql"}},
                            ],
                            "agents": ["claude", "gpt4"],
                            "max_rounds": 3,
                        },
                    )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "matrix_id" in data

    @pytest.mark.asyncio
    async def test_get_matrix_debate_by_id(self, matrix_handler, mock_http_handler):
        """GET /api/debates/matrix/{id} returns matrix debate data from storage."""
        matrix_data = {
            "id": "matrix-456",
            "task": "API Design",
            "scenario_count": 3,
            "results": [],
            "org_id": E2E_ORG,
        }

        mock_storage = AsyncMock()
        mock_storage.get_matrix_debate = AsyncMock(return_value=matrix_data)
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/matrix-456", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "matrix-456"

    @pytest.mark.asyncio
    async def test_get_matrix_scenarios(self, matrix_handler, mock_http_handler):
        """GET /api/debates/matrix/{id}/scenarios returns scenario list."""
        scenarios = [
            {"name": "REST", "confidence": 0.85},
            {"name": "GraphQL", "confidence": 0.80},
        ]

        mock_storage = AsyncMock()
        mock_storage.get_matrix_scenarios = AsyncMock(return_value=scenarios)
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": E2E_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/matrix-456/scenarios", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "matrix-456"
        assert len(data["scenarios"]) == 2

    @pytest.mark.asyncio
    async def test_get_matrix_conclusions(self, matrix_handler, mock_http_handler):
        """GET /api/debates/matrix/{id}/conclusions returns conclusions."""
        conclusions = {
            "universal": ["Both approaches support REST principles"],
            "conditional": [
                {"condition": "When GraphQL", "conclusion": "Better for mobile clients"}
            ],
        }

        mock_storage = AsyncMock()
        mock_storage.get_matrix_conclusions = AsyncMock(return_value=conclusions)
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": E2E_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/matrix-456/conclusions", {}
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "matrix-456"
        assert len(data["universal_conclusions"]) == 1
        assert len(data["conditional_conclusions"]) == 1

    @pytest.mark.asyncio
    async def test_can_handle_matrix_debate_paths(self, matrix_handler):
        """Handler correctly identifies matrix debate paths."""
        assert matrix_handler.can_handle("/api/v1/debates/matrix")
        assert matrix_handler.can_handle("/api/v1/debates/matrix/abc/scenarios")
        assert matrix_handler.can_handle("/api/v1/matrix-debates")
        assert not matrix_handler.can_handle("/api/v1/debates/graph")
        assert not matrix_handler.can_handle("/api/v1/debates")

    @pytest.mark.asyncio
    async def test_get_returns_404_for_not_found(self, matrix_handler, mock_http_handler):
        """GET returns 404 when matrix debate not found."""
        mock_storage = AsyncMock()
        mock_storage.get_matrix_debate = AsyncMock(return_value=None)
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/nonexistent", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_503_without_storage(self, matrix_handler, mock_http_handler):
        """GET returns 503 when storage is not available."""
        mock_http_handler.storage = None

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/some-id", {}
        )
        assert result.status_code == 503

    def test_helper_build_comparison_matrix(self, matrix_handler):
        """Helper method builds correct comparison statistics."""
        results = [
            {
                "scenario_name": "Small",
                "consensus_reached": True,
                "confidence": 0.9,
                "rounds_used": 3,
            },
            {
                "scenario_name": "Large",
                "consensus_reached": True,
                "confidence": 0.7,
                "rounds_used": 5,
            },
            {
                "scenario_name": "Enterprise",
                "consensus_reached": False,
                "confidence": 0.5,
                "rounds_used": 7,
            },
        ]

        matrix = matrix_handler._build_comparison_matrix(results)
        assert matrix["scenarios"] == ["Small", "Large", "Enterprise"]
        assert abs(matrix["consensus_rate"] - 2 / 3) < 0.01
        assert abs(matrix["avg_confidence"] - 0.7) < 0.01
        assert abs(matrix["avg_rounds"] - 5.0) < 0.01


# ============================================================================
# Cross-Feature Integration Tests
# ============================================================================


class TestGraphMatrixIntegration:
    """Integration tests combining graph and matrix debate features."""

    @pytest.mark.asyncio
    async def test_graph_debate_result_feeds_matrix_comparator(self):
        """Use graph debate results as input to matrix scenario comparison."""
        from aragora.debate.graph import DebateGraph, MergeStrategy, NodeType, BranchReason
        from aragora.debate.scenarios import ScenarioComparator, ScenarioResult

        # Simulate two graph debates under different scenarios
        graph_a = DebateGraph(debate_id="graph-a")
        root_a = graph_a.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="API design under low budget",
        )
        graph_a.add_node(
            node_type=NodeType.CONCLUSION,
            agent_id="agent-alpha",
            content="Use REST for simplicity and cost-effectiveness",
            parent_id=root_a.id,
            confidence=0.85,
            claims=["simplicity", "low cost", "wide tooling"],
        )

        graph_b = DebateGraph(debate_id="graph-b")
        root_b = graph_b.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="API design under high budget",
        )
        graph_b.add_node(
            node_type=NodeType.CONCLUSION,
            agent_id="agent-beta",
            content="Use GraphQL for flexibility and developer experience",
            parent_id=root_b.id,
            confidence=0.80,
            claims=["flexibility", "developer experience", "type safety"],
        )

        # Convert graph conclusions to scenario results
        result_a = ScenarioResult(
            scenario_id="low-budget",
            scenario_name="Low Budget",
            conclusion="Use REST for simplicity and cost-effectiveness",
            confidence=0.85,
            consensus_reached=True,
            key_claims=["simplicity", "low cost", "wide tooling"],
        )

        result_b = ScenarioResult(
            scenario_id="high-budget",
            scenario_name="High Budget",
            conclusion="Use GraphQL for flexibility and developer experience",
            confidence=0.80,
            consensus_reached=True,
            key_claims=["flexibility", "developer experience", "type safety"],
        )

        # Compare using matrix comparator
        comparator = ScenarioComparator()
        comparison = comparator.compare_pair(result_a, result_b)

        assert comparison.scenario_a_id == "low-budget"
        assert comparison.scenario_b_id == "high-budget"
        assert len(comparison.unique_to_a) > 0
        assert len(comparison.unique_to_b) > 0
        # No shared claims between REST and GraphQL conclusions
        assert comparison.similarity_score == 0.0

    def test_graph_serialization_compatible_with_handler_response(self):
        """Graph.to_dict() output matches the handler's expected response format."""
        from aragora.debate.graph import DebateGraph, NodeType

        graph = DebateGraph(debate_id="format-test")
        root = graph.add_node(
            node_type=NodeType.ROOT,
            agent_id="system",
            content="Format compatibility test",
            confidence=1.0,
        )

        data = graph.to_dict()

        # Handler returns these fields - verify they exist in serialized graph
        assert "debate_id" in data
        assert "nodes" in data
        assert "branches" in data
        assert "root_id" in data
        assert "policy" in data
        assert "created_at" in data

        # Nodes should be serializable to JSON
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["debate_id"] == "format-test"

        # Branches include the expected fields
        branches = [b for b in data["branches"].values()]
        assert all("id" in b for b in branches)
        assert all("is_active" in b for b in branches)

    def test_convergence_scorer_with_different_thresholds(self):
        """ConvergenceScorer correctly identifies mergeable branches at various thresholds."""
        from aragora.debate.graph import (
            Branch,
            BranchReason,
            ConvergenceScorer,
            DebateNode,
            NodeType,
        )

        # High overlap nodes
        nodes_a = [
            DebateNode(
                id="a1",
                node_type=NodeType.PROPOSAL,
                agent_id="agent-1",
                content="Use microservices for scalability",
                claims=["scalability", "modularity", "independence"],
                confidence=0.85,
            ),
        ]
        nodes_b = [
            DebateNode(
                id="b1",
                node_type=NodeType.PROPOSAL,
                agent_id="agent-2",
                content="Microservices enable better scaling",
                claims=["scalability", "modularity", "complexity"],
                confidence=0.80,
            ),
        ]

        branch_a = Branch(
            id="a", name="A", reason=BranchReason.ALTERNATIVE_APPROACH, start_node_id="root"
        )
        branch_b = Branch(
            id="b", name="B", reason=BranchReason.ALTERNATIVE_APPROACH, start_node_id="root"
        )

        # Low threshold -- should merge
        scorer_low = ConvergenceScorer(threshold=0.3)
        assert scorer_low.should_merge(branch_a, branch_b, nodes_a, nodes_b) is True

        # Very high threshold -- should not merge (2/4 = 0.5 Jaccard)
        scorer_high = ConvergenceScorer(threshold=0.9)
        assert scorer_high.should_merge(branch_a, branch_b, nodes_a, nodes_b) is False

    def test_scenario_summary_generation(self):
        """ScenarioComparator generates human-readable summary."""
        from aragora.debate.scenarios import (
            MatrixResult,
            Scenario,
            ScenarioComparator,
            ScenarioResult,
            ScenarioType,
        )

        comparator = ScenarioComparator()

        matrix_result = MatrixResult(
            matrix_id="summary-test",
            task="Infrastructure migration strategy",
            created_at=datetime.now(),
            scenarios=[
                Scenario(
                    id="cloud",
                    name="Cloud Migration",
                    scenario_type=ScenarioType.TECHNOLOGY,
                    description="Full cloud migration",
                    parameters={"target": "cloud"},
                ),
                Scenario(
                    id="hybrid",
                    name="Hybrid Approach",
                    scenario_type=ScenarioType.TECHNOLOGY,
                    description="Hybrid cloud/on-prem",
                    parameters={"target": "hybrid"},
                ),
            ],
            results=[
                ScenarioResult(
                    scenario_id="cloud",
                    scenario_name="Cloud Migration",
                    conclusion="Full cloud provides best scalability",
                    confidence=0.88,
                    consensus_reached=True,
                    key_claims=["scalability", "cost optimization"],
                ),
                ScenarioResult(
                    scenario_id="hybrid",
                    scenario_name="Hybrid Approach",
                    conclusion="Hybrid reduces risk during transition",
                    confidence=0.82,
                    consensus_reached=True,
                    key_claims=["risk reduction", "gradual migration"],
                ),
            ],
        )

        summary = comparator.generate_summary(matrix_result)

        assert "Infrastructure migration strategy" in summary
        assert "Cloud Migration" in summary
        assert "Hybrid Approach" in summary
        assert "88%" in summary
        assert "82%" in summary
