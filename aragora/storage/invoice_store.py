"""
Invoice Storage Backends (Accounts Payable).

Persistent storage for AP invoices with PO matching and anomaly detection.

Backends:
- InMemoryInvoiceStore: For testing
- SQLiteInvoiceStore: For single-instance deployments
- PostgresInvoiceStore: For multi-instance production

Usage:
    from aragora.storage.invoice_store import get_invoice_store

    store = get_invoice_store()
    await store.save(invoice_data)
    invoice = await store.get("inv_123")
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.config import resolve_db_path
from aragora.storage.invoice_common import (
    DecimalEncoder,
    decimal_decoder,
)

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)

# Global singleton
_invoice_store: InvoiceStoreBackend | None = None
_store_lock = threading.RLock()


class InvoiceStoreBackend(ABC):
    """Abstract base class for invoice storage backends."""

    @abstractmethod
    async def get(self, invoice_id: str) -> dict[str, Any] | None:
        """Get invoice by ID."""
        pass

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None:
        """Save invoice data."""
        pass

    @abstractmethod
    async def delete(self, invoice_id: str) -> bool:
        """Delete invoice."""
        pass

    @abstractmethod
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all invoices with pagination."""
        pass

    @abstractmethod
    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List invoices by status."""
        pass

    @abstractmethod
    async def list_by_vendor(
        self,
        vendor_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List invoices by vendor."""
        pass

    @abstractmethod
    async def list_pending_approval(self) -> list[dict[str, Any]]:
        """List invoices pending approval."""
        pass

    @abstractmethod
    async def list_scheduled_payments(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """List invoices with scheduled payments."""
        pass

    @abstractmethod
    async def find_duplicates(
        self,
        vendor_id: str,
        invoice_number: str,
        total_amount: Decimal,
    ) -> list[dict[str, Any]]:
        """Find potential duplicate invoices."""
        pass

    @abstractmethod
    async def get_by_po(self, po_number: str) -> list[dict[str, Any]]:
        """Get invoices by PO number."""
        pass

    @abstractmethod
    async def update_status(
        self,
        invoice_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        """Update invoice status."""
        pass

    @abstractmethod
    async def schedule_payment(
        self,
        invoice_id: str,
        payment_date: datetime,
    ) -> bool:
        """Schedule invoice for payment."""
        pass

    @abstractmethod
    async def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: datetime,
        payment_method: str | None = None,
        reference: str | None = None,
    ) -> bool:
        """Record a payment against an invoice."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any resources."""
        pass


class InMemoryInvoiceStore(InvoiceStoreBackend):
    """In-memory invoice store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    async def get(self, invoice_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get(invoice_id)

    async def save(self, data: dict[str, Any]) -> None:
        invoice_id = data.get("id")
        if not invoice_id:
            raise ValueError("id is required")
        with self._lock:
            self._data[invoice_id] = data

    async def delete(self, invoice_id: str) -> bool:
        with self._lock:
            if invoice_id in self._data:
                del self._data[invoice_id]
                return True
            return False

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(
                self._data.values(),
                key=lambda x: x.get("created_at", ""),
                reverse=True,
            )
            return items[offset : offset + limit]

    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = [i for i in self._data.values() if i.get("status") == status]
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]

    async def list_by_vendor(
        self,
        vendor_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = [i for i in self._data.values() if i.get("vendor_id") == vendor_id]
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]

    async def list_pending_approval(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                i
                for i in self._data.values()
                if i.get("status") == "pending_approval" or i.get("requires_approval", False)
            ]

    async def list_scheduled_payments(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for inv in self._data.values():
                if inv.get("status") != "approved":
                    continue
                pay_date = inv.get("scheduled_payment_date")
                if not pay_date:
                    continue
                if isinstance(pay_date, str):
                    pay_date = datetime.fromisoformat(pay_date.replace("Z", "+00:00"))
                if start_date and pay_date < start_date:
                    continue
                if end_date and pay_date > end_date:
                    continue
                results.append(inv)
            return sorted(results, key=lambda x: x.get("scheduled_payment_date", ""))

    async def find_duplicates(
        self,
        vendor_id: str,
        invoice_number: str,
        total_amount: Decimal,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for inv in self._data.values():
                if inv.get("vendor_id") == vendor_id:
                    if inv.get("invoice_number") == invoice_number:
                        results.append(inv)
                    elif inv.get("total_amount") == total_amount:
                        results.append(inv)
            return results

    async def get_by_po(self, po_number: str) -> list[dict[str, Any]]:
        with self._lock:
            return [i for i in self._data.values() if i.get("po_number") == po_number]

    async def update_status(
        self,
        invoice_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        with self._lock:
            if invoice_id not in self._data:
                return False
            self._data[invoice_id]["status"] = status
            self._data[invoice_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            if approved_by:
                self._data[invoice_id]["approved_by"] = approved_by
            if rejection_reason:
                self._data[invoice_id]["rejection_reason"] = rejection_reason
            return True

    async def schedule_payment(
        self,
        invoice_id: str,
        payment_date: datetime,
    ) -> bool:
        with self._lock:
            if invoice_id not in self._data:
                return False
            self._data[invoice_id]["scheduled_payment_date"] = payment_date.isoformat()
            self._data[invoice_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True

    async def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: datetime,
        payment_method: str | None = None,
        reference: str | None = None,
    ) -> bool:
        with self._lock:
            if invoice_id not in self._data:
                return False

            inv = self._data[invoice_id]
            payments = inv.get("payments", [])
            payments.append(
                {
                    "amount": str(amount),
                    "payment_date": payment_date.isoformat(),
                    "payment_method": payment_method,
                    "reference": reference,
                }
            )
            inv["payments"] = payments

            # Update amount paid and balance
            total_paid = sum(Decimal(p["amount"]) for p in payments)
            inv["amount_paid"] = str(total_paid)

            total = inv.get("total_amount", Decimal("0"))
            if isinstance(total, str):
                total = Decimal(total)
            inv["balance_due"] = str(total - total_paid)

            if total_paid >= total:
                inv["status"] = "paid"

            inv["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True

    async def close(self) -> None:
        pass


class SQLiteInvoiceStore(InvoiceStoreBackend):
    """SQLite-backed invoice store."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path("invoices.db")

        self._db_path = Path(resolve_db_path(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS invoices (
                        id TEXT PRIMARY KEY,
                        vendor_id TEXT,
                        vendor_name TEXT,
                        invoice_number TEXT,
                        po_number TEXT,
                        total_amount TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        approved_by TEXT,
                        invoice_date TEXT,
                        due_date TEXT,
                        scheduled_payment_date TEXT,
                        requires_approval INTEGER DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        data_json TEXT NOT NULL
                    )
                    """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_status ON invoices(status)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_invoice_vendor ON invoices(vendor_id)"
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_po ON invoices(po_number)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_invoice_number ON invoices(invoice_number)"
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoice_due ON invoices(due_date)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_invoice_payment ON invoices(scheduled_payment_date)"
                )
                conn.commit()
            finally:
                conn.close()

    async def get(self, invoice_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM invoices WHERE id = ?",
                    (invoice_id,),
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row[0], object_hook=decimal_decoder)
                return None
            finally:
                conn.close()

    async def save(self, data: dict[str, Any]) -> None:
        invoice_id = data.get("id")
        if not invoice_id:
            raise ValueError("id is required")

        now = time.time()
        data_json = json.dumps(data, cls=DecimalEncoder)

        total_amount = data.get("total_amount", "0")
        if isinstance(total_amount, Decimal):
            total_amount = str(total_amount)

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO invoices
                    (id, vendor_id, vendor_name, invoice_number, po_number,
                     total_amount, status, approved_by, invoice_date, due_date,
                     scheduled_payment_date, requires_approval, created_at,
                     updated_at, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        data.get("vendor_id"),
                        data.get("vendor_name"),
                        data.get("invoice_number"),
                        data.get("po_number"),
                        total_amount,
                        data.get("status", "pending"),
                        data.get("approved_by"),
                        data.get("invoice_date"),
                        data.get("due_date"),
                        data.get("scheduled_payment_date"),
                        1 if data.get("requires_approval") else 0,
                        now,
                        now,
                        data_json,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    async def delete(self, invoice_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM invoices
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM invoices
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def list_by_vendor(
        self,
        vendor_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM invoices
                    WHERE vendor_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (vendor_id, limit),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def list_pending_approval(self, limit: int = 500) -> list[dict[str, Any]]:
        """List invoices pending approval.

        Args:
            limit: Maximum number of invoices to return (default 500)
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM invoices
                    WHERE status = 'pending_approval' OR requires_approval = 1
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (limit,),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def list_scheduled_payments(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List scheduled payments within a date range.

        Args:
            start_date: Start of date range (optional)
            end_date: End of date range (optional)
            limit: Maximum number of invoices to return (default 500)
        """
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                where_parts = ["status = 'approved'", "scheduled_payment_date IS NOT NULL"]
                params: list[Any] = []

                if start_date:
                    where_parts.append("scheduled_payment_date >= ?")
                    params.append(start_date.isoformat())
                if end_date:
                    where_parts.append("scheduled_payment_date <= ?")
                    params.append(end_date.isoformat())

                cursor.execute(
                    f"""
                    SELECT data_json FROM invoices
                    WHERE {" AND ".join(where_parts)}
                    ORDER BY scheduled_payment_date ASC
                    LIMIT ?
                    """,  # dynamic clause from internal state
                    params + [limit],
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def find_duplicates(
        self,
        vendor_id: str,
        invoice_number: str,
        total_amount: Decimal,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM invoices
                    WHERE vendor_id = ?
                      AND (invoice_number = ? OR total_amount = ?)
                    """,
                    (vendor_id, invoice_number, str(total_amount)),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def get_by_po(self, po_number: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM invoices WHERE po_number = ?",
                    (po_number,),
                )
                return [
                    json.loads(row[0], object_hook=decimal_decoder) for row in cursor.fetchall()
                ]
            finally:
                conn.close()

    async def update_status(
        self,
        invoice_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT data_json FROM invoices WHERE id = ?",
                    (invoice_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                data = json.loads(row[0], object_hook=decimal_decoder)
                data["status"] = status
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                if approved_by:
                    data["approved_by"] = approved_by
                if rejection_reason:
                    data["rejection_reason"] = rejection_reason

                cursor.execute(
                    """
                    UPDATE invoices
                    SET status = ?, approved_by = ?, updated_at = ?, data_json = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        approved_by,
                        time.time(),
                        json.dumps(data, cls=DecimalEncoder),
                        invoice_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def schedule_payment(
        self,
        invoice_id: str,
        payment_date: datetime,
    ) -> bool:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT data_json FROM invoices WHERE id = ?",
                    (invoice_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                data = json.loads(row[0], object_hook=decimal_decoder)
                data["scheduled_payment_date"] = payment_date.isoformat()
                data["updated_at"] = datetime.now(timezone.utc).isoformat()

                cursor.execute(
                    """
                    UPDATE invoices
                    SET scheduled_payment_date = ?, updated_at = ?, data_json = ?
                    WHERE id = ?
                    """,
                    (
                        payment_date.isoformat(),
                        time.time(),
                        json.dumps(data, cls=DecimalEncoder),
                        invoice_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: datetime,
        payment_method: str | None = None,
        reference: str | None = None,
    ) -> bool:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT data_json FROM invoices WHERE id = ?",
                    (invoice_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return False

                data = json.loads(row[0], object_hook=decimal_decoder)

                payments = data.get("payments", [])
                payments.append(
                    {
                        "amount": str(amount),
                        "payment_date": payment_date.isoformat(),
                        "payment_method": payment_method,
                        "reference": reference,
                    }
                )
                data["payments"] = payments

                total_paid = sum(Decimal(p["amount"]) for p in payments)
                data["amount_paid"] = str(total_paid)

                total = data.get("total_amount", Decimal("0"))
                if isinstance(total, str):
                    total = Decimal(total)
                data["balance_due"] = str(total - total_paid)

                if total_paid >= total:
                    data["status"] = "paid"

                data["updated_at"] = datetime.now(timezone.utc).isoformat()

                cursor.execute(
                    """
                    UPDATE invoices
                    SET status = ?, updated_at = ?, data_json = ?
                    WHERE id = ?
                    """,
                    (
                        data["status"],
                        time.time(),
                        json.dumps(data, cls=DecimalEncoder),
                        invoice_id,
                    ),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def close(self) -> None:
        pass


class PostgresInvoiceStore(InvoiceStoreBackend):
    """PostgreSQL-backed invoice store for production."""

    SCHEMA_NAME = "invoices"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            vendor_id TEXT,
            vendor_name TEXT,
            invoice_number TEXT,
            po_number TEXT,
            total_amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by TEXT,
            invoice_date TIMESTAMPTZ,
            due_date TIMESTAMPTZ,
            scheduled_payment_date TIMESTAMPTZ,
            requires_approval BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            data_json JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_invoice_status ON invoices(status);
        CREATE INDEX IF NOT EXISTS idx_invoice_vendor ON invoices(vendor_id);
        CREATE INDEX IF NOT EXISTS idx_invoice_po ON invoices(po_number);
        CREATE INDEX IF NOT EXISTS idx_invoice_number ON invoices(invoice_number);
        CREATE INDEX IF NOT EXISTS idx_invoice_due ON invoices(due_date);
        CREATE INDEX IF NOT EXISTS idx_invoice_payment ON invoices(scheduled_payment_date);
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)
        self._initialized = True

    async def get(self, invoice_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data_json FROM invoices WHERE id = $1",
                invoice_id,
            )
            if row:
                data = row["data_json"]
                return json.loads(data) if isinstance(data, str) else data
            return None

    async def save(self, data: dict[str, Any]) -> None:
        invoice_id = data.get("id")
        if not invoice_id:
            raise ValueError("id is required")

        total_amount = data.get("total_amount", "0")
        if isinstance(total_amount, Decimal):
            total_amount = str(total_amount)
        elif isinstance(total_amount, str):
            total_amount = str(Decimal(total_amount))

        def parse_date(val: Any) -> datetime | None:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            return None

        data_json = json.dumps(data, cls=DecimalEncoder)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO invoices
                (id, vendor_id, vendor_name, invoice_number, po_number,
                 total_amount, status, approved_by, invoice_date, due_date,
                 scheduled_payment_date, requires_approval, data_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (id) DO UPDATE SET
                    vendor_id = EXCLUDED.vendor_id,
                    vendor_name = EXCLUDED.vendor_name,
                    invoice_number = EXCLUDED.invoice_number,
                    po_number = EXCLUDED.po_number,
                    total_amount = EXCLUDED.total_amount,
                    status = EXCLUDED.status,
                    approved_by = EXCLUDED.approved_by,
                    invoice_date = EXCLUDED.invoice_date,
                    due_date = EXCLUDED.due_date,
                    scheduled_payment_date = EXCLUDED.scheduled_payment_date,
                    requires_approval = EXCLUDED.requires_approval,
                    updated_at = NOW(),
                    data_json = EXCLUDED.data_json
                """,
                invoice_id,
                data.get("vendor_id"),
                data.get("vendor_name"),
                data.get("invoice_number"),
                data.get("po_number"),
                total_amount,
                data.get("status", "pending"),
                data.get("approved_by"),
                parse_date(data.get("invoice_date")),
                parse_date(data.get("due_date")),
                parse_date(data.get("scheduled_payment_date")),
                data.get("requires_approval", False),
                data_json,
            )

    async def delete(self, invoice_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM invoices WHERE id = $1",
                invoice_id,
            )
            return result != "DELETE 0"

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data_json FROM invoices
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data_json FROM invoices
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def list_by_vendor(
        self,
        vendor_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data_json FROM invoices
                WHERE vendor_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                vendor_id,
                limit,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def list_pending_approval(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT data_json FROM invoices
                WHERE status = 'pending_approval' OR requires_approval = TRUE
                ORDER BY created_at ASC
                """)
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def list_scheduled_payments(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            where_parts = [
                "status = 'approved'",
                "scheduled_payment_date IS NOT NULL",
            ]
            params: list[Any] = []
            param_idx = 1

            if start_date:
                where_parts.append(f"scheduled_payment_date >= ${param_idx}")
                params.append(start_date)
                param_idx += 1
            if end_date:
                where_parts.append(f"scheduled_payment_date <= ${param_idx}")
                params.append(end_date)
                param_idx += 1

            rows = await conn.fetch(
                f"""
                SELECT data_json FROM invoices
                WHERE {" AND ".join(where_parts)}
                ORDER BY scheduled_payment_date ASC
                """,  # dynamic clause from internal state
                *params,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def find_duplicates(
        self,
        vendor_id: str,
        invoice_number: str,
        total_amount: Decimal,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data_json FROM invoices
                WHERE vendor_id = $1
                  AND (invoice_number = $2 OR total_amount = $3)
                """,
                vendor_id,
                invoice_number,
                str(total_amount),
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def get_by_po(self, po_number: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT data_json FROM invoices WHERE po_number = $1",
                po_number,
            )
            results = []
            for row in rows:
                data = row["data_json"]
                results.append(json.loads(data) if isinstance(data, str) else data)
            return results

    async def update_status(
        self,
        invoice_id: str,
        status: str,
        approved_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data_json FROM invoices WHERE id = $1",
                invoice_id,
            )
            if not row:
                return False

            raw_data = row["data_json"]
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            data["status"] = status
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            if approved_by:
                data["approved_by"] = approved_by
            if rejection_reason:
                data["rejection_reason"] = rejection_reason

            result = await conn.execute(
                """
                UPDATE invoices
                SET status = $1, approved_by = $2, updated_at = NOW(), data_json = $3
                WHERE id = $4
                """,
                status,
                approved_by,
                json.dumps(data, cls=DecimalEncoder),
                invoice_id,
            )
            return result != "UPDATE 0"

    async def schedule_payment(
        self,
        invoice_id: str,
        payment_date: datetime,
    ) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data_json FROM invoices WHERE id = $1",
                invoice_id,
            )
            if not row:
                return False

            raw_data = row["data_json"]
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            data["scheduled_payment_date"] = payment_date.isoformat()
            data["updated_at"] = datetime.now(timezone.utc).isoformat()

            result = await conn.execute(
                """
                UPDATE invoices
                SET scheduled_payment_date = $1, updated_at = NOW(), data_json = $2
                WHERE id = $3
                """,
                payment_date,
                json.dumps(data, cls=DecimalEncoder),
                invoice_id,
            )
            return result != "UPDATE 0"

    async def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        payment_date: datetime,
        payment_method: str | None = None,
        reference: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as conn:
            # Use a transaction with FOR UPDATE to prevent race conditions
            # when multiple payments are recorded concurrently
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT data_json FROM invoices WHERE id = $1 FOR UPDATE",
                    invoice_id,
                )
                if not row:
                    return False

                raw_data = row["data_json"]
                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

                payments = data.get("payments", [])
                payments.append(
                    {
                        "amount": str(amount),
                        "payment_date": payment_date.isoformat(),
                        "payment_method": payment_method,
                        "reference": reference,
                    }
                )
                data["payments"] = payments

                total_paid = sum(Decimal(p["amount"]) for p in payments)
                data["amount_paid"] = str(total_paid)

                total = data.get("total_amount", Decimal("0"))
                if isinstance(total, str):
                    total = Decimal(total)
                data["balance_due"] = str(total - total_paid)

                if total_paid >= total:
                    data["status"] = "paid"

                data["updated_at"] = datetime.now(timezone.utc).isoformat()

                result = await conn.execute(
                    """
                    UPDATE invoices
                    SET status = $1, updated_at = NOW(), data_json = $2
                    WHERE id = $3
                    """,
                    data["status"],
                    json.dumps(data, cls=DecimalEncoder),
                    invoice_id,
                )
                return result != "UPDATE 0"

    async def close(self) -> None:
        pass


def get_invoice_store() -> InvoiceStoreBackend:
    """
    Get the global invoice store instance.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_INVOICE_STORE_BACKEND: "memory", "sqlite", "postgres", or "supabase"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured InvoiceStoreBackend instance
    """
    global _invoice_store

    with _store_lock:
        if _invoice_store is not None:
            return _invoice_store

        from aragora.storage.connection_factory import create_persistent_store

        _invoice_store = create_persistent_store(
            store_name="invoice",
            sqlite_class=SQLiteInvoiceStore,
            postgres_class=PostgresInvoiceStore,
            db_filename="invoices.db",
            memory_class=InMemoryInvoiceStore,
        )

        return _invoice_store


def set_invoice_store(store: InvoiceStoreBackend) -> None:
    """Set a custom invoice store instance."""
    global _invoice_store
    with _store_lock:
        _invoice_store = store


def reset_invoice_store() -> None:
    """Reset the global invoice store (for testing)."""
    global _invoice_store
    with _store_lock:
        _invoice_store = None


__all__ = [
    "InvoiceStoreBackend",
    "InMemoryInvoiceStore",
    "SQLiteInvoiceStore",
    "PostgresInvoiceStore",
    "get_invoice_store",
    "set_invoice_store",
    "reset_invoice_store",
]
