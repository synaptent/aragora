"""Pipeline transitions namespace API (stage-to-stage AI transitions)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class PipelineTransitionsAPI:
    """Synchronous Pipeline Transitions API."""

    def __init__(self, client: AragoraClient):
        self._client = client

    def ideas_to_goals(
        self,
        ideas: list[dict[str, Any]],
        *,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Cluster ideas and derive goals with OKR fields.

        Args:
            ideas: List of idea dicts (each with 'label' or 'text', optional 'id').
            context: Optional context string for goal derivation.

        Returns:
            TransitionResult with nodes, edges, and provenance.
        """
        payload: dict[str, Any] = {"ideas": ideas}
        if context:
            payload["context"] = context
        return self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/ideas-to-goals",
            json=payload,
        )

    def goals_to_tasks(
        self,
        goals: list[dict[str, Any]],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Decompose goals into actionable tasks.

        Args:
            goals: List of goal dicts (each with 'id', 'label', 'metadata').
            constraints: Optional constraints dict (e.g. {'max_tasks': 10}).

        Returns:
            TransitionResult with task nodes and dependency edges.
        """
        payload: dict[str, Any] = {"goals": goals}
        if constraints:
            payload["constraints"] = constraints
        return self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/goals-to-tasks",
            json=payload,
        )

    def tasks_to_workflow(
        self,
        tasks: list[dict[str, Any]],
        *,
        execution_mode: str | None = None,
    ) -> dict[str, Any]:
        """Generate a workflow DAG from tasks.

        Args:
            tasks: List of task dicts from goals_to_tasks.
            execution_mode: 'parallel' or 'sequential'.

        Returns:
            TransitionResult with orchestration nodes and trigger edges.
        """
        payload: dict[str, Any] = {"tasks": tasks}
        if execution_mode:
            payload["execution_mode"] = execution_mode
        return self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/tasks-to-workflow",
            json=payload,
        )

    def execute(
        self,
        workflow_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute or dry-run a workflow.

        Args:
            workflow_id: Identifier for the workflow.
            nodes: Orchestration node dicts.
            edges: Edge dicts.
            dry_run: If True, return plan without executing.

        Returns:
            Execution result with execution_id and status.
        """
        return self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/execute",
            json={
                "workflow_id": workflow_id,
                "nodes": nodes,
                "edges": edges,
                "dry_run": dry_run,
            },
        )

    def get_provenance(self, node_id: str) -> dict[str, Any]:
        """Get the full provenance chain for a node.

        Args:
            node_id: The node to trace back.

        Returns:
            Dict with 'chain' list (origin first) and 'depth'.
        """
        return self._client.request(
            "GET",
            f"/api/v1/pipeline/transitions/{node_id}/provenance",
        )

    def transition(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Trigger a stage transition for a pipeline item."""
        return self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition",
            json={"target_stage": target_stage},
        )

    def get_history(self, pipeline_id: str, item_id: str) -> list[dict[str, Any]]:
        """Get transition history for a pipeline item."""
        return self._client.request(
            "GET",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transitions",
        )

    def validate(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Validate whether a transition is allowed."""
        return self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition/validate",
            json={"target_stage": target_stage},
        )

    def available(self, pipeline_id: str, item_id: str) -> dict[str, Any]:
        """Get available transitions for the current stage."""
        return self._client.request(
            "GET",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transitions/available",
        )

    def rollback(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Rollback to a previous stage."""
        return self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition/rollback",
            json={"target_stage": target_stage},
        )


class AsyncPipelineTransitionsAPI:
    """Asynchronous Pipeline Transitions API."""

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def ideas_to_goals(
        self,
        ideas: list[dict[str, Any]],
        *,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Cluster ideas and derive goals."""
        payload: dict[str, Any] = {"ideas": ideas}
        if context:
            payload["context"] = context
        return await self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/ideas-to-goals",
            json=payload,
        )

    async def goals_to_tasks(
        self,
        goals: list[dict[str, Any]],
        *,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Decompose goals into actionable tasks."""
        payload: dict[str, Any] = {"goals": goals}
        if constraints:
            payload["constraints"] = constraints
        return await self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/goals-to-tasks",
            json=payload,
        )

    async def tasks_to_workflow(
        self,
        tasks: list[dict[str, Any]],
        *,
        execution_mode: str | None = None,
    ) -> dict[str, Any]:
        """Generate a workflow DAG from tasks."""
        payload: dict[str, Any] = {"tasks": tasks}
        if execution_mode:
            payload["execution_mode"] = execution_mode
        return await self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/tasks-to-workflow",
            json=payload,
        )

    async def execute(
        self,
        workflow_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute or dry-run a workflow."""
        return await self._client.request(
            "POST",
            "/api/v1/pipeline/transitions/execute",
            json={
                "workflow_id": workflow_id,
                "nodes": nodes,
                "edges": edges,
                "dry_run": dry_run,
            },
        )

    async def get_provenance(self, node_id: str) -> dict[str, Any]:
        """Get the full provenance chain for a node."""
        return await self._client.request(
            "GET",
            f"/api/v1/pipeline/transitions/{node_id}/provenance",
        )

    async def transition(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Trigger a stage transition for a pipeline item."""
        return await self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition",
            json={"target_stage": target_stage},
        )

    async def get_history(self, pipeline_id: str, item_id: str) -> list[dict[str, Any]]:
        """Get transition history for a pipeline item."""
        return await self._client.request(
            "GET",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transitions",
        )

    async def validate(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Validate whether a transition is allowed."""
        return await self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition/validate",
            json={"target_stage": target_stage},
        )

    async def available(self, pipeline_id: str, item_id: str) -> dict[str, Any]:
        """Get available transitions for the current stage."""
        return await self._client.request(
            "GET",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transitions/available",
        )

    async def rollback(self, pipeline_id: str, item_id: str, target_stage: str) -> dict[str, Any]:
        """Rollback to a previous stage."""
        return await self._client.request(
            "POST",
            f"/api/v2/pipelines/{pipeline_id}/items/{item_id}/transition/rollback",
            json={"target_stage": target_stage},
        )
