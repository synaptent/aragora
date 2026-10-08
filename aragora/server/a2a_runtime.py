"""
A2A Application Server.

Server for exposing Aragora agents via the A2A protocol.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from collections.abc import AsyncIterator, Callable, Coroutine

if TYPE_CHECKING:
    from aragora.agents.base import AgentType

from aragora.protocols.a2a.types import (
    AgentCard,
    AgentCapability,
    TaskRequest,
    TaskResult,
    TaskStatus,
    ARAGORA_AGENT_CARDS,
)

logger = logging.getLogger(__name__)


class TaskHandler:
    """Handler for a specific task type."""

    def __init__(
        self,
        capability: AgentCapability,
        handler: Callable[[TaskRequest], Coroutine[Any, Any, TaskResult]],
        stream_handler: Callable[[TaskRequest], AsyncIterator[dict[str, Any]]] | None = None,
    ):
        self.capability = capability
        self.handler = handler
        self.stream_handler = stream_handler


class A2AServer:
    """
    Server for exposing Aragora agents via A2A protocol.

    Provides:
    - Agent card advertisement
    - Task handling with sync and stream modes
    - Task lifecycle management
    - Built-in handlers for Aragora capabilities
    """

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104 - A2A server binds all interfaces by default
        port: int = 8766,
        max_concurrent_tasks: int = 10,
    ):
        """
        Initialize A2A server.

        Args:
            host: Server host
            port: Server port
            max_concurrent_tasks: Maximum concurrent tasks
        """
        self._host = host
        self._port = port
        self._max_concurrent = max_concurrent_tasks

        # Registered agents and handlers
        self._agents: dict[str, AgentCard] = {}
        self._handlers: dict[AgentCapability, TaskHandler] = {}

        # Active tasks
        self._tasks: dict[str, TaskResult] = {}
        self._task_lock = asyncio.Lock()

        # Register built-in Aragora agents
        self._register_aragora_agents()

    def _register_aragora_agents(self) -> None:
        """Register built-in Aragora agent cards."""
        for name, card in ARAGORA_AGENT_CARDS.items():
            self._agents[card.name] = card

        # Register handlers for capabilities
        self._handlers[AgentCapability.DEBATE] = TaskHandler(
            capability=AgentCapability.DEBATE,
            handler=self._handle_debate,
            stream_handler=self._stream_debate,
        )

        self._handlers[AgentCapability.AUDIT] = TaskHandler(
            capability=AgentCapability.AUDIT,
            handler=self._handle_audit,
        )

        self._handlers[AgentCapability.CRITIQUE] = TaskHandler(
            capability=AgentCapability.CRITIQUE,
            handler=self._handle_gauntlet,
        )

        self._handlers[AgentCapability.RESEARCH] = TaskHandler(
            capability=AgentCapability.RESEARCH,
            handler=self._handle_research,
        )

    def register_agent(self, agent: AgentCard) -> None:
        """
        Register an agent with the server.

        Args:
            agent: Agent card to register
        """
        self._agents[agent.name] = agent
        logger.info("Registered agent: %s", agent.name)

    def register_handler(
        self,
        capability: AgentCapability,
        handler: Callable[[TaskRequest], Coroutine[Any, Any, TaskResult]],
        stream_handler: Callable[[TaskRequest], AsyncIterator[dict[str, Any]]] | None = None,
    ) -> None:
        """
        Register a task handler for a capability.

        Args:
            capability: Capability to handle
            handler: Sync handler function
            stream_handler: Optional stream handler
        """
        self._handlers[capability] = TaskHandler(
            capability=capability,
            handler=handler,
            stream_handler=stream_handler,
        )
        logger.info("Registered handler for capability: %s", capability.value)

    def list_agents(self) -> list[AgentCard]:
        """List all registered agents."""
        return list(self._agents.values())

    def get_agent(self, name: str) -> AgentCard | None:
        """Get an agent by name."""
        return self._agents.get(name)

    async def handle_task(self, request: TaskRequest) -> TaskResult:
        """
        Handle a task request.

        Args:
            request: Task request to handle

        Returns:
            Task result
        """
        started_at = datetime.now()

        # Find appropriate handler
        handler = None
        if request.capability:
            handler = self._handlers.get(request.capability)
        else:
            # Try to find any matching handler
            for cap, h in self._handlers.items():
                handler = h
                break

        if not handler:
            return TaskResult(
                task_id=request.task_id,
                agent_name="aragora",
                status=TaskStatus.FAILED,
                error_message=f"No handler for capability: {request.capability}",
                started_at=started_at,
                completed_at=datetime.now(),
            )

        # Track task
        async with self._task_lock:
            self._tasks[request.task_id] = TaskResult(
                task_id=request.task_id,
                agent_name="aragora",
                status=TaskStatus.RUNNING,
                started_at=started_at,
            )

        try:
            # Execute handler
            result = await handler.handler(request)
            result.started_at = started_at
            result.completed_at = datetime.now()

            # Update task record
            async with self._task_lock:
                self._tasks[request.task_id] = result

            return result

        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Task %s failed: %s", request.task_id, e, exc_info=True)

            result = TaskResult(
                task_id=request.task_id,
                agent_name="aragora",
                status=TaskStatus.FAILED,
                error_message=str(e),
                started_at=started_at,
                completed_at=datetime.now(),
            )

            async with self._task_lock:
                self._tasks[request.task_id] = result

            return result

    async def stream_task(
        self,
        request: TaskRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Handle a streaming task request.

        Args:
            request: Task request to handle

        Yields:
            Stream events
        """
        started_at = datetime.now()

        # Find appropriate handler
        handler = None
        if request.capability:
            handler = self._handlers.get(request.capability)

        if not handler or not handler.stream_handler:
            yield {
                "type": "error",
                "task_id": request.task_id,
                "error": f"No stream handler for capability: {request.capability}",
            }
            return

        # Track task
        async with self._task_lock:
            self._tasks[request.task_id] = TaskResult(
                task_id=request.task_id,
                agent_name="aragora",
                status=TaskStatus.RUNNING,
                started_at=started_at,
            )

        try:
            # Start event
            yield {
                "type": "start",
                "task_id": request.task_id,
                "timestamp": started_at.isoformat(),
            }

            # Stream from handler
            async for event in handler.stream_handler(request):
                yield event

            # Complete event
            yield {
                "type": "complete",
                "task_id": request.task_id,
                "timestamp": datetime.now().isoformat(),
            }

        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Stream task %s failed: %s", request.task_id, e, exc_info=True)
            yield {
                "type": "error",
                "task_id": request.task_id,
                "error": str(e),
            }

    def get_task_status(self, task_id: str) -> TaskResult | None:
        """Get the status of a task."""
        return self._tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task.

        Args:
            task_id: Task ID to cancel

        Returns:
            True if cancellation was successful
        """
        async with self._task_lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = datetime.now()
                    return True
        return False

    # Built-in Aragora handlers

    async def _handle_debate(self, request: TaskRequest) -> TaskResult:
        """Handle debate capability requests."""
        from aragora.agents.base import create_agent
        from aragora.config import DEFAULT_AGENT_LIST, DEFAULT_CONSENSUS, DEFAULT_ROUNDS
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena, DebateProtocol

        # Parse context for additional parameters
        rounds = DEFAULT_ROUNDS
        agents_str = ",".join(DEFAULT_AGENT_LIST)

        for ctx in request.context:
            if ctx.metadata.get("rounds"):
                rounds = int(ctx.metadata["rounds"])
            if ctx.metadata.get("agents"):
                agents_str = ctx.metadata["agents"]

        # Create agents
        agent_names = [a.strip() for a in agents_str.split(",")]
        agents = []
        roles = ["proposer", "critic", "synthesizer"]

        for i, agent_name in enumerate(agent_names):
            role = roles[i] if i < len(roles) else "critic"
            try:
                agent = create_agent(
                    model_type=cast("AgentType", agent_name),
                    name=f"{agent_name}_{role}",
                    role=role,
                )
                agents.append(agent)
            except (ImportError, ValueError, TypeError, RuntimeError) as e:
                logger.warning("Could not create agent %s: %s", agent_name, e)

        if not agents:
            return TaskResult(
                task_id=request.task_id,
                agent_name="aragora-debate-orchestrator",
                status=TaskStatus.FAILED,
                error_message="No valid agents could be created",
            )

        # Run debate
        env = Environment(task=request.instruction, max_rounds=rounds)
        consensus_type = cast(
            Literal[
                "majority",
                "unanimous",
                "judge",
                "none",
                "weighted",
                "supermajority",
                "any",
                "byzantine",
            ],
            DEFAULT_CONSENSUS,
        )
        protocol = DebateProtocol(rounds=rounds, consensus=consensus_type)
        arena = Arena(env, agents, protocol)

        result = await arena.run()

        return TaskResult(
            task_id=request.task_id,
            agent_name="aragora-debate-orchestrator",
            status=TaskStatus.COMPLETED,
            output=result.final_answer,
            structured_output={
                "consensus_reached": result.consensus_reached,
                "confidence": result.confidence,
                "rounds_used": result.rounds_used,
                "agents": [a.name for a in agents],
            },
        )

    async def _stream_debate(
        self,
        request: TaskRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream debate events."""
        # This would integrate with the debate's WebSocket streaming
        # For now, run debate and yield result
        result = await self._handle_debate(request)

        yield {
            "type": "message",
            "content": result.output,
        }

        if result.structured_output:
            yield {
                "type": "structured",
                "data": result.structured_output,
            }

    async def _handle_audit(self, request: TaskRequest) -> TaskResult:
        """Handle audit capability requests."""

        # Determine audit type from context
        audit_type = "security"
        content = request.instruction

        for ctx in request.context:
            if ctx.metadata.get("audit_type"):
                audit_type = ctx.metadata["audit_type"]
            if ctx.type == "file" or ctx.type == "text":
                content = ctx.content

        # Run audit (simplified - would use full audit infrastructure)
        try:
            from aragora.audit.audit_types.security import SecurityAuditor
            from aragora.audit.document_auditor import AuditSession

            auditor = SecurityAuditor()
            session = AuditSession(name="a2a_audit")

            # Convert content to chunk format expected by auditor
            chunks = [{"id": "chunk_0", "document_id": "a2a_doc", "content": content}]
            findings = await auditor.audit(chunks, session)

            return TaskResult(
                task_id=request.task_id,
                agent_name="aragora-audit-engine",
                status=TaskStatus.COMPLETED,
                structured_output={
                    "findings": [f.to_dict() for f in findings[:10]],
                    "finding_count": len(findings),
                    "audit_type": audit_type,
                },
            )
        except ImportError:
            return TaskResult(
                task_id=request.task_id,
                agent_name="aragora-audit-engine",
                status=TaskStatus.FAILED,
                error_message="Audit module not available",
            )

    async def _handle_gauntlet(self, request: TaskRequest) -> TaskResult:
        """Handle gauntlet/critique capability requests."""
        from aragora.gauntlet import GauntletRunner, QUICK_GAUNTLET

        content = request.instruction
        for ctx in request.context:
            if ctx.type == "text":
                content = ctx.content

        runner = GauntletRunner(QUICK_GAUNTLET)
        result = await runner.run(content)

        return TaskResult(
            task_id=request.task_id,
            agent_name="aragora-gauntlet",
            status=TaskStatus.COMPLETED,
            structured_output={
                "verdict": result.verdict.value if hasattr(result, "verdict") else "unknown",
                "risk_score": getattr(result, "risk_score", 0),
                "vulnerabilities_count": len(getattr(result, "vulnerabilities", [])),
            },
        )

    async def _handle_research(self, request: TaskRequest) -> TaskResult:
        """Handle research capability requests."""
        # Would integrate with multi-agent research workflow
        # For now, run a simple debate on the research question

        return await self._handle_debate(request)

    # HTTP API (for integration with web frameworks)

    def get_openapi_spec(self) -> dict[str, Any]:
        """Generate OpenAPI specification for the A2A server."""
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Aragora A2A Server",
                "description": "Agent-to-Agent protocol server for Aragora",
                "version": "1.0.0",
            },
            "paths": {
                "/agents": {
                    "get": {
                        "summary": "List available agents",
                        "responses": {
                            "200": {
                                "description": "List of agent cards",
                            }
                        },
                    }
                },
                "/agents/{name}": {
                    "get": {
                        "summary": "Get agent by name",
                        "parameters": [{"name": "name", "in": "path", "required": True}],
                        "responses": {
                            "200": {"description": "Agent card"},
                            "404": {"description": "Agent not found"},
                        },
                    }
                },
                "/tasks": {
                    "post": {
                        "summary": "Submit a task",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TaskRequest"}
                                }
                            }
                        },
                        "responses": {
                            "200": {"description": "Task result"},
                        },
                    }
                },
                "/tasks/{task_id}": {
                    "get": {
                        "summary": "Get task status",
                        "responses": {
                            "200": {"description": "Task result"},
                            "404": {"description": "Task not found"},
                        },
                    },
                    "delete": {
                        "summary": "Cancel task",
                        "responses": {
                            "204": {"description": "Task cancelled"},
                        },
                    },
                },
            },
        }


__all__ = [
    "A2AServer",
    "TaskHandler",
]
