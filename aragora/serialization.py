"""
Serialization utilities for Aragora dataclasses.

Provides SerializableMixin for consistent serialization/deserialization
across all dataclasses in the codebase. Handles common patterns:
- Datetime → ISO format
- Enum → value
- Nested dataclasses → recursive to_dict()
- Optional field exclusion

Usage:
    from dataclasses import dataclass
    from datetime import datetime
    from aragora.serialization import SerializableMixin

    @dataclass
    class MyData(SerializableMixin):
        name: str
        created_at: datetime
        status: MyEnum

    # Serialize
    data = MyData(name="test", created_at=datetime.now(), status=MyEnum.ACTIVE)
    json_dict = data.to_dict()
    # {"name": "test", "created_at": "2024-01-01T12:00:00+00:00", "status": "active"}

    # Deserialize
    restored = MyData.from_dict(json_dict)
"""

from __future__ import annotations

import logging
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, TypeVar, get_type_hints

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="SerializableMixin")


def serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON export.

    Handles:
    - None → None
    - datetime → ISO format string (with UTC if no timezone)
    - Enum → value
    - Dataclass with to_dict() → recursive serialization
    - List/tuple → recursive serialization of items
    - Dict → recursive serialization of values

    Args:
        value: Any value to serialize

    Returns:
        JSON-serializable value
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        # Ensure timezone-aware for consistent ISO format
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    # Fallback: return as-is (str, int, float, bool, etc.)
    return value


def deserialize_value(value: Any, target_type: Any) -> Any:
    """Deserialize a value to a target type.

    Handles:
    - str → datetime (if target_type is datetime)
    - str/value → Enum (if target_type is Enum subclass)
    - dict → dataclass with from_dict() (if target_type has from_dict)

    Args:
        value: Value to deserialize
        target_type: Target Python type

    Returns:
        Deserialized value
    """
    if value is None:
        return None

    # Handle X | None by extracting X
    origin = getattr(target_type, "__origin__", None)
    if origin is type(None):
        return None
    if origin:
        # For Optional/Union, get the first non-None argument
        args = getattr(target_type, "__args__", ())
        for arg in args:
            if arg is not type(None):
                target_type = arg
                break

    # Datetime reconstruction
    if target_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)

    # Enum reconstruction
    if isinstance(target_type, type) and issubclass(target_type, Enum):
        if isinstance(value, str):
            # Try to find matching enum value
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

    return value


class SerializableMixin:
    """Mixin providing consistent serialization for dataclasses.

    Subclasses should be decorated with @dataclass. The mixin provides:
    - to_dict(): Serialize to JSON-compatible dictionary
    - from_dict(): Reconstruct from dictionary

    Configuration:
    - _exclude_fields: Tuple of field names to exclude from serialization
    - _custom_serializers: Dict mapping field names to custom serializer functions

    Example:
        @dataclass
        class User(SerializableMixin):
            name: str
            email: str
            password_hash: str
            created_at: datetime

            _exclude_fields = ("password_hash",)  # Never serialize password

        user = User(
            name="Alice",
            email="alice@example.com",
            password_hash="abc123",
            created_at=datetime.now(),
        )
        data = user.to_dict()
        # {"name": "Alice", "email": "alice@example.com", "created_at": "..."}
    """

    # Fields to exclude from serialization (override in subclass)
    _exclude_fields: ClassVar[tuple[str, ...]] = ()

    # Custom serializers for specific fields (override in subclass)
    # Maps field_name -> callable(value) -> serialized_value
    _custom_serializers: ClassVar[dict[str, Any]] = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary with consistent datetime/enum handling.

        Returns:
            JSON-compatible dictionary representation

        Raises:
            TypeError: If the class is not a dataclass
        """
        if not is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} must be a dataclass")

        result: dict[str, Any] = {}
        for f in fields(self):
            # Skip excluded fields
            if f.name in self._exclude_fields:
                continue
            # Skip private fields (starting with _)
            if f.name.startswith("_"):
                continue

            value = getattr(self, f.name)

            # Apply custom serializer if defined
            if f.name in self._custom_serializers:
                serializer = self._custom_serializers[f.name]
                value = serializer(value)
            else:
                value = serialize_value(value)

            result[f.name] = value

        return result

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with field values

        Returns:
            New instance of the class

        Raises:
            TypeError: If the class is not a dataclass
        """
        if not is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be a dataclass")

        # Get type hints for field type detection
        try:
            hints = get_type_hints(cls)
        except (NameError, AttributeError, TypeError):
            # Forward references or missing imports - fall back to no type hints
            hints = {}

        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue

            value = data[f.name]
            target_type = hints.get(f.name, Any)

            # Deserialize the value based on type hint
            kwargs[f.name] = deserialize_value(value, target_type)

        return cls(**kwargs)


def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Utility function to serialize any dataclass to dict.

    Works with dataclasses that don't inherit from SerializableMixin.
    Useful for one-off serialization without modifying class hierarchy.

    Args:
        obj: Dataclass instance to serialize

    Returns:
        JSON-compatible dictionary

    Raises:
        TypeError: If obj is not a dataclass instance
    """
    if not is_dataclass(obj):
        raise TypeError(f"{type(obj).__name__} is not a dataclass")

    result: dict[str, Any] = {}
    for f in fields(obj):
        if f.name.startswith("_"):
            continue
        result[f.name] = serialize_value(getattr(obj, f.name))
    return result


def dict_to_dataclass(cls: type[T], data: dict[str, Any]) -> T:
    """Utility function to deserialize dict to any dataclass.

    Works with dataclasses that don't inherit from SerializableMixin.

    Args:
        cls: Target dataclass type
        data: Dictionary with field values

    Returns:
        New instance of cls

    Raises:
        TypeError: If cls is not a dataclass
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} is not a dataclass")

    try:
        hints = get_type_hints(cls)
    except (NameError, AttributeError, TypeError) as e:
        # Forward references, missing imports, or complex generics can cause these errors
        logger.debug("Failed to get type hints for %s: %s: %s", cls.__name__, type(e).__name__, e)
        hints = {}

    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        target_type = hints.get(f.name, Any)
        kwargs[f.name] = deserialize_value(data[f.name], target_type)

    return cls(**kwargs)


__all__ = [
    "SerializableMixin",
    "serialize_value",
    "deserialize_value",
    "dataclass_to_dict",
    "dict_to_dataclass",
]
