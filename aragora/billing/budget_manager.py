"""
Budget Manager - Comprehensive budget operations and enforcement.

Provides:
- Budget CRUD operations with persistence
- Real-time budget enforcement with hard stops
- Budget policy management
- Alert threshold configuration
- Budget override mechanism for authorized users
"""

from __future__ import annotations

import contextvars
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)


class BudgetPeriod(Enum):
    """Budget period types."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    UNLIMITED = "unlimited"


class BudgetStatus(Enum):
    """Budget status states."""

    ACTIVE = "active"
    WARNING = "warning"  # 75%+ usage
    CRITICAL = "critical"  # 90%+ usage
    EXCEEDED = "exceeded"  # 100%+ usage
    SUSPENDED = "suspended"  # Auto-suspended due to exceed
    PAUSED = "paused"  # Manually paused
    CLOSED = "closed"  # Budget period ended


class BudgetAction(Enum):
    """Actions when budget thresholds are reached."""

    NOTIFY = "notify"  # Send alert only
    WARN = "warn"  # Warn users + slow down operations
    SOFT_LIMIT = "soft_limit"  # Warn + require confirmation
    HARD_LIMIT = "hard_limit"  # Block operations
    SUSPEND = "suspend"  # Suspend all operations
    ALLOW_WITH_CHARGES = "allow_with_charges"  # Allow but track as overage


@dataclass
class SpendResult:
    """Result of a spend check or operation."""

    allowed: bool
    message: str = ""
    is_overage: bool = False
    overage_amount_usd: float = 0.0
    overage_rate_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "message": self.message,
            "is_overage": self.is_overage,
            "overage_amount_usd": self.overage_amount_usd,
            "overage_rate_multiplier": self.overage_rate_multiplier,
        }


@dataclass
class BudgetThreshold:
    """Budget alert threshold configuration."""

    percentage: float  # 0.0 - 1.0
    action: BudgetAction
    notify_channels: list[str] = field(default_factory=lambda: ["email"])
    cooldown_minutes: int = 60  # Minimum time between alerts


# Default thresholds for new budgets
DEFAULT_THRESHOLDS = [
    BudgetThreshold(0.50, BudgetAction.NOTIFY),
    BudgetThreshold(0.75, BudgetAction.WARN),
    BudgetThreshold(0.90, BudgetAction.SOFT_LIMIT),
    BudgetThreshold(1.00, BudgetAction.HARD_LIMIT),
]

# SMB-strict thresholds: Hard block at 90% to prevent bill shock
# Recommended for small/medium businesses that want stricter cost control
SMB_DEFAULT_THRESHOLDS = [
    BudgetThreshold(0.50, BudgetAction.NOTIFY),
    BudgetThreshold(0.75, BudgetAction.WARN),
    BudgetThreshold(0.90, BudgetAction.HARD_LIMIT),  # Block before 100% - no bill shock
]


@dataclass
class Budget:
    """Budget configuration and state."""

    budget_id: str
    org_id: str
    name: str
    description: str = ""

    # Limits
    amount_usd: float = 0.0  # Total budget amount
    period: BudgetPeriod = BudgetPeriod.MONTHLY

    # Current usage
    spent_usd: float = 0.0
    period_start: float = 0.0  # Unix timestamp
    period_end: float = 0.0

    # Status
    status: BudgetStatus = BudgetStatus.ACTIVE
    auto_suspend: bool = True  # Auto-suspend on exceed

    # Thresholds (default: warn at 75%, critical at 90%, hard limit at 100%)
    thresholds: list[BudgetThreshold] = field(default_factory=lambda: list(DEFAULT_THRESHOLDS))

    # Overrides
    override_user_ids: list[str] = field(default_factory=list)  # Users who can bypass
    override_until: float | None = None  # Temporary override expiry

    # Overage settings
    allow_overage: bool = False  # Allow spending beyond budget with charges
    overage_rate_multiplier: float = 1.5  # Rate multiplier for overage (1.5x = 50% surcharge)
    overage_spent_usd: float = 0.0  # Amount spent in overage
    max_overage_usd: float | None = None  # Optional cap on overage amount

    # Metadata
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    created_by: str | None = None

    @property
    def usage_percentage(self) -> float:
        """Get current usage as percentage (0.0 - 1.0+)."""
        if self.amount_usd <= 0:
            return 0.0
        return self.spent_usd / self.amount_usd

    @property
    def remaining_usd(self) -> float:
        """Get remaining budget in USD."""
        return max(0.0, self.amount_usd - self.spent_usd)

    @property
    def is_exceeded(self) -> bool:
        """Check if budget is exceeded."""
        return self.spent_usd >= self.amount_usd and self.amount_usd > 0

    @property
    def current_action(self) -> BudgetAction:
        """Get the action for current usage level."""
        pct = self.usage_percentage
        action = BudgetAction.NOTIFY

        for threshold in sorted(self.thresholds, key=lambda t: t.percentage):
            if pct >= threshold.percentage:
                action = threshold.action

        return action

    def can_spend_extended(self, amount_usd: float, user_id: str | None = None) -> SpendResult:
        """Check if spending is allowed with extended overage info.

        Returns:
            SpendResult with allowed status and overage info
        """
        # Check override
        if user_id and user_id in self.override_user_ids:
            if self.override_until is None or time.time() < self.override_until:
                return SpendResult(allowed=True, message="Override active")

        # Check status
        if self.status == BudgetStatus.SUSPENDED:
            return SpendResult(allowed=False, message="Budget suspended")
        if self.status == BudgetStatus.PAUSED:
            return SpendResult(allowed=False, message="Budget paused")
        if self.status == BudgetStatus.CLOSED:
            return SpendResult(allowed=False, message="Budget period closed")

        # Check if period expired
        if self.period_end > 0 and time.time() > self.period_end:
            return SpendResult(allowed=False, message="Budget period expired")

        # Check if within budget
        new_total = self.spent_usd + amount_usd
        if new_total <= self.amount_usd or self.amount_usd <= 0:
            return SpendResult(allowed=True, message="OK")

        # Over budget - check what action to take
        overage_amount = new_total - self.amount_usd
        action = self.current_action

        # Check if overage is allowed
        if self.allow_overage or action == BudgetAction.ALLOW_WITH_CHARGES:
            # Check max overage cap if set
            if self.max_overage_usd is not None:
                total_overage = self.overage_spent_usd + overage_amount
                if total_overage > self.max_overage_usd:
                    return SpendResult(
                        allowed=False,
                        message=f"Overage cap exceeded (${total_overage:.2f}/${self.max_overage_usd:.2f})",
                    )

            return SpendResult(
                allowed=True,
                message=f"Overage allowed at {self.overage_rate_multiplier}x rate",
                is_overage=True,
                overage_amount_usd=overage_amount,
                overage_rate_multiplier=self.overage_rate_multiplier,
            )

        # Hard limit or suspend
        if action == BudgetAction.HARD_LIMIT:
            return SpendResult(
                allowed=False,
                message=f"Budget exceeded (${self.spent_usd:.2f}/${self.amount_usd:.2f})",
            )
        if action == BudgetAction.SUSPEND and self.auto_suspend:
            return SpendResult(allowed=False, message="Budget auto-suspended")

        # Soft limit or warn - allow but flag
        return SpendResult(allowed=True, message="OK")

    def can_spend(self, amount_usd: float, user_id: str | None = None) -> tuple[bool, str]:
        """Check if spending is allowed (legacy interface).

        Returns:
            Tuple of (allowed, reason)
        """
        result = self.can_spend_extended(amount_usd, user_id)
        return (result.allowed, result.message)

    def record_overage(self, amount_usd: float) -> None:
        """Record overage spending.

        Args:
            amount_usd: Amount spent in overage
        """
        self.overage_spent_usd += amount_usd
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "budget_id": self.budget_id,
            "org_id": self.org_id,
            "name": self.name,
            "description": self.description,
            "amount_usd": self.amount_usd,
            "period": self.period.value,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "usage_percentage": self.usage_percentage,
            "period_start": self.period_start,
            "period_start_iso": (
                datetime.fromtimestamp(self.period_start, tz=timezone.utc).isoformat()
                if self.period_start
                else None
            ),
            "period_end": self.period_end,
            "period_end_iso": (
                datetime.fromtimestamp(self.period_end, tz=timezone.utc).isoformat()
                if self.period_end
                else None
            ),
            "status": self.status.value,
            "current_action": self.current_action.value,
            "auto_suspend": self.auto_suspend,
            "is_exceeded": self.is_exceeded,
            "thresholds": [
                {"percentage": t.percentage, "action": t.action.value} for t in self.thresholds
            ],
            # Overage settings
            "allow_overage": self.allow_overage,
            "overage_rate_multiplier": self.overage_rate_multiplier,
            "overage_spent_usd": self.overage_spent_usd,
            "max_overage_usd": self.max_overage_usd,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BudgetAlert:
    """Budget alert event."""

    alert_id: str
    budget_id: str
    org_id: str
    threshold_percentage: float
    action: BudgetAction
    spent_usd: float
    amount_usd: float
    message: str
    created_at: float = field(default_factory=lambda: time.time())
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "budget_id": self.budget_id,
            "org_id": self.org_id,
            "threshold_percentage": self.threshold_percentage,
            "action": self.action.value,
            "spent_usd": self.spent_usd,
            "amount_usd": self.amount_usd,
            "usage_percentage": self.spent_usd / self.amount_usd if self.amount_usd > 0 else 0,
            "message": self.message,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
        }


@dataclass
class BudgetTransaction:
    """A recorded spending transaction against a budget."""

    transaction_id: str
    budget_id: str
    amount_usd: float
    description: str = ""
    debate_id: str | None = None
    user_id: str | None = None
    created_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "transaction_id": self.transaction_id,
            "budget_id": self.budget_id,
            "amount_usd": self.amount_usd,
            "description": self.description,
            "debate_id": self.debate_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }


class BudgetManager:
    """
    Manages budget lifecycle and enforcement.

    Thread-safe with SQLite persistence.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS budgets (
        budget_id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        amount_usd REAL NOT NULL,
        period TEXT NOT NULL,
        spent_usd REAL DEFAULT 0,
        period_start REAL,
        period_end REAL,
        status TEXT DEFAULT 'active',
        auto_suspend INTEGER DEFAULT 1,
        thresholds_json TEXT,
        override_user_ids_json TEXT,
        override_until REAL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        created_by TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_budgets_org ON budgets(org_id);
    CREATE INDEX IF NOT EXISTS idx_budgets_status ON budgets(status);

    CREATE TABLE IF NOT EXISTS budget_alerts (
        alert_id TEXT PRIMARY KEY,
        budget_id TEXT NOT NULL,
        org_id TEXT NOT NULL,
        threshold_percentage REAL NOT NULL,
        action TEXT NOT NULL,
        spent_usd REAL NOT NULL,
        amount_usd REAL NOT NULL,
        message TEXT,
        created_at REAL NOT NULL,
        acknowledged INTEGER DEFAULT 0,
        acknowledged_by TEXT,
        acknowledged_at REAL,
        FOREIGN KEY (budget_id) REFERENCES budgets(budget_id)
    );

    CREATE INDEX IF NOT EXISTS idx_alerts_budget ON budget_alerts(budget_id);
    CREATE INDEX IF NOT EXISTS idx_alerts_org ON budget_alerts(org_id);

    CREATE TABLE IF NOT EXISTS budget_transactions (
        transaction_id TEXT PRIMARY KEY,
        budget_id TEXT NOT NULL,
        amount_usd REAL NOT NULL,
        description TEXT,
        debate_id TEXT,
        user_id TEXT,
        created_at REAL NOT NULL,
        FOREIGN KEY (budget_id) REFERENCES budgets(budget_id)
    );

    CREATE INDEX IF NOT EXISTS idx_transactions_budget ON budget_transactions(budget_id);
    """

    def __init__(self, db_path: str | None = None, event_emitter: Any | None = None):
        """Initialize budget manager.

        Args:
            db_path: Path to SQLite database
            event_emitter: Optional event emitter for COST_ANOMALY events
        """
        db_path = db_path or "budgets.db"
        self._db_path = resolve_db_path(db_path)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            "budget_manager_conn", default=None
        )
        self._connections: list[sqlite3.Connection] = []
        self._init_lock = threading.Lock()
        self._initialized = False
        self._alert_callbacks: list[Callable[[BudgetAlert], None]] = []
        self._alert_cooldowns: dict[str, float] = {}  # budget_id -> last alert time
        self._event_emitter = event_emitter

    def _get_connection(self) -> sqlite3.Connection:
        """Get context-local database connection."""
        conn = self._conn_var.get()
        if conn is None:
            import os

            db_dir = os.path.dirname(self._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            self._conn_var.set(conn)
            self._connections.append(conn)

        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Ensure database schema exists."""
        with self._init_lock:
            if not self._initialized:
                conn.executescript(self.SCHEMA)
                conn.commit()
                self._initialized = True

    def register_alert_callback(self, callback: Callable[[BudgetAlert], None]) -> None:
        """Register a callback for budget alerts."""
        self._alert_callbacks.append(callback)

    # =========================================================================
    # Budget CRUD Operations
    # =========================================================================

    def create_budget(
        self,
        org_id: str,
        name: str,
        amount_usd: float,
        period: BudgetPeriod = BudgetPeriod.MONTHLY,
        description: str = "",
        auto_suspend: bool = True,
        thresholds: list[BudgetThreshold] | None = None,
        created_by: str | None = None,
    ) -> Budget:
        """Create a new budget.

        Args:
            org_id: Organization ID
            name: Budget name
            amount_usd: Budget limit in USD
            period: Budget period type
            description: Optional description
            auto_suspend: Auto-suspend on exceed
            thresholds: Custom alert thresholds
            created_by: User who created the budget

        Returns:
            Created Budget object
        """
        import json

        budget_id = f"budget-{uuid.uuid4().hex[:12]}"
        now = time.time()

        # Calculate period bounds
        period_start, period_end = self._calculate_period_bounds(period)

        budget = Budget(
            budget_id=budget_id,
            org_id=org_id,
            name=name,
            description=description,
            amount_usd=amount_usd,
            period=period,
            period_start=period_start,
            period_end=period_end,
            auto_suspend=auto_suspend,
            thresholds=thresholds or DEFAULT_THRESHOLDS,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )

        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO budgets
            (budget_id, org_id, name, description, amount_usd, period,
             spent_usd, period_start, period_end, status, auto_suspend,
             thresholds_json, override_user_ids_json, created_at, updated_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                budget.budget_id,
                budget.org_id,
                budget.name,
                budget.description,
                budget.amount_usd,
                budget.period.value,
                budget.spent_usd,
                budget.period_start,
                budget.period_end,
                budget.status.value,
                1 if budget.auto_suspend else 0,
                json.dumps(
                    [
                        {"percentage": t.percentage, "action": t.action.value}
                        for t in budget.thresholds
                    ]
                ),
                json.dumps(budget.override_user_ids),
                budget.created_at,
                budget.updated_at,
                budget.created_by,
            ),
        )
        conn.commit()

        logger.info(
            "Created budget %s for org %s: $%.2f/%s", budget_id, org_id, amount_usd, period.value
        )
        return budget

    def create_smb_budget(
        self,
        org_id: str,
        name: str,
        amount_usd: float,
        period: BudgetPeriod = BudgetPeriod.MONTHLY,
        description: str = "",
        created_by: str | None = None,
    ) -> Budget:
        """Create a budget with SMB-strict thresholds (hard block at 90%).

        This is a convenience method for small/medium businesses that want
        stricter cost control to prevent bill shock. The budget will hard-block
        at 90% of the limit, leaving 10% headroom.

        Args:
            org_id: Organization ID
            name: Budget name
            amount_usd: Budget limit in USD
            period: Budget period type (default: monthly)
            description: Optional description
            created_by: User who created the budget

        Returns:
            Created Budget object with SMB-strict thresholds
        """
        return self.create_budget(
            org_id=org_id,
            name=name,
            amount_usd=amount_usd,
            period=period,
            description=description or "SMB-strict budget with 90% hard limit",
            auto_suspend=True,  # Always auto-suspend for SMB
            thresholds=list(SMB_DEFAULT_THRESHOLDS),
            created_by=created_by,
        )

    def get_budget(self, budget_id: str) -> Budget | None:
        """Get a budget by ID."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM budgets WHERE budget_id = ?", (budget_id,))
        row = cursor.fetchone()

        if row:
            return self._budget_from_row(row)
        return None

    def get_budgets_for_org(self, org_id: str, active_only: bool = True) -> list[Budget]:
        """Get all budgets for an organization."""
        conn = self._get_connection()

        if active_only:
            cursor = conn.execute(
                "SELECT * FROM budgets WHERE org_id = ? AND status NOT IN ('closed', 'suspended') ORDER BY created_at DESC",
                (org_id,),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM budgets WHERE org_id = ? ORDER BY created_at DESC",
                (org_id,),
            )

        return [self._budget_from_row(row) for row in cursor.fetchall()]

    def handle_cost_anomaly(
        self,
        org_id: str,
        anomaly_type: str,
        severity: str,
        amount: float,
        expected: float,
    ) -> bool:
        """Handle a cost anomaly by suspending budgets if critical.

        Args:
            org_id: Organization ID
            anomaly_type: Type of anomaly (spike, drift, etc.)
            severity: Severity level (info, warning, critical)
            amount: Actual cost amount
            expected: Expected cost amount

        Returns:
            True if budgets were suspended, False otherwise
        """
        if severity != "critical":
            return False

        budgets = self.get_budgets_for_org(org_id, active_only=True)
        if not budgets:
            return False

        for budget in budgets:
            self.update_budget(budget.budget_id, status=BudgetStatus.SUSPENDED)

        logger.warning(
            "Suspended %s budget(s) for org %s due to %s %s anomaly (actual=%s, expected=%s)",
            len(budgets),
            org_id,
            severity,
            anomaly_type,
            amount,
            expected,
        )

        # Emit COST_ANOMALY event
        if self._event_emitter:
            try:
                from aragora.events.types import StreamEvent, StreamEventType

                self._event_emitter.emit(
                    StreamEvent(
                        type=StreamEventType.COST_ANOMALY,
                        data={
                            "org_id": org_id,
                            "anomaly_type": anomaly_type,
                            "severity": severity,
                            "actual_amount": amount,
                            "expected_amount": expected,
                            "budgets_suspended": len(budgets),
                        },
                    )
                )
            except ImportError:
                pass
            except (AttributeError, TypeError) as exc:
                logger.debug("budget_anomaly_webhook_failed: %s", exc)

        return True

    def is_budget_suspended(self, org_id: str) -> bool:
        """Check if any budget for an organization is suspended.

        Args:
            org_id: Organization ID

        Returns:
            True if any budget is in SUSPENDED state
        """
        all_budgets = self.get_budgets_for_org(org_id, active_only=False)
        return any(b.status == BudgetStatus.SUSPENDED for b in all_budgets)

    def update_budget(
        self,
        budget_id: str,
        name: str | None = None,
        description: str | None = None,
        amount_usd: float | None = None,
        auto_suspend: bool | None = None,
        status: BudgetStatus | None = None,
    ) -> Budget | None:
        """Update a budget."""
        budget = self.get_budget(budget_id)
        if not budget:
            return None

        if name is not None:
            budget.name = name
        if description is not None:
            budget.description = description
        if amount_usd is not None:
            budget.amount_usd = amount_usd
        if auto_suspend is not None:
            budget.auto_suspend = auto_suspend
        if status is not None:
            budget.status = status

        budget.updated_at = time.time()

        conn = self._get_connection()
        conn.execute(
            """
            UPDATE budgets SET
                name = ?, description = ?, amount_usd = ?,
                auto_suspend = ?, status = ?, updated_at = ?
            WHERE budget_id = ?
            """,
            (
                budget.name,
                budget.description,
                budget.amount_usd,
                1 if budget.auto_suspend else 0,
                budget.status.value,
                budget.updated_at,
                budget_id,
            ),
        )
        conn.commit()

        logger.info("Updated budget %s", budget_id)
        return budget

    def delete_budget(self, budget_id: str) -> bool:
        """Delete a budget (soft delete by setting status to closed)."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE budgets SET status = 'closed', updated_at = ? WHERE budget_id = ?",
            (time.time(), budget_id),
        )
        conn.commit()
        return True

    # =========================================================================
    # Budget Enforcement
    # =========================================================================

    def check_budget(
        self,
        org_id: str,
        estimated_cost_usd: float,
        user_id: str | None = None,
    ) -> tuple[bool, str, BudgetAction | None]:
        """Check if an operation is allowed within budget.

        Args:
            org_id: Organization ID
            estimated_cost_usd: Estimated cost of operation
            user_id: User requesting the operation (for override check)

        Returns:
            Tuple of (allowed, reason, action_required)
        """
        configured_budgets = [
            budget
            for budget in self.get_budgets_for_org(org_id, active_only=False)
            if budget.status != BudgetStatus.CLOSED
        ]

        if not configured_budgets:
            # No budget configured - allow
            return True, "No budget configured", None

        warning_result: tuple[bool, str, BudgetAction | None] | None = None

        for budget in configured_budgets:
            if budget.status == BudgetStatus.SUSPENDED:
                return False, "Budget suspended", BudgetAction.SUSPEND

            if budget.status == BudgetStatus.EXCEEDED or budget.is_exceeded:
                return (
                    False,
                    f"Budget exceeded (${budget.spent_usd:.2f}/${budget.amount_usd:.2f})",
                    BudgetAction.HARD_LIMIT,
                )

            allowed, reason = budget.can_spend(estimated_cost_usd, user_id)
            if not allowed:
                if budget.status == BudgetStatus.SUSPENDED:
                    action_required = BudgetAction.SUSPEND
                elif budget.is_exceeded:
                    action_required = BudgetAction.HARD_LIMIT
                else:
                    action_required = budget.current_action
                return False, reason, action_required

            # Check if this would trigger a warning
            new_total = budget.spent_usd + estimated_cost_usd
            new_pct = new_total / budget.amount_usd if budget.amount_usd > 0 else 0

            for threshold in budget.thresholds:
                if (
                    new_pct >= threshold.percentage
                    and budget.usage_percentage < threshold.percentage
                ):
                    # This operation would cross a threshold
                    if threshold.action == BudgetAction.SOFT_LIMIT and warning_result is None:
                        warning_result = (
                            True,
                            f"Warning: This will use {new_pct:.0%} of budget",
                            threshold.action,
                        )

        if warning_result is not None:
            return warning_result

        return True, "OK", None

    def record_spend(
        self,
        org_id: str,
        amount_usd: float,
        description: str = "",
        debate_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Record spending against the organization's budget.

        Args:
            org_id: Organization ID
            amount_usd: Amount spent in USD
            description: Description of the spend
            debate_id: Associated debate ID
            user_id: User who incurred the spend

        Returns:
            True if recorded successfully
        """
        budgets = self.get_budgets_for_org(org_id, active_only=True)

        if not budgets:
            return True  # No budget to track against

        conn = self._get_connection()

        for budget in budgets:
            old_pct = budget.usage_percentage
            budget.spent_usd += amount_usd
            new_pct = budget.usage_percentage

            # Update database
            conn.execute(
                "UPDATE budgets SET spent_usd = ?, updated_at = ? WHERE budget_id = ?",
                (budget.spent_usd, time.time(), budget.budget_id),
            )

            # Record transaction
            conn.execute(
                """
                INSERT INTO budget_transactions
                (transaction_id, budget_id, amount_usd, description, debate_id, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"txn-{uuid.uuid4().hex[:12]}",
                    budget.budget_id,
                    amount_usd,
                    description,
                    debate_id,
                    user_id,
                    time.time(),
                ),
            )

            # Check thresholds and trigger alerts
            self._check_thresholds(budget, old_pct, new_pct)

            # Auto-suspend if exceeded
            if budget.is_exceeded and budget.auto_suspend:
                budget.status = BudgetStatus.SUSPENDED
                conn.execute(
                    "UPDATE budgets SET status = 'suspended', updated_at = ? WHERE budget_id = ?",
                    (time.time(), budget.budget_id),
                )
                logger.warning("Budget %s auto-suspended (exceeded)", budget.budget_id)

            # Trip circuit breaker for exceeded/suspended budgets
            self._check_budget_circuit_breaker(budget)

        conn.commit()
        return True

    def _check_budget_circuit_breaker(self, budget: Budget) -> None:
        """Trip circuit breaker when budget is exceeded or suspended.

        Integrates budget enforcement with the resilience system,
        ensuring that API calls are blocked at the circuit breaker level
        when budgets are exhausted — preventing runaway costs.
        """
        if budget.status not in (BudgetStatus.EXCEEDED, BudgetStatus.SUSPENDED):
            return
        try:
            from aragora.resilience.circuit_breaker import CircuitBreaker

            breaker_name = f"budget_{budget.org_id}"
            if not hasattr(self, "_budget_breakers"):
                self._budget_breakers: dict[str, CircuitBreaker] = {}
            if breaker_name not in self._budget_breakers:
                self._budget_breakers[breaker_name] = CircuitBreaker(
                    name=breaker_name,
                    failure_threshold=1,  # Trip immediately
                    cooldown_seconds=300.0,  # 5 min cooldown before re-check
                )
            breaker = self._budget_breakers[breaker_name]
            breaker.record_failure()
            logger.warning(
                "Budget circuit breaker tripped for org %s: status=%s",
                budget.org_id,
                budget.status.value,
            )
        except ImportError:
            logger.debug("Circuit breaker module unavailable for budget enforcement")
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Budget circuit breaker failed: %s", e)

    def is_budget_circuit_open(self, org_id: str) -> bool:
        """Check if budget circuit breaker is blocking operations for an org.

        Returns True if the circuit is open (operations blocked due to budget).
        """
        if not hasattr(self, "_budget_breakers"):
            return False
        breaker_name = f"budget_{org_id}"
        breaker = self._budget_breakers.get(breaker_name)
        if breaker is None:
            return False
        return not breaker.can_proceed()

    def _check_thresholds(self, budget: Budget, old_pct: float, new_pct: float) -> None:
        """Check if any thresholds were crossed and trigger alerts."""
        for threshold in budget.thresholds:
            if old_pct < threshold.percentage <= new_pct:
                # Threshold crossed - check cooldown
                cooldown_key = f"{budget.budget_id}:{threshold.percentage}"
                last_alert = self._alert_cooldowns.get(cooldown_key, 0)

                if time.time() - last_alert > threshold.cooldown_minutes * 60:
                    alert = self._create_alert(budget, threshold)
                    self._alert_cooldowns[cooldown_key] = time.time()

                    # Trigger callbacks
                    for callback in self._alert_callbacks:
                        try:
                            callback(alert)
                        except (TypeError, ValueError, RuntimeError, OSError) as e:
                            logger.error("Alert callback failed: %s", e)

    def _create_alert(self, budget: Budget, threshold: BudgetThreshold) -> BudgetAlert:
        """Create and persist a budget alert."""
        alert = BudgetAlert(
            alert_id=f"alert-{uuid.uuid4().hex[:12]}",
            budget_id=budget.budget_id,
            org_id=budget.org_id,
            threshold_percentage=threshold.percentage,
            action=threshold.action,
            spent_usd=budget.spent_usd,
            amount_usd=budget.amount_usd,
            message=f"Budget '{budget.name}' reached {threshold.percentage:.0%} "
            f"(${budget.spent_usd:.2f}/${budget.amount_usd:.2f})",
        )

        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO budget_alerts
            (alert_id, budget_id, org_id, threshold_percentage, action,
             spent_usd, amount_usd, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.alert_id,
                alert.budget_id,
                alert.org_id,
                alert.threshold_percentage,
                alert.action.value,
                alert.spent_usd,
                alert.amount_usd,
                alert.message,
                alert.created_at,
            ),
        )
        conn.commit()

        logger.info("Budget alert: %s", alert.message)
        return alert

    # =========================================================================
    # Alerts Management
    # =========================================================================

    def get_alerts(
        self,
        org_id: str | None = None,
        budget_id: str | None = None,
        unacknowledged_only: bool = False,
        limit: int = 50,
    ) -> list[BudgetAlert]:
        """Get budget alerts."""
        conn = self._get_connection()

        query = "SELECT * FROM budget_alerts WHERE 1=1"
        params: list[Any] = []

        if org_id:
            query += " AND org_id = ?"
            params.append(org_id)
        if budget_id:
            query += " AND budget_id = ?"
            params.append(budget_id)
        if unacknowledged_only:
            query += " AND acknowledged = 0"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)

        alerts = []
        for row in cursor.fetchall():
            alerts.append(
                BudgetAlert(
                    alert_id=row["alert_id"],
                    budget_id=row["budget_id"],
                    org_id=row["org_id"],
                    threshold_percentage=row["threshold_percentage"],
                    action=BudgetAction(row["action"]),
                    spent_usd=row["spent_usd"],
                    amount_usd=row["amount_usd"],
                    message=row["message"],
                    created_at=row["created_at"],
                    acknowledged=bool(row["acknowledged"]),
                    acknowledged_by=row["acknowledged_by"],
                    acknowledged_at=row["acknowledged_at"],
                )
            )

        return alerts

    def acknowledge_alert(self, alert_id: str, user_id: str) -> bool:
        """Acknowledge a budget alert."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE budget_alerts SET acknowledged = 1, acknowledged_by = ?, acknowledged_at = ? WHERE alert_id = ?",
            (user_id, time.time(), alert_id),
        )
        conn.commit()
        return True

    # =========================================================================
    # Overrides
    # =========================================================================

    def add_override(
        self,
        budget_id: str,
        user_id: str,
        duration_hours: float | None = None,
    ) -> bool:
        """Add a budget override for a user.

        Args:
            budget_id: Budget ID
            user_id: User ID to grant override
            duration_hours: Override duration (None = permanent)
        """
        import json

        budget = self.get_budget(budget_id)
        if not budget:
            return False

        if user_id not in budget.override_user_ids:
            budget.override_user_ids.append(user_id)

        if duration_hours:
            budget.override_until = time.time() + (duration_hours * 3600)

        conn = self._get_connection()
        conn.execute(
            "UPDATE budgets SET override_user_ids_json = ?, override_until = ?, updated_at = ? WHERE budget_id = ?",
            (json.dumps(budget.override_user_ids), budget.override_until, time.time(), budget_id),
        )
        conn.commit()

        logger.info("Added override for user %s on budget %s", user_id, budget_id)
        return True

    def remove_override(self, budget_id: str, user_id: str) -> bool:
        """Remove a budget override for a user."""
        import json

        budget = self.get_budget(budget_id)
        if not budget:
            return False

        if user_id in budget.override_user_ids:
            budget.override_user_ids.remove(user_id)

        conn = self._get_connection()
        conn.execute(
            "UPDATE budgets SET override_user_ids_json = ?, updated_at = ? WHERE budget_id = ?",
            (json.dumps(budget.override_user_ids), time.time(), budget_id),
        )
        conn.commit()

        return True

    # =========================================================================
    # Utilities
    # =========================================================================

    def _budget_from_row(self, row: sqlite3.Row) -> Budget:
        """Create Budget from database row."""
        import json

        thresholds_data = json.loads(row["thresholds_json"] or "[]")
        thresholds = [
            BudgetThreshold(t["percentage"], BudgetAction(t["action"])) for t in thresholds_data
        ]

        override_ids = json.loads(row["override_user_ids_json"] or "[]")

        return Budget(
            budget_id=row["budget_id"],
            org_id=row["org_id"],
            name=row["name"],
            description=row["description"] or "",
            amount_usd=row["amount_usd"],
            period=BudgetPeriod(row["period"]),
            spent_usd=row["spent_usd"],
            period_start=row["period_start"] or 0,
            period_end=row["period_end"] or 0,
            status=BudgetStatus(row["status"]),
            auto_suspend=bool(row["auto_suspend"]),
            thresholds=thresholds or DEFAULT_THRESHOLDS,
            override_user_ids=override_ids,
            override_until=row["override_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
        )

    def _calculate_period_bounds(self, period: BudgetPeriod) -> tuple[float, float]:
        """Calculate period start and end timestamps."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if period == BudgetPeriod.DAILY:
            start = start_of_day
            end = start + timedelta(days=1)
        elif period == BudgetPeriod.WEEKLY:
            start = start_of_day - timedelta(days=now.weekday())
            end = start + timedelta(weeks=1)
        elif period == BudgetPeriod.MONTHLY:
            start = start_of_day.replace(day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        elif period == BudgetPeriod.QUARTERLY:
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            start = start_of_day.replace(month=quarter_start_month, day=1)
            end_month = quarter_start_month + 3
            if end_month > 12:
                end = start.replace(year=start.year + 1, month=end_month - 12)
            else:
                end = start.replace(month=end_month)
        elif period == BudgetPeriod.ANNUAL:
            start = start_of_day.replace(month=1, day=1)
            end = start.replace(year=start.year + 1)
        else:  # UNLIMITED
            start = start_of_day
            end = start_of_day.replace(year=start.year + 100)

        return start.timestamp(), end.timestamp()

    def reset_period(self, budget_id: str) -> Budget | None:
        """Reset a budget's spending for a new period."""
        budget = self.get_budget(budget_id)
        if not budget:
            return None

        budget.spent_usd = 0.0
        budget.status = BudgetStatus.ACTIVE
        period_start, period_end = self._calculate_period_bounds(budget.period)
        budget.period_start = period_start
        budget.period_end = period_end
        budget.updated_at = time.time()

        conn = self._get_connection()
        conn.execute(
            """
            UPDATE budgets SET
                spent_usd = 0, status = 'active',
                period_start = ?, period_end = ?, updated_at = ?
            WHERE budget_id = ?
            """,
            (period_start, period_end, budget.updated_at, budget_id),
        )
        conn.commit()

        logger.info("Reset budget %s for new period", budget_id)
        return budget

    def get_summary(self, org_id: str) -> dict[str, Any]:
        """Get budget summary for an organization."""
        budgets = self.get_budgets_for_org(org_id, active_only=False)

        total_budget = sum(b.amount_usd for b in budgets if b.status == BudgetStatus.ACTIVE)
        total_spent = sum(b.spent_usd for b in budgets if b.status == BudgetStatus.ACTIVE)
        active_count = len([b for b in budgets if b.status == BudgetStatus.ACTIVE])
        exceeded_count = len([b for b in budgets if b.is_exceeded])

        return {
            "org_id": org_id,
            "total_budget_usd": total_budget,
            "total_spent_usd": total_spent,
            "total_remaining_usd": total_budget - total_spent,
            "overall_usage_percentage": total_spent / total_budget if total_budget > 0 else 0,
            "active_budgets": active_count,
            "exceeded_budgets": exceeded_count,
            "budgets": [b.to_dict() for b in budgets],
        }

    # =========================================================================
    # Transaction History
    # =========================================================================

    def get_transactions(
        self,
        budget_id: str,
        limit: int = 50,
        offset: int = 0,
        date_from: float | None = None,
        date_to: float | None = None,
        user_id: str | None = None,
    ) -> list[BudgetTransaction]:
        """Get transaction history for a budget.

        Args:
            budget_id: Budget ID to get transactions for
            limit: Maximum transactions to return
            offset: Pagination offset
            date_from: Filter by created_at >= date_from (unix timestamp)
            date_to: Filter by created_at <= date_to (unix timestamp)
            user_id: Filter by user who recorded the spend

        Returns:
            List of BudgetTransaction objects
        """
        conn = self._get_connection()

        query = "SELECT * FROM budget_transactions WHERE budget_id = ?"
        params: list[Any] = [budget_id]

        if date_from:
            query += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            query += " AND created_at <= ?"
            params.append(date_to)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)

        transactions = []
        for row in cursor.fetchall():
            transactions.append(
                BudgetTransaction(
                    transaction_id=row["transaction_id"],
                    budget_id=row["budget_id"],
                    amount_usd=row["amount_usd"],
                    description=row["description"] or "",
                    debate_id=row["debate_id"],
                    user_id=row["user_id"],
                    created_at=row["created_at"],
                )
            )

        return transactions

    def count_transactions(
        self,
        budget_id: str,
        date_from: float | None = None,
        date_to: float | None = None,
        user_id: str | None = None,
    ) -> int:
        """Count transactions matching filters."""
        conn = self._get_connection()

        query = "SELECT COUNT(*) FROM budget_transactions WHERE budget_id = ?"
        params: list[Any] = [budget_id]

        if date_from:
            query += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            query += " AND created_at <= ?"
            params.append(date_to)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        cursor = conn.execute(query, params)
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_spending_trends(
        self,
        budget_id: str,
        period: str = "day",
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Get spending trends aggregated by period.

        Args:
            budget_id: Budget ID
            period: Aggregation period ("hour", "day", "week", "month")
            limit: Number of periods to return

        Returns:
            List of dicts with period, total_spent, transaction_count
        """
        conn = self._get_connection()

        # Build date truncation based on period
        if period == "hour":
            # SQLite: truncate to hour
            date_trunc = "strftime('%Y-%m-%d %H:00:00', datetime(created_at, 'unixepoch'))"
        elif period == "day":
            date_trunc = "strftime('%Y-%m-%d', datetime(created_at, 'unixepoch'))"
        elif period == "week":
            # SQLite week: start of week (Sunday)
            date_trunc = "strftime('%Y-%W', datetime(created_at, 'unixepoch'))"
        elif period == "month":
            date_trunc = "strftime('%Y-%m', datetime(created_at, 'unixepoch'))"
        else:
            date_trunc = "strftime('%Y-%m-%d', datetime(created_at, 'unixepoch'))"

        query = f"""
            SELECT
                {date_trunc} as period,
                SUM(amount_usd) as total_spent,
                COUNT(*) as transaction_count,
                AVG(amount_usd) as avg_transaction
            FROM budget_transactions
            WHERE budget_id = ?
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
        """  # nosec B608 - date_trunc is constructed from hardcoded values  # noqa: S608

        cursor = conn.execute(query, (budget_id, limit))

        trends = []
        for row in cursor.fetchall():
            trends.append(
                {
                    "period": row["period"],
                    "total_spent_usd": row["total_spent"] or 0.0,
                    "transaction_count": row["transaction_count"] or 0,
                    "avg_transaction_usd": row["avg_transaction"] or 0.0,
                }
            )

        # Return chronological order (oldest first) for charting
        return list(reversed(trends))

    def get_org_spending_trends(
        self,
        org_id: str,
        period: str = "day",
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Get spending trends for entire organization across all budgets.

        Args:
            org_id: Organization ID
            period: Aggregation period ("hour", "day", "week", "month")
            limit: Number of periods to return

        Returns:
            List of dicts with period, total_spent, transaction_count
        """
        conn = self._get_connection()

        # Build date truncation based on period
        if period == "hour":
            date_trunc = "strftime('%Y-%m-%d %H:00:00', datetime(t.created_at, 'unixepoch'))"
        elif period == "day":
            date_trunc = "strftime('%Y-%m-%d', datetime(t.created_at, 'unixepoch'))"
        elif period == "week":
            date_trunc = "strftime('%Y-%W', datetime(t.created_at, 'unixepoch'))"
        elif period == "month":
            date_trunc = "strftime('%Y-%m', datetime(t.created_at, 'unixepoch'))"
        else:
            date_trunc = "strftime('%Y-%m-%d', datetime(t.created_at, 'unixepoch'))"

        query = f"""
            SELECT
                {date_trunc} as period,
                SUM(t.amount_usd) as total_spent,
                COUNT(*) as transaction_count,
                AVG(t.amount_usd) as avg_transaction
            FROM budget_transactions t
            JOIN budgets b ON t.budget_id = b.budget_id
            WHERE b.org_id = ?
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
        """  # nosec B608 - date_trunc is constructed from hardcoded values  # noqa: S608

        cursor = conn.execute(query, (org_id, limit))

        trends = []
        for row in cursor.fetchall():
            trends.append(
                {
                    "period": row["period"],
                    "total_spent_usd": row["total_spent"] or 0.0,
                    "transaction_count": row["transaction_count"] or 0,
                    "avg_transaction_usd": row["avg_transaction"] or 0.0,
                }
            )

        # Return chronological order (oldest first) for charting
        return list(reversed(trends))


# Module-level singleton
_budget_manager: BudgetManager | None = None


def get_budget_manager(db_path: str | None = None) -> BudgetManager:
    """Get or create the budget manager singleton."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager(db_path)
    elif db_path is not None and _budget_manager._db_path != resolve_db_path(db_path):
        _budget_manager = BudgetManager(db_path)
    return _budget_manager
