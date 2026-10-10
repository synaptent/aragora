"""
Abstract base class for audit log persistence backends.

All persistence backends must implement this interface to ensure
consistent behavior across storage mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.observability.audit_log import AuditEvent, AuditQuery


class AuditPersistenceBackend(ABC):
    """
    Abstract interface for audit log storage backends.

    Backends are responsible for:
    - Persisting audit events with integrity guarantees
    - Querying events by various criteria
    - Verifying hash chain integrity
    - Managing retention policies
    """

    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the backend (create tables, directories, etc).

        Should be idempotent - safe to call multiple times.
        """
        pass

    @abstractmethod
    def store(self, event: AuditEvent) -> str:
        """
        Store an audit event.

        Args:
            event: The audit event to persist

        Returns:
            Event ID

        Raises:
            PersistenceError: If storage fails
        """
        pass

    @abstractmethod
    def get(self, event_id: str) -> AuditEvent | None:
        """
        Retrieve a single event by ID.

        Args:
            event_id: The event ID

        Returns:
            The event if found, None otherwise
        """
        pass

    @abstractmethod
    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """
        Query events matching criteria.

        Args:
            query: Query parameters

        Returns:
            List of matching events
        """
        pass

    @abstractmethod
    def get_last_hash(self) -> str:
        """
        Get the hash of the most recent event for chain continuity.

        Returns:
            Last event hash, or empty string if no events exist
        """
        pass

    @abstractmethod
    def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """
        Count events in date range.

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            Event count
        """
        pass

    @abstractmethod
    def delete_before(self, cutoff: datetime) -> int:
        """
        Delete events older than cutoff (retention policy).

        Args:
            cutoff: Delete events with timestamp < cutoff

        Returns:
            Number of events deleted
        """
        pass

    @abstractmethod
    def verify_integrity(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Verify hash chain integrity.

        Args:
            start_date: Start of verification range
            end_date: End of verification range

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connections and release resources."""
        pass

    def get_stats(self) -> dict[str, Any]:
        """
        Get backend statistics.

        Returns:
            Dictionary with backend-specific stats
        """
        return {
            "backend": self.__class__.__name__,
            "total_events": self.count(),
        }


class PersistenceError(Exception):
    """Raised when persistence operations fail."""

    pass
