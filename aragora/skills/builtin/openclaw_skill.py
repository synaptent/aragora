"""
OpenClaw Skill.

Wraps OpenClaw actions as an Aragora skill, routing all operations
through the enterprise gateway proxy with full audit logging.

Supports shell execution, file operations, and browser control
with policy enforcement and approval workflows.
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import (
    Skill,
    SkillCapability,
    SkillContext,
    SkillManifest,
    SkillResult,
)

logger = logging.getLogger(__name__)

# Mapping from OpenClaw action names to ActionType string values
_ACTION_TYPE_MAP = {
    "shell": "shell",
    "file_read": "file_read",
    "file_write": "file_write",
    "file_delete": "file_delete",
    "browser": "browser",
    "screenshot": "screenshot",
    "api": "api",
}


class OpenClawSkill(Skill):
    """
    Skill that routes actions through the OpenClaw Enterprise Gateway.

    All actions go through the secure proxy, which enforces:
    - Policy-based access control
    - RBAC permissions
    - Rate limiting
    - Audit logging
    - Approval workflows for sensitive operations

    Input format:
        {"action": "shell", "command": "ls -la /workspace"}
        {"action": "file_read", "path": "/workspace/README.md"}
        {"action": "file_write", "path": "/workspace/out.txt", "content": "hello"}
        {"action": "browser", "url": "https://example.com"}
    """

    def __init__(
        self,
        proxy: Any | None = None,
        default_workspace: str = "/workspace",
    ):
        """
        Initialize OpenClaw skill.

        Args:
            proxy: Optional OpenClawSecureProxy instance. If not provided,
                   one will be created with default enterprise policy.
            default_workspace: Default workspace directory for sessions.
        """
        self._proxy = proxy
        self._default_workspace = default_workspace
        self._sessions: dict[str, str] = {}  # context_key -> session_id

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="openclaw",
            version="1.0.0",
            description="Execute actions through the OpenClaw Enterprise Gateway with policy enforcement",
            capabilities=[
                SkillCapability.SHELL_EXECUTION,
                SkillCapability.READ_LOCAL,
                SkillCapability.WRITE_LOCAL,
                SkillCapability.WEB_FETCH,
                SkillCapability.CODE_EXECUTION,
            ],
            input_schema={
                "action": {
                    "type": "string",
                    "description": "Action type: shell, file_read, file_write, file_delete, browser, screenshot",
                    "required": True,
                },
                "command": {
                    "type": "string",
                    "description": "Shell command (for action=shell)",
                },
                "path": {
                    "type": "string",
                    "description": "File path (for file actions)",
                },
                "content": {
                    "type": "string",
                    "description": "File content (for action=file_write)",
                },
                "url": {
                    "type": "string",
                    "description": "URL (for action=browser)",
                },
            },
            tags=["openclaw", "enterprise", "gateway", "security"],
            debate_compatible=True,
            max_execution_time_seconds=60.0,
            rate_limit_per_minute=60,
        )

    async def execute(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Execute an action through the OpenClaw proxy."""
        action = input_data.get("action", "")
        if not action:
            return SkillResult.create_failure(
                "Action is required (shell, file_read, file_write, browser, etc.)",
                error_code="missing_action",
            )

        if action not in _ACTION_TYPE_MAP:
            return SkillResult.create_failure(
                f"Unknown action type: {action}. Supported: {', '.join(_ACTION_TYPE_MAP.keys())}",
                error_code="invalid_action",
            )

        proxy = await self._get_proxy()
        session_id = await self._ensure_session(proxy, context)

        try:
            if action == "shell":
                return await self._execute_shell(proxy, session_id, input_data)
            elif action == "file_read":
                return await self._execute_file_read(proxy, session_id, input_data)
            elif action == "file_write":
                return await self._execute_file_write(proxy, session_id, input_data)
            elif action == "file_delete":
                return await self._execute_file_delete(proxy, session_id, input_data)
            elif action in ("browser", "screenshot"):
                return await self._execute_browser(proxy, session_id, input_data)
            else:
                return SkillResult.create_failure(f"Unhandled action: {action}")

        except (RuntimeError, ValueError, OSError, ConnectionError) as e:
            logger.exception("OpenClaw action failed: %s", e)
            return SkillResult.create_failure(f"Action failed: {e}")

    async def _get_proxy(self) -> Any:
        """Get or create the proxy instance."""
        if self._proxy is not None:
            return self._proxy

        from aragora.compat.openclaw_policy import create_enterprise_policy
        from aragora.compat.openclaw_proxy import OpenClawSecureProxy

        self._proxy = OpenClawSecureProxy(policy=create_enterprise_policy())
        return self._proxy

    async def _ensure_session(self, proxy: Any, context: SkillContext) -> str:
        """Ensure a proxy session exists for this context."""
        context_key = f"{context.user_id or 'anon'}:{context.tenant_id or 'default'}"

        if context_key in self._sessions:
            return self._sessions[context_key]

        session = await proxy.create_session(
            user_id=context.user_id or "anonymous",
            tenant_id=context.tenant_id or "default",
            workspace_id=self._default_workspace,
            roles=getattr(context, "roles", ["user"]),
        )
        self._sessions[context_key] = session.session_id
        return session.session_id

    async def _execute_shell(
        self, proxy: Any, session_id: str, input_data: dict[str, Any]
    ) -> SkillResult:
        """Execute a shell command."""
        command = input_data.get("command", "")
        if not command:
            return SkillResult.create_failure(
                "Command is required for shell action",
                error_code="missing_command",
            )

        result = await proxy.execute_action(
            session_id=session_id,
            action_type="shell",
            command=command,
        )
        return self._to_skill_result(result, "shell")

    async def _execute_file_read(
        self, proxy: Any, session_id: str, input_data: dict[str, Any]
    ) -> SkillResult:
        """Execute a file read."""
        path = input_data.get("path", "")
        if not path:
            return SkillResult.create_failure(
                "Path is required for file_read action",
                error_code="missing_path",
            )

        result = await proxy.execute_action(
            session_id=session_id,
            action_type="file_read",
            path=path,
        )
        return self._to_skill_result(result, "file_read")

    async def _execute_file_write(
        self, proxy: Any, session_id: str, input_data: dict[str, Any]
    ) -> SkillResult:
        """Execute a file write."""
        path = input_data.get("path", "")
        content = input_data.get("content", "")
        if not path:
            return SkillResult.create_failure(
                "Path is required for file_write action",
                error_code="missing_path",
            )

        result = await proxy.execute_action(
            session_id=session_id,
            action_type="file_write",
            path=path,
            content=content,
        )
        return self._to_skill_result(result, "file_write")

    async def _execute_file_delete(
        self, proxy: Any, session_id: str, input_data: dict[str, Any]
    ) -> SkillResult:
        """Execute a file delete."""
        path = input_data.get("path", "")
        if not path:
            return SkillResult.create_failure(
                "Path is required for file_delete action",
                error_code="missing_path",
            )

        result = await proxy.execute_action(
            session_id=session_id,
            action_type="file_delete",
            path=path,
        )
        return self._to_skill_result(result, "file_delete")

    async def _execute_browser(
        self, proxy: Any, session_id: str, input_data: dict[str, Any]
    ) -> SkillResult:
        """Execute a browser action."""
        url = input_data.get("url", "")
        if not url:
            return SkillResult.create_failure(
                "URL is required for browser action",
                error_code="missing_url",
            )

        action = input_data.get("action", "browser")
        result = await proxy.execute_action(
            session_id=session_id,
            action_type=action,
            url=url,
        )
        return self._to_skill_result(result, action)

    @staticmethod
    def _to_skill_result(proxy_result: Any, action: str) -> SkillResult:
        """Convert proxy result to SkillResult."""
        if proxy_result.requires_approval:
            return SkillResult.create_failure(
                f"Action requires approval (approval_id: {proxy_result.approval_id})",
                error_code="requires_approval",
            )

        if not proxy_result.success:
            error = (
                proxy_result.error
                or f"Action denied by policy ({proxy_result.policy_decision.value})"
            )
            return SkillResult.create_failure(error, error_code="action_denied")

        return SkillResult.create_success(
            {
                "action": action,
                "action_id": proxy_result.action_id,
                "result": proxy_result.result,
                "execution_time_ms": proxy_result.execution_time_ms,
                "audit_id": proxy_result.audit_id,
            },
            provider="openclaw",
        )


# Skill instance for auto-registration
SKILLS = [OpenClawSkill()]
