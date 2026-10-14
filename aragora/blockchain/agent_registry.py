"""
Blockchain Identity Bridge for Control Plane.

Bridges Aragora's AgentRegistry with ERC-8004 on-chain identities,
enabling agents to have verifiable blockchain-based identities.

Features:
- Link Aragora agents to on-chain token IDs
- Verify agent ownership on-chain
- Sync identity metadata between systems
- Query agents by blockchain address

Usage:
    from aragora.blockchain.agent_registry import BlockchainIdentityBridge
    from aragora.blockchain.provider import Web3Provider

    provider = Web3Provider.from_env()
    bridge = BlockchainIdentityBridge(provider=provider)

    # Link an agent to a blockchain identity
    await bridge.link_agent("claude-api", token_id=42)

    # Get blockchain identity for an agent
    identity = await bridge.get_blockchain_identity("claude-api")
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.blockchain.models import OnChainAgentIdentity
    from aragora.blockchain.provider import Web3Provider

logger = logging.getLogger(__name__)


@dataclass
class AgentBlockchainLink:
    """Link between an Aragora agent and an on-chain identity."""

    aragora_agent_id: str
    chain_id: int
    token_id: int
    owner_address: str
    verified: bool = False
    linked_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BlockchainIdentityBridge:
    """Bridges Aragora agents with ERC-8004 on-chain identities.

    Provides methods to link, verify, and query the relationship between
    Aragora's internal agent IDs and blockchain token IDs.
    """

    def __init__(
        self,
        provider: Web3Provider | None = None,
        agent_registry: Any | None = None,
        persistence_path: str | Path | None = None,
    ) -> None:
        """Initialize the bridge.

        Args:
            provider: Web3Provider for blockchain access.
            agent_registry: Aragora AgentRegistry instance.
            persistence_path: Optional path to a JSON file for persisting
                link state across restarts. When provided, links are loaded
                on init and saved after every mutation.
        """
        self._provider = provider
        self._agent_registry = agent_registry
        self._persistence_path: Path | None = Path(persistence_path) if persistence_path else None
        self._links: dict[str, AgentBlockchainLink] = {}
        self._token_to_agent: dict[tuple[int, int], str] = {}  # (chain_id, token_id) -> agent_id
        self._load_state()

    # -----------------------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------------------

    def _load_state(self) -> None:
        """Load persisted link state from JSON file (if configured)."""
        if self._persistence_path is None:
            return
        if not self._persistence_path.exists():
            return
        try:
            raw = self._persistence_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            for entry in data.get("links", []):
                link = AgentBlockchainLink(
                    aragora_agent_id=entry["aragora_agent_id"],
                    chain_id=entry["chain_id"],
                    token_id=entry["token_id"],
                    owner_address=entry.get("owner_address", ""),
                    verified=entry.get("verified", False),
                    linked_at=entry.get("linked_at"),
                    metadata=entry.get("metadata", {}),
                )
                self._links[link.aragora_agent_id] = link
                self._token_to_agent[(link.chain_id, link.token_id)] = link.aragora_agent_id
            logger.info(
                "Loaded %d blockchain identity links from %s",
                len(self._links),
                self._persistence_path,
            )
        except (json.JSONDecodeError, TypeError, KeyError, OSError) as exc:
            logger.warning(
                "Failed to load blockchain identity state from %s: %s", self._persistence_path, exc
            )

    def _save_state(self) -> None:
        """Persist current link state to JSON file (if configured)."""
        if self._persistence_path is None:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            entries = [asdict(link) for link in self._links.values()]
            payload = {"links": entries}
            self._persistence_path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to save blockchain identity state to %s: %s", self._persistence_path, exc
            )

    def _get_provider(self) -> Web3Provider:
        """Get or create the Web3 provider."""
        if self._provider is None:
            from aragora.blockchain.provider import Web3Provider

            self._provider = Web3Provider.from_env()
        return self._provider

    def _get_identity_contract(self) -> Any:
        """Get the Identity Registry contract."""
        from aragora.blockchain.contracts.identity import IdentityRegistryContract

        return IdentityRegistryContract(self._get_provider())

    async def link_agent(
        self,
        aragora_agent_id: str,
        token_id: int,
        chain_id: int | None = None,
        verify: bool = True,
    ) -> AgentBlockchainLink:
        """Link an Aragora agent to an on-chain identity.

        Args:
            aragora_agent_id: Internal Aragora agent ID.
            token_id: ERC-721 token ID on the Identity Registry.
            chain_id: Chain ID. Defaults to provider's default.
            verify: If True, verifies the token exists on-chain.

        Returns:
            AgentBlockchainLink record.

        Raises:
            ValueError: If verification fails.
        """
        provider = self._get_provider()
        config = provider.get_config(chain_id)
        resolved_chain_id = config.chain_id

        owner_address = ""
        verified = False

        if verify:
            try:
                identity = self._get_identity_contract().get_agent(token_id)
                owner_address = identity.owner
                verified = True
            except (RuntimeError, ValueError, OSError, ConnectionError, KeyError) as e:
                raise ValueError(
                    f"Failed to verify token {token_id} on chain {resolved_chain_id}: {e}"
                )

        from datetime import datetime

        link = AgentBlockchainLink(
            aragora_agent_id=aragora_agent_id,
            chain_id=resolved_chain_id,
            token_id=token_id,
            owner_address=owner_address,
            verified=verified,
            linked_at=datetime.now().isoformat(),
        )

        self._links[aragora_agent_id] = link
        self._token_to_agent[(resolved_chain_id, token_id)] = aragora_agent_id

        logger.info(
            "Linked agent %s to token %s on chain %s", aragora_agent_id, token_id, resolved_chain_id
        )
        self._save_state()
        return link

    async def unlink_agent(self, aragora_agent_id: str) -> bool:
        """Remove the link between an Aragora agent and its blockchain identity.

        Args:
            aragora_agent_id: Internal Aragora agent ID.

        Returns:
            True if unlinked, False if not found.
        """
        if aragora_agent_id not in self._links:
            return False

        link = self._links[aragora_agent_id]
        del self._token_to_agent[(link.chain_id, link.token_id)]
        del self._links[aragora_agent_id]

        logger.info("Unlinked agent %s", aragora_agent_id)
        self._save_state()
        return True

    async def get_blockchain_identity(
        self,
        aragora_agent_id: str,
    ) -> OnChainAgentIdentity | None:
        """Get the on-chain identity for an Aragora agent.

        Args:
            aragora_agent_id: Internal Aragora agent ID.

        Returns:
            OnChainAgentIdentity or None if not linked.
        """
        link = self._links.get(aragora_agent_id)
        if not link:
            return None

        try:
            return self._get_identity_contract().get_agent(link.token_id)
        except (RuntimeError, ValueError, OSError, ConnectionError, KeyError) as e:
            logger.warning("Failed to fetch identity for %s: %s", aragora_agent_id, e)
            return None

    async def get_agent_by_token(
        self,
        token_id: int,
        chain_id: int | None = None,
    ) -> str | None:
        """Get the Aragora agent ID linked to a token.

        Args:
            token_id: On-chain token ID.
            chain_id: Chain ID. Defaults to provider's default.

        Returns:
            Aragora agent ID or None if not linked.
        """
        provider = self._get_provider()
        config = provider.get_config(chain_id)
        return self._token_to_agent.get((config.chain_id, token_id))

    async def get_agents_by_owner(
        self,
        owner_address: str,
    ) -> list[str]:
        """Get all Aragora agents linked to a blockchain address.

        Args:
            owner_address: Ethereum address.

        Returns:
            List of Aragora agent IDs.
        """
        return [
            link.aragora_agent_id
            for link in self._links.values()
            if link.owner_address.lower() == owner_address.lower()
        ]

    def get_link(self, aragora_agent_id: str) -> AgentBlockchainLink | None:
        """Get the link record for an agent.

        Args:
            aragora_agent_id: Internal Aragora agent ID.

        Returns:
            AgentBlockchainLink or None.
        """
        return self._links.get(aragora_agent_id)

    def get_all_links(self) -> list[AgentBlockchainLink]:
        """Get all agent-blockchain links.

        Returns:
            List of all AgentBlockchainLink records.
        """
        return list(self._links.values())

    async def verify_link(self, aragora_agent_id: str) -> bool:
        """Verify that a link is still valid on-chain.

        Args:
            aragora_agent_id: Internal Aragora agent ID.

        Returns:
            True if verified, False otherwise.
        """
        link = self._links.get(aragora_agent_id)
        if not link:
            return False

        try:
            identity = self._get_identity_contract().get_agent(link.token_id)
            link.owner_address = identity.owner
            link.verified = True
            self._save_state()
            return True
        except (RuntimeError, ValueError, OSError, ConnectionError, KeyError) as e:
            logger.warning("Failed to verify link for %s: %s", aragora_agent_id, e)
            link.verified = False
            self._save_state()
            return False

    async def sync_from_blockchain(self, limit: int = 100) -> int:
        """Discover and link agents from blockchain.

        Scans the Identity Registry for agents with metadata containing
        Aragora agent IDs and creates links automatically.

        Args:
            limit: Maximum agents to scan.

        Returns:
            Number of new links created.
        """
        links_created = 0

        try:
            contract = self._get_identity_contract()
            total = contract.get_total_supply()

            for token_id in range(1, min(total + 1, limit + 1)):
                try:
                    identity = contract.get_agent(token_id)

                    # Check if already linked
                    chain_id = identity.chain_id
                    if (chain_id, token_id) in self._token_to_agent:
                        continue

                    # Check for Aragora agent ID in metadata
                    aragora_id = identity.aragora_agent_id
                    if not aragora_id:
                        # Try to extract from on-chain metadata
                        try:
                            metadata_bytes = contract.get_metadata(token_id, "aragora_agent_id")
                            if metadata_bytes:
                                aragora_id = metadata_bytes.decode("utf-8").strip()
                        except (ValueError, UnicodeDecodeError, KeyError) as exc:
                            logger.debug("Failed to decode metadata: %s", exc)

                    if aragora_id:
                        await self.link_agent(
                            aragora_agent_id=aragora_id,
                            token_id=token_id,
                            chain_id=chain_id,
                            verify=False,  # Already verified by fetch
                        )
                        links_created += 1

                except (RuntimeError, ValueError, OSError, ConnectionError, KeyError) as e:
                    logger.debug("Failed to process token %s: %s", token_id, e)

        except (RuntimeError, ValueError, OSError, ConnectionError, KeyError) as e:
            logger.error("Sync from blockchain failed: %s", e)

        return links_created


# Singleton instance
_bridge: BlockchainIdentityBridge | None = None


def get_blockchain_identity_bridge() -> BlockchainIdentityBridge:
    """Get the singleton BlockchainIdentityBridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = BlockchainIdentityBridge()
    return _bridge


__all__ = [
    "AgentBlockchainLink",
    "BlockchainIdentityBridge",
    "get_blockchain_identity_bridge",
]
