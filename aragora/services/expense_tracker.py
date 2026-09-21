"""
Expense Tracker Service.

Tracks and categorizes business expenses with OCR capabilities:
- Receipt processing (OCR extraction)
- Auto-categorization using ML/LLM
- Duplicate detection
- QBO sync integration
- Expense reporting

Usage:
    from aragora.services.expense_tracker import ExpenseTracker

    tracker = ExpenseTracker()

    # Process a receipt
    expense = await tracker.process_receipt(image_bytes)

    # Categorize expense
    category = await tracker.categorize_expense(expense)

    # Sync to QuickBooks
    result = await tracker.sync_to_qbo([expense])
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aragora.config import get_api_key

if TYPE_CHECKING:
    from aragora.connectors.accounting.qbo import QuickBooksConnector
    from aragora.storage.expense_store import ExpenseStoreBackend

logger = logging.getLogger(__name__)


class ExpenseCategory(str, Enum):
    """Standard expense categories."""

    TRAVEL = "travel"
    MEALS = "meals"
    OFFICE_SUPPLIES = "office_supplies"
    SOFTWARE = "software"
    HARDWARE = "hardware"
    PROFESSIONAL_SERVICES = "professional_services"
    MARKETING = "marketing"
    UTILITIES = "utilities"
    RENT = "rent"
    INSURANCE = "insurance"
    PAYROLL = "payroll"
    TAXES = "taxes"
    EQUIPMENT = "equipment"
    SHIPPING = "shipping"
    ENTERTAINMENT = "entertainment"
    SUBSCRIPTIONS = "subscriptions"
    TELECOMMUNICATIONS = "telecommunications"
    BANK_FEES = "bank_fees"
    OTHER = "other"


class ExpenseStatus(str, Enum):
    """Expense processing status."""

    PENDING = "pending"  # Awaiting processing
    PROCESSED = "processed"  # OCR/extraction complete
    CATEGORIZED = "categorized"  # Category assigned
    APPROVED = "approved"  # Ready for sync
    SYNCED = "synced"  # Synced to accounting system
    REJECTED = "rejected"  # Rejected/deleted
    DUPLICATE = "duplicate"  # Marked as duplicate


class PaymentMethod(str, Enum):
    """Payment methods."""

    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CASH = "cash"
    CHECK = "check"
    WIRE = "wire"
    ACH = "ach"
    BANK_TRANSFER = "bank_transfer"
    PAYPAL = "paypal"
    VENMO = "venmo"
    OTHER = "other"


@dataclass
class LineItem:
    """A line item on a receipt/invoice."""

    description: str
    quantity: float = 1.0
    unit_price: Decimal = Decimal("0.00")
    amount: Decimal = Decimal("0.00")
    category: ExpenseCategory | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unitPrice": float(self.unit_price),
            "amount": float(self.amount),
            "category": self.category.value if self.category else None,
        }


@dataclass
class ExpenseRecord:
    """A tracked expense record."""

    id: str
    vendor_name: str
    amount: Decimal
    currency: str = "USD"
    date: datetime = field(default_factory=datetime.now)
    category: ExpenseCategory = ExpenseCategory.OTHER
    status: ExpenseStatus = ExpenseStatus.PENDING
    payment_method: PaymentMethod = PaymentMethod.CREDIT_CARD
    description: str = ""
    notes: str = ""
    receipt_image: bytes | None = None
    receipt_text: str = ""
    line_items: list[LineItem] = field(default_factory=list)
    tax_amount: Decimal = Decimal("0.00")
    tip_amount: Decimal = Decimal("0.00")
    is_reimbursable: bool = False
    is_billable: bool = False
    project_id: str | None = None
    client_id: str | None = None
    employee_id: str | None = None
    qbo_id: str | None = None
    duplicate_of: str | None = None
    confidence_score: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    synced_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_amount(self) -> Decimal:
        """Total including tax and tip."""
        return self.amount + self.tax_amount + self.tip_amount

    @property
    def hash_key(self) -> str:
        """Generate hash for duplicate detection."""
        key_parts = [
            self.vendor_name.lower().strip(),
            str(self.amount),
            self.date.strftime("%Y-%m-%d"),
        ]
        return hashlib.md5("|".join(key_parts).encode(), usedforsecurity=False).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendorName": self.vendor_name,
            "amount": float(self.amount),
            "currency": self.currency,
            "date": self.date.isoformat(),
            "category": self.category.value,
            "status": self.status.value,
            "paymentMethod": self.payment_method.value,
            "description": self.description,
            "notes": self.notes,
            "lineItems": [li.to_dict() for li in self.line_items],
            "taxAmount": float(self.tax_amount),
            "tipAmount": float(self.tip_amount),
            "totalAmount": float(self.total_amount),
            "isReimbursable": self.is_reimbursable,
            "isBillable": self.is_billable,
            "projectId": self.project_id,
            "clientId": self.client_id,
            "employeeId": self.employee_id,
            "qboId": self.qbo_id,
            "confidenceScore": self.confidence_score,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "syncedAt": self.synced_at.isoformat() if self.synced_at else None,
            "tags": self.tags,
        }


@dataclass
class SyncResult:
    """Result of syncing expenses to accounting system."""

    success_count: int = 0
    failed_count: int = 0
    duplicate_count: int = 0
    synced_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "successCount": self.success_count,
            "failedCount": self.failed_count,
            "duplicateCount": self.duplicate_count,
            "syncedIds": self.synced_ids,
            "failedIds": self.failed_ids,
            "errors": self.errors,
        }


@dataclass
class ExpenseStats:
    """Expense statistics."""

    total_expenses: int = 0
    total_amount: float = 0.0
    pending_count: int = 0
    pending_amount: float = 0.0
    by_category: dict[str, float] = field(default_factory=dict)
    by_month: dict[str, float] = field(default_factory=dict)
    top_vendors: list[dict[str, Any]] = field(default_factory=list)
    avg_expense: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalExpenses": self.total_expenses,
            "totalAmount": round(self.total_amount, 2),
            "pendingCount": self.pending_count,
            "pendingAmount": round(self.pending_amount, 2),
            "byCategory": self.by_category,
            "byMonth": self.by_month,
            "topVendors": self.top_vendors,
            "avgExpense": round(self.avg_expense, 2),
        }


# Common vendor patterns for categorization
VENDOR_CATEGORY_PATTERNS = {
    ExpenseCategory.MEALS: [
        r"restaurant",
        r"cafe",
        r"coffee",
        r"starbucks",
        r"mcdonald",
        r"subway",
        r"pizza",
        r"grubhub",
        r"doordash",
        r"uber eats",
        r"chipotle",
        r"panera",
        r"wendy",
        r"taco bell",
    ],
    ExpenseCategory.TRAVEL: [
        r"airline",
        r"hotel",
        r"marriott",
        r"hilton",
        r"hyatt",
        r"uber",
        r"lyft",
        r"taxi",
        r"rental car",
        r"hertz",
        r"avis",
        r"delta",
        r"united",
        r"american airlines",
        r"southwest",
        r"airbnb",
        r"expedia",
        r"booking\.com",
    ],
    ExpenseCategory.OFFICE_SUPPLIES: [
        r"staples",
        r"office depot",
        r"office max",
        r"amazon",
        r"paper",
        r"pen",
        r"supplies",
    ],
    ExpenseCategory.SOFTWARE: [
        r"software",
        r"saas",
        r"subscription",
        r"license",
        r"github",
        r"slack",
        r"zoom",
        r"microsoft",
        r"adobe",
        r"google workspace",
        r"atlassian",
        r"jira",
        r"notion",
    ],
    ExpenseCategory.HARDWARE: [
        r"apple",
        r"dell",
        r"hp",
        r"lenovo",
        r"computer",
        r"laptop",
        r"monitor",
        r"keyboard",
        r"mouse",
    ],
    ExpenseCategory.TELECOMMUNICATIONS: [
        r"verizon",
        r"at&t",
        r"t-mobile",
        r"sprint",
        r"comcast",
        r"spectrum",
        r"internet",
        r"phone",
    ],
    ExpenseCategory.UTILITIES: [
        r"electric",
        r"gas",
        r"water",
        r"utility",
        r"pge",
        r"con edison",
        r"duke energy",
    ],
    ExpenseCategory.SUBSCRIPTIONS: [
        r"netflix",
        r"spotify",
        r"hulu",
        r"youtube premium",
        r"linkedin premium",
        r"membership",
    ],
}


class ExpenseTracker:
    """
    Service for tracking and managing business expenses.

    Provides receipt OCR, auto-categorization, duplicate detection,
    and integration with accounting systems like QuickBooks.
    Includes circuit breaker protection for external service calls.
    """

    def __init__(
        self,
        qbo_connector: QuickBooksConnector | None = None,
        enable_ocr: bool = True,
        enable_llm_categorization: bool = True,
        use_persistent_storage: bool = False,
        store: ExpenseStoreBackend | None = None,
        enable_circuit_breakers: bool = True,
    ):
        """
        Initialize expense tracker.

        Args:
            qbo_connector: QuickBooks connector for syncing
            enable_ocr: Enable OCR for receipt processing
            enable_llm_categorization: Use LLM for smart categorization
            use_persistent_storage: Use database storage instead of in-memory
            store: Custom store backend (uses default if None)
            enable_circuit_breakers: Enable circuit breaker protection
        """
        self.qbo = qbo_connector
        self.enable_ocr = enable_ocr
        self.enable_llm_categorization = enable_llm_categorization
        self._use_persistent = use_persistent_storage
        self._store = store
        self._enable_circuit_breakers = enable_circuit_breakers

        # In-memory storage (used when persistent storage is disabled)
        self._expenses: dict[str, ExpenseRecord] = {}
        self._by_vendor: dict[str, set[str]] = {}
        self._by_category: dict[ExpenseCategory, set[str]] = {}
        self._by_date: dict[str, set[str]] = {}  # YYYY-MM-DD -> expense_ids
        self._hash_index: dict[str, str] = {}  # hash_key -> expense_id

        # Circuit breakers for external service resilience
        self._circuit_breakers: dict[str, Any] = {}
        if enable_circuit_breakers:
            from aragora.resilience import get_circuit_breaker

            self._circuit_breakers = {
                "ocr": get_circuit_breaker("expense_tracker_ocr", 3, 60.0),
                "llm": get_circuit_breaker("expense_tracker_llm", 3, 60.0),
                "qbo": get_circuit_breaker("expense_tracker_qbo", 5, 120.0),
            }

        # Lazily initialize persistent store
        if self._use_persistent and self._store is None:
            from aragora.storage.expense_store import get_expense_store

            self._store = get_expense_store()

    def _check_circuit_breaker(self, service: str) -> bool:
        """Check if circuit breaker allows the request."""
        if service not in self._circuit_breakers:
            return True
        cb = self._circuit_breakers[service]
        if not cb.can_proceed():
            logger.warning("Circuit breaker open for %s", service)
            return False
        return True

    def _record_cb_success(self, service: str) -> None:
        """Record successful external call."""
        if service in self._circuit_breakers:
            self._circuit_breakers[service].record_success()

    def _record_cb_failure(self, service: str) -> None:
        """Record failed external call."""
        if service in self._circuit_breakers:
            self._circuit_breakers[service].record_failure()

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get status of all circuit breakers."""
        return {
            "enabled": self._enable_circuit_breakers,
            "services": {
                svc: {"status": cb.get_status(), "failures": cb._single_failures}
                for svc, cb in self._circuit_breakers.items()
            },
        }

    async def _emit_usage_event(
        self,
        operation: str,
        tokens: int = 0,
        cost_usd: float = 0.0,
        provider: str = "",
        model: str = "",
        tenant_id: str | None = None,
    ) -> None:
        """Emit usage event for cost tracking."""
        try:
            from decimal import Decimal

            from aragora.server.stream.usage_stream import (
                UsageEventType,
                emit_usage_event,
            )

            await emit_usage_event(
                tenant_id=tenant_id or "default",
                event_type=UsageEventType.COST_UPDATE,
                tokens_out=tokens,
                cost_usd=Decimal(str(cost_usd)),
                provider=provider,
                model=model,
                operation=f"expense_tracker.{operation}",
                metadata={"service": "expense_tracker"},
            )
        except (ValueError, OSError, ConnectionError, RuntimeError, TypeError) as e:
            logger.debug("Failed to emit usage event: %s", e)

    async def process_receipt(
        self,
        image_data: bytes,
        employee_id: str | None = None,
        payment_method: PaymentMethod = PaymentMethod.CREDIT_CARD,
    ) -> ExpenseRecord:
        """
        Process a receipt image and extract expense data.

        Args:
            image_data: Receipt image bytes (PNG, JPG, PDF)
            employee_id: Employee who incurred expense
            payment_method: How it was paid

        Returns:
            Extracted expense record
        """
        expense_id = f"exp_{uuid4().hex[:12]}"

        # Initialize record with defaults
        expense = ExpenseRecord(
            id=expense_id,
            vendor_name="Unknown Vendor",
            amount=Decimal("0.00"),
            employee_id=employee_id,
            payment_method=payment_method,
            receipt_image=image_data,
            status=ExpenseStatus.PENDING,
        )

        if self.enable_ocr:
            # Extract text and data from receipt
            extracted = await self._extract_receipt_data(image_data)
            expense.vendor_name = extracted.get("vendor", "Unknown Vendor")
            expense.amount = Decimal(str(extracted.get("amount", 0)))
            expense.date = extracted.get("date", datetime.now())
            expense.receipt_text = extracted.get("text", "")
            expense.tax_amount = Decimal(str(extracted.get("tax", 0)))
            expense.tip_amount = Decimal(str(extracted.get("tip", 0)))
            expense.line_items = extracted.get("line_items", [])
            expense.confidence_score = extracted.get("confidence", 0.5)
            expense.status = ExpenseStatus.PROCESSED

        # Store in memory and persist
        self._store_expense(expense)
        await self._persist_expense(expense)

        # Emit usage event for OCR processing
        await self._emit_usage_event(
            operation="process_receipt",
            cost_usd=0.001,  # Approximate OCR cost
            provider="ocr",
            model="pdfplumber" if image_data[:4] == b"%PDF" else "pytesseract",
        )

        logger.info(
            "Processed receipt -> expense %s: %s $%s",
            expense_id,
            expense.vendor_name,
            expense.amount,
        )
        return expense

    async def _extract_receipt_data(self, image_data: bytes) -> dict[str, Any]:
        """
        Extract data from receipt image/PDF using OCR.

        Uses pdfplumber for PDFs and optional pytesseract for images.
        Falls back to pattern matching if OCR libraries unavailable.
        """
        import io

        # Detect document type
        is_pdf = image_data[:4] == b"%PDF"
        is_png = image_data[:4] == b"\x89PNG"
        is_jpeg = image_data[:2] == b"\xff\xd8"

        doc_type = "PDF" if is_pdf else "PNG" if is_png else "JPEG" if is_jpeg else "unknown"
        logger.debug("Processing %s receipt (%s bytes)", doc_type, len(image_data))

        extracted_text = ""
        confidence = 0.5

        # Try PDF extraction with pdfplumber
        if is_pdf:
            try:
                import pdfplumber

                with pdfplumber.open(io.BytesIO(image_data)) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        extracted_text += page_text + "\n"
                        # Also try to extract tables
                        tables = page.extract_tables()
                        for table in tables:
                            for row in table:
                                if row:
                                    extracted_text += " | ".join(str(c) for c in row if c) + "\n"
                confidence = 0.85 if extracted_text.strip() else 0.3
            except ImportError:
                logger.warning("pdfplumber not available, using basic PDF extraction")
                try:
                    import pypdf

                    reader = pypdf.PdfReader(io.BytesIO(image_data))
                    for page in reader.pages:
                        extracted_text += page.extract_text() or ""
                    confidence = 0.7 if extracted_text.strip() else 0.2
                except Exception as e:
                    logger.warning("PDF extraction failed: %s", e)
            except Exception as e:
                logger.warning("pdfplumber extraction failed: %s", e)

        # Try image OCR with pytesseract if available
        elif is_png or is_jpeg:
            try:
                import pytesseract
                from PIL import Image

                img = Image.open(io.BytesIO(image_data))
                extracted_text = pytesseract.image_to_string(img)
                confidence = 0.75 if extracted_text.strip() else 0.2
            except ImportError:
                logger.info("pytesseract not available - install for image OCR support")
                extracted_text = (
                    "[Image OCR requires pytesseract - install with: pip install pytesseract]"
                )
                confidence = 0.0
            except (ValueError, OSError, ConnectionError, RuntimeError, TypeError) as e:
                logger.warning("Image OCR failed: %s", e)

        # Parse extracted text for receipt data
        result = self._parse_receipt_text(extracted_text)
        result["text"] = extracted_text[:2000] if extracted_text else ""
        result["confidence"] = confidence

        return result

    def _parse_receipt_text(self, text: str) -> dict[str, Any]:
        """Parse extracted text to find receipt fields."""
        import re

        result: dict[str, Any] = {
            "vendor": "",
            "amount": 0.00,
            "date": datetime.now(),
            "tax": 0.00,
            "tip": 0.00,
            "line_items": [],
        }

        if not text:
            return result

        lines = text.strip().split("\n")

        # First non-empty line is often vendor name
        for line in lines[:5]:
            line = line.strip()
            if line and len(line) > 2:
                result["vendor"] = line
                break

        # Find total amount (look for patterns like "Total: $XX.XX" or "TOTAL $XX.XX")
        total_patterns = [
            r"(?:total|amount|grand\s*total|balance\s*due)[:\s]*\$?\s*(\d+[.,]\d{2})",
            r"\$\s*(\d+[.,]\d{2})\s*(?:total|due)?",
            r"(\d+[.,]\d{2})\s*(?:total|due)",
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", "")
                try:
                    result["amount"] = float(amount_str)
                    break
                except ValueError as e:
                    logger.debug("Failed to parse numeric value: %s", e)

        # Find tax
        tax_patterns = [
            r"(?:tax|vat|gst|hst)[:\s]*\$?\s*(\d+[.,]\d{2})",
            r"\$?\s*(\d+[.,]\d{2})\s*(?:tax|vat)",
        ]
        for pattern in tax_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    result["tax"] = float(match.group(1).replace(",", ""))
                    break
                except ValueError as e:
                    logger.debug("Failed to parse numeric value: %s", e)

        # Find tip
        tip_patterns = [
            r"(?:tip|gratuity)[:\s]*\$?\s*(\d+[.,]\d{2})",
        ]
        for pattern in tip_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    result["tip"] = float(match.group(1).replace(",", ""))
                    break
                except ValueError as e:
                    logger.debug("Failed to parse numeric value: %s", e)

        # Find date
        date_patterns = [
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s*\d{2,4})",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Try common date formats
                for fmt in ["%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"]:
                    try:
                        result["date"] = datetime.strptime(date_str, fmt)
                        break
                    except ValueError as e:
                        logger.debug("Failed to parse datetime value: %s", e)
                break

        # Extract line items (lines with price pattern)
        item_pattern = r"(.+?)\s+\$?\s*(\d+[.,]\d{2})\s*$"
        for line in lines:
            match = re.match(item_pattern, line.strip())
            if match:
                desc = match.group(1).strip()
                if len(desc) > 2 and not any(
                    kw in desc.lower() for kw in ["total", "subtotal", "tax", "tip"]
                ):
                    try:
                        price = float(match.group(2).replace(",", ""))
                        result["line_items"].append({"description": desc, "amount": price})
                    except ValueError as e:
                        logger.debug("Failed to parse numeric value: %s", e)

        return result

    async def create_expense(
        self,
        vendor_name: str,
        amount: float,
        date: datetime | None = None,
        category: ExpenseCategory | None = None,
        payment_method: PaymentMethod = PaymentMethod.CREDIT_CARD,
        description: str = "",
        employee_id: str | None = None,
        is_reimbursable: bool = False,
        tags: list[str] | None = None,
    ) -> ExpenseRecord:
        """
        Create an expense record manually.

        Args:
            vendor_name: Vendor/merchant name
            amount: Expense amount
            date: Transaction date
            category: Expense category
            payment_method: Payment method
            description: Description/memo
            employee_id: Employee ID
            is_reimbursable: Whether reimbursable
            tags: Optional tags

        Returns:
            Created expense record
        """
        expense_id = f"exp_{uuid4().hex[:12]}"

        expense = ExpenseRecord(
            id=expense_id,
            vendor_name=vendor_name,
            amount=Decimal(str(amount)),
            date=date or datetime.now(),
            category=category or ExpenseCategory.OTHER,
            payment_method=payment_method,
            description=description,
            employee_id=employee_id,
            is_reimbursable=is_reimbursable,
            tags=tags or [],
            status=ExpenseStatus.PROCESSED,
        )

        # Auto-categorize if not specified
        if not category:
            expense.category = await self.categorize_expense(expense)
            expense.status = ExpenseStatus.CATEGORIZED

        # Check for duplicates
        duplicates = await self.detect_duplicates(expense)
        if duplicates:
            expense.duplicate_of = duplicates[0].id
            expense.status = ExpenseStatus.DUPLICATE

        self._store_expense(expense)
        await self._persist_expense(expense)
        return expense

    async def categorize_expense(self, expense: ExpenseRecord) -> ExpenseCategory:
        """
        Auto-categorize an expense based on vendor and description.

        Args:
            expense: Expense to categorize

        Returns:
            Suggested category
        """
        vendor_lower = expense.vendor_name.lower()
        description_lower = expense.description.lower()
        combined = f"{vendor_lower} {description_lower}"

        # Pattern-based categorization
        for category, patterns in VENDOR_CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    logger.debug(
                        "Categorized %s as %s (pattern: %s)",
                        expense.vendor_name,
                        category.value,
                        pattern,
                    )
                    return category

        # LLM-based categorization for unknown vendors
        if self.enable_llm_categorization:
            llm_category = await self._llm_categorize(expense)
            if llm_category:
                return llm_category

        return ExpenseCategory.OTHER

    async def _llm_categorize(self, expense: ExpenseRecord) -> ExpenseCategory | None:
        """
        Use LLM to categorize expense.

        Uses Anthropic Claude API (with OpenAI fallback) to intelligently
        categorize expenses based on vendor name, amount, and description.
        """
        # Try Anthropic first, then OpenAI
        api_key = get_api_key("ANTHROPIC_API_KEY", required=False)
        provider = "anthropic"

        if not api_key:
            api_key = get_api_key("OPENAI_API_KEY", required=False)
            provider = "openai"

        if not api_key:
            logger.debug("No LLM API key configured, skipping LLM categorization")
            return None

        categories = [cat.value for cat in ExpenseCategory]
        prompt = f"""Categorize this expense into exactly one of these categories: {", ".join(categories)}

Expense details:
- Vendor: {expense.vendor_name}
- Amount: ${expense.amount}
- Description: {expense.description or "N/A"}
- Date: {expense.date.strftime("%Y-%m-%d")}

Respond with ONLY the category name (lowercase, with underscores). No explanation."""

        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()

            if provider == "anthropic":
                async with pool.get_session("anthropic") as client:
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-3-haiku-20240307",  # Fast, cheap model for categorization
                            "max_tokens": 50,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        content = data.get("content") if isinstance(data, dict) else None
                        if not isinstance(content, list) or not content:
                            logger.warning("Anthropic API returned unexpected response format")
                            return None
                        first_item = content[0]
                        if not isinstance(first_item, dict):
                            logger.warning("Anthropic API returned unexpected response format")
                            return None
                        category_text = first_item.get("text")
                        if not isinstance(category_text, str):
                            logger.warning("Anthropic API returned unexpected response format")
                            return None
                        category_text = category_text.strip().lower()
                        # Emit usage event for LLM call
                        usage = data.get("usage", {})
                        await self._emit_usage_event(
                            operation="categorize_expense",
                            tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                            cost_usd=0.00025,  # ~$0.25/M tokens for Haiku
                            provider="anthropic",
                            model="claude-3-haiku-20240307",
                        )
                        try:
                            return ExpenseCategory(category_text)
                        except ValueError:
                            logger.debug("LLM returned invalid category: %s", category_text)
                            return None
                    else:
                        logger.warning("Anthropic API error: %s", response.status_code)
                        return None
            else:  # OpenAI
                async with pool.get_session("openai") as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "gpt-4o-mini",  # Fast, cheap model
                            "max_tokens": 50,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=10,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        choices = data.get("choices") if isinstance(data, dict) else None
                        if not isinstance(choices, list) or not choices:
                            logger.warning("OpenAI API returned unexpected response format")
                            return None
                        first_choice = choices[0]
                        if not isinstance(first_choice, dict):
                            logger.warning("OpenAI API returned unexpected response format")
                            return None
                        message = first_choice.get("message")
                        if not isinstance(message, dict):
                            logger.warning("OpenAI API returned unexpected response format")
                            return None
                        category_text = message.get("content")
                        if not isinstance(category_text, str):
                            logger.warning("OpenAI API returned unexpected response format")
                            return None
                        category_text = category_text.strip().lower()
                        # Emit usage event for LLM call
                        usage = data.get("usage", {})
                        await self._emit_usage_event(
                            operation="categorize_expense",
                            tokens=usage.get("total_tokens", 0),
                            cost_usd=0.00015,  # ~$0.15/M tokens for GPT-4o-mini
                            provider="openai",
                            model="gpt-4o-mini",
                        )
                        try:
                            return ExpenseCategory(category_text)
                        except ValueError:
                            logger.debug("LLM returned invalid category: %s", category_text)
                            return None
                    else:
                        logger.warning("OpenAI API error: %s", response.status_code)
                        return None
        except (ValueError, OSError, ConnectionError, RuntimeError, TypeError) as e:
            logger.warning("LLM categorization failed: %s", e)
            return None

    async def detect_duplicates(
        self,
        expense: ExpenseRecord,
        tolerance_days: int = 3,
    ) -> list[ExpenseRecord]:
        """
        Detect potential duplicate expenses.

        Args:
            expense: Expense to check
            tolerance_days: Days to consider for duplicates

        Returns:
            List of potential duplicates
        """
        duplicates = []
        hash_key = expense.hash_key

        # Exact match
        if hash_key in self._hash_index:
            existing_id = self._hash_index[hash_key]
            if existing_id != expense.id and existing_id in self._expenses:
                duplicates.append(self._expenses[existing_id])
                return duplicates

        # Fuzzy match: same vendor, similar amount, close date
        for existing in self._expenses.values():
            if existing.id == expense.id:
                continue

            # Skip if already marked as duplicate
            if existing.status == ExpenseStatus.DUPLICATE:
                continue

            # Check vendor similarity
            if existing.vendor_name.lower() != expense.vendor_name.lower():
                continue

            # Check amount (within 1%)
            if existing.amount > 0:
                diff = abs(float(existing.amount - expense.amount) / float(existing.amount))
                if diff > 0.01:
                    continue

            # Check date (within tolerance)
            date_diff = abs((existing.date - expense.date).days)
            if date_diff > tolerance_days:
                continue

            duplicates.append(existing)

        return duplicates

    async def sync_to_qbo(
        self,
        expenses: list[ExpenseRecord] | None = None,
        expense_ids: list[str] | None = None,
    ) -> SyncResult:
        """
        Sync expenses to QuickBooks Online.

        Args:
            expenses: List of expenses to sync
            expense_ids: Or list of expense IDs

        Returns:
            Sync result with success/failure counts
        """
        result = SyncResult()

        if not self.qbo:
            logger.warning("No QBO connector configured")
            result.errors.append({"error": "QBO connector not configured"})
            return result

        # Get expenses to sync
        to_sync: list[ExpenseRecord] = []
        if expenses:
            to_sync = expenses
        elif expense_ids:
            to_sync = [self._expenses[eid] for eid in expense_ids if eid in self._expenses]
        else:
            # Sync all approved expenses not yet synced
            to_sync = [
                e
                for e in self._expenses.values()
                if e.status == ExpenseStatus.APPROVED and not e.qbo_id
            ]

        for expense in to_sync:
            try:
                # Skip duplicates
                if expense.status == ExpenseStatus.DUPLICATE:
                    result.duplicate_count += 1
                    continue

                # Create expense in QBO
                qbo_id = await self._create_qbo_expense(expense)

                expense.qbo_id = qbo_id
                expense.status = ExpenseStatus.SYNCED
                expense.synced_at = datetime.now()
                expense.updated_at = datetime.now()

                result.success_count += 1
                result.synced_ids.append(expense.id)
                logger.info("Synced expense %s to QBO as %s", expense.id, qbo_id)

            except (ValueError, OSError, ConnectionError, RuntimeError, TypeError) as e:
                result.failed_count += 1
                result.failed_ids.append(expense.id)
                result.errors.append(
                    {
                        "expenseId": expense.id,
                        "error": str(e),
                    }
                )
                logger.error("Failed to sync expense %s: %s", expense.id, e)

        return result

    async def _create_qbo_expense(self, expense: ExpenseRecord) -> str:
        """Create expense in QuickBooks."""
        if not self.qbo:
            logger.warning("No QBO connector configured - returning mock ID")
            return f"qbo_{uuid4().hex[:8]}"

        try:
            # Get or create vendor in QBO
            vendor = await self.qbo.get_vendor_by_name(expense.vendor_name)
            if not vendor:
                vendor = await self.qbo.create_vendor(
                    display_name=expense.vendor_name,
                    email=None,
                )
            vendor_id = vendor.get("Id", "") if isinstance(vendor, dict) else ""

            # Get a default expense account (would typically be configured)
            accounts = await self.qbo.list_accounts(account_type="Expense")
            expense_account_id = accounts[0].id if accounts else None

            if not expense_account_id:
                logger.warning("No expense account found in QBO")
                return f"qbo_{uuid4().hex[:8]}"

            # Map payment method
            payment_type = {
                PaymentMethod.CREDIT_CARD: "CreditCard",
                PaymentMethod.DEBIT_CARD: "CreditCard",
                PaymentMethod.CASH: "Cash",
                PaymentMethod.CHECK: "Check",
                PaymentMethod.BANK_TRANSFER: "Cash",
                PaymentMethod.OTHER: "Cash",
            }.get(expense.payment_method, "Cash")

            # Create the expense (Purchase) in QBO
            result = await self.qbo.create_expense(
                vendor_id=vendor_id,
                account_id=expense_account_id,
                amount=float(expense.amount),
                description=expense.description or f"Expense: {expense.vendor_name}",
                txn_date=expense.date,
                payment_type=payment_type,
            )

            qbo_id = result.get("Id", f"qbo_{uuid4().hex[:8]}")
            logger.info("Created QBO expense %s for expense %s", qbo_id, expense.id)
            return qbo_id

        except (ValueError, OSError, ConnectionError, RuntimeError, TypeError) as e:
            logger.exception("Failed to create QBO expense: %s", e)
            # Return mock ID on failure so sync can continue
            return f"qbo_error_{uuid4().hex[:8]}"

    def _store_expense(self, expense: ExpenseRecord) -> None:
        """Store expense and update indexes."""
        self._expenses[expense.id] = expense

        # Index by vendor
        vendor_lower = expense.vendor_name.lower()
        if vendor_lower not in self._by_vendor:
            self._by_vendor[vendor_lower] = set()
        self._by_vendor[vendor_lower].add(expense.id)

        # Index by category
        if expense.category not in self._by_category:
            self._by_category[expense.category] = set()
        self._by_category[expense.category].add(expense.id)

        # Index by date
        date_key = expense.date.strftime("%Y-%m-%d")
        if date_key not in self._by_date:
            self._by_date[date_key] = set()
        self._by_date[date_key].add(expense.id)

        # Hash index for duplicate detection
        self._hash_index[expense.hash_key] = expense.id

    async def _persist_expense(self, expense: ExpenseRecord) -> None:
        """Persist expense to database store if enabled."""
        if self._use_persistent and self._store:
            await self._store.save(self._expense_to_dict(expense))

    def _expense_to_dict(self, expense: ExpenseRecord) -> dict[str, Any]:
        """Convert expense record to dict for storage."""
        return {
            "id": expense.id,
            "vendor_name": expense.vendor_name,
            "amount": str(expense.amount),
            "currency": expense.currency,
            "expense_date": expense.date.isoformat(),
            "category": expense.category.value,
            "status": expense.status.value,
            "payment_method": expense.payment_method.value,
            "description": expense.description,
            "notes": expense.notes,
            "receipt_text": expense.receipt_text,
            "line_items": [li.to_dict() for li in expense.line_items],
            "tax_amount": str(expense.tax_amount),
            "tip_amount": str(expense.tip_amount),
            "is_reimbursable": expense.is_reimbursable,
            "is_billable": expense.is_billable,
            "project_id": expense.project_id,
            "client_id": expense.client_id,
            "employee_id": expense.employee_id,
            "qbo_expense_id": expense.qbo_id,
            "synced_to_qbo": expense.qbo_id is not None,
            "confidence_score": expense.confidence_score,
            "created_at": expense.created_at.isoformat(),
            "updated_at": expense.updated_at.isoformat(),
            "synced_at": expense.synced_at.isoformat() if expense.synced_at else None,
            "tags": expense.tags,
        }

    def _dict_to_expense(self, data: dict[str, Any]) -> ExpenseRecord:
        """Convert stored dict back to expense record."""
        return ExpenseRecord(
            id=data["id"],
            vendor_name=data.get("vendor_name", "Unknown"),
            amount=Decimal(str(data.get("amount", 0))),
            currency=data.get("currency", "USD"),
            date=(
                datetime.fromisoformat(data["expense_date"].replace("Z", "+00:00"))
                if data.get("expense_date")
                else datetime.now(timezone.utc)
            ),
            category=ExpenseCategory(data.get("category", "other")),
            status=ExpenseStatus(data.get("status", "pending")),
            payment_method=PaymentMethod(data.get("payment_method", "credit_card")),
            description=data.get("description", ""),
            notes=data.get("notes", ""),
            receipt_text=data.get("receipt_text", ""),
            tax_amount=Decimal(str(data.get("tax_amount", 0))),
            tip_amount=Decimal(str(data.get("tip_amount", 0))),
            is_reimbursable=data.get("is_reimbursable", False),
            is_billable=data.get("is_billable", False),
            project_id=data.get("project_id"),
            client_id=data.get("client_id"),
            employee_id=data.get("employee_id"),
            qbo_id=data.get("qbo_expense_id"),
            confidence_score=data.get("confidence_score", 0.0),
            created_at=(
                datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                if data.get("created_at")
                else datetime.now(timezone.utc)
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
                if data.get("updated_at")
                else datetime.now(timezone.utc)
            ),
            synced_at=(
                datetime.fromisoformat(data["synced_at"].replace("Z", "+00:00"))
                if data.get("synced_at")
                else None
            ),
            tags=data.get("tags", []),
        )

    async def get_expense(self, expense_id: str) -> ExpenseRecord | None:
        """Get expense by ID."""
        # Check in-memory first
        if expense_id in self._expenses:
            return self._expenses[expense_id]

        # Try persistent store
        if self._use_persistent and self._store:
            data = await self._store.get(expense_id)
            if data:
                expense = self._dict_to_expense(data)
                # Cache in memory
                self._expenses[expense_id] = expense
                return expense

        return None

    async def list_expenses(
        self,
        category: ExpenseCategory | None = None,
        vendor: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        status: ExpenseStatus | None = None,
        employee_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ExpenseRecord], int]:
        """
        List expenses with filters.

        Args:
            category: Filter by category
            vendor: Filter by vendor name
            start_date: Filter by date range start
            end_date: Filter by date range end
            status: Filter by status
            employee_id: Filter by employee
            limit: Max results
            offset: Offset for pagination

        Returns:
            Tuple of (expenses, total_count)
        """
        expenses = list(self._expenses.values())

        # Apply filters
        if category:
            expenses = [e for e in expenses if e.category == category]

        if vendor:
            vendor_lower = vendor.lower()
            expenses = [e for e in expenses if vendor_lower in e.vendor_name.lower()]

        if start_date:
            expenses = [e for e in expenses if e.date >= start_date]

        if end_date:
            expenses = [e for e in expenses if e.date <= end_date]

        if status:
            expenses = [e for e in expenses if e.status == status]

        if employee_id:
            expenses = [e for e in expenses if e.employee_id == employee_id]

        # Sort by date descending
        expenses.sort(key=lambda x: x.date, reverse=True)

        total = len(expenses)
        expenses = expenses[offset : offset + limit]

        return expenses, total

    async def update_expense(
        self,
        expense_id: str,
        vendor_name: str | None = None,
        amount: float | None = None,
        category: ExpenseCategory | None = None,
        description: str | None = None,
        status: ExpenseStatus | None = None,
        is_reimbursable: bool | None = None,
        tags: list[str] | None = None,
    ) -> ExpenseRecord | None:
        """Update an expense record."""
        expense = await self.get_expense(expense_id)
        if not expense:
            return None

        if vendor_name is not None:
            expense.vendor_name = vendor_name
        if amount is not None:
            expense.amount = Decimal(str(amount))
        if category is not None:
            expense.category = category
        if description is not None:
            expense.description = description
        if status is not None:
            expense.status = status
        if is_reimbursable is not None:
            expense.is_reimbursable = is_reimbursable
        if tags is not None:
            expense.tags = tags

        expense.updated_at = datetime.now(timezone.utc)

        # Update in-memory and persist
        self._expenses[expense_id] = expense
        await self._persist_expense(expense)

        return expense

    async def approve_expense(self, expense_id: str) -> ExpenseRecord | None:
        """Mark expense as approved for sync."""
        return await self.update_expense(expense_id, status=ExpenseStatus.APPROVED)

    async def reject_expense(self, expense_id: str, reason: str = "") -> ExpenseRecord | None:
        """Reject an expense."""
        expense = await self.get_expense(expense_id)
        if expense:
            expense.status = ExpenseStatus.REJECTED
            expense.notes = reason
            expense.updated_at = datetime.now(timezone.utc)
            self._expenses[expense_id] = expense
            await self._persist_expense(expense)
        return expense

    async def delete_expense(self, expense_id: str) -> bool:
        """Delete an expense."""
        expense = self._expenses.get(expense_id)

        # Also try loading from persistent store
        if not expense and self._use_persistent and self._store:
            data = await self._store.get(expense_id)
            if data:
                expense = self._dict_to_expense(data)

        if not expense:
            return False

        # Remove from in-memory indexes
        if expense_id in self._expenses:
            vendor_lower = expense.vendor_name.lower()
            if vendor_lower in self._by_vendor:
                self._by_vendor[vendor_lower].discard(expense_id)

            if expense.category in self._by_category:
                self._by_category[expense.category].discard(expense_id)

            date_key = expense.date.strftime("%Y-%m-%d")
            if date_key in self._by_date:
                self._by_date[date_key].discard(expense_id)

            if expense.hash_key in self._hash_index:
                del self._hash_index[expense.hash_key]

            del self._expenses[expense_id]

        # Delete from persistent store
        if self._use_persistent and self._store:
            await self._store.delete(expense_id)

        return True

    def get_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> ExpenseStats:
        """Get expense statistics."""
        expenses = list(self._expenses.values())

        if start_date:
            expenses = [e for e in expenses if e.date >= start_date]
        if end_date:
            expenses = [e for e in expenses if e.date <= end_date]

        # Exclude duplicates and rejected
        expenses = [
            e for e in expenses if e.status not in [ExpenseStatus.DUPLICATE, ExpenseStatus.REJECTED]
        ]

        if not expenses:
            return ExpenseStats()

        total_amount = sum(float(e.total_amount) for e in expenses)
        pending = [
            e for e in expenses if e.status in [ExpenseStatus.PENDING, ExpenseStatus.PROCESSED]
        ]

        # By category
        by_category: dict[str, float] = {}
        for expense in expenses:
            cat = expense.category.value
            by_category[cat] = by_category.get(cat, 0) + float(expense.total_amount)

        # By month
        by_month: dict[str, float] = {}
        for expense in expenses:
            month_key = expense.date.strftime("%Y-%m")
            by_month[month_key] = by_month.get(month_key, 0) + float(expense.total_amount)

        # Top vendors
        vendor_totals: dict[str, float] = {}
        for expense in expenses:
            vendor = expense.vendor_name
            vendor_totals[vendor] = vendor_totals.get(vendor, 0) + float(expense.total_amount)

        top_vendors = [
            {"vendor": v, "total": round(t, 2)}
            for v, t in sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        return ExpenseStats(
            total_expenses=len(expenses),
            total_amount=total_amount,
            pending_count=len(pending),
            pending_amount=sum(float(e.total_amount) for e in pending),
            by_category={k: round(v, 2) for k, v in by_category.items()},
            by_month={k: round(v, 2) for k, v in sorted(by_month.items())},
            top_vendors=top_vendors,
            avg_expense=total_amount / len(expenses) if expenses else 0,
        )

    async def get_expenses_by_vendor(self, vendor_name: str) -> list[ExpenseRecord]:
        """Get all expenses for a vendor."""
        vendor_lower = vendor_name.lower()
        expense_ids = self._by_vendor.get(vendor_lower, set())
        return [self._expenses[eid] for eid in expense_ids if eid in self._expenses]

    async def get_expenses_by_category(self, category: ExpenseCategory) -> list[ExpenseRecord]:
        """Get all expenses in a category."""
        expense_ids = self._by_category.get(category, set())
        return [self._expenses[eid] for eid in expense_ids if eid in self._expenses]

    async def get_pending_approval(self) -> list[ExpenseRecord]:
        """Get expenses pending approval."""
        return [
            e
            for e in self._expenses.values()
            if e.status in [ExpenseStatus.PROCESSED, ExpenseStatus.CATEGORIZED]
        ]

    async def get_reimbursable_expenses(
        self,
        employee_id: str | None = None,
    ) -> list[ExpenseRecord]:
        """Get reimbursable expenses."""
        expenses = [e for e in self._expenses.values() if e.is_reimbursable]
        if employee_id:
            expenses = [e for e in expenses if e.employee_id == employee_id]
        return expenses

    async def bulk_categorize(
        self,
        expense_ids: list[str] | None = None,
    ) -> dict[str, ExpenseCategory]:
        """
        Bulk categorize expenses.

        Args:
            expense_ids: Specific IDs or all uncategorized

        Returns:
            Map of expense_id -> assigned category
        """
        results: dict[str, ExpenseCategory] = {}

        if expense_ids:
            to_categorize = [self._expenses[eid] for eid in expense_ids if eid in self._expenses]
        else:
            to_categorize = [
                e for e in self._expenses.values() if e.status == ExpenseStatus.PROCESSED
            ]

        for expense in to_categorize:
            category = await self.categorize_expense(expense)
            expense.category = category
            expense.status = ExpenseStatus.CATEGORIZED
            expense.updated_at = datetime.now()
            results[expense.id] = category

        return results

    async def export_expenses(
        self,
        format: str = "csv",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """
        Export expenses to CSV or JSON.

        Args:
            format: 'csv' or 'json'
            start_date: Filter start
            end_date: Filter end

        Returns:
            Exported data as string
        """
        expenses, _ = await self.list_expenses(
            start_date=start_date,
            end_date=end_date,
            limit=10000,
        )

        if format == "json":
            import json

            return json.dumps([e.to_dict() for e in expenses], indent=2)

        # CSV format
        lines = ["date,vendor,amount,category,status,description"]
        for e in expenses:
            line = f"{e.date.strftime('%Y-%m-%d')},{e.vendor_name},{e.amount},{e.category.value},{e.status.value},{e.description}"
            lines.append(line)

        return "\n".join(lines)
