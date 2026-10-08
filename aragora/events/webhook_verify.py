"""
Webhook Signature Verification Utilities.

Provides utilities for verifying webhook signatures and preventing replay attacks.
Can be used standalone by webhook consumers.

Example usage:
    from aragora.events.webhook_verify import verify_webhook_request

    @app.post("/webhook")
    def handle_webhook(request):
        is_valid, error = verify_webhook_request(
            payload=request.get_data(),
            signature=request.headers.get("X-Aragora-Signature"),
            timestamp=request.headers.get("X-Aragora-Timestamp"),
            secret=WEBHOOK_SECRET,
        )

        if not is_valid:
            return {"error": error}, 401

        # Process the webhook
        data = json.loads(request.get_data())
        ...
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass

from aragora.security.webhook_signing import generate_signature

# Default tolerance for timestamp validation (5 minutes)
DEFAULT_TIMESTAMP_TOLERANCE_SECONDS = 300


@dataclass
class VerificationResult:
    """Result of webhook verification."""

    valid: bool
    error: str | None = None

    def __bool__(self) -> bool:
        return self.valid


def verify_signature(payload: str, signature: str, secret: str) -> bool:
    """
    Verify webhook signature.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        payload: JSON string payload
        signature: Signature header value (sha256=...)
        secret: Webhook secret key

    Returns:
        True if signature is valid
    """
    if not signature or not signature.startswith("sha256="):
        return False

    expected = generate_signature(payload, secret)
    return hmac.compare_digest(signature, expected)


def verify_timestamp(
    timestamp: str | int | float,
    tolerance_seconds: float = DEFAULT_TIMESTAMP_TOLERANCE_SECONDS,
) -> tuple[bool, str | None]:
    """
    Verify webhook timestamp to prevent replay attacks.

    Args:
        timestamp: Unix timestamp from X-Aragora-Timestamp header
        tolerance_seconds: Maximum age allowed (default: 5 minutes)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False, "Invalid timestamp format"

    now = time.time()

    # Check if timestamp is in the future (with small tolerance for clock skew)
    if ts > now + 60:  # 1 minute tolerance for future
        return False, "Timestamp is in the future"

    # Check if timestamp is too old
    age = now - ts
    if age > tolerance_seconds:
        return False, f"Timestamp too old ({age:.0f}s > {tolerance_seconds}s)"

    return True, None


def verify_webhook_request(
    payload: str | bytes,
    signature: str | None,
    timestamp: str | int | float | None = None,
    secret: str = "",
    check_timestamp: bool = True,
    timestamp_tolerance: float = DEFAULT_TIMESTAMP_TOLERANCE_SECONDS,
) -> VerificationResult:
    """
    Verify a complete webhook request.

    Performs signature verification and optional timestamp validation
    to protect against replay attacks.

    Args:
        payload: Raw request body (bytes or string)
        signature: X-Aragora-Signature header value
        timestamp: X-Aragora-Timestamp header value (optional if check_timestamp=False)
        secret: Webhook secret key
        check_timestamp: Whether to validate timestamp (recommended: True)
        timestamp_tolerance: Maximum age for timestamp (default: 5 minutes)

    Returns:
        VerificationResult with valid status and optional error message

    Example:
        result = verify_webhook_request(
            payload=request.get_data(),
            signature=request.headers.get("X-Aragora-Signature"),
            timestamp=request.headers.get("X-Aragora-Timestamp"),
            secret="whsec_xxx",
        )

        if not result:
            return {"error": result.error}, 401
    """
    # Validate inputs
    if not secret:
        return VerificationResult(False, "Secret key is required")

    if not signature:
        return VerificationResult(False, "Missing signature header")

    # Convert bytes to string if needed
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return VerificationResult(False, "Invalid payload encoding")

    # Check timestamp if enabled
    if check_timestamp:
        if timestamp is None:
            return VerificationResult(False, "Missing timestamp header")

        ts_valid, ts_error = verify_timestamp(timestamp, timestamp_tolerance)
        if not ts_valid:
            return VerificationResult(False, f"Timestamp validation failed: {ts_error}")

    # Verify signature
    if not verify_signature(payload, signature, secret):
        return VerificationResult(False, "Invalid signature")

    return VerificationResult(True)


def create_test_webhook_payload(
    event_type: str,
    data: dict,
    secret: str,
) -> tuple[dict, dict]:
    """
    Create a test webhook payload with valid signature for testing.

    Args:
        event_type: Event type (e.g., "debate_end")
        data: Event data
        secret: Webhook secret

    Returns:
        Tuple of (payload_dict, headers_dict)

    Example:
        payload, headers = create_test_webhook_payload(
            "debate_end",
            {"debate_id": "123"},
            "whsec_test",
        )

        # Use in tests
        response = client.post(
            "/webhook",
            json=payload,
            headers=headers,
        )
    """
    import json
    import uuid

    timestamp = int(time.time())

    payload = {
        "event": event_type,
        "timestamp": timestamp,
        "delivery_id": f"del_{uuid.uuid4().hex[:12]}",
        "data": data,
    }

    payload_json = json.dumps(payload)
    signature = generate_signature(payload_json, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Aragora-Signature": signature,
        "X-Aragora-Event": event_type,
        "X-Aragora-Timestamp": str(timestamp),
        "X-Aragora-Delivery": payload["delivery_id"],
    }

    return payload, headers


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "VerificationResult",
    "generate_signature",
    "verify_signature",
    "verify_timestamp",
    "verify_webhook_request",
    "create_test_webhook_payload",
    "DEFAULT_TIMESTAMP_TOLERANCE_SECONDS",
]
