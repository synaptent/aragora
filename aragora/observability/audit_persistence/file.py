"""
File-based persistence backend for audit logs.

Simple, zero-dependency backend suitable for:
- SMB deployments without database infrastructure
- Development and testing
- Single-instance deployments
- Air-gapped environments

Features:
- JSON-line format for easy parsing
- Daily rotation for manageability
- Index file for fast lookups
- No external dependencies
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import AuditPersistenceBackend, PersistenceError

if TYPE_CHECKING:
    from aragora.observability.audit_log import AuditEvent, AuditQuery

logger = logging.getLogger(__name__)


class FileBackend(AuditPersistenceBackend):
    """
    File-based audit log persistence using JSON-lines format.

    Storage structure:
        <storage_path>/
            audit_YYYY-MM-DD.jsonl  # Daily event files
            index.json              # ID -> file:line mapping for lookups
            meta.json               # Last hash and stats

    Each event is stored as a single JSON line, making the logs:
    - Human-readable
    - Easy to parse with standard tools (grep, jq)
    - Appendable without rewriting
    - Suitable for log aggregation pipelines
    """

    def __init__(
        self,
        storage_path: Path,
        max_file_size_mb: int = 100,
    ):
        """
        Initialize file backend.

        Args:
            storage_path: Directory for audit log files
            max_file_size_mb: Max size per file before rotation (default 100MB)
        """
        self.storage_path = Path(storage_path)
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self._index_path = self.storage_path / "index.json"
        self._meta_path = self.storage_path / "meta.json"
        self._index: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, Any] = {}

    def initialize(self) -> None:
        """Create storage directory and load index."""
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Load or create index
        if self._index_path.exists():
            try:
                with open(self._index_path) as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load audit index, starting fresh: %s", e)
                self._index = {}

        # Load or create meta
        if self._meta_path.exists():
            try:
                with open(self._meta_path) as f:
                    self._meta = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load audit meta, starting fresh: %s", e)
                self._meta = {}

        logger.info("File audit backend initialized at %s", self.storage_path)

    def _get_current_file(self) -> Path:
        """Get the current day's log file."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.storage_path / f"audit_{date_str}.jsonl"

    def _save_index(self) -> None:
        """Persist index to disk."""
        temp_path = self._index_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(self._index, f)
        temp_path.replace(self._index_path)

    def _save_meta(self) -> None:
        """Persist meta to disk."""
        temp_path = self._meta_path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(self._meta, f)
        temp_path.replace(self._meta_path)

    def store(self, event: AuditEvent) -> str:
        """Store an audit event."""
        log_file = self._get_current_file()

        # Serialize event
        event_json = json.dumps(event.to_dict(), separators=(",", ":"))

        try:
            # Append with file locking for concurrent access
            with open(log_file, "a") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    # Get line number before write
                    f.seek(0, os.SEEK_END)
                    if log_file.exists():
                        with open(log_file) as count_f:
                            line_num = sum(1 for _ in count_f)
                    else:
                        line_num = 0

                    f.write(event_json + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Update index
            self._index[event.id] = {
                "file": log_file.name,
                "line": line_num,
                "timestamp": event.timestamp.isoformat(),
            }

            # Update meta
            self._meta["last_hash"] = event.event_hash
            self._meta["last_event_id"] = event.id
            self._meta["event_count"] = self._meta.get("event_count", 0) + 1

            # Periodic index save (every 100 events)
            if self._meta["event_count"] % 100 == 0:
                self._save_index()
                self._save_meta()

            return event.id

        except OSError as e:
            raise PersistenceError(f"Failed to write audit event: {e}")

    def get(self, event_id: str) -> AuditEvent | None:
        """Retrieve a single event by ID."""
        if event_id not in self._index:
            return None

        location = self._index[event_id]
        log_file = self.storage_path / location["file"]

        if not log_file.exists():
            return None

        try:
            with open(log_file) as f:
                for i, line in enumerate(f):
                    if i == location["line"]:
                        data = json.loads(line)
                        return self._dict_to_event(data)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read event %s: %s", event_id, e)

        return None

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """Query events matching criteria."""
        results: list[AuditEvent] = []
        count = 0
        skipped = 0

        # Get all log files in date range
        log_files = sorted(self.storage_path.glob("audit_*.jsonl"), reverse=True)

        for log_file in log_files:
            # Extract date from filename
            try:
                file_date_str = log_file.stem.replace("audit_", "")
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            # Skip files outside date range
            if query.start_date and file_date.date() < query.start_date.date():
                continue
            if query.end_date and file_date.date() > query.end_date.date():
                continue

            # Read and filter events
            try:
                with open(log_file) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            event = self._dict_to_event(data)

                            if self._matches_query(event, query):
                                if skipped < query.offset:
                                    skipped += 1
                                    continue

                                results.append(event)
                                count += 1

                                if count >= query.limit:
                                    return results
                        except json.JSONDecodeError:
                            continue
            except OSError as e:
                logger.warning("Failed to read %s: %s", log_file, e)

        return results

    def _matches_query(self, event: AuditEvent, query: AuditQuery) -> bool:
        """Check if event matches query criteria."""
        if query.start_date and event.timestamp < query.start_date:
            return False
        if query.end_date and event.timestamp > query.end_date:
            return False
        if query.category and event.category != query.category:
            return False
        if query.action and event.action != query.action:
            return False
        if query.actor_id and event.actor_id != query.actor_id:
            return False
        if query.resource_type and event.resource_type != query.resource_type:
            return False
        if query.resource_id and event.resource_id != query.resource_id:
            return False
        if query.outcome and event.outcome != query.outcome:
            return False
        if query.org_id and event.org_id != query.org_id:
            return False
        if query.ip_address and event.ip_address != query.ip_address:
            return False

        if query.search_text:
            search = query.search_text.lower()
            searchable = (
                f"{event.action} {event.actor_id} {event.resource_type} "
                f"{event.resource_id} {json.dumps(event.details)} {event.reason}"
            ).lower()
            if search not in searchable:
                return False

        return True

    def get_last_hash(self) -> str:
        """Get the hash of the most recent event."""
        return self._meta.get("last_hash", "")

    def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count events in date range."""
        if not start_date and not end_date:
            return self._meta.get("event_count", 0)

        # Need to scan files
        count = 0
        for log_file in self.storage_path.glob("audit_*.jsonl"):
            try:
                file_date_str = log_file.stem.replace("audit_", "")
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if start_date and file_date.date() < start_date.date():
                continue
            if end_date and file_date.date() > end_date.date():
                continue

            try:
                with open(log_file) as f:
                    for line in f:
                        if line.strip():
                            count += 1
            except OSError:
                continue

        return count

    def delete_before(self, cutoff: datetime) -> int:
        """Delete events older than cutoff."""
        deleted = 0

        for log_file in list(self.storage_path.glob("audit_*.jsonl")):
            try:
                file_date_str = log_file.stem.replace("audit_", "")
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            # Delete entire file if all events are old
            if file_date.date() < cutoff.date():
                try:
                    # Count events in file
                    with open(log_file) as f:
                        file_count = sum(1 for line in f if line.strip())
                    deleted += file_count

                    # Remove from index
                    to_remove = [
                        eid for eid, loc in self._index.items() if loc["file"] == log_file.name
                    ]
                    for eid in to_remove:
                        del self._index[eid]

                    log_file.unlink()
                    logger.info("Deleted old audit log: %s", log_file.name)
                except OSError as e:
                    logger.warning("Failed to delete %s: %s", log_file, e)

        if deleted:
            self._meta["event_count"] = max(0, self._meta.get("event_count", 0) - deleted)
            self._save_index()
            self._save_meta()

        return deleted

    def verify_integrity(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify hash chain integrity."""
        errors = []
        prev_hash = ""

        log_files = sorted(self.storage_path.glob("audit_*.jsonl"))

        for log_file in log_files:
            try:
                file_date_str = log_file.stem.replace("audit_", "")
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if start_date and file_date.date() < start_date.date():
                continue
            if end_date and file_date.date() > end_date.date():
                continue

            try:
                with open(log_file) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            event = self._dict_to_event(data)

                            if event.previous_hash != prev_hash:
                                errors.append(
                                    f"Hash chain broken at event {event.id}: "
                                    f"expected previous_hash={prev_hash}, "
                                    f"got {event.previous_hash}"
                                )

                            computed = event.compute_hash()
                            if event.event_hash != computed:
                                errors.append(
                                    f"Event {event.id} hash mismatch: "
                                    f"stored={event.event_hash}, computed={computed}"
                                )

                            prev_hash = event.event_hash
                        except json.JSONDecodeError:
                            errors.append(f"Invalid JSON in {log_file.name}")
            except OSError as e:
                errors.append(f"Failed to read {log_file}: {e}")

        return len(errors) == 0, errors

    def close(self) -> None:
        """Persist index and meta on close."""
        self._save_index()
        self._save_meta()
        logger.info("File audit backend closed")

    def _dict_to_event(self, data: dict[str, Any]) -> AuditEvent:
        """Convert dictionary to AuditEvent."""
        from aragora.observability.audit_log import AuditCategory, AuditEvent, AuditOutcome

        return AuditEvent(
            id=data.get("id", ""),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else datetime.now(timezone.utc)
            ),
            category=AuditCategory(data.get("category", "system")),
            action=data.get("action", ""),
            actor_id=data.get("actor_id", ""),
            resource_type=data.get("resource_type", ""),
            resource_id=data.get("resource_id", ""),
            outcome=AuditOutcome(data.get("outcome", "success")),
            ip_address=data.get("ip_address", ""),
            user_agent=data.get("user_agent", ""),
            correlation_id=data.get("correlation_id", ""),
            org_id=data.get("org_id", ""),
            workspace_id=data.get("workspace_id", ""),
            details=data.get("details", {}),
            reason=data.get("reason", ""),
            previous_hash=data.get("previous_hash", ""),
            event_hash=data.get("event_hash", ""),
        )

    def get_stats(self) -> dict[str, Any]:
        """Get backend statistics."""
        log_files = list(self.storage_path.glob("audit_*.jsonl"))
        total_size = sum(f.stat().st_size for f in log_files if f.exists())

        oldest = None
        newest = None
        if log_files:
            dates = []
            for f in log_files:
                try:
                    d = datetime.strptime(f.stem.replace("audit_", ""), "%Y-%m-%d")
                    dates.append(d)
                except ValueError as e:
                    logger.debug("Failed to parse datetime value: %s", e)
            if dates:
                oldest = min(dates).isoformat()
                newest = max(dates).isoformat()

        return {
            "backend": "File",
            "storage_path": str(self.storage_path),
            "total_events": self._meta.get("event_count", 0),
            "total_files": len(log_files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "oldest_file": oldest,
            "newest_file": newest,
            "last_hash": self._meta.get("last_hash", "")[:16] + "..."
            if self._meta.get("last_hash")
            else None,
        }
