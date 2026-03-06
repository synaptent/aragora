"""
Tenant model and configuration.

Defines the core tenant entity and its configuration options.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TenantTier(Enum):
    """Subscription tiers for tenants."""

    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


class TenantStatus(Enum):
    """Tenant account status."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"
    TRIAL = "trial"
    CANCELLED = "cancelled"


@dataclass
class TenantConfig:
    """Configuration options for a tenant."""

    # Limits
    max_debates_per_day: int = 100
    max_agents_per_debate: int = 10
    max_rounds_per_debate: int = 20
    max_concurrent_debates: int = 5
    max_users: int = 10
    max_connectors: int = 5

    # Features
    enable_rlm: bool = True
    enable_extended_debates: bool = False
    enable_custom_agents: bool = False
    enable_api_access: bool = True
    enable_webhooks: bool = False
    enable_sso: bool = False
    enable_audit_log: bool = True

    # Storage limits (bytes)
    storage_quota: int = 10 * 1024 * 1024 * 1024  # 10GB
    knowledge_quota: int = 1 * 1024 * 1024 * 1024  # 1GB

    # MFA enforcement
    require_admin_mfa: bool = True
    mfa_grace_period_days: int = 7

    # Rate limits
    api_requests_per_minute: int = 60
    api_requests_per_day: int = 10000

    # Token limits
    tokens_per_month: int = 1_000_000
    tokens_per_debate: int = 50_000

    @classmethod
    def for_tier(cls, tier: TenantTier) -> TenantConfig:
        """Get default configuration for a tier."""
        configs = {
            TenantTier.FREE: cls(
                max_debates_per_day=10,
                max_agents_per_debate=5,
                max_rounds_per_debate=8,
                max_concurrent_debates=1,
                max_users=3,
                max_connectors=1,
                enable_extended_debates=False,
                enable_custom_agents=False,
                enable_webhooks=False,
                enable_sso=False,
                storage_quota=1 * 1024 * 1024 * 1024,  # 1GB
                knowledge_quota=100 * 1024 * 1024,  # 100MB
                api_requests_per_minute=20,
                api_requests_per_day=1000,
                tokens_per_month=100_000,
                tokens_per_debate=10_000,
            ),
            TenantTier.STARTER: cls(
                max_debates_per_day=50,
                max_agents_per_debate=8,
                max_rounds_per_debate=15,
                max_concurrent_debates=3,
                max_users=10,
                max_connectors=3,
                enable_extended_debates=True,
                enable_custom_agents=False,
                enable_webhooks=True,
                enable_sso=False,
                storage_quota=10 * 1024 * 1024 * 1024,  # 10GB
                knowledge_quota=1 * 1024 * 1024 * 1024,  # 1GB
                api_requests_per_minute=60,
                api_requests_per_day=10_000,
                tokens_per_month=500_000,
                tokens_per_debate=25_000,
            ),
            TenantTier.PROFESSIONAL: cls(
                max_debates_per_day=200,
                max_agents_per_debate=15,
                max_rounds_per_debate=50,
                max_concurrent_debates=10,
                max_users=50,
                max_connectors=10,
                enable_extended_debates=True,
                enable_custom_agents=True,
                enable_webhooks=True,
                enable_sso=True,
                storage_quota=100 * 1024 * 1024 * 1024,  # 100GB
                knowledge_quota=10 * 1024 * 1024 * 1024,  # 10GB
                api_requests_per_minute=300,
                api_requests_per_day=100_000,
                tokens_per_month=5_000_000,
                tokens_per_debate=100_000,
            ),
            TenantTier.ENTERPRISE: cls(
                max_debates_per_day=10000,
                max_agents_per_debate=50,
                max_rounds_per_debate=100,
                max_concurrent_debates=100,
                max_users=1000,
                max_connectors=50,
                enable_extended_debates=True,
                enable_custom_agents=True,
                enable_webhooks=True,
                enable_sso=True,
                storage_quota=1024 * 1024 * 1024 * 1024,  # 1TB
                knowledge_quota=100 * 1024 * 1024 * 1024,  # 100GB
                api_requests_per_minute=1000,
                api_requests_per_day=1_000_000,
                tokens_per_month=50_000_000,
                tokens_per_debate=500_000,
            ),
        }
        return configs.get(tier, cls())


@dataclass
class Tenant:
    """A tenant (organization) in the multi-tenant system."""

    id: str
    """Unique tenant identifier."""

    name: str
    """Display name of the tenant."""

    slug: str
    """URL-safe identifier."""

    tier: TenantTier = TenantTier.FREE
    """Subscription tier."""

    status: TenantStatus = TenantStatus.ACTIVE
    """Account status."""

    config: TenantConfig = field(default_factory=TenantConfig)
    """Tenant configuration."""

    # Contact
    owner_email: str = ""
    """Primary contact email."""

    billing_email: str | None = None
    """Billing contact email."""

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    """When the tenant was created."""

    updated_at: datetime = field(default_factory=datetime.now)
    """When the tenant was last updated."""

    # Security
    api_key_hash: str | None = None
    """Hash of the tenant's API key."""

    sso_provider: str | None = None
    """SSO provider (okta, azure_ad, google, etc.)."""

    sso_config: dict[str, Any] = field(default_factory=dict)
    """SSO configuration."""

    # Customization
    logo_url: str | None = None
    """Custom logo URL."""

    theme: dict[str, Any] = field(default_factory=dict)
    """Custom theme settings."""

    # Usage tracking
    current_month_tokens: int = 0
    """Tokens used this month."""

    current_month_debates: int = 0
    """Debates this month."""

    storage_used: int = 0
    """Current storage usage in bytes."""

    def __post_init__(self):
        """Apply tier defaults if needed."""
        if self.config is None:
            self.config = TenantConfig.for_tier(self.tier)

    @classmethod
    def create(
        cls,
        name: str,
        owner_email: str,
        tier: TenantTier = TenantTier.FREE,
    ) -> Tenant:
        """Create a new tenant."""
        slug = cls._generate_slug(name)
        tenant_id = cls._generate_id(slug)

        return cls(
            id=tenant_id,
            name=name,
            slug=slug,
            tier=tier,
            config=TenantConfig.for_tier(tier),
            owner_email=owner_email,
        )

    @staticmethod
    def _generate_slug(name: str) -> str:
        """Generate a URL-safe slug from name."""
        slug = name.lower()
        slug = "".join(c if c.isalnum() else "-" for c in slug)
        slug = "-".join(filter(None, slug.split("-")))
        return slug[:50]

    @staticmethod
    def _generate_id(slug: str) -> str:
        """Generate a unique tenant ID."""
        random_suffix = secrets.token_hex(4)
        return f"{slug}-{random_suffix}"

    def generate_api_key(self) -> str:
        """Generate a new API key for this tenant."""
        api_key = f"ara_{self.slug}_{secrets.token_urlsafe(32)}"
        self.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return api_key

    def verify_api_key(self, api_key: str) -> bool:
        """Verify an API key."""
        if not self.api_key_hash:
            return False
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return secrets.compare_digest(key_hash, self.api_key_hash)

    def is_active(self) -> bool:
        """Check if tenant is in an active state."""
        return self.status in [TenantStatus.ACTIVE, TenantStatus.TRIAL]

    def can_create_debate(self) -> bool:
        """Check if tenant can create a new debate."""
        if not self.is_active():
            return False
        return self.current_month_debates < self.config.max_debates_per_day

    def can_use_tokens(self, count: int) -> bool:
        """Check if tenant has enough token budget."""
        return self.current_month_tokens + count <= self.config.tokens_per_month

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "tier": self.tier.value,
            "status": self.status.value,
            "owner_email": self.owner_email,
            "created_at": self.created_at.isoformat(),
            "current_month_tokens": self.current_month_tokens,
            "current_month_debates": self.current_month_debates,
            "storage_used": self.storage_used,
        }


class TenantSuspendedError(Exception):
    """Raised when a suspended tenant attempts to perform an action."""

    def __init__(self, tenant_id: str, reason: str = ""):
        self.tenant_id = tenant_id
        self.reason = reason
        message = f"Tenant {tenant_id} is suspended"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class TenantManager:
    """Manager for tenant lifecycle and validation.

    Provides centralized tenant registration, validation, and suspension
    management for multi-tenant deployments.
    """

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}
        self._api_key_index: dict[str, str] = {}  # hash -> tenant_id

    def register_tenant(self, tenant: Tenant) -> None:
        """Register a tenant in the manager."""
        self._tenants[tenant.id] = tenant
        if tenant.api_key_hash:
            self._api_key_index[tenant.api_key_hash] = tenant.id

    def unregister_tenant(self, tenant_id: str) -> Tenant | None:
        """Remove a tenant from the manager."""
        tenant = self._tenants.pop(tenant_id, None)
        if tenant and tenant.api_key_hash:
            self._api_key_index.pop(tenant.api_key_hash, None)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        """Get a tenant by ID."""
        return self._tenants.get(tenant_id)

    async def validate_api_key(self, api_key: str) -> Tenant | None:
        """Validate an API key and return the associated tenant.

        Returns None if the key is invalid or tenant not found.
        Raises TenantSuspendedError if tenant is suspended.
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        tenant_id = self._api_key_index.get(key_hash)

        if not tenant_id:
            # Fallback: check all tenants (slower but handles unindexed keys)
            for tenant in self._tenants.values():
                if tenant.verify_api_key(api_key):
                    # Index for future lookups
                    self._api_key_index[key_hash] = tenant.id
                    if tenant.status == TenantStatus.SUSPENDED:
                        raise TenantSuspendedError(tenant.id)
                    return tenant if tenant.is_active() else None
            return None

        found_tenant = self._tenants.get(tenant_id)
        if not found_tenant:
            return None

        if found_tenant.status == TenantStatus.SUSPENDED:
            raise TenantSuspendedError(found_tenant.id)

        return found_tenant if found_tenant.is_active() else None

    async def suspend_tenant(self, tenant_id: str, reason: str = "") -> bool:
        """Suspend a tenant account.

        Returns True if suspension was successful, False if tenant not found.
        """
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        tenant.status = TenantStatus.SUSPENDED
        tenant.updated_at = datetime.now()
        return True

    async def activate_tenant(self, tenant_id: str) -> bool:
        """Reactivate a suspended tenant.

        Returns True if activation was successful, False if tenant not found.
        """
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        tenant.status = TenantStatus.ACTIVE
        tenant.updated_at = datetime.now()
        return True

    def list_tenants(
        self,
        status: TenantStatus | None = None,
        tier: TenantTier | None = None,
    ) -> list[Tenant]:
        """List tenants with optional filtering."""
        tenants = list(self._tenants.values())

        if status:
            tenants = [t for t in tenants if t.status == status]
        if tier:
            tenants = [t for t in tenants if t.tier == tier]

        return tenants

    @property
    def count(self) -> int:
        """Number of registered tenants."""
        return len(self._tenants)
