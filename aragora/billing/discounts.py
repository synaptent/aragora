"""
Discount Codes System for Aragora Billing.

Provides promotional code management, volume discounts, and discount tracking.

Usage:
    from aragora.billing.discounts import DiscountManager, get_discount_manager

    manager = get_discount_manager()

    # Create a promo code
    code = await manager.create_code(
        code="WELCOME50",
        discount_percent=50,
        max_uses=100,
        expires_at=datetime.now() + timedelta(days=30),
    )

    # Validate and apply a code
    result = await manager.apply_code("WELCOME50", org_id="org_123")
    if result.valid:
        print(f"Applied {result.discount_percent}% discount")
"""

from __future__ import annotations

import contextvars
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)


class DiscountType(str, Enum):
    """Types of discounts."""

    PERCENTAGE = "percentage"  # Percentage off (e.g., 20% off)
    FIXED_AMOUNT = "fixed_amount"  # Fixed dollar amount off
    VOLUME = "volume"  # Volume-based discount tiers


class DiscountCodeStatus(str, Enum):
    """Status of a discount code."""

    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"  # Max uses reached
    DISABLED = "disabled"


@dataclass
class DiscountCode:
    """A promotional discount code."""

    id: str = field(default_factory=lambda: f"disc_{uuid4().hex[:12]}")
    code: str = ""  # User-facing code (e.g., "WELCOME50")
    description: str = ""

    # Discount configuration
    discount_type: DiscountType = DiscountType.PERCENTAGE
    discount_percent: float = 0.0  # For PERCENTAGE type (0-100)
    discount_amount_cents: int = 0  # For FIXED_AMOUNT type

    # Validity constraints
    valid_from: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    max_uses: int | None = None  # None = unlimited
    max_uses_per_org: int = 1  # How many times one org can use it
    min_purchase_cents: int = 0  # Minimum purchase to apply

    # Targeting
    eligible_tiers: list[str] = field(default_factory=list)  # Empty = all tiers
    eligible_org_ids: list[str] = field(default_factory=list)  # Empty = all orgs

    # Status tracking
    status: DiscountCodeStatus = DiscountCodeStatus.ACTIVE
    total_uses: int = 0
    total_discount_cents: int = 0  # Total discount given

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "code": self.code,
            "description": self.description,
            "discount_type": self.discount_type.value,
            "discount_percent": self.discount_percent,
            "discount_amount_cents": self.discount_amount_cents,
            "valid_from": self.valid_from.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "max_uses": self.max_uses,
            "max_uses_per_org": self.max_uses_per_org,
            "min_purchase_cents": self.min_purchase_cents,
            "eligible_tiers": self.eligible_tiers,
            "eligible_org_ids": self.eligible_org_ids,
            "status": self.status.value,
            "total_uses": self.total_uses,
            "total_discount_cents": self.total_discount_cents,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }

    @property
    def is_valid(self) -> bool:
        """Check if code is currently valid."""
        now = datetime.now(timezone.utc)

        # Check status
        if self.status != DiscountCodeStatus.ACTIVE:
            return False

        # Check dates
        if now < self.valid_from:
            return False
        if self.expires_at and now > self.expires_at:
            return False

        # Check usage
        if self.max_uses is not None and self.total_uses >= self.max_uses:
            return False

        return True


@dataclass
class DiscountUsage:
    """Record of discount code usage."""

    id: str = field(default_factory=lambda: f"duse_{uuid4().hex[:12]}")
    code_id: str = ""
    org_id: str = ""
    user_id: str | None = None

    # Applied discount
    original_amount_cents: int = 0
    discount_cents: int = 0
    final_amount_cents: int = 0

    # Context
    invoice_id: str | None = None
    subscription_id: str | None = None

    applied_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "code_id": self.code_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "original_amount_cents": self.original_amount_cents,
            "discount_cents": self.discount_cents,
            "final_amount_cents": self.final_amount_cents,
            "invoice_id": self.invoice_id,
            "subscription_id": self.subscription_id,
            "applied_at": self.applied_at.isoformat(),
        }


@dataclass
class VolumeTier:
    """A volume discount tier."""

    min_spend_cents: int  # Minimum cumulative spend to qualify
    discount_percent: float  # Discount percentage for this tier


@dataclass
class VolumeDiscount:
    """Volume discount configuration for an organization."""

    org_id: str
    tiers: list[VolumeTier] = field(default_factory=list)
    cumulative_spend_cents: int = 0
    current_discount_percent: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def calculate_discount(self) -> float:
        """Calculate discount based on cumulative spend."""
        discount = 0.0
        for tier in sorted(self.tiers, key=lambda t: t.min_spend_cents, reverse=True):
            if self.cumulative_spend_cents >= tier.min_spend_cents:
                discount = tier.discount_percent
                break
        self.current_discount_percent = discount
        return discount

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "org_id": self.org_id,
            "tiers": [
                {"min_spend_cents": t.min_spend_cents, "discount_percent": t.discount_percent}
                for t in self.tiers
            ],
            "cumulative_spend_cents": self.cumulative_spend_cents,
            "current_discount_percent": self.current_discount_percent,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ApplyCodeResult:
    """Result of attempting to apply a discount code."""

    valid: bool
    code: str | None = None
    discount_type: DiscountType | None = None
    discount_percent: float = 0.0
    discount_amount_cents: int = 0
    message: str = ""
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "code": self.code,
            "discount_type": self.discount_type.value if self.discount_type else None,
            "discount_percent": self.discount_percent,
            "discount_amount_cents": self.discount_amount_cents,
            "message": self.message,
            "error_code": self.error_code,
        }


class DiscountManager:
    """
    Manages discount codes and volume discounts.

    Thread-safe SQLite-backed discount storage with support for:
    - Promo code creation and management
    - Code validation and redemption
    - Volume discount tiers
    - Usage tracking
    """

    # Default volume discount tiers
    DEFAULT_VOLUME_TIERS = [
        VolumeTier(min_spend_cents=10000_00, discount_percent=5.0),  # $10k+ = 5%
        VolumeTier(min_spend_cents=50000_00, discount_percent=10.0),  # $50k+ = 10%
        VolumeTier(min_spend_cents=100000_00, discount_percent=15.0),  # $100k+ = 15%
        VolumeTier(min_spend_cents=500000_00, discount_percent=20.0),  # $500k+ = 20%
    ]

    def __init__(self, db_path: str | None = None):
        """
        Initialize discount manager.

        Args:
            db_path: Path to SQLite database. Defaults to ARAGORA_DATA_DIR/discounts.db
        """
        if db_path is None:
            db_path = "discounts.db"

        self.db_path = resolve_db_path(db_path)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            "discount_manager_conn", default=None
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connections: list[sqlite3.Connection] = []
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get context-local database connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS discount_codes (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                description TEXT,
                discount_type TEXT NOT NULL,
                discount_percent REAL DEFAULT 0,
                discount_amount_cents INTEGER DEFAULT 0,
                valid_from TEXT NOT NULL,
                expires_at TEXT,
                max_uses INTEGER,
                max_uses_per_org INTEGER DEFAULT 1,
                min_purchase_cents INTEGER DEFAULT 0,
                eligible_tiers TEXT DEFAULT '[]',
                eligible_org_ids TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active',
                total_uses INTEGER DEFAULT 0,
                total_discount_cents INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_codes_code ON discount_codes(code);
            CREATE INDEX IF NOT EXISTS idx_codes_status ON discount_codes(status);

            CREATE TABLE IF NOT EXISTS discount_usage (
                id TEXT PRIMARY KEY,
                code_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                user_id TEXT,
                original_amount_cents INTEGER DEFAULT 0,
                discount_cents INTEGER DEFAULT 0,
                final_amount_cents INTEGER DEFAULT 0,
                invoice_id TEXT,
                subscription_id TEXT,
                applied_at TEXT NOT NULL,
                FOREIGN KEY (code_id) REFERENCES discount_codes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_usage_code ON discount_usage(code_id);
            CREATE INDEX IF NOT EXISTS idx_usage_org ON discount_usage(org_id);

            CREATE TABLE IF NOT EXISTS volume_discounts (
                org_id TEXT PRIMARY KEY,
                tiers TEXT NOT NULL,
                cumulative_spend_cents INTEGER DEFAULT 0,
                current_discount_percent REAL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """)
        conn.commit()

    async def create_code(
        self,
        code: str,
        discount_percent: float = 0.0,
        discount_amount_cents: int = 0,
        description: str = "",
        expires_at: datetime | None = None,
        max_uses: int | None = None,
        max_uses_per_org: int = 1,
        min_purchase_cents: int = 0,
        eligible_tiers: list[str] | None = None,
        eligible_org_ids: list[str] | None = None,
        created_by: str | None = None,
    ) -> DiscountCode:
        """
        Create a new discount code.

        Args:
            code: User-facing code string (e.g., "WELCOME50")
            discount_percent: Percentage discount (0-100)
            discount_amount_cents: Fixed amount discount in cents
            description: Human-readable description
            expires_at: Optional expiration date
            max_uses: Maximum total uses (None = unlimited)
            max_uses_per_org: Max uses per organization
            min_purchase_cents: Minimum purchase amount to apply
            eligible_tiers: Tiers that can use this code
            eligible_org_ids: Specific orgs that can use this code
            created_by: User ID of creator

        Returns:
            Created DiscountCode

        Raises:
            ValueError: If code already exists or discount values invalid
        """
        # Validate
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("discount_percent must be between 0 and 100")
        if discount_amount_cents < 0:
            raise ValueError("discount_amount_cents must be non-negative")
        if discount_percent == 0 and discount_amount_cents == 0:
            raise ValueError("Must specify either discount_percent or discount_amount_cents")

        discount_type = (
            DiscountType.PERCENTAGE if discount_percent > 0 else DiscountType.FIXED_AMOUNT
        )

        discount_code = DiscountCode(
            code=code.upper().strip(),
            description=description,
            discount_type=discount_type,
            discount_percent=discount_percent,
            discount_amount_cents=discount_amount_cents,
            expires_at=expires_at,
            max_uses=max_uses,
            max_uses_per_org=max_uses_per_org,
            min_purchase_cents=min_purchase_cents,
            eligible_tiers=eligible_tiers or [],
            eligible_org_ids=eligible_org_ids or [],
            created_by=created_by,
        )

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO discount_codes
                (id, code, description, discount_type, discount_percent, discount_amount_cents,
                 valid_from, expires_at, max_uses, max_uses_per_org, min_purchase_cents,
                 eligible_tiers, eligible_org_ids, status, total_uses, total_discount_cents,
                 created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discount_code.id,
                    discount_code.code,
                    discount_code.description,
                    discount_code.discount_type.value,
                    discount_code.discount_percent,
                    discount_code.discount_amount_cents,
                    discount_code.valid_from.isoformat(),
                    discount_code.expires_at.isoformat() if discount_code.expires_at else None,
                    discount_code.max_uses,
                    discount_code.max_uses_per_org,
                    discount_code.min_purchase_cents,
                    str(discount_code.eligible_tiers),
                    str(discount_code.eligible_org_ids),
                    discount_code.status.value,
                    discount_code.total_uses,
                    discount_code.total_discount_cents,
                    discount_code.created_at.isoformat(),
                    discount_code.created_by,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Discount code '{code}' already exists")

        logger.info(
            "Created discount code: %s (%s%% or %sc)", code, discount_percent, discount_amount_cents
        )
        return discount_code

    async def get_code(self, code: str) -> DiscountCode | None:
        """Get a discount code by code string."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM discount_codes WHERE code = ?",
            (code.upper().strip(),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_code(row)

    async def validate_code(
        self,
        code: str,
        org_id: str,
        purchase_amount_cents: int = 0,
        tier: str | None = None,
    ) -> ApplyCodeResult:
        """
        Validate a discount code for an organization.

        Args:
            code: Discount code to validate
            org_id: Organization attempting to use the code
            purchase_amount_cents: Purchase amount for minimum check
            tier: Organization's subscription tier

        Returns:
            ApplyCodeResult with validation status
        """
        discount_code = await self.get_code(code)

        if not discount_code:
            return ApplyCodeResult(
                valid=False,
                code=code,
                message="Invalid discount code",
                error_code="CODE_NOT_FOUND",
            )

        # Check if code is active
        if not discount_code.is_valid:
            # Check specific reasons for invalidity
            if discount_code.status == DiscountCodeStatus.DISABLED:
                return ApplyCodeResult(
                    valid=False,
                    code=code,
                    message="This code is no longer active",
                    error_code="CODE_DISABLED",
                )
            elif discount_code.status == DiscountCodeStatus.EXHAUSTED:
                return ApplyCodeResult(
                    valid=False,
                    code=code,
                    message="This code has reached its maximum uses",
                    error_code="CODE_EXHAUSTED",
                )
            # Check if expired by date (status may still be ACTIVE)
            now = datetime.now(timezone.utc)
            if discount_code.expires_at and now > discount_code.expires_at:
                return ApplyCodeResult(
                    valid=False,
                    code=code,
                    message="This code has expired",
                    error_code="CODE_EXPIRED",
                )
            # Check if not yet valid
            if now < discount_code.valid_from:
                return ApplyCodeResult(
                    valid=False,
                    code=code,
                    message="This code is not yet active",
                    error_code="CODE_NOT_YET_ACTIVE",
                )
            # Check if max uses reached
            if discount_code.max_uses and discount_code.total_uses >= discount_code.max_uses:
                return ApplyCodeResult(
                    valid=False,
                    code=code,
                    message="This code has reached its maximum uses",
                    error_code="CODE_EXHAUSTED",
                )
            # Generic invalid
            return ApplyCodeResult(
                valid=False,
                code=code,
                message="This code is not valid",
                error_code="CODE_INVALID",
            )

        # Check organization eligibility
        if discount_code.eligible_org_ids and org_id not in discount_code.eligible_org_ids:
            return ApplyCodeResult(
                valid=False,
                code=code,
                message="This code is not available for your organization",
                error_code="ORG_NOT_ELIGIBLE",
            )

        # Check tier eligibility
        if tier and discount_code.eligible_tiers and tier not in discount_code.eligible_tiers:
            return ApplyCodeResult(
                valid=False,
                code=code,
                message="This code is not available for your subscription tier",
                error_code="TIER_NOT_ELIGIBLE",
            )

        # Check minimum purchase
        if purchase_amount_cents < discount_code.min_purchase_cents:
            return ApplyCodeResult(
                valid=False,
                code=code,
                message=f"Minimum purchase of ${discount_code.min_purchase_cents / 100:.2f} required",
                error_code="MIN_PURCHASE_NOT_MET",
            )

        # Check per-org usage
        org_uses = await self._get_org_usage_count(discount_code.id, org_id)
        if org_uses >= discount_code.max_uses_per_org:
            return ApplyCodeResult(
                valid=False,
                code=code,
                message="You have already used this code",
                error_code="MAX_USES_PER_ORG",
            )

        # Calculate discount
        if discount_code.discount_type == DiscountType.PERCENTAGE:
            discount_cents = int(purchase_amount_cents * discount_code.discount_percent / 100)
        else:
            discount_cents = min(discount_code.discount_amount_cents, purchase_amount_cents)

        return ApplyCodeResult(
            valid=True,
            code=code,
            discount_type=discount_code.discount_type,
            discount_percent=discount_code.discount_percent,
            discount_amount_cents=discount_cents,
            message=(
                f"Code valid: {discount_code.discount_percent}% off"
                if discount_code.discount_type == DiscountType.PERCENTAGE
                else f"Code valid: ${discount_cents / 100:.2f} off"
            ),
        )

    async def apply_code(
        self,
        code: str,
        org_id: str,
        purchase_amount_cents: int,
        user_id: str | None = None,
        invoice_id: str | None = None,
        subscription_id: str | None = None,
        tier: str | None = None,
    ) -> ApplyCodeResult:
        """
        Validate and apply a discount code.

        Args:
            code: Discount code to apply
            org_id: Organization using the code
            purchase_amount_cents: Purchase amount
            user_id: User applying the code
            invoice_id: Related invoice
            subscription_id: Related subscription
            tier: Organization's tier

        Returns:
            ApplyCodeResult with applied discount
        """
        # First validate
        result = await self.validate_code(code, org_id, purchase_amount_cents, tier)
        if not result.valid:
            return result

        # Get the code object
        discount_code = await self.get_code(code)
        if not discount_code:
            return ApplyCodeResult(
                valid=False, message="Code not found", error_code="CODE_NOT_FOUND"
            )

        # Record usage
        usage = DiscountUsage(
            code_id=discount_code.id,
            org_id=org_id,
            user_id=user_id,
            original_amount_cents=purchase_amount_cents,
            discount_cents=result.discount_amount_cents,
            final_amount_cents=purchase_amount_cents - result.discount_amount_cents,
            invoice_id=invoice_id,
            subscription_id=subscription_id,
        )

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO discount_usage
            (id, code_id, org_id, user_id, original_amount_cents, discount_cents,
             final_amount_cents, invoice_id, subscription_id, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usage.id,
                usage.code_id,
                usage.org_id,
                usage.user_id,
                usage.original_amount_cents,
                usage.discount_cents,
                usage.final_amount_cents,
                usage.invoice_id,
                usage.subscription_id,
                usage.applied_at.isoformat(),
            ),
        )

        # Update code stats
        conn.execute(
            """
            UPDATE discount_codes
            SET total_uses = total_uses + 1,
                total_discount_cents = total_discount_cents + ?
            WHERE id = ?
            """,
            (result.discount_amount_cents, discount_code.id),
        )

        # Check if exhausted
        if discount_code.max_uses and discount_code.total_uses + 1 >= discount_code.max_uses:
            conn.execute(
                "UPDATE discount_codes SET status = ? WHERE id = ?",
                (DiscountCodeStatus.EXHAUSTED.value, discount_code.id),
            )

        conn.commit()

        logger.info(
            "Applied discount code %s for org %s: $%.2f off",
            code,
            org_id,
            result.discount_amount_cents / 100,
        )
        return result

    async def get_volume_discount(self, org_id: str) -> VolumeDiscount:
        """
        Get volume discount for an organization.

        Args:
            org_id: Organization ID

        Returns:
            VolumeDiscount with current tier
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM volume_discounts WHERE org_id = ?",
            (org_id,),
        )
        row = cursor.fetchone()

        if row:
            import json

            tiers = [VolumeTier(**t) for t in json.loads(row["tiers"])]
            volume = VolumeDiscount(
                org_id=org_id,
                tiers=tiers,
                cumulative_spend_cents=row["cumulative_spend_cents"],
                current_discount_percent=row["current_discount_percent"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        else:
            # Create new with default tiers
            volume = VolumeDiscount(
                org_id=org_id,
                tiers=self.DEFAULT_VOLUME_TIERS.copy(),
            )

        volume.calculate_discount()
        return volume

    async def update_volume_spend(
        self,
        org_id: str,
        spend_cents: int,
    ) -> VolumeDiscount:
        """
        Update cumulative spend for volume discount calculation.

        Args:
            org_id: Organization ID
            spend_cents: Additional spend to add

        Returns:
            Updated VolumeDiscount
        """
        import json

        volume = await self.get_volume_discount(org_id)
        volume.cumulative_spend_cents += spend_cents
        volume.updated_at = datetime.now(timezone.utc)
        volume.calculate_discount()

        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO volume_discounts
            (org_id, tiers, cumulative_spend_cents, current_discount_percent, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                org_id,
                json.dumps(
                    [
                        {
                            "min_spend_cents": t.min_spend_cents,
                            "discount_percent": t.discount_percent,
                        }
                        for t in volume.tiers
                    ]
                ),
                volume.cumulative_spend_cents,
                volume.current_discount_percent,
                volume.updated_at.isoformat(),
            ),
        )
        conn.commit()

        logger.debug(
            "Updated volume discount for org %s: $%.2f spent, %s%% discount",
            org_id,
            volume.cumulative_spend_cents / 100,
            volume.current_discount_percent,
        )
        return volume

    async def list_codes(
        self,
        status: DiscountCodeStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DiscountCode]:
        """List discount codes with optional status filter."""
        conn = self._get_conn()

        if status:
            cursor = conn.execute(
                """
                SELECT * FROM discount_codes
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (status.value, limit, offset),
            )
        else:
            cursor = conn.execute(
                """
                SELECT * FROM discount_codes
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        return [self._row_to_code(row) for row in cursor]

    async def disable_code(self, code: str) -> bool:
        """Disable a discount code."""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE discount_codes SET status = ? WHERE code = ?",
            (DiscountCodeStatus.DISABLED.value, code.upper().strip()),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def get_code_usage(
        self,
        code_id: str,
        limit: int = 100,
    ) -> list[DiscountUsage]:
        """Get usage history for a discount code."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT * FROM discount_usage
            WHERE code_id = ?
            ORDER BY applied_at DESC
            LIMIT ?
            """,
            (code_id, limit),
        )

        usages = []
        for row in cursor:
            usages.append(
                DiscountUsage(
                    id=row["id"],
                    code_id=row["code_id"],
                    org_id=row["org_id"],
                    user_id=row["user_id"],
                    original_amount_cents=row["original_amount_cents"],
                    discount_cents=row["discount_cents"],
                    final_amount_cents=row["final_amount_cents"],
                    invoice_id=row["invoice_id"],
                    subscription_id=row["subscription_id"],
                    applied_at=datetime.fromisoformat(row["applied_at"]),
                )
            )
        return usages

    async def _get_org_usage_count(self, code_id: str, org_id: str) -> int:
        """Get how many times an org has used a code."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM discount_usage WHERE code_id = ? AND org_id = ?",
            (code_id, org_id),
        )
        row = cursor.fetchone()
        return row["count"] if row else 0

    def _row_to_code(self, row: sqlite3.Row) -> DiscountCode:
        """Convert database row to DiscountCode."""
        import ast

        return DiscountCode(
            id=row["id"],
            code=row["code"],
            description=row["description"] or "",
            discount_type=DiscountType(row["discount_type"]),
            discount_percent=row["discount_percent"],
            discount_amount_cents=row["discount_amount_cents"],
            valid_from=datetime.fromisoformat(row["valid_from"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            max_uses=row["max_uses"],
            max_uses_per_org=row["max_uses_per_org"],
            min_purchase_cents=row["min_purchase_cents"],
            eligible_tiers=ast.literal_eval(row["eligible_tiers"]) if row["eligible_tiers"] else [],
            eligible_org_ids=(
                ast.literal_eval(row["eligible_org_ids"]) if row["eligible_org_ids"] else []
            ),
            status=DiscountCodeStatus(row["status"]),
            total_uses=row["total_uses"],
            total_discount_cents=row["total_discount_cents"],
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
        )


# Global discount manager instance
_discount_manager: DiscountManager | None = None
_discount_manager_lock = threading.Lock()


def get_discount_manager(db_path: str | None = None) -> DiscountManager:
    """
    Get or create the global discount manager.

    Args:
        db_path: Optional database path (only used for first initialization)

    Returns:
        DiscountManager instance
    """
    global _discount_manager
    with _discount_manager_lock:
        if _discount_manager is None:
            _discount_manager = DiscountManager(db_path)
        return _discount_manager


def reset_discount_manager() -> None:
    """Reset the global discount manager (for testing)."""
    global _discount_manager
    with _discount_manager_lock:
        _discount_manager = None


__all__ = [
    "DiscountType",
    "DiscountCodeStatus",
    "DiscountCode",
    "DiscountUsage",
    "VolumeTier",
    "VolumeDiscount",
    "ApplyCodeResult",
    "DiscountManager",
    "get_discount_manager",
    "reset_discount_manager",
]
