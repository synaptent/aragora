"""
RBAC Permissions for Integrations, Connectors, and External Services.

Contains permissions related to:
- Connectors (data sources)
- Webhooks
- Integrations
- Gateway (OpenClaw)
- Bots
- Repository indexing
- API keys
- Vendor management
"""

from __future__ import annotations

from aragora.rbac.models import Action, ResourceType

from ._helpers import _permission

# ============================================================================
# CONNECTOR PERMISSIONS
# ============================================================================

PERM_CONNECTOR_READ = _permission(
    ResourceType.CONNECTOR, Action.READ, "View Connectors", "View connector configurations"
)
PERM_CONNECTOR_CREATE = _permission(
    ResourceType.CONNECTOR, Action.CREATE, "Create Connectors", "Configure new data connectors"
)
PERM_CONNECTOR_DELETE = _permission(
    ResourceType.CONNECTOR, Action.DELETE, "Delete Connectors", "Remove connector configurations"
)
PERM_CONNECTOR_AUTHORIZE = _permission(
    ResourceType.CONNECTOR,
    Action.AUTHORIZE,
    "Authorize Connectors",
    "Grant OAuth/API credentials for connectors",
)
PERM_CONNECTOR_ROTATE = _permission(
    ResourceType.CONNECTOR,
    Action.ROTATE,
    "Rotate Connector Credentials",
    "Rotate API keys and secrets",
)
PERM_CONNECTOR_TEST = _permission(
    ResourceType.CONNECTOR,
    Action.TEST,
    "Test Connectors",
    "Verify connector health and connectivity",
)
PERM_CONNECTOR_UPDATE = _permission(
    ResourceType.CONNECTOR,
    Action.UPDATE,
    "Update Connectors",
    "Modify connector configurations",
)
PERM_CONNECTOR_ROLLBACK = _permission(
    ResourceType.CONNECTOR,
    Action.ROLLBACK,
    "Rollback Connectors",
    "Revert failed connector operations",
)
PERM_CONNECTOR_CONFIGURE = _permission(
    ResourceType.CONNECTOR,
    Action.CONFIGURE,
    "Configure Connectors",
    "Update and test connectors, and start or cancel connector syncs",
)

# ============================================================================
# WEBHOOK PERMISSIONS
# ============================================================================

PERM_WEBHOOK_READ = _permission(
    ResourceType.WEBHOOK, Action.READ, "View Webhooks", "View webhook configurations"
)
PERM_WEBHOOK_CREATE = _permission(
    ResourceType.WEBHOOK, Action.CREATE, "Create Webhooks", "Create new webhooks"
)
PERM_WEBHOOK_DELETE = _permission(
    ResourceType.WEBHOOK, Action.DELETE, "Delete Webhooks", "Remove webhook configurations"
)
PERM_WEBHOOK_ADMIN = _permission(
    ResourceType.WEBHOOK, Action.ALL, "Webhook Admin", "Admin webhook operations (DLQ management)"
)

# ============================================================================
# INTEGRATIONS PERMISSIONS
# ============================================================================

PERM_INTEGRATIONS_READ = _permission(
    ResourceType.INTEGRATIONS, Action.READ, "View Integrations", "View third-party integrations"
)
PERM_INTEGRATIONS_DELETE = _permission(
    ResourceType.INTEGRATIONS, Action.DELETE, "Delete Integrations", "Remove integrations"
)

# ============================================================================
# GATEWAY PERMISSIONS (OpenClaw and external AI runtimes)
# ============================================================================

PERM_GATEWAY_EXECUTE = _permission(
    ResourceType.GATEWAY,
    Action.EXECUTE,
    "Execute Gateway Tasks",
    "Execute tasks via external AI gateways (OpenClaw)",
)
PERM_GATEWAY_READ = _permission(
    ResourceType.GATEWAY,
    Action.READ,
    "View Gateway",
    "View gateway status and task history",
)
PERM_GATEWAY_CONFIGURE = _permission(
    ResourceType.GATEWAY,
    Action.CONFIGURE,
    "Configure Gateway",
    "Configure gateway settings and policies",
)
PERM_GATEWAY_DEVICE_REGISTER = _permission(
    ResourceType.GATEWAY,
    Action.CREATE,
    "Register Gateway Devices",
    "Register devices with the gateway",
)
PERM_GATEWAY_DEVICE_UNREGISTER = _permission(
    ResourceType.GATEWAY,
    Action.DELETE,
    "Unregister Gateway Devices",
    "Remove devices from the gateway",
)
PERM_GATEWAY_PLUGIN_INSTALL = _permission(
    ResourceType.GATEWAY,
    Action.INSTALL,
    "Install Gateway Plugins",
    "Install plugins via the gateway",
)
PERM_GATEWAY_PLUGIN_UNINSTALL = _permission(
    ResourceType.GATEWAY,
    Action.UNINSTALL,
    "Uninstall Gateway Plugins",
    "Remove plugins from the gateway",
)
PERM_GATEWAY_ADMIN = _permission(
    ResourceType.GATEWAY,
    Action.ADMIN_OP,
    "Administer Gateway",
    "Full administrative access to gateway (allowlists, security policies)",
)

# Gateway - External Agent Management
PERM_GATEWAY_AGENT_CREATE = _permission(
    ResourceType.GATEWAY,
    Action.AGENT_CREATE,
    "Register Gateway Agents",
    "Register external agents with the gateway",
)
PERM_GATEWAY_AGENT_READ = _permission(
    ResourceType.GATEWAY,
    Action.AGENT_READ,
    "View Gateway Agents",
    "View registered external agents and status",
)
PERM_GATEWAY_AGENT_DELETE = _permission(
    ResourceType.GATEWAY,
    Action.AGENT_DELETE,
    "Remove Gateway Agents",
    "Remove external agents from the gateway",
)

# Gateway - Credential Management
PERM_GATEWAY_CREDENTIAL_CREATE = _permission(
    ResourceType.GATEWAY,
    Action.CREDENTIAL_CREATE,
    "Store Gateway Credentials",
    "Store credentials in the gateway vault",
)
PERM_GATEWAY_CREDENTIAL_READ = _permission(
    ResourceType.GATEWAY,
    Action.CREDENTIAL_READ,
    "View Gateway Credentials",
    "View credential metadata (not values)",
)
PERM_GATEWAY_CREDENTIAL_DELETE = _permission(
    ResourceType.GATEWAY,
    Action.CREDENTIAL_DELETE,
    "Delete Gateway Credentials",
    "Delete credentials from the gateway vault",
)
PERM_GATEWAY_CREDENTIAL_ROTATE = _permission(
    ResourceType.GATEWAY,
    Action.CREDENTIAL_ROTATE,
    "Rotate Gateway Credentials",
    "Rotate credentials in the gateway vault",
)

# Gateway - Hybrid Debate
PERM_GATEWAY_HYBRID_DEBATE = _permission(
    ResourceType.GATEWAY,
    Action.HYBRID_DEBATE,
    "Hybrid Gateway Debate",
    "Execute hybrid debates with external agents",
)

# Gateway - Health
PERM_GATEWAY_HEALTH = _permission(
    ResourceType.GATEWAY,
    Action.HEALTH_READ,
    "View Gateway Health",
    "View gateway health status",
)

# ============================================================================
# BOT PERMISSIONS
# ============================================================================

PERM_BOTS_READ = _permission(
    ResourceType.BOT, Action.READ, "View Bot Status", "View bot integration status"
)

# ============================================================================
# REPOSITORY PERMISSIONS
# ============================================================================

PERM_REPOSITORY_READ = _permission(
    ResourceType.REPOSITORY, Action.READ, "View Repositories", "View repository indexing status"
)
PERM_REPOSITORY_CREATE = _permission(
    ResourceType.REPOSITORY, Action.CREATE, "Index Repositories", "Start repository indexing"
)
PERM_REPOSITORY_UPDATE = _permission(
    ResourceType.REPOSITORY,
    Action.UPDATE,
    "Update Repositories",
    "Incrementally update repositories",
)
PERM_REPOSITORY_DELETE = _permission(
    ResourceType.REPOSITORY, Action.DELETE, "Remove Repositories", "Remove indexed repositories"
)

# ============================================================================
# API PERMISSIONS
# ============================================================================

PERM_API_GENERATE_KEY = _permission(
    ResourceType.API, Action.GENERATE_KEY, "Generate API Keys", "Create new API keys"
)
PERM_API_REVOKE_KEY = _permission(
    ResourceType.API, Action.REVOKE_KEY, "Revoke API Keys", "Revoke existing API keys"
)
PERM_API_KEY_CREATE = _permission(
    ResourceType.API_KEY,
    Action.CREATE,
    "Create API Key",
    "Generate personal API keys",
)
PERM_API_KEY_REVOKE = _permission(
    ResourceType.API_KEY,
    Action.REVOKE,
    "Revoke API Key",
    "Revoke personal API keys",
)
PERM_API_KEY_LIST_ALL = _permission(
    ResourceType.API_KEY,
    Action.LIST_ALL,
    "List All API Keys",
    "View all API keys in organization",
)
PERM_API_KEY_EXPORT_SECRET = _permission(
    ResourceType.API_KEY,
    Action.EXPORT_SECRET,
    "Export API Key Secrets",
    "Export API key secrets after creation",
)

# ============================================================================
# VENDOR PERMISSIONS
# ============================================================================

PERM_VENDOR_READ = _permission(
    ResourceType.VENDOR, Action.READ, "View Vendors", "View third-party vendor list"
)
PERM_VENDOR_APPROVE = _permission(
    ResourceType.VENDOR, Action.GRANT, "Approve Vendors", "Approve third-party integrations"
)

# ============================================================================
# PLUGINS PERMISSIONS
# ============================================================================

PERM_PLUGINS_EXECUTE = _permission(
    ResourceType.PLUGINS, Action.EXECUTE, "Execute Plugins", "Run plugin operations"
)
PERM_PLUGINS_INSTALL = _permission(
    ResourceType.PLUGINS, Action.INSTALL, "Install Plugins", "Install new plugins"
)
PERM_PLUGINS_UNINSTALL = _permission(
    ResourceType.PLUGINS, Action.UNINSTALL, "Uninstall Plugins", "Remove plugins"
)
PERM_PLUGINS_SUBMIT = _permission(
    ResourceType.PLUGINS, Action.SUBMIT, "Submit Plugins", "Submit plugins for review"
)

# All integration-related permission exports
__all__ = [
    # Connector
    "PERM_CONNECTOR_READ",
    "PERM_CONNECTOR_CREATE",
    "PERM_CONNECTOR_DELETE",
    "PERM_CONNECTOR_AUTHORIZE",
    "PERM_CONNECTOR_ROTATE",
    "PERM_CONNECTOR_TEST",
    "PERM_CONNECTOR_UPDATE",
    "PERM_CONNECTOR_ROLLBACK",
    "PERM_CONNECTOR_CONFIGURE",
    # Webhook
    "PERM_WEBHOOK_READ",
    "PERM_WEBHOOK_CREATE",
    "PERM_WEBHOOK_DELETE",
    "PERM_WEBHOOK_ADMIN",
    # Integrations
    "PERM_INTEGRATIONS_READ",
    "PERM_INTEGRATIONS_DELETE",
    # Gateway
    "PERM_GATEWAY_EXECUTE",
    "PERM_GATEWAY_READ",
    "PERM_GATEWAY_CONFIGURE",
    "PERM_GATEWAY_DEVICE_REGISTER",
    "PERM_GATEWAY_DEVICE_UNREGISTER",
    "PERM_GATEWAY_PLUGIN_INSTALL",
    "PERM_GATEWAY_PLUGIN_UNINSTALL",
    "PERM_GATEWAY_ADMIN",
    "PERM_GATEWAY_AGENT_CREATE",
    "PERM_GATEWAY_AGENT_READ",
    "PERM_GATEWAY_AGENT_DELETE",
    "PERM_GATEWAY_CREDENTIAL_CREATE",
    "PERM_GATEWAY_CREDENTIAL_READ",
    "PERM_GATEWAY_CREDENTIAL_DELETE",
    "PERM_GATEWAY_CREDENTIAL_ROTATE",
    "PERM_GATEWAY_HYBRID_DEBATE",
    "PERM_GATEWAY_HEALTH",
    # Bots
    "PERM_BOTS_READ",
    # Repository
    "PERM_REPOSITORY_READ",
    "PERM_REPOSITORY_CREATE",
    "PERM_REPOSITORY_UPDATE",
    "PERM_REPOSITORY_DELETE",
    # API
    "PERM_API_GENERATE_KEY",
    "PERM_API_REVOKE_KEY",
    "PERM_API_KEY_CREATE",
    "PERM_API_KEY_REVOKE",
    "PERM_API_KEY_LIST_ALL",
    "PERM_API_KEY_EXPORT_SECRET",
    # Vendor
    "PERM_VENDOR_READ",
    "PERM_VENDOR_APPROVE",
    # Plugins
    "PERM_PLUGINS_EXECUTE",
    "PERM_PLUGINS_INSTALL",
    "PERM_PLUGINS_UNINSTALL",
    "PERM_PLUGINS_SUBMIT",
]
