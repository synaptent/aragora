"""
Canvas State Manager.

Manages canvas state, handles operations, and broadcasts updates
to connected clients via WebSocket for real-time collaboration.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable, Coroutine

from .models import (
    Canvas,
    CanvasEdge,
    CanvasEvent,
    CanvasEventType,
    CanvasNode,
    CanvasNodeType,
    EdgeType,
    Position,
)

logger = logging.getLogger(__name__)


class CanvasStateManager:
    """
    Manages canvas state and operations for real-time collaboration.

    Handles:
    - Canvas CRUD operations
    - Node and edge management
    - Event broadcasting to connected clients
    - Undo/redo history
    - Collaborative editing with user selections
    """

    def __init__(self, max_history: int = 100):
        """
        Initialize the canvas state manager.

        Args:
            max_history: Maximum undo history size per canvas
        """
        self._canvases: dict[str, Canvas] = {}
        self._subscribers: dict[str, set[Callable[[CanvasEvent], Coroutine[Any, Any, None]]]] = {}
        self._user_selections: dict[
            str, dict[str, set[str]]
        ] = {}  # canvas_id -> user_id -> node_ids
        self._history: dict[str, list[CanvasEvent]] = {}  # canvas_id -> events
        self._max_history = max_history
        self._lock = asyncio.Lock()

    # =========================================================================
    # Canvas Management
    # =========================================================================

    async def create_canvas(
        self,
        canvas_id: str | None = None,
        name: str = "Untitled Canvas",
        owner_id: str | None = None,
        workspace_id: str | None = None,
        **metadata: Any,
    ) -> Canvas:
        """Create a new canvas."""
        async with self._lock:
            if canvas_id is None:
                canvas_id = str(uuid.uuid4())

            canvas = Canvas(
                id=canvas_id,
                name=name,
                owner_id=owner_id,
                workspace_id=workspace_id,
                metadata=metadata,
            )
            self._canvases[canvas_id] = canvas
            self._subscribers[canvas_id] = set()
            self._history[canvas_id] = []
            logger.info("Created canvas: %s (%s)", canvas_id, name)
            return canvas

    async def get_canvas(self, canvas_id: str) -> Canvas | None:
        """Get a canvas by ID."""
        return self._canvases.get(canvas_id)

    async def get_or_create_canvas(
        self,
        canvas_id: str,
        name: str = "Untitled Canvas",
        **kwargs: Any,
    ) -> Canvas:
        """Get an existing canvas or create a new one."""
        canvas = self._canvases.get(canvas_id)
        if canvas is None:
            canvas = await self.create_canvas(canvas_id=canvas_id, name=name, **kwargs)
        return canvas

    async def delete_canvas(self, canvas_id: str) -> bool:
        """Delete a canvas."""
        async with self._lock:
            if canvas_id in self._canvases:
                del self._canvases[canvas_id]
                self._subscribers.pop(canvas_id, None)
                self._history.pop(canvas_id, None)
                self._user_selections.pop(canvas_id, None)
                logger.info("Deleted canvas: %s", canvas_id)
                return True
            return False

    async def list_canvases(
        self,
        owner_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[Canvas]:
        """List canvases, optionally filtered by owner or workspace."""
        canvases = list(self._canvases.values())

        if owner_id:
            canvases = [c for c in canvases if c.owner_id == owner_id]
        if workspace_id:
            canvases = [c for c in canvases if c.workspace_id == workspace_id]

        return canvases

    async def update_canvas(
        self,
        canvas_id: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        owner_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> Canvas | None:
        """
        Update canvas properties.

        Args:
            canvas_id: ID of the canvas to update
            name: New name for the canvas (if provided)
            metadata: Metadata to merge into existing metadata (if provided)
            owner_id: New owner ID (if provided)
            workspace_id: New workspace ID (if provided)
            user_id: ID of the user performing the update (for event tracking)

        Returns:
            Updated Canvas object, or None if canvas not found
        """
        async with self._lock:
            canvas = self._canvases.get(canvas_id)
            if not canvas:
                return None

            updates: dict[str, Any] = {}

            if name is not None:
                canvas.name = name
                updates["name"] = name

            if metadata is not None:
                canvas.metadata.update(metadata)
                updates["metadata"] = metadata

            if owner_id is not None:
                canvas.owner_id = owner_id
                updates["owner_id"] = owner_id

            if workspace_id is not None:
                canvas.workspace_id = workspace_id
                updates["workspace_id"] = workspace_id

            canvas.updated_at = datetime.now(timezone.utc)
            updates["updated_at"] = canvas.updated_at.isoformat()

            # Broadcast update event
            event = CanvasEvent(
                event_type=CanvasEventType.CANVAS_UPDATE,
                canvas_id=canvas_id,
                user_id=user_id,
                data={"updates": updates, "canvas": canvas.to_dict()},
            )
            await self._broadcast(canvas_id, event)
            self._add_to_history(canvas_id, event)

            logger.info("Updated canvas: %s (updates: %s)", canvas_id, list(updates.keys()))
            return canvas

    # =========================================================================
    # Node Operations
    # =========================================================================

    async def add_node(
        self,
        canvas_id: str,
        node_type: CanvasNodeType,
        position: Position,
        label: str = "",
        data: dict[str, Any] | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> CanvasNode | None:
        """Add a node to the canvas."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        node = canvas.add_node(
            node_type=node_type,
            position=position,
            label=label,
            data=data,
            **kwargs,
        )

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_CREATE,
            canvas_id=canvas_id,
            node_id=node.id,
            user_id=user_id,
            data=node.to_dict(),
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return node

    async def update_node(
        self,
        canvas_id: str,
        node_id: str,
        user_id: str | None = None,
        **updates: Any,
    ) -> CanvasNode | None:
        """Update a node's properties."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        node = canvas.get_node(node_id)
        if not node:
            return None

        # Apply updates
        if "label" in updates:
            node.label = updates["label"]
        if "data" in updates:
            node.data.update(updates["data"])
        if "style" in updates:
            node.style.update(updates["style"])
        if "locked" in updates:
            node.locked = updates["locked"]

        node.updated_at = datetime.now(timezone.utc)

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_UPDATE,
            canvas_id=canvas_id,
            node_id=node_id,
            user_id=user_id,
            data={"updates": updates, "node": node.to_dict()},
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return node

    async def move_node(
        self,
        canvas_id: str,
        node_id: str,
        x: float,
        y: float,
        user_id: str | None = None,
    ) -> CanvasNode | None:
        """Move a node to a new position."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        node = canvas.get_node(node_id)
        if not node:
            return None

        if node.locked:
            return None

        old_position = node.position.to_dict()
        node.move(x, y)

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_MOVE,
            canvas_id=canvas_id,
            node_id=node_id,
            user_id=user_id,
            data={
                "old_position": old_position,
                "new_position": node.position.to_dict(),
            },
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return node

    async def resize_node(
        self,
        canvas_id: str,
        node_id: str,
        width: float,
        height: float,
        user_id: str | None = None,
    ) -> CanvasNode | None:
        """Resize a node."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        node = canvas.get_node(node_id)
        if not node:
            return None

        if node.locked:
            return None

        old_size = node.size.to_dict()
        node.resize(width, height)

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_RESIZE,
            canvas_id=canvas_id,
            node_id=node_id,
            user_id=user_id,
            data={
                "old_size": old_size,
                "new_size": node.size.to_dict(),
            },
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return node

    async def delete_node(
        self,
        canvas_id: str,
        node_id: str,
        user_id: str | None = None,
    ) -> bool:
        """Delete a node from the canvas."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return False

        node = canvas.remove_node(node_id)
        if not node:
            return False

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_DELETE,
            canvas_id=canvas_id,
            node_id=node_id,
            user_id=user_id,
            data={"node": node.to_dict()},
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return True

    async def select_node(
        self,
        canvas_id: str,
        node_id: str,
        user_id: str,
        multi_select: bool = False,
    ) -> None:
        """Select a node (for collaborative cursors)."""
        if canvas_id not in self._user_selections:
            self._user_selections[canvas_id] = {}

        if user_id not in self._user_selections[canvas_id]:
            self._user_selections[canvas_id][user_id] = set()

        if not multi_select:
            self._user_selections[canvas_id][user_id].clear()

        self._user_selections[canvas_id][user_id].add(node_id)

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.NODE_SELECT,
            canvas_id=canvas_id,
            node_id=node_id,
            user_id=user_id,
            data={
                "selected_nodes": list(self._user_selections[canvas_id][user_id]),
                "multi_select": multi_select,
            },
        )
        await self._broadcast(canvas_id, event)

    # =========================================================================
    # Edge Operations
    # =========================================================================

    async def add_edge(
        self,
        canvas_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType = EdgeType.DEFAULT,
        label: str = "",
        user_id: str | None = None,
        **kwargs: Any,
    ) -> CanvasEdge | None:
        """Add an edge between two nodes."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        edge = canvas.add_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            label=label,
            **kwargs,
        )
        if not edge:
            return None

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.EDGE_CREATE,
            canvas_id=canvas_id,
            edge_id=edge.id,
            user_id=user_id,
            data=edge.to_dict(),
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return edge

    async def update_edge(
        self,
        canvas_id: str,
        edge_id: str,
        user_id: str | None = None,
        **updates: Any,
    ) -> CanvasEdge | None:
        """Update an edge's properties."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        edge = canvas.get_edge(edge_id)
        if not edge:
            return None

        # Apply updates
        if "label" in updates:
            edge.label = updates["label"]
        if "data" in updates:
            edge.data.update(updates["data"])
        if "style" in updates:
            edge.style.update(updates["style"])
        if "animated" in updates:
            edge.animated = updates["animated"]

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.EDGE_UPDATE,
            canvas_id=canvas_id,
            edge_id=edge_id,
            user_id=user_id,
            data={"updates": updates, "edge": edge.to_dict()},
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return edge

    async def delete_edge(
        self,
        canvas_id: str,
        edge_id: str,
        user_id: str | None = None,
    ) -> bool:
        """Delete an edge from the canvas."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return False

        edge = canvas.remove_edge(edge_id)
        if not edge:
            return False

        # Broadcast event
        event = CanvasEvent(
            event_type=CanvasEventType.EDGE_DELETE,
            canvas_id=canvas_id,
            edge_id=edge_id,
            user_id=user_id,
            data={"edge": edge.to_dict()},
        )
        await self._broadcast(canvas_id, event)
        self._add_to_history(canvas_id, event)

        return True

    # =========================================================================
    # Actions
    # =========================================================================

    async def execute_action(
        self,
        canvas_id: str,
        action: str,
        params: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a canvas action.

        Actions can trigger debates, workflows, or other operations.
        """
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return {"success": False, "error": "Canvas not found"}

        # Broadcast action event
        action_event = CanvasEvent(
            event_type=CanvasEventType.ACTION,
            canvas_id=canvas_id,
            user_id=user_id,
            data={"action": action, "params": params},
        )
        await self._broadcast(canvas_id, action_event)

        result: dict[str, Any] = {"success": True, "action": action}

        # Handle built-in actions
        if action == "start_debate":
            result = await self._handle_start_debate(canvas, params, user_id)
        elif action == "run_workflow":
            result = await self._handle_run_workflow(canvas, params, user_id)
        elif action == "query_knowledge":
            result = await self._handle_query_knowledge(canvas, params, user_id)
        elif action == "clear_canvas":
            canvas.clear()
            result = {"success": True, "action": action}
        else:
            result = {"success": False, "error": f"Unknown action: {action}"}

        # Broadcast result event
        result_event = CanvasEvent(
            event_type=CanvasEventType.ACTION_RESULT,
            canvas_id=canvas_id,
            user_id=user_id,
            data={"action": action, "result": result},
        )
        await self._broadcast(canvas_id, result_event)

        return result

    async def _handle_start_debate(
        self,
        canvas: Canvas,
        params: dict[str, Any],
        user_id: str | None,
    ) -> dict[str, Any]:
        """Handle starting a debate from the canvas."""
        question = params.get("question", "")
        if not question:
            return {"success": False, "error": "Question is required"}

        # Create a debate node
        debate_node = canvas.add_node(
            node_type=CanvasNodeType.DEBATE,
            position=Position(params.get("x", 100), params.get("y", 100)),
            label=question[:50] + "..." if len(question) > 50 else question,
            data={"question": question, "status": "pending"},
        )

        # Broadcast debate start event
        event = CanvasEvent(
            event_type=CanvasEventType.DEBATE_START,
            canvas_id=canvas.id,
            node_id=debate_node.id,
            user_id=user_id,
            data={"question": question, "node_id": debate_node.id},
        )
        await self._broadcast(canvas.id, event)

        # Actually run the debate
        try:
            from aragora.config.settings import DebateSettings
            from aragora.core import Environment
            from aragora.protocols.debate import DebateProtocol
            from aragora.debate.orchestrator import Arena

            # Update node status to running
            debate_node.data["status"] = "running"
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.NODE_UPDATE,
                    canvas_id=canvas.id,
                    node_id=debate_node.id,
                    data={"status": "running"},
                ),
            )

            # Create environment and run debate
            env = Environment(task=question)
            defaults = DebateSettings()
            protocol = DebateProtocol(
                rounds=params.get("rounds", defaults.default_rounds),
                consensus=params.get("consensus", defaults.default_consensus),
            )

            # Get agents - use configured defaults or from params
            agents = await self._get_debate_agents(params.get("agents"))

            arena = Arena(env, agents, protocol)
            # Optional timeout for callers (especially CI/E2E) that need bounded latency.
            timeout_raw = params.get("timeout_seconds")
            if timeout_raw is None:
                result = await arena.run()
            else:
                try:
                    debate_timeout_seconds = float(timeout_raw)
                except (TypeError, ValueError):
                    debate_timeout_seconds = 45.0
                if debate_timeout_seconds <= 0:
                    debate_timeout_seconds = 45.0
                result = await asyncio.wait_for(arena.run(), timeout=debate_timeout_seconds)

            # Update node with results
            debate_node.data["status"] = "completed"
            debate_node.data["result"] = {
                "decision": result.decision if hasattr(result, "decision") else str(result),
                "consensus_reached": getattr(result, "consensus_reached", False),
                "rounds_used": getattr(result, "rounds_used", protocol.rounds),
            }

            # Broadcast completion
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.DEBATE_END,
                    canvas_id=canvas.id,
                    node_id=debate_node.id,
                    data=debate_node.data,
                ),
            )

            return {
                "success": True,
                "action": "start_debate",
                "debate_node_id": debate_node.id,
                "result": debate_node.data["result"],
            }

        except asyncio.TimeoutError:
            logger.warning("Debate execution timed out")
            debate_node.data["status"] = "timeout"
            debate_node.data["error"] = "Debate execution timed out"
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.ERROR,
                    canvas_id=canvas.id,
                    node_id=debate_node.id,
                    data={"error": "Debate execution timed out"},
                ),
            )
            return {
                "success": False,
                "action": "start_debate",
                "debate_node_id": debate_node.id,
                "status": "timeout",
                "message": "Debate execution timed out",
            }
        except ImportError as e:
            logger.warning("Debate modules not available: %s", e)
            debate_node.data["status"] = "error"
            debate_node.data["error"] = "Debate modules not available"
            return {
                "success": False,
                "action": "start_debate",
                "debate_node_id": debate_node.id,
                "error": "Debate modules not available",
            }
        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Debate execution failed: %s", e)
            debate_node.data["status"] = "error"
            debate_node.data["error"] = "Debate execution failed"
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.ERROR,
                    canvas_id=canvas.id,
                    node_id=debate_node.id,
                    data={"error": "Debate execution failed"},
                ),
            )
            return {
                "success": False,
                "action": "start_debate",
                "debate_node_id": debate_node.id,
                "error": "Debate execution failed",
            }

    async def _get_debate_agents(self, agent_config: list[str] | None = None):
        """Get agents for debate, using defaults if not specified."""
        try:
            from aragora.agents.registry import AgentRegistry

            if agent_config:
                agents = []
                for name in agent_config:
                    if AgentRegistry.is_registered(name):
                        agent = AgentRegistry.create(name)
                        if agent:
                            agents.append(agent)
                return agents

            # Default agents
            default_agents = ["claude", "gpt4"]
            agents = []
            for name in default_agents:
                if AgentRegistry.is_registered(name):
                    agent = AgentRegistry.create(name)
                    if agent:
                        agents.append(agent)

            if not agents:
                # Fallback to any available agent
                available = AgentRegistry.get_registered_types()
                if available:
                    agent = AgentRegistry.create(available[0])
                    if agent:
                        agents = [agent]

            return agents
        except ImportError:
            return []

    async def _handle_run_workflow(
        self,
        canvas: Canvas,
        params: dict[str, Any],
        user_id: str | None,
    ) -> dict[str, Any]:
        """Handle running a workflow from the canvas."""
        workflow_id = params.get("workflow_id")
        workflow_definition = params.get("definition")

        if not workflow_id and not workflow_definition:
            return {"success": False, "error": "workflow_id or definition is required"}

        # Create workflow node
        workflow_node = canvas.add_node(
            node_type=CanvasNodeType.WORKFLOW,
            position=Position(params.get("x", 100), params.get("y", 100)),
            label=f"Workflow: {workflow_id or 'custom'}",
            data={"workflow_id": workflow_id, "status": "pending"},
        )

        # Actually run the workflow
        try:
            from aragora.workflow.engine import WorkflowEngine
            from aragora.workflow.models import WorkflowDefinition

            # Update status
            workflow_node.data["status"] = "running"
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.NODE_UPDATE,
                    canvas_id=canvas.id,
                    node_id=workflow_node.id,
                    data={"status": "running"},
                ),
            )

            # Load or create workflow definition
            if workflow_definition:
                definition = WorkflowDefinition(**workflow_definition)
            elif workflow_id:
                # Try to load from templates
                definition = await self._load_workflow_definition(workflow_id)
                if not definition:
                    workflow_node.data["status"] = "error"
                    return {
                        "success": False,
                        "error": f"Workflow '{workflow_id}' not found",
                    }
            else:
                return {"success": False, "error": "No workflow definition provided"}

            # Execute workflow
            engine = WorkflowEngine()
            inputs = params.get("inputs", {})
            result = await engine.execute(definition, inputs, workflow_id or "canvas-workflow")

            # Update node with results
            workflow_node.data["status"] = "completed"
            workflow_node.data["result"] = {
                "success": getattr(result, "success", True),
                "outputs": getattr(result, "outputs", {}),
            }

            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.NODE_UPDATE,
                    canvas_id=canvas.id,
                    node_id=workflow_node.id,
                    data=workflow_node.data,
                ),
            )

            return {
                "success": True,
                "action": "run_workflow",
                "workflow_node_id": workflow_node.id,
                "result": workflow_node.data["result"],
            }

        except ImportError as e:
            logger.warning("Workflow modules not available: %s", e)
            workflow_node.data["status"] = "pending"
            workflow_node.data["execution_note"] = "Workflow modules not available"
            # Return success for node creation, but indicate execution wasn't possible
            return {
                "success": True,
                "action": "run_workflow",
                "workflow_node_id": workflow_node.id,
                "executed": False,
                "note": "Workflow modules not available - node created but not executed",
            }
        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Workflow execution failed: %s", e)
            workflow_node.data["status"] = "error"
            workflow_node.data["error"] = "Workflow execution failed"
            return {
                "success": False,
                "action": "run_workflow",
                "workflow_node_id": workflow_node.id,
                "error": "Workflow execution failed",
            }

    async def _load_workflow_definition(self, workflow_id: str):
        """Load a workflow definition by ID."""
        try:
            from aragora.workflow.templates import get_template

            template = get_template(workflow_id)
            return template  # get_template already returns a dict definition
        except ImportError:
            return None

    async def _handle_query_knowledge(
        self,
        canvas: Canvas,
        params: dict[str, Any],
        user_id: str | None,
    ) -> dict[str, Any]:
        """Handle querying knowledge from the canvas."""
        query = params.get("query", "")
        if not query:
            return {"success": False, "error": "Query is required"}

        # Create knowledge node
        knowledge_node = canvas.add_node(
            node_type=CanvasNodeType.KNOWLEDGE,
            position=Position(params.get("x", 100), params.get("y", 100)),
            label=f"Query: {query[:30]}..." if len(query) > 30 else f"Query: {query}",
            data={"query": query, "status": "pending"},
        )

        # Actually query knowledge
        try:
            # Update status
            knowledge_node.data["status"] = "searching"
            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.NODE_UPDATE,
                    canvas_id=canvas.id,
                    node_id=knowledge_node.id,
                    data={"status": "searching"},
                ),
            )

            # Try to query knowledge mound
            results = await self._query_knowledge_mound(
                query,
                limit=params.get("limit", 10),
                min_confidence=params.get("min_confidence", 0.0),
            )

            # Update node with results
            knowledge_node.data["status"] = "completed"
            knowledge_node.data["results"] = results
            knowledge_node.data["result_count"] = len(results)

            await self._broadcast(
                canvas.id,
                CanvasEvent(
                    event_type=CanvasEventType.NODE_UPDATE,
                    canvas_id=canvas.id,
                    node_id=knowledge_node.id,
                    data=knowledge_node.data,
                ),
            )

            return {
                "success": True,
                "action": "query_knowledge",
                "knowledge_node_id": knowledge_node.id,
                "results": results,
                "count": len(results),
            }

        except ImportError as e:
            logger.warning("Knowledge modules not available: %s", e)
            knowledge_node.data["status"] = "pending"
            knowledge_node.data["execution_note"] = "Knowledge modules not available"
            # Return success for node creation, but indicate query wasn't executed
            return {
                "success": True,
                "action": "query_knowledge",
                "knowledge_node_id": knowledge_node.id,
                "results": [],
                "count": 0,
                "executed": False,
                "note": "Knowledge modules not available - node created but not queried",
            }
        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Knowledge query failed: %s", e)
            knowledge_node.data["status"] = "error"
            knowledge_node.data["error"] = "Knowledge query failed"
            return {
                "success": False,
                "action": "query_knowledge",
                "knowledge_node_id": knowledge_node.id,
                "error": "Knowledge query failed",
            }

    async def _query_knowledge_mound(
        self,
        query: str,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Query the knowledge mound for relevant information."""
        try:
            from aragora.knowledge.mound.facade import KnowledgeMound

            # KnowledgeMound facade is instantiable despite abstract base methods
            mound = KnowledgeMound()  # type: ignore[abstract]
            results = await mound.query(query, limit=limit)

            # Format results
            formatted = []
            for result in results.items:
                confidence = getattr(result, "confidence", 0.0)
                if confidence >= min_confidence:
                    formatted.append(
                        {
                            "id": getattr(result, "id", str(uuid.uuid4())),
                            "content": getattr(result, "content", str(result)),
                            "confidence": confidence,
                            "source": getattr(result, "source", "knowledge_mound"),
                        }
                    )

            return formatted
        except ImportError:
            # KnowledgeMound not available
            return []
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            # If primary knowledge mound fails, return empty results
            logger.debug("Knowledge mound query failed: %s: %s", type(e).__name__, e)
            return []

    # =========================================================================
    # Subscription Management
    # =========================================================================

    async def subscribe(
        self,
        canvas_id: str,
        callback: Callable[[CanvasEvent], Coroutine[Any, Any, None]],
    ) -> bool:
        """Subscribe to canvas events."""
        if canvas_id not in self._subscribers:
            self._subscribers[canvas_id] = set()

        self._subscribers[canvas_id].add(callback)
        logger.debug("Subscriber added to canvas %s", canvas_id)
        return True

    async def unsubscribe(
        self,
        canvas_id: str,
        callback: Callable[[CanvasEvent], Coroutine[Any, Any, None]],
    ) -> bool:
        """Unsubscribe from canvas events."""
        if canvas_id in self._subscribers:
            self._subscribers[canvas_id].discard(callback)
            logger.debug("Subscriber removed from canvas %s", canvas_id)
            return True
        return False

    async def _broadcast(self, canvas_id: str, event: CanvasEvent) -> None:
        """Broadcast an event to all subscribers."""
        subscribers = self._subscribers.get(canvas_id, set())
        if not subscribers:
            return

        # Send to all subscribers concurrently
        tasks = [callback(event) for callback in subscribers]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Error broadcasting event: %s", result)

    # =========================================================================
    # History Management
    # =========================================================================

    def _add_to_history(self, canvas_id: str, event: CanvasEvent) -> None:
        """Add an event to the history for undo support."""
        if canvas_id not in self._history:
            self._history[canvas_id] = []

        self._history[canvas_id].append(event)

        # Trim history if too long
        if len(self._history[canvas_id]) > self._max_history:
            self._history[canvas_id] = self._history[canvas_id][-self._max_history :]

    async def get_history(
        self,
        canvas_id: str,
        limit: int = 50,
    ) -> list[CanvasEvent]:
        """Get recent history for a canvas."""
        history = self._history.get(canvas_id, [])
        return history[-limit:] if limit else history

    # =========================================================================
    # State Sync
    # =========================================================================

    async def get_state(self, canvas_id: str) -> dict[str, Any] | None:
        """Get the full state of a canvas for sync."""
        canvas = self._canvases.get(canvas_id)
        if not canvas:
            return None

        return {
            "canvas": canvas.to_dict(),
            "selections": {
                user_id: list(nodes)
                for user_id, nodes in self._user_selections.get(canvas_id, {}).items()
            },
        }

    async def sync_state(
        self,
        canvas_id: str,
        user_id: str | None = None,
    ) -> None:
        """Broadcast current state to all subscribers."""
        state = await self.get_state(canvas_id)
        if not state:
            return

        event = CanvasEvent(
            event_type=CanvasEventType.STATE,
            canvas_id=canvas_id,
            user_id=user_id,
            data=state,
        )
        await self._broadcast(canvas_id, event)


# Global manager instance
_manager: CanvasStateManager | None = None


def get_canvas_manager() -> CanvasStateManager:
    """Get or create the global canvas state manager."""
    global _manager
    if _manager is None:
        _manager = CanvasStateManager()
    return _manager


__all__ = [
    "CanvasStateManager",
    "get_canvas_manager",
]
