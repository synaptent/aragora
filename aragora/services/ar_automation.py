"""
Accounts Receivable Automation Service.

Automates accounts receivable workflows:
- Invoice generation from work completed
- Payment reminder emails with escalating urgency
- AR aging report generation
- Collection action suggestions
- Cash flow forecasting

Usage:
    from aragora.services.ar_automation import ARAutomation

    ar = ARAutomation()

    # Generate invoice
    invoice = await ar.generate_invoice(customer_id, line_items)

    # Send payment reminder
    await ar.send_payment_reminder(invoice_id, escalation_level=1)

    # Get aging report
    aging = await ar.track_aging()

    # Get collection suggestions
    actions = await ar.suggest_collections()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from aragora.connectors.accounting.qbo import QuickBooksConnector
    from aragora.integrations.email import EmailConfig, EmailIntegration

logger = logging.getLogger(__name__)


class InvoiceStatus(str, Enum):
    """AR invoice status."""

    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    PARTIAL = "partial"  # Partially paid
    PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"


class ReminderLevel(str, Enum):
    """Payment reminder escalation levels."""

    FRIENDLY = "friendly"  # First reminder, polite
    FIRM = "firm"  # Second reminder
    URGENT = "urgent"  # Third reminder, urgent tone
    FINAL = "final"  # Final notice before collections


class CollectionAction(str, Enum):
    """Suggested collection actions."""

    SEND_REMINDER = "send_reminder"
    PHONE_CALL = "phone_call"
    PAYMENT_PLAN = "payment_plan"
    COLLECTION_AGENCY = "collection_agency"
    LEGAL_ACTION = "legal_action"
    WRITE_OFF = "write_off"


@dataclass
class ARInvoice:
    """An accounts receivable invoice."""

    id: str
    customer_id: str
    customer_name: str
    customer_email: str | None = None
    invoice_number: str = ""
    invoice_date: datetime = field(default_factory=datetime.now)
    due_date: datetime | None = None
    subtotal: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    total_amount: Decimal = Decimal("0.00")
    amount_paid: Decimal = Decimal("0.00")
    balance: Decimal = Decimal("0.00")
    currency: str = "USD"
    status: InvoiceStatus = InvoiceStatus.DRAFT
    line_items: list[dict[str, Any]] = field(default_factory=list)
    payment_terms: str = "Net 30"
    memo: str = ""
    qbo_id: str | None = None
    sent_at: datetime | None = None
    reminder_count: int = 0
    last_reminder: datetime | None = None
    last_reminder_level: ReminderLevel | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def days_overdue(self) -> int:
        """Days past due date."""
        if self.due_date and self.status != InvoiceStatus.PAID:
            days = (datetime.now() - self.due_date).days
            return max(0, days)
        return 0

    @property
    def is_overdue(self) -> bool:
        """Check if invoice is overdue."""
        return self.days_overdue > 0

    @property
    def aging_bucket(self) -> str:
        """Get aging bucket (Current, 1-30, 31-60, 61-90, 90+)."""
        days = self.days_overdue
        if days == 0:
            return "Current"
        elif days <= 30:
            return "1-30"
        elif days <= 60:
            return "31-60"
        elif days <= 90:
            return "61-90"
        else:
            return "90+"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "customerId": self.customer_id,
            "customerName": self.customer_name,
            "customerEmail": self.customer_email,
            "invoiceNumber": self.invoice_number,
            "invoiceDate": self.invoice_date.isoformat(),
            "dueDate": self.due_date.isoformat() if self.due_date else None,
            "subtotal": float(self.subtotal),
            "taxAmount": float(self.tax_amount),
            "totalAmount": float(self.total_amount),
            "amountPaid": float(self.amount_paid),
            "balance": float(self.balance),
            "status": self.status.value,
            "lineItems": self.line_items,
            "paymentTerms": self.payment_terms,
            "daysOverdue": self.days_overdue,
            "isOverdue": self.is_overdue,
            "agingBucket": self.aging_bucket,
            "reminderCount": self.reminder_count,
            "lastReminder": self.last_reminder.isoformat() if self.last_reminder else None,
            "createdAt": self.created_at.isoformat(),
        }


@dataclass
class AgingReport:
    """AR aging report."""

    as_of_date: datetime = field(default_factory=datetime.now)
    total_receivables: Decimal = Decimal("0.00")
    current: Decimal = Decimal("0.00")
    days_1_30: Decimal = Decimal("0.00")
    days_31_60: Decimal = Decimal("0.00")
    days_61_90: Decimal = Decimal("0.00")
    days_90_plus: Decimal = Decimal("0.00")
    by_customer: list[dict[str, Any]] = field(default_factory=list)
    invoice_count: int = 0
    customer_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "asOfDate": self.as_of_date.isoformat(),
            "totalReceivables": float(self.total_receivables),
            "current": float(self.current),
            "days1_30": float(self.days_1_30),
            "days31_60": float(self.days_31_60),
            "days61_90": float(self.days_61_90),
            "days90Plus": float(self.days_90_plus),
            "byCustomer": self.by_customer,
            "invoiceCount": self.invoice_count,
            "customerCount": self.customer_count,
        }


@dataclass
class CollectionSuggestion:
    """A suggested collection action."""

    invoice_id: str
    customer_id: str
    customer_name: str
    balance: Decimal
    days_overdue: int
    action: CollectionAction
    priority: str  # high, medium, low
    reason: str
    suggested_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoiceId": self.invoice_id,
            "customerId": self.customer_id,
            "customerName": self.customer_name,
            "balance": float(self.balance),
            "daysOverdue": self.days_overdue,
            "action": self.action.value,
            "priority": self.priority,
            "reason": self.reason,
            "suggestedMessage": self.suggested_message,
        }


@dataclass
class ReminderTemplate:
    """Email reminder template."""

    level: ReminderLevel
    subject: str
    body: str


# Default reminder templates
REMINDER_TEMPLATES = {
    ReminderLevel.FRIENDLY: ReminderTemplate(
        level=ReminderLevel.FRIENDLY,
        subject="Friendly Reminder: Invoice {invoice_number} Due",
        body="""Hi {customer_name},

This is a friendly reminder that invoice #{invoice_number} for ${amount} is due on {due_date}.

If you've already sent payment, please disregard this message.

Best regards,
{company_name}""",
    ),
    ReminderLevel.FIRM: ReminderTemplate(
        level=ReminderLevel.FIRM,
        subject="Payment Reminder: Invoice {invoice_number} Past Due",
        body="""Dear {customer_name},

Our records indicate that invoice #{invoice_number} for ${amount} was due on {due_date} and is now {days_overdue} days past due.

Please arrange payment at your earliest convenience.

Thank you,
{company_name}""",
    ),
    ReminderLevel.URGENT: ReminderTemplate(
        level=ReminderLevel.URGENT,
        subject="URGENT: Invoice {invoice_number} Requires Immediate Attention",
        body="""Dear {customer_name},

Invoice #{invoice_number} for ${amount} is now {days_overdue} days past due.

To avoid service interruption and additional fees, please submit payment immediately.

If you are experiencing difficulties, please contact us to discuss payment arrangements.

{company_name}""",
    ),
    ReminderLevel.FINAL: ReminderTemplate(
        level=ReminderLevel.FINAL,
        subject="FINAL NOTICE: Invoice {invoice_number}",
        body="""Dear {customer_name},

This is a final notice regarding invoice #{invoice_number} for ${amount}, which is now {days_overdue} days past due.

If we do not receive payment within 7 days, we will be forced to take further action, which may include:
- Service suspension
- Referral to a collection agency
- Reporting to credit bureaus

Please contact us immediately to resolve this matter.

{company_name}""",
    ),
}


class ARAutomation:
    """
    Service for automating accounts receivable workflows.

    Handles invoice generation, payment reminders, aging reports,
    and collection suggestions.
    """

    def __init__(
        self,
        qbo_connector: QuickBooksConnector | None = None,
        company_name: str = "Your Company",
        default_payment_terms: str = "Net 30",
        email_config: EmailConfig | None = None,
        email_integration: EmailIntegration | None = None,
    ):
        """
        Initialize AR automation service.

        Args:
            qbo_connector: QuickBooks connector for sync
            company_name: Company name for templates
            default_payment_terms: Default payment terms
            email_config: Email configuration for sending reminders
            email_integration: Pre-configured email integration instance
        """
        self.qbo = qbo_connector
        self.company_name = company_name
        self.default_payment_terms = default_payment_terms

        # Email integration for sending reminders
        self._email: EmailIntegration | None = email_integration
        self._email_config = email_config

        # In-memory storage
        self._invoices: dict[str, ARInvoice] = {}
        self._by_customer: dict[str, set[str]] = {}
        self._by_status: dict[InvoiceStatus, set[str]] = {}
        self._customers: dict[str, dict[str, Any]] = {}  # Customer data
        self._reminder_history: list[dict[str, Any]] = []

    def _get_email_integration(self) -> EmailIntegration | None:
        """Get or create email integration lazily."""
        if self._email is not None:
            return self._email

        if self._email_config is not None:
            from aragora.notifications.email_senders import create_email_sender

            self._email = create_email_sender(self._email_config)
            return self._email

        return None

    async def generate_invoice(
        self,
        customer_id: str,
        line_items: list[dict[str, Any]],
        customer_name: str | None = None,
        customer_email: str | None = None,
        invoice_date: datetime | None = None,
        due_date: datetime | None = None,
        payment_terms: str | None = None,
        memo: str = "",
        auto_send: bool = False,
    ) -> ARInvoice:
        """
        Generate an invoice from line items.

        Args:
            customer_id: Customer ID
            line_items: Invoice line items [{description, quantity, unitPrice, amount}]
            customer_name: Customer name
            customer_email: Customer email for sending
            invoice_date: Invoice date
            due_date: Payment due date
            payment_terms: Payment terms
            memo: Invoice memo
            auto_send: Automatically send to customer

        Returns:
            Generated invoice
        """
        invoice_id = f"ar_{uuid4().hex[:12]}"
        inv_date = invoice_date or datetime.now()

        # Calculate due date from payment terms
        if due_date is None:
            terms = payment_terms or self.default_payment_terms
            if "Net 30" in terms:
                due_date = inv_date + timedelta(days=30)
            elif "Net 15" in terms:
                due_date = inv_date + timedelta(days=15)
            elif "Net 60" in terms:
                due_date = inv_date + timedelta(days=60)
            elif "Due on Receipt" in terms:
                due_date = inv_date
            else:
                due_date = inv_date + timedelta(days=30)

        # Calculate totals
        subtotal = Decimal("0")
        for item in line_items:
            amount = Decimal(str(item.get("amount", 0)))
            subtotal += amount

        # Simple tax calculation (could be enhanced)
        tax_rate = Decimal("0.0825")  # 8.25% example
        tax_amount = subtotal * tax_rate
        total_amount = subtotal + tax_amount

        # Get customer info
        if customer_id in self._customers:
            customer_data = self._customers[customer_id]
            customer_name = customer_name or customer_data.get("name", "Unknown")
            customer_email = customer_email or customer_data.get("email")

        # Generate invoice number
        invoice_count = len(self._invoices) + 1
        invoice_number = f"INV-{datetime.now().year}-{invoice_count:05d}"

        invoice = ARInvoice(
            id=invoice_id,
            customer_id=customer_id,
            customer_name=customer_name or "Unknown Customer",
            customer_email=customer_email,
            invoice_number=invoice_number,
            invoice_date=inv_date,
            due_date=due_date,
            subtotal=subtotal,
            tax_amount=tax_amount.quantize(Decimal("0.01")),
            total_amount=total_amount.quantize(Decimal("0.01")),
            balance=total_amount.quantize(Decimal("0.01")),
            line_items=line_items,
            payment_terms=payment_terms or self.default_payment_terms,
            memo=memo,
            status=InvoiceStatus.DRAFT,
        )

        self._store_invoice(invoice)

        # Auto-send if requested
        if auto_send and customer_email:
            await self.send_invoice(invoice_id)

        logger.info("Generated invoice %s for %s: $%s", invoice_number, customer_name, total_amount)
        return invoice

    async def send_invoice(self, invoice_id: str, send_email: bool = True) -> bool:
        """
        Send invoice to customer.

        Args:
            invoice_id: Invoice ID
            send_email: Whether to actually send the email (default True)

        Returns:
            Success status
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return False

        if not invoice.customer_email:
            logger.warning("No email for customer %s", invoice.customer_name)
            return False

        email_sent = False

        # Send actual email if configured
        if send_email:
            email_sent = await self._send_invoice_email(invoice)

        # Update status regardless of email success
        invoice.status = InvoiceStatus.SENT
        invoice.sent_at = datetime.now()
        invoice.updated_at = datetime.now()

        logger.info(
            "Sent invoice %s to %s (email=%s)",
            invoice.invoice_number,
            invoice.customer_email,
            "sent" if email_sent else "not sent",
        )
        return True

    async def _send_invoice_email(self, invoice: ARInvoice) -> bool:
        """
        Send invoice email using the email integration.

        Args:
            invoice: The invoice to send

        Returns:
            True if email was sent successfully
        """
        email_integration = self._get_email_integration()
        if email_integration is None:
            logger.debug("No email integration configured, skipping invoice email")
            return False

        if not invoice.customer_email:
            return False

        subject = f"Invoice {invoice.invoice_number} from {self.company_name}"
        html_body = self._build_invoice_html(invoice)
        text_body = self._build_invoice_text(invoice)

        # Create recipient
        from aragora.notifications.email_recipient import EmailRecipient

        recipient = EmailRecipient(
            email=invoice.customer_email,
            name=invoice.customer_name,
        )

        try:
            success = await email_integration._send_email(
                recipient=recipient,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
            return success
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("Error sending invoice email: %s", e)
            return False

    def _build_invoice_html(self, invoice: ARInvoice) -> str:
        """Build HTML email for invoice."""
        # Build line items table
        line_items_html = ""
        for item in invoice.line_items:
            description = item.get("description", "")
            quantity = item.get("quantity", 1)
            unit_price = item.get("unitPrice", 0)
            amount = item.get("amount", 0)
            line_items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{description}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{quantity}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">${float(unit_price):,.2f}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">${float(amount):,.2f}</td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #2196F3; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #e0e0e0; }}
                .footer {{ background: #333; color: #999; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
                .invoice-header {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
                .invoice-info {{ background: #fff; padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; background: #fff; }}
                th {{ background: #f5f5f5; padding: 12px; text-align: left; border-bottom: 2px solid #ddd; }}
                .totals {{ text-align: right; margin-top: 20px; }}
                .total-row {{ padding: 8px 0; }}
                .grand-total {{ font-size: 20px; font-weight: bold; color: #2196F3; }}
                .button {{ display: inline-block; background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Invoice</h1>
                    <p>{invoice.invoice_number}</p>
                </div>
                <div class="content">
                    <div class="invoice-info">
                        <p><strong>Bill To:</strong> {invoice.customer_name}</p>
                        <p><strong>Invoice Date:</strong> {invoice.invoice_date.strftime("%B %d, %Y")}</p>
                        <p><strong>Due Date:</strong> {invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "N/A"}</p>
                        <p><strong>Payment Terms:</strong> {invoice.payment_terms}</p>
                    </div>

                    <table>
                        <thead>
                            <tr>
                                <th>Description</th>
                                <th style="text-align: center;">Qty</th>
                                <th style="text-align: right;">Unit Price</th>
                                <th style="text-align: right;">Amount</th>
                            </tr>
                        </thead>
                        <tbody>
                            {line_items_html}
                        </tbody>
                    </table>

                    <div class="totals">
                        <div class="total-row">Subtotal: ${float(invoice.subtotal):,.2f}</div>
                        <div class="total-row">Tax: ${float(invoice.tax_amount):,.2f}</div>
                        <div class="total-row grand-total">Total Due: ${float(invoice.total_amount):,.2f}</div>
                    </div>

                    {f'<p style="margin-top: 20px;"><strong>Memo:</strong> {invoice.memo}</p>' if invoice.memo else ""}

                    <div style="text-align: center; margin-top: 20px;">
                        <a href="mailto:payments@{self.company_name.lower().replace(" ", "")}.com?subject=Payment for {invoice.invoice_number}" class="button">
                            Pay Now
                        </a>
                    </div>
                </div>
                <div class="footer">
                    <p>{self.company_name}</p>
                    <p>Thank you for your business!</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _build_invoice_text(self, invoice: ARInvoice) -> str:
        """Build plain text email for invoice."""
        lines = [
            f"INVOICE {invoice.invoice_number}",
            "=" * 50,
            "",
            f"Bill To: {invoice.customer_name}",
            f"Invoice Date: {invoice.invoice_date.strftime('%B %d, %Y')}",
            f"Due Date: {invoice.due_date.strftime('%B %d, %Y') if invoice.due_date else 'N/A'}",
            f"Payment Terms: {invoice.payment_terms}",
            "",
            "-" * 50,
            "Line Items:",
            "-" * 50,
        ]

        for item in invoice.line_items:
            description = item.get("description", "")
            quantity = item.get("quantity", 1)
            amount = item.get("amount", 0)
            lines.append(f"  {description} (x{quantity}): ${float(amount):,.2f}")

        lines.extend(
            [
                "-" * 50,
                f"Subtotal: ${float(invoice.subtotal):,.2f}",
                f"Tax: ${float(invoice.tax_amount):,.2f}",
                f"TOTAL DUE: ${float(invoice.total_amount):,.2f}",
                "",
            ]
        )

        if invoice.memo:
            lines.extend([f"Memo: {invoice.memo}", ""])

        lines.extend(
            [
                "-" * 50,
                self.company_name,
                "Thank you for your business!",
            ]
        )

        return "\n".join(lines)

    async def send_payment_reminder(
        self,
        invoice_id: str,
        escalation_level: int | None = None,
        custom_message: str | None = None,
        send_email: bool = True,
    ) -> dict[str, Any] | None:
        """
        Send a payment reminder for an overdue invoice.

        Args:
            invoice_id: Invoice ID
            escalation_level: 1-4 (friendly to final), auto-determined if None
            custom_message: Custom reminder message
            send_email: Whether to actually send the email (default True)

        Returns:
            Reminder details or None if failed
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return None

        if not invoice.customer_email:
            logger.warning("No email for customer %s", invoice.customer_name)
            return None

        # Determine escalation level
        if escalation_level is None:
            escalation_level = min(invoice.reminder_count + 1, 4)

        # Map level to enum
        level_map = {
            1: ReminderLevel.FRIENDLY,
            2: ReminderLevel.FIRM,
            3: ReminderLevel.URGENT,
            4: ReminderLevel.FINAL,
        }
        level = level_map.get(escalation_level, ReminderLevel.FRIENDLY)

        # Get template
        template = REMINDER_TEMPLATES.get(level)
        if not template:
            template = REMINDER_TEMPLATES[ReminderLevel.FRIENDLY]

        # Format message
        message = custom_message or template.body.format(
            customer_name=invoice.customer_name,
            invoice_number=invoice.invoice_number,
            amount=f"{float(invoice.balance):,.2f}",
            due_date=invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "N/A",
            days_overdue=invoice.days_overdue,
            company_name=self.company_name,
        )

        subject = template.subject.format(
            invoice_number=invoice.invoice_number,
        )

        # Build reminder record
        reminder = {
            "invoiceId": invoice_id,
            "customerId": invoice.customer_id,
            "customerEmail": invoice.customer_email,
            "level": level.value,
            "subject": subject,
            "message": message,
            "sentAt": datetime.now().isoformat(),
            "emailSent": False,
        }

        # Send actual email if configured and requested
        if send_email:
            email_sent = await self._send_reminder_email(
                invoice=invoice,
                subject=subject,
                text_body=message,
                level=level,
            )
            reminder["emailSent"] = email_sent

            if not email_sent:
                logger.warning(
                    "Failed to send email for reminder on invoice %s", invoice.invoice_number
                )

        # Update invoice
        invoice.reminder_count += 1
        invoice.last_reminder = datetime.now()
        invoice.last_reminder_level = level
        invoice.updated_at = datetime.now()

        # Store history
        self._reminder_history.append(reminder)

        logger.info(
            "Sent %s reminder for invoice %s (email=%s)",
            level.value,
            invoice.invoice_number,
            "sent" if reminder["emailSent"] else "not sent",
        )
        return reminder

    async def _send_reminder_email(
        self,
        invoice: ARInvoice,
        subject: str,
        text_body: str,
        level: ReminderLevel,
    ) -> bool:
        """
        Send reminder email using the email integration.

        Args:
            invoice: The invoice to send reminder for
            subject: Email subject
            text_body: Plain text email body
            level: Reminder escalation level

        Returns:
            True if email was sent successfully
        """
        email_integration = self._get_email_integration()
        if email_integration is None:
            logger.debug("No email integration configured, skipping email send")
            return False

        if not invoice.customer_email:
            return False

        # Build HTML body
        html_body = self._build_reminder_html(
            invoice=invoice,
            text_body=text_body,
            level=level,
        )

        # Create recipient
        from aragora.notifications.email_recipient import EmailRecipient

        recipient = EmailRecipient(
            email=invoice.customer_email,
            name=invoice.customer_name,
        )

        # Send email
        try:
            success = await email_integration._send_email(
                recipient=recipient,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )
            return success
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.error("Error sending reminder email: %s", e)
            return False

    def _build_reminder_html(
        self,
        invoice: ARInvoice,
        text_body: str,
        level: ReminderLevel,
    ) -> str:
        """Build HTML email for payment reminder."""
        # Color coding based on urgency level
        level_colors = {
            ReminderLevel.FRIENDLY: "#4CAF50",  # Green
            ReminderLevel.FIRM: "#FF9800",  # Orange
            ReminderLevel.URGENT: "#f44336",  # Red
            ReminderLevel.FINAL: "#9C27B0",  # Purple
        }
        header_color = level_colors.get(level, "#4CAF50")

        level_titles = {
            ReminderLevel.FRIENDLY: "Payment Reminder",
            ReminderLevel.FIRM: "Payment Past Due",
            ReminderLevel.URGENT: "Urgent: Payment Required",
            ReminderLevel.FINAL: "Final Notice",
        }
        header_title = level_titles.get(level, "Payment Reminder")

        # Convert text body to HTML paragraphs
        body_html = "<br>".join(text_body.split("\n"))

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: {header_color}; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #e0e0e0; }}
                .footer {{ background: #333; color: #999; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
                .invoice-details {{ background: #fff; border: 1px solid #e0e0e0; padding: 15px; margin: 15px 0; border-radius: 4px; }}
                .detail-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }}
                .detail-row:last-child {{ border-bottom: none; }}
                .detail-label {{ color: #666; }}
                .detail-value {{ font-weight: bold; }}
                .amount {{ font-size: 24px; color: {header_color}; font-weight: bold; }}
                .button {{ display: inline-block; background: {header_color}; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; margin: 15px 0; }}
                .message {{ white-space: pre-line; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{header_title}</h1>
                </div>
                <div class="content">
                    <div class="invoice-details">
                        <div class="detail-row">
                            <span class="detail-label">Invoice Number</span>
                            <span class="detail-value">{invoice.invoice_number}</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Due Date</span>
                            <span class="detail-value">{invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "N/A"}</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Days Overdue</span>
                            <span class="detail-value">{invoice.days_overdue} days</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">Amount Due</span>
                            <span class="amount">${float(invoice.balance):,.2f}</span>
                        </div>
                    </div>

                    <div class="message">
                        {body_html}
                    </div>

                    <div style="text-align: center;">
                        <a href="mailto:payments@{self.company_name.lower().replace(" ", "")}.com?subject=Payment for {invoice.invoice_number}" class="button">
                            Contact Us About Payment
                        </a>
                    </div>
                </div>
                <div class="footer">
                    <p>{self.company_name}</p>
                    <p>This is an automated payment reminder.</p>
                </div>
            </div>
        </body>
        </html>
        """

    async def track_aging(self) -> AgingReport:
        """
        Generate AR aging report.

        Returns:
            Aging report with buckets
        """
        report = AgingReport()
        customer_totals: dict[str, dict[str, Any]] = {}

        for invoice in self._invoices.values():
            if invoice.status == InvoiceStatus.PAID or invoice.balance <= 0:
                continue

            report.invoice_count += 1
            report.total_receivables += invoice.balance

            # Categorize by aging bucket
            bucket = invoice.aging_bucket
            if bucket == "Current":
                report.current += invoice.balance
            elif bucket == "1-30":
                report.days_1_30 += invoice.balance
            elif bucket == "31-60":
                report.days_31_60 += invoice.balance
            elif bucket == "61-90":
                report.days_61_90 += invoice.balance
            else:
                report.days_90_plus += invoice.balance

            # Track by customer
            cust_id = invoice.customer_id
            if cust_id not in customer_totals:
                customer_totals[cust_id] = {
                    "customerId": cust_id,
                    "customerName": invoice.customer_name,
                    "total": Decimal("0"),
                    "current": Decimal("0"),
                    "days1_30": Decimal("0"),
                    "days31_60": Decimal("0"),
                    "days61_90": Decimal("0"),
                    "days90Plus": Decimal("0"),
                    "invoiceCount": 0,
                }

            customer_totals[cust_id]["total"] += invoice.balance
            customer_totals[cust_id]["invoiceCount"] += 1

            if bucket == "Current":
                customer_totals[cust_id]["current"] += invoice.balance
            elif bucket == "1-30":
                customer_totals[cust_id]["days1_30"] += invoice.balance
            elif bucket == "31-60":
                customer_totals[cust_id]["days31_60"] += invoice.balance
            elif bucket == "61-90":
                customer_totals[cust_id]["days61_90"] += invoice.balance
            else:
                customer_totals[cust_id]["days90Plus"] += invoice.balance

        # Convert customer totals to list
        report.by_customer = [
            {
                **data,
                "total": float(data["total"]),
                "current": float(data["current"]),
                "days1_30": float(data["days1_30"]),
                "days31_60": float(data["days31_60"]),
                "days61_90": float(data["days61_90"]),
                "days90Plus": float(data["days90Plus"]),
            }
            for data in sorted(
                customer_totals.values(),
                key=lambda x: x["total"],
                reverse=True,
            )
        ]

        report.customer_count = len(customer_totals)
        return report

    async def suggest_collections(self) -> list[CollectionSuggestion]:
        """
        Generate collection action suggestions based on aging.

        Returns:
            List of suggested collection actions
        """
        suggestions: list[CollectionSuggestion] = []

        for invoice in self._invoices.values():
            if invoice.status == InvoiceStatus.PAID or invoice.balance <= 0:
                continue

            if not invoice.is_overdue:
                continue

            days = invoice.days_overdue
            balance = invoice.balance

            # Determine action based on age and previous reminders
            if days <= 7:
                action = CollectionAction.SEND_REMINDER
                priority = "low"
                reason = "Recently overdue - send friendly reminder"
            elif days <= 30:
                if invoice.reminder_count < 2:
                    action = CollectionAction.SEND_REMINDER
                    priority = "medium"
                    reason = "Overdue 1-30 days - send firm reminder"
                else:
                    action = CollectionAction.PHONE_CALL
                    priority = "medium"
                    reason = "Multiple reminders sent - follow up by phone"
            elif days <= 60:
                if balance > Decimal("1000"):
                    action = CollectionAction.PHONE_CALL
                    priority = "high"
                    reason = "Large balance 31-60 days overdue"
                else:
                    action = CollectionAction.SEND_REMINDER
                    priority = "medium"
                    reason = "31-60 days overdue - send urgent reminder"
            elif days <= 90:
                action = CollectionAction.PAYMENT_PLAN
                priority = "high"
                reason = "61-90 days overdue - offer payment plan"
            else:  # 90+ days
                if balance > Decimal("5000"):
                    action = CollectionAction.LEGAL_ACTION
                    priority = "high"
                    reason = "Large balance 90+ days - consider legal action"
                elif balance < Decimal("100"):
                    action = CollectionAction.WRITE_OFF
                    priority = "low"
                    reason = "Small balance 90+ days - consider write-off"
                else:
                    action = CollectionAction.COLLECTION_AGENCY
                    priority = "high"
                    reason = "90+ days overdue - refer to collections"

            suggestions.append(
                CollectionSuggestion(
                    invoice_id=invoice.id,
                    customer_id=invoice.customer_id,
                    customer_name=invoice.customer_name,
                    balance=invoice.balance,
                    days_overdue=days,
                    action=action,
                    priority=priority,
                    reason=reason,
                )
            )

        # Sort by priority and amount
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: (priority_order[x.priority], -float(x.balance)))

        return suggestions

    async def record_payment(
        self,
        invoice_id: str,
        amount: float,
        payment_date: datetime | None = None,
        payment_method: str = "check",
        reference: str = "",
    ) -> ARInvoice | None:
        """
        Record a payment against an invoice.

        Args:
            invoice_id: Invoice ID
            amount: Payment amount
            payment_date: Payment date
            payment_method: Payment method
            reference: Payment reference

        Returns:
            Updated invoice
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return None

        payment = Decimal(str(amount))
        invoice.amount_paid += payment
        invoice.balance = invoice.total_amount - invoice.amount_paid

        # Update status
        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID
        elif invoice.amount_paid > 0:
            invoice.status = InvoiceStatus.PARTIAL

        invoice.updated_at = datetime.now()

        logger.info(
            "Recorded payment $%s for invoice %s, balance: $%s",
            amount,
            invoice.invoice_number,
            invoice.balance,
        )
        return invoice

    async def add_customer(
        self,
        customer_id: str,
        name: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> None:
        """Add or update customer info."""
        self._customers[customer_id] = {
            "id": customer_id,
            "name": name,
            "email": email,
            "phone": phone,
        }

    def _store_invoice(self, invoice: ARInvoice) -> None:
        """Store invoice and update indexes."""
        self._invoices[invoice.id] = invoice

        # Index by customer
        if invoice.customer_id not in self._by_customer:
            self._by_customer[invoice.customer_id] = set()
        self._by_customer[invoice.customer_id].add(invoice.id)

        # Index by status
        if invoice.status not in self._by_status:
            self._by_status[invoice.status] = set()
        self._by_status[invoice.status].add(invoice.id)

    async def get_invoice(self, invoice_id: str) -> ARInvoice | None:
        """Get invoice by ID."""
        return self._invoices.get(invoice_id)

    async def list_invoices(
        self,
        customer_id: str | None = None,
        status: InvoiceStatus | None = None,
        overdue_only: bool = False,
    ) -> list[ARInvoice]:
        """List invoices with filters."""
        invoices = list(self._invoices.values())

        if customer_id:
            invoices = [i for i in invoices if i.customer_id == customer_id]

        if status:
            invoices = [i for i in invoices if i.status == status]

        if overdue_only:
            invoices = [i for i in invoices if i.is_overdue]

        invoices.sort(key=lambda x: x.invoice_date, reverse=True)
        return invoices

    async def get_customer_balance(self, customer_id: str) -> Decimal:
        """Get total outstanding balance for a customer."""
        invoice_ids = self._by_customer.get(customer_id, set())
        total = Decimal("0")
        for inv_id in invoice_ids:
            invoice = self._invoices.get(inv_id)
            if invoice and invoice.status != InvoiceStatus.PAID:
                total += invoice.balance
        return total

    def get_stats(self) -> dict[str, Any]:
        """Get AR statistics."""
        invoices = list(self._invoices.values())
        active = [i for i in invoices if i.status != InvoiceStatus.PAID]

        return {
            "totalInvoices": len(invoices),
            "activeInvoices": len(active),
            "totalReceivables": float(sum(i.balance for i in active)),
            "overdueCount": len([i for i in active if i.is_overdue]),
            "overdueAmount": float(sum(i.balance for i in active if i.is_overdue)),
            "remindersSent": len(self._reminder_history),
            "customerCount": len(self._by_customer),
        }

    async def send_bulk_reminders(
        self,
        min_days_overdue: int = 1,
        max_reminders_per_invoice: int = 4,
        min_days_between_reminders: int = 7,
    ) -> dict[str, Any]:
        """
        Send payment reminders for all overdue invoices.

        Args:
            min_days_overdue: Minimum days overdue to trigger reminder
            max_reminders_per_invoice: Maximum reminders to send per invoice
            min_days_between_reminders: Minimum days between reminders

        Returns:
            Summary of reminders sent
        """
        sent = 0
        skipped = 0
        failed = 0
        results: list[dict[str, Any]] = []

        for invoice in self._invoices.values():
            # Skip paid or non-overdue invoices
            if invoice.status == InvoiceStatus.PAID or invoice.balance <= 0:
                continue

            if invoice.days_overdue < min_days_overdue:
                continue

            # Check reminder limit
            if invoice.reminder_count >= max_reminders_per_invoice:
                skipped += 1
                continue

            # Check time since last reminder
            if invoice.last_reminder:
                days_since = (datetime.now() - invoice.last_reminder).days
                if days_since < min_days_between_reminders:
                    skipped += 1
                    continue

            # Send reminder
            reminder = await self.send_payment_reminder(invoice.id)
            if reminder:
                if reminder.get("emailSent"):
                    sent += 1
                else:
                    failed += 1
                results.append(reminder)
            else:
                failed += 1

        logger.info(
            "Bulk reminders complete: %s sent, %s skipped, %s failed", sent, skipped, failed
        )

        return {
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
            "reminders": results,
        }

    async def close(self) -> None:
        """Close resources (email integration session)."""
        if self._email is not None:
            await self._email.close()

    async def __aenter__(self) -> ARAutomation:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
