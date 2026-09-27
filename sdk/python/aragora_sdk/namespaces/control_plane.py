"""
Control Plane Namespace API

Provides methods for enterprise control plane operations:
- Agent registry and management
- Task scheduling and management
- Health monitoring
- Policy violations
- Deliberation management
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class ControlPlaneAPI:
    """Synchronous Control Plane API."""

    def __init__(self, client: AragoraClient):
        self._client = client

    # =========================================================================
    # Agents
    # =========================================================================

    def list_agents(self) -> dict[str, Any]:
        """List registered agents."""
        return self._client.request("GET", "/api/control-plane/agents")

    def register_agent(self, **kwargs: Any) -> dict[str, Any]:
        """Register an agent."""
        return self._client.request("POST", "/api/control-plane/agents", json=kwargs)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get an agent by ID."""
        return self._client.request("GET", f"/api/control-plane/agents/{agent_id}")

    def deregister_agent(self, agent_id: str) -> dict[str, Any]:
        """Deregister an agent."""
        return self._client.request("DELETE", f"/api/control-plane/agents/{agent_id}")

    def heartbeat(self, agent_id: str) -> dict[str, Any]:
        """Send agent heartbeat."""
        return self._client.request("POST", f"/api/control-plane/agents/{agent_id}/heartbeat")

    # =========================================================================
    # Health
    # =========================================================================

    def get_health(self) -> dict[str, Any]:
        """Get control plane health."""
        return self._client.request("GET", "/api/control-plane/health")

    def get_health_detailed(self) -> dict[str, Any]:
        """Get detailed health information."""
        return self._client.request("GET", "/api/control-plane/health/detailed")

    def get_agent_health(self, agent_id: str) -> dict[str, Any]:
        """Get health of a specific agent."""
        return self._client.request("GET", f"/api/control-plane/health/{agent_id}")

    # =========================================================================
    # Tasks
    # =========================================================================

    def create_task(self, **kwargs: Any) -> dict[str, Any]:
        """Create a task."""
        return self._client.request("POST", "/api/control-plane/tasks", json=kwargs)

    def claim_task(self, **kwargs: Any) -> dict[str, Any]:
        """Claim a task."""
        return self._client.request("POST", "/api/control-plane/tasks/claim", json=kwargs)

    def get_task_history(self) -> dict[str, Any]:
        """Get task history."""
        return self._client.request("GET", "/api/control-plane/tasks/history")

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task by ID."""
        return self._client.request("GET", f"/api/control-plane/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel a task."""
        return self._client.request("POST", f"/api/control-plane/tasks/{task_id}/cancel")

    def complete_task(self, task_id: str) -> dict[str, Any]:
        """Complete a task."""
        return self._client.request("POST", f"/api/control-plane/tasks/{task_id}/complete")

    def fail_task(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        """Mark a task as failed."""
        return self._client.request("POST", f"/api/control-plane/tasks/{task_id}/fail", json=kwargs)

    # =========================================================================
    # Metrics & Stats
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """Get control plane metrics."""
        return self._client.request("GET", "/api/control-plane/metrics")

    def get_stats(self) -> dict[str, Any]:
        """Get control plane statistics."""
        return self._client.request("GET", "/api/control-plane/stats")

    def get_breakers(self) -> dict[str, Any]:
        """Get circuit breaker status."""
        return self._client.request("GET", "/api/control-plane/breakers")

    # =========================================================================
    # Queue
    # =========================================================================

    def get_queue(self) -> dict[str, Any]:
        """Get task queue."""
        return self._client.request("GET", "/api/control-plane/queue")

    def get_queue_metrics(self) -> dict[str, Any]:
        """Get queue metrics."""
        return self._client.request("GET", "/api/control-plane/queue/metrics")

    # =========================================================================
    # Audit
    # =========================================================================

    def get_audit(self) -> dict[str, Any]:
        """Get control plane audit log."""
        return self._client.request("GET", "/api/control-plane/audit")

    def get_audit_stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        return self._client.request("GET", "/api/control-plane/audit/stats")

    def verify_audit(self) -> dict[str, Any]:
        """Verify audit integrity."""
        return self._client.request("GET", "/api/control-plane/audit/verify")

    # =========================================================================
    # Policy Violations
    # =========================================================================

    def list_violations(self) -> dict[str, Any]:
        """List policy violations."""
        return self._client.request("GET", "/api/control-plane/policies/violations")

    def get_violations_stats(self) -> dict[str, Any]:
        """Get policy violations statistics."""
        return self._client.request("GET", "/api/control-plane/policies/violations/stats")

    def get_violation(self, violation_id: str) -> dict[str, Any]:
        """Get a policy violation by ID."""
        return self._client.request("GET", f"/api/control-plane/policies/violations/{violation_id}")

    def update_violation(self, violation_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update a policy violation."""
        return self._client.request(
            "PATCH", f"/api/control-plane/policies/violations/{violation_id}", json=kwargs
        )

    # =========================================================================
    # Deliberations
    # =========================================================================

    def create_deliberation(self, **kwargs: Any) -> dict[str, Any]:
        """Create a deliberation."""
        return self._client.request("POST", "/api/control-plane/deliberations", json=kwargs)

    def get_deliberation(self, request_id: str) -> dict[str, Any]:
        """Get a deliberation."""
        return self._client.request("GET", f"/api/control-plane/deliberations/{request_id}")

    def get_deliberation_status(self, request_id: str) -> dict[str, Any]:
        """Get deliberation status."""
        return self._client.request("GET", f"/api/control-plane/deliberations/{request_id}/status")

    # =========================================================================
    # Notifications
    # =========================================================================

    def list_notifications(self) -> dict[str, Any]:
        """List control plane notifications."""
        return self._client.request("GET", "/api/control-plane/notifications")

    def get_notification_stats(self) -> dict[str, Any]:
        """Get notification statistics."""
        return self._client.request("GET", "/api/control-plane/notifications/stats")

    # =========================================================================
    # Agent Metrics / Pause / Resume
    # =========================================================================

    def get_agent_metrics(self, agent_id: str) -> dict[str, Any]:
        """Get metrics for a specific agent."""
        return self._client.request("GET", f"/api/control-plane/agents/{agent_id}/metrics")

    def pause_agent(self, agent_id: str) -> dict[str, Any]:
        """Pause an agent."""
        return self._client.request("POST", f"/api/control-plane/agents/{agent_id}/pause")

    def resume_agent(self, agent_id: str) -> dict[str, Any]:
        """Resume a paused agent."""
        return self._client.request("POST", f"/api/control-plane/agents/{agent_id}/resume")

    # =========================================================================
    # Audit Logs
    # =========================================================================

    def get_audit_logs(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get control plane audit logs."""
        return self._client.request(
            "GET",
            "/api/control-plane/audit-logs",
            params={"limit": limit, "offset": offset},
        )

    def get_audit_log(self, log_id: str) -> dict[str, Any]:
        """Get a specific audit log by ID."""
        return self._client.request("GET", f"/api/control-plane/audit-logs/{log_id}")

    # =========================================================================
    # Deliberation Transcript
    # =========================================================================

    def get_deliberation_transcript(self, request_id: str) -> dict[str, Any]:
        """
        Get the full transcript of a deliberation.

        Args:
            request_id: Deliberation request identifier.

        Returns:
            Dict with full deliberation transcript including all rounds.
        """
        return self._client.request(
            "GET", f"/api/control-plane/deliberations/{request_id}/transcript"
        )

    # =========================================================================
    # System & Task Metrics
    # =========================================================================

    def get_system_metrics(self) -> dict[str, Any]:
        """Get system-wide metrics (CPU, memory, throughput)."""
        return self._client.request("GET", "/api/control-plane/metrics/system")

    def get_task_metrics(self) -> dict[str, Any]:
        """Get task-level metrics (completion rate, avg duration)."""
        return self._client.request("GET", "/api/control-plane/metrics/tasks")

    def get_agent_metrics_by_id(self, agent_id: str) -> dict[str, Any]:
        """Get metrics for a specific agent by agent ID."""
        return self._client.request("GET", f"/api/control-plane/metrics/agents/{agent_id}")

    # =========================================================================
    # Policies
    # =========================================================================

    def list_policies(self) -> dict[str, Any]:
        """List control plane policies."""
        return self._client.request("GET", "/api/control-plane/policies")

    def create_policy(self, **kwargs: Any) -> dict[str, Any]:
        """Create a control plane policy."""
        return self._client.request("POST", "/api/control-plane/policies", json=kwargs)

    # =========================================================================
    # Queue Prioritization
    # =========================================================================

    def prioritize_queue(self, **kwargs: Any) -> dict[str, Any]:
        """Reprioritize tasks in the control plane queue."""
        return self._client.request("POST", "/api/control-plane/queue/prioritize", json=kwargs)

    # =========================================================================
    # Schedules
    # =========================================================================

    def list_schedules(self) -> dict[str, Any]:
        """List control plane task schedules."""
        return self._client.request("GET", "/api/control-plane/schedules")

    def create_schedule(self, **kwargs: Any) -> dict[str, Any]:
        """Create a control plane task schedule."""
        return self._client.request("POST", "/api/control-plane/schedules", json=kwargs)

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Get a specific schedule by ID."""
        return self._client.request("GET", f"/api/control-plane/schedules/{schedule_id}")

    def update_schedule(self, schedule_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update a control plane task schedule."""
        return self._client.request(
            "PUT", f"/api/control-plane/schedules/{schedule_id}", json=kwargs
        )

    def delete_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Delete a control plane task schedule."""
        return self._client.request("DELETE", f"/api/control-plane/schedules/{schedule_id}")

    # =========================================================================
    # Stream
    # =========================================================================

    def get_stream_info(self) -> dict[str, Any]:
        """Get SSE/WebSocket stream info for control plane events."""
        return self._client.request("GET", "/api/control-plane/stream")


class AsyncControlPlaneAPI:
    """Asynchronous Control Plane API."""

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def list_agents(self) -> dict[str, Any]:
        """List registered agents."""
        return await self._client.request("GET", "/api/control-plane/agents")

    async def register_agent(self, **kwargs: Any) -> dict[str, Any]:
        """Register an agent."""
        return await self._client.request("POST", "/api/control-plane/agents", json=kwargs)

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get an agent by ID."""
        return await self._client.request("GET", f"/api/control-plane/agents/{agent_id}")

    async def deregister_agent(self, agent_id: str) -> dict[str, Any]:
        """Deregister an agent."""
        return await self._client.request("DELETE", f"/api/control-plane/agents/{agent_id}")

    async def heartbeat(self, agent_id: str) -> dict[str, Any]:
        """Send agent heartbeat."""
        return await self._client.request("POST", f"/api/control-plane/agents/{agent_id}/heartbeat")

    async def get_health(self) -> dict[str, Any]:
        """Get control plane health."""
        return await self._client.request("GET", "/api/control-plane/health")

    async def get_health_detailed(self) -> dict[str, Any]:
        """Get detailed health information."""
        return await self._client.request("GET", "/api/control-plane/health/detailed")

    async def get_agent_health(self, agent_id: str) -> dict[str, Any]:
        """Get health of a specific agent."""
        return await self._client.request("GET", f"/api/control-plane/health/{agent_id}")

    async def create_task(self, **kwargs: Any) -> dict[str, Any]:
        """Create a task."""
        return await self._client.request("POST", "/api/control-plane/tasks", json=kwargs)

    async def claim_task(self, **kwargs: Any) -> dict[str, Any]:
        """Claim a task."""
        return await self._client.request("POST", "/api/control-plane/tasks/claim", json=kwargs)

    async def get_task_history(self) -> dict[str, Any]:
        """Get task history."""
        return await self._client.request("GET", "/api/control-plane/tasks/history")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task by ID."""
        return await self._client.request("GET", f"/api/control-plane/tasks/{task_id}")

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel a task."""
        return await self._client.request("POST", f"/api/control-plane/tasks/{task_id}/cancel")

    async def complete_task(self, task_id: str) -> dict[str, Any]:
        """Complete a task."""
        return await self._client.request("POST", f"/api/control-plane/tasks/{task_id}/complete")

    async def fail_task(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        """Mark a task as failed."""
        return await self._client.request(
            "POST", f"/api/control-plane/tasks/{task_id}/fail", json=kwargs
        )

    async def get_metrics(self) -> dict[str, Any]:
        """Get control plane metrics."""
        return await self._client.request("GET", "/api/control-plane/metrics")

    async def get_stats(self) -> dict[str, Any]:
        """Get control plane statistics."""
        return await self._client.request("GET", "/api/control-plane/stats")

    async def get_breakers(self) -> dict[str, Any]:
        """Get circuit breaker status."""
        return await self._client.request("GET", "/api/control-plane/breakers")

    async def get_queue(self) -> dict[str, Any]:
        """Get task queue."""
        return await self._client.request("GET", "/api/control-plane/queue")

    async def get_queue_metrics(self) -> dict[str, Any]:
        """Get queue metrics."""
        return await self._client.request("GET", "/api/control-plane/queue/metrics")

    async def get_audit(self) -> dict[str, Any]:
        """Get control plane audit log."""
        return await self._client.request("GET", "/api/control-plane/audit")

    async def get_audit_stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        return await self._client.request("GET", "/api/control-plane/audit/stats")

    async def verify_audit(self) -> dict[str, Any]:
        """Verify audit integrity."""
        return await self._client.request("GET", "/api/control-plane/audit/verify")

    async def list_violations(self) -> dict[str, Any]:
        """List policy violations."""
        return await self._client.request("GET", "/api/control-plane/policies/violations")

    async def get_violations_stats(self) -> dict[str, Any]:
        """Get policy violations statistics."""
        return await self._client.request("GET", "/api/control-plane/policies/violations/stats")

    async def get_violation(self, violation_id: str) -> dict[str, Any]:
        """Get a policy violation by ID."""
        return await self._client.request(
            "GET", f"/api/control-plane/policies/violations/{violation_id}"
        )

    async def update_violation(self, violation_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update a policy violation."""
        return await self._client.request(
            "PATCH", f"/api/control-plane/policies/violations/{violation_id}", json=kwargs
        )

    async def create_deliberation(self, **kwargs: Any) -> dict[str, Any]:
        """Create a deliberation."""
        return await self._client.request("POST", "/api/control-plane/deliberations", json=kwargs)

    async def get_deliberation(self, request_id: str) -> dict[str, Any]:
        """Get a deliberation."""
        return await self._client.request("GET", f"/api/control-plane/deliberations/{request_id}")

    async def get_deliberation_status(self, request_id: str) -> dict[str, Any]:
        """Get deliberation status."""
        return await self._client.request(
            "GET", f"/api/control-plane/deliberations/{request_id}/status"
        )

    async def list_notifications(self) -> dict[str, Any]:
        """List control plane notifications."""
        return await self._client.request("GET", "/api/control-plane/notifications")

    async def get_notification_stats(self) -> dict[str, Any]:
        """Get notification statistics."""
        return await self._client.request("GET", "/api/control-plane/notifications/stats")

    # Agent Metrics / Pause / Resume
    async def get_agent_metrics(self, agent_id: str) -> dict[str, Any]:
        """Get metrics for a specific agent."""
        return await self._client.request("GET", f"/api/control-plane/agents/{agent_id}/metrics")

    async def pause_agent(self, agent_id: str) -> dict[str, Any]:
        """Pause an agent."""
        return await self._client.request("POST", f"/api/control-plane/agents/{agent_id}/pause")

    async def resume_agent(self, agent_id: str) -> dict[str, Any]:
        """Resume a paused agent."""
        return await self._client.request("POST", f"/api/control-plane/agents/{agent_id}/resume")

    # Audit Logs
    async def get_audit_logs(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get control plane audit logs."""
        return await self._client.request(
            "GET",
            "/api/control-plane/audit-logs",
            params={"limit": limit, "offset": offset},
        )

    async def get_audit_log(self, log_id: str) -> dict[str, Any]:
        """Get a specific audit log by ID."""
        return await self._client.request("GET", f"/api/control-plane/audit-logs/{log_id}")

    # Deliberation Transcript
    async def get_deliberation_transcript(self, request_id: str) -> dict[str, Any]:
        """Get the full transcript of a deliberation."""
        return await self._client.request(
            "GET", f"/api/control-plane/deliberations/{request_id}/transcript"
        )

    # System & Task Metrics
    async def get_system_metrics(self) -> dict[str, Any]:
        """Get system-wide metrics."""
        return await self._client.request("GET", "/api/control-plane/metrics/system")

    async def get_task_metrics(self) -> dict[str, Any]:
        """Get task-level metrics."""
        return await self._client.request("GET", "/api/control-plane/metrics/tasks")

    async def get_agent_metrics_by_id(self, agent_id: str) -> dict[str, Any]:
        """Get metrics for a specific agent by agent ID."""
        return await self._client.request("GET", f"/api/control-plane/metrics/agents/{agent_id}")

    # Policies
    async def list_policies(self) -> dict[str, Any]:
        """List control plane policies."""
        return await self._client.request("GET", "/api/control-plane/policies")

    async def create_policy(self, **kwargs: Any) -> dict[str, Any]:
        """Create a control plane policy."""
        return await self._client.request("POST", "/api/control-plane/policies", json=kwargs)

    # Queue Prioritization
    async def prioritize_queue(self, **kwargs: Any) -> dict[str, Any]:
        """Reprioritize tasks in the control plane queue."""
        return await self._client.request(
            "POST", "/api/control-plane/queue/prioritize", json=kwargs
        )

    # Schedules
    async def list_schedules(self) -> dict[str, Any]:
        """List control plane task schedules."""
        return await self._client.request("GET", "/api/control-plane/schedules")

    async def create_schedule(self, **kwargs: Any) -> dict[str, Any]:
        """Create a control plane task schedule."""
        return await self._client.request("POST", "/api/control-plane/schedules", json=kwargs)

    async def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Get a specific schedule by ID."""
        return await self._client.request("GET", f"/api/control-plane/schedules/{schedule_id}")

    async def update_schedule(self, schedule_id: str, **kwargs: Any) -> dict[str, Any]:
        """Update a control plane task schedule."""
        return await self._client.request(
            "PUT", f"/api/control-plane/schedules/{schedule_id}", json=kwargs
        )

    async def delete_schedule(self, schedule_id: str) -> dict[str, Any]:
        """Delete a control plane task schedule."""
        return await self._client.request("DELETE", f"/api/control-plane/schedules/{schedule_id}")

    # Stream
    async def get_stream_info(self) -> dict[str, Any]:
        """Get SSE/WebSocket stream info for control plane events."""
        return await self._client.request("GET", "/api/control-plane/stream")
