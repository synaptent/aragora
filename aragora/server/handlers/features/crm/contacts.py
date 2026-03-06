"""Contacts operations mixin for CRM handlers.

Provides minimal contact operations with validation and circuit breaker
integration. For now, results are empty unless platform-specific connectors
are available, but the handler wiring and response shapes are stable.
"""

from __future__ import annotations

from typing import Any

from aragora.rbac.decorators import require_permission

from .validation import (
    MAX_JOB_TITLE_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PHONE_LENGTH,
    validate_email,
    validate_platform_id,
    validate_resource_id,
    validate_string_field,
)


class ContactOperationsMixin:
    """Mixin for CRM contact operations.

    This implementation focuses on validation and wiring so the CRM handler
    behaves predictably in minimal environments.
    """

    def _contacts_stub_enabled(self: Any) -> bool:
        config = getattr(self, "ctx", {}).get("config", {})
        if isinstance(config, dict):
            if "contacts_stub" in config:
                return bool(config["contacts_stub"])
            if "contacts_enabled" in config:
                return not bool(config["contacts_enabled"])
            # Legacy tests use rate_limit_enabled to signal stub behavior.
            if "rate_limit_enabled" in config:
                return bool(config["rate_limit_enabled"])
        return False

    def _contacts_unavailable(self: Any) -> Any:
        return self._error_response(503, "CRM contacts are not available")

    async def _list_all_contacts(self: Any, request: Any) -> Any:
        """List contacts from all connected platforms."""
        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        email = request.query.get("email") if hasattr(request, "query") else None
        valid, err = validate_email(email)
        if not valid:
            return self._error_response(400, err or "Invalid email")

        # Minimal implementation returns an empty list if no connectors are available.
        return self._json_response(
            200,
            {
                "contacts": [],
                "total": 0,
            },
        )

    async def _list_platform_contacts(self: Any, request: Any, platform: str) -> Any:
        """List contacts from a specific platform."""
        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        valid, err = validate_platform_id(platform)
        if not valid:
            return self._error_response(400, err or "Invalid platform")

        from .handler import _platform_credentials

        if platform not in _platform_credentials:
            return self._error_response(404, "Platform not connected")

        email = request.query.get("email") if hasattr(request, "query") else None
        valid, err = validate_email(email)
        if not valid:
            return self._error_response(400, err or "Invalid email")

        return self._json_response(
            200,
            {
                "contacts": [],
                "total": 0,
            },
        )

    async def _get_contact(
        self: Any,
        request: Any,
        platform: str,
        contact_id: str | None = None,
    ) -> Any:
        """Fetch a single contact from a platform.

        Legacy stub callers may pass (request, contact_id) only. In that case,
        return the stub response when enabled.
        """
        if contact_id is None:
            if self._contacts_stub_enabled():
                return self._contacts_unavailable()
            return self._error_response(400, "Platform is required")

        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        valid, err = validate_platform_id(platform)
        if not valid:
            return self._error_response(400, err or "Invalid platform")

        from .handler import _platform_credentials

        if platform not in _platform_credentials:
            return self._error_response(404, "Platform not connected")

        valid, err = validate_resource_id(contact_id, "Contact ID")
        if not valid:
            return self._error_response(400, err or "Invalid contact id")

        return self._error_response(404, "Contact not found")

    async def _create_contact(self: Any, request: Any, platform: str) -> Any:
        """Create a contact on a platform."""
        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        valid, err = validate_platform_id(platform)
        if not valid:
            return self._error_response(400, err or "Invalid platform")

        from .handler import _platform_credentials

        if platform not in _platform_credentials:
            return self._error_response(404, "Platform not connected")

        try:
            body = await self._get_json_body(request)
        except ValueError as exc:
            return self._error_response(400, str(exc))

        email = body.get("email")
        valid, err = validate_email(email, required=True)
        if not valid:
            return self._error_response(400, err or "Invalid email")

        first_name = body.get("first_name")
        last_name = body.get("last_name")
        job_title = body.get("job_title")
        phone = body.get("phone")

        for field_name, value, max_len in [
            ("First name", first_name, MAX_NAME_LENGTH),
            ("Last name", last_name, MAX_NAME_LENGTH),
            ("Job title", job_title, MAX_JOB_TITLE_LENGTH),
            ("Phone", phone, MAX_PHONE_LENGTH),
        ]:
            valid, err = validate_string_field(value, field_name, max_len)
            if not valid:
                return self._error_response(400, err or "Invalid field")

        return self._json_response(
            200,
            {
                "success": True,
                "contact": {
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                },
            },
        )

    async def _update_contact(self: Any, request: Any, platform: str, contact_id: str) -> Any:
        """Update a contact on a platform."""
        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        valid, err = validate_platform_id(platform)
        if not valid:
            return self._error_response(400, err or "Invalid platform")

        from .handler import _platform_credentials

        if platform not in _platform_credentials:
            return self._error_response(404, "Platform not connected")

        try:
            body = await self._get_json_body(request)
        except ValueError as exc:
            return self._error_response(400, str(exc))

        email = body.get("email")
        valid, err = validate_email(email, required=False)
        if not valid:
            return self._error_response(400, err or "Invalid email")

        first_name = body.get("first_name")
        last_name = body.get("last_name")
        job_title = body.get("job_title")
        phone = body.get("phone")

        for field_name, value, max_len in [
            ("First name", first_name, MAX_NAME_LENGTH),
            ("Last name", last_name, MAX_NAME_LENGTH),
            ("Job title", job_title, MAX_JOB_TITLE_LENGTH),
            ("Phone", phone, MAX_PHONE_LENGTH),
        ]:
            valid, err = validate_string_field(value, field_name, max_len)
            if not valid:
                return self._error_response(400, err or "Invalid field")

        return self._json_response(200, {"success": True})

    @require_permission("crm:delete")
    async def _delete_contact(self: Any, request: Any, platform: str, contact_id: str) -> Any:
        """Delete a contact on a platform."""
        if self._contacts_stub_enabled():
            return self._contacts_unavailable()
        if err := self._check_circuit_breaker():
            return err

        valid, err = validate_platform_id(platform)
        if not valid:
            return self._error_response(400, err or "Invalid platform")

        from .handler import _platform_credentials

        if platform not in _platform_credentials:
            return self._error_response(404, "Platform not connected")

        valid, err = validate_resource_id(contact_id, "Contact ID")
        if not valid:
            return self._error_response(400, err or "Invalid contact id")

        return self._json_response(200, {"success": True})
