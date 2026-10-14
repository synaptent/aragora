"""Synthetic GitHub prediction market connector (compatibility path).

The adapter lives in :mod:`aragora.markets.synthetic_github`; this module
re-exports the same objects.
"""

from __future__ import annotations

from aragora.markets.synthetic_github import (
    DEFAULT_POSITION_CAP,
    SYNTHETIC_MARKETS_FLAG,
    SyntheticGitHubAdapter,
    SyntheticGitHubError,
    open_adapter,
    synthetic_markets_enabled,
)

__all__ = [
    "DEFAULT_POSITION_CAP",
    "SYNTHETIC_MARKETS_FLAG",
    "SyntheticGitHubAdapter",
    "SyntheticGitHubError",
    "open_adapter",
    "synthetic_markets_enabled",
]
