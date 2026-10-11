"""
OpenClaw Gateway Adapter.

Provides comprehensive integration between Aragora and OpenClaw systems:
- Protocol translation (Aragora <-> OpenClaw message formats)
- Channel mapping (WhatsApp, Telegram, Slack, Discord, etc.)
- Action execution (browser control, canvas, cron, etc.)
- Session management with tenant/user context

Usage:
    from aragora.gateway.openclaw import (
        OpenClawAdapter,
        OpenClawMessage,
        OpenClawAction,
        OpenClawSession,
        ChannelMapping,
    )

    adapter = OpenClawAdapter(
        openclaw_endpoint="http://localhost:8081",
        rbac_checker=checker,
    )

    # Create session
    session = await adapter.create_session(
        user_id="user-123",
        channel="telegram",
        tenant_id="tenant-456",
    )

    # Execute action
    result = await adapter.execute_action(
        session_id=session.session_id,
        action=OpenClawAction(
            action_type="browser_navigate",
            parameters={"url": "https://example.com"},
        ),
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from collections.abc import Callable
from uuid import uuid4

from .audit import OpenClawAuditEvents, get_event_severity
from .capabilities import CapabilityFilter
from .formatters import (
    ChannelFormatter,
    DiscordFormatter,
    SlackFormatter,
    TelegramFormatter,
    WhatsAppFormatter,
)
from .models import (
    ActionResult,
    ActionStatus,
    ChannelMapping,
    DeviceHandle,
    DeviceRegistration,
    GatewayResult,
    OpenClawAction,
    OpenClawActionType,
    OpenClawChannel,
    OpenClawMessage,
    OpenClawSession,
    PluginInstallRequest,
    SessionState,
)
from .protocol import (
    AragoraRequest,
    AragoraResponse,
    AuthorizationContext,
    OpenClawProtocolTranslator,
    TenantContext,
)
from .protocols import (
    ApprovalGateProtocol,
    AuditLoggerProtocol,
    RBACCheckerProtocol,
)
from .sandbox import OpenClawSandbox, OpenClawTask, SandboxConfig

logger = logging.getLogger(__name__)


# ============================================================================
# OpenClaw Adapter
# ============================================================================


class OpenClawAdapter:
    """
    Comprehensive adapter for Aragora-OpenClaw integration.

    Provides:
    - Protocol translation between Aragora and OpenClaw formats
    - Channel mapping with custom formatters
    - Action execution with timeout and retry handling
    - Session management with tenant/user context

    Usage:
        adapter = OpenClawAdapter(
            openclaw_endpoint="http://localhost:8081",
            rbac_checker=checker,
        )

        # Create session
        session = await adapter.create_session(
            user_id="user-123",
            channel="telegram",
            tenant_id="tenant-456",
        )

        # Send message
        message = OpenClawMessage(
            message_id=str(uuid4()),
            type="text",
            content="Hello from Aragora!",
            channel=OpenClawChannel.TELEGRAM,
        )
        result = await adapter.send_message(session.session_id, message)
    """

    # Default channel mappings
    DEFAULT_CHANNEL_MAPPINGS: dict[str, ChannelMapping] = {
        "whatsapp": ChannelMapping("whatsapp", OpenClawChannel.WHATSAPP, "whatsapp"),
        "telegram": ChannelMapping("telegram", OpenClawChannel.TELEGRAM, "telegram"),
        "slack": ChannelMapping("slack", OpenClawChannel.SLACK, "slack"),
        "discord": ChannelMapping("discord", OpenClawChannel.DISCORD, "discord"),
        "sms": ChannelMapping("sms", OpenClawChannel.SMS),
        "email": ChannelMapping("email", OpenClawChannel.EMAIL),
        "web": ChannelMapping("web", OpenClawChannel.WEB),
        "voice": ChannelMapping("voice", OpenClawChannel.VOICE),
        "teams": ChannelMapping("teams", OpenClawChannel.TEAMS),
        "matrix": ChannelMapping("matrix", OpenClawChannel.MATRIX),
    }

    # Default formatters
    DEFAULT_FORMATTERS: dict[str, type[ChannelFormatter]] = {
        "whatsapp": WhatsAppFormatter,
        "telegram": TelegramFormatter,
        "slack": SlackFormatter,
        "discord": DiscordFormatter,
    }

    def __init__(
        self,
        openclaw_endpoint: str = "http://localhost:8081",
        rbac_checker: RBACCheckerProtocol | None = None,
        audit_logger: AuditLoggerProtocol | None = None,
        approval_gate: ApprovalGateProtocol | None = None,
        sandbox_config: SandboxConfig | None = None,
        capability_filter: CapabilityFilter | None = None,
        protocol_translator: OpenClawProtocolTranslator | None = None,
        session_timeout_seconds: int = 3600,
        action_default_timeout: int = 60,
    ) -> None:
        """
        Initialize OpenClaw adapter.

        Args:
            openclaw_endpoint: OpenClaw runtime endpoint URL.
            rbac_checker: RBAC permission checker for authorization.
            audit_logger: Audit logging service.
            approval_gate: Approval gate service for sensitive operations.
            sandbox_config: Default sandbox configuration.
            capability_filter: Capability filter with policy rules.
            protocol_translator: Protocol translator instance.
            session_timeout_seconds: Default session timeout.
            action_default_timeout: Default action timeout in seconds.
        """
        self.openclaw_endpoint = openclaw_endpoint
        self.rbac_checker = rbac_checker
        self.audit_logger = audit_logger
        self.approval_gate = approval_gate
        self.sandbox_config = sandbox_config or SandboxConfig()
        self.capability_filter = capability_filter or CapabilityFilter()
        self.protocol_translator = protocol_translator or OpenClawProtocolTranslator()
        self.session_timeout_seconds = session_timeout_seconds
        self.action_default_timeout = action_default_timeout

        # Sandbox for task execution
        self.sandbox = OpenClawSandbox(
            config=self.sandbox_config,
            openclaw_endpoint=openclaw_endpoint,
        )

        # Session storage
        self._sessions: dict[str, OpenClawSession] = {}
        self._sessions_lock = asyncio.Lock()

        # Channel mappings and formatters
        self._channel_mappings: dict[str, ChannelMapping] = dict(self.DEFAULT_CHANNEL_MAPPINGS)
        self._formatters: dict[str, ChannelFormatter] = {
            name: cls() for name, cls in self.DEFAULT_FORMATTERS.items()
        }

        # Action handlers
        self._action_handlers: dict[str, Callable[..., Any]] = {}
        self._register_default_action_handlers()

        # Event callbacks
        self._session_callbacks: list[Callable[[OpenClawSession, str], Any]] = []
        self._action_callbacks: list[Callable[[ActionResult], Any]] = []

    # ========================================================================
    # Session Management
    # ========================================================================

    async def create_session(
        self,
        user_id: str,
        channel: OpenClawChannel | str,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        auth_context: AuthorizationContext | None = None,
    ) -> OpenClawSession:
        """
        Create a new OpenClaw session.

        Args:
            user_id: User identifier.
            channel: Communication channel.
            tenant_id: Optional tenant identifier.
            metadata: Session metadata.
            auth_context: Authorization context for permission checking.

        Returns:
            Created OpenClawSession.

        Raises:
            PermissionError: If user lacks session creation permission.
        """
        # Check permission if RBAC is enabled
        if self.rbac_checker and auth_context:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "openclaw.session.create",
            )
            if not has_permission:
                await self._log_audit(
                    OpenClawAuditEvents.TASK_BLOCKED,
                    auth_context.actor_id,
                    details={"reason": "permission_denied", "operation": "session.create"},
                )
                raise PermissionError("Permission denied: openclaw.session.create required")

        session_id = f"oc-sess-{uuid4().hex[:16]}"
        expires_at: datetime | None = None
        if self.session_timeout_seconds > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=self.session_timeout_seconds
            )

        session = OpenClawSession(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state=SessionState.ACTIVE,
            tenant_id=tenant_id,
            expires_at=expires_at,
            metadata=metadata or {},
        )

        async with self._sessions_lock:
            self._sessions[session_id] = session

        # Log session creation
        await self._log_audit(
            OpenClawAuditEvents.DEVICE_REGISTERED,
            user_id,
            session_id,
            {
                "channel": channel.value if isinstance(channel, OpenClawChannel) else channel,
                "tenant_id": tenant_id,
            },
        )

        # Notify callbacks
        for callback in self._session_callbacks:
            try:
                result = callback(session, "created")
                if asyncio.iscoroutine(result):
                    await result
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided session callback
                logger.error("Session callback error: %s", e)

        return session

    async def get_session(self, session_id: str) -> OpenClawSession | None:
        """
        Retrieve a session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            OpenClawSession or None if not found.
        """
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session and session.expires_at:
                if datetime.now(timezone.utc) > session.expires_at:
                    session.state = SessionState.EXPIRED
            return session

    async def update_session(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> OpenClawSession | None:
        """
        Update session metadata and context.

        Args:
            session_id: Session identifier.
            metadata: New metadata to merge.
            context: New context to merge.

        Returns:
            Updated session or None if not found.
        """
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            session.update_activity()

            if metadata:
                session.metadata.update(metadata)
            if context:
                session.context.update(context)

            return session

    async def close_session(
        self,
        session_id: str,
        reason: str = "user_closed",
    ) -> OpenClawSession | None:
        """
        Close and terminate a session.

        Args:
            session_id: Session identifier.
            reason: Reason for closing.

        Returns:
            Closed session or None if not found.
        """
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            session.state = SessionState.TERMINATED
            session.metadata["close_reason"] = reason

        # Log session closure
        await self._log_audit(
            OpenClawAuditEvents.DEVICE_UNREGISTERED,
            session.user_id,
            session_id,
            {"reason": reason},
        )

        # Notify callbacks
        for callback in self._session_callbacks:
            try:
                result = callback(session, "closed")
                if asyncio.iscoroutine(result):
                    await result
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided session callback
                logger.error("Session callback error: %s", e)

        return session

    async def list_sessions(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        channel: OpenClawChannel | str | None = None,
        state: SessionState | None = None,
    ) -> list[OpenClawSession]:
        """
        List sessions with optional filters.

        Args:
            user_id: Filter by user.
            tenant_id: Filter by tenant.
            channel: Filter by channel.
            state: Filter by state.

        Returns:
            List of matching sessions.
        """
        async with self._sessions_lock:
            sessions = list(self._sessions.values())

        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if tenant_id:
            sessions = [s for s in sessions if s.tenant_id == tenant_id]
        if channel:
            channel_value = channel.value if isinstance(channel, OpenClawChannel) else channel
            sessions = [
                s
                for s in sessions
                if (s.channel.value if isinstance(s.channel, OpenClawChannel) else s.channel)
                == channel_value
            ]
        if state:
            sessions = [s for s in sessions if s.state == state]

        return sessions

    def add_session_callback(
        self,
        callback: Callable[[OpenClawSession, str], Any],
    ) -> None:
        """Register a callback for session lifecycle events."""
        self._session_callbacks.append(callback)

    # ========================================================================
    # Channel Mapping
    # ========================================================================

    def register_channel_mapping(self, mapping: ChannelMapping) -> None:
        """
        Register a custom channel mapping.

        Args:
            mapping: Channel mapping configuration.
        """
        self._channel_mappings[mapping.aragora_channel] = mapping

    def get_channel_mapping(self, aragora_channel: str) -> ChannelMapping | None:
        """
        Get channel mapping for an Aragora channel.

        Args:
            aragora_channel: Aragora channel identifier.

        Returns:
            ChannelMapping or None if not found.
        """
        return self._channel_mappings.get(aragora_channel)

    def register_formatter(
        self,
        channel: str,
        formatter: ChannelFormatter,
    ) -> None:
        """
        Register a custom channel formatter.

        Args:
            channel: Channel identifier.
            formatter: Formatter instance.
        """
        self._formatters[channel] = formatter

    def get_formatter(self, channel: str) -> ChannelFormatter:
        """
        Get formatter for a channel.

        Args:
            channel: Channel identifier.

        Returns:
            ChannelFormatter (default if not found).
        """
        return self._formatters.get(channel, ChannelFormatter())

    def map_aragora_to_openclaw_channel(
        self,
        aragora_channel: str,
    ) -> OpenClawChannel | str:
        """
        Map Aragora channel to OpenClaw channel.

        Args:
            aragora_channel: Aragora channel identifier.

        Returns:
            OpenClaw channel.
        """
        mapping = self._channel_mappings.get(aragora_channel)
        if mapping:
            return mapping.openclaw_channel
        return aragora_channel

    def map_openclaw_to_aragora_channel(
        self,
        openclaw_channel: OpenClawChannel | str,
    ) -> str:
        """
        Map OpenClaw channel to Aragora channel.

        Args:
            openclaw_channel: OpenClaw channel.

        Returns:
            Aragora channel identifier.
        """
        openclaw_value = (
            openclaw_channel.value
            if isinstance(openclaw_channel, OpenClawChannel)
            else openclaw_channel
        )
        for aragora_ch, mapping in self._channel_mappings.items():
            mapping_value = (
                mapping.openclaw_channel.value
                if isinstance(mapping.openclaw_channel, OpenClawChannel)
                else mapping.openclaw_channel
            )
            if mapping_value == openclaw_value:
                return aragora_ch
        return openclaw_value

    # ========================================================================
    # Protocol Translation
    # ========================================================================

    def convert_aragora_request(
        self,
        request: AragoraRequest,
        auth_context: AuthorizationContext | None = None,
        tenant_context: TenantContext | None = None,
    ) -> OpenClawTask:
        """
        Convert Aragora request to OpenClaw task.

        Args:
            request: Aragora-format request.
            auth_context: Authorization context.
            tenant_context: Tenant context.

        Returns:
            OpenClawTask for execution.
        """
        return self.protocol_translator.aragora_to_openclaw(
            request,
            auth_context=auth_context,
            tenant_context=tenant_context,
        )

    def convert_openclaw_response(
        self,
        task: OpenClawTask,
        openclaw_result: dict[str, Any],
    ) -> AragoraResponse:
        """
        Convert OpenClaw result to Aragora response.

        Args:
            task: Original OpenClaw task.
            openclaw_result: Result from OpenClaw.

        Returns:
            AragoraResponse.
        """
        return self.protocol_translator.openclaw_to_aragora(task, openclaw_result)

    def convert_aragora_message(
        self,
        aragora_msg: dict[str, Any],
        session: OpenClawSession,
    ) -> OpenClawMessage:
        """
        Convert Aragora message format to OpenClaw message.

        Args:
            aragora_msg: Aragora message dictionary.
            session: Associated session.

        Returns:
            OpenClawMessage.
        """
        return OpenClawMessage(
            message_id=aragora_msg.get("message_id", str(uuid4())),
            type=aragora_msg.get("type", "text"),
            content=aragora_msg.get("content"),
            channel=session.channel,
            metadata=aragora_msg.get("metadata", {}),
            sender_id=aragora_msg.get("sender_id", session.user_id),
            attachments=aragora_msg.get("attachments", []),
            reply_to=aragora_msg.get("reply_to"),
            thread_id=aragora_msg.get("thread_id"),
        )

    def convert_openclaw_message(
        self,
        openclaw_msg: OpenClawMessage,
    ) -> dict[str, Any]:
        """
        Convert OpenClaw message to Aragora format.

        Args:
            openclaw_msg: OpenClaw message.

        Returns:
            Aragora message dictionary.
        """
        return {
            "message_id": openclaw_msg.message_id,
            "type": openclaw_msg.type,
            "content": openclaw_msg.content,
            "channel": self.map_openclaw_to_aragora_channel(openclaw_msg.channel),
            "metadata": openclaw_msg.metadata,
            "sender_id": openclaw_msg.sender_id,
            "timestamp": openclaw_msg.timestamp.isoformat(),
            "attachments": openclaw_msg.attachments,
            "reply_to": openclaw_msg.reply_to,
            "thread_id": openclaw_msg.thread_id,
        }

    # ========================================================================
    # Action Execution
    # ========================================================================

    async def execute_action(
        self,
        session_id: str,
        action: OpenClawAction,
        auth_context: AuthorizationContext | None = None,
    ) -> ActionResult:
        """
        Execute an OpenClaw action.

        Args:
            session_id: Session identifier.
            action: Action to execute.
            auth_context: Authorization context.

        Returns:
            ActionResult with execution details.
        """
        action_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        start_time = time.monotonic()

        # Validate session
        session = await self.get_session(session_id)
        if not session:
            return ActionResult(
                action_id=action_id,
                status=ActionStatus.FAILED,
                error="Session not found",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        if not session.is_active():
            return ActionResult(
                action_id=action_id,
                status=ActionStatus.FAILED,
                error=f"Session is {session.state.value}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        # Check permission if RBAC is enabled
        if self.rbac_checker and auth_context:
            action_type_value = (
                action.action_type.value
                if isinstance(action.action_type, OpenClawActionType)
                else action.action_type
            )
            permission = f"openclaw.action.{action_type_value}"
            has_permission = await self._check_permission(
                auth_context.actor_id,
                permission,
            )
            if not has_permission:
                await self._log_audit(
                    OpenClawAuditEvents.TASK_BLOCKED,
                    auth_context.actor_id,
                    action_id,
                    {"reason": "permission_denied", "action_type": action_type_value},
                )
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.FAILED,
                    error=f"Permission denied: {permission} required",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                )

        # Check capability filter
        action_capability = self._action_to_capability(action.action_type)
        if action_capability:
            check_result = self.capability_filter.check(action_capability)
            if not check_result.allowed and not check_result.requires_approval:
                await self._log_audit(
                    OpenClawAuditEvents.CAPABILITY_DENIED,
                    session.user_id,
                    action_id,
                    {"capability": action_capability},
                )
                return ActionResult(
                    action_id=action_id,
                    status=ActionStatus.FAILED,
                    error=f"Capability blocked: {action_capability}",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                )

        # Log action start
        await self._log_audit(
            OpenClawAuditEvents.TASK_SUBMITTED,
            session.user_id,
            action_id,
            {
                "action_type": action.action_type.value
                if isinstance(action.action_type, OpenClawActionType)
                else action.action_type,
                "session_id": session_id,
            },
        )

        # Execute action
        try:
            timeout = action.timeout or self.action_default_timeout
            result = await asyncio.wait_for(
                self._execute_action_impl(action, session),
                timeout=timeout,
            )
            execution_time_ms = int((time.monotonic() - start_time) * 1000)

            action_result = ActionResult(
                action_id=action_id,
                status=ActionStatus.COMPLETED,
                result=result,
                execution_time_ms=execution_time_ms,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

            # Log completion
            await self._log_audit(
                OpenClawAuditEvents.TASK_COMPLETED,
                session.user_id,
                action_id,
                {"execution_time_ms": execution_time_ms},
            )

        except asyncio.TimeoutError:
            action_result = ActionResult(
                action_id=action_id,
                status=ActionStatus.TIMEOUT,
                error=f"Action timed out after {action.timeout}s",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

            await self._log_audit(
                OpenClawAuditEvents.TASK_TIMEOUT,
                session.user_id,
                action_id,
            )

        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            logger.exception("Action %s failed", action_id)
            action_result = ActionResult(
                action_id=action_id,
                status=ActionStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

            await self._log_audit(
                OpenClawAuditEvents.TASK_FAILED,
                session.user_id,
                action_id,
                {"error": str(e)},
            )

        # Update session activity
        session.update_activity()

        # Notify callbacks
        for callback in self._action_callbacks:
            try:
                cb_result = callback(action_result)
                if asyncio.iscoroutine(cb_result):
                    await cb_result
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided action callback
                logger.error("Action callback error: %s", e)

        return action_result

    async def _execute_action_impl(
        self,
        action: OpenClawAction,
        session: OpenClawSession,
    ) -> Any:
        """Internal action execution implementation."""
        action_type_value = (
            action.action_type.value
            if isinstance(action.action_type, OpenClawActionType)
            else action.action_type
        )

        # Check for registered handler
        handler = self._action_handlers.get(action_type_value)
        if handler:
            result = handler(action, session)
            if asyncio.iscoroutine(result):
                return await result
            return result

        # Forward to OpenClaw runtime
        return await self._forward_action_to_openclaw(action, session)

    async def _forward_action_to_openclaw(
        self,
        action: OpenClawAction,
        session: OpenClawSession,
    ) -> Any:
        """Forward action to OpenClaw runtime via HTTP."""
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not available, returning mock result")
            return {"mock": True, "action_type": action.action_type}

        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(
                    f"{self.openclaw_endpoint}/api/v1/actions",
                    json={
                        "action": action.to_dict(),
                        "session_id": session.session_id,
                        "user_id": session.user_id,
                        "tenant_id": session.tenant_id,
                    },
                    timeout=aiohttp.ClientTimeout(total=action.timeout),
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise RuntimeError(f"OpenClaw returned {response.status}: {error_text}")

        except aiohttp.ClientError as e:
            raise RuntimeError(f"Failed to connect to OpenClaw: {e}")

    def _action_to_capability(
        self,
        action_type: OpenClawActionType | str,
    ) -> str | None:
        """Map action type to capability for filtering."""
        action_value = (
            action_type.value if isinstance(action_type, OpenClawActionType) else action_type
        )

        capability_map = {
            "browser_navigate": "browser_automation",
            "browser_click": "browser_automation",
            "browser_type": "browser_automation",
            "browser_screenshot": "browser_automation",
            "browser_scroll": "browser_automation",
            "browser_wait": "browser_automation",
            "browser_extract": "browser_automation",
            "file_read": "file_system_read",
            "file_write": "file_system_write",
            "file_delete": "file_system_write",
            "file_list": "file_system_read",
            "http_request": "network_external",
            "api_call": "network_external",
            "code_run": "code_execution",
            "code_eval": "code_execution",
            "db_query": "database_read",
            "db_execute": "database_write",
            "cron_create": "scheduler_manage",
            "cron_update": "scheduler_manage",
            "cron_delete": "scheduler_manage",
            "cron_list": "scheduler_read",
            "cron_trigger": "scheduler_manage",
        }

        return capability_map.get(action_value)

    def _register_default_action_handlers(self) -> None:
        """Register default action handlers."""
        # These are placeholder handlers - in production, they would
        # integrate with actual browser automation, file systems, etc.
        pass

    def register_action_handler(
        self,
        action_type: OpenClawActionType | str,
        handler: Callable[..., Any],
    ) -> None:
        """
        Register a custom action handler.

        Args:
            action_type: Action type to handle.
            handler: Handler function (sync or async).
        """
        action_value = (
            action_type.value if isinstance(action_type, OpenClawActionType) else action_type
        )
        self._action_handlers[action_value] = handler

    def add_action_callback(
        self,
        callback: Callable[[ActionResult], Any],
    ) -> None:
        """Register a callback for action completion events."""
        self._action_callbacks.append(callback)

    # ========================================================================
    # Message Sending
    # ========================================================================

    async def send_message(
        self,
        session_id: str,
        message: OpenClawMessage,
    ) -> dict[str, Any]:
        """
        Send a message through the appropriate channel.

        Args:
            session_id: Session identifier.
            message: Message to send.

        Returns:
            Sending result from channel.
        """
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if not session.is_active():
            raise ValueError(f"Session is {session.state.value}")

        # Get formatter for channel
        channel_value = (
            session.channel.value
            if isinstance(session.channel, OpenClawChannel)
            else session.channel
        )
        formatter = self.get_formatter(channel_value)

        # Format message for channel
        formatted = formatter.format_outgoing(message, session)

        # Send via OpenClaw (in production, this would call the actual channel API)
        result = await self._send_to_openclaw(session, formatted)

        # Update session activity
        session.update_activity()

        return result

    async def _send_to_openclaw(
        self,
        session: OpenClawSession,
        formatted_message: dict[str, Any],
    ) -> dict[str, Any]:
        """Send formatted message via OpenClaw."""
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not available, returning mock result")
            return {"mock": True, "sent": True}

        channel_value = (
            session.channel.value
            if isinstance(session.channel, OpenClawChannel)
            else session.channel
        )

        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(
                    f"{self.openclaw_endpoint}/api/v1/channels/{channel_value}/send",
                    json={
                        "message": formatted_message,
                        "session_id": session.session_id,
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise RuntimeError(f"Send failed: {response.status}: {error_text}")

        except aiohttp.ClientError as e:
            raise RuntimeError(f"Failed to send message: {e}")

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    async def _check_permission(
        self,
        actor_id: str,
        permission: str,
    ) -> bool:
        """Check if actor has permission."""
        if not self.rbac_checker:
            return True

        try:
            return await self.rbac_checker.check_permission_async(
                actor_id,
                permission,
            )
        except (OSError, RuntimeError, AttributeError) as e:
            # Fallback to sync check
            logger.debug(
                "Async permission check failed, falling back to sync: %s: %s", type(e).__name__, e
            )
            return self.rbac_checker.check_permission(actor_id, permission)

    async def _log_audit(
        self,
        event: OpenClawAuditEvents,
        actor_id: str,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log an audit event."""
        if not self.audit_logger:
            logger.info("Audit: %s actor=%s resource=%s", event.value, actor_id, resource_id)
            return

        severity = get_event_severity(event)

        try:
            await self.audit_logger.log_async(
                event.value,
                actor_id,
                resource_id,
                details,
                severity,
            )
        except (OSError, RuntimeError, AttributeError) as e:
            # Fallback to sync log
            logger.debug(
                "Async audit log failed, falling back to sync: %s: %s", type(e).__name__, e
            )
            self.audit_logger.log(
                event.value,
                actor_id,
                resource_id,
                details,
                severity,
            )


# Re-export OpenClawGatewayAdapter for backward compatibility.
# Imported after OpenClawAdapter is defined to avoid circular imports.
from .gateway_adapter import OpenClawGatewayAdapter


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # New adapter classes
    "OpenClawAdapter",
    "OpenClawGatewayAdapter",
    # Enums
    "OpenClawChannel",
    "OpenClawActionType",
    "SessionState",
    "ActionStatus",
    # Core dataclasses
    "OpenClawMessage",
    "OpenClawAction",
    "OpenClawSession",
    "ChannelMapping",
    "ActionResult",
    # Legacy dataclasses
    "GatewayResult",
    "DeviceRegistration",
    "DeviceHandle",
    "PluginInstallRequest",
    # Formatters
    "ChannelFormatter",
    "WhatsAppFormatter",
    "TelegramFormatter",
    "SlackFormatter",
    "DiscordFormatter",
    # Protocol interfaces
    "RBACCheckerProtocol",
    "AuditLoggerProtocol",
    "ApprovalGateProtocol",
]
