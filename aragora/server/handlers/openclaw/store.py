"""
In-memory storage for OpenClaw Gateway.

Stability: STABLE

Contains:
- OpenClawGatewayStore - in-memory data store
- Global store instance management
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.openclaw.models import (
    Action,
    ActionStatus,
    ApprovalRequest,
    AuditEntry,
    Credential,
    CredentialType,
    Session,
    SessionStatus,
)

logger = logging.getLogger(__name__)


class OpenClawGatewayStore:
    """In-memory store for OpenClaw gateway data.

    In production, this would be replaced with a persistent storage backend
    (PostgreSQL, Redis, etc.).
    """

    # Default session idle timeout: 24 hours (F10)
    DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS = 86400

    def __init__(self, session_idle_timeout: int | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._actions: dict[str, Action] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._credentials: dict[str, Credential] = {}
        self._credential_secrets: dict[str, str] = {}  # Stored separately
        self._audit_log: list[AuditEntry] = []
        self._session_idle_timeout = (
            session_idle_timeout
            if session_idle_timeout is not None
            else self.DEFAULT_SESSION_IDLE_TIMEOUT_SECONDS
        )

    def cleanup_expired_sessions(self) -> int:
        """Close sessions idle past the timeout (F10).

        Returns the number of sessions closed.
        """
        if self._session_idle_timeout <= 0:
            return 0
        now = datetime.now(timezone.utc)
        expired_ids = []
        for sid, session in self._sessions.items():
            if session.status != SessionStatus.ACTIVE:
                continue
            idle_seconds = (now - session.last_activity_at).total_seconds()
            if idle_seconds > self._session_idle_timeout:
                expired_ids.append(sid)

        for sid in expired_ids:
            self._sessions[sid].status = SessionStatus.CLOSED
            self._sessions[sid].updated_at = now
        if expired_ids:
            logger.info(
                "Closed %d idle sessions (timeout=%ds)",
                len(expired_ids),
                self._session_idle_timeout,
            )
        return len(expired_ids)

    # Session methods
    def create_session(
        self,
        user_id: str,
        tenant_id: str | None = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session."""
        now = datetime.now(timezone.utc)
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
            config=config or {},
            metadata=metadata or {},
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        """List sessions with optional filtering."""
        sessions = list(self._sessions.values())

        # Apply filters
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if tenant_id:
            sessions = [s for s in sessions if s.tenant_id == tenant_id]
        if status:
            sessions = [s for s in sessions if s.status == status]

        # Sort by created_at descending
        sessions.sort(key=lambda s: s.created_at, reverse=True)

        total = len(sessions)
        return sessions[offset : offset + limit], total

    def update_session_status(self, session_id: str, status: SessionStatus) -> Session | None:
        """Update session status."""
        session = self._sessions.get(session_id)
        if session:
            session.status = status
            session.updated_at = datetime.now(timezone.utc)
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    # Action methods
    def create_action(
        self,
        session_id: str,
        action_type: str,
        input_data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Action:
        """Create a new action."""
        now = datetime.now(timezone.utc)
        action = Action(
            id=str(uuid.uuid4()),
            session_id=session_id,
            action_type=action_type,
            status=ActionStatus.PENDING,
            input_data=input_data,
            output_data=None,
            error=None,
            created_at=now,
            started_at=None,
            completed_at=None,
            metadata=metadata or {},
        )
        self._actions[action.id] = action
        return action

    def get_action(self, action_id: str) -> Action | None:
        """Get action by ID."""
        return self._actions.get(action_id)

    def update_action(
        self,
        action_id: str,
        status: ActionStatus | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Action | None:
        """Update action state."""
        action = self._actions.get(action_id)
        if action:
            now = datetime.now(timezone.utc)
            if status:
                action.status = status
                if status == ActionStatus.RUNNING and not action.started_at:
                    action.started_at = now
                elif status in (
                    ActionStatus.COMPLETED,
                    ActionStatus.FAILED,
                    ActionStatus.CANCELLED,
                    ActionStatus.TIMEOUT,
                ):
                    action.completed_at = now
            if output_data is not None:
                action.output_data = output_data
            if error is not None:
                action.error = error
            if metadata is not None:
                action.metadata = metadata
        return action

    # Approval methods
    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        """Persist a pending approval record."""
        self._approvals[approval.approval_id] = approval
        return approval

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        """Get approval by ID."""
        return self._approvals.get(approval_id)

    def list_approvals(
        self,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> tuple[list[ApprovalRequest], int]:
        """List approvals with optional filtering."""
        approvals = [
            approval for approval in self._approvals.values() if approval.status == "pending"
        ]
        if tenant_id:
            approvals = [a for a in approvals if a.tenant_id == tenant_id]
        if session_id:
            approvals = [a for a in approvals if a.session_id == session_id]
        approvals.sort(key=lambda a: a.requested_at, reverse=True)
        total = len(approvals)
        return approvals[offset : offset + limit], total

    def update_approval_status(
        self,
        approval_id: str,
        *,
        status: str,
        decided_by: str | None = None,
        reason: str | None = None,
        decided_at: datetime | None = None,
    ) -> ApprovalRequest | None:
        """Update approval decision state."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            return None
        approval.status = status
        approval.decided_by = decided_by
        approval.reason = reason
        approval.decided_at = decided_at or datetime.now(timezone.utc)
        return approval

    # Credential methods
    def store_credential(
        self,
        name: str,
        credential_type: CredentialType,
        secret_value: str,
        user_id: str,
        tenant_id: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Credential:
        """Store a new credential."""
        now = datetime.now(timezone.utc)
        credential = Credential(
            id=str(uuid.uuid4()),
            name=name,
            credential_type=credential_type,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            last_rotated_at=None,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self._credentials[credential.id] = credential
        self._credential_secrets[credential.id] = secret_value
        return credential

    def get_credential(self, credential_id: str) -> Credential | None:
        """Get credential metadata by ID (not the secret)."""
        return self._credentials.get(credential_id)

    def list_credentials(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        credential_type: CredentialType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Credential], int]:
        """List credentials with optional filtering (no secret values)."""
        credentials = list(self._credentials.values())

        # Apply filters
        if user_id:
            credentials = [c for c in credentials if c.user_id == user_id]
        if tenant_id:
            credentials = [c for c in credentials if c.tenant_id == tenant_id]
        if credential_type:
            credentials = [c for c in credentials if c.credential_type == credential_type]

        # Sort by created_at descending
        credentials.sort(key=lambda c: c.created_at, reverse=True)

        total = len(credentials)
        return credentials[offset : offset + limit], total

    def delete_credential(self, credential_id: str) -> bool:
        """Delete a credential."""
        if credential_id in self._credentials:
            del self._credentials[credential_id]
            del self._credential_secrets[credential_id]
            return True
        return False

    def rotate_credential(self, credential_id: str, new_secret_value: str) -> Credential | None:
        """Rotate a credential's secret value."""
        credential = self._credentials.get(credential_id)
        if credential:
            now = datetime.now(timezone.utc)
            credential.last_rotated_at = now
            credential.updated_at = now
            self._credential_secrets[credential_id] = new_secret_value
        return credential

    # Audit methods
    def add_audit_entry(
        self,
        action: str,
        actor_id: str,
        resource_type: str,
        resource_id: str | None = None,
        result: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Add an audit log entry."""
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            details=details or {},
        )
        self._audit_log.append(entry)
        # Keep only last 10000 entries
        if len(self._audit_log) > 10000:
            logger.warning(
                "In-memory audit log exceeded 10,000 entries; oldest entries dropped. "
                "Use OpenClawPersistentStore for unlimited audit retention."
            )
            self._audit_log = self._audit_log[-10000:]
        return entry

    def get_audit_log(
        self,
        action: str | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        """Get audit log entries with optional filtering."""
        entries = self._audit_log.copy()

        # Apply filters
        if action:
            entries = [e for e in entries if e.action == action]
        if actor_id:
            entries = [e for e in entries if e.actor_id == actor_id]
        if resource_type:
            entries = [e for e in entries if e.resource_type == resource_type]

        # Sort by timestamp descending (most recent first)
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        total = len(entries)
        return entries[offset : offset + limit], total

    # Metrics
    def get_metrics(self) -> dict[str, Any]:
        """Get gateway metrics."""
        active_sessions = sum(
            1 for s in self._sessions.values() if s.status == SessionStatus.ACTIVE
        )
        pending_actions = sum(1 for a in self._actions.values() if a.status == ActionStatus.PENDING)
        running_actions = sum(1 for a in self._actions.values() if a.status == ActionStatus.RUNNING)

        return {
            "sessions": {
                "total": len(self._sessions),
                "active": active_sessions,
                "by_status": {
                    status.value: sum(1 for s in self._sessions.values() if s.status == status)
                    for status in SessionStatus
                },
            },
            "actions": {
                "total": len(self._actions),
                "pending": pending_actions,
                "running": running_actions,
                "by_status": {
                    status.value: sum(1 for a in self._actions.values() if a.status == status)
                    for status in ActionStatus
                },
            },
            "credentials": {
                "total": len(self._credentials),
                "by_type": {
                    ctype.value: sum(
                        1 for c in self._credentials.values() if c.credential_type == ctype
                    )
                    for ctype in CredentialType
                },
            },
            "audit_log_entries": len(self._audit_log),
        }


# ---------------------------------------------------------------------------
# Persistent Store Implementation
# ---------------------------------------------------------------------------


class OpenClawPersistentStore:
    """Persistent SQLite store for OpenClaw gateway data.

    Provides the same interface as OpenClawGatewayStore but persists data
    to SQLite. Supports LRU caching for hot reads.

    Usage:
        store = OpenClawPersistentStore()  # Uses default SQLite path
        store = OpenClawPersistentStore(db_path="/path/to/db.sqlite")
    """

    def __init__(
        self,
        db_path: str | None = None,
        cache_size: int = 500,
    ) -> None:
        import threading
        from collections import OrderedDict
        from pathlib import Path

        from aragora.config import resolve_db_path

        self._db_path = Path(db_path or resolve_db_path("openclaw_gateway.db"))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory LRU cache
        self._session_cache: OrderedDict[str, Session] = OrderedDict()
        self._action_cache: OrderedDict[str, Action] = OrderedDict()
        self._cache_size = cache_size
        self._cache_lock = threading.Lock()

        # Initialize database
        self._init_db()

    def _get_connection(self) -> Any:
        """Get a database connection."""
        import sqlite3

        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS openclaw_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_activity_at TEXT NOT NULL,
                    config_json TEXT,
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON openclaw_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_status ON openclaw_sessions(status);

                CREATE TABLE IF NOT EXISTS openclaw_actions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    metadata_json TEXT,
                    FOREIGN KEY (session_id) REFERENCES openclaw_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_actions_session ON openclaw_actions(session_id);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON openclaw_actions(status);

                CREATE TABLE IF NOT EXISTS openclaw_approvals (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT,
                    action_type TEXT NOT NULL,
                    normalized_action_type TEXT NOT NULL,
                    action_data_json TEXT NOT NULL,
                    metadata_json TEXT,
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    reason TEXT,
                    FOREIGN KEY (action_id) REFERENCES openclaw_actions(id),
                    FOREIGN KEY (session_id) REFERENCES openclaw_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON openclaw_approvals(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON openclaw_approvals(status);
                CREATE INDEX IF NOT EXISTS idx_approvals_requested_at ON openclaw_approvals(requested_at DESC);

                CREATE TABLE IF NOT EXISTS openclaw_credentials (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    credential_type TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT,
                    secret_encrypted TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_rotated_at TEXT,
                    expires_at TEXT,
                    metadata_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_creds_user ON openclaw_credentials(user_id);
                CREATE INDEX IF NOT EXISTS idx_creds_type ON openclaw_credentials(credential_type);

                CREATE TABLE IF NOT EXISTS openclaw_audit (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    result TEXT NOT NULL,
                    details_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON openclaw_audit(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_actor ON openclaw_audit(actor_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def _encrypt_secret(self, value: str) -> str:
        """Encrypt a secret value for storage."""
        try:
            from aragora.security.encryption import encrypt_value

            return encrypt_value(value)
        except ImportError:
            # SECURITY: base64 is NOT encryption. Log a critical warning so
            # operators know secrets are stored without confidentiality protection.
            import base64
            import os

            logger.critical(
                "cryptography library unavailable — credential secrets are stored "
                "with base64 encoding only (NOT encrypted). Install the "
                "'cryptography' package to enable AES-256-GCM encryption."
            )
            if os.environ.get("ARAGORA_ENV", "").lower() in ("production", "prod"):
                raise RuntimeError(
                    "Encryption library unavailable in production. "
                    "Install the 'cryptography' package or set "
                    "ARAGORA_ENV to a non-production value."
                )
            return base64.b64encode(value.encode()).decode()

    def _decrypt_secret(self, encrypted: str) -> str:
        """Decrypt a stored secret value."""
        try:
            from aragora.security.encryption import decrypt_value

            return decrypt_value(encrypted)
        except ImportError:
            import base64

            logger.warning(
                "Decrypting credential with base64 fallback — "
                "secret was stored without real encryption."
            )
            return base64.b64decode(encrypted.encode()).decode()

    def _cache_session(self, session: Session) -> None:
        """Add session to LRU cache."""
        with self._cache_lock:
            self._session_cache[session.id] = session
            self._session_cache.move_to_end(session.id)
            while len(self._session_cache) > self._cache_size:
                self._session_cache.popitem(last=False)

    def _cache_action(self, action: Action) -> None:
        """Add action to LRU cache."""
        with self._cache_lock:
            self._action_cache[action.id] = action
            self._action_cache.move_to_end(action.id)
            while len(self._action_cache) > self._cache_size:
                self._action_cache.popitem(last=False)

    # Session methods
    def create_session(
        self,
        user_id: str,
        tenant_id: str | None = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new session."""
        import json

        now = datetime.now(timezone.utc)
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
            config=config or {},
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO openclaw_sessions
                   (id, user_id, tenant_id, status, created_at, updated_at,
                    last_activity_at, config_json, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.user_id,
                    session.tenant_id,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.last_activity_at.isoformat(),
                    json.dumps(session.config),
                    json.dumps(session.metadata),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._cache_session(session)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID."""
        import json

        # Check cache first
        with self._cache_lock:
            if session_id in self._session_cache:
                self._session_cache.move_to_end(session_id)
                return self._session_cache[session_id]

        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM openclaw_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None

            session = Session(
                id=row["id"],
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                status=SessionStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                last_activity_at=datetime.fromisoformat(row["last_activity_at"]),
                config=json.loads(row["config_json"] or "{}"),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            self._cache_session(session)
            return session
        finally:
            conn.close()

    def list_sessions(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Session], int]:
        """List sessions with optional filtering."""
        import json

        conn = self._get_connection()
        try:
            # Build query
            where_clauses = []
            params: list[Any] = []
            if user_id:
                where_clauses.append("user_id = ?")
                params.append(user_id)
            if tenant_id:
                where_clauses.append("tenant_id = ?")
                params.append(tenant_id)
            if status:
                where_clauses.append("status = ?")
                params.append(status.value)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            # Get total count
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM openclaw_sessions WHERE {where_sql}",  # noqa: S608 -- internal clause
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0

            # Get paginated results
            rows = conn.execute(
                f"""SELECT * FROM openclaw_sessions
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",  # noqa: S608 -- internal query construction
                params + [limit, offset],
            ).fetchall()

            sessions = []
            for row in rows:
                session = Session(
                    id=row["id"],
                    user_id=row["user_id"],
                    tenant_id=row["tenant_id"],
                    status=SessionStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    last_activity_at=datetime.fromisoformat(row["last_activity_at"]),
                    config=json.loads(row["config_json"] or "{}"),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
                sessions.append(session)

            return sessions, total
        finally:
            conn.close()

    def update_session_status(self, session_id: str, status: SessionStatus) -> Session | None:
        """Update session status."""
        now = datetime.now(timezone.utc)
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE openclaw_sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now.isoformat(), session_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Invalidate cache and reload
        with self._cache_lock:
            self._session_cache.pop(session_id, None)
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM openclaw_sessions WHERE id = ?", (session_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
        finally:
            conn.close()

        if deleted:
            with self._cache_lock:
                self._session_cache.pop(session_id, None)
        return deleted

    # Action methods
    def create_action(
        self,
        session_id: str,
        action_type: str,
        input_data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Action:
        """Create a new action."""
        import json

        now = datetime.now(timezone.utc)
        action = Action(
            id=str(uuid.uuid4()),
            session_id=session_id,
            action_type=action_type,
            status=ActionStatus.PENDING,
            input_data=input_data,
            output_data=None,
            error=None,
            created_at=now,
            started_at=None,
            completed_at=None,
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO openclaw_actions
                   (id, session_id, action_type, status, input_json, output_json,
                    error, created_at, started_at, completed_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action.id,
                    action.session_id,
                    action.action_type,
                    action.status.value,
                    json.dumps(action.input_data),
                    None,
                    None,
                    action.created_at.isoformat(),
                    None,
                    None,
                    json.dumps(action.metadata),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._cache_action(action)
        return action

    def get_action(self, action_id: str) -> Action | None:
        """Get action by ID."""
        import json

        # Check cache first
        with self._cache_lock:
            if action_id in self._action_cache:
                self._action_cache.move_to_end(action_id)
                return self._action_cache[action_id]

        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM openclaw_actions WHERE id = ?", (action_id,)
            ).fetchone()
            if not row:
                return None

            action = Action(
                id=row["id"],
                session_id=row["session_id"],
                action_type=row["action_type"],
                status=ActionStatus(row["status"]),
                input_data=json.loads(row["input_json"] or "{}"),
                output_data=json.loads(row["output_json"]) if row["output_json"] else None,
                error=row["error"],
                created_at=datetime.fromisoformat(row["created_at"]),
                started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            self._cache_action(action)
            return action
        finally:
            conn.close()

    def update_action(
        self,
        action_id: str,
        status: ActionStatus | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Action | None:
        """Update action state."""
        import json

        action = self.get_action(action_id)
        if not action:
            return None

        now = datetime.now(timezone.utc)
        updates: list[str] = []
        params: list[Any] = []

        if status:
            updates.append("status = ?")
            params.append(status.value)
            if status == ActionStatus.RUNNING and not action.started_at:
                updates.append("started_at = ?")
                params.append(now.isoformat())
            elif status in (
                ActionStatus.COMPLETED,
                ActionStatus.FAILED,
                ActionStatus.CANCELLED,
                ActionStatus.TIMEOUT,
            ):
                updates.append("completed_at = ?")
                params.append(now.isoformat())

        if output_data is not None:
            updates.append("output_json = ?")
            params.append(json.dumps(output_data))

        if error is not None:
            updates.append("error = ?")
            params.append(error)

        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        if not updates:
            return action

        params.append(action_id)
        conn = self._get_connection()
        try:
            conn.execute(
                f"UPDATE openclaw_actions SET {', '.join(updates)} WHERE id = ?",  # noqa: S608 -- dynamic clause from internal state
                params,
            )
            conn.commit()
        finally:
            conn.close()

        # Invalidate cache and reload
        with self._cache_lock:
            self._action_cache.pop(action_id, None)
        return self.get_action(action_id)

    # Approval methods
    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        """Persist a pending approval record."""
        import json

        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO openclaw_approvals
                   (id, action_id, session_id, user_id, tenant_id, action_type,
                    normalized_action_type, action_data_json, metadata_json, status,
                    requested_at, decided_at, decided_by, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    approval.approval_id,
                    approval.action_id,
                    approval.session_id,
                    approval.user_id,
                    approval.tenant_id,
                    approval.action_type,
                    approval.normalized_action_type,
                    json.dumps(approval.action_data),
                    json.dumps(approval.metadata),
                    approval.status,
                    approval.requested_at.isoformat(),
                    approval.decided_at.isoformat() if approval.decided_at else None,
                    approval.decided_by,
                    approval.reason,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return approval

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        """Get approval metadata by ID."""
        import json

        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM openclaw_approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if not row:
                return None
            return ApprovalRequest(
                approval_id=row["id"],
                action_id=row["action_id"],
                session_id=row["session_id"],
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                action_type=row["action_type"],
                normalized_action_type=row["normalized_action_type"],
                action_data=json.loads(row["action_data_json"] or "{}"),
                metadata=json.loads(row["metadata_json"] or "{}"),
                status=row["status"],
                requested_at=datetime.fromisoformat(row["requested_at"]),
                decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
                decided_by=row["decided_by"],
                reason=row["reason"],
            )
        finally:
            conn.close()

    def list_approvals(
        self,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> tuple[list[ApprovalRequest], int]:
        """List approvals with optional filtering."""
        import json

        clauses: list[str] = ["status = ?"]
        params: list[Any] = ["pending"]
        if tenant_id is not None:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        conn = self._get_connection()
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM openclaw_approvals {where}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"""SELECT * FROM openclaw_approvals {where}
                    ORDER BY requested_at DESC
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
            approvals = [
                ApprovalRequest(
                    approval_id=row["id"],
                    action_id=row["action_id"],
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    tenant_id=row["tenant_id"],
                    action_type=row["action_type"],
                    normalized_action_type=row["normalized_action_type"],
                    action_data=json.loads(row["action_data_json"] or "{}"),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                    status=row["status"],
                    requested_at=datetime.fromisoformat(row["requested_at"]),
                    decided_at=datetime.fromisoformat(row["decided_at"])
                    if row["decided_at"]
                    else None,
                    decided_by=row["decided_by"],
                    reason=row["reason"],
                )
                for row in rows
            ]
            return approvals, int(total_row["count"] if total_row is not None else 0)
        finally:
            conn.close()

    def update_approval_status(
        self,
        approval_id: str,
        *,
        status: str,
        decided_by: str | None = None,
        reason: str | None = None,
        decided_at: datetime | None = None,
    ) -> ApprovalRequest | None:
        """Update approval decision state."""
        approval = self.get_approval(approval_id)
        if approval is None:
            return None

        approval.status = status
        approval.decided_by = decided_by
        approval.reason = reason
        approval.decided_at = decided_at or datetime.now(timezone.utc)

        import json

        conn = self._get_connection()
        try:
            conn.execute(
                """UPDATE openclaw_approvals
                   SET status = ?, decided_at = ?, decided_by = ?, reason = ?, metadata_json = ?
                   WHERE id = ?""",
                (
                    approval.status,
                    approval.decided_at.isoformat() if approval.decided_at else None,
                    approval.decided_by,
                    approval.reason,
                    json.dumps(approval.metadata),
                    approval_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return approval

    # Credential methods
    def store_credential(
        self,
        name: str,
        credential_type: CredentialType,
        secret_value: str,
        user_id: str,
        tenant_id: str | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Credential:
        """Store a new credential."""
        import json

        now = datetime.now(timezone.utc)
        credential = Credential(
            id=str(uuid.uuid4()),
            name=name,
            credential_type=credential_type,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            last_rotated_at=None,
            expires_at=expires_at,
            metadata=metadata or {},
        )

        encrypted = self._encrypt_secret(secret_value)

        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO openclaw_credentials
                   (id, name, credential_type, user_id, tenant_id, secret_encrypted,
                    created_at, updated_at, last_rotated_at, expires_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    credential.id,
                    credential.name,
                    credential.credential_type.value,
                    credential.user_id,
                    credential.tenant_id,
                    encrypted,
                    credential.created_at.isoformat(),
                    credential.updated_at.isoformat(),
                    None,
                    credential.expires_at.isoformat() if credential.expires_at else None,
                    json.dumps(credential.metadata),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return credential

    def get_credential(self, credential_id: str) -> Credential | None:
        """Get credential metadata by ID (not the secret)."""
        import json

        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM openclaw_credentials WHERE id = ?", (credential_id,)
            ).fetchone()
            if not row:
                return None

            return Credential(
                id=row["id"],
                name=row["name"],
                credential_type=CredentialType(row["credential_type"]),
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                last_rotated_at=datetime.fromisoformat(row["last_rotated_at"])
                if row["last_rotated_at"]
                else None,
                expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
        finally:
            conn.close()

    def list_credentials(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        credential_type: CredentialType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Credential], int]:
        """List credentials with optional filtering (no secret values)."""
        import json

        conn = self._get_connection()
        try:
            where_clauses = []
            params: list[Any] = []
            if user_id:
                where_clauses.append("user_id = ?")
                params.append(user_id)
            if tenant_id:
                where_clauses.append("tenant_id = ?")
                params.append(tenant_id)
            if credential_type:
                where_clauses.append("credential_type = ?")
                params.append(credential_type.value)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            count_row = conn.execute(
                f"SELECT COUNT(*) FROM openclaw_credentials WHERE {where_sql}",  # noqa: S608 -- internal clause
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0

            rows = conn.execute(
                f"""SELECT * FROM openclaw_credentials
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",  # noqa: S608 -- internal query construction
                params + [limit, offset],
            ).fetchall()

            credentials = []
            for row in rows:
                credentials.append(
                    Credential(
                        id=row["id"],
                        name=row["name"],
                        credential_type=CredentialType(row["credential_type"]),
                        user_id=row["user_id"],
                        tenant_id=row["tenant_id"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        last_rotated_at=datetime.fromisoformat(row["last_rotated_at"])
                        if row["last_rotated_at"]
                        else None,
                        expires_at=datetime.fromisoformat(row["expires_at"])
                        if row["expires_at"]
                        else None,
                        metadata=json.loads(row["metadata_json"] or "{}"),
                    )
                )

            return credentials, total
        finally:
            conn.close()

    def delete_credential(self, credential_id: str) -> bool:
        """Delete a credential."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM openclaw_credentials WHERE id = ?", (credential_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def rotate_credential(self, credential_id: str, new_secret_value: str) -> Credential | None:
        """Rotate a credential's secret value."""
        now = datetime.now(timezone.utc)
        encrypted = self._encrypt_secret(new_secret_value)

        conn = self._get_connection()
        try:
            conn.execute(
                """UPDATE openclaw_credentials
                   SET secret_encrypted = ?, last_rotated_at = ?, updated_at = ?
                   WHERE id = ?""",
                (encrypted, now.isoformat(), now.isoformat(), credential_id),
            )
            conn.commit()
        finally:
            conn.close()

        return self.get_credential(credential_id)

    # Audit methods
    def add_audit_entry(
        self,
        action: str,
        actor_id: str,
        resource_type: str,
        resource_id: str | None = None,
        result: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Add an audit log entry."""
        import json

        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            details=details or {},
        )

        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO openclaw_audit
                   (id, timestamp, action, actor_id, resource_type, resource_id, result, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.timestamp.isoformat(),
                    entry.action,
                    entry.actor_id,
                    entry.resource_type,
                    entry.resource_id,
                    entry.result,
                    json.dumps(entry.details),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return entry

    def get_audit_log(
        self,
        action: str | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        """Get audit log entries with optional filtering."""
        import json

        conn = self._get_connection()
        try:
            where_clauses = []
            params: list[Any] = []
            if action:
                where_clauses.append("action = ?")
                params.append(action)
            if actor_id:
                where_clauses.append("actor_id = ?")
                params.append(actor_id)
            if resource_type:
                where_clauses.append("resource_type = ?")
                params.append(resource_type)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            count_row = conn.execute(
                f"SELECT COUNT(*) FROM openclaw_audit WHERE {where_sql}",  # noqa: S608 -- internal clause
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0

            rows = conn.execute(
                f"""SELECT * FROM openclaw_audit
                    WHERE {where_sql}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?""",  # noqa: S608 -- internal query construction
                params + [limit, offset],
            ).fetchall()

            entries = []
            for row in rows:
                entries.append(
                    AuditEntry(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        action=row["action"],
                        actor_id=row["actor_id"],
                        resource_type=row["resource_type"],
                        resource_id=row["resource_id"],
                        result=row["result"],
                        details=json.loads(row["details_json"] or "{}"),
                    )
                )

            return entries, total
        finally:
            conn.close()

    def get_metrics(self) -> dict[str, Any]:
        """Get gateway metrics."""
        conn = self._get_connection()
        try:
            # Session counts
            session_counts = {}
            for sess_status in SessionStatus:
                row = conn.execute(
                    "SELECT COUNT(*) FROM openclaw_sessions WHERE status = ?",
                    (sess_status.value,),
                ).fetchone()
                session_counts[sess_status.value] = row[0] if row else 0

            total_sessions = sum(session_counts.values())
            active_sessions = session_counts.get(SessionStatus.ACTIVE.value, 0)

            # Action counts
            action_counts = {}
            for action_status in ActionStatus:
                row = conn.execute(
                    "SELECT COUNT(*) FROM openclaw_actions WHERE status = ?",
                    (action_status.value,),
                ).fetchone()
                action_counts[action_status.value] = row[0] if row else 0

            total_actions = sum(action_counts.values())
            pending_actions = action_counts.get(ActionStatus.PENDING.value, 0)
            running_actions = action_counts.get(ActionStatus.RUNNING.value, 0)

            # Credential counts
            cred_counts = {}
            for ctype in CredentialType:
                row = conn.execute(
                    "SELECT COUNT(*) FROM openclaw_credentials WHERE credential_type = ?",
                    (ctype.value,),
                ).fetchone()
                cred_counts[ctype.value] = row[0] if row else 0

            total_credentials = sum(cred_counts.values())

            # Audit count
            audit_row = conn.execute("SELECT COUNT(*) FROM openclaw_audit").fetchone()
            audit_count = audit_row[0] if audit_row else 0

            return {
                "sessions": {
                    "total": total_sessions,
                    "active": active_sessions,
                    "by_status": session_counts,
                },
                "actions": {
                    "total": total_actions,
                    "pending": pending_actions,
                    "running": running_actions,
                    "by_status": action_counts,
                },
                "credentials": {
                    "total": total_credentials,
                    "by_type": cred_counts,
                },
                "audit_log_entries": audit_count,
            }
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Global store instance
# ---------------------------------------------------------------------------

_store: OpenClawGatewayStore | OpenClawPersistentStore | None = None


def _get_store() -> OpenClawGatewayStore | OpenClawPersistentStore:
    """Get or create the global store instance.

    Uses OpenClawPersistentStore (SQLite) by default. Set
    ARAGORA_OPENCLAW_STORE=memory to use the in-memory store.
    """
    import os

    # Allow test overrides via the compatibility shim module.
    try:
        import sys

        gateway_module = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        override = getattr(gateway_module, "_get_store", None) if gateway_module else None
        if override is not None and override is not _get_store:
            return override()
    except (ImportError, AttributeError, TypeError, KeyError) as e:
        logging.getLogger(__name__).debug("Failed to resolve _get_store override: %s", e)

    global _store
    if _store is None:
        store_type = os.environ.get("ARAGORA_OPENCLAW_STORE", "persistent").lower()
        if store_type == "memory":
            _store = OpenClawGatewayStore()
        else:
            _store = OpenClawPersistentStore()
    return _store


__all__ = [
    "OpenClawGatewayStore",
    "OpenClawPersistentStore",
    "_get_store",
]
