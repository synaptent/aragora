"""
Plugin Revenue Sharing System.

Tracks plugin installs, usage, and revenue distribution to plugin developers.
Default revenue split: 70% to developer, 30% to platform.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Generator
from uuid import uuid4

logger = logging.getLogger(__name__)


class RevenueEventType(Enum):
    """Types of revenue events."""

    INSTALL = "install"  # One-time purchase
    SUBSCRIPTION = "subscription"  # Subscription payment
    USAGE = "usage"  # Per-use charge
    REFUND = "refund"  # Refund


@dataclass
class PluginRevenueEvent:
    """A single revenue event for a plugin."""

    id: str = field(default_factory=lambda: str(uuid4()))
    plugin_name: str = ""
    plugin_version: str = ""
    developer_id: str = ""  # Plugin developer user ID
    org_id: str = ""  # Purchasing organization
    user_id: str = ""  # User who triggered the event

    event_type: RevenueEventType = RevenueEventType.INSTALL
    gross_amount_cents: int = 0  # Total charge in cents
    platform_fee_cents: int = 0  # Platform commission
    developer_amount_cents: int = 0  # Amount to developer
    currency: str = "USD"

    # Stripe integration
    stripe_payment_id: str = ""
    stripe_transfer_id: str = ""  # Transfer to developer's connected account

    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def calculate_split(self, developer_share_percent: int = 70) -> None:
        """Calculate revenue split between platform and developer."""
        self.developer_amount_cents = int(self.gross_amount_cents * developer_share_percent / 100)
        self.platform_fee_cents = self.gross_amount_cents - self.developer_amount_cents

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plugin_name": self.plugin_name,
            "plugin_version": self.plugin_version,
            "developer_id": self.developer_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "event_type": self.event_type.value,
            "gross_amount_cents": self.gross_amount_cents,
            "platform_fee_cents": self.platform_fee_cents,
            "developer_amount_cents": self.developer_amount_cents,
            "currency": self.currency,
            "stripe_payment_id": self.stripe_payment_id,
            "stripe_transfer_id": self.stripe_transfer_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DeveloperPayout:
    """Payout record for a plugin developer."""

    id: str = field(default_factory=lambda: str(uuid4()))
    developer_id: str = ""
    amount_cents: int = 0
    currency: str = "USD"
    status: str = "pending"  # pending, processing, completed, failed
    stripe_transfer_id: str = ""
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "developer_id": self.developer_id,
            "amount_cents": self.amount_cents,
            "currency": self.currency,
            "status": self.status,
            "stripe_transfer_id": self.stripe_transfer_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PluginInstall:
    """Record of a plugin installation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    plugin_name: str = ""
    plugin_version: str = ""
    org_id: str = ""
    user_id: str = ""
    installed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trial_ends_at: datetime | None = None
    subscription_active: bool = False
    uninstalled_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plugin_name": self.plugin_name,
            "plugin_version": self.plugin_version,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "installed_at": self.installed_at.isoformat(),
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "subscription_active": self.subscription_active,
            "uninstalled_at": self.uninstalled_at.isoformat() if self.uninstalled_at else None,
        }


class PluginRevenueTracker:
    """
    Tracks plugin revenue and manages developer payouts.

    Features:
    - Track plugin installs and purchases
    - Calculate revenue splits (default 70/30)
    - Generate developer payout reports
    - Integration with Stripe Connect for payouts
    """

    # Default revenue split
    DEFAULT_DEVELOPER_SHARE = 70  # 70% to developer

    # Minimum payout threshold (in cents)
    MIN_PAYOUT_THRESHOLD = 1000  # $10

    def __init__(self, db_path: Path | None = None):
        """
        Initialize plugin revenue tracker.

        Args:
            db_path: Path to SQLite database (default: .nomic/plugin_revenue.db)
        """
        if db_path is None:
            from aragora.persistence.db_config import get_nomic_dir

            db_path = get_nomic_dir() / "plugin_revenue.db"
        self.db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Create database schema if not exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript("""
                -- Plugin installs
                CREATE TABLE IF NOT EXISTS plugin_installs (
                    id TEXT PRIMARY KEY,
                    plugin_name TEXT NOT NULL,
                    plugin_version TEXT,
                    org_id TEXT NOT NULL,
                    user_id TEXT,
                    installed_at TEXT NOT NULL,
                    trial_ends_at TEXT,
                    subscription_active INTEGER DEFAULT 0,
                    uninstalled_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_installs_plugin
                    ON plugin_installs(plugin_name);
                CREATE INDEX IF NOT EXISTS idx_installs_org
                    ON plugin_installs(org_id);

                -- Revenue events
                CREATE TABLE IF NOT EXISTS revenue_events (
                    id TEXT PRIMARY KEY,
                    plugin_name TEXT NOT NULL,
                    plugin_version TEXT,
                    developer_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    user_id TEXT,
                    event_type TEXT NOT NULL,
                    gross_amount_cents INTEGER DEFAULT 0,
                    platform_fee_cents INTEGER DEFAULT 0,
                    developer_amount_cents INTEGER DEFAULT 0,
                    currency TEXT DEFAULT 'USD',
                    stripe_payment_id TEXT,
                    stripe_transfer_id TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_revenue_developer
                    ON revenue_events(developer_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_revenue_plugin
                    ON revenue_events(plugin_name, created_at);

                -- Developer payouts
                CREATE TABLE IF NOT EXISTS developer_payouts (
                    id TEXT PRIMARY KEY,
                    developer_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    status TEXT DEFAULT 'pending',
                    stripe_transfer_id TEXT,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_payouts_developer
                    ON developer_payouts(developer_id, status);
            """)
            conn.commit()

    def record_install(
        self,
        plugin_name: str,
        plugin_version: str,
        org_id: str,
        user_id: str,
        trial_days: int = 0,
    ) -> PluginInstall:
        """
        Record a plugin installation.

        Args:
            plugin_name: Name of the plugin
            plugin_version: Version installed
            org_id: Organization installing the plugin
            user_id: User who triggered the install
            trial_days: Number of trial days (0 for no trial)

        Returns:
            PluginInstall record
        """
        install = PluginInstall(
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            org_id=org_id,
            user_id=user_id,
        )

        if trial_days > 0:
            install.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=trial_days)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO plugin_installs
                (id, plugin_name, plugin_version, org_id, user_id,
                 installed_at, trial_ends_at, subscription_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    install.id,
                    install.plugin_name,
                    install.plugin_version,
                    install.org_id,
                    install.user_id,
                    install.installed_at.isoformat(),
                    install.trial_ends_at.isoformat() if install.trial_ends_at else None,
                    1 if install.subscription_active else 0,
                ),
            )
            conn.commit()

        logger.info(
            "Plugin install recorded: %s v%s by org %s", plugin_name, plugin_version, org_id
        )
        return install

    def record_revenue(
        self,
        plugin_name: str,
        plugin_version: str,
        developer_id: str,
        org_id: str,
        user_id: str,
        event_type: RevenueEventType,
        gross_amount_cents: int,
        developer_share_percent: int = DEFAULT_DEVELOPER_SHARE,
        stripe_payment_id: str = "",
        metadata: dict | None = None,
    ) -> PluginRevenueEvent:
        """
        Record a revenue event for a plugin.

        Args:
            plugin_name: Plugin generating revenue
            plugin_version: Plugin version
            developer_id: Developer user ID
            org_id: Paying organization
            user_id: User who triggered the payment
            event_type: Type of revenue event
            gross_amount_cents: Total amount in cents
            developer_share_percent: Developer's percentage (default 70%)
            stripe_payment_id: Stripe payment ID
            metadata: Additional metadata

        Returns:
            PluginRevenueEvent record
        """
        import json

        event = PluginRevenueEvent(
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            developer_id=developer_id,
            org_id=org_id,
            user_id=user_id,
            event_type=event_type,
            gross_amount_cents=gross_amount_cents,
            stripe_payment_id=stripe_payment_id,
            metadata=metadata or {},
        )

        # Calculate revenue split
        event.calculate_split(developer_share_percent)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO revenue_events
                (id, plugin_name, plugin_version, developer_id, org_id, user_id,
                 event_type, gross_amount_cents, platform_fee_cents,
                 developer_amount_cents, currency, stripe_payment_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.plugin_name,
                    event.plugin_version,
                    event.developer_id,
                    event.org_id,
                    event.user_id,
                    event.event_type.value,
                    event.gross_amount_cents,
                    event.platform_fee_cents,
                    event.developer_amount_cents,
                    event.currency,
                    event.stripe_payment_id,
                    json.dumps(event.metadata),
                    event.created_at.isoformat(),
                ),
            )
            conn.commit()

        logger.info(
            "Revenue recorded: %s $%.2f (developer: $%.2f)",
            plugin_name,
            event.gross_amount_cents / 100,
            event.developer_amount_cents / 100,
        )
        return event

    def get_developer_balance(self, developer_id: str) -> dict[str, Any]:
        """
        Get current balance for a developer.

        Args:
            developer_id: Developer user ID

        Returns:
            Balance information
        """
        with self._connection() as conn:
            # Get total earnings (excluding refunds) and total refunds separately
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN event_type != 'refund' THEN developer_amount_cents ELSE 0 END), 0) as total_earnings,
                    COALESCE(SUM(CASE WHEN event_type = 'refund' THEN developer_amount_cents ELSE 0 END), 0) as total_refunds
                FROM revenue_events
                WHERE developer_id = ?
                """,
                (developer_id,),
            ).fetchone()

            total_earnings = row["total_earnings"] if row else 0
            total_refunds = row["total_refunds"] if row else 0

            # Get total payouts
            payout_row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) as total_payouts
                FROM developer_payouts
                WHERE developer_id = ? AND status = 'completed'
                """,
                (developer_id,),
            ).fetchone()

            total_payouts = payout_row["total_payouts"] if payout_row else 0

            # Calculate balance
            balance = total_earnings - total_refunds - total_payouts

            return {
                "developer_id": developer_id,
                "total_earnings_cents": total_earnings,
                "total_refunds_cents": abs(total_refunds),
                "total_payouts_cents": total_payouts,
                "available_balance_cents": balance,
                "payout_eligible": balance >= self.MIN_PAYOUT_THRESHOLD,
                "min_payout_cents": self.MIN_PAYOUT_THRESHOLD,
            }

    def get_plugin_stats(self, plugin_name: str) -> dict[str, Any]:
        """
        Get revenue statistics for a plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Plugin statistics
        """
        with self._connection() as conn:
            # Get install count
            install_row = conn.execute(
                """
                SELECT COUNT(*) as total_installs,
                       COUNT(CASE WHEN subscription_active = 1 THEN 1 END) as active_subscriptions,
                       COUNT(CASE WHEN uninstalled_at IS NULL THEN 1 END) as current_installs
                FROM plugin_installs
                WHERE plugin_name = ?
                """,
                (plugin_name,),
            ).fetchone()

            # Get revenue stats
            revenue_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(gross_amount_cents), 0) as total_revenue,
                    COUNT(*) as transaction_count
                FROM revenue_events
                WHERE plugin_name = ? AND event_type != 'refund'
                """,
                (plugin_name,),
            ).fetchone()

            return {
                "plugin_name": plugin_name,
                "total_installs": install_row["total_installs"] if install_row else 0,
                "active_subscriptions": install_row["active_subscriptions"] if install_row else 0,
                "current_installs": install_row["current_installs"] if install_row else 0,
                "total_revenue_cents": revenue_row["total_revenue"] if revenue_row else 0,
                "transaction_count": revenue_row["transaction_count"] if revenue_row else 0,
            }

    def create_payout(
        self,
        developer_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> DeveloperPayout | None:
        """
        Create a payout for a developer.

        Args:
            developer_id: Developer user ID
            period_start: Start of payout period
            period_end: End of payout period

        Returns:
            DeveloperPayout if eligible, None otherwise
        """
        balance = self.get_developer_balance(developer_id)

        if not balance["payout_eligible"]:
            logger.info(
                "Developer %s not eligible for payout (balance: $%.2f)",
                developer_id,
                balance["available_balance_cents"] / 100,
            )
            return None

        payout = DeveloperPayout(
            developer_id=developer_id,
            amount_cents=balance["available_balance_cents"],
            period_start=period_start,
            period_end=period_end,
        )

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO developer_payouts
                (id, developer_id, amount_cents, currency, status,
                 period_start, period_end, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payout.id,
                    payout.developer_id,
                    payout.amount_cents,
                    payout.currency,
                    payout.status,
                    payout.period_start.isoformat(),
                    payout.period_end.isoformat(),
                    payout.created_at.isoformat(),
                ),
            )
            conn.commit()

        logger.info(
            "Payout created for developer %s: $%.2f", developer_id, payout.amount_cents / 100
        )
        return payout

    def complete_payout(
        self,
        payout_id: str,
        stripe_transfer_id: str,
    ) -> bool:
        """
        Mark a payout as completed.

        Args:
            payout_id: Payout ID
            stripe_transfer_id: Stripe transfer ID

        Returns:
            True if successful
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE developer_payouts
                SET status = 'completed',
                    stripe_transfer_id = ?,
                    completed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (stripe_transfer_id, datetime.now(timezone.utc).isoformat(), payout_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_developer_revenue_history(
        self,
        developer_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get revenue history for a developer.

        Args:
            developer_id: Developer user ID
            limit: Maximum records to return
            offset: Pagination offset

        Returns:
            List of revenue events
        """

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM revenue_events
                WHERE developer_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (developer_id, limit, offset),
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "plugin_name": row["plugin_name"],
                    "plugin_version": row["plugin_version"],
                    "org_id": row["org_id"],
                    "event_type": row["event_type"],
                    "gross_amount_cents": row["gross_amount_cents"],
                    "developer_amount_cents": row["developer_amount_cents"],
                    "platform_fee_cents": row["platform_fee_cents"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]


# Default tracker instance
_default_tracker: PluginRevenueTracker | None = None


def get_plugin_revenue_tracker() -> PluginRevenueTracker:
    """Get the default plugin revenue tracker instance."""
    global _default_tracker
    if _default_tracker is None:
        _default_tracker = PluginRevenueTracker()
    return _default_tracker


__all__ = [
    "PluginRevenueTracker",
    "PluginRevenueEvent",
    "PluginInstall",
    "DeveloperPayout",
    "RevenueEventType",
    "get_plugin_revenue_tracker",
]
