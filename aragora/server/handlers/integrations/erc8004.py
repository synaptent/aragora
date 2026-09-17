"""
HTTP Handler for ERC-8004 blockchain operations.

Provides REST API endpoints for interacting with ERC-8004 registries:
- GET /api/v1/blockchain/agents - List on-chain agents
- GET /api/v1/blockchain/agents/{token_id} - Get agent identity
- POST /api/v1/blockchain/agents - Register new agent
- GET /api/v1/blockchain/agents/{token_id}/reputation - Get reputation
- POST /api/v1/blockchain/agents/{token_id}/reputation - Submit feedback
- GET /api/v1/blockchain/agents/{token_id}/validations - Get validations
- GET /api/v1/blockchain/config - Get chain configuration
- POST /api/v1/blockchain/sync - Trigger manual sync
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Awaitable

from aragora.blockchain.action_store import enqueue_register_agent_action
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    rate_limit,
)
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.rbac.decorators import require_permission
from aragora.resilience import with_timeout, get_circuit_breaker

logger = logging.getLogger(__name__)

# Re-export names that tests and downstream modules patch against.
# Importing eagerly is safe because these modules do not pull in ``web3``.
from aragora.blockchain.config import get_chain_config as get_chain_config  # noqa: E402

# Optional heavy connectors / adapters -- imported lazily at call-time but
# made available as module-level attributes so ``unittest.mock.patch`` can
# target ``aragora.server.handlers.integrations.erc8004.ERC8004Connector`` etc.
try:
    from aragora.connectors.blockchain import ERC8004Connector as ERC8004Connector  # noqa: E402
except ImportError:  # pragma: no cover – web3 optional
    ERC8004Connector = None  # type: ignore[assignment,misc]

try:
    from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter as ERC8004Adapter  # noqa: E402
except ImportError:  # pragma: no cover – web3 optional
    ERC8004Adapter = None  # type: ignore[assignment,misc]

# Lazy-loaded components
_provider = None
_connector = None
_adapter = None

# Circuit breaker for blockchain operations
_blockchain_circuit_breaker = None


def _get_circuit_breaker():
    """Get or create circuit breaker for blockchain operations."""
    global _blockchain_circuit_breaker
    if _blockchain_circuit_breaker is None:
        _blockchain_circuit_breaker = get_circuit_breaker(
            "erc8004_blockchain",
            failure_threshold=5,
            cooldown_seconds=30,
            half_open_max_calls=2,
        )
    return _blockchain_circuit_breaker


def _get_provider():
    """Get or create the Web3 provider."""
    global _provider
    if _provider is None:
        try:
            from aragora.blockchain.provider import Web3Provider

            _provider = Web3Provider.from_env()
        except ImportError:
            raise ImportError("web3 is required for blockchain endpoints")
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.error("Failed to create Web3Provider: %s", e)
            raise
    return _provider


def _get_connector():
    """Get or create the ERC-8004 connector."""
    global _connector
    if _connector is None:
        from aragora.connectors.blockchain import ERC8004Connector

        _connector = ERC8004Connector.from_env()
    return _connector


def _get_adapter():
    """Get or create the ERC-8004 adapter."""
    global _adapter
    if _adapter is None:
        from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

        _adapter = ERC8004Adapter(provider=_get_provider())
    return _adapter


def _serialize_identity(identity: Any) -> dict[str, Any]:
    """Serialize an on-chain identity into a response-safe dict."""
    return {
        "token_id": identity.token_id,
        "owner": identity.owner,
        "agent_uri": identity.agent_uri,
        "wallet_address": identity.wallet_address,
        "chain_id": identity.chain_id,
        "aragora_agent_id": identity.aragora_agent_id,
        "registered_at": identity.registered_at.isoformat() if identity.registered_at else None,
        "tx_hash": identity.tx_hash,
    }


def _coerce_metadata_value(value: Any) -> bytes:
    """Normalize metadata values to bytes for on-chain storage."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (int, float, bool)):
        return str(value).encode("utf-8")
    raise ValueError("metadata values must be bytes, str, int, float, or bool")


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/config",
    summary="Get blockchain configuration",
    description="Returns current chain configuration and connectivity status.",
    tags=["Blockchain"],
    responses={
        "200": {"description": "Configuration returned"},
        "500": {"description": "Configuration error"},
        "503": {"description": "Circuit breaker open"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=60)
@with_timeout(10.0)
async def handle_blockchain_config() -> HandlerResult:
    """Get blockchain configuration and connectivity status."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        provider = _get_provider()
        config = provider.get_config()

        return json_response(
            {
                "chain_id": config.chain_id,
                "rpc_url": config.rpc_url[:50] + "..."
                if len(config.rpc_url) > 50
                else config.rpc_url,
                "identity_registry": config.identity_registry_address or None,
                "reputation_registry": config.reputation_registry_address or None,
                "validation_registry": config.validation_registry_address or None,
                "block_confirmations": config.block_confirmations,
                "is_connected": provider.is_connected(),
                "health": provider.get_health_status(),
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError, AttributeError) as e:
        logger.error("Error getting blockchain config: %s", e)
        return error_response("Configuration error. Check server logs for details.", status=500)


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/agents/{token_id}",
    summary="Get agent identity",
    description="Retrieves on-chain agent identity by token ID.",
    tags=["Blockchain", "Agents"],
    responses={
        "200": {"description": "Agent identity returned"},
        "404": {"description": "Agent not found"},
        "500": {"description": "Fetch error"},
        "503": {"description": "Circuit breaker open"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=120)
@with_timeout(15.0)
async def handle_get_agent(token_id: int) -> HandlerResult:
    """Get agent identity by token ID."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        from aragora.blockchain.contracts.identity import IdentityRegistryContract

        provider = _get_provider()
        contract = IdentityRegistryContract(provider)
        identity = contract.get_agent(token_id)

        return json_response(_serialize_identity(identity))
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, LookupError, ValueError, RuntimeError) as e:
        logger.error("Error fetching agent %s: %s", token_id, e)
        return error_response("Agent not found or could not be retrieved.", status=404)


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/agents/{token_id}/reputation",
    summary="Get agent reputation",
    description="Retrieves aggregated reputation summary for an agent.",
    tags=["Blockchain", "Reputation"],
    responses={
        "200": {"description": "Reputation summary returned"},
        "404": {"description": "Agent or reputation not found"},
        "500": {"description": "Fetch error"},
        "503": {"description": "Circuit breaker open"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=120)
@with_timeout(15.0)
async def handle_get_reputation(
    token_id: int,
    tag1: str = "",
    tag2: str = "",
) -> HandlerResult:
    """Get reputation summary for an agent."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        from aragora.blockchain.contracts.reputation import ReputationRegistryContract

        provider = _get_provider()
        contract = ReputationRegistryContract(provider)
        summary = contract.get_summary(token_id, tag1=tag1, tag2=tag2)

        return json_response(
            {
                "agent_id": summary.agent_id,
                "count": summary.count,
                "summary_value": summary.summary_value,
                "summary_value_decimals": summary.summary_value_decimals,
                "normalized_value": summary.normalized_value,
                "tag1": summary.tag1,
                "tag2": summary.tag2,
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, LookupError, ValueError, RuntimeError) as e:
        logger.error("Error fetching reputation for agent %s: %s", token_id, e)
        return error_response("Reputation not found or could not be retrieved.", status=404)


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/agents/{token_id}/validations",
    summary="Get agent validations",
    description="Retrieves validation summary for an agent.",
    tags=["Blockchain", "Validation"],
    responses={
        "200": {"description": "Validation summary returned"},
        "404": {"description": "Agent or validations not found"},
        "500": {"description": "Fetch error"},
        "503": {"description": "Circuit breaker open"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=120)
@with_timeout(15.0)
async def handle_get_validations(
    token_id: int,
    tag: str = "",
) -> HandlerResult:
    """Get validation summary for an agent."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        from aragora.blockchain.contracts.validation import ValidationRegistryContract

        provider = _get_provider()
        contract = ValidationRegistryContract(provider)
        summary = contract.get_summary(token_id, tag=tag)

        return json_response(
            {
                "agent_id": summary.agent_id,
                "count": summary.count,
                "average_response": summary.average_response,
                "tag": summary.tag,
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, LookupError, ValueError, RuntimeError) as e:
        logger.error("Error fetching validations for agent %s: %s", token_id, e)
        return error_response("Validations not found or could not be retrieved.", status=404)


@api_endpoint(
    method="POST",
    path="/api/v1/blockchain/sync",
    summary="Trigger blockchain sync",
    description="Manually triggers synchronization between blockchain and Knowledge Mound.",
    tags=["Blockchain", "Sync"],
    responses={
        "200": {"description": "Sync completed"},
        "500": {"description": "Sync error"},
        "503": {"description": "Circuit breaker open"},
    },
)
@require_permission("blockchain:write")
@rate_limit(requests_per_minute=10)
@with_timeout(60.0)
async def handle_blockchain_sync(
    sync_identities: bool = True,
    sync_reputation: bool = True,
    sync_validations: bool = True,
    agent_ids: list[int] | None = None,
) -> HandlerResult:
    """Trigger manual blockchain sync to Knowledge Mound."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        adapter = _get_adapter()
        result = await adapter.sync_to_km(
            agent_ids=agent_ids,
            sync_identities=sync_identities,
            sync_reputation=sync_reputation,
            sync_validations=sync_validations,
        )

        return json_response(
            {
                "records_synced": result.records_synced,
                "records_skipped": result.records_skipped,
                "records_failed": result.records_failed,
                "duration_ms": result.duration_ms,
                "errors": result.errors[:10] if result.errors else [],
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.error("Blockchain sync error: %s", e)
        return error_response("Blockchain sync failed. Check server logs for details.")


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/health",
    summary="Get blockchain connector health",
    description="Returns health status of the blockchain integration.",
    tags=["Blockchain", "Health"],
    responses={
        "200": {"description": "Health status returned"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=60)
async def handle_blockchain_health() -> HandlerResult:
    """Get blockchain connector health status."""
    try:
        connector = _get_connector()
        health = await connector.health_check()

        adapter_status = {}
        try:
            adapter = _get_adapter()
            adapter_status = adapter.get_health_status()
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
            AttributeError,
        ) as e:
            logger.warning("ERC-8004 adapter health check error: %s", e)
            adapter_status = {"error": "Adapter unavailable. Check server logs for details."}

        return json_response(
            {
                "connector": health.to_dict(),
                "adapter": adapter_status,
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return json_response(
            {
                "available": False,
                "error": "Blockchain features are not available. Required dependencies are not installed.",
            }
        )
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError, AttributeError) as e:
        logger.warning("ERC-8004 health check error: %s", e)
        return json_response(
            {
                "available": False,
                "error": "Blockchain feature not available. Check server logs for details.",
            }
        )


@api_endpoint(
    method="GET",
    path="/api/v1/blockchain/agents",
    summary="List on-chain agents",
    description="Lists registered agents with pagination via the Identity Registry.",
    tags=["Blockchain", "Agents"],
    responses={
        "200": {"description": "Agent list returned"},
        "500": {"description": "Listing error"},
        "503": {"description": "Blockchain dependencies not installed or circuit breaker open"},
    },
)
@require_permission("blockchain:read")
@rate_limit(requests_per_minute=60)
@with_timeout(30.0)
async def handle_list_agents(skip: int = 0, limit: int = 100) -> HandlerResult:
    """List registered agents with pagination."""
    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        skip = max(skip, 0)
        limit = min(max(limit, 1), 500)

        from aragora.blockchain.contracts.identity import IdentityRegistryContract

        provider = _get_provider()
        config = provider.get_config()
        if not config.has_identity_registry:
            return error_response(
                "Identity registry is not configured for the current chain",
                status=503,
            )

        contract = IdentityRegistryContract(provider)
        total = int(contract.get_total_supply())

        if total <= 0:
            return json_response(
                {
                    "total": 0,
                    "skip": skip,
                    "limit": limit,
                    "count": 0,
                    "agents": [],
                }
            )

        start_token_id = skip + 1
        if start_token_id > total:
            return json_response(
                {
                    "total": total,
                    "skip": skip,
                    "limit": limit,
                    "count": 0,
                    "agents": [],
                }
            )

        end_token_id = min(total, start_token_id + limit - 1)

        agents: list[dict[str, Any]] = []
        for token_id in range(start_token_id, end_token_id + 1):
            try:
                identity = contract.get_agent(token_id)
                agents.append(_serialize_identity(identity))
            except (
                ConnectionError,
                TimeoutError,
                OSError,
                LookupError,
                ValueError,
                RuntimeError,
            ) as e:
                logger.debug("Could not fetch agent %s: %s", token_id, e)

        return json_response(
            {
                "total": total,
                "skip": skip,
                "limit": limit,
                "count": len(agents),
                "agents": agents,
            }
        )
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.error("Error listing agents: %s", e)
        return error_response("Listing error. Check server logs for details.", status=500)


@api_endpoint(
    method="POST",
    path="/api/v1/blockchain/agents",
    summary="Register new agent on-chain",
    description="Queues a new agent registration for the ERC-8004 Identity Registry.",
    tags=["Blockchain", "Agents"],
    responses={
        "202": {"description": "Agent registration queued"},
        "400": {"description": "Invalid request"},
        "500": {"description": "Registration error"},
        "503": {"description": "Blockchain dependencies not installed or circuit breaker open"},
    },
)
@require_permission("blockchain:write")
@rate_limit(requests_per_minute=10)
@with_timeout(120.0)
async def handle_register_agent(
    agent_uri: str = "",
    metadata: dict[str, Any] | None = None,
    requested_by: str = "",
    approval_id: str = "",
    receipt_id: str = "",
) -> HandlerResult:
    """Queue a new agent registration on the Identity Registry."""
    if not agent_uri:
        return error_response("agent_uri is required", status=400)

    try:
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Blockchain service temporarily unavailable", status=503)

        from aragora.blockchain.contracts.identity import IdentityRegistryContract

        provider = _get_provider()
        config = provider.get_config()
        if not config.has_identity_registry:
            return error_response(
                "Identity registry is not configured for the current chain",
                status=503,
            )

        # Validate metadata values up front, but do not sign inside the request path.
        for value in (metadata or {}).values():
            _coerce_metadata_value(value)

        IdentityRegistryContract(provider)
        action = enqueue_register_agent_action(
            agent_uri=agent_uri,
            metadata=metadata,
            requested_by=requested_by or "system",
            approval_id=approval_id,
            receipt_id=receipt_id,
        )

        return json_response(
            {
                "action_id": action.action_id,
                "status": action.status.value,
                "agent_uri": agent_uri,
                "chain_id": config.chain_id,
                "requires_approval": True,
            },
            status=202,
        )
    except ValueError as e:
        logger.warning("Handler error: %s", e)
        return error_response("Invalid metadata format", status=400)
    except ImportError as e:
        logger.warning("ERC-8004 handler error: %s", e)
        return error_response(
            "Blockchain features are not available. Required dependencies are not installed.",
            status=503,
        )
    except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
        logger.error("Error registering agent: %s", e)
        return error_response("Registration error. Check server logs for details.", status=500)


# Handler registry for unified server
BLOCKCHAIN_HANDLERS = {
    "blockchain_config": handle_blockchain_config,
    "blockchain_list_agents": handle_list_agents,
    "blockchain_register_agent": handle_register_agent,
    "blockchain_get_agent": handle_get_agent,
    "blockchain_get_reputation": handle_get_reputation,
    "blockchain_get_validations": handle_get_validations,
    "blockchain_sync": handle_blockchain_sync,
    "blockchain_health": handle_blockchain_health,
}

__all__ = [
    "BLOCKCHAIN_HANDLERS",
    "ERC8004Handler",
    "handle_blockchain_config",
    "handle_list_agents",
    "handle_register_agent",
    "handle_get_agent",
    "handle_get_reputation",
    "handle_get_validations",
    "handle_blockchain_sync",
    "handle_blockchain_health",
]


def _get_query_param(query_params: dict[str, Any], name: str, default: str = "") -> str:
    value = query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _get_int_query_param(
    query_params: dict[str, Any],
    name: str,
    default: int,
    *,
    min_value: int = 0,
) -> int:
    raw = _get_query_param(query_params, name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    return value


class ERC8004Handler(BaseHandler):
    """Handler for ERC-8004 blockchain API endpoints."""

    ROUTES = [
        "/api/v1/blockchain/config",
        "/api/v1/blockchain/health",
        "/api/v1/blockchain/sync",
        "/api/v1/blockchain/agents",
        "/api/v1/blockchain/agents/*",
    ]

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/blockchain/")

    @require_permission("blockchain:read")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | Awaitable[HandlerResult] | None:
        method = handler.command if hasattr(handler, "command") else "GET"

        if path == "/api/v1/blockchain/config" and method == "GET":
            return handle_blockchain_config()

        if path == "/api/v1/blockchain/health" and method == "GET":
            return handle_blockchain_health()

        if path == "/api/v1/blockchain/sync" and method == "POST":
            body = self.read_json_body(handler) or {}
            return handle_blockchain_sync(
                sync_identities=bool(body.get("sync_identities", True)),
                sync_reputation=bool(body.get("sync_reputation", True)),
                sync_validations=bool(body.get("sync_validations", True)),
                agent_ids=body.get("agent_ids"),
            )

        if path == "/api/v1/blockchain/agents":
            if method == "GET":
                try:
                    skip = _get_int_query_param(query_params, "skip", 0, min_value=0)
                    limit = _get_int_query_param(query_params, "limit", 100, min_value=1)
                except ValueError as e:
                    logger.warning("Handler error: %s", e)
                    return error_response("Invalid request", status=400)
                return handle_list_agents(skip=skip, limit=limit)
            if method == "POST":
                body = self.read_json_body(handler) or {}
                agent_uri = body.get("agent_uri", "")
                metadata = body.get("metadata")
                if metadata is not None and not isinstance(metadata, dict):
                    return error_response("metadata must be an object", status=400)
                return handle_register_agent(
                    agent_uri=agent_uri,
                    metadata=metadata,
                    requested_by=str(body.get("requested_by", "")).strip(),
                    approval_id=str(body.get("approval_id", "")).strip(),
                    receipt_id=str(body.get("receipt_id", "")).strip(),
                )
            return error_response(f"Method {method} not allowed", status=405)

        if path.startswith("/api/v1/blockchain/agents/"):
            suffix = path[len("/api/v1/blockchain/agents/") :]
            parts = [p for p in suffix.split("/") if p]
            if not parts:
                return error_response("Invalid agent path", status=400)
            try:
                token_id = int(parts[0])
            except ValueError:
                return error_response("Invalid token_id", status=400)

            if len(parts) == 1 and method == "GET":
                return handle_get_agent(token_id)

            if len(parts) == 2 and parts[1] == "reputation" and method == "GET":
                tag1 = _get_query_param(query_params, "tag1", "")
                tag2 = _get_query_param(query_params, "tag2", "")
                return handle_get_reputation(token_id, tag1=tag1, tag2=tag2)

            if len(parts) == 2 and parts[1] == "validations" and method == "GET":
                tag = _get_query_param(query_params, "tag", "")
                return handle_get_validations(token_id, tag=tag)

            return error_response("Invalid blockchain agent endpoint", status=400)

        return error_response("Invalid path", status=400)
