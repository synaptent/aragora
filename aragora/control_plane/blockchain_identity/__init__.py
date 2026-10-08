"""Compatibility re-export of :mod:`aragora.blockchain.agent_registry`.

The blockchain identity bridge moved next to its blockchain consumers (charter
CHR-X-041). Every name below is the identical object. The bridge singleton
(``_bridge``) lives only in the new module; patch or reset it there.
"""

from __future__ import annotations

from aragora.blockchain.agent_registry import (
    AgentBlockchainLink,
    BlockchainIdentityBridge,
    get_blockchain_identity_bridge,
)

__all__ = [
    "AgentBlockchainLink",
    "BlockchainIdentityBridge",
    "get_blockchain_identity_bridge",
]
