"""
Inbox trust wedge for receipt-gated email actions.

Implements the narrow proving path:
Gmail ingest -> debated triage decision -> persisted signed receipt ->
CLI approval or narrow auto-approval -> gmail.modify action.

The wedge is intentionally strict:
- only ARCHIVE, STAR, LABEL, and IGNORE are supported
- execution requires a previously persisted approved receipt
- signatures use a durable local HMAC key by default
- duplicate execution attempts fail closed
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Generator

from aragora.config import resolve_db_path
from aragora.gauntlet.signing import HMACSigner, ReceiptSigner, SignedReceipt
from aragora.services.email_actions import (
    ActionResult,
    EmailActionsService,
    get_email_actions_service,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = resolve_db_path(os.getenv("ARAGORA_INBOX_TRUST_WEDGE_DB", "inbox_trust_wedge.db"))
DEFAULT_SIGNING_KEY_PATH = Path(
    resolve_db_path(
        os.getenv("ARAGORA_INBOX_TRUST_WEDGE_KEY_FILE", "inbox_trust_wedge_signing.key")
    )
)
SIGNING_KEY_ENV_VAR = "ARAGORA_INBOX_TRUST_WEDGE_SIGNING_KEY"
AUTO_APPROVAL_THRESHOLD = float(
    os.getenv("ARAGORA_INBOX_TRUST_WEDGE_AUTO_APPROVAL_THRESHOLD", "0.85")
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class InboxWedgeAction(str, Enum):
    """Allowed inbox trust wedge actions."""

    ARCHIVE = "archive"
    STAR = "star"
    LABEL = "label"
    IGNORE = "ignore"

    @classmethod
    def parse(cls, value: str | InboxWedgeAction) -> InboxWedgeAction:
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported inbox wedge action: {value!r}. "
                "Allowed actions are archive, star, label, ignore."
            ) from exc


# Backward-compatible alias retained for earlier trust-wedge callers.
AllowedAction = InboxWedgeAction


class ReceiptState(str, Enum):
    """Receipt lifecycle state for the inbox wedge."""

    CREATED = "created"
    APPROVED = "approved"
    EXECUTED = "executed"
    EXPIRED = "expired"


@dataclass
class ActionIntent:
    """Canonical execution intent for a single inbox action."""

    provider: str
    message_id: str
    action: InboxWedgeAction
    content_hash: str
    synthesized_rationale: str
    confidence: float
    provider_route: str
    debate_id: str | None = None
    label_id: str | None = None
    user_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        message_id: str,
        action: str | InboxWedgeAction,
        content_hash: str,
        synthesized_rationale: str,
        confidence: float,
        provider_route: str,
        debate_id: str | None = None,
        label_id: str | None = None,
        user_id: str | None = None,
    ) -> ActionIntent:
        return cls(
            provider=provider.strip().lower(),
            message_id=message_id,
            action=InboxWedgeAction.parse(action),
            content_hash=content_hash,
            synthesized_rationale=synthesized_rationale,
            confidence=float(confidence),
            provider_route=provider_route,
            debate_id=debate_id,
            label_id=label_id,
            user_id=user_id,
        )

    @staticmethod
    def compute_content_hash(*parts: str) -> str:
        return _sha256_text("\n".join(part for part in parts if part))

    def to_dict(self) -> dict[str, Any]:
        action = self.action
        action_str = action.value if isinstance(action, Enum) else str(action)
        return {
            "provider": self.provider,
            "message_id": self.message_id,
            "action": action_str,
            "content_hash": self.content_hash,
            "synthesized_rationale": self.synthesized_rationale,
            "confidence": self.confidence,
            "provider_route": self.provider_route,
            "debate_id": self.debate_id,
            "label_id": self.label_id,
            "user_id": self.user_id,
        }

    def intent_hash(self) -> str:
        return _sha256_text(_canonical_json(self.to_dict()))


def compute_content_hash(*parts: str) -> str:
    """Backward-compatible content hash helper for legacy callers."""
    return ActionIntent.compute_content_hash(*parts)


@dataclass(frozen=True)
class PersistedReceipt:
    """Receipt metadata persisted before execution."""

    receipt_id: str
    intent_hash: str
    signature: str
    signing_key_id: str
    state: ReceiptState
    created_at: datetime
    expires_at: datetime | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    execution_count: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "intent_hash": self.intent_hash,
            "signature": self.signature,
            "signing_key_id": self.signing_key_id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": _isoformat(self.expires_at),
            "approved_at": _isoformat(self.approved_at),
            "executed_at": _isoformat(self.executed_at),
            "execution_count": self.execution_count,
            "last_error": self.last_error,
        }


@dataclass
class TriageDecision:
    """Final debated triage decision for the inbox wedge."""

    final_action: InboxWedgeAction
    confidence: float
    dissent_summary: str
    receipt_id: str | None = None
    auto_approval_eligible: bool = False
    receipt_state: str = "created"
    intent: ActionIntent | None = None
    provider_route: str = "direct"
    label_id: str | None = None
    blocked_by_policy: bool = False
    cost_usd: float | None = None
    latency_seconds: float | None = None

    @classmethod
    def create(
        cls,
        *,
        final_action: str | InboxWedgeAction,
        confidence: float,
        dissent_summary: str,
        receipt_id: str | None = None,
        auto_approval_eligible: bool = False,
        receipt_state: str = "created",
        intent: ActionIntent | None = None,
        provider_route: str = "direct",
        label_id: str | None = None,
        blocked_by_policy: bool = False,
        cost_usd: float | None = None,
        latency_seconds: float | None = None,
    ) -> TriageDecision:
        return cls(
            final_action=InboxWedgeAction.parse(final_action),
            confidence=float(confidence),
            dissent_summary=dissent_summary,
            receipt_id=receipt_id,
            auto_approval_eligible=auto_approval_eligible,
            receipt_state=receipt_state,
            intent=intent,
            provider_route=provider_route,
            label_id=label_id,
            blocked_by_policy=blocked_by_policy,
            cost_usd=cost_usd,
            latency_seconds=latency_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "final_action": self.final_action.value
            if isinstance(self.final_action, Enum)
            else self.final_action,
            "confidence": self.confidence,
            "dissent_summary": self.dissent_summary,
            "receipt_id": self.receipt_id,
            "auto_approval_eligible": self.auto_approval_eligible,
            "receipt_state": self.receipt_state,
            "provider_route": self.provider_route,
            "label_id": self.label_id,
            "blocked_by_policy": self.blocked_by_policy,
            "cost_usd": self.cost_usd,
            "latency_seconds": self.latency_seconds,
        }
        if self.intent is not None:
            result["intent"] = self.intent.to_dict()
        return result


@dataclass(frozen=True)
class StoredInboxTrustEnvelope:
    """Combined persisted wedge state."""

    intent: ActionIntent
    decision: TriageDecision
    receipt: PersistedReceipt
    signed_receipt: SignedReceipt
    provider_route: str
    debate_id: str | None = None
    review_choice: str | None = None
    execution_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "decision": self.decision.to_dict(),
            "receipt": self.receipt.to_dict(),
            "signed_receipt": self.signed_receipt.to_dict(),
            "provider_route": self.provider_route,
            "debate_id": self.debate_id,
            "review_choice": self.review_choice,
            "execution_result": self.execution_result,
        }


@dataclass(frozen=True)
class ReceiptValidationResult:
    """Result of wedge receipt validation."""

    valid: bool
    receipt_id: str
    error: str | None = None
    envelope: StoredInboxTrustEnvelope | None = None


def _load_or_create_signing_key(
    env_var: str = SIGNING_KEY_ENV_VAR,
    key_path: Path = DEFAULT_SIGNING_KEY_PATH,
) -> HMACSigner:
    key_hex = os.getenv(env_var)
    if key_hex:
        key_hex = key_hex.strip()
    else:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key_hex = key_path.read_text(encoding="utf-8").strip()
        else:
            key_hex = secrets.token_hex(32)
            key_path.write_text(key_hex, encoding="utf-8")
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                logger.debug("Could not chmod inbox wedge signing key: %s", key_path)

    if len(key_hex) != 64:
        raise ValueError(
            f"Inbox trust wedge signing key must be 64 hex characters, got {len(key_hex)}"
        )

    key_bytes = bytes.fromhex(key_hex)
    key_id = f"inbox-wedge-{hashlib.sha256(key_bytes).hexdigest()[:12]}"
    return HMACSigner(secret_key=key_bytes, key_id=key_id)


_default_signer: ReceiptSigner | None = None
_default_signer_lock = threading.Lock()


def get_inbox_trust_wedge_signer() -> ReceiptSigner:
    """Get the durable signer used for inbox wedge receipts."""
    global _default_signer
    if _default_signer is None:
        with _default_signer_lock:
            if _default_signer is None:
                _default_signer = ReceiptSigner(_load_or_create_signing_key())
    return _default_signer


class InboxTrustWedgeStore:
    """Persistent store for inbox wedge receipts and decisions."""

    def __init__(self, db_path: str | None = None):
        self.db_path = resolve_db_path(db_path or DEFAULT_DB_PATH)
        self._connections: list[sqlite3.Connection] = []
        self._init_lock = threading.Lock()
        self._initialized = False
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"inbox_trust_wedge_conn_{id(self)}",
            default=None,
        )
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS inbox_trust_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        user_id TEXT,
                        message_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        provider_route TEXT NOT NULL,
                        debate_id TEXT,
                        content_hash TEXT NOT NULL,
                        intent_hash TEXT NOT NULL,
                        state TEXT NOT NULL,
                        signature TEXT NOT NULL,
                        signing_key_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        approved_at TEXT,
                        executed_at TEXT,
                        execution_count INTEGER NOT NULL DEFAULT 0,
                        execution_claim_token TEXT,
                        label_id TEXT,
                        review_choice TEXT,
                        last_error TEXT,
                        intent_json TEXT NOT NULL,
                        decision_json TEXT NOT NULL,
                        receipt_payload_json TEXT NOT NULL,
                        signed_receipt_json TEXT NOT NULL,
                        execution_result_json TEXT
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_inbox_trust_state
                    ON inbox_trust_receipts(state, created_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_inbox_trust_message
                    ON inbox_trust_receipts(provider, message_id, created_at DESC)
                    """
                )
            self._initialized = True

    def close(self) -> None:
        self._conn_var.set(None)
        while self._connections:
            conn = self._connections.pop()
            try:
                conn.close()
            except sqlite3.Error:
                logger.debug("Failed to close inbox trust wedge connection", exc_info=True)

    def _build_receipt_payload(
        self,
        *,
        receipt_id: str,
        intent: ActionIntent,
        decision: TriageDecision,
        state: ReceiptState,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        return {
            "receipt_id": receipt_id,
            "intent_hash": intent.intent_hash(),
            "action_intent": intent.to_dict(),
            "triage_decision": decision.to_dict(),
            "state": state.value,
            "created_at": created_at.isoformat(),
            "expires_at": _isoformat(expires_at),
        }

    def create_receipt(
        self,
        intent: ActionIntent,
        decision: TriageDecision,
        *,
        expires_at: datetime | None = None,
        signer: ReceiptSigner | None = None,
    ) -> StoredInboxTrustEnvelope:
        receipt_id = str(uuid.uuid4())
        created_at = _utcnow()
        state = ReceiptState.CREATED
        payload = self._build_receipt_payload(
            receipt_id=receipt_id,
            intent=intent,
            decision=decision,
            state=state,
            created_at=created_at,
            expires_at=expires_at,
        )
        signer = signer or get_inbox_trust_wedge_signer()
        signed_receipt = signer.sign(payload)
        persisted = PersistedReceipt(
            receipt_id=receipt_id,
            intent_hash=intent.intent_hash(),
            signature=signed_receipt.signature,
            signing_key_id=signed_receipt.signature_metadata.key_id,
            state=state,
            created_at=created_at,
            expires_at=expires_at,
        )
        stored_decision = replace(decision, receipt_id=receipt_id)
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO inbox_trust_receipts (
                    receipt_id, provider, user_id, message_id, action, provider_route,
                    debate_id, content_hash, intent_hash, state, signature,
                    signing_key_id, created_at, expires_at, approved_at, executed_at,
                    execution_count, execution_claim_token, label_id, review_choice,
                    last_error, intent_json, decision_json, receipt_payload_json,
                    signed_receipt_json, execution_result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, NULL, ?, ?, ?, ?, NULL)
                """,
                (
                    receipt_id,
                    intent.provider,
                    intent.user_id,
                    intent.message_id,
                    intent.action.value,
                    intent.provider_route,
                    intent.debate_id,
                    intent.content_hash,
                    persisted.intent_hash,
                    persisted.state.value,
                    persisted.signature,
                    persisted.signing_key_id,
                    created_at.isoformat(),
                    _isoformat(expires_at),
                    None,
                    None,
                    intent.label_id or stored_decision.label_id,
                    json.dumps(intent.to_dict(), default=_json_default),
                    json.dumps(stored_decision.to_dict(), default=_json_default),
                    json.dumps(payload, default=_json_default),
                    json.dumps(signed_receipt.to_dict(), default=_json_default),
                ),
            )
        return StoredInboxTrustEnvelope(
            intent=intent,
            decision=stored_decision,
            receipt=persisted,
            signed_receipt=signed_receipt,
            provider_route=intent.provider_route,
            debate_id=intent.debate_id,
        )

    def get_receipt(self, receipt_id: str) -> StoredInboxTrustEnvelope | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                SELECT receipt_id, provider, user_id, message_id, action, provider_route,
                       debate_id, content_hash, intent_hash, state, signature,
                       signing_key_id, created_at, expires_at, approved_at, executed_at,
                       execution_count, label_id, review_choice, last_error,
                       intent_json, decision_json, signed_receipt_json, execution_result_json
                FROM inbox_trust_receipts
                WHERE receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()
        if row is None:
            return None
        intent_dict = json.loads(row["intent_json"])
        decision_dict = json.loads(row["decision_json"])
        signed_receipt = SignedReceipt.from_dict(json.loads(row["signed_receipt_json"]))
        execution_result = (
            json.loads(row["execution_result_json"]) if row["execution_result_json"] else None
        )
        intent = ActionIntent.create(
            provider=intent_dict["provider"],
            message_id=intent_dict["message_id"],
            action=intent_dict["action"],
            content_hash=intent_dict["content_hash"],
            synthesized_rationale=intent_dict.get("synthesized_rationale", ""),
            confidence=float(intent_dict.get("confidence", 0.0)),
            provider_route=intent_dict.get("provider_route", "unknown"),
            debate_id=intent_dict.get("debate_id"),
            label_id=intent_dict.get("label_id"),
            user_id=intent_dict.get("user_id"),
        )
        decision = TriageDecision.create(
            final_action=decision_dict["final_action"],
            confidence=float(decision_dict.get("confidence", 0.0)),
            dissent_summary=decision_dict.get("dissent_summary", ""),
            receipt_id=decision_dict.get("receipt_id"),
            auto_approval_eligible=bool(decision_dict.get("auto_approval_eligible")),
            label_id=decision_dict.get("label_id"),
            blocked_by_policy=bool(decision_dict.get("blocked_by_policy")),
            cost_usd=decision_dict.get("cost_usd"),
            latency_seconds=decision_dict.get("latency_seconds"),
        )
        receipt = PersistedReceipt(
            receipt_id=row["receipt_id"],
            intent_hash=row["intent_hash"],
            signature=row["signature"],
            signing_key_id=row["signing_key_id"],
            state=ReceiptState(row["state"]),
            created_at=_parse_datetime(row["created_at"]) or _utcnow(),
            expires_at=_parse_datetime(row["expires_at"]),
            approved_at=_parse_datetime(row["approved_at"]),
            executed_at=_parse_datetime(row["executed_at"]),
            execution_count=int(row["execution_count"] or 0),
            last_error=row["last_error"],
        )
        return StoredInboxTrustEnvelope(
            intent=intent,
            decision=decision,
            receipt=receipt,
            signed_receipt=signed_receipt,
            provider_route=row["provider_route"],
            debate_id=row["debate_id"],
            review_choice=row["review_choice"],
            execution_result=execution_result,
        )

    def list_receipts(
        self,
        *,
        state: ReceiptState | None = None,
        limit: int = 50,
    ) -> list[StoredInboxTrustEnvelope]:
        query = """
            SELECT receipt_id
            FROM inbox_trust_receipts
        """
        params: list[Any] = []
        if state is not None:
            query += " WHERE state = ?"
            params.append(state.value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cursor:
            rows = cursor.execute(query, tuple(params)).fetchall()
        receipts: list[StoredInboxTrustEnvelope] = []
        for row in rows:
            item = self.get_receipt(row["receipt_id"])
            if item is not None:
                receipts.append(item)
        return receipts

    def approve_receipt(self, receipt_id: str, *, review_choice: str = "approve") -> bool:
        approved_at = _utcnow().isoformat()
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET state = ?, approved_at = ?, review_choice = ?, last_error = NULL
                WHERE receipt_id = ? AND state = ?
                """,
                (
                    ReceiptState.APPROVED.value,
                    approved_at,
                    review_choice,
                    receipt_id,
                    ReceiptState.CREATED.value,
                ),
            )
        return row.rowcount == 1

    def expire_receipt(self, receipt_id: str, *, reason: str | None = None) -> bool:
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET state = ?, review_choice = ?, last_error = ?
                WHERE receipt_id = ? AND state IN (?, ?)
                """,
                (
                    ReceiptState.EXPIRED.value,
                    "reject",
                    reason,
                    receipt_id,
                    ReceiptState.CREATED.value,
                    ReceiptState.APPROVED.value,
                ),
            )
        return row.rowcount == 1

    def update_decision(
        self,
        receipt_id: str,
        *,
        action: str | InboxWedgeAction | None = None,
        synthesized_rationale: str | None = None,
        label_id: str | None = None,
        signer: ReceiptSigner | None = None,
    ) -> StoredInboxTrustEnvelope:
        envelope = self.get_receipt(receipt_id)
        if envelope is None:
            raise ValueError(f"Receipt not found: {receipt_id}")
        if envelope.receipt.state is not ReceiptState.CREATED:
            raise ValueError("Only created receipts can be edited")

        updated_action = InboxWedgeAction.parse(action or envelope.intent.action)
        updated_label = (
            label_id
            if label_id is not None
            else (envelope.intent.label_id or envelope.decision.label_id)
        )
        updated_intent = replace(
            envelope.intent,
            action=updated_action,
            synthesized_rationale=(
                synthesized_rationale
                if synthesized_rationale is not None
                else envelope.intent.synthesized_rationale
            ),
            label_id=updated_label,
        )
        updated_decision = replace(
            envelope.decision,
            final_action=updated_action,
            label_id=updated_label,
        )
        payload = self._build_receipt_payload(
            receipt_id=receipt_id,
            intent=updated_intent,
            decision=updated_decision,
            state=ReceiptState.CREATED,
            created_at=envelope.receipt.created_at,
            expires_at=envelope.receipt.expires_at,
        )
        signer = signer or get_inbox_trust_wedge_signer()
        signed_receipt = signer.sign(payload)
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET action = ?, label_id = ?, intent_hash = ?, signature = ?, signing_key_id = ?,
                    intent_json = ?, decision_json = ?, receipt_payload_json = ?,
                    signed_receipt_json = ?, review_choice = ?, last_error = NULL
                WHERE receipt_id = ? AND state = ?
                """,
                (
                    updated_action.value,
                    updated_label,
                    updated_intent.intent_hash(),
                    signed_receipt.signature,
                    signed_receipt.signature_metadata.key_id,
                    json.dumps(updated_intent.to_dict(), default=_json_default),
                    json.dumps(updated_decision.to_dict(), default=_json_default),
                    json.dumps(payload, default=_json_default),
                    json.dumps(signed_receipt.to_dict(), default=_json_default),
                    "edit",
                    receipt_id,
                    ReceiptState.CREATED.value,
                ),
            )
        updated = self.get_receipt(receipt_id)
        if updated is None:
            raise RuntimeError(f"Edited receipt disappeared: {receipt_id}")
        return updated

    def claim_execution(self, receipt_id: str) -> str | None:
        claim_token = str(uuid.uuid4())
        now_iso = _utcnow().isoformat()
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET execution_claim_token = ?, last_error = NULL
                WHERE receipt_id = ?
                  AND state = ?
                  AND execution_count = 0
                  AND execution_claim_token IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (
                    claim_token,
                    receipt_id,
                    ReceiptState.APPROVED.value,
                    now_iso,
                ),
            )
        if row.rowcount != 1:
            return None
        return claim_token

    def mark_executed(
        self,
        receipt_id: str,
        claim_token: str,
        result: dict[str, Any],
    ) -> bool:
        executed_at = _utcnow().isoformat()
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET state = ?, executed_at = ?, execution_count = execution_count + 1,
                    execution_claim_token = NULL, execution_result_json = ?, review_choice = ?,
                    last_error = NULL
                WHERE receipt_id = ?
                  AND state = ?
                  AND execution_count = 0
                  AND execution_claim_token = ?
                """,
                (
                    ReceiptState.EXECUTED.value,
                    executed_at,
                    json.dumps(result, default=_json_default),
                    "execute",
                    receipt_id,
                    ReceiptState.APPROVED.value,
                    claim_token,
                ),
            )
        return row.rowcount == 1

    def release_execution_claim(
        self,
        receipt_id: str,
        claim_token: str,
        *,
        error: str,
    ) -> bool:
        with self._cursor() as cursor:
            row = cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET execution_claim_token = NULL, last_error = ?
                WHERE receipt_id = ? AND execution_claim_token = ?
                """,
                (error, receipt_id, claim_token),
            )
        return row.rowcount == 1

    def tamper_signed_receipt_for_tests(self, receipt_id: str, *, signature: str) -> None:
        """Test helper to mutate stored signature."""
        envelope = self.get_receipt(receipt_id)
        if envelope is None:
            raise ValueError(f"Receipt not found: {receipt_id}")
        signed_receipt = envelope.signed_receipt.to_dict()
        signed_receipt["signature"] = signature
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET signature = ?, signed_receipt_json = ?
                WHERE receipt_id = ?
                """,
                (
                    signature,
                    json.dumps(signed_receipt, default=_json_default),
                    receipt_id,
                ),
            )

    def tamper_intent_for_tests(self, receipt_id: str, *, action: str) -> None:
        """Test helper to mutate the stored intent without resigning."""
        envelope = self.get_receipt(receipt_id)
        if envelope is None:
            raise ValueError(f"Receipt not found: {receipt_id}")
        intent_dict = envelope.intent.to_dict()
        intent_dict["action"] = action
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE inbox_trust_receipts
                SET action = ?, intent_json = ?
                WHERE receipt_id = ?
                """,
                (action, json.dumps(intent_dict, default=_json_default), receipt_id),
            )


class InboxTrustWedgeService:
    """Service layer for receipt-gated inbox actions."""

    def __init__(
        self,
        *,
        email_actions_service: EmailActionsService | None = None,
        store: InboxTrustWedgeStore | None = None,
        signer: ReceiptSigner | None = None,
        auto_approval_threshold: float = AUTO_APPROVAL_THRESHOLD,
    ):
        self.email_actions_service = email_actions_service or get_email_actions_service()
        self.store = store or get_inbox_trust_wedge_store()
        self.signer = signer or get_inbox_trust_wedge_signer()
        self.auto_approval_threshold = auto_approval_threshold

    def _normalize_action_and_decision(
        self,
        intent: ActionIntent,
        decision: TriageDecision,
    ) -> tuple[ActionIntent, TriageDecision]:
        if intent.action != decision.final_action:
            intent = replace(intent, action=decision.final_action)
        label_id = decision.label_id if decision.label_id is not None else intent.label_id
        intent = replace(intent, label_id=label_id)
        eligible = (
            decision.final_action
            in {
                InboxWedgeAction.ARCHIVE,
                InboxWedgeAction.STAR,
                InboxWedgeAction.IGNORE,
            }
            and decision.confidence >= self.auto_approval_threshold
            and not decision.blocked_by_policy
        )
        decision = replace(
            decision,
            auto_approval_eligible=eligible,
            label_id=label_id,
        )
        return intent, decision

    def create_receipt(
        self,
        intent: ActionIntent,
        decision: TriageDecision,
        *,
        expires_in_hours: float = 24.0,
        auto_approve: bool = False,
    ) -> StoredInboxTrustEnvelope:
        if expires_in_hours <= 0:
            raise ValueError("expires_in_hours must be positive")
        intent, decision = self._normalize_action_and_decision(intent, decision)
        if intent.action == InboxWedgeAction.LABEL and not intent.label_id:
            raise ValueError("LABEL actions require a label_id")
        envelope = self.store.create_receipt(
            intent,
            decision,
            expires_at=_utcnow() + timedelta(hours=expires_in_hours),
            signer=self.signer,
        )
        if auto_approve and envelope.decision.auto_approval_eligible:
            self.store.approve_receipt(envelope.receipt.receipt_id, review_choice="auto_approve")
            approved = self.store.get_receipt(envelope.receipt.receipt_id)
            if approved is not None:
                return approved
        return envelope

    def validate_receipt(
        self,
        receipt_id: str,
        *,
        require_state: ReceiptState = ReceiptState.APPROVED,
    ) -> ReceiptValidationResult:
        envelope = self.store.get_receipt(receipt_id)
        if envelope is None:
            return ReceiptValidationResult(
                valid=False, receipt_id=receipt_id, error="receipt not found"
            )
        if envelope.receipt.execution_count > 0:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="receipt already executed",
                envelope=envelope,
            )
        if envelope.receipt.state is not require_state:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error=f"receipt state must be {require_state.value}",
                envelope=envelope,
            )
        if envelope.receipt.expires_at is not None and envelope.receipt.expires_at <= _utcnow():
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="receipt expired",
                envelope=envelope,
            )
        recomputed_intent_hash = envelope.intent.intent_hash()
        if recomputed_intent_hash != envelope.receipt.intent_hash:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="intent hash mismatch",
                envelope=envelope,
            )
        if envelope.signed_receipt.signature != envelope.receipt.signature:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="stored signature mismatch",
                envelope=envelope,
            )
        if envelope.signed_receipt.signature_metadata.key_id != envelope.receipt.signing_key_id:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="signing key mismatch",
                envelope=envelope,
            )
        if not self.signer.verify(envelope.signed_receipt):
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="signature verification failed",
                envelope=envelope,
            )
        receipt_data = envelope.signed_receipt.receipt_data
        if receipt_data.get("intent_hash") != recomputed_intent_hash:
            return ReceiptValidationResult(
                valid=False,
                receipt_id=receipt_id,
                error="signed receipt intent hash mismatch",
                envelope=envelope,
            )
        return ReceiptValidationResult(valid=True, receipt_id=receipt_id, envelope=envelope)

    def review_receipt(
        self,
        receipt_id: str,
        *,
        choice: str,
        edited_action: str | InboxWedgeAction | None = None,
        edited_rationale: str | None = None,
        label_id: str | None = None,
    ) -> StoredInboxTrustEnvelope:
        normalized_choice = choice.strip().lower()
        if normalized_choice == "approve":
            validation = self.validate_receipt(receipt_id, require_state=ReceiptState.CREATED)
            if not validation.valid:
                raise ValueError(validation.error or "receipt validation failed")
            if not self.store.approve_receipt(receipt_id):
                raise ValueError(f"Could not approve receipt: {receipt_id}")
        elif normalized_choice == "reject":
            if not self.store.expire_receipt(receipt_id, reason="rejected by operator"):
                raise ValueError(f"Could not reject receipt: {receipt_id}")
        elif normalized_choice == "edit":
            if edited_action is None and edited_rationale is None and label_id is None:
                raise ValueError("edit requires at least one of action, rationale, or label_id")
            return self.store.update_decision(
                receipt_id,
                action=edited_action,
                synthesized_rationale=edited_rationale,
                label_id=label_id,
                signer=self.signer,
            )
        elif normalized_choice == "skip":
            pass
        else:
            raise ValueError("choice must be one of approve, reject, edit, skip")

        envelope = self.store.get_receipt(receipt_id)
        if envelope is None:
            raise ValueError(f"Receipt not found after review: {receipt_id}")
        return envelope

    async def execute_receipt(self, receipt_id: str) -> ActionResult:
        validation = self.validate_receipt(receipt_id, require_state=ReceiptState.APPROVED)
        if not validation.valid or validation.envelope is None:
            raise ValueError(validation.error or "receipt validation failed")

        envelope = validation.envelope
        claim_token = self.store.claim_execution(receipt_id)
        if claim_token is None:
            raise ValueError("receipt is not executable or was already claimed")

        try:
            if not envelope.intent.user_id:
                raise ValueError("receipt missing user_id")

            action = envelope.intent.action
            provider = envelope.intent.provider
            user_id = envelope.intent.user_id
            message_id = envelope.intent.message_id

            if action == InboxWedgeAction.ARCHIVE:
                result = await self.email_actions_service.archive(provider, user_id, message_id)
            elif action == InboxWedgeAction.STAR:
                result = await self.email_actions_service.star(provider, user_id, message_id)
            elif action == InboxWedgeAction.LABEL:
                label_id = envelope.intent.label_id or envelope.decision.label_id
                if not label_id:
                    raise ValueError("label action requires label_id")
                result = await self.email_actions_service.add_label(
                    provider,
                    user_id,
                    message_id,
                    label_id,
                )
            elif action == InboxWedgeAction.IGNORE:
                result = await self.email_actions_service.ignore(provider, user_id, message_id)
            else:
                raise ValueError(f"Unsupported inbox wedge action: {action.value}")

            if not result.success:
                raise ValueError(result.error or f"{action.value} failed")

            if not self.store.mark_executed(receipt_id, claim_token, result.to_dict()):
                raise ValueError("failed to mark receipt as executed")

            updated = self.store.get_receipt(receipt_id)
            if updated is None or updated.receipt.state is not ReceiptState.EXECUTED:
                raise ValueError("receipt execution state not persisted")
            return result
        except Exception as exc:
            self.store.release_execution_claim(receipt_id, claim_token, error=str(exc))
            raise


_store_singleton: InboxTrustWedgeStore | None = None
_store_lock = threading.Lock()
_service_singleton: InboxTrustWedgeService | None = None
_service_lock = threading.Lock()


def get_inbox_trust_wedge_store() -> InboxTrustWedgeStore:
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _store_singleton = InboxTrustWedgeStore()
    return _store_singleton


def reset_inbox_trust_wedge_store() -> None:
    global _store_singleton
    with _store_lock:
        if _store_singleton is not None:
            _store_singleton.close()
        _store_singleton = None


def get_inbox_trust_wedge_service() -> InboxTrustWedgeService:
    global _service_singleton
    if _service_singleton is None:
        with _service_lock:
            if _service_singleton is None:
                _service_singleton = InboxTrustWedgeService()
    return _service_singleton


def reset_inbox_trust_wedge_service() -> None:
    global _service_singleton
    with _service_lock:
        _service_singleton = None


__all__ = [
    "ActionIntent",
    "AllowedAction",
    "AUTO_APPROVAL_THRESHOLD",
    "InboxTrustWedgeService",
    "InboxTrustWedgeStore",
    "InboxWedgeAction",
    "PersistedReceipt",
    "ReceiptState",
    "ReceiptValidationResult",
    "StoredInboxTrustEnvelope",
    "TriageDecision",
    "compute_content_hash",
    "get_inbox_trust_wedge_service",
    "get_inbox_trust_wedge_signer",
    "get_inbox_trust_wedge_store",
    "reset_inbox_trust_wedge_service",
    "reset_inbox_trust_wedge_store",
]
