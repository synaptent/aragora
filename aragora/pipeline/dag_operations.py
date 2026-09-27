"""DAG Operations Coordinator for the Universal Pipeline.

Wraps existing subsystems (Arena, TaskDecomposer, MetaPlanner, AgentRouter,
KnowledgeMound, StatusPropagator) into node-level AI operations on a
UniversalGraph.

Usage:
    graph = UniversalGraph(id="g1")
    coord = DAGOperationsCoordinator(graph)
    result = await coord.decompose_node("node-1")
    result = await coord.auto_flow(["idea A", "idea B"])
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from aragora.canvas.stages import PipelineStage, StageEdgeType
from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode

logger = logging.getLogger(__name__)


@dataclass
class DAGOperationResult:
    """Result of a DAG operation."""

    success: bool
    message: str
    created_nodes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DAGOperationsCoordinator:
    """Coordinates AI operations on a UniversalGraph.

    Each method validates the target node, calls the underlying subsystem,
    creates/updates graph nodes, and returns a DAGOperationResult.
    """

    def __init__(
        self,
        graph: UniversalGraph,
        store: Any | None = None,
        control_plane: Any | None = None,
        federation_coordinator: Any | None = None,
    ) -> None:
        self.graph = graph
        self._store = store
        self._control_plane = control_plane
        self._federation_coordinator = federation_coordinator

    def _save(self) -> None:
        """Persist graph to store if available."""
        if self._store is not None:
            try:
                self._store.update(self.graph)
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug("Graph persistence failed: %s", e)

    async def debate_node(
        self,
        node_id: str,
        agents: list[str] | None = None,
        rounds: int = 3,
    ) -> DAGOperationResult:
        """Run Arena debate on a node's content."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {node_id} not found")

        try:
            from aragora.core import Environment
            from aragora.debate.orchestrator import Arena
            from aragora.debate.protocol import DebateProtocol

            env = Environment(task=f"{node.label}: {node.description}")
            protocol = DebateProtocol(rounds=rounds, consensus="majority")

            debate_agents = []
            if agents:
                from aragora.agents import create_agent

                agent_factory = cast(Callable[[str], Any], create_agent)
                for agent_name in agents:
                    try:
                        debate_agents.append(agent_factory(agent_name))
                    except (RuntimeError, ImportError, ValueError) as exc:
                        logger.debug("Skipping agent %r: %s", agent_name, exc)

            if not debate_agents:
                return DAGOperationResult(
                    success=False,
                    message="No agents available for debate",
                )

            arena = Arena(env, debate_agents, protocol)
            result = await arena.run()

            node.metadata["debate_result"] = {
                "confidence": getattr(result, "confidence", 0),
                "final_answer": getattr(result, "final_answer", ""),
            }
            node.confidence = getattr(result, "confidence", node.confidence)
            self._save()

            return DAGOperationResult(
                success=True,
                message=f"Debate completed with confidence {node.confidence:.2f}",
                metadata={"confidence": node.confidence},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="Debate infrastructure not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("debate_node failed: %s", e)
            return DAGOperationResult(success=False, message="Debate failed")

    async def decompose_node(self, node_id: str) -> DAGOperationResult:
        """Use TaskDecomposer to break node into children."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {node_id} not found")

        try:
            from aragora.nomic.task_decomposer import TaskDecomposer

            decomposer = TaskDecomposer()
            result = decomposer.analyze(f"{node.label}: {node.description}")

            if not result.should_decompose or not result.subtasks:
                return DAGOperationResult(
                    success=True,
                    message="No decomposition needed",
                    metadata={"complexity": result.complexity_score},
                )

            created_ids: list[str] = []
            for subtask in result.subtasks:
                child_id = f"{node.stage.value}-{uuid.uuid4().hex[:8]}"
                child = UniversalNode(
                    id=child_id,
                    stage=node.stage,
                    node_subtype=node.node_subtype,
                    label=subtask.title,
                    description=subtask.description,
                    parent_ids=[node.id],
                    source_stage=node.stage,
                    data={"complexity": subtask.estimated_complexity},
                )
                self.graph.add_node(child)
                created_ids.append(child_id)

                edge = UniversalEdge(
                    id=f"edge-{uuid.uuid4().hex[:8]}",
                    source_id=node.id,
                    target_id=child_id,
                    edge_type=StageEdgeType.DECOMPOSES_INTO,
                    label="decomposes_into",
                )
                self.graph.add_edge(edge)

            self._save()
            return DAGOperationResult(
                success=True,
                message=f"Decomposed into {len(created_ids)} subtasks",
                created_nodes=created_ids,
                metadata={"complexity": result.complexity_score},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="TaskDecomposer not available",
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("decompose_node failed: %s", e)
            return DAGOperationResult(success=False, message="Decomposition failed")

    async def prioritize_children(self, parent_id: str) -> DAGOperationResult:
        """Use MetaPlanner to rank children by priority."""
        node = self.graph.nodes.get(parent_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {parent_id} not found")

        children = [n for n in self.graph.nodes.values() if parent_id in n.parent_ids]
        if not children:
            return DAGOperationResult(success=True, message="No children to prioritize")

        try:
            from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig

            config = MetaPlannerConfig(quick_mode=True)
            planner = MetaPlanner(config=config)
            objective = "; ".join(c.label for c in children)
            goals = await planner.prioritize_work(objective=objective)

            # Apply priority from MetaPlanner results to child nodes
            for i, child in enumerate(children):
                if i < len(goals):
                    child.data["priority"] = goals[i].priority
                    child.data["estimated_impact"] = goals[i].estimated_impact
                else:
                    child.data["priority"] = i + 1

            self._save()
            return DAGOperationResult(
                success=True,
                message=f"Prioritized {len(children)} children",
                metadata={"priorities": [c.data.get("priority") for c in children]},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="MetaPlanner not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("prioritize_children failed: %s", e)
            return DAGOperationResult(success=False, message="Prioritization failed")

    async def assign_agents(self, node_ids: list[str]) -> DAGOperationResult:
        """Use AgentRouter to assign agent teams to nodes."""
        try:
            from aragora.nomic.agent_router import AgentRouter
            from aragora.nomic.task_decomposer import SubTask

            router = AgentRouter()
            assignments: dict[str, str] = {}

            for nid in node_ids:
                node = self.graph.nodes.get(nid)
                if node is None:
                    continue

                subtask = SubTask(
                    id=nid,
                    title=node.label,
                    description=node.description,
                    file_scope=node.data.get("file_scope", []),
                )
                track = router.determine_track(subtask)
                agent_type = router.select_agent_type(subtask, track)

                node.data["assigned_agent"] = agent_type
                node.data["track"] = track.value
                assignments[nid] = agent_type

            self._save()
            return DAGOperationResult(
                success=True,
                message=f"Assigned agents to {len(assignments)} nodes",
                metadata={"assignments": assignments},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="AgentRouter not available",
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("assign_agents failed: %s", e)
            return DAGOperationResult(success=False, message="Agent assignment failed")

    async def assign_agents_with_selector(
        self,
        node_ids: list[str] | None = None,
        team_selector: Any | None = None,
        available_agents: list[Any] | None = None,
    ) -> DAGOperationResult:
        """Use TeamSelector to assign agent pools to orchestration nodes.

        Walks orchestration-stage nodes and uses the TeamSelector's ELO-based
        scoring to pick the best agents for each node's domain.

        Args:
            node_ids: Specific node IDs to assign. If None, walks all
                orchestration nodes in the graph.
            team_selector: A TeamSelector instance. If None, attempts to
                create one with default settings.
            available_agents: Pool of candidate agents for selection.
                If None, attempts to discover agents via create_agent.
        """
        try:
            from aragora.debate.team_selector import TeamSelector
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="TeamSelector not available",
            )

        if team_selector is None:
            try:
                team_selector = TeamSelector()
            except (RuntimeError, TypeError, ValueError) as e:
                logger.debug("Failed to create default TeamSelector: %s", e)
                return DAGOperationResult(
                    success=False,
                    message="Could not create TeamSelector",
                )

        # Build candidate agent list
        if available_agents is None:
            try:
                from aragora.agents import create_agent

                agent_factory = cast(Callable[[str], Any], create_agent)
                available_agents = []
                for name in ("claude", "gpt", "gemini", "mistral", "grok"):
                    try:
                        available_agents.append(agent_factory(name))
                    except (RuntimeError, ImportError, ValueError) as exc:
                        logger.debug("Skipping agent %r: %s", name, exc)
            except ImportError:
                return DAGOperationResult(
                    success=False,
                    message="Agent creation not available",
                )

        if not available_agents:
            return DAGOperationResult(
                success=False,
                message="No agents available for selection",
            )

        # Determine target nodes
        if node_ids is not None:
            targets = [self.graph.nodes[nid] for nid in node_ids if nid in self.graph.nodes]
        else:
            targets = [
                n
                for n in self.graph.nodes.values()
                if n.stage == PipelineStage.ORCHESTRATION
                or n.data.get("orch_type") == "agent_task"
                or n.data.get("orchType") == "agent_task"
            ]

        assignments: dict[str, list[str]] = {}
        for node in targets:
            domain = node.data.get("domain", "general")
            selected = team_selector.select(
                available_agents,
                domain=domain,
                task=node.label,
            )
            agent_names = [getattr(a, "name", str(a)) for a in selected]
            node.data["agent_pool"] = agent_names
            assignments[node.id] = agent_names

        self._save()
        return DAGOperationResult(
            success=True,
            message=f"Assigned agent pools to {len(assignments)} nodes",
            metadata={"assignments": assignments},
        )

    async def debate_assignment(
        self,
        node_ids: list[str] | None = None,
        agents: list[str] | None = None,
        rounds: int = 2,
    ) -> DAGOperationResult:
        """Use a mini-Arena debate to decide agent assignments for nodes.

        Creates a structured prompt listing the tasks and candidate agents,
        runs a short debate, and parses the consensus into assignments.

        Args:
            node_ids: Specific node IDs to assign. If None, walks all
                orchestration nodes.
            agents: Candidate agent names. If None, uses defaults.
            rounds: Number of debate rounds (default 2 for speed).
        """
        # Collect target nodes
        if node_ids is not None:
            targets = [self.graph.nodes[nid] for nid in node_ids if nid in self.graph.nodes]
        else:
            targets = [
                n
                for n in self.graph.nodes.values()
                if n.stage == PipelineStage.ORCHESTRATION
                or n.data.get("orch_type") == "agent_task"
                or n.data.get("orchType") == "agent_task"
            ]

        if not targets:
            return DAGOperationResult(
                success=False,
                message="No target nodes found for debate-driven assignment",
            )

        agent_names = agents or ["claude", "gpt", "gemini", "mistral", "grok"]

        # Build structured prompt for the debate
        task_descriptions = "\n".join(
            f"- T{i + 1} ({n.id}): {n.label} — {n.description}" for i, n in enumerate(targets)
        )
        prompt = (
            f"Given the following tasks and available agents ({', '.join(agent_names)}), "
            f"assign the best agent(s) to each task. Consider agent strengths, "
            f"task complexity, and domain fit.\n\n"
            f"Tasks:\n{task_descriptions}\n\n"
            f"For each task, respond with: T<n>: <agent1>, <agent2>"
        )

        try:
            from aragora.core import Environment
            from aragora.debate.orchestrator import Arena
            from aragora.debate.protocol import DebateProtocol

            env = Environment(task=prompt)
            protocol = DebateProtocol(rounds=rounds, consensus="majority")

            debate_agents = []
            from aragora.agents import create_agent

            agent_factory = cast(Callable[[str], Any], create_agent)
            for agent_name in agent_names[:3]:  # Use up to 3 agents for the debate
                try:
                    debate_agents.append(agent_factory(agent_name))
                except (RuntimeError, ImportError, ValueError):
                    pass

            if not debate_agents:
                return DAGOperationResult(
                    success=False,
                    message="No agents available for assignment debate",
                )

            arena = Arena(env, debate_agents, protocol)
            result = await arena.run()

            # Parse assignments from debate result
            summary = getattr(result, "summary", str(result))
            assignments: dict[str, list[str]] = {}

            for i, node in enumerate(targets):
                tag = f"T{i + 1}"
                assigned: list[str] = []
                for line in summary.split("\n"):
                    if tag in line and ":" in line:
                        after_colon = line.split(":", 1)[1].strip()
                        for candidate in agent_names:
                            if candidate.lower() in after_colon.lower():
                                assigned.append(candidate)
                        break

                if not assigned:
                    # Fallback: assign first available agent
                    assigned = [agent_names[0]]

                node.data["agent_pool"] = assigned
                node.data["assignment_method"] = "debate"
                assignments[node.id] = assigned

            self._save()
            return DAGOperationResult(
                success=True,
                message=f"Debate-assigned agents to {len(assignments)} nodes",
                metadata={
                    "assignments": assignments,
                    "debate_rounds": rounds,
                },
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="Arena not available for debate-driven assignment",
            )
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("debate_assignment failed: %s", e)
            return DAGOperationResult(
                success=False,
                message="Debate-driven assignment failed",
            )

    async def execute_node(self, node_id: str) -> DAGOperationResult:
        """Execute via HardenedOrchestrator with status propagation.

        If the node specifies ``data.workspace_id`` different from the current
        workspace, delegates through ``CrossWorkspaceCoordinator`` (federation).
        """
        node = self.graph.nodes.get(node_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {node_id} not found")

        if node.stage != PipelineStage.ORCHESTRATION:
            return DAGOperationResult(
                success=False,
                message=f"Only orchestration nodes can be executed, got {node.stage.value}",
            )

        # Cross-workspace federation: delegate to remote workspace if needed
        target_workspace = node.data.get("workspace_id")
        if target_workspace and self._federation_coordinator is not None:
            return await self._execute_federated(node, target_workspace)

        try:
            from aragora.pipeline.status_propagator import StatusPropagator

            propagator = StatusPropagator(self.graph)
            propagator.propagate_status(node_id, "in_progress")
        except ImportError:
            pass

        try:
            from aragora.nomic.hardened_orchestrator import HardenedOrchestrator

            orchestrator = HardenedOrchestrator()
            result = await orchestrator.execute_goal(
                goal=f"{node.label}: {getattr(node, 'description', '')}",
            )

            status = "succeeded" if getattr(result, "success", False) else "failed"
            node.execution_status = status

            try:
                from aragora.pipeline.status_propagator import StatusPropagator

                propagator = StatusPropagator(self.graph)
                propagator.propagate_status(node_id, status)
            except ImportError:
                pass

            self._save()
            return DAGOperationResult(
                success=status == "succeeded",
                message=f"Execution {status}",
                metadata={"execution_status": status},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="HardenedOrchestrator not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("execute_node failed: %s", e)
            try:
                from aragora.pipeline.status_propagator import StatusPropagator

                StatusPropagator(self.graph).propagate_status(node_id, "failed")
            except ImportError:
                pass
            return DAGOperationResult(success=False, message="Execution failed")

    async def _execute_federated(
        self,
        node: UniversalNode,
        target_workspace: str,
    ) -> DAGOperationResult:
        """Delegate execution to a remote workspace via CrossWorkspaceCoordinator.

        Uses the three-tier policy hierarchy, consent management, and audit
        trail built into CrossWorkspaceCoordinator.
        """
        try:
            from aragora.coordination.cross_workspace import CrossWorkspaceCoordinator

            coordinator = self._federation_coordinator
            if not isinstance(coordinator, CrossWorkspaceCoordinator):
                # Wrap raw reference if needed
                coordinator = CrossWorkspaceCoordinator()

            result = await coordinator.execute_remote(  # type: ignore[attr-defined]
                workspace_id=target_workspace,
                task={
                    "node_id": node.id,
                    "label": node.label,
                    "description": getattr(node, "description", ""),
                    "stage": node.stage.value if hasattr(node.stage, "value") else str(node.stage),
                    "data": node.data,
                },
                graph_id=self.graph.id,
            )

            success = getattr(result, "success", bool(result))
            node.metadata["execution_status"] = "completed" if success else "failed"
            node.metadata["federated_workspace"] = target_workspace
            self._save()

            return DAGOperationResult(
                success=success,
                message=f"Federated execution to workspace '{target_workspace}'",
                metadata={
                    "workspace_id": target_workspace,
                    "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
                },
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="CrossWorkspaceCoordinator not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Federated execution failed for node %s: %s", node.id, e)
            node.metadata["execution_status"] = "federation_error"
            self._save()
            return DAGOperationResult(
                success=False,
                message=f"Federation to workspace '{target_workspace}' failed",
            )

    async def execute_node_via_scheduler(
        self,
        node_id: str,
        poll_interval: float = 0.5,
        max_polls: int = 600,
    ) -> DAGOperationResult:
        """Execute a node by submitting it to the Control Plane scheduler.

        Requires a control_plane instance (e.g. ControlPlaneCoordinator) to be
        set on this coordinator. The control plane handles distributed task
        routing, capability matching, and retry logic.
        """
        if self._control_plane is None:
            return DAGOperationResult(
                success=False,
                message="Control plane not configured",
            )

        node = self.graph.nodes.get(node_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {node_id} not found")

        try:
            import asyncio

            task_id = await self._control_plane.submit_task(
                task_type="pipeline_node",
                payload={
                    "node_id": node.id,
                    "label": node.label,
                    "description": node.description,
                    "stage": node.stage.value if hasattr(node.stage, "value") else str(node.stage),
                    "data": node.data,
                },
                metadata={"graph_id": self.graph.id, "node_id": node.id},
            )

            node.metadata["execution_status"] = "submitted"
            node.metadata["scheduler_task_id"] = task_id

            # Poll for completion
            for _ in range(max_polls):
                task = await self._control_plane.get_task(task_id)
                if task is None:
                    break
                status_val = getattr(task, "status", None)
                status_str = status_val.value if hasattr(status_val, "value") else str(status_val)  # type: ignore[union-attr]
                if status_str in ("completed", "failed", "cancelled"):
                    node.metadata["execution_status"] = status_str
                    node.metadata["task_result"] = getattr(task, "result", None)
                    self._save()
                    return DAGOperationResult(
                        success=status_str == "completed",
                        message=f"Scheduler execution {status_str}",
                        metadata={
                            "task_id": task_id,
                            "execution_status": status_str,
                        },
                    )
                await asyncio.sleep(poll_interval)

            node.metadata["execution_status"] = "timeout"
            self._save()
            return DAGOperationResult(
                success=False,
                message="Scheduler execution timed out waiting for result",
                metadata={"task_id": task_id},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="Control plane scheduler not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("execute_node_via_scheduler failed: %s", e)
            node.metadata["execution_status"] = "error"
            self._save()
            return DAGOperationResult(success=False, message="Scheduler execution failed")

    async def find_precedents(
        self,
        node_id: str,
        max_results: int = 5,
    ) -> DAGOperationResult:
        """Find similar past work via KnowledgeMound semantic search."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return DAGOperationResult(success=False, message=f"Node {node_id} not found")

        try:
            from aragora.knowledge.mound import get_knowledge_mound

            km = get_knowledge_mound()
            if km is None:
                return DAGOperationResult(
                    success=False,
                    message="KnowledgeMound not available",
                )

            search_query = f"{node.label} {getattr(node, 'description', '')}"
            results = await km.query(query=search_query, limit=max_results)  # type: ignore[misc]

            precedents = []
            if results:
                for r in results:
                    precedents.append(
                        {
                            "title": getattr(r, "title", str(r)),
                            "similarity": getattr(r, "similarity", 0),
                        }
                    )

            node.metadata["precedents"] = precedents
            self._save()

            return DAGOperationResult(
                success=True,
                message=f"Found {len(precedents)} precedents",
                metadata={"precedents": precedents},
            )
        except ImportError:
            return DAGOperationResult(
                success=False,
                message="KnowledgeMound not available",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("find_precedents failed: %s", e)
            return DAGOperationResult(success=False, message="Precedent search failed")

    async def cluster_ideas(
        self,
        ideas: list[str],
        threshold: float = 0.3,
    ) -> DAGOperationResult:
        """Cluster ideas and add them to graph with similarity edges."""
        if not ideas:
            return DAGOperationResult(success=False, message="No ideas provided")

        from aragora.pipeline.idea_clusterer import cluster_ideas as _cluster

        result = _cluster(ideas, threshold=threshold)

        created_ids: list[str] = []
        idea_node_ids: list[str] = []

        # Create a node for each idea
        for i, idea_text in enumerate(ideas):
            node_id = f"ideas-{uuid.uuid4().hex[:8]}"
            node = UniversalNode(
                id=node_id,
                stage=PipelineStage.IDEAS,
                node_subtype="concept",
                label=idea_text[:80],
                description=idea_text,
            )
            self.graph.add_node(node)
            created_ids.append(node_id)
            idea_node_ids.append(node_id)

        # Create cluster nodes
        for cluster in result.clusters:
            if len(cluster.idea_indices) > 1:
                cluster_id = f"ideas-cluster-{uuid.uuid4().hex[:8]}"
                cluster_node = UniversalNode(
                    id=cluster_id,
                    stage=PipelineStage.IDEAS,
                    node_subtype="cluster",
                    label=cluster.label,
                    description=f"Cluster of {len(cluster.idea_indices)} ideas",
                    data={"centroid_terms": cluster.centroid_terms},
                )
                self.graph.add_node(cluster_node)
                created_ids.append(cluster_id)

                # Link ideas to cluster
                for idx in cluster.idea_indices:
                    edge = UniversalEdge(
                        id=f"edge-{uuid.uuid4().hex[:8]}",
                        source_id=idea_node_ids[idx],
                        target_id=cluster_id,
                        edge_type=StageEdgeType.RELATES_TO,
                        label="belongs_to_cluster",
                    )
                    self.graph.add_edge(edge)

        # Add similarity edges
        for i, j, sim in result.similarity_edges:
            edge = UniversalEdge(
                id=f"edge-sim-{uuid.uuid4().hex[:8]}",
                source_id=idea_node_ids[i],
                target_id=idea_node_ids[j],
                edge_type=StageEdgeType.RELATES_TO,
                label=f"similarity={sim:.2f}",
                weight=sim,
            )
            self.graph.add_edge(edge)

        self._save()
        return DAGOperationResult(
            success=True,
            message=f"Clustered {len(ideas)} ideas into {len(result.clusters)} clusters",
            created_nodes=created_ids,
            metadata={
                "cluster_count": len(result.clusters),
                "edge_count": len(result.similarity_edges),
                "idea_node_ids": idea_node_ids,
            },
        )

    async def auto_flow(
        self,
        ideas: list[str],
        config: dict[str, Any] | None = None,
    ) -> DAGOperationResult:
        """Full pipeline: cluster -> goals -> tasks -> assign.

        This is a convenience method that chains multiple operations.
        """
        config = config or {}

        # Step 1: Cluster ideas
        cluster_result = await self.cluster_ideas(
            ideas,
            threshold=config.get("threshold", 0.3),
        )
        if not cluster_result.success:
            return cluster_result

        idea_node_ids = cluster_result.metadata.get("idea_node_ids", [])

        # Step 2: Promote ideas to goals
        try:
            from aragora.pipeline.stage_transitions import ideas_to_goals

            goal_nodes = ideas_to_goals(self.graph, idea_node_ids)
            goal_ids = [g.id for g in goal_nodes]
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("auto_flow ideas_to_goals failed: %s", e)
            return DAGOperationResult(
                success=True,
                message="Clustered ideas but goal promotion failed",
                created_nodes=cluster_result.created_nodes,
                metadata=cluster_result.metadata,
            )

        # Step 3: Promote goals to actions
        try:
            from aragora.pipeline.stage_transitions import goals_to_actions

            action_nodes = goals_to_actions(self.graph, goal_ids)
            action_ids = [a.id for a in action_nodes]
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning("auto_flow goals_to_actions failed: %s", e)
            action_ids = []

        # Step 4: Assign agents to action nodes
        if action_ids:
            await self.assign_agents(action_ids)

        all_created = cluster_result.created_nodes + goal_ids + action_ids

        self._save()
        return DAGOperationResult(
            success=True,
            message=(
                f"Auto-flow complete: {len(ideas)} ideas -> "
                f"{len(goal_ids)} goals -> {len(action_ids)} actions"
            ),
            created_nodes=all_created,
            metadata={
                "ideas": len(ideas),
                "clusters": cluster_result.metadata.get("cluster_count", 0),
                "goals": len(goal_ids),
                "actions": len(action_ids),
            },
        )


__all__ = ["DAGOperationsCoordinator", "DAGOperationResult"]
