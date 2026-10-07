"""
Plaid Bank Connector.

Provides bank account connectivity via Plaid:
- Plaid Link integration for secure account connection
- Transaction sync with automatic categorization
- Account balance tracking
- Multi-agent categorization for ambiguous transactions
- Anomaly detection for suspicious activity

Dependencies:
    pip install plaid-python

Environment Variables:
    PLAID_CLIENT_ID - Plaid client ID
    PLAID_SECRET - Plaid secret key
    PLAID_ENVIRONMENT - 'sandbox', 'development', or 'production'
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

from aragora.connectors.model_base import ConnectorDataclass
from aragora.resilience import CircuitBreaker
from aragora.observability.http_client_pool import get_http_pool


class PlaidEnvironment(str, Enum):
    """Plaid environment."""

    SANDBOX = "sandbox"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class TransactionCategory(str, Enum):
    """Transaction categories for accounting."""

    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    PAYROLL = "payroll"
    LOAN = "loan"
    REFUND = "refund"
    INVESTMENT = "investment"
    UNKNOWN = "unknown"


class AccountType(str, Enum):
    """Bank account types."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT = "credit"
    INVESTMENT = "investment"
    LOAN = "loan"
    OTHER = "other"


@dataclass
class PlaidCredentials(ConnectorDataclass):
    """Credentials for a linked Plaid account."""

    _include_none = True

    access_token: str
    item_id: str
    institution_id: str
    institution_name: str
    user_id: str
    tenant_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_sync: datetime | None = None

    def to_dict(self, exclude=None, use_api_names=False) -> dict[str, Any]:
        result = super().to_dict(exclude=exclude, use_api_names=use_api_names)
        result["access_token"] = self.access_token[:20] + "..."  # Mask token
        return result


@dataclass
class BankAccount(ConnectorDataclass):
    """A linked bank account."""

    _include_none = True

    account_id: str
    name: str
    official_name: str | None
    account_type: AccountType
    subtype: str | None
    mask: str  # Last 4 digits
    current_balance: Decimal
    available_balance: Decimal | None
    limit: Decimal | None  # For credit accounts
    currency: str = "USD"
    institution_name: str = ""

    def to_dict(self, exclude=None, use_api_names=False) -> dict[str, Any]:
        result = super().to_dict(exclude=exclude, use_api_names=use_api_names)
        # Convert Decimal to float for API compatibility
        result["current_balance"] = float(self.current_balance)
        result["available_balance"] = (
            float(self.available_balance) if self.available_balance else None
        )
        result["limit"] = float(self.limit) if self.limit else None
        return result


@dataclass
class BankTransaction(ConnectorDataclass):
    """A bank transaction from Plaid."""

    _include_none = True
    _exclude_fields = {"category_id", "anomaly_score", "location"}

    transaction_id: str
    account_id: str
    amount: Decimal  # Positive = outflow, negative = inflow (Plaid convention)
    date: date
    name: str  # Merchant/description
    merchant_name: str | None
    pending: bool

    # Plaid categorization
    category: list[str] = field(default_factory=list)
    category_id: str | None = None

    # Our enriched categorization
    accounting_category: TransactionCategory = TransactionCategory.UNKNOWN
    qbo_account_id: str | None = None  # Mapped QBO account
    confidence: float = 0.0
    categorization_source: str = "plaid"  # plaid, rule, agent, user

    # Anomaly detection
    is_anomaly: bool = False
    anomaly_reason: str | None = None
    anomaly_score: float = 0.0

    # Metadata
    payment_channel: str | None = None  # online, in_store, other
    location: dict[str, Any] | None = None
    iso_currency_code: str = "USD"

    def to_dict(self, exclude=None, use_api_names=False) -> dict[str, Any]:
        result = super().to_dict(exclude=exclude, use_api_names=use_api_names)
        # Convert Decimal to float for API compatibility
        result["amount"] = float(self.amount)
        return result

    @property
    def is_inflow(self) -> bool:
        """Check if this is an inflow (income/deposit)."""
        return self.amount < 0  # Plaid uses negative for credits

    @property
    def is_outflow(self) -> bool:
        """Check if this is an outflow (expense/payment)."""
        return self.amount > 0

    @property
    def absolute_amount(self) -> Decimal:
        """Get absolute amount."""
        return abs(self.amount)


@dataclass
class CategoryMapping:
    """Mapping from Plaid category to QBO account."""

    plaid_category: str
    qbo_account_id: str
    qbo_account_name: str
    accounting_category: TransactionCategory
    confidence: float = 1.0


class PlaidConnector:
    """
    Plaid bank connectivity connector.

    Provides secure bank account linking and transaction sync.
    """

    # Plaid API URLs
    SANDBOX_URL = "https://sandbox.plaid.com"
    DEVELOPMENT_URL = "https://development.plaid.com"
    PRODUCTION_URL = "https://production.plaid.com"

    def __init__(
        self,
        client_id: str | None = None,
        secret: str | None = None,
        environment: PlaidEnvironment | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initialize Plaid connector.

        Args:
            client_id: Plaid client ID (or from PLAID_CLIENT_ID env var)
            secret: Plaid secret (or from PLAID_SECRET env var)
            environment: Plaid environment (or from PLAID_ENVIRONMENT env var)
            circuit_breaker: Optional pre-configured circuit breaker
            enable_circuit_breaker: Enable circuit breaker protection (default: True)
        """
        self.client_id = client_id or os.getenv("PLAID_CLIENT_ID")
        self.secret = secret or os.getenv("PLAID_SECRET")

        if environment is not None:
            self.environment = environment
        else:
            env_str = os.getenv("PLAID_ENVIRONMENT", "sandbox").lower()
            if env_str == "production":
                self.environment = PlaidEnvironment.PRODUCTION
            elif env_str == "development":
                self.environment = PlaidEnvironment.DEVELOPMENT
            else:
                self.environment = PlaidEnvironment.SANDBOX

        self.base_url = {
            PlaidEnvironment.SANDBOX: self.SANDBOX_URL,
            PlaidEnvironment.DEVELOPMENT: self.DEVELOPMENT_URL,
            PlaidEnvironment.PRODUCTION: self.PRODUCTION_URL,
        }[self.environment]

        # Circuit breaker for API resilience
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                name="plaid",
                failure_threshold=3,  # Strict for financial data
                cooldown_seconds=60.0,
            )
        else:
            self._circuit_breaker = None

        # Category mappings
        self._category_mappings: dict[str, CategoryMapping] = {}
        self._load_default_mappings()

        # Transaction history for anomaly detection
        self._transaction_history: dict[str, list[BankTransaction]] = {}

    @property
    def is_configured(self) -> bool:
        """Check if connector is configured."""
        return bool(self.client_id and self.secret)

    def _load_default_mappings(self) -> None:
        """Load default Plaid to QBO category mappings."""
        default_mappings = [
            # Income categories
            ("INCOME_DIVIDENDS", "5000", "Dividend Income", TransactionCategory.INCOME),
            ("INCOME_INTEREST_EARNED", "5001", "Interest Income", TransactionCategory.INCOME),
            ("INCOME_WAGES", "5002", "Salary & Wages", TransactionCategory.INCOME),
            ("TRANSFER_IN_DEPOSIT", "5003", "Deposits", TransactionCategory.INCOME),
            # Expense categories
            (
                "FOOD_AND_DRINK_RESTAURANTS",
                "6100",
                "Meals & Entertainment",
                TransactionCategory.EXPENSE,
            ),
            ("TRAVEL_FLIGHTS", "6200", "Travel", TransactionCategory.EXPENSE),
            ("TRAVEL_LODGING", "6200", "Travel", TransactionCategory.EXPENSE),
            (
                "GENERAL_MERCHANDISE_OFFICE_SUPPLIES",
                "6300",
                "Office Supplies",
                TransactionCategory.EXPENSE,
            ),
            ("RENT_AND_UTILITIES_RENT", "6400", "Rent", TransactionCategory.EXPENSE),
            ("RENT_AND_UTILITIES_UTILITIES", "6410", "Utilities", TransactionCategory.EXPENSE),
            (
                "GENERAL_SERVICES_ACCOUNTING",
                "6500",
                "Professional Services",
                TransactionCategory.EXPENSE,
            ),
            (
                "GENERAL_SERVICES_LEGAL",
                "6500",
                "Professional Services",
                TransactionCategory.EXPENSE,
            ),
            ("LOAN_PAYMENTS_CAR_PAYMENT", "6600", "Loan Payments", TransactionCategory.LOAN),
            ("LOAN_PAYMENTS_CREDIT_CARD", "6610", "Credit Card Payments", TransactionCategory.LOAN),
            # Payroll
            ("TRANSFER_OUT_PAYROLL", "6700", "Payroll Expense", TransactionCategory.PAYROLL),
            # Transfers
            (
                "TRANSFER_IN_INTERNAL_ACCOUNT_TRANSFER",
                "1000",
                "Transfers",
                TransactionCategory.TRANSFER,
            ),
            (
                "TRANSFER_OUT_INTERNAL_ACCOUNT_TRANSFER",
                "1000",
                "Transfers",
                TransactionCategory.TRANSFER,
            ),
        ]

        for plaid_cat, qbo_id, qbo_name, acct_cat in default_mappings:
            self._category_mappings[plaid_cat] = CategoryMapping(
                plaid_category=plaid_cat,
                qbo_account_id=qbo_id,
                qbo_account_name=qbo_name,
                accounting_category=acct_cat,
            )

    async def _request(
        self,
        endpoint: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Make authenticated request to Plaid API with circuit breaker protection."""
        import httpx

        # Check circuit breaker before making request
        if self._circuit_breaker and not self._circuit_breaker.can_proceed():
            cooldown = self._circuit_breaker.cooldown_remaining()
            raise PlaidError(
                "CIRCUIT_BREAKER_OPEN",
                f"Circuit breaker open - retry in {cooldown:.1f}s",
            )

        url = f"{self.base_url}{endpoint}"

        # Add authentication
        payload = {
            "client_id": self.client_id,
            "secret": self.secret,
            **data,
        }

        try:
            pool = get_http_pool()
            async with pool.get_session("plaid") as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                response_data = response.json()

                # Handle transient errors (record failure for circuit breaker)
                if response.status_code >= 500 or response.status_code == 429:
                    if self._circuit_breaker:
                        self._circuit_breaker.record_failure()
                    error_code = response_data.get("error_code", "SERVER_ERROR")
                    error_message = response_data.get(
                        "error_message", f"HTTP {response.status_code}"
                    )
                    raise PlaidError(error_code, error_message)

                # Handle client errors (don't record failure - not transient)
                if response.status_code >= 400:
                    error_code = response_data.get("error_code", "UNKNOWN")
                    error_message = response_data.get("error_message", "Unknown error")
                    raise PlaidError(error_code, error_message)

                # Success - record for circuit breaker
                if self._circuit_breaker:
                    self._circuit_breaker.record_success()

                return response_data

        except httpx.RequestError as e:
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()
            raise PlaidError("NETWORK_ERROR", f"Connection error: {e}")

        except TimeoutError:
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()
            raise PlaidError("TIMEOUT", "Request timeout")

    # =========================================================================
    # Link Token (for Plaid Link UI)
    # =========================================================================

    async def create_link_token(
        self,
        user_id: str,
        tenant_id: str,
        products: list[str] | None = None,
        country_codes: list[str] | None = None,
        language: str = "en",
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a Link token for Plaid Link initialization.

        Args:
            user_id: Unique user identifier
            tenant_id: Tenant identifier for multi-tenancy
            products: Plaid products to enable (default: transactions)
            country_codes: Countries to support (default: US)
            language: Language for Plaid Link
            redirect_uri: OAuth redirect URI (for OAuth institutions)

        Returns:
            Dict with link_token and expiration
        """
        data = {
            "user": {"client_user_id": f"{tenant_id}:{user_id}"},
            "client_name": "Aragora",
            "products": products or ["transactions"],
            "country_codes": country_codes or ["US"],
            "language": language,
        }

        if redirect_uri:
            data["redirect_uri"] = redirect_uri

        response = await self._request("/link/token/create", data)

        return {
            "link_token": response["link_token"],
            "expiration": response["expiration"],
            "request_id": response["request_id"],
        }

    # =========================================================================
    # Public Token Exchange
    # =========================================================================

    async def exchange_public_token(
        self,
        public_token: str,
        user_id: str,
        tenant_id: str,
        institution_id: str,
        institution_name: str,
    ) -> PlaidCredentials:
        """
        Exchange public token for access token after Plaid Link.

        Args:
            public_token: Public token from Plaid Link
            user_id: User identifier
            tenant_id: Tenant identifier
            institution_id: Institution ID
            institution_name: Institution name

        Returns:
            PlaidCredentials for future API calls
        """
        response = await self._request(
            "/item/public_token/exchange",
            {"public_token": public_token},
        )

        credentials = PlaidCredentials(
            access_token=response["access_token"],
            item_id=response["item_id"],
            institution_id=institution_id,
            institution_name=institution_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        logger.info("[Plaid] Linked account for user %s: %s", user_id, institution_name)

        return credentials

    # =========================================================================
    # Account Operations
    # =========================================================================

    async def get_accounts(
        self,
        credentials: PlaidCredentials,
    ) -> list[BankAccount]:
        """
        Get all accounts for a linked item.

        Args:
            credentials: Plaid access credentials

        Returns:
            List of BankAccount objects
        """
        response = await self._request(
            "/accounts/get",
            {"access_token": credentials.access_token},
        )

        accounts = []
        for item in response.get("accounts", []):
            account_type = self._map_account_type(item.get("type", "other"))

            balances = item.get("balances", {})

            accounts.append(
                BankAccount(
                    account_id=item["account_id"],
                    name=item.get("name", ""),
                    official_name=item.get("official_name"),
                    account_type=account_type,
                    subtype=item.get("subtype"),
                    mask=item.get("mask", "****"),
                    current_balance=Decimal(str(balances.get("current", 0))),
                    available_balance=(
                        Decimal(str(balances.get("available", 0)))
                        if balances.get("available") is not None
                        else None
                    ),
                    limit=(
                        Decimal(str(balances.get("limit", 0)))
                        if balances.get("limit") is not None
                        else None
                    ),
                    currency=balances.get("iso_currency_code", "USD"),
                    institution_name=credentials.institution_name,
                )
            )

        return accounts

    def _map_account_type(self, plaid_type: str) -> AccountType:
        """Map Plaid account type to our AccountType enum."""
        mapping = {
            "depository": AccountType.CHECKING,
            "credit": AccountType.CREDIT,
            "loan": AccountType.LOAN,
            "investment": AccountType.INVESTMENT,
            "brokerage": AccountType.INVESTMENT,
        }
        return mapping.get(plaid_type.lower(), AccountType.OTHER)

    # =========================================================================
    # Transaction Operations
    # =========================================================================

    async def get_transactions(
        self,
        credentials: PlaidCredentials,
        start_date: date,
        end_date: date,
        account_ids: list[str] | None = None,
        include_pending: bool = True,
    ) -> tuple[list[BankTransaction], int]:
        """
        Get transactions for linked accounts.

        Args:
            credentials: Plaid access credentials
            start_date: Start date for transaction range
            end_date: End date for transaction range
            account_ids: Optional list of specific account IDs
            include_pending: Include pending transactions

        Returns:
            Tuple of (transactions, total_count)
        """
        data: dict[str, Any] = {
            "access_token": credentials.access_token,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": {
                "include_personal_finance_category": True,
            },
        }

        if account_ids:
            data["options"]["account_ids"] = account_ids

        response = await self._request("/transactions/get", data)

        transactions = []
        for item in response.get("transactions", []):
            if not include_pending and item.get("pending", False):
                continue

            txn = self._parse_transaction(item)
            transactions.append(txn)

        # Update credentials last sync
        credentials.last_sync = datetime.now(timezone.utc)

        total = response.get("total_transactions", len(transactions))

        logger.info(
            "[Plaid] Fetched %s transactions for %s",
            len(transactions),
            credentials.institution_name,
        )

        return transactions, total

    async def sync_transactions(
        self,
        credentials: PlaidCredentials,
        cursor: str | None = None,
    ) -> tuple[list[BankTransaction], list[str], str]:
        """
        Sync transactions using Plaid's sync endpoint (incremental).

        Args:
            credentials: Plaid access credentials
            cursor: Previous sync cursor (None for initial sync)

        Returns:
            Tuple of (added_transactions, removed_txn_ids, new_cursor)
        """
        data: dict[str, Any] = {
            "access_token": credentials.access_token,
            "options": {
                "include_personal_finance_category": True,
            },
        }

        if cursor:
            data["cursor"] = cursor

        response = await self._request("/transactions/sync", data)

        added = [self._parse_transaction(t) for t in response.get("added", [])]
        removed = [t["transaction_id"] for t in response.get("removed", [])]
        new_cursor = response.get("next_cursor", "")

        # Handle pagination
        has_more = response.get("has_more", False)
        while has_more:
            data["cursor"] = new_cursor
            response = await self._request("/transactions/sync", data)
            added.extend([self._parse_transaction(t) for t in response.get("added", [])])
            removed.extend([t["transaction_id"] for t in response.get("removed", [])])
            new_cursor = response.get("next_cursor", "")
            has_more = response.get("has_more", False)

        credentials.last_sync = datetime.now(timezone.utc)

        logger.info("[Plaid] Synced %s added, %s removed transactions", len(added), len(removed))

        return added, removed, new_cursor

    def _parse_transaction(self, item: dict[str, Any]) -> BankTransaction:
        """Parse Plaid transaction into BankTransaction."""
        # Get personal finance category
        pfc = item.get("personal_finance_category", {})
        primary_cat = pfc.get("primary", "")
        detailed_cat = pfc.get("detailed", "")

        # Build category list
        category = item.get("category", [])
        if detailed_cat:
            category = [detailed_cat]

        # Map to accounting category
        accounting_cat, qbo_account, confidence = self._categorize_transaction(
            detailed_cat or primary_cat, category
        )

        # Parse date
        txn_date = date.fromisoformat(item["date"])

        txn = BankTransaction(
            transaction_id=item["transaction_id"],
            account_id=item["account_id"],
            amount=Decimal(str(item["amount"])),
            date=txn_date,
            name=item.get("name", ""),
            merchant_name=item.get("merchant_name"),
            pending=item.get("pending", False),
            category=category,
            category_id=item.get("category_id"),
            accounting_category=accounting_cat,
            qbo_account_id=qbo_account,
            confidence=confidence,
            categorization_source="plaid",
            payment_channel=item.get("payment_channel"),
            location=item.get("location"),
            iso_currency_code=item.get("iso_currency_code", "USD"),
        )

        return txn

    def _categorize_transaction(
        self,
        plaid_category: str,
        category_list: list[str],
    ) -> tuple[TransactionCategory, str | None, float]:
        """
        Categorize transaction using mapping.

        Returns:
            Tuple of (accounting_category, qbo_account_id, confidence)
        """
        # Check exact match first
        if plaid_category in self._category_mappings:
            mapping = self._category_mappings[plaid_category]
            return mapping.accounting_category, mapping.qbo_account_id, mapping.confidence

        # Check category list for partial matches
        for cat in category_list:
            for key, mapping in self._category_mappings.items():
                if key in cat.upper() or cat.upper() in key:
                    return mapping.accounting_category, mapping.qbo_account_id, 0.7

        # Default based on amount direction (will be refined later)
        return TransactionCategory.UNKNOWN, None, 0.0

    # =========================================================================
    # Anomaly Detection
    # =========================================================================

    async def detect_anomalies(
        self,
        transactions: list[BankTransaction],
        account_id: str,
    ) -> list[BankTransaction]:
        """
        Detect anomalous transactions.

        Uses simple statistical methods:
        - Unusual amount (> 3 std deviations from mean)
        - Unusual merchant (first time)
        - Unusual time (e.g., late night)
        - Duplicate detection

        Args:
            transactions: Transactions to analyze
            account_id: Account ID for context

        Returns:
            Transactions with anomaly flags set
        """
        # Get historical data
        history = self._transaction_history.get(account_id, [])

        if not history:
            # No history to compare against
            self._transaction_history[account_id] = transactions
            return transactions

        # Calculate statistics from history
        amounts = [float(t.amount) for t in history if not t.pending]
        if not amounts:
            return transactions

        import statistics

        try:
            mean_amount = statistics.mean(amounts)
            std_amount = statistics.stdev(amounts) if len(amounts) > 1 else mean_amount * 0.5
        except statistics.StatisticsError:
            mean_amount = 0
            std_amount = 100

        # Known merchants
        known_merchants = {t.merchant_name or t.name for t in history}

        # Check each transaction
        for txn in transactions:
            anomaly_reasons = []

            # Amount anomaly
            if abs(float(txn.amount) - mean_amount) > 3 * std_amount:
                anomaly_reasons.append(
                    f"Unusual amount: ${abs(float(txn.amount)):.2f} (avg: ${abs(mean_amount):.2f})"
                )

            # New merchant
            merchant = txn.merchant_name or txn.name
            if merchant and merchant not in known_merchants:
                # Only flag large transactions from new merchants
                if abs(float(txn.amount)) > mean_amount * 2:
                    anomaly_reasons.append(f"New merchant with large amount: {merchant}")

            # Duplicate detection (same amount, same day, same merchant)
            recent_txns = [
                t
                for t in history
                if t.date == txn.date
                and t.amount == txn.amount
                and (t.merchant_name or t.name) == (txn.merchant_name or txn.name)
            ]
            if recent_txns:
                anomaly_reasons.append("Potential duplicate transaction")

            if anomaly_reasons:
                txn.is_anomaly = True
                txn.anomaly_reason = "; ".join(anomaly_reasons)
                txn.anomaly_score = min(1.0, len(anomaly_reasons) * 0.3)

        # Update history
        self._transaction_history[account_id] = (history + transactions)[-1000:]  # Keep last 1000

        return transactions

    # =========================================================================
    # Multi-Agent Categorization
    # =========================================================================

    async def categorize_with_agents(
        self,
        transactions: list[BankTransaction],
        qbo_accounts: list[dict[str, Any]] | None = None,
    ) -> list[BankTransaction]:
        """
        Use multi-agent debate to categorize ambiguous transactions.

        Only categorizes transactions with low confidence.

        Args:
            transactions: Transactions to categorize
            qbo_accounts: Available QBO accounts for mapping

        Returns:
            Transactions with updated categories
        """
        # Filter to low-confidence transactions
        ambiguous = [t for t in transactions if t.confidence < 0.5]

        if not ambiguous:
            return transactions

        try:
            from aragora.debate.arena import DebateArena

            for txn in ambiguous:
                # Build categorization prompt
                accounts_context = ""
                if qbo_accounts:
                    account_list = "\n".join(
                        [
                            f"- {a['name']} (ID: {a['id']}, Type: {a['accountType']})"
                            for a in qbo_accounts[:20]
                        ]
                    )
                    accounts_context = f"\nAvailable QBO accounts:\n{account_list}"

                question = f"""Categorize this bank transaction for accounting:

Transaction:
- Description: {txn.name}
- Merchant: {txn.merchant_name or "Unknown"}
- Amount: ${abs(float(txn.amount)):.2f} ({"expense/outflow" if txn.is_outflow else "income/inflow"})
- Date: {txn.date}
- Plaid Category: {", ".join(txn.category) if txn.category else "Uncategorized"}
{accounts_context}

Provide:
1. CATEGORY: income, expense, transfer, payroll, loan, refund, or investment
2. QBO_ACCOUNT: Best matching account name from the list (or suggest one)
3. CONFIDENCE: 0.0 to 1.0
4. REASON: Brief explanation"""

                arena = DebateArena(agents=["anthropic-api", "openai-api"])
                result = await arena.debate(question=question, rounds=1, timeout=15)

                if result and hasattr(result, "final_answer"):
                    # Parse result
                    import re

                    answer = result.final_answer

                    cat_match = re.search(r"CATEGORY:\s*(\w+)", answer, re.IGNORECASE)
                    if cat_match:
                        cat_str = cat_match.group(1).lower()
                        try:
                            txn.accounting_category = TransactionCategory(cat_str)
                        except ValueError as e:
                            logger.debug("plaid operation failed: %s", e)

                    conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", answer, re.IGNORECASE)
                    if conf_match:
                        txn.confidence = float(conf_match.group(1))

                    txn.categorization_source = "agent"

                    logger.debug(
                        "[Plaid] Agent categorized %s: %s", txn.name, txn.accounting_category.value
                    )

        except ImportError:
            logger.warning("[Plaid] Debate arena not available for categorization")
        except (ValueError, RuntimeError, TypeError, KeyError) as e:
            logger.error("[Plaid] Agent categorization failed: %s", e)

        return transactions

    # =========================================================================
    # Item Management
    # =========================================================================

    async def remove_item(self, credentials: PlaidCredentials) -> bool:
        """
        Remove a linked item (disconnect bank).

        Args:
            credentials: Credentials for the item to remove

        Returns:
            True if successful
        """
        try:
            await self._request(
                "/item/remove",
                {"access_token": credentials.access_token},
            )
            logger.info(
                "[Plaid] Removed item %s for user %s", credentials.item_id, credentials.user_id
            )
            return True
        except PlaidError as e:
            logger.error("[Plaid] Failed to remove item: %s", e)
            return False

    async def get_item_status(
        self,
        credentials: PlaidCredentials,
    ) -> dict[str, Any]:
        """Get status of linked item."""
        response = await self._request(
            "/item/get",
            {"access_token": credentials.access_token},
        )

        item = response.get("item", {})
        status = response.get("status", {})

        return {
            "item_id": item.get("item_id"),
            "institution_id": item.get("institution_id"),
            "available_products": item.get("available_products", []),
            "billed_products": item.get("billed_products", []),
            "consent_expiration_time": item.get("consent_expiration_time"),
            "error": item.get("error"),
            "transactions_status": status.get("transactions", {}),
        }


class PlaidError(Exception):
    """Plaid API error."""

    def __init__(self, error_code: str, error_message: str):
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(f"[{error_code}] {error_message}")


# =============================================================================
# Mock Data for Demo
# =============================================================================


def get_mock_accounts() -> list[BankAccount]:
    """Generate mock bank account data."""
    return [
        BankAccount(
            account_id="acc_checking_001",
            name="Business Checking",
            official_name="Business Checking Account",
            account_type=AccountType.CHECKING,
            subtype="checking",
            mask="1234",
            current_balance=Decimal("45678.90"),
            available_balance=Decimal("44500.00"),
            limit=None,
            institution_name="Demo Bank",
        ),
        BankAccount(
            account_id="acc_savings_001",
            name="Business Savings",
            official_name="Business Savings Account",
            account_type=AccountType.SAVINGS,
            subtype="savings",
            mask="5678",
            current_balance=Decimal("125000.00"),
            available_balance=Decimal("125000.00"),
            limit=None,
            institution_name="Demo Bank",
        ),
        BankAccount(
            account_id="acc_credit_001",
            name="Business Credit Card",
            official_name="Business Platinum Card",
            account_type=AccountType.CREDIT,
            subtype="credit card",
            mask="9012",
            current_balance=Decimal("3456.78"),
            available_balance=Decimal("21543.22"),
            limit=Decimal("25000.00"),
            institution_name="Demo Bank",
        ),
    ]


def get_mock_transactions() -> list[BankTransaction]:
    """Generate mock transaction data."""
    today = date.today()
    return [
        BankTransaction(
            transaction_id="txn_001",
            account_id="acc_checking_001",
            amount=Decimal("1250.00"),
            date=today - timedelta(days=1),
            name="AWS Cloud Services",
            merchant_name="Amazon Web Services",
            pending=False,
            category=["GENERAL_SERVICES_OTHER_GENERAL_SERVICES"],
            accounting_category=TransactionCategory.EXPENSE,
            confidence=0.9,
        ),
        BankTransaction(
            transaction_id="txn_002",
            account_id="acc_checking_001",
            amount=Decimal("-15000.00"),
            date=today - timedelta(days=2),
            name="Client Payment - Acme Corp",
            merchant_name=None,
            pending=False,
            category=["TRANSFER_IN_DEPOSIT"],
            accounting_category=TransactionCategory.INCOME,
            confidence=0.85,
        ),
        BankTransaction(
            transaction_id="txn_003",
            account_id="acc_checking_001",
            amount=Decimal("89.99"),
            date=today - timedelta(days=3),
            name="Zoom Video Communications",
            merchant_name="Zoom",
            pending=False,
            category=["GENERAL_SERVICES_OTHER_GENERAL_SERVICES"],
            accounting_category=TransactionCategory.EXPENSE,
            confidence=0.95,
        ),
        BankTransaction(
            transaction_id="txn_004",
            account_id="acc_credit_001",
            amount=Decimal("156.78"),
            date=today,
            name="Office Depot",
            merchant_name="Office Depot",
            pending=True,
            category=["GENERAL_MERCHANDISE_OFFICE_SUPPLIES"],
            accounting_category=TransactionCategory.EXPENSE,
            confidence=0.9,
        ),
    ]


__all__ = [
    "PlaidConnector",
    "PlaidCredentials",
    "PlaidEnvironment",
    "PlaidError",
    "BankAccount",
    "BankTransaction",
    "AccountType",
    "TransactionCategory",
    "CategoryMapping",
    "get_mock_accounts",
    "get_mock_transactions",
]
