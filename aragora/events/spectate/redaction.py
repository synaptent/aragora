"""PII redaction helpers for spectator-facing event payloads."""

from __future__ import annotations

from typing import Any

from aragora.utils.pii_redactor import PIIRedactor, PIIType

_REDACTABLE_TEXT_KEYS = frozenset(
    {
        "content",
        "description",
        "details",
        "message",
        "reason",
        "summary",
        "task",
        "text",
    }
)

_spectator_redactor = PIIRedactor(
    enabled_types=[
        PIIType.EMAIL,
        PIIType.PHONE,
        PIIType.SSN,
    ],
    log_redactions=False,
)


def redact_spectator_text(value: str) -> str:
    """Redact high-confidence spectator-facing PII from freeform text."""
    return _spectator_redactor.redact(value).redacted_text


def redact_spectator_payload(
    value: Any,
    *,
    key: str | None = None,
    redact_nested: bool = False,
) -> Any:
    """Recursively redact spectator payload fields that carry freeform text."""
    should_redact = redact_nested or key in _REDACTABLE_TEXT_KEYS

    if isinstance(value, dict):
        nested_redaction = should_redact
        return {
            item_key: redact_spectator_payload(
                item_value,
                key=item_key,
                redact_nested=nested_redaction,
            )
            for item_key, item_value in value.items()
        }

    if isinstance(value, list):
        return [
            redact_spectator_payload(
                item,
                key=key,
                redact_nested=should_redact,
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            redact_spectator_payload(
                item,
                key=key,
                redact_nested=should_redact,
            )
            for item in value
        )

    if should_redact and isinstance(value, str):
        return redact_spectator_text(value)

    return value
