"""
Bank Reconciliation Service.

Automated bank-to-book reconciliation with multi-agent verification:
- Match bank transactions to QBO transactions
- Identify discrepancies (missing, duplicates, amount mismatches)
- Multi-agent debate to resolve complex discrepancies
- Generate reconciliation reports

Usage:
    from aragora.services.accounting.reconciliation import (
        ReconciliationService,
        ReconciliationResult,
    )

    service = ReconciliationService(
        plaid_connector=plaid,
        qbo_connector=qbo,
    )

    result = await service.reconcile(
        plaid_credentials=creds,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )

    print(f"Matched: {result.matched_count}")
    print(f"Discrepancies: {len(result.discrepancies)}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.connectors.accounting.plaid import (
        PlaidConnector,
        PlaidCredentials,
        BankTransaction,
    )
    from aragora.connectors.accounting.qbo import (
        QuickBooksConnector,
        QBOTransaction,
    )

logger = logging.getLogger(__name__)


class DiscrepancyType(str, Enum):
    """Types of reconciliation discrepancies."""

    UNMATCHED_BANK = "unmatched_bank"  # Bank txn with no book match
    UNMATCHED_BOOK = "unmatched_book"  # Book txn with no bank match
    AMOUNT_MISMATCH = "amount_mismatch"  # Amounts don't match
    DATE_MISMATCH = "date_mismatch"  # Dates significantly different
    POTENTIAL_DUPLICATE = "potential_duplicate"  # Possible duplicate entry
    CATEGORIZATION = "categorization"  # Category/account mismatch


class DiscrepancySeverity(str, Enum):
    """Severity of discrepancy."""

    LOW = "low"  # Minor, informational
    MEDIUM = "medium"  # Should be reviewed
    HIGH = "high"  # Requires attention
    CRITICAL = "critical"  # Potential error or fraud


class ResolutionStatus(str, Enum):
    """Status of discrepancy resolution."""

    PENDING = "pending"
    AGENT_SUGGESTED = "agent_suggested"
    USER_RESOLVED = "user_resolved"
    AUTO_RESOLVED = "auto_resolved"
    IGNORED = "ignored"


@dataclass
class MatchedTransaction:
    """A matched bank-to-book transaction pair."""

    bank_txn_id: str
    book_txn_id: str
    bank_amount: Decimal
    book_amount: Decimal
    bank_date: date
    book_date: date
    bank_description: str
    book_description: str
    match_confidence: float = 1.0
    match_method: str = "exact"  # exact, fuzzy, manual

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_txn_id": self.bank_txn_id,
            "book_txn_id": self.book_txn_id,
            "bank_amount": float(self.bank_amount),
            "book_amount": float(self.book_amount),
            "bank_date": self.bank_date.isoformat(),
            "book_date": self.book_date.isoformat(),
            "bank_description": self.bank_description,
            "book_description": self.book_description,
            "match_confidence": self.match_confidence,
            "match_method": self.match_method,
        }


@dataclass
class Discrepancy:
    """A reconciliation discrepancy."""

    discrepancy_id: str
    discrepancy_type: DiscrepancyType
    severity: DiscrepancySeverity
    description: str

    # Transaction references
    bank_txn_id: str | None = None
    book_txn_id: str | None = None
    bank_amount: Decimal | None = None
    book_amount: Decimal | None = None
    bank_date: date | None = None
    book_date: date | None = None
    bank_description: str | None = None
    book_description: str | None = None

    # Resolution
    resolution_status: ResolutionStatus = ResolutionStatus.PENDING
    resolution_suggestion: str | None = None
    resolution_confidence: float = 0.0
    resolved_by: str | None = None
    resolved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "discrepancy_id": self.discrepancy_id,
            "discrepancy_type": self.discrepancy_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "bank_txn_id": self.bank_txn_id,
            "book_txn_id": self.book_txn_id,
            "bank_amount": float(self.bank_amount) if self.bank_amount else None,
            "book_amount": float(self.book_amount) if self.book_amount else None,
            "bank_date": self.bank_date.isoformat() if self.bank_date else None,
            "book_date": self.book_date.isoformat() if self.book_date else None,
            "resolution_status": self.resolution_status.value,
            "resolution_suggestion": self.resolution_suggestion,
            "resolution_confidence": self.resolution_confidence,
        }


@dataclass
class ReconciliationResult:
    """Result of bank reconciliation."""

    reconciliation_id: str
    start_date: date
    end_date: date
    account_id: str
    account_name: str

    # Counts
    bank_transaction_count: int = 0
    book_transaction_count: int = 0
    matched_count: int = 0
    unmatched_bank_count: int = 0
    unmatched_book_count: int = 0

    # Amounts
    bank_total: Decimal = Decimal("0")
    book_total: Decimal = Decimal("0")
    difference: Decimal = Decimal("0")

    # Details
    matched_transactions: list[MatchedTransaction] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)

    # Status
    is_reconciled: bool = False
    reconciled_at: datetime | None = None
    reconciled_by: str | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def discrepancy_count(self) -> int:
        return len(self.discrepancies)

    @property
    def match_rate(self) -> float:
        total = self.bank_transaction_count + self.book_transaction_count
        if total == 0:
            return 1.0
        return (self.matched_count * 2) / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_id": self.reconciliation_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "account_id": self.account_id,
            "account_name": self.account_name,
            "bank_transaction_count": self.bank_transaction_count,
            "book_transaction_count": self.book_transaction_count,
            "matched_count": self.matched_count,
            "unmatched_bank_count": self.unmatched_bank_count,
            "unmatched_book_count": self.unmatched_book_count,
            "bank_total": float(self.bank_total),
            "book_total": float(self.book_total),
            "difference": float(self.difference),
            "discrepancy_count": self.discrepancy_count,
            "match_rate": self.match_rate,
            "is_reconciled": self.is_reconciled,
            "created_at": self.created_at.isoformat(),
        }


class ReconciliationService:
    """
    Automated bank reconciliation service.

    Matches bank transactions to book transactions and identifies discrepancies.
    Uses multi-agent debate for complex discrepancy resolution.
    """

    def __init__(
        self,
        plaid_connector: PlaidConnector | None = None,
        qbo_connector: QuickBooksConnector | None = None,
        match_tolerance_days: int = 3,
        amount_tolerance: Decimal = Decimal("0.01"),
    ):
        """
        Initialize reconciliation service.

        Args:
            plaid_connector: Plaid connector for bank data
            qbo_connector: QuickBooks connector for book data
            match_tolerance_days: Days tolerance for date matching
            amount_tolerance: Amount tolerance for matching
        """
        self.plaid = plaid_connector
        self.qbo = qbo_connector
        self.match_tolerance_days = match_tolerance_days
        self.amount_tolerance = amount_tolerance

        # Reconciliation history
        self._reconciliation_history: dict[str, ReconciliationResult] = {}

    async def reconcile(
        self,
        plaid_credentials: PlaidCredentials,
        start_date: date,
        end_date: date,
        account_id: str | None = None,
        use_agents: bool = True,
    ) -> ReconciliationResult:
        """
        Perform bank reconciliation.

        Args:
            plaid_credentials: Plaid credentials for bank access
            start_date: Start of reconciliation period
            end_date: End of reconciliation period
            account_id: Specific account to reconcile (or all)
            use_agents: Use multi-agent debate for discrepancy resolution

        Returns:
            ReconciliationResult with matches and discrepancies
        """
        import uuid

        reconciliation_id = f"recon_{uuid.uuid4().hex[:12]}"

        # Fetch bank transactions
        bank_txns = await self._fetch_bank_transactions(
            plaid_credentials, start_date, end_date, account_id
        )

        # Fetch book transactions
        book_txns = await self._fetch_book_transactions(start_date, end_date)

        # Get account name
        account_name = "All Accounts"
        if account_id:
            accounts = await self.plaid.get_accounts(plaid_credentials) if self.plaid else []
            for acc in accounts:
                if acc.account_id == account_id:
                    account_name = acc.name
                    break

        # Initialize result
        result = ReconciliationResult(
            reconciliation_id=reconciliation_id,
            start_date=start_date,
            end_date=end_date,
            account_id=account_id or "all",
            account_name=account_name,
            bank_transaction_count=len(bank_txns),
            book_transaction_count=len(book_txns),
        )

        # Calculate totals
        result.bank_total = sum((t.amount for t in bank_txns), Decimal(0))
        result.book_total = sum((Decimal(str(t.total_amount)) for t in book_txns), Decimal(0))
        result.difference = result.bank_total - result.book_total

        # Perform matching
        matched, unmatched_bank, unmatched_book = await self._match_transactions(
            bank_txns, book_txns
        )

        result.matched_transactions = matched
        result.matched_count = len(matched)
        result.unmatched_bank_count = len(unmatched_bank)
        result.unmatched_book_count = len(unmatched_book)

        # Generate discrepancies
        discrepancies = self._generate_discrepancies(unmatched_bank, unmatched_book, matched)
        result.discrepancies = discrepancies

        # Use agents to suggest resolutions
        if use_agents and discrepancies:
            await self._resolve_with_agents(discrepancies)

        # Check if fully reconciled
        result.is_reconciled = (
            len(discrepancies) == 0 and abs(result.difference) <= self.amount_tolerance
        )

        if result.is_reconciled:
            result.reconciled_at = datetime.now(timezone.utc)

        # Store result
        self._reconciliation_history[reconciliation_id] = result

        logger.info(
            f"[Reconciliation] {reconciliation_id}: "
            f"Matched {result.matched_count}, "
            f"Discrepancies {len(discrepancies)}, "
            f"Difference ${float(result.difference):.2f}"
        )

        return result

    async def _fetch_bank_transactions(
        self,
        credentials: PlaidCredentials,
        start_date: date,
        end_date: date,
        account_id: str | None,
    ) -> list[BankTransaction]:
        """Fetch bank transactions from Plaid."""
        if not self.plaid:
            logger.warning("[Reconciliation] Plaid connector not configured")
            return []

        try:
            txns, _ = await self.plaid.get_transactions(
                credentials,
                start_date,
                end_date,
                account_ids=[account_id] if account_id else None,
                include_pending=False,
            )
            return txns
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("[Reconciliation] Failed to fetch bank transactions: %s", e)
            return []

    async def _fetch_book_transactions(
        self,
        start_date: date,
        end_date: date,
    ) -> list[QBOTransaction]:
        """Fetch book transactions from QuickBooks."""
        if not self.qbo:
            logger.warning("[Reconciliation] QBO connector not configured")
            return []

        try:
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date, datetime.max.time())

            # Fetch all transaction types
            invoices = await self.qbo.list_invoices(start_dt, end_dt)
            expenses = await self.qbo.list_expenses(start_dt, end_dt)

            return invoices + expenses
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("[Reconciliation] Failed to fetch book transactions: %s", e)
            return []

    async def _match_transactions(
        self,
        bank_txns: list[BankTransaction],
        book_txns: list[QBOTransaction],
    ) -> tuple[list[MatchedTransaction], list[BankTransaction], list[QBOTransaction]]:
        """
        Match bank transactions to book transactions.

        Uses multiple matching strategies:
        1. Exact match (amount + date)
        2. Fuzzy match (amount + date within tolerance)
        3. Description-based match
        """
        matched: list[MatchedTransaction] = []
        unmatched_bank = list(bank_txns)
        unmatched_book = list(book_txns)

        # Pass 1: Exact amount + date match
        for bank_txn in list(unmatched_bank):
            for book_txn in list(unmatched_book):
                # Compare amounts (note: Plaid positive = expense, negative = income)
                bank_amount = abs(bank_txn.amount)
                book_amount = Decimal(str(abs(book_txn.total_amount)))

                if abs(bank_amount - book_amount) <= self.amount_tolerance:
                    # Compare dates
                    book_date = book_txn.txn_date.date() if book_txn.txn_date else None
                    if book_date and bank_txn.date == book_date:
                        match = MatchedTransaction(
                            bank_txn_id=bank_txn.transaction_id,
                            book_txn_id=book_txn.id,
                            bank_amount=bank_txn.amount,
                            book_amount=Decimal(str(book_txn.total_amount)),
                            bank_date=bank_txn.date,
                            book_date=book_date,
                            bank_description=bank_txn.name,
                            book_description=book_txn.memo or book_txn.customer_name or "",
                            match_confidence=1.0,
                            match_method="exact",
                        )
                        matched.append(match)
                        unmatched_bank.remove(bank_txn)
                        unmatched_book.remove(book_txn)
                        break

        # Pass 2: Fuzzy match (within date tolerance)
        for bank_txn in list(unmatched_bank):
            for book_txn in list(unmatched_book):
                bank_amount = abs(bank_txn.amount)
                book_amount = Decimal(str(abs(book_txn.total_amount)))

                if abs(bank_amount - book_amount) <= self.amount_tolerance:
                    book_date = book_txn.txn_date.date() if book_txn.txn_date else None
                    if book_date:
                        date_diff = abs((bank_txn.date - book_date).days)
                        if date_diff <= self.match_tolerance_days:
                            confidence = 1.0 - (date_diff * 0.1)
                            match = MatchedTransaction(
                                bank_txn_id=bank_txn.transaction_id,
                                book_txn_id=book_txn.id,
                                bank_amount=bank_txn.amount,
                                book_amount=Decimal(str(book_txn.total_amount)),
                                bank_date=bank_txn.date,
                                book_date=book_date,
                                bank_description=bank_txn.name,
                                book_description=book_txn.memo or book_txn.customer_name or "",
                                match_confidence=confidence,
                                match_method="fuzzy",
                            )
                            matched.append(match)
                            unmatched_bank.remove(bank_txn)
                            unmatched_book.remove(book_txn)
                            break

        return matched, unmatched_bank, unmatched_book

    def _generate_discrepancies(
        self,
        unmatched_bank: list[BankTransaction],
        unmatched_book: list[QBOTransaction],
        matched: list[MatchedTransaction],
    ) -> list[Discrepancy]:
        """Generate discrepancy records from unmatched transactions."""
        import uuid

        discrepancies: list[Discrepancy] = []

        # Unmatched bank transactions
        for txn in unmatched_bank:
            severity = DiscrepancySeverity.MEDIUM
            if abs(txn.amount) > 1000:
                severity = DiscrepancySeverity.HIGH

            discrepancies.append(
                Discrepancy(
                    discrepancy_id=f"disc_{uuid.uuid4().hex[:8]}",
                    discrepancy_type=DiscrepancyType.UNMATCHED_BANK,
                    severity=severity,
                    description=f"Bank transaction not found in books: {txn.name} ${abs(float(txn.amount)):.2f}",
                    bank_txn_id=txn.transaction_id,
                    bank_amount=txn.amount,
                    bank_date=txn.date,
                    bank_description=txn.name,
                )
            )

        # Unmatched book transactions (QBOTransaction, not BankTransaction)
        for book_txn in unmatched_book:
            severity = DiscrepancySeverity.MEDIUM
            if abs(book_txn.total_amount) > 1000:
                severity = DiscrepancySeverity.HIGH

            discrepancies.append(
                Discrepancy(
                    discrepancy_id=f"disc_{uuid.uuid4().hex[:8]}",
                    discrepancy_type=DiscrepancyType.UNMATCHED_BOOK,
                    severity=severity,
                    description=f"Book transaction not found in bank: {book_txn.memo or book_txn.doc_number} ${abs(book_txn.total_amount):.2f}",
                    book_txn_id=book_txn.id,
                    book_amount=Decimal(str(book_txn.total_amount)),
                    book_date=book_txn.txn_date.date() if book_txn.txn_date else None,
                    book_description=book_txn.memo or book_txn.doc_number or "",
                )
            )

        # Check for potential duplicates in matched
        seen_amounts: dict[Decimal, list[MatchedTransaction]] = {}
        for match in matched:
            key = abs(match.bank_amount)
            if key not in seen_amounts:
                seen_amounts[key] = []
            seen_amounts[key].append(match)

        for amount, matches in seen_amounts.items():
            if len(matches) > 2:  # More than 2 of same amount is suspicious
                discrepancies.append(
                    Discrepancy(
                        discrepancy_id=f"disc_{uuid.uuid4().hex[:8]}",
                        discrepancy_type=DiscrepancyType.POTENTIAL_DUPLICATE,
                        severity=DiscrepancySeverity.MEDIUM,
                        description=f"Multiple transactions of ${float(amount):.2f} - possible duplicates",
                        bank_amount=amount,
                    )
                )

        return discrepancies

    async def _resolve_with_agents(
        self,
        discrepancies: list[Discrepancy],
    ) -> None:
        """Use multi-agent debate to suggest discrepancy resolutions."""
        try:
            from aragora.debate.arena import DebateArena

            for disc in discrepancies[:10]:  # Limit to first 10 for performance
                if disc.resolution_status != ResolutionStatus.PENDING:
                    continue

                bank_amount = (
                    f"${float(disc.bank_amount):.2f}" if disc.bank_amount is not None else "N/A"
                )
                book_amount = (
                    f"${float(disc.book_amount):.2f}" if disc.book_amount is not None else "N/A"
                )
                question = f"""Suggest a resolution for this bank reconciliation discrepancy:

Type: {disc.discrepancy_type.value}
Description: {disc.description}
Bank Amount: {bank_amount}
Book Amount: {book_amount}
Bank Date: {disc.bank_date or "N/A"}
Book Date: {disc.book_date or "N/A"}

Provide:
1. Most likely explanation for this discrepancy
2. Recommended action (create_entry, ignore, investigate, match_manually)
3. Confidence level (0.0 to 1.0)

Format: EXPLANATION: ... ACTION: ... CONFIDENCE: ..."""

                arena = DebateArena(agents=["anthropic-api", "openai-api"])
                result = await arena.debate(question=question, rounds=1, timeout=15)

                if result and hasattr(result, "final_answer"):
                    import re

                    answer = result.final_answer

                    # Parse suggestion
                    disc.resolution_suggestion = answer[:500]
                    disc.resolution_status = ResolutionStatus.AGENT_SUGGESTED

                    conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", answer, re.IGNORECASE)
                    if conf_match:
                        disc.resolution_confidence = float(conf_match.group(1))

                    logger.debug(
                        "[Reconciliation] Agent suggested resolution for %s", disc.discrepancy_id
                    )

        except ImportError:
            logger.warning("[Reconciliation] Debate arena not available")
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("[Reconciliation] Agent resolution failed: %s", e)

    async def resolve_discrepancy(
        self,
        discrepancy_id: str,
        reconciliation_id: str,
        resolution: str,
        resolved_by: str = "user",
    ) -> bool:
        """
        Manually resolve a discrepancy.

        Args:
            discrepancy_id: ID of discrepancy to resolve
            reconciliation_id: Parent reconciliation ID
            resolution: Resolution action/description
            resolved_by: Who resolved it

        Returns:
            True if successful
        """
        result = self._reconciliation_history.get(reconciliation_id)
        if not result:
            return False

        for disc in result.discrepancies:
            if disc.discrepancy_id == discrepancy_id:
                disc.resolution_status = ResolutionStatus.USER_RESOLVED
                disc.resolution_suggestion = resolution
                disc.resolved_by = resolved_by
                disc.resolved_at = datetime.now(timezone.utc)

                # Check if all discrepancies resolved
                all_resolved = all(
                    d.resolution_status != ResolutionStatus.PENDING for d in result.discrepancies
                )
                if all_resolved:
                    result.is_reconciled = True
                    result.reconciled_at = datetime.now(timezone.utc)
                    result.reconciled_by = resolved_by

                return True

        return False

    def get_reconciliation(
        self,
        reconciliation_id: str,
    ) -> ReconciliationResult | None:
        """Get a reconciliation result by ID."""
        return self._reconciliation_history.get(reconciliation_id)

    def list_reconciliations(
        self,
        account_id: str | None = None,
        limit: int = 10,
    ) -> list[ReconciliationResult]:
        """List reconciliation results."""
        results = list(self._reconciliation_history.values())

        if account_id:
            results = [r for r in results if r.account_id == account_id]

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]


# =============================================================================
# Mock Data for Demo
# =============================================================================


def get_mock_reconciliation_result() -> ReconciliationResult:
    """Generate mock reconciliation result."""
    today = date.today()

    return ReconciliationResult(
        reconciliation_id="recon_demo_001",
        start_date=today - timedelta(days=30),
        end_date=today,
        account_id="acc_checking_001",
        account_name="Business Checking",
        bank_transaction_count=45,
        book_transaction_count=42,
        matched_count=40,
        unmatched_bank_count=5,
        unmatched_book_count=2,
        bank_total=Decimal("-15678.90"),
        book_total=Decimal("-15234.56"),
        difference=Decimal("-444.34"),
        matched_transactions=[
            MatchedTransaction(
                bank_txn_id="txn_001",
                book_txn_id="inv_001",
                bank_amount=Decimal("1250.00"),
                book_amount=Decimal("1250.00"),
                bank_date=today - timedelta(days=5),
                book_date=today - timedelta(days=5),
                bank_description="AWS Cloud Services",
                book_description="AWS Monthly Invoice",
                match_confidence=1.0,
                match_method="exact",
            ),
        ],
        discrepancies=[
            Discrepancy(
                discrepancy_id="disc_001",
                discrepancy_type=DiscrepancyType.UNMATCHED_BANK,
                severity=DiscrepancySeverity.MEDIUM,
                description="Bank transaction not found in books: Office Depot $156.78",
                bank_txn_id="txn_unmatched_001",
                bank_amount=Decimal("156.78"),
                bank_date=today - timedelta(days=3),
                bank_description="Office Depot",
                resolution_status=ResolutionStatus.AGENT_SUGGESTED,
                resolution_suggestion="This appears to be an office supplies purchase. Recommend creating expense entry in QBO under Office Supplies account.",
                resolution_confidence=0.85,
            ),
            Discrepancy(
                discrepancy_id="disc_002",
                discrepancy_type=DiscrepancyType.UNMATCHED_BOOK,
                severity=DiscrepancySeverity.HIGH,
                description="Book transaction not found in bank: INV-1005 $1200.00",
                book_txn_id="inv_1005",
                book_amount=Decimal("1200.00"),
                book_date=today - timedelta(days=10),
                book_description="Invoice 1005 - Consulting Services",
                resolution_status=ResolutionStatus.PENDING,
            ),
        ],
    )


__all__ = [
    "ReconciliationService",
    "ReconciliationResult",
    "MatchedTransaction",
    "Discrepancy",
    "DiscrepancyType",
    "DiscrepancySeverity",
    "ResolutionStatus",
    "get_mock_reconciliation_result",
]
