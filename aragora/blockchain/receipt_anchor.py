"""
On-chain receipt anchoring for decision receipts.

Writes a SHA-256 hash of a decision receipt to the blockchain, creating an
immutable timestamp proof that a decision was made at a specific time.

Works in two modes:
1. **On-chain mode**: When a Web3Provider and signer are available, submits
   the receipt hash as a validation request to the Validation Registry.
2. **Local mode**: When no provider is available, returns a local anchor
   record (useful for testing and offline operation).

Usage:
    from aragora.blockchain.receipt_anchor import ReceiptAnchor

    anchor = ReceiptAnchor(provider=provider)
    tx_hash = await anchor.anchor_receipt(
        receipt_hash="abc123...",
        metadata={"debate_id": "d1", "verdict": "approved"},
        signer=signer,
    )
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AnchorRecord:
    """Record of a receipt anchored on-chain or locally.

    Attributes:
        receipt_hash: SHA-256 hash of the decision receipt.
        tx_hash: Transaction hash if anchored on-chain, None for local anchors.
        chain_id: Chain ID where the anchor was submitted.
        timestamp: When the anchor was created.
        metadata: Additional metadata about the anchored receipt.
        local_only: True if this is a local-only anchor (no blockchain).
    """

    receipt_hash: str
    tx_hash: str | None = None
    chain_id: int | None = None
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    local_only: bool = False


class ReceiptAnchor:
    """Anchors decision receipt hashes on-chain.

    Creates immutable records proving that a decision was made at a specific
    time by writing the receipt hash to the blockchain's Validation Registry.

    Args:
        provider: Optional Web3Provider for on-chain anchoring.
        chain_id: Chain ID to use. Defaults to provider's default.
    """

    def __init__(
        self,
        provider: Any | None = None,
        chain_id: int | None = None,
    ) -> None:
        self._provider = provider
        self._chain_id = chain_id
        self._local_anchors: list[AnchorRecord] = []

    async def anchor_receipt(
        self,
        receipt_hash: str,
        metadata: dict[str, Any] | None = None,
        signer: Any | None = None,
    ) -> str:
        """Write a receipt hash to the blockchain.

        If no provider is configured, falls back to local anchoring.

        Args:
            receipt_hash: SHA-256 hex digest of the decision receipt.
            metadata: Optional metadata (debate_id, verdict, etc.).
            signer: WalletSigner for on-chain transactions.

        Returns:
            Transaction hash (on-chain) or local anchor ID (local mode).
        """
        meta = metadata or {}

        if self._provider is not None and signer is not None:
            return await self._anchor_on_chain(receipt_hash, meta, signer)

        return self._anchor_locally(receipt_hash, meta)

    async def _anchor_on_chain(
        self,
        receipt_hash: str,
        metadata: dict[str, Any],
        signer: Any,
    ) -> str:
        """Submit receipt hash to the Validation Registry on-chain."""
        from aragora.blockchain.contracts.validation import ValidationRegistryContract

        contract = ValidationRegistryContract(
            provider=self._provider,
            chain_id=self._chain_id,
        )

        # Encode the receipt hash as bytes32
        receipt_hash_bytes = (
            bytes.fromhex(receipt_hash)
            if len(receipt_hash) == 64
            else hashlib.sha256(receipt_hash.encode()).digest()
        )

        # Create a lightweight metadata URI token.
        metadata_uri = f"data:application/json;receipt={receipt_hash[:16]}"

        try:
            tx_hash = contract.request_validation(
                validator_address=signer.address,
                agent_id=0,  # Receipt anchor, not an agent validation
                request_uri=metadata_uri,
                request_hash=receipt_hash_bytes,
                signer=signer,
            )

            record = AnchorRecord(
                receipt_hash=receipt_hash,
                tx_hash=tx_hash,
                chain_id=self._chain_id,
                timestamp=time.time(),
                metadata=metadata,
                local_only=False,
            )
            self._local_anchors.append(record)

            logger.info(
                "Anchored receipt %s on-chain: tx=%s",
                receipt_hash[:16],
                tx_hash[:16] if tx_hash else "None",
            )
            return tx_hash

        except (RuntimeError, ConnectionError, ValueError, OSError) as exc:
            logger.warning("On-chain anchoring failed, falling back to local: %s", exc)
            return self._anchor_locally(receipt_hash, metadata)

    def _anchor_locally(
        self,
        receipt_hash: str,
        metadata: dict[str, Any],
    ) -> str:
        """Create a local anchor record when blockchain is unavailable."""
        # Generate a deterministic local anchor ID
        anchor_input = f"{receipt_hash}:{time.time()}"
        anchor_id = f"local:{hashlib.sha256(anchor_input.encode()).hexdigest()[:32]}"

        record = AnchorRecord(
            receipt_hash=receipt_hash,
            tx_hash=None,
            chain_id=None,
            timestamp=time.time(),
            metadata=metadata,
            local_only=True,
        )
        self._local_anchors.append(record)

        logger.info(
            "Locally anchored receipt %s as %s",
            receipt_hash[:16],
            anchor_id,
        )
        return anchor_id

    def get_anchors(self, receipt_hash: str | None = None) -> list[AnchorRecord]:
        """Retrieve anchor records, optionally filtered by receipt hash.

        Args:
            receipt_hash: If provided, filter to this receipt hash only.

        Returns:
            List of AnchorRecord instances.
        """
        if receipt_hash is None:
            return list(self._local_anchors)
        return [a for a in self._local_anchors if a.receipt_hash == receipt_hash]

    def verify_anchor(self, receipt_hash: str) -> dict[str, Any]:
        """Verify anchoring status for a given receipt hash.

        Looks up all anchors (on-chain and local) for the receipt hash and
        returns a verification summary.

        Args:
            receipt_hash: SHA-256 hex digest of the decision receipt.

        Returns:
            Dictionary with verification status::

                {
                    "anchored": True/False,
                    "receipt_hash": "...",
                    "anchors": [...],
                    "verified_at": <timestamp>,
                }

            Each anchor entry includes:
            - For on-chain: tx_hash, chain_id, block_number (if available), timestamp
            - For local: anchor_id, timestamp
        """
        anchors = self.get_anchors(receipt_hash)
        verified_at = time.time()

        if not anchors:
            return {
                "anchored": False,
                "receipt_hash": receipt_hash,
                "anchors": [],
                "verified_at": verified_at,
            }

        anchor_details: list[dict[str, Any]] = []
        for record in anchors:
            if record.local_only:
                anchor_details.append(
                    {
                        "type": "local",
                        "timestamp": record.timestamp,
                        "metadata": record.metadata,
                    }
                )
            else:
                detail: dict[str, Any] = {
                    "type": "on_chain",
                    "tx_hash": record.tx_hash,
                    "chain_id": record.chain_id,
                    "timestamp": record.timestamp,
                    "metadata": record.metadata,
                }
                # Include block_number if available in metadata
                if "block_number" in record.metadata:
                    detail["block_number"] = record.metadata["block_number"]
                anchor_details.append(detail)

        return {
            "anchored": True,
            "receipt_hash": receipt_hash,
            "anchors": anchor_details,
            "verified_at": verified_at,
        }


__all__ = [
    "AnchorRecord",
    "ReceiptAnchor",
]
