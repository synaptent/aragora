"""Base class for connector data models.

Provides unified serialization and deserialization for connector models
across accounting, e-commerce, marketing, calendar, and other integrations.

This consolidates ~1,200 lines of duplicated to_dict() implementations
across 29+ connector model files.

Features:
- Consistent datetime handling (timezone-aware, ISO8601)
- Decimal serialization for financial data
- Enum value serialization
- Nested model support
- Field name mapping for API compatibility (snake_case <-> camelCase)
- Optional field exclusion

Usage:
    from dataclasses import dataclass
    from decimal import Decimal
    from datetime import datetime
    from aragora.connectors.model_base import ConnectorDataclass

    @dataclass
    class Invoice(ConnectorDataclass):
        id: str
        amount: Decimal
        created_at: datetime
        status: InvoiceStatus

        # Optional: map Python field names to external API field names
        _field_mapping = {"created_at": "createdAt"}

    # Serialize
    invoice = Invoice(id="inv-1", amount=Decimal("99.99"), ...)
    data = invoice.to_dict()  # {"id": "inv-1", "amount": "99.99", "createdAt": "..."}

    # Deserialize
    restored = Invoice.from_dict(data)
"""

from __future__ import annotations

import logging
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="ConnectorDataclass")


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON/API export.

    Handles connector-specific types:
    - Decimal -> str (preserves precision)
    - datetime -> ISO8601 string (timezone-aware)
    - Enum -> value
    - Nested dataclass -> recursive to_dict()
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime):
        # Ensure timezone-aware for consistent format
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value) and hasattr(value, "to_dict"):
        return value.to_dict()

    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]

    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}

    if isinstance(value, (set, frozenset)):
        return [_serialize_value(v) for v in value]

    # Fallback: return as-is (str, int, float, bool, bytes)
    return value


def _deserialize_value(value: Any, target_type: Any) -> Any:
    """Deserialize a value to a target type.

    Handles connector-specific types:
    - str -> Decimal (for financial fields)
    - str -> datetime (ISO8601 parsing)
    - str/value -> Enum
    """
    if value is None:
        return None

    # Handle X | None by extracting X
    origin = getattr(target_type, "__origin__", None)
    if origin is type(None):
        return None
    if origin:
        args = getattr(target_type, "__args__", ())
        for arg in args:
            if arg is not type(None):
                target_type = arg
                break

    # Decimal reconstruction
    if target_type is Decimal:
        if isinstance(value, (str, int, float)):
            return Decimal(str(value))
        return value

    # Datetime reconstruction
    if target_type is datetime:
        if isinstance(value, str):
            # Handle Z suffix
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return value

    # Enum reconstruction
    if isinstance(target_type, type) and issubclass(target_type, Enum):
        if isinstance(value, str):
            for member in target_type:
                if member.value == value or member.name == value:
                    return member
        return value

    # Dataclass reconstruction
    if (
        isinstance(target_type, type)
        and is_dataclass(target_type)
        and hasattr(target_type, "from_dict")
        and isinstance(value, dict)
    ):
        return target_type.from_dict(value)

    # List reconstruction
    if origin in (list, tuple):
        args = getattr(target_type, "__args__", ())
        if args and isinstance(value, list):
            item_type = args[0]
            return [_deserialize_value(v, item_type) for v in value]

    return value


class ConnectorDataclass:
    """Base class for connector data models with unified serialization.

    Provides consistent to_dict/from_dict methods that handle:
    - Financial types (Decimal)
    - Datetime with timezone handling
    - Enum serialization
    - Nested models
    - Field name mapping for external APIs

    Subclasses should use the @dataclass decorator.

    Configuration (optional):
        _exclude_fields: Set of field names to exclude from serialization
        _field_mapping: Dict mapping Python field names to external API field names
        _include_none: Whether to include None values in output (default: False)
    """

    # Optional configuration - subclasses can override
    _exclude_fields: ClassVar[set[str]] = set()
    _field_mapping: ClassVar[dict[str, str]] = {}
    _include_none: ClassVar[bool] = False

    def to_dict(
        self,
        exclude: set[str] | None = None,
        use_api_names: bool = False,
    ) -> dict[str, Any]:
        """Serialize the model to a JSON-compatible dictionary.

        Args:
            exclude: Additional field names to exclude.
            use_api_names: If True, use API field names from _field_mapping.

        Returns:
            Dictionary with serialized values.
        """
        if not is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} must be decorated with @dataclass")

        exclude_set = set(self._exclude_fields)
        if exclude:
            exclude_set |= exclude

        result = {}
        for f in fields(self):
            if f.name in exclude_set:
                continue
            if f.name.startswith("_"):
                continue  # Skip private fields

            value = getattr(self, f.name)

            # Skip None values unless configured to include them
            if value is None and not self._include_none:
                continue

            # Serialize the value
            serialized = _serialize_value(value)

            # Apply field name mapping if requested
            if use_api_names:
                field_name = self._field_mapping.get(f.name, f.name)
            else:
                field_name = f.name

            result[field_name] = serialized

        return result

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any], from_api: bool = False) -> T:
        """Reconstruct a model instance from a dictionary.

        Args:
            data: Dictionary with serialized values.
            from_api: If True, map API field names back to Python field names.

        Returns:
            New instance of the model.
        """
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be decorated with @dataclass")

        # Build reverse mapping for API names
        if from_api and cls._field_mapping:
            reverse_mapping = {v: k for k, v in cls._field_mapping.items()}
            data = {reverse_mapping.get(k, k): v for k, v in data.items()}

        # Get type hints for proper deserialization
        try:
            hints = {}
            for f in fields(cls):
                hints[f.name] = f.type
        except (TypeError, AttributeError):
            hints = {}

        kwargs = {}
        for f in fields(cls):
            if f.name not in data:
                continue

            value = data[f.name]
            target_type = hints.get(f.name, Any)

            # Deserialize the value
            kwargs[f.name] = _deserialize_value(value, target_type)

        return cls(**kwargs)

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize using API field names (convenience method).

        Returns:
            Dictionary with API-compatible field names.
        """
        return self.to_dict(use_api_names=True)

    @classmethod
    def from_api_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Deserialize from API field names (convenience method).

        Args:
            data: Dictionary with API field names.

        Returns:
            New instance of the model.
        """
        return cls.from_dict(data, from_api=True)

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Update the model's fields from a dictionary.

        Only updates fields that exist in the data and are not excluded.

        Args:
            data: Dictionary with new values.
        """
        if not is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} must be decorated with @dataclass")

        try:
            hints = {}
            for f in fields(self):
                hints[f.name] = f.type
        except (TypeError, AttributeError):
            hints = {}

        for f in fields(self):
            if f.name not in data:
                continue
            if f.name in self._exclude_fields:
                continue
            if f.name.startswith("_"):
                continue

            value = data[f.name]
            target_type = hints.get(f.name, Any)
            deserialized = _deserialize_value(value, target_type)
            setattr(self, f.name, deserialized)


__all__ = ["ConnectorDataclass"]
