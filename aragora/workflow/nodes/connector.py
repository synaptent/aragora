"""
Connector Step for workflow-connector integration.

Provides first-class connector support in workflows, allowing workflows
to leverage all 100+ connectors (GitHub, Slack, DocuSign, QuickBooks, etc.)
with proper credential management, error handling, and result caching.

Usage:
    step = ConnectorStep(
        name="Fetch GitHub Issue",
        config={
            "connector_type": "github",
            "operation": "fetch",
            "params": {
                "owner": "myorg",
                "repo": "myrepo",
                "issue_number": "{inputs.issue_id}",
            },
            "credentials_key": "github_token",  # Optional - key in context.state
        }
    )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aragora.exceptions import ConnectorError, ConnectorRateLimitError
from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_DELAY = 5.0


def _retry_delay(error: ConnectorError) -> float:
    """Seconds to wait before retrying after ``error``: its ``retry_after`` when set."""
    if error.retry_after:
        return error.retry_after
    return 60.0 if isinstance(error, ConnectorRateLimitError) else _DEFAULT_RETRY_DELAY


class ConnectorOperation(str, Enum):
    """Standard connector operations."""

    SEARCH = "search"
    FETCH = "fetch"
    LIST = "list"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SYNC = "sync"
    CUSTOM = "custom"


@dataclass
class ConnectorMetadata:
    """Metadata about a connector type."""

    name: str
    description: str
    module_path: str
    class_name: str
    operations: list[str]
    auth_required: bool = True
    auth_type: str = "api_key"  # api_key, oauth2, basic, none


# Registry of known connector types and their implementations
_CONNECTOR_REGISTRY: dict[str, ConnectorMetadata] = {
    # Core connectors
    "github": ConnectorMetadata(
        name="GitHub",
        description="GitHub repositories, issues, PRs, and discussions",
        module_path="aragora.connectors.github",
        class_name="GitHubConnector",
        operations=["search", "fetch", "list"],
        auth_type="api_key",
    ),
    "web": ConnectorMetadata(
        name="Web",
        description="Web pages and content fetching",
        module_path="aragora.connectors.web",
        class_name="WebConnector",
        operations=["search", "fetch"],
        auth_required=False,
    ),
    "local_docs": ConnectorMetadata(
        name="Local Docs",
        description="Local documentation and files",
        module_path="aragora.connectors.local_docs",
        class_name="LocalDocsConnector",
        operations=["search", "fetch", "list"],
        auth_required=False,
    ),
    # News and Social
    "hackernews": ConnectorMetadata(
        name="Hacker News",
        description="Hacker News stories and discussions",
        module_path="aragora.connectors.hackernews",
        class_name="HackerNewsConnector",
        operations=["search", "fetch", "list"],
        auth_required=False,
    ),
    "reddit": ConnectorMetadata(
        name="Reddit",
        description="Reddit posts and comments",
        module_path="aragora.connectors.reddit",
        class_name="RedditConnector",
        operations=["search", "fetch"],
        auth_type="oauth2",
    ),
    "twitter": ConnectorMetadata(
        name="Twitter",
        description="Twitter/X posts and trends",
        module_path="aragora.connectors.twitter",
        class_name="TwitterConnector",
        operations=["search", "fetch"],
        auth_type="oauth2",
    ),
    "newsapi": ConnectorMetadata(
        name="News API",
        description="News articles from multiple sources",
        module_path="aragora.connectors.newsapi",
        class_name="NewsAPIConnector",
        operations=["search", "fetch"],
        auth_type="api_key",
    ),
    # Academic
    "arxiv": ConnectorMetadata(
        name="ArXiv",
        description="Academic papers and preprints",
        module_path="aragora.connectors.arxiv",
        class_name="ArXivConnector",
        operations=["search", "fetch"],
        auth_required=False,
    ),
    "wikipedia": ConnectorMetadata(
        name="Wikipedia",
        description="Wikipedia articles",
        module_path="aragora.connectors.wikipedia",
        class_name="WikipediaConnector",
        operations=["search", "fetch"],
        auth_required=False,
    ),
    # Enterprise
    "sql": ConnectorMetadata(
        name="SQL Database",
        description="Query SQL databases (PostgreSQL, MySQL, SQLite)",
        module_path="aragora.connectors.sql",
        class_name="SQLConnector",
        operations=["search", "fetch", "custom"],
        auth_type="basic",
    ),
    "sec": ConnectorMetadata(
        name="SEC EDGAR",
        description="SEC financial filings",
        module_path="aragora.connectors.sec",
        class_name="SECConnector",
        operations=["search", "fetch"],
        auth_required=False,
    ),
    # Legal
    "docusign": ConnectorMetadata(
        name="DocuSign",
        description="E-signature and envelope management",
        module_path="aragora.connectors.legal.docusign",
        class_name="DocuSignConnector",
        operations=["fetch", "create", "list", "custom"],
        auth_type="oauth2",
    ),
    # Accounting
    "quickbooks": ConnectorMetadata(
        name="QuickBooks",
        description="QuickBooks Online accounting",
        module_path="aragora.connectors.accounting.quickbooks",
        class_name="QuickBooksConnector",
        operations=["search", "fetch", "create", "update", "sync"],
        auth_type="oauth2",
    ),
    "xero": ConnectorMetadata(
        name="Xero",
        description="Xero accounting integration",
        module_path="aragora.connectors.accounting.xero",
        class_name="XeroConnector",
        operations=["search", "fetch", "create", "update"],
        auth_type="oauth2",
    ),
    "plaid": ConnectorMetadata(
        name="Plaid",
        description="Bank account and transaction data",
        module_path="aragora.connectors.accounting.plaid",
        class_name="PlaidConnector",
        operations=["fetch", "list", "sync"],
        auth_type="api_key",
    ),
    # DevOps
    "pagerduty": ConnectorMetadata(
        name="PagerDuty",
        description="Incident management",
        module_path="aragora.connectors.devops.pagerduty",
        class_name="PagerDutyConnector",
        operations=["fetch", "create", "update", "list"],
        auth_type="api_key",
    ),
    # Chat
    "slack": ConnectorMetadata(
        name="Slack",
        description="Slack messaging and channels",
        module_path="aragora.connectors.chat.slack",
        class_name="SlackConnector",
        operations=["search", "fetch", "create", "list"],
        auth_type="oauth2",
    ),
    "discord": ConnectorMetadata(
        name="Discord",
        description="Discord messages and channels",
        module_path="aragora.connectors.chat.discord",
        class_name="DiscordConnector",
        operations=["fetch", "create", "list"],
        auth_type="api_key",
    ),
    # E-commerce
    "shopify": ConnectorMetadata(
        name="Shopify",
        description="Shopify store data",
        module_path="aragora.connectors.ecommerce.shopify",
        class_name="ShopifyConnector",
        operations=["search", "fetch", "create", "update", "list"],
        auth_type="api_key",
    ),
    # Support
    "zendesk": ConnectorMetadata(
        name="Zendesk",
        description="Zendesk support tickets",
        module_path="aragora.connectors.support.zendesk",
        class_name="ZendeskConnector",
        operations=["search", "fetch", "create", "update"],
        auth_type="api_key",
    ),
}


def register_connector(
    name: str,
    metadata: ConnectorMetadata,
) -> None:
    """Register a connector type for use in workflows."""
    _CONNECTOR_REGISTRY[name] = metadata
    logger.debug("Registered connector type: %s", name)


def get_connector_metadata(name: str) -> ConnectorMetadata | None:
    """Get metadata for a connector type."""
    return _CONNECTOR_REGISTRY.get(name)


def list_connectors() -> list[ConnectorMetadata]:
    """List all registered connector types."""
    return list(_CONNECTOR_REGISTRY.values())


async def create_connector(
    connector_type: str,
    config: dict[str, Any],
) -> Any:
    """
    Dynamically create a connector instance.

    Args:
        connector_type: Type of connector (e.g., "github", "slack")
        config: Connector configuration including credentials

    Returns:
        Instantiated connector

    Raises:
        ValueError: If connector type is unknown
        ImportError: If connector module cannot be loaded
    """
    metadata = _CONNECTOR_REGISTRY.get(connector_type)
    if not metadata:
        raise ValueError(f"Unknown connector type: {connector_type}")

    # Dynamic import
    import importlib

    try:
        module = importlib.import_module(metadata.module_path)
        connector_class = getattr(module, metadata.class_name)
    except (ImportError, AttributeError) as e:
        logger.error("Failed to load connector %s: %s", connector_type, e)
        raise ImportError(f"Connector {connector_type} not available: {e}")

    # Instantiate connector
    return connector_class(**config)


class ConnectorStep(BaseStep):
    """
    Workflow step that executes connector operations.

    Provides access to all registered connectors with:
    - Dynamic connector instantiation
    - Credential management via context.state
    - Parameter interpolation from workflow context
    - Error handling with retries
    - Result caching

    Config options:
        connector_type: str - Type of connector (e.g., "github", "slack", "quickbooks")
        operation: str - Operation to perform (search, fetch, create, update, list, sync, custom)
        params: dict - Parameters for the operation (supports {placeholder} interpolation)
        credentials_key: str - Key in context.state containing credentials (optional)
        credentials: dict - Direct credentials (optional, less secure)
        custom_method: str - Method name for custom operations
        timeout_seconds: int - Operation timeout (default: 30)
        retry_on_error: bool - Whether to retry on transient errors (default: True)
        max_retries: int - Maximum retry attempts (default: 3)

    Example configs:

        # GitHub issue fetch
        {
            "connector_type": "github",
            "operation": "fetch",
            "params": {
                "owner": "myorg",
                "repo": "myrepo",
                "issue_number": "{inputs.issue_id}",
            }
        }

        # QuickBooks invoice create
        {
            "connector_type": "quickbooks",
            "operation": "create",
            "params": {
                "resource_type": "invoice",
                "data": "{step.invoice_data.result}",
            },
            "credentials_key": "qbo_credentials",
        }

        # DocuSign envelope status
        {
            "connector_type": "docusign",
            "operation": "custom",
            "custom_method": "get_envelope_status",
            "params": {
                "envelope_id": "{inputs.envelope_id}",
            }
        }
    """

    def __init__(
        self,
        name: str,
        config: dict[str, Any] | None = None,
    ):
        super().__init__(name, config)
        self._connector_cache: dict[str, Any] = {}

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the connector operation."""
        connector_type = self._config.get("connector_type")
        operation = self._config.get("operation", "fetch")
        params = self._config.get("params", {})
        timeout = self._config.get("timeout_seconds", 30)
        retry_on_error = self._config.get("retry_on_error", True)
        max_retries = self._config.get("max_retries", 3)

        if not connector_type:
            raise ValueError("connector_type is required")

        # Get connector metadata
        metadata = get_connector_metadata(connector_type)
        if not metadata:
            raise ValueError(f"Unknown connector type: {connector_type}")

        # Validate operation
        if operation not in metadata.operations and operation != "custom":
            raise ValueError(
                f"Operation '{operation}' not supported by {connector_type}. "
                f"Supported: {metadata.operations}"
            )

        # Get credentials
        connector_config = self._get_credentials(context)

        # Interpolate parameters
        interpolated_params = self._interpolate_params(params, context)

        # Create connector (with caching)
        cache_key = f"{connector_type}:{hash(str(sorted(connector_config.items())))}"
        if cache_key not in self._connector_cache:
            self._connector_cache[cache_key] = await create_connector(
                connector_type, connector_config
            )
        connector = self._connector_cache[cache_key]

        # Execute operation with retry
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._execute_operation(connector, operation, interpolated_params),
                    timeout=timeout,
                )
                logger.info(
                    "[ConnectorStep] %s: %s.%s succeeded", self._name, connector_type, operation
                )
                return self._format_result(result)

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"Operation timed out after {timeout}s")
                if not retry_on_error or attempt >= max_retries:
                    raise last_error
                delay = _DEFAULT_RETRY_DELAY
                logger.warning("[ConnectorStep] %s: Timeout, retrying in %ss...", self._name, delay)
                await asyncio.sleep(delay)

            except ConnectorError as e:
                last_error = e
                if not retry_on_error or not e.is_retryable or attempt >= max_retries:
                    raise
                delay = _retry_delay(e)
                logger.warning("[ConnectorStep] %s: %s, retrying in %ss...", self._name, e, delay)
                await asyncio.sleep(delay)

            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                ConnectionError,
                AttributeError,
                KeyError,
            ) as e:
                logger.error("[ConnectorStep] %s: Unexpected error: %s", self._name, e)
                raise

        raise last_error or RuntimeError("Connector operation failed")

    def _get_credentials(self, context: WorkflowContext) -> dict[str, Any]:
        """Get credentials from config or context."""
        # Direct credentials in config (less secure, for testing)
        if "credentials" in self._config:
            return self._config["credentials"]

        # Credentials key in context.state
        credentials_key = self._config.get("credentials_key")
        if credentials_key:
            creds = context.get_state(credentials_key)
            if creds:
                return creds if isinstance(creds, dict) else {"api_key": creds}

        # Try to get from workflow inputs
        connector_type = self._config.get("connector_type", "")
        input_key = f"{connector_type}_credentials"
        if input_key in context.inputs:
            return context.inputs[input_key]

        # Return empty config (connector may use env vars)
        return {}

    def _interpolate_params(
        self,
        params: dict[str, Any],
        context: WorkflowContext,
    ) -> dict[str, Any]:
        """Interpolate parameter placeholders with context values."""
        result = {}
        for key, value in params.items():
            if isinstance(value, str):
                result[key] = self._interpolate_string(value, context)
            elif isinstance(value, dict):
                result[key] = self._interpolate_params(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._interpolate_string(v, context) if isinstance(v, str) else v for v in value
                ]
            else:
                result[key] = value
        return result

    def _interpolate_string(self, value: str, context: WorkflowContext) -> Any:
        """Interpolate a single string value."""
        import re

        # Pattern: {inputs.key}, {step.step_id.key}, {state.key}
        pattern = r"\{(inputs|step|state)\.([^}]+)\}"

        def replace(match: re.Match) -> str:
            source = match.group(1)
            path = match.group(2)

            if source == "inputs":
                return str(context.get_input(path, match.group(0)))
            elif source == "step":
                parts = path.split(".", 1)
                if len(parts) == 2:
                    step_output = context.get_step_output(parts[0], {})
                    if isinstance(step_output, dict):
                        return str(step_output.get(parts[1], match.group(0)))
                return str(context.get_step_output(path, match.group(0)))
            elif source == "state":
                return str(context.get_state(path, match.group(0)))
            return match.group(0)

        # If entire value is a placeholder, return the actual value (not stringified)
        full_match = re.fullmatch(pattern, value)
        if full_match:
            source = full_match.group(1)
            path = full_match.group(2)
            if source == "inputs":
                return context.get_input(path, value)
            elif source == "step":
                parts = path.split(".", 1)
                if len(parts) == 2:
                    step_output = context.get_step_output(parts[0], {})
                    if isinstance(step_output, dict):
                        return step_output.get(parts[1], value)
                return context.get_step_output(path, value)
            elif source == "state":
                return context.get_state(path, value)

        # Otherwise, do string interpolation
        return re.sub(pattern, replace, value)

    async def _execute_operation(
        self,
        connector: Any,
        operation: str,
        params: dict[str, Any],
    ) -> Any:
        """Execute the connector operation."""
        if operation == "search":
            query = params.get("query", "")
            return await connector.search(
                query, **{k: v for k, v in params.items() if k != "query"}
            )

        elif operation == "fetch":
            source_id = params.get("source_id") or params.get("id")
            if source_id:
                return await connector.fetch(source_id)
            # Some connectors have fetch methods with different signatures
            return await connector.fetch(**params)

        elif operation == "list":
            if hasattr(connector, "list"):
                return await connector.list(**params)
            elif hasattr(connector, "list_all"):
                return await connector.list_all(**params)
            raise ValueError("Connector does not support list operation")

        elif operation == "create":
            if hasattr(connector, "create"):
                return await connector.create(**params)
            raise ValueError("Connector does not support create operation")

        elif operation == "update":
            if hasattr(connector, "update"):
                return await connector.update(**params)
            raise ValueError("Connector does not support update operation")

        elif operation == "delete":
            if hasattr(connector, "delete"):
                return await connector.delete(**params)
            raise ValueError("Connector does not support delete operation")

        elif operation == "sync":
            if hasattr(connector, "sync"):
                return await connector.sync(**params)
            raise ValueError("Connector does not support sync operation")

        elif operation == "custom":
            method_name = self._config.get("custom_method")
            if not method_name:
                raise ValueError("custom_method required for custom operation")
            method = getattr(connector, method_name, None)
            if not method:
                raise ValueError(f"Connector has no method '{method_name}'")
            return (
                await method(**params) if asyncio.iscoroutinefunction(method) else method(**params)
            )

        else:
            raise ValueError(f"Unknown operation: {operation}")

    def _format_result(self, result: Any) -> Any:
        """Format connector result for workflow output."""
        # Handle Evidence objects
        if hasattr(result, "to_dict"):
            return result.to_dict()

        # Handle lists of Evidence
        if isinstance(result, list) and result and hasattr(result[0], "to_dict"):
            return [r.to_dict() if hasattr(r, "to_dict") else r for r in result]

        return result


# Alias for convenience
Connector = ConnectorStep
