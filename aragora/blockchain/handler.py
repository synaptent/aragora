"""
ERC-8004 blockchain handler for managing agent identity, reputation, and validation.

Provides a class-based handler that wraps blockchain operations behind a clean API
suitable for both direct use and HTTP endpoint integration.

Usage:
    from aragora.blockchain.handler import ERC8004Handler

    handler = ERC8004Handler(ctx)
    config = await handler.handle_blockchain_config({})
    agent = await handler.handle_get_agent({"token_id": "42"}, query_params={})
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Ethereum address pattern: 0x followed by 40 hex characters
_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _validate_token_id(raw: str) -> int:
    """Parse and validate a token ID string, raising ValueError if invalid."""
    try:
        token_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid token_id: {raw!r}") from exc
    if token_id < 0:
        raise ValueError(f"Invalid token_id: must be non-negative, got {token_id}")
    return token_id


def _validate_eth_address(address: str) -> str:
    """Validate an Ethereum address, raising ValueError if invalid."""
    if not _ETH_ADDRESS_RE.match(address):
        raise ValueError(f"Invalid Ethereum address: {address!r}")
    return address


class ERC8004Handler:
    """Handler for ERC-8004 blockchain API endpoints.

    Provides methods for querying on-chain agent identity, reputation,
    and validation registries through a uniform interface.
    """

    ROUTES = [
        {"path": "/api/v1/blockchain/config", "method": "GET"},
        {"path": "/api/v1/blockchain/health", "method": "GET"},
        {"path": "/api/v1/blockchain/sync", "method": "POST"},
        {"path": "/api/v1/blockchain/agents", "method": "GET"},
        {"path": "/api/v1/blockchain/agents/{token_id}", "method": "GET"},
        {"path": "/api/v1/blockchain/agents/{token_id}/reputation", "method": "GET"},
        {"path": "/api/v1/blockchain/agents/{token_id}/validations", "method": "GET"},
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    def get_routes(self) -> list[dict[str, str]]:
        """Return the list of routes this handler manages."""
        return list(self.ROUTES)

    def can_handle(self, path: str) -> bool:
        """Check whether *path* falls under the blockchain namespace."""
        return path.startswith("/api/v1/blockchain/") or path == "/api/v1/blockchain"

    # ------------------------------------------------------------------
    # Endpoint methods
    # ------------------------------------------------------------------

    async def handle_blockchain_config(
        self,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return the current blockchain / chain configuration."""
        # Import from the server handler module so that test patches on
        # ``aragora.server.handlers.integrations.erc8004.get_chain_config`` are honoured.
        from aragora.server.handlers.integrations import erc8004 as _erc

        config = _erc.get_chain_config()
        return {
            "chain_id": config.chain_id,
            "rpc_url": getattr(config, "rpc_url", ""),
            "identity_registry": getattr(config, "identity_registry_address", None),
            "reputation_registry": getattr(config, "reputation_registry_address", None),
            "validation_registry": getattr(config, "validation_registry_address", None),
        }

    async def handle_get_agent(
        self,
        params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get a single agent identity by token ID."""
        token_id = _validate_token_id(params.get("token_id", ""))

        from aragora.server.handlers.integrations import erc8004 as _erc

        connector = _erc.ERC8004Connector()
        result = connector.fetch(f"identity:{self.ctx.get('chain_id', 1)}:{token_id}")
        if result is None:
            raise LookupError(f"Agent with token_id={token_id} not found")

        metadata = getattr(result, "metadata", {}) or {}
        return {
            "token_id": metadata.get("token_id", token_id),
            "owner": metadata.get("owner"),
            "content": getattr(result, "content", None),
        }

    async def handle_get_reputation(
        self,
        params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get reputation data for an agent."""
        token_id = _validate_token_id(params.get("token_id", ""))

        from aragora.server.handlers.integrations import erc8004 as _erc

        connector = _erc.ERC8004Connector()
        result = connector.fetch(f"reputation:{self.ctx.get('chain_id', 1)}:{token_id}")
        if result is None:
            raise LookupError(f"Reputation for token_id={token_id} not found")

        metadata = getattr(result, "metadata", {}) or {}
        return metadata

    async def handle_get_validations(
        self,
        params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get validation records for an agent."""
        token_id = _validate_token_id(params.get("token_id", ""))

        from aragora.server.handlers.integrations import erc8004 as _erc

        connector = _erc.ERC8004Connector()
        result = connector.fetch(f"validation:{self.ctx.get('chain_id', 1)}:{token_id}")
        if result is None:
            raise LookupError(f"Validations for token_id={token_id} not found")

        metadata = getattr(result, "metadata", {}) or {}
        return metadata

    async def handle_blockchain_sync(
        self,
        params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Trigger a manual sync between blockchain and Knowledge Mound."""
        from aragora.server.handlers.integrations import erc8004 as _erc

        adapter = _erc.ERC8004Adapter()
        result = await adapter.sync_to_km()
        return {
            "records_synced": getattr(result, "records_synced", 0),
            "errors": getattr(result, "errors", []),
        }

    async def handle_blockchain_health(
        self,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return health status of the blockchain connector."""
        from aragora.server.handlers.integrations import erc8004 as _erc

        connector = _erc.ERC8004Connector()
        health = connector.health_check()
        if isinstance(health, dict):
            return health
        return health.to_dict() if hasattr(health, "to_dict") else {"healthy": bool(health)}

    async def handle_list_agents(
        self,
        params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """List registered on-chain agents, optionally filtered by owner."""
        query_params = query_params or {}
        owner = query_params.get("owner")

        if owner is not None:
            _validate_eth_address(owner)

        from aragora.server.handlers.integrations import erc8004 as _erc

        connector = _erc.ERC8004Connector()

        if owner:
            results = await connector.search_by_owner(owner)
        else:
            results = await connector.search(query="*")

        agents = []
        for r in results:
            agents.append(
                {
                    "id": getattr(r, "id", None),
                    "title": getattr(r, "title", None),
                    "metadata": getattr(r, "metadata", {}),
                }
            )
        return {"agents": agents}


__all__ = ["ERC8004Handler"]
