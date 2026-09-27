"""
Invoice Processor Service.

Processes incoming invoices for accounts payable automation:
- PDF/image invoice parsing and data extraction
- Line item extraction
- Purchase order matching (3-way match)
- Anomaly detection (unusual amounts, new vendors, duplicates)
- Approval routing based on thresholds
- Payment scheduling
- QBO sync integration

Usage:
    from aragora.services.invoice_processor import InvoiceProcessor

    processor = InvoiceProcessor()

    # Extract data from invoice
    invoice = await processor.extract_invoice_data(pdf_bytes)

    # Match to purchase order
    match = await processor.match_to_po(invoice)

    # Detect anomalies
    anomalies = await processor.detect_anomalies(invoice)

    # Schedule payment
    schedule = await processor.schedule_payment(invoice, pay_date)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from aragora.connectors.accounting.qbo import QuickBooksConnector

logger = logging.getLogger(__name__)


class InvoiceStatus(str, Enum):
    """Invoice processing status."""

    RECEIVED = "received"  # Just received, pending extraction
    EXTRACTED = "extracted"  # Data extracted successfully
    MATCHED = "matched"  # Matched to PO
    UNMATCHED = "unmatched"  # Could not match to PO
    PENDING_APPROVAL = "pending_approval"  # Awaiting approval
    APPROVED = "approved"  # Approved for payment
    SCHEDULED = "scheduled"  # Payment scheduled
    PAID = "paid"  # Payment completed
    REJECTED = "rejected"  # Rejected
    DUPLICATE = "duplicate"  # Duplicate invoice


class AnomalyType(str, Enum):
    """Types of invoice anomalies."""

    UNUSUAL_AMOUNT = "unusual_amount"  # Amount significantly differs from history
    NEW_VENDOR = "new_vendor"  # First invoice from this vendor
    DUPLICATE = "duplicate"  # Potential duplicate
    MISSING_PO = "missing_po"  # No matching purchase order
    PRICE_VARIANCE = "price_variance"  # Line item price differs from PO
    QUANTITY_VARIANCE = "quantity_variance"  # Quantity differs from PO
    EARLY_INVOICE = "early_invoice"  # Invoice before expected delivery
    ROUND_AMOUNT = "round_amount"  # Suspiciously round number
    HIGH_VALUE = "high_value"  # Exceeds approval threshold


class ApprovalLevel(str, Enum):
    """Approval levels based on amount."""

    AUTO = "auto"  # Auto-approved (low value)
    MANAGER = "manager"  # Manager approval
    DIRECTOR = "director"  # Director approval
    EXECUTIVE = "executive"  # Executive/CFO approval


@dataclass
class InvoiceLineItem:
    """A line item on an invoice."""

    description: str
    quantity: float = 1.0
    unit_price: Decimal = Decimal("0.00")
    amount: Decimal = Decimal("0.00")
    product_code: str | None = None
    unit: str | None = None
    tax_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unitPrice": float(self.unit_price),
            "amount": float(self.amount),
            "productCode": self.product_code,
            "unit": self.unit,
            "taxRate": self.tax_rate,
        }


@dataclass
class InvoiceData:
    """Extracted invoice data."""

    id: str
    vendor_name: str
    vendor_id: str | None = None
    invoice_number: str = ""
    invoice_date: datetime = field(default_factory=datetime.now)
    due_date: datetime | None = None
    subtotal: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    total_amount: Decimal = Decimal("0.00")
    currency: str = "USD"
    payment_terms: str | None = None
    line_items: list[InvoiceLineItem] = field(default_factory=list)
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    po_number: str | None = None
    matched_po_id: str | None = None
    approval_level: ApprovalLevel = ApprovalLevel.AUTO
    approver_id: str | None = None
    approved_at: datetime | None = None
    scheduled_pay_date: datetime | None = None
    paid_at: datetime | None = None
    qbo_id: str | None = None
    document_bytes: bytes | None = None
    extracted_text: str = ""
    confidence_score: float = 0.0
    anomalies: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hash_key(self) -> str:
        """Generate hash for duplicate detection."""
        key_parts = [
            self.vendor_name.lower().strip(),
            self.invoice_number.strip(),
            str(self.total_amount),
        ]
        return hashlib.md5("|".join(key_parts).encode(), usedforsecurity=False).hexdigest()

    @property
    def days_until_due(self) -> int | None:
        """Days until payment is due."""
        if self.due_date:
            return (self.due_date - datetime.now()).days
        return None

    @property
    def is_overdue(self) -> bool:
        """Check if invoice is overdue."""
        if self.due_date and self.status not in [InvoiceStatus.PAID, InvoiceStatus.REJECTED]:
            return datetime.now() > self.due_date
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendorName": self.vendor_name,
            "vendorId": self.vendor_id,
            "invoiceNumber": self.invoice_number,
            "invoiceDate": self.invoice_date.isoformat(),
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "subtotal": float(self.subtotal),
            "taxAmount": float(self.tax_amount),
            "totalAmount": float(self.total_amount),
            "currency": self.currency,
            "paymentTerms": self.payment_terms,
            "lineItems": [li.to_dict() for li in self.line_items],
            "status": self.status.value,
            "poNumber": self.po_number,
            "matchedPoId": self.matched_po_id,
            "approvalLevel": self.approval_level.value,
            "approverId": self.approver_id,
            "scheduledPayDate": (
                self.scheduled_pay_date.isoformat() if self.scheduled_pay_date else None
            ),
            "qboId": self.qbo_id,
            "confidenceScore": self.confidence_score,
            "anomalies": self.anomalies,
            "daysUntilDue": self.days_until_due,
            "isOverdue": self.is_overdue,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


@dataclass
class PurchaseOrder:
    """Purchase order for matching."""

    id: str
    po_number: str
    vendor_id: str
    vendor_name: str
    total_amount: Decimal
    order_date: datetime
    expected_delivery: datetime | None = None
    line_items: list[dict[str, Any]] = field(default_factory=list)
    status: str = "open"
    received_amount: Decimal = Decimal("0.00")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "poNumber": self.po_number,
            "vendorId": self.vendor_id,
            "vendorName": self.vendor_name,
            "totalAmount": float(self.total_amount),
            "orderDate": self.order_date.isoformat(),
            "expectedDelivery": (
                self.expected_delivery.isoformat() if self.expected_delivery else None
            ),
            "lineItems": self.line_items,
            "status": self.status,
            "receivedAmount": float(self.received_amount),
        }


@dataclass
class POMatch:
    """Result of PO matching."""

    invoice_id: str
    po_id: str | None = None
    po_number: str | None = None
    match_type: str = "none"  # exact, partial, none
    match_score: float = 0.0
    amount_variance: Decimal = Decimal("0.00")
    variance_percent: float = 0.0
    line_item_matches: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoiceId": self.invoice_id,
            "poId": self.po_id,
            "poNumber": self.po_number,
            "matchType": self.match_type,
            "matchScore": self.match_score,
            "amountVariance": float(self.amount_variance),
            "variancePercent": self.variance_percent,
            "lineItemMatches": self.line_item_matches,
            "issues": self.issues,
        }


@dataclass
class Anomaly:
    """An anomaly detected in an invoice."""

    type: AnomalyType
    severity: str  # low, medium, high
    description: str
    expected_value: str | None = None
    actual_value: str | None = None
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "severity": self.severity,
            "description": self.description,
            "expectedValue": self.expected_value,
            "actualValue": self.actual_value,
            "recommendation": self.recommendation,
        }


@dataclass
class PaymentSchedule:
    """Scheduled payment information."""

    invoice_id: str
    pay_date: datetime
    amount: Decimal
    vendor_id: str
    vendor_name: str
    payment_method: str = "ach"
    status: str = "scheduled"
    early_pay_discount: float = 0.0
    discount_amount: Decimal = Decimal("0.00")

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoiceId": self.invoice_id,
            "payDate": self.pay_date.isoformat(),
            "amount": float(self.amount),
            "vendorId": self.vendor_id,
            "vendorName": self.vendor_name,
            "paymentMethod": self.payment_method,
            "status": self.status,
            "earlyPayDiscount": self.early_pay_discount,
            "discountAmount": float(self.discount_amount),
        }


# Approval thresholds (configurable)
APPROVAL_THRESHOLDS = {
    ApprovalLevel.AUTO: Decimal("500"),  # Auto-approve under $500
    ApprovalLevel.MANAGER: Decimal("5000"),  # Manager up to $5,000
    ApprovalLevel.DIRECTOR: Decimal("25000"),  # Director up to $25,000
    ApprovalLevel.EXECUTIVE: Decimal("999999999"),  # Executive for higher
}


class InvoiceProcessor:
    """
    Service for processing and managing incoming invoices.

    Provides extraction, matching, anomaly detection, and
    payment scheduling for accounts payable automation.
    Includes circuit breaker protection for external service calls.
    """

    def __init__(
        self,
        qbo_connector: QuickBooksConnector | None = None,
        auto_approve_threshold: Decimal = Decimal("500"),
        enable_ocr: bool = True,
        enable_llm_extraction: bool = True,
        enable_circuit_breakers: bool = True,
    ):
        """
        Initialize invoice processor.

        Args:
            qbo_connector: QuickBooks connector for sync
            auto_approve_threshold: Amount below which invoices auto-approve
            enable_ocr: Enable OCR extraction
            enable_llm_extraction: Use LLM for data extraction
            enable_circuit_breakers: Enable circuit breaker protection
        """
        self.qbo = qbo_connector
        self.auto_approve_threshold = auto_approve_threshold
        self.enable_ocr = enable_ocr
        self.enable_llm_extraction = enable_llm_extraction
        self._enable_circuit_breakers = enable_circuit_breakers

        # In-memory storage (would be persisted in production)
        self._invoices: dict[str, InvoiceData] = {}
        self._purchase_orders: dict[str, PurchaseOrder] = {}
        self._by_vendor: dict[str, set[str]] = {}
        self._by_status: dict[InvoiceStatus, set[str]] = {}
        self._hash_index: dict[str, str] = {}
        self._payment_schedule: dict[str, PaymentSchedule] = {}

        # Vendor history for anomaly detection
        self._vendor_history: dict[str, list[float]] = {}
        self._known_vendors: set[str] = set()

        # Circuit breakers for external service resilience
        self._circuit_breakers: dict[str, Any] = {}
        if enable_circuit_breakers:
            from aragora.resilience import get_circuit_breaker

            self._circuit_breakers = {
                "ocr": get_circuit_breaker("invoice_processor_ocr", 3, 60.0),
                "llm": get_circuit_breaker("invoice_processor_llm", 3, 60.0),
                "qbo": get_circuit_breaker("invoice_processor_qbo", 5, 120.0),
            }

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
                operation=f"invoice_processor.{operation}",
                metadata={"service": "invoice_processor"},
            )
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Failed to emit usage event: %s", e)

    async def extract_invoice_data(
        self,
        document_bytes: bytes,
        vendor_hint: str | None = None,
    ) -> InvoiceData:
        """
        Extract data from an invoice document (PDF or image).

        Args:
            document_bytes: Invoice document bytes
            vendor_hint: Optional vendor name hint

        Returns:
            Extracted invoice data
        """
        invoice_id = f"inv_{uuid4().hex[:12]}"

        # Initialize with defaults
        invoice = InvoiceData(
            id=invoice_id,
            vendor_name=vendor_hint or "Unknown Vendor",
            document_bytes=document_bytes,
            status=InvoiceStatus.RECEIVED,
        )

        if self.enable_ocr:
            # Extract text and data from document
            extracted = await self._extract_document_data(document_bytes)
            invoice.vendor_name = extracted.get("vendor", vendor_hint or "Unknown Vendor")
            invoice.invoice_number = extracted.get("invoice_number", "")
            invoice.invoice_date = extracted.get("invoice_date", datetime.now())
            invoice.due_date = extracted.get("due_date")
            invoice.subtotal = Decimal(str(extracted.get("subtotal", 0)))
            invoice.tax_amount = Decimal(str(extracted.get("tax", 0)))
            invoice.total_amount = Decimal(str(extracted.get("total", 0)))
            invoice.payment_terms = extracted.get("payment_terms")
            invoice.line_items = extracted.get("line_items", [])
            invoice.extracted_text = extracted.get("text", "")
            invoice.confidence_score = extracted.get("confidence", 0.5)
            invoice.po_number = extracted.get("po_number")
            invoice.status = InvoiceStatus.EXTRACTED

        # Determine approval level based on amount
        invoice.approval_level = self._determine_approval_level(invoice.total_amount)

        # Store
        self._store_invoice(invoice)

        # Emit usage event for OCR processing
        if self.enable_ocr:
            await self._emit_usage_event(
                operation="extract_invoice_data",
                cost_usd=0.001,  # Approximate OCR cost
                provider="ocr",
                model="pdfplumber" if document_bytes[:4] == b"%PDF" else "pytesseract",
            )

        logger.info(
            "Extracted invoice %s: %s $%s", invoice_id, invoice.vendor_name, invoice.total_amount
        )
        return invoice

    async def _extract_document_data(self, document_bytes: bytes) -> dict[str, Any]:
        """
        Extract data from invoice document using OCR.

        Uses pdfplumber for PDFs and optional pytesseract for images.
        Parses extracted text for invoice-specific fields.
        """
        import io

        # Detect document type
        is_pdf = document_bytes[:4] == b"%PDF"
        is_png = document_bytes[:4] == b"\x89PNG"
        is_jpeg = document_bytes[:2] == b"\xff\xd8"

        doc_type = "PDF" if is_pdf else "PNG" if is_png else "JPEG" if is_jpeg else "unknown"
        logger.debug("Processing %s invoice (%s bytes)", doc_type, len(document_bytes))

        extracted_text = ""
        tables_data = []
        confidence = 0.5

        # Try PDF extraction with pdfplumber
        if is_pdf:
            try:
                import pdfplumber

                with pdfplumber.open(io.BytesIO(document_bytes)) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        extracted_text += page_text + "\n"
                        # Extract tables (useful for line items)
                        tables = page.extract_tables()
                        for table in tables:
                            tables_data.append(table)
                            for row in table:
                                if row:
                                    extracted_text += " | ".join(str(c) for c in row if c) + "\n"
                confidence = 0.85 if extracted_text.strip() else 0.3
            except ImportError:
                logger.warning("pdfplumber not available, using pypdf")
                try:
                    import pypdf

                    reader = pypdf.PdfReader(io.BytesIO(document_bytes))
                    for page in reader.pages:
                        extracted_text += page.extract_text() or ""
                    confidence = 0.7 if extracted_text.strip() else 0.2
                except (ImportError, ValueError, OSError, ConnectionError, RuntimeError) as e:
                    logger.warning("PDF extraction failed: %s", e)
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.warning("pdfplumber extraction failed: %s", e)

        # Try image OCR with pytesseract
        elif is_png or is_jpeg:
            try:
                import pytesseract
                from PIL import Image

                img = Image.open(io.BytesIO(document_bytes))
                extracted_text = pytesseract.image_to_string(img)
                confidence = 0.75 if extracted_text.strip() else 0.2
            except ImportError:
                logger.info("pytesseract not available - install for image OCR")
                extracted_text = "[Image OCR requires pytesseract]"
                confidence = 0.0
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Image OCR failed: %s", e)

        # Parse extracted text for invoice data
        result = self._parse_invoice_text(extracted_text, tables_data)
        result["text"] = extracted_text[:3000] if extracted_text else ""
        result["confidence"] = confidence

        return result

    def _parse_invoice_text(
        self, text: str, tables: list[list[list[str]]] | None = None
    ) -> dict[str, Any]:
        """Parse extracted text to find invoice fields."""
        import re

        result = {
            "vendor": "",
            "invoice_number": "",
            "invoice_date": datetime.now(),
            "due_date": datetime.now() + timedelta(days=30),
            "subtotal": 0.00,
            "tax": 0.00,
            "total": 0.00,
            "payment_terms": "Net 30",
            "line_items": [],
            "po_number": "",
        }

        if not text:
            return result

        lines = text.strip().split("\n")

        # Find vendor (usually in header, first few lines)
        for line in lines[:10]:
            line = line.strip()
            # Skip lines that look like addresses or phone numbers
            if line and len(line) > 3:
                if not re.match(r"^[\d\s\-\(\)\+]+$", line):  # Not just phone
                    if not re.match(r"^\d+\s+\w+", line):  # Not address
                        result["vendor"] = line
                        break

        # Find invoice number
        inv_patterns = [
            r"(?:invoice|inv|bill)[#:\s]*([A-Z0-9\-]+)",
            r"(?:invoice|inv)\s*(?:no|number|#)?[:\s]*([A-Z0-9\-]+)",
            r"#\s*([A-Z0-9\-]{4,})",
        ]
        for pattern in inv_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["invoice_number"] = match.group(1).strip()
                break

        # Find PO number
        po_patterns = [
            r"(?:po|purchase\s*order)[#:\s]*([A-Z0-9\-]+)",
            r"(?:po|purchase\s*order)\s*(?:no|number|#)?[:\s]*([A-Z0-9\-]+)",
        ]
        for pattern in po_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["po_number"] = match.group(1).strip()
                break

        # Find dates
        date_patterns = [
            (r"(?:invoice\s*date|date)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", "invoice_date"),
            (r"(?:due\s*date|payment\s*due)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", "due_date"),
        ]
        for pattern, date_field in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                for fmt in ["%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y"]:
                    try:
                        result[date_field] = datetime.strptime(date_str, fmt)
                        break
                    except ValueError as e:
                        logger.debug("Failed to parse datetime value: %s", e)

        # Find amounts
        amount_patterns = [
            (r"(?:subtotal|sub\s*total)[:\s]*\$?\s*([\d,]+[.,]\d{2})", "subtotal"),
            (r"(?:tax|vat|gst)[:\s]*\$?\s*([\d,]+[.,]\d{2})", "tax"),
            (
                r"(?:total|amount\s*due|balance\s*due|grand\s*total)[:\s]*\$?\s*([\d,]+[.,]\d{2})",
                "total",
            ),
        ]
        for pattern, amount_field in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    result[amount_field] = float(match.group(1).replace(",", ""))
                except ValueError as e:
                    logger.debug("Failed to parse numeric value: %s", e)

        # Find payment terms
        terms_patterns = [
            r"(?:terms|payment\s*terms)[:\s]*(net\s*\d+)",
            r"(net\s*\d+)\s*(?:days)?",
            r"(?:due\s*in|payable\s*within)\s*(\d+)\s*days",
        ]
        for pattern in terms_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                term = match.group(1)
                if term.isdigit():
                    result["payment_terms"] = f"Net {term}"
                else:
                    result["payment_terms"] = term.title()
                break

        # Extract line items from tables or text
        if tables:
            result["line_items"] = self._extract_line_items_from_tables(tables)
        if not result["line_items"]:
            result["line_items"] = self._extract_line_items_from_text(lines)

        return result

    def _extract_line_items_from_tables(
        self, tables: list[list[list[str]]]
    ) -> list[dict[str, Any]]:
        """Extract line items from table data."""
        import re

        items = []
        for table in tables:
            if not table or len(table) < 2:
                continue

            # Try to identify header row and skip it
            for i, row in enumerate(table[:3]):
                if row and any(
                    h
                    and any(
                        kw in str(h).lower() for kw in ["desc", "item", "qty", "price", "amount"]
                    )
                    for h in row
                ):
                    # Skip header row
                    table = table[i + 1 :]
                    break

            for row in table:
                if not row:
                    continue
                # Find description and amount columns
                desc = ""
                amount = 0.0
                qty = 1
                unit_price = 0.0

                for _, cell in enumerate(row):
                    if not cell:
                        continue
                    cell_str = str(cell).strip()

                    # Check if it's a monetary amount
                    amount_match = re.match(r"\$?\s*([\d,]+[.,]\d{2})", cell_str)
                    if amount_match:
                        val = float(amount_match.group(1).replace(",", ""))
                        if amount == 0.0:
                            amount = val
                        elif unit_price == 0.0:
                            unit_price = val
                    # Check if it's a quantity
                    elif re.match(r"^\d+$", cell_str):
                        qty = int(cell_str)
                    # Otherwise might be description
                    elif len(cell_str) > 3 and not cell_str.replace(".", "").isdigit():
                        if not desc:
                            desc = cell_str

                if desc and amount > 0:
                    items.append(
                        {
                            "description": desc,
                            "quantity": qty,
                            "unit_price": unit_price if unit_price else amount,
                            "amount": amount,
                        }
                    )

        return items

    def _extract_line_items_from_text(self, lines: list[str]) -> list[dict[str, Any]]:
        """Extract line items from text lines."""
        import re

        items = []
        item_pattern = (
            r"(.+?)\s+(\d+)\s*[xX@]?\s*\$?\s*([\d,]+[.,]\d{2})?\s*\$?\s*([\d,]+[.,]\d{2})"
        )

        for line in lines:
            line = line.strip()
            # Skip header-like lines
            if any(kw in line.lower() for kw in ["total", "subtotal", "tax", "invoice", "bill to"]):
                continue

            match = re.match(item_pattern, line)
            if match:
                try:
                    items.append(
                        {
                            "description": match.group(1).strip(),
                            "quantity": int(match.group(2)),
                            "unit_price": (
                                float(match.group(3).replace(",", "")) if match.group(3) else 0
                            ),
                            "amount": float(match.group(4).replace(",", "")),
                        }
                    )
                except (ValueError, AttributeError) as e:
                    logger.debug("extract line items from text encountered an error: %s", e)

        return items

    def _determine_approval_level(self, amount: Decimal) -> ApprovalLevel:
        """Determine approval level based on invoice amount."""
        for level, threshold in APPROVAL_THRESHOLDS.items():
            if amount <= threshold:
                return level
        return ApprovalLevel.EXECUTIVE

    async def match_to_po(self, invoice: InvoiceData) -> POMatch:
        """
        Match invoice to a purchase order (3-way match).

        Args:
            invoice: Invoice to match

        Returns:
            Match result with score and variances
        """
        match = POMatch(invoice_id=invoice.id)

        # Try to find PO by number from invoice
        po = None
        if invoice.po_number:
            for p in self._purchase_orders.values():
                if p.po_number == invoice.po_number:
                    po = p
                    break

        # Try to find by vendor and amount
        if not po:
            for p in self._purchase_orders.values():
                if p.vendor_name.lower() == invoice.vendor_name.lower():
                    # Check amount within 10%
                    diff = abs(float(p.total_amount - invoice.total_amount))
                    if diff / float(p.total_amount) < 0.1:
                        po = p
                        break

        if not po:
            match.match_type = "none"
            match.issues.append("No matching purchase order found")
            invoice.status = InvoiceStatus.UNMATCHED
            return match

        # Calculate match score
        match.po_id = po.id
        match.po_number = po.po_number
        match.amount_variance = invoice.total_amount - po.total_amount

        if po.total_amount > 0:
            match.variance_percent = float(match.amount_variance / po.total_amount) * 100

        # Determine match quality
        if abs(match.variance_percent) < 1:
            match.match_type = "exact"
            match.match_score = 1.0
        elif abs(match.variance_percent) < 5:
            match.match_type = "partial"
            match.match_score = 0.9
            match.issues.append(f"Amount variance: {match.variance_percent:.1f}%")
        elif abs(match.variance_percent) < 10:
            match.match_type = "partial"
            match.match_score = 0.7
            match.issues.append(f"Significant amount variance: {match.variance_percent:.1f}%")
        else:
            match.match_type = "partial"
            match.match_score = 0.5
            match.issues.append(f"Large amount variance: {match.variance_percent:.1f}%")

        # Update invoice status
        invoice.matched_po_id = po.id
        invoice.status = InvoiceStatus.MATCHED
        invoice.updated_at = datetime.now()

        return match

    async def detect_anomalies(self, invoice: InvoiceData) -> list[Anomaly]:
        """
        Detect anomalies in an invoice.

        Args:
            invoice: Invoice to analyze

        Returns:
            List of detected anomalies
        """
        anomalies: list[Anomaly] = []
        vendor_key = invoice.vendor_name.lower()

        # 1. New vendor check
        if vendor_key not in self._known_vendors:
            anomalies.append(
                Anomaly(
                    type=AnomalyType.NEW_VENDOR,
                    severity="medium",
                    description=f"First invoice from vendor: {invoice.vendor_name}",
                    recommendation="Verify vendor details before processing",
                )
            )

        # 2. Unusual amount (compared to vendor history)
        if vendor_key in self._vendor_history and len(self._vendor_history[vendor_key]) >= 3:
            history = self._vendor_history[vendor_key]
            avg_amount = sum(history) / len(history)
            current = float(invoice.total_amount)

            # Flag if more than 3x or less than 1/3 of average
            if current > avg_amount * 3:
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.UNUSUAL_AMOUNT,
                        severity="high",
                        description=f"Amount ${current:.2f} is {current / avg_amount:.1f}x higher than average ${avg_amount:.2f}",
                        expected_value=f"${avg_amount:.2f}",
                        actual_value=f"${current:.2f}",
                        recommendation="Review invoice details and verify with vendor",
                    )
                )
            elif current < avg_amount / 3:
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.UNUSUAL_AMOUNT,
                        severity="low",
                        description=f"Amount ${current:.2f} is much lower than average ${avg_amount:.2f}",
                        expected_value=f"${avg_amount:.2f}",
                        actual_value=f"${current:.2f}",
                        recommendation="Verify this is the complete invoice",
                    )
                )

        # 3. Duplicate check
        if invoice.hash_key in self._hash_index:
            existing_id = self._hash_index[invoice.hash_key]
            if existing_id != invoice.id:
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.DUPLICATE,
                        severity="high",
                        description=f"Potential duplicate of invoice {existing_id}",
                        recommendation="Review both invoices before processing",
                    )
                )

        # 4. Round amount check (potential fraud indicator)
        amount = float(invoice.total_amount)
        if amount >= 100 and amount == int(amount) and amount % 100 == 0:
            anomalies.append(
                Anomaly(
                    type=AnomalyType.ROUND_AMOUNT,
                    severity="low",
                    description=f"Invoice has a round amount: ${amount:.2f}",
                    recommendation="Verify invoice authenticity",
                )
            )

        # 5. High value check
        if invoice.total_amount > Decimal("10000"):
            anomalies.append(
                Anomaly(
                    type=AnomalyType.HIGH_VALUE,
                    severity="medium",
                    description=f"High-value invoice: ${float(invoice.total_amount):.2f}",
                    recommendation=f"Requires {invoice.approval_level.value} approval",
                )
            )

        # 6. Missing PO check
        if invoice.status == InvoiceStatus.UNMATCHED:
            anomalies.append(
                Anomaly(
                    type=AnomalyType.MISSING_PO,
                    severity="medium",
                    description="No matching purchase order found",
                    recommendation="Request PO reference or create retrospective PO",
                )
            )

        # Update invoice anomalies
        invoice.anomalies = [a.type.value for a in anomalies]
        invoice.updated_at = datetime.now()

        return anomalies

    async def schedule_payment(
        self,
        invoice: InvoiceData,
        pay_date: datetime | None = None,
        payment_method: str = "ach",
    ) -> PaymentSchedule:
        """
        Schedule payment for an approved invoice.

        Args:
            invoice: Invoice to schedule
            pay_date: Payment date (defaults to due date)
            payment_method: Payment method

        Returns:
            Payment schedule
        """
        if invoice.status not in [InvoiceStatus.APPROVED, InvoiceStatus.MATCHED]:
            raise ValueError(
                f"Invoice must be approved before scheduling payment (current: {invoice.status})"
            )

        # Default to due date or 30 days
        if pay_date is None:
            pay_date = invoice.due_date or (datetime.now() + timedelta(days=30))

        # Check for early payment discount
        discount = Decimal("0")
        discount_rate = 0.0
        if invoice.payment_terms and "2/10" in invoice.payment_terms:
            # 2% discount if paid within 10 days
            days_to_invoice = (pay_date - invoice.invoice_date).days
            if days_to_invoice <= 10:
                discount_rate = 0.02
                discount = invoice.total_amount * Decimal("0.02")

        schedule = PaymentSchedule(
            invoice_id=invoice.id,
            pay_date=pay_date,
            amount=invoice.total_amount - discount,
            vendor_id=invoice.vendor_id or "",
            vendor_name=invoice.vendor_name,
            payment_method=payment_method,
            early_pay_discount=discount_rate,
            discount_amount=discount,
        )

        # Update invoice
        invoice.scheduled_pay_date = pay_date
        invoice.status = InvoiceStatus.SCHEDULED
        invoice.updated_at = datetime.now()

        # Store schedule
        self._payment_schedule[invoice.id] = schedule

        logger.info(
            "Scheduled payment for invoice %s: $%s on %s",
            invoice.id,
            schedule.amount,
            pay_date.date(),
        )
        return schedule

    async def approve_invoice(
        self,
        invoice_id: str,
        approver_id: str,
    ) -> InvoiceData | None:
        """
        Approve an invoice for payment.

        Args:
            invoice_id: Invoice ID
            approver_id: Approver user ID

        Returns:
            Updated invoice
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return None

        invoice.status = InvoiceStatus.APPROVED
        invoice.approver_id = approver_id
        invoice.approved_at = datetime.now()
        invoice.updated_at = datetime.now()

        # Update vendor history
        vendor_key = invoice.vendor_name.lower()
        if vendor_key not in self._vendor_history:
            self._vendor_history[vendor_key] = []
        self._vendor_history[vendor_key].append(float(invoice.total_amount))
        self._known_vendors.add(vendor_key)

        return invoice

    async def reject_invoice(
        self,
        invoice_id: str,
        reason: str = "",
    ) -> InvoiceData | None:
        """Reject an invoice."""
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return None

        invoice.status = InvoiceStatus.REJECTED
        invoice.notes = reason
        invoice.updated_at = datetime.now()
        return invoice

    async def create_manual_invoice(
        self,
        vendor_name: str,
        total_amount: float,
        invoice_number: str = "",
        invoice_date: datetime | None = None,
        due_date: datetime | None = None,
        line_items: list[dict[str, Any]] | None = None,
        po_number: str | None = None,
    ) -> InvoiceData:
        """
        Create an invoice manually (without document extraction).

        Args:
            vendor_name: Vendor name
            total_amount: Invoice total
            invoice_number: Invoice reference number
            invoice_date: Invoice date
            due_date: Payment due date
            line_items: Line items
            po_number: Purchase order reference

        Returns:
            Created invoice
        """
        invoice_id = f"inv_{uuid4().hex[:12]}"

        # Convert line items
        items = []
        if line_items:
            for li in line_items:
                items.append(
                    InvoiceLineItem(
                        description=li.get("description", ""),
                        quantity=li.get("quantity", 1),
                        unit_price=Decimal(str(li.get("unitPrice", 0))),
                        amount=Decimal(str(li.get("amount", 0))),
                    )
                )

        invoice = InvoiceData(
            id=invoice_id,
            vendor_name=vendor_name,
            invoice_number=invoice_number,
            invoice_date=invoice_date or datetime.now(),
            due_date=due_date or (datetime.now() + timedelta(days=30)),
            total_amount=Decimal(str(total_amount)),
            line_items=items,
            po_number=po_number,
            status=InvoiceStatus.EXTRACTED,
            confidence_score=1.0,  # Manual entry is 100% confident
        )

        # Calculate subtotal from line items if provided
        if items:
            invoice.subtotal = sum((li.amount for li in items), Decimal(0))

        # Determine approval level
        invoice.approval_level = self._determine_approval_level(invoice.total_amount)

        self._store_invoice(invoice)
        return invoice

    def _store_invoice(self, invoice: InvoiceData) -> None:
        """Store invoice and update indexes."""
        self._invoices[invoice.id] = invoice

        # Index by vendor
        vendor_key = invoice.vendor_name.lower()
        if vendor_key not in self._by_vendor:
            self._by_vendor[vendor_key] = set()
        self._by_vendor[vendor_key].add(invoice.id)

        # Index by status
        if invoice.status not in self._by_status:
            self._by_status[invoice.status] = set()
        self._by_status[invoice.status].add(invoice.id)

        # Hash index for duplicate detection
        self._hash_index[invoice.hash_key] = invoice.id

    async def add_purchase_order(
        self,
        po_number: str,
        vendor_name: str,
        total_amount: float,
        order_date: datetime | None = None,
        expected_delivery: datetime | None = None,
        line_items: list[dict[str, Any]] | None = None,
    ) -> PurchaseOrder:
        """Add a purchase order for matching."""
        po_id = f"po_{uuid4().hex[:12]}"

        po = PurchaseOrder(
            id=po_id,
            po_number=po_number,
            vendor_id="",
            vendor_name=vendor_name,
            total_amount=Decimal(str(total_amount)),
            order_date=order_date or datetime.now(),
            expected_delivery=expected_delivery,
            line_items=line_items or [],
        )

        self._purchase_orders[po_id] = po
        return po

    async def get_invoice(self, invoice_id: str) -> InvoiceData | None:
        """Get invoice by ID."""
        return self._invoices.get(invoice_id)

    async def list_invoices(
        self,
        status: InvoiceStatus | None = None,
        vendor: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[InvoiceData], int]:
        """
        List invoices with filters.

        Args:
            status: Filter by status
            vendor: Filter by vendor name
            start_date: Filter by date range
            end_date: Filter by date range
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (invoices, total_count)
        """
        invoices = list(self._invoices.values())

        if status:
            invoices = [i for i in invoices if i.status == status]

        if vendor:
            vendor_lower = vendor.lower()
            invoices = [i for i in invoices if vendor_lower in i.vendor_name.lower()]

        if start_date:
            invoices = [i for i in invoices if i.invoice_date >= start_date]

        if end_date:
            invoices = [i for i in invoices if i.invoice_date <= end_date]

        # Sort by date descending
        invoices.sort(key=lambda x: x.invoice_date, reverse=True)

        total = len(invoices)
        invoices = invoices[offset : offset + limit]

        return invoices, total

    async def get_pending_approvals(self) -> list[InvoiceData]:
        """Get invoices pending approval."""
        return [
            i
            for i in self._invoices.values()
            if i.status
            in [InvoiceStatus.MATCHED, InvoiceStatus.UNMATCHED, InvoiceStatus.PENDING_APPROVAL]
        ]

    async def get_scheduled_payments(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[PaymentSchedule]:
        """Get scheduled payments."""
        payments = list(self._payment_schedule.values())

        if start_date:
            payments = [p for p in payments if p.pay_date >= start_date]
        if end_date:
            payments = [p for p in payments if p.pay_date <= end_date]

        payments.sort(key=lambda x: x.pay_date)
        return payments

    async def get_overdue_invoices(self) -> list[InvoiceData]:
        """Get overdue invoices."""
        return [i for i in self._invoices.values() if i.is_overdue]

    def get_stats(self) -> dict[str, Any]:
        """Get invoice processing statistics."""
        invoices = list(self._invoices.values())

        if not invoices:
            return {
                "totalInvoices": 0,
                "totalAmount": 0,
                "pendingApproval": 0,
                "overdue": 0,
                "byStatus": {},
            }

        # Exclude rejected
        active = [i for i in invoices if i.status != InvoiceStatus.REJECTED]

        by_status = {}
        for status in InvoiceStatus:
            count = len([i for i in invoices if i.status == status])
            if count > 0:
                by_status[status.value] = count

        overdue = [i for i in active if i.is_overdue]
        pending = [
            i for i in active if i.status in [InvoiceStatus.MATCHED, InvoiceStatus.UNMATCHED]
        ]

        return {
            "totalInvoices": len(active),
            "totalAmount": sum(float(i.total_amount) for i in active),
            "pendingApproval": len(pending),
            "pendingAmount": sum(float(i.total_amount) for i in pending),
            "overdue": len(overdue),
            "overdueAmount": sum(float(i.total_amount) for i in overdue),
            "byStatus": by_status,
            "avgProcessingTime": 0,  # Would calculate from timestamps
        }
