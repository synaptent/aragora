"""
Billing Data Models.

Core data structures for user management, organizations, and subscriptions.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from aragora.exceptions import ConfigurationError
from aragora.serialization import SerializableMixin


class MFABypassAuditSink(Protocol):
    """Required audit capability for privileged MFA bypass changes."""

    def __call__(self, admin_id: str, action: str, **kwargs: Any) -> None: ...


_mfa_bypass_audit_sink: MFABypassAuditSink | None = None


def register_mfa_bypass_audit_sink(sink: MFABypassAuditSink) -> None:
    """Register the required MFA bypass audit capability."""
    global _mfa_bypass_audit_sink
    _mfa_bypass_audit_sink = sink


def clear_mfa_bypass_audit_sink() -> None:
    """Clear the audit capability, primarily for isolated tests."""
    global _mfa_bypass_audit_sink
    _mfa_bypass_audit_sink = None


def _audit_mfa_bypass(
    *,
    component: str,
    missing_reason: str,
    admin_id: str,
    action: str,
    target_id: str,
    details: dict[str, Any],
) -> None:
    if _mfa_bypass_audit_sink is None:
        raise ConfigurationError(component=component, reason=missing_reason)
    _mfa_bypass_audit_sink(
        admin_id=admin_id,
        action=action,
        target_type="service_account",
        target_id=target_id,
        details=details,
    )


# Try to import bcrypt for secure password hashing
try:
    import bcrypt

    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

logger = logging.getLogger(__name__)

# Password hash version prefixes for migration support
HASH_VERSION_SHA256 = "sha256:"
HASH_VERSION_BCRYPT = "bcrypt:"
HASH_VERSION_CURRENT = HASH_VERSION_BCRYPT if HAS_BCRYPT else HASH_VERSION_SHA256
BCRYPT_ROUNDS = 12  # Cost factor for bcrypt

# Security: Allow SHA-256 fallback only when explicitly enabled
# Set ARAGORA_ALLOW_INSECURE_PASSWORDS=1 for testing (NOT for production)
# Note: bcrypt is a required dependency, so fallback should never be needed
_insecure_requested = os.environ.get("ARAGORA_ALLOW_INSECURE_PASSWORDS", "").lower() in (
    "1",
    "true",
    "yes",
)
_is_production = os.environ.get("ARAGORA_ENV", "development").lower() in ("production", "staging")
ALLOW_INSECURE_PASSWORDS = _insecure_requested and not _is_production
if _insecure_requested and _is_production:
    logger.warning("ARAGORA_ALLOW_INSECURE_PASSWORDS ignored in production/staging")


class SubscriptionTier(Enum):
    """Available subscription tiers."""

    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


@dataclass
class TierLimits(SerializableMixin):
    """Limits for a subscription tier."""

    debates_per_month: int
    users_per_org: int
    api_access: bool
    all_agents: bool
    custom_agents: bool
    sso_enabled: bool
    audit_logs: bool
    priority_support: bool
    price_monthly_cents: int  # Price in cents

    # Enterprise features
    dedicated_infrastructure: bool = False
    sla_guarantee: bool = False
    compliance_certifications: bool = False  # SOC2, HIPAA-ready

    # to_dict() inherited from SerializableMixin


# Tier configurations
TIER_LIMITS: dict[SubscriptionTier, TierLimits] = {
    SubscriptionTier.FREE: TierLimits(
        debates_per_month=10,
        users_per_org=1,
        api_access=False,
        all_agents=False,
        custom_agents=False,
        sso_enabled=False,
        audit_logs=False,
        priority_support=False,
        price_monthly_cents=0,
    ),
    SubscriptionTier.STARTER: TierLimits(
        debates_per_month=100,
        users_per_org=5,
        api_access=True,
        all_agents=False,
        custom_agents=False,
        sso_enabled=False,
        audit_logs=False,
        priority_support=False,
        price_monthly_cents=2900,  # $29
    ),
    SubscriptionTier.PROFESSIONAL: TierLimits(
        debates_per_month=1000,
        users_per_org=25,
        api_access=True,
        all_agents=True,
        custom_agents=False,
        sso_enabled=False,
        audit_logs=True,
        priority_support=True,
        price_monthly_cents=9900,  # $99
    ),
    SubscriptionTier.ENTERPRISE: TierLimits(
        debates_per_month=999999,  # Unlimited
        users_per_org=999999,
        api_access=True,
        all_agents=True,
        custom_agents=True,
        sso_enabled=True,
        audit_logs=True,
        priority_support=True,
        price_monthly_cents=0,  # Custom pricing
        # Enterprise features
        dedicated_infrastructure=True,
        sla_guarantee=True,
        compliance_certifications=True,
    ),
}


def _hash_password_sha256(password: str, salt: str | None = None) -> tuple[str, str]:
    """
    Legacy SHA-256 password hashing (for backward compatibility).

    Args:
        password: Plain text password
        salt: Optional salt (generated if not provided)

    Returns:
        Tuple of (hash, salt)
    """
    if salt is None:
        salt = secrets.token_hex(32)
    hash_input = f"{salt}{password}".encode()
    password_hash = hashlib.sha256(hash_input).hexdigest()
    return password_hash, salt


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """
    Hash a password using bcrypt.

    In production, bcrypt is REQUIRED. SHA-256 fallback is only allowed
    when ARAGORA_ALLOW_INSECURE_PASSWORDS=1 is set (for testing only).

    Args:
        password: Plain text password
        salt: Optional salt (only used for SHA-256 fallback in dev)

    Returns:
        Tuple of (versioned_hash, salt)
        - For bcrypt: salt is empty string (embedded in hash)
        - For SHA-256: salt is the random salt used

    Raises:
        RuntimeError: If bcrypt is not installed and insecure fallback not enabled
    """
    if HAS_BCRYPT:
        # Use bcrypt (salt is embedded in the hash)
        password_bytes = password.encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
        return f"{HASH_VERSION_BCRYPT}{hashed.decode('utf-8')}", ""
    elif ALLOW_INSECURE_PASSWORDS:
        # Fall back to SHA-256 ONLY in development/testing
        legacy_hash, salt = _hash_password_sha256(password, salt)
        logger.warning(
            "SECURITY WARNING: Using SHA-256 for password hashing. "
            "This is insecure for production. Install bcrypt: pip install bcrypt"
        )
        return f"{HASH_VERSION_SHA256}{legacy_hash}", salt
    else:
        # Production: fail if bcrypt not available
        raise ConfigurationError(
            component="Password Hashing",
            reason="bcrypt is required for secure password hashing but is not installed. "
            "Install it with: pip install bcrypt. "
            "For development/testing only, set ARAGORA_ALLOW_INSECURE_PASSWORDS=1",
        )


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """
    Verify a password against a stored hash with automatic version detection.

    Supports:
    - bcrypt: hashes prefixed with "bcrypt:"
    - sha256: hashes prefixed with "sha256:" or legacy unprefixed 64-char hex

    Args:
        password: Plain text password to verify
        password_hash: Stored hash (may include version prefix)
        salt: Stored salt (used for SHA-256, ignored for bcrypt)

    Returns:
        True if password matches
    """
    if password_hash.startswith(HASH_VERSION_BCRYPT):
        # Modern bcrypt verification
        if not HAS_BCRYPT:
            logger.error("Cannot verify bcrypt hash: bcrypt not installed")
            return False
        stored_hash = password_hash[len(HASH_VERSION_BCRYPT) :].encode("utf-8")
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash)
        except (ValueError, TypeError, RuntimeError) as e:
            logger.error("bcrypt verification failed: %s", e)
            return False

    elif password_hash.startswith(HASH_VERSION_SHA256):
        # Prefixed SHA-256
        actual_hash = password_hash[len(HASH_VERSION_SHA256) :]
        computed_hash, _ = _hash_password_sha256(password, salt)
        return secrets.compare_digest(computed_hash, actual_hash)

    elif len(password_hash) == 64:
        # Legacy unprefixed SHA-256 (64-char hex)
        computed_hash, _ = _hash_password_sha256(password, salt)
        return secrets.compare_digest(computed_hash, password_hash)

    else:
        logger.warning("Unknown password hash format (length=%s)", len(password_hash))
        return False


def needs_rehash(password_hash: str) -> bool:
    """
    Check if a password hash should be upgraded to the current algorithm.

    Call this after successful password verification to determine if
    the hash should be updated. This enables transparent migration
    from SHA-256 to bcrypt.

    Args:
        password_hash: The stored password hash

    Returns:
        True if hash should be regenerated with current algorithm
    """
    if not password_hash:
        return True

    # If bcrypt is available and hash isn't bcrypt, it needs rehash
    if HAS_BCRYPT and not password_hash.startswith(HASH_VERSION_BCRYPT):
        return True

    # If bcrypt isn't available but hash is bcrypt, can't rehash (keep as-is)
    if not HAS_BCRYPT and password_hash.startswith(HASH_VERSION_BCRYPT):
        return False

    return False


@dataclass
class User:
    """A user account."""

    id: str = field(default_factory=lambda: str(uuid4()))
    email: str = ""
    password_hash: str = ""
    password_salt: str = ""
    name: str = ""
    org_id: str | None = None
    role: str = "member"  # owner, admin, member
    is_active: bool = True
    email_verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: datetime | None = None

    # API access (secure storage: hash + prefix for identification)
    api_key_hash: str | None = None  # SHA-256 hash of the key
    api_key_prefix: str | None = None  # First 12 chars for identification (ara_xxxx...)
    api_key_created_at: datetime | None = None
    api_key_expires_at: datetime | None = None  # Expiration time
    api_key_bound_ips: str | None = None  # Comma-separated IPs/CIDRs for IP binding

    # MFA/2FA fields
    mfa_secret: str | None = None  # TOTP secret (encrypted)
    mfa_enabled: bool = False
    mfa_backup_codes: str | None = None  # JSON-encoded list of hashed backup codes

    # MFA grace period tracking for newly promoted admins
    # When a user is promoted to admin, this is set to track when MFA setup must be completed
    mfa_grace_period_started_at: datetime | None = None

    # Token revocation - increment to invalidate all existing tokens
    token_version: int = 1

    # Service account fields for programmatic access without MFA
    is_service_account: bool = False  # Machine/bot account indicator
    service_account_created_by: str | None = None  # User ID who created this service account
    service_account_scopes: str | None = None  # JSON list of allowed scopes

    # MFA bypass tracking for service accounts
    mfa_bypass_reason: str | None = None  # 'service_account', 'api_integration'
    mfa_bypass_approved_by: str | None = None  # User ID who approved bypass
    mfa_bypass_approved_at: datetime | None = None  # When bypass was approved
    mfa_bypass_expires_at: datetime | None = None  # Auto-expire bypass (security)

    def set_password(self, password: str) -> None:
        """Set user password."""
        self.password_hash, self.password_salt = hash_password(password)
        self.updated_at = datetime.now(timezone.utc)

    def verify_password(self, password: str) -> bool:
        """Verify user password."""
        return verify_password(password, self.password_hash, self.password_salt)

    def needs_password_rehash(self) -> bool:
        """Check if password hash should be upgraded to current algorithm."""
        return needs_rehash(self.password_hash)

    def upgrade_password_hash(self, password: str) -> bool:
        """
        Upgrade password hash to current algorithm if needed.

        Call this after successful password verification to transparently
        migrate from SHA-256 to bcrypt.

        Args:
            password: The verified plaintext password

        Returns:
            True if hash was upgraded, False if no upgrade needed
        """
        if not self.needs_password_rehash():
            return False
        self.password_hash, self.password_salt = hash_password(password)
        self.updated_at = datetime.now(timezone.utc)
        logger.info("Password hash upgraded for user %s", self.id)
        return True

    def generate_api_key(self, expires_days: int = 365, bound_ips: str | None = None) -> str:
        """
        Generate a new API key for this user.

        The plaintext key is returned once and never stored. Only the
        SHA-256 hash is persisted for verification.

        Args:
            expires_days: Days until key expires (default 365)
            bound_ips: Optional comma-separated IPs/CIDRs to restrict key usage

        Returns:
            The plaintext API key (only returned once, never stored)
        """
        api_key = f"ara_{secrets.token_urlsafe(32)}"

        # Store hash, not plaintext
        self.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self.api_key_prefix = api_key[:12]  # "ara_" + 8 chars for identification
        self.api_key_created_at = datetime.now(timezone.utc)
        self.api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
        self.api_key_bound_ips = bound_ips
        self.updated_at = datetime.now(timezone.utc)

        return api_key  # Returned to user once, never stored

    def verify_api_key(self, api_key: str, client_ip: str | None = None) -> bool:
        """
        Verify an API key against stored hash.

        Checks hash match, expiration, and optional IP binding.

        Args:
            api_key: The plaintext API key to verify
            client_ip: Optional client IP to check against bound IPs

        Returns:
            True if key is valid, not expired, and IP allowed
        """
        if not self.api_key_hash:
            return False

        # Check expiration
        if self.api_key_expires_at and datetime.now(timezone.utc) > self.api_key_expires_at:
            logger.debug("API key expired for user %s", self.id)
            return False

        # Verify hash
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if not secrets.compare_digest(key_hash, self.api_key_hash):
            return False

        # Check IP binding if configured
        if self.api_key_bound_ips and client_ip:
            import ipaddress

            try:
                client = ipaddress.ip_address(client_ip)
                allowed = False
                for entry in self.api_key_bound_ips.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    if "/" in entry:
                        if client in ipaddress.ip_network(entry, strict=False):
                            allowed = True
                            break
                    elif client == ipaddress.ip_address(entry):
                        allowed = True
                        break
                if not allowed:
                    logger.warning(
                        "API key IP binding rejected: client_ip=%s not in bound_ips for user %s",
                        client_ip,
                        self.id,
                    )
                    return False
            except ValueError:
                logger.warning("Invalid IP in binding check: %s", client_ip)
                return False

        return True

    def is_api_key_expired(self) -> bool:
        """Check if API key is expired."""
        if not self.api_key_expires_at:
            return False
        return datetime.now(timezone.utc) > self.api_key_expires_at

    def revoke_api_key(self) -> None:
        """Revoke the user's API key."""
        self.api_key_hash = None
        self.api_key_prefix = None
        self.api_key_created_at = None
        self.api_key_expires_at = None
        self.api_key_bound_ips = None
        self.updated_at = datetime.now(timezone.utc)

    def promote_to_admin(self, new_role: str = "admin") -> None:
        """
        Promote user to admin role and start MFA grace period.

        Sets mfa_grace_period_started_at to current time so the user
        has a window to set up MFA before enforcement kicks in.

        Args:
            new_role: The admin role to assign (admin, owner, superadmin)
        """
        admin_roles = {"admin", "owner", "superadmin"}
        if new_role not in admin_roles:
            raise ValueError(f"Invalid admin role: {new_role}. Must be one of {admin_roles}")

        was_admin = self.role in admin_roles
        self.role = new_role
        self.updated_at = datetime.now(timezone.utc)

        # Start MFA grace period if newly promoted to admin
        if not was_admin and not self.mfa_enabled:
            self.mfa_grace_period_started_at = datetime.now(timezone.utc)
            logger.info(
                "User %s promoted to %s. MFA grace period started at %s",
                self.id,
                new_role,
                self.mfa_grace_period_started_at,
            )

    def clear_mfa_grace_period(self) -> None:
        """Clear the MFA grace period (called when MFA is enabled)."""
        self.mfa_grace_period_started_at = None
        self.updated_at = datetime.now(timezone.utc)

    def get_service_account_scopes(self) -> list[str]:
        """Get list of scopes for service account."""
        import json

        if not self.service_account_scopes:
            return []
        try:
            return json.loads(self.service_account_scopes)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "Failed to parse service_account_scopes for user %s: %s",
                self.id,
                e,
            )
            return []

    def set_service_account_scopes(self, scopes: list[str]) -> None:
        """Set scopes for service account."""
        import json

        self.service_account_scopes = json.dumps(scopes)
        self.updated_at = datetime.now(timezone.utc)

    def has_scope(self, scope: str) -> bool:
        """Check if service account has a specific scope."""
        if not self.is_service_account:
            return True  # Non-service accounts have all scopes
        return scope in self.get_service_account_scopes()

    def is_mfa_bypass_valid(self) -> bool:
        """Check if MFA bypass is still valid (not expired)."""
        if not self.is_service_account:
            return False
        if not self.mfa_bypass_approved_at:
            return False
        if self.mfa_bypass_expires_at:
            return datetime.now(timezone.utc) < self.mfa_bypass_expires_at
        return True  # No expiration set, bypass is valid

    def approve_mfa_bypass(
        self,
        approved_by: str,
        reason: str = "service_account",
        expires_days: int = 90,
    ) -> None:
        """
        Approve MFA bypass for this service account.

        Args:
            approved_by: User ID of the approver (must be admin)
            reason: Reason for bypass ('service_account', 'api_integration')
            expires_days: Days until bypass expires (default: 90)
        """
        if not self.is_service_account:
            raise ValueError("MFA bypass can only be approved for service accounts")

        approved_at = datetime.now(timezone.utc)
        expires_at = approved_at + timedelta(days=expires_days)
        _audit_mfa_bypass(
            component="MFA Bypass Approval Audit",
            missing_reason=(
                "aragora.audit.unified.audit_admin is required to approve MFA bypasses"
            ),
            admin_id=approved_by,
            action="mfa_bypass_approved",
            target_id=str(self.id),
            details={"reason": reason, "expires_days": expires_days},
        )

        self.mfa_bypass_reason = reason
        self.mfa_bypass_approved_by = approved_by
        self.mfa_bypass_approved_at = approved_at
        self.mfa_bypass_expires_at = expires_at
        self.updated_at = datetime.now(timezone.utc)

        logger.info(
            "MFA bypass approved for service account %s by %s. Expires: %s",
            self.id,
            approved_by,
            self.mfa_bypass_expires_at,
        )

    def revoke_mfa_bypass(self, revoked_by: str, reason: str = "manual_revocation") -> None:
        """Revoke MFA bypass for this service account."""
        if not self.is_service_account:
            raise ValueError("MFA bypass can only be revoked for service accounts")
        previous_approved_by = self.mfa_bypass_approved_by
        _audit_mfa_bypass(
            component="MFA Bypass Revocation Audit",
            missing_reason=("aragora.audit.unified.audit_admin is required to revoke MFA bypasses"),
            admin_id=revoked_by,
            action="mfa_bypass_revoked",
            target_id=str(self.id),
            details={"reason": reason, "previous_approved_by": previous_approved_by},
        )

        self.mfa_bypass_approved_at = None
        self.mfa_bypass_approved_by = None
        self.mfa_bypass_expires_at = None
        self.mfa_bypass_reason = None
        self.updated_at = datetime.now(timezone.utc)
        logger.info(
            "MFA bypass revoked for service account %s by %s. Reason: %s. Previously approved by: %s",
            self.id,
            revoked_by,
            reason,
            previous_approved_by,
        )

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        data = {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "org_id": self.org_id,
            "role": self.role,
            "is_active": self.is_active,
            "email_verified": self.email_verified,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "has_api_key": self.api_key_hash is not None,
            "token_version": self.token_version,
            "mfa_enabled": self.mfa_enabled,
            "mfa_grace_period_started_at": (
                self.mfa_grace_period_started_at.isoformat()
                if self.mfa_grace_period_started_at
                else None
            ),
            # Service account fields
            "is_service_account": self.is_service_account,
            "service_account_scopes": self.get_service_account_scopes(),
        }
        if include_sensitive:
            data["api_key_prefix"] = self.api_key_prefix
            # Include MFA bypass info for service accounts
            if self.is_service_account:
                data["mfa_bypass_reason"] = self.mfa_bypass_reason
                data["mfa_bypass_approved_by"] = self.mfa_bypass_approved_by
                data["mfa_bypass_approved_at"] = (
                    self.mfa_bypass_approved_at.isoformat() if self.mfa_bypass_approved_at else None
                )
                data["mfa_bypass_expires_at"] = (
                    self.mfa_bypass_expires_at.isoformat() if self.mfa_bypass_expires_at else None
                )
                data["service_account_created_by"] = self.service_account_created_by
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        """Create from dictionary."""
        import json

        user = cls(
            id=data.get("id", str(uuid4())),
            email=data.get("email", ""),
            password_hash=data.get("password_hash", ""),
            password_salt=data.get("password_salt", ""),
            name=data.get("name", ""),
            org_id=data.get("org_id"),
            role=data.get("role", "member"),
            is_active=data.get("is_active", True),
            email_verified=data.get("email_verified", False),
            token_version=data.get("token_version", 1),
            is_service_account=data.get("is_service_account", False),
            service_account_created_by=data.get("service_account_created_by"),
            mfa_bypass_reason=data.get("mfa_bypass_reason"),
            mfa_bypass_approved_by=data.get("mfa_bypass_approved_by"),
        )
        # Handle service_account_scopes (can be list or JSON string)
        scopes = data.get("service_account_scopes")
        if isinstance(scopes, list):
            user.service_account_scopes = json.dumps(scopes)
        elif isinstance(scopes, str):
            user.service_account_scopes = scopes
        # Datetime fields
        if "created_at" in data and data["created_at"]:
            if isinstance(data["created_at"], str):
                user.created_at = datetime.fromisoformat(data["created_at"])
            else:
                user.created_at = data["created_at"]
        if "updated_at" in data and data["updated_at"]:
            if isinstance(data["updated_at"], str):
                user.updated_at = datetime.fromisoformat(data["updated_at"])
            else:
                user.updated_at = data["updated_at"]
        if "last_login_at" in data and data["last_login_at"]:
            if isinstance(data["last_login_at"], str):
                user.last_login_at = datetime.fromisoformat(data["last_login_at"])
            else:
                user.last_login_at = data["last_login_at"]
        if "api_key_created_at" in data and data["api_key_created_at"]:
            if isinstance(data["api_key_created_at"], str):
                user.api_key_created_at = datetime.fromisoformat(data["api_key_created_at"])
            else:
                user.api_key_created_at = data["api_key_created_at"]
        if "mfa_grace_period_started_at" in data and data["mfa_grace_period_started_at"]:
            if isinstance(data["mfa_grace_period_started_at"], str):
                user.mfa_grace_period_started_at = datetime.fromisoformat(
                    data["mfa_grace_period_started_at"]
                )
            else:
                user.mfa_grace_period_started_at = data["mfa_grace_period_started_at"]
        if "mfa_bypass_approved_at" in data and data["mfa_bypass_approved_at"]:
            if isinstance(data["mfa_bypass_approved_at"], str):
                user.mfa_bypass_approved_at = datetime.fromisoformat(data["mfa_bypass_approved_at"])
            else:
                user.mfa_bypass_approved_at = data["mfa_bypass_approved_at"]
        if "mfa_bypass_expires_at" in data and data["mfa_bypass_expires_at"]:
            if isinstance(data["mfa_bypass_expires_at"], str):
                user.mfa_bypass_expires_at = datetime.fromisoformat(data["mfa_bypass_expires_at"])
            else:
                user.mfa_bypass_expires_at = data["mfa_bypass_expires_at"]
        # Load MFA enabled flag
        if "mfa_enabled" in data:
            user.mfa_enabled = data.get("mfa_enabled", False)
        return user


@dataclass
class Organization:
    """An organization (team/company)."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""  # URL-friendly name
    tier: SubscriptionTier = SubscriptionTier.FREE
    owner_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Billing
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    # Usage tracking (reset monthly)
    debates_used_this_month: int = 0
    billing_cycle_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Settings
    settings: dict[str, Any] = field(default_factory=dict)

    # Trial tracking
    trial_started_at: datetime | None = None
    trial_expires_at: datetime | None = None
    trial_debates_limit: int = 10  # Debates allowed during trial
    trial_converted: bool = False  # Whether user upgraded from trial

    @property
    def is_in_trial(self) -> bool:
        """Check if organization is in active trial period."""
        if self.trial_started_at is None or self.trial_expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        return now < self.trial_expires_at and not self.trial_converted

    @property
    def trial_days_remaining(self) -> int:
        """Get number of days remaining in trial."""
        if not self.is_in_trial or self.trial_expires_at is None:
            return 0
        now = datetime.now(timezone.utc)
        remaining = (self.trial_expires_at - now).days
        return max(0, remaining)

    @property
    def trial_debates_remaining(self) -> int:
        """Get remaining trial debates."""
        if not self.is_in_trial:
            return 0
        return max(0, self.trial_debates_limit - self.debates_used_this_month)

    @property
    def is_trial_expired(self) -> bool:
        """Check if trial has expired (was in trial but now past expiration)."""
        if self.trial_started_at is None or self.trial_expires_at is None:
            return False
        if self.trial_converted:
            return False  # Converted users aren't "expired"
        now = datetime.now(timezone.utc)
        return now >= self.trial_expires_at

    def start_trial(self, duration_days: int = 7, debates_limit: int = 10) -> None:
        """Start a new trial for this organization."""
        now = datetime.now(timezone.utc)
        self.trial_started_at = now
        self.trial_expires_at = now + timedelta(days=duration_days)
        self.trial_debates_limit = debates_limit
        self.trial_converted = False
        self.debates_used_this_month = 0
        self.updated_at = now

    def convert_trial(self, new_tier: SubscriptionTier) -> None:
        """Convert trial to paid subscription."""
        self.trial_converted = True
        self.tier = new_tier
        self.updated_at = datetime.now(timezone.utc)

    @property
    def limits(self) -> TierLimits:
        """Get limits for this organization's tier."""
        return TIER_LIMITS[self.tier]

    @property
    def debates_remaining(self) -> int:
        """Get remaining debates this month (respects trial limits)."""
        if self.is_in_trial:
            return self.trial_debates_remaining
        return max(0, self.limits.debates_per_month - self.debates_used_this_month)

    @property
    def is_at_limit(self) -> bool:
        """Check if organization has reached debate limit (respects trial limits)."""
        if self.is_in_trial:
            return self.debates_used_this_month >= self.trial_debates_limit
        return self.debates_used_this_month >= self.limits.debates_per_month

    def increment_debates(self, count: int = 1) -> bool:
        """
        Increment debate count.

        Returns:
            True if successful, False if at limit
        """
        if self.is_at_limit:
            return False
        self.debates_used_this_month += count
        self.updated_at = datetime.now(timezone.utc)
        return True

    def reset_monthly_usage(self) -> None:
        """Reset monthly usage counters."""
        self.debates_used_this_month = 0
        self.billing_cycle_start = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "tier": self.tier.value,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "debates_used_this_month": self.debates_used_this_month,
            "billing_cycle_start": self.billing_cycle_start.isoformat(),
            "debates_remaining": self.debates_remaining,
            "is_at_limit": self.is_at_limit,
            "limits": self.limits.to_dict(),
            "settings": self.settings,
            # Trial information
            "trial_started_at": self.trial_started_at.isoformat()
            if self.trial_started_at
            else None,
            "trial_expires_at": self.trial_expires_at.isoformat()
            if self.trial_expires_at
            else None,
            "trial_debates_limit": self.trial_debates_limit,
            "trial_converted": self.trial_converted,
            "is_in_trial": self.is_in_trial,
            "trial_days_remaining": self.trial_days_remaining,
            "trial_debates_remaining": self.trial_debates_remaining,
            "is_trial_expired": self.is_trial_expired,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Organization:
        """Create from dictionary."""
        org = cls(
            id=data.get("id", str(uuid4())),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            tier=SubscriptionTier(data.get("tier", "free")),
            owner_id=data.get("owner_id"),
            stripe_customer_id=data.get("stripe_customer_id"),
            stripe_subscription_id=data.get("stripe_subscription_id"),
            debates_used_this_month=data.get("debates_used_this_month", 0),
            settings=data.get("settings", {}),
        )
        if "created_at" in data and data["created_at"]:
            if isinstance(data["created_at"], str):
                org.created_at = datetime.fromisoformat(data["created_at"])
            else:
                org.created_at = data["created_at"]
        if "updated_at" in data and data["updated_at"]:
            if isinstance(data["updated_at"], str):
                org.updated_at = datetime.fromisoformat(data["updated_at"])
            else:
                org.updated_at = data["updated_at"]
        if "billing_cycle_start" in data and data["billing_cycle_start"]:
            if isinstance(data["billing_cycle_start"], str):
                org.billing_cycle_start = datetime.fromisoformat(data["billing_cycle_start"])
            else:
                org.billing_cycle_start = data["billing_cycle_start"]
        # Trial fields
        if "trial_started_at" in data and data["trial_started_at"]:
            if isinstance(data["trial_started_at"], str):
                org.trial_started_at = datetime.fromisoformat(data["trial_started_at"])
            else:
                org.trial_started_at = data["trial_started_at"]
        if "trial_expires_at" in data and data["trial_expires_at"]:
            if isinstance(data["trial_expires_at"], str):
                org.trial_expires_at = datetime.fromisoformat(data["trial_expires_at"])
            else:
                org.trial_expires_at = data["trial_expires_at"]
        org.trial_debates_limit = data.get("trial_debates_limit", 10)
        org.trial_converted = data.get("trial_converted", False)
        return org


@dataclass
class Subscription:
    """A subscription record."""

    id: str = field(default_factory=lambda: str(uuid4()))
    org_id: str = ""
    tier: SubscriptionTier = SubscriptionTier.FREE
    status: str = "active"  # active, canceled, past_due, trialing
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None

    # Billing period
    current_period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_period_end: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30)
    )
    cancel_at_period_end: bool = False

    # Trial
    trial_start: datetime | None = None
    trial_end: datetime | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        """Check if subscription is active."""
        return self.status in ("active", "trialing")

    @property
    def is_trialing(self) -> bool:
        """Check if subscription is in trial."""
        if self.status != "trialing":
            return False
        if self.trial_end is None:
            return False
        return datetime.now(timezone.utc) < self.trial_end

    @property
    def days_until_renewal(self) -> int:
        """Get days until next renewal."""
        delta = self.current_period_end - datetime.now(timezone.utc)
        return max(0, delta.days)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "tier": self.tier.value,
            "status": self.status,
            "stripe_subscription_id": self.stripe_subscription_id,
            "stripe_price_id": self.stripe_price_id,
            "current_period_start": self.current_period_start.isoformat(),
            "current_period_end": self.current_period_end.isoformat(),
            "cancel_at_period_end": self.cancel_at_period_end,
            "trial_start": self.trial_start.isoformat() if self.trial_start else None,
            "trial_end": self.trial_end.isoformat() if self.trial_end else None,
            "is_active": self.is_active,
            "is_trialing": self.is_trialing,
            "days_until_renewal": self.days_until_renewal,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subscription:
        """Create from dictionary."""
        sub = cls(
            id=data.get("id", str(uuid4())),
            org_id=data.get("org_id", ""),
            tier=SubscriptionTier(data.get("tier", "free")),
            status=data.get("status", "active"),
            stripe_subscription_id=data.get("stripe_subscription_id"),
            stripe_price_id=data.get("stripe_price_id"),
            cancel_at_period_end=data.get("cancel_at_period_end", False),
        )
        for field_name in [
            "current_period_start",
            "current_period_end",
            "trial_start",
            "trial_end",
            "created_at",
            "updated_at",
        ]:
            if field_name in data and data[field_name]:
                value = data[field_name]
                if isinstance(value, str):
                    value = datetime.fromisoformat(value)
                setattr(sub, field_name, value)
        return sub


@dataclass
class OrganizationInvitation:
    """An organization invitation for a user.

    Invitations are sent to email addresses. When the user registers or
    logs in with that email, they can accept the invitation to join.
    Invitations expire after a configurable number of days.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    org_id: str = ""
    email: str = ""  # Email address of invitee
    role: str = "member"  # Role to assign on acceptance (member, admin)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    invited_by: str | None = None  # User ID of inviter
    status: str = "pending"  # pending, accepted, expired, revoked
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=7)
    )
    accepted_by: str | None = None  # User ID who accepted the invitation
    accepted_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_pending(self) -> bool:
        """Check if invitation is still pending and valid."""
        return self.status == "pending" and not self.is_expired

    def accept(self) -> bool:
        """Mark invitation as accepted.

        Returns:
            True if successfully accepted, False if already processed or expired
        """
        if not self.is_pending:
            return False
        self.status = "accepted"
        self.accepted_at = datetime.now(timezone.utc)
        return True

    def revoke(self) -> bool:
        """Revoke the invitation.

        Returns:
            True if successfully revoked, False if already processed
        """
        if self.status != "pending":
            return False
        self.status = "revoked"
        return True

    def to_dict(self, include_token: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        data = {
            "id": self.id,
            "org_id": self.org_id,
            "email": self.email,
            "role": self.role,
            "invited_by": self.invited_by,
            "status": self.status,
            "is_pending": self.is_pending,
            "is_expired": self.is_expired,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
        }
        if include_token:
            data["token"] = self.token
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrganizationInvitation:
        """Create from dictionary."""
        inv = cls(
            id=data.get("id", str(uuid4())),
            org_id=data.get("org_id", ""),
            email=data.get("email", "").lower(),
            role=data.get("role", "member"),
            token=data.get("token", secrets.token_urlsafe(32)),
            invited_by=data.get("invited_by"),
            status=data.get("status", "pending"),
        )
        for field_name in ["created_at", "expires_at", "accepted_at"]:
            if field_name in data and data[field_name]:
                value = data[field_name]
                if isinstance(value, str):
                    value = datetime.fromisoformat(value)
                setattr(inv, field_name, value)
        return inv


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from name."""
    import re

    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:50] or "org"


__all__ = [
    "SubscriptionTier",
    "TierLimits",
    "TIER_LIMITS",
    "User",
    "Organization",
    "Subscription",
    "OrganizationInvitation",
    "hash_password",
    "verify_password",
    "needs_rehash",
    "generate_slug",
    "HAS_BCRYPT",
]
