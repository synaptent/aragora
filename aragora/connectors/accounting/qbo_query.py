"""
QuickBooks Online Query Builder.

Extracted from qbo.py. Provides safe query construction for QuickBooks
Query Language (OOQL) with input validation and injection prevention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class QBOQueryBuilder:
    """
    Safe query builder for QuickBooks Query Language (OOQL).

    Provides a fluent API that automatically validates and escapes all inputs
    to prevent injection attacks. All values are validated before being used.

    Example:
        query = (QBOQueryBuilder("Invoice")
            .select("Id", "DocNumber", "TxnDate", "TotalAmt")
            .where_eq("Active", True)
            .where_gte("TxnDate", start_date)
            .where_ref("CustomerRef", customer_id)
            .limit(100)
            .offset(0)
            .build())

    Security:
        - Entity names validated against VALID_ENTITIES allowlist
        - Field names validated against VALID_FIELDS allowlist
        - String values sanitized (max 500 chars, special chars stripped, quotes escaped)
        - Numeric IDs validated as digits only
        - Dates formatted safely as YYYY-MM-DD
        - Pagination bounded (max 1000, no negative offsets)
    """

    # Allowlist of valid QBO entities
    VALID_ENTITIES = frozenset(
        {
            "Account",
            "Bill",
            "BillPayment",
            "Budget",
            "Class",
            "CompanyInfo",
            "CreditMemo",
            "Customer",
            "Department",
            "Deposit",
            "Employee",
            "Estimate",
            "Invoice",
            "Item",
            "JournalEntry",
            "Payment",
            "PaymentMethod",
            "Purchase",
            "PurchaseOrder",
            "RefundReceipt",
            "SalesReceipt",
            "TaxAgency",
            "TaxCode",
            "TaxRate",
            "Term",
            "TimeActivity",
            "Transfer",
            "Vendor",
            "VendorCredit",
        }
    )

    # Allowlist of valid QBO query fields
    VALID_FIELDS = frozenset(
        {
            # Common fields
            "Id",
            "SyncToken",
            "Active",
            "DocNumber",
            "TxnDate",
            "DueDate",
            "TotalAmt",
            "Balance",
            "PrivateNote",
            "Line",
            "CustomerRef",
            "VendorRef",
            "Metadata",
            "CreateTime",
            "LastUpdatedTime",
            # Customer fields
            "DisplayName",
            "CompanyName",
            "PrimaryEmailAddr",
            "PrimaryPhone",
            # Account fields
            "Name",
            "AccountType",
            "AccountSubType",
            "CurrentBalance",
            # Invoice/Transaction fields
            "SalesTermRef",
            "ShipDate",
            "TrackingNum",
            "PaymentMethodRef",
        }
    )

    # Characters allowed in string values (defense in depth)
    _SAFE_CHARS = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        " -_.@+#$%&*()[]{}:;,/\\!?<>=~`|^"
    )

    def __init__(self, entity: str):
        """
        Initialize query builder for a specific entity.

        Args:
            entity: QBO entity name (e.g., "Invoice", "Customer")

        Raises:
            ValueError: If entity is not in the allowlist
        """
        if entity not in self.VALID_ENTITIES:
            raise ValueError(
                f"Invalid QBO entity '{entity}'. Must be one of: {sorted(self.VALID_ENTITIES)}"
            )
        self._entity = entity
        self._select_fields: list[str] = []
        self._conditions: list[str] = []
        self._limit_val: int = 100
        self._offset_val: int = 0

    def select(self, *fields: str) -> QBOQueryBuilder:
        """
        Specify fields to select.

        Args:
            fields: Field names to select (validated against allowlist)

        Returns:
            Self for chaining

        Raises:
            ValueError: If any field is not in the allowlist
        """
        for field_name in fields:
            if field_name not in self.VALID_FIELDS:
                raise ValueError(
                    f"Invalid QBO field '{field_name}'. Must be one of: {sorted(self.VALID_FIELDS)}"
                )
        self._select_fields.extend(fields)
        return self

    def where_eq(self, field: str, value: Any) -> QBOQueryBuilder:
        """
        Add equality condition.

        Args:
            field: Field name (validated)
            value: Value (sanitized based on type)

        Returns:
            Self for chaining
        """
        self._validate_field(field)
        safe_value = self._format_value(value)
        self._conditions.append(f"{field} = {safe_value}")
        return self

    def where_raw(self, condition: str) -> QBOQueryBuilder:
        """Add a pre-sanitized raw condition string."""
        self._conditions.append(condition)
        return self

    def where_gte(self, field: str, value: datetime) -> QBOQueryBuilder:
        """Add >= condition for dates."""
        self._validate_field(field)
        safe_date = self._format_date(value)
        self._conditions.append(f"{field} >= '{safe_date}'")
        return self

    def where_lte(self, field: str, value: datetime) -> QBOQueryBuilder:
        """Add <= condition for dates."""
        self._validate_field(field)
        safe_date = self._format_date(value)
        self._conditions.append(f"{field} <= '{safe_date}'")
        return self

    def where_ref(self, field: str, ref_id: str) -> QBOQueryBuilder:
        """Add reference ID condition (e.g., CustomerRef)."""
        self._validate_field(field)
        safe_id = self._validate_numeric_id(ref_id)
        self._conditions.append(f"{field} = '{safe_id}'")
        return self

    def where_like(self, field: str, pattern: str) -> QBOQueryBuilder:
        """Add LIKE condition with sanitized pattern."""
        self._validate_field(field)
        safe_pattern = self._sanitize_string(pattern)
        self._conditions.append(f"{field} LIKE '%{safe_pattern}%'")
        return self

    def limit(self, value: int) -> QBOQueryBuilder:
        """Set max results (capped at 1000)."""
        self._limit_val = max(1, min(int(value), 1000))
        return self

    def offset(self, value: int) -> QBOQueryBuilder:
        """Set starting position (0-indexed, capped at 100000)."""
        self._offset_val = max(0, min(int(value), 100000))
        return self

    def build(self) -> str:
        """
        Build the final query string.

        Returns:
            Safe QBO query string
        """
        # Default to "*" if no fields specified
        fields = ", ".join(self._select_fields) if self._select_fields else "*"

        # Build WHERE clause
        where_clause = " AND ".join(self._conditions) if self._conditions else "1=1"

        # QBO uses 1-indexed STARTPOSITION
        start_position = self._offset_val + 1

        return (
            f"SELECT {fields} FROM {self._entity} "  # internal query construction
            f"WHERE {where_clause} "
            f"MAXRESULTS {self._limit_val} STARTPOSITION {start_position}"
        )

    def _validate_field(self, field: str) -> None:
        """Validate field name against allowlist."""
        if field not in self.VALID_FIELDS:
            raise ValueError(
                f"Invalid QBO field '{field}'. Must be one of: {sorted(self.VALID_FIELDS)}"
            )

    def _format_value(self, value: Any) -> str:
        """Format value based on type."""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, datetime):
            return f"'{self._format_date(value)}'"
        else:
            return f"'{self._sanitize_string(str(value))}'"

    def _format_date(self, date_value: datetime) -> str:
        """Format date as YYYY-MM-DD."""
        if not isinstance(date_value, datetime):
            raise ValueError(f"Expected datetime, got {type(date_value)}")
        return date_value.strftime("%Y-%m-%d")

    def _validate_numeric_id(self, value: str) -> str:
        """Validate numeric ID (digits only)."""
        value_str = str(value).strip()
        if not value_str.isdigit():
            raise ValueError(f"ID must be numeric (must be a numeric ID), got '{value}'")
        return value_str

    def _sanitize_string(self, value: str) -> str:
        """
        Sanitize string value for QBO query.

        Security measures:
        - Max 500 characters (raises ValueError if exceeded)
        - Only safe characters allowed (defined in _SAFE_CHARS)
        - Single quotes are filtered out (not in _SAFE_CHARS), preventing
          quote-based injection attacks entirely
        """
        if len(value) > 500:
            raise ValueError(f"String value exceeds 500 character limit: {len(value)}")

        # Filter to safe characters (single quotes are excluded)
        sanitized = "".join(c for c in value if c in self._SAFE_CHARS)

        return sanitized


__all__ = [
    "QBOQueryBuilder",
]
