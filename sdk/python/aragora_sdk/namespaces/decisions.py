"""
Decisions namespace for unified decision management.

Provides a high-level API for submitting decisions and retrieving results
across all decision types (debates, gauntlets, workflows).
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

DecisionType = Literal["debate", "gauntlet", "workflow", "quick"]
DecisionPriority = Literal["low", "normal", "high", "urgent"]
DecisionStatus = Literal["pending", "processing", "completed", "failed", "cancelled"]


class DecisionsAPI:
    """Synchronous decisions API."""

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def submit(
        self,
        input: str,
        decision_type: DecisionType = "debate",
        priority: DecisionPriority = "normal",
        context: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit a decision request.

        This is the unified entry point for all decision types.
        The system will route to the appropriate handler based on type.

        Args:
            input: The decision input (question, claim, task)
            decision_type: Type of decision process
            priority: Processing priority
            context: Optional context for the decision
            config: Type-specific configuration
            callback_url: Webhook URL for completion notification

        Returns:
            Decision submission result with decision_id
        """
        data: dict[str, Any] = {
            "input": input,
            "decision_type": decision_type,
            "priority": priority,
        }
        if context:
            data["context"] = context
        if config:
            data["config"] = config
        if callback_url:
            data["callback_url"] = callback_url

        return self._client._request("POST", "/api/v1/decisions", json=data)

    def get(self, decision_id: str) -> dict[str, Any]:
        """
        Get a decision by ID.

        Args:
            decision_id: Decision identifier

        Returns:
            Decision details including status and result
        """
        return self._client._request("GET", f"/api/v1/decisions/{decision_id}")

    def get_status(self, decision_id: str) -> dict[str, Any]:
        """
        Get the status of a decision.

        Lightweight endpoint for polling decision completion.

        Args:
            decision_id: Decision identifier

        Returns:
            Decision status
        """
        return self._client._request("GET", f"/api/v1/decisions/{decision_id}/status")

    def list(
        self,
        status: DecisionStatus | None = None,
        decision_type: DecisionType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List decisions with optional filtering.

        Args:
            status: Filter by status
            decision_type: Filter by decision type
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of decisions with pagination
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if decision_type:
            params["decision_type"] = decision_type

        return self._client._request("GET", "/api/v1/decisions", params=params)

    def cancel(self, decision_id: str, reason: str | None = None) -> dict[str, Any]:
        """
        Cancel a pending or processing decision.

        Only decisions in PENDING or PROCESSING status can be cancelled.

        Args:
            decision_id: Decision identifier
            reason: Cancellation reason

        Returns:
            Cancellation confirmation with status and cancelled_at timestamp

        Raises:
            HTTPError: If decision cannot be cancelled (wrong status or not found)
        """
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason

        return self._client._request(
            "POST",
            f"/api/v1/decisions/{decision_id}/cancel",
            json=data if data else None,
        )

    def retry(self, decision_id: str) -> dict[str, Any]:
        """
        Retry a failed or cancelled decision.

        Creates a new decision with the same parameters as the original.
        Only decisions in FAILED, CANCELLED, or TIMEOUT status can be retried.

        Args:
            decision_id: Decision identifier

        Returns:
            Retry result with new decision_id and result

        Raises:
            HTTPError: If decision cannot be retried (wrong status or not found)
        """
        return self._client._request("POST", f"/api/v1/decisions/{decision_id}/retry")

    def get_receipt(self, decision_id: str) -> dict[str, Any]:
        """
        Get the receipt for a completed decision.

        Retrieves the cryptographic receipt for audit and compliance.
        The receipt includes the decision signature, timestamp, and full audit trail.

        Args:
            decision_id: Decision identifier

        Returns:
            Decision receipt with signature and audit data
        """
        return self._client._request("GET", f"/api/v2/receipts/{decision_id}")

    def get_explanation(self, decision_id: str) -> dict[str, Any]:
        """
        Get the explanation for a completed decision.

        Args:
            decision_id: Decision identifier

        Returns:
            Decision explanation with factors and reasoning
        """
        return self._client._request("GET", f"/api/v1/decisions/{decision_id}/explain")

    def submit_feedback(
        self,
        decision_id: str,
        rating: int,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit feedback on a decision.

        Args:
            decision_id: Decision identifier
            rating: Rating (1-5)
            comment: Optional comment

        Returns:
            Feedback submission confirmation
        """
        data: dict[str, Any] = {
            "type": "debate_quality",
            "score": rating,
            "context": {"decision_id": decision_id},
        }
        if comment:
            data["comment"] = comment
        else:
            data["comment"] = f"Feedback for decision {decision_id}"

        return self._client._request("POST", "/api/v1/feedback/general", json=data)

    # -------------------------------------------------------------------------
    # DecisionPlan methods (gold path: debate → plan → execute → verify)
    # -------------------------------------------------------------------------

    def create_plan(
        self,
        debate_id: str,
        budget_limit_usd: float | None = None,
        approval_mode: Literal["always", "risk_based", "confidence_based", "never"] = "risk_based",
        max_auto_risk: Literal["low", "medium", "high", "critical"] = "low",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a DecisionPlan from a completed debate.

        Args:
            debate_id: ID of the completed debate
            budget_limit_usd: Optional budget cap for execution
            approval_mode: When human approval is required
            max_auto_risk: Maximum risk level for auto-approval
            metadata: Optional extra metadata

        Returns:
            Created plan details including plan_id and status
        """
        data: dict[str, Any] = {"debate_id": debate_id}
        if budget_limit_usd is not None:
            data["budget_limit_usd"] = budget_limit_usd
        if approval_mode:
            data["approval_mode"] = approval_mode
        if max_auto_risk:
            data["max_auto_risk"] = max_auto_risk
        if metadata:
            data["metadata"] = metadata

        return self._client._request("POST", "/api/v1/decisions/plans", json=data)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        """
        Get a DecisionPlan by ID.

        Args:
            plan_id: Plan identifier

        Returns:
            Plan details including status, risk assessment, and tasks
        """
        return self._client._request("GET", f"/api/v1/decisions/plans/{plan_id}")

    def list_plans(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        List DecisionPlans with optional filtering.

        Args:
            status: Filter by status (created, approved, executing, completed, etc.)
            limit: Maximum results (default 50, max 200)

        Returns:
            List of plans with count
        """
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        return self._client._request("GET", "/api/v1/decisions/plans", params=params)

    def approve_plan(
        self,
        plan_id: str,
        reason: str = "",
        conditions: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Approve a DecisionPlan for execution.

        Args:
            plan_id: Plan identifier
            reason: Optional approval reason
            conditions: Optional conditions for approval

        Returns:
            Updated plan status with approval record
        """
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason
        if conditions:
            data["conditions"] = conditions

        return self._client._request(
            "POST",
            f"/api/v1/decisions/plans/{plan_id}/approve",
            json=data if data else None,
        )

    def reject_plan(self, plan_id: str, reason: str = "") -> dict[str, Any]:
        """
        Reject a DecisionPlan.

        Args:
            plan_id: Plan identifier
            reason: Reason for rejection

        Returns:
            Updated plan status with rejection record
        """
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason

        return self._client._request(
            "POST",
            f"/api/v1/decisions/plans/{plan_id}/reject",
            json=data if data else None,
        )

    def execute_plan(self, plan_id: str) -> dict[str, Any]:
        """
        Execute an approved DecisionPlan.

        Triggers workflow execution. The plan must be in APPROVED status.

        Args:
            plan_id: Plan identifier

        Returns:
            Execution result with plan status and outcome
        """
        return self._client._request("POST", f"/api/v1/decisions/plans/{plan_id}/execute")

    def get_plan_outcome(self, plan_id: str) -> dict[str, Any]:
        """
        Get the execution outcome for a completed plan.

        Args:
            plan_id: Plan identifier

        Returns:
            Execution outcome with success status, tasks completed, and lessons
        """
        return self._client._request("GET", f"/api/v1/decisions/plans/{plan_id}/outcome")

    def list_outcomes(self, decision_id: str) -> dict[str, Any]:
        """List all outcomes for a decision.

        Args:
            decision_id: Decision identifier.

        Returns:
            Dict with outcomes array.
        """
        return self._client._request("GET", f"/api/v1/decisions/{decision_id}/outcomes")


class AsyncDecisionsAPI:
    """Asynchronous decisions API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def submit(
        self,
        input: str,
        decision_type: DecisionType = "debate",
        priority: DecisionPriority = "normal",
        context: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """Submit a decision request."""
        data: dict[str, Any] = {
            "input": input,
            "decision_type": decision_type,
            "priority": priority,
        }
        if context:
            data["context"] = context
        if config:
            data["config"] = config
        if callback_url:
            data["callback_url"] = callback_url

        return await self._client._request("POST", "/api/v1/decisions", json=data)

    async def get(self, decision_id: str) -> dict[str, Any]:
        """Get a decision by ID."""
        return await self._client._request("GET", f"/api/v1/decisions/{decision_id}")

    async def get_status(self, decision_id: str) -> dict[str, Any]:
        """Get the status of a decision."""
        return await self._client._request("GET", f"/api/v1/decisions/{decision_id}/status")

    async def list(
        self,
        status: DecisionStatus | None = None,
        decision_type: DecisionType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List decisions with optional filtering."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if decision_type:
            params["decision_type"] = decision_type

        return await self._client._request("GET", "/api/v1/decisions", params=params)

    async def cancel(self, decision_id: str, reason: str | None = None) -> dict[str, Any]:
        """Cancel a pending or processing decision.

        Only decisions in PENDING or PROCESSING status can be cancelled.

        Args:
            decision_id: Decision identifier
            reason: Cancellation reason

        Returns:
            Cancellation confirmation with status and cancelled_at timestamp
        """
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason

        return await self._client._request(
            "POST",
            f"/api/v1/decisions/{decision_id}/cancel",
            json=data if data else None,
        )

    async def retry(self, decision_id: str) -> dict[str, Any]:
        """Retry a failed or cancelled decision.

        Creates a new decision with the same parameters as the original.
        Only decisions in FAILED, CANCELLED, or TIMEOUT status can be retried.

        Args:
            decision_id: Decision identifier

        Returns:
            Retry result with new decision_id and result
        """
        return await self._client._request("POST", f"/api/v1/decisions/{decision_id}/retry")

    async def get_receipt(self, decision_id: str) -> dict[str, Any]:
        """Get the receipt for a completed decision."""
        return await self._client._request("GET", f"/api/v2/receipts/{decision_id}")

    async def get_explanation(self, decision_id: str) -> dict[str, Any]:
        """Get the explanation for a completed decision."""
        return await self._client._request("GET", f"/api/v1/decisions/{decision_id}/explain")

    async def submit_feedback(
        self,
        decision_id: str,
        rating: int,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Submit feedback on a decision."""
        data: dict[str, Any] = {
            "type": "debate_quality",
            "score": rating,
            "context": {"decision_id": decision_id},
        }
        if comment:
            data["comment"] = comment
        else:
            data["comment"] = f"Feedback for decision {decision_id}"

        return await self._client._request("POST", "/api/v1/feedback/general", json=data)

    # -------------------------------------------------------------------------
    # DecisionPlan methods (gold path: debate → plan → execute → verify)
    # -------------------------------------------------------------------------

    async def create_plan(
        self,
        debate_id: str,
        budget_limit_usd: float | None = None,
        approval_mode: Literal["always", "risk_based", "confidence_based", "never"] = "risk_based",
        max_auto_risk: Literal["low", "medium", "high", "critical"] = "low",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a DecisionPlan from a completed debate."""
        data: dict[str, Any] = {"debate_id": debate_id}
        if budget_limit_usd is not None:
            data["budget_limit_usd"] = budget_limit_usd
        if approval_mode:
            data["approval_mode"] = approval_mode
        if max_auto_risk:
            data["max_auto_risk"] = max_auto_risk
        if metadata:
            data["metadata"] = metadata

        return await self._client._request("POST", "/api/v1/decisions/plans", json=data)

    async def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Get a DecisionPlan by ID."""
        return await self._client._request("GET", f"/api/v1/decisions/plans/{plan_id}")

    async def list_plans(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List DecisionPlans with optional filtering."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        return await self._client._request("GET", "/api/v1/decisions/plans", params=params)

    async def approve_plan(
        self,
        plan_id: str,
        reason: str = "",
        conditions: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        """Approve a DecisionPlan for execution."""
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason
        if conditions:
            data["conditions"] = conditions

        return await self._client._request(
            "POST",
            f"/api/v1/decisions/plans/{plan_id}/approve",
            json=data if data else None,
        )

    async def reject_plan(self, plan_id: str, reason: str = "") -> dict[str, Any]:
        """Reject a DecisionPlan."""
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason

        return await self._client._request(
            "POST",
            f"/api/v1/decisions/plans/{plan_id}/reject",
            json=data if data else None,
        )

    async def execute_plan(self, plan_id: str) -> dict[str, Any]:
        """Execute an approved DecisionPlan."""
        return await self._client._request("POST", f"/api/v1/decisions/plans/{plan_id}/execute")

    async def get_plan_outcome(self, plan_id: str) -> dict[str, Any]:
        """Get the execution outcome for a completed plan."""
        return await self._client._request("GET", f"/api/v1/decisions/plans/{plan_id}/outcome")

    async def list_outcomes(self, decision_id: str) -> dict[str, Any]:
        """List all outcomes for a decision."""
        return await self._client._request("GET", f"/api/v1/decisions/{decision_id}/outcomes")
