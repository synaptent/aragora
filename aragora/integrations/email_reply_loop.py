"""
Email Reply Loop for Bidirectional Email Communication.

Enables users to reply to debate emails and have their input routed
back to the appropriate debate. Works with:
- SendGrid Inbound Parse Webhook
- AWS SES with SNS notifications
- Direct IMAP polling (fallback)

Architecture:
    1. User receives debate notification email
    2. User replies to email
    3. Reply is routed to webhook endpoint
    4. Webhook extracts debate_id from email headers/subject
    5. Reply content is added to debate as user input
    6. Result router sends updated debate results back

Usage:
    # At server startup
    from aragora.integrations.email_reply_loop import setup_email_reply_loop
    setup_email_reply_loop()

    # Or manually process an inbound email
    from aragora.integrations.email_reply_loop import process_inbound_email
    await process_inbound_email(email_data)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.exceptions import REDIS_CONNECTION_ERRORS
from aragora.control_plane.leader import (
    is_distributed_state_required,
    DistributedStateError,
)
from aragora.persistence.db_config import get_default_data_dir

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)

# Configuration from environment
EMAIL_INBOUND_SECRET = os.environ.get("EMAIL_INBOUND_SECRET", "")
SENDGRID_INBOUND_SECRET = os.environ.get("SENDGRID_INBOUND_SECRET", EMAIL_INBOUND_SECRET)
SES_NOTIFICATION_SECRET = os.environ.get("SES_NOTIFICATION_SECRET", EMAIL_INBOUND_SECRET)

# Email parsing patterns
DEBATE_ID_PATTERN = re.compile(r"debate[_-]?id[:=\s]*([a-zA-Z0-9_-]+)", re.IGNORECASE)
REPLY_MARKER_PATTERN = re.compile(r"^>.*$|^On .+ wrote:$", re.MULTILINE)
SIGNATURE_PATTERN = re.compile(r"^--\s*$.*", re.DOTALL | re.MULTILINE)


@dataclass
class InboundEmail:
    """Represents a parsed inbound email."""

    message_id: str
    from_email: str
    from_name: str = ""
    to_email: str = ""
    subject: str = ""
    body_plain: str = ""
    body_html: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: bytes | None = None

    @property
    def debate_id(self) -> str | None:
        """Extract debate ID from email headers or subject."""
        # Check X-Aragora-Debate-Id header
        if "X-Aragora-Debate-Id" in self.headers:
            return self.headers["X-Aragora-Debate-Id"]

        # Check In-Reply-To header for debate reference
        if self.in_reply_to:
            match = DEBATE_ID_PATTERN.search(self.in_reply_to)
            if match:
                return match.group(1)

        # Check References header
        for ref in self.references:
            match = DEBATE_ID_PATTERN.search(ref)
            if match:
                return match.group(1)

        # Check subject line
        if self.subject:
            match = DEBATE_ID_PATTERN.search(self.subject)
            if match:
                return match.group(1)

        return None

    @property
    def cleaned_body(self) -> str:
        """Get body with quoted text and signature removed."""
        body = self.body_plain or ""

        # Remove signature
        body = SIGNATURE_PATTERN.sub("", body).strip()

        # Remove quoted reply text
        lines = body.split("\n")
        cleaned_lines = []
        in_quote = False

        for line in lines:
            # Check if this is a quote marker
            if line.strip().startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
                in_quote = True
                continue

            if in_quote and line.strip() == "":
                # Empty line after quote - might be end of quoted section
                continue

            if not line.strip().startswith(">"):
                in_quote = False
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "to_email": self.to_email,
            "subject": self.subject,
            "body_plain": self.body_plain,
            "debate_id": self.debate_id,
            "cleaned_body": self.cleaned_body,
            "received_at": self.received_at.isoformat(),
        }


@dataclass
class EmailReplyOrigin:
    """Tracks an email that expects a reply."""

    debate_id: str
    message_id: str
    recipient_email: str
    recipient_name: str = ""
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reply_received: bool = False
    reply_received_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "debate_id": self.debate_id,
            "message_id": self.message_id,
            "recipient_email": self.recipient_email,
            "recipient_name": self.recipient_name,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "reply_received": self.reply_received,
            "reply_received_at": (
                self.reply_received_at.isoformat() if self.reply_received_at else None
            ),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmailReplyOrigin:
        """Create from dictionary."""
        sent_at = data.get("sent_at")
        reply_received_at = data.get("reply_received_at")
        return cls(
            debate_id=data["debate_id"],
            message_id=data["message_id"],
            recipient_email=data["recipient_email"],
            recipient_name=data.get("recipient_name", ""),
            sent_at=datetime.fromisoformat(sent_at) if sent_at else datetime.now(timezone.utc),
            reply_received=data.get("reply_received", False),
            reply_received_at=(
                datetime.fromisoformat(reply_received_at) if reply_received_at else None
            ),
            metadata=data.get("metadata", {}),
        )


# TTL for email origins in Redis (24 hours)
EMAIL_ORIGIN_TTL_SECONDS = 86400

# In-memory store for tracking reply origins (with Redis persistence)
_reply_origins: dict[str, EmailReplyOrigin] = {}
_reply_origins_lock = asyncio.Lock()


class SQLiteEmailReplyStore:
    """SQLite-backed email reply origin store for durability without Redis."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            data_dir = get_default_data_dir()
            db_path = str(Path(data_dir) / "email_reply_origins.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_reply_origins (
                message_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                recipient_name TEXT,
                sent_at TEXT,
                reply_received INTEGER DEFAULT 0,
                reply_received_at TEXT,
                metadata_json TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_origins_debate ON email_reply_origins(debate_id)"
        )
        conn.commit()
        conn.close()

    def save(self, origin: EmailReplyOrigin) -> None:
        """Save an email reply origin to SQLite."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO email_reply_origins
               (message_id, debate_id, recipient_email, recipient_name,
                sent_at, reply_received, reply_received_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                origin.message_id,
                origin.debate_id,
                origin.recipient_email,
                origin.recipient_name,
                origin.sent_at.isoformat() if origin.sent_at else None,
                1 if origin.reply_received else 0,
                origin.reply_received_at.isoformat() if origin.reply_received_at else None,
                json.dumps(origin.metadata),
            ),
        )
        conn.commit()
        conn.close()

    def get(self, message_id: str) -> EmailReplyOrigin | None:
        """Get an email reply origin by message ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT * FROM email_reply_origins WHERE message_id = ?", (message_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return EmailReplyOrigin(
                message_id=row[0],
                debate_id=row[1],
                recipient_email=row[2],
                recipient_name=row[3] or "",
                sent_at=datetime.fromisoformat(row[4]) if row[4] else datetime.now(timezone.utc),
                reply_received=bool(row[5]),
                reply_received_at=datetime.fromisoformat(row[6]) if row[6] else None,
                metadata=json.loads(row[7]) if row[7] else {},
            )
        return None


class PostgresEmailReplyStore:
    """PostgreSQL-backed email reply origin store for multi-instance deployments."""

    SCHEMA_NAME = "email_reply_origins"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS email_reply_origins (
            message_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            recipient_name TEXT,
            sent_at TIMESTAMPTZ,
            reply_received BOOLEAN DEFAULT FALSE,
            reply_received_at TIMESTAMPTZ,
            metadata_json TEXT,
            expires_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_email_origins_debate ON email_reply_origins(debate_id);
        CREATE INDEX IF NOT EXISTS idx_email_origins_expires ON email_reply_origins(expires_at);
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self._initialized = False
        logger.info("PostgresEmailReplyStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    async def save(self, origin: EmailReplyOrigin) -> None:
        """Save an email reply origin to PostgreSQL."""
        expires_at = datetime.now(timezone.utc).timestamp() + EMAIL_ORIGIN_TTL_SECONDS
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO email_reply_origins
                   (message_id, debate_id, recipient_email, recipient_name,
                    sent_at, reply_received, reply_received_at, metadata_json, expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, to_timestamp($9))
                   ON CONFLICT (message_id) DO UPDATE SET
                    debate_id = EXCLUDED.debate_id,
                    recipient_email = EXCLUDED.recipient_email,
                    recipient_name = EXCLUDED.recipient_name,
                    sent_at = EXCLUDED.sent_at,
                    reply_received = EXCLUDED.reply_received,
                    reply_received_at = EXCLUDED.reply_received_at,
                    metadata_json = EXCLUDED.metadata_json,
                    expires_at = EXCLUDED.expires_at""",
                origin.message_id,
                origin.debate_id,
                origin.recipient_email,
                origin.recipient_name,
                origin.sent_at,
                origin.reply_received,
                origin.reply_received_at,
                json.dumps(origin.metadata),
                expires_at,
            )

    async def get(self, message_id: str) -> EmailReplyOrigin | None:
        """Get an email reply origin by message ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM email_reply_origins WHERE message_id = $1", message_id
            )
            if row:
                return EmailReplyOrigin(
                    message_id=row["message_id"],
                    debate_id=row["debate_id"],
                    recipient_email=row["recipient_email"],
                    recipient_name=row["recipient_name"] or "",
                    sent_at=row["sent_at"] or datetime.now(timezone.utc),
                    reply_received=row["reply_received"],
                    reply_received_at=row["reply_received_at"],
                    metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                )
            return None

    async def cleanup_expired(self) -> int:
        """Remove expired email reply origin records."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM email_reply_origins WHERE expires_at < NOW()")
            count = int(result.split()[-1]) if result else 0
            return count


# Lazy-loaded stores with thread-safe initialization
_sqlite_email_store: SQLiteEmailReplyStore | None = None
_sqlite_email_store_lock = threading.Lock()
_postgres_email_store: PostgresEmailReplyStore | None = None
_postgres_email_store_lock = asyncio.Lock()


def _get_sqlite_email_store() -> SQLiteEmailReplyStore:
    """Get or create the SQLite email reply store (thread-safe)."""
    global _sqlite_email_store
    if _sqlite_email_store is not None:
        return _sqlite_email_store

    with _sqlite_email_store_lock:
        # Double-check after acquiring lock
        if _sqlite_email_store is None:
            _sqlite_email_store = SQLiteEmailReplyStore()
        return _sqlite_email_store


async def _get_postgres_email_store() -> PostgresEmailReplyStore | None:
    """Get or create the PostgreSQL email reply store if configured (thread-safe)."""
    global _postgres_email_store
    if _postgres_email_store is not None:
        return _postgres_email_store

    async with _postgres_email_store_lock:
        # Double-check after acquiring lock
        if _postgres_email_store is not None:
            return _postgres_email_store

        # Check if PostgreSQL is configured
        backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()
        if backend not in ("postgres", "postgresql"):
            return None

        try:
            from aragora.storage.postgres_store import get_postgres_pool

            pool = await get_postgres_pool()
            _postgres_email_store = PostgresEmailReplyStore(pool)
            await _postgres_email_store.initialize()
            logger.info("PostgreSQL email reply store initialized")
            return _postgres_email_store
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "PostgreSQL email reply store connection failed: %s: %s", type(e).__name__, e
            )
            return None
        except Exception as e:  # noqa: BLE001 - asyncpg/psycopg custom exception hierarchies
            logger.warning(
                "PostgreSQL email reply store not available: %s: %s", type(e).__name__, e
            )
            return None


def _get_postgres_email_store_sync() -> PostgresEmailReplyStore | None:
    """Synchronous wrapper for getting PostgreSQL email store."""
    try:
        asyncio.get_running_loop()
        # Can't use run_until_complete in async context
        return _postgres_email_store
    except RuntimeError:
        # No running event loop - safe to use asyncio.run()
        try:
            return asyncio.run(_get_postgres_email_store())
        except RuntimeError:
            # No event loop available
            return None


def _store_email_origin_redis(origin: EmailReplyOrigin) -> None:
    """Store email origin in Redis with TTL."""
    try:
        import redis

        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        key = f"email_origin:{origin.message_id}"
        r.setex(key, EMAIL_ORIGIN_TTL_SECONDS, json.dumps(origin.to_dict()))
    except ImportError:
        raise
    except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
        logger.debug("Redis email origin store failed: %s", e)
        raise


def _load_email_origin_redis(message_id: str) -> EmailReplyOrigin | None:
    """Load email origin from Redis."""
    try:
        import redis

        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        key = f"email_origin:{message_id}"
        data = r.get(key)
        if data:
            return EmailReplyOrigin.from_dict(json.loads(data))
        return None
    except ImportError:
        raise
    except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
        logger.debug("Redis email origin load failed: %s", e)
        raise


def register_email_origin(
    debate_id: str,
    message_id: str,
    recipient_email: str,
    recipient_name: str = "",
    metadata: dict[str, Any] | None = None,
) -> EmailReplyOrigin:
    """
    Register an email as expecting a reply.

    Call this after sending a debate notification email.

    Args:
        debate_id: The debate ID
        message_id: Email Message-ID header
        recipient_email: Recipient email address
        recipient_name: Recipient name
        metadata: Additional metadata

    Returns:
        EmailReplyOrigin tracking object

    Raises:
        DistributedStateError: If distributed state is required but Redis unavailable
    """
    origin = EmailReplyOrigin(
        debate_id=debate_id,
        message_id=message_id,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        metadata=metadata or {},
    )
    _reply_origins[message_id] = origin

    # Try PostgreSQL first if configured
    pg_store = _get_postgres_email_store_sync()
    if pg_store:
        try:
            try:
                asyncio.get_running_loop()
                # Running in async context - schedule as task
                asyncio.create_task(pg_store.save(origin))
            except RuntimeError:
                # Not in async context - run synchronously
                asyncio.run(pg_store.save(origin))
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning(
                "PostgreSQL email origin storage connection error: %s: %s", type(e).__name__, e
            )
        except Exception as e:  # noqa: BLE001 - asyncpg/psycopg custom exception hierarchies
            logger.warning("PostgreSQL email origin storage failed: %s: %s", type(e).__name__, e)
    else:
        # Persist to SQLite for durability (always available)
        try:
            _get_sqlite_email_store().save(origin)
        except sqlite3.Error as e:
            logger.warning("SQLite email origin storage failed: %s: %s", type(e).__name__, e)

    # Persist to Redis for distributed deployments
    redis_success = False
    try:
        _store_email_origin_redis(origin)
        redis_success = True
    except ImportError:
        if is_distributed_state_required():
            raise DistributedStateError(
                "email_reply_loop",
                "Redis library not installed (pip install redis)",
            )
        logger.debug("Redis not available, using SQLite/PostgreSQL only")
    except (*REDIS_CONNECTION_ERRORS, RuntimeError, ValueError) as e:
        if is_distributed_state_required():
            raise DistributedStateError(
                "email_reply_loop",
                f"Redis connection failed: {e}",
            )
        logger.debug("Redis email origin storage not available: %s", e)

    logger.debug(
        "Registered email origin for debate %s: %s (redis=%s)", debate_id, message_id, redis_success
    )
    return origin


async def get_origin_by_reply(in_reply_to: str) -> EmailReplyOrigin | None:
    """Get the origin for an email reply.

    Checks in-memory cache first, then falls back to Redis, PostgreSQL, then SQLite.
    """
    async with _reply_origins_lock:
        # Check in-memory first
        origin = _reply_origins.get(in_reply_to)
        if origin:
            return origin

        # Fall back to Redis
        try:
            origin = _load_email_origin_redis(in_reply_to)
            if origin:
                _reply_origins[in_reply_to] = origin  # Cache locally
                return origin
        except (*REDIS_CONNECTION_ERRORS, RuntimeError, ValueError) as e:
            logger.debug("Redis email origin lookup not available: %s: %s", type(e).__name__, e)

        # Try PostgreSQL if configured
        pg_store = await _get_postgres_email_store()
        if pg_store:
            try:
                origin = await pg_store.get(in_reply_to)
                if origin:
                    _reply_origins[in_reply_to] = origin  # Cache locally
                    return origin
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.debug(
                    "PostgreSQL email origin lookup connection error: %s: %s", type(e).__name__, e
                )
            except Exception as e:  # noqa: BLE001 - asyncpg/psycopg custom exception hierarchies
                logger.debug("PostgreSQL email origin lookup failed: %s: %s", type(e).__name__, e)
        else:
            # Fall back to SQLite
            try:
                origin = _get_sqlite_email_store().get(in_reply_to)
                if origin:
                    _reply_origins[in_reply_to] = origin  # Cache locally
                    return origin
            except sqlite3.Error as e:
                logger.debug("SQLite email origin lookup failed: %s: %s", type(e).__name__, e)

        return None


def parse_raw_email(raw_data: bytes) -> InboundEmail:
    """
    Parse a raw email (RFC 2822 format).

    Args:
        raw_data: Raw email bytes

    Returns:
        InboundEmail object
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw_data)

    # Extract headers
    headers = {}
    for key in msg.keys():
        headers[key] = str(msg[key])

    # Extract body
    body_plain = ""
    body_html = ""
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                attachments.append(
                    {
                        "filename": part.get_filename(),
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True) or b""),
                    }
                )
            elif content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body_plain = payload.decode("utf-8", errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload and isinstance(payload, bytes):
                    body_html = payload.decode("utf-8", errors="replace")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload and isinstance(payload, bytes):
            if content_type == "text/html":
                body_html = payload.decode("utf-8", errors="replace")
            else:
                body_plain = payload.decode("utf-8", errors="replace")

    # Parse From header
    from_header = msg.get("From", "")
    from_email, from_name = _parse_email_address(from_header)

    # Parse references
    references = []
    ref_header = msg.get("References", "")
    if ref_header:
        references = [r.strip() for r in ref_header.split() if r.strip()]

    return InboundEmail(
        message_id=msg.get("Message-ID", f"unknown-{time.time()}"),
        from_email=from_email,
        from_name=from_name,
        to_email=msg.get("To", ""),
        subject=msg.get("Subject", ""),
        body_plain=body_plain,
        body_html=body_html,
        in_reply_to=msg.get("In-Reply-To", ""),
        references=references,
        headers=headers,
        attachments=attachments,
        raw_data=raw_data,
    )


def parse_sendgrid_webhook(data: dict[str, Any]) -> InboundEmail:
    """
    Parse SendGrid Inbound Parse webhook data.

    SendGrid sends form data with email components.

    Args:
        data: Webhook POST data (form fields)

    Returns:
        InboundEmail object
    """
    headers = {}
    if "headers" in data:
        # Parse headers from string
        for line in data["headers"].split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

    envelope = data.get("envelope", "{}")
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except json.JSONDecodeError:
            envelope = {}

    from_email = data.get("from", envelope.get("from", ""))
    from_email, from_name = _parse_email_address(from_email)

    return InboundEmail(
        message_id=headers.get("Message-ID", f"sendgrid-{time.time()}"),
        from_email=from_email,
        from_name=from_name,
        to_email=data.get("to", ""),
        subject=data.get("subject", ""),
        body_plain=data.get("text", ""),
        body_html=data.get("html", ""),
        in_reply_to=headers.get("In-Reply-To", ""),
        references=headers.get("References", "").split() if headers.get("References") else [],
        headers=headers,
        attachments=[],  # Attachments require separate handling
    )


def parse_ses_notification(data: dict[str, Any]) -> InboundEmail | None:
    """
    Parse AWS SES SNS notification.

    SES sends notifications via SNS, which can contain:
    - Bounce/complaint notifications (type: Notification, notificationType: Bounce/Complaint)
    - Delivery notifications (notificationType: Delivery)
    - Email receipt (action: SNS)

    Args:
        data: SNS notification data

    Returns:
        InboundEmail object or None if not an email notification
    """
    # Check message type
    msg_type = data.get("Type", "")
    if msg_type == "SubscriptionConfirmation":
        logger.info("SES SNS subscription confirmation received")
        return None

    # Parse the Message field (it's JSON-encoded)
    message = data.get("Message", "{}")
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except json.JSONDecodeError:
            logger.error("Failed to parse SES notification message")
            return None

    notification_type = message.get("notificationType", "")

    # Handle receipt notification
    if notification_type == "Received" or "mail" in message:
        mail = message.get("mail", {})
        content = message.get("content", "")

        if content:
            # Full email content available, parse it
            return parse_raw_email(content.encode("utf-8"))

        # Otherwise use mail headers
        headers = {}
        for header in mail.get("headers", []):
            headers[header["name"]] = header["value"]

        common_headers = mail.get("commonHeaders", {})

        return InboundEmail(
            message_id=mail.get("messageId", headers.get("Message-ID", "")),
            from_email=common_headers.get("from", [""])[0] if common_headers.get("from") else "",
            to_email=common_headers.get("to", [""])[0] if common_headers.get("to") else "",
            subject=common_headers.get("subject", ""),
            body_plain="",  # Content not included in basic notification
            headers=headers,
            in_reply_to=headers.get("In-Reply-To", ""),
        )

    return None


def _parse_email_address(address: str) -> tuple[str, str]:
    """Parse email address to (email, name)."""
    if not address:
        return "", ""

    # Format: "Name <email@example.com>" or "email@example.com"
    match = re.match(r'"?([^"<]+)"?\s*<([^>]+)>', address)
    if match:
        return match.group(2).strip(), match.group(1).strip()

    # Plain email
    email_match = re.search(r"[\w\.-]+@[\w\.-]+", address)
    if email_match:
        return email_match.group(0), ""

    return address, ""


# Pattern for detecting debate requests in email subject
NEW_DEBATE_PATTERN = re.compile(r"^(?:DEBATE|DISCUSS|ASK|QUESTION)[:\s]+(.+)$", re.IGNORECASE)


async def _try_start_new_debate(email_data: InboundEmail) -> bool:
    """
    Try to start a new debate from an email.

    Recognizes subjects like:
    - "DEBATE: Should we use microservices?"
    - "DISCUSS: Best practices for API design"
    - "ASK: How do we handle authentication?"

    Routes through DecisionRouter for unified handling with caching
    and deduplication across all channels.

    Args:
        email_data: Parsed inbound email

    Returns:
        True if a new debate was started
    """
    # Check if subject indicates a debate request
    subject = email_data.subject or ""
    match = NEW_DEBATE_PATTERN.match(subject.strip())
    if not match:
        return False

    topic = match.group(1).strip()
    if not topic:
        return False

    logger.info("Starting new debate from email: %s...", topic[:80])

    try:
        from aragora.server.middleware.decision_routing import (
            DecisionRoutingMiddleware,
            RoutingContext,
        )

        # Create routing context
        context = RoutingContext(
            channel="email",
            channel_id=email_data.to_email,
            user_id=email_data.from_email,
            request_id=email_data.message_id,
            message_id=email_data.message_id,
            metadata={
                "from_name": email_data.from_name,
                "subject": email_data.subject,
                "via": "email_inbound",
            },
        )

        # Get or create middleware
        middleware = DecisionRoutingMiddleware(
            enable_deduplication=True,
            enable_caching=True,
        )

        # Route through middleware
        result = await middleware.process(
            content=topic,
            context=context,
            decision_type="debate",
        )

        if result.get("success"):
            logger.info(
                "Email debate started: %s from %s",
                result.get("request_id", "unknown"),
                email_data.from_email,
            )

            # Register origin for bidirectional routing
            try:
                from aragora.server.debate_origin import register_debate_origin

                register_debate_origin(
                    debate_id=result.get("request_id", email_data.message_id),
                    platform="email",
                    channel_id=email_data.to_email,
                    user_id=email_data.from_email,
                    message_id=email_data.message_id,
                    metadata={
                        "from_name": email_data.from_name,
                        "subject": email_data.subject,
                        "is_new_debate": True,
                    },
                )
            except ImportError:
                pass

            return True
        else:
            logger.warning("Email debate failed: %s", result.get("error", "unknown error"))
            return False

    except ImportError as e:
        logger.debug("DecisionRouter middleware not available: %s", e)
        return False
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("Email debate connection error: %s: %s", type(e).__name__, e)
        return False
    except (RuntimeError, ValueError, TypeError) as e:
        logger.error("Failed to start email debate: %s: %s", type(e).__name__, e)
        return False


async def process_inbound_email(email_data: InboundEmail) -> bool:
    """
    Process an inbound email and route it to the appropriate debate.

    If the email is not a reply to an existing debate, check if it's a request
    to start a new debate (subject starts with "DEBATE:") and route through
    DecisionRouter.

    Args:
        email_data: Parsed inbound email

    Returns:
        True if email was successfully processed
    """
    debate_id = email_data.debate_id
    if not debate_id:
        # Check if this is a request to start a new debate
        if await _try_start_new_debate(email_data):
            return True
        logger.debug("No debate_id found in email from %s", email_data.from_email)
        return False

    # Check if we have an origin for this reply
    origin = await get_origin_by_reply(email_data.in_reply_to)
    if origin and origin.debate_id != debate_id:
        # In-Reply-To doesn't match, use the origin's debate_id
        debate_id = origin.debate_id

    # Get the cleaned reply content
    content = email_data.cleaned_body
    if not content:
        logger.debug("Empty reply content from %s", email_data.from_email)
        return False

    logger.info(
        "Processing email reply for debate %s from %s: %s chars",
        debate_id,
        email_data.from_email,
        len(content),
    )

    # Route the reply to the debate system
    try:
        from aragora.server.debate_origin import register_debate_origin

        # Register email as the reply origin
        register_debate_origin(
            debate_id=debate_id,
            platform="email",
            channel_id=email_data.from_email,
            user_id=email_data.from_email,
            metadata={
                "message_id": email_data.message_id,
                "subject": email_data.subject,
                "from_name": email_data.from_name,
                "is_reply": True,
            },
        )
    except ImportError:
        logger.debug("debate_origin not available")

    # Submit as user input to the debate
    try:
        from aragora.debate.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.emit(
            "user_input",
            debate_id=debate_id,
            source="email",
            user_id=email_data.from_email,
            user_name=email_data.from_name or email_data.from_email,
            content=content,
            metadata={
                "message_id": email_data.message_id,
                "subject": email_data.subject,
            },
        )
        logger.info("Email reply routed to debate %s", debate_id)
        return True

    except ImportError:
        logger.warning("Event bus not available for email reply routing")
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("Email reply routing connection error: %s: %s", type(e).__name__, e)
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to route email reply: %s: %s", type(e).__name__, e)

    # Alternative: Try queue-based submission
    try:
        import aragora.queue as queue_module

        # create_user_input_job is an optional extension that may not be present
        create_user_input_job = getattr(queue_module, "create_user_input_job", None)
        if create_user_input_job is None:
            raise ImportError("create_user_input_job not available")

        job = create_user_input_job(
            debate_id=debate_id,
            user_id=email_data.from_email,
            content=content,
            source="email",
        )

        # Fire and forget
        async def enqueue() -> None:
            from aragora.queue import create_redis_queue

            q = await create_redis_queue()
            await q.enqueue(job)

        asyncio.create_task(enqueue())
        return True

    except ImportError:
        logger.debug("Queue system not available for email routing")
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("Email queue connection error: %s: %s", type(e).__name__, e)
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to queue email input: %s: %s", type(e).__name__, e)

    return False


def verify_sendgrid_signature(payload: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify SendGrid Event Webhook signature using HMAC-SHA256.

    SendGrid signs Event Webhook payloads by computing an HMAC-SHA256 of the
    timestamp concatenated with the raw request body, using the webhook
    verification key as the HMAC secret. The resulting digest is base64-encoded
    and sent in the X-Twilio-Email-Event-Webhook-Signature header.

    For Inbound Parse webhooks that do not include a signature header,
    verification is skipped when the secret is not configured, preserving
    backward compatibility with unsigned inbound parse callbacks.

    Reference:
        https://docs.sendgrid.com/for-developers/tracking-events/getting-started-event-webhook-security-features

    Args:
        payload: Raw request body bytes
        timestamp: X-Twilio-Email-Event-Webhook-Timestamp header value
        signature: X-Twilio-Email-Event-Webhook-Signature header value (base64-encoded)

    Returns:
        True if signature is valid or verification is not configured
    """
    if not SENDGRID_INBOUND_SECRET:
        logger.warning("SENDGRID_INBOUND_SECRET not configured, skipping verification")
        return True

    if not signature:
        logger.warning("SendGrid webhook missing signature header")
        return False

    if not timestamp:
        logger.warning("SendGrid webhook missing timestamp header")
        return False

    # SendGrid: HMAC-SHA256(key, timestamp + payload), then base64-encode
    signed_payload = timestamp.encode("utf-8") + payload
    computed = hmac.new(
        SENDGRID_INBOUND_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(computed).decode("ascii")

    # Timing-safe comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected_b64)


# Mailgun configuration from environment
MAILGUN_WEBHOOK_SIGNING_KEY = os.environ.get("MAILGUN_WEBHOOK_SIGNING_KEY", "")


def verify_mailgun_signature(
    timestamp: str,
    token: str,
    signature: str,
    *,
    signing_key: str | None = None,
) -> bool:
    """
    Verify Mailgun webhook signature using HMAC-SHA256.

    Mailgun signs webhooks by computing HMAC-SHA256 of the concatenation of
    timestamp and token, using the webhook signing key as the HMAC secret.
    The resulting hex digest must match the signature provided in the POST body.

    Mailgun webhook POST bodies include three verification fields:
      - signature.timestamp: Unix epoch seconds when the event was generated
      - signature.token: A randomly generated string (50 chars)
      - signature.signature: HMAC-SHA256 hex digest for verification

    Reference:
        https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Webhooks/#securing-webhooks

    Args:
        timestamp: Unix timestamp string from the webhook payload
        token: Random token string from the webhook payload
        signature: HMAC-SHA256 hex digest from the webhook payload
        signing_key: Override signing key (defaults to MAILGUN_WEBHOOK_SIGNING_KEY env var)

    Returns:
        True if signature is valid
    """
    key = signing_key or MAILGUN_WEBHOOK_SIGNING_KEY
    if not key:
        logger.warning("MAILGUN_WEBHOOK_SIGNING_KEY not configured, skipping verification")
        return True

    if not timestamp or not token or not signature:
        logger.warning("Mailgun webhook missing required signature fields")
        return False

    # Mailgun: HMAC-SHA256(key, timestamp + token) -> hex digest
    computed = hmac.new(
        key.encode("utf-8"),
        (timestamp + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Timing-safe comparison to prevent timing attacks
    return hmac.compare_digest(signature, computed)


def verify_ses_signature(message: dict[str, Any]) -> bool:
    """
    Verify AWS SNS message signature.

    AWS SNS messages are signed with the certificate URL provided in the message.
    For simplicity, this implementation validates message structure.

    In production, fetch the certificate and validate the signature.

    Args:
        message: SNS notification

    Returns:
        True if message appears valid
    """
    # Basic validation - check required fields
    required = ["Type", "MessageId", "TopicArn", "Timestamp"]
    for field_name in required:
        if field_name not in message:
            return False

    # Validate TopicArn format
    topic_arn = message.get("TopicArn", "")
    if not topic_arn.startswith("arn:aws:sns:"):
        return False

    return True


# Reply handlers registry with thread-safe access
_reply_handlers: list[Callable[[InboundEmail], bool]] = []
_reply_handlers_lock = threading.Lock()


def register_reply_handler(handler: Callable[[InboundEmail], bool]) -> None:
    """
    Register a custom handler for email replies (thread-safe).

    Handlers are called in order until one returns True.

    Args:
        handler: Callable that takes InboundEmail and returns bool
    """
    with _reply_handlers_lock:
        _reply_handlers.append(handler)


async def handle_email_reply(email_data: InboundEmail) -> bool:
    """
    Handle an email reply through registered handlers.

    Args:
        email_data: Parsed inbound email

    Returns:
        True if handled
    """
    # Take a snapshot of handlers to avoid holding lock during iteration
    with _reply_handlers_lock:
        handlers = list(_reply_handlers)

    # Try custom handlers first
    for handler in handlers:
        try:
            if handler(email_data):
                return True
        except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Reply handler error (%s): %s", type(e).__name__, e)

    # Default processing
    return await process_inbound_email(email_data)


def setup_email_reply_loop() -> None:
    """
    Set up the email reply loop.

    Call this at server startup to enable email reply processing.
    This registers the necessary webhook handlers with the server.
    """
    logger.info("Email reply loop initialized")

    # Note: Actual webhook route registration happens in the handler module
    # This function initializes any required state


async def send_debate_result_email(
    debate_id: str,
    result: dict[str, Any],
    recipient_email: str,
) -> dict[str, Any] | None:
    """
    Send a debate result back to the user via email.

    This is called by the routing worker to deliver debate results
    to users who initiated debates via email.

    Args:
        debate_id: The debate ID
        result: Debate result dictionary
        recipient_email: Email address to send to

    Returns:
        Email send result dict, or None if sending failed
    """
    try:
        # Try SendGrid first
        sendgrid_key = os.environ.get("SENDGRID_API_KEY")
        if sendgrid_key:
            return await _send_via_sendgrid(debate_id, result, recipient_email)

        # Try SES
        ses_region = os.environ.get("AWS_SES_REGION")
        if ses_region:
            return await _send_via_ses(debate_id, result, recipient_email)

        # Fallback to SMTP if configured
        smtp_host = os.environ.get("SMTP_HOST")
        if smtp_host:
            return await _send_via_smtp(debate_id, result, recipient_email)

        logger.warning("No email provider configured for sending debate results")
        return None

    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("Debate result email connection error: %s: %s", type(e).__name__, e)
        return None
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to send debate result email: %s: %s", type(e).__name__, e)
        return None


async def _send_via_sendgrid(
    debate_id: str,
    result: dict[str, Any],
    recipient_email: str,
) -> dict[str, Any] | None:
    """Send email via SendGrid API."""
    try:
        from aragora.observability.http_client_pool import get_http_pool
    except ImportError:
        logger.warning("HTTPClientPool not available, cannot send via SendGrid")
        return None

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    from_email = os.environ.get("EMAIL_FROM_ADDRESS", "debates@aragora.ai")
    from_name = os.environ.get("EMAIL_FROM_NAME", "Aragora Debates")

    # Format the result
    subject = f"Debate Result: {debate_id[:16]}..."
    consensus = result.get("consensus", {})
    summary = consensus.get("summary", "No consensus reached")

    body_text = f"""
Debate Result

Debate ID: {debate_id}

Summary:
{summary}

Confidence: {consensus.get("confidence", "N/A")}
Participants: {", ".join(result.get("participants", []))}

---
Reply to this email to continue the discussion.
"""

    pool = get_http_pool()
    async with pool.get_session("sendgrid") as client:
        response = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": recipient_email}]}],
                "from": {"email": from_email, "name": from_name},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body_text}],
                "headers": {
                    "X-Aragora-Debate-Id": debate_id,
                },
            },
            timeout=30.0,
        )

        if response.status_code in (200, 202):
            return {"status": "sent", "provider": "sendgrid"}
        else:
            logger.error("SendGrid error: %s %s", response.status_code, response.text)
            return None


async def _send_via_ses(
    debate_id: str,
    result: dict[str, Any],
    recipient_email: str,
) -> dict[str, Any] | None:
    """Send email via AWS SES."""
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 not installed, cannot send via SES")
        return None

    from_email = os.environ.get("EMAIL_FROM_ADDRESS", "debates@aragora.ai")
    region = os.environ.get("AWS_SES_REGION", "us-east-1")

    # Format the result
    subject = f"Debate Result: {debate_id[:16]}..."
    consensus = result.get("consensus", {})
    summary = consensus.get("summary", "No consensus reached")

    body_text = f"""
Debate Result

Debate ID: {debate_id}

Summary:
{summary}

Confidence: {consensus.get("confidence", "N/A")}
Participants: {", ".join(result.get("participants", []))}

---
Reply to this email to continue the discussion.
"""

    try:
        ses = boto3.client("ses", region_name=region)
        response = ses.send_email(
            Source=from_email,
            Destination={"ToAddresses": [recipient_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            },
        )
        return {"status": "sent", "provider": "ses", "message_id": response["MessageId"]}
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("SES connection error: %s: %s", type(e).__name__, e)
        return None
    except Exception as e:  # noqa: BLE001 - botocore exceptions (ClientError, etc.) may not be importable
        logger.error("SES error (%s): %s", type(e).__name__, e)
        return None


async def _send_via_smtp(
    debate_id: str,
    result: dict[str, Any],
    recipient_email: str,
) -> dict[str, Any] | None:
    """Send email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText

    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    from_email = os.environ.get("EMAIL_FROM_ADDRESS", "debates@aragora.ai")

    # Format the result
    subject = f"Debate Result: {debate_id[:16]}..."
    consensus = result.get("consensus", {})
    summary = consensus.get("summary", "No consensus reached")

    body_text = f"""
Debate Result

Debate ID: {debate_id}

Summary:
{summary}

Confidence: {consensus.get("confidence", "N/A")}
Participants: {", ".join(result.get("participants", []))}

---
Reply to this email to continue the discussion.
"""

    try:
        msg = MIMEText(body_text)
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = recipient_email
        msg["X-Aragora-Debate-Id"] = debate_id

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_pass:
                server.starttls()
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        return {"status": "sent", "provider": "smtp"}
    except smtplib.SMTPAuthenticationError as e:
        logger.error("SMTP authentication error: %s", e)
        return None
    except smtplib.SMTPException as e:
        logger.error("SMTP protocol error: %s: %s", type(e).__name__, e)
        return None
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("SMTP connection error: %s: %s", type(e).__name__, e)
        return None
    return None


__all__ = [
    "InboundEmail",
    "EmailReplyOrigin",
    "parse_raw_email",
    "parse_sendgrid_webhook",
    "parse_ses_notification",
    "process_inbound_email",
    "verify_sendgrid_signature",
    "verify_ses_signature",
    "verify_mailgun_signature",
    "register_email_origin",
    "register_reply_handler",
    "handle_email_reply",
    "setup_email_reply_loop",
    "send_debate_result_email",
]
