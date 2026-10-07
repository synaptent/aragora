"""
Approval Gate Middleware for High-Risk Operations.

Provides middleware and decorators for requiring human approval
before executing sensitive operations such as:
- Role changes
- API key generation/revocation
- Connector configuration changes
- Organization settings updates

Usage:
    from aragora.server.middleware.approval_gate import (
        require_approval,
        ApprovalGate,
        OperationRiskLevel,
    )

    # As a decorator
    @require_approval(
        operation="delete_user",
        risk_level=OperationRiskLevel.HIGH,
        checklist=["Confirm user data backup", "Verify user notification"],
    )
    async def delete_user(request, auth_context):
        ...

    # As middleware
    gate = ApprovalGate(operations={
        "org.settings.update": OperationRiskLevel.MEDIUM,
        "user.role.change": OperationRiskLevel.HIGH,
    })
    app.middlewares.append(gate)
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TypeVar, ParamSpec
from collections.abc import Awaitable, Callable, Coroutine

from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class OperationRiskLevel(Enum):
    """Risk level for operations requiring approval."""

    LOW = "low"  # Info only, no approval needed
    MEDIUM = "medium"  # Requires single approver
    HIGH = "high"  # Requires approval with checklist
    CRITICAL = "critical"  # Requires multi-approver or escalation


class ApprovalState(Enum):
    """State of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ESCALATED = "escalated"


@dataclass
class ApprovalChecklistItem:
    """A checklist item for approval."""

    label: str
    required: bool = True
    checked: bool = False


@dataclass
class OperationApprovalRequest:
    """Request for approval of a sensitive operation."""

    id: str
    operation: str
    risk_level: OperationRiskLevel
    requester_id: str
    requester_email: str | None = None
    org_id: str | None = None
    workspace_id: str | None = None
    resource_type: str = ""
    resource_id: str = ""
    description: str = ""
    checklist: list[ApprovalChecklistItem] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    state: ApprovalState = ApprovalState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "operation": self.operation,
            "risk_level": self.risk_level.value,
            "requester_id": self.requester_id,
            "requester_email": self.requester_email,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "description": self.description,
            "checklist": [
                {"label": c.label, "required": c.required, "checked": c.checked}
                for c in self.checklist
            ],
            "context": self.context,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejection_reason": self.rejection_reason,
        }


class ApprovalPendingError(Exception):
    """Raised when operation requires approval that is pending."""

    def __init__(self, request: OperationApprovalRequest):
        self.request = request
        super().__init__(f"Operation '{request.operation}' requires approval (ID: {request.id})")


class ApprovalDeniedError(Exception):
    """Raised when approval was denied."""

    def __init__(self, request: OperationApprovalRequest, reason: str = ""):
        self.request = request
        self.reason = reason
        super().__init__(f"Operation '{request.operation}' was denied: {reason}")


# In-memory storage for pending approvals (should use GovernanceStore in production)
_pending_approvals: dict[str, OperationApprovalRequest] = {}
_MAX_PENDING_APPROVALS = 10_000  # Prevent unbounded growth
_CLEANUP_INTERVAL = 300  # Cleanup every 5 minutes
_last_cleanup_time: float = 0.0


def _cleanup_expired_approvals() -> int:
    """Remove expired or resolved approvals from in-memory store.

    Returns number of entries removed.
    """
    global _last_cleanup_time
    now = datetime.now(timezone.utc)
    _last_cleanup_time = time.time()

    expired_ids = [
        rid
        for rid, req in _pending_approvals.items()
        if (req.expires_at and now > req.expires_at) or req.state != ApprovalState.PENDING
    ]
    for rid in expired_ids:
        del _pending_approvals[rid]

    if expired_ids:
        logger.debug("Cleaned up %s expired/resolved approval requests", len(expired_ids))

    return len(expired_ids)


def _maybe_cleanup() -> None:
    """Run cleanup if enough time has elapsed since last cleanup."""
    if time.time() - _last_cleanup_time >= _CLEANUP_INTERVAL:
        _cleanup_expired_approvals()


async def create_approval_request(
    operation: str,
    risk_level: OperationRiskLevel,
    auth_context: AuthorizationContext,
    resource_type: str = "",
    resource_id: str = "",
    description: str = "",
    checklist: list[str] | None = None,
    context: dict[str, Any] | None = None,
    timeout_hours: float = 24.0,
) -> OperationApprovalRequest:
    """
    Create an approval request for a sensitive operation.

    Args:
        operation: Operation name (e.g., "user.role.change")
        risk_level: Risk level of the operation
        auth_context: Authorization context of the requester
        resource_type: Type of resource being affected
        resource_id: ID of the resource
        description: Human-readable description
        checklist: List of checklist items (strings)
        context: Additional context data
        timeout_hours: Hours until request expires

    Returns:
        The created approval request
    """
    request_id = str(uuid.uuid4())

    checklist_items = [ApprovalChecklistItem(label=item) for item in (checklist or [])]

    request = OperationApprovalRequest(
        id=request_id,
        operation=operation,
        risk_level=risk_level,
        requester_id=auth_context.user_id,
        requester_email=auth_context.user_email,
        org_id=auth_context.org_id,
        workspace_id=auth_context.workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        checklist=checklist_items,
        context=context or {},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=timeout_hours),
    )

    # Cleanup expired entries periodically and enforce max size
    _maybe_cleanup()
    if len(_pending_approvals) >= _MAX_PENDING_APPROVALS:
        _cleanup_expired_approvals()
        if len(_pending_approvals) >= _MAX_PENDING_APPROVALS:
            logger.warning(
                "Pending approvals at capacity (%d), rejecting new request",
                _MAX_PENDING_APPROVALS,
            )
            raise RuntimeError("Too many pending approval requests")

    # Store in memory and persist to governance store
    _pending_approvals[request_id] = request

    # Persist to governance store
    await _persist_approval_request(request)

    # Emit metrics
    _record_approval_request_created(request)

    logger.info(
        "Approval request created: %s for %s by %s (risk: %s)",
        request_id,
        operation,
        auth_context.user_id,
        risk_level.value,
    )

    return request


async def get_approval_request(request_id: str) -> OperationApprovalRequest | None:
    """Get an approval request by ID."""
    # Check in-memory first
    if request_id in _pending_approvals:
        return _pending_approvals[request_id]

    # Try to recover from governance store
    return await _recover_approval_request(request_id)


async def resolve_approval(
    request_id: str,
    approved: bool,
    approver_id: str,
    checklist_status: dict[str, bool] | None = None,
    rejection_reason: str = "",
) -> bool:
    """
    Resolve an approval request.

    Args:
        request_id: ID of the approval request
        approved: Whether the operation is approved
        approver_id: ID of the approver
        checklist_status: Status of checklist items (label -> checked)
        rejection_reason: Reason for rejection (if not approved)

    Returns:
        True if resolution was successful
    """
    request = await get_approval_request(request_id)
    if not request:
        logger.warning("Approval request not found: %s", request_id)
        return False

    if request.state != ApprovalState.PENDING:
        logger.warning("Approval request %s already resolved: %s", request_id, request.state)
        return False

    # Check if expired
    if request.expires_at and datetime.now(timezone.utc) > request.expires_at:
        request.state = ApprovalState.EXPIRED
        _pending_approvals.pop(request_id, None)
        await _update_approval_state(request)
        return False

    # Update checklist if provided
    if checklist_status:
        for item in request.checklist:
            if item.label in checklist_status:
                item.checked = checklist_status[item.label]

    # Check required checklist items
    if approved:
        for item in request.checklist:
            if item.required and not item.checked:
                logger.warning(
                    "Cannot approve %s: required checklist item '%s' not checked",
                    request_id,
                    item.label,
                )
                return False

    # Update state
    request.approved_by = approver_id
    request.approved_at = datetime.now(timezone.utc)

    if approved:
        request.state = ApprovalState.APPROVED
    else:
        request.state = ApprovalState.REJECTED
        request.rejection_reason = rejection_reason

    # Update storage
    _pending_approvals.pop(request_id, None)
    await _update_approval_state(request)

    # Record metrics and audit
    _record_approval_resolved(request)

    logger.info(
        "Approval request %s resolved: %s by %s", request_id, request.state.value, approver_id
    )

    return True


async def get_pending_approvals(
    org_id: str | None = None,
    requester_id: str | None = None,
) -> list[OperationApprovalRequest]:
    """Get pending approval requests."""
    results = []

    for request in _pending_approvals.values():
        if request.state != ApprovalState.PENDING:
            continue

        # Check expiry
        if request.expires_at and datetime.now(timezone.utc) > request.expires_at:
            request.state = ApprovalState.EXPIRED
            continue

        # Filter by org
        if org_id and request.org_id != org_id:
            continue

        # Filter by requester
        if requester_id and request.requester_id != requester_id:
            continue

        results.append(request)

    return results


def require_approval(
    operation: str,
    risk_level: OperationRiskLevel = OperationRiskLevel.HIGH,
    checklist: list[str] | None = None,
    description: str = "",
    resource_type_param: str | None = None,
    resource_id_param: str | None = None,
    auto_approve_roles: set[str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """
    Decorator to require approval for a sensitive operation.

    If the operation hasn't been approved, raises ApprovalPendingError.
    The caller should handle this by presenting the approval UI to the user.

    Args:
        operation: Operation name for identification
        risk_level: Risk level (determines approval requirements)
        checklist: List of checklist items for approvers
        description: Human-readable description
        resource_type_param: Kwarg name containing resource type
        resource_id_param: Kwarg name containing resource ID
        auto_approve_roles: Roles that can auto-approve (e.g., {"owner"})

    Usage:
        @require_approval(
            operation="org.member.remove",
            risk_level=OperationRiskLevel.HIGH,
            checklist=["Verify user notification", "Confirm data handling"],
        )
        async def remove_member(request, auth_context, member_id):
            ...
    """
    auto_roles = auto_approve_roles or set()

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Find auth_context in kwargs
            auth_context = kwargs.get("auth_context")
            if not auth_context:
                # Try to find in args (for methods)
                for arg in args:
                    if isinstance(arg, AuthorizationContext):
                        auth_context = arg
                        break

            if not auth_context:
                raise ValueError("No AuthorizationContext found for approval check")

            # Type check for auth_context
            if not isinstance(auth_context, AuthorizationContext):
                raise TypeError(f"Expected AuthorizationContext, got {type(auth_context).__name__}")

            # Check if user has auto-approve role
            if auto_roles and auth_context.has_any_role(*auto_roles):
                logger.debug(
                    "Auto-approved %s for %s (roles: %s)",
                    operation,
                    auth_context.user_id,
                    auth_context.roles,
                )
                result = await func(*args, **kwargs)
                return result

            # Check for existing approval token in kwargs
            approval_id = kwargs.pop("_approval_id", None)

            if approval_id:
                # Verify the approval is valid
                request = await get_approval_request(str(approval_id))
                if request and request.state == ApprovalState.APPROVED:
                    # Approval is valid, proceed
                    logger.info(
                        "Executing approved operation %s (approval: %s)", operation, approval_id
                    )
                    result = await func(*args, **kwargs)
                    return result
                elif request and request.state == ApprovalState.REJECTED:
                    raise ApprovalDeniedError(request, request.rejection_reason or "")
                elif request and request.state == ApprovalState.EXPIRED:
                    raise ApprovalDeniedError(request, "Approval expired")

            # Extract resource info if specified
            resource_type = ""
            resource_id = ""
            if resource_type_param:
                resource_type = str(kwargs.get(resource_type_param, ""))
            if resource_id_param:
                resource_id = str(kwargs.get(resource_id_param, ""))

            # Create approval request
            approval_request = await create_approval_request(
                operation=operation,
                risk_level=risk_level,
                auth_context=auth_context,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else "",
                description=description or f"Approval required for {operation}",
                checklist=checklist,
                context={
                    "function": func.__name__,
                    "kwargs_keys": list(kwargs.keys()),
                },
            )

            # Raise pending error so caller can present approval UI
            raise ApprovalPendingError(approval_request)

        return wrapper

    return decorator


# =============================================================================
# Internal Helpers
# =============================================================================


async def _persist_approval_request(request: OperationApprovalRequest) -> None:
    """Persist approval request to governance store.

    Raises:
        DistributedStateError: If distributed state required but persistence fails.
    """
    try:
        from aragora.storage.governance_store import get_governance_store

        store = get_governance_store()
        if hasattr(store, "save_approval"):
            result = store.save_approval(
                approval_id=request.id,
                title=f"{request.operation}: {request.description}",
                description=request.description,
                risk_level=request.risk_level.value,
                status=request.state.value,
                requested_by=request.requester_id,
                changes=[],
                timeout_seconds=(
                    int((request.expires_at - request.created_at).total_seconds())
                    if request.expires_at
                    else 86400
                ),
                workspace_id=request.workspace_id,
                metadata={
                    "operation": request.operation,
                    "resource_type": request.resource_type,
                    "resource_id": request.resource_id,
                    "org_id": request.org_id,
                    "context": request.context,
                    "checklist": [
                        {"label": c.label, "required": c.required} for c in request.checklist
                    ],
                },
            )
            if inspect.isawaitable(result):
                await result
    except (TypeError, ValueError, KeyError, AttributeError, RuntimeError, OSError) as e:
        # In distributed mode, persistence failure is critical
        from aragora.config.distributed import is_distributed_state_required
        from aragora.control_plane.leader import DistributedStateError

        if is_distributed_state_required():
            raise DistributedStateError(
                "approval_gate",
                f"Failed to persist approval request: {e}. "
                "Approvals must be persisted in distributed deployments.",
            )
        logger.warning("Failed to persist approval request: %s", e)


async def _recover_approval_request(request_id: str) -> OperationApprovalRequest | None:
    """Try to recover approval request from governance store."""
    try:
        from aragora.storage.governance_store import get_governance_store
        import json

        store = get_governance_store()
        record = store.get_approval(request_id)

        if not record:
            return None

        metadata = json.loads(record.metadata_json) if record.metadata_json else {}

        checklist = [
            ApprovalChecklistItem(
                label=item.get("label", ""),
                required=item.get("required", True),
            )
            for item in metadata.get("checklist", [])
        ]

        request = OperationApprovalRequest(
            id=record.approval_id,
            operation=metadata.get("operation", "unknown"),
            risk_level=OperationRiskLevel(metadata.get("risk_level", "high")),
            requester_id=record.requested_by or "",
            org_id=metadata.get("org_id"),
            workspace_id=record.workspace_id,
            resource_type=metadata.get("resource_type", ""),
            resource_id=metadata.get("resource_id", ""),
            description=record.description or "",
            checklist=checklist,
            context=metadata.get("context", {}),
            state=ApprovalState(record.status),
            created_at=getattr(record, "created_at", datetime.now(timezone.utc)),
            expires_at=(
                getattr(record, "created_at", datetime.now(timezone.utc))
                + timedelta(seconds=getattr(record, "timeout_seconds", 86400))
                if getattr(record, "timeout_seconds", None)
                else None
            ),
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            rejection_reason=record.rejection_reason,
        )

        # Cache it
        if request.state == ApprovalState.PENDING:
            _pending_approvals[request_id] = request

        return request

    except (
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
    ) as e:
        logger.warning("Failed to recover approval request %s: %s", request_id, e)
        return None


async def _update_approval_state(request: OperationApprovalRequest) -> None:
    """Update approval state in governance store."""
    try:
        from aragora.storage.governance_store import get_governance_store

        store = get_governance_store()
        store.update_approval_status(
            approval_id=request.id,
            status=request.state.value,
            approved_by=request.approved_by,
            rejection_reason=request.rejection_reason,
        )
    except (TypeError, ValueError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to update approval state: %s", e)


def _record_approval_request_created(request: OperationApprovalRequest) -> None:
    """Record metrics for approval request creation."""
    try:
        from aragora.observability.metrics.stores import record_governance_approval

        record_governance_approval(request.operation, "created")
    except ImportError:
        # Metrics module not available (optional dependency)
        pass
    except (AttributeError, TypeError, RuntimeError, ValueError) as e:
        logger.warning("Failed to record approval creation metric: %s", e)


def _record_approval_resolved(request: OperationApprovalRequest) -> None:
    """Record metrics and audit for approval resolution."""
    try:
        from aragora.observability.metrics.stores import record_governance_approval

        record_governance_approval(request.operation, request.state.value)
    except ImportError:
        # Metrics module not available (optional dependency)
        pass
    except (AttributeError, TypeError, RuntimeError, ValueError) as e:
        logger.warning("Failed to record approval resolution metric: %s", e)

    # Audit log
    try:
        from aragora.observability.security_audit import audit_rbac_decision

        asyncio.create_task(
            audit_rbac_decision(
                user_id=request.approved_by or "system",
                permission=f"approve:{request.operation}",
                granted=request.state == ApprovalState.APPROVED,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                workspace_id=request.workspace_id,
                request_id=request.id,
                requester_id=request.requester_id,
            )
        )
    except ImportError:
        # Audit module not available (optional dependency)
        pass
    except (RuntimeError, TypeError) as e:
        logger.warning("Failed to create audit task for approval: %s", e)


# =============================================================================
# Startup Recovery
# =============================================================================


async def recover_pending_approvals() -> int:
    """
    Recover pending approval requests from the governance store at startup.

    This function should be called during server initialization to restore
    any pending approvals that were active when the server last stopped.
    Approvals that have expired are automatically rejected.

    Returns:
        Number of pending approvals recovered
    """
    try:
        from aragora.storage.governance_store import get_governance_store

        store = get_governance_store()
        pending_records = store.list_approvals(status="pending")

        recovered = 0
        expired = 0
        now = datetime.now(timezone.utc)

        for record in pending_records:
            try:
                metadata = json.loads(record.metadata_json) if record.metadata_json else {}

                # Check if expired
                if record.timeout_seconds:
                    expires_at = record.requested_at + timedelta(seconds=record.timeout_seconds)
                    if now > expires_at:
                        # Auto-expire
                        store.update_approval_status(
                            approval_id=record.approval_id,
                            status="expired",
                        )
                        expired += 1
                        continue

                # Recover to in-memory cache
                checklist = [
                    ApprovalChecklistItem(
                        label=item.get("label", ""),
                        required=item.get("required", True),
                    )
                    for item in metadata.get("checklist", [])
                ]

                request = OperationApprovalRequest(
                    id=record.approval_id,
                    operation=metadata.get("operation", "unknown"),
                    risk_level=OperationRiskLevel(record.risk_level or "high"),
                    requester_id=record.requested_by or "",
                    org_id=metadata.get("org_id"),
                    workspace_id=record.workspace_id,
                    resource_type=metadata.get("resource_type", ""),
                    resource_id=metadata.get("resource_id", ""),
                    description=record.description or "",
                    checklist=checklist,
                    context=metadata.get("context", {}),
                    state=ApprovalState.PENDING,
                    created_at=record.requested_at,
                    expires_at=(
                        record.requested_at + timedelta(seconds=record.timeout_seconds)
                        if record.timeout_seconds
                        else None
                    ),
                )

                _pending_approvals[record.approval_id] = request
                recovered += 1

            except (TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError) as e:
                logger.warning("Failed to recover approval %s: %s", record.approval_id, e)

        if recovered > 0 or expired > 0:
            logger.info(
                "Approval gate recovery: %s pending restored, %s expired", recovered, expired
            )

        return recovered

    except ImportError:
        logger.debug("GovernanceStore not available, approval recovery skipped")
        return 0
    except (TypeError, ValueError, KeyError, AttributeError, RuntimeError, OSError) as e:
        logger.warning("Failed to recover pending approvals: %s", e)
        return 0


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ApprovalChecklistItem",
    "ApprovalDeniedError",
    "ApprovalPendingError",
    "ApprovalState",
    "OperationApprovalRequest",
    "OperationRiskLevel",
    "create_approval_request",
    "get_approval_request",
    "get_pending_approvals",
    "recover_pending_approvals",
    "require_approval",
    "resolve_approval",
]
