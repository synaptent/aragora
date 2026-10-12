"""
Legacy OpenClaw Gateway Adapter.

Backward-compatible adapter providing task execution, device management,
and plugin management via the OpenClaw gateway. Inherits from the
primary OpenClawAdapter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from .audit import OpenClawAuditEvents
from .capabilities import CapabilityCheckResult, CapabilityFilter
from .models import (
    DeviceHandle,
    DeviceRegistration,
    GatewayResult,
    PluginInstallRequest,
)
from .protocol import (
    AragoraRequest,
    AuthorizationContext,
    TenantContext,
)
from .sandbox import OpenClawSandbox, SandboxConfig, SandboxStatus

logger = logging.getLogger(__name__)


# Import here (not at top) to keep it clear this is a subclass relationship.
# No circular import since adapter.py does NOT import gateway_adapter.py.
from .adapter import OpenClawAdapter


class OpenClawGatewayAdapter(OpenClawAdapter):
    """
    Legacy gateway adapter for backward compatibility.

    This class maintains the original OpenClawGatewayAdapter API while
    inheriting from the new OpenClawAdapter implementation.

    Usage:
        adapter = OpenClawGatewayAdapter(
            openclaw_endpoint="http://localhost:8081",
            rbac_checker=checker,
            audit_logger=logger,
        )

        result = await adapter.execute_task(
            request=AragoraRequest(content="Generate a summary"),
            auth_context=ctx,
        )
    """

    async def execute_task(
        self,
        request: AragoraRequest,
        auth_context: AuthorizationContext,
        tenant_context: TenantContext | None = None,
        sandbox_override: SandboxConfig | None = None,
    ) -> GatewayResult:
        """
        Execute task via OpenClaw with full security enforcement.

        Args:
            request: Aragora-format request
            auth_context: Authorization context
            tenant_context: Optional tenant context for isolation
            sandbox_override: Optional sandbox config override

        Returns:
            GatewayResult with execution details
        """
        request_id = str(uuid4())

        # Check RBAC permission
        if self.rbac_checker:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "gateway.execute",
            )
            if not has_permission:
                await self._log_audit(
                    OpenClawAuditEvents.TASK_BLOCKED,
                    auth_context.actor_id,
                    request_id,
                    {"reason": "permission_denied"},
                )
                return GatewayResult(
                    success=False,
                    request_id=request_id,
                    error="Permission denied: gateway.execute required",
                    blocked_reason="permission_denied",
                )

        # Check capabilities
        blocked_capabilities: list[str] = []
        approval_needed: list[CapabilityCheckResult] = []

        for capability in request.capabilities:
            check_result = self.capability_filter.check(capability)
            if not check_result.allowed:
                if check_result.requires_approval:
                    approval_needed.append(check_result)
                else:
                    blocked_capabilities.append(capability)

        # Block if any capabilities are not allowed
        if blocked_capabilities:
            await self._log_audit(
                OpenClawAuditEvents.CAPABILITY_DENIED,
                auth_context.actor_id,
                request_id,
                {"blocked_capabilities": blocked_capabilities},
            )
            return GatewayResult(
                success=False,
                request_id=request_id,
                error=f"Capabilities blocked: {blocked_capabilities}",
                blocked_reason="capability_blocked",
            )

        # Check approval gates for capabilities that require them
        if approval_needed and self.approval_gate:
            for check_result in approval_needed:
                if check_result.approval_gate:
                    approved, reason = await self.approval_gate.check_approval(
                        check_result.approval_gate,
                        auth_context.actor_id,
                        request_id,
                    )
                    if not approved:
                        await self._log_audit(
                            OpenClawAuditEvents.CAPABILITY_DENIED,
                            auth_context.actor_id,
                            request_id,
                            {
                                "capability": check_result.capability,
                                "approval_gate": check_result.approval_gate,
                                "reason": reason,
                            },
                        )
                        return GatewayResult(
                            success=False,
                            request_id=request_id,
                            error=f"Approval required for {check_result.capability}: {reason}",
                            blocked_reason="approval_required",
                        )

        # Log task submission
        await self._log_audit(
            OpenClawAuditEvents.TASK_SUBMITTED,
            auth_context.actor_id,
            request_id,
            {
                "request_type": request.request_type,
                "capabilities": request.capabilities,
                "plugins": request.plugins,
            },
        )

        # Translate to OpenClaw format
        task = self.protocol_translator.aragora_to_openclaw(
            request,
            auth_context=auth_context,
            tenant_context=tenant_context,
        )

        # Override task ID with our request ID for tracing
        task.id = request_id

        # Execute in sandbox
        sandbox_result = await self.sandbox.execute(
            task,
            config_override=sandbox_override,
        )

        # Log completion
        if sandbox_result.status == SandboxStatus.COMPLETED:
            await self._log_audit(
                OpenClawAuditEvents.TASK_COMPLETED,
                auth_context.actor_id,
                request_id,
                {
                    "execution_time_ms": sandbox_result.execution_time_ms,
                    "memory_used_mb": sandbox_result.memory_used_mb,
                },
            )
        elif sandbox_result.status == SandboxStatus.TIMEOUT:
            await self._log_audit(
                OpenClawAuditEvents.TASK_TIMEOUT,
                auth_context.actor_id,
                request_id,
                {"error": sandbox_result.error},
            )
        elif sandbox_result.status == SandboxStatus.POLICY_VIOLATION:
            await self._log_audit(
                OpenClawAuditEvents.SANDBOX_VIOLATION,
                auth_context.actor_id,
                request_id,
                {"error": sandbox_result.error},
            )
        else:
            await self._log_audit(
                OpenClawAuditEvents.TASK_FAILED,
                auth_context.actor_id,
                request_id,
                {"error": sandbox_result.error},
            )

        # Convert to Aragora response
        response = self.protocol_translator.openclaw_to_aragora(
            task,
            {
                "status": sandbox_result.status.value,
                "result": sandbox_result.output,
                "error": sandbox_result.error,
                "execution_time_ms": sandbox_result.execution_time_ms,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return GatewayResult(
            success=sandbox_result.status == SandboxStatus.COMPLETED,
            request_id=request_id,
            response=response,
            error=sandbox_result.error,
            metadata={
                "sandbox_status": sandbox_result.status.value,
                "execution_time_ms": sandbox_result.execution_time_ms,
            },
        )

    async def register_device(
        self,
        device: DeviceRegistration,
        auth_context: AuthorizationContext,
    ) -> GatewayResult:
        """
        Register a device with the OpenClaw gateway.

        Args:
            device: Device registration details
            auth_context: Authorization context

        Returns:
            GatewayResult with device handle
        """
        # Check RBAC permission
        if self.rbac_checker:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "gateway.device.register",
            )
            if not has_permission:
                return GatewayResult(
                    success=False,
                    request_id=device.device_id,
                    error="Permission denied: gateway.device.register required",
                    blocked_reason="permission_denied",
                )

        # Log registration
        await self._log_audit(
            OpenClawAuditEvents.DEVICE_REGISTERED,
            auth_context.actor_id,
            device.device_id,
            {
                "device_name": device.device_name,
                "device_type": device.device_type,
                "capabilities": device.capabilities,
            },
        )

        # Create device handle
        handle = DeviceHandle(
            device_id=device.device_id,
            registration_id=str(uuid4()),
            registered_at=datetime.now(timezone.utc),
        )

        return GatewayResult(
            success=True,
            request_id=device.device_id,
            metadata={"device_handle": handle.__dict__},
        )

    async def unregister_device(
        self,
        device_id: str,
        auth_context: AuthorizationContext,
    ) -> GatewayResult:
        """Unregister a device from the gateway."""
        if self.rbac_checker:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "gateway.device.unregister",
            )
            if not has_permission:
                return GatewayResult(
                    success=False,
                    request_id=device_id,
                    error="Permission denied",
                    blocked_reason="permission_denied",
                )

        await self._log_audit(
            OpenClawAuditEvents.DEVICE_UNREGISTERED,
            auth_context.actor_id,
            device_id,
        )

        return GatewayResult(
            success=True,
            request_id=device_id,
        )

    async def install_plugin(
        self,
        plugin: PluginInstallRequest,
        auth_context: AuthorizationContext,
        tenant_context: TenantContext | None = None,
    ) -> GatewayResult:
        """
        Install a plugin via the OpenClaw gateway.

        Args:
            plugin: Plugin installation request
            auth_context: Authorization context
            tenant_context: Optional tenant context

        Returns:
            GatewayResult with installation status
        """
        # Check RBAC permission
        if self.rbac_checker:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "gateway.plugin.install",
            )
            if not has_permission:
                await self._log_audit(
                    OpenClawAuditEvents.PLUGIN_BLOCKED,
                    auth_context.actor_id,
                    plugin.plugin_id,
                    {"reason": "permission_denied"},
                )
                return GatewayResult(
                    success=False,
                    request_id=plugin.plugin_id,
                    error="Permission denied: gateway.plugin.install required",
                    blocked_reason="permission_denied",
                )

        # Check plugin allowlist if enabled
        if self.sandbox_config.plugin_allowlist_mode:
            if plugin.plugin_id not in self.sandbox_config.allowed_plugins:
                await self._log_audit(
                    OpenClawAuditEvents.PLUGIN_BLOCKED,
                    auth_context.actor_id,
                    plugin.plugin_id,
                    {"reason": "not_in_allowlist"},
                )
                return GatewayResult(
                    success=False,
                    request_id=plugin.plugin_id,
                    error=f"Plugin '{plugin.plugin_id}' not in allowlist",
                    blocked_reason="plugin_not_allowed",
                )

        # Log installation
        await self._log_audit(
            OpenClawAuditEvents.PLUGIN_INSTALLED,
            auth_context.actor_id,
            plugin.plugin_id,
            {
                "plugin_name": plugin.plugin_name,
                "version": plugin.version,
                "source": plugin.source,
            },
        )

        return GatewayResult(
            success=True,
            request_id=plugin.plugin_id,
            metadata={"installed_at": datetime.now(timezone.utc).isoformat()},
        )

    async def uninstall_plugin(
        self,
        plugin_id: str,
        auth_context: AuthorizationContext,
    ) -> GatewayResult:
        """Uninstall a plugin from the gateway."""
        if self.rbac_checker:
            has_permission = await self._check_permission(
                auth_context.actor_id,
                "gateway.plugin.uninstall",
            )
            if not has_permission:
                return GatewayResult(
                    success=False,
                    request_id=plugin_id,
                    error="Permission denied",
                    blocked_reason="permission_denied",
                )

        await self._log_audit(
            OpenClawAuditEvents.PLUGIN_UNINSTALLED,
            auth_context.actor_id,
            plugin_id,
        )

        return GatewayResult(
            success=True,
            request_id=plugin_id,
        )

    def update_sandbox_config(self, config: SandboxConfig) -> None:
        """Update default sandbox configuration."""
        self.sandbox_config = config
        self.sandbox = OpenClawSandbox(
            config=config,
            openclaw_endpoint=self.openclaw_endpoint,
        )

    def update_capability_filter(self, filter_config: CapabilityFilter) -> None:
        """Update capability filter configuration."""
        self.capability_filter = filter_config

    def enable_tenant_capability(
        self,
        capability: str,
        tenant_context: TenantContext,
    ) -> None:
        """Enable a capability for a specific tenant."""
        self.capability_filter.enable_for_tenant(capability)
        tenant_context.enabled_capabilities.add(capability)

    def add_plugin_to_allowlist(self, plugin_id: str) -> None:
        """Add a plugin to the allowed plugins list."""
        if plugin_id not in self.sandbox_config.allowed_plugins:
            self.sandbox_config.allowed_plugins.append(plugin_id)
