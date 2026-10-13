"""
RBAC Ownership - Resource ownership tracking and implicit permission enforcement.

Provides automatic owner-based access control where resource creators get
implicit permissions on resources they own. This supplements the explicit
permission grants in resource_permissions.py.

Key features:
- Track resource owners (who created what)
- Implicit owner permissions (owners get automatic access)
- Ownership transfer with audit trail
- Integration with PermissionChecker

Example:
    manager = OwnershipManager()

    # Set owner when resource is created
    manager.set_owner(
        resource_type=ResourceType.DEBATE,
        resource_id="debate-123",
        owner_id="user-456",
        org_id="org-789"
    )

    # Check ownership
    if manager.is_owner("user-456", ResourceType.DEBATE, "debate-123"):
        # User owns this resource, grant implicit access
        pass

    # Transfer ownership
    manager.transfer_ownership(
        resource_type=ResourceType.DEBATE,
        resource_id="debate-123",
        new_owner_id="user-999",
        transferred_by="admin-1"
    )
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aragora.utils.cache import TTLCache
from .models import AuthorizationDecision, AuthorizationContext, ResourceType

logger = logging.getLogger(__name__)

# Configuration constants for bounded collections
MAX_OWNERSHIP_RECORDS = 100_000  # Max records per manager instance
MAX_TRANSFER_HISTORY = 10_000  # Max transfer events to keep
OWNERSHIP_CACHE_TTL = 300.0  # 5 minutes
OWNERSHIP_CACHE_SIZE = 10_000  # Max cache entries


# Default implicit permissions granted to resource owners
DEFAULT_OWNER_PERMISSIONS: dict[ResourceType, list[str]] = {
    ResourceType.DEBATE: [
        "debates.read",
        "debates.update",
        "debates.delete",
        "debates.run",
        "debates.stop",
        "debates.pause",
        "debates.resume",
        "debates.fork",
    ],
    ResourceType.WORKFLOW: [
        "workflows.read",
        "workflows.update",
        "workflows.delete",
        "workflows.run",
    ],
    ResourceType.AGENT: [
        "agents.read",
        "agents.update",
        "agents.delete",
        "agents.deploy",
        "agents.configure",
    ],
    ResourceType.EVIDENCE: [
        "evidence.read",
        "evidence.update",
        "evidence.delete",
    ],
    ResourceType.CONNECTOR: [
        "connectors.read",
        "connectors.update",
        "connectors.delete",
        "connectors.test",
        "connectors.configure",
    ],
    ResourceType.WEBHOOK: [
        "webhooks.read",
        "webhooks.update",
        "webhooks.delete",
    ],
}


@dataclass
class OwnershipRecord:
    """
    Record of resource ownership.

    Attributes:
        id: Unique identifier for this ownership record
        resource_type: Type of resource (e.g., DEBATE, WORKFLOW)
        resource_id: Specific resource ID
        owner_id: User ID who owns the resource
        org_id: Organization scope
        created_at: When ownership was established
        transferred_from: Previous owner if this was a transfer
        transferred_at: When ownership was transferred
        transferred_by: Who initiated the transfer
        metadata: Additional metadata for auditing
    """

    id: str
    resource_type: ResourceType
    resource_id: str
    owner_id: str
    org_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    transferred_from: str | None = None
    transferred_at: datetime | None = None
    transferred_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        resource_type: ResourceType,
        resource_id: str,
        owner_id: str,
        org_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> OwnershipRecord:
        """Factory method to create a new ownership record."""
        return cls(
            id=str(uuid4()),
            resource_type=resource_type,
            resource_id=resource_id,
            owner_id=owner_id,
            org_id=org_id,
            created_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "owner_id": self.owner_id,
            "org_id": self.org_id,
            "created_at": self.created_at.isoformat(),
            "transferred_from": self.transferred_from,
            "transferred_at": self.transferred_at.isoformat() if self.transferred_at else None,
            "transferred_by": self.transferred_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OwnershipRecord:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            resource_type=ResourceType(data["resource_type"]),
            resource_id=data["resource_id"],
            owner_id=data["owner_id"],
            org_id=data["org_id"],
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data["created_at"], str)
                else data["created_at"]
            ),
            transferred_from=data.get("transferred_from"),
            transferred_at=(
                datetime.fromisoformat(data["transferred_at"])
                if data.get("transferred_at")
                else None
            ),
            transferred_by=data.get("transferred_by"),
            metadata=data.get("metadata", {}),
        )


class OwnershipManager:
    """
    Manages resource ownership and implicit owner permissions.

    Provides tracking of resource owners and automatic permission
    grants for owners without requiring explicit permission entries.

    Example:
        manager = OwnershipManager()

        # Register ownership when debate is created
        manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-123",
            owner_id="user-456",
            org_id="org-789"
        )

        # Check if user owns resource
        is_owner = manager.is_owner("user-456", ResourceType.DEBATE, "debate-123")

        # Check implicit permission
        decision = manager.check_owner_permission(
            context, ResourceType.DEBATE, "debates.delete", "debate-123"
        )
    """

    def __init__(
        self,
        owner_permissions: dict[ResourceType, list[str]] | None = None,
        cache_ttl: int = 300,
        enable_cache: bool = True,
    ) -> None:
        """
        Initialize the ownership manager.

        Args:
            owner_permissions: Custom owner permission mappings.
                              If None, uses DEFAULT_OWNER_PERMISSIONS.
            cache_ttl: Cache TTL in seconds for ownership lookups.
            enable_cache: Whether to enable caching.
        """
        self._owner_permissions = owner_permissions or DEFAULT_OWNER_PERMISSIONS
        self._cache_ttl = cache_ttl
        self._enable_cache = enable_cache

        # In-memory storage
        self._ownership_records: dict[str, OwnershipRecord] = {}

        # Indexes for fast lookup
        self._by_resource: dict[str, str] = {}  # resource_key -> record_id
        self._by_owner: dict[str, set[str]] = {}  # owner_id -> set of record_ids
        self._by_org: dict[str, set[str]] = {}  # org_id -> set of record_ids

        # Cache for ownership checks (bounded with TTL)
        self._ownership_cache: TTLCache[str | None] = TTLCache(
            maxsize=OWNERSHIP_CACHE_SIZE, ttl_seconds=cache_ttl
        )

        # Transfer history for audit (bounded circular buffer)
        self._transfer_history: deque[dict[str, Any]] = deque(maxlen=MAX_TRANSFER_HISTORY)

    def set_owner(
        self,
        resource_type: ResourceType,
        resource_id: str,
        owner_id: str,
        org_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> OwnershipRecord:
        """
        Set the owner of a resource.

        If the resource already has an owner, this will replace it
        (use transfer_ownership for formal transfers with audit trail).

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID
            owner_id: User ID who owns the resource
            org_id: Organization scope
            metadata: Optional metadata

        Returns:
            The created OwnershipRecord
        """
        resource_key = self._resource_key(resource_type, resource_id)

        # Check if already owned
        existing_record_id = self._by_resource.get(resource_key)
        if existing_record_id:
            existing = self._ownership_records.get(existing_record_id)
            if existing and existing.owner_id == owner_id:
                # Same owner, no change needed
                return existing
            # Different owner - remove old record
            self._remove_record(existing_record_id)

        # Create new record
        record = OwnershipRecord.create(
            resource_type=resource_type,
            resource_id=resource_id,
            owner_id=owner_id,
            org_id=org_id,
            metadata=metadata,
        )

        self._store_record(record)
        self._invalidate_cache(resource_type, resource_id)

        logger.info(
            "Set owner %s for %s/%s in org %s", owner_id, resource_type.value, resource_id, org_id
        )

        return record

    def get_owner(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> str | None:
        """
        Get the owner of a resource.

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID

        Returns:
            Owner user ID or None if not found
        """
        # Check cache first
        if self._enable_cache:
            cache_key = self._cache_key(resource_type, resource_id)
            cached = self._get_cached_owner(cache_key)
            if cached is not None:
                return cached if cached != "" else None

        resource_key = self._resource_key(resource_type, resource_id)
        record_id = self._by_resource.get(resource_key)

        if not record_id:
            if self._enable_cache:
                self._cache_owner(cache_key, None)
            return None

        record = self._ownership_records.get(record_id)
        owner_id = record.owner_id if record else None

        if self._enable_cache:
            self._cache_owner(cache_key, owner_id)

        return owner_id

    def is_owner(
        self,
        user_id: str,
        resource_type: ResourceType,
        resource_id: str,
    ) -> bool:
        """
        Check if a user is the owner of a resource.

        Args:
            user_id: User to check
            resource_type: Type of resource
            resource_id: Specific resource ID

        Returns:
            True if the user owns the resource
        """
        owner_id = self.get_owner(resource_type, resource_id)
        return owner_id == user_id

    def get_ownership_record(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> OwnershipRecord | None:
        """
        Get the full ownership record for a resource.

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID

        Returns:
            OwnershipRecord or None if not found
        """
        resource_key = self._resource_key(resource_type, resource_id)
        record_id = self._by_resource.get(resource_key)

        if not record_id:
            return None

        return self._ownership_records.get(record_id)

    def transfer_ownership(
        self,
        resource_type: ResourceType,
        resource_id: str,
        new_owner_id: str,
        transferred_by: str | None = None,
        reason: str | None = None,
    ) -> OwnershipRecord | None:
        """
        Transfer ownership of a resource to a new owner.

        Creates an audit trail of the transfer.

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID
            new_owner_id: New owner's user ID
            transferred_by: Who is performing the transfer
            reason: Reason for the transfer

        Returns:
            Updated OwnershipRecord or None if resource not found
        """
        record = self.get_ownership_record(resource_type, resource_id)
        if not record:
            logger.warning(
                "Cannot transfer ownership: resource %s/%s not found",
                resource_type.value,
                resource_id,
            )
            return None

        old_owner_id = record.owner_id

        if old_owner_id == new_owner_id:
            logger.info("Ownership transfer skipped: same owner %s", new_owner_id)
            return record

        # Record transfer history
        transfer_event = {
            "id": str(uuid4()),
            "resource_type": resource_type.value,
            "resource_id": resource_id,
            "from_owner": old_owner_id,
            "to_owner": new_owner_id,
            "transferred_by": transferred_by,
            "transferred_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        self._transfer_history.append(transfer_event)

        # Update record
        record.transferred_from = old_owner_id
        record.transferred_at = datetime.now(timezone.utc)
        record.transferred_by = transferred_by
        record.owner_id = new_owner_id

        # Update indexes
        self._update_owner_index(record.id, old_owner_id, new_owner_id)

        # Invalidate cache
        self._invalidate_cache(resource_type, resource_id)

        logger.info(
            "Transferred ownership of %s/%s from %s to %s",
            resource_type.value,
            resource_id,
            old_owner_id,
            new_owner_id,
        )

        return record

    def remove_ownership(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> bool:
        """
        Remove ownership record for a resource.

        Typically called when a resource is deleted.

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID

        Returns:
            True if removed, False if not found
        """
        resource_key = self._resource_key(resource_type, resource_id)
        record_id = self._by_resource.get(resource_key)

        if not record_id:
            return False

        self._remove_record(record_id)
        self._invalidate_cache(resource_type, resource_id)

        logger.info("Removed ownership for %s/%s", resource_type.value, resource_id)

        return True

    def get_owned_resources(
        self,
        user_id: str,
        resource_type: ResourceType | None = None,
        org_id: str | None = None,
    ) -> list[OwnershipRecord]:
        """
        Get all resources owned by a user.

        Args:
            user_id: Owner's user ID
            resource_type: Optional filter by resource type
            org_id: Optional filter by organization

        Returns:
            List of OwnershipRecord objects
        """
        record_ids = self._by_owner.get(user_id, set())
        records = []

        for record_id in record_ids:
            record = self._ownership_records.get(record_id)
            if record:
                if resource_type and record.resource_type != resource_type:
                    continue
                if org_id and record.org_id != org_id:
                    continue
                records.append(record)

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def check_owner_permission(
        self,
        context: AuthorizationContext,
        resource_type: ResourceType,
        permission_key: str,
        resource_id: str,
    ) -> AuthorizationDecision | None:
        """
        Check if a user has implicit owner permission on a resource.

        This should be called before checking explicit permissions.
        Returns None if user is not owner (continue to other checks).

        Args:
            context: Authorization context
            resource_type: Type of resource
            permission_key: Permission being checked
            resource_id: Specific resource ID

        Returns:
            AuthorizationDecision if owner has implicit permission, None otherwise
        """
        # Check if user is owner
        if not self.is_owner(context.user_id, resource_type, resource_id):
            return None

        # Check if this permission is in the implicit owner permissions
        owner_perms = self._owner_permissions.get(resource_type, [])

        if permission_key in owner_perms:
            return AuthorizationDecision(
                allowed=True,
                reason="Owner implicit access",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
            )

        # Check wildcard
        resource_prefix = permission_key.split(".")[0] if "." in permission_key else ""
        if f"{resource_prefix}.*" in owner_perms:
            return AuthorizationDecision(
                allowed=True,
                reason="Owner implicit access (wildcard)",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
            )

        return None

    def get_implicit_permissions(
        self,
        resource_type: ResourceType,
    ) -> list[str]:
        """
        Get the list of implicit permissions granted to owners of a resource type.

        Args:
            resource_type: Type of resource

        Returns:
            List of permission keys
        """
        return list(self._owner_permissions.get(resource_type, []))

    def get_transfer_history(
        self,
        resource_type: ResourceType | None = None,
        resource_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get ownership transfer history.

        Args:
            resource_type: Optional filter by resource type
            resource_id: Optional filter by resource ID
            limit: Maximum number of records to return

        Returns:
            List of transfer events
        """
        # Convert deque to list for filtering and slicing
        history: list[dict[str, Any]] = list(self._transfer_history)

        if resource_type:
            history = [h for h in history if h["resource_type"] == resource_type.value]

        if resource_id:
            history = [h for h in history if h["resource_id"] == resource_id]

        return history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about ownership records.

        Returns:
            Dictionary with statistics
        """
        by_type: dict[str, int] = {}
        for record in self._ownership_records.values():
            rt = record.resource_type.value
            by_type[rt] = by_type.get(rt, 0) + 1

        return {
            "total_records": len(self._ownership_records),
            "unique_owners": len(self._by_owner),
            "unique_orgs": len(self._by_org),
            "by_resource_type": by_type,
            "transfer_count": len(self._transfer_history),
            "cache_enabled": self._enable_cache,
            "cache_size": len(self._ownership_cache),
        }

    def clear_cache(self) -> None:
        """Clear the ownership cache."""
        self._ownership_cache.clear()

    # Private helper methods

    def _resource_key(self, resource_type: ResourceType, resource_id: str) -> str:
        """Generate a key for resource indexing."""
        return f"{resource_type.value}:{resource_id}"

    def _cache_key(self, resource_type: ResourceType, resource_id: str) -> str:
        """Generate a cache key for ownership lookups."""
        return f"owner:{resource_type.value}:{resource_id}"

    def _store_record(self, record: OwnershipRecord) -> None:
        """Store a record and update indexes."""
        self._ownership_records[record.id] = record

        # Resource index
        resource_key = self._resource_key(record.resource_type, record.resource_id)
        self._by_resource[resource_key] = record.id

        # Owner index
        if record.owner_id not in self._by_owner:
            self._by_owner[record.owner_id] = set()
        self._by_owner[record.owner_id].add(record.id)

        # Org index
        if record.org_id not in self._by_org:
            self._by_org[record.org_id] = set()
        self._by_org[record.org_id].add(record.id)

    def _remove_record(self, record_id: str) -> None:
        """Remove a record and update indexes."""
        record = self._ownership_records.pop(record_id, None)
        if not record:
            return

        # Remove from resource index
        resource_key = self._resource_key(record.resource_type, record.resource_id)
        self._by_resource.pop(resource_key, None)

        # Remove from owner index
        if record.owner_id in self._by_owner:
            self._by_owner[record.owner_id].discard(record_id)

        # Remove from org index
        if record.org_id in self._by_org:
            self._by_org[record.org_id].discard(record_id)

    def _update_owner_index(
        self,
        record_id: str,
        old_owner_id: str,
        new_owner_id: str,
    ) -> None:
        """Update owner index after ownership transfer."""
        # Remove from old owner
        if old_owner_id in self._by_owner:
            self._by_owner[old_owner_id].discard(record_id)

        # Add to new owner
        if new_owner_id not in self._by_owner:
            self._by_owner[new_owner_id] = set()
        self._by_owner[new_owner_id].add(record_id)

    def _get_cached_owner(self, cache_key: str) -> str | None:
        """Get cached owner lookup result.

        Returns:
            Owner ID if cached and not expired, None otherwise.
            Note: Returns empty string for explicitly cached "no owner" case.
        """
        return self._ownership_cache.get(cache_key)

    def _cache_owner(self, cache_key: str, owner_id: str | None) -> None:
        """Cache an owner lookup result.

        Args:
            cache_key: The cache key for this resource.
            owner_id: The owner ID (or empty string for "no owner").
        """
        # Store empty string for None to distinguish from cache miss
        self._ownership_cache.set(cache_key, owner_id or "")

    def _invalidate_cache(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> None:
        """Invalidate cache for a resource."""
        cache_key = self._cache_key(resource_type, resource_id)
        self._ownership_cache.invalidate(cache_key)


# Global ownership manager instance
_ownership_manager: OwnershipManager | None = None


def get_ownership_manager() -> OwnershipManager:
    """Get or create the global ownership manager."""
    global _ownership_manager
    if _ownership_manager is None:
        _ownership_manager = OwnershipManager()
    return _ownership_manager


def set_ownership_manager(manager: OwnershipManager | None) -> None:
    """Set the global ownership manager."""
    global _ownership_manager
    _ownership_manager = manager


def set_resource_owner(
    resource_type: ResourceType,
    resource_id: str,
    owner_id: str,
    org_id: str,
) -> OwnershipRecord:
    """Convenience function to set resource owner using global manager."""
    return get_ownership_manager().set_owner(
        resource_type=resource_type,
        resource_id=resource_id,
        owner_id=owner_id,
        org_id=org_id,
    )


def get_resource_owner(
    resource_type: ResourceType,
    resource_id: str,
) -> str | None:
    """Convenience function to get resource owner using global manager."""
    return get_ownership_manager().get_owner(
        resource_type=resource_type,
        resource_id=resource_id,
    )


def is_resource_owner(
    user_id: str,
    resource_type: ResourceType,
    resource_id: str,
) -> bool:
    """Convenience function to check resource ownership using global manager."""
    return get_ownership_manager().is_owner(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def check_owner_permission(
    context: AuthorizationContext,
    resource_type: ResourceType,
    permission_key: str,
    resource_id: str,
) -> AuthorizationDecision | None:
    """Convenience function to check owner permission using global manager."""
    return get_ownership_manager().check_owner_permission(
        context=context,
        resource_type=resource_type,
        permission_key=permission_key,
        resource_id=resource_id,
    )
