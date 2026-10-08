"""
Payment Failure Recovery System.

Tracks failed payments and handles automatic recovery actions:
1. Records payment failures with timestamps
2. Sends escalating notifications at each retry attempt
3. Auto-downgrades to FREE tier after grace period
4. Provides background job for grace period enforcement

Stripe typically retries payments on Day 1, Day 3, Day 5, Day 7.
After the final retry, we wait 3 more days before downgrading.

Grace Period Schedule:
- Day 0: First payment failure (Stripe retry 1)
- Day 3: Stripe retry 2 - Warning notification
- Day 5: Stripe retry 3 - Urgent notification
- Day 7: Stripe retry 4 (final) - Final warning
- Day 10: Grace period ends - Auto-downgrade to FREE

Environment Variables:
- ARAGORA_PAYMENT_GRACE_DAYS: Days before downgrade (default: 10)
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, cast

from aragora.billing.models import SubscriptionTier
from aragora.persistence.db_config import get_default_data_dir
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)

# Grace period configuration (days after first failure before downgrade)
PAYMENT_GRACE_DAYS = int(os.getenv("ARAGORA_PAYMENT_GRACE_DAYS", "10"))


@dataclass
class PaymentFailure:
    """Record of a payment failure."""

    id: str
    org_id: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    first_failure_at: datetime
    last_failure_at: datetime
    attempt_count: int
    invoice_id: str | None = None
    invoice_url: str | None = None
    status: str = "failing"  # failing, recovered, downgraded
    grace_ends_at: datetime | None = field(default=None)

    def __post_init__(self):
        if self.grace_ends_at is None:
            self.grace_ends_at = self.first_failure_at + timedelta(days=PAYMENT_GRACE_DAYS)

    @property
    def days_failing(self) -> int:
        """Days since first failure."""
        return (datetime.now(timezone.utc) - self.first_failure_at).days

    @property
    def days_until_downgrade(self) -> int:
        """Days until automatic downgrade."""
        return max(
            0,
            (cast(datetime, self.grace_ends_at) - datetime.now(timezone.utc)).days,
        )

    @property
    def should_downgrade(self) -> bool:
        """Check if grace period has ended."""
        return datetime.now(timezone.utc) >= cast(datetime, self.grace_ends_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "first_failure_at": self.first_failure_at.isoformat(),
            "last_failure_at": self.last_failure_at.isoformat(),
            "attempt_count": self.attempt_count,
            "invoice_id": self.invoice_id,
            "invoice_url": self.invoice_url,
            "status": self.status,
            "grace_ends_at": cast(datetime, self.grace_ends_at).isoformat(),
            "days_failing": self.days_failing,
            "days_until_downgrade": self.days_until_downgrade,
            "should_downgrade": self.should_downgrade,
        }


class PaymentRecoveryStore(SQLiteStore):
    """
    SQLite-backed store for payment failure tracking.

    Persists payment failure records for grace period enforcement.
    """

    SCHEMA_NAME = "payment_recovery"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS payment_failures (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            stripe_customer_id TEXT NOT NULL,
            stripe_subscription_id TEXT,
            first_failure_at TEXT NOT NULL,
            last_failure_at TEXT NOT NULL,
            attempt_count INTEGER DEFAULT 1,
            invoice_id TEXT,
            invoice_url TEXT,
            status TEXT DEFAULT 'failing',
            grace_ends_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_payment_failures_org ON payment_failures(org_id);
        CREATE INDEX IF NOT EXISTS idx_payment_failures_status ON payment_failures(status);
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            data_path = get_default_data_dir()
            data_path.mkdir(parents=True, exist_ok=True)
            db_path = str(data_path / "payment_recovery.db")

        super().__init__(db_path=db_path)

    def record_failure(
        self,
        org_id: str,
        stripe_customer_id: str,
        stripe_subscription_id: str | None = None,
        invoice_id: str | None = None,
        invoice_url: str | None = None,
    ) -> PaymentFailure:
        """
        Record a payment failure or update existing failure record.

        Args:
            org_id: Organization ID
            stripe_customer_id: Stripe customer ID
            stripe_subscription_id: Stripe subscription ID
            invoice_id: Failed invoice ID
            invoice_url: URL for customer to pay invoice

        Returns:
            PaymentFailure record
        """
        import uuid

        now = datetime.now(timezone.utc)

        with self.connection() as conn:
            # Check for existing active failure
            cursor = conn.execute(
                """
                SELECT id, first_failure_at, attempt_count, grace_ends_at
                FROM payment_failures
                WHERE org_id = ? AND status = 'failing'
                ORDER BY first_failure_at DESC LIMIT 1
                """,
                (org_id,),
            )
            row = cursor.fetchone()

            if row:
                # Update existing failure
                failure_id = row[0]
                first_failure = datetime.fromisoformat(row[1])
                attempt_count = row[2] + 1
                grace_ends = datetime.fromisoformat(row[3])

                conn.execute(
                    """
                    UPDATE payment_failures
                    SET last_failure_at = ?,
                        attempt_count = ?,
                        invoice_id = COALESCE(?, invoice_id),
                        invoice_url = COALESCE(?, invoice_url),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        now.isoformat(),
                        attempt_count,
                        invoice_id,
                        invoice_url,
                        now.isoformat(),
                        failure_id,
                    ),
                )

                return PaymentFailure(
                    id=failure_id,
                    org_id=org_id,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=stripe_subscription_id,
                    first_failure_at=first_failure,
                    last_failure_at=now,
                    attempt_count=attempt_count,
                    invoice_id=invoice_id,
                    invoice_url=invoice_url,
                    status="failing",
                    grace_ends_at=grace_ends,
                )
            else:
                # Create new failure record
                failure_id = f"pf_{uuid.uuid4().hex[:12]}"
                grace_ends = now + timedelta(days=PAYMENT_GRACE_DAYS)

                conn.execute(
                    """
                    INSERT INTO payment_failures (
                        id, org_id, stripe_customer_id, stripe_subscription_id,
                        first_failure_at, last_failure_at, attempt_count,
                        invoice_id, invoice_url, status, grace_ends_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'failing', ?)
                    """,
                    (
                        failure_id,
                        org_id,
                        stripe_customer_id,
                        stripe_subscription_id,
                        now.isoformat(),
                        now.isoformat(),
                        invoice_id,
                        invoice_url,
                        grace_ends.isoformat(),
                    ),
                )

                return PaymentFailure(
                    id=failure_id,
                    org_id=org_id,
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=stripe_subscription_id,
                    first_failure_at=now,
                    last_failure_at=now,
                    attempt_count=1,
                    invoice_id=invoice_id,
                    invoice_url=invoice_url,
                    status="failing",
                    grace_ends_at=grace_ends,
                )
        # Should not reach here
        raise RuntimeError("Failed to record payment failure")

    def mark_recovered(self, org_id: str) -> bool:
        """
        Mark payment as recovered (successful payment).

        Called when invoice.payment_succeeded is received.

        Args:
            org_id: Organization ID

        Returns:
            True if there was a failing record that was updated
        """
        with self.connection() as conn:
            result = conn.execute(
                """
                UPDATE payment_failures
                SET status = 'recovered', updated_at = ?
                WHERE org_id = ? AND status = 'failing'
                """,
                (datetime.now(timezone.utc).isoformat(), org_id),
            )
            return result.rowcount > 0

    def mark_downgraded(self, org_id: str) -> bool:
        """
        Mark payment failure as resulting in downgrade.

        Called when organization is downgraded due to non-payment.

        Args:
            org_id: Organization ID

        Returns:
            True if there was a failing record that was updated
        """
        with self.connection() as conn:
            result = conn.execute(
                """
                UPDATE payment_failures
                SET status = 'downgraded', updated_at = ?
                WHERE org_id = ? AND status = 'failing'
                """,
                (datetime.now(timezone.utc).isoformat(), org_id),
            )
            return result.rowcount > 0

    def get_active_failure(self, org_id: str) -> PaymentFailure | None:
        """
        Get active payment failure for an organization.

        Args:
            org_id: Organization ID

        Returns:
            PaymentFailure if active failure exists, None otherwise
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, org_id, stripe_customer_id, stripe_subscription_id,
                       first_failure_at, last_failure_at, attempt_count,
                       invoice_id, invoice_url, status, grace_ends_at
                FROM payment_failures
                WHERE org_id = ? AND status = 'failing'
                ORDER BY first_failure_at DESC LIMIT 1
                """,
                (org_id,),
            )
            row = cursor.fetchone()
            if row:
                return PaymentFailure(
                    id=row[0],
                    org_id=row[1],
                    stripe_customer_id=row[2],
                    stripe_subscription_id=row[3],
                    first_failure_at=datetime.fromisoformat(row[4]),
                    last_failure_at=datetime.fromisoformat(row[5]),
                    attempt_count=row[6],
                    invoice_id=row[7],
                    invoice_url=row[8],
                    status=row[9],
                    grace_ends_at=datetime.fromisoformat(row[10]),
                )
            return None

    def get_expired_failures(self) -> list[PaymentFailure]:
        """
        Get all failures where grace period has expired.

        These should be auto-downgraded to FREE tier.

        Returns:
            List of PaymentFailure records ready for downgrade
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, org_id, stripe_customer_id, stripe_subscription_id,
                       first_failure_at, last_failure_at, attempt_count,
                       invoice_id, invoice_url, status, grace_ends_at
                FROM payment_failures
                WHERE status = 'failing' AND grace_ends_at <= ?
                """,
                (now,),
            )
            results = []
            for row in cursor.fetchall():
                results.append(
                    PaymentFailure(
                        id=row[0],
                        org_id=row[1],
                        stripe_customer_id=row[2],
                        stripe_subscription_id=row[3],
                        first_failure_at=datetime.fromisoformat(row[4]),
                        last_failure_at=datetime.fromisoformat(row[5]),
                        attempt_count=row[6],
                        invoice_id=row[7],
                        invoice_url=row[8],
                        status=row[9],
                        grace_ends_at=datetime.fromisoformat(row[10]),
                    )
                )
            return results

    def get_failures_needing_notification(self, days_threshold: int) -> list[PaymentFailure]:
        """
        Get failures that may need escalated notification.

        Args:
            days_threshold: Notify if failing for >= this many days

        Returns:
            List of PaymentFailure records needing notification
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_threshold)).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, org_id, stripe_customer_id, stripe_subscription_id,
                       first_failure_at, last_failure_at, attempt_count,
                       invoice_id, invoice_url, status, grace_ends_at
                FROM payment_failures
                WHERE status = 'failing' AND first_failure_at <= ?
                """,
                (cutoff,),
            )
            results = []
            for row in cursor.fetchall():
                results.append(
                    PaymentFailure(
                        id=row[0],
                        org_id=row[1],
                        stripe_customer_id=row[2],
                        stripe_subscription_id=row[3],
                        first_failure_at=datetime.fromisoformat(row[4]),
                        last_failure_at=datetime.fromisoformat(row[5]),
                        attempt_count=row[6],
                        invoice_id=row[7],
                        invoice_url=row[8],
                        status=row[9],
                        grace_ends_at=datetime.fromisoformat(row[10]),
                    )
                )
            return results


# Global store instance
_recovery_store: PaymentRecoveryStore | None = None
_store_lock = threading.Lock()


def get_recovery_store() -> PaymentRecoveryStore:
    """Get the global payment recovery store instance."""
    global _recovery_store
    if _recovery_store is None:
        with _store_lock:
            if _recovery_store is None:
                _recovery_store = PaymentRecoveryStore()
    return _recovery_store


def process_expired_grace_periods(user_store) -> dict[str, Any]:
    """
    Process all organizations with expired grace periods.

    Downgrades them to FREE tier and sends notification.

    Args:
        user_store: UserStore instance for organization updates

    Returns:
        Summary of actions taken
    """
    from aragora.billing.notifications import get_billing_notifier

    store = get_recovery_store()
    notifier = get_billing_notifier()

    expired = store.get_expired_failures()
    results = {
        "processed": 0,
        "downgraded": 0,
        "notification_sent": 0,
        "errors": 0,
    }

    for failure in expired:
        results["processed"] += 1
        try:
            org = user_store.get_organization_by_id(failure.org_id)
            if not org:
                logger.warning("Org %s not found for grace period expiry", failure.org_id)
                continue

            # Skip if already on FREE tier
            if org.tier == SubscriptionTier.FREE:
                store.mark_downgraded(failure.org_id)
                continue

            # Downgrade to FREE
            old_tier = org.tier.value
            user_store.update_organization(
                failure.org_id,
                tier=SubscriptionTier.FREE,
            )
            store.mark_downgraded(failure.org_id)
            results["downgraded"] += 1

            logger.warning(
                "Auto-downgraded org %s from %s to FREE due to payment failure (grace period expired after %s days)",
                failure.org_id,
                old_tier,
                failure.days_failing,
            )

            # Send downgrade notification
            owner = user_store.get_organization_owner(failure.org_id)
            if owner and owner.email:
                notifier.notify_downgraded(
                    org_id=failure.org_id,
                    org_name=org.name,
                    email=owner.email,
                    previous_tier=old_tier,
                    invoice_url=failure.invoice_url,
                )
                results["notification_sent"] += 1

        except (RuntimeError, OSError, ConnectionError, ValueError, TypeError, KeyError) as e:
            logger.error("Error processing grace period expiry for %s: %s", failure.org_id, e)
            results["errors"] += 1

    return results


__all__ = [
    "PaymentFailure",
    "PaymentRecoveryStore",
    "get_recovery_store",
    "process_expired_grace_periods",
    "PAYMENT_GRACE_DAYS",
]
