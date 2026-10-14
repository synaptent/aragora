"""
OpenClaw Secure Proxy.

Enterprise security proxy layer for OpenClaw instances that enforces:
- Policy-based action control
- RBAC integration
- Audit logging
- Rate limiting
- Tenant isolation

All actions flow through the proxy before reaching the OpenClaw backend,
enabling fine-grained security controls without modifying OpenClaw itself.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from aragora.compat.openclaw_policy import (
    ActionRequest,
    ActionType,
    OpenClawPolicy,
    PolicyDecision,
    create_enterprise_policy,
)

logger = logging.getLogger(__name__)


@dataclass
class ProxySession:
    """Active session with the OpenClaw backend."""

    session_id: str
    user_id: str
    tenant_id: str
    workspace_id: str
    roles: list[str]
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    action_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProxyActionResult:
    """Result of a proxied action."""

    success: bool
    action_id: str
    policy_decision: PolicyDecision
    result: Any = None
    error: str | None = None
    execution_time_ms: float = 0.0
    audit_id: str | None = None
    requires_approval: bool = False
    approval_id: str | None = None


@dataclass
class PendingApproval:
    """An action pending human approval."""

    approval_id: str
    action_request: ActionRequest
    session: ProxySession
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    status: str = "pending"  # pending, approved, denied, expired
    approver_id: str | None = None
    approved_at: float | None = None


class OpenClawSecureProxy:
    """
    Secure proxy for OpenClaw instances.

    Intercepts all actions before they reach OpenClaw, enforcing:
    - Policy-based access control
    - Role-based permissions
    - Audit logging for compliance
    - Rate limiting per user/tenant
    - Approval workflows for sensitive operations

    Example:
    ```python
    from aragora.compat.openclaw_proxy import OpenClawSecureProxy
    from aragora.compat.openclaw_policy import create_enterprise_policy

    # Create proxy with enterprise policy
    proxy = OpenClawSecureProxy(
        policy=create_enterprise_policy(),
        audit_callback=lambda e: audit_logger.log(e),
    )

    # Create session for user
    session = await proxy.create_session(
        user_id="user-123",
        tenant_id="acme-corp",
        roles=["developer"],
    )

    # Execute action through proxy
    result = await proxy.execute_action(
        session_id=session.session_id,
        action_type="shell",
        command="ls -la /workspace/project",
    )
    ```
    """

    def __init__(
        self,
        policy: OpenClawPolicy | None = None,
        policy_file: str | None = None,
        openclaw_client: Any | None = None,
        audit_callback: Callable[[dict[str, Any]], None] | None = None,
        approval_callback: Callable[[PendingApproval], None] | None = None,
        rbac_checker: Any | None = None,
        max_sessions_per_user: int = 5,
        session_timeout_seconds: int = 3600,
        approval_timeout_seconds: int = 300,
    ):
        """
        Initialize the secure proxy.

        Args:
            policy: OpenClawPolicy instance for action control
            policy_file: Path to YAML policy file (alternative to policy)
            openclaw_client: Client for the OpenClaw backend (optional)
            audit_callback: Callback for audit events
            approval_callback: Callback when approval is needed
            rbac_checker: Optional RBAC PermissionChecker
            max_sessions_per_user: Maximum concurrent sessions per user
            session_timeout_seconds: Session idle timeout
            approval_timeout_seconds: Time limit for pending approvals
        """
        # Load policy
        if policy:
            self._policy = policy
        elif policy_file:
            self._policy = OpenClawPolicy(policy_file=policy_file)
        else:
            self._policy = create_enterprise_policy()

        self._openclaw_client = openclaw_client
        self._audit_callback = audit_callback
        self._approval_callback = approval_callback
        self._rbac_checker = rbac_checker
        self._max_sessions_per_user = max_sessions_per_user
        self._session_timeout = session_timeout_seconds
        self._approval_timeout = approval_timeout_seconds

        # Session management
        self._sessions: dict[str, ProxySession] = {}
        self._user_sessions: dict[str, list[str]] = {}

        # Approval workflow
        self._pending_approvals: dict[str, PendingApproval] = {}

        # Statistics
        self._stats = {
            "sessions_created": 0,
            "sessions_ended": 0,
            "actions_allowed": 0,
            "actions_denied": 0,
            "actions_pending_approval": 0,
            "approvals_granted": 0,
            "approvals_denied": 0,
            "approvals_expired": 0,
            "total_execution_time_ms": 0.0,
        }

    async def create_session(
        self,
        user_id: str,
        tenant_id: str = "default",
        workspace_id: str = "default",
        roles: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProxySession:
        """
        Create a new proxy session.

        Args:
            user_id: User identifier
            tenant_id: Tenant/organization identifier
            workspace_id: Workspace for scoped operations
            roles: User's roles for RBAC
            metadata: Additional session metadata

        Returns:
            ProxySession for use in action execution
        """
        # Check session limit
        user_sessions = self._user_sessions.get(user_id, [])
        if len(user_sessions) >= self._max_sessions_per_user:
            # Clean up oldest session
            oldest = user_sessions[0]
            await self.end_session(oldest)

        session_id = str(uuid.uuid4())
        session = ProxySession(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            roles=roles or [],
            metadata=metadata or {},
        )

        self._sessions[session_id] = session

        # Track user sessions
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = []
        self._user_sessions[user_id].append(session_id)

        self._stats["sessions_created"] += 1

        self._emit_audit(
            {
                "event_type": "session_created",
                "session_id": session_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "roles": roles,
            }
        )

        return session

    async def end_session(self, session_id: str) -> bool:
        """End a proxy session."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        # Clean up user sessions list
        if session.user_id in self._user_sessions:
            sessions = self._user_sessions[session.user_id]
            if session_id in sessions:
                sessions.remove(session_id)
            if not sessions:
                del self._user_sessions[session.user_id]

        self._stats["sessions_ended"] += 1

        self._emit_audit(
            {
                "event_type": "session_ended",
                "session_id": session_id,
                "user_id": session.user_id,
                "action_count": session.action_count,
                "duration_seconds": time.time() - session.created_at,
            }
        )

        return True

    def get_session(self, session_id: str) -> ProxySession | None:
        """Get a session by ID."""
        session = self._sessions.get(session_id)
        if session:
            # Check for timeout
            if time.time() - session.last_activity > self._session_timeout:
                asyncio.create_task(self.end_session(session_id))
                return None
        return session

    async def execute_action(
        self,
        session_id: str,
        action_type: str | ActionType,
        path: str | None = None,
        command: str | None = None,
        url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProxyActionResult:
        """
        Execute an action through the proxy.

        Args:
            session_id: Session identifier
            action_type: Type of action to perform
            path: File path for file operations
            command: Command for shell operations
            url: URL for browser/API operations
            metadata: Additional action metadata

        Returns:
            ProxyActionResult with outcome and any results
        """
        start_time = time.time()
        action_id = str(uuid.uuid4())

        # Validate session
        session = self.get_session(session_id)
        if not session:
            return ProxyActionResult(
                success=False,
                action_id=action_id,
                policy_decision=PolicyDecision.DENY,
                error="Invalid or expired session",
            )

        # Convert action type
        if isinstance(action_type, str):
            try:
                action_type = ActionType(action_type)
            except ValueError:
                return ProxyActionResult(
                    success=False,
                    action_id=action_id,
                    policy_decision=PolicyDecision.DENY,
                    error=f"Unknown action type: {action_type}",
                )

        # Build action request
        request = ActionRequest(
            action_type=action_type,
            user_id=session.user_id,
            session_id=session_id,
            workspace_id=session.workspace_id,
            path=path,
            command=command,
            url=url,
            roles=session.roles,
            tenant_id=session.tenant_id,
            metadata=metadata or {},
        )

        # Evaluate policy
        policy_result = self._policy.evaluate(request)

        # Update session activity
        session.last_activity = time.time()
        session.action_count += 1

        # Handle policy decision
        if policy_result.decision == PolicyDecision.DENY:
            self._stats["actions_denied"] += 1
            exec_time = (time.time() - start_time) * 1000

            self._emit_audit(
                {
                    "event_type": "action_denied",
                    "action_id": action_id,
                    "session_id": session_id,
                    "user_id": session.user_id,
                    "tenant_id": session.tenant_id,
                    "action_type": action_type.value,
                    "path": path,
                    "command": command,
                    "url": url,
                    "reason": policy_result.reason,
                    "rule": policy_result.matched_rule.name if policy_result.matched_rule else None,
                }
            )

            return ProxyActionResult(
                success=False,
                action_id=action_id,
                policy_decision=PolicyDecision.DENY,
                error=policy_result.reason,
                execution_time_ms=exec_time,
            )

        if policy_result.decision == PolicyDecision.REQUIRE_APPROVAL:
            # Create pending approval
            approval = await self._create_pending_approval(request, session)
            self._stats["actions_pending_approval"] += 1

            return ProxyActionResult(
                success=False,
                action_id=action_id,
                policy_decision=PolicyDecision.REQUIRE_APPROVAL,
                requires_approval=True,
                approval_id=approval.approval_id,
                error="Action requires approval",
            )

        # Policy allows - execute action
        self._stats["actions_allowed"] += 1

        result = await self._execute_backend_action(
            action_type=action_type,
            path=path,
            command=command,
            url=url,
            session=session,
            metadata=metadata,
        )

        exec_time = (time.time() - start_time) * 1000
        self._stats["total_execution_time_ms"] += exec_time

        audit_id = str(uuid.uuid4())
        self._emit_audit(
            {
                "event_type": "action_executed",
                "audit_id": audit_id,
                "action_id": action_id,
                "session_id": session_id,
                "user_id": session.user_id,
                "tenant_id": session.tenant_id,
                "action_type": action_type.value,
                "path": path,
                "command": command,
                "url": url,
                "success": result.get("success", False),
                "execution_time_ms": exec_time,
                "rule": policy_result.matched_rule.name if policy_result.matched_rule else None,
            }
        )

        return ProxyActionResult(
            success=result.get("success", False),
            action_id=action_id,
            policy_decision=PolicyDecision.ALLOW,
            result=result.get("result"),
            error=result.get("error"),
            execution_time_ms=exec_time,
            audit_id=audit_id,
        )

    async def _execute_backend_action(
        self,
        action_type: ActionType,
        path: str | None,
        command: str | None,
        url: str | None,
        session: ProxySession,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute action on the OpenClaw backend."""
        if not self._openclaw_client:
            # Dispatch browser/UI actions via the real action dispatcher
            return await self._dispatch_via_computer_use(action_type, url=url, metadata=metadata)

        try:
            # Map to OpenClaw API calls
            if action_type == ActionType.SHELL:
                result = await self._openclaw_client.execute_shell(command)
            elif action_type == ActionType.FILE_READ:
                result = await self._openclaw_client.read_file(path)
            elif action_type == ActionType.FILE_WRITE:
                content = metadata.get("content", "") if metadata else ""
                result = await self._openclaw_client.write_file(path, content)
            elif action_type == ActionType.FILE_DELETE:
                result = await self._openclaw_client.delete_file(path)
            elif action_type == ActionType.BROWSER:
                result = await self._openclaw_client.navigate(url)
            elif action_type == ActionType.SCREENSHOT:
                result = await self._openclaw_client.screenshot()
            elif action_type == ActionType.KEYBOARD:
                text = metadata.get("text", "") if metadata else ""
                result = await self._openclaw_client.type_text(text)
            elif action_type == ActionType.MOUSE:
                x = metadata.get("x", 0) if metadata else 0
                y = metadata.get("y", 0) if metadata else 0
                result = await self._openclaw_client.click(x, y)
            elif action_type == ActionType.API:
                result = await self._openclaw_client.api_call(url, metadata)
            else:
                return {"success": False, "error": f"Unsupported action: {action_type}"}

            return {"success": True, "result": result}

        except (OSError, ConnectionError, RuntimeError) as e:
            logger.error("Backend execution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def _create_pending_approval(
        self,
        request: ActionRequest,
        session: ProxySession,
    ) -> PendingApproval:
        """Create a pending approval request."""
        approval_id = str(uuid.uuid4())
        approval = PendingApproval(
            approval_id=approval_id,
            action_request=request,
            session=session,
            expires_at=time.time() + self._approval_timeout,
        )

        self._pending_approvals[approval_id] = approval

        # Notify via callback
        if self._approval_callback:
            try:
                self._approval_callback(approval)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided approval callback
                logger.warning("Approval callback failed: %s", e)

        self._emit_audit(
            {
                "event_type": "approval_requested",
                "approval_id": approval_id,
                "session_id": session.session_id,
                "user_id": session.user_id,
                "tenant_id": session.tenant_id,
                "action_type": request.action_type.value,
                "path": request.path,
                "command": request.command,
                "expires_at": approval.expires_at,
            }
        )

        return approval

    async def approve_action(
        self,
        approval_id: str,
        approver_id: str,
    ) -> ProxyActionResult:
        """
        Approve a pending action and execute it.

        Args:
            approval_id: ID of pending approval
            approver_id: ID of user granting approval

        Returns:
            ProxyActionResult from executing the approved action
        """
        approval = self._pending_approvals.get(approval_id)
        if not approval:
            return ProxyActionResult(
                success=False,
                action_id="",
                policy_decision=PolicyDecision.DENY,
                error="Approval not found",
            )

        # Check expiration
        if approval.expires_at and time.time() > approval.expires_at:
            approval.status = "expired"
            self._stats["approvals_expired"] += 1
            return ProxyActionResult(
                success=False,
                action_id="",
                policy_decision=PolicyDecision.DENY,
                error="Approval has expired",
            )

        # Mark approved
        approval.status = "approved"
        approval.approver_id = approver_id
        approval.approved_at = time.time()
        self._stats["approvals_granted"] += 1

        # Remove from pending
        del self._pending_approvals[approval_id]

        self._emit_audit(
            {
                "event_type": "approval_granted",
                "approval_id": approval_id,
                "approver_id": approver_id,
                "session_id": approval.session.session_id,
                "user_id": approval.session.user_id,
                "action_type": approval.action_request.action_type.value,
            }
        )

        # Execute the action
        request = approval.action_request
        result = await self._execute_backend_action(
            action_type=request.action_type,
            path=request.path,
            command=request.command,
            url=request.url,
            session=approval.session,
            metadata=request.metadata,
        )

        action_id = str(uuid.uuid4())
        return ProxyActionResult(
            success=result.get("success", False),
            action_id=action_id,
            policy_decision=PolicyDecision.ALLOW,
            result=result.get("result"),
            error=result.get("error"),
            audit_id=str(uuid.uuid4()),
        )

    async def deny_approval(
        self,
        approval_id: str,
        denier_id: str,
        reason: str = "",
    ) -> bool:
        """
        Deny a pending approval.

        Args:
            approval_id: ID of pending approval
            denier_id: ID of user denying approval
            reason: Reason for denial

        Returns:
            True if denial was recorded
        """
        approval = self._pending_approvals.get(approval_id)
        if not approval:
            return False

        approval.status = "denied"
        approval.approver_id = denier_id
        self._stats["approvals_denied"] += 1

        del self._pending_approvals[approval_id]

        self._emit_audit(
            {
                "event_type": "approval_denied",
                "approval_id": approval_id,
                "denier_id": denier_id,
                "reason": reason,
                "session_id": approval.session.session_id,
                "user_id": approval.session.user_id,
                "action_type": approval.action_request.action_type.value,
            }
        )

        return True

    def get_pending_approvals(
        self,
        tenant_id: str | None = None,
    ) -> list[PendingApproval]:
        """Get pending approvals, optionally filtered by tenant."""
        now = time.time()
        result = []

        for approval in list(self._pending_approvals.values()):
            # Check expiration
            if approval.expires_at and now > approval.expires_at:
                approval.status = "expired"
                self._stats["approvals_expired"] += 1
                del self._pending_approvals[approval.approval_id]
                continue

            # Filter by tenant
            if tenant_id and approval.session.tenant_id != tenant_id:
                continue

            result.append(approval)

        return result

    def get_stats(self) -> dict[str, Any]:
        """Get proxy statistics."""
        return {
            **self._stats,
            "active_sessions": len(self._sessions),
            "pending_approvals": len(self._pending_approvals),
            "policy_rules": len(self._policy.get_rules()),
        }

    def _emit_audit(self, event: dict[str, Any]) -> None:
        """Emit an audit event."""
        event["timestamp"] = time.time()
        event["source"] = "openclaw_proxy"

        if self._audit_callback:
            try:
                self._audit_callback(event)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided audit callback
                logger.warning("Audit callback failed: %s", e)

    async def _dispatch_via_computer_use(
        self,
        action_type: ActionType,
        url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch browser/UI action types through OpenClawActionDispatcher.

        Maps the gateway ActionType enum to OpenClaw action names that the
        ComputerUseBridge understands, then dispatches through the real
        Playwright-backed executor.

        Falls back to simulated success for action types that have no
        computer-use equivalent (shell, file ops, API).
        """
        # Map gateway ActionType to OpenClaw action name + params
        openclaw_action: str | None = None
        params: dict[str, Any] = {}

        if action_type == ActionType.BROWSER:
            openclaw_action = "navigate"
            params = {"url": url or ""}
        elif action_type == ActionType.SCREENSHOT:
            openclaw_action = "screenshot"
        elif action_type == ActionType.KEYBOARD:
            openclaw_action = "type"
            params = {"text": (metadata or {}).get("text", "")}
        elif action_type == ActionType.MOUSE:
            openclaw_action = "click"
            x = (metadata or {}).get("x", 0)
            y = (metadata or {}).get("y", 0)
            params = {"coordinate": [x, y]}
        else:
            # Shell, file ops, API -- no computer-use mapping; return simulated
            return {"success": True, "result": {"simulated": True}}

        try:
            from aragora.compat.openclaw.action_dispatcher import OpenClawActionDispatcher

            dispatcher = OpenClawActionDispatcher()
            await dispatcher.start()
            try:
                result = await dispatcher.dispatch(openclaw_action, params, skip_policy=True)
                return {
                    "success": result.success,
                    "result": result.to_dict(),
                    "error": result.error,
                }
            finally:
                await dispatcher.stop()
        except ImportError:
            logger.debug("Action dispatcher unavailable, returning simulated result")
            return {"success": True, "result": {"simulated": True}}
        except (RuntimeError, OSError, TimeoutError) as e:
            logger.error("Dispatch via computer-use failed: %s", e)
            return {"success": False, "error": str(e)}

    def set_policy(self, policy: OpenClawPolicy) -> None:
        """Replace the current policy."""
        self._policy = policy

    def get_policy(self) -> OpenClawPolicy:
        """Get the current policy."""
        return self._policy

    async def cleanup_expired(self) -> dict[str, int]:
        """Clean up expired sessions and approvals."""
        now = time.time()
        cleaned = {"sessions": 0, "approvals": 0}

        # Clean expired sessions
        for session_id, session in list(self._sessions.items()):
            if now - session.last_activity > self._session_timeout:
                await self.end_session(session_id)
                cleaned["sessions"] += 1

        # Clean expired approvals
        for approval_id, approval in list(self._pending_approvals.items()):
            if approval.expires_at and now > approval.expires_at:
                approval.status = "expired"
                self._stats["approvals_expired"] += 1
                del self._pending_approvals[approval_id]
                cleaned["approvals"] += 1

        return cleaned
