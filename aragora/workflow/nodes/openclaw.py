"""
OpenClaw Step for executing Enterprise Gateway actions in workflows.

Provides workflow steps that execute actions through the OpenClaw
Enterprise Gateway proxy with policy enforcement and audit logging:
- OpenClawActionStep: Execute shell, file, and browser actions
- OpenClawSessionStep: Manage proxy sessions within workflows
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

# Valid action types for the OpenClaw proxy
VALID_ACTION_TYPES = frozenset(
    {
        "shell",
        "file_read",
        "file_write",
        "file_delete",
        "browser",
        "screenshot",
        "api",
        "keyboard",
        "mouse",
    }
)


@dataclass
class OpenClawActionConfig:
    """Configuration for an OpenClaw action step."""

    action_type: str = "shell"
    session_id: str = ""
    command: str = ""
    path: str = ""
    content: str = ""
    text: str = ""
    x: float | None = None
    y: float | None = None
    url: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    require_approval: bool = False
    on_failure: str = "error"  # error, skip, retry


class OpenClawActionStep(BaseStep):
    """
    Execute an action through the OpenClaw Enterprise Gateway.

    Config options:
        action_type: str - Action type (shell, file_read, file_write, file_delete, browser, screenshot, api, keyboard, mouse)
        session_id: str - Session ID (or use {step.session_step.session_id} template)
        command: str - Shell command (for action_type=shell)
        path: str - File path (for file actions)
        content: str - File content (for action_type=file_write)
        text: str - Keyboard input text (for action_type=keyboard)
        x: float - Mouse X coordinate (for action_type=mouse)
        y: float - Mouse Y coordinate (for action_type=mouse)
        url: str - URL (for action_type=browser/screenshot)
        params: dict - Additional action parameters
        timeout_seconds: float - Action timeout (default 60)
        require_approval: bool - Whether to require manual approval
        on_failure: str - Failure handling: error, skip, retry

    Usage:
        step = OpenClawActionStep(
            name="List workspace files",
            config={
                "action_type": "shell",
                "session_id": "{step.create_session.session_id}",
                "command": "ls -la /workspace",
            }
        )
    """

    step_type = "openclaw_action"

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)
        cfg = config or {}
        self._step_config = OpenClawActionConfig(
            action_type=cfg.get("action_type", "shell"),
            session_id=cfg.get("session_id", ""),
            command=cfg.get("command", ""),
            path=cfg.get("path", ""),
            content=cfg.get("content", ""),
            text=cfg.get("text", ""),
            x=cfg.get("x"),
            y=cfg.get("y"),
            url=cfg.get("url", ""),
            params=cfg.get("params", {}),
            timeout_seconds=cfg.get("timeout_seconds", 60.0),
            require_approval=cfg.get("require_approval", False),
            on_failure=cfg.get("on_failure", "error"),
        )

    def validate_config(self) -> bool:
        """Validate that action_type is valid and required params are set."""
        cfg = self._step_config
        if cfg.action_type not in VALID_ACTION_TYPES:
            logger.error(
                "Invalid action_type '%s'. Valid types: %s",
                cfg.action_type,
                ", ".join(sorted(VALID_ACTION_TYPES)),
            )
            return False

        if cfg.action_type == "shell" and not cfg.command:
            logger.error("Shell action requires 'command' config")
            return False

        if cfg.action_type in ("file_read", "file_write", "file_delete") and not cfg.path:
            logger.error("File action '%s' requires 'path' config", cfg.action_type)
            return False

        if cfg.action_type == "browser" and not cfg.url:
            logger.error("Browser action requires 'url' config")
            return False

        if cfg.action_type == "screenshot" and not cfg.url:
            logger.error("Screenshot action requires 'url' config")
            return False

        if cfg.action_type == "keyboard":
            has_text = bool(cfg.text or cfg.content or cfg.params.get("text"))
            if not has_text:
                logger.error("Keyboard action requires 'text' config")
                return False

        if cfg.action_type == "mouse":
            x_val = cfg.x if cfg.x is not None else cfg.params.get("x")
            y_val = cfg.y if cfg.y is not None else cfg.params.get("y")
            if x_val is None or y_val is None:
                logger.error("Mouse action requires 'x' and 'y' config")
                return False

        return True

    async def execute(self, context: WorkflowContext) -> dict[str, Any]:
        """Execute an action through the OpenClaw proxy."""
        config = {**self._config, **context.current_step_config}
        cfg = self._step_config

        # Resolve template variables in config values
        action_type = self._resolve(config.get("action_type", cfg.action_type), context)
        session_id = self._resolve(config.get("session_id", cfg.session_id), context)
        command = self._resolve(config.get("command", cfg.command), context)
        path = self._resolve(config.get("path", cfg.path), context)
        content = self._resolve(config.get("content", cfg.content), context)
        text = self._resolve(config.get("text", cfg.text), context)
        x = config.get("x", cfg.x)
        y = config.get("y", cfg.y)
        url = self._resolve(config.get("url", cfg.url), context)
        params = config.get("params", cfg.params)

        if not session_id:
            return {
                "success": False,
                "error": "session_id is required. Use a session step output or provide directly.",
                "action_type": action_type,
            }

        # Build action payload for proxy
        metadata = {
            "workflow_id": context.workflow_id,
            "step_name": self.name,
        }
        if params:
            metadata.update(params)
        if action_type == "file_write":
            metadata.setdefault("content", content)
        if action_type == "keyboard":
            metadata.setdefault("text", text or content)
        if action_type == "mouse":
            if x is not None:
                metadata.setdefault("x", x)
            if y is not None:
                metadata.setdefault("y", y)

        input_payload: dict[str, Any] = {}
        if action_type == "shell" and command:
            input_payload["command"] = command
        if action_type in ("file_read", "file_write", "file_delete") and path:
            input_payload["path"] = path
        if action_type == "file_write" and content:
            input_payload["content"] = content
        if action_type in ("browser", "screenshot", "api") and url:
            input_payload["url"] = url
        if action_type == "keyboard":
            payload_text = text or content
            if payload_text:
                input_payload["text"] = payload_text
        if action_type == "mouse":
            if x is not None:
                input_payload["x"] = x
            if y is not None:
                input_payload["y"] = y
        if isinstance(params, dict) and params:
            input_payload.update(params)

        try:
            proxy = await self._get_proxy()
            try:
                result = await proxy.execute_action(
                    session_id=session_id,
                    action_type=action_type,
                    input=input_payload,
                    metadata=metadata,
                )
            except TypeError as exc:
                if "input" not in str(exc):
                    raise
                result = await proxy.execute_action(
                    session_id=session_id,
                    action_type=action_type,
                    path=path if action_type.startswith("file") else None,
                    command=command if action_type == "shell" else None,
                    url=url if action_type in ("browser", "screenshot", "api") else None,
                    metadata=metadata,
                )

            if hasattr(result, "to_dict"):
                result_data = result.to_dict()
            elif isinstance(result, dict):
                result_data = result
            else:
                result_data = {"raw": str(result)}

            success = result_data.get("success", True)
            if not success and cfg.on_failure == "skip":
                logger.warning("Action failed but on_failure=skip: %s", result_data.get("error"))
                return {
                    "success": False,
                    "skipped": True,
                    "action_type": action_type,
                    "error": result_data.get("error"),
                }

            return {
                "success": success,
                "action_type": action_type,
                "action_id": result_data.get("action_id", result_data.get("id", "")),
                "result": result_data.get("result"),
                "execution_time_ms": result_data.get("execution_time_ms", 0),
                "audit_id": result_data.get("audit_id"),
                "requires_approval": result_data.get("requires_approval", False),
            }

        except ImportError:
            return {
                "success": False,
                "error": "OpenClaw gateway module not available",
                "action_type": action_type,
            }
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, AttributeError) as e:
            logger.error("OpenClaw action failed: %s", e)
            if cfg.on_failure == "skip":
                return {
                    "success": False,
                    "skipped": True,
                    "action_type": action_type,
                    "error": "OpenClaw action failed",
                }
            return {
                "success": False,
                "error": "OpenClaw action failed",
                "action_type": action_type,
            }

    async def _get_proxy(self) -> Any:
        """Get or create the OpenClaw proxy."""
        from aragora.compat.openclaw_policy import create_enterprise_policy
        from aragora.compat.openclaw_proxy import OpenClawSecureProxy

        return OpenClawSecureProxy(policy=create_enterprise_policy())

    def _resolve(self, value: str, context: WorkflowContext) -> str:
        """Resolve template variables in a string value."""
        if not value or "{" not in value:
            return value

        try:
            # Replace {step.<step_id>.<field>} patterns
            import re

            def _replace_match(m: re.Match) -> str:
                ref = m.group(1)
                parts = ref.split(".", 2)
                if len(parts) >= 2 and parts[0] == "step":
                    step_id = parts[1]
                    step_output = context.get_step_output(step_id)
                    if step_output and len(parts) == 3:
                        field_name = parts[2]
                        if isinstance(step_output, dict):
                            return str(step_output.get(field_name, m.group(0)))
                    elif step_output:
                        return str(step_output)
                elif len(parts) >= 1 and parts[0] == "input":
                    key = parts[1] if len(parts) > 1 else None
                    if key:
                        return str(context.get_input(key, m.group(0)))
                return m.group(0)

            return re.sub(r"\{([^}]+)\}", _replace_match, value)
        except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("Template resolution failed for %r: %s", value, exc)
            return value


class OpenClawSessionStep(BaseStep):
    """
    Manage OpenClaw proxy sessions within workflows.

    Creates or ends a session. Output includes session_id for use
    by subsequent OpenClawActionStep instances.

    Config options:
        operation: str - "create" or "end"
        session_id: str - Session ID (for operation=end)
        workspace_id: str - Workspace directory (default /workspace)
        roles: list[str] - User roles for the session

    Usage:
        step = OpenClawSessionStep(
            name="Create sandbox session",
            config={
                "operation": "create",
                "workspace_id": "/workspace/project",
                "roles": ["developer"],
            }
        )
    """

    step_type = "openclaw_session"

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)

    def validate_config(self) -> bool:
        """Validate session step configuration."""
        operation = self._config.get("operation", "create")
        if operation not in ("create", "end"):
            logger.error("Invalid operation '%s'. Must be 'create' or 'end'.", operation)
            return False
        if operation == "end" and not self._config.get("session_id"):
            logger.error("End operation requires 'session_id' config")
            return False
        return True

    async def execute(self, context: WorkflowContext) -> dict[str, Any]:
        """Create or end an OpenClaw session."""
        config = {**self._config, **context.current_step_config}
        operation = config.get("operation", "create")

        try:
            proxy = await self._get_proxy()

            if operation == "create":
                return await self._create_session(proxy, config, context)
            elif operation == "end":
                return await self._end_session(proxy, config, context)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}

        except ImportError:
            return {
                "success": False,
                "error": "OpenClaw gateway module not available",
                "operation": operation,
            }
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, AttributeError) as e:
            logger.error("OpenClaw session operation failed: %s", e)
            return {
                "success": False,
                "error": "OpenClaw session operation failed",
                "operation": operation,
            }

    async def _create_session(
        self, proxy: Any, config: dict[str, Any], context: WorkflowContext
    ) -> dict[str, Any]:
        """Create a new proxy session."""
        user_id = config.get("user_id", context.metadata.get("user_id", "workflow"))
        tenant_id = config.get("tenant_id", context.metadata.get("tenant_id", "default"))
        workspace_id = config.get("workspace_id", "/workspace")
        roles = config.get("roles", ["user"])

        session = await proxy.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            roles=roles,
        )

        session_id = session.session_id if hasattr(session, "session_id") else str(session)

        logger.info("Created OpenClaw session %s for workflow %s", session_id, context.workflow_id)
        return {
            "success": True,
            "operation": "create",
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }

    async def _end_session(
        self, proxy: Any, config: dict[str, Any], context: WorkflowContext
    ) -> dict[str, Any]:
        """End an existing proxy session."""
        session_id = config.get("session_id", "")
        if not session_id:
            return {"success": False, "error": "session_id is required for end operation"}

        # Resolve template variable
        if "{" in session_id:
            session_id = OpenClawActionStep._resolve(
                OpenClawActionStep.__new__(OpenClawActionStep), session_id, context
            )

        await proxy.end_session(session_id)

        logger.info("Ended OpenClaw session %s", session_id)
        return {
            "success": True,
            "operation": "end",
            "session_id": session_id,
        }

    async def _get_proxy(self) -> Any:
        """Get or create the OpenClaw proxy."""
        from aragora.compat.openclaw_policy import create_enterprise_policy
        from aragora.compat.openclaw_proxy import OpenClawSecureProxy

        return OpenClawSecureProxy(policy=create_enterprise_policy())


def register_openclaw_steps() -> None:
    """Register OpenClaw step types with the workflow engine."""
    try:
        from aragora.workflow.nodes import register_step_type

        register_step_type("openclaw_action", OpenClawActionStep)
        register_step_type("openclaw_session", OpenClawSessionStep)
        logger.debug("Registered OpenClaw step types")
    except ImportError:
        logger.debug("Workflow node registration not available")
