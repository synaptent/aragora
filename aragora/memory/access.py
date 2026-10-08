"""Access control helpers for ContinuumMemory entries.

Provides lightweight, metadata-based filtering for memory entries using
AuthorizationContext and existing RBAC permissions. This enables
workspace/org isolation and personal-memory visibility without requiring
schema changes.
"""

from __future__ import annotations

from collections import Counter
import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aragora.rbac.models import AuthorizationContext
else:
    AuthorizationContext = Any


def _env_flag(name: str, default: str = "1") -> bool:
    value = os.environ.get(name, default).strip().lower()
    return value not in {"0", "false", "no", "off"}


def resolve_tenant_id(auth_context: AuthorizationContext | None) -> str | None:
    """Resolve tenant/workspace id for memory isolation."""
    if auth_context is None or not _env_flag("ARAGORA_MEMORY_TENANT_ENFORCE", "1"):
        return None
    workspace_id = getattr(auth_context, "workspace_id", None)
    org_id = getattr(auth_context, "org_id", None)
    return workspace_id or org_id


def tenant_enforcement_enabled() -> bool:
    """Return True if tenant isolation enforcement is enabled."""
    return _env_flag("ARAGORA_MEMORY_TENANT_ENFORCE", "1")


def _has_permission(auth_context: AuthorizationContext | None, permission: str) -> bool:
    if auth_context is None:
        return False
    check = getattr(auth_context, "has_permission", None)
    if callable(check):
        try:
            return bool(check(permission))
        except (TypeError, ValueError, AttributeError):
            _logger.debug("Permission check failed for %s", permission, exc_info=True)
            return False
    return False


def _has_role(auth_context: AuthorizationContext | None, *roles: str) -> bool:
    if auth_context is None:
        return False
    check = getattr(auth_context, "has_any_role", None)
    if callable(check):
        try:
            return bool(check(*roles))
        except (TypeError, ValueError, AttributeError):
            _logger.debug("Role check failed for %s", roles, exc_info=True)
            return False
    # Fallback: check roles attribute
    current_roles: Any = getattr(auth_context, "roles", set()) or set()
    return bool(set(roles) & set(current_roles))


def is_admin_context(auth_context: AuthorizationContext | None) -> bool:
    """Return True if context has admin-level memory access."""
    if auth_context is None:
        return False
    return _has_permission(auth_context, "memory:manage") or _has_role(
        auth_context, "owner", "admin", "superadmin"
    )


def has_memory_read_access(auth_context: AuthorizationContext | None) -> bool:
    """Return True when context is allowed to read memory content."""
    if auth_context is None:
        # Internal/system calls without a user context remain allowed.
        return True
    if is_admin_context(auth_context):
        return True
    return _has_permission(auth_context, "memory:read") or _has_permission(
        auth_context, "memory.read"
    )


def _get_metadata(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        meta = entry.get("metadata") or {}
    else:
        meta = getattr(entry, "metadata", None) or {}
    return meta if isinstance(meta, dict) else {}


def _get_value(entry: Any, key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _entry_identifier(entry: Any) -> str:
    entry_id = _get_value(entry, "id") or _get_value(entry, "memory_id")
    return str(entry_id) if entry_id is not None else "unknown"


def build_access_envelope(
    auth_context: AuthorizationContext | None,
    *,
    source: str | None = None,
    allowed: bool | None = None,
) -> dict[str, Any]:
    """Build a stable, auditable memory-access envelope for telemetry/audit payloads."""
    envelope: dict[str, Any] = {
        "source": source or "memory",
        "allowed": allowed,
        "user_id": None,
        "workspace_id": None,
        "tenant_id": None,
        "org_id": None,
        "roles": [],
        "permission_count": 0,
        "request_id": None,
    }
    if auth_context is None:
        return envelope

    roles = sorted(str(role) for role in (getattr(auth_context, "roles", set()) or set()))
    permissions: Any = getattr(auth_context, "permissions", set()) or set()
    workspace_id = getattr(auth_context, "workspace_id", None)
    org_id = getattr(auth_context, "org_id", None)

    envelope.update(
        {
            "user_id": getattr(auth_context, "user_id", None),
            "workspace_id": workspace_id,
            "tenant_id": workspace_id or org_id,
            "org_id": org_id,
            "roles": roles,
            "permission_count": len(permissions),
            "request_id": getattr(auth_context, "request_id", None),
        }
    )
    return envelope


def emit_denial_telemetry(
    source: str,
    auth_context: AuthorizationContext | None,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit structured denial telemetry for memory access debugging."""
    envelope = build_access_envelope(auth_context, source=source, allowed=False)
    payload = dict(envelope)
    payload["reason"] = reason
    if details:
        payload["details"] = details
    _logger.warning("memory_access_denied %s", payload)


def _evaluate_entry_access(
    entry: Any,
    auth_context: AuthorizationContext | None,
) -> tuple[bool, str]:
    if auth_context is None:
        return True, "no_context"

    meta = _get_metadata(entry)
    admin = is_admin_context(auth_context)

    # Tenant/workspace isolation (if tenant_id present)
    tenant_id = meta.get("tenant_id") or meta.get("workspace_id")
    if tenant_id:
        expected = resolve_tenant_id(auth_context)
        if expected and tenant_id != expected and not admin:
            return False, "tenant_mismatch"

    # Org isolation (if org_id present)
    org_id = meta.get("org_id")
    ctx_org = getattr(auth_context, "org_id", None)
    if org_id and ctx_org and org_id != ctx_org and not admin:
        return False, "org_mismatch"

    # Persona scope (if persona_id present)
    persona_id = meta.get("persona_id") or meta.get("persona")
    if persona_id and not admin:
        persona_values: set[str] = set()
        single_persona = getattr(auth_context, "persona_id", None) or getattr(
            auth_context, "active_persona_id", None
        )
        if single_persona:
            persona_values.add(str(single_persona))
        persona_values.update(
            str(pid) for pid in (getattr(auth_context, "persona_ids", []) or []) if pid is not None
        )
        has_persona_read = _has_permission(auth_context, "personas:read") or _has_permission(
            auth_context, "personas.read"
        )
        if str(persona_id) not in persona_values and not has_persona_read:
            return False, "persona_mismatch"

    # Personal memory scope
    owner_id = meta.get("owner_id") or meta.get("user_id") or _get_value(entry, "owner_id")
    scope = meta.get("scope") or meta.get("visibility")
    if scope in {"user", "private"} or owner_id:
        if owner_id and owner_id != getattr(auth_context, "user_id", None) and not admin:
            return False, "owner_mismatch"

    return True, "allowed"


def can_view_entry(entry: Any, auth_context: AuthorizationContext | None) -> bool:
    """Return True if auth_context can view the memory entry."""
    allowed, _ = _evaluate_entry_access(entry, auth_context)
    return allowed


def filter_entries(
    entries: Iterable[Any],
    auth_context: AuthorizationContext | None,
    *,
    source: str | None = None,
) -> list[Any]:
    """Filter memory entries based on auth_context."""
    if auth_context is None:
        return list(entries)

    allowed_entries: list[Any] = []
    denied_ids: list[str] = []
    denial_reasons: Counter[str] = Counter()

    for entry in entries:
        allowed, reason = _evaluate_entry_access(entry, auth_context)
        if allowed:
            allowed_entries.append(entry)
            continue
        denied_ids.append(_entry_identifier(entry))
        denial_reasons[reason] += 1

    if source and denied_ids:
        emit_denial_telemetry(
            source,
            auth_context,
            "entry_filtering",
            details={
                "checked": len(allowed_entries) + len(denied_ids),
                "allowed": len(allowed_entries),
                "denied": len(denied_ids),
                "reasons": dict(denial_reasons),
                "sample_denied_ids": denied_ids[:5],
            },
        )

    return allowed_entries


__all__ = [
    "resolve_tenant_id",
    "tenant_enforcement_enabled",
    "is_admin_context",
    "has_memory_read_access",
    "build_access_envelope",
    "emit_denial_telemetry",
    "can_view_entry",
    "filter_entries",
]
