"""
Supermemory Connector (compatibility path).

The Supermemory client lives in :mod:`aragora.memory.supermemory`; this package
and its ``client``, ``config`` and ``privacy_filter`` submodules re-export the
same objects. The shared client returned by ``get_client`` lives only in
:mod:`aragora.memory.supermemory.client`; patch or reset it there.
"""

from aragora.memory.supermemory import (
    PrivacyFilter,
    PrivacyFilterConfig,
    SupermemoryClient,
    SupermemoryConfig,
    clear_client,
    get_client,
)

__all__ = [
    # Config
    "SupermemoryConfig",
    # Client
    "SupermemoryClient",
    "get_client",
    "clear_client",
    # Privacy
    "PrivacyFilter",
    "PrivacyFilterConfig",
]
