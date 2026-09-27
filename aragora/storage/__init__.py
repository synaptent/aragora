"""
Aragora Storage Module.

Provides persistent storage backends for users, organizations, and usage tracking.
Supports both SQLite (default) and PostgreSQL (for production scale).
"""

from .audit_store import AuditStore
from .backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
    get_database_backend,
    reset_database_backend,
)
from .base_database import BaseDatabase
from .base_store import SQLiteStore
from .interface import (
    AsyncStorageInterface,
    AsyncStoreBackend,
    BatchStoreBackend,
    HealthCheckBackend,
    StorageInterface,
    StoreBackend,
    SyncBackendWrapper,
    sync_backend,
)
from .share_store import ShareLinkStore
from .webhook_store import (
    InMemoryWebhookStore,
    SQLiteWebhookStore,
    WebhookStoreBackend,
    get_webhook_store,
    reset_webhook_store,
    set_webhook_store,
)
from .integration_store import (
    IntegrationConfig,
    IntegrationStoreBackend,
    InMemoryIntegrationStore,
    SQLiteIntegrationStore,
    RedisIntegrationStore,
    get_integration_store,
    set_integration_store,
    reset_integration_store,
    VALID_INTEGRATION_TYPES,
)
from .gmail_token_store import (
    GmailUserState,
    SyncJobState,
    GmailTokenStoreBackend,
    InMemoryGmailTokenStore,
    SQLiteGmailTokenStore,
    RedisGmailTokenStore,
    get_gmail_token_store,
    set_gmail_token_store,
    reset_gmail_token_store,
)
from .finding_workflow_store import (
    WorkflowDataItem,
    FindingWorkflowStoreBackend,
    InMemoryFindingWorkflowStore,
    SQLiteFindingWorkflowStore,
    RedisFindingWorkflowStore,
    get_finding_workflow_store,
    set_finding_workflow_store,
    reset_finding_workflow_store,
)
from .federation_registry_store import (
    FederatedRegionConfig,
    FederationRegistryStoreBackend,
    InMemoryFederationRegistryStore,
    SQLiteFederationRegistryStore,
    RedisFederationRegistryStore,
    get_federation_registry_store,
    set_federation_registry_store,
    reset_federation_registry_store,
)
from .redis_utils import (
    get_redis_client,
    reset_redis_client,
    is_cluster_mode,
)
from .connection_router import (
    ConnectionRouter,
    RouterConfig,
    ReplicaConfig,
    RouterMetrics,
    initialize_connection_router,
    get_connection_router,
    is_router_initialized,
    close_connection_router,
)
from .redis_ha import (
    RedisMode,
    RedisHAConfig,
    get_redis_client as get_ha_redis_client,
    get_async_redis_client as get_async_ha_redis_client,
    get_cached_redis_client,
    get_cached_async_redis_client,
    reset_cached_clients,
    check_redis_health,
    check_async_redis_health,
)
from .gauntlet_run_store import (
    GauntletRunItem,
    GauntletRunStoreBackend,
    InMemoryGauntletRunStore,
    SQLiteGauntletRunStore,
    RedisGauntletRunStore,
    get_gauntlet_run_store,
    set_gauntlet_run_store,
    reset_gauntlet_run_store,
)
from .approval_request_store import (
    ApprovalRequestItem,
    ApprovalRequestStoreBackend,
    InMemoryApprovalRequestStore,
    SQLiteApprovalRequestStore,
    RedisApprovalRequestStore,
    get_approval_request_store,
    set_approval_request_store,
    reset_approval_request_store,
)
from .ar_invoice_store import (
    ARInvoiceStoreBackend,
    InMemoryARInvoiceStore,
    SQLiteARInvoiceStore,
    PostgresARInvoiceStore,
    get_ar_invoice_store,
    set_ar_invoice_store,
    reset_ar_invoice_store,
)
from .invoice_store import (
    InvoiceStoreBackend,
    InMemoryInvoiceStore,
    SQLiteInvoiceStore,
    PostgresInvoiceStore,
    get_invoice_store,
    set_invoice_store,
    reset_invoice_store,
)

from typing import Any

# Global debate storage singleton (set during server startup)
_debate_storage: Any = None
_LAZY_STORE_EXPORTS = {
    "DebateStorageAdapter": ("aragora.export.storage_adapter", "DebateStorageAdapter"),
    "OrganizationStore": (".organization_store", "OrganizationStore"),
    "UserStore": (".user_store", "UserStore"),
}


def get_storage() -> Any:
    """Get the current debate storage instance.

    Returns the DebateStorage set during server startup via set_storage(),
    or None if not yet initialized.
    """
    return _debate_storage


def set_storage(storage: Any) -> None:
    """Set the debate storage instance (called during server startup)."""
    global _debate_storage
    _debate_storage = storage


def reset_storage() -> None:
    """Reset debate storage to None (for testing)."""
    global _debate_storage
    _debate_storage = None


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_STORE_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = [
    # Legacy base classes
    "BaseDatabase",
    "SQLiteStore",
    "StorageInterface",
    "AsyncStorageInterface",
    "DebateStorageAdapter",
    # Unified store protocols (recommended)
    "StoreBackend",
    "AsyncStoreBackend",
    "BatchStoreBackend",
    "HealthCheckBackend",
    "SyncBackendWrapper",
    "sync_backend",
    # Domain stores
    "UserStore",
    "OrganizationStore",
    "AuditStore",
    # Webhook idempotency
    "WebhookStoreBackend",
    "InMemoryWebhookStore",
    "SQLiteWebhookStore",
    "get_webhook_store",
    "set_webhook_store",
    "reset_webhook_store",
    # Database backends
    "DatabaseBackend",
    "SQLiteBackend",
    "PostgreSQLBackend",
    "get_database_backend",
    "reset_database_backend",
    "POSTGRESQL_AVAILABLE",
    # Share links
    "ShareLinkStore",
    # Integration config storage
    "IntegrationConfig",
    "IntegrationStoreBackend",
    "InMemoryIntegrationStore",
    "SQLiteIntegrationStore",
    "RedisIntegrationStore",
    "get_integration_store",
    "set_integration_store",
    "reset_integration_store",
    "VALID_INTEGRATION_TYPES",
    # Gmail token storage
    "GmailUserState",
    "SyncJobState",
    "GmailTokenStoreBackend",
    "InMemoryGmailTokenStore",
    "SQLiteGmailTokenStore",
    "RedisGmailTokenStore",
    "get_gmail_token_store",
    "set_gmail_token_store",
    "reset_gmail_token_store",
    # Finding workflow storage
    "WorkflowDataItem",
    "FindingWorkflowStoreBackend",
    "InMemoryFindingWorkflowStore",
    "SQLiteFindingWorkflowStore",
    "RedisFindingWorkflowStore",
    "get_finding_workflow_store",
    "set_finding_workflow_store",
    "reset_finding_workflow_store",
    # Federation registry storage
    "FederatedRegionConfig",
    "FederationRegistryStoreBackend",
    "InMemoryFederationRegistryStore",
    "SQLiteFederationRegistryStore",
    "RedisFederationRegistryStore",
    "get_federation_registry_store",
    "set_federation_registry_store",
    "reset_federation_registry_store",
    # Redis client utilities (legacy)
    "get_redis_client",
    "reset_redis_client",
    "is_cluster_mode",
    # Redis HA (High-Availability)
    "RedisMode",
    "RedisHAConfig",
    "get_ha_redis_client",
    "get_async_ha_redis_client",
    "get_cached_redis_client",
    "get_cached_async_redis_client",
    "reset_cached_clients",
    "check_redis_health",
    "check_async_redis_health",
    # Gauntlet run storage
    "GauntletRunItem",
    "GauntletRunStoreBackend",
    "InMemoryGauntletRunStore",
    "SQLiteGauntletRunStore",
    "RedisGauntletRunStore",
    "get_gauntlet_run_store",
    "set_gauntlet_run_store",
    "reset_gauntlet_run_store",
    # Approval request storage
    "ApprovalRequestItem",
    "ApprovalRequestStoreBackend",
    "InMemoryApprovalRequestStore",
    "SQLiteApprovalRequestStore",
    "RedisApprovalRequestStore",
    "get_approval_request_store",
    "set_approval_request_store",
    "reset_approval_request_store",
    # Connection router (read replicas)
    "ConnectionRouter",
    "RouterConfig",
    "ReplicaConfig",
    "RouterMetrics",
    "initialize_connection_router",
    "get_connection_router",
    "is_router_initialized",
    "close_connection_router",
    # AR Invoice storage (Accounts Receivable)
    "ARInvoiceStoreBackend",
    "InMemoryARInvoiceStore",
    "SQLiteARInvoiceStore",
    "PostgresARInvoiceStore",
    "get_ar_invoice_store",
    "set_ar_invoice_store",
    "reset_ar_invoice_store",
    # Invoice storage (Accounts Payable)
    "InvoiceStoreBackend",
    "InMemoryInvoiceStore",
    "SQLiteInvoiceStore",
    "PostgresInvoiceStore",
    "get_invoice_store",
    "set_invoice_store",
    "reset_invoice_store",
    # Debate storage singleton
    "get_storage",
    "set_storage",
    "reset_storage",
]
