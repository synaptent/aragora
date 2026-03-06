"""
Encryption wrapper for sensitive storage fields.

Provides a unified interface for encrypting/decrypting sensitive data
in storage layers (integration configs, OAuth tokens, webhook secrets).

Usage:
    from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

    # Before saving to database:
    encrypted_data = encrypt_sensitive(config_dict, record_id="user_123")

    # After loading from database:
    decrypted_data = decrypt_sensitive(encrypted_data, record_id="user_123")
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Fields that should always be encrypted when present
SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        # OAuth and API tokens
        "access_token",
        "refresh_token",
        "api_key",
        "auth_token",
        "bot_token",
        "bearer_token",
        # Secrets and passwords
        "secret",
        "password",
        "client_secret",
        "signing_secret",
        # MFA secrets
        "mfa_secret",
        "mfa_backup_codes",
        "totp_secret",
        # Platform-specific credentials
        "webhook_url",  # May contain tokens in URL
        "webhook_secret",
        "sendgrid_api_key",
        "ses_secret_access_key",
        "twilio_auth_token",
        "smtp_password",
        "slack_signing_secret",
        "discord_token",
        "telegram_token",
        "github_token",
        "private_key",
        "encryption_key",
    }
)


def _get_encryption_service():
    """Lazily import and get encryption service to avoid circular imports."""
    from aragora.security import get_encryption_service

    return get_encryption_service()


def is_encryption_available() -> bool:
    """Check if encryption is available (cryptography library installed)."""
    try:
        from aragora.security.encryption import CRYPTO_AVAILABLE

        return CRYPTO_AVAILABLE
    except ImportError:
        return False


def is_encryption_configured() -> bool:
    """Check if a persistent encryption key is configured."""
    return bool(os.environ.get("ARAGORA_ENCRYPTION_KEY"))


def encrypt_sensitive(
    data: dict[str, Any],
    record_id: str | None = None,
    additional_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Encrypt sensitive fields in a dictionary before storage.

    Uses AES-256-GCM encryption with the configured master key.
    Fields are marked with {"_encrypted": True, "_value": "base64..."}.

    Args:
        data: Dictionary containing data to encrypt
        record_id: Optional identifier for AAD (associated authenticated data).
                   Using record_id prevents encrypted values from being
                   moved between records.
        additional_fields: Extra field names to encrypt beyond SENSITIVE_FIELDS

    Returns:
        Dictionary with sensitive fields encrypted

    Note:
        If encryption is not available or no data needs encryption,
        returns the original data unchanged.
    """
    if not data:
        return data

    if not is_encryption_available():
        logger.debug("Encryption not available, storing fields as-is")
        return data

    # Determine which fields to encrypt
    fields_to_encrypt = SENSITIVE_FIELDS
    if additional_fields:
        fields_to_encrypt = fields_to_encrypt | additional_fields

    # Find fields that exist in data and need encryption
    present_sensitive_fields = [
        field for field in fields_to_encrypt if field in data and data[field] is not None
    ]

    if not present_sensitive_fields:
        return data

    try:
        service = _get_encryption_service()
        return service.encrypt_fields(
            record=data,
            sensitive_fields=present_sensitive_fields,
            associated_data=record_id,
        )
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Failed to encrypt sensitive fields: %s", e)
        # In case of encryption failure, don't store unencrypted
        raise EncryptionError(f"Failed to encrypt data: {e}") from e


def decrypt_sensitive(
    data: dict[str, Any],
    record_id: str | None = None,
    additional_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Decrypt sensitive fields in a dictionary after retrieval.

    Args:
        data: Dictionary containing encrypted data
        record_id: Optional identifier used as AAD during encryption.
                   Must match the value used during encryption.
        additional_fields: Extra field names to check for decryption

    Returns:
        Dictionary with sensitive fields decrypted

    Note:
        Fields that are not encrypted (no {"_encrypted": True} marker)
        are returned unchanged.
    """
    if not data:
        return data

    if not is_encryption_available():
        return data

    # Determine which fields to check for decryption
    fields_to_decrypt = SENSITIVE_FIELDS
    if additional_fields:
        fields_to_decrypt = fields_to_decrypt | additional_fields

    # Find fields that are encrypted
    encrypted_fields = [
        field
        for field in fields_to_decrypt
        if field in data and isinstance(data[field], dict) and data[field].get("_encrypted") is True
    ]

    if not encrypted_fields:
        return data

    try:
        service = _get_encryption_service()
        return service.decrypt_fields(
            record=data,
            sensitive_fields=encrypted_fields,
            associated_data=record_id,
        )
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Failed to decrypt sensitive fields: %s", e)
        raise DecryptionError(f"Failed to decrypt data: {e}") from e
    except Exception as e:  # noqa: BLE001 - cryptography errors (InvalidTag) don't subclass standard types
        logger.error("Failed to decrypt sensitive fields (crypto error): %s", e)
        raise DecryptionError(f"Failed to decrypt data: {e}") from e


def is_field_encrypted(data: dict[str, Any], field_name: str) -> bool:
    """Check if a specific field is encrypted."""
    if field_name not in data:
        return False
    value = data[field_name]
    return isinstance(value, dict) and value.get("_encrypted") is True


def get_encrypted_field_names(data: dict[str, Any]) -> list[str]:
    """Get list of field names that are currently encrypted."""
    return [
        key
        for key, value in data.items()
        if isinstance(value, dict) and value.get("_encrypted") is True
    ]


def encrypt_by_classification(
    data: dict[str, Any],
    classification_level: str,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Encrypt data fields based on classification level.

    If the classification level is ``CONFIDENTIAL``, ``RESTRICTED``, or ``PII``,
    all string values in *data* are encrypted.  For lower levels the data is
    returned unchanged.

    Args:
        data: Dictionary of data to potentially encrypt.
        classification_level: Classification level string (e.g. ``"confidential"``).
        record_id: Optional record ID for AAD binding.

    Returns:
        Dictionary with string values encrypted when required, plus an
        ``_encrypted: True`` marker.  If encryption is not available but
        required, a warning is logged and the data is returned as-is.
    """
    if not data:
        return data

    sensitive_levels = {"confidential", "restricted", "pii"}
    if classification_level.lower() not in sensitive_levels:
        return data

    if not is_encryption_available():
        logger.warning(
            "Encryption required for classification level '%s' but cryptography library "
            "is not available — storing data unencrypted",
            classification_level,
        )
        return data

    try:
        service = _get_encryption_service()
        # Encrypt all string-valued fields
        string_fields = [k for k, v in data.items() if isinstance(v, str) and not k.startswith("_")]
        if not string_fields:
            return data

        encrypted = service.encrypt_fields(
            record=data,
            sensitive_fields=string_fields,
            associated_data=record_id,
        )
        encrypted["_encrypted"] = True
        return encrypted
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Failed to encrypt by classification: %s", e)
        raise EncryptionError(f"Classification-based encryption failed: {e}") from e


class EncryptionError(Exception):
    """Raised when encryption fails."""

    pass


class DecryptionError(Exception):
    """Raised when decryption fails."""

    pass


__all__ = [
    "SENSITIVE_FIELDS",
    "encrypt_sensitive",
    "decrypt_sensitive",
    "encrypt_by_classification",
    "is_encryption_available",
    "is_encryption_configured",
    "is_field_encrypted",
    "get_encrypted_field_names",
    "EncryptionError",
    "DecryptionError",
]
