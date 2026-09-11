"""
Admin Namespace API

Provides methods for platform administration operations.
Requires admin role for all operations.

Features:
- Organization and user listing
- Platform statistics and system metrics
- Nomic loop control
- Security operations
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


def _format_bulk_feature_flag_rollback_failures(rollback_failures: dict[str, str]) -> str:
    return "; ".join(f"{flag_name}: {message}" for flag_name, message in rollback_failures.items())


class AdminAPI:
    """
    Synchronous Admin API.

    Provides methods for platform administration:
    - Organization and user listing
    - Platform statistics and system metrics
    - Revenue analytics
    - Nomic loop control
    - Security operations

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai", api_key="admin-key")
        >>> stats = client.admin.get_stats()
        >>> print(f"{stats['total_organizations']} orgs, {stats['active_debates']} debates")
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # ===========================================================================
    # Organizations and Users
    # ===========================================================================

    def list_organizations(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List all organizations with pagination.

        Args:
            limit: Maximum number of organizations to return
            offset: Number of organizations to skip

        Returns:
            Dict with organizations list, total count, and pagination info
        """
        return self._client.request(
            "GET",
            "/api/v1/admin/organizations",
            params={"limit": limit, "offset": offset},
        )

    def list_users(
        self,
        limit: int = 20,
        offset: int = 0,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """
        List all users with pagination.

        Args:
            limit: Maximum number of users to return
            offset: Number of users to skip
            org_id: Filter by organization ID

        Returns:
            Dict with users list, total count, and pagination info
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if org_id:
            params["org_id"] = org_id

        return self._client.request("GET", "/api/v1/admin/users", params=params)

    # ===========================================================================
    # Platform Statistics
    # ===========================================================================

    def get_stats(self) -> dict[str, Any]:
        """
        Get platform-wide statistics.

        Returns:
            Dict with total_organizations, total_users, active_debates, etc.
        """
        return self._client.request("GET", "/api/v1/admin/stats")

    def get_revenue(self) -> dict[str, Any]:
        """
        Get revenue analytics.

        Returns:
            Dict with mrr, arr, revenue_this_month, growth_rate, etc.
        """
        return self._client.request("GET", "/api/v1/admin/revenue")

    # ===========================================================================
    # Nomic Loop Control
    # ===========================================================================

    def get_nomic_status(self) -> dict[str, Any]:
        """
        Get the current Nomic loop status.

        Returns:
            Dict with running, current_phase, current_cycle, health, etc.
        """
        return self._client.request("GET", "/api/v1/admin/nomic/status")

    def reset_nomic(self) -> dict[str, Any]:
        """
        Reset the Nomic loop to initial state.

        Returns:
            Dict with success status
        """
        return self._client.request("POST", "/api/v1/admin/nomic/reset")

    def pause_nomic(self) -> dict[str, Any]:
        """
        Pause the Nomic loop.

        Returns:
            Dict with success status
        """
        return self._client.request("POST", "/api/v1/admin/nomic/pause")

    def resume_nomic(self) -> dict[str, Any]:
        """
        Resume a paused Nomic loop.

        Returns:
            Dict with success status
        """
        return self._client.request("POST", "/api/v1/admin/nomic/resume")

    # ===========================================================================
    # Security Operations
    # ===========================================================================

    def get_security_status(self) -> dict[str, Any]:
        """
        Get security status overview.

        Returns:
            Dict with encryption_enabled, mfa_enforcement, audit_logging, etc.
        """
        return self._client.request("GET", "/api/v1/admin/security/status")

    def get_security_health(self) -> dict[str, Any]:
        """
        Get security health check results.

        Returns:
            Dict with healthy status and checks map
        """
        return self._client.request("GET", "/api/v1/admin/security/health")

    def list_security_keys(self) -> dict[str, Any]:
        """
        List all security keys.

        Returns:
            Dict with keys array
        """
        return self._client.request("GET", "/api/v1/admin/security/keys")

    # ===========================================================================
    # Diagnostics
    # ===========================================================================

    def get_handler_diagnostics(self) -> dict[str, Any]:
        """
        Get handler diagnostics information.

        GET /api/v1/diagnostics/handlers

        Returns:
            Dict with handler diagnostics
        """
        return self._client.request("GET", "/api/v1/diagnostics/handlers")

    def list_circuit_breakers(self) -> dict[str, Any]:
        """List all circuit breaker states."""
        return self._client.request("GET", "/api/v1/admin/circuit-breakers")

    def reset_circuit_breakers(self) -> dict[str, Any]:
        """Reset all circuit breakers."""
        return self._client.request("POST", "/api/v1/admin/circuit-breakers/reset")

    # ===========================================================================
    # Emergency Access
    # ===========================================================================

    def activate_emergency(
        self,
        user_id: str,
        reason: str,
        duration_minutes: int = 60,
    ) -> dict[str, Any]:
        """Activate break-glass emergency access.

        Args:
            user_id: User to grant emergency access.
            reason: Reason for emergency access (min 10 chars).
            duration_minutes: Duration in minutes (default 60, max 1440).

        Returns:
            Dict with activation status and session details.
        """
        return self._client.request(
            "POST",
            "/api/v1/admin/emergency/activate",
            json={
                "user_id": user_id,
                "reason": reason,
                "duration_minutes": duration_minutes,
            },
        )

    def deactivate_emergency(self, session_id: str | None = None) -> dict[str, Any]:
        """Deactivate break-glass emergency access.

        Args:
            session_id: Optional session ID to deactivate.

        Returns:
            Dict with deactivation status.
        """
        data: dict[str, Any] = {}
        if session_id:
            data["session_id"] = session_id
        return self._client.request(
            "POST",
            "/api/v1/admin/emergency/deactivate",
            json=data if data else None,
        )

    def get_emergency_status(self) -> dict[str, Any]:
        """Get active emergency access sessions.

        Returns:
            Dict with active emergency sessions and counts.
        """
        return self._client.request("GET", "/api/v1/admin/emergency/status")

    # ===========================================================================
    # Feature Flags
    # ===========================================================================

    def list_feature_flags(self) -> dict[str, Any]:
        """List admin feature flags."""
        return self._client.request("GET", "/api/v1/admin/feature-flags")

    def update_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        """Update admin feature flags.

        Args:
            flags: Feature flag key-value pairs to update.

        Returns:
            Dict keyed by flag name with individual update results.
        """
        original_values: dict[str, Any] = {}
        results: dict[str, Any] = {}
        applied_flags: list[str] = []

        try:
            for flag_name, value in flags.items():
                original_values[flag_name] = self.get_feature_flag(flag_name)["value"]
                results[flag_name] = self.set_feature_flag(flag_name, value)
                applied_flags.append(flag_name)
        except Exception as exc:
            rollback_failures: dict[str, str] = {}
            for flag_name in reversed(applied_flags):
                try:
                    self.set_feature_flag(flag_name, original_values[flag_name])
                except Exception as rollback_exc:
                    rollback_failures[flag_name] = str(rollback_exc)

            if rollback_failures:
                raise RuntimeError(
                    "Bulk feature flag update failed and rollback did not restore all prior "
                    f"values: {_format_bulk_feature_flag_rollback_failures(rollback_failures)}"
                ) from exc
            raise

        return results

    def get_feature_flag(self, flag_name: str) -> dict[str, Any]:
        """Get a specific feature flag by name.

        Args:
            flag_name: Feature flag identifier.

        Returns:
            Dict with flag details including enabled status and metadata.
        """
        return self._client.request("GET", f"/api/v1/admin/feature-flags/{flag_name}")

    def set_feature_flag(self, flag_name: str, value: Any) -> dict[str, Any]:
        """Set a specific feature flag value."""
        return self._client.request(
            "PUT", f"/api/v1/admin/feature-flags/{flag_name}", json={"value": value}
        )

    # ===========================================================================
    # User Management
    # ===========================================================================

    def activate_user(self, user_id: str) -> dict[str, Any]:
        """Activate a user."""
        return self._client.request("POST", f"/api/v1/admin/users/{user_id}/activate")

    def deactivate_user(self, user_id: str) -> dict[str, Any]:
        """Deactivate a user."""
        return self._client.request("POST", f"/api/v1/admin/users/{user_id}/deactivate")

    def unlock_user(self, user_id: str) -> dict[str, Any]:
        """Unlock a locked user account."""
        return self._client.request("POST", f"/api/v1/admin/users/{user_id}/unlock")

    # ===========================================================================
    # System Metrics
    # ===========================================================================

    def get_system_metrics(self) -> dict[str, Any]:
        """Get system metrics (CPU, memory, disk, etc.)."""
        return self._client.request("GET", "/api/v1/admin/system/metrics")

    # ===========================================================================
    # Security Maintenance
    # ===========================================================================

    def rotate_security_key(self, key_type: str) -> dict[str, Any]:
        """Rotate a security key by type."""
        return self._client.request(
            "POST", "/api/v1/admin/security/rotate-key", json={"key_type": key_type}
        )

    def get_rotation_status(self) -> dict[str, Any]:
        """Get key rotation status."""
        return self._client.request("GET", "/api/v1/admin/security/rotation-status")

    # ===========================================================================
    # System Health
    # ===========================================================================

    def get_system_health(self) -> dict[str, Any]:
        """Get system health overview."""
        return self._client.request("GET", "/api/v1/admin/system-health")

    def get_system_health_circuit_breakers(self) -> dict[str, Any]:
        """Get admin system health circuit breakers."""
        return self._client.request("GET", "/api/v1/admin/system-health/circuit-breakers")

    def get_system_health_slos(self) -> dict[str, Any]:
        """Get admin system health SLOs."""
        return self._client.request("GET", "/api/v1/admin/system-health/slos")

    def get_system_health_adapters(self) -> dict[str, Any]:
        """Get admin system health adapters."""
        return self._client.request("GET", "/api/v1/admin/system-health/adapters")

    def get_system_health_agents(self) -> dict[str, Any]:
        """Get admin system health agents."""
        return self._client.request("GET", "/api/v1/admin/system-health/agents")

    def get_system_health_budget(self) -> dict[str, Any]:
        """Get admin system health budget."""
        return self._client.request("GET", "/api/v1/admin/system-health/budget")

    def get_system_health_component(self, component: str) -> dict[str, Any]:
        """Get health status for a specific supported component."""
        normalized = component.strip().lower().replace("_", "-")
        handlers = {
            "circuit-breakers": self.get_system_health_circuit_breakers,
            "slos": self.get_system_health_slos,
            "adapters": self.get_system_health_adapters,
            "agents": self.get_system_health_agents,
            "budget": self.get_system_health_budget,
        }
        handler = handlers.get(normalized)
        if handler is None:
            raise ValueError(f"Unsupported system health component: {component}")
        return handler()

    def get_mfa_compliance(self) -> dict[str, Any]:
        """Get MFA compliance status."""
        return self._client.request("GET", "/api/v1/admin/mfa/compliance")


class AsyncAdminAPI:
    """
    Asynchronous Admin API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     stats = await client.admin.get_stats()
        ...     print(f"Active debates: {stats['active_debates']}")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # ===========================================================================
    # Organizations and Users
    # ===========================================================================

    async def list_organizations(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List all organizations with pagination."""
        return await self._client.request(
            "GET",
            "/api/v1/admin/organizations",
            params={"limit": limit, "offset": offset},
        )

    async def list_users(
        self,
        limit: int = 20,
        offset: int = 0,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """List all users with pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if org_id:
            params["org_id"] = org_id

        return await self._client.request("GET", "/api/v1/admin/users", params=params)

    # ===========================================================================
    # Platform Statistics
    # ===========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """Get platform-wide statistics."""
        return await self._client.request("GET", "/api/v1/admin/stats")

    async def get_revenue(self) -> dict[str, Any]:
        """Get revenue analytics."""
        return await self._client.request("GET", "/api/v1/admin/revenue")

    # ===========================================================================
    # Nomic Loop Control
    # ===========================================================================

    async def get_nomic_status(self) -> dict[str, Any]:
        """Get the current Nomic loop status."""
        return await self._client.request("GET", "/api/v1/admin/nomic/status")

    async def reset_nomic(self) -> dict[str, Any]:
        """Reset the Nomic loop to initial state."""
        return await self._client.request("POST", "/api/v1/admin/nomic/reset")

    async def pause_nomic(self) -> dict[str, Any]:
        """Pause the Nomic loop."""
        return await self._client.request("POST", "/api/v1/admin/nomic/pause")

    async def resume_nomic(self) -> dict[str, Any]:
        """Resume a paused Nomic loop."""
        return await self._client.request("POST", "/api/v1/admin/nomic/resume")

    # ===========================================================================
    # Security Operations
    # ===========================================================================

    async def get_security_status(self) -> dict[str, Any]:
        """Get security status overview."""
        return await self._client.request("GET", "/api/v1/admin/security/status")

    async def get_security_health(self) -> dict[str, Any]:
        """Get security health check results."""
        return await self._client.request("GET", "/api/v1/admin/security/health")

    async def list_security_keys(self) -> dict[str, Any]:
        """List all security keys."""
        return await self._client.request("GET", "/api/v1/admin/security/keys")

    # ===========================================================================
    # Diagnostics
    # ===========================================================================

    async def get_handler_diagnostics(self) -> dict[str, Any]:
        """Get handler diagnostics information. GET /api/v1/diagnostics/handlers"""
        return await self._client.request("GET", "/api/v1/diagnostics/handlers")

    async def list_circuit_breakers(self) -> dict[str, Any]:
        """List all circuit breaker states."""
        return await self._client.request("GET", "/api/v1/admin/circuit-breakers")

    async def reset_circuit_breakers(self) -> dict[str, Any]:
        """Reset all circuit breakers."""
        return await self._client.request("POST", "/api/v1/admin/circuit-breakers/reset")

    # ===========================================================================
    # Emergency Access
    # ===========================================================================

    async def activate_emergency(
        self,
        user_id: str,
        reason: str,
        duration_minutes: int = 60,
    ) -> dict[str, Any]:
        """Activate break-glass emergency access."""
        return await self._client.request(
            "POST",
            "/api/v1/admin/emergency/activate",
            json={
                "user_id": user_id,
                "reason": reason,
                "duration_minutes": duration_minutes,
            },
        )

    async def deactivate_emergency(self, session_id: str | None = None) -> dict[str, Any]:
        """Deactivate break-glass emergency access."""
        data: dict[str, Any] = {}
        if session_id:
            data["session_id"] = session_id
        return await self._client.request(
            "POST",
            "/api/v1/admin/emergency/deactivate",
            json=data if data else None,
        )

    async def get_emergency_status(self) -> dict[str, Any]:
        """Get active emergency access sessions."""
        return await self._client.request("GET", "/api/v1/admin/emergency/status")

    # ===========================================================================
    # Feature Flags
    # ===========================================================================

    async def list_feature_flags(self) -> dict[str, Any]:
        """List admin feature flags."""
        return await self._client.request("GET", "/api/v1/admin/feature-flags")

    async def update_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        """Update admin feature flags."""
        original_values: dict[str, Any] = {}
        results: dict[str, Any] = {}
        applied_flags: list[str] = []

        try:
            for flag_name, value in flags.items():
                original_values[flag_name] = (await self.get_feature_flag(flag_name))["value"]
                results[flag_name] = await self.set_feature_flag(flag_name, value)
                applied_flags.append(flag_name)
        except Exception as exc:
            rollback_failures: dict[str, str] = {}
            for flag_name in reversed(applied_flags):
                try:
                    await self.set_feature_flag(flag_name, original_values[flag_name])
                except Exception as rollback_exc:
                    rollback_failures[flag_name] = str(rollback_exc)

            if rollback_failures:
                raise RuntimeError(
                    "Bulk feature flag update failed and rollback did not restore all prior "
                    f"values: {_format_bulk_feature_flag_rollback_failures(rollback_failures)}"
                ) from exc
            raise

        return results

    async def get_feature_flag(self, flag_name: str) -> dict[str, Any]:
        """Get a specific feature flag by name."""
        return await self._client.request("GET", f"/api/v1/admin/feature-flags/{flag_name}")

    async def set_feature_flag(self, flag_name: str, value: Any) -> dict[str, Any]:
        """Set a specific feature flag value."""
        return await self._client.request(
            "PUT", f"/api/v1/admin/feature-flags/{flag_name}", json={"value": value}
        )

    # ===========================================================================
    # User Management
    # ===========================================================================

    async def activate_user(self, user_id: str) -> dict[str, Any]:
        """Activate a user."""
        return await self._client.request("POST", f"/api/v1/admin/users/{user_id}/activate")

    async def deactivate_user(self, user_id: str) -> dict[str, Any]:
        """Deactivate a user."""
        return await self._client.request("POST", f"/api/v1/admin/users/{user_id}/deactivate")

    async def unlock_user(self, user_id: str) -> dict[str, Any]:
        """Unlock a locked user account."""
        return await self._client.request("POST", f"/api/v1/admin/users/{user_id}/unlock")

    # ===========================================================================
    # System Metrics
    # ===========================================================================

    async def get_system_metrics(self) -> dict[str, Any]:
        """Get system metrics (CPU, memory, disk, etc.)."""
        return await self._client.request("GET", "/api/v1/admin/system/metrics")

    # ===========================================================================
    # Security Maintenance
    # ===========================================================================

    async def rotate_security_key(self, key_type: str) -> dict[str, Any]:
        """Rotate a security key by type."""
        return await self._client.request(
            "POST", "/api/v1/admin/security/rotate-key", json={"key_type": key_type}
        )

    async def get_rotation_status(self) -> dict[str, Any]:
        """Get key rotation status."""
        return await self._client.request("GET", "/api/v1/admin/security/rotation-status")

    # ===========================================================================
    # System Health
    # ===========================================================================

    async def get_system_health(self) -> dict[str, Any]:
        """Get system health overview."""
        return await self._client.request("GET", "/api/v1/admin/system-health")

    async def get_system_health_circuit_breakers(self) -> dict[str, Any]:
        """Get admin system health circuit breakers."""
        return await self._client.request("GET", "/api/v1/admin/system-health/circuit-breakers")

    async def get_system_health_slos(self) -> dict[str, Any]:
        """Get admin system health SLOs."""
        return await self._client.request("GET", "/api/v1/admin/system-health/slos")

    async def get_system_health_adapters(self) -> dict[str, Any]:
        """Get admin system health adapters."""
        return await self._client.request("GET", "/api/v1/admin/system-health/adapters")

    async def get_system_health_agents(self) -> dict[str, Any]:
        """Get admin system health agents."""
        return await self._client.request("GET", "/api/v1/admin/system-health/agents")

    async def get_system_health_budget(self) -> dict[str, Any]:
        """Get admin system health budget."""
        return await self._client.request("GET", "/api/v1/admin/system-health/budget")

    async def get_system_health_component(self, component: str) -> dict[str, Any]:
        """Get health status for a specific supported component."""
        normalized = component.strip().lower().replace("_", "-")
        handlers = {
            "circuit-breakers": self.get_system_health_circuit_breakers,
            "slos": self.get_system_health_slos,
            "adapters": self.get_system_health_adapters,
            "agents": self.get_system_health_agents,
            "budget": self.get_system_health_budget,
        }
        handler = handlers.get(normalized)
        if handler is None:
            raise ValueError(f"Unsupported system health component: {component}")
        return await handler()

    async def get_mfa_compliance(self) -> dict[str, Any]:
        """Get MFA compliance status."""
        return await self._client.request("GET", "/api/v1/admin/mfa/compliance")
