"""
Cross-Workspace Coordination for Multi-Tenant Operations.

Enables secure coordination between workspaces including:
- Federated agent execution
- Cross-workspace data sharing with consent
- Multi-workspace workflow orchestration
- Secure message passing between workspaces
- Permission delegation

Security model:
- All cross-workspace operations require explicit consent
- Data sharing is scoped and audited
- Agent execution respects workspace isolation
- Federation policies control allowed operations
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class SharingScope(str, Enum):
    """Scope of data sharing between workspaces."""

    NONE = "none"  # No sharing allowed
    METADATA = "metadata"  # Only metadata (titles, timestamps)
    SUMMARY = "summary"  # Summarized content
    FULL = "full"  # Full content sharing
    SELECTIVE = "selective"  # Selected fields only


class FederationMode(str, Enum):
    """Mode of workspace federation."""

    ISOLATED = "isolated"  # No federation
    READONLY = "readonly"  # Read from federated workspaces only
    BIDIRECTIONAL = "bidirectional"  # Read and write
    ORCHESTRATED = "orchestrated"  # Central orchestration


class OperationType(str, Enum):
    """Types of cross-workspace operations."""

    READ_KNOWLEDGE = "read_knowledge"
    QUERY_MOUND = "query_mound"
    EXECUTE_AGENT = "execute_agent"
    RUN_WORKFLOW = "run_workflow"
    SHARE_FINDINGS = "share_findings"
    SYNC_CULTURE = "sync_culture"
    BROADCAST_MESSAGE = "broadcast_message"


@dataclass
class FederationPolicy:
    """Policy governing workspace federation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""

    # Federation settings
    mode: FederationMode = FederationMode.ISOLATED
    sharing_scope: SharingScope = SharingScope.NONE

    # Allowed operations
    allowed_operations: set[OperationType] = field(default_factory=set)
    blocked_operations: set[OperationType] = field(default_factory=set)

    # Workspace permissions
    allowed_source_workspaces: set[str] | None = None  # None = any
    allowed_target_workspaces: set[str] | None = None  # None = any
    blocked_workspaces: set[str] = field(default_factory=set)

    # Rate limiting
    max_requests_per_hour: int = 100
    max_data_transfer_mb: float = 100.0

    # Audit settings
    audit_all_requests: bool = True
    require_approval: bool = False
    approval_timeout_hours: int = 24

    # Validity
    valid_from: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: datetime | None = None
    created_by: str = ""

    def is_valid(self) -> bool:
        """Check if policy is currently valid."""
        now = datetime.now(timezone.utc)
        if now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    def allows_operation(
        self,
        operation: OperationType,
        source_workspace: str,
        target_workspace: str,
    ) -> bool:
        """Check if operation is allowed by this policy."""
        if not self.is_valid():
            return False

        if self.mode == FederationMode.ISOLATED:
            return False

        # Check blocked workspaces
        if source_workspace in self.blocked_workspaces:
            return False
        if target_workspace in self.blocked_workspaces:
            return False

        # Check allowed workspaces
        if self.allowed_source_workspaces is not None:
            if source_workspace not in self.allowed_source_workspaces:
                return False

        if self.allowed_target_workspaces is not None:
            if target_workspace not in self.allowed_target_workspaces:
                return False

        # Check operation
        if operation in self.blocked_operations:
            return False

        if self.allowed_operations and operation not in self.allowed_operations:
            return False

        # Check read-only mode
        if self.mode == FederationMode.READONLY:
            write_ops = {
                OperationType.EXECUTE_AGENT,
                OperationType.RUN_WORKFLOW,
                OperationType.SHARE_FINDINGS,
            }
            if operation in write_ops:
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "mode": self.mode.value,
            "sharing_scope": self.sharing_scope.value,
            "allowed_operations": [op.value for op in self.allowed_operations],
            "blocked_operations": [op.value for op in self.blocked_operations],
            "allowed_source_workspaces": (
                list(self.allowed_source_workspaces) if self.allowed_source_workspaces else None
            ),
            "allowed_target_workspaces": (
                list(self.allowed_target_workspaces) if self.allowed_target_workspaces else None
            ),
            "blocked_workspaces": list(self.blocked_workspaces),
            "max_requests_per_hour": self.max_requests_per_hour,
            "max_data_transfer_mb": self.max_data_transfer_mb,
            "audit_all_requests": self.audit_all_requests,
            "require_approval": self.require_approval,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


@dataclass
class DataSharingConsent:
    """Consent for data sharing between workspaces."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source_workspace_id: str = ""
    target_workspace_id: str = ""

    # Consent details
    scope: SharingScope = SharingScope.METADATA
    data_types: set[str] = field(default_factory=set)  # e.g., "debates", "findings"
    operations: set[OperationType] = field(default_factory=set)

    # Consent metadata
    granted_by: str = ""
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    revoked: bool = False
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    # Usage tracking
    times_used: int = 0
    last_used: datetime | None = None
    data_transferred_bytes: int = 0

    def is_valid(self) -> bool:
        """Check if consent is currently valid."""
        if self.revoked:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def record_usage(self, bytes_transferred: int = 0) -> None:
        """Record usage of this consent."""
        self.times_used += 1
        self.last_used = datetime.now(timezone.utc)
        self.data_transferred_bytes += bytes_transferred

    def revoke(self, by: str) -> None:
        """Revoke this consent."""
        self.revoked = True
        self.revoked_at = datetime.now(timezone.utc)
        self.revoked_by = by

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "source_workspace_id": self.source_workspace_id,
            "target_workspace_id": self.target_workspace_id,
            "scope": self.scope.value,
            "data_types": list(self.data_types),
            "operations": [op.value for op in self.operations],
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_valid(),
            "times_used": self.times_used,
            "data_transferred_bytes": self.data_transferred_bytes,
        }


@dataclass
class FederatedWorkspace:
    """Represents a workspace in a federation."""

    id: str = ""
    name: str = ""
    org_id: str = ""

    # Federation status
    is_federated: bool = True
    federation_mode: FederationMode = FederationMode.READONLY
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Capabilities
    supports_agent_execution: bool = True
    supports_workflow_execution: bool = True
    supports_knowledge_query: bool = True

    # Connection info
    endpoint_url: str | None = None
    public_key: str | None = None  # For secure communication

    # Status
    is_online: bool = True
    last_heartbeat: datetime | None = None
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "org_id": self.org_id,
            "is_federated": self.is_federated,
            "federation_mode": self.federation_mode.value,
            "joined_at": self.joined_at.isoformat(),
            "supports_agent_execution": self.supports_agent_execution,
            "supports_workflow_execution": self.supports_workflow_execution,
            "supports_knowledge_query": self.supports_knowledge_query,
            "is_online": self.is_online,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "latency_ms": self.latency_ms,
        }


@dataclass
class CrossWorkspaceRequest:
    """Request for cross-workspace operation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    operation: OperationType = OperationType.READ_KNOWLEDGE
    source_workspace_id: str = ""
    target_workspace_id: str = ""

    # Request details
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0

    # Authentication
    requester_id: str = ""
    requester_role: str = ""
    consent_id: str | None = None

    # Tracking
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, approved, rejected, executing, completed, failed
    approval_required: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "operation": self.operation.value,
            "source_workspace_id": self.source_workspace_id,
            "target_workspace_id": self.target_workspace_id,
            "payload": self.payload,
            "timeout_seconds": self.timeout_seconds,
            "requester_id": self.requester_id,
            "status": self.status,
            "approval_required": self.approval_required,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CrossWorkspaceResult:
    """Result of cross-workspace operation."""

    request_id: str = ""
    success: bool = False
    data: Any = None
    error: str | None = None
    error_code: str | None = None

    # Performance
    execution_time_ms: float = 0.0
    data_size_bytes: int = 0

    # Audit
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    executed_in_workspace: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "success": self.success,
            "data": self.data if self.success else None,
            "error": self.error,
            "error_code": self.error_code,
            "execution_time_ms": self.execution_time_ms,
            "data_size_bytes": self.data_size_bytes,
            "executed_at": self.executed_at.isoformat(),
        }


# Type for operation handlers
OperationHandler = Callable[[CrossWorkspaceRequest], CrossWorkspaceResult]


class CrossWorkspaceCoordinator:
    """
    Coordinates operations across multiple workspaces.

    Manages:
    - Workspace federation
    - Cross-workspace permissions
    - Data sharing consents
    - Operation routing and execution
    - Audit logging
    """

    def __init__(
        self,
        default_policy: FederationPolicy | None = None,
        audit_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        """
        Initialize cross-workspace coordinator.

        Args:
            default_policy: Default federation policy
            audit_callback: Callback for audit events
        """
        # Workspace registry
        self._workspaces: dict[str, FederatedWorkspace] = {}

        # Policies
        self._default_policy = default_policy or FederationPolicy(
            name="default",
            mode=FederationMode.ISOLATED,
        )
        self._workspace_policies: dict[str, FederationPolicy] = {}  # workspace_id -> policy
        self._pair_policies: dict[
            tuple[str, str], FederationPolicy
        ] = {}  # (source, target) -> policy

        # Consents
        self._consents: dict[str, DataSharingConsent] = {}  # consent_id -> consent
        self._workspace_consents: dict[str, set[str]] = {}  # workspace_id -> consent_ids

        # Pending requests
        self._pending_requests: dict[str, CrossWorkspaceRequest] = {}

        # Rate limiting
        self._request_counts: dict[str, list[datetime]] = {}  # workspace_id -> request times

        # Operation handlers
        self._handlers: dict[OperationType, OperationHandler] = {}

        # Audit
        self._audit_callback = audit_callback

    def register_workspace(self, workspace: FederatedWorkspace) -> None:
        """
        Register a workspace for federation.

        Args:
            workspace: Workspace to register
        """
        self._workspaces[workspace.id] = workspace
        self._workspace_consents.setdefault(workspace.id, set())

        logger.info("Registered workspace %s for federation", workspace.id)

        self._audit(
            "workspace_registered",
            workspace_id=workspace.id,
            org_id=workspace.org_id,
        )

    def unregister_workspace(self, workspace_id: str) -> None:
        """Remove a workspace from federation."""
        if workspace_id in self._workspaces:
            del self._workspaces[workspace_id]

        # Revoke all consents involving this workspace
        for consent_id in list(self._workspace_consents.get(workspace_id, set())):
            if consent_id in self._consents:
                self._consents[consent_id].revoke("system")

        logger.info("Unregistered workspace %s", workspace_id)

        self._audit(
            "workspace_unregistered",
            workspace_id=workspace_id,
        )

    def set_policy(
        self,
        policy: FederationPolicy,
        workspace_id: str | None = None,
        source_workspace_id: str | None = None,
        target_workspace_id: str | None = None,
    ) -> None:
        """
        Set a federation policy.

        Args:
            policy: Policy to set
            workspace_id: Apply to specific workspace
            source_workspace_id: Apply to specific source-target pair
            target_workspace_id: Apply to specific source-target pair
        """
        if source_workspace_id and target_workspace_id:
            self._pair_policies[(source_workspace_id, target_workspace_id)] = policy
        elif workspace_id:
            self._workspace_policies[workspace_id] = policy
        else:
            self._default_policy = policy

    def get_policy(
        self,
        source_workspace_id: str,
        target_workspace_id: str,
    ) -> FederationPolicy:
        """Get applicable policy for a workspace pair."""
        # Check pair-specific policy first
        pair_key = (source_workspace_id, target_workspace_id)
        if pair_key in self._pair_policies:
            return self._pair_policies[pair_key]

        # Check workspace-specific policies
        if source_workspace_id in self._workspace_policies:
            return self._workspace_policies[source_workspace_id]
        if target_workspace_id in self._workspace_policies:
            return self._workspace_policies[target_workspace_id]

        return self._default_policy

    def grant_consent(
        self,
        source_workspace_id: str,
        target_workspace_id: str,
        scope: SharingScope,
        data_types: set[str],
        operations: set[OperationType],
        granted_by: str,
        expires_in_days: int | None = None,
    ) -> DataSharingConsent:
        """
        Grant data sharing consent between workspaces.

        Args:
            source_workspace_id: Source workspace
            target_workspace_id: Target workspace
            scope: Sharing scope
            data_types: Types of data to share
            operations: Allowed operations
            granted_by: User granting consent
            expires_in_days: Expiration in days

        Returns:
            Created consent
        """
        consent = DataSharingConsent(
            source_workspace_id=source_workspace_id,
            target_workspace_id=target_workspace_id,
            scope=scope,
            data_types=data_types,
            operations=operations,
            granted_by=granted_by,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=expires_in_days)
                if expires_in_days
                else None
            ),
        )

        self._consents[consent.id] = consent
        self._workspace_consents.setdefault(source_workspace_id, set()).add(consent.id)
        self._workspace_consents.setdefault(target_workspace_id, set()).add(consent.id)

        logger.info(
            "Granted consent %s from %s to %s", consent.id, source_workspace_id, target_workspace_id
        )

        self._audit(
            "consent_granted",
            consent_id=consent.id,
            source_workspace=source_workspace_id,
            target_workspace=target_workspace_id,
            scope=scope.value,
            granted_by=granted_by,
        )

        return consent

    def revoke_consent(self, consent_id: str, revoked_by: str) -> bool:
        """Revoke a consent."""
        if consent_id not in self._consents:
            return False

        consent = self._consents[consent_id]
        consent.revoke(revoked_by)

        self._audit(
            "consent_revoked",
            consent_id=consent_id,
            revoked_by=revoked_by,
        )

        return True

    def get_consent(
        self,
        source_workspace_id: str,
        target_workspace_id: str,
        operation: OperationType,
    ) -> DataSharingConsent | None:
        """Find a valid consent for the operation."""
        # Check consents for source workspace
        for consent_id in self._workspace_consents.get(source_workspace_id, set()):
            consent = self._consents.get(consent_id)
            if not consent or not consent.is_valid():
                continue

            if consent.target_workspace_id != target_workspace_id:
                continue

            if operation not in consent.operations:
                continue

            return consent

        return None

    def register_handler(
        self,
        operation: OperationType,
        handler: OperationHandler,
    ) -> None:
        """Register a handler for an operation type."""
        self._handlers[operation] = handler

    async def execute(
        self,
        request: CrossWorkspaceRequest,
    ) -> CrossWorkspaceResult:
        """
        Execute a cross-workspace request.

        Args:
            request: Request to execute

        Returns:
            Operation result
        """
        start_time = datetime.now(timezone.utc)

        # Validate workspaces
        if request.source_workspace_id not in self._workspaces:
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Source workspace not registered",
                error_code="WORKSPACE_NOT_FOUND",
            )

        if request.target_workspace_id not in self._workspaces:
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Target workspace not registered",
                error_code="WORKSPACE_NOT_FOUND",
            )

        # Get applicable policy
        policy = self.get_policy(
            request.source_workspace_id,
            request.target_workspace_id,
        )

        # Check policy allows operation
        if not policy.allows_operation(
            request.operation,
            request.source_workspace_id,
            request.target_workspace_id,
        ):
            self._audit(
                "request_denied_by_policy",
                request_id=request.id,
                operation=request.operation.value,
                source_workspace=request.source_workspace_id,
                target_workspace=request.target_workspace_id,
            )

            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Operation not allowed by federation policy",
                error_code="POLICY_DENIED",
            )

        # Check consent
        consent = self.get_consent(
            request.source_workspace_id,
            request.target_workspace_id,
            request.operation,
        )

        if not consent and policy.sharing_scope != SharingScope.NONE:
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="No valid consent for this operation",
                error_code="NO_CONSENT",
            )

        # Check rate limits
        if not self._check_rate_limit(request.source_workspace_id, policy):
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Rate limit exceeded",
                error_code="RATE_LIMIT_EXCEEDED",
            )

        # Handle approval if required
        if policy.require_approval and not request.approved_by:
            request.status = "pending_approval"
            request.approval_required = True
            self._pending_requests[request.id] = request

            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Request requires approval",
                error_code="APPROVAL_REQUIRED",
            )

        # Execute operation
        request.status = "executing"
        result = await self._execute_operation(request)

        # Record consent usage
        if consent:
            consent.record_usage(result.data_size_bytes)

        # Record execution time
        end_time = datetime.now(timezone.utc)
        result.execution_time_ms = (end_time - start_time).total_seconds() * 1000

        # Audit
        self._audit(
            "request_executed",
            request_id=request.id,
            operation=request.operation.value,
            source_workspace=request.source_workspace_id,
            target_workspace=request.target_workspace_id,
            success=result.success,
            execution_time_ms=result.execution_time_ms,
        )

        return result

    async def _execute_operation(
        self,
        request: CrossWorkspaceRequest,
    ) -> CrossWorkspaceResult:
        """Execute the actual operation."""
        handler = self._handlers.get(request.operation)

        if not handler:
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error=f"No handler for operation: {request.operation.value}",
                error_code="NO_HANDLER",
            )

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, handler, request),
                timeout=request.timeout_seconds,
            )
            return result

        except asyncio.TimeoutError:
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error="Operation timed out",
                error_code="TIMEOUT",
            )
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error("Operation execution failed: %s", e)
            return CrossWorkspaceResult(
                request_id=request.id,
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR",
            )

    def _check_rate_limit(
        self,
        workspace_id: str,
        policy: FederationPolicy,
    ) -> bool:
        """Check if workspace is within rate limits."""
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)

        # Get recent requests
        request_times = self._request_counts.get(workspace_id, [])

        # Filter to last hour
        recent = [t for t in request_times if t > hour_ago]
        self._request_counts[workspace_id] = recent

        # Check limit
        if len(recent) >= policy.max_requests_per_hour:
            return False

        # Record this request
        recent.append(now)
        return True

    def approve_request(
        self,
        request_id: str,
        approved_by: str,
    ) -> bool:
        """Approve a pending request."""
        if request_id not in self._pending_requests:
            return False

        request = self._pending_requests[request_id]
        request.status = "approved"
        request.approved_by = approved_by
        request.approved_at = datetime.now(timezone.utc)

        del self._pending_requests[request_id]

        self._audit(
            "request_approved",
            request_id=request_id,
            approved_by=approved_by,
        )

        return True

    def reject_request(
        self,
        request_id: str,
        rejected_by: str,
        reason: str = "",
    ) -> bool:
        """Reject a pending request."""
        if request_id not in self._pending_requests:
            return False

        request = self._pending_requests[request_id]
        request.status = "rejected"

        del self._pending_requests[request_id]

        self._audit(
            "request_rejected",
            request_id=request_id,
            rejected_by=rejected_by,
            reason=reason,
        )

        return True

    def list_workspaces(self) -> list[FederatedWorkspace]:
        """List all federated workspaces."""
        return list(self._workspaces.values())

    def list_consents(
        self,
        workspace_id: str | None = None,
    ) -> list[DataSharingConsent]:
        """List consents, optionally filtered by workspace."""
        if workspace_id:
            consent_ids = self._workspace_consents.get(workspace_id, set())
            return [self._consents[cid] for cid in consent_ids if cid in self._consents]
        return list(self._consents.values())

    def list_pending_requests(
        self,
        workspace_id: str | None = None,
    ) -> list[CrossWorkspaceRequest]:
        """List pending approval requests."""
        requests = list(self._pending_requests.values())
        if workspace_id:
            requests = [r for r in requests if r.target_workspace_id == workspace_id]
        return requests

    def _audit(self, event_type: str, **kwargs: Any) -> None:
        """Record audit event."""
        if self._audit_callback:
            try:
                self._audit_callback(
                    {
                        "event_type": event_type,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **kwargs,
                    }
                )
            except (TypeError, ValueError, RuntimeError) as e:
                logger.error("Audit callback failed: %s", e)

        logger.debug("Audit: %s %s", event_type, kwargs)

    def get_stats(self) -> dict[str, Any]:
        """Get coordinator statistics."""
        return {
            "total_workspaces": len(self._workspaces),
            "total_consents": len(self._consents),
            "valid_consents": sum(1 for c in self._consents.values() if c.is_valid()),
            "pending_requests": len(self._pending_requests),
            "registered_handlers": [h.value for h in self._handlers.keys()],
        }


# Global coordinator instance
_coordinator: CrossWorkspaceCoordinator | None = None


def get_coordinator() -> CrossWorkspaceCoordinator:
    """Get or create the global coordinator."""
    global _coordinator
    if _coordinator is None:
        _coordinator = CrossWorkspaceCoordinator()
    return _coordinator


# Backward-compatible alias
CrossWorkspaceOperation = OperationType

__all__ = [
    "CrossWorkspaceCoordinator",
    "CrossWorkspaceOperation",
    "FederatedWorkspace",
    "FederationPolicy",
    "FederationMode",
    "CrossWorkspaceRequest",
    "CrossWorkspaceResult",
    "DataSharingConsent",
    "SharingScope",
    "OperationType",
    "get_coordinator",
]
