"""Receipt settlement integration -- wires DecisionReceipt to blockchain anchoring.

Connects the gauntlet receipt system to ERC-8004 on-chain anchoring:
1. Takes a DecisionReceipt and anchors its hash on-chain (or locally)
2. Populates the receipt's ``settlement_status`` field with anchoring details
3. Optionally pushes participating agent reputation data to the registry
4. Gracefully degrades to local-only mode when no chain is configured

Usage:
    from aragora.blockchain.receipt_settlement import ReceiptSettlementService

    service = ReceiptSettlementService()
    receipt = await service.anchor_receipt(receipt)
    # receipt.settlement_status is now populated

    # Check anchoring status
    status = service.get_settlement_status(receipt)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from aragora.blockchain.receipt_anchor import ReceiptAnchor

logger = logging.getLogger(__name__)


@dataclass
class SettlementResult:
    """Result of anchoring a receipt on-chain.

    Attributes:
        anchored: Whether the receipt was successfully anchored.
        anchor_id: Transaction hash or local anchor ID.
        chain_id: Chain ID if on-chain, None if local.
        block_number: Block number if on-chain and known.
        local_only: True if only locally anchored (no blockchain).
        receipt_hash: The SHA-256 hash that was anchored.
        timestamp: When the anchoring occurred.
        error: Error message if anchoring failed.
    """

    anchored: bool = False
    anchor_id: str = ""
    chain_id: int | None = None
    block_number: int | None = None
    local_only: bool = True
    receipt_hash: str = ""
    timestamp: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for receipt settlement_status field."""
        result: dict[str, Any] = {
            "anchored": self.anchored,
            "anchor_id": self.anchor_id,
            "local_only": self.local_only,
            "receipt_hash": self.receipt_hash,
            "timestamp": self.timestamp,
        }
        if self.chain_id is not None:
            result["chain_id"] = self.chain_id
        if self.block_number is not None:
            result["block_number"] = self.block_number
        if self.error:
            result["error"] = self.error
        return result


class ReceiptSettlementService:
    """Service that anchors decision receipts to the blockchain.

    Provides a high-level API for anchoring receipts and managing
    settlement state. Works in two modes:

    1. **On-chain mode**: When a provider and signer are configured,
       submits receipt hashes to the ERC-8004 Validation Registry.
    2. **Local mode**: When no chain is configured, creates local
       anchor records for offline verification.

    The service is intentionally stateless -- all state is stored
    either on-chain or in the receipt's ``settlement_status`` field.

    Args:
        provider: Optional Web3Provider for on-chain anchoring.
        signer: Optional WalletSigner for signing transactions.
        identity_bridge: Optional BlockchainIdentityBridge for agent linking.
    """

    def __init__(
        self,
        provider: Any | None = None,
        signer: Any | None = None,
        identity_bridge: Any | None = None,
    ) -> None:
        self._provider = provider
        self._signer = signer
        self._identity_bridge = identity_bridge
        self._anchor = ReceiptAnchor(provider=provider)

    async def anchor_receipt(self, receipt: Any) -> Any:
        """Anchor a DecisionReceipt on-chain and populate its settlement_status.

        This is the main entry point. Takes a receipt, computes its hash,
        anchors it (on-chain or locally), and sets the ``settlement_status``
        field on the receipt.

        Args:
            receipt: A DecisionReceipt instance.

        Returns:
            The same receipt with ``settlement_status`` populated.
        """
        receipt_hash = getattr(receipt, "artifact_hash", "")
        if not receipt_hash:
            # Compute hash if not already set
            receipt_hash = self._compute_receipt_hash(receipt)

        receipt_id = getattr(receipt, "receipt_id", "unknown")
        debate_id = getattr(receipt, "gauntlet_id", "")
        verdict = getattr(receipt, "verdict", "")

        metadata = {
            "receipt_id": receipt_id,
            "debate_id": debate_id,
            "verdict": verdict,
            "anchored_at": time.time(),
        }

        try:
            anchor_id = await self._anchor.anchor_receipt(
                receipt_hash=receipt_hash,
                metadata=metadata,
                signer=self._signer,
            )

            # Determine if this was local or on-chain
            is_local = anchor_id.startswith("local:")

            result = SettlementResult(
                anchored=True,
                anchor_id=anchor_id,
                chain_id=self._get_chain_id() if not is_local else None,
                local_only=is_local,
                receipt_hash=receipt_hash,
                timestamp=time.time(),
            )

            logger.info(
                "Receipt %s anchored: %s (local=%s)",
                receipt_id,
                anchor_id[:24],
                is_local,
            )

        except (RuntimeError, ConnectionError, ValueError, OSError, ImportError) as e:
            logger.warning("Receipt anchoring failed for %s: %s", receipt_id, e)
            result = SettlementResult(
                anchored=False,
                receipt_hash=receipt_hash,
                timestamp=time.time(),
                error=f"Anchoring failed: {type(e).__name__}",
            )

        # Populate the receipt's settlement_status field
        if hasattr(receipt, "settlement_status"):
            receipt.settlement_status = result.to_dict()

        return receipt

    async def push_agent_reputation(
        self,
        receipt: Any,
        agent_elo_ratings: dict[str, float] | None = None,
    ) -> int:
        """Push participating agents' reputation data based on receipt outcome.

        Reads agent names from the receipt's consensus_proof and pushes
        their ELO ratings (if available) to the ERC-8004 Reputation Registry
        via the identity bridge.

        Args:
            receipt: A DecisionReceipt instance.
            agent_elo_ratings: Optional dict mapping agent names to ELO ratings.

        Returns:
            Number of agents whose reputation was pushed.
        """
        if not agent_elo_ratings:
            return 0

        bridge = self._get_identity_bridge()
        if bridge is None:
            logger.debug("No identity bridge available, skipping reputation push")
            return 0

        pushed = 0
        consensus = getattr(receipt, "consensus_proof", None)
        if consensus is None:
            return 0

        supporting = getattr(consensus, "supporting_agents", []) or []
        dissenting = getattr(consensus, "dissenting_agents", []) or []
        all_agents = set(supporting + dissenting)

        for agent_name in all_agents:
            elo = agent_elo_ratings.get(agent_name)
            if elo is None:
                continue

            link = bridge.get_link(agent_name)
            if link is None:
                logger.debug("Agent %s not linked to blockchain identity", agent_name)
                continue

            try:
                adapter = self._get_erc8004_adapter()
                if adapter is not None and hasattr(adapter, "push_reputation"):
                    adapter.push_reputation(
                        agent_id=agent_name,
                        score=int(elo),
                        domain="debate_elo",
                        metadata={
                            "receipt_id": getattr(receipt, "receipt_id", ""),
                            "token_id": link.token_id,
                            "chain_id": link.chain_id,
                            "elo_rating": elo,
                        },
                    )
                    pushed += 1
                    logger.debug(
                        "Pushed reputation for agent %s (ELO=%.0f, token=%d)",
                        agent_name,
                        elo,
                        link.token_id,
                    )
            except (RuntimeError, ValueError, OSError, ImportError) as e:
                logger.warning("Failed to push reputation for %s: %s", agent_name, e)

        return pushed

    def get_settlement_status(self, receipt: Any) -> dict[str, Any]:
        """Get the settlement/anchoring status for a receipt.

        Checks both the receipt's stored settlement_status and the
        anchor's verification data.

        Args:
            receipt: A DecisionReceipt instance.

        Returns:
            Dictionary with settlement status details.
        """
        stored = getattr(receipt, "settlement_status", None)
        if stored is not None:
            return stored

        # Check if we can verify from the receipt hash
        receipt_hash = getattr(receipt, "artifact_hash", "")
        if receipt_hash:
            return self._anchor.verify_anchor(receipt_hash)

        return {
            "anchored": False,
            "receipt_hash": "",
            "error": "No artifact hash available",
        }

    def _compute_receipt_hash(self, receipt: Any) -> str:
        """Compute SHA-256 hash of a receipt's core content."""
        import hashlib
        import json

        data = {
            "receipt_id": getattr(receipt, "receipt_id", ""),
            "gauntlet_id": getattr(receipt, "gauntlet_id", ""),
            "input_hash": getattr(receipt, "input_hash", ""),
            "verdict": getattr(receipt, "verdict", ""),
            "confidence": getattr(receipt, "confidence", 0.0),
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_chain_id(self) -> int | None:
        """Get the configured chain ID, if any."""
        if self._provider is None:
            return None
        try:
            config = self._provider.get_config()
            return config.chain_id
        except (ValueError, AttributeError):
            return None

    def _get_identity_bridge(self) -> Any:
        """Get or create the identity bridge."""
        if self._identity_bridge is not None:
            return self._identity_bridge
        try:
            from aragora.blockchain.agent_registry import (
                get_blockchain_identity_bridge,
            )

            self._identity_bridge = get_blockchain_identity_bridge()
            return self._identity_bridge
        except ImportError:
            return None

    def _get_erc8004_adapter(self) -> Any:
        """Get the ERC8004 adapter for reputation pushes."""
        try:
            from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

            return ERC8004Adapter(
                provider=self._provider,
                signer=self._signer,
            )
        except ImportError:
            return None


# Module-level convenience functions


async def anchor_receipt(receipt: Any, **kwargs: Any) -> Any:
    """Convenience function to anchor a receipt with default settings.

    Args:
        receipt: A DecisionReceipt instance.
        **kwargs: Passed to ReceiptSettlementService constructor.

    Returns:
        The receipt with settlement_status populated.
    """
    service = ReceiptSettlementService(**kwargs)
    return await service.anchor_receipt(receipt)


__all__ = [
    "ReceiptSettlementService",
    "SettlementResult",
    "anchor_receipt",
]
