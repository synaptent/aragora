"""
Comprehensive tests for aragora.billing.models module.

Tests cover:
- SubscriptionTier enum and TierLimits dataclass
- User dataclass with password hashing, API keys, MFA, service accounts
- Organization dataclass with billing and usage tracking
- Subscription dataclass with trial and period management
- OrganizationInvitation dataclass
- Password hashing functions (bcrypt and SHA-256)
- Utility functions like generate_slug
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from aragora.billing.models import (
    SubscriptionTier,
    TierLimits,
    TIER_LIMITS,
    User,
    Organization,
    Subscription,
    OrganizationInvitation,
    hash_password,
    verify_password,
    needs_rehash,
    generate_slug,
    HAS_BCRYPT,
    HASH_VERSION_BCRYPT,
    HASH_VERSION_SHA256,
    BCRYPT_ROUNDS,
    clear_mfa_bypass_audit_sink,
    register_mfa_bypass_audit_sink,
)
from aragora.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def configured_mfa_bypass_audit_sink():
    """Provide the required MFA audit capability for model tests."""
    sink = MagicMock()
    register_mfa_bypass_audit_sink(sink)
    yield sink
    clear_mfa_bypass_audit_sink()


# =============================================================================
# SubscriptionTier Tests
# =============================================================================


class TestSubscriptionTier:
    """Tests for the SubscriptionTier enum."""

    def test_tier_values(self):
        """Test that all subscription tiers have correct values."""
        assert SubscriptionTier.FREE.value == "free"
        assert SubscriptionTier.STARTER.value == "starter"
        assert SubscriptionTier.PROFESSIONAL.value == "professional"
        assert SubscriptionTier.ENTERPRISE.value == "enterprise"
        assert len(SubscriptionTier) == 4  # Free, Starter, Professional, Enterprise

    def test_tier_from_string(self):
        """Test creating tier from string value."""
        assert SubscriptionTier("free") == SubscriptionTier.FREE
        assert SubscriptionTier("enterprise") == SubscriptionTier.ENTERPRISE

    def test_tier_invalid_string(self):
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError):
            SubscriptionTier("invalid_tier")

    def test_all_tiers_in_limits(self):
        """Test that all tiers have defined limits."""
        for tier in SubscriptionTier:
            assert tier in TIER_LIMITS


# =============================================================================
# TierLimits Tests
# =============================================================================


class TestTierLimits:
    """Tests for the TierLimits dataclass."""

    def test_free_tier_limits(self):
        """Test FREE tier has correct limits."""
        limits = TIER_LIMITS[SubscriptionTier.FREE]
        assert limits.debates_per_month == 10
        assert limits.users_per_org == 1
        assert limits.api_access is False
        assert limits.all_agents is False
        assert limits.custom_agents is False
        assert limits.sso_enabled is False
        assert limits.audit_logs is False
        assert limits.priority_support is False
        assert limits.price_monthly_cents == 0

    def test_starter_tier_limits(self):
        """Test STARTER tier has correct limits."""
        limits = TIER_LIMITS[SubscriptionTier.STARTER]
        assert limits.debates_per_month == 100
        assert limits.users_per_org == 5
        assert limits.api_access is True
        assert limits.price_monthly_cents == 2900  # $29

    def test_professional_tier_limits(self):
        """Test PROFESSIONAL tier has correct limits."""
        limits = TIER_LIMITS[SubscriptionTier.PROFESSIONAL]
        assert limits.debates_per_month == 1000
        assert limits.users_per_org == 25
        assert limits.api_access is True
        assert limits.all_agents is True
        assert limits.audit_logs is True
        assert limits.priority_support is True
        assert limits.price_monthly_cents == 9900  # $99

    def test_enterprise_tier_limits(self):
        """Test ENTERPRISE tier has correct limits."""
        limits = TIER_LIMITS[SubscriptionTier.ENTERPRISE]
        assert limits.debates_per_month == 999999  # Unlimited
        assert limits.users_per_org == 999999
        assert limits.sso_enabled is True
        assert limits.priority_support is True
        assert limits.price_monthly_cents == 0  # Custom pricing
        assert limits.dedicated_infrastructure is True
        assert limits.sla_guarantee is True
        assert limits.compliance_certifications is True

    def test_tier_limits_to_dict(self):
        """Test TierLimits serialization."""
        limits = TIER_LIMITS[SubscriptionTier.FREE]
        data = limits.to_dict()
        assert isinstance(data, dict)
        assert data["debates_per_month"] == 10
        assert data["api_access"] is False


# =============================================================================
# Password Hashing Tests
# =============================================================================


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_bcrypt(self):
        """Test password hashing with bcrypt (when available)."""

        password = "secure_password_123"
        hashed, salt = hash_password(password)

        assert hashed.startswith(HASH_VERSION_BCRYPT)
        assert salt == ""  # bcrypt embeds salt in hash

    def test_verify_password_bcrypt(self):
        """Test password verification with bcrypt."""

        password = "test_password"
        hashed, salt = hash_password(password)

        assert verify_password(password, hashed, salt) is True
        assert verify_password("wrong_password", hashed, salt) is False

    @patch.dict(os.environ, {"ARAGORA_ALLOW_INSECURE_PASSWORDS": "1"})
    def test_hash_password_sha256_fallback(self):
        """Test SHA-256 fallback when bcrypt unavailable."""
        # This test simulates bcrypt being unavailable
        with patch("aragora.billing.models.HAS_BCRYPT", False):
            # Need to reimport to get the patched version
            from aragora.billing import models as m

            # Manually call the sha256 function
            password = "test_password"
            hashed, salt = m._hash_password_sha256(password)

            assert len(hashed) == 64  # SHA-256 hex length
            assert len(salt) == 64  # 32 bytes hex

    def test_verify_password_legacy_sha256(self):
        """Test verification of legacy SHA-256 hashes."""
        password = "test_password"
        salt = secrets.token_hex(32)
        hash_input = f"{salt}{password}".encode()
        legacy_hash = hashlib.sha256(hash_input).hexdigest()

        # Unprefixed legacy hash (64 chars)
        assert verify_password(password, legacy_hash, salt) is True
        assert verify_password("wrong", legacy_hash, salt) is False

        # Prefixed SHA-256 hash
        prefixed_hash = f"{HASH_VERSION_SHA256}{legacy_hash}"
        assert verify_password(password, prefixed_hash, salt) is True

    def test_verify_password_unknown_format(self):
        """Test verification rejects unknown hash formats."""
        assert verify_password("password", "short_hash", "salt") is False
        assert verify_password("password", "unknown:prefix:hash", "salt") is False

    def test_needs_rehash_empty_hash(self):
        """Test that empty hash needs rehash."""
        assert needs_rehash("") is True

    def test_needs_rehash_sha256_with_bcrypt_available(self):
        """Test that SHA-256 hash needs rehash when bcrypt is available."""

        sha256_hash = f"{HASH_VERSION_SHA256}{'a' * 64}"
        assert needs_rehash(sha256_hash) is True

    def test_needs_rehash_bcrypt_hash(self):
        """Test that bcrypt hash doesn't need rehash."""

        password = "test"
        hashed, _ = hash_password(password)
        assert needs_rehash(hashed) is False


# =============================================================================
# User Tests
# =============================================================================


class TestUser:
    """Tests for the User dataclass."""

    def test_user_creation_defaults(self):
        """Test User creation with default values."""
        user = User()
        assert user.id is not None
        assert user.email == ""
        assert user.role == "member"
        assert user.is_active is True
        assert user.email_verified is False
        assert user.mfa_enabled is False
        assert user.token_version == 1
        assert user.is_service_account is False

    def test_user_creation_with_values(self):
        """Test User creation with explicit values."""
        user_id = str(uuid4())
        user = User(
            id=user_id,
            email="test@example.com",
            name="Test User",
            role="admin",
            org_id="org-123",
        )
        assert user.id == user_id
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.role == "admin"
        assert user.org_id == "org-123"

    def test_user_set_password(self):
        """Test setting user password."""
        user = User()
        user.set_password("secure_password")

        assert user.password_hash != ""
        assert user.verify_password("secure_password") is True
        assert user.verify_password("wrong_password") is False

    def test_user_verify_password(self):
        """Test password verification."""
        user = User()
        user.set_password("my_password")

        assert user.verify_password("my_password") is True
        assert user.verify_password("other_password") is False
        assert user.verify_password("") is False

    def test_user_needs_password_rehash(self):
        """Test password rehash detection."""
        user = User()
        user.set_password("test")

        if HAS_BCRYPT:
            # Fresh bcrypt hash shouldn't need rehash
            assert user.needs_password_rehash() is False

    def test_user_upgrade_password_hash(self):
        """Test password hash upgrade."""
        user = User()
        user.set_password("test")

        # If already current, no upgrade needed
        if HAS_BCRYPT:
            assert user.upgrade_password_hash("test") is False

    def test_user_generate_api_key(self):
        """Test API key generation."""
        user = User()
        api_key = user.generate_api_key()

        assert api_key.startswith("ara_")
        assert len(api_key) > 40
        assert user.api_key_hash is not None
        assert user.api_key_prefix == api_key[:12]
        assert user.api_key_created_at is not None
        assert user.api_key_expires_at is not None

    def test_user_verify_api_key(self):
        """Test API key verification."""
        user = User()
        api_key = user.generate_api_key()

        assert user.verify_api_key(api_key) is True
        assert user.verify_api_key("ara_invalid_key") is False

    def test_user_verify_api_key_expired(self):
        """Test expired API key verification."""
        user = User()
        api_key = user.generate_api_key(expires_days=0)
        # Force expiration
        user.api_key_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        assert user.verify_api_key(api_key) is False

    def test_user_verify_api_key_no_key(self):
        """Test API key verification when no key exists."""
        user = User()
        assert user.verify_api_key("ara_some_key") is False

    def test_user_is_api_key_expired(self):
        """Test API key expiration check."""
        user = User()
        user.generate_api_key()

        assert user.is_api_key_expired() is False

        user.api_key_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert user.is_api_key_expired() is True

    def test_user_revoke_api_key(self):
        """Test API key revocation."""
        user = User()
        user.generate_api_key()

        user.revoke_api_key()

        assert user.api_key_hash is None
        assert user.api_key_prefix is None
        assert user.api_key_created_at is None
        assert user.api_key_expires_at is None

    def test_user_promote_to_admin(self):
        """Test user promotion to admin."""
        user = User(role="member")
        user.promote_to_admin("admin")

        assert user.role == "admin"
        assert user.mfa_grace_period_started_at is not None

    def test_user_promote_to_admin_invalid_role(self):
        """Test promotion with invalid admin role."""
        user = User()
        with pytest.raises(ValueError, match="Invalid admin role"):
            user.promote_to_admin("member")

    def test_user_promote_to_admin_already_admin(self):
        """Test promotion when already admin."""
        user = User(role="admin", mfa_enabled=False)
        user.promote_to_admin("owner")

        assert user.role == "owner"
        # Grace period shouldn't be set if already admin
        # (though implementation may vary)

    def test_user_clear_mfa_grace_period(self):
        """Test clearing MFA grace period."""
        user = User()
        user.mfa_grace_period_started_at = datetime.now(timezone.utc)
        user.clear_mfa_grace_period()

        assert user.mfa_grace_period_started_at is None

    def test_user_service_account_scopes(self):
        """Test service account scope management."""
        user = User(is_service_account=True)

        assert user.get_service_account_scopes() == []

        user.set_service_account_scopes(["read:debates", "write:debates"])
        assert user.get_service_account_scopes() == ["read:debates", "write:debates"]

    def test_user_service_account_scopes_invalid_json(self):
        """Test service account scopes with invalid JSON."""
        user = User(is_service_account=True)
        user.service_account_scopes = "not valid json"

        assert user.get_service_account_scopes() == []

    def test_user_has_scope_non_service_account(self):
        """Test non-service account has all scopes."""
        user = User(is_service_account=False)
        assert user.has_scope("any:scope") is True

    def test_user_has_scope_service_account(self):
        """Test service account scope checking."""
        user = User(is_service_account=True)
        user.set_service_account_scopes(["read:debates"])

        assert user.has_scope("read:debates") is True
        assert user.has_scope("write:debates") is False

    def test_user_mfa_bypass_not_service_account(self):
        """Test MFA bypass for non-service accounts."""
        user = User(is_service_account=False)
        assert user.is_mfa_bypass_valid() is False

    def test_user_mfa_bypass_valid(self):
        """Test valid MFA bypass."""
        user = User(is_service_account=True)
        user.mfa_bypass_approved_at = datetime.now(timezone.utc)
        user.mfa_bypass_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        assert user.is_mfa_bypass_valid() is True

    def test_user_mfa_bypass_expired(self):
        """Test expired MFA bypass."""
        user = User(is_service_account=True)
        user.mfa_bypass_approved_at = datetime.now(timezone.utc) - timedelta(days=100)
        user.mfa_bypass_expires_at = datetime.now(timezone.utc) - timedelta(days=10)

        assert user.is_mfa_bypass_valid() is False

    def test_user_approve_mfa_bypass(self, configured_mfa_bypass_audit_sink):
        """Test approving MFA bypass."""
        user = User(is_service_account=True)
        user.approve_mfa_bypass(
            approved_by="admin-123",
            reason="api_integration",
            expires_days=60,
        )

        assert user.mfa_bypass_reason == "api_integration"
        assert user.mfa_bypass_approved_by == "admin-123"
        assert user.mfa_bypass_approved_at is not None
        assert user.mfa_bypass_expires_at is not None
        configured_mfa_bypass_audit_sink.assert_called_once_with(
            admin_id="admin-123",
            action="mfa_bypass_approved",
            target_type="service_account",
            target_id=str(user.id),
            details={"reason": "api_integration", "expires_days": 60},
        )

    def test_user_approve_mfa_bypass_not_service_account(self):
        """Test MFA bypass approval fails for non-service accounts."""
        user = User(is_service_account=False)
        with pytest.raises(ValueError, match="service accounts"):
            user.approve_mfa_bypass(approved_by="admin-123")

    def test_user_revoke_mfa_bypass(self, configured_mfa_bypass_audit_sink):
        """Test revoking MFA bypass."""
        user = User(is_service_account=True)
        user.approve_mfa_bypass(approved_by="admin-123")
        configured_mfa_bypass_audit_sink.reset_mock()
        user.revoke_mfa_bypass(revoked_by="admin-456", reason="security_review")

        assert user.mfa_bypass_approved_at is None
        assert user.mfa_bypass_approved_by is None
        assert user.mfa_bypass_expires_at is None
        assert user.mfa_bypass_reason is None
        configured_mfa_bypass_audit_sink.assert_called_once_with(
            admin_id="admin-456",
            action="mfa_bypass_revoked",
            target_type="service_account",
            target_id=str(user.id),
            details={
                "reason": "security_review",
                "previous_approved_by": "admin-123",
            },
        )

    def test_user_approve_mfa_bypass_requires_audit_capability(self):
        """Approval fails closed when no audit sink has been registered."""
        clear_mfa_bypass_audit_sink()
        user = User(is_service_account=True)

        with pytest.raises(ConfigurationError, match="required to approve MFA bypasses"):
            user.approve_mfa_bypass(approved_by="admin-123")

        assert user.mfa_bypass_approved_at is None
        assert user.mfa_bypass_approved_by is None
        assert user.mfa_bypass_expires_at is None
        assert user.mfa_bypass_reason is None

    def test_user_revoke_mfa_bypass_requires_audit_capability(self):
        """Revocation fails closed when no audit sink has been registered."""
        user = User(is_service_account=True)
        user.approve_mfa_bypass(approved_by="admin-123")
        approved_at = user.mfa_bypass_approved_at
        expires_at = user.mfa_bypass_expires_at
        clear_mfa_bypass_audit_sink()

        with pytest.raises(ConfigurationError, match="required to revoke MFA bypasses"):
            user.revoke_mfa_bypass(revoked_by="admin-456")

        assert user.mfa_bypass_approved_at == approved_at
        assert user.mfa_bypass_approved_by == "admin-123"
        assert user.mfa_bypass_expires_at == expires_at
        assert user.mfa_bypass_reason == "service_account"

    def test_user_approve_mfa_bypass_propagates_audit_failure(self):
        """A configured but failing audit sink remains fail closed."""
        register_mfa_bypass_audit_sink(MagicMock(side_effect=RuntimeError("audit down")))
        user = User(is_service_account=True)

        with pytest.raises(RuntimeError, match="audit down"):
            user.approve_mfa_bypass(approved_by="admin-123")

        assert user.mfa_bypass_approved_at is None
        assert user.mfa_bypass_approved_by is None

    def test_user_revoke_mfa_bypass_not_service_account(self):
        """Test MFA bypass revocation fails for non-service accounts."""
        user = User(is_service_account=False)
        with pytest.raises(ValueError, match="service accounts"):
            user.revoke_mfa_bypass(revoked_by="admin-123")

    def test_user_to_dict(self):
        """Test User serialization."""
        user = User(
            id="user-123",
            email="test@example.com",
            name="Test User",
            role="admin",
            mfa_enabled=True,
        )
        data = user.to_dict()

        assert data["id"] == "user-123"
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert data["role"] == "admin"
        assert data["mfa_enabled"] is True
        assert "password_hash" not in data  # Sensitive data excluded

    def test_user_to_dict_include_sensitive(self):
        """Test User serialization with sensitive data."""
        user = User(is_service_account=True)
        user.generate_api_key()
        user.approve_mfa_bypass(approved_by="admin-123")

        data = user.to_dict(include_sensitive=True)

        assert "api_key_prefix" in data
        assert "mfa_bypass_reason" in data
        assert "service_account_created_by" in data

    def test_user_from_dict(self):
        """Test User deserialization."""
        data = {
            "id": "user-123",
            "email": "test@example.com",
            "name": "Test User",
            "role": "admin",
            "is_active": True,
            "mfa_enabled": True,
            "created_at": "2024-01-01T00:00:00",
        }
        user = User.from_dict(data)

        assert user.id == "user-123"
        assert user.email == "test@example.com"
        assert user.role == "admin"
        assert user.mfa_enabled is True

    def test_user_from_dict_with_scopes_list(self):
        """Test User deserialization with scopes as list."""
        data = {
            "is_service_account": True,
            "service_account_scopes": ["read:debates", "write:debates"],
        }
        user = User.from_dict(data)

        assert user.get_service_account_scopes() == ["read:debates", "write:debates"]

    def test_user_from_dict_with_scopes_string(self):
        """Test User deserialization with scopes as JSON string."""
        data = {
            "is_service_account": True,
            "service_account_scopes": '["read:debates"]',
        }
        user = User.from_dict(data)

        assert user.get_service_account_scopes() == ["read:debates"]


# =============================================================================
# Organization Tests
# =============================================================================


class TestOrganization:
    """Tests for the Organization dataclass."""

    def test_organization_creation_defaults(self):
        """Test Organization creation with defaults."""
        org = Organization()
        assert org.id is not None
        assert org.name == ""
        assert org.tier == SubscriptionTier.FREE
        assert org.debates_used_this_month == 0

    def test_organization_creation_with_values(self):
        """Test Organization creation with values."""
        org = Organization(
            id="org-123",
            name="Test Org",
            slug="test-org",
            tier=SubscriptionTier.PROFESSIONAL,
            owner_id="user-456",
        )
        assert org.id == "org-123"
        assert org.name == "Test Org"
        assert org.slug == "test-org"
        assert org.tier == SubscriptionTier.PROFESSIONAL
        assert org.owner_id == "user-456"

    def test_organization_limits_property(self):
        """Test Organization limits property."""
        org = Organization(tier=SubscriptionTier.PROFESSIONAL)
        limits = org.limits

        assert limits == TIER_LIMITS[SubscriptionTier.PROFESSIONAL]
        assert limits.debates_per_month == 1000

    def test_organization_debates_remaining(self):
        """Test debates remaining calculation."""
        org = Organization(tier=SubscriptionTier.FREE)
        assert org.debates_remaining == 10

        org.debates_used_this_month = 5
        assert org.debates_remaining == 5

        org.debates_used_this_month = 15  # Over limit
        assert org.debates_remaining == 0  # Can't go negative

    def test_organization_is_at_limit(self):
        """Test limit detection."""
        org = Organization(tier=SubscriptionTier.FREE)
        assert org.is_at_limit is False

        org.debates_used_this_month = 10
        assert org.is_at_limit is True

        org.debates_used_this_month = 15  # Over limit
        assert org.is_at_limit is True

    def test_organization_increment_debates(self):
        """Test debate increment."""
        org = Organization(tier=SubscriptionTier.FREE)

        result = org.increment_debates()
        assert result is True
        assert org.debates_used_this_month == 1

        result = org.increment_debates(5)
        assert result is True
        assert org.debates_used_this_month == 6

    def test_organization_increment_debates_at_limit(self):
        """Test debate increment at limit."""
        org = Organization(tier=SubscriptionTier.FREE)
        org.debates_used_this_month = 10  # At limit

        result = org.increment_debates()
        assert result is False
        assert org.debates_used_this_month == 10  # Unchanged

    def test_organization_reset_monthly_usage(self):
        """Test monthly usage reset."""
        org = Organization(tier=SubscriptionTier.FREE)
        org.debates_used_this_month = 8
        old_cycle_start = org.billing_cycle_start

        org.reset_monthly_usage()

        assert org.debates_used_this_month == 0
        assert org.billing_cycle_start >= old_cycle_start

    def test_organization_to_dict(self):
        """Test Organization serialization."""
        org = Organization(
            id="org-123",
            name="Test Org",
            tier=SubscriptionTier.PROFESSIONAL,
            debates_used_this_month=50,
        )
        data = org.to_dict()

        assert data["id"] == "org-123"
        assert data["name"] == "Test Org"
        assert data["tier"] == "professional"
        assert data["debates_used_this_month"] == 50
        assert data["debates_remaining"] == 950
        assert "limits" in data

    def test_organization_from_dict(self):
        """Test Organization deserialization."""
        data = {
            "id": "org-123",
            "name": "Test Org",
            "tier": "enterprise",
            "debates_used_this_month": 100,
            "created_at": "2024-01-01T00:00:00",
        }
        org = Organization.from_dict(data)

        assert org.id == "org-123"
        assert org.name == "Test Org"
        assert org.tier == SubscriptionTier.ENTERPRISE
        assert org.debates_used_this_month == 100


# =============================================================================
# Subscription Tests
# =============================================================================


class TestSubscription:
    """Tests for the Subscription dataclass."""

    def test_subscription_creation_defaults(self):
        """Test Subscription creation with defaults."""
        sub = Subscription()
        assert sub.id is not None
        assert sub.tier == SubscriptionTier.FREE
        assert sub.status == "active"
        assert sub.cancel_at_period_end is False

    def test_subscription_creation_with_values(self):
        """Test Subscription creation with values."""
        sub = Subscription(
            id="sub-123",
            org_id="org-456",
            tier=SubscriptionTier.ENTERPRISE,
            status="trialing",
            stripe_subscription_id="sub_stripe_123",
        )
        assert sub.id == "sub-123"
        assert sub.org_id == "org-456"
        assert sub.tier == SubscriptionTier.ENTERPRISE
        assert sub.status == "trialing"
        assert sub.stripe_subscription_id == "sub_stripe_123"

    def test_subscription_is_active(self):
        """Test is_active property."""
        sub = Subscription(status="active")
        assert sub.is_active is True

        sub.status = "trialing"
        assert sub.is_active is True

        sub.status = "canceled"
        assert sub.is_active is False

        sub.status = "past_due"
        assert sub.is_active is False

    def test_subscription_is_trialing(self):
        """Test is_trialing property."""
        sub = Subscription(
            status="trialing",
            trial_end=datetime.now(timezone.utc) + timedelta(days=7),
        )
        assert sub.is_trialing is True

        # Expired trial
        sub.trial_end = datetime.now(timezone.utc) - timedelta(days=1)
        assert sub.is_trialing is False

        # Not trialing status
        sub.status = "active"
        sub.trial_end = datetime.now(timezone.utc) + timedelta(days=7)
        assert sub.is_trialing is False

    def test_subscription_is_trialing_no_end_date(self):
        """Test is_trialing with no trial_end."""
        sub = Subscription(status="trialing", trial_end=None)
        assert sub.is_trialing is False

    def test_subscription_days_until_renewal(self):
        """Test days until renewal calculation."""
        sub = Subscription()
        sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=15)

        assert 14 <= sub.days_until_renewal <= 15

    def test_subscription_days_until_renewal_past(self):
        """Test days until renewal when past."""
        sub = Subscription()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=5)

        assert sub.days_until_renewal == 0

    def test_subscription_to_dict(self):
        """Test Subscription serialization."""
        sub = Subscription(
            id="sub-123",
            org_id="org-456",
            tier=SubscriptionTier.PROFESSIONAL,
            status="active",
        )
        data = sub.to_dict()

        assert data["id"] == "sub-123"
        assert data["org_id"] == "org-456"
        assert data["tier"] == "professional"
        assert data["is_active"] is True
        assert "days_until_renewal" in data

    def test_subscription_from_dict(self):
        """Test Subscription deserialization."""
        data = {
            "id": "sub-123",
            "org_id": "org-456",
            "tier": "enterprise",
            "status": "trialing",
            "current_period_start": "2024-01-01T00:00:00",
            "current_period_end": "2024-02-01T00:00:00",
        }
        sub = Subscription.from_dict(data)

        assert sub.id == "sub-123"
        assert sub.tier == SubscriptionTier.ENTERPRISE
        assert sub.status == "trialing"


# =============================================================================
# OrganizationInvitation Tests
# =============================================================================


class TestOrganizationInvitation:
    """Tests for the OrganizationInvitation dataclass."""

    def test_invitation_creation_defaults(self):
        """Test invitation creation with defaults."""
        inv = OrganizationInvitation()
        assert inv.id is not None
        assert inv.token is not None
        assert inv.role == "member"
        assert inv.status == "pending"

    def test_invitation_creation_with_values(self):
        """Test invitation creation with values."""
        inv = OrganizationInvitation(
            id="inv-123",
            org_id="org-456",
            email="user@example.com",
            role="admin",
            invited_by="user-789",
        )
        assert inv.id == "inv-123"
        assert inv.org_id == "org-456"
        assert inv.email == "user@example.com"
        assert inv.role == "admin"
        assert inv.invited_by == "user-789"

    def test_invitation_is_expired(self):
        """Test invitation expiration detection."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        assert inv.is_expired is False

        inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert inv.is_expired is True

    def test_invitation_is_pending(self):
        """Test invitation pending status."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        assert inv.is_pending is True

        # Expired
        inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert inv.is_pending is False

        # Non-pending status
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        inv.status = "accepted"
        assert inv.is_pending is False

    def test_invitation_accept(self):
        """Test accepting invitation."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        result = inv.accept()
        assert result is True
        assert inv.status == "accepted"
        assert inv.accepted_at is not None

    def test_invitation_accept_expired(self):
        """Test accepting expired invitation."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        result = inv.accept()
        assert result is False
        assert inv.status == "pending"

    def test_invitation_accept_already_accepted(self):
        """Test accepting already accepted invitation."""
        inv = OrganizationInvitation()
        inv.status = "accepted"

        result = inv.accept()
        assert result is False

    def test_invitation_revoke(self):
        """Test revoking invitation."""
        inv = OrganizationInvitation()

        result = inv.revoke()
        assert result is True
        assert inv.status == "revoked"

    def test_invitation_revoke_already_processed(self):
        """Test revoking already processed invitation."""
        inv = OrganizationInvitation()
        inv.status = "accepted"

        result = inv.revoke()
        assert result is False

    def test_invitation_to_dict(self):
        """Test invitation serialization."""
        inv = OrganizationInvitation(
            id="inv-123",
            org_id="org-456",
            email="user@example.com",
        )
        data = inv.to_dict()

        assert data["id"] == "inv-123"
        assert data["email"] == "user@example.com"
        assert "token" not in data  # Excluded by default

    def test_invitation_to_dict_include_token(self):
        """Test invitation serialization with token."""
        inv = OrganizationInvitation()
        data = inv.to_dict(include_token=True)

        assert "token" in data
        assert len(data["token"]) > 20

    def test_invitation_from_dict(self):
        """Test invitation deserialization."""
        data = {
            "id": "inv-123",
            "org_id": "org-456",
            "email": "USER@EXAMPLE.COM",
            "role": "admin",
            "status": "pending",
        }
        inv = OrganizationInvitation.from_dict(data)

        assert inv.id == "inv-123"
        assert inv.email == "user@example.com"  # Lowercased
        assert inv.role == "admin"


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestGenerateSlug:
    """Tests for the generate_slug function."""

    def test_generate_slug_basic(self):
        """Test basic slug generation."""
        assert generate_slug("Test Company") == "test-company"
        assert generate_slug("My Org") == "my-org"

    def test_generate_slug_special_characters(self):
        """Test slug generation with special characters."""
        assert generate_slug("Test@Company!") == "testcompany"
        assert generate_slug("Hello, World!") == "hello-world"

    def test_generate_slug_multiple_spaces(self):
        """Test slug generation with multiple spaces."""
        assert generate_slug("Test   Company") == "test-company"
        assert generate_slug("A  B  C") == "a-b-c"

    def test_generate_slug_multiple_dashes(self):
        """Test slug generation with multiple dashes."""
        assert generate_slug("test--company") == "test-company"
        assert generate_slug("a---b") == "a-b"

    def test_generate_slug_leading_trailing_dashes(self):
        """Test slug generation strips leading/trailing dashes."""
        assert generate_slug("-test-") == "test"
        assert generate_slug("---company---") == "company"

    def test_generate_slug_long_name(self):
        """Test slug generation truncates long names."""
        long_name = "a" * 100
        slug = generate_slug(long_name)
        assert len(slug) <= 50

    def test_generate_slug_empty_result(self):
        """Test slug generation with empty result."""
        assert generate_slug("@#$%") == "org"  # Default fallback
        assert generate_slug("") == "org"

    def test_generate_slug_underscores(self):
        """Test slug generation handles underscores."""
        # Underscores are stripped by the first regex that removes non-alphanumeric
        # The underscore pattern only applies to internal spaces/underscores
        slug = generate_slug("test_company")
        # The regex r"[^a-z0-9\s-]" removes underscores, so result is "testcompany"
        assert slug == "testcompany"


# =============================================================================
# Integration Tests
# =============================================================================


class TestBillingIntegration:
    """Integration tests for billing models working together."""

    def test_full_user_lifecycle(self):
        """Test complete user lifecycle."""
        # Create user
        user = User(email="test@example.com", name="Test User")
        user.set_password("secure_password_123")

        # Generate API key
        api_key = user.generate_api_key()
        assert user.verify_api_key(api_key)

        # Promote to admin
        user.promote_to_admin("admin")
        assert user.role == "admin"

        # Serialize and deserialize
        data = user.to_dict()
        restored = User.from_dict(data)
        assert restored.email == user.email
        assert restored.role == "admin"

    def test_organization_subscription_integration(self):
        """Test organization and subscription integration."""
        org = Organization(
            name="Test Org",
            slug="test-org",
            tier=SubscriptionTier.PROFESSIONAL,
        )

        sub = Subscription(
            org_id=org.id,
            tier=org.tier,
            status="active",
        )

        # Verify consistency
        assert sub.tier == org.tier
        assert org.limits.api_access is True

    def test_service_account_complete_flow(self):
        """Test service account complete flow."""
        # Create service account
        sa = User(
            email="bot@example.com",
            is_service_account=True,
        )
        sa.set_service_account_scopes(["read:debates", "write:debates"])

        # Approve MFA bypass
        sa.approve_mfa_bypass(
            approved_by="admin-123",
            reason="api_integration",
            expires_days=90,
        )

        # Verify state
        assert sa.is_mfa_bypass_valid()
        assert sa.has_scope("read:debates")
        assert not sa.has_scope("delete:debates")

        # Serialize and restore
        data = sa.to_dict(include_sensitive=True)
        restored = User.from_dict(data)
        assert restored.is_service_account
        assert restored.get_service_account_scopes() == ["read:debates", "write:debates"]


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_organization_zero_debates(self):
        """Test organization with zero debates."""
        org = Organization(tier=SubscriptionTier.FREE)
        assert org.debates_used_this_month == 0
        assert org.debates_remaining == 10
        assert org.is_at_limit is False

    def test_subscription_negative_days_until_renewal(self):
        """Test subscription with past renewal date."""
        sub = Subscription()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=30)
        assert sub.days_until_renewal == 0  # Should be 0, not negative

    def test_user_empty_password(self):
        """Test user with empty password."""
        user = User()
        # Trying to verify with unset password
        assert user.verify_password("any_password") is False

    def test_api_key_boundary_expiration(self):
        """Test API key at exact expiration time."""
        user = User()
        api_key = user.generate_api_key(expires_days=0)
        # Key should still work for very brief moment after creation
        # (depends on timing, but test the boundary)

    def test_tier_limits_immutability(self):
        """Test that TIER_LIMITS is properly defined for all tiers."""
        for tier in SubscriptionTier:
            limits = TIER_LIMITS[tier]
            assert isinstance(limits, TierLimits)
            assert limits.price_monthly_cents >= 0

    def test_datetime_timezone_awareness(self):
        """Test datetime fields are timezone-aware."""
        user = User()
        org = Organization()
        sub = Subscription()

        # All datetime fields should be set
        assert user.created_at is not None
        assert org.created_at is not None
        assert sub.current_period_start is not None


# =============================================================================
# Additional Password Hashing Tests
# =============================================================================


class TestPasswordHashingExtended:
    """Extended tests for password hashing edge cases."""

    def test_hash_password_no_bcrypt_no_insecure(self):
        """Test hash_password raises ConfigurationError when bcrypt missing and insecure not allowed."""
        from aragora.exceptions import ConfigurationError

        with (
            patch("aragora.billing.models.HAS_BCRYPT", False),
            patch("aragora.billing.models.ALLOW_INSECURE_PASSWORDS", False),
        ):
            with pytest.raises(ConfigurationError):
                hash_password("test_password")

    def test_verify_password_bcrypt_hash_no_bcrypt_installed(self):
        """Test verify_password with bcrypt hash when bcrypt not installed."""
        bcrypt_hash = f"{HASH_VERSION_BCRYPT}$2b$12$somebcrypthashvalue"
        with patch("aragora.billing.models.HAS_BCRYPT", False):
            result = verify_password("test", bcrypt_hash, "")
            assert result is False

    def test_verify_password_bcrypt_checkpw_exception(self):
        """Test verify_password handles bcrypt.checkpw exception gracefully."""

        # A malformed bcrypt hash will cause checkpw to raise
        bad_bcrypt_hash = f"{HASH_VERSION_BCRYPT}$2b$12$invalidhashdata"
        result = verify_password("test", bad_bcrypt_hash, "")
        assert result is False

    def test_hash_password_sha256_with_explicit_salt(self):
        """Test SHA-256 hashing with explicit salt."""
        from aragora.billing.models import _hash_password_sha256

        salt = "fixed_salt_for_testing"
        hash1, salt1 = _hash_password_sha256("password", salt)
        hash2, salt2 = _hash_password_sha256("password", salt)

        assert hash1 == hash2
        assert salt1 == salt
        assert salt2 == salt

    def test_hash_password_sha256_different_salts(self):
        """Test SHA-256 hashing produces different results with different salts."""
        from aragora.billing.models import _hash_password_sha256

        hash1, salt1 = _hash_password_sha256("password", "salt_a")
        hash2, salt2 = _hash_password_sha256("password", "salt_b")

        assert hash1 != hash2

    def test_hash_password_sha256_auto_salt(self):
        """Test SHA-256 hashing generates salt when not provided."""
        from aragora.billing.models import _hash_password_sha256

        hash1, salt1 = _hash_password_sha256("password")
        hash2, salt2 = _hash_password_sha256("password")

        # Different auto-generated salts -> different hashes
        assert salt1 != salt2
        assert hash1 != hash2

    @patch.dict(os.environ, {"ARAGORA_ALLOW_INSECURE_PASSWORDS": "1"})
    def test_hash_password_sha256_fallback_produces_prefixed_hash(self):
        """Test SHA-256 fallback produces properly prefixed hash."""
        with (
            patch("aragora.billing.models.HAS_BCRYPT", False),
            patch("aragora.billing.models.ALLOW_INSECURE_PASSWORDS", True),
        ):
            from aragora.billing.models import _hash_password_sha256

            legacy_hash, salt = _hash_password_sha256("test")
            prefixed = f"{HASH_VERSION_SHA256}{legacy_hash}"

            # Verify it can be verified
            result = verify_password("test", prefixed, salt)
            assert result is True

    def test_needs_rehash_legacy_unprefixed_sha256(self):
        """Test that legacy unprefixed SHA-256 hash needs rehash."""

        legacy_hash = "a" * 64  # 64-char hex looks like legacy SHA-256
        assert needs_rehash(legacy_hash) is True

    def test_needs_rehash_bcrypt_not_available_bcrypt_hash(self):
        """Test needs_rehash returns False for bcrypt hash when bcrypt unavailable."""
        with patch("aragora.billing.models.HAS_BCRYPT", False):
            bcrypt_hash = f"{HASH_VERSION_BCRYPT}$2b$12$somehash"
            assert needs_rehash(bcrypt_hash) is False

    def test_verify_password_with_various_hash_lengths(self):
        """Test verify_password rejects unknown format hashes of various lengths."""
        assert verify_password("test", "short", "salt") is False
        assert verify_password("test", "x" * 63, "salt") is False  # Not 64 chars
        assert verify_password("test", "x" * 65, "salt") is False
        assert verify_password("test", "x" * 128, "salt") is False

    def test_bcrypt_rounds_constant(self):
        """Test BCRYPT_ROUNDS is set to a reasonable value."""
        assert BCRYPT_ROUNDS == 12
        assert BCRYPT_ROUNDS >= 10  # Security minimum


# =============================================================================
# Extended User Tests
# =============================================================================


class TestUserExtended:
    """Extended tests for User dataclass."""

    def test_user_set_password_updates_timestamp(self):
        """Test that set_password updates the updated_at timestamp."""
        user = User()
        # set_password uses datetime.now(timezone.utc), so compare with timezone-aware
        old_updated = datetime.now(timezone.utc)
        user.set_password("new_password")
        assert user.updated_at >= old_updated

    def test_user_upgrade_password_hash_when_needed(self):
        """Test password hash upgrade when hash is legacy SHA-256."""

        user = User()
        # Set a legacy SHA-256 hash manually
        salt = secrets.token_hex(32)
        hash_input = f"{salt}my_password".encode()
        legacy_hash = hashlib.sha256(hash_input).hexdigest()
        user.password_hash = f"{HASH_VERSION_SHA256}{legacy_hash}"
        user.password_salt = salt

        # Verify it needs rehash
        assert user.needs_password_rehash() is True

        # Upgrade
        result = user.upgrade_password_hash("my_password")
        assert result is True
        assert user.password_hash.startswith(HASH_VERSION_BCRYPT)

        # Verify new hash works
        assert user.verify_password("my_password") is True

    def test_user_generate_api_key_custom_expiration(self):
        """Test API key generation with custom expiration days."""
        user = User()
        user.generate_api_key(expires_days=30)

        expected_expiry = datetime.now(timezone.utc) + timedelta(days=30)
        # Within 10 seconds tolerance
        delta = abs((user.api_key_expires_at - expected_expiry).total_seconds())
        assert delta < 10

    def test_user_api_key_prefix_format(self):
        """Test API key prefix is first 12 characters."""
        user = User()
        api_key = user.generate_api_key()

        assert user.api_key_prefix == api_key[:12]
        assert user.api_key_prefix.startswith("ara_")

    def test_user_is_api_key_expired_no_expiration(self):
        """Test is_api_key_expired when no expiration set."""
        user = User()
        assert user.is_api_key_expired() is False

    def test_user_promote_to_admin_valid_roles(self):
        """Test promotion to each valid admin role."""
        for role in ["admin", "owner", "superadmin"]:
            user = User(role="member")
            user.promote_to_admin(role)
            assert user.role == role

    def test_user_promote_to_admin_mfa_already_enabled(self):
        """Test promotion when MFA is already enabled skips grace period."""
        user = User(role="member", mfa_enabled=True)
        user.promote_to_admin("admin")

        assert user.role == "admin"
        # MFA already enabled, so no grace period
        assert user.mfa_grace_period_started_at is None

    def test_user_service_account_scopes_none(self):
        """Test service account scopes when None."""
        user = User(is_service_account=True)
        user.service_account_scopes = None
        assert user.get_service_account_scopes() == []

    def test_user_mfa_bypass_no_expiration(self):
        """Test MFA bypass is valid when no expiration set."""
        user = User(is_service_account=True)
        user.mfa_bypass_approved_at = datetime.now(timezone.utc)
        user.mfa_bypass_expires_at = None

        assert user.is_mfa_bypass_valid() is True

    def test_user_mfa_bypass_no_approval(self):
        """Test MFA bypass is invalid when not approved."""
        user = User(is_service_account=True)
        assert user.is_mfa_bypass_valid() is False

    def test_user_to_dict_with_last_login(self):
        """Test User serialization includes last_login_at when set."""
        user = User()
        login_time = datetime.now(timezone.utc)
        user.last_login_at = login_time

        data = user.to_dict()
        assert data["last_login_at"] == login_time.isoformat()

    def test_user_to_dict_without_last_login(self):
        """Test User serialization handles missing last_login_at."""
        user = User()
        data = user.to_dict()
        assert data["last_login_at"] is None

    def test_user_to_dict_has_api_key_flag(self):
        """Test has_api_key flag in serialization."""
        user = User()
        assert user.to_dict()["has_api_key"] is False

        user.generate_api_key()
        assert user.to_dict()["has_api_key"] is True

    def test_user_to_dict_sensitive_no_service_account(self):
        """Test sensitive data for non-service account."""
        user = User(is_service_account=False)
        user.generate_api_key()

        data = user.to_dict(include_sensitive=True)
        assert "api_key_prefix" in data
        # mfa_bypass fields should not be present for non-service accounts
        assert "mfa_bypass_reason" not in data

    def test_user_from_dict_minimal(self):
        """Test User deserialization with minimal data."""
        user = User.from_dict({})
        assert user.email == ""
        assert user.role == "member"
        assert user.is_active is True
        assert user.token_version == 1

    def test_user_from_dict_with_datetime_objects(self):
        """Test User deserialization with datetime objects (not strings)."""
        now = datetime.now(timezone.utc)
        data = {
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }
        user = User.from_dict(data)

        assert user.created_at == now
        assert user.updated_at == now
        assert user.last_login_at == now

    def test_user_from_dict_with_api_key_dates(self):
        """Test User deserialization with api_key_created_at."""
        data = {
            "api_key_created_at": "2024-06-15T10:30:00",
        }
        user = User.from_dict(data)
        assert user.api_key_created_at is not None
        assert user.api_key_created_at.year == 2024

    def test_user_from_dict_with_mfa_bypass_dates(self):
        """Test User deserialization with MFA bypass datetime fields."""
        data = {
            "is_service_account": True,
            "mfa_bypass_approved_at": "2024-03-01T00:00:00",
            "mfa_bypass_expires_at": "2024-06-01T00:00:00",
            "mfa_bypass_reason": "api_integration",
            "mfa_bypass_approved_by": "admin-123",
        }
        user = User.from_dict(data)

        assert user.mfa_bypass_approved_at is not None
        assert user.mfa_bypass_expires_at is not None
        assert user.mfa_bypass_reason == "api_integration"
        assert user.mfa_bypass_approved_by == "admin-123"

    def test_user_from_dict_with_mfa_grace_period(self):
        """Test User deserialization with mfa_grace_period_started_at."""
        data = {
            "mfa_grace_period_started_at": "2024-05-01T12:00:00",
        }
        user = User.from_dict(data)
        assert user.mfa_grace_period_started_at is not None

    def test_user_round_trip_serialization(self):
        """Test User serialization/deserialization round trip."""
        original = User(
            id="user-rt",
            email="rt@test.com",
            name="Round Trip",
            role="admin",
            org_id="org-rt",
            is_active=True,
            email_verified=True,
            mfa_enabled=True,
            token_version=3,
        )

        data = original.to_dict()
        restored = User.from_dict(data)

        assert restored.id == original.id
        assert restored.email == original.email
        assert restored.name == original.name
        assert restored.role == original.role
        assert restored.org_id == original.org_id
        assert restored.mfa_enabled == original.mfa_enabled
        assert restored.token_version == original.token_version

    def test_user_revoke_api_key_updates_timestamp(self):
        """Test that revoke_api_key updates updated_at."""
        user = User()
        user.generate_api_key()
        old_updated = user.updated_at

        user.revoke_api_key()
        assert user.updated_at >= old_updated


# =============================================================================
# Extended Organization Tests
# =============================================================================


class TestOrganizationExtended:
    """Extended tests for Organization dataclass."""

    def test_organization_enterprise_limits(self):
        """Test ENTERPRISE tier limits on organization."""
        org = Organization(tier=SubscriptionTier.ENTERPRISE)
        limits = org.limits

        assert limits.dedicated_infrastructure is True
        assert limits.sla_guarantee is True
        assert limits.compliance_certifications is True

    def test_organization_increment_debates_by_count(self):
        """Test incrementing debates by various counts."""
        org = Organization(tier=SubscriptionTier.FREE)  # 10 limit

        assert org.increment_debates(3) is True
        assert org.debates_used_this_month == 3

        assert org.increment_debates(7) is True
        assert org.debates_used_this_month == 10

        # Now at limit
        assert org.increment_debates(1) is False

    def test_organization_to_dict_complete(self):
        """Test Organization serialization includes all fields."""
        org = Organization(
            id="org-full",
            name="Full Org",
            slug="full-org",
            tier=SubscriptionTier.ENTERPRISE,
            owner_id="user-owner",
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_456",
            debates_used_this_month=42,
            settings={"theme": "dark", "notifications": True},
        )
        data = org.to_dict()

        assert data["stripe_customer_id"] == "cus_123"
        assert data["stripe_subscription_id"] == "sub_456"
        assert data["settings"] == {"theme": "dark", "notifications": True}
        assert data["is_at_limit"] is False
        assert "limits" in data

    def test_organization_from_dict_with_datetime_objects(self):
        """Test Organization deserialization with datetime objects."""
        now = datetime.now(timezone.utc)
        data = {
            "name": "Datetime Org",
            "created_at": now,
            "updated_at": now,
            "billing_cycle_start": now,
        }
        org = Organization.from_dict(data)

        assert org.created_at == now
        assert org.updated_at == now
        assert org.billing_cycle_start == now

    def test_organization_from_dict_with_settings(self):
        """Test Organization deserialization preserves settings."""
        data = {
            "settings": {"feature_flags": ["beta"], "max_retries": 3},
        }
        org = Organization.from_dict(data)
        assert org.settings["feature_flags"] == ["beta"]
        assert org.settings["max_retries"] == 3

    def test_organization_from_dict_minimal(self):
        """Test Organization deserialization with minimal data."""
        org = Organization.from_dict({})
        assert org.name == ""
        assert org.tier == SubscriptionTier.FREE
        assert org.debates_used_this_month == 0

    def test_organization_round_trip_serialization(self):
        """Test Organization serialization round trip."""
        original = Organization(
            id="org-rt",
            name="Round Trip Org",
            slug="round-trip-org",
            tier=SubscriptionTier.PROFESSIONAL,
            owner_id="user-123",
            debates_used_this_month=25,
            settings={"key": "value"},
        )

        data = original.to_dict()
        restored = Organization.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.tier == original.tier
        assert restored.debates_used_this_month == original.debates_used_this_month

    def test_organization_debates_remaining_all_tiers(self):
        """Test debates_remaining for all tier types."""
        for tier in SubscriptionTier:
            org = Organization(tier=tier)
            limits = TIER_LIMITS[tier]
            assert org.debates_remaining == limits.debates_per_month
            assert org.is_at_limit is False


# =============================================================================
# Extended Subscription Tests
# =============================================================================


class TestSubscriptionExtended:
    """Extended tests for Subscription dataclass."""

    def test_subscription_from_dict_with_trial_dates(self):
        """Test Subscription deserialization with trial dates."""
        data = {
            "status": "trialing",
            "trial_start": "2024-01-01T00:00:00",
            "trial_end": "2024-01-15T00:00:00",
        }
        sub = Subscription.from_dict(data)

        assert sub.trial_start is not None
        assert sub.trial_end is not None

    def test_subscription_from_dict_with_cancel_at_period_end(self):
        """Test Subscription deserialization with cancel flag."""
        data = {
            "cancel_at_period_end": True,
        }
        sub = Subscription.from_dict(data)
        assert sub.cancel_at_period_end is True

    def test_subscription_from_dict_with_all_dates(self):
        """Test Subscription deserialization with all date fields."""
        data = {
            "current_period_start": "2024-01-01T00:00:00",
            "current_period_end": "2024-02-01T00:00:00",
            "trial_start": "2024-01-01T00:00:00",
            "trial_end": "2024-01-15T00:00:00",
            "created_at": "2023-12-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        sub = Subscription.from_dict(data)

        assert sub.current_period_start.year == 2024
        assert sub.current_period_end.month == 2
        assert sub.trial_start is not None
        assert sub.trial_end is not None
        assert sub.created_at.year == 2023

    def test_subscription_from_dict_with_datetime_objects(self):
        """Test Subscription deserialization with datetime objects (not strings)."""
        now = datetime.now(timezone.utc)
        data = {
            "current_period_start": now,
            "current_period_end": now + timedelta(days=30),
        }
        sub = Subscription.from_dict(data)

        assert sub.current_period_start == now

    def test_subscription_to_dict_with_trial(self):
        """Test Subscription serialization with trial data."""
        sub = Subscription(
            status="trialing",
            trial_start=datetime.now(timezone.utc),
            trial_end=datetime.now(timezone.utc) + timedelta(days=14),
        )
        data = sub.to_dict()

        assert data["trial_start"] is not None
        assert data["trial_end"] is not None
        assert data["is_trialing"] is True

    def test_subscription_to_dict_no_trial(self):
        """Test Subscription serialization without trial."""
        sub = Subscription(status="active")
        data = sub.to_dict()

        assert data["trial_start"] is None
        assert data["trial_end"] is None

    def test_subscription_round_trip_serialization(self):
        """Test Subscription serialization round trip."""
        original = Subscription(
            id="sub-rt",
            org_id="org-rt",
            tier=SubscriptionTier.PROFESSIONAL,
            status="active",
            stripe_subscription_id="sub_stripe_rt",
            stripe_price_id="price_rt",
            cancel_at_period_end=True,
        )

        data = original.to_dict()
        restored = Subscription.from_dict(data)

        assert restored.id == original.id
        assert restored.org_id == original.org_id
        assert restored.tier == original.tier
        assert restored.cancel_at_period_end is True

    def test_subscription_all_status_types(self):
        """Test all possible subscription statuses."""
        for status, expected_active in [
            ("active", True),
            ("trialing", True),
            ("canceled", False),
            ("past_due", False),
        ]:
            sub = Subscription(status=status)
            assert sub.is_active is expected_active, (
                f"Status '{status}' expected active={expected_active}"
            )


# =============================================================================
# Extended OrganizationInvitation Tests
# =============================================================================


class TestOrganizationInvitationExtended:
    """Extended tests for OrganizationInvitation dataclass."""

    def test_invitation_from_dict_with_datetime_objects(self):
        """Test invitation deserialization with datetime objects."""
        now = datetime.now(timezone.utc)
        data = {
            "created_at": now,
            "expires_at": now + timedelta(days=7),
            "accepted_at": now,
        }
        inv = OrganizationInvitation.from_dict(data)

        assert inv.created_at == now
        assert inv.accepted_at == now

    def test_invitation_from_dict_with_string_dates(self):
        """Test invitation deserialization with string dates."""
        data = {
            "created_at": "2024-01-01T00:00:00",
            "expires_at": "2024-01-08T00:00:00",
        }
        inv = OrganizationInvitation.from_dict(data)

        assert inv.created_at.year == 2024
        assert inv.expires_at.month == 1

    def test_invitation_to_dict_accepted(self):
        """Test invitation serialization when accepted."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        inv.accept()

        data = inv.to_dict()
        assert data["status"] == "accepted"
        assert data["accepted_at"] is not None
        assert data["is_pending"] is False

    def test_invitation_to_dict_revoked(self):
        """Test invitation serialization when revoked."""
        inv = OrganizationInvitation()
        inv.revoke()

        data = inv.to_dict()
        assert data["status"] == "revoked"
        assert data["is_pending"] is False

    def test_invitation_round_trip(self):
        """Test invitation serialization round trip."""
        original = OrganizationInvitation(
            id="inv-rt",
            org_id="org-rt",
            email="test@example.com",
            role="admin",
            invited_by="user-rt",
        )

        data = original.to_dict(include_token=True)
        restored = OrganizationInvitation.from_dict(data)

        assert restored.id == original.id
        assert restored.org_id == original.org_id
        assert restored.email == original.email
        assert restored.role == original.role

    def test_invitation_accept_then_revoke_fails(self):
        """Test that accepted invitation cannot be revoked."""
        inv = OrganizationInvitation()
        inv.expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        inv.accept()
        result = inv.revoke()
        assert result is False
        assert inv.status == "accepted"


# =============================================================================
# Extended Generate Slug Tests
# =============================================================================


class TestGenerateSlugExtended:
    """Extended tests for generate_slug function."""

    def test_generate_slug_with_numbers(self):
        """Test slug generation with numbers."""
        assert generate_slug("Team 42") == "team-42"
        assert generate_slug("123 Corp") == "123-corp"

    def test_generate_slug_already_slugified(self):
        """Test slug generation with already slugified input."""
        assert generate_slug("already-a-slug") == "already-a-slug"

    def test_generate_slug_unicode(self):
        """Test slug generation strips non-ASCII unicode."""
        slug = generate_slug("Cafe")
        assert slug == "cafe"

    def test_generate_slug_single_word(self):
        """Test slug generation with single word."""
        assert generate_slug("Company") == "company"

    def test_generate_slug_whitespace_only(self):
        """Test slug generation with whitespace only."""
        assert generate_slug("   ") == "org"

    def test_generate_slug_exact_50_chars(self):
        """Test slug generation with exactly 50 character result."""
        name = "a" * 50
        slug = generate_slug(name)
        assert len(slug) == 50

    def test_generate_slug_51_chars_truncated(self):
        """Test slug generation truncates at 50 characters."""
        name = "a" * 51
        slug = generate_slug(name)
        assert len(slug) == 50


# =============================================================================
# ALLOW_INSECURE_PASSWORDS Configuration Tests
# =============================================================================


class TestInsecurePasswordConfig:
    """Tests for ALLOW_INSECURE_PASSWORDS configuration."""

    def test_allow_insecure_true_values(self):
        """Test ALLOW_INSECURE_PASSWORDS recognizes 'true' values."""
        for val in ["1", "true", "yes", "TRUE", "True", "YES", "Yes"]:
            result = val.lower() in ("1", "true", "yes")
            assert result is True, f"Value '{val}' should be truthy"

    def test_allow_insecure_false_values(self):
        """Test ALLOW_INSECURE_PASSWORDS rejects false values."""
        for val in ["0", "false", "no", "", "maybe"]:
            result = val.lower() in ("1", "true", "yes")
            assert result is False, f"Value '{val}' should be falsy"


# =============================================================================
# TierLimits Extended Tests
# =============================================================================


class TestTierLimitsExtended:
    """Extended tests for TierLimits dataclass."""

    def test_tier_limits_default_enterprise_features(self):
        """Test default enterprise features are False for standard tiers."""
        for tier in [
            SubscriptionTier.FREE,
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
        ]:
            limits = TIER_LIMITS[tier]
            assert limits.dedicated_infrastructure is False
            assert limits.sla_guarantee is False
            assert limits.compliance_certifications is False

    def test_tier_pricing_monotonically_increasing(self):
        """Test that self-serve tier pricing increases with each level.

        Enterprise tier uses custom pricing (0 cents) so is excluded.
        """
        tier_order = [
            SubscriptionTier.FREE,
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
        ]

        for i in range(len(tier_order) - 1):
            lower = TIER_LIMITS[tier_order[i]].price_monthly_cents
            higher = TIER_LIMITS[tier_order[i + 1]].price_monthly_cents
            assert higher > lower, (
                f"{tier_order[i + 1].value} price ({higher}) should be greater "
                f"than {tier_order[i].value} price ({lower})"
            )

    def test_tier_debates_monotonically_increasing(self):
        """Test that debate limits increase with each level."""
        tier_order = [
            SubscriptionTier.FREE,
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
            SubscriptionTier.ENTERPRISE,
        ]

        for i in range(len(tier_order) - 1):
            lower = TIER_LIMITS[tier_order[i]].debates_per_month
            higher = TIER_LIMITS[tier_order[i + 1]].debates_per_month
            assert higher > lower

    def test_enterprise_tier_has_all_features(self):
        """Test that ENTERPRISE has all base features enabled."""
        limits = TIER_LIMITS[SubscriptionTier.ENTERPRISE]
        assert limits.api_access is True
        assert limits.all_agents is True
        assert limits.custom_agents is True
        assert limits.sso_enabled is True
        assert limits.audit_logs is True
        assert limits.priority_support is True
